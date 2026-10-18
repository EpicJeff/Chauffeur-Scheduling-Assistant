"""Projects delete, hide at once (spec rev 3 section 4 step 3; plan Task 1 Step 2).

The moment `deletion.start` returns, the project and every closure record are gone for everyone,
before any cleanup has run:

  * `access.gone(kind, row)` (the row is missing, or carries `deleting`) runs first in every
    visibility primitive: projects.can_see, project_visible, record_view, channel_view (and its legacy
    path), mission_view (and its origin-thread shortcut), practice_hidden, the hold readers,
    commitment_view, finding_view, finding_visible. One assertion per access-matrix class (4.1-4.8).
  * Calendar and commitment readers get a third outcome beside full and neutral: GONE. The row is
    skipped, never drawn as "Busy", and no consumer errors (`/api/schedule`, `/api/commitments`).
  * Chat: a message whose card or `refs` name a gone record is hidden BEFORE the limit is applied,
    and in channel previews and unread counts (`limit=1` still returns the newest survivor).
  * A warm wall board drops it at once (no cache clear, no waiting out the digest window).
  * The fail-closed pointer: a survivor whose subject (or subject history) names a deleted record is
    readable only by its own person, at their keeper view, on every surface, never widening; it
    stays that way after cleanup has removed the record outright, and after its owner changes.

Run from chauffeur/:  python tests/test_deletion_hide.py
"""
import datetime
import hashlib
import json
import time
import traceback

from harness import check  # noqa: F401
import access_fixture
from access_fixture import _thread, _mission, _program
from test_subjects import MOM, DAD
from test_deletion_core import start_ok, finish, http, leaked, words_of, reset_ledgers, REAL_POST, pair, LOAD
from services import storage, projects, access, missions

CLOSURE = ('R1', 'R2', 'R3', 'R7', 'R9origin', 'R9a')        # everything homed in Mom's private project
HOUSEHOLD = ('R5t', 'R5p', 'R5s', 'R9b', 'R10', 'R12')        # everything homed in the Household project
DAY = datetime.date(2026, 10, 16)
NOW = datetime.datetime(2026, 10, 16, 12)
RANK = {None: 0, 'keeper': 1, 'full': 2}


def load(fx, key):
    kind, rid = pair(fx, key)
    return kind, LOAD[kind](rid)


def viewers(fx):
    return list(fx.viewers.items()) + [('house-parent', access.HOUSE_PARENT)]


def practice_event(fx, key):
    return {'id': 'practice-' + fx.ids[key], 'title': fx.title(key), 'description': fx.secret(key),
            'start': f'{DAY}T17:00:00', 'end': f'{DAY}T18:00:00', 'event_type': 'practice',
            'calendar_ids': ['kid-cal'], 'practice': {'program_id': fx.ids[key], 'member_id': 'kid',
                                                      'phase_name': fx.secret(key), 'unit_body': fx.secret(key)}}


def busy_id(fx, key):
    return 'busy-' + hashlib.sha1(('practice-' + fx.ids[key]).encode()).hexdigest()[:12]


def world():
    """The access fixture, with practice on the calendar, commitments, findings and a hold."""
    fx = access_fixture.build()
    reset_ledgers()
    missions._post = REAL_POST
    for key in ('R3', 'R5p'):
        storage.update_program(fx.ids[key], {'state': 'active', 'phases': [
            {'name': fx.secret(key), 'weeks': 2, 'what': 'x', 'steps': [fx.secret(key)], 'milestone': 'm'}]})
    fx.commitments = {}
    for key in ('R3', 'R5p'):
        fx.commitments[key] = storage.add_protected_commitment({
            'id': 'pc-' + key, 'member_id': 'kid', 'title': fx.title(key), 'days_of_week': [DAY.weekday()],
            'time_start': '17:00', 'time_end': '18:00', 'active': True,
            'source': {'kind': 'program', 'id': fx.ids[key]}})
    fx.findings = {}
    for key in ('R1', 'R2', 'R3', 'R5t'):
        kind = load(fx, key)[0]
        fx.findings[key] = storage.add_finding({'subject_type': kind, 'subject_id': fx.ids[key], 'kind': f'{kind}_x',
                                                'line': fx.title(key) + ' ' + fx.secret(key), 'state': 'open',
                                                'identity': f'{kind}_x:{fx.ids[key]}'})
    storage.update_member('mom', {'driver_id': 'd_mom'})
    pid = fx.projects['mom_private']['id']
    step = projects.add_step(pid, {'title': fx.secret('R1') + ' hold', 'owner': 'mom'}, dict(MOM))
    check(step['status'] == 'success', f"the fixture adds a step: {step}")
    hold = projects.confirm_hold(pid, step['step']['id'], {'date': '2027-03-06', 'start': '08:00', 'end': '09:00'},
                                 dict(MOM))
    check(hold['status'] == 'success', f"the fixture holds time on it: {hold}")
    # Last: writing members and holds above invalidates the cached schedule.
    storage.set_cached_schedule({'events': [practice_event(fx, 'R3'), practice_event(fx, 'R5p'),
                                            {'id': 'e-plain', 'title': 'Soccer', 'start': f'{DAY}T09:00:00',
                                             'end': f'{DAY}T10:00:00'}],
                                 'assignments': {}, 'unassigned': []})
    check(len((storage.get_cached_schedule() or {}).get('events') or []) == 3, "the fixture: the schedule is cached")
    storage.ensure_family_channel()
    argyle = storage.ensure_argyle_member()
    fx.dm = {m: storage.get_or_create_dm(argyle['id'], m) for m in ('mom', 'dad')}
    fx.family = storage.get_family_channel()
    return fx


def holds_for(pid, viewer):
    start, end = datetime.date(2027, 3, 1), datetime.date(2027, 3, 31)
    return [h for h in projects.calendar_holds(start, end, viewer) if h.get('project_id') == pid]


def scenario_every_access_primitive_returns_nothing_for_the_project_and_its_closure():
    fx = world()
    pid = fx.projects['mom_private']['id']
    check(holds_for(pid, dict(MOM)) and projects.driver_hold_rules(datetime.date(2027, 3, 1), datetime.date(2027, 3, 31)),
          "the fixture: Mom's hold is on the calendar and in the driver rules")
    survivor_mission = storage.get_mission(fx.ids['R9b'])
    start_ok('project', pid, dict(MOM))
    project = storage.get_project(pid)
    focus = {name: f"channel:{ch['id']}" for name, ch in (('mom-dm', fx.dm['mom']), ('dad-dm', fx.dm['dad']),
                                                         ('family', fx.family))}
    for col, viewer in viewers(fx):
        check(not projects.can_see(project, viewer), f"4.1 projects.can_see {col}")
        check(not access.project_visible(project, viewer), f"4.1 project_visible {col}")
        for key in CLOSURE:
            kind, row = load(fx, key)
            check(access.record_view(kind, row, viewer) is None, f"4.1 record_view {key} {col}")
            check(not access.record_actable(kind, row, viewer, 'delete'), f"4.1 record_actable {key} {col}")
            check(not access.shared_screen_visible(kind, row, viewer), f"4.6 shared screen {key} {col}")
            for name, key_ in focus.items():
                check(access.conversation_view(kind, row, viewer, key_) is None, f"4.2 conversation {key} {col} {name}")
        _, program = load(fx, 'R3')
        check(access.practice_hidden(program, viewer) and access.practice_hidden(program, viewer, shared=True),
              f"4.7 practice_hidden R3 {col}")
        check(not isinstance(access.commitment_view(storage.get_protected_commitment(fx.commitments['R3']), viewer), dict),
              f"4.7 commitment_view is the gone outcome, never a Busy row: R3 {col}")
        check(holds_for(pid, viewer) == [], f"4.7 hold reader {col}: {holds_for(pid, viewer)}")
        for key in ('R1', 'R2', 'R3'):
            finding = storage.get_finding(fx.findings[key])
            check(access.finding_view(finding, viewer) is None, f"4.8 finding_view {key} {col}")
            check(not access.finding_visible(finding, viewer), f"4.8 finding_visible {key} {col}")
    for name, key_ in focus.items():
        for key in CLOSURE:
            kind, row = load(fx, key)
            check(access.channel_view(kind, row, key_) is None, f"4.3 channel_view {key} {name}")
    for key in CLOSURE:
        kind, row = load(fx, key)
        check(access.mission_view(survivor_mission, kind, row) is None, f"4.4 mission_view R9b -> {key}")
        check(access.private_recipients(kind, row) == [], f"4.8 private_recipients {key}")
        check(access.record_view(kind, row, access.HOUSE) is None, f"4.5 a speaker reads nothing of {key}")
    _, origin = load(fx, 'R9origin')
    check(access.mission_view(storage.get_mission(fx.ids['R9a']), 'thread', origin) is None,
          "4.4 the origin-thread shortcut never opens a gone thread")
    check(projects.driver_hold_rules(datetime.date(2027, 3, 1), datetime.date(2027, 3, 31)) == [],
          "4.7 a gone project's hold blocks no driver")


def scenario_an_unrestricted_closure_is_gone_on_the_legacy_channel_path_too():
    fx = world()
    pid = fx.projects['household']['id']
    focus = f"channel:{fx.family['id']}"
    _, r5t = load(fx, 'R5t')
    check(access.channel_view('thread', r5t, focus) == 'full', "the fixture: a household thread reads in the family channel")
    start_ok('project', pid, dict(DAD))
    for key in HOUSEHOLD:
        kind, row = load(fx, key)
        check(access.channel_view(kind, row, focus) is None, f"legacy channel path: {key}")
        for col, viewer in viewers(fx):
            check(access.record_view(kind, row, viewer) is None, f"{key} {col}")
    _, program = load(fx, 'R5p')
    for col, viewer in viewers(fx):
        check(access.practice_hidden(program, viewer), f"an unrestricted gone program is hidden too: {col}")


def scenario_calendar_and_commitment_readers_skip_gone_rows_without_error():
    fx = world()
    start_ok('project', fx.projects['household']['id'], dict(DAD))
    blob = storage.get_cached_schedule()
    for col, viewer in viewers(fx):
        for reader in (access.schedule_view, access.shared_schedule_view):
            events = reader(blob, viewer)['events']
            ids = {e.get('id') for e in events}
            check('practice-' + fx.ids['R5p'] not in ids and busy_id(fx, 'R5p') not in ids,
                  f"{reader.__name__} {col}: the gone practice is skipped, not Busy: {ids}")
            check('e-plain' in ids, f"{reader.__name__} {col}: everything else is still there")
        gone = access.event_view(practice_event(fx, 'R5p'), viewer)
        check(not (isinstance(gone, dict) and gone.get('title')), f"event_view {col}: the gone outcome: {gone}")
        events = access.cached_schedule(viewer)['events']
        check(not any((e.get('practice') or {}).get('program_id') == fx.ids['R5p'] or e.get('id') == busy_id(fx, 'R5p')
                      for e in events), f"cached_schedule {col}")
    for who in ('mom', 'dad', 'kid'):
        r = http(who, 'GET', '/api/schedule')
        check(r.status_code == 200, f"/api/schedule {who}: {r.status_code} {r.text[:200]}")
        ids = {e.get('id') for e in (r.json() or {}).get('events') or []}
        check('practice-' + fx.ids['R5p'] not in ids and busy_id(fx, 'R5p') not in ids, f"/api/schedule {who}: {ids}")
        r = http(who, 'GET', '/api/commitments')
        check(r.status_code == 200, f"/api/commitments {who} answers: {r.status_code} {r.text[:200]}")
        rows = r.json()
        check(not any(c.get('id') == fx.commitments['R5p'] for c in rows),
              f"/api/commitments {who}: the gone program's commitment is absent, not Busy: {rows}")
        check(any(c.get('id') == fx.commitments['R3'] for c in rows), f"/api/commitments {who}: the rest stays")


def scenario_the_routes_answer_as_if_it_never_existed():
    fx = world()
    pid = fx.projects['mom_private']['id']
    check(http('mom', 'GET', f'/api/projects/{pid}').status_code == 200, "the fixture: Mom reads her project")
    start_ok('project', pid, dict(MOM))
    r = http('mom', 'GET', '/api/projects')
    check(r.status_code == 200 and pid not in r.text and not leaked(r.json(), words_of(fx, CLOSURE)),
          f"/api/projects drops it: {r.status_code}")
    for path in (f'/api/projects/{pid}', f'/api/projects/{pid}/pieces', f"/api/missions/{fx.ids['R2']}",
                 f"/api/threads/{fx.ids['R1']}/missions", f"/api/projects/for/thread/{fx.ids['R1']}",
                 f"/api/programs/{fx.ids['R3']}/footprint", f"/api/deletion/project/{pid}/preview"):
        r = http('mom', 'GET', path)
        check(r.status_code == 404, f"{path}: a 404 shaped like a missing record: {r.status_code} {r.text[:160]}")
    r = http('mom', 'GET', '/api/projects/elsewhere')
    check(r.status_code == 200 and not leaked(r.json(), words_of(fx, CLOSURE)), "the elsewhere list is clean")


def _msg(channel, sender, body, ts, card=None, refs=None):
    from models.schemas import ChatMessage
    m = ChatMessage(channel_id=channel['id'], sender_member_id=sender, body=body, card=card).model_dump()
    m['ts'] = ts
    if refs is not None:
        m['refs'] = refs
    storage.add_chat_message(m)
    return m['id']


def scenario_chat_hides_gone_messages_before_the_limit_and_in_previews_and_counts():
    fx = world()
    dm, argyle = fx.dm['mom'], storage.ensure_argyle_member()['id']
    base = time.time() - 1000
    keep = _msg(dm, argyle, 'Plain survivor note', base + 1)
    gone = [
        _msg(dm, argyle, fx.title('R2'), base + 2, card={'kind': 'mission_ask', 'mission_id': fx.ids['R2']}),
        _msg(dm, argyle, fx.title('R1'), base + 3, refs=[{'kind': 'thread', 'id': fx.ids['R1']}]),
        _msg(dm, argyle, 'mixed', base + 4, refs=[{'kind': 'thread', 'id': fx.ids['R1']},
                                                  {'kind': 'thread', 'id': fx.ids['R5t']}]),
        _msg(dm, argyle, 'Mom private', base + 5, card={'kind': 'project_start', 'project_id': fx.projects['mom_private']['id']}),
        _msg(dm, argyle, fx.title('R3'), base + 6, card={'kind': 'program', 'program_id': fx.ids['R3']}),
        _msg(dm, argyle, fx.title('R7'), base + 7, card={'kind': 'thread', 'thread_id': fx.ids['R7']}),
    ]
    storage.set_last_read(dm['id'], 'mom', base)
    check(storage.get_channel_messages(dm['id'], limit=1)[0]['id'] == gone[-1], "the fixture: the newest is a gone card")
    start_ok('project', fx.projects['mom_private']['id'], dict(MOM))
    newest = storage.get_channel_messages(dm['id'], limit=1)
    check([m['id'] for m in newest] == [keep], f"limit=1 is the newest SURVIVING message: {[m['body'] for m in newest]}")
    every = storage.get_channel_messages(dm['id'])
    check([m['id'] for m in every] == [keep], f"no gone card, ref or mixed message is read: {[m['body'] for m in every]}")
    check(storage.get_unread_counts('mom').get(dm['id']) == 1, f"unread counts the survivor only: {storage.get_unread_counts('mom')}")
    r = http('mom', 'GET', f"/api/channels/{dm['id']}/messages?limit=1")
    check(r.status_code == 200 and [m['id'] for m in r.json()] == [keep], f"the route too: {r.text[:200]}")
    r = http('mom', 'GET', '/api/channels?member_id=mom')
    row = next((c for c in r.json() if c['id'] == dm['id']), None)
    check(row and (row.get('last_message') or {}).get('id') == keep and row.get('unread') == 1,
          f"the channel preview and its count: {row}")


def scenario_a_warm_wall_board_drops_it_at_once():
    from services import home_board
    fx = world()
    config = json.dumps([{'id': 'calendar-proof', 'type': 'calendar', 'config': {'view': 'list'}}])

    def rows(board):
        tile = next(t for t in board['tiles'] if t.get('id') == 'calendar-proof')
        return [r['title'] for r in (tile.get('data') or {}).get('rows') or []]
    home_board._CACHE.clear()
    before = rows(home_board.build(config, now=NOW))
    check(fx.title('R5p') in before and before.count('Busy') == 1,
          f"the fixture: the household practice is on the wall, Mom's private one as Busy: {before}")
    start_ok('project', fx.projects['household']['id'], dict(DAD))
    after_board = home_board.build(config, now=NOW)      # warm: no cache clear, no waiting out the digest
    after = rows(after_board)
    check(fx.title('R5p') not in after and after.count('Busy') == 1 and 'Soccer' in after,
          f"the warm board drops the gone practice outright, never as a second Busy: {after}")
    check(fx.secret('R5p') not in json.dumps(after_board, default=str), "no word of it anywhere on the board")


# --- the fail-closed pointer -------------------------------------------------------------

def _pointer_world():
    fx = world()
    house = fx.projects['household']
    _thread(fx, 'RH', 'dad', house, subject_history=[{'kind': 'thread', 'id': fx.ids['R1']}])
    _mission(fx, 'R10m', 'dad', house, origin_kind='thread', origin_ref=fx.ids['R10'])
    _program(fx, 'PX', 'kid', fx.projects['mom_parents'], subject_kind='thread', subject_id=fx.ids['R1'])
    storage.update_program(fx.ids['PX'], {'subject_kind': 'thread', 'subject_id': fx.ids['R1']})
    return fx


def _views(fx, kind, rid):
    row = {'thread': storage.get_thread, 'program': storage.get_program}[kind](rid)
    return {col: access.record_view(kind, row, v) for col, v in viewers(fx)}


def _check_fail_closed(fx, before, stage):
    for key, keeper in (('R10', 'dad'), ('RH', 'dad')):
        after = _views(fx, 'thread', fx.ids[key])
        want = {col: ('keeper' if col == keeper else None) for col in after}
        check(after == want, f"{stage} {key}: only its own person, at the keeper view: {after}")
        for col in after:
            check(RANK[after[col]] <= RANK[before[key][col]], f"{stage} {key} {col}: never widening")
    r10 = storage.get_thread(fx.ids['R10'])
    focus = {m: f"channel:{fx.dm[m]['id']}" for m in ('mom', 'dad')}
    check(access.conversation_view('thread', r10, fx.viewers['dad'], focus['dad']) == 'keeper', f"{stage}: Dad's own DM")
    check(access.conversation_view('thread', r10, fx.viewers['mom'], focus['mom']) is None, f"{stage}: Mom's DM")
    check(access.channel_view('thread', r10, f"channel:{fx.family['id']}") is None, f"{stage}: the family channel")
    check(access.mission_view(storage.get_mission(fx.ids['R10m']), 'thread', r10) != 'full',
          f"{stage}: a mission's origin shortcut never opens the survivor in full")
    px = storage.get_program(fx.ids['PX'])
    for col, viewer in viewers(fx):
        check(access.practice_hidden(px, viewer) == (col != 'kid'), f"{stage}: practice of PX for {col}")


def scenario_a_survivor_pointing_at_a_deleted_record_fails_closed_on_every_surface():
    fx = _pointer_world()
    before = {key: _views(fx, 'thread', fx.ids[key]) for key in ('R10', 'RH')}
    check(before['R10']['mom'] == 'full' and before['R10']['dad'] == 'keeper', f"the fixture: {before['R10']}")
    start_ok('project', fx.projects['mom_private']['id'], dict(MOM))
    _check_fail_closed(fx, before, 'after start')
    finish()
    check(storage.get_thread(fx.ids['R1']) is None, "cleanup removed the private thread outright")
    r10 = storage.get_thread(fx.ids['R10'])
    check(r10['subject_kind'] == 'thread' and r10['subject_id'] == fx.ids['R1'],
          "the survivor keeps the bare id of what it pointed at")
    _check_fail_closed(fx, before, 'after cleanup')


def scenario_a_survivor_whose_owner_changes_keeps_failing_closed():
    fx = _pointer_world()
    start_ok('project', fx.projects['mom_private']['id'], dict(MOM))
    finish()
    storage.update_thread(fx.ids['R10'], {'owner_member_id': 'mom'})
    views = _views(fx, 'thread', fx.ids['R10'])
    check(views == {col: ('keeper' if col == 'mom' else None) for col in views},
          f"the new owner keeps it, at the keeper view, with no lockout error: {views}")


def scenario_a_finding_whose_subject_is_missing_is_hidden():
    """Gone is missing OR stamped (spec section 4 step 3): today's permissive missing-subject branch goes."""
    fx = world()
    start_ok('project', fx.projects['mom_private']['id'], dict(MOM))
    finish()
    # Raw rows, as a racing writer or old data would leave them (storage refuses them; the orphan pass
    # would collect them; until then no reader may show them).
    storage.findings_table.insert({'id': 'never', 'subject_type': 'thread', 'subject_id': 'a-thread-that-never-existed',
                                   'kind': 'x', 'line': 'orphan words', 'state': 'open', 'identity': 'x:never'})
    never = 'never'
    check(storage.get_thread(fx.ids['R1']) is None, "the fixture: R1 is removed outright")
    leftover = storage.findings_table.insert({'id': 'leftover-r1', 'subject_type': 'thread', 'subject_id': fx.ids['R1'],
                                              'kind': 'x', 'line': fx.secret('R1'), 'state': 'open', 'identity': 'x:r1'})
    check(leftover, "the fixture: a finding a racing writer left on the removed thread")
    for fid in (never, 'leftover-r1'):
        finding = storage.get_finding(fid)
        for col, viewer in viewers(fx):
            check(not access.finding_visible(finding, viewer), f"finding_visible {fid} {col}: a missing subject hides it")
            check(access.finding_view(finding, viewer) is None, f"finding_view {fid} {col}: a missing subject hides it")


# --- the fail-closed pointer, for every target kind, pointer kind and survivor kind ------------------

def _pointer_matrix_world():
    """Survivors in Household pointing at each kind of record in Mom's private project.

    Thread PT-* (Dad keeps it) and mission PM-* (Dad started it), each by subject or by subject history,
    at R1 (thread), R2 (mission), R3 (program) and the project itself."""
    fx = world()
    house = fx.projects['household']
    targets = {'thread': fx.ids['R1'], 'mission': fx.ids['R2'], 'program': fx.ids['R3'],
               'project': fx.projects['mom_private']['id']}
    keys = []
    for tkind, tid in targets.items():
        for via in ('subject', 'history'):
            extra = ({'subject_kind': tkind, 'subject_id': tid} if via == 'subject'
                     else {'subject_history': [{'kind': tkind, 'id': tid}]})
            _thread(fx, f'PT-{tkind}-{via}', 'dad', house, **extra)
            _mission(fx, f'PM-{tkind}-{via}', 'dad', house, **extra)
            keys += [('thread', f'PT-{tkind}-{via}'), ('mission', f'PM-{tkind}-{via}')]
    return fx, keys


def _view_all(fx, kind, key):
    row = LOAD[kind](fx.ids[key])
    return {col: access.record_view(kind, row, v) for col, v in viewers(fx)}


def _keeper_only(fx, keys, before, keeper, stage):
    for kind, key in keys:
        after = _view_all(fx, kind, key)
        want = {col: ('keeper' if col == keeper else None) for col in after}
        check(after == want, f"{stage} {key}: readable only by {keeper}, at the keeper view: {after}")
        if before:
            for col in after:
                check(RANK[after[col]] <= RANK[before[key][col]], f"{stage} {key} {col}: never widening")


def scenario_fail_closed_for_every_target_kind_pointer_kind_and_survivor_kind():
    fx, keys = _pointer_matrix_world()
    before = {key: _view_all(fx, kind, key) for kind, key in keys}
    check(all(before[key]['mom'] == 'full' for _, key in keys), f"the fixture: Mom reads every survivor in full: {before}")
    start_ok('project', fx.projects['mom_private']['id'], dict(MOM))
    _keeper_only(fx, keys, before, 'dad', 'after start')
    finish()
    for tkind, rid in (('thread', fx.ids['R1']), ('mission', fx.ids['R2']), ('program', fx.ids['R3'])):
        check(LOAD[tkind](rid) is None, f"the fixture: the {tkind} target is removed outright")
    _keeper_only(fx, keys, before, 'dad', 'after cleanup')
    for kind, key in keys:
        storage.update_thread(fx.ids[key], {'owner_member_id': 'mom'}) if kind == 'thread' else \
            storage.update_mission(fx.ids[key], {'created_by': 'mom'})
    _keeper_only(fx, keys, None, 'mom', 'after the owner changed')


# --- every read surface, and the requirements no primitive shows ------------------------------------

READ_SURFACES = ('/api/threads', '/api/situations', '/api/subjects/search?q=Title', '/api/missions/admin',
                 '/api/programs', '/api/action-proposals', '/api/projects/elsewhere', '/api/projects',
                 '/api/findings', '/api/home_board')


def scenario_no_read_surface_leaks_a_gone_record():
    from services import home_board, house_programs
    fx = world()
    storage.add_action_proposal({'action_type': 'skip_occurrence', 'summary': fx.secret('R2'), 'status': 'proposed',
                                 'origin_kind': 'mission', 'origin_id': fx.ids['R2']})
    words = words_of(fx, CLOSURE)

    def surfaces():
        out = {}
        for path in READ_SURFACES:
            r = http('mom', 'GET', path)
            check(r.status_code == 200, f"{path} answers Mom: {r.status_code} {r.text[:160]}")
            out[path] = r.text
        home_board._CACHE.clear()
        out['board'] = json.dumps(home_board.build(None, now=NOW, viewer=fx.viewers['mom']), default=str)
        out['house programs'] = json.dumps(house_programs.objects(viewer=fx.viewers['mom']), default=str)
        return out
    seen = {path: leaked(text, words) for path, text in surfaces().items()}
    # Before the delete every surface that draws these records for Mom names them; the elsewhere list and
    # the boards have nothing of them to draw (Mom sees the project; the practice is on no board yet).
    quiet = {'/api/projects/elsewhere', '/api/home_board', 'board'}
    check(all(found for path, found in seen.items() if path not in quiet),
          f"the fixture: Mom's surfaces name the private records before the delete: "
          f"{ {path: bool(found) for path, found in seen.items()} }")
    start_ok('project', fx.projects['mom_private']['id'], dict(MOM))
    for path, text in surfaces().items():
        check(not leaked(text, words), f"{path}: names a gone record: {leaked(text, words)}")


def scenario_the_board_digest_reads_the_stamp():
    from unittest.mock import patch
    from services import home_board
    fx = world()
    with patch.object(home_board, 'ACCESS_DIGEST_SECONDS', 0):
        before = home_board._access_input_digest()
        storage.update_thread(fx.ids['R5t'], {'deleting': 'a-deletion-id'})
        check(home_board._access_input_digest() != before, "`deleting` is an input of the board's access digest")


def scenario_a_chat_read_resolves_its_distinct_refs_in_one_batch():
    from unittest.mock import patch
    fx = world()
    dm, argyle = fx.dm['mom'], storage.ensure_argyle_member()['id']
    refs = [{'kind': 'thread', 'id': fx.ids['R5t']}, {'kind': 'mission', 'id': fx.ids['R9b']},
            {'kind': 'program', 'id': fx.ids['R5p']}]
    base = time.time() - 1000
    for i in range(30):
        _msg(dm, argyle, f'note {i}', base + i, refs=[refs[i % 3]], card={'kind': 'mission_ask', 'mission_id': fx.ids['R9b']})
    loads = []
    getters = {name: getattr(storage, name) for name in ('get_thread', 'get_mission', 'get_program', 'get_project')}

    def counted(name):
        return lambda rid, *a, **k: loads.append((name, rid)) or getters[name](rid, *a, **k)
    with patch.multiple(storage, **{name: counted(name) for name in getters}):
        msgs = storage.get_channel_messages(dm['id'])
    check(len(msgs) == 30, f"all thirty survive: {len(msgs)}")
    check(len(loads) <= 3, f"three distinct refs are resolved once each, not once per message: {len(loads)} loads")


def scenario_the_schedule_is_marked_dirty_at_start_and_refreshed_once_by_cleanup():
    from unittest.mock import patch
    import main
    fx = world()
    calls = []
    pid = fx.projects['mom_private']['id']
    with patch.object(main, 'trigger_background_refresh', lambda *a, **k: calls.append((a, k))):
        preview = http('mom', 'GET', f'/api/deletion/project/{pid}/preview')
        check(preview.status_code == 200, f"the preview route: {preview.status_code} {preview.text[:160]}")
        r = http('mom', 'DELETE', f'/api/projects/{pid}', json={'token': preview.json()['token']})
        check(r.status_code == 200, f"deleted: {r.status_code} {r.text[:200]}")
        check(len(calls) >= 1, "the tap marks the schedule dirty (a refresh is requested)")
        at_start = len(calls)
        finish()
        check(len(calls) - at_start == 1, f"cleanup refreshes the schedule exactly once: {len(calls) - at_start}")


def scenario_commitment_findings_hide_at_start_with_their_program():
    from services import findings
    fx = world()
    ids = {}
    for key in ('R3', 'R5p'):
        ids[key] = storage.add_finding({
            'subject_type': 'commitment', 'subject_id': fx.commitments[key] + ':practice-occurrence',
            'kind': 'commitment', 'line': fx.title(key) + ' ' + fx.secret(key),
            'state': 'open', 'identity': 'commitment-proof:' + key})
    before = http('mom', 'GET', '/api/findings')
    check(before.status_code == 200 and fx.secret('R5p') in before.text, 'the emitted finding starts visible')
    private = storage.get_finding(ids['R3'])
    for col, viewer in viewers(fx):
        allowed = col in ('mom', 'kid')
        check(access.finding_visible(private, viewer) == allowed, f'private commitment finding audience for {col}')
        check((access.finding_view(private, viewer) is not None) == allowed,
              f'private commitment finding words require program access for {col}')
        check(any(f['id'] == private['id'] for f in findings.open_findings(viewer=viewer)) == allowed,
              f'Needs You applies the source program audience for {col}')
    for who in ('mom', 'dad', 'aunt'):
        response = http(who, 'GET', '/api/findings')
        check(response.status_code == 200, response.text)
        check(any(f['id'] == private['id'] for f in response.json()['findings']) == (who == 'mom'),
              f'findings API applies the source program audience for {who}')
        if who != 'mom':
            check(fx.secret('R3') not in response.text, f'no private program words for {who}')
    start_ok('project', fx.projects['household']['id'], dict(DAD))
    gone = storage.get_finding(ids['R5p'])
    for col, viewer in viewers(fx):
        check(not access.finding_visible(gone, viewer), f'commitment finding hidden for {col}')
        check(access.finding_view(gone, viewer) is None, f'no commitment projection for {col}')
        check(not any(f['id'] == gone['id'] for f in findings.open_findings(viewer=viewer)),
              f'Needs You reader omits it for {col}')
    after = http('mom', 'GET', '/api/findings')
    check(after.status_code == 200 and fx.secret('R5p') not in after.text, 'findings API hides the gone program')
    check(fx.secret('R3') in after.text, 'the surviving program finding stays')


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
