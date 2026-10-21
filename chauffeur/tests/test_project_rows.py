"""projects.rows: one exhaustive row table for a project's detail (spec
2026-10-20-projects-one-list §1). Run from chauffeur/:
python tests/test_project_rows.py"""
import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness import check  # noqa: F401
from services import storage, missions, threads, auth, programs
from test_front_door_chat import _fresh
from test_subjects import MOM, DAD, AUNT, KID


def _p():
    from services import projects
    return projects


def _bath(owner='mom', audience='household'):
    return _p().create({'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'tiled',
                        'owner_member_id': owner, 'audience': audience}, dict(MOM))['project']


def _rows(pid, who=MOM):
    return _p().rows(storage.get_project(pid), dict(who))


def _by(rows, kind, rid):
    return next(r for r in rows if r['kind'] == kind and r['id'] == rid)


def _step(pid, title, owner='mom', **fields):
    return _p().add_step(pid, {'title': title, 'owner': owner, **fields}, dict(MOM))['step']


def scenario_person_steps_by_state():
    _fresh()
    p = _bath()
    a = _step(p['id'], 'Demo the old tile')
    b = _step(p['id'], 'Tile the floor', owner='dad', needs=[a['id']], due_date='2030-01-05')
    rows = _rows(p['id'])
    ra, rb = _by(rows, 'step', a['id']), _by(rows, 'step', b['id'])
    check(ra['box'] == 'open' and ra['group'] == 'later' and ra['when'] is None and ra['moment'] == {'step_id': a['id']},
          f"an undated open step is Later: {ra}")
    check(rb['box'] == 'not_yet' and rb['reason'] == 'waiting on Demo the old tile' and rb['group'] == 'later',
          f"a step with unmet needs is not yet, naming the need: {rb}")
    _p().set_step_state(p['id'], a['id'], 'done', dict(MOM))
    rows = _rows(p['id'])
    ra, rb = _by(rows, 'step', a['id']), _by(rows, 'step', b['id'])
    check(ra['box'] == 'done' and ra['group'] == 'logbook', f"a done step sinks to the Logbook: {ra}")
    check(rb['box'] == 'open' and rb['when'] == {'date': '2030-01-05', 'time': ''} and rb['group'] == 'next'
          and rb['subtitle'] == 'Dad · due Jan 5', f"a released dated step is Next with its date: {rb}")
    _p().set_step_state(p['id'], b['id'], 'skipped', dict(MOM))
    check(_by(_rows(p['id']), 'step', b['id'])['reason'] == 'skipped', "a skipped step says so in the Logbook")


def scenario_step_due_today_is_now():
    _fresh()
    p = _bath()
    s = _step(p['id'], 'Call the plumber', due_date=datetime.date.today().isoformat())
    r = _by(_rows(p['id']), 'step', s['id'])
    check(r['group'] == 'now' and r['box'] == 'open', f"a step due today is Now: {r}")


def scenario_step_on_the_calendar_uses_its_hold():
    _fresh()
    p = _bath()
    s = _step(p['id'], 'Tile the floor', owner='dad')
    _p().confirm_hold(p['id'], s['id'], {'date': '2030-01-05', 'start': '08:00', 'end': '09:00'}, dict(MOM))
    r = _by(_rows(p['id']), 'step', s['id'])
    check(r['when'] == {'date': '2030-01-05', 'time': '08:00'} and 'on the calendar' in r['subtitle'],
          f"a held step's when is its window: {r}")


def scenario_argyle_steps_by_state():
    _fresh()
    p = _bath()
    todo = _step(p['id'], 'Find tile', owner='argyle', goal='find ivory matte tile')
    rows = _rows(p['id'])
    r = _by(rows, 'step', todo['id'])
    check(not [x for x in rows if x['kind'] == 'argyle'], f"a step's mission has no second row: {rows}")
    # missions are on in _fresh(); advance launched it, so it is doing.
    check(r['box'] == 'argyle' and r['when'] == 'running' and r['group'] == 'next'
          and r['title'] == 'Argyle is working on find ivory matte tile', f"a running Argyle step: {r}")
    mid = storage.get_project(p['id'])['steps'][0]['mission_id']
    # As the mission asks (missions._ask): it waits on a person with a question ask, then the step learns the question.
    storage.update_mission(mid, {'status': 'waiting_user'})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Matte or gloss?'}})
    _p().on_question(mid, 'Matte or gloss?')
    r = _by(_rows(p['id']), 'step', todo['id'])
    check(r['box'] == 'asking' and r['group'] == 'now' and r['title'] == 'Argyle needs you: Matte or gloss?'
          and [a['verb'] for a in r['actions']] == ['answer'] and r['subtitle'] == 'Argyle asks · find ivory matte tile',
          f"an asking Argyle step carries its projected Answer (the page labels it Answer): {r}")
    _p().on_stage_done(mid, None, {'tiles': 'Ivory matte'})
    r = _by(_rows(p['id']), 'step', todo['id'])
    check(r['box'] == 'done' and r['group'] == 'logbook' and r['title'] == 'tiles: Ivory matte', f"a done Argyle step shows its found line: {r}")


def scenario_argyle_step_waiting_on_a_need_or_switched_off():
    _fresh(missions_on=False)
    p = _bath()
    first = _step(p['id'], 'Pick a colour')
    off = _step(p['id'], 'Find tile', owner='argyle', goal='find tile')
    r = _by(_rows(p['id']), 'step', off['id'])
    check(r['box'] == 'not_yet' and r['reason'] == "Argyle's work is switched off" and r['group'] == 'later', f"missions off: {r}")
    _fresh()
    p = _bath()
    first = _step(p['id'], 'Pick a colour')
    gated = _step(p['id'], 'Find tile', owner='argyle', goal='find tile', needs=[first['id']])
    r = _by(_rows(p['id']), 'step', gated['id'])
    check(r['box'] == 'not_yet' and r['reason'] == 'waits for Pick a colour' and r['title'] == 'Argyle will find tile', f"gated Argyle step: {r}")


def scenario_step_with_gone_mission():
    _fresh()
    p = _bath()
    s = _step(p['id'], 'Find tile', owner='argyle', goal='find tile')
    mid = storage.get_project(p['id'])['steps'][0]['mission_id']
    from services import access
    with patch.object(access, 'gone', lambda kind, row, rid=None: kind == 'mission' and (row or {}).get('id') == mid):
        r = _by(_rows(p['id']), 'step', s['id'])
    check(r['box'] == 'not_yet' and r['reason'] == "Argyle's work is gone", f"a step whose mission is gone: {r}")


def scenario_conversation_rows():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', goal='tile by May', created_by='mom', project_id=p['id'],
                         counterparty_name='Ace Tile', next_action='Call Ace back', next_action_at='2030-02-01')
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['title'] == 'Call Ace back' and r['box'] == 'open' and r['when'] == {'date': '2030-02-01', 'time': ''}
          and r['group'] == 'next' and r['subtitle'] == 'Ace Tile · conversation'
          and r['moment'] == {'thread_id': tid, 'rev': 0} and r['sheet'] == {'kind': 'thread', 'id': tid}, f"a conversation row: {r}")
    threads.advance(tid, '', None, who='mom')
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['title'] == 'Tiler' and r['box'] == 'not_yet' and r['reason'] == 'set a next step' and r['group'] == 'later', f"no next step: {r}")
    threads.advance(tid, 'Call Ace back', '2020-01-01', who='mom')
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['group'] == 'now' and r['box'] == 'open', f"an overdue next step is Now: {r}")
    threads.close(tid, 'done', who='mom')
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['box'] == 'done' and r['group'] == 'logbook', f"a done thread is in the Logbook: {r}")


def scenario_bad_next_action_date():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
    storage.update_thread(tid, {'next_action_at': 'next tuesday'})
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['box'] == 'open' and r['when'] == {'date': datetime.date.today().isoformat(), 'time': ''} and r['group'] == 'now',
          f"a malformed date reads as today: {r}")


def scenario_thread_waiting_on_them():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], counterparty_name='Ace')
    storage.update_thread(tid, {'state': 'waiting'})
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['title'] == 'Waiting on Ace' and r['box'] == 'not_yet' and r['group'] == 'next', f"waiting on them: {r}")


def scenario_mission_rows_and_precedence():
    _fresh()
    p = _bath()
    mid = missions.launch('find three tilers', created_by='mom', project_id=p['id'])['mission_id']
    r = _by(_rows(p['id']), 'argyle', mid)
    check(r['box'] == 'argyle' and r['when'] == 'running' and r['group'] == 'next' and r['moment'] == {'mission_id': mid}, f"a running mission: {r}")
    storage.update_mission(mid, {'status': 'waiting_user'})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Which day suits the tiler?'}})
    r = _by(_rows(p['id']), 'argyle', mid)
    check(r['box'] == 'asking' and r['group'] == 'now' and r['title'] == 'Which day suits the tiler?'
          and any(a['verb'] == 'answer' for a in r['actions']) and r['subtitle'].startswith('Argyle asks · '),
          f"an asking mission carries its buttons: {r}")
    storage.update_mission(mid, {'status': 'done'})
    with patch.object(missions, 'verify_open', lambda row: True):
        r = _by(_rows(p['id']), 'argyle', mid)
    check(r['group'] == 'now' and r['box'] == 'asking', f"a terminal mission with an open verification is Now, not Logbook: {r}")
    r = _by(_rows(p['id']), 'argyle', mid)
    check(r['box'] == 'done' and r['group'] == 'logbook', f"a closed mission: {r}")


def scenario_folded_mission_asks_through_its_thread():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
    mid = missions.launch('draft to the tiler', created_by='mom', project_id=p['id'],
                          origin_kind='thread', origin_ref=tid)['mission_id']
    storage.update_mission(mid, {'status': 'waiting_user'})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Send it?'}})
    with patch('services.projects.THREAD_SHEET_HISTORY', True):
        rows = _rows(p['id'])
    check(not any(r['kind'] == 'argyle' and r['id'] == mid for r in rows), "a folded mission has no row of its own")
    r = _by(rows, 'conversation', tid)
    check(r['box'] == 'asking' and r['group'] == 'now' and r['title'] == 'Send it?', f"its ask rides on the thread row: {r}")


def scenario_program_rows():
    _fresh()
    p = _bath()
    from library_run_fixture import add_run
    add_run({'id': 'run1', 'member_id': 'mom', 'title': 'Strength basics', 'state': 'active',
             'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
             'source': {'origin': 'none', 'reason': 'test'},
             'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}})
    _p().adopt('program', 'run1', None, project_id=p['id'])
    today = datetime.date.today()
    win = [{'program_id': 'run1', 'date': today.isoformat(), 'time_start': '18:00', 'lesson_id': 'l1', 'variant_label': 'A',
            'unit_title': 'Push-ups', 'logged': False},
           {'program_id': 'run1', 'date': (today + datetime.timedelta(days=2)).isoformat(), 'time_start': '18:00',
            'lesson_id': 'l1', 'variant_label': 'B', 'unit_title': 'Push-ups', 'logged': False}]
    with patch.object(programs, 'practice_windows', lambda *a, **k: win):
        rows = _rows(p['id'])
    prog = [r for r in rows if r['kind'] == 'program']
    check(len(prog) == 2, f"one row per window: {prog}")
    t, f = prog
    check(t['title'] == 'Push-ups, A' and t['box'] == 'open' and t['group'] == 'now'
          and t['moment'] == {'run_id': 'run1', 'window_date': today.isoformat(), 'slot_rank': 0, 'lesson_id': 'l1', 'variant_label': 'A'},
          f"today's window is open and Now: {t}")
    check(f['box'] == 'not_yet' and f['reason'].startswith('box opens ') and f['group'] == 'next', f"a future window is not yet: {f}")


def scenario_two_windows_one_day():
    _fresh()
    p = _bath()
    from library_run_fixture import add_run
    add_run({'id': 'run1', 'member_id': 'mom', 'title': 'Strength basics', 'state': 'active',
             'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
             'source': {'origin': 'none', 'reason': 'test'},
             'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}})
    _p().adopt('program', 'run1', None, project_id=p['id'])
    today = datetime.date.today().isoformat()
    win = [{'program_id': 'run1', 'date': today, 'time_start': '08:00', 'lesson_id': 'l1', 'variant_label': 'A', 'unit_title': 'Push-ups', 'logged': False},
           {'program_id': 'run1', 'date': today, 'time_start': '18:00', 'lesson_id': 'l1', 'variant_label': 'B', 'unit_title': 'Push-ups', 'logged': False}]
    with patch.object(programs, 'practice_windows', lambda *a, **k: win):
        prog = [r for r in _rows(p['id']) if r['kind'] == 'program']
    check([r['moment']['slot_rank'] for r in prog] == [0, 1], f"same-day windows carry their rank: {prog}")


def scenario_program_states_without_windows():
    _fresh()
    p = _bath()
    from library_run_fixture import add_run
    base = {'member_id': 'kid', 'title': 'Piano', 'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
            'source': {'origin': 'none', 'reason': 'test'},
            'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}
    for rid, state in (('prop', 'proposed'), ('paus', 'paused'), ('done', 'done')):
        add_run({'id': rid, 'state': state, **base})
        _p().adopt('program', rid, None, project_id=p['id'])
    with patch.object(programs, 'practice_windows', lambda *a, **k: []):
        rows = _rows(p['id'])
    prop, paus, done = _by(rows, 'program', 'prop'), _by(rows, 'program', 'paus'), _by(rows, 'program', 'done')
    check(prop['box'] == 'not_yet' and prop['reason'] == 'needs approval' and prop['group'] == 'now'
          and any(a['label'] == 'Approve' for a in prop['actions']), f"a proposed run for a parent: {prop}")
    check(paus['box'] == 'not_yet' and paus['reason'] == 'paused' and paus['group'] == 'later', f"paused: {paus}")
    check(done['box'] == 'done' and done['group'] == 'logbook', f"done: {done}")
    with patch.object(programs, 'practice_windows', lambda *a, **k: []):
        prop_kid = _by(_rows(p['id'], KID), 'program', 'prop')
    check(prop_kid['group'] == 'later' and not prop_kid['actions'], f"a child sees the proposal as Later with no Approve: {prop_kid}")


def scenario_unresolved_program():
    _fresh()
    p = _bath()
    storage.add_program({'id': 'lost', 'member_id': 'mom', 'state': 'active', 'library_id': 'nope', 'shape': {}, 'progress': {},
                         'sessions': [], 'emissions': {}, 'baseline': {}})
    _p().adopt('program', 'lost', None, project_id=p['id'])
    with patch.object(programs, 'practice_windows', lambda *a, **k: []):
        r = _by(_rows(p['id']), 'program', 'lost')
    check(r['title'] == 'Needs a program' and r['box'] == 'not_yet' and any(a['label'] == 'Pick a program' for a in r['actions']),
          f"an unresolved run: {r}")


def scenario_only_links():
    _fresh()
    p = _bath()
    _p().add_piece(p['id'], 'list', 'l1', dict(MOM))
    rows = _rows(p['id'])
    check(len(rows) == 1 and rows[0]['kind'] == 'link' and rows[0]['box'] is None and rows[0]['group'] == 'linked'
          and rows[0]['glyph'] == 'list' and rows[0]['sheet'] is None, f"a link row: {rows}")


def scenario_keeper_view_words_only():
    _fresh()
    from services import access
    p = _p().create({'title': 'Surprise', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'private'}, dict(MOM))['project']
    tid = threads.create(title='Venue', owner_member_id='aunt', created_by='aunt', project_id=p['id'], next_action='Book the hall')
    # A viewer who may not see the project at all gets no rows from it (Argyle's elsewhere() carries her keeper rows).
    check(_rows(p['id'], AUNT) == [], "a viewer outside a private project reads no rows")
    # A viewer who sees the project but reads the thread as its keeper: the row carries only the keeper projection's words.
    storage.update_project(p['id'], {'audience': 'household'})
    real = access.record_view
    keeper_for_thread = lambda kind, row, viewer, **kw: access.KEEPER if kind == 'thread' else real(kind, row, viewer, **kw)
    with patch.object(access, 'record_view', keeper_for_thread):
        r = _by(_rows(p['id'], AUNT), 'conversation', tid)
    check('Book the hall' not in (r['title'] + r['subtitle']), f"a keeper row carries no hidden words: {r}")
    check(r['box'] == 'not_yet' and r['reason'] == 'set a next step' and r['group'] == 'later' and not r['actions']
          and r['subtitle'] == 'conversation', f"a keeper row is never tickable and never Now: {r}")


def scenario_detail_route_carries_rows():
    _fresh()
    import main
    p = _bath()
    s = _step(p['id'], 'Demo the old tile')
    headers = {'X-Member-Token': storage.create_member_token('mom')}
    settings = dict(storage.get_settings(), auth_enforce=True)
    with patch.object(storage, 'get_settings', return_value=settings):
        response = TestClient(main.app).get(f"/api/projects/{p['id']}", headers=headers)
    body = response.json()
    check(response.status_code == 200 and body['project']['id'] == p['id']
          and [(r['kind'], r['id']) for r in body['rows']] == [('step', s['id'])],
          f"the detail route carries rows beside the project: {response.text[:300]}")


def scenario_doing_step_is_next():
    _fresh()
    p = _bath()
    s = _step(p['id'], 'Demo the old tile')
    _p().set_step_state(p['id'], s['id'], 'doing', dict(MOM))
    r = _by(_rows(p['id']), 'step', s['id'])
    check(r['box'] == 'open' and r['group'] == 'next' and '_doing' not in r, f"an undated doing step is Next: {r}")


def _mission(pid, goal='find three tilers', launch=None, **fields):
    launch = launch or {}
    with patch.object(missions, '_bump_call', lambda *a, **k: True):   # the daily launch cap is not under test
        mid = missions.launch(goal, created_by='mom', project_id=pid, **launch)['mission_id']
    if fields:
        storage.update_mission(mid, fields)
    return mid


_WORK_PLAN = {'state': 'approved', 'rev': 1, 'stages': [
    {'id': 's1', 'kind': 'work', 'state': 'running', 'title': 'Call the tilers', 'snapshot': 'snap', 'rows': []}]}


def scenario_blocked_mission_is_not_the_logbook():
    _fresh()
    p = _bath()
    mid = _mission(p['id'], status='blocked')
    r = _by(_rows(p['id']), 'argyle', mid)
    check(r['box'] == 'not_yet' and r['group'] == 'later' and r['reason'] and '_' not in r['reason'], f"a blocked mission waits for a person, Later: {r}")


def scenario_running_planned_mission_is_not_asking():
    _fresh()
    p = _bath()
    mid = _mission(p['id'], status='running', plan=_WORK_PLAN)
    from services import situations
    opts = situations.view('mission', mid, dict(MOM))['options']
    check(any(o['verb'] == 'run_stage' for o in opts), "precondition: a running planned mission carries Skip/Stop")
    r = _by(_rows(p['id']), 'argyle', mid)
    check(r['box'] == 'argyle' and r['when'] == 'running' and r['group'] == 'next' and r['title'] == 'Call the tilers' and not r['actions'],
          f"a running planned mission is Next, titled by its work, with no buttons: {r}")
    # Its thread (forwarding and folding) is not asking either.
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
    mid2 = _mission(p['id'], 'draft to the tiler', launch={'origin_kind': 'thread', 'origin_ref': tid}, status='running', plan=_WORK_PLAN)
    rows = _rows(p['id'])
    t = _by(rows, 'conversation', tid)
    check(t['box'] == 'open' and t['title'] == 'Call' and not t['actions'], f"a thread whose mission is only running is not asking: {t}")
    check(not any(r['kind'] == 'argyle' and r['id'] == mid2 for r in rows), "and the folded mission has no row")


def scenario_quiet_stalled_thread_is_not_an_empty_ask():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'])
    with patch.object(threads, 'is_stalled', lambda *a, **k: 'quiet'):
        r = _by(_rows(p['id']), 'conversation', tid)
    check(r['box'] == 'not_yet' and r['reason'] == 'set a next step' and not r['actions'], f"a quiet thread with no next step: {r}")


def scenario_fold_needs_a_parent_or_adult():
    projects = _p()
    thread = {'kind': 'thread', 'id': 't1', 'situation': {'x': 1}, 'sheet': True, 'view': 'full'}
    mission = {'kind': 'mission', 'id': 'm1', 'origin_thread': 't1', 'situation': {'x': 1}, 'sheet': True, 'view': 'full'}
    cards = [thread, mission]
    check(projects._fold_target(cards, mission, dict(MOM)) == 't1', "a parent folds")
    check(projects._fold_target(cards, mission, dict(DAD)) == 't1', "an adult folds")
    check(projects._fold_target(cards, mission, dict(KID)) is None, "a child keeps the mission's own row")
    check(projects._fold_target(cards, mission, None) is None, "no viewer, no fold")


def scenario_house_viewer_is_never_an_approver():
    _fresh()
    p = _bath()
    from library_run_fixture import add_run
    from services import access
    add_run({'id': 'prop', 'state': 'proposed', 'member_id': 'kid', 'title': 'Piano',
             'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
             'source': {'origin': 'none', 'reason': 'test'},
             'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}})
    _p().adopt('program', 'prop', None, project_id=p['id'])
    with patch.object(programs, 'practice_windows', lambda *a, **k: []):
        rows = _p().rows(storage.get_project(p['id']), dict(access.HOUSE))
    prop = [r for r in rows if r['kind'] == 'program']
    check(not prop or not prop[0]['actions'], f"the wall never gets Approve: {prop}")


ALLOWED_BOXES = ('open', 'done', 'argyle', 'asking', 'not_yet')


def _one_row(rows, kind, rid, what):
    mine = [r for r in rows if r['kind'] == kind and r['id'] == rid]
    check(len(mine) == 1, f"{what}: exactly one row, got {len(mine)}")
    r = mine[0]
    check(r['box'] in ALLOWED_BOXES and r['group'] in _p().ROW_GROUPS, f"{what}: a known box and group: {r}")
    for field in ('title', 'subtitle', 'reason'):
        check('_' not in (r[field] or ''), f"{what}: no state code in {field}: {r}")
    return r


def scenario_every_status_and_state_maps_to_one_row():
    _fresh()
    p = _bath()
    # Every mission status.
    statuses = sorted(set(missions.LIVE) | set(missions.ATTENTION) | set(missions.TERMINAL))
    check(len(statuses) >= 8, f"the status table: {statuses}")
    ids = {}
    for status in statuses:
        mid = _mission(p['id'], f'work for {status}'.replace('_', ' '), status=status)
        if status == 'waiting_user':
            storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Which one?'}})
        ids[status] = mid
    # Every step: owner x state, with and without a question.
    from services import projects
    proj = storage.get_project(p['id'])
    step_ids = []
    for owner in ('mom', 'argyle'):
        for state in projects.STEP_STATES:
            for question in (None, 'Which one?'):
                sid = uuid_hex()
                proj['steps'].append({'id': sid, 'title': f'{owner} {state}', 'owner': owner, 'state': state, 'needs': [],
                                      'order': len(proj['steps']) + 1, 'goal': 'find tile', 'mission_id': None,
                                      'question': question, 'reason': 'out of tile' if state == 'blocked' else None})
                step_ids.append((owner, state, question, sid))
    storage.update_project(p['id'], {'steps': proj['steps']})
    # Every program state.
    from library_run_fixture import add_run
    base = {'member_id': 'kid', 'title': 'Piano', 'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
            'source': {'origin': 'none', 'reason': 'test'},
            'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}
    pstates = ('active', 'proposed', 'paused', 'done', 'dropped')
    for state in pstates:
        add_run({'id': 'prog_' + state, 'state': state, **base})
        _p().adopt('program', 'prog_' + state, None, project_id=p['id'])
    with patch.object(programs, 'practice_windows', lambda *a, **k: []):
        rows = _rows(p['id'])
    for status, mid in ids.items():
        r = _one_row(rows, 'argyle', mid, f'mission {status}')
        if status in ('done', 'dropped'):
            check(r['group'] == 'logbook', f"{status} is the Logbook: {r}")
        if status == 'waiting_user':
            check(r['box'] == 'asking' and r['group'] == 'now', f"{status} is asking: {r}")
        if status in ('waiting_retry', 'waiting_step', 'blocked'):
            check(r['box'] == 'not_yet' and r['group'] == 'later', f"{status} is not yet, Later: {r}")
        if status in ('running', 'browsing'):
            check(r['box'] == 'argyle' and r['group'] == 'next', f"{status} is Next: {r}")
    for owner, state, question, sid in step_ids:
        _one_row(rows, 'step', sid, f'step {owner} {state} q={question}')
    for state in pstates:
        _one_row(rows, 'program', 'prog_' + state, f'program {state}')


def uuid_hex():
    import uuid
    return uuid.uuid4().hex


def scenario_planned_ask_on_a_step_backed_mission_is_one_asking_row():
    _fresh()
    p = _bath()
    from services import planned
    plan = {'state': 'approved', 'rev': 1, 'stages': [
        {'id': 's1', 'kind': 'work', 'state': 'proposed', 'title': 'Find tile', 'snapshot': 'snap', 'rows': []},
        {'id': 's2', 'kind': 'work', 'state': 'pending', 'title': 'Order tile', 'snapshot': 'snap', 'rows': []}]}
    mid = _mission(p['id'], 'find and order tile', status='running', plan=plan)
    proj = storage.get_project(p['id'])
    base = {'owner': 'argyle', 'needs': [], 'mission_id': mid, 'found': None, 'question': None, 'state': 'todo', 'goal': 'x'}
    proj['steps'] = [{**base, 'id': 'st1', 'title': 'Find tile', 'stage_id': 's1', 'order': 1},
                     {**base, 'id': 'st2', 'title': 'Order tile', 'stage_id': 's2', 'order': 2}]
    storage.update_project(p['id'], {'steps': proj['steps']})
    with patch('services.missions._dm_person', lambda *a, **k: None):
        planned._ask(mid, 'stage', 'Do this part?', stage_id='s1')
    rows = _rows(p['id'])
    asking = [r for r in rows if r['box'] == 'asking']
    check(len(asking) == 1 and asking[0]['kind'] == 'step' and asking[0]['id'] == 'st1' and asking[0]['group'] == 'now'
          and asking[0]['actions'] and asking[0]['sheet'] == {'kind': 'mission', 'id': mid}
          and asking[0]['title'] == 'Argyle needs you: Do this part?', f"one asking row, on the asked stage's step: {asking}")
    check(not any(r['kind'] == 'argyle' for r in rows), "the step owns the mission's row")
    other = _by(rows, 'step', 'st2')
    check(other['box'] != 'asking', f"the other stage's step does not also ask: {other}")


def scenario_thread_ask_with_no_projected_buttons_is_not_asking():
    # Final review F1: the invented Answer fallback is gone. With no ask on the
    # viewer's own projection the row is the plain conversation, never a dead button.
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
    mid = _mission(p['id'], 'draft to the tiler', launch={'origin_kind': 'thread', 'origin_ref': tid}, status='waiting_user')
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Send it?'}})
    from services import projects
    with patch.object(projects, '_ask_actions', lambda sit, mission=None: []):
        r = _by(_rows(p['id']), 'conversation', tid)
    check(r['box'] == 'open' and r['title'] == 'Call' and r['actions'] == [] and 'Send it?' not in r['title'] + r['subtitle'],
          f"no projected ask: no asking row, no Answer: {r}")


def scenario_stage_buttons_stay_off_non_stage_asks():
    _fresh()
    p = _bath()
    from services import situations
    mid = _mission(p['id'], 'book the tiler', status='waiting_user', plan=_WORK_PLAN)
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'release', 'result_json': {'question': 'Share your phone number?'}})
    verbs = [o['verb'] for o in situations.view('mission', mid, dict(MOM))['options']]
    check('run_stage' in verbs and 'release' in verbs, f"precondition: the sheet carries Skip/Stop beside the release: {verbs}")
    r = _by(_rows(p['id']), 'argyle', mid)
    check(r['box'] == 'asking' and r['actions'] and {a['verb'] for a in r['actions']} == {'release'},
          f"a release ask's row carries release buttons only: {r['actions']}")
    # The same ask through a thread and through a step.
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
    mid2 = _mission(p['id'], 'draft to the tiler', launch={'origin_kind': 'thread', 'origin_ref': tid}, status='waiting_user', plan=_WORK_PLAN)
    storage.add_mission_step(mid2, {'kind': 'ask', 'name': 'release', 'result_json': {'question': 'Share your email?'}})
    t = _by(_rows(p['id']), 'conversation', tid)
    check(t['box'] == 'asking' and t['actions'] and 'run_stage' not in {a['verb'] for a in t['actions']},
          f"and its thread row: {t['actions']}")
    # A stage ask keeps its own run_stage buttons (covered by the planned-ask scenario).


# --- Final review F1: rows speak only the viewer's projection (probes A-D, real records) ---

def _project(title, owner, audience, actor=MOM):
    return _p().create({'title': title, 'goal': 'g', 'done_when': 'd', 'owner_member_id': owner,
                        'audience': audience}, dict(actor))['project']


def _keeper_mission():
    """Dad's mission about a thread in Mom's private project, adopted into Dad's household project."""
    _fresh()
    from services import access
    hidden = _project('Surprise party', 'mom', 'private')
    garden = _project('Garden', 'dad', 'household')
    t_hidden = threads.create(title='Riverside venue', owner_member_id='mom', created_by='mom', project_id=hidden['id'],
                              next_action='Pay the deposit')
    mid = storage.add_mission({'goal': 'Draft to the venue', 'created_by': 'dad', 'status': 'waiting_user',
                               'subject_kind': 'thread', 'subject_id': t_hidden})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question',
                                   'result_json': {'question': 'SECRET-A: mention the surprise party at Riverside on May 3?'}})
    _p().adopt('mission', mid, None, project_id=garden['id'])
    check(access.record_view('mission', storage.get_mission(mid), dict(DAD)) == access.KEEPER,
          "precondition: Dad reads his own mission as its keeper (its subject is hidden from him)")
    return garden, mid


def scenario_keeper_mission_row_carries_no_ask_words():
    garden, mid = _keeper_mission()   # probe A
    r = _by(_rows(garden['id'], DAD), 'argyle', mid)
    check('SECRET' not in r['title'] + r['subtitle'] + r['reason'] and r['actions'] == [] and r['box'] != 'asking'
          and r['title'] == 'Draft to the venue', f"a keeper's mission row carries only the card title, no ask, no Answer: {r}")
    # The same mission read in full (Mom may see the subject): the question is hers to answer.
    mom = _by(_rows(garden['id'], MOM), 'argyle', mid)
    check(mom['box'] == 'asking' and mom['title'].startswith('SECRET-A') and [a['verb'] for a in mom['actions']] == ['answer'],
          f"a full reader keeps the ask and its words: {mom}")


def scenario_keeper_running_mission_row_carries_no_stage_title():
    garden, mid = _keeper_mission()   # probe C
    storage.update_mission(mid, {'status': 'running', 'plan': {'state': 'approved', 'rev': 1, 'stages': [
        {'id': 's1', 'kind': 'work', 'state': 'running', 'title': 'SECRET-C: call Riverside about the surprise',
         'snapshot': 'x', 'rows': []}]}})
    r = _by(_rows(garden['id'], DAD), 'argyle', mid)
    check('SECRET' not in r['title'] + r['subtitle'] and r['title'] == 'Draft to the venue' and r['box'] == 'argyle'
          and r['actions'] == [], f"a keeper's running row reads the card title, never the stage: {r}")
    mom = _by(_rows(garden['id'], MOM), 'argyle', mid)
    check(mom['title'] == 'SECRET-C: call Riverside about the surprise', f"a full reader sees the stage under way: {mom}")


def scenario_child_thread_row_never_quotes_a_hidden_mission():
    _fresh()   # probe B
    from services import access
    piano = _project('Piano', 'kid', 'household')
    tid = threads.create(title='Piano teacher', owner_member_id='kid', created_by='mom', project_id=piano['id'],
                         counterparty_name='Ms Lee', next_action='')
    mid = storage.add_mission({'goal': 'Draft to Ms Lee', 'created_by': 'mom', 'status': 'waiting_user',
                               'origin_kind': 'thread', 'origin_ref': tid, 'project_id': piano['id']})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'SECRET-B: offer $40 an hour?'}})
    check(access.record_view('thread', storage.get_thread(tid), dict(KID)) == access.FULL
          and access.record_view('mission', storage.get_mission(mid), dict(KID)) is None,
          "precondition: Kate reads her thread in full and may not see Mom's mission")
    rows = _rows(piano['id'], KID)
    r = _by(rows, 'conversation', tid)
    check('SECRET' not in r['title'] + r['subtitle'] and r['box'] != 'asking' and r['actions'] == []
          and r['title'] == 'Piano teacher', f"a child's own thread row never carries a mission she cannot see: {r}")
    check(not any(x['kind'] == 'argyle' for x in rows), "and she gets no mission row")
    mom = _by(_rows(piano['id'], MOM), 'conversation', tid)
    check(mom['box'] == 'asking' and mom['title'] == 'SECRET-B: offer $40 an hour?', f"Mom, who reads the mission, is asked: {mom}")


def scenario_child_step_row_never_quotes_its_mission():
    _fresh()   # probe D
    from services import access
    p = _project('Ride a bike', 'kid', 'household')
    s = _step(p['id'], 'Find a helmet', owner='argyle', goal='find a helmet')
    mid = storage.get_project(p['id'])['steps'][0]['mission_id']
    check(access.record_view('mission', storage.get_mission(mid), dict(KID)) is None, "precondition: Kate cannot see the step's mission")
    storage.update_mission(mid, {'status': 'waiting_user'})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'stage',
                                   'result_json': {'question': 'SECRET-D: spend $60 on the Giro helmet?', 'stage_id': 'x'}})
    r = _by(_rows(p['id'], KID), 'step', s['id'])
    check('SECRET' not in r['title'] + r['subtitle'] and r['actions'] == [] and r['box'] != 'asking'
          and r['title'] == 'Find a helmet' and (r['sheet'] or {}).get('kind') == 'step',
          f"a child's step row: the step's title, no Answer, no mission sheet: {r}")
    # A plain ask writes step.question: still not on the child's row.
    _p().on_question(mid, 'SECRET-D2: which colour?')
    r = _by(_rows(p['id'], KID), 'step', s['id'])
    check('SECRET' not in r['title'] + r['subtitle'] and r['actions'] == [], f"nor the step's copied question: {r}")


def scenario_pick_a_program_is_gated_like_the_old_card():
    _fresh()
    from services import access
    p = _bath()
    storage.add_program({'id': 'lost', 'member_id': 'kid', 'state': 'active', 'library_id': 'nope', 'shape': {}, 'progress': {},
                         'sessions': [], 'emissions': {}, 'baseline': {}})
    _p().adopt('program', 'lost', None, project_id=p['id'])
    with patch.object(programs, 'practice_windows', lambda *a, **k: []):
        mom = _by(_rows(p['id'], MOM), 'program', 'lost')
        own = _by(_rows(p['id'], KID), 'program', 'lost')
        house = _by(_p().rows(storage.get_project(p['id']), access.HOUSE), 'program', 'lost')
        with patch.object(_p(), 'can_act', lambda project, viewer: False):
            aunt = _by(_rows(p['id'], AUNT), 'program', 'lost')
    check(any(a['verb'] == 'rebind' for a in mom['actions']), f"the project's actor picks a program: {mom}")
    check(not _p().can_act(storage.get_project(p['id']), dict(KID)) and any(a['verb'] == 'rebind' for a in own['actions']),
          f"the run's own member does, without acting on the project: {own}")
    check(house['actions'] == [] and aunt['actions'] == [],
          f"a viewer who may not act and is not the run's member gets no Pick a program: {house} {aunt}")


def scenario_groups_order():
    check(_p().ROW_GROUPS == ('now', 'next', 'later', 'linked', 'logbook'), "the five groups in order")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            with patch.multiple(auth, identify=auth.identify, acting_member=auth.acting_member,
                                impersonation_refused=auth.impersonation_refused):
                fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
