"""Planned missions: interview, plan approval, build stages and the runner
(spec §1, §4, §5, §6; Codex F2–F7, F9, H5–H7). Task 7.

Names this file fixes (the cards and the router build on them):
  * ask steps: 'interview', 'plan', 'stage', 'stage_check';
  * verbs: `approve_plan` with options `approve_plan:<rev>:approve|stop|drop:<stage_id>`,
    `run_stage` with options `run_stage:<stage_id>:<snapshot>:approve|skip|stop|exclude:<row_id>`;
  * `planned.answer_plan(mission_id, answers, actor)`, `planned.run_stage(mission_id, stage_id,
    snapshot, actor)`, `planned.reconcile()`, `planned.may_approve(mission, actor)`;
  * `chat_actions.run_row(proposal_id, approver, idem)` is the runner's only door; every other
    door refuses a proposal that carries a `stage_id`.

Run from chauffeur/:  python tests/test_planned_missions.py
"""
import threading
import time

from harness import check  # noqa: F401
from services import storage, missions, situations, subjects, chat_actions, occasions, meals
from services import agent_tools_v2 as tools
from test_mission_subject import _fresh as _fresh_subjects, _plan, _mission, _step, _steps, PROMPTS
from test_subjects import MOM, DAD, AUNT, KID


def _fresh(step_cap=60):
    _fresh_subjects()
    storage.agent_action_proposals_table.truncate()
    base = storage.get_settings()
    storage.get_settings = (lambda s: (lambda: dict(s, mission_step_cap=step_cap, mission_cap_pro_calls=200)))(base)


def _p():
    from services import planned
    return planned


def _plan_of(mid):
    return storage.get_mission(mid).get('plan') or {}


def _ask_names(mid):
    return [s['name'] for s in storage.get_mission_steps(mid) if s['kind'] == 'ask']


def _opts(mid, verb):
    return [o for o in situations.options_for('mission', situations.load('mission', mid)) if o['verb'] == verb]


QUESTIONS = [{'key': 'budget', 'ask': 'What is the budget?', 'kind': 'number'}]
STAGES = [{'id': 's1', 'kind': 'build', 'title': 'The party and its people', 'why': 'everything hangs off it',
           'makes': ['the occasion', 'the guest list']},
          {'id': 's2', 'kind': 'work', 'title': 'Find a cake bakery', 'why': 'nearby options', 'goal': 'find two bakeries',
           'step_budget': 4, 'makes': ['two bakeries with prices']}]


def _interviewed(mid=None, template='birthday'):
    mid = mid or _mission(created_by='mom')
    _plan({'action': 'interview', 'template': template, 'questions': QUESTIONS})
    _step(mid)
    return mid


def _planned_mission(stages=STAGES):
    mid = _interviewed(template=None)
    _p().answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'plan', 'stages': stages})
    _step(mid)
    return mid


def _approved(stages=STAGES):
    mid = _planned_mission(stages)
    rev = _plan_of(mid)['rev']
    res = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"approved: {res}")
    return mid


ROWS = [{'id': 'r1', 'tool': 'add_occasion', 'args': {'title': "Kate's 10th birthday", 'anchor_date': '2027-02-14', 'kind': 'birthday'},
         'summary': "Make Kate's 10th birthday"},
        {'id': 'r2', 'tool': 'add_occasion_guests',
         'args': {'occasion_id': {'$ref': 'r1', 'kind': 'occasion'}, 'who': 'The Wilsons', 'headcount': 4},
         'summary': 'Add the Wilsons', 'needs': ['r1']}]


def _staged(rows=ROWS):
    mid = _approved()
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': rows})
    _step(mid)
    st = _plan_of(mid)['stages'][0]
    return mid, st


# --- A. The interview -----------------------------------------------------------

def scenario_a1_the_interview_writes_questions_and_waits():
    _fresh()
    mid = _interviewed()
    plan = _plan_of(mid)
    keys = [q['key'] for q in plan['questions']]
    check(plan['state'] == 'interviewing' and storage.get_mission(mid)['status'] == 'waiting_user', f"waiting: {plan.get('state')}")
    check(keys[:5] == ['headcount', 'cooking_hands', 'cake', 'theme', 'gifts'] and keys[5] == 'budget',
          f"the birthday template's questions first, with their keys, then the planner's: {keys}")
    check(all(q.get('template_key') == q['key'] for q in plan['questions'][:5]) and plan['questions'][5].get('template_key') is None,
          "template questions carry their template_key")
    check(_ask_names(mid)[-1] == 'interview', f"an interview ask: {_ask_names(mid)}")
    card = missions.ask_card(storage.get_mission(mid))
    check(card and card['ask'] == 'interview' and len(card['questions']) == 5, f"the card shows one round of five: {card and card.get('questions')}")
    big = _mission(created_by='mom')
    _plan({'action': 'interview', 'questions': [{'key': f'q{i}', 'ask': f'Q{i}?', 'kind': 'text'} for i in range(11)]})
    _step(big)
    check(not storage.get_mission(big).get('plan') and _steps(big, 'refused'), "more than two rounds of five is refused")


def scenario_a2_answers_stay_on_the_mission_until_a_stage():
    _fresh()
    calls = []
    orig = (occasions.answer, meals.set_plate_hosting)
    occasions.answer = lambda *a, **k: calls.append('answer')
    meals.set_plate_hosting = lambda *a, **k: calls.append('kitchen')
    try:
        mid = _interviewed()
        res = _p().answer_plan(mid, {'headcount': 14, 'cake': True, 'theme': 'you_decide'}, dict(MOM))
        check(res['status'] == 'success' and res.get('remaining') == 3, f"three left: {res}")
        qs = {q['key']: q for q in _plan_of(mid)['questions']}
        check(qs['headcount']['answer'] == 14 and qs['headcount']['answered_by'] == 'mom', "recorded with who")
        check(qs['theme']['you_decide'] is True and qs['theme']['answer'] is None, "'you decide' is a flag, never a value")
        check(storage.get_mission(mid)['status'] == 'waiting_user', "still waiting")
        card = missions.ask_card(storage.get_mission(mid))
        check([q['key'] for q in card['questions']] == ['cooking_hands', 'gifts', 'budget'], f"the card shows what is left: {card['questions']}")
        _p().answer_plan(mid, {'cooking_hands': 2, 'gifts': True, 'budget': 40}, dict(MOM))
        check(storage.get_mission(mid)['status'] == 'running', "all answered: the planner runs on")
    finally:
        occasions.answer, meals.set_plate_hosting = orig
    check(calls == [], f"nothing reached the occasion or the kitchen: {calls}")
    check(_p().answer_plan(mid, {'budget': 50}, dict(KID))['status'] in ('refused', 'error'), "a child cannot answer")


def scenario_a3_answers_in_words_become_answers():
    _fresh()
    mid = _interviewed(template=None)
    res = missions.answer(mid, 'about 40 dollars', dict(MOM))
    check(res['status'] == 'success' and storage.get_mission(mid)['status'] == 'running', f"words answer: {res}")
    _plan({'action': 'answers', 'values': {'budget': 40}})
    _step(mid)
    q = _plan_of(mid)['questions'][0]
    check(q['answer'] == 40, f"the planner turned them into an answer: {q}")
    check(storage.get_mission(mid)['status'] == 'running', "nothing left: running")
    check('budget' in PROMPTS[-1]['user'] or 'budget' in PROMPTS[-1]['system'], "the planner sees the questions and answers")


def scenario_a4_answers_lead_every_later_prompt():
    _fresh()
    mid = _interviewed(template=None)
    _p().answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'ask_user', 'question': 'ok?'})
    _step(mid)
    head = PROMPTS[-1]['user'].split('TRANSCRIPT SO FAR')[0]
    check('What is the budget?' in head and '40' in head, f"the answers sit above the transcript:\n{head[-400:]}")


# --- B. The plan ----------------------------------------------------------------

def scenario_b1_the_plan_waits_for_approval_and_writes_nothing():
    _fresh()
    mid = _planned_mission()
    plan = _plan_of(mid)
    check(plan['state'] == 'proposed' and [s['id'] for s in plan['stages']] == ['s1', 's2'] and _ask_names(mid)[-1] == 'plan',
          f"proposed: {plan}")
    rev = plan['rev']
    ids = {o['id'] for o in _opts(mid, 'approve_plan')}
    check({f'approve_plan:{rev}:approve', f'approve_plan:{rev}:stop', f'approve_plan:{rev}:drop:s1', f'approve_plan:{rev}:drop:s2'} <= ids,
          f"the plan's options carry its rev: {ids}")
    check(not storage.get_action_proposals(), "no proposal exists before a stage is approved")
    res = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    check(res['status'] == 'success' and _plan_of(mid)['state'] == 'approved' and _plan_of(mid)['approved_by'] == 'mom', f"{res}")
    check(storage.get_mission(mid)['status'] == 'running' and not storage.get_action_proposals(), "approving writes nothing")


def scenario_b2_a_plan_that_cannot_fit_the_budget_is_refused():
    _fresh(step_cap=6)
    mid = _interviewed(template=None)
    _p().answer_plan(mid, {'budget': 40}, dict(MOM))
    _plan({'action': 'plan', 'stages': STAGES})
    _step(mid)
    check(not _plan_of(mid).get('stages') and _steps(mid, 'refused'), "1 build + 1 work of 4 needs 1 + 5 + 2 steps; the cap has fewer left")
    note = repr(_steps(mid, 'refused')[-1]['result_json']).lower()
    check('step' in note, f"said in words: {note}")


def scenario_b3_dropping_a_stage_moves_the_plan():
    _fresh()
    mid = _planned_mission()
    rev = _plan_of(mid)['rev']
    res = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:drop:s2', payload={}, actor=dict(MOM))
    check(res['status'] == 'success' and _plan_of(mid)['rev'] == rev + 1, f"rev moves: {res}")
    check(next(s for s in _plan_of(mid)['stages'] if s['id'] == 's2')['state'] == 'skipped', "the stage is left out")
    stale = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    check(stale['status'] == 'refused' and _plan_of(mid)['state'] == 'proposed', f"an old button is stale: {stale}")


def scenario_b4_words_on_a_waiting_plan_steer_never_approve():
    _fresh()
    mid = _planned_mission()
    missions.answer(mid, 'yes looks good, but no bakery', dict(MOM))
    check(_plan_of(mid)['state'] == 'proposed', "free text is never an approval")
    check(_steps(mid, 'user_steer') or _steps(mid, 'user_answer'), "it is a steer the planner reads")


def scenario_b5_only_someone_who_may_see_the_subject_approves():
    _fresh()
    mid = _planned_mission()
    storage.update_mission(mid, {'subject_kind': 'occasion', 'subject_id': 'o1', 'subject_rev': 1,
                                 'subject_history': [{'kind': 'occasion', 'id': 'o1'}]})
    rev = _plan_of(mid)['rev']
    res = situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(AUNT))
    check(res['status'] == 'refused' and _plan_of(mid)['state'] == 'proposed', f"an adult the party excludes cannot approve: {res}")
    check(not _p().may_approve(storage.get_mission(mid), dict(AUNT)) and _p().may_approve(storage.get_mission(mid), dict(MOM)), "may_approve")


# --- C. Build stages ------------------------------------------------------------

def scenario_c1_a_stage_proposes_rows_behind_one_button():
    _fresh()
    mid, st = _staged()
    check(st['state'] == 'proposed' and st['snapshot'] and [r['id'] for r in st['rows']] == ['r1', 'r2'], f"proposed: {st}")
    check(_ask_names(mid)[-1] == 'stage' and storage.get_mission(mid)['status'] == 'waiting_user', "waiting on the stage")
    for r in st['rows']:
        prop = storage.get_action_proposal(r['proposal_id'])
        check(prop['stage_id'] == 's1' and prop['row_id'] == r['id'] and prop['origin_kind'] == 'mission' and prop['origin_id'] == mid,
              f"each row is a proposal that knows its stage: {prop}")
    ids = {o['id'] for o in _opts(mid, 'run_stage')}
    snap = st['snapshot']
    check({f'run_stage:s1:{snap}:approve', f'run_stage:s1:{snap}:skip', f'run_stage:s1:{snap}:stop',
           f'run_stage:s1:{snap}:exclude:r1', f'run_stage:s1:{snap}:exclude:r2'} <= ids, f"the snapshot rides on every button: {ids}")
    check(not _opts(mid, 'do'), "no per-row Approve: the stage is the unit")


def scenario_c2_bad_rows_and_out_of_turn_stages_are_refused():
    _fresh()
    mid = _approved()
    _plan({'action': 'stage', 'stage_id': 's1', 'rows': [{'id': 'r1', 'tool': 'add_occasion_guests',
                                                          'args': {'occasion_name': "Kate's", 'who': 'x'}, 'summary': 'x'}]})
    _step(mid)
    check(_plan_of(mid)['stages'][0]['state'] == 'pending' and _steps(mid, 'refused'), "a name lookup refuses the stage")
    _plan({'action': 'stage', 'stage_id': 's2', 'rows': [{'id': 'r1', 'tool': 'draft_message', 'args': {'to': 'a', 'words': 'b'},
                                                          'summary': 'x'}]})
    _step(mid)
    check(_plan_of(mid)['stages'][1]['state'] == 'pending', "only the next pending BUILD stage")


def scenario_c3_leaving_a_row_out_makes_old_buttons_stale():
    _fresh()
    mid, st = _staged()
    snap = st['snapshot']
    res = situations.act('mission', mid, 'run_stage', option_id=f'run_stage:s1:{snap}:exclude:r2', payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"left out: {res}")
    st2 = _plan_of(mid)['stages'][0]
    check(st2['snapshot'] != snap and next(r for r in st2['rows'] if r['id'] == 'r2')['state'] == 'excluded', "a new snapshot")
    stale = situations.act('mission', mid, 'run_stage', option_id=f'run_stage:s1:{snap}:approve', payload={}, actor=dict(MOM))
    check(stale['status'] == 'refused', f"the old Do this is stale: {stale}")


def scenario_c4_no_other_door_runs_a_stage_row():
    _fresh()
    mid, st = _staged()
    pid = st['rows'][0]['proposal_id']
    res = chat_actions.act_on_proposal(pid, 'approve', dict(MOM))
    check(res['status'] == 'error' and 'stage' in res['message'].lower(), f"the per-proposal approve refuses: {res}")
    import main
    from fastapi import HTTPException
    from test_subject_audience import _as
    for call in (lambda: main.missions_proposal_act(mid, pid, body={'act': 'approve', 'member_id': 'mom'}, request=_as('mom'), background_tasks=None),):
        try:
            out = call()
            check(out.get('status') != 'success', f"the mission route refuses: {out}")
        except HTTPException as e:
            check(e.status_code in (400, 403, 409), f"refused: {e.status_code}")
    check(storage.get_action_proposal(pid)['status'] == 'proposed', "untouched")
    other = _mission(created_by='mom')
    try:
        main.missions_proposal_act(other, pid, body={'act': 'dismiss', 'member_id': 'mom'}, request=_as('mom'), background_tasks=None)
        check(False, "a proposal from another mission is refused on this mission's route")
    except HTTPException as e:
        check(e.status_code in (400, 403, 404), f"refused: {e.status_code}")


def scenario_c5_retarget_waits_for_the_stage():
    _fresh()
    mid, st = _staged()
    res = subjects.retarget('mission', mid, 'occasion', 'o2', dict(MOM))
    check(res['status'] == 'refused', f"no retarget while a stage is proposed: {res}")


# --- D. The runner --------------------------------------------------------------

def scenario_d1_rows_run_in_order_and_the_created_party_becomes_the_subject():
    _fresh()
    mid, st = _staged()
    res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s1:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    check(res['status'] == 'success', f"ran: {res}")
    st = _plan_of(mid)['stages'][0]
    check(st['state'] == 'done' and [r['state'] for r in st['rows']] == ['done', 'done'], f"both done: {st}")
    oid = st['rows'][0]['result']['created'][0]['id']
    check([g['name'] for g in storage.get_occasion_guests(oid)] == ['The Wilsons'], "the $ref reached the new occasion")
    m = storage.get_mission(mid)
    check(missions.subject_of(m)[:2] == ('occasion', oid) and {'kind': 'occasion', 'id': oid} in (m.get('subject_history') or []),
          "the created party binds as the mission's subject")
    check(m['status'] == 'running', "the planner runs on")
    for r in st['rows']:
        check(storage.get_action_proposal(r['proposal_id'])['status'] == 'approved', "each row's proposal is approved")


def scenario_d2_two_taps_run_it_once():
    _fresh()
    mid, st = _staged()
    count = []
    orig = tools.TOOL_HANDLERS['add_occasion']

    def slow(args, actor=None):
        count.append(1)
        time.sleep(0.3)
        return orig(args, actor=actor)
    tools.TOOL_HANDLERS['add_occasion'] = slow
    out = []
    try:
        ts = [threading.Thread(target=lambda: out.append(_p().run_stage(mid, 's1', st['snapshot'], dict(MOM)))) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        tools.TOOL_HANDLERS['add_occasion'] = orig
    check(len(count) == 1, f"the party was created once: {len(count)}")
    check(sum(1 for r in out if r.get('already')) == 1, f"the second tap answers 'already doing it': {out}")


def scenario_d3_a_failed_row_skips_what_needs_it():
    _fresh()
    rows = [{'id': 'r1', 'tool': 'add_occasion_guests', 'args': {'occasion_id': 'o2', 'who': 'FAIL', 'headcount': 1}, 'summary': 'fails'},
            {'id': 'r2', 'tool': 'add_occasion_guests', 'args': {'occasion_id': 'o2', 'who': 'The Lees', 'headcount': 2},
             'summary': 'needs r1', 'needs': ['r1']},
            {'id': 'r3', 'tool': 'draft_message', 'args': {'to': 'Grandma', 'words': 'Come!'}, 'summary': 'a draft'}]
    orig = tools.TOOL_HANDLERS['add_occasion_guests']
    tools.TOOL_HANDLERS['add_occasion_guests'] = (
        lambda args, actor=None: {'status': 'error', 'message': 'nobody by that name'} if args.get('who') == 'FAIL' else orig(args, actor=actor))
    try:
        mid, st = _staged(rows)
        _p().run_stage(mid, 's1', st['snapshot'], dict(MOM))
    finally:
        tools.TOOL_HANDLERS['add_occasion_guests'] = orig
    st = _plan_of(mid)['stages'][0]
    states = {r['id']: r['state'] for r in st['rows']}
    check(states == {'r1': 'failed', 'r2': 'skipped', 'r3': 'done'} and st['state'] == 'partial', f"{states} {st['state']}")
    check(not [g for g in storage.get_occasion_guests('o2') if g['name'] == 'The Lees'], "the dependent row never ran")


def scenario_d4_a_restart_never_reruns_a_row():
    _fresh()
    mid, st = _staged()
    plan = _plan_of(mid)
    plan['stages'][0]['state'] = 'running'
    plan['stages'][0]['rows'][0]['state'] = 'running'
    storage.update_mission(mid, {'plan': plan, 'status': 'running'})
    ran = []
    orig = chat_actions.run_row
    chat_actions.run_row = lambda *a, **k: ran.append(a) or {'status': 'success'}
    try:
        _p().reconcile()
    finally:
        chat_actions.run_row = orig
    st = _plan_of(mid)['stages'][0]
    check(st['rows'][0]['state'] == 'uncertain' and st['state'] == 'uncertain', f"marked uncertain: {st}")
    check(not ran, "and nothing re-ran")
    check(_ask_names(mid)[-1] == 'stage_check' and storage.get_mission(mid)['status'] == 'waiting_user', "a person is asked to check")


def scenario_d5_the_time_bound_leaves_the_rest_for_later():
    _fresh()
    rows = [{'id': f'r{i}', 'tool': 'draft_message', 'args': {'to': 'x', 'words': str(i)}, 'summary': f'd{i}'} for i in range(3)]
    mid, st = _staged(rows)
    p = _p()
    # `planned._clock` is the runner's one time source: read once at the claim,
    # then before each row; a row starts only while within CAPS['stage_seconds'].
    ticks = iter([0.0, 0.0, 500.0, 500.0, 500.0, 500.0])
    orig = p._clock
    p._clock = lambda: next(ticks, 500.0)
    try:
        p.run_stage(mid, 's1', st['snapshot'], dict(MOM))
    finally:
        p._clock = orig
    st = _plan_of(mid)['stages'][0]
    states = [r['state'] for r in st['rows']]
    check(states == ['done', 'proposed', 'proposed'] and st['state'] == 'partial', f"stopped at the bound, resumable: {states}")


def scenario_d6_a_wrong_snapshot_or_actor_runs_nothing():
    _fresh()
    mid, st = _staged()
    res = _p().run_stage(mid, 's1', 'not-the-snapshot', dict(MOM))
    check(res.get('moved') and _plan_of(mid)['stages'][0]['state'] == 'proposed', f"stale: {res}")
    res = _p().run_stage(mid, 's1', st['snapshot'], dict(KID))
    check(res['status'] == 'refused', f"a child cannot: {res}")


SCENARIOS = [
    scenario_a1_the_interview_writes_questions_and_waits,
    scenario_a2_answers_stay_on_the_mission_until_a_stage,
    scenario_a3_answers_in_words_become_answers,
    scenario_a4_answers_lead_every_later_prompt,
    scenario_b1_the_plan_waits_for_approval_and_writes_nothing,
    scenario_b2_a_plan_that_cannot_fit_the_budget_is_refused,
    scenario_b3_dropping_a_stage_moves_the_plan,
    scenario_b4_words_on_a_waiting_plan_steer_never_approve,
    scenario_b5_only_someone_who_may_see_the_subject_approves,
    scenario_c1_a_stage_proposes_rows_behind_one_button,
    scenario_c2_bad_rows_and_out_of_turn_stages_are_refused,
    scenario_c3_leaving_a_row_out_makes_old_buttons_stale,
    scenario_c4_no_other_door_runs_a_stage_row,
    scenario_c5_retarget_waits_for_the_stage,
    scenario_d1_rows_run_in_order_and_the_created_party_becomes_the_subject,
    scenario_d2_two_taps_run_it_once,
    scenario_d3_a_failed_row_skips_what_needs_it,
    scenario_d4_a_restart_never_reruns_a_row,
    scenario_d5_the_time_bound_leaves_the_rest_for_later,
    scenario_d6_a_wrong_snapshot_or_actor_runs_nothing,
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
