"""Argyle can look for a deal. Argyle cannot send the asks on its own."""
from harness import check
from services import agent_tools, agent_tools_v2, storage


def scenario_both_stacks_can_look():
    names = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('negotiate_day' in names, f"the Gemma stack has it, got {len(names)} tools")
    check('negotiate_day' in agent_tools.TOOL_SCHEMAS,
          "and so does the v1 loop")


def scenario_only_the_new_stack_can_ask():
    names = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('ask_deal' in names, "asking lives where identity is resolved")
    check('ask_deal' not in agent_tools.TOOL_SCHEMAS,
          "and not in the admin loop, which resolves nobody")


def scenario_asking_refuses_an_unresolved_caller():
    res = agent_tools_v2.ask_deal('Soccer', acting_member=None)
    check(res.get('status') == 'error',
          f"an anonymous wall panel may not fan out asks, got {res}")


def scenario_asking_refuses_a_child():
    res = agent_tools_v2.ask_deal('Soccer',
                                  acting_member={'id': 'k1', 'role': 'child'})
    check(res.get('status') == 'error', f"nor may a kid, got {res}")


def scenario_looking_never_asks():
    """negotiate_day must not create a single request, whatever it finds."""
    before = len(storage.get_requests(status='open'))
    agent_tools_v2.negotiate_day(day='2026-09-07',
                                 acting_member={'id': 'p1', 'role': 'parent'})
    after = len(storage.get_requests(status='open'))
    check(before == after,
          f"searching is free and silent, got {before} -> {after}")


def scenario_a_fuzzy_day_is_resolved_before_the_lookup():
    """"Tuesday" and "tomorrow" are what a model says. Handed straight to the
    day cache they miss, and a miss reads as "Nothing on Tuesday needs a deal
    — it all covers": a confident all-clear on the exact question this tool
    exists to answer."""
    import datetime
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    res = agent_tools_v2.negotiate_day(
        day='tomorrow', acting_member={'id': 'p1', 'role': 'parent'})
    check(tomorrow in res.get('message', ''),
          f"'tomorrow' has to become a real date, got {res}")
    check('tomorrow' not in res.get('message', ''),
          f"and never be echoed back as if it were one, got {res}")


def scenario_one_chat_turn_cannot_spend_three_deep_budgets():
    """The deep budget is for ONE question somebody is waiting on. Spent per
    seed it becomes three of them — up to 120 CP-SAT replays inside a 120 s
    Assist budget, from a single chat turn."""
    from services import negotiation, storage as _st
    budgets = []
    real = negotiation.propose
    negotiation.propose = lambda d, s, budget=8: budgets.append(budget) or None
    day = '2026-09-07'
    _st.save_cached_daily_schedule(day, {
        'true_unassigned': ['a', 'b', 'c'],
        'events': [{'id': x, 'title': x} for x in ('a', 'b', 'c')]}, 'h')
    try:
        agent_tools_v2.negotiate_day(day=day,
                                     acting_member={'id': 'p1', 'role': 'parent'})
    finally:
        negotiation.propose = real
    check(len(budgets) == 3, f"three seeds were seeded, got {budgets}")
    deep = int(_st.get_settings().get('negotiation_deep_budget',
                                      negotiation.DEEP_BUDGET))
    check(sum(budgets) <= deep,
          f"the whole turn must cost one deep budget, got {budgets} vs {deep}")


def scenario_ask_deal_will_not_guess_between_two_days():
    """A title is not an identifier: a weekly practice has a draft deal on two
    evenings often enough, and fanning asks at the wrong Tuesday is worse than
    a question."""
    storage.deals_table.truncate()
    for day in ('2026-09-07', '2026-09-14'):
        storage.add_deal({'date': day, 'seed_event_id': f'soccer-{day}',
                          'seed_title': 'Soccer practice', 'state': 'draft',
                          'parts': []})
    parent = {'id': 'p1', 'role': 'parent'}
    res = agent_tools_v2.ask_deal('Soccer', acting_member=parent)
    check(res.get('status') == 'error', f"it must not pick one, got {res}")
    check('2026-09-07' in res['message'] and '2026-09-14' in res['message'],
          f"and must name both days rather than guessing, got {res['message']}")
    # With the day given it resolves — and asks about that one only.
    asked = []
    from services import negotiation
    real = negotiation.start_asks
    negotiation.start_asks = lambda did, who=None: asked.append(did) or {'status': 'success'}
    try:
        out = agent_tools_v2.ask_deal('Soccer', day='2026-09-14',
                                      acting_member=parent)
    finally:
        negotiation.start_asks = real
    check(out.get('status') == 'success', f"a named day resolves it, got {out}")
    check(len(asked) == 1, f"exactly one deal is asked, got {asked}")
    check(storage.get_deal(asked[0])['date'] == '2026-09-14',
          "and it is the day that was named")


if __name__ == '__main__':
    scenario_both_stacks_can_look()
    scenario_a_fuzzy_day_is_resolved_before_the_lookup()
    scenario_one_chat_turn_cannot_spend_three_deep_budgets()
    scenario_ask_deal_will_not_guess_between_two_days()
    scenario_only_the_new_stack_can_ask()
    scenario_asking_refuses_an_unresolved_caller()
    scenario_asking_refuses_a_child()
    scenario_looking_never_asks()
    print("test_negotiation_agent_tools OK")
