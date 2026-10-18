"""Projects delete, cleanup (spec rev 3 section 5, `deletion.maintain()`; plan Task 1 Step 4).

After `maintain()` has run with no worker left, ZERO rows and files remain of the closure, children
before parents, each step idempotent by id:

  1. chat copies: every message whose card names a closure record (mission_id, thread_id, program_id,
     project_id) or a collected ask_id / proposal_id, and every message with a gone typed ref, deleted
     WHOLE (a mixed message never comes back with a line missing); old plain-text notices stay;
  2. ledgers: action proposals sourced from the closure, asks on closure records and on their findings;
  3. findings on closure records; commitment findings and protected exceptions of the closure
     programs' commitments, from the emissions snapshot taken before the pause;
  4. the programs' commitments (a failing delete keeps its program until it succeeds) and lessons;
  5. files: browse folders, new thread photos (under threads/<thread id>/) and legacy thread photos
     in the shared media archive;
  6. surviving records: thread-history entries summarizing a closure mission; steps naming a closure
     mission lose mission_id, attempts, found, question and stage payloads, an unfinished one becoming
     `blocked` with "Its work was deleted."; origin_mission_id, wrapped_from and pieces[] entries
     naming a closure record; a deleted thread in surviving programs' emissions.thread_ids; app-state
     keys (mission_steer, triage focus, watcher-notified, practice-pushed);
  7-9. steps, missions, threads, programs, the project row, and the deletion row itself.

Also: an interruption after each step, re-run, converges; the orphan pass removes what a racing
writer left (a late screenshot); maintenance runs with watchers off; Review Focus 2 (a restart while
a deletion is half done: startup maintenance resumes and finishes, the project hidden throughout).

Run from chauffeur/:  python tests/test_deletion_cleanup.py
"""
import hashlib
import json
import os
import re
import time
import traceback
import uuid
from unittest.mock import patch

from harness import check  # noqa: F401
from access_fixture import _mission
from test_deletion_core import (_d, build, garage, start_ok, finish, GARAGE_KEYS, pair, LOAD, WORK_DELETED, REAL_POST)
from test_subjects import MOM
from services import storage, missions, access, chat_actions, threads, triage, programs

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
       b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82')


def _msg(channel, sender, body, card=None, refs=None):
    from models.schemas import ChatMessage
    m = ChatMessage(channel_id=channel['id'], sender_member_id=sender, body=body, card=card).model_dump()
    if refs is not None:
        m['refs'] = refs
    storage.add_chat_message(m)
    return m['id']


def _files_under(*roots):
    out = set()
    for root in roots:
        for dirpath, _, names in os.walk(root):
            out |= {os.path.join(dirpath, n) for n in names}
    return out


def _roots():
    return [os.path.dirname(storage.DB_PATH)] + list(storage._media_roots())


def rich():
    """The Garage world with something attached at every step of section 5."""
    fx = build()
    missions._post = REAL_POST
    g = garage(fx)
    ids = {k: fx.ids[k] for k in GARAGE_KEYS}
    house, survivor = fx.projects['household'], fx.projects['survivor']
    # A mission homed in the Garage that summarized into a SURVIVING thread, and one whose subject is the
    # SURVIVING project (its steps name it): both go, their traces on the survivors go with them.
    _mission(fx, 'GSM', 'mom', fx.projects['garage'], subject_kind='project', subject_id=survivor['id'])
    _mission(fx, 'GHM', 'mom', fx.projects['garage'], origin_kind='thread', origin_ref=fx.ids['R5t'])
    fx.closure = dict(ids, GSM=fx.ids['GSM'], GHM=fx.ids['GHM'])
    storage.append_thread_history(fx.ids['R5t'], {'kind': 'mission', 'mission_id': fx.ids['GHM'], 'who': 'argyle',
                                                  'text': fx.secret('GHM') + ' summary', 'ts': time.time()})
    storage.append_thread_history(fx.ids['R5t'], {'kind': 'note', 'text': 'a survivor note', 'ts': time.time(), 'who': 'dad'})
    steps = [{'id': 'st-open', 'order': 0, 'title': 'Argyle finds a bakery', 'owner': 'argyle', 'needs': [], 'due_date': None,
              'state': 'doing', 'done_by': None, 'done_at': None, 'mission_id': fx.ids['GSM'], 'stage_id': 's2',
              'attempts': [{'text': fx.secret('GSM')}], 'found': {'summary': fx.secret('GSM')},
              'question': fx.secret('GSM') + '?'},
             {'id': 'st-done', 'order': 1, 'title': 'Argyle made the list', 'owner': 'argyle', 'needs': [], 'due_date': None,
              'state': 'done', 'done_by': 'argyle', 'done_at': time.time(), 'mission_id': fx.ids['GSM'], 'stage_id': 's1',
              'found': {'summary': fx.secret('GSM')}, 'question': None},
             {'id': 'st-mine', 'order': 2, 'title': 'Call the bakery', 'owner': 'mom', 'needs': [], 'due_date': None,
              'state': 'todo', 'done_by': None, 'done_at': None, 'hold': None}]
    pieces = storage.get_project(survivor['id'])['pieces'] + [{'kind': 'mission', 'id': fx.ids['GSM']},
                                                              {'kind': 'trip', 'id': 'ev_disney'}]
    storage.update_project(survivor['id'], {'steps': steps, 'origin_mission_id': fx.ids['GSM'], 'pieces': pieces,
                                            'wrapped_from': {'kind': 'mission', 'id': fx.ids['GSM']}})
    r5p = storage.get_program(fx.ids['R5p'])
    storage.update_program(fx.ids['R5p'], {'emissions': {'commitment_ids': [], 'event_ids': [],
                                                         'thread_ids': [fx.ids['GT1'], fx.ids['R5t']]}})
    # Chat: every card shape, a typed ref, a mixed message, and the three that stay.
    argyle = storage.ensure_argyle_member()['id']
    dm = storage.get_or_create_dm(argyle, 'mom')
    ask_t = storage.add_ask({'situation_kind': 'thread', 'situation_id': ids['GT1'], 'to_name': 'Pest Co',
                             'what': fx.secret('GT1'), 'channel': 'chauffeur', 'asked_by': 'mom', 'state': 'sent'})
    ask_m = storage.add_ask({'situation_kind': 'mission', 'situation_id': ids['GM2'], 'to_name': 'Dad', 'what': 'x',
                             'channel': 'chauffeur', 'asked_by': 'mom', 'state': 'sent'})
    f_thread = storage.add_finding({'subject_type': 'thread', 'subject_id': ids['GT1'], 'kind': 'thread_stall',
                                    'line': fx.secret('GT1'), 'state': 'open', 'identity': f"thread_stall:{ids['GT1']}"})
    f_mission = storage.add_finding({'subject_type': 'mission', 'subject_id': ids['GM2'], 'kind': 'mission_waiting',
                                     'line': fx.secret('GM2'), 'state': 'open', 'identity': f"mission_waiting:{ids['GM2']}"})
    f_program = storage.add_finding({'subject_type': 'program', 'subject_id': ids['GP1'], 'kind': 'program_drift',
                                     'line': fx.secret('GP1'), 'state': 'open', 'identity': f"program_drift:{ids['GP1']}"})
    ask_f = storage.add_ask({'situation_kind': 'finding', 'situation_id': f_thread, 'to_name': 'Dad', 'what': 'y',
                             'channel': 'chauffeur', 'asked_by': 'mom', 'state': 'sent'})
    prop = chat_actions.create_action_proposal('create_list', fx.secret('GM2'), {'name': 'x'}, created_by_member_id='mom',
                                               extra_allowed=missions.proposable_tools(),
                                               extra={'origin_kind': 'mission', 'origin_id': ids['GM2']})
    keep_prop = chat_actions.create_action_proposal('create_list', 'survivor', {'name': 'y'}, created_by_member_id='mom',
                                                    extra_allowed=missions.proposable_tools(),
                                                    extra={'origin_kind': 'mission', 'origin_id': fx.ids['R9b']})
    fx.gone_msgs = [
        _msg(dm, argyle, fx.secret('GM2'), card={'kind': 'mission_ask', 'mission_id': ids['GM2']}),
        _msg(dm, argyle, fx.secret('GT1'), card={'kind': 'thread', 'thread_id': ids['GT1']}),
        _msg(dm, argyle, fx.secret('GP1'), card={'kind': 'program', 'program_id': ids['GP1']}),
        _msg(dm, argyle, 'Garage started', card={'kind': 'project_start', 'project_id': g}),
        _msg(dm, 'mom', fx.secret('GT1'), card={'kind': 'ask', 'ask_id': ask_t, 'actions': []}),
        _msg(dm, argyle, fx.secret('GM2'), card=chat_actions.build_card(prop['proposal_id'], 'create_list', 'x', 'proposed')),
        _msg(dm, argyle, 'mixed: ' + fx.secret('GT1') + ' and the survivor', refs=[{'kind': 'thread', 'id': ids['GT1']},
                                                                                {'kind': 'thread', 'id': fx.ids['R5t']}]),
        _msg(dm, argyle, fx.secret('GTL'), refs=[{'kind': 'thread', 'id': ids['GTL']}]),
    ]
    fx.kept_msgs = [_msg(dm, argyle, 'An old plain notice about the garage'),
                    _msg(dm, argyle, 'survivor ref', refs=[{'kind': 'thread', 'id': fx.ids['R5t']}]),
                    _msg(dm, argyle, 'survivor card', card={'kind': 'mission_ask', 'mission_id': fx.ids['R9b']})]
    # Program emissions: commitments, their exceptions and commitment findings; a lesson.
    fx.commitments = []
    for day in (1, 3):
        cid = storage.add_protected_commitment({'id': uuid.uuid4().hex, 'member_id': 'kid', 'title': fx.title('GP1'),
                                                'days_of_week': [day], 'time_start': '17:00', 'time_end': '17:30',
                                                'active': True, 'source': {'kind': 'program', 'id': ids['GP1']}})
        fx.commitments.append(cid)
        storage.add_protected_exception(cid, '2027-01-05')
        storage.add_finding({'subject_type': 'commitment', 'subject_id': f'{cid}:ev1', 'kind': 'commitment',
                             'line': fx.secret('GP1'), 'state': 'open', 'identity': f'commitment:{cid}:ev1'})
    storage.update_program(ids['GP1'], {'state': 'active', 'emissions': {'commitment_ids': list(fx.commitments),
                                                                        'thread_ids': [ids['GK1']], 'event_ids': []}})
    storage.upsert_program_lesson(ids['GP1'], {'phase_name': 'Grade 1', 'unit_n': 0, 'session_label': ''},
                                  {'scenes': [{'type': 'say', 'text': fx.secret('GP1')}]})
    # Files: two browse folders, a new thread photo, a legacy thread photo in the shared archive.
    for key in ('GM1', 'GM2'):
        with open(os.path.join(missions.browse_dir(ids[key]), 'turn_01.png'), 'wb') as f:
            f.write(PNG)
    before = _files_under(*_roots())
    with patch.object(threads, 'read_photo', lambda *a, **k: None):
        added = threads.add_photo(ids['GT1'], PNG, 'image/png', 'mom')
    check(added.get('status') == 'ok', f"the fixture adds a photo to GT1: {added}")
    fx.new_photo_files = _files_under(*_roots()) - before
    check(fx.new_photo_files, "the fixture: the photo is a file")
    legacy = storage.save_photo_bytes(PNG, 'image/png')
    storage.append_thread_history(ids['GK1'], {'kind': 'photo', 'media_id': legacy['id'], 'url': legacy['url'],
                                               'text': 'old photo', 'who': 'mom', 'ts': time.time()})
    fx.legacy_media = legacy['id']
    check(storage.media_file_path(legacy['id']), "the fixture: the legacy photo is on disk")
    # App state naming closure records, beside survivors' keys that must stay.
    storage.set_app_state(f"mission_steer:{ids['GM2']}", {'text': 'Stop', 'ts': time.time()})
    storage.set_app_state(f"mission_steer:{fx.ids['R9b']}", {'text': 'Keep', 'ts': time.time()})
    triage.set_focus('conv:del', 'thread', ids['GT1'], fx.title('GT1'))
    triage.set_focus('conv:keep', 'thread', fx.ids['R5t'], fx.title('R5t'))
    storage.set_app_state('watcher_notified', {f"thread_stall:{ids['GT1']}": time.time(),
                                               f"mission_waiting:{ids['GM2']}": time.time(),
                                               f"thread_stall:{fx.ids['R5t']}": time.time()})
    gp1_key = hashlib.sha1(ids['GP1'].encode()).hexdigest()[:12]
    r5p_key = hashlib.sha1(fx.ids['R5p'].encode()).hexdigest()[:12]
    today = time.strftime('%Y-%m-%d')
    storage.set_app_state(programs.PUSH_STATE_KEY, [f'{gp1_key}|{today}|17:00', f"{ids['GP1']}|{today}|17:00",
                                                    f'{r5p_key}|{today}|17:00'])
    fx.survivors = {'ask_keep': storage.add_ask({'situation_kind': 'thread', 'situation_id': fx.ids['R5t'], 'to_name': 'X',
                                                 'what': 'keep', 'channel': 'chauffeur', 'asked_by': 'mom', 'state': 'sent'}),
                    'finding_keep': storage.add_finding({'subject_type': 'thread', 'subject_id': fx.ids['R5t'],
                                                         'kind': 'thread_stall', 'line': 'keep', 'state': 'open',
                                                         'identity': f"thread_stall:{fx.ids['R5t']}"}),
                    'prop_keep': keep_prop['proposal_id'], 'r5p_key': r5p_key, 'gp1_key': gp1_key}
    fx.ledger = {'asks': [ask_t, ask_m, ask_f], 'findings': [f_thread, f_mission, f_program], 'prop': prop['proposal_id']}
    check(r5p is not None, "the fixture")
    return fx


def _all_rows():
    out = {}
    for name in sorted(storage.db.tables()):
        out[name] = [dict(r) for r in storage.db.table(name).all()]
    return out


def assert_clean(fx, how):
    """Zero rows and files of the closure; every survivor intact; nothing of the mark left."""
    d = _d()
    closure = set(fx.closure.values())
    for key, rid in fx.closure.items():
        kind = 'mission' if key in ('GSM', 'GHM') else pair(fx, key)[0]
        check(LOAD[kind](rid) is None, f"{how}: {key} is gone")
        if kind == 'mission':
            check(not storage.get_mission_steps(rid), f"{how}: {key}'s steps are gone")
    check(storage.get_project(garage(fx)) is None, f"{how}: the project row is gone")
    check(storage.get_deletions() == [], f"{how}: the deletion row itself is gone")
    for mid in fx.gone_msgs:
        check(storage.get_chat_message(mid) is None, f"{how}: chat copy {mid} is deleted whole")
    for mid in fx.kept_msgs:
        check(storage.get_chat_message(mid) is not None, f"{how}: an unrelated or plain message {mid} stays")
    for aid in fx.ledger['asks']:
        check(storage.get_ask(aid) is None, f"{how}: ask {aid} is gone")
    for fid in fx.ledger['findings']:
        check(storage.get_finding(fid) is None, f"{how}: finding {fid} is gone")
    check(storage.get_action_proposal(fx.ledger['prop']) is None, f"{how}: the closure's proposal is gone")
    for cid in fx.commitments:
        check(storage.get_protected_commitment(cid) is None, f"{how}: commitment {cid} is released")
        check(not storage.get_protected_exceptions(cid), f"{how}: its exceptions are gone")
        check(not [f for f in storage.get_findings() if str(f.get('subject_id', '')).startswith(cid)],
              f"{how}: its commitment findings are gone")
    check(not storage.program_lessons_table.search(storage.Query().program_id == fx.ids['GP1']), f"{how}: lessons gone")
    for key in ('GM1', 'GM2'):
        check(not os.path.exists(os.path.join(os.path.dirname(storage.DB_PATH), 'browse', fx.ids[key])),
              f"{how}: {key}'s browse folder is gone")
    for path in fx.new_photo_files:
        check(not os.path.exists(path), f"{how}: the thread photo {path} is gone")
    for root in _roots():
        for dirpath, dirs, _ in os.walk(root):
            check(not (os.path.basename(dirpath) == fx.ids['GT1'] and os.path.basename(os.path.dirname(dirpath)) == 'threads'),
                  f"{how}: the thread's photo folder is gone: {dirpath}")
    check(storage.media_file_path(fx.legacy_media) is None, f"{how}: the legacy photo is gone from the archive")
    # Survivors.
    survivor = storage.get_project(fx.projects['survivor']['id'])
    check(survivor is not None, f"{how}: the survivor project stays")
    steps = {s['id']: s for s in survivor['steps']}
    for sid in ('st-open', 'st-done'):
        s = steps[sid]
        check(not s.get('mission_id') and not s.get('attempts') and not s.get('found') and not s.get('stage_id'),
              f"{how}: {sid} lost the deleted mission's payloads: {s}")
        check(fx.secret('GSM') not in json.dumps(s), f"{how}: {sid} carries nothing of it: {s}")
    check(steps['st-open']['state'] == 'blocked' and WORK_DELETED in json.dumps(steps['st-open']),
          f"{how}: the unfinished step is blocked with '{WORK_DELETED}': {steps['st-open']}")
    check(steps['st-done']['state'] == 'done', f"{how}: a finished step stays finished: {steps['st-done']}")
    check(steps['st-mine'] == {**steps['st-mine'], 'title': 'Call the bakery', 'owner': 'mom', 'state': 'todo'},
          f"{how}: a person's own step is untouched")
    check(not survivor.get('origin_mission_id') and not survivor.get('wrapped_from'), f"{how}: provenance pointers cleared")
    check(not [p for p in survivor['pieces'] if p['id'] in closure] and any(p['id'] == 'ev_disney' for p in survivor['pieces']),
          f"{how}: the closure's pieces entry goes, the rest stays: {survivor['pieces']}")
    r5t = storage.get_thread(fx.ids['R5t'])
    check(not [h for h in r5t.get('history') or [] if h.get('mission_id') in closure], f"{how}: the mission summary went")
    check(any(h.get('text') == 'a survivor note' for h in r5t['history']), f"{how}: the survivor's own history stays")
    check(storage.get_program(fx.ids['R5p'])['emissions']['thread_ids'] == [fx.ids['R5t']],
          f"{how}: a deleted thread leaves surviving programs' emissions")
    keys = [r['key'] for r in storage.app_state_table.all()]
    check(not [k for k in keys if any(i in k for i in closure)], f"{how}: no app-state key names a closure record")
    check(storage.get_app_state(f"mission_steer:{fx.ids['R9b']}"), f"{how}: a survivor's steer flag stays")
    focus = storage.get_app_state(triage.FOCUS_KEY) or {}
    check('conv:del' not in focus and 'conv:keep' in focus, f"{how}: triage focus: {focus}")
    notified = storage.get_app_state('watcher_notified') or {}
    check(not [k for k in notified if any(i in k for i in closure)] and f"thread_stall:{fx.ids['R5t']}" in notified,
          f"{how}: watcher-notified: {notified}")
    pushed = storage.get_app_state(programs.PUSH_STATE_KEY) or []
    check(not [k for k in pushed if fx.survivors['gp1_key'] in k or fx.ids['GP1'] in k]
          and any(fx.survivors['r5p_key'] in k for k in pushed), f"{how}: practice-pushed: {pushed}")
    check(storage.get_ask(fx.survivors['ask_keep']) and storage.get_finding(fx.survivors['finding_keep'])
          and storage.get_action_proposal(fx.survivors['prop_keep']), f"{how}: the survivors' ledgers stay")
    for key in ('SA1', 'SA2', 'R5t', 'R9b', 'R5p'):
        kind, rid = pair(fx, key)
        check(LOAD[kind](rid) is not None, f"{how}: {key} survives")
    # Nothing of the mark: no stamp, no deletion row, and no word of the closure in any table.
    words = [fx.secret(k) for k in fx.closure] + [fx.title(k) for k in fx.closure]
    dump = json.dumps(_all_rows(), default=str, ensure_ascii=False)
    found = [w for w in words if re.search(re.escape(w) + r'(?!\w)', dump)]
    check(not found, f"{how}: no word of the closure survives anywhere: {found}")
    stamps = [(name, r.get('id')) for name, rows in _all_rows().items() for r in rows if r.get('deleting')]
    check(not stamps and d.active is not None, f"{how}: no stamp survives: {stamps[:5]}")


def scenario_after_maintain_nothing_of_the_closure_remains():
    fx = rich()
    start_ok('project', garage(fx), dict(MOM))
    out = finish()
    check(out['finished'] >= 1 or storage.get_deletions() == [], f"maintain reports it finished: {out}")
    assert_clean(fx, 'one pass')


def scenario_the_emissions_snapshot_drives_the_release_even_when_the_row_forgot_them():
    fx = rich()
    start_ok('project', garage(fx), dict(MOM))
    for cid in fx.commitments:
        check(storage.get_protected_commitment(cid) is not None, "pausing for a delete released nothing")
    storage.update_program(fx.ids['GP1'], {'emissions': {'commitment_ids': [], 'thread_ids': [], 'event_ids': []}})
    finish()
    assert_clean(fx, 'snapshot')


def scenario_a_failing_commitment_delete_keeps_its_program_until_it_succeeds():
    fx = rich()
    start_ok('project', garage(fx), dict(MOM))
    real = storage.delete_protected_commitment
    stuck = fx.commitments[0]

    def flaky(cid, *a, **k):
        if cid == stuck:
            raise OSError('the commitments table is locked')
        return real(cid, *a, **k)
    with patch.object(storage, 'delete_protected_commitment', flaky):
        for _ in range(3):
            _d().maintain()
    check(storage.get_protected_commitment(stuck) is not None, "the failed commitment is still there")
    check(storage.get_program(fx.ids['GP1']) is not None, "so its program is kept until it goes")
    check(storage.get_deletions(), "and the deletion is still open")
    check(not access.project_visible(storage.get_project(garage(fx)) or {}, dict(MOM)), "hidden all the while")
    finish()
    assert_clean(fx, 'after the retry')


def _counted_writes():
    """Count the table writes one clean maintain() makes (removes and updates)."""
    from services import storage_sqlite
    seen = {'n': 0}
    real_remove, real_update = storage_sqlite.SqliteTable.remove, storage_sqlite.SqliteTable.update

    def remove(self, cond=None, doc_ids=None):
        seen['n'] += 1
        return real_remove(self, cond=cond, doc_ids=doc_ids)

    def update(self, fields, cond=None, doc_ids=None):
        seen['n'] += 1
        return real_update(self, fields, cond=cond, doc_ids=doc_ids)
    return patch.multiple(storage_sqlite.SqliteTable, remove=remove, update=update), seen


class Interrupted(BaseException):
    """A process killed mid-step (BaseException: no handler may swallow a kill)."""


def _interrupt_at(n):
    from services import storage_sqlite
    seen = {'n': 0}
    real_remove, real_update = storage_sqlite.SqliteTable.remove, storage_sqlite.SqliteTable.update

    def bump():
        seen['n'] += 1
        if seen['n'] == n:
            raise Interrupted(f'killed at write {n}')

    def remove(self, cond=None, doc_ids=None):
        bump()
        return real_remove(self, cond=cond, doc_ids=doc_ids)

    def update(self, fields, cond=None, doc_ids=None):
        bump()
        return real_update(self, fields, cond=cond, doc_ids=doc_ids)
    return patch.multiple(storage_sqlite.SqliteTable, remove=remove, update=update)


def scenario_an_interruption_after_each_step_re_run_converges():
    fx = rich()
    start_ok('project', garage(fx), dict(MOM))
    counter, seen = _counted_writes()
    with counter:
        finish()
    total = seen['n']
    check(total > 5, f"the clean run made its writes: {total}")
    assert_clean(fx, 'reference run')
    stride = max(1, total // 60)          # every write when there are few; an even spread of 60 otherwise
    for n in range(1, total + 1, stride):
        fx = rich()
        start_ok('project', garage(fx), dict(MOM))
        with _interrupt_at(n):
            try:
                _d().maintain()
            except Interrupted:
                pass
        check(not access.project_visible(storage.get_project(garage(fx)) or {}, dict(MOM)),
              f"killed at write {n}: still hidden")
        finish()
        assert_clean(fx, f"killed at write {n} of {total}, then re-run")


def scenario_the_orphan_pass_removes_what_a_racing_writer_left():
    fx = rich()
    start_ok('project', garage(fx), dict(MOM))
    finish()
    gm2, gt1, gp1 = fx.ids['GM2'], fx.ids['GT1'], fx.ids['GP1']
    late_dir = os.path.join(os.path.dirname(storage.DB_PATH), 'browse', gm2)
    os.makedirs(late_dir, exist_ok=True)
    with open(os.path.join(late_dir, 'turn_99.png'), 'wb') as f:
        f.write(PNG)                                     # a screenshot written after the check
    storage.mission_steps_table.insert({'id': uuid.uuid4().hex, 'mission_id': gm2, 'idx': 9, 'ts': time.time(),
                                        'kind': 'note', 'name': 'late', 'args_json': None, 'result_json': {}})
    storage.asks_table.insert({'id': uuid.uuid4().hex, 'situation_kind': 'thread', 'situation_id': gt1, 'state': 'sent',
                               'what': 'late'})
    storage.findings_table.insert({'id': uuid.uuid4().hex, 'subject_type': 'mission', 'subject_id': gm2, 'state': 'open',
                                   'line': 'late', 'identity': f'late:{gm2}'})
    storage.program_lessons_table.insert({'id': uuid.uuid4().hex, 'program_id': gp1, 'phase_name': 'late', 'unit_n': 0,
                                          'session_label': '', 'scenes': []})
    storage.set_app_state(f'mission_steer:{gm2}', {'text': 'late'})
    out = _d().maintain()
    check(out['orphans'] >= 1, f"the orphan pass reports what it removed: {out}")
    check(not os.path.exists(late_dir), "the late screenshot and its folder are gone")
    check(not storage.get_mission_steps(gm2), "the orphan step is gone")
    check(not [a for a in storage.asks_table.all() if a.get('situation_id') == gt1], "the orphan ask is gone")
    check(not [f for f in storage.findings_table.all() if f.get('subject_id') == gm2], "the orphan finding is gone")
    check(not storage.program_lessons_table.search(storage.Query().program_id == gp1), "the orphan lesson is gone")
    check(storage.get_app_state(f'mission_steer:{gm2}') in (None, {}), "the orphan app-state key is gone")
    check(storage.get_ask(fx.survivors['ask_keep']) and storage.get_finding(fx.survivors['finding_keep']),
          "and nothing with a living parent is touched")


def scenario_maintenance_runs_with_watchers_and_notifications_off():
    fx = rich()
    base = storage.get_settings()
    storage.get_settings = (lambda s: (lambda: dict(s)))(dict(base, proactive_watchers_enabled=False, missions_enabled=False,
                                                          programs_enabled=False, mind_enabled=False,
                                                          tomorrow_digest_enabled=False, kid_digest_enabled=False))
    start_ok('project', garage(fx), dict(MOM))
    finish()
    assert_clean(fx, 'watchers off')


def scenario_rf2_a_restart_mid_cleanup_resumes_at_startup_and_stays_hidden():
    from fastapi.testclient import TestClient
    import main
    fx = rich()
    base = storage.get_settings()
    storage.get_settings = (lambda s: (lambda: dict(s)))(dict(base, proactive_watchers_enabled=False))
    start_ok('project', garage(fx), dict(MOM))
    with _interrupt_at(4):
        try:
            _d().maintain()
        except Interrupted:
            pass
    check(storage.get_deletions(), "the deletion is half done")
    for viewer in (dict(MOM), access.HOUSE, access.HOUSE_PARENT):
        check(not access.project_visible(storage.get_project(garage(fx)) or {}, viewer), "hidden while half done")
    for key in GARAGE_KEYS:
        kind, rid = pair(fx, key)
        row = LOAD[kind](rid)
        check(row is None or access.record_view(kind, row, dict(MOM)) is None, f"{key} hidden while half done")
    with patch.object(main, 'trigger_background_refresh', lambda *a, **k: None):
        with TestClient(main.app):                      # a restart: the lifespan runs startup maintenance
            deadline = time.monotonic() + 20
            while storage.get_deletions() and time.monotonic() < deadline:
                time.sleep(0.2)
    check(storage.get_deletions() == [], "startup maintenance resumed and finished it")
    assert_clean(fx, 'after the restart')


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
