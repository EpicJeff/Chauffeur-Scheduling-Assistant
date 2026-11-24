# Awnings, landings 0 to 2: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an awning an ordinary roof with a support setting: independent of walls, migrated from today's `awning` extensions with the same look, and selectable, editable and deletable by hand and by the agent, with straight brackets, corbels, braces, cables and posts.

**Architecture:** A roof record gains optional fields (`support`, `host`, `thickness`, `fascia`). A single predicate, `isSupported`, exists in JS and Python. The generator computes the walled envelope exactly as today, and builds supported roofs in their own group. Support shapes come from one new module, `roof_supports.js`. Later plans cover ends, underside and devices (3), slats (4), placing and copying (5).

**Tech Stack:** FastAPI + Python services, three.js r187, node-driven tests, Playwright Chromium.

**Spec:** docs/superpowers/specs/2026-11-24-awnings-as-roofs-design.md (owner approved 2026-11-24). Worktree `E:\repositories\Chauffeur-awnings`, branch `awnings`.

## Global Constraints

- Walled roofs and their walls, gables and trim are byte-identical before and after (golden hash, Task 1).
- 0 new samplers, 0 new programs, 0 new draws for existing materials. Supports are static and merged into the building meshes.
- Costs (triangles, draws, programs, samplers, build ms) are reported before any look review.
- No generated-only piece kinds or behaviour: every agent operation has a hand path.
- No browser dialogs (`alert`, `confirm`, `prompt`); use `showGlobalAlert`, `promptConfirm`, `promptInput`.
- Implementers never commit, never bump `chauffeur/config.yaml`, and never edit the main folder.
- Tests run from `chauffeur/` as `python tests/<file>` with `HA_BASE_URL` unset, using `E:\repositories\Chauffeur\venv\Scripts\python.exe`.
- The owner's export is read only by path (`C:\Users\ffejn\Downloads\Current house.chauffeur-house-11-20-2016.json`); its contents are never copied.
- Old saves, undo history and exports with `awning` extensions must keep opening.

## Shared names (contract)

JavaScript, new `chauffeur/static/twin/roof_supports.js`:

```js
export const SUPPORT_KINDS = ['walls', 'bracket', 'corbel', 'brace', 'cable', 'post'];
export function isSupported(section)            // section.support?.kind is set and not 'walls'
export function supportPoints(roof)             // -> [{ id, edge, u, at:[x,y] }], outer edge in order
export function supportGeometry(roof, points, { groundAt, wallTopAt })  // -> [{ geometry, slot, part }]
```

Python, new `chauffeur/services/twin_model_supports.py`: `SUPPORT_KINDS` (same strings), `is_supported(roof)`, `normalize_support(roof, notes)`, `support_points(roof)` (same order and values as JS, parity tested).

Stored fields on a `roofs` record, all optional:

- `support: {kind, count, inset_ft, spacing_ft, size_ft, style, at: {<index>: [x, y]}}`
- `host: {wall, edge}`, `thickness_ft`, `fascia: bool`

Automatic placement, the same as today's brackets: along the outer edge of width `w`, with `inset = min(inset_ft ?? 0.6, w / 2)` and index `i` of `count`, the position is `inset + i * (w - 2 * inset) / max(1, count - 1)` from its start. `at[i]` overrides a position. Defaults: bracket, corbel, brace `count 2`; cable `count 2`; post `count 2`.

## Review Focus

- A house with no supported roof, opened and re-saved: the model round-trips with no new fields, and the drawn hash is unchanged.
- A walled roof directly above an awning: the wall, its gable and the awning all keep their own shapes.
- An old save with an awning that has no wall, or a wall deleted later: opens, keeps the awning, and shows a flag instead of failing.
- Undo of an awning edit after the migration: returns to the migrated state with one step, and a reload keeps it.
- Deleting the last wall an awning hangs from: the awning stays, flagged, and still draws.

Each line is pinned by a test in Tasks 1, 2, 4 and 6 below.

---

### Task 1: Grouped envelope (landing 0)

**Implementer:** Codex. **Files:**
- Modify: `chauffeur/static/twin/twin_generator.js` (1075, 1119-1129, 1555, 1567-1640), `chauffeur/static/twin/twin_roof.js` (324 `roofMesh`)
- Create: `chauffeur/static/twin/roof_supports.js` (only `SUPPORT_KINDS`, `isSupported`)
- Test: `chauffeur/tests/test_twin_awning_golden_js.py`

**Interfaces:**
- Produces: `isSupported(section)`; `roofEnvelope(sections, options)` in `twin_roof.js` returning `{ walled, supported }`, each the same shape `roofMesh` returns today, with `walled` identical to `roofMesh(walledSections, options)`.

- [ ] **Step 1: Write the golden test.** Load the generator from git at `0ec59a62` (pattern in `test_twin_untouched_house_js.py` `baseline_sources`), build the household fixture and, when `--owner-export PATH` is given, the owner plan, and hash every mesh's name, material key, position, index and uv. Assertions:

```python
assert result['walled_hash'] == baseline['walled_hash']       # every mesh except awnings
assert result['sections_supported'] == 0                      # no supported roof exists yet
assert result['draws'] == baseline['draws'] and result['triangles'] == baseline['triangles']
```

- [ ] **Step 2: Run it.** `python tests/test_twin_awning_golden_js.py` — Expected: FAIL `ERR_MODULE_NOT_FOUND roof_supports.js`.
- [ ] **Step 3: Implement** `isSupported(section)` and `roofEnvelope(sections, options)`, and replace the generator's `envelope`, `roofLayers`, `visibleRoof` and `storeyRoofs` calls with it. Supported sections are passed through but always empty in this task; each supported group is built by `roofMesh(supportedSections, options)` and never merged into walled data.
- [ ] **Step 4: Run** the golden test (and with `--owner-export`), `test_twin_untouched_house_js.py`, `test_twin_roof_js.py`, `test_twin_roof_derive.py`, `test_twin_gutters_js.py`, `test_twin_bake_atlas_js.py`. Expected: all pass; golden hash equal.
- [ ] **Step 5: Report** (`.superpowers/sdd/awnings/task-1-report.md`): hash evidence, build ms before and after, files changed.

### Task 2: Record and normalisation

**Implementer:** Codex. **Files:**
- Create: `chauffeur/services/twin_model_supports.py`
- Modify: `chauffeur/services/twin_model.py` (429-443), `services/twin_model_roofs.py` (22-60, 152-188, 201-240), `services/twin_plan.py` (293-341), `services/twin_model_bridge.py` (372-440, 911-925), `services/twin_model_ops.py` (1319-1327, 811-826), `services/twin_edit.py` (437, 718), `services/twin_build.py` (913, 2227), `services/twin_joints.py` (221, 552)
- Test: `chauffeur/tests/test_twin_awning_model.py`

**Interfaces:**
- Consumes: `isSupported` semantics from Task 1.
- Produces: the Python contract above.

- [ ] **Step 1: Write the failing tests:**

```python
def test_support_fields_round_trip():            # support, host, thickness_ft, fascia survive normalize, flatten, from_section, save and reload
def test_invalid_support_is_coerced_with_a_note():  # bad kind -> removed; out-of-range size -> default
def test_walled_roof_has_no_new_fields():        # a house without support re-saves byte-identical
def test_dormers_inherit_support_flag():
def test_deleted_host_wall_keeps_roof_and_flags(): # roof stays, host cleared, a flag names the roof
def test_parity_with_js():                       # support_points(roof) == node supportPoints(roof), 12 cases
```

- [ ] **Step 2: Run** `python tests/test_twin_awning_model.py`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the Python module and the validation and persistence changes named above. The edge-field drop in `from_section` is fixed by keeping every edge field except `gutters`, `downspouts`, `setting`, `pitch` keys already handled. `attach_edges` on a supported roof records `host` and moves the whole area.
- [ ] **Step 4: Run** the test and the neighbours `test_twin_model.py`, `test_twin_model_roofs.py`, `test_twin_model_bridge.py`, `test_twin_model_ops_more.py`, `test_twin_plan.py` if present, `test_twin_build_replay.py`, `test_twin_joints.py` if present. Expected: PASS.
- [ ] **Step 5: Report.**

### Task 3: Walls and ceilings ignore supported roofs

**Implementer:** Codex. **Files:** Modify `static/twin/twin_generator.js` (1108-1130, 1474-1484, 1654-1667, 1699-1749, 1714, 1845, 1952, 1983, 2098, 1119), `static/twin/twin_roof.js` (187, 244), `static/twin/gutters.js` (537, 254, 261), `static/twin/twin_ground.js` (75), `services/twin_roof_issues.py` (140-172), `services/twin_build.py` (1358-1369, 2178-2243), `services/twin_solar.py` (272, 390), `services/twin_joints.py` (221-262, 552-584). Test: `chauffeur/tests/test_twin_awning_independence_js.py` and `chauffeur/tests/test_twin_awning_model.py`.

**Interfaces:** Consumes `isSupported`, `roofEnvelope`.

- [ ] **Step 1: Write the failing tests** (node, on a two-storey fixture with an awning against a wall, one under a higher roof, and one free-standing on posts):

```js
assert.deepEqual(wallProfiles(withAwning), wallProfiles(without));   // every wall top, gable fill and step face
assert.equal(ceilingCount(withAwning), ceilingCount(without));
assert.equal(porchPostTop(withAwning), porchPostTop(without));
assert.ok(awningMesh(withAwning));                                   // and it draws
```

- [ ] **Step 2: Run.** Expected: FAIL (walls rise to the awning).
- [ ] **Step 3: Implement** by filtering `isSupported` sections at each listed line. `Math.max` heights take the lowest roof above the floor. A supported roof is cut by every floor outline, not only outlines above it.
- [ ] **Step 4: Run** the tests, Task 1's golden test and its owner export, `test_twin_gutters_js.py`, `test_twin_gutter_geometry_js.py`, `test_twin_eave_streams_js.py`, `test_twin_solar*` tests. Expected: PASS, golden hash unchanged.
- [ ] **Step 5: Report.**

### Task 4: Migration

**Implementer:** Codex. **Files:** Create `chauffeur/services/twin_awning_migration.py`; modify `services/twin_model.py` (load path), `services/twin_model_bridge.py` (911-930), `static/twin/twin_generator.js` (remove 1764-1821, extensions kind awning), `static/twin/gutters.js` (261-330), `static/twin/editor/scene_tree.js` (45-46, 210), `static/twin/editor/cards.js` (269), `services/twin_reads.py` (610), `services/twin_draft.py` (41). Test: `chauffeur/tests/test_twin_awning_migration.py`.

**Interfaces:** Consumes Task 2 fields. Produces `migrate_awnings(model) -> (model, notes)`, idempotent.

- [ ] **Step 1: Write the failing tests:**

```python
def test_awning_becomes_a_bracket_roof():     # id, span, depth, pitch, eave (plate), gutter, bracket count kept; thickness_ft 0.3; fascia False
def test_missing_wall_is_resolved_or_flagged():  # same wall the renderer chooses today; none -> flag, roof still draws
def test_is_idempotent_and_old_saves_open():  # load old save -> migrated -> save -> load -> same
def test_undo_returns_to_the_migrated_state()
def test_shed_continuation_becomes_a_shed_roof()
def test_owner_export_counts(): # with --owner-export only: 2 awnings -> 2 supported roofs, 0 awning extensions
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** A supported roof's plane is the plane of today's awning: eave at `aw.eave`, rising to the wall by `depth * pitch / 12`. Drawing with `fascia: false` and `thickness_ft: 0.3` reproduces today's slab, seams, and brackets (bracket box 0.3 x 0.3, `run = min(3, depth * 0.8)`, `rise = run * 2.6 / 3`).
- [ ] **Step 4: Run** the tests, Task 1's golden (walled hash unchanged), `test_twin_gutters_js.py`, `test_twin_gutters_live.py` (Chromium, Claude runs), `test_twin_eave_streams_js.py`. Expected: PASS. Any visible difference from today's awnings is shown as a side-by-side, not described.
- [ ] **Step 5: Report.**

### Task 5: Operations, editor and agent

**Implementer:** Codex (operations, agent text), Claude (editor review). **Files:** Modify `services/twin_model_ops.py` (MORE_OPS 829, 1493-1540 dispatch, 1639 words), `services/agent_tools_v2.py` (7749-7757, 9643), `static/twin/editor/cards.js`, `scene_tools.js` (325-364), `handles.js` (91-175, 369-377), `gizmo.js` (36-52), `selection_bounds.js`, `roof_tools.js`, `clipboard.js` (119 unchanged here), `scene_tree.js`. Test: `chauffeur/tests/test_twin_awning_ops.py`, `chauffeur/tests/test_twin_awning_editor_js.py`.

**Interfaces:** Produces op `set_roof_support {building, id, support?, host?, thickness_ft?, fascia?, at?}`; existing `draw_roof`, `set_roof_edge`, `move_roof_edge`, `delete` accept supported roofs; `move_roof {building, id, by:[x,y]}` moves the whole roof (new, hand and agent).

- [ ] **Step 1: Write the failing tests:**

```python
def test_set_support_changes_only_named_fields()      # and one undo step restores all
def test_move_roof_moves_area_and_supports_together()
def test_delete_supported_roof_removes_it()           # and nothing else
def test_agent_can_do_everything_the_editor_can()     # every op name documented, same validation
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** ops first, then the card (support kind, count, inset, size, style, thickness, fascia, host), the 3D pick proxy for roof triangles and supports, the handles (ends, depth, outline, support points, height), hide, lock and scene-tree label "Awning". No dialogs. Same selection path as other roofs.
- [ ] **Step 4: Run** the tests, `test_twin_roof_tools_js.py`, `test_twin_gutters_editor_js.py`, `test_house_editor_live.py` (Claude, Chromium). Expected: PASS.
- [ ] **Step 5: Report.**

### Task 6: Support shapes

**Implementer:** Gemini. **Files:** Modify `chauffeur/static/twin/roof_supports.js` (`supportPoints`, `supportGeometry`), `static/twin/twin_generator.js` (the one call site after each supported roof's slab). Test: `chauffeur/tests/test_twin_awning_supports_js.py`; look captures in `.gemini-tmp/shots/awnings/`.

**Interfaces:** Produces `supportPoints(roof)`, `supportGeometry(roof, points, { groundAt, wallTopAt }) -> [{ geometry, slot, part }]`. Slots: `support` (new surface kind, fallback `trim`), existing `column` for posts. Parts are named `support:<index>` so a support can be picked.

- [ ] **Step 1: Write the failing tests:**

```js
assert.equal(supportPoints(awning).length, 2);               // automatic placement matches the contract formula
assert.deepEqual(supportPoints(override).map(p => p.at), [[0,0],[6,0]]);  // at overrides
for (const kind of ['bracket','corbel','brace','cable','post']) {
  const parts = supportGeometry(awning(kind), points, ctx);
  assert.ok(parts.every(p => triangles(p.geometry) <= 400));  // bracket 12, post 24, cable 24, brace 60, corbel 400
  assert.ok(parts.every(p => !hasNaN(p.geometry)));
  assert.ok(parts.length === 2 && parts.every(p => p.part === 'support:0' || p.part === 'support:1'));
}
assert.deepEqual(supportGeometry(awning('bracket'), p, ctx), todaysBracketGeometry);  // pixel-identical to today's
```

- [ ] **Step 2: Run.** Expected: FAIL (undefined).
- [ ] **Step 3: Implement.** Shapes are plain box and prism geometry with one profile curve for corbels (`style` 'scroll' or 'plain'), a triangular `brace`, a straight bar with end plates for `cable`, and a square post with a base. `bracket` is today's box, unchanged.
- [ ] **Step 4: Run** the tests and report costs: triangles per shape, the owner's house total before and after, draws, programs, samplers, build ms.
- [ ] **Step 5: Look captures** (Chromium, fixed cameras: default overview, pool house, garage side, day and night, High and Low), compare against the four reference photos in `C:\Users\ffejn\.claude\projects\e--repositories-Chauffeur\memory\awning-refs\`, and report each shape with one line and the before and after.

### Task 7: Material slots and the patio

**Implementer:** Codex. **Files:** Modify `services/twin_surface_kinds.py` (KINDS, parity with `static/twin/surface_kinds.js`), `services/twin_model_ops.py` (`set_material` on a roof support, `move_posts_to_roof`), `static/twin/editor/cards.js` (porch card action "Move posts to the roof", `promptConfirm` with a before and after preview line). Test: `chauffeur/tests/test_twin_awning_materials.py`, `test_twin_surface_kinds.py` (parity).

**Interfaces:** Produces the `support` kind, usable per roof through `materials: {support: <ref>}`; op `move_posts_to_roof {building, porch, roof}`, one undo step, inverse by undo only.

- [ ] **Step 1: Write the failing tests:**

```python
def test_support_material_inherits_trim_then_overrides()
def test_move_posts_to_roof_keeps_the_floor()      # porch room unchanged; the roof gets support post with the same 2 positions; the porch record has no columns
def test_undo_puts_the_posts_back()
def test_the_action_is_offered_only_for_a_porch_under_a_supported_or_shed_roof()
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** The action never runs automatically. It is refused, with the reason, when the porch has no columns or no roof overlaps it.
- [ ] **Step 4: Run** the tests, `test_twin_surface_kinds.py`, `test_twin_model_ops_more.py`. Expected: PASS.
- [ ] **Step 5: Report.**

### Task 8: Release check (Claude)

- [ ] **Step 1:** Run the golden test with the owner export, and the fixed captures before and after (default overview, pool house, garage side, focused room, day and night, High and Low). Expected: walled hash equal; awnings look the same.
- [ ] **Step 2:** Report costs from Tasks 1 to 7 before any look review; then send the owner side-by-sides: each awning type, the patio before and after, and the two migrated awnings.
- [ ] **Step 3:** Independent whole-branch review (most capable model), then merge main, bump, capabilities entry, land, and note that one rebake is needed.
