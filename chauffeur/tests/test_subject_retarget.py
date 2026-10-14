"""Changing or clearing what a thread or mission is about (spec 2026-10-14 §3
and §4, Codex review finding 4).

Pinned here (Task 6):

  * `subjects.retarget(sit_kind, sid, new_kind, new_id, actor)` is the one
    operation: parent/adult only; REFUSED while the situation's live mission
    has a tap-only ask pending (release, submit, verify) or is browsing, so an
    approval drawn about trip A can never run about trip B; otherwise it
    writes the fields, bumps subject_rev, leaves a `subject_changed` note on
    the live mission and dismisses its pending proposals; clearing is the
    same operation with None;
  * a mission waiting to retry may be retargeted, and its next step reads
    the new record;
  * the `subject` verb on the thread card (and a manual mission's card, never
    a thread mission's: the thread is the authority): "Link to something in
    Chauffeur" unbound, "Change what this is about" bound (never the title: options carry no viewer), plus "Unlink";
    through `situations.act` a query binds a clear winner, a tie answers
    status 'choose' with the candidates, {kind, id} binds that one, {clear}
    unlinks; `act_on_situation` verb `subject` with text is the same path;
  * the card's verb list and Argyle's verb enum both know `subject`.

Run from chauffeur/:  python tests/test_subject_retarget.py
"""
import re

from harness import check  # noqa: F401
from services import storage, missions, situations, subjects, triage
from services import agent_tools_v2 as tools
from test_mission_subject import _fresh, _plan, _mission, _step, _steps, _thread, PROMPTS
from test_subjects import MOM, AUNT, KID


def _report(outcome, **kw):
    base = {'outcome': outcome, 'text': kw.pop('text', outcome), 'learned': {}, 'stopped_at': 'https://disneyworld.disney.go.com/dining',
            'wanted_fields': [], 'turns': 3, 'tokens_in': 100, 'tokens_out': 10, 'seconds': 5.0, 'screenshots': [], 'filled': {}}
    return {**base, **kw}


def _disney_thread_with_mission():
    tid = _thread('Disney dining plans', subject_kind='trip', subject_id='ev_disney', subject_rev=1)
    mid = _mission(created_by='mom', origin=tid)
    return tid, mid


def scenario_retarget_is_refused_while_an_ask_is_pending_or_a_browse_is_live():
    _fresh()
    tid, mid = _disney_thread_with_mission()
    storage.get_settings = (lambda s: (lambda: dict(s, contact_first_name='Jeff', contact_email='j@example.com')))(storage.get_settings())
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['first_name', 'email'])
    _plan({'action': 'browse', 'goal': 'find a table', 'site': 'disneyworld.disney.go.com'})
    _step(mid)
    check(missions.tap_only_ask_pending(mid), "a release is waiting on a tap")
    res = subjects.retarget('thread', tid, 'trip', 'ev_hawaii', MOM)
    check(res['status'] == 'refused' and 'pending' in res['message'].lower(), f"refused while the ask is pending: {res}")
    check(storage.get_thread(tid)['subject_id'] == 'ev_disney', "nothing changed")
    tid2, mid2 = _disney_thread_with_mission()
    storage.update_mission(mid2, {'status': 'browsing'})
    res = subjects.retarget('thread', tid2, 'trip', 'ev_hawaii', MOM)
    check(res['status'] == 'refused', f"refused while a browse is live: {res}")
    res = subjects.retarget('thread', tid2, 'trip', 'ev_hawaii', KID)
    check(res['status'] == 'refused', "a child never")


def scenario_retarget_bumps_rev_notes_and_dismisses_pending_proposals():
    _fresh()
    tid, mid = _disney_thread_with_mission()
    pid = storage.add_action_proposal({'action_type': 'add_trip_poi', 'summary': 'Add Chef Mickey to Disney', 'payload': {}})
    storage.add_mission_step(mid, {'kind': 'proposal', 'name': 'add_trip_poi', 'args_json': {}, 'result_json': {'proposal_id': pid}})
    res = subjects.retarget('thread', tid, 'trip', 'ev_hawaii', MOM)
    check(res['status'] == 'success' and res.get('rev') == 2, f"retargeted: {res}")
    t = storage.get_thread(tid)
    check(t['subject_kind'] == 'trip' and t['subject_id'] == 'ev_hawaii' and t['subject_rev'] == 2, f"fields and rev: {t}")
    note = _steps(mid, 'subject_changed')
    check(note and note[-1]['kind'] == 'note' and note[-1]['result_json'].get('from') == 'Disney World'
          and note[-1]['result_json'].get('to') == 'Hawaii', f"the live mission is told, old and new: {note}")
    check(storage.get_action_proposal(pid)['status'] == 'dismissed', "a proposal built about Disney is not offered about Hawaii")
    res = subjects.retarget('thread', tid, None, None, MOM)
    t = storage.get_thread(tid)
    check(res['status'] == 'success' and t.get('subject_kind') is None and t.get('subject_id') is None and t['subject_rev'] == 3,
          f"unlinked: {res} {t}")
    check('unlinked' in repr(_steps(mid, 'subject_changed')[-1]['result_json']).lower(), "the note says unlinked")
    res = subjects.retarget('thread', tid, 'occasion', 'o1', AUNT)
    check(res['status'] in ('error', 'refused') and storage.get_thread(tid).get('subject_kind') is None,
          f"a record the person may not see is not theirs to link: {res}")


def scenario_a_mission_waiting_to_retry_may_be_retargeted_and_reads_the_new_record():
    _fresh()
    tid, mid = _disney_thread_with_mission()
    storage.update_mission(mid, {'status': 'waiting_retry'})
    res = subjects.retarget('thread', tid, 'trip', 'ev_hawaii', MOM)
    check(res['status'] == 'success', f"no ask, no browse: allowed: {res}")
    storage.update_mission(mid, {'status': 'running'})
    _plan({'action': 'ask_user', 'question': 'ok?'})
    _step(mid)
    check('ABOUT: trip "Hawaii"' in PROMPTS[-1]['system'] and 'Disney World' not in PROMPTS[-1]['system'].split('TRANSCRIPT')[0],
          "the next step reads Hawaii")


def scenario_the_subject_verb_on_the_cards():
    _fresh()
    tid = _thread('Plain thread')
    opts = situations.options_for('thread', situations.load('thread', tid))
    link = [o for o in opts if o['verb'] == 'subject']
    check([o['id'] for o in link] == ['subject'] and link[0]['label'] == 'Link to something in Chauffeur', f"unbound: {link}")
    res = situations.act('thread', tid, 'subject', option_id='subject', payload={'query': 'Disney World'}, actor=MOM)
    check(res['status'] == 'success' and storage.get_thread(tid)['subject_id'] == 'ev_disney', f"a clear winner binds: {res}")
    opts = situations.options_for('thread', situations.load('thread', tid))
    link = {o['id']: o for o in opts if o['verb'] == 'subject'}
    check(set(link) == {'subject', 'subject:clear'} and link['subject']['label'] == 'Change what this is about'
          and link['subject:clear']['label'] == 'Unlink', f"bound: {link}")
    check(all('Disney' not in o['label'] for o in opts),
          "an option is built with no viewer, so it never names the record (the chip, filtered per viewer, does)")
    res = situations.act('thread', tid, 'subject', option_id='subject', payload={'query': 'Disney'}, actor=MOM)
    check(res['status'] == 'choose' and {'ev_disney', 'th1'} <= {c['id'] for c in res.get('candidates') or []},
          f"a tie asks which: {res}")
    res = situations.act('thread', tid, 'subject', option_id='subject', payload={'kind': 'trip', 'id': 'ev_hawaii'}, actor=MOM)
    check(res['status'] == 'success' and storage.get_thread(tid)['subject_id'] == 'ev_hawaii', f"the picked one binds: {res}")
    res = situations.act('thread', tid, 'subject', option_id='subject:clear', payload={}, actor=MOM)
    check(res['status'] == 'success' and storage.get_thread(tid).get('subject_kind') is None, f"Unlink: {res}")
    res = situations.act('thread', tid, 'subject', option_id='subject', payload={'query': 'Disney World'}, actor=KID)
    check(res['status'] == 'refused', "a child never")
    manual = _mission(created_by='mom')
    check(any(o['id'] == 'subject' for o in situations.options_for('mission', situations.load('mission', manual))),
          "a manual mission's card offers it")
    _tid, tmid = _disney_thread_with_mission()
    check(not any(o['verb'] == 'subject' for o in situations.options_for('mission', situations.load('mission', tmid))),
          "a thread mission's card does not: its thread is the one place to change it")


def scenario_argyle_and_the_card_know_the_verb():
    _fresh()
    tid = _thread('Trip planning')
    triage.set_focus('conv:1', 'thread', tid, 'Trip planning')
    res = tools.act_on_situation(verb='subject', text='Disney World', acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and storage.get_thread(tid)['subject_id'] == 'ev_disney', f"Argyle links the focus thread: {res}")
    res = tools.act_on_situation(verb='subject', text='Hawaii', acting_member=MOM, focus_key='conv:1')
    check(res['status'] == 'success' and storage.get_thread(tid)['subject_id'] == 'ev_hawaii',
          f"on a linked thread, words change it (never 'say which option'): {res}")
    check('subject' in situations.VERBS, "a situation verb")
    src = open('static/situations.js', encoding='utf-8').read()
    block = re.search(r"VERB_LABELS\s*=\s*\{([^}]*)\}", src).group(1)
    check("'subject'" in block, "the card has a label for it")
    enum = next(t for t in tools.get_available_tools() if t['name'] == 'act_on_situation')['parameters']['properties']['verb']['enum']
    check('subject' in enum, "Argyle's verb list has it")


SCENARIOS = [
    scenario_retarget_is_refused_while_an_ask_is_pending_or_a_browse_is_live,
    scenario_retarget_bumps_rev_notes_and_dismisses_pending_proposals,
    scenario_a_mission_waiting_to_retry_may_be_retargeted_and_reads_the_new_record,
    scenario_the_subject_verb_on_the_cards,
    scenario_argyle_and_the_card_know_the_verb,
]

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
