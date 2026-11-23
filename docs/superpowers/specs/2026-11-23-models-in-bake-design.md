# Placed models in the bake: baked shadows and a light-visibility grid

Date: 2026-11-23. Owner: house twin. Status: design for owner approval.

## Intent

Placed models (imported furniture, library items, site furniture, door and
window models) are cut off from baked lamp light in both directions today:

- They cast no baked shadows. `loadModel` marks every placed model
  `bakeExcluded` (`static/twin/twin_library.js:527-530`), so the bake's
  occluder pass (`bake/bake_pass.js:145-158`) never sees them. A sofa under a
  lamp leaves no shadow on the floor.
- They receive no baked lamp light. The live lamp pool skips every freshly
  baked lamp (`live/real_lights.js:61-67`), and lightmaps are only applied to
  atlas surfaces. After a bake, a model in a lamp-lit room at night is lit only
  by the hemisphere light, the sky environment and the night floor. Lamps the
  bake left realtime still reach models through the live pool, but only in the
  Lights and All modes (the pool is hidden elsewhere, `real_lights.js:33-36`),
  and most pool lamps have no shadows, so a lamp in the next room lights a
  model through the wall.

The exclusion was a side effect of the v2.499.815 fix for tier-dependent atlas
keys (commit 1e66249a, the low-tier heavy stand-in), never an owner decision.

The owner's words (2026-11-23): "Do 1 and 2 so we can determine if that's good
enough. The light samples is how Unreal used to handle character lighting so it
should look ok if done right. This should come before model mode."
1 = models as shadow casters in the bake. 2 = a light-sample grid that models
read. The owner picked approach 1 below (light-visibility samples).

Success is the owner looking at their house at night and judging whether
models now sit in the baked lighting: lit by the lamps in their room with the
right falloff and colour, dark where a wall blocks a lamp, and casting baked
shadows on floors and walls. "Good enough" is the owner's call from images and
on device; this project delivers the comparison views for that call.

## How the bake works today (facts the design builds on)

- The bake runs on the main thread in the house editor, high/max tier only,
  one stale light per step (`bake/baker.js:240-343`). The editor bakes but
  never draws baked lighting (`twin_view.js:1884` `display: !editor`,
  `bake/runtime.js:519`); the viewer draws it.
- Point lamps take 16 jittered samples; each sample renders a 512 cube depth
  map of all occluders (`bake_pass.js:186-222`). Rect and line fixtures take
  16-48 samples (`bake/fixture_terms.js:34-56`).
- For a lamp entity with one emitter, pages store visibility and falloff and
  N.L are computed per pixel at draw time (`lightmap_material.js:15-19`,
  `:161-169`). For an entity with several emitters (kind 3, "sum",
  `fixture_terms.js:7`), pages store sqrt(irradiance/scale) instead
  (`bake_pass.js:54`, `lightmap_material.js:29`, `:253`).
- Bounce is one scalar per room per light slot, the "fill"
  (`bake_pass.js:352-369`), applied through `RE_IndirectDiffuse`.
- Sun and sky are not baked.
- Live lamp state (on/off, brightness, colour) is a texture write into
  `lmTints`, no rebake (`bake/runtime.js:340-354`).
- The bake is addressed by the atlas key (`baker.js:99`,
  `services/twin_bakes.py:47`). The atlas key hashes `authoredGeometry(plan)`
  (`bake/geometry_key.js:16-33`), which includes building `items`, site
  `furniture` and `planting`, and opening models. **So moving any placed model
  today gives a new atlas key and a full rebake of every lamp**, even though
  models play no part in the bake.
- The per-light key (`baker.js:11-23`) hashes `light.reach`
  (`bake/reach.js:222-238`): receiving geometry only, no occluders.
- Storage: atlas container at `/api/house/atlases/{key}`, light pages at
  `/api/house/bakes/{key}/{page}.png` (KTX2), manifest JSON capped at 1 MiB.
  Auth rows at `services/auth.py:474-482`. Page upload accepts PNG or KTX2 only
  (`services/twin_bakes.py:93`).
- Placed models are mostly merged. Building items and door/window models are
  baked into world space and merged per material per level
  (`twin_generator.js:1780-1782`, `:1809`, merge key `:78`); yard furniture the
  same (`twin_yard.js:825`, `:993`). Every copy of a chair on a level ends up in
  one mesh, which may span rooms. Only imports with LODs in the viewer on
  medium and above stay separate `THREE.LOD` objects (`twin_generator.js:1777`,
  `model_lods.js:188`).
- Objects already carry `casts_shadow` (`objects.js:212`) and
  `object_kind: 'lamp'` (`objects.js:214`).
- Multi-colour line lamps go back into the live pool even when baked
  (`real_lights.js:63`).
- Rooms are volumes: `atlas.js:58-81` `roomData` (polygon, level, floor
  offset), levels carry `elevation` and `ceiling`; the yard has the lot polygon,
  `yard_rooms` and `groundAt`.
- Imported models carry server-stored LODs (`lod1.glb` at 25%, `lod2.glb` at
  5%, `model_lods.js`).

## Goals

1. Placed models cast baked lamp shadows on lightmapped surfaces.
2. Placed models receive baked lamp light: direct light with the same falloff,
   angle, colour and live tint as the lightmaps, shadowed by walls, floors,
   ceilings and other built geometry.
3. Placed models receive their room's baked lamp fill, the same fill the walls
   around them get.
4. Live lamp changes (on/off, dim, colour) reach models with no rebake, exactly
   as they reach lightmaps.
5. Moving a model no longer rebakes the whole house. After a move and a save,
   the viewer lights the moved model correctly at once from the existing grid.
   The shadows it casts on surfaces update when the lamps near its old and new
   positions are rebaked; lamps elsewhere stay fresh.
6. Every tier that shows baked lightmaps shows baked lamp light on models.
7. The owner gets comparison images to decide "good enough".

## Non-goals

- Bounced light beyond today's per-room fill (light transport is a separate,
  bigger project; the grid built here is where its results could live later).
- Baking the sun or sky. Models keep the realtime sun with its live shadow.
- Model-on-model baked shadowing (a wardrobe blocking a lamp from a chair).
  The grid sees static built geometry only (see "Grid occluders" for why).
- Self-shadowing of a model from baked lamps (a table top shading its own
  legs). Realtime sun shadows still self-shadow.
- Baked shadows from alpha-tested or transparent parts (plant leaves, glass).
  They are excluded by the same opaque-only rule the atlas uses today.
- Drawing baked lighting in the editor. The editor keeps showing unbaked
  lighting on walls and models alike, as today.
- Changing model materials, the Library page or Models mode (next project).

## Anti-goals

- A sampler added to every lit material. The owner GPU has 16 texture units
  and water has one left (memory: twin-texture-unit-budget). Samplers added
  here go on placed-model materials only and are counted.
- A new shader variant per lamp count or per model. Compile time on ANGLE D3D11
  is the owner's top pain (memory: design-for-performance).
- Un-merging placed models. The house render is draw-call bound.
- A model darkened because it stands next to a wall or a kitchen island
  (grid points inside solid geometry reading as black).
- Bake time that grows with model triangle count at full detail.
- Models that look different between tiers for the same bake.
- A person's existing control silently stopping working (`casts_shadow`).

## Approaches considered

1. **Light-visibility sample grid (chosen by the owner).** At bake time a 3D
   grid of points fills each room and the lit parts of the yard. Each point
   stores how visible each nearby emitter is (0..1, soft), measured against the
   same jittered cube depth maps the baker already renders. At draw time a
   model computes each emitter's falloff, spot cone and angle itself and
   multiplies by the visibility interpolated at the fragment. This is the same
   split the lightmaps use, so live tints work unchanged, and it matches
   Unreal's precomputed shadowing for movable objects from stationary lights.
2. **Baked-light samples as spherical harmonics.** Each point stores lamp
   light already summed with direction. Rejected: there is no bounce to
   capture, nearby point lamps lose their sharp direction and falloff, and live
   on/off would need one SH set per lamp anyway.
3. **Live shadow maps for every lamp.** Correct shadows but a 6-face depth
   render per lamp per frame. Today only the pool area gets one live shadow;
   this cannot run on the panel. Rejected.

## Design

### A. Models as bake occluders, and the keys

- Every placed model with `casts_shadow` not false joins the occluder set of
  each lamp whose range reaches its bounds. Only its opaque meshes occlude
  (the `atlasMesh` opaque rule: not transparent, no alphaTest, not glass).
- The occluder uses the model's mid LOD (`lod1.glb`) when one exists, else its
  full mesh. The bake runs on high/max only, so the low-tier stand-in never
  enters it.
- Models stay out of the atlas (they receive no lightmap).
- **A lamp is never blocked by a model that contains it.** For each lamp, a
  model whose world bounds contain the lamp's centre is left out of that lamp's
  occluder set. This covers a bulb inside a lamp-shade model and
  `object_kind: 'lamp'` objects alike. The anchors-and-lights project can
  refine it.
- Range culling: only models whose bounds intersect a lamp's range sphere are
  rendered into that lamp's cubes.
- **Keys.** Building `items` and site `furniture` placements leave the atlas
  key and move into the per-light keys: each light's key gains an occluder hash
  of the models inside its range (asset id, LOD file the bake uses, world
  transform rounded to 1 mm and 0.1 degree, `casts_shadow`). The hash is
  computed from the plan and the import metadata (stored bounds and LOD list),
  never from loaded geometry, so it is identical on every tier. Opening models
  stay in the atlas key, because they replace the generated frame geometry that
  receives lightmaps. `planting` stays as it is (not a placed model).
  `ATLAS_VERSION` is bumped once, so the first bake after this lands redoes
  every lamp. After that, moving a model rebakes only the lamps whose range
  covered its old or new bounds.
- The lighting fingerprint (`services/twin_lighting_rev.py`) already counts
  model placement, so the editor chip turns stale on a move.

### B. The light-visibility grid

**Layout.**
- Indoors: one grid per room, filling the room polygon from floor to that
  level's ceiling, spacing 1 ft (0.3048 m). Points sit at cell centres inset
  half a spacing from the walls, so no point lies inside a wall.
- Yard: one grid over the parts of the lot that a baked yard lamp reaches,
  spacing 2 ft horizontally, from `groundAt` up to 10 ft above it, following
  the terrain.
- Points only exist where at least one baked lamp's range reaches.
- The layout is a pure function of the plan's rooms, levels, lot and the baked
  lamps' ranges, so the editor and the viewer derive the same layout.

**What each point stores.** One byte per emitter in range: visibility 0..255,
the fraction of that emitter's jittered samples that reach the point
unblocked. A lamp entity with several emitters (kind 3) gets one visibility
value per emitter, because one value cannot say which of six cans a point can
see; each sample the baker takes already belongs to one emitter. The grid's
penumbra matches the lightmap's for the same lamp.

**Grid occluders: static built geometry only.** The grid is measured against
the same occluders as today's lightmaps (walls, floors, ceilings, roofs, built
geometry), not against placed models. Reasons:
- A model's own triangles would shadow the grid points inside and around it,
  so every model would light itself as dark (classic self-shadowing).
- The grid stays independent of model placement, so moving a model never makes
  the grid stale.
This is why model-on-model shadowing is a non-goal.

**Grid key.** Each light's grid chunk is keyed by the light key without the
model occluder hash. A model move that marks a lamp's pages stale leaves its
grid chunk fresh, and the viewer keeps using it.

**Points inside solid geometry.** A point inside a built solid (a kitchen
island, a counter, a fireplace) is marked invalid at bake time and skipped by
interpolation with the remaining weights renormalised. Detection is the
builder's choice (a ray-parity test against a BVH of the static occluders is
one; `live/cone_occluder.js` already builds one).

**Computation.** On the GPU, in the baker's existing per-light step: the grid
points in that lamp's range are written to a float texture, and one pass per
jittered cube sample accumulates visibility for all points at once, into the
slot of the emitter that sample belongs to. Expected cost is small next to the
pages; the builder measures it.

**Storage.** One binary visibility chunk per baked light, published in the
light's step, under the grid key. The manifest entry records the chunk name and
the grid layout hash. Upload goes through a new route next to the pages with
its own auth rows (same tiers as pages: WALL_OR_SERVICE to read, PARENTS to
write) and its own signature and size checks. The format is a small header plus
a gzipped byte grid; the builder picks the exact layout. The manifest stays
under its 1 MiB cap because only names and hashes go in it.

### C. Model shading

Placed models stay merged per material. Shading works from data, the way the
lightmaps cope with merged batches (`lightmap_material.js:34`).

**Per-copy visibility brick.** For each placed copy, the CPU resamples the
world grid into a brick over the copy's world bounds: 5 x 5 x 5 points (the
size Unreal's per-object volume lighting used). Each point holds the visibility
of the copy's chosen emitters (up to 8). Resampling is trilinear across the
room grids, honours invalid points, and reads the grid of whichever room or
yard area contains each brick point.

**Which brick a fragment reads.** Merged geometry gets a per-vertex brick index
when the copy is merged. Copies that stay separate `THREE.LOD` objects share
geometry between copies, so they carry their brick index in a per-object
uniform instead. One program handles both: the shader adds the uniform to the
attribute, and each case leaves the other at zero.

**Two textures, on placed-model materials only.**
- `mvBricks`: one RGBA8 3D texture holding every brick, two texels per point
  for 8 emitters. Sampled with hardware trilinear filtering, clamped to each
  brick's interior.
- `mvLamps`: one float data texture read with `texelFetch`. It holds a row per
  baked emitter (position and range, falloff, spot axis and cone, shape for
  rect and line, live colour times tint) and a row per brick (its 8 emitter
  indices, the emitter count, its texture offset, and the room fill times live
  tints).
This adds two samplers to placed-model materials and none anywhere else. The
builder confirms with the sampler census that model programs on the owner's
house stay within 16.

**Emitters per copy.** Each copy takes the up-to-8 baked emitters that
contribute most at its centre (output x falloff x visibility). When more than
8 contribute, the weaker emitters of one lamp entity fold into that entity's
strongest emitter (energy kept, direction approximate) before any emitter is
dropped. Emitters past 8 after folding are dropped. The editor bake stats
report copies that folded or dropped emitters.

**The shader.** One patch on placed-model materials, through the existing
`onBeforeCompile` hook chain and with a stable `customProgramCacheKey`:
- A fixed loop of 8 with an early exit on the brick's emitter count, so one
  program serves every copy.
- Rect and line emitters use the representative-point approximation (closest
  point on the emitter, energy-normalised) instead of the lightmaps' LTC, so no
  LTC samplers are added.
- Each emitter builds an `IncidentLight` (colour x falloff x cone x
  visibility, direction to the representative point) and goes through three's
  own `RE_Direct`, so models keep their full physical BRDF, specular included.
- Room fill from the brick row goes through `RE_IndirectDiffuse`, the way the
  lightmaps add it.

**Live tints.** The CPU already holds every baked lamp's live tint (the values
written into `lmTints`). The same values are written into the `mvLamps` rows,
so anything that dims or colours a baked lamp on surfaces does the same on
models, in every mode where lightmaps show lamp light.

**No double lighting.** Only lamps that the live pool skips go through the
grid. Multi-colour line lamps, which the pool keeps (`real_lights.js:63`), stay
out of the grid. A lamp the bake left realtime stays in the pool.

**Before a bake, or with a stale grid.** Copies without a fresh grid chunk for
their lamps fall back to today's behaviour.

### D. Debugging and stats

- The bake stats line adds grid points, grid bytes, grid bake time and copies
  that folded or dropped emitters.
- A debug view in the viewer (behind the existing `?perf=1` style flag) draws
  the grid points coloured by the visibility of a chosen lamp, so a bad grid is
  visible at a glance.

## Performance budget (measured before any look review)

Reported against main on the owner's exported house, ANGLE D3D11, High:
- Model shader patch: FXC slot count and transcendental count (scratchpad
  `roofrev\fxc_count.py`), and program link time for one model material.
- Programs: no new variants beyond one per model material (the patch is in or
  out); confirm with the program count across a mode cycle.
- Samplers: census per model program; must stay at 16 or under on the owner's
  house.
- Draw calls: unchanged (no un-merging).
- Bake: full-bake time and one-lamp rebake time with models as occluders at
  mid LOD, against today's 65-75 s full bake.
- Grid: point count, bytes on disk and over the wire.
- Frame: model fragment cost at High and Low (8 emitters worst case, early
  exit).

## Look checks

Chromium captures of the owner's exported house at night, before and after,
sent to the owner:
- A model under a ceiling lamp: lit, with its baked shadow on the floor.
- A model in the room next to a lit lamp: dark (no light through the wall).
- A model against a wall and beside a counter: not darkened.
- A lamp dimmed and recoloured live: model and walls change together.
- A lamp-shade model around a bulb: the room stays lit.
- A model moved and saved: relit at once in the viewer, the rest of the bake
  still fresh.

## Constraints

- three.js r187 vendored; WebGL2; owner GPU ANGLE D3D11 with 16 texture units.
- Bake runs only in the editor, button only (memory: bake-in-editor).
- The viewer stays exact at its own atlas key; stamps feed only the editor
  chip.
- New routes get auth rows in `services/auth.py`.
- When generated receiving geometry changes, bump `BAKE_GENERATOR_VERSION`
  (not expected here; `ATLAS_VERSION` is the bump).

## Calls made without the owner (check these while reading)

1. Placed models stay merged; shading reads per-copy data from two textures
   (two samplers on model materials only) instead of per-object uniforms.
2. Items and site furniture leave the atlas key for per-light occluder hashes;
   opening models stay in the atlas key. This also ends today's full rebake on
   every model move.
3. The editor keeps not drawing baked lighting; "relit at once" is seen in the
   viewer after a save.
4. Multi-emitter lamps get one grid value per emitter, with weaker emitters of
   one entity folded together when a copy has more than 8.
5. `casts_shadow: false` keeps a model out of the bake's occluders.
6. 1 ft indoor grid, 2 ft yard grid up to 10 ft, 5 x 5 x 5 bricks, 8 emitters
   per copy.
7. The grid debug view lives in the viewer.

## Left to the builder

- The grid file format and the GPU accumulation pass.
- The inside-solid test.
- Brick allocation in the 3D texture and its growth when models are added.
- How the occluder pass loads mid-LOD geometry in the editor.
- Exact data-texture packing.
- Test design, within the repo rules: every critical path has a test that runs
  it (node for the JS modules, a Chromium check for the editor bake and the
  viewer).
