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


def scenario_the_preference_routes_list_delete_and_clear_as_a_parent():
    _fresh()
    client, main = _client()
    a = storage.upsert_errand_preference({'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
                                          'polarity': 'avoid', 'source': 'steer'}, now=time.time())
    b = storage.upsert_errand_preference({'scope': '*', 'kind': 'return', 'dimension': 'driver', 'value': 'd2',
                                          'polarity': 'prefer', 'source': 'steer'}, now=time.time())
    r = client.get('/api/errands/preferences')
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    rows = r.json()['rows']
    texts = sorted(x['text'] for x in rows)
    check(texts == ['Jeff: groceries not on Saturdays (learned from 1 steer)', 'Lorena runs returns (learned from 1 steer)'], f"{texts}")
    r = client.delete(f'/api/errands/preferences/{a["id"]}')
    check(r.status_code == 200 and len(storage.get_errand_preferences()) == 1, f"{r.status_code} {r.text}")
    r = client.delete('/api/errands/preferences/nope')
    check(r.status_code == 404, f"{r.status_code}")
    r = client.delete('/api/errands/preferences')
    check(r.status_code == 200 and r.json()['removed'] == 1 and storage.get_errand_preferences() == [], f"{r.text}")
    from services import auth
    check(auth.resolve('GET', '/api/errands/preferences') == auth.PARENTS, "listing is parents only")
    check(auth.resolve('DELETE', '/api/errands/preferences/{pref_id}') == auth.PARENTS, "deleting is parents only")
    check(auth.resolve('GET', '/api/errands') != auth.PARENTS, "the errands list itself stays as it was")


def scenario_kind_and_home_bound_round_trip_and_forget_placements():
    _fresh()
    client, main = _client()
    doc_id = storage.add_errand(_errand(id='e-kind', title='Costco run'))
    _cache_row('2026-10-29', _row('e-kind', '2026-10-29'))
    r = client.get('/api/errands')
    me = next(x for x in r.json() if x['id'] == 'e-kind')
    check(me['kind'] is None and me['kind_inferred'] == 'groceries' and me['home_bound'] is None, f"{me}")
    body = {k: v for k, v in me.items() if k not in ('placement', 'unplaced', 'generation', 'shopping_lists', 'kind_inferred', 'scheduled_start')}
    body['home_bound'] = False
    r = client.put(f'/api/errands/{doc_id}', json=body)
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    check(storage.get_errand_by_id(doc_id)['home_bound'] is False, "saved")
    check(storage.get_all_scheduled_errand_rows().get('e-kind') is None, "a routing field changed: placement forgotten")
    check(storage.get_errand_preferences() == [], "a flag edit teaches nothing")
    body['kind'] = 'snacks'
    r = client.put(f'/api/errands/{doc_id}', json=body)
    check(r.status_code == 422, f"an unknown kind is refused: {r.status_code}")


def scenario_a_rule_copies_kind_and_home_bound_onto_a_new_errand():
    _fresh()
    client, main = _client()
    storage.add_errand_rule({'title': 'Grocery runs', 'constraint_type': 'driver_assignment', 'keywords': ['costco'],
                             'kind': 'groceries', 'home_bound': False, 'is_enabled': True})
    r = client.post('/api/errands', json=_errand(id='e-rule', title='Costco run'))
    check(r.status_code == 200, f"{r.status_code} {r.text}")
    saved = storage.get_errand_by_id('e-rule')
    check(saved['kind'] == 'groceries' and saved['home_bound'] is False, f"{saved}")
    r = client.post('/api/errands', json=_errand(id='e-rule2', title='Costco run', home_bound=True))
    saved = storage.get_errand_by_id('e-rule2')
    check(saved['home_bound'] is True, "the errand's own value beats the rule")


def scenario_the_agent_sets_kind_and_home_bound_and_reads_and_forgets_preferences():
    _fresh()
    from services import agent_tools_v2 as tools, missions, maps
    maps.resolve_routable_location = lambda loc: loc      # never geocode in a unit test
    out = tools.handle_add_errand({'title': 'Costco run', 'duration_mins': 30, 'location': 'Costco', 'home_bound': False})
    doc_id = int(out['created'][0]['id'])
    saved = storage.get_errand_by_id(doc_id)
    check(saved['home_bound'] is False and saved.get('kind') is None, f"{saved}")
    out = tools.handle_update_errand({'errand_id': str(doc_id), 'kind': 'service', 'home_bound': True})
    check(out['status'] == 'success', f"{out}")
    saved = storage.get_errand_by_id(doc_id)
    check(saved['kind'] == 'service' and saved['home_bound'] is True, f"{saved}")
    out = tools.handle_update_errand({'errand_id': str(doc_id), 'kind': 'snacks'})
    check(out['status'] == 'error' and 'kind' in out['message'], f"{out}")
    n_before = len(storage.get_all_errands())
    out = tools.handle_add_errand({'title': 'Snack run', 'duration_mins': 10, 'location': 'Shop', 'kind': 'snacks'})
    check(out['status'] == 'error' and 'kind' in out['message'] and len(storage.get_all_errands()) == n_before,
          f"add_errand refuses an unknown kind the same way update does, and saves nothing: {out}")
    a = storage.upsert_errand_preference({'scope': 'd1', 'kind': 'groceries', 'dimension': 'weekday', 'value': '5',
                                          'polarity': 'avoid', 'source': 'steer'}, now=time.time())
    storage.upsert_errand_preference({'scope': '*', 'kind': 'return', 'dimension': 'driver', 'value': 'd2',
                                      'polarity': 'prefer', 'source': 'steer'}, now=time.time())
    out = tools.handle_get_errand_preferences({})
    check(out['status'] == 'success' and sorted(r['text'] for r in out['rows'])
          == ['Jeff: groceries not on Saturdays (learned from 1 steer)', 'Lorena runs returns (learned from 1 steer)'], f"{out}")
    out = tools.handle_forget_errand_preference({'preference_id': a['id']})
    check(out['status'] == 'success' and len(storage.get_errand_preferences()) == 1, f"{out}")
    out = tools.handle_forget_errand_preference({'preference_id': 'nope'})
    check(out['status'] == 'error', f"{out}")
    out = tools.handle_forget_errand_preference({'preference_id': 'all'})
    check(out['status'] == 'success' and storage.get_errand_preferences() == [], f"{out}")
    for name in ('get_errand_preferences', 'forget_errand_preference'):
        check(name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS and name in tools.ADMIN_TOOLS, f"{name} registered")
    check('get_errand_preferences' in missions.READ_TOOLS, "a read is a read")
    check('forget_errand_preference' in tools.SCHEDULE_MUTATING_ADMIN_TOOLS, "forgetting re-plans")
    schema = tools.TOOL_SCHEMAS['update_errand']['properties']
    check('kind' in schema and 'home_bound' in schema, "the hand path's fields are the agent's too")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand-prefs API scenarios passed")
