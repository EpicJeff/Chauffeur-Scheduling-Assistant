"""Stairs through real model ops, bridge, HTTP and persisted undo/redo."""
import copy
import json
import math
import os
import tempfile

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_stairs_')
from test_twin_model_ops_more import _house, _b, _people, _client, _enforced
from services import twin_model, twin_plan, twin_model_bridge as bridge, twin_model_ops as ops, twin_store


def run():
    model = _house(2)
    _b(model)['levels'][1]['elevation'] = 9
    bid = _b(model)['id']
    add = {'op': 'add_stair', 'building': bid, 'level': 'L1', 'from': [1, 2], 'to': [13, 2], 'to_level': 'L2'}
    changed, words = ops.apply(model, add)
    stair = _b(changed)['stairs'][0]
    assert stair['rise_to'] == 9 and stair['risers'] == 15
    assert math.isclose(9 / stair['risers'] * 12, 7.2)
    assert (stair['width'], stair['style'], stair['rail']) == (3, 'solid', 'both')
    assert stair['src']['person'] and not _b(model)['stairs']
    update = {'op': 'update_stair', 'building': bid, 'id': stair['id']}
    for operation in (add, update):
        source = model if operation is add else changed
        for field, values, message in (
            ('width', (1.99, 8.01), '2 to 8'),
            ('width', (True, None, '3', float('nan'), float('inf')), 'finite'),
            ('to', ([2, 2], [1, 2]), 'Make the stair longer'),
            ('to', ([40, 2],), 'Make the stair shorter'),
            ('to_level', ('L1', 'missing'), 'above'),
            ('style', ('spiral', None), 'solid or open'),
            ('rail', ('middle', None), 'rails'),
        ):
            for value in values:
                before = copy.deepcopy(source)
                try:
                    ops.apply(source, {**operation, field: value})
                except ops.Refused as exc:
                    assert message in str(exc), (value, str(exc))
                else:
                    raise AssertionError(f'Accepted {field}={value}')
                assert source == before
        for width in (2, 8):
            assert _b(ops.apply(source, {**operation, 'width': width})[0])['stairs'][0]['width'] == width
        for run in (9, 9 / math.tan(math.radians(20))):
            assert _b(ops.apply(source, {**operation, 'to': [1 + run, 2]})[0])['stairs']
    revised = ops.apply(changed, {**update, 'from': [0, 2], 'style': 'open', 'rail': 'left', 'risers': 2})[0]
    assert _b(revised)['stairs'][0]['risers'] == 15  # caller cannot set a non-derived count
    revised = ops.apply(revised, {**update, 'rise_to': 8})[0]
    assert 'to_level' not in _b(revised)['stairs'][0] and _b(revised)['stairs'][0]['risers'] == 13
    flat = bridge.flatten(revised)
    assert _b(bridge.assemble(flat)[0])['stairs'] == _b(revised)['stairs']
    reread = copy.deepcopy(flat)
    _b(reread)['stairs'] = []
    assert _b(bridge.assemble(reread, previous=revised)[0])['stairs'] == _b(revised)['stairs']
    legacy = {'id': 'old', 'level': 'L1', 'from': [1, 2], 'to': [13, 2], 'width': 3, 'rise_to': 9, 'risers': 12}
    _b(flat)['stairs'] = [copy.deepcopy(legacy)]
    for normalized in (twin_plan.normalize(flat)[0], bridge.assemble(flat)[0]):
        old = _b(normalized)['stairs'][0]
        assert all(old[k] == v for k, v in legacy.items())
        assert old.get('style', 'solid') == 'solid' and old.get('rail', 'none') == 'none'
        assert 'style' not in old and 'rail' not in old  # effective defaults, no legacy data rewrite
    base = twin_store.push_round(bridge.flatten(model), 'build')
    tokens, client = _people(), _client()
    with _enforced():
        for who, expected in (('child', 403), ('parent', 200)):
            response = client.post('/api/house/editor/op', headers=tokens[who], json={'op': add})
            assert response.status_code == expected, response.text
        added = twin_store.current_id()
        persisted = _b(twin_store.current_model())['stairs'][0]
        change = {**update, 'id': persisted['id'], 'width': 4, 'style': 'open'}
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': change})
        assert response.status_code == 200, response.text
        edited = twin_store.current_id()
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': {**change, 'width': 1}})
        assert response.status_code == 400 and twin_store.current_id() == edited
        twin_store.revert(added)
        assert _b(twin_store.current_model())['stairs'][0]['style'] == 'solid'
        twin_store.revert(edited)
        assert _b(twin_store.current_model())['stairs'][0]['style'] == 'open'
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': {'op': 'delete', 'building': bid, 'id': persisted['id']}})
        assert response.status_code == 200 and not _b(twin_store.current_model())['stairs'], response.text
        twin_store.revert(base)
        assert not _b(twin_store.current_model())['stairs']
    from services.agent_tools_v2 import TOOL_SCHEMAS
    schema = TOOL_SCHEMAS['house_design']
    assert all(word in schema['properties']['edit']['description'] for word in ('add_stair', 'update_stair', 'to_level', 'rail?'))
    assert len(json.dumps(schema)) <= 5600
    print(f'Passed: immutable add/update validation, pitch boundaries/messages, derived risers, legacy defaults, bridge, HTTP, delete, undo/redo; schema {len(json.dumps(schema))}/5600')


if __name__ == '__main__':
    run()
