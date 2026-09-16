# The Home — the regular house + orbit (massing arc 1 of 3)

Binding spec, user-ratified 2026-09-16. First of three sequenced specs that turn the dollhouse into a house a generator can dress: **1. the regular house + orbit** (this document) → 2. blocks, materials, roof forms → 3. style kits. Every prior house law travels with it: batching (`2026-09-10-house-batching-design.md`), the lifecycle law (mkTex owns textures; cgeo owns geometry), the shell registry law (`2026-09-11-house-shell-occlusion-design.md`: every shell piece registers through `regFabric`/`shellRegister`; occlusion is cutaways, ghost edges stay OFF), and the facade generator (`2026-09-15-house-facade-generator-design.md`: slots, spans, palette names, saved facades).

## 1. Why

The facade arc showed that a photo match is decided by massing and material, not by window placement — and that the current massing is a hand-drawn house: an east wing projecting past the front, a patio notch, a rear room and a rear service block that hold nothing, and eleven roof pieces meeting at odd angles. A generator cannot put "a hip roof" on that. The exterior is also viewable from exactly one angle, which hides the mudroom, half-hides the garage, and would hide a side-loading garage entirely.

This arc makes the house **three rectangles with four roofs** and lets the panel **orbit** it in eight stops. Interiors do not move except the study, which slides north by one translation. Nothing a person can do today is lost: the rear room and the patio notch are shell with no contents (ruled by the user 2026-09-16: "no purpose other than visual"); the kitchen's patio slider survives on the flat east wall and still opens onto a patio.

## 2. Footprint (world units; street to the south, +z toward the street)

| block | x | z | size | holds | front face z |
|---|---|---|---|---|---|
| **main** | -7.15 .. 6.85 | -6.10 .. 14.55 | 14.0 × 20.65 | kitchen (north), living (south), pantry closet | 14.55 (unchanged) |
| **garage block** | -18.20 .. -7.15 | -6.10 .. 10.10 | 11.05 × 16.20 | garage (x -18.2..-12.6), mudroom (x -12.6..-7.15); the old rear service void becomes garage/mudroom depth | 10.10 (unchanged) — set back 4.45 behind the main; this is the first block with a `depth` a later arc varies |
| **study block** | 6.85 .. 14.65 | 7.65 .. 14.55 | 7.8 × 6.9 | the study, translated north by 2.17 (`house_study.js`: `NORTH 9.88 → 7.71`, `SOUTH 16.62 → 14.45`; `EAST`/`WEST` unchanged) | 14.55 — flush with the main |

Everything east of x 6.85 and north of z 7.65 is outside: a back patio slab (concrete, 6.85..12.0 × 1.5..7.0) sits against the main's east wall under the kitchen's existing patio slider, which stays at z 5.80 on the main's east face and keeps its marker (`patio_slider` → Kitchen).

**Deleted** (shell only, no props, no zones): `massing_east_back_north/east/patio`, `massing_east_front_east/patio/south`, `massing_front_roof`, `massing_back_roof_*` and `massing_back_roof_shed`, `massing_service_north/south/west/roof`, `mudroom_cross_roof`, `mudroom_roof`, the terrace slab and its furniture, `living_back_room_door` (`house_features.js`) and the door piece it targets, `living_roof` (registered, empty, inert since H3). The `mudroom_front_cladding` / `mudroom_east_finish` pieces fold into the garage block's walls.

**Kept as-is**: `north_wall`, `north_cladding`, `west_wall`, `west_skirt`, `west_cladding`, `south_wall`, `east_wall` (now runs the main's full east side, -6.1..7.65 exterior, 7.65..14.55 shared with the study block), `garage_shell`, `garage_door`, `patio_slider`, `yard`, every interior zone, every camera except the study's.

**New pieces**: `garage_block_north`, `garage_block_west` (windows per kit defaults), `garage_block_roof_*`, `study_south` (a facade face; its windows come from the slot strip), `study_east`, `study_north` (exterior, z 7.65, one window), `study_roof_*`, `back_door` (main north wall, x ≈ -2.0, into the kitchen — a registered piece with `room: 'kitchen'` and `entry: 'back_door'`), `back_patio` (slab, not registered).

## 3. Roofs — four calls

| roof | extent | form | ridge |
|---|---|---|---|
| `roof_main` | main block + overhang | gable (ridge along x, as today) — `form` is a parameter from day one: `gable_side \| gable_front \| hip` | y = eave + half-depth · tan(pitch) |
| `garage_block_roof` | garage block + overhang | gable, ridge along z (a front-facing gable end over the garage door, as the photo family has) | — |
| `study_roof` | study block + overhang | gable_front (ridge along z) | — |
| porch roof | the facade porch feature, as today | gable / shed per the feature | — |

`shellGable` gains a `hip` form: two trapezoid decks along the ridge plus two triangular decks on the ends, four registered pieces, same eave/pitch parameters, no gable-end infill. Ridge heights are derived, never typed. Eleven roof calls become four (plus facade features), and the generated street gables/dormers from the facade arc sit on `roof_main`, `garage_block_roof` or `study_roof` per face — the facade slot table's `roof` column is re-derived from these three.

The roof plane of the garage block's front is now the gable END (ridge along z), so the facade arc's `garage_gable` feature is no longer needed to fake it; the canonical facade drops that roof entry (spec 2026-09-15 §2.2 amended: garage face roof = `eave`, the block's own gable end is the front). Coplanar-run roof features across garage+mudroom are now trivially one plane.

## 4. Orbit

- **Eight stops** at 45°, index 0..7, stop 0 = today's exterior view. Pivot `P = (-1.8, 4.0, 4.2)` (the three-block bounding box centre in x/z, `EXT_AT.y` kept). Radius and height come from today's `EXT_POS` measured against the pivot (r ≈ 84 in x/z, y = 31); stop k sits at `P + (r cos(a0 + k·45°), 31, r sin(a0 + k·45°))` with `a0` = today's azimuth, so stop 0 is pixel-identical to the current resting view. `EXT_AT` becomes `P` for every stop.
- **Hand path**: two chevron buttons at the bottom corners of the exterior overlay (touch-sized, 56px), a horizontal swipe ≥ 60px on the canvas at the exterior level, and `?angle=N` on `/house`. Keyboard: ← / →. Interiors ignore all of it (rooms stay fixed dioramas; the back control still exits to the CURRENT stop).
- **Motion**: one tween per step through the existing `tween` slot (same easing/duration as `goExterior`), render-on-demand intact — the scene renders during the tween and idles after. `solveShell` runs once at settle with `subject === null` (every piece solid), exactly as the exterior does today.
- **Idle return**: the panel's `panel_idle_return_seconds` timer already returns to the home board; at the exterior level it also snaps the orbit to stop 0 (one tween) so the wall always rests on the street view.
- **Lighting**: the sun rig is unchanged (SUN_OFF, shadows, fillN). From the north stops the facades read in hemisphere/fill light — honest for a fixed sun, and it keeps the interior lighting laws untouched. If the north read is too flat in the probe, a second static fill aimed at the back wall is the ONE permitted lighting change, gated by the same kitchen-ratio gate the quality pass used.
- **What orbit exposes** (authored in this arc because the camera now sees it): the main's north wall gets two windows + the back door; the garage block's west wall gets one window; the study block's north and east walls get one window each; the back patio slab; nothing else. The street, curb, bus, driveway and front walk stay south.
- **Markers**: `EXTERIOR_HINTS` already derive pixels from world boxes via `chfNavProbe`; a hint whose target is occluded at the current stop returns null and is not drawn. `back_door` joins the table as a Kitchen entry.

## 5. Facade slot table re-derivation

`services/house_facade.py` `FACES` and the JS mirror become: garage block front (`x -18.20..-7.15`, z 10.10 — garage door slots + mudroom-front slots on ONE face now), main (`-7.15..6.85`, z 14.55), study (`6.85..14.65`, z 14.55). The mudroom face merges into the garage block face (6 slots at 1.84); main 8; study 4 — eighteen still. `CANONICAL` moves nothing except dropping the garage gable roof entry and re-indexing the garage-door span (slots 0–2 of a 6-slot face). The Python/JS parity pin and every normalize law hold unchanged; `worst_case()` re-runs.

## 6. Budget and pins (all quality=high `--day`)

- Re-baseline every view AND every orbit stop; record before/after. Expectation: exterior draw calls fall (nine roof/wall pieces gone, a handful added). The exterior gate for later arcs becomes the WORST stop's in-frustum count.
- Registry expected-name tables in `tests/test_house_live.py` rewritten to the §2 lists; the canonical facade mesh pin re-recorded RED-first.
- `buildMs` ≤ 1500 as before.

## 7. Tests

- Pure: slot table from the three faces (garage 6 / main 8 / study 4), `CANONICAL` normal + idempotent, worst case within caps.
- Live (`tests/test_house_live.py`): footprint pin (registered set equals the §2 kept+new list; none of the deleted names); 8-stop orbit walk — every stop settles with zero console errors, `chfHouseMode()==='exterior'`, at least one marker drawn per stop, and every room entrance reachable from some stop (`chfNavProbe({entry|piece})` non-null at ≥1 stop); `?angle=3` boots at stop 3; a swipe advances one stop; idle-return snaps to 0 (timer shortened via an init script); study lean-in still frames the desk (`STUDY_POS/AT` translated with the block); patio slider still enters the kitchen; the facade scenarios (canonical pin, worst case, exit tap) green.
- Probe: `tools/house_probe.py --angle N` (default 0) and `--views orbit` = all eight stops.

## 8. Hand path summary

Orbit chevrons + swipe + `?angle=`; the Home config section unchanged in this arc (blocks/materials editing is spec 2). Nothing a person could do is removed: the rear room and terrace had no interactions; the patio slider, every zone, every card and every marker keep working.

## 9. Task order

1. Study translation + camera (smallest, isolates the module move).
2. Footprint: delete the east/rear/service shell, build the garage block walls/roof and the study block walls/roof, back door/windows/patio slab, `shellGable` hip form; registry tables + footprint pin (RED first); budget re-baseline.
3. Facade faces re-derived (Python + JS), canonical amended, parity/worst-case pins green.
4. Orbit: stops, tween, chevrons/swipe/URL/keys, idle snap, marker culling, probe `--angle`; orbit live scenario; per-stop budget table.
5. Wrap: capabilities entry, style bible (massing section), spec §10, memory.

Each task bumps `config.yaml`, sweeps (`env -u HA_BASE_URL python chauffeur/tools/test.py`, run once, foreground), commits, pushes.

## 10. Results

Filled at wrap: per-view and per-stop in-frustum/buildMs before/after, the new registered-piece list, the re-recorded canonical mesh pin, deviations.
