# Paver paths: design

Approved proposal: 2026-11-18 ("paver proposal is fine. After slice 3a."). This document turns that proposal into a buildable design. Where it settles something the proposal left open, the line is marked *(Claude's call)*.

## Why

The yard's "Paver path" preset is the sidewalk strip with the paving material, 3 ft wide. It reads as a concrete walk with a different texture. The household wants walkways like their photo collage: stepping stones set in lawn, square pavers in a grid with grass in the joints, running bond and diagonal patterns, herringbone brick. Grass growing between the pavers is part of the look and is required.

## Goals

- A path can be laid as real pavers: separate flat blocks placed along its centre line, each one oriented to the path where it lies.
- Settings on the path card: layout, paver size, gap, rotation, edge mode and joint fill.
- Grass grows in the joints when the joint fill is grass.
- One draw call per paver path. The yard build stays fast on the owner's house.
- Paths drawn before this change look exactly as they do today until a person turns pavers on.

## Non-goals

- Irregular flagstones and open-cell grass-block pavers. They are different shapes; deferred.
- Per-paver editing (moving or deleting single pavers).
- Pavers on patios (closed hardscape polygons). Paths only.
- Any change to the `house_design` agent tool schema. This is a hand path.

## Anti-goals

- Pavers floating above the lawn or sinking under it.
- Grass blades coming up through a paver.
- A path that silently draws nothing because the paver is wider than the path.

## Data

A path (`site.hardscape[]` item with `kind: 'path'`) gains one optional field, `pavers`. Without it the path is the continuous surface it is today. *(Claude's call: one nested object rather than flat fields, so "Solid" vs "Pavers" is one switch and older readers ignore it whole.)*

```json
"pavers": {
  "layout": "grid",
  "length_in": 24, "width_in": 24,
  "gap_in": 3,
  "rotation": 0,
  "edge": "whole",
  "joint": "grass"
}
```

| Field | Values | Default | Meaning |
|---|---|---|---|
| `layout` | `stepping`, `grid`, `running_bond`, `diagonal`, `herringbone` | `grid` | See Layouts. |
| `length_in` | 2 to 60 | 24 | Paver length along the path, in inches. |
| `width_in` | 2 to 60 | 24 | Paver width across the path, in inches. |
| `gap_in` | 0 to 48 | 3 | Joint between neighbouring pavers, in inches. For stepping stones this is the space between stones. |
| `rotation` | -90 to 90 | 0 | Degrees added to the pattern's angle relative to the path. |
| `edge` | `whole`, `cut` | `whole` | `whole` keeps only pavers that lie fully inside the path; `cut` trims pavers at the path's sides and ends. |
| `joint` | `grass`, `gravel`, `sand`, `none` | `grass` | What fills the joints. |

All values are validated on the server (`services/twin_site_shapes.py`) on create and on update, with the same refusal style as the other path fields. `pavers: null` in an update turns pavers off.

The path card's material slots gain `joint` for a path with pavers, so a person can pick any library material for gravel or sand joints *(Claude's call)*. Server `SLOTS['hardscape']` grows to `('surface', 'edging', 'joint')`.

**Presets.** New paths drawn with the "Paver path" preset get `pavers` with the defaults above, in both the client preset (`static/twin/path_shapes.js` `pathPresets.paver`) and the server's `PATH_PRESETS['paver']`. Existing paver paths have no `pavers` field and keep their look.

**Size cap.** The server refuses a change that would lay more than 5000 pavers on one path, estimated as path area divided by `(length + gap) x (width + gap)`: "Use larger pavers or a shorter path." *(Claude's call: protects the yard build and the bake.)*

## Layouts

Pavers are laid out in path-local coordinates: `s` is distance along the centre line (from `pathCentreline`, so rounded corners and smooth curves are followed), `t` is distance across, 0 on the centre line. A paver's centre `(s, t)` maps to the lot through the centre line's position and tangent at `s`; the paver turns with the tangent there.

- **stepping**: one stone across, centred on the line, one per `length + gap` along it. Path width is ignored.
- **grid**: rows across the path; as many whole pavers across as fit the width (at least one), the group centred. Stack bond.
- **running_bond**: grid with every other row shifted half a paver plus half a gap along the row.
- **diagonal**: the grid turned 45 degrees (plus `rotation`), filling the strip.
- **herringbone**: classic 90-degree herringbone of `length x width` pavers (length is the long side; if equal, it lays a grid), filling the strip, turned 45 degrees plus `rotation` *(Claude's call: 45 degrees is the usual look for walkways)*.

`rotation` turns the pattern within the strip for every layout.

**Edges.** With `whole`, a paver is kept only when every corner lies within the strip (`|t| <= width/2`, `0 <= s <= length of the line`). With `cut`, pavers that cross a side or an end are clipped to it; pieces smaller than a tenth of a paver's area are dropped. Grid and stepping always place at least one paver across, even if it is wider than the path, so a path never draws empty.

**Curves.** On the outside of a bend the joints fan open, as real pavers do. On the inside they would overlap; when a paver overlaps one already placed by more than 10% of its area, it is skipped *(Claude's call)*. Sharp mitred corners follow the same rule.

## Geometry and look

- One merged `BufferGeometry` per paver path, added through the yard's `surfaceMesh`, so picking ownership (`{kind: 'hardscape', pieceId}`), material slots and the bake treat it like the path surface it replaces.
- Each paver is a prism: top face, a small bevel (0.25 in), and four sides down to just below the ground. Its top sits 1 inch above the ground at its centre (`groundAt`, plus the path's `elevation`) *(Claude's call: pavers set at grade read as pavers; a full slab height would float)*.
- Texture coordinates are planar on the top, with a per-paver random offset taken from the path id and the paver's index, so neighbouring pavers do not repeat the same patch of texture.
- The material is the path's surface material (`material`, `materials.surface`), unchanged.
- Curb edging still works with pavers.

**Joints.**
- `grass`: no strip under the pavers. The lawn ground shows, and grass grows in the joints (next section).
- `gravel`: the strip is drawn under the pavers as a thin surface 0.5 in above the ground, kit role `base`, or the `joint` slot when set.
- `sand`: the same strip in a plain sand colour (`#cdb994`, roughness 0.95), or the `joint` slot when set.
- `none`: the lawn ground shows; no grass grows in the joints.

## Grass in the joints

Today a path keeps grass off its whole strip (`grassCovers` in `static/twin/yard_grass.js`).

- A paver path with `grass` joints covers only its pavers: one cover per paver polygon, with a margin just large enough that the field's clumps never stand inside a paver (the clump's reach at the tier's spread).
- Joints narrower than the field's clump spacing would get almost no grass from the field alone. So joint grass is also placed along the joints themselves: short clumps, squeezed across to fit the joint, every 0.15 ft along each joint line, in the same instanced mesh and material as the lawn (still one draw call). They come out of the tier's blade budget, as the edge fringe does.
- With `gravel`, `sand` or `none`, the whole strip stays clear, as today.
- Tiers without lawn blades show the lawn texture in the joints.

Build time: the owner's house grass build on High may grow by at most 100 ms with a 60 ft grass-joint paver path added.

## Editing

The path card (`static/twin/editor/site_shape_shelf.js`) gets a **Surface** choice: Solid or Pavers. With Pavers it shows Layout, Paver length (in), Paver width (in), Gap (in), Rotation (degrees), Edges (Whole pavers only, Cut at the edge) and Joints (Grass, Gravel, Sand, None), plus the Joint material slot for gravel or sand. Each change is one `update_site_shape` op with the whole `pavers` object, so undo steps back one setting.

The terrain card's preset field and the "Paver path" button use the new preset.

Selecting, moving, rotating and editing the centre line work as they do for any path. A click anywhere on the strip, joints included, selects the path.

## What is left to the builder

- The module layout for the paver generator (a new `static/twin/paver_layout.js` for the pure layout, used by the yard build, grass and tests, is the expected shape).
- The exact herringbone construction and the clipping method.
- How joint lines are derived for joint grass (from the layout's rows and columns, or from paver edges).

## Tests

- Pure layout (node): counts and positions for each layout on a straight path; `whole` vs `cut`; the at-least-one rule; curve overlap skipping; the per-path cap.
- Server: field validation, defaults from the preset, `pavers: null`, the cap refusal, older paths untouched.
- Yard build (node): a paver path makes one paver mesh and no continuous slab; gravel and sand add the strip; ownership for picking; curb still drawn.
- Grass (node): covers per paver with grass joints, whole strip otherwise; joint clumps lie in joints and never inside a paver.
- Card (node): the controls and the ops they send.
- Browser (Chromium, test household): draw a Paver path, see pavers, switch layout to herringbone, undo; screenshot for the household.
