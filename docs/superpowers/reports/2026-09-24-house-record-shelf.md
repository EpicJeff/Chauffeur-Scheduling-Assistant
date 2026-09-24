# Radio records and search

Version 2.499.168 · `feature/living-room-atmosphere`

Superseded visually in v2.499.169 by [albums inside the photographed shelf](2026-09-24-house-record-bay.md).
The shared music behavior below is retained; the separate record strip is replaced.

The radio now has a wooden record ledge beneath it. HTML/CSS sleeves carry live
Music Assistant cover art, titles and artist/type labels. They have slight depth,
straighten on hover/focus, and browse horizontally with touch, keyboard or the
previous/next buttons. Missing artwork leaves a titled paper sleeve. No generated
bitmap assets, dependencies or backend endpoints were added.

Choose whose shelf to browse; Favorites and Recent read the same personal music
store as the music card. A sleeve plays through the radio's selected speaker and
records that choice for the selected member. Save/Remove uses the shared favorite
methods. Shelves are never merged and switching people clears the previous shelf
immediately. The choice is remembered locally for this radio surface.

The search symbol in the radio glass moves the camera closer to its display.
Type an artist, album or song and press Find/Enter. Results appear as record
sleeves on the same ledge, with playback and save controls. Searching and playing
work without a personal selection; saving requires one. Radio/Escape returns to
the ordinary face; a second Escape returns to the room. Reduced motion removes
the camera animation. Short screens can scroll down to the record ledge.

The implementation reuses `MusicLogic.search`, `flatten`, `imageOf`, `myShelf`,
`addFavorite`, `removeFavorite` and `play`. Artwork keeps the shared authenticated
proxy handling. Search and shelf requests are guarded against stale responses
after another request, a member switch or leaving the room. Failed search/save
requests have visible messages. No hidden music widget or browser player is
started. Advanced provider filters, queue management and artist/album track
drill-down remain in the existing music surfaces.

## Verification

- `tests/test_house_records_live.py`: personal separation, proxied art, playback
  attribution and recent items, search, save/remove, superseded results, failures,
  phone input geometry, shelf navigation, short-screen playback and Escape.
- `tests/test_house_radio_live.py`: existing playback, tuning, volume, touch,
  failures and polling lifecycle.
- `tests/test_house_hybrid_live.py`: all destinations, day/night, mobile,
  navigation, reduced motion, no WebGL and the 3D comparison.

All passed. Desktop and phone captures were visually reviewed in
`scratch/record-review/`; the test artwork is a deterministic SVG fixture.
The ignored preview script offers demo records with geometric covers and
simulated playback. Production uses the user's Music Assistant catalog and
personal shelves. Physical speaker playback has not been auditioned here.
