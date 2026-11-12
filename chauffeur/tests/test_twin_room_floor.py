"""Room offsets through validation, real operations, HTTP and stored history."""
import copy
import os
import tempfile

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_room_floor_')
from test_twin_model_ops_more import _house, _b, _people, _client, _enforced
from services import twin_model, twin_plan, twin_model_bridge as bridge, twin_model_ops as ops, twin_model_hosts as hosts, twin_store


def run():
    model = _house()
    b = _b(model)
    assert all(r['floor_offset_ft'] == 0 for r in b['rooms'])
    change = {'op': 'set', 'building': b['id'], 'id': 'dining', 'field': 'floor_offset_ft', 'value': -2}
    for value in (-10, -2.25, 0, 10):
        raw = copy.deepcopy(model)
        _b(raw)['rooms'][1]['floor_offset_ft'] = value
        assert twin_model.normalize(raw)[0]['buildings'][0]['rooms'][1]['floor_offset_ft'] == value
    for value in (-10.01, 10.01, '2', True, None, [], float('nan'), float('inf')):
        raw = copy.deepcopy(model)
        _b(raw)['rooms'][1]['floor_offset_ft'] = value
        normalized, notes = twin_model.normalize(raw)
        assert _b(normalized)['rooms'][1]['floor_offset_ft'] == 0 and any('floor_offset_ft' in n for n in notes)
        try:
            ops.apply(model, {**change, 'value': value})
        except (ops.Refused, ValueError):
            pass
        else:
            raise AssertionError(f'invalid offset accepted: {value}')
    changed = ops.apply(model, change)[0]
    assert _b(changed)['rooms'][1]['floor_offset_ft'] == -2
    assert _b(model)['rooms'][1]['floor_offset_ft'] == 0
    assert hosts.world_point(_b(changed), {'floor': 'dining', 'u': .5, 'v': .5})[2] == -2
    assert hosts.world_point(_b(changed), {'ceiling': 'dining', 'u': .5, 'v': .5})[2] == 9
    changed = ops.apply(changed, {'op': 'add_opening', 'building': b['id'], 'wall': 'mid', 'at': 5, 'width': 3, 'kind': 'door'})[0]
    assert next(o for o in _b(changed)['openings'] if o['wall'] == 'mid')['step_down_ft'] == 2
    # A sunken exterior opening can be taller than the old level-relative wall
    # height while its head still stays below the unchanged wall top.
    changed = ops.apply(changed, {'op': 'add_opening', 'building': b['id'], 'wall': 'e', 'at': 5, 'width': 3, 'kind': 'garage', 'sill': 0, 'head': 10})[0]
    flat = bridge.flatten(changed)
    ext = next(o for o in _b(flat)['openings'] if o['wall'] == 'e')
    assert ext['floor_reference_ft'] == -2 and ext['head'] == 10
    assert hosts.world_point(_b(changed), next(o for o in _b(changed)['openings'] if o['wall'] == 'e'))[2] == -2
    assert hosts.world_point(_b(changed), {'opening': ext['id'], 'side': 'in'})[2] == 1.5
    assert any(o['id'] == ext['id'] for o in _b(twin_plan.normalize(flat)[0])['openings'])
    rebuilt = bridge.assemble(flat)[0]
    assert _b(rebuilt)['rooms'][1]['floor_offset_ft'] == -2
    base = twin_store.push_round(bridge.flatten(model), 'build')
    tokens = _people()
    with _enforced():
        response = _client().post('/api/house/editor/op', headers=tokens['parent'], json={'op': change})
    assert response.status_code == 200, response.text
    after = response.json()['round']
    assert _b(twin_store.current_model())['rooms'][1]['floor_offset_ft'] == -2
    twin_store.revert(base)
    assert _b(twin_store.current_model())['rooms'][1]['floor_offset_ft'] == 0
    twin_store.revert(after)
    assert _b(twin_store.current_model())['rooms'][1]['floor_offset_ft'] == -2
    print('Passed: range/type/default migration, immutable ops, hosts, opening references, bridge, HTTP, undo and redo')


if __name__ == '__main__':
    run()
