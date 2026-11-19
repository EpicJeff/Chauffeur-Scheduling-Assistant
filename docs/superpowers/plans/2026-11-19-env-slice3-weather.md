# Environment slice 3: weather — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The twin shows the weather as it is: rain falling and splashing, wet and puddled surfaces, falling snow and snow cover, fog drawing the haze in, and one wind moving grass, trees, precipitation and clouds; snow and wetness linger plausibly after the weather passes.

**Architecture:** The add-on keeps a small running ground-state model (snow depth, wetness) from the weather entity it already watches, stored outside the `house_twin` settings row and read by the twin from one small endpoint it polls (no new stream). In the browser, one `sky/weather.js` turns the weather entity plus that ground state into a weather state (precipitation kind and rate, fog, wind, wetness, snow cover) with previews. Surfaces get one weather layer installed once at mount as a shader-chunk patch (procedural, no texture, one packed `vec4` of uniforms), like slice 2's cloud shadows; precipitation is its own drawn objects with their own materials.

**Tech Stack:** FastAPI services under `chauffeur/services/`, plain ES modules under `chauffeur/static/twin/`, three r187, node-driven tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-18-twin-environment-design.md`, "Slice 3: weather", "Weather data contract", "Where the live state applies", "Settings", "Testing". Slices 1 (sky, v2.499.937) and 2 (clouds, v2.499.941) are shipped: read their entries at the top of `chauffeur/system_capabilities.md`, `static/twin/sky/clouds.js` (weather mapping, wind), `sky/cloud_shadow.js` (the one-patch-for-every-lit-material pattern and its census), `sky/stage_haze.js`, `sky/look.js`, `twin_view.js` `applyTimeLook`.

## Global Constraints

- Work in `E:\repositories\Chauffeur-env-weather` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser. Claude runs the browser checks.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run the named tests and neighbours, and **every test file that mounts the twin view** (grep `tests/test_*_js.py` for `twin_view.js`, `from test_twin_drag_js`, `twin_editor_dom`); compare failures with main in a detached baseline outside the repo folder (never edit it). Node tests must also run over the real household fixture, not only hand-written plans.
- **Texture units:** the owner's GPU allows 16 per shader; heavy materials are at or near it. **No new sampler in any lit material.** Precipitation objects may use their own textures (their own programs).
- **Uniform budget:** the heaviest stress program (pool water with probes, mirror and full ripples) is at 223 of WebGL 2's guaranteed 224 fragment vectors (slice 2 report). The weather layer adds **at most one `vec4`** to lit materials (pack wetness, snow cover, puddle amount and rain rate into it; time comes from an existing uniform or the vec4's own channel budget). Report the heaviest program's total; if it would pass 224, pack further rather than exceed it.
- **Program keys never change with weather, wind, time, preview or ground state.** Everything installed once at mount; the rest is uniforms and object visibility of the precipitation objects only.
- Every shader: floor every `pow` base, no unguarded division, no NaN reaching bloom (`sky/atmosphere.js`, `post.js` `guardSample`).
- **Degrade:** no weather entity means clear, dry, calm (a gentle default breeze for the grass); missing quantities fall back per the data contract; nothing is required beyond a weather entity.
- **The environment never shows anything that could read as a device's state** (owner): no steam over the pool, no chimney smoke, no window glow from weather; a sprinkler or other effect fixture never runs because of weather.
- **Editor:** neutral by default (dry, no precipitation, calm; slice 1's rule); the editor's existing lighting control gains a choice to show the live state.
- New settings go in `services/settings_registry.py` and the viewer's settings drawer (spec "Settings"); never `config.html`. No new long-lived stream (each house tab holds two; the browser allows six per host). Per-weather data never grows the `house_twin` settings row. No new packages. No `transmission`. New modules appear in the generated import maps. No browser dialogs. Every new route gets an auth rule in `services/auth.py`.

## Rulings (Claude's calls within the spec)

1. **Weather state** (`sky/weather.js`, `weatherState(entity, ground, sensors, now)`): `precip` = `none|rain|snow|mix|hail` from the condition (`rainy`, `pouring`, `lightning-rainy` rain; `snowy` snow; `snowy-rainy` mix; `hail` hail); `rate` 0..1 = `rainy` .45, `pouring` 1, `lightning-rainy` .8, `snowy` .5, `snowy-rainy` .5, `hail` .7, refined by the current hour's forecast `precipitation` (mm/h: rate = clamp(mm/h / 8, .1, 1)) when the entity offers it; a local rain sensor overrides (on/off = .5/0, or a rate in mm/h). Fog = `fog` condition, or `visibility` (km) below 5: fog density from visibility (1 km heavy, 5 km none). Wind = the slice 2 wind (speed, bearing, units) with local wind sensors overriding; none means calm with the default grass breeze. Stale weather (older than slice 1's stale rule) means clear and calm.
2. **Ground state model** (`services/twin_weather_state.py`): updated whenever the weather entity changes and at least every 10 minutes, from temperature, condition, rate, cloud coverage and sun altitude. Snow depth (cm) grows at rate x 2.5 cm/h while snowing at or below 1 C (mix: x 1, wet); melts at max(0, T) x .4 cm/h plus .8 cm/h in sun above 0 C (scaled by 1 - cloud cover); cleared to 0 below .2 cm. Wetness 0..1 goes to 1 while raining (mix and melting snow count), dries with a time constant of 60 min at 20 C, 180 min at 0 C (linear between, clamped), halved in sun, doubled at humidity over 90%. Puddles = wetness above .6 and rain in the last 3 hours. Stored in its own small row or file under the data directory (never `house_twin`), tolerant of restarts (a missing or old record starts dry and bare). "Plausible, not exact."
3. **Delivery:** `GET /api/house/twin/weather-state` returns `{snow_cm, wetness, puddles, updated, source:{entity, missing:[...], sensors:{...}}}`; the twin polls it every 5 minutes and on weather changes it already sees through the existing stream. Auth: the same tier as the twin's other read routes.
4. **Weather layer** (`sky/weather_surface.js`, installed once like `cloud_shadow.js`): one chunk patch for standard and physical materials, the lightmap-patched and viewing-clone materials, the grass and the custom water and effect shaders. Wet: albedo darkened up to 35% (less on already-dark and metal), roughness pulled toward .15 by wetness, on every surface; rain on upward-facing surfaces adds procedural ripple rings (world-space hashed cells, no texture). Puddles: on upward faces (normal.y > .9) only, a world-space low-frequency procedural mask (two octaves of value noise) thresholded by the puddle amount, mirror-smooth inside (roughness .03), never on roofs (pitched faces fail the normal test) or water. Snow: on upward faces, coverage = smoothstep over normal.y (.55 to .85) and the snow depth, broken by a world-space noise edge; white-blue albedo .85, roughness .7, never on water (the pool and spa stay open); roof snow follows the same rule (pitched roofs hold snow up to the normal threshold). Trees and shrubs: snow on the upper faces of leaves through the same rule. The editor's neutral look sets all to zero.
5. **Precipitation objects** (`sky/precipitation.js`): rain as camera-following instanced streaks in a box around the view (counts per tier: low 1500, medium 4000, high 8000, max 12000 at rate 1, scaled by rate), angled by wind, fading with distance and haze; snow as camera-following instanced flakes (half the rain counts, slow fall .9 m/s with wind drift and a small flutter); hail as fast small pellets (rain counts x .3). Splashes: short-lived ring sprites on hard upward surfaces near the camera (pads, paths, decks, roofs; a cheap ray to the ground by sampling the existing ground height function, not a GPU ray-cast), and ripple rings on the pool and puddles come from the weather layer (ruling 4), not particles. All precipitation materials are unlit or lit by the sky light only, take no shadows and add nothing to lit materials. Low tier keeps precipitation (the panel must show rain) at its count.
6. **Wind:** one global wind from ruling 1 drives the grass (replacing the hard-coded gust: direction from the bearing, strength from speed, default breeze when none), tree and shrub sway (a vertex sway on tree and shrub materials only: trunk none, branches small, leaves more, by height above the root and wind strength; low tier stays still per the spec), precipitation angle and drift, and the cloud drift (already slice 2). Wind uniforms live only in grass, tree and precipitation programs.
7. **Fog:** slice 1's stage haze pulls in toward the house by fog density (haze start and end scale down to 15% of their clear values at heavy fog), and the sky cube and clouds dim toward the fog colour; no new pass.
8. **Previews:** viewer controls beside Day and Night: Clear, Rain, Pouring, Snow, Fog, Thunderstorm. A preview overrides the weather state (and sets a plausible ground state: rain previews wet with puddles, snow previews 8 cm) and returns to live after 120 s or on Now. Not settings.
9. **Settings and source report:** optional local sensors (`weather_rain_sensor`, `weather_wind_speed_sensor`, `weather_wind_direction_sensor`, `weather_temperature_sensor`) in `settings_registry.py` beside `weather_entity`, shown in the house viewer's settings drawer with the source report: which entity drives the weather, which quantities are missing and what stands in for them (spec: "no silent guessing").

## Review Focus

1. No new programs across clear, rain, pouring, snow, mix, hail, fog and thunderstorm, day and night, previews and returning to live (the slice 1/2 live check).
2. The heaviest lit program gains no texture unit and stays within 224 fragment vectors; a material census proves every lit material kind gets the weather layer.
3. The pool and spa never show snow, and water never shows puddles; nothing reads as a device's state.
4. No weather entity, a stale entity, or an entity missing every optional attribute gives a defined look (clear and dry, or the condition alone) and the source report says what is missing.
5. The ground state survives an add-on restart and starts dry and bare when its record is missing or corrupt; a snow day followed by sun melts within plausible hours.

---

### Task 1: Ground state, delivery, settings and the source report

**Files:**
- Create: `chauffeur/services/twin_weather_state.py`
- Modify: `chauffeur/main.py` (the route and the update hook where the weather entity changes are already seen), `chauffeur/services/auth.py` (route rule), `chauffeur/services/settings_registry.py` (four optional sensors), the house viewer's settings drawer template and JS (sensor pickers, source report)
- Test: `chauffeur/tests/test_twin_weather_state.py` (new: model rates of ruling 2 over simulated hours, restart and corrupt-record recovery, no `house_twin` growth, the route through a TestClient with auth, sensor overrides, the source report's missing list); `tests/test_auth_route_rules.py` or the file that flags unclassified routes; the drawer's existing tests

- [ ] Failing tests, run, implement, pass.

### Task 2: The weather state, wind and fog in the browser

**Files:**
- Create: `chauffeur/static/twin/sky/weather.js`
- Modify: `chauffeur/static/twin/twin_view.js` (poll ruling 3, previews, editor neutral, pass the state to clouds, haze and the later layers), `sky/stage_haze.js` (fog, ruling 7), `yard_grass.js` (wind, ruling 6), the tree and shrub materials (sway, ruling 6), the viewer's Day/Night controls (previews, ruling 8)
- Test: `chauffeur/tests/test_twin_weather_js.py` (new: every condition and missing attribute maps to a defined state; precipitation rate refinement; sensor overrides; stale; previews return after 120 s; editor neutral; program keys unchanged across states); neighbours: grass, stage haze, sky, clouds, every twin-view test

- [ ] Failing tests, run, implement, pass.

### Task 3: The weather layer on every surface

**Files:**
- Create: `chauffeur/static/twin/sky/weather_surface.js`
- Modify: `twin_view.js` (install once), the custom shaders that bypass the chunk (water, grass, effects), `bake/lightmap_material.js` and `viewing.js` only if their patches bypass it
- Test: `chauffeur/tests/test_twin_weather_surface_js.py` (new: census over a built house and the real household fixture: every lit material kind compiles with the patch and no sampler is added (expanded source); fragment-vector totals for the heavy stress programs; wet darkening and roughness values; puddles only on upward non-water faces; snow never on water; program keys unchanged)

- [ ] Failing tests, run, implement, pass.

### Task 4: Precipitation

**Files:**
- Create: `chauffeur/static/twin/sky/precipitation.js`
- Modify: `twin_view.js`
- Test: `chauffeur/tests/test_twin_precipitation_js.py` (new: counts per tier and rate, wind angle, camera following, hidden at rate 0 and in the editor's neutral look, no program change across rain/snow/hail, splash placement on hard upward surfaces only, reduced motion keeps precipitation but slows nothing it should not)

- [ ] Failing tests, run, implement, pass.

### Task 5: Browser checks (Claude)

- [ ] New `tests/test_twin_weather_live.py`: screenshots for rain, pouring, snow with 8 cm cover, fog and thunderstorm at noon, golden hour and night on high and low; no new programs across them; the active-sampler and uniform census in Chromium; previews return to live; frame cost of precipitation at 1080p high, frame cap off.
