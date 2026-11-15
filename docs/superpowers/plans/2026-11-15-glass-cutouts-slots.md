# Glass, Cutouts and Material Slots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Library materials can be see-through (cutout or blend), and every drawn surface of the house that has a fixed look today can take a Library material, first as a house default and then per item.

**Architecture:** Slice A adds three parameters and one map slot to the material record and teaches the one material builder (`static/twin/twin_library.js`) the two non-opaque modes; the mode is set from the record synchronously, never from a late texture, so the bake's mesh set does not depend on tier or timing. Slice B adds one surface-kinds table per side (server and browser, held in step by a test) and routes every fixed look in the generator and yard through one lookup that returns today's exact material object when nothing is set. Slice C stores per-item slots under `materials: {<kind>: slot}` on the item, written through `set_material` with new targets, and resolves item, then house default, then parent kind, then today's look.

**Tech Stack:** Python 3 (FastAPI, Pillow), SQLite-backed twin store, browser ES modules with vendored three.js, tests as plain Python scripts that run node drivers through `tests/twin_editor_dom.py`.

**Spec:** `docs/superpowers/specs/2026-11-15-glass-cutouts-slots-design.md` (binding).

## Global Constraints

- Work only in the worktree `E:\repositories\Chauffeur-glass-slots`, branch `glass-slots`. Never edit `E:\repositories\Chauffeur`. Never read anything under `chauffeur/data`. Never open a `*_api_key.txt`.
- Implementers do not commit, do not bump `chauffeur/config.yaml`, and do not edit `chauffeur/system_capabilities.md`. The last step of every task is a note of what changed and what was tested. Claude reviews, runs the gate, and commits.
- Tests are plain scripts run from `chauffeur/` with `HA_BASE_URL` unset: `env -u HA_BASE_URL python tests/<file>.py` (PowerShell: `Remove-Item Env:HA_BASE_URL -ErrorAction SilentlyContinue; python tests/<file>.py`). Run the task's own tests and the neighbours it names. Never run the whole suite.
- Entry points swallow exceptions. Every test in this plan runs the code: a node run of the browser module, or a TestClient request. No test reads source text.
- Chromium tests are listed in "Chromium scenarios, run by Claude" at the end. Implementers write them when the task says so but do not run them; the sandbox cannot launch Chromium.
- `transmission` stays banned (`house-render-headroom`). Blend is `transparent` + `opacity` + `depthWrite: false`, nothing else.
- No added draw calls for a house that sets nothing: an unset slot returns the same shared material object as today, so the merge buckets (`twin_generator.js:68`, by `material.uuid`) do not change.
- Reuse keys (`buildingKeyParts`, `yardMaterialKey`, `yardPartKeys`), `materialKey` output for existing opaque materials, and the bake atlas key are byte-identical to commit `49d96582` for a plan that uses none of the new fields.
- No browser dialogs: `showGlobalAlert`, `promptConfirm`, `promptInput` only. Vendored Alpine `:disabled` bindings are coerced with `!!`.
- After any template class change run `python tools/build_tailwind.py` from `chauffeur/`.
- No new route is expected. If one appears it needs a rule in `services/auth.py`. No new setting is expected; if one appears it goes in `services/settings_registry.py`.
- No new long-lived stream per tab (`twin-tab-stream-limit`). No static file name that reads like a tracker (`no-tracker-like-static-file-names`).
- Nothing a person can do today is removed. The fixture `body` and `top` colour pickers, the porch `materials` (`posts`, `skirt`, `solid`), the foundation slab slot, and the room and roof material lines keep working.
- Agent path: `set_material` is already an agent-reachable op; every new target added here has a hand path in slice B or C in the same slice that adds it.
- UI tasks (A4, B5, C3, C4) follow `chauffeur/docs/ui_design_guide.md` "Spatial house surfaces" and "Process contract for UI agents" (:587-616): read the guide and the nearest sibling end to end, cite a sibling `file:line` for every styling choice, stop and say so if no sibling solved the shape.

## Review Focus

- **Stale bake never applied to a different mesh set.** Flipping a material between opaque and non-opaque changes `buildAtlas(...).key`, and a stored bake for the old key is not mounted. Test: `flipping_alpha_mode_changes_the_atlas_key_and_drops_the_stored_bake` (Task A3).
- **Untouched house is identical.** Material names, material keys, reuse keys, UVs, mesh count and atlas key equal `49d96582`. Test: `untouched_house_equals_main` (Task B2), extended for the yard in B3 and for item slots in C2.
- **Mode never depends on a texture arriving.** The same record gives the same `transparent`/`alphaTest`/`userData.alphaMode` on the low tier and before any map has loaded. Test: `mode_flags_are_set_before_any_map_loads_and_on_low_tier` (Task A2).
- **The two surface-kinds tables agree.** Test: `browser_table_equals_server_table` (Task B1).
- **Invalid slots are refused on write and reset on load, and delete refusal names the new places.** Tests: `load_resets_unknown_ids_in_every_new_slot` (Task C1), `delete_refusal_names_new_surfaces` (Tasks B1 and C1).

---

## Questions and rulings needed

Each item gives the conflict, the recommended ruling, and the tasks written to it. The tasks assume the recommendation.

1. **Garage `door_colour` does not exist in the twin.** The spec's anti-goal names it as a picker that keeps working. It exists only in the older photographic facade (`templates/config.html:2423`, `services/house_facade.py`, `static/house.js`). The twin draws a garage opening as glazing in the generic branch (`static/twin/twin_generator.js:812-816`). *Recommend:* read the sentence as covering fixture `body` and `top` only; a garage opening takes `pane`, `window_frame` and `casing` like any other opening. (B2, C2)
2. **Does an alpha split set the mode?** The spec splits a base colour's alpha into the opacity map but does not say whether `alpha_mode` changes. A material with an opacity map and mode `opaque` shows nothing. *Recommend:* the split sets `alpha_mode` to `cutout` only when the current mode is `opaque` and the alpha channel is not uniformly solid. A glTF material declared `OPAQUE` stays opaque (its alpha is discarded, as glTF requires). Staged source downloads (`ingest_image(staged=True)`) follow the same rule. (A1, A4)
3. **An opaque material in a pane slot.** The spec says an opaque pane gets no glow. Today glow, atlas exclusion and occluder skipping all key on `material.name === 'glass'` (`bake/runtime.js:249`, `bake/atlas.js:605`, `bake/bake_pass.js:89`). *Recommend:* a pane's material is named `glass` only when the resolved material is non-opaque; an opaque material in a pane slot is named `pane`, so it joins the atlas, occludes, and gets no glow. The mesh set changes, the key changes, and the stale-bake rule covers it. The same applies to `shower_glass`. (B2, C2)
4. **Room ceiling fallback and geometry.** The spec says `ceiling` falls back to "today's look" and that a ceiling surface is added where none exists. Today there is no per-room ceiling: the upper slab underside is one `mat('interior_wall')` slab (`twin_generator.js:1218`), the roof underside is `mat('porch_ceiling')` (:1001), and the editor's Ceiling line shows `porch_ceiling` as inherited (`editor/library.js:56`, :222). *Recommend:* draw a per-room ceiling surface only for a room whose `ceiling_material` is set or when the house `ceiling` default is set, 0.02 ft under the slab or roof underside, hidden by the same rule that hides that underside; otherwise draw nothing new. The editor line's inherited label becomes "House look". (B4, B5)
5. **A split roof.** `roofs[].material` is copied to every flat `roof.sections[]` entry (`services/twin_model_roofs.py:99-129`). *Recommend:* one material per model roof; all its sections draw it. (B4)
   **User requirement, 2026-11-15:** "Roof sections need material overrides. My roof is shingles but the porch roof is metal and the pool house is the same split." So B4 is a must, not a tidy-up: every entry of `building.roofs[]` (main roof, porch roof, wing) and every dormer takes its own material override over the building's `roof` default, each building has its own `roof` default, the override is set by hand from the roof's selection card and by dropping a Library material on that roof, and a test builds one building with a shingle main roof and a metal porch roof and asserts the two roofs draw different materials while the fascia and soffit of each are unchanged. A roof drawn as one area is one material; a person who wants two materials on it draws two roofs.
6. **`soffit` and `stair_rail` fall back to `porch_ceiling`.** *Recommend:* the fallback is the role, not a frozen look: with no `soffit` default, a house `porch_ceiling` override keeps driving soffit, stair rail and stringers exactly as today. Likewise `fascia`, `casing`, `column` follow `trim`; `stair_tread` follows `floor`. (B1, B2)
7. **Built-in glass, screen and water in the catalogue.** The kit has no such entries, `builtin_rows` requires `asset` on every kit ref (`services/twin_materials.py:79-88`), and `tests/test_twin_materials.py:89` pins twelve built-ins. *Recommend:* hold the three as code-side built-in looks in the surface-kinds table (ids `glass`, `screen`, `water`, present values), list them in the catalogue as read-only built-ins after the kit's, and change the pinned count to fifteen in the same task. No kit file change. (A2, B1)
8. **Fixture colour against a house default.** The spec's order is item, house default, parent kind, today's look, and today's look for a cabinet is the item's `body` colour. *Recommend:* item slot, then the item's own `body`/`top` colour when the item has one, then the house default, then the built-in colour. A person's per-item colour is not silently overridden by a house-wide choice. (B2, C2)
9. **Where site defaults live.** `lawn` and `water` are yard kinds; `set_material {building, role}` writes a building. *Recommend:* a new target `{site: true, role}` limited to the table's site kinds writes top-level `materials[role]`, which the yard already reads (`twin_yard.js:103-109`). (B3)

## File Structure

Create:

- `chauffeur/services/twin_surface_kinds.py` — the server table, built-in looks, slot cleaning.
- `chauffeur/static/twin/surface_kinds.js` — the browser table, built-in looks, `resolveSlot`.
- `chauffeur/static/twin/editor/house_materials.js` — the House materials panel.
- Tests: `tests/test_twin_alpha_materials.py`, `tests/test_twin_alpha_render_js.py`, `tests/test_twin_alpha_bake_js.py`, `tests/test_twin_alpha_library_page_js.py`, `tests/test_twin_surface_kinds.py`, `tests/test_twin_untouched_house_js.py`, `tests/test_twin_house_defaults_js.py`, `tests/test_twin_yard_defaults_js.py`, `tests/test_twin_ceiling_roof_slots_js.py`, `tests/test_twin_house_materials_panel_js.py`, `tests/test_twin_item_slots.py`, `tests/test_twin_item_slots_js.py`, `tests/test_twin_item_slot_rows_js.py`, `tests/test_twin_item_slot_drop_js.py`, `tests/test_twin_glass_slots_live.py` (Chromium).

Modify: `services/twin_materials.py`, `services/twin_library.py`, `services/twin_model_ops.py`, `services/twin_plan.py`, `services/twin_site_shapes.py`, `static/twin/twin_library.js`, `static/twin/twin_view.js`, `static/twin/twin_generator.js`, `static/twin/twin_stairs.js`, `static/twin/twin_yard.js`, `static/twin/pool_features.js`, `static/twin/library_page/{properties,preview,gltf_import,texture_slots}.js`, `static/twin/editor/{library,cards,site_shape_shelf}.js`, and the pinned tests named in each task.

All paths below are under `chauffeur/` unless they start with `docs/`.

---

## Slice A: Alpha in materials

### Task A1: Record and ingest

**Files:**
- Modify: `services/twin_materials.py` (`SLOTS` :22, `DEFAULT_PARAMS` :23-25, `_params` :159-180, `_image_file` :343-373, `ingest_image` :376, `set_image` :387-391, `page_manifest` :144-156)
- Test: `tests/test_twin_alpha_materials.py` (create); keep green `tests/test_twin_materials.py`, `tests/test_twin_material_sources.py`, `tests/test_twin_import_maps.py`

**Interfaces:**
- Consumes: the existing map upload route (`main.py:8021`) and params route; no route change.
- Produces:
  - `SLOTS` gains `'opacity'`.
  - `DEFAULT_PARAMS` gains `'alpha_mode': 'opaque'`, `'opacity': 1.0`, `'alpha_cutoff': 0.5`.
  - `_params(current, change)` merges `DEFAULT_PARAMS` under `current` before applying `change`; validates `alpha_mode in ('opaque', 'cutout', 'blend')`, `opacity` and `alpha_cutoff` as numbers clamped to 0..1.
  - `_split_alpha(image) -> PIL.Image | None`: mode `L` image of the alpha channel, or `None` when the image has no alpha or every alpha value is 255.
  - `ingest_image` and `set_image` on slot `base_color`: when `_split_alpha` returns an image and the record has no `opacity` map, store it as the `opacity` map (same file encoding as the `roughness` slot) and, when the record's mode is `opaque`, set `alpha_mode` to `cutout` (ruling 2). The base colour file is stored exactly as today.
  - Every read path (catalogue row, `page_manifest`, revision restore) returns the three params with defaults for an old record.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_alpha_materials.py` (TestClient and direct service calls against a temp data dir, as `test_twin_materials.py`):
  - `old_record_reads_as_opaque`: write a record whose stored params lack the three keys; the catalogue row and `page_manifest()` entry both report `alpha_mode == 'opaque'`, `opacity == 1.0`, `alpha_cutoff == 0.5`.
  - `params_validate_mode_and_clamp`: PATCH `alpha_mode: 'frosted'` returns 400 with a message; `opacity: 1.7` stores `1.0`; `alpha_cutoff: -1` stores `0.0`.
  - `base_colour_with_alpha_splits_an_opacity_map`: upload a 4x4 RGBA PNG with a transparent quadrant as `base_color`; the record now has an `opacity` map whose decoded pixels are 0 in that quadrant and 255 elsewhere; `alpha_mode == 'cutout'`; the stored base colour file is byte-identical to what the same upload produced at `49d96582` semantics (RGB JPEG, same dimensions).
  - `split_does_not_replace_an_existing_opacity_map`: upload an opacity map, then an RGBA base colour; the opacity file's hash is unchanged and the mode is unchanged.
  - `solid_alpha_changes_nothing`: an RGBA PNG with alpha all 255 creates no opacity map and leaves the mode `opaque`.
  - `opacity_map_upload_and_clear`: uploading to slot `opacity` and clearing it works through the map route; the manifest lists and then omits the map.
  - `undo_to_a_pre_alpha_revision_reads_defaults`: restore a revision saved without the keys; params read with defaults.
  - `staged_ingest_follows_the_same_rule`: `ingest_image(..., staged=True)` with an RGBA base colour stages an opacity map and the mode change.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_alpha_materials.py`. Expected: FAIL (`KeyError: 'alpha_mode'` or unknown slot `opacity`).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** the new file plus `tests/test_twin_materials.py`, `tests/test_twin_material_sources.py`, `tests/test_twin_import_maps.py`. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task A2: Rendering the two modes

**Files:**
- Modify: `static/twin/twin_library.js` (`materialKey` :125-129, `copyMaterialParams` :202-209, `applyMaterialParams` :233-307, `kitMaterial` :309-374, `materialSlot` :379-405)
- Create: `static/twin/surface_kinds.js` (only `BUILTIN_LOOKS` and `builtinMaterial` in this task; the table arrives in B1)
- Test: `tests/test_twin_alpha_render_js.py` (create); keep green `tests/test_twin_material_render_js.py`, `tests/test_twin_materials_js.py`, `tests/test_twin_library_js.py`, `tests/test_twin_lightmap_material_js.py`, `tests/test_twin_viewing_js.py`

**Interfaces:**
- Consumes: manifest entry `params.alpha_mode`, `params.opacity`, `params.alpha_cutoff`, `maps.opacity` (A1).
- Produces:
  - `alphaModeOf(entry, ref) -> 'opaque' | 'cutout' | 'blend'` (exported from `twin_library.js`): `ref.pattern === 'lattice'` gives `'cutout'`; otherwise `entry?.params?.alpha_mode || 'opaque'`.
  - `applyMaterialParams(material, entry, ref, role, tier)` sets, synchronously and before any texture request: `material.userData.alphaMode`; for `cutout` `alphaTest = alpha_cutoff`, `side = DoubleSide`, `transparent = false`; for `blend` `transparent = true`, `opacity = params.opacity`, `depthWrite = false`, `alphaTest = 0`; for `opaque` the values it resets to today (:261). The opacity map is requested on every tier, including low, for a non-opaque material, and assigned to `alphaMap` when it arrives.
  - The kit lattice keeps its generated texture (`latticeTexture` :91) and its present `alphaTest`; it reports `userData.alphaMode === 'cutout'`.
  - `copyMaterialParams(target, source)` also copies `transparent`, `opacity`, `depthWrite`, `alphaTest`, `alphaMap`, `side`, except onto a target with `userData.viewingOpaque !== undefined` (a viewing clone, `viewing.js:74-83`), where it updates the clone's stored source opacity and depthWrite instead of the live values.
  - `materialKey` output is unchanged for an entry whose mode is `opaque`; for a non-opaque entry it appends the mode (the revision already covers opacity and cutoff).
  - `surface_kinds.js`: `export const BUILTIN_LOOKS = { glass: { color: '#b9d7db', transparent: true, opacity: 0.26, roughness: 0.1, depthWrite: false }, screen: { color: '#59615d', transparent: true, opacity: 0.3, depthWrite: false, doubleSide: true }, water: { color: '#7fd0e6', transparent: true, opacity: 0.65, roughness: 0.12, depthWrite: false } }` and `builtinMaterial(id, name = id) -> THREE.MeshStandardMaterial` giving the same properties as `plain(...)` at `twin_generator.js:463-464` and `twin_yard.js:395`.
  - `materialSlot(value, defaultRole, kit, tier, cache, roleMaterial)` resolves `value.id` in `BUILTIN_LOOKS` to `builtinMaterial(value.id, defaultRole)` tinted by `value.color` when present.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_alpha_render_js.py` (node driver through `run_node`, textures stubbed as in `test_twin_material_render_js.py`):
  - `cutout_sets_alpha_test_and_double_side`: entry `{alpha_mode:'cutout', alpha_cutoff:0.4}` gives `alphaTest === 0.4`, `side === THREE.DoubleSide`, `transparent === false`, and after the stub loader resolves, `alphaMap` is the opacity texture.
  - `blend_sets_opacity_and_no_depth_write`: entry `{alpha_mode:'blend', opacity:0.35}` gives `transparent === true`, `opacity === 0.35`, `depthWrite === false`, `alphaTest === 0`, and no `transmission` property above 0.
  - `mode_flags_are_set_before_any_map_loads_and_on_low_tier`: with a loader that never resolves, on tiers `low` and `high`, `transparent`, `alphaTest`, `side`, `depthWrite`, `userData.alphaMode` equal the values above; on `low` the loader was asked for the opacity map and, for an opaque entry, was asked for base colour only (today's behaviour).
  - `opaque_entry_is_unchanged`: an opaque household entry gives a material whose `alphaTest`, `transparent`, `opacity`, `side`, `depthWrite`, `alphaMap` equal those from the baseline module (`git show 49d96582:chauffeur/static/twin/twin_library.js`, loaded as in `test_twin_bake_fixtures_js.py`), and `materialKey` strings are equal.
  - `lattice_keeps_its_look`: kit role `lattice` gives the same `alphaTest`, `side`, and `alphaMap.image` dimensions as the baseline module and `userData.alphaMode === 'cutout'`.
  - `copy_carries_mode_between_instances`: `copyMaterialParams` from a blend material to an opaque one sets `transparent`, `opacity`, `depthWrite`; onto a viewing clone it leaves `transparent === true` and updates the stored source values.
  - `builtin_looks_equal_todays_materials`: `builtinMaterial('glass')`, `('screen')`, `('water')` equal, property by property (`color`, `opacity`, `transparent`, `roughness`, `depthWrite`, `side`, `name`), the objects the baseline `buildBuilding`/`buildYard` put on a pane, a porch screen and pool water.
  - `slot_naming_a_builtin_resolves`: `materialSlot({id:'glass'}, 'glass', …)` returns a material equal to `builtinMaterial('glass')`; with `color` it is tinted.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_alpha_render_js.py`. Expected: FAIL (`alphaModeOf is not a function`).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** the new file plus the five neighbours named above. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task A3: Live refresh and bake staleness

**Files:**
- Modify: `static/twin/twin_view.js` (`refreshMaterials` :307-358, rebuild test :314), `static/twin/bake/runtime.js` (`materialsChanged` :498-518) only if a test below fails without it
- Test: `tests/test_twin_alpha_bake_js.py` (create); extend `tests/test_twin_material_live_js.py`; keep green `tests/test_twin_bake_atlas_js.py`, `tests/test_twin_bake_runtime_js.py`, `tests/test_twin_bake_fixtures_js.py`, `tests/test_twin_baker_js.py`

**Interfaces:**
- Consumes: `alphaModeOf`, `userData.alphaMode` (A2); `atlasMesh` (`bake/atlas.js:601-607`), `buildAtlas` (:749-824), `mountBake` (`bake/runtime.js:109`).
- Produces:
  - `refreshMaterials(ids)` requests a full rebuild when, for any live material of a changed id, `material.userData.alphaMode !== alphaModeOf(newEntry, material.userData.materialRef)`. This replaces the lattice-only test at :314. A change to `opacity` or `alpha_cutoff` alone applies in place through `applyMaterialParams`.
  - No change to `atlasMesh`: a cutout material is excluded by `alphaTest > 0`, a blend material by `transparent`. Because the mode is synchronous (A2), the mesh set is the same on every tier.
  - After the rebuild the view starts the bake runtime against the new atlas key; a stored bake under the old key is not mounted.

- [ ] **Step 1: Write the failing tests.**
  In `tests/test_twin_alpha_bake_js.py`:
  - `flipping_alpha_mode_changes_the_atlas_key_and_drops_the_stored_bake`: build a one-building plan whose siding slot names a household material; call `buildBuilding` and `buildAtlas` with the entry opaque, record `key1` and the `atlasMesh` count; rebuild with the same plan and the entry's mode `cutout`; assert `key2 !== key1` and the count dropped by the siding meshes. Then run `mountBake` with a fetch stub that serves a manifest and pages only at `api/house/bakes/${key1}`: assert no mesh in the second scene has a lightmap or shadowmask texture and the runtime reports the unbaked state. Repeat the flip with `blend`, and in the reverse direction.
  - `opacity_or_cutoff_change_keeps_the_key`: changing `opacity` 0.4 to 0.6 on a blend entry, or `alpha_cutoff` on a cutout entry, leaves `buildAtlas(...).key` equal.
  - `low_and_high_tiers_build_the_same_key_with_a_cutout_material`: same plan, tiers `low` and `high`, equal keys, with the opacity loader never resolving.
  In `tests/test_twin_material_live_js.py` (existing harness):
  - `alpha_mode_change_rebuilds`: `refreshMaterials([id])` after a manifest change opaque to blend calls the view's rebuild once and `applyMaterialParams` zero times for that id.
  - `opacity_change_applies_in_place`: after a manifest change of `opacity` only, rebuild is not called and the live material's `opacity` equals the new value.
  - `lattice_refresh_still_in_place`: a kit refresh that leaves lattice as lattice does not rebuild (today's behaviour).
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_alpha_bake_js.py` and `tests/test_twin_material_live_js.py`. Expected: FAIL on `alpha_mode_change_rebuilds`.
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** both files plus the four bake neighbours. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task A4: Library page controls and glTF import

**Files:**
- Modify: `static/twin/library_page/properties.js` (`slots` :3, `defaults` :5-6, `mountProperties` :25), `static/twin/library_page/preview.js` (`createPreview` :12), `static/twin/library_page/gltf_import.js` (`readGltfMaterials` :45, result :168-181), `static/twin/library_page/texture_slots.js` (suffix table :10, `slotForFilename` :22)
- Test: `tests/test_twin_alpha_library_page_js.py` (create); keep green `tests/test_twin_library_page_js.py`, `tests/test_twin_gltf_material_js.py`, `tests/test_twin_texture_slots_js.py`, `tests/test_twin_library_route.py`; extend `tests/test_twin_materials.py::test_gltf_import_creates_a_gltf_material_through_the_map_route`

**Interfaces:**
- Consumes: params and slot from A1; `applyMaterialParams` from A2.
- Produces:
  - `properties.js`: `slots` gains `opacity` (label "Opacity map"); a three-way mode choice bound to `alpha_mode`; an opacity slider (0..1, step 0.01) shown only for `blend`; a cutoff slider (0..1, step 0.01) shown only for `cutout`. All go through the existing `change` callback. Layout follows the sibling param rows in the same file.
  - `preview.js`: the preview material shows the mode through `applyMaterialParams`; a mode change replaces the preview material rather than patching it.
  - `gltf_import.js`: each result gains `params.alpha_mode` (`MASK` to `cutout`, `BLEND` to `blend`, absent or `OPAQUE` to `opaque`), `params.alpha_cutoff` (`alphaCutoff`, default 0.5, only for `MASK`), `params.opacity` (`baseColorFactor[3]`, only for `BLEND`). For `MASK` and `BLEND` the base colour texture is uploaded with its alpha so A1 splits it; for `OPAQUE` the mode is sent as `opaque` after the upload so ruling 2 does not turn it into a cutout.
  - `texture_slots.js`: file suffixes `opacity`, `alpha`, `mask` map to slot `opacity`.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_alpha_library_page_js.py` (node with the DOM prelude):
  - `mode_choice_shows_the_right_slider`: mounting with `alpha_mode: 'opaque'` shows neither slider; choosing blend calls `change({alpha_mode:'blend'})` and, after remount with the new entry, shows the opacity slider only; cutout shows the cutoff slider only.
  - `sliders_send_clamped_numbers`: moving the opacity slider to 0.35 calls `change({opacity: 0.35})`; cutoff likewise.
  - `opacity_slot_uploads_and_clears`: the opacity map slot calls `replaceMap('opacity', file)` and `clearMap('opacity')`.
  - `read_only_builtin_shows_no_controls`: a built-in entry renders the mode as text and no inputs.
  - `gltf_mask_blend_opaque_map_to_modes`: three in-memory glTF documents give `cutout` with `alpha_cutoff` 0.3, `blend` with `opacity` 0.5, and `opaque`.
  - `filename_suffixes_route_to_opacity`: `leaf_opacity.png`, `leaf_alpha.png`, `leaf_mask.png` give `opacity`; existing suffix cases are unchanged.
  - `preview_material_follows_mode`: with a stub renderer, `createPreview` given a blend entry has a material with `transparent === true`; switching to opaque replaces it with one where `transparent === false`.
  Extend the TestClient glTF test: an import of a `MASK` material ends with a record whose `alpha_mode == 'cutout'` and an `opacity` map; an `OPAQUE` material with an RGBA base colour ends `opaque`.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_alpha_library_page_js.py`. Expected: FAIL (no mode control found).
- [ ] **Step 3: Implement** the Produces block. If a template class changes, run `python tools/build_tailwind.py`.
- [ ] **Step 4: Run** the new file plus the neighbours named above. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested. Add scenario L1 to `tests/test_twin_glass_slots_live.py` (see the Chromium list); do not run it.

---

## Slice B: House defaults

### Task B1: The two surface-kinds tables

**Files:**
- Create: `services/twin_surface_kinds.py`
- Modify: `static/twin/surface_kinds.js` (add the table), `services/twin_library.py` (`material_slot_error` :45-61, `material_choices` :36), `services/twin_materials.py` (`builtin_rows` :79-88, `_surface_kind` :470-474, `_labels` :437-467), `services/twin_plan.py` (building `materials` cleaning)
- Test: `tests/test_twin_surface_kinds.py` (create); update `tests/test_twin_materials.py::test_catalogue_lists_twelve_builtins_first_read_only` to fifteen and rename it `test_catalogue_lists_fifteen_builtins_first_read_only`; keep green `tests/test_twin_library.py`, `tests/test_twin_plan.py`, `tests/test_twin_materials.py`

**Interfaces:**
- Produces, server (`twin_surface_kinds.py`):
  - `KINDS: list[dict]`, one row per kind in this order, each `{'kind', 'label', 'scope': 'building'|'site', 'fallback': {'role': str} | {'builtin': str} | {'look': str}, 'item': None|'opening'|'porch'|'stair'|'fixture'|'room'|'roof'|'pool'|'spa'}`:

    | kind | fallback | item |
    |---|---|---|
    | `trim` | role `trim` | none |
    | `fascia` | role `trim` | none |
    | `casing` | role `trim` | opening |
    | `window_frame` | role `window_frame` | opening |
    | `pane` | builtin `glass` | opening |
    | `door` | role `door` | opening |
    | `column` | role `trim` | porch |
    | `screen` | builtin `screen` | porch |
    | `soffit` | role `porch_ceiling` | none |
    | `base` | role `base` | none |
    | `stair_tread` | role `floor` | stair |
    | `stair_rail` | role `porch_ceiling` | stair |
    | `ceiling` | look `ceiling` | room |
    | `roof` | role `roof` | roof |
    | `cabinet` | look `cabinet` | fixture |
    | `counter` | look `counter` | fixture |
    | `shower_tile` | look `ceramic` | fixture |
    | `shower_glass` | builtin `glass` | fixture |
    | `lawn` | role `lawn` | none (scope site) |
    | `water` | builtin `water` | pool, spa (scope site) |

    Rows whose kind already is a kit role (`trim`, `window_frame`, `door`, `base`, `roof`, `lawn`) keep storing under that role name, so existing plans need no migration. The panel also lists `siding`, `interior_wall`, `floor` as `PANEL_ROLES` (existing roles, not new kinds).
  - `BUILTIN_LOOKS: dict` with the same three ids and values as the browser side.
  - `ITEM_PARTS: dict[str, tuple[str, ...]]`: `{'opening': ('casing','window_frame','pane','door'), 'porch': ('column','screen'), 'stair': ('stair_tread','stair_rail'), 'fixture': ('cabinet','counter','shower_tile','shower_glass'), 'pool': ('water',), 'spa': ('water',)}`.
  - `label(kind) -> str`; `clean_slots(materials, allowed, notes, owner) -> dict` dropping keys outside `allowed` only when `allowed` is given, and resetting any value that fails `normalize_material_slot`, appending one note per reset.
- Produces, browser (`surface_kinds.js`): `KINDS`, `PANEL_ROLES`, `ITEM_PARTS` with the same content, and `kindRow(kind)`.
- `material_slot_error` accepts an id in `BUILTIN_LOOKS`. `material_choices` and the catalogue list the three as read-only built-ins after the kit's twelve.
- `_surface_kind` and `_labels` take their part labels from `twin_surface_kinds.label`, so a material used as a house `pane` default reads "House panes" style labels (exact strings fixed in the test).
- `twin_plan` runs `clean_slots` over each building's `materials` (no `allowed` filter: `set_material {building, role}` accepts any role today and that stays).

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_surface_kinds.py`:
  - `browser_table_equals_server_table`: a node run imports `surface_kinds.js` and prints `JSON.stringify({KINDS, PANEL_ROLES, ITEM_PARTS, BUILTIN_LOOKS})`; the parsed value equals the Python module's values (tuples compared as lists; `doubleSide` compared as a boolean).
  - `every_role_fallback_is_a_kit_role`: each `fallback.role` is a key of `kit('modern_farmhouse')['materials']`.
  - `builtin_ids_validate_as_slots`: `normalize_material_slot({'id': 'glass'})` returns the slot; `{'id': 'nope'}` raises.
  - `catalogue_lists_three_code_builtins_read_only`: the catalogue has fifteen built-ins; `glass`, `screen`, `water` are read-only and refuse PATCH and DELETE through TestClient with the same status as a kit built-in.
  - `load_resets_an_unknown_house_default`: a model whose building `materials.pane` names a missing id loads with that key removed and one note; a valid one survives.
  - `delete_refusal_names_new_surfaces`: with a household material set as house `pane` and `column` defaults, DELETE returns the refusal whose labels include the pane and column labels from the table, with counts.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_surface_kinds.py`. Expected: FAIL (`ModuleNotFoundError: services.twin_surface_kinds`).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** the new file plus `tests/test_twin_materials.py`, `tests/test_twin_library.py`, `tests/test_twin_plan.py`. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task B2: Generator lookups, reuse key, and the untouched-house test

**Files:**
- Modify: `static/twin/twin_generator.js` (`buildingKeyParts` :295-354, `plain`/`glass`/`screen` :458-464, `mat` :474-481, openings :762-817, roof trim :1025 and neighbours, porches :1263/:1298/:1309, stairs :1313-1317, fixtures :1342-1346), `static/twin/twin_stairs.js` (part roles :12, :25, :33, :35), `static/twin/surface_kinds.js` (`resolveSlot`)
- Test: `tests/test_twin_untouched_house_js.py` (create), `tests/test_twin_house_defaults_js.py` (create); keep green `tests/test_twin_building_reuse_js.py`, `tests/test_twin_uv_offset_js.py`, `tests/test_twin_stairs_js.py`, `tests/test_twin_porches_js.py`, `tests/test_twin_roof_js.py`, `tests/test_twin_bake_atlas_js.py`

**Interfaces:**
- Consumes: `KINDS`, `builtinMaterial`, `materialSlot` (A2, B1).
- Produces:
  - `resolveSlot(kind, { item, building, level }) -> slot | null` in `surface_kinds.js`: `item?.materials?.[kind]`, else `level?.materials?.[kind]`, else `building?.materials?.[kind]`, else `null`. (Item reading lands in C2; the parameter exists now.)
  - In `buildBuilding`, one closure `kindMat(kind, item) -> THREE.Material`: when `resolveSlot` returns `null`, return exactly what the call site returns today (`mat(fallbackRole)`, the shared `glass`/`screen` object, or the fixture's `plain(...)`); otherwise `materialSlot(slot, name, kit, tier, cache, roleMaterial)` where `name` is the fallback role for role kinds, and for `pane`/`shower_glass` is `'glass'` when the resolved material's `userData.alphaMode !== 'opaque'` and `'pane'` otherwise (ruling 3); for `screen` it is `'screen'`.
  - Call-site mapping: frames to `window_frame`; casing (:802, :805) to `casing`; door leaves (:808, :811) to `door`; half-glass lights (:809) and glazing (:815), including garage openings, to `pane`; fascia and rake (:1025 and its neighbours that use `mat('trim')` on the roof edge) to `fascia`; porch columns (:1263) to `column`; porch screens (:1298) to `screen`; porch ceiling (:1309) and roof underside (:1001) to `soffit`; stair treads and solid body to `stair_tread`; stringers, posts, handrail to `stair_rail`; cabinet body (:1342) to `cabinet`; counter top (:1343) to `counter`; shower tile (:1345) to `shower_tile`; shower glass (:1346) to `shower_glass`. Fixture order follows ruling 8.
  - `twin_stairs.js` parts carry `kind: 'stair_tread' | 'stair_rail'` beside the existing `role`, which stays.
  - `buildingKeyParts` adds the resolved slots of the new kinds to `finishes` only for kinds whose slot is non-null, appended after today's entries, so the output for a building with none set is byte-identical to `49d96582`.
  - A cache keyed by slot keeps one material instance per distinct slot and name, so a house default adds at most one material per kind.

- [ ] **Step 1: Write the failing tests.**
  `tests/test_twin_untouched_house_js.py` — the baseline harness. It loads two module graphs in one node run: the working tree's, and main's, read with `git show 49d96582:chauffeur/static/twin/<file>` for every twin module the generator, yard, library and atlas import, rewritten to `data:` URLs exactly as `tests/test_twin_bake_fixtures_js.py::legacy_key_pages_and_shader_equal_main` does. The fixture plan is a full house built in the test: two levels, a gable and a hip roof, windows, a slider, a bifold, a garage opening, a half-glass door, a screened porch with columns, a stair with `rail: 'both'`, a kitchen run with `body` and `top` colours, a shower, an upper slab, a lawn, a pool with a spa, a fence and a patio. It sets none of the new fields.
  - `untouched_house_equals_main`: for both graphs call `buildBuilding` for each building, then collect per mesh in traversal order `[material.name, material.userData.materialKey ?? null, material.userData.alphaMode-free flags (transparent, alphaTest, opacity, side, depthWrite), geometry.attributes.position.count, sha1 of uv array, sha1 of position array]`. Assert the two lists are deep-equal, the mesh counts are equal, the count of distinct `material.uuid` values is equal, `JSON.stringify(buildingKeyParts(...))` is equal, and `buildAtlas(...).key` and atlas version are equal.
  - `house_with_alpha_free_library_materials_equals_main`: the same plan with a household opaque material on siding and on a floor; same assertions (covers A2's `materialKey` promise inside the reuse key).
  `tests/test_twin_house_defaults_js.py`:
  - `each_building_kind_default_reaches_its_meshes`: for every building-scope kind in `KINDS` except `ceiling` and `roof`, set `building.materials[kind] = {id: <household id>}` alone and assert the meshes at that kind's call sites have `userData.materialId` equal to the id, and that the count of meshes with that id equals the count of meshes that carried the fallback at those sites in the unset build.
  - `fallback_role_still_drives_unset_kinds`: with `building.materials.porch_ceiling` set and no `soffit` or `stair_rail`, soffit, stringers and handrail carry the `porch_ceiling` material; with `trim` set and no `fascia`/`casing`/`column`, those follow `trim`; with `floor` set, treads follow `floor`.
  - `opaque_pane_is_named_pane_and_joins_the_atlas`: a house `pane` default naming an opaque material gives pane meshes named `pane` for which `atlasMesh` is true after merging, and the atlas key differs from the unset build; naming a blend material gives name `glass` and `atlasMesh` false.
  - `garage_opening_takes_pane_and_frame`: a garage opening's glazing follows the `pane` default.
  - `fixture_colour_beats_house_default`: an item with `body: '#112233'` keeps that colour when a house `cabinet` default is set; an item with no `body` takes the house default.
  - `a_default_changes_the_reuse_key_only_for_its_building`: setting `pane` on building A changes A's `buildingKeyParts` and leaves B's equal.
  - `one_material_instance_per_default`: with a `pane` default, all pane meshes of a building share one `material.uuid`; mesh count after merging equals the unset build's.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_untouched_house_js.py` (expected: PASS before any change; it is the guard, run it first to prove the harness) and `tests/test_twin_house_defaults_js.py` (expected: FAIL, pane meshes carry no `materialId`).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** both files plus the six neighbours named above. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task B3: Yard defaults for lawn and water

**Files:**
- Modify: `static/twin/twin_yard.js` (`yardMaterialInputs` :112-155, `buildYard` lawn :314-320, `water` :395-397), `static/twin/pool_features.js` (`buildPoolFeatures` :102, spa water :149/:153), `services/twin_model_ops.py` (`_material` :856-884 and its dispatch :1147)
- Test: `tests/test_twin_yard_defaults_js.py` (create); extend `tests/test_twin_untouched_house_js.py`; add cases to `tests/test_twin_model_ops_more.py`; keep green `tests/test_twin_yard_material_slots.py`, `tests/test_twin_pool_features_js.py`, `tests/test_twin_site_shapes_js.py`

**Interfaces:**
- Produces:
  - `set_material` target `{site: true, role}` where `role` is a site-scope kind (`lawn`, `water`): writes or clears top-level `materials[role]`. Any other role with `site` is refused with `Choose a surface for the material.` (ruling 9).
  - `buildYard`: `water` is today's shared `plain('water', …)` object when `plan.materials.water` is unset; otherwise `materialSlot(plan.materials.water, 'water', …)`. The water kind does not go through `yardMaterialKit` (:103-109), which would treat it as a kit role. Lawn keeps its present path (`plan.materials.lawn` already drives it); the `terrain_lawn` variant keeps `vertexColors` and `DoubleSide`.
  - `yardMaterialInputs` pushes the water slot into `slots` only when it is set.

- [ ] **Step 1: Write the failing tests.**
  `tests/test_twin_yard_defaults_js.py`:
  - `water_default_reaches_pool_and_spa`: with `plan.materials.water = {id: <household blend id>}` the pool water mesh and the spa water mesh carry that `materialId` and name `water`.
  - `builtin_water_slot_equals_todays_water`: `plan.materials.water = {id: 'water'}` gives a water material equal property by property to the unset build's.
  - `water_default_changes_the_yard_key`: `yardMaterialKey` differs between unset and set, and is equal between two builds with the same slot.
  - `lawn_default_still_works_on_flat_and_graded_lots`: a `lawn` slot reaches both the flat lawn and the `terrain_lawn` mesh, which keeps `vertexColors === true`.
  Extend `tests/test_twin_untouched_house_js.py::untouched_house_equals_main` to call `buildYard` in both graphs and compare the same per-mesh list, `yardMaterialKey`, and `yardPartKeys`.
  `tests/test_twin_model_ops_more.py`:
  - `test_site_material_target_sets_and_clears_water`: the op stores `materials.water`, `material: None` removes it, role `siding` with `site` is refused, an unknown id is refused.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_yard_defaults_js.py`. Expected: FAIL (water mesh has no `materialId`).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** the new file, the untouched-house file, `tests/test_twin_model_ops_more.py`, and the three neighbours. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task B4: Roof section material and the room ceiling surface

**Files:**
- Modify: `static/twin/twin_generator.js` (roof :967, :1002; floors :1197-1220; `buildingKeyParts`), `static/twin/editor/library.js` (`materialLines` :56, `surfaceAt` :222, `ceilingAt` :232-246)
- Test: `tests/test_twin_ceiling_roof_slots_js.py` (create); keep green `tests/test_twin_roof_js.py`, `tests/test_twin_model_roofs.py`, `tests/test_twin_model_bridge.py`, `tests/test_twin_editor_library_js.py`, `tests/test_twin_untouched_house_js.py`

**Interfaces:**
- Consumes: flat `roof.sections[].material` and `.roof` (already produced by `services/twin_model_roofs.py:99-129`); `rooms[].ceiling_material` (already written by `set_material {room, surface: 'ceiling'}`).
- Produces:
  - Roof: each section's top surface uses `materialSlot(section.material, 'roof', …)` when `section.material` is set, else `kindMat('roof')`. All sections of one model roof share one instance (ruling 5).
  - Ceiling: for a room with `ceiling_material` set, or any room when the house `ceiling` default is set, add one surface with the room's polygon, 0.02 ft below the underside it sits under (upper slab :1218, or roof underside :1001 for a top-level room), facing down, named `ceiling`, tagged `userData.pieceId = room.id`, `userData.kind = 'room'`, `userData.part = 'ceiling'`, and placed in the same group and under the same visibility rule as that underside so it hides when the underside hides (ruling 4). No room gets a ceiling surface when neither is set.
  - `buildingKeyParts`: `rooms[].ceiling_material` and `roof.sections[].material` already sit in the building's authored data; confirm by test that changing either changes the key, and add them to `finishes` if the test shows they do not.
  - `editor/library.js`: the Ceiling line and `surfaceAt`/`ceilingAt` use role `ceiling` with inherited label "House look" in place of `porch_ceiling`.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_ceiling_roof_slots_js.py`:
  - `roof_section_material_is_drawn`: a model with two roofs, one with `material`, flattened through the bridge output shape (`sections[].material`, `.roof`), gives roof-top meshes with that `materialId` for the first roof's sections only; a split roof (`id~1`, `id~2`) shares one `material.uuid`.
  - `roof_material_changes_the_key_and_clears_back`: setting it changes `buildingKeyParts`; removing it restores the original string.
  - `no_ceiling_surface_when_unset`: mesh count and names equal the unset build (covered also by the untouched-house test).
  - `room_ceiling_material_adds_one_surface_under_the_slab`: one new mesh named `ceiling` whose bounding box matches the room polygon in plan and whose y is 0.02 ft below the slab underside; its normal points down; its `userData.pieceId` is the room id.
  - `ceiling_hides_with_its_underside`: after the view-volume or level-hide call that hides the slab underside in the existing harness, the ceiling surface's `visible` (or its group's) is false.
  - `house_ceiling_default_covers_every_room`: with `building.materials.ceiling` set, each room has one ceiling surface; a room override wins for that room.
  - `ceiling_line_uses_role_ceiling`: `materialLines` for a room returns a Ceiling line with role `ceiling` and target `{room, surface:'ceiling'}`.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_ceiling_roof_slots_js.py`. Expected: FAIL (roof meshes carry the kit roof material).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** the new file plus the five neighbours. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task B5: House materials panel

**Files:**
- Create: `static/twin/editor/house_materials.js`
- Modify: `static/twin/editor/cards.js` (building card, beside `foundationShelf` :212), the editor template only if a host element is needed
- Test: `tests/test_twin_house_materials_panel_js.py` (create); keep green `tests/test_twin_material_slot_js.py`, `tests/test_twin_editor_library_js.py`, `tests/test_twin_foundation_material_js.py`

**Interfaces:**
- Consumes: `KINDS`, `PANEL_ROLES` (B1); `materialSlot({ label, value, defaultLabel, defaultColor, quickPicks, kit, onChange, readOnly, report, loadMaterials })` from `editor/material_slot.js`; `set_material` targets `{building, role}` and `{site: true, role}`.
- Produces: `houseMaterialsShelf(host, building, { getPlan, getKit, canEdit, op, report })` — the same option shape as `foundationShelf` (`editor/foundation_shelf.js:4`). It renders one `materialSlot` per row of `PANEL_ROLES` then `KINDS`, grouped under the headings Walls and floors, Trim, Openings, Porch and stairs, Roof and ceilings, Fixtures, Yard. `onChange(slot)` sends `{op: 'set_material', building: building.id, target: {building: building.id, role: kind}, material: slot}` for building kinds and target `{site: true, role: kind}` for site kinds. `defaultLabel` names the fallback ("Follows Trim", "Built-in glass", "House look"). `readOnly` is `!canEdit`.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_house_materials_panel_js.py` (node with the DOM prelude):
  - `panel_lists_every_kind_once`: the host holds one `[data-material-slot]` per `PANEL_ROLES` and `KINDS` entry, labels equal to the table labels.
  - `choosing_a_material_sends_set_material`: clicking a material in the Panes slot calls `op` with target `{building, role: 'pane'}` and `material: {id}`; "Use default" sends `material: null`.
  - `site_kinds_use_the_site_target`: Water and Lawn send `{site: true, role}`.
  - `tint_is_sent_with_the_slot`: an override tint sends `{id, color}`.
  - `read_only_shows_no_buttons`: with `canEdit: false` no Change or Use default button exists.
  - `current_values_are_shown`: a building with `materials.pane` set shows that material's name from `materialName(id)`.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_house_materials_panel_js.py`. Expected: FAIL (module not found).
- [ ] **Step 3: Implement** the Produces block, citing the sibling precedent for each styling choice in the hand-off note. Run `python tools/build_tailwind.py` if a class is new.
- [ ] **Step 4: Run** the new file plus the three neighbours. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested. Add scenarios L2 and L3 to `tests/test_twin_glass_slots_live.py`; do not run them.

---

## Slice C: Per-item overrides

### Task C1: Server targets, validation, where-used

**Files:**
- Modify: `services/twin_model_ops.py` (`_material` :856-884), `services/twin_plan.py` (`_details` :448-510, building pieces), `services/twin_site_shapes.py` (`SLOTS` :12-14), `services/twin_materials.py` (`_labels` :437-467)
- Test: `tests/test_twin_item_slots.py` (create); keep green `tests/test_twin_model_ops_more.py`, `tests/test_twin_plan.py`, `tests/test_twin_model_bridge.py`, `tests/test_twin_site_shapes.py`, `tests/test_twin_pool_features.py`, `tests/test_twin_yard_material_slots.py`, `tests/test_twin_materials.py`

**Interfaces:**
- Consumes: `ITEM_PARTS`, `clean_slots`, `label` (B1).
- Produces:
  - Plan paths, all `materials: {<kind>: slot}` on the item: `openings[].materials` (`casing`, `window_frame`, `pane`, `door`), `porches_detail[].materials` (`column`, `screen`), `stairs[].materials` (`stair_tread`, `stair_rail`), `items[].materials` for items with `rect` (`cabinet`, `counter`, `shower_tile`, `shower_glass`), `site.pool.materials.water`, spa feature `materials.water`.
  - `set_material` targets: `{opening: id, part}`, `{porch: id, part}`, `{stair: id, part}`, `{item: id, part}`. Each finds the piece with the existing `_find`, refuses a `part` outside `ITEM_PARTS[<type>]` with `Choose a surface for the material.`, and writes or clears `piece['materials'][part]`; an emptied `materials` dict is removed so a cleared item returns to the shape it had before.
  - `twin_site_shapes.SLOTS`: `pool` and `spa` gain `water`; pool and spa water are written through the existing site-shape and pool-feature operations.
  - `twin_plan` runs `clean_slots(piece.get('materials'), ITEM_PARTS[type], notes, owner)` on openings, porch details, stairs and rect items; the bridge already carries the key through (`twin_model_bridge.py:962-988` deep-copies pieces).
  - `_labels` names an item slot by the item's name or kind and the table label (for example "Front door pane").

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_item_slots.py`:
  - `set_material_writes_each_item_target`: for each of the four targets and each allowed part, the op stores the slot at the plan path above; `material: None` removes it and leaves no empty `materials` key.
  - `wrong_part_or_unknown_item_is_refused`: `{opening, part: 'cabinet'}`, `{stair, part: 'pane'}`, and an unknown id are each refused with a message and change nothing.
  - `unknown_material_id_is_refused`: a slot naming a missing id is refused by every new target.
  - `builtin_id_is_accepted`: `{opening, part: 'pane'}` with `{id: 'glass', color: '#88aacc'}` is stored.
  - `flatten_carries_item_materials`: after `flatten`, the flat `fixtures[]`, `porches[]`, `openings[]` and `stairs[]` entries hold the same `materials`.
  - `load_resets_unknown_ids_in_every_new_slot`: a stored model with a missing id in one slot of each of the six places loads with exactly those keys removed, valid neighbours kept, and one note each.
  - `pool_and_spa_water_slot_validate`: the site-shape op accepts `materials.water` on the pool and on a spa feature and refuses an unknown id.
  - `delete_refusal_names_new_surfaces`: DELETE of a material used in an opening pane, a stair rail, a cabinet and pool water returns labels naming each, grouped with counts; history-only use still reports history.
  - `existing_targets_unchanged`: wall face, room surface, roof, `{building, role}` and `{level, role}` behave as before (one assertion each).
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_item_slots.py`. Expected: FAIL (`Choose a surface for the material.` on the opening target).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** the new file plus the seven neighbours. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task C2: Generator and yard read item slots

**Files:**
- Modify: `static/twin/twin_generator.js` (pass the item into `kindMat` at each call site; `buildingKeyParts`; pick tagging), `static/twin/twin_yard.js` (`yardMaterialInputs`, pool water), `static/twin/pool_features.js` (spa water), `static/twin/bake/geometry_key.js` only if the key test below fails
- Test: `tests/test_twin_item_slots_js.py` (create); extend `tests/test_twin_untouched_house_js.py`; keep green `tests/test_twin_house_defaults_js.py`, `tests/test_twin_building_reuse_js.py`, `tests/test_twin_pool_features_js.py`, `tests/test_twin_bake_fingerprint_js.py`

**Interfaces:**
- Consumes: `resolveSlot(kind, { item, building, level })` (B2).
- Produces:
  - Every `kindMat(kind, item)` call site passes its opening, porch detail, stair or fixture. Order: item slot, (fixture colour, ruling 8), house default, fallback.
  - Pool water: `site.pool.materials?.water`, else `plan.materials?.water`, else today's object. Spa water: `feature.materials?.water`, else the pool's resolved water.
  - `buildPoolFeatures(group, pool, height, { mat, plain, water, copingRole, spaWater })` where `spaWater(feature) -> THREE.Material` defaults to `() => water`.
  - Meshes that are not merged pick targets already carry `userData.pieceId`/`kind`; every pick object for an opening, porch part, stair part and fixture part also carries `userData.part = <kind>` so the editor can tell a pane from a frame (C4). Tagging adds no mesh.
  - `buildingKeyParts` includes item `materials` (they sit inside the pieces already keyed; confirm by test). `yardMaterialInputs` pushes pool and spa water slots when set.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_item_slots_js.py`:
  - `item_slot_beats_house_default_beats_fallback`: for one representative of each item type (opening `pane`, porch `screen`, stair `stair_rail`, fixture `counter`), build three ways and assert the `materialId` on that item's meshes is the item's, then the house default's, then absent with the fallback name.
  - `only_the_named_item_changes`: with two windows and a slot on one, the other window's pane material is the shared default object (same `uuid` as the unset build's panes).
  - `two_items_with_the_same_slot_share_one_material`: equal slots on two openings give one `material.uuid`.
  - `spa_water_follows_pool_then_house`: spa slot, pool slot, house default, each in turn.
  - `item_slot_changes_reuse_and_atlas_keys`: an opening `pane` slot naming an opaque material changes `buildingKeyParts` and `buildAtlas(...).key`; a slot naming built-in `glass` with no colour leaves the pane's material equal to today's but still changes the reuse key (the plan differs).
  - `part_tags_are_present`: the pick objects for a window expose parts `pane`, `window_frame`, `casing`; a door `door` (and `pane` when half-glass); a porch `column`, `screen`; a stair `stair_tread`, `stair_rail`; a kitchen run `cabinet`, `counter`; a shower `shower_tile`, `shower_glass`.
  - `mesh_count_unchanged_by_tags`: the unset build's mesh count equals the count before this task (asserted against the baseline graph in the untouched-house file).
  Extend `untouched_house_equals_main` to assert no baseline-vs-tree difference after this task (it compares names, keys, UVs and counts; `userData.part` is new and not compared).
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_item_slots_js.py`. Expected: FAIL (item slot ignored).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** the new file, the untouched-house file, and the four neighbours. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task C3: Selection-card rows

**Files:**
- Modify: `static/twin/editor/library.js` (`materialLines` :29-60, `surfaceOperation` :71-84), `static/twin/editor/cards.js` (material rows :160-178), `static/twin/editor/site_shape_shelf.js` (`siteMaterialSlots` :13)
- Test: `tests/test_twin_item_slot_rows_js.py` (create); keep green `tests/test_twin_editor_library_js.py`, `tests/test_twin_stair_editor_js.py`, `tests/test_twin_pool_features_editor_js.py`, `tests/test_twin_site_shapes_js.py`

**Interfaces:**
- Consumes: `ITEM_PARTS`, `kindRow` (B1); targets from C1.
- Produces:
  - `materialLines(record, plan, kit)` returns lines for kinds `opening` (parts by opening type: a window gets `window_frame`, `casing`, `pane`; a door gets `door`, `casing`, `window_frame`, and `pane` only when its model has a light; a garage opening gets `pane`, `window_frame`, `casing`), porch room (`column`, and `screen` only when `screened`), `stair` (`stair_tread`, `stair_rail` only when `rail !== 'none'` or `style === 'open'`), and rect item (kitchen kinds get `cabinet`, `counter`; a shower gets `shower_tile`, `shower_glass`). Each line is `line(label, kind, override, target, …)` with target `{opening|porch|stair|item: id, part: kind}` and an inherited label from the house default or the fallback.
  - `surfaceOperation` passes these targets through unchanged; item lines offer no scope chooser (the scope is the item).
  - The existing row markup (`editor-material-line`, Change, Clear, reset) at `cards.js:160-178` draws them; no new markup.
  - `siteMaterialSlots('pool', piece)` and the spa feature card list `water`.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_item_slot_rows_js.py`:
  - `lines_per_item_type`: the line labels and targets for a window, a half-glass door, a solid door, a garage opening, a screened and an unscreened porch room, a solid stair with no rail, an open stair with both rails, a kitchen run and a shower equal the lists above.
  - `inherited_label_names_the_source`: with a house `pane` default the window's Pane line reads that material's name as inherited; without it, "Built-in glass".
  - `change_and_clear_send_the_item_target`: through the card, Change then picking a material calls `op` with `{op:'set_material', target:{opening: id, part:'pane'}, material:{id}}`; Clear sends `material: null`.
  - `room_and_roof_lines_still_listed`: a room still lists Floor, Ceiling, Walls and a roof its Roof line.
  - `pool_and_spa_cards_list_water`: the pool shelf and the spa feature card each show a Water slot whose change sends the site-shape operation with `materials: {water: slot}`.
  - `read_only_card_has_no_buttons`.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_item_slot_rows_js.py`. Expected: FAIL (`materialLines` returns `[]` for an opening).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** the new file plus the four neighbours. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested.

### Task C4: Drag and drop onto the new surfaces

**Files:**
- Modify: `static/twin/editor/library.js` (`surfaceAt` :197-229, redirect :201-207, drop handler :410-421), `static/twin/twin_view.js` (`pick` :429-474 returns `part`)
- Test: `tests/test_twin_item_slot_drop_js.py` (create); keep green `tests/test_twin_editor_library_js.py`

**Interfaces:**
- Consumes: `userData.part` tags (C2, B4); item lines (C3).
- Produces:
  - `view.pick(clientX, clientY, { skip })` result gains `part` (the hit object's `userData.part`, or `undefined`).
  - `surfaceAt(event, options)`: when the hit has a `part` and its kind is opening, porch part, stair or item, return `{ kind, role: part, target: {opening|porch|stair|item: pieceId, part}, label }` and do not redirect. A hit on an opening, anchor, light or item without a `part` redirects to the host wall, room or roof exactly as today. A hit with `part === 'ceiling'` returns the room ceiling surface.
  - A drop on such a surface applies to the item directly, with no scope chooser; the report line names the item and part. Pool and spa water drops send the site-shape operation.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_item_slot_drop_js.py` (node, `view.pick` stubbed to return a hit):
  - `drop_on_a_pane_targets_the_opening`: a hit `{kind:'opening', pieceId:'w1', part:'pane'}` gives target `{opening:'w1', part:'pane'}` and the drop calls `op` with it.
  - `drop_on_a_frame_targets_the_frame`: `part: 'window_frame'` gives that part.
  - `drop_on_an_untagged_opening_still_goes_to_the_wall`: no `part` gives the host wall face as before.
  - `drop_on_a_light_or_anchor_still_redirects`.
  - `drop_on_stair_column_cabinet_and_ceiling`: one assertion each for `stair_rail`, `column`, `counter`, `ceiling`.
  - `drop_on_pool_water_sends_the_site_shape_op`.
  - `no_scope_chooser_for_item_drops`: `choose` is not called.
  - `read_only_editor_ignores_item_drops`.
- [ ] **Step 2: Run** `env -u HA_BASE_URL python tests/test_twin_item_slot_drop_js.py`. Expected: FAIL (target is the host wall).
- [ ] **Step 3: Implement** the Produces block.
- [ ] **Step 4: Run** the new file plus `tests/test_twin_editor_library_js.py`. Expected: PASS.
- [ ] **Step 5:** Leave changes in the working tree and write a short note of what changed and what was tested. Add scenarios L4 and L5 to `tests/test_twin_glass_slots_live.py`; do not run them.

---

## Slice D: Garage door that follows its device (added 2026-11-15, tasks to be written before the slice starts)

User requirement: "the garage door ... is always open currently. It would be nice to have it linked to a device/entity and have it open/close to match." This replaces the spec's non-goal "no new geometry for panelled garage doors".

Decided so far (Claude's calls unless marked):

- A `garage` opening draws a sectional door panel filling the opening, with horizontal section lines, in place of the glazed pane. New surface kind `garage_door` (house default plus per-opening override, opaque built-in colour by default). The `pane` slot no longer applies to a garage opening.
- The link is the existing device placement: a garage cover device already attaches to a garage opening (`services/twin_ha.py:313-319`). No new link store, no new stream; state comes from the states the twin already receives.
- State to drawing: `closed` or no linked device or state unknown/unavailable draws the door closed. `open` draws it raised (panel gone from the opening, a short strip left under the head). `current_position` when present sets the height in between. `opening`/`closing` animate toward the end state.
- The door panel takes no baked light and is not a bake occluder, so opening and closing never makes the stored bake stale and the bake key of a house with a garage opening does not change. Live shadows from the panel follow the tier's present rules.
- With no Home Assistant the door draws closed.
- Hand path: the opening's selection card shows the linked device and the existing place-a-device flow links or unlinks it.

User direction, 2026-11-15 (overrides the calls above where they differ):

- "The control to open close should just be the device marker in the room." No control on the door itself; the existing device marker stays the one control. "The firepit should probably follow that same design really": before writing slice D's tasks, read how the fire pit is switched today and bring it to the same design (device marker is the control, the drawn thing follows the entity state). Report what a person can do today with the fire pit before changing it; nothing a person can do is removed without the user's word.
- "There should be a way to get different door styles ... there are really only a few different styles so maybe we could model them and have a selector." So: a `style` choice on a garage opening, a small fixed set of modelled styles (call, to confirm with the user when the slice is planned: flat panel, raised panel, carriage, full-view glass), chosen from the opening's selection card. Colour and material still come from the `garage_door` slot; a style with windows uses the `pane` slot for its lites.
- "An animation to open/close would be cool but not necessary for the first slice." First slice snaps between states (and to `current_position`); animation is a later slice.

## Chromium scenarios, run by Claude

All in `tests/test_twin_glass_slots_live.py`, written by the implementer of the task named, run only by Claude (`env -u HA_BASE_URL python tests/test_twin_glass_slots_live.py`), dark theme, wall viewport, a realistic house fixture, a screenshot saved per scenario.

- **L1 (A4):** on the Library page, switch a material to blend, move opacity to 0.4, upload a leaf PNG with alpha to another material; the preview canvas shows see-through pixels (sampled centre pixel differs from the opaque render), the cutout material shows the mode as cutout with an opacity map thumbnail, and no page error is logged.
- **L2 (B5):** in the editor, open House materials, set Panes to a blend material; pane meshes in the live scene report that `materialId`; the draw-call count from `?perf=1` is no higher than before the change.
- **L3 (B2, A3):** load a house with a finished bake, flip its siding material from opaque to cutout on the Library page; the twin tab rebuilds, the bake badge reports unbaked, and no mesh holds a lightmap. Flip back: the stored bake mounts again.
- **L4 (C4):** drag a material from the Library strip onto a window pane; only that window changes; drag onto the same window's frame; only the frame changes; the wall is untouched.
- **L5 (C3):** select a stair, set Rail from the card, clear it, and confirm the rail returns to the house look.
- Also rerun after the last task: `tests/test_twin_view_live.py`, `tests/test_twin_editor_scene_live.py`, `tests/test_twin_shadowmask_live.py`, `tests/test_twin_site_shapes_live.py`.

## Decisions the spec left to the builder

- Table layout: `services/twin_surface_kinds.py` and `static/twin/surface_kinds.js`, parity by `browser_table_equals_server_table`.
- Per-item plan path: `materials: {<kind>: slot}` on the item, part names equal to kind names.
- House defaults: `building.materials[<kind>]` for building kinds, top-level `materials[<kind>]` for `lawn` and `water`.
- Control layout: one `materialSlot` per kind in a grouped shelf on the building card; item rows reuse the existing material-line markup.
- Ceiling surface: one down-facing polygon per room, 0.02 ft under the underside, drawn only when a ceiling material applies.
- Pane naming: `glass` when non-opaque, `pane` when opaque.

## Self-review

- **Spec coverage:** params, map slot, ingest split, glTF mapping (A1, A4); modes, low tier, lattice, built-ins (A2); live refresh and stale bake (A3); Library page (A4); kinds table and validation (B1); every table row drawn (B2, B3, B4); panel (B5); item paths, validation, reset on load, delete refusal (C1); resolution order and keys (C2); card rows (C3); drag and drop (C4). Agent: no schema change, covered by C1's op tests.
- **Review Focus:** each of the five lines names its test and task.
- **Types:** `kindMat`, `resolveSlot`, `alphaModeOf`, `builtinMaterial`, `ITEM_PARTS`, `clean_slots` and the four targets are spelled the same in every task that uses them.
- **Known gap stated, not hidden:** an opaque pane named `pane` loses the window glow by design (ruling 3); a split roof cannot take two materials (ruling 5).
