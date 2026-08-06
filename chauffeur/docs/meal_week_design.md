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
