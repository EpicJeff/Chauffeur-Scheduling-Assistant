# Exterior vehicle body correction

Created 2026-09-28 with built-in ImageGen. Input references were the user's exterior night image and white 2021 Murano rear-three-quarter reference photo.

Saved outputs:

- `exterior-vehicles-corrected-night.png`
- `exterior-vehicles-corrected-day.png`

The driveway uses this corrected Murano for every occupancy combination. The right-only garage layer uses the corrected Mercedes. These are masked vehicle layers; the existing house base keeps the closed garage blinds and other architecture. The SVG driveway mask follows the outer roof and windshield silhouette and includes the complete tires. Its front edge was expanded after visual review exposed a diagonal cut across the front glass.

## Night correction prompt

Use case: precise-object-edit. IMAGE 1 (night house exterior) is the EDIT TARGET. IMAGE 2 (white Nissan rear-three-quarter photograph) is an IDENTITY/SHAPE REFERENCE ONLY for the driveway vehicle. Fix TWO vehicles in image 1. (1) Garage: rebuild the white Mercedes GLS 450 in the right-hand bay with physically correct, undamaged full-size SUV body proportions. Its front is pointing into the garage, rear toward viewer. Continuous straight roof and beltline, correctly aligned side windows, doors and fenders; proper full-length hood/front end receding into the bay, realistic wheelbase and round correctly aligned wheels. Absolutely no folded/melted panels, compressed nose, bulging side or disconnected wheels. Keep right bay occupied and left bay empty. (2) Driveway: replace the inaccurate generic crossover with the exact 2021 Nissan Murano styling shown in IMAGE 2: distinctive angular boomerang rear lamps rising beside rear glass and extending inward across tailgate, floating-roof black rear pillars, sculpted tailgate, correct rear bumper and window shape. Match the reference's recognizable generation/body, NOT a newer Murano or generic rounded crossover. Keep white paint, blank license plate; do not copy the reference watermark or text. Both vehicles must keep the image-1 parking position, orientation, ground footprint and scale, so existing click targets align. Match night illumination and realistic contact shadows. Preserve the rest of image 1 exactly: camera, framing, house geometry, garage opening, all plants and pavement. Output one full-frame 1536x1024 image, no crop or collage. Render both cars carefully as solid manufactured bodies with coherent perspective.

## Matching day prompt

Use case: lighting-weather. IMAGE 1 is EDIT TARGET: the corrected night house with white Mercedes and correct 2021 white Nissan Murano. IMAGE 2 is DAYLIGHT REFERENCE ONLY. Relight image 1 to exactly the soft daytime illumination of image 2. Preserve the newly corrected vehicle designs, silhouettes, body proportions, parking positions, wheels and ALL image-1 geometry pixel-for-pixel. Do not copy the malformed old cars from image 2. Daylight materials and reflections, no glowing brake lights. Unchanged 1536x1024 framing and camera. Preserve all architecture and empty left garage bay. Output a single full-frame DAY version of image 1. No text or UI.

Day inputs: corrected night output as edit target; `exterior-personal-right.png` as lighting reference only.

## Verification

`test_house_exterior_lighting_live.py` checks the corrected driveway source in all parking states and the corrected Mercedes source when only the right bay is occupied. It verifies that the actual browser mask is opaque at three windshield landmarks, including two that were completely transparent before the fix. It writes full exterior screenshots and enlarged vehicle-area screenshots for every day/night occupancy combination under `scratch/exterior-lighting/`.
