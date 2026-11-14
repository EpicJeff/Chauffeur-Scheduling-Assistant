# Light fixtures: design

Date: 2026-11-13. Status: draft for the user's approval; revised after Codex adversarial review (ownership, quotas, persistence, invalidation, snapped hosts, emission states, units, legacy placement).

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

**Ownership and storage (revised).** Fixtures are owned by the **entity** that switches them, not by the device placement:
- They live in the model at `light_fixtures: {<entity_id>: [fixture, …]}`, at most 64 per entity.
- This matters because the existing placement ops (`place_device`, marker drag, yard-height edits) rebuild a device's placement record from device, host, offset and source. Fixtures stored there would be erased by an ordinary marker move.
- The marker remains the control icon. Moving it never moves the fixtures, and re-placing or regrouping a device (Show as, v2.499.841) never touches them.
- A device with several entities can have fixtures on each one.

**Legacy placement (revised).** An entity with no `light_fixtures` entry uses today's legacy resolver unchanged, in both live and bake: floor lamps raised by `LAMP_HEIGHT`, ceiling emitters lowered by 0.2 ft (`modes.js`, `reach.js`). Old houses render exactly as before.

**Fixture coordinates** are explicit lot feet plus a vertical reference (`ref: floor | ground | absolute`, with the host building and level for `floor`). The legacy offsets do not apply to them.

| shape | fields |
|---|---|
| `point` | `at` [x, y, z] (lot feet; z above the host floor or the ground) |
| `spot` | `at`, `aim` [x, y, z], `cone_deg` 10-160 (default 90), `softness` 0-1 (default 0.3) |
| `line` | `path` [[x, y, z], …] (2-64 points), or `edge` (a reference to a host edge, see the editor section), plus `facing`: `down` / `out` / `up` / `in` relative to the host edge (default `down`), and `width_in` 0.25-2 (default 0.5) |
| `area` | `at` (the centre), `size_ft` [w, h], `facing` (a unit normal, or the `down`/`out`/`up` presets), `rotation_deg` |

- Each fixture has a stable `id` (`fixture:<uuid>`), plus an optional `share`.

**Output and units (revised).**
- Each entity has a total output, `output_lm`, in lumens. The default 503 lm equals today's 40 cd point (40 × 4π).
- Each fixture gets a share of it: the authored `share`, otherwise proportional to length (line) or area (area), with points and spots counted as 1 each. So a 40 ft rope run is not 40 times brighter than a 1 ft one, and subdividing a run never changes the total.
- **Conversions:**
  - point: cd = lm / 4π;
  - spot: cd = lm / (2π(1 − cos(cone/2)));
  - area: luminance = lm / (π·A), the three.js `RectAreaLight` convention;
  - line: treated as an area of length × `width_in`, split into segments whose luminance stays constant.
- Live and bake use the same conversion, so they match.
- Brightness and colour from Home Assistant scale the entity's output.

**When an entity emits (revised).** This is a single shared resolver, `emission(entity_state, domain)`, used by both live and bake. Device control kinds and their controls are unchanged.
- `light`: `on`, with brightness and colour from the state.
- `switch`: `on` gives brightness 1 at 2700 K by default (adjustable per entity).
- `media_player` (TV screen): `on`, `playing` and `paused` emit; `idle`, `standby` and `off` do not. The default colour is 6500 K at 30% output.
- `unavailable`, `unknown` and stale data: no emission.
- **The fire pit derives its fixtures; you never place them.** A linear burner (about 4:1 or longer) gives a `line` along the burner centre, facing up. A wider burner gives an `area` the burner's size, facing up. A wood fire gives a `point` above the logs. The fire pit's entity drives them.
- **Validation is server-side.** It refuses a path outside the lot or with too few points.

**Snapped runs (revised).** A line always stores its resolved `path`. It may also store `snap: {host: {kind, id}, edge: {from: [x, y], to: [x, y]}, t0, t1}`:
- `host` is a stable host id: retaining-wall pad id plus edge, patio/path/deck id, step id, wall id or fence id.
- `edge` is the edge's endpoints, not an index, so a reshape that renumbers edges still finds it by nearest matching endpoints.
- When the host moves or reshapes, the path is re-resolved from the snap.
- If the host or edge is gone, after a deletion, a split or join that removes the edge, or a reversal the match cannot follow, the fixture keeps its last `path`, gets `detached: true` and shows a "Reattach" prompt in its row. It is never dropped.
- Undo of the host change restores the attachment.

Normalisation drops a malformed fixture with a note, and never drops the entity's other fixtures or the device.

## Rendering

### Real time
- point → `PointLight`;
- spot → `SpotLight` (angle and penumbra from `cone_deg`/`softness`), with a target at `aim`;
- line → a thin emissive strip mesh along the path (the visible rope), plus `RectAreaLight`s along the run facing `facing`. Each covers at most a few feet;
- area → `RectAreaLight` plus an emissive panel (the burner glow or the TV screen).
- `RectAreaLight` needs `RectAreaLightUniformsLib`, lights only Standard/Physical materials, and casts no shadows. That is acceptable, because the bake carries the shadows.
- **Quotas (revised).** Each tier has fixed slot counts per type. Every expanded light counts, so each `RectAreaLight` piece of a line counts against the area quota. My numbers, which the builder tunes against frame time:

| tier | point | spot | area | shadow casters |
|---|---|---|---|---|
| low | 4 | 1 | 2 | 0 |
| medium | 8 | 2 | 4 | 1 |
| high | 12 | 4 | 8 | 2 |
| max | 16 | 6 | 12 | 4 |

- A line run expands into at most 4 area pieces, merged evenly however long it is.
- **Selection:** candidates are per fixture, picked by distance to the view target and by output, as today per device.
- **Overflow:** fixtures over quota still show their emissive glow (strip, burner, screen), and the bake carries their light. Without a bake they are glow-only, and the energy-check style status says "Some lights are shown as glow only on this tier".
- **Programs:** the pool keeps every slot of every type visible inside Lights mode, with fixed shadow-caster counts, because three keys programs on light counts and shadow counts too. The fixed variants are warmed, as the existing point pool already is.

### Bake
- Each shape is an emitter in the lightmap baker: point (as today), spot (a cone mask with a soft edge), line (sampled along its length with facing cosine falloff) and area (sampled over its rectangle). All four cast shadows.
- **Grouping (revised).** All fixtures of one entity share one bake channel, because they always switch together.
  - Today the pipeline keys lights by device: `real_lights.js` maps candidates by device, and `atlas.js` `assignChannels` drops repeats of a device.
  - Fixtures become distinct emitters with fixture ids for reach and sampling. Their per-chart irradiance and receivers are aggregated **by entity** before the per-chart channel ranking, and the published channel is the entity's.
  - So a 12-light landscape circuit uses one channel per chart, and the 6-per-chart limit counts entities.
- **Invalidation (revised).** A canonical, resolved emitter signature per entity covers shape, positions, aim, cone, dimensions, facing, shares, output and the resolved snapped path. It is threaded through:
  - the live `layoutKey`, so a changed aim remounts the live layer;
  - the bake's light transport (`lightsOf`);
  - the reach cache input;
  - the bake fingerprint (`baker.js`), with a bake format version bump.
  Changing a spot's aim or cone marks the bake stale. A test covers each kind of edit.
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
- Tests (acceptance cases from the review are included):
  - per shape: data validation, real-time light creation and quota, bake emitter output (a node test of the bake pass against known geometry), and editor tools;
  - several fixtures on one entity: one channel per chart, every fixture lit;
  - a marker re-placement or drag keeps the fixtures;
  - an aim or cone edit invalidates live and bake;
  - deleting, reshaping or splitting a snapped host detaches the run and keeps it, and undo reattaches it;
  - a paused TV emits, an idle TV does not;
  - a legacy house is pixel-identical in live and bake (floor lamp and ceiling light);
  - subdividing a line keeps its total output;
  - Chromium night screenshots of the wall-cap grazing case and the linear burner;
  - a no-recompile check when lights switch.

## Decided by the user

- Rope lights are line lights under wall caps or along paver edges, and they light the surfaces next to them.
- One entity can drive many fixtures (pool lights, landscape lights on one switch), and each rope run is its own entity.
- Spotlights are aimed by dragging an aim point, with a cone setting. Camera frustums use the same setup.
- A TV screen is a light source.
- Bake every light, including yard and fire-pit lights (being built now).

## My calls (the user can override any of these)

- Fixtures are keyed by entity in the model. Marker moves never move them.
- Total output is in lumens, with a 503 lm default (today's 40 cd), and shares by length or area.
- Real-time quotas per tier as tabled; over quota means glow plus bake only.
- Snapped runs detach and keep their path rather than drop. Matching is by endpoints, not edge index.
- A paused TV emits; a switch defaults to 2700 K.
- Fire pit fixtures are derived from the burner and are not editable.
- Real time uses `RectAreaLight` without shadows for line and area lights.
- Entities share one bake channel.
- At most 64 fixtures per device.
- Default cone 90°, default line facing `down`.
