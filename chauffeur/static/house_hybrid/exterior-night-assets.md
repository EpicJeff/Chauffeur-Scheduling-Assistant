# Exterior, garage and vehicle night artwork

Created 2026-09-25 with the built-in ImageGen tool. Day originals remain unchanged. Each output is `<day-basename>-night.png` in this directory and is paired through versioned template URLs.

Outputs:

- `exterior-model-full-block-empty-night.png`
- `exterior-personal-vehicles-night.png`
- `exterior-personal-left-night.png`
- `exterior-personal-right-night.png`
- `garage-empty-night.png`
- `garage-personal-vehicles-night.png`
- `cluster-ev9-home-night.png`
- `cluster-gls-home-night.png`
- `cluster-murano-driveway-night.png`
- `cluster-murano-left-night.png`
- `cluster-murano-right-night.png`
- `cluster-murano-empty-night.png`

## Exterior prompt

Use case: lighting-weather. Input image is EDIT TARGET: matching NIGHT variant of this interactive house artwork. Change ONLY illumination: deep navy night sky, cool dim moonlit garden and pavement, warmly glowing existing windows, porch lamps and garage lights. Remove all sunlight and sun shadows. Keep inviting and readable, photoreal. STRICT: preserve exactly 1536x1024, camera, crop, every architectural edge, plants, driveway, garage opening and all vehicle silhouettes/positions. No added or removed objects, people, text or UI. Pixel-aligned geometry is essential for overlaid click targets. Return one full-frame image.

The occupied exterior was generated first. For empty, left-only and right-only variants, the corresponding day image was input 1 and the occupied night exterior was input 2. Appended instruction:

Image 1 is the EDIT TARGET: preserve its exact vehicle presence/absence. Image 2 is LIGHTING REFERENCE ONLY: match its night lighting exactly, but never copy its cars into empty parking spaces. Output the night version of image 1 only.

## Garage prompt

Use case: lighting-weather. Input is EDIT TARGET. Create matching NIGHT version of this garage. Change only lighting: no sunshine, no sun patches or bright daylight through left window or open front doorway. Window is deep navy night. Existing ceiling fixtures give soft warm practical illumination, enough to see cabinetry and cars comfortably; cooler dim blue ambient light from outdoors across foreground floor. Preserve EXACT camera, framing, 1536x1024 dimensions, geometry, every object and its position, vehicle silhouettes and badges, and blank license plates. Do not move/add/remove anything. No new text or UI. Output full-frame matching night artwork.

The occupied garage was generated first. For the empty variant, the empty day garage was input 1 and the occupied night garage was input 2. Appended instruction:

Image 1 is EDIT TARGET. Image 2 is lighting reference only. Keep garage EMPTY as image 1; match illumination of image 2 exactly.

## Dashboard prompt

Use case: lighting-weather. Image 1 is EDIT TARGET: create matching NIGHT dashboard artwork. Image 2 is lighting reference ONLY for warm softly lit garage with navy night outside and no sunlight. Dim cabin illuminated by soft cool ambient night light and subtle instrument backlighting. Preserve all black digital display areas COMPLETELY BLANK for live HTML instruments. Preserve exact camera/framing, steering wheel, controls, material detail, ALL geometry and outside vehicle presence/absence. No added/removed objects or new lettering, no UI. Keep the scene comfortably visible but clearly night. Output one image at same aspect ratio and resolution as image 1.

EV9, GLS and occupied-driveway Murano used their respective day targets with the occupied night garage as input 2. Remaining Murano variants used their respective day targets and the night occupied-driveway Murano as input 2, with this appended instruction:

Match image 2 lighting exactly, keeping the garage parking occupancy of image 1. Preserve image 1 garage architecture and furniture. Do not import missing cars from reference.

## Integration and verification

The shared `chf-house-light` event selects these assets for manual previews and automatic sun changes. Exterior base/parking layers and garage bay layers decode before switching. Dashboards preserve live HTML telemetry and reject obsolete loads. Bus sprites and uploaded vehicle cutouts receive night shading without dimming labels.

Browser proof: `python chauffeur/tests/test_house_exterior_lighting_live.py`. Screenshots are written to `scratch/exterior-lighting/`.


## Garage window correction — 2026-09-26

The base `exterior-model-full-block-empty-night.png` was edited with built-in ImageGen to remove domestic furniture and table lamps from the two ground-floor garage windows. This base supplies those windows for every live occupancy state; the vehicle overlays are masked to the garage opening and driveway only.

Exact edit prompt:

Use case: precise-object-edit. This image is the EDIT TARGET. Fix ONLY the interior contents visible through the TWO ground-floor tall narrow windows in the GARAGE wall immediately LEFT of the open double garage bay (approximately x=47–50%, y=58–70%, and x=54–56.5%, y=61–72% in the full image). They incorrectly show a furnished living room and table lamp. These are GARAGE windows: remove the lamps, houseplants, domestic furniture, and room decor visible inside ONLY these two windows. Show subdued warm neutral garage illumination with plain undecorated walls and indistinct utility storage, dimmer than the living room windows. Preserve glazing, mullions, shutters, trim, outside landscaping, and exact window shape. Do NOT modify any other windows, porch, architecture, garage opening, driveway, trees, sky or lighting elsewhere. Preserve original camera, framing, exact 1536x1024 size, and pixel-aligned geometry. No new cars, people, words or UI. Return the entire full-frame corrected night exterior, no crop.

