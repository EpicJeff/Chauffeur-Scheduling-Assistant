"""Batch equivalence, one-pass finalization and authenticated HTTP cost gates."""
from contextlib import ExitStack
from copy import deepcopy
import math
import os
from pathlib import Path
import tempfile
from time import perf_counter
import traceback
from unittest.mock import patch

# Service imports must never see the developer's real store. Keep all scratch
# files within this worktree, including helpers imported by the HTTP fixture.
SCRATCH = Path(__file__).resolve().parents[1] / '.tmp-batch-fix1'
SCRATCH.mkdir(exist_ok=True)
tempfile.tempdir = str(SCRATCH)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='batch_fix1_')
os.environ.pop('HA_BASE_URL', None)

from test_twin_server_speed import house, ts, OP
from services import twin_edit, twin_model, twin_model_ops as ops
from services import twin_fixtures as lights, twin_effect_fixtures as effects
from services import twin_plan, twin_terrain

ENTITY = 'light.batch_fix1'
LIGHT_SNAP = 'fixture:00000000-0000-4000-8000-000000000001'
LIGHT_ANCHOR = 'fixture:00000000-0000-4000-8000-000000000002'
LIGHT_AREA = 'fixture:00000000-0000-4000-8000-000000000003'
EFFECT_SNAP = 'effect:00000000-0000-4000-8000-000000000004'
EFFECT_POINT = 'effect:00000000-0000-4000-8000-000000000005'


def fixture_house():
    model = ts.current_model()
    building = model['buildings'][0]
    wall = next(w for w in building['walls'] if lights._host_edges(model, {'kind': 'wall', 'id': w['id']}))
    edge = lights._host_edges(model, {'kind': 'wall', 'id': wall['id']})[0]
    snap = {'host': {'kind': 'wall', 'id': wall['id']},
            'edge': {'from': edge[0][:2], 'to': edge[1][:2]}, 't0': .2, 't1': .8}
    path = lights.resolve_snap(model, snap)
    host = {'kind': 'building', 'id': building['id'], 'building': building['id']}
    frame = lights._anchor_frame(model, host)[1]
    local = [[2, 3, 4], [5, 3, 4]]
    anchored_path = [lights._anchor_transform(point, frame) for point in local]
    model['light_fixtures'] = {ENTITY: [
        {'id': LIGHT_SNAP, 'shape': 'line', 'ref': 'absolute', 'path': path, 'snap': snap},
        {'id': LIGHT_ANCHOR, 'shape': 'line', 'ref': 'absolute', 'path': anchored_path,
         'anchors': [{'host': host, 'local': point} for point in local]},
        {'id': LIGHT_AREA, 'shape': 'area', 'ref': 'absolute', 'at': [20, 20, 6], 'size_ft': [4, 2]},
    ]}
    model['effect_fixtures'] = [
        {'id': EFFECT_SNAP, 'type': 'waterfall', 'shape': 'line', 'ref': 'absolute',
         'path': deepcopy(path), 'snap': deepcopy(snap)},
        {'id': EFFECT_POINT, 'type': 'fountain', 'shape': 'point', 'ref': 'absolute', 'at': [25, 25, 1]},
    ]
    model, _ = twin_model.normalize(model)
    assert len(model['light_fixtures'][ENTITY]) == 3 and len(model['effect_fixtures']) == 2
    assert not any(f.get('orphaned') for f in model['light_fixtures'][ENTITY] + model['effect_fixtures'])
    return model


def selection_ops(model, kind):
    building, plants = model['buildings'][0], model['site']['planting'][:4]
    members = []
    if kind == 'move':
        members.append(dict(op='move_building', building=building['id'],
                            to=[building['position'][0] + .5, building['position'][1]]))
        members += [dict(op='move_site_item', list='planting', id=p['id'],
                         at=[p['at'][0] + .5, p['at'][1]]) for p in plants]
        members.append(dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_AREA, change={'at': [20.5, 20, 6]}))
        members.append(dict(op='update_effect_fixture', id=EFFECT_POINT, change={'at': [25.5, 25, 1]}))
    elif kind == 'turn':
        members.append(dict(op='rotate_building', building=building['id'], rotation=building.get('rotation', 0) + 5))
        angle = math.radians(5)
        for p in plants:
            members += [dict(op='set_object', list='planting', id=p['id'], properties={'rotation': p.get('rotation', 0) + 5}),
                        dict(op='move_site_item', list='planting', id=p['id'],
                             at=[p['at'][0]*math.cos(angle)-p['at'][1]*math.sin(angle),
                                 p['at'][0]*math.sin(angle)+p['at'][1]*math.cos(angle)])]
        members.append(dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_AREA, change={'rotation_deg': 5}))
    elif kind == 'scale':
        for p in plants:
            members += [dict(op='set_object', list='planting', id=p['id'], properties={'scale': p.get('scale', 1)*1.05}),
                        dict(op='move_site_item', list='planting', id=p['id'], at=[v*1.05 for v in p['at']])]
        members.append(dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_AREA, change={'size_ft': [4.2, 2.1]}))
        members.append(dict(op='update_effect_fixture', id=EFFECT_POINT, change={'size_max': 6.3}))
    else:
        members += [dict(op='delete_site_item', list='planting', id=p['id']) for p in plants]
        members.append(dict(op='delete_light_fixture', entity_id=ENTITY, id=LIGHT_AREA))
        members.append(dict(op='delete_effect_fixture', id=EFFECT_POINT))
    return members


def slow_members(model, members):
    result = deepcopy(model)
    for member in members:
        result, _ = twin_edit.apply_model(result, member, _normalized=(result, []))
    return result


def test_household_move_turn_scale_delete_equal_slow_with_real_fixtures():
    with house():
        original = fixture_house()
        unchanged = deepcopy(original)
        for kind in ('move', 'turn', 'scale', 'delete'):
            members = selection_ops(original, kind)
            wanted = slow_members(original, members)
            actual, _ = ops.apply(original, dict(op='batch', ops=members), _normalized=(original, []))
            assert actual == wanted, kind
            assert original == unchanged, kind
            if kind in ('move', 'turn'):
                # These references must genuinely follow changed hosts; an
                # equivalence assertion with inert fixture rows is insufficient.
                for fid in (LIGHT_SNAP, LIGHT_ANCHOR):
                    before = next(f for f in original['light_fixtures'][ENTITY] if f['id'] == fid)
                    after = next(f for f in actual['light_fixtures'][ENTITY] if f['id'] == fid)
                    assert after['path'] != before['path'] and not after.get('orphaned'), (kind, fid)
                assert actual['effect_fixtures'][0]['path'] != original['effect_fixtures'][0]['path']
                assert not actual['effect_fixtures'][0].get('orphaned')


def test_whole_model_finalization_runs_once_for_the_set():
    with house():
        original = fixture_house()
        targets = [(twin_plan, 'record_compose_overrides'), (lights, 'follow_host_moves'),
                   (lights, 'normalize'), (effects, 'normalize'), (twin_terrain, 'crossing_error')]
        with ExitStack() as stack:
            calls = [stack.enter_context(patch.object(owner, name, wraps=getattr(owner, name)))
                     for owner, name in targets]
            result, _ = ops.apply(original, dict(op='batch', ops=selection_ops(original, 'move')),
                                  _normalized=(original, []))
        assert result != original
        assert all(call.call_count == 1 for call in calls), [(name, call.call_count) for (_, name), call in zip(targets, calls)]


def test_creation_cannot_supply_indirect_targets_to_later_members():
    with house():
        original = fixture_house()
        building = original['buildings'][0]
        building['anchors'] = []
        bid, room = building['id'], building['rooms'][0]['id']
        original['site']['yard_rooms'] = []
        catalogue = {'available': False, 'devices': []}
        cases = [
            (dict(op='add_anchor', building=bid, kind='light', host={'ceiling': room, 'u': .5, 'v': .5}),
             dict(op='place_device', building=bid, device='fix1-device', anchor='anchor:1')),
            (dict(op='add_level', building=bid, name='Test attic', elevation=100, ceiling=7),
             dict(op='set_material', building=bid,
                  target={'level': ops._id(building, 'level'), 'role': 'interior_wall'}, material={'id': 'siding'})),
            (dict(op='add_site_shape', list='yard_rooms', name='Test garden',
                  polygon=[[0, 0], [10, 0], [10, 10], [0, 10]]),
             dict(op='place_device', device='fix1-yard-device',
                  host={'yard_room': 'yard_rooms:1', 'u': .5, 'v': .5})),
        ]
        unchanged = deepcopy(original)
        for create, use in cases:
            # Establish the concrete regression: sequential validation would
            # accept each reference after creation, but batch preflight must
            # resolve every indirect target on the original model.
            created, _ = twin_edit.apply_model(original, create, ha_catalogue=catalogue, _normalized=(original, []))
            twin_edit.apply_model(created, use, ha_catalogue=catalogue, _normalized=(created, []))
            try:
                twin_edit.apply_model(original, dict(op='batch', ops=[create, use]),
                                      ha_catalogue=catalogue, _normalized=(original, []))
            except ops.BatchRefused as exc:
                assert exc.member == 1 and exc.reason, (create, exc.member, exc.reason)
            else:
                raise AssertionError(('Earlier creation supplied a later target', create, use))
            assert original == unchanged


def test_malformed_member_containers_are_attributed_refusals():
    with house():
        original = fixture_house()
        bid = original['buildings'][0]['id']
        first = selection_ops(original, 'move')[1]
        for malformed in (dict(op='move_joints', building=bid, joints=None),
                          dict(op='accept', building=bid, pieces=3)):
            try:
                twin_edit.apply_model(original, dict(op='batch', ops=[first, malformed]), _normalized=(original, []))
            except ops.BatchRefused as exc:
                assert exc.member == 1 and exc.reason, (exc.member, exc.reason)
            else:
                raise AssertionError(('Malformed member accepted', malformed))


def test_fixture_updates_after_host_move_keep_snap_and_equal_slow_result():
    with house():
        original = fixture_house()
        move = selection_ops(original, 'move')[0]
        move['to'][0] += 2  # exceed the 0.5 ft snap matching tolerance
        members = [move,
                   dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_SNAP, change={'offset_ft': .1}),
                   dict(op='update_effect_fixture', id=EFFECT_SNAP, change={'offset_ft': .1})]
        wanted = slow_members(original, members)
        actual, _ = twin_edit.apply_model(original, dict(op='batch', ops=members), _normalized=(original, []))
        assert actual == wanted
        for rows, fid in ((actual['light_fixtures'][ENTITY], LIGHT_SNAP), (actual['effect_fixtures'], EFFECT_SNAP)):
            fixture = next(f for f in rows if f['id'] == fid)
            assert fixture.get('snap') and not fixture.get('orphaned'), fixture
            assert fixture['offset_ft'] == .1


def test_fixture_payload_references_cannot_use_an_earlier_created_level():
    with house():
        original = fixture_house()
        building = original['buildings'][0]
        bid, new_level = building['id'], ops._id(building, 'level')
        create = dict(op='add_level', building=bid, name='Fixture attic', elevation=100, ceiling=7)
        reference = dict(ref='floor', building=bid, level=new_level)
        new_light = dict(id='fixture:00000000-0000-4000-8000-000000000006', shape='point', at=[20, 20, 2], **reference)
        new_effect = dict(id='effect:00000000-0000-4000-8000-000000000007', type='fountain', shape='point', at=[20, 20, 2], **reference)
        anchor = {'host': {'kind': 'floor', 'id': 'floor:' + new_level, 'building': bid}, 'local': [2, 3, 4]}
        uses = [
            dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_AREA, change=reference),
            dict(op='update_effect_fixture', id=EFFECT_POINT, change=reference),
            dict(op='add_light_fixture', entity_id=ENTITY, fixture=new_light),
            dict(op='add_effect_fixture', fixture=new_effect),
            dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_ANCHOR,
                 change={'anchors': [anchor, {**anchor, 'local': [5, 3, 4]}]}),
        ]
        unchanged = deepcopy(original)
        for use in uses:
            created, _ = twin_edit.apply_model(original, create, _normalized=(original, []))
            twin_edit.apply_model(created, use, _normalized=(created, []))
            try:
                twin_edit.apply_model(original, dict(op='batch', ops=[create, use]), _normalized=(original, []))
            except ops.BatchRefused as exc:
                assert exc.member == 1 and exc.reason, (use, exc.member, exc.reason)
            else:
                raise AssertionError(('Earlier creation supplied a fixture reference', use))
            assert original == unchanged


def test_explicit_attachment_references_use_the_authored_intermediate_frame():
    with house():
        original = fixture_house()
        move_first = selection_ops(original, 'move')[0]
        move_first['to'][0] += 2
        intermediate, _ = twin_edit.apply_model(original, move_first, _normalized=(original, []))
        light = next(f for f in intermediate['light_fixtures'][ENTITY] if f['id'] == LIGHT_SNAP)
        effect = next(f for f in intermediate['effect_fixtures'] if f['id'] == EFFECT_SNAP)
        anchored = next(f for f in intermediate['light_fixtures'][ENTITY] if f['id'] == LIGHT_ANCHOR)
        anchors = deepcopy(anchored['anchors'])
        for anchor in anchors:
            anchor['local'][0] += .25
        frame = lights._anchor_frame(intermediate, anchors[0]['host'])[1]
        path = [lights._anchor_transform(anchor['local'], frame) for anchor in anchors]
        move_last = {**move_first, 'to': [move_first['to'][0] + 3, move_first['to'][1]]}
        members = [move_first,
                   dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_SNAP,
                        change={'snap': deepcopy(light['snap']), 'offset_ft': .1}),
                   dict(op='update_effect_fixture', id=EFFECT_SNAP,
                        change={'snap': deepcopy(effect['snap']), 'offset_ft': .1}),
                   dict(op='update_light_fixture', entity_id=ENTITY, id=LIGHT_ANCHOR,
                        change={'anchors': anchors, 'path': path}),
                   move_last]
        wanted = slow_members(original, members)
        actual, _ = twin_edit.apply_model(original, dict(op='batch', ops=members), _normalized=(original, []))
        assert actual == wanted
        for rows, fid, prior in ((actual['light_fixtures'][ENTITY], LIGHT_SNAP, light),
                                 (actual['effect_fixtures'], EFFECT_SNAP, effect)):
            fixture = next(f for f in rows if f['id'] == fid)
            assert not fixture.get('detached') and not fixture.get('orphaned'), fixture
            for end in ('from', 'to'):
                assert all(abs(fixture['snap']['edge'][end][i] - prior['snap']['edge'][end][i] - (3 if i == 0 else 0)) < 1e-8
                           for i in (0, 1)), (fid, fixture['snap'], prior['snap'])
        assert next(f for f in actual['light_fixtures'][ENTITY] if f['id'] == LIGHT_ANCHOR)['anchors'] == anchors


def test_final_terrain_refusal_names_first_failing_member():
    with house():
        original = fixture_house()
        # Start with a valid zero-height pad beneath a fixed building. Raising
        # that pad is a cross-model refusal deferred to batch finalization.
        building = original['buildings'][0]
        building['foundation'].update(mode='fixed', offset_ft=0)
        building['base'] = 0
        footprint = twin_terrain.footprint(building)
        original['site']['terraces'] = [dict(id='fix1-pad', polygon=footprint, height=0, blend=0)]
        original, _ = twin_model.normalize(original)
        assert twin_terrain.crossing_error(original) is None
        plant = original['site']['planting'][0]
        members = [dict(op='move_site_item', list='planting', id=plant['id'],
                        at=[plant['at'][0] + .5, plant['at'][1]]),
                   dict(op='update_pad', id='fix1-pad', height=2),
                   dict(op='set_object', list='planting', id=plant['id'], properties={'rotation': 5})]
        unchanged = deepcopy(original)
        try:
            ops.apply(original, dict(op='batch', ops=members), _normalized=(original, []))
        except ops.BatchRefused as exc:
            assert exc.member == 1 and 'fixed building' in exc.reason, (exc.member, exc.reason)
        else:
            raise AssertionError('A raised pad cannot cut through a fixed building')
        assert original == unchanged


def test_http_200_plant_move_and_turn_within_single_move_budget():
    with house() as c:
        expanded = ts.current_model()
        plants = expanded['site']['planting']
        for index in range(len(plants), 200):
            piece = deepcopy(plants[index % len(plants)])
            piece['id'] = f'fix1-cost-plant:{index}'
            plants.append(piece)
        ts.update_model(lambda _: expanded)

        def commit(operation):
            started = perf_counter()
            response = c.client.post(OP, headers=c.mum, json={'op': operation})
            elapsed = perf_counter() - started
            assert response.status_code == 200, response.text
            return elapsed

        def single():
            p = ts.current_model()['site']['planting'][0]
            return commit(dict(op='move_site_item', list='planting', id=p['id'], at=[p['at'][0]+.1, p['at'][1]]))

        # Warm the HTTP serializer/store caches, then use medians of three
        # same-run operations to avoid a single scheduler/fsync outlier.
        single()
        baseline = sorted(single() for _ in range(3))[1]
        measured = {}
        for kind in ('move', 'turn'):
            samples = []
            for _ in range(3):
                members = []
                for p in ts.current_model()['site']['planting']:
                    if kind == 'turn':
                        members.append(dict(op='set_object', list='planting', id=p['id'],
                                            properties={'rotation': p.get('rotation', 0)+1}))
                    angle = math.radians(1)
                    at = ([p['at'][0]*math.cos(angle)-p['at'][1]*math.sin(angle),
                           p['at'][0]*math.sin(angle)+p['at'][1]*math.cos(angle)] if kind == 'turn'
                          else [p['at'][0]+.1, p['at'][1]])
                    members.append(dict(op='move_site_item', list='planting', id=p['id'],
                                        at=at))
                samples.append(commit(dict(op='batch', ops=members)))
            measured[kind] = sorted(samples)[1]
        print('COST fix1 HTTP 200 plants: single={:.2f} ms, move={:.2f} ms ({:.3f}x), turn={:.2f} ms ({:.3f}x)'.format(
            baseline*1000, measured['move']*1000, measured['move']/baseline,
            measured['turn']*1000, measured['turn']/baseline))
        for kind, elapsed in measured.items():
            assert elapsed <= baseline*1.5, (kind, elapsed, baseline, elapsed/baseline)


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
