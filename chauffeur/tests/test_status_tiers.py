"""Tests for auto-earned status tiers (services/status_tiers.py).

Two independent single-metric ladders: chore status from lifetime points EARNED,
routine status from BEST streak. The load-bearing property is monotonicity —
spending points on a reward never demotes a kid.

Run from chauffeur/:  python tests/test_status_tiers.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import status_tiers, storage


def scenario_status_for_thresholds():
    sf = status_tiers.status_for
    tiers = [{"name": "A", "threshold": 10}, {"name": "B", "threshold": 50}, {"name": "C", "threshold": 100}]
    check(sf(0, tiers) is None, "below the first threshold = no status yet")
    check(sf(9, tiers) is None, "just under the first threshold = still none")
    check(sf(10, tiers)["name"] == "A", "meeting the first threshold reaches it")
    check(sf(75, tiers)["name"] == "B", "highest tier met wins")
    check(sf(1000, tiers)["name"] == "C", "far past the top still caps at the top tier")
    # order-independence: shuffled input still evaluates highest-met
    check(sf(75, list(reversed(tiers)))["name"] == "B", "tier order in the config doesn't matter")


def scenario_zero_threshold_is_a_default_level():
    sf = status_tiers.status_for
    tiers = [{"name": "Rookie", "threshold": 0}, {"name": "Star", "threshold": 50}]
    check(sf(0, tiers)["name"] == "Rookie", "a threshold-0 level is a default every kid starts with")
    check(sf(49, tiers)["name"] == "Rookie", "still Rookie just under the next level")
    check(sf(50, tiers)["name"] == "Star", "outgrows the default at the next threshold")


def scenario_chore_status_is_monotonic():
    storage.members_table.truncate()
    storage.points_ledger_table.truncate()
    storage.add_member({"id": "kid", "name": "Jack", "role": "child", "is_child": True})
    storage.points_ledger_table.insert({"member_id": "kid", "delta": 120, "ts": 1})   # chores earned
    storage.points_ledger_table.insert({"member_id": "kid", "delta": -50, "ts": 2})   # redeemed a reward
    check(storage.get_points_balance("kid") == 70, "current balance nets the redemption to 70")
    check(storage.get_points_earned("kid") == 120, "lifetime earned counts only positives (monotonic)")
    st = status_tiers.compute_member_status("kid", "chore")
    check(st and st["name"] == "Super Helper",
          f"chore status uses lifetime earned (120 -> Super Helper), not balance (70), got {st}")


def scenario_tracks_are_independent():
    # A kid with lots of chore points but no routine streak is a chore Legend
    # yet has NO routine status — the old shared design wrongly showed Legend on
    # both boards.
    storage.members_table.truncate()
    storage.points_ledger_table.truncate()
    storage.routines_table.truncate()
    storage.routine_checks_table.truncate()
    storage.add_member({"id": "kid", "name": "Jack", "role": "child", "is_child": True})
    storage.points_ledger_table.insert({"member_id": "kid", "delta": 600, "ts": 1})
    chore = status_tiers.compute_member_status("kid", "chore")
    routine = status_tiers.compute_member_status("kid", "routine")
    check(chore and chore["name"] == "Legend", f"chore track = Legend from 600 pts, got {chore}")
    check(routine is None, f"routine track = no status (zero streak), got {routine}")


def scenario_separate_configured_ladders():
    # The harness mocks storage.get_settings, so override it to serve two ladders.
    orig = storage.get_settings
    storage.get_settings = lambda: {
        "calendar_ids": ["primary"],
        "chore_status_tiers": [{"name": "Chore Champ", "emoji": "🏆", "threshold": 10}],
        "routine_status_tiers": [{"name": "Streak Boss", "emoji": "🔥", "threshold": 2}],
    }
    try:
        check([t["name"] for t in status_tiers.get_tiers("chore")] == ["Chore Champ"], "chore ladder is read")
        check([t["name"] for t in status_tiers.get_tiers("routine")] == ["Streak Boss"], "routine ladder is read")
        # empty falls back to that track's defaults
        storage.get_settings = lambda: {"calendar_ids": ["primary"], "chore_status_tiers": []}
        check(status_tiers.get_tiers("chore") == status_tiers.DEFAULT_CHORE_TIERS, "empty chore config -> chore defaults")
        check(status_tiers.get_tiers("routine") == status_tiers.DEFAULT_ROUTINE_TIERS, "unset routine config -> routine defaults")
    finally:
        storage.get_settings = orig


SCENARIOS = [
    scenario_status_for_thresholds,
    scenario_zero_threshold_is_a_default_level,
    scenario_chore_status_is_monotonic,
    scenario_tracks_are_independent,
    scenario_separate_configured_ladders,
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
