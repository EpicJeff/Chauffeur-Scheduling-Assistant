"""Tests for Layer 3: the implicit-detection funnel (services/chat_actions.py).

The funnel is opt-in and must never butt in: Tier 1 is a cheap keyword filter,
Tier 2 a fail-closed classifier, and it only ever surfaces a *dismissible
proposal card* — and only when the agent actually produced one. It never mutates
anything and never posts plain chatter. These lock those invariants down.

Run from chauffeur/:  python tests/test_chat_suggestions.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import agent_router, agent_tools_v2, chat_actions, storage


def scenario_keyword_prefilter_recall_and_quiet():
    for line in ["I can't drive Emma on Thursday", "we're out of dog food",
                 "can someone pick up Jack?", "need to buy poster board", "reschedule the dentist"]:
        check(chat_actions.suggests_action(line), f"tier-1 catches action-shaped line: {line!r}")
    for line in ["good morning everyone!", "that game was awesome", "love you guys", "what a day"]:
        check(not chat_actions.suggests_action(line), f"tier-1 stays quiet on chatter: {line!r}")


def scenario_classifier_fail_closed_without_key():
    s = storage.get_settings()
    s.pop('llm_gemini_api_key', None)
    storage.update_settings(s)
    v = chat_actions.classify_actionable("I can't drive Emma Thursday")
    check(v == {"actionable": False, "confidence": 0.0},
          f"classifier fails closed with no API key, got {v}")


def _funnel_with(classify_verdict, agent_result):
    """Run the funnel with classify + agent + post all stubbed; return the
    captured post (or None) plus whether an agent run happened."""
    captured = {"posted": None, "agent_ran": False}

    orig_classify = chat_actions.classify_actionable
    orig_agent = agent_router.process_agent_request
    orig_post = agent_tools_v2._post_chat_message

    chat_actions.classify_actionable = lambda body: classify_verdict

    def fake_agent(*a, **k):
        captured["agent_ran"] = True
        return agent_result

    def fake_post(channel, sender, body, card=None):
        captured["posted"] = {"body": body, "card": card}
        return {"body": body, "card": card}

    agent_router.process_agent_request = fake_agent
    agent_tools_v2._post_chat_message = fake_post
    try:
        chat_actions.run_suggestion_funnel({"id": "fam"}, {"id": "mom", "role": "parent"}, "some line")
    finally:
        chat_actions.classify_actionable = orig_classify
        agent_router.process_agent_request = orig_agent
        agent_tools_v2._post_chat_message = orig_post
    return captured


def scenario_silent_when_not_actionable():
    cap = _funnel_with({"actionable": False, "confidence": 0.9}, {"message": "x", "card": None})
    check(cap["posted"] is None and cap["agent_ran"] is False,
          "not-actionable: agent is never even run, nothing posted")


def scenario_silent_below_confidence():
    cap = _funnel_with({"actionable": True, "confidence": 0.3}, {"message": "x", "card": None})
    check(cap["posted"] is None and cap["agent_ran"] is False,
          "low confidence: below threshold, agent not run")


def scenario_silent_when_agent_yields_no_card():
    cap = _funnel_with({"actionable": True, "confidence": 0.9},
                       {"message": "just chatting", "card": None})
    check(cap["agent_ran"] is True and cap["posted"] is None,
          "actionable but agent produced no proposal card: stay silent (no butting in)")


def scenario_surfaces_card_when_produced():
    storage.agent_action_proposals_table.truncate()
    prop = chat_actions.create_action_proposal("add_errand", "Buy dog food",
                                               {"title": "Dog food", "duration_mins": 15})
    cap = _funnel_with({"actionable": True, "confidence": 0.9},
                       {"message": "Buy dog food", "card": prop["card"]})
    check(cap["posted"] and cap["posted"]["card"]["proposal_id"] == prop["proposal_id"],
          "a produced proposal card is surfaced as a suggestion")
    bound = storage.get_action_proposal(prop["proposal_id"])
    check(bound.get("channel_id") == "fam", "the surfaced proposal is bound to its channel for follow-up")
    # It is a proposal (needs approval) — nothing was executed by surfacing it.
    check(cap["posted"]["card"]["status"] == "proposed", "surfacing is a suggestion, not an action")


SCENARIOS = [
    scenario_keyword_prefilter_recall_and_quiet,
    scenario_classifier_fail_closed_without_key,
    scenario_silent_when_not_actionable,
    scenario_silent_below_confidence,
    scenario_silent_when_agent_yields_no_card,
    scenario_surfaces_card_when_produced,
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
