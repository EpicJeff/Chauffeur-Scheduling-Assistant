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
    for kind, settings, expected in (
            ('wall', {'material': 'block', 'cap': {}, 'rail': {'style': 'pickets'}},
             {'material': 'block', 'thickness_in': 8, 'above_in': 0, 'cap': {'thickness_in': 2, 'overhang_in': 1},
              'rail': {'style': 'pickets', 'height_in': 36}}),
            ('stair', {'rail': {'style': 'cable'}},
             {'riser_in': 7, 'tread_in': 11, 'treads': True, 'rail': {'style': 'cable', 'height_in': 36}})):
        p = copy.deepcopy(pad); p['edges'][0] = {'edge': 'sharp', kind: settings}
        assert twin_terrain.pad_error(p) is None
        assert p['edges'][0][kind] == expected
        p['edges'][0]['edge'] = 'slope'
        assert twin_terrain.pad_error(p) is None and p['edges'][0] == {'edge': 'slope'}
    invalid_edges = [
        {'wall': {'material': 'block'}, 'stair': {}},
        {'stair': {'treads': 1}}, {'stair': []},
        *({'stair': {key: v}} for key, values in [('riser_in', [3.9, 8.1, True, float('nan')]),
                                                  ('tread_in', [8.9, 24.1, None])] for v in values),
        *({'wall': {'material': 'block', 'cap': {key: v}}} for key, values in
          [('thickness_in', [.9, 8.1, True]), ('overhang_in', [-.1, 6.1])] for v in values),
        {'wall': {'material': 'block', 'cap': False}},
        *({'stair': {'rail': r}} for r in [None, {}, {'style': 'wood'}, {'style': 'panel', 'height_in': 23.9},
                                          {'style': 'panel', 'height_in': 48.1}, {'style': 'panel', 'height_in': True}]),
        {'stair': {'materials': {'face': None}}}, {'stair': {'materials': {'riser': {'id': 'missing'}}}},
        {'wall': {'material': 'block', 'materials': {'cap': {'id': 'missing'}}}},
        {'stair': {'rail': {'style': 'cable', 'materials': {'rail': {'id': 'missing'}}}}},
    ]
    for edge in invalid_edges:
        p = copy.deepcopy(pad); p['edges'][0] = {'edge': 'sharp', **edge}
        assert twin_terrain.pad_error(p), edge
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
        for edge in [
                {'edge': 'sharp', 'wall': {'material': 'block', 'cap': {}, 'materials': {'cap': {'id': 'red_brick_03'}},
                                         'rail': {'style': 'panel', 'materials': {'rail': {'id': 'black_metal'}}}}},
                {'edge': 'sharp', 'stair': {'materials': {'riser': {'id': 'red_brick_03'}, 'tread': {'id': 'mocha_oak_veneer'}},
                                          'rail': {'style': 'cable'}}}]:
            operation = {'op': 'update_pad', 'id': target, 'edges': [edge] + [{'edge': 'slope'} for _ in range(3)]}
            response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': operation})
            assert response.status_code == 200, response.text
            from services import twin_plan
            loaded, notes = twin_plan.normalize(bridge.flatten(twin_store.current_model()))
            assert loaded['site']['terraces'][-1]['edges'] == response.json()['plan']['site']['terraces'][-1]['edges']
            authored = twin_store.current_id()
            slope = copy.deepcopy(operation); slope['edges'][0]['edge'] = 'slope'
            response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': slope})
            assert response.status_code == 200, response.text
            assert response.json()['plan']['site']['terraces'][-1]['edges'][0] == {'edge': 'slope'}
            twin_store.revert(authored)
        # Unknown slots are reset at load, preserving the pad and its geometry settings.
        broken = bridge.flatten(twin_store.current_model())
        stair = broken['site']['terraces'][-1]['edges'][0]['stair']
        stair['materials']['tread'] = {'id': 'retired'}
        stair['rail']['materials'] = {'rail': {'id': 'retired'}}
        loaded, notes = twin_plan.normalize(broken)
        stair = loaded['site']['terraces'][-1]['edges'][0]['stair']
        assert 'materials' not in stair and 'materials' not in stair['rail'] and notes
        for invalid_edge in invalid_edges:
            invalid = copy.deepcopy(operation); invalid['edges'][0] = {'edge': 'sharp', **invalid_edge}
            before_invalid = twin_store.current_id()
            response = client.post('/api/house/editor/op', headers={**tokens['parent'], 'Content-Type': 'application/json'},
                                   content=json.dumps({'op': invalid}))
            assert response.status_code == 400 and twin_store.current_id() == before_invalid, response.text
        slope = copy.deepcopy(operation); slope['edges'][0]['edge'] = 'slope'
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': slope})
        assert response.status_code == 200, response.text
        assert 'wall' not in response.json()['plan']['site']['terraces'][-1]['edges'][0]
        twin_store.revert(added)
        assert twin_store.current_model()['site']['terraces'][-1]['edges'] == stored['edges']
    from services.agent_tools_v2 import TOOL_SCHEMAS
    schema = TOOL_SCHEMAS['house_design']
    assert len(json.dumps(schema)) <= 6000  # shared house_design budget (5,689 at v2.499.836)
    assert all(word in schema['properties']['edit']['description'] for word in ('wall?', 'thickness_in', 'above_in', 'timber', 'slope drops it'))
    print('Passed: wall validation/defaults, update_pad API/refusals, round trip, undo/redo, slope removal and compact tool docs')
    print('Passed: cap/stair/rail defaults, range and slot refusals, API round trips and load-time slot reset')


if __name__ == '__main__':
    run()
