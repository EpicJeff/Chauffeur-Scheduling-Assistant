# Layered neighborhood street scene

Version 2.499.144 upgrades the nearest houses to the active home's exterior quality.
The objective is a full neighborhood surrounding the active home, including its rear.

## Layout and styles

A deterministic seven-by-seven parcel grid leaves the center for the active home:
eight detailed matching-home neighbors, forty simpler mixed-style outer houses, then a continuous painted
panorama of distant roofs and trees. Paired rows face shared streets. The ground,
sidewalks and road extensions reach the horizon instead of ending beside the home.

The nearest houses reuse the user's finished exterior. Four facade-compatible recipes
remain independent of parcel placement for the outer ring:

| Style | Distinguishing features |
| --- | --- |
| Farmhouse | White batten, steep gables, two stories, black frames, covered porch |
| Craftsman | Sage lap, lower cross-gables, broad grouped windows, gabled porch with substantial posts and masonry bases |
| Modern | Greige stucco, black trim, two stories, low hip roofs, flat entry canopy and glazed garage door |
| Ranch | Single story, pale brick, low hip roofs, grouped windows and shutters |

The modern recipe respects the existing schema's 22.5-degree minimum and hip/gable
main-roof vocabulary; it does not introduce flat main roofs. The outer ring uses a
mixed neighborhood; the inner ring matches the actual rendered home without a
style classifier or a style-selection UI.

## Rendering

`captureExterior` freezes the active renderer's finished exterior after its geometry,
clipping, merging and ambient-occlusion passes. This replaces the earlier simplified
projection for the eight nearest lots: roofs, openings, porch details, authored
landscaping, texture UVs, normal maps and baked vertex shading are retained. Neighbors
follow the active rendering tier (high on high, reduced alongside the home on low).
No second house build or renderer/context is created.

The capture excludes garage contents, vehicles, sky, runtime labels/screens, room-only
cutaways and lights. Shared road triangles are omitted. Meshes and existing instanced
scenery are flattened into material batches, then instanced across nearby lots.
Mirrors reverse triangle winding while keeping instance matrices positive. Maps are
borrowed; materials and geometry are owned copies, so room navigation and source
material changes cannot mutate the frozen neighbors. Source resources are not disposed
when the neighborhood is released. Further houses retain the low-detail projection.

The horizon is a deterministic 4096x512 canvas on a continuous cylindrical surface;
wrapped painter copies prevent a seam. Transparent sky reveals the existing weather
sky dome. Its tint follows the active home's day/night transition. No images, providers, map service,
address or household data are requested. All scenery remains render-on-demand.

The sky/far plane grow only in normal house views. Capture and instancing occur once
per house build, not per frame; scenery remains inert for room hit-testing.

## Navigation and limits

The neighborhood stays outside `houseRoot`, independent of the active house's mirror.
It has no room hit-testing or household state. Room views hide the whole neighborhood.
Foreground lots within the camera-to-house corridor hide to preserve active-home
visibility; lots can appear/disappear while orbiting. Photo/editor captures (`editor=1`)
exclude all scenery and retain the original sky and far plane.

`chfNeighborhood()` reports near/far counts, style, placement, visibility and geometry
budgets, including source exterior mesh/instance/triangle counts. A canonical high-tier
capture contains about 144,000 triangles; all scenery totals about 1.2 million triangles.
The first browser measurement added 151 draws on high. Costs depend on the user's
facade and quality tier. Device-level Raspberry Pi frame times remain unverified.

## Verification

Pure tests validate all 48 facade specs, generation stability, no canonical mutation,
style recipes, rear coverage, near/far detail differences, inert
picking, camera/room visibility and resource disposal. Capture tests cover full
single-material geometry groups, transformed instances, mirrored triangle winding,
retained UV/color attributes, road exclusion and ownership of copied resources. Browser checks cover high/low
quality, all eight orbit stops, room entry/exit and marker clicks, narrow-screen layout,
editor isolation and the rendered panorama. No live model calls are required.

Neighbor interiors, roaming, saved neighbor editing and varied high-detail style
recipes remain outside this slice. The immediate neighbors currently repeat the
active exterior with mirrored placements; the outer ring supplies style variety.
