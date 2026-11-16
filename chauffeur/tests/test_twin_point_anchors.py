"""Point anchors and vertical offsets: validation, shared follow pass and HTTP undo."""
import copy
import math
import os
from pathlib import Path
import sys
import tempfile
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT.parent / '.codex-task-point-anchors-tmp'
SCRATCH.mkdir(exist_ok=True)
tempfile.tempdir = str(SCRATCH)
DATA = SCRATCH / ('point-anchors-' + str(uuid4()))
DATA.mkdir()
os.environ['CHAUFFEUR_DATA_DIR'] = str(DATA)
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from services import twin_effect_fixtures as effects, twin_fixtures as lights
from test_twin_ha_routes import Ctx, _house, seed as house_seed, ts

ENTITY = 'light.landscape'


def fixture(effect=False, shape='line', **changes):
    geometry = {'path': [[10, 10, 2], [20, 10, 2]]} if shape == 'line' else {'at': [10, 10, 2]}
    return {'id': ('effect:' if effect else 'fixture:') + str(uuid4()),
            **({'type': 'waterfall' if shape == 'line' else 'fountain'} if effect else {}),
            'shape': shape, 'ref': 'absolute', **geometry, **changes}


def anchor(kind='terrace', hid='pad1', local=(0, 0, 0), building=None):
    return {'host': {'kind': kind, 'id': hid, **({'building': building} if building else {})}, 'local': list(local)}


def refused(module, value):
    try:
        module.validate(value)
    except ValueError as exc:
        assert str(exc), 'Invalid input needs a clear validation error.'
    else:
        raise AssertionError('Accepted invalid fixture: ' + repr(value))


def model_with_anchors(host, path, locals=None):
    model = _house(position=(10, 20), rotation=0)
    model['buildings'][0]['base'] = 2
    anchors = [anchor(**host, local=p) for p in (locals or path)]
    model['light_fixtures'] = {ENTITY: [lights.validate(fixture(path=path, anchors=anchors, offset_ft=-1))]}
    model['effect_fixtures'] = [effects.validate(fixture(True, path=path, anchors=anchors, offset_ft=-1))]
    return model


def rows(model):
    return [model['light_fixtures'][ENTITY][0], model['effect_fixtures'][0]]


def set_anchor_locals(model):
    """Author synthetic fixture anchors in the host's east/north/up frame."""
    for row in rows(model):
        for point, binding in zip(row['path'], row['anchors']):
            if binding is None:
                continue
            frame = lights._anchor_frame(model, binding['host'])
            assert frame is not None, binding['host']
            absolute = [*point[:2], point[2] + lights._anchor_reference(model, row, point)]
            binding['local'] = lights._anchor_transform(absolute, frame[1], inverse=True)


def assert_path(actual, expected):
    assert len(actual) == len(expected), (actual, expected)
    assert all(math.dist(a, b) < 1e-7 for a, b in zip(actual, expected)), (actual, expected)


def test_anchor_validation_closed_hosts_and_parallel_points():
    kinds = ('building', 'wall', 'roof', 'floor', 'room', 'porch', 'stair', 'opening', 'item',
             'fixture', 'light', 'anchor', 'solar_zone', 'retaining_wall', 'terrace', 'hardscape',
             'fence', 'pool', 'spa', 'ledge', 'steps')
    for effect, module in ((False, lights), (True, effects)):
        for kind in kinds:
            raw = fixture(effect, anchors=[anchor(kind), None])
            original = copy.deepcopy(raw)
            value = module.validate(raw)
            assert value['anchors'] == raw['anchors'] and raw == original
            assert module.validate(value) == value
        invalid = (None, {}, [], [None], [None, None, None], [True, None],
                   [{'host': {'kind': 'unknown', 'id': 'x'}, 'local': [0, 0, 0]}, None],
                   [anchor(hid=5), None], [anchor(hid=''), None],
                   [{'host': {'kind': [], 'id': 'x'}, 'local': [0, 0, 0]}, None],
                   [{'host': {'kind': 'wall', 'id': 'x', 'building': 4}, 'local': [0, 0, 0]}, None],
                   [{'host': {'kind': 'wall', 'id': 'x'}, 'local': [0, 0]}, None],
                   [{'host': {'kind': 'wall', 'id': 'x'}, 'local': [True, 0, 0]}, None],
                   [{'host': {'kind': 'wall', 'id': 'x'}, 'local': [float('nan'), 0, 0]}, None],
                   [{'host': {'kind': 'wall', 'id': 'x'}, 'local': [0, float('inf'), 0]}, None],
                   [{**anchor(), 'unknown': 1}, None],
                   [{**anchor(), 'host': {**anchor()['host'], 'unknown': 1}}, None])
        for anchors in invalid:
            refused(module, fixture(effect, anchors=anchors))
        refused(module, fixture(effect, shape='point', anchors=[anchor()]))
        refused(module, fixture(effect, anchors=[None, None], snap={
            'host': {'kind': 'retaining_wall', 'id': 'pad1'},
            'edge': {'from': [10, 10], 'to': [20, 10]}}))


def test_offset_validation_keeps_authored_geometry_and_default():
    for effect, module in ((False, lights), (True, effects)):
        for shape in ('line', 'point'):
            raw = fixture(effect, shape)
            assert module.validate(raw).get('offset_ft', 0) == 0
            for offset in (-50, -1.5, 0, 2.25, 50):
                value = module.validate({**raw, 'offset_ft': offset})
                assert value['offset_ft'] == offset
                key = 'path' if shape == 'line' else 'at'
                assert value[key] == raw[key]
            for offset in (-50.001, 50.001, True, False, None, '1', float('nan'), float('inf'), -float('inf')):
                refused(module, {**raw, 'offset_ft': offset})


def test_building_translation_base_and_rotation_carry_both_kinds():
    path = [[11, 20, 7], [14, 20, 7]]
    before = model_with_anchors({'kind': 'wall', 'hid': 's1', 'building': 'B1'}, path,
                                [[1, 0, 5], [4, 0, 5]])
    set_anchor_locals(before)
    after = copy.deepcopy(before)
    after['buildings'][0].update(position=[15, 17], base=5)
    lights.follow_host_moves(before, after)
    for row in rows(after):
        assert_path(row['path'], [[16, 17, 10], [19, 17, 10]])
        assert row['anchors'] == rows(before)[0]['anchors'] and row['offset_ft'] == -1
    rotated = copy.deepcopy(after)
    rotated['buildings'][0]['rotation'] = 90
    lights.follow_host_moves(after, rotated)
    for row in rows(rotated):
        assert_path(row['path'], [[15, 18, 10], [15, 21, 10]])
    assert rows(before)[0]['path'] == path, 'Following must not mutate the previous round.'


def test_authored_local_controls_follow_and_offset_stays_separate():
    before = model_with_anchors({'kind': 'wall', 'hid': 's1', 'building': 'B1'},
                                [[11, 20, 7], [14, 20, 7]], [[2, 1, 5], [4, 0, 5]])
    after = copy.deepcopy(before)
    after['buildings'][0].update(position=[15, 17], base=5)
    lights.follow_host_moves(before, after)
    for row in rows(after):
        assert_path(row['path'], [[17, 18, 10], [19, 17, 10]])
        assert row['anchors'][0]['local'] == [2, 1, 5]
        assert row['offset_ft'] == -1
    assert rows(before)[0]['path'] == [[11, 20, 7], [14, 20, 7]]


def test_floor_reference_and_auto_foundation_follow_rendered_height():
    before = model_with_anchors({'kind': 'wall', 'hid': 's1', 'building': 'B1'},
                                [[11, 20, 5], [14, 20, 5]])
    for row in rows(before):
        row.update(ref='floor', building='B1', level='L1')
    set_anchor_locals(before)
    after = copy.deepcopy(before)
    after['buildings'][0].update(position=[15, 17], base=5)
    lights.follow_host_moves(before, after)
    for row in rows(after):
        assert_path(row['path'], [[16, 17, 5], [19, 17, 5]])
    reshaped = copy.deepcopy(before)
    reshaped['buildings'][0]['base'] = 5
    reshaped['buildings'][0]['joints'][0]['at'][0] += 2
    lights.follow_host_moves(before, reshaped)
    for row in rows(reshaped):
        assert_path(row['path'], [[11, 20, 2], [14, 20, 2]])
        assert row['anchors'] == [None, None]
    auto = model_with_anchors({'kind': 'wall', 'hid': 's1', 'building': 'B1'},
                              [[11, 20, 5], [14, 20, 5]])
    auto['buildings'][0].update(base=0, foundation={'mode': 'auto', 'offset_ft': 0})
    auto['site']['terraces'] = [{'id': 'higher', 'height': 6,
        'polygon': [[50, 0], [120, 0], [120, 100], [50, 100]]}]
    set_anchor_locals(auto)
    higher = copy.deepcopy(auto)
    higher['buildings'][0]['position'] = [60, 20]
    lights.follow_host_moves(auto, higher)
    for row in rows(higher):
        assert_path(row['path'], [[61, 20, 11], [64, 20, 11]])
        assert all(row['anchors'])


def test_deleted_floor_or_building_preserves_last_absolute_height():
    before = model_with_anchors({'kind': 'wall', 'hid': 's1', 'building': 'B1'},
                                [[11, 20, 3], [14, 20, 3]])
    before['buildings'][0]['levels'][0]['elevation'] = 10
    for row in rows(before):
        row.update(ref='floor', building='B1', level='L1')
    set_anchor_locals(before)
    for delete_building in (False, True):
        after = copy.deepcopy(before)
        if delete_building:
            after['buildings'] = []
        else:
            after['buildings'][0]['levels'] = []
        lights.follow_host_moves(before, after)
        lights.normalize(after, [])
        effects.normalize(after, [])
        for row in rows(after):
            assert_path(row['path'], [[11, 20, 15], [14, 20, 15]])
            assert row['anchors'] == [None, None]
            assert row['orphaned']


def test_dependent_opening_and_pool_depth_reshapes_clear_anchors():
    before = model_with_anchors({'kind': 'wall', 'hid': 's1', 'building': 'B1'},
                                [[11, 20, 5], [14, 20, 5]])
    before['buildings'][0]['openings'] = [{'id': 'door', 'wall': 's1', 'width': 3}]
    set_anchor_locals(before)
    after = copy.deepcopy(before)
    after['buildings'][0]['openings'][0]['width'] = 6
    lights.follow_host_moves(before, after)
    for row in rows(after):
        assert row['anchors'] == [None, None]
        assert row['path'] == rows(before)[0]['path']
    for kind in ('spa', 'ledge', 'steps'):
        before = model_with_anchors({'kind': kind, 'hid': 'feature'}, [[10, 10, -3], [20, 10, -3]])
        before['site']['pool'] = {'id': 'pool', 'depth': 5, 'polygon': [[0, 0], [30, 0], [30, 30], [0, 30]],
                                 'features': [{'id': 'feature', 'kind': kind, 'polygon': [[10, 10], [20, 10], [20, 20], [10, 20]]}]}
        set_anchor_locals(before)
        after = copy.deepcopy(before)
        after['site']['pool']['depth'] = 8
        lights.follow_host_moves(before, after)
        for row in rows(after):
            assert row['anchors'] == [None, None]
            assert row['path'] == rows(before)[0]['path']
        translated = copy.deepcopy(before)
        pool = translated['site']['pool']
        for obj in [pool, *pool['features']]:
            obj['polygon'] = [[p[0]+5, p[1]+3] for p in obj['polygon']]
        lights.follow_host_moves(before, translated)
        for row in rows(translated):
            assert_path(row['path'], [[15, 13, -3], [25, 13, -3]])
            assert all(row['anchors'])


def test_item_position_rotation_and_building_frame():
    before = model_with_anchors({'kind': 'item', 'hid': 'table', 'building': 'B1'},
                                [[14, 24, 3], [15, 24, 3]], [[1, 0, 1], [2, 0, 1]])
    before['buildings'][0]['items'] = [{'id': 'table', 'kind': 'table', 'asset': 'table',
        'host': {'ground': True, 'at': [3, 4]}, 'offset': 0, 'rotation': 0}]
    set_anchor_locals(before)
    after = copy.deepcopy(before)
    after['buildings'][0]['items'][0]['host']['at'] = [6, 8]
    after['buildings'][0]['items'][0]['rotation'] = 90
    lights.follow_host_moves(before, after)
    for row in rows(after):
        assert_path(row['path'], [[16, 29, 3], [16, 30, 3]])
        assert all(row['anchors'])
    moved = copy.deepcopy(after)
    moved['buildings'][0].update(position=[20, 30], rotation=90, base=4)
    lights.follow_host_moves(after, moved)
    for row in rows(moved):
        assert_path(row['path'], [[11, 36, 5], [10, 36, 5]])


def site_cases():
    polygon = [[10, 10], [20, 10], [20, 20], [10, 20]]
    return (
        ('terrace', {'terraces': [{'id': 'pad1', 'polygon': polygon, 'height': 2}]}, 'terraces', 'polygon'),
        ('retaining_wall', {'terraces': [{'id': 'pad1', 'polygon': polygon, 'height': 2}]}, 'terraces', 'polygon'),
        ('hardscape', {'hardscape': [{'id': 'pad1', 'polygon': polygon, 'elevation': 2}]}, 'hardscape', 'polygon'),
        ('hardscape', {'hardscape': [{'id': 'pad1', 'kind': 'path', 'points': [[10, 10], [20, 10]], 'width': 3}]}, 'hardscape', 'points'),
        ('fence', {'fence': [{'id': 'pad1', 'polyline': [[10, 10], [20, 10]], 'height': 6}]}, 'fence', 'polyline'),
        ('pool', {'pool': {'id': 'pad1', 'polygon': polygon, 'features': []}}, 'pool', 'polygon'),
        ('spa', {'pool': {'id': 'pool', 'polygon': polygon, 'features': [
            {'id': 'pad1', 'kind': 'spa', 'polygon': polygon, 'raise_in': 18}]}}, 'spa', 'polygon'),
    )


def site_host(model, collection):
    site = model['site']
    return site['pool']['features'][0] if collection == 'spa' else site['pool'] if collection == 'pool' else site[collection][0]


def test_site_polygon_and_polyline_translation_preserves_free_point():
    for kind, site, collection, field in site_cases():
        before = model_with_anchors({'kind': kind, 'hid': 'pad1'}, [[10, 10, 2], [20, 10, 2], [30, 10, 2]])
        before['site'].update(copy.deepcopy(site))
        for row in rows(before):
            row['anchors'][2] = None
        set_anchor_locals(before)
        after = copy.deepcopy(before)
        host = site_host(after, collection)
        host[field] = [[p[0]+5, p[1]-3] for p in host[field]]
        lights.follow_host_moves(before, after)
        for row in rows(after):
            assert_path(row['path'], [[15, 7, 2], [25, 7, 2], [30, 10, 2]])
            assert row['anchors'] == rows(before)[0]['anchors'], kind


def test_rendered_roof_sections_follow_building_and_detach_on_reshape():
    before = model_with_anchors({'kind': 'roof', 'hid': 'roof', 'building': 'B1'},
                               [[12, 22, 11], [16, 22, 11]])
    building = before['buildings'][0]
    building['roof'] = {'sections': [{'id': 'roof', 'kind': 'shed', 'rect': [0, 0, 10, 10], 'plate': 9, 'pitch': 2}]}
    set_anchor_locals(before)
    after = copy.deepcopy(before)
    after['buildings'][0]['position'] = [15, 17]
    lights.follow_host_moves(before, after)
    for row in rows(after):
        assert_path(row['path'], [[17, 19, 11], [21, 19, 11]])
        assert all(row['anchors'])
    after = copy.deepcopy(before)
    after['buildings'][0]['roof']['sections'][0]['pitch'] = 4
    lights.follow_host_moves(before, after)
    for row in rows(after):
        assert row['path'] == rows(before)[0]['path']
        assert row['anchors'] == [None, None]


def test_deleted_and_reshaped_hosts_freeze_and_clear_both_kinds():
    for kind, site, collection, field in site_cases():
        before = model_with_anchors({'kind': kind, 'hid': 'pad1'}, [[10, 10, 2], [20, 10, 2]])
        before['site'].update(copy.deepcopy(site))
        set_anchor_locals(before)
        for deleted in (False, True):
            after = copy.deepcopy(before)
            if deleted:
                after['site'].pop('pool' if collection in ('pool', 'spa') else collection)
            else:
                site_host(after, collection)[field][1][0] += 2
            lights.follow_host_moves(before, after)
            for row in rows(after):
                assert row['path'] == rows(before)[0]['path'], (kind, deleted)
                assert row['anchors'] == [None, None], (kind, deleted)


def test_building_piece_and_item_loss_clears_only_its_entry():
    before = model_with_anchors({'kind': 'wall', 'hid': 's1', 'building': 'B1'},
                                [[11, 20, 7], [14, 24, 3]])
    before['buildings'][0]['items'] = [{'id': 'table', 'kind': 'table', 'asset': 'table',
        'host': {'ground': True, 'at': [3, 4]}, 'offset': 0, 'rotation': 0, 'width': 4}]
    for row in rows(before):
        row['anchors'][1] = anchor('item', 'table', [1, 0, 1], 'B1')
    set_anchor_locals(before)
    for kind, index in (('wall', 0), ('item', 1), ('building', None)):
        for deleted in (False, True):
            after = copy.deepcopy(before)
            building = after['buildings'][0]
            if kind == 'building':
                if not deleted:
                    continue
                after['buildings'] = []
            elif kind == 'wall':
                if deleted:
                    building['walls'] = [w for w in building['walls'] if w['id'] != 's1']
                else:
                    building['joints'][0]['at'][0] += 2
            elif deleted:
                building['items'] = []
            else:
                building['items'][0]['width'] = 8
            lights.follow_host_moves(before, after)
            for row in rows(after):
                assert row['path'] == rows(before)[0]['path'], (kind, deleted)
                if index is None:
                    assert row['anchors'] == [None, None]
                else:
                    assert row['anchors'][index] is None, (kind, deleted)
                    assert row['anchors'][1-index] == rows(before)[0]['anchors'][1-index]


def post(ctx, op, status=200):
    current, count = ts.current_id(), len(ts.rounds())
    response = ctx.client.post('/api/house/editor/op', headers=ctx.mum, json={'op': op})
    assert response.status_code == status, response.text
    assert len(ts.rounds()) == count + (status == 200), 'Each accepted op is one undoable round.'
    if status != 200:
        assert ts.current_id() == current
        return None
    return response.json()['model']


def test_http_roundtrip_shared_follow_offset_update_and_history():
    house_seed()
    def setup(model):
        model['site']['lot'] = [[-100, -100], [200, -100], [200, 200], [-100, 200]]
        model['site']['terraces'] = [{'id': 'pad1', 'polygon': [[10, 10], [20, 10], [20, 20], [10, 20]],
            'height': 2, 'edges': [{'edge': 'sharp', 'wall': {'material': 'stone'}} for _ in range(4)]}]
        return model
    ts.update_model(setup)
    with Ctx() as ctx:
        originals = []
        for effect in (False, True):
            value = fixture(effect, path=[[10, 10, 2], [20, 10, 2], [20, 20, 2]], offset_ft=-1,
                anchors=[anchor(local=[0, 0, 0]), anchor(local=[10, 0, 0]), anchor(local=[10, 10, 0])])
            model = post(ctx, {'op': 'add_effect_fixture' if effect else 'add_light_fixture',
                **({} if effect else {'entity_id': ENTITY}), 'fixture': value})
            row = model['effect_fixtures'][0] if effect else model['light_fixtures'][ENTITY][0]
            assert row['path'] == value['path'] and row['anchors'] == value['anchors'] and row['offset_ft'] == -1
            originals.append(row)
        added = ts.current_id()
        model = post(ctx, {'op': 'update_pad', 'id': 'pad1', 'polygon': [[15, 12], [25, 12], [25, 22], [15, 22]]})
        moved = ts.current_id()
        for row in rows(model):
            assert row['path'] == [[15, 12, 2], [25, 12, 2], [25, 22, 2]] and row['offset_ft'] == -1
        signature = lights.live_layout(model)['light_fixtures_signatures'][ENTITY]
        for effect, original in zip((False, True), originals):
            model = post(ctx, {'op': 'update_effect_fixture' if effect else 'update_light_fixture',
                **({} if effect else {'entity_id': ENTITY}), 'id': original['id'], 'change': {'offset_ft': 3}})
            assert rows(model)[1 if effect else 0]['path'] == [[15, 12, 2], [25, 12, 2], [25, 22, 2]]
            post(ctx, {'op': 'update_effect_fixture' if effect else 'update_light_fixture',
                **({} if effect else {'entity_id': ENTITY}), 'id': original['id'], 'change': {'offset_ft': 51}}, 400)
        assert lights.live_layout(model)['light_fixtures_signatures'][ENTITY] != signature
        changed = ts.current_id()
        for round_id, expected_path, offset in ((added, originals[0]['path'], -1),
                (changed, [[15, 12, 2], [25, 12, 2], [25, 22, 2]], 3),
                (moved, [[15, 12, 2], [25, 12, 2], [25, 22, 2]], -1)):
            response = ctx.client.post('/api/house/twin/revert', headers=ctx.mum, json={'round': round_id})
            assert response.status_code == 200, response.text
            for row in rows(ts.current_model()):
                assert row['path'] == expected_path and row['offset_ft'] == offset
                assert row['anchors'] == originals[0]['anchors']


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
