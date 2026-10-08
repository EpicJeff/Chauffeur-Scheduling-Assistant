# Vector Family Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw the family map (/map, board map cards, the 3D House's bus map) as a MapLibre vector map on OSMF Shortbread tiles, light or dark to match the page, falling back to today's Leaflet raster map whenever vectors cannot be drawn.

**Architecture:** Leaflet stays the map. Only the base layer changes: `@maplibre/maplibre-gl-leaflet` puts a MapLibre GL canvas inside Leaflet's tile pane, so markers, popups, fit, recenter and `interactive` are untouched. Style, sprite and glyph files are vendored from VersaTiles and rewritten in the browser to point at OSMF's TileJSON and our own static path. A tiny server route answers glyph ranges we did not vendor with an empty glyph set.

**Tech Stack:** Leaflet 1.9.4 (already vendored), maplibre-gl 6.13.0 (ESM), @maplibre/maplibre-gl-leaflet 0.1.4 (UMD build), VersaTiles style v6.3.1 + fonts v3.0.0, FastAPI, Playwright (existing `tests/live_app.py`).

**Spec:** `docs/superpowers/specs/2026-10-08-vector-family-map-design.md` — read it before starting any task.

## Global Constraints

- All paths below are relative to `chauffeur/` unless they start with `docs/`. Run tests from `chauffeur/`.
- Run tests with `HA_BASE_URL` unset (`env -u HA_BASE_URL python tests/<file>.py` in bash). Five test files go red with it set.
- Per change: run the task's own test files plus `python tools/test.py --focus`. Do not run the full suite per commit; it runs once at the end (Task 5). Never pipe test output through `head`/`tail`.
- Every commit bumps the patch number of `version:` in `config.yaml` (currently `2.499.268`; each task takes the next number), uses the message form `type(scope): summary (vX.Y.Z)` with the Co-Authored-By trailer, and is pushed. No double quotes in commit messages if committing from PowerShell.
- Never round-trip source files through PowerShell `Get-Content`/`Set-Content`. Use the Edit/Write tools.
- Pinned versions, exactly: `maplibre-gl` **6.13.0**, `@maplibre/maplibre-gl-leaflet` **0.1.4**, VersaTiles style **v6.3.1**, VersaTiles fonts **v3.0.0**.
- Tile endpoint, exactly: `https://vector.openstreetmap.org/shortbread_v1/tilejson.json`. Raster fallback stays `https://tile.openstreetmap.org/{z}/{x}/{y}.png`.
- Styles: `light` → `colorful`, `dark` → `eclipse`. Font stacks: `noto_sans_regular`, `noto_sans_bold`. Glyph ranges: `0-255`, `256-511`, `512-767`, `768-1023`, `1024-1279`, `8192-8447`.
- Context-loss grace before falling back to raster: 3000 ms.
- No browser dialogs (`alert`/`confirm`/`prompt`). No add-on tile proxy or cache. Trip, trip kiosk, drive setup and the House neighbourhood are not touched.
- Every `FamilyMap` gets the vector map, both House experiences included (user's ruling: the photographic House may use WebGL features). The WebGL probe runs only when a map is first built, so a page that never opens a map makes zero WebGL attempts.

## Review Focus

The input classes the spec implies that are most likely to bite, each pinned by a test in the owning task:

1. **A map on a two-deep route or under ingress** (`/board/<slug>`, `/api/hassio_ingress/<token>/...`): glyph, sprite and module URLs must resolve against `apiBase`, not the site root. Pinned in Task 3 (`assetBase` scenario).
2. **Theme flipped twice quickly** (light→dark→light before the first style lands): the map must end on the last theme, not the one whose fetch finished last. Pinned in Task 3 (theme scenario).
3. **A map destroyed while it is still loading** (Alpine replaces the tile mid-load): no orphaned vector layer, no console error. Pinned in Task 3 (destroy-mid-load scenario).
4. **Two vector maps on one page** (a board with two map cards): the memoised loader is reused and both draw vectors. Pinned in Task 3 (second-instance scenario).
5. **A page that includes the map component but has not opened a map** (the photographic House before its bus map opens): zero WebGL attempts; opening the bus map adds exactly one, the memoised probe. Pinned in Task 4 (`tests/test_house_exterior_live.py`'s two counters).

---

## File Structure

- Modify `tools/vendor_assets.py` — adds the map section and a `map` argument. One responsibility: fetch pinned third-party files.
- Create `static/vendor/maplibre/` — `maplibre-gl.mjs`, `maplibre-gl-worker.mjs`, `maplibre-gl.css`, `leaflet-maplibre-gl.js` (committed output).
- Create `static/vendor/map-style/` — `colorful.json`, `eclipse.json`, `sprites/base{,@2x}.{json,png}`, `glyphs/<stack>/<range>.pbf` (committed output).
- Modify `main.py` — `.mjs` MIME registration and the glyph route, both just above `app.mount("/static", ...)`.
- Modify `services/auth.py` — one `RULES` row for the glyph route.
- Modify `templates/components/family_map_core.html` — loader, probe, style rewrite, theme resolver, base-layer factory, fallback. Callers keep the same `FamilyMap.create(el, opts)` API.
- Modify `templates/home.html` — scope the dark-invert filter to the raster fallback.
- Modify `tests/test_house_exterior_live.py` — its post-bus-map WebGL counter expects the map's one probe.
- Create `tests/test_map_vendor.py` — pins the vendored files.
- Create `tests/test_map_assets_routes.py` — pins MIME and the glyph route.
- Create `tests/test_family_map_live.py` — the real-browser scenarios.
- Modify `system_capabilities.md` — the shipped-behaviour entry.

---

### Task 1: Vendor the map assets

**Files:**
- Modify: `tools/vendor_assets.py`
- Create (by running the script): `static/vendor/maplibre/*`, `static/vendor/map-style/**`
- Test: `tests/test_map_vendor.py`

**Interfaces:**
- Produces: module constants `MAPLIBRE`, `MAPLIBRE_LEAFLET`, `VERSATILES_STYLE`, `VERSATILES_FONTS`, `MAP_STYLES`, `MAP_FONTSTACKS`, `MAP_GLYPH_RANGES`, `MAP_SPRITES` in `tools/vendor_assets.py` (Task 2 and the tests import `MAP_FONTSTACKS`); function `vendor_map()`.
- Produces on disk: `static/vendor/maplibre/maplibre-gl.mjs`, `maplibre-gl-worker.mjs`, `maplibre-gl.css`, `leaflet-maplibre-gl.js`; `static/vendor/map-style/colorful.json`, `eclipse.json`, `sprites/base.json`, `sprites/base.png`, `sprites/base@2x.json`, `sprites/base@2x.png`, `glyphs/{noto_sans_regular,noto_sans_bold}/{range}.pbf`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_map_vendor.py`:

```python
"""The vendored vector-map assets are what the family map expects.

The map is drawn from files committed under static/vendor/ (tools/vendor_assets.py
writes them). A re-vendor that renamed a file, dropped a glyph range or picked up
a style that references a font stack we did not ship would fail only in a
browser, on the wall, as a blank or label-less map. These pins catch it here.

Run from chauffeur/:  python tests/test_map_vendor.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import vendor_assets as va  # noqa: E402

VENDOR = os.path.join(HERE, 'static', 'vendor')
LIB = os.path.join(VENDOR, 'maplibre')
STYLE = os.path.join(VENDOR, 'map-style')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def read(path, mode='r'):
    with open(path, mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as f:
        return f.read()


def scenario_maplibre_is_the_pinned_v6_module_with_its_worker_beside_it():
    head = read(os.path.join(LIB, 'maplibre-gl.mjs'))[:400]
    check(f'v{va.MAPLIBRE}' in head, f'maplibre-gl.mjs is not v{va.MAPLIBRE}: {head[:200]!r}')
    # The module finds its worker beside itself via import.meta.url.
    check(os.path.getsize(os.path.join(LIB, 'maplibre-gl-worker.mjs')) > 100_000,
          'maplibre-gl-worker.mjs missing or truncated')
    check(os.path.getsize(os.path.join(LIB, 'maplibre-gl.css')) > 10_000, 'maplibre-gl.css missing')


def scenario_the_plugin_is_the_umd_build_reading_globals():
    src = read(os.path.join(LIB, 'leaflet-maplibre-gl.js'))
    check('global.maplibregl' in src and 'global.L' in src,
          'leaflet-maplibre-gl.js must be the UMD build that reads window.L and window.maplibregl')
    check('L.maplibreGL = maplibreGL' in src, 'the plugin must register L.maplibreGL')


def scenario_styles_are_stored_unmodified_and_reference_only_what_we_ship():
    shipped_sprites = {n.rsplit('.', 1)[0].replace('@2x', '') for n in va.MAP_SPRITES}
    for name in va.MAP_STYLES:
        style = json.loads(read(os.path.join(STYLE, f'{name}.json')))
        src = style['sources']['versatiles-shortbread']
        # Unmodified: the rewrite to OSMF happens in the browser, not here.
        check(src['type'] == 'vector' and src['tiles'][0].startswith('https://tiles.versatiles.org/'),
              f'{name}.json was modified on disk; the rewrite belongs in family_map_core.html')
        stacks = set()
        for layer in style['layers']:
            font = layer.get('layout', {}).get('text-font')
            if isinstance(font, list):
                stacks.add(','.join(font))
        check(stacks <= set(va.MAP_FONTSTACKS),
              f'{name}.json uses font stacks we do not ship: {stacks - set(va.MAP_FONTSTACKS)}')
        ids = {s['url'].rsplit('/', 1)[-1] for s in style['sprite']}
        check(ids <= shipped_sprites, f'{name}.json uses sprites we do not ship: {ids - shipped_sprites}')


def scenario_every_shipped_stack_has_every_range():
    for stack in va.MAP_FONTSTACKS:
        for rng in va.MAP_GLYPH_RANGES:
            path = os.path.join(STYLE, 'glyphs', stack, f'{rng}.pbf')
            check(os.path.isfile(path) and os.path.getsize(path) > 1000, f'missing glyphs {stack}/{rng}')
    for name in va.MAP_SPRITES:
        check(os.path.isfile(os.path.join(STYLE, 'sprites', name)), f'missing sprite {name}')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    for fn in SCENARIOS:
        fn()
        print(f'  ok  {fn.__name__}')
    print(f'\n{len(SCENARIOS)}/{len(SCENARIOS)} map vendor scenarios passed')
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `env -u HA_BASE_URL python tests/test_map_vendor.py`
Expected: FAIL with `AttributeError: module 'vendor_assets' has no attribute 'MAPLIBRE'`.

- [ ] **Step 3: Add the map section to `tools/vendor_assets.py`**

Add `import io` and `import tarfile` to the imports. Below `LEAFLET_IMAGES`, add:

```python
# The vector family map (spec: docs/superpowers/specs/2026-10-08-vector-family-map-design.md).
# MapLibre v6 ships ESM only; its worker sits BESIDE the module, which finds it
# through import.meta.url, so both land in the same directory. The Leaflet
# plugin is its UMD build on purpose: the ESM build imports `leaflet` and
# `maplibre-gl` by bare specifier, and our Leaflet is a global script.
MAPLIBRE = '6.13.0'
MAPLIBRE_LEAFLET = '0.1.4'
VERSATILES_STYLE = 'v6.3.1'
VERSATILES_FONTS = 'v3.0.0'
# English-label variants (`en.json`: name_en, falling back to name).
MAP_STYLES = ['colorful', 'eclipse']
# The only two stacks those styles reference, and the ranges a US family's
# map needs: Latin through Cyrillic, plus General Punctuation for the curly
# apostrophe. Anything else is answered empty by main.py's glyph route.
MAP_FONTSTACKS = ['noto_sans_regular', 'noto_sans_bold']
MAP_GLYPH_RANGES = ['0-255', '256-511', '512-767', '768-1023', '1024-1279', '8192-8447']
MAP_SPRITES = ['base.json', 'base.png', 'base@2x.json', 'base@2x.png']
```

Below `vendor_font`, add:

```python
def _tar_members(data):
    """A release tarball as {member name: bytes}, read in memory — nothing
    from the archive is ever written to disk under its own name."""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        for member in tar.getmembers():
            if member.isfile():
                name = member.name[2:] if member.name.startswith('./') else member.name
                out[name] = tar.extractfile(member).read()
    return out


def vendor_map():
    """MapLibre, its Leaflet bridge, and the VersaTiles style files."""
    for sub in ('maplibre', 'map-style'):
        shutil.rmtree(os.path.join(VENDOR, sub), ignore_errors=True)

    base = f'https://unpkg.com/maplibre-gl@{MAPLIBRE}/dist/'
    for name in ('maplibre-gl.mjs', 'maplibre-gl-worker.mjs', 'maplibre-gl.css'):
        write(f'maplibre/{name}', fetch(base + name))
    write('maplibre/leaflet-maplibre-gl.js',
          fetch(f'https://unpkg.com/@maplibre/maplibre-gl-leaflet@{MAPLIBRE_LEAFLET}'
                '/leaflet-maplibre-gl.js'))

    release = ('https://github.com/versatiles-org/versatiles-style/releases/download/'
               + VERSATILES_STYLE)
    styles = _tar_members(fetch(release + '/styles.tar.gz'))
    for name in MAP_STYLES:
        write(f'map-style/{name}.json', styles[f'{name}/en.json'])
    sprites = _tar_members(fetch(release + '/sprites.tar.gz'))
    for name in MAP_SPRITES:
        write(f'map-style/sprites/{name}', sprites[name])

    fonts = _tar_members(fetch(
        'https://github.com/versatiles-org/versatiles-fonts/releases/download/'
        f'{VERSATILES_FONTS}/noto_sans.tar.gz'))
    for stack in MAP_FONTSTACKS:
        for rng in MAP_GLYPH_RANGES:
            write(f'map-style/glyphs/{stack}/{rng}.pbf', fonts[f'{stack}/{rng}.pbf'])
```

In `main()`, after the leaflet images loop, add:

```python
    print('vector map')
    vendor_map()
```

and at the top of `main()`, before the `rmtree`, add:

```python
    # `python tools/vendor_assets.py map` refreshes only the map's files, so
    # bumping MapLibre does not silently re-pull every font and script.
    if sys.argv[1:] == ['map']:
        os.makedirs(VENDOR, exist_ok=True)
        vendor_map()
        return
```

Add one line to the module docstring after the usage line:

```
    python tools/vendor_assets.py map     # only the vector map's files
```

- [ ] **Step 4: Run the vendoring**

Run: `python tools/vendor_assets.py map`
Expected: lines for each file written, no traceback; `static/vendor/maplibre/` holds 4 files and `static/vendor/map-style/` holds 2 styles, 4 sprites and 12 glyph files.

- [ ] **Step 5: Run the test to verify it passes**

Run: `env -u HA_BASE_URL python tests/test_map_vendor.py`
Expected: `4/4 map vendor scenarios passed`.

- [ ] **Step 6: Commit**

Bump `config.yaml` version to the next patch number, then:

```bash
git add tools/vendor_assets.py static/vendor/maplibre static/vendor/map-style tests/test_map_vendor.py config.yaml
git commit -m "feat(map): vendor MapLibre 6.13 and the VersaTiles style files (vX.Y.Z)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push
```

---

### Task 2: Serve the module and the glyphs

**Files:**
- Modify: `main.py` (just above `app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")`, currently line 1288)
- Modify: `services/auth.py` (`RULES`, beside the `/static/translations/{path:path}` row)
- Test: `tests/test_map_assets_routes.py`; also run `tests/test_auth.py`

**Interfaces:**
- Consumes: `vendor_assets.MAP_FONTSTACKS` values (duplicated as a literal tuple in `main.py`, since `tools/` is not importable from the app).
- Produces: `main.map_glyphs(fontstack: str, glyph_range: str) -> Response`; `main._empty_glyphs(fontstack: str, glyph_range: str) -> bytes`; route `GET /static/vendor/map-style/glyphs/{fontstack}/{glyph_range}.pbf`.

FastAPI's `TestClient` is unusable here (no httpx), so the test calls the endpoint function directly, as `tests/test_packing_api.py` does.

- [ ] **Step 1: Write the failing test**

Create `tests/test_map_assets_routes.py`:

```python
"""The two server-side pieces the vector map needs.

1. `.mjs` must be served as JavaScript. Browsers refuse to run a module with
   any other MIME type, and Python's mimetypes table does not reliably know
   `.mjs` — so the map would be blank on exactly the platforms that lack it.
2. Glyph ranges we did not vendor are answered with a valid EMPTY glyph set,
   so a street name in another script draws without those characters instead
   of failing the whole tile it sits on.

TestClient needs httpx, which is not installed here, so the endpoint function
is called directly (the tests/test_packing_api.py pattern).

Run from chauffeur/:  python tests/test_map_assets_routes.py
"""
import mimetypes
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_map_assets_'))

import main  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from services import auth  # noqa: E402

GLYPHS = os.path.join(main.STATIC_DIR, 'vendor', 'map-style', 'glyphs')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_mjs_is_javascript():
    check(mimetypes.guess_type('maplibre-gl.mjs')[0] == 'text/javascript',
          f".mjs guessed as {mimetypes.guess_type('maplibre-gl.mjs')[0]!r}")


def scenario_a_vendored_range_is_served_as_is():
    r = main.map_glyphs('noto_sans_regular', '0-255')
    with open(os.path.join(GLYPHS, 'noto_sans_regular', '0-255.pbf'), 'rb') as f:
        check(r.body == f.read(), 'vendored range must be served byte for byte')
    check(r.media_type == 'application/x-protobuf', r.media_type)
    check('max-age' in r.headers.get('cache-control', ''), 'glyphs must be cacheable')


def scenario_a_missing_range_is_a_valid_empty_glyph_set():
    r = main.map_glyphs('noto_sans_bold', '1536-1791')
    expected = (b'\x0a\x1b'                       # glyphs.stacks, length 27
                b'\x0a\x0enoto_sans_bold'         # fontstack.name
                b'\x12\x091536-1791')             # fontstack.range
    check(r.body == expected, f'empty glyph set wrong: {r.body!r}')
    check(main._empty_glyphs('noto_sans_bold', '1536-1791') == expected, 'helper disagrees')


def scenario_unknown_stacks_and_bad_ranges_are_refused():
    for stack, rng in (('arial', '0-255'), ('noto_sans_regular', 'abc'),
                       ('../secrets', '0-255'), ('noto_sans_regular', '0-255/../x')):
        try:
            main.map_glyphs(stack, rng)
        except HTTPException as e:
            check(e.status_code == 400, f'{stack}/{rng}: {e.status_code}')
        else:
            raise AssertionError(f'{stack}/{rng} should be refused')


def scenario_the_route_is_public_and_registered_before_the_mount():
    template = '/static/vendor/map-style/glyphs/{fontstack}/{glyph_range}.pbf'
    check(auth.resolve('GET', template) == auth.ANYONE, 'glyph route must be ANYONE')
    paths = [getattr(r, 'path', None) for r in main.app.routes]
    check(template in paths, 'glyph route not registered')
    check(paths.index(template) < paths.index('/static'),
          'glyph route must be registered before the /static mount or the mount swallows it')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    for fn in SCENARIOS:
        fn()
        print(f'  ok  {fn.__name__}')
    print(f'\n{len(SCENARIOS)}/{len(SCENARIOS)} map asset route scenarios passed')
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `env -u HA_BASE_URL python tests/test_map_assets_routes.py`
Expected: FAIL at `scenario_a_missing_range...` or earlier with `AttributeError: module 'main' has no attribute 'map_glyphs'` (the `.mjs` scenario may pass or fail depending on the platform's table; sorted order runs `a_missing` first).

- [ ] **Step 3: Add the MIME registration and the route to `main.py`**

Immediately above `app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")`, add:

```python
# The vector family map's module is `.mjs`, and a browser refuses to run a
# module served as anything but JavaScript. Python's mimetypes table does not
# reliably know the extension (it depends on the platform's mime.types), so
# StaticFiles would guess text/plain on exactly the hosts that lack it.
import mimetypes as _mimetypes
_mimetypes.add_type('text/javascript', '.mjs')

_MAP_FONTSTACKS = ('noto_sans_regular', 'noto_sans_bold')  # tools/vendor_assets.py MAP_FONTSTACKS


def _empty_glyphs(fontstack: str, glyph_range: str) -> bytes:
    """A valid glyph PBF holding no glyphs: `glyphs { stacks { name, range } }`.
    Both strings are short (validated), so every length fits one varint byte."""
    name, rng = fontstack.encode(), glyph_range.encode()
    inner = b'\x0a' + bytes([len(name)]) + name + b'\x12' + bytes([len(rng)]) + rng
    return b'\x0a' + bytes([len(inner)]) + inner


@app.get("/static/vendor/map-style/glyphs/{fontstack}/{glyph_range}.pbf")
def map_glyphs(fontstack: str, glyph_range: str):
    """The vector map's font glyphs. We vendor only the ranges a US family's
    map needs (tools/vendor_assets.py); MapLibre treats a failed range as a
    failed TILE, so any other range gets a valid empty set and the label just
    draws without those characters."""
    if fontstack not in _MAP_FONTSTACKS or not re.match(r'^\d{1,5}-\d{1,5}$', glyph_range):
        raise HTTPException(status_code=400, detail="Path not allowed")
    path = os.path.join(STATIC_DIR, 'vendor', 'map-style', 'glyphs', fontstack, f'{glyph_range}.pbf')
    if os.path.isfile(path):
        with open(path, 'rb') as f:
            content = f.read()
    else:
        content = _empty_glyphs(fontstack, glyph_range)
    return Response(content=content, media_type='application/x-protobuf',
                    headers={'Cache-Control': 'max-age=604800'})
```

(`re`, `os`, `HTTPException`, `Response` and `STATIC_DIR` are already in scope in `main.py`; the `/static/mdi/{fname}` route directly above uses all of them.)

- [ ] **Step 4: Classify the route in `services/auth.py`**

Directly below the `('GET', '/static/translations/{path:path}', ANYONE, None),` row, add:

```python
    # The vector family map's font glyphs (main.map_glyphs): outlines of
    # Noto Sans, the same files any browser fetches before sign-in.
    ('GET', '/static/vendor/map-style/glyphs/{fontstack}/{glyph_range}.pbf', ANYONE, None),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u HA_BASE_URL python tests/test_map_assets_routes.py`
Expected: `5/5 map asset route scenarios passed`.

Run: `env -u HA_BASE_URL python tests/test_auth.py`
Expected: passes (it fails on any unclassified route, so it proves the new row is matched).

- [ ] **Step 6: Commit**

Bump the version, then:

```bash
git add main.py services/auth.py tests/test_map_assets_routes.py config.yaml
git commit -m "feat(map): serve .mjs as JavaScript and answer unvendored glyph ranges empty (vX.Y.Z)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push
```

---

### Task 3: The vector base layer in `FamilyMap`

**Files:**
- Modify: `templates/components/family_map_core.html`
- Test: `tests/test_family_map_live.py` (create); also run `tests/test_template_js.py`

**Interfaces:**
- Consumes: Task 1's files under `static/vendor/maplibre/` and `static/vendor/map-style/`; Task 2's glyph route.
- Produces (on `window.FamilyMap`): `create(el, opts)` (unchanged signature and options), `fetchLocations()`, `ensureLeaflet()`, plus `mapTheme() -> 'light'|'dark'`, `rewriteStyle(style, base) -> style`, `assetBase(prefix, href?) -> absolute URL string ending in 'static/vendor/map-style/'`, `canVector() -> boolean`. Instances gain `inst.base` (`'vector'|'raster'|null`), `inst.theme`, `inst.baseLayer`, `inst.toRaster()`. Container classes: `fm-vector` / `fm-raster`, plus `fm-dark` on a dark vector map.
- Constants inside the component: `OSMF_TILEJSON`, `OSM_TILES`, `OSM_ATTRIBUTION`, `STYLE_FOR = {light: 'colorful', dark: 'eclipse'}`, `CONTEXT_GRACE_MS = 3000`.

- [ ] **Step 1: Write the failing live test**

Create `tests/test_family_map_live.py`:

```python
"""The family map, drawn in a real browser: vector when it can be, raster when not.

All tile hosts are stubbed, so this never touches OpenStreetMap: OSMF's
TileJSON and an empty .mvt for the vector path, a 1x1 PNG for the raster
path, and VersaTiles' own tile host recorded and refused (the style rewrite
must have pointed MapLibre away from it).

Run from chauffeur/:  python tests/test_family_map_live.py
"""
import base64
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_family_map_live_'))

from live_app import live_app  # noqa: E402
from services import storage, ha_api  # noqa: E402

TILEJSON = {'tilejson': '3.0.0', 'minzoom': 0, 'maxzoom': 14,
            'tiles': ['https://vector.openstreetmap.org/shortbread_v1/{z}/{x}/{y}.mvt']}
PNG_1X1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
STATES = {
    'person.ana': {'entity_id': 'person.ana', 'state': 'not_home',
                   'last_updated': '2026-10-08T12:00:00+00:00',
                   'attributes': {'latitude': 35.80, 'longitude': -78.64}},
    'person.ben': {'entity_id': 'person.ben', 'state': 'school',
                   'last_updated': '2026-10-08T12:00:00+00:00',
                   'attributes': {'latitude': 35.83, 'longitude': -78.60}},
    'zone.home': {'entity_id': 'zone.home', 'state': '0',
                  'attributes': {'latitude': 35.81, 'longitude': -78.62}},
}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    for mid, name, ent in (('m1', 'Ana', 'person.ana'), ('m2', 'Ben', 'person.ben')):
        storage.add_member({'id': mid, 'name': name, 'color_code': '#3b82f6', 'avatar': None,
                            'bio': '', 'can_drive': False, 'is_child': False, 'driver_id': None,
                            'passenger_id': None, 'ha_person_entity': ent, 'notify_service': None,
                            'media_player_entity': None, 'pin': None, 'created_at': time.time()})
    ha_api.get_state = lambda e, *a, **kw: STATES.get(e)
    ha_api.get_states = lambda *a, **kw: list(STATES.values())


class Tiles:
    """Stubs every tile host on a page and records what was asked for."""
    def __init__(self, page):
        self.tilejson, self.mvt, self.raster, self.versatiles = [], [], [], []
        page.route('https://vector.openstreetmap.org/**', self._osmf)
        page.route('https://tile.openstreetmap.org/**', self._raster)
        page.route('https://tiles.versatiles.org/**', self._versatiles)

    def _osmf(self, route):
        url = route.request.url
        if url.endswith('tilejson.json'):
            self.tilejson.append(url)
            route.fulfill(status=200, content_type='application/json', body=json.dumps(TILEJSON),
                          headers={'Access-Control-Allow-Origin': '*'})
        else:
            self.mvt.append(url)
            route.fulfill(status=200, content_type='application/x-protobuf', body=b'',
                          headers={'Access-Control-Allow-Origin': '*'})

    def _raster(self, route):
        self.raster.append(route.request.url)
        route.fulfill(status=200, content_type='image/png', body=PNG_1X1)

    def _versatiles(self, route):
        self.versatiles.append(route.request.url)
        route.abort()


def has_webgl2(page):
    return page.evaluate("!!document.createElement('canvas').getContext('webgl2')")


def open_map(page, served):
    page.goto(served.url('map'))
    page.wait_for_function("typeof _fmInstance !== 'undefined' && _fmInstance && _fmInstance.base")
    page.wait_for_selector('#family-map .leaflet-marker-icon')


def scenario_vector_map_on_the_map_page(served):
    with served.browser() as page:
        tiles = Tiles(page)
        page.goto(served.url('map'))
        if not has_webgl2(page):
            print('  skip  this chromium has no WebGL2 — vector scenarios not run')
            return False
        open_map(page, served)
        page.wait_for_function("_fmInstance.base === 'vector'")
        check(page.locator('#family-map.fm-vector canvas.maplibregl-canvas').count() == 1,
              'one MapLibre canvas inside the map container')
        check(page.locator('#family-map .leaflet-marker-icon').count() == 2, 'both members pinned')
        page.locator('#family-map .leaflet-marker-icon').first.click()
        page.wait_for_selector('#family-map .leaflet-popup-content')
        page.wait_for_function("_fmInstance.baseLayer.getMaplibreMap().isStyleLoaded()")
        check(tiles.tilejson, 'MapLibre must resolve tiles from the OSMF TileJSON')
        check(not tiles.versatiles, f'the style rewrite missed: {tiles.versatiles[:2]}')
        check(not tiles.raster, 'no raster tiles when vector works')
        # /map is an admin page (html.dark), so it is a dark map.
        check(page.evaluate("_fmInstance.theme") == 'dark', 'admin page should resolve dark')
        check(page.evaluate("_fmInstance.baseLayer.getMaplibreMap().getStyle().name")
              == 'versatiles-colorful-dark', 'dark should load the eclipse style')
        check(page.locator('#family-map .leaflet-control-attribution').inner_text().find('OpenStreetMap') >= 0,
              'OSM credit visible')
        check(page.locator('#family-map .maplibregl-ctrl-attrib').count() == 0,
              "MapLibre's own attribution must be off (credit shown once)")
        check(not served.errors(), served.errors())
    return True


def scenario_theme_follows_the_page_and_the_last_flip_wins(served):
    with served.browser() as page:
        Tiles(page)
        open_map(page, served)
        page.wait_for_function("_fmInstance.base === 'vector'")
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        page.wait_for_function(
            "_fmInstance.baseLayer.getMaplibreMap().getStyle().name === 'versatiles-colorful'")
        check(page.locator('#family-map .leaflet-marker-icon').count() == 2, 'markers survive a restyle')
        # Rapid flips: dark, light, dark before any style lands -> ends dark.
        page.evaluate("""() => { const r = document.documentElement;
            r.setAttribute('data-theme', 'dark'); r.setAttribute('data-theme', 'light');
            r.setAttribute('data-theme', 'dark'); }""")
        page.wait_for_function("_fmInstance.theme === 'dark'")
        page.wait_for_timeout(800)
        check(page.evaluate("_fmInstance.baseLayer.getMaplibreMap().getStyle().name")
              == 'versatiles-colorful-dark', 'the last flip must win')
        check(page.evaluate("document.getElementById('family-map').classList.contains('fm-dark')"),
              'dark vector map carries fm-dark')
        check(not served.errors(), served.errors())


def scenario_resolver_and_asset_base(served):
    with served.browser() as page:
        Tiles(page)
        page.goto(served.url('map'))
        page.wait_for_function("window.FamilyMap && FamilyMap.mapTheme")
        got = page.evaluate("""() => { const r = document.documentElement, out = [];
            r.setAttribute('data-panel-theme', 'light'); out.push(FamilyMap.mapTheme());
            r.setAttribute('data-panel-theme', 'dark'); out.push(FamilyMap.mapTheme());
            r.removeAttribute('data-panel-theme');
            r.setAttribute('data-theme', 'light'); out.push(FamilyMap.mapTheme());
            r.removeAttribute('data-theme'); out.push(FamilyMap.mapTheme());
            return out; }""")
        check(got == ['light', 'dark', 'light', 'dark'], f'resolver order wrong: {got}')
        # Review Focus 1: a two-deep route climbs with apiBase, and ingress is
        # never climbed out of.
        got = page.evaluate("""() => [
            FamilyMap.assetBase('../', 'http://h/board/kitchen'),
            FamilyMap.assetBase('', 'http://h/api/hassio_ingress/tok/map'),
            FamilyMap.assetBase('../', 'http://h/api/hassio_ingress/tok/board/kitchen'),
            FamilyMap.assetBase('')]""")
        check(got[0] == 'http://h/static/vendor/map-style/', f'board route: {got[0]}')
        check(got[1] == 'http://h/api/hassio_ingress/tok/static/vendor/map-style/', f'ingress: {got[1]}')
        check(got[2] == 'http://h/api/hassio_ingress/tok/static/vendor/map-style/',
              f'board under ingress: {got[2]}')
        check(got[3] == served.url('static/vendor/map-style/'), f'this page: {got[3]}')
        style = page.evaluate("""() => FamilyMap.rewriteStyle({sources: {s: {type: 'vector',
                tiles: ['https://tiles.versatiles.org/tiles/osm/{z}/{x}/{y}']}},
                sprite: [{id: 'base', url: 'https://tiles.versatiles.org/assets/sprites/base'}],
                glyphs: 'https://tiles.versatiles.org/assets/glyphs/{fontstack}/{range}.pbf',
                layers: []}, 'http://h/x/static/vendor/map-style/')""")
        check(style['sources']['s'] == {'type': 'vector',
              'url': 'https://vector.openstreetmap.org/shortbread_v1/tilejson.json'}, style['sources'])
        check(style['glyphs'] == 'http://h/x/static/vendor/map-style/glyphs/{fontstack}/{range}.pbf',
              style['glyphs'])
        check(style['sprite'] == [{'id': 'base', 'url': 'http://h/x/static/vendor/map-style/sprites/base'}],
              style['sprite'])


def scenario_raster_when_there_is_no_webgl2(served):
    with served.browser() as page:
        tiles = Tiles(page)
        page.add_init_script("""const real = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function (kind, ...a) {
                if (/webgl/.test(kind)) return null; return real.call(this, kind, ...a); };""")
        open_map(page, served)
        check(page.evaluate("_fmInstance.base") == 'raster', 'no WebGL2 means raster')
        check(page.evaluate("typeof maplibregl") == 'undefined', 'MapLibre is never even loaded')
        check(page.locator('#family-map.fm-raster').count() == 1, 'container marked fm-raster')
        page.wait_for_function("document.querySelectorAll('#family-map .leaflet-tile-loaded').length > 0")
        check(tiles.raster and not tiles.tilejson, 'raster tiles only')
        check(page.locator('#family-map .leaflet-marker-icon').count() == 2, 'markers on raster')
        check(not served.errors(), served.errors())


def scenario_context_loss_drops_to_raster_and_keeps_the_pins(served):
    with served.browser() as page:
        tiles = Tiles(page)
        open_map(page, served)
        page.wait_for_function("_fmInstance.base === 'vector'")
        page.evaluate("""_fmInstance.baseLayer.getMaplibreMap().getCanvas()
            .getContext('webgl2').getExtension('WEBGL_lose_context').loseContext()""")
        page.wait_for_function("_fmInstance.base === 'raster'", timeout=10000)
        check(page.locator('#family-map.fm-raster').count() == 1, 'container flipped to fm-raster')
        check(page.locator('#family-map canvas.maplibregl-canvas').count() == 0, 'vector layer removed')
        check(page.locator('#family-map .leaflet-marker-icon').count() == 2, 'pins survive the swap')
        page.wait_for_function("document.querySelectorAll('#family-map .leaflet-tile-loaded').length > 0")
        check(tiles.raster, 'raster tiles requested after the swap')


def scenario_destroy_mid_load_and_a_second_map(served):
    with served.browser() as page:
        Tiles(page)
        open_map(page, served)
        page.wait_for_function("_fmInstance.base === 'vector'")
        # Review Focus 3 + 4: a map torn down while loading, and a second live
        # map sharing the memoised loader.
        page.evaluate("""async () => {
            for (const id of ['fm-a', 'fm-b']) {
                const d = document.createElement('div'); d.id = id;
                d.style.cssText = 'width:300px;height:200px'; document.body.appendChild(d); }
            window._fmA = FamilyMap.create(document.getElementById('fm-a'), {interactive: false});
            window._fmB = FamilyMap.create(document.getElementById('fm-b'), {interactive: true});
            _fmA.ensure(); _fmA.destroy();
            await _fmB.ensure();
            return true; }""")
        page.wait_for_function("window._fmB.base === 'vector'")
        page.wait_for_timeout(1500)
        check(page.locator('#fm-a canvas').count() == 0, 'destroyed map left a canvas behind')
        check(page.evaluate("window._fmA.base") is None, 'destroyed map must not come back')
        check(page.evaluate("_fmB.map.dragging.enabled()") is True, 'interactive map drags')
        check(page.evaluate("_fmInstance.base") == 'vector', 'the first map is still vector')
        check(not served.errors(), served.errors())


if __name__ == '__main__':
    served = live_app(seed)
    if served is None:
        sys.exit(0)
    try:
        if scenario_vector_map_on_the_map_page(served):
            print('  ok  scenario_vector_map_on_the_map_page')
            for fn in (scenario_theme_follows_the_page_and_the_last_flip_wins,
                       scenario_context_loss_drops_to_raster_and_keeps_the_pins,
                       scenario_destroy_mid_load_and_a_second_map):
                fn(served)
                print(f'  ok  {fn.__name__}')
        for fn in (scenario_resolver_and_asset_base, scenario_raster_when_there_is_no_webgl2):
            fn(served)
            print(f'  ok  {fn.__name__}')
    finally:
        served.stop()
    print('\nfamily map live scenarios passed')
```

Note on `assetBase(prefix, href)`: the optional second argument stands in for `location.href` so the test can ask what a `/board/<slug>` page (prefix `../`) and an ingress page (prefix `''` under `/api/hassio_ingress/<token>/`) would get, without serving either.

- [ ] **Step 2: Run it to make sure it fails**

Run: `env -u HA_BASE_URL python tests/test_family_map_live.py`
Expected: FAIL — `_fmInstance.base` is undefined, so the first `wait_for_function` times out (or `FamilyMap.mapTheme` is undefined in the resolver scenario).

- [ ] **Step 3: Correct the stale header comment**

In `templates/components/family_map_core.html`, replace item 2 of the header comment (the paragraph starting `2. **A map that is not a control.**`) with:

```
     2. **A map that may or may not be a control.** Every board map card has
        its own `interactive` setting. Off, the card is a door — the whole
        card is an <a> to /map, so `interactive: false` turns Leaflet's
        handlers off and the tile puts `pointer-events: none` over the top.
        On, it is a full map with popups. home.html rebuilds the instance
        when the setting flips, because Leaflet bakes its handlers in at
        construction.

     The base map is vector when the browser can draw it (MapLibre GL inside
     Leaflet via maplibre-gl-leaflet, OSMF Shortbread tiles, a light or dark
     VersaTiles style that follows the page) and today's raster OSM tiles
     when it cannot. Spec: docs/superpowers/specs/2026-10-08-vector-family-map-design.md.
```

- [ ] **Step 4: Add the dark attribution style**

In the component's `<style>` block, after the `.fm-quiet .leaflet-control-attribution` rule, add:

```css
    /* A dark vector map would otherwise carry Leaflet's white credit chip. */
    .fm-dark .leaflet-control-attribution {
        background: rgb(0 0 0 / 0.55);
        color: #d4d4d4;
    }
    .fm-dark .leaflet-control-attribution a { color: #93c5fd; }
```

- [ ] **Step 5: Add the loader, probe, theme and style helpers**

In the IIFE, directly after `function ensureLeaflet() { ... }`, add:

```js
        // ---- The vector base map ------------------------------------------
        const OSMF_TILEJSON = 'https://vector.openstreetmap.org/shortbread_v1/tilejson.json';
        const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
        const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
        const STYLE_FOR = { light: 'colorful', dark: 'eclipse' };
        // How long a lost WebGL context gets to come back before this map
        // gives up on vectors. Browsers cap live contexts per page and take
        // the oldest; HA saw those never return.
        const CONTEXT_GRACE_MS = 3000;

        // Absolute, because MapLibre resolves glyph and sprite URLs inside its
        // worker, where a relative path has no page to be relative to. Built
        // from the page's own location plus the climb (`apiBase`), so ingress
        // and the board's extra segment resolve the same way the scripts do.
        // `href` exists for the test; callers leave it out.
        function assetBase(prefix, href) {
            return new URL((prefix === undefined ? apiBase : prefix)
                           + 'static/vendor/map-style/', href || location.href).href;
        }

        let _canVector = null;
        // Asked only when a map is first built — never at include time, so a
        // page that never opens a map makes no WebGL attempt at all.
        function canVector() {
            if (_canVector !== null) return _canVector;
            try {
                const gl = document.createElement('canvas').getContext('webgl2');
                _canVector = !!gl;
                const lose = gl && gl.getExtension('WEBGL_lose_context');
                if (lose) lose.loseContext();   // the probe holds no context
            } catch (e) { _canVector = false; }
            return _canVector;
        }

        // MapLibre v6 is ESM only, the Leaflet bridge is its UMD build (its
        // ESM build imports `leaflet` by bare name, and our Leaflet is a
        // global script), so: import the module, publish it as the global
        // the bridge reads, then load the bridge. Once per page.
        function ensureVector() {
            if (window._fmVectorLoading) return window._fmVectorLoading;
            window._fmVectorLoading = (async () => {
                const css = document.createElement('link');
                css.rel = 'stylesheet';
                css.href = apiBase + 'static/vendor/maplibre/maplibre-gl.css';
                document.head.appendChild(css);
                const mod = await import(new URL(apiBase + 'static/vendor/maplibre/maplibre-gl.mjs',
                                                 location.href).href);
                window.maplibregl = mod;
                await new Promise((resolve, reject) => {
                    const js = document.createElement('script');
                    js.src = apiBase + 'static/vendor/maplibre/leaflet-maplibre-gl.js';
                    js.onload = resolve;
                    js.onerror = reject;
                    document.head.appendChild(js);
                });
                if (!L.maplibreGL) throw new Error('maplibre-gl-leaflet did not register');
            })();
            // A failed load stays failed for this page: every map goes raster.
            window._fmVectorLoading.catch(() => {});
            return window._fmVectorLoading;
        }

        function luminance(css) {
            const s = String(css || '').trim();
            let r, g, b, m;
            if ((m = s.match(/^#([0-9a-f]{3})$/i))) {
                [r, g, b] = m[1].split('').map(c => parseInt(c + c, 16));
            } else if ((m = s.match(/^#([0-9a-f]{6})$/i))) {
                [r, g, b] = [0, 2, 4].map(i => parseInt(m[1].substr(i, 2), 16));
            } else if ((m = s.match(/^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i))) {
                [r, g, b] = [m[1], m[2], m[3]].map(Number);
            } else {
                return null;
            }
            return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
        }

        function prefersLight() {
            try { return window.matchMedia('(prefers-color-scheme: light)').matches; }
            catch (e) { return false; }
        }

        // Which style the page wants. Order matters: the wall's own setting,
        // then the PWA's, then an HA theme's background, then the admin
        // pages' permanent `dark` class, then the device.
        function mapTheme() {
            const root = document.documentElement;
            const panel = root.getAttribute('data-panel-theme');
            if (panel === 'light' || panel === 'dark') return panel;
            if (panel === 'auto') return prefersLight() ? 'light' : 'dark';
            const pwa = root.getAttribute('data-theme');
            if (pwa === 'light' || pwa === 'dark') return pwa;
            if (root.classList.contains('ha-theme')) {
                const lum = luminance(getComputedStyle(root).getPropertyValue('--ha-bg'));
                if (lum !== null) return lum > 0.5 ? 'light' : 'dark';
            }
            if (root.classList.contains('dark')) return 'dark';
            return prefersLight() ? 'light' : 'dark';
        }

        // The vendored VersaTiles style is stored as published. Here it is
        // pointed at OSMF's tiles (through TileJSON, as OSMF asks, never a
        // hard-coded tile URL) and at our own copies of its fonts and icons.
        function rewriteStyle(style, base) {
            const s = JSON.parse(JSON.stringify(style));
            Object.keys(s.sources || {}).forEach(k => {
                if (s.sources[k].type === 'vector') {
                    s.sources[k] = { type: 'vector', url: OSMF_TILEJSON };
                }
            });
            s.glyphs = base + 'glyphs/{fontstack}/{range}.pbf';
            const sprites = Array.isArray(s.sprite) ? s.sprite
                : (s.sprite ? [{ id: 'default', url: s.sprite }] : []);
            s.sprite = sprites.map(sp => ({ id: sp.id, url: base + 'sprites/' + sp.url.split('/').pop() }));
            return s;
        }

        const _styles = {};
        function styleFor(theme) {
            const name = STYLE_FOR[theme];
            if (!_styles[name]) {
                _styles[name] = fetch(apiBase + `static/vendor/map-style/${name}.json`)
                    .then(r => { if (!r.ok) throw new Error(`style ${name}: ${r.status}`); return r.json(); })
                    .then(s => rewriteStyle(s, assetBase()));
                // A failed fetch is not remembered; the next map may retry.
                _styles[name].catch(() => { delete _styles[name]; });
            }
            return _styles[name];
        }

        // Every live vector map, so one observer can restyle them all.
        const _vectorMaps = new Set();
        let _watching = false;
        function watchTheme() {
            if (_watching) return;
            _watching = true;
            const onChange = () => _vectorMaps.forEach(i => i.applyTheme());
            new MutationObserver(onChange).observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-panel-theme', 'data-theme', 'class', 'style']
            });
            try {
                window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', onChange);
            } catch (e) { /* old browser: theme follows on the next map build */ }
        }
```

- [ ] **Step 6: Build the base layer through one factory**

Add `base: null, theme: null, baseLayer: null, lostTimer: null, gen: 0,` to the `inst` object literal (after `timer: null,`).

In `ensure()`, replace the opening `await ensureLeaflet();` with:

```js
                    // A destroy() that lands while Leaflet is still loading
                    // (Alpine replacing the tile) must not be undone by this
                    // call resuming and building a map anyway.
                    const gen = inst.gen;
                    await ensureLeaflet();
                    if (gen !== inst.gen) return null;
```

Replace the `L.tileLayer(...).addTo(inst.map);` statement inside `ensure()` with:

```js
                        await inst.addBase();
```

and add these methods to `inst` (after `ensure()`):

```js
                setBaseClass() {
                    el.classList.toggle('fm-vector', inst.base === 'vector');
                    el.classList.toggle('fm-raster', inst.base === 'raster');
                    el.classList.toggle('fm-dark', inst.base === 'vector' && inst.theme === 'dark');
                },

                async addBase() {
                    const map = inst.map;
                    if (canVector()) {
                        try {
                            await ensureVector();
                            const theme = mapTheme();
                            const style = await styleFor(theme);
                            // Torn down (or rebuilt) while we waited: draw nothing.
                            if (inst.map !== map) return;
                            inst.theme = theme;
                            inst.baseLayer = L.maplibreGL({
                                style: style,
                                attributionControl: false,   // Leaflet's control carries the credit
                                attribution: OSM_ATTRIBUTION
                            }).addTo(map);
                            inst.base = 'vector';
                            inst.watchContext();
                            _vectorMaps.add(inst);
                            watchTheme();
                            inst.setBaseClass();
                            return;
                        } catch (e) { /* fall through to the raster map */ }
                    }
                    if (inst.map === map) inst.toRaster();
                },

                // Once raster, raster for this instance's life: no flapping.
                toRaster() {
                    if (!inst.map || inst.base === 'raster') return;
                    clearTimeout(inst.lostTimer);
                    _vectorMaps.delete(inst);
                    if (inst.baseLayer) {
                        try { inst.map.removeLayer(inst.baseLayer); } catch (e) { }
                    }
                    inst.baseLayer = L.tileLayer(OSM_TILES, {
                        maxZoom: 19, attribution: OSM_ATTRIBUTION
                    }).addTo(inst.map);
                    inst.base = 'raster';
                    inst.setBaseClass();
                },

                watchContext() {
                    const gl = inst.baseLayer.getMaplibreMap();
                    gl.on('webglcontextlost', () => {
                        clearTimeout(inst.lostTimer);
                        inst.lostTimer = setTimeout(() => inst.toRaster(), CONTEXT_GRACE_MS);
                    });
                    gl.on('webglcontextrestored', () => clearTimeout(inst.lostTimer));
                },

                async applyTheme() {
                    if (inst.base !== 'vector') return;
                    const theme = mapTheme();
                    if (theme === inst.theme) return;
                    inst.theme = theme;
                    inst.setBaseClass();
                    try {
                        const style = await styleFor(theme);
                        // Only the LAST flip gets to draw: a slower earlier
                        // fetch landing second must not win.
                        if (inst.base === 'vector' && inst.theme === theme) {
                            inst.baseLayer.getMaplibreMap().setStyle(style);
                        }
                    } catch (e) { /* keep the style it has */ }
                },
```

In `destroy()`, before `if (inst.map) { inst.map.remove(); inst.map = null; }`, add:

```js
                    inst.gen++;
                    clearTimeout(inst.lostTimer);
                    _vectorMaps.delete(inst);
```

and after it, add:

```js
                    inst.base = null;
                    inst.baseLayer = null;
                    inst.theme = null;
                    el.classList.remove('fm-vector', 'fm-raster', 'fm-dark');
```

(`inst.map.remove()` removes the vector layer, whose `onRemove` calls MapLibre's own `remove()` and frees its WebGL context.)

Change the return statement to:

```js
        return { create: create, fetchLocations: fetchLocations, ensureLeaflet: ensureLeaflet,
                 mapTheme: mapTheme, rewriteStyle: rewriteStyle, assetBase: assetBase,
                 canVector: canVector };
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `env -u HA_BASE_URL python tests/test_family_map_live.py`
Expected: every scenario prints `ok` and the run ends `family map live scenarios passed`. If it prints `skip  this chromium has no WebGL2`, the vector scenarios did not run — report that rather than calling the task done.

Run: `env -u HA_BASE_URL python tests/test_template_js.py`
Expected: passes (the inline script, including the dynamic `import()`, parses).

Run: `env -u HA_BASE_URL python tests/test_family_map.py`
Expected: passes unchanged.

- [ ] **Step 8: Commit**

Bump the version, then:

```bash
git add templates/components/family_map_core.html tests/test_family_map_live.py config.yaml
git commit -m "feat(map): the family map draws vectors on OSMF tiles, raster when it cannot (vX.Y.Z)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push
```

---

### Task 4: The board's dark trick goes raster-only; the House test counts the map's probe

**Files:**
- Modify: `templates/home.html:645-662` (the `.board-map .leaflet-tile-pane` rules and their comment)
- Modify: `tests/test_house_exterior_live.py:291`
- Test: `tests/test_family_map_live.py` (add a board scenario); run `tests/test_house_exterior_live.py`

**Interfaces:**
- Consumes: Task 3's `fm-raster`/`fm-vector` container classes and the `vector` option.

- [ ] **Step 1: Write the failing board scenario**

Append to `tests/test_family_map_live.py`, before the `if __name__ == '__main__':` block:

```python
def _board_with_map(page, served, interactive):
    """/home?panel=true with the real board, its map card's `interactive` set."""
    def patch(route):
        resp = route.fetch()
        body = resp.json()
        tiles = [t for t in body.get('tiles', []) if t.get('type') == 'map']
        check(tiles and not tiles[0]['data'].get('empty'),
              'the default board must carry a non-empty map card for the seeded family')
        tiles[0]['data']['interactive'] = interactive
        route.fulfill(response=resp, json=body)
    page.route(re.compile(r'.*/api/home_board(\?.*)?$'), patch)
    page.goto(served.url('home?panel=true'))
    page.wait_for_selector('.board-map .leaflet-marker-icon')


def scenario_board_cards_interactive_on_and_off_and_the_invert_trick(served):
    with served.browser(has_touch=True) as page:
        Tiles(page)
        _board_with_map(page, served, interactive=True)
        page.wait_for_selector('.board-map.fm-vector canvas.maplibregl-canvas')
        check(page.evaluate("getComputedStyle(document.querySelector('.board-map .leaflet-tile-pane')).filter")
              == 'none', 'a vector board map must never be colour-inverted')
        check(page.locator('.board-map').first.evaluate("e => getComputedStyle(e).pointerEvents") != 'none',
              'interactive card takes pointer events')
        check(not served.errors(), served.errors())
    with served.browser(has_touch=True) as page:
        Tiles(page)
        _board_with_map(page, served, interactive=False)
        page.wait_for_selector('.board-map.fm-vector')
        check(page.locator('.board-map').first.evaluate("e => getComputedStyle(e).pointerEvents") == 'none',
              'non-interactive card stays a door')
    with served.browser(has_touch=True) as page:
        Tiles(page)
        page.add_init_script("""const real = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function (kind, ...a) {
                if (/webgl/.test(kind)) return null; return real.call(this, kind, ...a); };""")
        page.add_init_script("try { localStorage.setItem('chauffeurPanelTheme', 'dark'); } catch (e) {}")
        _board_with_map(page, served, interactive=True)
        page.wait_for_selector('.board-map.fm-raster')
        check('invert' in page.evaluate(
              "getComputedStyle(document.querySelector('.board-map .leaflet-tile-pane')).filter"),
              'a raster board map on a dark panel keeps the night inversion')
```

and add `scenario_board_cards_interactive_on_and_off_and_the_invert_trick` to the tuple of vector scenarios run inside `if scenario_vector_map_on_the_map_page(served):`.

- [ ] **Step 2: Run it to make sure it fails**

Run: `env -u HA_BASE_URL python tests/test_family_map_live.py`
Expected: FAIL at `a vector board map must never be colour-inverted` (the filter still applies to the tile pane, where the MapLibre canvas lives).

- [ ] **Step 3: Scope the filter to the raster fallback**

In `templates/home.html`, replace the three rules

```css
        .board-map .leaflet-tile-pane {
            filter: invert(1) hue-rotate(180deg) brightness(0.85) contrast(0.9) saturate(0.6);
        }
        html[data-panel-theme="light"] .board-map .leaflet-tile-pane { filter: none; }
        @media (prefers-color-scheme: light) {
            html[data-panel-theme="auto"] .board-map .leaflet-tile-pane { filter: none; }
        }
```

with

```css
        .board-map.fm-raster .leaflet-tile-pane {
            filter: invert(1) hue-rotate(180deg) brightness(0.85) contrast(0.9) saturate(0.6);
        }
        html[data-panel-theme="light"] .board-map.fm-raster .leaflet-tile-pane { filter: none; }
        @media (prefers-color-scheme: light) {
            html[data-panel-theme="auto"] .board-map.fm-raster .leaflet-tile-pane { filter: none; }
        }
```

and append to the comment above them (before its closing `*/`):

```
           Since the vector map (v2.499.x, family_map_core.html) this is the
           RASTER FALLBACK's night look only: a vector map draws a designed
           dark style, and its canvas sits in this same tile pane, so an
           unscoped filter would invert it too.
```

(Write the real version number in place of `v2.499.x` — the one this commit takes.)

- [ ] **Step 4: Let the House test count the map's probe**

`tests/test_house_exterior_live.py` stubs WebGL off and counts attempts. The
photographic House draws no 3D scene, but its bus map now probes once for
WebGL2 (memoised per page) and, finding none, draws raster. The user ruled
that the photographic House may use WebGL features, so the counter after the
bus map has opened expects that one probe. Leave the line-58 check (`== 0`,
before any map opens) untouched.

At line 291, change

```python
            assert page.evaluate('webglAttempts') == 0
```

to

```python
            # The bus map (opened above) probes once for WebGL2 and, finding
            # none under this stub, draws raster. Nothing else on the page
            # asks: the photographic House builds no 3D scene.
            assert page.evaluate('webglAttempts') == 1
```

Also change the matching value in the results file at line 316 from `'webglAttempts':0` to `'webglAttempts':1`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u HA_BASE_URL python tests/test_family_map_live.py`
Expected: all scenarios `ok`, including the board scenario.

Run: `env -u HA_BASE_URL python tests/test_house_exterior_live.py --out <scratch dir>`
Expected: passes — zero attempts before the bus map opens, exactly one after, and the existing bus-map marker assertions (`.leaflet-marker-icon` count 2, `.leaflet-pane` count 0 after close) hold on the raster map.

Run: `env -u HA_BASE_URL python tools/test.py --focus`
Expected: green.

- [ ] **Step 6: Commit**

Bump the version, then:

```bash
git add templates/home.html tests/test_house_exterior_live.py tests/test_family_map_live.py config.yaml
git commit -m "fix(board): night inversion only for the raster map (vX.Y.Z)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push
```

---

### Task 5: Capability entry and the full sweep

**Files:**
- Modify: `system_capabilities.md` (top of the shipped list, and the "Current through" line)

- [ ] **Step 1: Write the capability entry**

At the top of the entries in `system_capabilities.md` (above the v2.499.263 entry), add, with the real version numbers from Tasks 1–4:

```markdown
**The family map draws vectors (v2.499.A–.D; `templates/components/family_map_core.html`, `tools/vendor_assets.py` `vendor_map`, `main.py` `map_glyphs`, `services/auth.py`, `templates/home.html`, `tests/test_map_vendor.py`, `tests/test_map_assets_routes.py`, `tests/test_family_map_live.py`; spec `docs/superpowers/specs/2026-10-08-vector-family-map-design.md`).** Everything drawn through `FamilyMap.create` (/map, board map cards, the 3D House's bus map) keeps Leaflet for markers, popups, fit, ⌖ and `interactive`, and swaps only the base layer: MapLibre GL 6.13.0 inside Leaflet via maplibre-gl-leaflet 0.1.4 (UMD build; the page imports MapLibre's ESM module and publishes it as `window.maplibregl`), drawing OSMF's Shortbread vector tiles (resolved from `vector.openstreetmap.org/shortbread_v1/tilejson.json`, fetched by the browser directly — no add-on proxy, by the user's decision). Styles are VersaTiles v6.3.1 `colorful` (light) and `eclipse` (dark), English labels, vendored unmodified and rewritten in the browser (tiles to OSMF, glyphs and sprites to absolute `static/vendor/map-style/` URLs from `apiBase`). Theme follows the page: `data-panel-theme`, then `data-theme`, then an HA theme's `--ha-bg` luminance, then the admin pages' `html.dark`, then the device; live restyle on change, last flip wins. Glyphs vendored only for Latin–Cyrillic + General Punctuation in `noto_sans_regular`/`noto_sans_bold`; any other range is answered by `GET /static/vendor/map-style/glyphs/{fontstack}/{glyph_range}.pbf` with a valid empty glyph set (ANYONE), because MapLibre fails a whole tile on a failed range. `.mjs` is registered as `text/javascript`. Falls back to the old raster OSM map, once and for good per instance, on no WebGL2, a failed module/style load, or a WebGL context lost for 3 s; markers survive the swap. The board's night inversion now applies to the raster fallback only (`.board-map.fm-raster`). Both House experiences take the vector bus map; the WebGL probe runs only when a map is first built (memoised per page), so a page that never opens a map makes no WebGL attempt. /map, an admin page, is now a dark map. Trip, trip kiosk, drive setup and the House neighbourhood are unchanged (Mapbox). NOT device-verified.
```

Update the "Current through" line to the final version and today's date.

- [ ] **Step 2: Run the full sweep**

Run: `env -u HA_BASE_URL python tools/test.py`
Expected: all green. If anything fails, report the failing file and its decisive line before changing anything.

- [ ] **Step 3: Commit**

Bump the version, then:

```bash
git add system_capabilities.md config.yaml
git commit -m "docs(capabilities): the vector family map (vX.Y.Z)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push
```
