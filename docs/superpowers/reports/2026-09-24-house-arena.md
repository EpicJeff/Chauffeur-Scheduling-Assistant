# Battles in the habitat; full-screen books and critters

Version 2.499.173 · `feature/living-room-atmosphere`

Battle opens sparring cards in a wooden drawer while the selected critter stands
in the habitat. Practice and accepted family battles play on the sand; the brass
plate carries both health bars, and the drawer becomes a paper battle log and
then the result. Again, Train and Done connect the arena to the existing habitat
and customization workbench. Day/night and reduced motion remain supported.

The implementation reuses the shared battle controller, endpoints, replay,
opponent catalog, XP caps and family invitation/acceptance rules. Normal callers
outside the hybrid habitat retain the existing arena. Watching history makes no
battle POST and does not award XP. Family invitations still use the first active
critter under the existing rules; the picker now states that when a different
critter is selected. Acceptance returns the actual stored combatants' artwork,
and Train opens the creature that fought.

All animation timers are canceled on Skip, Leave, reopen and completion. Response
revision guards prevent canceled requests from starting hidden fights or
overwriting another open. SVG definitions receive unique stage IDs so a hidden
copy in the habitat cannot erase its fighter. Reward refresh happens when the
server resolves a battle, including if the viewer leaves before the response;
family acceptance also invalidates the board projection. The server remains the
owner of battle resolution and rewards.

Books and the habitat now cover the viewport with one photograph, preserving
their registered control plane and cropping the edges as necessary. There is no
inset over a blurred enlargement. Phones retain the book's left/right page
camera; the workbench and arena reframe the habitat to leave room for controls.
Clipped scene containers cannot scroll themselves when focus or orientation
changes, and unused 3D tooltips cannot intercept hybrid controls.

No new image generation, assets, dependencies, or rendering services were needed.
The existing photographs and deterministic SVG critters supply the artwork.

## Validation

- `test_house_arena_live.py`: real selected-pet practice battle, family acceptance
  and actual combatant art, mirrored family view, health/result, replay without
  new POST or XP, timer cleanup, delayed-response cancellation, training handoff,
  full-screen registration, desktop/phone/landscape and ordinary-arena fallback.
- `test_house_habitat_live.py`: browsing, permission cancellation, hatch/buy,
  save refresh, errors, day/night, touch and keyboard.
- `test_house_books_live.py`: page data, full-screen image bounds, registration,
  page turns, day/night, permissions, in-book lesson controls and teardown.
- `test_house_workbench_live.py`: live drafts, Save/Cancel, training and purchases,
  full-screen workbench geometry and responsive layout.
- `test_house_hybrid_live.py`: destination navigation, sun updates, late images,
  touch, no-WebGL and the 3D comparison path.
- `test_pets_pvp.py`: 19/19 consent, level matching, rewards and cap checks.

Screenshots inspected in ignored `scratch/arena-review/`, `scratch/book-review/`
and `scratch/workbench-review/`. The local preview uses isolated fixture data.
Work remains in the fork/worktree; the main repository checkout is untouched.
