# Critters in a tabletop habitat

Version 2.499.171 · `feature/living-room-atmosphere`

The hybrid Critters destination now approaches a miniature walnut habitat on
the living-room coffee table. Saved SVG creatures stand in its sandy clearing,
with contact shadows, gentle breathing, and a brass nameplate showing the
selected creature. Adjacent creatures and unhatched eggs make the collection
browsable through the brass arrows, touch swipes, or Left/Right keys. Browsing
does not hatch, spend XP, edit a pet, or start a battle. Reduced motion disables
breathing. The existing owner/level/interaction display settings remain honored.

The image, creatures, nameplate, level progress and controls share one coordinate
plane. Phone controls move inside the visible plaque area. Short landscape
screens hide comparison/chat chrome while inside the habitat. Focus uses
preventScroll so it cannot shift the cropped scene out of alignment.

Customize, Hatch and Battle hand off to the existing full-screen editor and
arena, retaining their member gates and server permissions. These deeper screens
have not been redesigned into the habitat. Optional pet IDs now carry the
selected creature through both doors and their cross-links; older callers keep
their existing first-active-creature default. An explicit empty/new-slot intent
opens a new creature even when that member already owns another. Buying a slot
keeps its confirmation and XP transaction.

Successful edits, hatching, slot purchases, retirement, move purchases and
practice battles invalidate the public board cache. Returning to the habitat
after saving therefore shows the saved creature immediately. Escape closes an
editor/arena before leaving the habitat, and returning to the room closes it.

## Artwork

Built-in ImageGen produced `chauffeur/static/house_hybrid/habitat-day.png` and
`chauffeur/static/house_hybrid/habitat-night.png`. The existing pet photograph
view supplied living-room continuity; the night edit preserves the new geometry.
Original images remain available. Creature identities still use the deterministic
shared SVG renderer, with no per-creature generated substitutes.
The [exact prompts](2026-09-24-house-habitat-prompts.md) are recorded separately.

## Verification

- `test_house_habitat_live.py`: real saved SVGs and shared editor/arena, selected
  second creature, canceled member gate, empty-slot hatching, canceled purchase,
  actual save and cache refresh, touch swipe without opening an editor, keyboard,
  day/night, portrait/landscape, common coordinates, no focus scrolling, errors
  and empty projection. Isolated storage; the one save changes only its fixture.
- `test_house_hybrid_live.py`: all four destinations, sun changes, navigation,
  focus, late images, touch, no-WebGL hybrid, and 3D comparison.
- `test_house_books_live.py`: book and lesson regression.
- Pet suites: 19/19 basic, 18/18 training, 19/19 family-battle tests passed.

Desktop and phone captures were inspected in ignored `scratch/habitat-review/`.
The local preview has sample creatures in isolated storage, alongside the prior
radio and book fixtures. Work remains on the isolated comparison branch.
