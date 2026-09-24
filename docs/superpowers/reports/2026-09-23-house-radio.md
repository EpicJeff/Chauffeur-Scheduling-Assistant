# A working object: the living-room radio

Version 2.499.167 · `feature/living-room-atmosphere`

The hybrid radio now has its own head-on camera destination and live controls
embedded in the depicted hardware. Its glass displays playback state, track,
artist and failures. The brass plaque selects an existing speaker. The power
button plays/pauses; the volume knob changes volume; the tuning knob selects and
plays saved Music Assistant radio stations. Clicking the glass opens a native
station picker. The other objects retain their existing close-up controls.

Drag a knob vertically. Volume sends one command on release; cancellation sends
nothing. Tuning previews stations and plays on release or a press. Keyboard
arrows adjust either dial; Enter/Space plays the tuning selection. The knobs have
slider semantics, focus rings and at least 44 px touch targets. Day/night artwork
and controls share a fixed coordinate plane. Portrait views keep the complete
radio face visible against an edge-to-edge softened backdrop.

The controller reuses `MusicLogic.players`, `command`, `favorites` and `play`,
including the existing API base, authentication and speaker preference. It does
not start another music widget or browser audio endpoint. Multiple speakers need
an explicit choice; a sole speaker is the default. An unavailable saved speaker
is retained, never silently replaced. Entry does not start playback. Reads poll
every five seconds only while the radio is open and the document visible. Late
responses cannot restore an exited view or overwrite a new speaker selection.
The shared command helper now reports HTTP failure instead of unconditional
success, so the radio can show a failed command honestly.

This is a one-object prototype, not a new production default. The 3D comparison
is unchanged. It controls existing Music Assistant/Home Assistant players; local
browser playback, music search and queue editing remain in the existing music
surfaces. A front-on generated perspective can drift from the overview's radio
design. This tests whether a functioning physical interface earns that tradeoff.

## Assets

Built-in ImageGen generated the day backplate and edited it for matching night
lighting. Exact prompts are in [house-radio-prompts.md](2026-09-23-house-radio-prompts.md).
Assets: `chauffeur/static/house_hybrid/radio-face-day.png` and
`chauffeur/static/house_hybrid/radio-face-night.png`. The original perspective
images remain available. Images load on destination intent/visit, not on initial
overview load. No external image-generation API or post-generation raster editing.

## Verification

Passed: the radio browser test, full hybrid browser regression, 38/38 music-card
scenarios and 16/16 music endpoint scenarios. The endpoint test initially picked
up the workstation's `HA_BASE_URL`, overriding its fixture; rerunning with that
one variable empty in the test child process passed. No production environment
was changed. Day/night desktop and phone captures were visually reviewed in
`scratch/radio-review/`; hybrid regression captures are in
`scratch/radio-hybrid-regression/` (both ignored).

`tests/test_house_radio_live.py` runs the real template, shared music logic and
controller with intercepted Music Assistant responses. It checks explicit
speaker choice, no entry autoplay, delayed favorites, play/pause, drag/keyboard
volume, cancellation, tuning, HTTP failures, stale commands, external player
changes, lost speakers, polling shutdown, mobile control geometry and day/night
captures. `tests/test_house_hybrid_live.py` covers the other destinations,
navigation, reduced motion, sun changes, mobile, disabled WebGL and 3D switching.

The local preview uses a clearly named demo speaker with simulated state, stored
only in the ignored preview script. Production endpoints contain no demo behavior.
Audible playback on physical household speakers has not been tested here.
