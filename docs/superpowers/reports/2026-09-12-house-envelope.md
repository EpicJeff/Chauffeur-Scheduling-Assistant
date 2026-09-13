# Full-house envelope and sitting porch

Task 8 replaces the partial roof assemblies with a connected exterior around the existing rooms. The user revised the roof direction, setback, porch size, eave heights, side-roof drainage, front-right pitch, and garage gable while reviewing screenshots. Those instructions govern this result; spec section 10 records them.

## Layout

World units are model coordinates, not claimed construction dimensions. The reference supplies the farmhouse vocabulary and approximate relative massing; the numbers below are architectural assumptions constrained by the built room coordinates.

| Part | Bounds or size | Basis |
|---|---|---|
| Main envelope | x -7.15..6.85; z -6.10..14.55 | Existing 13-unit floor width plus wall thickness; existing great-room depth |
| Rear service extension | x -18.20..-7.15; z -6.10..2.12 | Garage's west edge and main rear alignment; width about 0.85 of the built floor width |
| Front east wing | x 6.85..10.40; z 9.80..14.55 | Width about 0.27 of the built floor width; preserve terrace's south edge |
| Rear east wing | x 6.85..10.40; z -6.10..4.20 | Same width, stopping at the terrace's north edge |
| Terrace | x 6.86..10.30; z 4.20..9.80 | Existing paved footprint preserved |
| Sitting porch | 8.4 wide by 4.6 deep, centered on x 1.3 | Two benches beside a clear central approach; offset door preserved |
| Setback | Street, curb, sidewalk, mailbox and bus +8 z | Room floor plans and room cameras remain fixed |

Main, service/garage, and front east eaves meet the existing great-room wall head at y=5.6. The main and service ridges run along x with 22.5-degree slopes. The front east gable uses the same pitch. The porch and garage gables project along z toward the street and retain the steeper farmhouse pitch. The rear east shed falls from the house toward the outer east wall, with 1.0 unit of fall across 3.55 units of run. Its front and back infill follow the roof slope.

The old 7-unit exterior wall extensions and the mudroom's above-crown return are lowered. The flat mudroom roof and the old separate garage roof are removed under their replacements. Garage upper cladding and a band over the mudroom door wall close the new roof connections. Existing room floors, fixtures, zone positions, and room camera transforms remain fixed.

The porch contains four timber posts, beams, two benches, a full deck, central steps, and a paved front walk. Driveway joints, lawn, fence, mailbox, and street move or extend with the setback. The exterior camera and its shadow coverage frame the larger property.

## Ownership and navigation

Each pitched plane owns its geometric normal, shell registration, merge boundary, and ghost outline. Gable infill is registered separately. The registry drives per-piece batching, so new roof pieces cannot be omitted from a hand-maintained merge list.

The south main facade and porch enter the kitchen; east wall and patio slider enter living. The front service slope enters the mudroom, while its rear slope and unbuilt walls remain inert. The garage gable and door enter the garage. The new visible roof targets replace west-skirt and garage-shell pixels obscured by the new geometry. Real mouse tests exercise these entries.

The legacy `mudroom_roof` registry name now owns only the front wall. Its normal changes from up to south to match that remaining face. The registered west and north cladding are excluded from room subjects. The mailbox now belongs to the yard: moving a street prop must not enlarge the kitchen's solver subject. No artificial room-box freeze or per-room hide array is introduced.

The rear window is moved inboard to x=5.20; its frame ends at x=6.67, inside the corner trim, and its glazing sits on the exterior north face. The patio slider sits on the east exterior face, with a threshold and handle. It is decorative room fabric, not a new zone.

New windows use black frames and authored dark panes. Two panes glow at night; their unique materials survive merging and are updated by the existing night pass.

## Planting and outdoor furniture

Both east foundation beds and their plants move 3.55 units east. The front bed splits around the deeper porch, with displaced plants reseated beside the porch steps. No planting entries are deleted. The rear west tree moves clear of the service extension; the gold tree moves clear of the front east wing. Patio furniture and pots shift locally to clear the slider and new wing edges; the patio footprint remains intact.

## Solver derivation

There are 42 registered pieces. The yard uses hide mode; the remaining registrations use ghost mode (the empty living-roof placeholder has no edge geometry). The test pins the complete registry and every room's non-solid set.

For a piece with normal n and box center p, the solver requires positive dot(n, camera-p), negative dot(n, subject-p), and overlap with the padded camera-to-subject bounds. The final kitchen subject center is approximately (-1.945, 1.6505, 0); living is (0, 0.9940, 9.6624). Their original camera positions are unchanged. Representative signed values below explain the changed verdicts rather than treating runtime output as the specification:

| Piece | Kitchen camera / subject | Living camera / subject | Consequence |
|---|---:|---:|---|
| Main south slope | 5.99 / -9.34 | 11.84 / -6.25 | Ghost in both; both corridors overlap |
| Main east gable | 7.51 / -9.03 | -1.89 / -7.09 | Kitchen ghosts; living camera is inward |
| Porch west slope | -4.84 / -3.24 | 2.50 / -4.89 | Living ghosts; kitchen camera is inward |
| Porch east slope | 10.34 / -6.94 | 6.95 / -6.37 | Ghost in both |
| Porch front | -2.39 / -19.39 | 7.11 / -9.73 | Living ghosts; kitchen camera is behind it |
| Front wing north slope | 2.30 / -0.02 | 0.88 / -4.32 | Both ghost after matching the main pitch |
| Rear wing patio wall | 12.80 / -4.20 | 22.30 / 5.46 | Kitchen ghosts; living subject is outside |

The kitchen's front-wing north-slope subject value is close to zero; the authored table protects that boundary without modifying the normal or adding a special-case hide rule. The garage's conservative corridor also overlaps the mudroom front wall by about 0.05 units in x, so that wall ghosts in the garage view. The roof and wall normals remain geometrically meaningful.

## Render budgets

Identical high-quality fixture method to the navigation baseline, with the expanded exterior camera and new geometry:

| View | v2.496 meshes | v2.497 meshes | Ghost-line draws | Estimated main-pass draws | Mesh ceiling |
|---|---:|---:|---:|---:|---:|
| Exterior | 1273 | 1367 | 0 | 1367 | 1400 |
| Kitchen | 417 | 445 | 14 | 459 | 459 |
| Living | 732 | 751 | 5 | 756 | 803 |
| Mudroom | 388 | 407 | 6 | 413 | 420 |
| Garage | 538 | 553 | 8 | 561 | 593 |

The controller adopts a 1400-mesh exterior ceiling for the expanded envelope: 46 above the prior 1354 ceiling (3.4%). The result exceeds the old ceiling by only 13 and adds 94 meshes over the measured baseline (7.4%). All interior ceilings stay unchanged. These are in-frustum mesh counts plus separately measured visible ghost LineSegments; they are not a count of all shadow and postprocessing passes. The probe now exposes the line counts explicitly.

## Focus-card race found during validation

A delayed board fetch could reopen a card after the camera had returned to room level. The overlay consumer now ignores fetch callbacks and Alpine render ticks from superseded focus events. The deterministic delayed-response test fails at the intended dismissal assertion before the fix and passes afterward; a new focus still opens the cached card. This is a small shared-overlay correction discovered by the existing real-mouse navigation regression, not a change to room navigation rules.

## Verification

`python tools/test.py`: **222/222 files passed in 326 seconds**, including the real-mouse room-entry, focus-return, leak, shell, and delayed-response regressions. No production changes follow this sweep. Idle-build results are appended below. Day/night street, rear and patio shots, side views, room metrics and registration boxes are retained in `scratch/full-house-final`. Browser console errors in the full visual pass: none. Mudroom's existing 350-pixel ghost-line floor and the authored room verdict tables pass in the focused shell scenario.


Fresh, otherwise idle high-quality builds measured **1263 / 1123 / 1001 ms**, all below 1500 ms. The earlier visual pass measured 2941 ms while another browser test was running, then 1150 ms on its night reload; those contended samples are not used as idle performance evidence. Low and medium builds retain all 42 registrations and correctly show the mudroom's ghost outlines. Ghost lines remain `0x2d2018` at opacity 0.55 and are built once.

`node --check` passes for both changed JavaScript files; `git diff --check` passes. The final screenshots, measurements, build times, and tier checks are copied to `%LOCALAPPDATA%/Temp/house_quality/shell-T8`. The high-quality visual probe uses the same fixture, renderer capture, and budget reader as `tools/house_probe.py`, and covers all five room views plus street, rear, side, patio, and night views. Physical wall-panel/device verification remains outside this desktop-browser pass.

## Final non-solid sets

All listed pieces ghost except `yard`, which hides. Exterior has no non-solid pieces.

- **Kitchen:** `south_wall`, `east_wall`, `roof_main_south`, `roof_main_end_east`, `porch_roof_east`, `massing_east_front_south`, `massing_east_front_east`, `massing_front_roof_north`, `massing_front_roof_south`, `massing_front_roof_end_east`, `massing_east_back_east`, `massing_east_back_patio`, `massing_back_roof_shed`, `massing_back_roof_front`, `patio_slider`, `yard`.
- **Living:** `south_wall`, `roof_main_south`, `porch_roof_west`, `porch_roof_east`, `porch_roof_front`, `massing_front_roof_north`, `massing_front_roof_south`, `yard`.
- **Mudroom:** `west_wall`, `west_cladding`, `massing_service_roof_south`, `mudroom_front_cladding`, `west_skirt`, `mudroom_roof`, `yard`.
- **Garage:** `massing_service_roof_south`, `garage_gable_west`, `garage_gable_east`, `garage_gable_front`, `mudroom_front_cladding`, `garage_shell`, `garage_door`, `mudroom_roof`, `yard`.
