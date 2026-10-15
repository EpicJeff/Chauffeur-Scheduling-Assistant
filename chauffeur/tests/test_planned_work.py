"""Work stages (planned missions spec §4; Codex H5, H6, H7). Task 9.

A work stage is a sub-goal Argyle pursues with its normal loop; approving it
means "go do this part". Pinned here:

  * when the next stage is a work stage, the engine STARTS it itself (no model
    call, no tap; Projects Decision 5, 2026-10-15): state 'running', a snapshot
    over goal, budget, plan rev and subject, Skip and Stop on it;
  * it starts once; an approve tap on a running stage changes nothing;
  * while it runs, every planner prompt carries `CURRENT STAGE: <title> — <goal>`
    and each step counts against its `step_budget`;
  * a `propose` during a work stage is not sent on its own: it is checked
    against the contract and queued as a row of the stage's follow-up build
    stage; `stage_done` closes the work stage with its `found`, inserts the
    follow-up right after it and proposes it (one card for all the writes);
  * spending the budget ends the stage 'partial' with Carry on;
  * the planner's `subject` action is refused mid-stage, except the first
    binding of an unbound mission, which pauses the stage and asks first;
  * a browse inside a work stage runs as in browse missions;
  * inserting a follow-up when the step cap cannot cover it waits with an ask.

Run from chauffeur/:  python tests/test_planned_work.py
"""
import threading

from harness import check  # noqa: F401
from services import storage, missions, situations
from test_planned_missions import _fresh, _planned_mission, _plan_of, _ask_names, _opts, STAGES
from test_mission_subject import _plan, _step, _steps, PROMPTS
from test_subjects import MOM


def _p():
    from services import planned
    return planned


def _work_proposed(step_cap=60):
    """A plan whose build stage is left out, approved: the next stage is the work stage."""
    _fresh(step_cap=step_cap)
    mid = _planned_mission()
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:drop:s1', payload={}, actor=dict(MOM))
    rev = _plan_of(mid)['rev']
    situations.act('mission', mid, 'approve_plan', option_id=f'approve_plan:{rev}:approve', payload={}, actor=dict(MOM))
    calls_before = len(PROMPTS)
    _step(mid)
    return mid, calls_before


def _work(mid):
    return next(s for s in _plan_of(mid)['stages'] if s['id'] == 's2')


def _go(mid):
    """Projects Decision 5: an approved plan's work stage starts itself; there is no Go tap."""
    st = _work(mid)
    check(st['state'] == 'running', f"the work stage started itself: {st}")
    return {'status': 'success'}


def scenario_the_engine_starts_the_next_work_stage_itself():
    mid, calls_before = _work_proposed()
    st = _work(mid)
    check(len(PROMPTS) == calls_before, "no model call to start it")
    check(st['state'] == 'running' and st['snapshot'] and st.get('steps_used') == 0, f"running: {st}")
    check('stage' not in _ask_names(mid), "no 'Go do this part' ask")
    labels = {o['id']: o['label'] for o in _opts(mid, 'run_stage')}
    check(labels.get(f"run_stage:s2:{st['snapshot']}:skip") == 'Skip' and labels.get(f"run_stage:s2:{st['snapshot']}:stop") == 'Stop',
          f"Skip and Stop on the running stage: {labels}")


def scenario_it_starts_once_and_a_tap_on_it_changes_nothing():
    mid, _ = _work_proposed()
    st = _work(mid)
    ts = [threading.Thread(target=lambda: _p().prepare_next(mid)) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    after = _work(mid)
    check(after['state'] == 'running' and after.get('steps_used') == 0 and after['snapshot'] == st['snapshot'],
          f"started once: {after}")
    res = situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s2:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    check(res['status'] != 'success' or res.get('already') or res.get('moved'), f"an approve on a running stage does nothing: {res}")
    check(_work(mid)['state'] == 'running' and storage.get_mission(mid)['status'] == 'running', "the planner works on it")


def scenario_the_running_stage_leads_every_prompt_and_counts_steps():
    mid, _ = _work_proposed()
    _go(mid)
    _plan({'action': 'tool', 'tool': 'find_in_chauffeur', 'args': {'query': 'bakery'}})
    _step(mid)
    head = PROMPTS[-1]['user'].split('TRANSCRIPT SO FAR')[0]
    check('CURRENT STAGE: Find a cake bakery — find two bakeries' in head, f"the stage leads the prompt:\n{head[-400:]}")
    check(_work(mid)['steps_used'] == 1, f"one step counted: {_work(mid).get('steps_used')}")


def scenario_writes_are_gathered_into_one_follow_up_build_stage():
    mid, _ = _work_proposed()
    _go(mid)
    _plan({'action': 'propose', 'tool': 'create_list', 'args': {'name': 'Bakeries'}, 'summary': 'A list of bakeries', 'why': 'compare'},
          {'action': 'propose', 'tool': 'adjust_points', 'args': {}, 'summary': 'nope', 'why': 'x'},
          {'action': 'stage_done', 'stage_id': 's2', 'summary': 'Two bakeries found', 'found': {'bakeries': ['Publix', 'Edible']}})
    _step(mid)
    check(not storage.get_action_proposals(), "no proposal is sent on its own during a work stage")
    _step(mid)
    check(_steps(mid, 'refused'), "a tool with no contract is refused, not queued")
    _step(mid)
    stages = _plan_of(mid)['stages']
    ids = [s['id'] for s in stages]
    work = next(s for s in stages if s['id'] == 's2')
    check(work['state'] == 'done' and work['found'] == {'bakeries': ['Publix', 'Edible']} and work['summary'] == 'Two bakeries found',
          f"closed with what it found: {work}")
    follow = stages[ids.index('s2') + 1]
    check(follow.get('parent') == 's2' and follow['kind'] == 'build' and [r['tool'] for r in follow['rows']] == ['create_list'],
          f"one follow-up build stage right after it, holding the queued write: {follow}")
    check(follow['state'] == 'proposed' and follow['rows'][0].get('proposal_id') and _ask_names(mid)[-1] == 'stage',
          "and it is proposed as one card")


def scenario_spending_the_budget_ends_it_partial_with_carry_on():
    mid, _ = _work_proposed()
    _go(mid)
    for _ in range(4):
        _plan({'action': 'tool', 'tool': 'find_in_chauffeur', 'args': {'query': 'bakery'}})
        _step(mid)
    st = _work(mid)
    check(st['state'] == 'partial' and storage.get_mission(mid)['status'] == 'waiting_user', f"the budget is spent: {st['state']}")
    resume = [o for o in _opts(mid, 'run_stage') if o['id'].endswith(':resume')]
    check(resume and resume[0]['label'] == 'Carry on', f"Carry on: {[o['id'] for o in _opts(mid, 'run_stage')]}")
    situations.act('mission', mid, 'run_stage', option_id=resume[0]['id'], payload={}, actor=dict(MOM))
    st = _work(mid)
    check(st['state'] == 'proposed' and st.get('steps_used') == 0, f"offered again with a fresh budget: {st}")


def scenario_no_subject_change_mid_stage_except_a_first_binding_which_asks():
    mid, _ = _work_proposed()
    _go(mid)
    _plan({'action': 'subject', 'kind': 'trip', 'id': 'ev_hawaii'})
    _step(mid)
    st = _work(mid)
    check(st['state'] == 'proposed' and missions.subject_of(storage.get_mission(mid))[:2] == ('trip', 'ev_hawaii'),
          f"a first binding is kept and pauses the stage: {st['state']}")
    card = missions.ask_card(storage.get_mission(mid))
    check(card and 'Now about' in (card.get('question') or '') and 'Hawaii' in card.get('question', ''), f"and asks: {card}")
    st = _work(mid)       # the pause asks "go on?" about the new subject; that tap stays (it is not the Go tap)
    situations.act('mission', mid, 'run_stage', option_id=f"run_stage:s2:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    check(_work(mid)['state'] == 'running', "going on resumes it")
    _plan({'action': 'subject', 'kind': 'trip', 'id': 'ev_disney'})
    _step(mid)
    check(missions.subject_of(storage.get_mission(mid))[:2] == ('trip', 'ev_hawaii') and _steps(mid, 'refused'),
          "a second change mid-stage is refused")


def scenario_a_browse_inside_a_work_stage_runs():
    mid, _ = _work_proposed()
    _go(mid)
    calls = []
    missions._browse = lambda **kw: calls.append(kw) or {'outcome': 'done', 'text': 'Publix bakery, $35 cakes', 'learned': {},
                                                        'stopped_at': 'https://publix.com', 'wanted_fields': [], 'turns': 2,
                                                        'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {}}
    _plan({'action': 'browse', 'goal': 'cake prices', 'site': 'publix.com'})
    _step(mid)
    check(calls and calls[0]['site'] == 'publix.com', "the browse ran")
    check(_work(mid)['state'] == 'running' and _work(mid)['steps_used'] == 1, "inside the running stage")


def scenario_a_follow_up_the_cap_cannot_cover_waits_with_an_ask():
    mid, _ = _work_proposed(step_cap=60)
    _go(mid)
    _plan({'action': 'propose', 'tool': 'create_list', 'args': {'name': 'Bakeries'}, 'summary': 'A list', 'why': 'x'},
          {'action': 'stage_done', 'stage_id': 's2', 'summary': 'done', 'found': {}})
    _step(mid)
    storage.update_mission(mid, {'step_count': 59})
    _step(mid)
    check(_ask_names(mid)[-1] == 'budget' and storage.get_mission(mid)['status'] == 'waiting_user', f"waits: {_ask_names(mid)}")
    card = missions.ask_card(storage.get_mission(mid))
    check(card and 'step cap' in (card.get('question') or '') and 'A list' in card.get('question', ''),
          f"says why and lists the queued writes: {card}")


SCENARIOS = [
    scenario_the_engine_starts_the_next_work_stage_itself,
    scenario_it_starts_once_and_a_tap_on_it_changes_nothing,
    scenario_the_running_stage_leads_every_prompt_and_counts_steps,
    scenario_writes_are_gathered_into_one_follow_up_build_stage,
    scenario_spending_the_budget_ends_it_partial_with_carry_on,
    scenario_no_subject_change_mid_stage_except_a_first_binding_which_asks,
    scenario_a_browse_inside_a_work_stage_runs,
    scenario_a_follow_up_the_cap_cannot_cover_waits_with_an_ask,
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
