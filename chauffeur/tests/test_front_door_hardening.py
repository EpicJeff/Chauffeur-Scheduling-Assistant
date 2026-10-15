"""Whole-branch review fixes for the Projects front door slice 1 (Codex, 2026-10-15).

  H1 a focused continuation never speaks or plans inside a project the room may not hear;
  H2 a project focus resolves only to missions the caller (and channel) may see; hidden goals never named;
  H3 a child's follow-up on their focused project launches nothing (a parent plans it);
  H4 reshaping a body-goal wrapper keeps the pin: still private, still a body goal;
  H5 a mission adopted into a project stops when the project is dropped (membership is project_id);
  H6 a thread-origin mission joins the thread's project even when the thread is ABOUT another project;
  H7 a child's new project reaches every parent's Argyle DM with Plan it with Argyle;
  H8 explaining a project focus works, and never aloud for a project the room may not hear.

Run from chauffeur/:  python tests/test_front_door_hardening.py
"""
from harness import check  # noqa: F401
from services import storage, missions, threads
from services import agent_tools_v2 as tools
from test_front_door_chat import _fresh, _dm_cards
from test_mission_subject import _plan
from test_subjects import MOM, DAD, AUNT, KID


def _p():
    from services import projects
    return projects


def _voice():
    from services import voice_identity as voice
    return voice.VoiceContext('ha', 'assist_satellite.kitchen', 'r', 'g', service_revision=voice._revision(), paired=True)


def scenario_h1_a_focused_continuation_never_speaks_a_private_project():
    _fresh()
    first = tools.start_project('renovate the bathroom', acting_member=None, voice_context=_voice(), focus_key='voice:1')
    pid = first['project_id']
    storage.update_mission(first['mission_id'], {'status': 'done'})
    check(_p().update(pid, {'audience': 'private', 'title': 'Secret bathroom'}, dict(MOM))['status'] == 'success', "made private on the phone")
    again = tools.start_project('find a tiler', acting_member=None, voice_context=_voice(), focus_key='voice:1')
    check('Secret' not in (again.get('message') or ''), f"the room never hears the private title: {again}")
    live = [m for m in storage.get_missions() if m.get('project_id') == pid and m.get('status') in missions.LIVE]
    check(not live, f"and nothing new is planned inside the private project by voice: {live}")


def scenario_h2_a_project_focus_never_names_a_hidden_mission():
    _fresh()
    p = _p().create({'title': 'House jobs', 'goal': 'jobs', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'household'}, dict(MOM))['project']
    a = missions.launch('book a plumber', created_by='mom', project_id=p['id'], subject=('project', p['id']))['mission_id']
    b = missions.launch('buy the secret gift', created_by='mom', project_id=p['id'])['mission_id']
    storage.update_mission(b, {'subject_kind': 'list', 'subject_id': 'l2', 'subject_rev': 1})    # Mom's private list
    from services import situations
    check(not situations.can_see('mission', storage.get_mission(b), dict(DAD)), "the fixture: Dad may not see the gift mission")
    res = tools.act_on_situation(ref=p['id'], kind='project', verb='answer', text='mornings only', acting_member=dict(DAD))
    check('secret' not in (res.get('message') or '').lower(), f"never named to Dad: {res}")
    steps = [s for s in storage.get_mission_steps(b) if 'mornings' in str(s.get('result_json') or '')]
    check(not steps, "and Dad's words never reach the mission he may not see")
    check(any('mornings' in str(s.get('result_json') or '') for s in storage.get_mission_steps(a)), f"they reach the one he can: {res}")


def scenario_h3_a_childs_follow_up_launches_nothing():
    _fresh()
    tools.start_project('learn to ride a bike', acting_member=dict(KID), focus_key='channel:kid1')
    more = tools.start_project('find a bike my size', acting_member=dict(KID), focus_key='channel:kid1')
    check(storage.get_missions() == [], f"no mission a child cannot answer: {[m['goal'] for m in storage.get_missions()]}")
    check('parent' in (more.get('message') or '').lower(), f"the child hears a parent plans it: {more}")


def scenario_h4_reshaping_a_body_goal_wrapper_keeps_the_pin():
    _fresh()
    from services import planned, situations
    mid = missions.launch('get down to 185 lbs', created_by='mom')['mission_id']
    home = storage.get_mission(mid)['project_id']
    check(storage.get_project(home)['body_goal'] is True and storage.get_project(home)['audience'] == 'private', "the wrapper is a pinned body goal")
    _plan({'action': 'interview', 'questions': [{'key': 'level', 'ask': 'Where are you starting?', 'kind': 'text'}]})
    missions.step(storage.get_mission(mid))
    planned.answer_plan(mid, {'level': 'x'}, dict(MOM))
    _plan({'action': 'plan', 'project': {'title': 'Healthy routines', 'goal': 'feel good', 'done_when': 'x', 'owner': 'mom', 'audience': 'household'},
           'steps': [{'id': 'p1', 'title': 'Walk daily', 'owner': 'mom'}],
           'stages': [{'id': 's1', 'kind': 'work', 'title': 'Find a gym', 'why': 'x', 'goal': 'gyms', 'step_budget': 2, 'makes': ['gyms']}]})
    missions.step(storage.get_mission(mid))
    plan = storage.get_mission(mid).get('plan') or {}
    if plan.get('state') == 'proposed':
        situations.act('mission', mid, 'approve_plan', option_id=f"approve_plan:{plan['rev']}:approve", payload={}, actor=dict(MOM))
    p = storage.get_project(home)
    check(p['body_goal'] is True and p['audience'] == 'private', f"the pin survives any reshape: {p['title']} {p['audience']} {p['body_goal']}")
    check(len(storage.get_projects()) == 1, "and no second project")


def scenario_h5_an_adopted_mission_stops_with_its_project():
    _fresh()
    mid = missions.launch('book a plumber', created_by='mom')['mission_id']
    pid = storage.get_mission(mid)['project_id']
    check(mid in [m['id'] for m in _p()._work_missions(storage.get_project(pid))], "the adopted mission is the project's work")
    _p().set_state(pid, 'dropped', dict(MOM))
    check(storage.get_mission(mid)['status'] not in missions.LIVE, f"dropping the project stops it: {storage.get_mission(mid)['status']}")


def scenario_h6_a_threads_project_wins_over_what_it_is_about():
    _fresh()
    a = _p().create({'title': 'Kitchen', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['project']
    b = _p().create({'title': 'Garden', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['project']
    tid = threads.create(title='Plumber', owner_member_id='mom', created_by='mom', project_id=a['id'])
    storage.update_thread(tid, {'subject_kind': 'project', 'subject_id': b['id'], 'subject_rev': 1})
    mid = missions.launch('get a quote', origin_kind='thread', origin_ref=tid, created_by='mom')['mission_id']
    check(storage.get_mission(mid)['project_id'] == a['id'], "the mission joins the thread's own project")


def scenario_h7_a_childs_project_reaches_every_parent():
    _fresh()
    out = tools.start_project('learn to ride a bike', acting_member=dict(KID))
    for parent in ('mom', 'dad'):
        cards = [c['card'] for c in _dm_cards(parent) if c['card'].get('project_id') == out['project_id']]
        check(cards and cards[0]['planning'] == 'needs_plan' and 'Kate' in cards[0]['reason'],
              f"{parent} gets the hand-off card: {cards}")
    check(not [c for c in _dm_cards('aunt') if c['card'].get('project_id') == out['project_id']], "an adult outside the audience gets nothing")


def scenario_h8_explaining_a_project_focus():
    _fresh()
    out = tools.start_project('renovate the bathroom', acting_member=dict(MOM), focus_key='channel:dm1')
    res = tools.explain_situation(acting_member=dict(MOM), focus_key='channel:dm1')
    check(res['status'] == 'success' and 'renovate the bathroom' in res['message'], f"explained: {res}")
    from services import triage
    triage.set_focus('voice:9', 'project', out['project_id'], 'renovate the bathroom')
    loud = tools.explain_situation(acting_member=dict(MOM), focus_key='voice:9', spoken=True)
    check('bathroom' not in (loud.get('message') or ''), f"a private project is never explained aloud: {loud}")


SCENARIOS = [scenario_h1_a_focused_continuation_never_speaks_a_private_project, scenario_h2_a_project_focus_never_names_a_hidden_mission,
             scenario_h3_a_childs_follow_up_launches_nothing, scenario_h4_reshaping_a_body_goal_wrapper_keeps_the_pin,
             scenario_h5_an_adopted_mission_stops_with_its_project, scenario_h6_a_threads_project_wins_over_what_it_is_about,
             scenario_h7_a_childs_project_reaches_every_parent, scenario_h8_explaining_a_project_focus]

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
    raise SystemExit(1 if failed else 0)
