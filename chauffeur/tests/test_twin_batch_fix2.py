"""Round-two batch regressions on the real household and HTTP route."""
from copy import deepcopy
import math
import os
from pathlib import Path
import tempfile
import traceback
from unittest.mock import patch

SCRATCH = Path(__file__).resolve().parents[1] / '.tmp-batch-fix2'
SCRATCH.mkdir(exist_ok=True)
tempfile.tempdir = str(SCRATCH)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='batch_fix2_')
os.environ.pop('HA_BASE_URL', None)

from test_twin_batch_fix1 import (fixture_house, slow_members, ENTITY, LIGHT_AREA, LIGHT_ANCHOR,
                                 test_malformed_member_containers_are_attributed_refusals as malformed_members)
from test_twin_server_speed import house, ts, OP
from services import twin_edit, twin_model, twin_model_ops as ops, twin_model_graph as graph


def plant_move(model):
    plant = model['site']['planting'][0]
    return dict(op='move_site_item', list='planting', id=plant['id'], at=[plant['at'][0]+.5, plant['at'][1]])


def post(c, members):
    return c.client.post(OP, headers=c.mum, json={'op': dict(op='batch', ops=members)})


def transform_set(model, level, turn):
    building = next(b for b in model['buildings'] if b['id'] == 'main-house')
    walls = [w for w in building['walls'] if w.get('state') != 'ghost' and (level is None or w['level'] == level)]
    ids = list(dict.fromkeys(j for wall in walls for j in wall['joints']))
    positions = {j['id']: j['at'] for j in building['joints']}
    angle = math.radians(3)
    transform = (lambda p: [p[0]*math.cos(angle)-p[1]*math.sin(angle),
                            p[0]*math.sin(angle)+p[1]*math.cos(angle)]) if turn else (lambda p: [p[0]+.5, p[1]])
    member = dict(op='move_joints', building=building['id'],
                  joints=[dict(joint=jid, to=transform(positions[jid])) for jid in ids])
    return building, ids, member, transform


def assert_promoted_targets(original, selected, actual, transform):
    # split_crossings is the geometry reader's canonical interpretation of
    # short read overshoots. A pruned original endpoint maps to its nearby
    # surviving crossing; every other selected corner keeps its own point.
    expected = {}
    for level in original['levels']:
        lid = level['id']
        walls = [w for w in original['walls'] if w.get('state') != 'ghost' and w['level'] == lid]
        positions = {j['id']: j['at'] for j in original['joints'] if j['level'] == lid}
        derived, split = graph.split_crossings(positions, walls)
        referenced = {jid for w in split for jid in w['joints']}
        for jid in selected:
            if jid not in positions:
                continue
            mapped = jid if jid in referenced else min(referenced, key=lambda key: math.dist(derived[key], positions[jid]))
            if mapped != jid:
                assert math.dist(derived[mapped], positions[jid]) < 1, (jid, mapped)
            expected[jid] = (lid, transform(derived[mapped]))
    assert len(expected) == len(selected)
    for jid, (lid, wanted) in expected.items():
        assert any(j['level'] == lid and math.dist(j['at'], wanted) < 1e-7 for j in actual['joints']), (jid, lid, wanted)


def test_household_l2_and_whole_house_translate_and_turn_over_http():
    with house() as c:
        original = ts.current_model()
        for level in ('L2', None):
            for turn in (False, True):
                ts.update_model(lambda _: deepcopy(original))
                current = ts.current_model()
                building, selected, movement, transform = transform_set(current, level, turn)
                assert len(selected) == (33 if level == 'L2' else 77), (level, len(selected))
                members = [movement, plant_move(current)]  # exercise composed in-place path
                response = post(c, members)
                assert response.status_code == 200, (level, turn, response.text)
                actual = response.json()['model']
                expected = slow_members(current, members)
                fast, _ = twin_edit.apply_model(current, dict(op='batch', ops=members), _normalized=(current, []))
                assert fast == expected, (level, turn, 'operation composition')
                # update_model publishes a normalized result; in particular,
                # person-owned pieces lose their old draft-step provenance.
                published, _ = twin_model.normalize(expected)
                assert actual == published, (level, turn, 'published HTTP model')
                moved = next(b for b in actual['buildings'] if b['id'] == building['id'])
                assert_promoted_targets(building, selected, moved, transform)


def test_later_building_delete_keeps_edited_floor_fixture_as_orphan():
    with house() as c:
        ts.update_model(lambda _: fixture_house())
        original = ts.current_model()
        poolhouse = next(b for b in original['buildings'] if b['id'] == 'pool-house')
        members = [dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_AREA,
                        change={'ref': 'floor', 'building': poolhouse['id'], 'level': poolhouse['levels'][0]['id'],
                                'at': [poolhouse['position'][0]+5, poolhouse['position'][1]+5, 1]}),
                   plant_move(original), dict(op='delete', building=poolhouse['id'], piece=poolhouse['id'])]
        wanted, _ = twin_model.normalize(slow_members(original, members))
        fast, _ = twin_edit.apply_model(original, dict(op='batch', ops=members), _normalized=(original, []))
        # Legacy building deletion returns before fixture normalization. The
        # observable saved model marks retained floor references as orphans.
        assert twin_model.normalize(fast)[0] == wanted
        response = post(c, members)
        assert response.status_code == 200, response.text
        actual = response.json()['model']
        assert actual == wanted
        fixture = next(f for f in actual['light_fixtures'][ENTITY] if f['id'] == LIGHT_AREA)
        assert fixture.get('orphaned') and fixture['ref'] == 'floor' and fixture['building'] == 'pool-house'
        assert not any(b['id'] == 'pool-house' for b in actual['buildings'])


def test_end_only_fixture_refusal_names_last_fixture_author():
    with house() as c:
        ts.update_model(lambda _: fixture_house())
        original, rounds = ts.current_model(), ts.rounds()
        building = original['buildings'][0]
        members = [dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_ANCHOR, change={'width_in': .75}),
                   dict(op='move_building', building=building['id'], to=[1000, 1000]), plant_move(original)]
        # The member validator accepted its authored path. Only the deferred
        # host-follow/lot check discovers that this anchored run left the lot.
        slow = slow_members(original, members)
        moved = next(f for f in slow['light_fixtures'][ENTITY] if f['id'] == LIGHT_ANCHOR)
        assert moved.get('orphaned') and moved['path'] != original['light_fixtures'][ENTITY][1]['path']
        response = post(c, members)
        assert response.status_code == 400, response.text
        body = response.json()
        assert body['member'] == 0 and 'lot' in body['reason'].lower(), body
        assert ts.current_model() == original and ts.rounds() == rounds
        # A second explicit edit becomes the author; neither the host move nor
        # the unrelated trailing plant is allowed to steal the attribution.
        members.insert(1, dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_ANCHOR,
                               change={'width_in': 1}))
        response = post(c, members)
        assert response.status_code == 400, response.text
        assert response.json()['member'] == 1, response.json()
        assert ts.current_model() == original and ts.rounds() == rounds


def test_preflight_programming_errors_propagate_without_user_refusal():
    with house():
        original = ts.current_model()
        original['site']['terraces'] = [dict(id='fix2-pad', polygon=[[0, 0], [1, 0], [1, 1], [0, 1]], height=0)]
        members = [plant_move(original), dict(op='update_pad', id='fix2-pad', height=0)]
        for error in (TypeError('injected preflight bug'), KeyError('injected preflight bug')):
            with patch.object(ops, '_find', side_effect=error):
                try:
                    twin_edit.apply_model(original, dict(op='batch', ops=members), _normalized=(original, []))
                except type(error) as exc:
                    assert exc is error
                else:
                    raise AssertionError(('Programming error was converted to refusal', type(error)))


def test_member_programming_errors_propagate_and_validator_refusals_are_attributed():
    with house():
        original = ts.current_model()
        members = [plant_move(original), {**plant_move(original), 'at': [2, 2]}]
        for error in (TypeError('injected validator bug'), KeyError('injected validator bug')):
            with patch.object(ops, '_apply', side_effect=error):
                try:
                    twin_edit.apply_model(original, dict(op='batch', ops=members), _normalized=(original, []))
                except type(error) as exc:
                    assert exc is error
                else:
                    raise AssertionError(('Programming error was converted to refusal', type(error)))
        for error in (ops.Refused('intentional refusal'), ValueError('intentional fixture validator refusal')):
            with patch.object(ops, '_apply', side_effect=error):
                try:
                    twin_edit.apply_model(original, dict(op='batch', ops=members), _normalized=(original, []))
                except ops.BatchRefused as exc:
                    assert exc.member == 0 and exc.reason == str(error)
                else:
                    raise AssertionError('A validator refusal lost its member attribution')
    malformed_members()


def test_malformed_lookup_keys_remain_indexed_refusals():
    with house() as c:
        original, rounds = ts.current_model(), ts.rounds()
        bad_members = [
            dict(op='move_building', building=[], to=[1, 0]),
            dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_AREA,
                 change=dict(ref='floor', building=[], level='L1')),
            dict(op='move_site_item', list=[], index=0, at=[1, 0]),
            dict(op='update_light_fixture', entity_id=[], id=LIGHT_AREA, change={}),
        ]
        for member in bad_members:
            response = post(c, [plant_move(original), member])
            assert response.status_code == 400, response.text
            assert response.json()['member'] == 1, response.json()
            assert ts.current_model() == original and ts.rounds() == rounds


def test_http_programming_errors_are_logged_server_failures():
    from fastapi.testclient import TestClient
    import main
    with house() as c:
        original, rounds = ts.current_model(), ts.rounds()
        members = [plant_move(original), {**plant_move(original), 'at': [2, 2]}]
        client = TestClient(c.client.app, raise_server_exceptions=False)
        try:
            for error in (TypeError('injected HTTP validator bug'), KeyError('injected HTTP validator bug')):
                with patch.object(ops, '_apply', side_effect=error), patch.object(main.logger, 'exception') as logged:
                    response = client.post(OP, headers=c.mum, json={'op': dict(op='batch', ops=members)})
                assert response.status_code == 500, (type(error), response.status_code, response.text)
                logged.assert_called_once_with('House editor operation failed')
                assert ts.current_model() == original and ts.rounds() == rounds
        finally:
            client.close()


if __name__ == '__main__':
    tests = [value for name, value in list(globals().items()) if name.startswith('test_') and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print('PASS', test.__name__)
        except Exception:
            failures += 1
            print('FAIL', test.__name__)
            traceback.print_exc()
    print(f'{len(tests)-failures}/{len(tests)} passed')
    raise SystemExit(bool(failures))
