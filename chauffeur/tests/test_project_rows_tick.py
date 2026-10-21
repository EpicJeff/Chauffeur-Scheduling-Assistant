"""POST /api/projects/{id}/tick: the checkbox (spec 2026-10-20-projects-one-list §2).
Run from chauffeur/: python tests/test_project_rows_tick.py"""
import datetime
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from harness import check  # noqa: F401
from services import storage, missions, threads, auth, programs
from test_front_door_chat import _fresh
from test_subjects import MOM, DAD, AUNT, KID


def _client():
    import main
    return TestClient(main.app)


def _hdr(who):
    return {'X-Member-Token': storage.create_member_token(who)}


def _p():
    from services import projects
    return projects


def _bath():
    return _p().create({'title': 'Bathroom', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'household'}, dict(MOM))['project']


def _row(pid, kind, rid, who='mom'):
    rows = _client().get(f'/api/projects/{pid}', headers=_hdr(who)).json()['rows']
    return next(r for r in rows if r['kind'] == kind and r['id'] == rid)


def _tick(pid, row, done=True, who='mom', key=None):
    return _client().post(f'/api/projects/{pid}/tick', headers=_hdr(who),
                          json={'kind': row['kind'], 'id': row['id'], 'moment': row['moment'], 'done': done, 'key': key or uuid.uuid4().hex})


def scenario_step_tick_and_untick():
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    r = _tick(p['id'], _row(p['id'], 'step', s['id']))
    check(r.status_code == 200 and storage.get_project(p['id'])['steps'][0]['state'] == 'done', f"tick completes: {r.text}")
    r = _tick(p['id'], _row(p['id'], 'step', s['id']), done=False)
    check(r.status_code == 200 and storage.get_project(p['id'])['steps'][0]['state'] == 'todo', f"untick reopens: {r.text}")


def scenario_idempotency_key_replays():
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    row, key = _row(p['id'], 'step', s['id']), uuid.uuid4().hex
    a = _tick(p['id'], row, key=key); b = _tick(p['id'], row, key=key)
    check(a.status_code == 200 and b.status_code == 200 and b.json() == a.json(), "the same key returns the stored result")


def scenario_stale_step_moment():
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    row = _row(p['id'], 'step', s['id'])
    _p().set_step_state(p['id'], s['id'], 'done', dict(MOM))
    r = _tick(p['id'], row)
    check(r.status_code == 409 and 'rows' in r.json(), f"a step already done is stale: {r.text}")


def scenario_blocked_step_parent_override():
    _fresh(); p = _bath()
    a = _p().add_step(p['id'], {'title': 'First', 'owner': 'mom'}, dict(MOM))['step']
    b = _p().add_step(p['id'], {'title': 'Second', 'owner': 'aunt', 'needs': [a['id']]}, dict(MOM))['step']
    row = _row(p['id'], 'step', b['id'])
    check(row['box'] == 'not_yet', "the row is not yet")
    r = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('aunt'),
                       json={'kind': 'step', 'id': b['id'], 'moment': row['moment'], 'done': True, 'key': uuid.uuid4().hex, 'override': True})
    check(r.status_code == 403, f"an adult cannot override a blocked step: {r.text}")
    r = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('mom'),
                       json={'kind': 'step', 'id': b['id'], 'moment': row['moment'], 'done': True, 'key': uuid.uuid4().hex, 'override': True})
    check(r.status_code == 200 and storage.get_project(p['id'])['steps'][1]['state'] == 'done', f"a parent completes anyway: {r.text}")


def scenario_conversation_round_trip():
    _fresh(); p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call Ace', next_action_at='2030-01-01')
    row = _row(p['id'], 'conversation', tid)
    r = _tick(p['id'], row)
    check(r.status_code == 200 and r.json()['result']['entry_id'] and storage.get_thread(tid)['next_action'] == '', f"complete: {r.text}")
    r2 = _tick(p['id'], row)
    check(r2.status_code == 409, f"the old revision is stale: {r2.text}")
    entry = r.json()['result']['entry_id']
    r3 = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('mom'),
                        json={'kind': 'conversation', 'id': tid, 'moment': {'thread_id': tid, 'rev': 1, 'entry_id': entry}, 'done': False, 'key': uuid.uuid4().hex})
    check(r3.status_code == 200 and storage.get_thread(tid)['next_action'] == 'Call Ace', f"restore: {r3.text}")


def scenario_skipped_step_unticks_to_todo():
    # Final review F2: a skipped step draws a done box; its untick reopens it, never a dead 409.
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    _p().set_step_state(p['id'], s['id'], 'skipped', dict(MOM))
    row = _row(p['id'], 'step', s['id'])
    check(row['box'] == 'done' and row['reason'] == 'skipped', f"precondition: a skipped step reads done: {row}")
    r = _tick(p['id'], row, done=False)
    check(r.status_code == 200 and storage.get_project(p['id'])['steps'][0]['state'] == 'todo', f"untick reopens a skipped step: {r.text}")
    r = _tick(p['id'], row, done=False)
    check(r.status_code == 409, f"a second untick of the now-open step is stale: {r.text}")


def scenario_post_tick_successor_carries_the_revision():
    # Final review (Codex 2): the page's "What's next" sends the completion's
    # revision; a successor someone else set meanwhile is never overwritten.
    _fresh(); p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call Ace')
    r = _tick(p['id'], _row(p['id'], 'conversation', tid))
    rev = r.json()['result']['rev']
    check(r.status_code == 200 and rev == 1, f"the completion returns its revision: {r.text}")
    a = _client().post(f'/api/threads/{tid}/advance', headers=_hdr('mom'), json={'next_action': 'Email the quote', 'expect_rev': rev})
    check(a.status_code == 200 and storage.get_thread(tid)['next_action'] == 'Email the quote', f"the successor lands on its revision: {a.text}")
    # Again, with another person's successor set while the prompt was open.
    row = _row(p['id'], 'conversation', tid)
    r = _tick(p['id'], row)
    rev = r.json()['result']['rev']
    threads.advance(tid, 'Dad booked the tiler', None, who='dad')
    before = storage.get_thread(tid)
    a = _client().post(f'/api/threads/{tid}/advance', headers=_hdr('mom'), json={'next_action': 'Email the quote', 'expect_rev': rev})
    check(a.status_code == 409 and a.json()['detail'] == 'Someone set the next step meanwhile.', f"a stale successor answers 409: {a.text}")
    check(storage.get_thread(tid) == before, "and writes nothing: Dad's step stands")
    bad = _client().post(f'/api/threads/{tid}/advance', headers=_hdr('mom'), json={'next_action': 'x', 'expect_rev': '1'})
    check(bad.status_code == 400 and storage.get_thread(tid) == before, f"a malformed revision is refused: {bad.text}")
    plain = _client().post(f'/api/threads/{tid}/advance', headers=_hdr('mom'), json={'next_action': 'Plain advance'})
    check(plain.status_code == 200 and storage.get_thread(tid)['next_action'] == 'Plain advance', "without expect_rev the route is unchanged")


def _run(pid, member='mom', state='active'):
    from library_run_fixture import add_run
    add_run({'id': 'run1', 'member_id': member, 'title': 'Strength', 'state': state,
             'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
             'source': {'origin': 'none', 'reason': 'test'},
             'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}})
    _p().adopt('program', 'run1', None, project_id=pid)


def _windows(date, n=1):
    return [{'program_id': 'run1', 'date': date, 'time_start': f'{8 + 10 * i:02d}:00', 'lesson_id': '', 'variant_label': '',
             'unit_title': 'Push-ups', 'logged': False} for i in range(n)]


def scenario_program_tick_logs_today_only():
    _fresh(); p = _bath(); _run(p['id'])
    today = datetime.date.today()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(today.isoformat())):
        row = _row(p['id'], 'program', 'run1')
        r = _tick(p['id'], row)
    check(r.status_code == 200 and len(storage.get_program('run1')['sessions']) == 1
          and storage.get_program('run1')['sessions'][0]['source'] == 'ticked', f"today's window logs: {r.text}")
    tomorrow = (today + datetime.timedelta(days=1)).isoformat()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(tomorrow)):
        row = _row(p['id'], 'program', 'run1')
        r = _tick(p['id'], row)
    check(r.status_code == 409 and len(storage.get_program('run1')['sessions']) == 1, f"a future window is not tickable: {r.text}")


def scenario_program_double_tick_logs_one():
    _fresh(); p = _bath(); _run(p['id'])
    today = datetime.date.today().isoformat()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(today)):
        row = _row(p['id'], 'program', 'run1')
        a = _tick(p['id'], row)
        b = _tick(p['id'], row)
    check(a.status_code == 200 and b.status_code == 409 and len(storage.get_program('run1')['sessions']) == 1,
          f"the second tick finds the window logged: {b.text}")
    check(b.json()['detail'] == 'That session is already logged.', f"and says so in its own words: {b.text}")


def scenario_program_same_day_windows_disappear_after_one_session():
    _fresh(); p = _bath(); _run(p['id'])
    today = datetime.date.today().isoformat()
    def windows(*args, **kwargs):
        result = _windows(today, 2)
        for window in result:
            window['logged'] = programs._already_logged(storage.get_program('run1'), datetime.date.today())
        return result
    with patch.object(programs, 'practice_windows', side_effect=windows):
        rows = _client().get(f"/api/projects/{p['id']}", headers=_hdr('mom')).json()['rows']
        slots = [r for r in rows if r['kind'] == 'program' and r['moment'].get('window_date') == today]
        check(len(slots) == 2, 'two same-day windows start open')
        first = _tick(p['id'], slots[0])
        check(first.status_code == 200 and not any(r['moment'].get('window_date') == today for r in first.json()['rows']),
              f'per-day logging removes the remaining same-day window: {first.text}')
        second = _tick(p['id'], slots[1])
        check(second.status_code == 409 and 'rows' in second.json() and len(storage.get_program('run1')['sessions']) == 1,
              f'a vanished window is stale, not a missing piece: {second.text}')


def scenario_program_untick_is_405():
    _fresh(); p = _bath(); _run(p['id'])
    today = datetime.date.today().isoformat()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(today)):
        row = _row(p['id'], 'program', 'run1')
        r = _tick(p['id'], row, done=False)
    check(r.status_code == 405, f"no untick on a program row: {r.text}")
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    for windows in (_windows(tomorrow), []):
        with patch.object(programs, 'practice_windows', return_value=windows):
            r = _tick(p['id'], row, done=False)
        check(r.status_code == 405, f'program untick stays 405 when its window moved or vanished: {r.text}')


def scenario_child_cannot_tick_a_siblings_run():
    _fresh(); p = _p().create({'title': 'Kate', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'kid', 'audience': 'household'}, dict(MOM))['project']
    _run(p['id'], member='dad')
    today = datetime.date.today().isoformat()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(today)):
        row = _row(p['id'], 'program', 'run1', who='mom')
        r = _tick(p['id'], row, who='kid')
    check(r.status_code == 403, f"not her run, not a parent: {r.text}")


def scenario_argyle_and_asking_rows_405():
    _fresh(); p = _bath()
    mid = missions.launch('find tilers', created_by='mom', project_id=p['id'])['mission_id']
    r = _tick(p['id'], _row(p['id'], 'argyle', mid))
    check(r.status_code == 405, f"argyle rows: {r.text}")
    storage.update_mission(mid, {'status': 'waiting_user'})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Which?'}})
    r = _tick(p['id'], _row(p['id'], 'argyle', mid))
    check(r.status_code == 405 and r.json()['detail'] == 'Argyle is waiting on you, not on a tick.', f"asking rows: {r.text}")


def scenario_tick_refused_on_paused_project():
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    row = _row(p['id'], 'step', s['id'])
    _p().set_state(p['id'], 'paused', dict(MOM))
    r = _tick(p['id'], row)
    check(r.status_code == 403, f"a paused project takes no ticks: {r.text}")


def scenario_not_a_piece_is_404():
    _fresh(); p = _bath(); q = _bath()
    tid = threads.create(title='Elsewhere', owner_member_id='mom', created_by='mom', project_id=q['id'], next_action='x')
    r = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('mom'),
                       json={'kind': 'conversation', 'id': tid, 'moment': {'thread_id': tid, 'rev': 0}, 'done': True, 'key': uuid.uuid4().hex})
    check(r.status_code == 404, f"a record of another project: {r.text}")


def scenario_bad_bodies_and_moment_identity():
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    row = _row(p['id'], 'step', s['id'])
    good = {'kind': 'step', 'id': s['id'], 'moment': row['moment'], 'done': True, 'key': uuid.uuid4().hex}
    for change in ({'kind': 'link'}, {'id': []}, {'key': {}}, {'done': 'false'},
                   {'moment': []}, {'moment': None}, {'moment': {}}, {'override': 'true'}):
        r = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('mom'), json={**good, **change})
        check(r.status_code == 400, f'bad body is 400: {change}: {r.text}')
    for body in ([], 'bad', 7):
        r = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('mom'), json=body)
        check(r.status_code == 400, f'a non-object body is 400: {r.text}')
    r = _tick(p['id'], {**row, 'moment': {'step_id': 'elsewhere'}})
    check(r.status_code == 409 and 'rows' in r.json(), f'wrong step identity is stale: {r.text}')


def scenario_conversation_validation_and_closed_restore():
    for state in ('done', 'dropped'):
        _fresh(); p = _bath()
        tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
        row = _row(p['id'], 'conversation', tid)
        for rev in (None, 'bad', True, 0.5):
            r = _tick(p['id'], {**row, 'moment': {'thread_id': tid, 'rev': rev}})
            check(r.status_code == 400, f'invalid revision is 400: {r.text}')
        wrong = _tick(p['id'], {**row, 'moment': {'thread_id': 'other', 'rev': 0}})
        check(wrong.status_code == 409, 'a thread id is part of its moment')
        completed = _tick(p['id'], row)
        threads.close(tid, state, who='mom')
        before = storage.get_thread(tid)
        for done in (True, False):
            moment = {'thread_id': tid, 'rev': 1, 'entry_id': completed.json()['result']['entry_id']}
            r = _tick(p['id'], {**row, 'moment': moment}, done=done)
            check(r.status_code == 409 and 'rows' in r.json() and storage.get_thread(tid) == before,
                  f'a {state} conversation cannot tick or restore: {r.text}')


def scenario_conversation_advance_invalidates_restore_and_asking_is_405():
    _fresh(); p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
    row = _row(p['id'], 'conversation', tid)
    completed = _tick(p['id'], row).json()['result']
    r = _client().post(f'/api/threads/{tid}/advance', headers=_hdr('mom'),
                      json={'next_action': 'Email Ace', 'member_id': 'mom'})
    check(r.status_code == 200 and storage.get_thread(tid)['next_action'] == 'Email Ace', f'next action by hand: {r.text}')
    moment = {'thread_id': tid, 'rev': completed['rev'], 'entry_id': completed['entry_id']}
    r = _tick(p['id'], {**row, 'moment': moment}, done=False)
    check(r.status_code == 409, f'a successor forbids restore: {r.text}')
    mid = missions.launch('find tilers', created_by='mom', project_id=p['id'], origin_kind='thread', origin_ref=tid)['mission_id']
    storage.update_mission(mid, {'status': 'waiting_user'})
    storage.add_mission_step(mid, {'kind': 'ask', 'result_json': {'question': 'Which?'}})
    r = _tick(p['id'], _row(p['id'], 'conversation', tid))
    check(r.status_code == 405, f'a folded conversation ask cannot tick: {r.text}')


def scenario_program_lesson_identity_and_logged_slot_rank():
    _fresh(); p = _bath(); _run(p['id'])
    today = datetime.date.today().isoformat()
    windows = _windows(today, 2)
    windows[0]['logged'] = True
    with patch.object(programs, 'practice_windows', return_value=windows):
        row = _row(p['id'], 'program', 'run1')
        check(row['moment']['slot_rank'] == 1, 'logged slots still occupy their rank')
        for change in ({'run_id': 'elsewhere'}, {'lesson_id': 'moved'}, {'variant_label': 'moved'}, {'slot_rank': 0}):
            r = _tick(p['id'], {**row, 'moment': {**row['moment'], **change}})
            check(r.status_code == 409 and 'rows' in r.json(), f'a moved program moment is stale: {change}: {r.text}')
        with patch.object(programs, 'lesson_for', return_value={'lesson_id': 'new', 'variant_label': ''}):
            r = _tick(p['id'], row)
            check(r.status_code == 409, f'the live lesson resolver must agree: {r.text}')
        r = _tick(p['id'], row)
        check(r.status_code == 200, f'a rank includes the logged first window: {r.text}')


def scenario_program_concurrent_ticks_and_same_key():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    for same_key in (False, True):
        _fresh(); p = _bath(); _run(p['id'])
        today = datetime.date.today().isoformat()
        with patch.object(programs, 'practice_windows', return_value=_windows(today)):
            row = _row(p['id'], 'program', 'run1')
            headers = _hdr('mom')
            barrier = Barrier(2)
            key = uuid.uuid4().hex
            def tick(i):
                barrier.wait(timeout=10)
                return _client().post(f"/api/projects/{p['id']}/tick", headers=headers,
                                      json={'kind': 'program', 'id': 'run1', 'moment': row['moment'],
                                            'done': True, 'key': key if same_key else f'{key}-{i}'})
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(tick, range(2)))
        check(sorted(r.status_code for r in responses) == ([200, 200] if same_key else [200, 409]),
              f'concurrent ticks (same_key={same_key}): {[r.text for r in responses]}')
        check(len(storage.get_program('run1')['sessions']) == 1, 'concurrent ticks log once')
        if same_key:
            check(responses[0].json() == responses[1].json(), 'concurrent replay returns the stored body')


def scenario_replay_obeys_access_and_expires():
    import time
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    row, key = _row(p['id'], 'step', s['id']), uuid.uuid4().hex
    first = _tick(p['id'], row, key=key)
    check(first.status_code == 200, first.text)
    r = _tick(p['id'], row, key=key, who='kid')
    check(r.status_code == 403 and 'rows' not in r.json(), f'a key never bypasses a gate: {r.text}')
    _p().set_state(p['id'], 'paused', dict(MOM))
    check(_tick(p['id'], row, key=key).status_code == 403, 'a paused project refuses a replay')
    _p().set_state(p['id'], 'active', dict(MOM))
    with patch('time.time', return_value=time.time() + 86401):
        r = _tick(p['id'], row, key=key)
    check(r.status_code == 409, f'a key older than 24 hours no longer replays: {r.text}')


def scenario_child_step_gate_and_override_service():
    _fresh()
    p = _p().create({'title': 'Kate', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'kid', 'audience': 'household'}, dict(MOM))['project']
    s = _p().add_step(p['id'], {'title': 'Parent work', 'owner': 'mom'}, dict(MOM))['step']
    r = _tick(p['id'], _row(p['id'], 'step', s['id']), who='kid')
    check(r.status_code == 403, f'a child cannot tick another owner step: {r.text}')
    result = _p().set_step_state(p['id'], s['id'], 'done', dict(AUNT), override=True)
    check(result.get('code') == 403, f'the service rejects a nonparent override too: {result}')


def scenario_keeper_visible_action_and_hidden_action():
    import access_fixture
    fx = access_fixture.build()
    # A keeper with a full view may complete the next action they actually see.
    tid = fx.ids['R5t']  # Dad's own conversation in the household project
    row = _row(fx.projects['household']['id'], 'conversation', tid, who='dad')
    r = _tick(fx.projects['household']['id'], row, who='dad')
    check(r.status_code == 200, f'the keeper can tick their visible next action: {r.text}')
    # R10 belongs to Dad but its subject is hidden; the projected action is absent.
    tid = fx.ids['R10']
    row = _row(fx.projects['household']['id'], 'conversation', tid, who='dad')
    check(row['box'] != 'open' and fx.secret('R10') not in str(row), 'a hidden action has no open box')
    r = _tick(fx.projects['household']['id'], row, who='dad')
    check(r.status_code == 409 and storage.get_thread(tid)['next_action'] == fx.secret('R10'),
          f'forging a tick cannot complete the hidden action: {r.text}')


def scenario_replay_cannot_reveal_a_now_hidden_piece():
    for kind in ('thread', 'link'):
        _fresh(); p = _bath()
        a = threads.create(title='First', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
        b = threads.create(title='Second', owner_member_id='dad', created_by='dad', project_id=p['id'], next_action='Private words') if kind == 'thread' else None
        if kind == 'link':
            storage.save_occasion({'id': 'secret-for-dad', 'title': 'Private words', 'audience': 'household'})
            linked = _p().add_piece(p['id'], 'occasion', 'secret-for-dad', dict(MOM))
            check(linked['status'] == 'success', f'the occasion starts visible: {linked}')
        row, key = _row(p['id'], 'conversation', a), uuid.uuid4().hex
        check(_tick(p['id'], row, key=key).status_code == 200, 'first tick succeeds')
        storage.save_occasion({'id': 'secret-for-dad', 'title': 'Private words', 'audience': 'private', 'shared_with': ['dad']})
        if b:
            storage.update_thread(b, {'subject_kind': 'occasion', 'subject_id': 'secret-for-dad'})
        r = _tick(p['id'], row, key=key)
        check(r.status_code == 409 and 'Private words' not in r.text, f'a replay respects current visibility ({kind}): {r.text}')


def scenario_replay_write_failure_rolls_back_completion():
    _fresh(); p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
    row = _row(p['id'], 'conversation', tid)
    before = storage.get_thread(tid)
    write = storage.set_app_state
    def fail_replay(name, value):
        if name == 'projects_tick_results':
            raise RuntimeError('replay write failed')
        return write(name, value)
    with patch.object(storage, 'set_app_state', side_effect=fail_replay):
        try:
            _tick(p['id'], row)
        except RuntimeError:
            pass
        else:
            raise AssertionError('the failed transaction must surface')
    check(storage.get_thread(tid) == before, 'completion and replay storage commit or roll back together')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            with patch.multiple(auth, identify=auth.identify, acting_member=auth.acting_member, impersonation_refused=auth.impersonation_refused):
                fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
