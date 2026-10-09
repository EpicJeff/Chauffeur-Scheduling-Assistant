"""Every card verb has a tool and every tool's verb renders on the card;
fuzzy resolution by title; write gates resolved at dispatch."""
import datetime
import re

from harness import check  # noqa: F401
from services import storage, situations, agent_tools_v2 as tools, threads

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.threads_table, storage.missions_table,
              storage.mission_steps_table, storage.assist_contacts_table, storage.chat_channels_table,
              storage.chat_messages_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary']}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
SIX = ('list_situations', 'explain_situation', 'act_on_situation', 'start_ask', 'mark_ask_sent', 'answer_ask')


def scenario_parity_both_ways():
    """Walk the card's verbs and the tools' verbs; they must be the same set."""
    src = open('static/situations.js', encoding='utf-8').read()
    block = re.search(r"VERB_LABELS\s*=\s*\{([^}]*)\}", src).group(1)
    card_verbs = set(re.findall(r"'([a-z_]+)':", block))
    check(card_verbs == situations.VERBS, f"the card knows every verb and nothing else: {card_verbs ^ situations.VERBS}")
    decl = {t['name'] for t in tools.get_available_tools()}
    check(set(SIX) <= decl, f"all six tools declared, missing {set(SIX) - decl}")
    verb_param = next(t for t in tools.get_available_tools() if t['name'] == 'act_on_situation')['parameters']['properties']['verb']
    check(set(verb_param.get('enum') or []) == situations.VERBS - {'ask'},
          "act_on_situation's verb enum is the closed set minus ask (start_ask is ask)")
    for name in SIX:
        check(name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS, f"{name} is in the registry")


def scenario_fuzzy_resolve_and_ambiguity():
    _reset()
    t1 = threads.create('Deck permit with the county', owner_member_id='mom', created_by='mom')
    t2 = threads.create('Deck furniture quote', owner_member_id='mom', created_by='mom')
    res = tools.explain_situation('county', acting_member=MOM)
    check(res['status'] == 'success' and res['situation']['id'] == t1, f"one match by fragment: {res}")
    res = tools.explain_situation('deck', acting_member=MOM)
    check(res['status'] == 'error' and 'county' in res['message'] and 'furniture' in res['message'],
          f"ambiguous: names the candidates: {res}")
    res = tools.explain_situation('pool', acting_member=MOM)
    check(res['status'] == 'error', "no match is an honest error")


def scenario_act_and_ask_through_tools():
    _reset()
    tid = threads.create('Deck permit', owner_member_id='mom', next_action='call', created_by='mom')
    res = tools.act_on_situation('Deck permit', 'advance', text='email the inspector',
                                 next_action_at='2026-10-20', acting_member=MOM)
    check(res['status'] == 'success' and storage.get_thread(tid)['next_action'] == 'email the inspector', f"advance via tool: {res}")
    res = tools.act_on_situation('Deck permit', 'close', acting_member={'id': 'kid', 'role': 'child'})
    check(res['status'] in ('error', 'refused'), "a child is refused at dispatch")
    res = tools.start_ask('Deck permit', 'the inspector', 'come Friday morning', 'email', acting_member=MOM)
    check(res['status'] == 'success' and res['draft'] and res['ask_id'], f"an ask from chat returns a draft: {res}")
    check(tools.mark_ask_sent(res['ask_id'], acting_member=MOM)['status'] == 'success', "sent it")
    res2 = tools.answer_ask(res['ask_id'], 'yes', acting_member=MOM)
    check(res2['status'] == 'success' and res2.get('outcome') == 'applied', f"a free ask's yes is recorded as applied (nothing to unlock): {res2}")
    listed = tools.list_situations(kinds='thread', acting_member=MOM)
    check(listed['status'] == 'success' and 'Deck permit' in listed['message'] and 'inspector' in listed['message'],
          f"the list reads the ledger: {listed['message']}")


SCENARIOS = [scenario_parity_both_ways, scenario_fuzzy_resolve_and_ambiguity, scenario_act_and_ask_through_tools]

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
