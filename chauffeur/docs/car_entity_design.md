# Car Entity & Solver Car Dimension (C1) — Design

Status: **IMPLEMENTED** (v2.47.0 — solver in `solver/matcher.py`, tests in `tests/test_cars.py`)
Arc: C1 = entity + solver + UI + agent tools. C2 (later) = HA telemetry (fuel/charge → reminders/errands, observed car location warnings).

## 1. Problem

The solver assigns drivers to events assuming every driver has a car of infinite
capacity available at all times. Real constraints it cannot express today:

- **Fewer cars than drivers.** 2–3 cars shared by 2–5 licensed drivers (parents,
  teen, live-in helpers). The binding resource is the car, not the driver.
- **Capacity differs per car.** The minivan fits everyone; the sedan/truck/sports
  car fits some. Whether a driver can take an event depends on which car they can
  get, not just who they are.
- **Car seats bind specific kids to specific cars.** `allowed_passenger_ids`.
- **Borrowed cars.** The aunt drives the family minivan (hers lacks car seats or
  she has no car); the family is down a car while she has it. The car's identity
  persists while its driver changes — this is resource semantics, not a driver
  attribute, and is the case that rules out putting capacity fields on `Driver`.
- **Teen restrictions.** Graduated-licensing passenger caps and "not trusted with
  the little ones."

## 2. Design principles

1. **Inert when unconfigured.** Zero cars defined → the solver never builds the
   car dimension; the v2.46 code path runs bit-identical. The regression contract
   is the existing test suite passing unchanged with an empty cars table.
2. **Implicit personal car.** A driver listed in no car's `allowed_driver_ids`
   keeps today's behavior (unconstrained). Partial configuration degrades
   gracefully — adding one car never strands unrelated drivers.
3. **Cars are time-shared tokens, not routed vehicles.** No car location in the
   solver. Handoffs are assumed to happen at home between non-overlapping
   possession windows (gap must cover e1.loc→home + home→e2.loc when drivers
   differ). Explicitly out of scope: midday non-home handoffs, moving car seats
   between cars, car location tracking (C2 observes it reactively via HA).
4. **Swaps are rare and loud.** Each car has a `default_driver_id`; deviating
   costs a penalty so the solver only swaps when necessary, and the UI badges
   non-default pairings.
5. **Manual override beats every car ban** — same escape hatch as every other
   hard constraint in the model (`overridden_pairs`).

### Known punt (documented limitation)

A pooled driver's **personal calendar events** (driver_events) do not consume a
car in C1. "Dad takes Car 1 to work 9–5" is invisible to contention. Mitigations:
`unavailable_ranges` for multi-day loans; C2 HA presence produces reactive
warnings ("tonight's schedule assumes the minivan is home").

## 3. Data model (`models/schemas.py`, next to Driver/Passenger)

```python
class CarUnavailableRange(BaseModel):
    start: str                      # ISO date (inclusive)
    end: str                        # ISO date (inclusive)
    reason: Optional[str] = ""      # "loaned to Aunt Sarah", "in the shop"

class Car(BaseModel):
    id: str = uuid hex
    name: str                       # "Minivan", "Red Tesla"
    icon: Optional[str] = None      # emoji; None -> generic car
    color_code: str = '#6b7280'
    seat_capacity: int = 4          # passenger seats, EXCLUDING the driver
    allowed_driver_ids: List[str]   # explicit; a driver on no car keeps the implicit personal car
    allowed_passenger_ids: Optional[List[str]] = None  # None = anyone fits; list = car-seat restriction
    default_driver_id: Optional[str] = None
    unavailable_ranges: List[CarUnavailableRange] = []
    is_disabled: bool = False       # hidden from solver entirely (soft-delete / seasonal)
    notes: Optional[str] = ""
```

Also added: `Driver.max_passengers: Optional[int] = None` — a driver-level cap
independent of car (teen graduated-licensing laws). Enforced as a pre-filter:
`len(event_passengers) > max_passengers` → pair banned (override-escapable).

## 4. Solver extension (`solver/matcher.py`)

New kwarg `cars: List[Car] = None` on `solve_schedule`. Entire extension guarded
by `if cars:` (enabled, non-disabled cars only). Return becomes a 4-tuple:
`(assignments, unassigned, lateness_warnings, car_assignments)` where
`car_assignments: Dict[event_id, car_id]` (only pooled-driver events appear).

### Definitions (plain-code prefilters, no solver vars)

- `pooled_drivers` = drivers listed in ≥1 enabled car's `allowed_driver_ids`.
- `eligible(e, d)` = cars c where: `d ∈ c.allowed_driver_ids` AND
  `pax_count(e) ≤ c.seat_capacity` AND (`c.allowed_passenger_ids is None` or
  `pax(e) ⊆ c.allowed_passenger_ids`) AND e does not overlap any
  `unavailable_range` of c. Uses the existing `get_event_passenger_ids` matching.
- Driver cap: pooled or not, if `d.max_passengers is not None` and
  `pax_count(e) > d.max_passengers` → `assign_vars[(e,d)] == 0` (skip if
  `(e.id, d.id) ∈ overridden_pairs`).

### Variables & channeling

- `car_vars[(e.id, c.id)]` BoolVar for every car c eligible for e under at least
  one pooled driver.
- `AddAtMostOne(car_vars[e, *])` per event.
- For pooled d: if `eligible(e, d)` is empty → `assign_vars[(e,d)] == 0`
  (override-escapable; recorded for diagnostics). Else
  `Add(sum(car_vars[e,c] for c in eligible(e,d)) >= assign_vars[(e,d)])`
  — an assigned pooled driver takes exactly one eligible car.
- Phantom guard: `car_vars[e,c] <= sum(assign_vars[e,d] for pooled d with
  c ∈ eligible(e,d))` — unassigned events and non-pooled drivers use no car.

### Contention (possession windows, pairwise)

For event pairs within the existing 3-hour pairing window that both have
`car_vars` for the same car c: same driver chaining keeps the car (fine);
different drivers require a home handoff. Needed gap =
`t(e1.loc → home) + t(home → e2.loc)` (global `home_location`; falls back to
direct `t(e1.loc → e2.loc)` when home is unset). If
`gap < needed`:

```
car_vars[e1,c] + car_vars[e2,c] <= 1 + same_driver(e1,e2)
```

`same_driver(e1,e2)` = BoolVar OR'd from per-driver `both_assigned` aux vars
(same construction as the continuity-bonus aux). Aux vars are created lazily,
only for pairs/cars that actually conflict.

### Objective terms

- **Swap penalty −2500** on aux (`assign[e,d] ∧ car[e,c]`) whenever
  `c.default_driver_id` is set and ≠ d.id. Above priority deltas (≤1350+150),
  below `preferred` rule (+10000): a rule can still force a swap, priority alone
  cannot. Scaled by no theme multiplier in C1 (add later if tuning demands).
- No car stickiness in C1 (driver stickiness +5 already stabilizes chains);
  revisit if churn is observed.

### Out of scope in solver

Ghost routes (`solve_ghost_routes`) and errand insertion ignore cars — they are
suggestions; badging them with cars would imply a precision the model doesn't
have. `compute_route_edges` unchanged (edges are per-driver).

## 5. Result flow (`main.py`)

- Load: `cars_data = storage.get_all_cars()` → `cars = [Car(**c) ...]` next to
  drivers/passengers (~6657), skipping `is_disabled`.
- Thread `cars=cars` through both `solve_schedule` call sites (7682, 7806);
  unpack 4-tuple.
- `base_schedules[date_str]["car_assignments"] = car_assignments`; draft mode
  restores it from `daily_cache` like `assignments`.
- `data_payload["car_assignments"]` (sibling of `assignments`, main.py:~7423);
  UI renders a car chip next to the driver on assigned events **only when the
  event has a car** (zero-car families see zero UI change): calendar.html's
  `eventContent` metaRow next to the driver badge (788-801, fed by a new
  `extendedProps.carName`), and app.html's schedule-card builders (2849/3096).
  Non-default pairings get a visible "swap" accent.

## 6. Storage & API

- `storage.py`: `cars_table = db.table('cars')`; `get_all_cars` / `add_car` /
  `update_car` / `delete_car` mirroring the passenger CRUD (646–744) **including
  the cache-busting trio** (cars affect solver output). No `ensure_members()`.
- `storage_sqlite.py`: no change (drop-in `_ensure_schema` handles new tables).
- `main.py`: `/api/cars` GET/POST/PUT/DELETE mirroring `/api/passengers`
  (2514–2534), with `background_tasks.add_task(refresh_schedule_logic)` on
  writes.
- SQLite migration: `cars` is just another doc table; nothing special needed in
  the pending migration plan.

## 7. Config UI (`templates/config.html`)

Cars sub-panel inside the **family** tab (`style="order:3"`), mirroring the
passenger form: Alpine state `cars: []` / `newCar` / `editCarId`, functions
`loadCars/submitCar/editCar/cancelEditCar/deleteCar` (PUT-if-editing pattern from
`submitPassenger`, `promptConfirm` guard on delete). Form fields: name, icon,
capacity, allowed drivers (checkboxes from `drivers`), default driver (select,
filtered to allowed), allowed passengers (checkbox list, "anyone" default),
unavailable ranges (add/remove rows), disabled toggle. Person cards get no
changes in C1.

## 8. Diagnostics & agent stacks

- `compute_diagnostics` (matcher.py:1660) gains a `"car"` reason type in the
  `diagnostics[event_id][driver_id]` map: "No car {driver} may drive fits this
  event's passengers", "{car} is unavailable ({reason})", "{driver} is capped at
  {n} passengers". `explain_assignment_conflicts` gains the same strings so the
  override-warning path matches. Dashboard's existing reason-card renderer
  (dashboard.html:1113-1178) needs no new action buttons — `"car"` renders as a
  plain reason like `"rule"`.
- Agent tools are implemented **once, in Stack B** (`agent_tools.py`): Pydantic
  tool classes + `TOOL_SCHEMAS` + `TOOL_HANDLERS` — `manage_car`
  (create/update/delete/set-availability) and cars added to
  `handle_get_current_state` output. The chat widget gets them for free by
  adding the tool name to `BRIDGED_V1_TOOLS` (agent_tools_v2.py:1332) and to
  `SCHEDULE_MUTATING_V1_TOOLS` (mutations bust the schedule); the router's
  bridge fall-through (agent_router.py:560) dispatches without a new elif. The
  agentic loop (llm.py) is registry-driven and needs no wiring.

## 9. Tests (`tests/test_cars.py`)

1. **Zero-car regression**: no `cars` kwarg / empty list → 4th return `{}`,
   assignments identical to a pre-change fixture run.
2. Implicit personal car: unpooled driver unaffected by other drivers' cars.
3. Capacity ban: 3 passengers, driver's only car holds 2 → unassigned (and
   assigned once capacity raised).
4. Allowed-passenger (car-seat) ban.
5. Contention: 2 pooled drivers, 1 car, overlapping events → one event moves to
   an unpooled driver or goes unassigned; non-overlapping events share the car.
6. Same-driver chain keeps one car through back-to-back events.
7. Swap penalty: both parents pooled on both cars → each keeps their default.
8. Unavailable range blocks the car; solver falls back or unassigns.
9. Manual override beats a car ban.
10. `Driver.max_passengers` cap.
11. Existing suite green with no cars defined.

## 10. Versioning

Implemented as v2.47.0. `system_capabilities.md` gains a "Cars & Vehicle
Assignment" section in the same change.
