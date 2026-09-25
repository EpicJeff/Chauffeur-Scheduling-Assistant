# Personal House vehicles - v2.499.183

The live photographic House now uses saved car assignments instead of requiring demo asset filenames. The exterior and garage agree on presence and car identity. Prototype shortcuts and preview controls are hidden on normal House visits, including when preview query parameters are supplied.

## Household setup after installing the update

In Config > Family > Vehicles, edit each existing vehicle and select its **House vehicle appearance**, then save:

- White 2026 Kia EV9 GT-Line, black roof: left garage bay.
- White 2022 Mercedes GLS 450, 23-inch wheels: right garage bay.
- White 2021 Nissan Murano: driveway.

Use each saved car's Home Assistant device tracker and battery/fuel/range entities. Without a tracker, a car is treated as resting at home; an unavailable assigned tracker does not fabricate home presence. Unknown energy/range displays a dash. Unassigned parking spaces stay empty. Assignment does not modify Home Assistant entities. This release does not configure the deployed household automatically or generalize image generation to arbitrary households.

## Behavior and verification

The new `test_house_personal_vehicles_live.py` saves assignments through Config and checks their persistence through the car API and House state. It exercises all eight combinations of three vehicles being home or away, both garage buttons, all three exterior-to-cluster transitions, matching telemetry, desktop/phone bounds, missing telemetry, live preview isolation, and four driveway windshield states. It uses isolated test storage and mocked Home Assistant responses.

Other focused checks: car telemetry, House state, garage browser flow, exterior browser flow, artwork upload persistence, House default/rollback, template JavaScript, and rebuilt Tailwind staleness checks. The full repository suite was not repeated for this change. No production Home Assistant credentials were used by these checks.

The test also exposed two missing Config Alpine initial values (`scopeTuneOpen` and `scopeMeta`); both are now initialized. The browser assertions finish without JavaScript errors.

## Assets and generation record

Generated with the **built-in image generation tool**, using the existing exterior, garage, and cluster images as references/edit targets. Final assets are stored in [`chauffeur/static/house_hybrid`](../../../chauffeur/static/house_hybrid/). These are curated prototype assets, not a general asset-generation service. No runtime image generation is required.

Final prompt specifications (normalized from the editing requests):

| Final saved file | Prompt specification |
| --- | --- |
| `exterior-personal-vehicles.png` | Preserve the existing house camera, architecture, planting, driveway, lighting and parking positions. Show a white 2026 Kia EV9 GT-Line with black roof in the left garage bay, white 2022 Mercedes GLS 450 with 23-inch wheels in the right bay, and white 2021 Nissan Murano in the driveway. Match photographic scale, perspective and contact shadows. |
| `exterior-personal-left.png` | Preserve the personal exterior scene and left EV9; remove the GLS from the right bay, restoring the empty garage behind it. |
| `exterior-personal-right.png` | Preserve the personal exterior scene and right GLS; remove the EV9 from the left bay, restoring the empty garage behind it. |
| `garage-personal-vehicles.png` | Preserve the existing garage camera, walls, windows, cabinets, workbench and lighting. Place the white EV9 with black roof in the left bay and white GLS 450 in the right, facing into the garage; rear views, consistent scale and natural shadows. |
| `cluster-ev9-home.png` | Driver instrument perspective inside the EV9. Through the windshield show the same garage from the left bay, including the correct back cabinets, left-side window and tools. Keep the display region clear for live application telemetry. |
| `cluster-gls-home.png` | Driver instrument perspective inside the GLS 450. Through the windshield show the same garage from the right bay, with the matching cabinets, central workbench and charger. Keep the display region clear for live application telemetry. |
| `cluster-murano-driveway.png` | Driver instrument perspective inside the 2021 Murano parked in its driveway position. Through the windshield show the same house facade, hydrangeas, open garage ahead/right and both parked vehicles. Preserve the Nissan dashboard and leave its center information display clear for live telemetry. |
| `cluster-murano-left.png` | Preserve the Murano cockpit and windshield framing; remove only the right-bay GLS and restore the empty space, retaining the left EV9. |
| `cluster-murano-right.png` | Preserve the Murano cockpit and windshield framing; remove only the left-bay EV9 and restore the empty space, retaining the right GLS. |
| `cluster-murano-empty.png` | Preserve the Murano cockpit, house and windshield framing; remove both garage cars, restoring the empty garage. |

The driveway uses a CSS-clipped section of the complete exterior photograph, retaining its photographed tire contact and shadow. The two interior garage bays share a source image and are clipped independently. Four complete Murano cockpit variants preserve the windshield background as the other cars leave or arrive. Rejected intermediate generations and browser screenshots remain in ignored scratch storage, outside the release.
