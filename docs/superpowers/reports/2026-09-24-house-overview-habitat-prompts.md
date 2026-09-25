# Living-room habitat overview prompts

Built-in ImageGen. Day inputs: `living-day.png` (edit target), `habitat-day.png` (habitat reference). Night inputs: `living-habitat-day.png` (edit target), `living-night.png` (lighting reference).

## Day

```text
Use case: precise-object-edit.
Asset type: production background for an interactive living-room overview, 1536 x 1024.
Input images: Image 1 is the edit target and must retain its exact camera, room composition and object positions. Image 2 is a supporting reference showing the critter habitat to place in the room.
Primary request: In Image 1 replace the small cream bowl of round objects on the coffee table with a miniature version of the walnut critter habitat from Image 2. It is a shallow rectangular dark walnut tray with a sandy open clearing, moss, tiny ferns, small stones and two little driftwood pieces, and a blank brass front nameplate with two round brass knobs. Make it convincingly sit on the existing coffee table in this wide view, in the bowl's spot, centered around 44.5% across and 53% down the image. The habitat should occupy approximately the left half of the coffee tabletop, roughly 190-220 pixels wide in this 1536-pixel-wide composition, and be clearly identifiable as the same habitat viewed from farther away. Match the room's perspective, scale, daylight, contact shadows and photorealistic materials.
Constraints: Edit only the bowl and immediately surrounding coffee-table area necessary for its replacement. Preserve the fireplace, sofa, chair, built-in shelves, radio at upper left, foreground teal Home Ledger book and burgundy Program book, windows, curtains, plants, picture frames, flooring, framing and camera angle. Keep the rest of the photo as unchanged as possible. No generated creatures, people, labels, lettering, buttons, watermarks or interface overlays. Keep the sand clearing empty. Do not enlarge the coffee table or change the room.
```

## Night

```text
Use case: lighting-weather.
Asset type: paired night background for an interactive living-room overview, 1536 x 1024.
Input images: Image 1 is the edit target: the updated DAY living room with the walnut habitat on the coffee table. Image 2 is the original NIGHT version of this same living room, used only as a lighting reference.
Primary request: Relight Image 1 to the warm nighttime setting of Image 2. Preserve the new miniature walnut habitat exactly: the same size, location, perspective, sandy clearing, moss, ferns, stones, driftwood, two brass knobs and blank brass plate. The bowl must not return. Outside the windows it is blue-black night with subtle garden lighting; the fireplace, table lamps, candles and shelf lights create warm amber illumination, as in Image 2.
Constraints: Only lighting and outdoors time-of-day change. Preserve Image 1's exact camera, crop, room geometry, sofa and chairs, shelves, radio, foreground teal and burgundy books, coffee table, picture frames and habitat geometry. Keep every interactive object in exactly the same pixel position as Image 1 so switching day/night does not move the hotspots. Do not copy the bowl from Image 2. No people, creatures, writing, labels, watermark, buttons or interface graphics. Keep it photorealistic and legible at night, matching Image 2's brightness.
```
