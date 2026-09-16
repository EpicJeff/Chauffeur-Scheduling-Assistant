# Regular House + Orbit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dollhouse becomes two rectangles with two configurable block roofs (main 21.8 × 20.65 with the study and two enclosed future rooms inside it; a set-back garage block holding garage + mudroom), and the panel can orbit the exterior in eight tweened stops.

**Architecture:** All geometry lives in `chauffeur/static/house.js` inside `buildRoom()`; every shell piece registers through `shellRegister`/`regFabric` so occlusion, navigation and merge fencing need no new solver code. `shellGable` gains a `ridge` parameter and a `hip` form. The facade generator's Python/JS face tables (`services/house_facade.py`, `house.js` `FACES`) are re-derived from the two blocks. The orbit is eight camera positions on a circle around a pivot, driven through the existing `tween` slot, with chevrons/swipe/URL/keys as the hand path and the panel's idle-return snapping to stop 0.

**Tech Stack:** three.js (vendored) in `house.js`; Python/FastAPI services; Playwright live tests (`tests/live_app.py`); `tools/house_probe.py` for budgets.

**Spec:** `docs/superpowers/specs/2026-09-16-regular-house-orbit-design.md` (binding; read §2–§5 before Task 2, §4 before Task 4).

## Global Constraints

- Every task ends with: read `chauffeur/config.yaml` `version:`, bump the patch, verify with `grep ^version`; ONE full sweep from the repo root in the FOREGROUND (`env -u HA_BASE_URL python chauffeur/tools/test.py`, Bash timeout 600000, never a second concurrent run); commit with the version in the subject `(vX.Y.Z)`; push. Known parallel-load flakes (re-run solo only if they are the only reds): `test_screensaver`, `test_study_live`, `test_negotiation_cost`, `test_trip_scheduler`.
- house.js laws: every geometry through `cgeo`, every material through `mat()`/`box()` opts, `mkTex` owns textures, no per-frame work, render-on-demand; every shell piece registers through `shellRegister`/`regFabric`; ghost edges stay OFF (cutaways only); palette hex only in `PALETTE`.
- Never drop functionality unasked: the spec's Deleted list is the whole permission. `patio_slider` and `living_back_room_door` stay as interior openings; every zone, card and marker keeps working; the exterior Kitchen marker moves to `back_door`.
- Budgets (quality=high `--day`): `buildMs` ≤ 1500; per-view and per-stop in-frustum recorded before/after — this arc RE-BASELINES (expect drops); no view may exceed its pre-arc number by more than +2 except where the spec adds geometry the camera now sees (north/east windows, back door, patio slab), which must be itemised.
- Tests are standalone scripts (`from harness import check`, `scenario_*`, runner at the bottom). Live tests: `cd chauffeur && env -u HA_BASE_URL python tests/test_house_live.py` (~6 min). Probe: `cd chauffeur && env -u HA_BASE_URL python tools/house_probe.py --views all --budget --quality high --day --out ../scratch/<name>`.
- No browser dialogs. Commit messages in prose, ending `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; commit via a Bash heredoc.

---

## File map

| file | responsibility in this arc |
|---|---|
| `chauffeur/static/house_study.js` | study translation (`NORTH`/`SOUTH`) |
| `chauffeur/static/house.js` | footprint, block roofs (`ridge`, `hip`), future rooms, back door/windows/patio, orbit stops/tween/input, hints, exposure (`chfOrbit*`) |
| `chauffeur/static/house_features.js` | `living_back_room_door` position check; nothing else |
| `chauffeur/templates/house.html` | orbit chevrons markup + CSS; `?angle=` read |
| `chauffeur/services/house_facade.py` | `FACES` two faces; `CANONICAL` re-snapped |
| `chauffeur/tests/test_house_facade.py` | slot/canonical expectations |
| `chauffeur/tests/test_house_live.py` | registry tables, footprint pin, orbit scenario, canonical mesh pin |
| `chauffeur/tests/test_house_life_live.py` | `patio_slider` verdict expectations (now interior) |
| `chauffeur/tools/house_probe.py` | `--angle N`, `--views orbit` |
| `chauffeur/system_capabilities.md`, `docs/house_style_bible.md`, spec §10 | wrap |

---

### Task 1: Study translation

**Files:**
- Modify: `chauffeur/static/house_study.js:11` (`NORTH`, `SOUTH`)
- Modify: `chauffeur/static/house.js` (`STUDY_POS`/`STUDY_AT` ~356-357; `ROOM_AABB`/study zone bounds if any literal cites z 9.8..16.72 — grep `16.72`, `16.62`, `9.88`, `9.8` near study code)
- Modify: `chauffeur/static/house_features.js` (`living_study_door` fixture position if it cites a z inside the old study span — read lines ~100-112)
- Test: `chauffeur/tests/test_house_live.py` (study lean-in scenario, if one exists — grep `study`), `chauffeur/tests/test_study_live.py`

**Interfaces:**
- Produces: the study occupies x 6.85..14.65, z 7.65..14.55 (was 9.8..16.72); `STUDY_POS = (5.85, 3.65, 15.83)`, `STUDY_AT = (12.30, 1.45, 10.68)` (both z − 2.17).

- [ ] **Step 1: Failing pin.** In `tests/test_house_live.py` add to the existing study/navigation scenario (or a new `scenario_study_sits_inside_the_main_block`): after entering the study (`window.chfHouseEnterRoom('study')` then settle), evaluate the study group's world bounding box via a new exposure `window.chfStudyBox()` (returns `[minx,maxx,miny,maxy,minz,maxz]` of the study root, `Box3.setFromObject`) and `check(box[5] <= 14.56 and box[4] >= 7.5, ...)`. Run → fails (`chfStudyBox` missing; then max z ≈ 16.6).
- [ ] **Step 2: Translate.** `house_study.js:11`: `NORTH = 7.71, SOUTH = 14.45` (EAST/WEST unchanged). `house.js`: `STUDY_POS`/`STUDY_AT` z − 2.17. Expose `window.chfStudyBox` beside `chfShellFabric`. Fix any literal that referenced the old span (grep the four numbers above; the `roof_main` call's `cutawayRoom 'study'` is unaffected).
- [ ] **Step 3: Run `tests/test_house_live.py` and `tests/test_study_live.py`** → ok. Take `tools/house_probe.py --views study` (add `'study'` to `ROOM_VIEWS` if absent; it enters via `chfHouseEnterRoom('study')`) and view the PNG: the desk framed as before.
- [ ] **Step 4: Sweep, bump, commit, push** — `feat: the study slides north inside the main block (vX.Y.Z)`.

---

### Task 2: The footprint — two rectangles, two block roofs

**Files:**
- Modify: `chauffeur/static/house.js` — `FULL_HOUSE` (~4127), the shell block (~4090-4900: east wall, `shellGable`, the massing calls 4769-4846, `mudFrontBandG`), `mudEastG` (~6640), `mudroomRoofG` (~7048), terrace furniture (~7410-7620), `EXTERIOR_HINTS` (~10167), `AO_HAND_CARVED`
- Modify: `chauffeur/static/house_features.js:117` (keep `living_back_room_door`; verify its wall position x 6.5 z 2.45 is on the new `east_partition`)
- Test: `chauffeur/tests/test_house_live.py` (`scenario_shell_fabric_registry` ~917-1100, `scenario_navigation_real_mouse` ~1132+, `scenario_shell_without_room_is_inert` ~1398, the `massing_east_back_east` probe ~1159), `chauffeur/tests/test_house_life_live.py:79-103`

**Interfaces:**
- Consumes: Task 1's study placement.
- Produces: `FULL_HOUSE = { west: -7.15, east: 14.65, north: -6.10, south: SWZ1, eave: EXT_TOP4, overhang: 0.32 }`; `GARAGE_BLOCK = { west: -18.20, east: -7.15, north: -6.10, south: 10.10, eave: 5.6 }`; `shellGable(name, x0, x1, z0, z1, eave, ridge, room, ends, pitch, slopeRooms, depthEnds, twoSidedRoof, cutawayRoom, form)` where `ridge` is `'x'|'z'` (replaces the boolean `alongZ`: `alongZ === true` ⇔ `ridge === 'z'`) and `form` is `'gable'|'hip'` (default gable); `ROOF_FORMS = { main: {form:'gable', ridge:'x'}, garage: {form:'gable', ridge:'x'} }` read at build (spec 2 will feed it from the block model); registered names per spec §2; `window.chfRoofForms()` returns `ROOF_FORMS`.

- [ ] **Step 1: RED — the footprint pin.** Replace `expected_names` in `scenario_shell_fabric_registry` with the spec §2 set:

```python
        KEPT = {'north_wall', 'north_cladding', 'west_wall', 'west_skirt', 'west_cladding',
                'south_wall', 'garage_shell', 'garage_door', 'patio_slider',
                'living_back_room_door', 'living_study_door', 'yard',
                'roof_main_north', 'roof_main_south', 'roof_main_end_west', 'roof_main_end_east'}
        NEW = {'east_wall', 'east_partition', 'north_wall_east', 'garage_block_north', 'garage_block_west',
               'mudroom_front', 'garage_block_roof_north', 'garage_block_roof_south',
               'garage_block_roof_end_west', 'garage_block_roof_end_east',
               'back_door', 'future_room_partition'}
        DELETED_PREFIXES = ('massing_', 'mudroom_cross_roof', 'mudroom_roof', 'living_roof',
                            'mudroom_front_cladding', 'mudroom_east_finish')
        names = {f['name'] for f in fab}
        hand = {n for n in names if not n.startswith('facade_')}
        check(KEPT <= hand, f'kept pieces missing: {sorted(KEPT - hand)}')
        check(NEW <= hand, f'new pieces missing: {sorted(NEW - hand)}')
        check(not [n for n in hand if n.startswith(DELETED_PREFIXES)],
              f'deleted pieces still registered: {[n for n in hand if n.startswith(DELETED_PREFIXES)]}')
        check(hand == KEPT | NEW, f'unexpected hand pieces: {sorted(hand - KEPT - NEW)}')
```
Delete the roof-geometry checks that cite `massing_service_roof_*`, `massing_front_roof_*`, `massing_back_roof_shed` (~1022-1038) and replace with: `garage_block_roof_south`'s box top equals `roof_main_south`'s eave line within 0.02 only if both eaves are 5.6 (they are: `GARAGE_BLOCK.eave = EXT_TOP4 = 5.6`), plus `roof_main_end_east` box max x ≈ 14.65 + overhang. Rewrite the per-view `EXPECTED` verdict tables (~1053-1090) to the new names: from the kitchen the `east_partition` is solid (interior partition between kitchen and the east room — `twoSided`, hides only when the camera is on its far side), `roof_main_south` cutaway, `south_wall` cutaway; from the living `roof_main_south`, `south_wall` cutaway; from the study `east_partition` hides; garage: `garage_block_roof_south` cutaway, `garage_door` hide; mudroom: `garage_block_roof_south`, `mudroom_front` cutaway. Derive each verdict from `solveShell`'s own rule (camera on the outward side + subject inside + corridor overlap), write the derivation in the test comment, and let the RED run tell you which you got wrong — fix the table only where the geometry says so. Replace the `massing_east_back_east` probe (~1159) with `{piece:'east_wall'}`. In `test_house_life_live.py:79-103` the `patio_slider` is interior now: from the kitchen lean it is `twoSided` — read `living_study_door`'s expectations in the same file and mirror them; `interiorGlow` stays 0. Run the live file → RED on the registry scenario.

- [ ] **Step 2: Constants and the east side.** In house.js:
  - `FULL_HOUSE` → `{ west: -7.15, east: 14.65, north: -6.10, south: SWZ1, eave: EXT_TOP4, overhang: 0.32 }`; delete `wingEast/studyEast/studySouth/patioNorth/patioSouth/serviceWest/serviceSouth/wingEave/serviceEave`. Add `var GARAGE_BLOCK = { west: -18.20, east: -7.15, north: -6.10, south: 10.10, eave: EXT_TOP4 };` and `var ROOF_FORMS = { main: { form: 'gable', ridge: 'x' }, garage: { form: 'gable', ridge: 'x' } };` (override from `window.HOUSE_ROOF_FORMS` if present — a hook for spec 2; default when absent).
  - **South wall grows east**: `SW_W` becomes `FULL_HOUSE.east - FULL_HOUSE.west` (21.8) and the slab centre x `(FULL_HOUSE.west + FULL_HOUSE.east) / 2` (3.75) — both the plaster half and the siding half and the baseboard (they read `SW_W` and centre `0` today: change the three `box(...)` calls' x to the new centre). `regFabric(southWallG…)` unchanged.
  - **North side**: the kitchen's `wallB`/`north_wall` stays; add `shellWall('north_wall_east', 6.85, wallB-outer-z, 14.65, wallB-outer-z, EXT_TOP4, [0,0,-1], [[10.75, 1.35, true]])` (one window centred on the future back room) and extend `north_cladding`'s siding run to x 14.65 (read how `northCladdingG` is sized; it reads the kitchen width — parameterise on `FULL_HOUSE.east`). `north_wall_east` is already in Step 1's `NEW` set.
  - **Back door** on the north wall at x -2.0: reuse `doorAt`'s leaf/casing idiom via a small `backDoorAt(x)` that builds into its own `shellGroup`, faces −z (rotate the assembly `Math.PI`), `shellRegister(g, 'back_door', [0,0,-1], 'kitchen')`, and stamps `userData.entry = 'back_door'` on the leaf. No coach lamp.
  - **East wall** (`eastWallG`, ~4096-4120): rebuild at x = 14.65 (`EWX0_4 = FULL_HOUSE.east - WALL_T4`, `EWX1_4 = FULL_HOUSE.east`), z from `EWZ0_4` (wallB outer) to `SWZ1`, with three `shellWindow`s at z 11.1 (study), 4.6 (east room), -2.3 (back room), normal `[1,0,0]`, name `east_wall`, `room: null` (an exterior side wall fronting three rooms; `cutawayRoom` null). The OLD east wall geometry at x 6.85 becomes `east_partition`: a plain interior partition (`C.wall` both faces, `sharp(WALL_O)`), full length -5.725..14.55 minus the two openings (the patio slider at z 5.8 and the study door — leave those pieces' openings as gaps: build the partition as three boxes z -5.725..4.5, 7.1..(study door z − 0.9), (study door z + 0.9)..14.55; read `living_study_door`'s z from house_features.js), registered `regFabric(eastPartG, { name: 'east_partition', n: [1,0,0], twoSided: true, room: null })`.
  - **Patio slider → interior**: keep `patioSliderG` where it is (x 6.85, z 5.80); its registration becomes `shellRegister(patioSliderG, 'patio_slider', [1, 0, 0], 'kitchen', true /* twoSided */)`; the glow stays off (`interiorWindow` on both panes).
  - **Future rooms**: floors — two `box(7.45, 0.1, depth, C.floor, cx, -0.05, cz, extG, sharp())` slabs (east room z 1.5..7.65, back room z -6.1..1.5) using the kitchen floor's material opts (read `floor`'s material at ~1397); `future_room_partition`: a wall box at z 1.5 from x 6.85..14.65, `regFabric(g, { name: 'future_room_partition', n: [0,0,1], twoSided: true })` (no room). Ceilings: none (the roof closes them). No zones, no cameras.
  - **Back patio slab**: `box(5.2, 0.16, 5.5, EXTC.drive, -2.0, -0.08, -9.0, extG, sharp({ rough: 0.95, map: driveT }))` outside the back door (z -6.1 is the north wall; the slab runs -6.3..-11.8). Not registered.
  - **Delete**: the terrace slab and furniture (~7410-7620: every block whose comment says terrace), `shellWall('massing_east_front_south'|'…_east'|'…_patio')`, `shellGable('massing_front_roof')`, `shellWall('massing_east_back_north'|'…_east'|'…_patio')`, the `massing_back_roof_*` IIFE (~4793-4825), `shellWall('massing_service_north'|'…_west'|'…_south')`, `shellGable('massing_service_roof')`, `shellGable('mudroom_cross_roof')`, `mudroomRoofG` (~7048) and whatever builds into it, `mudFrontBandG` (~4840-4846), `mudEastG`'s `mudroom_east_finish` registration (~6640) — fold its geometry into the garage block's east partition below if it is the mudroom/kitchen party wall, else delete; `living_roof` registration and its empty group. Grep afterwards for every deleted name: zero hits outside comments.

- [ ] **Step 3: The garage block.**
  - Walls: `shellWall('garage_block_north', -18.20, -6.10, -7.15, -6.10, GARAGE_BLOCK.eave, [0,0,-1], [])`; `shellWall('garage_block_west', -18.20, -6.10, -18.20, 10.10, GARAGE_BLOCK.eave, [-1,0,0], [[2.0, 1.35, true]])`; the garage's own `garage_shell` (x -18.08 / -12.72 side walls, back wall at z 2.12) stays as the garage ROOM's walls — the block's outer walls sit outside them by 0.12; the space z -6.1..2.12 behind the garage back wall is enclosed shell (like the future rooms; no floor needed — no camera sees it). `mudroom_front`: the mudroom's street face at z 10.10 from x -12.6..-7.15 = today's `mudFrontBandG` band re-authored as a full-height `shellWall('mudroom_front', -12.60, 10.10, -7.15, 10.10, GARAGE_BLOCK.eave, [0,0,1], [])` with `room: 'mudroom'` (pass room through `shellRegister` — `shellWall` registers `room: null`; add an optional `room` argument to `shellWall` defaulting to null). The mudroom's existing walls/door/window at z 8.2-8.44 stay inside.
  - Roof: `shellGable('garage_block_roof', GARAGE_BLOCK.west, GARAGE_BLOCK.east, GARAGE_BLOCK.north, GARAGE_BLOCK.south, GARAGE_BLOCK.eave, ROOF_FORMS.garage.ridge, null, null, Math.PI / 8, ['garage', 'mudroom'] /* slopeRooms north/south */, null, false, null, ROOF_FORMS.garage.form)` — read how `slopeRooms` maps to the two decks today (`sign < 0 ? [0] : [1]`) and give the south deck `cutawayRoom` handling for both garage and mudroom: since `cutawayRoom` is a single value, register the south deck with `room: 'garage'` and add the mudroom via the solver's normal half-space test (the mudroom camera is south of the deck too). Verify with the mudroom and garage EXPECTED tables.
  - `roof_main`: `shellGable('roof_main', FULL_HOUSE.west, FULL_HOUSE.east, FULL_HOUSE.north, FULL_HOUSE.south, EXT_TOP4, ROOF_FORMS.main.ridge, null, null, Math.PI / 8, ['kitchen', 'living'], null, false, 'study', ROOF_FORMS.main.form)`.
  - `AO_HAND_CARVED` unchanged (`garage_shell` still has its door opening).

- [ ] **Step 4: `shellGable` — `ridge` + `hip`.** Rename the `alongZ` parameter to `ridge` (`'z'` ⇔ old `true`); update every call site (grep `shellGable(`). Add `form` as the last parameter: when `'hip'`, the two ridge decks become trapezoids (an `ExtrudeGeometry` from a `Shape` with the two eave corners at `±half` and the two ridge corners inset by `run` — the hip's run equals the main run so all four pitches match) and the two `ends` become triangular decks (a `Shape` triangle eave-eave-ridge point) with the same shingle material and `shellRegister(... name + '_end_west' …)` — no gable-end batten infill. Geometry through `cgeo` keyed on `'shell-hip|' + half + '|' + depth + '|' + eave + '|' + pitch + '|' + form`. Ridge caps: for hip the ridge is shorter by `2·run` — derive. Build both blocks with `form:'hip'` once via `window.HOUSE_ROOF_FORMS = {main:{form:'hip',ridge:'x'}, garage:{form:'hip',ridge:'z'}}` in an init script (probe `--roof hip` or a test init script) and screenshot; zero console errors.

- [ ] **Step 5: Markers.** `EXTERIOR_HINTS`: `['back_door', 'Kitchen', [...same icons...], 'entry']` replaces the `patio_slider` row; `['mudroom_front', 'Mudroom', ...]` replaces `mudroom_cross_roof_south`; `front_door` and `garage_front` unchanged. Update `scenario_navigation_real_mouse`'s `exterior_targets` to `{'back_door', 'front_door', 'mudroom_front', 'garage_front'}` and its entry clicks (the Kitchen entry via `{entry:'back_door'}` needs an orbit stop that sees the north wall — until Task 4 lands, assert the marker is ABSENT at stop 0 and reachable via `chfNavProbe({entry:'back_door'})` returning null there; Task 4 turns that into a positive check).

- [ ] **Step 6: Live file green; budget re-baseline.** `tests/test_house_live.py` all ok (the canonical facade mesh pin `CANONICAL_EXTERIOR_MESHES` WILL change — re-record RED-first with the new number and update the comment's derivation); `tests/test_house_life_live.py` ok; `tests/test_study_live.py` ok. Probe `--views all --budget --quality high --day` → table (expect exterior to drop); also `--views exterior` with the hip init script for both blocks → record.

- [ ] **Step 7: Sweep, bump, commit, push** — `feat: the regular house — two rectangles, two block roofs, hip form, ridge parameter (vX.Y.Z)` with the before/after table and the deleted/new piece lists in the body.

---

### Task 3: Facade faces re-derived

**Files:**
- Modify: `chauffeur/services/house_facade.py` (`FACES`, `CANONICAL`, `worst_case` if slot indices are hard-coded)
- Modify: `chauffeur/static/house.js` (`FACES` JS mirror; `roofPlaneEave`/`ROOF_PLANE_EAVE`; `gableAt`'s garage special case now reads the garage block extents)
- Test: `chauffeur/tests/test_house_facade.py`, `chauffeur/tests/test_house_live.py` (parity pin, registry facade names)

**Interfaces:**
- Produces: `FACES = [garage_block (-18.20..-7.15, z 10.10, eave 5.6, room 'garage', roof 'garage_block_roof'), main (-7.15..14.65, z 14.55, eave 5.6, room 'living', roof 'roof_main')]`; 18 slots (0–5, 6–17); `CANONICAL` re-snapped by the rule.

- [ ] **Step 1: Compute, don't guess.** `python -c "from services import house_facade as hf; ..."` with the new FACES to print slot centres; snap today's world positions (windows -4.525, -1.025, 4.225; door 0.725; wing windows 9.775, 11.725; porch centre 0.1 width 7.0; garage door -15.4) to nearest slots; write the numbers into `CANONICAL` and into `scenario_slot_table_is_derived_from_the_faces` / the canonical expectations (mudroom-face slots are now part of the garage-block face: the garage door spans slots 0–2 of six; `normalize`'s "garage door spans its own bay" rule must pin to the garage ROOM's x range (-18.2..-12.6 → slots 0–2), not the whole face — adjust `_face_range('garage')` usage to a new `GARAGE_BAY_SLOTS = (0, 2)` derived from the bay x range).
- [ ] **Step 2: RED**: run `tests/test_house_facade.py` → the face count/slot assertions fail; update the tests to the computed numbers (18 slots: 6 + 12; canonical door slot; porch span) and the JS `FACES`; `roofPlaneEave` table → `{ garage: GARAGE_BLOCK.eave, main: EXT_TOP4 }`; `gableAt` garage special case reads `GARAGE_BLOCK.west/east` and z `4.0..10.1` as today.
- [ ] **Step 3: GREEN**: `tests/test_house_facade.py` all ok; live parity + registry + worst-case scenarios ok; `worst_case()` re-probed (`--facade worst`) and recorded.
- [ ] **Step 4: Sweep, bump, commit, push** — `feat: facade faces follow the two blocks (vX.Y.Z)`.

---

### Task 4: Orbit

**Files:**
- Modify: `chauffeur/static/house.js` (camera constants ~324-357; `goExterior` ~9717; `tween` ticker ~9150-9165; keydown ~10444; pointer handling around `onTap`; exposure block; idle hook)
- Modify: `chauffeur/templates/house.html` (chevrons markup + CSS beside `#house-back`; `?angle=` param)
- Modify: `chauffeur/tools/house_probe.py` (`--angle`, `--views orbit`)
- Test: `chauffeur/tests/test_house_live.py` (new `scenario_orbit_eight_stops`; `scenario_navigation_real_mouse` back-door entry)

**Interfaces:**
- Produces: `ORBIT = { pivot: T.Vector3(-1.8, 4.0, 4.2), radius, height: 31, a0 }` with `radius = hypot(EXT_POS.x - pivot.x, EXT_POS.z - pivot.z)` and `a0 = atan2(EXT_POS.z - pivot.z, EXT_POS.x - pivot.x)`; `orbitPos(k) = pivot + (r cos(a0 + k·π/4), 31, r sin(a0 + k·π/4))`; `orbitAt = pivot`; `window.chfOrbitStop()` → current k; `window.chfOrbitTo(k)` (tweened, exterior only, returns false inside a room); `window.chfOrbitStep(±1)`; URL `?angle=N` boots at stop N; keys ← → at the exterior; a horizontal swipe ≥ 60px on the canvas at the exterior steps; idle-return snaps to 0.

- [ ] **Step 1: RED scenario.**

```python
def scenario_orbit_eight_stops():
    """Spec 2026-09-16 §4: eight tweened stops around the pivot; every stop
    settles clean, draws at least one marker, and every entrance is reachable
    from some stop."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high&angle=3'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == 3, '?angle=3 boots at stop 3')
        seen = {}
        for k in range(8):
            page.evaluate('window.chfOrbitTo(%d)' % k)
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            page.wait_for_timeout(300)
            check(page.evaluate('window.chfHouseMode()') == 'exterior', 'orbit never leaves the exterior')
            n = page.locator('#house-hints:not([hidden]) .house-hint').count()
            check(n >= 1, f'stop {k} draws at least one marker (got {n})')
            for spec in ("{entry:'front_door'}", "{entry:'back_door'}", "{piece:'mudroom_front'}", "{front:'garage'}"):
                if page.evaluate('window.chfNavProbe(%s)' % spec):
                    seen[spec] = k
        check(len(seen) == 4, f'every entrance reachable from some stop: {seen}')
        # a swipe steps once
        before = page.evaluate('window.chfOrbitStop()')
        box = page.locator('#room canvas').bounding_box()
        page.mouse.move(box['x'] + box['width'] * 0.7, box['y'] + box['height'] * 0.5)
        page.mouse.down(); page.mouse.move(box['x'] + box['width'] * 0.3, box['y'] + box['height'] * 0.5, steps=8); page.mouse.up()
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == (before + 1) % 8, 'a left swipe advances one stop')
        page.keyboard.press('ArrowLeft')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == before, 'ArrowLeft steps back')
        # entering a room and leaving returns to the CURRENT stop
        page.evaluate("window.chfOrbitTo(5)")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        page.evaluate("window.chfHouseEnter()")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        page.evaluate("window.chfHouseExit()")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == 5, 'exit returns to the stop you left from')
        check(not errors, f'zero console errors across the orbit: {errors[:3]}')
```
Add to the runner. Run → fails (`chfOrbitStop` missing).

- [ ] **Step 2: Implement.** In house.js: `ORBIT` constants after `EXT_POS/EXT_AT`; `var orbitStop = parseInt(new URLSearchParams(location.search).get('angle') || '0', 10) % 8`; `function orbitPos(k)`; initial `cam.position.copy(orbitPos(orbitStop))` and `cam.lookAt(ORBIT.pivot)` where `EXT_POS` was used at boot (~358); `goExterior` tweens to `orbitPos(orbitStop)` / `ORBIT.pivot` instead of `EXT_POS/EXT_AT` and calls `solveShell(orbitPos(orbitStop), null)`; `function orbitTo(k, cb)` — exterior only, `k = ((k % 8) + 8) % 8`, sets `orbitStop`, `solveShell(orbitPos(k), null)`, tweens `fromP → orbitPos(k)`, `fromA → pivot`, then `scheduleHint()`; `orbitStep(d) = orbitTo(orbitStop + d)`. Keep `webgl.EXT_POS/EXT_AT` exported for the probe/`chfHouseCam` callers but make them getters of the current stop (`Object.defineProperty`) so nothing else moves. Keys: extend the keydown handler — at the exterior, `ArrowLeft → orbitStep(-1)`, `ArrowRight → orbitStep(1)`. Swipe: on the canvas `pointerdown` record x/y/time; on `pointerup` if `mode === 'exterior'`, `|dx| ≥ 60`, `|dy| < |dx|`, `dt < 800ms` → `orbitStep(dx < 0 ? 1 : -1)` and suppress the tap (`onTap` must not fire for a swipe — set a `swiped` flag it checks). Idle: wherever the page handles `panel_idle_return_seconds` (grep in `house.html`/the shared panel script — it reloads or navigates to the home board; if the house IS the home board it stays), add `if (mode === 'exterior' && orbitStop !== 0) orbitTo(0)` before the return. Exposure: `window.chfOrbitStop/chfOrbitTo/chfOrbitStep`. `house.html`: two `<button class="house-orbit" data-dir="-1|1" aria-label="Rotate left/right">` fixed at bottom-left/right (56px, same look as `#house-back`), shown only at the exterior (toggle `hidden` where `#house-back` is toggled), wired to `chfOrbitStep`.
- [ ] **Step 3: Probe.** `--angle N` (default 0): set `window.chfOrbitTo(N)` after the exterior settles; `--views orbit` expands to `orbit0..orbit7` (each `chfOrbitTo(k)` + settle + shot + budget line). Run `--views orbit --budget --quality high --day` → eight lines; record the worst stop.
- [ ] **Step 4: Live file green** (the orbit scenario; `scenario_navigation_real_mouse` now enters the kitchen via the back door from a north stop — `chfOrbitTo(4)` first, then `{entry:'back_door'}` click → mode kitchen). Note in the report how the north stops read (fill light); if a facade is unreadably flat, add the ONE permitted static fill (spec §4) and re-run the kitchen-ratio gate from the quality pass (`tools/house_probe.py --views kitchen` before/after, ratio within 1.02).
- [ ] **Step 5: Sweep, bump, commit, push** — `feat: orbit the house in eight stops (vX.Y.Z)` with the eight-stop budget table.

---

### Task 5: Wrap

**Files:** `chauffeur/system_capabilities.md` (new entry after the facade generator entries; bump `Current through`), `docs/house_style_bible.md` (a "massing" note: two blocks, block roofs `{form, ridge, pitch}`), spec §10 Results, memory (controller).

- [ ] **Step 1:** capabilities entry in the file's voice: the regular house (two rectangles, what was deleted and why, the future rooms, the study move, the interior slider/back-room door, the back door marker), block roofs with `form`/`ridge`, the orbit (stops, hand path, idle snap, lighting caveat), faces re-derived (6 + 12), budgets before/after per view and per stop, pins. Ends with **NOT device-verified.**
- [ ] **Step 2:** spec §10 tables + deviations; style bible note.
- [ ] **Step 3:** bump, commit (docs-only, no sweep), push — `docs: regular house + orbit wrap (vX.Y.Z)`.
