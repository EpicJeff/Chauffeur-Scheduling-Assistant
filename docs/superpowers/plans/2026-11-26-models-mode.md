# Library Models mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Models become as first-class as materials: imported, previewed, levelled, sized, turned and re-skinned per part on the Library page, with per-copy overrides in the editor, and the bake's shadow key following every change that alters a shadow.

**Architecture:** One shared pure module per side (`static/twin/model_parts.js`, `services/twin_model_parts.py`) defines part keys, override resolution, fix maths and the bake's occluder inputs; everything else consumes it. The server keeps one model record per model (imports in `.asset.json`, built-ins in their own small file). The client applies the fix and model defaults inside `loadModel` and per-copy overrides per placement, swapping materials and the `uv` attribute only, so programs stay shared.

**Tech Stack:** FastAPI, plain-script Python tests with TestClient, three.js ES modules, node-driven JS tests (`tests/test_*_js.py`), meshoptimizer worker, GLTFExporter.

**Spec:** `docs/superpowers/specs/2026-11-23-library-models-mode-design.md` (approved 2026-11-26). Executors read both.

## Global Constraints

- All paths below are under `chauffeur/` unless they start with `docs/`.
- Tests run from `chauffeur/` with `HA_BASE_URL` unset. Gates use `python tools/test.py <exact basenames with .py>`, which runs the named files in parallel. Never pass bare words, and never run the whole suite as a gate.
- Implementers do not commit and do not bump `config.yaml`. They leave changes in the worktree and write a report file. Claude commits and lands.
- No new sampler on any lit program, and no new program per copy or per override. A first use of a library material compiles once, as for walls.
- No browser dialogs: use `promptConfirm`, `promptInput` and `showGlobalAlert`.
- Every new route gets an explicit row in `services/auth.py`:
  - reads are `WALL_OR_SERVICE`, like model reads;
  - writes are `PARENTS`;
  - `/house/library` stays `ANYONE`.
- Run `python tools/build_tailwind.py` after any template class change.
- Works with no Home Assistant.
- Nothing a person can do today is removed: the editor keeps Import, canvas drop, Rename and Delete.
- Existing placements with no overrides, no fix and default percentages render exactly as today. The household fixture goldens do not change.
- Bake rules:
  - The occluder hash gains the fix, the mid-level identity and per-part shadow casting.
  - Colour, texture mode, `tiles`, and the full and far percentages stay out of every bake key.
  - `model_materials` stays out of the atlas key.
- **Plan-level call (Claude):** the per-copy override field is `model_materials` on EVERY placed copy (items, site furniture, site planting and openings). Fixture items and openings already use `materials` for finish kinds. The spec is amended to match in Task 1.
- **Plan-level call (Claude):** real-size box UVs are computed at load from positions (feet, after the fix), not stored in the level files. Every level gets the same projection by construction, and no custom glTF attribute is needed. This meets the spec's requirement that every level carries real-size UVs.

## Who does what

| Task | Owner | Worktree / branch |
|---|---|---|
| 1 Contract: shared module, data shapes, tests | Claude | `Chauffeur-models-design` / `models-design` |
| 2 Server: records, routes, validation, auth, in-use | Codex | `Chauffeur-models-server` / `models-server` |
| 3 Bake: occluder inputs, editor freshness parity | Codex | `Chauffeur-models-bake` / `models-bake-keys` |
| 4 Client pipeline: part keys, loadModel, levels, cars | Codex | `Chauffeur-models-pipeline` / `models-pipeline` |
| 5 Library page Models tab | Gemini | `Chauffeur-models-library` / `models-library` |
| 6 Editor: part rows, drop scopes, model-record undo | Codex | `Chauffeur-models-editor` / `models-editor` |
| 7 Browser proof, cost report, demo shot, landing | Claude | `Chauffeur-models-design` |

- Order: 1, then 2 and 3 in parallel, then 4, then 5 and 6 in parallel, then 7.
- Each of tasks 2 to 6 lands on main after its review and Claude's checks, so main stays shippable.
- Every task gets an independent review from a diff file, the brief and the report. Fix rounds go back to the implementer and end with a scoped re-review.

## Review Focus

1. **A missing override target:**
   - Situations: an override names an archived or deleted library material, or a part key the record no longer has (re-import, or an old file).
   - Expected: the part renders with its original material and the console logs once. It never renders blank and never throws.
   - Tests: Task 4, `stale_override_falls_back`; Task 2, `refuses_unknown_part`.
2. **Two quick percentage edits:**
   - Situation: a rebuild from the first edit finishes after the second edit.
   - Expected: only the upload matching the record's current `lod_percent` attaches, and the stale one is refused with 409.
   - Tests: Task 2, `stale_lod_upload_refused`; Task 5, `last_percent_wins`.
3. **Unnamed and duplicate material names** in one file:
   - Expected: the same part keys on the original and every generated level, and after a reload.
   - Tests: Task 1, `keys_for_duplicates_and_unnamed`; Task 4, `keys_survive_export_roundtrip`.
4. **Two tabs editing one model record:**
   - Situation: a write carries an old `revision`.
   - Expected: refused with 409 and the current record. The page reloads the record and says so with `showGlobalAlert`.
   - Tests: Task 2, `revision_conflict_409`; Task 5, `conflict_reloads`.
5. **Deleting a library material a model uses:**
   - Situation: the use is a model default or a copy's `model_materials`.
   - Expected: it follows the in-use rule ("Used on N surfaces", or archive when the use is history only).
   - Test: Task 2, `material_in_use_by_model`.

---

### Task 1: Contract: shared part module, record shape, spec amendment (Claude)

**Files:**
- Create: `static/twin/model_parts.js`
- Create: `services/twin_model_parts.py`
- Create: `tests/test_model_parts_js.py`
- Create: `tests/test_model_parts.py`
- Modify: `docs/superpowers/specs/2026-11-23-library-models-mode-design.md` (Data section: per-copy field is `model_materials`; box UVs at load)

**Interfaces (Produces, used by every later task):**

Model record additions. Imports keep them in `.asset.json`; built-ins keep them in `DATA_DIR/library_models/<id>.json`:

```
revision: int                       # bumps on every record write
lod_percent: [full, mid, far]       # ints, 100 >= full >= mid >= far >= 1; default [100, 25, 5]
lods: [{name: 'lod0.glb'|'lod1.glb'|'lod2.glb', triangles, bytes, percent, revision}]
                                    # lod0 exists only while full < 100
fix: {turn: 0|90|180|270, height_m?: >0..30, width_m?: >0..30}   # at most one of height_m/width_m
materials: {partKey: {material: libraryId, texture: 'real'|'model', tiles?: >0..100}}
parts: [{key, name, triangles, has_uv: bool, opaque: bool}]
parts_version: 1                    # generated levels carry partKey; absent = regenerate
```

The per-copy field on items, site furniture, site planting and openings:

```
model_materials: {partKey: {material: libraryId|'original', texture?: 'real'|'model', tiles?}}
```

`model_parts.js` exports. `services/twin_model_parts.py` mirrors the first five as `part_keys`, `resolve_part`, `validate_model_materials`, `validate_fix` and `validate_lod_percent`:
- `DEFAULT_LOD_PERCENT = [100, 25, 5]`
- `partKeys(names: (string|null)[]) -> string[]`
  - The first occurrence of a name keeps it; an empty or null name becomes `'unnamed'`.
  - Later occurrences get `~2`, `~3`, and so on, counted per name in order of appearance.
- `resolvePart(part, modelMaterials, copyMaterials) -> {source: 'copy'|'model'|'original', material: string|null, texture: 'real'|'model', tiles: number}`
  - A copy entry wins, then a model entry, then the original.
  - A copy entry with `'original'` gives `{source: 'copy', material: null}`.
  - `texture` is forced to `'real'` when `!part.has_uv`.
  - `tiles` defaults to 1 and counts only with `'model'`.
- `fixScale(fix, sizeM: [w, h, d]) -> number` returns `height_m / h`, or `width_m / w`, or 1.
- `fixTurnRadians(fix) -> number`
- `modelUv(uv: Float32Array, tiles: number, tileFt: [u, v]) -> Float32Array` returns `uv * tiles * tileFt`, so the shared `repeat = 1/tile_ft` yields exactly `tiles` repeats.
- `boxUvFeet(position: Float32Array, normal: Float32Array, scale: number) -> Float32Array`
  - Each vertex is projected on the dominant axis of its normal, in feet: `position * scale * 3.28084`.
  - It matches the wall convention: u along the horizontal axis and v up on the side faces; x/z on top and bottom.
- `materialCastsShadow(materialRecord) -> bool`
  - The library-record version of the occluder walk's `opaque` test. It is false when the material would build transparent (opacity < 1 or transmission), alpha-tested (an alpha map or cutout), or named `glass` or `fixture`.
  - Read `applyMaterialParams` in `static/twin/twin_library.js` (around line 302) for which params produce those flags. The test below pins the cases.
- `occluderInputs(record, copyMaterials, materialsById) -> string`
  - A canonical JSON of `{turn, height_m, width_m, mid: [percent, revision], shadow: '<one 0/1 per part in record.parts order>'}`.
  - Built from `resolvePart` + `materialCastsShadow`, with `part.opaque` for originals.
  - Returns `''` when the record has none of these fields, so today's keys stay unchanged.

*Done 2026-11-26. As built:*
- `materialCastsShadow` keys on `params.alpha_mode` (`blend` and `cutout` cast no shadow) and on the ids or roles `glass` and `fixture`, matching `alphaModeOf` and `applyMaterialParams`.
- `occluderInputs` omits members equal to a legacy record:
  - a mid level is included only when its percent is not 25 or its revision is above 1;
  - the shadow pattern is included only when it differs from the originals.

  So untouched or regenerated models keep today's keys. `attach_lod` (Task 2) starts the revisions at 1.

- [ ] **Step 1: Write the failing node tests** in `tests/test_model_parts_js.py`, using the pattern in `tests/test_model_lods_js.py`:
  - `keys_for_duplicates_and_unnamed`: `partKeys(['Wood', null, 'Wood', '', 'Metal', 'Wood'])` deep-equals `['Wood', 'unnamed', 'Wood~2', 'unnamed~2', 'Metal', 'Wood~3']`.
  - `resolution_order`:
    - part `{key: 'Wood', has_uv: true}`, model `{Wood: {material: 'oak', texture: 'model', tiles: 3}}`, copy `{}` gives `{source: 'model', material: 'oak', texture: 'model', tiles: 3}`;
    - copy `{Wood: {material: 'original'}}` gives `{source: 'copy', material: null}`;
    - copy `{Wood: {material: 'walnut'}}` gives source `'copy'`, texture `'real'`, tiles 1.
  - `no_uv_forces_real`: part `has_uv: false` with model texture `'model'` gives texture `'real'`.
  - `fix_maths`:
    - `fixScale({height_m: 0.9}, [2, 0.45, 1])` is `2`;
    - `fixScale({width_m: 1}, [2, 1, 1])` is `0.5`;
    - `fixScale({}, [2, 1, 1])` is `1`;
    - `fixTurnRadians({turn: 90})` is `Math.PI / 2`.
  - `model_uv_tiles`: `modelUv([0, 0, 1, 1], 3, [2, 2])` deep-equals `[0, 0, 6, 6]`.
  - `box_uv_feet`: a 1 m quad facing +z at scale 1 gives a u span of `3.28084` ±1e-5.
  - `shadow_cast_cases`: an opaque wood record is true; records with `opacity: 0.5`, an alpha cutout, and `name: 'glass'` are each false.
  - `occluder_inputs_neutral`: a record with no fix, no lods and no materials gives `''`.
  - `occluder_inputs_change_only_on_three`. Start from a record with lods `[{name: 'lod1.glb', percent: 25, revision: 1}]`. The value changes when each of these changes alone:
    - `fix.turn`;
    - `fix.height_m`;
    - the lod1 `revision`;
    - the lod1 `percent`;
    - a part going from oak to glass.

    It stays the same when each of these changes alone:
    - oak to walnut (both opaque);
    - texture `'real'` to `'model'`;
    - `tiles`;
    - the lod0 or lod2 percent.
- [ ] **Step 2: Write the failing Python tests** in `tests/test_model_parts.py`:
  - the same `part_keys` case;
  - `resolve_part` order;
  - validators refuse:
    - `lod_percent` `[100, 30, 40]`, `[0, 0, 0]` and `[101, 25, 5]`;
    - a fix with both `height_m` and `width_m`, and `turn: 45`;
    - `tiles` with `texture: 'real'`;
    - a `'original'` material at model level;
    - a part key not in `parts`;
    - a material id not in the given library ids.
  - Each validator raises `ValueError` with a person-readable message.
- [ ] **Step 3: Run both and see them fail:** `python tools/test.py test_model_parts_js.py test_model_parts.py`. Expected: FAIL, because the modules don't exist yet.
- [ ] **Step 4: Implement `static/twin/model_parts.js` and `services/twin_model_parts.py`** with the signatures above. Both are pure, with no three.js import (positions arrive as typed arrays).
- [ ] **Step 5: Run again:** `python tools/test.py test_model_parts_js.py test_model_parts.py`. Expected: PASS.
- [ ] **Step 6: Amend the spec** (Data: `model_materials` on every placed copy; box UVs computed at load) and commit on `models-design`.

---

### Task 2: Server: records, routes, validation, auth, in-use (Codex)

**Files:**
- Create: `services/twin_model_records.py`
- Modify: `services/twin_imports.py` (`attach_lod` around line 202; `start_upload` around lines 82-87; `rename` around line 439, which must keep `materials`/`fix`/`lod_percent` on a kind change)
- Modify: `main.py`, the model routes next to `/api/house/twin/imports` (around line 8309)
- Modify: `services/auth.py` (add rows beside lines 510-511 and 525-528)
- Modify: `services/twin_objects.py` (`validate` line 30, `update` line 69: accept and validate `model_materials`)
- Modify: `static/twin/object_schema.json` (`common.model_materials`, type object)
- Modify: `services/twin_materials.py` (`uses` line 654: count model-record `materials` and copies' `model_materials`)
- Modify: `static/twin/bake/geometry_key.js` line 5: add `'model_materials'` to `finishes`
- Test: `tests/test_twin_model_records.py` (new)
- Gate neighbours: `test_twin_import_chunks.py`, `test_twin_objects.py`, `test_twin_materials.py`, `test_auth.py`, `test_access_register.py`, `test_car_models.py`, `test_twin_bake_model_keys_js.py`

**Interfaces:**
- Consumes (Task 1): `twin_model_parts.validate_*`, `resolve_part`, and the record shape.
- Produces:
  - `twin_model_records.get(asset_id) -> dict`: the import record or built-in record, merged with defaults. KeyError if unknown.
  - `twin_model_records.catalog() -> list[dict]`: imports plus built-ins, each `{id, name, kind, builtin: bool, ...record}`.
  - `twin_model_records.update(asset_id, changes: dict, revision: int) -> dict`:
    - `changes` is a subset of `{lod_percent, fix, materials, parts, parts_version}`;
    - a revision mismatch raises `twin_model_records.Conflict(current)`;
    - a full percent of 100 removes `lod0.glb`;
    - a changed percentage clears that level's entry in `lods` until its upload arrives;
    - `parts` is accepted only while the record has no `parts_version` (first stamp or regeneration). Existing `materials` keys missing from the new parts are kept and listed in the response as `orphans`.
  - History works like materials (the `twin_materials._step` line 708 and `_save` line 354 pattern): every `update` pushes the previous `{lod_percent, fix, materials}` onto the record's history. `POST /api/house/models/{asset_id}/undo|redo|reset` with `{revision}` returns the record. Reset sets `lod_percent` to the default and removes `fix` and `materials`.
  - `GET /api/house/models` returns `{models: catalog()}`.
  - `GET /api/house/models/{asset_id}` returns the record.
  - `PATCH /api/house/models/{asset_id}`, body `{revision, lod_percent?, fix?, materials?}`. It returns the record; 409 `{detail, record}` on a conflict; 400 on a validation error.
  - Upload start accepts `lod in {'lod0.glb', 'lod1.glb', 'lod2.glb'}` plus `percent`. `finish` refuses with 409 when `percent` no longer equals the record's `lod_percent` for that level.
  - `attach_lod` records `{name, triangles, bytes, percent, revision}`, with `revision` = previous + 1.
  - The import file route serves with `Cache-Control: no-cache`. The client adds `?v=<lod revision>` (Task 4).

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_model_records.py` (TestClient, isolated `CHAUFFEUR_DATA_DIR`, one import created with `twin_imports.create`, and the parts list set at import):
  - `catalog_lists_imports_and_builtins`: `GET /api/house/models` includes the import and `mid_century_lounge_chair`, the latter with `builtin: true` and `lod_percent == [100, 25, 5]`.
  - `patch_sets_fix_and_materials`: a PATCH with `fix {height_m: 0.8, turn: 90}` and `materials {Wood: {material: <a library id>, texture: 'model', tiles: 2}}` returns `revision` +1 with both fields stored.
  - `revision_conflict_409`: a second PATCH with the old revision gives 409, and its body's `record.revision` is the current one.
  - `refuses_unknown_part`: `materials {Nope: ...}` gives 400.
  - `refuses_unknown_material`: 400.
  - `stale_lod_upload_refused`: start a lod1 upload with `percent: 25`, PATCH `lod_percent [100, 40, 5]`, finish gives 409, and `lods` has no lod1.
  - `full_below_100_lod0`:
    - after `lod_percent [60, 25, 5]`, an upload of `lod0.glb` with percent 60 attaches;
    - after PATCHing back to `[100, 25, 5]`, `lod0.glb` is gone from `files` and from disk.
  - `kind_change_keeps_overrides`: a rename to another kind with no placements keeps `materials` and `fix`.
  - `builtin_record_persists`: a PATCH on `mid_century_lounge_chair` writes `library_models/mid_century_lounge_chair.json`, and it survives `twin_library.ensure()`.
  - `copy_model_materials_validated`:
    - `set_object` on a placed item with `model_materials {Wood: {material: 'original'}}` succeeds;
    - with an unknown part it gives `ValueError` "Unknown part";
    - an opening's `model_materials` is validated against its `model` record.
  - `material_in_use_by_model`:
    - deleting a library material named in a model default fails with "Used on";
    - the same holds when only a copy's `model_materials` names it.
  - `undo_redo_reset`: after two PATCHes, undo gives the first state, redo the second, and reset gives `lod_percent [100, 25, 5]` with no `fix` and no `materials`. Each bumps `revision`.
  - `parts_stamp_once`: PATCHing `parts` on a record without `parts_version` succeeds; once `parts_version: 1` is set, the same PATCH gives 400.
  - `auth_rows`: `auth.resolve('GET', '/api/house/models')` is `WALL_OR_SERVICE`; `PATCH /api/house/models/{asset_id}` and `POST /api/house/models/{asset_id}/undo` are `PARENTS`.
- [ ] **Step 2: Add to `tests/test_twin_bake_model_keys_js.py`:** `atlas_key_ignores_model_materials`. A plan identical except for an item's and an opening's `model_materials` gives an equal `geometryKey`.
- [ ] **Step 3: Run and see them fail:** `python tools/test.py test_twin_model_records.py test_twin_bake_model_keys_js.py`.
- [ ] **Step 4: Implement** per Interfaces. Notes:
  - The built-in record file lives outside `DATA_DIR/library/<id>` so that `ensure()` can't remove it.
  - `uses()` reports model uses with labels like `"Model <name>: <partKey>"`, and copy uses like `"<piece name>: <partKey>"`.
- [ ] **Step 5: Gate:** `python tools/test.py test_twin_model_records.py test_twin_bake_model_keys_js.py test_twin_import_chunks.py test_twin_objects.py test_twin_materials.py test_auth.py test_access_register.py test_car_models.py`. Expected: all PASS.
- [ ] **Step 6: Write the report** to `docs/superpowers/reports/models-task2.md`: changes, tests and gate output. Do not commit.

---

### Task 3: Bake: occluder inputs and editor freshness parity (Codex)

**Files:**
- Modify: `static/twin/bake/model_occluders.js`:
  - `placedCopies` (line 9) adds opening copies `{id: 'opening:<b>:<o>', asset: o.model, at, rot, scale: [1, 1, 1], castsShadow}` for openings with a `model`. Use the opening's fitted transform from the same helpers the generator uses; if none is available without the builder, use the opening centre and wall yaw.
  - `occluderHash` (line 46) gains a parameter `inputs: (copy) => string`. Each near copy's tuple appends `inputs(copy)`.
- Modify: `static/twin/bake/baker.js` (`bakeLayout`, around lines 53-55: pass `copy => occluderInputs(records[copy.asset], copyMaterials(copy), materialsById)`).
- Modify: `static/twin/bake/runtime.js` (`editorFreshness`, around lines 645-661):
  - the editor compares each lamp's stored occluder hash with the current one, as the viewer does;
  - the grid check (around lines 618-624) also compares `gridLayout` with the current layout hash.
- Test: `tests/test_twin_bake_model_occluders_js.py` (extend)
- Gate neighbours: `test_twin_bake_model_keys_js.py`, `test_twin_bake_model_occluders_live.py`

**Interfaces:**
- Consumes (Task 1): `occluderInputs(record, copyMaterials, materialsById)`. Model records come from `GET /api/house/models`; the bake loads them once per bake. Materials come from the manifest already in the view.
- Produces: `occluderHash(copies, source, range, inputs = () => '')`. With the default `inputs`, the hash is byte-identical to today's.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_bake_model_occluders_js.py`, over the household fixture with one imported model on two items and one opening:
  - `hash_unchanged_without_inputs`: today's hash equals the new hash with the default `inputs` (golden from current main).
  - `fix_stales_only_near_lamps`:
    - setting `fix.turn: 90` on the model changes the hash of every lamp within reach of any of its copies;
    - every other lamp's hash is unchanged.
  - `mid_revision_stales`, `glass_override_stales`: same shape, for the lod1 revision bump and a copy override to a glass library material.
  - `colour_override_keeps_keys`: an oak-to-walnut model default changes no lamp hash and no `geometryKey`.
  - `opening_model_in_hash`: a door with a `model` appears in `placedCopies`, and an opening-copy glass override stales the lamps near that door only.
  - `editor_freshness_matches_viewer`: after a fix change, `editorFreshness` and the viewer's freshness list the same stale lamps.
- [ ] **Step 2: Run and see them fail:** `python tools/test.py test_twin_bake_model_occluders_js.py`.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Gate:** `python tools/test.py test_twin_bake_model_occluders_js.py test_twin_bake_model_keys_js.py test_twin_bake_model_occluders_live.py`. Expected: PASS.
- [ ] **Step 5: Write the report** to `docs/superpowers/reports/models-task3.md`. Do not commit.

---

### Task 4: Client pipeline: part keys, loadModel, levels, cars (Codex)

**Files:**
- Modify: `static/twin/model_lods.js`:
  - `makeLod` keeps `material.userData.partKey` on clones;
  - add `generateLevel(source, percent, signal) -> THREE.Object3D`, with full levels (percent < 100) through the same simplifier.
- Modify: `static/twin/editor/imports.js`:
  - `generateVersions` (line 215) moves to a new shared module, `static/twin/model_levels.js`. The editor imports it from there.
  - Its queue (lines 153-160) also regenerates records lacking `parts_version`.
- Create: `static/twin/model_levels.js`:
  - `stampParts(root) -> parts[]` sets `userData.partKey` on every material in first-appearance order (meshes in depth-first order) and returns the `parts` list. `opaque` uses the occluder walk's test on the original material.
  - `buildLevels(record, source, {signal, progress, upload, patch}) -> Promise<record>`:
    - when the record lacks `parts_version`, it first runs `stampParts` and `patch({parts, parts_version: 1})`;
    - it then generates and uploads every level whose `lods` entry is missing or whose percent differs, sending `percent` with each upload.
  - `GLTFExporter` must write `userData` to `extras`, and the loader reads it back.
- Modify: `static/twin/twin_library.js` `loadModel` (line 524):
  - it fetches the record (cached per `revision`);
  - it uses `lod0.glb` in place of the original wherever the full level is drawn, the editor included (lines 537-553);
  - it applies `fixScale` and `fixTurnRadians` to the root before `normaliseModel`;
  - it merges by part key, so one mesh per part per level. Today this equals merge-by-original-material, so the goldens stay the same;
  - it applies model defaults with `applyPartMaterials(root, record, {}, kit)`;
  - level URLs gain `?v=<lod revision>`, and `modelCache` keys include it;
  - the heavy stand-in and import warnings read the effective full level's triangles.
- Add: `applyPartMaterials(root, record, copyMaterials, kit) -> void`, exported from `twin_library.js`:
  - per mesh, `resolvePart`;
  - a library material goes through the same `kitMaterial` / `materialSlot` path walls use (shared instance);
  - `texture: 'real'` sets the `uv` attribute to `boxUvFeet`;
  - `'model'` sets it to `modelUv(original uv, tiles, tile_ft)`. The original uv is kept in `userData.uvOriginal`;
  - `'original'` restores the cached original material and uv;
  - an unknown material id or part key falls back to the original and logs one `console.warn` per model and part.
- Modify: `static/twin/twin_generator.js` (items 2537-2606, openings 1447-1477) and `static/twin/twin_yard.js` (803-842):
  - after `applyObject`, call `applyPartMaterials(model, record, piece.model_materials || {}, kit)`;
  - each `snapRanges` entry for a model copy gains `partKey`.
- Modify: `static/twin/live/cars.js` `placeCarModel` (line 9): when `record.fix.turn` is set, it replaces `carTurn`.
- Test: `tests/test_model_parts_pipeline_js.py` (new)
- Gate neighbours: `test_model_lods_js.py`, `test_model_lod_import_js.py`, `test_twin_import_chunks_js.py`, `test_twin_objects_js.py`, `test_twin_library_js.py`, `test_twin_cars_js.py`, `test_twin_item_slot_rows_js.py`

**Interfaces:**
- Consumes:
  - from Task 1, every `model_parts.js` export;
  - from Task 2, `GET /api/house/models/{id}`, the upload `lod` and `percent` fields, and 409 on stale.
- Produces:
  - `model_levels.js`: `stampParts`, `buildLevels`;
  - `twin_library.js`: `applyPartMaterials`, `modelRecord(assetId) -> Promise<record>`;
  - snapRange `partKey`. Tasks 5 and 6 rely on these.

- [ ] **Step 1: Write the failing tests** in `tests/test_model_parts_pipeline_js.py`. The fixture is a generated glTF with materials `['Wood', null, 'Wood', 'Glass']`, one mesh with no uv, placed twice in the household fixture.
  - `keys_survive_export_roundtrip`: `stampParts`, then `buildLevels` with a fake upload capturing the files, then re-parse each level. Every material's `userData.partKey` is in the original's key set, and all four keys appear in the original.
  - `untouched_render_identical`: with no record fields, `loadModel` output (mesh count, material names, triangle count, world bounds) equals main's.
  - `fix_applies_everywhere`:
    - with `fix {height_m: 0.9}`, the loaded bounds height is 0.9 ±1e-3 for the item copy and the car;
    - an opening copy keeps the `fitOpening` size;
    - with `fix.turn: 90`, the car's yaw equals the fix and not `carTurn`.
  - `model_default_on_every_copy`: a model default `Wood -> oak` gives both copies a `Wood` mesh material equal (`===`) to the `kitMaterial('oak')` instance.
  - `copy_override_and_original`: copy A `{Wood: {material: 'walnut'}}`, copy B `{Wood: {material: 'original'}}`. A uses walnut, B the original, and copy C (no field) uses oak.
  - `uv_modes`:
    - a part with uv and `texture: 'model', tiles: 2` gets `uv == uvOriginal * 2 * tile_ft`;
    - the no-uv part gets `boxUvFeet` values;
    - no new material is created per copy (the count of distinct material instances equals the count of distinct resolved materials).
  - `stale_override_falls_back`: an override naming a missing material id renders the original, with exactly one `console.warn`.
  - `full_level_used`: with `lod_percent [60, 25, 5]` and lod0 present, both `loadModel(..., {editor: true})` and the viewer fetch `lod0.glb?v=<rev>`, not the original.
  - `snapranges_carry_part`: every model copy's snapRange has a `partKey` from the record's parts.
- [ ] **Step 2: Run and see them fail:** `python tools/test.py test_model_parts_pipeline_js.py`.
- [ ] **Step 3: Implement** per Files and Interfaces.
- [ ] **Step 4: Gate:** `python tools/test.py test_model_parts_pipeline_js.py test_model_lods_js.py test_model_lod_import_js.py test_twin_import_chunks_js.py test_twin_objects_js.py test_twin_library_js.py test_twin_cars_js.py test_twin_item_slot_rows_js.py test_model_parts_js.py`. Expected: PASS.
- [ ] **Step 5: Write the report** to `docs/superpowers/reports/models-task4.md`, including draw calls and programs on the household fixture before and after, with one model default applied. Do not commit.

---

### Task 5: Library page Models tab (Gemini)

**Files:**
- Modify: `templates/house_library.html`:
  - add `window.chfLodWorker` exactly as `templates/house_editor.html` line 63 does;
  - add an import-map entry for `three/addons/exporters/GLTFExporter.js` if the generic `three/addons/` mapping does not resolve it.
- Modify: `static/twin/library_page/page.js`:
  - a `Materials | Models` tab strip in the header;
  - `?model=<id>` opens the Models tab on that model;
  - the right-panel model-file drop imports a model on the Models tab and keeps `importGltf` on the Materials tab.
- Create: `static/twin/library_page/models.js`, `mountModels(root, {api})`:
  - left column: grid with filters All / Built-in / Mine plus kind; Import button and drop.
  - centre: `createPreview` extended with `setModel(object)`, a level switch Full / Mid / Far, and a wireframe toggle. Each level shows its triangles and bytes.
  - right column:
    - Name, Kind, Delete, following today's rules and messages from the server;
    - Size (ft/in, height or width) and quarter turns;
    - Detail levels (three percentages);
    - Parts, one `createSlotRow` per part: swatch, "from the original" / "<material>", Texture Real size / Model's own (Model's own disabled with no uv), Tiles (shown only with Model's own), Use selected, Clear.
- Modify: `static/twin/library_page/preview.js`:
  - `setModel(object3d)`;
  - `partAt(x, y) -> partKey|null` for drag-over highlighting with a tinted outline;
  - accepts a material drop on a part.
- Test: `tests/test_twin_library_models_js.py` (new), `tests/test_house_library_page.py` (extend)
- Gate neighbours: `test_twin_library_page_js.py`, `test_twin_alpha_library_page_js.py`, `test_twin_slot_row_js.py`, `test_house_library_page.py`

**Interfaces:**
- Consumes:
  - from Task 2: `GET /api/house/models`, `GET|PATCH /api/house/models/{id}` with `revision` and the 409 body, the chunked upload routes, and `PATCH /api/house/editor/imports/{id}` for name/kind;
  - from Task 4: `buildLevels`, `stampParts`, `applyPartMaterials`, `modelRecord`;
  - from Task 1: `partKeys` and `resolvePart`;
  - `createSlotRow` from `static/twin/editor/slot_row.js`.
- Produces: nothing consumed later. The editor links to `house/library?model=<id>` (Task 6).

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_library_models_js.py` (node DOM rig as in `test_twin_library_page_js.py`, with the API faked):
  - `tab_and_deeplink`: `?model=import-…` opens Models with that model selected, and the Materials tab still shows today's grid.
  - `import_on_models_tab`: dropping a .glb on the Models tab calls the chunked upload, then `buildLevels`. The same drop on Materials calls `importGltf`.
  - `last_percent_wins`: two percentage edits 10 ms apart; the first build's upload gets a 409 from the fake and is ignored; the record shows the second percentage.
  - `conflict_reloads`: a PATCH returning 409 reloads the record and calls `showGlobalAlert` once.
  - `part_rows`:
    - four rows for the four-part fixture, and the no-uv row has Model's own disabled;
    - Tiles appears only with Model's own;
    - Clear sends `materials` without that key.
  - `size_and_turn`: entering 2 ft 6 in height PATCHes `fix {height_m: 0.762}`, and quarter turn sends `turn: 90`.
  - `builtin_no_levels`: a built-in model hides the Detail levels and Delete, and shows Parts and Size.
  - `old_import_regenerates`: selecting a record without `parts_version` calls `buildLevels` once and shows its progress.
  - `undo_redo_reset_buttons`: the Models tab's Undo, Redo and Reset post to `models/{id}/undo|redo|reset` with the current revision and redraw from the response.
  - `thumbnail_rerenders`: after a parts or fix change on an import, the page renders a new thumbnail from the preview and sends it through `PATCH /api/house/editor/imports/{id}` (`thumbnail`).
- [ ] **Step 2: Extend `tests/test_house_library_page.py`:** the page HTML defines `window.chfLodWorker`.
- [ ] **Step 3: Run and see them fail:** `python tools/test.py test_twin_library_models_js.py test_house_library_page.py`.
- [ ] **Step 4: Implement**, following `docs/ui_design_guide.md` and the page's existing three-column layout. Run `python tools/build_tailwind.py` after class changes.
- [ ] **Step 5: Look at it in Chromium on the household fixture data:**
  - grid;
  - a model at Full/Mid/Far with wireframe;
  - a drag of oak over a chair leg (highlight), then dropped;
  - a part row in Model's own with Tiles 3.

  Save screenshots under `.gemini-tmp/shots/`.
- [ ] **Step 6: Gate:** `python tools/test.py test_twin_library_models_js.py test_house_library_page.py test_twin_library_page_js.py test_twin_alpha_library_page_js.py test_twin_slot_row_js.py`. Expected: PASS.
- [ ] **Step 7: Write the report** to `docs/superpowers/reports/models-task5.md` with the screenshot paths. Do not commit.

---

### Task 6: Editor: part rows, drop scopes, model-record undo (Codex)

**Files:**
- Modify: `static/twin/editor/history.js` (`createHistory`):
  - add `record({kind: 'model-record', asset, before, after})`;
  - undo PATCHes `/api/house/models/{asset}` with `before` and the current revision; redo does the same with `after`;
  - the step sits in the same stack as round steps, in order;
  - a 409 on undo stops, with `showGlobalAlert`, and leaves the stack unchanged.
- Modify: `static/twin/editor/library.js`:
  - `surfaceAt` (line 450) returns `{kind: 'model-part', pieceKind, pieceId, buildingId, asset, partKey}` for a model copy's triangle, using the snapRange `partKey`;
  - `scopeChoices` (line 220) offers "This copy" and "The model (all copies)" for that surface;
  - "This copy" applies through `set_object` with `model_materials`;
  - "The model" applies through PATCH plus `history.record`;
  - `assetActions` (line 348) gains "Edit in Library" for models, linking `house/library?model=<id>` with `target=_blank` like materials.
- Modify: `static/twin/editor/object_shelf.js`:
  - `drawObjectShelf` (line 27) and `drawOpeningModelSlot` (line 89) add a Parts section with one `createSlotRow` per part;
  - `inherited` reads "from the model" or "original";
  - an entry with `material: 'original'` reads "original (this copy)";
  - Clear removes the copy key.
- Test: `tests/test_twin_model_part_drops_js.py` (new)
- Gate neighbours: `test_twin_editor_library_js.py`, `test_twin_object_shelf_js.py`, `test_twin_slot_row_js.py`, `test_twin_item_slot_rows_js.py`, `test_house_editor_history_js.py` (if missing, list the file that tests `history.js` in the report)

**Interfaces:**
- Consumes:
  - from Task 4: snapRange `partKey`, `modelRecord`, `applyPartMaterials`;
  - from Task 2: PATCH with revision, and `set_object` accepting `model_materials`.
- Produces: nothing later.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_model_part_drops_js.py` (editor DOM rig, household fixture plus the four-part model on two items and one door):
  - `drop_offers_model_scopes`: a material drop on a chair's Wood triangle shows "This copy" and "The model (all copies)". On a wall it shows today's choices unchanged.
  - `this_copy_sets_model_materials`: "This copy" sends `set_object` with `model_materials {Wood: {material: id}}` for that piece only.
  - `model_scope_undo_redo`:
    - "The model" PATCHes the record, and Ctrl+Z PATCHes it back to `before`;
    - Ctrl+Shift+Z re-applies;
    - a round step made between them undoes in stack order.
  - `undo_conflict_stops`: an undo PATCH answered 409 calls `showGlobalAlert`, and the stack is unchanged.
  - `parts_rows_on_card`: the selected item card lists four part rows, and the door's card lists its model's parts. Rows read "from the model" or "original (this copy)" as set.
  - `edit_in_library_link`: an import model's actions include an anchor to `house/library?model=<id>`.
- [ ] **Step 2: Run and see them fail:** `python tools/test.py test_twin_model_part_drops_js.py`.
- [ ] **Step 3: Implement** per Files.
- [ ] **Step 4: Gate:** `python tools/test.py test_twin_model_part_drops_js.py test_twin_editor_library_js.py test_twin_object_shelf_js.py test_twin_slot_row_js.py test_twin_item_slot_rows_js.py` plus the history test file named in Files. Expected: PASS.
- [ ] **Step 5: Write the report** to `docs/superpowers/reports/models-task6.md`. Do not commit.

---

### Task 7: Browser proof, cost report, demo shot, landing (Claude)

**Files:**
- Modify: `tools/demo_capture.py`: add the shot `library-models`, with a `SHOTS` entry, a `SURFACE_LABELS` entry, a readiness clause, and a capture branch that opens `house/library?model=<seeded id>` with one part overridden.
- Modify: `tools/demo_seed.py`: seed the four-part model with a model default, through `twin_imports.create` and `twin_model_records.update`.
- Modify: `chauffeur/system_capabilities.md` (top entry per landed slice)

- [ ] **Step 1: Run the browser checks on the owner's house export**, one per spec line:
  - import on the Models tab, then a level rebuild at a changed percentage;
  - a model default showing on every copy;
  - a per-copy override through the drop menu;
  - a library material edit propagating to a model part;
  - real-size texture on a part with 0..1 UVs and on a part with no UVs;
  - a colour-only override leaving every bake key unchanged;
  - a size fix, a mid-percent change and an opaque-to-glass override each staling only the nearby lamps, and a rebake clearing them.

  Capture the default overview, the building focus and close-ups, after shaders settle.
- [ ] **Step 2: Cost report:**
  - programs, draws, triangles and samplers before and after, on the owner's house with overrides applied;
  - level rebuild time for a 300k and a 1M triangle model;
  - expected: the program delta is 0 except a first use of a new library material.
- [ ] **Step 3: Demo shot:** `python tools/demo_capture.py library-models` produces the shot.
- [ ] **Step 4: Land each slice per AGENTS.md:**
  1. merge main;
  2. run the task's gate;
  3. bump with `tools/bump_version.py`;
  4. add the capabilities entry;
  5. fast-forward and push;
  6. run `hub_note --kind shipped`.

  The final slice's note uses `--item models-mode`.
