"""Retaining-wall validation and the real update_pad/history/API path."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_retaining_')
from services import twin_terrain, twin_model_ops as ops, twin_model_bridge as bridge, twin_store


def run():
    pad = {'polygon': [[500, 500], [504, 500], [504, 504], [500, 504]], 'height': 3,
           'edges': [{'edge': 'sharp', 'wall': {'material': 'stone'}}] + [{'edge': 'slope'} for _ in range(3)]}
    for material in ('stone', 'block', 'concrete', 'brick', 'timber'):
        p = copy.deepcopy(pad)
        p['edges'][0]['wall']['material'] = material
        assert twin_terrain.pad_error(p) is None
        assert p['edges'][0]['wall'] == {'material': material, 'thickness_in': 8, 'above_in': 0}
        for thickness, above in ((4, 0), (24, 36), (8.5, 12.5)):
            p['edges'][0]['wall'].update(thickness_in=thickness, above_in=above)
            assert twin_terrain.pad_error(p) is None
    for wall in (None, [], 'stone', {}, {'material': 'steel'}, {'material': []},
                 *({'material': 'stone', 'thickness_in': v} for v in (3.9, 24.1, True, None, '8', float('nan'), float('inf'))),
                 *({'material': 'stone', 'above_in': v} for v in (-.1, 36.1, True, None, '0', float('nan'), float('inf')))):
        p = copy.deepcopy(pad); p['edges'][0]['wall'] = wall
        assert twin_terrain.pad_error(p), wall
    p = copy.deepcopy(pad); p['edges'][0]['edge'] = 'slope'
    assert twin_terrain.pad_error(p) is None and 'wall' not in p['edges'][0]
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = bridge.assemble(fixture)[0]
    bare = {**pad, 'edges': [{'edge': 'sharp'} for _ in range(4)]}
    model, _ = ops.apply(model, {'op': 'add_pad', **bare})
    target = model['site']['terraces'][-1]['id']
    twin_store.push_round(bridge.flatten(model), 'build')
    from test_twin_model_ops_more import _client, _people, _enforced
    tokens, client = _people(), _client()
    before = twin_store.current_id()
    with _enforced():
        operation = {'op': 'update_pad', 'id': target, 'edges': pad['edges']}
        for who, expected in (('child', 403), ('parent', 200)):
            response = client.post('/api/house/editor/op', headers=tokens[who], json={'op': operation})
            assert response.status_code == expected, response.text
        stored = twin_store.current_model()['site']['terraces'][-1]
        assert stored['edges'][0]['wall'] == {'material': 'stone', 'thickness_in': 8, 'above_in': 0}
        added = twin_store.current_id()
        invalid = copy.deepcopy(operation); invalid['edges'][0]['wall']['above_in'] = 37
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': invalid})
        assert response.status_code == 400 and twin_store.current_id() == added
        twin_store.revert(before)
        assert 'wall' not in twin_store.current_model()['site']['terraces'][-1]['edges'][0]
        twin_store.revert(added)
        assert twin_store.current_model()['site']['terraces'][-1]['edges'] == stored['edges']
        slope = copy.deepcopy(operation); slope['edges'][0]['edge'] = 'slope'
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': slope})
        assert response.status_code == 200, response.text
        assert 'wall' not in response.json()['plan']['site']['terraces'][-1]['edges'][0]
        twin_store.revert(added)
        assert twin_store.current_model()['site']['terraces'][-1]['edges'] == stored['edges']
    from services.agent_tools_v2 import TOOL_SCHEMAS
    schema = TOOL_SCHEMAS['house_design']
    assert len(json.dumps(schema)) <= 5200  # the shared house_design budget (test_twin_model_devices)
    assert all(word in schema['properties']['edit']['description'] for word in ('wall?', 'thickness_in', 'above_in', 'timber', 'slope drops it'))
    print('Passed: wall validation/defaults, update_pad API/refusals, round trip, undo/redo, slope removal and compact tool docs')


if __name__ == '__main__':
    run()
