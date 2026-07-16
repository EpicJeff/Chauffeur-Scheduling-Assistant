# Chauffeur Solver & AI Scheduling Assistant Capabilities

This document outlines the core logic, constraints, and weighting mechanics of the Chauffeur Scheduling Solver. It serves as the primary context layer for the AI Scheduling Assistant when parsing natural language into `Rule` JSON objects or when providing scheduling optimization advice.

## Core Solver Mechanics (CP-SAT)

The solver formulates the schedule by assigning drivers to events in a way that maximizes the global "weight" (score) while strictly adhering to hard constraints. 

### Baseline Event Weights & Penalties
When evaluating whether to assign an event to a driver or leave it unassigned:
- **Base Assignment Reward:** `1,000,000` (modified by `unassigned_penalty_multiplier` in Theme settings).
  - *Leaving an event unassigned scores `0`. If a driver's total score drops below 0 for an event, the solver will refuse to assign them and leave the event unassigned instead.*
  - *This value is deliberately large so that assigning an event at all outweighs routing preferences. Compare bonuses against each other, not against this base — it is identical for every driver on the same event and therefore cancels out when choosing between drivers.*
- **Priority Scaling Bonus:** `+150` points per rank. (e.g., Priority 1 driver gets `+1350`, Priority 10 gets `+0`).
- **Driver in Event (Attendee):** `+50,000,000` (Massive bonus if the driver is also attending the event. This is the largest term in the model apart from manual overrides, and in practice it decides the assignment on its own.)
- **Primary Driver Bonus:** `+2000` (modified by `primary_driver_bonus_multiplier`).
- **Manual Override:** `+100,000,000` (plus the override's `created_at` epoch seconds, so newer overrides win). Dominates every other term.
- **Group Bonus:** `+1000` when both events of a `group` rule go to the same driver.
- **Stickiness Bonus:** `+5` points if they drove the same event in the previous run.
- **Passenger Continuity:** Up to `+50,000` points if a driver handles consecutive events back-to-back with the same passenger. This decays linearly to `0` dynamically based on the specific travel gap threshold where a driver would typically have enough time to go home for a layover (e.g., 75+ minutes).
- **Location Continuity:** Up to `+5,000` points if a driver handles consecutive events at the exact same location, decaying linearly to `0` at a 3-hour gap.

**Penalties:**
- **Travel Time:** Scaled heavy penalty (approx `-600` points per 10 minutes) of driving from the previous event's location to the next. This penalty *only* applies if the gap between events is 1 hour or less, to avoid unfairly penalizing drivers for taking completely independent trips separated by long layovers at home.
- **Tolerance Overlap:** Heavy dynamic penalty (`-50,000`) if an event relies on a tolerance rule to be feasible for a primary driver. The penalty comfortably overcomes the primary driver bonus (`+2000`) and group bonus (`+1000`) combined, so the solver prefers a clean secondary driver over a primary driver who has to be late. It does **not** overcome the attendee bonus or a manual override, and it exactly ties the maximum passenger-continuity bonus (`+50,000`) — so at a near-zero travel gap, continuity can cancel it out.
- **Preferred Hours Violation:** `-2,000,000` points if an event falls outside the driver's preferred working hours. At default settings this drives the score below 0 (`1,000,000 - 2,000,000`) so the event stays unassigned. It does **not** hold if the driver is an attendee (`+50,000,000` swamps it) or if `unassigned_penalty_multiplier >= 2.0`.
- **Soft Buffer Violation:** `-2,000` points if an event slightly overlaps a buffer zone.

---

## Travel Time Data & Caching
Travel times come from Mapbox's Matrix API using the free-flow `driving` profile (no traffic-aware profile is requested anywhere, and cached reads always report a traffic delay of `0`). Durations are therefore treated as **static**: a cached value for a pair of fixed addresses does not go stale, and the solver reads them without an age check.
- **Priming**: each schedule refresh primes only the location pairs it does not already have. Stale-but-valid pairs are never re-purchased — doing so previously exceeded the 100,000 element/month Matrix allowance.
- **`route_cache_duration_mins`**: defaults to `43200` (30 days). It only needs shortening if a traffic-aware profile is introduced.
- **Unroutable pairs**: when a location cannot be geocoded or the routing APIs fail, the pair is cached as `-1` and reported to the solver as `900` minutes (effectively unreachable). This suppresses retry storms against the API quota, but expires after **24 hours** so that a transient outage cannot permanently poison the cache.

---

## Storage Engine
All persistence goes through `services/storage.py`, backed by **SQLite** (`data/chauffeur.sqlite3` locally, `/data/chauffeur.sqlite3` on the HA add-on) as of 2026-07-16. It is a document store — one table per legacy TinyDB table, each row `(doc_id, JSON data)` — accessed via a TinyDB-compatible table API (`services/storage_sqlite.py`), so callers still pass `tinydb.Query` objects. WAL mode; writes are single-row and take ~1 ms (previously TinyDB rewrote the entire 4.8 MB JSON file per write, ~275 ms).
- **Toggle**: `CHAUFFEUR_STORAGE=tinydb` env var is a one-release escape hatch back to the legacy engine; `CHAUFFEUR_DATA_DIR` redirects the data directory (used by tests, which must never touch `data/`).
- **Migration**: first sqlite boot auto-migrates `db.json` + `routes_cache.json` (route geometry now lives in the same SQLite file), preserving doc_ids and deduplicating the distance/geocode caches; originals are kept as `*.pre-sqlite.bak`. Restore-from-JSON = delete the `.sqlite3` file, place a `db.json`, restart.
- **Backups**: `/api/download_db` zips the data dir, snapshotting the SQLite file via the backup API (safe under WAL).
- **`db_lock`**: the coarse process-wide lock in storage.py is still in place (cheap now); removing it is a separate planned cleanup.

---

## Rule Attributes & Filters
Every rule (Routing Rule or Priority Rule) can filter events using any combination of the following criteria. The solver evaluates these using AND logic across different criteria types.
- **Keywords**: Match substrings in the event title or description. (Match Any or Match All).
- **Passengers**: Match specific passengers who are attending the event. (Match Any or Match All).
- **Days of Week**: Restrict rules to specific days (0=Monday, 6=Sunday).
- **Date Window (`start_date`, `end_date`)**: Restrict a rule to only apply on or after a specific start date (YYYY-MM-DD), and/or on or before an end date. Useful for driver vacations, summer schedules, or holiday-specific rules.
- **Time Window (`time_start`, `time_end`)**: Restrict a rule to a specific time of day window.
- **Location**: Match a substring in the event location.

---

## Supported Constraints (`constraint_type`)

When generating JSON for the frontend to digest, use the following `constraint_type` mappings.

### 1. Driver Assignment
Controls how the solver treats a specific driver for an event. Each of these is its own top-level `constraint_type` value — there is **no** `"assignment"` constraint_type and **no** `assignment_type` property. `Rule` has no such field, so a rule shaped that way is silently discarded by the schema and does nothing.

All four require `driver_id` to name the driver the rule applies to.

* `constraint_type: "required"` (Hard Constraint)
  * The selected driver MUST be assigned. All other drivers are strictly prohibited. The named driver also receives a `+500` weight bonus.
* `constraint_type: "preferred"` (Weight Bonus)
  * Grants a massive `+10000` weight bonus to the selected driver. They will almost certainly get the assignment unless physically impossible.
* `constraint_type: "unavailable"` (Hard Constraint)
  * The selected driver is strictly forbidden from taking the event.
* `constraint_type: "avoid"` (Soft Penalty)
  * Caps the driver's score at `1` — above `0` (the score of leaving the event unassigned) but below every viable driver. The driver is pushed to the absolute bottom of the priority list yet is still chosen as a "last resort" rather than leaving the event unassigned. A driver already excluded for another reason (e.g. a preferred-hours violation, which yields a negative score) stays excluded; `avoid` never resurrects them.

### 2. Duplicate Event Handling (`constraint_type: "duplicate"`)
For recurring events or overlapping schedules.
* `duplicate_action: "schedule_one"`: The solver will only schedule *one* matching event per `grouping_period` (daily, weekly, monthly, all).
* `duplicate_action: "schedule_all"`: Schedule all occurrences as normal.

### 3. Tolerance - Late Arrival / Early Departure (`constraint_type: "tolerance"`)
Allows an event to be "fudged" to make an otherwise impossible schedule fit.
* `tolerance_mins`: Integer. How many minutes the solver is allowed to overlap.
* `tolerance_type`: `"arrival"`, `"departure"`, or `"both"`.

### 4. Group Events (`constraint_type: "group"`)
Forces the solver to assign the exact same driver to a set of different events.
* Uses the `filter_sets` array instead of standard keyword/passenger filters. Each element in the array represents a distinct event match (e.g., grouping Lily's 8:00am swim practice with James's 9:00am tennis practice).

### 5. Buffer Time (`constraint_type: "buffer"`)
Enforces artificial padding around an event for a driver.
* `buffer_before_mins`: Integer.
* `buffer_after_mins`: Integer.

### 6. Event Attendance (`constraint_type: "attendance"`)
* `attendance_action: "stay"`: The driver must stay at the event for its entire duration.
* `attendance_action: "dropoff_pickup"`: The driver will split the event into a distinct Drop-off (at the start time) and a Pickup (at the end time). The driver is free to do other things during the event duration. The Drop-off and Pick-up are treated as independent events and are NOT grouped together, meaning they can be freely assigned to different drivers.

---

## Priority Rules (`PriorityRule` objects)
Distinct from standard rules, priority rules allow dynamic modification of the `Base Assignment Reward` (`1,000,000`) on an event-by-event basis. The `weight_modifier` is added to that base verbatim — there is no rescaling or remapping.
- **Why use this?** If the user says "Doctor appointments are the most important thing to schedule," you create a Priority Rule with `keywords: ["Doctor"]` and `weight_modifier: 100000`. This ensures the solver prioritizes finding *any* driver for the doctor appointment before solving other low-priority events.
- **Choosing a magnitude.** The modifier only matters relative to the *other* terms it competes with, since the base is identical across events. Useful reference points: `1000` is a mild nudge (enough to break a tie, roughly 17 minutes of travel penalty); `100,000` outranks the maximum passenger-continuity bonus (`+50,000`); `500,000` is effectively "schedule this before anything else." Negative values deprioritize. Nothing outranks the attendee bonus or a manual override.

## Matching Logic
- **AND vs OR:** Across different criteria types in a single rule (e.g., Keywords AND Passengers AND Days), the solver uses `AND` logic. An event must meet all configured criteria types.
- **Match Any vs Match All:** For criteria that support multiple selections (Keywords, Passengers), the solver defaults to "Match Any" (OR logic). 
  - For example, if two passengers are selected, the rule matches if *either* is an attendee.
  - This behavior can be toggled using the `keywords_match_all` and `passengers_match_all` boolean flags. When set to `true`, the solver switches to "Match All" (AND logic) for that specific criterion, requiring all listed keywords or passengers to be present on the event for the rule to match.
- **Filter Sets (Groups):** For grouped rules with multiple `filter_sets`, the evaluation across sets is an `OR` logic (matches if it hits Group A OR Group B).

## Best Practices for AI Recommendations
1. **Never use "Avoid" to completely block a driver.** If the driver absolutely cannot do it, use `unavailable`. Only use `avoid` if the driver should be a last resort.
2. **Use Group Events sparingly.** Grouping large chains of events can drastically reduce solver feasibility (making it "too sticky").
3. **Recommend Tolerance for tight schedules.** If the user complains that events are going unassigned due to 5-10 minute overlaps, recommend adding a `tolerance` rule to allow minor late arrivals.


## User Interface Architecture
- The Rules tab is divided into two sub-tabs: 'Routing Rules' and 'Priority Rules', controlled by Alpine.js state.
- Rule creation forms are located at the top of each sub-tab, before the respective rule lists.
- **Kiosk Mode (`?kiosk=true`)**: A streamlined display state that hides the triage inbox and converts the full sidebar chat into a floating popup, maintaining chat history while maximizing schedule visibility.
- **HA Theme (`?theme=ha`)**: Supports Home Assistant integrations via CSS variable propagation without overwriting the core Tailwind configuration palette. State is persisted across navigation views.
- **Dynamic Drive Times**: The UI intelligently handles drive-time calculations when errands are toggled off. It accumulates the time of the hidden `A -> Errand` and `Errand -> B` edges so the gap accurately reflects the total actual drive time.
- **Calendar Passenger Resolution**: The `calendar.html` view shares the same deep passenger resolution logic as the dashboard, analyzing `matched_rules` to display non-attendee passengers as colorful pills.
- **Triage Diagnostics**: When an event cannot be scheduled, it falls into the "Unassigned" triage bucket. The solver provides granular diagnostics per driver. If an event has multiple passengers and one of them causes a physical overlap conflict (double booking) with another scheduled event, the UI intelligently catches the `passenger_conflict` diagnostic type and presents a one-click button to drop the conflicting passenger from that specific event instance.

## Errands Scheduling Logic
- **Errands Inbox**: A dynamic management UI allows users to add errands using natural language.
- **Errand Rules Engine & Routing Rules Integration**: Errands intelligently respect global Routing Rules (Event Rules) dynamically. If a driver is marked "Unavailable" or "Avoid" for a specific time window or day, the global errand solver evaluates these constraints against the exact proposed `start_time` of each scheduled gap to accurately prevent assignment. Furthermore, errands support advanced native options (Driver Assignment, Passenger Constraints, Time of Day, Day of Week Restrictions, Buffer & Tolerance, Grouping) configured via the Errand Rules Engine or directly on the Errand.
- **Global Heuristic Errands Solver**: `matcher.py` intelligently places errands into gaps across the entire 7-day schedule, including **intra-event gaps** inside scheduled events (e.g., between a drop-off and pickup). It targets a specific scheduling window based on the errand's `created_at` date and its `recurrence_rule` to prevent over-scheduling. It then finds the single gap across all valid dates that requires the least detour time without violating the master route structure or any Errand Rules constraints.
- **Past Due State**: Errands that exceed their estimated scheduled time without being completed are placed in a `past_due` state. The solver safely ignores them so they stop auto-scheduling and wait for manual intervention.
- **Recurrence**: Errands can be set to recur Daily, Weekly, or Monthly upon completion. When marked complete, a new pending errand is generated automatically, which will reset the `created_at` anchor date, starting the cycle anew.
- **AI Agent POI / Category Search**: The AI agent is capable of looking up Points of Interest (POIs) such as gas stations, coffee shops, and groceries, and routing them based on the proximity of a driver's existing route stops. It leverages Mapbox's Category Search and Forward API with independent rate limiting.
- **Trip POIs as Bounded Errands**: Trip Points of Interest (POIs) act as specialized dynamic errands. They are automatically constrained strictly to the date range of the Trip event and can enforce Day of Week Restrictions to schedule around crowds or closures. The solver schedules them opportunistically within the trip's time window, correctly adapting and localizing logic to the trip's destination timezone. It uses intelligent slot-scoring to prefer geographically close POIs on the same day (using Mapbox travel times), and applies strict Meal Block constraints for `food` POIs (Max 1 Lunch from 11-14, Max 1 Dinner from 17-21 per day), while intelligently treating desserts/sweets as flexible, highly-scored adjacent events. The bulk scheduler uses **hard day-of-week filtering** when clustering regular POIs to background anchors: if a regular POI has `valid_days_of_week` set, it will never be assigned to a background anchor whose `valid_days_of_week` doesn't overlap, preventing mismatches when multiple background POIs exist at the same location on different days (e.g. EPCOT Day 1 vs Day 3).
- **Live Pricing Integration**: The UI can fetch real-time "Live Prices" for flights and accommodations within a trip using the SerpApi via the `/api/trip/{trip_id}/live_pricing` endpoint. These fetched prices are marked with `is_live_price = True` to render a "Live" badge and provide accurate trip budgeting without repeatedly depleting free-tier API quotas. If the user hits their 250 requests/month SerpApi limit, the system gracefully falls back to Deep Links to Google Flights and Hotels.

## Background Trip Events
- **Trip Passenger Constraint**: If an event overlaps with a background trip and **ALL** passengers on the event are also on the background trip, the solver strictly enforces that non-trip drivers cannot be assigned to it. (Conversely, if at least one passenger on the local event is NOT on the background trip, the event is allowed to be scheduled locally). It also ensures that if a trip driver *is* assigned, the event must be geographically close (within 60 minutes) to the trip's location. This acts as an absolute block, taking precedence over any manual driver overrides or recurring assignment rules, preventing home-based events from being mistakenly scheduled while the family is on vacation.

## Draft Trips & AI Scheduling
- **Draft-First Creation**: All newly generated trips (whether Exact Dates or Flexible Dates) are securely stored locally as Draft Trips in the backend JSON database, protecting the user's primary Google Calendar from unconfirmed events while iterating.
- **Smart Calendar Analysis**: The agent queries Google Calendar for upcoming free/busy schedules and intelligently cross-references this with destination-specific seasonal heuristics (e.g. avoiding hurricanes) to suggest an optimal booking window via the `/api/trip/{event_id}/suggest_dates` endpoint.
- **Budget Compliance**: For trip plan generation, the backend enforces the `budget_max_usd` property automatically. It intercepts the LLM output, sums the `estimated_price_usd` for all generated POIs, accommodations, and flights, and forcibly injects a warning payload to the chat context if the total exceeds the budget, preventing the LLM from silently ignoring constraints.
- **Strict Day-of-Week Mapping**: The background LLM mapping `valid_days_of_week` uses an absolute Monday=0 index, rejecting relative "Day X" labels to ensure POIs correctly map to absolute dates when solving in a mock calendar future environment.

## Trip Itinerary Scheduling (CP-SAT, services/trip_scheduler.py)
The trip itinerary is built by a two-level scheduler (design: `docs/trip_scheduler_design.md`), replacing the old greedy slot-scanner:
- **Level 1 (global assignment)**: A CP-SAT model assigns every POI to a `(day, block)` slot simultaneously. Each trip day has a block skeleton: `breakfast` 07:30–09:30, `morning` 09:00–12:00 (≤180 active mins), `lunch` 11:30–13:30, `afternoon` 13:00–17:30 (≤270), `dinner` 17:30–20:30, `evening` 20:00–23:00 (≤150). Distances for clustering use haversine on stored `lat`/`lng` — zero Mapbox calls during solving.
- **Level 2 (timing)**: Deterministic code lays concrete clock times onto each day (nearest-neighbor order within blocks, real cached travel times between consecutive stops, meals anchored toward 08:00/12:00/18:30, 5-minute snapping).
- **Meal intelligence**: `meal_type` ('breakfast'|'brunch'|'lunch'|'dinner'|'dessert'|'snack') and `dining_style` ('quick'|'casual'|'fine') on TripPOI drive placement. Fine dining → dinner block. At most one non-dessert meal per meal block per day. Desserts/snacks go in activity blocks, with a bonus for evening-after-dinner. Food without `meal_type` may take lunch or dinner. Legacy POIs infer meal type from `ideal_time_start`.
- **Anchors (background POIs)**: `is_background=true` + `days_claimed=N` makes a POI claim N full days (one POI — no more "(Day 1)/(Day 2)" clones; `claimed_dates` records the exact local dates). Claims are consecutive by default (soft), but a `valid_days_of_week` on the anchor is a HARD subset constraint (3 days + Mon/Wed/Fri = exactly Mon, Wed, Fri). At most one anchor per day. Children link via `parent_container` (background POI id) and may only be placed on the parent's claimed days. On a claimed day the distance "home base" switches from the accommodation to the anchor, so any POI is welcome on that day in proportion to its proximity to the anchor. Anchors generalize beyond theme parks (e.g. "Explore the Eiffel Tower district").
- **Objective tiers**: placement rewards by `priority` (must 10M / want 1M / stretch 100k) dominate; then soft-rule weights (default 50k); then shaping terms (−300/haversine-min from the day's base, −100/min between same-day pairs, day-balance −30/min beyond a 60-min deadband, claim-span −40k/day, dessert-after-dinner +20k). `ideal_time_start/end` is now a SOFT block preference (−20k off-window), never a hard failure.
- **Explainable failures**: unscheduled POIs stream a concrete `reason` ("restricted to Sat/Sun but the trip includes none of those days", "its parent 'Epcot' was not scheduled", "all eligible dinner slots were taken (N slots, M competitors)") plus `suggested_fixes` actions (`clear_days`, `disable_rule`) consumed by the failure modal in trip.html.
- **Incremental solves**: already-scheduled POIs are locked to their current day/block; adding POIs never reshuffles existing days (times within an affected day may adjust).

## Trip Rules (`TripRule` objects)
Per-trip scheduling rules stored in `TripMetadata.rules`, mirroring the driving Rule system. The AI agent creates/manages them via the `manage_trip_rules` tool (create/list/enable/disable/delete); the trip page shows a read-only Rules panel with an enable/disable toggle (`GET/PATCH /api/trip/{event_id}/rules`). Pydantic rejects unknown fields (`extra='forbid'`) — emit exactly the documented fields.
- `rule_type` values and their parameters:
  - `day_restriction` — matched POIs only on `days_of_week` (0=Mon..6=Sun) and/or `trip_days` (1-indexed). "Epcot on Tuesday".
  - `block_restriction` — matched POIs only in `blocks` (breakfast|morning|lunch|afternoon|dinner|evening). "Boat tour in the morning".
  - `budget_cap` — sum of matched POIs' `estimated_price_usd` ≤ `max_usd`. "Keep dinners under $100".
  - `day_capacity` — active minutes on matched days ≤ `max_active_mins`. "Keep Tuesday light".
  - `keep_clear` — nothing scheduled on matched `trip_days`/`days_of_week` × `blocks` (all blocks if unset). Defaults to HARD. "Leave Thursday afternoon free".
  - `spacing` — ≥ `min_gap_days` between matched POIs/anchors. "No two parks back-to-back".
  - `template_override` — trip-wide block changes: disable listed `blocks`, and/or clamp the day with `template_start`/`template_end` ('HH:MM'). "Nothing before 9am".
- Selectors: `poi_ids`, `categories`, `keywords` (name/description substring). Empty selectors match all POIs.
- `hardness`: 'soft' (weighted, default) or 'hard' (constraint). Agent-created rules default soft except `keep_clear`; escalate to hard only on emphatic user language. Soft `weight` default 50,000 (rule preferences outrank shaping terms but never placement rewards).
- POI fields (`valid_days_of_week`, `meal_type`, `dining_style`, `parent_container`, `days_claimed`, opening hours) compile into the same constraint pipeline as stored rules; the Rules panel lists them under "Derived from POI settings".
