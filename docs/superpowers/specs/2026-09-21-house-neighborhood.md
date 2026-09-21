# Layered neighborhood street scene

Version 2.499.143 replaces the five-house exterior slice from 2.499.142.
The objective is a full neighborhood surrounding the active home, including its rear.

## Layout and styles

A deterministic seven-by-seven parcel grid leaves the center for the active home:
eight immediate neighbors, forty simpler outer houses, then a continuous painted
panorama of distant roofs and trees. Paired rows face shared streets. The ground,
sidewalks and road extensions reach the horizon instead of ending beside the home.

Four facade-compatible recipes are independent of parcel placement:

| Style | Distinguishing features |
| --- | --- |
| Farmhouse | White batten, steep gables, two stories, black frames, covered porch |
| Craftsman | Sage lap, lower cross-gables, broad grouped windows, gabled porch with substantial posts and masonry bases |
| Modern | Greige stucco, black trim, two stories, low hip roofs, flat entry canopy and glazed garage door |
| Ranch | Single story, pale brick, low hip roofs, grouped windows and shutters |

The modern recipe respects the existing schema's 22.5-degree minimum and hip/gable
main-roof vocabulary; it does not introduce flat main roofs. This release uses a
mixed neighborhood, without an automatic style classifier or a style-selection UI.

## Rendering

`house_neighborhood.js` consumes the shared facade schema, block envelopes, palette
and material factory. Nearest houses are full-scale exterior projections with the
active renderer's procedural cladding/shingle tiles, foundations, corner/eave trim,
window frames/grilles/sills, fences and fuller trees. These are medium-detail scenery,
not copies of the active home's detailed interior/cutaway renderer. Outer houses
omit textures and most trim/yard details while preserving style and silhouette.

The horizon is a deterministic 4096x512 canvas on a continuous cylindrical surface;
wrapped painter copies prevent a seam. Transparent sky reveals the existing weather
sky dome. Its tint follows the active home's day/night transition. No images, providers, map service,
address or household data are requested. All scenery remains render-on-demand.

Instanced geometry shares surface materials. Active cladding textures are borrowed
from its cache; the neighborhood owns and disposes its materials, instance buffers,
geometries and panorama texture. The sky/far plane grow only in normal house views.

## Navigation and limits

The neighborhood stays outside `houseRoot`, independent of the active house's mirror.
It has no room hit-testing or household state. Room views hide the whole neighborhood.
Foreground lots within the camera-to-house corridor hide to preserve active-home
visibility; lots can appear/disappear while orbiting. Photo/editor captures (`editor=1`)
exclude all scenery and retain the original sky and far plane.

`chfNeighborhood()` reports near/far counts, style, placement, visibility and geometry
budgets. The current scene has 5,407 instances and 77,932 triangles including the
panorama, in twelve batches. Chromium measured 23 added draw calls on high and twelve on low.
Device-level Raspberry Pi frame times remain unverified.

## Verification

Pure tests validate all 48 facade specs, generation stability, no canonical mutation,
all four styles in the near ring, rear coverage, near/far detail differences, inert
picking, camera/room visibility and resource disposal. Browser checks cover high/low
quality, all eight orbit stops, room entry/exit and marker clicks, narrow-screen layout,
editor isolation and the rendered panorama. No live model calls are required.

Neighbor interiors, roaming, saved neighbor editing and automatic matching to the
user's house style remain outside this slice.
