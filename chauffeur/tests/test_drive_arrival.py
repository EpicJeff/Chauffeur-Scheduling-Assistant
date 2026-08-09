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
        storage.get_all_members = lambda: self.members
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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} drive-arrival scenarios passed")
