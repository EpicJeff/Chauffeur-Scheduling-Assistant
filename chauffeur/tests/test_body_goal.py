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


BLOCK_A = [scenario_a1_the_classifier, scenario_a2_programs_use_it]
BLOCK_B = []          # Task 3 adds the project scenarios here.
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
