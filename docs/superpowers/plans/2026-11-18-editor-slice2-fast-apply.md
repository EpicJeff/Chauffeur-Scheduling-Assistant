# House Editor Slice 2 (Fast Apply) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A released drag (wall, joint, room, yard item) shows its result within 0.5 s on the owner's house, the save runs in the background through an ordered queue, and a refusal snaps back only that step and the steps that needed it.

**Architecture:** The drag preview the person already sees becomes the applied result; the editor keeps a list of pending steps on top of the last house the server confirmed and shows "server house + pending steps". Steps go to the server one at a time. When the server answers, the editor reconciles the kept meshes with the server's house (cheap deform when topology is unchanged, an off-screen rebuild swapped in when it changed). The yard and the server get cheaper where slice 1 measured waste: plants are reused by appearance, the yard updates after the house, solar roof faces are computed once per roof, and the op response is built without re-reading the house.

**Tech Stack:** Python 3.11, FastAPI, vanilla ES modules, three.js r187, node for JS unit tests (`tests/twin_editor_dom.py` `PRELUDE`, `run_node`), Playwright Chromium through `tests/live_app.py` and `tests/house_editor_model_harness.py`.

**Spec:** `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md` (slice 2, Testing). **Numbers:** `docs/superpowers/notes/2026-11-16-editor-slice1-numbers.md`.

## Global Constraints

- Worktree `E:\repositories\Chauffeur-editor-slice2`, branch `editor-slice2`. Never edit `E:\repositories\Chauffeur`.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset: `cd chauffeur; $env:HA_BASE_URL=$null; python tests/<file>.py`. Only the named tests, never the whole suite.
- Codex implements; it does not commit, bump `chauffeur/config.yaml`, or edit `system_capabilities.md`. Codex must not launch Chromium or use the user's browser; it writes Chromium tests and Claude runs them.
- Never read or write `chauffeur/data`; never open `*_api_key.txt`; no real model calls; no new packages in `requirements.txt`.
- No browser dialogs (`alert`, `confirm`, `prompt`): use `showGlobalAlert`, `promptConfirm`. A `beforeunload` guard is the one allowed exception (spec).
- No change to render quality, no `transmission`, no second scene render, no new long-lived stream per tab.
- No change to the `house_design` agent tool schema. New server behaviour is reachable through the existing op route.
- Nothing a person can do today is removed. Undo, redo, the History list, the timing overlay and Send timing keep working.
- Rule I5 holds: undo and redo never revert over someone else's round (`history.js` `CHANGED_SINCE`).
- History keeps the newest 50 steps; nothing here may grow the `house_twin` settings row.
- Words a person reads are plain sentences, as the existing refusal texts are.

## Review Focus

1. **Two releases on the same wall before the first answer.** The second step is computed from the first's local result and both save in order; the house ends where the person left it. Pinned in Task 4 (`second_step_builds_on_first`).
2. **Signed out (401) while steps are queued.** No retry storm, the edits stay on screen as unsaved, the existing sign-in notice shows once. Pinned in Task 4 (`signed_out_stops_sending`).
3. **A refused step followed by a step that only the server can judge** (a door added to the wall whose move was refused). The later refusal joins the same notice instead of raising a second one. Pinned in Task 4 (`later_refusal_joins_notice`).
4. **Argyle or another parent lands a round while steps are queued.** The editor takes that house, replays its unsent steps on top, and undo still refuses to revert over the foreign round. Pinned in Task 4 (`foreign_round_replays_pending`) and Task 5 (`undo_refuses_over_foreign_round_after_replay`).
5. **The state poll arrives with an older round than the editor's newest answer.** It is ignored; the scene does not flash back. Pinned in Task 5 (`stale_poll_ignored`).

---

### Task 1: Solar roof faces computed once per roof (server)

**Files:**
- Modify: `chauffeur/services/twin_solar.py` (`faces`, about line 92)
- Modify: `chauffeur/services/twin_model_ops.py` (`solar_clear`, about line 1304)
- Test: `chauffeur/tests/test_twin_server_speed.py`

**Interfaces:**
- Produces: `twin_solar.faces(building)` returns the same list as today; repeated calls for identical roof input (the building's non-ghost `roofs` and `dormers`, compared by value) reuse one computation. Callers must not mutate the returned faces (return copies or immutable data; the builder chooses). `solar_clear(building, previous)` returns at once when `roofs`, `dormers` and `solar_zones` are equal by value in `building` and `previous`.

- [ ] **Step 1: Write the failing tests** in `test_twin_server_speed.py`, following its `counted()` pattern:
  - `test_wall_move_computes_roof_faces_at_most_once`: on the fixture `tests/fixtures/twin_model/household-2026-11-09.json` with one solar zone added to its first roof (use the existing solar test helpers if present, else `twin_model_ops.apply` with `add_solar_zone`), two consecutive `move_wall` ops through `twin_edit.save` run the face clipping body (`twin_solar.clip`, counted) no more often than one uncached `faces` call does for that building.
  - `test_solar_clear_skips_unchanged_roofs`: `solar_clear(b, copy.deepcopy(b))` calls `twin_solar.error` zero times.
  - `test_roof_edit_still_strands_zone`: the refusal "That would move a solar zone off its roof plane. Move or delete the zone before changing the roof." still fires when a roof under a zone changes so the zone no longer fits (no test covers it today; add it so the cache cannot hide it), and fires again after the cache already holds the old roof.
- [ ] **Step 2: Run** `python tests/test_twin_server_speed.py`. Expected: the two new speed tests fail; the strand test and the existing tests pass.
- [ ] **Step 3: Implement** the memo (a small bounded cache keyed by a canonical JSON of the roof input is enough; 32 entries) and the early return.
- [ ] **Step 4: Run** `python tests/test_twin_server_speed.py`, `python tests/test_twin_energy_equipment.py`, `python tests/test_twin_energy.py`, `python tests/test_twin_model_ops_walls.py`, `python tests/test_twin_model_ops_more.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted; report what changed and what ran.

### Task 2: Op response without re-reading the house (server)

**Files:**
- Modify: `chauffeur/main.py` (`house_editor_op`, about lines 8809-8826)
- Modify: `chauffeur/services/twin_edit.py` (`save`, about line 878) and, if needed, `chauffeur/services/twin_store.py` (`update_model`, about line 697)
- Test: `chauffeur/tests/test_twin_server_speed.py`

**Interfaces:**
- Produces: `POST api/house/editor/op` returns the same JSON as today (`round`, `words`, `plan`, `model`, `timing`, `bytes`); the `plan` and `model` come from the model `save` just wrote, not from a second read. Refusals unchanged: HTTP 400 `{error, timing, bytes}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_op_response_matches_state_without_reread`: after a `move_wall` through the route (TestClient, parent token as the file's other route tests do), the response's `plan` and `model` deep-equal `GET api/house/editor/state`'s; and during the op request `twin_store.current_model` (counted) is called no more than once (the read that loads the house to edit).
  - The existing `test_op_and_state_responses_identical_with_cache` stays green.
- [ ] **Step 2: Run** the file. Expected: the new test fails on the call count.
- [ ] **Step 3: Implement.** `twin_edit.save` returns the written model alongside `round` and `summary`; the route flattens that model for `plan` (the same `twin_model_bridge.flatten` call the read path uses) and primes the read cache with it if one exists, so the next state read is free.
- [ ] **Step 4: Run** `python tests/test_twin_server_speed.py`, `python tests/test_twin_edit_timing.py`, `python tests/test_twin_model_ops_more.py`, `python tests/test_twin_fixtures.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 3: Local moves as pure functions (client)

**Files:**
- Create: `chauffeur/static/twin/editor/local_ops.js`
- Modify: `chauffeur/static/twin/editor/drag.js` (move the preview computation, lines 77-110, into `local_ops.js` and call it)
- Test: create `chauffeur/tests/test_twin_local_ops_js.py`

**Interfaces:**
- Produces, all pure (never mutate the input plan, return a new one):
  - `export class LocalMissing extends Error` — the piece an op names is not in the plan.
  - `export function moveGesture(plan, selection) -> { building, piece, moved: Set<string>, touched, oldWalls: Map, normal: [x,y]|null }` — what `drag.js begin` computes today (lines 28-46), throwing `LocalMissing` when the piece is absent or a ghost.
  - `export function movePreview(plan, gesture, by: [x,y]) -> plan|null` — lines 77-110 of today's `drag.js`; `null` when a moved wall would collapse to zero length.
  - `export function applyLocal(plan, operation) -> { plan, building: string, level: string|null, touched } | null` — for `move_wall` (`by` is a signed distance along the wall's normal, as the server takes it), `move_joint` (`to`), `move_room` (`by`), and `move_site_item` (`list`, `id` or `index`, `at` or `by`; updates `plan.site[list][i].at`; `building` and `level` are `null`, `touched` is `{ site: [list] }`). Returns `null` for any other op (no local apply). Throws `LocalMissing` when the named piece is missing.
- Consumes: `snapTo` stays in `drag.js` (snapping is a gesture concern, not a replay concern).

- [ ] **Step 1: Write the failing tests** (node, the `PRELUDE` harness, the household fixture plan):
  - `move_wall_matches_drag_preview`: for the first non-ghost wall, `applyLocal(plan, {op:'move_wall', building, wall, by: 1}).plan` deep-equals the preview `createDrag` produces for the same 1 ft move (drive `createDrag` with a stub `view` whose `rebuildLevel` records its plan, and `snapTo` reach that cannot snap).
  - `input_plan_untouched`: the plan passed to `applyLocal` is deep-equal before and after.
  - `missing_piece_throws`: `applyLocal(plan, {op:'move_wall', building, wall:'nope', by:1})` throws `LocalMissing`.
  - `site_item_moves`: `move_site_item` with `at: [5, 6]` and with `by: [1, 0]` sets the planting's `at` accordingly; `touched` is `{site:['planting']}`.
  - `other_ops_return_null`: `applyLocal(plan, {op:'add_opening', ...})` is `null`.
- [ ] **Step 2: Run** `python tests/test_twin_local_ops_js.py`. Expected: fails on import.
- [ ] **Step 3: Implement** `local_ops.js` and switch `drag.js` to `moveGesture` and `movePreview` with no behaviour change.
- [ ] **Step 4: Run** `python tests/test_twin_local_ops_js.py`, `python tests/test_twin_drag_js.py`, `python tests/test_twin_import_maps.py`. Expected: all pass (`test_twin_import_maps.py` must see the new module).
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 4: The edit queue (client, pure logic)

**Files:**
- Create: `chauffeur/static/twin/editor/edit_queue.js`
- Test: create `chauffeur/tests/test_twin_edit_queue_js.py`

**Interfaces:**
- Consumes: `applyLocal`, `LocalMissing` from Task 3.
- Produces: `export function createEditQueue({ send, onChange, onSignedOut, retryMs = [1000, 2000, 5000, 10000], now = () => performance.now(), sleep })` returning:
  - `base(state)` — set the confirmed house `{ round, plan, model }`. A state whose `round` is older than the newest confirmed round is ignored (returns `false`); otherwise pending steps are replayed on it and `onChange` fires.
  - `push({ op, label, selection, local })` → `{ id, saved: Promise<result> }`. `local` is the plan the person already sees after this step (the drag preview), or `null`. The step is shown at once (`shown()` includes it) and sent after every earlier step.
  - `shown() -> plan` — the confirmed plan with every pending step applied: a step's `local` while nothing before it changed, otherwise `applyLocal` of its op on the replayed plan; a step whose `applyLocal` returns `null` contributes nothing until the server answers.
  - `state() -> { saved: boolean, saving: number, unsaved: number }`.
  - `pending() -> number`.
- Behaviour, decided here:
  - `send(op)` resolves `{ round, plan, model, words }` or rejects with an `Error` carrying `.status`.
  - **Refusal** is `status` 400, 409 or 422. The step's `saved` rejects with that error (marked `.refused = true`). Later unsent steps are replayed on the confirmed house; any whose `applyLocal` throws `LocalMissing` is dropped, its `saved` rejecting with `.dropped = true`. Steps whose `applyLocal` is `null` stay queued and are sent. `onChange` receives `{ refused: [{ label, reason }], dropped: [label] }` once per drain: refusals that happen while later steps of the same burst are still being sent are collected and reported together when the queue empties.
  - **Signed out** is `status` 401 or 403: sending stops, steps stay pending and unsaved, `onSignedOut()` is called once; `resume()` (also exported) starts sending again.
  - **Any other failure** (no `status`, or 5xx): nothing snaps back, the step stays first in line, and it is retried after `retryMs[min(attempt, last)]` milliseconds through the injected `sleep`. `state().unsaved` counts every pending step while a retry is waiting.
  - On a successful answer the answer becomes the confirmed house (`base`), and the step leaves the pending list.

- [ ] **Step 1: Write the failing tests** (node; inject `send` as a scripted fake and `sleep` as an immediate resolver that records delays):
  - `sends_in_order_one_at_a_time`: three pushes; `send` sees ops in push order, never two in flight.
  - `second_step_builds_on_first`: two `move_wall` pushes on the same wall, `local` null for the second; `shown()` has the wall moved by both; after both answers the confirmed plan is the second answer's.
  - `refusal_snaps_back_only_that_step`: steps A (unrelated wall), B (refused), C (unrelated yard item); B's `saved` rejects `.refused`; A and C are saved; `onChange` reports `refused: [{label: B.label, reason}]`, `dropped: []`.
  - `dependent_step_is_dropped_and_named`: B refused; C is a `move_wall` on a wall id that exists only in B's local result (simulate with a confirmed plan lacking it); C's `saved` rejects `.dropped`; `onChange` reports `dropped: [C.label]`; C is never sent.
  - `later_refusal_joins_notice`: B refused, then D (local `null`) also refused by the server; one `onChange` carries both refusals.
  - `network_failure_keeps_edits_and_retries`: first `send` rejects with no status, then succeeds; `shown()` still includes the step during the wait; `state().unsaved === 1` during the wait; `sleep` was called with `1000`; the step ends saved.
  - `signed_out_stops_sending`: `send` rejects 401; `onSignedOut` called once; no further `send` and no `sleep`; after `resume()` the step is sent.
  - `foreign_round_replays_pending`: while step A waits, `base({round: newer, plan: foreignPlan})`; `shown()` is `foreignPlan` with A applied; `base({round: older})` returns `false` and changes nothing.
- [ ] **Step 2: Run** `python tests/test_twin_edit_queue_js.py`. Expected: fails on import.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_edit_queue_js.py`, `python tests/test_twin_import_maps.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 5: The editor uses the queue

**Files:**
- Modify: `chauffeur/static/twin/editor/editor.js` (`applyOp`, `applyOpNow`, `renderScene`, `polling.onState`, `syncBuildButton`; about lines 68-130, 203-259)
- Modify: `chauffeur/static/twin/editor/history.js` (`enabled`, `sync`)
- Modify: `chauffeur/static/twin/editor/drag.js` (`finish`), `chauffeur/static/twin/editor/scene_tools.js` (`onCommit`), `chauffeur/static/twin/editor/handles.js` (site and hosted-piece finishes), `chauffeur/static/twin/editor/library.js` (planting and furniture drag release, about line 558)
- Modify: `chauffeur/static/twin/editor/api.js` (an op sender that does not raise its own alert)
- Modify: `chauffeur/templates/house_editor.html` (a save-state element in the existing top bar, `#editor-save-state`); run `python tools/build_tailwind.py` if classes change
- Test: create `chauffeur/tests/test_twin_edit_queue_editor_js.py` (drive the real `editor.js` boot the way `test_twin_edit_timing_js.py` does)

**Interfaces:**
- Consumes: `createEditQueue` (Task 4), `applyLocal` (Task 3), `view.settle` (Task 6; until Task 6 lands, call `view.rebuild(plan)` behind the same function name so this task is testable alone).
- Produces: `applyOp(operation, { drag = false, local = null, label = '', selection = null } = {})` returns a promise that resolves when the server saved the step, but the scene shows the step before that. Callers that pass `local` are drag releases: `drag.js finish` passes `g.preview`, the site handles and `library.js` pass `applyLocal(plan, op).plan`. `api.sendOp(operation, timing) -> result` throws the raw error (no alert).
- Decisions:
  - `history.perform` wraps only the wait for `saved`, so a release never waits behind another step's save. Undo and redo buttons stay enabled while steps are pending; a press waits its turn (today's `later` path).
  - `renderScene` draws `queue.shown()` instead of `snapshot.plan` while steps are pending. After a kept drag the editor sets `lastScene` to the shown plan's signature, so neither `renderScene` nor the poll rebuilds what is already drawn.
  - `polling.onState` passes the state to `queue.base`; a state the queue ignores leaves `snapshot` untouched.
  - The save state reads `Saved`, `Saving 2 changes` or `2 changes not saved` (singular for one) in `#editor-save-state`.
  - One notice per drain through `showGlobalAlert`: `"<label> was not saved: <reason>"`, then, when steps were dropped, `"Also undone because it needed that change: <label>, <label>."` The first refused step is selected again (`tools.select(selection)`).
  - A refusal or dropped step that changes what is shown rebuilds the scene from `queue.shown()` (a full `view.rebuild`; refusals are rare).
  - `beforeunload` warns while `queue.pending() > 0`.
  - The timing record for a kept release sets `first_frame` at the local frame and adds `settle` (server answer to settled frame), as the spike did.

- [ ] **Step 1: Write the failing tests** (node, the real editor boot with the fake request layer `test_twin_edit_timing_js.py` uses):
  - `kept_release_draws_once`: a `move_wall` applied with `{drag:true, local}`: `view.rebuild` is not called before or after the answer, `#editor-save-state` reads `Saving 1 change` then `Saved`, and a following poll with the same round calls `view.rebuild` zero times.
  - `stale_poll_ignored`: after an answer at round 12, a poll returning round 11 leaves `snapshot.plan` and the scene unchanged.
  - `refusal_notice_and_selection`: the fake server refuses; one `showGlobalAlert` with the label and reason; `view.rebuild` called once with the plan without the step; the refused piece selected.
  - `undo_waits_for_in_flight_step`: Ctrl+Z pressed while a step is in flight reverts that step after it saves (one `revert` request naming its round).
  - `undo_refuses_over_foreign_round_after_replay`: a foreign round lands during the step; Ctrl+Z after shows `CHANGED_SINCE` and sends no `revert`.
  - `leaving_with_unsaved_warns`: with a pending step, a dispatched `beforeunload` event has `defaultPrevented` true (or `returnValue` set); with none, it does not.
  - `no_browser_dialogs`: `alert`, `confirm` and `prompt` throw if called; the scenarios above still pass.
- [ ] **Step 2: Run** `python tests/test_twin_edit_queue_editor_js.py`. Expected: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_edit_queue_editor_js.py`, `python tests/test_twin_edit_timing_js.py`, `python tests/test_twin_drag_js.py`, `python tests/test_twin_editor_api_js.py`, `python tests/test_twin_editor_history_js.py`, `python tests/test_twin_handles_js.py`, `python tests/test_twin_fixture_editor_js.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 6: Settling a kept release, and the yard after the house (view)

**Files:**
- Modify: `chauffeur/static/twin/twin_view.js` (`rebuildLevel` about line 810, `rebuild` about line 938, `startBake` about line 1184)
- Test: create `chauffeur/tests/test_twin_view_settle_js.py`

**Interfaces:**
- Produces:
  - `rebuildLevel(buildingId, levelId, flat, touched, { keep = false } = {})`: with `keep`, the building is not marked stale.
  - `view.settle(plan, { buildingId = null, levelId = null, touched = null, selection = null } = {}) -> Promise<{ path: 'deform'|'rebuild', selection }>`. When the server's building has the same ids and counts of walls, rooms and openings on that level as the shown one, `settle` deforms in place (`rebuildLevel` with `keep`) and returns `path: 'deform'`. Otherwise it runs `rebuild(plan, { yardLater: true })`, which builds off-screen and swaps in one frame, and returns `path: 'rebuild'`. Either way the bake is restarted once (`startBake`) after the settle, and `selection` is remapped when its wall id is gone: to the wall on the same level whose segment contains the old wall's midpoint (within 0.05 ft), else `null`.
  - `rebuild(plan, { yardLater = false })`: with `yardLater`, the house swap and `view.ready` do not wait for the yard; the yard is built after and swapped in with the same revision check `rebuild` uses, and a newer rebuild cancels it.
- [ ] **Step 1: Write the failing tests** (node, reusing the harness of `tests/test_twin_building_reuse_js.py`, which already drives `twin_view` rebuilds):
  - `same_topology_deforms`: the server plan equals the kept preview except a room polygon; `settle` returns `deform`; `generateTwin` is not called.
  - `split_rebuilds_and_keeps_selection`: the server plan splits the moved wall `w1` into `w1a` and `w1b`; `settle` returns `rebuild` and `selection.id` is the part containing the old midpoint.
  - `yard_later_does_not_hold_ready`: with a yard part that never resolves, `rebuild(plan, {yardLater:true})` resolves and `view.ready` is true; the old yard group is still in the scene.
  - `bake_restarts_once`: after either path, `startBake` ran exactly once.
- [ ] **Step 2: Run** `python tests/test_twin_view_settle_js.py`. Expected: fails.
- [ ] **Step 3: Implement**, and switch Task 5's stand-in to `view.settle`.
- [ ] **Step 4: Run** `python tests/test_twin_view_settle_js.py`, `python tests/test_twin_building_reuse_js.py`, `python tests/test_twin_edit_queue_editor_js.py`, `python tests/test_twin_edit_timing_js.py`, `python tests/test_twin_bake_runtime_js.py`, `python tests/test_twin_reflection_probes_js.py`, `python tests/test_twin_yard_reuse_js.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 7: Plants reused by appearance (yard)

**Files:**
- Modify: `chauffeur/static/twin/twin_yard.js` (`plants` part, about lines 523-563)
- Test: `chauffeur/tests/test_twin_yard_reuse_js.py` (it already drives `buildYard` with a `previous` yard)

**Interfaces:**
- Produces: when `buildYard` rebuilds the `plants` part with a `previous` yard, a plant whose appearance (every planting field except `at` and `elevation`, plus the tier and `viewing`) matches a plant in the previous yard reuses that object (or its geometry and materials) and is only repositioned; `presetTree` and `bakePreset` run only for new or changed appearances. Output identical to a fresh build: same positions, scale, rotation and materials.
- [ ] **Step 1: Write the failing tests:**
  - `moving_one_plant_generates_no_trees`: a yard with three planted presets on high; move one plant's `at`; `presetTree` (counted) runs zero times in the rebuild; the moved plant's object sits at the new ground position.
  - `changed_preset_regenerates_only_that_plant`: change one plant's `preset`; `presetTree` runs once.
  - `fresh_and_reused_match`: the reused yard's plant transforms equal a fresh `buildYard` of the same plan.
- [ ] **Step 2: Run** the test. Expected: fails.
- [ ] **Step 3: Implement.** Reused objects must not be disposed with the previous yard (the yard's existing reuse of parts shows how ownership moves).
- [ ] **Step 4: Run** `python tests/test_twin_yard_reuse_js.py`, `python tests/test_twin_yard_grass_js.py`, `python tests/test_twin_yard_rooms_js.py`, `python tests/test_twin_yard_parts_draw_calls_js.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 8: Checks during the drag

**Files:**
- Modify: `chauffeur/static/twin/editor/local_ops.js` (add the check), `chauffeur/static/twin/editor/drag.js` (`update`), `chauffeur/static/twin/editor/dimensions.js` or the existing dimension label (show it)
- Test: `chauffeur/tests/test_twin_local_ops_js.py`

**Interfaces:**
- Produces: `export function moveProblem(before, after, buildingId) -> string|null` in `local_ops.js`, mirroring `twin_model_ops._validate_move`: a changed wall shorter than 1 ft → `'A wall must be at least 1 ft long.'`; a shortened wall shorter than its widest hosted opening, anchor or item plus 2 × 0.5 ft (`twin_model_hosts.MIN_CLEAR`) → `'That would leave the door narrower than its wall.'`; a changed wall on the same level that now crosses or overlaps another it did not cross before → `'That would cross another wall.'`. The texts are the server's, verbatim. During a drag the current problem shows beside the dimension label and in the status line; the release is still sent (the server stays the judge).
- [ ] **Step 1: Write the failing tests:** `short_wall_problem`, `narrow_door_problem`, `crossing_problem`, `clean_move_has_no_problem`, each building `before`/`after` from the fixture with `movePreview`; and `texts_match_server`: the three strings equal the constants read from `services/twin_model_ops.py` (`_SHORT`, `_NARROW`, `_CROSS`) by the Python test file.
- [ ] **Step 2: Run.** Expected: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_local_ops_js.py`, `python tests/test_twin_drag_js.py`. Expected: all pass.
- [ ] **Step 5:** Leave uncommitted with a note.

### Task 9: Chromium checks and the owner's numbers (Codex writes, Claude runs)

**Files:**
- Create: `chauffeur/tests/test_twin_edit_fast_live.py` (pattern: `tests/test_twin_edit_measure_live.py`, `house_editor_model_harness.open_editor`)
- Modify: `chauffeur/tests/twin_edit_measure.py` (measure a kept release: drive the real handle drag on the measured wall, release, and read the timing record; report `local_frame` and `settle` medians next to today's fields)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1 (Codex): Write** the live tests, skipping with a printed line when Playwright is missing:
  - `kept_move_matches_full_rebuild`: move an interior and an exterior wall 1 ft with a real mouse drag; screenshot `#editor-scene` from a fixed camera; force `view.rebuild(structuredClone(view.plan), {force: true})`; screenshot again; the mean absolute pixel difference over the canvas is below 2 (of 255) and no 32×32 tile differs by more than 12. (This is where the slice 1 "pale block" must be gone.)
  - `split_keeps_selection`: drag a wall end so it lands on another wall's middle (the server splits it); after the answer the selection names an existing wall and the Properties card still shows it.
  - `release_shows_within_bound`: on the fixture at tier `low`, `local_frame` median under 150 ms over 3 releases (a regression guard; the 0.5 s goal is judged on the owner's house in Step 3).
  - `network_drop_keeps_edit`: route `**/api/house/editor/op` to abort once; the moved wall stays moved, the save state reads `1 change not saved`, then `Saved` after the retry.
  - `refused_step_snaps_back_alone`: two releases, the first refused (move a wall 1 ft short of a 1 ft limit), the second unrelated; one notice; the second stays.
- [ ] **Step 2 (Claude):** Run `python tests/test_twin_edit_fast_live.py`. For each failure find the cause; the pale block from slice 1 is investigated here first (its candidates are in the slice 1 note). Fixes go back through review like any task.
- [ ] **Step 3 (Claude):** Run `python -I tests/twin_edit_measure.py --house "C:\Users\ffejn\Downloads\Current house.chauffeur-house.json" --runs 5 --tier high` and `--tier low`. Pass: wall and plant `local_frame` medians under 500 ms on high. Record the table for the capabilities entry.
- [ ] **Step 4 (Claude):** Run the gate: `python tests/test_house_editor_live.py` (expect 38 of 39, the known `scenario_pause_card_shows_its_reason_cost_and_pins` failure only) and `python tests/test_house_editor_steps_live.py` (7 of 8, the known `scenario_add_plans_opens_your_files` only).
- [ ] **Step 5 (Claude):** Land per `AGENTS.md`: merge main, gate tests, `python chauffeur/tools/bump_version.py`, `system_capabilities.md` entry, commit, fast-forward, push, remove the worktree.

## Rulings made in this plan

- **Card edits keep their own route.** Edits saved through `POST api/house/editor/edit` (`editNow`) are not moved onto the op queue; they already run in the history lane, which now waits behind pending op saves, so order is kept. They show when the server answers, as the spec allows for property edits. Cost if wrong: a card edit made during a slow save waits for it.

- **Hosted pieces moved by handle** (openings, anchors, items on a wall) keep their drag preview at release like walls, but `applyLocal` does not replay them. If a foreign round lands while one is in flight, it shows when its answer arrives. Cost if wrong: a rare snap-back flicker, fixed by adding the op to `applyLocal`.
- **Crossing checks on the server stay whole-house** in this slice. Slice 1 measured them at about a quarter of server time; making them local changes `twin_model_graph` semantics that slice 9 rewrites. The settle (second step) still costs about 1 s on the owner's house after Tasks 1 and 2, which the spec allows.
- **The settle may hitch, never flash.** An off-screen rebuild on the owner's house blocks the main thread for about 1 to 2.5 s when topology changed (a split). It swaps in one frame. Cost if wrong: a stutter the owner notices; the fix is a per-level regenerate, which slice 1 did not measure.
