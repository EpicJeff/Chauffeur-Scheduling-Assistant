# House editor: joints first, then the whole-building draft read — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every house the twin builds hold together like a real building, with no see-through seams, no walls through roofs, and awnings that slope correctly. Then replace the crop-by-crop reading of a building's drawings with one whole-building read in feet.

**Architecture:** Two phases that ship separately.

- **Phase A (Tasks 1–4) is the joints.** It touches the 3D generator (`static/twin/twin_generator.js`, `twin_roof.js`) and adds a Python snap pass and joint report (`services/twin_joints.py`) run on every settle and edit. It improves the current engine straight away and ships as v2.499.768.
- **Phase B (Tasks 5–11) is the draft.** It adds new read kinds in `twin_reads`, two schema additions in `twin_plan` and the generator, and a `draft` step in `twin_build` that settles a whole building in feet. Around that step come a quick outline ghost on a side thread, a heartbeat, page anchors for registrations, a per-level fallback, a rooms read, and rebuild matching and migration. It ships as v2.499.769 after local acceptance.

**Tech Stack:** Python 3 (FastAPI services, plain-script tests), ES modules with vendored three r187 run under node for generator tests, and Playwright live tests through `tests/live_app.py`.

**Spec:** `docs/superpowers/specs/2026-11-08-house-editor-whole-building-draft-design.md` (approved 2026-11-08). Read §6a (joints) for Phase A and §1–§8 for Phase B.

## Global Constraints

**Roles**
- Claude writes each task's failing tests first. Codex implements against them. Claude reviews, gates, updates `chauffeur/system_capabilities.md`, bumps `chauffeur/config.yaml` and commits.
- Codex never commits or bumps; it leaves changes in the working tree with a note of what it changed and tested.
- A Codex implementation is never reviewed by Codex.

**Running tests**
- Tests run from `chauffeur/` as plain scripts with `env -u HA_BASE_URL`. Run the task's own tests plus the named neighbours, never the whole suite.
- Every test that imports services sets `CHAUFFEUR_DATA_DIR` to a temp folder BEFORE the import.
- Never read, write or delete anything under `chauffeur/data`.
- Never open, print or commit any `*_api_key.txt`. Recorded fixtures are checked for key-like strings before commit.
- Every critical path gets at least one test that actually runs it: a node run of the generator, or a stub-reader build run. A test that greps the source does not count.

**Product rules**
- No browser dialogs. Plain-sentence log lines and ghost whys, never raw ids.
- After any template class change run `python tools/build_tailwind.py`.
- Do not add packages to `requirements.txt`.
- **Joints come first.** When a measured position and a clean joint disagree within the snap tolerances, the joint wins (spec §6a).
- **Snap tolerances, exactly:**
  - wall ends weld within 1 ft;
  - square or straight within 3 degrees;
  - coordinates round to the nearest inch (1/12 ft);
  - upper-floor walls onto lower wall lines within 1 ft;
  - roof rect edges onto bearing wall lines within 1.5 ft;
  - plates onto wall tops within 1.5 ft;
  - meeting plates equalised within 0.5 ft.
- **Draft read settings:**
  - draft: `thinking_level='medium'`, `max_output_tokens=64000`, `timeout_s=420`, `max_models=1`;
  - per-level fallback and rooms: medium, 32000 output;
  - images whole at up to 2576 px long side;
  - up to 4 photos, the front photo first.
- **Legacy build body** `{building, photos}`: its steps stay exactly as today. The tests that pin slice 1's steps stay green unchanged.
- **Person edits:** a piece with `src.person` is never moved by the snap pass or by a rebuild.

## Review Focus

1. **A wall with no roof over it.** This happens on a hand-edited plan or a shell before its roof is set. `heightAt` returns null there, and the generator's `roofHeight` turns that into Infinity. The wall must keep its own height and never become infinitely tall. Test in Task 2.
2. **An awning whose span sits over no exterior wall, or over a corner.** Expected: it hangs from the nearest exterior wall that faces its side, within 2 ft. Otherwise it is left out with one plain log line, never drawn floating. Test in Task 1.
3. **The snap pass on a plan where a person moved a wall end 0.6 ft from a read corner.** The person's end stays put and the read wall's end moves to it. Test in Task 4.
4. **A draft answer whose page anchors are missing, outside 0..1, or fewer than 2.** That page gets no registration; the build neither crashes nor pauses. Test in Task 8.
5. **A rebuild after a person moved a draft wall.** The wall is matched on its `read_geometry` and comes back once, not twice. Test in Task 10.

---

## Phase A — Joints (ships as v2.499.768)

### Task 1: The awning hangs from its wall and slopes down and away

**Files:**
- Modify: `chauffeur/static/twin/twin_generator.js` (awning branch near line 455; brackets)
- Modify: `chauffeur/services/twin_plan.py` (awning validation near line 234: optional `wall` field)
- Create: `chauffeur/tests/test_twin_awning_js.py` (node driver patterned on `tests/test_twin_materials_js.py`)

**Interfaces:**
- Produces: the awning extension may carry `wall: <exterior wall id>`.
  - When it has one, the generator hangs the awning from that wall's outside face.
  - When it has none, the generator picks the exterior wall on the section's `y0` side whose span overlaps `[x0, x1]` most. Failing that, it takes the nearest exterior wall within 2 ft of the span's midpoint on any side.
  - When nothing qualifies, it draws nothing and records `extension_skipped` in `out.notes`. `buildTwin` already returns `out`; add a `notes` array if there isn't one.
  - The awning's high edge is at the wall face, at `eave + depth * pitch / 12`. Its low outer edge is at `eave`.

- [ ] **Step 1 (Claude): write the failing node tests.** Each test builds the pool-house plan (L1 31×22, front wall from `[0,0]` to `[31,0]`) with awning `{section:'main', x0:17.15, x1:30.14, depth:4, pitch:2, eave:8.75, brackets:2}`. It reads back the awning meshes from `out.pieces` under the piece key of the roof section.
  - `test_awning_slopes_down_away_from_wall`: the top of the awning at plan y = −0.2 is greater than the top at plan y = −3.8. Their difference is 0.67 ± 0.05 ft.
  - `test_awning_low_edge_at_eave`: the lowest top vertex at the outer edge is 8.75 ± 0.2.
  - `test_awning_hangs_from_projecting_wall`: add a 1 ft bay (walls from `[19,0]` to `[19,-1]` to `[28,-1]` to `[28,0]`) and give the awning `wall:'bay-front'`. The awning's wall-side edge is then at plan y −1 ± 0.1, not 0.
  - `test_awning_side_wall`: an awning with `wall` set to the right wall (`[31,0]` to `[31,22]`). Its outer edge lies at x > 31 and is lower than its wall edge.
  - `test_awning_without_wall_is_skipped`: an awning whose span is 10 ft from any wall draws no mesh, and `out.notes` contains `extension_skipped`.
  - `test_awning_brackets_under_it`: every bracket mesh's top is at or below the awning's underside at its plan position, and its back face is within 0.2 ft of the wall face.
- [ ] **Step 2:** Run `env -u HA_BASE_URL python tests/test_twin_awning_js.py`. Expected: FAIL. The slope is reversed today; the check run on 2026-11-08 measured 8.90 at the wall and 9.56 at the outer edge.
- [ ] **Step 3 (Codex):** implement it in the generator. In `twin_plan`, accept an optional string `wall` on the awning that names an existing wall. An unknown id drops the field, with a note, and keeps the awning.
- [ ] **Step 4:** Run the test, `tests/test_twin_materials_js.py` and `tests/test_twin_roof_js.py`. Expected: all PASS.
- [ ] **Step 5 (Claude):** review, then commit with `fix(twin): awnings hang from their wall and slope down and away`.

### Task 2: Every wall meets the roof; walls inside the line; corners close; each floor on its own outline

**Files:**
- Modify: `chauffeur/static/twin/twin_generator.js` (the `wall()` placement near 243, the wall loop near 323, floors near 462)
- Create: `chauffeur/tests/test_twin_joints_js.py` (node driver; raycasts with `THREE.Raycaster` against `out` meshes, no renderer)

**Interfaces:**
- Produces: `buildTwin` behaviour, with no new exports.
  - **Wall tops.** Every wall, exterior and interior, on every level has its top at `roof underside − 0.08` wherever a roof section covers its line, whether that is above or below its own `height`.
  - **Where no roof covers it,** its top is its `height`.
  - **A floor below a higher level** caps its walls at that level's floor underside wherever the next level's outline covers them. Otherwise they reach the roof.
  - **Wall position.** Exterior walls are offset inward by `thickness/2`, so the outside face lies on the from–to line. Corners are extended by `thickness/2` at both ends, so neighbouring walls overlap and close.
  - **Floor slabs.** Each level's slab uses that level's own `outline`, falling back to its own exterior walls' footprint, never L1's.

- [ ] **Step 1 (Claude): write the failing node tests.** Use the main-house draft fixture: copy `plan5.json` from the spike into `tests/fixtures/twin_reads/recorded/claude/draft-main-spike.json` after checking it for keys.
  - `test_no_band_under_eaves`: for each exterior L1 wall under a section with plate 10.9, cast rays from 3 ft outside the wall, perpendicular to it, at heights 10.2 and 10.7, at 5 points along the wall. Each ray hits a wall or roof mesh before passing the wall line + 1 ft.
  - `test_no_wall_above_roof`: cast down from z = 40 at 20 points along each exterior wall's outside face. The first hit is a roof mesh, or nothing where no section covers the point.
  - `test_corners_closed`: at every exterior corner, cast diagonal rays (45°, from outside, at heights 1, 5 and 9 ft). They hit a wall mesh within 0.5 ft of the corner.
  - `test_outside_face_on_line`: for the front wall `[0,0]`–`[70,0]` style segments, the wall meshes' min plan y equals the line within 0.02 (outside face). The max is line + thickness.
  - `test_uncovered_wall_keeps_height`: remove all roof sections. Every wall mesh top equals its `height` within 0.01, and none is infinite.
  - `test_upper_floor_slab_own_outline`: the L2 slab's plan bounds equal L2's outline bounds within 0.05, not L1's.
- [ ] **Step 2:** Run `env -u HA_BASE_URL python tests/test_twin_joints_js.py`. Expected: FAIL on the band, the corners, the outside face and the slab.
- [ ] **Step 3 (Codex):** implement it in the generator.
  - Keep the existing gable-owning behaviour.
  - Clip openings to the new wall top as `wall()` already does.
  - Interior walls stay centred on their line.
- [ ] **Step 4:** Run this test, `test_twin_materials_js.py`, `test_twin_roof_js.py`, `test_twin_awning_js.py`, live `tests/test_twin_view_live.py` and `tests/test_twin_editor_scene_live.py`. Expected: all PASS.
- [ ] **Step 5 (Claude):** review, then commit with `fix(twin): walls meet the roof on every floor, sit inside the line and close at the corners`.

### Task 3: Roof steps are filled; the roof has thickness, fascia, rake trim and soffit

**Files:**
- Modify: `chauffeur/static/twin/twin_roof.js` (new export `stepFaces(sections)`)
- Modify: `chauffeur/static/twin/twin_generator.js` (draw the step faces as siding; roof edge trim and soffit)
- Modify: `chauffeur/tests/test_twin_roof_js.py` (step-face cases)
- Modify: `chauffeur/tests/test_twin_joints_js.py` (rear seams)

**Interfaces:**
- Produces: `stepFaces(sections) -> Float32Array` of triangles in plan feet with z up, in the same convention as `roofMesh().gables[i].positions`. It covers every vertical face where the upper envelope drops by more than 0.05 ft across a section boundary, including overhang edges that sit over another section. Gable ends stay with `gableEnds`.

- [ ] **Step 1 (Claude): write the failing tests.**
  - Roof JS: `test_step_face_between_overlapping_hips`: two hips, A at `[0,0,20,20]` with plate 10 and B at `[20,5,30,15]` with plate 8, both pitch 6. The faces cover the vertical gap along the x = 20 boundary: their area is within 2% of the integral of (A − B) over that boundary.
  - Roof JS: `test_no_step_where_continuous`: two coplanar touching sections give no faces.
  - Joints JS: `test_rear_seams_closed`: with the main-house fixture, cast horizontal rays at 0.5 ft height steps from the rear and both sides toward the building. Wherever the ray's height is below `heightAt` at the building edge, every ray hits a mesh.
  - Joints JS: `test_eave_trim_present`: every free eave edge of the envelope has a trim mesh within 0.3 ft, and the roof surface mesh has thickness of at least 0.15 ft.
- [ ] **Step 2:** Run `env -u HA_BASE_URL python tests/test_twin_roof_js.py` and `tests/test_twin_joints_js.py`. Expected: FAIL.
- [ ] **Step 3 (Codex):** implement `stepFaces`, then in the generator:
  - draw the step faces with the siding material;
  - give the roof thickness by offsetting the envelope down 0.25 ft and stitching the edges;
  - add fascia at eaves and rake trim at gable edges (trim material);
  - add a soffit under each overhang.
- [ ] **Step 4:** Run both tests plus `test_twin_materials_js.py` and the two live view tests. Expected: PASS. Keep the draw-call budget: merge the new meshes through `mergeStatic` like the rest (memory: the house render is draw-call bound).
- [ ] **Step 5 (Claude):** review, then commit with `fix(twin): roof steps are filled and the roof has thickness, fascia, rake and soffit`.

### Task 4: The snap pass and the joint report

**Files:**
- Create: `chauffeur/services/twin_joints.py`
- Modify: `chauffeur/services/twin_build.py` (call `snap` on the building being built after each building step's normalize in `_settle`; log `report` lines when the building's last read step settles)
- Modify: `chauffeur/services/twin_edit.py` (call `snap` on the edited building after an edit applies, before save)
- Create: `chauffeur/tests/test_twin_joints.py`

**Interfaces:**
- Produces:
  - `snap(building: dict) -> list[str]`
    - Mutates the building in place and returns plain-sentence notes, one per kind of move with a count: "Joined 3 wall corners." / "Lined up 2 roof edges with their walls."
    - Never moves a piece with `src.person`. A weld between a person piece and a read piece moves the read end.
    - Idempotent: a second call returns `[]`.
  - `report(building: dict) -> list[str]`: plain sentences for what is still open after snap:
    - "2 outside corners on the Main floor do not meet."
    - "A roof edge over the rear is 2 ft from any wall."
    - "The awning over the garage window has no wall to hang from."
    - Returns `[]` when everything meets.

- [ ] **Step 1 (Claude): write the failing tests.**
  - `test_weld_close_ends`: walls ending 0.8 ft apart share one corner. The moved end is at most 1 ft from its original position.
  - `test_no_weld_beyond_tolerance`: ends 1.3 ft apart stay apart, and `report` names the open corner.
  - `test_square_within_3_degrees`: a 2° skewed wall becomes axis-aligned, and a 5° wall stays.
  - `test_round_to_inch`: every coordinate is a multiple of 1/12 within 1e-9.
  - `test_upper_wall_onto_lower_line`: an L2 wall 0.7 ft inside an L1 wall line moves onto it.
  - `test_roof_edge_onto_wall`: a rect edge 1.2 ft from its bearing wall line moves onto the line, and one 2 ft away stays and is reported.
  - `test_plate_onto_wall_top`: a plate 10.9 over L1 walls with top 10.0 becomes 10.0, while one at 12.0 stays.
  - `test_meeting_plates_equal`: two meeting sections at 10.9 and 10.6 both become one value.
  - `test_awning_gets_wall`: an awning over the front wall gets `wall` set to that wall's id. An awning over nothing is reported.
  - `test_person_piece_never_moves`: a person wall end 0.6 ft from a read corner stays put, and the read end moves to it (Review Focus 3).
  - `test_idempotent`: a second `snap` returns `[]` and changes nothing.
  - `test_build_runs_snap` (stub reader, through `twin_build.start(..., inline=True)` as in `tests/test_twin_build_repair.py`): an outline and walls read with ends 0.5 ft apart settle welded, and the build log contains "Joined".
  - `test_edit_runs_snap`: a `twin_edit` move leaving a read wall end 0.4 ft from another wall's end saves it welded, and the person-moved end is unchanged.
- [ ] **Step 2:** Run `env -u HA_BASE_URL python tests/test_twin_joints.py`. Expected: FAIL (no module).
- [ ] **Step 3 (Codex):** implement it with the tolerances from Global Constraints. Run snap only on building parts, never the lot, and never on load (`twin_store` and `normalize` stay untouched).
- [ ] **Step 4:** Run it plus `test_twin_build_repair.py`, `test_twin_build.py`, `test_twin_build_parts.py`, `test_twin_build_shells.py`, `test_twin_edit.py`, `test_twin_build_replay.py` (its settled counts may rise, never fall) and live `test_house_editor_live.py`. Expected: all PASS.
- [ ] **Step 5 (Claude): ship Phase A.**
  - Rebuild the household's place locally from the recorded reads (no paid reads) and compare the renders before and after from all four sides.
  - Update `system_capabilities.md`, bump to 2.499.768, commit with `fix(twin): joints first - ... (v2.499.768)`, push.

---

## Phase B — The whole-building draft read (ships as v2.499.769)

### Task 5: Lenient JSON and the draft read kinds

**Files:**
- Modify: `chauffeur/services/llm.py` (the JSON return near line 482: `strict_json == 'lenient'`)
- Modify: `chauffeur/services/twin_reads.py` (kinds `draft`, `draft_level`, `draft_rooms`; per-kind thinking, timeout, output; prompts; validators)
- Modify: `chauffeur/services/twin_cost.py` (`estimate` uses per-kind image tokens)
- Modify: `chauffeur/tests/test_twin_reads.py`, `chauffeur/tests/test_twin_cost.py`

**Interfaces:**
- **`call_pool_json(..., strict_json='lenient')`** keeps every completion check that `strict_json=True` has, so a truncated reply still raises. It parses as follows:
  - strip code fences;
  - drop text before the first `{`;
  - decode one object with `raw_decode`;
  - if what follows is exactly one stray `}`, ignore it;
  - if a second JSON object follows, raise `RuntimeError('Two JSON objects in one reply')`;
  - nothing else is repaired.
- **`twin_reads.KINDS`** adds `'draft'`, `'draft_level'` and `'draft_rooms'`.
- **Per-kind settings:**
  - `MAX_OUTPUT`: `draft` 64000, the other two 32000.
  - New `THINKING = {'draft': 'medium', 'draft_level': 'medium', 'draft_rooms': 'medium'}`; every other kind uses `'low'`.
  - New `TIMEOUT = {'draft': 420, 'draft_level': 300, 'draft_rooms': 300}`; every other kind uses 120.
- **Retries.** The draft kinds do not take the doubled-output retry, because 64k is the ceiling. A truncated `draft` returns `{'error': ..., 'truncated': True}`.
- **`parse('draft', answer)`** validates this answer shape: `{building:{levels, walls, openings, rooms, roof:{sections, extensions}, porch, stairs}, pages:[{image:int, level:str, anchors:[{px:[u,v], at:[x,y]}]}], checks:{...}, notes:[...]}`.
  - `parse('draft_level', ...)` takes the same shape restricted to one level, or `roof` only.
  - `parse('draft_rooms', ...)` takes `{rooms:[{name, level, polygon}], walls:[...exterior false]}`.
- **`twin_reads.OUTPUT_CAP`** = `{'anthropic': 64000, 'openai': 64000, 'gemini': 65536}`, keyed by the twin provider.
  - The draft kinds clamp `max_output_tokens` to it.
  - When the cap is below 32000, a `draft` read returns `{'error': 'too small', 'truncated': True}` without calling, and the build takes the per-level fallback. Test: `test_small_output_cap_skips_to_fallback`.
- **`twin_cost.estimate(kind, images)`** uses `IMAGE_TOKENS = {'draft': 5000, 'draft_level': 5000, 'draft_rooms': 5000}` (others 1600) per image.
- **Prompts.** `PROMPTS['draft']` carries every rule in spec §2 "Prompt rules" plus the §3 half-storey and gable-opening rules, the §6a ambiguity line, and the `pages`/`anchors` request. It is written generically, with no household text.

- [ ] **Step 1 (Claude): write the failing tests.**
  - `test_lenient_fences_and_lead_text`: `'Here:\n```json\n{"a":1}\n```'` parses to `{'a':1}`.
  - `test_lenient_trailing_brace`: `'{"a":1}}'` parses to `{'a':1}`.
  - `test_lenient_two_objects_refused`: `'{"a":1}{"b":2}'` raises.
  - `test_lenient_keeps_truncation_check`: an Anthropic stub with `stop_reason='max_tokens'` still raises.
  - `test_draft_call_settings`: a recorded `call_pool_json` stub sees `thinking_level='medium'`, `max_output_tokens=64000`, `timeout_s=420`, `strict_json='lenient'`, `max_models=1` for `draft`, and `'low'`/120 for `outline`.
  - `test_draft_truncated_no_retry`: one call only, and the result has `truncated` True.
  - `test_draft_prompt_generic`: `PROMPTS['draft']` contains "dimension strings", "stop reasoning by about 45000", "half", "anchors" and "prefer the reading where walls, floors and roofs meet". It contains none of "Upton", "Lot 58" or "pool house".
  - `test_parse_draft_shape`: the spike answer `answer5.json`, copied as fixture `draft-main-spike-answer.json` after the key check, parses with no problems.
  - `test_estimate_draft`: `estimate('draft', 6)` is greater than `estimate('outline', 6)` and at most $1.40 at Opus 5.5 rates.
- [ ] **Step 2:** Run `env -u HA_BASE_URL python tests/test_twin_reads.py` and `tests/test_twin_cost.py`. Expected: FAIL.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** Run both, plus `tests/test_model_pools.py` if it exists and `test_twin_place_reads.py`. Expected: PASS.
- [ ] **Step 5 (Claude):** review, then commit with `feat(twin): whole-building draft read kinds with lenient JSON`.

### Task 6: Half-storey levels and gable openings on either ridge axis

**Files:**
- Modify: `chauffeur/services/twin_plan.py` (`_levels` keeps `half: bool`; `_opening_error` for ridge-x gables with `y`)
- Modify: `chauffeur/static/twin/twin_generator.js` (the gable-opening branch near line 413 handles `alongX`; half levels draw a slab and knee walls)
- Modify: `chauffeur/tests/test_twin_plan.py`, `chauffeur/tests/test_twin_joints_js.py`

**Interfaces:**
- **Level shape:** `{..., half: true}`. It is optional and defaults to false.
- **Gable opening on a ridge-`x` gable:** `{gable:'front'|'rear', section, kind, y, width, sill, head}`.
  - `front` is the x0 end and `rear` is the x1 end.
  - `y` is the opening's centre along plan y.
  - Its span must lie within the section's y range.

- [ ] **Step 1 (Claude): write the failing tests.**
  - Plan: `test_half_level_kept` (`half` survives normalize).
  - Plan: `test_ridge_x_gable_opening_valid` (`y` within the span is kept).
  - Plan: `test_ridge_x_gable_opening_outside_dropped`.
  - Plan: `test_ridge_y_gable_opening_unchanged` (an existing case still passes).
  - JS: `test_half_level_has_slab` (an L2 with `half:true` and an outline has a floor slab with its own outline bounds).
  - JS: `test_ridge_x_gable_window_cut` (a ray through the window centre on the x0 gable end passes through the siding and hits the glass mesh).
- [ ] **Step 2:** Run `env -u HA_BASE_URL python tests/test_twin_plan.py` and `tests/test_twin_joints_js.py`. Expected: FAIL.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** Run both plus `test_twin_plan_v2.py`, `test_twin_materials_js.py` and live `test_twin_view_live.py`. Expected: PASS.
- [ ] **Step 5 (Claude):** review, then commit with `feat(twin): half-storey levels and gable windows on side-facing gables`.

### Task 7: The draft step settles a whole building in feet

**Files:**
- Modify: `chauffeur/services/twin_build.py` (`plan_steps`, `_images_context`, `_obtain`, `_settle`, the cache, labels)
- Create: `chauffeur/tests/test_twin_build_draft.py`

**Interfaces:**
- **Steps.** For a building part with floor pages, `plan_steps(...)` returns `[draft, draft_rooms, finishes?, fit?, compose?]`.
  - The step ids are `'draft'` and `'draft_rooms'`.
  - Ruling: `draft_rooms`, not `rooms`, because the step id equals its kind and `rooms` is taken by the crop kind.
  - Labels: "Reading the drawings" and "Rooms".
  - The legacy body path and shells are unchanged.
- **`_images_context` for `draft`** sends one image per page:
  - every page of the building with role floor, roof, elevation or other, whole, through `twin_store.crop(source, page, _FULL, max_side=2576)`, or the person's region when one is cropped onto the building;
  - then up to 4 tagged photos, the front photo first.
  - The context has `pages: [{image, role, level_name}]` and the building's name and kind.
- **`_settle` for `draft`** takes the fragment in feet as is, with no registration mapping.
  - Pieces get `src.step='draft'` and pass through `_merge_list`.
  - Levels come from the draft: L1..Ln by elevation, and the page `level_name` becomes the level `name`.
  - Then `twin_plan.normalize`, then `twin_joints.snap`, then the §5 checks.
  - A failing piece becomes a ghost with a plain why. If the whole first floor fails, the build pauses with `"The drawings could not be read as one building."`, and the pause offers Try again (reread).
- **§5 checks:**
  - the walls of each level close within 0.1 ft;
  - each upper level lies within the level below plus 2 ft;
  - each upper level's area is at least 20% of the level below;
  - each roof rect lies within 3 ft of its bearing walls;
  - each opening lies within its wall's span and height.

- [ ] **Step 1 (Claude): write the failing tests.** They use a stub reader keyed by kind and a temp data dir; the fixture is the spike answer.
  - `test_plan_steps_draft`
  - `test_draft_settles_all_at_once` (one `settled` event carries levels, walls, openings, roof sections and the porch)
  - `test_draft_images_whole_pages_and_photos` (the reader sees N page images and then at most 4 photos, front first)
  - `test_draft_levels_named_from_pages`
  - `test_open_upper_walls_become_ghost_with_why`
  - `test_first_floor_failure_pauses`
  - `test_legacy_body_steps_unchanged`
  - `test_shell_unchanged`
  - `test_draft_cost_estimate_shown` (the build's pre-start estimate includes `draft` and `draft_rooms`)
- [ ] **Step 2:** Run `env -u HA_BASE_URL python tests/test_twin_build_draft.py`. Expected: FAIL.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** Run it plus `test_twin_build.py`, `test_twin_build_parts.py`, `test_twin_build_shells.py`, `test_twin_build_chain.py`, `test_twin_build_repair.py`, `test_twin_joints.py` and `test_house_editor_routes.py`. Expected: PASS.
  - Tests that assumed the crop steps for part builds of drawn buildings get their expected steps updated only where this plan changes them. Name each one in the report.
- [ ] **Step 5 (Claude):** review, then commit with `feat(twin): a drawn building is read whole in feet`.

### Task 8: The quick outline ghost, the heartbeat and page anchors

**Files:**
- Modify: `chauffeur/services/twin_build.py`
- Modify: `chauffeur/services/twin_register.py` (new `from_points`)
- Modify: `chauffeur/tests/test_twin_build_draft.py`, `chauffeur/tests/test_twin_register.py`

**Interfaces:**
- **`twin_register.from_points(px: list, ft: list) -> tuple[dict, float]`** is a least-squares similarity fit from two or more pairs (sheet y flipped as in `apply`). It returns the registration and its RMS in feet, and raises `ValueError` for fewer than 2 pairs or coincident points.
- **The side outline read.** The `draft` step starts the existing `outline` read of the first floor page on a side thread before the draft call.
  - Its result is emitted as one `ghost` event per outline edge with why `"First look at the outline while the drawings are read."`. It never settles anything.
  - It is dropped if it fails or lands after the draft.
  - The cost checkpoint is checked once with `estimate('draft', n) + estimate('outline', 1)`. Both reads go to the ledger.
- **The heartbeat.** While the draft call runs, a `log` event goes out at least every 15 s: `"Reading the <building name> drawings as one set, M:SS so far."`. The clock is injectable as `twin_build._clock` for tests.
- **Anchors.** For each `pages[]` entry with ≥ 2 valid anchors (`px` within 0..1), the anchors map through `twin_store.crop_to_master`, and the build fits `from_points` and stores it with `twin_store.set_registration(source, page, level, reg)`.
  - Invalid or too few anchors mean no registration for that page and no error (Review Focus 4).

- [ ] **Step 1 (Claude): write the failing tests.**
  - Register: `test_from_points_exact` (a known `make(...)` reproduced from 3 points, rms < 1e-6).
  - Register: `test_from_points_needs_two`.
  - Build: `test_outline_ghost_first` (with a stub draft that blocks until released, the outline ghost event comes before the draft's `settled`).
  - Build: `test_outline_late_dropped`.
  - Build: `test_heartbeat_every_15s` (a fake clock advanced 50 s gives at least 3 heartbeat lines with the building's name).
  - Build: `test_checkpoint_combined_estimate`.
  - Build: `test_anchor_registration_upper_floor` (L2's page gets a registration whose apply of an anchor px returns its `at` within 0.5 ft).
  - Build: `test_bad_anchors_no_registration`.
- [ ] **Step 2:** Run both test files. Expected: FAIL.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** Run both plus `test_twin_build.py`, `test_twin_build_repair.py` and live `test_house_editor_live.py` (the Sheet tool shows a drawing under L2 in the stubbed build). Expected: PASS.
- [ ] **Step 5 (Claude):** review, then commit with `feat(twin): a first outline in seconds, a heartbeat while the drawings are read, and every floor lined up with its sheet`.

### Task 9: The per-level fallback and the rooms read

**Files:**
- Modify: `chauffeur/services/twin_build.py`
- Modify: `chauffeur/tests/test_twin_build_draft.py`

**Interfaces:**
- **When the fallback runs:** a truncated `draft`, or a draft whose first floor fails its checks.
- **What it does:** the `draft` step runs `draft_level` reads in order, within the same step: L1 first; then each next level with the settled lower levels as JSON in the context; then `roof` with all levels.
  - It stops at the first level that returns nothing usable, and that pauses as in Task 7.
  - The log says `"The drawings were read one floor at a time."`.
- **`draft_rooms`:** after `draft` settles, one read with the floor pages whole plus the settled levels, exterior walls and openings as JSON. It returns rooms and interior walls in feet.
  - A room or wall outside its level's outline becomes a ghost with a why.

- [ ] **Step 1 (Claude): write the failing tests.**
  - `test_truncated_draft_runs_per_level` (reader calls in order: draft, draft_level L1, draft_level L2, draft_level roof)
  - `test_fallback_level_context_has_lower_levels`
  - `test_fallback_stops_and_pauses_on_empty_level`
  - `test_rooms_read_settles_rooms_and_interior_walls`
  - `test_room_outside_outline_is_ghost`
- [ ] **Step 2:** Run the test. Expected: FAIL.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** Run it plus the Task 7 neighbours. Expected: PASS.
- [ ] **Step 5 (Claude):** review, then commit with `feat(twin): one floor at a time when the whole set does not fit, and rooms read whole`.

### Task 10: Rebuilds keep a person's edits; old-pipeline buildings migrate

**Files:**
- Modify: `chauffeur/services/twin_build.py` (`_matches` and `_merge_list` use `read_geometry` for every person-touched piece; the `fit` gate uses `position_from == 'person'` only; migration before the first `draft` settle)
- Create: `chauffeur/tests/test_twin_build_draft_rebuild.py`

**Interfaces:**
- **Old-pipeline buildings.** A building is old-pipeline when it has walls with `src.step` starting `walls:` or `outline:` and none with `src.step == 'draft'`.
  - On its first draft settle, `twin_register.fit_outline(old L1 enclosed outline, draft L1 outline)` is computed.
  - If its RMS is ≤ 2 ft, every person-added, person-moved and tombstoned piece, and the person `position` when `position_from == 'person'`, is mapped through the fit before the merge.
  - Otherwise these pieces are kept as they are, and one log line says `"Some of your changes may need moving: the new reading of the drawings sits differently."`.
  - Old levels map to new levels by elevation order.
- **Renames.** A rename never sets `position_from`.

- [ ] **Step 1 (Claude): write the failing tests.**
  - `test_person_moved_wall_not_duplicated` (Review Focus 5)
  - `test_person_deleted_wall_stays_deleted`
  - `test_person_placed_building_not_moved_by_fit`
  - `test_renamed_building_is_refit`
  - `test_old_pipeline_edits_migrate` (an old L1 outline offset by (−3, +2) and rotated 0: a person wall moves by the same transform and lands on the draft's wall)
  - `test_old_pipeline_poor_fit_keeps_and_logs`
- [ ] **Step 2:** Run the test. Expected: FAIL.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** Run it plus `test_twin_build.py`, `test_twin_edit.py`, `test_twin_build_parts.py` and `test_twin_build_chain.py`. Expected: PASS.
- [ ] **Step 5 (Claude):** review, then commit with `feat(twin): rebuilds keep your changes, including on buildings read the old way`.

### Task 11: Recordings, replay, acceptance and ship

**Files:**
- Modify: `chauffeur/tools/twin_live.py` (`record-draft --building <id> --budget 2.00`: records `draft` and `draft_rooms` answers for one building into `tests/fixtures/twin_reads/recorded/claude/draft-<id>.json` and `draft_rooms-<id>.json`; refuses `chauffeur/data`)
- Create: `chauffeur/tests/test_twin_build_draft_replay.py`
- Modify: `chauffeur/tests/test_house_editor_live.py` (stubbed draft build: the outline ghost appears, then the building settles; the floor buttons show a half level)
- Modify: `chauffeur/system_capabilities.md`, `chauffeur/config.yaml`

- [ ] **Step 1 (Claude): record the household's two buildings once,** within $2 total, from a scratch data dir holding copies of the documents. Check the fixtures for key-like strings.
- [ ] **Step 2 (Claude): write the replay test.** It must check these against the tolerances in spec §8:
  - pool house: L1 31 × 22 ± 0.25, L2 offset ± 0.25;
  - main house: L1 70 × 66.3 ± 0.5, each wing front y ± 0.5, upper walls closed, centre front gable present;
  - the `twin_joints.report` is empty after snap;
  - the rooms gate: each printed room name inside its polygon, overlap < 1 sq ft, coverage ≥ 85%. The names and their positions come from the recorded fixture's `checks`, or a hand list in the test.

  Also write the live test.
- [ ] **Step 3 (Codex):** fix whatever fails, within this plan's interfaces.
- [ ] **Step 4 (Claude): local acceptance.** Run a full Build your place with real reads in a scratch data dir: under $5 and 30 min. Compare renders from all four sides with the six photos. Check the first ghost appears within 30 s and no 20 s gap in the log.
- [ ] **Step 5 (Claude): ship.** Update `system_capabilities.md`, bump to 2.499.769, commit with `feat(twin): the whole-building draft read ... (v2.499.769)`, push. Update the memory arc. The device run (slice 1b-i Task 19) follows.
