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
    check(owner and owner['page'] == 'errands' and owner['anchor'] == 'errand-settings',
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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand routing api scenarios passed")
