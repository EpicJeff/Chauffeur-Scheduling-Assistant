"""Spec §5 acceptance, end to end: text a helper → sent → yes → applied once
→ the finding retires by absence; a helper answers her own Chauffeur ask;
a done mission with a pending proposal stays actionable; the ordinary path
never goes stale; interrupted applying recovers to one assignment."""
import datetime
import time
from unittest import mock

from harness import check  # noqa: F401
from services import storage, situations, asks, watchers, findings

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.assist_contacts_table,
              storage.assist_assignments_table, storage.assist_history_table, storage.chat_channels_table,
              storage.chat_messages_table, storage.missions_table, storage.mission_steps_table,
              storage.agent_action_proposals_table, storage.drivers_table, storage.chores_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary']}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'nan', 'name': 'Nan', 'role': 'helper'})
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'phone': '555', 'kinds': ['driving'], 'active': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': (start + datetime.timedelta(hours=1)).isoformat()}],
                                 'assignments': {}, 'unassigned': ['ev1']})
    return start


def _sweep(now):
    with mock.patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         mock.patch('services.agent_tools_v2._post_chat_message',
                    side_effect=lambda ch, sender, body, card=None: {'id': 'm'}):
        watchers.run_watchers(now=now)


def _assigned(event_id='ev1'):
    v = storage.get_assist_assignment_map().get(event_id)
    return {'contact_id': v} if isinstance(v, str) else (v or {})


def _new_ask_option(fid):
    return next(o for o in situations.view('finding', fid, MOM)['options'] if o['id'] == 'ask:new')


def _with_contact(unlocks, contact_id):
    return {**unlocks, 'payload': {**unlocks['payload'], 'contact_id': contact_id}}


def scenario_1_text_a_helper_to_retirement():
    start = _reset()
    _sweep(NOON)
    fid = storage.get_findings(state='open')[0]['id']
    opt = _new_ask_option(fid)
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, opt['payload']['what'], 'text', 'mom',
                    unlocks=_with_contact(opt['payload']['unlocks'], 'c1'))['ask']
    check(a['draft_body'] and a['state'] == 'drafted', "drafted")
    asks.mark_sent(a['id'], MOM)
    r = asks.answer(a['id'], 'yes', MOM, reported=True)
    r2 = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'applied' and r2.get('already'), "applied once through a duplicate tap")
    check(_assigned().get('contact_id') == 'c1', "one assignment")
    # The applied yes flags schedule_dirty; in production the background
    # re-solve writes the assist assignment into the schedule cache, which is
    # what the sweep reads. Stand in for that re-solve here.
    sched = storage.get_cached_schedule() or {}
    sched['assist_assignments'] = {'ev1': 'c1'}
    storage.set_cached_schedule(sched)
    _sweep(NOON + datetime.timedelta(hours=1))
    row = storage.get_finding(fid)
    check(row['state'] == 'done' and row['resolved_by'] == 'auto',
          f"the covered ride retires by absence on the next sweep: {row['state']}/{row.get('resolved_by')}")


def scenario_2_helper_answers_her_own_chauffeur_ask():
    start = _reset()
    _sweep(NOON)
    fid = storage.get_findings(state='open')[0]['id']
    opt = _new_ask_option(fid)
    a = asks.create('finding', fid, {'name': 'Nan', 'member_id': 'nan'}, opt['payload']['what'], 'chauffeur', 'mom',
                    unlocks=opt['payload']['unlocks'])['ask']
    check(a['state'] == 'sent' and a['message_id'], "posted as a DM")
    r = asks.answer(a['id'], 'yes', {'id': 'nan', 'role': 'helper'})
    check(r['status'] == 'success' and r['outcome'] == 'applied', f"her yes applies under Mom's authority: {r}")
    assigned = _assigned()
    check(assigned.get('contact_id') and (storage.get_assist_contact(assigned['contact_id']) or {}).get('name') == 'Nan',
          "a new contact was minted for the helper and holds the ride")


def scenario_3_done_mission_with_pending_proposal_stays_actionable():
    _reset()
    mid = storage.add_mission({'goal': 'Find a plumber', 'status': 'done', 'created_by': 'mom', 'tier': 'flash',
                               'origin_kind': 'manual', 'step_count': 3, 'summary': 'Found two'})
    storage.add_action_proposal({'id': 'p1', 'action_type': 'add_errand', 'summary': 'Add: call Ace Plumbing',
                                 'payload': {'title': 'Call Ace Plumbing'}, 'status': 'proposed', 'requires_admin': True})
    storage.add_mission_step(mid, {'kind': 'proposal', 'name': 'add_errand',
                                   'result_json': {'proposal_id': 'p1', 'status': 'proposed'}})
    rows = situations.list_situations(MOM, kinds=('mission',))
    check([r['id'] for r in rows] == [mid] and rows[0]['group'] == 'now', "a done mission with a decision left is live")
    with mock.patch('services.chat_actions._execute', return_value={'status': 'success', 'message': 'added'}):
        res = situations.act('mission', mid, 'do', option_id='do:p1', actor=MOM)
    check(res['status'] == 'success', f"approving from the card: {res}")
    rows = situations.list_situations(MOM, kinds=('mission',))
    check(rows == [], f"resolved: it leaves the lane: {[r['id'] for r in rows]}")
    check(situations.view('mission', mid, MOM)['group'] == 'done', "and reads as history")


def scenario_4_the_ordinary_path_never_goes_stale():
    start = _reset()
    _sweep(NOON)
    fid = storage.get_findings(state='open')[0]['id']
    u = _new_ask_option(fid)['payload']['unlocks']
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive', 'text', 'mom',
                    unlocks=_with_contact(u, 'c1'))['ask']
    asks.mark_sent(a['id'], MOM)
    storage.add_assist_contact({'id': 'c2', 'name': 'Mike', 'kinds': ['driving'], 'active': True})
    b = asks.create('finding', fid, {'name': 'Mike', 'contact_id': 'c2'}, 'drive', 'text', 'mom',
                    unlocks=_with_contact(u, 'c2'))['ask']
    asks.mark_sent(b['id'], MOM)
    situations._pool_call = lambda *a_, **k: {'status_note': 'Two asks out.', 'options': []}
    storage.get_settings = lambda: {'calendar_ids': ['primary'], 'llm_gemini_api_key': 'k'}
    check(situations.refresh('finding', fid)['status'] == 'noted', "a note refresh happened in between")
    r = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'applied', f"sent, a sibling, and a note refresh did not make Sarah's yes stale: {r}")


def scenario_5_interrupted_applying_recovers_to_one_assignment():
    start = _reset()
    _sweep(NOON)
    fid = storage.get_findings(state='open')[0]['id']
    u = _new_ask_option(fid)['payload']['unlocks']
    a = asks.create('finding', fid, {'name': 'Sarah', 'contact_id': 'c1'}, 'drive', 'text', 'mom',
                    unlocks=_with_contact(u, 'c1'))['ask']
    asks.mark_sent(a['id'], MOM)
    # Stop after the yes, before the claim.
    storage.update_ask(a['id'], {'state': 'yes', 'answered_at': time.time(), 'answered_by': 'mom'})
    r = asks.answer(a['id'], 'yes', MOM, reported=True)
    check(r['outcome'] == 'applied', "a retry picks up from the claim")
    # Stop after the claim, before completion.
    storage.update_ask(a['id'], {'outcome': 'claimed', 'claim_ts': time.time() - 300, 'applied_at': None})
    _sweep(datetime.datetime.now() + datetime.timedelta(minutes=10))
    row = storage.get_ask(a['id'])
    check(row['outcome'] == 'applied', f"the sweep finished the claim: {row['outcome']}")
    check(_assigned().get('contact_id') == 'c1', "exactly one assignment stands")


SCENARIOS = [scenario_1_text_a_helper_to_retirement, scenario_2_helper_answers_her_own_chauffeur_ask,
             scenario_3_done_mission_with_pending_proposal_stays_actionable,
             scenario_4_the_ordinary_path_never_goes_stale,
             scenario_5_interrupted_applying_recovers_to_one_assignment]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
