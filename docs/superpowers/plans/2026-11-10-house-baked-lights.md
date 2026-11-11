# Baked room lights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each light's contribution, and the sky's, is baked into lightmaps on the desktop GPU. At runtime it is scaled by live brightness and colour, so lit rooms get soft shadows, no light through walls, a glow at lit windows, and almost no cost on the Pi.

**Architecture:** After `mergeStatic`, the merged house meshes get a deterministic second UV set packed into atlas pages (`static/twin/bake/atlas.js`). A GPU texture-space baker (`static/twin/bake/baker.js`) renders each light's direct light, plus visibility from a cube shadow map, plus jittered soft-shadow samples and a light blur, into one channel of an RGBA page. It also bakes a sky-visibility channel. Pages are stored as PNGs through the server (`services/twin_bakes.py`) and keyed by geometry and light spots. A runtime material patch (`static/twin/bake/lightmap_material.js`) sums `channel × brightness × colour` and `sky × current sky colour`. A light with no fresh bake falls back to the real-time pool from v2.499.783.

**Tech Stack:** vendored three.js r187 (WebGLRenderTarget, CubeCamera or a cube shadow, `onBeforeCompile`), FastAPI, PNG via Pillow (already in requirements-twin.txt), node and Playwright tests. No new packages.

**Spec:** `docs/superpowers/specs/2026-11-10-house-baked-lights-design.md` (user answers in §5).

## Global Constraints

- **Where baking runs:** only on High and Max tiers, only in a browser (the meshes exist only there), on idle frames, never while the person drags, and never on the Pi (Low).
- **Trigger:** any open 3D view, meaning the editor or `/house/twin`, re-bakes stale lights in the background (user, 2026-11-10). There is also a `Bake lighting now` control.
- **What is baked:** room lights and sky visibility. The sun and moon stay real-time (spec §5).
- **Atlas:**
  - deterministic: the same model and generator version give the same atlas;
  - 2-texel gutters, no overlapping charts;
  - High density 8 texels/ft;
  - pages are 2048² RGBA.
- **Channels:** single-channel per light, four lights to a page, grouped by room so a surface reads one page. Sky visibility is its own channel set.
- **Bake key:** a hash of the geometry (the model round's walls, openings, roofs, rooms, levels and buildings), the generator version, the atlas parameters and the light's spot. Only stale lights re-bake. A stale light draws real-time until its bake lands.
- **Routes:**
  - upload is PARENTS;
  - download is WALL_OR_SERVICE with an ETag;
  - every route gets a tier in `services/auth.py`.
  - Pages are size-capped, and keys no longer referenced by the current model are removed.
- **Fallback:**
  - The real-time pool, fixture glow and wash from v2.499.783 stay for any light without a fresh bake.
  - With no Home Assistant, a light reads as off.
  - With no bake at all, Lights mode behaves exactly as v2.499.783.
- **Window glow:** a lit room's glazed windows glow from outside, scaled by the room's baked-light total at the window.
- **Housekeeping:**
  - No browser dialogs.
  - Page JS fetches `base() + 'api/...'`.
  - Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset.
  - Keep green: the live and real-lights suites (`tests/test_twin_real_lights_js.py`, `tests/test_house_twin_real_lights_live.py`, `tests/test_house_twin_live_rooms.py`, `tests/test_house_twin_live_markers.py`, `tests/test_twin_view_live.py`).

## Review Focus

1. **Geometry changes while a bake runs** (an edit, a build round): the in-flight bake is thrown away, never uploaded under the old key or shown on new geometry.
2. **Two desktop tabs bake at once:** no torn page. The last upload wins atomically per page, and both end on the same key.
3. **A Pi panel opens while bakes are partial:** baked lights draw baked, the rest draw real-time, and nothing errors when a page fetch 404s.
4. **A light is moved by hand:** only that light re-bakes. Other channels on its page keep their data, because the page is rewritten with the other channels untouched.
5. **A room has more than four lights:** they spill to a second page, and surfaces in that room read both. The surface-to-page grouping must allow that.

---

### Task 1: The lightmap atlas
**Files:** create `chauffeur/static/twin/bake/atlas.js`. Test: `chauffeur/tests/test_twin_bake_atlas_js.py` (node).
**Interfaces:**
- `buildAtlas(group, {density, page, gutter}) -> {pages: n, charts: [{mesh, faces, page, rect}], key}`.
- It adds a `uv2` attribute to each merged mesh in place.
- Charts come from coplanar connected faces, are scaled to world size × density, and are packed by a deterministic shelf packer, sorted by size then id.
- [ ] Tests:
  - `same_model_same_atlas` (two builds of the household fixture give equal `uv2` arrays and equal `key`);
  - `charts_never_overlap_and_keep_gutters`;
  - `texel_density_matches_world_size`;
  - `every_interior_face_has_uv2`;
  - `pages_grow_when_one_is_full`.
- [ ] Fail, implement, pass. Commit `feat(twin-bake): a lightmap atlas for the house`.

### Task 2: Bake storage and keys
**Files:** create `chauffeur/services/twin_bakes.py`; modify `chauffeur/main.py` and `chauffeur/services/auth.py`. Test: `chauffeur/tests/test_twin_bakes.py` (TestClient).
**Interfaces:**
- `POST /api/house/bakes/{key}/{page}.png` (PARENTS; PNG body; size cap 16 MB; the key format is validated). It writes atomically to `DATA_DIR/bakes/<key>/<page>.png`.
- `GET` the same path (WALL_OR_SERVICE, ETag, 404 when missing).
- `GET /api/house/bakes/{key}` returns a manifest `{pages, lights:{device: {page, channel, key}}, sky:{page, channel}}`.
- `PUT` the manifest (PARENTS).
- `twin_bakes.prune(live_keys)` removes the rest.
- [ ] Tests:
  - `upload_then_download_with_etag`;
  - `non_parent_upload_is_refused`;
  - `bad_key_and_oversize_refused`;
  - `concurrent_uploads_never_tear_a_page` (Review Focus 2);
  - `prune_keeps_only_live_keys`;
  - `wall_panel_can_read`.
- [ ] Fail, implement, pass (plus `tests/test_auth*.py` route-classification neighbours). Commit `feat(twin-bake): store baked light pages`.

### Task 3: The baker
**Files:** create `chauffeur/static/twin/bake/baker.js`; modify `chauffeur/static/twin/twin_view.js` (idle hook, tier gate). Test: node `chauffeur/tests/test_twin_baker_js.py` (logic with a fake renderer); live `chauffeur/tests/test_house_twin_bake_live.py`.
**Interfaces:**
- `createBaker(view, {renderer, atlas, lights, api}) -> {staleLights(), bakeNext(), cancel(), progress()}`.
- Per light:
  - render the atlas in texture space;
  - each texel takes the light's irradiance from its world position and normal, times visibility from a cube depth map rendered from the light;
  - 16 jittered samples over a 0.15 ft sphere;
  - a 3×3 edge-aware blur;
  - pack into the light's channel.
- Sky: each texel's visibility of the upper hemisphere, from 32 directional depth maps, packed into the sky channel.
- Uploads go through Task 2; the manifest is updated last.
- It cancels when the model round changes mid-bake (Review Focus 1).
- [ ] Tests:
  - node: `stale_lights_are_only_the_changed_ones` (Review Focus 4), `a_round_change_cancels_and_uploads_nothing`, `more_than_four_lights_spill_to_a_second_page` (Review Focus 5), `low_tier_never_bakes`;
  - live, on the desktop GPU in Chromium: `scenario_bake_runs_on_idle_and_lands`, `scenario_baked_light_does_not_cross_a_wall` (luminance in the next room stays at its unlit value ±3), `scenario_moving_a_light_rebakes_only_it`.
- [ ] Fail, implement, pass. Commit `feat(twin-bake): bake each light and the sky on the desktop GPU`.

### Task 4: Baked lights at runtime
**Files:** create `chauffeur/static/twin/bake/lightmap_material.js`; modify `chauffeur/static/twin/live/modes.js` and `real_lights.js` (use the bake when fresh, the pool otherwise), and `chauffeur/static/twin/twin_view.js` (sky channel times the current sky colour; window glow). Test: node `chauffeur/tests/test_twin_lightmap_material_js.py`; live scenarios in `test_house_twin_bake_live.py`.
**Interfaces:**
- `patchLightmaps(materials, pages, uniforms)` uses `onBeforeCompile` with fixed uniform arrays (no recompiles on toggle):
  - `lightTint[16]` (rgb × intensity per channel slot);
  - `skyTint`.
- A light with a fresh bake takes no pool slot.
- Windows of a room get an emissive term equal to the room's baked lit total.
- [ ] Tests:
  - node: `fixed_uniforms_never_recompile`, `fresh_bake_frees_the_pool_slot`;
  - live: `scenario_baked_kitchen_lights_like_the_real_one` (near-fixture rise > 25, far corner lower), `scenario_toggle_is_exact` (off returns pixels to unlit ±2), `scenario_colour_follows_live`, `scenario_lit_room_glows_through_its_windows_from_outside`, `scenario_pi_tier_draws_baked_lights` (?tier=low; a partial bake mixes baked and real-time without errors, Review Focus 3), `scenario_no_bake_behaves_like_783`.
- [ ] Fail, implement, pass. Commit `feat(twin-bake): lit rooms from their bakes, toggled live`.

### Task 5: Trigger, status and the button
**Files:** modify `chauffeur/static/twin/twin_view.js`, `chauffeur/templates/house_twin.html`, `chauffeur/static/twin/editor/editor.js` (the editor kicks the baker too); `services/settings_registry.py` only if a setting is needed (none planned). Test: live scenarios in `test_house_twin_bake_live.py`.
**Interfaces:**
- The twin settings show `Baking lights {n} of {m}` while baking, and `Bake lighting now` (a button that bakes every light again).
- Idle frames only: pause while the pointer is down or the camera moves, resume after 2 s still.
- [ ] Tests: `scenario_bake_pauses_while_dragging`, `scenario_bake_now_rebakes_everything`, `scenario_progress_words`.
- [ ] Fail, implement, pass. Commit `feat(twin-bake): bakes run by themselves and on demand`.

**Execution order:** 1 and 2 (independent), then 3, 4, 5. Tasks 3 to 5 each need a Claude browser round after Codex.
