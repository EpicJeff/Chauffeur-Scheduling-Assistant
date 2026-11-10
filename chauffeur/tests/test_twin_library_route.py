"""The editor's library route (spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md section 5.7;
plan docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md
Part B Task 15; brief .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/
task-15-brief.md).

GET /api/house/editor/library returns what the house can use, read from the
vetted library that already exists: the manifest's `material` and `model`
entries plus the style kit's roles and its plant and furniture lists, as
{materials: [{id, name, color}], items: [{id, name, kind}]}.

Readings pinned here (see the task 15 tests report):
- every manifest `material` entry is listed, and every kit role is listed with
  its asset as the id and the kit's colour (so the generator materials the kit
  uses, such as board_and_batten siding, can be put back by hand);
- every manifest `model` entry and every kit furniture asset is an item of
  kind 'furniture'; every kit shrub preset is an item of kind 'shrub' and every
  kit tree preset (backdrop and specimen) one of kind 'tree', the kind words of
  site.planting, so a dropped plant joins the yard as the composer's own do;
- names are words for people (no raw ids with underscores); colours are #rrggbb;
- HDRIs are neither materials nor items;
- nothing is downloaded to answer (the route reads the manifest and the kit);
- parents only, under the existing /api/house/editor/* rule.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_library_route.py
"""
import os
import re
import sys
import tempfile
import traceback
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_library_route_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage  # noqa: E402
from services import twin_library  # noqa: E402

KIT = 'modern_farmhouse'
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


_real_settings = storage.get_settings
PEOPLE = {}


def _enforced():
    return patch.object(storage, 'get_settings', side_effect=lambda: {**_real_settings(), 'auth_enforce': True})


def _people():
    if not PEOPLE:
        storage.add_member({'id': 'p1', 'name': 'Pat', 'role': 'parent'})
        storage.add_member({'id': 'k1', 'name': 'Kit', 'role': 'child'})
        PEOPLE['parent'] = {'X-Member-Token': storage.create_member_token('p1')}
        PEOPLE['child'] = {'X-Member-Token': storage.create_member_token('k1')}
    return PEOPLE


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app)


def _no_download(*args, **kwargs):
    raise AssertionError('the library route must not download anything')


def test_library_route_lists_materials_and_items():
    people = _people()
    client = _client()
    manifest = twin_library.manifest()
    kit = twin_library.kit(KIT)
    with _enforced(), patch.object(twin_library, '_urlopen', _no_download):
        r = client.get('/api/house/editor/library', headers=people['parent'])
        check(r.status_code == 200, ('a parent reads the library', r.status_code, r.text[:300]))
        for name, who in (('child', people['child']), ('nobody', {})):
            refused = client.get('/api/house/editor/library', headers=who)
            check(refused.status_code in (401, 403), ('parents only', name, refused.status_code))
    body = r.json()
    check(set(body) >= {'materials', 'items'}, list(body))
    materials, items = body['materials'], body['items']
    check(isinstance(materials, list) and isinstance(items, list) and materials and items, body)

    # Every entry has exactly the brief's fields, in words people read.
    for m in materials:
        check(set(m) == {'id', 'name', 'color'}, ('a material is {id, name, color}', m))
        check(isinstance(m['name'], str) and m['name'].strip() and '_' not in m['name'], ('a material name is words', m))
        check(isinstance(m['color'], str) and HEX.match(m['color']), ('a material colour is #rrggbb', m))
    for i in items:
        check(set(i) == {'id', 'name', 'kind'}, ('an item is {id, name, kind}', i))
        check(isinstance(i['name'], str) and i['name'].strip() and '_' not in i['name'], ('an item name is words', i))
    item_ids = [i['id'] for i in items]
    check(len(item_ids) == len(set(item_ids)), ('each item once', item_ids))

    # Materials: the manifest's materials, and each kit role at the kit's colour.
    material_ids = {m['id'] for m in materials}
    manifest_materials = {k for k, v in manifest.items() if v.get('kind') == 'material'}
    check(manifest_materials <= material_ids, ('every manifest material is listed', manifest_materials - material_ids))
    for role, value in kit['materials'].items():
        check(any(m['id'] == value['asset'] and m['color'].lower() == value['color'].lower() for m in materials),
              (f'the kit role {role} is listed as its asset at the kit colour', value))
    check('red_brick_03' in material_ids and 'board_and_batten' in material_ids, sorted(material_ids))

    # Items: models and kit furniture are furniture; kit plants carry the site's kind words.
    kinds = {i['id']: i['kind'] for i in items}
    models = {k for k, v in manifest.items() if v.get('kind') == 'model'}
    for asset in models | set(kit['furniture'].values()):
        check(kinds.get(asset) == 'furniture', (f'{asset} is a furniture item', kinds.get(asset)))
    for preset in kit['shrubs']:
        check(kinds.get(preset) == 'shrub', (f'{preset} is a shrub item', kinds.get(preset)))
    for preset in kit['backdrop_trees'] + kit['specimen_trees']:
        check(kinds.get(preset) == 'tree', (f'{preset} is a tree item', kinds.get(preset)))

    # Nothing else crosses over.
    hdris = {k for k, v in manifest.items() if v.get('kind') == 'hdri'}
    check(not (hdris & material_ids) and not (hdris & set(item_ids)), 'skies are not library pieces')
    check(not (models & material_ids), ('a model is not a material', models & material_ids))
    check(not (manifest_materials & set(item_ids)), ('a material is not an item', manifest_materials & set(item_ids)))


TESTS = (
    test_library_route_lists_materials_and_items,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
