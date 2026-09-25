# Photographic kitchen prototype

The kitchen is available from the exterior room marker and Kitchen shortcuts,
or directly at `house?compare=exterior&scene=kitchen`. It uses the same home
materials as the accepted living room: oak, cream, brass and black windows.
The fireplace was accepted as the baseline before starting this room.

Five destinations approach the household objects that hold their content:

- Recipe stand: the existing weekly meal card, fetched only on entry.
- Refrigerator: actual family moment media mounted directly as magnetic prints, in both overview and close-up. Tapping opens the shared viewer; manually opened photos stay open until dismissed and support Escape/focus restoration.
- Pantry: its own shelves and wall-mounted shopping board, retaining check/undo.
- Wall calendar: a paper month grid, using the shared FamilyCalendar event pipeline and details dialog, with previous/next/current month controls.
- Window: the existing house-state weather condition selects clear, cloudy, rain, snow or fog outdoor photography. Forecast data appears separately on a brass wall display. Unknown conditions show an unavailable message and neutral outdoors.

Navigation supports tap, exterior quick preview/hold-to-visit, keyboard, browser
back/forward, direct room entry and returning outside. Paper and controls use
one coordinate plane. Every lean-in photograph covers the entire viewport,
without an inset image or blurred duplicate behind it. Narrow screens can pan
across cropped objects; their live content also scrolls as needed. The existing day/night/automatic
sun selection applies to the overview and all close-ups. Missing artwork leaves
a working back button; missing data gets an explicit empty/unavailable message.

## Artwork

Twenty selected images generated with the built-in ImageGen tool are installed in
`chauffeur/static/house_hybrid/`: `kitchen-day.png`, `kitchen-night.png`, and
day/night pairs for `kitchen-meals`, `kitchen-board`, `kitchen-moments`,
`kitchen-pantry` and `kitchen-weather`, plus four day/night `kitchen-outside-*` conditions.
SVG masks confine daytime weather variants and overview layers to the window panes.
Night close-ups use complete nighttime weather photographs without a brightness
filter or pane mask, keeping the foreground clock and plants warmly lit. Weather
assets follow the room lighting selection; mismatched layers stay hidden while loading.
The fridge artwork contains
no generated moment placeholders; an empty feed leaves the door empty.
The [complete prompts](2026-09-24-house-kitchen-prompts.md) record the generation.
The kitchen is illustrative, not a reconstruction of the user's actual interior.

## Steam

`chauffeur/tools/render_kitchen_steam.py` builds a Mantaflow gas simulation from
a thin ring around a modeled saucepan lid. An animated Clouds texture varies
emission. The ring is hidden in the render; only pale vapour contributes pixels.
Resolution 48, 144 cache frames, time scale 0.65, density 0.22, temperature 0.8,
dissolve speed 8; Cycles/OptiX 32 samples with transparent film.

Frames 25–144 feed `encode_fire_loop.py --pattern 'steam_*.png'`: a one-second
eased, premultiplied-alpha overlap gives a four-second VP9 alpha loop at 24 fps.
The 160x240 asset is 222,098 bytes, projected at (665,289), 64x96 in the 1536x1024
overview. All 120 render frames have zero alpha on their outer borders.
This is subtle ambient artwork, not a report that a real stove is on.

Fire and steam now use one native-video lifecycle controller. Each layer plays
only in its own room overview; motion toggles, reduced motion, hidden tabs,
navigation and failed media stop it. The still photographs are never warped.
Blender sources/cache remain in ignored `scratch/kitchen-steam/`.
No purchases, appliance commands, new server endpoint or runtime 3D dependency.
The outdoor conditions currently use still photographic variants, not animated
rain or snow. The weather signal is live; photographs are illustrative.

## Verification

- `test_house_kitchen_live.py`: exterior preview/entry, all five destinations,
  day/night, matching paper/control coordinates, phone/short landscape/wide
  desktop, history, direct entry, reduced motion, steam toggle/loop and fire
  stopping. Also verifies six real feed media URLs, photo viewer keyboard/focus,
  month navigation and event details, all weather categories and unavailable
  weather. Night weather checks compare rendered clock and foliage exposure with
  each source image, and verify the filter and mask are absent. Screenshots:
  `scratch/kitchen-night-weather/`. Shopping check/undo touches only an isolated fixture.
- `test_house_exterior_live.py`: existing room/garage/vehicle interactions.
- `test_house_flames_live.py`: accepted fire playback, alpha and lifecycle.
- Correction screenshots and walkthrough: `scratch/kitchen-corrections/`.
  Full-screen correction screenshots: `scratch/kitchen-fullscreen/`. The browser
  gate verifies all five lean-ins cover every edge without stretching, in day
  and night and across phone, short landscape, desktop and ultrawide sizes.
  The walkthrough uses fixture exterior photos and a fixture calendar event;
  installed code reads actual household moments and events.

Visual acceptance of the new kitchen and steam remains with the user.
