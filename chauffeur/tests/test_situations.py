"""The situation view-model: one shape over four tables, deterministic options
with a closed verb set, ranking, viewer gates, fallback notes; then act —
server-bound options, own vs done, the write gate."""
import datetime
import time

from harness import check  # noqa: F401
from models.schemas import HouseholdTask
from services import storage, situations, threads, findings

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _reset():
    for t in (storage.findings_table, storage.mind_insights_table, storage.threads_table,
              storage.missions_table, storage.mission_steps_table, storage.asks_table,
              storage.members_table, storage.cache_table, storage.app_state_table,
              storage.agent_action_proposals_table, storage.assist_contacts_table,
              storage.coverage_asks_table, storage.drivers_table, storage.overrides_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"], "llm_gemini_api_key": ""}
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "dad", "name": "Dad", "role": "adult"})
    storage.add_member({"id": "kid", "name": "Kate", "role": "child", "is_child": True})
    storage.add_driver({"id": "mom", "name": "Mom", "color_code": "#fff"})


def _unassigned_event():
    soon = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({
        "events": [{"id": "ev1", "title": "Soccer", "start": soon.isoformat(),
                    "end": (soon + datetime.timedelta(hours=1)).isoformat()}],
        "assignments": {}, "unassigned": ["ev1"]})
    return soon


def scenario_finding_view_has_facts_options_and_fallback_note():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned',
                               'severity': 'decide', 'line': '🚨 No driver yet: Soccer',
                               'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': soon.timestamp(), 'state': 'open',
                               'fingerprint': f"ev1|{soon.timestamp()}"})
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['kind'] == 'finding' and s['title'].startswith('🚨'), f"shape: {s}")
    check(s['state'] == 'open' and s['due'] == soon.timestamp(), "facts carried")
    check(s['note_source'] == 'fallback' and s['status_note'], "a fallback note is never empty")
    verbs = [o['verb'] for o in s['options']]
    check(verbs and set(verbs) <= situations.VERBS, f"only closed-set verbs: {verbs}")
    check(s['next_step']['id'] == s['options'][0]['id'], "next step is the first option")
    check(any(o['verb'] == 'ask' for o in s['options']), "an uncovered ride offers an ask")
    check(any(o['verb'] == 'own' for o in s['options']) and any(o['verb'] == 'dismiss' for o in s['options']),
          "own and dismiss are always there")
    check(all(o['id'] for o in s['options']) and len({o['id'] for o in s['options']}) == len(s['options']),
          "option ids are present and unique")


def scenario_finding_with_a_free_driver_offers_assign_first():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned',
                               'severity': 'approve', 'line': 'No driver yet', 'subject_type': 'event',
                               'subject_id': 'ev1', 'due_at': soon.timestamp(), 'state': 'open',
                               'fingerprint': f"ev1|{soon.timestamp()}"})
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['next_step']['verb'] == 'assign' and 'Mom' in s['next_step']['label'],
          f"a free family driver is the first move: {s['next_step']}")
    check(s['next_step']['payload'].get('driver_name') == 'Mom'
          and s['next_step']['payload'].get('event_name') == 'Soccer', "assign payload is server-built")


def scenario_insight_options_follow_the_plan_stages():
    _reset()
    iid = storage.add_mind_insight({'slug': 's', 'line': 'Tue and Thu collide', 'category': 'overload',
                                    'approach': 'ask Sarah to take Thursday', 'identity': 'overload:x',
                                    'refs': ['kate']})
    s = situations.view('insight', iid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['next_step']['verb'] == 'plan' and 'ask Sarah' in s['next_step']['label'],
          f"before a plan the next step is to plan, labelled with the approach: {s['next_step']}")
    storage.update_mind_insight(iid, {'state': 'in_hand', 'plan_json': {'steps': [
        {'id': 'st1', 'kind': 'tool', 'text': 'Ask Sarah', 'status': 'open', 'proposal_json': None},
        {'id': 'st2', 'kind': 'human', 'text': 'Call the coach', 'status': 'open',
         'owner_member_id': 'mom', 'owner_name': 'Mom', 'due': '2026-10-12'},
        {'id': 'st3', 'kind': 'tool', 'text': 'Move dentist', 'status': 'open',
         'proposal_json': {'proposal_id': 'p1', 'summary': 'Move dentist'}}]}})
    s = situations.view('insight', iid, viewer={'id': 'mom', 'role': 'parent'})
    by_verb = {o['verb']: o for o in s['options']}
    check(s['next_step']['verb'] == 'prepare' and s['next_step']['payload']['step_id'] == 'st1',
          "first open tool step, unbound, is prepare")
    check('done' in by_verb and by_verb['done']['payload']['step_id'] == 'st2', "human step is done")
    check(any(o['verb'] == 'do' and o['payload']['step_id'] == 'st3' for o in s['options']), "bound step is do")
    check(sum(1 for o in s['options'] if o['verb'] == 'skip') == 3, "every open step can be skipped")
    check(s['group'] == 'in_hand', "a planned insight is in hand")


def scenario_thread_and_mission_views():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call county',
                         next_action_at=(NOON - datetime.timedelta(days=3)).date().isoformat(),
                         counterparty_name='County', created_by='mom')
    s = situations.view('thread', tid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['title'] == 'Deck permit' and 'County' in s['people'], f"thread facts: {s}")
    check(s['group'] == 'now', "an overdue next action needs you now")
    check('call county' in s['status_note'], "fallback note names the next action")
    check([o['verb'] for o in s['options'][:1]] == ['advance'], "overdue thread: advance is first")
    check({'draft', 'close', 'own'} <= {o['verb'] for o in s['options']}, "deterministic thread verbs present")

    mid = storage.add_mission({'goal': 'Find a plumber', 'status': 'waiting_user', 'created_by': 'mom',
                               'tier': 'flash', 'origin_kind': 'manual', 'step_count': 2})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'ask_user', 'result_json': {'question': 'Budget?'}})
    s = situations.view('mission', mid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['next_step']['verb'] == 'answer' and 'Budget?' in s['next_step']['label'], f"waiting mission asks: {s['next_step']}")
    check(s['needs_attention'] and s['group'] == 'now', "waiting_user needs attention")
    storage.update_mission(mid, {'status': 'done'})
    storage.add_mission_step(mid, {'kind': 'proposal', 'name': 'add_errand',
                                   'result_json': {'proposal_id': 'p9', 'status': 'proposed'}})
    storage.add_action_proposal({'id': 'p9', 'action_type': 'add_errand', 'summary': 'Add errand',
                                 'payload': {}, 'status': 'proposed', 'requires_admin': True})
    s = situations.view('mission', mid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['needs_attention'] and s['next_step']['verb'] == 'do', "a done mission with a pending proposal still needs you")


def scenario_rank_and_viewer_gates():
    _reset()
    soon = _unassigned_event()
    f_decide = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                                    'line': 'ride', 'subject_type': 'event', 'subject_id': 'ev1',
                                    'due_at': soon.timestamp(), 'state': 'open'})
    f_fyi = storage.add_finding({'identity': 'optional_skip:ev1', 'kind': 'optional_skip', 'severity': 'fyi',
                                 'line': 'skipped', 'subject_type': 'event', 'subject_id': 'ev1', 'state': 'open'})
    i_norm = storage.add_mind_insight({'slug': 'a', 'line': 'normal', 'category': 'c', 'confidence': 0.9,
                                       'approach': 'x', 'identity': 'c:1'})
    i_sens = storage.add_mind_insight({'slug': 'b', 'line': 'secret', 'category': 'c', 'confidence': 0.5,
                                       'approach': 'x', 'identity': 'c:2', 'sensitivity': 'sensitive'})
    rows = situations.list_situations({'id': 'mom', 'role': 'parent'}, kinds=('finding', 'insight'))
    check([r['id'] for r in rows] == [f_decide, i_norm, i_sens, f_fyi],
          f"decide, then insights by confidence, then fyi: {[r['id'] for r in rows]}")
    rows = situations.list_situations({'id': 'kid', 'role': 'child'}, kinds=('finding', 'insight'))
    check([r['id'] for r in rows] == [i_norm], f"a child sees non-sensitive insights only: {[r['id'] for r in rows]}")
    rows = situations.list_situations(None, kinds=('finding', 'insight'))
    check([r['id'] for r in rows] == [i_norm], "no viewer (a wall) is the same as a child")
    rows = situations.list_situations({'id': 'dad', 'role': 'adult'}, kinds=('finding', 'insight'))
    check(f_decide in [r['id'] for r in rows] and i_sens not in [r['id'] for r in rows],
          "an adult sees findings but not sensitive insights")


SCENARIOS = [scenario_finding_view_has_facts_options_and_fallback_note,
             scenario_finding_with_a_free_driver_offers_assign_first,
             scenario_insight_options_follow_the_plan_stages,
             scenario_thread_and_mission_views,
             scenario_rank_and_viewer_gates]

def scenario_act_resolves_the_option_server_side():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'approve',
                               'line': 'No driver yet', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': soon.timestamp(), 'state': 'open'})
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    assign = next(o for o in s['options'] if o['verb'] == 'assign')
    res = situations.act('finding', fid, 'assign', option_id=assign['id'],
                         payload={'driver_name': 'Dad'},      # ignored: payload is server-built
                         actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success' and res.get('schedule_dirty'), f"assign ran: {res}")
    ov = [o for o in storage.get_all_overrides() if str(o.get('event_id')) == 'ev1']
    check(ov and ov[0].get('driver_id') == 'mom', f"the SERVER's driver was assigned, not the client's: {ov}")


def scenario_stale_option_id_is_refused():
    _reset()
    iid = storage.add_mind_insight({'slug': 's', 'line': 'x', 'category': 'c', 'approach': 'y',
                                    'identity': 'c:1', 'state': 'in_hand', 'plan_json': {'steps': [
                                        {'id': 'st1', 'kind': 'human', 'text': 'Call', 'status': 'open'}]}})
    res = situations.act('insight', iid, 'done', option_id='done:st1', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success', f"a current option runs: {res}")
    res = situations.act('insight', iid, 'done', option_id='done:st1', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'refused',
          f"the same id a second time is stale and refused (the plan closed, so the row is settled): {res}")
    res = situations.act('insight', iid, 'launch_rocket', option_id='x', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'refused', "a verb outside the set is refused")


def scenario_own_is_not_done():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'ride', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': soon.timestamp(), 'state': 'open'})
    res = situations.act('finding', fid, 'own', option_id='own', actor={'id': 'dad', 'role': 'adult'})
    row = storage.get_finding(fid)
    check(res['status'] == 'success' and row['state'] == 'in_hand' and row[situations.OWNER] == 'dad',
          f"own moves to in hand with an owner: {row}")
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['group'] == 'in_hand' and s['next_step']['verb'] == 'done', "in hand: next step is Handled")
    res = situations.act('finding', fid, 'done', option_id='done', actor={'id': 'dad', 'role': 'adult'})
    check(storage.get_finding(fid)['state'] == 'done' and storage.get_finding(fid)['resolved_by'] == 'tap',
          "done closes it the way a tap always has")


def scenario_write_gate():
    _reset()
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    res = situations.act('thread', tid, 'close', option_id='close:done', actor={'id': 'kid', 'role': 'child'})
    check(res['status'] == 'refused', "a child cannot act")
    res = situations.act('thread', tid, 'close', option_id='close:done', actor=None)
    check(res['status'] == 'refused', "no actor cannot act (the tool layer passes the admin surface's nominee)")
    res = situations.act('thread', tid, 'close', option_id='close:done', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success' and storage.get_thread(tid)['state'] == 'done', "a parent can")
    check((storage.get_thread(tid).get('rev') or 0) >= 1, "an act bumps rev")


SCENARIOS += [scenario_act_resolves_the_option_server_side, scenario_stale_option_id_is_refused,
              scenario_own_is_not_done, scenario_write_gate]


def scenario_snoozed_finding_leaves_the_lane():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'ride', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': soon.timestamp(), 'state': 'open'})
    res = situations.act('finding', fid, 'snooze', option_id='snooze:7', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success', f"snooze runs: {res}")
    rows = situations.list_situations({'id': 'mom', 'role': 'parent'}, kinds=('finding',))
    check(rows == [], "a parked finding is out of the lane")
    storage.update_finding(fid, {'snoozed_until': time.time() - 1})
    rows = situations.list_situations({'id': 'mom', 'role': 'parent'}, kinds=('finding',))
    check([r['id'] for r in rows] == [fid], "and back when the date passes")


def scenario_a_dismissed_finding_cannot_be_taken_back_by_own():
    _reset()
    soon = _unassigned_event()
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'ride', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': soon.timestamp(), 'state': 'dismissed', 'resolved_by': 'dismiss'})
    s = situations.view('finding', fid, viewer={'id': 'mom', 'role': 'parent'})
    check(s['options'] == [] and s['next_step'] is None, f"a closed situation offers nothing: {s['options']}")
    res = situations.act('finding', fid, 'own', option_id='own', actor={'id': 'dad', 'role': 'adult'})
    check(res['status'] == 'refused' and storage.get_finding(fid)['state'] == 'dismissed',
          "dismissed is dismissed, even against an old card")


def scenario_an_adult_cannot_act_on_a_parents_only_insight():
    _reset()
    iid = storage.add_mind_insight({'slug': 's', 'line': 'secret', 'category': 'c', 'approach': 'x',
                                    'identity': 'c:1', 'sensitivity': 'sensitive'})
    res = situations.act('insight', iid, 'dismiss', option_id='dismiss', actor={'id': 'dad', 'role': 'adult'})
    check(res['status'] == 'refused' and storage.get_mind_insight(iid)['state'] == 'active',
          "an adult acting by id on a sensitive insight is refused")
    res = situations.act('insight', iid, 'dismiss', option_id='dismiss', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success', "a parent can")


def scenario_mission_since_is_its_last_step_not_the_note():
    _reset()
    mid = storage.add_mission({'goal': 'g', 'status': 'running', 'created_by': 'mom', 'tier': 'flash',
                               'origin_kind': 'manual', 'step_count': 1})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'x', 'result_json': {}})
    step_ts = storage.get_mission_steps(mid)[-1]['ts']
    time.sleep(0.01)
    storage.update_mission(mid, {'status_note': 'n', 'note_ts': time.time(), 'note_source': 'argyle', 'note_rev': 0})
    s = situations.view('mission', mid, viewer={'id': 'mom', 'role': 'parent'})
    check(abs(s['since'] - step_ts) < 0.001, f"since is the last step, not the note write: {s['since']} vs {step_ts}")


SCENARIOS += [scenario_snoozed_finding_leaves_the_lane, scenario_a_dismissed_finding_cannot_be_taken_back_by_own,
              scenario_an_adult_cannot_act_on_a_parents_only_insight, scenario_mission_since_is_its_last_step_not_the_note]

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
