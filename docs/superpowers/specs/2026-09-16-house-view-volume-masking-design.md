# The Home — view-volume masking and roof valleys

Binding spec, user-ratified 2026-09-16 (brainstormed after the massing arc 1 post-ship fixes). It replaces the shell solver's per-piece verdicts with a geometric mask computed per room at build time, and it clips facade roof features to the roof they sit on. Every prior house law travels with it: batching (`2026-09-10-house-batching-design.md`), the lifecycle law (mkTex owns textures; cgeo owns geometry), the shell registry (`2026-09-11-house-shell-occlusion-design.md`: every shell piece registers through `regFabric`/`shellRegister`; ghost edges stay OFF), the facade generator (`2026-09-15-house-facade-generator-design.md`), and the regular house (`2026-09-16-regular-house-orbit-design.md`).

## 1. Why

The shell solver hides or ghosts WHOLE pieces. Since massing arc 1 merged per-room enclosure pieces into whole-block pieces, that has meant one-off surgery per room: an `owners` table (v2.499.41), the south wall and the main roof split at x 6.85, hand-derived verdict tables per camera, and still the garage-block roof comes off whole when the mudroom is the subject. The split also broke the main roof's hip and ridge-z forms. The user's framing, ratified: "a generic solution that only hides what is actually necessary to see the selected room" — take the room's bounds and the camera, build the volume from the camera that contains the whole room, and mask the shell inside that volume. Computed at build time and swapped at settle, it is cheaper than the solver it replaces.

The second half of the arc uses the same clipping machinery for a separate defect the user pointed at: facade gables and dormers are full rectangles that run back under the main roof and show inside the house.

## 2. The mask (user choices A / A / A)

For a room R with room camera C:

- **B** is R's registered AABB: footprint × floor-to-eave (**eave-high, choice A**). The roof is cut only where a ray through it would reach the walled volume; the near slope of the vaulted ceiling comes off and the far slope stays visible from inside.
- **Front faces** of B are the faces whose outward normal points toward C.
- **P** (pyramid) is the intersection of the half-spaces through C and B's silhouette edges as seen from C. Convex, at most six side planes.
- **W** (wedge) is the intersection of the half-spaces behind each front face plane (the box side). Convex.
- **Masked = P ∩ ¬W; kept = ¬P ∪ W.** A point is masked exactly when the ray from C through it would enter B after passing it. The cut edges therefore project onto B's silhouette from C: from the room camera the cut coincides with the room boundary.
- **Shell only (choice A).** The mask applies to registered fabric (walls, roofs, doors, windows, yard). Props of other rooms in the way are never cut.
- **Cut faces are capped in one neutral section tone (choice A)**: a light plaster grey, the same for every piece, a single shared material.
- Camera inside B never happens for a room camera. Lean-in cameras (frameZone) keep the room's mask; no recompute.
- Exterior and every orbit stop: no mask, the full shell.

## 3. The clipper — `chauffeur/static/house_clip.js`

One unit of pure functions, no scene state, no three.js objects except `Vector3`/`Plane` maths.

- A **solid** is a convex polyhedron: a list of faces, each a planar polygon of vertices carrying `position`, `uv` and `ao` (the baked vertex ambient occlusion), plus the face's material slot.
- `clipConvex(solid, plane)` returns the part of the solid on the kept side of `plane`, with one new capped face on the plane; every new vertex interpolates `position`, `uv` and `ao` linearly along the cut edge.
- `subtractConvex(solid, planes)` returns the parts of the solid OUTSIDE the convex region bounded by `planes`, as a list of solids, by sequential splitting: the piece outside plane 1; then the remainder inside plane 1 split against plane 2; and so on. The pieces do not overlap and leave no gap.
- `toGeometry(solids, capSlot)` returns one BufferGeometry with groups: original faces keep the piece's material slot; cap faces go to `capSlot`.
- Solids come from the builders, never from reverse-engineering a mesh: a `box()` is six planes; a `shellGable` deck or hip end is its extruded polygon (n side planes plus top and bottom). Every fabric row grows a `solids()` getter that returns them with the piece's attributes.
- For a room: `keep(piece) = clipConvex(piece, W planes) ∪ subtractConvex(piece, P planes)`.
- Non-convex fabric (door and window kits, the coach lamp): masked whole if the piece's box centre is masked, kept whole otherwise; a kit whose box is more than half inside the mask goes whole.

## 4. Build and swap

- After the last `regFabric`, `buildRoomShells()` runs once per room camera (kitchen, living, study, garage, mudroom). For each fabric row it computes the kept solids, builds one geometry, and merges per room by material with the same `mergeStatic` idiom, so the batching contract is unchanged. Result: five room-shell groups beside the untouched full shell. Every geometry goes through `cgeo`, keyed `shell-mask|<room>|<piece>|<camera>`.
- `enterRoom(r)` at settle: full shell hidden, room-shell r visible, the other four hidden. `goExterior` and the orbit: full shell visible. Lean-ins keep the room's shell. `shadowDirty()` after each swap, as today. The shell still pops at settle, as today.
- Cut geometry is absent from the raycast and the shadow map for that room, exactly like a hidden verdict today, so markers and taps behave as they do now.

## 5. Retired

- `solveShell`'s verdicts and the corridor rule; on fabric rows: `owners`, `cutawayRoom`, `twoSided`, `mode: 'hide'`, `plane`, `pad`.
- The x 6.85 splits: `south_wall_east` folds back into `south_wall`; `roof_main_west`/`roof_main_east` become one `shellGable('roof_main', …)` again, so hip and ridge-z build as they did before v2.499.41. The garage-block roof stays one piece.
- `STUDY_SLOTS` and `slot_owners()` in `services/house_facade.py` and their JS mirror; the slot table loses `owners`; the parity pin is updated.
- The verdict tables in `tests/test_house_live.py` and `test_house_life_live.py`.

Kept: every `regFabric` name and its `room` (taps), the registry pin (exact set, re-derived for the un-split names), `chfShellFabric()` (rows report `maskedFraction` per room instead of `verdict`: the surface area of the piece's original faces that was removed, divided by the original surface area, 0 for untouched and 1 for masked whole), `chfNavProbe`, the kitchen camera at the street and the study camera east of the split (they stay: nothing but the room's own enclosure should stand between camera and room), ghost edges OFF.

## 6. Roof valleys

- Every deck, rake/eave trim and ridge cap of a facade gable or dormer is `clipConvex(solid, parentDeckPlane)`, the plane of the block roof deck it sits on, derived from the same eave/pitch/ridge numbers `shellGable` uses for that block (`roofPlaneEave` keeps the per-face eave). The part under the main roof disappears; the valley line is exact; nothing shows inside the house. The front gable-end infill is clipped by the same plane.
- Height rule: a feature's eave is set so that its ridge stands proud of the parent plane at the street wall by the feature's own rise; computed per feature, recorded in §9.
- Garage-block face features clip against the garage-block deck plane.
- The main roof being one piece again, the hip and ridge-z variants are built and looked at (probe `--roof`), with the masks cutting them per room.

## 7. Tests

- `tests/test_house_live.py`: for each room, `chfShellFabric()`'s `maskedFraction` pins — the room's near wall and the roof over it mostly masked (> 0.5); its far wall, its side walls, every other room's enclosure and the yard at 0; exterior and every orbit stop all zeros. A vertex pin: sampled kept vertices of every piece lie outside the mask. A valley pin: every vertex of every facade roof feature sits at or above its parent deck plane (minus 0.05). The existing marker/pixel scenarios, the registry pin, the canonical mesh pin (re-recorded RED-first for the un-split pieces), the facade parity pin (owners gone) all green.
- `tests/test_house_facade.py`: slot rooms/owners assertions removed; canonical, normalize, worst case unchanged.
- Probe: `--views all --budget --quality high --day` before/after; `--views orbit`; `--roof hip` and the ridge-z variant; the five room PNGs looked at: every other room enclosed, the subject open along its silhouette, caps legible, no gable under the roof from inside.

## 8. Budget

`buildMs` ≤ 1500 including the five room shells (expected +100–200 ms; record it). Per-room in-frustum re-baselined (cut geometry is smaller). Exterior and orbit unchanged. Memory: five room shells of cut geometry beside the full shell; record the geometry count delta.

## 9. Results

Filled at wrap (Task 6, v2.499.57). Sources: task-1..5 reports and progress.md in
`.superpowers/sdd/2026-09-16-house-view-volume-masking/`.

### Per-view budgets, quality=high --day --budget (task-3-report.md, task-4-report.md, task-5-report.md)

| view | pre-arc (mask-before) meshes/inFrustum/tris | v2.499.53 (mask-after) | v2.499.54 final (mask-after3) | v2.499.55 (unsplit-after) | v2.499.56 (valley-after) |
|---|---|---|---|---|---|
| exterior | 2084/1432/299134 | 2286/1432/299134 | 2287/1432/299134 | 2272/1417/298770 | 2286/1433/299285 |
| kitchen | 2084/519/115190 | 2286/591/224624 | 2287/539/111879 | —/515/110924 | —/530/111804 |
| living | 2084/728/136880 | 2286/815/250976 | 2287/753/138182 | —/736/137799 | —/744/138175 |
| mudroom | 2084/400/46518 | 2286/476/160822 | 2287/428/48394 | —/443/49022 | (not re-probed; carries v2.499.55's 443/49022) |
| garage | 2084/754/110034 | 2286/822/218545 | 2287/770/111173 | —/784/111789 | (not re-probed; carries v2.499.55's 784/111789) |
| study | 2084/322/26040 | 2286/411/135457 | 2287/343/26585 | —/342/26588 | (not re-probed; carries v2.499.55's 342/26588) |

`buildMs`: pre-arc 1002–1020; v2.499.53 1180–1213; v2.499.54 1113–1162; v2.499.55
934–1213 (1075 canonical, 1213 hip probe, 1172 ridge-z probe); v2.499.56 1050–1283
(1283 canonical exterior, ≤1283 everywhere probed). Ceiling 1500 throughout — never
approached. Geometry count: 1502 (pre-arc) → 1704 (v2.499.53) → 1705 (v2.499.54) →
1693 (v2.499.55) → 1713 (v2.499.56).

Orbit (8 stops, v2.499.53 mask-after): every stop draws exactly the exterior's list
(1432 in-frustum, 1429 at stops 2/6, 299134 tris) — a stop is `solveShell(to, null)`,
the same draw list as the exterior, so the exterior's own before/after numbers are
also the orbit's baseline. Orbit at v2.499.56 (valley-after): 1433/299285 at every
stop but 2 and 6 (1430/298133), buildMs 1191.

### Canonical exterior mesh pin, re-recorded RED-first at every task

| version | count | delta and cause |
|---|---|---|
| pre-arc (v2.499.45, vaulted partitions) | 1869 | baseline |
| v2.499.53 (Task 3, first room shells) | 1993 | +124: the five shells' unmerged remnants (kitchen 46, living 10, study 9, garage 8, mudroom 51) |
| v2.499.54 (Task 3 fix round 1, per-row merge + porch de-kit) | 2026 | +33 more: shells merge per mirrored row instead of at the shell root (kitchen 57, living 20, study 14, garage 8, mudroom 58 total) |
| v2.499.55 (Task 4, one `south_wall`/one `roof_main`) | 2017 | −9: the two x-6.85 splits folded back (−3 wall boxes, −6 roof pieces) |
| v2.499.56 (Task 5, roof valleys) | 2015 | −2 net: +6 exterior survivors from the porch/bay gables' extra convex pieces, −8 kitchen shell (buried porch-gable back removed from its cone), +4 garage shell, −4 mudroom shell |

Standalone (scenario's own seed only, no room-shell content beyond the scenario's
own fixtures): 1876 at v2.499.55 against 1885 at v2.499.54 — the same −9 and nothing
else, and the same 141-mesh seeded gap that has existed since the split first landed.

### Mask-fraction table per room (`chfShellFabric()`, task-3-report.md; renames per task-4-report.md)

Recorded as built at v2.499.53/.54 (task-3-report.md); the row names below are the
task-4 renames (`roof_main_west_south` → `roof_main_south`, `south_wall_east` folded
into `south_wall`) with task-4's re-derived numbers where the fold changed the
fraction, else the task-3 number is unchanged (confirmed in task-4-report.md and
task-5-report.md's probes).

| row | kitchen | living | study | garage | mudroom |
|---|---|---|---|---|---|
| north_wall | 0 | 0 | 0 | 0 | 0 |
| west_wall | 0.196 | 0.006 | 0 | 0 | 0.372 |
| west_cladding | 0.028 | 0 | 0 | 0 | 0.318 |
| north_cladding | 0 | 0 | 0 | 0 | 0 |
| south_wall (was split south_wall/south_wall_east) | 0 | 0.5615 | 0.3516 | 0 | 0 |
| east_partition | 0 | 0 | 0 | 0 | 0 |
| east_wall | 0 | 0 | 0.008 | 0 | 0 |
| roof_main_north (was roof_main_west_north) | 0.0041 | 0 | 0 | 0 | 0 |
| roof_main_south (was roof_main_west_south/east_south) | 0.3007 | 0.2106 | 0.0049 | 0 | 0 |
| roof_main_end_west | 0.371 | 0 | 0 | 0 | 0.039 |
| roof_main_end_east | 0 | 0 | 0.0002 | 0 | 0 |
| garage_block_north | 0 | 0 | 0 | 0 | 0 |
| garage_block_west | 0 | 0 | 0 | 0 | 0 |
| mudroom_front | 0.033 | 0 | 0 | 0 | 0.517 |
| garage_block_roof_north | 0.003 | 0 | 0 | 0 | 0 |
| garage_block_roof_south | 0.034 | 0 | 0 | 0.145 | 0.003 |
| garage_block_roof_end_west | 0 | 0 | 0 | 0 | 0 |
| garage_block_roof_end_east | 0.578 | 0 | 0 | 0 | 0.067 |
| north_wall_east | 0 | 0 | 0 | 0 | 0 |
| back_door (kit) | 0 | 0 | 0 | 0 | 0 |
| future_room_partition | 0 | 0 | 0 | 0 | 0 |
| west_skirt | 0.291 | 0 | 0 | 0 | 0.388 |
| facade_main_window_7/9/12 (kit) | 0 | 1 | 0 | 0 | 0 |
| facade_main_door_10 (kit) | 0 | 1 | 0 | 0 | 0 |
| facade_main_window_15/16 (kit) | 0 | 0 | 1 | 0 | 0 |
| facade_garage_block_gable_0_west | 0 | 0 | 0 | 0.49 (0.34 pre-valley) | 0 |
| facade_garage_block_gable_0_east | 0 | 0 | 0 | 0.27 (0.14 pre-valley) | 0 (0.09 pre-valley) |
| facade_garage_block_gable_0_front | 0 | 0 | 0 | 0.866 | 0 |
| facade_main_gable_8_west/east | 0.2034 (0.2486 pre-valley) | 1 (dropped whole, roof-feature rule) | 0 | 0 | 0 |
| facade_main_gable_8_front | 0 | 0.6958 | 0 | 0 | 0 |
| facade_main_porch_8 (non-kit since v2.499.54) | 0 | 0.132 | 0 | 0 | 0 |
| garage_shell | 0 | 0 | 0 | 0.036 | 0.001 |
| garage_door (kit) | 0 | 0 | 0 | 1 | 0 |
| yard (hidden whole in every room, v2.499.54 ruling) | 1 | 1 | 1 | 1 | 1 |
| living_study_door / east_room_door / living_back_room_door (kit, late) | 0 | 0 | 0 | 0 | 0 |

Mask boxes (eave-high): kitchen x −10.39..6.5 z −5.8..5.8; living x −6.5..6.5
z 5.1..14.22; study x 6.92..15.25 z 7.12..14.45; garage x −17.96..−12.83 z
2.21..9.76; mudroom x −12.6..−6.8 z 2.36..8.3; all y 0..5.6.

### Hip/ridge-z probe numbers (task-4-report.md, task-5-report.md)

Task 4 (`--roof hip` / ridge-z, on the un-split `roof_main`): hip exterior
1410/298618, buildMs 1167 (one proper hip, four planes meeting at a 1.15 ridge, no
hole, masked per room like the gable); ridge-z exterior 1416/298742, buildMs 1172
(gable running north–south, gable end to the street, vault gated off, walls at the
eave under it, clean).

Task 5 (`--roof hip` / ridge-z, with the roof-valley clip active): hip exterior
1428/299194, buildMs 1050 (porch gable meets the hip's south plane with two valleys;
bay gable pokes out of the garage block's clamped pyramid with valleys into both its
south and west planes); ridge-z exterior 1432/299140, buildMs 1143 (porch gable's
ridge, 7.505, is under the ridge-z roof line at its x, so behind the wall it is
wholly buried and clipped away — a gabled porch against the end wall, no cut end
floating). Worst-case facade (`--facade worst`, six dormers + three bay gables +
one span-1 porch gable): 1542/300188, buildMs 1092, clean — dormers stand on the
roof with cut backs, bay gables close into the garage roof with valleys, the
span-1 porch gable (ridge 5.61 < the plane's 5.78 at the wall) is wholly buried and
gone behind the wall.

### Valley heights per feature (eave / ridge, before → after; task-5-report.md)

Main street deck plane: centre line 5.78 at the wall (z 14.55), ridge 10.057 at
z 4.225. Garage-block street deck: 5.78 at z 10.10, ridge 9.135 at z 2.0.

| feature | eave before → after | ridge before → after | proud at the wall | back (z0) before → after |
|---|---|---|---|---|
| canonical porch gable (span 4, half 3.633, rise 2.525) | 4.8 → 4.8 (porch exception) | 7.505 → 7.505 | 1.725 (2.525 − 0.8); measured 1.85 with the cap | 11.75 → 9.785 |
| canonical garage bay gable (span 1, half 2.7625, rise 1.92) | 5.6 → 5.6 | 7.70 → 7.70 | 1.92 (its whole rise); measured 2.045 | 4.0 → 4.0 (already behind both deck and cap) |
| study reproduction (span 3, slot 13/14, half 2.725, rise 1.894) | 4.8 → 5.6 (height rule) | 7.505 → 7.674 | 1.894 (its whole rise; was 1.725); measured 2.019 | 11.75 → 9.378 |
| span-1 main dormer (w 1.417) | box centre 6.443 → 7.061 (bottom on the roof at its front face) | mini gable 8.065 → 8.684 | the whole 1.9 front face out of the roof (was 1.28) | box z 12.15..13.75 unchanged; back clipped under the plane |

Buried-vertex audit: 0 for every feature row of the canonical facade and the study
reproduction, after the fix (RED at HEAD/e89b4be: 36 of 72 vertices of
`facade_garage_block_gable_0_west` below its parent deck plane, lowest −2.884).

### Deviations and their rulings

1. **Room shells hold remnants only** (stamped `maskPattern`/`maskOnly`, toggled at
   settle, merged per mirrored row), not a full cut copy of every fabric row —
   budget-driven (five full copies would have added a merge+bake per room against a
   1500 ms ceiling with ~500 ms headroom); the brief's named interface
   (`f.shells[room]`, `roomShellGroups`, `CAP_MAT`, `chfRoomShellShown`,
   `chfRoomMask`, `chfRoomShellLeak`, `maskedFraction`) is preserved. Ruling:
   accepted (task-3-report.md).
2. **Box top SET to the eave**, not `min(top, eave)` — `ROOF_AABB` is measured from
   props and floor only, so a literal `min` would cut the roof only where a ray
   reaches a sofa. Ruling: read the spec's stated intent ("footprint ×
   floor-to-eave") over its literal formula (task-3-report.md).
3. **Per-mesh W-plane shift for straddling enclosure** (`STRADDLE_TOL` = 0.60) — not
   in the brief; needed because `ROOM_AABB`'s footprint runs into the enclosure
   itself in four places. Ruling: pin strengthened in the fix round
   (task-3-report.md, progress.md Task 3 ruling 2).
4. **Kit rule is spec §3's** (box centre or ≥5 of 8 corners), not the brief's draft
   `hits < 5` of nine points — the draft rule kept the garage door visible in its
   own room. Ruling: spec wins (task-3-report.md).
5. **Hairline clips** (< 0.1% of a mesh's area) count as untouched — no remnant, no
   toggle. Ruling: accepted, undisputed (task-3-report.md).
6. **Roof features drop whole below a fifth kept**, rather than always clipping —
   controller ruling made after the first room-shell build showed floating
   porch/bay-gable shards. Cost accepted: a feature vanishes at a view where 20%
   of it would have been honest (progress.md Task 3 ruling 1).
7. **The yard hides whole in every room view**, reversing the spec's literal "yard
   is maskable fabric" — masking bought nothing a room camera sees and doubled
   per-room draw cost. Ruling: yard exempted, old per-room cost restored
   (progress.md Task 3 ruling 3).
8. **`facade_main_porch_8` is no longer a kit** — its roof decks are separate rows
   already covered by ruling 6; the row itself (slab/step/posts/rails/beam) is all
   `box()`, clipped per mesh like a wall. Found and fixed after a user screenshot
   showed the whole porch roof standing across the living view (progress.md, Task 3
   fix round 1).
9. **Spec §7's "roof over the room > 0.5" is not met** for four of five rooms
   (measured: living 0.329, kitchen 0.469, garage 0.145, mudroom 0.003, study
   0.013, at the first room-shell build) — a direct consequence of the eave-high
   box (choice A) plus each room's low camera. Ruling: accepted as the honest
   consequence of the ratified choice; recorded here rather than chasing the
   number with a camera change this arc (progress.md Task 3 ruling 4).
10. **The mudroom view reads darker.** Its own roof now stays (the camera sits 0.6
    above the eave and looks level through the wall, so the roof is never between
    it and the walled volume) where the old verdict removed the roof and let the
    sun in. Geometrically correct; a mood change, not fixed this arc.
11. **Porch exception to the height rule** (roof valleys): a gable sharing a span
    with the porch keeps the porch's own eave and stands proud by rise − 0.8, not
    its whole rise — the literal height rule would float the porch roof clear of
    its own posts (task-5-report.md).
12. **Dormer rule**: box bottom stands on the roof at its front face, not
    `parentY − 0.18` for the mini gable's eave, which would bury the box
    (task-5-report.md).
13. **Buried region, not a single plane**: `shellGable(..., buried)` takes a convex
    region (below every block deck plane, behind the face, forward of the block's
    back), emitted as one convex mesh per surviving piece — a single plane would
    also have cut the porch roof's own overhang in open air (task-5-report.md).
14. **No end bounds in the buried region** — the first draft had them and they kept
    the bay gable's west strip poking through the garage's gable-end wall under the
    rake; dropped (task-5-report.md).
15. **The saved-facade reproduction uses slot 13, not 14** — slot 13 straddles the
    partition and reproduces the user's own wedge from the living camera; slot 14
    buries identically but the partition hides it from that camera. Both shot
    before/after (task-5-report.md).

### Parked / known items (progress.md `minor (deferred)` lines and Task 3 look items)

- The mudroom is darker under its own kept roof (deviation 10 above) — the roof
  stays under choice A; not moved this arc, the user's mood call to make.
- The kitchen's mask box reaches the pantry nook behind the great room's west wall
  (tagged `kitchen`), which is why the kitchen view opens the mudroom's east gable
  end, the west gable end and the west skirt; the fix, if wanted, is the box's room
  tag, not the mask (task-3-report.md concerns).
- The study and mudroom room cameras were not moved this arc (progress.md Task 3
  ruling 4) — the mood is the user's call before any camera pass.
- A height-rule gable's eave trim mitres at a small diagonal cut where the main
  deck plane drops under it in front of the wall — a return board would be a
  follow-up (task-5-report.md concerns).
- The bay gable's front infill carries an unclipped 5.6..5.78 sliver at the wall
  head (spec §6's literal wording, not its intent) — invisible in practice
  (task-5-report.md concerns; progress.md Task 5 review minors).
- Coincident internal section caps add 16 never-visible exterior draws; a later
  pass could skip caps whose cut faces are all buried (task-5-report.md concerns).
- The hip garage variant leaves a ~0.3 square end at the west hip plane where the
  bay-gable meet was solved against the street deck only (progress.md Task 5
  review minors).
- `FEATURE_VERTS` holds every facade row's vertices for the page's life — a few
  thousand floats per row, ~30 rows in the worst-case facade (task-5-report.md
  concerns).
- The vault is still gated off for a ridge-z main roof (pre-existing, task-4
  concern) — `vaultSection` would need to become axis-generic.
- Several stale comments flagged for a later prune, none load-bearing: a
  "ghost and cutaway verdicts" phrase at house.js ~5069-5072/~4740, ~80 lines of
  marked retired-solver history comments, a `porchAt`/test-comment naming mismatch
  ("roof deck"/"rails" for what are now gable_8 rows), and a study `south_wall`
  pin ceiling (0.36) slightly looser than the physical number (0.358).
- `test_house_live.py`'s `scenario_clipper_cuts_convex_meshes` doesn't assert `nW`
  exactly (only ≥ 1); crossing de-dup uses 1e-6 against an `EPS` of 1e-7 at house
  scale (progress.md Task 1 minor).
- `house_features.js`'s `box()` helper doesn't stamp `userData.convex` (inert: all
  three fixtures it builds are kits) (progress.md Task 2 minor).

Device verification: **none of the code in this arc has been confirmed on the live
add-on**, with one exception — the user viewed v2.499.54 (the room-shell fix round,
before the roof-valley fix) on a device and reported the saved-facade wedge over
the study that Task 5 then fixed. That sighting was of an interim commit, not the
arc's finished state; the finished state (through v2.499.56) is NOT device-verified.
