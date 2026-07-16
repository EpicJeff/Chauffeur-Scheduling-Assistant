# Trip Itinerary Scheduler v2 — Design

Status: **IMPLEMENTED** (v2.7.0 — `services/trip_scheduler.py`, tests in `tests/test_trip_scheduler.py`)
Replaces: the greedy slot-scanner in `services/trip_planner.py` (`schedule_poi` / `schedule_pois_bulk`)

## 1. Goals

- Itineraries that "feel right": day-shaped plans (morning activity, lunch, afternoon, dinner, evening), geographically clustered, balanced across the trip instead of front-loaded.
- Correct handling of **container POIs** (Magic Kingdom, Epcot) that claim whole days and host child POIs (character dining, rides), including multi-day visits.
- Meal intelligence by declared type (`meal_type`, `dining_style`), not keyword sniffing — fine dining lands in dinner slots.
- A **TripRule** engine mirroring the driving-schedule `Rule` system: POI settings compile to rules, and the AI agent can create rules from natural language ("keep Tuesday light", "no mornings").
- Explainable failures: "couldn't honor both X and Y — which bends?" instead of "no available time slot".
- Near-zero Mapbox cost during solving.

Non-goals: exact minute-level optimization inside the solver (times are laid out deterministically afterward); UI redesign (existing endpoints and NDJSON streaming contract are preserved).

## 2. Why the current scheduler is replaced, not patched

The current design places POIs one at a time, greedily, scanning every 5-minute slot and scoring it with ~30 interacting magic numbers. Its structural defects:

| Defect | Where |
|---|---|
| Insertion order determines the outcome; three competing sort keys try to guess a good order | `schedule_pois_bulk` |
| `+100` decaying day bonus front-loads the trip | `find_slots` score |
| Containers linked to children by "travel ≤ 30 min", not by identity | anchor clustering |
| Multi-day parks = cloned "(Day 1)/(Day 2)" POIs + `+0.01` load-balance epsilon | `generate_trip_pois` |
| Dessert detection by substring (`'sweet'`, `'cafe'`) | `schedule_poi` |
| LLM clock-string guesses (`ideal_time_start`) enforced as near-hard (±15 min) | `find_slots` |
| Travel > 60 min treated as **zero** buffer | overlap check |
| Mapbox calls inside a ~2,000-iteration slot loop | `find_slots` |

Placement decisions here interact (meal exclusivity, clustering, container days, day capacity). Greedy commits blind and never revisits; no amount of weight tuning fixes that. The 13 `trip_planner_hacked*.py` iterations are the empirical evidence.

## 3. Architecture overview

```
LLM (suggestions)          TripRule engine              Scheduler
─────────────────          ────────────────             ─────────────────────────────
generate_trip_pois /       built-in template rules      Level 1: CP-SAT assigns each
generate_trip_plan    ──►  + implicit rules from   ──►  POI to (day, block), globally
emits meal_type,           POI fields                   Level 2: deterministic clock
dining_style,              + agent-created rules        times within each day from the
parent_container,          (NL → TripRule JSON)         block template + real travel
days_claimed                                            times
```

- **Level 1 (CP-SAT)** decides structure: which day, which block, which days each container claims. Search space for a 7-day / 30-POI trip is ~1,300 booleans — solves in milliseconds. Distances use **haversine from stored `lat`/`lng`** (zero API calls).
- **Level 2 (plain code)** lays concrete times onto each day: template windows + real cached travel times between consecutive stops (~5–8 Directions lookups per day, mostly cache hits).

Both levels live in a new module `services/trip_scheduler.py`. LLM generation stays in `trip_planner.py`.

## 4. Day/block template

All block logic runs in the **trip's local timezone**. Stored timestamps remain UTC (unchanged).

| Block | Window (local) | Kind | Capacity |
|---|---|---|---|
| `breakfast` | 07:30–09:30 | meal | 1 meal |
| `morning` | 09:00–12:00 | activity | ≤ 180 active mins |
| `lunch` | 11:30–13:30 | meal | 1 meal |
| `afternoon` | 13:00–17:30 | activity | ≤ 270 active mins |
| `dinner` | 17:30–20:30 | meal | 1 meal |
| `evening` | 20:00–23:00 | activity | ≤ 150 active mins |

Windows overlap deliberately — blocks are *ordinal slots*; windows guide Level 2 timing, they are not hard fences. The template is data, overridable per-trip by a `template_override` rule ("we're not morning people" → shift start to 10:00, or disable `breakfast`).

Arrival/departure days are truncated: blocks before check-in / after check-out on those days are removed (flight times, when known, set the cut).

## 5. Data model changes

### 5.1 `TripPOI` — new fields (additive)

```python
meal_type: Optional[str] = None      # 'breakfast'|'brunch'|'lunch'|'dinner'|'dessert'|'snack'
dining_style: Optional[str] = None   # 'quick'|'casual'|'fine'
parent_container: Optional[str] = None  # id of the background POI this lives inside
days_claimed: int = 1                # background POIs only: number of full days
```

Semantics changes:
- **Multi-day parks**: one background POI with `days_claimed=3` replaces three "(Day N)" clones. At commit time, N calendar events are created (one per claimed day). `occurrences` cloning remains only for genuinely repeated non-background activities ("two surf lessons").
- `ideal_time_start/end` are kept as **optional user overrides** that compile to a soft block restriction. The LLM is no longer asked to invent them.
- Scheduled output unchanged: `is_scheduled`, `scheduled_start`, `scheduled_end`, `event_id`.

### 5.2 `TripRule` — new model

Mirrors the driving `Rule` shape, but with `extra='forbid'` so phantom fields fail loudly (lesson from the `assignment_type` incident).

```python
class TripRule(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    description: str                  # human-readable, shown in chat / future UI
    rule_type: str                    # see vocabulary below
    # --- selectors (empty = not filtering on that axis) ---
    poi_ids: List[str] = []
    categories: List[str] = []        # 'food', 'sightseeing', ...
    keywords: List[str] = []          # matched against POI name/description
    # --- parameters (used per rule_type) ---
    days_of_week: List[int] = []      # 0=Mon .. 6=Sun
    trip_days: List[int] = []         # 1-indexed day of trip ("day 3")
    blocks: List[str] = []            # 'breakfast'..'evening'
    max_usd: Optional[float] = None
    max_active_mins: Optional[int] = None
    min_gap_days: Optional[int] = None
    template_start: Optional[str] = None   # 'HH:MM' template_override only
    template_end: Optional[str] = None
    # --- semantics ---
    hardness: str = 'soft'            # 'hard' | 'soft'
    weight: int = 50_000              # soft rules only
    is_ai_generated: bool = False
    is_enabled: bool = True
```

Stored on the trip: `TripMetadata.rules: List[TripRule] = []`.

### 5.3 Rule vocabulary v1 (seven types — grow only on real demand)

| `rule_type` | Meaning | Example NL trigger |
|---|---|---|
| `day_restriction` | Matched POIs only on given `days_of_week`/`trip_days` | "Epcot on Tuesday — lower crowds" |
| `block_restriction` | Matched POIs only in given `blocks` | "the boat tour must be in the morning" |
| `budget_cap` | Sum of `estimated_price_usd` of matched POIs ≤ `max_usd` | "keep dinners under $100" |
| `day_capacity` | Active mins on matched days ≤ `max_active_mins` | "keep Tue–Thu light, grandma's with us" |
| `keep_clear` | Nothing scheduled in the matched `trip_days`/`days_of_week` × `blocks` (all blocks if unset) | "leave Thursday afternoon free", "keep day 4 clear for the pool" |
| `spacing` | ≥ `min_gap_days` between matched POIs | "no two parks back-to-back" |
| `template_override` | Adjust/disable blocks for the whole trip | "nothing before 9am" |

There is deliberately no first-class "rest block" concept (decided): downtime is the *absence* of scheduling, expressed as `keep_clear` (specific days/blocks) or `day_capacity` (lighter days). `keep_clear` defaults to **hard** — when a user asks for free time, an activity quietly appearing there is a broken promise.

**Compilation targets:**

| Rule | Hard | Soft |
|---|---|---|
| `day_restriction` | forbid `x[p,d,·]` on other days | penalty `weight` per placement on other days |
| `block_restriction` | forbid other blocks | penalty per off-block placement |
| `budget_cap` | linear sum constraint over `scheduled[p]` | penalty × overshoot (scaled) |
| `day_capacity` | linear sum per day | penalty × overshoot |
| `keep_clear` | forbid `x[·,d,k]` on matched (day, block) combos | penalty per placement in the cleared zone |
| `spacing` | day-distance reification | penalty per violating pair |
| `template_override` | rewrites the template pre-solve (always "hard") | — |

**Implicit rules** compiled from POI fields at solve time (same pipeline, no second code path):
- `valid_days_of_week` → hard `day_restriction`
- `meal_type`/`dining_style` → `block_restriction` (see §6 meal matrix)
- `parent_container` → containment constraint (§6)
- `priority` → the POI's placement reward tier (§7)
- `ideal_time_start/end` → soft `block_restriction` (window mapped to nearest blocks)
- `opening_hours` (parsed) → hard `block_restriction` to blocks overlapping the open window

**Agent integration:** a new agent tool `manage_trip_rules(trip_id, action, rule_json)` (create/list/disable), documented in `system_capabilities.md` exactly like scheduling rules. Agent-created rules default to `soft` (except `keep_clear`, hard by default); the agent escalates to `hard` only on emphatic user language. Every rule carries its NL `description` so "what rules are active?" is answerable in chat.

**Rules visibility (decided):** v1 ships a **read-only rules panel** on the trip page — description, type, hardness, source badge (AI / user / implicit), and an enable/disable toggle (toggle = the one write operation; it's the cheapest safety valve when an AI rule misbehaves). Stored rules (AI + user) show by default; rules derived from POI settings sit in a collapsed "derived from POI settings" section so the effective constraint set is fully inspectable without noise. This exists to verify the agent is creating rules correctly and the solver is honoring them; it may later grow into a full editor or shrink away as confidence builds.

## 6. Level 1 — CP-SAT model

### Variables

- `x[p,d,k]` ∈ {0,1} — POI `p` assigned to day `d`, block `k` (only for legal `(p,d,k)` combos after hard-rule pruning; illegal combos are never created)
- `scheduled[p]` = Σ_{d,k} `x[p,d,k]` ≤ 1 (a POI is placed at most once — placement is optional, so the model stays feasible; "must" POIs are driven in by reward, not forced)
- `claim[b,d]` ∈ {0,1} — background POI `b` claims day `d`
- `day_of[p]` ∈ {0..D} — channeling IntVar for spacing/pairing reifications

### Hard constraints (built-in template rules)

1. **Meal exclusivity**: for each meal block `(d,k)`: Σ over food POIs (excluding `dessert`/`snack`) `x[p,d,k]` ≤ 1.
2. **Meal typing** (allowed blocks by declared type):
   - `breakfast`/`brunch` → `breakfast` block; `lunch` → `lunch`; `dinner` → `dinner`
   - `dining_style='fine'` → `dinner` only (unless the POI says `lunch` explicitly)
   - food with no `meal_type` → `lunch` or `dinner`
   - `dessert`/`snack` → activity blocks or `evening`; never occupy a meal block's exclusive slot
   - non-food POIs never occupy meal blocks
3. **Activity block capacity**: Σ `duration_mins · x[p,d,k]` ≤ capacity(k) for activity blocks.
4. **Containers / anchors**: Σ_d `claim[b,d]` = `days_claimed(b) · scheduled_b`; at most one container per day (Σ_b `claim[b,d]` ≤ 1); child `c` with `parent_container=b`: `x[c,d,k]` ≤ `claim[b,d]`.
   - **Valid-day interaction (decided)**: if the background POI has `valid_days_of_week` set, claimed days are a **hard subset** of those weekdays — `days_claimed=3` + valid days Mon/Wed/Fri means the claims land exactly on Mon, Wed, Fri. Consecutiveness is a *soft* preference (minimize claim span) that yields to valid-day constraints; absent valid days, claims come out contiguous.
   - **Anchor semantics (decided)**: a background POI is a *gravity center* for its days, not an exclusive occupation. "Explore Eiffel Tower" is as valid a container as Magic Kingdom. On a claimed day, the home base for distance scoring **switches from the accommodation to the anchor's location**, so any POI — child or not — is welcome on that day *in proportion to its proximity to the anchor*. Nearby bistro: cheap. Cross-town museum on Epcot day: expensive. No flat "unrelated POI" penalty; distance does the work.
5. **Trip bounds**: no placements outside trip days; truncated arrival/departure days per §4.
6. Hard `TripRule`s and hard implicit rules, as compiled per §5.3.

### Objective (maximize)

Tiered like `matcher.py` so classes of concern can't fight across tiers:

| Tier | Term | Weight |
|---|---|---|
| 1 — placement | `scheduled[p]` reward by priority: must / want / stretch | 10,000,000 / 1,000,000 / 100,000 |
| 2 — rules | soft-rule penalties | rule `weight` (default 50,000) |
| 3 — shape | home-base distance: −(haversine-mins from that day's base × x); base = the day's anchor POI on claimed days, else the accommodation | −300/min |
| 3 | same-day pair distance: −(haversine-mins between same-day pairs) | −100/min |
| 3 | dessert-after-dinner: dessert in `evening` on a day with a scheduled dinner | +20,000 |
| 3 | container claim-span: −(last claimed day − first claimed day − (days_claimed−1)) per container | −40,000/day |
| 3 | day-load balance: −Σ |load_d − mean| deviations | −50/min |
| 3 | container children placed on their container's days (already hard); bonus for filling park days fully | +10,000/child |

Same-day pair terms use one reified equality per POI pair on `day_of` (~435 aux vars at 30 POIs — trivial). "That day's accommodation" is precomputed per day from `check_in_date`/`check_out_date` (no solver involvement).

Distances: haversine from stored `lat`/`lng` converted to rough driving minutes (`mins ≈ km × 1.4`). Good enough for *clustering* decisions; real travel times only enter Level 2. POIs missing coordinates get one geocode attempt at solve start (cached forever), else they simply contribute no distance terms.

### Solver budget

`max_time_in_seconds = 5` (mirrors matcher). Expected solve time for realistic trips: < 1s.

## 7. Level 2 — deterministic timing

Per day, after Level 1 fixes `(day, block)` for every POI:

1. Start point = that day's accommodation (or trip location).
2. Iterate blocks in template order. Within a multi-POI activity block, order by nearest-neighbor from the previous stop (haversine).
3. `start(next) = max(window_start(block), end(prev) + real_travel(prev → next))`, snapped to 5 minutes. Real travel from `maps.get_travel_time_minutes` — consecutive stops only, so ~5–8 lookups/day, hitting the existing distance cache.
4. Meals anchor to their window midpoints when slack allows (dinner tends to 18:30, not 17:30).
5. Overflow past a block window spills into the next block's slack; if a day genuinely overruns 23:00, the last POI gets flagged in the results (`"warning": "tight day"`) rather than silently squeezed.
6. Container background events span first block start → last block end of each claimed day.

Output writes the same fields as today (`scheduled_start/end` UTC timestamps, `draft_poi_*` event ids), so commit-to-calendar and `trip.html` rendering are untouched.

## 8. Failure reporting & explanations

- **Unscheduled POIs**: after solving, each unplaced POI gets a reason derived from its binding constraints — e.g. `"4 dinner-type restaurants for 3 dinner slots"`, `"parent container 'Epcot' was not scheduled"`, `"day restriction (Tue only) conflicts with container claim"`. Computed by cheap post-hoc checks against the compiled rule set, not by re-solving.
- **Hard-rule conflicts**: hard rules enter as assumption literals; on INFEASIBLE, `SufficientAssumptionsForInfeasibility()` names the conflicting rule set. The agent turns that into: *"I couldn't honor both 'no mornings' and 'four parks in three days' — which should bend?"*
- The NDJSON stream contract is preserved: `{"poi_id", "success", "reason", "suggested_fixes"}` per POI + `{"type": "insight", ...}` entries. `suggested_fixes` gains rule-aware actions, e.g. `{"type": "disable_rule", "rule_id": ..., "label": "Relax 'no mornings' and retry"}`.

## 9. LLM contract changes (`generate_trip_pois` / `generate_trip_plan`)

Request per POI:
- **add**: `meal_type`, `dining_style`, `parent_container` (the *name* of the suggested park/resort/anchor it belongs to; resolver matches it to a background POI by fuzzy name), `days_claimed` (backgrounds only)
- **broaden `is_background` guidance**: an anchor is any experience worth organizing a day around — theme parks, national parks, but also "Explore the Eiffel Tower district" or "Old Town day". The current prompt's theme-park-only framing is replaced.
- **drop as required**: `ideal_time_start/end` (accepted if volunteered → soft override), the `occurrences`-for-multi-day-parks instruction (replaced by `days_claimed`)
- **keep**: `valid_days_of_week`, `duration_mins`, `category`, `is_background`, prices, descriptions

The proposed-itinerary alignment feature ("assistant promised this plan") maps day names → `valid_days_of_week` + `parent_container`, which the solver honors as implicit rules — stronger than today's hope that clock strings survive the slot scanner.

## 10. API & incremental scheduling

- `POST /api/trip/{id}/schedule_pois_bulk` → `trip_scheduler.schedule_pois_bulk(trip, poi_ids)`, same generator/NDJSON shape. Internally: one global solve for the requested POIs **with already-scheduled POIs locked** to their current `(day, block)` (derived from their timestamps), then Level 2 re-times only affected days.
- `POST .../schedule_poi` (single) → same solve with exactly one free POI. Result quality now benefits from global context even for single placements.
- A "reshuffle trip" action (optional, later): same solve with nothing locked.
- Draft mode: unchanged — mock date range becomes the day grid; no Google Calendar interaction until commit.

## 11. Mapbox budget

| Phase | Calls |
|---|---|
| Level 1 solve | 0 (haversine on stored coords) |
| Level 2 timing | ≤ stops−1 per day, Directions, served by the existing cache with the 43,200-min TTL |
| Removed | the per-slot `get_travel_time_minutes` loop and `prime_matrix_cache` N×N priming in bulk scheduling |

Net effect: trip planning drops from thousands of potential cache lookups/API calls per bulk run to a few dozen, all cacheable pairs.

## 12. Migration plan

1. **Schema** (additive): `TripPOI` fields, `TripRule`, `TripMetadata.rules`. TinyDB needs no migration; old trips lack the fields and get defaults.
2. **New module** `services/trip_scheduler.py`: rule compiler → CP-SAT model → Level 2 layout. No edits to the old scheduler.
3. **Scenario tests first** (new `chauffeur/tests/` — the repo's first real test dir; the root `test_*.py` scratch files are not a suite):
   - Disney: 2-day Magic Kingdom + 1-day Epcot containers, character dining children, fine dining offsite → children land inside claimed days; nearby offsite dinner allowed cheaply, cross-town POI on a park day costs
   - Valid-day claims: background POI with `days_claimed=3` + `valid_days_of_week=[0,2,4]` over a Mon–Sun trip → claims land exactly Mon/Wed/Fri; same POI without valid days → contiguous run
   - Anchor generality: "Explore Eiffel Tower" background with 4 surrounding POIs (2 inside, 2 nearby) → all cluster on the anchor day
   - Meal fit: 5 restaurants (1 fine, 2 casual, 1 breakfast, 1 dessert) over 3 days → fine→dinner, dessert→evening, no double-booked meal slots
   - Clustering: 8 POIs in two geographic lobes → two coherent days, not interleaved
   - Balance: 12 uniform POIs / 4 days → 3/day, not 6-4-2-0
   - Rules: "no mornings" template override; "Tuesday light" capacity; "keep day 4 clear" `keep_clear`; infeasible pair → named conflict
   - Locked incremental: adding 2 POIs to a scheduled trip doesn't move existing ones
4. **Swap** the two imports in `main.py`; LLM prompt updates in `trip_planner.py`; rules panel (read-only + toggle) in `trip.html` with `GET/PATCH /api/trip/{id}/rules` endpoints.
5. **Docs**: new "Trip Itinerary Scheduling & Rules" section in `system_capabilities.md` (same turn as the swap, per repo policy).
6. **Cleanup** (separate commit): delete `trip_planner_hacked*.py` (17k lines), root scratch `test_*.py`, `trip.html.rej`.
7. Version bump in `config.yaml` for the HA add-on.

## 13. Resolved decisions (2026-07-16 review)

1. **Block template defaults**: accepted as proposed; tunable per-trip via `template_override` rules.
2. **Container days**: single background POI with `days_claimed`; consecutive by default as a *soft* preference, but `valid_days_of_week` is a **hard** subset constraint that wins — `days_claimed=3` + Mon/Wed/Fri means claims land exactly on Mon, Wed, Fri.
3. **Offsite POIs on anchor days**: allowed, scored by proximity to the anchor (home base switches to the anchor's location on claimed days). Containers generalize beyond theme parks — "Explore Eiffel Tower" with surrounding restaurants/sights is the same mechanism.
4. **Downtime**: no first-class rest block. Users tell the agent to keep a day or block clear → `keep_clear` rule (hard by default); lighter days → `day_capacity`.
5. **Rules UI**: read-only rules panel on the trip page in v1 (description, type, hardness, source badge, enable/disable toggle; implicit rules in a collapsed section). May grow into an editor or be retired as confidence builds.
