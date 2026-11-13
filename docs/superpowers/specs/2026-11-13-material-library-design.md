# Material library: design

Date: 2026-11-13. Status: draft for the user's approval.

## Why

The user can model their house's geometry closely in the twin, but the surfaces do not look like theirs (foundation, roof, interior walls, some floors, grass, hardscapes, fence), so the house does not read as their house. Today the Library is twelve vetted Poly Haven materials shipped in the add-on, with a fixed four-foot tile, a tint and nothing else. Every surface and feature can now take a Library material (material slots, v2.499.83x-.842); what is missing is a library worth choosing from and a way to make materials.

The user is a game developer with 20+ years of experience. Their real workflow: "I usually just look for textures that match what I want and then maybe tweak them in Photoshop." Their order of preference: find it on Poly Haven or a similar site first; build a material from loose textures only "when I can't find something close enough"; glTF import "if that is easy".

## Goals

1. Browse online CC0 libraries (Poly Haven and ambientCG) from inside Chauffeur, pick a material and a resolution, and add it to the household's Library.
2. Create a material from loose texture files, assigning each file to a texture slot of the material.
3. Import the material and textures carried by a `.glb` or `.gltf` file.
4. Edit any material's parameters in a dedicated editor with a snappy live preview.
5. Every material slot and every house surface override picks from this one Library.

## Non-goals

- Making textures from photos of the house. The user rejected this explicitly.
- Painting or editing texture pixels in Chauffeur. Photoshop does that; Chauffeur imports the result.
- Procedural or node-graph materials (Substance `.sbsar`, MaterialX).
- Per-surface UV editing beyond the per-material tile size, rotation and offset below.
- Selling, sharing or syncing materials between households.

## Anti-goals (would make this a failure even if it works)

- A consumer-grade "pick a colour" tool. The vocabulary is PBR: base colour, normal, roughness, metalness, AO, ORM.
- Slow feedback. The user's standing complaint is that house edits take several seconds. Parameter changes in the material editor must show in the preview within a frame or two, never through a server round trip.
- Breaking existing houses. Every saved slot and surface override keeps rendering as it does today.

## The pieces

### 1. The material asset

A material is a Library entry with this shape (stored on the server; names are the builder's to finalise):

- `id`, `name`, `source` (`builtin`, `polyhaven`, `ambientcg`, `user`, `gltf`), `licence` and `source_url` when known, `created_by`, `updated_at`.
- `based_on`: the id it was duplicated from, if any.
- `maps`: any of `base_color`, `normal`, `roughness`, `metalness`, `ao`, `orm` (glTF channel order: R occlusion, G roughness, B metalness), `height` (stored, not rendered in this version). Each is a file in the material's folder.
- `params`:
  - `tint`: a colour multiplied into the base colour (white means none);
  - `roughness` and `metalness`: multipliers applied over the maps, or flat values when there is no map;
  - `normal_scale`, and `normal_convention`: `gl` or `dx`; DX flips green at render time;
  - `ao_intensity`;
  - `tile_ft`: `[width, height]`, the real-world size of one repeat of the texture;
  - `rotation_deg`;
  - `random_offset`: a boolean; each surface gets a stable pseudo-random UV offset so long runs do not show the repeat.
- `thumbnail`: a small PNG rendered in the browser from the preview.

**The twelve shipped materials and the kit roles stay.** They are read-only Library entries (`source: builtin`). "Duplicate" makes an editable user copy. Existing slot values `{id, color?}` keep working: `color` remains a tint override on top of the material's own tint.

**Ownership.** The Library belongs to the household, not to one house, so it outlives house save and load when that ships. Parents create, edit and delete; everyone who can see the house can read.

**Editing a material updates every surface that uses it.** Downloaded materials are starting points: editing a Poly Haven material's parameters or swapping one of its maps saves it as the household's own material (copy on write, keeping `based_on`), so the downloaded original is never altered.

**Deleting a material in use** is refused with the count of places that use it, unless the person confirms. On confirm those slots and overrides return to their defaults, in one undoable house edit. Use `promptConfirm`, never a browser dialog.

### 2. Getting materials in

**Browse online.**
- A search over Poly Haven (`api.polyhaven.com`) and ambientCG (`ambientcg.com/api/v2/full_json`), both CC0.
- Search by text and category, show thumbnails, pick a resolution (1k, 2k, 4k), then Add.
- The server downloads the chosen maps, unzipping ambientCG's archives with the standard library, into the household Library. It reuses the atomic fetch-once pattern of `twin_library.ensure()`.
- Each source's map names map to our slots: Poly Haven `diff`, `nor_gl`, `rough`, `arm` and `ao`; ambientCG `Color`, `NormalGL`, `Roughness`, `Metalness` and `AmbientOcclusion`. The builder confirms against the live APIs.
- Thumbnails and search go through the server, so the page never talks to third-party hosts directly. That keeps it working under Home Assistant ingress and the add-on's content security policy, and it caches results.
- With no internet, the search says so, and the rest of the Library still works.

**Create from loose textures.**
- Make a new material, then drop in image files (PNG, JPG or WebP). Files are assigned to slots by common suffixes:
  - `_basecolor`, `_albedo`, `_diff`, `_color`;
  - `_normal`, `_nor_gl` or `_normalgl` (marked GL), `_nor_dx` or `_normaldx` (marked DX);
  - `_rough` or `_roughness`; `_metal` or `_metalness`; `_ao` or `_occlusion`;
  - `_arm` or `_orm` (packed);
  - `_height` or `_disp`.
- Any slot can be reassigned or cleared by hand, and an unmatched file asks which slot it fills.

**Import glTF.**
- Accept `.glb`, or `.gltf` with its textures. If the file has several materials, the person picks one.
- From it we take `baseColorTexture` and `baseColorFactor` (which becomes the tint), `metallicRoughnessTexture` (glTF packs it G = roughness, B = metalness) together with its roughness and metalness factors, `normalTexture` and its `scale`, and `occlusionTexture` and its `strength`.
- glTF normals are GL. Parsing reuses the vendored `GLTFLoader` in the browser, which then uploads the extracted images like loose textures.

**Upload handling.**
- Images are decoded and resized in the browser before upload, to one stored master per map with a cap of 4096 px. The server has no image library and must not gain one: `requirements.txt` stays as it is.
- The server validates the type, the size and that the image decodes as declared (by reading the PNG, JPEG or WebP header), and stores the files.
- Large uploads reuse the chunked upload path of model imports (`twin_imports` start, chunk and finish).

### 3. The Library page (all editing happens here)

A new page, for example `/house/library`, reached from the house editor and the house admin pages. It is a separate page because the user asked for it: "I would be fine if there was a separate page for the Library and you do all the editing there and the Library in the house editor is just a viewer for adding things to your house."

- **Left:** the Library grid with thumbnails, a source filter (built-in, downloaded, mine) and search. The actions are New material, Browse online, Import glTF, Duplicate and Delete.
- **Centre:** the preview, a small three.js view with:
  - a shape switch: sphere, cube, a wall-sized plane, and a ground plane;
  - a scale reference (a 6 ft figure or a ruler) so `tile_ft` reads true;
  - a light rig switch: neutral studio, and the house's day sun;
  - orbit controls.
- **Right:** the properties: each texture slot with its thumbnail, replace, clear and the GL/DX switch; then the parameters above as sliders with numeric fields; the name; and the licence.

**Snappy is a hard requirement.** Parameter changes update the preview material's uniforms and properties directly, with no shader recompile where avoidable. Persisting is debounced, a few hundred milliseconds after the last change, and never blocks the preview. Swapping a map uploads in the background while the preview already shows the local image.

**Each material change is one entry in the Library's own history,** with undo and redo on the page. That history is separate from the house's history.

### 4. The house editor's Library (a viewer)

The house editor's Library and every material slot chooser show the household Library: thumbnails, names and the source filter. They only pick. "Edit in Library" opens the Library page on that material (a new tab, or a return link back to the editor; the builder's call). When the person comes back, the editor rereads the catalogue, so new and edited materials appear without a reload.

### 5. Rendering

`kitMaterial` and `materialSlot` in `static/twin/twin_library.js` build from the material asset instead of the fixed Poly Haven filename patterns:

- **Maps:** `map` from base colour (sRGB); `normalMap` with `normalScale` (the y component negated for DX); `roughnessMap`, `metalnessMap` and `aoMap`, either as separate maps or one ORM texture shared by all three (three's standard material reads AO from R, roughness from G and metalness from B, which matches ORM).
- **Parameters:** `color` takes the tint (and a slot's `color` overrides it); `roughness` and `metalness` take the multipliers; `aoMapIntensity` takes the AO strength.
- **Tiling:** generator UVs are in feet, so `repeat` is `1/tile_ft`, together with `rotation` and the random offset. Tiling is per material, replacing the hardcoded 4 ft (8 ft for lawn). Built-ins keep exactly their current scales.
- **AO needs a second UV set** in three r187 unless it is mapped through UV0. The builder checks and keeps AO on UV0 if the generator gives no `uv1`.
- **Quality tiers keep their caps:**
  - low: base colour only, at 512 px at most;
  - medium: all maps at 1024 px at most;
  - high: all maps at 2048 px at most.
  - The server serves the stored master, and the browser downsamples once per tier and caches the result. Storing tier variants at upload instead is the builder's call.
- **Cache and share:** materials are cached by id plus a parameter hash, so twenty walls in one material are one material, which keeps draw-call batching intact. That matters because the twin is draw-call bound.
- **Live updates:** editing a material on the Library page updates open house views at their next layout or catalogue read. The editor rereads on focus.
- **Baked lighting:** if the bake depends on material colour or roughness, a material edit marks the bake stale the same way a geometry edit does. The builder checks and states which.

### 6. Argyle

Argyle can list materials and assign them through the existing slot ops, since every capability needs a hand path and these already have one. Creating materials stays a hand-only job in this version. The `house_design` schema is at 5,955 of its 6,000-character cap, so any addition there needs the existing text compressed first.

## Constraints

- Auth: every new route gets a rule in `services/auth.py`. Reads use the same tier as `/api/house/twin/library`; writes are for parents only.
- No browser dialogs; use `showGlobalAlert`, `promptConfirm` and `promptInput`.
- Page JavaScript fetches with `base() + 'api/...'`, never a root-relative URL, because of ingress.
- Tailwind is precompiled: rebuild after template class changes.
- The page works with no Home Assistant present, and online browsing degrades cleanly with no internet.
- Tests: Python and node tests per piece, at least one runtime test per entry point, and Chromium screenshots of the Library page and of a house surface wearing a user material.
- New settings, if any (for example the cap on master resolution), go in `settings_registry.py` and the Library page, never `config.html`.

## Decided by the user

- Use loose textures from Photoshop. Do not build materials from photos.
- Online libraries come first; creating a material is the fallback; glTF is welcome if it is easy.
- The editor has a preview, and updates must be snappy.
- Editing happens on a separate Library page; the house editor's Library is a viewer for adding materials to the house.

## My calls (the user can override any of these)

- The Library belongs to the household and outlives individual houses.
- Downloaded materials are copy-on-write; the original stays intact.
- Built-ins stay read-only and can be duplicated.
- Images are resized in the browser, with a 4096 px master cap, and the server stays free of image libraries.
- Tier caps are 512, 1024 and 2048 px, with low tier loading base colour only (as today).
- Height maps are stored but not rendered in this version.
- KTX2 texture compression is a later step. The vendored basis encoder makes it possible, but it adds normal-map quality tuning this version does not need.

## Left to the builder

- Route and module names, the storage layout under the data directory, and the exact JSON schema field names.
- Whether resized tier variants are stored on upload or derived in the browser.
- The exact suffix tables, checked against current Poly Haven and ambientCG file names.
- How "Edit in Library" returns to the editor.
- The order of slices, as long as each ships whole. Suggested order: material asset and rendering; Library page with preview and loose-texture create; online browse; glTF import.
