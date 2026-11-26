# Placed models in the bake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Placed models cast baked lamp shadows and receive baked lamp light (shadowed by built geometry, live-tinted) through a light-visibility grid, and moving a model stops forcing a full rebake.

**Architecture:** The editor baker renders placed models (mid LOD, per copy) into each lamp's jittered shadow cubes, and on each lamp's first page accumulates per-emitter visibility for a grid of points filling rooms and lit yard. Grid chunks are stored next to the pages. The viewer resamples the grid into a 5x5x5 brick per placed copy, packs bricks into one RGBA8 3D texture and emitter/brick rows into one float data texture, and a patch on placed-model materials runs up to 8 emitters through three's `RE_Direct`.

**Tech Stack:** three.js r187 (vendored, WebGL2), FastAPI (`chauffeur/main.py`), node-run JS tests and Playwright Chromium tests driven from Python.

**Spec:** `docs/superpowers/specs/2026-11-23-models-in-bake-design.md` (owner-approved 2026-11-23). Read it before your task.

## Global Constraints

- All paths below are relative to `chauffeur/` unless they start with `docs/`.
- Tests run from `chauffeur/` as plain scripts: `python tests/test_x.py`. Unset `HA_BASE_URL` first. Never run the whole suite.
- Every critical path has a test that runs it (node for JS modules, Chromium for GPU and page paths), never a source grep.
- No sampler on any material except placed-model materials. Placed-model materials gain exactly two: `mvBricks` (sampler3D) and `mvLamps` (sampler2D).
- One extra program per placed-model material at most; no variant per emitter count or per copy.
- Placed models stay merged per material (no un-merging).
- Indoor grid spacing 1 ft (0.3048 m), points at cell centres inset half a spacing; yard spacing 2 ft horizontally, from `groundAt` to 10 ft above it; bricks 5 x 5 x 5; at most 8 emitters per copy.
- Visibility byte 0..254 = 0..1; 255 = invalid point (inside solid).
- `casts_shadow: false` keeps a copy out of bake occluders.
- Implementers (Codex, Gemini) do not commit and do not bump `config.yaml`; leave changes in the working tree with a note of what was changed and tested. Claude reviews, commits per task, and lands.
- PowerShell: never round-trip source through Get-Content/Set-Content. No browser dialogs.

## Rulings made while planning (deviations from the spec text, same intent)

1. **Occluder hash is plan-only.** Kit models have no size metadata and import metadata may not be loaded when the viewer computes keys. A copy counts for a lamp when its placement point is within `range + MODEL_REACH_MARGIN_M` (5 m) of the lamp source. The hash holds asset id, placement point, rotation/pitch/roll, scale fields and `casts_shadow`; it omits the LOD file (LODs change only at import). Cost if wrong: a move can mark a few extra lamps stale.
2. **LOD copies carry the brick index as a vertex attribute too**, on a per-copy shallow geometry (shared attribute objects plus their own `mvBrick`), instead of a per-object uniform. One path for merged and LOD copies. `material.defaultAttributeValues.mvBrick = [0]` covers any mesh without it.
3. **The grid lights a model only for lamps whose pages are fresh.** A lamp made stale by a move lights models through the live pool, as it lights the walls. This prevents double lighting. The grid chunk still has its own key, so rebaking that lamp after a move reuses the chunk instead of uploading it again.
4. **`mvBrick` stores brick index + 1;** 0 means no brick (the patch adds nothing).

## Review Focus

1. A lamp inside a lamp-shade model must still light its room (bounds-contain-source exclusion). Test in Task 2.
2. A model against a wall or beside a kitchen island must not be darkened by invalid points. Test in Tasks 4 and 6.
3. A lamp switched off or dimmed live must darken models and walls together, including in modes that hide lights (tint 0). Test in Task 8.
4. A multi-colour line lamp (palette) must never light a model twice. Test in Task 6.
5. A house with no bake, or a bake made before this change, must render models exactly as today with no new programs. Test in Task 8.

## Split (owner rule: say the split before code)

- **Codex** (`--model gpt-6.1-sol`, worktree `E:\repositories\Chauffeur-models-bake`): Tasks 1, 2, 3, 5, 8: keys, occluders, server, baker integration, runtime wiring.
- **Gemini** (worktree `E:\repositories\Chauffeur-models-bake-g`, branch `models-bake-g` from `models-bake`): Tasks 4, 6, 7, 9: grid layout and bake pass, bricks, shader, debug view.
- Order: Codex 1 then 2 then 3; Gemini 4 then 6 then 7, in parallel. Claude merges `models-bake-g` into `models-bake`, then Codex 5 and 8, then Gemini 9. Claude runs every Chromium check (Codex's sandbox cannot launch Playwright) and Task 10.

---

### Task 1: Placement leaves the atlas key; per-lamp occluder hash and grid key

**Files:**
- Create: `static/twin/bake/model_occluders.js`
- Modify: `static/twin/bake/geometry_key.js:27-29`, `static/twin/bake/key_inputs.js:5-7`, `static/twin/bake/baker.js:11-23` and `bakeLayout` (:27-75)
- Test: `tests/test_twin_bake_model_keys_js.py` (new, node driver patterned on `tests/test_twin_bake_fingerprint_js.py:221-232`); update `tests/test_twin_bake_fingerprint_js.py:60-66` and `:131-134`

**Interfaces:**
- Produces:
  - `placedCopies(plan) -> [{id:'item:<bId>:<itemId>'|'furniture:<id>'|'planting:<id>', asset, at:[x,y,z] world metres, rot:[pitch,rotation,roll], scale:[sx,sy,sz], castsShadow:boolean}]`. Items: world point from `hostPoint(b, item.host, item.offset)` plus `elevation`, through the building transform (position, `buildingGround`, rotation). Furniture and imported planting (`asset` starts with `import-`): `at` plus `groundAt`. Openings are not included (they stay in the atlas key).
  - `MODEL_REACH_MARGIN_M = 5`
  - `occluderHash(copies, source:{x,y,z}, range) -> string` (fingerprint over the sorted ids and fields of copies whose `at` lies within `range + MODEL_REACH_MARGIN_M`; empty string when none).
  - `lightKey(atlas, light, slot, bank)` hashes one more element, `light.occluders || ''`. `gridKey(atlas, light, slot, bank) -> string` is the same hash without it.
  - `bakeLayout` sets `light.occluders = occluderHash(placedCopies(atlas.room.plan), reach source, light.range)` and writes `entries[device].grid = gridKey(...)`.
  - `authoredGeometry` drops building `items`, site `furniture` and imported `planting` (non-import planting stays).
  - `ATLAS_VERSION = 'reach-atlas-13'`, `ATLAS_WORKER_VERSION = 'atlas-worker-reach-13'`.

- [ ] **Step 1: Write the failing tests.** In `test_twin_bake_model_keys_js.py`:
  - `test_moving_an_item_keeps_atlas_key`: rotating or moving a building item, or a `site.furniture` piece, leaves `authoredGeometry(plan)` and `buildAtlas(...).key` unchanged. Changing an opening's `model` still changes them.
  - `test_occluder_hash_only_near_lamps`: with a lamp at the origin with range 6 m, an item at 4 m changes `occluderHash` when moved. An item at 20 m does not, and its hash is `''`.
  - `test_casts_shadow_changes_hash`: toggling `casts_shadow` false changes the hash of a nearby lamp.
  - `test_grid_key_ignores_models`: `lightKey` changes and `gridKey` stays when a nearby item moves. Both change when the lamp moves.
  - `test_versions_bumped`: `ATLAS_VERSION === 'reach-atlas-13'`.
  - Update the two fingerprint tests: furniture and items no longer change the atlas key, and the occluder hash does change.
- [ ] **Step 2:** Run `python tests/test_twin_bake_model_keys_js.py`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement as in Interfaces. Use `fingerprint()` from `geometry_key.js`. Round the hashed coordinates to 1 mm and the angles to 0.1 degree.
- [ ] **Step 4:** Run the new test, `tests/test_twin_bake_fingerprint_js.py`, `tests/test_twin_baker_js.py`, `tests/test_twin_bake_editor_keys_js.py` and `tests/test_twin_light_reach_js.py`. Expected: all pass.
- [ ] **Step 5:** Claude commits: `feat(bake): placements leave the atlas key; per-lamp occluder hash and grid key`.

### Task 2: Placed models occlude in the bake

**Files:**
- Modify: `static/twin/bake/bake_pass.js:145-163` (`occluders(view)` becomes `occluders(view, source, range)`), `static/twin/bake/runtime.js:858` (add `modelRoot()` to the controller)
- Create: `static/twin/bake/model_occluder_meshes.js`
- Test: `tests/test_twin_bake_model_occluders_js.py` (node), `tests/test_twin_bake_model_occluders_live.py` (Chromium, patterned on `tests/test_twin_shadowmask_live.py:224-234`)

**Interfaces:**
- Consumes: the plan item fields `casts_shadow` and `object_kind`; merged meshes with `userData.merged`, `geometry.userData.bakeExcluded`, and `userData.snapRanges = [{start, count, kind, pieceId, buildingId}]`; LOD objects with `userData.modelLod` (`lod.levels[1].object` = lod1).
- Produces:
  - `modelOccluderMeshes(root, plan, source:THREE.Vector3, range) -> THREE.Mesh[]`. One Mesh per copy (`drawRange` = the copy's snap range on the shared geometry; `matrix` = the source's `matrixWorld`). Includes only copies that are `bakeExcluded` (model-sourced), opaque (the `atlasMesh` material rules), with `casts_shadow !== false`, whose world bounds intersect the range sphere and do NOT contain `source`. LOD copies contribute their level-1 meshes, or level 0 when there is no level 1. Bounds are cached per (geometry uuid, start, count).
  - `controller.modelRoot()` returns the editor's lazy viewer-shaped build (`physical`, twin_view.js:1864-1869) once `physical.ready` resolves, else `null`.
  - `occluders(view, source, range)` adds `modelOccluderMeshes(view.bake.modelRoot(), view.plan, source, range)` to today's blockers.

- [ ] **Step 1: Write the failing node test** `test_model_occluder_selection`. Fake merged geometry with three copies:
  - a copy 2 m from the source: included;
  - a copy 30 m away with range 6: excluded;
  - a copy whose box contains the source: excluded;
  - a copy with `casts_shadow:false`: excluded;
  - a transparent-material copy: excluded.
  Also an LOD copy that yields its level-1 meshes. Assert ids and `drawRange` values.
- [ ] **Step 2: Write the failing Chromium test** `test_model_shadows_floor_and_shade_keeps_light`, using a bare scene as in `test_twin_shadowmask_live.py`:
  - a floor chart, a point lamp 2 m up, and a 0.5 m box "model" (bakeExcluded merged mesh with a snap range) between them;
  - the page texel under the box is below 0.5x the texel 1.5 m away;
  - with a closed box enclosing the lamp instead, floor texels stay at 0.9x or more of the no-model value.
- [ ] **Step 3:** Run both. Expected: FAIL.
- [ ] **Step 4:** Implement. `renderPage` passes `source`/`range` (already computed at bake_pass.js:184) to `occluders`.
- [ ] **Step 5:** Claude runs both tests plus `tests/test_twin_shadowmask_live.py` and `tests/test_twin_baker_js.py`. Expected: pass.
- [ ] **Step 6:** Claude commits: `feat(bake): placed models cast baked lamp shadows at mid LOD`.

### Task 3: Grid chunk storage routes

**Files:**
- Modify: `services/twin_bakes.py` (after `save_page` :89-105), `main.py` (next to the page routes :8020-8068), `services/auth.py:474-482`
- Test: `tests/test_twin_bakes.py` (add cases next to :201, :299, :383)

**Interfaces:**
- Produces:
  - `GRID_SIGNATURE = b'MVG1'`; `MAX_GRID_BYTES = 8 MiB`; grid name regex `[0-9a-f]{16,64}`.
  - `save_grid(key, name, data, owner) -> {etag, version}`: lease-checked and atomic like `save_page`, stored at `bakes/<key>/grid-<name>.bin`, so it is pruned with its key.
  - `grid_response(key, name, matches) -> (bytes|None, etag, size)`.
  - Routes: `POST /api/house/bakes/{key}/grid/{name}.bin` (PARENTS, `X-Bake-Owner`, 413 over the cap, 409 on a lease conflict, 400 on a bad signature or name) and `GET` of the same path (WALL_OR_SERVICE, `ETag`, 304 on match).
  - `_check_manifest` accepts entry fields `grid` (name string) and `gridLayout` (hex string).

- [ ] **Step 1: Write the failing tests:**
  - `test_grid_roundtrip`;
  - `test_grid_rejects_bad_signature`;
  - `test_grid_rejects_oversize`;
  - `test_grid_routes_have_their_tiers` (the existing `_app_routes` pattern);
  - `test_grid_pruned_with_key`;
  - `test_manifest_accepts_grid_fields`.
- [ ] **Step 2:** Run `python tests/test_twin_bakes.py`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `tests/test_twin_bakes.py`, `tests/test_auth.py` and `tests/test_access_register.py`. Expected: pass.
- [ ] **Step 5:** Claude commits: `feat(bake): grid chunk storage and routes`.

### Task 4: Grid layout, inside-solid mask, chunk codec, GPU accumulation

**Files:**
- Create: `static/twin/bake/grid_layout.js`, `static/twin/bake/grid_chunk.js`, `static/twin/bake/grid_pass.js`
- Test: `tests/test_twin_grid_layout_js.py` (node), `tests/test_twin_grid_pass_live.py` (Chromium)

**Interfaces:**
- Consumes: `roomData(plan)` (atlas.js:58-81, building-local feet, plan y = -z); the building transform (twin_generator.js:503, :640-642); `groundAt(plan, x, y)` (twin_ground.js:29); `plan.site.lot`; `buildOccluderBVH(meshes, bounds)` and `collectStaticOccluders(scene, view)` from `live/cone_occluder.js` (`castRay(ox,oy,oz,dx,dy,dz,tMin,tMax) -> t|tMax`, double-sided); the shadow cube depth `R = length(wp-source)/far` and the test `step(reached-.02, stored)` (bake_pass.js:28-31, :190-193).
- Produces:
  - `gridLayout(plan, lamps:[{source:{x,y,z}, range, outdoor:boolean}]) -> {hash, count, blocks:[{id, kind:'room'|'yard', atlasRoom?, building?, level?, spacing, dims:[nx,ny,nz], first, toLocal:Matrix4 (world m -> block cell coords), ground?:Float32Array (yard: per column ground height m)}]}`. Room blocks fill the room's polygon bounds from floor to the level ceiling and are kept only when a lamp range reaches them; yard blocks cover the lot cells within a yard lamp's range. `first` is the block's first global point index.
  - `gridPoints(layout) -> Float32Array` (xyz world m per global index; points outside the room polygon are present but marked invalid).
  - `pointsInRange(layout, points, source, range) -> Uint32Array`.
  - `insideMask(points, bvh, layout) -> Uint8Array` (1 = invalid): outside the polygon, or inside a solid by ray parity along +-x, +-y, +-z (majority of 6). Walk each ray hit-by-hit with `tMin = t + 1e-4`.
  - `encodeGridChunk({layoutHash, device, emitters:n, indices:Uint32Array, values:Uint8Array}) -> Uint8Array` and `decodeGridChunk(bytes) -> same shape`. Magic `MVG1`, then u32 header length, JSON header, the indices and the values `[pointIndex*n + emitter]`, all gzipped.
  - `createGridAccumulator(renderer, points:Float32Array, indices:Uint32Array, emitterCount) -> {sample(shadowTexture:CubeTexture, source:Vector3, far:number, emitter:int, weight:number), read() -> Uint8Array (n values per index, 0..254), dispose()}`. One float render target, one texel per (point, emitter), additive blend of `weight * visible`, normalised by each emitter's weight sum on `read()`.

- [ ] **Step 1: Write the failing node tests:**
  - `test_room_grid_dims`: a 10 x 12 ft room with a 9 ft ceiling and a lamp in range gives dims `[10, 12, 9]` and points at 0.5 ft insets.
  - `test_room_without_lamp_has_no_block`.
  - `test_yard_grid_follows_ground`: on a sloped lot, the yard points' heights above `groundAt` are 1, 3, 5, 7 and 9 ft.
  - `test_layout_hash_stable`: same input, same hash; moving a placed item does not change it.
  - `test_inside_mask`: a point inside a closed 1 m box is 1; a point in open room air is 0; a point inside a 3 x 3 ft closet with walls is 0.
  - `test_chunk_roundtrip`.
- [ ] **Step 2: Write the failing Chromium test** `test_accumulator_matches_cpu`:
  - a wall between the lamp and half the points;
  - 16 jittered samples;
  - accumulator values within 2/254 of a CPU reference that uses the same depth test via `castRay`;
  - fully visible points give 254 and points fully behind the wall give 0.
- [ ] **Step 3:** Run. Expected: FAIL.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Claude runs both tests. Expected: pass.
- [ ] **Step 6:** Claude commits: `feat(bake): visibility grid layout, mask, chunk codec and accumulator`.

### Task 5: Baker bakes and publishes the grid

**Files:**
- Modify: `static/twin/bake/bake_pass.js` (`renderPage` option `onSample(shadowTexture, sample, far)` called after the 6 faces at :222), `static/twin/bake/baker.js` (`bakeStep` :210-344, `createBaker` state), `static/twin/bake/runtime.js` (`controller.state()` :854-855)
- Test: `tests/test_twin_baker_js.py` (extend `fakeServer` :157+ with the grid route), `tests/test_house_twin_bake_live.py` (add one scenario)

**Interfaces:**
- Consumes: everything from Task 4; `sample.emitter` and `sample.visibilityWeight ?? sample.weight` (fixture_terms.js:40-69; legacy lamps use emitter 0); `entries[device].grid` from Task 1; the Task 3 routes.
- Produces:
  - On the first page of each stale light, the baker builds the layout once per bake (cached on the layout hash). It then creates an accumulator for `pointsInRange` and calls `sample` from `onSample`. It writes 255 into every value of masked points.
  - `encodeGridChunk`/`decodeGridChunk` are async (ruling after Task 4): `await` them. The uploaded chunk is gzip-wrapped MVG1, at most 8 MiB on the wire.
  - Build the inside-mask BVH from `collectStaticOccluders` WITHOUT a `bounds` crop (ray parity needs whole solids), and record `insideMask` time in `state().grid.ms` alongside the accumulation time.
  - It POSTs the chunk to `${path}/grid/${entry.grid}.bin` before the manifest PUT, and only when no chunk with that name is already listed in the manifest.
  - The manifest entry gains `grid` and `gridLayout`.
  - Lamps excluded from the grid: palette line lamps (`paletteLineEntities`, real_lights.js:10-13). Their entries carry no `grid`.
  - `controller.state()` gains `grid: {points, bytes, ms}` for the last light, and the editor status text shows `Grid n points` while baking.
  - The inside mask uses `collectStaticOccluders` on the bake's occlusion root, built once per bake.

- [ ] **Step 1: Write the failing tests:**
  - In `test_twin_baker_js.py`:
    - `test_grid_chunk_published_with_light`: one POST to `/grid/<entry.grid>.bin` with the MVG1 signature, and the manifest entry has `grid` and `gridLayout`.
    - `test_grid_not_reuploaded_when_name_listed`.
    - `test_palette_line_has_no_grid`.
  - In `test_house_twin_bake_live.py`: `scenario_bake_publishes_grid_chunks` on the household fixture. Every fresh non-palette light has a `grid` that GETs 200, and `state().grid.points > 0`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Claude runs `tests/test_twin_baker_js.py`, `tests/test_twin_bake_editor_js.py`, `tests/test_twin_bake_fixtures_js.py` and `tests/test_house_twin_bake_live.py`. Expected: pass. Claude records the bake time against main on the household fixture.
- [ ] **Step 5:** Claude commits: `feat(bake): bake and publish the light-visibility grid`.

### Task 6: Per-copy bricks, emitter choice, the two textures

**Files:**
- Create: `static/twin/bake/model_bricks.js`
- Test: `tests/test_twin_model_bricks_js.py` (node)

**Interfaces:**
- Consumes: the layout and decoded chunks (Task 4); emitter records from `bakeLights` (runtime.js:118-137), with fields from `resolveEmitters` (live/emitters.js:235-267): `shape`, `position`, `range` (ft), `aim`, `cone_deg`, `softness`, `size_ft`, `rotation_deg`, `width_in`, `output_lm`, `output_fraction`. Legacy markers become one point emitter at `at` with `range`.
- Produces:
  - `emitterTable(lights, freshIds) -> [{id:'<device>#<i>', device, index, shape:0 point|1 spot|2 rect|3 line, position, range, axis, cosOuter, cosInner, halfSize:[w,h], rotation:Quaternion, outputScale}]`. Only fresh lights with a `grid`; palette lines are never included.
  - Decoded chunks come from the async `decodeGridChunk` (await it). Block cell coordinates: `block.toLocal` maps world metres to cell space with centres at i+0.5. For yard blocks the z it returns is worldY/spacing, so subtract the bilinearly interpolated `ground[iy*nx+ix]/spacing` to get the height cell.
  - `sampleGrid(grid, p:Vector3, emitterId) -> number|null`: trilinear over the block containing `p`, skipping 255 with renormalised weights; `null` when all 8 are invalid or there is no block.
  - `chooseEmitters(centre, table, grid, max=8) -> {ids, folded, dropped}`. Ranked by `outputScale * falloff * visibility` at the centre. Over 8: the weaker emitters of one device fold into that device's strongest (their outputScale is summed into it), then the excess is dropped.
  - `buildBrick(grid, box:Box3, ids) -> Uint8Array(5*5*5*8)`, laid out as two RGBA texels per point; null samples are filled from the nearest valid brick point, else 0.
  - `createModelLightTextures({maxBricks, maxEmitters}) -> {bricks:Data3DTexture (RGBA, UnsignedByte, LinearFilter, ClampToEdge; width 10, height 5, depth 5*maxBricks), lamps:DataTexture (RGBA Float, Nearest), writeBrick(i, data, ids, fill:THREE.Color), writeEmitter(j, record), setTint(j, linearColor), grow(maxBricks) -> new textures}`. Rows: 4 per emitter (position+range, axis+cosOuter, cosInner+shape+halfSize, linear colour x tint x outputScale) and 3 per brick (8 emitter indices, count + brick z offset, fill rgb).
  - `fillFor(manifest, atlasRoomIndex, tints) -> THREE.Color`: the sum over lights of `fill[atlasRoomIndex] * tint`, matching `directTerm`'s `lmFill` (lightmap_material.js:249-268).

- [ ] **Step 1: Write the failing tests:**
  - `test_sample_grid_skips_invalid`: one corner at 255 and the rest at 254 gives 1.0; all corners at 255 gives null.
  - `test_choose_emitters_folds_then_drops`: 6 emitters of one device plus 4 single lamps fold to at most 8, with `folded > 0` and output conserved.
  - `test_brick_layout`: point (2,2,2) emitter 5 sits at texel (5, 2, 2) channel 1.
  - `test_palette_line_excluded`.
  - `test_fill_matches_lightmap_sum`.
  - `test_textures_grow_preserves_bricks`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: pass.
- [ ] **Step 5:** Claude commits: `feat(twin): per-copy visibility bricks and model light textures`.

### Task 7: Placed-model shader patch

**Files:**
- Create: `static/twin/bake/model_light_material.js`
- Modify: `tests/test_twin_texture_units_live.py:49-52` (add `SAMPLER_3D`)
- Test: `tests/test_twin_model_light_live.py` (Chromium, bare scene)

**Interfaces:**
- Consumes: the Task 6 textures; the hook pattern of `patchLightmaps` (lightmap_material.js:269-353): `before = material.userData.mvBefore || material.onBeforeCompile`, save the original key before patching, `Object.assign(shader.uniforms, shared)`, inject after `#include <lights_fragment_end>`, `RE_Direct` with an `IncidentLight`, `RE_IndirectDiffuse` for fill. The falloff is the lightmaps' `cutoff/max(d², .01)` with `cutoff = (1-(d/r)^4)²` (lightmap_material.js:158-170).
- Produces:
  - `patchModelLighting(material, shared:{mvBricks, mvLamps, mvSize}) -> material` (idempotent). Cache key suffix `'|mv-1'`. It sets `material.defaultAttributeValues = {...material.defaultAttributeValues, mvBrick:[0]}` and declares `attribute float mvBrick`, passed to a flat varying.
  - The fragment loops `for (int i = 0; i < 8; i++) { if (i >= count) break; ... }`. Per emitter: the representative point (rect: clamp to the rectangle; line: clamp to the segment), the falloff, the spot cone window (`coneWindow`, fixture_terms.js:10-13), visibility from `texture(mvBricks, ...)` clamped to the brick interior, then `RE_Direct`.
  - `mvBrick == 0` adds nothing.

- [ ] **Step 1: Write the failing Chromium tests:**
  - `test_brick_lights_and_shadows`: two boxes with patched MeshStandardMaterial, one point emitter, brick visibility 254 for box A and 0 for box B. A's lit-face luminance is at least 5x B's. Setting the tint to 0 makes A match an unpatched reference within 1%.
  - `test_no_brick_matches_unpatched`.
  - `test_one_program_for_counts_1_and_8`.
  - `test_sampler_census`: a patched model program has exactly 2 samplers more than unpatched; non-model programs gain none.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Claude runs it and `tests/test_twin_texture_units_live.py` with `ANGLE=d3d11`. Expected: pass. Claude records FXC slots and transcendentals (scratchpad `roofrev\fxc_count.py`) and the program link time against an unpatched MeshStandardMaterial.
- [ ] **Step 5:** Claude commits: `feat(twin): placed-model materials read baked lamp visibility`.

### Task 8: Viewer wiring

**Files:**
- Create: `static/twin/bake/model_lighting.js`
- Modify: `static/twin/bake/runtime.js`: after `loadPages` computes `fresh` (:702-706), and in `light()` (:337-355) to forward tints; display mode only, never `inspectOnly`
- Test: `tests/test_twin_model_lighting_js.py` (node, fake meshes), `tests/test_house_twin_model_light_live.py` (Chromium, household fixture)

**Interfaces:**
- Consumes: Tasks 1 and 4-7; `snapRanges` on merged model meshes (`bakeExcluded`); `userData.modelLod` LOD copies.
- Produces:
  - `mountModelLighting(view, {manifest, layout, fresh, tints, api}) -> {update(fresh), setTint(device, linearColor), rebuild(), stop()}`.
  - It GETs the chunks of fresh lights whose `entry.gridLayout === layout.hash`, decodes them (async `decodeGridChunk`, awaited), and builds the emitter table.
  - For each placed copy (merged snap range or LOD copy) it computes world bounds, chooses emitters, writes a brick, and writes `mvBrick = brickIndex + 1` over the copy's vertex range. Merged meshes get a post-merge `mvBrick` attribute; LOD copies get a shallow per-copy geometry (Ruling 2). It then patches the copy's materials.
  - Each brick's fill is `fillFor(manifest, atlasRoom, tints)`, where `atlasRoom` comes from the room block containing the copy's bounds centre. Yard copies and copies outside any room block get no fill. Fills are rewritten on every `setTint`.
  - `rebuild()` runs on `twinrebuilt` / `twinyardrebuilt`. `stop()` disposes the textures and restores nothing else (materials keep the patch with brick 0).
  - Before any fresh chunk exists, nothing is patched.
  - Runtime: `light()` also calls `models?.setTint(device, tint)` with the same `tint` it writes to `lmTints` (0 when the mode hides lights, runtime.js:321).

- [ ] **Step 1: Write the failing node tests:**
  - `test_bricks_assigned_per_copy_range`: two copies in one merged mesh get different `mvBrick` values over their own ranges.
  - `test_lod_copy_gets_own_geometry`.
  - `test_stale_light_not_in_table`.
  - `test_no_fresh_grid_patches_nothing`.
- [ ] **Step 2: Write the failing Chromium scenarios** on the household fixture after a bake, at night, Lights mode:
  - `scenario_model_lit_by_room_lamp`: the luminance of a model under a fresh lamp rises by 3x or more against the lamp off.
  - `scenario_model_next_room_stays_dark`: a model in the adjacent room changes by under 10% when that lamp toggles.
  - `scenario_tint_follows_lamp`: dimming to 50% halves the model's lamp term within 10%, and the wall changes by the same ratio.
  - `scenario_no_bake_no_new_programs`: on a house without a grid, the program count equals main's for the same view.
  - `scenario_moved_item_keeps_other_lamps_fresh`: moving an item and saving leaves lamps out of range fresh.
- [ ] **Step 3:** Run. Expected: FAIL.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Claude runs the node test, the Chromium scenarios, `tests/test_twin_bake_runtime_js.py`, `tests/test_house_twin_real_lights_live.py`, `tests/test_house_twin_energy_live.py` and `tests/test_twin_texture_units_live.py`. Expected: pass, apart from the known main reds listed in the v2.499.986 capabilities entry.
- [ ] **Step 6:** Claude commits: `feat(twin): placed models lit by baked lamps through the grid`.

### Task 9: Grid debug view and bake stats

**Files:**
- Create: `static/twin/bake/grid_debug.js`
- Modify: `static/twin/twin_view.js` (mount next to `mountFrameMeter`, :2040-2041, when `?grid=1`), the editor status text in `static/twin/bake/runtime.js:303-311`
- Test: `tests/test_twin_grid_debug_js.py` (node)

**Interfaces:**
- Produces:
  - `mountGridDebug(view, modelLighting) -> {setLamp(device), stop()}`. A `THREE.Points` of the valid grid points in the chosen lamp's range, coloured black to white by visibility, with invalid points red. A small select lists the lamps. Layer 31, so it is excluded from picking and the bake.
  - The editor status after a bake reads `Grid n points, x KB` plus `k models folded or dropped lamps` when k > 0.

- [ ] **Step 1: Write the failing test** `test_debug_points_colours`: three points with values 0, 254 and 255 get colours black, white and red.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: pass.
- [ ] **Step 5:** Claude commits: `feat(twin): grid debug view and bake stats`.

### Task 10: Measure, look, land (Claude)

- [ ] **Step 1:** Report numbers before any images, on the owner's export (`C:\Users\ffejn\Downloads\Current house.chauffeur-house.json`, passed by path only), ANGLE D3D11, High:
  - FXC slots and transcendentals of the model patch;
  - link time;
  - program count across a mode cycle;
  - samplers per model program (16 or under);
  - draw calls unchanged;
  - full-bake and one-lamp rebake time against main;
  - grid points and bytes;
  - model fragment cost at High and Low.
- [ ] **Step 2:** Capture the six look checks from the spec, at night, before and after, and send them to the owner.
- [ ] **Step 3:** Land under the AGENTS.md contract:
  1. merge main;
  2. run the gate tests from Tasks 1-9;
  3. `python chauffeur/tools/bump_version.py`;
  4. add the capabilities entry (including the occluder-hash, LOD-attribute and fresh-only rulings);
  5. fast-forward main and push;
  6. remove both worktrees and branches.
- [ ] **Step 4:** Update the memory files `models-in-bake.md` and `bake-in-editor.md`.
