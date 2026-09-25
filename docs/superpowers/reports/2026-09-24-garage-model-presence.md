# Garage geometry and exterior vehicle presence

The main garage parking depth is the ENTIRE garage block width, not the interior navigation room width. The third bay now uses that same 11.05 scene-unit depth. The corrected house snapshot uses a 6.0-unit double opening and a 3.0-unit single opening, both 3.0 high. The single door keeps its street-facing orientation, perpendicular to the double door. Exposed returns and roof ends are enclosed when the longer bay projects past the parent block.

## Model sources

- `chauffeur/static/house_hybrid/exterior-study/my-house-garage-corrected.json`
- `chauffeur/static/house_hybrid/exterior-study/model-garage-corrected.png` (camera 0)
- `chauffeur/static/house_hybrid/exterior-study/model-garage-side-corrected.png` (camera 7)
- Measured geometry: `scratch/garage-model-full-block/dimensions.json`

The isolated preview seeds the corrected saved facade. The original personal facade data in the main checkout was not changed. The model renderer, normalizer, validator and editor now support the corrected dimensions.

## Runtime composition

Both garage vehicles appear inside ONE double opening. Gray EV9 and white GLS states match their configured artwork identities; absent or unknown presence does not show an occupied space. The third garage stays closed. A single image layer selects both/left/right occupants over the empty base. No perspective warp or per-door homography is used.

The driveway uses a genuine RGBA cutout with uniform scale and translation, plus a separate CSS contact shadow. The earlier opaque pavement polygon was removed after visual review. Car and shadow leave together. Room markers and desktop traffic shortcuts were moved clear of the cars. The enlarged bus remains on the curb. Vehicle thumbnails are removed; hover/focus labels and vehicle details remain accessible.

## Project assets

All below are in `chauffeur/static/house_hybrid/`:

- `exterior-model-full-block-empty.png`: empty base, open main double garage.
- `exterior-model-full-block-all-home.png`: master / both garage cars.
- `exterior-model-full-block-left.png`: gray vehicle only in main garage.
- `exterior-model-full-block-right.png`: white vehicle only in main garage.
- `exterior-murano-cutout.png`: RGBA driveway vehicle; original generated alpha preserved.

Unused rejected architectural generations were moved to `scratch/garage-rejected/`. Original generated files remain in the Codex generated-image directory.

## Verification

- `tests/test_house_facade.py`: passed.
- `tests/test_house_garage_dimensions_live.py --out ../scratch/garage-model-full-block`: passed, actual mesh extents 6.0 / 3.0 openings and equal 11.05000019 depths.
- `scenario_side_garage_front_seal_and_popout`: passed all four configurations (flush, projecting, mirrored, upper story). Its unstubbed chat stream logged a disconnect during shutdown; geometry/navigation checks passed.
- `tests/test_house_exterior_live.py --out ../scratch/garage-full-block-exterior`: final cutout run passed, with no browser errors. Exercises all eight presence combinations, unknown presence, alpha transparency, shadow removal, desktop/phone/ultrawide registration, vehicle detail actions, room navigation, history, keyboard/touch, reduced motion and no WebGL.
- Browser visual captures: `scratch/garage-full-block-preview/alpha-desktop.png`, `alpha-detail.png`, and exterior regression screenshots.

## Generation provenance

Used built-in ImageGen, not the CLI. Model captures define geometry; `exterior-scene.jpg` provides photographic materials/lighting. Presence edits reference the new full-block master. Driveway extraction references that same master. Original canvas 1536x1024; cutout was returned larger than requested, so it is placed with a uniform 0.55 scale, preserving proportions.

### Master prompt

Use case: model-guided photorealistic architectural rendering. IMAGE 1 is the CORRECTED 3D HOUSE MODEL at the REQUIRED CAMERA. It is the absolute authority for house footprint, garage door widths/heights, bay DEPTHS, roof planes/ridges/intersections, the right-hand projecting garage volume, and door orientation. IMAGE 2 is a second side view of the SAME corrected model, supplied ONLY to disambiguate the full depth and roof connection of the third garage. Do NOT adopt image 2's camera. IMAGE 3 is the original photographic MATERIALS AND LIGHTING reference, not the geometry authority: use its white board-and-batten siding, white masonry base, charcoal shingle roofs, dark metal lower porch/garage roof accents, shutters, warm natural daylight, lawn and mature trees. Render a beautiful photorealistic full exterior from EXACTLY image 1's elevated three-quarter camera and framing, faithfully preserving the corrected model's roof topology and solid garage volumes. The main side-entry DOUBLE garage opening is 6 model units wide by 3 high. Its projecting SINGLE garage door is exactly half that width, 3 units, with the same height. Both bays have 11.05 units parking depth measured perpendicular inward from their respective door faces: the ENTIRE width of the main garage block is its parking depth, including the portion behind the front windows. The single bay has that SAME full 11.05 unit parking depth, not just the narrower interior room width. Follow exactly the larger full-depth bay shown in image 1 and image 2. The projecting single bay is a real full-depth car garage, not a shallow entry porch. Its door faces the street/driveway on the LEFT visible face of its bump-out, perpendicular to the main double door; its other visible gabled end is the RIGHT face. Do NOT move this third door onto the gabled right face. Keep the third door CLOSED with dark grid-panel glazing as modeled. Open ONLY the broad MAIN DOUBLE GARAGE door, preserving its modeled opening dimensions, and park a GRAY 2026 Kia EV9 and a WHITE 2022 Mercedes GLS side by side INSIDE THAT ONE MAIN DOUBLE GARAGE, nose-in with their rear ends visible just behind the shared threshold. Show full-size SUVs whose widths are about one third of the 6-unit clear double opening. Put a BLUE 2021 Nissan Murano farther forward on the driveway to the left so neither garaged SUV is obscured. All three vehicles have consistent real-world scale: Murano length about 4.9 model units, EV9/GLS about 5.0/5.2 units, all about 2 units wide. No miniature garage cars or giant driveway car. Preserve the coherent modeled main gable and simple separate lower full-depth pop-out roof; NO invented roof wedges, doubled eaves, broken planes or extensions. Do not redesign, rotate, shrink, widen or shorten the modeled garage volumes. Use photographic realism and natural material detail, not a cartoon render. No labels, UI, dimensions or text. All three garages remain part of this same house; two cars are together in the main double bay, the third single door stays closed.

### empty presence prompt

Use case: precise-object-edit. Edit this exact photograph as an aligned presence-state asset. Remove all THREE vehicles: gray SUV inside main double garage, white SUV beside it inside the SAME double garage, and blue SUV on driveway. Reconstruct the now-empty garage interior (concrete floor, deep dim interior, beige walls) and empty concrete driveway with natural matching light. Keep the MAIN DOUBLE GARAGE OPEN and EMPTY. Keep single garage CLOSED. Everything else including ALL house geometry, roof planes, full-depth third garage, door jambs, thresholds, doors, windows, garden, trees, road, camera, image dimensions and framing must stay exactly pixel-aligned to the reference. This is only vehicle removal. No architectural redesign or camera change. No cars, no people, no text.

### left presence prompt

Use case: precise-object-edit. Edit this exact photograph as an aligned presence-state asset. Remove ONLY the WHITE Mercedes SUV from inside the main double garage. Keep the gray SUV exactly where it is on the left side of that SAME main opening, and keep blue SUV on driveway unchanged. Reconstruct empty concrete floor and deep dim beige-walled garage in the space vacated by the white SUV. MAIN DOUBLE GARAGE stays OPEN, single garage stays CLOSED. Everything outside the removed white SUV, ALL architecture, roof planes, long third bay, jambs, floor, garden, lighting, camera, canvas size and framing must remain exactly pixel-aligned. No camera shift, no new objects, no redesign, no text.

### right presence prompt

Use case: precise-object-edit. Edit this exact photograph as an aligned presence-state asset. Remove ONLY the GRAY SUV from inside the main double garage. Keep the white Mercedes SUV exactly where it is on the right side of that SAME main opening, and keep blue SUV on driveway unchanged. Reconstruct empty concrete floor and deep dim beige-walled garage in the space vacated by the gray SUV. MAIN DOUBLE GARAGE stays OPEN, single garage stays CLOSED. Everything outside the removed gray SUV, ALL architecture, roof planes, long third bay, jambs, floor, garden, lighting, camera, canvas size and framing must remain exactly pixel-aligned. No camera shift, no new objects, no redesign, no text.

### Driveway cutout prompt

Use case: background-extraction. Extract ONLY the blue Nissan Murano parked on the driveway in this exact photograph, with a soft translucent contact shadow immediately beneath its tires. Output on a genuinely transparent alpha background. Preserve the exact photographed rear three-quarter camera angle, blue paint, proportions, rear/front orientation, wheels, details and lighting of this specific vehicle. Remove the entire house, garage, all other cars, concrete, plants, sky and street; no opaque pavement or scenery anywhere. Keep the ORIGINAL FULL 1536 x 1024 canvas with the car at its EXACT ORIGINAL PIXEL POSITION and SIZE: approximately x=716..966, y=732..878, with shadow just beneath it. Do not zoom, recenter, rotate or resize it. Pixels outside the car and its contact shadow must have alpha zero, not a white/checkered background. No added text.
