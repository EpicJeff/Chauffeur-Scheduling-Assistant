# Paver paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A yard path can be laid as real pavers (layouts, size, gap, rotation, edges, joint fill) with grass growing in the joints.

**Architecture:** A pure layout module (`static/twin/paver_layout.js`) turns a path and its `pavers` settings into paver polygons and joint segments in lot feet. The server validates the new `pavers` field. The yard build turns the layout into one merged mesh per path; the grass field covers only the pavers and adds joint clumps; the path card edits the settings.

**Tech Stack:** three r187 (vendored), plain ES modules, FastAPI services in Python, tests as plain Python scripts that drive node.

**Spec:** `docs/superpowers/specs/2026-11-18-paver-paths-design.md`

## Global Constraints

- Work in `E:\repositories\Chauffeur-paver-paths` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit and do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser, and never use the user's browser.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset: `python tests/test_x.py`. Run only the tests the task names; never the whole suite.
- Do not change the `house_design` agent tool schema. No new packages. No `transmission` on any material. No browser dialogs.
- Paths without `pavers` must build exactly as before (same meshes, same grass covers).
- Field names and ranges exactly as the spec's Data table: `layout` in `stepping|grid|running_bond|diagonal|herringbone`, `length_in` 2..60, `width_in` 2..60, `gap_in` 0..48, `rotation` -90..90, `edge` in `whole|cut`, `joint` in `grass|gravel|sand|none`. Defaults: `grid`, 24, 24, 3, 0, `whole`, `grass`.
- `MAX_PAVERS = 5000` per path. Refusal text: `Use larger pavers or a shorter path.`

## Review Focus

1. A paver wider than the path (grid or running bond, `whole`): at least one paver across, centred; never an empty path.
2. A tight rounded corner or a sharp mitred corner: pavers on the inside never overlap by more than 10% of a paver's area.
3. Grass joints: no lawn clump root inside a paver, and joint clumps sit only in joints; blades never come up through a paver.
4. An older path with no `pavers` field: identical meshes, covers and card (no Surface change unless the person picks Pavers).
5. Paver path on a pad or with `elevation`: paver tops sit 1 inch above the ground there, not at lot height 0.

---

### Task 1: Pure paver layout

**Files:**
- Create: `chauffeur/static/twin/paver_layout.js`
- Test: `chauffeur/tests/test_twin_paver_layout_js.py` (node driver in the style of `tests/test_twin_site_drawing_js.py`, importing `PREFIX, ROOT` from `test_twin_ground_js`)

**Interfaces:**
- Consumes: `pathCentreline(path)` from `static/twin/path_shapes.js`.
- Produces:
  - `export const PAVER_DEFAULTS = { layout: 'grid', length_in: 24, width_in: 24, gap_in: 3, rotation: 0, edge: 'whole', joint: 'grass' }`
  - `export const MAX_PAVERS = 5000`
  - `export function paverSettings(path) -> object | null`: `null` when `path.pavers` is absent or null, else `{...PAVER_DEFAULTS, ...path.pavers}`.
  - `export function paverEstimate(path) -> number`: centre-line length (from `pathCentreline`) times strip width (stepping: paver width) divided by `(length+gap)*(width+gap)` in feet, rounded up. The server mirrors this formula.
  - `export function paverLayout(path) -> { pavers: Array<{ polygon: [x,y][], centre: [x,y], angle: number, index: number }>, joints: Array<[[x,y],[x,y]]>, jointWidth: number }`, all in lot feet, `angle` in radians in the lot plane. `joints` are segments along the middle of each joint between neighbouring pavers (for joint grass); `jointWidth = gap_in / 12`. Returns `{ pavers: [], joints: [], jointWidth: 0 }` when `paverSettings` is null. Deterministic for the same input.

- [ ] **Step 1: Write the failing tests** (one node driver, each check an `assert`):
  - `straight_grid`: path `points [[0,0],[20,0]]`, width 6, `{layout:'grid', length_in:24, width_in:24, gap_in:3}`: 2 pavers across, rows every 27 in along; every paver polygon has 4 corners, side lengths 2 ft within 1e-6; all corners within `|y| <= 3` and `0 <= x <= 20`.
  - `stepping_ignores_width`: same path, width 10, `layout:'stepping'`: every centre has `y` within 1e-6 of 0; centres 27 in apart.
  - `at_least_one_across`: width 1, `{layout:'grid', width_in:24, edge:'whole'}`: one paver across per row, centred (`|centre y| < 1e-6`).
  - `running_bond_offset`: alternate rows' first-paver centres differ in `y` by `(width+gap)/2` (in feet; rows run across the path).
  - `cut_clips`: `layout:'diagonal', edge:'cut'`: every polygon corner within `|y| <= width/2 + 1e-6`; some polygons have other than 4 corners; no polygon area below a tenth of a paver.
  - `whole_keeps_whole`: `layout:'diagonal', edge:'whole'`: every polygon has 4 corners and lies within the strip.
  - `herringbone`: `{length_in:16, width_in:8, gap_in:0.5}`: polygons are 16x8 in rectangles at angles a multiple of 90 degrees from each other (plus the pattern angle), no two overlap (polygon intersection area < 1e-4 sq ft).
  - `curve_no_overlap`: smooth path `points [[0,0],[10,0],[10,10]]`, `corner:'rounded', radius:3`, width 6, grid: no two pavers overlap by more than 10% of a paver's area.
  - `joints_in_gaps`: straight grid: every joint segment's midpoint lies outside every paver polygon, and at least one joint runs along the path and one across.
  - `estimate`: `paverEstimate` of a 100 ft x 4 ft path with 2x2 in pavers and 0 gap is above `MAX_PAVERS`.
  - `none_without_field`: `paverLayout({points:[[0,0],[5,0]], width:3})` returns empty arrays.

- [ ] **Step 2: Run to verify it fails.** `python tests/test_twin_paver_layout_js.py` from `chauffeur/`; expect a module-not-found failure.

- [ ] **Step 3: Implement `paver_layout.js`.** Lay pavers in path-local `(s, t)` (spec "Layouts"), map each centre through the centre line's position and tangent at `s` (interpolate along `pathCentreline` by arc length), turn the polygon with the tangent. `whole` keeps pavers with every local corner inside the strip; `cut` clips each local polygon to the strip rectangle `0 <= s <= L, |t| <= width/2` before mapping (convex clip is enough: pavers are rectangles, the strip is a rectangle in local space) and drops pieces under a tenth of a paver's area. Skip a paver that overlaps an already placed one by more than 10% of its area (check against nearby placed pavers only, e.g. a coarse grid, never all-pairs over the path). Herringbone: 90-degree herringbone of length x width turned 45 degrees plus `rotation`; a grid when length equals width.

- [ ] **Step 4: Run the test to verify it passes.**

---

### Task 2: Server validation and presets

**Files:**
- Modify: `chauffeur/services/twin_site_shapes.py` (`SLOTS`, `PATH_PRESETS`, `create`, `validate`, `update`)
- Test: `chauffeur/tests/test_twin_site_shapes.py` (add cases), `chauffeur/tests/test_twin_yard_material_slots.py` (run as a neighbour)

**Interfaces:**
- Consumes: Task 1's estimate formula (mirrored in Python, not imported).
- Produces: a path piece may carry `pavers` (object, all seven fields filled on save) or omit it. `update` accepts `{'pavers': {...}}` (merged over defaults, then stored whole) and `{'pavers': None}` (removes the field). `SLOTS['hardscape'] == ('surface', 'edging', 'joint')`. `PATH_PRESETS['paver']` includes `'pavers': dict(PAVER_DEFAULTS)`.

- [ ] **Step 1: Write the failing tests** in `test_twin_site_shapes.py`:
  - `create` with `preset='paver'` stores `pavers == {'layout':'grid','length_in':24,'width_in':24,'gap_in':3,'rotation':0,'edge':'whole','joint':'grass'}`; `preset='sidewalk'` stores no `pavers`.
  - `update` with each out-of-range value (`length_in: 1`, `width_in: 61`, `gap_in: -1`, `rotation: 91`, `layout: 'basket'`, `edge: 'half'`, `joint: 'moss'`, an unknown key) raises `ValueError`.
  - `update` with `{'pavers': {'layout': 'herringbone'}}` stores all seven fields with the others at defaults.
  - `update` with `{'pavers': None}` removes the field.
  - a 200 ft path, width 4, with `{'length_in': 2, 'width_in': 2, 'gap_in': 0}` raises `ValueError('Use larger pavers or a shorter path.')`.
  - a path without `pavers` validates and updates exactly as before (an existing case run unchanged).
  - `materials: {'joint': ...}` accepted on a path.

- [ ] **Step 2: Run** `python tests/test_twin_site_shapes.py`; expect the new cases to fail.

- [ ] **Step 3: Implement** in `twin_site_shapes.py`: `PAVER_DEFAULTS`, `MAX_PAVERS = 5000`, a `pavers(value)` validator returning the filled dict, the estimate (centre-line length from the points; rounded corners can be ignored for the estimate), `create` allows `pavers`, `update` allows `pavers` for paths, `validate` checks it when present.

- [ ] **Step 4: Run** `python tests/test_twin_site_shapes.py` and `python tests/test_twin_yard_material_slots.py`; both pass.

---

### Task 3: Paver mesh in the yard build

**Files:**
- Create: `chauffeur/static/twin/paver_geometry.js`
- Modify: `chauffeur/static/twin/twin_yard.js` (hardscape part), `chauffeur/static/twin/path_shapes.js` (`pathPresets.paver` gains `pavers: { ...PAVER_DEFAULTS }`)
- Test: `chauffeur/tests/test_twin_paver_yard_js.py` (new); neighbours `tests/test_twin_site_drawing_js.py`, `tests/test_twin_yard_reuse_js.py`, `tests/test_twin_yard_material_slots_js.py`

**Interfaces:**
- Consumes: `paverLayout`, `paverSettings` (Task 1); `groundAt(plan, x, y)` from `static/twin/twin_ground.js`.
- Produces: `export function paverGeometry(plan, path, layout) -> THREE.BufferGeometry` (positions in the yard's frame: x = lot x, y = up, z = -lot y; normals; `uv`), one prism per paver: top 1 in (1/12 ft) above `groundAt(centre) + (path.elevation || 0)`, 0.25 in bevel, sides down to 2 in below that ground; planar top uv with a per-paver offset from a hash of `path.id` and `index`.

- [ ] **Step 1: Write the failing tests** (node, `buildYard` on a small plan as in `test_twin_site_drawing_js.py`):
  - a path with `pavers` (grid, joint grass) yields exactly one mesh owned by `{kind:'hardscape', pieceId}` for its surface, with triangle count = pavers x (prism triangles), and no continuous slab mesh for it.
  - `joint:'gravel'` adds one strip mesh using kit role `base`; `joint:'sand'` one strip mesh with the plain sand material (`#cdb994`); `joint:'none'` and `'grass'` add none.
  - with `materials:{joint: <slot>}` and gravel, the strip uses the slot's material.
  - curb edging still builds with pavers.
  - a paver's top is 1/12 ft above `groundAt` at its centre on a pad (`terraces` height -2) and with `elevation: 1`.
  - a path without `pavers` builds the same meshes as before (compare mesh count and triangle count with the build before the change: assert against a slab built from `pathSurfacePolygons`).
  - `pathPresets.paver.pavers` deep-equals `PAVER_DEFAULTS`.

- [ ] **Step 2: Run** `python tests/test_twin_paver_yard_js.py`; expect failure.

- [ ] **Step 3: Implement** `paver_geometry.js` and the hardscape branch: when `paverSettings(h)` is set, build `paverGeometry` through `surfaceMesh` with the path's surface material and owner; for gravel/sand draw the strip with `surface(poly, e + 0, e + 0.5/12)` per `pathSurfacePolygons` (where `e` is the elevation), else no strip; curb as today. Mark the paver geometry like the curb (`geometry.userData.paverPath = true`).

- [ ] **Step 4: Run** the new test and the three neighbours; all pass.

---

### Task 4: Grass in the joints

**Files:**
- Modify: `chauffeur/static/twin/yard_grass.js` (`grassCovers`, `buildGrass`)
- Test: `chauffeur/tests/test_twin_yard_grass_js.py` (add cases); neighbour `tests/test_twin_post_js.py`

**Interfaces:**
- Consumes: `paverLayout`, `paverSettings` (Task 1).
- Produces: `grassCovers(plan)` entries for a grass-joint paver path are one `{polygon, margin, paver: true}` per paver (margin 0; `buildGrass` widens a `paver` cover by the clump reach `.13 * spread`), instead of the strip polygons. `export function jointClumps(plan, spread) -> Float32Array` of instance matrices (16 per clump) for joint grass, which `buildGrass` writes into the same field mesh within the tier budget, after the field clumps; the `buildGrass` result gains `jointInstances` (the count of joint clumps at the end of the instance buffer).

- [ ] **Step 1: Write the failing tests:**
  - covers: a grass-joint paver path gives one cover per paver; gravel/sand/none give the strip polygons with margin .4 as today; a path without `pavers` unchanged.
  - field: on a lot with one grass-joint grid path, no clump root (matrix translation) lies inside any paver polygon grown by `.13 * spread`, except joint clumps; every joint clump root lies on a joint segment (within 1e-6 of it) and its across scale keeps its reach within `jointWidth / 2`.
  - budget: `instances` never exceeds `TIERS[tier].lawnBlades`; a tier with `lawnBlades: 0` adds no joint clumps.
  - the field stays one mesh, one draw.

- [ ] **Step 2: Run** `python tests/test_twin_yard_grass_js.py`; expect the new cases to fail.

- [ ] **Step 3: Implement.** Joint clumps every 0.15 ft along each joint segment, yaw along the joint, scaled across so the clump fits the joint, height scale .6; skip joints narrower than 0.5 in. Placed only where the lawn grows grass (`growsGrass`) and inside the lot.

- [ ] **Step 4: Run** the test and the neighbour; both pass. Report the field build time on the test plan before and after (node `performance.now()` around `buildGrass` with a 60 ft grass-joint path).

---

### Task 5: Path card

**Files:**
- Modify: `chauffeur/static/twin/editor/site_shape_shelf.js` (path section), `chauffeur/static/twin/editor/terrain_tools.js` only if the preset field needs the new preset (it reads `pathPresets`, so likely no change)
- Test: `chauffeur/tests/test_twin_paver_card_js.py` (new, node, driving `drawSiteShapeShelf` as `tests/test_twin_site_drawing_js.py` does); neighbours `tests/test_twin_terrain_tools_js.py`, `tests/test_twin_site_drawing_js.py`

**Interfaces:**
- Consumes: `PAVER_DEFAULTS` (Task 1); the server op shape from Task 2.
- Produces: path card controls labelled exactly: `Surface` (Solid, Pavers), `Layout` (Stepping stones, Grid, Running bond, Diagonal, Herringbone), `Paver length (in)`, `Paver width (in)`, `Gap (in)`, `Rotation (degrees)`, `Edges` (Whole pavers only, Cut at the edge), `Joints` (Grass, Gravel, Sand, None). The Joint material slot (label `Joint`) shows only for gravel or sand.

- [ ] **Step 1: Write the failing tests:**
  - a path without `pavers` shows `Surface` = Solid and none of the paver controls.
  - choosing Pavers sends one op whose change is `{pavers: PAVER_DEFAULTS}`; choosing Solid on a paver path sends `{pavers: null}`.
  - changing Layout to Herringbone sends `{pavers: {...current, layout:'herringbone'}}` (the whole object).
  - number inputs carry `min`/`max` from the spec ranges.
  - the Joint slot shows for gravel and sand only.
  - read-only (`canEdit` false) disables every paver control.

- [ ] **Step 2: Run** `python tests/test_twin_paver_card_js.py`; expect failure.

- [ ] **Step 3: Implement** in the `if (path)` block, using the card's existing `field` and `choice` helpers; `siteMaterialSlots` adds `['joint', 'Joint', ...]` for a path with gravel or sand joints.

- [ ] **Step 4: Run** the test and both neighbours; all pass.

---

### Task 6: Browser check (Claude)

**Files:**
- Create: `chauffeur/tests/test_twin_paver_paths_live.py` (Chromium, test household, the `H` helpers as in `tests/test_twin_site_drawing_live.py`)

- [ ] Draw a Paver path with the terrain card's "Paver path" button: the saved path has the default `pavers`; the yard has a paver mesh for it.
- [ ] On its card, set Layout to Herringbone: one op, the mesh changes; undo restores grid.
- [ ] Set Surface to Solid: the path draws as a slab again.
- [ ] Screenshot a grass-joint grid path and a herringbone path on High for the household.
