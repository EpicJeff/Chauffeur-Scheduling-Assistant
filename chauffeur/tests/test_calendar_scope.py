"""The grandparent endpoint (family-network arc S5).

`/api/calendar/events` is the §8 good news made real: it already returned
titles and times with no assignment, edge, car, carpool-contact or
driver-calendar key — S5 teaches it who is looking. A keeping-up adult gets
the children's events and nothing about the adults'; a child gets their own;
a guest gets nothing; parents, household adults and the tokenless dashboard
trip-linker keep today's behaviour exactly.

Run from chauffeur/:  python tests/test_calendar_scope.py
"""
import datetime
from types import SimpleNamespace

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import storage
from services import calendar as cal_svc


class Req:
    def __init__(self, token=None):
        self.headers = {'x-member-token': token} if token else {}
        self.query_params = {}


def _seed():
    storage.members_table.truncate()
    storage.passengers_table.truncate()
    storage.add_passenger({'id': 'p_emma', 'name': 'Emma',
                           'calendar_ids': ['cal_emma'], 'hashtags': []})
    storage.add_passenger({'id': 'p_jack', 'name': 'Jack',
                           'calendar_ids': ['cal_jack'], 'hashtags': []})
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "gran", "name": "Gran", "role": "adult",
                        "scope": {"preset": "keeping_up"}})
    storage.add_member({"id": "emma", "name": "Emma", "role": "child",
                        "passenger_id": "p_emma"})
    storage.add_member({"id": "jack", "name": "Jack", "role": "child",
                        "passenger_id": "p_jack"})
    # No creatable path to this role until S15 — seeded at the storage layer
    # precisely to pin the refusal before the role ever ships.
    storage.add_member({"id": "cuz", "name": "Cousin", "role": "guest"})
    return {mid: storage.create_member_token(mid)
            for mid in ("mom", "gran", "emma", "jack", "cuz")}


def _fake_events():
    t = datetime.datetime(2026, 8, 25, 16, 0)
    mk = lambda i, title, cals: SimpleNamespace(
        id=i, title=title, start=t, event_type='standard', trip_id=None,
        source_event_ids=[], calendar_ids=cals)
    return [mk('e1', 'Volleyball', ['cal_emma']),
            mk('e2', 'Recital', ['cal_jack']),
            mk('e3', 'Poker night', ['cal_adults'])]


def _titles(res):
    return {e['title'] for e in res['events']}


def _run(fn):
    real = cal_svc.fetch_upcoming_events
    cal_svc.fetch_upcoming_events = lambda *a, **k: _fake_events()
    try:
        return fn()
    finally:
        cal_svc.fetch_upcoming_events = real


def scenario_keeping_up_gets_the_kids_calendar_and_nothing_else():
    import main
    tok = _seed()

    def body():
        res = main.list_calendar_events_api('2026-08-25', '2026-08-26',
                                            request=Req(tok['gran']))
        check(_titles(res) == {'Volleyball', 'Recital'},
              f"the children's events only — an adult-only event is absent "
              f"entirely, got {_titles(res)}")
        for e in res['events']:
            check(set(e) == {'id', 'title', 'start', 'event_type', 'trip_id',
                             'source_event_ids', 'calendar_ids'},
                  f"titles and times, and NO assignment, edge, car, "
                  f"carpool-contact or driver-calendar key: {sorted(e)}")
    _run(body)


def scenario_a_child_gets_their_own():
    import main
    tok = _seed()

    def body():
        res = main.list_calendar_events_api('2026-08-25', '2026-08-26',
                                            request=Req(tok['emma']))
        check(_titles(res) == {'Volleyball'},
              f"reach own is Emma's rows and nothing of Jack's: {_titles(res)}")
    _run(body)


def scenario_a_guest_gets_nothing():
    import main
    tok = _seed()

    def body():
        res = main.list_calendar_events_api('2026-08-25', '2026-08-26',
                                            request=Req(tok['cuz']))
        check(res['events'] == [], "calendar.events: none is an empty list")
    _run(body)


def scenario_todays_behaviour_is_reproduced_for_everyone_else():
    import main
    tok = _seed()

    def body():
        for req, who in ((Req(tok['mom']), 'a parent'),
                         (Req(), 'the tokenless trip linker')):
            res = main.list_calendar_events_api('2026-08-25', '2026-08-26',
                                                request=req)
            check(_titles(res) == {'Volleyball', 'Recital', 'Poker night'},
                  f"{who} keeps today's behaviour exactly")
    _run(body)


SCENARIOS = [
    scenario_keeping_up_gets_the_kids_calendar_and_nothing_else,
    scenario_a_child_gets_their_own,
    scenario_a_guest_gets_nothing,
    scenario_todays_behaviour_is_reproduced_for_everyone_else,
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
