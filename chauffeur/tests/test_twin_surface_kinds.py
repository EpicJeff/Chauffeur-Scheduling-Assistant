"""Surface tables, load repair and read-only looks through real Node/HTTP paths."""
import json
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

from test_twin_materials import API, Ctx, create, materials, seed
from services import twin_library, twin_plan, twin_surface_kinds as surfaces
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]


def test_browser_table_equals_server_table():
    code, output = run_node(PRELUDE + """
const {KINDS,PANEL_ROLES,ITEM_PARTS,BUILTIN_LOOKS}=await import(file('static/twin/surface_kinds.js'));
console.log(JSON.stringify({KINDS,PANEL_ROLES,ITEM_PARTS,BUILTIN_LOOKS}));
""", {'root': ROOT.as_posix()})
    assert code == 0, output
    expected = {key: getattr(surfaces, key) for key in ('KINDS', 'PANEL_ROLES', 'ITEM_PARTS', 'BUILTIN_LOOKS')}
    assert json.loads(output) == json.loads(json.dumps(expected))
    assert [r['kind'] for r in surfaces.KINDS] == ['trim', 'fascia', 'gutter', 'casing', 'window_frame', 'pane', 'door', 'garage_door',
        'support', 'column', 'screen', 'soffit', 'base', 'stair_tread', 'stair_rail', 'ceiling', 'roof', 'cabinet',
        'counter', 'shower_tile', 'shower_glass', 'lawn', 'water']


def test_every_role_fallback_is_a_kit_role():
    roles = twin_library.kit('modern_farmhouse')['materials']
    for row in surfaces.KINDS:
        assert 'role' not in row['fallback'] or row['fallback']['role'] in roles, row


def test_builtin_ids_validate_as_slots():
    for mid in surfaces.BUILTIN_LOOKS:
        assert twin_library.normalize_material_slot({'id': mid}) == {'id': mid}
    seed()
    try:
        twin_library.normalize_material_slot({'id': 'nope'})
    except ValueError:
        pass
    else:
        raise AssertionError('unknown material accepted')


def test_catalogue_lists_code_builtins_read_only():
    seed()
    with Ctx() as c:
        rows = c.client.get(API, headers=c.mum).json()['materials']
        builtins = [r for r in rows if r['builtin']]
        manifest_ids = [mid for mid, entry in twin_library.manifest().items() if entry['kind'] == 'material']
        kit_assets = [ref['asset'] for ref in twin_library.kit('modern_farmhouse')['materials'].values()]
        expected_ids = list(dict.fromkeys([*manifest_ids, *kit_assets, *surfaces.BUILTIN_LOOKS]))
        assert [row['id'] for row in builtins] == expected_ids
        assert [r['id'] for r in builtins[-5:]] == ['glass', 'screen', 'water', 'chain_link', 'black_metal']
        assert [r['id'] for r in twin_library.material_choices()][-5:] == ['glass', 'screen', 'water', 'chain_link', 'black_metal']
        kit_id = builtins[0]['id']
        for method, payload in (('patch', {'name': 'No'}), ('delete', None)):
            def call(mid):
                kwargs = {'headers': c.mum}
                if payload is not None:
                    kwargs['json'] = payload
                return getattr(c.client, method)(f'{API}/{mid}', **kwargs)
            expected = call(kit_id).status_code
            assert expected == 400
            for mid in surfaces.BUILTIN_LOOKS:
                row = next(r for r in builtins if r['id'] == mid)
                assert row['source'] == 'builtin' and row['revision'] == 0
                assert call(mid).status_code == expected
                assert materials.get(mid)['params']['alpha_mode'] == {'chain_link': 'cutout', 'black_metal': 'opaque'}.get(mid, 'blend')


def test_black_metal_is_an_opaque_named_look_and_copies_as_one():
    seed()
    source = materials.get('black_metal')
    assert source['name'] == 'Black metal' and source['maps'] == {}
    params = source['params']
    assert (params['tint'], params['alpha_mode'], params['opacity'], params['roughness'], params['metalness']) == (
        '#1b1c1e', 'opaque', 1, .42, 0)
    with Ctx() as c:
        response = c.client.post(f'{API}/black_metal/duplicate', headers=c.mum)
        assert response.status_code == 200, response.text
        copied = materials.get(response.json()['id'])
        assert copied['params'] == params and copied['maps'] == {} and copied['name'] == 'Black metal copy'


def test_chain_link_copy_keeps_the_generated_cutout():
    from PIL import Image
    seed()
    source = materials.get('chain_link')
    assert source['name'] == 'Chain link'
    assert source['params']['tile_ft'] == [1 / 3, 1 / 3]
    assert source['params']['alpha_cutoff'] == .5
    assert 'transmission' not in source['params']
    with Ctx() as c:
        response = c.client.post(f'{API}/chain_link/duplicate', headers=c.mum)
        assert response.status_code == 200, response.text
        copied = materials.get(response.json()['id'])
        assert copied['params'] == source['params']
        assert copied['maps'].keys() == {'opacity'}
        with Image.open(materials.root() / copied['id'] / copied['maps']['opacity']) as mask:
            assert mask.size == (256, 256)
            assert mask.convert('L').getpixel((20, 20)) == 255
            assert mask.convert('L').getpixel((32, 64)) == 0
            assert mask.convert('L').getpixel((160, 192)) == 0


def test_load_resets_an_unknown_house_default():
    seed()
    raw = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    raw, _ = twin_plan.normalize(raw)  # Finish legacy awning migration before injecting the corrupt slot.
    raw['buildings'][0]['materials'] = {'pane': {'id': 'nope'}, 'column': {'id': 'glass'},
                                         'custom_role': {'id': 'trim'}}
    plan, notes = twin_plan.normalize(raw)
    assert plan['buildings'][0]['materials'] == {'column': {'id': 'glass'}, 'custom_role': {'id': 'trim'}}
    assert len(notes) == 1 and 'pane' in notes[0].lower(), notes


def test_clean_slots_filters_only_when_given_and_notes_each_reset():
    seed()
    notes = []
    slots = {'pane': {'id': 'glass'}, 'custom': {'id': 'trim'}, 'bad': {'id': 'missing'}, 'null': None}
    assert surfaces.clean_slots(slots, None, notes, 'House') == {'pane': {'id': 'glass'}, 'custom': {'id': 'trim'}}
    assert len(notes) == 1, notes
    assert surfaces.clean_slots(slots, ('pane',), [], 'House') == {'pane': {'id': 'glass'}}
    notes = []
    assert surfaces.clean_slots([], None, notes, 'House') == {} and len(notes) == 1


def test_delete_refusal_names_new_surfaces():
    seed()
    with Ctx() as c:
        row = create(c)
        model = {'buildings': [{'materials': {'pane': {'id': row['id']}, 'column': {'id': row['id']}}},
                               {'materials': {'pane': {'id': row['id']}}}]}
        with patch.object(materials.twin_store, 'current_model', return_value=model):
            response = c.client.delete(f"{API}/{row['id']}", headers=c.mum)
        assert response.status_code == 400, response.text
        detail = response.json()['detail']
        assert detail == 'Used on 3 surfaces: House panes (2), House columns (1)', detail
        assert surfaces.label('pane') == 'Panes' and surfaces.label('column') == 'Columns'


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=8)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
