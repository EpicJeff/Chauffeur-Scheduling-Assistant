# Avatars — design brief (v0)

Routines had no sink. Chores earn points and points buy rewards that cost real
money; routines earn a streak and a badge and nothing else. This is the sink:
a full-body character you build, that everyone in the house sees.

The motivation engine is not the wardrobe. It is that Chauffeur already has a
public square — a panel on the wall, boards in the kitchen, a hearth, a map.
A cosmetic nobody sees is not a reward.

## The one rule

> **Identity is free. Flex is earned.**

Body, build, height, skin tone, hair style, hair colour, face, glasses,
mobility aids — every part a person uses to say *this is me* is unlocked from
first login, at zero cost, forever. What routines buy is **flair**: headwear,
jackets, backgrounds, pets (v2), effects, poses.

Non-negotiable, for three reasons:

1. The kid-support arc is the priority arc and `due dates never grades` is
   locked. Gating a child's own likeness behind chore compliance is a grade.
2. The comparison surface is a screen in the kitchen. Siblings will stand in
   front of it. Earned flair reads as *did a thing*; earned identity reads as
   *is behind*.
3. It removes the body-image minefield entirely instead of managing it.

## Second rule: a thing unlocked is never lost

The ledger is append-only. No expiry, no seasons, no revocation, no decay.
Breaking a streak costs you future earning, never anything already on your
shelf.

This was already broken once. `compute_streak` computed `best` over a rolling
90-day window while `status_tiers` documented it as monotonic — a tier badge
demoted itself after 90 quiet days. Fixed in v2.273.8: `best` now scans from
the first recorded check and is persisted as a high-water mark on the member
(`best_routine_streak`). Unlocks hang off persisted values, never off a value
re-derived from history that can be edited or pruned.

---

## Art: buy the rig, don't draw it

A layered paper doll is not a pile of images, it is a **registration
contract** — every hair asset on the same skull at the same anchor, same line
weight, same palette, same implied light. Generative models are good at "a
cool jacket" and bad at "a cool jacket that shares an anchor and stroke weight
with the other thirty-nine". Generating a wardrobe from scratch means
hand-fixing a wardrobe from scratch. That is the failure mode that eats this
idea, and it is where the schedule goes if we get it wrong.

**Decisions:**

- **SVG, not raster.** Colours bound to CSS custom properties: one shirt path
  x twelve palette slots = twelve shirts for free. Resolution-independent, so
  the same asset serves a 24px chip and a 400px hero. Tiny payload, no asset
  pipeline or CDN — matches how the app already inlines images as data-URLs.
- **Body type is a parameter, not three hand-drawn rigs.** Height and build
  sliders drive transforms on one rig; garments are drawn once. This honestly
  caps out near +/-15% before garment paths tear from the silhouette. That
  buys meaningfully different bodies, not radically different silhouettes, and
  it avoids paying 3x on every wardrobe item forever.
- **Start from an existing layered set.** See the source survey below.
  Generation then produces variants *against a fixed rig as a control image*,
  never assets from scratch.
- **Deferred: author in 3D, ship 2D.** Pose a rig, pre-render each garment to
  a flat sprite against a fixed camera. Perfect registration for free, and the
  whole wardrobe re-renders at a new angle with one batch job. Phase 2, once
  the wardrobe is worth scaling.

Not doing runtime 3D. Not because three.js is hard — because rigged meshes are
*more* art pipeline, the wall panel is a modest device drawing several boards
at once, and there is no payoff at 40px.

### Source survey (checked 2026-08-18)

The style we want and the coverage we want do not exist in the same library.
Every flat cartoon avatar set in the Avataaars family is **bust only**; the two
full-body sets are in styles we do not want.

| | Avataaars | Beanheads | Character Creator | Open Peeps | DiceBear |
|---|---|---|---|---|---|
| Who | Pablo Stanley (art), fangpenlin (port) | Robert Broersma | Frédéric Guimont | Pablo Stanley | wrapper library |
| Art licence | **free, personal + commercial** | **MIT** | CC-BY-NC (commercial = Patreon) | CC0 | mixed per style |
| Code licence | **MIT** | MIT | **AGPL** | n/a | MIT |
| Full body | no — bust | no — bust | yes | yes | no |
| Real wardrobe | **yes** | yes | yes | **no** — clothing is drawn into the pose | fixed per style |
| Style | flat bold cartoon | flat bold cartoon | detailed semi-realistic | sketchy hand-drawn | varies |

**Decision: Avataaars is the rig, and we draw the lower body ourselves.**

This is not a compromise, it is the cheapest path, for three reasons:

1. **Flat style is cheap to extend.** Avataaars is flat fills, bold rounded
   shapes, no gradients or line shading. Legs, shoes and trousers in that style
   are a handful of SVG paths each. Extending Character Creator's rendering
   style would be a genuine illustration job; extending this one is not. The
   style that *looks* like less work actually is less work.
2. **It is legible at 40px.** It was designed as an avatar, so the head crop is
   its native form — the chip surfaces come free. Character Creator's detail
   would have turned to mush at `w-8`.
3. **The licences are clean.** Free for personal and commercial use on the art,
   MIT on the port. No NC ambiguity, no AGPL trap, no attribution obligation to
   design around (we will credit anyway).

### The full-body extension is smaller than it looks

Avataaars' canvas is `viewBox="0 0 264 280"`. Every garment sits in a group at
`translate(0, 170)` and its path terminates at y=110 — **absolute y=280, exactly
the bottom edge of the canvas.** The bust does not fade or taper; it ends flush
on a flat horizontal line.

So going full body needs **no modification to any existing asset**. Extend the
viewBox downward and draw a new hips/legs/feet layer that starts at y=280 and
butts against it. A shallow waistband layer overlapping the seam hides any
join. The registration contract is already written and every existing garment
already obeys it.

**Prototyped and confirmed 2026-08-18.** A working figure was built from the
real source paths; the seam is invisible. Nine new paths were enough:

| Path | Layer | Fill |
|---|---|---|
| `ARM_L`, `ARM_R` | skin | skin mask |
| `SLEEVE_L`, `SLEEVE_R` | garment | clothe colour |
| `TORSO_EXT` | garment | clothe colour |
| `LOWER` (waist→hips→legs→ankles) | skin | skin mask |
| `TROUSERS` | garment | clothe colour |
| `SHOE_L`, `SHOE_R` | garment | clothe colour |

### The geometry contract

Anything new registers against these numbers, taken from the source:

- Canvas `0 0 264 280` becomes `0 0 264 600`. Nothing above y=280 changes.
- The shoulder edge is flat: **y=280, x 32..232**, centre x=132.
- That edge splits three ways: `x 32..76` left arm, `x 76..188` torso,
  `x 188..232` right arm.
- Skin: base `#D0C6AC` with a masked colour rect over it (7 tones). New skin
  paths use the same mask, so tone selection needs no new code.
- Garments: base `#E6E6E6` with a masked colour rect (15-colour palette in
  `clothes/Colors.tsx`).
- Shading is `#000000` at `fill-opacity` 0.10–0.16. No strokes, no gradients.

A new wardrobe item is therefore a spec, not a matter of taste: obey those
five rules and register to that edge.

### Two rules the prototype found the hard way

1. **Avataaars' bust has no arms.** The dome is shoulders and upper arms
   merged, because the circle crop hides everything below it. Arms are a
   *required* new asset, not a nice-to-have — the first render made that
   obvious instantly.
2. **Every garment must overhang the limb it covers.** Trouser legs drawn
   narrower than the skin legs leave a sliver of skin down the inner edge.
   Garment silhouettes are cut slightly wider than the body beneath them.

### On generation — a correction

An earlier draft of this brief assumed we would generate wardrobe variants
against a fixed rig. Having built it: for flat vector at this complexity,
**hand-authoring is faster than repairing generated output.** A pair of
trousers is about twelve path commands. Generation keeps a narrower role —
raster patterns for graphic tees, and silhouette exploration — but it does not
produce the paths.

Remaining art cost is small and countable: roughly one path per lower garment
and two per shoe, so a wardrobe of ten trousers and eight shoes is about 26
paths. The one real tax is **sleeves, which want per-garment variants** (blazer
cuff, hoodie, overall straps). v0 ships one generic sleeve and defers the rest.

**The 40px crop is free.** The head render is simply the original
`viewBox="0 0 264 280"` — unmodified Avataaars, which is what it was designed
to be.

### Continuing a garment that isn't one colour

One flat `TORSO_EXT` only works for the plain tops. `BlazerShirt` reaches y=280
as five colour runs, not one:

| x range | source | fill |
|---|---|---|
| 32..90 | `Saco` | `#3A4C5A` hardcoded |
| 90..106 | `Wing` (lapel) | `#2F4351` hardcoded |
| 106..158 | `Shirt` | **user's colour, via mask** |
| 158..174 | `Wing` | `#2F4351` |
| 174..232 | `Saco` | `#3A4C5A` |

`BlazerSweater` is the same shape, `Overall` and `Hoodie` have four runs each.

**The extension is baked, not drawn.** Every garment terminates on flat
horizontal segments — verified across all nine — so the bottom edge is a set of
colour runs, and a vertical extrusion of those runs is *exact* rather than
approximate:

1. Render the garment twice at build time with two different clothe colours.
2. Sample the pixel row at y=279. Runs that change between the two renders are
   mask-driven (user colour); runs that stay are hardcoded.
3. Emit one extrusion rect per run, down to that garment's hem, carrying either
   the hardcoded fill or a reference to the colour mask.

That generates the continuation for all nine tops and any future one, with no
hand-authoring and no possibility of a colour mismatch.

**Structured garments end in a hem.** A blazer stops at the hip in real life,
so it stops here too — extrude ~60 units to a hem at y≈340, cap it with the
standard `#000` / 0.1 shading strip so the edge reads, and let trousers take
over below. Soft tops (tees, hoodies, sweaters) extrude further, to the waist
at y=372. Straight-sided extrusion is exactly right for both; it would only be
wrong for a garment that flares, and v0 has none.

### Slots, not accessories

Avataaars models `accessoriesType` as a **single-choice enum** — seven glasses,
one at a time. Belts, bracelets, necklaces and hairbands are not more items in
that slot; they are worn *simultaneously*, so they are separate slots. This is
a data-model change and it belongs in A1, before any content exists.

The v0 slot set:

| Slot | Source | Notes |
|---|---|---|
| top | inherited (37) | hair, hats — add mohawks and hats here, cheap |
| facial hair | inherited (8) | |
| eyewear | inherited (7) | the existing accessories enum, renamed |
| clothes | inherited (9) | |
| graphic | inherited (11) | valid only on `GraphicShirt` |
| bottoms | **new** | trousers, shorts, skirt |
| shoes | **new** | |
| neck | **new** | necklaces, scarves |
| wrist | **new** | bracelets, watches |
| waist | **new** | belts |
| hair accessory | **new** | bows, headbands |

**Slots are expensive, items are cheap.** A new slot costs a registration
decision and a z-order position, paid once and forever. A new item inside an
existing slot is about a dozen path commands. So the discipline is: fix the
slot set carefully now, then farm items indefinitely without further design.

Registration hazards, each of which is a decision not a discovery:

- **Neck** — nine garments have different necklines (crew, V, scoop, hoodie,
  blazer). Keep necklaces short (choker/short chain) so they land on neck skin
  above every one of them, or they will float on the low-cut tops.
- **Wrist** — sits on the forearm we author, so it is ours to place, but it
  must hide under long sleeves. Sleeve length becomes a property other slots
  read.
- **Waist** — belts ride the bottoms' waistband. One waistline in v0; adding
  high-rise vs low-rise later means belts need a variant per waistline.
- **Hair accessory** — must draw over hair but under hats, and there are 33
  hair styles. Headbands sit on the skull line so they work generically; bows
  take a fixed offset. Do not attempt per-hair placement.

**This materially improves the economy.** One accessory slot means unlocking a
hat ends the game. Eleven independent slots means layering, real combinatorics,
and a long drip of small unlocks — which is exactly what a routine streak needs
to keep paying out.

**Where generation genuinely earns its keep: chest graphics.** A graphic is a
self-contained motif inside a fixed bounding box on `GraphicShirt`, with no
registration contract beyond that box and no style-matching burden. That is the
one asset class where generated output needs no repair — unlike garments, where
hand-authoring won.

### Inventory we inherit free

| Category | Count |
|---|---|
| Tops (hair, hats, turban, hijab, eyepatch) | 37 |
| Accessories (glasses) | 8 |
| Facial hair | 8 |
| Garments | 9 + graphic overlays |
| Eyes / eyebrows / mouths / noses | 13 / 14 / 13 / 2 |

Plus hair, hat, clothing and skin colour tables — every one of which multiplies
the above at zero art cost.

**Extraction note.** The assets are inline SVG inside React `.tsx` components
using `lodash.uniqueId` for `<path>` and `<mask>` ids. Pulling them into plain
SVG is mechanical but real work, and the ids matter: **our compositor must
namespace ids per render**, or two avatars on the same board will collide on a
shared mask id and one will render wrong. That is exactly why the original
generates them at runtime.

**DiceBear keeps one job:** deterministic seed-based generation as the
**day-one default**, so every member has a distinct avatar before anyone opens
the editor and building a character is an upgrade rather than a chore. Its
avataaars style is a remix of the same Pablo Stanley art, so the default and
the built character sit in the same visual family.

**Not chosen:** Character Creator (style too detailed, CC-BY-NC + AGPL, and its
`src/layer/` splits into `female/` and `male/` — two complete trees, which is
both a 2x wardrobe tax and a hard gender fork of the wardrobe that fights
*identity is free*). Open Peeps (CC0 and genuinely full body, but clothing is
drawn into each pose, so there is almost nothing to unlock).
---

## Data model

**On the member record** (partial updates via `update_member`, alongside the
existing `avatar` / `image` fields):

- `avatar_config` — small JSON blob: `{layers: {...}, palette: {...},
  build: 0.0, height: 0.0}`.
- `avatar_kind` — `'photo' | 'character' | 'emoji'`. **The member chooses.** A
  family that already set photos must not have them silently replaced by
  cartoon heads; the existing `avatarInner()` precedence (photo wins) stays
  intact unless someone opts in.
- `best_routine_streak` — already added by the v2.273.8 fix.

**New table `avatar_unlocks_table`** — the ledger, append-only:

```
{member_id, item_key, unlocked_at, source}
source: 'default' | 'routine_cumulative' | 'routine_streak'
      | 'chore_points' | 'grant'
```

Never a derived set. A row exists or the item is locked.

**Backfill on first read:** grant every `free` item, plus any unlockable whose
threshold the member's existing counters already meet. Nobody starts behind
for having been here before the feature.

## Catalog — data, not code

`services/avatar_catalog.py`, one list of dicts, same shape as the tile
catalog in `home_board.py`:

```
{key, layer, label, tier: 'free'|'unlock', track, threshold, palette_slots}
```

Layer z-order: `background, behind_hair, body, legs, torso, arms, head, face,
brows, eyes, mouth, hair, headwear, accessory, effect`.

Adding wardrobe is adding rows. That is the whole point of paying the
registration cost up front — expansion must never be a code change.

## Renderer — one config, two crops

`services/avatar_render.py` → `render_svg(config, crop='head'|'full')`.
Server-side, so kiosk boards, digests and any non-JS surface all work.

**The 40px problem.** Every avatar surface in the app today is a 24–56px
circle (`w-6` through `w-14`). A full-body character with a customisable
jacket is an unreadable smudge at that size. So one config yields two renders:
a head-and-shoulders crop for the circles, a full body for the showcase
surfaces. Designed in from day one, not retrofitted.

The editor needs live preview, so the layer stack is assembled client-side
too. To stop the two drifting, the catalog is served as JSON at
`/api/avatar/catalog` and both sides consume it — only the ~20-line assembly
loop is duplicated, never the data.

---

## Surfaces

**Showcase (full body):** the hearth
(`templates/components/moments_hearth.html`), chores
(`templates/components/chores_lanes.html`), routines
(`templates/components/routine_lanes.html`).

**Chips (head crop):** `avatarInner()` at `templates/app.html:2369` is the one
chokepoint — it becomes avatar-aware there. Nine other templates render
avatars without going through it (`config.html`, `chores.html`,
`routines.html`, `board_tile_body.html`, `kid_digest_lanes.html`,
`family_map_core.html`, `emoji_picker.html`, `chores_lanes.html`,
`routine_lanes.html`). Route them through the shared helper as part of this
work rather than patching each.

## The editor

One component, `templates/components/avatar_editor.html`, mounted two ways —
the kiosk-shares-logic pattern, presentation-only differences:

1. **As a board card.** New tile key `avatar_editor`: a catalog entry in
   `home_board.py` `_TILE_CATALOG`, a `_tile_avatar_editor` builder in
   `_BUILDERS`, and a `<template x-if="t.type === 'avatar_editor'">` branch in
   `board_tile_body.html`. Options: `members` (whose avatar), `require_pin`
   (bool, default true). Anyone can build their own place for it on any board.
2. **As an overlay.** The same component in a fixed-inset modal, opened by an
   edit affordance on any avatar. Follows the `control_center.html` modal
   conventions (`z-[100]`+) — never a browser dialog.

Per the card-conversion paradigm: section toggles default on, members filter,
`interactive` on by default.

## PIN gate

Reuse the existing member-PIN flow (`main.py:5049`) — `verify_member_pin`
plus `_pin_rate_check` / `_pin_rate_record`, so lockout counters and rate
limiting come for free.

**The gate is on the write endpoint, not the UI.** A client-side gate on a
wall panel is theatre; `POST /api/avatar/config` requires a member token or a
fresh PIN verification for that member, and re-checks server-side.

**Decided — a member with no PIN edits freely.** The existing endpoint no-ops
the challenge when `pin_hash` is unset, and the avatar editor matches that
posture exactly rather than inventing a stricter rule for cosmetics than the
app uses for everything else. A family that wants the protection sets a PIN;
that already works. No new setting, no new code path.

## Economy

| Track | Counter | Buys |
|---|---|---|
| Routine volume | cumulative routine completions (new, monotonic) | the bulk of flair |
| Routine consistency | `best_routine_streak` (persisted) | prestige items |
| Chore points | `get_points_earned` (lifetime, monotonic) | a distinct flair line |

Every counter is monotonic and persisted. Grants are checked on routine check
and chore completion; the check returns newly-unlocked items so the UI can
celebrate — reuse `status_celebration.html`.

Parents get a hand path to **grant** items (config page). No revoke path, by
design.

## Full tops supersede extensions (user direction, 2026-08-18)

"Stop trying to patch things together." Every catalog top is now a FULL
garment in `FULL_TOPS` -- collar to hem, sleeves included, one self-contained
multi-part asset drawn over the whole torso -- **keyed by its original name**,
so saved configs, the unlock ledger and the editor carried over untouched.
The source bust garments, the hem bake, the extrusion and the seam covers are
dormant fallback code; nothing in the catalog reaches them.

What this bought, beyond killing every torso seam class at once (garment hem
AA, colour-mask #E6E6E6 leaks, shoulder skin joints -- fabric now covers them
all):
- The blazer takes the member's colour (the source hardcoded its jacket).
- Chest graphics DRAW. They never had: `Graphics.tsx` holds all eleven in one
  file, the extractor skipped it, and `{{SLOT:graphic}}` resolved to an empty
  bucket -- the catalog sold unlockables that rendered nothing. Extracted now;
  the renderer overlays them in the clothes frame (`translate(0,170)`).
- Silhouette rules, learned on light backgrounds: shapes OVERLAP, never abut
  (AA hairlines); leg separation is a DRAWN sh2 crease, never a transparent
  gap (the page showed through the figure); shoe pairs gap 2 units.
- The far-limb tint was tried and removed: on a symmetric front-facing rig it
  reads as "one arm is the wrong colour", not depth.
- Hair accessories anchor ON the hair (bow/clips y44-78): the face frame is
  translate(76,82), so anything at y82-104 lands on the eyebrows.

## Handing the work out: the body template (2026-08-20)

The geometry contract above is a spec an artist has to read and hold in their
head. `tools/avatar_body_template.py` turns it into a picture, and writes two
files:

- `avatar_template.svg` — the rig drawn undressed with every anchor line on it,
  in a viewBox that is **exactly** the renderer's `0 0 264 600`. A path traced
  on it pastes into the wardrobe tables verbatim, which is why the guide labels
  are bare numbers squeezed into the 30 units of margin either side of the arms
  rather than words in a comfortable gutter: widening the canvas to fit prose
  would have cost the one property that makes the file worth having. Layered
  (`rig`, `garment-envelope`, `slot-frames`, `guides`) and headed with an XML
  comment saying to delete all four.
- `avatar_authoring_brief.html` — the handout: the same template annotated, the
  fill vocabulary, the rules below, the slot table, a worked example, and
  reference figures.

Both are **generated from `avatar_render.py`**, never hand-drawn, so the
template cannot drift from the rig. Two things learned pointing it at itself:
the slot `focus` crops are *extents*, so a label on a crop's top edge reads as
an anchor (`waist` printed up at the armpit) — centre it and spell out the
range; and near-coincident anchors have to be clustered into one label block,
because four necklines inside 14 units cannot each carry a 10-unit label.

## Production art: the rules the contact sheet taught (2026-08-18)

`tools/avatar_contact_sheet.py` is the review gate for wardrobe art: every
authored item, worn, across six variant columns (skins, white-on-white,
black-on-black, hoodie, blazer) plus a lane-scale strip. No new asset ships
without a pass through it. The sheet caught, in one afternoon: its own mask-id
collisions, a scarf drawn as a bib, a scarf drawn as horns, and every neck
anchor sitting 30 units below the collar seam (found by debug-colouring the
parts -- when a shape reads wrong, paint its parts red/green/blue and look).

**Multi-part format.** An item is a list of `{'d', 'f', 'o'?}` parts painted in
order; fills are `c1` (slot colour), `sh`/`sh2` (the source's 10%/16% black),
`hi` (white highlight, own opacity), or a `#hex` literal. A watch is a strap
AND a case AND a dial; one path with one fill was the quality ceiling.

**Depth rules** (user direction: flat colour reads as unpolished):
- Shade and highlight in the source's own vocabulary -- low-opacity black and
  white over flat fills. Never a gradient, never a stroke.
- The FAR LIMB (viewer-right arm) is one shade darker, whole silhouette,
  painted over its sleeve -- the single cheapest depth cue in every polished
  flat reference.
- A soft contact shadow under the feet grounds the standing figure.
- Sleeves cast on arms; waistbands, hems and cuffs each carry a shade line;
  soles are their own colour.

**Anchor lines** (learned empirically; the geometry contract's companion):
- collar seam y~225; a scarf's top edge hugs y~196 nearly FLAT (a dipped top
  edge reads as horns around a bare throat); necklaces hang from y~232
- wrists y~392-406; waistband y~364-380; feet stand on y~576

## Tests

- Ledger is append-only; an unlock survives losing routines, deleting checks,
  and a rebuild.
- Backfill grants free items and already-earned unlockables exactly once.
- `avatar_kind` respects an existing photo; no silent replacement.
- Write endpoint rejects a wrong PIN and an absent token (server-side, not
  just hidden UI).
- Reachability: the editor is reachable by hand from the hearth, chores and
  routines surfaces, and the card is placeable from the board editor.
- Renderer produces both crops for every catalog combination without a missing
  layer.

## Slices

- **A0** — extract Avataaars' SVG out of the `.tsx` components into plain
  assets with namespaced ids, extend the viewBox, author the hips/legs/feet
  layer and the first trousers and shoes. *The long pole, and the only slice
  with real art in it.*
- **A1** — catalog + unlock ledger + backfill + counters. No UI.
- **A2** — renderer, both crops, `avatar_kind`, `avatarInner()` and the nine
  bypassing templates.
- **A3** — editor component, overlay mount, PIN gate on the write endpoint.
- **A4** — editor as a placeable board card.
- **A5** — full-body showcase on hearth, chores, routines.
- **A6** — grant-on-earn + unlock celebration.

## Out of scope for v0

Virtual pets (v2 — the pet is a care loop, its own economy and its own
neglect-guilt problem, and it deserves its own brief). Runtime 3D. Animation.
Follow-me. Seasonal or expiring items — see rule two.
