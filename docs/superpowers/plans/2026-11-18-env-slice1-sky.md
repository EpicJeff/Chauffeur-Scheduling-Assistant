# Environment slice 1: sky, sun, moon, stars, north and the stage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A physically based sky drawn behind the house and used for its light and reflections, sun and moon discs drawn the way the eye sees them, real stars, north taken from the map, a circular stage that fades into haze at a radius setting, an interim overcast look from the real weather, and a time-of-day scrub.

**Architecture:** One sky module renders the current sky (atmosphere, sun and moon discs, stars) into a fixed-size cube render target. That cube is `scene.background`, the source of a fixed-size PMREM that is `scene.environment`, and the background the reflection probes capture, so everything shows one sky. A global fog chunk override fades every lit surface toward the sky's horizon colour by world-space distance from the stage centre. North comes from a map bearing computed once on the server.

**Tech Stack:** three r187 (vendored), plain ES modules, FastAPI services in Python, node-driven tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-18-twin-environment-design.md`, "Slice 1", "Weather data contract", "Where the live state applies". Recon of the current code with file:line for every hook below: `.superpowers/sdd/2026-11-18-env-slice1-sky/recon.md` (read it).

## Global Constraints

- Work in `E:\repositories\Chauffeur-env-design` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run only the named tests and neighbours; never the whole suite.
- No new packages. No `transmission`. No browser dialogs. No new long-lived stream per tab. Nothing new in the `house_twin` settings row except the map bearing fields named below.
- **Program keys never change with time or weather.** Sky, stars, discs, haze and the environment change only through uniforms and texture contents; the PMREM keeps one size and one render target; nothing toggles visibility or defines by time. The live test "clock changes compile no programs" must stay green.
- Every new shader: floor every `pow` base, no division without a floor, and no NaN reaching the bloom chain. Pin to vendored r187 define names.
- Every new module is added to the generated import maps (`tests/test_twin_import_maps.py`).
- Every Home Assistant touchpoint degrades: no weather entity means a clear sky; no map means the dial value.
- Assets already in place (public domain): `chauffeur/static/twin/sky/assets/moon_lroc_1k.jpg` (NASA SVS CGI Moon Kit, LROC colour, 1024x512 equirect) and `chauffeur/static/twin/sky/assets/stars.json` (Yale Bright Star Catalogue V <= 6.0, 5080 stars, `[ra_rad, dec_rad, vmag, kelvin]`).

## Rulings (Claude's calls within the spec)

1. **Sky model.** Single-scattering atmosphere (Rayleigh + Mie, ozone absorption) ray-marched per cube texel, in the family of Hillaire's sky-view approach but evaluated directly into the cube (16 view steps, 8 light steps are enough at cube resolution). Output is linear HDR radiance in the same units the lights use, scaled so noon sky luminance matches today's day look within reason. Night sky adds a faint airglow floor so it is never pure black.
2. **Sky cube.** 256 px per face on low and medium, 512 on high and max, HalfFloat. Re-rendered when the sun or moon moves more than 0.25 degrees, when the weather overcast factor changes by more than 0.05, on the minute tick, and on a scrub step. Rendering the cube is cheap (one fullscreen pass per face); it never calls `updateTime`.
3. **Discs** (the eye's size, owner): drawn into the main view as a camera-centred `Mesh` (not Points, not Sprites, depthTest on, depthWrite off, renderOrder low, far inside the cube cameras' far plane), so the planar mirror and the main view both see them. Angular diameter = `base * (1 + 0.6 * (1 - smoothstep(0, 30, altitudeDeg)))`, with `base` 2.2 degrees for the moon and 2.0 for the sun. The moon's base scales with its real distance (perigee-apogee, about +-7%). Near the horizon both redden and dim by the sky model's transmittance and flatten vertically by refraction (up to 15% at the horizon). The sun disc has limb darkening and is bright enough to bloom (within `guardSample` caps). The moon uses `moon_lroc_1k.jpg`, lit by the true sun direction (phase and terminator correct), with faint earthshine on the dark side. The discs are also drawn into the sky cube at their (small) cube resolution so reflections carry them.
4. **Stars.** A camera-centred mesh of small quads (one per star; not Points, so probes and the mirror can include them where wanted), positioned from RA/Dec by local sidereal time and latitude, size and brightness from magnitude, colour from temperature. Fade in from sun altitude -4 down to -12 degrees, dimmed by moon brightness and by the overcast factor; slight twinkle below 20 degrees altitude. Export `localSiderealTime(date, lon)` from `ephemeris.js`.
5. **Light balance.** `lookAt` keeps its signature and fields for its consumers, but `background` is no longer used for `scene.background`; ambient/hemisphere colours come from the sky's zenith and ground-bounce estimate; `environment` intensity is applied to the sky PMREM. Day/Night/Now and the editor's Unlit keep working; Unlit keeps `scene.environment === null` and draws its flat background as today.
6. **Editor look (spec):** the editor never reads weather (it has no live layer); its Day / Night / Now use the sky with no overcast. The editor's dark work surface (`#171e27`) stays only for Unlit.
7. **Interim overcast (spec):** factor `c` = `cloud_coverage / 100` when present, else from condition: `sunny` / `clear-night` 0, `partlycloudy` .4, `cloudy` .85, `fog` .9, every rain / snow / storm / `hail` / `exceptional` 1, `windy` / `windy-variant` .3, unknown 0. The sky desaturates toward a grey overcast (horizon-weighted), sun disc intensity and sun light scale by `1 - .75 c`, hemisphere and environment lift by `+ .35 c`, stars and moon disc fade by `1 - c`. Weather entity: the glance `weather_entity`, else the first `weather.*` by friendly name, read from `view.live?.peek()`; stale or missing means `c = 0`.
8. **North (owner: from the map).** The server computes `map_bearing_deg`, the true compass bearing from the house toward its street, using the home building footprint's street-facing edge when the footprint is found, else the nearest street point's normal (house_map.py `compile_layout` `normal`, in true metres before scaling). It is stored once in `house_twin.place.lot.map_bearing_deg` with `map_bearing_source: 'footprint' | 'street'`. It is computed by a background job started when the twin or editor page is served and the value is missing (never inside `twin_site.site()`), and again when the home location changes. `twin_site.site()` serves `front_bearing_deg` = the dial value when `front_bearing_override` is true, else `map_bearing_deg` when present, else the dial value as today. Moving the dial sets `front_bearing_override: true`; a new **Use map direction** button beside the dial clears it. Existing installs have no override flag, so the map wins once it arrives (owner: the dial was moved by hand to try lighting).
9. **One frame for north.** `front_bearing_deg` now means the compass bearing of the direction from the house toward its street, which is plan -y (three +z). `modelDirection` drops the Front camera ray (`atan2(-41,-69)`); its test changes on purpose.
10. **The stage.** A global override of three's `fog_pars_vertex`, `fog_vertex`, `fog_pars_fragment`, `fog_fragment` chunks (instancing-aware world position), active through one `scene.fog` set at mount and never removed: fade factor = `smoothstep(R, R * 1.35, distance(worldPos.xz, stageCentre.xz))` blended toward the sky's horizon radiance in the view direction (sampled from the sky cube, so haze matches the sky at every hour). `R` is the stage radius. Editor overlays (handles, outlines, markers, ghosts) set `fog: false`. The lawn plane becomes a disc out to `R * 1.4`. Custom effect ShaderMaterials inside the lot are exempt (they never reach `R`). The haze is the same one slices 3 and 5 use; this slice drives it only from the stage radius.
11. **Stage radius setting.** `house_twin_stage_radius_ft`, default 120 ft beyond the farthest lot corner from the house centre, range 30 to 1000, in the viewer settings drawer's desk-only sections, GET/PUT under `/api/house/twin/...` like the glance settings, parents only. The editor uses the same value.
12. **Time scrub.** A range input "Time of day" in the viewer's `twin-time-preview` section (0 to 24 h for today, 5-minute steps). During input it re-renders the sky cube, moves the lights and discs (cheap); on `change` (release) it runs the full `updateTime` once (shadows, probes, warm-ups). It returns to Now after the existing 120 s.

## Review Focus

1. Program count unchanged across noon, dusk, midnight, a weather change and a scrub (live test).
2. `scene.environment` stays the same texture object across times (PMREM into one fixed target); reflections show night at night.
3. No NaN or black frame at the horizon, at the sun's position, or with the sun below -18 degrees (night) on high with MSAA.
4. Panel / low tier (no composer, no probes): the sky, discs, stars and haze still look right through `scene.background` and `scene.environment` alone.
5. The library preview page (`library_page/preview.js`) and Unlit keep working.

---

### Task 1: North from the map

**Files:**
- Modify: `chauffeur/services/house_map.py` (return the true street-normal bearing and the home footprint's street-facing edge bearing from the true-metre frame, before scaling), `chauffeur/services/twin_store.py` (store `map_bearing_deg`, `map_bearing_source`, `front_bearing_override`; `set_front_bearing` sets the override), `chauffeur/services/twin_site.py` (rule 8), `chauffeur/main.py` (start the background bearing job when the twin or editor page or state is served and the bearing is missing; a POST to clear the override), `chauffeur/services/auth.py` (tier rule for the new route), `chauffeur/static/twin/sky/look.js` (`modelDirection` per rule 9), `chauffeur/static/twin/editor/place.js` (Use map direction button; show the map's value and source)
- Test: `chauffeur/tests/test_twin_map_bearing.py` (new); update `tests/test_twin_sky_js.py` (`modelDirection` now street-normal based); neighbours `tests/test_house_map.py`, `tests/test_twin_site.py`, `tests/test_twin_house_saves.py`, `tests/test_auth.py` (route tiers only), `tests/test_twin_lot_tools_js.py`

**Interfaces:**
- Produces: `house_map.street_bearing(home_lat, home_lon, data) -> {'bearing_deg': float, 'source': 'footprint' | 'street'} | None` (pure, from fetched tile data, true compass degrees 0..360 clockwise from north); site fields `front_bearing_deg`, `front_bearing_source` (`'map' | 'dial' | 'default'`), `map_bearing_deg` (or absent).
- `modelDirection(azimuth, altitude, frontBearing)`: a body at azimuth equal to `frontBearing` lies toward three +z (plan -y, the street side).

- [ ] **Step 1: failing tests**: a synthetic tile set with a footprint containing the home point and a street to the south gives `bearing_deg` 180 within 1 degree and source `footprint`; rotate everything 30 degrees and the bearing follows; no footprint gives source `street`; no data gives None. Site: override false + map present serves the map value with source `map`; override true serves the dial; no map serves the dial. Dial PUT sets the override; the clear POST clears it. `twin_site.site()` never calls the network (patch the fetch to raise). `modelDirection(180, 0, 180)` is `[0, 0, 1]`; `modelDirection(90, 0, 180)` points to plan +x or -x consistently with east when the street is south (assert with a worked example in the test).
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement.** The background job reuses `neighborhood_layout`'s fetch and cache path and its usage accounting; it runs at most once per home location (keyed like the existing cache), off the request thread.
- [ ] **Step 4: tests and neighbours pass.**

---

### Task 2: The sky cube, environment and reflections

**Files:**
- Create: `chauffeur/static/twin/sky/atmosphere.js` (sky radiance shader + cube renderer), `chauffeur/static/twin/sky/overcast.js` (rule 7, pure)
- Modify: `chauffeur/static/twin/twin_view.js` (`applyTimeLook`, `applySky`, background/environment wiring, overcast read from `view.live`), `chauffeur/static/twin/sky/look.js` (rule 5), `chauffeur/static/twin/reflection_probes.js` (`sky()` returns the sky cube; `backgroundIntensity` semantics; request on sky change), `chauffeur/static/twin/post.js` (no `linearBackground` for a texture background; keep it for Unlit's Color)
- Test: `chauffeur/tests/test_twin_atmosphere_js.py` (new), `chauffeur/tests/test_twin_overcast_js.py` (new); update `tests/test_twin_sky_js.py`, `tests/test_twin_reflection_probes_js.py`, `tests/test_twin_post_js.py` where they pin the old Color background / HDRI behaviour (list each changed assertion in the report); neighbours `tests/test_twin_editor_lighting_js.py`, `tests/test_twin_water_surface_js.py`, `tests/test_twin_water_mirror_define.py`, `tests/test_twin_effect_lighting_water_js.py`, `tests/test_twin_lightmap_material_js.py`, `tests/test_twin_viewing_js.py`, `tests/test_twin_library_js.py`, `tests/test_twin_import_maps.py`

**Interfaces:**
- Produces: `createSky(renderer, { tier }) -> { cube: THREE.CubeTexture-compatible render target texture, environment: THREE.Texture (fixed PMREM target), update({ sunDir, moonDir, moonPhase, moonFraction, overcast, siderealTime, latitude }), horizon(dirWorld) -> THREE.Color (linear), dispose() }`; `overcastFactor(state) -> number` 0..1 per rule 7, where `state` is a HA weather state object or null.

- [ ] **Step 1: failing tests**: radiance is finite and non-negative over a grid of view and sun directions including the sun direction itself and sun altitudes -30..90; zenith is bluer than the horizon at noon; the horizon toward the sun is redder at sun altitude 2 than at 40; night (sun -20) is dim but not zero; `overcastFactor` table per rule 7 including missing attributes, stale and null; `scene.environment` is the same object at noon, dusk and midnight and after an overcast change; `scene.background` is the sky cube in the viewer and Day/Night; Unlit still gives `scene.environment === null`; probes capture with the sky cube as background.
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement** per rules 1, 2, 5, 6, 7. The PMREM is produced into one render target created once (`fromCubemap(cube, target)`); no material recompiles when the sky changes.
- [ ] **Step 4: tests and neighbours pass.**

---

### Task 3: Sun and moon discs, stars

**Files:**
- Create: `chauffeur/static/twin/sky/bodies.js` (discs), `chauffeur/static/twin/sky/stars.js`
- Modify: `chauffeur/static/twin/sky/ephemeris.js` (export `localSiderealTime(date, lonDeg) -> radians`), `chauffeur/static/twin/sky/atmosphere.js` (discs into the cube), `chauffeur/static/twin/twin_view.js` (mount once, update with the time look)
- Test: `chauffeur/tests/test_twin_sky_bodies_js.py` (new); extend `tests/test_twin_ephemeris_js.py` (sidereal time against a published value); neighbours from Task 2

**Interfaces:**
- Produces: `createBodies({ moonMap }) -> { object: THREE.Object3D, update({ camera, sunDir, moonDir, moonPhase, moonDistanceKm, sunAltDeg, moonAltDeg, transmittance, overcast }) }`; `createStars(catalogue) -> { object, update({ camera, siderealTime, latitudeRad, sunAltDeg, moonFraction, overcast }) }`; `discDiameterDeg(kind, altitudeDeg, moonDistanceKm?)` (pure, rule 3).

- [ ] **Step 1: failing tests**: `discDiameterDeg('moon', 60) ~ 2.2`, at 0 degrees `~ 2.2 * 1.6`, at perigee larger than at apogee; the moon's lit side faces the sun direction (the dot product of the lit-hemisphere normal and the sun direction is positive); star count 5080, Polaris (HR 424) within 1 degree of the north celestial pole's altitude = latitude; stars' opacity uniform 0 at sun 0 degrees and 1 at -15; nothing toggles `visible` with time; no Points or Sprites.
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement** per rules 3 and 4.
- [ ] **Step 4: tests and neighbours pass.**

---

### Task 4: The stage, its radius setting, and the time scrub

**Files:**
- Create: `chauffeur/static/twin/sky/stage_haze.js` (chunk override + uniforms)
- Modify: `chauffeur/static/twin/twin_view.js` (install once at mount; stage centre and radius; scrub handling), `chauffeur/static/twin/twin_yard.js` (lawn disc to `R * 1.4`), editor overlay materials (`fog: false`: handles, outlines, markers, ghosts; find them by the `editor-` naming), `chauffeur/templates/house_twin.html` (scrub input; stage radius field in a desk-only section), `chauffeur/services/settings_registry.py`, `chauffeur/main.py` (GET/PUT), `chauffeur/services/auth.py`
- Test: `chauffeur/tests/test_twin_stage_haze_js.py` (new), `chauffeur/tests/test_twin_stage_settings.py` (new); neighbours `tests/test_settings_registry.py`, `tests/test_twin_preview_drawer.py`, `tests/test_twin_yard_reuse_js.py`, `tests/test_twin_yard_grass_js.py`, `tests/test_twin_lightmap_material_js.py`, `tests/test_twin_viewing_js.py`, `tests/test_twin_levels_js.py`, `tests/test_tailwind_build.py`

**Interfaces:**
- Produces: `installStageHaze(scene, sky) -> { set({ centre: [x, z], radius }) }`; setting key `house_twin_stage_radius_ft` (30..1000, default rule 11); scrub input `#twin-time-scrub`.

- [ ] **Step 1: failing tests**: a mesh at the centre has haze 0, at `R * 1.35` and beyond 1; every material kind in a built house (standard, lightmap-patched, viewing clone, grass, water surface, granite, glass) compiles with the override and shares one program per kind across radius changes (program keys unchanged); editor overlays are unhazed; the setting validates the range and parents-only; the scrub sets the preview hour and calls the full `updateTime` once on `change`, not on `input`; the lawn disc reaches `R * 1.4`.
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement** per rules 10, 11, 12. Rebuild Tailwind if template classes change.
- [ ] **Step 4: tests and neighbours pass.**

---

### Task 5: Browser checks (Claude)

**Files:**
- Create: `chauffeur/tests/test_twin_sky_live.py`

- [ ] Viewer at Now, Day, Night and a scrub to sunset: no program compiles after warm-up; screenshots on high (sky, sun disc, moon disc with the right phase, stars at night, the stage edge in haze).
- [ ] A weather state with `cloud_coverage: 100` greys the sky and softens shadows; removing it restores.
- [ ] Panel query (`?panel=true&kiosk=true`, low tier): sky, discs and haze visible; no console errors.
- [ ] Editor Day / Night / Unlit unchanged in behaviour; the dial's Use map direction button.
- [ ] Neighbours: `tests/test_house_twin_real_sun_live.py`, `tests/test_twin_water_surface_live.py`, `tests/test_house_editor_lighting_live.py`.
