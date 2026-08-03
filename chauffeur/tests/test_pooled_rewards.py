"""Tests for pooled rewards / family goals (storage semantics + agent tool).

A pledge is a hold — spendable = balance - pending redemptions - pledges,
nothing hits the ledger until a parent grants the funded pool.

Run from chauffeur/:  python tests/test_pooled_rewards.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="chauffeur_pool_test_")
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
                       "color_code": "#3b82f6", "avatar": None,
                        "is_child": role == "child", "created_at": time.time()})


def _reward(rid, title="Movie Night", cost=150, pooled=True, min_share=0):
    storage.add_reward({"id": rid, "title": title, "description": "",
                        "cost": cost, "pooled": pooled, "min_share": min_share,
                        "created_at": time.time()})


def _family():
    _member("a", "Ava", "child")
    _member("b", "Ben", "child")
    _member("c", "Cal", "child")
    _member("mom", "Mom", "parent")
    storage.adjust_points("a", 120, "seed")
    storage.adjust_points("b", 100, "seed")


def scenario_pledge_holds_and_clamping():
    _family()
    _reward("goal", cost=150, min_share=20)
    _reward("plain", title="Ice cream", cost=30, pooled=False)

    check(storage.request_redemption("goal", "a") == "pooled",
          "pooled reward refuses individual redemption")
    check(storage.contribute_to_pool("plain", "a", 10)[0] == "not_pooled",
          "plain reward refuses pledges")
    check(storage.contribute_to_pool("nope", "a", 10)[0] == "missing", "missing reward")
    check(storage.contribute_to_pool("goal", "a", 0)[0] == "invalid", "zero amount refused")

    check(storage.contribute_to_pool("goal", "a", 100) == ("ok", 100), "first pledge")
    check(storage.get_spendable_points("a") == 20, "pledge holds spendable points")
    check(storage.get_points_balance("a") == 120, "pledge never touches the ledger")

    check(storage.contribute_to_pool("goal", "a", 30)[0] == "insufficient",
          "pledge beyond spendable refused")
    check(storage.contribute_to_pool("goal", "a", 20) == ("ok", 20),
          "second pledge adds to the first")
    check(storage.request_redemption("plain", "a") == "insufficient",
          "pledges count against redemption spendable too")

    check(storage.contribute_to_pool("goal", "b", 50) == ("ok", 30),
          "pledge clamps to what's remaining")
    status = storage.get_pool_status(storage.get_rewards()[0]
                                     if storage.get_rewards()[0]["id"] == "goal"
                                     else storage.get_rewards()[1])
    check(status["pledged"] == 150 and status["funded"], "pool fully funded")
    check(storage.contribute_to_pool("goal", "b", 10)[0] == "full", "full pool refuses more")


def scenario_withdraw_and_clear():
    _family()
    _reward("goal", cost=150)
    storage.contribute_to_pool("goal", "a", 60)
    check(storage.get_spendable_points("a") == 60, "hold active")
    check(storage.withdraw_pool_pledge("goal", "a") == 60, "withdraw returns amount")
    check(storage.get_spendable_points("a") == 120, "hold released")
    check(storage.withdraw_pool_pledge("goal", "a") == 0, "nothing left to withdraw")

    storage.contribute_to_pool("goal", "a", 40)
    storage.contribute_to_pool("goal", "b", 40)
    check(storage.clear_pool("goal") == 2, "clear releases every pledge")
    check(storage.get_pool_contributions(reward_id="goal") == [], "pool empty after clear")


def scenario_grant_min_share_and_ledger():
    _family()
    _reward("goal", cost=150, min_share=20)
    storage.contribute_to_pool("goal", "a", 120)
    _, err = storage.grant_pool("goal", "mom")
    check(err == "unfunded", "underfunded pool refuses grant")
    storage.contribute_to_pool("goal", "b", 30)

    reward = next(r for r in storage.get_rewards() if r["id"] == "goal")
    status = storage.get_pool_status(reward)
    check(status["short"] == ["Cal"], "child with no pledge is short of min_share")
    _, err = storage.grant_pool("goal", "mom")
    check(err == "short", "min_share blocks grant without force")

    red, err = storage.grant_pool("goal", "mom", force=True)
    check(err is None and red["pooled"] and red["member_id"] is None,
          "forced grant writes a pooled redemption row")
    check(red["cost"] == 150 and len(red["contributions"]) == 2,
          "redemption carries the per-child split")
    check(storage.get_points_balance("a") == 0 and storage.get_points_balance("b") == 70,
          "each contributor debited exactly their pledge")
    ledger_a = storage.get_points_ledger("a")
    check(ledger_a[0]["reason"] == "redeem" and ledger_a[0]["delta"] == -120
          and ledger_a[0]["by_member_id"] == "mom",
          "ledger entry carries reason + granter")
    check(storage.get_pool_contributions(reward_id="goal") == [], "pledges cleared on grant")
    check(storage.get_redemptions("a") == [], "pooled row not attributed to one child")
    check(any(r.get("pooled") for r in storage.get_redemptions()),
          "pooled row visible in full history (digest source)")
    _, err = storage.grant_pool("goal", "mom", force=True)
    check(err == "unfunded", "granted pool can't be granted again")


def scenario_reset_and_reward_lifecycle_release_pledges():
    _family()
    _reward("goal", cost=150)
    storage.contribute_to_pool("goal", "a", 50)
    result = storage.reset_points("a")
    check(result["released_pledges"] == 1, "reset releases the pledge")
    check(storage.get_points_balance("a") == 0, "balance zeroed")
    check(storage.get_pool_contributions(member_id="a") == [], "no orphaned hold")

    storage.contribute_to_pool("goal", "b", 40)
    storage.update_reward("goal", {"pooled": False, "min_share": 0})
    check(storage.get_pool_contributions(reward_id="goal") == [],
          "un-pooling a reward releases pledges")

    storage.update_reward("goal", {"pooled": True})
    storage.contribute_to_pool("goal", "b", 40)
    storage.delete_reward("goal")
    check(storage.get_pool_contributions(reward_id="goal") == [],
          "deleting a reward releases pledges")


def scenario_agent_tools():
    from services import agent_tools_v2 as tools
    _family()
    _reward("goal", title="Family Movie Night", cost=150, min_share=0)

    res = tools.get_family_goals()
    check(res["status"] == "success" and "Family Movie Night" in res["message"],
          "goals listed")

    res = tools.contribute_to_family_goal("movie", 50, member_name="Ava")
    check(res["status"] == "success" and "50/150" in res["message"], "agent pledge works")
    check(storage.get_spendable_points("a") == 70, "agent pledge holds points")

    res = tools.contribute_to_family_goal("movie", 50, member_name="Mom")
    check(res["status"] == "error", "non-child refused")
    res = tools.contribute_to_family_goal("movie", 50)
    check(res["status"] == "error", "unknown actor must be asked for")
    res = tools.contribute_to_family_goal("zorp", 50, member_name="Ben")
    check(res["status"] == "error", "unknown goal refused")

    res = tools.contribute_to_family_goal("movie", 10, member_name="Cal")
    check(res["status"] == "error" and "spendable" in res["message"],
          "pledge beyond spendable refused (Cal has no points)")
    # "Put 500 toward it" clamps to the 100 remaining, which Ben can afford.
    res = tools.contribute_to_family_goal("movie", 500, member_name="Ben")
    check(res["status"] == "success" and "Only 100 was needed" in res["message"]
          and "fully funded" in res["message"],
          "over-ask clamps to remaining and announces the funded pool")
    res = tools.get_family_goals()
    check("fully funded" in res["message"], "goal listing reflects funded state")
    check(storage.get_pool_status(
        next(r for r in storage.get_rewards() if r["id"] == "goal"))["funded"],
        "pool funded via agent pledges")


SCENARIOS = [
    scenario_pledge_holds_and_clamping,
    scenario_withdraw_and_clear,
    scenario_grant_min_share_and_ledger,
    scenario_reset_and_reward_lifecycle_release_pledges,
    scenario_agent_tools,
]

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
