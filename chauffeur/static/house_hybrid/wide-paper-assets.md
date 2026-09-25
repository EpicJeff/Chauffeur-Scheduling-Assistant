# Wide household paper surfaces

Generated September 25, 2026 with the built-in image-generation tool in edit mode.
Original portrait images remain the phone/narrow-layout assets. All images are
1536 x 1024; geometry is registered in `house_utility_rooms.js` and
`house_kitchen.js`. The camera fits the whole physical frame, while controls
occupy only the blank paper. Day/night variants share registration.

| Assets | Reference | Physical object |
| --- | --- | --- |
| mudroom-chores-wide-day.png, mudroom-chores-wide-night.png | mudroom-chores-day.png | Oak cork pinboard with four brass pins |
| mudroom-routines-wide-day.png, mudroom-routines-wide-night.png | mudroom-routines-day.png | Oak clipboard with brass clip on shelf |
| kitchen-board-wide-day.png, kitchen-board-wide-night.png | kitchen-board-day.png | Kitchen cork board with pinned calendar sheet |

## Prompts

Chores initial edit: ?Edit this photograph for a wide landscape wall-panel application. Photorealistic same oak-and-cream mudroom. Make the main cork pinboard and pinned blank cream paper much WIDER horizontally, a landscape rectangle. Output 1536x1024. Straight-on camera no perspective skew. Oak outer frame bounding rectangle x35 y155 to1501 y865, cork inset, blank cream paper rectangle x100 y220 to1436 y800, four small brass pins near paper corners. Keep ALL four outer frame edges fully visible. Keep narrow strips of cream wall around frame, slim oak shelf beneath with plant partly at lower corners, warm natural daylight. Paper must be flat, blank, evenly lit with subtle texture, no writing no UI. The wide paper occupies most of the width, but the frame, cork, pins, shadow on wall, shelf prove it is a real household object. Preserve material language of reference, recompose surrounding room to fit the wider board, no overlays.?

Chores refinement: ?Edit ONLY the central cork board: make it a much wider panoramic shallow horizontal rectangle, width unchanged but height reduced by 25 percent. Reduce the thick cork margins to only a narrow band around the paper, enlarging paper to almost touch the inner oak frame. Entire frame and paper must remain visible. Blank paper should have a 2.5:1 aspect ratio. Keep brass pins, fine paper texture, narrow cork surround, oak frame, shelf, room lighting and 1536x1024 photo composition. No writing. This must be a wide household planning board, not a portrait page.?

Routines initial edit: ?Edit this photograph into a wide landscape household clipboard. Output 1536x1024. Preserve photorealistic oak cream mudroom, brass clip, shelf, plants. Central clipboard must be wide horizontal rectangle, outer wooden board from x180 y190 to x1370 y740, blank cream paper x210 y225 to x1340 y710. Small brass clip at top center above writing area. All four wooden board edges visible. Move plants to edges so nothing overlaps paper. Straight on flat paper, blank no text or UI. Large landscape paper nearly fills board. Natural daylight. Actual physical wood and brass with room context.?

Routines refinement: ?Keep this photograph identical except make wooden clipboard and blank paper 30 percent shorter in height with bottom still resting on shelf. Keep width unchanged, top of board lower, brass clip lower with top edge. This should be a panoramic landscape clipboard, 2.4 times wider than tall. Blank paper fills board with narrow wooden edges. Same room and daylight. Output1536x1024.?

Calendar edit: ?Recompose this exact kitchen photograph with a panoramic wide shallow calendar cork board. Output1536x1024. Board is 3 times wider than tall. Entire oak frame visible surrounded by cream wall. Huge blank cream landscape sheet occupies 90% of board width and 80%height, brass pins in corners, thin cork margin. Board centered, from approximately x120 y260 to1410 y780. No writing no UI. Move small photos to wall beside board, foliage outside paper. Preserve warm natural kitchen daylight oak materials, lemon bowl and pitcher on counter at bottom, straight-on camera. Paper must be much wider than tall.?

Night edits use each selected day image as reference: preserve geometry, paper edges, pins, frame and camera; change only illumination to warm household lamplight with dark outdoors, keeping blank paper readable. No text or new objects, 1536x1024 output.

## Verification

Browser regression tests cover five child lanes, full frame visibility, paper
registration, portrait/landscape switching, day/night artwork, panel-theme
transparency and the calendar's live month/event controls. Screenshots are
written to the test output directories under scratch.
