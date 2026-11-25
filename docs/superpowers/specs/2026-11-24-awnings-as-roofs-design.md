# Awnings as roofs: design

Date: 2026-11-24. Branch: `awnings`. Status: direction chosen by the owner (approach A). This document awaits approval.

## Intent

The owner: "Honestly, they are really just roofs with supports instead of walls supporting them. The real difference is the support type. So they should basically be a subtype of roof with all of the properties of a roof and the addition of the suport type and materials for those." And: "There shouldn't be any difference between what the agent adds during automatic generation and what I can add by hand."

Today an awning is a special piece only the drawing reader can create. It cannot be placed, edited, moved, hidden, given materials or picked in the 3D view. This makes an awning an ordinary roof that people and the agent place and edit the same way.

Reference photos (not committed): a sloped metal awning on wood braces, a gable with an open truss end on large brackets, a flat slatted canopy on cables, and a shallow closed-in box on scroll corbels.

## Goals

1. One roof record with a support setting. Every roof property works on it: outline, slope per edge including flat, gable or shed, overhang, gutters, dormers, solar, a material per plane.
2. Support types: walls (every roof today), straight bracket, corbel, brace, cables, posts.
3. Ends open, open with a truss, or closed in.
4. An underside of its own: exposed, exposed with rafters, or a flat ceiling. Lights and fans can hang from it.
5. An optional open-slat covering that lets rain and sunlight through.
6. Place, select, move, resize, copy, hide, lock, delete and undo by hand in the 3D view and the scene panel.
7. The two existing awnings become these with the same look. The pool house patio can become one roof with posts.
8. Walled roofs are unchanged.

## Non-goals

- Curved, retractable or motorised awnings, fabric.
- Roof outlines that are not right angles; roofs have that limit today.
- Plants or lights as part of the awning. Lights attach as devices.
- Solving the roof seam and flat-siding questions. Those are separate.

## Anti-goals

- Any change to how a walled roof, its walls or its gables look.
- A second roof builder.
- A generated piece that behaves differently from a hand-made one.

## Constraints

- Budgets: 0 new samplers, 0 new programs. Supports are merged per material into the existing building meshes, so 0 extra draws when an existing material is used.
- Supports are static geometry, so there is no per-frame cost. Costs are reported before any look review: triangles, draws, programs, samplers, build time.
- Any change to receiving geometry needs one rebake. All landings that need one land together.
- Undo history and saved houses must keep opening, in both the old and new shape.

## Approaches

| | What | Trade-off |
|---|---|---|
| **A. One roof record with a support setting (owner's choice)** | Everything a roof does, plus supports | The roof code assumes walls; that is taught out in the list below |
| B. A separate awning piece that borrows the roof builder | Walled roofs untouched | Every roof feature wired up twice, and the two drift apart; that is how today's awnings came about |
| C. A roof plus separately placed supports | Least work | The roof still shapes walls, and supports do not follow it |

## The data

All fields are optional on the stored `roofs` record. A roof without `support` is a walled roof, exactly as today. Field shapes are the builder's, within these meanings:

- `support`: `{ kind: walls | bracket | corbel | brace | cable | post, count, inset_ft, spacing_ft, size_ft, style, at: {<index>: [x, y]} }`.
  - `count` is an integer from 0 to 40; absent defaults to 2. Zero means no support geometry for any kind. Legacy numeric bracket counts are rounded up and clamped to 0..40 (true means 1); absent brackets means zero. Later bool, string and fractional edits default to 2; fractional legacy spacing is retained with ordinary building-frame `support.at` overrides (owner Task 4 review rulings).
  - Supports are placed automatically by `count` along the outer edge, spread evenly with an inset. Any one can be dragged; its override replaces the automatic place. Reset returns it.
  - `style` picks a built-in shape for brackets, corbels and braces, or a Library model.
  - Cables: an anchor height above the eave on the wall, rod diameter and an anchor plate. Posts: size and shape, with a base. The ground under a post is the floor or the yard below it.
- `host`: the wall the roof hangs from and which roof edge is attached. Absent for a free-standing roof. The roof moves with its wall. A deleted wall leaves a flag, and the roof stays.
- `ends`: per open edge: `open`, `truss` or `closed`.
- `underside`: `exposed`, `rafters` or `flat` with a height. Slatted roofs have none.
- `covering`: `solid`, or `slats` with slat width, gap, thickness and direction.
- `thickness`: the slab thickness. Today's awnings are 0.3 ft; walled roofs keep their own.
- Overhang becomes settable per edge, so the side against the wall can be 0.
- Materials: the existing roof, plane and fascia materials, plus slots for supports, truss, underside and slats. New slots go in `services/twin_surface_kinds.py` and its JS twin.

Task 4 review I3: gutter mount overhang is the edge's own `overhang_ft`, falling back to uniform overhang; it never uses section depth. Post searches retain that limit. Only an eave parallel to and opposite its recorded host edge can route to that host wall across the measured wall gap; this separate wall reach also identifies the wall's corner. It cannot extend post searches or reach another wall.

Persistence facts that must be handled: `from_section` drops unknown edge fields, a re-read restores only `wall` and `wall_offset`, `accept_proposal` and the legacy edit replace the record, the `choices` whitelists omit new fields, and dormers do not inherit record fields.

## Calls made where the code left a choice (Claude; change any by asking)

- **Height:** like `plate` today, the eave height is absolute in the building's own frame. `level` is stored only for floor-view visibility. An upper-floor awning uses its host wall's level for that.
- **Outline:** the same right-angle polygon roofs accept today, split into sections by the existing code. Today's awnings are single rectangles.
- **Host:** the existing edge attachment (`wall`, `wall_offset`) is reused. For a supported roof, the whole roof moves with the wall, not just the edge. A host within 1 degree of a building axis is accepted (Task 4 review ruling). More diagonal walls keep the old drawn placement without a host, with a plain flag. The optional ordinary `roof_frame: {origin: [x, y], angle}` rotates canonical roof coordinates about a building-frame origin; angle is radians. Automatic support points rotate with it; authored `support.at` points remain in building-frame feet. `gable_beam` is an ordinary boolean stored on the walled roof and round-trips independently of any supported roof.
- **What counts as an awning:** any roof whose `support` is not `walls`. Post-supported roofs, including the patio, are awnings. The scene panel labels them "Awning" and the agent uses that word.
- **Old houses:** awnings migrate on load, and the new shape is written on the next save. Undo steps and saves in the old shape keep opening. A house saved by this version does not open in an older app version.
- **Slats and lamps:** the slat geometry itself is the occluder for baked lamps and the sun. The baker has no partial-transmission occluder, so none is added. At outdoor texel density the lamp stripes will be soft. Cap: 60 slats (720 triangles) per awning; a wider roof spaces them further apart.
- **Golden hash:** the owner's house may have roofs under other roofs. Because the walled group's code does not change, the hash must still match; if it does not, landing 0 is wrong.
- **Patio conversion:** moving the posts makes that shed roof post-supported, so it stops shaping walls and gables under it. The action shows the before and after first, and is one undo step. It is only ever the person's explicit choice.

## Behaviour

- **Nothing about supports reaches walls.** A supported roof does not lower or raise walls, fill gables, make step siding, count as a storey or a ceiling, cut floors, snap or re-level under the joint pass, become a proposal in a re-read, or block solar saves. Its own height is the lowest roof above a given floor, so a porch post under a high roof ends at the right height.
- **It is still a roof.** Sky cover, rain, snow, eaves, streams by catchment, gutters, downspouts, baked lamp shadows, solar panels and picking treat it like any roof. Downspouts may mount to a support post or the host wall.
- **Slats:** rain, snow and wetness pass through; the ground below is wet; no eave streams come off it. Sunlight makes real stripes from the live sun shadow. Baked lamp light is too coarse (4 texels per foot outdoors) to show stripes, so lamp light passes as if the slats were open by their gap ratio.
- **Underside:** a flat ceiling hides the slope above it. Baked light, rain shelter and the eave height use the surface you see.
- **Devices:** a light, fan or camera can hang from an awning's underside, at any point, and moves with it.
- **Floor view:** an awning shows with the level its host wall belongs to, or the ground level when free-standing.
- **Agent:** the same operations, documented in `house_design`, through the same save path.

## Editor

- A support choice on the roof card: what holds it up, count, size, style, ends, underside, covering. Unused options stay hidden.
- Place: an Awning tool. Click a wall to hang one (4 ft deep, centred on the click, eave 8.5 ft high or 6 in above a door or window head below it); drag its ends and depth. Or draw one anywhere with posts.
- Handles: ends, depth, outline, each support, and height. Drag the whole awning along its wall. Works from the view and the scene panel, with the same selection, undo, copy and delete as any piece.
- Copy and paste, hide and lock like other pieces. Today roofs refuse copying; a copied roof needs no host wall until placed.

## Migration

- Each `awning` extension becomes a roof with straight brackets, keeping its id, span, depth, pitch, eave height, gutter setting and bracket count. The host wall is the one the renderer picks today; the main house awning has none recorded, so it is taken from the renderer's choice and flagged if none is found.
- Save files, undo history and exports with the old shape open the same way. A drawing read produces the new shape.
- `shed_continuation` extensions become ordinary shed roofs (the owner has none).
- The pool house patio is **not** changed automatically. The porch card offers "Move posts to the roof", which moves the 2 posts to the shed roof above, keeps the porch as the floor, and can be undone.

## Proving walled roofs are unchanged

- A golden test hashes every drawn mesh of the owner's house (export by path only) and the household fixtures, before and after, with awnings removed from both. The hash must match exactly.
- A second comparison with the migrated awnings shows identical triangles and materials for them within a documented tolerance, and side-by-sides.
- Fixed captures before and after: default overview, pool house, garage side, a focused room, day and night, High and Low.

The places that assume walls today, with the fix each needs, from a code map (line numbers at `0ec59a62`):

| # | Where | Fix |
|---|---|---|
| 1 | Wall tops, `twin_generator.js` 1125, 1474 | Shape walls from walled roofs only |
| 2 | Step faces, 1654, `twin_roof.js` 244 | Skip pairs with a supported roof |
| 3 | Gable fill, 1699 | Skip supported roofs |
| 4 | Single-valued envelope, `twin_roof.js` 83, 324; generator 1123, 1634 | Build one envelope per group and concatenate, so a roof under another keeps its eaves and fascia |
| 5 | Heights by maximum, generator 1983, 2098; `gutters.js` 537 | Preserve today's walled height; where covered, override with the lowest supported roof's underside above the floor and below that height |
| 6 | Ceilings, generator 1952 | Filter supported roofs |
| 7 | Floor cutters, generator 1119 | Cut supported roofs only by outlines whose storey's occupied volume or floor structure overlaps the slab's height range |
| 8 | Own-storey tests, generator 1126, 1656; `twin_model_bridge.py` 372; `twin_model_ops.py` 1517; `twin_build.py` 1359 | Use the stored level |
| 9 | Wall attachment, `twin_model_roofs.py` 201; ops 1532, 2379 | Store the host wall; move the whole roof; flag a deleted wall |
| 10 | Joint snap and report, `twin_joints.py` 221, 552 | Skip supported roofs |
| 11 | Draft checks and roof issues, `twin_build.py` 1358, 2178; `twin_roof_issues.py` 140 | Skip |
| 12 | Re-read overlap, bridge 422 | Exclude supported roofs |
| 13 | `roof_over`, ops 1497 | Unchanged; it is for walled roofs |
| 14 | Solar clipping, `twin_solar.py` 272, 390 | Use the supported roof's own envelope |
| 15 | Beam and gable trim, generator 1714 | Key on walled roofs |
| 16 | Buildings with no walls, `twin_ground.js` 75 | Footprint from the supported roof |

**Row 5, owner clarification (2026-11-24):** the walled rule wins. Porch posts,
screens, columns and porch lights keep today's upper-envelope height query on
walled roofs. Room lights and gutter posts also compute their existing walled
result first. Only where a supported roof covers the point, lies above the
relevant floor and below that existing height, use the lowest such roof's
underside instead. No supported roof means no height change; the owner's
walled golden hash must remain equal. "Lowest roof above the floor" in this
row applies to supported roofs only. Coverage means the drawn, cut footprint;
an indoor lamp or recessed post under a cut-away part is unaffected. Ghost and
proposal roofs cannot cap real fixtures, and the underside must be above the floor.

**Row 7, owner correction (2026-11-24):** an outline below an awning does not
cut it unless that storey reaches the slab. A second-storey awning over a
one-storey wing therefore draws in full and remains selectable. The same eligible
cutters govern drawing and the row 5 coverage query.

**Rain paths, owner ruling R1 (2026-11-24):** supported roofs participate in
rain cover and landing. Where an awning intersects a walled gutter's rain path,
that run may split and a downspout may move or land on the awning. Walled gutters
elsewhere remain unchanged. This is the same rain behavior as legacy awnings.

Supported roof envelopes and picks retain each piece's identity, while their
drawn geometry merges by building, stored level and material. With the existing
shared finishes, one, two or three awnings cost at most three draws per level
with awnings and zero on levels without them. Per-piece hide and bake ranges survive batching.

## Landings

Each is reviewed and shipped on its own, with the fixed captures and the golden test.

0. **Grouped envelope refactor.** Fix 4 lands first, alone, as a behaviour-neutral change with its own golden hash: the walled group runs exactly today's code path, and a supported group (none exists yet) would be built separately and concatenated. This protects every later step.
1. **Record and independence.** Fields, migration, the other fixes, golden test, undo and save compatibility. Awnings keep today's look and bracket shape, and become selectable, editable and deletable. Shipped together with landing 2, because it changes awning geometry ids, so the owner rebakes once.
2. **Supports.** Straight bracket, corbel, brace, cable and post shapes, materials, the support handles, and the patio conversion action.
3. **Ends, underside and devices.** Truss and closed ends, rafters, flat ceiling, hanging lights and fans.
4. **Slats.** Covering, rain and sun, wetness, shelter.
5. **Place and copy.** The Awning tool, handles for a whole awning, copy and paste, agent documentation and tests.

Landings 0 and 3 to 5 do not need a rebake of their own unless their golden test says otherwise; any that does is held to the same release.

## Work split

- Codex: landing 1 (data, migration, the golden test, the server fixes) and the operations in 5. Test first.
- Gemini: supports, ends, underside, slats, and their look captures.
- Claude: contracts and tests before parallel work, reviews, browser checks, landing.

## Left to the builder

Field spellings, built-in shape proportions, handle layout, card order, and how overrides are stored, within the meanings above.
