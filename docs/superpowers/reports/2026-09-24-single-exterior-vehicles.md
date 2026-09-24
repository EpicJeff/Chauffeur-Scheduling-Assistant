# Single exterior and vehicle artwork — 2.499.178

The eight-view consistency experiment used one frozen appearance anchor with
the target model camera for each view. Eight requests plus two camera corrections
completed with Nano Banana 2; there were no automatic retries. The prompt/result
records are in `assets/house-orbit-2026-09-24/coherent-*`. Garage and detail drift
remained, so the user selected one front three-quarter exterior instead of orbit
navigation. The eight outputs remain as experiment assets; runtime loads only
`chauffeur/static/house_hybrid/exterior-scene.jpg`.

The exterior now uses the existing marker controller: tap to expand, tap a
feature for its regular quick-view card, hold to visit its hybrid room object,
and tap the expanded room marker to enter. Keyboard Shift+Enter, drag
cancellation, focus trapping, back/history and reduced motion are retained.

Cars and the bus follow the existing shared fleet/curb state. Away cars disappear;
car and bus taps open the Cars and Next Up cards. Three driveway positions are
available, with the full count in the shortcut. The preview bus is explicitly
labeled Demo. Its tires sit on the road; bottom-aligned cover framing keeps the
street visible on wide displays. Mobile still uses full-screen cover, which can
crop the traffic out; accessible shortcuts remain available.

Whole-vehicle color multiplication was removed. Each car can instead retain an
optional `exterior_image`, uploaded in Config → People → Cars → House driveway
artwork. PNG/WebP uploads preserve transparency and aspect ratio, downscaled to
at most 512 pixels. The existing small photo remains unchanged. Missing/broken
artwork uses neutral stock body artwork. No identity is inferred from the color
picker or generic body type.

The user supplied white 2022 Mercedes GLS, gray 2026 Kia E9 (interpreted as EV9),
and blue 2021 Nissan Murano. Separate transparent prototype cutouts were generated
with the built-in imagegen tool and saved under
`chauffeur/static/house_hybrid/vehicles/`. Exact prompts and references are in
`2026-09-24-house-vehicle-prompts.json`. Vehicle trims were not supplied, so these
are representative model/year/color assets rather than exact factory builds.
This does not implement server-side paid Gemini vehicle generation or automatic
photo extraction. These static assets make no generation calls during use.

The local preview's isolated temporary fleet uses these three assets. The main
checkout and its data were not changed. All work remains on
`feature/living-room-atmosphere` in the existing worktree.

Validation:
- `test_house_exterior_live.py`: single exterior, all three vehicle assets,
  live presence/bus updates, all four marker cards, second tap, long press,
  drag cancellation, keyboard, history, mobile, reduced/full motion; no WebGL.
- `test_house_vehicle_artwork_live.py`: real file input, transparent image
  resizing, API save, re-edit, shared fleet state round trip. Config test teardown
  can log an interrupted background request after assertions pass.
- `test_house_orbit_generation.py`: bounded request/credential guards, two tests.
- Earlier in this change: existing hybrid, 3D marker and books live regressions
  passed before the traffic artwork changes.
- Visual review at 1280×720 and 1400×1000 verified road placement and composition.

Review screenshots are in ignored `scratch/exterior-personalized-review/`.
