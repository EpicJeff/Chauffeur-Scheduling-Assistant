"""Revision-checked next-action completion and restore (spec 2026-10-20-projects-one-list §2.2-2.3).
Run from chauffeur/: python tests/test_thread_next_action_rev.py"""
from unittest.mock import patch

from harness import check  # noqa: F401
from services import storage, threads
from test_front_door_chat import _fresh


def _t(**kw):
    return threads.create(title='Tiler', owner_member_id='mom', created_by='mom',
                          next_action=kw.pop('next_action', 'Call Ace back'), next_action_at=kw.pop('next_action_at', '2030-02-01'), **kw)


def scenario_advance_bumps_rev():
    _fresh()
    tid = _t()
    check(int(storage.get_thread(tid).get('next_action_rev') or 0) == 0, "a new thread starts at rev 0")
    threads.advance(tid, 'Email Ace', None, who='mom')
    check(storage.get_thread(tid)['next_action_rev'] == 1, "advance bumps the revision")


def scenario_complete_clears_and_logs():
    _fresh()
    tid = _t()
    r = threads.complete_next_action(tid, 0, 'mom')
    row = storage.get_thread(tid)
    check(r['status'] == 'success' and row['next_action'] == '' and row['next_action_at'] is None and row['next_action_rev'] == 1,
          f"complete clears the action and bumps: {r} {row}")
    entry = row['history'][-1]
    check(entry['kind'] == 'completed' and entry['next_action'] == 'Call Ace back' and entry['next_action_at'] == '2030-02-01'
          and entry['entry_id'] == r['entry_id'] and entry['who'] == 'mom', f"the completed entry keeps the action and its date: {entry}")


def scenario_complete_refuses_a_stale_rev():
    _fresh()
    tid = _t()
    threads.advance(tid, 'Email Ace', None, who='dad')
    r = threads.complete_next_action(tid, 0, 'mom')
    check(r['status'] == 'error' and r['code'] == 409 and storage.get_thread(tid)['next_action'] == 'Email Ace',
          f"a stale revision completes nothing: {r}")


def scenario_restore_only_while_empty_and_latest():
    _fresh()
    tid = _t()
    done = threads.complete_next_action(tid, 0, 'mom')
    r = threads.restore_next_action(tid, done['entry_id'], 'mom')
    row = storage.get_thread(tid)
    check(r['status'] == 'success' and row['next_action'] == 'Call Ace back' and row['next_action_at'] == '2030-02-01'
          and row['next_action_rev'] == 2, f"restore puts the action and date back: {row}")
    done2 = threads.complete_next_action(tid, 2, 'mom')
    threads.advance(tid, 'Email Ace', None, who='mom')
    r = threads.restore_next_action(tid, done2['entry_id'], 'mom')
    check(r['status'] == 'error' and r['code'] == 409 and storage.get_thread(tid)['next_action'] == 'Email Ace',
          f"restore refuses once a successor is set: {r}")


def scenario_draft_carries_the_rev_and_the_finisher_respects_it():
    _fresh()
    tid = _t()
    with patch.object(threads, '_pool_call', lambda *a, **k: {'subject': 'Hi', 'body': 'Hello'}):
        d = threads.draft_message(tid, 'ask for a quote')
    check(d['status'] == 'ok' and d['next_action_rev'] == 0, f"a draft names the revision it was made against: {d}")
    threads.complete_next_action(tid, 0, 'mom')
    threads.advance(tid, 'Email Ace', None, who='mom')
    # The mission finisher (missions.py ~1433) advances the thread only when the revision it captured is current.
    from services import missions
    captured = 0
    missions._land_finish({'id': 'm1', 'origin_kind': 'thread', 'origin_ref': tid, 'goal': 'g'},
                          {'summary': 'Called Ace', 'next_action': 'Wait for the quote'}, next_action_rev=captured)
    row = storage.get_thread(tid)
    check(row['next_action'] == 'Email Ace', f"a late finisher never overwrites a newer next action: {row['next_action']}")
    check(any(h.get('kind') == 'mission' and 'earlier next step' in (h.get('text') or '') for h in row['history']),
          "the finisher's note says it was against an earlier next step")


def scenario_missing_empty_and_nonlatest_refuse_without_writes():
    _fresh()
    check(threads.complete_next_action('missing', 0, 'mom')['code'] == 404, 'missing completion is 404')
    check(threads.restore_next_action('missing', 'missing', 'mom')['code'] == 404, 'missing restore is 404')
    tid = _t()
    first = threads.complete_next_action(tid, 0, 'mom')
    empty = storage.get_thread(tid)
    check(threads.complete_next_action(tid, 1, 'mom')['code'] == 409, 'an empty action cannot be completed')
    check(storage.get_thread(tid) == empty, 'an empty completion writes nothing')
    restored = threads.restore_next_action(tid, first['entry_id'], 'dad')
    check(restored == {'status': 'success', 'entry_id': first['entry_id'], 'rev': 2},
          f'restore returns its identity and revision: {restored}')
    check(storage.get_thread(tid)['history'][-1]['who'] == 'dad', 'restore logs the actor')
    second = threads.complete_next_action(tid, 2, 'mom')
    latest = storage.get_thread(tid)
    check(latest['history'][-1]['rev_before'] == 2 and second['rev'] == 3, 'completion logs the captured revision')
    check(threads.restore_next_action(tid, first['entry_id'], 'mom')['code'] == 409, 'only the latest completion restores')
    check(threads.restore_next_action(tid, 'missing', 'mom')['code'] == 409, 'an unknown entry cannot restore')
    check(storage.get_thread(tid) == latest, 'refused restores write nothing')


def scenario_draft_lands_after_the_action_changes():
    _fresh()
    tid = _t()

    def model(*a, **k):
        threads.complete_next_action(tid, 0, 'mom')
        threads.advance(tid, 'Email Ace', None, who='mom')
        return {'subject': 'Hi', 'body': 'Hello'}

    with patch.object(threads, '_pool_call', model):
        draft = threads.draft_message(tid, 'ask for a quote')
    row = storage.get_thread(tid)
    check(draft['status'] == 'ok' and draft['next_action_rev'] == 0, 'draft keeps the pre-model revision')
    check(row['next_action'] == 'Email Ace' and row['next_action_rev'] == 2, 'late drafting leaves the successor alone')
    check(row['history'][-1]['kind'] == 'drafted'
          and 'drafted against an earlier next step' in row['history'][-1]['text'],
          f'the late draft is marked in history: {row["history"][-1]}')


def scenario_mission_draft_revision_survives_until_finish():
    from services import missions
    for stale in (False, True):
        _fresh()
        tid = _t()
        mid = storage.add_mission({'goal': 'Contact Ace', 'created_by': 'mom', 'status': 'running',
                                   'origin_kind': 'thread', 'origin_ref': tid})
        with patch.object(threads, '_pool_call', return_value={'subject': 'Hi', 'body': 'Hello'}), \
                patch.object(missions, '_llm', return_value={'action': 'draft', 'intent': 'say hello'}):
            missions.step(storage.get_mission(mid))
        drafts = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'draft']
        check(drafts[-1]['result_json']['next_action_rev'] == 0, 'the mission saves the draft revision')
        if stale:
            threads.complete_next_action(tid, 0, 'mom')
            threads.advance(tid, 'Email Ace', None, who='mom')
        with patch.object(missions, '_llm', return_value={'action': 'finish', 'summary': 'Draft ready',
                                                         'next_action': 'Review the draft'}), \
                patch.object(missions, '_dm_person') as dm:
            missions.step(storage.get_mission(mid))
        row = storage.get_thread(tid)
        check(storage.get_mission(mid)['status'] == 'done', 'the real mission finish executes')
        check(row['next_action'] == ('Email Ace' if stale else 'Review the draft'),
              f'the finisher checks the persisted revision (stale={stale}): {row}')
        entry = row['history'][-1]
        check(entry['kind'] == 'mission' and entry['next_action'] == (None if stale else 'Review the draft'),
              'a stale finish offers no outdated next action')
        check(('earlier next step' in entry['text']) == stale, 'only the stale finish is annotated')
        check(('Next: Review the draft' in dm.call_args.args[1]) != stale,
              'the stale DM does not propose the superseded next step')


def scenario_planned_thread_draft_revision_reaches_the_finisher():
    from services import missions, planned
    from test_planned_missions import _fresh as fresh_plan, _approved
    for tool in ('draft_thread_message', 'draft_message'):
        fresh_plan()
        tid = _t()
        mid = _approved([{'id': 's1', 'kind': 'build', 'title': 'Draft', 'why': '', 'makes': ['a draft']}])
        storage.update_mission(mid, {'origin_kind': 'thread', 'origin_ref': tid})
        args = {'thread_id': tid, 'intent': 'say hello'} if tool == 'draft_thread_message' else {'to': 'Ace', 'words': 'Hello'}
        result = planned.propose_stage(mid, 's1', [{'id': 'd1', 'tool': tool, 'args': args, 'summary': 'Draft to Ace'}])
        check(result['status'] == 'success', f'the draft stage is proposed: {result}')
        stage = storage.get_mission(mid)['plan']['stages'][0]
        with patch.object(threads, '_pool_call', return_value={'subject': 'Hi', 'body': 'Hello'}):
            planned.run_stage(mid, 's1', stage['snapshot'], storage.get_member('mom'))
        stage = storage.get_mission(mid)['plan']['stages'][0]
        check(stage['rows'][0]['state'] == 'done', f'the real draft tool runs: {stage}')
        if tool == 'draft_thread_message':
            check(stage['rows'][0]['result'].get('next_action_rev') == 0, 'the tool wrapper preserves the draft revision')
            check(stage['rows'][0]['done_at'] > 0, 'the planned draft keeps its completion timestamp')
        threads.complete_next_action(tid, 0, 'mom')
        threads.advance(tid, 'Email Ace', None, who='mom')
        with patch.object(missions, '_llm', return_value={'action': 'finish', 'summary': 'Draft ready',
                                                         'next_action': 'Review the draft'}), patch.object(missions, '_dm_person'):
            missions.step(storage.get_mission(mid))
        check(storage.get_mission(mid)['status'] == 'done', 'the planned mission finishes')
        expected = 'Email Ace' if tool == 'draft_thread_message' else 'Review the draft'
        check(storage.get_thread(tid)['next_action'] == expected,
              f'only a real thread draft constrains the finisher ({tool})')


def scenario_later_planned_draft_uses_wall_clock_and_wins_at_finish():
    from services import missions, planned
    from test_planned_missions import _fresh as fresh_plan, _approved
    fresh_plan()
    tid = _t()
    mid = _approved([{'id': 's1', 'kind': 'build', 'title': 'Draft', 'why': '', 'makes': ['a draft']}])
    storage.update_mission(mid, {'origin_kind': 'thread', 'origin_ref': tid})
    with patch.object(threads, '_pool_call', return_value={'subject': 'Old', 'body': 'Older draft'}):
        direct = threads.draft_message(tid, 'say hello')
    storage.add_mission_step(mid, {'kind': 'draft', 'args_json': {'thread_id': tid}, 'result_json': direct})
    direct_step = next(s for s in storage.get_mission_steps(mid) if s['kind'] == 'draft')
    check(direct['next_action_rev'] == 0, 'the direct draft captures the original action')
    threads.advance(tid, 'Email Ace', None, who='mom')
    proposed = planned.propose_stage(mid, 's1', [{'id': 'd1', 'tool': 'draft_thread_message',
        'args': {'thread_id': tid, 'intent': 'write the newer draft'}, 'summary': 'Draft to Ace'}])
    check(proposed['status'] == 'success', f'the planned draft is proposed: {proposed}')
    stage = storage.get_mission(mid)['plan']['stages'][0]
    later_wall_time = direct_step['ts'] + 10
    with patch.object(planned.time, 'time', return_value=later_wall_time), \
            patch.object(threads, '_pool_call', return_value={'subject': 'New', 'body': 'Newer draft'}):
        planned.run_stage(mid, 's1', stage['snapshot'], storage.get_member('mom'))
    draft = storage.get_mission(mid)['plan']['stages'][0]['rows'][0]
    check(draft['state'] == 'done' and draft['result']['next_action_rev'] == 1,
          f'the real planned draft captures the successor: {draft}')
    with patch.object(missions, '_llm', return_value={'action': 'finish', 'summary': 'Ready',
                                                     'next_action': 'Review the newer planned draft'}), \
            patch.object(missions, '_dm_person'):
        missions.step(storage.get_mission(mid))
    check(storage.get_mission(mid)['status'] == 'done', 'the real mission finishes')
    check(storage.get_thread(tid)['next_action'] == 'Review the newer planned draft',
          'the finisher uses the newer planned draft revision instead of the older direct draft')
    check(draft['done_at'] == later_wall_time and draft['done_at'] > direct_step['ts'],
          'real planned and direct draft timestamps share the wall clock')


def scenario_completion_and_restore_rollback_the_history_on_failure():
    _fresh()
    tid = _t()
    before = storage.get_thread(tid)
    with patch.object(storage, 'update_thread', side_effect=RuntimeError('write failed')):
        try:
            threads.complete_next_action(tid, 0, 'mom')
        except RuntimeError:
            pass
        else:
            raise AssertionError('completion must surface the failed write')
    check(storage.get_thread(tid) == before, 'completion history and action roll back together')
    done = threads.complete_next_action(tid, 0, 'mom')
    before = storage.get_thread(tid)
    with patch.object(storage, 'update_thread', side_effect=RuntimeError('write failed')):
        try:
            threads.restore_next_action(tid, done['entry_id'], 'mom')
        except RuntimeError:
            pass
        else:
            raise AssertionError('restore must surface the failed write')
    check(storage.get_thread(tid) == before, 'restore history and action roll back together')


def scenario_finisher_without_a_draft_keeps_legacy_behavior():
    from services import missions
    _fresh()
    tid = _t()
    threads.advance(tid, 'Email Ace', None, who='mom')
    with patch.object(missions, '_dm_person'):
        missions._land_finish({'id': 'm1', 'origin_kind': 'thread', 'origin_ref': tid, 'goal': 'g'},
                              {'summary': 'Called Ace', 'next_action': 'Wait for the quote'}, next_action_rev=None)
    check(storage.get_thread(tid)['next_action'] == 'Wait for the quote', 'None keeps the existing advance')


def scenario_restore_refuses_after_an_empty_advance():
    _fresh()
    tid = _t()
    done = threads.complete_next_action(tid, 0, 'mom')
    threads.advance(tid, '', None, who='mom')
    before = storage.get_thread(tid)
    result = threads.restore_next_action(tid, done['entry_id'], 'mom')
    check(result.get('code') == 409 and storage.get_thread(tid) == before,
          f'an empty successor still invalidates restore: {result}')


def scenario_finisher_uses_the_chronologically_latest_draft():
    from services import missions
    for direct_latest in (False, True):
        _fresh()
        tid = _t()
        threads.advance(tid, 'Email Ace', None, who='mom')
        # Storage returns direct steps separately from planned rows. Either source
        # may be newest; concatenation order cannot decide the captured revision.
        direct_rev, planned_rev = (1, 0) if direct_latest else (0, 1)
        mid = storage.add_mission({'goal': 'Contact Ace', 'created_by': 'mom', 'status': 'running',
                                  'origin_kind': 'thread', 'origin_ref': tid,
                                  'plan': {'state': 'done', 'rev': 1, 'stages': [{'id': 's1', 'kind': 'build', 'title': 'Draft', 'state': 'done', 'rows': [{
                                      'id': 'd1', 'tool': 'draft_thread_message', 'state': 'done',
                                      'result': {'status': 'success', 'thread_id': tid,
                                                 'next_action_rev': planned_rev},
                                      'done_at': 10 if direct_latest else 20}]}]}})
        storage.add_mission_step(mid, {'kind': 'draft', 'ts': 20 if direct_latest else 10,
                                      'args_json': {'thread_id': tid},
                                      'result_json': {'status': 'ok', 'next_action_rev': direct_rev}})
        with patch.object(missions, '_llm', return_value={'action': 'finish', 'summary': 'Ready',
                                                         'next_action': 'Review the newest draft'}), \
                patch.object(missions, '_dm_person'):
            missions.step(storage.get_mission(mid))
        check(storage.get_thread(tid)['next_action'] == 'Review the newest draft',
              f'finish uses the newest draft revision (direct_latest={direct_latest})')


def scenario_advance_with_a_stale_expect_rev_writes_nothing():
    # Final review (Codex 2): the post-tick successor prompt sends the
    # completion's revision; a successor set meanwhile stands.
    _fresh()
    tid = _t()
    done = threads.complete_next_action(tid, 0, 'mom')
    threads.advance(tid, 'Email Ace', None, who='dad')        # someone else, while the prompt was open
    before = storage.get_thread(tid)
    r = threads.advance(tid, 'Call Ace again', None, who='mom', expect_rev=done['rev'])
    check(isinstance(r, dict) and r.get('status') == 'error' and r.get('code') == 409, f"a stale expect_rev answers 409: {r}")
    check(storage.get_thread(tid) == before, "and writes nothing: the newer next step and the history stand")
    r = threads.advance(tid, 'Call Ace again', None, who='mom', expect_rev=before['next_action_rev'])
    row = storage.get_thread(tid)
    check(r is True and row['next_action'] == 'Call Ace again' and row['next_action_rev'] == before['next_action_rev'] + 1,
          f"a current expect_rev writes as before: {r} {row['next_action']}")
    check(threads.advance(tid, 'No check', None, who='mom') is True, "without expect_rev advance is unchanged (a bool)")


def _launch_on(tid, goal='Research grout colours'):
    from services import missions
    with patch.object(missions, '_bump_call', lambda *a, **k: True):
        res = missions.launch(goal, origin_kind='thread', origin_ref=tid, created_by='mom')
    check(res.get('status') == 'launched', f"precondition: the mission launched: {res}")
    return res['mission_id']


def _finish(mid, next_action='Pick a grout'):
    from services import missions
    with patch.object(missions, '_llm', return_value={'action': 'finish', 'summary': 'Found three colours',
                                                     'next_action': next_action}),             patch.object(missions, '_dm_person') as dm:
        missions.step(storage.get_mission(mid))
    check(storage.get_mission(mid)['status'] == 'done', 'the real mission finish executes')
    return dm


def scenario_research_finish_keeps_a_successor_set_while_it_ran():
    # Final review (Codex 3): a non-drafting thread-origin mission compares
    # against the revision captured at launch.
    for successor in (False, True):
        _fresh()
        tid = _t()
        mid = _launch_on(tid)
        check(storage.get_mission(mid).get('origin_rev') == 0, "launch captures the thread's revision")
        if successor:
            threads.complete_next_action(tid, 0, 'mom')
            threads.advance(tid, 'Email Ace', None, who='mom')
        dm = _finish(mid)
        row = storage.get_thread(tid)
        check(row['next_action'] == ('Email Ace' if successor else 'Pick a grout'),
              f"the finish never overwrites a person's successor (successor={successor}): {row['next_action']}")
        entry = row['history'][-1]
        check(entry['kind'] == 'mission' and ('earlier next step' in entry['text']) == successor
              and entry['next_action'] == (None if successor else 'Pick a grout'),
              f"only the late finish is noted against an earlier next step: {entry}")
        check(('Next: Pick a grout' in dm.call_args.args[1]) != successor, 'the late DM proposes no superseded step')


def scenario_legacy_thread_mission_without_origin_rev_keeps_todays_finish():
    _fresh()
    tid = _t()
    mid = storage.add_mission({'goal': 'Research grout colours', 'created_by': 'mom', 'status': 'running',
                               'origin_kind': 'thread', 'origin_ref': tid})
    check('origin_rev' not in storage.get_mission(mid), "precondition: a row from before origin_rev")
    threads.advance(tid, 'Email Ace', None, who='mom')
    _finish(mid)
    check(storage.get_thread(tid)['next_action'] == 'Pick a grout', "a legacy row (no revision) advances as it always did")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
