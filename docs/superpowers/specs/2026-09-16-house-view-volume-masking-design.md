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

Filled at wrap: before/after per view and per stop, buildMs delta, the mask-fraction table per room, the hip/ridge-z probe numbers, the valley heights per feature, deviations.
