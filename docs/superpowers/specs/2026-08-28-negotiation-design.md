# Negotiation — the Mind brings a deal, not a conflict

**Status:** design agreed 2026-08-28. Fourth item in the ambient-family-AI
sequence (pulse → web research → threads → **negotiation** → programs →
channels).

## Why

A family manager who only reports problems is not managing anything. Today
the app is asked one question — *who drives?* — and when the answer is
"nobody", it says so. `services/coverage_options.py` softens that with a
three-tier ladder (somebody is free / an outside hand has covered this /
here are the reasons nobody can), which is a genuine improvement over a bare
alarm, but every rung still hands the problem back to a parent.

Negotiation asks the solver a **second** question: not *who drives*, but
*what is the smallest change that makes this day work, and who has to agree
to it*. The constraints are already in the model. What is missing is asking.

> "Jeff has three drives this week and Lorena has one — but hers sits behind
> a 4:45. Lorena, could that move fifteen minutes? Then Tuesday solves
> itself."

## Shape

A **deal** is a set of **parts**. Each part is one person giving up one
concrete thing. A deal applies only when every part has been agreed to by
the person it costs.

```
Deal   { id, date, seed_event_id, seed_reason, parts[], cost{}, state, created_at }
Part   { id, deal_id, member_id, lever, payload, ask_text, state }
state  draft | asking | accepted | applied | dead | expired
lever  shift_event | lift_protected | swap_drive | skip_optional
```

## How the what-if runs

### The solve pack

The negotiator does not rebuild the solver's world from storage. Two inputs
would drift immediately:

- `driver_events` — a driver's own calendar, which carries the
  `+50,000,000` attendance term and in practice decides assignments on its
  own. It is built during the calendar fetch and is not in the day cache.
- The rule list, which is assembled from three sources inside the refresh:
  stored rules, status-day unavailability, and protected commitments
  converted to `Rule(constraint_type='unavailable')` (`main.py`, protected
  commitment injection).

A negotiator that reconstructs those by hand answers a different question
than the one the family's schedule answered, and its deals are fiction.

So at the point in `_refresh_schedule_logic_impl` where every input is
already in hand, the refresh persists a **solve pack** per day: events,
`driver_events`, rules, priority rules, overrides, trip metadata, cars,
passengers, driver/passenger map, and the load-balancing flags. Negotiation
replays the pack through `matcher.solve_schedule` directly.

This is what makes the guard below possible, and it is why the pack is
preferred over extracting a day-solve seam out of the 1300-line refresh.

**Acceptance test for the whole arc: replaying a pack with no mutation
reproduces that day's cached assignments exactly.** If it does not, an input
is missing and everything built on it is untrustworthy.

### Read-only against the world

The negotiator never writes a schedule, never patches a calendar, never
touches the live cache. It mutates *copies* of a pack and returns deals.
Application happens only through an accepted request, on the existing rails.

Two guards:

- **Travel lookups are cache-only.** A shifted start changes departure time
  and could buy Matrix elements. A candidate that needs an uncached pair is
  dropped, not bought. (June 2026 burned ~118k elements against a 100k
  monthly allowance; that must not happen from a background sweep.)
- **Budget.** The sweep gets 8 re-solves with a per-solve time cap; the
  on-demand path gets 40. Over budget means fewer candidates, never a slower
  sweep.

## The levers

Each is a mutation of a pack copy, and each names the person who must agree.

| Lever | Mutation | Who must agree |
|---|---|---|
| `shift_event` | `start`/`end` moved ±15 / ±30 | the event's owner (its passenger's member, else the parents) |
| `lift_protected` | drop that one `unavailable` rule | the commitment's member |
| `swap_drive` | append a `ManualOverride` pinning a driver to an already-assigned event | the driver taking it on |
| `skip_optional` | drop the event, as `optional_decision == 'skip'` already does | the event's owner |

### Movability is learned, not declared

There is no "we control this time" flag. The app cannot know that moving the
calendar record moves the actual practice, and guessing wrong produces a
deal that makes the family look ridiculous to a coach. So the **ask is the
gate**: the deal asks whether the 4:45 can move, and the time is written
only after a person says yes.

A declined shift is remembered against that series — the negotiator never
proposes moving it again. That is how the flag gets earned. A person can
clear it by hand.

## Generation

Seeded, not exhaustive. Seeds are the day's `true_unassigned` and
`conflicts`. From each seed only things touching its window (event ±90 min)
are considered:

- `coverage_options.driver_options` already reports who is blocked and
  **why**. "Driving X" seeds a `swap_drive` on X; a protected window seeds a
  `lift_protected`.
- Events overlapping the window seed `shift_event`.
- Overlapping optionals seed `skip_optional`.

Candidates are **ordered by predicted cheapness before any solving**, and
solved down that queue until the budget runs out. The budget is a cutoff on
an ordered list, never a random sample: the sweep's 8 solves are spent on
the 8 most promising deals, and the on-demand path simply goes deeper down
the same queue.

A candidate survives only if the re-solve leaves the seed covered **and
creates no new unassigned event and no new conflict anywhere else in that
day**. Fixing the 5:00 by breaking the 7:15 is not a deal.

Validation is the seed day, and that is enough *because every lever is
occurrence-scoped*: one event moved, one occurrence of a commitment lifted,
one drive pinned, one optional skipped. None of them reaches another day's
pack. The one cross-day channel is `previous_assignments` stickiness, which
biases the next day's solve without constraining it. If a series-level lever
is ever added, this validation stops being sufficient and must widen with
it — that is the tripwire.

## Cost

Hard filter first (above), then two tiers:

**Tier 1 — people disturbed.** A one-person deal beats a two-person deal
always, whatever the numbers say. Social cost is not tradeable against
routing.

**Tier 2 — a blend, among deals disturbing the same number of people:**

- **Give-up**, in friction points, priced by what the person actually loses:

  | | points |
  |---|---|
  | shift 15 min | 1 |
  | shift 30 min | 2 |
  | skip an optional | 2 |
  | take on a drive | 3 |
  | lift a protected window | **5** |

  Protected time is deliberately the most expensive lever in the model. It
  is the one place an adult's time is *for* something rather than an
  obstacle, and the negotiator reaches for it last.

- **Objective delta**, as a capped tiebreaker (÷1000, cap 4). The base
  assignment reward is identical across candidates and cancels; what is left
  is routing and priority degradation. It breaks ties; it never drives the
  choice.

- **Fairness**, +1 per time that person was asked to give something up in
  the trailing 14 days. Counted from recorded deals — a real count, not an
  estimate.

## Consent and lifecycle

1. The sweep negotiates *before* it speaks. The finding line stops being
   `🚨 No driver yet: Soccer practice — Thu 5:00 PM` and becomes *"Tuesday
   works if Lorena's 4:45 moves 15 minutes."* One action: **Ask them**.
2. **Nothing is asked without a person tapping.** The search and the asking
   are separate functions behind separate endpoints — the same shape as
   threads' draft/send split, and for the same reason.
3. The tap creates one request per part (`kind='deal_part'`,
   `subject_ref` = part id). Each person answers on the surface they already
   answer requests on, with the existing DM and push rails and the existing
   blameless decline-with-a-reason.
4. **Nothing applies until every part says yes.** `requests._perform`
   delegates `deal_part` to `negotiation.accept_part`; the last yes applies
   the whole deal and marks the schedule dirty.
5. One decline kills the deal and the runner-up is offered — the next
   candidate down the queue that does not contain the refused part.
6. Expiry rides the request TTL (20h) and the event itself. A deal whose
   event has passed dies quietly.

**Application, only on full acceptance:**

| Lever | Applied by |
|---|---|
| `shift_event` | `calendar.patch_event` |
| `lift_protected` | a one-occurrence exception record — never deleting the commitment |
| `swap_drive` | `storage.add_override` (the call `requests._perform` already makes) |
| `skip_optional` | the existing optional-skip decision |

## Surfaces

No new nav page. Three places, all of which exist:

- **The finding is the deal's face.** `findings.reconcile` already keeps a
  line current, so the sweep rewrites it as parts answer: *"Tuesday: Jeff
  said yes, waiting on Lorena."*
- **Requests** carries each part.
- **Chat**, in *both* agent stacks (`agent_tools_v2` and
  `agentic_chat_loop`): `negotiate_day(date)` (read-only, returns ranked
  deals) and `ask_deal(deal_title)` (fans out the requests). Fuzzy day and
  deal references, never ids. `ask_deal` requires a resolved parent or adult
  from an allowlist — `/api/chat` is `WALL_OR_SERVICE`, so a blocklist would
  let an anonymous kiosk fan out asks.

Parents and adults only, kiosk-hidden: a deal names who is giving up what.

### Hand path

Nothing here is agent-only.

- **Find a way** on an uncovered event — in the override dialog, where
  `explain_assignment_conflicts` already answers the deeper question — and
  on the finding card. Runs the deep search on demand.
- Deal state is readable without asking Argyle: the finding line plus the
  Requests surface.
- **Kill this deal** and **clear a learned "can't move"** are both taps. A
  flag the app taught itself must be untaught by hand.

## Settings

In `settings_registry.py` and on the feature's own page, never
`config.html`: `negotiation_enabled`, sweep budget (default 8 solves),
deep budget (40), shift steps (15/30), per-solve time cap.

## Out of scope

- **The agent never asks anybody without a tap.**
- No new nav page, no deal inbox.
- No fifth lever. Status days, car reassignment and driver windows stay
  where they are.
- Seeds and validation are both one day, which is sound only while every
  lever stays occurrence-scoped. No multi-day deal composition in v1.
- No counterfactual week — that is the rung after this one.
- Outside-hand asking is not duplicated. `coverage_options` tier 2 already
  does it; if no deal is found, the ladder is still the answer, unchanged.

## Testing

- **Replay fidelity** — a pack replayed unmutated reproduces the cached
  assignments exactly. Everything else rests on this.
- One constructed day per lever, where exactly that lever works.
- A candidate that covers the seed but breaks something else on the same day
  is rejected.
- Cost ordering — a two-person deal never outranks a one-person deal; a
  protected-lift is never chosen when a shift also works.
- Consent — partial acceptance applies **nothing**; assert the calendar and
  the overrides are untouched.
- Decline → the runner-up excludes the refused part, and a refused shift is
  never proposed for that series again.
- Budget — the sweep never exceeds N solves, and a candidate needing an
  uncached travel pair is dropped rather than bought.
- A test that actually **runs** the sweep path end to end. Entry points
  swallow exceptions, so a source-reading test proves nothing.
- Hand-path reachability — the button exists and reaches the endpoint.
