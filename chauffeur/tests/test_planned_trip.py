"""Acceptance: "help me plan our Disney trip in January" (planned missions spec
§9). Real registry, real runner, the real CP-SAT itinerary scheduler; only
models and the browser are faked. Task 13.

  1. an interview (dates, travellers, budget, must-dos, dining style);
  2. a plan: build "the trip" (create it, the hotel, attractions and dining
     stops, schedule them) then work "dining reservations";
  3. the build stage creates a NEW trip (a same-named trip already on file is
     untouched), its hotel and four stops by `$ref`, and schedules them on the
     server: the windows are STORED; the trip becomes the subject;
  4. the work stage runs the browse; the site wants a sign-in, so it hands
     off — and the planner had each dining stop and its window in front of it
     (ABOUT, dining facet) to name in the hand-off;
  5. the finish.

Run from chauffeur/:  python tests/test_planned_trip.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations
from test_planned_missions import _fresh, _plan_of
from test_mission_subject import _plan, _step, _steps, _mission, PROMPTS
from test_subjects import MOM


def _stage(mid, sid):
    return next(s for s in _plan_of(mid)['stages'] if s['id'] == sid)


def _approve(mid, sid):
    st = _stage(mid, sid)
    res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:{sid}:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"stage {sid} approved: {res}")
    return _stage(mid, sid)


STAGES = [
    {'id': 's1', 'kind': 'build', 'title': 'The trip', 'why': 'everything hangs off it',
     'makes': ['the trip', 'the hotel', 'two parks', 'two dinners', 'a schedule']},
    {'id': 's2', 'kind': 'work', 'title': 'Dining reservations', 'why': 'they go fast', 'goal': 'reserve the two dinners on disneyworld.disney.go.com',
     'step_budget': 3, 'makes': ['reservations or a hand-off with the times']},
]


def scenario_the_whole_trip():
    _fresh(step_cap=200)
    before = {m['event_id'] for m in storage.get_all_trip_metadata()}
    old_pois = len(storage.get_trip_metadata('ev_disney')['pois'])
    mid = _mission(created_by='mom')
    storage.update_mission(mid, {'goal': 'help me plan our Disney trip in January'})

    _plan({'action': 'interview', 'questions': [
        {'key': 'start', 'ask': 'First day?', 'kind': 'date'}, {'key': 'end', 'ask': 'Last day?', 'kind': 'date'},
        {'key': 'travellers', 'ask': 'How many of you?', 'kind': 'number'}, {'key': 'budget', 'ask': 'Budget?', 'kind': 'number'},
        {'key': 'dining', 'ask': 'Dining style?', 'kind': 'text'}]})
    _step(mid)
    from services import planned
    planned.answer_plan(mid, {'start': '2028-01-10', 'end': '2028-01-13', 'travellers': 4, 'budget': 4000, 'dining': 'character meals'}, dict(MOM))

    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))

    trip = {'$ref': 'r1', 'kind': 'trip'}
    poi = lambda rid, name, cat, meal=None: {'id': rid, 'tool': 'add_trip_poi', 'needs': ['r1'], 'summary': name,
                                              'args': {'trip_id': trip, 'title': name, 'location': f'{name}, Orlando, FL', 'category': cat,
                                                       'duration_mins': 90 if cat == 'food' else 360, **({'meal_type': meal} if meal else {})}}
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': [
        {'id': 'r1', 'tool': 'create_trip', 'args': {'title': 'Disney World', 'location': 'Orlando, FL', 'start_date': '2028-01-10',
                                                     'end_date': '2028-01-13', 'travelers': 4}, 'summary': 'The trip'},
        {'id': 'r2', 'tool': 'add_trip_accommodation', 'needs': ['r1'], 'summary': 'Pop Century',
         'args': {'trip_id': trip, 'name': 'Pop Century', 'location': 'Orlando, FL', 'check_in_date': '2028-01-10', 'check_out_date': '2028-01-13'}},
        poi('r3', 'Magic Kingdom', 'sightseeing'), poi('r4', 'EPCOT', 'sightseeing'),
        poi('r5', "Chef Mickey's", 'food', 'breakfast'), poi('r6', 'Be Our Guest', 'food', 'dinner'),
        {'id': 'r7', 'tool': 'schedule_trip_itinerary', 'args': {'trip_id': trip}, 'summary': 'Schedule the stops',
         'needs': ['r3', 'r4', 'r5', 'r6']},
    ]})
    _step(mid)
    check({m['event_id'] for m in storage.get_all_trip_metadata()} == before, "proposing writes nothing")
    st = _approve(mid, 's1')
    check(st['state'] == 'done', f"stage 1: {[(r['id'], r['state'], (r.get('result') or {}).get('message')) for r in st['rows']]}")
    made = {m['event_id'] for m in storage.get_all_trip_metadata()} - before
    check(len(made) == 1, f"one new trip: {made}")
    tid = made.pop()
    meta = storage.get_trip_metadata(tid)
    check([a['name'] for a in meta['accommodations']] == ['Pop Century'], "the hotel")
    names = {p['name']: p for p in meta['pois']}
    check(set(names) == {'Magic Kingdom', 'EPCOT', "Chef Mickey's", 'Be Our Guest'}, f"four stops: {sorted(names)}")
    for n in ("Chef Mickey's", 'Be Our Guest'):
        check(names[n]['category'] == 'food' and names[n].get('is_scheduled') and names[n].get('scheduled_start'),
              f"{n} is a dining stop with a STORED window from the server scheduler: {names[n]}")
    check(len(storage.get_trip_metadata('ev_disney')['pois']) == old_pois, "the trip of the same name already on file is untouched")
    check(missions.subject_of(storage.get_mission(mid))[:2] == ('trip', tid), "the trip is the subject")

    _step(mid)                      # the engine proposes the work stage itself
    check(_stage(mid, 's2')['state'] == 'proposed', "the dining stage waits for Go")
    _approve(mid, 's2')
    calls = []
    missions._browse = lambda **kw: calls.append(kw) or {
        'outcome': 'blocked', 'text': 'The dining page needs a My Disney Experience sign-in.', 'learned': {},
        'stopped_at': 'https://disneyworld.disney.go.com/dining/', 'wanted_fields': [], 'turns': 4, 'tokens_in': 1, 'tokens_out': 1,
        'seconds': 1, 'screenshots': [], 'filled': {}}
    _plan({'action': 'browse', 'goal': 'reserve the two dinners', 'site': 'disneyworld.disney.go.com'},
          {'action': 'tool', 'tool': 'find_in_chauffeur', 'args': {'query': 'Disney World', 'kind': 'trip', 'facet': 'dining'}},
          {'action': 'stage_done', 'stage_id': 's2', 'summary': 'Disney needs your sign-in to book; here are the times.',
           'found': {'handoff': 'https://disneyworld.disney.go.com/dining/'}})
    _step(mid)
    check(calls and calls[0]['site'] == 'disneyworld.disney.go.com', "the browse ran")
    prompt = PROMPTS[-1]['system'] + PROMPTS[-1]['user']
    check("Chef Mickey's" in prompt and 'Be Our Guest' in prompt and 'breakfast' in prompt,
          "the planner had the dining stops in front of it (ABOUT for the bound trip)")
    _step(mid)
    _step(mid)
    st = _stage(mid, 's2')
    check(st['state'] == 'done' and st['found'].get('handoff', '').startswith('https://disneyworld'), f"handed off: {st}")

    _plan({'action': 'finish', 'summary': 'The trip is planned; book the two dinners with your sign-in.', 'next_action': 'book the dinners'})
    _step(mid)
    check(_plan_of(mid)['state'] == 'done', "done")


SCENARIOS = [scenario_the_whole_trip]

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
