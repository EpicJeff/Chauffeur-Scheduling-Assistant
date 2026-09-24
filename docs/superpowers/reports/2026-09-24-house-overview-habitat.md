# Match the overview to the critter habitat

Version 2.499.174 · `feature/living-room-atmosphere`

The day and night living-room overviews now show the walnut critter habitat
instead of the bowl on the coffee table. The shallow tray, sandy clearing, moss,
ferns, driftwood and brass front match the habitat close-up. The room camera,
radio, foreground books and existing hotspot positions remain aligned.

Built-in ImageGen edited the original day overview using the habitat close-up
as the object reference. The night edit uses the new day view for geometry and
the original night overview for lighting. Original overview assets are retained.
No live creature art was baked into the room images.

Saved assets:

- `chauffeur/static/house_hybrid/living-habitat-day.png`
- `chauffeur/static/house_hybrid/living-habitat-night.png`

The comparison template now loads the new pair through the existing versioned,
lazy-loading day/night path. [Exact prompts](2026-09-24-house-overview-habitat-prompts.md)
record generation provenance.

Validation: image inspection and `test_house_hybrid_live.py` cover overview
loading, marker registration, day/night changes, all destinations, phone
navigation, no-WebGL operation and the 3D comparison. Browser screenshots were
reviewed in ignored `scratch/overview-habitat-review/`.
