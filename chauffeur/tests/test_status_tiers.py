"""Tests for auto-earned status tiers (services/status_tiers.py).

The load-bearing property: status is monotonic — based on lifetime points EARNED
and BEST streak, so spending points on a reward never demotes a kid.

Run from chauffeur/:  python tests/test_status_tiers.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import status_tiers, storage


def scenario_status_for_thresholds():
    sf = status_tiers.status_for
    check(sf(0, 0) is None, "below the first threshold = no status yet")
    check(sf(25, 0)["name"] == "Rising Star", "25 pts earned reaches Rising Star")
    check(sf(0, 3)["name"] == "Rising Star", "a 3-day streak reaches Rising Star on the streak track")
    check(sf(100, 0)["name"] == "Super Helper", "100 pts = Super Helper")
    check(sf(0, 30)["name"] == "Legend", "a 30-day streak = Legend")
    check(sf(500, 5)["name"] == "Legend", "the highest tier reached wins")
    check(sf(120, 14)["name"] == "Everyday Hero", "either track counts; 14-day streak lifts to Everyday Hero")
    check(sf(24, 2) is None, "just under both thresholds = still no status")


def scenario_earned_is_monotonic():
    storage.members_table.truncate()
    storage.points_ledger_table.truncate()
    storage.add_member({"id": "kid", "name": "Jack", "role": "child", "is_child": True})
    storage.points_ledger_table.insert({"member_id": "kid", "delta": 120, "ts": 1})   # chores earned
    storage.points_ledger_table.insert({"member_id": "kid", "delta": -50, "ts": 2})   # redeemed a reward
    check(storage.get_points_balance("kid") == 70, "current balance nets the redemption to 70")
    check(storage.get_points_earned("kid") == 120, "lifetime earned counts only positives (monotonic)")
    st = status_tiers.compute_member_status("kid")
    check(st and st["name"] == "Super Helper",
          f"status comes from lifetime earned (120 -> Super Helper), not balance (70), got {st}")


def scenario_no_ledger_no_status():
    storage.members_table.truncate()
    storage.points_ledger_table.truncate()
    storage.add_member({"id": "new", "name": "New", "role": "child", "is_child": True})
    check(status_tiers.compute_member_status("new") is None, "a fresh kid with no points/streak has no status")


SCENARIOS = [
    scenario_status_for_thresholds,
    scenario_earned_is_monotonic,
    scenario_no_ledger_no_status,
]

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
