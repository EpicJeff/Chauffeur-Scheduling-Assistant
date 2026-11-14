"""Entity-owned light fixtures: real parent HTTP ops, isolated store and snap geometry."""
import copy
import json
import os
import sys
import tempfile
import traceback
import subprocess
from pathlib import Path
from uuid import uuid4

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_fixtures_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_twin_ha_routes import Ctx, LIVE, seed as house_seed, ts, twin_model
from test_twin_device_controls import controller

ENTITY = 'light.landscape'
OP = '/api/house/editor/op'


def fixture(shape='point', **values):
    fields = {
        'point': {'at': [10, 10, 1]},
        'spot': {'at': [10, 10, 6], 'aim': [12, 12, 0]},
        'line': {'path': [[10, 10, 2], [20, 10, 2]]},
        'area': {'at': [10, 10, 4], 'size_ft': [4, 2]},
    }
    return {'id': 'fixture:' + str(uuid4()), 'shape': shape, 'ref': 'absolute', **fields[shape], **values}


def seed():
    house_seed()
    def setup(m):
        m['site']['lot'] = [[-100, -100], [200, -100], [200, 200], [-100, 200]]
        m['site']['terraces'] = [{'id': 'pad1', 'polygon': [[10, 10], [20, 10], [20, 20], [10, 20]],
                                  'height': 2, 'edges': [{'edge': 'sharp', 'wall': {'material': 'stone'}} for _ in range(4)]}]
        m['site']['yard_rooms'] = [{'id': 'yard', 'name': 'Garden', 'ha_area': 'patio',
                                    'polygon': [[0, 0], [40, 0], [40, 40], [0, 40]]}]
        return m
    ts.update_model(setup)


def post(c, op, status=200, headers=None):
    before, count = ts.current_id(), len(ts.rounds())
    response = c.client.post(OP, headers=headers or c.mum, json={'op': op})
    assert response.status_code == status, response.text
    assert len(ts.rounds()) == count + (status == 200), 'each accepted op is one undoable round'
    if status != 200:
        assert ts.current_id() == before
        return response.json()
    return response.json()['model']


def add(c, f=None, entity=ENTITY):
    m = post(c, {'op': 'add_light_fixture', 'entity_id': entity, 'fixture': f or fixture()})
    return m['light_fixtures'][entity][-1]


def snapped(c, **values):
    return add(c, fixture('line', snap={'host': {'kind': 'retaining_wall', 'id': 'pad1'},
                                      'edge': {'from': [10, 10], 'to': [20, 10]}, 't0': .2, 't1': .8}, **values))


def test_add_update_delete_each_shape_round_trip():
    for shape in ('point', 'spot', 'line', 'area'):
        seed()
        with Ctx() as c:
            f = add(c, fixture(shape))
            assert f['shape'] == shape and f['id'].startswith('fixture:')
            if shape == 'spot':
                assert f['cone_deg'] == 90 and f['softness'] == .3
            if shape == 'line':
                assert f['width_in'] == .5 and f['facing'] == 'down' and f['detached'] is False
            added = ts.current_id()
            changes = {'point': {'at': [15, 15, 1]}, 'spot': {'aim': [15, 15, 0]},
                       'line': {'path': [[11, 10, 2], [21, 10, 2]]}, 'area': {'size_ft': [6, 3]}}
            m = post(c, {'op': 'update_light_fixture', 'entity_id': ENTITY, 'id': f['id'], 'change': {'share': 2, **changes[shape]}})
            assert m['light_fixtures'][ENTITY][0]['share'] == 2
            assert all(m['light_fixtures'][ENTITY][0][k] == v for k, v in changes[shape].items())
            m = post(c, {'op': 'set_light_output', 'entity_id': ENTITY, 'output_lm': 1200})
            assert m['light_fixtures_meta'][ENTITY] == {'output_lm': 1200}
            m = post(c, {'op': 'delete_light_fixture', 'entity_id': ENTITY, 'id': f['id']})
            assert ENTITY not in m.get('light_fixtures', {}), 'last deletion restores legacy resolution'
            response = c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': added})
            assert response.status_code == 200, response.text
            assert ts.current_model()['light_fixtures'][ENTITY] == [f]


def test_limits_refused():
    seed()
    with Ctx() as c:
        for f in (fixture('line', path=[[1, 1, 1]]), fixture('spot', cone_deg=200), fixture('line', width_in=3),
                  fixture('line', path=[[1, 1, 1]] * 65), fixture('spot', softness=1.1), fixture('area', size_ft=[0, 1]),
                  fixture(ref='floor'), fixture(share=-1), fixture('area', facing=[0, 0, 0]),
                  fixture('line', path=[[1, 1, 1], [300, 0, 1]])):
            post(c, {'op': 'add_light_fixture', 'entity_id': ENTITY, 'fixture': f}, 400)
        ts.update_model(lambda m: {**m, 'light_fixtures': {ENTITY: [fixture() for _ in range(64)]}})
        post(c, {'op': 'add_light_fixture', 'entity_id': ENTITY, 'fixture': fixture()}, 400)
        for value in (-1, True, '503'):
            post(c, {'op': 'set_light_output', 'entity_id': ENTITY, 'output_lm': value}, 400)
        post(c, {'op': 'add_light_fixture', 'entity_id': 'sensor.bad', 'fixture': fixture()}, 400)


def test_placement_ops_never_touch_fixtures():
    seed()
    with Ctx() as c:
        # Fixtures survive the same device being placed, dragged, raised and regrouped.
        controller(c, [(ENTITY, 'Landscape')])
        for _ in range(12):
            add(c)
        before = copy.deepcopy(ts.current_model()['light_fixtures'])
        for op in [
            {'op': 'place_device', 'device': 'dev-k-light', 'building': 'B1', 'host': {'ceiling': 'kitchen', 'u': .3, 'v': .4}, 'offset': 0},
            {'op': 'place_device', 'device': 'dev-k-light', 'building': 'B1', 'host': {'ceiling': 'kitchen', 'u': .7, 'v': .8}, 'offset': 0},
            {'op': 'place_device', 'device': 'dev-k-light', 'host': {'yard_room': 'yard', 'u': .2, 'v': .3}, 'offset': 1},
            {'op': 'place_device', 'device': 'dev-k-light', 'host': {'yard_room': 'yard', 'u': .4, 'v': .5}, 'offset': 3},
            {'op': 'set_ha_display', 'device': 'dev-k-light', 'show_as': 'entities'},
            {'op': 'set_ha_display', 'device': 'dev-k-light', 'show_as': 'controls'},
        ]:
            assert post(c, op)['light_fixtures'] == before


def test_snap_follows_host_move():
    seed()
    with Ctx() as c:
        f = snapped(c)
        poly = [[13, 10], [23, 10], [23, 20], [13, 20]]
        m = post(c, {'op': 'update_pad', 'id': 'pad1', 'polygon': poly})
        moved = m['light_fixtures'][ENTITY][0]
        assert moved['path'] == [[p[0] + 3, p[1], p[2]] for p in f['path']]
        assert moved['detached'] is False
        assert twin_model.normalize(m)[0] == m


def test_snap_survives_edge_renumbering():
    seed()
    with Ctx() as c:
        f = snapped(c)
        poly = [[10, 15], [10, 10], [20, 10], [20, 20], [10, 20]]
        m = post(c, {'op': 'update_pad', 'id': 'pad1', 'polygon': poly,
                     'edges': [{'edge': 'sharp', 'wall': {'material': 'stone'}} for _ in poly]})
        assert m['light_fixtures'][ENTITY][0]['path'] == f['path']
        assert m['light_fixtures'][ENTITY][0]['detached'] is False


def test_deleted_host_detaches_and_undo_reattaches():
    seed()
    with Ctx() as c:
        f = snapped(c)
        attached = ts.current_id()
        m = post(c, {'op': 'delete_pad', 'id': 'pad1'})
        detached = m['light_fixtures'][ENTITY][0]
        assert detached['path'] == f['path'] and detached['snap'] == f['snap'] and detached['detached'] is True
        assert c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': attached}).status_code == 200
        assert ts.current_model()['light_fixtures'][ENTITY] == [f]


def test_removed_edge_detaches_without_index_fallback():
    seed()
    with Ctx() as c:
        f = snapped(c)
        # Splitting the matched edge must not silently choose its first half.
        poly = [[10, 10], [15, 10], [20, 10], [20, 20], [10, 20]]
        m = post(c, {'op': 'update_pad', 'id': 'pad1', 'polygon': poly,
                     'edges': [{'edge': 'sharp', 'wall': {'material': 'stone'}} for _ in poly]})
        assert m['light_fixtures'][ENTITY][0]['path'] == f['path']
        assert m['light_fixtures'][ENTITY][0]['detached'] is True


def test_live_layout_carries_light_fixtures_and_signature():
    from services import twin_fixtures as tf
    seed()
    with Ctx() as c:
        f = add(c, fixture('spot'))
        body = c.client.get(LIVE, headers=c.mum).json()
        assert body['light_fixtures'][ENTITY] == [f]
        assert body['light_fixtures_meta'][ENTITY]['output_lm'] == 503
        sig = body['light_fixtures_signatures'][ENTITY]
        assert isinstance(sig, str) and sig
        assert tf.signature(ENTITY, [f]) == tf.signature(ENTITY, [dict(reversed(list(f.items())))])
        post(c, {'op': 'update_light_fixture', 'entity_id': ENTITY, 'id': f['id'], 'change': {'aim': [20, 10, 0]}})
        changed = c.client.get(LIVE, headers=c.panel).json()
        assert changed['light_fixtures_signatures'][ENTITY] != sig
        post(c, {'op': 'set_light_output', 'entity_id': ENTITY, 'output_lm': 700})
        assert c.client.get(LIVE, headers=c.mum).json()['light_fixtures_signatures'][ENTITY] != changed['light_fixtures_signatures'][ENTITY]
    with Ctx(available=False) as c:
        body = c.client.get(LIVE, headers=c.mum).json()
        assert body['available'] is False and body['light_fixtures'][ENTITY]


def test_parents_only():
    seed()
    with Ctx() as c:
        f = add(c)
        for op in ({'op': 'add_light_fixture', 'entity_id': ENTITY, 'fixture': fixture()},
                   {'op': 'update_light_fixture', 'entity_id': ENTITY, 'id': f['id'], 'change': {'share': 2}},
                   {'op': 'delete_light_fixture', 'entity_id': ENTITY, 'id': f['id']},
                   {'op': 'set_light_output', 'entity_id': ENTITY, 'output_lm': 900}):
            for headers in (c.kid, c.visitor, c.panel):
                post(c, op, 403, headers)


def test_legacy_model_without_fixtures_unchanged():
    seed()
    m = ts.current_model()
    out, notes = twin_model.normalize(m)
    assert out == m
    assert 'light_fixtures' not in out and 'light_fixtures_meta' not in out


def test_normalize_isolates_malformed_fixture_and_checks_floor_host():
    from services import twin_fixtures as tf
    seed()
    m = ts.current_model()
    good = fixture(ref='floor', building='B1', level='L1')
    m['light_fixtures'] = {ENTITY: [good, fixture('spot', cone_deg=200), fixture(ref='floor', building='gone', level='L1')]}
    out, notes = twin_model.normalize(m)
    assert out['light_fixtures'][ENTITY] == [tf.validate(good)] and len(notes) >= 2
    assert len(m['light_fixtures'][ENTITY]) == 3, 'normalization must not mutate input'
    bad = fixture('point', at=[float('nan'), 0, 0])
    try:
        tf.validate(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('nonfinite coordinate accepted')


def test_snap_endpoint_tolerance_reversal_and_all_host_kinds():
    from services import twin_fixtures as tf
    seed()
    m = ts.current_model()
    snap = {'host': {'kind': 'retaining_wall', 'id': 'pad1'}, 'edge': {'from': [20.4, 10], 'to': [10.4, 10]}, 't0': .2, 't1': .8}
    path = tf.resolve_snap(m, snap)
    assert path and abs(path[0][0] - 18) < 1e-6 and abs(path[1][0] - 12) < 1e-6
    snap['edge']['from'][0] = 20.51
    assert tf.resolve_snap(m, snap) is None
    m['site']['hardscape'] = [{'id': 'deck', 'polygon': [[1, 1], [5, 1], [5, 5], [1, 5]], 'elevation': 2}]
    m['site']['fence'] = [{'id': 'fence1', 'polyline': [[1, 1], [5, 1]], 'height': 6}]
    b = m['buildings'][0]
    b['stairs'] = [{'id': 'stair1', 'level': 'L1', 'from': [0, 0], 'to': [4, 0], 'width': 4, 'risers': 4, 'rise_to': 4}]
    for kind, host, ends in [('hardscape', 'deck', [[1, 1], [5, 1]]), ('fence', 'fence1', [[1, 1], [5, 1]]),
                             ('wall', 's1', [[100, 50], [100, 62]]), ('step', 'stair1', [[98, 51], [102, 51]])]:
        result = tf.resolve_snap(m, {'host': {'kind': kind, 'id': host}, 'edge': dict(zip(('from', 'to'), ends)), 't0': 0, 't1': 1})
        assert result and len(result) == 2 and all(len(p) == 3 for p in result), (kind, result)


def test_update_refuses_identity_changes_and_preserves_model_on_failure():
    seed()
    with Ctx() as c:
        f = add(c)
        for change in ({'id': fixture()['id']}, {'shape': 'area'}, {'typo': 1}, {'ref': 'floor', 'building': 'gone', 'level': 'L1'}):
            post(c, {'op': 'update_light_fixture', 'entity_id': ENTITY, 'id': f['id'], 'change': change}, 400)
        post(c, {'op': 'add_light_fixture', 'entity_id': ENTITY, 'fixture': f}, 400)
        post(c, {'op': 'delete_light_fixture', 'entity_id': ENTITY, 'id': 'missing'}, 400)


def test_concave_lot_checks_open_segments_and_vertical_runs():
    seed()
    # U-shaped lot: the closing diagonal crosses the notch, the open run does not.
    lot = [[0, 0], [10, 0], [10, 10], [7, 10], [7, 3], [3, 3], [3, 10], [0, 10]]
    ts.update_model(lambda m: {**m, 'site': {**m['site'], 'lot': lot}})
    with Ctx() as c:
        add(c, fixture('line', path=[[1, 8, 1], [1, 1, 1], [9, 1, 1], [9, 8, 1]]))
        post(c, {'op': 'add_light_fixture', 'entity_id': ENTITY,
                 'fixture': fixture('line', path=[[1, 8, 1], [9, 8, 1]])}, 400)
        add(c, fixture('line', path=[[0, 0, 0], [0, 0, 3]]))
        add(c, fixture(at=[0, 0, 1]))


def test_host_leaving_lot_keeps_detached_last_path():
    seed()
    with Ctx() as c:
        f = snapped(c)
        # Host edits must never discard the run, even when the host leaves the lot.
        m = post(c, {'op': 'update_pad', 'id': 'pad1', 'polygon': [[310, 10], [320, 10], [320, 20], [310, 20]]})
        row = m['light_fixtures'][ENTITY][0]
        assert row['path'] == f['path'] and row['detached'] is True


def test_hardscape_path_snap_is_on_boundary_not_centreline():
    from services import twin_fixtures as tf
    seed()
    m = ts.current_model()
    m['site']['hardscape'] = [{'id': 'walk', 'kind': 'path', 'points': [[0, 0], [10, 0]], 'width': 4}]
    snap = {'host': {'kind': 'hardscape', 'id': 'walk'}, 'edge': {'from': [0, 2], 'to': [10, 2]}, 't0': 0, 't1': 1}
    path = tf.resolve_snap(m, snap)
    assert path and [p[:2] for p in path] == [[0, 2], [10, 2]]


def test_wall_snap_follows_building_frame_without_moving_other_fixtures():
    seed()
    with Ctx() as c:
        point = add(c)
        wall = add(c, fixture('line', snap={'host': {'kind': 'wall', 'id': 's1'},
                                           'edge': {'from': [100, 50], 'to': [100, 62]}, 't0': 0, 't1': 1}))
        m = post(c, {'op': 'move_building', 'building': 'B1', 'to': [103, 50]})
        assert m['light_fixtures'][ENTITY][0] == point
        assert m['light_fixtures'][ENTITY][1]['path'] == [[p[0]+3, p[1], p[2]] for p in wall['path']]


def test_reference_heights_and_missing_floor_snap_are_preserved():
    from services import twin_fixtures as tf
    seed()
    m = ts.current_model()
    m['buildings'][0]['base'] = 1
    m['buildings'][0]['levels'][0]['elevation'] = 2
    with Ctx() as c:
        # Reference conversion of a cap at absolute z=2.
        ground = snapped(c, ref='ground')
        assert all(p[2] == 0 for p in ground['path'])
    snap = {'host': {'kind': 'wall', 'id': 's1'}, 'edge': {'from': [100, 50], 'to': [100, 62]}, 't0': 0, 't1': 1}
    f = fixture('line', snap=snap, ref='floor', building='B1', level='L1')
    m['light_fixtures'] = {ENTITY: [f]}
    tf.normalize(m, [])
    assert all(p[2] == 9 for p in m['light_fixtures'][ENTITY][0]['path'])
    old = copy.deepcopy(m['light_fixtures'][ENTITY][0]['path'])
    m['buildings'] = []
    tf.normalize(m, [])
    assert m['light_fixtures'][ENTITY][0]['path'] == old
    assert m['light_fixtures'][ENTITY][0]['detached'] is True


def test_flat_read_round_preserves_owned_fixtures_and_output():
    seed()
    with Ctx() as c:
        f = add(c)
        post(c, {'op': 'set_light_output', 'entity_id': ENTITY, 'output_lm': 1200})
        # Builds/flat edits normalize schema 2 before assembling against the current model.
        ts.update_current(lambda plan: plan, 'edit')
        m = ts.current_model()
        assert m['light_fixtures'][ENTITY] == [f]
        assert m['light_fixtures_meta'][ENTITY] == {'output_lm': 1200}


def test_path_boundary_math_matches_existing_render_geometry():
    from services import twin_fixtures as tf
    paths = [
        {'points': [[0, 0], [10, 0]], 'width': 4},
        {'points': [[0, 0], [10, 0], [10, 10]], 'width': 3, 'corner': 'mitred'},
        {'points': [[0, 0], [10, 0], [10, 10]], 'width': 3, 'corner': 'rounded', 'radius': 2},
        {'points': [[0, 0], [8, 2], [10, 10], [20, 15]], 'width': 3, 'smooth': True},
        {'points': [[0, 0], [10, 0], [0, 1]], 'width': 3},
    ]
    module = (Path(__file__).resolve().parents[1] / 'static/twin/path_shapes.js').as_uri()
    script = f'import {{pathOutline}} from {json.dumps(module)}; console.log(JSON.stringify({json.dumps(paths)}.map(pathOutline)));'
    result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    for path, expected in zip(paths, json.loads(result.stdout)):
        actual = tf._path_outline(path)
        assert len(actual) == len(expected)
        assert all(abs(x-y) < 1e-8 for a, b in zip(actual, expected) for x, y in zip(a, b))


def test_update_can_change_shape_while_keeping_stable_id():
    seed()
    with Ctx() as c:
        f = add(c, fixture('spot'))
        m = post(c, {'op': 'update_light_fixture', 'entity_id': ENTITY, 'id': f['id'],
                     'change': {'shape': 'line', 'path': [[1, 1, 1], [5, 1, 1]]}})
        line = m['light_fixtures'][ENTITY][0]
        assert line['shape'] == 'line' and line['id'] == f['id']
        assert not set(line) & {'at', 'aim', 'cone_deg', 'softness'}


def test_placement_does_not_rewrite_snap_endpoints_or_area_normal():
    seed()
    raw = fixture('line', snap={'host': {'kind': 'retaining_wall', 'id': 'pad1'},
                                'edge': {'from': [10, 10], 'to': [20, 10]}, 't0': 0, 't1': 1})
    ts.update_model(lambda m: {**m, 'light_fixtures': {ENTITY: [raw, fixture('area', facing=[5, 8, 11])]}})
    before = json.dumps(ts.current_model()['light_fixtures'], sort_keys=True)
    with Ctx() as c:
        m = post(c, {'op': 'place_device', 'device': 'dev-k-light', 'building': 'B1',
                     'host': {'ceiling': 'kitchen', 'u': .4, 'v': .4}, 'offset': 0})
        assert json.dumps(m['light_fixtures'], sort_keys=True) == before


def test_output_and_share_do_not_inherit_the_coordinate_limit():
    seed()
    with Ctx() as c:
        f = add(c, fixture(share=200000))
        assert f['share'] == 200000
        m = post(c, {'op': 'set_light_output', 'entity_id': ENTITY, 'output_lm': 200000})
        assert m['light_fixtures_meta'][ENTITY]['output_lm'] == 200000


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=6)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
