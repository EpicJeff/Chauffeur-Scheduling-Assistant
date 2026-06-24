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
- **Location/Passenger Continuity:** `+1000` points if a driver handles consecutive events back-to-back with the same passenger or at the same location within 3 hours.

**Penalties:**
- **Travel Time:** `-10` points per minute of driving from the previous event's location to the next.
- **Preferred Hours Violation:** `-300` points if an event falls outside the driver's preferred working hours.
- **Soft Buffer Violation:** `-1000` points if an event slightly overlaps a buffer zone.

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
* `attendance_action: "dropoff_pickup"`: The driver will split the event into a distinct Drop-off (at the start time) and a Pickup (at the end time). The driver is free to do other things during the event duration.

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
- The Rules tab is divided into two sub-tabs: 'Routing Rules' and 'Priority Rules', controlled by Alpine.js state 
ulesSubTab.
- Rule creation forms are located at the top of each sub-tab, before the respective rule lists.



## Errands Scheduling Logic
- **Errands Inbox**: A dynamic management UI allows users to add errands using natural language.
- **Global Heuristic Errands Solver**: `matcher.py` intelligently places errands into gaps across the entire 7-day schedule. It targets a specific scheduling window based on the errand's `created_at` date and its `recurrence_rule` to prevent over-scheduling. It then finds the single gap across all valid dates that requires the least detour time without violating the master route structure.
- **Past Due State**: Errands that exceed their estimated scheduled time without being completed are placed in a `past_due` state. The solver safely ignores them so they stop auto-scheduling and wait for manual intervention.
- **Recurrence**: Errands can be set to recur Daily, Weekly, or Monthly upon completion. When marked complete, a new pending errand is generated automatically, which will reset the `created_at` anchor date, starting the cycle anew.
