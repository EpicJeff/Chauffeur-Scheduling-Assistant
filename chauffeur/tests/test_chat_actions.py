"""Tests for Layer 2: typed agent action-proposals + interactive chat cards
(services/chat_actions.py + propose_family_action in agent_router).

The agent proposes a schedule-changing action as a card; a parent approves; the
approval tap executes the action and is where the admin gate is enforced. These
lock down the lifecycle, scope, idempotency, and that the router surfaces the
card onto the reply.

Run from chauffeur/:  python tests/test_chat_actions.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_router, chat_actions, storage


def _seed():
    storage.members_table.truncate()
    storage.rules_table.truncate()
    storage.agent_action_proposals_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent", "is_child": False})
    storage.add_member({"id": "kid", "name": "Jack", "role": "child", "is_child": True})


def _propose():
    return chat_actions.create_action_proposal(
        "add_routing_rule", "Mark Dad unavailable Thursday",
        {"constraint_type": "unavailable", "driver_id": "dad"}, created_by_member_id="mom")


def scenario_propose_builds_open_card():
    _seed()
    p = _propose()
    check(p["status"] == "success" and p.get("proposal_id"), "proposal is created")
    card = p["card"]
    check(card["kind"] == "action_proposal" and card["status"] == "proposed", "card starts proposed")
    check([a["act"] for a in card["actions"]] == ["approve", "dismiss"], "open card offers approve + dismiss")


def scenario_unknown_action_rejected():
    _seed()
    p = chat_actions.create_action_proposal("frobnicate", "do a thing", {})
    check(p["status"] == "error", "an unproposable action type is refused")


def scenario_parent_approve_executes_and_resolves():
    _seed()
    pid = _propose()["proposal_id"]
    before = len(storage.get_all_rules())
    res = chat_actions.act_on_proposal(pid, "approve", storage.get_member("mom"))
    check(res["status"] == "success" and len(storage.get_all_rules()) == before + 1,
          "parent approval executes the action (rule persisted)")
    check(res["card"]["status"] == "approved" and not res["card"]["actions"],
          "approved card is static (no live buttons)")
    check(res.get("schedule_dirty") is True, "a schedule-changing approval flags a re-solve")


def scenario_child_approve_denied():
    _seed()
    pid = _propose()["proposal_id"]
    before = len(storage.get_all_rules())
    res = chat_actions.act_on_proposal(pid, "approve", storage.get_member("kid"))
    check(res["status"] == "error" and len(storage.get_all_rules()) == before,
          "a child cannot approve an admin action — nothing executes")
    # still open for a parent afterward
    reopened = storage.get_action_proposal(pid)
    check(reopened["status"] == "proposed", "a denied approval leaves the proposal open")


def scenario_dismiss_does_not_execute():
    _seed()
    pid = _propose()["proposal_id"]
    before = len(storage.get_all_rules())
    res = chat_actions.act_on_proposal(pid, "dismiss", storage.get_member("kid"))
    check(res["status"] == "success" and res["card"]["status"] == "dismissed", "dismiss resolves the card")
    check(len(storage.get_all_rules()) == before, "dismiss executes nothing")


def scenario_idempotent_after_resolution():
    _seed()
    pid = _propose()["proposal_id"]
    chat_actions.act_on_proposal(pid, "approve", storage.get_member("mom"))
    again = chat_actions.act_on_proposal(pid, "approve", storage.get_member("mom"))
    check(again["status"] == "error" and "already" in again["message"],
          "an already-approved proposal cannot be re-run")


def scenario_router_surfaces_card():
    _seed()
    call = {"name": "propose_family_action",
            "arguments": {"action_type": "reassign_driver",
                          "summary": "Reassign Emma's pickup to Mom",
                          "payload": {"event_name": "pickup", "driver_name": "Mom", "target_date": "2026-08-05"}}}
    state = {"n": 0}

    def fake(prompt, tools, system_prompt):
        state["n"] += 1
        if state["n"] == 1:
            return {"message": "ok", "tool_calls": [call]}
        return {"message": "done", "tool_calls": []}

    orig = agent_router.call_gemma_with_fallback
    agent_router.call_gemma_with_fallback = fake
    try:
        res = agent_router.process_agent_request("reassign emma", source="family",
                                                 acting_member=storage.get_member("mom"))
    finally:
        agent_router.call_gemma_with_fallback = orig
    check(res.get("card") and res["card"]["status"] == "proposed",
          f"router surfaces the proposal card onto the reply, got {res.get('card')}")
    check(res["card"]["action_type"] == "reassign_driver", "card carries the proposed action type")


def scenario_new_actions_proposable_and_labeled():
    _seed()
    for at, summ in [("clear_assignment", "Clear Emma's pickup override"),
                     ("delete_errand", "Remove the dog-food errand"),
                     ("create_event", "Add Soccer Thu 4-5pm"),
                     ("update_errand", "Bump grocery run to 30 min"),
                     ("delete_priority_rule", "Drop the Mom-first rule")]:
        p = chat_actions.create_action_proposal(at, summ, {})
        check(p["status"] == "success", f"{at} is proposable")
        check(p["card"]["action_label"] and p["card"]["action_label"] != at,
              f"{at} card carries a human label, got {p['card'].get('action_label')}")


def scenario_create_event_requires_calendar():
    _seed()
    s = storage.get_settings()
    s.pop('default_calendar_id', None)
    storage.update_settings(s)
    pid = chat_actions.create_action_proposal(
        "create_event", "Add Soccer",
        {"title": "Soccer", "start": "2026-08-06T16:00:00", "end": "2026-08-06T17:00:00"})["proposal_id"]
    res = chat_actions.act_on_proposal(pid, "approve", storage.get_member("mom"))
    check(res["status"] == "error" and "calendar" in res["message"].lower(),
          f"create_event without a default calendar errors clearly, got {res}")
    check(storage.get_action_proposal(pid)["status"] == "proposed",
          "a failed execution leaves the proposal open to retry")


class _TokenReq:
    """A fake Request carrying only a member token — what `_acting_id`
    actually reads (mirrors test_missions_endpoints.py's `_TokenReq`), driven
    through the real token path rather than a stubbed resolver."""
    def __init__(self, token):
        self.headers = {'x-member-token': token}
        self.query_params = {}


def scenario_action_proposal_act_resolves_identity_not_claim():
    """Review finding: /api/action-proposals/{id}/act resolved the approver
    from the raw client-claimed member_id via storage.get_member — never
    _acting_id — so a child holding their OWN valid token could claim to be
    "mom" in the request body and be treated as that parent. Same S2
    discipline /api/missions/* and /api/mind/* already apply: a token always
    outranks the body's claim, so the child's own token wins and the
    downstream admin check in chat_actions.act_on_proposal (unchanged) still
    catches it."""
    _seed()
    import main
    from fastapi import BackgroundTasks
    pid = _propose()["proposal_id"]
    before = len(storage.get_all_rules())
    kid_token = storage.create_member_token("kid")
    req = main.ActionProposalAct(act="approve", member_id="mom")   # claims mom
    res = main.act_on_action_proposal(pid, req, BackgroundTasks(),
                                      request=_TokenReq(kid_token))
    check(res.get("status") == "error" and len(storage.get_all_rules()) == before,
          f"a child's own token outranks a claimed parent id, got {res}")
    check(req.member_id == "kid", f"the claim was corrected to the token's owner, got {req.member_id}")
    reopened = storage.get_action_proposal(pid)
    check(reopened["status"] == "proposed", "still open for the real parent afterward")

    # The real parent, with their own token, still approves normally.
    mom_token = storage.create_member_token("mom")
    req2 = main.ActionProposalAct(act="approve", member_id="mom")
    res2 = main.act_on_action_proposal(pid, req2, BackgroundTasks(),
                                       request=_TokenReq(mom_token))
    check(res2.get("status") == "success" and len(storage.get_all_rules()) == before + 1,
          f"a parent's own token still approves normally, got {res2}")


def scenario_action_proposal_list_filters_for_non_admin():
    """Review finding: the generic list endpoint is a side window around
    every parent-gated surface (mind/missions/negotiation/programs proposals
    are never posted to a chat channel), so a non-admin caller must not see
    those there even though this GET never raises. A channel-bearing
    proposal (already visible in the chat it was posted to) is unaffected."""
    _seed()
    import main
    channel_less = _propose()["proposal_id"]
    bearing = chat_actions.create_action_proposal(
        "add_car_stop", "Fuel stop on the way",
        {"title": "Gas", "location": "Shell"})["proposal_id"]
    storage.update_action_proposal(bearing, {"channel_id": "chan1"})

    kid_rows = main.list_action_proposals(request=_TokenReq(storage.create_member_token("kid")))
    kid_ids = {r["id"] for r in kid_rows}
    check(bearing in kid_ids and channel_less not in kid_ids,
          f"a child sees only channel-bearing proposals, got {kid_ids}")

    mom_rows = main.list_action_proposals(request=_TokenReq(storage.create_member_token("mom")))
    mom_ids = {r["id"] for r in mom_rows}
    check(channel_less in mom_ids and bearing in mom_ids, "a parent still sees everything")


def scenario_create_event_normalizes_datetimes():
    # The LLM emits NAIVE ISO datetimes; Google 400s any dateTime without a
    # zone ("Missing time zone definition") — the field failure where an
    # approved card came back "the calendar rejected the event".
    from unittest import mock
    from services import calendar as gcal
    _seed()

    sent = {}
    def fake_insert(calendar_id, body):
        sent['calendar_id'], sent['body'] = calendar_id, body
        return 'gid123'
    # calendar_id in the payload (the harness stubs get_settings, so the
    # default-calendar fallback isn't reachable here — covered by the
    # requires-calendar scenario above).
    def _payload(**kw):
        return {"title": "Soccer", "calendar_id": "fam@cal", **kw}
    with mock.patch.object(gcal, 'insert_event', side_effect=fake_insert), \
         mock.patch.object(gcal, 'get_calendar_timezone', return_value='America/Chicago'):
        res = chat_actions._create_event(
            _payload(start="2026-08-06T16:00:00", end="2026-08-06T17:00:00"))
        check(res["status"] == "success", f"naive datetimes accepted, got {res}")
        s = sent['body']['start']['dateTime']
        check(('+' in s[10:] or '-' in s[10:]) and s.startswith('2026-08-06T16:00:00'),
              f"naive start gained the server's local offset, got {s}")
        check(sent['body']['start'].get('timeZone') == 'America/Chicago'
              and sent['body']['end'].get('timeZone') == 'America/Chicago',
              f"calendar's IANA zone stamped (no GMT pseudo-zone in the edit UI), got {sent['body']['start']}")

        # already-zoned datetimes pass through unchanged
        res = chat_actions._create_event(
            _payload(start="2026-08-06T16:00:00-05:00", end="2026-08-06T17:00:00-05:00"))
        check(sent['body']['start']['dateTime'] == '2026-08-06T16:00:00-05:00',
              "zoned datetimes pass through unchanged")

        # all-day: Google's end date is exclusive — same-day proposals bump
        res = chat_actions._create_event(
            _payload(all_day=True, start="2026-08-06", end="2026-08-06"))
        check(res["status"] == "success" and sent['body']['end']['date'] == '2026-08-07',
              f"same-day all-day end bumped to exclusive, got {sent['body']['end']}")

        # garbage times get a specific message, never a Google round-trip
        res = chat_actions._create_event(_payload(start="Thursday-ish", end="later"))
        check(res["status"] == "error" and "couldn't understand" in res["message"],
              f"unparseable times explained, got {res}")
        res = chat_actions._create_event(
            _payload(start="2026-08-06T17:00:00", end="2026-08-06T16:00:00"))
        check(res["status"] == "error" and "isn't after" in res["message"],
              f"end-before-start explained, got {res}")


SCENARIOS = [
    scenario_propose_builds_open_card,
    scenario_new_actions_proposable_and_labeled,
    scenario_create_event_requires_calendar,
    scenario_create_event_normalizes_datetimes,
    scenario_unknown_action_rejected,
    scenario_parent_approve_executes_and_resolves,
    scenario_child_approve_denied,
    scenario_dismiss_does_not_execute,
    scenario_idempotent_after_resolution,
    scenario_router_surfaces_card,
    scenario_action_proposal_act_resolves_identity_not_claim,
    scenario_action_proposal_list_filters_for_non_admin,
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
