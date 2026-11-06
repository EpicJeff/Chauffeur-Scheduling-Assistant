# The House as a digital twin: design

Status: design, awaiting approval (2026-11-06). Nothing here is built. A throwaway spike exists in `.superpowers/spike-poolhouse/` (git-ignored) and is described in section 12 as evidence, not as code to keep.

## 1. Intent and why

The House was first imagined as a digital twin of the family's actual home: a 3D model you look at to see what is happening in each room, and touch to control it through Home Assistant. Over time it became a window into Chauffeur instead (a generic modern-farmhouse dollhouse holding cars, the bus, the chores dock, packing and the Study). In the user's words, being a window into Chauffeur "doesn't add anything to your experience". Being the way into Home Assistant does.

The prompt was a Reddit post (Simon Karlsson, 2026-11) showing a three.js twin built from architect plans: live energy ribbons, the roof fading as you zoom, one floor at a time cut like a plan, rooms glowing in their lights' real colour, tap a room for its HA area controls, temperature colouring, voice that lights up the rooms it acted on, and an idle mode with a large clock, weather and a glance bar.

The new House is the **house management side of family management: every physical thing the family can monitor and control, reached through HA, drawn on a faithful model of their own home and lot.**

Success: standing at the wall panel, the family does its everyday house jobs faster and more pleasantly on the twin than on HA dashboards, and the model looks like their house to anyone who knows it.

## 2. Where it lives and who uses it

- **Primary surface: the wall panels** (`?panel=true&kiosk=true`, the existing panel shell). Phones are secondary and not designed for in this document.
- **Everyday jobs the user does at the panel today** (the bar the twin must clear): monitor energy (grid, solar, car charging, Powerwall), lock and unlock doors, check and set thermostats, turn devices on and off (TV, lights), view cameras. Also pool equipment, robot vacuums, robot mower and sprinklers.

## 3. Goals, non-goals, anti-goals

**Goals**
- A twin of the family's real house and lot, accurate enough that it reads as *their* house.
- Generated from what an ordinary household can provide (plan drawings, a floor plan image, photos; later a phone LiDAR scan), **reproducibly through the model APIs Chauffeur already uses (Gemini, Claude, OpenAI)**. No Blender, no hand modelling, no engineering plans required.
- Every HA-controllable thing reachable spatially, at the right level of detail for the zoom.
- Visualization modes are pluggable: adding one does not change core logic.
- Runs smoothly on the wall panel hardware.

**Non-goals**
- Not a window into Chauffeur. Chores, routines, programs, packing, the Study and the rest stay in their PWA homes and in the legacy House; the twin does not host them. The single exception is the compact hero card in idle mode (section 6.4).
- Not a general CAD tool. The editor edits the plan file, it is not a modeller.
- Not making it smooth for strangers' houses in the first phases. The pipeline must be general; polish for other households comes later.
- Not reproducing a specific existing product's look. The Reddit video is inspiration for behaviour; the visual target is set by the user's own Twinmotion renders (section 9.6).

**Anti-goals (would make this a failure even if it works)**
- Markers piled on markers until nothing reads at panel distance.
- A twin that looks like a toy (cartoon trees, flat untextured ground) next to a faithful building.
- Any asset or texture the model *invents*: the model chooses from vetted libraries and writes plan data, it never paints or sculpts.
- A panel that stutters. The v2.499.163 lesson stands: no feature that adds a scene pre-pass (for example `transmission` on glass or water) without measuring it on the panel.

## 4. Decisions already made (by the user, in conversation 2026-11-06)

1. **The twin replaces the House wholesale.** The current 3D House is kept as a legacy feature behind a switch, not deleted (this is the approval the never-drop rule requires). The photographic House stays as it is, also selectable.
2. **Cars and the bus belong** because they are physical and already come from HA.
3. **Level of detail follows zoom** (section 6.1). Not "everything at once".
4. **Every device has two aspects:** an always-present overlay marker with status, and a visualization drawn only in its mode.
5. **Glance bar:** anchored along the bottom on every view; in idle mode it moves up into the time card. One bar, never shown twice.
6. **Idle mode** after a minute untouched: slow orbit, large time, date and weather, the glance bar, and Chauffeur's compact hero card.
7. **Glance bar contents are configurable** per panel.
8. **Wall panel control:** taps on the twin may control everything, locks, garage doors and alarms included. A later setting will put those behind a PIN. *Recorded as the designer's call, not the user's:* this covers taps on the twin only; Argyle's voice and chat rule on the panel (never trusted for locks, garage and alarms; `house-tool-arc` memory) is unchanged.
9. **Modes are plugins** (not needed for the POC, but the seams go in from the start).
10. **Quality bar:** the realtime render in the spike (version A) already clears the user's bar *for the building*. Baked lighting is "icing", wanted but not on the critical path. The weak point is the environment: plants, ground, materials and how the pieces blend.
11. **Reproducibility constraint:** whatever we build should be reproducible by Chauffeur through the model APIs. The user's own CAD models are not an input (no one else has them); they may be used only as an answer key to measure extraction accuracy.
12. **Yard for the POC:** believable, not yet the family's actual planting. How much "this is yours" versus "this looks good" is decided later.
13. **The baker may run on the user's desktop** (all bake options run there; hardware is not a deciding factor).

## 5. What the user sees

### 5.1 Levels of detail

| Level | What is drawn | Markers |
|---|---|---|
| **Exterior (whole site)** | Roof on, lot, yard, every building | Outdoor and whole-house things: solar, Powerwall, cars, exterior doors and locks, cameras, pool equipment, sprinklers, mower, outdoor lights, weather |
| **Floor** | Roof faded, one floor cut like a plan (walls full height, no ceilings), other floors hidden | Per room, a compact status like an HA area card: temperature, lights on, door/window open, vacuum present |
| **Room** | The room in focus, others dimmed | Every device in the room with full status and controls |

Attention states (unlocked, open, leaking, offline, running, alarm) push through at **every** level, even where that device's marker would otherwise be rolled up. Resting states are quiet; attention states are loud. "All locked" reads as the absence of red, not as six green badges.

Floors switch by a floor control and by zoom. Detached buildings (the pool house) are their own stack of floors on the same site.

### 5.2 Markers

A marker is drawn per *device* (not per entity: a device is many entities, per the `house-tool-arc` memory), at its placed position, showing its primary state. Tapping it does the obvious one-tap action (toggle a light, lock/unlock) or opens its detail. Markers with no placed position sit at an automatic spot inside their room.

### 5.3 Modes

A mode is a visualization of one aspect of the house, chosen from a mode strip. Modes for the first live phase: **Lights** (rooms lit with their lights' real brightness and colour), **Climate** (rooms coloured by temperature, setpoints on top), **Energy** (flow ribbons solar to Powerwall to house to car to grid), **Security** (locks, contacts, cameras with their view cones). Later: pool, vacuums, mower, sprinklers, and anything else via the plugin registry. A mode both draws its picture and brings its marker kinds forward while dimming the others.

Energy is the job the spatial picture helps least, so the energy numbers always live in the glance bar regardless of mode.

### 5.4 Room panel

Tapping a room opens a side panel with everything in that HA area: lights and dimmers, climate, covers, media, plugs. Controls go through the existing permission-checked HA paths (`services/house.py`). Reuse of HA's real cards through the hosted-card runtime (`static/ha_card_host.js`, hosted builtin cards arc) is the builder's call to evaluate against custom controls.

### 5.5 Voice

When Argyle acts on devices (from the panel's Ask or a satellite in the room), the rooms it acted on glow briefly. The agent stack is unchanged; this is a visual echo of tool results.

### 5.6 Idle mode, glance bar, hero card

- After one minute untouched: the camera orbits the exterior slowly; time, date and weather large enough to read across the room (the existing glance clock, `templates/components/glance_clock.html`); the glance bar under them; the compact hero card (`templates/components/hero_card.html`, `compact` variant, the same builder the screensaver uses, never a copy).
- Glance bar: a per-panel list of chosen entities with small icons and values (for example solar kW, house kW, battery %, each car's charge). Anchored along the bottom outside idle; part of the time card in idle.
- **Undecided idea, not part of this design yet:** because the idle orbit is a fixed path, it could be pre-rendered offline at much higher quality (day and night loops) and played back under live overlays. Trade-off: a pre-rendered loop cannot show live state (which lights are on, which cars are home, the real sun angle) and must be re-rendered when the scene changes.

## 6. Extensibility: two registries

- **Marker kinds.** Input: a device and its HA entities. Output: how it looks at rest, how it looks needing attention, what one tap does, what its detail shows. Matched by HA domain, device class or the inferred kind the `house` tool already computes (car, TV).
- **Modes.** Declares which marker kinds it brings forward, what it draws (room fills, glows, ribbons, zones, paths), and its legend. The core knows nothing about pools or mowers.

A new mode or marker kind is one module registered with the core. No core change.

## 7. The twin plan file

One plan document per household is the single source of truth. Everything visual is generated from it deterministically. The model writes and edits plan data; it never produces geometry or images directly.

Contents (the spike's `poolhouse.plan.json` is a working example; field names are illustrative, the builder owns the final schema):
- **units, axes, materials** (siding, roof, trim, base, window frame, door, floors, paving; each a reference into a vetted material library plus a colour).
- **buildings**, each with **levels** (elevation, ceiling height), **walls** (from, to, thickness, height, exterior flag), **openings** (wall, centre offset, width, sill, head, kind: window, door, slider, bifold, passage; panels, glazing), **gable openings**, **rooms** (level, polygon, name, `ha_area`), **stairs**, **roof** (main form with pitch, plate, overhang; extensions such as pitch-change sheds and awnings), **porch** (slab, columns), **fixtures** (counters, appliances, bath fixtures; kind plus rect), **lights** (positions, from an electrical plan where one exists).
- **site**: ground extent, hardscape (patios, paths, driveway), pool (polygon, depth, coping), fire pit, beds, fence, planting (each plant a species preset, seed and height), outdoor furniture (asset reference, position, rotation).
- **devices**: placement of HA devices (device id, building, level, position), optional; unplaced devices auto-place in their room.

## 8. Generating the twin

### 8.1 Sources, in order of introduction

1. **Plan drawings or a floor-plan image** (PDF or picture). A vision model drafts the plan file: walls, openings, rooms, roof forms, dimensions. Elevations, where present, give roof pitch and window heights. Electrical sheets, where present, give light and fan positions.
2. **Photos** of the outside (a few angles): the model picks materials and colours from the vetted library, confirms roof forms and fills what the drawings lack.
3. **The household's HA areas and floors**: room names come from them when drawings leave rooms unnamed (the user's main-house plans are dimensioned but unlabelled), and they give the room-to-area mapping.
4. **Later: a phone LiDAR scan** (Apple RoomPlan exports from third-party apps), imported into the same plan format.
5. **Later: a satellite or survey image** for the lot outline, the real trees and beds.

**Pool house photos supplied by the user (2026-11-06)** are the P0 finish source: a dusk photo from the pool and a night photo of the porch kitchen. They show: light grey board-and-batten (not white), white trim and white window sashes, stained mahogany French doors with divided lites, a dark bronze standing-seam roof and bar awning, stained cedar brackets, black lantern sconces, a white beadboard porch ceiling with recessed lights, a ceiling fan and an infrared heater, an outdoor kitchen (stainless grill and hood, ceramic cooker, stacked-stone base, dark stone counter), travertine pavers in a French pattern, stacked-stone raised pool walls and seat walls, a raised pool with spa, a black stacked-stone water wall, a fire pit with rocking chairs, navy loungers, artificial turf, a black aluminium fence, and a dense backdrop of tall pines and hardwoods. The spike's colour guesses were wrong on most of these. The photos also show the real site arrangement, which matters when the yard becomes "yours" (P5).

The user's documents: `Reference Plans Lot 58.pdf` (main house, Westpark Designs; first floor, second floor with bonus room, roof plan with hips and valleys; stamped "changes may have been made during construction"; rooms unlabelled; no elevations or pitch), `UPTON POOLHOUSE FINALS 6-2-22.pdf` (pool house, Design Tech, complete: elevations, both floor plans, electrical, roof framing, section, structural), `Pool Simplified Plot Plan.pdf` (lot, house, driveway, pool, pool house, fire pit positions).

### 8.2 The plan editor (2D)

A plan editor, not a modeller: drag walls, add or move doors and windows, set a building block's roof form and pitch, draw site pieces (beds, paths, zones), name rooms and assign each to an HA area, place devices. It shows the source drawing underneath for tracing. Accessible from the House's settings drawer. Model drafts land here for correction before they replace the live plan (the existing facade pipeline's draft-token preview, `?draft=`, is the precedent).

### 8.3 The generator

Deterministic plan to three.js scene: walls with real openings, board-and-batten or other siding as geometry or material, standing seams, trim and corner boards, brick or masonry base, window and door frames and glazing (no `transmission`), gables, roof planes with pitch changes and awnings, slabs, stairs, porch columns, fixtures, the site, and cut variants for floor views (gables clipped, upstairs walls stopping under the roof). Built for batching from the start (merged static geometry per material, instancing for repeated assets), following the existing house's lifecycle law for geometry and texture ownership.

### 8.4 Style kits, composition rules and the art director

This is where the POC's quality risk lives.
- **Style kits (data).** A kit (for example "modern farmhouse") lists siding, roof, trim, fence, paving, light fixtures, brackets, outdoor furniture and plant sets that are vetted to look right together and to fit the panel budget. The model picks a kit and composes with it; it never introduces assets outside the vetted library.
- **Composition rules (code).** Backdrop tree line, foundation bed depth, plants in odd-numbered groups and layered by height, edge treatments where lawn meets paving or beds, spacing and clearances, no bare expanses. The generator applies them; the plan can override.
- **Art director loop.** Render a fixed set of cameras, have a vision model critique them against the style guide and against a reference image when one exists (the user's Twinmotion render), and edit the plan file. Capped rounds, every round saved, the user picks or reverts. Precedent and caution: the v2.499.5 object-authoring experiment (`services/house_authoring.py`, `docs/house_authoring_experiment.md`) ran a design-then-critique loop and its own doc says it must prove quality before going further. The same bar applies.

### 8.5 Asset and material library

Vetted, licensed for redistribution (CC0 or MIT), stored with the add-on or fetched once and cached locally (the spike downloaded Poly Haven models locally after the API refused default clients). Plants come from a seeded procedural generator (EZ-Tree, MIT, three.js native, species presets), so a plant is plan data, not a file. Each asset carries its panel cost (triangles, textures) so the generator can budget.

## 8.6 Model calls and cost

- Keys exist for Claude, Gemini (paid) and OpenAI in the usual git-ignored `*_api_key.txt` files; the provider is chosen through the existing model provider selector.
- **No spend cap is fixed up front** (the user's ruling, 2026-11-06): a cap set before we know what reaching the bar costs could guarantee never reaching it. Instead every model call logs its tokens and cost, every art-director round reports its own cost and the running total, and the decision of "good enough versus what perfect costs" is made from that data.
- **Guards (designer's call):** the user does not want this to approach $100 in credits. The run pauses and reports at a running total of $10, $25 and $50, and does not continue past a checkpoint without the user's go-ahead. A per-run round cap (5 rounds, then report) exists to stop a critic that is never satisfied, not as a budget.

## 9. Rendering

### 9.1 Realtime base

PBR materials, a sky environment image, one sun with shadows, tone mapping. This is the spike's version A, which clears the user's bar for the building.

### 9.2 Quality tiers and panel budget

Four render tiers (the user's ruling, 2026-11-06), chosen per panel with an automatic suggestion from a quick device check:

| Tier | Target hardware | Shape |
|---|---|---|
| **Low** | Raspberry Pi 5 with Chromium (the current wall panel) | Tight draw-call and triangle budget, plants as impostors or cards, no or one cheap shadow, no post-processing. Baked lighting, when it lands, matters most here: it is the cheapest way to look good. |
| **Medium** | A decent NUC-class machine with integrated graphics | Realtime sun shadows, near plants as leaf cards, light finishing. |
| **High** | A discrete GPU | The spike's version A and better: full plants, soft shadows, ambient occlusion, full finishing. |
| **Max** | A strong discrete GPU | Progressive path tracing when the camera is still (the spike's version B, via three-gpu-pathtracer on WebGL; a WebGPU variant exists), with a denoiser, falling back to High while moving. Browsers expose no hardware ray-tracing API, so this is compute-based, not RTX cores. |

Every tier draws the same plan; tiers change only how it is drawn. The existing House's `?quality=` tiers are the precedent. The House already proved itself draw-call bound on panels (`house-render-headroom` memory; `tools/house_probe.py` measures). Known costs from the spike: trees dominate triangles; glass and water must not use `transmission` (the spike did, so its 60 fps desktop figure includes a forbidden double pass).

*P0 exit by tier (designer's call):* the look is judged at High, where it must match or beat the spike's version A; Low must hold a smooth frame rate on the Pi 5 while orbiting and still read as the same house. If Low cannot reach that, the pre-rendered idle loop (section 5.6) becomes the Low tier's resting face.

### 9.3 Night and room lighting

Room lights are real light sources at their fixture positions; in the Lights mode their brightness and colour follow HA. The realtime approach (light count, shadows, light leaking through walls) is the builder's call; the requirement is that a lit room reads as lit from outside through its windows and from above in floor view, and light does not visibly bleed through walls.

### 9.4 Baked lighting (later, icing)

Bake daylight soft light and per-room light layers into textures on the user's desktop; at runtime each room's layer is scaled by its lights' brightness and tinted by their colour. Offline sampling plus a denoiser (Open Image Denoise has a lightmap mode) avoids the noise seen in the live path-traced preview. Where the bake runs (an in-browser baker on the existing ray-tracing library, or headless Blender) is open; both run on the user's desktop.

### 9.5 Finishing

Colour grading, subtle bloom on bright areas, contact shadows or ambient occlusion where affordable.

### 9.6 Quality targets

- **Bar (must):** spike version A for the building, plus an environment that blends (no cartoon or toy elements).
- **Ceiling (aspire):** the user's Twinmotion renders (`E:\Pool House\Renders\Image2.png`, `Image3.png`), which took seconds per frame at raised quality. They also record the real finishes: white windows, bronze standing-seam roof, stained cedar brackets under the bar awning, lantern sconces, an outdoor kitchen on the porch, porcelain pavers, black aluminium fence, spa and water wall.

## 10. Home Assistant integration

- Areas, floors, devices and states come from the existing HA layer (`services/ha_api.py` area and device registries, `services/house.py` catalogue and permission-checked control).
- Live updates use whatever the current House uses for state; the builder decides polling versus the websocket subscription.
- **Graceful degradation:** with no HA, the twin still renders the house and site, idle mode works (time, weather if available, hero card), markers and modes are absent, and nothing errors.
- The `house` tool's existing rules stand for Argyle. Taps on the twin follow decision 8.
- *Designer's call:* the Assist-exposure gate in `services/house.py` (`house_control_unexposed`) governs what Argyle may control by voice and chat. The twin is a hand path, like HA's own dashboards, so it shows and controls every entity the add-on can reach, consistent with decision 8. The control route for twin taps is therefore separate from, or a flagged variant of, the agent's permission check.
- New routes need an auth tier in `services/auth.py`.

## 11. Legacy, settings and placement in the app

- The House experience becomes a choice among **Twin**, **Legacy 3D** and **Photographic**, replacing the boolean `house_hybrid_enabled`; existing installs keep what they have until switched. Settings go in `services/settings_registry.py` and the House's own settings drawer, never `config.html`.
- `panel_house_home` (Use The House as Home) continues to apply to whichever experience is selected.
- The twin plan, kits and assets are household data, backed up with the rest.

## 12. Evidence from the spike (2026-11-06, throwaway)

- **Plan from drawings works for the building.** I read the pool house drawings and wrote the plan file by hand, as the model would through the API; a deterministic generator produced a building the user recognised and judged good (11:12 gable, 3:12 pitch change over the porch, 2:12 bar awning, board-and-batten, standing seam, all openings at plan sill and head heights, both floors with kneewalls).
- **Realtime (A) cleared the bar for the building**; live path tracing (B) looked better but is noisy without a denoiser and needs roughly a minute of shader compile on Windows Chrome.
- **The environment was the weak point.** Blobs for trees read as toys. EZ-Tree plants, CC0 furniture, mulch beds, a fence and a softer lawn helped. Shrubs remain thin, lawn edges are hard, and pieces from different sources do not yet blend.
- **Cut floor views read well** as plans from above, and night lighting from real fixture positions reads well in floor view.

## 13. Phases

Each phase is shippable and device-verifiable. The phase boundaries are the designer's proposal.

- **P0, POC: generate the pool house and its yard to the bar, through the API.** Plan drafting from the pool house drawings by a vision model (not by hand), the generator, the first style kit, composition rules, the art director loop, the vetted asset library, and a measured run on the actual wall panel. Exit: the user says the pool house and yard look right, and the panel holds frame rate.
  - *P0 shape (designer's call):* P0 runs inside the add-on, behind a hidden preview route (for example `/house/twin`), so generation really goes through Chauffeur's model calls; it is not yet a selectable House experience (that arrives with P2). Model calls run server-side; the art director's renders happen in the family's own browser (the precedent from the facade pipeline), since the add-on host has no GPU.
  - *Corrections in P0 (designer's call):* hand edits to the drafted plan JSON are allowed, and every hand fix is logged as an extraction miss; that log is P0's accuracy measure. No automatic scoring against the user's CAD model in P0.
  - *Reference images (designer's call):* the art director critiques against the style guide and the household's own photos only. The Twinmotion renders are not an input to the pipeline (they are as private to this household as the CAD models); they stay the human-judged quality ceiling.
- **P1, the main house and the whole site.** Main house drafted from its drawings plus photos plus HA area names; the lot from the plot plan; the plan editor.
- **P2, the live layer.** Levels of detail, markers (resting and attention), the room panel, the Lights, Climate, Energy and Security modes, voice glow, and the marker and mode registries.
- **P3, idle mode.** Orbit, time and weather card, glance bar (configurable), compact hero card; the glance bar anchored outside idle.
- **P4, more modes as plugins.** Pool, vacuums, mower, sprinklers; outdoor zones in the editor.
- **P5, icing and reach.** Baked lighting, the PIN setting for locks on the panel, LiDAR import, "this is your yard" from satellite and photos, and smoothing the pipeline for other households.

## 14. Left to the builder

- Final plan schema, file layout and versioning.
- Whether the generator runs in the browser (as in the spike) or server-side producing a scene file; both must stay deterministic.
- Realtime lighting technique for room lights; LOD and impostor technique for plants; whether markers are DOM overlays or in-scene sprites.
- Whether the room panel uses hosted HA cards or custom controls.
- Polling versus websocket for live state.
- The art director's camera set, round cap and prompt design.
- How the vetted library is stored and shipped.

## 15. Risks

- **Panel performance** is unmeasured; the spike numbers come from a desktop GPU and include a forbidden transmission pass.
- **Blending** is a taste problem; the art director loop may not converge without a human in it. Mitigation: kits and rules carry most of the load; the loop only adjusts.
- **Extraction accuracy** on scanned, unlabelled, "may have changed" plans (the main house). Mitigation: the editor, HA names, photos; optionally score against the user's CAD model as an answer key.
- **Device placement effort** for a large house; mitigated by room-level auto-placement and optional refinement.
- **Library licensing:** only CC0 or MIT assets; record the source of each.
