# House Editor Slice 3a (Picking and Drag Rules) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the house editor, nothing moves unless the person drags a handle of the selected thing or uses the Move tool; a press-and-drag anywhere else moves the camera; a click selects what is under the pointer and clicking again reaches the thing beneath.

**Architecture:** One gesture arbiter in `scene_tools.js` decides who owns a press, in this order: an armed tool (drawing, placing), the selected thing's handles from every handle source, the Move/Rotate tool on the selected thing's body, and otherwise a "selecting" press that leaves the camera free and selects on release. One picker (`editor/picking.js`) merges every pick source (house pieces, yard objects, yard shapes, pads, light and effect fixtures) into a nearest-first list and owns click cycling and hover. The yard, pad and fixture modules stop starting drags on their own; they supply hits and handles to the arbiter instead.

**Tech Stack:** vanilla ES modules, three.js r187, node tests through `tests/twin_editor_dom.py` (`PRELUDE`, `run_node`), Playwright Chromium through `tests/house_editor_model_harness.py` and `tests/live_app.py`.

**Spec:** `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md`, section "Slice 3a: picking and drag rules" and Testing. **Recon of today's code** (who listens, in what order, every hit test and radius): the scout report pasted into each brief; key facts are restated in the tasks.

## Global Constraints

- Worktree `E:\repositories\Chauffeur-editor-slice3a`, branch `editor-slice3a`. Never edit `E:\repositories\Chauffeur`.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Only the named tests.
- Codex implements; it does not commit, bump `chauffeur/config.yaml`, or edit `system_capabilities.md`. Codex must not launch Chromium or use the user's browser; it writes Chromium tests and Claude runs them.
- No browser dialogs. Desktop mouse and keyboard only (touch is a non-goal), but do not break the existing pinch bookkeeping.
- Nothing a person can do today is removed: every move that a body drag does today stays possible through a handle or the Move tool.
- Right-button and middle-button drags keep their OrbitControls meaning (pan, dolly). Only the left button is arbitrated.
- Picking constants, exported from `editor/picking.js` and used everywhere: `DRAG_THRESHOLD_PX = 3` (unchanged value, now one constant), `HANDLE_HIT_PX = 16` (every handle source: larger than any drawn handle), `CYCLE_SLOP_PX = 4` (a second click within 4 px of the last click cycles).
- Slice 5 will add hide and lock: picking calls `isPickable(candidate)` (default: always true) so slice 5 has one place to plug in.

## Review Focus

1. **A pad is selected and one of its corners sits under a tree.** Pressing the corner and dragging moves the corner; the tree is not selected or moved; the pad stays selected. Pinned in Task 3 (`pad_corner_wins_over_tree`) and Task 7 live (`pad_corner_under_a_tree_moves_the_corner`).
2. **A drag that starts on an unselected tree, bed, building or wall.** The camera turns, the house does not change, nothing new is selected. Pinned in Task 2 (`unselected_press_navigates`) and Task 7 live (`drag_over_a_tree_only_turns_the_camera`, the spec's required test).
3. **A small hand tremor during a click (1 to 2 px).** It is a click: it selects, nothing moves, no op is sent. Pinned in Task 2 (`jitter_under_threshold_is_a_click`).
4. **Clicking again in the same place after the house rebuilt in between.** The cycle restarts at the nearest thing instead of jumping to a stale index. Pinned in Task 1 (`cycle_restarts_when_hits_change`).
5. **Esc during a Move-tool drag of a whole building or a yard item.** The outline and drag hint disappear, nothing is sent, the camera controls come back. Pinned in Task 5 (`esc_cancels_body_drag`).

---

### Task 1: The picker (`editor/picking.js`) and `view.pickAll`

**Files:**
- Create: `chauffeur/static/twin/editor/picking.js`
- Modify: `chauffeur/static/twin/twin_view.js` (`pick`, about lines 519-593: add `pickAll`)
- Test: create `chauffeur/tests/test_twin_picking_js.py`

**Interfaces:**
- Produces in `twin_view.js`: `view.pickAll(x, y) -> Array<{kind, id, building, pieceId, buildingId, level, distance}>`, nearest first, one entry per piece (dedupe by building + id), with today's filters (hidden, faded, focused-room allowed set, roofs in top view). `view.pick(x, y)` keeps its exact current result (its plan-camera wall preference, hosted-piece preference and part refinement stay); `pickAll(...)[0]` need not equal `pick` in those preference cases, but `pick` must be unchanged.
- Produces in `picking.js`:
  - `export const DRAG_THRESHOLD_PX = 3, HANDLE_HIT_PX = 16, CYCLE_SLOP_PX = 4;`
  - `export function createPicker({ sources, isPickable = () => true, now = () => performance.now() })` where `sources` is an array of functions `(x, y) -> Array<candidate>` and a candidate is `{ kind, id, building = null, distance, ...rest }` (`distance` is metres along the pick ray; sources without a ray distance pass one computed from their own hit point). Returns:
    - `at(x, y) -> candidate[]`: all sources merged, `isPickable` applied, deduped by `kind + building + id`, sorted by `distance`.
    - `click(x, y) -> candidate|null`: the nearest, unless the last click was within `CYCLE_SLOP_PX` and `at(x, y)` lists the same candidates (by key, same order) as then, in which case the next one after the last chosen (wrapping). Remembers this click.
    - `peek(x, y) -> candidate|null`: what `click` would return, without remembering anything (for hover).
    - `reset()`: forget the last click (used when the selection is cleared by other means).

- [ ] **Step 1: Write the failing tests** (node; stub sources returning fixed candidate lists):
  - `nearest_first_across_sources`: a house hit at 9 m and a tree at 4 m from two sources: `at` returns the tree first; `click` returns the tree.
  - `second_click_cycles`: clicking twice at the same point returns tree, then house; a third click returns the tree again.
  - `moved_click_does_not_cycle`: a second click 6 px away returns the nearest again.
  - `cycle_restarts_when_hits_change`: between two clicks at the same point a source starts returning a different list (a rebuild): the second click returns the new nearest.
  - `peek_matches_click_without_advancing`: `peek` twice returns the same candidate, then `click` returns that candidate.
  - `unpickable_skipped`: `isPickable` returning false for the tree makes `click` return the house.
  - `pick_all_lists_stacked_pieces` (real `twin_view` through the harness `tests/test_twin_building_reuse_js.py` uses, or the existing pick tests in `tests/test_twin_drag_js.py`): a ray through a wall and the floor behind it returns both, wall first; `view.pick` at the same point returns what it returned before this task.
- [ ] **Step 2: Run** `python tests/test_twin_picking_js.py`. Expected: fails on import.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_picking_js.py`, `python tests/test_twin_drag_js.py`, `python tests/test_twin_import_maps.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 2: The gesture arbiter (select tool) and the pick sources

**Files:**
- Modify: `chauffeur/static/twin/editor/scene_tools.js` (`pick`, about lines 93-113; canvas `pointerdown` capture listener, about lines 229-269; `pointermove` hover, about line 271; `finish`, about lines 304-338)
- Modify: `chauffeur/static/twin/editor/library.js` (`pickSite` about 506-535 becomes a source; `pointerDown` about 542-551)
- Modify: `chauffeur/static/twin/editor/editor.js` (the delegate chain, about lines 749-755, if a delegate's role changes)
- Modify: `chauffeur/tests/test_twin_editor_library_js.py` (lines about 224-231 pin today's select-and-move of a tree in one press; change them to the new rule, see Rulings)
- Test: create `chauffeur/tests/test_twin_gesture_rules_js.py` (drive the real `scene_tools.js` the way `tests/test_twin_drag_js.py` and `tests/test_twin_editor_library_js.py` do)

**Interfaces:**
- Consumes: `createPicker`, constants (Task 1); `view.pickAll`.
- Produces:
  - `library.siteHits(x, y) -> candidate[]` (plants and furniture by their boxes, with ray distance; shape footprints: beds, paths, fences, pool, fire pit, yard rooms, with the distance to their ground hit point). `library.pickSite` stays as a thin wrapper (`picker`-free callers keep working) or is removed if no caller remains.
  - `scene_tools` builds one picker with sources in this order of definition (order does not matter for ranking; distance does): the delegate's own `pick` (flags), `view.pickAll`, `library.siteHits`, and the sources Tasks 3 and 6 add (`terrain.padHits`, `fixtures.hits`). `tools.pick(x, y)` keeps returning one item (now `picker.peek`), so existing callers keep working.
- Rules, all on the left button with the select tool:
  - A press on empty space, or on any thing that is not the current selection, starts a `selecting` gesture and leaves OrbitControls enabled. On release within `DRAG_THRESHOLD_PX` it selects `picker.click(x, y)` (or clears the selection on empty space, as today). Past the threshold it was a camera drag: nothing is selected and nothing changes.
  - `library.pointerDown` no longer selects or starts a `siteDrag` on a press; a yard object moves through its handles (handles.js already gives yard objects `site_move`, `site_rotate`, and shape `site_vertex` handles) or through the Move tool (Task 4).
  - The selected wall's or room's body is no longer a handle with the select tool (`handles.hit` drops its body fallbacks at about lines 235-251 when the tool is `select`; see Rulings). Its drawn handles still drag it.
  - Hover (`roomSelection.hover`) shows `picker.peek(x, y)` and is not recomputed while a button is down.
  - Shift-click add-room and the `!canEdit()` browse path keep working.

- [ ] **Step 1: Write the failing tests:**
  - `unselected_press_navigates`: with a tree and a building in the plan, nothing selected, a press on the tree that moves 40 px: no op is sent, the selection is still empty, and `view.controls.enabled` stayed true throughout.
  - `jitter_under_threshold_is_a_click`: a press on the tree that moves 2 px then releases selects the tree and sends no op.
  - `selected_wall_body_does_not_move_with_select_tool`: a wall is selected; a press on the wall's body away from its drawn handles, moved 40 px: no op is sent and the camera stays enabled.
  - `selected_wall_handle_still_moves`: the same wall, press on its drawn move handle, moved 40 px: one `move_wall` op is sent (through the edit queue as today).
  - `click_cycles_through_stacked_things`: a tree standing on a bed: first click selects the tree, a second click at the same point selects the bed.
  - `hover_shows_what_click_selects`: after the first click on the tree-on-bed point, hover reports the bed.
- [ ] **Step 2: Run** `python tests/test_twin_gesture_rules_js.py`. Expected: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_gesture_rules_js.py`, `python tests/test_twin_editor_library_js.py`, `python tests/test_twin_handles_js.py`, `python tests/test_twin_drag_js.py`, `python tests/test_twin_site_shapes_js.py`, `python tests/test_twin_edit_queue_editor_js.py`. Expected: all pass (the library test with its pinned lines changed to the new rule; every other existing assertion unchanged).
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 3: Handles win: pads and every other handle source

**Files:**
- Modify: `chauffeur/static/twin/editor/terrain_tools.js` (`pointerDown` about lines 388-414; handle radius at about 395; pad outline selection at about 404-411)
- Modify: `chauffeur/static/twin/editor/handles.js` (`hit` radius, about line 227; ring 8 px at about 233; wall segment 10 px at about 242)
- Modify: `chauffeur/static/twin/editor/lot_tools.js` (handle radius 18 px and street edge 10 px, about lines 340 and 360) only to use `HANDLE_HIT_PX` where it is a handle of the selected lot thing
- Modify: `chauffeur/static/twin/editor/scene_tools.js` (the arbiter asks every handle source before anything else)
- Test: `chauffeur/tests/test_twin_gesture_rules_js.py`, `chauffeur/tests/test_twin_terrain_tools_js.py`

**Interfaces:**
- Produces: a handle source contract the arbiter calls first on every left press: `{ hit(event) -> handle|null, begin(event, handle) -> boolean }`. Sources: `handles.js` (selected house piece and yard object), `terrain_tools.js` (the chosen pad's vertex and insert handles), `lot_tools.js` (selected lot handles), and `fixtures.js` point handles (Task 6). The first source whose `hit` returns a handle owns the press; it disables OrbitControls and captures the pointer as today.
- Produces: `terrain.padHits(x, y) -> candidate[]` (a pad is hit on its outline within .6 ft, as today, or on its filled area; `distance` from the ray to its top surface), so a click on a pad selects it through the picker; `terrain.pointerDown` no longer selects a pad on press and no longer gives up its handle to a plant (`close(); return false` at about 398 is removed).
- Every handle hit radius is `HANDLE_HIT_PX` (16); a handle wins over any pick even when a yard object's box is nearer.
- A pad's handles stay usable while a pad save is in flight: the press is held (no other module gets it) instead of falling through; the drag starts after the save answers or is refused with the existing notice if the pad changed underneath.

- [ ] **Step 1: Write the failing tests:**
  - `pad_corner_wins_over_tree` (gesture rules): a pad is chosen; a tree's box covers one of its corners; a press within 12 px of that corner, moved 30 px: one `update_pad` op with that corner moved; the tree is never selected; the pad stays chosen.
  - `handle_radius_is_16`: a press 15 px from a selected wall's end handle grabs it; 17 px does not.
  - `pad_click_selects_through_picker` (terrain tools): with nothing chosen, a click on a pad's outline chooses it; a 40 px drag starting there turns the camera and chooses nothing.
  - `busy_pad_holds_its_handle`: while a pad save is pending, a press on its corner is not passed to the library (no plant selected).
- [ ] **Step 2: Run** the two test files. Expected: the new cases fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_gesture_rules_js.py`, `python tests/test_twin_terrain_tools_js.py`, `python tests/test_twin_handles_js.py`, `python tests/test_twin_lot_tools_js.py`, `python tests/test_twin_site_shapes_js.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 4: The Move and Rotate tools never select and move in one press

**Files:**
- Modify: `chauffeur/static/twin/editor/scene_tools.js` (move/rotate branch, about lines 255-268, and its release, about 332-337)
- Modify: `chauffeur/static/twin/editor/lot_tools.js` (`begin` whole-building move/turn, about lines 335-367)
- Modify: `chauffeur/static/twin/editor/library.js` (a yard object's body drag, now only under the Move tool)
- Test: `chauffeur/tests/test_twin_gesture_rules_js.py`

**Interfaces:**
- Rules with the Move or Rotate tool: a press on the body of the current selection starts a body drag (as today, past `DRAG_THRESHOLD_PX`); a press on anything else is a `selecting` press (Task 2 rules: a click selects it, a drag turns the camera). In the exterior view with a building selected, its body is the whole building, as today. A yard object's body (plant, furniture, shape) moves under the Move tool with the same `move_site_item` op and edit-queue path `library.pointerUp` uses today.

- [ ] **Step 1: Write the failing tests:**
  - `move_tool_unselected_press_navigates`: Move tool, nothing selected, press on a tree moved 40 px: no op, no selection, camera enabled.
  - `move_tool_click_then_drag_moves`: Move tool, click the tree (selects it), then press on it and drag 40 px: one `move_site_item` op.
  - `move_tool_selected_building_body_moves`: exterior view, building selected, Move tool, drag on its body: one building move op as today.
  - `rotate_tool_needs_selection_first`: Rotate tool, unselected building, drag: no op.
- [ ] **Step 2: Run.** Expected: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_gesture_rules_js.py`, `python tests/test_twin_lot_tools_js.py`, `python tests/test_twin_editor_library_js.py`, `python tests/test_twin_drag_js.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 5: Esc cancels any drag and restores exactly

**Files:**
- Modify: `chauffeur/static/twin/editor/scene_tools.js` (Esc handler, about lines 372-377; body drag gesture state)
- Modify: `chauffeur/static/twin/editor/library.js` (Move-tool yard drag from Task 4), `chauffeur/static/twin/editor/terrain_tools.js` (vertex drag), `chauffeur/static/twin/editor/lot_tools.js` (building drag) only where they lack a cancel
- Test: `chauffeur/tests/test_twin_gesture_rules_js.py`

**Interfaces:**
- Esc during any left-button drag (handle, body, pad vertex, yard object, building) cancels it: the preview, drag outline and drag hint are cleared, the thing shows where it was, no op is sent, OrbitControls are restored to their state before the press, and the pointer capture is released. The following pointerup does nothing. Esc with no drag keeps today's meaning (`roomSelection.back()`), and the ground card's own Esc (close) still runs when no drag is active.

- [ ] **Step 1: Write the failing tests:** `esc_cancels_body_drag` (Move tool, building body drag, Esc mid-drag, then pointerup: no op, `#editor-drag-outline` points empty, `#editor-drag-hint` hidden, controls enabled), `esc_cancels_yard_object_drag`, `esc_cancels_pad_vertex_drag` (pad polygon unchanged, no `update_pad`), `esc_without_drag_goes_back` (selection steps back as today).
- [ ] **Step 2: Run.** Expected: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_gesture_rules_js.py`, `python tests/test_twin_handles_js.py`, `python tests/test_twin_terrain_tools_js.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 6: Line fixtures get a handle at every point

**Files:**
- Modify: `chauffeur/static/twin/editor/fixtures.js` (pick at about lines 314-329; the card's point fields at about 94-98 show the op shape)
- Modify: `chauffeur/static/twin/editor/effects.js` (path effects: waterfalls, sheers, anything with `path`)
- Test: create `chauffeur/tests/test_twin_line_point_handles_js.py`

**Interfaces:**
- Consumes: the handle source contract (Task 3), `HANDLE_HIT_PX`.
- Produces: `fixtures.hits(x, y) -> candidate[]` (light and effect fixture meshes, nearest by ray distance, today's occlusion check) for the picker; and a handle source: when a line light fixture with a free path (no `snap`) or a path effect is selected, each path point is a handle drawn like the other editor handles; dragging one moves that point only (on the plane at the point's own height) and sends, on release past the threshold, the same op the card's point fields send: `{op:'update_light_fixture', entity_id, id, change:{path, ...(anchors ? {anchors with that index set to null} : {})}}` for lights, and the effect card's own path op for effects (find it in `effects.js`; if the card has no path field, `{op:'update_effect_fixture', id, change:{path}}`, checked against `services/twin_effect_fixtures.py`). Snapped runs (`snap` set) show no point handles; their card keeps its existing control that frees the run.
- A press on a fixture that is not selected selects it on click and turns the camera on drag (Task 2 rules); `fixtures.pointerDown` no longer disables the camera on a press.

- [ ] **Step 1: Write the failing tests:** `free_line_has_a_handle_per_point` (three points, three handles at their screen positions), `dragging_a_point_moves_only_that_point` (one op; the other points unchanged; the press did not select the floor or wall under it), `snapped_run_has_no_point_handles`, `path_effect_point_drag_sends_its_op`, `unselected_fixture_press_navigates`.
- [ ] **Step 2: Run.** Expected: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_line_point_handles_js.py`, `python tests/test_twin_fixture_editor_js.py`, `python tests/test_twin_line_fixture_tool_js.py`, `python tests/test_twin_effect_editor_js.py`, `python tests/test_twin_gesture_rules_js.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 7: Chromium checks (Codex writes, Claude runs) and landing

**Files:**
- Create: `chauffeur/tests/test_twin_picking_live.py` (pattern: `tests/test_twin_edit_fast_live.py`: one fresh fixture house per scenario via `twin_store.start_over()` then `twin_edit_measure._prepare(None)`; real mouse drags through `twin_edit_measure._mouse_release`; ids computed at runtime from `window.__twin.plan`, never hard-coded)

- [ ] **Step 1 (Codex): Write** the live tests, skipping with a printed line when Playwright is missing:
  - `drag_over_a_tree_only_turns_the_camera` (the spec's required test): add a tree to the fixture's yard; with nothing selected, real-mouse drag 120 px starting on the tree; the camera position changed by more than 0.1 m; `window.__twin.plan` is unchanged (deep-equal); no request to `**/api/house/editor/op` was sent; nothing is selected.
  - `pad_corner_under_a_tree_moves_the_corner`: add a pad and a tree standing over one of its corners; open Ground and yard, choose the pad; drag that corner 1.5 ft; one `update_pad` was sent with the corner moved; the tree's `at` is unchanged; the pad is still the chosen pad.
  - `click_twice_reaches_the_thing_beneath`: a tree on a bed: click selects the tree (card shows it), a second click at the same point selects the bed.
  - `move_tool_never_selects_and_moves`: Move tool, drag on an unselected tree: camera turned, plan unchanged; click it, then drag it 2 ft: one `move_site_item`.
  - `esc_mid_drag_restores`: Move tool, selected tree, start a drag, press Escape before release, release: plan unchanged, no op.
  - `line_light_point_drag`: a free line light fixture with three points selected; drag the middle point's handle; one `update_light_fixture` with only that point changed.
- [ ] **Step 2 (Claude):** Run `python tests/test_twin_picking_live.py`; investigate each failure to its cause; fixes go back through review.
- [ ] **Step 3 (Claude):** Run the gates: `python tests/test_house_editor_live.py` (expect 38 of 39, the known `scenario_pause_card_shows_its_reason_cost_and_pins` failure only; any scenario that dragged a body with the select tool is updated to the new rule only if the old behaviour is exactly what this slice removes, and named in the landing note), `python tests/test_house_editor_steps_live.py` (8 of 8), `python tests/test_twin_edit_fast_live.py` (5 of 5), `python tests/test_house_editor_model_live_t15.py` and `python tests/test_house_editor_model_live_t19.py` (their yard-tree move and Escape scenarios).
- [ ] **Step 4 (Claude):** Land per `AGENTS.md`: merge main, gate tests, `python chauffeur/tools/bump_version.py`, `system_capabilities.md` entry, commit, fast-forward, push, remove the worktree.

## Rulings made in this plan

- **The selected wall's or room's body stops being a handle under the select tool.** Today `handles.hit` treats a press anywhere on the selected wall's line (or room's floor) as its move handle, so a press meant to turn the camera across a selected wall moves the wall: the owner's "navigating moves things". The spec allows movement only from a handle or the Move tool. The wall keeps its drawn move handle and end handles, and the Move tool moves its body. Cost if wrong: one extra step to move a wall; the fix is a single fallback restored.
- **A yard object no longer moves by dragging its body with the select tool.** It moves by its `site_move` handle (already drawn when selected) or with the Move tool. `test_twin_editor_library_js.py` lines about 224-231 pin the old one-press select-and-move and are changed to the new rule; that is the spec superseding a test, not a weakened test.
- **Snapped line runs get no point handles.** Their points follow the host edge; moving one point would detach the run. The card keeps its existing free-the-run control. Cost if wrong: the owner frees a run before dragging its points.
- **Picking is unified for selection; armed tools keep their own clicks.** Drawing a wall or room, placing a device, lot placement and the line-fixture draw tool still take the press before the arbiter while armed, as today; they are explicit modes the person entered.
