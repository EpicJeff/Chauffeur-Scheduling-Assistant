# Errands with common sense — design

**Date:** 2026-10-22. **Status:** rev 1, approved in conversation (approach A, all six sections). **Follows:** `2026-10-22-errands-ride-the-route-design.md` (rev 2.2, shipped v2.499.670-.677). **Touches:** `solver/matcher.py` (`insert_errands_globally`, the candidate shapes, the ranking key), a new `services/errand_prefs.py`, `services/storage.py`, `services/maps.py` (one route primer), `models/schemas.py` (`Errand.kind`, `Errand.home_bound`), `main.py` (the PUT, the refresh, three preference routes), `services/agent_tools_v2.py`, `templates/errands.html` (editor fields, the Learned block), a new `templates/components/errand_learned.html`.

## Problem

First device run of the route arc, 2026-10-22, two grocery errands:

1. One landed **Saturday 08:00 as a trip from home**. The empty-day shape takes the earliest fit at `ERRAND_DAY_START` 08:00 (`matcher.py:2857`), and the from-home candidate won because the passing legs most likely ranked *unknown*: a between-stops candidate needs the stop-to-stop pair cached too (`tab`, `matcher.py:2876`), and the drivers' own appointments were never in the main solve, so their pairs are not. Under R5 any known candidate beats any unknown one, so home → store (cached) beat every real drive.
2. The other landed **on the way to an appointment at least two hours before anyone would be home**. Scoring is pure detour minutes per shape; nothing in the pass knows that groceries have to be the last stop before home.

The user: "This isn't about not wanting a dedicated grocery trip. It is about using common sense when scheduling things … it should be the foundation of everything in Chauffeur. I am ok with the way things are as long as I can steer it and how I steer it will influence how things are done in the future … what I really want is for it to handle the most common things the right way without requiring users to set anything."

## Decisions (the user's, 2026-10-22)

1. **Common sense is built in, not configured.** The most common errand kinds get the right default with no setting: groceries ride home, nobody drives out at 08:00 Saturday for one errand.
2. **Every steer teaches.** A steer still fixes this cycle (shipped), and it also writes a standing preference the pass scores from then on.
3. **Learned preferences apply silently**, said out loud in the why text, and are listed on the Errands page where any one can be deleted. Never a lock; always a soft cost. (Chosen over "propose once, apply after a yes".)
4. **Explicit flags are welcome but secondary.** A per-errand "on the way home" and a kind override exist for the case the guess is wrong.

## Approaches considered

- **A. Heuristics in the pass plus a preference store scored as soft costs.** Chosen. Deterministic, explainable, one small store.
- **B. Steers materialize into `ErrandRule`s.** Rejected: rules are hard constraints, keyword-only, carry no per-driver time taste, and auto-rules would pile up beside hand rules.
- **C. Argyle learns and interprets at placement time.** Rejected: opaque, a model call per refresh, violates the owning-module rule (a number the UI states comes from the module that owns it).

## 1. Kind inference (zero config)

`services/errand_prefs.py: errand_kind(errand) -> str`, one of `groceries` · `pharmacy` · `return` · `pickup` · `service` · `other`. Order of evidence:

1. `errand.kind` when set (the override, §5).
2. A shopping list bound to the errand by tag (`storage.find_shopping_lists_for_errand`) → `groceries`.
3. Tags, then the title, lowercased, word-boundary match against the built-in table:
   - `groceries`: grocery, groceries, market, supermarket, food, costco, sam's, sams club, kroger, aldi, publix, meijer, wegmans, trader joe, whole foods, walmart, target run, h-e-b, heb, safeway, giant, harris teeter, fresh market
   - `pharmacy`: pharmacy, prescription, rx, walgreens, cvs, rite aid, meds
   - `return`: return, drop off, drop-off, mail, ship, ups, fedex, post office, usps, library (when paired with return/drop)
   - `pickup`: pick up, pickup, collect, fetch
   - `service`: haircut, barber, salon, nails, oil change, car wash, tires, vet, dentist, doctor, appointment
   - else `other`
   First matching kind in the order above wins (a "pick up groceries" is groceries, because the groceries test runs first; a "return library books" is a return).

The table is a module constant, not a setting. The admin editor shows the inferred kind as a chip ("Groceries, guessed") next to the kind select so a wrong guess has a one-tap fix.

## 2. Defaults per kind

- **Home-bound kinds: `groceries`, `pharmacy`.** Allowed candidate shapes are the after-last-stop-then-home leg (`to_home_leg`) and the round trip from home (`empty`). The before-first-stop leg and every between-stops leg are not generated for a home-bound errand. `Errand.home_bound` (§5) overrides in either direction: `True` makes any kind home-bound, `False` lets groceries ride any leg, `None` means by kind.
- **Dedicated trips keep human hours.** When the errand has no standing window and no pinned window, the `empty` shape's bounds become `[dedicated_start, 17:00 − duration]` where `dedicated_start` is 09:00 on a weekday and 10:00 on Saturday or Sunday; start is the earliest fit. When the person set a standing window or a pinned window, that window alone bounds the trip as today (a 07:00–09:00 window or an Evening pin is their choice and the band never narrows it). `ERRAND_DAY_START` 08:00 stays for legs: an errand on the way to an 08:30 drop-off is fine at 08:00, that drive is happening anyway.
- **A day someone already leaves the house is preferred for a dedicated trip.** No new rule needed: on such a day the home-bound errand has a `to_home_leg` candidate carrying only its detour, while the `empty` shape on a blank day carries the `errand_dedicated_trip_mins` penalty. The spec records this so nobody adds a second mechanism.
- Nothing else changes for `return`, `pickup`, `service`, `other`.

## 3. Unknown legs

- **Route priming.** Once per refresh, before any errand is scored, `_prime_route_pairs(routes, homes, storage, maps)` collects every adjacent pair on every driver's day route (home → first stop, stop → next stop, last stop → home) whose minutes are unknown and primes them with `maps.prime_matrix_cache` in chunks of at most 24 distinct locations, nothing under `travel_cache_only_active()`, never raising. Bounded: one pass, adjacent pairs only. The existing per-errand primer (errand ↔ every place) stays.
- **Estimation replaces the unknown tier.** `matcher.errand_leg_estimate(a, b) -> Optional[int]`: both places' coordinates from `storage.get_cached_geocode` (under cache-only mode) or `maps.geocode_address` (otherwise); haversine kilometres; `minutes = round(km × 1.5) + 2` (a 40 km/h suburban average plus a stop). `None` when either place has no coordinates. A leg is costed as its cached minutes when known, else its estimate **plus a 10-minute uncertainty surcharge** on the candidate; a candidate with a leg that cannot even be estimated keeps today's rank-last tier.
- The ranking key becomes `(unestimable, cost, date, start_time, driver_id)` where `unestimable` is 1 only when some leg has neither cache nor estimate. `cost` includes the surcharge and §4's preference cost.
- **Nothing estimated is stated as fact.** `why.estimated = True` when any leg of the winner was estimated; the text reads "on Jeff's way home from Work, about +8 min (estimated)". `travel_to_mins` / `travel_from_mins` stay `None` for an estimated leg so leave-by is never drawn from a guess (R5 kept). `why.kind` is `on_the_way` / `inside_stop` / `from_home` / `pinned` as today; `unknown_travel` remains only for the unestimable tier.

## 4. What a steer teaches

### 4.1 Store

`storage` keeps `errand_preferences` as an app-state list of rows (small, a few dozen at most):

```
{"id": uuid, "scope": driver_id | "*", "kind": "groceries" | ... | "*",
 "dimension": "weekday" | "time_band" | "driver", "value": "5" | "evening" | driver_id,
 "polarity": "prefer" | "avoid", "weight": 2.0, "last_seen": 1761177600.0,
 "source": "steer" | "hand"}
```

Helpers: `get_errand_preferences()`, `upsert_errand_preference(row)` (same scope+kind+dimension+value+polarity → weight +1, `last_seen` now), `delete_errand_preference(id)`, `clear_errand_preferences()`. Rows whose effective weight (§4.3) falls under 0.5 are pruned on any write.

### 4.2 Teaching, from the diff of a steer

`errand_prefs.learn_from_steer(before, after, placement, now)` runs in ONE place and is called by both writers, the PUT in `main.py` and the agent's `handle_update_errand`, before `forget_errand_placements` so the pre-steer placement row is still there. `placement` is the errand's cached row (`storage.get_all_scheduled_errand_rows().get(eid)`), which carries the day and the driver. `kind = errand_kind(after)`; `scope` is the placement's driver when it has one, else `after.once_driver_id`, else `"*"`.

| steer | rows written |
|---|---|
| `skip_dates` gained a date | `(scope, kind, weekday, that date's weekday, avoid)` |
| `pinned_date` set or changed | `(scope, kind, weekday, pinned weekday, prefer)` |
| `pinned_start`/`pinned_end` set or changed | `(scope, kind, time_band, band, prefer)`; band is the `STEER_WINDOWS` entry whose range equals the pin, else the band containing the pin's midpoint (morning 08–12, midday 11–14, afternoon 14–17, evening 17–20) |
| `once_driver_id` set | `("*", kind, driver, that driver, prefer)` |
| all four cleared (Back to automatic) | nothing |
| any non-steer field | nothing |

Weight starts at 1 and grows by 1 per repeat of the same row. Nothing is ever written with weight above 6 (cap). A `dimension: shape` row is **not** learned in this slice: no steer verb says "on the way home", and the explicit `home_bound` flag covers it. (Deviation from the conversational design, which listed shape among the dimensions; recorded here for the user.)

### 4.3 Scoring

`errand_prefs.preference_cost(rows, driver_id, kind, day_date, start, now) -> (cost_mins, matched_rows)`. Effective weight = `weight × 0.5 ** (days_since_last_seen / 90)`. For each row with `scope in (driver_id, "*")` and `kind in (kind, "*")` that matches the candidate (weekday equal; start inside the band; driver equal): `prefer` subtracts `5 × weight`, `avoid` adds `5 × weight`. The sum is clamped to `[-30, +30]` and added to the candidate's `cost`. Soft only: an avoided Saturday still wins when every other candidate costs more than 30 minutes extra.

The winner's `why` gains `learned: [row ids]` when `matched_rows` is non-empty, and the text appends ", as you steered it before". Same sentence everywhere, built in `errand_why_text`.

## 5. Hand paths and the explicit flags

- **`Errand.kind: Optional[str]`** (validated against the six kinds) and **`Errand.home_bound: Optional[bool]`**, both in `ERRAND_ROUTING_FIELDS` so a change forgets placements. `ErrandRule` gains the same two fields so a rule may set them by keyword (matching unchanged). Admin editor (`errands.html` edit modal): a kind select ("Automatic" plus the six, with the guessed kind shown as a chip) and an "On the way home" select (Automatic / Yes / No).
- **Learned block.** `templates/components/errand_learned.html`, included on the Errands page's rules tab under the rules list, Alpine logic in the component so a kiosk never draws it. One row per preference in plain words from `errand_prefs.describe(row, people) -> str`, e.g. "Jeff: groceries not on Saturdays (learned from 2 steers)", "Anyone: pharmacy in the evening", "Kate runs returns". Each row has Delete; the block has Clear all behind `promptConfirm`. Empty state: "Nothing learned yet. Steering an errand teaches this list."
- **Routes.** `GET /api/errands/preferences` → `{rows: [{...row, text}]}`; `DELETE /api/errands/preferences/{id}`; `DELETE /api/errands/preferences` (all). Auth tier: `PARENTS`, same as `/api/errand_rules/*`. A delete queues a refresh.
- **Agent.** `AddErrandTool` / `UpdateErrandTool` gain `kind` and `home_bound`. New `GetErrandPreferencesTool` (no args) and `ForgetErrandPreferenceTool(id: str | "all")`, admin-only like the other errand tools, registered once in `agent_tools_v2.py` (the one stack). Every new agent arg is reachable from the editor or the Learned block.
- **Nothing removed.** The steer sheet, Complete, Edit, Delete, rules, the setting, every standing field stay as they are.

## 6. Tests, written first

`tests/test_errand_common_sense.py` (new; same grid fixture and `errand_leg_minutes` stub as `test_errand_routing.py`, plus a stubbed `errand_leg_estimate`):

1. **Kind table.** Each kind from a tag, from a title, the override wins, a bound shopping list means groceries, "pick up groceries" is groceries.
2. **Groceries ride home.** A grocery store 4 minutes off the drive to a 10:00 appointment and 4 minutes off the drive home at 17:00: the errand lands after the appointment, `why.leg.to == 'Home'`. With `home_bound=False` the morning leg wins (earlier tie-break). A `return` with the same geometry lands on the morning leg.
3. **Dedicated trip hours.** Empty Saturday, no window: the trip lands at 10:00, not 08:00; empty Tuesday at 09:00; a standing window 07:00–09:00 places at 07:00; an Evening pin places at 17:00 (the band never narrows a window the person set).
4. **A passing leg with an estimated pair beats from home.** Own appointment whose stop→next pair is uncached but estimable (detour 8 + surcharge 10 = 18) beats a known round trip from home (10 + 25 = 35); `why.estimated` true, text says "about +8 min (estimated)", `travel_to_mins is None`. A leg with no coordinates still ranks last.
5. **Route primer.** Recording stub on `maps.prime_matrix_cache`: adjacent pairs only, once per refresh, chunked at 24, nothing under cache-only, no `UncachedTravelPair`.
6. **Teaching.** Each steer verb writes the row in the table of §4.2; a repeat raises weight to 2; Back to automatic and a location edit write nothing; the agent's `update_errand` writes the same row as the PUT.
7. **Scoring.** An avoid-Saturday row of weight 2 moves the next cycle off Saturday when the alternative costs under 10 more; a 40-minute-worse alternative does not (soft); decay halves a 90-day-old row; the clamp holds at 30; the why text appends the learned sentence and `why.learned` lists the ids.

`tests/test_errand_prefs_api.py` (new, TestClient): PUT steer → row exists; GET lists rows with `text`; DELETE one, DELETE all, both queue a refresh and need a parent; `kind` and `home_bound` round-trip through PUT and forget placements; the agent tools write and read the same rows; `AddErrandTool` with `home_bound=True`.

`tests/test_errand_lists_render.py` (extend) or a sibling: the Learned block renders rows, Delete calls the route (node-run through the component's logic), empty state text, not drawn on a kiosk board.

Gate (never the full suite): the two new files, `test_errand_routing.py`, `test_errand_routing_api.py`, `test_errand_lists_render.py`, `test_pwa_errand_steer.py`, `test_solve_pack.py`, `test_storage.py`, `test_chat_actions.py`, `test_registry_parity.py`, `test_template_js.py`, `test_auth.py` (route classification).

## 7. Not in this slice

- Learning a shape preference from steers (no verb says it; `home_bound` is the hand path).
- Learning from completion time (ticking an errand at a different hour than planned).
- Per-person defaults beyond what steers teach (no "Jeff never runs errands before 10" setting).
- Kind-aware duration defaults.
- Negotiation when a preference displaces someone else's plan.

## 8. Who builds what

Claude writes the failing tests for each task, Codex implements, Claude reviews each diff, runs the gate, updates `system_capabilities.md`, bumps `config.yaml`, commits. Never Codex reviewing Codex-built work. Tasks, in order: (1) `errand_prefs.py` kind table + store + describe; (2) home-bound shapes and dedicated-trip hours in the pass; (3) estimate, surcharge, route primer, ranking key, why text; (4) teaching from both writers; (5) scoring in the pass; (6) schema fields, editor, routes, Learned block; (7) agent tools; (8) capabilities entry and device steps.
