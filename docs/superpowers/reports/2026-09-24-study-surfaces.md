# Study surfaces and exterior vehicle presence

The hybrid Study now opens each object on its own photographed surface. Intake uses the wooden tray and a browsable paper stack; Agreements opens a two-page book; Findings and Connections have different pinned sheets; gauges carry live vector ticks, needles and values; the family baseline uses a plant instead of the monitor. Existing full-screen coverage calendar, desk pad and program binder remain.

The school bus footprint is 37% of the exterior image width, up from 24% (54% larger). An exterior fleet strip shows every vehicle's thumbnail, name, home/away/unknown state, and available fuel/charge reading. It remains visible when cars are parked indoors. Navigation stays above the enlarged bus hit target.

## In-room details and actions

- Plans: actual step text, owner, due date, notes and attached proposal summary. Complete or skip human steps; prepare and explicitly approve tool steps; set a plan aside or mark it handled.
- Intake: one proposal per sheet; date/title/sender sorting; previous/next navigation; editable title, dates, location and notes; destination selection, supply selection, approval and ignore.
- Programs: current phase, practice instructions, milestone, current lesson and notes, existing progress counts; log practice with minutes and note, pause/resume, or mark the current milestone reached.
- Agreements: event/date, proposed arrangement, individual asks and reply states; explicit send-asks control and close-agreement control. No messages were sent during verification.
- Findings: mark handled or dismiss. Connections: read thread/insight details and make a plan or set an insight aside.

All actions reuse established endpoints and the current bounded parent session. The only new endpoint locates a visible trip using the existing geocoder, validates the returned coordinates, and stores the location alias. Refreshes preserve unsubmitted edits. Failed saves remain visible; duplicate clicks are blocked; late responses cannot repopulate a locked Study.

## Geography and baseline

The map uses actual Natural Earth country geometry with an equirectangular projection shared by the trip pins. Source data is [public domain](https://www.naturalearthdata.com/about/terms-of-use/); provenance is beside `world-map.svg`. Pins use cached destination latitude/longitude and link with the trip's `event_id`, not its unrelated metadata ID. Unknown, nonfinite and failed `(0, 0)` geocodes stay unpinned. An explicit Locate destination action uses the app's configured geocoding service; no geocoder runs merely by opening the room. A location still needs to be specific enough for that service to resolve correctly.

The plant reflects existing baseline readiness and worse-than-usual signals: forming baseline, thriving (no worse signals), drooping (one), wilting (two or more). These are illustrations of those signals, not a newly invented health score. Both the room overview and plant close-up change, with separate day/night photographs. Phone views can move between plant and note, or between individual gauges.

## Validation

Passed:

1. `python tests/test_study_state.py` — aggregation, role filtering, real details, calm fallback and trip visibility.
2. `python tests/test_house_parent_session.py` — existing bounded parent sessions.
3. `python tests/test_house_connected_live.py --out ../scratch/study-revision-connected` — room navigation, kitchen icons/Groceries, all object surfaces day/night, phone/landscape/ultrawide full-screen photography, PIN, lock and history.
4. `python tests/test_house_exterior_live.py --out ../scratch/study-revision-exterior` — enlarged bus, each fleet vehicle/status, live presence changes and exterior navigation.
5. `python tests/test_house_study_surfaces_live.py --out ../scratch/study-surfaces` — actual isolated-database writes for plan completion, intake approval, practice logging, pause/resume, finding resolution and agreement closure; coordinate projection and lookup; all four plant states; separate book pages; phone layouts; dirty-form preservation; injected save failure; expiry during a pending request and late-result rejection.
6. Running preview smoke check — actual populated records and new photographs load, all seven revised close-ups open, locking clears private data, four vehicle presence entries remain visible.
7. JavaScript syntax checks and `git diff --check`.

Browser evidence is in the scratch directories above and `scratch/study-preview`. Verification uses isolated fictional storage. External calendar writes, AI generation of new plans, live geocoder network quality and actual message delivery were not exercised.

Twenty images were generated through built-in ImageGen and copied into project assets. Exact prompts and original output paths are in [the provenance record](2026-09-24-study-surfaces-prompts.md). No purchased artwork or CLI image generation was used.

Preview: http://127.0.0.1:50978/house?compare=exterior&traffic_demo=1

Demo Parent PIN: `1234`.
