"""Validated yard-shape operations through the real store and parent HTTP gate."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
DATA = tempfile.mkdtemp(prefix='chauffeur_shapes_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
from services import twin_model_bridge as bridge, twin_model_ops as ops, twin_store


def run():
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = bridge.assemble(fixture)[0]
    rect = [[5, 5], [15, 5], [15, 10], [5, 10]]
    model['site'].update(lot=[[0, 0], [40, 0], [40, 40], [0, 40]],
        beds=[{'polygon': rect}], hardscape=[{'id': 'patio', 'polygon': rect}],
        edges=[{'id': 'edge', 'polygon': rect}, {'points': [[2, 2], [4, 2]]}],
        pool={'id': 'pool', 'polygon': rect, 'depth': 5, 'coping': 1},
        fire_pit={'at': [20, 20], 'radius': 2}, fence={'polyline': [[2, 2], [4, 2]], 'height': 6, 'style': 'wood'})
    original = copy.deepcopy(model)
    for name, change in [('beds', {'polygon': [[5, 5], [10, 5], [10, 15]], 'rotation': 90}),
                         ('hardscape', {'rotation': 45}), ('edges', {'polygon': rect}),
                         ('pool', {'depth': 6, 'coping': 0}), ('fire_pit', {'radius': 3}),
                         ('fence', {'polyline': [[2, 2], [4, 2], [4, 4]], 'height': 8, 'style': 'rail'})]:
        changed, _ = ops.apply(model, {'op': 'update_site_shape', 'list': name, 'index': 0, **change})
        piece = changed['site'][name] if isinstance(changed['site'][name], dict) else changed['site'][name][0]
        for key, value in change.items():
            assert piece[key] == value
        assert piece['src']['person']
        assert bridge.flatten(bridge.assemble(bridge.flatten(changed))[0])['site'][name] == bridge.flatten(changed)['site'][name]
    assert model == original, 'no input mutation'
    legacy = copy.deepcopy(model)
    legacy['site']['hardscape'][0]['material'] = 'concrete'
    assert ops.apply(legacy, {'op': 'update_site_shape', 'list': 'hardscape', 'index': 0, 'rotation': 15})[0]['site']['hardscape'][0]['material'] == 'concrete'
    # Additions travel through the same operation/store boundary as edits.
    for name in ('beds', 'hardscape', 'edges'):
        added, _ = ops.apply(model, {'op': 'add_site_shape', 'list': name, 'polygon': rect})
        assert added['site'][name][-1]['polygon'] == rect
        assert added['site'][name][-1]['material'] == ('mulch' if name == 'beds' else 'lawn' if name == 'edges' else 'patio_concrete')
        assert added['site'][name][-1]['src']['person']
    no_pool = copy.deepcopy(model)
    no_pool['site']['pool'] = None
    added, _ = ops.apply(no_pool, {'op': 'add_site_shape', 'list': 'pool', 'polygon': rect})
    assert added['site']['pool']['depth'] == 5 and added['site']['pool']['coping'] == 1
    # Missing shape migrates to round; adding more pits/fences preserves the old one.
    migrated = bridge.assemble(bridge.flatten(model))[0]
    assert migrated['site']['fire_pit']['shape'] == 'round'
    assert migrated['site']['fire_pit']['at'] == model['site']['fire_pit']['at']
    from services import twin_model
    for radius in (.05, 150):
        legacy = copy.deepcopy(model)
        legacy['site']['fire_pit']['radius'] = radius
        assert twin_model.normalize(legacy)[0]['site']['fire_pit']['radius'] == radius
    tall = copy.deepcopy(model)
    tall['site']['fence']['height'] = 12
    assert ops.apply(tall, {'op': 'move_site_item', 'list': 'fence', 'by': [1, 0]})[0]['site']['fence']['height'] == 12
    for shape in ('square', 'rect'):
        added, _ = ops.apply(model, {'op': 'add_site_shape', 'list': 'fire_pit', 'shape': shape, 'polygon': rect})
        assert added['site']['fire_pit'][1]['polygon'] == rect
    for shape, properties in [('round', {'at': [20, 20]}), ('square', {'at': [20, 20]}),
                              ('rect', {'at': [20, 20]}), ('outline', {'polygon': rect})]:
        added, _ = ops.apply(model, {'op': 'add_site_shape', 'list': 'fire_pit', 'shape': shape, **properties})
        pits = added['site']['fire_pit']
        assert len(pits) == 2 and pits[0]['at'] == model['site']['fire_pit']['at']
        pit = pits[1]
        assert pit['shape'] == shape and pit['src']['person']
        if shape == 'round':
            assert pit['radius'] == 2 and pit['at'] == [20, 20]
        else:
            assert 'at' not in pit and len(pit['polygon']) >= 3
            if shape in ('square', 'rect'):
                assert max(p[0] for p in pit['polygon'])-min(p[0] for p in pit['polygon']) == 4
                assert max(p[1] for p in pit['polygon'])-min(p[1] for p in pit['polygon']) == (4 if shape == 'square' else 6)
            edited, _ = ops.apply(added, {'op': 'update_site_shape', 'list': 'fire_pit', 'id': pit['id'], 'rotation': 45})
            assert edited['site']['fire_pit'][1]['polygon'] != pit['polygon']
        assert bridge.assemble(bridge.flatten(added))[0]['site']['fire_pit'] == pits
    fence_op = {'op': 'add_site_shape', 'list': 'fence', 'polyline': [[20, 20], [25, 20], [25, 25]], 'style': 'wood'}
    added, _ = ops.apply(model, fence_op)
    assert len(added['site']['fence']) == 2 and added['site']['fence'][1]['height'] == 6
    assert added['site']['fence'][0]['polyline'] == model['site']['fence']['polyline']
    assert added['site']['fence'][1]['style'] == 'wood'
    for operation in [dict(fence_op, height=1.99), dict(fence_op, height=10.01), dict(fence_op, polyline=[[0, 0]]),
                      {'op': 'add_site_shape', 'list': 'fire_pit', 'shape': 'triangle', 'at': [1, 1]},
                      {'op': 'add_site_shape', 'list': 'fire_pit', 'shape': 'square', 'at': [1, 1], 'side': 0},
                      {'op': 'add_site_shape', 'list': 'fire_pit', 'shape': 'rect', 'at': [1, 1], 'width': True},
                      {'op': 'add_site_shape', 'list': 'fire_pit', 'shape': 'outline', 'polygon': [[0, 0], [2, 2], [0, 2], [2, 0]]},
                      {'op': 'add_site_shape', 'list': 'fire_pit', 'shape': 'round', 'at': [1, 1], 'radius': 0}]:
        try:
            ops.apply(model, operation)
        except ops.Refused:
            pass
        else:
            raise AssertionError(operation)
    for preset, width, material in [('sidewalk', 4, 'patio_concrete'), ('paver', 3, 'paving'), ('driveway', 10, 'patio_concrete')]:
        added, _ = ops.apply(model, {'op': 'add_site_shape', 'list': 'hardscape', 'kind': 'path', 'preset': preset, 'points': [[5, 5], [15, 5], [15, 15]]})
        path = added['site']['hardscape'][-1]
        assert path['width'] == width and path['material'] == material
        assert path['corner'] == ('rounded' if preset == 'paver' else 'mitred')
        assert bridge.assemble(bridge.flatten(added))[0]['site']['hardscape'][-1] == path
    path_op = {'op': 'add_site_shape', 'list': 'hardscape', 'kind': 'path', 'points': [[5, 5], [15, 15], [5, 15], [15, 5]]}
    added, _ = ops.apply(model, path_op)  # User-authored crossing is allowed.
    assert added['site']['hardscape'][-1]['width'] == 3
    changed, _ = ops.apply(added, {'op': 'update_site_shape', 'list': 'hardscape', 'index': 1, 'width': 4, 'smooth': True, 'edging': 'curb', 'radius': 2})
    assert changed['site']['hardscape'][1]['width'] == 4
    for change in [{'points': [[1, 1]]}, {'points': [[1, 1], [1, 1]]}, {'points': [[1, 1], [float('nan'), 1]]},
                   {'width': .99}, {'width': 30.01}, {'width': True}, {'smooth': 'yes'}, {'corner': 'spike'}, {'edging': 'wall'},
                   {'preset': 'unknown'}, {'material': 'made-up'}, {'polygon': rect}, {'radius': 0}]:
        try:
            ops.apply(model, {**path_op, **change})
        except ops.Refused:
            pass
        else:
            raise AssertionError(change)
    for polygon in [rect[:2], [[0, 0], [8, 8], [0, 8], [8, 0]], [[0, 0], [3000, 0], [0, 1]]]:
        try:
            ops.apply(model, {'op': 'add_site_shape', 'list': 'beds', 'polygon': polygon})
        except ops.Refused:
            pass
        else:
            raise AssertionError(polygon)
    _, words = ops.apply(model, {'op': 'add_site_shape', 'list': 'beds', 'polygon': [[50, 50], [60, 50], [50, 60]]})
    assert 'outside the lot' in words
    by_id, _ = ops.apply(model, {'op': 'update_site_shape', 'list': 'hardscape', 'id': 'patio', 'rotation': 30})
    assert by_id['site']['hardscape'][0]['rotation'] == 30
    turned, _ = ops.apply(model, {'op': 'update_site_shape', 'list': 'hardscape', 'id': 'patio', 'rotation': 90})
    assert turned['site']['hardscape'][0]['polygon'] == [[12.5, 2.5], [12.5, 12.5], [7.5, 12.5], [7.5, 2.5]]
    assert ops.apply(turned, {'op': 'update_site_shape', 'list': 'hardscape', 'id': 'patio', 'rotation': 0})[0]['site']['hardscape'][0]['polygon'] == rect
    invalid = [('beds', {'polygon': rect[:2]}), ('beds', {'polygon': [[0, 0], [8, 8], [0, 8], [8, 0]]}),
               ('beds', {'polygon': [[0, 0], [1, 0], [2, 0]]}), ('beds', {'polygon': [[0, 0], [3000, 0], [0, 1]]}),
               ('beds', {'polygon': [[0, 0], [float('inf'), 0], [0, 1]]}),
               ('pool', {'depth': 1.9}), ('pool', {'depth': 12.1}), ('pool', {'coping': -.1}), ('pool', {'coping': 3.1}),
               ('fire_pit', {'radius': 0}), ('fire_pit', {'radius': 101}), ('fence', {'height': 0}), ('fence', {'height': 51}),
               ('fence', {'polyline': [[1, 1]]}), ('fence', {'polyline': [[1, 1], [1, 1]]}),
               ('pool', {'depth': True}), ('pool', {'radius': 3}), ('planting', {'rotation': 3})]
    for name, change in invalid:
        try:
            ops.apply(model, {'op': 'update_site_shape', 'list': name, 'index': 0, **change})
        except ops.Refused:
            pass
        else:
            raise AssertionError((name, change))
    _, words = ops.apply(model, {'op': 'update_site_shape', 'list': 'beds', 'index': 0, 'polygon': [[50, 50], [60, 50], [50, 60]]})
    assert 'outside the lot' in words
    twin_store.push_round(bridge.flatten(model), 'build')
    before = twin_store.current_id()
    after = twin_store.update_model(lambda m: ops.apply(m, {'op': 'update_site_shape', 'list': 'pool', 'depth': 6, 'coping': 0})[0])
    assert twin_store.current_model()['site']['pool']['depth'] == 6
    twin_store.revert(before)
    assert twin_store.current_model()['site']['pool']['depth'] == 5
    twin_store.revert(after)
    assert twin_store.current_model()['site']['pool']['coping'] == 0
    before_draw = twin_store.current_id()
    after_draw = twin_store.update_model(lambda m: ops.apply(m, path_op)[0])
    assert twin_store.current_model()['site']['hardscape'][-1]['kind'] == 'path'
    twin_store.revert(before_draw)
    assert len(twin_store.current_model()['site']['hardscape']) == 1
    twin_store.revert(after_draw)
    assert twin_store.current_model()['site']['hardscape'][-1]['kind'] == 'path'
    before_bed = twin_store.current_id()
    count = len(twin_store.current_model()['site']['beds'])
    after_bed = twin_store.update_model(lambda m: ops.apply(m, {'op': 'add_site_shape', 'list': 'beds', 'polygon': rect})[0])
    assert len(twin_store.current_model()['site']['beds']) == count+1
    twin_store.revert(before_bed)
    assert len(twin_store.current_model()['site']['beds']) == count
    twin_store.revert(after_bed)
    assert len(twin_store.current_model()['site']['beds']) == count+1
    for operation, name in [(fence_op, 'fence'), ({'op': 'add_site_shape', 'list': 'fire_pit', 'shape': 'rect', 'at': [20, 20]}, 'fire_pit')]:
        before_feature = twin_store.current_id()
        after_feature = twin_store.update_model(lambda m: ops.apply(m, operation)[0])
        assert len(twin_store.current_model()['site'][name]) == 2
        twin_store.revert(before_feature)
        assert isinstance(twin_store.current_model()['site'][name], dict)
        twin_store.revert(after_feature)
        assert len(twin_store.current_model()['site'][name]) == 2
    from test_twin_model_ops_more import _client, _people, _enforced
    tokens, client = _people(), _client()
    with _enforced():
        for draw_op in [path_op, {'op': 'add_site_shape', 'list': 'beds', 'polygon': rect}, fence_op,
                        {'op': 'add_site_shape', 'list': 'fire_pit', 'shape': 'square', 'at': [20, 20]}]:
            before = twin_store.current_id()
            response = client.post('/api/house/editor/op', headers=tokens['child'], json={'op': draw_op})
            assert response.status_code == 403 and twin_store.current_id() == before
            response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': draw_op})
            assert response.status_code == 200, response.text
        before = twin_store.current_id()
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': dict(path_op, width=31)})
        assert response.status_code == 400 and twin_store.current_id() == before
        op = {'op': 'update_site_shape', 'list': 'pool', 'depth': 7}
        before = twin_store.current_id()
        response = client.post('/api/house/editor/op', headers=tokens['child'], json={'op': op})
        assert response.status_code == 403 and twin_store.current_id() == before
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': dict(op, depth=13)})
        assert response.status_code == 400 and twin_store.current_id() == before
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': op})
        assert response.status_code == 200, response.text
        assert response.json()['plan']['site']['pool']['depth'] == 7
    # A normal plot/site rebuild must still run with multiple hand-authored pits.
    from test_twin_build_parts import _lot_only, _confirm_lot, Reader, tb, ts
    plot = _lot_only()
    placement = _confirm_lot(plot)
    authored = [{'id': 'manual-round', 'at': [20, 20], 'radius': 2, 'shape': 'round', 'src': {'person': True}},
                {'id': 'manual-outline', 'polygon': rect, 'shape': 'outline', 'src': {'person': True}}]
    from services import twin_plan
    plan = twin_plan.normalize({'units': 'ft', 'buildings': [], 'site': {'lot': placement['outline'], 'fire_pit': copy.deepcopy(authored)}})[0]
    ts.push_round(plan, 'edit')
    build = tb.start({'part': 'lot'}, reader=Reader(), inline=True)
    assert tb.status(build)['state'] == 'done', tb.status(build)
    assert all(next(p for p in ts.current()['site']['fire_pit'] if p['id'] == pit['id']) == pit for pit in authored)
    print('Yard shape validation, legacy index, ID, history, HTTP and multi-pit lot rebuild passed')


if __name__ == '__main__':
    try:
        run()
    finally:
        from services import storage
        storage.db.close()
        try:
            shutil.rmtree(DATA)
        except PermissionError:
            # TestClient worker-thread SQLite handles close at process exit on
            # Windows. The outer test runner can then remove this temp folder.
            pass
