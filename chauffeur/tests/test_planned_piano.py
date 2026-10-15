"""Acceptance: "I want to learn piano" (planned missions spec §9). A program,
then two work stages whose writes come back as one follow-up batch each.
Real registry and runner; models, research and the curator are faked. Task 13.

  1. an interview (who, starting point, minutes, days, budget);
  2. a plan: build "the program", work "find lessons nearby", work "find a
     piano and books";
  3. the program lands as a PROPOSAL for Kate on the Programs page (the
     curator's plan is a person's to approve) and becomes the subject;
  4. lessons: research, then two teacher threads and a drafted message to
     each are queued (the draft refers to its thread by `$ref`) and come back
     as one follow-up stage; approving it opens both threads with drafts;
  5. instrument and books: research, then a "Piano" list, its items by list
     id, and a note to send yourself, as one follow-up stage;
  6. the finish hands the note over.

Run from chauffeur/:  python tests/test_planned_piano.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations, web, threads
from test_planned_missions import _fresh, _plan_of
from test_mission_subject import _plan, _step, _steps, _mission
from test_subjects import MOM

DMS = []


def _stage(mid, sid):
    return next(s for s in _plan_of(mid)['stages'] if s['id'] == sid)


def _approve(mid, sid):
    st = _stage(mid, sid)
    res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:{sid}:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"stage {sid} approved: {res}")
    return _stage(mid, sid)


STAGES = [
    {'id': 's1', 'kind': 'build', 'title': 'The program', 'why': 'a weekly plan', 'makes': ["Kate's piano program"]},
    {'id': 's2', 'kind': 'work', 'title': 'Find lessons nearby', 'why': 'a teacher', 'goal': 'two teachers within 15 minutes', 'step_budget': 6,
     'makes': ['two teacher threads with drafts']},
    {'id': 's3', 'kind': 'work', 'title': 'Find a piano and books', 'why': 'something to play', 'goal': 'a used keyboard under $300 and two books',
     'step_budget': 5, 'makes': ['a Piano list', 'a note']},
]


def scenario_learning_piano():
    _fresh(step_cap=200)
    DMS.clear()
    missions._post = lambda dm, argyle, body, card=None: DMS.append(card) or {'id': f'm{len(DMS)}'}
    from services import programs_curate
    programs_curate.curate = lambda *a, **k: {'phases': [], 'source': {'origin': 'none', 'reason': 'test', 'plan_name': '', 'url': ''}}
    web.research = lambda question, read_pages=None, api_key=None: {'status': 'success', 'answer': f'Found: {question}', 'facts': [], 'sources': []}
    threads.draft_message = lambda thread_id, intent=None, **k: {'status': 'ok', 'subject': 'Piano lessons', 'body': 'Hello, lessons for Kate?'}

    mid = _mission(created_by='mom')
    storage.update_mission(mid, {'goal': 'I want Kate to learn piano'})
    _plan({'action': 'interview', 'questions': [
        {'key': 'who', 'ask': 'Who is learning?', 'kind': 'text'}, {'key': 'start', 'ask': 'Where are they starting?', 'kind': 'text'},
        {'key': 'minutes', 'ask': 'Minutes a session?', 'kind': 'number'}, {'key': 'days', 'ask': 'Sessions a week?', 'kind': 'number'},
        {'key': 'budget', 'ask': 'Budget for an instrument?', 'kind': 'number'}]})
    _step(mid)
    from services import planned
    planned.answer_plan(mid, {'who': 'Kate', 'start': 'never played', 'minutes': 20, 'days': 3, 'budget': 300}, dict(MOM))
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))

    _plan({'action': 'stage', 'stage_id': 's1', 'rows': [
        {'id': 'r1', 'tool': 'propose_program', 'args': {'title': 'Learn piano', 'for_member_name': 'Kate', 'sessions_per_week': 3, 'minutes': 20,
                                                         'starting_point': 'never played'}, 'summary': "Propose Kate's piano program"}]})
    _step(mid)
    st = _approve(mid, 's1')
    pid = st['rows'][0]['result']['created'][0]['id']
    prog = storage.get_program(pid)
    check(prog['state'] == 'proposed' and prog['member_id'] == 'kid', f"a proposal for Kate on the Programs page: {prog}")
    check(missions.subject_of(storage.get_mission(mid))[:2] == ('program', pid), "the program is the subject")

    # Lessons: the work stage starts itself (Projects Decision 5).
    _step(mid)
    check(_stage(mid, 's2')['state'] == 'running', "lessons start themselves")
    _plan({'action': 'research', 'question': 'piano teachers near home for a beginner child'},
          {'action': 'propose', 'tool': 'create_thread', 'row_id': 't1', 'args': {'title': 'Piano teacher: Ms Rivera', 'kind': 'vendor'},
           'summary': 'A thread for Ms Rivera', 'why': 'nearby'},
          {'action': 'propose', 'tool': 'draft_thread_message', 'row_id': 'd1', 'needs': ['t1'],
           'args': {'thread_id': {'$ref': 't1', 'kind': 'thread'}, 'intent': 'ask about Tuesday lessons for Kate'},
           'summary': 'Draft to Ms Rivera', 'why': 'ask'},
          {'action': 'propose', 'tool': 'create_thread', 'row_id': 't2', 'args': {'title': 'Piano teacher: Mr Okafor', 'kind': 'vendor'},
           'summary': 'A thread for Mr Okafor', 'why': 'nearby'},
          {'action': 'propose', 'tool': 'draft_thread_message', 'row_id': 'd2', 'needs': ['t2'],
           'args': {'thread_id': {'$ref': 't2', 'kind': 'thread'}, 'intent': 'ask about Thursday lessons for Kate'},
           'summary': 'Draft to Mr Okafor', 'why': 'ask'},
          {'action': 'stage_done', 'stage_id': 's2', 'summary': 'Two teachers nearby', 'found': {'teachers': ['Ms Rivera', 'Mr Okafor']}})
    for _ in range(6):
        _step(mid)
    follow = next(s for s in _plan_of(mid)['stages'] if s.get('parent') == 's2')
    check([r['id'] for r in follow['rows']] == ['t1', 'd1', 't2', 'd2'] and follow['state'] == 'proposed',
          f"one follow-up stage holding the four writes, by the planner's own row ids: {follow}")
    st = _approve(mid, follow['id'])
    check(st['state'] == 'done', f"the follow-up ran: {[(r['id'], r['state'], (r.get('result') or {}).get('message')) for r in st['rows']]}")
    titles = {t['title'] for t in storage.get_threads()}
    check({'Piano teacher: Ms Rivera', 'Piano teacher: Mr Okafor'} <= titles, "both teacher threads")

    # Instrument and books.
    _step(mid)
    check(_stage(mid, 's3')['state'] == 'running', "the instrument search starts itself")
    _plan({'action': 'research', 'question': 'used digital piano under $300 and beginner books'},
          {'action': 'propose', 'tool': 'create_list', 'row_id': 'l1', 'args': {'name': 'Piano'}, 'summary': 'A Piano list', 'why': 'shopping'},
          {'action': 'propose', 'tool': 'add_shopping_items', 'row_id': 'i1', 'needs': ['l1'],
           'args': {'list_id': {'$ref': 'l1', 'kind': 'list'}, 'items': '61-key keyboard, Faber Piano Adventures 1, music stand'},
           'summary': 'Keyboard and books', 'why': 'shopping'},
          {'action': 'propose', 'tool': 'draft_message', 'row_id': 'n1', 'args': {'to': 'You', 'words': 'Check Marketplace for a Yamaha P-45 under $300.'},
           'summary': 'A note to yourself', 'why': 'used'},
          {'action': 'stage_done', 'stage_id': 's3', 'summary': 'A keyboard and two books', 'found': {'keyboard': 'Yamaha P-45, used'}})
    for _ in range(5):
        _step(mid)
    follow = next(s for s in _plan_of(mid)['stages'] if s.get('parent') == 's3')
    _approve(mid, follow['id'])
    piano = next(l for l in storage.get_shopping_lists() if l['name'] == 'Piano')
    items = {i['name'].lower() for i in storage.get_shopping_items(piano['id'])}
    check({'61-key keyboard', 'music stand'} <= items, f"the Piano list by id: {items}")

    _plan({'action': 'finish', 'summary': "Kate's piano plan is ready.", 'next_action': 'approve the program and send the two drafts'})
    _step(mid)
    check(_plan_of(mid)['state'] == 'done', "done")
    done = [c for c in DMS if c and c.get('kind') == 'mission_done']
    check(done and any('Yamaha' in d['words'] for d in done[-1]['drafts']), f"the note is handed over: {done and done[-1]}")


def scenario_queued_rows_keep_the_order_rules():
    """A queued write keeps the planner's row id and prerequisites; a reference
    must name an earlier row; a row id is used once; a row with no id of its
    own gets one that cannot collide with the planner's."""
    from test_planned_work import _work_proposed, _go
    mid, _ = _work_proposed()
    _go(mid)
    _plan({'action': 'propose', 'tool': 'create_thread', 'row_id': 'r2', 'args': {'title': 'Teacher A', 'kind': 'vendor'},
           'summary': 'Teacher A', 'why': 'x'},
          {'action': 'propose', 'tool': 'create_list', 'args': {'name': 'Piano'}, 'summary': 'A Piano list', 'why': 'x'},
          {'action': 'propose', 'tool': 'draft_thread_message', 'row_id': 'd1', 'needs': ['t9'],
           'args': {'thread_id': {'$ref': 't9', 'kind': 'thread'}, 'intent': 'hello'}, 'summary': 'Draft', 'why': 'x'},
          {'action': 'propose', 'tool': 'create_thread', 'row_id': 'r2', 'args': {'title': 'Teacher B', 'kind': 'vendor'},
           'summary': 'Teacher B', 'why': 'x'})
    for _ in range(4):
        _step(mid)
    follow = next(s for s in _plan_of(mid)['stages'] if s.get('parent') == 's2')
    ids = [r['id'] for r in follow['rows']]
    check([r['tool'] for r in follow['rows']] == ['create_thread', 'create_list'] and ids[0] == 'r2' and len(set(ids)) == 2,
          f"the planner's id kept, a fresh one that does not collide: {follow['rows']}")
    check(len(_steps(mid, 'refused')) == 2, f"a dangling reference and a reused id are refused: {_steps(mid, 'refused')}")


def scenario_a_build_stage_reference_must_name_an_earlier_row():
    from test_planned_missions import _approved
    _fresh()
    mid = _approved()
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': [
        {'id': 'r1', 'tool': 'add_occasion_guests', 'args': {'occasion_id': {'$ref': 'r2', 'kind': 'occasion'}, 'who': 'The Wilsons', 'headcount': 4},
         'summary': 'Add the Wilsons'},
        {'id': 'r2', 'tool': 'add_occasion', 'args': {'title': "Kate's 10th birthday", 'anchor_date': '2027-02-14', 'kind': 'birthday'},
         'summary': 'Make the party'}]})
    _step(mid)
    check(_plan_of(mid)['stages'][0]['state'] == 'pending' and _steps(mid, 'refused'),
          "a reference to a later row refuses the stage before anything is proposed")


SCENARIOS = [scenario_learning_piano, scenario_queued_rows_keep_the_order_rules, scenario_a_build_stage_reference_must_name_an_earlier_row]

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
