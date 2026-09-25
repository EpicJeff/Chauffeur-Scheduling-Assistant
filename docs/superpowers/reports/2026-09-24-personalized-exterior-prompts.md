# Personalized exterior study — exact prompts

Built-in ImageGen; one generation per treatment. No CLI/API fallback.

## Photo-only three-quarter treatment

Only input: `docs/superpowers/specs/assets/2026-09-17-photo-farmhouse.jpg`.
Neither the model render nor the interior image was supplied.

```text
Use case: photorealistic-natural.
Generate one landscape 1536 x 1024 architectural photograph of the exact farmhouse in the supplied reference, viewed from a NEW elevated front-right three-quarter camera.
The supplied photo is the ONLY visual reference. Move the camera approximately 45 degrees around to the viewer's right, looking back toward the house, high enough to see the roofs while keeping the front and right side legible. Show the entire house with comfortable space around it. This is a new perspective of the same house, not a head-on photo and not a redesign.
Preserve the real facade's architectural identity: broad low left wing; taller central two-story block and its left-right roof ridge with the prominent front cross-gable over three upper windows; small entry porch gable above the dark double door on the left with a long shed porch roof to the right; the prominent right front-facing gable with one upper window, the large grouped lower windows and narrower flanking windows. Preserve relative story heights, widths, roof slopes, opening counts and placements. Keep light greige board-and-batten, painted white/cream masonry in the shown locations, charcoal shingles, dark standing-seam porch roof, white trim and muted blue-gray shutters.
Infer the unseen right-side depth and surfaces conservatively from the front photo. Do not add new wings, extra floors, dormers or chimneys. Do not place garage doors on the front facade. Do not invent gratuitous architectural features.
Warm afternoon daylight, natural tactile materials, subtle window reflections, rich restrained colors, soft realistic shadows and contact shadows, detailed individual shingles and siding. A high-end architectural photograph, not a miniature, toy or low-poly image. Wooded residential surroundings, quiet lawn and front path, plausible side landscaping/driveway, continuous ground. Remove the temporary builder's sign and address lettering. No people, vehicles, text, signs, watermarks, interface, cutaway or collage.
```

## Combined model + photo treatment

Inputs, in order:
1. `chauffeur/static/house_hybrid/exterior-study/model-three-quarter.png` (camera and structure)
2. `docs/superpowers/specs/assets/2026-09-17-photo-farmhouse.jpg` (surface appearance)
3. `chauffeur/static/house_hybrid/living-habitat-day.png` (shared atmosphere)

```text
Use case: sketch-to-render with multiple references.
Asset: landscape 1536 x 1024 personalized farmhouse exterior, one coherent high-quality architectural photograph.
Reference hierarchy:
IMAGE 1: the hand-authored 3D model rendered at the REQUIRED three-quarter front-right viewpoint. This is the absolute authority for camera, perspective, footprint, massing, relative building proportions, roof geometry and locations of doors/windows.
IMAGE 2: the real farmhouse photograph. Use it for the actual home's surface appearance: charcoal shingles, standing-seam dark porch roof, warm light greige board-and-batten, painted white/cream masonry, white trim, muted blue-gray shutters and dark glazed wood double entry doors. Translate those materials onto the corresponding model surfaces. Do NOT copy its head-on camera.
IMAGE 3: the existing living room. Use only for the shared art direction: warm afternoon daylight, tactile natural materials, soft realistic shadows, restrained colors, photographic quality. No indoor objects outside.
Task: photograph the real house from Image 2 FROM THE EXACT CAMERA AND STRUCTURE OF IMAGE 1, as a beautiful exterior in the visual world of Image 3. Keep the entire model house in frame with its right side, side-entry glass garage doors and projecting third bay visible. Preserve the long side walls and all roof ridges and slopes. The elevated three-quarter view is essential. Do not flatten back into a front view.
Where references differ, model structure wins: keep its low right front gable without an attic window; keep the central two-story block with three upstairs windows, its front cross-gable, lower porch gable and shed porch roof, and the broad low left wing. Material details from the photo can be richer, but do not add windows, dormers, chimneys, extra floors or new projections. Keep the front porch in its modeled position and retain the modeled yard layout: left picket fence, front walk, planting beds, right driveway.
Replace the model's blue void and floating parcel edge with continuous natural ground, a wooded residential background and subtle sky. Change low-poly trees and shrubs into realistic vegetation in their existing locations. Full realistic material detail and contact shadows; physically plausible glass and painted siding. Preserve camera/framing/geometry; improve rendering quality. No miniature look, toy look, text, signs, addresses, watermarks, vehicles, people, UI or cutaways.
```

## Photo treatment

Inputs, in order:
1. `docs/superpowers/specs/assets/2026-09-17-photo-farmhouse.jpg`
2. `chauffeur/static/house_hybrid/living-habitat-day.png` (style only)

```text
Use case: style-transfer.
Asset type: prototype exterior background for a personalized house interface, landscape 1536 x 1024.
Input images: Image 1 is the exact farmhouse whose architectural identity must be preserved. Image 2 is a STYLE AND LIGHTING reference only: our existing polished living-room background. Do not insert any living-room furniture outside.
Primary request: Create the exterior of this exact farmhouse as if it belongs to the same beautifully photographed, warm, tactile world as Image 2. Keep the near head-on view and entire house visible. Use soft warm afternoon light, rich but restrained natural colors, realistic materials, detailed shingle roofs and painted board-and-batten siding, subtle contact shadows, believable white-painted masonry, and welcoming window reflections. Quality should be high-end architectural photography, not a cartoon, miniature or low-poly render.
Architectural invariants from Image 1: the broad low left wing; taller central two-story section with a roof ridge running left-right; the large front-facing cross-gable above the three second-story windows; the lower entry porch with its smaller front gable over the double door on the left and long shed-roof run to the right; the prominent right wing's front-facing gable with ONE upper window; the large grouped ground-floor right window with narrow side windows. Preserve all relative widths, heights, asymmetry, roof pitches and directions, door/window positions, porch columns and greige/cream/white/charcoal material placement. Do not mirror, simplify or redesign the architecture.
Composition: retain the original front viewpoint and proportions, but fit the whole facade comfortably into a 3:2 frame by extending sky/foreground, not stretching the house. Keep a quiet lawn, front walk and wooded residential background. Remove only the temporary builder's sign and address lettering. No new wings, dormers, skylights, chimneys, garage doors on the front, extra windows, people, vehicles, interface elements, text or watermark. This is one coherent exterior image, not a collage or an interior/exterior cutaway.
```

## Model treatment

Inputs, in order:
1. `chauffeur/static/house_hybrid/exterior-study/model-source.png`
2. `chauffeur/static/house_hybrid/living-habitat-day.png` (style only)

```text
Use case: sketch-to-render.
Asset type: personalized house-interface exterior background, landscape 1536 x 1024.
Input roles: Image 1 is the exact hand-authored house model, the authoritative architecture and camera. Image 2 is ONLY the photographic style, warmth, material richness and lighting reference from the existing living room. No interior furniture belongs outside.
Primary request: transform the simple realtime 3D render in Image 1 into a beautiful, believable architectural photograph in the same warm, tactile visual world as Image 2. Preserve the exact house design and near head-on slightly elevated viewpoint. Make surfaces physically detailed: individual charcoal roof shingles, greige vertical board-and-batten siding with subtle paint texture, pale trim, cream brick at the porch, wood double doors and dark stained porch posts. Add natural warm afternoon lighting, soft realistic shadows and contact shadows, subtle window reflections, realistic foliage and grass. Real architecture, not a miniature or toy.
Strict architecture lock: preserve the silhouette, all relative heights and widths, story counts, roof pitches and ridge directions. Broad low left wing; two-story central block with left-right ridge and its offset front cross-gable; exactly three upper windows; low entry porch gable over the pair of doors on the left, continuing as a low shed roof to the right; right single-story wing with its low front gable. The right front gable has NO attic window. Keep each opening in its shown position and keep the far-right setback side-garage projection. Preserve the left picket fence, front path, right driveway and yard layout. Do not invent dormers, windows, chimneys, rooms or extra architectural trim.
Composition: match Image 1 framing and house proportions, keep the full house visible. Replace the bare cyan void and floating edge of the lot with an unobtrusive continuous wooded residential background, sky, lawn and realistic road surface. Natural landscaping in the shown planting areas, not overgrown. Keep the front facade legible. Preserve the model's massing even where a different design might seem more attractive. No people, vehicles, signs, text, watermarks, interface, cutaway or collage. The result should plausibly be the exterior of the warm living-room style reference, while remaining this exact saved house.
```
