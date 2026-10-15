"""Each contracted tool keeps its contract (planned missions spec §3; Task 6,
block B). Tasks 4 and 5 made the occasion tools, create_trip and create_list
conform; this pins the rest of the table:

  * trips: `add_trip_poi(trip_id, title, location, category, meal_type,
    duration_mins, start_time=None, idem)` — an unscheduled stop when no time is
    given, the dining kind as `category: 'food'`; `add_trip_accommodation`
    declared and registered with `trip_id`; both idempotent and saying what
    they created;
  * lists: `add_shopping_items(items, list_id=…)` adds to that list by id;
  * threads: `create_thread(..., idem)` creates once and says so;
    `add_thread_note` and `draft_thread_message` take a `thread_id`;
  * household tasks: `add_household_task(..., idem)` creates once;
  * errands: `add_errand(..., idem)` creates once and says so;
  * programs: `propose_program` says which program it proposed.

Run from chauffeur/:  python tests/test_stage_contract_tools.py
"""
import datetime

from harness import check, mk_trip, MONDAY  # noqa: F401
from services import storage
from services import agent_tools_v2 as tools
from test_subjects import _reset, _seed, MOM

ACTOR = dict(MOM)


def _fresh():
    _reset()
    for t in (storage.errands_table, storage.household_tasks_table):
        t.truncate()
    _seed()
    trip = mk_trip(days=3, location='Orlando')
    storage.set_trip_metadata(trip.event_id, trip.model_dump())
    return trip.event_id


def _twice(tool, args):
    a = tools.execute_tool(tool, dict(args), actor=ACTOR)
    b = tools.execute_tool(tool, dict(args), actor=ACTOR)
    return a, b


def scenario_trip_stops_and_hotels_by_trip_id():
    tid = _fresh()
    a, b = _twice('add_trip_poi', {'trip_id': tid, 'title': "Be Our Guest", 'location': 'Magic Kingdom', 'category': 'food',
                                   'meal_type': 'dinner', 'duration_mins': 90, 'idem': 'p1'})
    check(a.get('status') == 'success' and a.get('created') and a['created'][0]['kind'] == 'poi', f"made: {a}")
    check(b.get('created') == a['created'], "a repeat returns the same stop")
    pois = storage.get_trip_metadata(tid)['pois']
    mine = [p for p in pois if p['name'] == 'Be Our Guest']
    check(len(mine) == 1 and mine[0]['category'] == 'food' and mine[0].get('meal_type') == 'dinner' and not mine[0].get('is_scheduled'),
          f"one unscheduled dining stop: {mine}")
    check('add_trip_accommodation' in {t['name'] for t in tools.get_available_tools()} and 'add_trip_accommodation' in tools.TOOL_SCHEMAS,
          "the hotel tool is declared with a schema")
    from services import trip_planner, trip_validation
    orig = (trip_planner.enrich_poi_data, trip_validation.vet_accommodation)
    trip_planner.enrich_poi_data = lambda *a, **k: None
    trip_validation.vet_accommodation = lambda *a, **k: None
    try:
        a, b = _twice('add_trip_accommodation', {'trip_id': tid, 'name': 'Pop Century', 'location': 'Orlando',
                                                 'check_in_date': MONDAY.isoformat(),
                                                 'check_out_date': (MONDAY + datetime.timedelta(days=3)).isoformat(), 'idem': 'a1'})
    finally:
        trip_planner.enrich_poi_data, trip_validation.vet_accommodation = orig
    check(a.get('status') == 'success' and a.get('created') and a['created'][0]['kind'] == 'accommodation', f"hotel: {a}")
    check(b.get('created') == a['created'] and
          len([x for x in storage.get_trip_metadata(tid)['accommodations'] if x['name'] == 'Pop Century']) == 1, "once")


def scenario_list_items_by_list_id():
    _fresh()
    storage.add_shopping_list({'id': 'l9', 'name': 'Piano'})
    out = tools.execute_tool('add_shopping_items', {'items': 'beginner piano book, music stand', 'list_id': 'l9'}, actor=ACTOR)
    check(out.get('status') == 'success', f"{out}")
    names = {i['name'].lower() for i in storage.get_shopping_items('l9')}
    check({'beginner piano book', 'music stand'} <= names, f"on the list by id: {names}")
    check(not {i['name'].lower() for i in storage.get_shopping_items('l1')} & {'beginner piano book', 'music stand'},
          "never the default list")


def scenario_threads_by_id():
    _fresh()
    a, b = _twice('create_thread', {'title': 'Piano teacher: Ms Rivera', 'kind': 'vendor', 'idem': 't1'})
    check(a.get('status') == 'success' and a.get('created') and a['created'][0]['kind'] == 'thread', f"made: {a}")
    check(b.get('created') == a['created'], "a repeat returns the same thread")
    tid = a['created'][0]['id']
    out = tools.execute_tool('add_thread_note', {'thread_id': tid, 'text': 'Left a voicemail'}, actor=ACTOR)
    check(out.get('status') == 'success' and any('voicemail' in (h.get('text') or '') for h in storage.get_thread(tid)['history']),
          f"a note by thread id: {out}")
    from services import threads
    orig = threads.draft_message
    threads.draft_message = lambda thread_id, intent=None, **k: {'status': 'ok', 'subject': 'Lessons', 'body': f'for {thread_id}'}
    try:
        out = tools.execute_tool('draft_thread_message', {'thread_id': tid, 'intent': 'ask about Tuesday lessons'}, actor=ACTOR)
    finally:
        threads.draft_message = orig
    check(out.get('status') in ('success', 'ok') and tid in repr(out), f"a draft by thread id: {out}")


def scenario_household_tasks_and_errands_once():
    _fresh()
    a, b = _twice('add_household_task', {'title': 'Renew passports', 'idem': 'h1'})
    check(a.get('created') and a['created'][0]['kind'] == 'task' and b.get('created') == a['created'], f"task once: {a} {b}")
    check(len([t for t in storage.get_household_tasks(include_done=True) if t['title'] == 'Renew passports']) == 1, "one row")
    a, b = _twice('add_errand', {'title': 'Pick up the cake', 'location': 'Publix', 'duration_mins': 15, 'idem': 'e1'})
    check(a.get('status') == 'success' and a.get('created') and a['created'][0]['kind'] == 'errand', f"errand: {a}")
    check(b.get('created') == a['created'] and len([e for e in storage.get_all_errands() if e['title'] == 'Pick up the cake']) == 1, "once")


def scenario_propose_program_says_which_program():
    _fresh()
    from services import programs_curate
    orig = programs_curate.curate
    programs_curate.curate = lambda *a, **k: {'phases': [], 'source': {'origin': 'none', 'reason': 'test', 'plan_name': '', 'url': ''}}
    try:
        out = tools.execute_tool('propose_program', {'title': 'Learn piano', 'for_member_name': 'Kate', 'sessions_per_week': 3, 'minutes': 20},
                                 actor=ACTOR)
    finally:
        programs_curate.curate = orig
    check(out.get('created') and out['created'][0]['kind'] == 'program', f"names the proposed program: {out}")
    row = storage.get_program(out['created'][0]['id'])
    check(row and row['state'] == 'proposed' and row['member_id'] == 'kid', f"a proposal for Kate, as today: {row}")


SCENARIOS = [
    scenario_trip_stops_and_hotels_by_trip_id,
    scenario_list_items_by_list_id,
    scenario_threads_by_id,
    scenario_household_tasks_and_errands_once,
    scenario_propose_program_says_which_program,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
