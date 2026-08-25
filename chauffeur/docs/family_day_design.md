# The Family Day card — one place the day lives

*Design settled 2026-08-25, in conversation. Companion to `docs/packing_design.md`
(P1+P2 shipped v2.388.0–v2.395.0); this reshapes the surface that arc built.
Where the two disagree, this document wins for the tile; the packing design's
mechanics (outings, claims, XP, the routine boundary) stand untouched.*

## The problem: the day is one thing, drawn in quarters

The wall answers "what is happening today and are we ready for it" in four
places: the agenda (`calendar` card) for what is on, the driving schedule
(`drives`) for who is driving where, the packing tile (`packing`) for what has
to be in the bags, and the hero for what is next. These are not four subjects.
They are four views of one subject, and a person standing at the wall has to
visit all four and join them in their head.

The observation that decides the shape: **most people look at the agenda**,
because it is simple and easy to parse. Whatever replaces it has to clear that
bar or it fails. The goal is not a richer card; it is the agenda's
parseability with the other three cards' answers woven in.

The hero stays. It is a loud reminder of the next thing, and its loudness is
its job — which frees this card to be uniformly quiet and scannable. The two
are complements: hero shouts *next*, Family Day lays out *the whole day*.

## The spine: blocks, not outings

The packing tile's spine was the outing. That spine cannot carry a whole day:
not everything leaves the house, and an event that stays home can still have
things to prepare — they just do not get packed into a car.

So the unit generalizes. The day is a time-ordered list of **blocks**:

- **The event block is the atom.** Time, title, and — when a kit matches —
  prep items with the needed counts and claims the packing arc already built.
  An at-home event is a bare event block. Kits are driver-blind
  (`match_kits_for_event` never asks who drives), so the birthday-cake kit
  against an at-home party is the same code path as the soccer bag.
- **The outing is a container, and it materializes only at two or more
  events.** A single-event outing drawn as a box around one line is redundant
  chrome, and most outings are single-event — that day would be all boxes. A
  single-event outing is one flat line carrying time, title, driver, car, and
  readiness. At two or more events the container appears: the outing's outer
  block carries what is trip-level — driver, car, the promoted readiness pill
  — and the events sit inside it as compact lines, title and time only,
  always visible. The box itself says "one trip, one packing job", which is
  the incident's fact stated more strongly than a joined title ever did.
  Expanding the container unfolds the inner event blocks to their full form.
- **A covered ride is a block too.** `outings_for` builds only from driver
  assignments, so an event an outside hand covers (load arc; no household
  driver, `leave_by.ready_for_covered` is its wall presence today) currently
  loses its packing entirely — Grandma driving does not mean the bag packs
  itself. On this card it is a bare event block naming its coverage
  ("Swim — Grandma driving") with its items. This is a repair, not a feature.
- **All-day events are a banner, not blocks.** One slim line across the top.
  They have no time to anchor a block to, and they must continue to never
  reach the solver (`driver_events`) — this card is a read-only lens over the
  event feed, and it changes nothing about what the solver sees.

## Presentation: an agenda at rest

The resting state reads like the agenda did — one line per block, time
ordered, readable from three metres:

```
─ Spirit Week ──────────────────────────────
  9:00  🚗 Soccer + Band     Sarah · CR-V   [3 to pack]
         9:00  Soccer
        10:30  Band
 12:00  🏠 Grandma's birthday               [4 to pack]
 15:30  🤝 Swim — Grandma driving           ✓
 18:00  🚗 Piano              Jeff · Sienna
```

- Container rows show the trip facts; their compact inner lines keep each
  event scannable with its own time (the agenda's parseability, preserved
  per event, with fewer top-level rows than the agenda had).
- Tap a block → its items unfold: kit groups, steppers where `needed > 1`,
  ticks where `needed == 1`. All of it is the shipped packing mechanics —
  optimistic claims, poll survival, the amber cap at `needed`. Expansion
  state lives client-side and survives the board's poll, which is exactly
  what the packing tile's tests already pin.
- No block auto-expands. Auto-expansion breaks the scan, and "what should I
  look at first" is the hero's job.

### The eye-catcher: one calm pill

With nothing auto-expanded, a row must still say "I need attending to"
without being tapped. The rule, and it is deliberately a two-state rule:

- Work remaining → a filled amber pill, **`3 to pack`**, promoted onto the
  container (or the flat row). It is the only saturated element on a resting
  row, so amber anywhere on the card means someone should tap. A household
  learns that rule in a day.
- Done, or nothing to pack → a muted `✓`, or nothing at all.

**No proximity escalation, no pulsing, no colour ramp toward departure.**
This card is a surface, not a notifier — the packing design's standing rule —
and a badge that is loud all day teaches everyone to ignore it, which is the
counter lesson this arc already learned once. If living with the card proves
a real need for departure-aware urgency, that is its own decision taken
later, with the watcher-signal policy applied to it.

## What changes underneath

Three shipped rules flip, deliberately:

1. **An outing with nothing to pack now draws.** "Nothing to pack is nothing
   to draw" was the packing tile's rule; on a family-day card a drive is a
   happening whether or not it has cargo. The quiet-day sentence becomes
   honest only when the day has **no blocks at all**.
2. **Turnover follows the last block, not the last outing.** A day ending
   with an at-home party must not flip to tomorrow mid-party. Same rule as
   before — the day the household is thinking about — wider input.
3. **Covered rides return to the packing surface** (the repair above).

Claims against home blocks are keyed `home:<event_id>` — the claims table
takes any string key, and every mechanic (counts, once-per-day XP, no
clawback, anonymous wall taps) carries over unchanged.

## The board swap

The default home board replaces **`calendar` + `drives` + `packing`** with
this one card. The hero stays. All three replaced cards remain in the
catalog, untouched and placeable — the swap is board configuration, so
living with it is reversible by anyone in board edit mode, and the trial the
household actually wants ("does one card really beat three?") costs nothing
to run or to unwind.

## Slices

**F1 — the reshape.** The packing card evolves in place (keeps placements,
config, tests, claims): blocks, the container rule, the amber pill, the three
rule flips, the all-day banner, the board swap. Packing is the only cargo
type.

**F2 — meals join.** Meal-prep items as a second kit source on the same rows
— the family eats full meals in the car between activities, so a prepped
cooler is outing cargo exactly like a soccer bag. Same claims, same pill.
Designed for now, built later.

The packing arc's P3 (the phone half) is untouched by this design and
composes with it: the kid's My Day items and the driver's list read the same
blocks.

## What this deliberately does not do

- **It does not absorb other systems.** Chores, routines, messages, moments,
  media stay their own cards. This card grows by cargo type (packing → meals
  → one-offs), never by surface type. The fragmentation it heals is the
  *day's* fragmentation; pulling in unrelated surfaces would rebuild the
  home board inside one tile.
- **No identity on the wall.** A kid finds their items by name and grouping,
  not by the wall guessing who is standing there. Anonymous claims stay
  anonymous.
- **No urgency machinery.** The pill has two states. See above.
- **Nothing changes for the solver.** Blocks are a lens over the schedule
  cache and the event feed. All-day events stay out of `driver_events`;
  covered events stay unassigned; the tile writes nothing but claims.

## Open questions

- **Should expanded blocks fold themselves after idle?** A wall card is
  shared; one person's expansion is the next person's clutter. Undecided —
  ship without, watch.
- **Should tomorrow appear early as a quiet second section?** Carried over
  from the packing design, and a family-day card strengthens the case — an
  adult packing tomorrow's swim bag at lunch cannot see it until the day
  turns. Still deferred; the day-follows-the-day rule ships unmodified.
- **Does the `drives` card's per-driver grouping have a constituency the
  block spine loses?** Blocks group by time, not driver. If a driver at the
  wall misses "just my drives", a member filter already exists on the card
  config. Watch before building more.
