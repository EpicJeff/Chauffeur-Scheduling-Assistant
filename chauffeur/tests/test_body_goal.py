"""One body-goal classifier (Projects core spec §1 "Body goals", Tasks 2 and 3).

`body_goal.is_body_goal(text)` is the single check for project titles, goals,
done-whens, step titles and program aims: today's program screen phrases and
words, plus "weight loss" and numeric weight and body-measurement targets.
Programs call it, closing the gaps Codex found ("reach 70 kg" passes today).

Block A (Task 2): the classifier and the program screen.
Block B (Task 3): projects use it; an adult's private body goal is allowed and
pinned; anything else is refused.

Run from chauffeur/:  python tests/test_body_goal.py
"""
from harness import check  # noqa: F401

BODY = ["reach 70 kg", "get down to 185 lbs", "lose 10 pounds", "waist to 24 inches", "weight loss",
        "BMI under 25", "body fat 15%", "lose weight", "drop a size", "hit 12 stone", "Get to 80kg by summer"]
NOT_BODY = ["run a 5k in 30 minutes", "cook 4 nights a week", "learn Portuguese",
            "build 3 shelves 24 inches wide", "walk 10,000 steps a day", "renovate the bathroom", "", None]


# --- Block A: the classifier and programs (Task 2) ---------------------------

def scenario_a1_the_classifier():
    from services import body_goal
    for text in BODY:
        check(body_goal.is_body_goal(text) is True, f"a body goal: {text!r}")
    for text in NOT_BODY:
        check(body_goal.is_body_goal(text) is False, f"not a body goal: {text!r}")


def scenario_a2_programs_use_it():
    from services import programs_curate
    check(programs_curate.screen_aim('reach 70 kg')['ok'] is False, "a program refuses 'reach 70 kg' (it passed before)")
    check(programs_curate.screen_aim('waist to 24 inches')['ok'] is False, "and a body measurement")
    check(programs_curate.screen_starting_point('currently 90 kg')['ok'] is False, "the starting point too")
    check(programs_curate.screen_aim('learn Portuguese')['ok'] is True, "an ordinary aim passes")
    check(programs_curate.screen_aim('lose weight')['ok'] is False, "the old phrases still refuse")


# --- Block B: projects (Task 3) ------------------------------------------------

def _projects():
    from test_projects import _fresh
    _fresh()
    from services import projects
    return projects


def scenario_b1_an_adults_private_body_goal_is_allowed_and_pinned():
    from test_subjects import MOM
    from services import storage
    projects = _projects()
    res = projects.create({'title': 'Get down to 185 lbs', 'goal': 'feel better on hikes', 'done_when': 'the scale says 185',
                           'owner_member_id': 'mom'}, dict(MOM))
    check(res['status'] == 'success', f"allowed for an adult: {res}")
    p = res['project']
    check(p['body_goal'] is True and p['audience'] == 'private', f"marked and private: {p}")
    for change in ({'audience': 'parents'}, {'audience': 'household'}, {'owner_member_id': 'kid'}):
        out = projects.update(p['id'], change, dict(MOM))
        check(out['status'] == 'error', f"the pin holds against {change}: {out}")
    check(storage.get_project(p['id'])['audience'] == 'private', "still private")
    check(projects.update(p['id'], {'body_goal': False}, dict(MOM))['status'] == 'error'
          or storage.get_project(p['id'])['body_goal'] is True, "a client never clears the mark")


def scenario_b2_anything_else_is_refused():
    from test_subjects import MOM, KID
    projects = _projects()
    for fields, actor, why in (
            ({'title': 'Get down to 185 lbs', 'audience': 'household', 'owner_member_id': 'mom'}, MOM, "a shared adult body goal"),
            ({'title': 'Get down to 185 lbs', 'audience': 'parents', 'owner_member_id': 'mom'}, MOM, "a parents-audience body goal"),
            ({'title': 'Lose 10 pounds', 'owner_member_id': 'kid'}, KID, "a child's own body goal"),
            ({'title': 'Lose 10 pounds', 'owner_member_id': 'kid'}, MOM, "a body goal a parent makes for a child")):
        res = projects.create({'goal': 'x', 'done_when': 'x', **fields}, dict(actor))
        check(res['status'] == 'error', f"refused: {why}: {res}")
    ok = projects.create({'title': 'Garage', 'goal': 'clear it', 'done_when': 'the car fits', 'owner_member_id': 'mom',
                          'audience': 'household'}, dict(MOM))['project']
    out = projects.update(ok['id'], {'goal': 'and reach 70 kg'}, dict(MOM))
    check(out['status'] == 'error', f"an edit that makes a shared project a body goal is refused: {out}")
    out = projects.update(ok['id'], {'done_when': 'waist to 32 inches'}, dict(MOM))
    check(out['status'] == 'error', f"the done-when is screened too: {out}")


BLOCK_A = [scenario_a1_the_classifier, scenario_a2_programs_use_it]
BLOCK_B = [scenario_b1_an_adults_private_body_goal_is_allowed_and_pinned, scenario_b2_anything_else_is_refused]
SCENARIOS = BLOCK_A + BLOCK_B

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
