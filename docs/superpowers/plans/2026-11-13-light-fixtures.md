# Light Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One light entity drives any number of fixtures (point, spot, line, area), which render in real time within fixed per-tier quotas and bake physically, with shadows. They are edited with multi-drop, aim, draw/snap and rectangle tools. Fire pits derive their fixtures, and cameras share the aim tool.

**Architecture:**
- **Server:** fixtures live in the model at `light_fixtures: {entity_id: [fixture]}`, validated and snap-resolved by a new `services/twin_fixtures.py`, and exposed in `/api/house/live`.
- **Browser:** one resolver, `static/twin/live/emitters.js`, turns the layout plus HA states into resolved emitters, with a legacy path for entities that have no fixtures. Both `real_lights.js` (real time) and the bake (`bake/*`) consume only that resolver's output.

**Tech Stack:** FastAPI (`chauffeur/main.py`); vendored three r187 (`PointLight`, `SpotLight`, `RectAreaLight` with `RectAreaLightUniformsLib`); and the existing lightmap baker under `static/twin/bake/`.

**Spec:** `docs/superpowers/specs/2026-11-13-light-fixtures-design.md`. Read it first; where this plan and the spec disagree, the spec wins.

**Prerequisite:** the `bake-all` work, which bakes yard and fire-pit lights onto outdoor yard charts, must be on main before Task 4. Merge main into this branch before each task.

## Global Constraints

- Follow `AGENTS.md`. Tests run from `chauffeur/` as `python tests/x.py`, with `HA_BASE_URL` unset. Run only the named tests. Implementers do not bump or commit.
- **No `light_fixtures` entry for an entity means the legacy resolver, unchanged.** That is floor lamps raised by `LAMP_HEIGHT` and ceiling emitters lowered by 0.2 ft (`live/modes.js` around line 96, and `bake/reach.js` `lightSource`). Legacy houses must stay pixel-identical in live and bake.
- **Units:** the entity's `output_lm` defaults to 503, which is today's 40 cd (`real_lights.js` `CANDELA`) times 4π. Conversions:
  - point: cd = lm / 4π;
  - spot: cd = lm / (2π(1 − cos(cone/2)));
  - area: luminance = lm / (π·A);
  - line: an area of length × `width_in`.
  Subdividing a run never changes its total.
- **`emission(state, domain)`** is the only source of on/off and colour. `light` follows its state. A `switch` that is on gives brightness 1 at 2700 K. A `media_player` emits when `on`, `playing` or `paused`, at 6500 K and 30%. `unavailable`, `unknown` and stale data never emit.
- **Real-time quotas** (point / spot / area / shadow casters): low 4/1/2/0; medium 8/2/4/1; high 12/4/8/2; max 16/6/12/4.
  - A line expands into at most 4 area pieces, and every piece counts against the area quota.
  - Every slot stays visible inside Lights mode, and the variants are warmed. Programs must never recompile when a light switches.
- **All fixtures of one entity share one bake channel per chart:** aggregate by entity before channel ranking.
- **The emitter signature** (shape, positions, aim, cone, size, facing, shares, output, resolved path) is part of the live `layoutKey`, `lightsOf`, the reach cache input and the bake fingerprint. Bump the bake format version.
- Fixtures belong to the entity: `place_device`, marker drag and Show as must never change `light_fixtures`.
- **Snapped runs are never dropped.** An unresolvable snap keeps the last `path` and sets `detached: true`.
- Limits: at most 64 fixtures per entity, 2-64 points per line, `cone_deg` 10-160, `width_in` 0.25-2.
- No browser dialogs. Parents only. One undoable edit per change.
- Do not touch the `house_design` schema; it is at its 6,000-character cap.
- Every HA touchpoint degrades: without HA, fixtures draw unlit.

## Review Focus

1. **A floor lamp and a ceiling light in an untouched house** look identical before and after, live and baked. Pinned in Tasks 2 and 4.
2. **Dragging a light's marker after configuring 12 path lights** keeps all 12. Pinned in Task 1.
3. **Deleting the retaining wall a rope run is snapped to** keeps the run, detached, and undo reattaches it. Pinned in Task 1.
4. **A 60 ft rope run on the Low tier** stays within the area quota and glows, and the frame does not recompile when it switches. Pinned in Task 3.
5. **Re-aiming a spotlight** makes the bake stale; an old bake must not stay "fresh". Pinned in Task 4.

---

## Slice A: data and resolver (lands as one version, with no visible change for existing houses)

### Task 1: Fixture storage, validation, snap resolution and ops

**Files:**
- Create: `chauffeur/services/twin_fixtures.py`
- Modify:
  - `chauffeur/services/twin_model.py`: normalize calls `twin_fixtures.normalize(model, notes)`;
  - `chauffeur/services/twin_model_ops.py`: new ops;
  - `chauffeur/main.py`: `house_live` around line 7564 adds a top-level `light_fixtures` to the response.
- Test: create `chauffeur/tests/test_twin_fixtures.py` (TestClient, isolated dirs; see `tests/test_twin_ha_display.py`).

**Interfaces:**
- Produces, in `twin_fixtures.py`:
  - `validate(fixture) -> fixture` (canonical form, or `ValueError`);
  - `normalize(model, notes) -> None`, which validates, re-resolves snaps and sets `detached`;
  - `resolve_snap(model, snap) -> list[[x, y, z]] | None`, which finds the host by `{kind, id}`, matches the edge by nearest endpoints within 0.5 ft (either direction), and returns the sub-path between `t0` and `t1` lifted by the facing rule;
  - `signature(entity_id, fixtures) -> str`.
- **Fixture fields**, as in the spec's model table:
  - common: `id` (`fixture:<uuid>`), `shape`, optional `share`, and `ref: floor|ground|absolute` (`building`/`level` when `floor`);
  - per shape: point `at`; spot `at`, `aim`, `cone_deg`, `softness`; line `path`, optional `snap`, `facing`, `width_in`, `detached`; area `at`, `size_ft`, `facing`, `rotation_deg`;
  - per entity: `output_lm`, kept in `light_fixtures_meta: {entity_id: {output_lm}}`.
- **Ops:** `add_light_fixture {entity_id, fixture}`, `update_light_fixture {entity_id, id, change}`, `delete_light_fixture {entity_id, id}`, `set_light_output {entity_id, output_lm}`.
- **Snap hosts:** `retaining_wall` (pad id plus edge), `hardscape` (site item id), `fence` (site item id), `step` (stair id), `wall` (building wall id).

- [ ] **Step 1: Write failing tests:**
  - `add_update_delete_each_shape_round_trip`;
  - `limits_refused` (65 fixtures, 1-point line, `cone_deg` 200, `width_in` 3);
  - `placement_ops_never_touch_fixtures`: add 12 point fixtures to `light.landscape`, run `place_device` and a marker move for its device, and get the same 12;
  - `snap_follows_host_move`: a run snapped to a retaining wall pad edge, after the pad is moved by 3 ft, has a path moved by 3 ft;
  - `snap_survives_edge_renumbering`: a vertex inserted before the edge still resolves;
  - `deleted_host_detaches_and_undo_reattaches`;
  - `live_layout_carries_light_fixtures_and_signature`;
  - `parents_only`;
  - `legacy_model_without_fixtures_unchanged` (normalize output is equal).
- [ ] **Step 2:** Run `python tests/test_twin_fixtures.py`. Expected: FAIL.
- [ ] **Step 3:** Implement as specified.
- [ ] **Step 4:** Run it, then `test_twin_model_bridge`, `test_twin_ha_routes`, `test_twin_device_controls`, `test_twin_house_saves`, `test_twin_server_speed` and `test_house_design_tool`. Expected: PASS.
- [ ] **Step 5:** Commit (controller).

### Task 2: The emitter resolver (one source for live and bake)

**Files:**
- Create: `chauffeur/static/twin/live/emitters.js`
- Modify: `chauffeur/static/twin/live/live.js`, where `layoutKey` around line 65 adds `light_fixtures` signatures.
- Test: create `chauffeur/tests/test_twin_emitters_js.py`.

**Interfaces:**
- Consumes the `light_fixtures` and `light_fixtures_meta` from Task 1, as found in the live layout.
- Produces:
  - `emission(state, domain) -> {on: bool, brightness: 0..1, rgb: [r, g, b]}`, following the Global Constraints;
  - `resolveEmitters(layout, states, plan) -> [emitter]`, where an emitter is `{fixture_id, entity_id, device_id, shape, at|path|aim|size_ft|facing|cone_deg|softness|width_in, output_lm_share, cd|luminance, rgb, on, building, level, room, legacy: bool}`. Entities without fixtures produce `legacy: true` emitters through the exact legacy rules, which move here from `modes.js` / `reach.js` so both now call `resolveEmitters`.
  - `firePitEmitters(pit, plan) -> [emitter]`: a linear burner (aspect ≥ 4) gives a line along the burner centre, facing up; a wider one gives an area of the burner's size; wood gives a point 1 ft above the logs. Read the burner from `fire_pits.js`. Driven by the fire pit's entity.
  - `emitterSignature(emitters) -> string`.

- [ ] **Step 1: Write failing tests:**
  - `legacy_floor_and_ceiling_match_old_rules`: positions match the old `modes.js`/`reach.js` output exactly; snapshot them from main first;
  - `switch_on_is_2700k_full`;
  - `tv_paused_emits_idle_does_not`;
  - `unavailable_and_stale_never_emit`;
  - `line_shares_sum_to_output_and_subdivision_keeps_total`;
  - `spot_cd_from_cone`;
  - `area_luminance_from_size`;
  - `linear_burner_gives_line_wide_gives_area_wood_gives_point`;
  - `signature_changes_on_aim_cone_size_facing_path`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement, and switch `modes.js` and `reach.js` to call `resolveEmitters` for positions.
- [ ] **Step 4:** Run it, then `test_twin_live_control_js`, `test_twin_live_rooms_js`, `test_twin_bake_runtime_js`, `test_twin_energy_js` and `test_twin_fire_pits`. The controller runs `test_house_twin_live_rooms` and the bake browser test. Expected: PASS, with legacy unchanged.
- [ ] **Step 5:** Commit (controller). **Slice A lands.**

## Slice B: real time

### Task 3: Typed light pool with quotas, glow meshes and warm variants

**Files:**
- Modify: `chauffeur/static/twin/live/real_lights.js` (`createRealLights` and `pickReal`) and `chauffeur/static/twin/twin_tiers.js` (per-tier `realLights` becomes `{point, spot, area, shadows}`).
- Create: `chauffeur/static/twin/live/fixture_glow.js`, holding the emissive strip for a line (a tube of radius `width_in`/2 along the path) and the panel for an area. It uses one shared emissive material per colour bucket.
- Test: create `chauffeur/tests/test_twin_fixture_lights_js.py`.

**Interfaces:**
- Consumes `resolveEmitters` from Task 2.
- Produces `createRealLights(view, {tier})`, now with typed pools. `RectAreaLightUniformsLib.init()` is called once.
- **Line expansion:** at most 4 equal pieces, each a `RectAreaLight` of piece length × `width_in` facing `facing`.
- **Selection:** fixtures are picked by distance and output within each type's quota, and shadows go to the closest casters within the shadow quota.

- [ ] **Step 1: Write failing tests:**
  - `quota_respected_per_type_and_tier`, including a 60 ft line on Low with 4 pieces against an area quota of 2: only 2 pieces light and the rest glow only;
  - `program_keys_stable_when_lights_switch` (render, toggle, render, with the same program cache keys);
  - `spot_targets_aim_with_cone_and_penumbra`;
  - `glow_strip_follows_path_and_state`;
  - `legacy_point_pool_unchanged` (same lights for a house without fixtures).
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it, then `test_twin_live_control_js`, `test_twin_energy_js` and `test_twin_import_maps`. The controller runs `test_house_twin_energy_live` and a night Chromium screenshot of a wall-cap line and a linear burner. Expected: PASS.
- [ ] **Step 5:** Commit (controller). **Slice B lands.**

## Slice C: bake

### Task 4: Emitter shapes, entity aggregation and invalidation in the bake

**Files:**
- Modify:
  - `chauffeur/static/twin/bake/runtime.js`: `lightsOf` becomes `resolveEmitters`, grouped by entity;
  - `chauffeur/static/twin/bake/reach.js`: reach per fixture, input = emitter signature;
  - `chauffeur/static/twin/bake/atlas.js`: `assignChannels` aggregates scores and receivers by entity before ranking;
  - `chauffeur/static/twin/bake/bake_pass.js` and `baker.js`: per-shape emitter sampling; the fingerprint includes `emitterSignature`, and the version tag becomes `light-slots-8`.
- Test: create `chauffeur/tests/test_twin_bake_fixtures_js.py`.

**Interfaces:**
- Consumes Task 2's emitters.
- Produces baked pages with one channel per entity per chart.
- **Sampling per shape:**
  - spot: the point emitter masked by a smoothstep cone (`cone_deg`, `softness`);
  - line: N samples (one per 0.5 ft, at least 4) with cosine facing;
  - area: a grid sampled at 0.5 ft;
  - all with shadows from the existing occluder pass;
  - sample weights sum to the fixture's share.

- [ ] **Step 1: Write failing tests:**
  - `twelve_fixtures_one_entity_one_channel_per_chart`;
  - `spot_cone_lights_inside_only`;
  - `line_facing_down_grazes_wall_below` (more energy on the wall face under the run than above it);
  - `area_total_matches_output`;
  - `reaim_changes_fingerprint_and_marks_stale`;
  - `legacy_house_bake_identical` (same bake inputs and fingerprint as before; the version tag aside, compare the emitter inputs).
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it, then `test_twin_bake_runtime_js` and the atlas tests (`ls tests | grep -i bake`). The controller runs a Chromium bake: two bakes leave nothing stale, and a night screenshot shows the grazing band under a wall-cap run. Expected: PASS.
- [ ] **Step 5:** Commit (controller). **Slice C lands.**

## Slice D: editor

### Task 5: The fixture card, multi-drop and the aim tool (shared with cameras)

**Files:**
- Create: `chauffeur/static/twin/editor/fixtures.js` and `chauffeur/static/twin/editor/aim_tool.js`.
- Modify: `chauffeur/static/twin/editor/device_placement.js` and `cards.js` (a light device's card lists fixtures by entity); camera placement (find the camera facing with `grep -rn facing_deg static/twin services`).
- Test: create `chauffeur/tests/test_twin_fixture_editor_js.py`.

**Interfaces:**
- Consumes the Task 1 ops.
- Produces:
  - **Rows:** one per fixture, with fields, Duplicate and Delete (`promptConfirm`).
  - **"Add fixtures" (multi-drop):** each click posts one `add_light_fixture`, and Done ends the mode.
  - **`aimTool({at, aim, cone_deg, onCommit})`:** drag the aim point on the ground or a wall, with a live cone preview and a cone slider. One commit per drag end.
  - **Cameras:** they get `camera_views: {entity_id: {at, aim, fov_deg}}` (default fov 90), stored by an op `set_camera_view`, which Task 1's module validates. An old `facing_deg` maps to `aim` at 20 ft at load. The frustum preview reuses the cone drawing.

- [ ] **Step 1: Write failing tests:**
  - `multi_drop_posts_one_op_per_click`;
  - `aim_drag_commits_once_with_cone`;
  - `camera_facing_maps_to_aim`;
  - `rows_edit_duplicate_delete_no_browser_dialogs`;
  - `read_only_for_non_parents`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement. Follow `docs/ui_design_guide.md`, and run `python tools/build_tailwind.py` if template classes change.
- [ ] **Step 4:** Run it, then `test_twin_ha_link_js`, `test_twin_material_slot_js`, `test_tailwind_build` and `test_twin_import_maps`. Expected: PASS.
- [ ] **Step 5:** Commit (controller).

### Task 6: Line draw/snap, the area rectangle and detached repair

**Files:**
- Create: `chauffeur/static/twin/editor/line_fixture_tool.js`.
- Modify: `fixtures.js`.
- Test: create `chauffeur/tests/test_twin_line_fixture_tool_js.py`.

**Interfaces:**
- Consumes the Task 1 snap hosts and the Task 5 rows.
- Produces:
  - **Draw mode:** a polyline, using `site_drawing.js`.
  - **Snap mode:** hovering highlights snappable edges (the five host kinds). A click picks the edge, dragging sets `t0`/`t1`, and a select sets `facing`.
  - **Area mode:** drag a rectangle, then pick the facing.
  - **Detached runs** show "Reattach", which re-enters snap mode for that fixture.

- [ ] **Step 1: Write failing tests:**
  - `snap_to_retaining_wall_cap_sets_snap_and_path`;
  - `facing_select_updates_once`;
  - `area_rectangle_commits_size_and_facing`;
  - `detached_row_offers_reattach`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run it, then `test_twin_fixture_editor_js`, `test_twin_terrain_tools_js` and `test_twin_import_maps`. The controller runs a Chromium editor pass that snaps a run to a wall cap and checks the night look. Expected: PASS.
- [ ] **Step 5:** Commit (controller). **Slice D lands.**
