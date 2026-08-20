"""The welded payloads take a viewer (family-network arc S9, §8).

Four payloads answered without asking who was looking; each now shapes its
answer from the viewer's field facets, applied where the data is ASSEMBLED
so every route inherits it. The §13 assertions live here: the meals plan
loses every place for a location-none viewer; a member's day loses driver
identity and leave-by for a keeping-up viewer; the family map narrows by
sees_people; and the schedule blob drops the ten driving keys plus the live
drives — asserted key by key — with /api/home_board redacting exactly the
same way because it runs the same redactor.

Run from chauffeur/:  python tests/test_welded_payloads.py
"""
import datetime

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import BackgroundTasks

from services import scope, storage


class Req:
    def __init__(self, token=None):
        self.headers = {'x-member-token': token} if token else {}
        self.query_params = {}


GRAN = {'id': 'gran', 'role': 'adult', 'scope': {'preset': 'keeping_up'}}

# §8.1's ten keys, plus the live-drive pair the doc calls out alongside them.
DRIVING_KEYS = ('assignments', 'ghost_assignments', 'ghost_drivers',
                'car_assignments', 'assist_assignments', 'assist_contacts',
                'route_edges', 'initial_edges', 'final_edges', 'driver_events',
                'completed_drives', 'in_progress_drives')


def _seed():
    storage.members_table.truncate()
    storage.passengers_table.truncate()
    storage.add_passenger({'id': 'p_emma', 'name': 'Emma',
                           'calendar_ids': ['cal_emma'], 'hashtags': []})
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "dad", "name": "Dad", "role": "adult",
                        "driver_id": "d_dad"})
    storage.add_member({"id": "gran", "name": "Gran", "role": "adult",
                        "scope": {"preset": "keeping_up"}})
    storage.add_member({"id": "aunt", "name": "Aunt", "role": "adult",
                        "scope": {"sees_people": {"kind": "chosen",
                                                  "ids": ["emma"]}}})
    storage.add_member({"id": "emma", "name": "Emma", "role": "child",
                        "is_child": True, "passenger_id": "p_emma"})
    storage.add_member({"id": "jack", "name": "Jack", "role": "child",
                        "is_child": True})
    return {mid: storage.create_member_token(mid)
            for mid in ("mom", "dad", "gran", "aunt", "emma", "jack")}


def _blob():
    return {
        'events': [
            {'id': 'ev1', 'title': 'Volleyball', 'calendar_ids': ['cal_emma'],
             'start': '2026-08-21T16:00:00', 'end': '2026-08-21T17:30:00'},
            {'id': 'ev2', 'title': 'Poker night', 'calendar_ids': ['cal_adults'],
             'start': '2026-08-21T20:00:00', 'end': '2026-08-21T22:00:00'},
            {'id': 'ev3', 'title': 'Karate', 'calendar_ids': ['cal_family'],
             'start': '2026-08-22T10:00:00', 'end': '2026-08-22T11:00:00'},
        ],
        'assignments': {'ev1': 'd_dad'}, 'ghost_assignments': {},
        'ghost_drivers': [], 'car_assignments': {'ev1': 'car1'},
        'assist_assignments': {}, 'assist_contacts': [{'id': 'ac1',
                                                       'name': 'Carpool Kim',
                                                       'phone': '555'}],
        'route_edges': {'d_dad': {}}, 'initial_edges': {'d_dad': {}},
        'final_edges': {'d_dad': {}}, 'driver_events': {'d_dad': ['ev1']},
        'diagnostics': {'note': 'x'}, 'unassigned': [],
        # A kid event bound by RULE, not calendar — the binding My Day's
        # fourth way carries. The keeping-up blank-tab bug was this event
        # vanishing because attribution ignored matched_rules.
        'matched_rules': {'ev3': [{'passenger_ids': ['p_emma']}]},
        'calendar_metadata': {}, 'drivers': [], 'passengers': [], 'cars': [],
    }


def scenario_the_meal_plan_stops_saying_where():
    from services import meals
    plan = {
        'people': [{'member_id': 'emma', 'name': 'Emma', 'role': 'child',
                    'slots': [{'start': 'a', 'end': 'b', 'mins': 30,
                               'modality': 'in_car', 'where': 'practice',
                               'label': 'In the car to practice', 'meal': 'dinner'}],
                    'first': {'where': 'practice', 'label': 'In the car'}}],
        'no_slot': [], 'away': [{'member_id': 'dad', 'name': 'Dad'}],
        'sittings': [{'label': '5:00–5:30 at practice', 'where': 'practice',
                      'where_kind': 'in_car', 'member_ids': ['emma']}],
        'lines': ['Emma eats in the car to practice'],
    }
    red = meals.redact_plan_for_viewer(plan, GRAN)
    check(all(s['where'] is None and s['label'] == ''
              for p in red['people'] for s in p['slots']),
          "no slot says where (§13: no `where`)")
    check(red['away'] == [], "who is away is not said (§13: no `away_on_trip`)")
    check(all(g['where'] is None and 'practice' not in g['label']
              for g in red['sittings']), "sittings keep times, lose places")
    check(red['lines'] == [], "the prose lines cannot leak what the keys hide")
    check(meals.redact_plan_for_viewer(plan, {'id': 'm', 'role': 'parent'}) is plan,
          "a full-reach viewer's plan is untouched")
    check(meals.redact_plan_for_viewer(plan, None) is plan,
          "no viewer, no change — a panel is a place")


def scenario_a_day_read_by_keeping_up_loses_the_driving():
    import main
    tok = _seed()
    storage.set_cached_schedule(_blob())
    day = main.member_day("emma", date="2026-08-21", request=Req(tok['gran']))
    check(day['rides'], "the ride itself survives — the calendar is hers")
    check(all(r['driver'] is None and r['car'] is None for r in day['rides']),
          "…with no driver identity and no car (§8.3)")
    check(day['launch'] is None, "and no leave-by (schedule.logistics: none)")
    day_mom = main.member_day("emma", date="2026-08-21", request=Req(tok['mom']))
    check(any(r['driver'] for r in day_mom['rides']),
          "a parent's read of the same day keeps the driver")


def scenario_the_map_narrows_by_sees_people():
    import main
    tok = _seed()
    rows = main.family_locations(request=Req(tok['aunt']))
    ids = {r['member_id'] for r in rows}
    check(ids == {'aunt', 'emma'},
          f"sees_people [emma]: Emma's row and their own, nothing of Jack's — {ids}")
    rows_mom = main.family_locations(request=Req(tok['mom']))
    check({'emma', 'jack'} <= {r['member_id'] for r in rows_mom},
          "everyone-scoped viewers keep the whole map")


def scenario_the_blob_drops_the_driving_keys_key_by_key():
    import main
    tok = _seed()
    storage.set_cached_schedule(_blob())
    got = main.get_schedule(BackgroundTasks(), request=Req(tok['gran']))
    for k in DRIVING_KEYS:
        check(k not in got, f"§13, asserted key by key: '{k}' must be ABSENT")
    check('diagnostics' not in got and 'matched_rules' not in got,
          "solver reasoning is nobody's but a debugging parent's")
    titles = [e['title'] for e in got['events']]
    check(titles == ['Volleyball', 'Karate'],
          f"events narrowed to the children's — the RULE-bound one included, "
          f"the adult-only one absent: {titles}")

    full = main.get_schedule(BackgroundTasks(), request=Req(tok['mom']))
    for k in DRIVING_KEYS:
        check(k in full, f"a parent keeps '{k}'")
    bare = main.get_schedule(BackgroundTasks(), request=Req())
    check('assignments' in bare and 'driver_events' in bare,
          "tokenless callers (panels) get the whole blob exactly as before")


def scenario_the_board_redacts_exactly_as_the_schedule_does():
    _seed()
    gran = storage.get_member('gran')
    blob = _blob()
    board = {'tiles': [{'type': 'drives', 'schedule': blob},
                       {'type': 'weather', 'days': []}]}
    red = scope.redact_board(board, gran)
    tile = red['tiles'][0]['schedule']
    direct = scope.redact_schedule_blob(blob, gran)
    check(set(tile) == set(direct),
          "§13: the board's schedule tile and /api/schedule agree key-for-key "
          "for the same viewer — same redactor, by construction")
    check('assignments' in blob and 'assignments' in board['tiles'][0]['schedule'],
          "copy-on-write: the cached original the panels share is untouched")
    check(scope.redact_board(board, None) is board,
          "no viewer, no copy — the panel path costs nothing")


def scenario_a_claim_narrows_and_can_never_grant():
    """The lived case: a phone whose token lapsed. With NO identity the blob
    is whole (a panel is a place), so honouring a claim can only ever make
    the answer smaller — the mirror of the auth arc's rule that a claim must
    never GRANT. Without this, scope silently did not apply to any session
    whose token had gone stale."""
    import main
    tok = _seed()
    storage.set_cached_schedule(_blob())

    class ClaimReq:
        def __init__(self, viewer=None, token=None):
            self.headers = {'x-member-token': token} if token else {}
            self.query_params = {'viewer': viewer} if viewer else {}

    claimed = main.get_schedule(BackgroundTasks(), request=ClaimReq(viewer='gran'))
    check('assignments' not in claimed,
          "a tokenless claim still redacts the driving keys")
    check([e['title'] for e in claimed['events']] == ['Volleyball', 'Karate'],
          f"…and narrows to her people: {[e['title'] for e in claimed['events']]}")

    bare = main.get_schedule(BackgroundTasks(), request=ClaimReq())
    check('assignments' in bare,
          "no claim, no token: the panel's whole blob, unchanged")

    # A claim cannot escalate: the TOKEN wins whenever one is present.
    both = main.get_schedule(BackgroundTasks(),
                             request=ClaimReq(viewer='mom', token=tok['gran']))
    check('assignments' not in both,
          "claiming to be a parent while holding her token grants nothing")


SCENARIOS = [
    scenario_the_meal_plan_stops_saying_where,
    scenario_a_day_read_by_keeping_up_loses_the_driving,
    scenario_the_map_narrows_by_sees_people,
    scenario_the_blob_drops_the_driving_keys_key_by_key,
    scenario_the_board_redacts_exactly_as_the_schedule_does,
    scenario_a_claim_narrows_and_can_never_grant,
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
