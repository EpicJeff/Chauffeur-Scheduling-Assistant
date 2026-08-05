# Meals & Provisioning Arc — design brief (drafted 2026-08-05)

The gap, in the family's words: **planning meals for a family is a full-time
job unless you want to serve frozen nuggets and fries.** Chauffeur exists to
carry mental load. Feeding people is one of the largest recurring loads in a
household, and until now the app's answer was to declare it out of scope.
That was a scope decision wearing a value judgment's clothes.

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
4. The bail-out — no time, we're in the car, where do we eat
5. The constraint layer — who's home, when, and how long the window really is

**#5 is the entire reason #1 is hard, and Chauffeur is the only app in the
house that owns #5.** At 4pm the blocker is not a shortage of recipes. It is
that practice ends at 7:15, a parent is on pickup until 6:40, four people eat
at 5:30 and two at 7:30 — so the real question is "what survives a 25-minute
window and reheats." Mealie cannot know that. AnyList cannot know that. The
solver already does.

This also explains why weekly meal planners fail, and they fail *for the
exact reason this app exists*: a Sunday plan is a static artifact fighting a
schedule that mutates by Tuesday. Chauffeur's thesis is that the schedule is
dynamic and must be re-solved. So the version this app should build is the
**nightly** one — precisely what weekly planners are worst at. This is not
meal-planning-lite; it is meal planning done the way Chauffeur does
everything else.

## Design principles (argue before violating)

1. **Own the constraint layer, bridge the content.** Chauffeur computes
   feasibility and timing. It does not become a recipe box. The commodity 60%
   of this domain (recipe storage, nutrition, scaling) belongs to Mealie /
   Tandoor / Grocy, all of which have real APIs and HA integrations. Same
   bridge-not-build principle the roadmap applies to movies.
2. **Never claim to know what is in the house.** Every pantry app dies on
   inventory maintenance. Nothing in this arc may require a human to log
   consumption. A photo of a fridge shelf answers "what should I add to the
   list," which is *not* the same as maintained inventory state — do not let
   the first quietly become a claim to the second.
3. **Nightly, not weekly.** Suggestions are derived fresh from the solved
   schedule. No stored multi-week plan.
4. **Zero-cost actions do not need approval.** The proposal queue exists for
   things that consume family time (events, errands, drives). Adding "milk"
   to a list costs nothing, so it lands directly with attribution — including
   from kids. (This revises the initial sketch, which routed kid capture
   through the K3 propose→approve cards; that is friction with no gate value.)
5. **Do not become a nag.** The routine-reminder caution applies. The
   bail-out proposal is opt-in, capped once per day, and silent when the
   evening is not actually squeezed.
6. **Read-only against schedule state.** This arc *derives* from solver
   output and must never write, reset, or persist itinerary/schedule state —
   the same discipline the trip scheduler ownership rule enforces.

## Build order

M1 is self-contained and is what the family actually asked for. M2 is nearly
free because C3 already built the machinery. M3 is the moat and needs the most
new derivation. M4 is only worth anything once M3 exists to filter it.

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

### Later: threshold → errand

The interesting version, once M1 is real: the list crosses N items, or gains
something urgent, and **proposes a grocery run** into the existing proposal
queue (`/api/proposals`). That is the app doing the noticing, and it is the
version nobody else can ship. Not v1.

---

## M2 — The bail-out (route-aware meal stops)

The cheapest high-value item in the arc, because C3 already built it.

`services/cars.py` fuel-stop flow is the template nearly parameter-for-
parameter: `maps.search_category(..., route_coords=coords)` → family-channel
proposal card → approval → min-detour errand placement, with the proximity
fallback for regions where search-along-route is unavailable.

- Swap the `gas_station` category for restaurant/fast-food categories.
- Gate on the meal windows `trip_scheduler.MEAL_ANCHOR` already defines.
- Fire only when the evening is genuinely squeezed: a driver is on the road
  inside a meal window and gets home well after the anchor. Opt-in setting,
  once per day maximum, quiet-hours respected.
- Reuse `dining_style` ('quick'|'casual'|'fine') from `TripPOI` — a squeezed
  Tuesday wants 'quick' and nothing else.

**Honest complication:** a fuel stop is one driver on one route. A dinner stop
must know who is *in the car* versus who is home eating something else. That
is real work — but against data the app already holds (the solver knows the
manifest of every leg). Do not ship this pretending the car is the family.

---

## M3 — The dinner window (the moat)

Derive from the already-solved schedule, per evening:

- each member's home-interval for the evening
- `cook_window_mins` — the largest contiguous span where a cooking-capable
  adult is home before the first sitting
- `eaters` per sitting, and a `split` flag when the family eats in shifts

Surface: a line on the existing **evening digest** and the **kiosk** card. No
new page (kid-arc principle: one digest, not N pings). *Assumption recorded
2026-08-05 — not explicitly confirmed by the family.*

The output converts formless dread into "tonight is 25 minutes, four people,
split service." On most nights that alone decides dinner, because **the
constraint is the decision.** No recipes are required for M3 to be valuable —
this is the piece to build even if M4 never happens.

Strictly a read-only derivation over solver output. It adds no solver
constraints and writes no schedule state (principle 6).

---

## M4 — The repertoire (a thin content layer, not a recipe box)

Ten to twenty meals the family actually makes. That is a small table, and it
turns "what's for dinner" from an act of planning into a filter over tonight's
window.

```
Meal: id, doc_id, name, cook_mins, serves, tags (list), ingredients (list of
      FREE-TEXT lines — no quantity/unit parsing), notes, link,
      last_served_at, is_active
```

- **Filter by M3's window** → "3 of your meals fit tonight."
- **"Add to list"** → M1 items carrying `source_meal_id`.
- **Voice add**, same as list capture.
- `last_served_at` drives rotation so the same thing is not suggested twice
  in a week. This is *not* a stored plan (principle 3).

### Dietary constraints

*Assumption recorded 2026-08-05 — not explicitly confirmed by the family.*
Model on `FamilyMember` (Config → People already exists as the home), mirroring
the solver's own hard/soft constraint grammar:

- **Allergies are hard** — a meal tagged with a member's avoid-tag is filtered
  out entirely whenever that member is eating.
- **Preferences are soft** — picky-eater tags demote a meal in ranking; they
  never remove it.

### Build thin rather than bridge — for now

Mealie/Tandoor/Grocy are the right answer for recipes as *content*. They are
the wrong answer for the twenty rows that make M3 useful: the integration is
larger than the table. Build M4 thin, and leave a **Mealie import as an
on-ramp** if the repertoire ever wants to become a real recipe box.

---

## Explicitly cut — with reasons that actually hold

- **Pantry / fridge inventory.** Fails on maintenance, always; and nothing in
  M1–M4 needs it. This is the real content of the original "meals" cut.
- **Recipe-site ingestion (URL or photo).** Permanent maintenance against
  changing layouts and paywalls; needs structured quantity/unit parsing to be
  useful; and it feeds the weakest link in the chain. The vision pipeline
  makes it *look* cheap. It is not.
- **Multi-week meal plans.** The static-artifact-versus-dynamic-schedule
  failure above.
- **Nutrition tracking / calories.** Different app, different family
  relationship with food. Out.

## Open questions

- Who counts as "cooking-capable" for M3's window — a role flag on
  FamilyMember, or every adult by default?
- Does M2's proposal write an errand (C3 behavior) or stay informational? An
  errand implies the solver may re-place it, which may be wrong for a stop
  that only makes sense *now*.
- Does the shopping list want a kiosk surface, or is it phone-only? The person
  at the store is by definition not at the wall panel.
- Multi-store UI in v1, or schema-only with a single visible list?
