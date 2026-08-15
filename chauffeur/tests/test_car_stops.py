"""C3 car-stop proposal tests (services/cars.py + chat_actions add_car_stop,
docs/car_errand_proposals_design.md).

Covers: proposal creation + first-drive-date dedupe, approve/dismiss/admin
gating through the real chat_actions path, the legacy auto-approve setting,
charge buffers (time not place), station-pick fallback order, the polyline
encoder, and digest fuel notes.

Run from chauffeur/:  python tests/test_car_stops.py
"""
import datetime

from harness import check  # noqa: F401

from services import storage, ha_api, cars, maps, chat_actions


# 9am, PINNED — not just "this hour, rounded". Scenarios below place events a
# few hours out (`_ev(..., hours_from_now=3)`) and assert the proposal is keyed
# on TODAY, so run after about 9pm the event crossed midnight and the sweep
# correctly keyed it on tomorrow. The test failed nightly and passed all day,
# which reads as flakiness and was really a fixture describing "now" instead
# of describing a morning.
NOW = datetime.datetime.now().astimezone().replace(
    hour=9, minute=0, second=0, microsecond=0)
TODAY = NOW.strftime('%Y-%m-%d')
TOMORROW = (NOW + datetime.timedelta(days=1)).strftime('%Y-%m-%d')

_BASE_SETTINGS = {"calendar_ids": ["primary"], "car_fuel_station": ""}


def _reset(settings=None):
    storage.cars_table.truncate()
    storage.errands_table.truncate()
    storage.daily_schedules_table.truncate()
    storage.members_table.truncate()
    storage.app_state_table.truncate()
    storage.agent_action_proposals_table.truncate()
    storage.ensure_family_channel()
    ha_api.get_state = lambda ent, *a, **kw: None
    s = dict(_BASE_SETTINGS)
    s.update(settings or {})
    storage.get_settings = lambda: s
    # No network: station picking is stubbed per-scenario.
    cars.pick_station = lambda origin, dest, settings=None: {
        'name': 'QuickFuel', 'address': 'QuickFuel, 1 Main St', 'source': 'stub'}


_orig_pick_station = cars.pick_station
_orig_deliver = cars._deliver_proposal


def _collect_deliveries():
    delivered = []

    def fake(summary, payload, body):
        delivered.append({'summary': summary, 'payload': payload, 'body': body})
        return 'pid_' + str(len(delivered))

    cars._deliver_proposal = fake
    return delivered


def _mk_car(**kw):
    base = {'id': kw.pop('id', 'c1'), 'name': kw.pop('name', 'Minivan'),
            'seat_capacity': 4, 'allowed_driver_ids': kw.pop('allowed_driver_ids', ['d1'])}
    base.update(kw)
    storage.add_car(base)
    return base


def _cache_day(offset_days, car_assignments, events, assignments=None):
    d = (NOW + datetime.timedelta(days=offset_days)).strftime('%Y-%m-%d')
    storage.save_cached_daily_schedule(d, {
        'car_assignments': car_assignments,
        'assignments': assignments or {},
        'events': events,
    }, f'hash_{d}')


def _ev(eid, title, hours_from_now, location='Practice Field, Town'):
    return {'id': eid, 'title': title, 'location': location,
            'start': (NOW + datetime.timedelta(hours=hours_from_now)).isoformat()}


def scenario_sweep_proposes_fuel_once():
    _reset()
    _mk_car(ha_fuel_entity='sensor.f')
    ha_api.get_state = lambda ent, *a, **kw: {'state': '12'} if ent == 'sensor.f' else None
    _cache_day(0, {'e1': 'c1'}, [_ev('e1', 'Practice', 3)])
    delivered = _collect_deliveries()

    actions = cars.run_sweep(lambda m, t, b: None, now=NOW)
    check(actions == [f'car_ready:c1:{TODAY}'], f"one proposal keyed on drive date, got {actions}")
    check(len(delivered) == 1, "delivered exactly one proposal")
    p = delivered[0]['payload']
    check(p['kind'] == 'fuel' and p['car_id'] == 'c1', f"fuel payload, got {p}")
    check(p['location'] == 'QuickFuel, 1 Main St' and p['station_name'] == 'QuickFuel',
          f"station from pick_station, got {p}")
    check(p['target_date'] == TODAY and p['allowed_drivers'] == ['d1'], f"targeting, got {p}")

    actions2 = cars.run_sweep(lambda m, t, b: None, now=NOW)
    check(actions2 == [] and len(delivered) == 1, "same drive date -> deduped")


def scenario_evening_tomorrow_is_separate():
    # Morning already proposed for today; evening finds tomorrow's drives ->
    # a NEW proposal keyed on tomorrow (the "plan for tomorrow" flow).
    _reset()
    _mk_car(ha_fuel_entity='sensor.f')
    ha_api.get_state = lambda ent, *a, **kw: {'state': '12'} if ent == 'sensor.f' else None
    storage.set_app_state('car_push_markers', {f'car_ready:c1:{TODAY}': NOW.timestamp()})
    _cache_day(1, {'e3': 'c1'}, [_ev('e3', 'School run', 20)])
    delivered = _collect_deliveries()

    actions = cars.run_sweep(lambda m, t, b: None, now=NOW)
    check(actions == [f'car_ready:c1:{TOMORROW}'], f"tomorrow proposal despite today's marker, got {actions}")
    check(delivered[0]['payload']['target_date'] == TOMORROW, "targets tomorrow")


def scenario_approve_creates_errand():
    _reset()
    storage.members_table.insert({'id': 'm1', 'name': 'Jeff', 'role': 'parent'})
    res = chat_actions.create_action_proposal('add_car_stop', 'Fuel stop', {
        'car_id': 'c1', 'kind': 'fuel', 'title': '⛽ Fuel up Minivan — QuickFuel',
        'location': 'QuickFuel, 1 Main St', 'duration_mins': 15,
        'target_date': TOMORROW, 'allowed_drivers': ['d1']})
    check(res['status'] == 'success', f"proposal stored, got {res}")
    out = chat_actions.act_on_proposal(res['proposal_id'], 'approve', {'id': 'm1', 'role': 'parent'})
    check(out['status'] == 'success' and out.get('schedule_dirty'), f"approve executed, got {out}")
    ers = storage.get_all_errands()
    check(len(ers) == 1, "errand created")
    er = ers[0]
    check(er['priority'] == 1 and er['window_days'] == 1, f"tight priority window, got {er}")
    check('auto_car_fuel' in er['tags'] and 'c1' in er['tags'], "dedupe tags")
    check(er['allowed_drivers'] == ['d1'], "restricted to the car's drivers")
    check(er['starts_on'] is not None, "anchored to the target date")


def scenario_dismiss_and_admin_gate():
    _reset()
    res = chat_actions.create_action_proposal('add_car_stop', 'Fuel stop', {
        'car_id': 'c1', 'kind': 'fuel', 'title': 'x', 'location': 'y'})
    pid = res['proposal_id']
    kid = {'id': 'k1', 'role': 'child'}
    out = chat_actions.act_on_proposal(pid, 'approve', kid)
    check(out['status'] == 'error' and 'parent' in out['message'].lower(), "kid cannot approve")
    check(storage.get_action_proposal(pid)['status'] == 'proposed', "still pending after refusal")
    out = chat_actions.act_on_proposal(pid, 'dismiss', kid)
    check(out['status'] == 'success', "anyone may dismiss")
    check(storage.get_all_errands() == [], "dismiss creates nothing")
    check(storage.get_action_proposals('proposed') == [], "no pending proposals left")


def scenario_auto_approve_setting():
    _reset(settings={'car_auto_errand': True})
    storage.members_table.insert({'id': 'm1', 'name': 'Jeff', 'role': 'parent', 'driver_id': 'd1'})
    _mk_car(ha_fuel_entity='sensor.f', default_driver_id='d1')
    ha_api.get_state = lambda ent, *a, **kw: {'state': '12'} if ent == 'sensor.f' else None
    _cache_day(0, {'e1': 'c1'}, [_ev('e1', 'Practice', 3)])
    delivered = _collect_deliveries()
    pushes = []

    cars.run_sweep(lambda m, t, b: pushes.append((m['id'], t)), now=NOW)
    check(delivered == [], "auto mode skips the card")
    check(len(storage.get_all_errands()) == 1, "errand added directly")
    check(pushes and pushes[0][0] == 'm1', f"informational push still sent, got {pushes}")


def scenario_charge_buffer_reserves_time():
    _reset(settings={'car_charge_buffer_mins': 30})
    _mk_car(id='ev1', name='Tesla', ha_battery_entity='sensor.b', allowed_driver_ids=['d2'])
    ha_api.get_state = lambda ent, *a, **kw: {'state': '14'} if ent == 'sensor.b' else None
    _cache_day(0, {'e1': 'ev1'}, [_ev('e1', 'Practice', 3, location='Gym, Town')])
    delivered = _collect_deliveries()

    def boom(*a, **kw):
        raise AssertionError("charge buffers must never pick stations")
    cars.pick_station = boom

    cars.run_sweep(lambda m, t, b: None, now=NOW)
    check(len(delivered) == 1, "buffer proposed")
    p = delivered[0]['payload']
    check(p['kind'] == 'charge_buffer' and p['duration_mins'] == 30, f"time reservation, got {p}")
    check(p['location'] == 'Gym, Town', f"anchored to the first event (detour ~0), got {p}")


def scenario_pick_station_fallbacks():
    _reset(settings={'car_fuel_station': 'Costco Gas, Main St'})
    cars.pick_station = _orig_pick_station
    calls = {'sar': 0, 'prox': 0}

    maps.get_route_geometry = lambda o, d, *a, **kw: {
        'geometry': {'coordinates': [[-84.0, 34.0], [-84.1, 34.1], [-84.2, 34.2]]}}

    def fake_category(cat, lat=None, lon=None, limit=10, route_coords=None, time_deviation_mins=8):
        if route_coords is not None:
            calls['sar'] += 1
            return [{'name': 'OnRoute Fuel', 'address': 'OnRoute Fuel, Hwy 9',
                     'lat': 34.1, 'lon': -84.1}]
        calls['prox'] += 1
        return []
    maps.search_category = fake_category

    st = cars.pick_station('A St', 'B Ave')
    check(st['source'] == 'sar' and st['name'] == 'OnRoute Fuel', f"SAR wins, got {st}")
    check(calls == {'sar': 1, 'prox': 0}, f"one SAR call only, got {calls}")

    # SAR and proximity both empty -> the fixed-station setting.
    maps.search_category = lambda *a, **kw: []
    st = cars.pick_station('A St', 'B Ave')
    check(st['source'] == 'setting' and st['name'] == 'Costco Gas, Main St', f"setting fallback, got {st}")

    # No route geometry and no setting -> near-origin search.
    storage.get_settings = lambda: dict(_BASE_SETTINGS)
    maps.get_route_geometry = lambda *a, **kw: None
    maps.geocode_address = lambda addr: (34.0, -84.0)
    maps.search_category = lambda cat, lat=None, lon=None, limit=10, **kw: (
        [{'name': 'Corner Gas', 'address': 'Corner Gas, A St', 'lat': lat, 'lon': lon}]
        if lat is not None else [])
    st = cars.pick_station('A St', 'B Ave')
    check(st['source'] == 'near_origin' and st['name'] == 'Corner Gas', f"near-origin fallback, got {st}")


def scenario_polyline_encoder():
    # Canonical example from the polyline algorithm docs (lat,lng pairs
    # (38.5,-120.2),(40.7,-120.95),(43.252,-126.453)) — coords arrive GeoJSON
    # [lon, lat].
    enc = maps._encode_polyline([[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]])
    check(enc == '_p~iF~ps|U_ulLnnqC_mqNvxq`@', f"canonical encoding, got {enc}")


def scenario_digest_fuel_notes():
    _reset()
    _mk_car(ha_fuel_entity='sensor.f')
    ha_api.get_state = lambda ent, *a, **kw: {'state': '15'} if ent == 'sensor.f' else None
    _cache_day(1, {'e3': 'c1'}, [_ev('e3', 'School run', 20)], assignments={'e3': 'd1'})
    notes = cars.digest_fuel_notes(TOMORROW)
    check('d1' in notes and 'Minivan' in notes['d1'] and '15%' in notes['d1'],
          f"driver-keyed fuel note, got {notes}")
    ha_api.get_state = lambda ent, *a, **kw: {'state': '80'} if ent == 'sensor.f' else None
    check(cars.digest_fuel_notes(TOMORROW) == {}, "healthy car -> no note")


def scenario_real_deliver_binds_family_channel():
    _reset()
    cars._deliver_proposal = _orig_deliver
    pid = cars._deliver_proposal('Fuel stop', {
        'car_id': 'c1', 'kind': 'fuel', 'title': 'x', 'location': 'y'}, 'body text')
    check(pid is not None, "proposal stored")
    prop = storage.get_action_proposal(pid)
    fam = storage.get_family_channel()
    check(prop['status'] == 'proposed' and prop['channel_id'] == fam['id'],
          f"bound to the family channel, got {prop}")


SCENARIOS = [
    scenario_sweep_proposes_fuel_once,
    scenario_evening_tomorrow_is_separate,
    scenario_approve_creates_errand,
    scenario_dismiss_and_admin_gate,
    scenario_auto_approve_setting,
    scenario_charge_buffer_reserves_time,
    scenario_pick_station_fallbacks,
    scenario_polyline_encoder,
    scenario_digest_fuel_notes,
    scenario_real_deliver_binds_family_channel,
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
        finally:
            cars.pick_station = _orig_pick_station
            cars._deliver_proposal = _orig_deliver
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
