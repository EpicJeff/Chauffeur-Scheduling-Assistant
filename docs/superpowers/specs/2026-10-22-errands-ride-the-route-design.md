# Errands ride the route — design

**Date:** 2026-10-22. **Status:** rev 2.1, Codex adversarial review of rev 1 folded (22 findings, §10) and the Task 2 implementation review folded into §1 (two anchors per ride, latest start for the from-home leg, allowed/required rule, trip-away drivers, no note outside the range). **Touches:** `solver/matcher.py` (`insert_errands_globally`), `main.py` (the refresh's errand pass, `/api/errands`), `models/schemas.py` (`Errand`, `Settings`), `services/storage.py`, `services/settings_registry.py`, `services/maps.py` (one bounded primer), `services/agent_tools_v2.py` (`update_errand`, `get_errands`), `templates/components/errand_lists.html`, `templates/errands.html` (the settings drawer), `templates/app.html` (My Day errand card and modal).

## Problem

The user, 2026-10-22: "Errands should not only look for gaps in the schedule but look for routes that take the driver by or near the errand location. Currently they just seem to look for gaps and often just choose the first slot on a day, so it isn't optimizing for someone already being out and about and doesn't care where they are or where they are going. They have never really worked well so we have avoided using them at all."

What the code does today (`solver/matcher.py:2430-2841`), and why it produces exactly that:

1. **It only sees rides.** The per-driver day it scores is built from `base_schedules[date].assignments`, which holds passenger events only. A driver's own appointments (work, the gym, a haircut: anything with no passenger) never enter the solve (`main.py:20806`), so the pass has no idea where a driver is going on their own. The drivers' own events exist in `driver_events_map` at the call site (`main.py:21725`) and are not passed in.
2. **It scores with numbers it does not have.** `services/maps.get_travel_time_minutes` tries the cache, then primes one pair, then falls back to `max(15, straight-line floor)` for a pair it still cannot route (`maps.py:245`); a pair cached as unroutable comes back as 900 (`maps.py:227`). The solver's wrapper collapses anything of 3 minutes or less to 0 (`matcher.py:14`). Where routing fails for a venue typed as a bare name, every leg costs the same and the comparison is strict `<`, so the first candidate scanned wins: earliest date, first driver, 9:00 on an empty day or before the first event. An errand with an empty `location` scores 0 everywhere and lands first-slot, every time.
3. **A trip from home is cheap.** An empty day scores `2 × (home → errand)`. A store five minutes from home beats every real detour, so the errand never waits for someone who is already out.
4. **Two latent bugs make it worse.** `valid_days_of_week` filters the cache scan (`matcher.py:2553`) but never the candidate days (`matcher.py:2659`): a Tuesday-only errand lands Monday (Codex reproduced it). And the winning placement is finalized from whatever `day_schedules` and `driver_home` the LAST scanned day and driver left behind (`matcher.py:2784-2794`), so a Monday winner can carry Tuesday's neighbour ids and another driver's home.
5. **It cannot be steered.** Once placed, the only hand verbs are tick it done, edit its fields on the admin page, or Reschedule a past-due one. There is no "not today" and no "put it on Thursday".
6. **The agent's `update_errand` is broken.** `handle_update_errand` calls `storage.get_errand` and `storage.complete_errand`, neither of which exists; every call raises and the dispatcher turns it into an error result (`agent_tools_v2.py:7813`, `:9480`).
7. **Nothing tests it.** No test imports `insert_errands_globally`.

## Decisions (the user's, 2026-10-22)

1. **Errands ride routes.** Prefer a leg a driver already drives inside the errand's window, scored by the extra minutes it adds to that leg.
2. **A trip from home is fine when nothing passes near.** It is a fallback, not a peer: it carries a penalty so it wins only when no outing in the window comes close.
3. **Every placement can be steered, by hand and by Argyle.** "People have different preferences for when they like to go out or may not feel like going at the time the scheduler picks." Steering is per errand in this slice (option 1 of three); standing per-person preferences are a later slice. Errand rules stay as they are. (Correction from rev 1: a rule matches only through a non-empty keyword, location or filter set, `main.py:18342`; a rule with nothing to match affects nothing. Rule matching is not changed here.)

## Rulings made while folding the review (for the user to confirm or overturn)

- **R1. A driver's own appointment is a stop, never a drop-off-and-run window.** The driver is there. Only passenger rides keep today's inside-event shape.
- **R2. Coarse windows on the phone, exact times on the admin editor.** The steer sheet's Pick a time offers Morning (08–12) · Midday (11–14) · Afternoon (14–17) · Evening (17–20); Pick a day offers the next 14 days as a list. No free text on either host (the PWA's `promptInput` is a textarea whatever `type` it is handed, `app.html:3551`). The admin errand editor keeps HH:MM fields for the standing window and gains the pinned fields with the same inputs.
- **R3. An unplaced errand is reachable on the phone.** My Day grows one row, "Errands not placed", under today whenever an errand the viewer may steer has an `unplaced` note; it opens the same sheet. Without it, "Someone else" could strand an errand where only Argyle could bring it back.
- **R4. The steer audience is Complete's audience.** Today Complete shows for `ev.isErrand && selectedDriverId` (any signed-in driver, `app.html:9288`); Steer uses the same predicate, and Complete is not touched.
- **R5. Unknown is not unroutable.** A pair the cache has never seen is unknown (placed only when nothing known exists, said out loud). A pair cached as unroutable, or an errand with no location, is never placed and is reported.
- **R6. The successor of a completed recurring errand is anchored on the cycle it completes**, not on the original `starts_on`, and never inherits steering.

## 1. Legs

For each driver and each day in the solve range, the pass builds the driver's **day route**: an ordered list of stops.

- **Stops**, in time order: the assigned rides (`assignments[event_id] == driver_id`, today's source), plus the driver's own events from `driver_events[driver_id]` that fall on that date (new). An own event counts when it has a non-empty `location`, is not `all_day`, is not `event_type == 'background_trip'`, and is not already in the list by id or `original_event_id` (a ride the driver also attends is one stop). Each stop carries `is_ride` (true for an assigned ride) so §1's shapes can tell them apart.
- Home is the implicit first and last stop (`driver.home_location`, or the active trip home via `get_active_home` exactly as today; a driver whose home has moved for a trip is skipped unless the errand is grouped with that trip, as today).
- **A drop-off-and-run ride is two anchors.** A ride the driver does not stay at (`requires_stay` false) enters the route as a drop stop at its start and a pickup stop at its end, both at the ride's location and both carrying the ride's id. The old "inside the event" shape is then just the between-stops gap from the drop to the pickup, and any other stop that falls inside the ride (an own appointment, an earlier errand) clips that gap the way it clips any other. A ride the driver stays at, and every own event (R1), is one busy stop. (Rev 2.1, from the Task 2 review: the single-stop form let an errand overlap an own appointment inside a ride, and a second errand placed inside a ride could run across the pickup.)
- **Candidate shapes** are: before the first stop (from home), between two stops (which now includes the drop → pickup gap of a ride), after the last stop (then home), and the empty day (home → errand → home). Passenger-in-car rules keep today's semantics: only a between-stops slot can carry passengers, and the drop → pickup gap of a ride carries none (the passengers are at the event).
- **Candidate timing** (new; fixes Pick a time and today's 09:00-only empty day). Each shape has bounds `[earliest, latest]`: before-first = `[day start, first.start − (errand → first) − duration]`; between = `[a.end + (a → errand), b.start − (errand → b) − duration]`; after-last = `[last.end + (last → errand), day end − duration]`; empty = `[day start, day end − duration]`. Day start is 08:00, day end 21:00. The candidate's start is a time inside the intersection of those bounds, the standing window (`time_window_start/end`), the pinned window (§4), and `now`: the LATEST such time for the before-first shape (the leg is the drive to the stop, so the errand sits just before leaving, not at dawn eight hours earlier), the earliest for every other shape. No intersection, no candidate. (Rev 2.1: rev 2 said earliest for every shape.)
- Driver filters (`required_drivers`, `prohibited_drivers`, `allowed_drivers`, assignment rules via `is_driver_allowed_for_slot`) are unchanged. `valid_days_of_week` is now applied to candidate days (fixing bug 4).
- `allowed_drivers` keeps today's rule exactly: it applies only when `required_drivers` is empty. A driver away on a trip (active home moved) is skipped before any "saw a driver" bookkeeping, so an errand only such drivers could run reports `no_driver`.
- An errand whose window holds no day in the solve range (a one-off starting next month, a Sunday-only errand in a Monday-to-Saturday solve) gets no note: it is not unplaced, it is waiting. Notes are for errands the pass looked at and could not place.

The function signature becomes `insert_errands_globally(base_schedules, errands, drivers, trip_metadata=None, driver_events=None, now=None, settings=None)` returning `(scheduled_by_date, notes)`. `driver_events` is the `driver_events_map` the call site already holds; `now` and `settings` are injectable for tests.

## 2. Score

Candidates are ranked by `(unknown, cost, date, start_time, driver_id)`, lowest first:

- `unknown` is 0 when every leg of the candidate has a known drive time, 1 otherwise. A known candidate always beats an unknown one; grouping cannot flip that (rev 1's 10 000 penalty lost to the 9 999 group bonus).
- `cost = detour_mins + dedicated_penalty − group_bonus`. `detour_mins` is what it is today per shape; `group_bonus` keeps lowering it for a grouped errand already placed with this driver on this day. `dedicated_penalty` is the setting **`errand_dedicated_trip_mins`** (default 25, bounds 0–120), applied only to the empty-day shape. A 10-minute round trip from home costs 35 and loses to any passing leg under 35 minutes of detour.
- Ties go to the earlier date, then start time, then **driver id as a string** (stable; list order never decides).
- The chosen candidate is finalized from ITS OWN saved route, home and legs (fixing bug 4's second half), and its `VirtualEvent` goes into that driver's day route so a second errand sees the first.

### 2.1 Drive time

A new `matcher.errand_leg_minutes(a, b)` returns the true cached minutes without the 3-minute collapse, `0` for the same place, and `None` for an unknown pair. It never returns a fallback. It is a pure cache read (`storage.get_cached_travel_time(..., ignore_age=True)`, the planning cache that `system_capabilities.md` already treats as immortal for scheduling). A pair cached as `UNROUTABLE` is `None` too, but the pass checks unroutability of the errand's own location first (§3) so it never scores one.

**Priming is one bounded step before scoring, not a fetch per leg.** For each active errand the pass collects the distinct locations it could touch across the range (the errand's location, every driver home, every stop location), removes pairs already cached, and primes once per errand with `maps.prime_matrix_cache(locations, ignore_age=True)` in chunks of at most 24 locations (Mapbox Matrix's limit is 25 coordinates). Under `travel_cache_only_active()` nothing is fetched and unknown stays unknown; `UncachedTravelPair` is never raised from this pass. The primer is covered by a real-boundary test (§6), not only the wrapper stub.

## 3. What a placement says about itself

Each row in `scheduled_errands` gains:

```
"why": {
  "kind": "on_the_way" | "inside_stop" | "from_home" | "pinned" | "unknown_travel",
  "detour_mins": 6,
  "leg": {"from": "Home", "to": "Soccer practice"},   # titles, not addresses; absent for from_home
  "driver_name": "Jeff",
  "text": "on Jeff's way to Soccer practice, +6 min"
}
```

`text` is built server-side by `errand_why_text(why)` so every surface says the same sentence: "on Jeff's way to Soccer practice, +6 min" · "while Kate is at Piano, +9 min" · "a trip from home, 12 min each way" · "the day you picked, on Jeff's way to Work, +4 min" · "drive time unknown, check the address". `pinned` wraps the shape that won on the pinned day. For `unknown_travel` the row's `travel_to_mins` / `travel_from_mins` are `None`; `home_board._errand_leave` and the route edges already draw no leave-by for a missing travel figure, so nothing is stated as fact that is not known (R5).

Errands the pass could not place are recorded, not dropped: `notes = {errand_id: {"reason", "text", "generation"}}` with reasons `no_location` · `unroutable_location` · `no_slot` · `no_driver` · `pinned_day_passed` · `pinned_day_not_in_range` · `every_day_skipped`. `main.py` saves them with `storage.save_errand_placement_notes(notes)` only from the routine refresh (not a draft, not a custom-range solve), replacing the whole set, so a note never outlives the run that could have cleared it. `GET /api/errands` merges, per errand, `placement` (the scheduled row's `start_time`, `driver`, `why`) when scheduled, else `unplaced` (the note), plus a top-level `generation` (§4.4). `storage.get_all_scheduled_errands` keeps returning the start time for its current callers; a sibling `get_all_scheduled_errand_rows` returns the whole row.

## 4. Steering

### 4.1 Fields on `Errand`

| field | type | meaning | lifetime |
|---|---|---|---|
| `skip_dates` | `List[str]` ISO dates | days this errand must not land on | dates before today prune on read; cleared on completion |
| `pinned_date` | `Optional[str]` ISO date | the one day it must land on | cleared on completion |
| `pinned_start`, `pinned_end` | `Optional[str]` HH:MM | the window on the pinned day; either may be absent | with `pinned_date` |
| `once_driver_id` | `Optional[str]` | this cycle's driver, one-shot | cleared on completion |

Pydantic validators reject a malformed date or time with 422 on every writer (PUT, agent, sheet).

### 4.2 Precedence

Computed in this order, each step narrowing the last:

1. **Window** from the recurrence anchor as today (`starts_on` else `created_at`; weekly ±2 days around anchor+7; daily; monthly ±5; one-off `window_days`), then today's overdue widening (past the window end → ASAP, open-ended).
2. **`pinned_date`** replaces the window with that single day, BEFORE overdue widening is considered. Pinned day before today → `pinned_day_passed`, no placement, the pin stays until a person clears or moves it (a passed pin never revives itself). Pinned day beyond the solve range → `pinned_day_not_in_range`. Pinned day not in `valid_days_of_week` → the pin wins (the person chose it on purpose); the card's why says "the day you picked".
3. **`skip_dates`** removes days. Every day gone → `every_day_skipped`.
4. **Driver**: `once_driver_id` acts as `required_drivers = [once_driver_id]` for this cycle and overrides the standing `required_drivers`/`allowed_drivers`; `prohibited_drivers` and assignment rules still apply (a prohibited or rule-barred driver → `no_driver`, text names the driver and why). A disabled driver, or one away on a trip, → `no_driver`.
5. **Time**: the standing window intersected with `pinned_start/pinned_end` (§1 candidate timing). Empty intersection → `no_slot`.

### 4.3 Completion and the recurring successor

`storage.complete_errand(doc_id, now=None)` is created and becomes the one path for the PUT, the PWA tick, the Errands page tick and the agent. It marks the row complete and, for a recurring errand, mints the successor as the PUT does today (new uuid, `is_completed False`, `status pending`, `last_scheduled_end None`, `created_at now`) with two corrections (R6): the successor's `starts_on` is the completed cycle's target date (anchor + 7 / 1 / 30 days), so the cadence holds instead of re-anchoring on a stale explicit date; and the successor's `skip_dates`, `pinned_*`, `once_driver_id` are empty. The completed row's one-shot fields are cleared too. The PUT handler calls this helper when `is_completed` flips to true; it is idempotent (a second completion of a completed row mints nothing).

### 4.4 A steer takes effect

A PUT that changes any steer field (or any field the pass reads: location, duration, windows, drivers) calls `storage.forget_errand_placements(errand_id)`: the errand's rows are removed from every cached daily schedule and its note dropped, so the `already_scheduled` scan cannot hold a stale placement over a new steer (rev 1 kept the scan as it was; Codex showed it would mask steering). The scan itself also validates: a cached row on a skipped day, or off the pinned day, or with the wrong driver after a `once_driver_id`, does not count as scheduled.

`GET /api/errands` carries `generation`, the refresh counter the routine refresh increments when it finishes (`storage.set_schedule_generation`). The sheet notes the generation at PUT time, shows "Replanning…" on the row, and re-reads `/api/errands` every 3 seconds for up to 60 seconds until `generation` moves; then it draws the new placement or the `unplaced` reason. After 60 seconds it says "Still planning, check back" and stops.

### 4.5 The hand path

One shared sheet, `steerErrand(errand)`, in `errand_lists.html` so the Errands page and the PWA draw the same one. It opens `promptChoice` (control_center.html; no browser dialogs) titled with the current `why.text` or `unplaced.text`:

- **Not this day** — the scheduled day joins `skip_dates`. Shown when scheduled.
- **Skip a day…** — `promptChoice` of the next 14 days → joins `skip_dates` (hand parity with the agent's arbitrary `skip_date`).
- **Pick a day** — `promptChoice` of the next 14 days → `pinned_date` (R2).
- **Pick a time** — `promptChoice` Morning / Midday / Afternoon / Evening → `pinned_start/pinned_end`, on the pinned day or, if none, the scheduled day (which it pins); unplaced with no day → asks Pick a day first.
- **Someone else** — `promptChoice` of the family's drivers (not disabled) → `once_driver_id`.
- **Back to automatic** — clears all four. Shown when any is set.

Every write re-reads the errand from `/api/errands` and sends the WHOLE record through `PUT /api/errands/{doc_id}` with only the steer fields changed, exactly as `toggleErrandDone` does, so standing controls are never reset by a partial record.

Where it is reachable:

- **Errands page** (`errand_lists.html`, `errand_row` with `interactive` and the page's `edit`): the ✓ label becomes "✓ Tue 4:10 pm · on Jeff's way to Soccer practice, +6 min" and a **Steer** button sits beside Edit. An unplaced errand draws an amber line with `unplaced.text`; for `no_location` and `unroutable_location` the Edit button is the fix (the location autocomplete is there). A steered errand draws a "steered" chip.
- **PWA My Day** (`app.html`): both event projections (`:9559`, `:9707`) and the merge at `:10078` carry `why` through to the card; the errand modal shows the why line under the time and a **Steer** button beside Complete under Complete's own predicate (R4). The "Errands not placed" row (R3) lists unplaced errands with their reason and opens the same sheet. Buttons only, no anchors.
- **Board / kiosk `errand_list` cards**: the why line and the unplaced line only. No Steer on a wall every child can reach; the tick stays as it is.
- **Admin errand editor** (`errands.html` edit modal): the four steer fields as inputs beside the standing window, so an exact HH:MM pin is possible there.

### 4.6 The agent path

No new tool. `UpdateErrandTool` gains `skip_date` (appended), `pinned_date`, `pinned_start`, `pinned_end`, `once_driver_id`, `clear_steer`. `handle_update_errand` resolves the errand by uuid OR doc_id to its **doc_id** first (`storage.get_errand_by_id`) and writes every update and completion by doc_id (today's writer passes the uuid into `update_errand`, which expects the integer id, so even a repaired lookup would write nothing). Completion goes through `storage.complete_errand`. `handle_get_errands` returns the same `placement` / `unplaced` / `generation` the page reads. The `chat_actions` typed `update_errand` action keeps working (same handler).

## 5. Settings

`Settings.errand_dedicated_trip_mins: int = 25` (bounds 0–120 by validator) in `models/schemas.py`; registry entry in `settings_registry.py` (group `daily`, label "Prefer errands on the way", help "How many extra minutes a passing drive may add before a separate trip from home is worth it", page `errands`, anchor `errand-settings`); a number input bound to the key in the Errands settings drawer (`templates/errands.html`) under an element with that anchor id, saved through the drawer's existing partial save. Both registry audits (model coverage and UI binding) must pass, and a round-trip test saves and reads the value through `/api/settings`.

## 6. Tests, written first

`tests/test_errand_routing.py` (new). Fixture: named places on a grid; `matcher.errand_leg_minutes` stubbed to Manhattan minutes, `None` for a place not on the map; injectable `now` and `settings`.

1. **Near a route beats earlier from home, and did not before.** Kate's soccer run Tuesday passes the store with detour 20; Monday is empty with a 10-minute round trip. Old behaviour (asserted by running with `errand_dedicated_trip_mins = 0`): Monday. New: Tuesday on Jeff's leg to soccer, `why.kind == 'on_the_way'`, text names Soccer practice and +20.
2. **A driver's own event is a leg, not a window.** Lorena's work event Wednesday passes the pharmacy; it lands on her way to work, never inside the work event (R1).
3. **From home when nothing passes near**: `from_home`, earliest valid day, text says a trip from home.
4. **Unknown ranks last, grouped or not.** A grouped unknown candidate with detour 10 loses to a known ungrouped candidate with detour 20. Alone, the unknown one is placed with `why.kind == 'unknown_travel'` and `travel_to_mins is None`.
5. **No location and unroutable are reported, not placed.**
6. **Weekday filter.** A Tuesday-only errand never lands Monday.
7. **Finalization uses the winner's own day.** Winner on Monday with a driver who is not scanned last: `inserted_after_event_id` / `inserted_before_event_id` are Monday's, travel legs are the winner's.
8. **Order never decides.** Reverse the driver list and the day order: identical placement; two identical drivers tie by id.
9. **Candidate timing.** An empty day pinned 10–11 places at 10:00; an afternoon window on a day with a morning ride places after the ride; no intersection → `no_slot`.
10. **Precedence.** Pin outside the recurrence window wins; pin on a non-valid weekday wins; passed pin → `pinned_day_passed` and stays; pin beyond range → `pinned_day_not_in_range`; every day skipped → `every_day_skipped`; `once_driver_id` of a prohibited driver → `no_driver`.
11. **Steer round trip.** Not this day → Thursday's leg; Pick a day → that day; Someone else → that driver; Back to automatic → the scenario-1 placement.
12. **Completion.** Through `storage.complete_errand`: one-shot fields cleared; a weekly errand's successor has a new id, `starts_on` = anchor + 7 days, empty steer fields; completing twice mints nothing.
13. **Forgetting placements.** A cached row on a now-skipped day does not count as scheduled; `forget_errand_placements` removes the row and the note.
14. **Priming is bounded.** With a recording stub on `maps.prime_matrix_cache`: one call per errand per 24-location chunk, only uncached pairs, nothing under cache-only mode, no `UncachedTravelPair`.

`tests/test_errand_routing_api.py` (new, TestClient): `GET /api/errands` carries `placement.why`, `unplaced`, `generation`; PUT with a bad date → 422; PUT changing a steer field forgets placements and queues a refresh; the agent's `update_errand` by uuid and by doc_id both write (today's raises), `skip_date` appends, `clear_steer` clears, `is_completed` goes through `complete_errand`; `get_errands` returns the placement; the settings round trip and both registry audits.

`tests/test_errand_lists_render.py` (extend): the page row shows the why text and a Steer button when interactive with an editor; a card shows the why text and no Steer; an unplaced errand draws its reason; the sheet's PUT payload is the whole record. `tests/test_pwa_errand_steer.py` (new, node-run): a scheduled row → both projections → card → modal keeps `why`; Steer shows under Complete's predicate and not otherwise; the "Errands not placed" row appears for an unplaced errand and opens the sheet. Reachability: every steer field the tool accepts is reachable from the sheet or the admin editor (hand path for every agent capability).

Gate (never the full suite): the new files plus `test_errand_lists_render.py`, `test_solve_pack.py`, `test_storage.py`, `test_chat_actions.py`, `test_agent_v2_bridge.py`, `test_schedule_timeline.py`, `test_settings_registry.py` (both registry audits), `test_template_js.py`.

## 7. Not in this slice

- Standing per-person preferences. Slice 2 if wanted.
- Negotiation when a steer displaces someone else's plan.
- Route-geometry proximity; detour minutes is the proxy.
- Chaining several errands into one outing beyond today's `group_id` bonus.
- Errand rules: no change to matching, no PWA UI.

## 8. Who builds what

Codex adversarial-reviewed rev 1 (§10). Then, task by task from the plan: Claude writes the failing tests, Codex implements, Claude reviews each diff, runs the gate, updates `system_capabilities.md`, bumps `config.yaml` and commits. Never Codex reviewing Codex-built work.

## 9. Nothing removed

Tick, Reschedule (past due), Edit, Delete, every standing field, Complete on the phone and the agent's add/delete/get stay exactly as they are. Steering is additive.

## 10. Codex findings on rev 1 and where each landed

1 own events as drop-off windows → R1, §1. 2 unknown travel semantics → R5, §2.1, §3. 3 successor anchor and inherited steering → R6, §4.3. 4 cache scan defeats steering → §4.4. 5 unknown penalty vs group bonus → §2 lexicographic rank. 6 priming budget → §2.1. 7 precedence → §4.2. 8 Pick a time vs fixed candidate starts → §1 candidate timing. 9 phone recovery and skip-any-day parity → R3, §4.5. 10 uuid writes → §4.6. 11 weekday filter → Problem 4, §1, test 6. 12 finalization from the last iteration → Problem 4, §2, test 7. 13 replanning marker and note scoping → §3, §4.4. 14 PWA projections drop fields → §4.5, PWA test. 15 tie contradiction → §2 driver id. 16 headline fixture already green → test 1 (20 vs 10, with the old behaviour asserted). 17 filterless rules → Decision 3 corrected. 18 settings audits → §5. 19 travel diagnosis → Problem 2. 20 completion audience → R4. 21 date input on the phone → R2, validators §4.1. 22 full-record PUT → §4.5.
