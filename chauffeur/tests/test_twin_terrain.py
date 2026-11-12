"""Pad/foundation invariants and actual connected-history round trips."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_ground_')
from services import twin_plan, twin_model, twin_model_bridge as bridge, twin_model_ops as ops, twin_store, twin_terrain


def run():
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = bridge.assemble(fixture)[0]
    b = model['buildings'][0]
    assert b['foundation'] == {'mode': 'fixed', 'offset_ft': 0, 'thickness_ft': 1}
    assert bridge.flatten(model)['buildings'][0]['base'] == b['base']
    pad = {'polygon': [[500, 500], [520, 500], [520, 520], [500, 520]], 'height': -4}
    p = copy.deepcopy(pad); assert twin_terrain.pad_error(p) is None
    assert p['blend'] == 6 and p['edges'] == [{'edge': 'slope'}] * 4
    for change in ({'height': 51}, {'height': float('nan')}, {'blend': -1}, {'blend': 51},
                   {'polygon': [[0, 0], [8, 8], [0, 8], [8, 0]]},
                   {'polygon': [[0, 0], [1, 0], [2, 0]]}, {'edges': [{'edge': 'wall'}] * 4}):
        invalid = copy.deepcopy(pad); invalid.update(change)
        assert twin_terrain.pad_error(invalid), change
        raw = copy.deepcopy(fixture); raw.setdefault('site', {})['terraces'] = [invalid]
        assert not twin_plan.normalize(raw)[0]['site']['terraces']
        try:
            ops.apply(model, {'op': 'add_pad', **invalid})
            raise AssertionError('invalid operation accepted')
        except ops.Refused:
            pass
    changed, _ = ops.apply(model, {'op': 'add_pad', **pad})
    p = changed['site']['terraces'][-1]
    assert p['height'] == -4 and p['src']['person']
    assert model.get('site', {}).get('terraces', []) != changed['site']['terraces']
    updated, _ = ops.apply(changed, {'op': 'update_pad', 'id': p['id'], 'height': -3, 'edges': [{'edge': 'sharp'}] * 4})
    assert bridge.flatten(twin_model.normalize(updated)[0])['site']['terraces'][-1]['height'] == -3
    deleted, _ = ops.apply(updated, {'op': 'delete_pad', 'id': p['id']})
    assert not deleted['site']['terraces']
    stacked, _ = ops.apply(changed, {'op': 'add_pad', **pad, 'height': -2})
    ids = [p['id'] for p in stacked['site']['terraces']]
    reordered, _ = ops.apply(stacked, {'op': 'reorder_pad', 'id': ids[0], 'to': 1})
    assert [p['id'] for p in reordered['site']['terraces']] == ids[::-1]
    assert [p['id'] for p in stacked['site']['terraces']] == ids, 'ops must not mutate their input'
    restored, _ = ops.apply(reordered, {'op': 'reorder_pad', 'id': ids[0], 'to': 0})
    assert restored['site']['terraces'] == stacked['site']['terraces']
    assert bridge.flatten(twin_model.normalize(reordered)[0])['site']['terraces'] == reordered['site']['terraces']
    for to in (None, -1, 2, 1.0, True, '1', [], {}):
        try:
            ops.apply(stacked, {'op': 'reorder_pad', 'id': ids[0], 'to': to})
            raise AssertionError(f'invalid layer accepted: {to!r}')
        except ops.Refused:
            pass
    for target in (None, 'missing'):
        try:
            ops.apply(stacked, {'op': 'reorder_pad', 'id': target, 'to': 0})
            raise AssertionError('missing pad accepted')
        except ops.Refused:
            pass
    cap = copy.deepcopy(model); cap['site']['terraces'] = [dict(copy.deepcopy(p), id=f'pad-{i}') for i in range(41)]
    assert len(twin_model.normalize(cap)[0]['site']['terraces']) == 40
    try:
        ops.apply(cap, {'op': 'add_pad', **pad})
        raise AssertionError('cap accepted')
    except ops.Refused:
        pass
    for f in ({'mode': 'bad'}, {'mode': 'auto', 'thickness_ft': -1}, {'mode': 'fixed', 'offset_ft': float('inf')}):
        try:
            ops.apply(model, {'op': 'set_foundation', 'building': b['id'], 'foundation': f})
            raise AssertionError('bad foundation accepted')
        except ops.Refused:
            pass
    poly = twin_terrain.footprint(b)
    raised = {'op': 'add_pad', 'polygon': poly, 'height': 5}
    try:
        ops.apply(model, raised)
        raise AssertionError('pad cut through fixed building')
    except ops.Refused:
        pass
    auto, _ = ops.apply(model, {'op': 'set_foundation', 'building': b['id'], 'foundation': {'mode': 'auto'}})
    assert ops.apply(auto, raised)[0]['site']['terraces'][-1]['height'] == 5
    simple = {'units': 'ft', 'buildings': [{'id': 'box', 'position': [0, 0], 'base': 0,
        'levels': [{'id': 'L1', 'elevation': 0, 'ceiling': 8, 'outline': [[0, 0], [10, 0], [10, 10], [0, 10]]}],
        'foundation': {'mode': 'fixed'}}], 'site': {}}
    band = {'polygon': [[11, 0], [20, 0], [20, 10], [11, 10]], 'height': 4, 'blend': 6}
    assert twin_terrain.pad_error(band) is None
    simple['site']['terraces'] = [band]
    assert twin_terrain.crossing_error(simple), 'a blend band must not enter a fixed building'
    band['edges'] = [{'edge': 'sharp'}]*4
    assert twin_terrain.crossing_error(simple) is None
    assert twin_terrain.ground_at([p], [510, 510]) == -4
    rect = lambda x0, y0, x1, y1: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    lower = {'polygon': rect(0, 0, 30, 30), 'height': -4, 'blend': 6}
    upper = {'polygon': rect(20, 5, 40, 25), 'height': 0, 'blend': 6}
    assert twin_terrain.ground_at([lower, upper], [17, 15]) == -2
    assert twin_terrain.ground_at([lower, upper], [25, 15]) == 0
    assert twin_terrain.ground_at([upper, lower], [25, 15]) == -4
    # Ordering can expose higher ground; the existing fixed-footprint refusal
    # must still run on reorder, just as it does on pad edits.
    covered = copy.deepcopy(model)
    covered['buildings'] = [copy.deepcopy(b)]
    covered['buildings'][0]['base'] = 0
    covered['site']['terraces'] = [
        {'id': 'raised', 'polygon': poly, 'height': 4},
        {'id': 'cover', 'polygon': poly, 'height': 0}]
    assert twin_terrain.crossing_error(covered) is None
    try:
        ops.apply(covered, {'op': 'reorder_pad', 'id': 'raised', 'to': 1})
        raise AssertionError('reorder cut through a fixed building')
    except ops.Refused:
        pass
    # Both scalar and polygon yard records use the real move/delete op path.
    yard = copy.deepcopy(model)
    for kind, piece in [('beds', {'polygon': pad['polygon']}), ('hardscape', {'polygon': pad['polygon']}),
                        ('edges', {'points': [[500, 500], [520, 500]]}), ('pool', {'polygon': pad['polygon']}),
                        ('fire_pit', {'at': [500, 500], 'radius': 2}), ('fence', {'polyline': [[500, 500], [520, 500]]})]:
        piece = dict(piece, id='yard-' + kind)
        yard['site'][kind] = piece if kind in ('pool', 'fire_pit', 'fence') else [piece]
        moved, _ = ops.apply(yard, {'op': 'move_site_item', 'list': kind, 'id': piece['id'], 'by': [3, -2]})
        item = moved['site'][kind] if isinstance(moved['site'][kind], dict) else moved['site'][kind][0]
        key = next(k for k in ('at', 'polygon', 'points', 'polyline') if k in piece)
        assert item[key] == ([503, 498] if key == 'at' else [[q[0]+3, q[1]-2] for q in piece[key]])
        gone, _ = ops.apply(moved, {'op': 'delete_site_item', 'list': kind, 'id': piece['id']})
        assert not gone['site'][kind]
    # The same append-only store used by editor op, undo and redo.
    twin_store.push_round(bridge.flatten(model), 'build')
    added_id = twin_store.update_model(lambda m: ops.apply(m, {'op': 'add_pad', **pad})[0])
    edited_id = twin_store.update_model(lambda m: ops.apply(m, {'op': 'update_pad', 'id': p['id'], 'height': -3})[0])
    twin_store.revert(added_id)
    assert twin_store.current_model()['site']['terraces'][-1]['height'] == -4
    twin_store.revert(edited_id)
    assert twin_store.current_model()['site']['terraces'][-1]['height'] == -3
    before_order = twin_store.update_model(lambda m: ops.apply(m, {'op': 'add_pad', **pad, 'height': -2})[0])
    order = [p['id'] for p in twin_store.current_model()['site']['terraces']]
    after_order = twin_store.update_model(lambda m: ops.apply(m, {'op': 'reorder_pad', 'id': order[0], 'to': 1})[0])
    assert [p['id'] for p in twin_store.current_model()['site']['terraces']] == order[::-1]
    twin_store.revert(before_order)
    assert [p['id'] for p in twin_store.current_model()['site']['terraces']] == order
    twin_store.revert(after_order)
    assert [p['id'] for p in twin_store.current_model()['site']['terraces']] == order[::-1]
    from test_twin_model_ops_more import _client, _people, _enforced
    tokens, client = _people(), _client()
    with _enforced():
        response = client.post('/api/house/editor/op', headers=tokens['child'], json={'op': {'op': 'add_pad', **pad}})
        assert response.status_code == 403
        before_id = twin_store.current_id()
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': {'op': 'add_pad', **pad, 'blend': 51}})
        assert response.status_code == 400 and twin_store.current_id() == before_id
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': {'op': 'add_pad', **pad}})
        assert response.status_code == 200, response.text
        assert response.json()['plan']['site']['terraces'][-1]['height'] == -4
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': {'op': 'set_foundation', 'building': b['id'], 'foundation': {'mode': 'auto'}}})
        assert response.status_code == 200, response.text
        target = response.json()['plan']['site']['terraces'][-1]['id']
        before_id = twin_store.current_id()
        for headers, to, status in ((tokens['child'], 0, 403), (tokens['parent'], -1, 400)):
            response = client.post('/api/house/editor/op', headers=headers, json={'op': {'op': 'reorder_pad', 'id': target, 'to': to}})
            assert response.status_code == status and twin_store.current_id() == before_id
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': {'op': 'reorder_pad', 'id': target, 'to': 0}})
        assert response.status_code == 200, response.text
        assert response.json()['plan']['site']['terraces'][0]['id'] == target
    reread = bridge.assemble(fixture, previous=twin_store.current_model())[0]
    assert next(item for item in reread['buildings'] if item['id'] == b['id'])['foundation']['mode'] == 'auto'
    print('Terrain validation, foundation migration, yard ops and history passed')


if __name__ == '__main__':
    run()
