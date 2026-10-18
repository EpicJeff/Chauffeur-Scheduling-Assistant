"""Projects delete, late work cannot write (spec rev 3 section 5, first half; plan Task 1 Step 3).

Each worker below is driven through its REAL entry point; only the outside world is stubbed (the
model, the browser runner, Google Calendar, the research boundary `programs_curate.curate`, web push,
the room speaker). The deletion lands while the worker is inside that boundary, or, where the worker
has no outside call to sit in, at a pass-through hook that calls the real function after starting
the deletion from another request (never a stub of the storage layer). Each one, finishing after
`start`, writes nothing, creates nothing and delivers nothing; cleanup waits while it is registered.

  * `deletion.acting_for(kind, id)` registers work for a source and carries it in a context variable;
    `deletion.active(kind, id)` is True while such work is registered; `deletion.check()` raises
    `deletion.Cancelled` once the source is gone. A worker may end by returning or by raising
    Cancelled; any other exception is a failure.
  * Creation is bound at insert, storage refuses children of gone parents, adoption never makes a
    replacement wrapper, queued deliveries (push fan-out, practice pushes, lesson voice timers)
    re-check just before they go out.
  * Review Focus 5: a worker that never exits keeps the project hidden, cleanup waits, a re-cancel
    is logged after 15 minutes, nothing else errors.

Interface decisions this file pins (beyond the brief):
  * the lesson wait route takes the program it was armed for: POST /api/lessons/wait
    {room, text, minutes, program_id}, and the queued entry carries it to delivery;
  * the 15-minute clock reads time.time() or time.monotonic() through the `time` module;
  * a route whose work hits Cancelled answers 404 shaped like a missing record (never an exception).

Run from chauffeur/:  python tests/test_deletion_late_work.py
"""
import contextlib
import contextvars
import datetime
import io
import json
import logging
import os
import tempfile
import threading
import time
import traceback
import uuid
from unittest.mock import patch

from harness import check  # noqa: F401
from test_deletion_core import (_d, build, garage, start_ok, finish, http, in_fresh_context, words_of, leaked,
                                GARAGE_KEYS, pair, LOAD)
from access_fixture import _program
from test_subjects import MOM
from services import storage, projects, missions, situations, threads

PUSHES, SPOKEN, INSERTS = [], [], []


class Gate:
    """An outside call that does not return until the test says so."""

    def __init__(self):
        self.entered, self.released = threading.Event(), threading.Event()

    def wait(self, timeout=60):
        self.entered.set()
        if not self.released.wait(timeout):
            raise RuntimeError('the gate was never released')

    def release(self):
        self.released.set()


class Worker:
    """A worker entry point on its own thread, in an empty context, as the scheduler would run it."""

    def __init__(self, fn, *args, **kwargs):
        self.box = {}
        self.thread = threading.Thread(target=self._run, args=(fn, args, kwargs), daemon=True)
        self.thread.start()

    def _run(self, fn, args, kwargs):
        try:
            self.box['value'] = contextvars.Context().run(fn, *args, **kwargs)
        except BaseException as exc:      # noqa: BLE001
            self.box['error'] = exc

    def done(self, how, timeout=30):
        self.thread.join(timeout)
        check(not self.thread.is_alive(), f"{how}: the worker returned")
        err = self.box.get('error')
        check(err is None or cancelled(err), f"{how}: ended by returning or by Cancelled, not {err!r}")
        return self.box.get('value')


def cancelled(exc):
    """deletion.Cancelled, alone or inside the exception group a threadpool wraps it in."""
    if isinstance(exc, _d().Cancelled):
        return True
    return isinstance(exc, BaseExceptionGroup) and any(cancelled(e) for e in exc.exceptions)


def settle(before, timeout=30):
    """Join every thread started since `before` (browse daemons, timers, fan-out)."""
    end = time.monotonic() + timeout
    for t in threading.enumerate():
        if t not in before and t is not threading.current_thread():
            t.join(max(0.1, end - time.monotonic()))


def _record_push(subscription_info=None, data=None, **_):
    PUSHES.append(json.loads(data) if data else {})


def late_world():
    fx = build()
    base = storage.get_settings()
    extra = {'mission_step_cap': 60, 'mission_cap_pro_calls': 200, 'missions_enabled': True,
             'default_calendar_id': 'cal-' + uuid.uuid4().hex[:8], 'programs_enabled': True,
             'program_lessons_enabled': True, 'proactive_watchers_enabled': True, 'llm_gemini_api_key': 'k',
             'tomorrow_digest_enabled': False, 'kid_digest_enabled': False, 'weekly_digest_enabled': False}
    storage.get_settings = (lambda s: (lambda: dict(s)))(dict(base, **extra))
    storage.agent_action_proposals_table.truncate()
    situations.REFRESH_DELAY_S = 0
    missions._browse_async = False
    install_outside_world()
    CAL['gate'] = None
    PUSHES.clear(); SPOKEN.clear(); INSERTS.clear()
    for member, driver in (('mom', 'd_mom'), ('dad', 'd_dad'), ('kid', 'd_kid')):
        storage.update_member(member, {'driver_id': driver})
        storage.save_push_subscription(driver, {'endpoint': f'https://push.example/{member}',
                                                'keys': {'p256dh': 'x', 'auth': 'y'}}, member_id=member)
    return fx


CAL = {'gate': None}       # set by the create_event scenario to hold the Google timezone lookup


def install_outside_world():
    """The outside world, stubbed for this whole process: web push, HA notify, the room speaker and
    Google Calendar are recorded, never reached, even by a worker that outlives its scenario."""
    import pywebpush
    from services import ha_api, announce, family_digest, calendar
    pywebpush.webpush = _record_push
    ha_api.call_service = lambda *a, **k: PUSHES.append({'ha': a}) or True
    announce.announce = lambda room, message: SPOKEN.append((room, message)) or {'status': 'ok'}
    family_digest.in_member_quiet_hours = lambda *a, **k: False
    calendar.get_calendar_service = lambda *a, **k: _FakeCalendar()
    from services import model_pools, web
    model_pools.call_pool_json = _no_model          # a scenario that needs the model patches its own
    web.read_page = lambda *a, **k: None


def _no_model(*a, **k):
    return {'error': 'no model in the deletion tests', 'transient': False}


@contextlib.contextmanager
def outside_world():
    """Kept as a marker of where the outside world is touched; install_outside_world() did the work."""
    yield


def closure_ids(fx):
    return {fx.ids[k] for k in GARAGE_KEYS} | {garage(fx)}


def mark(fx, extra_missions=()):
    """Everything a late worker could write, create or deliver."""
    rows = {}
    for key in GARAGE_KEYS:
        kind, rid = pair(fx, key)
        rows[key] = LOAD[kind](rid)
    for mid in extra_missions:
        rows[mid] = storage.get_mission(mid)
    steps = {mid: storage.get_mission_steps(mid) for mid in [fx.ids['GM1'], fx.ids['GM2'], fx.ids['GKM'], *extra_missions]}
    return {
        'rows': json.dumps(rows, sort_keys=True, default=str),
        'steps': json.dumps(steps, sort_keys=True, default=str),
        'project': json.dumps(storage.get_project(garage(fx)), sort_keys=True, default=str),
        'threads': {t['id'] for t in storage.get_threads(include_closed=True)},
        'missions': {m['id'] for m in storage.get_missions()},
        'programs': {p['id'] for p in storage.get_programs(include_finished=True)},
        'projects': {p['id'] for p in storage.get_projects()},
        'messages': {m['id'] for m in storage.chat_messages_table.all()},
        'proposals': {p['id'] for p in storage.agent_action_proposals_table.all()},
        'asks': {a['id'] for a in storage.asks_table.all()},
        'findings': {f['id'] for f in storage.findings_table.all()},
        'lessons': len(storage.program_lessons_table.all()),
        'commitments': {c['id'] for c in storage.get_protected_commitments(include_inactive=True)},
        'trip': json.dumps(storage.get_trip_metadata('ev_disney'), sort_keys=True, default=str),
        'pushes': len(PUSHES), 'spoken': len(SPOKEN), 'google': len(INSERTS),
    }


def nothing_since(fx, before, how, extra_missions=()):
    after = mark(fx, extra_missions)
    for key in before:
        if before[key] != after[key]:
            extra = ''
            if isinstance(before[key], set):
                extra = f" new: {sorted(after[key] - before[key])[:5]} gone: {sorted(before[key] - after[key])[:5]}"
            check(False, f"{how}: the late worker changed {key}{extra}")


def delete_garage(fx):
    return in_fresh_context(start_ok, 'project', garage(fx), dict(MOM))


def waits_for(fx, kind, rid, how):
    d = _d()
    check(d.active(kind, rid), f"{how}: the worker is registered for its source")
    held = d.maintain()
    check(held['waiting'] >= 1 and storage.get_deletions() and LOAD[kind](rid) is not None,
          f"{how}: cleanup waits while it is registered: {held}")


def drained(fx, how):
    finish()
    for key in GARAGE_KEYS:
        kind, rid = pair(fx, key)
        check(LOAD[kind](rid) is None, f"{how}: {key} is gone once the work has exited")


def _report(outcome, **kw):
    base = {'outcome': outcome, 'text': kw.pop('text', outcome), 'learned': {}, 'stopped_at': 'https://bodewell.com/x',
            'wanted_fields': [], 'turns': 3, 'tokens_in': 10, 'tokens_out': 5, 'seconds': 3.0, 'screenshots': [],
            'filled': {}, 'submit': None, 'attempt': None, 'changed': [], 'attempts_extra': []}
    return {**base, **kw}


# --- the browse turn --------------------------------------------------------------------------

def scenario_a_browse_turn_finishing_after_start_writes_creates_and_delivers_nothing():
    fx = late_world()
    mid = fx.ids['GM2']
    storage.update_mission(mid, {'status': 'running'})
    gate = Gate()
    missions._browse = lambda **kw: gate.wait() or _report('needs_release', wanted_fields=['first_name', 'email'])
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'find a slot', 'site': 'bodewell.com'}
    missions._browse_async = True
    before = set(threading.enumerate())
    with outside_world():
        try:
            Worker(missions.tick).done('the turn that starts the browse')
            check(gate.entered.wait(10), "the browser was reached")
            delete_garage(fx)
            waits_for(fx, 'mission', mid, 'browse')
            snap = mark(fx)
        finally:
            gate.release()
            missions._browse_async = False
            settle(before)
        check(not _d().active('mission', mid), "the browse daemon unregistered in its own finally")
        nothing_since(fx, snap, 'browse')
    drained(fx, 'browse')


# --- a build stage ----------------------------------------------------------------------------

def _staged_in_garage(fx, rows):
    from test_planned_missions import _approved, _plan_of
    from test_mission_subject import _plan, _step
    mid = _approved()
    projects.adopt('mission', mid, None, project_id=garage(fx))
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': rows})
    _step(mid)
    st = _plan_of(mid)['stages'][0]
    check(st['state'] == 'proposed', f"the fixture: a proposed build stage: {st}")
    check(storage.get_mission(mid)['project_id'] == garage(fx), "the fixture: the planned mission lives in the Garage")
    return mid, st


def _run_stage(mid, st):
    return situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve",
                          payload={}, actor=dict(MOM))


def _hooked(fx, target, name, source, seen, extra_missions=()):
    """A pass-through: the first call starts the deletion from another request, then runs the real thing.

    `source` is the (kind, id) the worker acts for: it must be registered while the hook runs."""
    real = getattr(target, name)

    def hook(*args, **kwargs):
        if not seen.get('fired'):
            seen['fired'] = True
            try:
                delete_garage(fx)
                seen['active'] = _d().active(*source)
                seen['maintain'] = _d().maintain()
                seen['mark'] = mark(fx, list(extra_missions))
            except BaseException as exc:      # noqa: BLE001 -- re-raised by reached()
                seen['error'] = exc
                raise
        return real(*args, **kwargs)
    return patch.object(target, name, hook)


def reached(seen, how):
    """The hook fired, and the deletion it started did start (else its own error is the failure)."""
    check(seen.get('fired'), f"{how}: the worker reached the hook")
    if seen.get('error') is not None:
        raise seen['error']


def scenario_a_build_stage_row_that_runs_after_start_creates_nothing():
    from services import chat_actions
    rows = {
        'create_thread': [{'id': 'r1', 'tool': 'create_thread', 'args': {'title': 'Late thread'}, 'summary': 'Open it'}],
        'add_trip_poi': [{'id': 'r1', 'tool': 'add_trip_poi',
                          'args': {'trip_id': 'ev_disney', 'title': 'Late stop', 'location': 'MK'}, 'summary': 'A stop'}],
    }
    for tool, stage_rows in rows.items():
        fx = late_world()
        mid, st = _staged_in_garage(fx, stage_rows)
        seen = {}
        with outside_world(), _hooked(fx, chat_actions, '_execute', ('mission', mid), seen, [mid]):
            Worker(_run_stage, mid, st).done(tool)
        reached(seen, tool)
        check(seen['active'] and seen['maintain']['waiting'] >= 1, f"{tool}: the stage was registered and cleanup waited: {seen}")
        nothing_since(fx, seen['mark'], tool, [mid])
        check(not any(t.get('title') == 'Late thread' for t in storage.get_threads(include_closed=True)), f"{tool}: no thread")
        check('Late stop' not in json.dumps(storage.get_trip_metadata('ev_disney')), f"{tool}: the linked trip is untouched")
        drained(fx, tool)
        check(storage.get_trip_metadata('ev_disney') is not None, f"{tool}: the linked trip itself stays")


def scenario_a_propose_program_row_blocked_in_research_creates_no_program():
    from services import programs_curate
    fx = late_world()
    mid, st = _staged_in_garage(fx, [{'id': 'r1', 'tool': 'propose_program', 'summary': 'Piano',
                                      'args': {'title': 'Late piano', 'for_member_name': 'Kate', 'sessions_per_week': 2,
                                               'minutes': 20, 'starting_point': 'never played'}}])
    gate = Gate()
    curated = {'phases': [], 'source': {'origin': 'none', 'reason': 'test', 'plan_name': '', 'url': ''}}
    with outside_world(), patch.object(programs_curate, 'curate', lambda *a, **k: gate.wait() or curated):
        w = Worker(_run_stage, mid, st)
        try:
            check(gate.entered.wait(15), "research was reached")
            delete_garage(fx)
            waits_for(fx, 'mission', mid, 'propose_program')
            snap = mark(fx, [mid])
        finally:
            gate.release()
            w.thread.join(30)
        w.done('propose_program')
    nothing_since(fx, snap, 'propose_program', [mid])
    check(not any(p.get('title') == 'Late piano' for p in storage.get_programs(include_finished=True)), "no program row")
    drained(fx, 'propose_program')


class _FakeCalendar:
    """Google Calendar, at the client: the timezone lookup can be held (CAL['gate']); inserts are recorded."""

    def calendars(self):
        class _Get:
            def get(self, calendarId=None):
                class _Exec:
                    def execute(self_inner):
                        if CAL['gate']:
                            CAL['gate'].wait()
                        return {'timeZone': 'America/New_York'}
                return _Exec()
        return _Get()

    def events(self):
        class _Events:
            def insert(self, calendarId=None, body=None):
                class _Exec:
                    def execute(self_inner):
                        INSERTS.append(body)
                        return {'id': 'g-' + uuid.uuid4().hex[:6]}
                return _Exec()
        return _Events()


def scenario_a_stage_blocked_inside_create_event_inserts_nothing_afterwards():
    fx = late_world()
    mid, st = _staged_in_garage(fx, [{'id': 'r1', 'tool': 'create_event', 'summary': 'Put it on the calendar',
                                      'args': {'title': 'Late event', 'start': '2027-01-10T10:00:00',
                                               'end': '2027-01-10T11:00:00'}}])
    gate = CAL['gate'] = Gate()
    with outside_world():
        w = Worker(_run_stage, mid, st)
        try:
            check(gate.entered.wait(15), "the stage is inside _create_event, talking to Google")
            delete_garage(fx)
            waits_for(fx, 'mission', mid, 'create_event')
            snap = mark(fx, [mid])
        finally:
            gate.release()
            w.thread.join(30)
        w.done('create_event')
    check(INSERTS == [], f"nothing is inserted at Google after the source is gone: {INSERTS}")
    nothing_since(fx, snap, 'create_event', [mid])
    drained(fx, 'create_event')


# --- a work stage -------------------------------------------------------------------------------

def scenario_a_work_stage_turn_finishing_after_start_writes_nothing():
    from test_planned_missions import _planned_mission, _plan_of
    from test_mission_subject import _step
    fx = late_world()
    mid = _planned_mission()
    projects.adopt('mission', mid, None, project_id=garage(fx))
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:drop:s1', payload={}, actor=dict(MOM))
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    _step(mid)
    check(next(s for s in _plan_of(mid)['stages'] if s['id'] == 's2')['state'] == 'running', "the fixture: a running work stage")
    gate = Gate()
    missions._llm = lambda m, s, u, st: gate.wait() or {'action': 'ask_user', 'question': 'Which bakery, ' + 'late?'}
    with outside_world():
        w = Worker(missions.tick)
        try:
            check(gate.entered.wait(15), "the planner was called inside the work stage")
            delete_garage(fx)
            waits_for(fx, 'mission', mid, 'work stage')
            snap = mark(fx, [mid])
        finally:
            gate.release()
            w.thread.join(30)
        w.done('work stage')
        nothing_since(fx, snap, 'work stage', [mid])
    drained(fx, 'work stage')


# --- programs: lessons, approval, resume ---------------------------------------------------------

def _active_program_with_tomorrow(fx, key='GP1', member='kid'):
    pid = fx.ids[key]
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    cid = storage.add_protected_commitment({'id': uuid.uuid4().hex, 'member_id': member, 'title': fx.title(key),
                                            'days_of_week': [tomorrow.weekday()], 'time_start': '17:00',
                                            'time_end': '17:30', 'active': True, 'source': {'kind': 'program', 'id': pid}})
    storage.update_program(pid, {'state': 'active', 'shape': {'sessions_per_week': 1, 'minutes': 20, 'preferred_days': []},
                                 'phases': [{'name': 'Grade 1', 'weeks': 4, 'what': 'Open chords',
                                             'steps': ['One minute changes'], 'milestone': 'm', 'milestone_hit_at': None}],
                                 'source': {'origin': 'generated'},
                                 'baseline': {'start_date': datetime.date.today().isoformat()},
                                 'emissions': {'commitment_ids': [cid], 'thread_ids': [fx.ids['GK1']], 'event_ids': []}})
    return pid, cid


def scenario_lesson_generation_finishing_after_start_writes_no_lesson():
    from services import model_pools, program_lessons
    fx = late_world()
    pid, _ = _active_program_with_tomorrow(fx)
    storage.set_app_state('program_lessons_swept', '')
    gate = Gate()
    script = {'scenes': [{'type': 'say', 'text': 'Play the change slowly, four times.'}]}
    with outside_world(), patch.object(model_pools, 'call_pool_json', lambda *a, **k: gate.wait() or script):
        w = Worker(program_lessons.generate_due)
        try:
            check(gate.entered.wait(15), "the lesson model was called")
            delete_garage(fx)
            waits_for(fx, 'program', pid, 'lesson generation')
            snap = mark(fx)
        finally:
            gate.release()
            w.thread.join(30)
        w.done('lesson generation')
    nothing_since(fx, snap, 'lesson generation')
    check(not storage.program_lessons_table.search(storage.Query().program_id == pid), "no lesson row for the gone program")
    drained(fx, 'lesson generation')


def scenario_program_approval_and_resume_finishing_after_start_write_nothing():
    import main
    from services import programs
    for verb in ('approve', 'resume'):
        fx = late_world()
        pid = _program(fx, 'GPX', 'kid', fx.projects['garage'])
        shape = {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}
        phases = [{'name': 'Grade 1', 'weeks': 4, 'what': 'You will need to buy a keyboard', 'steps': ['C scale'],
                   'milestone': 'm', 'milestone_hit_at': None}]
        storage.update_program(pid, {'state': 'proposed' if verb == 'approve' else 'paused', 'shape': shape, 'phases': phases,
                                     'emissions': {'commitment_ids': [], 'thread_ids': [], 'event_ids': []},
                                     'paused_slots': [{'day': 2, 'time_start': '17:00', 'time_end': '17:30'}]})
        seen = {}
        real = programs._kit_line if verb == 'approve' else programs.release_commitments
        name = '_kit_line' if verb == 'approve' else 'release_commitments'

        def hook(*args, _real=real, _fx=fx, _pid=pid, **kwargs):
            if not seen.get('fired'):
                seen['fired'] = True
                try:
                    delete_garage(_fx)
                    seen['active'] = _d().active('program', _pid)
                    seen['waiting'] = _d().maintain()['waiting']
                    seen['commitments'] = {c['id'] for c in storage.get_protected_commitments(include_inactive=True)}
                    seen['threads'] = {t['id'] for t in storage.get_threads(include_closed=True)}
                    seen['row'] = json.dumps(storage.get_program(_pid), sort_keys=True, default=str)
                except BaseException as exc:      # noqa: BLE001 -- re-raised by reached()
                    seen['error'] = exc
                    raise
            return _real(*args, **kwargs)
        with outside_world(), patch.object(programs, name, hook), \
                patch.object(main, 'trigger_background_refresh', lambda *a, **k: None):
            try:
                r = http('mom', 'POST', f'/api/programs/{pid}/{verb}', json={})
            except BaseException as exc:      # noqa: BLE001 -- reached() reports a deletion that could not start
                if seen.get('error') is None:
                    raise AssertionError(f"{verb}: Cancelled must never escape a route: {exc!r}") from exc
                r = None
        reached(seen, verb)
        check(r.status_code == 404, f"{verb}: work that hits Cancelled answers 404 like a missing record: "
                                    f"{r.status_code} {r.text[:200]}")
        check(seen['active'] and seen['waiting'] >= 1, f"{verb}: registered, and cleanup waited: {seen}")
        check({t['id'] for t in storage.get_threads(include_closed=True)} == seen['threads'], f"{verb}: no kit thread is created")
        check({c['id'] for c in storage.get_protected_commitments(include_inactive=True)} <= seen['commitments'],
              f"{verb}: no commitment is claimed after start")
        check(json.dumps(storage.get_program(pid), sort_keys=True, default=str) == seen['row'],
              f"{verb}: the program row is not written after start")
        drained(fx, verb)
        check(not [c for c in storage.get_protected_commitments(include_inactive=True)
                   if (c.get('source') or {}).get('id') == pid], f"{verb}: and cleanup leaves no commitment of it")


# --- watchers, replies, asks, situation refresh --------------------------------------------------

def _in_window():
    return datetime.datetime.combine(datetime.date.today(), datetime.time(10, 0))


def scenario_a_watcher_sweep_and_its_posting_say_nothing_of_a_gone_record():
    from services import watchers
    gone_words = words_of(late_world(), GARAGE_KEYS)
    for when in ('before the sweep', 'between collecting and posting'):
        fx = late_world()
        storage.update_mission(fx.ids['GM2'], {'status': 'waiting_user'})
        ids = closure_ids(fx)
        with outside_world():
            if when == 'before the sweep':
                delete_garage(fx)
                watchers.run_watchers(_in_window())
            else:
                real = watchers.collect_findings

                seen = {}

                def hooked(now=None, _real=real, _fx=fx):
                    out = _real(now)
                    seen['fired'] = True
                    try:
                        delete_garage(_fx)
                    except BaseException as exc:      # noqa: BLE001
                        seen['error'] = exc
                        raise
                    return out
                with patch.object(watchers, 'collect_findings', hooked):
                    try:
                        watchers.run_watchers(_in_window())
                    except BaseException:      # noqa: BLE001 -- reached() re-raises the start's own error
                        if seen.get('error') is None:
                            raise
                reached(seen, 'watchers')
        found = [f for f in storage.findings_table.all() if f.get('subject_id') in ids]
        check(not found, f"{when}: no finding is created or kept for a gone record: {found[:2]}")
        bodies = [m.get('body') or '' for m in storage.chat_messages_table.all()]
        check(not leaked(bodies, gone_words), f"{when}: no DM line names a gone record: {leaked(bodies, gone_words)}")
        check(any(fx.title('R5t') in b for b in bodies), f"{when}: the sweep still posts about the survivors")
        notified = storage.get_app_state('watcher_notified') or {}
        check(not [k for k in notified if any(i in k for i in ids)], f"{when}: nothing gone is marked notified: {notified}")
        props = [p for p in storage.agent_action_proposals_table.all()
                 if (p.get('payload') or {}).get('program_id') in ids]
        check(not props, f"{when}: no action card for a gone program: {props}")
        drained(fx, f'watchers {when}')


def scenario_a_reply_read_after_start_records_nothing_and_a_deferred_dm_never_goes():
    from services import replies, asks
    fx = late_world()
    tid = fx.ids['GT1']
    storage.append_thread_history(tid, {'kind': 'received', 'message_id': 'msg-1', 'ts': time.time(), 'who': None,
                                        'text': 'Received from Pest Co: yes, Tuesday works'})
    ask_id = asks.record_sent('thread', tid, {'name': 'Pest Co', 'email': 'p@example.com'}, 'Can you come Tuesday?',
                              'Tuesday', 'Can you come Tuesday?', 'mom')
    gate = Gate()
    with outside_world(), patch.object(replies, '_pool_call', lambda *a, **k: gate.wait() or {'answer': 'yes', 'summary': 'Tuesday works'}), \
            patch.object(replies, '_now', _in_window):
        w = Worker(replies.read, tid, 'msg-1')
        try:
            check(gate.entered.wait(15), "the reply reader was called")
            delete_garage(fx)
            waits_for(fx, 'thread', tid, 'reply reading')
            snap = mark(fx)
        finally:
            gate.release()
            w.thread.join(30)
        w.done('reply reading')
    nothing_since(fx, snap, 'reply reading')
    entry = next(h for h in storage.get_thread(tid)['history'] if h.get('message_id') == 'msg-1')
    check('reading' not in entry and 'dm_pending' not in entry, f"no reading lands on the gone thread: {entry}")
    check(storage.get_ask(ask_id)['state'] == 'sent', "and the ask records no answer")
    drained(fx, 'reply reading')

    fx = late_world()
    for key in ('GT1', 'R5t'):
        storage.append_thread_history(fx.ids[key], {'kind': 'received', 'message_id': 'late-' + key, 'ts': time.time(),
                                                    'text': f'Received from Pest Co: {fx.secret(key)}', 'dm_pending': True,
                                                    'reading': {'answer': 'info', 'summary': fx.secret(key)}})
    delete_garage(fx)
    with outside_world():
        posted = replies.flush_pending_dms(_in_window())
    bodies = [m.get('body') or '' for m in storage.chat_messages_table.all()]
    check(posted == 1 and any(fx.title('R5t') in b for b in bodies), f"the survivor's deferred DM goes: {posted}")
    check(not leaked(bodies, words_of(fx, GARAGE_KEYS)), "the gone thread's deferred DM never goes")
    drained(fx, 'deferred DM')


def scenario_an_ask_applied_after_start_changes_nothing():
    from services import asks
    fx = late_world()
    tid = fx.ids['GT1']
    ask_id = storage.add_ask({'situation_kind': 'thread', 'situation_id': tid, 'to_name': 'Pest Co', 'what': 'Tuesday?',
                              'channel': 'email', 'asked_by': 'mom', 'state': 'yes',
                              'unlocks': {'action_type': 'thread_advance',
                                          'payload': {'thread_id': tid, 'next_action': 'Book the late Tuesday'}}})
    seen = {}
    with outside_world(), _hooked(fx, asks, '_effect', ('thread', tid), seen):
        Worker(asks.apply, ask_id).done('ask application')
    reached(seen, 'ask application')
    check(seen['active'] and seen['maintain']['waiting'] >= 1, f"applying an ask is registered for its thread: {seen}")
    nothing_since(fx, seen['mark'], 'ask application')
    thread = storage.get_thread(tid)
    check(thread['next_action'] == fx.secret('GT1') and 'Book the late Tuesday' not in json.dumps(thread),
          f"the gone thread does not advance: {thread['next_action']}")
    check(storage.get_ask(ask_id).get('outcome') != 'applied', "the ask is not marked applied")
    with outside_world():
        Worker(asks.recover, _in_window() + datetime.timedelta(days=1)).done('ask recovery')
    check('Book the late Tuesday' not in json.dumps(storage.get_thread(tid)), "recovery applies nothing either")
    drained(fx, 'ask application')


def scenario_a_situation_refresh_timer_writes_no_note_on_a_gone_record():
    fx = late_world()
    tid = fx.ids['GT1']
    gate = Gate()

    def pool(tier, api_key, system, prompt, **kw):
        if fx.title('GT1') in prompt and not gate.entered.is_set():
            gate.wait()
            return {'status_note': 'LATE NOTE WORDS', 'options': []}
        return {}
    before = set(threading.enumerate())
    try:
        with outside_world(), patch.object(situations, '_pool_call', pool), patch.object(situations, 'REFRESH_DELAY_S', 0.2):
            situations.request_refresh('thread', tid)
            check(gate.entered.wait(10), "the timer fired and called the model")
            delete_garage(fx)
            waits_for(fx, 'thread', tid, 'refresh timer')
            snap = mark(fx)
            gate.release()
            settle(before)
            nothing_since(fx, snap, 'refresh timer')
            check('LATE NOTE WORDS' not in json.dumps(storage.get_thread(tid)), "no note lands")
            drained(fx, 'refresh timer')

            fx = late_world()
            tid = fx.ids['GT1']
            with patch.object(situations, 'REFRESH_DELAY_S', 0.6):
                before = set(threading.enumerate())
                situations.request_refresh('thread', tid)
                delete_garage(fx)
                check(_d().active('thread', tid), "a scheduled timer is registered before it fires")
                snap = mark(fx)
                time.sleep(1.0)
                settle(before)
                nothing_since(fx, snap, 'a timer scheduled before start')
            drained(fx, 'scheduled timer')
    finally:
        gate.release()


# --- queued deliveries -------------------------------------------------------------------------

def scenario_a_queued_push_fan_out_re_reads_the_message_before_sending():
    import main
    from models.schemas import ChatMessage
    fx = late_world()
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], 'mom')
    gone = ChatMessage(channel_id=dm['id'], sender_member_id=argyle['id'], body=fx.title('GM2'),
                       card={'kind': 'mission_ask', 'mission_id': fx.ids['GM2']}).model_dump()
    gone['refs'] = [{'kind': 'mission', 'id': fx.ids['GM2']}]
    kept = ChatMessage(channel_id=dm['id'], sender_member_id=argyle['id'], body='Survivor news',
                       card={'kind': 'mission_ask', 'mission_id': fx.ids['R9b']}).model_dump()
    for m in (gone, kept):
        storage.add_chat_message(m)
    delete_garage(fx)
    with outside_world():
        main._fanout_message_notifications(dm, gone)      # queued before the tap, sent after it
        main._fanout_message_notifications(dm, kept)
    bodies = [p.get('body') for p in PUSHES]
    check(bodies == ['Survivor news'], f"only the survivor's push goes out: {PUSHES}")


class _Stop(BaseException):
    pass


def _one_push_loop_pass():
    import asyncio
    import main

    async def stop(*a, **k):
        raise _Stop()
    key = os.path.join(tempfile.mkdtemp(prefix='vapid_'), 'vapid.pem')
    with open(key, 'w') as f:
        f.write('test')
    now = time.time()
    for marker in ('watchers_last_run', 'coverage_nudges_swept', 'runway_cues_swept', 'requests_swept',
                   'week_plan_last_run', 'status_sweep_last_run', 'presence_prompt_last_run'):
        storage.set_app_state(marker, now)
    with patch.object(main, 'VAPID_PRIVATE_KEY_PATH', key), patch.object(main.asyncio, 'sleep', stop):
        try:
            asyncio.run(main.push_notification_loop())
        except _Stop:
            pass


def scenario_a_practice_push_and_a_lesson_voice_timer_re_check_before_delivery():
    from services import programs, program_lessons
    fx = late_world()
    sp = _program(fx, 'SP1', 'dad', fx.projects['survivor'])
    frozen = datetime.datetime.combine(datetime.date.today(), datetime.time(12, 2))   # the clock, frozen at noon
    now = frozen - datetime.timedelta(minutes=2)
    hhmm, end = now.strftime('%H:%M'), (now + datetime.timedelta(minutes=30)).strftime('%H:%M')
    for key, member in (('GP1', 'kid'), ('SP1', 'dad')):
        cid = storage.add_protected_commitment({'id': uuid.uuid4().hex, 'member_id': member, 'title': fx.title(key),
                                                'days_of_week': [now.weekday()], 'time_start': hhmm, 'time_end': end,
                                                'active': True, 'source': {'kind': 'program', 'id': fx.ids[key]}})
        storage.update_program(fx.ids[key], {'state': 'active', 'phases': [
            {'name': 'P', 'weeks': 4, 'what': 'x', 'steps': [fx.title(key) + ' step'], 'milestone': 'm'}],
            'emissions': {'commitment_ids': [cid], 'event_ids': [],
                          'thread_ids': [fx.ids['GK1']] if key == 'GP1' else []}})
    for who, room, text, key in (('kid', 'Kitchen', 'Dough is ready', 'GP1'), ('dad', 'Office', 'Scales are done', 'SP1')):
        r = http(who, 'POST', '/api/lessons/wait', json={'room': room, 'text': text, 'minutes': 1, 'program_id': fx.ids[key]})
        check(r.status_code == 200, f"armed for {key}: {r.status_code} {r.text[:200]}")
    queue = storage.get_app_state(program_lessons.WAIT_STATE_KEY) or []
    check(len(queue) == 2 and all(e.get('program_id') for e in queue), f"each timer carries its program: {queue}")
    storage.set_app_state(program_lessons.WAIT_STATE_KEY, [dict(e, fire_ts=time.time() - 5) for e in queue])
    real = programs.due_practice_pushes

    seen = {}

    def due_then_delete(*a, **k):
        out = real(frozen)                                   # the loop's read, at the frozen clock
        seen['fired'] = True
        seen['due'] = {w.get('program_id') for w in out}
        try:
            delete_garage(fx)                                # the tap lands between the read and the send
        except BaseException as exc:      # noqa: BLE001 -- the loop swallows it; reached() re-raises it
            seen['error'] = exc
            raise
        return out
    with outside_world(), patch.object(programs, 'due_practice_pushes', due_then_delete):
        _one_push_loop_pass()
    reached(seen, 'practice push')
    check(seen['due'] >= {fx.ids['GP1'], sp}, f"the fixture: both windows were due before the tap: {seen['due']}")
    titles = json.dumps(PUSHES)
    check(fx.title('SP1') in titles, f"the survivor's practice push goes out: {PUSHES}")
    check(fx.title('GP1') not in titles and 'Practice time' not in titles, f"the gone program's push does not: {PUSHES}")
    said = [m for _, m in SPOKEN]
    check('Scales are done' in said and 'Dough is ready' not in said, f"only the survivor's timer speaks: {SPOKEN}")
    drained(fx, 'queued deliveries')


# --- creation bound at insert, children refused, no replacement wrapper ---------------------------

def scenario_nothing_new_is_created_inside_or_on_behalf_of_a_gone_record():
    from services import programs
    fx = late_world()
    delete_garage(fx)
    before = mark(fx)
    attempts = {
        'threads.create': lambda: threads.create(title='Late thread', owner_member_id='mom', created_by='mom',
                                                 project_id=garage(fx)),
        'missions.launch': lambda: missions.launch('late goal', origin_kind='thread', origin_ref=fx.ids['GT1'],
                                                   created_by='mom'),
        'programs.create_row': lambda: programs.create_row({'title': 'Late program', 'member_id': 'kid',
                                                            'state': 'proposed', 'created_by': 'mom'},
                                                           project_id=garage(fx)),
        'adopt a thread': lambda: projects.adopt('thread', fx.ids['GT1'], dict(MOM)),
        'adopt a mission': lambda: projects.adopt('mission', fx.ids['GM1'], dict(MOM)),
        'add_mission_step': lambda: storage.add_mission_step(fx.ids['GM2'], {'kind': 'note', 'name': 'late'}),
        'add_ask': lambda: storage.add_ask({'situation_kind': 'thread', 'situation_id': fx.ids['GT1'], 'what': 'late'}),
        'add_finding': lambda: storage.add_finding({'subject_type': 'thread', 'subject_id': fx.ids['GT1'], 'line': 'late'}),
        'upsert_program_lesson': lambda: storage.upsert_program_lesson(fx.ids['GP1'], {'phase_name': 'late'},
                                                                       {'scenes': [{'type': 'say', 'text': 'late'}]}),
        'add_protected_commitment': lambda: storage.add_protected_commitment({
            'id': 'late-c', 'member_id': 'kid', 'title': 'late', 'days_of_week': [1], 'time_start': '17:00',
            'time_end': '17:30', 'active': True, 'source': {'kind': 'program', 'id': fx.ids['GP1']}}),
        'add_action_proposal': lambda: storage.add_action_proposal({
            'action_type': 'create_list', 'summary': 'late', 'payload': {}, 'origin_kind': 'mission',
            'origin_id': fx.ids['GM2']}),
        'append_thread_history': lambda: storage.append_thread_history(fx.ids['GT1'], {'kind': 'note', 'text': 'late'}),
        'a chat message with a gone ref': lambda: storage.add_chat_message({
            'id': 'late-msg', 'channel_id': 'c', 'sender_member_id': 'argyle', 'ts': time.time(), 'body': 'late',
            'refs': [{'kind': 'thread', 'id': fx.ids['GT1']}]}),
    }
    for name, attempt in attempts.items():
        try:
            attempt()
        except Exception as exc:      # a refusal may raise or return; either way nothing may land
            if not isinstance(exc, (_d().Cancelled,)) and type(exc).__name__ not in ('Refused', 'ValueError', 'PermissionError'):
                print(f"  ({name} raised {type(exc).__name__}: {exc})")
        except BaseException as exc:  # noqa: BLE001 -- Cancelled may be a BaseException
            if not cancelled(exc):
                raise
    nothing_since(fx, before, 'creation after start')
    check(storage.get_thread(fx.ids['GT1'])['project_id'] == garage(fx), "adoption never re-homes a gone record")
    check(storage.get_chat_message('late-msg') is None, "a chat message carrying a gone ref is refused")
    check(not storage.get_protected_commitment('late-c'), "a commitment for a gone program is refused")
    drained(fx, 'creation')


# --- Review Focus 5: the worker that never exits ----------------------------------------------------

@contextlib.contextmanager
def _later(minutes):
    real_time, real_mono = time.time, time.monotonic
    with patch('time.time', lambda: real_time() + minutes * 60), patch('time.monotonic', lambda: real_mono() + minutes * 60):
        yield


def scenario_rf5_a_hung_worker_keeps_the_project_hidden_and_cleanup_waiting():
    from services import access
    fx = late_world()
    mid = fx.ids['GM2']
    storage.update_mission(mid, {'status': 'running'})
    gate = Gate()
    missions._browse = lambda **kw: gate.wait(timeout=300) or _report('done')
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'hang', 'site': 'bodewell.com'}
    missions._browse_async = True
    before = set(threading.enumerate())
    try:
        with outside_world():
            Worker(missions.tick).done('the turn that starts a browse that never returns')
            check(gate.entered.wait(10), "the browser was reached")
            delete_garage(fx)
            for _ in range(3):
                held = _d().maintain()
                check(held['waiting'] >= 1 and storage.get_mission(mid) is not None, f"cleanup keeps waiting: {held}")
            check(not access.project_visible(storage.get_project(garage(fx)), dict(MOM)) and
                  not access.project_visible(storage.get_project(garage(fx)), access.HOUSE), "the project stays hidden")
            out, records = io.StringIO(), []
            handler = logging.Handler()
            handler.emit = lambda record: records.append(record.getMessage())
            logging.getLogger().addHandler(handler)
            old_level = logging.getLogger().level
            logging.getLogger().setLevel(logging.DEBUG)
            try:
                with _later(16), contextlib.redirect_stdout(out):
                    held = _d().maintain()
            finally:
                logging.getLogger().removeHandler(handler)
                logging.getLogger().setLevel(old_level)
            check(held['waiting'] >= 1 and storage.get_mission(mid) is not None,
                  f"elapsed time never proves exit: still waiting after 16 minutes: {held}")
            logged = out.getvalue() + '\n'.join(records)
            check(mid in logged, f"the re-cancel is logged, naming the worker's source: {logged[-400:]}")
            r = http('mom', 'GET', '/api/projects')
            check(r.status_code == 200 and garage(fx) not in r.text, "and nothing else errors")
            snap = mark(fx)
    finally:
        gate.release()
        missions._browse_async = False
    settle(before)
    nothing_since(fx, snap, 'the hung worker, released at last')
    drained(fx, 'hung worker')


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:      # a leaked deletion.Cancelled must fail its scenario, not the file
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
