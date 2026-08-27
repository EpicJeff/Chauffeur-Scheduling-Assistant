"""Handle it -> on-demand proposal: the insight asks the live agent stack for
one concrete move. A card with a proposal_id attaches to the insight; no card
is an honest no-move. Nothing executes without the separate approve tap."""
import datetime
from harness import check
from services import storage, mind


CALLS = []


def _fake_agent(result):
    def f(prompt, actor):
        CALLS.append({'prompt': prompt, 'actor': actor})
        return result
    return f


def _reset():
    CALLS.clear()
    storage.mind_insights_table.truncate()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'mind_enabled': True}


PARENT = {'id': 'p1', 'role': 'parent', 'name': 'Jeff'}


def scenario_proposal_attaches():
    _reset()
    iid = storage.add_mind_insight({'slug': 'overlap', 'category': 'logistics-conflict',
                                    'line': 'Tuesday 17:00 overlap: Next Level vs Sea Wolves'})
    mind._agent_request = _fake_agent({
        'message': 'I can move Grandma onto Sea Wolves.',
        'card': {'proposal_id': 'prop9', 'title': 'Assign Grandma to Sea Wolves Tue'}})
    res = mind.propose_fix(iid, PARENT)
    check(res['status'] == 'proposed', f"got {res}")
    check(res['proposal_id'] == 'prop9' and 'Grandma' in res['summary'],
          "endpoint reply carries the proposal")
    row = storage.get_mind_insight_by_slug('overlap')
    check(row['proposal_json'] == {'proposal_id': 'prop9',
                                   'summary': 'Assign Grandma to Sea Wolves Tue'},
          f"proposal stored on the insight, got {row['proposal_json']}")
    check(row['state'] == 'active', "proposing never retires the insight")
    check('overlap' in CALLS[0]['prompt'] or 'Sea Wolves' in CALLS[0]['prompt'],
          "the insight text reaches the agent")
    check(CALLS[0]['actor'] == PARENT, "the tapping member is the acting member")


def scenario_existing_proposal_is_returned_not_regenerated():
    res = mind.propose_fix(storage.get_mind_insight_by_slug('overlap')['id'], PARENT)
    check(res['status'] == 'proposed' and res['proposal_id'] == 'prop9',
          f"second tap returns the stored proposal, got {res}")
    check(len(CALLS) == 1, "no second agent call")


def scenario_no_card_is_an_honest_no_move():
    _reset()
    iid = storage.add_mind_insight({'slug': 'vibe', 'category': 'overload',
                                    'line': 'Rough week building for Ellie'})
    mind._agent_request = _fake_agent({'message': 'Nothing I can schedule fixes this.',
                                       'card': None})
    res = mind.propose_fix(iid, PARENT)
    check(res['status'] == 'no_move', f"got {res}")
    check('Nothing I can schedule' in (res.get('note') or ''),
          "the agent's own words ride back as the note")
    row = storage.get_mind_insight_by_slug('vibe')
    check(not row.get('proposal_json') and row['state'] == 'active',
          "no-move leaves the insight untouched")


def scenario_cap_and_missing_key():
    _reset()
    iid = storage.add_mind_insight({'slug': 'x', 'category': 'c', 'line': 'y'})
    day_key = f"mind_calls:{datetime.date.today().isoformat()}"
    storage.set_app_state(day_key, {'handle': 30})
    mind._agent_request = _fake_agent({'message': 'hi', 'card': None})
    check(mind.propose_fix(iid, PARENT)['status'] == 'capped', "cap = silent skip")
    storage.set_app_state(day_key, {})
    storage.get_settings = lambda: {'mind_enabled': True}
    check(mind.propose_fix(iid, PARENT)['status'] == 'no_key', "no key = no agent run")
    check(not CALLS, "neither path reached the agent")


def scenario_unknown_insight():
    _reset()
    mind._agent_request = _fake_agent({'message': 'hi', 'card': None})
    check(mind.propose_fix('nope', PARENT)['status'] == 'not_found', "unknown id")


if __name__ == '__main__':
    scenario_proposal_attaches()
    scenario_existing_proposal_is_returned_not_regenerated()
    scenario_no_card_is_an_honest_no_move()
    scenario_cap_and_missing_key()
    scenario_unknown_insight()
    print("test_mind_propose OK")
