# Radio hardware and music controls

Version 2.499.186.

Generated the radio's five transport buttons and three knobs directly into matching day/night photographs. Transparent, keyboard-accessible hit targets share the photograph's coordinate plane; volume, shuffle and repeat state appear in the amber display. Removed the shelf toolbar and album action badges. Choose an owner and Favorites/Recent in the radio screen, then use Browse these records on the shelf. Swipe or arrow keys browse; tapping the front record plays it. Context-click a record for its screen options.

The radio reuses MusicLogic and its existing selected-speaker lifecycle for previous/next, stop, shuffle, repeat, favorites, radio mode, queue editing, search filters and playlist actions. It does not register a new browser audio endpoint. Queue/library information is live text inside the photographed display. No household services were contacted during tests.

Validation: intercepted browser tests cover playback, saved stations, volume, race protection, queue edits/read-only fallback, house/personal favorites, playlist creation, search, cover flow, phone/landscape alignment and exit lifecycle. Template JavaScript and Tailwind checks also run.

## Artwork

Built-in imagegen edit mode; original assets retained.

- `chauffeur/static/house_hybrid/radio-controls-day.png`
- `chauffeur/static/house_hybrid/radio-controls-night.png`

### Day prompt

Use case: precise-object-edit. Edit the supplied daytime bookshelf photograph into a production background, maintaining exact 1536x1024 composition and geometry. Preserve bookshelf, records, plants, radio body, speaker, blank amber glass at x505..810 y350..485, and all lighting. Complete the radio with photographic physical hardware: replace the three unfinished knob bases with real aged brass rotary knobs centered exactly at (271,598), (479,598), (695,598), diameter  seventy pixels, first engraved power symbol, other two fine black index marks. Tiny engraved labels POWER, VOLUME, TUNING underneath. Integrate FIVE small recessed aged brass pushbuttons in a single row in the wood strip beneath the glass, centers (500,534),(568,534),(636,534),(704,534),(772,534), each roughly  fifty by thirty pixels. Engraved icons in order previous track, next track, stop square, crossed shuffle arrows, repeat arrows. These must look manufactured into this real vintage radio, recessed seams, patina, contact shadows, same perspective and illumination, NOT pasted rectangles or UI. Preserve blank nameplate x300..454 y523..549. Keep amber screen empty for live text. No other buttons, text, interface or changes to the shelf. Photorealistic high quality.

### Night prompt

Use case: lighting-weather. Image 1 is edit target: finished radio bookshelf daylight photograph. Image 2 is lighting reference only. Produce the NIGHT version of image 1 matching image 2 warm dim under-shelf lighting. Preserve EXACT geometry, composition, all five brass transport buttons, three completed knobs and their engraved symbols and labels, blank amber screen, nameplate, books, plants, grain. Only change illumination. 1536x1024 photorealistic background, no UI or added text.

