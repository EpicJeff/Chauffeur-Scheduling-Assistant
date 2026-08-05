# Meals & Provisioning Arc — design brief (drafted 2026-08-05)

The gap, in the family's words: **planning meals for a family is a full-time
job unless you want to serve frozen nuggets and fries.** Chauffeur exists to
carry mental load. Feeding people is one of the largest recurring loads in a
household, and until now the app's answer was to declare it out of scope.
That was a scope decision wearing a value judgment's clothes.

> **Revision note (2026-08-05, same day).** This brief was rewritten once
> after the family described how they actually eat. The original draft
> modeled meals as *cooked at home in an evening window* and split the work
> into four phases including a standalone "bail-out." Both were wrong. Real
> pattern: meals are prepped in pieces across the day and eaten **in the car
> between activities**, and a meal may be ordered, part-ordered, or all prep.
> The bail-out phase dissolved into M2/M3 once ordered food became ordinary
> rather than exceptional. Old numbering (M1 list / M2 bail-out / M3 window /
> M4 repertoire) → new (M1 list / M2 eating plan / M3 repertoire).

## Why the old cut was wrong (read this before re-cutting)

`roadmap.md` carried, under "Explicitly cut": *"**Meals**: no synergy with
the solver/logistics DNA; at most a calendar concern."*

That reason is false, and the codebase disproves it twice:

- `services/trip_scheduler.py` defines `MEAL_BLOCKS` and `MEAL_ANCHOR`
  (breakfast 08:00, lunch 12:00, dinner 18:30), infers a POI's meal type,
  reserves a day's meal slot, and pairs dinner with dessert. That is a
  constraint solver deciding when and where this family eats — already
  shipped, for trips.
- `services/cars.py` (C3, v2.50.0) already does propose-a-stop-on-your-route:
  Mapbox search-along-route → family-channel card → parent approval →
  min-detour errand placement. Retargeting that from fuel to food is close to
  a category-parameter change.

What is *actually* true, and what the cut should have said: **recipe
management and pantry inventory have no synergy.** The cut over-generalized
from that narrow truth to the whole domain, and in doing so it discarded the
one part of feeding a family that only Chauffeur can do.

## The load is in the constraints, not the recipes

Decompose what feeding a family actually costs:

1. The nightly decision — *what's for dinner* — highest frequency, highest dread
2. Provisioning — getting the ingredients into the house
3. Repertoire — what we even make
4. Acquisition — cooking it, ordering it, or both
5. The constraint layer — who's where, when, and what can be eaten there

**#5 is the entire reason #1 is hard, and Chauffeur is the only app in the
house that owns #5.** At 4pm the blocker is not a shortage of recipes. It is
that practice ends at 7:15, a parent is on pickup until 6:40, two kids eat in
the car at 5:10 and the rest eat at home at 7:30 — so the real question is
what can be *made in pieces before 3:40, packed in three containers, and
eaten with a fork in a moving car*. Mealie cannot know that. AnyList cannot
know that. The solver already does.

This also explains why weekly meal planners fail, and they fail *for the exact
reason this app exists*: a Sunday plan is a static artifact fighting a schedule
that mutates by Tuesday. Chauffeur's thesis is that the schedule is dynamic and
must be re-solved. So the version this app should build is the **nightly** one
— precisely what weekly planners are worst at. This is not meal-planning-lite;
it is meal planning done the way Chauffeur does everything else.

## Design principles (argue before violating)

1. **Own the constraint layer, bridge the content.** Chauffeur computes
   feasibility, timing, and routing. It does not become a recipe box. The
   commodity 60% of this domain (recipe storage, nutrition, scaling) belongs
   to Mealie / Tandoor / Grocy, all of which have real APIs and HA
   integrations. Same bridge-not-build principle the roadmap applies to movies.
2. **Never claim to know what is in the house.** Every pantry app dies on
   inventory maintenance. Nothing in this arc may require a human to log
   consumption. A photo of a fridge shelf answers "what should I add to the
   list," which is *not* the same as maintained inventory state — do not let
   the first quietly become a claim to the second.
3. **Nightly, not weekly.** Suggestions are derived fresh from the solved
   schedule. No stored multi-week plan.
4. **Zero-cost actions do not need approval.** The proposal queue exists for
   things that consume family time (events, errands, drives). Adding "milk" to
   a list costs nothing, so it lands directly with attribution — including from
   kids. (Revises the initial sketch, which routed kid capture through the K3
   propose→approve cards; that is friction with no gate value.)
5. **Household norms are settings, never constants.** The first draft of this
   brief hardcoded "in-car means one hand, no utensils, nothing messy." This
   family eats **full meals with utensils in the car**; other families will not
   eat in the car at all. Anything that encodes how a family *ought* to eat is
   a config field with a permissive default. See §Settings.
6. **Do not become a taskmaster.** Emitting "start rice at 3:40, pack two at
   4:50" every single day is a stream of orders, and the promise is removing
   load, not issuing it. Surface the plan only when the day is genuinely
   constrained. Silence on an ordinary day is a feature.
7. **Schedule what the family decides to eat; never grade it.** No spend
   tracking, no takeout-frequency counters, no nutrition scoring. The calm-voice
   principle from the kid arc applies to adults here.
8. **Read-only against schedule state.** This arc *derives* from solver output
   and must never write, reset, or persist itinerary/schedule state — the same
   discipline the trip scheduler ownership rule enforces.

## Build order

**M1 → M2 → M3.** M1 is self-contained and is what the family asked for. M2 is
the moat and the centerpiece. M3 is only worth much once M2 exists to filter
it — though M2 stands alone with an empty repertoire.

---

## M1 — The shopping list (provisioning)

The list is a commodity; the **bindings** are the product. Build the list thin
and the bindings thick.

What makes it Chauffeur and not AnyList:
- It attaches to the recurring grocery **errand** the solver places, which
  already carries `location` and `window_days` (`models/schemas.py` `Errand`).
- **The person who notices is not the person who shops.** A kid says "we're
  out of cereal" and it lands on the list of whoever the solver assigns
  Thursday. No standalone list app can close that loop.
- Completing the errand and completing the list are the same act.

### Schema (new entities — not fields on `Errand`)

The list **outlives any single errand instance**: a recurring grocery errand
regenerates, the standing list does not. Binding by `errand_id` would be
backwards and painful later — bind by tag/location instead.

```
ShoppingList:  id, doc_id, name="Groceries", store (display name, matches
               Errand.location), errand_tag (binds to the recurring errand
               via Errand.tags), is_default, created_at

ShoppingItem:  id, doc_id, list_id, name, qty (FREE TEXT "2 lbs" — units are
               deliberately not parsed), note, added_by (member id),
               added_via ('manual'|'voice'|'photo'|'meal'|'barcode'),
               source_meal_id, is_checked, checked_at, checked_by, created_at
```

### Concurrency — this is the app's first shared mutable document

Everything else in Chauffeur is single-writer. Two people at the store, or one
adding while another shops, is the normal case. The answer: **items are
individually addressable; there is no whole-list PUT.** Check/uncheck are
idempotent per-item PATCHes, so last-write-wins per item is correct rather
than lossy. Broadcast item deltas over the existing SSE stream.

### Capture

- **Voice/text — build first, ~80% of the value at ~10% of the cost.** Tools
  in *both* agent stacks (`agent_router`/`agent_tools_v2` for the widget, plus
  the older `agent_tools`): `add_shopping_items`, `list_shopping_items`,
  `check_shopping_item`, `remove_shopping_item`.
- **Photo — cheap, but aim it correctly.** The vision tier already exists
  (`model_pools.py` `'vision': ['flash','lite']`) and `/api/ingest/photo` is a
  working template. Photographing an item you are *holding* is worse than
  saying its name. Photo earns its place on shots voice cannot do: the open
  fridge shelf, the pile of empty packages, a handwritten list on the counter.
- **Barcode — deferred, and the deferral is a sequencing win.** The lookup is
  solved: Open Food Facts is free, open-data, needs no key (two gotchas: an
  unknown barcode returns HTTP 200 with `"status":0`, so parse the payload not
  the status code; send a descriptive User-Agent). The *scanning* is the hard
  part — `BarcodeDetector` is implemented in no browser on iOS and Apple shows
  no sign of moving, so on this family's phones it means shipping a WASM
  decoder plus camera-stream handling. Most work, narrowest coverage (no
  produce, no bulk, spotty on US store brands), for the interaction where
  voice is already nearly as good. **The native-app track makes this free** —
  Capacitor gets native ML Kit barcode scanning as a plugin. Waiting turns the
  most expensive capture path into the cheapest.

### Store dimension

One flat list breaks the moment there is Costco *and* the regular store. Items
route to a list, lists carry a `store` that maps onto the errand's `location`.
Multi-store is v1 schema, but the UI may ship single-store first.

### Ordered meals do not generate list items

An M3 entry with `source='ordered'` contributes nothing to the grocery list.
Hybrid entries contribute only their prepped components. The "add to list"
path must branch on source or it will dump a vendor's menu into groceries.

### Later: threshold → errand

The interesting version, once M1 is real: the list crosses N items, or gains
something urgent, and **proposes a grocery run** into the existing proposal
queue (`/api/proposals`). That is the app doing the noticing, and it is the
version nobody else can ship. Not v1.

---

## M2 — The day's eating plan (the moat)

Not "the dinner window." Eating is **per-person and all-day**: production
scattered through the day, consumption distributed across cars, venues, and
home. The household-cooks-at-6pm model is the degenerate case where everyone
happens to be home.

This is squarely solver ground. Eating competes for exactly the resources the
solver already allocates — gaps in the day and seats in cars — and the solver
already knows every leg, every manifest, and every gap between them.

### The primitive: eating slots

Per person, per day, derived read-only from solver output. Each slot carries a
**modality**:

- `at_home` — anything goes
- `in_car` — bounded by the family's `car_dining` setting, not by assumption
- `at_venue` — the bleachers gap while a sibling practices

**Passengers can eat during a leg; the driver cannot.** The manifest gives
this for free, and it is the structural reason the driving parent is the one
who does not eat: their only slots are the gaps *between* legs (waiting at a
venue, or time at home), while everyone they are driving has the whole ride.

**Emit spans, not timestamps.** "Between drop-off and about 5:30, roughly 20
minutes" is honest; "eats at 5:10" claims precision the schedule does not have.
The app is already careful this way about unassigned rides.

### The driver's slot is a first-class output

Finding it matters. So does failing to find it: **"no feasible slot for
anyone" is a real finding**, and it is the honest trigger for suggesting food
on the route — far better than a clock heuristic. The late-and-nothing-fits
case is one branch of this phase, not a separate feature.

### Packing — the surface already exists

`services/prep_kits.py` is exactly this concept: rule-filtered packing lists
that surface on **My Day ride cards and the tomorrow digest**, so the "what do
we need to bring" scramble happens once at setup instead of before every
departure. A packed meal is the same idea with a count.

**But do not build it as a kit rule.** Kits are static (soccer → shin guards,
always). A packed meal is dynamic: the count depends on who is actually riding
that leg today, and the item depends on what got made. So it is a **computed
item injected into the kit surfaces**, read off the solver's manifest rather
than matched by a rule. Reuse the surface and the concept, not the rule engine.
Reading the manifest is also what makes "pack 3" trustworthy — it is the same
manifest that assigned the seats.

### Prep placement

`prep_ahead_mins` (see M3) is itself a schedulable object: detachable work that
can land in **any** earlier gap, including the morning. This is what makes
"Chauffeur schedules the meal" literally true rather than a slogan.

`needs_ahead` (thaw/marinate) creates a **morning** touchpoint on a surface
that already exists — K5's launch line. *"Tonight's window is 25 minutes — put
the chicken out now."* Zero-cost, high-value, and structurally unavailable to
anything that does not know tonight's schedule at 7am.

### Routing: pickup and delivery

An ordered or hybrid meal is a routing problem, which is the C3 machinery
again — vendor location, min-detour insertion into legs the solver already
computed, approval card, errand placement.

- **Pickup** inserts a waypoint into an existing route, respecting
  `order_lead_mins` so the order is placed early enough.
- **Delivery is a presence constraint the solver can check.** Delivery needs
  someone home in a window; Chauffeur knows nobody is home 6:00–6:40 and can
  say so. No food app can tell you that.

### Surfaces

Evening digest + kiosk (kid-arc principle: one digest, not N pings), plus the
computed packing items on My Day ride cards. Per principle 6, all of it stays
silent on an unconstrained day.

---

## M3 — The repertoire (fit, not method)

A repertoire is **not a small recipe collection**. A recipe answers *how do I
make this*; a repertoire entry answers *can we have this today* — a scheduling
question, and the only kind Chauffeur should store. Nobody here reads
instructions to make tacos.

```
Meal: id, doc_id, name,

      # timing — four numbers, never steps
      prep_ahead_mins,      # detachable work, schedulable into ANY earlier gap
      finish_mins,          # must happen near eating
      unattended_mins,      # oven/slow cooker; someone present at start + end
      needs_ahead,          # none|thaw|marinate|slow_cooker — lead time, not work

      # place and persistence
      holds_well: bool,     # survives split service and reheats
      portability,          # none|handheld|utensils_ok — matched against modality

      # acquisition
      source,               # prep|ordered|hybrid
      vendor, vendor_location, order_lead_mins,
      fulfillment,          # pickup|delivery

      effort,               # easy|normal|project — Thursday 9pm is not Sunday
      serves, tags,
      ingredients: [{name, kind: staple|fresh}],
      notes, link,          # the Mealie on-ramp, and the twice-a-year meal
      last_served_at, is_active
```

**Why `cook_mins` was wrong.** One number cannot express the most common shape
of a real weeknight: a 90-minute roast with 8 minutes hands-on is *ideal* when
a parent is home 4:30–6:00, while a 25-minute stir-fry that is 25 minutes at
the stove is impossible on that same night.

**Ordered is ordinary.** "Thursday is pizza from the usual place" is a planned
meal that happens to need a stop, not an emergency. Hybrid is the case that
proves the model — rotisserie chicken picked up on the way plus a salad made
at home: the pickup lands on someone's legs, the salad drops into an earlier
gap, and both must complete before the first eating slot.

**No steps, ever.** That is the line between this and a recipe box. `notes`
and `link` cover the twice-a-year meal nobody remembers.

### Staples versus fresh — inventory's value without inventory

The reason people want inventory is one question: *can we do this today
without a store run?* Classify ingredients instead of tracking them —
**staples** (rice, oil, spices; assumed present) versus **fresh** (must be
bought within days). Only fresh lines matter, for both M1 and feasibility.
This classification is a property of the dish, stable forever, so there is
nothing to maintain and nothing to rot. Do not track state; track item class.

### Population is where this phase dies if it dies

Nobody fills in fifteen meals on a form with twelve fields. **The human
supplies the name; the model supplies the metadata.** "We had tacos" → the LLM
proposes 20 minutes, mostly finish-time, holds well, utensils_ok, serves 4,
fresh = beef/tortillas/cilantro, staples = the spices. The family corrects with
a tap. Seeding is a conversation with the agent ("name five things you make on
a weeknight"), not a page of forms. Entry cost must be one sentence.

`last_served_at` is set where attention already is: the evening surface that
suggested the meal offers a one-tap "we had this." Rotation maintains itself
or it does not get maintained.

### Dietary constraints

*Assumption recorded 2026-08-05 — not explicitly confirmed by the family.*
Model on `FamilyMember` (Config → People is the natural home), mirroring the
solver's own hard/soft grammar: **allergies are hard** (a meal tagged with an
eater's avoid-tag is filtered out entirely), **preferences are soft** (picky
tags demote in ranking, never remove).

### Shape as UI

Not a browsable page — a **filter result inside the evening digest** ("3 of
yours fit today"). An editor exists only for corrections. If people start
browsing it, it has become a recipe box and failed. Size is deliberately small,
roughly 15–25; past ~30 the filter stops being decisive. Small-data feature;
do not optimize for scale.

### Build thin rather than bridge — for now

Mealie/Tandoor/Grocy are the right answer for recipes as *content* and the
wrong answer for the twenty rows that make M2 useful: the integration is larger
than the table. Build thin, leave a **Mealie import** as the later on-ramp.

---

## Settings (Config → General)

```
car_dining:    none | snack | handheld | full     # this family: full
venue_dining:  none | snack | handheld | full
```

**Default permissive; let families restrict.** A wrong permission produces a
visible bad suggestion someone corrects in seconds. A wrong restriction
silently hides slots, and the family concludes the feature is useless without
learning why. Invisible failures are worse. `none` is meaningful — it disables
that modality's slots wholesale.

Also expected: an opt-in toggle and a once-per-day cap on the route-food
suggestion, matching C3's pattern.

## Explicitly cut — with reasons that actually hold

- **Pantry / fridge inventory.** Fails on maintenance, always; and nothing in
  M1–M3 needs it. This is the real content of the original "meals" cut.
- **Recipe-site ingestion (URL or photo).** Permanent maintenance against
  changing layouts and paywalls; needs structured quantity/unit parsing to be
  useful; and it feeds the weakest link. The vision tier makes it *look* cheap.
- **Multi-week meal plans.** Static artifact versus dynamic schedule.
- **Cost/spend tracking and takeout-frequency counters.** The roadmap already
  cut currency integration, and a "you ordered out four times this week"
  counter is the app forming an opinion about the family's choices (principle
  7). Ordered meals are scheduled, not scored.
- **Nutrition tracking / calories.** Different app, different family
  relationship with food.

## Open questions

- Who counts as "cooking-capable" for prep placement — a role flag on
  FamilyMember, or every adult by default?
- Does the route-food suggestion write an errand (C3 behavior) or stay
  informational? An errand implies the solver may re-place it, which may be
  wrong for a stop that only makes sense *now*.
- Does the shopping list want a kiosk surface, or is it phone-only? The person
  at the store is by definition not at the wall panel.
- Multi-store UI in v1, or schema-only with a single visible list?
- Does an eating slot need a *minimum* length setting, or is "any gap over ~10
  minutes" good enough for every family?
- When a packed meal is computed for a leg, who is accountable for actually
  packing it — the driver, or the person doing the prep? Affects which My Day
  card it lands on.

## Tests when built

M1: list/item CRUD both storage backends, per-item concurrency, tag-binding to
a regenerated recurring errand. M2: slot derivation across a split-service day,
driver-has-no-slot detection, packing counts against a manifest, `car_dining`
settings gating in-car slots, delivery-presence refusal. M3: window filtering,
hard allergy exclusion versus soft demotion, hybrid timing reconciliation.
