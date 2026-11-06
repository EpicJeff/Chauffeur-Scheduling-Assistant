"""The twin's vetted asset library and the first style kit (spec
docs/superpowers/specs/2026-11-06-house-digital-twin-design.md sections
8.4, 8.5; plan Task 4).

Run from chauffeur/:  python tests/test_twin_library.py
"""
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_library_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_library as tl  # noqa: E402
from services import twin_store as ts  # noqa: E402


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


EZ_TREE_PRESETS = {'Ash Large', 'Ash Medium', 'Ash Small', 'Aspen Large', 'Aspen Medium', 'Aspen Small',
                   'Bush 1', 'Bush 2', 'Bush 3', 'Oak Large', 'Oak Medium', 'Oak Small',
                   'Pine Large', 'Pine Medium', 'Pine Small'}
FIXTURE_ROLES = {'siding', 'trim', 'roof', 'base', 'window_frame', 'door', 'floor',
                 'interior_wall', 'porch_ceiling', 'paving'}


class _Resp:
    def __init__(self, data):
        self._d = data

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub_fetch(fail=False):
    seen = []

    def opener(req, timeout=None):
        seen.append(req)
        if fail:
            raise OSError('network down')
        return _Resp(b'BYTES:' + req.full_url.encode())
    return seen, opener


def _clear_library():
    shutil.rmtree(os.path.join(ts.DATA_DIR, 'library'), ignore_errors=True)


def scenario_manifest_is_licensed_and_complete():
    m = tl.manifest()
    check(isinstance(m, dict) and len(m) >= 12, f'a real set of assets: {len(m)}')
    for aid, e in m.items():
        check(e['kind'] in ('material', 'model', 'hdri', 'geometry'), (aid, e['kind']))
        check(e['licence'] in ('CC0', 'MIT'), (aid, e['licence']))
        if e['kind'] == 'geometry':
            continue      # drawn by the generator (siding battens, standing seams); no files
        check(e['source'] and e['source_id'] and e.get('page', '').startswith('http'), (aid, e))
        check(e['files'] and all(u.startswith('https://') for u in e['files'].values()), (aid, e['files']))
        check('cost' in e, (aid, 'cost'))
    kinds = {e['kind'] for e in m.values()}
    check({'material', 'model', 'hdri'} <= kinds, kinds)


def scenario_kit_references_resolve():
    k = tl.kit('modern_farmhouse')
    m = tl.manifest()
    check(k['id'] == 'modern_farmhouse', k['id'])
    check(FIXTURE_ROLES <= set(k['materials']), f'every fixture role has a kit material: {set(k["materials"])}')
    for role, ref in k['materials'].items():
        check(ref['asset'] in m and ref['color'].startswith('#') and len(ref['color']) == 7, (role, ref))
    for role, aid in k['furniture'].items():
        check(aid in m and m[aid]['kind'] == 'model', (role, aid))
    for key in ('shrubs', 'backdrop_trees', 'specimen_trees'):
        check(k[key] and set(k[key]) <= EZ_TREE_PRESETS, (key, k[key]))
    check(isinstance(k['style_guide'], str) and len(k['style_guide']) > 200, 'a real brief for the critic')
    check(k['composition'] == {
        'foundation_bed_depth_ft': 5, 'shrub_spacing_ft': 3.5, 'shrub_height_ft': [3, 4.5],
        'group_sizes': [3, 5], 'door_clearance_ft': 3, 'pool_clearance_ft': 2,
        'backdrop_min_building_ft': 25, 'backdrop_spacing_ft': 16, 'backdrop_jitter_ft': 4,
        'backdrop_rows': 2, 'backdrop_row_gap_ft': 10, 'backdrop_height_ft': [45, 70]}, k['composition'])


def scenario_unknown_kit_raises():
    try:
        tl.kit('nope')
    except KeyError:
        return
    raise AssertionError('unknown kit raises KeyError')


def scenario_ensure_downloads_once():
    _clear_library()
    m = tl.manifest()
    aid = next(a for a, e in m.items() if e['kind'] == 'material')
    seen, opener = _stub_fetch()
    orig = tl._urlopen
    tl._urlopen = opener
    try:
        d1 = tl.ensure(aid)
        n = len(seen)
        d2 = tl.ensure(aid)
    finally:
        tl._urlopen = orig
    check(d1 == d2 == os.path.join(ts.DATA_DIR, 'library', aid), d1)
    check(n == len(m[aid]['files']) and len(seen) == n, f'one fetch per file, none the second time: {len(seen)}')
    check(all(r.get_header('User-agent') for r in seen), 'every request carries a User-Agent')
    for name in m[aid]['files']:
        check(os.path.exists(os.path.join(d1, name)), name)


def scenario_missing_asset_falls_back():
    _clear_library()
    m = tl.manifest()
    aid = next(a for a, e in m.items() if e['kind'] == 'material')
    _, opener = _stub_fetch(fail=True)
    orig = tl._urlopen
    tl._urlopen = opener
    try:
        try:
            tl.ensure(aid)
        except OSError:
            pass
        else:
            raise AssertionError('a failed fetch raises')
        check(not os.path.exists(os.path.join(ts.DATA_DIR, 'library', aid)), 'no partial directory left behind')
        from fastapi.testclient import TestClient
        import main
        c = TestClient(main.app)
        name = next(iter(m[aid]['files']))
        r = c.get(f'/api/house/twin/library/{aid}/{name}')
        check(r.status_code == 404, f'route answers 404 on a failed fetch: {r.status_code}')
        r = c.get('/api/house/twin/library/not-an-asset/x.jpg')
        check(r.status_code == 404, 'unknown asset 404')
        r = c.get(f'/api/house/twin/library/{aid}/..%2F..%2Fdb.json')
        check(r.status_code == 404, 'a file name not in the manifest is 404, never a path walk')
    finally:
        tl._urlopen = orig


def scenario_routes_serve_cached_files_and_the_kit():
    _clear_library()
    m = tl.manifest()
    aid = next(a for a, e in m.items() if e['kind'] == 'material')
    _, opener = _stub_fetch()
    orig = tl._urlopen
    tl._urlopen = opener
    try:
        from fastapi.testclient import TestClient
        import main
        c = TestClient(main.app)
        name = next(iter(m[aid]['files']))
        r = c.get(f'/api/house/twin/library/{aid}/{name}')
        check(r.status_code == 200 and r.content.startswith(b'BYTES:'), r.status_code)
        r = c.get('/api/house/twin/kit/modern_farmhouse')
        check(r.status_code == 200 and r.json()['id'] == 'modern_farmhouse', r.text[:200])
        check(c.get('/api/house/twin/kit/nope').status_code == 404, 'unknown kit 404')
    finally:
        tl._urlopen = orig
    from services import auth
    check(auth.resolve('GET', '/api/house/twin/library/{asset_id}/{name:path}') == auth.WALL_OR_SERVICE, 'library tier')
    check(auth.resolve('GET', '/api/house/twin/kit/{kit_id}') == auth.WALL_OR_SERVICE, 'kit tier')


def scenario_files_live_in_the_repo():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'twin_library', 'manifest.json'), encoding='utf-8') as f:
        check(json.load(f) == tl.manifest(), 'manifest() reads twin_library/manifest.json')
    with open(os.path.join(root, 'twin_kits', 'modern_farmhouse.json'), encoding='utf-8') as f:
        check(json.load(f) == tl.kit('modern_farmhouse'), 'kit() reads twin_kits/<id>.json')


if __name__ == '__main__':
    for fn in (scenario_manifest_is_licensed_and_complete,
               scenario_kit_references_resolve,
               scenario_unknown_kit_raises,
               scenario_ensure_downloads_once,
               scenario_missing_asset_falls_back,
               scenario_routes_serve_cached_files_and_the_kit,
               scenario_files_live_in_the_repo):
        fn()
        print('  ok ', fn.__name__)
