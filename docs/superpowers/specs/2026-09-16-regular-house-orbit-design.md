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

**New pieces**: `north_wall_east` (the main's north wall from x 6.85 to 14.65, one window), `mudroom_front` (the mudroom's full-height street face on the garage block, `room: 'mudroom'` — the old front band folded in), `east_wall` (rebuilt: the main's full east side at x 14.65, -6.1..14.55, exterior; the old east wall at x 6.85 becomes the interior partition between kitchen/living and the future rooms/study, registered as `east_partition` for cutaways), `garage_block_north`, `garage_block_west` (one window), `garage_block_roof_*`, `roof_main_*` (re-extended to the full main), `back_door` (north wall, `room: 'kitchen'`, `entry: 'back_door'`), `future_room_partition` (between east room and back room, `room: null` — inert), `back_patio` (slab, not registered).

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

- **Eight stops** at 45°, index 0..7, stop 0 = today's exterior view. Pivot `P = (-1.8, 4.0, 4.2)` (the two-block bounding box centre in x/z, `EXT_AT.y` kept). Radius and height come from today's `EXT_POS` measured against the pivot (r ≈ 84 in x/z, y = 31); stop k sits at `P + (r cos(a0 + k·45°), 31, r sin(a0 + k·45°))` with `a0` = today's azimuth, so stop 0 is pixel-identical to the current resting view. `EXT_AT` becomes `P` for every stop.
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

Shipped as commits 2fb22a4..cdf334f, v2.499.31–v2.499.37, across four implementation tasks (task
reports: `.superpowers/sdd/2026-09-16-regular-house-orbit/task-{1,2,3,4}-report.md`). None of it is
device-verified.

### 10.1 Per-view budget, before/after (quality=high, `--day`)

BASE = 2fb22a4 (pre-arc). AFTER = canonical after task 2's fix round (v2.499.33), which is what
tasks 3 and 4 build on; task 3's facade re-derivation shifted a few window positions by less than
one slot width, which moves the exterior's own tris slightly further (see 10.1.1) without changing
which pieces are in frustum.

| view | in-frustum before | in-frustum after | Δ | tris before | tris after |
|---|---|---|---|---|---|
| exterior | 1448 | 1403 | -45 | 306710 | 298126 |
| kitchen | 470 | 476 | +6 | 116664 | 116852 |
| living | 710 | 700 | -10 | 135880 | 135972 |
| mudroom | 406 | 400 | -6 | 46746 | 46506 |
| garage | 747 | 753 | +6 | 109774 | 110022 |
| study | 321 | 318 | -3 | 26644 | 26476 |

`buildMs` 1156 → 946-1058 across runs; cap 1500. Scene meshes 2100 → 2055; materials 1475/1481 →
1462/1468; geometries 1522 → 1488. Every Δ is traced to specific pieces in task 2's report: kitchen
+6 and garage +6 are new geometry (`north_wall_east`, the future-room floors/partition, the back
patio slab; `garage_block_west/north`, the block roof's new `_end_east`) now standing in a camera's
existing frustum, not noise.

### 10.1.1 Exterior after task 3 (facade faces re-derived)

Re-deriving the facade grammar onto the two blocks re-snapped a few features by up to one slot
width (see 10.4), which moved a handful of window boxes without adding or removing any:

| build | in-frustum | tris | meshes | buildMs |
|---|---|---|---|---|
| canonical, after task 2 | 1403 | 298126 | 2055 | 946-1058 |
| canonical, after task 3 (faces re-derived) | 1403 | 298214 | 2055 | 934 |
| worst case (`--facade worst`) | 1496 | 298782 | 2148 | 1014 |

### 10.2 Roof-form variants (task 2; `--roof` on `tools/house_probe.py`)

Both blocks canonically build `{form:'gable', ridge:'x'}`. The brief's hip variant was budgeted for
both blocks and for the mixed form the spec names in §3 (main hip ridge `x`, garage hip ridge `z` —
the tract-house garage look):

| build | in-frustum | tris | meshes | buildMs |
|---|---|---|---|---|
| canonical (gable, ridge x, both blocks) | 1403 | 298126 | 2055 | 946 |
| hip, ridge x, both blocks (garage clamps to a pyramid — its ridge-x depth is short) | 1397 | 298014 | 2049 | 976 |
| hip, main ridge x + garage ridge z (spec §3's variant) | 1399 | 298046 | 2051 | 932 |

The hip form costs nothing over gable (four extruded decks replace four boxes plus two clapboard
infills); the pyramid case is two meshes lighter than the ridge-z hip (a pyramid has no ridge cap).
**Not recorded:** a plain gable-ridge-z budget for either block in isolation — only the hip variants
were probed, since ridge direction only visibly changes shape under `hip` (a gable roof's silhouette
is the same regardless of which axis the ridge runs along; the mechanism was still exercised, and
`chfRoofForms()` confirms `ROOF_FORMS` reports whichever form/ridge pair a given build used).

### 10.3 Per-stop budget, the eight-stop orbit (task 4; quality=high, `--day`, canonical roofs)

| stop | bearing | meshes | visible | in-frustum | tris | materials | geometries | buildMs |
|---|---|---|---|---|---|---|---|---|
| orbit0 | SE 43.6° (the resting view) | 2055 | 1403 | 1403 | 298214 | 1462 | 1489 | 1135 |
| orbit1 | S 88.6° | 2055 | 1403 | 1403 | 298214 | 1462 | 1489 | 1135 |
| orbit2 | SW 133.6° | 2055 | 1403 | 1400 | 297062 | 1462 | 1489 | 1135 |
| orbit3 | W 178.6° | 2055 | 1403 | 1403 | 298214 | 1462 | 1489 | 1135 |
| orbit4 | NW 223.6° | 2055 | 1403 | 1403 | 298214 | 1462 | 1489 | 1135 |
| orbit5 | N 268.6° | 2055 | 1403 | 1403 | 298214 | 1462 | 1489 | 1135 |
| orbit6 | NE 313.6° | 2055 | 1403 | 1400 | 297062 | 1462 | 1489 | 1135 |
| orbit7 | E 358.6° | 2055 | 1403 | 1403 | 298214 | 1462 | 1489 | 1135 |

`ghostLines=0 ghostDraws=0` at every stop (ghost edges stay OFF per the shell-occlusion law).
`buildMs` is one number (1135, ≤1500) because one build serves all eight stops. The worst stop is
1403 in-frustum / 298214 tris, shared by six of the eight (0, 1, 3, 4, 5, 7) — stops 2 and 6 each
drop three meshes. **1403 in-frustum is the exterior gate for later massing arcs.**

Stop 0 vs. task 3's plain exterior view, itemised (isolates the cost of the look-at pivot change,
deviation 1 below):

| | task 3 exterior | task 4 orbit0 | Δ |
|---|---|---|---|
| meshes | 2055 | 2055 | 0 |
| visible | 1403 | 1403 | 0 |
| in-frustum | 1403 | 1403 | **0** |
| tris | 298214 | 298214 | 0 |
| materials | 1462 | 1462 | 0 |
| geometries | 1489 | 1489 | 0 |
| buildMs | 934 | 1135 | +201 (run-to-run jitter on software WebGL — nothing was added to the build) |

The ~2.4° aim rotation from moving the look-at target to the shared pivot cost nothing: not one mesh
crossed the frustum boundary.

### 10.4 The computed facade slot table (task 3)

Both `FACES` (eave 5.6 on both):

| face | x0 | x1 | width | slots | slot width |
|---|---|---|---|---|---|
| `garage_block` | -18.20 | -7.15 | 11.05 | 6 (0-5) | 1.841667 |
| `main` | -7.15 | 14.65 | 21.80 | 12 (6-17) | 1.816667 |

Full 18-slot table (index, face, x0, x1, centre):

```
0  garage_block  -18.2000  -16.3583  -17.2792
1  garage_block  -16.3583  -14.5167  -15.4375
2  garage_block  -14.5167  -12.6750  -13.5958
3  garage_block  -12.6750  -10.8333  -11.7542
4  garage_block  -10.8333   -8.9917   -9.9125
5  garage_block   -8.9917   -7.1500   -8.0708
6  main            -7.1500   -5.3333   -6.2417
7  main            -5.3333   -3.5167   -4.4250
8  main            -3.5167   -1.7000   -2.6083
9  main            -1.7000    0.1167   -0.7917
10 main             0.1167    1.9333    1.0250
11 main             1.9333    3.7500    2.8417
12 main             3.7500    5.5667    4.6583
13 main             5.5667    7.3833    6.4750
14 main             7.3833    9.2000    8.2917
15 main             9.2000   11.0167   10.1083
16 main            11.0167   12.8333   11.9250
17 main            12.8333   14.6500   13.7417
```

`GARAGE_BAY_SLOTS = (0, 2)`, derived from the garage room's own x range (-18.2..-12.6) snapped to
the nearest slot **boundary** — reproduces the old 3-slot 'garage' face exactly, so `worst_case()`'s
dormer-exclusion zone and window-placement loop are numerically unchanged.

Canonical re-snap (nearest slot centre for a point feature, nearest slot boundary for an extent's
own edges; every element moved ≤ 1 slot):

```
ground: garage_door(0, span 3)  window(7)  porch(8, span 4)  window(9)  door(10)
        window(12)  window(15)  window(16)
roof:   gable(0, span 3)  gable(8, span 4)
```

### 10.5 Registered hand pieces

**KEPT (16), unchanged registration:** `north_wall`, `north_cladding`, `west_wall`, `west_skirt`,
`west_cladding`, `south_wall`, `garage_shell`, `garage_door`, `patio_slider`,
`living_back_room_door`, `living_study_door`, `yard`, `roof_main_north`, `roof_main_south`,
`roof_main_end_west`, `roof_main_end_east`.

**NEW (12):** `east_wall`, `east_partition`, `north_wall_east`, `garage_block_north`,
`garage_block_west`, `mudroom_front`, `garage_block_roof_north`, `garage_block_roof_south`,
`garage_block_roof_end_west`, `garage_block_roof_end_east`, `back_door`, `future_room_partition`.

**DELETED** (shell only, always empty of props/zones — grep-confirmed zero live references,
comments excepted): `massing_east_back_north/east/patio`, `massing_east_front_east/patio/south`,
`massing_front_roof` (+ its `_end_east`/`_north`/`_south` pieces), `massing_back_roof_back/front`
and `massing_back_roof_shed`, `massing_service_north/west/south` and `massing_service_roof` (+ its
`_end_west`/`_north`/`_south` pieces), `mudroom_cross_roof` (+ its `_north`/`_south` pieces),
`mudroom_front_cladding` (`mudFrontBandG`), `living_roof` (registered, always empty since H3), the
terrace slab and its furniture (table, three chairs, planter, bench, watering can, three pots) and
their now-dead `gChair`/`gTable`/`planter` builders.

Two of the three pieces spec §2 calls out as folding do fold, one does not — checked against the
actual commit (`git show 5d907b2 -- chauffeur/static/house.js`), not assumed: `mudroom_east_finish`
folds unchanged into `west_wall` (same plane, same room, same `[1,0,0]` flip), and `mudroom_roof`'s
geometry (the mudroom's street wall, its glazed door, and that door's jamb/hardware) folds unchanged
into `mudroom_front` — only the registry name retires. `mudroom_front_cladding` does not: its own
group (`mudFrontBandG`, a single box closing the gap above the mudroom's door wall up to the
underside of the now-deleted `mudroom_cross_roof`) is deleted outright, along with its registration.
The gap it used to close is now covered by the new `mudroom_front` wall — a fresh `shellWall` call
building the mudroom's whole street face from scratch, not the old band reparented — which the
commit's own comment describes as "that band re-authored as the face itself." See 10.7.9 for the
resulting spec-wording deviation.

### 10.6 The canonical facade mesh-count pin

**Changed.** Before this arc (the facade-generator arc's own pin): **1873** in-file. After task 2's
deletions: **1840** (-33 — seventeen shell pieces plus the terrace's furniture merge well with what
survives; the yard furniture they might have overlapped was already folded into `instanceYard`'s
InstancedMeshes). Task 3's facade re-derivation (renaming/repositioning features inside their own
per-feature `shellGroup()`s) did **not** move the count — confirmed by running the pin standalone
before the production edits landed. The count is camera-independent (`INVARIANT_JS` counts unmerged
survivors by scene-graph traversal, not frustum), so task 4's orbit — which only moves the camera —
left it unchanged and green at every stop.

### 10.7 Deviations from this spec's text, with the ruling for each

1. **Stop-0 look-at.** §4 states both that stop 0 is pixel-identical to today's resting view and
   that `EXT_AT` becomes the shared pivot for every stop; those cannot both hold, since today's
   `EXT_AT` (-3.9, 4.0, 7.0) and the pivot (-1.8, 4.0, 4.2) differ. **Ruling: the pivot wins** — one
   look-at for every stop keeps the orbit a true orbit. Stop 0's camera *position* is bit-for-bit
   `EXT_POS`; only the aim rotates, ~2.4°, so the house sits about 200px further left in the frame
   than before. Cost: none in the frustum (10.3); reversible with a stop-0 look-at special case if
   the shifted framing is disliked on device.
2. **One north window, not two.** §4 says "the main's north wall gets two windows + the back door";
   §2 already specifies `north_wall_east` (the only *new* north-wall piece) with **one** window.
   **Ruling: the plan's reading stands** — the "two windows" in §4 counts the whole north side,
   including the kitchen's own pre-existing north window on `north_wall`, not two new windows on the
   new piece. Cost if wrong: one window box to add later.
3. **Mudroom marker target.** §4's marker table implies `mudroom_front` is a valid marker target;
   measured, `chfNavProbe({piece:'mudroom_front'})` returns null from every exterior stop (that face
   sits behind the porch and, now, behind the main block). **Ruling: the marker rides
   `garage_block_roof_south`** (the same deck plane, carrying `room:'mudroom'`) instead — identical
   behaviour to the pre-arc marker, which rode the equivalent roof piece under its old name. Required
   by §8's "every marker keeps working."
4. **`mudroom_roof`'s geometry folds rather than deletes.** §2 deletes the registry *name*
   `mudroom_roof`; the geometry it owned is a real, visible assembly (the mudroom's street wall, its
   glazed door, the door's jamb and hardware), not roof decking. **Ruling: fold the geometry into
   `mudroom_front`** (both at identity, so every absolute coordinate is unchanged) rather than delete
   it — deleting it would have left the mudroom behind a blank wall with no door, which no other part
   of the spec asks for and which §8 ("nothing a person could do is removed") forbids.
5. **A yard tree moved.** Not named anywhere in the spec. Orbit stop 5 looks straight up the main
   block's north wall, and the largest tree in the back planting line stood exactly in the sightline
   to the back door, so `chfNavProbe({entry:'back_door'})` returned null and stop 5 drew zero
   markers — failing §7's "at least one marker drawn per stop." **Ruling: slide the one tree 2.45
   units west** (same z, same size, same silhouette from the street) to clear the sightline by
   roughly 3.8 units against its own ~3.5-unit crown half-width, verified per stop rather than by
   arithmetic alone. Warranted by §4's own "authored in this arc because the camera now sees it."
6. **Car plaques re-aim per landed stop.** Not addressed by the spec, which only describes the
   camera. A driveway plaque billboards toward the exterior eye at build time; with that eye now a
   ring, it would go edge-on (invisible) at seven of eight stops — a capability silently dropped.
   **Ruling: re-aim on landing** (`aimCarPlates()`, called from the tween callback, never per frame),
   preserving the existing behaviour without adding per-frame cost. Bay plaques keep facing their own
   fixed garage camera.
7. **Idle-return timer shortened via the real setting, not an init script.** §7's test list says
   "timer shortened via an init script." Measured: `nav.html`'s `chfIdleRemaining` floors *every*
   period at three seconds, so an init-script route (seeding a stale `chfPanelLastInput` in
   localStorage) also collapses the **screensaver's** own period to three seconds and races it — a
   screensaver that wins defers the return entirely. **Ruling (controller-approved, "the cheapest
   honest way"): seed `panel_idle_return_seconds` through the real settings path** instead
   (`storage.update_settings`, restored after), and use an init script only for the snap's own
   sessionStorage recorder.
8. **Hip end-plane pitch on a clamped block.** §3 does not specify what a clamped hip's end planes
   should do; the mechanism (inset clamp, degenerate to a pyramid) was built to keep the block's
   ridge height — and therefore its silhouette — independent of roof form. **Ruling: hold the ridge
   height fixed and let the end pitch steepen** rather than lowering the apex to equalize all four
   pitches, since the latter would make a block's height depend on which roof form it's wearing.
   Flagged as an open design question for spec 2, where ridge axis becomes a per-block user choice
   rather than a probe-only variant.
9. **§2's "fold" wording is loose for `mudroom_front_cladding`.** §2 groups it with
   `mudroom_east_finish` under "fold into the garage block's walls." Checked against the commit
   (10.5): `mudroom_east_finish` does fold (reparented unchanged), but `mudroom_front_cladding`'s own
   geometry is deleted outright — the new `mudroom_front` wall is fresh geometry covering the same
   visual gap, not the old band moved into a new parent. **Ruling: no code changed** (task 2 built it
   this way and review found no defect in the result — the street face is continuous either way); the
   deviation is purely that §2's text describes two different mechanisms with one word. Cost if the
   wording had been read literally: none — the geometry is correct regardless of which word describes
   how it got there.

### 10.8 Parked / deferred (not fixed in this arc; none blocking)

- The canonical facade mesh-count pin's own derivation comment miscounts the deleted pieces
  (`test_house_live.py` ~1325-1333: the comment says 17, lists 19 names, and the true count is 24).
  The pinned number itself (1840, see 10.6) is correct and verified by running the suite; only the
  comment explaining it is wrong.
- `north_wall_east` inherits `shellWall`'s plinth and corner boards, but the pre-existing
  `north_cladding` half of the same street run has neither — flagged in task 2 for an eyeball at the
  north orbit stops in task 4. Checked: task 4's report does not mention this seam, so it was not
  looked at and remains open, not resolved.
- `test_house_facade.py:127`'s comment still says "garage face" — a name retired when task 3 merged
  the garage and mudroom faces into `garage_block`.

- A ridge-`z` block renames its four roof pieces (`_north/_south/_end_west/_end_east` →
  `_west/_east/_back/_front`) by `shellGable`'s existing compass-suffix convention; `EXTERIOR_HINTS`'
  `garage_block_roof_south` row and the registry pin are canonical-only. Needs a ridge-relative
  suffix (or a `slopeRooms`-derived hint) before spec 2 makes ridge a per-block setting.
- A tap on the garage block's roof over the bay opens the mudroom — the shared south deck belongs to
  both rooms by the solver's existing half-space + corridor rule; pre-existing behaviour, recorded
  here per the brief.
- Hip form + `depthEnds` are untested together; the end triangles ignore the `depthEnds` shift
  (latent — needs a guard or a comment for spec 2).
- At orbit stops 3 and 7 the Garage/Mudroom markers project onto open sky, because their target deck
  (`garage_block_roof_south`) sits on the far block from those angles — the pre-existing marker rule,
  newly visible now that those stops exist.
- `get EXT_AT()` returns the live `ORBIT.pivot`, not a defensive clone (`house.js` ~9299);
  `orbitTo` accepts `NaN` and writes it straight into `ORBIT.stop` (`house.js` ~9993); `var EXT_AT`
  (`house.js` ~334) is dead code.
- The exterior chevrons (56px, `bottom:16px`) sit under the Argyle chat bar below roughly 816px
  viewport width; swipe and the arrow keys still work there.
- `nav.html`'s idle-snap tween is only observable on the slideshow path (the page navigates away
  immediately otherwise) — the comment beside it should say so.
- The arrow-key text-field guard is pinned live only against `#chat-input`; `#mw-volume`,
  `#cc-input-field` and `#mw-search` are covered by the same tag-based check but not individually
  exercised by a scenario.
- `scenario_study_sits_inside_the_main_block` does not assert `page.errors()` is empty
  (`test_house_live.py` ~221-251).
- `SHADOW_BOX.study` and the study reading-lamp's literal position are off-centre against the
  translated study span; visually fine per probe, left alone as a quality nicety rather than a
  correctness fix.
- Nothing pins `patio_slider`'s `twoSided` interior registration directly.
- `STUDY_DOOR_Z4` (`house.js` ~4161) duplicates `house_features.js:108`'s z value with only a
  comment binding the two together.
- A stale test comment still names `facade_wing_window_15/16` (`test_house_live.py` ~1337) after the
  face rename to `main`.
- The "no porch in the driveway" rule now spans slots 0-5 (garage + mudroom together); only slot 0 is
  exercised by a test.
