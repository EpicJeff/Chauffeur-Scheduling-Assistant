"""Errands with common sense — the writers, the routes, the agent, the editor fields.

Spec: docs/superpowers/specs/2026-10-22-errands-common-sense-design.md
§4.2 (both writers teach), §5 (routes, fields, agent tools).

Run from chauffeur/:  python tests/test_errand_prefs_api.py
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_errand_prefs_api_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from services import storage  # noqa: E402


def _fresh():
    with storage.db_lock:
        storage.errands_table.truncate()
        storage.daily_schedules_table.truncate()
        storage.app_state_table.truncate()
        storage.drivers_table.truncate()
        storage.drivers_table.insert({'id': 'd1', 'name': 'Jeff', 'home_location': 'Home', 'color_code': '#000'})
        storage.drivers_table.insert({'id': 'd2', 'name': 'Lorena', 'home_location': 'Home', 'color_code': '#000'})


def _errand(**over):
    base = {'id': over.pop('id', 'e-' + str(time.time_ns())), 'title': 'Costco run',
            'duration_mins': 30, 'location': 'Costco', 'priority': 2,
            'is_completed': False, 'status': 'pending', 'created_at': time.time(),
            'starts_on': None, 'recurrence_rule': None, 'tags': [],
            'skip_dates': [], 'pinned_date': None, 'pinned_start': None,
            'pinned_end': None, 'once_driver_id': None, 'kind': None, 'home_bound': None}
    base.update(over)
    return base


def _row(errand_id, date_str, driver_id='d1'):
    return {'id': errand_id, 'driver': {'id': driver_id, 'name': 'Jeff'},
            'start': f'{date_str}T16:10:00', 'start_time': f'{date_str}T16:10:00',
            'end': f'{date_str}T16:40:00', 'end_time': f'{date_str}T16:40:00',
            'title': 'Costco run', 'location': 'Costco', 'kind': 'groceries',
            'why': {'kind': 'on_the_way', 'detour_mins': 6, 'driver_name': 'Jeff',
                    'leg': {'from': 'Work', 'to': 'Home'}, 'text': "on Jeff's way home from Work, +6 min"}}


def _cache_row(date_str, row):
    with storage.db_lock:
        storage.daily_schedules_table.insert({'date': date_str, 'schedule': {'scheduled_errands': [row]}})


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app), main


def scenario_the_put_teaches_before_it_forgets():
    _fresh()
    client, main = _client()
    doc_id = storage.add_errand(_errand(id='e-put'))
    _cache_row('2026-10-31', _row('e-put', '2026-10-31'))       # a Saturday
    body = dict(storage.get_errand_by_id(doc_id))
    body.pop('doc_id', None)
    body['skip_dates'] = ['2026-10-31']
    r = client.put(f'/api/errands/{doc_id}', json=body)
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    prefs = storage.get_errand_preferences()
    check(len(prefs) == 1 and (prefs[0]['scope'], prefs[0]['kind'], prefs[0]['dimension'], prefs[0]['value'], prefs[0]['polarity'])
          == ('d1', 'groceries', 'weekday', '5', 'avoid'), f"the steer taught Jeff's groceries not on Saturdays: {prefs}")
    check(storage.get_all_scheduled_errand_rows().get('e-put') is None, "and the placement was forgotten after")


def scenario_the_agent_teaches_the_same_row():
    _fresh()
    from services import agent_tools_v2 as tools
    storage.add_errand(_errand(id='e-agent'))
    _cache_row('2026-10-31', _row('e-agent', '2026-10-31'))
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'skip_date': '2026-10-31'})
    check(out['status'] == 'success', f"{out}")
    prefs = storage.get_errand_preferences()
    check(len(prefs) == 1 and (prefs[0]['scope'], prefs[0]['dimension'], prefs[0]['value'], prefs[0]['polarity'])
          == ('d1', 'weekday', '5', 'avoid'), f"{prefs}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'once_driver_id': 'd2'})
    prefs = storage.get_errand_preferences()
    check(any(p['dimension'] == 'driver' and p['value'] == 'd2' and p['scope'] == '*' for p in prefs), f"{prefs}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'duration_mins': 45})
    check(len(storage.get_errand_preferences()) == 2, "an edit teaches nothing")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'is_completed': True})
    check(len(storage.get_errand_preferences()) == 2, "completion teaches nothing")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand-prefs API scenarios passed")
