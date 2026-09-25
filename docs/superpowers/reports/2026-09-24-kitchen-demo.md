# Populated kitchen preview

URL: http://127.0.0.1:50978/house?compare=exterior&scene=kitchen&light=day

The running scratch/serve_hybrid.py imports chauffeur/tools/kitchen_demo.py. Fixtures require CHAUFFEUR_DATA_DIR and use the preview temporary database. Dates follow today. No external calendar, weather, media-player or family account writes.

Seven dinners, fourteen calendar events (including four today), fourteen additional shopping items, three fictional photo moments, rainy current weather and a five-day forecast. Existing living-room demo fixtures remain enabled. Shopping check/undo uses the normal API and temporary storage.

Verified against the running server with scratch/check_kitchen_demo.py: actual API payloads, photo loading/viewer, populated meal rendering, calendar event details, pantry check/undo, and weather. Browser errors: none. Screenshots: scratch/kitchen-populated/.

## Demo image assets

Generated using built-in ImageGen, copied into scratch/kitchen-demo-media/{picnic,dog,painting}.png and served only by the demo server. Fictional people and scenes, not user family photos.

### picnic

A candid family picnic at a leafy park, two adults and two school-age children laughing around a checkered picnic blanket, sandwiches and strawberries, natural imperfect smartphone photo, warm afternoon light. Fictional people. No text. Landscape 4:3.

### dog

An ordinary affectionate family snapshot of a golden retriever carrying a tennis ball on a sandy beach, ocean behind, late afternoon natural smartphone photograph, no text, portrait composition.

### painting

A family snapshot of two school-age children proudly holding their colorful watercolor paintings at the kitchen table, paint supplies and a little mess, believable candid smartphone photo, fictional people, no text. Landscape 4:3.
