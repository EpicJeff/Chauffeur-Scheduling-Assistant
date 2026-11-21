"""Slice 7 storage contract, exercised through real operations and HTTP history.

Run from chauffeur/: python tests/test_twin_surface_slots_ops.py
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_surface_slots_')

from services import twin_library, twin_model, twin_model_bridge as bridge
from services import twin_model_ops as ops, twin_model_roofs as roofs, twin_plan, twin_store
from test_twin_model_ops_more import _house, _client, _people, _enforced

HOUSEHOLD = ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json'
UV = {'u': .25, 'v': .75, 'rot': 90}
REF = {'id': 'wood_floor', 'color': '#123456', 'uv': UV}
SITE_ROLES = ('lawn', 'water', 'paving', 'mulch', 'patio_concrete', 'fence',
              'pool_interior', 'pool_waterline', 'pool_coping')


def household():
    return json.loads(HOUSEHOLD.read_text(encoding='utf-8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def refused(model, op):
    before = copy.deepcopy(model)
    try:
        ops.apply(model, op)
    except ops.Refused:
        assert model == before
    else:
        raise AssertionError(f'Accepted {op!r}')


def roof_model():
    model = _house()
    model['buildings'][0]['roofs'] = [roofs.from_section({
        'id': 'roof', 'rect': [0, 0, 20, 10], 'kind': 'hip', 'ridge': 'x',
        'pitch': 8, 'plate': 9, 'overhang': 1})]
    return model


def test_slot_refs_inherit_tint_uv_wrap_and_detach():
    for ref in ({'id': 'wood_floor'}, {'color': '#123456'}, {'uv': UV}, REF):
        got = twin_library.normalize_material_slot(ref)
        assert got == ref
        assert got is not ref
        if 'uv' in ref:
            assert got['uv'] is not ref['uv']
    assert twin_library.normalize_material_slot({}) is None
    assert twin_library.normalize_material_slot(None) is None
    assert twin_library.normalize_material_slot({'uv': {'u': 1, 'v': 1, 'rot': 270}}) == {
        'uv': {'u': 0, 'v': 0, 'rot': 270}}
    for ref in ('wood_floor', [], {'id': ''}, {'id': None}, {'id': 'unknown'},
                {'color': ''}, {'color': True}, {'shine': 1}, {'uv': None},
                {'uv': {}}, {'uv': {**UV, 'extra': 1}}):
        try:
            twin_library.normalize_material_slot(ref)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Accepted {ref!r}')


def test_every_set_material_target_carries_inherited_refs_and_clear():
    model = roof_model()
    building = model['buildings'][0]
    building['dormers'] = [{'id': 'dormer', 'roof': 'roof', 'edge': 0, 'at': 6,
                            'width': 3, 'pitch': 8, 'plate_offset': 0}]
    model, _ = ops.apply(model, {'op': 'add_opening', 'building': 'B1', 'wall': 's1',
                                'kind': 'door', 'at': 4, 'width': 3, 'sill': 0, 'head': 7})
    opening = model['buildings'][0]['openings'][0]['id']
    targets = [({'wall': 'mid', 'side': side}, lambda b, side=side: b['walls'][6].get('faces', {}).get(side))
               for side in ('left', 'right')]
    for surface, field in [('floor', 'floor_material'), ('ceiling', 'ceiling_material'), ('walls', 'wall_material')]:
        targets.append(({'room': 'kitchen', 'surface': surface},
                        lambda b, field=field: next(r for r in b['rooms'] if r['id'] == 'kitchen').get(field)))
    targets += [({'roof': 'roof'}, lambda b: b['roofs'][0].get('material')),
                ({'roof': 'roof', 'plane': 2}, lambda b: b['roofs'][0].get('plane_materials', {}).get('2')),
                ({'dormer': 'dormer'}, lambda b: b['dormers'][0].get('material')),
                ({'opening': opening, 'part': 'door'}, lambda b: b['openings'][0].get('materials', {}).get('door')),
                ({'level': 'L1', 'role': 'floor'}, lambda b: b['levels'][0].get('materials', {}).get('floor')),
                ({'building': 'B1', 'role': 'floor'}, lambda b: b.get('materials', {}).get('floor'))]
    for target, read in targets:
        for ref in ({'color': '#abcdef'}, {'uv': UV}, REF):
            changed, _ = ops.apply(model, {'op': 'set_material', 'building': 'B1', 'target': target, 'material': ref})
            assert read(changed['buildings'][0]) == ref, target
            loaded = twin_model.normalize(json.loads(json.dumps(changed)))[0]
            assert read(loaded['buildings'][0]) == ref, target
            flat = twin_plan.normalize(bridge.flatten(loaded))[0]
            if 'plane' in target:
                assert flat['buildings'][0]['roof']['sections'][0]['plane_materials']['2'] == ref
            for empty in (None, {}):
                cleared, _ = ops.apply(changed, {'op': 'set_material', 'building': 'B1', 'target': target, 'material': empty})
                assert read(cleared['buildings'][0]) is None, target


def test_site_roles_and_invalid_uv_planes_are_refused_through_ops():
    model = roof_model()
    for role in SITE_ROLES:
        changed, _ = ops.apply(model, {'op': 'set_material', 'target': {'site': True, 'role': role}, 'material': REF})
        assert changed['materials'][role] == REF
        assert twin_model.normalize(changed)[0]['materials'][role] == REF
        cleared, _ = ops.apply(changed, {'op': 'set_material', 'target': {'site': True, 'role': role}, 'material': {}})
        assert role not in cleared['materials']
    for role in ('roof', 'pool', '', None, 'pool-interior'):
        refused(model, {'op': 'set_material', 'target': {'site': True, 'role': role}, 'material': REF})
    for index in (-1, 4, True, 1.0, '1', None):
        refused(model, {'op': 'set_material', 'building': 'B1', 'target': {'roof': 'roof', 'plane': index}, 'material': REF})
    for field, values in [('u', [-.01, 1.01, True, '0', None, float('inf'), float('nan')]),
                          ('v', [-1, 2, False, '0', None]), ('rot', [-90, 45, 360, True, '90', None])]:
        for value in values:
            refused(model, {'op': 'set_material', 'building': 'B1', 'target': {'roof': 'roof', 'plane': 0},
                            'material': {'uv': {**UV, field: value}}})


def test_pool_ledge_steps_partial_slots_load_and_clear():
    model = roof_model()
    model['site']['pool'] = {'id': 'pool', 'polygon': [[0, 0], [30, 0], [30, 20], [0, 20]]}
    for kind in ('ledge', 'steps', 'spa'):
        model, _ = ops.apply(model, {'op': 'add_pool_feature', 'kind': kind,
            'polygon': [[0, 0], [6, 0], [6, 4], [0, 4]], 'materials': {'interior': REF}})
        feature = model['site']['pool']['features'][-1]
        model, _ = ops.apply(model, {'op': 'update_pool_feature', 'id': feature['id'], 'materials': {'coping': {'uv': UV}}})
        expected = {'interior': REF, 'coping': {'uv': UV}}
        assert model['site']['pool']['features'][-1]['materials'] == expected
        flat = twin_plan.normalize(bridge.flatten(model))[0]
        assert flat['site']['pool']['features'][-1]['materials'] == expected
        assert bridge.assemble(flat)[0]['site']['pool']['features'][-1]['materials'] == expected
        if kind != 'spa':
            refused(model, {'op': 'update_pool_feature', 'id': feature['id'], 'materials': {'water': REF}})
        for part in ('interior', 'coping'):
            model, _ = ops.apply(model, {'op': 'update_pool_feature', 'id': feature['id'], 'materials': {part: {}}})
        assert 'materials' not in model['site']['pool']['features'][-1]


def test_existing_item_yard_foundation_and_pad_slots_keep_the_ref_contract():
    from test_twin_item_slots import fixture, targets
    from services.twin_surface_kinds import ITEM_PARTS
    model = fixture()
    for kind, collection, pid in targets(model):
        for part in ITEM_PARTS['fixture' if kind == 'item' else kind]:
            changed, _ = ops.apply(model, {'op': 'set_material', 'building': model['buildings'][0]['id'],
                'target': {kind: pid, 'part': part}, 'material': {'uv': UV}})
            loaded = twin_model.normalize(changed)[0]
            assert loaded['buildings'][0][collection][0]['materials'][part] == {'uv': UV}
    porch = next(r for r in model['buildings'][0]['rooms'] if r.get('kind') == 'porch')
    changed, _ = ops.apply(model, {'op': 'set_porch_foundation', 'building': model['buildings'][0]['id'],
        'id': porch['id'], 'foundation': {'type': 'posts', 'materials': {'posts': {'uv': UV}, 'skirt': {'color': '#abcdef'}}}})
    loaded = twin_model.normalize(changed)[0]
    saved = next(r for r in loaded['buildings'][0]['rooms'] if r['id'] == porch['id'])
    assert saved['foundation']['materials']['posts'] == {'uv': UV}
    assert saved['foundation']['materials']['skirt'] == {'color': '#abcdef'}
    from test_twin_yard_material_slots import _model, _piece
    model = _model()
    from services import twin_site_shapes
    for name, pid in [('fence', 'fence'), ('hardscape', 'walk'), ('beds', 'bed'), ('pool', 'pool'),
                      ('edges', 'edge'), ('fire_pit', 'pit')]:
        for part in twin_site_shapes.SLOTS[name]:
            changed, _ = ops.apply(model, {'op': 'update_site_shape', 'list': name, 'id': pid,
                                          'materials': {part: {'uv': UV}}})
            assert _piece(twin_model.normalize(changed)[0], name, pid)['materials'][part] == {'uv': UV}
    changed, _ = ops.apply(model, {'op': 'set_foundation', 'building': model['buildings'][0]['id'],
        'foundation': {**model['buildings'][0]['foundation'], 'materials': {'slab': {'uv': UV}}}})
    assert changed['buildings'][0]['foundation']['materials']['slab'] == {'uv': UV}
    edges = copy.deepcopy(_piece(model, 'terraces', 'pad')['edges'])
    edges[0]['wall']['materials'] = {'face': {'color': '#abcdef'}, 'cap': {'uv': {'u': 1, 'v': 1, 'rot': 0}}}
    changed, _ = ops.apply(model, {'op': 'update_pad', 'id': 'pad', 'edges': edges})
    wall = _piece(changed, 'terraces', 'pad')['edges'][0]['wall']
    assert wall['materials']['cap'] == {'uv': {'u': 0, 'v': 0, 'rot': 0}}
    edges[0]['wall']['materials'] = {'face': {}, 'cap': {}}
    cleared, _ = ops.apply(changed, {'op': 'update_pad', 'id': 'pad', 'edges': edges})
    assert 'materials' not in _piece(cleared, 'terraces', 'pad')['edges'][0]['wall']


def test_roof_section_mapping_uses_area_edge_index_and_keeps_refs():
    shapes = [r for b in bridge.assemble(household())[0]['buildings'] for r in b['roofs']]
    shapes += [dict(roof_model()['buildings'][0]['roofs'][0],
        area=[[0, 0], [20, 0], [20, 10], [10, 10], [10, 20], [0, 20]],
        edges=[{'setting': 'sloped', 'pitch': 8}] * 6)]
    for roof in shapes:
        roof['plane_materials'] = {str(i): {'color': f'#{i:06x}'} for i in range(len(roof['edges']))}
        for section in roofs.to_sections(roof):
            assert section['plane_materials'] == roof['plane_materials']
            assert section['plane_materials'] is not roof['plane_materials']
            assert set(section['plane_edges']) == {'y0', 'x1', 'y1', 'x0'}
            x0, y0, x1, y1 = section['rect']
            segments = {'y0': ([x0, y0], [x1, y0]), 'x1': ([x1, y0], [x1, y1]),
                        'y1': ([x1, y1], [x0, y1]), 'x0': ([x0, y1], [x0, y0])}
            for side, (a, b) in segments.items():
                axis = 0 if a[0] == b[0] else 1
                candidates = []
                for i, (p, q) in enumerate(zip(roof['area'], roof['area'][1:] + roof['area'][:1])):
                    if p[axis] == q[axis] == a[axis]:
                        overlap = min(max(a[1-axis], b[1-axis]), max(p[1-axis], q[1-axis])) - max(min(a[1-axis], b[1-axis]), min(p[1-axis], q[1-axis]))
                        if overlap > 1e-8:
                            candidates.append((overlap, -i))
                assert section['plane_edges'][side] == (-max(candidates)[1] if candidates else None)
            assert 'plane_edges' not in roofs.from_section(section), 'derived side map is not authored data'
    section = roofs.to_sections(roof_model()['buildings'][0]['roofs'][0])[0]
    assert section['plane_edges'] == {'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3}


def test_flat_roof_import_keeps_the_material_on_its_original_side():
    for area in ([[20, 0], [20, 10], [0, 10], [0, 0]],
                 [[0, 0], [20, 0], [20, 10], [10, 10], [10, 20], [0, 20]]):
        model = roof_model()
        roof = model['buildings'][0]['roofs'][0]
        roof['area'] = area
        roof['edges'] = [{'setting': 'sloped', 'pitch': 8}] * len(area)
        roof['plane_materials'] = {str(i): {'color': f'#{i:06x}', 'uv': UV} for i in range(len(area))}
        def by_side(plan):
            return {(tuple(s['rect']), side): s.get('plane_materials', {}).get(str(edge))
                    for b in plan['buildings'] for s in b['roof']['sections']
                    for side, edge in s['plane_edges'].items()}
        flat = bridge.flatten(model)
        imported = bridge.assemble(twin_plan.normalize(json.loads(json.dumps(flat)))[0])[0]
        assert by_side(bridge.flatten(imported)) == by_side(flat)


def test_normalizers_repair_only_bad_slots_and_keep_unset_house_bytes():
    # Captured before implementation from the exact fixture seeded by the live harness.
    assert digest(twin_plan.normalize(household())[0]) == 'cd9e31d8eccfb6be73672c4682a53821c956f44adba0f0e8ff8ba6b37407d492'
    model = bridge.assemble(household())[0]
    assert digest(twin_model.normalize(model)[0]) == '12fba9dc2b33b032a6ff9ccd9e98a863f58286de8f509948e3dda9368c2b27cc'
    raw = roof_model()
    b = raw['buildings'][0]
    b['roofs'][0]['plane_materials'] = {'0': REF, '1': {}, '4': REF, '-1': REF, '01': REF, '2': {'uv': {**UV, 'rot': 42}}}
    b['walls'][0]['faces'] = {'left': {'uv': UV}, 'right': {'uv': {**UV, 'rot': 42}}}
    b['rooms'][0]['floor_material'] = {}
    raw['materials'] = {'paving': REF, 'mulch': {'uv': {**UV, 'u': -1}}}
    cleaned, notes = twin_model.normalize(raw)
    assert cleaned['buildings'][0]['roofs'][0]['plane_materials'] == {'0': REF}
    assert cleaned['buildings'][0]['walls'][0]['faces'] == {'left': {'uv': UV}}
    assert 'floor_material' not in cleaned['buildings'][0]['rooms'][0]
    assert cleaned['materials'] == {'paving': REF}
    assert notes


def test_http_save_load_and_undo_redo_carry_all_new_shapes():
    twin_store.push_round(household(), 'build')
    with _enforced():
        client, headers = _client(), _people()['parent']
        model = twin_store.current_model()
        building = model['buildings'][0]
        roof = building['roofs'][0]
        edits = [{'op': 'set_material', 'building': building['id'], 'target': {'roof': roof['id'], 'plane': 0}, 'material': REF}]
        edits += [{'op': 'set_material', 'target': {'site': True, 'role': role}, 'material': {'uv': UV}} for role in SITE_ROLES]
        for kind in ('ledge', 'steps'):
            # Use the real pool outline to ensure these are valid household feature edits.
            edits.append({'op': 'add_pool_feature', 'kind': kind, 'polygon': copy.deepcopy(model['site']['pool']['polygon']),
                          'materials': {'interior': {'color': '#abcdef'}, 'coping': REF}})
        for op in edits:
            before_id = twin_store.current_id()
            before = copy.deepcopy(twin_store.current_model())
            response = client.post('/api/house/editor/op', headers=headers, json={'op': op})
            assert response.status_code == 200, response.text
            after_id = twin_store.current_id()
            after = copy.deepcopy(twin_store.current_model())
            assert after != before
            for round_id, expected in ((before_id, before), (after_id, after)):
                response = client.post('/api/house/twin/revert', headers=headers, json={'round': round_id})
                assert response.status_code == 200, response.text
                assert twin_store.current_model() == expected
        for feature in twin_store.current_model()['site']['pool']['features']:
            before_id = twin_store.current_id()
            previous = copy.deepcopy(feature['materials'])
            response = client.post('/api/house/editor/op', headers=headers, json={'op': {
                'op': 'update_pool_feature', 'id': feature['id'], 'materials': {'interior': None, 'coping': {'uv': UV}}}})
            assert response.status_code == 200, response.text
            updated_id = twin_store.current_id()
            for round_id, expected in ((before_id, previous), (updated_id, {'coping': {'uv': UV}})):
                response = client.post('/api/house/twin/revert', headers=headers, json={'round': round_id})
                assert response.status_code == 200, response.text
                current = next(f for f in twin_store.current_model()['site']['pool']['features'] if f['id'] == feature['id'])
                assert current['materials'] == expected


if __name__ == '__main__':
    failed = 0
    for name, test in list(globals().items()):
        if name.startswith('test_') and callable(test):
            try:
                test()
                print(f'PASS {name}')
            except Exception:
                failed += 1
                print(f'FAIL {name}')
                traceback.print_exc()
    sys.exit(bool(failed))
