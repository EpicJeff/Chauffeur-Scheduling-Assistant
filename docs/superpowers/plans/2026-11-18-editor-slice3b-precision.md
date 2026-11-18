# Editor slice 3b: handles and precision tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move / Turn / Scale gizmos on placed things, a typed value during any drag, snapping on by default with Shift to drag free, wall split from the editor with a visible join on drop, and mirroring of placed objects.

**Architecture:** Gizmos are one new handle source (`editor/gizmo.js`) in slice 3a's arbiter, drawn in the same DOM handle layer and sending the ops that exist today. A shared typed-value box (`editor/typed_value.js`) and one snap policy (`editor/snap.js`) serve every drag. Mirror is two booleans on an object, rendered as a negative axis scale with the triangle winding fixed wherever a transform is baked into geometry.

**Tech Stack:** three r187 (vendored), plain ES modules, FastAPI services in Python, tests as plain Python scripts that drive node; Chromium live tests through `tests/house_editor_model_harness.py`.

**Spec:** `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md`, section "Slice 3b: handles and precision tools". Recon of the current code: `.superpowers/sdd/2026-11-18-editor-slice3b-precision/recon.md` (read it; it cites file:line for every hook named below).

## Global Constraints

- Work in `E:\repositories\Chauffeur-editor-slice3b` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser, and never use the user's browser.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run only the tests the task names plus the named neighbours; never the whole suite.
- Do not change the `house_design` agent tool schema. No new packages. No `transmission`. No browser dialogs (`showGlobalAlert`, `promptConfirm`, `promptInput`, `promptChoice` only).
- After any template class change run `python tools/build_tailwind.py` from `chauffeur/`.
- Slice 3a rules stay: a drag on empty space or an unselected thing turns the camera; handles of the selection win at `HANDLE_HIT_PX = 16`; the Move and Turn tools never select and move in one press; Esc cancels any drag and restores exactly.
- Never remove anything a person can do. A control may move (for example from the Select tool to the Turn tool) but must still exist.

## Rulings (Claude's calls, recorded for the owner)

1. **Which tool shows which gizmo.** Select tool: no gizmo; shape handles (wall ends, room corners, pad and shape vertices, line points) as today. Move tool: move gizmo (two plan-axis arrows and a centre square). Turn tool (`#rail-rotate`): a rotate ring. A new **Scale** tool on the rail, next to Turn: a uniform corner handle plus one handle per plan axis. The keys `r`, Shift+`r`, `[`, `]` keep working.
2. **Kinds.** Gizmos apply to building items and anchors without a device (`set_object` / `move_hosted`), yard planting and furniture (`move_site_item`, `set_object`-equivalent site ops as today), site shapes (`move_site_item {by}`, `update_site_shape` through `transformShape`) and point and spot light fixtures (move and `rotation_deg`). Buildings keep their lot glyphs (↔, ↻), which gain snapping, Shift-free and the typed value. Devices keep re-placing; their rotation has no stored field and is not added in this slice. Walls and rooms never get a gizmo; they resize by handles (spec).
3. **The old per-kind glyphs** `object_rotate`, `object_scale`, `site_rotate`, `site_scale` are replaced by the gizmo for the kinds above. Their capability moves to the Turn and Scale tools. `site_move`, vertex, insert and radius handles stay under Select.
4. **Snapping.** On by default for every drag. Holding **Shift** during a drag drags free (no snap) for that drag only. Steps: positions of placed things and site shapes 0.5 ft; angles 15 degrees; scale factor 0.05; walls and joints keep `snapTo` (joint > wall line > extension > right angle > anchor > grid). Buildings: 90 degrees within 7 degrees as today, otherwise 1 degree; Shift frees both.
5. **Typed value.** During any gizmo drag, wall or joint drag, or building move/turn, a small box near the pointer shows the live value (feet and inches, degrees, or a factor). Typing a digit, `.`, `-`, `'` or `"` switches it to entry; Enter applies the exact value along the drag's axis; Esc cancels the whole drag (handled inside the box too); Backspace edits. Values parse with the existing `parseLength` / `feetInches` (`editor/cards.js`).
6. **Join.** A dragged wall end that comes within 1 ft of another joint on the same level (not a neighbour) snaps onto it in the preview, regardless of zoom, and the hint reads "Joins the corner"; that matches the server weld radius (`_weld_move`, 1 ft). Detaching one wall's end from a shared corner is not in this slice.
7. **Split.** A selected wall gets a **Split wall** button on its card. It arms a one-shot click on that wall: the click point (snapped to the inch, and to the midpoint within 6 in) sends `split_wall {building, wall, at}` measured from the wall's first joint; points within 1 ft of an end are refused locally with the server's words. Esc disarms. `split_wall` gets a local apply so the split shows at once.
8. **Mirror.** Two booleans on an object, `mirror_x` (the object's width axis) and `mirror_y` (its depth axis in plan), never the vertical. Rendered as a negative scale on that axis. Toggles "Mirror left-right" and "Mirror front-back" on the object card (`editor/object_shelf.js`), sent as `set_object {properties:{mirror_x}}`. Allowed on building items, anchors without a device, yard planting and furniture.

## Review Focus

1. A mirrored model on every tier and in the bake: faces not inside-out (merged items, rect fixtures, lights, anchors, yard late placements, viewing mode, the bake atlas).
2. Esc while the typed-value box has focus cancels the drag and restores exactly (today `canEscape` skips input targets).
3. Shift held at press time vs pressed mid-drag: the snap state follows the key at each pointer move.
4. A queued step after a split or a join that names the old wall or the merged-away joint: refused cleanly and named, never a stuck queue (slice 2 queue rules).
5. The Select tool still reaches every capability it had (shape handles, vertex insert/remove, keys) and the 3a picking tests stay green.

---

### Task 1: Snap policy and the typed value box

**Files:**
- Create: `chauffeur/static/twin/editor/typed_value.js`
- Modify: `chauffeur/static/twin/editor/snap.js` (add the policy), `chauffeur/static/twin/editor/scene_tools.js` (pass `{free: event.shiftKey}` to every handle gesture's update; route keys to the typed box while a drag is live), `chauffeur/static/twin/editor/drag.js` (honour `free`; joint join snap per ruling 6), `chauffeur/static/twin/editor/handles.js` (`update(event)` passes `free` through), `chauffeur/static/twin/editor/lot_tools.js` (building move/turn: snap per ruling 4, Shift free, typed value)
- Test: `chauffeur/tests/test_twin_typed_value_js.py` (new), `chauffeur/tests/test_twin_snap_js.py` (extend); neighbours `tests/test_twin_drag_js.py`, `tests/test_twin_gesture_rules_js.py`, `tests/test_twin_lot_tools_js.py`, `tests/test_twin_handles_js.py`

**Interfaces:**
- Produces in `snap.js`: `export const SNAP = { move_ft: .5, angle_deg: 15, scale_step: .05, join_ft: 1 }`; `export function snapValue(kind, value, free)` with kind `'move' | 'angle' | 'scale'` (returns `value` unchanged when `free`); `export function joinTarget(plan, buildingId, level, jointId, point) -> {joint, at} | null` (nearest joint on the level within `SNAP.join_ft`, excluding joints that share a wall with `jointId`).
- Produces in `typed_value.js`: `export function createTypedValue(host) -> { show(kind, value, clientXY), key(event) -> 'typing' | 'commit' | 'cancel' | null, value() -> number | null, editing() -> boolean, hide() }`, kind `'length' | 'angle' | 'factor'`. `show` formats `length` as feet and inches (`feetInches`), `angle` as whole degrees, `factor` to two decimals. It never steals focus from the canvas until a value key is typed.
- Gesture contract change: a handle source gesture's `update(point, options)` receives `options = { free: boolean }`; `commit(typed)` receives the typed number when Enter applied one. Existing gestures ignore the new argument safely.

- [ ] **Step 1: Write the failing tests**
  - `snapValue('move', 1.26, false) === 1.5`; `snapValue('angle', 22, false) === 15`; `snapValue('scale', 1.27, false) === 1.25`; each returns the input with `free = true`.
  - `joinTarget` finds a joint 0.9 ft away and not one 1.1 ft away; never a joint that shares a wall with the dragged one.
  - typed box: `show('length', 3.5)` text is `3' 6"`; keys `1`,`2`,Enter give `commit` and `value() === 12`; `4'6"` then Enter gives 4.5; Esc gives `cancel`; Backspace edits; a letter key returns null.
  - drag: a joint dragged to 0.8 ft from another joint previews exactly on it and the hint is `Joins the corner`; with `free` the point is the raw point.
  - gesture rules: Shift held during a site-shape rotate drag gives an unsnapped angle; without Shift it is a multiple of 15.
  - lot tools: building turn snaps to 90 within 7 degrees, otherwise to whole degrees; Shift gives the raw angle; Enter with a typed `30` sends `rotate_building` with rotation exactly 30 more than at the press.
  - Esc while the typed box is in entry mode cancels the drag and restores the preview (the 3a Esc test pattern).

- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.** Thread `free` from `scene_tools` pointer moves (`event.shiftKey` at each move). The typed box lives in the editor's handle layer, follows the pointer, and is shown by each gesture's `update` with its live value; Enter calls the gesture's commit with the typed number applied along the gesture's own axis (a length along the drag direction from the press point, an angle from the press angle, a factor of the press scale).
- [ ] **Step 4: Run the tests and neighbours; all pass.**

---

### Task 2: Gizmos and the Scale tool

**Files:**
- Create: `chauffeur/static/twin/editor/gizmo.js`
- Modify: `chauffeur/static/twin/editor/editor.js` (register the gizmo as a handle source, before `handles`), `chauffeur/static/twin/editor/handles.js` (drop `object_rotate`, `object_scale`, `site_rotate`, `site_scale` descriptors; the gizmo owns them), `chauffeur/static/twin/editor/scene_tools.js` (Scale tool), `chauffeur/templates/house_editor.html` or wherever the rail is built (a **Scale** button `#rail-scale` after `#rail-rotate`, same markup), `chauffeur/static/twin/editor/local_ops.js` (`applyLocal` for `set_object` rotation/scale and for `update_site_shape` points/rotation, so the queue's replay keeps them instant), `chauffeur/static/twin/editor/fixtures.js` (point/spot fixture move and turn through the gizmo)
- Test: `chauffeur/tests/test_twin_gizmo_js.py` (new); extend `tests/test_twin_local_ops_js.py`; neighbours `tests/test_twin_gesture_rules_js.py`, `tests/test_twin_picking_js.py`, `tests/test_twin_handles_js.py`, `tests/test_twin_objects_js.py`, `tests/test_twin_site_shapes_js.py`, `tests/test_twin_ring_js.py`, `tests/test_twin_line_point_handles_js.py`, `tests/test_twin_edit_queue_js.py`

**Interfaces:**
- Consumes: Task 1's `snapValue`, `createTypedValue`, the `update(point, {free})` contract.
- Produces: `export function createGizmo({ getPlan, getSelection, getTool, view, layer, op, typed }) -> { hit(event) -> handle | null, begin(event, handle) -> gesture | null, draw(), clear() }`, a handle source in slice 3a's sense. Handle kinds: `gizmo_move_x`, `gizmo_move_y`, `gizmo_move_free` (Move tool), `gizmo_turn` (Turn tool), `gizmo_scale` (uniform), `gizmo_scale_x`, `gizmo_scale_y` (Scale tool). DOM elements carry `data-gizmo="<kind>"`. Ops are exactly those the replaced handles sent (`move_hosted`, `move_site_item`, `set_object {properties:{rotation|scale|scale_axes}}`, `update_site_shape` via `transformShape`, `update_light_fixture`).

- [ ] **Step 1: Write the failing tests** (node, the editor modules with the stubs used by `test_twin_gesture_rules_js.py`):
  - Move tool + a selected yard plant: the gizmo draws `gizmo_move_x`, `gizmo_move_y`, `gizmo_move_free`; dragging `gizmo_move_x` by 3.2 ft sends `move_site_item` with `at` changed only in x, by 3.0 (snapped); with Shift by 3.2.
  - Turn tool + a selected building item: `gizmo_turn` drag of 50 degrees sends `set_object {properties:{rotation: start+45}}`; typed `33` + Enter sends start+33.
  - Scale tool + a selected item: `gizmo_scale` drag doubling the distance sends `scale` 2.0; `gizmo_scale_x` sends `scale_axes` with only x changed; values clamp to 0.05..20.
  - Select tool: no gizmo elements; `object_rotate` / `site_rotate` descriptors no longer exist; the site shape's vertex and insert handles still do.
  - Turn tool + a site shape: `gizmo_turn` sends `update_site_shape` with rotation in 15-degree steps.
  - A press on a gizmo of the selection wins over an unselected tree under it (3a handle rule).
  - Walls and rooms never show a gizmo under any tool.
  - `applyLocal` applies `set_object` rotation/scale and `update_site_shape` points so `edit_queue.replay` keeps them.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** The gizmo is drawn at the selection's centre in screen space (SVG/DOM in the handle layer, like the existing dots), sized for a 16 px hit. Preview uses the same path each replaced handle used (site outline / `view.rebuildLevel`), plus Task 1's typed box. Rebuild Tailwind if classes changed.
- [ ] **Step 4: Run the tests and neighbours; all pass.**

---

### Task 3: Split wall and join feedback

**Files:**
- Modify: `chauffeur/static/twin/editor/cards.js` or the wall card's builder (a **Split wall** button), `chauffeur/static/twin/editor/scene_tools.js` (the one-shot armed click, via `delegate.pointerArmedDown`), `chauffeur/static/twin/editor/local_ops.js` (`applyLocal` for `split_wall`, mirroring `twin_model_ops._split_drawing` closely enough that the preview matches: two walls, one new joint at `at`, hosted openings kept on the side they sit), `chauffeur/static/twin/editor/drag.js` (hint wording from Task 1 already; make sure the released step after a join does not leave a second joint drawn on the same spot once the server answers)
- Test: `chauffeur/tests/test_twin_split_wall_js.py` (new); extend `tests/test_twin_local_ops_js.py`; neighbours `tests/test_twin_model_ops_walls.py` (server, unchanged, must stay green), `tests/test_twin_edit_queue_js.py`, `tests/test_twin_gesture_rules_js.py`

**Interfaces:**
- Consumes: the server op `split_wall {building, wall, at}` (`services/twin_model_ops.py`, `at` measured from `joints[0]`, refused within 1 ft of either end).
- Produces: card button label `Split wall`; while armed the status line reads `Click the wall where it should split. Esc cancels.`; the armed click sends one `split_wall`.

- [ ] **Step 1: Write the failing tests:**
  - the wall card shows `Split wall`; clicking it arms; a click 4.3 ft along a 10 ft wall sends `split_wall` with `at` 4.25 (inch-snapped: 4.25 is 4' 3"); a click within 6 in of the midpoint sends `at` 5.
  - a click 0.5 ft from an end sends nothing and shows the refusal `Split at least 1 foot from either end.` (or the server's exact words if they differ: use the server's).
  - Esc disarms; a click on another wall while armed sends nothing and disarms.
  - `applyLocal` of `split_wall` on a schema 3 model yields two walls sharing a new joint at the point, with the original's height, thickness and kind; an opening at 2 ft stays on the first wall at 2 ft and an opening at 7 ft moves to the second at 7 - at.
  - join: after a `move_joint` onto another joint, `applyLocal` merges the two joints (one joint left, walls re-pointed) so the preview matches the server's weld.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and neighbours; all pass.**

---

### Task 4: Mirror placed objects

**Files:**
- Modify: `chauffeur/static/twin/object_schema.json` (`mirror_x`, `mirror_y` booleans), `chauffeur/services/twin_objects.py` (validate them; `set_object` accepts them), `chauffeur/services/twin_model_ops.py` (`set_object` / `add_item` paths accept them for items, anchors without a device, yard planting and furniture), `chauffeur/static/twin/objects.js` (`applyObject` negates the x or z scale; a shared `bakeMatrix(geometry, matrix)` that applies the matrix and swaps triangle winding when the determinant is negative, reusing the logic in `mergeByMaterial`), `chauffeur/static/twin/twin_generator.js` (use `bakeMatrix` at the item, rect fixture, light, anchor and door bake sites and in `mergeStatic`), `chauffeur/static/twin/twin_yard.js` (late placements), `chauffeur/static/twin/editor/object_shelf.js` (the two toggles), `chauffeur/static/twin/editor/local_ops.js` (`set_object` mirror in `applyLocal`)
- Test: `chauffeur/tests/test_twin_mirror_js.py` (new); extend `tests/test_twin_objects.py`; neighbours `tests/test_twin_objects_js.py`, `tests/test_twin_object_shelf_js.py`, `tests/test_twin_edit.py`, `tests/test_twin_yard_reuse_js.py`, `tests/test_model_lod_import_js.py`

**Interfaces:**
- Produces: object properties `mirror_x: true` / `mirror_y: true` (absent or false = not mirrored; saved only when true). `export function bakeMatrix(geometry, matrix) -> geometry` in `objects.js`. Card labels `Mirror left-right`, `Mirror front-back`.

- [ ] **Step 1: Write the failing tests:**
  - server: `set_object {properties:{mirror_x: true}}` stores it; `mirror_x: 'yes'` and `mirror_z` are refused; `mirror_x: false` removes the key; an anchor carrying a device is still refused.
  - `applyObject` with `mirror_x` gives a negative x scale and `mirror_y` a negative z scale (three space); never negative y.
  - `bakeMatrix` with a negative-determinant matrix keeps every triangle's normal facing the same way as the unmirrored, transformed triangle (compare the geometric normal from the winding to the transformed vertex normal); with a positive determinant the index order is untouched.
  - a built house with a mirrored item and a mirrored yard furniture piece: every merged mesh's triangles agree with their vertex normals (no inside-out faces) on low, medium and high.
  - right-hinged and swing-out doors (already negative scale): the same winding check passes (fix them if it fails, and say so in the report).
  - the card shows both toggles for an item and a yard furniture piece; toggling sends one `set_object` (or the site equivalent) with only that key.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Check the bake atlas (`static/twin/bake/atlas.js`) charts geometry after `bakeMatrix`, so it sees corrected winding; no atlas change if so, otherwise apply the same fix there.
- [ ] **Step 4: Run the tests and neighbours; all pass.**

---

### Task 5: Browser checks (Claude)

**Files:**
- Create: `chauffeur/tests/test_twin_precision_live.py`

- [ ] Move tool on a yard plant: drag the x arrow; the plant moves along x only, by a 0.5 ft multiple; Shift drag gives a non-multiple; Esc mid-drag restores.
- [ ] Turn tool on a building item: drag the ring, type `30`, Enter: the stored rotation is the start plus 30.
- [ ] Scale tool on an item: uniform drag doubles the scale; undo restores.
- [ ] A wall: Split wall, click near the middle: two walls; drag the new end onto another corner: one joint, "Joins the corner" seen during the drag.
- [ ] Mirror left-right on an imported model item: screenshot before and after on High; no inside-out faces.
- [ ] `tests/test_twin_picking_live.py`, `tests/test_house_editor_steps_live.py`, `tests/test_twin_edit_fast_live.py` stay green.
