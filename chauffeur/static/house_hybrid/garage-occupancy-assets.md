# Complete single-car garage artwork

Created with built-in ImageGen on 2026-09-26. Outputs saved beside this document: `garage-left-day.png`, `garage-right-day.png`, `garage-left-night.png`, `garage-right-night.png`.

The renderer selects one full photograph for empty, left-only, right-only or both-home occupancy. This replaces clipped halves of the empty and occupied photographs, whose lighting differed and produced a vertical seam. Day and night each have all four states. Existing empty and both-home artwork remains unchanged.

For each edit, image 1 is `garage-personal-vehicles.png` (day) or `garage-personal-vehicles-night.png` (night). Image 2 is the matching `garage-empty.png` or `garage-empty-night.png`.

## garage-left-day

Use case: precise-object-edit. Image 1 is EDIT TARGET, a two-car garage. Image 2 is reference ONLY for cabinetry and floor hidden behind cars. Produce a single seamless full-frame garage photograph at exactly 1536x1024, keeping the camera and all architectural edges and remaining car pixel aligned with image 1. Preserve image 1 lighting and exposure across the ENTIRE scene: no vertical seam, no split lighting, no pasted half-image. Reconstruct continuous wall, cabinetry, floor texture, reflections and physically plausible shadows in the vacated bay. Change only the requested vehicle removal; no additional objects, no text, no UI. REMOVE ONLY the Mercedes SUV on the RIGHT. KEEP the Kia EV9 on the LEFT exactly as-is. Preserve day lighting of image 1. Image 2 must not override its lighting.

## garage-right-day

Use case: precise-object-edit. Image 1 is EDIT TARGET, a two-car garage. Image 2 is reference ONLY for cabinetry and floor hidden behind cars. Produce a single seamless full-frame garage photograph at exactly 1536x1024, keeping the camera and all architectural edges and remaining car pixel aligned with image 1. Preserve image 1 lighting and exposure across the ENTIRE scene: no vertical seam, no split lighting, no pasted half-image. Reconstruct continuous wall, cabinetry, floor texture, reflections and physically plausible shadows in the vacated bay. Change only the requested vehicle removal; no additional objects, no text, no UI. REMOVE ONLY the Kia EV9 on the LEFT. KEEP the Mercedes SUV on the RIGHT exactly as-is. Preserve day lighting of image 1. Image 2 must not override its lighting.

## garage-left-night

Use case: precise-object-edit. Image 1 is EDIT TARGET, a two-car garage. Image 2 is reference ONLY for cabinetry and floor hidden behind cars. Produce a single seamless full-frame garage photograph at exactly 1536x1024, keeping the camera and all architectural edges and remaining car pixel aligned with image 1. Preserve image 1 lighting and exposure across the ENTIRE scene: no vertical seam, no split lighting, no pasted half-image. Reconstruct continuous wall, cabinetry, floor texture, reflections and physically plausible shadows in the vacated bay. Change only the requested vehicle removal; no additional objects, no text, no UI. REMOVE ONLY the Mercedes SUV on the RIGHT. KEEP the Kia EV9 on the LEFT exactly as-is. Preserve night lighting of image 1. Image 2 must not override its lighting.

## garage-right-night

Use case: precise-object-edit. Image 1 is EDIT TARGET, a two-car garage. Image 2 is reference ONLY for cabinetry and floor hidden behind cars. Produce a single seamless full-frame garage photograph at exactly 1536x1024, keeping the camera and all architectural edges and remaining car pixel aligned with image 1. Preserve image 1 lighting and exposure across the ENTIRE scene: no vertical seam, no split lighting, no pasted half-image. Reconstruct continuous wall, cabinetry, floor texture, reflections and physically plausible shadows in the vacated bay. Change only the requested vehicle removal; no additional objects, no text, no UI. REMOVE ONLY the Kia EV9 on the LEFT. KEEP the Mercedes SUV on the RIGHT exactly as-is. Preserve night lighting of image 1. Image 2 must not override its lighting.

Validation: `test_house_exterior_lighting_live.py` captures all eight complete garage views at 2470×1236, checks that each has one unmasked image, and exercises live parking updates on a phone viewport. Screenshots: `scratch/exterior-lighting/garage-{empty,left,right,both}-{day,night}.png`.

