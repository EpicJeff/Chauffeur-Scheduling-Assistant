"""Errands ride the route — storage, API and agent contract.

Spec: docs/superpowers/specs/2026-10-22-errands-ride-the-route-design.md
§3 (placement/unplaced on GET), §4.1 (fields + validators), §4.3
(completion and the recurring successor), §4.4 (a steer forgets placements),
§4.6 (the agent writes by doc_id), §5 (the setting round trip).

Run from chauffeur/:  python tests/test_errand_routing_api.py
"""
import datetime
import os
import sys
import tempfile
import time

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_errand_api_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from services import storage  # noqa: E402

WEEK = 7 * 86400


def _fresh():
    with storage.db_lock:
        storage.errands_table.truncate()
        storage.daily_schedules_table.truncate()
        storage.app_state_table.truncate()


def _errand(**over):
    base = {'id': over.pop('id', 'e-' + str(time.time_ns())), 'title': 'Costco run',
            'duration_mins': 30, 'location': 'Costco', 'priority': 2,
            'is_completed': False, 'status': 'pending', 'created_at': time.time(),
            'starts_on': None, 'recurrence_rule': None, 'tags': [],
            'skip_dates': [], 'pinned_date': None, 'pinned_start': None,
            'pinned_end': None, 'once_driver_id': None}
    base.update(over)
    return base


def _row(errand_id, date_str, driver_id='d1'):
    return {'id': errand_id, 'driver': {'id': driver_id, 'name': 'Jeff'},
            'start': f'{date_str}T16:10:00', 'start_time': f'{date_str}T16:10:00',
            'end': f'{date_str}T16:40:00', 'end_time': f'{date_str}T16:40:00',
            'title': 'Costco run', 'location': 'Costco',
            'why': {'kind': 'on_the_way', 'detour_mins': 6, 'driver_name': 'Jeff',
                    'leg': {'from': 'Home', 'to': 'Soccer'},
                    'text': "on Jeff's way to Soccer, +6 min"}}


def scenario_the_errand_model_carries_steer_fields_and_validates_them():
    from models.schemas import Errand, STEER_FIELDS
    e = Errand(**_errand(skip_dates=['2026-10-27'], pinned_date='2026-10-31',
                         pinned_start='09:00', pinned_end='11:00', once_driver_id='d2'))
    check(e.skip_dates == ['2026-10-27'] and e.pinned_date == '2026-10-31'
          and e.pinned_start == '09:00' and e.once_driver_id == 'd2',
          "the four steer fields round-trip through the model")
    check(set(STEER_FIELDS) == {'skip_dates', 'pinned_date', 'pinned_start', 'pinned_end', 'once_driver_id'},
          f"STEER_FIELDS names the one-shot fields: {STEER_FIELDS}")
    for bad in ({'pinned_date': '31/10/2026'}, {'skip_dates': ['tomorrow']},
                {'pinned_start': '9am'}, {'pinned_end': '25:00'}):
        try:
            Errand(**_errand(**bad))
            check(False, f"a malformed steer value was accepted: {bad}")
        except ValueError:
            pass
    check(Errand(**_errand()).skip_dates == [], "steer fields default empty")


def scenario_the_setting_exists_with_its_default_and_bounds():
    from models.schemas import Settings
    check(Settings().errand_dedicated_trip_mins == 25, "default is 25 minutes")
    for bad in (-1, 121):
        try:
            Settings(errand_dedicated_trip_mins=bad)
            check(False, f"out-of-range penalty accepted: {bad}")
        except ValueError:
            pass
    from services import settings_registry as reg
    owner = reg.owner('errand_dedicated_trip_mins')
    check(owner and owner['page'] == 'errands?tab=errands' and owner['anchor'] == 'errand-settings',
          f"the registry points the setting at the Errands drawer: {owner}")


def scenario_get_errand_by_id_takes_a_uuid_or_a_doc_id():
    _fresh()
    doc_id = storage.add_errand(_errand(id='e-uuid'))
    by_uuid = storage.get_errand_by_id('e-uuid')
    by_doc = storage.get_errand_by_id(doc_id)
    by_doc_str = storage.get_errand_by_id(str(doc_id))
    check(by_uuid and by_uuid['doc_id'] == doc_id, "found by uuid, carrying doc_id")
    check(by_doc and by_doc['id'] == 'e-uuid', "found by integer doc_id")
    check(by_doc_str and by_doc_str['id'] == 'e-uuid', "found by doc_id as a string")
    check(storage.get_errand_by_id('nope') is None, "unknown ids are None, not an error")


def scenario_complete_errand_clears_steer_and_anchors_the_successor_on_the_cycle():
    _fresh()
    anchor = time.mktime(datetime.datetime(2026, 10, 5, 0, 0).timetuple())
    doc_id = storage.add_errand(_errand(id='e-weekly', recurrence_rule='weekly', starts_on=anchor,
                                        skip_dates=['2026-10-13'], pinned_date='2026-10-14',
                                        pinned_start='09:00', once_driver_id='d2'))
    succ = storage.complete_errand(doc_id, now=anchor + 8 * 86400)
    rows = {e['id']: e for e in storage.get_all_errands()}
    done = rows['e-weekly']
    check(done['is_completed'] is True and done['skip_dates'] == [] and done['pinned_date'] is None
          and done['pinned_start'] is None and done['once_driver_id'] is None,
          f"the completed row is done and its one-shot fields are cleared: {done}")
    check(succ is not None and succ != doc_id, "a weekly errand mints a successor with a new doc_id")
    new = next(e for e in rows.values() if e['doc_id'] == succ)
    check(new['id'] != 'e-weekly' and new['is_completed'] is False and new['status'] == 'pending'
          and new['last_scheduled_end'] is None, f"the successor is a fresh pending row: {new}")
    check(abs(new['starts_on'] - (anchor + WEEK)) < 1,
          f"the successor anchors on the completed cycle (anchor + 7 days), got {new['starts_on']} vs {anchor + WEEK}")
    check(new['skip_dates'] == [] and new['pinned_date'] is None and new['once_driver_id'] is None,
          "the successor inherits no steering")
    check(storage.complete_errand(doc_id, now=anchor + 9 * 86400) is None
          and len(storage.get_all_errands()) == 2, "completing twice mints nothing")
    one_off = storage.add_errand(_errand(id='e-once'))
    check(storage.complete_errand(one_off) is None and len(storage.get_all_errands()) == 3,
          "a one-off errand has no successor")


def scenario_forget_errand_placements_removes_rows_and_the_note():
    _fresh()
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e1', '2026-10-27'), _row('e2', '2026-10-27')]}, 'h')
    storage.save_cached_daily_schedule('2026-10-28', {'scheduled_errands': [_row('e1', '2026-10-28')]}, 'h')
    storage.save_errand_placement_notes({'e1': {'reason': 'no_slot', 'text': 'x', 'generation': 1},
                                         'e3': {'reason': 'no_location', 'text': 'y', 'generation': 1}})
    removed = storage.forget_errand_placements('e1')
    check(removed == 2, f"both of e1's rows went, got {removed}")
    rows = storage.get_all_scheduled_errand_rows()
    check(set(rows) == {'e2'} and rows['e2']['why']['kind'] == 'on_the_way',
          f"e2 keeps its whole row: {rows}")
    check(set(storage.get_errand_placement_notes()) == {'e3'}, "e1's note is gone, e3's stays")
    check(storage.get_all_scheduled_errands() == {'e2': '2026-10-27T16:10:00'},
          "the start-only aggregator still works for its old callers")


def scenario_the_schedule_generation_counts_up():
    _fresh()
    check(storage.get_schedule_generation() == 0, "starts at zero")
    check(storage.bump_schedule_generation() == 1 and storage.bump_schedule_generation() == 2
          and storage.get_schedule_generation() == 2, "bumps by one and reads back")


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None   # never solve in a unit test
    return TestClient(main.app), main


def _headers():
    """No token: with no `auth_enforce` setting the guard is in audit mode
    (`services/auth.enforcing()` reads absent as False), so every route
    answers. Kept as a hook so a later enforcing fixture has one place to add
    a parent token."""
    return {}


def scenario_get_errands_carries_placement_or_unplaced_and_the_generation():
    _fresh()
    client, main = _client()
    storage.add_errand(_errand(id='e-sched'))
    storage.add_errand(_errand(id='e-lost'))
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e-sched', '2026-10-27')]}, 'h')
    storage.save_errand_placement_notes({'e-lost': {'reason': 'no_slot', 'text': 'no drive in its window has room for it', 'generation': 4}})
    storage.set_app_state('schedule_generation', 4)
    res = client.get('/api/errands', headers=_headers())
    check(res.status_code == 200, f"GET /api/errands {res.status_code}: {res.text[:200]}")
    rows = {r['id']: r for r in res.json()}
    sched = rows['e-sched']
    check(sched['placement']['why']['text'] == "on Jeff's way to Soccer, +6 min"
          and sched['placement']['driver'] == {'id': 'd1', 'name': 'Jeff'}
          and sched['placement']['start_time'] == '2026-10-27T16:10:00'
          and sched['scheduled_start'] == '2026-10-27T16:10:00' and 'unplaced' not in sched, f"{sched}")
    lost = rows['e-lost']
    check(lost['unplaced']['reason'] == 'no_slot' and 'placement' not in lost, f"{lost}")
    check(all(r['generation'] == 4 for r in rows.values()), "every row carries the generation")


def scenario_put_rejects_a_bad_date_and_a_steer_forgets_placements():
    _fresh()
    client, main = _client()
    doc_id = storage.add_errand(_errand(id='e-steer'))
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e-steer', '2026-10-27')]}, 'h')
    body = dict(storage.get_errand_by_id(doc_id))
    body['pinned_date'] = 'next tuesday'
    res = client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    check(res.status_code == 422, f"a malformed date is refused: {res.status_code}")
    body['pinned_date'] = '2026-10-31'
    res = client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    check(res.status_code == 200, f"{res.status_code} {res.text[:200]}")
    check(storage.get_all_scheduled_errand_rows() == {}, "the stale placement is forgotten")
    check(storage.get_errand_by_id(doc_id)['pinned_date'] == '2026-10-31', "the pin is stored")
    storage.save_cached_daily_schedule('2026-10-31', {'scheduled_errands': [_row('e-steer', '2026-10-31')]}, 'h')
    body = dict(storage.get_errand_by_id(doc_id))
    body['title'] = 'Costco run (big)'
    client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    check(set(storage.get_all_scheduled_errand_rows()) == {'e-steer'}, "a title-only edit keeps the placement")


def scenario_completing_twice_mints_nothing_through_put():
    _fresh()
    client, main = _client()
    anchor = time.mktime(datetime.datetime(2026, 10, 5, 0, 0).timetuple())
    doc_id = storage.add_errand(_errand(id='e-wk', recurrence_rule='weekly', starts_on=anchor, once_driver_id='d2'))
    body = dict(storage.get_errand_by_id(doc_id))
    body['is_completed'] = True
    client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    rows = storage.get_all_errands()
    check(len(rows) == 2, f"one successor: {len(rows)}")
    done = storage.get_errand_by_id(doc_id)
    check(done['is_completed'] and done['once_driver_id'] is None, "completed through complete_errand")
    succ = next(r for r in rows if r['doc_id'] != doc_id)
    check(abs(succ['starts_on'] - (anchor + WEEK)) < 1 and succ['once_driver_id'] is None, f"{succ}")
    body = dict(storage.get_errand_by_id(doc_id))
    client.put(f'/api/errands/{doc_id}', json=body, headers=_headers())
    check(len(storage.get_all_errands()) == 2, "a second completed PUT mints nothing")


def scenario_the_agent_updates_by_uuid_or_doc_id_and_steers():
    _fresh()
    from services import agent_tools_v2 as tools
    doc_id = storage.add_errand(_errand(id='e-agent'))
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e-agent', '2026-10-27')]}, 'h')
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'skip_date': '2026-10-27'})
    check(out.get('status') == 'success', f"by uuid: {out}")
    check(storage.get_errand_by_id(doc_id)['skip_dates'] == ['2026-10-27'], "skip_date appended")
    check(storage.get_all_scheduled_errand_rows() == {}, "a steer through the agent forgets the placement")
    out = tools.handle_update_errand({'errand_id': str(doc_id), 'pinned_date': '2026-10-31',
                                      'pinned_start': '09:00', 'once_driver_id': 'd2'})
    e = storage.get_errand_by_id(doc_id)
    check(out.get('status') == 'success' and e['pinned_date'] == '2026-10-31' and e['pinned_start'] == '09:00'
          and e['once_driver_id'] == 'd2', f"by doc_id string: {out} {e}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'pinned_date': 'friday'})
    check(out.get('status') == 'error' and 'date' in out.get('message', '').lower(), f"a bad date is refused in words: {out}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'clear_steer': True})
    e = storage.get_errand_by_id(doc_id)
    check(e['skip_dates'] == [] and e['pinned_date'] is None and e['pinned_start'] is None and e['once_driver_id'] is None,
          f"clear_steer clears all four: {e}")
    out = tools.handle_update_errand({'errand_id': 'e-agent', 'is_completed': True})
    check(out.get('status') == 'success' and storage.get_errand_by_id(doc_id)['is_completed'], "completion works")
    check(tools.handle_update_errand({'errand_id': 'ghost'}).get('status') == 'error', "unknown id is an error result")


def scenario_skip_date_is_idempotent():
    _fresh()
    from services import agent_tools_v2 as tools
    storage.add_errand(_errand(id='e-twice'))
    tools.handle_update_errand({'errand_id': 'e-twice', 'skip_date': '2026-10-27'})
    tools.handle_update_errand({'errand_id': 'e-twice', 'skip_date': '2026-10-27'})
    check(storage.get_errand_by_id('e-twice')['skip_dates'] == ['2026-10-27'], "appended once")


def scenario_the_agent_reads_the_same_placement_the_page_does():
    _fresh()
    from services import agent_tools_v2 as tools
    storage.add_errand(_errand(id='e-read'))
    storage.save_cached_daily_schedule('2026-10-27', {'scheduled_errands': [_row('e-read', '2026-10-27')]}, 'h')
    storage.set_app_state('schedule_generation', 9)
    out = tools.handle_get_errands({})
    row = next(r for r in out['errands'] if r['id'] == 'e-read')
    check(row['placement']['why']['text'] == "on Jeff's way to Soccer, +6 min" and row['generation'] == 9, f"{row}")
    schema = tools.UpdateErrandTool.model_json_schema()['properties']
    for f in ('skip_date', 'pinned_date', 'pinned_start', 'pinned_end', 'once_driver_id', 'clear_steer'):
        check(f in schema, f"the tool declares {f}")


def scenario_the_setting_round_trips_through_the_api_and_has_a_control():
    _fresh()
    client, main = _client()
    res = client.post('/api/settings', json={'errand_dedicated_trip_mins': 40}, headers=_headers())
    check(res.status_code == 200, f"POST /api/settings {res.status_code}: {res.text[:200]}")
    # harness.py stubs storage.get_settings for the solver tests, so read the table.
    with storage.db_lock:
        stored = (storage.settings_table.all() or [{}])[0]
    check(stored.get('errand_dedicated_trip_mins') == 40, f"stored: {stored.get('errand_dedicated_trip_mins')}")
    res = client.post('/api/settings', json={'errand_dedicated_trip_mins': 500}, headers=_headers())
    check(res.status_code == 422, f"out of bounds refused: {res.status_code}")
    from services import settings_registry as reg
    ui = reg.audit_ui()
    missing = [m for m in ui.get('unreachable', []) if m.get('key') == 'errand_dedicated_trip_mins']
    check(not missing, f"the Errands drawer carries the control: {missing}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand routing api scenarios passed")
