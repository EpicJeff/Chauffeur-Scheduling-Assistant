# Pets — design brief (v0)

`avatar_design.md` deferred pets to v2 and said why: *"the pet is a care loop,
its own economy and its own neglect-guilt problem, and it deserves its own
brief."* This is that brief, and the first thing it does is throw out the care
loop.

A pet here is not a tamagotchi. It is a **sidekick with stats** — a rudimentary
Pokémon. You earn it by doing chores, you build it by doing chores and
routines, and you fight it against NPCs and against your siblings. That framing
is strictly better than a care loop for this house, for one reason: **you cannot
fail a battler by ignoring it.** No hunger bar, no guilt, no decay. Rule two of
the avatar brief — *a thing unlocked is never lost* — holds for free instead of
being fought for.

---

## The three rules

> **1. Identity is free. Power is earned. Neither one wins a fight.**

Hatching a pet, naming it, and dressing it — body, horns, eyes, mouth, pattern,
colours — is free from the first pet, forever. This is the avatar brief's first
rule and it applies unchanged: the comparison surface is a screen in the
kitchen, and a critter that looks sad because its owner did fewer chores is a
grade.

What the grind buys is **breadth** — more species, more moves, a second pet
slot, higher NPC tiers. What it must never buy is an unbeatable sibling. See
*Level-matching*, which is the load-bearing part of this document.

> **2. XP is not points. The membrane is one-way.**

Points redeem for real money — reward requests, pooled family goals. Pet XP is
a separate currency in a separate ledger. A verified chore mints **both**, so a
kid never chooses between levelling their critter and the family movie-night
pool. Battles mint XP only. Nothing converts XP back into points, ever.

Without this rule, grinding NPCs prints money out of Mum's wallet, and pledging
to a shared goal means losing to your brother. Both are fatal. This rule is not
negotiable and every endpoint that touches `pet_xp_ledger` must be readable as
obeying it.

> **3. A pet is never lost, sick, hungry, or taken away.**

Append-only, like the avatar ledger. No decay, no seasons, no revocation. A pet
cannot be used as a punishment lever by anyone, including a parent — the
Settings surface deliberately exposes no "remove pet" control, only the daily
battle cap and whether PvP is on at all.

---

## Art: DiceBear Critters — verified viable

**Verdict: use it. Bake it. Don't build our own.** Measured 2026-08-18 against
`api.dicebear.com/10.x/critters`.

### Licence

**CC0 1.0 — public domain, author DiceBear, no attribution required.** The
licence is asserted in-band: every generated SVG carries an RDF `<metadata>`
block naming `creativecommons.org/publicdomain/zero/1.0/`. This is the cleanest
licence in the whole avatar survey — cleaner than Avataaars, which we already
shipped on. We may harvest, modify, redistribute and commercialise without
condition. We will credit anyway.

### Coverage — measured over 300 seeds

| Part | Variants | Names |
|---|---|---|
| `body` | **14** | bell, blob, block, chimney, dome, lean, peak, round, squat, steps, tilt, tower, wedge, wedgeInv |
| `top` | **15** | antenna, antennae, bobble, crown, earsDroop, earsPointy, earsRound, fin, horns, hornsIn, hornsSmall, nub, spike, spikes, sprout |
| `eyes` | **19** | angry, bigPupils, close, closedLine, dots, four, happy, inward, mono, monoSleepy, round, sideeye, sleepy, squint, threeRow, trio, uneven, wide, wink |
| `mouth` | **19** | blep, catMouth, dot, frown, grin, laugh, line, ooh, open, sad, slant, smile, smirk, teeth, tinySmile, tongue, tooth, wavy, zigzag |
| `pattern` | **10** | bar, bars, belly, chevron, dotRow, dots, ring, speckles, spot, stripes |
| `cheeks` | **3** | blush, blushBig, freckles |
| base colour | **12** | Tailwind 300-level pastels (`#fcd34d`, `#7dd3fc`, `#c4b5fd`, …) |

`body × top` = **210 distinct silhouettes**. That is the species axis, and 210
is far past what this family will exhaust. The remaining axes multiply to ~9
million looks. Payload is ~2.9 KB per critter.

### The registration contract is better than Avataaars'

Avataaars needed a hand-authored lower body and a hem table because its garments
all terminated on one seam. Critters needs neither. Measured across all 14
bodies:

```
cheeks  @ (28, 53)     eyes @ (27, 36)     mouth @ (36, 60)     pattern @ (34, 75)
```

**Identical for every body.** The only per-body value is the top's anchor —
`x=26` always, `y` ranging 2 → 10 — a 14-entry table:

```
bell 2.5  blob 2  block 5.5  chimney 2  dome 2.5  lean 2  peak 4
round 8   squat 10  steps 3.5  tilt 2  tower 2  wedge 2  wedgeInv 5.5
```

Every part is a self-contained `<g id="part-variant-hash">` in `<defs>`,
composed by `<use transform="translate(x y)">`. Shading is done as white/slate
overlays at `opacity .1–.16` over a **single base fill** per group — verified:
every body group carries exactly one non-ink, non-white fill. So recolouring is
one string swap, and the implied light survives it. That is the same
`palette_slots` model `avatar_catalog` already uses.

### Four defects, all cheap

1. **Critters is a preview style.** Not on npm — there is no `@dicebear/critters`
   and `@dicebear/collection@9.4.2` does not list it; `schema.json` 400s; and
   **explicit option params are ignored** (`?body=blob` returned `body-tilt`,
   then `body-dome`). The style is seed-driven only.
   *Fix:* harvest by seed. Sample until every variant is seen (300 seeds covered
   all 80), lift each `<g>` out of `<defs>` once, write `pets/pieces.json` in the
   same shape as `static/avatar/pieces.json`. A build-time script, run once,
   pinned thereafter. CC0 makes this unambiguously ours; the upstream style
   changing later cannot affect us. **We were going to bake it regardless** —
   the app renders avatars server-side in Python precisely because kiosk boards
   and digests have no JS runtime, and a Home Assistant add-on must not need
   `api.dicebear.com` to draw a pet.
2. **`clipPath` ids are not hashed.** They are `dbcrb-<body>` — stable and
   global. Two critters with the same body on one page collide, and the second
   one's clip silently resolves to the first's. The battle overlay draws **two
   pets side by side**, so this would have shipped broken.
   *Fix:* namespace every id at bake time, exactly as the Avataaars extraction
   already does.
3. **No animations ship.** `animation=` accepts anything and always yields
   `animation-none`. But the markup keeps the hooks — `class="dbcr-c"` on the
   critter, `dbcr-t` on the top, `dbcr-eb` on the eyes. Idle bob and blink are a
   dozen lines of our own CSS on classes that are already there.
4. **No limbs and no poses.** Critters are blobs. There is no punch frame and
   never will be.
   *Fix, and it is a feature:* battle motion is **transform-based** — lunge,
   squash, recoil, shake, tint-flash, particle burst. Pure CSS on a `<g>`,
   readable at any size, no sprite sheets, and it costs nothing per new species.
   Frame-based animation was never affordable here anyway.

### Alternatives, rejected

- **Build our own critters.** The avatar brief already established the failure
  mode: generative models are good at "a cool jacket" and bad at "a cool jacket
  that shares an anchor and stroke weight with the other thirty-nine". Here we
  would be hand-authoring 210 silhouettes plus 51 face parts to land where CC0
  already puts us for free. Only reason to revisit: dedicated evolution
  silhouettes (see below), and even then we extend rather than replace.
- **Other DiceBear styles.** `bottts` is robots (wrong register, and less
  creature-collectable), `big-ears` / `toon-head` / `personas` are humanoid —
  they read as a second avatar, not a sidekick, which kills the whole
  avatar-plus-pet composition. `thumbs`, `shapes`, `icons`, `fun-emoji` are not
  creatures.
- **Commissioned art.** Not until the loop is proven fun.

### Evolution without new art

There is no evolved-form artwork and we are not drawing any. Evolution is
**scale + top upgrade**: `nub → hornsSmall → horns`, `antenna → antennae`,
`spike → spikes`, with a ~12% size step. It reads as growth, costs nothing, and
stays inside the registration contract.

### The background

`static/pet_battle_background.jpg` is 2752×1536 and **3.6 MB**. That is too
heavy for a wall panel drawing a board plus two pets, and far too heavy for a
kid's phone on cellular. Downscale to ~1600×896 WebP (target < 200 KB) at P0,
keep the original out of `static/`, and commit the derived asset — it is
currently untracked.

---

## The economy

Two ledgers, one mint, no bridge.

```
verified chore  ──▶ points_ledger  (existing, unchanged — real-money rewards)
                └─▶ pet_xp_ledger  (new, same hook, same transaction)

routine check   ──▶ pet_xp_ledger  (new — routines finally have a sink)

battle result   ──▶ pet_xp_ledger  (winner and loser both)

pet_xp_ledger   ──X  never writes back
```

**Routines are the quiet win here.** `RoutineItem` says *"No points — streaks
instead"*, and the avatar brief opens by naming that as the problem it existed
to solve. Routine completions minting pet XP gives the daily loop a second sink
that pays out on the surface kids care about most.

**Mint rates (v0, tunable in Settings):**

| Source | XP |
|---|---|
| Verified chore | `chore.points` × 1 |
| Routine item checked | 3 |
| All of today's routine checked | +10 bonus |
| PvE win | 15 → 40 by NPC tier |
| PvE loss | 5 |
| PvP win | 30 |
| PvP loss | 18 |

**Anti-farm guards, all required:**

- **Routine toggling.** `set_routine_check` upserts one row per
  `(routine_id, date)`. Mint only on the `false → true` transition and make the
  XP row idempotent on `(routine_id, date)`, or a kid earns infinite XP by
  tapping a checkbox.
- **PvE cap.** Default 5 NPC battles per day per member. Beyond the cap battles
  still run — they just mint 0 XP and say so. Never refuse the fun, only the
  payout.
- **PvP cap.** Default 3 rewarded battles per opponent pair per day, for the
  same reason and also because sibling grudge-matching should have a floor.
- ~~**Chore reversal.**~~ **Wrong when written; checked in P2.** There is no
  such path. Points are minted exactly once, at `verify_chore`, and nothing in
  the app ever reverses a chore award — `reject_chore` fires at `done`, before
  anything is awarded ("No forfeiture — points just wait for a pass"), and
  reopening a verified chore only changes its state. XP mints on the same
  event and inherits the same behaviour, so there is no reversal machinery to
  build and none was.

**Sinks:** stat training, move slots, species unlocks, the second pet slot,
cosmetic parts. Lifetime XP earned drives **level**; XP spent buys the rest.
Spending never lowers level — same shape as `get_points_balance` vs the status
tiers that must never be taken away.

**XP belongs to the MEMBER, and every pet they own shares the level it buys**
(decided in P2). Banking XP per creature splits a child's effort the moment
they own two: the second pet arrives useless and the first one they liked
stops growing. Sharing answers "which one do I feed" with *neither, you feed
yourself*. Training points are still spent per pet, so the choice that matters
is where effort goes, not which animal receives it. `Pet.level` is therefore
**derived on every read** and never trusted from the record.

**The curve** is quadratic: `20 × (L−1)²` lifetime XP to reach level L, capped
at 50. L2 at 20, L5 at 320, L10 at 1620. At roughly 25–80 XP a day that is a
level on day one and L10 in about a month.

**XP mints for adults too**, even though points do not. Points are
children-only because they cost a parent real money; XP costs nothing and buys
nothing outside the game — and a parent's critter has to be able to level or
it drags every level-matched fight down to its own floor.

---

## Battle

### Asynchronous, resolved server-side, watched as a replay

Kids are not on the app at the same moment, and a wall panel cannot sit blocked
waiting for a phone. Live turn-based PvP means presence, sockets, timeouts and
rage-quits.

Instead: **pick a 4-move loadout, challenge, the server resolves the whole
battle deterministically, and both sides watch the same replay in the overlay.**

The resolver is a pure function of `(seed, loadout_a, loadout_b)`, so we persist
the seed and the loadouts — never a frame log. The replay is reproducible on any
device, at any time, forever, from ~100 bytes. It is also trivially unit
testable, involves no LLM and never touches the solver.

The honest cost: no mid-fight decisions. The strategy lives in team building and
move selection instead — which is exactly what the chore economy feeds, so it
pulls in the right direction.

### Stats

The Pokémon six, because kids who love Pokémon will want the real thing:
**HP, Attack, Defense, Sp. Atk, Sp. Def, Speed.**

Level comes from lifetime XP. Each level grants training points; training points
are allocated by hand, capped per stat so nothing degenerates into one number.

### Types — a five-ring, not eighteen

Each type is strong against the next and weak against the previous. A ring is
provably balanced, has no lookup table to memorise, and a seven-year-old can
hold it in their head:

```
Ember burns Leaf → Leaf splits Stone → Stone grounds Spark
      → Spark boils Tide → Tide quenches Ember → (Ember)
```

Super-effective ×1.6, resisted ×0.625. No immunities — a move that does nothing
is not fun, it is a wasted turn.

### Moves

Four slots. `{key, name, type, category: physical|special, power, accuracy,
effect?}`. Ship ~20. Damage is a flattened Pokémon formula:

```
dmg = ((2·level/5 + 2) · power · atk/def) / 50 + 2
      × type_multiplier × stab(1.2) × random(0.90 … 1.00)
```

Speed orders turns; ties break on the seed. Effects in v0 are limited to
stat stages, flinch, and heal — no status clocks, no weather, no switching.

### Level-matching — the spine of the whole design

A pet's power **must not** decide a sibling fight. In PvP:

- Both pets are scaled to `min(level_a, level_b)`.
- Each pet's **stat total is normalised** to the same budget, while its
  **distribution is preserved.**

So the kid who thought about their build keeps every bit of that advantage, and
the kid who has done more chores keeps none of it. The fight is decided by
allocation, typing, move choice and luck — all of which are free.

**Power progression lives in PvE.** NPC tiers scale with level, so the grind is
rewarded against the machine and neutralised against the family. That division
is the answer to the one thing that could genuinely hurt a child here, and every
future change to the battle model has to be checked against it.

Supporting rules: the loser always earns meaningfully (18 vs 30). There is no
ladder, no ranking, no win-loss record on any board tile or kiosk surface. A
battle is a toy, not a standing.

---

## Data model

**`pets_table`**

```
{id, member_id, name, created_at, active,
 species: {body, top},                       # the 210-silhouette axis
 look:    {eyes, mouth, pattern, cheeks, base_color, accent_color},
 type:    'ember'|'leaf'|'stone'|'spark'|'tide',
 level, training: {hp, atk, def, spa, spd, spe}, moves: [key × 4]}
```

**`pet_xp_ledger`** — append-only, deliberately mirroring `points_ledger`:

```
{id, member_id, delta, reason: 'chore'|'routine'|'battle'|'grant',
 ref_id, ts, by_member_id?}
```

**`pet_battles_table`**

```
{id, a_pet_id, b_pet_id | npc_key, seed, loadout_a, loadout_b,
 winner, xp_a, xp_b, created_at, seen_by: [member_id]}
```

**Storage functions**, named to match what exists so the shapes rhyme:
`get_pet_xp_balance`, `get_spendable_pet_xp`, `grant_pet_xp`,
`get_pet_xp_ledger`, `sync_pet_unlocks`.

**Hooks:** `verify_chore` (mint alongside the existing `points_ledger.insert`,
same lock), `set_routine_check` (transition-guarded), and the chore-rejection
path.

**Catalog as data, not code** — `pets/catalog.json` holding parts, species,
types, moves and NPCs, in the spirit of `avatar_catalog`. Adding an NPC or a
move must never be a code change.

---

## Surfaces, and the rules they have to obey

- **Hand path for everything.** *Every agent capability needs a hand path.* Any
  pet action an agent can take — hatch, rename, train, challenge — must be
  reachable by tapping. The battle overlay must be openable from the pets card
  without an agent in the loop.
- **Both agent stacks.** The chat widget runs `agent_router` / `agent_tools_v2`;
  the loop runs `agent_tools`. Pet tools go in both or the feature is invisible
  from half the app.
- **Boards, not pages.** Pets is a placeable card (`_tile_pets`) with section
  toggles defaulting on, a members filter, and `interactive` on by default —
  the card-conversion paradigm. It must render on `?panel=true`.
- **Kiosk shares logic.** The battle replay is a shared component, not a
  duplicated one; the kiosk variant differs only in presentation.
- **No browser dialogs.** `showGlobalAlert` / `promptConfirm` / `promptInput`,
  never `alert()`.
- **Settings live in `settings_registry`** plus the pets page — not
  `config.html`. Keys: PvP on/off, daily PvE cap, per-pair PvP cap, XP rates,
  quiet-hour suppression for battle notifications (the kid-support arc's
  quiet-hour rule applies to challenge pings).
- **Degrade without HA.** Nothing here may require Home Assistant.
- **Tailwind is precompiled.** Run `tools/build_tailwind.py` after template
  class changes.

---

## Slices

- **P0 — the bake.** *Done (v2.294.0).* Harvest script → `static/pets/pieces.json` (80 groups, ids
  namespaced, top-anchor table, base-fill slot marked). `pet_render.py`
  compositor, two crops (`chip` 100×100, `battle` full). Downscaled background.
  *No gameplay. This is the only slice with asset work in it, and it is a day,
  not the week Avataaars' A0 was.*
- **P1 — pets exist.** *Done (v2.295.0).* `pets_table`, hatch, name, free customisation, pets card,
  editor overlay. No XP, no battle. A kid can make a critter and everyone sees
  it on the wall.
- **P2 — the ledger.** *Done (v2.296.0).* `pet_xp_ledger`, the two mint hooks
  with their guards, levels, rates in Settings, balance and progress on the
  card and in the editor. No reversal path — see above. Nothing to spend it on
  yet.
- **P3 — the resolver.** *Done (v2.297.0).* Pure `pet_battle.py`: stats,
  five-ring types, 20 moves, damage, turn order, level-matching, seeded RNG.
  20 tests, no UI. Two things the build added that this brief did not
  anticipate: **every body sums to the same stat total** (shape, never
  strength — rule 1 at the stat table), and **moves may declare `uses`**,
  which heals do, because two healers otherwise ride the turn limit to a
  coin flip in 8–16% of fights. Damage constants are calibrated, not
  inherited from Pokémon — theirs assume level 50–100 and gave two-hit
  knockouts here.
- **P4 — the overlay.** *Done (v2.298.0).* Replay player on the background:
  two critters, HP bars, scrolling move log, CSS transform hits. PvE against
  6 NPCs, daily cap, visible odds. **Avatars are NOT in the scene** — two
  critters and two HP plates already fill a 16:9 stage, and a bust-crop
  avatar beside a full creature read as a collage. Revisit if the stage ever
  gets wider.
- **P5 — training and spending.** Levels, training points, move slots, species
  unlocks, second pet slot.
- **P6 — PvP.** Challenge, accept, resolve, both-sides replay, caps, quiet-hour
  respect, agent tools in both stacks.

Full sweep with `tools/test.py` before each commit; `--focus` for the inner
loop. Bump `config.yaml` and commit at every slice.

---

## Out of scope for v0

Trading, breeding, shiny/rarity tiers, held items, status clocks, weather,
switching mid-battle, multi-pet teams, real-time battles, cross-family
opponents, any leaderboard or W/L record, and evolution beyond the
scale-plus-top rule. Also: pets do not follow the avatar around the app — that
is `follow-me`, already deferred once.
