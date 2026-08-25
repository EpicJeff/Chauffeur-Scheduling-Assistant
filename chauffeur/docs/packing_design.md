# Outings, and getting the stuff packed

A driver took a passenger to an event, went straight on to a second event, and
arrived without the second event's gear. Nobody had done anything wrong: they
packed what the app showed them, and the app showed them one event's list at the
one moment it shows anything actionable — the car door.

The household's own reading of it, which this design follows: **we knew they
weren't coming home in between, so we could have done something to save them.**

## What the incident revealed

Three separate gaps, in order of how much they cost.

**There is no surface for packing at all.** Prep kits are matched to events by
rule filters and rendered on every surface that draws an event, with *no timing
logic whatsoever* — pills on the driver's event card, the family card, the event
modal, the kid's ride card, the wall's calendar dialog. The only place they
become something you can *act* on is the drive sheet, and that is deliberately
"a loading checklist at the car, before pulling out". So the app helps you
**load**. Nothing in it helps you **pack**, and packing is the act that was
missed. Moving the load list earlier does not fix this; a list read while walking
out of the door can only ever be a list of things you already failed to pack.

**Nothing spans two events.** The app has legs and it has events. It has no word
for the thing that starts when you leave home and ends when you get back — which
is exactly the unit that decides what has to be in the car. Prep therefore had
nowhere correct to live, and defaulted to the event.

**The knowledge existed and was never said.** The solver already chains each
driver's day and, for every gap, works out whether there is room to detour home
(`matcher.py:1888-1924`: a gap over 45 minutes or a wait over 15, needing a
20-minute layover to be worth taking). When there isn't room it simply omits the
`home_waypoint` — the *absence* is the answer. A second model, `meals.member_spans`,
independently classifies the same gaps as `at_home` / `in_car` / `at_venue` and is
used to decide whether the family must pack food. Neither reaches the phone or the
wall. On the day this happened, two parts of the system knew.

## The concept: an outing

**An outing is one trip out of the house: leaving home, however many stops, back
home.** It is computed, never stored — a driver's chained edges for a date, cut
wherever a `home_waypoint` says they passed through home.

    initial edge          →  the outing starts
    route edge, no home   →  the outing continues
    route edge, home      →  this outing ends, the next one starts
    final edge            →  the last outing ends

An outing belongs to a driver, so two drivers out at once are two outings. The
household's day is the set of today's outings, ordered by departure.

**Naming, decided:** `home_board.todays_runs()` already means *today's rides*, and
`services/runway.py` already means *a child's morning*. "Outing" is free, and it is
the word the household used first. `run` and `runway` keep their meanings.

This is what makes the incident's two events into **one packing job**, and it is
also what keeps the app from over-warning: when the driver *is* coming home in
between, the two events stay two packing jobs, because carrying the whole day's
gear on every trip is its own kind of wrong.

## An item is a count, not a checkbox

The household's insight, and the one that makes the rest work. Two kids at the
same practice do not need *a* water bottle; they need two. A single checkbox
against "water bottle" is a silent way to leave one kid's bottle at home — and a
flat dedupe across kits (which is what the code does today, case-insensitively)
guarantees it.

So an item on an outing carries a **needed** count and a **packed** count, drawn
as a stepper: `− 1 +`, against a target.

**Needed** is derived, not typed:

- the people the item applies to = the kit's `passenger_ids` (already how a kit
  is targeted) intersected with the event's attendees;
- **distinct people across the whole outing**, not the sum per event — the kid who
  needs a water bottle at soccer and again at band needs *one* bottle, because they
  are carrying it all afternoon;
- no people resolvable → 1.

**Packed** is the sum of claims (below). A stepper never exceeds `needed`.

**The exception that must exist:** not everything scales with people. The team
snack, the folding chair, the cash for the fundraiser are one each however many
kids are going. An item can be marked **one for the group**, which pins `needed`
to 1. Without this the counter is wrong in a way that trains people to ignore it.

## State: claims for packing, one confirmation for loading

Two states at different granularities, because the granularity should match where
the person is standing.

**Packing is per item, and a tick is a claim.** A claim is
`{outing, item, member_id or null, ts}`. A kid ticking their own water bottle in
their own day claims a slot with their name on it. Somebody tapping `+` on the wall
claims an anonymous one — the wall has no identity and should not pretend
otherwise (`prep_status.confirmed_by` is written and never read today, which is the
same lesson already learned once). `packed` is the number of claims; the wall shows
`2/2`, and the names when it knows them.

A **tick-all** on a list is a convenience over the same claims, not a fourth state.

**Loading is one confirmation for the whole outing.** At the car you do not want to
work a list, you want to answer one honest question: *is it all with me?* This is
very nearly the boolean `prep_status` already stores; it moves from the event to
the outing.

**Per-day by construction.** Every calendar occurrence already has its own id
(`singleEvents=True` at `calendar.py:112-119` returns expanded instances), so an
outing key built from its events is per-day for free. No date needs to be part of
the key, and nothing needs pruning to stay correct.

## Where it appears

**The panel tile — the family's day (the centrepiece).** A card, not a page, so it
can be placed on the home board, the routines kiosk, or a board of its own, the way
every other content type on this wall works. It draws today's outings, each with
its packing list, and it is **interactive** — anyone in the house can tick, and
everyone can see what is left.

Read from three metres, so: outing → kit → progress (`Soccer bag 2/4`), items on
tap. Twenty bare strings in a tile is a tile nobody reads.

**It flips to tomorrow in the evening**, on the same reasoning the kid digest board
already uses at 19:00 — "a 'Tomorrow' board at 3pm answers the wrong question."
The packing for a 7am departure happens the night before, and a tile that is dark
at that hour misses the only moment that mattered.

**The kid's own day.** Prep for an event a kid is attending appears in their My Day,
sourced from the event and ticked once, everywhere. This is the household's own
framing and it is the right architecture as well as the right parenting: *routines
are the daily repeats, the day's activities are the source of truth for what today
needs.* A kid's "pack your backpack" habit stays a routine item with its photo
steps; "shin guards for Tuesday" comes from the event.

**The driver's phone.** The same outing list, for the adult who is not in the room —
and, at the car, the drive sheet becomes the outing's list with one confirmation
instead of one event's list.

**Event details, everywhere it opens.** Adding a one-off item is not a wall feature;
it is an *event* feature, reachable from the PWA's event modal, the schedule and
calendar admin pages, and the wall's own event dialog. The calendar dialog is
already a shared component, which keeps this from being four implementations.

## One-off items

An item added to an occurrence means **this occurrence**, and afterwards the app
offers once to keep it for next time.

The default is the safe direction: a wrong one-off is forgotten tomorrow, while a
wrong forever-item nags every week until somebody hunts down the kit that spawned
it. The offer exists because the other intent is real and common — "we forget the
mouthguard *every* week" is a kit edit somebody should not have to go and find.

Accepting the offer writes to the kit that already matches, or mints one when none
does. That is the existing prep-kit editor's job and its existing rules apply.

## What this deliberately does not do

- **No new nagging.** The tile is a surface, not a notifier. The one thing worth
  *saying* is the non-obvious fact — "you are not stopping home between these two"
  — said once, on the outing that has it. Everything else is a list that sits there
  until somebody reads it. This follows the standing rule for findings: time-critical,
  actionable, solution attached, or silent.
- **A tick mints nothing.** No points, no XP, no streak. Packing is not a chore
  ledger and routine steps already set this precedent.
- **No attribution on the wall.** The wall has no identity. Anonymous claims are
  honest; a name guessed from who usually stands there is not.
- **Blank means blank.** A day with no outing needing anything draws no card.
- **Not a shopping list.** "We are out of sunscreen" is the supply intake arc's
  question, not this one.

## Slices, in order

Each slice is a shipped thing on its own, and the incident is fixed by the first
two rather than by the last.

**P1 — outings.** `services/outings.py`: chain a driver's date into outings from
the existing edges, cut on `home_waypoint`. Pure computation over the solve cache,
no storage, no UI. Fold in the union of prep across an outing's events, deduped by
person. This is the piece the whole arc stands on and it is small, because the
chain data already exists.

**P2 — the panel tile.** The family-day card: today's outings, kits, steppers,
interactive ticking, evening flip to tomorrow. Claims storage lands here (it is what
the ticking writes). Ships the incident fix: two events in one outing show as one
packing job, with the reason said once.

**P3 — the phone half.** The kid's My Day gets its own event-sourced items with the
same claims; the driver's phone gets the outing list; the drive sheet's checklist
becomes the outing's, with the single loading confirmation.

**P4 — one-off items.** The event-attached item store, the editor in event details
wherever it opens, and the offer to keep it.

**P5 — the driver's tab.** `My Drives` → `My Day`, with the timeline as the spine
and the day's other work anchored above it. The load arc's own audit says the
adult's work is unmodelled and a tab named *My Drives* asserts that a driving
parent's day *is* the drives. True, and separable — which is why it is last rather
than first.

## Testing

The parts that have burned this codebase before decide where the tests go.

- **Outing chaining** (P1) is arithmetic over fixtures: two events with no room to
  get home are one outing; the same two with a long gap are two; a day with three
  drivers is three chains; an overnight chain does not exist because the solver
  groups per date, and the tests should say so rather than discover it later.
- **Counts** are where the silent wrong answer lives: two kids at one event needs 2;
  one kid at two events in one outing needs 1; a group item pinned at 1 stays 1
  however many are going.
- **The tile is geometry and interaction**, so it gets a browser test the way the
  card grid did — a tick on the wall changes the count, and the count survives a
  poll (the board rebuilds every 20 seconds; a checklist that resets on poll is
  worse than no checklist).
- **The evening flip** gets a clock-injected test at the cutover boundary, both sides.

## Cleanups this touches

Small, and honest to do while we are in here:

- Three production comments explain per-day prep keys with a **false mechanism**
  ("`_unrolled_` recurrence instances stay distinct" — `_unrolled_` is a
  per-passenger split-time index, not recurrence). The conclusion is true; the
  reason is a myth the next reader will build on.
- `prep_status` rows are never pruned. Harmless today; less harmless once claims
  are per item.
- No test anywhere covers the actual cross-day question for prep keys.

## Open questions

- **How many outings is a day, really?** If a household's typical day is one outing,
  the tile is a list of one and much of this ceremony is unearned. Worth counting
  against a real week before building P2's grouping.
- **Does the kid's view need the outing at all**, or only their own items? A kid does
  not care that their band run and their sister's soccer run are one trip.
- **What happens to an item nobody claims by departure?** Silence is defensible.
  Saying something is a notification, and this design has been careful not to add one.
