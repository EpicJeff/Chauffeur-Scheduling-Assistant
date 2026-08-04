# Car Telemetry (C2) — HA integration for cars

Status: **IMPLEMENTED** (v2.49.0 — `services/cars.py`, tests in `tests/test_car_telemetry.py`)
Depends on: C1 (`docs/car_entity_design.md`). Principle carried over: **telemetry informs
humans and creates errands; it never moves solver assignments.**

## 1. Scope

- **Map**: cars with a device tracker appear on the family map like members do.
- **Readiness**: low EV charge / low fuel before upcoming drives → push to the car's
  usual driver (else parents), optional auto-created fuel errand.
- **Reality check**: a car that has a drive coming up but isn't home → push warning.

Out of scope (unchanged from C1): car location as a solver input, mileage-based energy
math (Matrix cache stores durations, not distances — a future refinement), per-car
threshold overrides.

## 2. Data model — `Car` HA fields (explicit mapping, no auto-discovery)

The bus arc auto-discovers by name because HCTB is one known integration; car
integrations (Tesla, Ford Pass, Mazda, OBD dongles…) vary too much, so mapping is
explicit only:

```python
ha_device_tracker: Optional[str] = None   # device_tracker.* — location
ha_battery_entity: Optional[str] = None   # sensor.* — EV charge %
ha_fuel_entity: Optional[str] = None      # sensor.* — fuel level %
ha_range_entity: Optional[str] = None     # sensor.* — remaining range (display only)
```

All `None` → the car is untouched by every C2 feature (the C1 inertness rule extends).

## 3. `services/cars.py`

Mirrors `services/bus.py`'s tolerant reads (`unknown`/`unavailable`/`''` → None):

- `car_location(car)` → `{state, latitude, longitude, gps_accuracy, last_updated}` from
  the tracker via `ha_api.get_state`.
- `car_levels(car)` → `{battery_pct, fuel_pct, range}` — floats or None.
- `upcoming_car_events(cars, hours)` — reads the daily-schedule caches'
  `car_assignments` for today/tomorrow, returns per-car upcoming events (id, title,
  start) within the window.
- `readiness_warnings(cars, levels_by_car, upcoming, thresholds)` — **pure**, returns
  `[{car, kind: 'battery'|'fuel', level, events}]`. Warn only when the car has ≥1
  upcoming drive in the window (a low car nobody needs is not worth a push).
- `away_warnings(cars, locations_by_car, upcoming, in_progress_car_ids)` — **pure**:
  car has a drive starting within `CAR_AWAY_LOOKAHEAD_H` (3h), tracker state is not
  `home`, and no in-progress drive is using it.
- `ensure_fuel_errand(car, settings)` — creates `⛽ Fuel up {name}` (15 min,
  `allowed_drivers` = car's drivers, tags `['auto_car_fuel', car.id]`, location =
  `car_fuel_station` setting else global home) unless an active errand with that tag
  pair already exists. EVs never get an errand — charging happens at home, so battery
  warnings are push-only ("plug in tonight").

## 4. Readiness job (push loop)

New block in `push_notification_loop` following the watchers pattern: app_state
time-gate `car_readiness_last_run` (1800s), body in `asyncio.to_thread`, early-return
during quiet hours (same helper watchers use), and skip entirely when no car has any
HA field (inert). Dedupe markers in app_state, set **before** send (loop convention):

- readiness: `car_ready:{car_id}:{date}`  (one nag per car per day)
- away: `car_away:{car_id}:{event_id}`    (one nag per car per event)

Push delivery = `_notify_member_lanes` (web push + HA companion). Target: member linked
to `default_driver_id`, else all `role == 'parent'` members.

Settings (keys, read with defaults; no new UI beyond the Cars panel alert block):
`car_battery_warn_pct` (30), `car_fuel_warn_pct` (25), `car_auto_errand` (False),
`car_fuel_station` ('').

## 5. Family map

`family_locations()` (main.py) appends, after members, one entry per enabled car with a
tracker: same shape plus car extras —

```
{ member_id: 'car:{id}', name, color_code, avatar: icon|'🚗', image, is_car: true,
  state, latitude, longitude, gps_accuracy, last_updated,
  battery_pct, fuel_pct, range, driving: {leg_title}|null }
```

`driving` is set when an in-progress drive's event maps to this car in
`car_assignments`. `family_map.html` renders car markers through the existing
photo/emoji path (square-ish rounded border distinguishes them) and the popup gains
battery/fuel/range lines for `is_car` entries; no-coords cars fall back to the state
chip like members.

## 6. Config UI

Car form gains a "Home Assistant" block (shown when HA is available): a
`device_tracker` select + three sensor inputs with a shared `<datalist>` of sensors
(the sensor domain is too big for a select). `loadHaOptions()` additionally fetches
`api/ha/entities?domain=device_tracker` and `?domain=sensor` (endpoint is already
generic). The Cars panel gets a compact "Alerts" row: battery %, fuel %, auto-errand
toggle — saved through the regular settings mechanism.

## 7. Tests (`tests/test_car_telemetry.py`)

Pure functions tested with stubbed `ha_api.get_state`: level parsing (numbers, strings,
unavailable), readiness only-with-upcoming-drives, EV vs fuel errand behavior +
existing-errand dedupe, away warning (not-home + upcoming + not-in-progress), map entry
builder shape, and full inertness with no HA fields set.
