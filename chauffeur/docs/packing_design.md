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

## The density this has to survive

Asked how big a day is, the household's answer: **a light weekday is at least two
activities, an average day is four, a weekend runs eight to ten.**

That settles a question this design was carrying — whether outing grouping earns its
place — and it changes two things.

**The chain is normal, not exceptional.** At four activities a day, going straight
from one to the next without passing home is most days, not a curiosity. So the
"you are not stopping home between these two" fact must NOT become a sentence the
tile says: at this frequency an announcement is wallpaper within a week, and this
design has been careful not to add a notifier. **The grouping is the message** — two
events under one heading with one list is the app saying it, in the only register
that survives repetition.

**Eight outings cannot all be open at once.** Ten activities at four items each is
forty lines on a wall panel read from across a room, which is a tile nobody uses. So
the tile is a **list of outings, not a list of items**: one row each, in departure
order, carrying its progress (`Soccer + swim · 2/6`); the **next** outing expanded to
its items; anything already packed collapsing out of the way. A household headline
("2 of 5 outings ready") is what somebody actually reads from the doorway.

**Two cars out at once is a new way to be wrong.** At this density several drivers
overlap, and "is it in the car" becomes *is it in the right car* — the bag packed
perfectly and loaded into the wrong boot is the same lost afternoon as the bag left
at home. An outing already belongs to a driver, so every outing row names its driver
and car, and the drive sheet at the car shows that outing's list and no other.

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

**It flips to tomorrow in the evening** — see *Timing*.

**The kid's own day.** Prep for an event a kid is attending appears in their My Day,
sourced from the event and ticked once, everywhere. This is the household's own
framing and it is the right architecture as well as the right parenting: *routines
are the daily repeats, the day's activities are the source of truth for what today
needs.* A kid's "pack your backpack" habit stays a routine item with its photo
steps; "shin guards for Tuesday" comes from the event.

**A child's day never flips.** An earlier draft of this design had it turning over
to tomorrow in the evening, and the household corrected it: *the routine has to stay
until it is over time-wise, which is bedtime, so there is no time in their day after
the routine ends.* A flip would hide a child's own unfinished evening at exactly the
hour they are working through it.

Instead, **tomorrow's packing slots into tonight's evening routine**, which is where
that work actually belongs — see *Timing*.

### The routine boundary

Prep items appear in a child's day beside their routine. They are **not routine
items**, and three properties follow from that — all three asked for by the
household, all three free by construction as long as prep never enters
`routines_for_day`:

- **An unpacked item cannot fail a routine.** The day's routine is complete when
  its routine items are ticked; a bag nobody has packed is a real problem, and it
  is not a broken habit.
- **Somebody else packing it cannot complete a child's routine.** A parent who
  drops the shin guards by the door has helped the household, not kept the child's
  streak.
- **Streaks are untouched, in both directions.** No prep tick lengthens one and no
  missed item breaks one.

The one thing prep DOES pay is **critter XP** (below), because getting your own
stuff ready is real work and the household wants it to feel that way.

### What a prep tick mints

One ledger row through the existing `grant_pet_xp`, with its own reason
(`'prep'`), and three rules borrowed from what routines already learned:

- **`once=True` per (member, item, day).** A child can tick and untick a box all
  afternoon; without the guard that is an XP faucet. Routines pass this flag for
  exactly this reason.
- **Unticking never claws it back** — "a thing earned is never taken away", the
  rule the routine ledger already states.
- **An anonymous wall tap mints nothing.** No member, no XP. The wall has no
  identity and inventing one to pay somebody would be a lie with a currency
  attached.

**XP goes to whoever did the packing**, not to whoever the item was for. If a
parent packs a child's kit, the child is not paid for work they did not do — that
would hollow out the one lesson this half of the design exists to teach, and it
would make a farm out of a helpful adult. Stated as a decision because it is
arguable: see *Open questions*.

Prep pays **no points**. Points are the chore ledger's currency and packing your
own bag is not a chore somebody assigned; XP is the right and only sink here.

**The driver's phone.** The same outing list, for the adult who is not in the room —
and, at the car, the drive sheet becomes the outing's list with one confirmation
instead of one event's list.

**Event details, everywhere it opens.** Adding a one-off item is not a wall feature;
it is an *event* feature, reachable from the PWA's event modal, the schedule and
calendar admin pages, and the wall's own event dialog. The calendar dialog is
already a shared component, which keeps this from being four implementations.

## Timing: no clock, no setting

An earlier draft gave both surfaces a cutover hour and had them share
`kid_digest_cutover_time`. **That decision is withdrawn.** The household's own rule
is better than a clock on both surfaces, and it costs no setting at all.

### A child's day: the item lands where there is still time to act on it

A child's day is drawn in buckets by time of day — morning before 12:00, afternoon
to 17:00, evening after, and anytime for the untimed (`KID_BUCKETS`,
`app.html:1216-1221`). A prep item is placed in **the last bucket before its outing
leaves**, and never after it:

- an outing leaving tomorrow morning → **tonight's evening**, beside "brush teeth"
  and "pack your backpack", because 06:40 on the way out of the door is not a time
  anybody packs a bag;
- an outing leaving later today → the bucket before its departure;
- an outing whose window has already passed → the current bucket, still asking.
  A list you can act on beats a list that is filed correctly and invisible.

Tomorrow's packing therefore appears *inside tonight's evening routine*, which is
the household's framing and also the honest one: it is evening work, on the evening
list, done before bed. It still does not count toward routine completion or a
streak — see *The routine boundary* — it simply sits where the work happens.

### The family tile: it follows the day, not the clock

The tile shows **what is still ahead**: today's remaining outings while any remain,
and tomorrow's once the last one is over. "The last event of the day concludes" is
the household's own trigger, and it is the moment a family starts thinking about
tomorrow — 19:00 on a day with a 20:30 pickup is not, and 19:00 on a day that ended
at 15:00 is three hours late.

Two properties fall out of it for free, both of which the clock version needed
rules to buy:

- **A live outing can never be hidden**, because the tile cannot turn over while
  something is still ahead. The pinning rule the previous draft needed is gone.
- **A day with no outings at all shows tomorrow from the start**, because nothing
  is ahead. No empty-day special case.

The turn-over point is the last outing's **end** — the drive home — rather than the
last event's end. Same moment plus the drive, and it avoids a wall at home
announcing tomorrow while the family is still standing in a car park.

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

- **No new nagging, and no sentence about the chain.** The tile is a surface, not a
  notifier. An earlier draft had it announce "you are not stopping home between
  these two"; at four activities a day that sentence fires constantly and stops
  being read. The grouping carries the same fact silently and permanently. This
  follows the standing rule for findings: time-critical, actionable, solution
  attached, or silent.
- **A tick never touches routines, streaks or points.** It mints critter XP and
  nothing else — see *The routine boundary*. Packing is not a chore somebody
  assigned, and a routine is a habit, not a to-do list for the day's logistics.
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

**P2 — the panel tile.** The family-day card: outings as rows in departure order,
each naming its driver and car, the next one expanded to its items, steppers,
interactive ticking, and the turn-over to tomorrow when the last outing is home.
Claims storage lands here (it is what the ticking writes). Ships the incident fix:
two events in one outing appear as one packing job, which is the fact stated in the
only way that survives being true most days.

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
- **A ten-activity Saturday** is a fixture in its own right: the tile stays readable
  (one row per outing, one expanded), items dedupe by person across an outing rather
  than summing, and two drivers out at once keep their lists apart.
- **The turn-over** is now a function of the day rather than a clock, so it is
  tested as one: a day with an outing still ahead shows today; the same day with
  that outing ended shows tomorrow; a day with no outings shows tomorrow throughout.
- **Bucket placement** for a child: an outing leaving tomorrow morning puts its
  items in tonight's evening; one leaving this afternoon lands earlier in the day;
  neither ever lands after its own departure.
- **The routine boundary** is three assertions, because all three are silent when
  wrong: an unpacked item leaves the day's routine complete; a parent's claim does
  not complete a child's routine or extend a streak; and a prep tick grants XP
  exactly once per (member, item, day) however many times it is toggled.

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

- **Does the kid's view need the outing at all**, or only their own items? A kid does
  not care that their band run and their sister's soccer run are one trip.
- **Should the family tile ever show tomorrow early?** It follows the day, so an
  adult who wants to pack tomorrow's swim bag at lunchtime cannot see it until the
  day is done. Adding tomorrow as a quiet second section would fix that and would
  also start filling a tile that is meant to be readable across a room.
- **What happens to an item nobody claims by departure?** Silence is defensible.
  Saying something is a notification, and this design has been careful not to add one.
- **Should a child be paid XP for an item an adult packed for them?** This design
  says no — the payer is the packer — because paying the child for a parent's work
  hollows out the lesson and turns a helpful adult into a farm. The counter-argument
  is real: a young child whose parent packs most things sees a list they can never
  earn from, which is its own discouragement. Worth revisiting once a kid has lived
  with it for a week.
