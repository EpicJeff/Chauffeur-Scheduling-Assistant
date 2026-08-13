"""Tests for daily routines/streaks and the rewards store.

Run from chauffeur/:  python tests/test_routines.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import time
from datetime import date, timedelta

_TMP = tempfile.mkdtemp(prefix="chauffeur_routines_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None


def _member(mid, name, role):
    storage.add_member({"id": mid, "name": name, "role": role,
                        "color_code": "#3b82f6", "is_child": role == "child",
                        "created_at": time.time()})


def _routine(rid, member_id, title="Teeth", days=None, tod=None):
    storage.add_routine({"id": rid, "member_id": member_id, "title": title,
                         "time_of_day": tod, "days_of_week": days or [],
                         "created_at": time.time()})


def scenario_day_masks_and_checks():
    _member("kid", "Kid", "child")
    today = date.today()
    _routine("r1", "kid", "Brush teeth", tod="07:30")
    _routine("r2", "kid", "Homework", days=[today.weekday()])
    _routine("r3", "kid", "Never today", days=[(today.weekday() + 1) % 7])

    items = storage.routines_for_day("kid", today.isoformat())
    ids = [i["id"] for i in items]
    check("r1" in ids and "r2" in ids and "r3" not in ids,
          f"day-of-week mask filters, got {ids}")
    check(items[0]["id"] == "r1", "timed items sort before untimed")
    check(all(not i["checked"] for i in items), "unchecked by default")

    check(storage.set_routine_check("r1", "kid", today.isoformat(), True), "check own")
    check(not storage.set_routine_check("r1", "other", today.isoformat(), True),
          "cannot check someone else's routine")
    items = storage.routines_for_day("kid", today.isoformat())
    check(next(i for i in items if i["id"] == "r1")["checked"], "check persisted")
    storage.set_routine_check("r1", "kid", today.isoformat(), False)
    items = storage.routines_for_day("kid", today.isoformat())
    check(not next(i for i in items if i["id"] == "r1")["checked"], "uncheck works")


def scenario_streaks():
    _member("kid", "Kid", "child")
    today = date.today()
    _routine("r1", "kid", "Teeth")
    _routine("r2", "kid", "Beds")

    def complete_day(offset):
        d = (today - timedelta(days=offset)).isoformat()
        storage.set_routine_check("r1", "kid", d, True)
        storage.set_routine_check("r2", "kid", d, True)

    # 3 complete days ending yesterday; today incomplete (1 of 2)
    for off in (1, 2, 3):
        complete_day(off)
    storage.set_routine_check("r1", "kid", today.isoformat(), True)
    s = storage.compute_streak("kid")
    check(s["current"] == 3, f"incomplete today doesn't break streak, got {s['current']}")
    check(s["today_done"] == 1 and s["today_total"] == 2 and not s["today_complete"],
          "today progress reported")

    # completing today extends to 4
    storage.set_routine_check("r2", "kid", today.isoformat(), True)
    s = storage.compute_streak("kid")
    check(s["current"] == 4 and s["today_complete"], f"today completes -> 4, got {s['current']}")

    # a gap two days further back caps best; older run separated by miss
    for off in (6, 7, 8, 9):
        complete_day(off)
    s = storage.compute_streak("kid")
    check(s["current"] == 4, "missed day 5 stops the current streak")
    check(s["best"] == 4, f"best = max(run lengths) = 4, got {s['best']}")


def scenario_streak_neutral_days():
    _member("kid", "Kid", "child")
    today = date.today()
    # Only scheduled on today's weekday -> all other days are neutral
    _routine("r1", "kid", "Practice", days=[today.weekday()])
    storage.set_routine_check("r1", "kid", today.isoformat(), True)
    storage.set_routine_check("r1", "kid", (today - timedelta(days=7)).isoformat(), True)
    s = storage.compute_streak("kid")
    check(s["current"] == 2, f"neutral days bridge the streak, got {s['current']}")


def scenario_rewards_flow():
    import main
    from fastapi import BackgroundTasks, HTTPException
    bt = BackgroundTasks()
    _member("kid", "Kid", "child")
    _member("gran", "Gran", "adult")
    _member("mom", "Mom", "parent")

    # bank 100 points
    with storage.db_lock:
        storage.points_ledger_table.insert({"id": "seed", "member_id": "kid",
                                            "delta": 100, "reason": "chore", "ts": time.time()})
    reward = main.create_reward(main.RewardRequest(title="Movie night", cost=60))

    try:
        main.redeem_reward(reward["id"], main.ChoreMemberRequest(member_id="gran"), bt)
        check(False, "expected 403")
    except HTTPException as e:
        check(e.status_code == 403, "only children redeem")

    main.redeem_reward(reward["id"], main.ChoreMemberRequest(member_id="kid"), bt)
    try:
        main.redeem_reward(reward["id"], main.ChoreMemberRequest(member_id="kid"), bt)
        check(False, "expected 409")
    except HTTPException as e:
        check(e.status_code == 409, "pending request reserves points (100-60 < 60)")

    pending = storage.get_redemptions(state="pending")
    check(len(pending) == 1, "one pending redemption")

    try:
        main.decide_redemption_endpoint(pending[0]["id"], main.RedemptionDecision(approve=True),
                                        bt, x_member_token=None)
        check(False, "expected 403")
    except HTTPException as e:
        check(e.status_code == 403, "decision requires parent token")

    mom_token = storage.create_member_token("mom")
    red = main.decide_redemption_endpoint(pending[0]["id"], main.RedemptionDecision(approve=True),
                                          bt, x_member_token=mom_token)
    check(red["state"] == "approved", "approved")
    check(storage.get_points_balance("kid") == 40, "cost deducted via ledger")
    check(storage.get_points_ledger("kid")[0]["reason"] == "redeem", "ledger reason redeem")

    # deny path: no deduction (cheaper reward — only 40 pts left)
    reward2 = main.create_reward(main.RewardRequest(title="Ice cream", cost=30))
    main.redeem_reward(reward2["id"], main.ChoreMemberRequest(member_id="kid"), bt)
    check(storage.get_points_balance("kid") == 40, "request alone deducts nothing")
    p2 = storage.get_redemptions(state="pending")[0]
    main.decide_redemption_endpoint(p2["id"], main.RedemptionDecision(approve=False),
                                    bt, x_member_token=mom_token)
    check(storage.get_points_balance("kid") == 40, "deny deducts nothing")
    check(storage.decide_redemption(p2["id"], "mom", True) is None, "cannot re-decide")


SCENARIOS = [
    scenario_day_masks_and_checks,
    scenario_streaks,
    scenario_streak_neutral_days,
    scenario_rewards_flow,
]

def scenario_copy_routine_between_kids():
    """Set one kid up, copy to the next, edit the differences. Merge by
    title: re-copying is harmless, a half-built routine tops up, and the
    target's own check history is never touched."""
    reset_db()
    import main
    from fastapi import HTTPException
    _member("alex", "Alex", "child")
    _member("emma", "Emma", "child")
    # The real family's shape: the SAME title twice, morning and night.
    # Title-only dedup collapsed this pair and only one copied.
    _routine("a1", "alex", "Brush teeth", tod="07:30")
    _routine("a4", "alex", "Brush teeth", tod="19:30")
    _routine("a2", "alex", "Make bed", days=[0, 1, 2, 3, 4])
    storage.update_routine("a1", {"emoji": "X"})   # hand-picked glyph rides along

    out = main.copy_routines(main.RoutineCopyRequest(
        from_member_id="alex", to_member_id="emma"))
    check(out == {"created": 3, "skipped": 0}, f"first copy creates all three: {out}")
    emma = {(r["title"], r.get("time_of_day")): r for r in storage.get_routines("emma")}
    check(set(emma) == {("Brush teeth", "07:30"), ("Brush teeth", "19:30"),
                        ("Make bed", None)},
          f"same title at two times is two items and BOTH copy: {set(emma)}")
    check(emma[("Brush teeth", "07:30")]["emoji"] == "X",
          f"the glyph survives the copy: {emma[('Brush teeth', '07:30')]}")
    check(emma[("Make bed", None)]["days_of_week"] == [0, 1, 2, 3, 4],
          f"day masks survive the copy: {emma[('Make bed', None)]}")
    check({r["id"] for r in storage.get_routines("emma")}.isdisjoint(
          {r["id"] for r in storage.get_routines("alex")}),
          "copies get their OWN ids — shared ids would share check history")

    # THE BALANCE, resolved by lineage: Emma retimes one copy and renames
    # another. Content matching would re-import both originals on re-copy;
    # copied_from still says what they are, so nothing comes back.
    emma_am = next(r for r in storage.get_routines("emma")
                   if r["title"] == "Brush teeth" and r["time_of_day"] == "07:30")
    check(emma_am.get("copied_from") == "a1",
          f"a copy records which item it came from: {emma_am}")
    storage.update_routine(emma_am["id"], {"time_of_day": "07:45"})
    emma_bed = next(r for r in storage.get_routines("emma") if r["title"] == "Make bed")
    storage.update_routine(emma_bed["id"], {"title": "Tidy bed"})

    # Alex gains one; re-copy lands ONLY the new item.
    _routine("a3", "alex", "Feed the cat", tod="17:00")
    out = main.copy_routines(main.RoutineCopyRequest(
        from_member_id="alex", to_member_id="emma"))
    check(out == {"created": 1, "skipped": 3},
          f"edited copies are still recognised — only the new item lands: {out}")
    titles = sorted((r["title"], r.get("time_of_day")) for r in storage.get_routines("emma"))
    check(("Brush teeth", "07:30") not in titles and ("Make bed", None) not in titles,
          f"the retimed and renamed copies did NOT come back as originals: {titles}")

    # Deleting a copy and re-copying brings it back — re-copy is an explicit
    # "make it like theirs again".
    cat = next(r for r in storage.get_routines("emma") if r["title"] == "Feed the cat")
    storage.delete_routine(cat["id"])
    out = main.copy_routines(main.RoutineCopyRequest(
        from_member_id="alex", to_member_id="emma"))
    check(out == {"created": 1, "skipped": 3},
          f"a deleted copy returns on an explicit re-copy: {out}")

    # Guard rails.
    for bad, code in ((("alex", "alex"), 400), (("ghost", "emma"), 404)):
        try:
            main.copy_routines(main.RoutineCopyRequest(
                from_member_id=bad[0], to_member_id=bad[1]))
            check(False, f"{bad} should have been refused")
        except HTTPException as e:
            check(e.status_code == code, f"{bad} -> {e.status_code}, wanted {code}")
    try:
        main.copy_routines(main.RoutineCopyRequest(
            from_member_id="emma", to_member_id="alex"))
    except HTTPException:
        check(False, "copying back is legal — Alex has nothing Emma lacks")


SCENARIOS.append(scenario_copy_routine_between_kids)


def scenario_routine_times_follow_the_households_clock():
    """`time_of_day` is stored as "HH:MM" and was printed straight to the
    screen, so every routine time read as 24-hour no matter what the
    `time_format_24h` setting said. The bug class is rendering a stored clock
    string RAW — so this checks no surface does it, rather than checking one
    call site somebody could add a fourth copy beside.
    """
    import re as _re
    import sys as _sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in _sys.path:
        _sys.path.insert(0, _here)
    # Include-inlined: the routines lanes (and their formatClock) moved into
    # components/routine_lanes.html so the board card draws the same lane the
    # page does. A surface is what it RENDERS, not what one file holds.
    import tpl_source
    for name in ('app.html', 'routines.html'):
        src = tpl_source.read(name)
        # `${...time_of_day}` in a template literal, or Alpine x-text on it,
        # with no formatter in between.
        raw = _re.findall(r'\$\{[^}]*\.time_of_day\s*\}', src)
        raw += _re.findall(r'x-text="[^"]*\.time_of_day[^"]*"', src)
        raw = [r for r in raw if 'formatClock' not in r]
        check(not raw, f"{name} prints a stored clock string raw: {raw[:3]}")
        check('formatClock' in src, f"{name} has the household's clock formatter")
        # And it must actually know the setting, or the formatter is a
        # 12-hour hardcode wearing a helper's clothes.
        check('time_format_24h' in src,
              f"{name} reads the 24-hour setting rather than assuming one")


SCENARIOS.append(scenario_routine_times_follow_the_households_clock)

if __name__ == "__main__":
    import traceback

    if "CHAUFFEUR_STORAGE" not in os.environ:
        import subprocess
        worst = 0
        for be in ("tinydb", "sqlite"):
            env = dict(os.environ, CHAUFFEUR_STORAGE=be)
            print(f"=== backend: {be} ===")
            rc = subprocess.call([sys.executable, os.path.abspath(__file__)], env=env)
            worst = max(worst, rc)
        raise SystemExit(worst)

    backend = getattr(storage, "BACKEND", "tinydb")
    print(f"storage backend: {backend}  (data dir: {_TMP})")
    failed = 0
    for fn in SCENARIOS:
        try:
            reset_db()
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
