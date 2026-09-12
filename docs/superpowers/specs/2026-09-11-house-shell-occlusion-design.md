# The house closes its shell

Arc 3 of the four-arc sequence (batching -> quality -> SHELL/OCCLUSION -> parametric generator). Binding spec. The batching laws (docs/superpowers/specs/2026-09-10-house-batching-design.md) and the quality pass lifecycle law (mkTex owns textures; cgeo owns geometry; rebuild loops dispose materials only) travel with it.

## 1. Why

The house is a dollhouse with its front sawn off: the great room has no south wall, the roof stops at the cutaway, and four hand-written hide: arrays in the ROOMS registry (house.js ~:7884) plus a show-all-then-hide dance in enterRoom/goExterior decide what vanishes when a camera goes inside. Every new room means re-deriving those lists by hand, and the exterior never reads as a whole building. Option A was chosen ON RECORD (2026-09-10) and its alternative rejected: free orbit with no outer walls costs 2-3x fidelity and an outer room still hides an inner one.

## 2. What this arc is (user-ratified 2026-09-11)

- **Sealed shell:** all four walls and a full roof. The great room gains a real south wall (siding, windows, trim consistent with the R5 exterior) and the main roof completes over it. From the exterior the house is closed; the garage door stays the one openable piece.
- **Ghost edges, edges only:** fabric between the camera and its subject hides its fill and shows a prebuilt edge outline (EdgesGeometry LineSegments). No translucent fills.
- **Roofs ghost like walls** (the user's pick over dollhouse-hide): overhead roof pieces become outlines while inside, never simply vanish.
- **All tiers ghost:** low/medium/high all draw edges; one draw per ghosted piece; the Pi sees the same shell language as the desktop.
- **Zero visibility authoring for new rooms:** a fabric registry plus a half-space solver replaces the hide: arrays. A room built with the shell helpers gets correct occlusion for free.

## 3. The fabric registry

regFabric(group, opts) — one call at the build site of every shell piece. Registered pieces:

- carry n (outward unit normal, THREE.Vector3) and box (world AABB [x0,x1,y0,y1,z0,z1]); roofs use their outward upward-sloping face normal.
- become their own merge unit: mergeStatic treats each registered group exactly as it treats the current fenced hide-groups (the L5 per-group law), and the registry FEEDS the shell entries of NO_MERGE/EXT_NO_MERGE — the hand-grown shell entries (westWallG, garageDoorG, mudroomRoofG, livingRoofG, yardG) migrate into registrations; prop entries (carsG, busG, pantry jars, coach-lamp glass, ...) stay hand-fenced, they are not fabric.
- get ONE prebuilt ghost: after mergeStatic, an EdgesGeometry over the piece's merged geometry (thresholdAngle ~35 deg) as LineSegments in ONE shared LineBasicMaterial (authored dark line, depthTest on, renderOrder above fills), .visible=false, added beside the group. Built once at startup; buildMs is the guard (section 7).
- may declare mode:'hide': the piece hides entirely instead of ghosting. The YARD is the one authored hide piece (scenery, not shell — outlined trees read as noise). Everything else ghosts.

Pieces (initial registration set): great-room south wall (NEW), kitchen/great-room north wall, east wall, west wall (current westWallG), main roof south slope + north slope, mudroom roof (mudroomRoofG), living roof (livingRoofG), garage walls + gabled roof, garage door (garageDoorG — registered; its openable dollhouse trick unchanged, the solver may also ghost it), yard (mode 'hide').

Granularity law: a piece is the unit that ghosts together. Walls split per run (a whole perimeter is never one piece), roofs per slope. A future room needing finer ghosting registers finer pieces — the solver does not change.

## 4. The solver

solveShell(subject) runs on camera SETTLE only — enterRoom, goExterior, frameZone (lean-in), never per frame; render-on-demand law intact.

- Subject: the active room's AABB (rooms register their AABB alongside their camera in roomsReg), or the focused zone's quad centre while leaned in.
- Verdict per registered piece: GHOST when dot(n, cam - p) > 0 (camera on the outward side) AND dot(n, subject - p) < 0 (subject on the inner side), p = the piece's AABB centre; plus the piece's AABB must overlap the expanded AABB of the camera-to-subject segment (skips far-away fabric that faces the wrong way, e.g. the garage's far wall while in the living room). SOLID otherwise. mode:'hide' pieces hide under exactly the conditions they would ghost.
- Exterior: every piece SOLID (sealed house). Solve against the DESTINATION at tween start — you fly through an outline, never a wall.
- Applying a verdict: fills .visible, ghost lines .visible, then webgl.shadowDirty() once per solve (visibility changes what the depth pass draws — the existing applyState law). applyState's own face/prop logic is untouched; the solver owns SHELL visibility only.
- The four hide: arrays, the show-all loops in enterRoom/goExterior, and their per-room knowledge are DELETED. ROOMS keeps camera homes plus the new room AABBs.

## 5. Tap law (unchanged, one addition)

Tap routing stays stamped-tag-only. The new south wall stamps room:kitchen (it fronts the great room) so the exterior tap-to-enter flow survives the closed front. A GHOSTED piece must NOT capture taps aimed at the room behind it: ghost lines carry no tags, and hidden fills are unhittable by construction — no special casing. Bus/curb stays inert; zone taps unchanged.

## 6. New fabric (the seal + the face) — REVISED 2026-09-11 per user redirect

The street face must read as an ACTUAL HOUSE from the curb: a front elevation that makes sense, a roofline that makes sense, and a front entrance — which this house has never had (the existing "front door" is decorative and lives on the WEST wall, house.js ~:1386; the mudroom's functional street door is a side entry).

**South wall (the street face), composed as an elevation, not a slab:**
- OFFSET FRONT DOOR under a COVERED GABLED PORCH (user-ratified): two posts, small gable roof echoing the garage gable's pitch family, stoop + one step, coach-lamp idiom beside the door (a second lamp instance; the garage's stays). Door reuses the decorative-door casing/panel idiom (~:2102) — decorative like the west one, NO new zone; it stamps room:kitchen like the wall it lives in.
- Window rhythm: a living-side window pair and a kitchen-side window with ALIGNED HEADS, panes per the existing pane idiom; siding = the shared clapboard-mapped material (R5 normal map rides along); trim/kick consistent with R5 hardware.
- Interior face: plaster + baseboard per the great-room idiom, wall-gradient map applied (T11 law: mapped materials, applyScenery exemption).
- The porch (posts + gable) belongs to the south_wall fabric GROUP — it ghosts with the wall as one piece.

**Roofline coherence law:** one pitch family across the whole silhouette. Exterior walls rise to the roof — gable ends get infill panels closing the wedge between interior wall height (5.6) and the eave/ridge line (~7.0); no daylight wedges under any slope (finding inherited from the first T4 attempt). Main roof both slopes complete over the great room; porch gable and garage gable share the pitch family; mudroom and living roof boxes are RE-CHECKED against the street read — if they float or fight the main roof from the compass shots, adjust pitch/eave to the family (composition change authorized in this task, and only this task).

**Elevation sanity gate:** the compass exterior shots must read as one coherent house — door anchors the elevation, windows rhythmic, rooflines resolve into each other. The exterior composition changes: THIS TASK'S SCREENSHOT GATE GOES TO THE USER before the arc proceeds past it.

## 7. Guards

- **Budget:** ghosts add at most one draw per ghosted piece; per-view ceilings = quality-pass closing-gate numbers +10% (exterior 1231, kitchen 418, living 730, mudroom 382, garage 539); the new south wall/roof fabric raises exterior/kitchen honestly — record before/after per view. Instrument: python tools/house_probe.py --views all --budget --quality high --day.
- **buildMs <=1500ms at high** (AO ~1100 + EdgesGeometry builds; if edges push past the ceiling, build edges lazily on first ghost — authored fallback, not the default).
- **Batching laws verbatim**; registered fabric = merge unit; ghost LineSegments never merge with meshes and share one material.
- **Zero pixel change at exterior for existing fabric** (the new wall/roof are additions; everything already built renders identically when SOLID).
- **Lifecycle law:** edge geometries and the shared line material are build-once, never rebuilt, never disposed by any rebuild path; the pinned leak scenarios stay green.
- **Tests:** live scenario asserting solver verdicts per view (table-driven: view -> expected ghost set); pixel probe proving edge lines render where fills hid; existing scenarios (tap law, leaks, overlays) stay green; full sweep per commit.

## 8. Open questions deliberately settled here

- Ghost line colour is ONE authored constant for all tiers (start 0x2d2018 at ~55% opacity; taste feedback lands at the screenshot gates).
- Lean-in ghosting uses the same solver with the zone quad as subject — no per-zone authored ghost lists.
- The pantry door lean-aside, the garage door openable trick, and the runway/lighting rigs are OUT OF SCOPE — untouched.
- Two-storey shells and parametric wall generation: arc 4.

## 9. Results

Shipped `79b76bc` (T1, v2.491.0) -> `4fab293`+comment-fix (T2, v2.492.0->v2.492.1) -> `1d63b88` (T3, v2.493.0) -> `511c2a2` (mid-arc user redirect, docs-only, v2.493.1) -> `69bcd43` (T4, v2.494.0) -> `5b37552` (T4 fix round 1, v2.494.1) -> this wrap, v2.494.2. All five tasks landed with a clean review (T2 needed one comment-only fix round; T4 needed one code fix round for two CRITICAL findings); no task required a second round beyond that. NOT device-verified, consistent with the rest of the house work.

**Registration table — 12 fabric pieces, as shipped:**

| piece | mode | n (outward normal) | box `[x0,x1,y0,y1,z0,z1]` | landed |
|---|---|---|---|---|
| west_wall | ghost | `[1,0,0]` (flipped from `[-1,0,0]`, T2 — see Deviations) | `[-6.86,-5.575,-0.03,5.6,-5.5,14.28]` | T1 |
| garage_door | ghost | `[0,0,1]` | `[-18.2,-12.6,0,5.7,9.76,10.443]` (post-split, T4; the walls/roof it used to include went to garage_shell) | T1, split T4 |
| mudroom_roof | ghost | `[0,1,0]` | `[-12.75,-6.85,0,4.57,2.3,8.5]` | T1 |
| living_roof | ghost, inert | `[0,1,0]` | degenerate (Box3's own empty sentinel — the group still holds zero meshes through T4) | T1 |
| yard | hide | `[0,1,0]` | `[-23.379,17,-0.384,7.43,-16.189,17.55]` | T1 |
| north_wall | ghost | `[0,0,-1]` | `[-6.5,6.5,0,5.6,-5.725,-5.375]` | T4 |
| south_wall | ghost | `[0,0,1]` | `[-6.5,6.5,-0.0,7,13.95,15.845]` | T4 |
| east_wall | ghost | `[1,0,0]` | `[6.44,6.85,-0.0,7,-5.725,14.55]` | T4 |
| roof_north | ghost | `[0,0.886,-0.463]` | `[-7.9,8.5,6.82,9.28,-6.442,-1.958]` | T4 |
| roof_south | ghost | `[0,0.991,0.133]` | `[-8.02,8.62,6.41,9.289,-6.4,15.21]` | T4 |
| garage_shell | ghost | `[1,0,0]` | `[-18.634,-12.166,0,6.54,1.4,10.6]` (the box garage_door held before the split) | T4 |
| west_skirt | ghost | `[1,0,0]` (dispatch suggested `[-1,0,0]`; implementer derived + rejected it; re-reviewer independently re-derived and confirmed `[1,0,0]`) | `[-7.15,-6.5,0,7.0,6.0,14.6]` | T4 fix round 1 |

Helper/registry code, current HEAD line numbers (grep-verified, not carried stale from a per-task report): `regFabric` `static/house.js:836`, `fabBox` `:847`, `boxOk` `:877`, `solveShell` `:890`, `GHOST_MAT` `:926`, per-room `ROOM_AABB` `:8471`, `window.chfShellFabric()` `:9271-9278` (shape `{name, mode, visible, verdict, edgesVisible}` — grown T1->T2->T3, unchanged since), `west_skirt`'s own `regFabric` call `:4426`.

**Per-view verdict sets, as shipped:**

| piece | mode | kitchen | living | mudroom | garage | exterior |
|---|---|---|---|---|---|---|
| north_wall | ghost | solid | solid | solid | solid | solid |
| west_wall | ghost | solid | solid | **ghost** | solid | solid |
| roof_north | ghost | solid | solid | solid | solid | solid |
| south_wall | ghost | **ghost** | **ghost** | solid | solid | solid |
| east_wall | ghost | **ghost** | solid | solid | solid | solid |
| roof_south | ghost | **ghost** | **ghost** | solid | solid | solid |
| garage_shell | ghost | solid | solid | solid | **ghost** | solid |
| garage_door | ghost | solid | solid | solid | **ghost** | solid |
| mudroom_roof | ghost | solid | solid | **ghost** | solid | solid |
| living_roof | ghost (inert) | solid | solid | solid | solid | solid |
| west_skirt | ghost | solid | solid | **ghost** | solid | solid |
| yard | hide | **hide** | **hide** | **hide** | **hide** | solid |

Non-solid summary per view (the shape every task's own LEGACY table used): exterior `[]` (sealed house, spec section 6: every piece SOLID); kitchen `[south_wall, east_wall, roof_south, yard]`; living `[south_wall, roof_south, yard]`; mudroom `[west_wall, mudroom_roof, west_skirt, yard]`; garage `[garage_shell, garage_door, yard]`. living/kitchen's asymmetry on east_wall (kitchen ghosts it, living doesn't — `LIV_POS.x 5.2 < 6.645`) is the proof the normal does real directional work, not just a same-room blanket ghost.

**Budget: before/after per view, vs ceiling (quality-pass closing-gate baseline +10%):**

| view | baseline (pre-arc) | ceiling | T1-T3 (bit-identical) | T4 original (69bcd43) | T4 fix round 1 (5b37552, HEAD) | this wrap's closing gate (live, 2026-09-11) |
|---|---|---|---|---|---|---|
| exterior | 1231 | 1354 | 1231 | 1262 | 1264 | **1264** |
| kitchen | 418 | 459 | 418 | 416 | 417 | **417** |
| living | 730 | 803 | 730 | 730 | 732 | **732** |
| mudroom | 382 | 420 | 382 | 389 | 389 | **389** |
| garage | 539 | 593 | 539 | 539 | 540 | **540** |

`python tools/house_probe.py --views all --budget --quality high --day`, re-run for this wrap: every view's `inFrustum` reproduced the fix round's own recorded final number exactly — zero discrepancy, so the closing-gate column and the fix round's own column are identical (the constraint about disagreement-beyond-noise doesn't apply here). All five sit comfortably under ceiling. The T4-original->fix-round deltas (+0..+2) are `west_skirt`'s own two meshes leaving `extG`'s shared merge bucket for their own too-small-to-merge group (T4 report's own explanation, reproduced in Deviations); the door reposition in the same round contributed zero mesh-count change (same meshes, moved, not added).

**buildMs trajectory** (quality=high, `--budget --day`, exterior unless noted; ceiling 1500ms throughout):

T1 post-implementation 1227ms (control 1304ms — wall-clock jitter only, byte-identical content) -> T2-final / T3-pre-baseline 1256ms (single sample) -> T3 post-edges 1250/1289/1346ms (+1356ms on a `--views all` run) — the ~50-100ms delta over the T2 baseline is the added `EdgesGeometry` cost for that stage's 114 contributing merged-out survivor meshes -> T4 original 1216/1229/1333ms -> T4 fix round 1201/1281/1297ms -> this wrap's closing-gate re-run: **1262ms** (single boot, all 5 views share it). No lazy-edge fallback was ever needed.

**Ghost-edge mechanics:** `GHOST_MAT` — one shared `THREE.LineBasicMaterial`, `color: 0x2d2018`, `transparent: true, opacity: 0.55` (`static/house.js:926-927`, grep-confirmed at HEAD). Built once, post-`mergeStatic`, from world-matrix-transformed (not naive property-copied — see Deviations) `EdgesGeometry` vertices, combined into exactly ONE `BufferGeometry`/`LineSegments` per fabric piece (not one per surviving merged-out mesh — also Deviations). Count: **10** real `LineSegments` objects for the 12 registered pieces — derived arithmetically (12 total minus 1 hide-mode piece that hides rather than ghosts [`yard`] minus 1 empty/degenerate piece with nothing to build edges from [`living_roof`] = 10), following T3's own verified method exactly (its measured, instrumented count of 3 at the 5-piece stage matched this identical arithmetic: 5-1-1=3). Not independently re-measured in-browser for T4's six additions or the fix round's `west_skirt` in this wrap — that would need new instrumentation, out of scope for a docs-only task; flagged rather than asserted as freshly measured. Every ghost `LineSegments` carries `ls.raycast = function () {}` (T3 finding — the vendored `Raycaster.intersectObject` never checks `.visible`, so an untagged edge-line hit could otherwise have landed ahead of a real tagged mesh and silently swallowed a tap meant for the room behind it).

**Deleted legacy, and what replaced it:** the four hand `hide:` arrays in the `ROOMS` registry (`kitchen: ['yard']`, `garage: ['garage_door','yard']`, `mudroom: ['mudroom_roof','west_wall','yard']`, `living: ['living_roof','yard']` pre-arc — T2's controller ruling dropped `living_roof` from the living row before the arrays were even deleted, since hiding an empty group was already a no-op) and the show-all-then-hide dance in `enterRoom`/`goExterior` are **DELETED** (T2). Replaced by: the `FABRIC` registry (`regFabric`/`fabBox`) feeding `NO_MERGE`/`EXT_NO_MERGE` automatically; per-room `ROOM_AABB`s derived at build via one `scene.traverse()` with two exclusions (skip any mesh under a registered FABRIC group; skip any mesh above `ROOM_CEILING=6.0`, a tuned-not-derived constant — see Deviations); `solveShell(camPos, subject)`, the half-space-plus-corridor solver, called once per camera SETTLE (`enterRoom`, `goExterior`, `goHome`, `solveLeanIn`) and never per frame; a verdict applied as `f.g.visible` + `f.edges.visible` (ghost pieces) or the equivalent for `mode:'hide'`, plus one `shadowDirty()` per solve. `applyState`'s own face/prop logic is untouched — the solver owns SHELL visibility only, per spec section 4.

**Screenshot directories:** `$LOCALAPPDATA/Temp/house_quality/shell-T4` (11 files — the elevation-sanity gate set: `exterior`, `exterior-south/-north/-east/-west`, `kitchen`, `living`, `mudroom`, `garage`, `lean_fridge`, `lean_radio`; sent to the user per the ledger's screenshot-gate ruling) and `$LOCALAPPDATA/Temp/house_quality/shell-T4/fix1` (9 files — re-shot after the two CRITICAL fixes; the three compass-orbit shots were deliberately not reproduced, no recorded camera params to match and neither finding touched them).

**Deviations and rulings, recorded across the arc:**

1. **Degenerate-box ruling** (controller, pre-T2): an empty/degenerate FABRIC box (`living_roof`, zero meshes) must never NaN the solver. `boxOk(b)` guards non-finite bounds and any `min > max` axis, forcing SOLID (inert) rather than risking an Infinity-driven verdict; the LEGACY test table's living row dropped `living_roof` (effective-behavior equality, not array-name equality). Still inert at HEAD.
2. **T3 shipped three fixes to the brief's own literal code, none of them briefed:** (a) world-matrix decompose replaces a naive `position`/`rotation`/`scale` property copy — a real bug for one live case (`calG`, the wall calendar: a real translate plus a 90-degree yaw two levels under `westWallG`; a bare copy would have drawn its edges in the wrong place, facing the wrong way). (b) ONE combined `LineSegments` per fabric piece, not one per surviving merged-out mesh — the brief's literal code would have cost up to 100 draws for `west_wall` alone (100 measured survivors), against section 7's "at most one draw per ghosted piece." (c) `ls.raycast` made a permanent no-op — unbriefed, found by reading the vendored `Raycaster` source rather than trusting section 5's "no special casing" claim.
3. **Mid-arc user redirect** (before T4's implementation proper): the street face had no front door that read as one (the real "front door" was decorative, on the west wall) and no coherent roofline. User picked an offset door under a covered gabled porch, an aligned-head window rhythm, and a roofline-coherence law (one pitch family, gable-end infill closing the wedge). Spec section 6 rewritten and committed docs-only (v2.493.1) before T4 built anything against it.
4. **T4 fix round 1 — two CRITICAL findings, both fixed:** (a) the front door leaf sat at dead centre of the wall's own thickness (`DOOR_Z4 = SWZ0 + WALL_T4/2`), entombed between the opaque interior-plaster and exterior-siding halves and invisible from every exterior camera — fixed by reanchoring to `SWZ1 + 0.02`, reusing the exact epsilon the window casing already proved out. (b) an unregistered west-siding extension sat squarely in the mudroom camera's sightline, turning `mudroom.png` into a plank-texture closeup — fixed by registering it as its own new piece (`west_skirt`) rather than folding it into `south_wall` (folding would have shifted `south_wall`'s own registered box centre enough to flip its already-verified, already-tested mudroom verdict from solid to ghost as a side effect).
5. **`garage_door`'s z-clamp deleted** (T4): Task 2's hand `z0=8.5` clamp (needed because the piece's honest box — spanning the whole gable assembly — tied exactly with the garage room's own AABB centre) is gone. Splitting the piece into `garage_shell` (walls+roof) and a narrower `garage_door` (the actual door cluster, z 9.76-10.443) gives the door a real off-centre box with no clamp needed — exactly what the clamp's own comment anticipated ("whoever registers the split should delete it rather than inherit it").
6. **`west_wall` normal flip** (T2): `[-1,0,0] -> [1,0,0]`. `west_wall` is an interior partition (kitchen<->mudroom), not a true exterior boundary — "outward" has to mean "the side whose room stays solid by default" (kitchen), and every camera including the mudroom's own sits on the same physical side of this wall.
7. **`west_skirt` normal, independently re-derived** (T4 fix round): the fix dispatch's own suggested `n=[-1,0,0]` ("true outward," matching genuine exterior siding) was checked and rejected by the implementer — that sign verdicts the piece SOLID in the mudroom, the one view the whole fix exists to clear. `[1,0,0]` earns the same flip `west_wall` did, for the identical reason. The re-reviewer independently re-derived the sign rather than trusting the rejection, and confirmed it.
8. **Pre-existing glazing night-glow bug found, NOT fixed here** (T4, ruled out of this arc's scope): 6 garage glazing meshes merge past `mergeStatic`'s 4-item floor with no `transparent:true`/`NO_MERGE` guard; the merged survivor drops `userData.glazing`, so those lights stop glowing after dark. Live since the batching arc, unrelated to shell/occlusion. Classified pre-existing-real by review; ledgered as a new finding needing its own dedicated fix task (Open follow-ups, below).

**Other deferred minors, non-blocking** (full detail in progress.md): T1 — the fence loop grants `westWallG` inert `EXT_NO_MERGE`/`NO_MERGE` membership (comment-durability note only, provably inert today); `TOP`'s hand list is now partially redundant post-feed. T2 — `solveShell`'s `if(webgl)` guard is unreachable-redundant; no graceful guard yet for a future room with no tagged floor mesh (`boxCentre(undefined)` would throw). T3 — the <=1-in-frustum-per-ghost check was a one-off script, never pinned as a real test; `bakeAO`'s own now-redundant `updateMatrixWorld` call was left untouched. T4 — a corridor comment overstates "fully inside on every axis" (overlap, not containment, on y; verdict unaffected); the door knob sits flush with the leaf face rather than proud (inherited from the legacy west-door idiom); skipping the compass re-shots in the fix round was ruled justified (no recorded camera params to reproduce, and the exterior verdicts SOLID regardless of angle).

**Open follow-ups (none of them this arc's to fix):**

- **Glazing night-glow task**: the pre-existing merge bug above needs a dedicated fix — exclude `userData.glazing` from `mergeStatic` eligibility (matching the lamp treatment) or copy the flag onto the merged survivor. Not device-verified either way; nobody has seen the garage glow at night since the batching arc.
- **AO-occluder-from-registry unification — an arc-4 prerequisite.** `AO_OCCLUDERS` is still a hand-maintained list: T4 added `south_wall`/`east_wall` rows by hand (citing their own constants) and deliberately skipped `roof_south` (sloped, no honest axis-aligned box to cite without guessing). A future task should generate AO occluders FROM the `FABRIC` registry the same way `NO_MERGE`/`EXT_NO_MERGE` already are fed — arc 4's parametric wall generator has no hand-authored call site to add a fresh AO row at, so this needs solving before generated walls can occlude correctly.
- **Dark yard prop**: a small dark rectangular prop stands alone in the yard between the great room and the mudroom. Confirmed pre-existing (byte-identical in the base commit, not introduced or moved by this arc) but unexplained and not investigated. Flagged as a possible unintentional leftover from an earlier arc.
