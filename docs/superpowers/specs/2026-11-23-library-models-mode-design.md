# Library Models mode: design

Status: drafted 2026-11-23, paused for models in the bake (v2.499.995), revised against v2.499.1006 and
approved by the owner 2026-11-26. First of four projects the owner ordered: (1) Models mode,
(2) multi-model imports, (3) anchors and lights, (4) doors that open. Only (1) is designed here.

The owner's night verdict on baked model lighting (needs-you "Judge model lighting on device") is still
open. It does not block this project: model lighting reads the material live, and this project changes
only what feeds the bake's shadow key (see Constraints, Bake).

## Intent

The owner: "Materials just feel more first-class than models." Models are imported in the editor and
can only be renamed or deleted there. The Library page (`/house/library`) is materials only. The owner
wants models to be equally first-class: imported, previewed and configured on the Library page.

He also wants to re-skin downloaded models with library materials, as in Live Home 3D, where you drag a
material onto any part of an imported model: "that would make it much easier to make downloaded models
look like your furniture or items."

## Goals

1. **Models tab on the Library page.** `Materials | Models` at the top. The Models tab has:
   - a grid of model thumbnails, with filters All / Built-in / Mine and by kind;
   - a big orbit preview with the existing 6 ft scale figure;
   - a properties panel on the right.

   The page is reachable from the editor: the dock's asset bar "Edit in Library" works for models and
   opens `house/library?model=<id>`.

2. **Import on the Library page.** A model file (.glb, .gltf, .dae, .zip, .kmz) dropped or picked on the
   Models tab imports as a model through the existing chunked import routes, with the same limits and
   kinds.

   On the Materials tab, a dropped model file still extracts its materials, as today. The open tab decides.

   Import generates the detail levels right away on this page, so a model imported here never waits for
   an editor session to get its LODs.

3. **Detail levels per model.**
   - Each model keeps three percentages: full, mid and far. The defaults are 100%, 25% and 5% (today's
     `LOD_RATIOS`).
   - Full can be lowered too, for example a 1M-triangle download thinned to 300k for everyday use.
   - Changing a percentage rebuilds that level in the background on the page and uploads it.
   - The original file is always kept; full below 100% produces a generated full-level file.
   - The preview switches between the three levels, has a wireframe toggle, and shows each level's
     triangle count and file size.

4. **Rename, kind and delete are added to this page.** The editor keeps its own (import button, canvas
   drop, Rename, Delete), because nothing a person can do today is removed. Today's rules still apply:
   a kind change is blocked while the model is placed, and delete is refused or archives when placed.

5. **Size and turn fixes, per model.** These apply to every placed copy.
   - Type the real height or width (ft/in); the model scales uniformly.
   - Quarter-turn buttons fix which way the model faces.

6. **Material overrides per part, two layers (owner chose "both").**
   - **Model default.** Set in the Library. Every placed copy uses it unless overridden.
   - **Per placed copy.** Set in the editor on a selected placed model. A copy with no override of its
     own follows the model default.
   - A **part** is everything in the model that uses the same original material, as in Live Home 3D.
     Drop wood on one chair leg and every leg sharing that wood changes. *(Claude's call, matching the
     owner's reference app.)*
   - **Texture scale on a model part.** Library materials assume real-world UVs in feet
     (`texture.repeat = 1/tile_ft`). Downloaded models usually carry 0..1 UVs per object, and untextured
     SketchUp-style parts often have none, so the plain wall path would stretch grain or show one flat
     colour. *(Claude's call, after the builder check.)*
     - Each part also gets real-size box-projected UVs (in feet, matching the wall convention, scaled by
       the size fix), computed at load from positions, so every level gets the same projection.
       *(Amended 2026-11-26 by the plan: computed at load instead of stored in level files.)*
     - Each part row has a **Texture: Real size | Model's own** choice. Real size is the default for an
       override, and the only choice for parts without UVs. "Model's own" keeps the author's unwrap, for
       example a sofa with sewn seams.
     - The loader swaps the part's `uv` attribute on its merged mesh, so the material and program stay
       shared and no program variant is added.
   - **"This piece only" is NOT in this project.** *(Claude's call, after the builder check; it was
     floated in chat.)* Piece identity does not survive today's level generation, which merges nodes by
     material. Carrying it through costs draw calls per copy or a new range scheme. Revisit with
     multi-model imports, which need per-node identity anyway.
   - **Ways to apply** a library material to a part:
     - drop it on the part in the 3D preview;
     - drop it on the part's row in the properties panel;
     - pick it with the row's "Use selected" button.

     These follow the editor's slot rows (`editor/slot_row.js`): swatch, a "where it comes from" line,
     Use selected, Clear.
   - Undo/redo and reset on the Library page, like materials.
   - **In the editor:** the selected placed model's Properties shows the same part rows. An empty row
     reads "from the model".
   - **Dropping a material on a placed model in the viewport** opens the existing drop-point scope menu.
     It gains "This copy" and "The model (all copies)". The owner ruled that this menu stays (slice 4
     ruling 8).
   - **Editor undo of "The model (all copies)".** The editor records the step in its own history as a
     model-record change with its inverse, so Ctrl+Z in the editor restores the previous model default
     through the Library's model route. *(Claude's call.)*
   - **Built-in models** (PolyHaven) appear in the grid and accept overrides and size/turn fixes.
     *(Claude's call: no LOD editing for built-ins, which keep their own files.)*

## Non-goals (later projects)

- Anchors: light positions, door leaf pivots and other sockets.
- Light fixtures using models.
- Doors and windows that open.
- Splitting a multi-model file into pieces.
- Editing model geometry or UVs.
- Creating new materials from inside a model (use the Materials tab).
- Server-side LOD generation.

## Anti-goals

These would make it a failure even if it works:

- A model's look diverging from the library material it uses. Editing a material in the library must
  show on every model part that uses it.
- A copy of the model file written per override or per placed copy.
- A new shader program per placed copy. Overrides resolve to the shared library material through the
  same path walls use, so the existing program cache is reused. The first use of a material not yet in
  the house compiles once, like any material.
- Breaking today's Materials tab behaviour, including model-file drops extracting materials there.
- Losing anything a person can do in the editor today.

## Approaches (owner picked 1)

1. **Detail levels generated in the browser; overrides applied at load.**
   - The Library page reuses `model_lods.js` and the meshopt worker (`lod_worker.js`) on import and
     whenever a percentage changes, then uploads the results.
   - Overrides are small maps on the model record and on each placement. They are resolved whenever a
     view loads the model.
   - Changes are instant everywhere and shaders stay shared.
   - *Trade-off:* a level is only rebuilt while a browser tab has the Library open.
2. **Detail levels generated by the add-on.** No browser needed, but it needs a native mesh library in the
   add-on image, built per platform (ARM included). A heavier, more fragile install for an occasional
   desk task.
3. **Overrides baked into re-materialed model files.** Duplicate files, slow changes, drift from library
   edits, and it fights per-copy overrides.

**Picked:** 1. It builds on working code, keeps the install lean, makes restyling instant, and keeps the
material library the single source of every look.

## Constraints

- **Auth.** New routes get rules in `services/auth.py`:
  - reads use the tiers today's model reads use;
  - writes are PARENTS, like material writes;
  - the Library page shell stays ANYONE.
- **Graceful degradation.** Works with no Home Assistant.
- **Hand paths.** No agent-only path; no agent tool is required.
- **No browser dialogs.** Use `promptConfirm`, `promptInput` and `showGlobalAlert`.
- **Tailwind is precompiled.** Rebuild after template class changes.
- **Settings.** Any new setting goes in `services/settings_registry.py` and this page, never
  `config.html`.
- **Performance** (owner rule: report numbers before landing):
  - Overrides add no per-frame CPU work.
  - Placed models keep merge-by-material batching after overrides (merge after resolving).
  - No new sampler on any lit program.
  - Report programs before/after on the owner's house with overrides applied.
  - Report LOD rebuild time for a 300k and a 1M triangle model.
- **Bake** (revised 2026-11-26; models joined the bake in v2.499.995).
  - Placed models are not lit surfaces in the lightmap (their geometry stays `bakeExcluded`) and are
    left out of the atlas key (`bake/geometry_key.js`). They ARE shadow casters: each lamp's bake draws
    every nearby copy's **mid** detail level as an occluder (`bake/model_occluder_meshes.js`, the
    `node.levels[1]` walk), skipping parts whose material is transparent, alpha-tested, `glass` or
    `fixture`. A model's own lighting comes from the per-lamp visibility grid plus live falloff and N.L
    (`bake/model_bricks.js`, `model_lighting.js`), so it reads the material live.
  - Today the per-lamp occluder hash (`occluderHash` in `bake/model_occluders.js`) covers only each
    copy's id, asset, position, rotation, scale and `castsShadow`. This project adds three things that
    change a shadow without changing those fields, so each must enter that hash for the copies of the
    model concerned:
    1. the model's size/turn fix (`fix`), or equivalently the copy's effective transform after the fix;
    2. the mid detail level's identity: its percentage plus a revision of the generated mid file, so a
       rebuild at the same percentage from a new original still counts;
    3. per part, whether the resolved material casts a shadow (the same opacity test the occluder walk
       uses), after per-copy and model overrides resolve.
  - Only lamps whose reach includes an affected copy go stale, as today. Material colour, texture,
    texture mode (real size or model's own) and the full and far percentages stay OUT of every bake key.
  - New per-copy override fields stay out of the atlas key, as placement fields already are.
  - The editor bake and the viewer status must agree on staleness; the editor's grid check gains the same
    inputs.
- **Part identity must be stable across the original and the generated levels.** GLTFExporter keeps
  material names but may reorder.
  - The part key is the original material's name.
  - Duplicates and unnamed materials are disambiguated by first-appearance order in the original file,
    recorded once at import.
  - Generated levels must carry the key through, for example in material `userData` or `extras`.
  - Older imports whose levels lack the key regenerate them on the page.
- **Existing placements** with no overrides, no size/turn fix and default percentages render exactly
  as today. The real household fixture golden must not change.

## Data (Claude's call; the builder may refine names, not semantics)

- **Model record** (`.asset.json` for imports; one small record per built-in id) gains:
  - `lod_percent: [full, mid, far]`;
  - `fix: {height_m | width_m, turn: 0|90|180|270}`;
  - `materials: {partKey: {material: materialId, texture: 'real' | 'model'}}`;
  - `parts: [{key, name, triangles, has_uv}]`, recorded at import for the UI.
- **Placed copies** (items, site items, openings with `model`) gain an optional `model_materials` map with
  the same shape, plus `{material: 'original'}`. The resolution order is per-copy part, then model part,
  then the original material. *(Amended 2026-11-26 by the plan: fixture items and openings already use
  `materials` for finish kinds, so every placed copy uses `model_materials`.)*
- **Occluder inputs** (`occluderInputs` in `static/twin/model_parts.js`) include a member only when it
  differs from a legacy record: a non-zero turn, a height or width fix, the mid level when its percent is
  not 25 or its revision is above 1, and the per-part shadow pattern when it differs from the originals.
  Untouched and merely regenerated models therefore keep today's lamp keys, so rollout needs no rebake.
- **Server.** Validate keys against the record's `parts`, and material ids against the
  material library. Unknown keys are refused, not dropped silently. Deleting a library material that a
  model or placement uses follows the material library's existing in-use rule.

## Settled after the second builder check (2026-11-26, Claude's calls)

- **Opening models (doors, windows) are in scope.** They get the turn fix, part overrides at both layers
  and detail levels. The size fix does not apply to them (`fitOpening` stretches every opening model to
  its opening), and the Library says so on a door or window model. Their per-copy field is
  `model_materials`, because openings already carry a `materials` map of finish kinds (`pane`,
  `window_frame`). For the bake, opening copies join the per-lamp occluder hash for the three new inputs
  (fix, mid-level identity, part shadow casting), so a door-model change stales only nearby lamps and
  never forces a full atlas rebake. Their geometry already in the atlas key stays there.
- **Full below 100% is used everywhere the full level is drawn, the editor included.** The original file
  is kept only as the source for regenerating levels. Triangle counts that drive the over-300k Low
  stand-in and the import warnings read the effective full level.
- **The fix and model-default overrides apply inside `loadModel`**, so every consumer gets them: placed
  copies, openings, cars and Library thumbnails. On a car, a set turn fix replaces the longest-side
  auto-turn; with no fix the auto-turn stays. Per-copy overrides apply per placement. Cars stay outside
  the bake.
- **A copy can return a part to the original material** while the model default overrides it: the
  per-copy entry `{material: 'original'}` is valid and the server accepts it. The editor row then reads
  "original (this copy)", and Clear returns it to "from the model".

## Owner decision after the second builder check (2026-11-26)

- **"Model's own" texture size is tiles per UV square.** Each part row in "Model's own" mode has a
  `Tiles` number (default 1, positive): how many times the material repeats across the model's 0..1 UV
  square, like tiling on a material instance. It is applied when the part's swapped `uv` attribute is
  built (author UV times `tiles` times the material's `tile_ft`, so the shared `repeat = 1/tile_ft`
  yields exactly `tiles` repeats). No per-part material or program. When the library material's tile
  size changes, the attribute is rebuilt on the next load so the part keeps `tiles` repeats; colour,
  texture and roughness edits show directly. Data: `materials: {partKey: {material, texture: 'real' |
  'model', tiles?}}`, `tiles` valid only with `texture: 'model'`; the server refuses it otherwise.
  `tiles` is outside every bake key.

## Left to the builder

- Exact UI layout within the page's existing three-column structure, following `docs/ui_design_guide.md`.
- Thumbnail regeneration after overrides. Recommended: re-render on change.
- How the preview highlights the part under the cursor during a drag. Recommended: tint outline.
- Rebuild queueing and progress display.
- Splitting the work into slices.

## Tests the plan must include

- Node tests over the real household fixture: resolution order; stable part keys across generated
  levels; size/turn fix; untouched placements identical.
- TestClient: the new and changed routes and their auth rules.
- Browser on the owner's house export:
  - import on the Models tab, then LOD rebuild at a changed percentage;
  - a model-default override showing on every copy;
  - a per-copy override in the editor through the drop menu;
  - a library material edit propagating to a model part;
  - real-size texture on a part with 0..1 UVs and on a part with no UVs;
  - a colour-only override (opaque to opaque) leaving every bake key unchanged;
  - a size fix, a mid-percentage change and an opaque-to-glass override each marking only the lamps
    near that model's copies stale, and a rebake clearing them.
- Node: `occluderHash` changes for each of the three new inputs and for nothing else (full/far
  percentages, colour, texture mode).
