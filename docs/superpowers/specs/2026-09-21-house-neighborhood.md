# Layered neighborhood street scene

Version 2.499.145 builds eight distinct nearby designs through the detailed parametric renderer.
The objective is a full neighborhood surrounding the active home, including its rear.

## Layout and styles

A deterministic seven-by-seven parcel grid leaves the center for the active home:
eight distinct detailed neighbors, forty simpler mixed-style outer houses, then a continuous painted
panorama of distant roofs and trees. Paired rows face shared streets. The ground,
sidewalks and road extensions reach the horizon instead of ending beside the home.

Four facade-compatible recipes supply both rings; nearby variants also change block
depth, garage ridge, porch span and upper-story extent:

| Style | Distinguishing features |
| --- | --- |
| Farmhouse | White batten, steep gables, two stories, black frames, covered porch |
| Craftsman | Sage lap, lower cross-gables, broad grouped windows, gabled porch with substantial posts and masonry bases |
| Modern | Greige stucco, black trim, two stories, low hip roofs, flat entry canopy and glazed garage door |
| Ranch | Single story, pale brick, low hip roofs, grouped windows and shutters |

The modern recipe respects the existing schema's 22.5-degree minimum and hip/gable
main-roof vocabulary; it does not introduce flat main roofs. Both rings use mixed styles. The eight nearby designs differ in geometry, not only
paint or mirrored placement. The user's active design is not used as a template.

## Rendering

`buildDetailedExterior(spec, renderer)` is the exterior entry point into the same
parametric construction code used by the active home. Explicit facade input replaces
reads from the active home's injection; neighboring construction cannot mutate that
injection. Each distinct near spec is built once. It reuses the active WebGL renderer
without attaching another canvas, constructing Study, building room cutaway masks,
starting household behavior or recursively creating another neighborhood.

The shared legacy construction still creates temporary room scaffolding while supplying
its geometry helpers. That scaffolding is not retained or rendered: the exterior path
returns before household painters/runtime wiring, captures only exterior geometry and
releases its temporary scene. Eight separate builds increase startup work as well as
rendering cost. This is an explicit exterior entry point, not a complete physical
extraction of every legacy geometry helper into a separate module.

`captureExterior` preserves detailed roofs, openings, porches, landscaping, UVs, normal
maps and baked shading, excluding vehicles, garage contents, labels, lights, cutaways
and duplicated roads. Owned material/geometry kits also own the retained textures from
their temporary builds. Disposal closures are outside construction/capture scopes so
they do not retain temporary scenes and work arrays. Mirrored instances reverse winding
without negative instance scales. Far houses continue to use the simplified projection.

Hip deck UVs now use the shared roof texture's world scale; the previous extrusion UVs
made shingles so dense that hip roofs read as flat-colored surfaces.

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
budgets, including distinct kit counts and fingerprints of the actual captured vertex
positions. The first high-tier measurement has eight distinct geometry fingerprints,
about 1.22 million total triangles, and 547 extra draw calls. Costs depend on quality;
Raspberry Pi frame times remain unverified.

## Verification

Pure tests validate all 48 facade specs, generation stability, no canonical mutation,
style recipes, rear coverage, near/far detail differences, inert
picking, camera/room visibility and resource disposal. Capture tests cover full
single-material geometry groups, transformed instances, mirrored triangle winding,
retained UV/color attributes, road exclusion and ownership of copied resources. Browser checks cover high/low
quality, all eight orbit stops, room entry/exit and marker clicks, narrow-screen layout,
editor isolation and the rendered panorama. The browser gate requires eight distinct
geometry fingerprints and exactly one mounted renderer canvas. No live model calls are required.

Neighbor interiors, roaming and saved neighbor editing remain outside this slice.

The generated grid remains the fallback. Version 2.499.146 adds
[map-derived street placement](2026-09-22-mapped-neighborhood.md) while retaining
these rendering tiers and distinct designs.
