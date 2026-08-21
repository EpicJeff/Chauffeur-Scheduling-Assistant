"""Tests for the chore economy (storage lifecycle + main.py endpoints).

Run from chauffeur/:  python tests/test_chores.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import time
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_chores_test_")
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


def _chore(cid, title="Trash", points=10, recurrence="once", eligible=None):
    storage.add_chore({"id": cid, "title": title, "description": "",
                       "points": points, "recurrence": recurrence,
                       "eligible_member_ids": eligible or [],
                       "state": "open", "claimed_by": None, "claimed_at": None,
                       "done_at": None, "verified_by": None, "verified_at": None,
                       "rejected_reason": None, "reopens_on": None,
                       "created_at": time.time()})


def scenario_lifecycle_and_points():
    _member("kid", "Kid", "child")
    _member("mom", "Mom", "parent")
    _chore("c1", points=15, recurrence="daily")

    check(storage.claim_chore("c1", "kid") == "ok", "claim open chore")
    check(storage.claim_chore("c1", "kid") == "not_open", "double claim refused")
    check(storage.mark_chore_done("c1", "mom") is False, "only claimant marks done")
    check(storage.mark_chore_done("c1", "kid"), "claimant marks done")

    rejected = storage.reject_chore("c1", "mom", "still smelly")
    check(rejected["state"] == "claimed" and rejected["rejected_reason"] == "still smelly",
          "reject returns to claimed with reason")
    check(storage.verify_chore("c1", "mom") is None, "cannot verify a non-done chore")
    check(storage.mark_chore_done("c1", "kid"), "redo after rejection")

    result = storage.verify_chore("c1", "mom")
    check(result["awarded"] == 15, "child awarded points on verify")
    check(result["chore"]["state"] == "verified" and result["chore"]["reopens_on"],
          "daily chore gets a reopen date")
    check(storage.get_points_balance("kid") == 15, "balance reflects award")
    ledger = storage.get_points_ledger("kid")
    check(ledger[0]["chore_title"] == "Trash" and ledger[0]["by_member_id"] == "mom",
          "ledger entry carries chore + verifier")


def scenario_adults_claimable_but_pointless():
    _member("gran", "Grandma", "adult")
    _member("mom", "Mom", "parent")
    _chore("c2", points=50)
    storage.claim_chore("c2", "gran")
    storage.mark_chore_done("c2", "gran")
    result = storage.verify_chore("c2", "mom")
    check(result["awarded"] == 0, "adults earn no points")
    check(result["chore"]["state"] == "verified", "chore still completes")
    check(result["chore"]["reopens_on"] is None, "one-off chores don't reopen")
    check(storage.get_points_balance("gran") == 0, "no ledger entry for adults")


def scenario_claim_cap():
    _member("kid", "Kid", "child")
    for i in range(storage.CHORE_CLAIM_CAP):
        _chore(f"cap{i}")
        check(storage.claim_chore(f"cap{i}", "kid") == "ok", f"claim {i}")
    _chore("cap-extra")
    check(storage.claim_chore("cap-extra", "kid") == "cap", "cap enforced")
    storage.mark_chore_done("cap0", "kid")
    check(storage.claim_chore("cap-extra", "kid") == "cap",
          "done-but-unverified still counts toward the cap")


def scenario_maintenance():
    from datetime import date, timedelta
    _member("kid", "Kid", "child")
    # recurring verified with a past reopen date -> back to open
    _chore("m1", recurrence="daily")
    storage.update_chore("m1", {"state": "verified", "claimed_by": "kid",
                                "verified_by": "mom",
                                "reopens_on": (date.today() - timedelta(days=1)).isoformat()})
    # future reopen stays verified
    _chore("m2", recurrence="weekly")
    storage.update_chore("m2", {"state": "verified",
                                "reopens_on": (date.today() + timedelta(days=3)).isoformat()})
    # stale claim -> released
    _chore("m3")
    storage.update_chore("m3", {"state": "claimed", "claimed_by": "kid",
                                "claimed_at": time.time() - (storage.CHORE_STALE_CLAIM_HOURS + 1) * 3600})
    # fresh claim survives
    _chore("m4")
    storage.claim_chore("m4", "kid")

    states = {c["id"]: c for c in storage.get_all_chores()}
    check(states["m1"]["state"] == "open" and states["m1"]["claimed_by"] is None,
          "recurring chore reopened clean")
    check(states["m2"]["state"] == "verified", "future reopen untouched")
    check(states["m3"]["state"] == "open", "stale claim released")
    check(states["m4"]["state"] == "claimed", "fresh claim untouched")


def scenario_endpoint_rules():
    import main
    from fastapi import BackgroundTasks, HTTPException
    bt = BackgroundTasks()
    _member("kid", "Kid", "child")
    _member("kid2", "Other Kid", "child")
    _member("mom", "Mom", "parent")
    _member("uber", "Hired", "helper")

    chore = main.create_chore(main.ChoreCreateRequest(
        title="Dishes", points=20, recurrence="daily",
        eligible_member_ids=["kid"]), bt)
    cid = chore["id"]

    for member_id, expect, why in [("uber", 403, "helper"), ("kid2", 403, "not eligible")]:
        try:
            main.claim_chore_endpoint(cid, main.ChoreMemberRequest(member_id=member_id))
            check(False, f"expected {expect} for {why}")
        except HTTPException as e:
            check(e.status_code == expect, f"{why} refused")

    main.claim_chore_endpoint(cid, main.ChoreMemberRequest(member_id="kid"))
    main.chore_done_endpoint(cid, main.ChoreMemberRequest(member_id="kid"), bt)

    # verification is parent-token gated
    for token in (None, "bogus"):
        try:
            main.verify_chore_endpoint(cid, bt, x_member_token=token)
            check(False, "expected 403")
        except HTTPException as e:
            check(e.status_code == 403, "verify requires parent token")
    kid_token = storage.create_member_token("kid")
    try:
        main.verify_chore_endpoint(cid, bt, x_member_token=kid_token)
        check(False, "expected 403 for child token")
    except HTTPException as e:
        check(e.status_code == 403, "child token cannot verify")

    mom_token = storage.create_member_token("mom")
    result = main.verify_chore_endpoint(cid, bt, x_member_token=mom_token)
    check(result["awarded"] == 20, "parent token verifies + awards")

    balances = main.all_points()
    check([b["member_id"] for b in balances[:1]] == ["kid"], "leaderboard: children only, sorted")
    check(all(b["member_id"] != "mom" for b in balances), "parents not on the board")

    detail = main.member_points("kid")
    check(detail["balance"] == 20 and detail["ledger"][0]["delta"] == 20, "member points detail")


def scenario_adjust_and_reset():
    import main
    from fastapi import BackgroundTasks, HTTPException
    bt = BackgroundTasks()
    _member("kid", "Kid", "child")
    _member("kid2", "Other Kid", "child")
    _member("mom", "Mom", "parent")

    # adjust: relative and absolute, append-only ledger
    res = main.adjust_points_endpoint(main.PointsAdjustRequest(
        member_id="kid", delta=30, note="Helped with groceries"), bt)
    check(res["balance"] == 30, "delta adjust lands")
    res = main.adjust_points_endpoint(main.PointsAdjustRequest(
        member_id="kid", set_to=100), bt)
    check(res["delta"] == 70 and res["balance"] == 100, "set_to computes the delta")
    ledger = storage.get_points_ledger("kid")
    check(len(ledger) == 2 and all(e["reason"] == "adjust" for e in ledger),
          "adjustments are appended, not edits")
    check(ledger[1]["chore_title"] == "Helped with groceries", "note rides in chore_title")

    # validation: children only, exactly one of delta/set_to
    for req, why in [
        (main.PointsAdjustRequest(member_id="mom", delta=5), "parents have no points"),
        (main.PointsAdjustRequest(member_id="kid"), "neither delta nor set_to"),
        (main.PointsAdjustRequest(member_id="kid", delta=5, set_to=5), "both delta and set_to"),
    ]:
        try:
            main.adjust_points_endpoint(req, bt)
            check(False, f"expected 400 for {why}")
        except HTTPException as e:
            check(e.status_code == 400, f"{why} refused")
    res = main.adjust_points_endpoint(main.PointsAdjustRequest(member_id="kid", set_to=100), bt)
    check(res["delta"] == 0 and storage.get_points_ledger("kid", limit=99) and
          len(storage.get_points_ledger("kid", limit=99)) == 2, "no-op set writes no ledger entry")

    # reset: zeroes via compensating entry, denies pending redemptions
    storage.adjust_points("kid2", 40)
    storage.add_reward({"id": "rw1", "title": "Movie night", "description": "",
                        "cost": 25, "created_at": time.time()})
    red_id = storage.request_redemption("rw1", "kid")
    check(red_id not in ("missing", "insufficient"), "redemption requested")

    result = main.reset_points_endpoint(main.PointsResetRequest(), bt)
    check(result["denied_redemptions"] == 1, "pending redemption auto-denied on reset")
    check(storage.get_points_balance("kid") == 0 and storage.get_points_balance("kid2") == 0,
          "all children zeroed")
    check(storage.get_redemptions("kid", "denied"), "redemption is denied, not deleted")
    check(len(storage.get_points_ledger("kid", limit=99)) == 3, "reset appends, history intact")

    # single-member reset leaves others alone
    storage.adjust_points("kid", 10)
    storage.adjust_points("kid2", 10)
    main.reset_points_endpoint(main.PointsResetRequest(member_id="kid"), bt)
    check(storage.get_points_balance("kid") == 0, "targeted reset zeroes the target")
    check(storage.get_points_balance("kid2") == 10, "targeted reset spares everyone else")


def scenario_agent_points_tools():
    from services import agent_tools_v2
    _member("kid", "Kid", "child")
    _member("kiddo", "Kiddo", "child")
    _member("mom", "Mom", "parent")

    res = agent_tools_v2.adjust_points("Kid", delta=25, note="chat bonus")
    check(res["status"] == "success" and storage.get_points_balance("kid") == 25,
          "agent delta adjust")
    res = agent_tools_v2.adjust_points("kiddo", set_to=50)
    check(storage.get_points_balance("kiddo") == 50, "agent set_to adjust")
    res = agent_tools_v2.adjust_points("Ki")  # ambiguous prefix, no delta/set_to
    check(res["status"] == "error", "ambiguous name refused")
    res = agent_tools_v2.adjust_points("Mom", delta=5)
    check(res["status"] == "error", "parent name is not a child match")

    res = agent_tools_v2.get_point_balances()
    check(res["status"] == "success" and "Kiddo has 50" in res["message"],
          "balance summary reads naturally")


def scenario_verification_is_reachable_from_the_admin_page():
    """Verifying was PWA-only, so a parent sitting at the admin page could see
    that a kid was owed points and had to pick up a phone to award them.
    Verification is the step that PAYS — the surface a parent actually uses
    cannot be the one that can't do it.

    The guard is NOT relaxed to achieve that: the page mints a real per-device
    token from the parent's PIN, so `verified_by` names a genuine parent
    exactly as it does from the phone."""
    import main
    from fastapi import BackgroundTasks
    _member("kid", "Kid", "child")
    _member("mom", "Mom", "parent")
    _chore("c1", title="Dishes", points=12)
    storage.claim_chore("c1", "kid")
    storage.mark_chore_done("c1", "kid")

    # The token gating itself is pinned by scenario_endpoint_rules; what
    # matters here is that the admin route produces the SAME attribution
    # rather than an anonymous verification the ledger cannot explain.
    mom_token = storage.create_member_token("mom")
    result = main.verify_chore_endpoint("c1", BackgroundTasks(), mom_token)
    check(result['awarded'] == 12 and storage.get_points_balance("kid") == 12,
          "a parent token verifies and pays")
    check(storage.get_chore("c1")['verified_by'] == 'mom',
          "and the record names who did it — the reason the admin page mints a "
          "real token instead of the endpoint trusting the surface")

    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    page = open(os.path.join(tpl, 'chores.html'), encoding='utf-8').read()
    check('pendingVerification' in page and 'Waiting for you to verify' in page,
          "finished work is listed on the admin Chores page")
    check('verifyChore' in page and 'rejectChore' in page,
          "with both answers available — approving is not the only outcome")
    # The reward queue had the identical gap and literally said so on screen.
    check('decideRedemption' in page and 'approve or deny in the app' not in page,
          "reward requests are decided here too, not deferred to the phone")
    check('affordsRedemption' in page,
          "and the balance is on screen before the click, because approving "
          "deducts the full cost without the server bounds-checking it")
    check('X-Member-Token' in page and 'api/members/' in page and '/auth' in page,
          "and it authenticates properly rather than posting unauthenticated")


def scenario_a_reward_cannot_be_approved_into_the_red():
    """Holds already stop a kid REQUESTING more than they have left — spendable
    subtracts pending requests and pool pledges. The hole was on the other
    side: approval never re-checked, and a parent adjusting points downward
    does not cancel existing holds the way a reset does. So a request made
    when the points were there could still be approved after they were gone."""
    import main
    from fastapi import BackgroundTasks, HTTPException
    _member("kid", "Kid", "child")
    _member("mom", "Mom", "parent")
    storage.adjust_points("kid", 100, "seed", "mom")
    rid = storage.add_reward({"id": "r1", "title": "Movie night", "cost": 60,
                              "description": "", "pooled": False})
    check(storage.request_redemption("r1", "kid") not in ('missing', 'pooled', 'insufficient'),
          "60 of 100 is affordable")
    # The half that already worked: the first request holds its cost.
    storage.add_reward({"id": "r2", "title": "Ice cream", "cost": 50,
                        "description": "", "pooled": False})
    check(storage.request_redemption("r2", "kid") == 'insufficient',
          "a second request cannot spend the points the first is holding")

    # Now the parent takes points away without touching the pending request.
    storage.adjust_points("kid", -70, "lost the tablet", "mom")
    red = storage.get_redemptions("kid", "pending")[0]
    check(storage.decide_redemption(red['id'], "mom", True) == 'insufficient',
          "approving what the balance no longer covers is refused")
    check(storage.get_points_balance("kid") == 30, "and nothing was deducted")

    mom_token = storage.create_member_token("mom")
    try:
        main.decide_redemption_endpoint(red['id'], main.RedemptionDecision(approve=True),
                                        BackgroundTasks(), mom_token)
        check(False, "the endpoint must refuse it too")
    except HTTPException as e:
        check(e.status_code == 409 and 'Approve anyway' in e.detail,
              f"409 that says how to proceed rather than a dead end: {e.detail}")

    # Denying is never bounds-checked — closing a request costs nothing, and
    # reset_points relies on being able to deny holds against a zeroed balance.
    check(storage.decide_redemption(red['id'], "mom", False)['state'] == 'denied',
          "a denial always goes through")

    # And the override is a real decision, recorded on the row. Getting back
    # into this state needs the points to exist AT REQUEST TIME and vanish
    # afterwards — asking for 60 on a balance of 30 is refused outright, which
    # is the request-side guard doing its job.
    storage.adjust_points("kid", 70, "back on the tablet", "mom")
    check(storage.request_redemption("r1", "kid") not in ('insufficient',),
          "affordable again once the points are restored")
    storage.adjust_points("kid", -70, "lost it again", "mom")
    red2 = storage.get_redemptions("kid", "pending")[0]
    out = storage.decide_redemption(red2['id'], "mom", True, override=True)
    check(out['state'] == 'approved' and out.get('overridden') is True,
          "a parent can still say have it anyway, and it is stamped as such")
    check(storage.get_points_balance("kid") == -30,
          "the deduction is the full cost — an override is generous, not free")


def scenario_reopen():
    import main
    from fastapi import BackgroundTasks, HTTPException
    bt = BackgroundTasks()
    _member("kid", "Kid", "child")
    _member("mom", "Mom", "parent")

    # verified recurring chore reopens early; points stay
    _chore("c1", title="Trash", points=15, recurrence="daily")
    storage.claim_chore("c1", "kid")
    storage.mark_chore_done("c1", "kid")
    storage.verify_chore("c1", "mom")
    check(storage.get_chore("c1")["reopens_on"], "verified daily chore is locked until reopens_on")
    chore = main.reopen_chore_endpoint("c1", bt)
    check(chore["state"] == "open" and chore["claimed_by"] is None
          and chore["reopens_on"] is None, "reopen returns chore to the pot clean")
    check(storage.get_points_balance("kid") == 15, "earned points untouched by reopen")

    # claimed chore releases; done chore refuses toward verify/reject
    storage.claim_chore("c1", "kid")
    check(main.reopen_chore_endpoint("c1", bt)["state"] == "open", "claimed chore released")
    storage.claim_chore("c1", "kid")
    storage.mark_chore_done("c1", "kid")
    for cid, expect, why in [("c1", 409, "done chore"), ("nope", 404, "missing chore")]:
        try:
            main.reopen_chore_endpoint(cid, bt)
            check(False, f"expected {expect} for {why}")
        except HTTPException as e:
            check(e.status_code == expect, f"{why} refused")
    check(storage.reopen_chore("c1") == 'not_reopenable', "open/done states not reopenable in storage")

    # agent tool: fuzzy match, state-aware messages
    from services import agent_tools_v2
    _chore("c2", title="Water plants", points=5)
    storage.claim_chore("c2", "kid")
    res = agent_tools_v2.reopen_chore("water")
    check(res["status"] == "success" and storage.get_chore("c2")["state"] == "open",
          "agent reopens by fuzzy title")
    res = agent_tools_v2.reopen_chore("water")
    check(res["status"] == "success" and "already open" in res["message"],
          "already-open reads as a no-op success")
    res = agent_tools_v2.reopen_chore("trash")
    check(res["status"] == "error" and "verify" in res["message"],
          "done chore steered to verify/reject")
    res = agent_tools_v2.reopen_chore("no such chore")
    check(res["status"] == "error", "unknown chore errors")


def scenario_the_house_tab_carries_lists_into_the_pwa():
    """Lists had no phone surface at all — the /lists page hangs off nav.html,
    which the PWA shell never includes, so a family member's only list screen
    was a wall panel. The chores tab is House now: chores + lists as one
    household-upkeep story, with jump anchors up top (the kid My Day shape)
    and room for future sections. Asserted from the shell source the way the
    admin-page scenario above does."""
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    page = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    check('>House</span>' in page and 'house-anchors' in page
          and 'house-lists' in page,
          "the tab exists, renamed, with an anchor row and a lists section")
    check('fetchHouseLists' in page and 'api/shopping/lists' in page,
          "lists come from the scope+audience-filtered endpoint — the shell "
          "draws what the server hands it, nothing else")
    check('houseCheckItem' in page and 'houseAddItem' in page,
          "seeing a list is using it: check off and add, right on the phone")
    check('houseMaybeRevealForLists' in page,
          "a member whose chores door is closed but who holds lists gets the "
          "tab back — lists half only, the chores decision stays closed")
    check("=== 'private'" in page and '🔒' in page,
          "a private list is marked as such")
    check('houseJump' in page and 'scrollIntoView' in page,
          "the anchors actually jump")


SCENARIOS = [
    scenario_the_house_tab_carries_lists_into_the_pwa,
    scenario_verification_is_reachable_from_the_admin_page,
    scenario_a_reward_cannot_be_approved_into_the_red,
    scenario_lifecycle_and_points,
    scenario_adults_claimable_but_pointless,
    scenario_claim_cap,
    scenario_maintenance,
    scenario_endpoint_rules,
    scenario_adjust_and_reset,
    scenario_agent_points_tools,
    scenario_reopen,
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
