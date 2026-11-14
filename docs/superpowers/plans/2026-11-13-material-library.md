# Material Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A household material library whose materials are PBR map sets plus parameters. You can download materials from Poly Haven and ambientCG, build them from loose textures, or import them from glTF. Each is edited on its own Library page with a live preview, and the house picks from the library through every existing material slot.

**Architecture:**
- A new server module, `services/twin_materials.py`, owns household materials. Each material is stored as a JSON record plus immutable, content-addressed map files under the twin data dir, with revisions, archival and reference scanning.
- The twelve built-in materials are projected into the same catalogue as read-only entries.
- In the browser, `kitMaterial` in `static/twin/twin_library.js` learns the new material schema, and the cache keys gain the material's revision.
- A new page, `/house/library`, holds all editing. The house editor's Library stays a picker.

**Tech Stack:** FastAPI (`chauffeur/main.py`); Python stdlib plus Pillow, which is already in `requirements-twin.txt`; vendored three r187 (`static/vendor/three-r187`), including `GLTFLoader`; and Jinja templates with precompiled Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-13-material-library-design.md`. Read it before any task. Where this plan and the spec disagree, the spec wins.

## Global Constraints

- Read `AGENTS.md` first. Run tests from `chauffeur/` as plain scripts (`python tests/test_x.py`) with `HA_BASE_URL` unset and `PYTHONIOENCODING=utf-8`. Run only the named tests, never the whole suite.
- No new packages and no edits to any `requirements*.txt`. Pillow is already in `requirements-twin.txt`.
- Every new route gets a rule in `services/auth.py`:
  - reads use the tier of `/api/house/twin/library/...` (`WALL_OR_SERVICE`) for files, and parents for the catalogue that the editor and Library page use;
  - writes are `PARENTS`.
- Page JavaScript fetches `base() + 'api/...'`, never a root-relative URL.
- No browser dialogs; use `showGlobalAlert`, `promptConfirm` and `promptInput`.
- After any template class change, run `python tools/build_tailwind.py`.
- Every critical path has a test that runs it: a TestClient request, or node running the real module.
- Old houses render identically: built-in materials keep their current maps, tiling (4 ft, lawn 8 ft), colours and shaders (granite neutral-light, lattice cutout, roof metalness 0.45).
- The image master cap is 4096 px. The tier caps are low 512 px (base colour only), medium 1024 px (all maps) and high 2048 px (all maps).
- Material ids are stable across edits, and map files are immutable and content-addressed (the URL carries a sha256 prefix).
- The material cache key is (id, revision, tier, receiving role, role-specific shader flags). One shared material instance never carries two roles, because `bake/atlas.js` reads `material.name` as the role.
- Do not touch the `house_design` tool schema in `services/agent_tools_v2.py`. It is at 5,955 of a 6,000-character cap.
- Implementers do not bump versions or commit; the controller commits per task and lands per slice.

## Review Focus

1. **An old house with built-in materials renders unchanged** after the schema change: same maps, repeat, colour and shader. Pinned in Task 2.
2. **A surface tinted through today's chooser**, saved as `{id, color}`, keeps its colour after the chooser stops copying colours. Pinned in Task 3.
3. **A map replaced while the house is open in another tab** shows the new pixels without a reload. Pinned in Task 4.
4. **Deleting a material the current house uses** is refused and names the uses; one used only by history is archived, and undo still renders it. Pinned in Task 1.
5. **A truncated JPEG, a 20000 px PNG, or a zip with `../` entries** is refused with nothing published. Pinned in Tasks 1 and 7.

---

## Slice A: the material asset and rendering (lands as one version)

### Task 1: Household material store and routes

**Files:**
- Create: `chauffeur/services/twin_materials.py`
- Modify: `chauffeur/services/twin_library.py`. `material_choices()` returns the merged catalogue rows, and `material_slot_error()` accepts any live or archived household id.
- Modify: `chauffeur/main.py`, adding the routes below. Both page routes (`/house/twin` and `/house/editor`, around lines 2007-2014) pass `twin_manifest` = `twin_materials.page_manifest()` instead of `twin_library.manifest()`.
- Modify: `chauffeur/services/auth.py`, with one rule per new route.
- Test: create `chauffeur/tests/test_twin_materials.py`.

**Interfaces:**
- Produces, in `services/twin_materials.py`:
  - **Storage:** `root() -> Path` is `<twin data dir>/materials`. Each material has `root()/<id>/material.json`, and its maps are stored in `root()/<id>/maps/<sha12>.<png|jpg>`.
  - **Record:** `{id, name, source: 'user'|'polyhaven'|'ambientcg'|'gltf', licence, source_url, based_on, revision:int, archived:bool, created_by, updated_at, maps:{slot: file}, params:{...}, source_snapshot:{maps, params}|None}`.
    - Slots are `base_color|normal|roughness|metalness|ao|orm|height`.
    - `params` holds `tint` (a hex string), `roughness`, `metalness`, `normal_scale`, `normal_convention` (`gl` or `dx`), `ao_intensity`, `tile_ft` (`[w, h]`), `rotation_deg` and `random_offset` (bool).
  - **Defaults:** tint `#ffffff`, roughness 1, metalness 1, normal_scale 1, `gl`, ao_intensity 1, tile_ft `[4, 4]`, rotation_deg 0, random_offset false.
  - **Ranges:**
    - roughness and metalness: 0-2;
    - normal_scale: 0-4;
    - ao_intensity: 0-2;
    - tile_ft: 0.25-200 per axis;
    - rotation_deg: 0-359.
  - `catalogue(include_archived=False) -> {'revision': int, 'materials': [row]}`. Each row has `{id, name, source, color, thumbnail_url|None, builtin:bool, archived:bool, revision}`.
    - Built-ins come first and are projected from `twin_library.manifest()` plus the kit, with `builtin: True` and `revision: 0`.
    - The top-level `revision` is a counter that increases on every write.
  - `get(material_id) -> record`. For built-ins it returns a read-only projection.
  - `page_manifest() -> dict`, which is `twin_library.manifest()` merged with one entry per household material. Each entry is `{'kind': 'material', 'household': True, 'revision': r, 'maps': {slot: url_path}, 'params': {...}}`, where `url_path` is `materials/<id>/<file>`.
  - `create(fields, actor) -> record`, `update(material_id, change, actor) -> record` (revision + 1, merges `params`, `maps` values are files already ingested), and `duplicate(material_id, actor) -> record`. `duplicate` works for built-ins too: it copies the built-in's map files into a household record with its current kit colour as the tint.
  - `ingest_image(material_id, slot, data: bytes) -> file`:
    - decodes fully with Pillow and refuses on any decode error;
    - downscales anything over 4096 px on its longest side;
    - writes PNG for normal, roughness, metalness, ao, orm and height maps, and JPG quality 92 for base_color;
    - names the file by sha256 of the written bytes;
    - limits: 40 MB per input file, 12 files per material, 200 MB per material.
  - `uses(material_id) -> {'current': [labels], 'history': bool}`, which scans the current model, every round (`twin_store.rounds()`) and saved houses if `services/twin_house_saves.py` exists at build time.
  - `delete(material_id, actor) -> {'archived': bool}`:
    - raises `ValueError('Used on N surfaces: …')` when `uses().current` is non-empty;
    - archives when only history uses the material;
    - otherwise removes its folder.
  - `reset_to_source(material_id, actor) -> record`.
  - `undo(material_id)` and `redo(material_id)` step the revision, using the revision files kept as `root()/<id>/revisions/<n>.json`.
- **Routes** (all JSON unless noted):
  - `GET /api/house/materials` returns `catalogue()` (parents);
  - `GET /api/house/materials/{id}` returns the record (parents);
  - `GET /api/house/twin/materials/{id}/{file}` returns a file response with `Cache-Control: public, max-age=31536000, immutable` (`WALL_OR_SERVICE`);
  - `POST /api/house/materials` creates;
  - `PATCH /api/house/materials/{id}` updates;
  - `POST /api/house/materials/{id}/duplicate`;
  - `POST /api/house/materials/{id}/maps/{slot}` takes raw image bytes in the body, ingests them, and sets the slot;
  - `DELETE /api/house/materials/{id}/maps/{slot}` clears the slot;
  - `POST /api/house/materials/{id}/undo|redo|reset`;
  - `DELETE /api/house/materials/{id}`.
  - Writes are parents only. Every `ValueError` becomes a 400 carrying its message.

- [ ] **Step 1: Write failing tests** in `tests/test_twin_materials.py`. Use the isolated data dir and TestClient fixture pattern from `tests/test_twin_ha_display.py` (`from test_twin_ha_routes import Ctx, seed, ts`).
  - `test_catalogue_lists_twelve_builtins_first_read_only`: `GET /api/house/materials` has 12 rows with `builtin: True` before any household row. A `PATCH` on a built-in id returns 400.
  - `test_create_ingest_and_serve_immutable_map`: create a material, POST a 64×64 PNG to `maps/base_color`, `GET` the file URL, and assert the bytes decode, the `Cache-Control` header contains `immutable`, and the file name equals the first 12 characters of the sha256.
  - `test_update_keeps_id_and_bumps_revision`: a PATCH on `params.tint` keeps the id, raises the record revision by 1 and raises the catalogue revision. Undo restores the previous tint, and redo reapplies it.
  - `test_bad_images_refused_nothing_published`: a truncated JPEG, a 5000×5000 PNG and an 11th or 13th file are refused or handled as follows. The 5000 px PNG is accepted but downscaled to 4096. The truncated file and the 13th file are refused with 400, and no new file appears under `maps/`.
  - `test_delete_in_use_refused_history_archives`: assign the material to a wall through the `set_material` op. Delete returns 400 with "Used on". Reassign the wall to a built-in, delete again, and get `archived: True`. Undo the house edit (`twin_store.revert`): the model references the archived id, `material_slot_error` accepts it, and `GET /api/house/twin/materials/{id}/{file}` still serves.
  - `test_duplicate_builtin_and_reset_to_source`: duplicating `red_brick_03` makes a household copy with `based_on: 'red_brick_03'` and the built-in's maps. Reset to source restores its maps and params after an edit.
  - `test_parents_only`: kid and panel tokens get 401 or 403 on every write.
  - `test_page_manifest_carries_household_material`: the `/house/editor` HTML contains the household id inside `window.twinManifest`.
- [ ] **Step 2: Run** `python tests/test_twin_materials.py`. Expected: FAIL, because the module does not exist yet.
- [ ] **Step 3: Implement** `services/twin_materials.py`, the routes and the auth rules as specified in Interfaces. Use atomic writes (a temp file plus `os.replace`). Hold one `threading.Lock` per material id for writes.
- [ ] **Step 4: Run** `test_twin_materials`, then the neighbour tests: `test_twin_yard_material_slots`, `test_twin_porch_foundation` (and its js), `test_twin_model_bridge`, `test_twin_library`, `test_house_design_tool`, `test_twin_ha_routes`. Expected: all PASS.
- [ ] **Step 5: Commit** (controller).

### Task 2: Render household materials (maps, parameters, tiling, revision keys)

**Files:**
- Modify: `chauffeur/static/twin/twin_library.js` (`kitMaterial`, `materialSlot`, `libUrl`).
- Test: create `chauffeur/tests/test_twin_material_render_js.py`, a node test in the style of `tests/test_twin_yard_material_slots_js.py`.

**Interfaces:**
- Consumes the `page_manifest()` entry shape from Task 1.
- Produces:
  - `libUrl(assetId, name)` resolves `materials/<id>/<file>` paths to `base() + 'api/house/twin/materials/...'`.
  - `materialKey(value, role, tier, manifest) -> string`, exported and used by `materialSlot` and `buildYard`. The string is `JSON.stringify(['m', id, revision, tier, role, color||null, flags])`, where `flags` names the role-specific shaders (`granite`, `lattice`, `roof`).
  - `applyMaterialParams(material, entry, ref, role, tier)`, exported and reused by the Library preview in Task 5.

**Mapping rules:**
- **Maps:** `map` comes from `base_color` (sRGB). `normalMap` comes from `normal`, with `normalScale = (s, normal_convention === 'dx' ? -s : s)`. `roughnessMap`, `metalnessMap` and `aoMap` come from their own slots. When there is an `orm` map, all three point at the same texture, which three reads as R ao, G rough, B metal.
- **Parameters:** `roughness` and `metalness` are the multipliers, or 1 with no map. `aoMapIntensity` is `ao_intensity`. Each texture's `repeat` is `(1 / tile_ft[0], 1 / tile_ft[1])` and its `rotation` is `rotation_deg` in radians.
- **Tint:** `color` is the slot `color` when present (it replaces the tint), otherwise `params.tint`.
- **Tier:** the low tier loads only `base_color`.
- **Built-ins:** they keep the existing code path byte-for-byte.

- [ ] **Step 1: Write failing tests:**
  - `builtin_materials_unchanged`: for each kit role, `kitMaterial` produces the same `color`, `roughness`, `metalness`, map URLs and repeat as a snapshot taken from current main (record it in the test).
  - `household_maps_and_params_applied`: a manifest entry with all slots and DX normals gives the expected map URLs, `normalScale.y < 0`, repeat `[1/6, 1/3]` for `tile_ft [6, 3]`, and `aoMapIntensity` and the multipliers as set.
  - `orm_shares_one_texture`: with an `orm` map, `roughnessMap === metalnessMap === aoMap`.
  - `low_tier_base_colour_only`.
  - `slot_color_replaces_tint`.
  - `same_material_two_roles_two_instances`: `materialSlot({id}, 'roof', …)` and `materialSlot({id}, 'interior_wall', …)` return different instances, with `.name === 'roof'` and `.name === 'interior_wall'` respectively.
  - `revision_changes_key`.
- [ ] **Step 2: Run** `python tests/test_twin_material_render_js.py`. Expected: FAIL.
- [ ] **Step 3: Implement** the rules above in `twin_library.js`.
- [ ] **Step 4: Run** it, then `test_twin_yard_material_slots_js`, `test_twin_material_slot_js`, `test_twin_porch_foundation_js`, `test_twin_bake_runtime_js`, `test_twin_energy_js` and `test_twin_import_maps`. Expected: PASS.
- [ ] **Step 5: Commit** (controller).

### Task 3: Choosers save `{id}`; explicit tint override

**Files:**
- Modify: `chauffeur/static/twin/editor/material_slot.js` (around line 49) and `chauffeur/static/twin/editor/library.js` (`surfaceOperation`, around line 82).
- Modify: `chauffeur/static/twin/editor/material_catalog.js`. It reads `api/house/materials`, and each row gains a `thumbnail_url`.
- Test: modify `chauffeur/tests/test_twin_material_slot_js.py` and `chauffeur/tests/test_twin_library_js.py`, or the editor library's existing node test (find it with `grep -l "surfaceOperation" tests`).

**Interfaces:**
- Consumes the catalogue rows from Task 1.
- Produces: a pick saves `{id}`. An "Override tint" colour input saves `{id, color}`. "Clear override" saves `{id}`. "Use default" saves `null`.

- [ ] **Step 1: Write failing tests:**
  - `pick_saves_id_only`: choosing a catalogue entry calls `onChange({id})` with no `color` key.
  - `override_then_clear`: Override tint calls `onChange({id, color:'#123456'})`, and Clear override calls `onChange({id})`.
  - `legacy_color_shows_clear_override`: a value of `{id, color}` renders a "Clear override" control.
  - `surface_operation_id_only`: `surfaceOperation(...)` emits `material: {id}` for a plain pick.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, plus `test_twin_terrain_tools_js`, `test_twin_yard_material_slots_js` and `test_tailwind_build` if any template classes changed. Expected: PASS.
- [ ] **Step 5: Commit** (controller).

### Task 4: Live invalidation and bake staleness

**Files:**
- Modify: `chauffeur/static/twin/twin_view.js` (around line 750, where material reuse is decided), `chauffeur/static/twin/twin_library.js` (add `refreshMaterials(ids)`) and `chauffeur/static/twin/bake/runtime.js` and `bake/reach.js` (staleness).
- Modify: `chauffeur/main.py` so that a material write sends the existing `chf-server-update` push. Find how the existing server push is emitted with `grep -n "chf-server-update" -r chauffeur`.
- Test: create `chauffeur/tests/test_twin_material_live_js.py`.

**Interfaces:**
- Consumes `GET /api/house/materials` and its `revision`.
- Produces:
  - `watchMaterialCatalogue(view, {api}) -> {stop()}` in a new `static/twin/material_watch.js`. It refetches on window focus, on `chf-server-update` and every 60 s. When the revision changes it updates the merged manifest, and for each id whose revision changed it rebuilds the cached materials and calls `view.render()`.
  - Bake: any changed id used by baked surfaces marks the bake stale (the bake's existing stale flag) and clears that layout's reach cache.

- [ ] **Step 1: Write failing tests:**
  - `new_map_url_after_replace`: with a material cached at revision 1, a catalogue revision 2 with a different base colour file makes the scene's material `map.source` URL the new one.
  - `tint_edit_reaches_two_views`: two mounted views share one catalogue, and after a tint change both materials' colours update.
  - `bake_marked_stale_on_material_revision`.
  - `unrelated_materials_untouched`: no rebuild happens for ids whose revision did not change.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement**, and mount `watchMaterialCatalogue` in `twin_view.js` for both the live house and the editor.
- [ ] **Step 4: Run** the tests, plus `test_twin_bake_runtime_js`, `test_twin_live_control_js` and `test_twin_material_render_js`. The controller also runs the browser tests `test_house_twin_energy_live` and the bake browser test (`grep -l bake tests/test_house_*live*.py`). Expected: PASS.
- [ ] **Step 5: Commit** (controller). **Slice A lands** (bump, capabilities entry, ff-merge, push). Before landing, the controller checks in Chromium that a household material with all maps renders on a wall.

## Slice B: the Library page and creating from loose textures

### Task 5: Library page with grid, preview and properties

**Files:**
- Create: `chauffeur/templates/house_library.html`, `chauffeur/static/twin/library_page/page.js`, `chauffeur/static/twin/library_page/preview.js` and `chauffeur/static/twin/library_page/properties.js`.
- Modify: `chauffeur/main.py`, adding `GET /house/library` with `twin_manifest` context like `/house/editor`.
- Modify: `services/auth.py`, adding `(ANY, '/house/library', ANYONE, None)` like `/house/editor`; the admin gate in the page handles parents.
- Modify: the house editor top bar, adding a "Library" link, and `static/twin/editor/library.js`, adding "Edit in Library" on a material that opens `house/library?material=<id>`.
- Test: create `chauffeur/tests/test_twin_library_page_js.py` (node) and `chauffeur/tests/test_house_library_page.py` (TestClient: the page renders and is in the auth table).

**Interfaces:**
- Consumes the Task 1 routes and Task 2's `applyMaterialParams`.
- Produces: `mountLibraryPage(root, {api}) -> {stop()}` and `createPreview(canvas) -> {setMaterial(entry, params), setShape('sphere'|'cube'|'wall'|'ground'), setLight('studio'|'sun'), dispose()}`. The preview includes a 6 ft scale figure and orbit controls (`OrbitControls` from the vendored three addons).
- **Property edits** call `preview.setMaterial` synchronously, with no fetch, then PATCH debounced by 300 ms. Undo and redo call the Task 1 routes.
- **Delete** confirms with `promptConfirm` and reports a refusal through `showGlobalAlert` with the server's "Used on …" text.
- Follow `docs/ui_design_guide.md`. The layout is a grid on the left, the preview in the centre and properties on the right; on a phone the three stack.

- [ ] **Step 1: Write failing tests:**
  - `param_change_updates_preview_without_fetch`: a roughness slider input changes the preview material's `roughness` before any fetch, and exactly one PATCH happens after 300 ms when two inputs arrive within 300 ms.
  - `builtin_shows_duplicate_not_edit`.
  - `delete_refusal_shows_reason_no_dialog`.
  - `undo_redo_call_routes`.
  - `edit_in_library_link_carries_id` (editor side).
  - In the TestClient test, `/house/library` returns 200 and contains `window.twinManifest`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement**, then run `python tools/build_tailwind.py`.
- [ ] **Step 4: Run** the tests, plus `test_tailwind_build`, `test_twin_import_maps` and the auth route classification test (`grep -l "every new route" tests`, or `test_auth_routes`). Expected: PASS.
- [ ] **Step 5: Commit** (controller).

### Task 6: Create from loose textures

**Files:**
- Create: `chauffeur/static/twin/library_page/texture_slots.js`.
- Modify: `chauffeur/static/twin/library_page/properties.js`.
- Test: create `chauffeur/tests/test_twin_texture_slots_js.py`.

**Interfaces:**
- Produces `slotForFilename(name) -> {slot, convention?}|null`, with these rules, case-insensitive, matched on the stem's last `_` or `-` token or the spec's suffixes:
  - `basecolor|albedo|diff|diffuse|color|col` → `base_color`;
  - `normalgl|nor_gl|normal` → `normal` (gl);
  - `normaldx|nor_dx` → `normal` (dx);
  - `rough|roughness` → `roughness`;
  - `metal|metalness|metallic` → `metalness`;
  - `ao|occlusion|ambientocclusion` → `ao`;
  - `arm|orm` → `orm`;
  - `height|disp|displacement` → `height`.
- Drop handling: files that match are uploaded to their slot (Task 1 route), and the preview shows a local object URL immediately. A file that matches nothing asks for its slot with `promptInput`, offering a select list of slots.

- [ ] **Step 1: Write failing tests:**
  - `suffix_table`: parametrised over Poly Haven names (`x_diff_2k.jpg`, `x_nor_gl_2k.png`, `x_nor_dx_2k.png`, `x_rough_2k.png`, `x_arm_2k.png`) and ambientCG names (`X_2K-JPG_Color.jpg`, `X_2K-JPG_NormalGL.jpg`, `X_2K-JPG_NormalDX.jpg`, `X_2K-JPG_Roughness.jpg`, `X_2K-JPG_Metalness.jpg`, `X_2K-JPG_AmbientOcclusion.jpg`).
  - `drop_uploads_each_to_its_slot_and_previews_locally`.
  - `unknown_file_asks_slot_via_promptInput`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** (controller). **Slice B lands.** Before landing, the controller takes Chromium screenshots of the Library page with a dropped texture set, and of a wall in the house view wearing that material.

## Slice C: browse online

### Task 7: Bounded online sources and a download job

**Files:**
- Create: `chauffeur/services/twin_material_sources.py`.
- Modify: `chauffeur/main.py` and `services/auth.py`, adding the routes below.
- Test: create `chauffeur/tests/test_twin_material_sources.py`. All HTTP goes through an injectable `_urlopen`, faked in tests, so no real network is used.

**Interfaces:**
- Produces:
  - `search(source: 'polyhaven'|'ambientcg', query: str, category: str|None) -> [{source, source_id, name, thumbnail, resolutions:[...]}]`. Results are cached for 10 minutes. Poly Haven uses `https://api.polyhaven.com/assets?t=textures` with a local text filter. ambientCG uses `https://ambientcg.com/api/v2/full_json?type=Material&q=<query>&include=downloadData`.
  - `thumbnail(source, source_id) -> bytes`, cached on disk under `root()/../material_sources/thumbs`.
  - `start_download(source, source_id, resolution, actor) -> job_id`, `job(job_id) -> {state: 'queued'|'running'|'done'|'failed', progress: 0..1, material_id?, error?}`.
    - One worker thread runs one job at a time.
    - Reads are streamed with caps of 64 MB per file and 300 MB per job, and a deadline of 180 s.
    - Archives (ambientCG zips) allow at most 64 entries and 400 MB expanded. Any entry whose path has `..`, starts with `/` or has a drive letter is refused, and only mapped image entries are extracted.
    - Every image goes through `twin_materials.ingest_image`.
    - Staging is removed on failure, and the material is published only on success, with `source_snapshot` set.
- **Routes:**
  - `GET /api/house/materials/sources/{source}?q=&category=` (parents);
  - `GET /api/house/materials/sources/{source}/{source_id}/thumb` (parents);
  - `POST /api/house/materials/sources/{source}/{source_id}/download` with body `{resolution}` (parents);
  - `GET /api/house/materials/jobs/{job_id}` (parents).
- With no network, search returns 503 with "Online libraries are not reachable."

- [ ] **Step 1: Write failing tests:**
  - `polyhaven_download_maps_slots`: the fake API returns diff, nor_gl, rough and arm files, and the published material has `base_color`, `normal` (gl), `roughness` and `orm`, with `source: 'polyhaven'` and a licence of CC0.
  - `ambientcg_zip_download_maps_slots`.
  - `zip_traversal_refused_nothing_published`.
  - `zip_bomb_refused`: a 1 MB entry that declares or expands past 400 MB.
  - `oversize_stream_refused`: the fake stream goes past 64 MB, the job fails, and no folder is left behind.
  - `deadline_refused`.
  - `one_job_at_a_time`.
  - `offline_search_503_message`.
  - `parents_only`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, plus `test_twin_materials`. Expected: PASS.
- [ ] **Step 5: Commit** (controller).

### Task 8: The Browse panel on the Library page

**Files:**
- Create: `chauffeur/static/twin/library_page/browse.js`.
- Modify: `page.js`.
- Test: create `chauffeur/tests/test_twin_library_browse_js.py`.

**Interfaces:**
- Produces a Browse view with a source switch, a search box (debounced 300 ms), a thumbnail grid served through the server's thumbnail route, a resolution select (1k/2k/4k, default 2k) and Add.
- After Add, it polls the job every 500 ms, shows progress, and opens the new material in the editor when done. A failure is shown with `showGlobalAlert` and the server's error.

- [ ] **Step 1: Write failing tests:**
  - `search_debounced_once`.
  - `add_polls_job_and_opens_material`.
  - `failure_reason_shown_no_dialog`.
  - `offline_message_shown`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** (controller). **Slice C lands.** Before landing, the controller tries the real network in Chromium once: search "brick" on both sources, add one at 1k, and take a screenshot.

## Slice D: glTF import and per-surface random offset

### Task 9: glTF material import

**Files:**
- Create: `chauffeur/static/twin/library_page/gltf_import.js`.
- Modify: `page.js`.
- Test: create `chauffeur/tests/test_twin_gltf_material_js.py`, using a tiny generated `.glb` fixture with an embedded PNG.

**Interfaces:**
- Produces `readGltfMaterials(files: File[]) -> [{name, maps:{slot: Blob}, params}]`, built with the vendored `GLTFLoader` and a `LoadingManager` that resolves sibling textures for `.gltf`. The mapping is:
  - `baseColorTexture` → `base_color`, and `baseColorFactor` → `tint` (as hex);
  - `metallicRoughnessTexture` → `orm`. glTF stores roughness in G and metalness in B; AO is absent there, so R is unused unless the occlusion texture is the same image;
  - `roughnessFactor` and `metallicFactor` → the multipliers;
  - `normalTexture` → `normal` (gl) and its `scale` → `normal_scale`;
  - `occlusionTexture` → `ao` and its `strength` → `ao_intensity`.
- With several materials in the file, the person chooses one through `promptInput` with a select list. The import then uploads each map through the Task 1 route on a new material with `source: 'gltf'`.

- [ ] **Step 1: Write failing tests:**
  - `glb_maps_and_factors`.
  - `multiple_materials_ask_which`.
  - `gltf_with_sibling_textures`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** (controller).

### Task 10: Per-surface random UV offset

**Files:**
- Modify: `chauffeur/static/twin/twin_generator.js` (where wall, floor and roof geometry gets UVs, before batching by material at about line 67) and `chauffeur/static/twin/twin_yard.js` (the yard surfaces).
- Test: create `chauffeur/tests/test_twin_uv_offset_js.py`.

**Interfaces:**
- Produces `uvOffsetFor(seedId: string, tileFt: [w, h]) -> [du, dv]`, a stable hash of the piece id that maps to `[0, w) × [0, h)` feet. It is applied to the geometry's `uv` attribute only when the surface's material has `params.random_offset`.

- [ ] **Step 1: Write failing tests:**
  - `same_id_same_offset`.
  - `different_walls_different_offsets_same_material_instance`: two walls in one random-offset material have different UV origins, and the batch still holds one material.
  - `off_by_default_geometry_unchanged`: the UVs equal current main's for a material without `random_offset`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests, plus `test_twin_material_render_js`, `test_twin_yard_material_slots_js`, and the generator's existing node tests (`grep -l "buildTwin" tests/*_js.py`). Expected: PASS.
- [ ] **Step 5: Commit** (controller). **Slice D lands.**
