"""The packing endpoints, exercised the way the wall's card actually calls
them: GET /api/packing/day builds the day's outings with their kit items and
claim counts, POST /api/packing/claim moves one item's count up or down.

FastAPI's TestClient needs httpx, which is not installed in this environment
(`starlette.testclient` raises `RuntimeError` on import here), so these
scenarios call the endpoint functions directly -- the same pattern already in
use for the pets battle endpoints (`tests/test_pet_battles_api.py`): a plain
Python call with a dict standing in for the request body, and FastAPI's own
`HTTPException` caught by hand where a scenario expects a refusal.

Run from chauffeur/:  python tests/test_packing_api.py
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_packing_api_'))

from services import storage  # noqa: E402

DAY = '2026-09-08'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()


def _ev(eid, hh, mm=0, dur=60, title=None, cal_ids=None):
    start = datetime.datetime(2026, 9, 8, hh, mm)
    return {'id': eid, 'title': title or eid,
            'start': start.isoformat(),
            'end': (start + datetime.timedelta(minutes=dur)).isoformat(),
            'calendar_ids': cal_ids or []}


def _seed_incident():
    """Soccer at 16:00, band at 17:30, one driver, no room to get home in
    between -- the same shape test_outings.py's incident fixture uses, now
    carrying two kits so the day endpoint has something to group."""
    reset_db()
    storage.add_driver({'id': 'd1', 'name': 'Dad', 'color_code': '#2563eb',
                        'group': 'primary', 'priority_index': 1})
    storage.add_passenger({'id': 'ellie', 'name': 'Ellie', 'calendar_ids': []})
    k1 = storage.add_prep_kit({'id': 'k1', 'name': 'Soccer bag',
                               'items': ['Water bottle'], 'enabled': True,
                               'per_person': True, 'keywords': ['soccer'],
                               'passenger_ids': ['ellie']})
    k2 = storage.add_prep_kit({'id': 'k2', 'name': 'Band bag',
                               'items': ['Sheet music'], 'enabled': True,
                               'per_person': True, 'keywords': ['band'],
                               'passenger_ids': ['ellie']})
    sched = {
        'events': [_ev('soccer', 16, cal_ids=['ellie']),
                  _ev('band', 17, 30, cal_ids=['ellie'])],
        'assignments': {'soccer': 'd1', 'band': 'd1'},
        'route_edges': {'d1': {'soccer': {'to_event': 'band', 'travel_mins': 20}}},
        'initial_edges': {}, 'final_edges': {}, 'cars': [], 'car_assignments': {},
    }
    storage.set_cached_schedule(sched)
    return k1, k2


def scenario_the_day_endpoint_groups_by_outing():
    """Two events on one trip are ONE packing job. That grouping IS the message
    — at four activities a day, a sentence saying 'you are not stopping home'
    would fire constantly and stop being read."""
    _seed_incident()
    import main
    out = main.packing_day(date=DAY)
    check(out['date'] == DAY, f"wrong day in the response: {out['date']}")
    check(len(out['outings']) == 1,
          f"two events with no way home should be one outing: {out['outings']}")
    outing = out['outings'][0]
    check(outing['event_ids'] == ['soccer', 'band'],
          f"the outing does not carry both events: {outing['event_ids']}")
    check(outing['driver_id'] == 'd1' and outing['driver'] == 'Dad',
          f"the outing lost its driver: {outing}")
    check(outing['color'] == '#2563eb',
          f"the outing should carry the driver's real color_code: {outing['color']}")
    labels = sorted(i['label'] for g in outing['groups'] for i in g['items'])
    check(labels == ['Sheet music', 'Water bottle'],
          f"both kits' items should be on the outing: {labels}")
    check(outing['needed'] == 2, f"needed should count one item from each kit: {outing['needed']}")
    check(outing['packed'] == 0, f"nothing has been packed yet: {outing['packed']}")


def scenario_a_claim_moves_the_count_and_comes_back():
    _seed_incident()
    import main
    outing_key = 'd1:soccer'
    item_key = 'k1:water bottle'
    res = main.packing_claim(payload={'outing_key': outing_key, 'item_key': item_key,
                                      'delta': 1, 'date': DAY})
    check(res['ok'] is True and res['packed'] == 1,
          f"a +1 claim should read back as packed=1: {res}")
    fresh = main.packing_day(date=DAY)
    item = next(i for g in fresh['outings'][0]['groups'] for i in g['items']
               if i['key'] == item_key)
    check(item['packed'] == 1, f"a fresh GET should also see the claim: {item}")

    res2 = main.packing_claim(payload={'outing_key': outing_key, 'item_key': item_key,
                                       'delta': -1, 'date': DAY})
    check(res2['ok'] is True and res2['packed'] == 0,
          f"a -1 claim should bring the count back to 0: {res2}")
    fresh2 = main.packing_day(date=DAY)
    item2 = next(i for g in fresh2['outings'][0]['groups'] for i in g['items']
                if i['key'] == item_key)
    check(item2['packed'] == 0, f"a fresh GET should see the claim come back: {item2}")


def scenario_a_claim_needs_a_real_outing_and_item():
    """A garbage outing_key is refused, not filed -- a stale card cannot write
    a claim against a trip that no longer exists and never be seen again."""
    _seed_incident()
    import main
    from fastapi import HTTPException
    try:
        main.packing_claim(payload={'outing_key': 'not-a-real-outing',
                                    'item_key': 'k1:water bottle',
                                    'delta': 1, 'date': DAY})
        raise AssertionError("a claim against a fake outing was filed instead of refused")
    except HTTPException as e:
        check(e.status_code == 404, f"wrong refusal: {e.status_code}")
    check(storage.get_packing_claims(DAY) == [],
          "the refused claim was written anyway")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} packing api scenarios passed")
