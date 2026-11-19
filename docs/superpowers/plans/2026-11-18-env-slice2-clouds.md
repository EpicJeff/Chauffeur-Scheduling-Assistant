# Environment slice 2: clouds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Volumetric clouds whose amount and type follow the real weather, drift with the real wind, are lit by the sun and moon, cast moving shadows on everything, and flash with lightning in thunderstorms.

**Architecture:** One cloud model (a 2D weather map for coverage and type, plus tiling 3D noise) is ray-marched by a shared GLSL function in three places: a screen-space cloud pass behind all geometry for the visible sky, the existing sky cube (so reflections, environment light and the low tier carry the clouds), and a small top-down cloud shadow map projected along the sun into every lit material through a lights chunk override installed once at mount (the same pattern as slice 1's stage haze). Weather and wind arrive through slice 1's weather plumbing (`sky/overcast.js`, `view.live`).

**Tech Stack:** three r187 (vendored), plain ES modules, node-driven tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-18-twin-environment-design.md`, "Slice 2: clouds" and "Weather data contract". Slice 1 is shipped (v2.499.937): read `chauffeur/static/twin/sky/atmosphere.js`, `sky/overcast.js`, `sky/stage_haze.js`, `sky/bodies.js`, `twin_view.js` `applyTimeLook`, and the slice 1 entry at the top of `chauffeur/system_capabilities.md` before starting.

## Global Constraints

- Work in `E:\repositories\Chauffeur-env-clouds` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser. Claude runs the browser checks.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run the named tests and neighbours. **Also run every test file that mounts the twin view** (grep `tests/test_*_js.py` for `twin_view.js`, `from test_twin_drag_js` and `twin_editor_dom`) before reporting: slice 1 broke ten such files that its named lists missed. Compare any failure against main (create a detached baseline worktree of main outside the repo folder if needed; never edit it).
- **Program keys never change with time, weather, wind or coverage.** The cloud pass, the cube cloud term and the shadow chunk are installed once at mount; everything else is uniforms and texture contents.
- Every shader: floor every `pow` base, no unguarded division, no NaN reaching bloom (the guard pattern in `sky/atmosphere.js` and `post.js` `guardSample`). Pin defines to vendored r187 names.
- No new packages. No `transmission`. No new long-lived stream. Every new module appears in the generated import maps (`tests/test_twin_import_maps.py`).
- Degrade: no weather entity means clear sky (no clouds); the editor stays clear (slice 1's neutral editor rule).
- **The environment never shows anything that could read as a device's state** (owner rule).

## Rulings (Claude's calls within the spec)

1. **Cloud model.** A layer from 1500 m to 4000 m above ground (stratus 500-1500 m when the type calls for it). Density = weather-map coverage remapped through a tiling 3D base noise (Perlin-Worley, 128^3) and eroded by a 3D detail noise (Worley, 32^3), both generated once at mount on the CPU into `Data3DTexture`s (or on the GPU once), never per frame. Height gradient per type: cumulus (rounded bottoms, billowing tops), stratocumulus (flatter, broader), stratus / nimbostratus (thick low sheet, dark undersides), cumulonimbus towers for lightning conditions.
2. **Weather mapping** (extends slice 1's `overcastFactor`): coverage `c` as slice 1 (cloud_coverage / 100, else the condition table); type by condition: `sunny`/`partlycloudy`/`windy*` cumulus; `cloudy` stratocumulus; `rainy`/`pouring`/`snowy`/`snowy-rainy`/`hail`/`fog`/`exceptional` nimbostratus; `lightning*` cumulonimbus; `clear-night` none. Missing or stale weather: clear.
3. **Lighting of clouds.** Beer-Lambert extinction, Henyey-Greenstein dual-lobe phase (forward g .8, back g -.3, mixed), powder term (`1 - exp(-2d)`), multiple-scattering approximation by octaves (Wrenninge style, 3 octaves). Sun and moon both light the clouds (the moon by its radiance and phase); ambient from slice 1's sky (top) and ground (bottom) colours. Cloud radiance is in the same scene-linear units as the atmosphere so exposure and bloom need no retuning.
4. **Visible clouds: screen pass.** Ray-march at half resolution on high and max, quarter on medium, with a per-pixel blue-noise start offset; bilateral (depth-aware) upsample; composite behind all geometry (only where the depth buffer is at the far plane) and in front of the sky cube's atmosphere, before bloom and tone mapping, so the composer and the plain path stay identical (slice 1's rule). The sun and moon discs show through thin cloud by the cloud transmittance. Optional temporal reprojection is the builder's call if the half-res march is not stable enough; say which in the report.
5. **Sky cube and the low tier.** The cloud term is also marched into slice 1's sky cube (at cube resolution, fewer steps), so reflections, environment light and the low tier (no composer, the Pi panel) all show the same clouds. The cube refreshes on the existing triggers plus cloud drift: at most every 4 s while clouds move, through the existing fixed render target (no recompile).
6. **Cloud shadows.** A 512 x 512 top-down cloud shadow map (256 on low and medium) covering the stage radius plus 50%, holding the transmittance of sunlight through the cloud layer along the sun direction for each ground point. Re-rendered when the sun, coverage or drift moves it more than a texel (at most every 250 ms). Applied by a lights chunk override, installed once at mount, that multiplies the **sun** directional light's contribution by the shadow map sample at the fragment's world position (the moon is dimmed by the same map at night). It must reach standard and physical materials, the lightmap-patched and viewing-clone materials, the grass, and the custom water (`waterSun`) and effect shaders (they read the same map through a shared uniform). Overcast lifts sky light as slice 1's interim does; slice 1's interim scalar sun dimming is replaced by the real cloud transmittance at the house (sampled from the shadow map at the stage centre), so the two never double-dim.
7. **Drift.** Wind from `wind_speed` (convert by `wind_speed_unit`: km/h, mph, m/s, kn) and `wind_bearing` (degrees the wind comes FROM; clouds move toward bearing + 180). Cloud drift speed = max(2 m/s, wind m/s x 2) x 6 (the x 2 is wind aloft, the x 6 is panel readability). No wind data: 3 m/s from the west. Detail noise scrolls 1.3 x faster than the base so cloud shapes evolve.
8. **Lightning** only under `lightning` and `lightning-rainy`: flashes at random intervals of 4-18 s (a double flash 30% of the time), each 80-160 ms, lighting the cloud volume from a random point inside the nearest cumulonimbus cell (a point light term in the cloud march) and briefly lifting the scene's hemisphere light; fades by uniforms only. Reduced motion (`prefers-reduced-motion`) disables the flashing but keeps the clouds.
9. **Interim overcast retires.** Slice 1's sky greying toward grey (horizon-weighted) is replaced by the clouds themselves; keep its sky-light lift. The editor stays clear.

## Review Focus

1. No new programs after warm-up across clear, partly cloudy, overcast, thunderstorm, day, golden hour and night (the slice 1 live check pattern).
2. No NaN or black frame with the sun inside a cloud, at the horizon, below the horizon, and with coverage 0 and 1.
3. Cloud shadows reach every lit material kind (a material census test), never double-dim with the slice 1 overcast scalar, and stay put in the editor's clear look.
4. The low tier (no composer) shows clouds through the cube and the shadow map, not nothing.
5. Frame cost of the cloud pass at 1080p high on the desktop is reported (ms), and the cube refresh never stalls the frame.

---

### Task 1: The cloud model, weather and wind mapping

**Files:**
- Create: `chauffeur/static/twin/sky/clouds.js` (weather-to-cloud mapping, wind conversion, the noise textures, the shared GLSL cloud functions exported as strings), `chauffeur/static/twin/sky/cloud_noise.js` (tiling Perlin-Worley and Worley generation)
- Modify: `chauffeur/static/twin/sky/overcast.js` (export the condition table for reuse)
- Test: `chauffeur/tests/test_twin_clouds_js.py` (new)

**Interfaces:**
- Produces: `cloudState(weather, { now }) -> { coverage, type, windMps, windToDeg, lightning }` (pure; rulings 2, 7, 8); `windSpeedMps(value, unit)`; `createCloudNoise({ size: 128, detail: 32 }) -> { base: THREE.Data3DTexture, detail: THREE.Data3DTexture, dispose() }`; `CLOUD_GLSL` (a string of GLSL functions: `cloudDensity(vec3 p)`, `cloudLight(vec3 p, vec3 sunDir)`, `marchClouds(vec3 ro, vec3 rd, float maxSteps, ...)`).
- [ ] Failing tests: every HA condition maps per ruling 2; coverage from `cloud_coverage` beats the table; wind units convert (36 km/h = 10 m/s; 10 kn = 5.144 m/s); bearing 270 drifts east; no wind gives 3 m/s from the west; the noise textures tile (value at x=0 equals x=size within 1e-6) and are deterministic; a CPU port of `cloudDensity` is 0 below the layer and with coverage 0, and > 0 inside the layer with coverage 1.
- [ ] Run, see them fail. Implement. Run, pass.

### Task 2: Visible clouds and the sky cube

**Files:**
- Create: `chauffeur/static/twin/sky/cloud_pass.js`
- Modify: `chauffeur/static/twin/sky/atmosphere.js` (cloud term in the cube; retire the interim greying per ruling 9), `chauffeur/static/twin/sky/bodies.js` (disc transmittance through cloud), `chauffeur/static/twin/twin_view.js` (mount the pass once, feed `cloudState`), `chauffeur/static/twin/post.js` (insert the composite before bloom/output on composer tiers; plain path parity)
- Test: `chauffeur/tests/test_twin_cloud_pass_js.py` (new); update `tests/test_twin_atmosphere_js.py`, `tests/test_twin_overcast_js.py`, `tests/test_twin_post_js.py` where they pin the interim greying (list each changed assertion); neighbours: every test that mounts the twin view (Global Constraints)

**Interfaces:** `createCloudPass(renderer, { tier, noise }) -> { render(scene, camera, depthTexture), update(cloudState, light), dispose() }`.
- [ ] Failing tests: program keys stable across cloud states; coverage 0 draws nothing (cloud alpha 0 everywhere); the pass only touches far-plane pixels; cube faces contain cloud radiance when coverage is 1 and none at 0; the sun disc's visible strength scales with the cloud transmittance along its direction; plain-path and composer outputs match for a cloud pixel within the existing tolerance.
- [ ] Run, fail, implement, pass.

### Task 3: Cloud shadows in every lit material

**Files:**
- Create: `chauffeur/static/twin/sky/cloud_shadow.js` (the shadow map render, the lights chunk override, the shared uniform)
- Modify: `chauffeur/static/twin/twin_view.js` (install once at mount; replace the interim sun scalar per ruling 6), the custom shaders that compute their own sun term (`effects/water_surface.js` `waterSun`, `yard_grass.js`, effect materials that read the sun), `bake/lightmap_material.js` and `viewing.js` only if their patches bypass the chunk
- Test: `chauffeur/tests/test_twin_cloud_shadow_js.py` (new; includes the material census: every lit material kind in a built house compiles with the override and samples the shadow map); neighbours: every test that mounts the twin view
- [ ] Failing tests: a fragment under a cloud gets the sun term scaled by the map's transmittance and one outside does not; the house-centre transmittance replaces the interim sun scalar (never both); program keys unchanged across coverage and time; the editor's clear look keeps transmittance 1.
- [ ] Run, fail, implement, pass.

### Task 4: Lightning

**Files:**
- Modify: `chauffeur/static/twin/sky/clouds.js`, `cloud_pass.js`, `twin_view.js`
- Test: extend `chauffeur/tests/test_twin_clouds_js.py`
- [ ] Failing tests: flashes only for the two lightning conditions; interval and duration within ruling 8; reduced motion gives no flash; fading by uniforms only (no visibility or define change).
- [ ] Run, fail, implement, pass.

### Task 5: Browser checks (Claude)

- [ ] New `tests/test_twin_clouds_live.py` with the fake HA weather entity: clear, partly cloudy (cumulus), overcast (nimbostratus), thunderstorm (lightning flash seen in a frame-difference check), at noon, golden hour and night; programs stable after the first pass; screenshots for the owner.
- [ ] Measure the cloud pass ms at 1080p high (renderer timer query or frame time delta) and report it.
- [ ] Neighbours: `tests/test_twin_sky_live.py`, `tests/test_house_twin_real_sun_live.py`, `tests/test_twin_water_surface_live.py`.
