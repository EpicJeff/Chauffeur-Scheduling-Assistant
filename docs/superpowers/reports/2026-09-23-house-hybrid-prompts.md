# House hybrid artwork: exact prompts

Built-in ImageGen, 2026-09-23. First call generated night with no reference;
second call edited that output to day. See the [comparison report](2026-09-23-house-hybrid-comparison.md).

## Night generation

```text
Use case: stylized-concept, premium photoreal architectural visualization.
Asset type: finished background artwork for an interactive living-room interface; landscape 3:2 composition at the highest available resolution.
Create one extraordinarily beautiful, believable living room at NIGHT, viewed from a fixed elevated three-quarter camera through an invisible front wall. Fill the frame with the room, not an entire house or exterior. Aim for high-end offline architectural rendering: detailed meshes, softly rounded linen upholstery, convincing oak grain, honed limestone, aged brass, lush individual plant leaves, realistic contact shadows and warm bounced illumination against cool blue night at the windows. This should look like an expensive interior visualization, never low-poly, toy-like, or a game screenshot.
Scene: rear wall has a limestone fireplace with a real small fire and built-in oak bookshelves; a vintage tabletop radio is clearly visible on a shelf to the LEFT of the fireplace. A cream linen sofa faces the fireplace, with muted teal cushions and a casually draped woven throw. A rounded wooden coffee table in front of it has an elegant shallow pet-treat bowl and a small pet photo frame as the Critters destination. Behind or beside the sofa on the RIGHT, an oak console has two clearly separate landing spots: a dark teal household ledger book nearer the center, and a burgundy hardcover program book farther right. Both books must be visibly distinct and unobstructed. A comfortable reading chair, soft wool rug, floor lamp, leafy plants, tasteful framed art and restrained accessories complete the room. Tall windows on the right show a quiet cool navy night garden. Include a visible doorway at far left as the room exit.
Composition: generous separation of the radio, coffee-table bowl, and the two console books so HTML markers can later sit over them. Keep these four targets inside the central 80% of the frame. Keep the lower 12% unobstructed by important targets, for application chrome. Natural architectural perspective, sharp enough that all destinations are readable; subtle atmospheric depth, no extreme depth of field, no fisheye. Cohesive warm oak, cream, slate teal and restrained burgundy palette.
Lighting: warm shaded practical lamps and fireplace glow, soft physically believable shadows, attractive dimensional illumination. The room is inviting and comfortably visible, not murky. Cool dim blue exterior contrasts with the warm interior.
Constraints: only the room artwork. NO words, text, captions, labels, icons, UI, watermarks, logos, people, or split-screen. Preserve believable proportions and architectural detail. This will later be relit to daytime while keeping every object and the camera fixed.
```

## Day edit

```text
Use case: lighting-weather edit. This input is the EDIT TARGET, a finished night interior used as an interactive background. Make the matching DAYTIME version of precisely this image. Change ONLY illumination, exposure, and the view's time of day outside the existing windows. Soft natural morning daylight enters from the windows on the right; outside becomes a softly sunlit green garden. Retain gentle warm practical lamps and the small fireplace fire, with lower prominence against daylight. Preserve the elegant, photoreal architectural-render quality and all material texture.
STRICT INVARIANTS: Identical camera, framing, perspective, image aspect ratio and resolution. Do not crop, rotate, recompose or move ANY object. Preserve every architectural edge, window mullion, doorway, shelf, plant silhouette, piece of furniture, pillow, rug, decorative object, artwork, and their exact positions. In particular preserve the vintage radio at left (around 22% x,26% y), pet treat bowl and photo frames on the coffee table (around 45% x,53% y), teal ledger on the console (around 80% x,71% y), and burgundy program book on the far right console (around 90% x,67% y). Interactive HTML hotspots must hit the identical objects in both images. Preserve the sofa, console and books without altering shape, size or orientation. No additions, deletions, text, labels, UI or watermark. The result is one full-frame daylight image, not a comparison or a collage.
```
