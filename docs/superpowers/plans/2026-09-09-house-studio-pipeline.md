# The Home — Studio Pipeline Brief (start here in a fresh session)

**Status:** greenlit by the user 2026-09-09, NOT started. The architect pass
(v2.466.0–.3) is shipped; this brief replaces its remaining tasks (cars v2,
lighting) with a studio-run quality effort.

## Why this exists

The user's verdict on the house so far: "I gave you an image for the kitchen
and asked if you could match it and you said 70% … This doesn't feel like it
is matching that at all." Correct. The diagnosis, agreed with the user:

1. **Iteration depth** — every prop got 1–2 screenshot cycles; the reference
   bar needs 10–15 per element.
2. **No style vocabulary** — each prop invents its own proportions, bevels
   and colors, so built-ins came out as featureless blocks.
3. **No separate judge** — the builder graded its own screenshots. A reviewer
   looking only at pictures catches "the armchair faces the wall" instantly.

The fix is process, not a new renderer: focused agents with their own context
budgets, a written style bible, and maker/judge separation.

**Honest ceiling (told to the user, unchanged):** the offline-rendered
reference (path-traced GI, light pooling, glossy reflections) is not
reachable in a forward renderer. Reachable: its GEOMETRY DENSITY, its
material richness, faked light pools, contact-shadow discipline, tuned
exposure — a polished indie-game look on the high tier, today's cost on Pi
tiers.

## The one tool everyone uses

`python tools/house_probe.py --views all --quality high --out <dir>`
(also `--views exterior,living`, `lean_board`, `--clip x,y,w,h`,
`--quality medium|low`). Seeds a standard fixture set (two children, driver,
event today, three shopping items, three cars). Prints console errors and
exits 1 on any — a silent 2D fallback means buildRoom threw (that failure is
now logged, v2.466.3).

## Roles

- **Art director** (runs FIRST, then reviews every pass): studies the user's
  reference images (in this conversation's history: the low-poly car pack and
  the isometric kitchen render) plus current probe shots, and writes
  `docs/house_style_bible.md` — palette with hex values, bevel radii by prop
  class, proportion rules, a prop vocabulary (what a built-in IS: face frame,
  reveal, shelf depth, book density…), density targets per room, and a
  per-room punch list. After each builder pass it reviews screenshots ONLY
  and returns a pass/fail plus a specific punch list. Nothing is "done"
  before it passes.
- **Set builders** (one room per pass, sequential — one shared scene file,
  parallel editors would merge-fight): living → kitchen → mudroom+pantry →
  garage → exterior/yard. Each runs edit → `node -e` parse check → probe →
  LOOK at the shot → iterate, 10+ rounds, against the bible.
- **Vehicle artist**: `buildCar` rewrite to the car-pack standard —
  side-profile `T.Shape` + ExtrudeGeometry bodies, inset glass, bumpers,
  grille, wheel arches, lights; all seven body types verified by screenshot;
  the school bus too.
- **Lighting artist** (LAST): sun/fill placement, exposure, painted light
  pools, per-tier material polish.
- **Main thread (me)**: briefs, law enforcement, commits, and a screenshot
  checkpoint to the user after every room.

## Laws every agent inherits

- Render-on-demand (no perpetual RAF); quality tiers high/medium/low/2d;
  `setPixelRatio(1)`; the 2D fallback stays first-class.
- Zone keys are frozen: door, radio, pet, board, calendar, counter, fridge,
  window, garage, curb. Moving furniture never renames a zone.
- `/kitchen` and `static/kitchen.js` are FROZEN until H4 — all work lands in
  `static/house.js`.
- Exterior/new-room fidelity must equal the kitchen's (standing user ruling).
- Every task: full sweep (`python chauffeur/tools/test.py`, never piped),
  bump `config.yaml`, commit `(vX.Y.Z)`, push.
- Arc opens at **v2.467.0**.

## Where the house stands (v2.466.3)

Open-concept great room on one plank floor (kitchen flows forward into a
full-width living room: hearth, wall TV, built-ins, sofa/armchair/rug,
radio shelf, critter laptop coffee table, plant); mudroom slotted between
garage and great room with a real doorway cut through the kitchen wall,
bench/hooks/coat/honest backpacks and the leave-door zone; pantry is a real
closet behind a paneled door that steps aside on lean-in; garage moved west
with a proper gable; main roof has both slopes and a fascia; parametric cars
+ curb bus (cars are the WEAK point — blocks, next to rebuild).

Known punch-list items already called out by the user and NOT yet fixed:
armchair orientation, built-ins reading as blocks, furniture crowded into one
corner of the living room, overall density and material richness below the
reference bar.

## First moves in the new session

1. Read this brief and `docs/superpowers/specs/2026-09-08-house-design.md`.
2. Run `python tools/house_probe.py --views all --out <scratch>` and LOOK at
   all five shots.
3. Dispatch the art director with the reference images the user provides
   (ask for them — they were pasted in the previous session) to write
   `docs/house_style_bible.md`; commit it.
4. Then room passes in order, checkpointing screenshots to the user after
   each.
