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
    'R3':  (F, X, X, K, X, X, X),
    'R4':  (F, F, X, X, X, X, X),
    'R5t': (F, F, F, X, X, X, F),
    'R5p': (F, F, F, F, X, X, F),
    'R6':  (F, X, X, F, X, X, X),
    'R7':  (F, X, X, K, X, X, X),
    'R8':  (F, F, X, X, X, X, X),
    'R10': (F, K, X, X, X, X, X),
    'R11': (F, F, X, X, X, X, X),
    'R12': (F, F, X, X, X, X, X),
    # Project audiences on the shared model (spec 2026-10-16). R14/R15: a child's private
    # project whose explicit list leaves Dad out; the parent-of-child-keeper bypass yields to it.
    'R14': (F, X, X, F, X, X, X),
    'R15': (F, X, X, F, X, X, X),
    # R16: a `shared` project is the parents plus its list (Aunt); the child and helper are out.
    'R16': (F, F, F, X, X, X, X),
    # Mom owns this private [Mom, Kate] home; Dad gets no child-keeper exception.
    'R17': (F, X, X, F, X, X, X),
}
COLS = ('mom', 'dad', 'aunt', 'kid', 'hal', 'pat', 'house')
# Spec section 7 Acting: visibility is necessary; keeper missions additionally
# restrict verbs. Existing endpoint role checks still apply to visible records.
ACT = {rkey: {col: F if value is not None else None for col, value in zip(COLS, row)}
       for rkey, row in TABLE.items()}
# Task 3 binding follow-up ruling: drop and own remain available to keepers.
MISSION_KEEPER_VERBS = frozenset({'ack', 'delete', 'steer', 'drop', 'own'})
KIND = {'R1': 'thread', 'R2': 'mission', 'R3': 'program', 'R4': 'thread', 'R5t': 'thread',
        'R5p': 'program', 'R6': 'thread', 'R7': 'thread', 'R8': 'thread', 'R10': 'thread',
        'R11': 'mission', 'R12': 'thread', 'R13': 'thread', 'R14': 'thread', 'R15': 'program',
        'R16': 'thread', 'R17': 'program', 'R9origin': 'thread',
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
    # Dad's plain thread is open to the house and every adult, so its wrapper is born household
    # (audience spec rev 3: judged by secrecy, not role): nobody gains or loses it.
    for col in ('mom', 'dad', 'aunt', 'house'):
        check(access.record_view(kind, rec, fx.viewers[col]) == 'full', f'R13 {col}')
    check(access.record_view(kind, rec, fx.viewers['kid']) is None, 'R13 kid base')
    check(access.record_view(kind, rec, fx.viewers['pat']) is None, 'R13 pat inactive')


def scenario_house_parent_reads_parents_subjects_not_projects():
    fx = access_fixture.build()
    kind, rec = load(fx, 'R8')
    check(access.record_view(kind, rec, access.HOUSE_PARENT) == 'full', 'parents-only subject is HOUSE_PARENT')
    # Audience spec rev 3: HOUSE_PARENT passes household, parents and shared projects (the shared
    # model's parent bypass), HOUSE only household, and neither ever opens a private list.
    kind, rec = load(fx, 'R4')
    check(access.record_view(kind, rec, access.HOUSE_PARENT) == 'full', 'a parents PROJECT opens to HOUSE_PARENT')
    check(access.record_view(kind, rec, access.HOUSE) is None, 'a parents PROJECT never opens to HOUSE')
    for key in ('R1', 'R14', 'R15'):
        kind, rec = load(fx, key)
        check(access.record_view(kind, rec, access.HOUSE_PARENT) is None, f'{key}: a private list never opens to HOUSE_PARENT')
    kind, rec = load(fx, 'R16')
    check(access.record_view(kind, rec, access.HOUSE_PARENT) == 'full', 'a shared PROJECT opens to HOUSE_PARENT')
    check(access.record_view(kind, rec, access.HOUSE) is None, 'a shared PROJECT never opens to HOUSE')


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


def scenario_moms_private_list_also_decides_for_a_child_keepers_program():
    fx = access_fixture.build()
    kind, rec = load(fx, 'R17')
    check(access.private_recipients(kind, rec) == ['kid', 'mom'],
          'R17 recipients retain Kate and Mom, never Dad despite being a parent of the keeper')
    from services import projects
    project = fx.projects['mom_no_dad']
    storage.update_project(project['id'], {'steps': [{'id': 'r17-hold', 'title': fx.secret('R17'),
        'owner': 'kid', 'state': 'todo', 'needs': [], 'order': 0,
        'hold': {'date': '2026-10-16', 'start': '17:00', 'end': '17:30'}}]})
    import datetime
    day = datetime.date(2026, 10, 16)
    for col in ('mom', 'kid', 'dad', 'house'):
        holds = projects.calendar_holds(day, day, fx.viewers[col])
        own = [h for h in holds if h['project_id'] == project['id']]
        check(own and (fx.secret('R17') in str(own)) == (col in ('mom', 'kid')),
              f'R17 hold words follow Mom private list for {col}: {own}')


def scenario_moms_private_program_signal_dms_only_mom_and_kate():
    import datetime
    from unittest.mock import patch
    from services import watchers, findings
    import main
    fx = access_fixture.build()
    finding = findings.make('r17-private', fx.secret('R17'), subject_type='program', subject_id=fx.ids['R17'])
    storage.chat_messages_table.truncate()
    with patch.object(watchers, 'collect_findings', return_value=([finding], [])), \
         patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         patch.object(main, '_push_message_event'), patch.object(main, '_fanout_message_notifications'):
        watchers.run_watchers(datetime.datetime(2026, 10, 16, 17, 0))
    argyle = storage.ensure_argyle_member()
    for col in ('mom', 'kid', 'dad', 'aunt'):
        dm = storage.get_or_create_dm(argyle['id'], col)
        messages = storage.get_channel_messages(dm['id'])
        check((fx.secret('R17') in str(messages)) == (col in ('mom', 'kid')),
              f'R17 real stored DM follows Mom private list for {col}: {messages}')
        if col in ('dad', 'aunt'):
            check(not messages, f'{col} receives nothing')


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
    for verb in ('ack', 'delete', 'steer', 'drop', 'own'):
        check(access.record_actable('mission', r2, aunt, verb), f'keeper may {verb}')
    for verb in ('approve_plan', 'run_stage', 'answer', 'release', 'submit', 'verify', 'subject'):
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


def scenario_wrapper_project_has_its_own_audience():
    fx = access_fixture.build()
    from services import projects
    wrapper = projects.project_for('thread', fx.ids['R13'])
    check(wrapper['audience'] == 'household' and access.project_visible(wrapper, access.HOUSE),
          'a wrapper of a record open to the house is born household, by its own audience')
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


def scenario_batches_index_live_missions_and_reuse_situation_rows():
    from unittest.mock import patch
    from collections import Counter
    from services import situations, subjects, study, home_board, missions, agent_tools_v2 as tools
    from test_access_calendar import NOW
    import json
    fx = access_fixture.build()
    tid = fx.ids['R5t']
    for n in (1, 2):
        mid = storage.add_mission({'goal': 'Origin work', 'status': 'waiting_user', 'created_by': 'dad',
            'origin_kind': 'thread', 'origin_ref': tid, 'created_at': n,
            'project_id': fx.projects['household']['id']})
    with patch.object(storage, 'get_missions', wraps=storage.get_missions) as reads:
        with access.batch():
            for key in ('R1', 'R4', 'R5t', 'R6', 'R7', 'R10'):
                row = storage.get_thread(fx.ids[key])
                subjects.subject_records('thread', row)
                access.record_view('thread', row, fx.viewers['mom'])
            with access.batch():
                check(situations._thread_mission(storage.get_thread(tid))['id'] == mid, 'newest origin mission wins')
        check(sum(c.kwargs.get('status') == missions.LIVE for c in reads.call_args_list) == 1,
              'one live mission scan across nested batches: ' + str(reads.call_args_list))
    storage.update_mission(mid, {'status': 'done'})
    check(situations._thread_mission(storage.get_thread(tid))['id'] != mid, 'no mission index survives a batch')

    storage.add_finding({'kind': 'thread_stall', 'state': 'open', 'line': 'Origin needs attention',
                        'subject_type': 'thread', 'subject_id': tid})
    config = json.dumps([{'id': 'batch-proof', 'type': 'mind'}])
    home_board.invalidate_cache()
    calls = [('Study', lambda: study.state(fx.viewers['mom'], NOW)),
             ('board', lambda: home_board.build(config, now=NOW, viewer=fx.viewers['mom'])),
             ('router listing', lambda: tools.list_situations(acting_member=fx.viewers['mom']))]
    for name, run in calls:
        with patch.object(storage, 'get_missions', wraps=storage.get_missions) as reads:
            result = run()
        scans = sum(c.kwargs.get('status') == missions.LIVE for c in reads.call_args_list)
        check(result and scans == 1, f'{name}: expected one live origin scan, got {scans}')
    with patch.object(situations, 'load', wraps=situations.load) as reads:
        result = situations.list_situations(fx.viewers['mom'], kinds=('thread',))
    counts = Counter(c.args for c in reads.call_args_list if c.args[0] == 'thread')
    check(result and counts and max(counts.values()) == 1, 'list_situations loads each thread once: ' + str(counts))
    with patch.object(storage, 'get_mission', wraps=storage.get_mission) as rows, \
         patch.object(storage, 'get_mission_steps', wraps=storage.get_mission_steps) as steps:
        result = situations.list_situations(fx.viewers['mom'], kinds=('mission',))
    for label, reads in (('mission rows', rows), ('mission steps', steps)):
        counts = Counter(c.args[0] for c in reads.call_args_list)
        check(result and counts and max(counts.values()) == 1,
              'list_situations loads ' + label + ' once: ' + str(counts))
    with patch.object(situations, 'load', wraps=situations.load) as reads:
        result = tools.list_situations(kinds='thread', acting_member=fx.viewers['mom'])
    check(result['situations'] and not any(c.args[0] == 'thread' for c in reads.call_args_list),
          'router listing renders its enumerated rows without reloading them')
    with patch.object(situations, 'load', wraps=situations.load) as reads:
        result = situations.list_situations(fx.viewers['mom'], kinds=('mission',))
    counts = Counter(c.args for c in reads.call_args_list if c.args[0] == 'mission')
    check(result and counts and max(counts.values()) == 1, 'list_situations loads each mission once: ' + str(counts))
    with patch.object(storage, 'get_mission_steps', wraps=storage.get_mission_steps) as steps:
        result = tools.list_situations(kinds='mission', acting_member=fx.viewers['mom'])
    counts = Counter(c.args[0] for c in steps.call_args_list)
    check(result['situations'] and counts and max(counts.values()) == 1,
          'router listing hydrates each visible mission once: ' + str(counts))
    with patch.object(storage, 'get_mission_steps', wraps=storage.get_mission_steps) as steps:
        check(situations.view('mission', fx.ids['R2'], fx.viewers['dad'],
                              row=storage.get_mission(fx.ids['R2'])) is None, 'hidden mission stays absent')
    check(not steps.called, 'visibility is checked before hydrating an enumerated mission')


def scenario_pruned_subjects_and_chat_history_stay_until_explicitly_deleted():
    from unittest.mock import patch
    fx = access_fixture.build()
    tid = fx.ids['R10']
    targets = [('thread', fx.ids['R1']), ('mission', fx.ids['R2']),
               ('program', fx.ids['R3']), ('project', fx.projects['mom_private']['id'])]
    storage.deletions_table.truncate()
    for kind, rid in targets:
        getattr(storage, kind + 's_table').remove(storage.Query().id == rid)
        storage.update_thread(tid, {'subject_kind': kind, 'subject_id': rid, 'subject_history': []})
        message = {'id': 'old-' + kind, 'card': {kind + '_id': rid}, 'refs': [{'kind': kind, 'id': rid}]}
        check(not access.gone(kind, None, rid=rid), 'retention alone is not deletion')
        check(storage.message_visible(message), 'a pruned card/ref keeps its chat history')
        check(access.record_view('thread', storage.get_thread(tid), fx.viewers['mom']) == 'full',
              'a pruned subject keeps the previous audience')
        did = storage.add_deletion({'kind': kind, 'root_id': rid, 'closure': [[kind, rid]], 'state': 'started'})
        with patch.object(storage, 'get_deletions', wraps=storage.get_deletions) as reads, access.batch():
            check(access.gone(kind, None, rid=rid) and not storage.message_visible(message), 'open deletion hides absent targets')
            check(access.record_view('thread', storage.get_thread(tid), fx.viewers['mom']) is None,
                  'open deletion keeps the survivor private')
            check(reads.call_count == 1, 'nested readers index open deletions once per batch')
        storage.delete_deletion(did)
        # Cleanup flags a matching entry before dropping the deletion row.
        storage.update_thread(tid, {'subject_history': [{'kind': kind, 'id': rid},
                                                       {'kind': kind, 'id': rid, 'gone': True}]})
        check(access.record_view('thread', storage.get_thread(tid), fx.viewers['mom']) is None,
              'a later flagged duplicate must not be lost')
        check(access.record_view('thread', storage.get_thread(tid), fx.viewers['dad']) == 'keeper',
              'the survivor keeper retains the neutral view')
        storage.update_thread(tid, {'owner_member_id': 'mom'})
        check(access.record_view('thread', storage.get_thread(tid), fx.viewers['mom']) == 'keeper'
              and access.record_view('thread', storage.get_thread(tid), fx.viewers['dad']) is None,
              'a flagged pointer stays closed after the keeper changes')
        storage.update_thread(tid, {'owner_member_id': 'dad'})
        storage.update_thread(tid, {'subject_history': [], 'subject_kind': None, 'subject_id': None,
                                   'subject': {'kind': kind, 'id': rid, 'gone': True}})
        check(access.record_view('thread', storage.get_thread(tid), fx.viewers['mom']) is None,
              'a flagged structured subject is also unreadable')
        storage.update_thread(tid, {'subject': None})
    for kind, card_key in (('ask', 'ask_id'), ('proposal', 'proposal_id')):
        check(storage.message_visible({'card': {card_key: 'pruned-ledger'}}), 'pruned ledger cards remain readable')
    finding = {'subject_type': 'thread', 'subject_id': 'pruned-source'}
    check(not access.finding_visible(finding, fx.viewers['mom'])
          and access.finding_view(finding, fx.viewers['mom']) is None, 'missing-source findings still hide')


def scenario_channel_list_shares_ref_resolution_across_counts_and_previews():
    from unittest.mock import patch
    from access_shared_signals import request
    fx = access_fixture.build()
    storage.chat_messages_table.truncate()
    storage.ensure_family_channel()
    argyle = storage.ensure_argyle_member()['id']
    channels = [storage.get_family_channel(), storage.get_or_create_dm(argyle, 'mom')]
    for n, channel in enumerate(channels):
        storage.add_chat_message({'id': f'batch-proof-{n}', 'channel_id': channel['id'],
                                  'sender_member_id': argyle, 'ts': 1, 'body': 'shared-ref proof',
                                  'refs': [{'kind': 'thread', 'id': fx.ids['R5t']}]})
    with patch.object(storage, 'get_thread', wraps=storage.get_thread) as refs, \
         patch.object(storage, 'get_deletions', wraps=storage.get_deletions) as deletions:
        response = request(fx, 'mom', 'GET', '/api/channels?member_id=mom')
    check(response.status_code == 200 and response.text.count('shared-ref proof') == 2, response.text)
    check(refs.call_count == 1 and deletions.call_count == 1,
          f'one reference load and deletion index across the entire request: {refs.call_count}, {deletions.call_count}')


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
