# Chauffeur Solver & AI Scheduling Assistant Capabilities

This document outlines the core logic, constraints, and weighting mechanics of the Chauffeur Scheduling Solver. It serves as the primary context layer for the AI Scheduling Assistant when parsing natural language into `Rule` JSON objects or when providing scheduling optimization advice.

## Core Solver Mechanics (CP-SAT)

The solver formulates the schedule by assigning drivers to events in a way that maximizes the global "weight" (score) while strictly adhering to hard constraints. 

### Baseline Event Weights & Penalties
When evaluating whether to assign an event to a driver or leave it unassigned:
- **Base Assignment Reward:** `100` (modified by `unassigned_penalty_multiplier` in Theme settings).
  - *If a driver's total score drops below 0 for an event, the solver will refuse to assign them and leave the event unassigned instead.*
- **Priority Scaling Bonus:** `+150` points per rank. (e.g., Priority 1 driver gets `+1350`, Priority 10 gets `+0`).
- **Driver in Event (Attendee):** `+5000` (Massive bonus if the driver is also attending the event).
- **Primary Driver Bonus:** `+2000` (modified by `primary_driver_bonus_multiplier`).
- **Stickiness Bonus:** `+5` points if they drove the same event in the previous run.
- **Passenger Continuity:** Up to `+50,000` points if a driver handles consecutive events back-to-back with the same passenger. This decays linearly to `0` dynamically based on the specific travel gap threshold where a driver would typically have enough time to go home for a layover (e.g., 75+ minutes).
- **Location Continuity:** Up to `+5,000` points if a driver handles consecutive events at the exact same location, decaying linearly to `0` at a 3-hour gap.

**Penalties:**
- **Travel Time:** Scaled heavy penalty (approx `-600` points per 10 minutes) of driving from the previous event's location to the next. This penalty *only* applies if the gap between events is 1 hour or less, to avoid unfairly penalizing drivers for taking completely independent trips separated by long layovers at home.
- **Tolerance Overlap:** Heavy dynamic penalty (`-50,000`) if an event relies on a tolerance rule to be feasible for a primary driver. The penalty overcomes the primary driver bonus and group bonus combined, ensuring the solver will always prefer a clean secondary driver over a primary driver who has to be late.
- **Preferred Hours Violation:** `-2,000,000` points if an event falls outside the driver's preferred working hours, which causes the event score to drop below 0 and remain unassigned.
- **Soft Buffer Violation:** `-2,000` points if an event slightly overlaps a buffer zone.

---

## Supported Constraints (`constraint_type`)

When generating JSON for the frontend to digest, use the following `constraint_type` mappings.

### 1. Driver Assignment (`constraint_type: "assignment"`)
Controls how the solver treats specific drivers for an event. Requires the `assignment_type` property.

* `assignment_type: "required"` (Hard Constraint)
  * The selected driver MUST be assigned. All other drivers are strictly prohibited.
* `assignment_type: "preferred"` (Weight Bonus)
  * Grants a massive `+10000` weight bonus to the selected driver. They will almost certainly get the assignment unless physically impossible.
* `assignment_type: "unavailable"` (Hard Constraint)
  * The selected driver is strictly forbidden from taking the event.
* `assignment_type: "avoid"` (Soft Penalty)
  * Subjects the driver to a massive penalty but establishes a "score floor" of `1`. This means the driver will be pushed to the absolute bottom of the priority list, but will still be chosen as a "last resort" rather than leaving the event unassigned.

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
Distinct from standard rules, priority rules allow dynamic modification of the `Base Assignment Reward` (`100`) on an event-by-event basis.
- **Why use this?** If the user says "Doctor appointments are the most important thing to schedule," you create a Priority Rule with `keywords: ["Doctor"]` and `weight_modifier: 10000`. This ensures the solver prioritizes finding *any* driver for the doctor appointment before solving other low-priority events.

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

## Errands Scheduling Logic
- **Errands Inbox**: A dynamic management UI allows users to add errands using natural language.
- **Errand Rules Engine & Direct Options**: Errands support advanced options (Driver Assignment, Passenger Constraints, Time of Day, Day of Week Restrictions, Buffer & Tolerance, Grouping) applied via an allowed/required/prohibited 3-state logic. These constraints can be configured *globally* via the Errand Rules Engine (matching by keywords/locations), or applied *directly* to individual Errands as one-off constraints.
- **Global Heuristic Errands Solver**: `matcher.py` intelligently places errands into gaps across the entire 7-day schedule, including **intra-event gaps** inside scheduled events (e.g., between a drop-off and pickup). It targets a specific scheduling window based on the errand's `created_at` date and its `recurrence_rule` to prevent over-scheduling. It then finds the single gap across all valid dates that requires the least detour time without violating the master route structure or any Errand Rules constraints.
- **Past Due State**: Errands that exceed their estimated scheduled time without being completed are placed in a `past_due` state. The solver safely ignores them so they stop auto-scheduling and wait for manual intervention.
- **Recurrence**: Errands can be set to recur Daily, Weekly, or Monthly upon completion. When marked complete, a new pending errand is generated automatically, which will reset the `created_at` anchor date, starting the cycle anew.
- **AI Agent POI / Category Search**: The AI agent is capable of looking up Points of Interest (POIs) such as gas stations, coffee shops, and groceries, and routing them based on the proximity of a driver's existing route stops. It leverages Mapbox's Category Search and Forward API with independent rate limiting.
- **Trip POIs as Bounded Errands**: Trip Points of Interest (POIs) act as specialized dynamic errands. They are automatically constrained strictly to the date range of the Trip event and can enforce Day of Week Restrictions to schedule around crowds or closures. The solver schedules them opportunistically within the trip's time window, correctly adapting and localizing logic to the trip's destination timezone. It uses intelligent slot-scoring to prefer geographically close POIs on the same day (using Mapbox travel times), and applies strict Meal Block constraints for `food` POIs (Max 1 Lunch from 11-14, Max 1 Dinner from 17-21 per day), while intelligently treating desserts/sweets as flexible, highly-scored adjacent events.
- **Live Pricing Integration**: The UI can fetch real-time "Live Prices" for flights and accommodations within a trip using the SerpApi via the `/api/trip/{trip_id}/live_pricing` endpoint. These fetched prices are marked with `is_live_price = True` to render a "Live" badge and provide accurate trip budgeting without repeatedly depleting free-tier API quotas. If the user hits their 250 requests/month SerpApi limit, the system gracefully falls back to Deep Links to Google Flights and Hotels.

## Background Trip Events
- **Trip Passenger Constraint**: If an event overlaps with a background trip and involves passengers who are on that trip, the solver strictly enforces that non-trip drivers cannot be assigned to it. It also ensures that if a trip driver *is* assigned, the event must be geographically close (within 60 minutes) to the trip's location. This acts as an absolute block, taking precedence over any manual driver overrides or recurring assignment rules, preventing home-based events from being mistakenly scheduled while the family is on vacation.

## Draft Trips & AI Scheduling
- **Draft-First Creation**: All newly generated trips (whether Exact Dates or Flexible Dates) are securely stored locally as Draft Trips in the backend JSON database, protecting the user's primary Google Calendar from unconfirmed events while iterating.
- **Smart Calendar Analysis**: The agent queries Google Calendar for upcoming free/busy schedules and intelligently cross-references this with destination-specific seasonal heuristics (e.g. avoiding hurricanes) to suggest an optimal booking window via the `/api/trip/{event_id}/suggest_dates` endpoint.
- **Budget Compliance**: For trip plan generation, the backend enforces the `budget_max_usd` property automatically. It intercepts the LLM output, sums the `estimated_price_usd` for all generated POIs, accommodations, and flights, and forcibly injects a warning payload to the chat context if the total exceeds the budget, preventing the LLM from silently ignoring constraints.
F i x e d   a   b u g   w h e r e   B a c k g r o u n d   P O I s   c o m m i t t e d   t o   G o o g l e   C a l e n d a r   w e r e   b e i n g   m i s t a k e n l y   c l a s s i f i e d   a s   A c c o m m o d a t i o n s   b y   t h e   S t a n d a r d   S c h e d u l i n g   E n g i n e   ( d u e   t o   t h e m   b o t h   u s i n g   t h e   \ 	 r i p _ b a c k g r o u n d \   e v e n t   t y p e   w i t h o u t   c h e c k i n g   \ p o i _ i d \ ) .   T h i s   r e s u l t e d   i n   t h e   T h e m e   P a r k   b e i n g   t r e a t e d   a s   t h e   h o m e   b a s e   h o t e l ,   a n d   c a u s i n g   t h e   t r a v e l   t i m e   c a l c u l a t i o n s   t o   f a i l   a n d   t h e   s l o t s   t o   b e   r e j e c t e d .  
 