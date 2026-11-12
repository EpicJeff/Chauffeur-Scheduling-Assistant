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
    from test_twin_model_ops_more import _client, _people, _enforced
    tokens, client = _people(), _client()
    with _enforced():
        op = {'op': 'update_site_shape', 'list': 'pool', 'depth': 7}
        before = twin_store.current_id()
        response = client.post('/api/house/editor/op', headers=tokens['child'], json={'op': op})
        assert response.status_code == 403 and twin_store.current_id() == before
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': dict(op, depth=13)})
        assert response.status_code == 400 and twin_store.current_id() == before
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': op})
        assert response.status_code == 200, response.text
        assert response.json()['plan']['site']['pool']['depth'] == 7
    print('Yard shape validation, legacy index, ID, history and HTTP passed')


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
