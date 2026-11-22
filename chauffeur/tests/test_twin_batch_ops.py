"""Atomic editor batches through the real authenticated HTTP operation route.

Run from chauffeur/: python tests/test_twin_batch_ops.py (HA_BASE_URL unset).
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter
import traceback
from unittest.mock import patch

from test_twin_server_speed import house, ts, storage, OP
from services import twin_edit, twin_model_ops as ops


@contextmanager
def small_house():
    with house() as c:
        plan = json.loads((Path(__file__).parent / 'fixtures/twin_edit_house.plan.json').read_text(encoding='utf8'))
        ts.push_round(plan, 'build')
        yield c


def post(c, members, headers=None):
    return c.client.post(OP, headers=headers or c.mum, json={'op': {'op': 'batch', 'ops': members}})


def rename(piece, value):
    return {'op': 'set', 'building': 'house', 'piece': piece, 'field': 'name', 'value': value}


def test_atomic_round_undo_and_redo():
    with small_house() as c:
        before, first = ts.current_model(), ts.current_id()
        rounds = len(ts.rounds())
        batch = [rename('room-1', 'Together'), rename('L1', 'Group floor')]
        with patch.object(ts, 'update_model', wraps=ts.update_model) as saves, patch.object(
                ts, 'lighting_fingerprint', wraps=ts.lighting_fingerprint) as lighting:
            response = post(c, batch)
        assert response.status_code == 200, response.text
        assert saves.call_count == 1 and lighting.call_count == 1, (saves.call_count, lighting.call_count)
        after = ts.current_model()
        assert after != before and len(ts.rounds()) == rounds + 1
        assert response.json()['round'] == ts.current_id()
        assert response.json()['lighting'] == ts.round_lighting(ts.current_id())
        assert after['buildings'][0]['rooms'][0]['name'] == 'Together'
        assert after['buildings'][0]['levels'][0]['name'] == 'Group floor'
        # History undo uses the existing revert route; redo replays the saved op.
        reverted = c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': first})
        assert reverted.status_code == 200, reverted.text
        assert ts.current_model() == before
        redone = post(c, batch)
        assert redone.status_code == 200, redone.text
        assert ts.current_model() == after


def test_refused_window_changes_nothing():
    with small_house() as c:
        before, rounds = ts.current_model(), ts.rounds()
        members = [rename('room-1', 'Must not land'), {
            'op': 'resize_opening', 'building': 'house', 'id': 'opening-1', 'width': 1000}]
        response = post(c, members)
        assert response.status_code == 400, response.text
        refused = response.json()
        assert refused['member'] == 1 and refused['reason'], refused
        assert 'opening-1' in refused['error'], refused
        assert ts.current_model() == before and ts.rounds() == rounds

        # Store-owned metadata validation must identify its member too.
        response = post(c, [rename('room-1', 'Must not land'),
                            dict(op='set', kind='building', building='house', id='house',
                                 field='name', value='')])
        assert response.status_code == 400 and response.json()['member'] == 1, response.text
        assert ts.current_model() == before and ts.rounds() == rounds


def test_prevalidation_uses_the_same_original_and_composition_is_checked():
    with small_house() as c:
        before, rounds = ts.current_model(), ts.rounds()
        # Creation by an earlier member cannot make a later member valid.
        new = {'op': 'add_site_item', 'list': 'furniture', 'asset': 'chair', 'at': [5, 5]}
        missing = {'op': 'move_site_item', 'list': 'furniture', 'id': 'furniture:1', 'at': [8, 8]}
        response = post(c, [new, missing])
        assert response.status_code == 400 and response.json()['member'] == 1, response.text
        assert ts.current_model() == before and ts.rounds() == rounds
        # Each resize fits the original opening. Together sill + head conflict.
        building = before['buildings'][0]
        window = next(o for o in building['openings'] if o['id'] == 'opening-1')
        members = [dict(op='resize_opening', building='house', id=window['id'], sill=4),
                   dict(op='resize_opening', building='house', id=window['id'], head=3)]
        for member in members:
            twin_edit.apply_model(before, member)
        response = post(c, members)
        assert response.status_code == 400 and response.json()['member'] == 1, response.text
        assert ts.current_model() == before and ts.rounds() == rounds


def test_singleton_matches_single_and_child_auth():
    with small_house() as c:
        initial = ts.current_id()
        member = rename('room-1', 'Same single operation')
        single = c.client.post(OP, headers=c.mum, json={'op': member})
        assert single.status_code == 200, single.text
        c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': initial})
        batch = post(c, [member])
        assert batch.status_code == 200, batch.text
        for key in ('model', 'plan', 'words', 'lighting'):
            assert single.json()[key] == batch.json()[key], key
        before, rounds = ts.current_model(), ts.rounds()
        child = {'X-Member-Token': storage.create_member_token('kid')}
        response = post(c, [rename('room-1', 'Denied')], child)
        assert response.status_code == 403, response.text
        assert ts.current_model() == before and ts.rounds() == rounds


def test_group_joints_move_once_and_validate_final_geometry():
    with small_house() as c:
        before = ts.current_model()
        building = before['buildings'][0]
        joints = [dict(joint=j['id'], to=[j['at'][0] + 100, j['at'][1] + 100]) for j in building['joints']]
        # A whole building wall set can move past its original neighbours;
        # intermediate single-corner positions must never be validated.
        response = post(c, [dict(op='move_joints', building=building['id'], joints=joints)])
        assert response.status_code == 200, response.text
        moved = {j['id']: j['at'] for j in ts.current_model()['buildings'][0]['joints']}
        for member in joints:
            assert moved[member['joint']] == member['to']
        prior, rounds = ts.current_model(), ts.rounds()
        wall = prior['buildings'][0]['walls'][0]
        positions = {j['id']: j['at'] for j in prior['buildings'][0]['joints']}
        response = post(c, [dict(op='move_joints', building=building['id'], joints=[
            dict(joint=wall['joints'][1], to=positions[wall['joints'][0]])])])
        assert response.status_code == 400 and response.json()['member'] == 0, response.text
        assert ts.current_model() == prior and ts.rounds() == rounds


def test_id_deletes_and_building_metadata():
    with house() as c:
        original = ts.current_model()
        plants = original['site']['planting'][:2]
        building = original['buildings'][0]
        members = [dict(op='delete_site_item', list='planting', id=p['id']) for p in plants]
        members.append(dict(op='set', kind='building', building=building['id'], id=building['id'],
                            field='name', value='Batch renamed house'))
        response = post(c, members)
        assert response.status_code == 200, response.text
        saved_ids = {p['id'] for p in ts.current_model()['site']['planting']}
        assert saved_ids == {p['id'] for p in original['site']['planting']} - {p['id'] for p in plants}
        assert ts.place()['buildings'][0]['name'] == 'Batch renamed house'


def test_cascade_delete_is_fulfilled_but_missing_original_refuses():
    with small_house() as c:
        before = ts.current_model()
        building = before['buildings'][0]
        room = next(r for r in building['rooms'] if r['id'] == 'room-1')
        positions = ops._positions(building)
        wall = next(w for w in building['walls'] if ops._bounds_wall(room, w, positions))
        response = post(c, [dict(op='delete', building='house', id=room['id']),
                            dict(op='delete', building='house', id=wall['id'])])
        assert response.status_code == 200, response.text
        assert all(w['id'] != wall['id'] for w in ts.current_model()['buildings'][0]['walls'])
        current, rounds = ts.current_model(), ts.rounds()
        response = post(c, [dict(op='delete', building='house', id=wall['id'])])
        assert response.status_code == 400 and response.json()['member'] == 0, response.text
        assert ts.current_model() == current and ts.rounds() == rounds


def test_site_object_id_survives_earlier_delete_without_index_fallback():
    with house() as c:
        plants = ts.current_model()['site']['planting']
        deleted, target = plants[:2]
        setter = dict(op='set_object', list='planting', index=1, id=target['id'], properties={'rotation': 45})
        response = post(c, [dict(op='delete_site_item', list='planting', id=deleted['id']), setter])
        assert response.status_code == 200, response.text
        saved = ts.current_model()
        assert next(p for p in saved['site']['planting'] if p['id'] == target['id'])['rotation'] == 45
        rounds = ts.rounds()
        missing = {**setter, 'id': deleted['id'], 'index': 0}
        response = post(c, [missing])
        assert response.status_code == 400 and response.json()['member'] == 0, response.text
        assert ts.current_model() == saved and ts.rounds() == rounds


def test_model_batch_uses_existing_ops_and_preserves_input():
    with small_house():
        original = ts.current_model()
        before = deepcopy(original)
        member = dict(op='set', building='house', id='room-1', field='name', value='Model API')
        single = ops.apply(original, member)
        batch = ops.apply(original, dict(op='batch', ops=[member]))
        assert batch == single
        assert original == before
        for members in ([], [None], [dict(op='batch', ops=[member])]):
            try:
                ops.apply(original, dict(op='batch', ops=members))
            except ops.Refused:
                pass
            else:
                raise AssertionError(('Malformed batch accepted', members))
        assert original == before


def test_site_singleton_matches_provenance_and_keeps_private_ownership():
    with house():
        original = ts.current_model()
        before = deepcopy(original)
        piece = original['site']['planting'][0]
        member = dict(op='move_site_item', list='planting', id=piece['id'],
                      at=[piece['at'][0] + 1, piece['at'][1]])
        single = ops.apply(original, member)
        batch = ops.apply(original, dict(op='batch', ops=[member]))
        assert single == batch
        if piece.get('by') == 'compose':
            assert batch[0]['site']['compose_overrides']['moved'][piece['id']] == member['at']
        batch[0]['buildings'][0]['name'] = 'Mutating the returned private model'
        batch[0]['site']['planting'][0]['at'][0] += 10
        assert original == before


def test_renamed_piece_can_be_deleted_later_in_same_batch():
    with small_house() as c:
        response = post(c, [rename('room-1', 'Temporary name'), {'op': 'delete', 'building': 'house', 'id': 'room-1'}])
        assert response.status_code == 200, response.text
        assert not any(p['id'] == 'room-1' for p in ts.current_model()['buildings'][0]['rooms'])


def test_each_registry_rename_is_validated_on_the_original():
    with house() as c:
        before, rounds = ts.current_model(), ts.rounds()
        bid = before['buildings'][0]['id']
        response = post(c, [dict(op='set', building=bid, piece=bid, field='name', value=''),
                            dict(op='set', building=bid, piece=bid, field='name', value='Valid replacement')])
        assert response.status_code == 400 and response.json()['member'] == 0, response.text
        assert ts.current_model() == before and ts.rounds() == rounds


def test_crossing_wall_set_translates_and_turns_rigidly():
    from test_twin_model import building, joint, wall, model
    from services import twin_model
    for turn in (False, True):
        b = building([joint('a', 0, 5), joint('b', 10, 5), joint('c', 5, 0), joint('d', 5, 10)],
                     [wall('h', 'a', 'b'), wall('v', 'c', 'd')], [])
        original, _ = twin_model.normalize(model(b))
        transform = (lambda p: [10 - p[1], p[0]]) if turn else (lambda p: [p[0] + 20, p[1]])
        moves = [dict(joint=j['id'], to=transform(j['at'])) for j in original['buildings'][0]['joints']]
        with house() as c:
            ts.update_model(lambda _: original)
            response = post(c, [dict(op='move_joints', building='main', joints=moves)])
            assert response.status_code == 200, response.text
            moved = ts.current_model()['buildings'][0]
            target = transform([5, 5])
            crossings = [j for j in moved['joints'] if abs(j['at'][0] - target[0]) < 1e-8 and abs(j['at'][1] - target[1]) < 1e-8]
            assert len(crossings) == 1, moved['joints']
            assert sum(crossings[0]['id'] in w['joints'] for w in moved['walls']) == 4


def test_household_cost():
    with house() as c:
        model = ts.current_model()
        plants = model['site']['planting']
        members = [dict(op='move_site_item', list='planting', id=p['id'],
                        at=[p['at'][0] + .5, p['at'][1]]) for p in plants[:200]]
        assert members
        started = perf_counter()
        response = post(c, members)
        elapsed = (perf_counter() - started) * 1000
        assert response.status_code == 200, response.text
        print(f'COST household batch: {len(members)} plants, HTTP commit={elapsed:.2f} ms')
        for member in members:
            item = next(p for p in ts.current_model()['site']['planting'] if p['id'] == member['id'])
            assert item['at'] == member['at']

        # Keep the real walls/roofs/yard and expand its existing plant records
        # to the required selection size; this measures commit, not drag frames.
        if len(plants) < 200:
            expanded = deepcopy(model)
            for index in range(len(plants), 200):
                piece = deepcopy(plants[index % len(plants)])
                piece['id'] = f'batch-cost-plant:{index}'
                expanded['site']['planting'].append(piece)
            ts.update_model(lambda _: expanded)
            members = [dict(op='move_site_item', list='planting', id=p['id'],
                            at=[p['at'][0] + .5, p['at'][1]]) for p in expanded['site']['planting']]
            started = perf_counter()
            response = post(c, members)
            elapsed = (perf_counter() - started) * 1000
            assert response.status_code == 200, response.text
            print(f'COST household with 200 plants: HTTP batch commit={elapsed:.2f} ms')


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
    print(f'{len(tests) - failures}/{len(tests)} passed')
    raise SystemExit(bool(failures))
