"""Sub-project 3: one rank across the four kinds, one spoken sentence, focus
held per conversation, voice as the parent of record. Spec:
docs/superpowers/specs/2026-10-10-triage-and-replies-design.md §1."""
import datetime
import time

from harness import check  # noqa: F401
from services import storage, situations, triage, threads

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.threads_table, storage.missions_table,
              storage.mission_steps_table, storage.assist_contacts_table, storage.chat_channels_table,
              storage.chat_messages_table, storage.conversations_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary'], 'thread_stall_days': 7}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def _finding(line, severity, due_in_hours, fid):
    due = (NOON + datetime.timedelta(hours=due_in_hours))
    return storage.add_finding({'identity': f'unassigned:{fid}', 'kind': 'unassigned', 'severity': severity,
                                'line': line, 'subject_type': 'event', 'subject_id': fid,
                                'due_at': due.timestamp(), 'state': 'open'})


def scenario_rank_tiers_across_four_kinds():
    _reset()
    _finding('No driver: soccer today', 'decide', 6, 'ev-soon')          # tier 0: due within 24h
    _finding('No driver: recital next week', 'decide', 24 * 6, 'ev-late')  # tier 1
    _finding('Approve the swap', 'approve', 24 * 2, 'ev-appr')             # tier 2
    _finding('FYI: bus late', 'fyi', 24 * 2, 'ev-fyi')                     # tier 4
    storage.add_mind_insight({'slug': 'i', 'line': 'Thursday is tight', 'category': 'c', 'approach': 'ask Sarah',
                              'identity': 'c:1', 'confidence': 0.8})      # tier 3
    overdue = threads.create('Pest control', owner_member_id='mom', next_action='call back',
                             next_action_at=(NOON - datetime.timedelta(days=1)).date().isoformat(), created_by='mom')  # tier 0
    quiet = threads.create('Gutters', owner_member_id='mom', created_by='mom')
    storage.update_thread(quiet, {'created_at': time.time() - 9 * 86400})                                              # tier 1 (quiet)
    mid = storage.add_mission({'goal': 'Find a sitter', 'status': 'waiting_user', 'created_by': 'mom'})                # tier 0
    rows = situations.list_situations(MOM)
    ranked = triage.triage_rank(rows)
    titles = [s['title'] for s in ranked]
    tiers = [triage.tier(s) for s in ranked]
    check(tiers == sorted(tiers), f"tiers are non-decreasing: {list(zip(titles, tiers))}")
    check(set(titles[:3]) == {'No driver: soccer today', 'Pest control', 'Find a sitter'},
          f"tier 0 is the due-today ride, the overdue thread and the waiting mission: {titles[:3]}")
    check(titles.index('No driver: recital next week') < titles.index('Approve the swap') < titles.index('Thursday is tight')
          < titles.index('FYI: bus late'), f"decide, then approve, then insight, then fyi: {titles}")
    check(titles.index('Gutters') < titles.index('Approve the swap'), "a quiet thread outranks an approve finding")


def scenario_spoken_sentence_per_kind():
    _reset()
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})
    fid = _finding('No driver yet: Soccer Thu 4:00', 'decide', 30, 'ev1')
    s = situations.view('finding', fid, MOM)
    line = triage.spoken(s)
    check(line.startswith('No driver yet: Soccer Thu 4:00.') and 'Next: ' in line, f"title then next step: {line}")
    storage.update_finding(fid, {'status_note': 'Mike was asked and said no.', 'note_source': 'argyle',
                                 'note_rev': storage.get_finding(fid).get('rev') or 0})
    s = situations.view('finding', fid, MOM)
    check('Mike was asked and said no.' in triage.spoken(s), "Argyle's note is spoken when it is hers")
    storage.update_finding(fid, {'note_source': 'fallback'})
    s = situations.view('finding', fid, MOM)
    check('Mike was asked' not in triage.spoken(s), "a fallback note is never spoken as hers")
    from services import asks
    asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive Kate Thursday', 'text', 'mom', draft_mode='template')
    s = situations.view('finding', fid, MOM)
    check('asked Sarah by text' in triage.spoken(s) and 'not sent yet' in triage.spoken(s), f"the ask clause: {triage.spoken(s)}")
    tid = threads.create('Pest control', owner_member_id='mom', created_by='mom')
    s = situations.view('thread', tid, MOM)
    check(triage.spoken(s).startswith('Pest control.'), f"a thread speaks its title: {triage.spoken(s)}")
    check(triage.spoken(s).endswith('.'), "a sentence ends with a full stop")


def scenario_spoken_list_never_holds_a_sensitive_insight():
    _reset()
    storage.add_mind_insight({'slug': 'n', 'line': 'normal', 'category': 'c', 'approach': 'x', 'identity': 'c:1'})
    storage.add_mind_insight({'slug': 's', 'line': 'SECRET', 'category': 'c', 'approach': 'x', 'identity': 'c:2',
                              'sensitivity': 'sensitive'})
    plain = [s['title'] for s in situations.list_situations(MOM)]
    check('SECRET' in plain, "a parent's ordinary list holds the sensitive row")
    spoken = [s['title'] for s in situations.list_situations(MOM, spoken=True)]
    check('SECRET' not in spoken and 'normal' in spoken, f"a spoken list never does: {spoken}")


SCENARIOS = [scenario_rank_tiers_across_four_kinds, scenario_spoken_sentence_per_kind,
             scenario_spoken_list_never_holds_a_sensitive_insight]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
