# Roofs from Blocks and Photos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A drawn building's roof form is decided by what its photos show, per block, and built by code over blocks taken from the walls.

**Architecture:** The draft read keeps walls, levels, openings, rooms, porches and extensions. Its roof sections become plan evidence only. After the draft settles, the draft step does four things:
- computes blocks from the walls (`twin_blocks`);
- maps each photo to blocks and sides (a `photo_map` read);
- asks what each block's sides show (a `roof_observe` read);
- derives roof sections in code (`twin_roof_derive`), applying a person's block choices first.

The roof check is retired. `roof_issues` runs last as a consistency log.

**Tech Stack:**
- Python 3 services with plain-script tests;
- ES modules (three r187) run under node;
- Playwright live tests.

**Spec:** `docs/superpowers/specs/2026-11-08-house-editor-roofs-from-photos-design.md` (approved 2026-11-08). The conventions it cites are in `docs/superpowers/specs/2026-11-08-plan-reading-conventions.md` §1.6.

## Global Constraints

**How the work is split**
- Claude writes each task's failing tests first.
- Codex implements, and leaves the work uncommitted with a report.
- Claude reviews, gates, documents, bumps the version and commits.
- Codex jobs run one at a time.

**Running tests**
- Run tests from `chauffeur/` with `env -u HA_BASE_URL`. Set `CHAUFFEUR_DATA_DIR` before any services import.
- Never touch `chauffeur/data`. Never open, print or commit any `*_api_key.txt`.

**What a person sees**
- Plain sentences only, with no raw ids, in anything a person reads.
- No browser dialogs.
- A piece with `src.person` is never moved or overwritten.
- Every critical path has a test that runs it.

**Ground truth (the household's main house)**
- No hips anywhere.
- **Middle block:** a side gable (ridge parallel to the street) with a gable end on its left. It has a front gable dormer centred at about 30 ft, about 15 ft wide (within 1 ft), and a pitch lower than the wings.
- **Left wing:** a side gable with its gable end facing left.
- **Right upper block:** a side gable.
- **Garage wing:** a front-facing gable.
- **Third garage, far right:** its ridge is parallel to the street.
- **Ridges:** the left wing, middle and right upper ridges share one ridge line in plan.
- **Rear:** a separate lower-slope roof sits between the two rear gables.
- **Photos:** front 22, right 26, left 23, rear 20.

**Fixed values**
- **Blocks:**
  - coordinates within 0.5 ft snap together;
  - the partition uses the fewest rectangles, largest first;
  - slivers narrower than 7 ft merge into a neighbour.
- **Photos:** use all tagged photos. Above 8, pick the photos that cover the most block sides.
- **Pitch:** clamp to 3–14 in 12. Take it from the plan's pitch triangle first, then the elevations, then the photo estimate.
- **Ridge check:** flag a ridge more than 6 ft above a neighbour's when the photos show them about level.
- **Dormers:** snap to an upper-floor wall jog, or to the plan's dormer position, when one is within 2 ft.
- **Person choices:** a choice matches its block when the block's rect is within 1 ft.

**Reads**
- `photo_map`: low effort, 4000 output.
- `roof_observe`: medium effort, 16000 output, one model, lenient JSON, require_clear before each call.
- The parse retry stays as it is (R35).

**Ruling (deferred).** Spec §7's deep-block split into front and rear roofs (only when the photos show two ridges) is not built in this plan. The observation read has no field for a second ridge, and the household's middle block is one ridge (user, 2026-11-08). It comes back if a household's photos show it.

## Review Focus

1. **A building whose photos show none of a block's ends.** The block gets gable ends, is flagged once with a plain line, and never pauses. The test is in Task 3.
2. **A photo that shows the house from a side the blocks don't match**, for example a photo of the pool house tagged to the main house. `photo_map` answers that no blocks are visible, and the photo is ignored, never mapped wrongly. The test is in Task 5.
3. **A person edits a derived roof's kind on the card, then rebuilds.** The person's form stays, and so does their pitch. The test is in Task 6.
4. **A building with no photos at all.** The plan evidence is used and every end is flagged. No `photo_map` or `roof_observe` read is made, and nothing is spent on them. The test is in Task 5.
5. **An old building with person-edited roof sections, rebuilt for the first time.** Those sections are kept as person sections, and their blocks take them as choices. The test is in Task 6.

---

### Task 1: Blocks from the walls

**Files:**
- Create: `chauffeur/services/twin_blocks.py`
- Create: `chauffeur/tests/test_twin_blocks.py`

**Interfaces:**
- Produces:
  - `blocks(building: dict) -> list[dict]`. Each entry is `{id: 'A'.., rect: [x0,y0,x1,y1], storey: 'upper'|'lower', level: 'L1'|'L2'.., plate: float}`. Ids run A, B, C… in order of area, largest first, and are stable for the same walls.
  - `block_diagram(building: dict, blocks: list) -> bytes`. A PNG top view showing each block's letter and size in feet, with "STREET" written along y=0.

- [ ] **Step 1 (Claude): write the failing tests.**
  - `test_household_blocks`: run it on `tests/fixtures/twin_reads/recorded/claude/draft-main-house.json` (after `twin_plan.normalize`). It returns an upper middle block whose rect is within 1 ft of [14.33,13.33,37.33,52], and an upper right block. The lower blocks include the left wing, the garage front and the third garage (x 59–70). No block is narrower than 7 ft.
  - `test_knee_wall_rooms_stay_in_lower_block`: no block's rect equals only the bonus room or the left bedroom.
  - `test_plate_from_storey`: a lower block's plate is the L1 elevation plus its ceiling; an upper block's plate is the L2 elevation plus its ceiling.
  - `test_stable_ids`: calling it twice gives the same ids and rects.
  - `test_diagram_png`: the diagram is a PNG over 1000 bytes.
- [ ] **Step 2:** run it with `env -u HA_BASE_URL python tests/test_twin_blocks.py`. Expected: FAIL (no module).
- [ ] **Step 3 (Codex):** implement it, using the spike's partition: snap, then minimal rectangles largest first, then merge slivers. The spike code is in scratchpad `spike_roof/`; reuse its approach, not its files. Draw the diagram with Pillow, which is already a dependency (check `requirements.txt`; never add one).
- [ ] **Step 4:** run it. Expected: PASS.
- [ ] **Step 5:** commit with `feat(twin): blocks from the walls`.

### Task 2: Per-end roof ends (gable, hip, clipped)

**Files:**
- Modify:
  - `chauffeur/services/twin_plan.py` `_roof` (~174–247), which keeps a valid `ends`;
  - `chauffeur/static/twin/twin_roof.js` `planes` and `gableEnds`;
  - `chauffeur/static/twin/twin_generator.js` (gable fill per end);
  - `chauffeur/static/twin/editor/cards.js` (roof card fields gain `ends`);
  - `chauffeur/services/twin_edit.py` (the editable roof fields gain `ends`);
  - `chauffeur/services/twin_roof_issues.py` (`hip_point` reads per-end).
- Test:
  - `chauffeur/tests/test_twin_plan.py` (append);
  - `chauffeur/tests/test_twin_roof_js.py` (append);
  - `chauffeur/tests/test_twin_edit.py` (append).

**Interfaces:**
- Produces: a gable or hip section may carry `ends: {<end>: 'gable'|'hip'|'clip'}`. For ridge x, the ends are `x0` and `x1`; for ridge y, they are `y0` and `y1`.
  - When `ends` is absent, the behaviour is unchanged: a gable has gable ends and a hip has hipped ends.
  - A `clip` end is a gable end whose top is a small hip. The hip covers the top third of the gable's rise.

- [ ] **Step 1 (Claude): write the failing tests.**
  - Plan: `ends` with valid keys and values survives normalize. An invalid value is dropped with a plain note.
  - Roof JS:
    - a ridge-x gable with `ends {x0:'gable', x1:'hip'}` has a vertical gable triangle at x0 and a sloped hip plane at x1 (`heightAt` near x1 at mid-depth is below the ridge);
    - a `clip` end has a vertical wall up to two-thirds of the rise and slopes above it;
    - with no `ends`, the results are identical to today's.
  - Edit: the card can set `ends` on a roof section and it persists.
- [ ] **Step 2:** run the three files. Expected: the new tests fail.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** run them, plus `test_twin_joints_js.py`, `test_twin_awning_js.py`, `test_twin_materials_js.py`, `test_twin_roof_issues.py` and live `test_twin_view_live.py`. Expected: PASS.
- [ ] **Step 5:** commit with `feat(twin): a roof can end in a gable, a hip or a clipped gable at each end`.

### Task 3: Deriving the roof from observations

**Files:**
- Create: `chauffeur/services/twin_roof_derive.py`
- Create: `chauffeur/tests/test_twin_roof_derive.py`

**Interfaces:**
- Consumes: `blocks()` (Task 1) and the `ends` schema (Task 2).
- Produces: `derive_roof(blocks, observations, evidence, choices) -> tuple[list[dict], list[dict]]`.
  - **Inputs:**
    - `observations` is `{block_id: {sides: {front|rear|left|right: {kind: 'gable_end'|'clipped_gable_end'|'dormer'|'slope'|'hidden'|'conflict', centre?, width?}}, pitch?: float, slope_vs_neighbours?: 'lower'|'same'|'steeper'}}`.
    - `evidence` is `{block_id: {ridge?: 'x'|'y', pitch?: float, dormers?: [{side, centre, width}]}}`, taken from the plan.
    - `choices` is a list of person choices, each `{rect, kind?, ridge?, ends?, pitch?, plate?, overhang?}`.
  - **Returns:**
    - `sections` in the plan schema. Each has `id 'roof-<block id>'` (a dormer is `'roof-<block id>-dormer-<n>'`), `src.step 'roof_blocks'` and `block: rect`.
    - `flags` as `{block, side?, text}`. The text is a plain sentence naming the block's place, for example "the right upper roof", from where the block sits.

- [ ] **Step 1 (Claude): write the failing tests.** Use the household blocks from Task 1's fixture.
  - `test_principle_per_end`: every combination in spec §4 maps to the right kind, ridge and ends:
    - gable ends left and right give ridge x;
    - gable ends front and rear give ridge y;
    - all four sides slope give a hip;
    - a clipped end gives `ends` with `clip`;
    - an unseen end gives a gable plus a flag;
    - front and rear slopes with both ends hidden take the ridge from the evidence;
    - with no evidence, the ridge runs along the long side, and both ends are flagged.
  - `test_household_truth`: give it the household observations from the spike's round 2 (copy them into the test as data), with the third garage's right side corrected to `gable_end`. The result:
    - matches every ground-truth line;
    - has no hip;
    - has a middle dormer within 1 ft of centre 30 and width 15 (it snaps to the L2 wall jog);
    - gives the left wing, middle and right upper the same ridge y, within 0.5 ft;
    - has a middle pitch below the wings' when `slope_vs_neighbours` is 'lower'.
  - `test_plan_never_decides_kind`: evidence of a hip-like form never changes a side seen as `gable_end`. Evidence only fills `ridge`, `pitch` and `dormers`.
  - `test_choice_wins`: a person choice on a block's rect (within 1 ft) overrides the derived kind, ridge, ends and pitch, and that block is never flagged.
  - `test_pitch_clamp_and_order`: a plan pitch beats the photo pitch; the result is clamped to 3–14.
  - `test_ridge_check_flags`: a ridge more than 6 ft above a neighbour's, where both are `same`, is flagged.
  - `test_unseen_block_flag_text`: a block with every side `hidden` gets plain-sentence flags with no block letter or id.
- [ ] **Step 2:** run it. Expected: FAIL (no module).
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** run it. Expected: PASS.
- [ ] **Step 5:** commit with `feat(twin): roofs derived from what the photos show`.

### Task 4: The two reads

**Files:**
- Modify: `chauffeur/services/twin_reads.py`, adding kinds `photo_map` and `roof_observe` with their prompts, parsing, settings and the parse retry.
- Modify: `chauffeur/services/twin_cost.py`, adding `IMAGE_TOKENS` for both kinds.
- Test: `chauffeur/tests/test_twin_reads.py` and `test_twin_cost.py` (append).

**Interfaces:**
- **`photo_map`:**
  - Images: the block diagram, then one photo.
  - Context: `{blocks: [{id, rect, storey}], building}`.
  - Answer: `{from_side: 'front'|'rear'|'left'|'right'|'front-left'|..|'none', blocks: [{id, sides: [...]}]}`.
- **`roof_observe`:**
  - Images: the block diagram, then the photos in order.
  - Context: `{blocks, photo_map: {photo_index: {from_side, blocks}}, building}`.
  - Answer: `{blocks: {id: {sides: {front|rear|left|right: {kind, centre?, width?, photo?}}, pitch?, slope_vs_neighbours?}}}`.
- **Draft prompt update** (spec §5): `PROMPTS['draft']` takes its roof-plan reading rules from the conventions reference §1.6.
  - It says hips run from the eave corners.
  - A small centred triangle narrower than the end is a clipped-gable mark.
  - The ridge direction comes from the ridge line.
  - Its roof sections are evidence only.
  - Test: the draft prompt contains "eave corners" and "clipped".
- **Prompts** are written from spec §2 and §3, and are generic. They contain "triangular wall", "clipped", "slopes down to the eave" and "hidden". They never ask for a roof kind; they ask only what is seen.

- [ ] **Step 1 (Claude): write the failing tests.**
  - Call settings: low effort / 4000, and medium effort / 16000, with `strict_json='lenient'` and max_models 1.
  - Parse shapes. An unknown block id is dropped with a problem. A side kind outside the enum is dropped.
  - The prompts are generic (no "Upton" and no "pool house"), contain the four phrases, and contain neither "hip" nor "gable roof" as a question.
  - `estimate('roof_observe', 4)` is at most $0.20 and `estimate('photo_map', 1)` is at most $0.04 at Opus 5.5 rates.
- [ ] **Step 2:** run them. Expected: the new tests fail.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** run `test_twin_reads.py`, `test_twin_cost.py` and `test_twin_place_reads.py`. Expected: PASS.
- [ ] **Step 5:** commit with `feat(twin): reads that ask what the photos show`.

### Task 5: Wiring into the draft step

**Files:**
- Modify: `chauffeur/services/twin_build.py`, covering the draft step's roof path, retiring the roof check, flags, the estimate and the heartbeat.
- Modify: `chauffeur/main.py`, for the build estimate (`estimates.build[id]` gains `photo_map` and `roof_observe`, and drops `roof_check`).
- Test: new `chauffeur/tests/test_twin_build_roof_blocks.py`. Existing pins change only where this task changes them; name each one.

**Interfaces:**
- Consumes: Tasks 1, 3 and 4.
- **Produces, in the draft step after the draft fragment is merged (or after the fallback):**
  1. Compute blocks.
  2. If there are photos, run one `photo_map` read per photo, picking photos by coverage when there are more than 8.
  3. Run one `roof_observe` read.
  4. Build plan evidence from the draft's roof sections: for each block, the ridge axis, pitch and dormers of the draft section that overlaps it most.
  5. Collect person choices from `building['roof']['choices']`.
  6. Call `derive_roof`.
  7. Replace every draft roof section that is not a porch roof and has no `src.person` with the derived sections.
  8. Keep extensions.
  9. Log each flag once, plainly, and store the flags on the step.
  10. Run `roof_issues` last, as today.
- `require_clear()` runs before each read. The heartbeat says "Checking the roofs against the photos, M:SS so far."
- `roof_check` is no longer called. Its kind stays in `twin_reads` for old caches.

- [ ] **Step 1 (Claude): write the failing tests,** using a stub reader keyed by kind and the household draft fixture.
  - `test_reads_in_order`: draft, then photo_map once per photo (4 photos give 4), then roof_observe, then draft_rooms. No roof_check.
  - `test_derived_roof_replaces_draft_roof`: with the stub answering the household round-2 observations (the third garage corrected), the settled roof matches the ground truth from Task 3, porch roofs and awning are kept, and there are no hips.
  - `test_no_photos_no_reads`: Review Focus 4.
  - `test_unrelated_photo_ignored`: Review Focus 2. A photo_map answer with `from_side: 'none'` leaves that photo out of roof_observe's map.
  - `test_unseen_end_flagged_never_pauses`: Review Focus 1.
  - `test_estimate_and_checkpoint`: the step estimate includes photo_map × photos and roof_observe, and there is one require_clear per read.
- [ ] **Step 2:** run it. Expected: FAIL.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** run it, plus `test_twin_build_draft*.py`, `test_twin_build_roof_check.py` (where it pins roof_check calls, update only that expectation), `test_twin_build_roof_issues.py`, `test_twin_build.py`, `test_house_editor_routes.py` and live `test_house_editor_live.py`. Expected: PASS.
- [ ] **Step 5:** commit with `feat(twin): the draft's roof comes from the blocks and the photos`.

### Task 6: Person choices and the editor marker

**Files:**
- Modify:
  - `chauffeur/services/twin_edit.py`: an edit to a section whose `src.step` is `roof_blocks` stores a choice in `building['roof']['choices']`, keyed by its `block` rect.
  - `chauffeur/services/twin_build.py`: migration of old person-edited sections.
  - `chauffeur/static/twin/editor/panel.js` and `scene_tools.js`, or the existing ghost and needs-checking path: a flagged block's roof shows the needs-checking marker, and tapping it selects the roof and opens its card.
- Test:
  - `chauffeur/tests/test_twin_edit.py` (append);
  - `test_twin_build_roof_blocks.py` (append);
  - a node test for the marker (new `tests/test_twin_roof_flags_js.py`);
  - live `test_house_editor_live.py` (append one scenario).

**Interfaces:**
- A choice is `{rect, kind?, ridge?, ends?, pitch?, plate?, overhang?, src:{person:true}}`.
- Flags are exposed on the build status as `roof_flags: [{block_rect, text}]`, and in the plan as `building['roof']['flags']`.

- [ ] **Step 1 (Claude): write the failing tests.**
  - `test_card_edit_becomes_choice`: an edit sets a derived section's kind to hip; the next rebuild keeps hip and the person's pitch. This is Review Focus 3.
  - `test_old_person_sections_migrate`: Review Focus 5.
  - `test_choice_clears_flag`: a choice on a flagged block removes its flag.
  - Node: a flagged block's roof gets the needs-checking marker, and a click selects that roof.
  - Live: after a stubbed build with one flag, the panel shows the plain flag line, and clicking the marker opens the roof card.
- [ ] **Step 2:** run them. Expected: FAIL.
- [ ] **Step 3 (Codex):** implement it.
- [ ] **Step 4:** run them, plus `test_twin_edit.py`, `test_twin_build_draft_rebuild.py`, `test_twin_build_draft_migration.py` and live `test_house_editor_live.py`. Expected: PASS.
- [ ] **Step 5:** commit with `feat(twin): your roof choices stick, and unsure roofs are marked for a look`.

### Task 7: Recording, replay, acceptance and ship

**Files:**
- Create: `chauffeur/tests/fixtures/twin_reads/recorded/claude/photo_map-main-house-<n>.json` and `roof_observe-main-house.json`. They are recorded once from photos 22, 26, 23 and 20, and key-checked.
- Create: `chauffeur/tests/test_twin_build_roof_blocks_replay.py`.
- Modify: `chauffeur/system_capabilities.md` and `chauffeur/config.yaml`.

- [ ] **Step 1 (Claude):** record the reads three times, within $1, using the acceptance-script pattern in scratchpad `accept/` with photos 22, 26, 23 and 20 tagged to the main house. Keep one set as the fixtures and use the other two for the determinism check.
- [ ] **Step 2 (Claude):** write the replay test. With the recorded answers, every ground-truth line holds, the three recordings derive identical forms, and `roof_issues` is empty for the main roof.
- [ ] **Step 3 (Codex):** fix whatever fails, within this plan's interfaces.
- [ ] **Step 4 (Claude): local acceptance.** Run a real build of both buildings, under $5, rendered from four sides. Compare it with photos 22, 26, 23 and 20, and with the pool house photo 25.
- [ ] **Step 5 (Claude): ship.** Then:
  1. run the final whole-branch review and one fix wave;
  2. update the capabilities entry;
  3. bump to the next version;
  4. commit and push;
  5. update the memory arc.
