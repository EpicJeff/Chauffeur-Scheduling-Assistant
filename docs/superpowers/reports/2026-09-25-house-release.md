# Photographic House add-on release ? 2.499.181

## Release and controls

The `feature/living-room-atmosphere` branch is merged into `main`. The add-on
version in `chauffeur/config.yaml` is 2.499.181. This publishes the existing
photographic house implementation and its packaged assets; it does not add a
per-house Gemini asset-generation pipeline.

After updating the Home Assistant add-on, open **Config ? Boards** and enable
**Use the new House experience**. Enable **Use The House as Home** to make it the
landing page. These household settings are independent and both default off.
Turning the new experience off restores the original 3D House on the next visit
or refresh. Editors and explicit `render=3d` URLs retain the original renderer.

The normal House starts outside and opens the living room, kitchen, mudroom,
study and garage. It omits the comparison toolbar. Existing household data feeds
the objects; the local preview's synthetic data and sample album-art downloads
are not part of application startup. Blender-rendered steam/fire and generated
scene images are packaged static assets and do not require Blender or Gemini at
runtime.

## Release verification

Validation uses isolated test data and removes inherited Home Assistant
credentials from test subprocesses. Results below describe local tests, not an
update of the running Home Assistant installation.

The release checks caught and corrected an unclassified neighborhood read route,
a living-room camera that hid the Study doorway, and marker timers that could
expire during a slow room transition. Existing test selectors were adjusted for
the nested calendar navigation, pet identity and manual photograph controls.
The screensaver test now waits for the actual overlay with a bounded timeout,
instead of assuming rendering finishes within 600 ms.

The 293-file sweep completed; after fixes and isolated reruns, **288/293 test files passed**. Focused reruns passed after the release fixes:
House/Home routing and both persisted toggles, the hybrid room browser flows,
original 3D household navigation, living-room high/low day/night visuals,
authentication, settings registration, screensaver, presence, album covers and
playback, radio controls, Study surfaces, vehicle artwork, and the workbench.
The changed Python files parse using Python 3.11 grammar, matching the add-on
image; local runtime tests used Python 3.14 on Windows with Chromium.

The broad suite is not fully green. All five remaining failures were reproduced on a clean
checkout of `origin/main` at `7efff2bc` (2.499.165):

- `test_house_window_groups.py`: a clipping fixture expects a "reduced" note.
- `test_house_facade_live.py`: the fixed exterior mesh-count expectation is
  stale (expected 1880; previous release 2299; this release 2398).

- `test_house_map_live.py`: visible neighborhood lots differ from the fixture's
  total during orbit; the same assertion fails on the previous release.
- `test_house_shell_live.py`: the mudroom roof fixture expects zero masking but
  gets `0.04487198504822554` on both releases.
- `test_house_variants_live.py`: the performance fixture gets `None` for
  `buildMs`, producing the same `TypeError` on both releases.

These assertions were not weakened to manufacture a passing release run.
The initially timing-sensitive navigation and weather tests passed when rerun
in isolation. The full original 3D navigation sweep passed in 443.6 seconds;
the living-room visual review passed all four high/low day/night captures.

Detailed local logs and the consolidated result list are in the ignored
`scratch/release-2.499.181/` directory. Installing or updating the deployed
Home Assistant add-on remains a separate action from publishing this merge.
