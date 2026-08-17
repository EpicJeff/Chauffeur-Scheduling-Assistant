"""Arrival auto-complete (services/drive_arrival.py).

The property that is load-bearing: a FALSE complete is worse than a stale
flag — it un-tracks a drive that is genuinely happening. So every proof
requirement (started leg, cached street-level geocode, fresh precise fix,
inside the radius) has a scenario showing its absence keeps the leg alone.

Run from chauffeur/:  python tests/test_drive_arrival.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import drive_arrival, storage

NOW = datetime.datetime.now().timestamp()
FRESH = datetime.datetime.now(datetime.timezone.utc).isoformat()
STALE = (datetime.datetime.now(datetime.timezone.utc)
         - datetime.timedelta(hours=1)).isoformat()

# Music & Arts, and a phone in its parking lot ~60 m off the pin.
SHOP = (35.7327, -78.7811)
LOT = (35.7332, -78.7808)
ELSEWHERE = (35.79, -78.65)   # ~10 km away, mid-drive


def _person(latlon, updated=FRESH, acc=25):
    return {'state': 'not_home', 'attributes': {
        'latitude': latlon[0], 'longitude': latlon[1], 'gps_accuracy': acc},
        'last_updated': updated}


class _World:
    """One knob per proof requirement, defaults arranged to COMPLETE."""

    def __init__(self):
        self.legs = ['init_guitar']
        self.sched = {'events': [{'id': 'guitar', 'title': 'Guitar',
                                  'location': 'Music & Arts, Cary'}],
                      'assignments': {'guitar': 'drv_jeff'},
                      'car_assignments': {}}
        self.members = [{'id': 'm_jeff', 'name': 'Jeff', 'driver_id': 'drv_jeff',
                         'ha_person_entity': 'person.jeff'}]
        self.geocode = {'lat': SHOP[0], 'lon': SHOP[1], 'precision': 'exact'}
        self.person_state = _person(LOT)
        self.marked = []

    def install(self):
        self.orig = (storage.get_in_progress_drives, storage.get_cached_schedule,
                     storage.get_all_members, storage.get_cached_geocode,
                     storage.mark_drive_status, storage.get_all_cars)
        storage.get_in_progress_drives = lambda: list(self.legs)
        storage.get_cached_schedule = lambda: self.sched
        storage.get_all_members = lambda **k: self.members
        storage.get_cached_geocode = lambda addr: self.geocode
        storage.mark_drive_status = lambda leg, st: self.marked.append((leg, st))
        storage.get_all_cars = lambda: []
        import services.ha_api as ha_api
        self.orig_state = ha_api.get_state
        ha_api.get_state = lambda ent: self.person_state
        return self

    def restore(self):
        (storage.get_in_progress_drives, storage.get_cached_schedule,
         storage.get_all_members, storage.get_cached_geocode,
         storage.mark_drive_status, storage.get_all_cars) = self.orig
        import services.ha_api as ha_api
        ha_api.get_state = self.orig_state


def _run(mutate=None):
    w = _World()
    if mutate:
        mutate(w)
    w.install()
    try:
        done = drive_arrival.check_arrivals(NOW)
    finally:
        w.restore()
    return w, done


def scenario_arrived_at_the_lesson_completes_the_leg():
    w, done = _run()
    check(w.marked == [('init_guitar', 'completed')],
          f"a fresh fix 60m from the pin completes the started leg: {w.marked}")
    check(done and done[0]['leg_id'] == 'init_guitar' and done[0]['distance_m'] < 175,
          f"and the sweep reports what it did: {done}")


def scenario_mid_drive_is_left_alone():
    w, done = _run(lambda w: setattr(w, 'person_state', _person(ELSEWHERE)))
    check(w.marked == [] and done == [],
          "10 km from the destination nothing completes")


def scenario_a_stale_fix_proves_nothing():
    w, _ = _run(lambda w: setattr(w, 'person_state', _person(LOT, updated=STALE)))
    check(w.marked == [],
          "an hour-old fix at the destination does not complete the leg — "
          "the phone may have LEFT since")


def scenario_a_vague_fix_proves_nothing():
    w, _ = _run(lambda w: setattr(w, 'person_state', _person(LOT, acc=1500)))
    check(w.marked == [],
          "a 1.5 km cell fix cannot place anyone in a parking lot")


def scenario_city_precision_geocode_is_not_a_destination():
    w, _ = _run(lambda w: w.geocode.update(precision='city'))
    check(w.marked == [],
          '"arrived in Cary" proves nothing about a music shop')


def scenario_no_cached_geocode_never_triggers_a_lookup():
    w, _ = _run(lambda w: setattr(w, 'geocode', None))
    check(w.marked == [],
          "no cached geocode -> skip; a polling loop must never buy geocodes")


def scenario_only_started_legs_are_touched():
    w, _ = _run(lambda w: setattr(w, 'legs', []))
    check(w.marked == [],
          "arrival only closes the loop a human opened — no legs, no writes")


def scenario_final_leg_completes_at_home():
    def mutate(w):
        w.legs = ['final_guitar']
        # Home geocode; the phone is in the driveway.
        w.geocode = {'lat': LOT[0], 'lon': LOT[1], 'precision': 'exact'}
    import services.maps as maps
    orig_home = maps.get_home_location
    maps.get_home_location = lambda: '123 Home St'
    try:
        w, done = _run(mutate)
    finally:
        maps.get_home_location = orig_home
    check(w.marked == [('final_guitar', 'completed')],
          f"a final_* leg heads HOME and completes there: {w.marked}")


def scenario_untracked_driver_keeps_the_manual_button():
    w, _ = _run(lambda w: w.members[0].pop('ha_person_entity'))
    check(w.marked == [],
          "no person entity and no car tracker -> nothing changes; the "
          "manual complete button remains the whole story")


def scenario_the_push_loop_runs_the_sweep():
    import os
    main_src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'main.py'), encoding='utf-8').read()
    check('drive_arrival.check_arrivals' in main_src,
          "the sweep is no longer wired into the background loop")


# --- The ride-status slice: ETA at start, the tap check, the nudge -----------
# These use REAL drive-status storage (the harness isolates the data dir) and
# patch only the schedule/geocode/member reads — the row lifecycle (eta parked,
# nudge marker burned, merge-not-replace) is exactly what is under test.

class _TapWorld:
    def __init__(self):
        self.sched = {'events': [{'id': 'guitar', 'title': 'Guitar',
                                  'location': 'Music & Arts, Cary'}],
                      'assignments': {'guitar': 'drv_jeff'},
                      'ghost_assignments': {},
                      'initial_edges': {'drv_jeff': {'guitar': {'travel_mins': 17}}},
                      'final_edges': {'drv_jeff': {'guitar': {'travel_mins': 21}}},
                      'car_assignments': {}}
        self.members = [{'id': 'm_jeff', 'name': 'Jeff', 'driver_id': 'drv_jeff'}]
        self.geocode = {'lat': SHOP[0], 'lon': SHOP[1], 'precision': 'exact'}
        self.route = None            # what maps.get_route_geometry answers

    def install(self):
        with storage.db_lock:
            storage.drive_status_table.truncate()
        self.orig = (storage.get_cached_schedule, storage.get_all_members,
                     storage.get_cached_geocode)
        storage.get_cached_schedule = lambda: self.sched
        storage.get_all_members = lambda **k: self.members
        storage.get_cached_geocode = lambda addr: self.geocode
        import services.maps as maps
        self.orig_route = maps.get_route_geometry
        maps.get_route_geometry = lambda *a, **k: self.route
        return self

    def restore(self):
        (storage.get_cached_schedule, storage.get_all_members,
         storage.get_cached_geocode) = self.orig
        import services.maps as maps
        maps.get_route_geometry = self.orig_route


def _tap(mutate=None, fn=None):
    w = _TapWorld()
    if mutate:
        mutate(w)
    w.install()
    try:
        return w, fn(w)
    finally:
        w.restore()


def scenario_eta_at_start_prices_from_the_solvers_own_edges():
    """No fix, no problem: the solver already priced this exact drive."""
    def body(w):
        into = drive_arrival.eta_for_start('init_guitar', NOW)
        home = drive_arrival.eta_for_start('final_guitar', NOW)
        return into, home
    _, (into, home) = _tap(fn=body)
    check(into == NOW + 17 * 60, f"the initial edge's 17 minutes: {into}")
    check(home == NOW + 21 * 60, f"a final_ leg uses the drive-home edge: {home}")


def scenario_a_fix_at_start_upgrades_the_eta_to_a_routed_time():
    """Started from the store, not the driveway: the fix beats the edge."""
    def mutate(w):
        w.route = {'duration_mins': 9.0}
    _, eta = _tap(mutate, lambda w: drive_arrival.eta_for_start(
        'init_guitar', NOW, lat=ELSEWHERE[0], lng=ELSEWHERE[1], accuracy=30))
    check(eta == NOW + 9 * 60, f"routed from where the driver IS: {eta}")


def scenario_tap_at_the_destination_checks_the_leg_off():
    def body(w):
        storage.mark_drive_status('init_guitar', 'in_progress', eta_ts=NOW - 300)
        return drive_arrival.tap_check('init_guitar', lat=LOT[0], lng=LOT[1],
                                       accuracy=25, now_ts=NOW)
    _, res = _tap(fn=body)
    check(res['arrived'] is True and res['title'] == 'Guitar',
          f"the tap at the parking lot IS the confirmation: {res}")
    row = storage.get_drive_status('init_guitar')
    check(row['status'] == 'completed' and row.get('arrived_ts') == NOW,
          f"and the leg is closed with a timestamp: {row}")
    check(row.get('eta_ts') == NOW - 300,
          "completing merges — the ETA the start wrote survives")


def scenario_tap_far_away_parks_a_new_eta_and_shares_nothing():
    def body(w):
        storage.mark_drive_status('init_guitar', 'in_progress', eta_ts=NOW - 300)
        return drive_arrival.tap_check('init_guitar', lat=ELSEWHERE[0],
                                       lng=ELSEWHERE[1], accuracy=25, now_ts=NOW)
    _, res = _tap(fn=body)
    check(res['arrived'] is False and res['eta_mins'] >= 2,
          f"13 km out is verifiably not arrived, with an honest estimate: {res}")
    row = storage.get_drive_status('init_guitar')
    check(row['status'] == 'in_progress' and row.get('pending_eta_ts'),
          f"the new time is PARKED on the row: {row}")
    check(row.get('eta_ts') == NOW - 300,
          "…and the family's promised time is untouched until the driver "
          "chooses to share — the app never narrates lateness uninvited")


def scenario_tap_without_evidence_asks_the_human():
    _, res = _tap(fn=lambda w: (
        storage.mark_drive_status('init_guitar', 'in_progress'),
        drive_arrival.tap_check('init_guitar', now_ts=NOW))[1])
    check(res['arrived'] is None, f"no fix: the human decides — {res}")
    _, res2 = _tap(lambda w: w.geocode.update(precision='city'),
                   lambda w: (storage.mark_drive_status('init_guitar', 'in_progress'),
                              drive_arrival.tap_check('init_guitar', lat=LOT[0],
                                                      lng=LOT[1], accuracy=25,
                                                      now_ts=NOW))[1])
    check(res2['arrived'] is None,
          '"arrived in Cary" proves nothing at tap time either')


def scenario_the_sweep_beating_the_tap_reads_as_success():
    _, res = _tap(fn=lambda w: (
        storage.mark_drive_status('init_guitar', 'completed'),
        drive_arrival.tap_check('init_guitar', lat=LOT[0], lng=LOT[1],
                                accuracy=25, now_ts=NOW))[1])
    check(res['arrived'] is True and res.get('already'),
          f"a drive the sweep already closed is a success, not an error: {res}")


def scenario_the_nudge_fires_once_after_grace_and_only_at_the_driver():
    sent = []
    def notify(member, title, body, path):
        sent.append((member['id'], title, path))
    def body(w):
        storage.mark_drive_status('init_guitar', 'in_progress',
                                  eta_ts=NOW - drive_arrival.NUDGE_GRACE_SECS - 10)
        first = drive_arrival.run_nudges(NOW, notify)
        second = drive_arrival.run_nudges(NOW, notify)
        return first, second
    _, (first, second) = _tap(fn=body)
    check(first == ['init_guitar'] and second == [],
          f"one nudge, ever: {first} then {second}")
    check(sent == [('m_jeff', 'Arrived at Guitar?', '/app?arrival=init_guitar')],
          f"addressed to the DRIVER, deep-linking the tap check: {sent}")


def scenario_the_nudge_respects_grace_and_expires_silently():
    sent = []
    def body(w):
        storage.mark_drive_status('init_guitar', 'in_progress', eta_ts=NOW - 60)
        early = drive_arrival.run_nudges(NOW, lambda *a: sent.append(a))
        storage.mark_drive_status('route_guitar', 'in_progress',
                                  eta_ts=NOW - drive_arrival.NUDGE_EXPIRE_SECS - 60)
        late = drive_arrival.run_nudges(NOW, lambda *a: sent.append(a))
        return early, late
    _, (early, late) = _tap(fn=body)
    check(early == [] and late == [] and sent == [],
          "an estimate deserves slack, and ancient legs are never pushed about")
    row = storage.get_drive_status('route_guitar')
    check(row.get('arrival_nudged_ts'),
          "the expired leg's marker burns silently — a restart cannot "
          "resurrect a push about yesterday's drive")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} drive-arrival scenarios passed")
