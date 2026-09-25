# Fixed garage base and instrument lean-in — 2.499.180

The approved `chauffeur/static/house_hybrid/garage-empty.png` is unchanged.
Gemini edits that image to add the gray EV9 to the left bay. The right side is
composited from the original base, so its cabinets, charger and materials cannot
drift when vehicle presence changes. The generated image is normalized onto the
base image's coordinate plane and feathered at the occupied region boundary.

The first two paid requests incorrectly generated a new empty room and its
occupied version. Those outputs were rejected after user feedback and remain
only in ignored scratch. The final generator requires `--base` and makes exactly
one paid call to edit that approved image; it cannot generate a replacement room
implicitly. A new output directory is required and failures are not retried.
Vehicle year/make/model, color and bay are explicit inputs, not hardcoded to EV9.

`chauffeur/tools/generate_garage_bay.py` is the server-runnable generation tool.
It uses the existing paid Gemini HTTP client, `gemini-3.1-flash-image`, and saves
validated image output, prompt, usage, model version and base SHA-256. This is a
tested generation path, not yet a household-facing setup/job-management UI.

Tapping the car now leans into a photographic instrument cluster. Battery (or
fuel), range with the actual sensor unit, presence and low-energy warning are
HTML drawn within the screen, rather than a floating card. Vehicle details
opens the existing card for remaining functionality. Garage/Escape returns to
the bay. Mobile uses the same projected image/screen coordinates. No telemetry
is invented: missing values display dashes and an unavailable notice.

Artwork-to-vehicle association is explicit in this prototype via `garage_car`
containing a car ID. A matching model name no longer silently associates a car.
Without that binding, the stock EV9 is illustrative and has no personal readings.
The Parked/Away preview switch changes artwork only, never real presence or the
instrument readings. A production setup should persist this ID association with
the server-generated asset manifest rather than use the preview query parameter.

Accepted Gemini assets:
- `chauffeur/static/house_hybrid/garage-left-ev9-gemini.jpg`
- `chauffeur/static/house_hybrid/garage-ev9-cluster.jpg`

Actual prompts and provider metadata are in `assets/garage-gemini-2026-09-24/`.
Four paid image calls total this turn: rejected new room and occupied room, the
instrument view, and the corrected edit of the fixed garage. No built-in image
generation was used this turn. The cluster is representative, not a verified
factory-exact EV9 dashboard, and the blurred background remains illustrative.

Validation:
- Two offline paid-generation guard tests: input/base propagation, one call,
  credential redaction, no retries and no accidental repeated output runs.
- All ten car telemetry scenarios, including preservation of range units.
- Garage live test: assigned/unassigned vehicles, live reading updates, missing
  data, warning state, bay presence/overrides, cards, navigation/history/reload,
  keyboard/hold, desktop/mobile and no vehicle API writes.
- Existing exterior/living marker regression.
- Visual screenshots reviewed in ignored `scratch/garage-two-bay-review/`.

All changes are confined to the existing worktree and experiment branch.
