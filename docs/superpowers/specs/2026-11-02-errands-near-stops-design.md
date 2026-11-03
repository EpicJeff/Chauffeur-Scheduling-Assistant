# Errands: near stops are one outing — design

**Date:** 2026-11-02. **Status:** rev 1, approved in conversation. **Follows:** `2026-11-02-errand-habits-design.md` (rev 1, shipped v2.499.747), whose §2.3 together machinery this generalises. **Touches:** `solver/matcher.py` (`insert_errands_globally`: a cluster pre-pass, the batch ordering, the sibling bonus, the why), `services/errand_prefs.py` (`describe_habits` wording), `models/schemas.py` + `services/settings_registry.py` (one setting), `templates/errands.html` (one input in "Where errands land"), `templates/components/errand_habits.html` (one caption), `services/agent_tools_v2.py` (one description), Tailwind rebuilt.

## Problem

The user, 2026-11-02, after v2.499.747: "people would be more likely to want to batch like kinds of errands or to batch errands colocated within a close proximity. I don't feel like blindly batching groceries with appointments is likely to ever be something someone chooses to do."

Like-kind batching is what shipped: a sibling is a placed row with the same `kind` (`matcher.py` sibling filter). Groceries never chain with an appointment. The wording lied about it: the summary line "Lorena runs groceries and pharmacy runs together", the card caption "Kinds this person likes to do in one outing" and the tool field "Kinds this person does in one outing" all read as cross-kind.

Proximity is the real gap. Kroger and the pharmacy next door are one stop whatever their kinds. The detour cost already favours placing a candidate beside a near sibling once the anchor sits, but the placement order kills it: the free errand goes first (priority order) and rides a Tuesday leg; the constrained one lands Saturday; two outings.

## Decisions (the user's, 2026-11-02)

1. **Proximity is a household setting, not a habit.** Geography is the same for everyone. `errand_near_mins`, default 5, 0 turns it off.
2. **Near stops form a cluster, any kinds.** Two errands whose places are within `errand_near_mins` of each other by drive time are one cluster; clusters are transitive (A near B, B near C puts all three together). The same place is near trivially.
3. **A cluster batches exactly as a kind does.** Constrained first in the order, the rest chain beside the anchor with the one-outing bonus. Per-person kind batching stays on top, and the two merge: an errand that is in a batched kind and in a cluster belongs to one batch group with both.
4. **Beside, never same day.** The bonus for a near sibling follows the shipped rule: prev or next stop on the route, never the `empty` shape, never the same place on another leg.
5. **Fix the words.** Per-kind means per-kind: "Lorena does groceries in one outing".

## 1. The setting

`Settings.errand_near_mins: int = Field(default=5, ge=0, le=60)`. Registry entry in group `daily`, label `Near stops are one outing`, help `Errands whose places are within this many minutes' drive of each other go in one outing: the one with the tighter day or window is placed first and the others chain beside it. 0 turns it off.`, page `errands?tab=errands`, anchor `errand-settings`. The Errands drawer section "Where errands land" gains a third number input `errand-near-mins` (0..60) wired like the other two in `errandRoutingSettings` (`LIMITS`, `settings`, `_last`). Argyle reaches it through whatever reaches the other registry settings; nothing new.

## 2. The pass

### 2.1 Clusters

Once per run, before ordering, over the active errands with a non-empty location:

1. `distinct = sorted({loc})`. `_prime_errand_cluster_pairs(distinct, storage, maps, chunk=24)`: nothing under cache-only mode; nothing when every pair is already known to `errand_leg_minutes`; else one `prime_matrix_cache(chunk, ignore_age=True)` per chunk of at most 24 places (a pair straddling two chunks stays unknown and is simply not near; never a second purchase for it). Wrapped like the other primers: a failure prints and returns 0.
2. `near(a, b)`: `a == b`, or `leg2(a, b)` and `leg2(b, a)` both known (cached or estimated) and both `<= errand_near_mins`. Unknown is not near. At `errand_near_mins == 0` proximity is off entirely (not even the same place), the shipped behaviour exactly.
3. Union-find over places with `near` edges; `cluster_of[loc]` = the root. A cluster with one errand is no cluster.

### 2.2 Batch groups

Replace the shipped "pull by kind" with a union-find over active errands:

- an edge between two errands of the same kind when that kind is in `batched_kinds` (the union of `together_kinds` over active, non-disabled drivers, as shipped);
- an edge between two errands whose places share a cluster.

Walking the base order `(priority, -duration)`, the first errand of a group with two or more members pulls the whole group into its position sorted by tightness `(0 if pinned_date else 1, len(valid_days_of_week) or 7, window minutes or 1440, priority, -duration)`. An errand in no group keeps its position exactly. With `errand_near_mins == 0` and no together kinds the order is the shipped order.

### 2.3 Bonus

When placing errand B for driver D on day d, its siblings are the rows this run already placed on d for D that are either

- **kind siblings**: same kind, and that kind is in D's `together_kinds` (shipped), or
- **near siblings**: a place in B's cluster (any kind, any driver's habits).

A candidate whose `prev_stop` or `next_stop` id is a sibling's id earns `TOGETHER_BONUS`, never the `empty` shape, as shipped. One bonus, never two. The why records which: `why['together'] = title` for a kind sibling, `why['near'] = title` for a near-only sibling (a sibling that is both is a kind sibling).

### 2.4 Primer, anchor fallback, notes

Unchanged from the habits spec §2.3–§2.4.

## 3. Words

`errand_why_text`: after the hours clause, `, with the Kroger run` for `why['together']` (shipped) else `, next to the Kroger run` for `why['near']`. Example: `on Lorena's way to Kroger run, +2 min, next to the Kroger run`. The pinned-text helper pops `near` as it pops `together`.

`describe_habits`: `Lorena does groceries in one outing`; several kinds `Lorena does groceries and pharmacy runs each in one outing`. Card caption: `Kinds this person does in one outing, each kind its own outing.` `SetErrandHabitsTool.together_kinds` description: `Kinds this person batches, each kind in one outing (groceries with groceries, never groceries with pharmacy), replacing any set: groceries, pharmacy, return, pickup, service, other. 'All the groceries together' is ['groceries']. Stops near each other already go in one outing for everyone; that is the household setting errand_near_mins, not a habit.`

## 4. Tests (Claude, first)

`tests/test_errand_near.py` on the grid world (new places `Bakery` (11,10), one minute from `Store`, and `Deli` (16,10), six from `Store`, five from `Bakery`):

1. Near stops are one outing for anyone: no habits; the constrained Kroger run (Store, Saturdays) anchors, the free pharmacy pickup (Bakery, priority 1) lands Saturday beside it with `why['near'] == 'Kroger run'`, detour 2, text ending `next to the Kroger run`; at `errand_near_mins: 0` the shipped answer (Monday from home, no words).
2. The threshold is the setting: `Deli` is six from `Store`, so at 5 they are not near and at 6 they are.
3. Transitive: Store, Bakery, Deli all land Saturday, each chained one has `near`.
4. Never across a trip home: the same geometry as the kinds test; the drive home past the near place earns nothing.
5. Kinds and clusters merge into one group: Lorena batches groceries; Kroger run (Store, Saturdays), Costco run (Shop, far, groceries, priority 1), Prescription (Bakery, pharmacy): all three Saturday, Costco `together`, Prescription `near`.
6. The cluster primer runs once with every distinct errand place; an unknown pair (a place off the grid) is not near and never breaks the pass.
7. The setting has its home: model default 5, registry entry on the Errands drawer, the input in the template.
8. Words: `errand_why_text` with `near`; `describe_habits` for one and two kinds.

`test_errand_habits_api.py` and `test_errand_habits_live.py` take the new wording. Gate: the errand suite, settings registry, template JS, Tailwind.

## Out of scope

Per-person proximity. Lookahead that moves an anchor to join a cluster. A cluster spanning two drivers (one outing is one driver).
