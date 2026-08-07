# Occasions Arc — design brief (drafted 2026-08-06)

The gap, in the family's words: mental-load research keeps naming the same
cluster — **holidays and birthdays: the meals, the gifts, the guests, the
travel, the errands** — and Chauffeur handles every one of those pieces
individually while helping with none of them *as the thing they belong to*.

The load here is not storage and it is not visibility. It is **planning**:
figuring out what to feed sixteen people, what a shark-themed party needs,
where the folding chairs come from, what has to be bought by when, and who is
doing all of it. That is generative work, and it is the part no checklist app
touches.

> **Naming.** "Holiday" was the starting word and it is wrong twice: it does
> not cover birthdays, graduations, anniversaries, or first-day-of-school
> (which are most instances), and in British English a holiday *is* a
> vacation, which is `Trip` — an entity that already exists and would be
> nested inside this one. **Occasion** throughout.

## What this brief argued out (read before relitigating)

This design survived a deliberate teardown. The conclusions that cost the most
to reach, so they are not casually reversed:

**1. The container is not the feature, and it must not be the system of
record.** The original pitch was a Holidays section that things live *inside*.
Every capability named — meals, lists, errands, travel — already has a working
home, a working capture path, and a working engine. A container that *owns*
copies of those records is a second write path and a drift surface, and it is
empty until a parent fills it in by hand, which is the mental load relocated
into a form. The roadmap's own bar, from the intake arc: *must be genuinely
one-tap or it is data entry with extra steps.*

**2. But a 30,000-ft view is fine, because derivation is not ownership.** A
read-only rollup over entities tagged with the occasion has none of the
properties above. Build it. See §O2 for the one thing it must be (a diff, not
a list).

**3. Why Trips gets to be a container and Occasions does not.** `TripPOI`,
`TripAccommodation`, `TripFlight`, and `TripRule` have no home outside a trip
— the container *constructs* the only place they can live, and there is a real
solve (`schedule_pois_bulk`) that needs it as an input surface. An occasion
*borrows*: errands, lists, plates, and events are all fully meaningful without
it. The test to apply to anything proposed for this arc: **does the content
exist independently?** If yes, tag it; do not own it.

  Trips is also the cautionary half of that comparison — ~8,400 lines across
  three services and three templates, 144 commits, thirteen abandoned
  `trip_planner_hacked*.py` snapshots, and two standing rules that exist only
  because it regressed. It bought its container with a solver. This arc has
  exactly one candidate solve (§O0) and it lives in meals, not here.

**4. Membership attaches to the coarsest entity the occasion wholly owns.**
An earlier draft put an occasion tag on individual items and invented a
two-writer problem that does not exist: if a shopping list belongs to the
shark party, an item added to it belongs to the party regardless of which page
the parent was standing on. Tag the *list*, the *trip*, the *errand*, the
*guest*. Plates need no tag at all — the occasion window is a date range and
the nightly derivation is already keyed by date.

  The single exception, and the reason `ShoppingItem.occasion_id` exists in
  §O1: the **standing grocery list** is a container the occasion owns only
  *part of*. The turkey wants to be on the normal list, bought on the normal
  run, at the normal store — everything downstream in `services/shopping.py`
  and `walmart.cart_for_list()` is keyed per-list, so a separate Thanksgiving
  list means a second errand and a second cart, and in practice it rots while
  the family puts the turkey on the main list anyway. Precedent for the fix
  already shipped: `ShoppingItem.source_meal_id` records *why an item is
  there* without the list belonging to the meal.

**5. The frequency objection, and why it lost.** This looked like the app's
first low-frequency surface — 12 occasions a year against a codebase whose
every win is daily or weekly. Counting parties, get-togethers, and any hosting
night alongside birthdays and holidays, it is 15–20, and the expensive
machinery (§O0) is exercised at every one. That is a different investment case
than "Thanksgiving and Christmas." The objection is not dead, though: see
§Risks.

## Design principles (argue before violating)

1. **The occasion is a context object, not a hub.** Every capability takes it
   as a *parameter*: "shark party" is context for list generation, "sixteen
   people Thursday" is context for the kitchen solve, "Thanksgiving week" is
   context for a dish pool. It exists to be passed in, not browsed.
2. **Planning is conversational; the write path is the thread.** Nobody fills
   in an occasion form. They say what is happening and answer questions, and
   the artifacts land in their existing homes already tagged. This is what
   kills the empty-container problem, and it is why the arc leans on the two
   agent stacks rather than a page of sub-forms.
3. **Tag the coarsest wholly-owned entity.** Principle 4 above, restated as a
   build rule. When tempted to add an `occasion_id` to something, first check
   whether its container could carry it instead.
4. **Never own what already has a home.** No occasion-local copies of errands,
   items, plates, or events. The rollup derives; it does not store.
5. **A view that cannot show an absence must not imply completeness.** §O2.
6. **Eligibility is not selection.** An occasion window makes holiday dishes
   *available*; a specific plate is what *chooses* them. Thanksgiving week is
   Wednesday to Sunday and exactly one meal in it is The Meal — Friday lunch is
   sandwiches. A window that swaps the pool wholesale proposes turkey for four
   days.
7. **Occasion days are invisible to ordinary rule accounting.** Not merely
   given extra rules — *excluded from the bookkeeping of the standing ones*.
8. **Do not become a taskmaster** (inherited from the meals arc, and it bites
   harder here). An occasion is a stressful time already. The app's job is to
   remove decisions, not to issue a stream of orders with a countdown.
9. **Read-only against schedule state** (inherited): this arc derives from
   solver output and never writes, resets, or persists itinerary state.

## Build order

**O0 → O1 → O2 → O3**, and O0 deliberately ships *without an occasion object
existing at all.*

O0 is the hard, expensive engineering; it stands alone; it is exercised by
every party and every hosting night; and it is the honest test of the whole
arc. If the family reaches for "we are having twelve people Saturday," the
occasion becomes a thin wrapper over proven machinery. If they do not, that
was learned for the price of one feature instead of an arc.

O3 is where this becomes *planning* help rather than logistics help — and it
is therefore the part most likely to be cut when the build runs long. Cutting
it ships a very good checklist, which is the specific failure this arc exists
to avoid.

---

## O0 — Cooking for a crowd (no occasion object)

### The kitchen is a resource model, and one already exists

`_totals_from_dishes()` ([meals.py](../services/meals.py) ~L1710) sums
`prep_ahead_mins` and `finish_mins` and takes the **max** of
`unattended_mins`, with the reasoning stated in its own docstring: *"Hands-on
time SUMS (one cook, one pair of hands) while unattended time takes the MAX
(the oven runs while the rice sits)."*

That is already a resource model. It has exactly two resources with hardcoded
capacities: **cook = 1** and **unattended equipment = ∞**. Both constants
invert at once the moment the family hosts — more hands are available, and
equipment becomes the binding constraint.

Where it is wrong today, in order of severity:

- **`unattended = max` assumes infinite oven.** Two dishes at 350° for 45
  minutes report 45 and take 90 if they do not share a rack. Two dishes at
  *different* temperatures cannot share an oven at any capacity — temperature
  is a harder constraint than space and the one people forget.
- **`finish = sum` assumes one cook.** "Can I help in the kitchen" is the
  defining feature of hosting.
- **Burners are not modeled at all.**

On a weeknight the errors cancel: one cook serializing everything means burner
contention rarely surfaces, and the optimistic oven number costs nothing
because `unattended_mins` deliberately does not count against the cook window
([meals.py](../services/meals.py) ~L521) — it gates nothing. The existing
error is real and currently harmless. It stops being harmless at twelve
people.

### Model three resources, not a kitchen inventory

Do **not** model pots and pans. Most tedious axis to maintain, least binding —
families own enough of most things.

New settings (Config → General, "🍳 Kitchen"):

| key | default | note |
|---|---|---|
| `kitchen_ovens` | 1 | |
| `kitchen_burners` | 4 | |
| `kitchen_cooks` | 1 | the everyday default; a plate may override |

New fields on `Dish`:

| field | type | note |
|---|---|---|
| `equipment` | `none\|oven\|burner` | what the dish occupies while cooking |
| `oven_temp_f` | `int?` | oven dishes only; equality is what allows sharing |
| `servings` | `int` | what the stored times and ingredients assume |

New field on the plate: `scale_servings` (nullable; absent = everyday).

### The solve

Classic cumulative-resource scheduling converging on a fixed serve time:
`AddCumulative` for cooks and burners, `AddNoOverlap` plus a
temperature-equality condition for oven sharing. CP-SAT is already a
dependency in two places; ten to twenty dishes solves instantly. It is rare
for a capability to need no new infrastructure — this one genuinely does not.

**Single path, not a second one.** Replace sum/max rather than bolting the
solve alongside it. Two code paths computing the same quantity differently is
worse than either alone, and the meals arc is two days old — nothing has
calcified. The property to hold is **reduction**: with one cook, one oven, and
no temperature conflicts, the solve must return exactly what sum/max returns
today. That is a test, not a hope. Where it does *not* reduce (two oven dishes
at different temps), sum/max is the one that was wrong.

Not a trust concern but a real one: `meal_fits_window()` gates which meals are
*offered*, so changed numbers change behaviour, not just display. Re-verify
the repertoire filter and update the assertions in `tests/test_meals.py`.

### Output is a run-sheet, not a Gantt chart

"Turkey in at 11:40. Potatoes in at 4:15, when the turkey comes out to rest."
Emit the solve as **timed `PrepStep`s** — that entity already fires the
reminders, and reminders are the whole payoff. Same move M2 made: reuse the
surface, do not build a new one.

### Dish scope — holiday food does not belong in the Tuesday pool

From the family: the food eaten at holidays and parties is not the food eaten
day to day. Some overlap, but keeping turkey and stuffing in the standing pool
just so they exist twice a year pollutes every picker for the other fifty
weeks.

**Two fields, not one** — and the overlap case is the proof they must be
separate. Mashed potatoes are everyday *and* Thanksgiving; one field cannot
say both.

- **`Dish.scope`** — `everyday | occasion`, default `everyday`. Controls
  eligibility in the composer and the default filter in every dish list.
- **`Dish.tags`** — already exists, already selectable by `MealRule`. Carries
  *which* occasion. Occasion templates name tags.

`is_active` stays what it is: retired, not seasonal.

**Not a new `MealRule` kind.** `MealRule` is deliberately two kinds
(`frequency_cap`, `batch_cycle`) and both are *rhythms*. "Turkey is not a
Tuesday food" is a property of a dish, and routing it through the rule engine
turns a narrow, listable, boring thing into the general predicate language its
docstring explicitly refuses to be.

### Four traps in the scope filter

1. **Leftovers must bypass it — this is the one that breaks the feature if
   missed.** Turkey is `scope: occasion`, and 27–29 November is precisely when
   it must appear on ordinary plates. Filter naively in `_dish_ok()` and the
   dish is blocked from the days it exists to cover. The precedent is already
   in that function: leftovers skip the portability check
   ([meals.py](../services/meals.py) ~L574 — *"it exists, and it is going in a
   container either way"*). **Scope gates proposal, never presence.**
2. **Occasion days must be excluded from rule accounting.** Otherwise the
   turkey burns the week's "meat about once a week" cap and the family gets a
   baffling vegetarian weekend, and a `batch_cycle` advances on a day that had
   no beans in it. Adding rules for the window is the easy half.
3. **Eligibility ≠ selection** (principle 6). The window makes occasion dishes
   available across it; `set_plate_lock` chooses them one plate at a time,
   which is the job it already does.
4. **Recency is already safe — know why before touching it.** `_rank()` caps
   the staleness bonus at 21 days ([meals.py](../services/meals.py) ~L837), so
   a dish served once a year scores the same `+1.0` as one served three weeks
   ago rather than dominating the pool. The only residual is that recency stops
   discriminating *among* occasion dishes; they tie at the ceiling. Harmless —
   an occasion plate is hand-composed anyway.

### Where twenty holiday dishes come from

The same problem M3 already had, and the same answer: a repertoire barely
reaches fifteen entries when a human types them. The occasion **template** is
the capture path — "Thanksgiving usually has turkey, stuffing, green bean
casserole, cranberry sauce, rolls, pie…" → a one-tap multi-select of which are
actually yours → LLM fills timings, equipment, temp, servings, and
ingredients, with `needs_detail` catching whatever it had to guess. That is
M1's staged-candidate picker and M4's metadata fill, reused. The first
Thanksgiving populates the pool every later one inherits.

---

## O1 — The occasion as context

### Schema

```
Occasion:
  id, doc_id
  title                 "Thanksgiving 2026", "Ellie's 8th"
  type                  free text + template key ('thanksgiving', 'kid_party', …)
  anchor_date           YYYY-MM-DD — the day the thing happens
  window_start/_end     YYYY-MM-DD — guests in the house, prep, travel
  dish_tags[]           which repertoire tags this occasion activates
  cooks                 override for kitchen_cooks during the window
  headcount             derived from guests, overridable
  template_id           what generated it; also what O2 diffs against
  prior_occasion_id     last year's instance — the carryover link
  status                planning | active | done
  thread_channel_id     the planning conversation
  created_at
```

```
OccasionGuest:
  id, doc_id, occasion_id
  name, member_id?          (family members link; others are just names)
  headcount        int      "the Wilsons, 4"
  dietary_avoid[]  dietary_dislike[]   same grammar as FamilyMember
  staying_over     bool
  arrival / departure  optional datetimes → airport runs enter the solver
  notes
```

Membership fields elsewhere, per principle 3: `occasion_id` on
`ShoppingList`, `Errand`, and `TripMetadata`; **`occasion_id` on
`ShoppingItem`** as the documented exception for the standing grocery list
(§argued-out 4). Plates carry nothing — the window is a date range.

### The thread is the interface

A per-occasion channel reusing `ChatChannel`/`ChatMessage`, with the occasion
injected as page context the way trips already are in
[llm.py](../services/llm.py) (~L837, `if 'trip' in path and 'event_id=' in
search`). Everything the parent says in it is scoped: "we need party favors"
generates against `type: kid_party` plus the theme, "who's coming" edits
guests, "add sixteen rolls" lands on the standing grocery list with
`occasion_id` set.

### Sourcing — themed list generation

"Party favors for a shark party" → LLM generates ~12 line items → a
`ShoppingList` owned by the occasion → shipped cart rails (Walmart, Instacart)
carry it the rest of the way. Days of work, no new nouns, and the single
highest value-per-line item in the arc.

Guest dietary constraints flow straight into the meal composer's existing
`_eater_diet()` grammar — allergies hard, preferences soft — which is the
cross-entity payoff that justifies modelling guests at all.

---

## O2 — The template, and the gap report

### The template is an interview, not a checklist

This is the difference between planning help and a form. Each answer
*generates* logistics rather than recording them:

- "How many are coming?" → headcount → scaling → shopping → oven capacity
- "Anyone staying over?" → beds, towels, an errand, a bigger breakfast
- "Who is flying in, and when do they land?" → airport runs into the solver
- "Are we doing gifts for the cousins this year?" → a decision (§O3), and a
  list if the answer is yes

A template is therefore: an ordered question set, a dish-tag set, and a set of
work stamps expressed as **offsets from the anchor** (`anchor − 4d`, etc.).
Errands already express a deadline as `starts_on` + `window_days`, so stamping
is arithmetic against shipped primitives, not new solver work.

### The gap report is a diff, not a list

The stated goal is *"make sure I haven't left anything out or let something
slip."* Those are two queries and a rollup only serves one.

- **"Let something slip"** — a list handles this if it sorts by **slack
  against the anchor**, never by completion, and shows **no percentage**. Six
  of fourteen gifts unchecked is fine in October and an emergency on 23
  December; one number cannot say both.
- **"Left anything out"** — a list *structurally cannot* answer this. It shows
  what someone remembered to add; the gap is invisible by construction. Nine
  tidy green rows manufacture confidence about the exact thing being worried
  about.

So the view's primary content is the **diff against the template and against
`prior_occasion_id`**: *"Last year this had a table-rental line. This year it
does not."* *"You have never done Thanksgiving without a cleaning errand the
day before."* That is the only mechanism that can surface an absence, and it
is what makes carryover load-bearing rather than a nice-to-have.

A second, independent reason the page must not present itself as authoritative
about completeness: **tag decay.** Things created through the thread tag
themselves for free; anything created elsewhere needs a cheap "belongs to →"
affordance and will still be roughly 80% complete in practice.

### It is not only a page

A surface you must remember to open is one you do not open. The gap report
belongs in the weekly family digest
([family_digest.py](../services/family_digest.py), which already carries an
intake section) during an active window, with the page as where you land when
a digest line makes you look. Anticipation belongs in
[watchers.py](../services/watchers.py): *"Thanksgiving is in three weeks. Last
year: twelve people. Start from last year's list?"*

---

## O3 — The planning intelligence (the part that must not be cut)

Everything above is nouns, and every noun is a logistics noun. What makes this
*planning* help is what the app says unprompted, using what only it knows:
where everyone is, who is driving, where the schedule has slack, how this
family cooks, and what happened last year.

**1. Model the load distribution, not just the tasks.** The research this arc
came from is about *who carries it*. The app has roles, assignment, and a
chore ledger. An occasion whose open items are eleven-of-fourteen on one
parent should say so, out loud, in the digest. Every other product in this
space ships a shared checklist and calls that equity. Naming the imbalance is
the actual intervention and Chauffeur is the only thing in the house with the
data to name it. (Calm voice, per the kid arc: name it, never score it.)

**2. Make the undecided visible.** Anticipate → identify → **decide** →
monitor; the first three are covered above and the fourth is where couples
actually stall. *Are we hosting or driving to Mom's? Cousin gifts this year?*
Model open decisions as **blockers with a cost that grows**: "deciding after
the 14th means no delivery slot, and the turkey will not thaw in time." The
app cannot decide. Making the price of not deciding concrete is most of the
value.

**3. Schedule-aware deadline placement.** Not "buy gifts by the 20th" but
"the only two-hour block where you are both free before the 20th is Saturday
the 13th — and there is a meet on the 6th." The solver already knows the
slack. This is the app's DNA pointed at a new problem and no checklist can
do it.

**4. Deadlines derived from dishes, not typed by humans.** `needs_ahead:
thaw` plus a twenty-pound bird is four days in the fridge, so the *buy* date
computes backward from the *serve* date. Same for `order_lead_mins` on
anything ordered. Nobody types that deadline; it falls out of the meal model.

**5. Conflict detection against the real calendar.** "You are hosting sixteen
at 2pm Saturday and you are on pickup for a game that ends at 1." Trivial
here, invisible to every list app.

**6. Outcome capture, so year N+1 beats year N.** "Three pies last year, one
came back untouched" → suggest two. Requires recording outcomes, which nothing
currently does. Lowest priority in O3, highest compounding value.

---

## Explicitly cut — with reasons that hold

- **Local dated-event discovery** ("what is on that weekend"). The trip
  pipeline is LLM-proposes → Mapbox-verifies, and its categories
  (`sightseeing|food|activity|shopping|other`) are all **places**. That works
  in Bergen because the answer is a place, famous places are in the model's
  priors, and Mapbox confirms it exists. Localized, you already know the
  trampoline park; what you want is the tree lighting and the craft fair —
  *dated, hyperlocal happenings* that are in neither the priors nor Mapbox,
  and there is no live web search anywhere in the LLM stack (SerpAPI appears
  only in `travel_api.py`, for flights). Asked cold, the model invents a tree
  lighting with a plausible date, which is the worst possible failure for
  something a family plans around. **Salvage:** seasonal *categories* the
  family forgets exist, framed as "look into this," never as a scheduled item.
- **Rentals and borrowing** (tables and chairs for sixteen). Rental is a
  vendor class with no API, and a reservation lifecycle — reserve, collect,
  return, deposit — that nothing in the app models. Borrowing is the real
  family answer and needs a social graph beyond `FamilyMember`, which the
  one-family-per-install assumption does not provide (still an open roadmap
  question). Both are arcs, and neither is unlocked by an occasion.
- **Sending invitations.** Non-member contacts, an outbound SMS/email sender,
  deliverability, RSVP tracking, opt-outs — every message path in the app
  today is internal. Highest cost, least differentiated, and a group text and
  Evite already work. **The guest list is kept; the sending is not.**
- **Spend tracking / budgets.** Holidays are the most money-heavy thing a
  family does, which is exactly why a half-modelled version is worse than
  none, and money mapping is already cut on purpose. Trips keep their own
  `budget_min_usd`/`budget_max_usd`; occasions get nothing.
- **Pots, pans, and kitchen inventory** (§O0). Most tedious to maintain, least
  binding.
- **An occasion-owned copy of anything.** Principle 4. If it needs a home, it
  has one.

## Risks

- **O3 is the arc.** O0–O2 without it is a very good checklist with a good
  kitchen solver attached — the specific outcome this brief exists to avoid.
  If the budget runs out, ship less of O2, not less of O3.
- **Frequency is still the quiet killer.** 15–20 uses a year is defensible for
  O0 (every party exercises it) and thin for a *page*. This is the strongest
  argument for the digest/watcher surfaces over the page, and for O0 shipping
  standalone as the test.
- **The template is the whole carryover story** and it is the piece most
  likely to be deferred as "we can add templates later." Later means the first
  two Thanksgivings teach the system nothing.
- **Gift secrecy is unsolved and deliberately not in this brief.** Every list
  in the app is visible to everyone and several render on kitchen kiosks;
  `ShoppingItem` has attribution but no visibility scoping, and PINs currently
  protect identity switching and point payouts only. A gift list is the app's
  first entity that must be *hidden from specific family members*, and getting
  it wrong is not a bug report. Either gifts stay out of the arc, or
  `hidden_from` gets designed first and enforced at storage, on every list
  surface, in the digest, on the kiosk, and in both agent stacks. Do not let
  it arrive as a late "we should also track gifts."

## Open questions

- Does an occasion ever own more than one trip (in-laws 22–26 Dec, then
  skiing 27–30)? Current answer: yes, `TripMetadata.occasion_id` is many-to-one
  and the occasion's window spans both. Verify no date authority is implied.
- Recurring occasion *definition* vs dated *instance*: this brief models one
  entity plus `prior_occasion_id`, betting the link is enough and a second
  entity is not. Revisit if templates start needing to differ per family
  per year.
- Do occasion dishes need their own `MealRule` scope, or is exclusion from
  ordinary accounting (principle 7) sufficient?
- Where do generated gift/party lists live when the occasion is done —
  archived with it, or dissolved back into the standing lists?

## Tests when built

- `tests/test_kitchen.py` — the **reduction property** first (one cook, one
  oven, no temp conflict → sum/max exactly); then oven capacity, temperature
  conflict, multi-cook parallelism, burner saturation, run-sheet ordering
  against a fixed serve time.
- `tests/test_meals.py` additions — leftover bypasses `scope`, occasion dishes
  absent from everyday composition, occasion days excluded from
  `frequency_cap` and `batch_cycle` accounting, scaling.
- `tests/test_occasions.py` — tag membership at list level, the
  standing-list `occasion_id` exception, gap-report diff against template and
  prior instance (including an item present last year and absent this year),
  slack ordering, guest dietary flow into `_eater_diet`.
