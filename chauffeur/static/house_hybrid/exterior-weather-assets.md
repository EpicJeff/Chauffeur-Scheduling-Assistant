# Exterior weather artwork

Generated 2026-09-28 with built-in ImageGen. These are full static photographic weather variants, not procedural effects. Clear weather retains the original day/night photographs.

## Saved assets

- `exterior-weather-cloudy-day.png`
- `exterior-weather-rain-day.png`
- `exterior-weather-snow-day.png`
- `exterior-weather-fog-day.png`
- `exterior-weather-cloudy-night.png`
- `exterior-weather-rain-night.png`
- `exterior-weather-snow-night.png`
- `exterior-weather-fog-night.png`
- `exterior-weather-vehicles-cloudy-day.png`
- `exterior-weather-vehicles-rain-day.png`
- `exterior-weather-vehicles-snow-day.png`
- `exterior-weather-vehicles-fog-day.png`
- `exterior-weather-vehicles-cloudy-night.png`
- `exterior-weather-vehicles-rain-night.png`
- `exterior-weather-vehicles-snow-night.png`
- `exterior-weather-vehicles-fog-night.png`

The eight empty-house images preserve the closed garage blinds. The eight vehicle images provide the driveway Murano and Mercedes-only garage layers through the existing SVG masks. Other garage occupancy layers remain sheltered inside the garage. Both background and vehicle images decode before a day/night or weather change is committed.

## Inputs

Day backgrounds: `exterior-model-full-block-empty.png` as edit target. Night backgrounds: matching generated day background as edit target; `exterior-model-full-block-empty-night.png` as night lighting reference. Vehicle variants: `exterior-vehicles-corrected-{day,night}.png` as edit target; matching generated weather background as lighting/material reference.

## Exact prompts

### cloudy-day

Use case: lighting-weather. The supplied image is the EDIT TARGET. Generate a photorealistic weather variant of this exact architectural scene, not a graphic overlay. Preserve the camera, framing, perspective, resolution 1536x1024, house outline, ALL doors and windows, landscaping, driveway seams and open garage geometry at exactly their current positions. Garage and driveway remain EMPTY with NO vehicles or people. The TWO ground-floor garage windows immediately left of the open garage have CLOSED horizontal blinds; preserve those blinds with NO visible furniture. Preserve the existing interior/garage exposure so separately composited parked vehicles still fit. Do not add UI, text, frames, borders, watermarks, or change the house design. Return one complete 1536x1024 image. WEATHER: Overcast daytime: continuous textured gray cloud cover and soft diffuse cool daylight, no direct sun or hard sun shadows. Dry driveway. Natural architectural photography.

### rain-day

Use case: lighting-weather. The supplied image is the EDIT TARGET. Generate a photorealistic weather variant of this exact architectural scene, not a graphic overlay. Preserve the camera, framing, perspective, resolution 1536x1024, house outline, ALL doors and windows, landscaping, driveway seams and open garage geometry at exactly their current positions. Garage and driveway remain EMPTY with NO vehicles or people. The TWO ground-floor garage windows immediately left of the open garage have CLOSED horizontal blinds; preserve those blinds with NO visible furniture. Preserve the existing interior/garage exposure so separately composited parked vehicles still fit. Do not add UI, text, frames, borders, watermarks, or change the house design. Return one complete 1536x1024 image. WEATHER: Rainy daytime: believable steady rain photographed at a natural shutter speed, overcast sky, wet roof and concrete, subtle shallow puddles and realistic reflections. Varied fine rain streaks at different depths, not a repeated pattern or white lines. No storm damage or flood.

### snow-day

Use case: lighting-weather. The supplied image is the EDIT TARGET. Generate a photorealistic weather variant of this exact architectural scene, not a graphic overlay. Preserve the camera, framing, perspective, resolution 1536x1024, house outline, ALL doors and windows, landscaping, driveway seams and open garage geometry at exactly their current positions. Garage and driveway remain EMPTY with NO vehicles or people. The TWO ground-floor garage windows immediately left of the open garage have CLOSED horizontal blinds; preserve those blinds with NO visible furniture. Preserve the existing interior/garage exposure so separately composited parked vehicles still fit. Do not add UI, text, frames, borders, watermarks, or change the house design. Return one complete 1536x1024 image. WEATHER: Snowy daytime: quiet natural light snowfall, textured overcast sky, a light realistic dusting on roof ridges, lawn and shrubs. Keep the paved driveway and sidewalks cleared, damp and mostly snow-free; do not add snowbanks or cover the architecture. Subtle scattered falling flakes with natural depth of field, not uniform dots.

### fog-day

Use case: lighting-weather. The supplied image is the EDIT TARGET. Generate a photorealistic weather variant of this exact architectural scene, not a graphic overlay. Preserve the camera, framing, perspective, resolution 1536x1024, house outline, ALL doors and windows, landscaping, driveway seams and open garage geometry at exactly their current positions. Garage and driveway remain EMPTY with NO vehicles or people. The TWO ground-floor garage windows immediately left of the open garage have CLOSED horizontal blinds; preserve those blinds with NO visible furniture. Preserve the existing interior/garage exposure so separately composited parked vehicles still fit. Do not add UI, text, frames, borders, watermarks, or change the house design. Return one complete 1536x1024 image. WEATHER: Foggy daytime: realistic atmospheric perspective, dense soft mist in the distant trees and sky, thinner haze around the house, foreground architecture readable. Damp natural materials, diffuse soft light, no opaque white veil uniformly covering the frame.

### cloudy-night

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET: this exact cloudy weather exterior. IMAGE 2 is a NIGHT LIGHTING REFERENCE ONLY. Relight image 1 to nighttime matching the warm windows, porch/garage/landscape lights and blue ambient exposure of image 2 while keeping image 1's cloudy weather, material appearance, and exact pixel-aligned geometry. Keep the same 1536x1024 framing, house, plants, empty garage and empty driveway. This is a photorealistic complete weather-specific night background, not an effect overlay. Thick weather clouds obscure the moon and stars; NO visible moon or stars. Preserve CLOSED horizontal blinds on the TWO ground-floor garage windows immediately left of the open garage, with a soft warm glow through the blinds and no visible furniture. Keep natural textured overcast clouds, dry pavement, and soft shadowless nighttime ambient lighting. No cars, people, text, UI or crop. Preserve the garage's warm exposure as in image 2. Output a single full-frame image.

### rain-night

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET: this exact rain weather exterior. IMAGE 2 is a NIGHT LIGHTING REFERENCE ONLY. Relight image 1 to nighttime matching the warm windows, porch/garage/landscape lights and blue ambient exposure of image 2 while keeping image 1's rain weather, material appearance, and exact pixel-aligned geometry. Keep the same 1536x1024 framing, house, plants, empty garage and empty driveway. This is a photorealistic complete weather-specific night background, not an effect overlay. Thick weather clouds obscure the moon and stars; NO visible moon or stars. Preserve CLOSED horizontal blinds on the TWO ground-floor garage windows immediately left of the open garage, with a soft warm glow through the blinds and no visible furniture. Keep realistic rain and wet pavement reflecting the warm lights, no flooding. No cars, people, text, UI or crop. Preserve the garage's warm exposure as in image 2. Output a single full-frame image.

### snow-night

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET: this exact snow weather exterior. IMAGE 2 is a NIGHT LIGHTING REFERENCE ONLY. Relight image 1 to nighttime matching the warm windows, porch/garage/landscape lights and blue ambient exposure of image 2 while keeping image 1's snow weather, material appearance, and exact pixel-aligned geometry. Keep the same 1536x1024 framing, house, plants, empty garage and empty driveway. This is a photorealistic complete weather-specific night background, not an effect overlay. Thick weather clouds obscure the moon and stars; NO visible moon or stars. Preserve CLOSED horizontal blinds on the TWO ground-floor garage windows immediately left of the open garage, with a soft warm glow through the blinds and no visible furniture. Keep light snowfall and the light snow cover on roofs, lawn and shrubs; driveway and sidewalks remain cleared and wet. No cars, people, text, UI or crop. Preserve the garage's warm exposure as in image 2. Output a single full-frame image.

### fog-night

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET: this exact fog weather exterior. IMAGE 2 is a NIGHT LIGHTING REFERENCE ONLY. Relight image 1 to nighttime matching the warm windows, porch/garage/landscape lights and blue ambient exposure of image 2 while keeping image 1's fog weather, material appearance, and exact pixel-aligned geometry. Keep the same 1536x1024 framing, house, plants, empty garage and empty driveway. This is a photorealistic complete weather-specific night background, not an effect overlay. Thick weather clouds obscure the moon and stars; NO visible moon or stars. Preserve CLOSED horizontal blinds on the TWO ground-floor garage windows immediately left of the open garage, with a soft warm glow through the blinds and no visible furniture. Keep real volumetric fog in the distance, soft halos around lamps, and a readable foreground. No cars, people, text, UI or crop. Preserve the garage's warm exposure as in image 2. Output a single full-frame image.

### vehicles-cloudy-day

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET with the white 2021 Nissan Murano in the driveway and the correctly formed white Mercedes GLS in the right garage bay. IMAGE 2 is the exact WEATHER AND LIGHTING REFERENCE (cloudy, day). Relight and weather image 1 so its materials, sky, driveway and surroundings MATCH image 2 exactly. Preserve image 1's two vehicle silhouettes, parking locations, scale, wheelbase, complete windshield, distinctive boomerang Murano tail lights, and every wheel pixel-aligned: no moving or redesigning either car. Both cars must retain coherent undamaged body shapes. Match wet or dry pavement and reflections to image 2 around and under the driveway car, including its contact shadow.  The garage car remains sheltered. Keep all architecture in place, garage open with LEFT bay EMPTY and only Mercedes in RIGHT bay. Output one full-frame 1536x1024 image at the identical camera angle, no crop, text, UI, borders or additional vehicles. Final image must have image 2's cloudy day appearance with image 1's EXACT two cars.

### vehicles-rain-day

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET with the white 2021 Nissan Murano in the driveway and the correctly formed white Mercedes GLS in the right garage bay. IMAGE 2 is the exact WEATHER AND LIGHTING REFERENCE (rain, day). Relight and weather image 1 so its materials, sky, driveway and surroundings MATCH image 2 exactly. Preserve image 1's two vehicle silhouettes, parking locations, scale, wheelbase, complete windshield, distinctive boomerang Murano tail lights, and every wheel pixel-aligned: no moving or redesigning either car. Both cars must retain coherent undamaged body shapes. Match wet or dry pavement and reflections to image 2 around and under the driveway car, including its contact shadow.  The garage car remains sheltered. Keep all architecture in place, garage open with LEFT bay EMPTY and only Mercedes in RIGHT bay. Output one full-frame 1536x1024 image at the identical camera angle, no crop, text, UI, borders or additional vehicles. Final image must have image 2's rain day appearance with image 1's EXACT two cars.

### vehicles-snow-day

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET with the white 2021 Nissan Murano in the driveway and the correctly formed white Mercedes GLS in the right garage bay. IMAGE 2 is the exact WEATHER AND LIGHTING REFERENCE (snow, day). Relight and weather image 1 so its materials, sky, driveway and surroundings MATCH image 2 exactly. Preserve image 1's two vehicle silhouettes, parking locations, scale, wheelbase, complete windshield, distinctive boomerang Murano tail lights, and every wheel pixel-aligned: no moving or redesigning either car. Both cars must retain coherent undamaged body shapes. Match wet or dry pavement and reflections to image 2 around and under the driveway car, including its contact shadow. The Murano has just arrived: clean windows and only very light snow dust on its roof, while driveway remains cleared. The garage car remains sheltered. Keep all architecture in place, garage open with LEFT bay EMPTY and only Mercedes in RIGHT bay. Output one full-frame 1536x1024 image at the identical camera angle, no crop, text, UI, borders or additional vehicles. Final image must have image 2's snow day appearance with image 1's EXACT two cars.

### vehicles-fog-day

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET with the white 2021 Nissan Murano in the driveway and the correctly formed white Mercedes GLS in the right garage bay. IMAGE 2 is the exact WEATHER AND LIGHTING REFERENCE (fog, day). Relight and weather image 1 so its materials, sky, driveway and surroundings MATCH image 2 exactly. Preserve image 1's two vehicle silhouettes, parking locations, scale, wheelbase, complete windshield, distinctive boomerang Murano tail lights, and every wheel pixel-aligned: no moving or redesigning either car. Both cars must retain coherent undamaged body shapes. Match wet or dry pavement and reflections to image 2 around and under the driveway car, including its contact shadow.  The garage car remains sheltered. Keep all architecture in place, garage open with LEFT bay EMPTY and only Mercedes in RIGHT bay. Output one full-frame 1536x1024 image at the identical camera angle, no crop, text, UI, borders or additional vehicles. Final image must have image 2's fog day appearance with image 1's EXACT two cars.

### vehicles-cloudy-night

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET with the white 2021 Nissan Murano in the driveway and the correctly formed white Mercedes GLS in the right garage bay. IMAGE 2 is the exact WEATHER AND LIGHTING REFERENCE (cloudy, night). Relight and weather image 1 so its materials, sky, driveway and surroundings MATCH image 2 exactly. Preserve image 1's two vehicle silhouettes, parking locations, scale, wheelbase, complete windshield, distinctive boomerang Murano tail lights, and every wheel pixel-aligned: no moving or redesigning either car. Both cars must retain coherent undamaged body shapes. Match wet or dry pavement and reflections to image 2 around and under the driveway car, including its contact shadow.  The garage car remains sheltered. Keep all architecture in place, garage open with LEFT bay EMPTY and only Mercedes in RIGHT bay. Output one full-frame 1536x1024 image at the identical camera angle, no crop, text, UI, borders or additional vehicles. Final image must have image 2's cloudy night appearance with image 1's EXACT two cars.

### vehicles-rain-night

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET with the white 2021 Nissan Murano in the driveway and the correctly formed white Mercedes GLS in the right garage bay. IMAGE 2 is the exact WEATHER AND LIGHTING REFERENCE (rain, night). Relight and weather image 1 so its materials, sky, driveway and surroundings MATCH image 2 exactly. Preserve image 1's two vehicle silhouettes, parking locations, scale, wheelbase, complete windshield, distinctive boomerang Murano tail lights, and every wheel pixel-aligned: no moving or redesigning either car. Both cars must retain coherent undamaged body shapes. Match wet or dry pavement and reflections to image 2 around and under the driveway car, including its contact shadow.  The garage car remains sheltered. Keep all architecture in place, garage open with LEFT bay EMPTY and only Mercedes in RIGHT bay. Output one full-frame 1536x1024 image at the identical camera angle, no crop, text, UI, borders or additional vehicles. Final image must have image 2's rain night appearance with image 1's EXACT two cars.

### vehicles-snow-night

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET with the white 2021 Nissan Murano in the driveway and the correctly formed white Mercedes GLS in the right garage bay. IMAGE 2 is the exact WEATHER AND LIGHTING REFERENCE (snow, night). Relight and weather image 1 so its materials, sky, driveway and surroundings MATCH image 2 exactly. Preserve image 1's two vehicle silhouettes, parking locations, scale, wheelbase, complete windshield, distinctive boomerang Murano tail lights, and every wheel pixel-aligned: no moving or redesigning either car. Both cars must retain coherent undamaged body shapes. Match wet or dry pavement and reflections to image 2 around and under the driveway car, including its contact shadow. The Murano has just arrived: clean windows and only very light snow dust on its roof, while driveway remains cleared. The garage car remains sheltered. Keep all architecture in place, garage open with LEFT bay EMPTY and only Mercedes in RIGHT bay. Output one full-frame 1536x1024 image at the identical camera angle, no crop, text, UI, borders or additional vehicles. Final image must have image 2's snow night appearance with image 1's EXACT two cars.

### vehicles-fog-night

Use case: lighting-weather. IMAGE 1 is the EDIT TARGET with the white 2021 Nissan Murano in the driveway and the correctly formed white Mercedes GLS in the right garage bay. IMAGE 2 is the exact WEATHER AND LIGHTING REFERENCE (fog, night). Relight and weather image 1 so its materials, sky, driveway and surroundings MATCH image 2 exactly. Preserve image 1's two vehicle silhouettes, parking locations, scale, wheelbase, complete windshield, distinctive boomerang Murano tail lights, and every wheel pixel-aligned: no moving or redesigning either car. Both cars must retain coherent undamaged body shapes. Match wet or dry pavement and reflections to image 2 around and under the driveway car, including its contact shadow.  The garage car remains sheltered. Keep all architecture in place, garage open with LEFT bay EMPTY and only Mercedes in RIGHT bay. Output one full-frame 1536x1024 image at the identical camera angle, no crop, text, UI, borders or additional vehicles. Final image must have image 2's fog night appearance with image 1's EXACT two cars.

