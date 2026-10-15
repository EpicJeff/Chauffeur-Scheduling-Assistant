"""The chat front door (front door spec §1, §5, §6, slice 1, Task 3):
start_project creates the project at once, posts its card first, plans inside.

Run from chauffeur/:  python tests/test_front_door_chat.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations, triage
from services import agent_tools_v2 as tools
from test_mission_subject import _fresh as _fresh_subjects, _plan
from test_subjects import MOM, DAD, AUNT, KID


def _fresh(missions_on=True):
    _fresh_subjects()
    storage.projects_table.truncate()
    base = storage.get_settings()
    storage.get_settings = (lambda s, on: (lambda: dict(s, missions_enabled=on)))(base, missions_on)
    from services import model_pools
    model_pools.api_key_for_pool = lambda pool, settings=None: 'k'
    _plan({'action': 'interview', 'questions': [{'key': 'level', 'ask': 'Where are you starting?', 'kind': 'text'}]})


def _dm_cards(member_id):
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], member_id)
    return [m for m in storage.get_channel_messages(dm['id']) if m.get('card')]


def _p():
    from services import projects
    return projects


def scenario_the_project_exists_at_once_and_its_card_comes_first():
    _fresh()
    out = tools.start_project('I want to learn Brazilian Portuguese', acting_member=dict(MOM), focus_key='channel:dm1')
    check(out['status'] == 'success' and out['project_id'] and out['mission_id'], f"started: {out}")
    p = storage.get_project(out['project_id'])
    check(p['goal'] == 'I want to learn Brazilian Portuguese' and p['owner_member_id'] == 'mom' and p['audience'] == 'private'
          and p['state'] == 'active', f"the project in the person's words: {p}")
    m = storage.get_mission(out['mission_id'])
    check(m['project_id'] == p['id'] and missions.subject_of(m)[:2] == ('project', p['id']), "the planning mission is bound and adopted")
    cards = _dm_cards('mom')
    check(cards and cards[0]['card']['kind'] == 'project' and cards[0]['card']['project_id'] == p['id'],
          f"the project card is the first card in Mom's DM: {[c['card']['kind'] for c in cards]}")
    check(cards[0]['card']['planning'] == 'started', f"and says planning started: {cards[0]['card']}")
    f = triage.get_focus('channel:dm1')
    check(f and f['kind'] == 'project' and f['id'] == p['id'], f"the project is the focus: {f}")


def scenario_approval_inside_the_started_project_appends_steps():
    _fresh()
    from services import planned
    out = tools.start_project('I want to learn Brazilian Portuguese', acting_member=dict(MOM))
    mid, pid = out['mission_id'], out['project_id']
    missions.step(storage.get_mission(mid))
    planned.answer_plan(mid, {'level': 'never'}, dict(MOM))
    _plan({'action': 'plan', 'steps': [{'id': 'p1', 'title': 'Attend a first class', 'owner': 'mom'}],
           'stages': [{'id': 's1', 'kind': 'work', 'title': 'Find meetups', 'why': 'practice', 'goal': 'meetups', 'step_budget': 2, 'makes': ['meetups']}]})
    missions.step(storage.get_mission(mid))
    card = missions.ask_card(storage.get_mission(mid))
    check(card['project']['id'] == pid, f"the plan card names the existing project, proposes no new one: {card.get('project')}")
    plan = storage.get_mission(mid)['plan']
    situations.act('mission', mid, 'approve_plan', option_id=f"approve_plan:{plan['rev']}:approve", payload={}, actor=dict(MOM))
    check(len(storage.get_projects()) == 1 and {s['title'] for s in storage.get_project(pid)['steps']} == {'Attend a first class', 'Find meetups'},
          f"steps appended to the one project: {[p['title'] for p in storage.get_projects()]}")


def scenario_dedupe_is_by_owner_subject_and_intent():
    _fresh()
    first = tools.start_project('learn Portuguese', for_member_name='Kate', acting_member=dict(MOM))
    again = tools.start_project('learn Portuguese', for_member_name='Kate', acting_member=dict(MOM))
    check(again['status'] == 'success' and again['project_id'] == first['project_id'] and 'already under way' in again['message'],
          f"the same goal for the same person is named, not doubled: {again}")
    other = tools.start_project('learn Portuguese', for_member_name='Mom', acting_member=dict(MOM))
    check(other['project_id'] != first['project_id'], "Kate's project never blocks Mom's")
    check(len(storage.get_projects()) == 2, f"two projects: {[p['title'] for p in storage.get_projects()]}")


def scenario_two_matches_ask_which():
    _fresh()
    a = _p().create({'title': 'Learn Portuguese', 'goal': 'learn Portuguese fast', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['project']
    b = _p().create({'title': 'Portuguese trip', 'goal': 'learn Portuguese basics', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['project']
    out = tools.start_project('learn Portuguese', acting_member=dict(MOM))
    check(out['status'] == 'ambiguous' and a['title'] in out['message'] and b['title'] in out['message'],
          f"asks which rather than suppressing: {out}")
    check(len(storage.get_projects()) == 2, "nothing created")


def scenario_voice_dedupe_is_spoken_safe():
    _fresh()
    from services import voice_identity as voice
    _p().create({'title': 'Secret Portuguese', 'goal': 'learn Portuguese', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'private'}, dict(MOM))
    ctx = voice.VoiceContext('ha', 'assist_satellite.kitchen', 'r', 'g', service_revision=voice._revision(), paired=True)
    out = tools.start_project('learn Portuguese', acting_member=None, voice_context=ctx, focus_key='voice:1')
    check('Secret' not in (out.get('message') or ''), f"a household voice request never hears a parent's private project: {out}")
    check(out['status'] == 'success' and storage.get_project(out['project_id'])['audience'] == 'household',
          f"a voice-started project is household, owned by the parent of record: {out}")


def scenario_not_a_project_drops_project_and_mission_in_one_write():
    _fresh()
    out = tools.start_project('get the dishwasher fixed', acting_member=dict(MOM))
    res = _p().set_state(out['project_id'], 'dropped', dict(MOM))
    check(res['status'] == 'success' and storage.get_project(out['project_id'])['state'] == 'dropped', "dropped")
    check(storage.get_mission(out['mission_id'])['status'] in ('dropped', 'blocked', 'done'), f"its planning mission is over: {storage.get_mission(out['mission_id'])['status']}")


def scenario_missions_off_still_creates_the_project():
    _fresh(missions_on=False)
    out = tools.start_project('renovate the bathroom', acting_member=dict(MOM))
    check(out['status'] == 'success' and out['project_id'] and out['mission_id'] is None, f"project without planning: {out}")
    card = _dm_cards('mom')[0]['card']
    check(card['planning'] == 'off' and 'Missions are off' in card['reason'], f"the card says why: {card}")


def scenario_a_child_starts_a_project_and_a_parent_plans_it():
    _fresh()
    out = tools.start_project('learn to ride a bike', acting_member=dict(KID))
    p = storage.get_project(out['project_id'])
    check(out['status'] == 'success' and out['mission_id'] is None and p['owner_member_id'] == 'kid' and p['audience'] == 'parents',
          f"created, nothing launched: {out} {p}")
    card = _dm_cards('kid')[0]['card']
    check(card['planning'] == 'needs_parent' and 'Ask a parent' in card['reason'], f"the kid's card: {card}")
    check(_p().needs_plan(p) is True, "flagged for a parent's Needs you")
    check(storage.get_missions() == [], "no mission a child cannot answer")


def scenario_body_goal_pins_private_and_refuses_a_child():
    _fresh()
    out = tools.start_project('get down to 185 lbs', acting_member=dict(MOM))
    p = storage.get_project(out['project_id'])
    check(p['body_goal'] is True and p['audience'] == 'private', f"an adult's body goal is private: {p}")
    kid = tools.start_project('lose 10 pounds', acting_member=dict(KID))
    check(kid['status'] == 'error' and not any(x['owner_member_id'] == 'kid' for x in storage.get_projects()), f"never for a minor: {kid}")


def scenario_channel_refusal_has_no_words():
    _fresh()
    from services import subjects
    orig = subjects.channel_humans
    subjects.channel_humans = lambda key: [dict(MOM), dict(KID)] if key == 'channel:fam' else orig(key)
    try:
        out = tools.start_project('plan a surprise for Kate', acting_member=dict(MOM), focus_key='channel:fam')
    finally:
        subjects.channel_humans = orig
    check(out['status'] == 'refused' and 'surprise' not in out['message'] and storage.get_projects() == [],
          f"refused with no words in a channel some member may not see: {out}")


def scenario_a_correction_with_a_project_focus_reaches_its_live_mission():
    _fresh()
    out = tools.start_project('get the dishwasher fixed', acting_member=dict(MOM), focus_key='channel:dm1')
    missions.step(storage.get_mission(out['mission_id']))   # the interview is asked; the mission waits on the person
    res = tools.act_on_situation(ref=out['project_id'], kind='project', verb='answer', text='use the manufacturer instead',
                                 acting_member=dict(MOM), focus_key='channel:dm1')
    check(res['status'] in ('success', 'planned'), f"the project focus resolved to its live mission: {res}")
    steps = storage.get_mission_steps(out['mission_id'])
    check(any('manufacturer' in str(s.get('result_json') or '') for s in steps), f"the steer landed on the mission: {[s['name'] for s in steps]}")


def scenario_a_new_goal_on_a_focused_project_plans_inside_it():
    _fresh()
    out = tools.start_project('renovate the bathroom', acting_member=dict(MOM), focus_key='channel:dm1')
    storage.update_mission(out['mission_id'], {'status': 'done'})
    more = tools.start_project('find a tiler', acting_member=dict(MOM), focus_key='channel:dm1')
    check(more['project_id'] == out['project_id'] and more['mission_id'] != out['mission_id'] and len(storage.get_projects()) == 1,
          f"a new goal on the focused project is new planning inside it: {more}")


SCENARIOS = [scenario_the_project_exists_at_once_and_its_card_comes_first, scenario_approval_inside_the_started_project_appends_steps,
             scenario_dedupe_is_by_owner_subject_and_intent, scenario_two_matches_ask_which, scenario_voice_dedupe_is_spoken_safe,
             scenario_not_a_project_drops_project_and_mission_in_one_write, scenario_missions_off_still_creates_the_project,
             scenario_a_child_starts_a_project_and_a_parent_plans_it, scenario_body_goal_pins_private_and_refuses_a_child,
             scenario_channel_refusal_has_no_words, scenario_a_correction_with_a_project_focus_reaches_its_live_mission,
             scenario_a_new_goal_on_a_focused_project_plans_inside_it]

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
