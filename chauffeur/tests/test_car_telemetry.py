"""Car telemetry tests (C2, services/cars.py, docs/car_telemetry_design.md).

HA reads are stubbed at services.ha_api.get_state. Storage runs against the
harness's isolated temp dir. The standing rule under test: telemetry is inert
for cars with no HA fields, warns only when someone actually needs the car,
and never touches solver assignments.

Run from chauffeur/:  python tests/test_car_telemetry.py
"""
import datetime

from harness import check  # noqa: F401

from services import storage, ha_api, cars


NOW = datetime.datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)


def _stub_states(states):
    ha_api.get_state = lambda ent, *a, **kw: states.get(ent)


def _reset():
    storage.cars_table.truncate()
    storage.errands_table.truncate()
    storage.daily_schedules_table.truncate()
    storage.members_table.truncate()
    storage.app_state_table.truncate()
    _stub_states({})


def _mk_car(**kw):
    base = {'id': kw.pop('id', 'c1'), 'name': kw.pop('name', 'Minivan'),
            'seat_capacity': 4, 'allowed_driver_ids': kw.pop('allowed_driver_ids', ['d1'])}
    base.update(kw)
    storage.add_car(base)
    return base


def _cache_day(offset_days, car_assignments, events):
    d = (NOW + datetime.timedelta(days=offset_days)).strftime('%Y-%m-%d')
    storage.save_cached_daily_schedule(d, {
        'car_assignments': car_assignments,
        'events': events,
    }, f'hash_{d}')


def _ev(eid, title, hours_from_now):
    return {'id': eid, 'title': title,
            'start': (NOW + datetime.timedelta(hours=hours_from_now)).isoformat()}


def scenario_inert_without_ha_fields():
    _reset()
    car = _mk_car()
    check(not cars.has_telemetry(car), "no HA fields -> no telemetry")
    sent = []
    actions = cars.run_sweep(lambda m, t, b: sent.append((t, b)), now=NOW)
    check(actions == [] and sent == [], "sweep is inert with no mapped cars")


def scenario_level_parsing():
    _reset()
    car = _mk_car(ha_battery_entity='sensor.ev_batt', ha_fuel_entity='sensor.fuel',
                  ha_range_entity='sensor.range')
    _stub_states({
        'sensor.ev_batt': {'state': '78.5'},
        'sensor.fuel': {'state': '45%'},
        'sensor.range': {'state': 'unavailable'},
    })
    lv = cars.car_levels(car)
    check(lv['battery_pct'] == 78.5, f"numeric battery, got {lv}")
    check(lv['fuel_pct'] == 45.0, f"percent-suffixed fuel, got {lv}")
    check(lv['range'] is None, f"unavailable -> None, got {lv}")


def scenario_location_read():
    _reset()
    car = _mk_car(ha_device_tracker='device_tracker.minivan')
    _stub_states({'device_tracker.minivan': {
        'state': 'not_home', 'last_updated': 'x',
        'attributes': {'latitude': 34.1, 'longitude': -84.2, 'gps_accuracy': 10}}})
    loc = cars.car_location(car)
    check(loc['state'] == 'not_home' and loc['latitude'] == 34.1, f"location parsed, got {loc}")


def scenario_readiness_needs_upcoming_drive():
    _reset()
    car = _mk_car(ha_battery_entity='sensor.b')
    levels = {'c1': {'battery_pct': 15.0, 'fuel_pct': None, 'range': None}}
    # Low battery but nobody needs the car -> silence.
    w = cars.readiness_warnings([car], levels, {})
    check(w == [], "no upcoming drives -> no warning")
    upcoming = {'c1': [{'id': 'e1', 'title': 'Practice', 'start': NOW + datetime.timedelta(hours=3)}]}
    w = cars.readiness_warnings([car], levels, upcoming)
    check(len(w) == 1 and w[0]['kind'] == 'battery', f"low battery + drive -> warning, got {w}")
    # Battery beats fuel when both are low (one push, charging is the cheaper ask).
    levels = {'c1': {'battery_pct': 10.0, 'fuel_pct': 5.0, 'range': None}}
    w = cars.readiness_warnings([car], levels, upcoming)
    check(len(w) == 1 and w[0]['kind'] == 'battery', "battery outranks fuel")
    # At/above threshold -> quiet.
    levels = {'c1': {'battery_pct': 30.0, 'fuel_pct': None, 'range': None}}
    check(cars.readiness_warnings([car], levels, upcoming) == [], "threshold is strict less-than")


def scenario_away_warning():
    _reset()
    car = _mk_car()
    soon = {'c1': [{'id': 'e1', 'title': 'Pickup', 'start': NOW + datetime.timedelta(hours=1)}]}
    far = {'c1': [{'id': 'e1', 'title': 'Pickup', 'start': NOW + datetime.timedelta(hours=8)}]}
    away = {'c1': {'state': 'not_home'}}
    home = {'c1': {'state': 'home'}}
    check(len(cars.away_warnings([car], away, soon, set(), now=NOW)) == 1, "away + soon -> warn")
    check(cars.away_warnings([car], home, soon, set(), now=NOW) == [], "home -> quiet")
    check(cars.away_warnings([car], away, far, set(), now=NOW) == [], "drive beyond lookahead -> quiet")
    check(cars.away_warnings([car], away, soon, {'c1'}, now=NOW) == [], "in-progress drive -> quiet")


def scenario_upcoming_from_daily_cache():
    _reset()
    car = _mk_car()
    _cache_day(0, {'e1': 'c1', 'e2': 'other_car'}, [_ev('e1', 'Practice', 3), _ev('e2', 'Game', 4)])
    _cache_day(1, {'e3': 'c1'}, [_ev('e3', 'School run', 20)])
    by_car, car_by_event = cars.upcoming_car_events([car], now=NOW)
    ids = [e['id'] for e in by_car.get('c1', [])]
    check(ids == ['e1', 'e3'], f"both days read, other cars ignored, sorted, got {ids}")
    check(car_by_event.get('e1') == 'c1', "event->car map populated")


def scenario_fuel_errand_dedupe():
    _reset()
    car = _mk_car(ha_fuel_entity='sensor.f')
    settings = {'car_fuel_station': 'Costco Gas, Main St'}
    doc_id = cars.ensure_fuel_errand(car, settings)
    check(doc_id is not None, "errand created")
    ers = storage.get_all_errands()
    check(len(ers) == 1 and 'auto_car_fuel' in ers[0]['tags'] and 'c1' in ers[0]['tags'],
          f"tagged for dedupe, got {ers}")
    check(ers[0]['allowed_drivers'] == ['d1'], "errand restricted to the car's drivers")
    check(cars.ensure_fuel_errand(car, settings) is None, "active errand -> no duplicate")
    check(len(storage.get_all_errands()) == 1, "still one errand")


def scenario_sweep_proposes_and_dedupes():
    # C3: readiness produces an approval PROPOSAL (charge buffer for EVs),
    # not a bare push; dedupe is keyed on the drive's date.
    _reset()
    storage.members_table.insert({'id': 'm1', 'name': 'Jeff', 'role': 'parent', 'driver_id': 'd1'})
    _mk_car(ha_battery_entity='sensor.b', default_driver_id='d1')
    _stub_states({'sensor.b': {'state': '12'}})
    _cache_day(0, {'e1': 'c1'}, [_ev('e1', 'Practice', 3)])

    delivered = []
    orig_deliver = cars._deliver_proposal
    cars._deliver_proposal = lambda s, p, b: delivered.append(p) or 'pid'
    try:
        actions = cars.run_sweep(lambda m, t, b: None, now=NOW)
        check(len(actions) == 1 and actions[0].startswith('car_ready:c1:'),
              f"one readiness proposal, got {actions}")
        check(len(delivered) == 1 and delivered[0]['kind'] == 'charge_buffer',
              f"EV low battery -> charge-buffer proposal, got {delivered}")

        actions2 = cars.run_sweep(lambda m, t, b: None, now=NOW)
        check(actions2 == [] and len(delivered) == 1, "same drive date -> deduped")
    finally:
        cars._deliver_proposal = orig_deliver


def scenario_sweep_away_push_targets_parents_without_default():
    _reset()
    storage.members_table.insert({'id': 'm1', 'name': 'Jeff', 'role': 'parent'})
    storage.members_table.insert({'id': 'm2', 'name': 'Sam', 'role': 'parent'})
    storage.members_table.insert({'id': 'm3', 'name': 'Kid', 'role': 'child'})
    _mk_car(ha_device_tracker='device_tracker.van')
    _stub_states({'device_tracker.van': {'state': 'not_home', 'attributes': {}}})
    _cache_day(0, {'e1': 'c1'}, [_ev('e1', 'Pickup', 1)])

    sent = []
    actions = cars.run_sweep(lambda m, t, b: sent.append(m['id']), now=NOW)
    check(len(actions) == 1 and actions[0] == 'car_away:c1:e1', f"away push fired, got {actions}")
    check(sorted(sent) == ['m1', 'm2'], f"no default driver -> both parents, never the kid, got {sent}")


SCENARIOS = [
    scenario_inert_without_ha_fields,
    scenario_level_parsing,
    scenario_location_read,
    scenario_readiness_needs_upcoming_drive,
    scenario_away_warning,
    scenario_upcoming_from_daily_cache,
    scenario_fuel_errand_dedupe,
    scenario_sweep_proposes_and_dedupes,
    scenario_sweep_away_push_targets_parents_without_default,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
