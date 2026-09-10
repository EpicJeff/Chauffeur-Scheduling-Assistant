# The house earns its detail

**Written:** 2026-09-10
**Status:** design, approved to plan
**Arc:** the second of four. Batching (DONE, v2.474.0–v2.477.3), then THIS, then the
shell/occlusion law, then the parametric house generator.

---

## 1. Why, and why now

The reference image the user set as the bar (an offline-rendered isometric kitchen)
reads as real for three reasons the fridge spike isolated and proved on 2026-09-10:

1. **No edge is sharp.** Every box in the reference carries a ~1mm chamfer that
   catches a highlight line. Our scene: 254 box-helper call sites with perfect 90°
   edges against 55 rounded ones — ~82% of box props have an edge nothing in the
   physical world has.
2. **Curved forms are lathes and sweeps, not boxes.** Jars, plates, knobs, feet,
   kettles are spun profiles; handles, faucets, lamp arms are tubes along curves.
   Current uses in `house.js`: `LatheGeometry` 0, `TubeGeometry` 0,
   `CatmullRomCurve3` 0 — all three sit unused in the vendored three bundle.
3. **Light has occlusion.** Corners, contacts and recesses darken. We have zero AO
   of any kind; the open-items doc noticed the symptom ("interior walls have no
   baked gradient") without the cause.

The spike (scratchpad, four variants, identical rig ported from house.js) measured
the fixes: a direct 44-triangle chamfered-box BufferGeometry **beat `roundedGeo` on
every axis** (fewer triangles than the ExtrudeGeometry it replaces, faster to
build, chamfers all 12 edges instead of 4); the lathe detail kit added 18 props for
+2,868 triangles; a vertex-AO bake over 27 props plus subdivided walls ran ~50ms
once at build. Detail costs draw calls, not triangles — which is why the batching
arc ran first. The budget now exists: exterior 1,134 / kitchen 363 / living 682 /
mudroom 373 / garage 526 in-frustum meshes at high tier.

**Scope ruling (user, 2026-09-10): technique + detail parts.** Props may gain small
authored detail parts where the reference demands them — hinges, feet, trim, knobs,
gaskets, pulls. Nothing is removed, nothing moves, no new furniture. The style
bible's density law governs: furnished, not sprinkled.

**Shape ruling (user, 2026-09-10): kit first, then room passes.** Invisible
infrastructure lands first with no-regression proof; then one visible pass per
room, screenshots to the user after each; lighting last.

**Lighting ruling (user, 2026-09-10): this arc owns the parked lighting work** —
the studio pipeline's missing last step.

## 2. What this pass is not

- Not a composition pass: no prop moves, none is removed, no furniture is added.
  The detail-parts licence covers parts OF existing props only.
- Not a re-batching: the draw-call wins are guarded, not renegotiated (§6).
- Not the shell arc: walls, roofs, occlusion and cameras are arc 3. Exterior work
  here upgrades surfaces and props (and cars), not architecture.
- Not device verification. Everything lands desktop-judged like the rest of the
  house arc; the Pi pass stays owed and is named in every acceptance as the
  backstop.
- `static/kitchen.js` stays untouched (legacy twin awaiting H4).

## 3. The kit (slices K1–K5)

All of it lands in `chauffeur/static/house.js` (strict ES5), inside the existing
helper layer, so the 254 call sites upgrade without site edits. Every geometry goes
through `cgeo` (shared, keyed) and every material through `mat()` (cached,
zone-aware) — the batching laws L1–L5 keep applying to everything the kit builds.

### K1 — the chamfer, inside the helpers

A direct BufferGeometry chamfered box: 6 faces, 12 one-segment chamfer strips, 8
corner triangles, 44 triangles, position-averaged smooth normals on the strips so
the chamfer SHADES as a fillet (the spike's flat-facet version read as white
triangles; the smoothed version reads as a highlight line — that fix ships, not the
first draft). Per-face box UVs preserved so existing canvas maps keep working.

Integration:

- `box(w, h, d, c, x, y, z, group, opts)` gains a default micro-chamfer at
  `NICE` tiers (DETAIL ≥ 2): `ch = min(0.022, w/2·0.45, h/2·0.45, d/2·0.45)`,
  overridable via `opts.ch` (0 forces sharp — the section plates, floor slabs and
  wall fabric SET 0: architecture keeps its crisp poche edges, props get the
  chamfer; the plan enumerates the opt-outs). Low tier: plain `BoxGeometry`
  unchanged.
- `cgeo` key gains the chamfer: `'b|w|h|d|ch'`. Sharing and instancing survive.
- `rbox(...)` redirects to the chamfer generator with `ch = r` (its 39 call sites
  keep their authored radii). `roundedGeo` retires unless a prop demonstrably
  needs multi-segment fillets — the spike showed the fridge body, the roundest
  prop in the house, reads better chamfered. If all 11 direct `roundedGeo` uses
  convert cleanly, the function is deleted; the plan verifies per site.
- `finish()`, zone uniqueness (`inZoneGroup`), and `userData` conventions
  untouched.

### K2 — lathe and sweep kits, with a profile library

```js
lathe(profileKey | points, seg, mat…)   // LatheGeometry, cgeo-cached by key
sweep(points, r, mat…)                  // TubeGeometry on CatmullRomCurve3
```

A named profile library so room passes author detail by vocabulary, not by
coordinates: `jar, lid, bowl, plate, cup, vase, knob, foot, hinge, pull, finial,
shade`. Each profile is an array of [x, y] pairs at unit scale, drawn to the style
bible's silhouette rules; instances scale at the mesh (the unit-canonical lesson
from batching L3 applied from birth). Segment counts tier: high 16–18, medium
10–12; low tier draws lathe props as the cheapest capsule/cylinder stand-in or
skips the part where the prop already exists without it (a fridge without hinge
caps is still a fridge — parts degrade, props never vanish).

### K3 — the physical materials tier

`mat()` grows a finish vocabulary, high tier (PBR) only, falling through the
existing ladder untouched below:

- `enamel` — clearcoat 1.0, clearcoatRoughness ~0.08 (fridge doors, range, retro
  appliances)
- `glassy` — transmission ~0.9, ior 1.45–1.5, thickness authored per prop (jars,
  pantry glass, pendants)
- `ceramic` — clearcoat 0.6–0.85, low roughness (plates, bowls, pot glaze)
- `brassM` / existing STEEL/CHROME stay Standard (already correct)

Implemented as `opts.finish` inside `makeMat` minting `MeshPhysicalMaterial` when
PBR; the cache key gains the finish token. **Calibration is part of the slice**:
the spike's clearcoat blew highlights under the linear tone mapping — values are
tuned against the real rig with probe screenshots, not copied from the spike.
Transparent (`glassy`) materials stay un-merged and un-instanced by the existing
batching guards; the plan budgets their draw cost per room.

### K4 — the ambient-occlusion bake

Build-time vertex AO, the spike's method hardened: hemisphere directions (10–12)
marched against a per-room list of occluder AABBs (walls, floors, counters, the
big masses — authored per room in the plan, not derived), written to a `color`
attribute; `vertexColors = true` on the receiving materials. Runs once at build
(~50ms scene-wide at the spike's density; L7's honest buildMs guard from the
batching arc watches it), zero per-frame cost, high+medium tiers; low skips.

Where the bake needs vertices it doesn't have (big flat walls/floors), surfaces
get modest subdivision — bounded by the budget guard, and only on fabric that the
batching merge owns (merged fabric bakes fine: the bake runs before merge in build
order, or operates on merged output — the plan fixes the order; the invariant is
AO PER VERTEX ON STATIC FABRIC, never per frame).

Corner/contact darkening on walls ALSO lands as baked canvas gradients where the
texture already exists (the floor-pool idiom) so the low tier — which skips vertex
AO — still gets the read from its textures. K4 does vertex AO; the L slice does
the gradient half.

### K5 — the contact discs join the batch

The accepted batching limit: `ysh()`/`blobShadow()` discs (low/medium tiers — the
Pi's tiers) mint per-call CircleGeometry + per-call MeshBasicMaterial, so they
never bucket. Fix: one shared unit-circle geometry via `cgeo`, materials cached by
(color, opacity, blending) with `userData.shared`, mesh-level scale — then the
yard's discs fold in `instanceYard` and interior discs share GPU state. Their
multiply blending and renderOrder semantics are preserved exactly.

**Kit acceptance (all five):** full sweep green; live tests green (the sharing
invariant and tap law must survive the new geometry paths); `--budget` within
+10% of the post-batching floor per view; screenshots same-or-better with the
chamfer visible as highlight lines, judged against baseline with the control-run
method (wall-clock card noise is documented); buildMs recorded before/after
(honest instrument since v2.477.3).

## 4. The room passes (R1–R5)

Order: **living → kitchen → mudroom+pantry → garage+cars → exterior.** Each pass
applies the kit by hand to that room's props: chamfer arrives free; lathe/sweep
parts and finishes are authored per prop against the style bible (S2 palette
roles, S4 accent discipline, S7 texture rules) and the reference bar. Each pass
also owns its room's punch-list items from
`docs/superpowers/plans/2026-09-09-house-open-items.md`:

- **R1 living:** built-ins stop reading as blocks (face frames, shelf lips,
  hardware); hearth tools; lamp gets a swept arm + lathe shade; plant pots lathe;
  the armchair keeps its ruled position (composition frozen) but gains piping/feet.
- **R2 kitchen:** the showcase — range hinges/rails/dials, fridge hinge caps +
  feet + badge (the spike, shipped for real), island pulls as sweeps, jars/bowls
  from the profile library on existing open shelving, faucet as a sweep, counter
  tier-consistency fix (`kWoodK` medium/high mismatch — open items).
- **R3 mudroom+pantry:** hooks as sweeps, bench feet, backpack hardware kept
  honest; pantry jars go `glassy` with brass lids (their count semantics
  untouched); paneled door gets rails/stiles relief.
- **R4 garage+cars:** **the vehicle-artist pass** — cars are the named weak point.
  Wheels with real rims/tyres (lathe), light housings, grilles, mirrors, trim
  sweeps, per-body-type silhouette fixes (minivan vs van separation — open items),
  garage clutter upgraded (tools, bins). Parametric contract preserved: everything
  still builds from the car record; body_type/color_code/seat_capacity stay the
  only inputs.
- **R5 exterior:** clapboard/shingle normal-map derivation from the existing
  canvas textures (~20 lines, height→normal), door hardware, coach lamp lathe,
  gutter/downspout sweeps, the bus-stop arm gets its lettering read fixed (open
  items), fence/gate hardware. Architecture itself waits for arc 3.

**Per-room gate:** budget re-run with a recorded ceiling (room's post-kit number
+15%; new static shared-material parts fold into the existing merge, zone-owned
parts stay honestly unique); sweep green; probe screenshots of the room and its
lean-ins **sent to the user** before the next room begins. The user can redirect
between rooms; absent a redirect the sequence continues.

## 5. The lighting slice (L, last)

The studio pipeline's missing lighting artist, plus what AO exposes:

- **Sun rake:** move the sun off the near-frontal axis (~15° today) far enough
  that form shows, re-aiming `SUN_OFF` and re-verifying every room's shadow box
  (`aimShadow` table) — with a compensating **north-wall fill** so the kitchen's
  subject wall doesn't go dark (the reason the rake was parked).
- **Baked gradients:** walls and counters get the floor-pool treatment — vertical
  falloff and corner darkening painted into (per-run where needed) canvas
  textures, so medium/low tiers share the read that high gets from vertex AO.
- **Tier consistency:** contact language and material response documented per
  tier; the authored medium/high mismatches from the open-items doc fixed.
- Acceptance: before/after probe screenshots all five views + key lean-ins to the
  user; the light budget rule from the rig comment (fill+key ≈0.90, pools to
  ~1.05, shade ~0.40) is re-stated with the new numbers in the same comment.

## 6. Guards

- **Budget:** per-room ceilings (§4); the batching arc's numbers are the floor
  being defended. `tools/house_probe.py --budget` is the instrument; every slice
  quotes before/after.
- **Batching laws carry over verbatim:** L1 zone material uniqueness (detail parts
  on a zone prop are zone parts), L3 colour-in-material, L4/L5 merge fences, L6
  tag-only routing (new parts under a room's fabric inherit stamps), honest L7
  buildMs.
- **Tests:** full sweep before every commit; live tests must stay green untouched
  unless a slice's own assertions extend them; screenshot judgment uses the
  control-run method for wall-clock noise.
- **Versioning:** spec v2.478.0; plan v2.478.1; build lands v2.479.0+ (kit) and
  onward per slice, every commit bumped and pushed.
- **Composition freeze:** any change that would move or remove a prop is out of
  scope and returns to the user — the never-drop-functionality rule applies to
  visual furniture too.

## 7. Open questions deliberately settled here

- **Vertex AO vs texture AO:** both, split by tier (K4 + L). Not SSAO — no
  EffectComposer in the bundle, and full-screen fill is the Pi's weakest axis.
- **Chamfer default-on vs opt-in:** default-on inside `box()` at NICE tiers with
  authored opt-outs for architecture. The 82% sharp-edge figure is the argument:
  opt-in would mean 254 site edits to get the same result.
- **`roundedGeo` retirement:** intended, verified per-site in the plan.
- **Where detail parts stop:** at the style bible's density rule and the per-room
  budget ceiling. A part that neither catches light at the room camera nor
  survives the lean-in framing is not built.

## 8. Related

`docs/house_style_bible.md` (S2, S4, S5, S7 govern every authored choice);
`docs/superpowers/specs/2026-09-10-house-batching-design.md` (laws + §9 numbers);
`docs/superpowers/plans/2026-09-09-house-open-items.md` (punch list this arc
retires by room); `chauffeur/tools/house_probe.py` (the eye and the meter).
