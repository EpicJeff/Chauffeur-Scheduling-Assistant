"""Projects delete, the core (spec 2026-10-18-projects-delete-design.md rev 3, sections 1-4; plan Task 1 Step 1).

Pinned here, and by the shared fixture `build()` the other three deletion files import:

  * `deletion.closure(kind, id) -> [(kind, id)]` from authoritative fields: a project's threads,
    missions and programs by `project_id` (never `pieces[]` alone); a thread's missions by origin,
    wherever they live; a program's kit threads (`emissions.thread_ids`) that still exist, with
    their missions; closed under the thread rule. Records elsewhere ABOUT the project stay out.
  * `deletion.preview(kind, id, actor)` -> {'status': 'ok', 'token', 'items': [{kind, id, title}],
    'links': n} | {'status': 'refused', 'message'}; `deletion.start(kind, id, actor, token)` ->
    {'status': 'ok', 'deletion_id'} | {'status': 'refused' | 'changed', 'message'}.
  * Who: a project's owner, or a parent who sees it; never a device; a standalone thread or mission
    by `record_actable(..., 'delete')`; a program by its project's owner or a parent who reads it.
    Every closure record must be readable by the actor, else "Ask a parent to delete this." and
    nothing is named. Linked kinds never block. The token hashes the (kind, id, title) snapshot the
    confirmation displayed: a moved closure answers `changed`, "This project changed. Look again."
  * `start` is one transaction: a deletions row (id, kind, root_id, closure, actor_id, started_at,
    state 'started', emissions) and a `deleting: <deletion id>` stamp on every closure row, or
    nothing at all. Then it stops the work: live missions close as dropped, browse missions get
    their stop flag, programs pause WITHOUT releasing (their emissions are snapshotted first).
  * Routes (spec section 6): GET /api/deletion/{kind}/{id}/preview; DELETE /api/projects|threads|
    missions|programs/{id} with body {token}; refusal 403, moved 409, unseen 404, no token 400
    "A confirmation is required." A route whose work hits deletion.Cancelled answers 404.
  * Review Focus 1 (double start), 3 (actor disabled before start), 4 (a large project).

Interface assumptions beyond the brief (the controller's ruling): `storage.get_deletions()` returns
the rows; a row has id, kind, root_id, closure (list of [kind, id]), actor_id, started_at, state,
emissions. Stamps are written through the storage table helpers (SqliteTable.update/upsert), which
is where the one-transaction scenario injects its crash.

Run from chauffeur/:  python tests/test_deletion_core.py
"""
import contextvars
import json
import threading
import time
import traceback
import uuid
from unittest.mock import patch

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)
import access_fixture
from access_fixture import _thread, _mission, _program, HAL, PAT, SIB
from test_subjects import MOM, DAD, AUNT, KID
from services import storage, projects, access, missions, situations

ASK_A_PARENT = "Ask a parent to delete this."
CHANGED = "This project changed. Look again."
WORK_DELETED = "Its work was deleted."
CONFIRM_TAIL = "Linked trips, lists and events stay."
TOKEN_REQUIRED = "A confirmation is required."      # a DELETE with no token: 400 (controller ruling, fix round 1)

REAL_POST = missions._post          # the fixtures stub it; deletion tests watch real DMs
PIECE_KINDS = ('thread', 'mission', 'program')
GARAGE_KEYS = ('GT1', 'GM1', 'GM2', 'GP1', 'GK1', 'GKM', 'GTL')


def _d():
    """Imported per call: until Task 2 lands every scenario is red on this import alone."""
    from services import deletion
    return deletion


# --- the shared fixture -------------------------------------------------------------------

def reset_ledgers():
    """Tables the access fixture leaves alone, emptied so no scenario reads another's rows."""
    for table in (storage.asks_table, storage.findings_table, storage.agent_action_proposals_table,
                  storage.protected_commitments_table, storage.protected_exceptions_table,
                  storage.program_lessons_table):
        table.truncate()
    storage.db.table('deletions').truncate()     # spec section 4: the `deletions` table



def build():
    """The access fixture household (R1-R17, spec section 6 of the access rule) plus the Garage world.

    Garage (household, owner Mom) holds:
      GT1  a thread;                     GM1  GT1's mission, homed in the Household project;
      GM2  a manual mission;             GP1  Kate's program, kit thread GK1 (homed in Household)
      GKM  GK1's mission (Household);    GTL  a thread whose pieces[] entry was lost;
      and a linked trip (Disney World).
    About the Garage, elsewhere, and so never in its closure: SA1 (a Household thread whose subject is
    the project) and SA2 (a Household mission whose subject is the project).
    Survivor (household, owner Mom) is an untouched project of its own.
    """
    fx = access_fixture.build()
    reset_ledgers()
    missions._post = REAL_POST
    house = fx.projects['household']
    garage = projects.create({'title': 'Garage', 'goal': 'clear the garage', 'done_when': 'the car fits',
                              'owner_member_id': 'mom', 'audience': 'household'}, dict(MOM))['project']
    survivor = projects.create({'title': 'Survivor', 'goal': 'g', 'done_when': 'd',
                                'owner_member_id': 'mom', 'audience': 'household'}, dict(MOM))['project']
    fx.projects.update(garage=garage, survivor=survivor)
    gt1 = _thread(fx, 'GT1', 'mom', garage)
    _mission(fx, 'GM1', 'mom', house, origin_kind='thread', origin_ref=gt1)
    _mission(fx, 'GM2', 'mom', garage)
    gk1 = _thread(fx, 'GK1', 'kid', house)
    _mission(fx, 'GKM', 'mom', house, origin_kind='thread', origin_ref=gk1)
    _program(fx, 'GP1', 'kid', garage)
    storage.update_program(fx.ids['GP1'], {'emissions': {'commitment_ids': [], 'thread_ids': [gk1],
                                                         'event_ids': []}})
    gtl = _thread(fx, 'GTL', 'mom', garage)
    row = storage.get_project(garage['id'])
    storage.update_project(garage['id'], {'pieces': [p for p in row['pieces'] if p['id'] != gtl]})
    _thread(fx, 'SA1', 'dad', house, subject_kind='project', subject_id=garage['id'])
    _mission(fx, 'SA2', 'mom', house, subject_kind='project', subject_id=garage['id'])
    res = projects.add_piece(garage['id'], 'trip', 'ev_disney', dict(MOM))
    check(res['status'] == 'success', f"the fixture links a trip to the Garage: {res}")
    for key in ('GM1', 'GKM'):
        check(storage.get_mission(fx.ids[key])['project_id'] == house['id'], f"the fixture: {key} lives in Household")
    check(storage.get_thread(gk1)['project_id'] == house['id'], "the fixture: the kit thread lives in Household")
    check(not any(p['id'] == gtl for p in storage.get_project(garage['id'])['pieces']),
          "the fixture: GTL's pieces entry is lost")
    return fx


KIND = {'GT1': 'thread', 'GM1': 'mission', 'GM2': 'mission', 'GP1': 'program', 'GK1': 'thread',
        'GKM': 'mission', 'GTL': 'thread', 'SA1': 'thread', 'SA2': 'mission', 'R5s': 'program',
        'AT1': 'thread', 'AP1': 'program'}
LOAD = {'thread': storage.get_thread, 'mission': storage.get_mission, 'program': storage.get_program,
        'project': storage.get_project}


def kind_of(key):
    from test_access_core import KIND as R_KIND
    return KIND.get(key) or R_KIND[key]


def pair(fx, key):
    return (kind_of(key), fx.ids[key])


def garage(fx):
    return fx.projects['garage']['id']


def pieces_of(closure, root=None):
    """The closure as a set of (kind, id), the root project row left out (either shape passes)."""
    out = set()
    for item in closure:
        kind, rid = tuple(item)
        if kind == 'project':
            check(rid == root, f"the only project in a closure is its root: {item}")
            continue
        out.add((kind, rid))
    return out


def stamped():
    """Every row, of any deletable kind, that carries a deleting stamp."""
    rows = []
    for kind, rows_of in (('thread', storage.get_threads(include_closed=True)), ('mission', storage.get_missions()),
                          ('program', storage.get_programs(include_finished=True)), ('project', storage.get_projects())):
        rows += [(kind, r['id']) for r in rows_of if r.get('deleting')]
    return rows


SNAPSHOT_TABLES = ('threads', 'missions', 'mission_steps', 'programs', 'projects', 'asks', 'findings',
                   'agent_action_proposals', 'protected_commitments', 'protected_exceptions', 'program_lessons',
                   'chat_messages', 'trip_metadata', 'deletions')


def snapshot():
    """Every row a refused or late action could touch, compared in full (never ids or counts)."""
    return {name: sorted(json.dumps(dict(r), sort_keys=True, default=str) for r in storage.db.table(name).all())
            for name in SNAPSHOT_TABLES}


def untouched(before, how):
    """Nothing written at all since `before`: no stamp, no deletions row, no changed payload."""
    check(stamped() == [], f"{how}: nothing is stamped: {stamped()}")
    after = snapshot()
    for name in SNAPSHOT_TABLES:
        if after[name] != before[name]:
            was, now = set(before[name]) - set(after[name]), set(after[name]) - set(before[name])
            check(False, f"{how}: {name} changed:\n  was {sorted(was)[:2]}\n  now {sorted(now)[:2]}")


def in_fresh_context(fn, *args, timeout=30, **kwargs):
    """Run fn in another thread with an EMPTY context (no worker source), joined with a timeout.

    The deletion is what a different request does; it must not inherit a worker's acting_for."""
    box = {}

    def target():
        try:
            box['value'] = contextvars.Context().run(fn, *args, **kwargs)
        except BaseException as exc:      # noqa: BLE001 -- reported to the caller
            box['error'] = exc
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    check(not t.is_alive(), f"{getattr(fn, '__name__', fn)} did not return within {timeout}s "
                            "(is a worker holding storage.db_lock across its outside call?)")
    if 'error' in box:
        raise box['error']
    return box.get('value')


def preview_ok(kind, rid, actor):
    res = _d().preview(kind, rid, actor)
    check(res.get('status') == 'ok' and res.get('token'), f"{kind} {rid} previews for {actor.get('id')}: {res}")
    return res


def start_ok(kind, rid, actor):
    """Preview and start as one person would: returns the start result."""
    res = _d().start(kind, rid, actor, preview_ok(kind, rid, actor)['token'])
    check(res.get('status') == 'ok' and res.get('deletion_id'), f"{kind} {rid} starts for {actor.get('id')}: {res}")
    return res


def finish(passes=30):
    """maintain() until no deletion is left (cleanup may take several passes, Review Focus 4)."""
    out = None
    for _ in range(passes):
        out = _d().maintain()
        check(isinstance(out, dict) and {'finished', 'waiting', 'orphans'} <= set(out),
              f"maintain() reports finished, waiting and orphans: {out}")
        if not storage.get_deletions():
            return out
    check(False, f"cleanup did not converge in {passes} passes: {storage.get_deletions()}")


def http(who, method, path, **kwargs):
    """A request as a signed-in member, or as a panel ('panel'), with enforcement on."""
    from fastapi.testclient import TestClient
    import main
    headers = ({'X-Device-Token': storage.enrol_device_token('del-' + uuid.uuid4().hex[:8], 'Panel')}
               if who == 'panel' else {'X-Member-Token': storage.create_member_token(who)})
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        return TestClient(main.app).request(method, path, headers=headers, **kwargs)


def words_of(fx, keys):
    out = []
    for key in keys:
        out += [fx.title(key), fx.secret(key)]
    return out


def leaked(value, words):
    import re
    text = json.dumps(value, default=str, ensure_ascii=False)
    return [w for w in words if re.search(re.escape(w) + r'(?!\w)', text)]


# --- section 2: the closure ------------------------------------------------------------------

def scenario_a_projects_pieces_are_found_by_project_id_even_when_pieces_lost_the_entry():
    fx = build()
    got = pieces_of(_d().closure('project', garage(fx)), garage(fx))
    for key in ('GT1', 'GM2', 'GP1', 'GTL'):
        check(pair(fx, key) in got, f"{key} lives in the Garage by project_id: {got}")


def scenario_a_threads_missions_follow_it_wherever_they_live():
    fx = build()
    got = pieces_of(_d().closure('project', garage(fx)), garage(fx))
    check(pair(fx, 'GM1') in got, f"GT1's mission is homed in Household and still goes with GT1: {got}")
    alone = pieces_of(_d().closure('thread', fx.ids['GT1']))
    check(alone == {pair(fx, 'GT1'), pair(fx, 'GM1')}, f"a thread alone takes its missions: {alone}")


def scenario_a_programs_kit_thread_goes_with_it():
    fx = build()
    got = pieces_of(_d().closure('program', fx.ids['GP1']))
    check(got == {pair(fx, 'GP1'), pair(fx, 'GK1'), pair(fx, 'GKM')},
          f"the program, its kit thread (homed in Household) and the kit thread's mission: {got}")
    storage.update_program(fx.ids['GP1'], {'emissions': {'commitment_ids': [], 'event_ids': [],
                                                         'thread_ids': [fx.ids['GK1'], 'a-thread-long-gone']}})
    again = pieces_of(_d().closure('program', fx.ids['GP1']))
    check(('thread', 'a-thread-long-gone') not in again and again == got,
          f"a kit thread that no longer exists is not in the closure: {again}")


def scenario_the_closure_is_closed_under_the_thread_rule():
    fx = build()
    got = pieces_of(_d().closure('project', garage(fx)), garage(fx))
    want = {pair(fx, k) for k in GARAGE_KEYS}
    check(got == want, f"project -> program -> kit thread -> its mission, all of it and nothing else:\n"
                       f"missing {want - got}\nextra {got - want}")


def scenario_records_elsewhere_about_the_project_are_not_in_its_closure():
    fx = build()
    got = pieces_of(_d().closure('project', garage(fx)), garage(fx))
    for key in ('SA1', 'SA2'):
        check(pair(fx, key) not in got, f"{key} is about the Garage but lives elsewhere: never deleted: {got}")
    check(('trip', 'ev_disney') not in got and not any(k == 'trip' for k, _ in got), "a linked trip is never in it")


def scenario_the_preview_names_every_piece_and_counts_the_links():
    fx = build()
    res = preview_ok('project', garage(fx), dict(MOM))
    items = {i['id']: i for i in res['items'] if i['kind'] in PIECE_KINDS}
    check(set(items) == {fx.ids[k] for k in GARAGE_KEYS}, f"every thread, mission and program by title: {res['items']}")
    for key in GARAGE_KEYS:
        it = items[fx.ids[key]]
        check(it['kind'] == kind_of(key) and it['title'] == fx.title(key), f"{key} named by its title: {it}")
    check(res['links'] == 1, f"one linked record (the trip) is counted, never deleted: {res}")
    check(not leaked(res, [fx.title('SA1'), fx.title('SA2'), 'Disney World']),
          f"records about it and linked records are not named: {res}")


# --- section 3: who may delete ------------------------------------------------------------------

def scenario_the_owner_and_a_parent_who_sees_it_may_delete_a_project():
    for actor in (MOM, DAD):
        fx = build()
        start_ok('project', garage(fx), dict(actor))
        rows = storage.get_deletions()
        check(len(rows) == 1 and rows[0]['actor_id'] == actor['id'] and rows[0]['kind'] == 'project'
              and rows[0]['root_id'] == garage(fx) and rows[0]['state'] == 'started', f"{actor['id']}: {rows}")


def scenario_no_other_adult_child_helper_disabled_member_or_device_may_delete_a_project():
    for actor in (AUNT, KID, HAL, PAT, SIB, access.HOUSE, access.HOUSE_PARENT):
        fx = build()
        before = snapshot()
        who = actor.get('id') or ('house-parent' if actor.get('role') == 'parent' else 'house')
        res = _d().preview('project', garage(fx), dict(actor))
        check(res.get('status') == 'refused' and not res.get('token'), f"{who} may not delete the Garage: {res}")
        token = preview_ok('project', garage(fx), dict(MOM))['token']
        res = _d().start('project', garage(fx), dict(actor), token)
        check(res.get('status') == 'refused', f"{who} cannot start it with somebody else's token: {res}")
        untouched(before, who)


def scenario_a_child_owner_deletes_her_own_project_when_she_can_read_all_of_it():
    fx = build()
    pid = fx.projects['kate_no_dad']['id']
    res = preview_ok('project', pid, dict(KID))
    check({i['id'] for i in res['items'] if i['kind'] in PIECE_KINDS} == {fx.ids['R14'], fx.ids['R15']},
          f"her thread and her program: {res}")
    check(_d().start('project', pid, dict(KID), res['token'])['status'] == 'ok', "she deletes it")


def scenario_a_closure_record_the_actor_cannot_read_refuses_and_names_nothing():
    fx = build()
    pid = fx.projects['kate_private']['id']       # Kate's project holds Mom's mission R11, unreadable to Kate
    before = snapshot()
    res = _d().preview('project', pid, dict(KID))
    check(res == {'status': 'refused', 'message': ASK_A_PARENT} or
          (res.get('status') == 'refused' and res.get('message') == ASK_A_PARENT and not res.get('items')),
          f"the child owner is told to ask a parent: {res}")
    check(not leaked(res, words_of(fx, ['R11'])), f"and nothing of the mission is named: {res}")
    token = preview_ok('project', pid, dict(MOM))['token']
    res = _d().start('project', pid, dict(KID), token)
    check(res.get('status') == 'refused' and res.get('message') == ASK_A_PARENT, f"start refuses the same way: {res}")
    check(not leaked(res, words_of(fx, ['R11'])), f"naming nothing: {res}")
    untouched(before, 'the refused child')
    check(_d().start('project', pid, dict(MOM), token)['status'] == 'ok', "a parent who sees it all deletes it")


def scenario_a_linked_trip_never_blocks():
    fx = build()
    pid = fx.projects['kate_no_dad']['id']
    res = projects.add_piece(pid, 'trip', 'ev_parents_trip', dict(MOM))
    check(res['status'] == 'success', f"Mom links a parents-only trip to Kate's project: {res}")
    preview = preview_ok('project', pid, dict(KID))
    check(preview['links'] == 1 and not leaked(preview, ['Parents trip']),
          f"Kate cannot read the trip: it is counted, never named, and never blocks: {preview}")
    check(_d().start('project', pid, dict(KID), preview['token'])['status'] == 'ok', "and she deletes the project")
    finish()
    check(storage.get_trip_metadata('ev_parents_trip') is not None, "the linked trip stays")


def scenario_no_hidden_title_in_a_preview_or_a_refusal():
    fx = build()
    hidden = words_of(fx, ['R1', 'R2', 'R3', 'R7', 'R9origin', 'R9a']) + ['Mom private']
    pid = fx.projects['mom_private']['id']
    before = snapshot()
    for actor in (DAD, AUNT, KID, access.HOUSE):
        res = _d().preview('project', pid, dict(actor))
        check(res.get('status') == 'refused' and not leaked(res, hidden), f"{actor.get('id')}: {res}")
        res = _d().start('project', pid, dict(actor), 'a-guessed-token')
        check(res.get('status') in ('refused', 'changed') and not leaked(res, hidden), f"{actor.get('id')}: {res}")
    untouched(before, 'refused strangers')


def scenario_a_token_for_a_closure_that_moved_answers_changed_and_deletes_nothing():
    fx = build()
    token = preview_ok('project', garage(fx), dict(MOM))['token']
    storage.update_thread(fx.ids['GT1'], {'title': 'Garage, renamed'})
    before = snapshot()
    res = _d().start('project', garage(fx), dict(MOM), token)
    check(res == {'status': 'changed', 'message': CHANGED} or
          (res.get('status') == 'changed' and res.get('message') == CHANGED), f"a renamed piece: {res}")
    untouched(before, 'renamed')
    token = preview_ok('project', garage(fx), dict(MOM))['token']
    threads_create = _thread(fx, 'GLATE', 'mom', fx.projects['garage'])
    check(threads_create, "a new thread joins the Garage after the preview")
    before = snapshot()
    res = _d().start('project', garage(fx), dict(MOM), token)
    check(res.get('status') == 'changed' and res.get('message') == CHANGED, f"a piece added after the preview: {res}")
    untouched(before, 'grown')
    fresh = preview_ok('project', garage(fx), dict(MOM))
    check(fx.ids['GLATE'] in {i['id'] for i in fresh['items']}, "looking again names the new piece")
    check(_d().start('project', garage(fx), dict(MOM), fresh['token'])['status'] == 'ok', "and the new token deletes")


def scenario_start_stamps_every_closure_row_and_writes_one_deletions_row():
    fx = build()
    did = start_ok('project', garage(fx), dict(MOM))['deletion_id']
    rows = storage.get_deletions()
    check(len(rows) == 1, f"one row: {rows}")
    row = rows[0]
    check(row['id'] == did and row['kind'] == 'project' and row['root_id'] == garage(fx) and row['actor_id'] == 'mom'
          and row['state'] == 'started' and row.get('started_at'), f"the row: {row}")
    check(pieces_of(row['closure'], garage(fx)) == {pair(fx, k) for k in GARAGE_KEYS}, f"its closure: {row['closure']}")
    for key in GARAGE_KEYS:
        kind, rid = pair(fx, key)
        check(LOAD[kind](rid).get('deleting') == did, f"{key} carries the stamp")
    check(storage.get_project(garage(fx)).get('deleting') == did, "the project carries the stamp")
    for key in ('SA1', 'SA2', 'R5t', 'R9b'):
        kind, rid = pair(fx, key)
        check(not LOAD[kind](rid).get('deleting'), f"{key} is not stamped")


class Crash(Exception):
    pass


def crash_on_stamp(n):
    """The n-th stamp write raises. Counted once, at `SqliteTable.update` (upsert persists through it),
    and before raising it proves the earlier stamps really landed inside the open transaction."""
    from services import storage_sqlite
    seen = {'stamps': 0, 'prior_persisted': None}
    real_update = storage_sqlite.SqliteTable.update

    def update(self, fields, cond=None, doc_ids=None):
        if isinstance(fields, dict) and fields.get('deleting'):
            seen['stamps'] += 1
            if seen['stamps'] == n:
                seen['prior_persisted'] = len(stamped())    # same connection: sees the uncommitted stamps
                raise Crash(f'the process died at stamp {n}')
        return real_update(self, fields, cond=cond, doc_ids=doc_ids)
    return patch.object(storage_sqlite.SqliteTable, 'update', update), seen


def scenario_start_is_one_transaction():
    fx = build()
    token = preview_ok('project', garage(fx), dict(MOM))['token']
    before = snapshot()
    patcher, seen = crash_on_stamp(2)
    with patcher:
        try:
            res = _d().start('project', garage(fx), dict(MOM), token)
        except Crash:
            res = 'raised'
    check(seen['stamps'] == 2 and seen['prior_persisted'] and seen['prior_persisted'] >= 1,
          f"the crash came after a first stamp had really been written: {seen}")
    check(res == 'raised' or res.get('status') != 'ok', f"a crashed start does not claim success: {res}")
    untouched(before, 'crashed start')
    check(access.project_visible(storage.get_project(garage(fx)), dict(MOM)), "the project is still Mom's to see")
    check(_d().start('project', garage(fx), dict(MOM), token)['status'] == 'ok', "the same tap again works")


def scenario_starting_stops_the_work_and_snapshots_emissions_before_the_pause():
    fx = build()
    gm2, gp1 = fx.ids['GM2'], fx.ids['GP1']
    storage.update_mission(gm2, {'status': 'browsing'})
    storage.update_program(gp1, {'state': 'active'})
    cid = storage.add_protected_commitment({'id': uuid.uuid4().hex, 'member_id': 'kid', 'title': 'Practice',
                                            'days_of_week': [1], 'time_start': '17:00', 'time_end': '17:30',
                                            'active': True, 'source': {'kind': 'program', 'id': gp1}})
    exc = storage.add_protected_exception(cid, '2027-01-05')
    fid = storage.add_finding({'subject_type': 'commitment', 'subject_id': f'{cid}:ev1', 'kind': 'commitment',
                               'line': 'x', 'state': 'open', 'identity': f'commitment:{cid}:ev1'})
    cid2 = storage.add_protected_commitment({'id': uuid.uuid4().hex, 'member_id': 'kid', 'title': 'Practice',
                                             'days_of_week': [3], 'time_start': '17:00', 'time_end': '17:30',
                                             'active': True, 'source': {'kind': 'program', 'id': gp1}})
    exc2 = storage.add_protected_exception(cid2, '2027-01-07')
    fid2 = storage.add_finding({'subject_type': 'commitment', 'subject_id': f'{cid2}:ev2', 'kind': 'commitment',
                                'line': 'y', 'state': 'open', 'identity': f'commitment:{cid2}:ev2'})
    storage.update_program(gp1, {'emissions': {'commitment_ids': [cid, cid2], 'thread_ids': [fx.ids['GK1']],
                                               'event_ids': []}})
    start_ok('project', garage(fx), dict(MOM))
    check(storage.get_mission(gm2)['status'] == 'dropped', f"a live mission closes as dropped: {storage.get_mission(gm2)['status']}")
    steer = storage.get_app_state(f'mission_steer:{gm2}') or {}
    check(steer.get('text'), f"a browse gets its stop flag: {steer}")
    check(storage.get_program(gp1)['state'] == 'paused', "the program pauses")
    check(storage.get_protected_commitment(cid) is not None and storage.get_protected_commitment(cid2) is not None,
          "pausing for a delete does not release: cleanup releases from the snapshot")
    snap = json.dumps(storage.get_deletions()[0].get('emissions'), default=str)
    for what in (cid, cid2, exc, exc2, fid, fid2):
        check(what in snap, f"the deletion row snapshotted every commitment, exception id ({exc}) and finding: "
                            f"{what} missing from {snap}")
    check(missions._steer_check(gm2)() == 'Stopped', "the browse's steer check reads Stopped")
    check(missions._steer_check(gm2)() == 'Stopped', "and still does once the flag is consumed: the mission is gone")


def scenario_a_token_survives_everything_the_confirmation_did_not_show():
    """The token is the sorted (kind, id, title) snapshot: edits it never showed leave it valid."""
    fx = build()
    token = preview_ok('project', garage(fx), dict(MOM))['token']
    storage.update_thread(fx.ids['GT1'], {'next_action': 'Call the haulers', 'status_note': 'moved on'})
    storage.update_mission(fx.ids['GM2'], {'summary': 'a new summary', 'status_note': 'later'})
    storage.update_program(fx.ids['GP1'], {'starting_point': 'a different start', 'shape': {'minutes': 30}})
    trip = storage.get_trip_metadata('ev_disney')
    storage.set_trip_metadata('ev_disney', dict(trip, title='Disney World, renamed'))   # a linked record's edit
    row = storage.get_project(garage(fx))
    storage.update_project(garage(fx), {'pieces': list(reversed(row['pieces'])), 'goal': 'a new goal'})
    for key, when in (('GTL', 1.0), ('GT1', 2.0), ('GK1', 3.0)):                     # enumeration order moves
        storage.update_thread(fx.ids[key], {'created_at': when})
    res = _d().start('project', garage(fx), dict(MOM), token)
    check(res.get('status') == 'ok', f"none of that was on the confirmation, so the token holds: {res}")


def scenario_renaming_a_mission_or_a_program_moves_the_token():
    for kind, key, fields in (('mission', 'GM1', {'goal': 'Renamed mission'}),
                              ('program', 'GP1', {'title': 'Renamed program'})):
        fx = build()
        token = preview_ok('project', garage(fx), dict(MOM))['token']
        getattr(storage, f'update_{kind}')(fx.ids[key], fields)
        before = snapshot()
        res = _d().start('project', garage(fx), dict(MOM), token)
        check(res.get('status') == 'changed' and res.get('message') == CHANGED, f"a renamed {kind}: {res}")
        untouched(before, f'renamed {kind}')


def _garden(fx):
    """A household project owned by Aunt, an adult who is not a parent, with her thread and program."""
    garden = projects.create({'title': 'Garden', 'goal': 'g', 'done_when': 'd', 'owner_member_id': 'aunt',
                              'audience': 'household'}, dict(AUNT))
    check(garden['status'] == 'success', f"the fixture: Aunt's own project: {garden}")
    garden = garden['project']
    _thread(fx, 'AT1', 'aunt', garden)
    _program(fx, 'AP1', 'aunt', garden)
    return garden


def scenario_an_adult_owner_who_is_not_a_parent_deletes_her_project_and_its_program():
    fx = build()
    garden = _garden(fx)
    res = preview_ok('program', fx.ids['AP1'], dict(AUNT))
    check([i['id'] for i in res['items']] == [fx.ids['AP1']], f"her program alone: {res}")
    check(_d().start('program', fx.ids['AP1'], dict(AUNT), res['token'])['status'] == 'ok',
          "she deletes the program as its project's owner")
    finish()
    check(storage.get_program(fx.ids['AP1']) is None and storage.get_project(garden['id']) is not None, "the program went")
    res = preview_ok('project', garden['id'], dict(AUNT))
    check({i['id'] for i in res['items']} == {fx.ids['AT1']}, f"what is left of it: {res}")
    check(_d().start('project', garden['id'], dict(AUNT), res['token'])['status'] == 'ok', "and then the project")
    finish()
    check(storage.get_project(garden['id']) is None and storage.get_thread(fx.ids['AT1']) is None, "all of it is gone")


def scenario_linked_records_of_every_other_kind_stay():
    from services import subjects
    fx = build()
    links = [('occasion', 'o2'), ('member', 'kid'), ('contact', 'c1'), ('list', 'l1'), ('event', 'e1'),
             ('project', fx.projects['survivor']['id'])]
    for kind, rid in links:
        res = projects.add_piece(garage(fx), kind, rid, dict(MOM))
        check(res['status'] == 'success', f"the fixture links a {kind}: {res}")
    preview = preview_ok('project', garage(fx), dict(MOM))
    check(preview['links'] == 1 + len(links), f"every linked record is counted, never named for deletion: {preview}")
    rows = {(kind, rid): json.dumps(subjects.load(kind, rid), sort_keys=True, default=str) for kind, rid in links}
    _d().start('project', garage(fx), dict(MOM), preview['token'])
    finish()
    for (kind, rid), was in rows.items():
        now = subjects.load(kind, rid)
        check(now is not None, f"the linked {kind} {rid} stays")
        if kind != 'project':
            check(json.dumps(now, sort_keys=True, default=str) == was, f"and is untouched: {kind} {rid}")


def scenario_the_stop_needs_no_plan_approval_permission():
    """Spec section 4 step 4: the stop is authorized by the delete check, not by plan approval."""
    from services import planned
    from test_planned_missions import _planned_mission, _plan_of
    from test_mission_subject import _step
    fx = build()
    garden = _garden(fx)
    mid = _planned_mission()
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:drop:s1', payload={}, actor=dict(MOM))
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    _step(mid)
    storage.update_mission(mid, {'created_by': 'aunt', 'subject_kind': 'occasion', 'subject_id': 'occ-parents'})
    projects.adopt('mission', mid, None, project_id=garden['id'])
    mission = storage.get_mission(mid)
    check(any(st['state'] == 'running' for st in _plan_of(mid)['stages']), "the fixture: a running work stage")
    check(access.record_view('mission', mission, dict(AUNT)) == 'keeper' and not planned.may_approve(mission, dict(AUNT)),
          "the fixture: Aunt keeps the mission but may not approve its plan (a parents-only subject)")
    before = snapshot()
    refused = planned.stop_plan(mid, dict(AUNT))
    check(refused.get('status') != 'success', f"Aunt's ordinary Stop is refused: {refused}")
    untouched(before, "Aunt's refused Stop")
    start_ok('project', garden['id'], dict(AUNT))
    mission = storage.get_mission(mid)
    plan = mission['plan']
    check(plan['state'] == 'stopped' and not [st for st in plan['stages'] if st['state'] == 'running'],
          f"the delete stops the plan and its running stage: {plan['state']} {[st['state'] for st in plan['stages']]}")
    check(mission['status'] == 'dropped', f"and closes the mission as dropped: {mission['status']}")
    storage.set_app_state(f'mission_steer:{mid}', {})          # whatever flag there was, consumed
    check(missions._steer_check(mid)() == 'Stopped', "a gone mission's steer check reads Stopped")


# --- Review Focus 1, 3, 4 ---------------------------------------------------------------------

def scenario_rf1_delete_pressed_twice_answers_cleanly_and_starts_once():
    fx = build()
    token = preview_ok('project', garage(fx), dict(MOM))['token']
    check(_d().start('project', garage(fx), dict(MOM), token)['status'] == 'ok', "the first tap")
    again = _d().start('project', garage(fx), dict(MOM), token)
    check(again.get('status') in ('changed', 'refused'), f"the second tap answers cleanly: {again}")
    check(len(storage.get_deletions()) == 1, f"one deletion row: {storage.get_deletions()}")

    fx = build()
    token = preview_ok('project', garage(fx), dict(MOM))['token']
    barrier, results = threading.Barrier(2), []

    def tap():
        barrier.wait(10)
        results.append(_d().start('project', garage(fx), dict(MOM), token))
    workers = [threading.Thread(target=lambda: contextvars.Context().run(tap), daemon=True) for _ in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(30)
    check(sorted(r.get('status') for r in results).count('ok') == 1 and len(results) == 2,
          f"two devices at once: exactly one starts: {results}")
    check(len(storage.get_deletions()) == 1, f"and one deletion row: {storage.get_deletions()}")

    fx = build()
    token = preview_ok('project', garage(fx), dict(MOM))['token']
    first = http('mom', 'DELETE', f"/api/projects/{garage(fx)}", json={'token': token})
    second = http('mom', 'DELETE', f"/api/projects/{garage(fx)}", json={'token': token})
    check(first.status_code == 200, f"the route deletes: {first.status_code} {first.text[:200]}")
    check(second.status_code in (404, 409), f"the second request is 404 or 409, never a 500: {second.status_code} {second.text[:200]}")
    check(len(storage.get_deletions()) == 1, "one deletion row")


def scenario_rf3_a_person_disabled_between_preview_and_start_is_refused():
    fx = build()
    token = preview_ok('project', garage(fx), dict(MOM))['token']
    storage.update_member('mom', {'status': 'disabled'})
    before = snapshot()
    res = _d().start('project', garage(fx), dict(MOM), token)       # the caller's stale dict still says active
    check(res.get('status') == 'refused', f"start re-reads the actor: {res}")
    untouched(before, 'disabled actor')


def _big_project():
    big = projects.create({'title': 'Big', 'goal': 'g', 'done_when': 'd', 'owner_member_id': 'mom',
                           'audience': 'household'}, dict(MOM))['project']
    history = [{'kind': 'note', 'text': f'note {i} ' + 'x' * 200, 'ts': 1700000000 + i, 'who': 'mom'} for i in range(200)]
    ids = []
    from services import threads
    for i in range(25):
        tid = threads.create(title=f'Big thread {i}', owner_member_id='mom', created_by='mom', project_id=big['id'])
        storage.update_thread(tid, {'history': history})
        ids.append(('thread', tid))
    for i in range(20):
        mid = storage.add_mission({'goal': f'Big mission {i}', 'created_by': 'mom', 'status': 'done'})
        for j in range(30):
            storage.add_mission_step(mid, {'kind': 'note', 'name': f's{j}', 'result_json': {'text': 'y' * 200}})
        projects.adopt('mission', mid, None, project_id=big['id'])
        ids.append(('mission', mid))
    for i in range(5):
        pid = storage.add_program({'title': f'Big program {i}', 'member_id': 'kid', 'state': 'active'})
        projects.adopt('program', pid, None, project_id=big['id'])
        ids.append(('program', pid))
    return big['id'], ids


def scenario_rf4_a_project_with_fifty_pieces_starts_in_one_quick_transaction_and_cleanup_converges():
    build()
    pid, ids = _big_project()
    check(len(storage.get_project(pid)['pieces']) == 50, "fifty pieces")
    token = preview_ok('project', pid, dict(MOM))['token']
    patcher, seen = crash_on_stamp(len(ids))
    with patcher:
        try:
            _d().start('project', pid, dict(MOM), token)
        except Crash:
            pass
    check(seen['stamps'] == len(ids) and (seen['prior_persisted'] or 0) >= len(ids) - 1,
          f"the crash landed late in the stamping, after the others had been written: {seen}")
    check(stamped() == [] and storage.get_deletions() == [], f"a crash late in the stamping leaves nothing: {stamped()[:3]}")
    t0 = time.monotonic()
    res = _d().start('project', pid, dict(MOM), token)
    took = time.monotonic() - t0
    check(res['status'] == 'ok' and took < 10, f"start returns quickly: {took:.2f}s {res}")
    check(not access.project_visible(storage.get_project(pid), dict(MOM)), "hidden at once")
    finish(passes=40)
    for kind, rid in ids:
        check(LOAD[kind](rid) is None, f"{kind} {rid} is gone")
    check(storage.get_project(pid) is None and all(not storage.get_mission_steps(r) for k, r in ids if k == 'mission'),
          "the project and every step are gone")


# --- standalone deletes ----------------------------------------------------------------------

def scenario_a_standalone_thread_takes_its_missions_wherever_they_live():
    fx = build()
    res = preview_ok('thread', fx.ids['GT1'], dict(MOM))
    check({i['id'] for i in res['items']} == {fx.ids['GT1'], fx.ids['GM1']}, f"named: {res['items']}")
    check(_d().start('thread', fx.ids['GT1'], dict(MOM), res['token'])['status'] == 'ok', "started")
    finish()
    check(storage.get_thread(fx.ids['GT1']) is None and storage.get_mission(fx.ids['GM1']) is None,
          "the thread and its Household-homed mission are gone")
    check(storage.get_project(garage(fx)) is not None and storage.get_mission(fx.ids['GM2']) is not None,
          "the project and its other pieces stay")
    check(not any(p['id'] == fx.ids['GT1'] for p in storage.get_project(garage(fx))['pieces']), "its piece entry went")
    child = _d().preview('thread', fx.ids['GTL'], dict(KID))
    check(child.get('status') == 'refused', f"a child cannot delete a parent's thread: {child}")


def scenario_a_standalone_mission_takes_only_itself():
    fx = build()
    res = preview_ok('mission', fx.ids['GM2'], dict(MOM))
    check([i['id'] for i in res['items']] == [fx.ids['GM2']], f"named: {res['items']}")
    _d().start('mission', fx.ids['GM2'], dict(MOM), res['token'])
    finish()
    check(storage.get_mission(fx.ids['GM2']) is None and not storage.get_mission_steps(fx.ids['GM2']), "gone with its steps")
    check(storage.get_thread(fx.ids['GT1']) is not None and storage.get_project(garage(fx)) is not None, "the rest stays")


def scenario_a_standalone_program_takes_its_kit_thread_and_needs_the_projects_owner_or_a_parent():
    fx = build()
    for actor in (AUNT, KID):
        res = _d().preview('program', fx.ids['GP1'], dict(actor))
        check(res.get('status') == 'refused', f"{actor['id']} is neither the project's owner nor a parent: {res}")
    res = preview_ok('program', fx.ids['GP1'], dict(DAD))
    check({i['id'] for i in res['items']} == {fx.ids['GP1'], fx.ids['GK1'], fx.ids['GKM']}, f"named: {res['items']}")
    _d().start('program', fx.ids['GP1'], dict(DAD), res['token'])
    finish()
    for key in ('GP1', 'GK1', 'GKM'):
        kind, rid = pair(fx, key)
        check(LOAD[kind](rid) is None, f"{key} is gone")
    check(storage.get_project(garage(fx)) is not None and storage.get_project(fx.projects['household']['id']) is not None,
          "both projects stay")


def scenario_deleting_the_last_piece_leaves_the_project():
    fx = build()
    lone = projects.create({'title': 'Lone', 'goal': 'g', 'done_when': 'd', 'owner_member_id': 'mom',
                            'audience': 'household'}, dict(MOM))['project']
    tid = _thread(fx, 'LONE', 'mom', lone)
    start_ok('thread', tid, dict(MOM))
    finish()
    row = storage.get_project(lone['id'])
    check(row is not None and row['pieces'] == [] and not row.get('deleting'), f"the empty project stays: {row}")


# --- section 6: routes ---------------------------------------------------------------------

def scenario_the_routes_preview_delete_refuse_and_hide():
    fx = build()
    before = snapshot()
    r = http('mom', 'GET', f"/api/deletion/project/{garage(fx)}/preview")
    check(r.status_code == 200 and r.json().get('status') == 'ok', f"preview: {r.status_code} {r.text[:200]}")
    token = r.json()['token']
    check({i['id'] for i in r.json()['items'] if i['kind'] in PIECE_KINDS} == {fx.ids[k] for k in GARAGE_KEYS},
          "the route previews what the service does")
    hidden = http('dad', 'GET', f"/api/deletion/project/{fx.projects['mom_private']['id']}/preview")
    check(hidden.status_code == 404 and not leaked(hidden.text, words_of(fx, ['R1', 'R2', 'R3', 'R7'])),
          f"a project Dad cannot see previews as a 404, never a 403 that admits it exists: "
          f"{hidden.status_code} {hidden.text[:200]}")
    r = http('dad', 'DELETE', f"/api/projects/{fx.projects['mom_private']['id']}", json={'token': token})
    check(r.status_code == 404, f"a project the actor cannot see is a 404: {r.status_code} {r.text[:200]}")
    refusal = _d().preview('project', garage(fx), dict(AUNT))['message']
    r = http('aunt', 'GET', f"/api/deletion/project/{garage(fx)}/preview")
    check(r.status_code == 403 and r.json().get('detail') == refusal,
          f"a visible project Aunt may not delete: 403 with the service's own words: {r.status_code} {r.text[:200]}")
    r = http('aunt', 'DELETE', f"/api/projects/{garage(fx)}", json={'token': token})
    check(r.status_code == 403 and r.json().get('detail') == refusal,
          f"a refusal is a 403 with exactly its message ({refusal!r}): {r.status_code} {r.text[:200]}")
    kates = fx.projects['kate_private']['id']
    r = http('kid', 'GET', f"/api/deletion/project/{kates}/preview")
    check(r.status_code == 403 and r.json().get('detail') == ASK_A_PARENT,
          f"Kate's own project holding a mission she cannot read: {r.status_code} {r.text[:200]}")
    mom_token = http('mom', 'GET', f"/api/deletion/project/{kates}/preview").json()['token']
    r = http('kid', 'DELETE', f"/api/projects/{kates}", json={'token': mom_token})
    check(r.status_code == 403 and r.json().get('detail') == ASK_A_PARENT and not leaked(r.text, words_of(fx, ['R11'])),
          f"and her DELETE says the same, naming nothing: {r.status_code} {r.text[:200]}")
    r = http('mom', 'DELETE', f"/api/projects/{garage(fx)}", json={})
    check(r.status_code == 400 and r.json().get('detail') == TOKEN_REQUIRED,
          f"no token is a 400 that deletes nothing: {r.status_code} {r.text[:200]}")
    untouched(before, 'refused routes')
    storage.update_thread(fx.ids['GT1'], {'title': 'moved'})
    before = snapshot()
    r = http('mom', 'DELETE', f"/api/projects/{garage(fx)}", json={'token': token})
    check(r.status_code == 409 and r.json().get('detail') == CHANGED, f"a moved closure is a 409: {r.status_code} {r.text[:200]}")
    untouched(before, 'a moved closure')
    token = http('mom', 'GET', f"/api/deletion/project/{garage(fx)}/preview").json()['token']
    r = http('mom', 'DELETE', f"/api/projects/{garage(fx)}", json={'token': token})
    check(r.status_code == 200, f"the owner deletes: {r.status_code} {r.text[:200]}")
    check(http('mom', 'GET', f"/api/projects/{garage(fx)}").status_code == 404, "and the project is a 404 at once")


def scenario_the_piece_routes_take_a_token():
    fx = build()
    for kind, key, path in (('mission', 'GM2', 'missions'), ('thread', 'GTL', 'threads'), ('program', 'GP1', 'programs')):
        rid = fx.ids[key]
        r = http('mom', 'DELETE', f"/api/{path}/{rid}")
        check(r.status_code == 400 and TOKEN_REQUIRED in r.text
              and LOAD[kind](rid) is not None and not LOAD[kind](rid).get('deleting'),
              f"{kind}: a DELETE with no token is a 400 that deletes nothing: {r.status_code} {r.text[:200]}")
        token = http('mom', 'GET', f"/api/deletion/{kind}/{rid}/preview").json()['token']
        r = http('mom', 'DELETE', f"/api/{path}/{rid}", json={'token': token})
        check(r.status_code == 200, f"{kind}: deleted by hand: {r.status_code} {r.text[:200]}")
        check(LOAD[kind](rid) is None or LOAD[kind](rid).get('deleting'), f"{kind}: hidden at once")
    check(len(storage.get_deletions()) == 3, f"three deletions started: {storage.get_deletions()}")
    r = http('panel', 'DELETE', f"/api/projects/{garage(fx)}", json={'token': 'x'})
    check(r.status_code in (401, 403, 404) and storage.get_project(garage(fx)) and not storage.get_project(garage(fx)).get('deleting'),
          f"a panel never deletes: {r.status_code}")


def scenario_argyle_has_no_delete_tool():
    from services import agent_tools_v2 as tools
    names = {t['name'] for t in tools.get_available_tools()} | set(tools.TOOL_HANDLERS)
    check(not [n for n in names if 'delete' in n and any(k in n for k in ('project', 'thread', 'mission', 'program'))],
          f"deletion stays by hand only: {sorted(n for n in names if 'delete' in n)}")
    _d()   # the service exists


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
