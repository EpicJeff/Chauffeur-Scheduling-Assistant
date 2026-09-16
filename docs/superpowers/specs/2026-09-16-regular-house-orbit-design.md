# The Home — the regular house + orbit (massing arc 1 of 3)

Binding spec, user-ratified 2026-09-16. First of three sequenced specs that turn the dollhouse into a house a generator can dress: **1. the regular house + orbit** (this document) → 2. blocks, materials, roof forms → 3. style kits. Every prior house law travels with it: batching (`2026-09-10-house-batching-design.md`), the lifecycle law (mkTex owns textures; cgeo owns geometry), the shell registry law (`2026-09-11-house-shell-occlusion-design.md`: every shell piece registers through `regFabric`/`shellRegister`; occlusion is cutaways, ghost edges stay OFF), and the facade generator (`2026-09-15-house-facade-generator-design.md`: slots, spans, palette names, saved facades).

## 1. Why

The facade arc showed that a photo match is decided by massing and material, not by window placement — and that the current massing is a hand-drawn house: an east wing projecting past the front, a patio notch, a rear room and a rear service block that hold nothing, and eleven roof pieces meeting at odd angles. A generator cannot put "a hip roof" on that. The exterior is also viewable from exactly one angle, which hides the mudroom, half-hides the garage, and would hide a side-loading garage entirely.

This arc makes the house **two rectangles with two block roofs** and lets the panel **orbit** it in eight stops. Interiors do not move except the study, which slides north by one translation to sit inside the main rectangle. Nothing a person can do today is lost: the rear room and the patio notch are shell with no contents (ruled by the user 2026-09-16: "no purpose other than visual"); they become two enclosed, unfurnished rooms inside the main rectangle — the house's future expansion areas — and the kitchen's slider and the living room's back door keep opening into them.

## 2. Footprint (world units; street to the south, +z toward the street)

| block | x | z | size | holds | front face z |
|---|---|---|---|---|---|
| **main** | -7.15 .. 14.65 | -6.10 .. 14.55 | 21.8 × 20.65 | kitchen (north-west), living (south-west), pantry closet, the **study** (south-east, x 6.85..14.65, z 7.65..14.55 — translated north by 2.17: `house_study.js` `NORTH 9.88 → 7.71`, `SOUTH 16.62 → 14.45`, `EAST`/`WEST` unchanged, plus `STUDY_POS/AT` by the same 2.17), and two **future rooms** north of the study: the *east room* (x 6.85..14.65, z 1.5..7.65, the old patio notch) and the *back room* (x 6.85..14.65, z -6.1..1.5, the old rear room) — floors, walls and their existing openings only; no props, no zones, no cameras | 14.55 (unchanged) |
| **garage block** | -18.20 .. -7.15 | -6.10 .. 10.10 | 11.05 × 16.20 | garage (x -18.2..-12.6), mudroom (x -12.6..-7.15); the old rear service void becomes garage/mudroom depth | 10.10 (unchanged) — set back 4.45 behind the main; the first block with a `depth` a later arc varies |

The main rectangle is the whole east side now; nothing projects past the front and nothing is notched. The kitchen's `patio_slider` (x 6.85, z 5.80) becomes an INTERIOR opening into the east room, registered like `living_study_door` (twoSided, `room: 'kitchen'`), and `living_back_room_door` stays as the living room's opening into the back room. The exterior "Kitchen" marker moves to a new **back door** on the main's north wall (x ≈ -2.0, `entry: 'back_door'`), with a back patio slab outside it in the yard. The future rooms get one exterior window each on the east wall so the orbit's east stops do not read as blank.

**Deleted** (shell only, no props, no zones): `massing_east_back_north/east/patio`, `massing_east_front_east/patio/south`, `massing_front_roof`, `massing_back_roof_*` and `massing_back_roof_shed`, `massing_service_north/south/west/roof`, `mudroom_cross_roof`, `mudroom_roof`, the terrace slab and its furniture, `living_roof` (registered, empty, inert since H3). `mudroom_front_cladding` / `mudroom_east_finish` fold into the garage block's walls.

**Kept as-is**: `north_wall` (grows east to x 14.65), `north_cladding`, `west_wall`, `west_skirt`, `west_cladding`, `south_wall` (grows east to x 14.65 — the study's street face is part of it now), `garage_shell`, `garage_door`, `patio_slider` (re-registered as interior), `living_back_room_door`, `yard`, every interior zone, every camera except the study's.

**New pieces**: `east_wall` (rebuilt: the main's full east side at x 14.65, -6.1..14.55, exterior; the old east wall at x 6.85 becomes the interior partition between kitchen/living and the future rooms/study, registered as `east_partition` for cutaways), `garage_block_north`, `garage_block_west` (one window), `garage_block_roof_*`, `roof_main_*` (re-extended to the full main), `back_door` (north wall, `room: 'kitchen'`, `entry: 'back_door'`), `future_room_partition` (between east room and back room, `room: null` — inert), `back_patio` (slab, not registered).

## 3. Roofs — two block roofs, both configurable

Every block roof is `{form: gable | hip, ridge: x | z, pitch}`; nothing about ridge direction is fixed. `shellGable` grows the `hip` form (two trapezoid decks along the ridge plus two triangular decks on the ends, four registered pieces, same eave/pitch parameters, no gable-end infill) and its existing `alongZ` flag becomes the `ridge` parameter.

| roof | extent | canonical | why canonical |
|---|---|---|---|
| `roof_main` | main block + overhang (21.8 × 20.65) | `gable`, ridge `x` | today's main roof, now reaching the east wall; the study's separate front gable is gone and its street face sits under the main eave like the rest of the front |
| `garage_block_roof` | garage block + overhang | `gable`, ridge `x` | today's service-roof direction; the garage-door front gable stays as the **facade feature** it already is (`gable` at slots 0–2), so the canonical look is unchanged |
| porch roof | the facade porch feature, as today | per feature | — |

Eleven roof calls become two block roofs plus the facade features. Generated street gables/dormers sit on `roof_main` or `garage_block_roof` per face. With ridge `z` a block's street face IS a gable end (the tract-house garage look) — a spec-2 block parameter, but the mechanism ships here so canonical and the ridge-z variant are both built and budgeted.

Coplanar-run roof features across the old garage/mudroom boundary are now trivially one plane.

## 4. Orbit

- **Eight stops** at 45°, index 0..7, stop 0 = today's exterior view. Pivot `P = (-1.8, 4.0, 4.2)` (the three-block bounding box centre in x/z, `EXT_AT.y` kept). Radius and height come from today's `EXT_POS` measured against the pivot (r ≈ 84 in x/z, y = 31); stop k sits at `P + (r cos(a0 + k·45°), 31, r sin(a0 + k·45°))` with `a0` = today's azimuth, so stop 0 is pixel-identical to the current resting view. `EXT_AT` becomes `P` for every stop.
- **Hand path**: two chevron buttons at the bottom corners of the exterior overlay (touch-sized, 56px), a horizontal swipe ≥ 60px on the canvas at the exterior level, and `?angle=N` on `/house`. Keyboard: ← / →. Interiors ignore all of it (rooms stay fixed dioramas; the back control still exits to the CURRENT stop).
- **Motion**: one tween per step through the existing `tween` slot (same easing/duration as `goExterior`), render-on-demand intact — the scene renders during the tween and idles after. `solveShell` runs once at settle with `subject === null` (every piece solid), exactly as the exterior does today.
- **Idle return**: the panel's `panel_idle_return_seconds` timer already returns to the home board; at the exterior level it also snaps the orbit to stop 0 (one tween) so the wall always rests on the street view.
- **Lighting**: the sun rig is unchanged (SUN_OFF, shadows, fillN). From the north stops the facades read in hemisphere/fill light — honest for a fixed sun, and it keeps the interior lighting laws untouched. If the north read is too flat in the probe, a second static fill aimed at the back wall is the ONE permitted lighting change, gated by the same kitchen-ratio gate the quality pass used.
- **What orbit exposes** (authored in this arc because the camera now sees it): the main's north wall gets two windows + the back door; the main's east wall gets three windows (study, east room, back room); the garage block's west wall gets one window; the back patio slab; nothing else. The street, curb, bus, driveway and front walk stay south.
- **Markers**: `EXTERIOR_HINTS` already derive pixels from world boxes via `chfNavProbe`; a hint whose target is occluded at the current stop returns null and is not drawn. `back_door` replaces `patio_slider` as the Kitchen entry (the slider is interior now).

## 5. Facade slot table re-derivation

`services/house_facade.py` `FACES` and the JS mirror become two faces: **garage block front** (`x -18.20..-7.15`, z 10.10 — 6 slots at 1.842; garage door + mudroom front on one face) and **main front** (`-7.15..14.65`, z 14.55 — 12 slots at 1.817; the old main and wing faces merged). Eighteen slots still (0–5, 6–17). `CANONICAL` re-snaps by the same nearest-slot rule (expected: windows 7, 9, 12; porch 9 span 4; door 10; the two old wing windows at 14 and 15; garage door 0 span 3; gables 0/3 and 9/4 — the plan pins the exact numbers after computing them, never by hand). The Python/JS parity pin and every normalize law hold unchanged; `worst_case()` re-runs. The `roof` column per face is `garage_block_roof` / `roof_main`.

## 6. Budget and pins (all quality=high `--day`)

- Re-baseline every view AND every orbit stop; record before/after. Expectation: exterior draw calls fall (nine roof/wall pieces gone, a handful added). The exterior gate for later arcs becomes the WORST stop's in-frustum count.
- Registry expected-name tables in `tests/test_house_live.py` rewritten to the §2 lists; the canonical facade mesh pin re-recorded RED-first.
- `buildMs` ≤ 1500 as before.

## 7. Tests

- Pure: slot table from the two faces (garage block 6 / main 12), `CANONICAL` normal + idempotent, worst case within caps.
- Live (`tests/test_house_live.py`): footprint pin (registered set equals the §2 kept+new list; none of the deleted names); 8-stop orbit walk — every stop settles with zero console errors, `chfHouseMode()==='exterior'`, at least one marker drawn per stop, and every room entrance reachable from some stop (`chfNavProbe({entry|piece})` non-null at ≥1 stop); `?angle=3` boots at stop 3; a swipe advances one stop; idle-return snaps to 0 (timer shortened via an init script); study lean-in still frames the desk (`STUDY_POS/AT` translated with the study); the back door enters the kitchen and the slider still leans from inside; the facade scenarios (canonical pin, worst case, exit tap) green.
- Probe: `tools/house_probe.py --angle N` (default 0) and `--views orbit` = all eight stops.

## 8. Hand path summary

Orbit chevrons + swipe + `?angle=`; the Home config section unchanged in this arc (blocks/materials editing is spec 2). Nothing a person could do is removed: the rear room and terrace had no interactions; the patio slider and the back-room door become interior openings into the future rooms; every zone, every card and every marker keep working (the exterior Kitchen marker moves to the back door).

## 9. Task order

1. Study translation + camera (smallest, isolates the module move).
2. Footprint: delete the east/rear/service shell, extend the main's north/south/roof to x 14.65, rebuild the east wall, enclose the two future rooms, build the garage block walls/roof, back door/windows/patio slab, `shellGable` hip form + `ridge` parameter; registry tables + footprint pin (RED first); budget re-baseline (canonical and the ridge-z variants of both blocks).
3. Facade faces re-derived (Python + JS), canonical amended, parity/worst-case pins green.
4. Orbit: stops, tween, chevrons/swipe/URL/keys, idle snap, marker culling, probe `--angle`; orbit live scenario; per-stop budget table.
5. Wrap: capabilities entry, style bible (massing section), spec §10, memory.

Each task bumps `config.yaml`, sweeps (`env -u HA_BASE_URL python chauffeur/tools/test.py`, run once, foreground), commits, pushes.

## 10. Results

Filled at wrap: per-view and per-stop in-frustum/buildMs before/after (canonical, and ridge-z for each block), the new registered-piece list, the re-recorded canonical mesh pin, deviations.
