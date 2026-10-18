"""Projects delete, late work cannot write (spec rev 3 section 5, first half; plan Task 1 Step 3).

Each worker below is driven through its REAL entry point; only the outside world is stubbed: the
model, the browser runner, Google Calendar (a fake client behind `calendar.get_calendar_service`), the
research boundary (`programs_curate.curate`, `threads._web_research`), outgoing mail (the SMTP client
under `mailer`, with `mailer.configured` held when the deletion must land before anything leaves), web
push (`pywebpush.webpush`), HA notify and the room speaker (`announce.announce`). The deletion lands
while the worker is held inside that boundary. Each one, finishing after `start`, writes nothing,
creates nothing and delivers nothing (every row it could touch is compared in full), and cleanup
waits while it is registered.

Where a worker has NO outside call to be held in, the deletion is started at a pass-through hook
that then calls the real function. Four remain, each stated in its scenario as the contract Task 4
builds to: the hooked function must stay reached through its module attribute (module-global lookup),
never captured or imported by name.
  * `chat_actions._execute`  (a build-stage row: create_thread, add_trip_poi)
  * `programs._kit_line`     (program approval)
  * `programs.release_commitments` (program resume)
  * `programs.orphaned_emissions`  (the watchers' program mutation)

Paths with no reachable race at all are pinned at the nearest layer and named for Task 4:
`planned.reconcile`, program-session append, history-entry update, program claims, lesson
replacement and the app_voice card update.

  * `deletion.acting_for(kind, id)` registers work for a source and carries it in a context variable
    that `contextvars.copy_context()` transfers; `deletion.active(kind, id)` is True while registered;
    `deletion.check()` raises `deletion.Cancelled` once the source is gone and never outside a worker.
    A check and its local write happen under `storage.db_lock`, which `start` also takes.
  * A worker ends by returning or by raising Cancelled (every leaf of an exception group must be
    Cancelled). A route whose work hits Cancelled answers exactly as it does for a missing record.
  * Creation is bound at insert, storage refuses children of gone parents, adoption never makes a
    replacement wrapper, queued deliveries re-check just before they go out (push fan-out re-reads the
    stored message; practice pushes and voice timers re-check per delivery).
  * Review Focus 5: a worker that never exits keeps the project hidden, cleanup waits, a re-cancel is
    logged after 15 minutes of MONOTONIC time (the wall clock is not consulted), nothing else errors.

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
import types
import uuid
from unittest.mock import patch

from harness import check  # noqa: F401
from test_deletion_core import (_d, build, garage, start_ok, finish, http, in_fresh_context, words_of, leaked,
                                snapshot, GARAGE_KEYS, pair, LOAD)
from access_fixture import _program
from test_subjects import MOM
from services import storage, projects, missions, situations, threads

PUSHES, SPOKEN, INSERTS, MAILS = [], [], [], []
PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
       b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82')


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
    """deletion.Cancelled, alone or as EVERY leaf of an exception group (a real defect beside it fails)."""
    if isinstance(exc, _d().Cancelled):
        return True
    return isinstance(exc, BaseExceptionGroup) and all(cancelled(e) for e in exc.exceptions)


def settle(before, timeout=30):
    """Join every thread started since `before` (browse daemons, timers, fan-out)."""
    end = time.monotonic() + timeout
    for t in threading.enumerate():
        if t not in before and t is not threading.current_thread():
            t.join(max(0.1, end - time.monotonic()))


def _record_push(subscription_info=None, data=None, **_):
    payload = json.loads(data) if data else {}
    gate = BOUNDARY.get('push')
    if gate and BOUNDARY.get('push_when', '') in json.dumps(payload):
        gate.wait()
    PUSHES.append(payload)


def _record_speech(room, message):
    gate = BOUNDARY.get('speak')
    if gate and message == BOUNDARY.get('speak_when'):
        gate.wait()
    SPOKEN.append((room, message))
    return {'status': 'ok'}


class _FakeSMTP:
    """The SMTP server, at the socket boundary: mailer.send runs for real down to here."""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        if BOUNDARY.get('mail_send'):
            BOUNDARY['mail_send'].wait()               # the mail is on the wire
        MAILS.append((msg['To'], msg['Subject'], msg.get_content()))


_REAL_CONFIGURED = {}


def _mail_configured(settings=None):
    """mailer.configured, held when a scenario wants the deletion to land before anything leaves."""
    if BOUNDARY.get('mail_ready'):
        BOUNDARY['mail_ready'].wait()
    return _REAL_CONFIGURED['fn'](settings)


BOUNDARY = {}      # per-scenario gates on the outside world, cleared by late_world()


def install_outside_world():
    """The outside world, stubbed for this whole process: web push, HA notify, the room speaker, mail
    and Google Calendar are recorded, never reached, even by a worker that outlives its scenario."""
    import pywebpush
    from services import ha_api, announce, family_digest, calendar, mailer, model_pools, web
    pywebpush.webpush = _record_push
    ha_api.call_service = lambda *a, **k: PUSHES.append({'ha': a}) or True
    announce.announce = _record_speech
    family_digest.in_member_quiet_hours = lambda *a, **k: False
    calendar.get_calendar_service = lambda *a, **k: _FakeCalendar()
    _REAL_CONFIGURED.setdefault('fn', mailer.configured)
    mailer.configured = _mail_configured
    mailer.smtplib = types.SimpleNamespace(SMTP=_FakeSMTP, SMTP_SSL=_FakeSMTP)
    model_pools.call_pool_json = _no_model          # a scenario that needs the model patches its own
    web.read_page = lambda *a, **k: None
    web.research = lambda *a, **k: {'status': 'disabled'}


def _no_model(*a, **k):
    return {'error': 'no model in the deletion tests', 'transient': False}


def late_world():
    fx = build()
    base = storage.get_settings()
    extra = {'mission_step_cap': 60, 'mission_cap_pro_calls': 200, 'missions_enabled': True,
             'default_calendar_id': 'cal-' + uuid.uuid4().hex[:8], 'programs_enabled': True,
             'program_lessons_enabled': True, 'proactive_watchers_enabled': True, 'llm_gemini_api_key': 'k',
             'tomorrow_digest_enabled': False, 'kid_digest_enabled': False, 'weekly_digest_enabled': False,
             'smtp_host': 'smtp.example.com', 'smtp_user': 'house@example.com', 'smtp_password': 'x',
             'smtp_from': 'house@example.com'}
    storage.get_settings = (lambda s: (lambda: dict(s)))(dict(base, **extra))
    storage.agent_action_proposals_table.truncate()
    situations.REFRESH_DELAY_S = 0
    missions._browse_async = False
    install_outside_world()
    BOUNDARY.clear()
    PUSHES.clear(); SPOKEN.clear(); INSERTS.clear(); MAILS.clear()
    for member, driver in (('mom', 'd_mom'), ('dad', 'd_dad'), ('kid', 'd_kid')):
        storage.update_member(member, {'driver_id': driver})
        storage.save_push_subscription(driver, {'endpoint': f'https://push.example/{member}',
                                                'keys': {'p256dh': 'x', 'auth': 'y'}}, member_id=member)
    return fx


@contextlib.contextmanager
def outside_world():
    """A marker of where the outside world is touched; install_outside_world() did the work."""
    yield


def closure_ids(fx):
    return {fx.ids[k] for k in GARAGE_KEYS} | {garage(fx)}


def mark(fx, extra_missions=()):
    """Everything a late worker could write, create or deliver: whole rows, never ids or counts."""
    return {**snapshot(), 'pushes': json.dumps(PUSHES, sort_keys=True), 'spoken': list(SPOKEN),
            'google': json.dumps(INSERTS, sort_keys=True, default=str), 'mail': list(MAILS)}


def nothing_since(fx, before, how, extra_missions=()):
    after = mark(fx)
    for key in before:
        if before[key] != after[key]:
            if isinstance(before[key], list) and before[key] and isinstance(before[key][0], str):
                was, now = set(before[key]) - set(after[key]), set(after[key]) - set(before[key])
                check(False, f"{how}: the late worker changed {key}:\n  was {sorted(was)[:2]}\n  now {sorted(now)[:2]}")
            check(False, f"{how}: the late worker changed {key}: {before[key]!r:.300} -> {after[key]!r:.300}")


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


def like_missing(r, who, method, missing_path, how, **kwargs):
    """A route whose work hit Cancelled answers exactly as it does for a record that never existed."""
    missing = http(who, method, missing_path, **kwargs)
    check(r is not None and r.status_code == missing.status_code and r.json() == missing.json(),
          f"{how}: answered {r.status_code if r is not None else None} {r.text[:160] if r is not None else ''}; "
          f"a missing record answers {missing.status_code} {missing.text[:160]}")


def _report(outcome, **kw):
    base = {'outcome': outcome, 'text': kw.pop('text', outcome), 'learned': {}, 'stopped_at': 'https://bodewell.com/x',
            'wanted_fields': [], 'turns': 3, 'tokens_in': 10, 'tokens_out': 5, 'seconds': 3.0, 'screenshots': [],
            'filled': {}, 'submit': None, 'attempt': None, 'changed': [], 'attempts_extra': []}
    return {**base, **kw}


def gated(how, fx, worker, gate, source, extra=None):
    """Run `worker` until it is held in `gate`, delete the Garage, check registration, release, join.
    Returns (worker result, the mark taken right after the deletion started)."""
    w = Worker(worker)
    try:
        if not gate.entered.wait(15):
            w.done(how, timeout=1)                         # a worker that failed first reports its own error
            check(False, f"{how}: the worker reached its outside call")
        delete_garage(fx)
        waits_for(fx, *source, how)
        snap = mark(fx)
    finally:
        gate.release()
        w.thread.join(30)
    return w.done(how), snap


# --- the contract of acting_for, check and the lock ----------------------------------------------

def scenario_acting_for_registers_carries_and_cancels():
    fx = late_world()
    d, tid = _d(), fx.ids['GT1']
    check(not d.active('thread', tid), "nothing is registered before the work starts")
    d.check()                                              # outside any worker: never raises
    box, entered, go = {}, threading.Event(), threading.Event()

    def probe(name):
        try:
            d.check()
            box[name] = 'passed'
        except d.Cancelled:
            box[name] = 'cancelled'

    def worker():
        with d.acting_for('thread', tid):
            box['active'] = d.active('thread', tid)
            probe('alive')
            entered.set()
            go.wait(15)
            probe('gone')
            ctx = contextvars.copy_context()
            for name, runner in (('copied', lambda: ctx.run(probe, 'copied')),
                                 ('fresh', lambda: contextvars.Context().run(probe, 'fresh'))):
                t = threading.Thread(target=runner)
                t.start()
                t.join(10)
            timer = threading.Timer(0.01, lambda: ctx.run(probe, 'timer'))
            timer.start()
            timer.join(10)
    w = Worker(worker)
    if not entered.wait(15):
        w.done('acting_for', timeout=1)
        check(False, "the worker started")
    delete_garage(fx)
    go.set()
    w.done('acting_for')
    check(box.get('active') is True and box.get('alive') == 'passed', f"registered, and a live source passes: {box}")
    check(box.get('gone') == 'cancelled', f"once the source is gone, check() raises Cancelled: {box}")
    check(box.get('copied') == 'cancelled' and box.get('timer') == 'cancelled',
          f"the source travels into a thread or timer through copy_context(): {box}")
    check(box.get('fresh') == 'passed', f"a thread started without the context carries no source: {box}")
    check(not d.active('thread', tid), "the registration ends with the work")
    drained(fx, 'acting_for')


def scenario_a_write_under_the_lock_and_the_deletions_admission_are_serialised():
    """Spec section 5: a check and its local write happen under storage.db_lock together with the
    deletion's admission (start takes the same lock). A write that holds the lock lands before the
    deletion is admitted; once admitted, the next write is refused."""
    fx = late_world()
    d, mid = _d(), fx.ids['GM2']
    holding, release_lock, admitted, box = threading.Event(), threading.Event(), threading.Event(), {}

    def writer():
        with d.acting_for('mission', mid):
            with storage.db_lock:
                storage.update_mission(mid, {'summary': 'written before the tap'})
                holding.set()
                release_lock.wait(15)
                storage.update_mission(mid, {'summary': 'still before the tap'})
            admitted.wait(15)
            try:
                storage.update_mission(mid, {'summary': 'after the tap'})
            except d.Cancelled:
                box['cancelled'] = True
    w = Worker(writer)
    if not holding.wait(15):
        w.done('the lock writer', timeout=1)
        check(False, "the writer holds the lock")
    starter = threading.Thread(target=lambda: box.update(start=contextvars.Context().run(
        start_ok, 'project', garage(fx), dict(MOM))), daemon=True)
    starter.start()
    starter.join(0.7)
    check(starter.is_alive() and 'start' not in box, "start waits for the lock a writer holds")
    release_lock.set()
    starter.join(15)
    check(box.get('start', {}).get('status') == 'ok', f"then it is admitted: {box}")
    admitted.set()
    w.done('the lock writer')
    check(storage.get_mission(mid)['summary'] == 'still before the tap',
          f"the write after admission never lands: {storage.get_mission(mid)['summary']!r}")
    drained(fx, 'admission')


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


def _hooked(fx, target, name, source, seen):
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
                seen['mark'] = mark(fx)
            except BaseException as exc:      # noqa: BLE001 -- re-raised by reached()
                seen['error'] = exc
                raise
        return real(*args, **kwargs)
    return patch.object(target, name, hook)


def reached(seen, how):
    """The hook fired, and the deletion it started did start (else its own error is the failure)."""
    check(seen.get('fired'), f"{how}: the worker reached the hook (it must call the function through its module)")
    if seen.get('error') is not None:
        raise seen['error']


def scenario_a_build_stage_row_that_runs_after_start_creates_nothing():
    """HOOK CONTRACT (Task 4): the stage runner reaches the row's tool through `chat_actions._execute`,
    looked up on the module at call time. create_thread and add_trip_poi make no outside call, so the
    deletion lands at that hook; the tool's own insert or update must then be refused by check()."""
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
        with _hooked(fx, chat_actions, '_execute', ('mission', mid), seen):
            Worker(_run_stage, mid, st).done(tool)
        reached(seen, tool)
        check(seen['active'] and seen['maintain']['waiting'] >= 1, f"{tool}: the stage was registered and cleanup waited: {seen}")
        nothing_since(fx, seen['mark'], tool)
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
    with patch.object(programs_curate, 'curate', lambda *a, **k: gate.wait() or curated):
        _, snap = gated('propose_program', fx, lambda: _run_stage(mid, st), gate, ('mission', mid))
    nothing_since(fx, snap, 'propose_program')
    check(not any(p.get('title') == 'Late piano' for p in storage.get_programs(include_finished=True)), "no program row")
    drained(fx, 'propose_program')


class _FakeCalendar:
    """Google Calendar, at the client: the timezone lookup can be held (BOUNDARY['calendar']); inserts recorded."""

    def calendars(self):
        class _Get:
            def get(self, calendarId=None):
                class _Exec:
                    def execute(self_inner):
                        if BOUNDARY.get('calendar'):
                            BOUNDARY['calendar'].wait()
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
    gate = BOUNDARY['calendar'] = Gate()
    _, snap = gated('create_event', fx, lambda: _run_stage(mid, st), gate, ('mission', mid))
    check(INSERTS == [], f"nothing is inserted at Google after the source is gone: {INSERTS}")
    nothing_since(fx, snap, 'create_event')
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
    missions._llm = lambda m, s, u, st: gate.wait() or {'action': 'ask_user', 'question': 'Which bakery, late?'}
    _, snap = gated('work stage', fx, missions.tick, gate, ('mission', mid))
    nothing_since(fx, snap, 'work stage')
    drained(fx, 'work stage')


# --- programs: lessons, approval, resume, the watchers' mutation -----------------------------------

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
    with patch.object(model_pools, 'call_pool_json', lambda *a, **k: gate.wait() or script):
        _, snap = gated('lesson generation', fx, program_lessons.generate_due, gate, ('program', pid))
    nothing_since(fx, snap, 'lesson generation')
    check(not storage.program_lessons_table.search(storage.Query().program_id == pid), "no lesson row for the gone program")
    drained(fx, 'lesson generation')


def scenario_program_approval_and_resume_finishing_after_start_write_nothing():
    """HOOK CONTRACT (Task 4): approval and resume make no outside call. The deletion lands at
    `programs._kit_line` (approve) and `programs.release_commitments` (resume), which approve() and
    resume() must keep calling through the module. The route then answers as for a missing program."""
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
        name = '_kit_line' if verb == 'approve' else 'release_commitments'
        with _hooked(fx, programs, name, ('program', pid), seen), \
                patch.object(main, 'trigger_background_refresh', lambda *a, **k: None):
            try:
                r = http('mom', 'POST', f'/api/programs/{pid}/{verb}', json={})
            except BaseException as exc:      # noqa: BLE001
                if seen.get('error') is None:
                    raise AssertionError(f"{verb}: Cancelled must never escape a route: {exc!r}") from exc
                r = None
        reached(seen, verb)
        like_missing(r, 'mom', 'POST', f'/api/programs/{uuid.uuid4().hex}/{verb}', verb, json={})
        check(seen['active'] and seen['maintain']['waiting'] >= 1, f"{verb}: registered, and cleanup waited: {seen}")
        nothing_since(fx, seen['mark'], verb)
        drained(fx, verb)
        check(not [c for c in storage.get_protected_commitments(include_inactive=True)
                   if (c.get('source') or {}).get('id') == pid], f"{verb}: and cleanup leaves no commitment of it")


def _in_window():
    return datetime.datetime.combine(datetime.date.today(), datetime.time(10, 0))


def scenario_the_watchers_program_mutation_after_start_writes_nothing():
    """HOOK CONTRACT (Task 4): the watchers' program check reads `programs.orphaned_emissions` through the
    module; the deletion lands right after it, and `forget_emissions` (a program mutation, in the
    program's acting_for) must then write nothing: no emissions change, no drift finding, no card."""
    from services import watchers, programs
    fx = late_world()
    pid = fx.ids['GP1']
    storage.update_program(pid, {'state': 'active', 'emissions': {'commitment_ids': ['a-commitment-long-gone'],
                                                                  'thread_ids': [fx.ids['GK1']], 'event_ids': []}})
    check(programs.orphaned_emissions(storage.get_program(pid)), "the fixture: the program has orphaned emissions")
    seen = {}
    with _hooked(fx, programs, 'orphaned_emissions', ('program', pid), seen):
        try:
            watchers.run_watchers(_in_window())
        except BaseException as exc:      # noqa: BLE001
            if seen.get('error') is None and not cancelled(exc):
                raise
    reached(seen, 'watchers program mutation')
    check(seen['active'], f"the mutation is registered for its program: {seen}")
    check(storage.get_program(pid)['emissions']['commitment_ids'] == ['a-commitment-long-gone'],
          "forget_emissions wrote nothing")
    check(not [f for f in storage.findings_table.all() if f.get('subject_id') == pid], "no drift finding")
    check(not [p for p in storage.agent_action_proposals_table.all() if (p.get('payload') or {}).get('program_id') == pid],
          "no re-shape card")
    drained(fx, 'watchers program mutation')


# --- watchers, replies, asks, situation refresh --------------------------------------------------

def scenario_a_watcher_sweep_and_its_posting_say_nothing_of_a_gone_record():
    """Before the sweep, and between collecting and posting: the deletion lands while the sweep is held in
    its prep-kit model call, which run_watchers makes after collecting and before reconciling and posting."""
    from services import watchers, model_pools
    gone_words = words_of(late_world(), GARAGE_KEYS)
    for when in ('before the sweep', 'between collecting and posting'):
        fx = late_world()
        storage.update_mission(fx.ids['GM2'], {'status': 'waiting_user'})
        ids = closure_ids(fx)
        if when == 'before the sweep':
            delete_garage(fx)
            watchers.run_watchers(_in_window())
        else:
            gate = Gate()
            with patch.object(model_pools, 'call_pool_json', lambda *a, **k: gate.wait() or {'error': 'held'}):
                w = Worker(watchers.run_watchers, _in_window())
                try:
                    check(gate.entered.wait(15), "the sweep reached its prep-kit model call after collecting")
                    delete_garage(fx)
                finally:
                    gate.release()
                    w.thread.join(30)
                w.done('watchers')
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
    with patch.object(replies, '_pool_call', lambda *a, **k: gate.wait() or {'answer': 'yes', 'summary': 'Tuesday works'}), \
            patch.object(replies, '_now', _in_window):
        _, snap = gated('reply reading', fx, lambda: replies.read(tid, 'msg-1'), gate, ('thread', tid))
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
    posted = replies.flush_pending_dms(_in_window())
    bodies = [m.get('body') or '' for m in storage.chat_messages_table.all()]
    check(posted == 1 and any(fx.title('R5t') in b for b in bodies), f"the survivor's deferred DM goes: {posted}")
    check(not leaked(bodies, words_of(fx, GARAGE_KEYS)), "the gone thread's deferred DM never goes")
    drained(fx, 'deferred DM')


def scenario_an_ask_applied_after_start_changes_nothing():
    """The ask's promised work is approving a create_event proposal, so its effect talks to Google: the
    deletion lands while the effect is held there, and the insert must then be refused."""
    from services import asks, chat_actions
    fx = late_world()
    tid = fx.ids['GT1']
    prop = chat_actions.create_action_proposal('create_event', 'Late appointment',
                                               {'title': 'Late appointment', 'start': '2027-01-12T09:00:00',
                                                'end': '2027-01-12T10:00:00'}, created_by_member_id='mom')
    ask_id = storage.add_ask({'situation_kind': 'thread', 'situation_id': tid, 'to_name': 'Pest Co', 'what': 'Tuesday?',
                              'channel': 'email', 'asked_by': 'mom', 'state': 'yes',
                              'unlocks': {'action_type': 'approve_proposal', 'payload': {'proposal_id': prop['proposal_id']}}})
    gate = BOUNDARY['calendar'] = Gate()
    _, snap = gated('ask application', fx, lambda: asks.apply(ask_id), gate, ('thread', tid))
    check(INSERTS == [], f"the gone thread's ask inserts nothing at Google: {INSERTS}")
    nothing_since(fx, snap, 'ask application')
    BOUNDARY.pop('calendar')
    Worker(asks.recover, _in_window() + datetime.timedelta(days=1)).done('ask recovery')
    check(INSERTS == [] and storage.get_ask(ask_id).get('outcome') != 'applied', "recovery applies nothing either")
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
        with patch.object(situations, '_pool_call', pool), patch.object(situations, 'REFRESH_DELAY_S', 0.2):
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


# --- request-driven thread work and direct proposal execution --------------------------------------

def _route(fx, how, method, path, gate, source, **kwargs):
    """A request held in its outside call while the deletion lands; it answers like a missing record."""
    r, snap = gated(how, fx, lambda: http('mom', method, path, **kwargs), gate, source)
    return r, snap


def scenario_request_driven_thread_draft_research_and_photo_write_nothing():
    fx = late_world()
    tid = fx.ids['GT1']
    bogus = uuid.uuid4().hex
    # draft: held in the model
    gate = Gate()
    with patch.object(threads, '_pool_call', lambda *a, **k: gate.wait() or {'subject': 'Late', 'body': 'Late words'}):
        r, snap = _route(fx, 'draft', 'POST', f'/api/threads/{tid}/draft', gate, ('thread', tid), json={'intent': 'a quote'})
    nothing_since(fx, snap, 'draft')
    like_missing(r, 'mom', 'POST', f'/api/threads/{bogus}/draft', 'draft', json={'intent': 'a quote'})
    drained(fx, 'draft')
    # research: held in the web research
    fx = late_world()
    tid = fx.ids['GT1']
    gate = Gate()
    found = {'status': 'ok', 'answer': 'About ninety dollars', 'sources': [{'url': 'https://example.com/a'}],
             'facts': [{'text': 'ninety', 'url': 'https://example.com/a'}]}
    with patch.object(threads, '_web_research', lambda q: gate.wait() or found):
        r, snap = _route(fx, 'research', 'POST', f'/api/threads/{tid}/research', gate, ('thread', tid),
                         json={'question': 'How much?'})
    nothing_since(fx, snap, 'research')
    like_missing(r, 'mom', 'POST', f'/api/threads/{bogus}/research', 'research', json={'question': 'How much?'})
    drained(fx, 'research')
    # photo: the bytes are stored, then the photo is read by the model; held there
    fx = late_world()
    tid = fx.ids['GT1']
    gate = Gate()
    with patch.object(threads, '_pool_call', lambda *a, **k: gate.wait() or {'text': 'a receipt for ninety dollars'}):
        r, snap = _route(fx, 'photo', 'POST', f'/api/threads/{tid}/photo', gate, ('thread', tid),
                         files={'file': ('p.png', PNG, 'image/png')})
    nothing_since(fx, snap, 'photo')
    like_missing(r, 'mom', 'POST', f'/api/threads/{bogus}/photo', 'photo', files={'file': ('p.png', PNG, 'image/png')})
    drained(fx, 'photo')


def scenario_a_send_checks_before_the_mail_goes_and_discards_an_in_flight_result():
    fx = late_world()
    tid = fx.ids['GT1']
    bogus = uuid.uuid4().hex
    body = {'subject': 'Quote', 'body': 'Could you quote it?', 'to': 'pest@example.com'}
    gate = BOUNDARY['mail_ready'] = Gate()                  # held before anything leaves
    r, snap = _route(fx, 'send (before)', 'POST', f'/api/threads/{tid}/send', gate, ('thread', tid), json=body)
    check(MAILS == [], f"the check before outgoing mail stops it: {MAILS}")
    nothing_since(fx, snap, 'send (before)')
    BOUNDARY.pop('mail_ready')
    like_missing(r, 'mom', 'POST', f'/api/threads/{bogus}/send', 'send (before)', json=body)
    drained(fx, 'send (before)')

    fx = late_world()
    tid = fx.ids['GT1']
    gate = BOUNDARY['mail_send'] = Gate()                   # the mail is already on its way
    r, snap = _route(fx, 'send (in flight)', 'POST', f'/api/threads/{tid}/send', gate, ('thread', tid), json=body)
    check(len(MAILS) == 1, "a request already in flight to the outside service completes (accepted gap)")
    snap['mail'] = list(MAILS)                              # ... and that is all that happens
    nothing_since(fx, snap, 'send (in flight)')
    BOUNDARY.pop('mail_send')
    like_missing(r, 'mom', 'POST', f'/api/threads/{bogus}/send', 'send (in flight)', json=body)
    drained(fx, 'send (in flight)')


def scenario_a_directly_approved_proposal_from_a_gone_mission_inserts_nothing():
    from services import chat_actions
    fx = late_world()
    mid = fx.ids['GM2']
    prop = chat_actions.create_action_proposal(
        'create_event', 'Late event', {'title': 'Late event', 'start': '2027-01-10T10:00:00', 'end': '2027-01-10T11:00:00'},
        created_by_member_id='mom', extra={'origin_kind': 'mission', 'origin_id': mid})
    gate = BOUNDARY['calendar'] = Gate()
    r, snap = _route(fx, 'proposal', 'POST', f"/api/action-proposals/{prop['proposal_id']}/act", gate, ('mission', mid),
                     json={'act': 'approve', 'member_id': 'mom'})
    check(INSERTS == [], f"nothing is inserted at Google: {INSERTS}")
    nothing_since(fx, snap, 'proposal')
    BOUNDARY.pop('calendar')
    like_missing(r, 'mom', 'POST', f'/api/action-proposals/{uuid.uuid4().hex}/act', 'proposal', json={'act': 'approve', 'member_id': 'mom'})
    drained(fx, 'proposal')


# --- paths with no outside call: the nearest layer (named for Task 4) --------------------------------

def scenario_planned_reconcile_after_start_writes_nothing():
    """NEAREST LAYER (Task 4): reconcile has no outside call to be held in. A build stage left `running`
    by a crashed runner would be marked uncertain with a stage_check ask; after start it must not be."""
    from services import planned
    fx = late_world()
    mid, st = _staged_in_garage(fx, [{'id': 'r1', 'tool': 'create_list', 'args': {'name': 'Late list'}, 'summary': 'A list'}])
    plan = storage.get_mission(mid)['plan']
    plan['stages'][0]['state'] = 'running'
    plan['stages'][0]['rows'][0]['state'] = 'running'
    storage.update_mission(mid, {'plan': plan})
    delete_garage(fx)
    snap = mark(fx)
    planned.reconcile()
    nothing_since(fx, snap, 'reconcile')
    drained(fx, 'reconcile')


def scenario_raw_writers_refuse_a_gone_parent():
    """NEAREST LAYER (Task 4): the raw-table writers spec section 5 moves behind checked helpers:
    program-session append, history-entry update, program claims, lesson replacement."""
    from services import programs
    fx = late_world()
    gp1, tid = fx.ids['GP1'], fx.ids['GT1']
    storage.update_program(gp1, {'state': 'active'})
    slot = {'phase_name': 'Grade 1', 'unit_n': 0, 'session_label': ''}
    storage.upsert_program_lesson(gp1, slot, {'scenes': [{'type': 'say', 'text': 'the first script'}]})
    gpx = _program(fx, 'GPX', 'kid', fx.projects['garage'])
    storage.update_program(gpx, {'state': 'proposed'})
    entered, go = threading.Event(), threading.Event()
    box = {}

    def worker():
        d = _d()
        with d.acting_for('thread', tid):
            with d.acting_for('program', gp1):
                entered.set()
                go.wait(15)
                for name, write in (
                        ('history entry update', lambda: storage.update_thread_history_entry(
                            tid, {'kind': 'opened'}, {'text': 'rewritten late'})),
                        ('program session append', lambda: storage.append_program_session(gp1, {'minutes': 5})),
                        ('lesson replacement', lambda: storage.upsert_program_lesson(
                            gp1, slot, {'scenes': [{'type': 'say', 'text': 'a late script'}]})),
                        ('program claim', lambda: storage.claim_program(gpx, 'proposed', 'approving'))):
                    try:
                        box[name] = write()
                    except d.Cancelled:
                        box[name] = 'cancelled'
    w = Worker(worker)
    if not entered.wait(15):
        w.done('raw writers', timeout=1)
        check(False, "the worker holds its sources")
    delete_garage(fx)
    snap = mark(fx)
    go.set()
    w.done('raw writers')
    nothing_since(fx, snap, 'raw writers')
    check(not box.get('program claim') or box['program claim'] == 'cancelled', f"no claim on a gone program: {box}")
    r = http('kid', 'POST', f'/api/programs/{gp1}/session', json={'minutes': 5})
    check(r.status_code == 404, f"a session logged by hand on a gone program is a 404: {r.status_code}")
    r = http('mom', 'PUT', f'/api/programs/{gp1}/lesson', json={**slot, 'scenes': [{'type': 'say', 'text': 'by hand'}]})
    check(r.status_code == 404, f"a hand edit of a gone program's lesson is a 404: {r.status_code}")
    programs.log_session(gp1, minutes=5)                   # the helper, with no worker around it
    nothing_since(fx, snap, 'raw writers by hand')
    drained(fx, 'raw writers')


def scenario_the_app_voice_card_update_on_behalf_of_a_gone_record_writes_nothing():
    """NEAREST LAYER (Task 4): app_voice.run rewrites the transcript message's phone_speech_safe with a raw
    table update after the agent answers. Run on behalf of a mission (its acting_for), with the agent
    starting the deletion, that update must not land."""
    from services import app_voice
    fx = late_world()
    mid = fx.ids['GM2']
    dm = storage.get_or_create_dm('mom', 'argyle')
    storage.ensure_argyle_member()
    from models.schemas import ChatMessage
    earlier = ChatMessage(channel_id=dm['id'], sender_member_id='argyle', body='Earlier, spoken').model_dump()
    earlier['phone_speech_safe'] = True
    storage.add_chat_message(earlier)
    token = storage.create_member_token('mom')
    turn = app_voice.begin(storage.get_member('mom'), token, 'voice-' + uuid.uuid4().hex[:20], channel_id=dm['id'])
    turn.text('What is next on the garage?')
    box = {}

    def agent(channel, member, transcript):
        delete_garage(fx)
        box['mark'] = mark(fx)
        return {'status': 'success', 'message': 'Done.'}

    def run():
        with _d().acting_for('mission', mid):
            return app_voice.run(turn, agent)
    Worker(run).done('app_voice')
    check('mark' in box, "the agent ran")
    nothing_since(fx, box['mark'], 'app_voice card update')
    drained(fx, 'app_voice')


# --- queued deliveries -------------------------------------------------------------------------

def scenario_a_queued_push_fan_out_re_reads_the_stored_message():
    import main
    from models.schemas import ChatMessage
    fx = late_world()
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], 'mom')

    def queued(body):
        m = ChatMessage(channel_id=dm['id'], sender_member_id=argyle['id'], body=body).model_dump()
        storage.add_chat_message(m)
        return m
    changed, removed, kept = queued('Queued, then changed'), queued('Queued, then removed'), queued('Survivor news')
    delete_garage(fx)
    storage.chat_messages_table.update({'refs': [{'kind': 'mission', 'id': fx.ids['GM2']}]},
                                       storage.Query().id == changed['id'])         # storage now names a gone record
    storage.delete_chat_message(removed['id'])                                      # storage no longer holds it
    for m in (changed, removed, kept):                       # the queued copies, as captured before
        main._fanout_message_notifications(dm, m)
    bodies = [p.get('body') for p in PUSHES]
    check(bodies == ['Survivor news'], f"delivery follows the stored message, not the queued copy: {PUSHES}")


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


def _frozen_programs_clock(frozen):
    """The programs module's clock, frozen (its windows read datetime.datetime.now())."""
    class Frozen(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen
    return types.SimpleNamespace(datetime=Frozen, date=datetime.date, time=datetime.time, timedelta=datetime.timedelta)


def scenario_a_practice_push_re_checks_each_window_before_it_goes():
    """The survivor's window starts a minute earlier, so its push goes first; the deletion lands while that
    push is held at the web-push boundary; the gone program's window, read before the tap, must not go."""
    from services import programs
    fx = late_world()
    sp = _program(fx, 'SP1', 'dad', fx.projects['survivor'])
    frozen = datetime.datetime.combine(datetime.date.today(), datetime.time(12, 2))
    for key, member, start in (('SP1', 'dad', '12:00'), ('GP1', 'kid', '12:01')):
        cid = storage.add_protected_commitment({'id': uuid.uuid4().hex, 'member_id': member, 'title': fx.title(key),
                                                'days_of_week': [frozen.weekday()], 'time_start': start, 'time_end': '12:30',
                                                'active': True, 'source': {'kind': 'program', 'id': fx.ids[key]}})
        storage.update_program(fx.ids[key], {'state': 'active', 'phases': [
            {'name': 'P', 'weeks': 4, 'what': 'x', 'steps': [fx.title(key) + ' step'], 'milestone': 'm'}],
            'emissions': {'commitment_ids': [cid], 'event_ids': [],
                          'thread_ids': [fx.ids['GK1']] if key == 'GP1' else []}})
    with patch.object(programs, 'datetime', _frozen_programs_clock(frozen)):
        due = programs.due_practice_pushes()
        check([w['program_id'] for w in due] == [sp, fx.ids['GP1']], f"the fixture: both due, the survivor first: {due}")
        gate = BOUNDARY['push'] = Gate()
        BOUNDARY['push_when'] = fx.title('SP1')
        w = Worker(_one_push_loop_pass)
        try:
            check(gate.entered.wait(30), "the survivor's push is on its way")
            delete_garage(fx)
        finally:
            gate.release()
            w.thread.join(60)
        w.done('practice push')
    titles = json.dumps(PUSHES)
    check(fx.title('SP1') in titles, f"the survivor's practice push goes out: {PUSHES}")
    check(fx.title('GP1') not in titles and 'Practice time' not in titles, f"the gone program's push does not: {PUSHES}")
    drained(fx, 'practice push')


def scenario_a_lesson_voice_timer_re_checks_after_it_is_dequeued():
    """Both timers are dequeued in one read; the survivor's speaks first and is held at the speaker while
    the deletion lands; the gone program's timer, already dequeued, must not speak."""
    from services import program_lessons
    fx = late_world()
    sp = _program(fx, 'SP1', 'dad', fx.projects['survivor'])
    for who, room, text, pid in (('dad', 'Office', 'Scales are done', sp), ('kid', 'Kitchen', 'Dough is ready', fx.ids['GP1'])):
        r = http(who, 'POST', '/api/lessons/wait', json={'room': room, 'text': text, 'minutes': 1, 'program_id': pid})
        check(r.status_code == 200, f"armed: {r.status_code} {r.text[:200]}")
    queue = storage.get_app_state(program_lessons.WAIT_STATE_KEY) or []
    check([e.get('program_id') for e in queue] == [sp, fx.ids['GP1']], f"each timer carries its program: {queue}")
    storage.set_app_state(program_lessons.WAIT_STATE_KEY, [dict(e, fire_ts=time.time() - 5) for e in queue])
    gate = BOUNDARY['speak'] = Gate()
    BOUNDARY['speak_when'] = 'Scales are done'
    w = Worker(_one_push_loop_pass)
    try:
        check(gate.entered.wait(30), "the survivor's call is being spoken")
        check(not storage.get_app_state(program_lessons.WAIT_STATE_KEY), "both timers were dequeued already")
        delete_garage(fx)
    finally:
        gate.release()
        w.thread.join(60)
    w.done('voice timer')
    said = [m for _, m in SPOKEN]
    check(said == ['Scales are done'], f"only the survivor's timer speaks: {SPOKEN}")
    drained(fx, 'voice timer')


# --- creation bound at insert, children refused, no replacement wrapper ---------------------------

def scenario_nothing_new_is_created_inside_or_on_behalf_of_a_gone_record():
    from services import programs
    fx = late_world()
    survivor = fx.projects['survivor']['id']
    live, gone = {}, {}
    pairs = [
        ('threads.create',
         lambda: threads.create(title='Live thread', owner_member_id='mom', created_by='mom', project_id=survivor),
         lambda: threads.create(title='Late thread', owner_member_id='mom', created_by='mom', project_id=garage(fx)),
         lambda: [t for t in storage.get_threads(include_closed=True) if t['title'] == 'Live thread']),
        ('missions.launch',
         lambda: missions.launch('live goal', origin_kind='thread', origin_ref=fx.ids['R5t'], created_by='mom'),
         lambda: missions.launch('late goal', origin_kind='thread', origin_ref=fx.ids['GT1'], created_by='mom'),
         lambda: [m for m in storage.get_missions() if m.get('goal') == 'live goal']),
        ('programs.create_row',
         lambda: programs.create_row({'title': 'Live program', 'member_id': 'kid', 'state': 'proposed',
                                      'created_by': 'mom'}, project_id=survivor),
         lambda: programs.create_row({'title': 'Late program', 'member_id': 'kid', 'state': 'proposed',
                                      'created_by': 'mom'}, project_id=garage(fx)),
         lambda: [p for p in storage.get_programs(include_finished=True) if p.get('title') == 'Live program']),
        ('add_mission_step',
         lambda: storage.add_mission_step(fx.ids['R9b'], {'kind': 'note', 'name': 'live'}),
         lambda: storage.add_mission_step(fx.ids['GM2'], {'kind': 'note', 'name': 'late'}),
         lambda: [s for s in storage.get_mission_steps(fx.ids['R9b']) if s.get('name') == 'live']),
        ('add_ask',
         lambda: storage.add_ask({'situation_kind': 'thread', 'situation_id': fx.ids['R5t'], 'what': 'live'}),
         lambda: storage.add_ask({'situation_kind': 'thread', 'situation_id': fx.ids['GT1'], 'what': 'late'}),
         lambda: [a for a in storage.asks_table.all() if a.get('what') == 'live']),
        ('add_finding',
         lambda: storage.add_finding({'subject_type': 'thread', 'subject_id': fx.ids['R5t'], 'line': 'live'}),
         lambda: storage.add_finding({'subject_type': 'thread', 'subject_id': fx.ids['GT1'], 'line': 'late'}),
         lambda: [f for f in storage.findings_table.all() if f.get('line') == 'live']),
        ('upsert_program_lesson',
         lambda: storage.upsert_program_lesson(fx.ids['R5p'], {'phase_name': 'live'}, {'scenes': [{'type': 'say', 'text': 'live'}]}),
         lambda: storage.upsert_program_lesson(fx.ids['GP1'], {'phase_name': 'late'}, {'scenes': [{'type': 'say', 'text': 'late'}]}),
         lambda: storage.program_lessons_table.search(storage.Query().phase_name == 'live')),
        ('add_protected_commitment',
         lambda: storage.add_protected_commitment({'id': 'live-c', 'member_id': 'kid', 'title': 'live', 'days_of_week': [1],
                                                   'time_start': '17:00', 'time_end': '17:30', 'active': True,
                                                   'source': {'kind': 'program', 'id': fx.ids['R5p']}}),
         lambda: storage.add_protected_commitment({'id': 'late-c', 'member_id': 'kid', 'title': 'late', 'days_of_week': [1],
                                                   'time_start': '17:00', 'time_end': '17:30', 'active': True,
                                                   'source': {'kind': 'program', 'id': fx.ids['GP1']}}),
         lambda: [storage.get_protected_commitment('live-c')] if storage.get_protected_commitment('live-c') else []),
        ('add_action_proposal',
         lambda: storage.add_action_proposal({'action_type': 'create_list', 'summary': 'live', 'payload': {},
                                              'origin_kind': 'mission', 'origin_id': fx.ids['R9b']}),
         lambda: storage.add_action_proposal({'action_type': 'create_list', 'summary': 'late', 'payload': {},
                                              'origin_kind': 'mission', 'origin_id': fx.ids['GM2']}),
         lambda: [p for p in storage.agent_action_proposals_table.all() if p.get('summary') == 'live']),
        ('append_thread_history',
         lambda: storage.append_thread_history(fx.ids['R5t'], {'kind': 'note', 'text': 'live'}),
         lambda: storage.append_thread_history(fx.ids['GT1'], {'kind': 'note', 'text': 'late'}),
         lambda: [h for h in storage.get_thread(fx.ids['R5t'])['history'] if h.get('text') == 'live']),
        ('a chat message with a ref',
         lambda: storage.add_chat_message({'id': 'live-msg', 'channel_id': 'c', 'sender_member_id': 'argyle',
                                           'ts': time.time(), 'body': 'live', 'refs': [{'kind': 'thread', 'id': fx.ids['R5t']}]}),
         lambda: storage.add_chat_message({'id': 'late-msg', 'channel_id': 'c', 'sender_member_id': 'argyle',
                                           'ts': time.time(), 'body': 'late', 'refs': [{'kind': 'thread', 'id': fx.ids['GT1']}]}),
         lambda: [storage.get_chat_message('live-msg')] if storage.get_chat_message('live-msg') else []),
    ]
    for name, alive, _, landed in pairs:
        alive()
        check(landed(), f"{name}: the call works against a living parent (the fixture is sound)")
    projects_before = {p['id'] for p in storage.get_projects()}
    check(projects.adopt('thread', fx.ids['R5t'], dict(MOM)) == storage.get_thread(fx.ids['R5t'])['project_id'],
          "adopt keeps a living record in its project")
    delete_garage(fx)
    before = mark(fx)
    for name, _, attempt, _ in pairs + [('adopt a thread', None, lambda: projects.adopt('thread', fx.ids['GT1'], dict(MOM)), None),
                                        ('adopt a mission', None, lambda: projects.adopt('mission', fx.ids['GM1'], dict(MOM)), None)]:
        try:
            attempt()
        except BaseException as exc:      # noqa: BLE001 -- only Cancelled is a refusal; anything else is a defect
            check(cancelled(exc), f"{name}: refused by an unexpected {type(exc).__name__}: {exc}")
    nothing_since(fx, before, 'creation after start')
    check({p['id'] for p in storage.get_projects()} == projects_before, "no replacement wrapper was made")
    drained(fx, 'creation')


# --- Review Focus 5: the worker that never exits, on the monotonic clock ----------------------------

@contextlib.contextmanager
def _later(minutes, *, wall=False, monotonic=False):
    real_time, real_mono = time.time, time.monotonic
    with patch('time.time', (lambda: real_time() + minutes * 60) if wall else real_time), \
            patch('time.monotonic', (lambda: real_mono() + minutes * 60) if monotonic else real_mono):
        yield


def _maintain_logged(**clock):
    out, records = io.StringIO(), []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record.getMessage())
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        with _later(16, **clock), contextlib.redirect_stdout(out):
            held = _d().maintain()
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    return held, out.getvalue() + '\n'.join(records)


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
        Worker(missions.tick).done('the turn that starts a browse that never returns')
        check(gate.entered.wait(10), "the browser was reached")
        delete_garage(fx)
        for _ in range(3):
            held = _d().maintain()
            check(held['waiting'] >= 1 and storage.get_mission(mid) is not None, f"cleanup keeps waiting: {held}")
        check(not access.project_visible(storage.get_project(garage(fx)), dict(MOM)) and
              not access.project_visible(storage.get_project(garage(fx)), access.HOUSE), "the project stays hidden")
        held, logged = _maintain_logged(wall=True)
        check(held['waiting'] >= 1 and mid not in logged,
              f"16 minutes on the WALL clock alone prove nothing: no re-cancel yet: {logged[-300:]}")
        held, logged = _maintain_logged(monotonic=True)
        check(held['waiting'] >= 1 and storage.get_mission(mid) is not None,
              f"elapsed time never proves exit: still waiting after 16 monotonic minutes: {held}")
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
