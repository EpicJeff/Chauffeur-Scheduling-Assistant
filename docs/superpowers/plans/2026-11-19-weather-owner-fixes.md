# Weather owner fixes (after v2.499.944) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four problems the owner found on his own machine after weather and seasons shipped: surfaces never look properly wet (no drop spots, no puddles, no pool ripples); rain fills the screen in floor and room views; snow and wetness appear on covered and indoor surfaces; fog fades things around the house instead of fading with distance from the camera.

**Architecture:** (1) A per-vertex "open to the sky" value computed on the CPU from what covers each point (roofs with their overhangs, porch roofs, upper floors and ceilings, the inside of buildings) is written into the generated geometry as a vertex attribute and multiplies every weather surface term, so covered surfaces stay dry and snow-free without any new uniform or sampler. (2) Wetness builds over time on the add-on and the surface layer turns it into a progression: drop spots, then glossy puddle spots, then mostly glossy surfaces with larger puddles; pool and spa rain rings become clearly visible. (3) Precipitation hides in floor and room views and steep downward views. (4) Fog becomes atmospheric extinction by distance from the camera, set by visibility, reusing existing haze uniform lanes.

**Tech Stack:** `chauffeur/services/twin_weather_state.py`, `chauffeur/static/twin/sky/weather_surface.js`, `sky/precipitation.js`, `sky/stage_haze.js`, `sky/weather.js`, `twin_generator.js` / `twin_yard.js` (geometry attributes), `effects/water_surface.js`, `twin_view.js`, three r187, node tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-18-twin-environment-design.md`, "Slice 3: weather" (unchanged intent), plus the owner's feedback of 2026-11-19 quoted here: "when it starts raining you actually see drops on the surfaces (like little spots of darkening) and then it starts to show puddling (glossy spots). After a while most of the surfaces would be fairly glossy with larger puddles." / "If you are viewing a floor or room with rain on, you get a horrible view with rain drops all up in your face." / "Snow and rain effects happen on covered surfaces including inside the house. There is snow on the wood floors, carpet, furniture, etc. It should be limited to surfaces that have a clear view to the sky (not covered)." / "I would expect it to be an atmospheric fog that fades things out from the view of the camera, not fading things around the house." His screenshots: an eye-level rainy yard with dry-looking paving, coping and lawn and an unrippled pool; a top-down floor view of the pool house with a radial burst of huge rain streaks; a top-down snowy floor view with snow on the wood floor, sofa, stairs and interior; heavy fog where the house is a clear disc and everything around it is white.

## Global Constraints

- Work in `E:\repositories\Chauffeur-weather-fix` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser. Claude runs the browser checks.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run the named tests and neighbours and every test file that mounts the twin view; compare failures with main in a detached baseline. Node tests run over the real household fixture (it has the pool house with furniture, a covered porch and eaves).
- **Budget (hard):** the shared lit path is at 224 of 224 guaranteed fragment vectors and 16 of 16 samplers. Add **no** uniform vector and **no** sampler to lit materials. Vertex attributes are allowed (the open-to-sky value). New fog and wetness behaviour must reuse existing uniform lanes (the packed `weatherSurface` vec4, the haze ring's or haze parameters' spare lanes); prove totals in the census.
- Program keys never change with weather, time, previews, views or ground state. Floor every `pow` base; no unguarded division; no NaN reaches bloom.
- Nothing reads as device state. The editor stays neutral unless Live weather is on.

## Rulings (Claude's calls)

1. **Open to the sky (`weatherOpen`, 0..1, per vertex):** computed once per generated geometry from a CPU cover model: a point is covered (0) if it lies inside a building's footprint below its roof, under a roof or porch roof including its overhang/eave, or under an upper floor slab or ceiling above it; otherwise open (1), with a .6 m soft edge (linear ramp) at eave lines so the drip edge reads. Upward faces of the roofs themselves are open. Interior walls, floors, ceilings, furniture, items and anything inside a building footprint are 0. Trees, yard pieces and the pool are open unless under a roof or pergola-like covering in the plan. Store as a vertex attribute on merged batches (house, yard, furniture, plants, pool); a geometry without the attribute behaves as open (default 1) so nothing breaks. Every weather surface term (wetness, drop spots, puddles, snow, rain rings) multiplies by it. Precipitation splashes skip covered points; falling drops are culled inside building footprints below roof height.
2. **Wetness builds (server):** while raining, wetness rises at `rate / 40 min` (pouring reaches 1 in 40 minutes, rainy .45 in about 90); mix counts half; melting snow wets at .5 / 40 min; drying unchanged. Puddle amount rises once wetness passes .45 and keeps growing with rain duration (full puddles after 60 minutes of pouring). Previews: Rain and Pouring ramp wetness 0 to 1 and puddles 0 to 1 over 90 seconds of the 120-second preview so the person sees the progression; Thunderstorm likewise.
3. **The wet progression (surface layer, from the packed vec4 only):** wetness 0 to .35: world-space drop spots (hashed cells about 3 cm, each spot darkens 25% and gains gloss when wetness passes its own random threshold), density rising with wetness; .35 to .7: spots merge, the surface darkens toward the full wet colour (ruling 4 of slice 3: up to 35%) and glossy puddle spots appear in low-frequency noise hollows on upward open faces; .7 to 1: most surfaces glossy (roughness toward .12) and puddles grow into larger connected patches by the puddle amount. Lawn gets darker and slightly glossier blades but no standing puddles unless puddle amount > .8 (then shallow patches). Roofs, walls and vertical faces: darkening and streaky gloss, no puddles. Rain rings on puddles, paving and water.
4. **Pool and spa ripples:** rain rings on water clearly visible at the eye-level view of the owner's screenshot: ring density and amplitude scale with rate so pouring shows dense overlapping rings across the whole surface; keep within the water program's existing uniforms (the packed vec4 and its own clock).
5. **Precipitation in views:** hidden (visibility false, counts 0) when the view is a floor or room level (the levels state is not the house/exterior view), or when the camera looks down more steeply than 55 degrees; drops nearer than 3 m are culled; the streak length floor applies only along a streak's projected fall direction and fades out when that projected direction is shorter than 4 px (a streak falling toward the camera is drawn as a short dot, never stretched).
6. **Fog:** atmospheric extinction by distance from the camera: `fogFactor = 1 - exp(-k * d)` with `k = 3.912 / visibility_m` (visibility from the entity; `fog` condition without a visibility value means 300 m; rain adds a veil equivalent to visibility `mix(20 km, 3 km, rate)`; take the shorter). Applied in the existing haze fog chunk alongside (combined by max with) the stage's radial fade, using spare existing uniform lanes; the sky and clouds blend toward the fog colour by the fog factor at their distance (sky = far). The old "pull the stage haze in around the house" fog behaviour is removed; the stage's radial fade returns to its clear distance in fog.

## Review Focus

1. Indoors (floors, rugs, furniture, stairs, interior walls) never shows snow, wetness, puddles or rain rings; a covered porch floor stays dry; the open deck beside it gets wet.
2. A floor or room view during rain or snow shows no precipitation on screen.
3. Fog at 300 m visibility from the house overview: the house is softened, the far yard fades out; nothing near the camera is fogged more than far things.
4. The progression is visible over a 90-second Rain preview from the owner's eye-level pool view: spots, then puddle spots, then gloss and larger puddles; the pool shows rings.
5. Budget unchanged: the heaviest stress program stays at 224 vectors and 16 samplers; no program key changes.

---

### Task 1: Open to the sky

**Files:** create `chauffeur/static/twin/sky/sky_cover.js` (cover model and per-vertex value); modify `twin_generator.js`, `twin_yard.js`, furniture/item builders, pool features (write the attribute), `sky/weather_surface.js` (read it), `sky/precipitation.js` (splash and drop culling)
**Test:** `chauffeur/tests/test_twin_sky_cover_js.py` (new: the household's interior floors, rugs, sofa and stairs are 0; covered porch floor 0; open deck and lawn 1; eave soft edge; roof upward faces 1; attribute present on every lit batch or defaulting to 1; snow/wetness terms zero where covered in the scalar port; no uniform or sampler added, census unchanged)

- [ ] Failing tests, run, implement, pass.

### Task 2: Wetness builds, the wet progression, pool ripples

**Files:** `chauffeur/services/twin_weather_state.py` (ruling 2), `sky/weather.js` (preview ramps), `sky/weather_surface.js` (ruling 3), `effects/water_surface.js` and the water path of the surface layer (ruling 4)
**Test:** extend `tests/test_twin_weather_state.py` (ramp rates), `tests/test_twin_weather_js.py` (preview ramp over 90 s), `tests/test_twin_weather_surface_js.py` (scalar port: spot coverage at wetness .1/.3/.5/.9, puddle coverage vs amount, lawn rules, vertical faces no puddles, ring density vs rate on water; census unchanged)

- [ ] Failing tests, run, implement, pass.

### Task 3: Precipitation in views, and fog

**Files:** `sky/precipitation.js` and `twin_view.js` (ruling 5), `sky/stage_haze.js`, `sky/atmosphere.js`, `sky/clouds.js`, `sky/weather.js` (ruling 6)
**Test:** extend `tests/test_twin_precipitation_js.py` (hidden in floor/room views and steep views; near cull; no stretched streaks toward the camera), `tests/test_twin_stage_haze_js.py` / weather tests (camera-distance fog factor at 50 m, 150 m, 600 m for 300 m visibility; rain veil; stage radial unchanged in fog; census unchanged)

- [ ] Failing tests, run, implement, pass.

### Task 4: Browser checks (Claude)

- [ ] Extend `tests/test_twin_weather_live.py`: an eye-level camera at the pool (like the owner's screenshot) for rain over the 90-second ramp (screenshots at 0, 30, 60, 90 s), pouring with pool rings, snow; a top-down floor view of the pool house in rain and snow (no precipitation on screen; no snow or wetness indoors); fog at 300 m visibility from the overview and from eye level; no new programs; the census.
