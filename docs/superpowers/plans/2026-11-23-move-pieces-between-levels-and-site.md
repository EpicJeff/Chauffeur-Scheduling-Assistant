# Move pieces between levels, buildings and the site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Move to ▸" action moves selected placed pieces to another level of any building or to the site, keeping their spot, facing, height above what they stand on, id and properties, as one undo step.

**Architecture:** A pure module computes the destinations and the ops from the plan and the selection; the editor sends the ops through `applyBatch`, so the server applies them atomically as one round and one undo step. Existing server ops only (`move_hosted`, `delete`, `add_item`, `delete_site_item`, `add_site_item`).

**Tech Stack:** Editor JS modules under `chauffeur/static/twin/editor/`, node-run JS tests and one Playwright Chromium editor test driven from Python.

**Spec:** `docs/superpowers/specs/2026-11-23-move-pieces-between-levels-and-site-design.md` (owner-approved 2026-11-23).

## Global Constraints

- Paths are relative to `chauffeur/`. Tests run from `chauffeur/` as `python tests/<file>.py` with `HA_BASE_URL` unset; never the whole suite.
- No browser dialogs: refusals use `showGlobalAlert` (templates/components/control_center.html).
- Explicit actions only; no re-linking on drag.
- The piece keeps its id; delete-then-add inside one `batch` op (delete first).
- Refusal is all-or-nothing: if any selected piece cannot move, nothing moves.
- Wall- and roof-hosted pieces, plants (`site.planting`), devices, openings and lights are not movable; wall/roof pieces show the entry disabled with the reason.
- Implementer (Codex) does not commit or bump the version.

## Review Focus

1. A rotated building (rotation ≠ 0) must keep the piece's lot point and world facing exactly, both directions. Test in Task 1.
2. A piece on a raised floor (`floor_offset_ft`) or upper level moved to the site keeps its height above the new support, not its absolute height. Test in Task 1.
3. Undo after a cross-list move restores the piece to its original list with the same id and properties. Test in Task 2.
4. A hidden or locked piece stays hidden or locked after the move (keyed by id). Test in Task 2.
5. A mixed selection where one piece cannot move leaves every piece where it was and names the blocker. Test in Task 1.

---

### Task 1: Destinations and ops

**Files:**
- Create: `static/twin/editor/move_to.js`, `static/twin/editor/lot_frame.js`
- Modify: `static/twin/editor/clipboard.js:25-30, :109-122` (import the shared helpers instead of its private copies)
- Test: `tests/test_twin_move_to_js.py` (node; pattern of the existing editor node tests that import clipboard.js)

**Interfaces:**
- Consumes: `hostPoint(building, host, offset)` (twin_hosts.js:15), `parkingPoint` (:6-14), `roomAt(building, levelId, [x,y])` (twin_floors.js:15), `groundAt(plan,x,y)` (twin_ground.js:29), `buildingBase` (:107); clipboard conversions at clipboard.js:298-337 (rotation `lot = item.rotation + b.rotation`; `item = ((lot - b.rotation) % 360 + 360) % 360`; site `elevation = z - groundAt + elevation`; strip `['id','at','src','state','host','device','device_id']`).
- Produces:
  - `lot_frame.js`: `toLot(building, [x,y]) -> [x,y]`, `toLocal(building, [x,y]) -> [x,y]`, `hostedAt(building, host, localXY) -> host` (moved from clipboard.js unchanged in behaviour).
  - `moveTargets(plan, refs) -> [{key:'site'|'<buildingId>:<levelId>', label, disabled:boolean, reason?:string}]`: Site plus every level of every building, labelled `'Site'` and `'<building name> · <level name>'`. The target that equals every selected piece's current place is omitted. When a ref is wall/roof hosted, every entry is disabled with reason `'Wall and roof pieces stay on their wall or roof.'`.
  - `moveOps(plan, refs, targetKey) -> {ops:[...], selection:[ref...]} | {refused:[{ref, reason}]}`. Same-building level change: `move_hosted {building, id, host}` (floor or ceiling of the room under the spot). Other building: `delete` + `add_item` (same id). To site: `delete` + `add_site_item {list:'furniture', id, require_inside:true}`. From site: `delete_site_item` + `add_item`. Reasons: `'No room under it on <level>.'`, `'Ceiling pieces cannot go to the site.'`, `'Wall and roof pieces stay on their wall or roof.'`, `'Plants stay on the site.'`, `'Outside the lot.'`.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_move_to_js.py`:
  - `test_targets_list_site_and_every_level`: two buildings with 2 levels and 1 level give 3 level entries plus Site, minus the current place; labels as specified.
  - `test_building_to_site_keeps_spot_facing_height`: building rotated 30°, item rotation 10°, floor host on an upper level with `floor_offset_ft` 1. The op batch is `[delete, add_site_item]`. The new `at` equals `toLot(hostPoint xy)` within 1e-6. `rotation` = 40. `elevation` = the item's height above its floor. Same id; tint, scale, casts_shadow and object_kind carried.
  - `test_site_to_building_lands_in_room`: `[delete_site_item, add_item]` with host floor = `roomAt` under the spot; `rotation = lot - b.rotation` normalised to 0..360.
  - `test_level_change_same_building_is_move_hosted`: a ceiling piece lands on the ceiling of the room under it.
  - `test_refusals_all_or_nothing`: two pieces, one with no room under it on the target level, gives `{refused:[...]}` naming only that piece, and no ops. Also covered: wall-hosted, plant, and ceiling-to-site.
  - `test_clipboard_unchanged`: the existing clipboard tests still pass when using `lot_frame.js`. Run the existing clipboard test file.
- [ ] **Step 2:** Run. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `lot_frame.js` and `move_to.js` per Interfaces, and switch clipboard.js to the shared helpers.
- [ ] **Step 4:** Run the new test and the existing clipboard test file(s). Expected: pass.
- [ ] **Step 5:** Claude commits: `feat(editor): move pieces between levels, buildings and the site (ops)`.

### Task 2: Editor action, Argyle hint, browser check

**Files:**
- Modify: `static/twin/editor/selection_card.js:123-269` (add a "Move to" button that opens a small menu of `moveTargets`), `static/twin/editor/scene_tools.js:509` (a "Move to" submenu beside Duplicate in the context menu via `context_menu.js`), `static/twin/editor/editor.js:284` (op labels if needed), `services/agent_tools_v2.py:7741-7764` (one line in the edit tool description)
- Test: `tests/test_house_editor_move_to_live.py` (Chromium; use `tests/house_editor_model_harness.py`)

**Interfaces:**
- Consumes: Task 1's `moveTargets` and `moveOps`; `applyBatch(ops, {label})` (editor.js:260); `selection.set(refs)` (selection.js); `tools.chooseFloor(key)` (editor.js:653), or the site view, to switch to the destination; `showGlobalAlert`.
- Produces:
  - On a choice: if `refused`, call `showGlobalAlert` with the names and reasons. Otherwise `applyBatch(ops, {label: 'Move to <label>'})`, then select the moved refs and switch to the destination level or the site.
  - Disabled entries show their reason as the tooltip and accessible description.
  - Agent description line: `"To move a piece between a building and the site (or between buildings) keep its id: send one batch with the delete op first, then the add op."`

- [ ] **Step 1: Write the failing Chromium test** `scenario_move_item_to_site_and_undo`:
  - open the editor on the harness house;
  - right-click a floor-hosted chair, then Move to, then Site;
  - the chair is in `plan.site.furniture` with the same id, and `at` is within 0.01 ft of its old lot point;
  - the editor shows the site, and the chair is selected;
  - press Ctrl+Z once: the chair is back in its building's items with the same id and host.
  Also `scenario_hidden_piece_stays_hidden` and `scenario_wall_piece_entry_disabled` (the entry is disabled with its reason).
- [ ] **Step 2:** Claude runs it (Codex's sandbox cannot launch Chromium). Expected: FAIL.
- [ ] **Step 3:** Implement the card button, context submenu, action and agent line.
- [ ] **Step 4:** Claude runs the Chromium test, `tests/test_twin_move_to_js.py`, and the existing editor selection-card and context-menu tests. Expected: pass.
- [ ] **Step 5:** Claude commits: `feat(editor): Move to action in the selection card and context menu`.
- [ ] **Step 6: Land** (Claude):
  1. Merge main.
  2. Run the gate tests.
  3. `python chauffeur/tools/bump_version.py`.
  4. Add the capabilities entry.
  5. Fast-forward main and push.
  6. Remove the worktree and branch.
  7. Update memory `object-relink-backlog.md` to SHIPPED.
