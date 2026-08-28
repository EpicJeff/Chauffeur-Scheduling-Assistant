"""The Mind brings a deal, and the ladder is still there when it cannot."""
import datetime

from harness import check
from services import chat_actions, negotiation, storage, watchers


def scenario_a_deal_replaces_the_siren():
    """When a deal exists, the finding says what would fix the day."""
    did = storage.add_deal({
        'date': datetime.date.today().isoformat(), 'seed_event_id': 'ev1',
        'seed_title': 'Soccer', 'line': '🤝 Soccer works if the piano moves',
        'parts': [{'id': 'p0', 'member_id': 'm1', 'lever': 'shift_event',
                   'payload': {'event_id': 'e2', 'series_key': 's2'},
                   'ask_text': 'Move it?', 'state': 'open', 'request_id': None}],
        'state': 'draft'})
    line, action = watchers._deal_line('ev1')
    check(line and 'works if' in line, f"the deal speaks, got {line}")
    check(action and action['action_type'] == 'ask_deal',
          f"and offers the ask, got {action}")
    check(action['payload']['deal_id'] == did, "pointing at this deal")


def scenario_no_deal_means_no_line():
    check(watchers._deal_line('nothing-here') == (None, None),
          "no deal, no claim — the coverage ladder answers instead")


def scenario_ask_deal_is_a_proposable_action():
    check('ask_deal' in chat_actions.ADMIN_ACTIONS,
          "the tap has to be able to reach something")
    check(chat_actions.ACTION_LABELS.get('ask_deal'),
          "and it needs a label a person can read")


def scenario_asking_needs_a_real_deal():
    res = chat_actions._execute('ask_deal', {'deal_id': 'nope'})
    check(res.get('status') == 'error', f"a missing deal is an error, got {res}")


if __name__ == '__main__':
    scenario_a_deal_replaces_the_siren()
    scenario_no_deal_means_no_line()
    scenario_ask_deal_is_a_proposable_action()
    scenario_asking_needs_a_real_deal()
    print("test_negotiation_watcher OK")
