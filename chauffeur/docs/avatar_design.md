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

What we author for v0: hips, two leg shapes, two shoe shapes, and trouser /
shorts / skirt variants as flat paths over the legs. That is the entire
full-body art task.

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
