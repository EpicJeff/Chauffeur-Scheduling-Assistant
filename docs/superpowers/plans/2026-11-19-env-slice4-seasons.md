# Environment slice 4: seasons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The twin follows the year: deciduous trees and shrubs green up, colour in autumn, drop their leaves and stand bare in winter while evergreens stay green; the lawn goes dormant and greens up the way the household's grass type really does; and three small touches appear in season: autumn leaves blowing with the real wind, fireflies on warm summer nights, light shafts at low sun.

**Architecture:** The add-on extends slice 3's ground record with a running 7 to 10 day air-temperature average, recent rain and a lawn dormancy state (0 green to 1 dormant) for the household's grass type, delivered through the same weather-state route. In the browser a season state (date and latitude phenology for trees; the server's lawn state, or a latitude calendar without weather history) drives tree and lawn materials through uniforms that live only in tree, shrub, lawn and grass programs (the shared lit path is at its 224-vector ceiling and gets nothing). The small touches are their own drawn objects or a post pass on the composer tiers.

**Tech Stack:** FastAPI services (`chauffeur/services/twin_weather_state.py`, settings), plain ES modules under `chauffeur/static/twin/` (yard, grass, trees, sky, post), three r187, node tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-18-twin-environment-design.md`, "Slice 4: seasons", "Weather data contract", "Where the live state applies", "Settings". Slices 1-3 are shipped (sky v2.499.937, clouds v2.499.941, weather v2.499.944): read their entries at the top of `chauffeur/system_capabilities.md`, `services/twin_weather_state.py`, `static/twin/sky/weather.js`, `sky/wind.js`, `sky/weather_surface.js`, `sky/precipitation.js`, `yard_grass.js`, `twin_yard.js` (EZ-Tree presets and plant cards).

## Global Constraints

- Work in `E:\repositories\Chauffeur-env-seasons` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser. Claude runs the browser checks.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run the named tests and neighbours, and every test file that mounts the twin view (grep `tests/test_*_js.py` for `twin_view.js`, `from test_twin_drag_js`, `twin_editor_dom`); compare failures with main in a detached baseline outside the repo folder. Node tests also run over the real household fixture.
- **Uniform and sampler budget:** the shared lit-material path is full (the heaviest stress program is at 224 of 224 guaranteed fragment vectors and 16 of 16 samplers). Season uniforms go **only** into tree, shrub, lawn and grass programs (which are below the ceiling: assert their totals in the census); nothing is added to the shared chunks, and no sampler is added anywhere a lit material can see.
- **Program keys never change with date, season, dormancy, previews or weather.** Everything installed once; the rest is uniforms and object visibility.
- Every shader: floor every `pow` base, no unguarded division, no NaN reaching bloom.
- **Degrade:** no weather entity or no history: trees follow the date and latitude alone; the lawn follows a growing-season calendar for the latitude. Nothing is required beyond what slice 3 needs.
- **Never anything that reads as a device's state** (owner). Fireflies and light shafts are nature, not devices; they never appear indoors or on a device.
- **Editor:** neutral by default (summer leaves, green lawn; slice 1's rule); the editor's Live weather lighting choice shows the live season too.
- New settings go in `services/settings_registry.py` and the feature's own page or drawer (spec "Settings": the lawn grass type on the lawn / lot card in the editor); never `config.html`. No new long-lived stream. No new packages. No `transmission`. New modules appear in the generated import maps. No browser dialogs. Every new route gets an auth rule.
- Imported tree models that cannot change keep their look.

## Rulings (Claude's calls within the spec)

1. **Temperature record (server):** extend slice 3's ground record with an hourly temperature log of at most 240 entries (10 days) and the rain hours of the last 10 days; the running average is the mean of the last 7 to 10 days available (at least 3 days of data, else "no history"). Stored in the same row, fixed size.
2. **Lawn dormancy (server), 0 green to 1 dormant, moving at most 1/14 per day** (about two weeks for a full change):
   - Warm-season: after the first frost of the autumn (an hourly temperature at or below 0 C after 1 August in the northern hemisphere, 1 February in the southern), target 1 when the average is below 12.8 C (55 F); target 0 once the average rises past 18.3 C (65 F); between, hold.
   - Cool-season: target .6 (brown) when the average is at or above 29.4 C (85 F) with under 6 mm-equivalent rain hours (fewer than 6 rain hours) in the last 10 days; target .3 (dulled) when the average is below 0 C; otherwise target 0.
   - No history: a calendar by latitude (warm-season dormant from the first average-frost month to the last, cool-season green except a .3 dull in the coldest month), using the same latitude source as slice 1.
   - The route adds `lawn: {dormancy, grass_type, source: 'history'|'calendar'}` and `season: {avg_temp_c, history_days}` to the weather-state JSON.
3. **Lawn grass type setting:** `lawn_grass_type` = `cool` (default) or `warm`, in `settings_registry.py`, shown on the lawn / lot card in the editor (beside the lawn material) with the examples from the spec (warm: Bermuda, zoysia, St. Augustine; cool: fescue, bluegrass, rye).
4. **Lawn look:** dormancy tints the lawn material and the grass blades (and the paver joint grass) toward a straw tan (scene-linear [.42, .34, .2] relative to the green's luminance) with a world-space patch noise so the change arrives in patches (a cell turns when dormancy passes its own threshold), through uniforms only in lawn and grass programs.
5. **Trees and shrubs (browser):** each EZ-Tree preset and plant kind is tagged deciduous or evergreen (pines, spruces, firs, junipers, boxwood, holly evergreen; the rest deciduous; say the full table in the report). Phenology from the day of year and latitude (northern; mirrored south): green-up over 3 weeks from a latitude-dependent spring date, full summer green, autumn colour over 3 weeks (each tree picks a hue in yellow-orange-red by a stable per-tree hash), leaf drop over 2 weeks, bare until spring. Leaf colour and leaf presence go through uniforms on the leaf material (presence as an alpha-test threshold over a per-leaf random attribute, so leaves drop individually); branches stay. Low-tier plant cards change colour and thin through the same uniforms. Imported tree models keep their look.
6. **Snow on branches** already comes from slice 3's surface layer; bare winter trees keep it on the branches.
7. **Autumn leaves:** during autumn colour and leaf drop, a few hundred leaf sprites (per tier: low 150, medium 300, high 500, max 800) tumble down and blow with slice 3's wind near the deciduous trees in view, own program, one draw; none in the editor's neutral look.
8. **Fireflies:** on summer nights (sun below -4 degrees, temperature at or above 18 C, not raining, June to August north / December to February south, or a preview), up to 60 soft blinking points (low 25) hovering .3 to 1.5 m over the lawn near the house, never indoors; own program, additive, one draw.
9. **Light shafts:** with the sun between -2 and 12 degrees and in front of the camera's half-space, a screen-space radial light-shaft pass from the sun's screen position on the composer tiers (medium, high, max), masked by depth (sky pixels only as the source), strength scaled by sun visibility through slice 2's clouds; the low tier has none (stated here as the tier choice the spec asks the plan to name).
10. **Season previews:** Spring, Summer, Autumn, Winter in the viewer's Preview drawer beside the weather previews, 120 s then live (as slice 3's previews); a Winter preview also sets dormancy 1 for warm-season lawns.

## Review Focus

1. No new programs across the four seasons, dormancy 0 to 1, fireflies on and off, light shafts on and off, previews and back to live.
2. The heaviest lit stress program is unchanged (224/224, 16/16); season uniforms appear only in tree, shrub, lawn and grass programs.
3. Evergreens never change; imported tree models never change.
4. No weather entity: the calendar drives the lawn and the date drives the trees; the source report says so.
5. Southern-hemisphere latitudes mirror the seasons.

---

### Task 1: Temperature record, lawn dormancy, the grass type setting

**Files:**
- Modify: `chauffeur/services/twin_weather_state.py` (rulings 1 and 2), `chauffeur/main.py` (route payload), `chauffeur/services/settings_registry.py` (ruling 3), the editor's lawn / lot card for the setting (`static/twin/editor/` where the lawn material row lives)
- Test: extend `chauffeur/tests/test_twin_weather_state.py` (the average over simulated days, warm and cool dormancy over a simulated year of hourly temperatures, the two-week rate limit, first-frost rule, southern hemisphere, calendar fallback, fixed record size, restart), the editor card test for the setting

- [ ] Failing tests, run, implement, pass.

### Task 2: Trees, shrubs and the lawn through the year

**Files:**
- Create: `chauffeur/static/twin/sky/seasons.js` (phenology, the season state, previews)
- Modify: `chauffeur/static/twin/twin_yard.js` (deciduous/evergreen tags, leaf presence attribute, uniforms on leaf and card materials), `yard_grass.js` and the lawn material (dormancy), the paver joint grass, `twin_view.js` (season state from date, latitude and the route; previews; editor neutral), the viewer Preview drawer template (season previews)
- Test: `chauffeur/tests/test_twin_seasons_js.py` (new: phenology dates for 40 N and 35 S; leaf colour and presence over the year; evergreens unchanged; dormancy tint and patches; previews; program keys unchanged; the census: season uniforms only in tree/shrub/lawn/grass programs and their totals below the ceiling; the real household)

- [ ] Failing tests, run, implement, pass.

### Task 3: Autumn leaves, fireflies, light shafts

**Files:**
- Create: `chauffeur/static/twin/sky/season_touches.js`
- Modify: `chauffeur/static/twin/post.js` (light-shaft pass on composer tiers), `twin_view.js`
- Test: `chauffeur/tests/test_twin_season_touches_js.py` (new: conditions of rulings 7-9; counts per tier; none in the editor's neutral look; no program change on/off; fireflies never inside a building footprint; light shafts NaN-safe with the sun behind the camera and at the horizon; composer and plain path parity)

- [ ] Failing tests, run, implement, pass.

### Task 4: Browser checks (Claude)

- [ ] New `tests/test_twin_seasons_live.py`: screenshots for each season preview at noon and golden hour on high and low; a warm-season lawn in winter; autumn leaves blowing; fireflies on a summer night; light shafts at sunrise; no new programs across all of it; the census in Chromium; frame cost of the touches at 1080p high (frame cap off).
