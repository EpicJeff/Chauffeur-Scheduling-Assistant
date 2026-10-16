"""Function-level cells of the project access rule (spec §3, §7 table).

Run from chauffeur/: python tests/test_access_core.py
"""
import traceback

from harness import check
import access_fixture
from services import access, storage, threads

F, K, X = 'full', 'keeper', None
# Spec §7, the person's-own-surface table. Columns: mom dad aunt kid hal pat house.
TABLE = {
    'R1':  (F, X, K, X, X, X, X),
    'R2':  (F, X, K, X, X, X, X),
    'R3':  (F, F, X, K, X, X, X),
    'R4':  (F, F, X, X, X, X, X),
    'R5t': (F, F, F, X, X, X, F),
    'R5p': (F, F, F, F, X, X, F),
    'R6':  (F, X, X, F, X, X, X),
    'R7':  (F, X, X, K, X, X, X),
    'R8':  (F, F, X, X, X, X, X),
    'R10': (F, K, X, X, X, X, X),
    'R11': (F, F, X, X, X, X, X),
    'R12': (F, F, X, X, X, X, X),
}
COLS = ('mom', 'dad', 'aunt', 'kid', 'hal', 'pat', 'house')
# Spec section 7 Acting: visibility is necessary; keeper missions additionally
# restrict verbs. Existing endpoint role checks still apply to visible records.
ACT = {rkey: {col: F if value is not None else None for col, value in zip(COLS, row)}
       for rkey, row in TABLE.items()}
MISSION_KEEPER_VERBS = frozenset({'ack', 'delete', 'steer'})
KIND = {'R1': 'thread', 'R2': 'mission', 'R3': 'program', 'R4': 'thread', 'R5t': 'thread',
        'R5p': 'program', 'R6': 'thread', 'R7': 'thread', 'R8': 'thread', 'R10': 'thread',
        'R11': 'mission', 'R12': 'thread', 'R13': 'thread', 'R9origin': 'thread',
        'R9a': 'mission', 'R9b': 'mission'}


def load(fx, rkey):
    kind = KIND[rkey]
    rid = fx.ids[rkey]
    return kind, {'thread': storage.get_thread, 'mission': storage.get_mission,
                  'program': storage.get_program}[kind](rid)


def scenario_the_table():
    fx = access_fixture.build()
    bad = []
    for rkey, row in TABLE.items():
        kind, rec = load(fx, rkey)
        for col, want in zip(COLS, row):
            got = access.record_view(kind, rec, fx.viewers[col])
            if got != want:
                bad.append(f'{rkey} {col}: want {want} got {got}')
    check(not bad, '\n'.join(bad))


def scenario_legacy_wrapped_record_is_as_today():
    fx = access_fixture.build()
    kind, rec = load(fx, 'R13')
    for col in ('mom', 'dad', 'aunt', 'house'):
        check(access.record_view(kind, rec, fx.viewers[col]) == 'full', f'R13 {col}')
    check(access.record_view(kind, rec, fx.viewers['kid']) is None, 'R13 kid base')
    check(access.record_view(kind, rec, fx.viewers['pat']) is None, 'R13 pat inactive')


def scenario_house_parent_reads_parents_subjects_not_projects():
    fx = access_fixture.build()
    kind, rec = load(fx, 'R8')
    check(access.record_view(kind, rec, access.HOUSE_PARENT) == 'full', 'parents-only subject is HOUSE_PARENT')
    kind, rec = load(fx, 'R4')
    check(access.record_view(kind, rec, access.HOUSE_PARENT) is None, 'a parents PROJECT never opens to HOUSE')


def scenario_inactive_keeper_and_viewer():
    fx = access_fixture.build()
    storage.update_member('aunt', {'status': 'disabled'})
    kind, rec = load(fx, 'R1')
    check(access.record_view(kind, rec, dict(fx.viewers['aunt'], status='disabled')) is None, 'disabled keeper sees nothing')
    check(access.record_view(kind, rec, fx.viewers['dad']) is None, 'disabled keeper does not open the record')
    tid = threads.create(title='Unowned', owner_member_id='', created_by='mom',
                         project_id=fx.projects['mom_private']['id'])
    row = storage.get_thread(tid)
    check(access.record_view('thread', row, access.HOUSE) is None, 'empty owner never matches HOUSE (M1)')
    check(access.keeper_id('thread', row) is None, 'empty keeper id')


def scenario_sibling_is_not_a_parent():
    fx = access_fixture.build()
    kind, rec = load(fx, 'R3')
    check(access.record_view(kind, rec, fx.viewers['sib']) is None, 'a sibling is not a parent of the child keeper')


def scenario_subject_cycle():
    fx = access_fixture.build()
    a = threads.create(title='A', owner_member_id='mom', created_by='mom')
    b = threads.create(title='B', owner_member_id='mom', created_by='mom',
                       project_id=fx.projects['mom_private']['id'])
    storage.update_thread(a, {'subject_kind': 'thread', 'subject_id': b})
    storage.update_thread(b, {'subject_kind': 'thread', 'subject_id': a})
    check(access.record_view('thread', storage.get_thread(a), fx.viewers['dad']) is None, 'cycle hides A from Dad')
    check(access.record_view('thread', storage.get_thread(b), fx.viewers['dad']) is None, 'cycle hides B from Dad')


def scenario_missing_home_project():
    fx = access_fixture.build()
    tid = threads.create(title='Orphan', owner_member_id='dad', created_by='dad')
    storage.update_thread(tid, {'project_id': 'prj-gone'})
    check(access.record_view('thread', storage.get_thread(tid), fx.viewers['aunt']) == 'full',
          'a deleted home project falls back to today')


def scenario_actable():
    fx = access_fixture.build()
    _, r2 = load(fx, 'R2')
    aunt, dad = fx.viewers['aunt'], fx.viewers['dad']
    check(not access.record_actable('mission', r2, dad, 'answer'), 'Dad cannot act on R2')
    for verb in ('ack', 'delete', 'steer'):
        check(access.record_actable('mission', r2, aunt, verb), f'keeper may {verb}')
    for verb in ('approve_plan', 'run_stage', 'answer', 'release', 'submit', 'verify'):
        check(not access.record_actable('mission', r2, aunt, verb), f'keeper may not {verb}')
    _, r3 = load(fx, 'R3')
    check(access.record_actable('program', r3, fx.viewers['kid'], 'session'), 'child keeper acts on her program')


def scenario_situations_view_uses_the_rule():
    fx = access_fixture.build()
    from services import situations, planned
    v = situations.view('thread', fx.ids['R1'], fx.viewers['aunt'])
    check(v and fx.secret('R1') not in str(v), f'thread keeper redaction: {v}')
    check(situations.view('thread', fx.ids['R1'], fx.viewers['dad']) is None, 'Dad gets nothing')
    m = storage.get_mission(fx.ids['R2'])
    check(planned.is_keeper(m, fx.viewers['aunt']), 'planned.is_keeper follows access')
    v = situations.view('mission', fx.ids['R2'], fx.viewers['aunt'])
    check(v and fx.secret('R2') not in str(v), f'mission keeper projection: {v}')


def scenario_wrapper_project_follows_its_record():
    fx = access_fixture.build()
    from services import projects
    wrapper = projects.project_for('thread', fx.ids['R13'])
    check(access.project_visible(wrapper, access.HOUSE), 'HOUSE sees a wrapper of a household-visible record')
    check(access.project_visible(fx.projects['household'], access.HOUSE), 'HOUSE sees a household project')
    check(not access.project_visible(fx.projects['mom_private'], access.HOUSE), 'HOUSE never sees a private project')


def scenario_program_subject_keeper_reads_it():
    """Codex T1 review #1: Aunt's program in Mom's private project; Aunt's own household
    thread about it stays visible to Aunt (a program keeper reads the whole program)."""
    fx = access_fixture.build()
    pid = storage.add_program({'title': 'Aunt piano', 'member_id': 'aunt', 'state': 'active'})
    from services import projects
    projects.adopt('program', pid, None, project_id=fx.projects['mom_private']['id'])
    tid = threads.create(title='About piano', owner_member_id='aunt', created_by='aunt',
                         project_id=fx.projects['household']['id'])
    storage.update_thread(tid, {'subject_kind': 'program', 'subject_id': pid})
    row = storage.get_thread(tid)
    check(access.record_view('thread', row, fx.viewers['aunt']) == 'full', 'program keeper reads the thread about it')
    check(access.record_view('thread', row, fx.viewers['dad']) is None, 'Dad cannot see the private program, so not the thread')


def scenario_legacy_id_less_sentinels_are_house():
    """Codex T1 review #2: _REGISTRY_READER and missions.read_viewer's dicts read as HOUSE."""
    fx = access_fixture.build()
    from services import agent_tools_v2
    kind, rec = load(fx, 'R5t')
    check(access.record_view(kind, rec, agent_tools_v2._REGISTRY_READER) == 'full', 'registry reader sees household')
    kind, rec = load(fx, 'R1')
    check(access.record_view(kind, rec, agent_tools_v2._REGISTRY_READER) is None, 'registry reader never sees private')
    kind, rec = load(fx, 'R8')
    check(access.record_view(kind, rec, {'id': None, 'role': 'parent'}) == 'full', 'legacy parent sentinel = HOUSE_PARENT')
    check(access.record_view(kind, rec, None) is None, 'None is still nobody')


def scenario_batch_memoises_projects():
    fx = access_fixture.build()
    calls = {'n': 0}
    real = storage.get_project
    def counting(pid):
        calls['n'] += 1
        return real(pid)
    storage.get_project = counting
    try:
        _, r1 = load(fx, 'R1')
        with access.batch():
            for _ in range(5):
                access.record_view('thread', r1, fx.viewers['mom'])
        check(calls['n'] <= 2, f'one project lookup per batch, got {calls["n"]}')
    finally:
        storage.get_project = real


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
