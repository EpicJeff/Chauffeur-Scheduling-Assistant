# Editor slice 7: a material slot on every surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every surface (each wall face, each room floor and ceiling, each roof plane, each yard piece and its parts, each pool part and sub-shape, each opening's frame and panel) has its own slot row that defaults to the house material, shows what it inherits, and carries its own tint and UV offset; changing one surface's material rebakes only what that surface affects.

**Architecture:** Overrides only: a house with no override draws and bakes exactly as today. The plan stores a surface's override as a slot ref `{id?, color?, uv?}` on the surface (the existing fields where they exist; new fields for roof planes, pool ledges and steps, and the yard's house-wide roles). The generator resolves every surface through one inheritance chain and keys material instances so identical resolved materials share one batch. The editor builds every row through slice 6's `slot_row.js`. The bake's atlas key stops depending on material choices; a surface's material change invalidates only the lightmap charts it owns and the lights that reach them, through the existing reach machinery.

**Tech Stack:** FastAPI services (`chauffeur/services/twin_model_ops.py`, `twin_site_shapes.py`, `twin_model_roofs.py`), plain ES modules under `chauffeur/static/twin/` (generator, roof, pool features, library, bake), the editor, three r187, node tests, Chromium live tests.

**Spec:** `docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md`, "Slice 7: a material slot on every surface". Recon (current state, with file:line): `.superpowers/sdd/2026-11-19-editor-slice7-surface-slots/recon.md`. Slice 6 (v2.499.943) is shipped: the slot row, Library selection and assignment.

## Global Constraints

- Work in `E:\repositories\Chauffeur-editor-slice7` only. Never edit `E:\repositories\Chauffeur`. Never touch `chauffeur/data`. Never open `*_api_key.txt`.
- Do not commit, do not bump `chauffeur/config.yaml`. Leave changes in the working tree and write the report file.
- Do not launch Chromium, Playwright or any browser; never use the user's browser.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Run the named tests and neighbours, then **every** node test touching the editor or the twin view (grep `tests/test_*_js.py` for `static/twin/editor/`, `house_editor.html`, `twin_editor_dom`, `from test_twin_drag_js`, `twin_view.js`), and every bake test (`tests/test_twin_bake*`, `test_twin_lightmap*`, `test_twin_reach*`); compare failures with main in a detached baseline outside the repo folder. Node tests must also run over the real household fixture.
- **A house with no override is identical to today**: same generated geometry and UVs, same material instances and batches, same draw calls, same bake pages. Assert it on the real household (geometry hash, draw-call census, atlas layout) before and after.
- **Never remove anything a person can do.** Every slot site from slice 6 keeps its row and operation; the "This floor / The whole building" drop scopes, "Clear for this floor / the building", the drop menu at the drop point (owner ruling 8) and the House materials dialog stay.
- **Material identity, tint, bake role and UV-offset rules from the material library arc stay**, extended as ruled below: a surface's override never changes its bake role (a wall stays a wall); tint is the ref's `color`; the material-level "Random UV offset per surface" stays the default when a surface sets no offset.
- No new texture sampler in any material; no shader program change from overrides (overrides are material instances and UVs, not defines). No browser dialogs. Rebuild Tailwind after template class changes. Every new route gets an auth rule. The `house_design` agent tool schema is not changed.

## Rulings (Claude's calls within the spec and the owner's answers of 2026-11-19)

1. **Slot ref** everywhere: `{id?, color?, uv?: {u, v, rot}}`. `id` absent means "inherit the material" while still allowing a tint or offset of the inherited one. `u`, `v` are offsets in texture repeats (0..1, wrapped), `rot` is 0, 90, 180 or 270 degrees. A ref with nothing set is stored as no ref.
2. **Surfaces and their storage** (existing fields kept; new ones added):
   - Wall face: `wall.faces.left|right` (exists).
   - Room floor / ceiling / walls: `room.floor_material`, `room.ceiling_material`, `room.wall_material` (exist).
   - **Roof plane (new):** `roof.plane_materials[<edgeIndex>]`, keyed by the index of the roof area edge whose slope the plane belongs to (the same edges `twin_model_roofs.py` `_rectangle_edges` reads); `roof.material` stays the whole roof's override and the planes inherit it. The renderer labels each generated roof triangle with its section and the area edge it slopes from (port `_rectangle_edges`' side mapping to `twin_roof.js`, tested against the Python on the household's roofs). Coplanar faces of different sections take the material of the plane they belong to, not the lower section index, when the two differ.
   - Dormer: `dormer.material` (exists).
   - Openings and items: the existing parts (`door`, `window_frame`, `casing`, `pane`, `garage_door`, stair, porch, counter, vanity and shower parts); "frame and panel as two slots" is the existing frame/door split.
   - Yard: hardscape `surface|edging|joint`, fence `boards|posts|rails`, pad edge `face|cap|riser|tread|rail`, beds, edges, fire pits (exist). Pool `coping|interior|waterline|water` (exist); spa (exists); **ledge and steps (new):** `pool.features[k].materials.{interior, coping}` allowed for ledges and steps, defaulting to the pool's own slots.
3. **Inheritance and the empty slot.** One resolver (`resolveSurfaceMaterial(plan, surface) -> {ref, source}`) used by the generator and the editor, chain: surface override, then room (for a wall face, the facing room's `wall_material`), then level, then building, then house-wide (`plan.materials`), then the kit default. An empty slot shows "House default: <name>" (or "From this floor: <name>", "From the room: <name>"), greyed (`aria-disabled` styling on the text only; the row stays usable). Clear returns to it.
4. **Yard house-wide roles (new):** `plan.materials.paving`, `mulch`, `patio_concrete`, `fence`, `pool_interior`, `pool_waterline`, `pool_coping` join `lawn` and `water` as site roles in House materials (server: `set_material` with `{site: true, role}` accepts them). Today's built-ins become their kit defaults, so an unset house draws exactly as today. A yard piece's Material drop-down (role) still picks which house-wide role it follows.
5. **The row** gains, for every surface: tint (exists in `slot_row.js`, now wired for card rows too) and **UV offset** (owner, 2026-11-19: per-surface): two nudge fields U and V (step .05, wrap 0..1) and a rotation choice 0/90/180/270, plus Reset offset. Applied by transforming that surface's UVs in the generator (where the material-level random offset is applied today, `twin_library.js` `offsetSurfaceUvs`), so it never changes a material instance or program. A surface with no offset uses the material's random offset if that material has it on.
6. **Batching.** Material instances key on the *resolved* material (id, revision, tier, role, tint, flags), so a face set to the same material as its building default shares the default's instance and batch (today it splits; fix). UV offsets live in geometry and never split a batch.
7. **Local rebake (owner, 2026-11-19).** The atlas key (`bake/geometry_key.js` `authoredGeometry`, `bake/atlas.js` `buildAtlas`) excludes material refs, tints and UV offsets, so a material change keeps the atlas and its pages. A changed surface marks its own charts and the lights whose reach includes those charts dirty (`bake/reach.js`, `runtime.js` `materialsChanged` already does this for Library revision edits; generalise it to a surface's resolved-material change, including a house-wide role change that reaches many surfaces). The bake role never changes, so baked shadowmask and occlusion stay valid; only albedo-dependent bounce terms rebake. Geometry edits keep invalidating as today.
8. **Many overrides on the Pi (spec: "the plan must measure").** Task 5 measures the real household with 40 distinct wall-face, floor and roof-plane overrides on the low tier: draw calls and median frame time against no overrides, reported in the slice entry. No cap is added.

## Review Focus

1. A house with no override renders, batches and bakes identically to main (household geometry hash, draw-call census and atlas layout equal).
2. Setting a wall face to the same material as its building default adds no draw call.
3. Changing one wall's material leaves the atlas key and every untouched page valid and rebakes only the charts and lights that reach that wall; changing a house-wide role rebakes the surfaces that inherit it.
4. A roof with four planes can carry four materials without a seam gap or z-fighting where sections meet, and the Python and JS plane-to-edge mapping agree on every household roof.
5. A UV offset on one surface moves only that surface's texture, survives undo/redo and save/load, and never compiles a new program.

---

### Task 1: Data model and server operations

**Files:**
- Modify: `chauffeur/services/twin_model_ops.py` (`_material`: roof `plane` target, the `uv` and id-less refs of ruling 1, site roles of ruling 4), `chauffeur/services/twin_site_shapes.py` (`SLOTS` for ledge and steps; `pool_feature` materials for ledge and steps), `chauffeur/services/twin_model_roofs.py` (keep `plane_materials` through `to_sections`; expose the edge index per section side), the plan schema/normaliser where refs are validated
- Test: `chauffeur/tests/test_twin_surface_slots_ops.py` (new: every new target and ref shape round-trips through the ops, validation rejects bad `uv` / roles / edge indexes, an unset house's plan is byte-identical after normalisation, undo/redo carries the refs)

- [ ] Failing tests, run, implement, pass.

### Task 2: One resolver, roof planes, ledges and steps, UV offsets and batching in the generator

**Files:**
- Create: `chauffeur/static/twin/surface_material.js` (`resolveSurfaceMaterial`)
- Modify: `chauffeur/static/twin/twin_generator.js` (`mat()` through the resolver; instance keys of ruling 6; roof per-plane materials), `chauffeur/static/twin/twin_roof.js` (plane labels and the edge mapping), `chauffeur/static/twin/pool_features.js` (ledge and step materials), `chauffeur/static/twin/twin_library.js` (per-surface UV offset beside `offsetSurfaceUvs`), `chauffeur/static/twin/twin_yard.js` (yard house-wide roles)
- Test: `chauffeur/tests/test_twin_surface_material_js.py` (new: resolver chain and sources; the real household with no overrides: geometry hash, material instance keys and the draw-call census equal to main's; a face set to its default adds no batch; four roof planes, four materials, no gaps (vertex coverage) and the JS/Python edge mapping agreement on every household roof; ledge/step materials; UV offset moves only its surface's UVs; program keys unchanged); neighbours `test_twin_yard_parts_draw_calls_js.py`, `test_twin_untouched_house_js.py`, `test_twin_uv_offset_js.py`, roof and pool tests

- [ ] Failing tests, run, implement, pass.

### Task 3: Local rebake

**Files:**
- Modify: `chauffeur/static/twin/bake/geometry_key.js`, `bake/atlas.js`, `bake/reach.js`, `bake/runtime.js` (ruling 7)
- Test: extend `tests/test_twin_bake_fingerprint_js.py` (material, tint and UV changes keep the atlas key; geometry changes still change it), `tests/test_twin_reach*` (a surface's material change dirties exactly its charts and reaching lights; a house-wide role change dirties every inheriting surface's charts), a runtime test that a stored bake stays valid for untouched pages after one wall's change

- [ ] Failing tests, run, implement, pass.

### Task 4: Every surface's row in the editor

**Files:**
- Modify: `chauffeur/static/twin/editor/slot_row.js` (the UV offset control; greyed inherited text), `editor/library.js` `materialLines` (resolver sources; roof plane rows; tint and offset for card rows), `editor/cards.js`, `editor/site_shape_shelf.js` (ledge and steps rows), `editor/house_materials.js` (yard house-wide roles), `editor/editor.css`, the template if needed
- Test: extend `tests/test_twin_slot_row_js.py`, `test_twin_item_slot_rows_js.py`, `test_twin_house_materials_panel_js.py`, `test_twin_editor_shell_js.py`; new card tests for roof plane rows (one per plane, named by the plane's side, e.g. "Front slope"), ledge/step rows, the "House default: X" text for each inheritance source, tint and offset payloads on card rows; the real household renders every row without throwing

- [ ] Failing tests, run, implement, pass. Rebuild Tailwind if classes change.

### Task 5: Browser checks and the Pi measurement (Claude)

- [ ] New `tests/test_twin_surface_slots_live.py`: one wall face, one roof plane and one ledge get their own materials and show them; Clear returns each to "House default"; a UV offset visibly shifts one face's texture; changing a house-wide role recolours every surface without an override; one wall's change rebakes only its pages (count pages requested); no new programs across all of it.
- [ ] Measure on the low tier: the real household with 40 distinct overrides vs none: draw calls and median frame time (frame cap off), reported in the slice entry.
- [ ] The editor browser suites stay green (main suite in its own order, steps, picking, precision, edit-fast, scene and layers, library assign, glass slots, porch foundation; t15 matching main's five known failures).
