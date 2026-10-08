# Vector family map — design

**Status:** approved 2026-10-08 (MapLibre v6 revision); implementation plan next.
**Scope:** the family map only — everything drawn through `FamilyMap.create`
(`templates/components/family_map_core.html`): the /map page
(`components/family_map.html`), board map cards (`home.html`), and the House
bus map (`static/house_life.js`). The Mapbox GL maps on trip, trip kiosk and
drive setup, and the House neighbourhood (server-side Mapbox tiles into
three.js) are out of scope and must not change.

## Problem

Home Assistant 2026.10 moved its maps from raster PNG tiles to vector tiles:
MapLibre GL drawing the OpenStreetMap Foundation's Shortbread tiles, styled with
VersaTiles, falling back to raster on devices that cannot draw vectors. Its old
raster provider had started stamping "API key required" across every tile.

Chauffeur's family map is still the raster stack HA left: Leaflet 1.9.4 pulling
`tile.openstreetmap.org/{z}/{x}/{y}.png` straight from the browser. It works,
but:

- There is no real dark map. The wall board fakes one by inverting the tiles
  with a CSS filter (`home.html`, `.board-map .leaflet-tile-pane`), which reads
  muddy; the PWA map tab and the House bus map have no dark map at all.
- Raster tiles blur on high-density screens and between zoom levels.
- It no longer matches the stack HA itself runs, and the hosted HA cards
  Chauffeur borrows already draw HA's new vector map beside it.

## Goal

The family map is drawn as vectors from OSMF's Shortbread tiles, in a light
style or a designed dark style that follows the page's theme, on every device
that can draw it — and on every device that cannot, it is exactly today's
raster map.

Success:

- /map, every board map card and the House bus map draw a MapLibre vector map
  on a WebGL2-capable browser (the Pi 5 wall panel included).
- The map's style is light (`colorful`) when the page is light and dark
  (`eclipse`) when the page is dark, and changes live when the theme changes.
- A browser with no WebGL2, a failed MapLibre or style load, or a WebGL context
  lost and not restored, shows the Leaflet raster map instead — never a blank
  card.
- Markers, popups, zone-only chips, fit-to-everyone, ⌖ recenter, polling,
  `fallbackCenter`, and a board card's `interactive` setting (on and off)
  behave exactly as they do today.
- No Mapbox token, no Home Assistant and no add-on proxy is needed for the map.

## Decisions taken in conversation

- **Keep Leaflet; replace only the base layer.** The vector map is a Leaflet
  layer via `@maplibre/maplibre-gl-leaflet`, the same shape HA chose. Leaflet
  keeps owning markers, popups, bounds, interaction and the fallback. Rejected:
  a pure-MapLibre rewrite (two renderers to maintain, since raster fallback
  still needs Leaflet), and reusing the vendored Mapbox GL (needs a token; the
  family map must work without one).
- **Tiles come straight from OSMF.** No caching proxy in the add-on. The
  browser's own HTTP cache already honours the tiles' expiry headers, so a
  proxy would not make the wall load faster, and outage resilience is not a
  goal.
- **`interactive` is a per-card setting**, on or off for any board map card
  (`home.html` passes `interactive: !!tile.data.interactive` and rebuilds the
  instance when it flips). Both modes must keep working. The header comment in
  `family_map_core.html` that calls the board map "a map that is not a
  control" is stale and gets corrected.

## Design

### 1. Vendored assets

`tools/vendor_assets.py` gains, all pinned and committed under
`static/vendor/` like everything else:

- `maplibre-gl` **6.13.0** (latest at spec time): `maplibre-gl.mjs` (1.08 MB),
  `maplibre-gl-worker.mjs` (0.51 MB), `maplibre-gl.css`. v6 ships ESM only and
  requires WebGL2. HA pins 5.24.0 only because v6's worker URL broke its rspack
  bundle; Chauffeur does not bundle, so that reason does not apply, and the
  OpenStreetMap website itself already runs v6. The module finds its worker
  beside itself (`new URL(..., import.meta.url)`), so the two files must sit in
  the same directory.
- `@maplibre/maplibre-gl-leaflet` **0.1.4**, its **UMD** build
  (`leaflet-maplibre-gl.js`). Checked: the package's ESM build imports both
  `leaflet` and `maplibre-gl` by bare specifier, and Chauffeur's Leaflet is a
  global script, not a module, so the ESM build cannot be used without an
  import map. The UMD build reads `window.L` and `window.maplibregl`, so the
  page imports MapLibre's module, assigns it to `window.maplibregl`, then
  loads the plugin script. Its peer range covers MapLibre `^6.0.0`.
- From VersaTiles' published releases (`versatiles-style` **v6.3.1**,
  `versatiles-fonts` **v3.0.0**): the English-label variants of the
  `colorful` and `eclipse` styles (`styles/<name>/en.json`, which prefer
  `name_en` and fall back to `name`), the `base` sprite sheet they reference
  (`base.json`/`.png` and `@2x`), and glyph PBFs for the only two font stacks
  they reference, `noto_sans_regular` and `noto_sans_bold`.

Glyphs are trimmed to the ranges a US family's map needs: `0-255` through
`1024-1279` (Latin, Latin Extended, IPA, Greek, Cyrillic) plus `8192-8447`
(General Punctuation — the curly apostrophe in "O’Brien Rd"), about 600 KB per
font stack. Any other range is answered by a small route (section 2a) with a
valid **empty** glyph set, so a label in another script draws without those
characters instead of failing its tile; CJK ideographs are drawn from the
device's own fonts by MapLibre's default `localIdeographFontFamily`. Map
assets total about 1.6 MB of style files and 1.6 MB of library (HA ships
5.4 MB of style files untrimmed). The script prints the total, as it does
today.

`vendor_assets.py` gains a `map` argument that vendors only the map assets,
without the full wipe-and-refetch the bare command does, so adding the map
does not silently re-pull every font and script.

The vendored style JSON files are stored **unmodified**, so re-vendoring is a
straight replace. All rewriting happens at runtime (section 2).

Assets live under `static/vendor/maplibre/` (library) and
`static/vendor/map-style/` (styles, sprites, glyphs).

### 2. `FamilyMap` (the single change point)

`family_map_core.html` changes; its callers do not, beyond the theme CSS in
section 3.

- **Loading.** `ensureLeaflet()` stays and still always loads Leaflet. A new
  `ensureVector()` loads MapLibre with dynamic `import()` of the vendored
  `maplibre-gl.mjs` (`apiBase`-relative, memoised once per page like
  `ensureLeaflet`), assigns the module to `window.maplibregl`, loads the
  plugin's UMD script and MapLibre's stylesheet, and is only called when
  `canVector()` is true. MapLibre v6 resolves its worker from the module's own
  URL, so no `setWorkerUrl` call is needed and ingress paths just work.
- **`canVector()`** — a one-off probe, memoised per page:
  `document.createElement('canvas').getContext('webgl2')` is non-null (the
  probe context is released straight away). It runs only when a map is first
  built, never when the component is merely included.
- **`vector` option** (default `true`). The photographic House promises it
  never touches WebGL (`tests/test_house_exterior_live.py` asserts zero WebGL
  attempts after opening the bus map), so `house_life.js` passes
  `vector: false` when `document.body.dataset.houseRender === 'hybrid'`. The
  3D House's bus map, which already sits beside three.js, takes the vector
  map.
- **Base layer factory.** `ensure()` builds the base layer through one
  function: a vector layer when `canVector()` and `ensureVector()` succeeded,
  otherwise today's `L.tileLayer('https://tile.openstreetmap.org/...')`. The
  instance records which it got (`inst.base = 'vector' | 'raster'`) and the
  container carries `fm-vector` or `fm-raster` accordingly.
- **Style at runtime.** The vector layer fetches the vendored style JSON for
  the current theme, then rewrites it before handing it to MapLibre:
  - its vector source's `url` becomes
    `https://vector.openstreetmap.org/shortbread_v1/tilejson.json` (the tile
    URL is resolved from TileJSON, not hard-coded, per OSMF's policy);
  - `glyphs` and `sprite` become **absolute** URLs into
    `static/vendor/map-style/`, built from `location` plus `apiBase` so ingress
    (`/api/hassio_ingress/<token>/`) and the board's extra path segment both
    resolve. The rewritten style is memoised per theme per page.
  - MapLibre's own attribution control is off; Leaflet's control carries the
    OSM credit, so it is shown once, in the same place as today.
- **Interaction.** The vector layer is created with its own MapLibre
  interaction off; Leaflet drives pan/zoom and the plugin keeps the GL map in
  step. `interactive: false` therefore still yields a picture (Leaflet handlers
  off), and `interactive: true` a full map, with no new code path.
- **Lifecycle.** `destroy()` removes the vector layer with the map (freeing its
  WebGL context), so the board's rebuild-on-`interactive`-flip and
  rebuild-on-detached-container keep working and do not leak contexts.
- Markers (`iconFor`), popups (`popupFor`), chips, `refresh`, `recenter`,
  `startPolling`/`stopPolling` and `fallbackCenter` are unchanged.

### 2a. Serving the module and the glyphs

- **`.mjs` MIME type.** Browsers refuse to run a module served with a
  non-JavaScript MIME type, and Python's `mimetypes` table does not reliably
  know `.mjs` (it varies by platform and version). `main.py` registers
  `mimetypes.add_type('text/javascript', '.mjs')` before the `/static` mount.
- **Glyph route.** `GET /static/vendor/map-style/glyphs/{fontstack}/{range}.pbf`
  is registered before the `/static` mount (the same pattern as
  `/static/mdi/{fname}`): it serves the vendored PBF when it exists and
  otherwise a valid empty glyph set for that stack and range (a few bytes of
  protobuf), with a long `Cache-Control`. `fontstack` must be one of the
  vendored stacks and `range` must match `^\d+-\d+$`, or it answers 400. It is
  classified `ANYONE` in `services/auth.py` — font outlines, the same files any
  browser fetches before sign-in.

### 3. Theme

- **Resolver** `mapTheme()` returns `'light'` or `'dark'`:
  1. `html[data-panel-theme]` when present (wall/board pages): `light` → light,
     `dark` → dark, `auto` → `prefers-color-scheme`;
  2. else `html[data-theme]` (PWA, `app.html`): `light` / `dark`;
  3. else, on an HA-themed page (`html.ha-theme`), the luminance of the
     computed `--ha-bg`: light above 0.5, dark otherwise;
  4. else `html.dark` (every admin page carries it) → dark;
  5. else `prefers-color-scheme`.

  Consequence worth stating: /map is an admin page with `class="dark"`, so it
  becomes a dark map. The board CSS comment in `home.html` ("the /map page is
  allowed to be bright") justified a bright raster map there only because the
  inverted tiles were the alternative; with a designed dark style it follows the page like
  everything else.
- `light` → `colorful`, `dark` → `eclipse`.
- **Live switching.** One page-level `MutationObserver` on `<html>`'s
  `data-panel-theme` and `data-theme`, plus a `matchMedia` change listener,
  re-resolves the theme; each live vector instance whose theme changed calls
  `setStyle()` with the memoised rewritten style. Markers are Leaflet DOM and
  are unaffected.
- **The invert trick becomes raster-only.** `home.html`'s
  `.board-map .leaflet-tile-pane` filter rules are scoped to
  `.board-map.fm-raster` (or the equivalent container class), so a raster
  fallback on a dark panel still looks as it does today, and the vector canvas
  is never inverted.
- Attribution keeps today's look in both modes, including the shrunken `.fm-quiet`
  mark on small cards; in dark mode its chip background follows the theme
  rather than staying white.

### 4. Falling back to raster

An instance falls back to the raster base layer, once, and stays raster for its
lifetime (no flapping), when any of these happen:

- `canVector()` is false;
- `ensureVector()` rejects (script 404, blocked) or the style JSON fetch fails;
- MapLibre fires `webglcontextlost` and no `webglcontextrestored` follows within
  about 3 seconds — the context-exhaustion case HA hit with many maps on one
  dashboard, and relevant here because the House page runs three.js beside the
  bus map.

Fallback is per instance: one map dropping to raster does not affect the
others. The swap removes the vector layer, adds the raster layer, flips the
container class to `fm-raster`, and leaves markers and the view untouched. No
error is shown to the person; the map just keeps working.

### 5. OSMF usage policy

The OSMF vector tile usage policy is met as follows:

- **Attribution:** "© OpenStreetMap contributors", linked to the copyright
  page, always visible bottom-right (as today).
- **Identification:** tiles are fetched by the browser, which sends a real
  User-Agent and, by default (`strict-origin-when-cross-origin`), the page's
  origin as Referer — what the policy asks of web pages. The map sets no
  `referrerPolicy` override.
- **Caching:** no `no-cache`/`Pragma` headers are sent; the browser's HTTP
  cache honours each tile's expiry.
- **No bulk download:** tiles are only requested for what a map is showing.
  Nothing pre-fetches.
- **TileJSON, not a hard-coded tile URL** (section 2).

### 6. Out of scope

- Trip, trip kiosk and drive setup (Mapbox GL with `dark-v11`).
- The House neighbourhood (server-side Mapbox vector tiles into three.js).
- Any add-on tile proxy or cache.
- A setting to force the classic map. Fallback is automatic, as in HA; a manual
  switch is added only if the wall panel shows a real need.
- Swapping the trip pages from Mapbox GL to MapLibre (possible later; not
  needed now).

## Testing

Per the source-reading-tests rule, the critical path is exercised by tests that
run it in a browser, using the existing Playwright harness (`tests/live_app.py`),
with all `vector.openstreetmap.org` requests routed to a local fixture
(TileJSON plus one small `.mvt`), so tests never touch OSMF.

1. **Vector path (/map).** A MapLibre canvas is drawn inside the map container;
   the container has `fm-vector`; a member marker is visible and its popup opens
   on tap; the fixture TileJSON was requested (the rewrite took effect) and no
   request went to VersaTiles' tile host.
2. **Theme.** Flipping `data-theme` light → dark switches the loaded style to
   `eclipse` without rebuilding the Leaflet map or losing markers.
3. **Raster fallback.** With WebGL2 forced unavailable (stubbed
   `getContext('webgl2')`), the container has `fm-raster`, Leaflet raster tiles
   are requested, and markers still render.
4. **Context loss.** Firing a context loss with no restore drops the instance to
   raster after the grace period, and markers survive the swap.
5. **Board cards.** One board map card with `interactive` on (drag moves the
   view, popup opens) and one with it off (the card stays a door to /map); on a
   dark panel with raster forced, the invert filter applies, and on vector it
   does not.
6. **Pin test (source).** The style rewrite replaces the vector source URL and
   absolutises `glyphs` and `sprite`; the vendored style files remain unmodified.

Existing `tests/test_family_map.py` (the locations assembler) is unaffected and
keeps passing.

## Docs

`system_capabilities.md` gets an entry for the vector map: stack, theme
resolution, fallback triggers, and the OSMF policy points, in the same change
that ships it.
