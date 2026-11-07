# House editor, slice 1: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking. This repo's split (memory `codex-coordination`): Claude writes each task's tests first, Codex implements, Claude reviews, gates, documents, bumps and commits. Codex never commits and never bumps `config.yaml` (AGENTS.md).

**Goal:** A full-screen, agent-driven 3D house editor at `/house/editor` that builds the user's main house piece by piece from their drawing sheets, with ghosts that settle and three pauses, and then the pool house. A parent can fix anything by talking to Argyle or by hand. It replaces P0's one-shot draft and its parent tools sheet.

**Architecture:**
- **Server side:** a step engine (`services/twin_build.py`) runs small metered model reads (`services/twin_reads.py`) on cropped regions of high-resolution sheet masters. It maps their coordinates into one building frame through per-sheet registrations (`services/twin_register.py`) and merges pieces into the current plan through one locked update. Hand edits (`services/twin_edit.py`) and Argyle's `house_design` tool share the same edit operations.
- **Browser side:** the editor (`static/twin/editor/`) reuses P0's `mountTwin`, extended with roof sections (`static/twin/twin_roof.js`), building rotation, ghosts and picking. It polls build status and posts edits.

**Tech stack:** FastAPI and Jinja (`chauffeur/main.py`, `templates/`), Python services, three.js r187 (vendored), plain ES modules (no Alpine on this page), pypdfium2 and Pillow (already installed via `requirements-twin.txt`), Playwright for live tests, node for pure JS module tests.

**Spec:** `docs/superpowers/specs/2026-11-07-house-editor-design.md`. It amends `docs/superpowers/specs/2026-11-06-house-digital-twin-design.md`; read both. Mockup screenshot: `docs/superpowers/plans/assets/2026-11-07-house-editor-mockup.png`.

## Global Constraints

- **Running tests:** run from `chauffeur/` as plain scripts, `python tests/test_x.py`, with `HA_BASE_URL` unset. Run the task's own tests plus the neighbours it names, never the whole suite.
- **Critical paths:** every critical path has a test that actually runs it (TestClient request, node run of the JS, or Playwright), because entry points swallow exceptions.
- **Dialogs:** no `alert`, `confirm` or `prompt`. Use `showGlobalAlert`, `promptConfirm` and `promptInput` from `templates/components/control_center.html`.
- **Fetches:** page JS fetches `base() + 'api/...'`, never root-relative (HA ingress).
- **Routes:** every new route gets a rule in `services/auth.py`. The editor APIs are `PARENTS`; the editor page is `(ANY, '/house/editor', ANYONE, None)`, the same as `/house/twin`.
- **Materials:** no material anywhere uses `transmission` (memory `house-render-headroom`).
- **Packages:** no new Python packages in `requirements.txt`. If one is unavoidable it goes in `requirements-twin.txt`.
- **Home Assistant:** every HA touchpoint (area names for rooms) degrades to empty with no HA present.
- **Spend:**
  - Stops at **$10, $20, $30 and $40** need a parent's Continue; the **hard stop is $50** (`services/twin_cost.py` CHECKPOINTS / HARD_STOP, unchanged).
  - The $50 covers all development and the acceptance run (user, 2026-11-07).
  - No test makes a live model call: tests replay recorded answers from `tests/fixtures/twin_reads/`.
  - Live reads during development go only through `tools/twin_live.py` (Task 12) with an explicit `--budget`. Every hand-off reports the local ledger total. The household ledger showed **$7.48** at plan time.
- **Copy:** person-readable text never says "mesh", "extrude", "gizmo" or "vertex". Lengths display as feet-inches (`70'-0"`).
- **Interaction:**
  - Dragging always slides along the floor or ground. Heights, pitches and elevations are numbers on a card.
  - Walls snap to walls and to right angles.
- **Agent parity:** every `house_design` action Argyle can take has a hand path in the editor, and vice versa (repo rule).
- **Page CSS:** the editor uses its own stylesheet `static/twin/editor/editor.css`. If any template uses Tailwind classes, run `python tools/build_tailwind.py`.
- **Nothing a person can do disappears without a replacement.** P0's tools sheet is retired only in Task 18, after the editor covers each of its actions.

## Review Focus

Most likely to bite first. Each line has its test in the owning task.

1. **A read returns coordinates outside the crop, or nonsense.** The piece stays a ghost with a plain reason and the build continues; nothing crashes (Task 8, `scenario_out_of_crop_read_stays_a_ghost`).
2. **The tab closes or the add-on restarts mid-build.** The build resumes from cached step answers without paying again (Task 8, `scenario_restart_resumes_without_repaying`).
3. **A spend checkpoint is reached mid-build.** The build stops in state `checkpoint`, and Continue resumes at the same step (Task 8, `scenario_checkpoint_stops_and_resumes`).
4. **A person edits while a step is running.** The step's merge never overwrites a piece a person edited (Task 8, `scenario_merge_keeps_person_edits`).
5. **HA signs the tab out (plain-text 401).** The editor says so in plain words and does not show a raw error (Task 13, `scenario_signed_out_message`).

---

### Task 1: Plan format v2

**Files:**
- Modify: `chauffeur/services/twin_plan.py`
- Test: `chauffeur/tests/test_twin_plan_v2.py` (new); neighbours `tests/test_twin_plan.py`, `tests/test_twin_compose.py`, `tests/test_twin_director.py`

**Interfaces:**
- Produces:
  - `SCHEMA = 'chauffeur.twin.plan/2'`.
  - `normalize(raw) -> (plan, notes)` accepts `/1`, `/2` or no schema and always returns `/2`.
  - Item meta fields on walls, openings, rooms, stairs, roof sections, site items: `id`, `state` (`'ghost'|'settled'`), `src`, `confidence`, `why`.
  - `building['roof'] = {'sections': [...], 'extensions': [...]}`.
  - `building['rotation']` (degrees, CCW in plan axes) and `building['base']` (ft).
  - `site['terraces']`; optional `elevation` on site items.
- `diff_paths`, `merge_director`, `overlay_director` and `record_compose_overrides` keep their signatures.

- [ ] **Step 1: Write the failing tests** (`tests/test_twin_plan_v2.py`, local `check()` helper, no `harness.py` import):

```python
def scenario_p0_pool_house_migrates_to_one_gable_section():
    p0 = json.load(open(FIXTURE))                     # tests/fixtures/twin_poolhouse.plan.json
    plan, notes = twin_plan.normalize(p0)
    roof = plan['buildings'][0]['roof']
    check(plan['schema'] == 'chauffeur.twin.plan/2', plan['schema'])
    main = p0['buildings'][0]['roof']['main']
    check(roof['sections'] == [{'id': 'roof-main', 'kind': 'gable',
        'rect': [main['x0'], main['y0'], main['x1'], main['y1']], 'ridge': main['ridge_axis'],
        'pitch': main['pitch'], 'plate': main['plate'], 'overhang': main['overhang'],
        'pitch_source': 'drawn', 'state': 'settled'}], roof['sections'])
    check(all(e['section'] == 'roof-main' for e in roof['extensions']), roof['extensions'])
    check(twin_plan.normalize(plan)[0] == plan, 'v2 normalize is idempotent')

def scenario_roof_sections_validate():
    b = _building(roof={'sections': [
        {'id': 'r1', 'kind': 'hip', 'rect': [0, 0, 40, 20], 'ridge': 'x', 'pitch': 8, 'plate': 9, 'overhang': 1},
        {'id': 'r2', 'kind': 'shed', 'rect': [40, 0, 50, 20], 'low_side': 'x1', 'pitch': 3, 'plate': 9},
        {'id': 'r3', 'kind': 'gable', 'rect': [5, 5, 5, 9], 'ridge': 'y', 'pitch': 8, 'plate': 9},   # empty rect
        {'id': 'r4', 'kind': 'dome', 'rect': [0, 0, 1, 1], 'pitch': 8, 'plate': 9},                 # unknown kind
        {'id': 'r5', 'kind': 'gable', 'rect': [0, 0, 10, 10], 'ridge': 'y', 'pitch': 40, 'plate': 9}]})
    plan, notes = twin_plan.normalize(_plan(b))
    s = plan['buildings'][0]['roof']['sections']
    check([x['id'] for x in s] == ['r1', 'r2', 'r5'], s)
    check(s[0]['pitch_source'] == 'default' and s[0]['overhang'] == 1, s[0])
    check(s[2]['pitch'] == 24 and any('r5' in n and 'clamped' in n for n in notes), notes)
    check(any('r3' in n for n in notes) and any('r4' in n for n in notes), notes)

def scenario_building_rotation_and_base():
    plan, notes = twin_plan.normalize(_plan(_building(rotation=-90, base=2.5)))
    b = plan['buildings'][0]
    check(b['rotation'] == 270 and b['base'] == 2.5 and b['position'] == [0, 0], b)
    plan, notes = twin_plan.normalize(_plan(_building(rotation='north')))
    check(plan['buildings'][0]['rotation'] == 0 and any('rotation' in n for n in notes), notes)

def scenario_missing_ids_are_assigned_and_unique():
    b = _building(walls=[_wall(None), _wall(None), _wall('wall-1')])
    plan, _ = twin_plan.normalize(_plan(b))
    ids = [w['id'] for w in plan['buildings'][0]['walls']]
    check(len(set(ids)) == 3 and 'wall-1' in ids, ids)

def scenario_piece_meta_is_kept_and_checked():
    w = {**_wall('w9'), 'state': 'ghost', 'src': {'sheet': 'abc', 'page': 2, 'step': 'walls:main:w1'},
         'confidence': 0.4, 'why': 'stamp covers the corner'}
    bad = {**_wall('w10'), 'state': 'floating', 'confidence': 3}
    plan, notes = twin_plan.normalize(_plan(_building(walls=[w, bad])))
    a, b = plan['buildings'][0]['walls']
    check(a['state'] == 'ghost' and a['src']['page'] == 2 and a['confidence'] == 0.4, a)
    check(b['state'] == 'settled' and 'confidence' not in b, b)

def scenario_terraces_validate_and_ground_items_keep_elevation():
    site = {'lot': [[0, 0], [100, 0], [100, 150], [0, 150]],
            'terraces': [{'id': 't1', 'polygon': [[0, 0], [100, 0], [100, 60], [0, 60]], 'height': -4},
                         {'id': 't2', 'polygon': [[0, 0], [1, 1]], 'height': 0}],
            'fire_pit': {'at': [20, 20], 'radius': 3, 'elevation': -4}}
    plan, notes = twin_plan.normalize({'buildings': [], 'site': site})
    check([t['id'] for t in plan['site']['terraces']] == ['t1'], plan['site']['terraces'])
    check(plan['site']['fire_pit']['elevation'] == -4, plan['site']['fire_pit'])
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_twin_plan_v2.py`. Expected: the first scenario fails on `schema`.

- [ ] **Step 3: Implement.** In `services/twin_plan.py`:
  - **Schema and caps:** `SCHEMA = 'chauffeur.twin.plan/2'`. `CAPS['roof_sections'] = 40`, `CAPS['terraces'] = 40`.
  - **Section kinds:**
    - `hip`, `gable`: need `ridge` in `x|y`.
    - `shed`: needs `low_side` in `x0|x1|y0|y1`.
    - `flat`: `pitch` is forced to 0.
  - **Section fields:**
    - `rect` needs `x0 < x1` and `y0 < y1`.
    - `pitch` is clamped to 1..24 (except flat), with a note naming the id and "clamped". Optional `pitches` takes the same per-side keys as `low_side`.
    - `plate > 0`. `overhang` is clamped to 0..4, default 1.
    - `pitch_source` in `drawn|photos|person|default`, default `default`.
  - **Migration from P0:** `roof.main` becomes section `roof-main` with `pitch_source: 'drawn'`. P0 extensions gain `section: 'roof-main'`.
  - **Building:**
    - `rotation` is normalised with `% 360` and must be finite; otherwise 0 plus a note.
    - `base` must be finite, -50..50, default 0.
  - **Meta:**
    - `id` matches `[A-Za-z0-9_.:-]{1,64}`. Missing or duplicate ids get `f'{kind}-{n}'` with the lowest unused `n` per kind (`wall`, `opening`, `room`, `stair`, `roof`, `site`).
    - `state` defaults to `settled`.
    - `src` is kept only as `{'sheet': str, 'page': int, 'step': str}` or `{'person': True}`, plus an optional `'sheet'`/`'page'` that a person edit keeps.
    - `confidence` is kept only if in 0..1. `why` is a string of at most 200 characters.
  - **Terraces:** need a valid polygon of 3 or more points and a finite height in -50..50.
  - Never mutate the input.

- [ ] **Step 4: Run the new test and the neighbours.** Command: `python tests/test_twin_plan_v2.py && python tests/test_twin_plan.py && python tests/test_twin_compose.py && python tests/test_twin_director.py`. Expected: all pass. P0 tests that assert `chauffeur.twin.plan/1` are updated to `/2` by Claude in Step 1, with that change named in the hand-off.

- [ ] **Step 5: Hand off.** Leave the changes in the working tree; Claude reviews and commits.

---

### Task 2: Registration math

**Files:**
- Create: `chauffeur/services/twin_register.py` (pure, no I/O)
- Test: `chauffeur/tests/test_twin_register.py`

**Interfaces:**
- Produces:
  - `make(scale: float, angle: float = 0.0, origin_px=(0, 0), offset=(0, 0)) -> dict` with keys `scale` (ft per px), `angle` (deg, CCW), `origin_px`, `offset`.
  - `apply(reg, point_px) -> [x, y]`: u = (px − ox)·s and v = (oy − py)·s, because sheet y runs down and plan y runs from the front to the rear. Then rotate by `angle` and add `offset`.
  - `invert(reg, point_ft) -> [px, py]`.
  - `from_dimension(a_px, b_px, feet) -> float`: ft per px. Raises `ValueError` under 1 px or feet ≤ 0.
  - `from_two_points(a_px, b_px, a_ft, b_ft) -> dict`.
  - `fit_outline(moving_ft: list, fixed_ft: list) -> (dict, float)`: a rigid move (angle + offset, no scale), trying the four quarter turns, each refined by a centroid shift plus small-angle least squares. Returns `({'angle': deg, 'offset': [dx, dy]}, rms_ft)`.
  - `to_world(building, point_local) -> [x, y]` = R(building.rotation)·local + position, and `to_local(building, point_world)`.
  - `feet_inches(ft: float) -> str`.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_apply_flips_sheet_y():
    reg = twin_register.make(0.1, origin_px=(100, 200))
    check(close(twin_register.apply(reg, (150, 200)), [5, 0]), 'x right')
    check(close(twin_register.apply(reg, (100, 100)), [0, 10]), 'up the sheet is toward the rear')
    check(close(twin_register.invert(reg, [5, 10]), [150, 100]), 'inverse')

def scenario_rotation_is_counterclockwise():
    reg = twin_register.make(1.0, angle=90)
    check(close(twin_register.apply(reg, (10, 0)), [0, 10]), twin_register.apply(reg, (10, 0)))

def scenario_scale_from_the_70_foot_dimension():
    check(abs(twin_register.from_dimension((100, 50), (1500, 50), 70.0) - 0.05) < 1e-9, 'ft per px')
    for bad in [((0, 0), (0, 0.5), 10), ((0, 0), (100, 0), 0)]:
        expect_value_error(lambda: twin_register.from_dimension(*bad))

def scenario_two_points_recover_a_transform():
    truth = twin_register.make(0.05, angle=30, origin_px=(0, 0), offset=(12, -3))
    a, b = (200, 400), (900, 120)
    reg = twin_register.from_two_points(a, b, twin_register.apply(truth, a), twin_register.apply(truth, b))
    for p in [(0, 0), (1000, 1000), (333, 77)]:
        check(close(twin_register.apply(reg, p), twin_register.apply(truth, p), 1e-6), p)

def scenario_fit_outline_finds_quarter_turn_and_shift():
    fixed = [[0, 0], [70, 0], [70, 40], [30, 40], [30, 65.33], [0, 65.33]]
    moved = [rot(p, 90, shift=(5, -2)) for p in fixed]        # rotate 90 deg CCW then shift
    move, rms = twin_register.fit_outline(moved, fixed)
    back = [add(rot(p, move['angle']), move['offset']) for p in moved]
    check(rms < 0.05 and all(close(x, y, 0.05) for x, y in zip(back, fixed)), (move, rms))

def scenario_world_rotation_and_feet_inches():
    b = {'position': [10, 20], 'rotation': 90}
    check(close(twin_register.to_world(b, [5, 0]), [10, 25]), 'rotated then placed')
    check(close(twin_register.to_local(b, [10, 25]), [5, 0]), 'inverse')
    check(twin_register.feet_inches(70.0) == "70'-0\"" and twin_register.feet_inches(65.3333) == "65'-4\"", 'format')
    check(twin_register.feet_inches(11.99) == "12'-0\"", 'rounds to the inch')
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_twin_register.py`.
- [ ] **Step 3: Implement** `services/twin_register.py` to the interfaces above (math only, standard library).
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_twin_register.py`.
- [ ] **Step 5: Hand off.**

---

### Task 3: Roof surfaces

> **Amendment (Codex adversarial review, 2026-11-07):** subtract from face A only the region where B's ACTUAL FACE POLYGON (its active domain) is higher, never B's whole footprint; the test gains `scenario_the_roof_has_no_holes` (sampled coverage, plus the point (16, 18) on HIP+CROSS).

**Files:**
- Create: `chauffeur/static/twin/twin_roof.js` (ES module, no imports, plan feet, z up)
- Test: `chauffeur/tests/test_twin_roof_js.py`, which runs a node script against the module the same way P0's node-run tests do (see `tests/test_nav_runtime.py` for spawning node)

**Interfaces:**
- Produces:
  - `export function sectionHeight(section, x, y)`: number, or `null` outside the rect grown by its overhang.
    - gable, ridge `x`: plate + (half depth − |y − yc|)·pitch/12.
    - hip: plate + min(distance to each of the four rect edges)·pitch/12, signed (negative outside the rect). With unequal `pitches`, each side uses its own pitch.
    - shed: plate + distance from `low_side`·pitch/12.
    - flat: plate.
  - `export function heightAt(sections, x, y)`: the maximum over sections that cover the point, or `null`.
  - `export function roofMesh(sections) -> { positions: Float32Array, section: Int32Array, gables: [{ section, positions }] }`:
    - `positions` holds triangles (x, y, z per vertex); `section` holds the section index per triangle.
    - Every triangle lies on the envelope: valleys and hips where sections meet come from clipping each plane to where it is the maximum.

- [ ] **Step 1: Write the failing tests** (the node script prints JSON; the Python test asserts):

```python
HIP = {'kind': 'hip', 'rect': [0, 0, 40, 20], 'ridge': 'x', 'pitch': 12, 'plate': 10, 'overhang': 0}
GABLE_X = {**HIP, 'kind': 'gable'}
CROSS = {'kind': 'gable', 'rect': [15, 15, 25, 35], 'ridge': 'y', 'pitch': 12, 'plate': 10, 'overhang': 0}

def scenario_section_heights():
    h = run_js("sectionHeight", [HIP, 20, 10], [HIP, 5, 10], [HIP, 20, 2], [GABLE_X, 5, 10], [HIP, 50, 50])
    check(h == [20, 15, 12, 20, None], h)

def scenario_shed_and_overhang():
    shed = {'kind': 'shed', 'rect': [0, 0, 10, 20], 'low_side': 'x1', 'pitch': 3, 'plate': 9, 'overhang': 1}
    h = run_js("sectionHeight", [shed, 10, 5], [shed, 0, 5], [shed, 10.5, 5])
    check(close(h, [9, 11.5, 8.875]), h)

def scenario_envelope_makes_the_valley():
    h = run_js("heightAt", [[HIP, CROSS], 20, 18], [[HIP, CROSS], 16, 18], [[HIP, CROSS], 20, 30])
    check(close(h, [15, 12, 15]), h)

def scenario_every_triangle_lies_on_the_envelope():
    for sections in ([HIP], [GABLE_X], [HIP, CROSS], LOT58_ROOF):       # LOT58_ROOF: 6 sections hand-read from sheet 3
        result = run_js_mesh(sections)                                   # centroid heights vs heightAt at the centroid
        check(result['triangles'] > 0 and result['max_error'] < 0.01, (sections, result))

def scenario_no_triangle_hides_under_another_section():
    result = run_js_mesh([HIP, CROSS])
    check(result['buried'] == 0, result)   # buried = triangles whose centroid z < heightAt - 0.01
```

  - `LOT58_ROOF` is written by Claude from `Reference Plans Lot 58.pdf` sheet 3:
    - the central hip,
    - the two hipped wings,
    - the front gable over the porch,
    - the garage gable,
    - the 6'-0" front gable.
  - It uses plausible pitches and lives in `tests/fixtures/twin_lot58_roof.json`.

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_twin_roof_js.py`.
- [ ] **Step 3: Implement** `static/twin/twin_roof.js`.
  - Approach (an algorithm the signatures do not fix):
    - Each section yields convex planar faces: 2 for a gable, 4 for a hip, 1 for a shed or flat roof.
    - Subtract from each face every region of another section where that section is higher. The face and section B's footprint intersected with the half-plane where B's face is higher form a convex region, so the subtraction is convex-minus-convex.
    - Triangulate what remains.
  - Gable end triangles are emitted as `gables`, already clipped the same way.
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_twin_roof_js.py`.
- [ ] **Step 5: Hand off.**

---

### Task 4: Generator v2 (sections, rotation, base, ground, ghosts, picking)

> **Amendment (review):** (a) merged settled meshes cannot carry per-piece identity, so picking uses a separate, never-rendered pick layer (one simple proxy per piece carrying `userData.pieceId`, raycast on its own layer); the live test selects two settled walls that share one merged material. (b) Scene keys for levels are namespaced `${buildingId}:${levelId}` everywhere (`groups.levels`, `levelElevations`, `showLevels`, cutaways, lighting, the P0 view buttons) so two buildings never share an `L1`; the live test seeds two buildings. (c) `services/twin_compose.py` uses `twin_register.to_world` for every footprint, porch, foundation bed and clearance check so planting follows a rotated building; `tests/test_twin_compose.py` gains `scenario_rotated_building_moves_its_beds` (P0 fixture at rotation 0 and 90: obstacle polygons differ by the rotation).

**Files:**
- Create: `chauffeur/static/twin/twin_ground.js`
- Modify: `chauffeur/static/twin/twin_generator.js`, `chauffeur/static/twin/twin_view.js`, `chauffeur/static/twin/twin_yard.js`
- Create: `chauffeur/tests/fixtures/twin_lot58_main.plan.json`, the hand-read main house in v2 with roof sections from `twin_lot58_roof.json`, two levels, one ghost wall
- Test: `chauffeur/tests/test_twin_editor_scene_live.py` (new); neighbours `tests/test_twin_view_live.py`, `tests/test_twin_director_live.py`

**Interfaces:**
- Consumes: Task 1's v2 plan; Task 3's `roofMesh` and `heightAt`.
- Produces:
  - `export function groundAt(plan, x, y)`: returns 0 in slice 1 and reads `plan.site.terraces` only to keep the call sites honest.
  - `buildTwin(plan, kit, tier)` additionally returns `pieces: Map<pieceId, Object3D[]>`.
  - Every mesh carries `userData.pieceId`, `userData.kind` and `userData.buildingId`.
  - Ghost pieces use one shared material named `ghost` (opacity 0.35, `transparent`, `depthWrite: false`, colour `#38bdf8`) plus dashed edges, and are never merged. Settled pieces merge as before.
  - Building groups take `rotation.y = rotation · π/180` (CCW seen from above) and sit at `groundAt(...) + base`.
  - Upper walls stop at `heightAt − 0.08` ft.
  - `view` gains:
    - `pick(clientX, clientY) -> { pieceId, kind, buildingId } | null`;
    - `worldBox(pieceId) -> { min:[x,y,z], max:[x,y,z] }` in plan feet;
    - `showLevels(ids|null)`;
    - `setSheet({ url, reg, buildingId, levelId, opacity } | null)`, which draws the page image on the level's floor plane through the registration;
    - `setCamera('top'|'front'|'back'|'orbit')` (P0's `porch`/`rear` stay as aliases).

- [ ] **Step 1: Write the failing live tests** (same harness pattern as `tests/test_twin_view_live.py`: `live_app`, GPU args, stubbed library):

```python
def scenario_hip_roof_draws_on_the_envelope():   # seed twin_lot58_main.plan.json
    r = page.evaluate("window.__twin.roofStats()")      # test hook: {triangles, maxError} vs heightAt
    check(r['triangles'] > 0 and r['maxError'] < 0.02, r)

def scenario_ghosts_are_translucent_and_unmerged():
    g = page.evaluate("window.__twin.pieceInfo('wall-ghost-1')")
    check(g['material'] == 'ghost' and g['opacity'] == 0.35 and not g['merged'], g)

def scenario_pick_returns_the_wall_under_the_cursor():
    x, y = page.evaluate("window.__twin.screenOf('wall-3')")   # projected midpoint of a settled wall
    check(page.evaluate(f"window.__twin.pick({x},{y})")['pieceId'] == 'wall-3', 'pick')

def scenario_rotation_turns_the_building():
    a = page.evaluate("window.__twin.worldBox('wall-3')")
    page.evaluate("window.__twin.rebuild(rotated(window.__twin.plan, 90))")
    b = page.evaluate("window.__twin.worldBox('wall-3')")
    check(close(width(a), depth(b), 0.05) and close(depth(a), width(b), 0.05), (a, b))

def scenario_still_no_transmission_and_pool_house_still_draws():
    check(page.evaluate("window.__twin.materialsWith('transmission')") == [], 'transmission')
    # and the unchanged P0 fixture (migrated by normalize) renders with its shed and awning

def scenario_sheet_underlay_sits_on_its_level():
    page.evaluate("window.__twin.setSheet({url: SHEET_PNG, reg: REG, buildingId: 'house', levelId: 'L1', opacity: 0.6})")
    check(page.evaluate("window.__twin.sheetInfo()")['y'] == pytest_approx(level_floor_y), 'underlay height')
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_twin_editor_scene_live.py`.
- [ ] **Step 3: Implement**, replacing P0's single-gable `roofHeight` and `roofPlane` code with `twin_roof.js` output:
  - Roof faces are built from `positions`, and gable ends use the `siding` material.
  - The roof material rules stay: standing seams only along faces whose `pitch_source` is irrelevant. Seams follow each face's slope direction.
  - Extensions (`shed_continuation`, `awning`) keep working for migrated P0 plans, anchored to their `section`'s rect.
  - The test hooks (`roofStats`, `pieceInfo`, `screenOf`, `materialsWith`, `sheetInfo`) live on `window.__twin` only when the URL has `?test=1`.
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_twin_editor_scene_live.py && python tests/test_twin_view_live.py && python tests/test_twin_director_live.py`.
- [ ] **Step 5: Hand off.**

---

### Task 5: Sheets, crops, page roles, registrations, start over, ledger reset

> **Amendment (review):** (a) Every persisted-plan read normalizes: `current()`, `_read_round`, `revert`, and every route that returns a plan; the test writes an untouched v1 round to disk and asserts `current()` and a revert both return `chauffeur.twin.plan/2` with roof sections. (b) One lifecycle protocol: `twin_store.LIFECYCLE` (an `RLock`) and `twin_store.generation()` (an int in the `house_twin` row). `start_over()` takes the lock, refuses while `build_running()`, and bumps the generation; `update_current(..., generation=None)` refuses with `StaleGeneration` when a given generation is no longer current, so a late worker result can never write after a start over. (c) Deletion tombstones: `add_tombstone(piece: dict)` / `tombstones() -> list` in the `house_twin` row (kind, level, geometry, `src.step`); cleared by `start_over()`.

**Files:**
- Modify: `chauffeur/services/twin_store.py`, `chauffeur/services/twin_pdf.py`, `chauffeur/services/twin_cost.py`
- Test: `chauffeur/tests/test_twin_sheets.py` (new); neighbours `tests/test_twin_store.py`, `tests/test_twin_cost.py`

**Interfaces:**
- Produces:
  - **Masters:** upload also stores `master-<n>.png`, rendered at 300 dpi and capped at 7200 px on the long side. Sources from before masters existed render them lazily from `original.pdf` on the first crop.
  - `crop(source_id, page, box, max_side=2048) -> {'mime','b64','box','size':[w,h],'master':[W,H]}`. `box` is `[x0,y0,x1,y1]` normalised 0..1 on the master.
  - `crop_to_master(crop, uv) -> [px, py]` (module function; uv normalised within the crop).
  - `page_image(source_id, page) -> bytes`: the 2048 px page PNG, for the underlay.
  - `set_page_roles(rows)` / `page_roles() -> list[dict]`. Each row is `{'source','page','role','level','box','building'}` (`building` defaults to `'house'`; the pool house's sheets use `'pool_house'`), with role in `floor|roof|plot|elevation|other|skip`. A page may carry several rows (the roof sheet also carries the bonus level).
  - `set_registration(source_id, page, level, reg)` / `registration(source_id, page, level) -> dict | None`.
  - `update_current(mutator, kind, note='', step=None, cost=None) -> int`: reads the current plan, applies `mutator(plan) -> plan` and pushes a round, all under `_LOCK` (never stale).
  - `_KINDS` gains `'build'`, `'edit'` and `'start_over'`. Round records gain an optional `step: {'id','label'}`.
  - `start_over() -> None`:
    - Removes rounds, sources, page roles, registrations and `runs/` and `builds/` under `DATA_DIR`.
    - Resets the `house_twin` settings row.
    - Keeps `house_twin_cost` and `house_twin_perf`.
    - Refuses while a build runs. Task 8 provides `twin_build.running() -> bool`; until then Task 5 checks a module flag that Task 8 sets.
  - `twin_cost.reset(by: str) -> dict`:
    - Moves live entries to `archived`, appends `{'at','by','total'}` to `resets`, and clears `acknowledged`.
    - `total()` counts live entries only.
    - The reset is the person's explicit act; nothing calls it automatically.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_crop_is_full_resolution():
    sid = twin_store.save_source('drawing', 'lot58.pdf', make_pdf(page_in=(17, 11)))   # vector test PDF
    full = twin_store.crop(sid, 1, [0, 0, 1, 1]); quarter = twin_store.crop(sid, 1, [0.25, 0.25, 0.5, 0.5])
    check(full['master'][0] == 5100 and full['master'][1] == 3300, full['master'])     # 17x11 in at 300 dpi
    check(max(quarter['size']) == 1275, quarter['size'])                               # 1275x825, not upscaled
    check(close(twin_store.crop_to_master(quarter, [0.5, 0.5]), [1912.5, 1237.5]), 'crop centre on master')

def scenario_old_sources_render_masters_lazily():
    sid = save_without_master(...)    # simulate a P0 upload
    check(twin_store.crop(sid, 1, [0, 0, 1, 1])['master'][0] == 5100, 'lazy master')

def scenario_page_roles_and_registrations_round_trip():
    twin_store.set_page_roles([{'source': sid, 'page': 3, 'role': 'roof', 'level': None, 'box': None},
                               {'source': sid, 'page': 3, 'role': 'floor', 'level': 'Bonus', 'box': [0.05, 0.2, 0.4, 0.8]}])
    check(len(twin_store.page_roles()) == 2, twin_store.page_roles())
    twin_store.set_registration(sid, 1, 'L1', twin_register.make(0.05))
    check(twin_store.registration(sid, 1, 'L1')['scale'] == 0.05, 'reg')

def scenario_update_current_is_never_stale():
    first = twin_store.push_round(minimal_plan(), 'build')
    rid = twin_store.update_current(lambda p: {**p, 'site': {'lot': LOT}}, 'edit', step={'id': 's', 'label': 'x'})
    check(twin_store.current_id() == rid and not twin_store.rounds()[-1]['stale'], twin_store.rounds())

def scenario_start_over_keeps_the_ledger():
    twin_cost.record('step:outline', [usage(1000, 100)])
    spent = twin_cost.total(); twin_store.start_over()
    check(twin_store.current() is None and twin_store.sources() == [] and twin_store.page_roles() == [], 'cleared')
    check(twin_cost.total() == spent, 'ledger kept')

def scenario_ledger_reset_is_recorded():
    twin_cost.record('step:outline', [usage(1000, 100)]); spent = twin_cost.total()
    twin_cost.reset('parent-1')
    check(twin_cost.total() == 0 and twin_cost.resets()[-1]['total'] == spent and twin_cost.resets()[-1]['by'] == 'parent-1', 'reset')
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_twin_sheets.py`.
- [ ] **Step 3: Implement** to the interfaces. `twin_pdf.render_pages` gains no new defaults; masters call it with `dpi=300, max_side=7200`.
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_twin_sheets.py && python tests/test_twin_store.py && python tests/test_twin_cost.py`.
- [ ] **Step 5: Hand off.**

---

### Task 6: Usage collector for every model request

> **Amendment (review):** the collector gates as well as counts: `llm.collect_usage(before=None, after=None)` calls `before()` immediately before each provider request (raising stops that request) and `after(row)` immediately after it, including failures; callers pass `twin_cost.require_clear` and a one-row `twin_cost.record`, so a checkpoint stops the very next request inside a multi-round agent turn. Residual: concurrent callers may each have one request in flight across a boundary. Model ids in tests are real: a bare Gemini id, `anthropic:claude-sonnet-5-5`, `openai:gpt-6.1`; each provider test asserts the dispatched endpoint and wire model.

**Files:**
- Modify: `chauffeur/services/llm.py`
- Test: `chauffeur/tests/test_llm_usage_collector.py`

**Interfaces:**
- Produces: `llm.collect_usage()`, a context manager yielding a list.
  - While it is active, every provider request made by `llm.call_model` in the same context appends `{'model','input_tokens','output_tokens','images','prompt_chars','max_output_tokens'}`. That includes the agent router's tool rounds and `model_pools.call_pool_json`.
  - Reported token counts are filled for Gemini, Claude and OpenAI responses; `None` only when a provider reports nothing.
  - Nested collectors both receive the rows.
  - Outside a collector nothing changes.

- [ ] **Step 1: Write the failing tests.** Stub the provider HTTP layer inside `services/llm.py` with canned response bodies for each provider (one per provider, with real token-usage field shapes):

```python
def scenario_each_provider_reports_tokens():
    for model, body in [('gemini:gemini-3-pro', GEMINI_BODY), ('claude:claude-sonnet-5-5', CLAUDE_BODY),
                        ('openai:gpt-6.1', OPENAI_BODY)]:
        with stub_provider(body), llm.collect_usage() as rows:
            llm.call_model(model, 'k', 'sys', 'hello')
        check(rows == [{'model': model, 'input_tokens': 120, 'output_tokens': 45, 'images': 0,
                        'prompt_chars': 8, 'max_output_tokens': 0}], rows)

def scenario_no_collector_no_change():
    with stub_provider(GEMINI_BODY):
        check(llm.call_model('gemini:gemini-3-pro', 'k', 'sys', 'hello') is not None, 'call works')

def scenario_agent_turn_is_collected():
    with stub_provider(GEMINI_BODY), llm.collect_usage() as rows:
        agent_router.process_agent_request('hi', source='house_editor', acting_member=PARENT)
    check(len(rows) >= 1, rows)
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_llm_usage_collector.py`.
- [ ] **Step 3: Implement** with a `contextvars.ContextVar`. Read the token fields each provider already returns; the `metrics` plumbing P0 added to `call_model` is the precedent.
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_llm_usage_collector.py && python tests/test_twin_draft.py`.
- [ ] **Step 5: Hand off.**

---

### Task 7: Step reads

**Files:**
- Create: `chauffeur/services/twin_reads.py`
- Create: `chauffeur/tests/fixtures/twin_reads/` (Claude writes the hand-made fixtures here in Step 1; Task 12 adds recorded ones)
- Test: `chauffeur/tests/test_twin_reads.py`

**Interfaces:**
- Consumes: `twin_cost.require_clear()` and `twin_cost.record(stage, usage, run)`; `model_pools.call_pool_json('twin', ..., max_models=1, usage=usage, strict_json=True, thinking_level='low')`.
- Produces:
  - `KINDS = ('sheet_roles','outline','walls','openings','rooms','registration','roof','pitch','plot','site','finishes')`.
  - `read(kind, images, context, *, run, step) -> dict`:
    - One metered request; recorded as stage `f'step:{kind}'`.
    - Returns the parsed fragment or `{'error': str}`.
    - Raises `twin_cost.CheckpointReached` unchanged.
  - `parse(kind, answer) -> (fragment, problems: list[str])`: validation only, no I/O. Coordinates are crop-normalised `[u, v]`, origin top-left. Points outside −0.05..1.05 are dropped from the fragment and named in `problems`.
  - `MAX_OUTPUT = {'sheet_roles': 2048, 'outline': 4096, 'walls': 16384, 'openings': 16384, 'rooms': 8192, 'registration': 4096, 'roof': 8192, 'pitch': 2048, 'plot': 8192, 'site': 8192, 'finishes': 8192}`. Timeout 120 s per read.
- **Contracts** (prompt text is the implementer's; these JSON shapes are fixed):
  - `sheet_roles`: `{"pages":[{"page":1,"role":"floor","level":"Main floor","box":null}]}`.
  - `outline`: `{"dimension":{"a":[u,v],"b":[u,v],"feet":70.0},"outline":[[u,v],...],"wings":[{"name":"garage","box":[u0,v0,u1,v1]}],"confidence":0.8,"why":""}`.
  - `walls`: `{"walls":[{"from":[u,v],"to":[u,v],"exterior":true,"thickness_in":6}],"confidence":..,"why":..}`.
  - `openings`: `{"openings":[{"at":[u,v],"kind":"window|door|slider|bifold|passage|garage","width_ft":3.0,"sill_ft":2.0,"head_ft":7.0}]}`. The engine snaps each opening to the nearest settled wall.
  - `rooms`: `{"rooms":[{"name":"","polygon":[[u,v],...]}]}`.
  - `registration`: `{"dimension":{...},"lower_outline":[[u,v],...],"outline":[[u,v],...],"wings":[{"name":"..","box":[u0,v0,u1,v1]}],"confidence":..,"why":..}`.
  - `roof`: `{"outline":[[u,v],...],"sections":[{"kind":"hip","box":[u0,v0,u1,v1],"ridge":"x","low_side":null}],"confidence":..}`.
  - `pitch`: `{"pitches":[{"section":"roof-3","pitch":8,"confidence":0.6,"why":""}]}`, from photos plus the section list in `context`.
  - `plot`: `{"scale":{"a":[u,v],"b":[u,v],"feet":150.2},"lot":[[u,v],...],"street_edge":[0,1],"buildings":[{"name":"house","outline":[[u,v],...]}],"confidence":..}`.
  - `site`: `{"pool":{"polygon":[...],"depth_ft":5},"hardscape":[{"kind":"patio","polygon":[...]}],"fire_pit":{"at":[u,v],"radius_ft":3},"retaining_walls":[{"from":[u,v],"to":[u,v],"height_ft":2}]}`.
  - `finishes`: P0's `FINISHES_PROMPT` contract, `{"materials":{...}}` (move P0's prompt here).

- [ ] **Step 1: Write the failing tests.** Fixtures `tests/fixtures/twin_reads/<kind>.json` are hand-written by Claude from the Lot 58 sheets.

```python
def scenario_each_kind_parses_its_fixture():
    for kind in twin_reads.KINDS:
        frag, problems = twin_reads.parse(kind, fixture(kind))
        check(frag and problems == [], (kind, problems))

def scenario_out_of_range_points_are_named_not_kept():
    frag, problems = twin_reads.parse('walls', {'walls': [{'from': [0.1, 0.1], 'to': [1.4, 0.1], 'exterior': True}]})
    check(frag['walls'] == [] and any('outside' in p for p in problems), (frag, problems))

def scenario_read_is_one_metered_request():
    calls = stub_pool(answer=fixture('outline'))
    frag = twin_reads.read('outline', [img()], {}, run='r1', step='outline:L1')
    check(len(calls) == 1 and calls[0]['max_models'] == 1 and calls[0]['max_output_tokens'] == 4096, calls)
    check(twin_cost.entries()[-1]['stage'] == 'step:outline' and twin_cost.entries()[-1]['run'] == 'r1', twin_cost.entries())

def scenario_failure_is_recorded_and_returned():
    stub_pool(raises=RuntimeError('boom'))
    check('error' in twin_reads.read('walls', [img()], {}, run='r1', step='walls:L1:w1'), 'error')
    check(twin_cost.entries()[-1]['stage'] == 'step:walls', 'charged even on failure')

def scenario_checkpoint_propagates():
    force_checkpoint(10.0)
    expect(twin_cost.CheckpointReached, lambda: twin_reads.read('walls', [img()], {}, run='r', step='s'))
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_twin_reads.py`.
- [ ] **Step 3: Implement** `services/twin_reads.py`. Prompts reuse P0's `_RULES` wording where it applies, and say coordinates are crop-normalised.
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_twin_reads.py && python tests/test_twin_cost.py`.
- [ ] **Step 5: Hand off.**

---

### Task 8: The build engine

> **Amendment (review):** (a) Child boxes (wings from an outline or registration read) are crop-normalised; the engine composes them through the parent crop into master-normalised boxes before calling `twin_store.crop`; test `scenario_nested_wing_crop_is_composed` (a Bonus role box [0.05,0.2,0.4,0.8] and a wing box [0.5,0.5,1,1] inside it crop master box [0.225,0.5,0.4,0.8]). (b) The engine holds `twin_store.LIFECYCLE` for start, stop, resume and every merge, and passes its generation to `update_current`; test `scenario_start_over_discards_a_late_result` (a blocked reader returns after start over; nothing is written). (c) Merges skip any new piece from the same step whose geometry lies within 1 ft of a tombstone; test `scenario_reread_does_not_resurrect_a_deleted_wall`.

**Files:**
- Create: `chauffeur/services/twin_build.py`
- Test: `chauffeur/tests/test_twin_build.py` (a fake reader returns fixtures by kind; no model calls)

**Interfaces:**
- Consumes: Tasks 1, 2, 5 and 7.
- Produces:
  - `plan_steps(page_roles: list, photos: list, plot: list) -> list[dict]`: the static skeleton, in order. Each step is `{'id','kind','label','pause': None|'scale_outline'|'level_registration'|'lot_placement', 'source','page','level','box'}`.
  - `start(inputs: dict, *, reader=twin_reads.read, inline=False) -> str` (build id). `inputs = {'building': {'id': 'house', 'name': 'Main house'}, 'photos': [ids]}`. One build builds one building from the role rows whose `building` matches. Levels get ids `L1..Ln` in the order their floor-role rows appear (page order, then box order) and take their names from the row's `level` text. A building already on the lot keeps its placement; the new one is placed beside it at `lot_placement`. Refuses with `ValueError('A build is already running.')`.
  - `running() -> bool`.
  - `status(build_id, since=0) -> dict` with keys `id`, `state` (`running|paused|checkpoint|done|failed|stopped`), `steps`, `events` (seq > since), `seq`, `pause` and `cost` (this build's spend).
  - `answer(build_id, step_id, decision) -> dict`. `decision` is one of `{'accept': True}`, `{'registration': reg}` or `{'transform': {'position': [x, y], 'rotation': deg}}`. It resumes the build.
  - `reread(build_id, step_id) -> dict`: drops that step's cached answer and the pieces it produced (unless a person edited them), then re-queues it. Explicit only.
  - `stop(build_id)`, `resume(build_id)`.
  - `recover() -> None`: called at app start. Builds left `running` become `stopped`.
  - Event types: `stage`, `log`, `ghost`, `settled`, `pause`, `question`, `cost`, `checkpoint`, `error`, `done`.
  - `log` text is templated with no model call. Pinned strings:
    - `"Main floor outline: 70'-0\" by 65'-4\""`
    - `"{level}: {w} walls, {o} openings, {r} rooms"`
    - `"Roof: {n} sections, pitches estimated from photos"`
    - `"Placed {building} on the lot, turned {deg}°"`
- **Order for one building:**
  1. `sheet_roles`, only when no roles are confirmed.
  2. `outline:<L1>` (pause `scale_outline`), registering the first floor sheet via `from_dimension` plus the outline.
  3. One `walls:<L1>:<wing>` per wing named by the outline read.
  4. `openings:<L1>`, then `rooms:<L1>`.
  5. For each further floor-role level: `registration:<L>` (pause `level_registration`, fitted with `fit_outline` against the settled level below), then its walls, openings and rooms.
  6. `roof`: the roof sheet's outline is fitted to the settled footprint grown by 1 ft. A fit RMS over 1.5 ft emits a `question`, not a pause.
  7. `pitch`, only when photos exist; otherwise sections keep `pitch_source: 'default'` and pitch 6.
  8. `plot` (pause `lot_placement`), then `site`, then `finishes` and `compose` (Task 18 fills these two).
- **Settling:**
  - Each step's pieces enter as ghosts (`ghost` event).
  - They settle (`settled` event plus one `twin_store.update_current(..., kind='build', step=...)` round) when `twin_plan.normalize` keeps them and, for walls, both ends lie within 2 ft of the settled outline or of another wall.
  - A piece that fails stays a ghost with `why` and is logged.
  - Pause steps settle only on `answer`.
- **Merge:** by piece id. Pieces whose `src` has `person: True` are never overwritten or deleted by the engine.
- **Persistence:**
  - `DATA_DIR/builds/<id>/state.json` and `steps/<step>.json` (the cached read answers, written atomically like P0's `_save`).
  - A resumed build never re-reads a cached step.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_main_house_step_order():
    roles = lot58_roles()          # p1 floor Main floor; p2 floor Upper floor; p3 roof + floor Bonus (box); plot sheet
    steps = twin_build.plan_steps(roles, photos=['ph1'], plot=[PLOT])
    check([s['id'] for s in steps] == ['outline:L1', 'openings:L1', 'rooms:L1', 'registration:L2', 'openings:L2',
        'rooms:L2', 'registration:L3', 'openings:L3', 'rooms:L3', 'roof', 'pitch', 'plot', 'site', 'finishes', 'compose'], steps)
    check([s['pause'] for s in steps if s['pause']] == ['scale_outline', 'level_registration', 'level_registration', 'lot_placement'], steps)

def scenario_wings_expand_after_the_outline():
    b = twin_build.start(INPUTS, reader=fake_reader(), inline=True)    # stops at the first pause
    st = twin_build.status(b)
    check(st['state'] == 'paused' and st['pause']['kind'] == 'scale_outline', st)
    twin_build.answer(b, 'outline:L1', {'accept': True})
    ids = [s['id'] for s in twin_build.status(b)['steps']]
    check(ids[1:3] == ['walls:L1:garage', 'walls:L1:main'], ids)

def scenario_first_log_line_is_pinned():
    b = run_to_first_pause(); twin_build.answer(b, 'outline:L1', {'accept': True})
    logs = [e['text'] for e in twin_build.status(b)['events'] if e['type'] == 'log']
    check("Main floor outline: 70'-0\" by 65'-4\"" in logs, logs)

def scenario_out_of_crop_read_stays_a_ghost():
    b = twin_build.start(INPUTS, reader=fake_reader(walls_extra=[{'from': [0.5, 0.5], 'to': [3.0, 0.5]}]), inline=True)
    accept_all_pauses(b)
    plan = twin_store.current()
    check(not any(w.get('state') == 'settled' and w['to'][0] > 200 for w in walls(plan)), 'nonsense never settles')
    check(twin_build.status(b)['state'] == 'done', 'build continues')

def scenario_restart_resumes_without_repaying():
    reader = fake_reader(); b = twin_build.start(INPUTS, reader=reader, inline=True)
    twin_build.answer(b, 'outline:L1', {'accept': True})
    before = len(reader.calls); simulate_restart(); twin_build.recover()
    check(twin_build.status(b)['state'] == 'stopped', 'recovered as stopped')
    twin_build.resume(b)
    check(not any(c['step'] == 'outline:L1' for c in reader.calls[before:]), 'cached step not re-read')

def scenario_checkpoint_stops_and_resumes():
    reader = fake_reader(checkpoint_at='rooms:L1'); b = run(reader)
    check(twin_build.status(b)['state'] == 'checkpoint', twin_build.status(b))
    twin_cost.acknowledge(10.0); reader.checkpoint_at = None; twin_build.resume(b)
    check(twin_build.status(b)['steps'][index_of(b, 'rooms:L1')]['status'] == 'done', 'same step resumed')

def scenario_merge_keeps_person_edits():
    b = run_until(fake_reader(), 'openings:L1')
    wall = first_wall(twin_store.current())
    twin_edit.save({'op': 'set', 'piece': wall['id'], 'field': 'height', 'value': 11}, actor_id='p1')
    twin_build.reread(b, f"walls:L1:{wing_of(wall)}"); accept_all_pauses(b)
    check(find(twin_store.current(), wall['id'])['height'] == 11, 'person edit kept')

def scenario_registration_answer_moves_the_level():
    b = run_until_pause('registration:L2')
    reg = shifted(twin_build.status(b)['pause']['registration'], dx=1.0)
    twin_build.answer(b, 'registration:L2', {'registration': reg})
    check(twin_store.registration(P2, 2, 'L2')['offset'][0] == pytest_approx(old_dx + 1.0), 'reg saved')
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_twin_build.py`.
- [ ] **Step 3: Implement** `services/twin_build.py`:
  - One background thread per running build, and one module lock.
  - `inline=True` runs on the caller's thread until a pause, checkpoint, `done` or `failed`.
  - Crops come from `twin_store.crop` with the step's box: the wing box from the outline read, or the role row's `box`.
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_twin_build.py && python tests/test_twin_sheets.py && python tests/test_twin_reads.py`.
- [ ] **Step 5: Hand off.**

---

### Task 9: Hand edits

> **Amendment (review):** `delete` records a tombstone (`twin_store.add_tombstone`) with the piece's kind, level, geometry and `src.step`, so a reread cannot bring it back (Task 8 honours it).

**Files:**
- Create: `chauffeur/services/twin_edit.py`
- Test: `chauffeur/tests/test_twin_edit.py`

**Interfaces:**
- Produces:
  - `EDITABLE = {'wall': ('height', 'thickness', 'exterior'), 'opening': ('width', 'sill', 'head', 'kind', 'panels', 'at'), 'room': ('name', 'ha_area'), 'roof': ('kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side'), 'building': ('name', 'position', 'rotation', 'base'), 'level': ('name', 'elevation', 'ceiling')}`.
  - `apply(plan, edit) -> (plan, summary: str)`. Ops:
    - `set {piece, field, value}`
    - `move {piece, by: [dx, dy]}`: walls move both ends, rooms translate, openings slide `at` along their wall by projection, roof sections move their rect, buildings move their position.
    - `rotate {building, to}`
    - `delete {piece}`
    - `accept {pieces}` (ghost to settled)
    - `add_wall {building, level, from, to}`
    - `add_opening {wall, at, kind, width}`
    - `registration {source, page, level, reg}`: every piece whose `src` names that sheet, page and level is moved from the old registration to the new one.
  - Every changed piece gains `src.person = True`. Setting `pitch` sets `pitch_source: 'person'`.
  - `summary` is plain words: `"Set the Kitchen window width to 4'-0\""`, `"Moved wall-12 1'-0\" toward the rear"`.
  - `save(edit, actor_id, reason='') -> {'round', 'summary'}`: via `twin_store.update_current(kind='edit')`, appending one fix per changed leaf to the accuracy record with P0's `extraction|yard` kinds.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_set_pitch_marks_the_person():
    plan, summary = twin_edit.apply(lot58(), {'op': 'set', 'piece': 'roof-3', 'field': 'pitch', 'value': 8})
    s = section(plan, 'roof-3')
    check(s['pitch'] == 8 and s['pitch_source'] == 'person' and s['src']['person'] is True, s)

def scenario_unknown_field_is_refused():
    expect_value_error(lambda: twin_edit.apply(lot58(), {'op': 'set', 'piece': 'wall-1', 'field': 'from', 'value': [0, 0]}))

def scenario_move_slides_an_opening_along_its_wall():
    plan, _ = twin_edit.apply(lot58(), {'op': 'move', 'piece': 'opening-4', 'by': [2, 5]})   # wall runs along x
    check(opening(plan, 'opening-4')['at'] == opening(lot58(), 'opening-4')['at'] + 2, 'projected onto the wall')

def scenario_registration_moves_every_piece_from_that_sheet():
    before = lot58(); plan, _ = twin_edit.apply(before, {'op': 'registration', 'source': P2, 'page': 2, 'level': 'L2',
                                                         'reg': shifted(REG_L2, dx=1.0)})
    for w in walls(plan, 'L2'):
        check(close(w['from'], add(wall(before, w['id'])['from'], [1, 0]), 1e-6), w['id'])
    check(walls(plan, 'L1') == walls(before, 'L1'), 'other sheets untouched')

def scenario_save_logs_fixes_and_a_plain_summary():
    seed(lot58()); out = twin_edit.save({'op': 'set', 'piece': 'opening-4', 'field': 'width', 'value': 4}, 'p1')
    check(out['summary'].startswith('Set ') and "4'-0\"" in out['summary'], out)
    check(twin_store.fixes()[-1]['round'] == out['round'], twin_store.fixes())
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_twin_edit.py`.
- [ ] **Step 3: Implement** `services/twin_edit.py`.
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_twin_edit.py && python tests/test_twin_store.py`.
- [ ] **Step 5: Hand off.**

---

### Task 10: Editor routes and auth

**Files:**
- Modify: `chauffeur/main.py`, `chauffeur/services/auth.py`, `chauffeur/templates/nav.html` (`_up` for `/house/editor`, same as `/house/twin`)
- Create: `chauffeur/templates/house_editor.html` (a stub that Task 13 fills)
- Test: `chauffeur/tests/test_house_editor_routes.py`; neighbours `tests/test_auth_rules.py` (or whichever test flags unclassified routes: find it with `grep -l "unclassified" tests/`)

**Interfaces:**
- Produces (all `PARENTS` except the page):
  - `GET /house/editor`: page; rule `(ANY, '/house/editor', ANYONE, None)`.
  - `GET /api/house/editor/sheets`: sources plus `page_roles` plus registrations.
  - `PUT /api/house/editor/sheets/roles`: body `{'rows': [...]}`.
  - `GET /api/house/editor/sheets/{source_id}/{page}.png`: the underlay image.
  - `POST /api/house/editor/build`: body `inputs`, returns `{'id'}`. 409 `{'detail': 'A build is already running.'}`.
  - `GET /api/house/editor/build/{build_id}?since=N`: `status`.
  - `POST /api/house/editor/build/{build_id}/answer`: `{'step', 'decision'}`.
  - `POST /api/house/editor/build/{build_id}/reread`: `{'step'}`.
  - `POST /api/house/editor/build/{build_id}/stop` and `/resume`.
  - `POST /api/house/editor/edit`: `{'edit', 'reason'?}`, returns `{'round', 'summary', 'plan'}`.
  - `POST /api/house/editor/start-over`: 409 while a build runs.
  - `POST /api/house/editor/cost/reset`: body `{'confirm': 'reset'}`; anything else is 400.
  - `GET /api/house/editor/state`: `{'plan', 'rounds', 'cost': {'total', 'blocking'}, 'build': latest build id or None}`.
  - `GET /api/house/twin/rounds/{round_id}`: one round's plan (for the timeline preview).
  - A checkpoint reached during any of these returns 409 `{'detail': {'checkpoint', 'total'}}`, as P0 does.
  - App start calls `twin_build.recover()`.

- [ ] **Step 1: Write the failing tests** (TestClient with a parent token, and a member token for the refusals):

```python
def scenario_every_editor_route_is_parents_only():
    for method, path in EDITOR_API:
        check(client.request(method, path, headers=MEMBER).status_code in (401, 403), path)

def scenario_build_runs_through_the_api():
    seed_sources_and_roles(); stub_reader_with_fixtures()
    bid = client.post('/api/house/editor/build', json=INPUTS, headers=PARENT).json()['id']
    st = wait_for(lambda: client.get(f'/api/house/editor/build/{bid}', headers=PARENT).json(), state='paused')
    check(st['pause']['kind'] == 'scale_outline', st)
    check(client.post('/api/house/editor/build', json=INPUTS, headers=PARENT).status_code == 409, 'one at a time')

def scenario_edit_returns_summary_and_plan():
    r = client.post('/api/house/editor/edit', json={'edit': {'op': 'set', 'piece': 'roof-3', 'field': 'pitch', 'value': 8}},
                    headers=PARENT).json()
    check(r['summary'] and section(r['plan'], 'roof-3')['pitch'] == 8, r)

def scenario_reset_needs_the_word():
    check(client.post('/api/house/editor/cost/reset', json={}, headers=PARENT).status_code == 400, 'no word, no reset')

def scenario_page_renders_for_anyone_and_gates_on_parent():
    check(client.get('/house/editor').status_code == 200, 'page')
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_house_editor_routes.py`.
- [ ] **Step 3: Implement** the routes as thin wrappers over Tasks 5, 8 and 9, plus the auth rules.
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_house_editor_routes.py` plus the unclassified-routes test.
- [ ] **Step 5: Hand off.**

---

### Task 11: Argyle's `house_design` tool and the editor conversation

> **Amendment (review):** the router's dispatch loop uses explicit branches, so `services/agent_router.py` gets an explicit `house_design` branch that calls `execute_tool('house_design', args, actor=acting_member, focus_key=focus_key)`; the test runs a real `process_agent_request` turn with a stubbed model that emits a `house_design` edit call and asserts the plan changed. The say endpoint passes `before=twin_cost.require_clear` and a per-request `after` to `llm.collect_usage` (Task 6 amendment) instead of one check and one record per turn.

**Files:**
- Modify: `chauffeur/services/agent_tools_v2.py` (schema, handler, `REGISTRY_EXCEPTIONS['house_design'] = 'The house editor never runs from a mission.'`), `chauffeur/services/agent_router.py` (one system-prompt paragraph when `source == 'house_editor'`), `chauffeur/main.py`, `chauffeur/services/auth.py`
- Test: `chauffeur/tests/test_house_design_tool.py`

**Interfaces:**
- Consumes: `twin_edit.apply/save`, `twin_build.status/answer/reread`, `llm.collect_usage`, `twin_cost.record`.
- Produces:
  - Tool `house_design(action, ...)` with actions:
    - `status` (current plan summary, build state, pause),
    - `edit` (one Task 9 edit),
    - `accept` (the pending pause),
    - `reread` (a step),
    - `describe` (a piece's fields in plain words).
  - The tool refuses any actor that is not a parent, with `'Only a parent can change the house.'`.
  - `POST /api/house/editor/say` (`PARENTS`), body `{'message', 'selection': pieceId|None, 'history': [...] (last 20)}`, returns `{'reply', 'changed': bool, 'summary': [...], 'cost'}`. It runs `process_agent_request(message, context={'house_editor': {...status, selection}}, history=history, source='house_editor', acting_member=parent, focus_key=f'house_editor:{build or "idle"}')` inside `llm.collect_usage()`, then `twin_cost.record('conversation', rows)`. `twin_cost.require_clear()` runs first.
  - The editor's conversation lives in the browser for the session (designer's call for slice 1); it is not stored as a chat surface.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_tool_edits_through_the_same_operations():
    seed(lot58())
    out = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'edit': {'op': 'set', 'piece': 'roof-3',
                                       'field': 'pitch', 'value': 8}}, actor=PARENT)
    check(out['status'] == 'ok' and section(twin_store.current(), 'roof-3')['pitch_source'] == 'person', out)

def scenario_tool_refuses_non_parents():
    out = agent_tools_v2.execute_tool('house_design', {'action': 'status'}, actor=CHILD)
    check('Only a parent' in out['message'], out)

def scenario_say_is_metered_as_conversation():
    stub_agent(reply='Done.', tool_calls=[('house_design', {'action': 'status'})], usage=(900, 80))
    r = client.post('/api/house/editor/say', json={'message': 'what is the roof pitch?'}, headers=PARENT).json()
    check(r['reply'] == 'Done.' and twin_cost.entries()[-1]['stage'] == 'conversation', (r, twin_cost.entries()))

def scenario_say_respects_the_checkpoint():
    force_checkpoint(10.0)
    check(client.post('/api/house/editor/say', json={'message': 'hi'}, headers=PARENT).status_code == 409, 'checkpoint')
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_house_design_tool.py`.
- [ ] **Step 3: Implement.** The schema is a Pydantic model like its neighbours; the handler takes `actor`.
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_house_design_tool.py && python tests/test_llm_usage_collector.py`. Also run whichever existing test asserts the tool registry is consistent (find it with `grep -l "REGISTRY_EXCEPTIONS" tests/`).
- [ ] **Step 5: Hand off.**

---

### Task 12: Live harness and the model comparison (LIVE, at most $3.00)

**Files:**
- Create: `chauffeur/tools/twin_live.py`
- Create: `docs/superpowers/plans/2026-11-07-house-editor-comparison.md` (the results)
- Create: `chauffeur/tests/fixtures/twin_reads/recorded/` (recorded answers)
- Test: `chauffeur/tests/test_twin_live_tool.py` (offline: budget refusal and recording format only)

**Interfaces:**
- `python tools/twin_live.py compare --sheets "E:/AirDrop/Reference Plans Lot 58.pdf" --budget 3.00 --models gemini,claude` runs the same four reads per model:
  1. `outline` on page 1;
  2. `walls` on the garage wing box from the hand answer key;
  3. `walls` on the main block box;
  4. `roof` on page 3.
- It uses the local data dir and the local ledger, and stops before any read once the local total plus the next read's ceiling estimate would pass `--budget`.
- It prints a table per model: cost, outline dimension error in feet, outline RMS against `tests/fixtures/twin_lot58_main.plan.json`, wall count against the key, and roof section count and kinds against the key.
- It writes every raw answer to `tests/fixtures/twin_reads/recorded/<model>/<kind>-<n>.json`.
- `python tools/twin_live.py build ... --budget N` later drives a whole live build through `twin_build` (used in Task 19).

- [ ] **Step 1: Offline tests.** The budget refusal (`--budget 0.01` makes no request) and the recording path format, with the pool stubbed.
- [ ] **Step 2: Implement** `tools/twin_live.py`. Keys come from the existing `*_api_key.txt` loading; the tool never prints keys.
- [ ] **Step 3: Run the comparison live (Claude runs this, not Codex).** Report the local ledger total, write the comparison note with both tables and the winner, and record the winner in the plan ledger. **Stop and tell the user** if both models fail the outline (dimension error over 2 ft): that means the crops or prompts need rework before Task 13. The prompts in `twin_reads.py` are then tuned for the winner against the recorded answers (replay tests only).
- [ ] **Step 4: Hand off** the tool, the recorded fixtures and the note.

---

### Task 13: Editor shell

**Files:**
- Modify: `chauffeur/templates/house_editor.html`. It includes `nav.html` inside a hidden `editor-chrome` wrapper (house.html's pattern) for the fetch wrapper, admin session and `_up`, plus `components/control_center.html`.
- Create: `chauffeur/static/twin/editor/editor.js`, `chauffeur/static/twin/editor/editor.css`, `chauffeur/static/twin/editor/panel.js` (Argyle panel), `chauffeur/static/twin/editor/api.js` (fetches, polling, session)
- Test: `chauffeur/tests/test_house_editor_live.py` (new)

**Interfaces:**
- Consumes: Task 10's routes; Task 4's `mountTwin` with the editor hooks.
- Produces the layout of the mockup (`docs/superpowers/plans/assets/2026-11-07-house-editor-mockup.png`):
  - full-screen scene;
  - top bar: title, live build state, running cost;
  - left tool rail;
  - floor stack;
  - Argyle panel (log, messages, quick replies, input, mic button using the PWA's existing voice input if it can be reused unchanged, otherwise text only and named in the hand-off);
  - bottom timeline (Task 17 makes it scrub).
- `api.js`:
  - Polls `GET /build/{id}` every **1000 ms** while a build runs and `GET /state` every **60000 ms** otherwise. The idle poll is also the HA ingress keep-alive.
  - Any non-JSON 401 shows `showGlobalAlert('Home Assistant signed this tab out. Open any Chauffeur admin page from the Home Assistant sidebar, then come back here.')`.
  - A 409 with a checkpoint opens `promptConfirm('Spent $X so far', 'Continue to the next checkpoint?', 'Continue', 'Stop')`. At $50 it shows a close-only notice, as P0 did.
- Empty state (no sources): one panel card with an upload control (PDF drawings, photos), the sheet list with each page's suggested role and level to confirm, and **Build**.
- The first ghost arrives within 30 s of Build on the recorded-replay test.

- [ ] **Step 1: Write the failing live tests** (stubbed reader replaying `tests/fixtures/twin_reads/`):

```python
def scenario_shell_matches_the_mockup_regions():
    for sel in ['#editor-scene canvas', '#editor-top', '#editor-rail', '#editor-floors', '#editor-agent', '#editor-time']:
        check(page.locator(sel).is_visible(), sel)

def scenario_build_streams_ghosts_and_log_lines():
    upload_lot58(); confirm_roles(); page.click('#editor-build')
    page.wait_for_function("window.__editor.ghostCount() > 0", timeout=30000)
    check("Main floor outline: 70'-0\" by 65'-4\"" in log_text_after_accept(), 'log')

def scenario_signed_out_message():
    route_text_401('**/api/house/editor/state')
    page.evaluate("window.__editor.pollNow()")
    check('Home Assistant signed this tab out' in alert_text(), 'plain message, no raw 401')

def scenario_idle_poll_is_one_minute():
    check(page.evaluate("window.__editor.idleInterval") == 60000, 'keep-alive cadence')

def scenario_no_banned_words():
    text = page.inner_text('body').lower()
    check(not any(w in text for w in ('mesh', 'extrude', 'gizmo', 'vertex')), 'plain words')
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_house_editor_live.py`.
- [ ] **Step 3: Implement.** Screenshot proof at 1600×900 goes in the hand-off (memory `ui-design-guide-rule`).
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_house_editor_live.py && python tests/test_twin_view_live.py`.
- [ ] **Step 5: Hand off.**

---

### Task 14: Scene interaction (select, piece cards, drag, rotate, cameras, floors, underlay)

**Files:**
- Create: `chauffeur/static/twin/editor/scene_tools.js`, `chauffeur/static/twin/editor/cards.js`, `chauffeur/static/twin/editor/snap.js` (pure)
- Test: `chauffeur/tests/test_twin_snap_js.py` (node, pure), plus scenarios added to `tests/test_house_editor_live.py`

**Interfaces:**
- `snap.js` (pure):
  - `snapPoint(p, walls, {grid: 0.5, reach: 1.0}) -> p'`: wall endpoints first, then wall lines, then the grid.
  - `snapAngle(from, to) -> to'`: right angles within 7°.
- Tap selects (`view.pick`). The card shows `EDITABLE` fields for the kind as plain labelled number or text inputs, lengths shown in feet-inches. Changing a field posts a `set` edit.
- The card has **Ask Argyle about this**, which focuses the panel with the selection. Advanced roof fields (ridge, low side) sit behind a **More** fold.
- Move tool: drag on the floor plane posts one `move` edit on release. Rotate tool on a building: drag around its centre, snapping to 90° steps within 7°, and posts `rotate`.
- Camera presets Top, Front, Back, Orbit. The floor stack shows, hides or isolates levels (`view.showLevels`). The Sheet tool toggles `view.setSheet` for the selected level's registered page.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_snap_prefers_endpoints_then_lines_then_grid():          # node
    check(run_js('snapPoint', [[10.3, 0.2], WALLS]) == [10, 0], 'endpoint')
    check(run_js('snapPoint', [[5.2, 0.4], WALLS]) == [5.2, 0], 'onto the wall line')
    check(run_js('snapPoint', [[33.3, 33.3], WALLS]) == [33.5, 33.5], 'grid')
    check(run_js('snapAngle', [[0, 0], [10, 0.9]]) == [10, 0], 'right angle within 7 degrees')

def scenario_card_edit_round_trip():                                # live
    click_piece('opening-4'); set_card_field('Width', "4'-0\"")
    check(plan_piece('opening-4')['width'] == 4, 'saved'); check('Set ' in last_log_line(), 'logged in plain words')

def scenario_drag_moves_on_the_floor_only():
    drag_piece('wall-3', by_px=(80, 0))
    w = plan_piece('wall-3'); check(w['from'][0] != orig['from'][0] and w['height'] == orig['height'], 'no vertical drag')

def scenario_rotate_snaps_to_quarter_turns():
    rotate_building('house', degrees=86)
    check(plan_building('house')['rotation'] == 90, 'snapped')
```

- [ ] **Step 2: Run, expect failures.** Command: `python tests/test_twin_snap_js.py && python tests/test_house_editor_live.py`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect pass.** Same commands.
- [ ] **Step 5: Hand off** with screenshots of a card open on a wall and on a roof section.

---

### Task 15: Plan view

**Files:**
- Create: `chauffeur/static/twin/editor/plan_view.js`
- Test: scenarios in `tests/test_house_editor_live.py`

**Interfaces:**
- One rail button, **Plan**, toggles an orthographic top-down view of the selected level. Upper levels are hidden, the level below is faint, and the sheet underlay is optional.
- In plan view:
  - select, move and card editing work exactly as in 3D (same `scene_tools.js` paths);
  - **Add wall**: two clicks, snapped, posts `add_wall`;
  - **Add door/window**: click on a wall, posts `add_opening` with width 3 ft, kind from the button;
  - **Delete**: on the card, with `promptConfirm`.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_plan_view_is_top_down_and_flat():
    page.click('#rail-plan'); check(page.evaluate("window.__twin.cameraKind()") == 'orthographic-top', 'ortho')

def scenario_add_wall_in_plan_view():
    page.click('#rail-plan'); page.click('#plan-add-wall'); click_floor(10, 10); click_floor(20, 10.4)
    check(any(w['from'] == [10, 10] and w['to'] == [20, 10] for w in plan_walls('L1')), 'snapped straight')

def scenario_add_window_on_a_wall():
    page.click('#rail-plan'); page.click('#plan-add-window'); click_wall_midpoint('wall-3')
    check(any(o['wall'] == 'wall-3' and o['kind'] == 'window' and o['width'] == 3 for o in plan_openings()), 'added')
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_house_editor_live.py`.
- [ ] **Step 5: Hand off** with a plan view screenshot.

---

### Task 16: Pauses

**Files:**
- Create: `chauffeur/static/twin/editor/pauses.js`
- Test: scenarios in `tests/test_house_editor_live.py`

**Interfaces:**
- On a `pause` event:
  - the camera goes to Top over the paused level, the sheet underlay is shown, and the ghost is drawn over it;
  - a card is anchored next to the ghost with what Argyle read (`why`, confidence as "sure", "fairly sure" or "unsure") and **Looks right**, **Drag**, **Pin 2 points** and **Re-read** with that step's last cost (`$0.05`).
- Argyle's panel posts the same question in words (templated), and the person may answer there instead.
- Behaviour per pause kind:
  - Drag on `scale_outline` or `level_registration` shifts the registration offset.
  - Drag on `lot_placement` moves the building, and rotate is available.
  - **Pin 2 points**: click a point on the ghost, then where it belongs on the sheet, twice. The result is `from_two_points` (built browser-side with the same math, or via a small POST helper), answered as `{'registration': reg}`.
  - Re-read uses `reread`.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_pause_card_answers_accept():
    start_build_to_pause(); check(page.locator('#pause-card').is_visible(), 'card')
    page.click('#pause-accept'); wait_state('running')

def scenario_pin_two_points_sends_a_registration():
    start_build_to_pause('registration:L2')
    pin(ghost_px(A), sheet_px(A2)); pin(ghost_px(B), sheet_px(B2))
    check(last_answer()['decision']['registration']['scale'] > 0, last_answer())

def scenario_reread_shows_its_cost_first():
    start_build_to_pause(); check('$' in page.inner_text('#pause-reread'), 'cost shown on the button')
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_house_editor_live.py`.
- [ ] **Step 5: Hand off** with a screenshot of the level-registration pause.

---

### Task 17: Timeline

**Files:**
- Create: `chauffeur/static/twin/editor/timeline.js`
- Test: scenarios in `tests/test_house_editor_live.py`

**Interfaces:**
- One mark per round, coloured by kind (`build`, `edit`, `revert`, `director`, `start_over` is never shown). Ticks show stage names, plus a running cost readout and "N of M pieces".
- Dragging the knob previews a round read-only (`GET /api/house/twin/rounds/{id}`), and the scene shows a "Looking at step N" chip.
- Releasing on an earlier round offers **Return here**, which posts P0's revert and creates a new entry. **Back to now** leaves the preview.
- Nothing re-runs.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_scrub_previews_without_changing_the_house():
    n = rounds_count(); drag_knob_to(index=2)
    check(rounds_count() == n and page.locator('#time-chip').is_visible(), 'preview only')

def scenario_return_here_appends_a_revert():
    n = rounds_count(); drag_knob_to(index=2); page.click('#time-return')
    check(rounds_count() == n + 1 and last_round()['kind'] == 'revert', 'append-only')
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_house_editor_live.py`.
- [ ] **Step 5: Hand off.**

---

### Task 18: Finishing steps, art director in the editor, retire P0's tools sheet

> **Amendment (review):** P0's JSON plan editor is not removed: it moves into the editor's menu as **Advanced: edit the plan file** (same reason-required save, same fixes log) until hand operations for site pieces and materials exist; only the tools sheet on `/house/twin` is retired. Test: the editor menu exposes it and a save round-trips.

**Files:**
- Modify: `chauffeur/services/twin_build.py` (`finishes` via `twin_reads.read('finishes', ...)`; `compose` via `twin_compose.compose`), `chauffeur/services/twin_director.py` (v2 plans), `chauffeur/static/twin/twin_director.js` (keep the capture-and-critique loop; remove `initTwinTools` and the sheet UI), `chauffeur/templates/house_twin.html` (remove the tools sheet markup and its script), `chauffeur/static/twin/editor/editor.js` (an **Art director** button in the panel's menu, **Start over**, **Reset spend total**, **Upload more**)
- Test: `tests/test_twin_director.py`, `tests/test_twin_director_live.py` (re-pointed at the editor), `tests/test_house_editor_live.py`, `tests/test_twin_build.py`

**Interfaces:**
- The build's last two steps produce a `build` round with materials and a composed yard.
- The art director runs from the editor with P0's caps and checkpoint handling; its rounds appear on the timeline as `director`.
- **Start over** uses `promptConfirm('Start over?', 'This clears the house, its history and the uploaded drawings and photos. The spend total stays.', 'Start over', 'Keep it')`.
- **Reset spend total** uses `promptInput` asking the parent to type `reset` (the word the API requires), with copy naming the current total and that it cannot be undone.
- `/house/twin` keeps only the view (panel and preview); its `Parent tools` button is gone. In its place, a parent-visible link "Edit the house" goes to `/house/editor`, shown when not in panel or kiosk mode.

- [ ] **Step 1: Write the failing tests:**

```python
def scenario_build_finishes_with_materials_and_yard():     # test_twin_build.py
    b = run_full_build(fake_reader()); plan = twin_store.current()
    check(plan['materials'] and plan['site'].get('planting'), 'finished'); check(twin_build.status(b)['state'] == 'done', 'done')

def scenario_director_runs_from_the_editor():              # test_twin_director_live.py, re-pointed
    open_editor_with(lot58_built()); page.click('#editor-menu'); page.click('#menu-director')
    wait_for_round_kind('director')

def scenario_twin_page_has_no_tools_sheet_but_links_to_the_editor():
    html = client.get('/house/twin').text
    check('twin-tools-sheet' not in html and 'house/editor' in html, 'retired with a way forward')

def scenario_start_over_clears_and_keeps_spend():           # live
    spent = cost_total(); start_over_via_ui(); check(plan() is None and cost_total() == spent, 'kept')
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect pass.** Command: `python tests/test_twin_build.py && python tests/test_twin_director.py && python tests/test_twin_director_live.py && python tests/test_house_editor_live.py && python tests/test_twin_view_live.py`.
- [ ] **Step 5: Hand off.**

---

### Task 19: Acceptance run with the user (LIVE)

Claude runs this with the user after the slice ships to the add-on (version bump, capabilities entry, push; the user rebuilds and verifies the version).

- [ ] **Step 1:** The user opens `/house/editor` from the HA sidebar session and checks the ledger total (expect about $7.48 plus Task 12's local spend, which is reported separately).
- [ ] **Step 2:** The user uploads `Reference Plans Lot 58.pdf`, the plot plans and the house photos, confirms the page roles and presses **Build**.
- [ ] **Step 3: Time and judge against the spec §11 targets:**
  - first ghost within 30 s;
  - never over about 20 s without visible progress;
  - under 30 minutes to a recognisable shell, at most 10 of them fixing;
  - under $5;
  - a family member names all four sides;
  - one fix made by someone without 3D experience, unaided.
- [ ] **Step 4:** Rebuild the pool house from `UPTON POOLHOUSE FINALS 6-2-22.pdf` (roughly $1-2) and place both buildings on the lot.
- [ ] **Step 5:**
  - Record the results, each target met or missed, and the fixes log in the twin memory arc and in `system_capabilities.md` as device-verified where true.
  - Delete the SDD workspace for this plan.
  - Name the parked items: slice 2 starting points and terrain drawing; marketing-plan input; LiDAR.
