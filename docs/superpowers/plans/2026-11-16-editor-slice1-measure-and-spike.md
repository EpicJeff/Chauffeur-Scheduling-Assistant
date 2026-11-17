# House Editor Slice 1 (Measure and Spike) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the numbers that decide whether an edit can show within 0.5 seconds of release on the owner's house, and what slice 2 must build to get there.

**Architecture:** Most of the instrumentation already exists (`static/twin/edit_timing.js`, `services/twin_timing.py`, the `?perf=1` frame meter). This slice closes its two gaps, adds one repeatable measuring script that drives the real editor in Chromium against a house file given by path, and runs two throwaway experiments (a server profile and a local-apply spike) on a branch that is never merged. It ends with a written note and a go or no-go for slice 2.

**Tech Stack:** Python 3.11, FastAPI, Playwright Chromium through `tests/live_app.py`, vanilla ES modules, three.js r187, node for JS unit tests.

**Spec:** `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md` (slice 1, "What is measured", "Testing").

## What recon found (read before starting)

- A wall move today: `drag.js finish` → `scene_tools.js onCommit` → `editor.js applyOp` → `api.op` → `POST api/house/editor/op` → `twin_edit.save` → `twin_model_ops.apply` → `twin_store.update_model` → `_append_round`. The response carries the whole flat plan and the whole model. The client then calls `view.rebuild(plan)`, and `twin_generator.buildTwin` regenerates the **entire building** the wall belongs to (other buildings and the yard are reused).
- During the drag, `twin_view.js rebuildLevel(buildingId, levelId, flat, touched)` already deforms the existing meshes in place for walls, rooms, openings, anchors and items. It then sets `model.stale = true` (`twin_view.js:846`), which is what forces the full regeneration at release.
- The server normalizes the model twice per edit (`twin_edit.save` → `apply`, then again inside `twin_store.update_model`) and writes the whole model with `fsync` each round.
- Server spans already reported per edit: `lock`, `apply`, `normalize`, `round`, `read`, `response`. Client record already has `request`, `parse`, `rebuild`, `first_frame`, `refresh_state`, `total`, `detail`, `counts`, `server`, `bytes`.
- The overlay exists: menu toggle `#menu-edit-timing`, panel `#editor-edit-timing`, last 30 records in `window.__twinEditTiming`. Gaps against the spec: it does not show frame time during the drag, and it cannot be switched on by a query flag.

## Who does what

- Codex implements Tasks 1, 2, 4 and 5 in the worktree, without committing or bumping (the hand-off contract in `AGENTS.md`).
- Claude reviews each, runs the Chromium checks, runs the measuring script on the owner's house (Task 3), investigates the two timing-out suites (Task 6), writes the note (Task 7), and lands Tasks 1 and 2 with one version bump.

## Global Constraints

- Work in a worktree, never in `E:\repositories\Chauffeur`. Tasks 1, 2, 3, 6, 7: worktree `E:\repositories\Chauffeur-editor-slice1`, branch `editor-slice1` from `main`. Tasks 4 and 5: worktree `E:\repositories\Chauffeur-editor-spike`, branch `editor-spike`, **never merged**.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset: `cd chauffeur; $env:HA_BASE_URL=$null; python tests/<file>.py`. Run only the named tests, never the whole suite.
- Never read or write `chauffeur/data`. Every script uses a temporary `CHAUFFEUR_DATA_DIR` set before any `services` import.
- The owner's house file `C:\Users\ffejn\Downloads\Current house.chauffeur-house.json` is data: pass it by path argument to a script run with `python -I`; never copy it into the repository, never commit numbers that include its contents (timings and counts are fine).
- Never open `*_api_key.txt`. No real model calls. No new packages in `requirements.txt`.
- No browser dialogs (`alert`, `confirm`, `prompt`).
- No change to render quality, no new long-lived stream, no `transmission`.
- No change to the `house_design` tool schema.
- Nothing a person can do today is removed. The existing menu toggle and send button keep working.
- Product code from this slice: the overlay changes and the measuring script. Everything in Tasks 4 and 5 is throwaway.

## Review Focus

1. No drag has happened yet (an edit made from a card or by the agent): the overlay shows `drag frame: n/a`, not `null` or `NaN`. Pinned in Task 1.
2. Browser storage is unavailable (private mode) with `?timing=1`: the overlay still shows. Pinned in Task 1.
3. The house file has no building with a movable wall, or is not a `chauffeur-house` export: the script exits with code 2 and one plain sentence, no traceback. Pinned in Task 2.
4. The server refuses the measured edit: the script reports the refusal text for that operation and still prints the others. Pinned in Task 2.
5. Playwright or Chromium is missing: the script and the live test print a skip line and exit 0, as the other live tests do. Pinned in Task 2.

---

### Task 1: Overlay shows drag frame time and opens by query flag

**Files:**
- Modify: `chauffeur/static/twin/edit_timing.js`
- Modify: `chauffeur/static/twin/editor/editor.js` (where `applyOp` and `applyOpNow` create the record, about lines 74-127; where `mountEditTiming` is called, about lines 351-352)
- Test: `chauffeur/tests/test_twin_edit_timing_js.py`

**Interfaces:**
- Produces: every edit record gains `drag_frame` (number of milliseconds for the last drag frame before the edit, or `null` when the edit did not come from a drag). `mountEditTiming({ toggle, overlay, send, signal, post, report, force })`: `force` true shows the overlay regardless of the stored preference and writes nothing to storage; the toggle still hides and shows it.
- Consumes: `tools.lastDragFrameMs` (`scene_tools.js:395`), which is `null` until a drag has run.

- [ ] **Step 1: Write the failing tests** in `test_twin_edit_timing_js.py`, following the file's existing node harness:
  - `drag_frame_is_recorded`: `beginEdit({op:'move_wall'}, 0)` returns a record with `drag_frame === null`; after the editor applies an op with `tools.lastDragFrameMs = 7.5`, the kept record has `drag_frame === 7.5`.
  - `drag_frame_resets`: a second op with no drag in between has `drag_frame === null` (the editor reads the value once and the next edit does not reuse it).
  - `overlay_shows_drag_frame`: with a last record of `drag_frame: 7.5` the overlay text contains `drag frame: 7.5 ms`; with `drag_frame: null` it contains `drag frame: n/a`.
  - `force_shows_overlay`: `mountEditTiming({..., force: true})` with stored preference `false` leaves `overlay.hidden === false` and does not call `localStorage.setItem`; the same with a `localStorage` whose `getItem` throws.
- [ ] **Step 2: Run** `python tests/test_twin_edit_timing_js.py`. Expected: the four new cases fail, the existing ones pass.
- [ ] **Step 3: Implement.** In `edit_timing.js` add `drag_frame: null` to `beginEdit` and the overlay line, and the `force` parameter. In `editor.js` read `tools.lastDragFrameMs` into the record when the op comes from a drag commit and clear it for the next edit (the builder chooses how the drag commit is told apart; a flag passed from `scene_tools.js onCommit` is the expected shape), and pass `force: new URLSearchParams(location.search).get('timing') === '1'`.
- [ ] **Step 4: Run** `python tests/test_twin_edit_timing_js.py` and the neighbours `python tests/test_twin_drag_js.py`, `python tests/test_twin_editor_api_js.py`, `python tests/test_twin_edit_timing.py`. Expected: all pass.
- [ ] **Step 5:** Leave the changes uncommitted with a short note of what changed and what was run.

### Task 2: Measuring script and regression guard

**Files:**
- Create: `chauffeur/tests/twin_edit_measure.py` (a runnable helper, not a test; same naming as `house_editor_model_harness.py`)
- Create: `chauffeur/tests/test_twin_edit_measure_live.py`
- Read for patterns: `chauffeur/tests/live_app.py`, `chauffeur/tests/house_editor_model_harness.py` (`seed`, `open_editor`, `SIGN_IN_SCRIPT`, `settle`), `chauffeur/services/twin_house_saves.py` (`upload`, `load`)

**Interfaces:**
- Produces: `python -I tests/twin_edit_measure.py --house <path> [--runs 5] [--tier high] [--wall <id>] [--json <out path>]`. Without `--house` it uses the fixture `tests/fixtures/twin_model/household-2026-11-09.json` seeded as the harness does. Importable as `measure(house_path=None, runs=5, tier='high', wall=None) -> dict`.
- Result shape:

```json
{"house": "fixture|file", "tier": "high", "runs": 5,
 "scene": {"meshes": 0, "draw_calls": 0, "triangles": 0, "buildings": 0, "levels": 0},
 "ops": {"move_wall": {"runs": 5, "refused": null,
   "total": {"median": 0, "min": 0, "max": 0},
   "request": {"median": 0}, "parse": {"median": 0}, "rebuild": {"median": 0}, "first_frame": {"median": 0},
   "server": {"lock": 0, "apply": 0, "normalize": 0, "round": 0, "read": 0, "response": 0},
   "detail": {"generate": 0, "batch": 0, "yard": 0, "materials": 0, "dispose": 0, "bake_stop": 0},
   "bytes": 0}},
 "drag_frame_ms": {"median": 0, "max": 0, "frames": 0},
 "idle_frame_ms": {"median": 0}}
```

  Medians for `server` and `detail`. All times in milliseconds.

- [ ] **Step 1: Write the failing live test** `test_twin_edit_measure_live.py` (skips with a printed line when Playwright is missing):
  - `fixture_run_reports_every_field`: `measure(runs=1, tier='low')` returns the keys above; `ops.move_wall.refused is None`; `total.median > 0`; every `server` span is a number.
  - `house_is_unchanged_after`: the plan read from `api/house/editor/state` after the run equals the plan before it, apart from the round number.
  - `bad_file_exits_2`: running the script with `--house` pointing at a temp file containing `{}` exits with code 2 and prints one line with no `Traceback`.
  - `refusal_is_reported`: `measure(runs=1, tier='low', wall='no-such-wall')` returns `ops.move_wall.refused` as a non-empty string and still returns the other operations.
  - `guard_move_wall_under_bound`: on the fixture at tier `low`, `ops.move_wall.total.median < 2500`. This is a regression guard, not the goal; slice 2 lowers it.
- [ ] **Step 2: Run** `python tests/test_twin_edit_measure_live.py`. Expected: fails on import.
- [ ] **Step 3: Implement `twin_edit_measure.py`.** Decisions the builder cannot make alone:
  - With `-I` the script's folder is not on `sys.path`: the script inserts `tests/` and `chauffeur/` itself, from `__file__`, before any other import.
  - Sets `CHAUFFEUR_DATA_DIR` to a fresh `tempfile.mkdtemp` before importing `services`. With `--house`, seeds the parent and token as `house_editor_model_harness.seed` does, then loads the file with `twin_house_saves.upload(data, member)` followed by `twin_house_saves.load(sid)`; an error from `upload` is the exit-2 case.
  - Opens `house/editor?tier=<tier>&test=1&timing=1` with `live_app` and GPU args `live_app.GPU_ARGS`.
  - Operations, each run `runs` times through `window.__twinEditor.op` and read back from `window.__twinEditTiming`: `move_wall` (the wall named by `--wall`, else the first non-ghost wall on the first building's editable level; alternating `by` of `+0.25` and `-0.25` feet so the house ends where it began, with one extra move back when `runs` is odd); `move_site_item` on the first planting, alternating `[1,0]` and `[-1,0]` (reported as `"refused": "no planting"` when the house has none). The first run of each operation is discarded as warm-up and one more is made in its place.
  - Drag frames: select the measured wall, press on its handle with the Playwright mouse, move in 20 steps of 4 pixels, read `window.__twinEditor.lastDragFrameMs` after each step, then press Esc so nothing is committed. If the handle cannot be found on screen, `drag_frame_ms.frames` is `0` and the run still succeeds.
  - Idle frame time: read from the `.twin-frame-meter` box by also passing `perf=1`, or from two `requestAnimationFrame` timestamps; the builder chooses.
  - Prints a short table to stdout and writes the JSON to `--json` when given.
- [ ] **Step 4: Run** `python tests/test_twin_edit_measure_live.py`. Expected: all pass. Also run `python tests/twin_edit_measure.py --runs 2 --tier low` and confirm a table prints.
- [ ] **Step 5:** Leave the changes uncommitted with a note.

### Task 3: Baseline on the owner's house (Claude)

- [ ] **Step 1:** From the slice worktree: `cd chauffeur; $env:HA_BASE_URL=$null; python -I tests/twin_edit_measure.py --house "C:\Users\ffejn\Downloads\Current house.chauffeur-house.json" --runs 5 --tier high --json <scratchpad>\baseline-high.json`, then the same with `--tier low`.
- [ ] **Step 2:** Record the tables for Task 7. Expected by earlier measurement: server about 800 ms, client rebuild about 900 ms; a large difference from that is itself a finding.

### Task 4: Server profile (throwaway, spike branch)

**Files:**
- Create: `chauffeur/tests/twin_edit_profile.py` on branch `editor-spike` only

**Interfaces:**
- Produces: `python -I tests/twin_edit_profile.py --house <path> [--op move_wall] [--runs 5]` prints (a) the six span medians, (b) the top 30 functions by cumulative time from `cProfile` over `twin_edit.save`, restricted to files under `services/`, (c) how many times `twin_model.normalize`, `twin_model.derive`, `twin_model_bridge.flatten`, `json.dumps` and `os.fsync` ran per edit, and the size in bytes of the model written.

- [ ] **Step 1:** Implement, loading the house into a temporary data dir as Task 2 does (copy the loading code; this file is not kept). Counting follows `test_twin_server_speed.py counted()`.
- [ ] **Step 2:** Run it on the fixture to prove it works; print the output. No test file: this is a spike.
- [ ] **Step 3:** Report the output. Claude runs it on the owner's house.

### Task 5: Local-apply spike (throwaway, spike branch)

The question: after a wall move, if the editor keeps the meshes that `rebuildLevel` already deformed instead of regenerating the building, how long does release-to-frame take, and what is wrong in the picture?

**Files (branch `editor-spike` only):**
- Modify: `chauffeur/static/twin/twin_view.js` (`rebuildLevel`, `rebuild`), `chauffeur/static/twin/editor/editor.js` (`applyOpNow`, `renderScene`), `chauffeur/static/twin/editor/drag.js`

- [ ] **Step 1:** Add a query flag `spike=keep`. With it, on a `move_wall` release: (a) the editor does not wait for the server before showing the result (the drag preview stays on screen and `first_frame` is taken at once); (b) when the server answers, the editor calls `view.rebuildLevel(building, level, <flat plan from the answer>, <touched pieces>)` and does **not** mark the building stale, and `renderScene` treats the plan as already drawn. Record `local_apply` (release to frame) and `settle` (server answer to frame) on the timing record.
- [ ] **Step 2:** Add a second value `spike=piece`: as above, but after the server answers, regenerate only the level the wall is on rather than the whole building, if `generateTwin` can be called for one level without rewriting it. If that needs more than a small change, stop and say so; that answer is a result.
- [ ] **Step 3:** Compare pictures. For the fixture house, move one interior wall and one exterior wall by 1 foot under `spike=keep`, then force a full `view.rebuild`; capture a screenshot before and after the forced rebuild from a fixed camera (top-down and one perspective). List every visible difference: wall ends and joints, floor and ceiling outlines, openings, roof edge, baseboards or trim, room labels, baked light.
- [ ] **Step 4:** Report: the two timing records per variant on the fixture, the list of differences with the screenshots' paths, and which pieces would have to be rebuilt for the picture to match. Claude repeats the timing on the owner's house with the script from Task 2 (pass the flag through a `--query` option added on the spike branch only).

### Task 6: Why the two live editor suites time out (Claude)

- [ ] **Step 1:** Follow `superpowers:systematic-debugging`. Run `python tests/test_house_editor_live.py` and `python tests/test_house_editor_steps_live.py` on untouched `main` in the slice worktree with a 10 minute limit each, capturing output; find the scenario and the wait that does not return.
- [ ] **Step 2:** State the root cause with evidence. Fix it only if the fix is inside the test files or harness; a product defect is reported, not fixed here.

### Task 7: The note and the decision (Claude)

**Files:**
- Create: `docs/superpowers/notes/2026-11-16-editor-slice1-numbers.md`

- [ ] **Step 1:** Write: baseline tables (high and low) for the owner's house; where the server time goes and which parts are avoidable (double normalize, whole-model write, whole-house response); spike timings and the list of picture differences; drag frame time; the cause of the live suite timeouts; anything learned that bears on slice 9 (one implementation of the room logic).
- [ ] **Step 2:** State plainly whether 0.5 seconds is reachable with slice 2 as designed, or what must change. If it is not reachable, stop and report to the owner before planning slices 2 and 3b.
- [ ] **Step 3:** Land Tasks 1 and 2 by the steps in `AGENTS.md` (merge main, gate tests, `python chauffeur/tools/bump_version.py`, `system_capabilities.md` entry, commit, fast-forward, push, remove the worktree). The spike branch is deleted unmerged.
- [ ] **Step 4:** Write the plans for slices 2, 3a and 3b from the note.
