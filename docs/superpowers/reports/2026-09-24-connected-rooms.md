# Connected photographic rooms

The hybrid exterior now has complete kitchen icons, and Groceries is the name on both the exterior preview and kitchen object. The pantry artwork remains the place where groceries live.

The mudroom provides Next up on a departure display, Chores on its corkboard and Routines on its clipboard. The Study provides all eleven existing destinations: Connections board, Plans in hand, Intake tray, Findings, Coverage calendar, Family baseline, Agreements, Program binders, Argyle gauges, Household monitor and Travel map. Related paper objects share desk/board perspectives; monitor views show live readouts. Coverage is drawn as a real monthly paper calendar. These use existing household cards and `/api/study/state`; no new production endpoint or WebGL dependency.

Walkthrough markers connect Living room ↔ Kitchen ↔ Mudroom ↔ Garage and Living room ↔ Study. Browser Back/Forward follows room visits and individual lean-ins. Outside explicitly returns to the exterior. Full-screen images cover every viewport edge; small screens can pan the scene while content remains readable on the object.

Study entry uses the existing parent PIN and bounded house session. Data is fetched with that session's token, removed on lock/exit/expiry, and checked again on restored pages. Parent actions retain the existing managed-page destinations and return flow.

## Artwork

Built-in ImageGen generated the 20 selected PNGs in `chauffeur/static/house_hybrid/` with prefixes `mudroom-` and `study-`. No purchases or API fallback. Room overviews use the kitchen day photograph as a style reference; each close-up uses its room overview, and night edits use their corresponding day image. Exact prompts and output paths are in [the prompt log](2026-09-24-connected-rooms-prompts.md).

## Review and validation

- `tests/test_house_connected_live.py --out ../scratch/connected-rooms`: complete kitchen icon fan, Groceries naming, every new object day/night, actual sample data, five connected rooms, history, parent PIN, lock/expiry, phone/landscape/ultrawide full-screen coverage.
- `tests/test_house_kitchen_live.py --out ../scratch/connected-kitchen`: kitchen regression, including nighttime clock/plant exposure.
- `tests/test_house_exterior_live.py --out ../scratch/connected-exterior`: exterior previews, hold visits, touch, history, traffic and existing living-room effects.

The isolated running preview is `http://127.0.0.1:50978/house?compare=exterior`. It includes fictional data via `tools/connected_rooms_demo.py`, loaded only by the ignored `scratch/serve_hybrid.py` launcher. Its fictional **Demo Parent** uses PIN **1234**. No fixture code is loaded by the application itself.
