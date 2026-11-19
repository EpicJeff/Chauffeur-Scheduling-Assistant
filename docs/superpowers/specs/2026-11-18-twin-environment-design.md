# House twin environment: sky, weather, seasons, surroundings

Brainstormed with the owner on 2026-11-18. Lines marked *(Claude's call)* are the author's decisions, not the owner's; everything else is the owner's direction.

## Why

The twin models the house and yard; the owner now wants its surroundings to mirror the real world as well. "This is just part of the concept of a digital twin." It runs on a wall panel the family looks at and touches through the day. Today the sky is a flat colour, there is no visible sun or moon, no weather, no seasons, and past the lot there is a lawn plane and then nothing.

The look target is Twinmotion, which the owner uses for their own yard: volumetric clouds lit by the sun, a visible sun and moon, stars at dusk, rain with wet glossy ground, puddles and ripples on the pool, snow that settles on the ground and on trees, and trees that change with the seasons.

Hardware does not limit the vision. The panel is a Pi 5 today; the owner will solve performance separately ("Hardware is an addressable issue"). Design for the right look first and treat cost as an engineering problem within the existing tier system, never as a reason to drop a feature.

## Goals

1. The sky, sun, moon and stars match the real time and place, with smooth transitions through dawn, day, dusk and night.
2. The sun and moon are drawn the way the eye sees them: larger than true angular size, larger again near the horizon, with real positions, the real moon phase, and the colour and dimming of the low sky.
3. Volumetric clouds whose amount follows the real cloud cover, drift with the real wind, are lit by the sun and moon, and cast moving shadows on everything.
4. The weather on screen is the current weather: rain, snow, fog, wind and thunderstorms, including what weather does to surfaces (wet, glossy ground, puddles, ripples; snow cover on upward faces).
5. Trees, shrubs and the lawn follow the real season.
6. Reflections show the sky the viewer sees.
7. The real surroundings out to a radius (streets, neighbouring house shells with a little landscaping, woods and other land cover), fading into haze beyond. Until that exists, a circular stage: everything fades out at a set radius.

## Non-goals

- Drawing anything far beyond the radius. "Building a drawing too far is pointless and costly."
- A Twinmotion-style panel of cloud and weather sliders. The real weather drives it; previews exist only to look and check.
- Detailed neighbouring houses. Simple shells with a little landscaping.
- Changing the indoor views.

## Anti-goals

- **Anything that could be mistaken for a device's state.** Window glow, steam, smoke and similar already mean "something in your house is on" (lights, the pool heater, heating and cooling). The environment never adds them. Ambient effects come only from nature and the weather. (Owner, 2026-11-18, ruling out chimney smoke, pool steam on cold mornings, and dusk window glow.)
- Weather that disagrees with the real weather, for example rain on screen while it is dry outside.
- Water and glass that keep reflecting a fixed daytime sky at night, which they do today.
- Streets, sun and shadows that disagree about which way is north.

## Constraints

- Repository rules in `AGENTS.md`. In particular:
  - Every Home Assistant touchpoint degrades gracefully: with no weather entity, the sky is clear and the season comes from the date alone.
  - New settings go in `services/settings_registry.py` and the feature's own page or drawer.
  - Tailwind is rebuilt after template class changes.
  - No browser dialogs.
- Never add a long-lived stream per tab (each house tab holds two; the browser allows six per host). Weather is already streamed to the twin: every `weather.*` entity with all attributes (`main.py:12396`, `static/twin/live/live.js:669`).
- No `transmission` on any material. Per-edit or per-weather data never grows the `house_twin` settings row.
- Material identity, tint, bake role and UV offset rules from the material library design are locked.
- Custom shaders: every new blur goes through the existing NaN guards and every `pow` base needs a floor (memory: the black-view and steam-shader fixes). The background colour path in `static/twin/post.js` undoes ACES for the clear colour; a sky that replaces it must keep the image identical with and without the composer.
- Device verification happens on the owner's machine and panel. Nothing ships as "done" on CPU tests alone.

## What exists (recon, main v2.499.935)

- **Sky:**
  - A flat `scene.background` colour from four sun-altitude bands (`static/twin/sky/look.js:50-69`, applied in `twin_view.js` `applyTimeLook`).
  - A fixed Poly Haven partly-cloudy HDRI is the environment for lighting and reflections and never changes (`twin_library.js:578-586`). Reflection cubes capture that HDRI as their background (`reflection_probes.js:389`).
  - No fog anywhere.
- **Sun and moon:**
  - `static/twin/sky/ephemeris.js` has sun and moon positions (with parallax), moon illumination fraction and phase, and rise/set times.
  - Location comes from the household's cached geocode (`services/twin_site.py`).
  - Two directional lights, `real-sun` (casts the single 4096 sun shadow, framed on the buildings) and `real-moon`.
  - Modes Now / Day / Night. Previews return to Now after 120 s.
  - Neither body is drawn. `modelDirection` (`look.js:39-48`) is keyed to the oblique Front camera ray, about 31 degrees off the plan's street axis.
- **Weather:**
  - Only the idle card reads it (icon, temperature).
  - Entity choice: the `weather_entity` setting, else the first one (`services/twin_glance.py:69-80`).
  - Nothing reads `cloud_coverage`, `wind_speed`, `wind_bearing`, `humidity`, `visibility` or precipitation.
  - The legacy 3D House had rain lines, snow points, a painted cloud dome and sun dimming (`static/house_weather.js`, `static/house.js:12091-12181`). Useful as a pattern; the art does not carry over.
- **Bake:** only room lamps bake; sun and sky are fully real-time (sky bake removed in v2.499.790), so moving cloud shadows do not conflict with baked light. Materials are already patched for lightmaps and for viewing clones.
- **Wind:** only the grass has wind, a hard-coded gust (`yard_grass.js`). Trees and plants do not sway.
- **Surroundings:**
  - The lawn plane runs to the lot bounding box ±150 ft; grass blades stop 4 ft past the lot line.
  - Beyond that is the background colour; the far plane is 1000 m.
  - The plan's street runs along the x axis, with the lot at +y (`services/twin_place.py:214`).
- **Neighbourhood pipeline** (`services/house_map.py`, legacy 3D House):
  - Mapbox Streets v8 vector tiles (roads, building footprints, house numbers) plus Terrain v2 land cover: up to 17 requests, counted by `maps.check_usage_limits_and_spikes`.
  - `compile_layout` fits neighbours to street-facing boxes, estimates missing houses from house numbers, packs yards and merges land cover.
  - Cached in `house_map.json` beside the database for 12 h.
  - Output is in dollhouse units (nearest street at 28.5 units), not feet. Endpoint `/api/house/neighborhood`.
  - Its renderer (`static/house_neighborhood.js`) cost about 1.2M triangles and 547 draw calls on high.
  - Known red tests: `test_house_map_live` and an untiered GET in `test_auth`.

## The design, by slice

Five slices, in this order. Each lands on its own with a version bump and makes the twin better without the later ones.

### Slice 1: sky, sun, moon, stars, and the stage

- **A physically based sky** that moves smoothly with sun altitude through night, astronomical, nautical and civil twilight, golden hour and day, replacing the four colour bands. *(Claude's call: an atmospheric-scattering sky in the family of Preetham/Hosek or a precomputed Bruneton-style model; the builder picks one that holds up at dusk.)*
- **The sun disc:** a bright disc with limb darkening and a glow that feeds the existing bloom.
  - It is drawn larger than its true half degree, and larger again near the horizon, the way the eye sees it (owner).
  - Near the horizon it turns orange-red, dims through the air mass, and is slightly flattened by refraction.
  - It shows through thin cloud once slice 2 exists.
- **The moon disc:**
  - Surface detail from a public-domain lunar map *(Claude's call: NASA's CGI Moon Kit)*.
  - Lit by the real sun direction, so the phase and the terminator are right; earthshine on the dark side, faintly.
  - The same perceived-size rule as the sun, plus its real month-to-month size change (perigee to apogee) and the low-sky colour.
- **Stars:**
  - They fade in through twilight, from a real star catalogue at the real sidereal time and latitude *(Claude's call: the brightest few thousand stars of a public catalogue such as Yale BSC)*.
  - They twinkle slightly near the horizon and are hidden by cloud and by the moon's glow.
- **Reflections and environment light use the sky the viewer sees:**
  - The fixed HDRI is replaced as the scene environment.
  - Probes recapture when the sky changes enough, within the existing quiet-time capture rules.
  - Water reflects tonight's sky.
- **The stage:**
  - The ground and everything on it fade into the sky and haze at a radius around the house, so the scene reads as a round stage, not a lawn plane with an edge.
  - Radius setting: default *(Claude's call)* 120 ft beyond the farthest lot corner, range 30 to 1000 ft.
  - The fade is an atmospheric haze toward the horizon colour, not a hard cut.
  - This haze is the same one slices 3 and 5 use.
- **North agrees everywhere:** the sun, the moon, the stars and (later) the streets use one frame. Resolving `modelDirection`'s tie to the Front camera ray is part of this slice.
- **North comes from the map** (owner: "If you can determine the house's north direction from the map, do it"; the stored dial value was recently moved by hand to try lighting, so it is not trusted):
  - The house's real orientation is read from map data at the household's location: the building footprint that contains the geocode, or failing that the bearing of the nearest street. The plan's street edge is matched to it, giving a true bearing for the plan's axes.
  - This becomes the twin's north. The facing dial in the editor stays as an override (nothing a person can do is removed) and shows the map's value as its default, with a way back to it.
  - The map lookup is a one-time fetch with the slice 5 data (Mapbox, kept); slice 1 needs only the orientation, so it fetches that part early. With no map key or no match, the dial value is used as today.
- **Previews:** Now / Day / Night stay. A time-of-day scrub *(Claude's call)* lets anyone watch a sunset, and returns to Now after the existing 120 s.
- **Interim overcast** *(Claude's call, from the builder check)*: until slice 2 lands, an overcast or rainy day must not show a clear sky with hard sun. Slice 1 greys the sky, softens the sun and lifts sky light from `cloud_coverage` or the condition, so each slice keeps agreeing with the real weather.

### Slice 2: clouds

- **Volumetric clouds:**
  - Ray-marched in a layer above the house, lit by the sun (and dimly by the moon), with powder and silver-lining effects.
  - Darker undersides, soft thin edges.
  - Several cloud types, from fair-weather cumulus to overcast stratus, chosen by the weather.
- **Amount** follows `cloud_coverage` (0 to 100 percent). When the attribute is missing, the condition maps to an amount: `sunny` and `clear-night` clear, `partlycloudy` about 40 percent, `cloudy` about 85 percent, rain, snow and storm conditions overcast.
- **Drift:** with `wind_speed` and `wind_bearing`, at a gentle multiple of the real wind so motion reads on a panel.
- **Cloud shadows:**
  - The sun's light is modulated by the clouds between it and each surface: a top-down cloud shadow texture projected along the sun direction, applied to the sun's contribution in every lit material.
  - That covers standard materials, the lightmap and viewing patches, and the custom water, effect and grass shaders.
  - Overcast skies soften direct sun and lift the sky light (the legacy House used sun ×0.58 cloudy and ×0.32 heavy as a rough guide).
- **Lightning:** under `lightning` and `lightning-rainy`, irregular flashes light the clouds from inside and briefly light the scene. Never under other conditions.

### Slice 3: weather

- **Conditions** come from the chosen weather entity's `condition`, using Home Assistant's standard set:
  - `clear-night`, `cloudy`, `exceptional`, `fog`, `hail`, `lightning`, `lightning-rainy`
  - `partlycloudy`, `pouring`, `rainy`, `snowy`, `snowy-rainy`, `sunny`, `windy`, `windy-variant`
  - Intensity comes from the condition (`rainy` vs `pouring`) and from a precipitation rate when the entity offers one.
- **Rain:**
  - Falling streaks around the camera, angled by the wind.
  - Splashes on hard surfaces; ripples on the pool and on puddles.
  - Wet surfaces: darker and glossier, with puddles forming on flat ground.
- **Snow:**
  - Falling flakes drifting with the wind.
  - Snow cover on upward-facing surfaces (ground, deck, roof, the tops of trees and shrubs), varying in depth.
  - Water stays open.
- **Fog:** `fog`, or a low `visibility` value, pulls the haze from slice 1 in toward the house.
- **Wind:** one global wind (speed and bearing) drives the grass (replacing its hard-coded gust), tree and shrub sway, falling precipitation and cloud drift.
- **Weather on surfaces** is one weather layer added to every material (wetness, puddles, ripples, snow cover), not per-material edits. It must work with the lightmap and viewing patches and the custom shaders, as cloud shadows do.
- **Lingering ground state** *(owner approved 2026-11-18: "Lingering snow and wetness is fine"; grass dormancy in slice 4 uses the same weather record)*:
  - The add-on keeps a small running model from the weather entity it already sees. Snow builds while it snows and melts above freezing, faster in sun; wet surfaces dry over an hour or two after rain, slower when cold or overcast.
  - It is stored outside the `house_twin` row. The twin shows that state.
  - "Plausible, not exact." If the owner rules it out, surfaces follow the current condition only.

### Slice 4: seasons

- **Trees and shrubs:**
  - Follow the real date at the household's latitude: spring green-up, summer, autumn colour, leaf drop and bare winter branches for deciduous kinds.
  - Evergreens stay green.
  - Snow sits on branches during snow cover.
  - Imported tree models that cannot change keep their look.
- **Lawn dormancy (owner):**
  - A lawn setting chooses warm-season grass (Bermuda, zoysia, St. Augustine) or cool-season grass (fescue, bluegrass, rye).
  - Dormancy follows a running 7 to 10 day average of air temperature from the weather entity, as a stand-in for soil temperature. The add-on keeps that average.
  - Warm-season: goes tan when the average falls below about 55°F after the first frost; greens up as it rises past about 65°F.
  - Cool-season: stays green most of the year; browns in a long hot dry spell (sustained 85 to 90°F and up with little rain); dulls in deep cold.
  - Changes take about two weeks, patchily, the way a real lawn does.
  - With no weather history, a growing-season calendar for the latitude stands in.
  - The paver joint grass follows the lawn.
- **Nature's small touches** (owner kept these):
  - autumn leaves blowing with the real wind
  - fireflies over the lawn on warm summer nights
  - low-sun light shafts at sunrise and sunset

### Slice 5: the neighbourhood

- **What it shows:**
  - The real surroundings out to a radius setting *(Claude's call: default 450 ft, a couple of houses deep)*, then haze: streets, neighbouring houses as simple shells with roofs and a little landscaping, and land cover.
  - Woods become stands of real trees; the owner's view out back is woods.
- **Data:**
  - Mapbox through the existing `services/house_map.py` fetch and compile.
  - Fetched once and built into the twin's own neighbourhood, which is kept. Fetched again only when the home location changes or a person asks for a refresh; no rebuild on every view (owner: "We aren't going to constantly pull the map and rebuild everything").
  - Licensing of the kept copy is not a concern for now: the add-on runs only for the owner (owner, 2026-11-18). OpenStreetMap is an acceptable source too ("I don't really care either way"); the builder may use it where Mapbox lacks something (for example woods).
  - **Real positions** *(Claude's call, from the builder check)*: the legacy `compile_layout` is illustrative (it scales the nearest street to a fixed distance, invents a home parcel and packs yards). The twin needs a metric compile instead: map footprints, roads and land cover in true feet, aligned to the drawn lot (the geocode can be tens of feet off), with houses estimated from house numbers only where the map has no footprint, and drawn as such. The fetch and cache are reused; the compile is new.
- **Rendering:** a new, light renderer in the twin. The legacy one is not reused.
  - Distant trees and houses use cheap stand-ins.
  - The extra cost stays a fraction of the legacy 1.2M triangles and 547 draw calls.
- **Haze and edge:** the stage radius from slice 1 grows to the neighbourhood radius, and the haze hides the edge.
- **Birds:** a few birds, which leave when the rain starts.
- **Shared frame:** streets, sun and shadows agree on north (the frame from slice 1).

## Weather data contract

Every Home Assistant install differs beyond the default integration (owner). The design builds on the standard weather entity and the integration every install gets at onboarding, and each feature degrades or turns off when its data is missing; nothing is required beyond a weather entity *(Claude's call between the owner's two options: support the most common source with fallbacks, rather than require one integration)*.

- **Baseline: Met.no** ("Forecast Home", created at HA onboarding). Its entity carries `condition`, `temperature`, `humidity`, `cloud_coverage`, `wind_speed`, `wind_bearing`, `dew_point`, `pressure`, and an hourly forecast through `weather.get_forecasts`. Every feature works on it.
- **Per quantity, with fallbacks:**
  - Cloud amount: `cloud_coverage`, else the condition table in slice 2.
  - Precipitation and its intensity: the condition (`rainy`, `pouring`, `snowy`, `snowy-rainy`, `hail`, `lightning-rainy`), refined by the current hour's forecast `precipitation` when offered.
  - Wind: `wind_speed` and `wind_bearing`, else calm with a gentle default breeze for the grass.
  - Fog: `fog`, or `visibility` when offered, else no fog.
  - Temperature (dormancy, melting, drying): `temperature`.
- **Optional local sensors** override single quantities when the household has them: a rain sensor (on/off or a rate), wind speed and direction, temperature. Settings beside `weather_entity`, each optional. A local rain sensor fixes the case where an integration reports the forecast hour as "now" and shows rain while it is dry.
- **No weather entity:** clear sky, no precipitation, calm, the season from the date and latitude, and the lawn on its growing-season calendar.
- The viewer says which source drives the weather, and what is missing, in its settings drawer (no silent guessing).

## Where the live state applies *(Claude's call, from the builder check)*

- **Viewer and wall panel, Now:** the real weather, season and ground state.
- **Viewer Day / Night / time scrub:** today's season and ground state at the chosen time, with the weather as it is now.
- **Editor:** a neutral look by default (clear sky, summer leaves, green lawn, dry ground), so materials and plants are judged as themselves; an editor lighting option shows the live state instead.
- **Weather and season previews:** apply wherever they are chosen and return to live after 120 s.

## Settings

*(Claude's call on placement)*

- **Weather entity:** the existing `weather_entity` setting.
- **Stage radius and neighbourhood radius:** in the house viewer's settings drawer.
- **Lawn grass type:** on the lawn / lot card in the editor, where the lawn material lives.
- **Weather and season previews:** viewer controls, beside Day and Night. They are not settings.

## Testing

- Entry points swallow exceptions, so each slice needs tests that run the real path: node runs of the modules, and Chromium runs of the real viewer and editor with screenshots checked by Claude.
- Sky and ephemeris: positions and phase against published values for known dates; north agreement between sun, moon, stars and streets.
- Weather mapping: every Home Assistant condition and missing attribute maps to a defined look; no weather entity gives a clear sky.
- Cloud shadows and the weather layer: a material census proving every lit material (standard, lightmap-patched, viewing clone, custom shaders) receives them.
- Shader safety: the NaN and negative-`pow` guards hold under MSAA on high (the class of bug fixed in v2.499.911-.912).
- Device verification on the owner's desktop and panel for each slice.

## Left to the builder

- The sky model, the cloud ray-march technique and its tier settings.
- How cloud shadows and the weather layer are injected into all materials (one shader-chunk patch is the expected shape).
- Precipitation particle technique and counts.
- Exact sun and moon on-screen sizes, within "the way the eye sees them" and judged against the owner's Twinmotion shot.
- The tree season technique for the existing preset trees.
- The neighbourhood stand-ins and their level-of-detail distances.
- Tier behaviour, within the owner's stance: tiers may change cost, and low keeps its still pose; but no tier silently loses a feature the owner asked for without saying so in the slice's plan.

## Planning

One plan per slice, written when the slice is reached. Slice 1 first.
