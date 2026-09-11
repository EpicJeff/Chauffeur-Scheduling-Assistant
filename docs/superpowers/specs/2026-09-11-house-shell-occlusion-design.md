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

(appended at wrap)
