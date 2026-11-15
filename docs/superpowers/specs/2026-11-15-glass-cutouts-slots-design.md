# Glass, cutouts and material slots on every surface

Status: direction given by the user on 2026-11-15 ("Just get glass and cutouts working with material slots for everything - you should be able to override the pane on an individual thing but a house default you can set to change all of them would be nice too. We can worry about shadows later."). Points marked **(call)** were decided by Claude and are open to correction.

## Intent

The house in the twin should read as the family's own house. Today a large part of it cannot be changed: trim, window frames, doors, panes, columns, stairs, counters, the lawn and more are hard-coded, and glass is one fixed pale-blue material that no Library material can replace. The user wants two things:

1. **Glass and cutouts are kinds of Library material.** Any place that accepts a material accepts a glass or a cutout material.
2. **Every surface the generator draws has a material slot.** Each kind of surface has a house-wide default, and an individual thing (this window's pane, this door) can override it.

## Goals

- A Library material can be opaque, a cutout (alpha tested) or blended (glass), with an opacity value and an optional opacity map.
- Every existing slot and surface override accepts such a material with no per-surface allow-list.
- Every surface kind listed under "Slots" has a house default the editor can set, and the listed per-item overrides.
- Window panes, shower glass, porch screens and pool water become ordinary slots whose default is the look they have today.
- The two slots that are stored but never drawn (room ceiling, per-roof-section material) start drawing.
- A house in which nobody has made any of the new choices looks the same as before and keeps its stored bake.

## Non-goals

- Shadows from glass, and baked shadows from cutouts. Deferred by the user. Live cutout shadows keep working where they already work (the shadow pass honours `alphaMap` and `alphaTest`, as it does for the lattice today); nothing new is built for them.
- Refraction. `transmission` stays banned (tests `scenario_no_material_uses_transmission` in `tests/test_twin_view_live.py`, `tests/test_twin_editor_scene_live.py`, `tests/test_twin_import_chunks_js.py`).
- Order-independent transparency. Overlapping blended surfaces may sort wrongly at some angles; accepted **(call)**.
- New geometry for things that do not exist: railings, panelled garage doors. A garage door stays the glazed opening it is today; its pane slot can take an opaque material **(call)**.
- Slots on imported models, plants, furniture models, solar panels, the parking glyph, light fixtures, and the small fire pit props (pan, logs, ash, burner, vents, chips, gravel ring) **(call)**.

## Anti-goals

- Removing anything a person can do today. Existing colour pickers (for example `fixtures[].body` and `top` colours, the garage `door_colour`) keep working and are the fallback when no slot is set.
- Changing the bake result, the bake key or texture coordinates of a house that has made none of the new choices.
- A new long-lived stream per tab, a browser dialog, a new package in `requirements.txt`, a change to the `house_design` tool schema (it is at its cap).

## Part 1: alpha in Library materials

### Record

In `services/twin_materials.py`:

- New param `alpha_mode`: `opaque` (default), `cutout` or `blend`.
- New param `opacity`: 0 to 1, default 1. Used only in `blend` mode.
- New param `alpha_cutoff`: 0 to 1, default 0.5. Used only in `cutout` mode.
- New map slot `opacity`: greyscale, white is solid.
- Existing records without these fields read as opaque.

### Ingest

- A base colour image that carries an alpha channel no longer loses it silently. If the material has no opacity map yet, the alpha channel is split off and stored as the opacity map; the base colour is still stored as it is today. This lets a PNG saved from Photoshop work in one upload **(call)**.
- glTF material import (`static/twin/library_page/gltf_import.js`) reads `alphaMode` (`MASK` becomes `cutout`, `BLEND` becomes `blend`), `alphaCutoff`, and the alpha of `baseColorFactor` as `opacity`.

### Rendering

In `static/twin/twin_library.js` (`applyMaterialParams`, `kitMaterial`, `copyMaterialParams`):

- `opaque`: as today.
- `cutout`: opacity map as `alphaMap`, `alphaTest` = `alpha_cutoff`, double sided, not blended. Same treatment as the built-in lattice.
- `blend`: `transparent`, `opacity` from the param, opacity map as `alphaMap` when present, `depthWrite` off, no shadow cast. Same treatment as the built-in glass today.
- The low tier loads only the base colour map today. It must also load the opacity map of a non-opaque material; a cutout that draws solid on the wall panel is a defect.
- The built-in lattice keeps its generated texture and its look, and goes through the same code path as a cutout.

### Live refresh

`refreshMaterials` in `static/twin/twin_view.js` already forces one full rebuild when a material's lattice cutout flips. The same applies when a material's `alpha_mode` changes, because the set of meshes that receive and occlude baked light changes. Changes to `opacity` or `alpha_cutoff` within a mode refresh in place.

### Built-in glass, screen and water

The three hard-coded materials (`glass` and `screen` in `static/twin/twin_generator.js`, `water` in `static/twin/twin_yard.js`) become built-in materials that a slot can name, with exactly their present values, so that "clear" on a pane slot returns the present look.

### Bake

Rules that exist and stay (shadows are out of scope):

- `atlasMesh` in `static/twin/bake/atlas.js` leaves out transparent materials, materials with `alphaTest`, and materials named `glass` or `fixture`, as receivers and as occluders. A glass or cutout wall therefore lets baked light through and takes no baked light itself; it is lit live.
- `patchWindows` in `static/twin/bake/runtime.js` finds panes by `material.name === 'glass'` to give them the night glow. A household material placed in a pane slot takes the receiving role as its name (`materialSlot` in `twin_library.js` already does this), so the glow survives. A pane whose material is opaque gets no glow **(call)**.

New requirement: when a surface changes between opaque and non-opaque, the stored bake must be reported stale and must never be applied to a mesh set it was not made for. A test must prove it by running the code.

### Library page

The material editor on `/house/library` gains: the mode choice, the opacity slider (blend), the cutoff slider (cutout), and the opacity map slot. The preview shows the result. Follow `chauffeur/docs/ui_design_guide.md`.

## Part 2: slots on every surface

### Model

Two levels, matching what the surface override system (`set_material`, `_material` in `services/twin_model_ops.py`) already does for siding, floors and interior walls:

1. **House default** per surface kind: `building.materials[role]` for parts of a building, the existing `plan.materials` or the feature's own `materials` for the yard.
2. **Per-item override** on the thing itself.

Resolution: item override, then house default, then the parent kind's house default where the table names one, then what the surface uses today. A slot value is `{id, color?}` as everywhere else.

`material.name` on a surface stays what it is today whichever slot supplied the material, because the bake classifies surfaces by that name.

### Surface kinds

| Kind (role) | Falls back to | Per-item override stored on |
|---|---|---|
| `trim` (bands, corner boards) | today's kit trim | none |
| `fascia` (fascia and rake) | `trim` | none |
| `casing` (window and door casing) | `trim` | opening |
| `window_frame` (frames and mullions) | today's kit | opening |
| `pane` (window, slider, bifold and garage door glazing, half-glass door lights) | built-in glass | opening |
| `door` (door leaf) | today's kit door | opening |
| `column` (porch columns) | `trim` | porch room |
| `screen` (porch screens) | built-in screen | porch room |
| `soffit` (roof underside and porch ceiling) | today's `porch_ceiling` | none |
| `base` (raised base band) | today's kit base | none |
| `stair_tread` | `floor` | stair |
| `stair_rail` (stringers, posts, handrail) | today's `porch_ceiling` | stair |
| `ceiling` (room ceilings) | today's look | room (`rooms[].ceiling_material`, already stored) |
| `roof` | today's kit roof | roof section (`roofs[].material`, already stored) |
| `cabinet` (counter and vanity bodies) | the fixture's `body` colour | fixture |
| `counter` (counter and vanity tops) | the fixture's `top` colour or kit counter | fixture |
| `shower_tile`, `shower_glass` | today's ceramic, built-in glass | fixture |
| `lawn` (lawn and base ground) | today's lawn | none |
| `water` (pool and spa water) | built-in water | pool, spa feature |

Notes:

- Room ceilings: if no per-room ceiling surface exists to carry the material, add one under the slab or roof underside, hidden wherever that underside is hidden today (cutaway and floor views must not change).
- The existing slots (siding, interior walls, floors, foundation, porch foundation, fences, retaining walls, hardscape, curb, beds, lawn edge, pool coping and interior, spa, fire pit body and top) stay as they are.

### One table

Today each slot is wired by hand in the editor, the server check, the generator and the reuse keys. The new kinds are described once per side (one table on the server, one in the browser, kept in step by a test) and everything else reads the table: validation, the editor panel, the generator's lookup, the reuse and cache keys (`buildingKeyParts` in the generator, `yardMaterialInputs` in the yard), and the "where used" labels that stop a material in use from being deleted (`services/twin_materials.py`).

### Editor (the hand path)

- **House materials panel:** one place in the house editor listing every kind with the shared slot control (`static/twin/editor/material_slot.js`): pick, clear, tint. It includes the kinds that already have a building-wide value (siding, interior wall, floor, roof).
- **Selection card:** selecting an opening, a porch, a stair, a fixture, a room, a roof section, the pool or a spa shows that thing's overrides with pick and clear, in the same rows the card already uses for walls and rooms. Clear returns to the house default.
- Dragging a Library material onto a pane, frame, door, column and the other new surfaces assigns it, as dragging onto a wall does today. Dropping on an opening no longer redirects to the host wall when the pointer is on the opening's own surface.
- Editing a material stays on the Library page; the editor only picks.
- No browser dialogs. Follow the UI design guide.

### Agent

Every agent capability needs a hand path, and the reverse is not required. `set_material` with `{building, role}` already accepts any role text, so Argyle can set house defaults without a schema change. Per-item overrides by the agent are not part of this work.

## Constraints

- A house with none of the new values set: same scene, same material names, same texture coordinates, same bake key and atlas version. A test compares against the current main commit by running both.
- Low tier draw budget: slots must not add draw calls to a house that has not used them. Meshes that share a material must still merge.
- Every server edit path validates slot values with the existing `normalize_material_slot` rules; invalid values are reset on load as yard slots are today.
- Deleting a material the house uses is refused, and the refusal names the new places.
- Tests run the code (node runs of the browser modules, TestClient requests, Chromium scenarios), not source greps. `HA_BASE_URL` unset. Never the whole suite.
- New auth rules for any new route in `services/auth.py`.
- Tailwind is precompiled: rebuild after template class changes.
- Works with no Home Assistant present.

## Slices

Each lands on main with its own version and capabilities entry.

- **A. Alpha in materials:** record, ingest, glTF import, rendering on all tiers, live refresh, Library page controls, built-in glass, screen and water as pickable materials, bake staleness on an opaque/non-opaque flip. Existing slots accept the result.
- **B. House defaults:** the table, server validation, generator and yard lookups, reuse keys, where-used labels, the House materials panel, the dead ceiling and roof-section slots drawing.
- **C. Per-item overrides:** openings, porches, stairs, fixtures, pool and spa water; selection card rows; drag and drop onto the new surfaces.

## Left to the builder

File layout of the tables, the exact plan paths for per-item overrides (follow the nearest existing pattern: `materials: {…}` on the item), control layout within the design guide, and how the per-room ceiling surface is built.

## Current state, for orientation (verify before relying on it)

- Surface overrides: `static/twin/editor/library.js` (`materialLines`, `scopeChoices`, `surfaceOperation`, `surfaceAt`), `static/twin/editor/cards.js`, server `_material` in `services/twin_model_ops.py`; generator `mat(role, level, override)` and `materialKitWithRefs` in `static/twin/twin_generator.js`.
- Feature slots: widget `static/twin/editor/material_slot.js`; resolver `materialSlot()` and `kitMaterial()` in `static/twin/twin_library.js`; yard registry `SLOTS` in `services/twin_site_shapes.py` and `siteMaterialSlots()` in `static/twin/editor/site_shape_shelf.js`; porch `services/twin_porches.py`; foundation and retaining wall `services/twin_terrain.py`.
- Material record: `services/twin_materials.py` (`SLOTS`, `DEFAULT_PARAMS`, `_params`, `page_manifest`); ingest converts base colour to RGB JPEG.
- Hard-coded today: `glass` and `screen` near the top of the generator's material set-up, `water` in the yard, trim and frame via `mat('trim')` and `mat('window_frame')`, stairs in `static/twin/twin_stairs.js`, fixtures near the end of the generator.
- `rooms[].ceiling_material` and `roofs[].material` are written by the editor and server and read by nothing.
- Lattice: `latticeTexture()` and the `pattern: 'lattice'` branches in `twin_library.js`.
