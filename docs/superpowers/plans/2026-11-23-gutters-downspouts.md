# Gutters and downspouts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eave edges, porch roofs and awnings can have gutters that stop eave streams. Gutters drain into downspouts placed automatically on outside corners and adjustable by a person, and in rain each downspout pours its share of the runoff.

**Architecture:**
- Authored per-edge flags (`gutter`, `downspouts`) are mirrored onto flattened sections.
- One pure module, `static/twin/gutters.js`, turns the plan into gutter runs and downspout placements. The generator, the stream system and the editor all read it.
- Geometry merges into the existing roof/wall batches; downspout pours reuse the eave-stream material.

**Tech Stack:** Python (FastAPI services, model ops, validation), vanilla JS ES modules with three.js r187, node-run JS tests, Playwright Chromium tests.

**Spec:** `docs/superpowers/specs/2026-11-23-gutters-downspouts-design.md` (owner-approved 2026-11-23). Its "The owner's real house" section overrides earlier placement rules.

## Global Constraints

- Paths are relative to `chauffeur/`. Tests run from `chauffeur/` with `HA_BASE_URL` unset; never the whole suite.
- Gutters are off by default. Existing houses render byte-identical geometry until a gutter is enabled.
- Downspouts go on outside (convex) corners only, never inner corners, and never mid-run.
- Count: one per started 35 ft of run. Longer runs use more of the run's outside corners.
- Landing preference: grass or `site.beds`, then a driveway. Never a walkway, path, patio step, porch step or deck stair. If a corner's outlet would land on a walkway, the kick-out turns along the wall toward the nearest grass or bed (up to 4 ft).
- Mounting: an exterior wall or porch post within overhang + 1 ft of the gutter back line. Overhangs up to 4 ft get a horizontal leader under the soffit.
- Never over an opening (door, window, slider, garage) on any level the downspout passes, ±1 ft. Avoid ends within 6 ft of an exterior door.
- `edges[i].downspouts` holds fractions 0..1 along authored edge i, from its first vertex; at most 8 per edge.
- Rake edges (gable/clip) cannot have gutters.
- Geometry: 5 in K-style gutter, 2×3 in downspout, two 45° offset elbows, 3 ft kick-out. Surface kind `gutter`, defaulting to the trim/fascia finish.
- Bump `BAKE_GENERATOR_VERSION` (static/twin/bake/key_inputs.js) to `gutters-1`.
- Placement is plan-only and deterministic.
- Every agent capability has a hand path. No browser dialogs. Implementers do not commit or bump.

## Review Focus

1. **A roof with no gutters must render exactly as before.** Same triangles and same bake key, apart from the generator version stamp. Test in Task 3.
2. **A guttered L-shaped house.** The inner corner of the L gets no downspout; each outer corner of the runs does. Test in Task 2.
3. **A downspout whose wall has a door near its corner.** The corner is still used if the door is more than 1 ft away; if the door is within 1 ft, the downspout slides to the next outside corner. Test in Task 2.
4. **Editing the roof after dragging a downspout.** Moving an edge keeps the downspout at the same fraction; deleting an area vertex remaps the overrides like `plane_materials`, or drops those on the deleted edge. Test in Task 1.
5. **Second-storey gutter above a ground-floor window.** The downspout path is checked against openings on every level it passes. Test in Task 2.

## Split (said before code)

- **Codex:** Tasks 1, 2 and 4 (data/ops, placement module, editor + Argyle), in the `gutters` worktree.
- **Gemini, through `agy_run.py`:** Task 3 (geometry, surface kind, stream suppression, downspout pours), in a second worktree `E:\repositories\Chauffeur-gutters-g`, branch `gutters-g`, created from `gutters` after Task 2 lands.
- **Contract-first:** the `gutters.js` output shape below is fixed before Task 3 starts.
- **Claude:** reviews every task, runs the Chromium checks, does Task 5 (look and acceptance against the owner's house), and lands.

## Shared contract (fixed now; Tasks 2-4 must match exactly)

```js
// static/twin/gutters.js
export const GUTTER = { runJoinFt: 0.3, runJoinHeightIn: 2, spanFt: 35, maxOverhangFt: 4,
  openingClearFt: 1, doorAvoidFt: 6, kickOutFt: 3, kickTurnFt: 4, profileIn: 5, spoutIn: [2, 3] };
// Pure: plan in, data out. Units: feet, building-local plan coordinates plus world metres where noted.
export function gutterRuns(plan, roofs /* Map<buildingId,{sections,eaveAttachments}> or null */) -> [{
  id: string,                   // stable: `${buildingId}:${roofId}:${firstEdgeIndex}` or `${buildingId}:porch:${porchId}`
  building: string,
  segments: [{ roof: string|null, edge: number|null, porch: string|null, a: [x,y,z], b: [x,y,z], outward: [dx,dy] }],  // world metres a,b; plan outward unit
  length: number,               // ft
  corners: [{ at: [x,y,z], convex: boolean, segIndex: number }],
}];
export function downspouts(plan, runs) -> [{
  id: string,                   // `${runId}:${k}`
  run: string,
  edge: { roof: string|null, edge: number|null, porch: string|null, fraction: number },
  top: [x,y,z],                 // outlet under the gutter, world metres
  mount: 'wall' | 'post' | 'hang',
  path: [[x,y,z], ...],         // centreline from outlet to outlet end, world metres
  outlet: { at: [x,y,z], dir: [dx,0,dz], lands: 'grass'|'bed'|'driveway'|'roof'|'deck'|'hard' },
  share: number,                // 0..1 fraction of the run's catchment
  source: 'auto' | 'override',
  flags: string[],              // e.g. ['no-outside-corner']
}];
```

---

### Task 1: Data, validation, ops, section mirror (Codex)

**Files:**
- Modify:
  - `services/twin_model.py:433-438` (edge validation: `gutter` bool; `downspouts` list of ≤8 numbers in [0,1]);
  - `services/twin_model_ops.py:1506-1538` (`set_roof_edge` accepts `gutter` and/or `downspouts` without `setting`, and refuses `gutter` on gable/clip edges);
  - the area-vertex insert/delete ops that remap `plane_materials` (find them), so they remap `gutter`/`downspouts` the same way;
  - `services/twin_model_roofs.py` `to_sections` (mirror `gutters{side:true}` and `downspouts{side:[fractions]}` through `plane_edges`);
  - `services/twin_plan.py:234-275` (whitelist and validate the section fields);
  - porch and awning records: a `gutter` bool, with the porch and item update ops accepting it.
- Test: `tests/test_twin_gutters_model.py` (new).

**Interfaces:**
- Produces: plan fields consumed by Tasks 2-4:
  - `building.roofs[].edges[i].gutter`;
  - `building.roofs[].edges[i].downspouts`;
  - `roof.sections[].gutters`;
  - `roof.sections[].downspouts`;
  - `porches_detail[].gutter` (or the porch record the generator reads; name it in the report);
  - an awning item's `gutter`.

- [ ] **Step 1: Write the failing tests:**
  - `test_set_roof_edge_gutter_only` (no `setting`; persists);
  - `test_gutter_refused_on_gable_edge`;
  - `test_downspouts_validated` (fractions in [0,1], at most 8, numbers only);
  - `test_sections_mirror_gutters_and_downspouts`;
  - `test_move_edge_keeps_fractions`;
  - `test_vertex_delete_remaps_like_plane_materials`;
  - `test_batch_all_eaves_is_one_round`;
  - `test_porch_and_awning_gutter_flags`;
  - `test_no_gutters_plan_unchanged` (flattened sections are identical to before when no flag is set).
- [ ] **Step 2:** Run `python tests/test_twin_gutters_model.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the new test plus `tests/test_twin_model_ops.py` (or the existing roof-op tests; name them in the report), `tests/test_house_design_tool.py` and `tests/test_twin_plan.py`. Expected: pass.
- [ ] **Step 5:** Claude commits: `feat(twin): gutter and downspout data on roof edges, porches and awnings`.

### Task 2: Runs and downspout placement (Codex)

**Files:**
- Create: `static/twin/gutters.js` (the shared contract above).
- Modify: `static/twin/sky/eave_streams.js` (carry `side`/`edge` on eave records; export `extractEaves` and `createEaveLandingSampler` for reuse without behaviour change).
- Test: `tests/test_twin_gutters_js.py` (node, synthetic plans).

**Interfaces:**
- Consumes: Task 1 fields; `extractEaves`, `clipExposedEdges`, `createEaveLandingSampler` (eave_streams.js); walls, openings, `allPorches`, `collectHardSurfaces` (sky/precipitation.js), `site.beds`, `groundAt`.
- Produces: `GUTTER`, `gutterRuns`, `downspouts`, exactly as in the contract.

- [ ] **Step 1: Write the failing tests:**
  - `test_rectangle_gable_two_runs_four_outside_corners` (each 30 ft run gets 1 downspout, on an outside corner);
  - `test_long_run_uses_both_outside_corners` (40 ft gets 2, at both ends);
  - `test_L_house_inner_corner_never_used`;
  - `test_run_with_no_outside_corner_uses_non_inner_end_and_flags`;
  - `test_opening_within_1ft_slides_to_next_outside_corner`;
  - `test_second_storey_checks_all_levels_below`;
  - `test_walkway_landing_turns_kickout_toward_grass` (≤ 4 ft);
  - `test_driveway_allowed_after_grass_and_beds`;
  - `test_porch_run_comes_down_a_post`;
  - `test_upper_roof_downspout_ends_on_lower_roof` (`lands: 'roof'`);
  - `test_deep_overhang_gets_leader` (3.5 ft is ok; 4.5 ft gives `mount: 'hang'` plus a flag);
  - `test_overrides_replace_auto_for_that_edge` (fractions snap to the nearest exposed mountable point);
  - `test_deterministic` (same plan, deep-equal output);
  - `test_door_avoidance_tiebreak` (6 ft).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Placement: candidates are the run's convex corners whose mounting test passes. Choose `ceil(length/35)` of them by priority:
  1. landing grass or bed;
  2. no door within 6 ft;
  3. nearer a house corner;
  4. lower edge index.

  Interior points are never used.
- [ ] **Step 4:** Run. Expected: pass. Also run `tests/test_twin_eave_streams_js.py` (no behaviour change).
- [ ] **Step 5:** Claude commits: `feat(twin): gutter runs and outside-corner downspout placement`.

### Task 3: Geometry, surface kind, streams and pours (Gemini via agy_run.py)

**Files:**
- Modify:
  - `static/twin/twin_generator.js` (gutter and downspout meshes next to the fascia loop :1226-1248, merged with the roof/wall batches);
  - `services/twin_surface_kinds.py`, `static/twin/surface_kinds.js` and `static/twin/editor/house_materials.js` (`gutter` kind in the Trim group);
  - `static/twin/bake/key_inputs.js` (`BAKE_GENERATOR_VERSION='gutters-1'`);
  - `static/twin/sky/eave_streams.js` (drop guttered segments; add downspout pour instances).
- Test: `tests/test_twin_gutter_geometry_js.py` (node), `tests/test_twin_gutters_live.py` (Chromium; Gemini can run it).

**Interfaces:**
- Consumes: `gutterRuns`, `downspouts` (contract); `eaveRunoff` (sky/roof_water.js).
- Produces: meshes tagged `userData.surfaceKind='gutter'`; pour instances driven by the same `eaveFlow` uniform, each scaled by `share`.

- [ ] **Step 1: Write the failing tests:**
  - `test_no_gutters_identical_geometry` (triangle count and position hash equal to main for the household fixture);
  - `test_gutter_follows_run_with_mitres_and_end_caps`;
  - `test_downspout_path_and_kickout` (offset elbows, 3 ft kick-out along `outlet.dir`);
  - `test_surface_kind_defaults_to_trim`;
  - `test_guttered_edges_shed_no_streams`;
  - `test_pours_follow_runoff_and_share` (no pour at `eaveRunoff` 0; scales with `share`);
  - `test_generator_version_bumped`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run, plus `tests/test_twin_surface_kinds.py`, `tests/test_twin_eave_streams_js.py` and `tests/test_twin_texture_units_live.py`. Report the costs first: triangles and draws on the owner's house with gutters on all eaves, against main.
- [ ] **Step 5:** Claude commits: `feat(twin): gutter and downspout geometry; downspouts pour, guttered eaves do not`.

### Task 4: Editor and Argyle (Codex)

**Files:**
- Modify:
  - `static/twin/editor/cards.js:405-440` (`drawEdge`: a Gutter toggle on eave edges only); the roof card ("Gutters on all eaves", "Remove all gutters": one `batch`, one undo);
  - `static/twin/editor/handles.js` (downspout handles on guttered roofs: drag along the run to write fractions; right-click to remove; "Add downspout" and "Reset to automatic" on the run's card);
  - porch and awning cards (a Gutter toggle);
  - the Check list (runs flagged `no-outside-corner` or `hang`);
  - `services/agent_tools_v2.py:7750` (document `gutter`/`downspouts` on `set_roof_edge`, and the porch/awning flag).
- Test: `tests/test_twin_gutters_editor_js.py` (node), `tests/test_house_editor_gutters_live.py` (Chromium; Claude runs it).

**Interfaces:**
- Consumes: Task 1 ops; Task 2 `downspouts()` for handle positions.

- [ ] **Step 1: Write the failing tests:**
  - `test_gutter_toggle_only_on_eave_edges`;
  - `test_all_eaves_is_one_batch`;
  - `test_drag_writes_fraction_override`;
  - `test_reset_clears_override`;
  - `test_check_list_flags_hanging_runs`;
  - Chromium `scenario_enable_gutters_drag_downspout_undo`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Follow `docs/ui_design_guide.md`; no browser dialogs; coerce Alpine `:disabled` with `!!`.
- [ ] **Step 4:** Claude runs the tests and the editor neighbours (roof card, handles). Expected: pass.
- [ ] **Step 5:** Claude commits: `feat(editor): gutter toggles, downspout handles, Argyle gutter edits`.

### Task 5: Acceptance on the owner's house, then land (Claude)

- [ ] **Step 1: Acceptance.** Enable gutters on all eaves of the owner's export (`C:\Users\ffejn\Downloads\Current house.chauffeur-house-11-20-2016.json`, passed by path). Assert:
  - every downspout is on an outside corner;
  - none is on an inner corner;
  - every outlet lands on grass, a bed or the driveway;
  - no downspout crosses an opening.

  List any flagged runs.
- [ ] **Step 2: Costs.** Triangles and draws against main, plus bake time for one rebake.
- [ ] **Step 3: Look.** Captures in heavy rain:
  - the default overview;
  - a building-focused view;
  - close-ups of a corner downspout, a porch-post downspout and a pour;
  - an unguttered edge still streaming.

  Send them to the owner.
- [ ] **Step 4: Land** under AGENTS.md:
  1. merge main;
  2. run the gates (Tasks 1-4 tests, `test_twin_eave_streams_js`, `test_twin_bake_fingerprint_js`, `test_twin_surface_kinds`);
  3. bump the version;
  4. add the capabilities entry;
  5. fast-forward main and push.
