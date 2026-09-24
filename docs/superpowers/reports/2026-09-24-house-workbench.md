# Customization in the habitat

Version 2.499.172 · `feature/living-room-atmosphere`

Customize and Hatch now open a wooden drawer below the habitat. The actual
critter remains on the sand and changes as parts and colors are selected. Its
name is edited on the brass plate. Parts are sample tiles, colors are paint
pots, and the existing element, training and move controls occupy the felt-lined
drawer. Undo, redo, shuffle, retirement, Battle, Cancel and Save remain available.

This uses the single shared pet editor and its existing markup, SVG composition,
member gate, endpoints and XP confirmation. The new stylesheet loads only for
the hybrid comparison. Ordinary editor callers retain the full-screen layout.
No new image assets, generated pet identities or rendering dependencies were
introduced. The existing day/night habitat photographs remain the backdrop.

Appearance drafts are not persisted until Save; Cancel/Escape discard them.
Training and moves retain their existing explicit save actions. Learning moves
is an immediate, separately confirmed XP purchase. Battle still enters the
shared arena; bringing combat into the habitat is a subsequent slice.

The photograph, live preview and nameplate share registered coordinates.
Portrait phones use a narrower drawer with wrapped category tabs; short
landscape displays place it alongside the habitat. Reduced motion suppresses
the drawer animation. The habitat behind the editor is inert, focus stays in
the drawer/nameplate, and Escape restores habitat focus. Canceled asynchronous
opens cannot overwrite a later draft. Shared refresh now preserves the selected
pet ID after training or learning rather than reverting to the owner's first pet.

## Verification

- `test_house_workbench_live.py`: real isolated storage and shared controller;
  registered scene geometry, parts/colors/name preview, cancel and reopen,
  selected-pet training, canceled and confirmed XP purchase, rejected save and
  successful retry, delayed-open cancellation, ordinary editor fallback,
  day/night and desktop/portrait/landscape controls, keyboard focus and Escape.
- `test_house_habitat_live.py`: selected pet, member-gate cancellation, hatch and
  buy intent, actual save/board refresh, touch/keyboard browsing, day/night,
  responsive geometry and empty/error/read-only projections.
- `test_house_hybrid_live.py`: all destinations, sun changes, transitions,
  focus, late image handling, touch, no-WebGL and the 3D comparison path.

Screenshots inspected in ignored `scratch/workbench-review/`. The preview uses
isolated fixtures; implementation and version changes remain in the worktree.
