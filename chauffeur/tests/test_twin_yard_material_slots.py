"""Yard material slots: one op per change, Library ids only, null returns the default look.

The user, 2026-11-13: "Why doesn't everything just have a material slot you can assign a
material from the library to?" Covers fences, fire pits, patios and paths, planting beds and
retaining walls through the real ops, the store's history, the model bridge and the parent
HTTP gate. Saved models without slots load unchanged.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
DATA = tempfile.mkdtemp(prefix='chauffeur_yard_slots_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
from services import twin_model_bridge as bridge, twin_model_ops as ops, twin_plan, twin_store

BRICK = {'id': 'red_brick_03', 'color': '#aa3322'}
OAK = {'id': 'mocha_oak_veneer'}
RECT = [[5, 5], [15, 5], [15, 10], [5, 10]]


def _model():
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = bridge.assemble(fixture)[0]
    model['site'].update(lot=[[0, 0], [40, 0], [40, 40], [0, 40]],
        beds=[{'id': 'bed', 'polygon': RECT, 'material': 'mulch'}],
        pool={'id': 'pool', 'polygon': RECT, 'material': 'paving'},
        edges=[{'id': 'edge', 'polygon': RECT, 'material': 'lawn'}],
        hardscape=[{'id': 'patio', 'polygon': RECT}, {'id': 'walk', 'kind': 'path', 'points': [[2, 20], [12, 20]], 'width': 3, 'edging': 'curb'}],
        fire_pit=[{'id': 'pit', 'at': [20, 20], 'radius': 2, 'fuel': 'wood', 'top': 'concrete'}],
        fence=[{'id': 'fence', 'polyline': [[2, 2], [30, 2]], 'height': 6}],
        terraces=[{'id': 'pad', 'polygon': [[20, 30], [30, 30], [30, 38], [20, 38]], 'height': 2, 'blend': 0,
                   'edges': [{'edge': 'sharp', 'wall': {'material': 'block', 'thickness_in': 8, 'above_in': 0}},
                             {'edge': 'slope'}, {'edge': 'slope'}, {'edge': 'slope'}]}])
    return model


def _piece(model, name, pid):
    if isinstance(model['site'][name], dict):
        assert model['site'][name]['id'] == pid
        return model['site'][name]
    return next(p for p in model['site'][name] if p['id'] == pid)


def _refused(model, op):
    try:
        ops.apply(model, op)
    except ops.Refused as exc:
        return str(exc)
    raise AssertionError(f'accepted {op}')


def test_each_feature_takes_its_parts_and_null_returns_the_default():
    model = _model()
    original = copy.deepcopy(model)
    for name, pid, slots in [('fence', 'fence', {'boards': BRICK, 'posts': OAK, 'rails': OAK}),
                             ('fire_pit', 'pit', {'body': BRICK, 'top': OAK}),
                             ('hardscape', 'patio', {'surface': BRICK}),
                             ('hardscape', 'walk', {'surface': BRICK, 'edging': OAK}),
                             ('beds', 'bed', {'fill': BRICK}),
                             ('pool', 'pool', {'coping': BRICK, 'interior': OAK}),
                             ('edges', 'edge', {'strip': BRICK})]:
        changed, words = ops.apply(model, {'op': 'update_site_shape', 'list': name, 'id': pid, 'materials': slots})
        assert _piece(changed, name, pid)['materials'] == slots, (name, _piece(changed, name, pid))
        assert words
        # A partial change keeps the other parts; null resets one part; the last null drops the field.
        first, *rest = slots
        partial, _ = ops.apply(changed, {'op': 'update_site_shape', 'list': name, 'id': pid, 'materials': {first: None}})
        assert _piece(partial, name, pid).get('materials', {}) == {k: slots[k] for k in rest}
        cleared, _ = ops.apply(changed, {'op': 'update_site_shape', 'list': name, 'id': pid, 'materials': {k: None for k in slots}})
        assert 'materials' not in _piece(cleared, name, pid)
        # The bridge round trip keeps the slots.
        assert bridge.flatten(bridge.assemble(bridge.flatten(changed))[0])['site'][name] == bridge.flatten(changed)['site'][name]
    assert model == original, 'no input mutation'


def test_unknown_parts_ids_and_features_are_refused():
    model = _model()
    assert 'boards, posts, rails' in _refused(model, {'op': 'update_site_shape', 'list': 'fence', 'id': 'fence', 'materials': {'body': BRICK}})
    assert 'Unknown material id' in _refused(model, {'op': 'update_site_shape', 'list': 'beds', 'id': 'bed', 'materials': {'fill': {'id': 'gold'}}})
    _refused(model, {'op': 'update_site_shape', 'list': 'beds', 'id': 'bed', 'materials': {'fill': {'id': 'red_brick_03', 'shine': 1}}})
    _refused(model, {'op': 'update_site_shape', 'list': 'beds', 'id': 'bed', 'materials': ['fill']})
    from services import twin_site_shapes
    for name, pid, part in [('pool', 'pool', 'water'), ('edges', 'edge', 'fill')]:
        _refused(model, {'op': 'update_site_shape', 'list': name, 'id': pid, 'materials': {part: BRICK}})
        for bad in ({'id': 'gold'}, {'id': 'red_brick_03', 'shine': 1}, 'red_brick_03'):
            _refused(model, {'op': 'update_site_shape', 'list': name, 'id': pid,
                             'materials': {('coping' if name == 'pool' else 'strip'): bad}})
    for name in ('yard_rooms',):
        try:
            twin_site_shapes.material_slots(name, {})
        except ValueError:
            pass
        else:
            raise AssertionError(f'{name} has no material slots yet')


def test_retaining_wall_face_slot_through_update_pad():
    model = _model()
    edges = copy.deepcopy(_piece(model, 'terraces', 'pad')['edges'])
    edges[0]['wall']['materials'] = {'face': BRICK}
    changed, _ = ops.apply(model, {'op': 'update_pad', 'id': 'pad', 'edges': edges})
    wall = _piece(changed, 'terraces', 'pad')['edges'][0]['wall']
    assert wall['materials'] == {'face': BRICK} and wall['material'] == 'block', wall
    edges[0]['wall']['materials'] = {'face': None}
    cleared, _ = ops.apply(changed, {'op': 'update_pad', 'id': 'pad', 'edges': edges})
    assert 'materials' not in _piece(cleared, 'terraces', 'pad')['edges'][0]['wall']
    for bad in ({'face': {'id': 'gold'}}, {'top': BRICK}, ['face']):
        edges[0]['wall']['materials'] = bad
        assert 'Library material' in _refused(model, {'op': 'update_pad', 'id': 'pad', 'edges': edges})


def test_saved_models_load_unchanged_and_a_missing_material_resets_only_the_slot():
    model = bridge.flatten(_model())
    plain = copy.deepcopy(model)
    normalized, notes = twin_plan.normalize(copy.deepcopy(model))
    for name in ('fence', 'fire_pit', 'hardscape', 'beds', 'terraces'):
        assert normalized['site'][name] == twin_plan.normalize(plain)[0]['site'][name]
        assert all('materials' not in piece for piece in normalized['site'][name])
    assert normalized['site']['pool'] == plain['site']['pool']
    assert normalized['site']['edges'] == plain['site']['edges']
    model['site']['pool']['materials'] = {'interior': {'id': 'retired_material'}}
    model['site']['edges'][0]['materials'] = {'strip': {'id': 'retired_material'}}
    model['site']['beds'][0]['materials'] = {'fill': {'id': 'retired_material'}}
    model['site']['fence'][0]['materials'] = {'boards': BRICK}
    model['site']['terraces'][0]['edges'][0]['wall']['materials'] = {'face': {'id': 'retired_material'}}
    normalized, notes = twin_plan.normalize(model)
    assert normalized['site']['beds'] and 'materials' not in normalized['site']['beds'][0], 'the bed stays; its slot resets'
    assert normalized['site']['fence'][0]['materials'] == {'boards': BRICK}
    assert normalized['site']['pool'] and 'materials' not in normalized['site']['pool']
    assert normalized['site']['edges'] and 'materials' not in normalized['site']['edges'][0]
    assert all(any(f'Reset {name} materials' in n for n in notes) for name in ('pool', 'edges'))
    pad = normalized['site']['terraces'][0]
    assert pad['edges'][0]['wall']['material'] == 'block' and 'materials' not in pad['edges'][0]['wall']
    assert any('Reset beds materials' in n for n in notes) and any('retaining wall materials' in n for n in notes), notes


def test_history_and_parent_http():
    model = _model()
    twin_store.push_round(bridge.flatten(model), 'build')
    from test_twin_model_ops_more import _client, _people, _enforced
    tokens, client = _people(), _client()
    op = {'op': 'update_site_shape', 'list': 'fence', 'id': 'fence', 'materials': {'boards': BRICK}}
    with _enforced():
        before = twin_store.current_id()
        response = client.post('/api/house/editor/op', headers=tokens['child'], json={'op': op})
        assert response.status_code == 403 and twin_store.current_id() == before
        bad = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': dict(op, materials={'boards': {'id': 'gold'}})})
        assert bad.status_code == 400 and twin_store.current_id() == before, bad.text
        response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': op})
        assert response.status_code == 200, response.text
        fence = response.json()['plan']['site']['fence']
        assert (fence[0] if isinstance(fence, list) else fence)['materials'] == {'boards': BRICK}
    after = twin_store.current_id()
    twin_store.revert(before)
    assert 'materials' not in _piece(twin_store.current_model(), 'fence', 'fence')
    twin_store.revert(after)
    assert _piece(twin_store.current_model(), 'fence', 'fence')['materials'] == {'boards': BRICK}


def test_pool_and_edge_parent_http_history_and_room_source():
    from test_twin_model_ops_more import _client, _people, _enforced
    tokens, client = _people(), _client()
    for name, pid, slots in [('pool', 'pool', {'coping': BRICK, 'interior': OAK}), ('edges', 'edge', {'strip': BRICK})]:
        twin_store.push_round(bridge.flatten(_model()), 'build')
        op = {'op': 'update_site_shape', 'list': name, 'id': pid, 'materials': slots}
        before, count = twin_store.current_id(), len(twin_store.rounds())
        with _enforced():
            assert client.post('/api/house/editor/op', headers=tokens['child'], json={'op': op}).status_code == 403
            bad = dict(op, materials={next(iter(slots)): {'id': 'gold'}})
            assert client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': bad}).status_code == 400
            assert twin_store.current_id() == before
            response = client.post('/api/house/editor/op', headers=tokens['parent'], json={'op': op})
            assert response.status_code == 200, response.text
        after = twin_store.current_id()
        assert len(twin_store.rounds()) == count + 1
        assert _piece(twin_store.current_model(), name, pid)['materials'] == slots
        twin_store.revert(before)
        assert 'materials' not in _piece(twin_store.current_model(), name, pid)
        twin_store.revert(after)
        assert _piece(twin_store.current_model(), name, pid)['materials'] == slots
    for name, pid in [('pool', 'pool'), ('hardscape', 'patio'), ('fire_pit', 'pit')]:
        made, _ = ops.apply(_model(), {'op': 'make_yard_room', 'list': name, 'id': pid})
        room = made['site']['yard_rooms'][-1]
        assert room['feature'] == {'list': name, 'id': pid}
        loaded, notes = twin_plan.normalize(bridge.flatten(made))
        assert loaded['site']['yard_rooms'][-1]['feature'] == room['feature'], notes


if __name__ == '__main__':
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    try:
        for test in tests:
            try:
                test()
                passed += 1
                print('ok  ', test.__name__)
            except Exception:
                print('FAIL', test.__name__)
                traceback.print_exc(limit=6)
    finally:
        from services import storage
        storage.db.close()
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
