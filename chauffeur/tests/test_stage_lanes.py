"""Stage shell on the wall (runway arc R1).

Stages (load arc A4) shaped the PWA from the day they shipped; the wall-panel
lanes never asked, so a Sprout and a Navigator got the identical row on the
one surface the little ones actually use. R1 puts the server's resolved
capabilities on the lane payloads and has both lane components draw per lane:

  * `/api/routines/streaks` and `/api/points` rows carry `shell`
    ({stage, glyph_scale, density, show_points, show_streaks}) for children,
    None for adults — an adult lane is not staged and draws as before;
  * a Sprout lane is glyph/photo-led and roomy (xl rows, item photos where
    they exist); a Navigator lane keeps its tight rows with points and
    streaks no longer leading. The ledger is untouched — presentation only;
  * pinned stage overrides win, exactly as `stage_of` already resolved them.

Run from chauffeur/:  python tests/test_stage_lanes.py
"""
import datetime

from harness import check  # noqa: F401

from services import storage, stages


def _seed():
    storage.members_table.truncate()
    storage.routines_table.truncate()
    y = datetime.date.today().year
    storage.add_member({"id": "tot", "name": "Tot", "role": "child",
                        "birthdate": f"{y - 4}-01-01"})
    storage.add_member({"id": "teen", "name": "Teen", "role": "child",
                        "birthdate": f"{y - 13}-01-01"})
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    for mid in ("tot", "teen", "mom"):
        storage.add_routine({"id": f"r-{mid}", "member_id": mid,
                             "title": "Brush teeth", "days_of_week": [],
                             "time_of_day": None, "steps": []})


def scenario_the_shell_rides_both_lane_payloads():
    import main
    _seed()
    streaks = {r['member_id']: r for r in main.routines_streaks()}
    check(streaks['tot']['shell']['stage'] == 'sprout'
          and streaks['tot']['shell']['glyph_scale'] == 'xl'
          and streaks['tot']['shell']['show_streaks'] is False,
          f"a four-year-old's lane is a Sprout lane: {streaks['tot']['shell']}")
    check(streaks['teen']['shell']['stage'] == 'navigator'
          and streaks['teen']['shell']['glyph_scale'] == 'sm'
          and streaks['teen']['shell']['show_points'] is False,
          f"a thirteen-year-old's is a Navigator lane: {streaks['teen']['shell']}")
    check(streaks['mom']['shell'] is None,
          "an adult lane is not staged — None, drawn exactly as before")

    storage.adjust_points("tot", 5, "seed", "mom")
    balances = {b['member_id']: b for b in main.all_points()}
    check(balances['tot']['shell'] and balances['tot']['shell']['stage'] == 'sprout',
          "the chores lanes payload carries the same shell")


def scenario_a_pinned_stage_wins_on_the_wall_too():
    import main
    _seed()
    storage.update_member("teen", {"stage_override": "explorer"})
    streaks = {r['member_id']: r for r in main.routines_streaks()}
    check(streaks['teen']['shell']['stage'] == 'explorer'
          and streaks['teen']['shell']['show_streaks'] is True,
          f"the pin resolves before the lane draws: {streaks['teen']['shell']}")


def scenario_the_lanes_actually_ask():
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates', 'components')
    lanes = open(os.path.join(tpl, 'routine_lanes.html'), encoding='utf-8').read()
    check('shellOf(' in lanes and "glyph_scale === 'xl'" in lanes,
          "routine lanes size rows and glyphs by the lane's shell")
    check('it.image_id && shellBig(s)' in lanes,
          "a Sprout/Explorer row is photo-led where a photo exists")
    check("s.shell ? s.shell.show_streaks : true" in lanes,
          "the streak flame respects the stage, adults keep it")
    # Steps wear the same shell as their item — one level down, same rule.
    step_block = lanes[lanes.index('rst-'):]
    check("shellOf(s).glyph_scale === 'xl' ? 'w-7 h-7" in step_block,
          "a Sprout's step ticks are big taps, not fine print")
    app = open(os.path.join(os.path.dirname(tpl), 'app.html'),
               encoding='utf-8').read()
    check("const xl = sh.glyph === 'xl'" in app,
          "kid My Day steps scale with the stage shell too")
    chores = open(os.path.join(tpl, 'chores_lanes.html'), encoding='utf-8').read()
    check('shellXl(b)' in chores and 'shellPoints(b)' in chores,
          "chores lanes scale rows and stop leading with points per stage")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

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
