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
- **The outing is a container.** Its outer block carries what is trip-level —
  driver colour down its side, the full time of the trip, driver, car, the
  readiness pill — and its events sit inside it as ordinary event rows in
  their own people's colours, always visible. The box itself says "one trip,
  one packing job", which is the incident's fact stated more strongly than a
  joined title ever did. Because the events carry the titles, the container's
  heading does not repeat them.

  *(F1 drew the box only at two or more events, on the reasoning that a box
  around one line is redundant chrome. Living with it showed the cost is
  elsewhere — see **Every trip is an outing** below, which supersedes that
  rule.)*
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

The default home board replaces **`calendar` + `drives`** with this one card
(the packing card was catalog-only, never on the default board; this card
takes calendar's slot). The hero stays. Both replaced cards remain in the
catalog, untouched and placeable — the swap is board configuration, so
living with it is reversible by anyone in board edit mode, and the trial the
household actually wants ("does one card really beat three?") costs nothing
to run or to unwind.

## What F1 shipped, and what it did not

*Added after living with F1 (v2.398.0–v2.406.1). The household's verdict is
the section that follows, and it is worth recording plainly rather than
quietly fixing.*

F1 delivered a **better agenda**: one feed instead of four cards, covered
rides repaired, two events on one trip drawn as one job, a turnover that
follows the day, and packing state that survives the board's poll.

It did not deliver **load reduction**, which was the point. Items were drawn
on the outing they belong to, which means the list for a 4:00 PM departure
appears at 4:00 PM. That is a report, not help. The household said it
exactly: *"it still falls into the trap of putting the packing at the time of
the event you are packing for, when it is too late."* Everything below is the
correction, and none of F1's substrate is wasted — the block spine, the
claims, the shared row builder and the endpoint are what the correction is
built from.

Two smaller things came out of the same look:

**The card spoke a different colour language than the rest of the app.** The
calendar's agenda colours an event's left bar from
`calendar_metadata[ev.calendar_ids[0]].backgroundColor`
(`family_calendar.html:1468-1470`) — the colour of the calendar the event
lives on, which in this household is the person's own. Every other surface
therefore says *whose* event it is at a glance. The Family Day card overrode
that with the driver's colour (`packing_card.html:549` and its siblings), and
the result was unreadable in the strictest sense: the household could not
work out what the colours meant. **Passenger colour belongs to the event,
driver colour belongs to the trip.** An event is a person's commitment; an
outing is a logistics job. Where they disagreed, the card was wrong.

**Who is going was a tap away, and that is a regression.** The agenda answers
"whose is this" with the bar colour; the grids answer it with passenger dots
(`family_calendar.html:730-742`). The Family Day card answered it only inside
the details dialog. A packing card that cannot say who an activity is for is
how cleats get packed for the wrong child.

## Prep is work, and work belongs where you can do it

The correction, in one sentence: **the packing for an outing appears in the
day as its own block, positioned where a household could actually do it, and
not beside the outing it serves.**

This is not a calendar appointment. A prep block has no start time and no
duration and never touches the solver — it is a **position in the list**, and
the list is the thing a family reads top to bottom. The household was
explicit that a slot right before the outing solves nothing.

**The placement rule.** A prep block lands at the start of the last part of
the day that ends *before* the outing departs:

| The outing leaves | Its prep sits at the start of |
|---|---|
| tomorrow morning (before ~12:00) | **tonight's evening** |
| this afternoon (12:00–17:00) | **this morning** |
| this evening (after 17:00) | **this afternoon** |

This is the rule the packing design already wrote for a child's own day —
*"a prep item is placed in the last bucket before its outing leaves, and
never after it"* — which the family tile simply never inherited. The naive
alternative (all of today's prep at the top of today, morning outings' prep
at the end of yesterday) is close to the same thing and would be defensible;
the reason to prefer the rule above is that it stays honest once **meals**
join, because a cooler packed ten hours early is a different kind of wrong.

**The catch-up rule, which is the one that keeps it usable.** If a prep
block's window has already passed and the items are not packed, it moves to
the front of what is left and keeps asking. *A list you can act on beats a
list that is filed correctly and invisible.* Without this rule, a single-day
view would silently lose the prep for this morning's outing, because that
block's proper home was last night.

**What a prep block says.** The outing it serves and when that outing leaves,
the **passengers it is for** — cleats for the wrong child is the specific
failure this prevents — and the items with their counts and steppers. It
carries the same amber pill as everything else.

**Nobody owns it.** There is no assignee. The wall has no identity, claims
stay anonymous there, and a prep block that named a person would be inventing
one. It is household work sitting in the household's day.

### Items are chips, and the app already draws them

A prep block's items are **chips flowing horizontally**, not a vertical list:
the kit's name as a leading label, then one chip per item, wrapping. Tapping
a chip claims it; tapping it again releases it. An item needing more than one
carries a `−  n  +` stepper immediately after its chip, as one non-breaking
unit.

This is not a new pattern. The drive sheet already ships exactly this control
— `app.html:6601-6607` draws each prep item as a **tappable chip**, amber
while it is still to pack, green with a `✓` once it is, toggled by tap — and
the My Drives event row already draws the read-only version, a `🎒 Bring`
label followed by amber chips flowing and wrapping (`app.html:1886-1889`).
The Family Day card should adopt that vocabulary rather than invent a third
one, and the kit name takes the position `🎒 Bring` holds there.

Two things fall out of it, both of which resolve questions this design had
left open:

- **A prep block never needs expanding.** Six items as rows is six rows; as
  chips it is one wrapping line. Compact enough to be always visible, which
  is what a block you are *meant to act on* should be. The no-auto-expand
  rule exists to protect the scan from walls of item rows; chips do not
  threaten the scan, so the rule has nothing to protect against here.
- **A prep block carries no amber pill.** The pill's job is to say "there is
  work here you cannot see". When the work is visible as chips, the pill is
  redundant — and a block showing both would put six amber chips beside an
  amber pill, which breaks the one-saturated-element rule by volume. So:
  **the pill lives on the outing** (where the items are one tap away) **and
  the chips live on the prep block** (where they are not). Each surface says
  the thing the other cannot.

The item chip's own states stay the drive sheet's: soft amber tint while
unpacked, green with a `✓` when packed. Neither is a saturated fill, so the
outing's filled amber pill remains the loudest thing on the card.

For consistency the outing's door-check list uses the same chips — one item
presentation everywhere, and the outing's expansion gets shorter as a bonus.

**The outing keeps its list too.** Items appear both in the prep block and
inside the outing, and this is deliberate rather than duplication: they are
two views of one truth, because a claim is stored against the outing and the
item, not against the place it was ticked. The prep block is where the work
is *scheduled*; the outing is the check at the door. The household's reason
is the right one: *"if you get to that in the day and it isn't packed, you
shouldn't have to go hunting back in the day to find the list."*

**Derived, never stored.** A prep block is computed on read from the outing
it serves, exactly as outings are computed from route edges. No new table, no
new state, the lens still never writes — the only thing written anywhere in
this arc remains a claim.

## Every trip is an outing

F1 drew the container only at two or more events, on the reasoning that a box
around one line is redundant chrome. Living with it showed the cost is
elsewhere: with two shapes, the driver, the car and the readiness pill move
depending on how many events a trip has, and the colour rule has nowhere
consistent to live. **Every trip out of the house is drawn as an outing
container** — driver colour down its left side, the full time of the trip,
driver, car, and whether it is packed — with its events inside it as ordinary
event rows in passenger colours, showing their passengers exactly as the
agenda does.

An event that needs no driving is an ordinary event row at the top level,
identical to its agenda self. Nothing about it is special here.

This costs a row per single-event trip. It buys one place for every trip
fact, one meaning for every colour, and it is paid for by prep moving out of
the outing into its own block.

## More than one day

A card that replaces the agenda has to do what the agenda does, and the
agenda shows several days (1–14, `agendaDays`). One day is also not enough
for prep to work: tomorrow morning's swim bag is packed tonight, so tonight's
view must be able to show tomorrow. Days become a card option, the way the
calendar card already has one.

The nesting this implies — day, then outing, then event, then items — is one
level too deep to read from three metres. **Day boundaries are separators,
not another nested panel**; the outing stays the only container.

## Packing is a decided act (F4)

*Added after living with F3 on the real wall. Six prep blocks, each repeating
the same four chips, in an order nobody could explain.*

F3 put the packing in the right part of the day and then drew it wrong. One
prep block per outing meant a Friday evening carrying four Saturday-morning
trips became four blocks stacked at the same anchor, sorted — because they
shared a timestamp — by their internal keys, which is to say alphabetically
by event id. To a household that is no order at all.

The deeper mistake was the unit. **You do not pack an item; you decide to
pack, and then you work one event's list.** The chips invited item-at-a-time
ticking from across the room, which is not how anybody packs a bag.

### One block per part of the day

A day has at most three prep blocks — morning, afternoon, evening — and each
is a single block wearing the `Pack` chip and no title, sitting at the start
of its own part of the day. Inside it are **per-event tiles**, laid out
horizontally and wrapping, ordered by the departure of the event they serve.
That ordering is the fix for the incident above: tiles run in the order the
day will actually happen, and one block replaces six.

A tile says three things: the event's **title**, its **passengers**, and how
big the job is — `4 items`. The size matters because a tile with no count
gives a household no way to judge whether to start now, and every tile
otherwise looks the same weight.

Its control is a single **`Pack Items`** button. That button is the point: it
is an intentional act — *I am ready to pack for this event* — rather than an
invitation to tick one thing in passing. When everything on it is claimed the
tile turns to **`Packed ✓`**, and the outing's own pill says `Packed ✓` too.

### The dialog

`Pack Items` opens a dialog naming the event, the people it is for, and the
list — the same claims, the same counts, the same chip vocabulary F3 borrowed
from the drive sheet, now somewhere with room for them. This is where the
list belongs: a wall row can hold four chips, a dialog can hold twelve, and
later it can hold the step photos routine items already have.

Three rules bind it:

- **It is a shared component.** The kid's My Day (packing arc P3) and the
  driver's list need exactly this — one event's list, ticked — and if it is
  built inside this card they will fork it.
- **The board's poll must not touch it.** The wall rebuilds every thirty
  seconds; an open dialog and its in-flight claims survive that, the same way
  expansion state and pending claims already do. This card has been burned
  twice by state that resets under a finger, so the rule gets a test rather
  than a comment.
- **It closes cleanly.** A shared wall must not be left holding somebody's
  half-finished modal.

### What stays

**The outing keeps its own chips** as the door-check. At 5:15 with the car
loading you want one tap, not a dialog — that fast path was argued for
earlier and it still holds. The dialog becomes the primary path; the chips
remain the last-minute one.

**The passed-bucket rule is restated for the new unit.** A block whose part
of the day has gone carries forward only its **unpacked** tiles — dragging
finished ones along would make a household re-read work it has already done.
A block whose tiles are all packed collapses to a single `Packed ✓` line
rather than vanishing, because hiding what is merely quiet is the one thing
this board has learned never to do.

**The known trade.** A row of chips could be read from three metres: you
could see that the *water bottle* was the missing thing. A tile says only
that four items are outstanding. The shape of the job survives; its contents
move behind a tap. Against six blocks of repeated cleats-and-water-bottle
chips, that is a trade worth making — but it is a real loss and it is
recorded here rather than discovered again later.

### The outing's heading, corrected

The heading put the trip's identity on a second line and its chips on a
third. It reads better as one line: the `Outing` chip, then the **driver as
plain text** (a person's name is not a tag — the prep tiles name people the
same way), then the **car as a chip**, with the **packed status right-aligned
on that same line**. The time range follows underneath.

## Slices

**F1 — the reshape.** The packing card evolves in place (keeps placements,
config, tests, claims): blocks, the container rule, the amber pill, the three
rule flips, the all-day banner, the board swap. Packing is the only cargo
type.

Shipped v2.398.0–v2.406.1.

**F2 — the family's own language.** *Shipped v2.409.0.* Passenger colour on events and driver
colour on outings, passengers visible on the row without a tap, every trip
drawn as an outing, and more than one day. This is the slice that makes the
card readable by somebody who was not in the room when it was designed.

**F3 — prep lands where you can act on it.** *Shipped v2.410.0.* Prep blocks, the placement rule
and its catch-up rule, passengers named on the block, the outing keeping its
list as the door-check. This is the slice that turns the card from a better
agenda into help.

**F4 — packing is a decided act.** One prep block per part of the
day, per-event tiles ordered by departure, the `Pack Items` dialog as a
shared component, and the outing heading on one line. See *Packing is a
decided act* above.

**F5 — meals join** (was F2 before the F3 work was understood). Meal-prep
items as a second kit source on the same rows and the same prep blocks — the
family eats full meals in the car between activities, so a prepped cooler is
outing cargo exactly like a soccer bag. Same claims, same pill. Perishables
are why F3's placement rule is bucket-shaped rather than everything-at-dawn.

The packing arc's P3 (the phone half) is untouched by this design and
composes with it: the kid's My Day items and the driver's list read the same
blocks — and after F3, the same prep blocks, which is the same rule the kid
design already stated.

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
- ~~**Should tomorrow appear early as a quiet second section?**~~ **Answered
  by F2:** the card shows several days, so tomorrow is simply there. The
  day-in-focus rule survives as the answer to *which day leads*, not as a
  limit on what can be seen.
- ~~**Does a prep block auto-expand?**~~ **Answered by the chip form:** it
  does not expand at all, because its items are always visible as chips. See
  *Items are chips*.
- **How is a multi-passenger event coloured?** The agenda takes the first
  calendar's colour and the grids draw a dot per passenger. Matching the
  agenda exactly is the safe start; if a two-child event reads as one
  child's, the grids' dot row is the precedent to borrow.
- **Does the `drives` card's per-driver grouping have a constituency the
  block spine loses?** Blocks group by time, not driver. If a driver at the
  wall misses "just my drives", a member filter already exists on the card
  config. Watch before building more.
