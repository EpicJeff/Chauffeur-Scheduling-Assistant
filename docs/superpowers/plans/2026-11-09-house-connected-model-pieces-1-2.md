# The house as a connected system, pieces 1 and 2: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the house as a connected model and give it a real house editor. The model has walls joined at joints, rooms derived from walls, everything hosted on a surface, and roofs as areas with an edge setting per edge. The editor has visible selection, room-first handles, snapping, drawing, roof editing, undo, a library, and placement on the lot inside the 3D scene.

**Architecture:**
- **The model is the stored truth.** The connected model (schema `chauffeur.twin.plan/3`) lives in new `services/twin_model*.py` modules, and the round store stores it.
- **A bridge keeps every existing consumer running unchanged.** These consumers are the build pipeline, director, place reads, the generator and the record download.
  - `flatten(model)` gives them the schema-2 shape they read today, plus extras.
  - `assemble(flat, previous)` turns what they write back into the model. It is the same routine as the migration.
- **All editing goes through one operation set,** `twin_model_ops.apply`. The browser previews joint moves locally at frame rate and commits each operation on release. The server re-derives everything.

**Tech Stack:**
- Python 3 for the FastAPI services.
- three.js ES modules for `static/twin`.
- Plain-script tests run from `chauffeur/`.
- node for the JS module tests.
- Playwright through `tests/live_app.py` for the browser tests, which the controller runs.

**Spec:** `docs/superpowers/specs/2026-11-09-house-connected-model-design.md` (approved 2026-11-09). Read §3, §4 and §5 before any task. §8 says what is kept, replaced and retired.

## Global Constraints

- **Tests**
  - Run as `env -u HA_BASE_URL python tests/<file>.py` from `chauffeur/`.
  - Set `CHAUFFEUR_DATA_DIR` to a temp dir before importing services. Never touch `chauffeur/data`.
  - Run a task's own tests plus its named neighbours. Never run the full suite.
  - Every critical path needs one test that actually runs it: a TestClient request, a node run or a live scenario.
- **No browser dialogs:** use `showGlobalAlert`, `promptConfirm` and `promptInput` from `templates/components/control_center.html`.
- **UI work:**
  - Read `chauffeur/docs/ui_design_guide.md` first.
  - The same concept uses the same shared builder.
  - Run `python tools/build_tailwind.py` after any template class change.
- **Vendored Alpine:** coerce bound booleans with `!!`.
- **No dropped functionality.** Every ability a person has today keeps a home. Spec §8.3 lists the only retirements: the 2D Plan mode, the Your place SVG map once its abilities are in the scene, and the legacy per-floor build path. The legacy path is NOT removed in this plan.
- **Agent parity:** every edit is reachable by Argyle's `house_design` tool through the same operations.
- **No Home Assistant work here.** Every Home Assistant touchpoint is piece 3.
- **No new packages:** never add packages to `requirements.txt`.
- **Fixed values from the spec:**
  - Weld tolerance: 1 ft.
  - Snap order: joints, wall lines and their extensions, right angles, anchors, the walls of the level below, a 1 in grid (1/12 ft).
  - A wall that changes length keeps its items at their distance from the end that did not move, clamped onto the wall.
  - Floor and ceiling items keep their relative position (u, v as fractions of the room's bounding box).
  - Roof areas are rectilinear polygons only. Edge settings are `sloped` (pitch 1-24), `gable` and `clip`.
  - Roofs may overlap, and the higher surface wins.
- **Fixed copy** (exact text):
  - Unclosed room: `This room isn't closed: a wall is missing here.`
  - Migration separator: `I added an invisible wall here to keep the {a} and the {b} apart; check it.` If either name is the generic `Room`, use `I added an invisible wall here to keep two rooms apart; check it.`
  - Unhosted item: `This {kind} lost its wall; place it again.` Use `lost its surface` when the host was a floor, ceiling or roof.
  - Proposal buttons: `Use this` and `Dismiss`.
  - Material source on the card: `{Material name}, from the {building|level|room}`. A surface override reads `{Material name}, set here`.
- **Ownership (§4.6a):** a piece touched by a person's operation carries `src.person: true`. A re-read never overwrites it. A disagreeing read becomes a proposal.

## Rulings made while planning

- **P1.** The store returns the flat view from `current()` so the build pipeline is untouched. New code reads `current_model()`.
  - *Cost if wrong:* a second migration later when consumers move to the model.
- **P2.** During a drag, walls, floors, ceilings and hosted items update live. Roofs update on release.
  - The spec requires a frame-rate drag; roof re-solving in the browser would duplicate roof logic.
  - *Cost if wrong:* roofs lag one release behind the drag.
- **P3.** The frame-rate target is at most 33 ms per drag update (30 fps) on the household's migrated house in Chromium on the dev GPU.
- **P4.** Yard plants and furniture stay in `site.planting` and `site.furniture`. They become selectable, movable, deletable and addable through operations that record into `compose_overrides`. That is how §5.7's "ordinary items" requirement is met without moving the yard composer.
- **P5.** Undo and redo are per session. Each operation's round id is pushed onto a client stack. Undo reverts to the round that was current before the operation (`POST /api/house/twin/revert`), and redo reverts to the later round. Undo is disabled while a build runs.
- **P6.** The migration fixture is the plan inside the user's `house-build-record-2026-11-09.json`, copied to `tests/fixtures/twin_model/household-2026-11-09.json`. It is checked for keys (`sk-`, `AIza`, `api_key`, `key=`) before commit. The main house's rooms are all named `Room` in that read, a draft_rooms naming defect that is noted and not fixed here.

## Review Focus

1. **Two walls crossing without a shared joint,** as reads often produce. Expected: the crossing is split into joints, and the rooms on both sides are derived. Test in Task 1.
2. **A room-resizing drag that pushes a wall past a door on a perpendicular wall.** Expected: the door clamps onto its shortened wall and is never left floating, and the wall refuses to shrink below the door's width plus 0.5 ft with a plain refusal. Test in Task 4.
3. **A build round written after a person edited the walls.** Expected: the person's walls and joints keep their positions, untouched walls take the new read, and a disagreeing new wall becomes a proposal. Test in Task 5.
4. **Undo after an operation that split a wall and re-derived rooms.** Expected: the walls, rooms and their names all come back exactly. Test in Task 13.
5. **Dragging a building that is rotated 90°.** Expected: the house follows the pointer on the ground plane, not a rotated axis, and lands where it is drawn. Test in Task 16.

---

## Part A: the connected model (piece 1)

### Task 1: The wall graph (joints, splits, regions, mitres)

**Files:**
- Create: `services/twin_model_graph.py`
- Test: `tests/test_twin_model_graph.py`

**Interfaces:**
- **Produces:**
  - `weld(points: list[list[float]], tol=1.0) -> tuple[list[list[float]], list[int]]`: the welded joint positions, plus the index each input point maps to.
  - `split_crossings(joints: dict[str, list], walls: list[dict]) -> tuple[dict, list[dict]]`. Walls are `{id, joints:[a,b], kind}`. Splits every T-junction (a joint within 0.05 ft of a wall's interior) and every proper crossing, and adds joints `j:<n>`. Split walls keep their id on the first part and get `<id>~2`, `<id>~3` on the rest, copying every other field.
  - `regions(joints, walls) -> list[dict]`: the bounded faces of the planar graph, as `{joints: [ids in counter-clockwise order], polygon: [[x,y]...], area: float}`. Both solid and separator walls bound faces. A wall with a free end (a dangling wall) bounds nothing.
  - `open_ends(joints, walls) -> list[list[float]]`: the positions of joints with exactly one wall.
  - `footprints(joints, walls) -> dict[str, list[list[float]]]`: per solid wall, a 4-point footprint `[from_left, to_left, to_right, from_right]`. Left is the side to the left of `from` to `to`. Each end is mitred against the other solid walls at that joint along the angle bisector of the adjacent pair; a free end is square. Separators get none.

- [ ] **Step 1: Write the failing tests**

```python
def test_t_junction_splits_and_makes_two_rooms():
    # 10x8 box plus an interior wall from (5,0) to (5,8) whose ends lie on the box's walls
    j, w = split_crossings(BOX_JOINTS, BOX_WALLS + [{'id': 'mid', 'joints': ['m0', 'm1'], 'kind': 'solid'}])
    r = regions(j, w)
    assert sorted(round(x['area'], 3) for x in r) == [40.0, 40.0]

def test_crossing_walls_split_into_four_rooms():   # Review Focus 1
    # a plus sign of two walls inside a 10x10 box, sharing no joint
    assert sorted(round(x['area'], 3) for x in regions(*split_crossings(J, W))) == [25.0] * 4

def test_separator_bounds_rooms_like_a_wall():
    # the same box with 'mid' as kind 'separator': two regions; footprints() has no 'mid'

def test_gap_leaves_no_region_and_reports_open_ends():
    # a box with one wall shortened by 2 ft: regions == []; open_ends gives the two gap ends

def test_weld_merges_within_one_foot_only():
    pts, idx = weld([[0, 0], [0.9, 0], [2.5, 0]])
    assert idx[0] == idx[1] and idx[2] != idx[0]

def test_l_corner_footprints_meet_without_a_gap():
    # walls (0,0)->(10,0) and (10,0)->(10,8), both 0.5 thick:
    # the outer corner of the first equals the outer corner of the second within 1e-6, likewise the inner corners

def test_t_junction_end_is_square_against_the_through_wall():
    # the stem's end at the joint lies on the through wall's face, not its centre line
```

- [ ] **Step 2:** Run `env -u HA_BASE_URL python tests/test_twin_model_graph.py`. Expected: it FAILS on the import.
- [ ] **Step 3:** Implement `twin_model_graph.py`.
  - **Faces:** use half-edge traversal. Sort the outgoing edges at each joint by angle and take the next edge clockwise. Keep the faces with positive signed area.
  - **Mitres:** the end point of each face side is the intersection of that face's offset line with the neighbouring wall's offset line on the same side. If the lines are parallel, fall back to a square end.
- [ ] **Step 4:** Run it. Expected: all PASS.
- [ ] **Step 5:** Commit `feat(twin): wall graph with joints, regions and mitred footprints`.

### Task 2: Schema 3 and derived rooms

**Files:**
- Create: `services/twin_model.py`
- Test: `tests/test_twin_model.py`

**Interfaces:**
- **Consumes:** Task 1.
- **Produces:**
  - `SCHEMA = 'chauffeur.twin.plan/3'`.
  - `normalize(model: dict) -> tuple[dict, list[str]]`. It validates and re-derives.
  - `derive(building: dict) -> dict`. It re-derives rooms and flags in place and returns the building.

**The building shape in schema 3** (top level: `{schema, units:'ft', materials, buildings, site}`, with `site` exactly as in schema 2):

```
{id, name, position, rotation, base, materials, position_from?,
 levels: [{id, name, elevation, ceiling, half?}],
 joints: [{id, level, at: [x, y]}],
 walls:  [{id, level, joints: [a, b], kind: 'solid'|'separator', thickness, exterior, height?, faces?: {left?: mat, right?: mat}, state?, src?, why?, confidence?}],
 rooms:  [{id, level, name, kind: 'room'|'porch', ha_area?, floor_material?, ceiling_material?, polygon (derived cache), joints (derived cache), src?}],
 openings: [{id, wall, at, width, sill, head, kind, panels?, split?, glass?, src?}]  or a gable opening {id, gable: {roof, edge}, at, width, sill, head, kind},
 anchors: [{id, kind: 'light'|'switch'|'outlet'|'fan'|'camera'|'sensor', host, offset, device?: null}],
 items:   [{id, asset, host, rotation, scale, src?}],
 roofs:   [{id, area: [[x, y]...], edges: [{setting, pitch?, clip?, wall?}], plate, overhang, material?, src?}],
 dormers: [{id, roof, edge, at, width, pitch, src?}],
 extensions, stairs, porches_detail?,
 proposals: [{id, kind, piece, against}],
 flags: [{level, at: [x, y], text, piece?}]}
```

`host` is one of:
- `{wall, side: 'left'|'right', at, z}`;
- `{floor: room_id, u, v}`;
- `{ceiling: room_id, u, v}`;
- `{ground: true, at: [x, y]}`;
- `{roof: roof_id, edge, at}`.

`mat` and every material is `{id, color}`, as in today's `materials`.

**Rules:**
- **Rooms are re-derived on every normalize.** A region keeps the identity of the stored room whose cached polygon overlaps it most (at least 25% of the region). Of two regions claiming one room, the larger keeps it, and the smaller gets a new id named `Room`. A region nobody claims gets a new room named `Room`. A stored room with no region is dropped, and its name moves into a flag `This room isn't closed: a wall is missing here.` at the stored polygon's centroid.
- **Every `open_ends` point gets that same flag**, deduplicated within 1 ft.
- **Caps:** walls 400, joints 800, openings 400, rooms 120, roofs 40, anchors 400, items 600.

- [ ] **Step 1: Write the failing tests**
  - `test_rooms_are_derived_and_keep_names`: a box with a T wall and two stored rooms named Kitchen and Dining. After normalize the two rooms keep their names and ids, and their polygons are the regions.
  - `test_moving_the_split_wall_keeps_identity`: the joints of `mid` move from x=5 to x=7. Kitchen is still on the left, with area 56.
  - `test_split_room_names_the_new_part_Room`.
  - `test_unclosed_room_is_flagged_never_silent`: a 2 ft gap gives `flags[0]['text'] == "This room isn't closed: a wall is missing here."`, and the stored room's name appears in the flag's `piece` field.
  - `test_caps_and_bad_hosts_are_refused_with_notes`: an opening on an unknown wall is kept with `state: 'ghost'`, and a note names it.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement `twin_model.normalize` and `twin_model.derive`. Reuse `twin_plan._piece_meta` for ids, state, src and why.
- [ ] **Step 4:** Run it plus `tests/test_twin_model_graph.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin): schema 3 with rooms derived from walls`.

### Task 3: Roof areas and dormers

**Files:**
- Create: `services/twin_model_roofs.py`
- Test: `tests/test_twin_model_roofs.py`

**Interfaces:**
- **Consumes:** Task 2's shapes.
- **Produces:**
  - `from_section(section: dict) -> dict`. Converts a schema-2 section (rect, kind, ridge, pitch, pitches, ends, low_side, plate, overhang) to a 4-edge roof.
    - Edges are ordered from the area's first point, counter-clockwise; for a rect `[x0,y0,x1,y1]` the area is `[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]`, so the edges are y0, x1, y1, x0.
    - `hip`: all four edges `sloped`.
    - `gable`: the two edges across the ridge are `gable`, or `clip` where `ends` says clip.
    - `shed`: only the `low_side` edge is sloped.
    - `flat`: all sloped with pitch 0.
    - Per-edge `pitch` is `pitches[edge]` or `pitch`.
  - `to_sections(roof: dict) -> list[dict]`. Splits a rectilinear area into overlapping rectangles: the maximal rectangles, using `twin_blocks`' partition as the seed and extending each rectangle through the inside corners to the area's far edges. Each rectangle is emitted as a schema-2 section carrying `pitches`, `ends`, `ridge`, `kind`, `plate`, `overhang` and `roof: <roof id>`. `to_sections(from_section(s))` must equal `s` on every form field.
  - `attach_edges(roof, walls, joints) -> roof`. An edge whose line lies within the overhang plus 0.5 ft of a parallel exterior wall line on the roof's bearing storey (the rule in twin_joints `_bearing`) records `wall: <id>`.
  - `follow_walls(roof, walls, joints) -> roof`. Moves each attached edge so that it stays at its overhang from its wall's outer face.
  - `dormer_from_section(section, parent_roof) -> dict`.
  - `dormer_sections(dormer, roof) -> list[dict]`. Gives the gable section, carrying `dormer_of`, that today's generator draws as a cross gable.

- [ ] **Step 1: Write the failing tests**
  - `test_round_trip_is_identity_for_every_household_section`: for every section in the household fixture (P6), `to_sections(from_section(s))` equals `s` on kind, rect, ridge, pitch(es), ends, plate, overhang and low_side.
  - `test_l_shaped_area_gives_two_overlapping_rects_with_inherited_edges`.
  - `test_per_edge_pitch_survives`: an edge pitch of 6 on y0 and 10 on y1 comes back as `pitches == {'y0': 6, 'y1': 10}`.
  - `test_attached_edge_follows_its_wall`: the wall moves +2 ft in y, the edge moves +2 ft, and an unattached awning edge does not move.
  - `test_rect_area_with_angled_edge_is_refused`: the error is `Roof areas must have square corners.`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it plus `tests/test_twin_roof_ends.py` and `tests/test_twin_blocks.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin): roofs as areas with an edge setting per edge`.

### Task 4: Hosts and how they follow

**Files:**
- Create: `services/twin_model_hosts.py`
- Test: `tests/test_twin_model_hosts.py`

**Interfaces:**
- **Produces:**
  - `snapshot(building) -> dict`: each wall's endpoints and each room's bounding box, taken before an operation.
  - `follow(building, before: dict) -> list[str]`. Applies spec §4.3 to openings (`at`), anchors, items and gable openings after any geometry change, and returns the plain notes.
  - `rehost(building, piece_id, host: dict) -> None`.
  - `world_point(building, host, offset=0) -> list[float]`: an x, y, z point in building-local feet.
  - `MIN_CLEAR = 0.5`: the clearance in feet.

**Rules:**
- **A wall item** keeps its distance from whichever end did not move. When both ends moved by the same vector it keeps its `at`. When both moved differently it keeps its fraction along the wall.
- **Clamping:** the item is then clamped so that `at ± width/2` lies within `[MIN_CLEAR, length - MIN_CLEAR]`.
- **An item whose host is gone** becomes `state: 'ghost'` and gets the unhosted flag.

- [ ] **Step 1: Write the failing tests**
  - `test_door_keeps_distance_from_the_fixed_end`.
  - `test_wall_moved_sideways_carries_its_window`.
  - `test_light_centred_in_a_room_stays_centred_when_the_room_grows`.
  - `test_shrinking_wall_clamps_the_door_onto_it` (Review Focus 2).
  - `test_rehost_moves_a_switch_to_the_other_wall`.
  - `test_deleted_wall_leaves_a_flagged_ghost_not_a_deletion`: the flag text is `This window lost its wall; place it again.`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin): hosted items follow their surface`.

### Task 5: The bridge (assemble, flatten, migration, ownership)

**Files:**
- Create: `services/twin_model_bridge.py`
- Create: `tests/fixtures/twin_model/household-2026-11-09.json` (P6, key-checked)
- Test: `tests/test_twin_model_bridge.py`

**Interfaces:**
- **Consumes:** Tasks 1-4.

**`assemble(flat: dict, previous: dict | None = None) -> tuple[dict, list[str]]`** turns a schema-2 plan into schema 3. It is used for migration (with `previous` set to None) and for every build write. The steps:
1. **Joints:** weld wall endpoints at 1 ft. Reuse a previous joint's id and position when the joint is within 1 ft of it. When the previous joint touches a person-owned wall, its position wins over the read.
2. **Walls:** `from`/`to` become `joints`, then `split_crossings`.
3. **Ownership against `previous`:**
   - A previous person-owned wall stays as it is.
   - An incoming wall within 1 ft of it at both ends is dropped.
   - An incoming wall that overlaps it by more than 50% of its length otherwise becomes a proposal (`proposals` entry with `kind: 'wall'`, the incoming wall stored as `state: 'proposal'`).
   - Untouched previous walls are replaced by the incoming read.
   - The same rule applies to openings (by wall and at, within 1 ft) and roofs (by area overlap of at least 50%).
4. **Rooms:** derived. Stored room polygons are matched by overlap. Where two stored rooms of one level fall in one region, a `separator` wall is added along the longest boundary they share, with the migration separator flag.
5. **Roofs:** `roof.sections` go through `from_section`. A section with `dormer_of` becomes a dormer. `extensions` carry over.
6. **Other lists:**
   - `lights` become anchors of kind light on the ceiling of the room containing them (an unhosted ghost when they are outside every room).
   - `fixtures` become items on that room's floor, keeping `asset`, rotation and size as scale.
   - `porches` become rooms of kind porch, closed by separators along their open sides, with `porches_detail` keeping columns and other fields.
   - `stairs` carry over unchanged.

**`flatten(model: dict) -> dict`** gives a schema-2 plan that `twin_plan.normalize` accepts and today's generator draws as before. Walls get `from`/`to`, plus the extras `joints`, `kind`, `footprint` and `faces`. Rooms get `polygon`, `kind`, `floor_material` and `ceiling_material`. `roof.sections` come from `to_sections` plus `dormer_sections`. Lights come back from the light anchors, with the anchors also passed through as `anchors`. `items`, `proposals` and `flags` pass through. Separator walls go into `walls` with `kind: 'separator'`.

**`twin_plan.normalize` must keep these extras**, so extend its field lists. `test_twin_plan.py` and `test_twin_plan_v2.py` stay green.

- [ ] **Step 1: Write the failing tests**
  - `test_household_migrates_and_keeps_every_room_name_and_opening`:
    - main house 25 rooms in, 25 rooms out;
    - pool house names `Pool Lounge`, `SHWR.`, `CHANGING`, `EXERCISE` and `CLOSET` kept;
    - every opening hosted or flagged;
    - `flags` count printed in the test output, for the record.
  - `test_household_walls_stay_within_a_foot`: every old wall's endpoints are within 1 ft of the flattened wall's endpoints, matched by id, with split parts compared on their union.
  - `test_household_roofs_round_trip`: flattened sections equal the old ones on form fields, apart from `dormer_of` sections, which come back via `dormer_sections`.
  - `test_flatten_normalizes_and_keeps_extras`.
  - `test_person_wall_survives_a_new_read_and_a_disagreement_is_a_proposal` (Review Focus 3).
  - `test_migration_separator_is_flagged_with_the_exact_copy`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it plus `tests/test_twin_plan.py`, `tests/test_twin_plan_v2.py` and `tests/test_twin_model_roofs.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin): assemble and flatten the connected model; migration`.

### Task 6: The store holds the model

**Files:**
- Modify: `services/twin_store.py` (`_read_round`, `current`, `push_round`, `update_current`, `revert`)
- Modify: `services/twin_record.py` (the record includes `model`)
- Test: `tests/test_twin_store_model.py`
- Neighbour tests: `tests/test_twin_store.py`, `tests/test_twin_build_draft.py`, `tests/test_twin_build_roof_blocks.py`, `tests/test_house_editor_routes.py`

**Interfaces:**
- **Produces:**
  - `current_model() -> dict | None`: schema 3.
  - `current() -> dict | None`: the flat view, the same shape callers get today (P1).
  - `push_round(plan, ...)` and `update_current(mutator, ...)` accept a flat plan and store `assemble(plan, previous=current_model)`.
  - `update_model(mutator, kind='edit', note='', changes=()) -> int`: the mutator receives and returns schema 3.
  - `rounds/{id}` may hold schema 2 or 3: `_read_round` assembles schema 2 on read, so old rounds keep working on the timeline.
  - `GET /api/house/editor/state` adds `model`.

- [ ] **Step 1: Write the failing tests**
  - `test_old_schema_2_round_reads_as_model_and_flat`.
  - `test_push_round_of_flat_keeps_joint_ids_and_person_walls`.
  - `test_revert_to_a_schema_2_round_works`.
  - `test_state_route_returns_model_and_plan`: a TestClient call to `/api/house/editor/state` with a parent session.
  - `test_record_download_includes_model`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it plus the neighbours. Expected: PASS. A neighbour that fails because it inspects stored round JSON directly is retargeted to `current()`; any such change is listed in the report.
- [ ] **Step 5:** Commit `feat(twin): the round store holds the connected model`.

### Task 7: The generator draws the model

**Files:**
- Modify: `static/twin/twin_generator.js`. Areas: the wall loop at about :463, the floors at :767-781, materials at :226, and fixtures and lights at :857-887.
- Test: `tests/test_twin_generator_model_live.py` (live; the controller runs it)

**Interfaces:**
- **Consumes:** flat extras from Task 5.

**Requirements:**
- **Walls:** a wall with `footprint` is extruded from that quadrilateral, with openings cut as today. This replaces the concave-corner extension for such walls; walls without a footprint keep today's path.
- **Separators** are never meshed.
- **Floors** come from room polygons when present.
- **Materials resolve per surface** in this order: the wall face (`faces.left`/`faces.right`), the room (`floor_material` for floor slabs per room), the building `materials[role]`, then the kit.
- **Items** load library models through `twin_library.loadModel`, placed by `host`. `world_point` is mirrored in JS as `hostPoint(building, host, offset)` in a new `static/twin/twin_hosts.js`, with the same fixtures as Task 4.
- **Anchors** draw only when `view.showAnchors` is true, as small discs. The editor sets it.

- [ ] **Step 1: Write the failing live scenarios**
  - `scenario_household_corners_are_closed`: for each L corner in the migrated household, the two wall meshes' outer corner vertices coincide within 0.01 ft, read from `window.__twin.pieces`.
  - `scenario_separator_draws_nothing`.
  - `scenario_room_floor_override_changes_only_that_room`: the pixel colour at two floor points differs after `floor_material` is set on one room.
  - `scenario_item_sits_on_its_host`.
  - Add a node test `tests/test_twin_hosts_js.py` running `twin_hosts.js` on Task 4's fixtures.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them plus `tests/test_twin_editor_scene_live.py`, `tests/test_twin_roof_js.py` and `tests/test_twin_materials_js.py`. Expected: PASS. The controller also screenshots the household from all four sides to compare with v2.499.771.
- [ ] **Step 5:** Commit `feat(twin): the generator draws mitred walls, derived rooms, items and material overrides`.

### Task 8: Operations, part 1 (walls, joints and rooms)

**Files:**
- Create: `services/twin_model_ops.py`
- Test: `tests/test_twin_model_ops_walls.py`

**Interfaces:**
- **Produces:**
  - `apply(model, op: dict, actor: str = 'person') -> tuple[dict, str]`: the new model and plain words.
  - `class Refused(ValueError)`.
  - Every operation is followed by: `twin_model.derive`, `hosts.follow(snapshot)`, `roofs.follow_walls`, and marking each touched piece with `src.person` when the actor is the person.

**Operations in this task** (`op['op']`):
- `move_joint {building, joint, to:[x,y]}`;
- `move_wall {building, wall, by: float}`: a perpendicular offset that moves both joints;
- `add_wall {building, level, from, to, kind?='solid', exterior?}`: welds and splits;
- `split_wall {building, wall, at}`;
- `draw_room {building, level, polygon, name?}`: adds walls on the polygon's edges and merges them with existing collinear walls;
- `split_room {building, room, from, to}`: adds a separator;
- `move_room {building, room, by:[dx,dy]}`: moves the room's joints;
- `delete {building, id}`.

**Refusals (exact copy):**
- `That would cross another wall.`
- `A wall must be at least 1 ft long.`
- `That would leave the door narrower than its wall.` (Review Focus 2)

- [ ] **Step 1: Write the failing tests**
  - `test_shared_wall_drag_resizes_both_rooms`.
  - `test_draw_room_beside_a_room_shares_one_wall`: the count of walls on the shared line is 1.
  - `test_move_room_stretches_the_neighbour_not_tears`.
  - `test_split_room_adds_a_separator_and_a_room_named_Room`.
  - `test_move_wall_too_far_past_a_door_is_refused`.
  - `test_ops_mark_touched_walls_person_owned`.
  - `test_delete_wall_merges_two_rooms_keeping_the_larger_name`.
  - `test_wall_drawn_over_an_existing_wall_merges_into_one` (spec §4.1).
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin): wall, joint and room operations`.

### Task 9: Operations, part 2 (hosted items, roofs, buildings, materials, proposals, the route and the agent)

**Files:**
- Modify: `services/twin_model_ops.py`
- Modify: `services/twin_edit.py`. `apply` translates each legacy op to model ops (`move` of a wall to `move_wall`/`move_joint`, `add_wall`, `add_opening`, `set`, `delete`, `accept`, `rotate`, `registration` unchanged), so `house_design` keeps working with the same op names.
- Modify: `main.py`. Add `POST /api/house/editor/op` taking `{op}`. It runs `twin_store.update_model`, returns `{round, words, plan: flat, model}`, and refuses with 400 `{error: words}`. The auth rule is covered by the existing `/api/house/editor/*` PARENTS rule.
- Modify: `services/agent_tools_v2.py`. `house_design` accepts every new op name. Its description lists them in plain words.
- Test: `tests/test_twin_model_ops_more.py`. Neighbours: `tests/test_twin_edit.py`, `tests/test_twin_live_tool.py`, `tests/test_house_editor_routes.py`.

**Operations in this task:**
- **Hosted items:**
  - `add_opening {building, wall, at, kind, width?, sill?, head?}`. The default widths are the editor's today: 3 ft for door and window.
  - `move_hosted {building, id, host?, at?, z?, offset?}`.
  - `resize_opening {building, id, width?, sill?, head?, at?}`.
  - `add_anchor {building, kind, host}`.
  - `add_item {building, asset, host, rotation?, scale?}`.
- **Roofs:**
  - `draw_roof {building, area, plate?, pitch?=6, overhang?=1}`. Every edge starts `sloped`.
  - `roof_over {building, rooms: [ids] | null}`. With null the area is the building's outline on its top storey; with rooms it is the union of the rooms' regions.
  - `set_roof_edge {building, roof, edge, setting, pitch?, clip?}`.
  - `move_roof_edge {building, roof, edge, by, detach?}`.
  - `add_dormer {building, roof, edge, at, width, pitch}`.
  - `move_dormer {building, id, at?, width?}`.
- **Buildings and levels:**
  - `add_level {building, name, elevation, ceiling}`.
  - `move_building {building, to:[x,y]}` (lot feet).
  - `rotate_building {building, rotation}`.
- **Fields and materials:**
  - `set {building, id, field, value}`: today's EDITABLE fields, plus `name` for rooms.
  - `set_material {building, target: {wall, side} | {room, surface: 'floor'|'ceiling'} | {roof} | {level} | {building, role}, material: {id, color} | null}`. Null clears the override.
- **Proposals:**
  - `accept_proposal {building, id}`;
  - `dismiss_proposal {building, id}`.
- **Site items (P4):**
  - `move_site_item {list: 'planting'|'furniture', index, at}`;
  - `delete_site_item {list, index}`;
  - `add_site_item {list, asset, at}`.
  - Each records into `compose_overrides` exactly as `twin_plan.record_compose_overrides` does.

- [ ] **Step 1: Write the failing tests**
  - `test_add_window_then_drag_it_to_another_wall_rehosts`.
  - `test_roof_over_rooms_then_set_an_edge_gable_and_a_side_pitch`: the flattened section's `pitches` show the side pitch.
  - `test_dormer_reaches_the_roof_whatever_the_pitch`.
  - `test_set_material_cascade_and_clear`.
  - `test_accept_and_dismiss_a_proposal`.
  - `test_op_route_round_trip`: a TestClient call to `/api/house/editor/op` that returns words and a new round.
  - `test_op_route_refusal_is_400_with_words`.
  - `test_house_design_tool_reaches_new_ops`: through `agent_tools_v2`.
  - `test_legacy_edit_ops_still_work`: the existing `tests/test_twin_edit.py` stays green.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it plus the neighbours. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin): hosted, roof, building and material operations; the op route and Argyle`.

---

## Part B: the editor and lot placement (piece 2)

Every Part B task reads `chauffeur/docs/ui_design_guide.md` first. The live scenarios go in `tests/test_house_editor_model_live.py`, which seeds the migrated household fixture through `twin_store.push_round`. The browser test hooks are on `window.__twinEditor`, which the editor sets only under the existing test flag.

The editor applies operations with `api.op(op)`, which posts to `/api/house/editor/op`. On success it replaces the plan and the model and rebuilds the scene. On a refusal it shows the words with `showGlobalAlert`.

### Task 10: Selection you can see, rooms first

**Files:**
- Create: `static/twin/editor/selection.js`
- Modify: `static/twin/editor/scene_tools.js`, `static/twin/twin_view.js` (pick returns `{kind, id, building, level}`), `static/twin/editor/cards.js` (the title names the thing), `static/twin/editor/api.js` (add `op(op)`, the Part B entry point, and keep `plan` and `model` from its response)

**Interfaces:**
- **Produces:**
  - `createSelection({view, getModel, onChange})` returns `{hover(pick), select(pick), clear(), current(), focusRoom}`.
  - Test hook: `__twinEditor.selection()`, which returns `{kind, id, room, ghosted: number, tinted: {floor: id|null, walls: [ids]}}`.

**Behaviour (spec §5.1-5.2):**
- **Hover** pre-highlights with an outline.
- **Selecting** adds an outline and a tint, using the UI guide's tokens.
- **A click on a room's floor** selects the room. Its floor takes tint A and its walls tint B. Every other piece is ghosted at 0.25 opacity and is not pickable.
- **With a room focused,** a click on its walls, openings, anchors or items selects that piece and keeps the room focused.
- **Clicking outside the room, or Escape,** steps back out: piece, then room, then nothing.
- **With nothing focused,** a click on a building in the exterior view selects the building, and a floor button in the Floors aside selects that level. Each gets its card (spec §5.2).
- **Card titles:** `Kitchen`, `Kitchen, east wall` and `Window, kitchen east wall`. The compass word comes from the wall's outward normal in lot coordinates.

- [ ] **Step 1:** Write the failing live scenarios:
  - `scenario_click_floor_tints_room_and_its_walls`;
  - `scenario_outside_pieces_are_ghosted_and_unpickable`;
  - `scenario_escape_steps_out`;
  - `scenario_hover_highlights_before_click`;
  - `scenario_card_names_the_wall_by_compass`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them plus `tests/test_house_editor_live.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin-editor): visible selection, rooms first`.

### Task 11: Dragging, snapping and dimensions

**Files:**
- Create: `static/twin/editor/drag.js`, `static/twin/editor/dimensions.js`
- Modify: `static/twin/editor/snap.js`, `static/twin/twin_view.js` (`rebuildLevel(buildingId, levelId, flat)` rebuilds only that level's group)
- Test: `tests/test_twin_snap_js.py` (extend), plus live scenarios

**Interfaces:**
- **Produces:**
  - `snapPoint(p, ctx)` with `ctx = {joints, walls, below, anchors, grid: 1/12, reach: 1}`. It returns `{point, target: 'joint'|'line'|'extension'|'right_angle'|'anchor'|'below'|'grid'}` in the spec's order.
  - `createDrag({view, model, onPreview, onCommit})`. During a drag it moves joints on a copy of the flat plan, re-runs `twin_hosts.hostPoint` for hosted items, and calls `rebuildLevel` (P2). On release it posts one op.
  - `dimensions.show(ctx)` draws live distance labels to the neighbouring walls and the item's own size. Clicking a label calls `promptInput` for feet and inches and posts the resulting op.
  - Test hook: `__twinEditor.lastDragFrameMs`.

- [ ] **Step 1: Write the failing tests**
  - node: `snaps_in_the_spec_order`, `extension_line_snap`, `grid_is_one_inch`.
  - live:
    - `scenario_drag_preview_is_under_33ms` (P3);
    - `scenario_release_posts_one_op_and_rooms_rederive`;
    - `scenario_dimension_label_click_types_a_value`. It uses `promptInput`, never `prompt`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin-editor): live drags with snapping and dimensions`.

### Task 12: Handles

**Files:**
- Create: `static/twin/editor/handles.js`
- Modify: `static/twin/editor/scene_tools.js`. The old Move and Turn piece-delta drags are removed for pieces whose handles exist; building Move and Turn move to Task 16.

**Interfaces:**
- **Consumes:** Tasks 10-11.
- **Produces** handles for the focused room and the selected piece (spec §5.3):
  - **A wall:** drag across its direction, giving `move_wall`.
  - **A joint:** a dot at each corner of the focused room, giving `move_joint`.
  - **A room:** drag the floor, giving `move_room`.
  - **An opening:** dragging the middle gives `move_hosted` along the wall. Dragging the left or right edge gives `resize_opening` on width and at. Dragging the top or bottom gives head or sill.
  - **An anchor or item:** slide along the host surface. Crossing onto an adjacent surface under the pointer gives `move_hosted` with a new `host`.

- [ ] **Step 1:** Write the failing live scenarios:
  - `scenario_drag_shared_wall_updates_both_rooms`;
  - `scenario_window_middle_moves_edges_resize`;
  - `scenario_switch_dragged_round_the_corner_rehosts`;
  - `scenario_move_room_carries_its_window`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin-editor): handles for walls, corners, rooms, openings and hosted items`.

### Task 13: Drawing tools, undo and redo, and retiring Plan mode

**Files:**
- Create: `static/twin/editor/draw.js`, `static/twin/editor/history.js`
- Modify: `templates/house_editor.html` (rail), `static/twin/editor/editor.js`
- Delete: `static/twin/editor/plan_view.js`. Its add-wall and add-door/window abilities are re-homed in `draw.js` with the Top camera; the user approved this in the spec, §3 item 9.

**Interfaces:**
- **The rail:** `#rail-select`, `#rail-draw-room`, `#rail-draw-wall`, `#rail-split-room`, `#rail-add-door`, `#rail-add-window`, `#rail-add-anchor`, `#rail-add-level`, `#rail-delete`, `#rail-undo` and `#rail-redo`. The existing Sheet button stays. `#rail-plan` is removed.
- **Drawing:** Draw room is a rectangle by drag, or a polygon by clicks closed on its first point. Draw wall is a click chain ended with Escape or a double click. Both snap through Task 11.
- **`history.js`** implements P5. Its keys are Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z, and they are disabled while a build is active (`api.active`).

- [ ] **Step 1:** Write the failing live scenarios:
  - `scenario_draw_room_beside_room_shares_a_wall`;
  - `scenario_draw_wall_chain_joins_corners`;
  - `scenario_split_room_makes_two_rooms`. After the split, `promptInput` asks for the new room's name (spec §4.2), and Skip keeps `Room`;
  - `scenario_undo_restores_walls_rooms_and_names_after_a_split` (Review Focus 4);
  - `scenario_redo_reapplies`;
  - `scenario_plan_mode_is_gone_and_top_camera_draws`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement, then run `python tools/build_tailwind.py`.
- [ ] **Step 4:** Run them plus `tests/test_house_editor_live.py`. Expected: PASS. Any old scenario that drives Plan mode is retargeted to the new tools and listed in the report.
- [ ] **Step 5:** Commit `feat(twin-editor): draw rooms and walls, undo and redo; Plan mode retired`.

### Task 14: Roof editing

**Files:**
- Create: `static/twin/editor/roof_tools.js`
- Modify: `static/twin/editor/cards.js` (the roof card lists the edges)

**Interfaces** (spec §5.3, roof bullet; §5.5):
- `#rail-roof` opens two choices: **Roof over this** (`roof_over`, using the focused room or the selected rooms, or the building when nothing is selected) and **Draw roof area** (a rectilinear polygon, giving `draw_roof`).
- **A selected roof** shows a handle on each edge, giving `move_roof_edge`. Dragging it away from its wall line by more than 1 ft detaches it.
- **Clicking an edge** opens the edge card: Sloped (pitch in x:12), Gable or Clipped, giving `set_roof_edge`.
- **Add dormer** works on a roof surface under the pointer (`add_dormer`). A selected dormer has middle and edge handles (`move_dormer`).
- **The roof flags of v2.499.771** (`roof.flags`) still show on the card, with **Looks right**.

- [ ] **Step 1:** Write the failing live scenarios:
  - `scenario_roof_over_the_left_wing_then_gable_both_ends`;
  - `scenario_one_side_pitch_differs`: the ridge moves toward the steeper side, read from the flattened section;
  - `scenario_dormer_added_reaches_the_main_roof`;
  - `scenario_detached_edge_stops_following_its_wall`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them plus `tests/test_twin_roof_flags_js.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin-editor): roofs drawn as areas, edges set one by one, dormers`.

### Task 15: The library, materials and items

**Files:**
- Create: `static/twin/editor/library.js`
- Modify: `templates/house_editor.html` (`#rail-library` opens a side panel `#library-panel`), `static/twin/editor/cards.js`
- Modify: `main.py`. Add `GET /api/house/editor/library`, which returns the manifest's `material` and `model` entries plus the kit's roles and plant/furniture lists, as `{materials: [{id, name, color}], items: [{id, name, kind}]}`.

**Interfaces** (spec §5.7):
- **The panel** has tabs Materials and Items. Thumbnails are rendered in the browser by one shared offscreen renderer: a material on a sphere, a model fitted to its box. They are cached in memory, and nothing is fetched beyond the library.
- **Dropping a material** on a surface posts `set_material` at the scope chosen in a small chooser that appears on drop: `This wall face`, `This room`, `The whole building`.
- **Every surface card** shows the material line in the fixed copy, with **Clear** when the material is set here.
- **Dropping an item** posts `add_item`, hosted where it lands. On the lot ground it posts `add_site_item`.
- **Yard plants and furniture** are selectable and movable, and the card's Delete button removes them (P4).

- [ ] **Step 1: Write the failing tests**
  - Live scenarios:
    - `scenario_drop_siding_on_one_face_sets_here`;
    - `scenario_whole_building_scope_recolours_all_faces`;
    - `scenario_card_reads_from_the_building`;
    - `scenario_drop_sofa_on_the_family_room_floor`;
    - `scenario_move_a_yard_tree_and_it_stays_after_rebuild`.
  - A route test: `test_library_route_lists_materials_and_items`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement, then run `python tools/build_tailwind.py`.
- [ ] **Step 4:** Run them plus `tests/test_twin_library.py`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin-editor): a library of materials and items`.

### Task 16: Placement on the lot in the scene

**Files:**
- Create: `static/twin/editor/lot_tools.js`
- Modify: `static/twin/editor/pauses.js` (the fit step's `lot_placement` pause uses these handles), `static/twin/editor/place.js` (the `#place-map` SVG and its handlers are removed once every ability below works), `templates/house_editor.html`

**Interfaces** (spec §5.6):
- **The plot plan underlay:** when `place.lot.read` exists, the plot page (`GET /api/house/editor/sheets/{source}/{page}.png`) lies on the ground as a textured plane, mapped by `read.matrix` into lot feet, at 0.6 opacity under the lot outline. It also shows during the fit pause.
- **A selected building** has a move handle at its centre and a turn handle at its outline's front edge.
  - The move handle raycasts the ground plane every frame and posts `move_building` on release.
  - The turn handle posts `rotate_building`, snapping by `snapRotation`.
  - Review Focus 5: the drag follows the pointer whatever the rotation.
- **Footprint suggestions** from the plot read draw as dashed outlines. Dragging a building within 2 ft and 7° of one snaps it on. Clicking a suggestion opens a card with Accept, Match to building and Dismiss, which are today's suggestion endpoints.
- **Clicking a lot edge** offers `This edge is the street`, which is today's `PUT /place/lot/placement` with `street_edge`.
- **The Your place dialog keeps** buildings, uploads and photo tags.

- [ ] **Step 1:** Write the failing live scenarios:
  - `scenario_plot_underlay_is_at_true_scale`: a plot dimension measured in the scene equals the read's dimension within 0.5 ft;
  - `scenario_rotated_building_follows_the_pointer`;
  - `scenario_building_snaps_to_its_footprint`;
  - `scenario_street_edge_set_in_scene`;
  - `scenario_suggestion_accept_in_scene`;
  - `scenario_fit_pause_shows_the_underlay`;
  - `scenario_place_map_svg_is_gone`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them plus `tests/test_twin_place.py` and the place scenarios in `tests/test_house_editor_live.py`. Expected: PASS. Old SVG-map scenarios are retargeted and listed in the report.
- [ ] **Step 5:** Commit `feat(twin-editor): place buildings on the plot plan in the scene`.

### Task 17: Flags and proposals on the model

**Files:**
- Create: `static/twin/editor/flags.js`
- Modify: `static/twin/editor/panel.js`

**Interfaces:**
- **Model flags** (`building.flags`: unclosed room, migration separator, unhosted) draw as a marker at their point.
- **A count** shows in the panel: `3 things to check`. Clicking it walks the flags one at a time, focusing the camera and selecting the piece.
- **Each flag** has **Looks right**, which posts `set` with `{field: 'flag_ok'}` and removes it, and **Fix it**, which selects the piece.
- **Proposals** draw as ghosts beside the person's piece, with a card offering `Use this` (`accept_proposal`) and `Dismiss` (`dismiss_proposal`).

- [ ] **Step 1:** Write the failing live scenarios:
  - `scenario_migrated_household_lists_its_flags`;
  - `scenario_looks_right_clears_a_separator_flag`;
  - `scenario_proposal_use_this_replaces_the_wall`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. The `flag_ok` field is added to Task 9's `set`, and it removes the flag by index and text.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit `feat(twin-editor): flags and proposals on the model`.

### Task 18: Ship (the controller)

- [ ] Run every task's tests and the named neighbours once more.
- [ ] Screenshot the migrated household from all four sides, plus one room focus and one roof edit.
- [ ] Update `chauffeur/system_capabilities.md` with shipped facts only.
- [ ] Bump `chauffeur/config.yaml`.
- [ ] Commit `(vX.Y.Z)` and push.
- [ ] Update the memory arc: pieces 1 and 2 shipped, NOT device-verified, plus the device-run checklist from spec §9.
