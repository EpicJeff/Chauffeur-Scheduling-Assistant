"""Every new surface that carries a project's words checks the audience (front door §5, Task 6).

Run from chauffeur/:  python tests/test_front_door_audience.py
"""
from harness import check  # noqa: F401
from services import storage
from services import agent_tools_v2 as tools
from test_front_door_chat import _fresh, _dm_cards
from test_subjects import MOM, DAD, AUNT, KID


def _p():
    from services import projects
    return projects


def scenario_the_card_follows_the_audience():
    _fresh()
    out = tools.start_project('get down to 185 lbs', acting_member=dict(MOM))
    p = storage.get_project(out['project_id'])
    check(_p().card(p, dict(DAD)) is None and _p().card(p, dict(KID)) is None, "a private body goal has no card for anyone else")
    check(_dm_cards('dad') == [], "and nothing in Dad's DM")
    kid = tools.start_project('learn to ride a bike', acting_member=dict(KID))
    kp = storage.get_project(kid['project_id'])
    check(_p().card(kp, dict(MOM)) and _p().card(kp, dict(AUNT)) is None, "a kid's project: parents yes, another adult no")


def scenario_the_wrapped_record_narrows_only():
    _fresh()
    from services import threads
    tid = threads.create(title='Pest control', owner_member_id='aunt', created_by='aunt')
    p = storage.get_project(storage.get_thread(tid)['project_id'])
    check(p['audience'] == 'parents' and _p().can_see(p, dict(MOM)) and not _p().can_see(p, dict(KID)),
          "an adult's wrapped thread: parents see it (as they saw the thread), a child does not")
    from services import situations
    check(situations.can_see('thread', storage.get_thread(tid), dict(MOM)), "the thread itself is seen exactly as before")


def scenario_the_focus_never_leaks_in_a_shared_channel():
    _fresh()
    from services import subjects
    tools.start_project('plan a surprise for Kate', acting_member=dict(MOM), focus_key='channel:dm1')
    orig = subjects.channel_humans
    subjects.channel_humans = lambda key: [dict(MOM), dict(KID)] if key == 'channel:fam' else orig(key)
    try:
        res = tools.list_projects(acting_member=dict(MOM), focus_key='channel:fam')
    finally:
        subjects.channel_humans = orig
    check('surprise' not in (res.get('message') or ''), f"list_projects in the family channel says nothing of it: {res}")


SCENARIOS = [scenario_the_card_follows_the_audience, scenario_the_wrapped_record_narrows_only, scenario_the_focus_never_leaks_in_a_shared_channel]

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
