"""Porch foundations: migration, validation, immutable ops and HTTP history."""
import copy
import os
import tempfile

os.environ.pop('HA_BASE_URL', None)
_data = tempfile.mkdtemp(prefix='chauffeur_porch_foundation_')
os.environ['CHAUFFEUR_DATA_DIR'] = _data
from test_twin_model_ops_more import _house, _b, _people, _client, _enforced
from services import twin_model, twin_model_bridge as bridge, twin_model_ops as ops, twin_plan, twin_store

def run():
    flat = bridge.flatten(_house())
    room = _b(flat)['rooms'][1]
    room['kind'] = 'porch'
    _b(flat)['porch'] = {'id': room['id'], 'floor': 0, 'polygon': copy.deepcopy(room['polygon']), 'columns': []}
    normalized, _ = twin_plan.normalize(flat)
    assert 'foundation' not in _b(normalized)['porch']
    model = bridge.assemble(normalized)[0]
    bid, rid = _b(model)['id'], room['id']
    porch = lambda m: next(r for r in _b(m)['rooms'] if r['id'] == rid)
    assert porch(model)['foundation']['type'] == 'posts'
    raw = copy.deepcopy(model)
    del porch(raw)['foundation']
    assert porch(twin_model.normalize(raw)[0])['foundation']['type'] == 'posts'
    change = {'op': 'set_porch_foundation', 'building': bid, 'id': rid}
    valid = {'type': 'solid', 'material': 'stone', 'lip_in': 1}
    for kind in ('posts', 'solid'):
        for material in ('stone', 'brick', 'concrete'):
            for lip in (0, .25, 1, 4):
                value = dict(valid, type=kind, material=material, lip_in=lip)
                changed = ops.apply(model, dict(change, foundation=value))[0]
                assert porch(changed)['foundation'] == value
                assert porch(model)['foundation']['type'] == 'posts'
                rendered = bridge.flatten(changed)
                assert next(p for p in _b(rendered)['porches'] if p['id'] == rid)['foundation'] == value
                assert porch(bridge.assemble(rendered)[0])['foundation'] == value
    invalid = [None, [], 'solid', {}, dict(valid, type='slab'), dict(valid, type=True),
               dict(valid, material='wood'), dict(valid, material=None)]
    invalid += [dict(valid, lip_in=v) for v in (-.01, 4.01, True, None, '1', [], float('nan'), float('inf'))]
    for value in invalid:
        try:
            ops.apply(model, dict(change, foundation=value))
        except ops.Refused:
            pass
        else:
            raise AssertionError(f'Accepted invalid foundation: {value}')
        raw = copy.deepcopy(model)
        porch(raw)['foundation'] = value
        result, notes = twin_model.normalize(raw)
        assert porch(result)['foundation']['type'] == 'posts' and any('porch foundation' in n for n in notes)
        raw = copy.deepcopy(flat)
        _b(raw)['porch']['foundation'] = value
        result, notes = twin_plan.normalize(raw)
        assert _b(result)['porch']['foundation']['type'] == 'posts' and any('porch foundation' in n for n in notes)
    defaults = ops.apply(model, dict(change, foundation={'type': 'solid'}))[0]
    assert porch(defaults)['foundation'] == valid
    # A later reader cannot overwrite the person's shelf choice.
    preserved = bridge.assemble(normalized, previous=defaults)[0]
    assert porch(preserved)['foundation'] == valid and porch(preserved)['src']['person']
    try:
        ops.apply(model, dict(change, id=_b(model)['rooms'][0]['id'], foundation=valid))
    except ops.Refused:
        pass
    else:
        raise AssertionError('A normal room acquired a porch foundation')
    base = twin_store.push_round(normalized, 'build')
    with _enforced():
        response = _client().post('/api/house/editor/op', headers=_people()['parent'], json={'op': dict(change, foundation=valid)})
        assert response.status_code == 200, response.text
        bad = _client().post('/api/house/editor/op', headers=_people()['parent'], json={'op': dict(change, foundation=dict(valid, lip_in=5))})
        assert bad.status_code == 400, bad.text
    after = response.json()['round']
    assert porch(twin_store.current_model())['foundation'] == valid
    twin_store.revert(base)
    assert porch(twin_store.current_model())['foundation']['type'] == 'posts'
    twin_store.revert(after)
    assert porch(twin_store.current_model())['foundation'] == valid
    print('Passed: porch defaults/migration, validation, ops, bridge, person preservation, HTTP, undo and redo')

if __name__ == '__main__':
    try:
        run()
    finally:
        from services import storage
        storage.db.close()
