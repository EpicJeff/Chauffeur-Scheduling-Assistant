# M6 — The week ahead

*Meals & provisioning arc, slice 6. Sibling of `meal_design.md` (M1–M5).*

## Why

M1–M5 answered **"what's for dinner tonight?"** well. It turns out that is the
smaller half of the problem. From the family:

> A large part of the mental load related to meals is planning the meals and
> making sure you have the groceries necessary. If you don't know what the
> meals are until the day of, you cannot plan or do any of the stuff you
> mentioned.

They are right, and the existing design made the useful half impossible. Same-day
composition can tell you what to cook with what you have; it cannot tell you what
to **buy**, because buying happens days before eating.

The routine being replaced is a real one, and stated plainly:

> We have historically found a day and time that works well for getting
> groceries so we plan our meals for the week a day or two before that so we
> have a solid list of what to buy for the week. That is the thing we need to
> replace with "how does this look?" approve or edit. Chauffeur takes care of
> the rest.

That sentence is the whole specification.

### On the earlier objection

M5 recorded a stated objection to "meal planning". That objection was to
**mandatory nightly assembly** — being made to build dinner in an app every
evening, which would add load rather than remove it. Planning a week ahead is the
opposite: it is one sitting that removes seven decisions and produces the shopping
list as a by-product. The objection stands where it was aimed and does not apply
here.

## The one bug that made it impossible

`_rank` scored recency as `(_now_ts() - last_served_at)` — wall-clock *now*,
regardless of which day was being composed. `last_served_at` only moves when a
meal is really marked served. So composing seven future days ranked all seven
against identical values and returned **the same top entree seven times**. This
was not a missing view; it was a ranking flaw that made any horizon meaningless.

Two changes fix it:

1. **`_as_of_ts(date)`** — a plate is ranked from midnight of *its own* date.
2. **The `served` overlay** — `compose_week` walks days in order carrying
   `{dish_id: when an earlier day in this horizon took it}`. Taking a dish on
   Monday pushes it down Tuesday's ranking exactly as really serving it would.

Measured on a 7-entree repertoire: **7/7 distinct entrees** with the overlay,
**1/7** without. `scenario_a_week_does_not_repeat_the_same_dinner` asserts both
halves, so the failure mode cannot silently return.

## The window is the shop, not "seven days"

Families do not plan "the next 7 days from whenever the page was opened". They
plan **up to the next grocery run** and buy for that span. So the horizon is
derived, not fixed (`plan_window`):

| Condition | Mode | Window |
|---|---|---|
| within `grocery_plan_lead_days` of the shop | `planning` | shop day → +6 (what this trip must cover) |
| otherwise | `current` | today → day before the next shop (what is left of what was already bought for) |

Settings (`grocery_weekday`, `grocery_plan_lead_days`, `meal_week_enabled`) get
all three touches the v2.56.2 lesson demands: `models/schemas.py:Settings`, the
`config.html` load *and* save halves, and the reader (`meals.grocery_settings`).

## Hold still vs. stay fluid

The M5 rule — *an edited plate is never re-proposed under you* — extends across
the horizon, with one addition:

- **Untouched future day**: fluid. Recomposes as the schedule moves under it.
  This is a feature: Thursday becoming a 20-minute night *should* change what
  Thursday proposes.
- **Touched day**: pinned. Editing is the pin; there is no separate gesture.
- **Approved/shopped day**: pinned. **Shopping for a dinner commits to it.** A
  day that quietly recomposed after the ingredients were bought would have spent
  the family's money on a meal they are no longer having.
- **Pinned days still feed the rotation overlay**, or the plan would repeat
  around them.

`prune_plates` was fixed as part of this: it deleted every plate dated *before*
the one being written — harmless when only tonight existed, but with a week in
the table, pinning Thursday would have wiped Monday through Wednesday. It now
prunes relative to today.

## The interaction

One approval, delivered where the family already is:

- **`propose_week_plan`** runs on the 30-minute sweep, fires **once per shopping
  cycle** (keyed on the grocery date, marker set before delivery), and is quiet
  outside the lead window and on an empty repertoire — a card reading "I have no
  dinners for you" is not a plan.
- Delivery is the established car-stop path: an `approve_week_plan` action
  proposal posted to the **family channel** (chat fan-out pushes phones) and the
  **dashboard approvals banner**.
- **The nights are the message.** The card lists them. A notification saying "a
  meal plan is ready" would just be a second trip to go and look at it.
- Approving **recomposes rather than replaying the payload**: between proposing
  and tapping yes, the family may have swapped a night on the page, and the plan
  they are looking at must be the plan they get.
- Approving pins every night and drains the whole span onto the list, reusing
  `dishes_to_shopping` — so staples, already-made dishes and duplicates are
  skipped with the same reasons the "+ List" dialog already explains, now with
  the **night** attached (chicken on Monday and Thursday buys once, and that is
  only legible if you can see which night a skip came from).

## Surfaces

- **Page**: a week strip under Tonight on Shopping & Meals. Chips per night, add
  and remove in place, per-day reset, a pin marker, one approve button.
- **Voice**: `get_week_dinners` ("what are we eating this week") and
  `approve_week_dinners` ("that looks good"), registered in **both** agent stacks
  and dispatched by `agent_router`, both terminal so the answer does not cost a
  40–80s concluding round.

## Deliberately not built

- **Nutrition, calories, macros.** Not the stated problem.
- **Recipes and steps.** The repertoire is a filter, not a recipe box (M5).
- **Auto-approving the week.** The whole value is the family seeing it. An
  auto-approved plan is a plan nobody agreed to, and it would spend money.
- **Breakfast and lunch.** Dinner is where the load is. Nothing here forbids
  extending the meal window later.

## Next

The natural successors, in order: an errand created from the list bound to the
grocery day; out-of-stock as a third item state (the only shopping fact that
changes someone else's plans, and now able to name the *night* it breaks); and an
exception-based trip report.

---

# M10 — Two spans, and a list that can be taken back off

*Meals & provisioning arc, slice 10. Amends M6's window and M1's item model.*

## Why

From the family, using it:

> It only generates meals up until the next grocery run, so you can only add
> stuff from meals prior to the grocery run to the shopping list. But generally
> what people do is decide what they are going to eat for the next week and then
> make a list of things they need and buy those groceries. We don't start
> building the next wave of meals until after we have been to the grocery store,
> so we miss the chance to buy the stuff to make those meals.

The diagnosis is half right, and the half that is wrong matters. M6's
`plan_window` DOES plan past the shop — but only inside the lead window, two
days before the trip. The real defect is that the horizon was **binary and
opened late**:

- For the other five days of a seven-day cycle there was no next-shop plan at
  all, so an idea landing on a Monday ("lasagna next week") had nowhere to go
  and the list could not accumulate against the coming run the way a real list
  does.
- In planning mode the window *started on the shop date*, so the last nights
  before the trip belonged to neither span and disappeared off the page.

## The hazard, and why claims come first

Untouched days recompose as the schedule moves under them — deliberately (M6).
That is safe only because compose → approve → buy happened in one press, and
approving pins every night as it buys: *"once the ingredients are bought, a day
that quietly recomposed itself would have spent their money on a dinner they are
no longer having."*

Open the next span all week and let items trickle onto the list, and that
guarantee breaks. So the un-add came first, and everything else rests on it.

`ShoppingItem.claims` is the fix, and the shape of the old bug explains why it
had to exist: `dishes_to_shopping` **skipped** an ingredient already on the list,
so chicken wanted by Monday and Thursday was one row remembering only Monday.
Removal was impossible, not merely unbuilt. A duplicate now leaves a claim
instead of being waved away.

**The rule:** an ingredient stays while any planned night still wants the dish
that brought it.

Matching is by **dish**, not by (dish, night), and that is load-bearing. From the
family:

> Plans change at the drop of a hat... generally that meal would just get punted
> to a different day and everything else shifts, so a meal that was in the
> current span might get bumped to the next span and just not need anything
> bought for it. It kind of works itself out in the end.

It does, exactly — but only under dish matching. Per-night matching would strip
the noodles off the list the moment lasagna moved from Thursday to Friday.

Three things are never removed, each a different way to throw away real
shopping:

| Never removed | Because |
|---|---|
| A row a **person** added | "We're out of milk" is not a consequence of the meal plan and does not evaporate when the plan changes, even if a dish later claimed the same name. |
| A row already **checked off** | You own it now. This is the top-up case: bought Wednesday, Thursday's dinner changes, and rewriting the list to pretend it was never bought helps nobody. |
| A row carrying **no claims** | A meal item from before claims existed. Unexplained is not the same as unwanted. |

Batch writers (`arrange_week`, `approve_week`, `repropose_week`) pass
`reconcile=False` and reconcile once at the end. Moving a dinner is two writes,
and between them the dish is planned nowhere — reconciling in that gap unbought
a dinner the family had merely dragged.

## The window

`plan_window` returns **both spans, always**:

- `current` — today → the trip. What the last shop bought for. Settled, not
  frozen: a meeting lands, tonight's dinner gets punted, everything shifts. A
  night that slides past the shop arrives already paid for, which falls out of
  the claims rather than needing a rule.
- `next` — the trip → cadence. What the coming trip has to buy for, and the only
  span the list is built from.

`start`/`days`/`mode` keep pointing at the span being **bought for**, which is
what every existing caller meant by them.

`grocery_cadence_days` (default 7) replaces the hardcoded 7. Seven is right for
most families, which is why it was hardcoded — but a household shopping every
ten days had three nights a cycle that nothing ever bought for.

## Runs

> I definitely think the lists need to be linked to a specific grocery errand...
> a mid-week top-up should not inherit the shopping list for the next grocery
> run automatically... With that said, there isn't any reason Argyle can't also
> ask if they also want the list for the next grocery run too.

Scoped per **item** (`ShoppingItem.buy_on`), not per list. A list per run
contradicts M1's standing-list decision for a reason that is still true: the
errand regenerates every cycle while the list persists across all of them, and a
list per run is how a second list rots while everyone keeps adding milk to the
main one. One standing list; the *view* is split.

`buy_on` is the run that has to buy for a night — the run **before** it, not the
next one on the calendar. A night falling before the next run means the plan
changed after the shopping was done: that is a top-up, and it is the one case
where an item is not for the standing run.

`shopping.item_runs` splits the open list into `now` (top-up), `next` (the coming
run, including everything added by hand — `buy_on` unset means "the next run",
which is what somebody typing "milk" means) and `later` (a group per run beyond).
The rest is **offered, not hidden**: standing in a store is the best moment to be
asked, and buying some of it just checks those rows and leaves the remainder.
With one group there is no header at all — a heading over an undivided list is
not a split, it is noise.

## Deliberately not built

- **Quantity arithmetic on un-add.** Two nights wanting chicken buy chicken
  once; dropping one night does not halve it. `qty` is free text and has never
  been parsed (M1), and guessing here would be a new class of wrong.
- **A run entity.** A date is enough to answer "which trip is this for", and the
  errand that happens on that date is already discoverable by tag.
