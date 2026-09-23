# Hybrid living-room comparison

2026-09-23 · v2.499.164 · `feature/living-room-atmosphere`

## Try it

Run this feature branch and open `/house?compare=living`. Switch between Hybrid
and 3D in the toolbar. Try the same four cards, then compare day and night.
`light=day` and `light=night` are preview overrides; omit them to follow the sun.
Existing query preferences and ingress prefixes survive switching. Full house
returns to the ordinary House. No production Home setting is changed.

The hybrid uses a curated interior, with HTML buttons placed over the depicted
radio, pet destination and books. On phones, four larger buttons sit below the
uncropped room image. They open the same live cards as 3D, including parent PIN
requirements for managing household work. There is no hidden WebGL renderer:
the template omits Three.js and House scene scripts, and switching reloads the page.

## What this comparison establishes

It tests the appearance and usefulness of fixed artwork with live cards on top.
The room has no free camera, animated geometry or personalized interior. The
generated camera/layout differs from the procedural living room; this is a
comparison of the two experience directions, not an isolated lighting benchmark.
The earlier 3D prototype remains available in the same branch.

Automatic lighting consumes the existing `window.night` and `next_sun_change`
state, refreshes every minute while visible, and schedules the next sun boundary.
The alternate image loads only when needed and then crossfades. A failed state
request retains the last sun state; artwork failure leaves card buttons usable.
Hidden pages stop polling; a restored browser-history page resumes updates.

The 1536×1024 PNGs are 2,829,811 bytes (day) and 2,699,911 bytes (night).
Only the selected variant loads initially. This prototype prioritizes source
quality; image delivery size is a remaining production optimization. Two decoded
RGBA images would be about 12 MiB before browser/compositor overhead, not a
measurement of total application memory.

The toolbar reports navigation-to-room-ready time for that visit. Hybrid waits
for the selected image and a paint opportunity; 3D waits for a settled living
room and all four markers. Cache, server response, device and connection affect
this number. It is not an FPS or GPU measurement. Compare on the actual wall
panel before drawing hardware-performance conclusions.

## Assets and generation

Generated with the built-in ImageGen tool. Night was generated first; day was an
edit of that exact image. Both outputs were visually inspected and copied into:

- `chauffeur/static/house_hybrid/living-night.png`
- `chauffeur/static/house_hybrid/living-day.png`

No API fallback or command-line image generation was used. The exact prompt set
is recorded in [house-hybrid-prompts.md](2026-09-23-house-hybrid-prompts.md).
The matching objects align with the same HTML anchors in both variants, but AI
editing is not a guarantee of pixel-identical geometry. A personalized exterior
would still need geometry-controlled views and structure review to preserve
stories, massing and roof directions. This prototype changes no photo pipeline.

## Validation

`tests/test_house_hybrid_live.py` serves isolated fixture data and exercises real
card requests, focus restoration, identical hotspot positions between variants,
automatic sun-boundary switching, phone touch targets, and 3D/Hybrid navigation.
It disables WebGL in hybrid pages and checks that neither Three.js nor house.js
loads. Captures and visit metrics are written to the requested output directory.

The live browser run passed, including both renderer-switch directions and the
Full house link's query cleanup. Desktop day/night and 390×844 touch captures
were visually reviewed. JavaScript syntax and Git whitespace checks passed.
One local Chromium visit reported 726 ms for hybrid and 4,883 ms for low-quality
3D; encoded resource bodies totaled 3,043,727 and 1,832,388 bytes respectively.
These are illustrative visits in one browser session, not statistically paired
cold-load benchmarks or wall-panel performance claims. Outputs are in the local
ignored `scratch/hybrid-review/` directory.

The bounded evaluation should decide whether the improvement in image quality
outweighs losing continuous spatial movement. If it does, the next slice is a
second curated room and the exterior-to-room transition, before investing in a
personalized offline rendering pipeline.
