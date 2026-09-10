# The house learns to draw in batches

**Written:** 2026-09-10
**Status:** design, approved to plan
**Arc:** the first of four. Batching, then a quality pass, then the shell/occlusion
law, then the parametric house generator (with the neighbourhood falling out of it).

---

## 1. Why

The `/house` scene is **draw-call bound, not triangle bound**, and by a wide margin.
Measured against the live app at `quality=high` on 2026-09-10, with a GL-hook probe
and a scene-graph walk:

| view | meshes in frustum | triangles |
|---|---|---|
| exterior | 3,106 | 300,728 |
| living | 1,019 | 93,638 |
| kitchen | 1,018 | 93,626 |
| mudroom | 1,175 | 133,220 |
| garage | 606 | 63,008 |

Roughly 97 triangles per draw call. Three hundred thousand triangles is nothing for
any GPU built this decade; three thousand draw calls is a lot of CPU work for a
Raspberry Pi. The GPU is idle while the main thread issues state changes.

The cause is visible in one number. The scene holds **3,310 meshes, 3,310 materials
and 3,310 geometries** — a perfect one-to-one-to-one. Nothing shares anything.
`mat()` (`static/house.js:650`) constructs a new `MeshStandardMaterial` on every
call, and `box()` (`:676`) constructs a new `BoxGeometry` on every call. There is no
cache, no reuse, no merging and no instancing anywhere in the file.

Where the exterior's budget goes, attributed to top-level scene groups:

```
1,759   extG            the yard, planting, roof, street, driveway, garage
  452   loose on scene
  237   one group
  ~660  spread across roughly 480 small groups
```

**The garden is about 57% of the exterior frame.** It is also the cheapest thing in
the scene to fix, because `planting()` (`:5004`) already draws from a fixed kit of
five silhouettes — `mound`, `low`, `tuft`, `column`, `ball` — varied only by
position, scale, a rotation derived arithmetically from the coordinates, and a tone
index into a six-entry leaf palette. There is no `Math.random()` in the planting
path. It is an instancing kit that has not been told it is one.

Two supporting facts:

- Frustum culling is already doing real work (kitchen: 2,186 visible meshes reduce
  to 1,018 in frustum). Nothing to add there.
- The shadow pass is effectively free, because `shadowMap.needsUpdate` is driven by
  state changes rather than the frame loop. So draw calls track meshes-in-frustum
  almost exactly.

Everything the later arcs want — denser rooms, chamfered edges, lathed props, baked
ambient occlusion, a neighbourhood, a parametric house generator — costs draw calls.
This pass is the budget that pays for them.

## 2. What this pass is, and what it is not

**It is:** a change to how meshes, materials and geometries are created and grouped.

**It is not:** a change to what the house contains, where anything sits, or how it is
lit. No prop is added, removed or moved. No colour, roughness or light value is
authored differently. Those belong to the quality pass that follows.

**Pixel policy (user ruling, 2026-09-10): same or better, not identical.** Every view
is screenshot-compared before and after each slice, and any visible difference is
judged on its merits and shown to the user rather than silently accepted. The
allowance exists because instancing could in principle disturb procedural variety —
but as noted above the planting is deterministic, so in practice we expect the
exterior to come back pixel-identical and should treat any difference as a finding to
explain, not a licence.

**Not device-verified.** Like everything from v2.463.0 onward, this lands judged on
desktop screenshots. The Pi look is still owed before H4 flips the panel's home.

## 3. The laws

These are the rules the implementation must not break. Each one exists because
something in the file already depends on the behaviour.

### L1. A zone never shares a material

`applyState` lights a zone by walking its group and writing `material.emissive`
(`static/house.js:5989`). If a zone prop shared a material with a shelf prop,
lighting the fridge would light the shelf. Therefore `mat()` must return a **fresh,
uncached** material whenever the target group is, or sits beneath, a `zoneGroup`
(`:1562`, which stamps `userData.zone`). Every geometry helper already receives its
target group, so this check costs nothing.

The same rule protects `zoneExtra` — the index of meshes that answer to a zone but
hang outside its group, such as the mudroom's garage door.

### L2. The scenery knob is already built for sharing; do not fight it

`applyScenery` (`:5760`) classifies by **ancestor**, not by material:
`scenIsScenery()` walks up looking for `userData.scenery === true` or
`userData.zone`. It tracks a per-material count of scenery uses and zone uses, and
where a material is used by both it clones one copy for the scenery side. Its own
comment names this pass as the reason the clone arm exists:

> *"The clone arm is not dead code — it is the guard rail for the first builder who
> hoists a material into a variable and reuses it, which is a one-line change nobody
> would think to flag."*

So a material cache is safe by construction. The implementation must not add a
parallel mechanism, and must leave `_scOrig` / `_scBase` / `_scDim` bookkeeping
alone.

### L3. Colour lives in the material, never in `instanceColor`

`scenTint()` desaturates `material.color` in HSL. An `InstancedMesh` using
`instanceColor` multiplies that result per instance, which is not a per-instance
desaturation and would break the knob.

Therefore: **one `InstancedMesh` per (geometry, material) pair.** For the planting
that means a canonical unit-radius sphere geometry against six leaf palettes times
four shade factors, plus blooms and tuft blades — roughly thirty instanced meshes
covering about 1,759 today. That is a 98% cut with **zero changes to
`applyScenery`**, which is worth far more than squeezing thirty draws down to three.

### L4. Never merge anything a tap must hit

`zoneAt()` (`:6521`) raycasts and walks ancestors for `userData.zone`;
`zoneFaceQuad()` projects a specific zone mesh to place the overlay card. Merging
inside a zone group would destroy both. Zones are merge-exempt, full stop.

### L5. Never merge across an independent visibility boundary

`enterRoom()` (`:6292`) hides whole groups — `westWallG`, `garageDoorG`,
`mudroomRoofG`, `livingRoofG`, `yardG`. Merging may only combine meshes that hide and
show together, which in practice means merging **within** one of those groups, never
across two.

### L6. The exterior tap router must stop reading `mesh.position`

`onTap()` currently decides "is this the house?" with
`if (!inExterior(hit) || hit.position.y > 0.2) enterRoom('kitchen')`. A merged mesh
sits at its group's origin, so `position.y` stops describing the prop and the test
silently fails — tapping the house would do nothing.

Replace the height heuristic with an explicit tag. The router already understands
`userData.room` (that is how the garage routes), so the fix is to stamp the house
fabric with a room tag rather than infer one from a coordinate. This is a small
behaviour improvement in its own right: the current rule is why two blob trees once
opened the kitchen.

### L7. Build time is part of the budget

The Pi pays for every geometry construction at boot. A cache that shares geometries
is a build-time win as well as a memory one, and the pass must not trade runtime
draw calls for a slower first paint. `--budget` reports build time so this stays
visible.

## 4. The slices

Four, in dependency order. Each is independently shippable, independently revertible,
and reports its own numbers.

### B0 — make the budget a number in the repo

Add `--budget` to `chauffeur/tools/house_probe.py`. For each requested view it
reports: total meshes, visible meshes, meshes in frustum, triangles, unique
materials, unique geometries, build time, and a per-group attribution of the
in-frustum count.

Mechanism: the probe already drives Playwright, so it intercepts the
`static/vendor/three.min.js` response and appends a wrapper around the
`WebGLRenderer` constructor that stashes the scene, camera and renderer on `window`.
Note for whoever implements it: three assigns `render` as an **instance** property,
not on the prototype, so patching `WebGLRenderer.prototype.render` is a silent no-op.
Wrap the constructor. No production code changes; the app ships no debug handle.

**Acceptance:** `python tools/house_probe.py --views all --budget` reproduces the
table in section 1 within noise, and every later slice quotes it before and after.

### B1 — the material and geometry cache

Cache inside `mat()` and the geometry helpers, keyed on the parameters that actually
distinguish a result: for materials, colour, roughness, metalness, envMapIntensity,
map identity and tier; for geometries, the constructor plus its dimensions.

Zone-owned targets always receive a fresh material (L1). Provide an explicit
`unique: true` escape hatch for anything that will be mutated per-mesh later, and use
it deliberately rather than defensively.

**Acceptance:** materials and geometries both fall from 3,310 into the low hundreds or
better (the exact floor is whatever the parameter space genuinely holds, and B0
reports it); draw calls are **expected to be roughly unchanged** — three still issues one
per mesh — and that is not a failure, it is the prerequisite for B3. Screenshots
identical. Build time down. `chfHouseScenery(0.45)` returns the same visual result and
its `clones` count is now non-zero where sharing genuinely crosses the zone boundary.

### B2 — instance the scenery kit

Add an `instanceKit` helper: collect prop instances during build, group them by
(geometry, material), and emit one `InstancedMesh` per group with a per-instance
matrix.

Apply it to the planting first — `shrub()`, `tuft()`, `planting()`, the fence
pickets, the pavers, the blob-shadow discs. These are deterministic functions of
position, so instancing changes the draw path and not the picture.

The helper is written knowing the neighbourhood will reuse it. It should take a kit
definition and a list of placements and know nothing about gardens.

**Acceptance:** exterior in-frustum meshes fall by roughly 1,700; the exterior
screenshot is pixel-identical or the difference is explained; `yardG.visible = false`
still hides the whole garden on room entry; `inYard()` still returns true for an
instanced shrub, so a tap on the planting stays inert.

### B3 — merge the static fabric

Merge same-material, same-visibility-group, non-interactive geometry into single
meshes: walls, floor slabs, roof planes, the street, the driveway, cabinetry
carcasses, baseboards, trim runs.

Merging is per hide-group (L5) and never touches a zone (L4). The exterior tap
router is converted to explicit room tags first (L6), because merging is what breaks
the current heuristic.

**Acceptance:** room views fall materially — kitchen and living are the ones to
watch; screenshots unchanged; every room still enters, every zone still leans in,
every lean-in card still lands on the right furniture; `tools/house_probe.py --views
all` plus the live Chromium suite pass.

## 5. Risks, and what catches each

| risk | catch |
|---|---|
| A zone shares a material and the glow bleeds | L1, plus a test that lights one zone and asserts no mesh outside it changed emissive |
| Merged fabric breaks the exterior tap | L6 conversion lands *before* the merge, with a test that taps the house body and asserts the kitchen is entered |
| Merged fabric breaks a lean-in card's placement | L4 keeps zones unmerged; `zoneFaceQuad` has existing coverage |
| Instanced planting stops hiding on room entry | B2 acceptance asserts it; the instanced meshes stay parented under `yardG` |
| The scenery knob double-tints a shared material | `applyScenery` already caches the authored value in `_scBase`; a k=0 round trip must restore exactly |
| Build time regresses on the Pi | `--budget` reports it every slice; a regression fails the slice |
| A screenshot changes and nobody notices | every slice diffs all five views and the notable lean-ins |

The sweep is known flaky under load (two consecutive runs each failed a different
browser-driven test, both passing in isolation, while other Chromium work ran
concurrently). Run the full sweep with nothing else driving a browser, and treat a
single failure as a re-run before treating it as a regression.

## 6. What this unlocks

Named so the pass is not judged on its own screenshots, which by design look the
same:

- **The quality pass** — chamfered edges on the ~82% of box props that are currently
  perfectly sharp, a lathe kit, swept tube handles, `MeshPhysicalMaterial`, and baked
  ambient occlusion. The fridge spike measured detail at 18 extra props for +2,868
  triangles but draw calls 15 → 86. Detail costs draw calls. This pass is what makes
  that affordable.
- **The shell and occlusion law** — a full exterior shell plus ghost-edge fabric adds
  geometry the current budget cannot carry.
- **The parametric house generator and the neighbourhood** — both are `instanceKit`
  with different placement lists.

## 7. Out of scope

- Any visual change. That is the next arc.
- `static/kitchen.js`. It is 1,433 lines against house.js's 6,648 and the two have
  diverged by roughly 5,700 lines; the "frozen twin" is now a legacy page awaiting
  H4's redirect. Batching lands in `house.js` only.
- Level-of-detail switching. With five fixed cameras, distance is known at build
  time; static level selection is correct and `THREE.LOD` is not needed.
- Screen-space ambient occlusion. `EffectComposer` and `SSAO` are absent from the
  vendored three build, and full-screen fill is the Pi's weakest axis.
- Any glTF or authored-mesh path. `GLTFLoader` is absent from the bundle, and the
  house's parametric behaviour — cars built from the car record, pantry jars counting
  the shopping list, backpacks counting active children — does not survive a frozen
  mesh.

## 8. Related

`docs/house_style_bible.md`, `docs/superpowers/plans/2026-09-09-house-open-items.md`
(the punch list and the lighting work this pass makes affordable),
`docs/superpowers/specs/2026-09-08-house-design.md`, `chauffeur/tools/house_probe.py`.

## 9. Results (implemented v2.474.0–v2.477.1)

Per-view in-frustum mesh counts at quality=high, baseline (v2.473.1) → final (v2.477.1):

| view | baseline | final | reduction |
|---|---|---|---|
| exterior | 3,147 | 1,134 | -64% |
| kitchen | 1,018 | 363 | -64% |
| living | ~1,411 | 682 | -52% |
| mudroom | ~575 | 373 | -35% |
| garage | ~702 | 526 | -25% |

(Three views use measured counts against true pre-merge HEAD; the plan's table had older fixture baselines: living was 1,019, mudroom 1,175, garage 606. Both numbers are reported here.)

Scene totals: meshes 3,310 → ~1,220 (-63%); unique materials 3,310 → 952 (-71%, high tier distinct looks); unique geometries 3,310 → 901 (-73%).

**Behavior changes shipped:**
- Tap on the bus at the curb is now inert (was: entered the kitchen via the deleted height heuristic in L6).
- Driveway car → garage case now guaranteed by the general mechanism (`buildCar` stamps room); no longer a special case.

**Design invariants verified:**
- Deterministic planting held: exterior pixel-identical (modulo known wall-clock card noise).
- L1 sharing invariant + tap-law tests now run live in `test_house_live.py`.
- `instanceYard` buckets by (geometry, material) identity; `ysph` normalized to canonical unit sphere per L3.

**Trade recorded by ruling (performance penalty documented):**
Per-room in-frustum **triangles** rose post-merge (kitchen 93.6k → 142.3k, +52%; living +19.5%; mudroom +17.3%; garage +5.1%) because merged meshes defeat per-object frustum culling. Accepted because the scene is draw-call bound (§1) and the triangle counts remain trivial for every target GPU. Pi device-verify pass (owed for the whole house arc) is the backstop.

The draw-budget tool (`tools/house_probe.py --budget`) reports build time, unique materials and geometries, confirming L7 (no regression under load). Scene batches via materials/geometries cached, garden instanced, fabric merged.
