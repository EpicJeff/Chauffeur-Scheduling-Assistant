# Light fixtures: design

Date: 2026-11-13. Status: draft for the user's approval.

## Why

Every light in the house twin is a single point light at its device marker. The user's house has lights that are not points:
- security floodlights;
- rope lights under the stone wall caps and along paver edges, grazing the wall below;
- a long linear gas burner;
- underwater pool lights, all on one `light.pool`;
- landscape lights on a single switch;
- a TV screen.

The user, 2026-11-13: "If the light is from a security spotlight, it would make more sense to use a spotlight. A rectangular fire pit doesn't look right with a point light either." On rope lights: "under wall caps or along paver decking corners. They definitely light up surfaces." "Pool lights are another special case. There are multiple lights all driven by one light entity." "Maybe there is a way to handle that generically for things like landscape lights with a single switch."

The user's reference photo shows what success looks like:
- a bright grazing band below each wall cap, fading down the stacked stone with every course edge shadowed;
- a warm wash from the burner across the granite top, the sofa and the wall;
- a soft strip of light on the pavers under the sofa.

This builds on the bake-every-light work (yard and fire-pit lights baked onto yard surfaces), which is being built separately.

## Goals

1. A light entity drives one or more fixtures. Each fixture has its own position and shape, and all of them follow the entity's state, brightness and colour.
2. Four shapes: **point**, **spot** (aim and cone), **line** (a drawn or edge-snapped run with a facing direction) and **area** (a rectangle with a facing direction).
3. The bake renders every shape physically, with shadows.
4. Real time renders every shape as well as three.js can, and the bake carries the detail.
5. The fire pit's light comes from its burner shape automatically.
6. Camera frustums use the same aim tool as spotlights.

## Non-goals

- IES photometric profiles, volumetric beams or fog, and projected-texture cookies.
- Light animations and effects: colour loops, flicker modes.
- New Home Assistant entities or any change in Home Assistant.

## The model

A placed light device has `fixtures: [fixture]`, at most 64 per device. A device with no `fixtures` keeps today's behaviour exactly: one point fixture at its marker. Old houses render unchanged.

| shape | fields |
|---|---|
| `point` | `at` [x, y, z] (lot feet; z above the host floor or the ground) |
| `spot` | `at`, `aim` [x, y, z], `cone_deg` 10-160 (default 90), `softness` 0-1 (default 0.3) |
| `line` | `path` [[x, y, z], …] (2-64 points), or `edge` (a reference to a host edge, see the editor section), plus `facing`: `down` / `out` / `up` / `in` relative to the host edge (default `down`), and `width_in` 0.25-2 (default 0.5) |
| `area` | `at` (the centre), `size_ft` [w, h], `facing` (a unit normal, or the `down`/`out`/`up` presets), `rotation_deg` |

- Each fixture also has `id` and an optional `intensity` share (default: the entity's brightness split by fixture length or area, so one 40 ft rope run is not 40 times brighter than a 1 ft one).
- Every fixture of a device follows the device's entity: on/off, brightness and colour or temperature.
- **Which entities can have fixtures:** `light.*`, `switch.*` (a switch counts as a light once it has fixtures), and `media_player.*` for a TV screen. A TV screen is an `area` fixture that glows while the player is on or playing, with a cool white default colour.
- **The fire pit derives its fixtures; you never place them.** A linear burner (about 4:1 or longer) gives a `line` along the burner centre, facing up. A wider burner gives an `area` the burner's size, facing up. A wood fire gives a `point` above the logs. The fire pit's entity drives them.
- **Validation is server-side.** It refuses a path outside the lot or with too few points. Normalisation on load drops an invalid fixture with a note and never drops the device.

## Rendering

### Real time
- point → `PointLight`;
- spot → `SpotLight` (angle and penumbra from `cone_deg`/`softness`), with a target at `aim`;
- line → a thin emissive strip mesh along the path (the visible rope), plus `RectAreaLight`s along the run facing `facing`. Each covers at most a few feet;
- area → `RectAreaLight` plus an emissive panel (the burner glow or the TV screen).
- `RectAreaLight` needs `RectAreaLightUniformsLib`, lights only Standard/Physical materials, and casts no shadows. That is acceptable, because the bake carries the shadows.
- **Budget.** Fixtures count against the existing per-tier real-light pool (`real_lights.js`, `TIERS[tier].realLights`), picked by distance and intensity as today.
- **Programs.** The pool keeps a fixed number of each light type visible, so programs never recompile when lights switch. That is the existing rule for point lights; extend it per type and warm the programs.

### Bake
- Each shape is an emitter in the lightmap baker: point (as today), spot (a cone mask with a soft edge), line (sampled along its length with facing cosine falloff) and area (sampled over its rectangle). All four cast shadows.
- **Grouping.** All fixtures of one entity share one bake channel, because they always switch together. The 6-channels-per-chart limit therefore counts entities, not fixtures: a 12-light landscape circuit uses one channel.
- **Emissive surfaces:** the rope strip, the burner and the TV panel glow in the bake too, and stay unlit by other lights.

## The editor

- **Placing:** pick the entity, then choose a shape.
  - Point and spot use **multi-drop**: click to place fixture after fixture, for a row of path lights, then press Done.
  - Spot and camera use the **aim tool**: place the fixture, then drag the aim point on the ground or a wall. A cone or frustum preview shows the reach, with a cone or field-of-view slider. Cameras store `aim` and `fov_deg` (default 90). Their existing facing direction maps onto `aim` for old houses.
  - Line uses **draw or snap**: draw a polyline like a fence, or snap to a host edge, then pick `facing`. Snappable edges:
    - a retaining wall cap (under the cap, facing down the face);
    - a patio, path or deck edge (facing out across the surface);
    - a step nose;
    - a building wall top;
    - a fence top.
    A snapped run follows its edge when the edge moves.
  - Area uses a rectangle with a facing direction.
- **Editing:** a light device's card lists its fixtures, each with its fields, Duplicate and Delete. Selecting a fixture in the scene opens its row.
- No browser dialogs. Parents only. Every change is one undoable edit.

## Constraints

- Old houses unchanged: no `fixtures` means today's single point.
- Every Home Assistant touchpoint degrades gracefully. Without HA, fixtures draw unlit, as markers do today.
- **Argyle:** the `house_design` tool description is at its 6,000-character cap. Fixtures are hand-only until that description is compressed; the hand path rule is satisfied.
- Tests:
  - per shape: data validation, real-time light creation and budget, bake emitter output (a node test of the bake pass against known geometry), and editor tools;
  - Chromium night screenshots of the wall-cap grazing case and the linear burner;
  - a no-recompile check when lights switch.

## Decided by the user

- Rope lights are line lights under wall caps or along paver edges, and they light the surfaces next to them.
- One entity can drive many fixtures (pool lights, landscape lights on one switch), and each rope run is its own entity.
- Spotlights are aimed by dragging an aim point, with a cone setting. Camera frustums use the same setup.
- A TV screen is a light source.
- Bake every light, including yard and fire-pit lights (being built now).

## My calls (the user can override any of these)

- Per-fixture intensity defaults to splitting the entity's brightness by length or area.
- Fire pit fixtures are derived from the burner and are not editable.
- Real time uses `RectAreaLight` without shadows for line and area lights.
- Entities share one bake channel.
- At most 64 fixtures per device.
- Default cone 90°, default line facing `down`.
