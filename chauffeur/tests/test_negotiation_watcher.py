"""The Mind brings a deal, and the ladder is still there when it cannot."""
import datetime

from harness import check
from services import chat_actions, negotiation, storage, watchers


def _mk_uncovered(ev_id, now):
    """A cached schedule holding exactly one uncovered, coverable event —
    real enough to drive `_unassigned_findings` end to end, not just
    `_deal_line` in isolation."""
    start = now + datetime.timedelta(hours=2)
    ev = {'id': ev_id, 'title': 'Soccer practice',
          'start': start.isoformat(), 'end': (start + datetime.timedelta(hours=1)).isoformat()}
    storage.set_cached_schedule({'events': [ev], 'unassigned': [ev_id],
                                 'assist_assignments': {}})
    return ev, start


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


def scenario_the_sweep_actually_wires_the_deal_in():
    """Not just `_deal_line` in isolation: the function that BUILDS the
    uncovered-event findings has to find the deal, skip the ladder, and hand
    back the deal's line and action -- the wiring `_deal_line` alone cannot
    prove."""
    now = datetime.datetime.now()
    ev_id = 'ev-wired-draft'
    ev, start = _mk_uncovered(ev_id, now)
    did = storage.add_deal({
        'date': start.date().isoformat(), 'seed_event_id': ev_id,
        'seed_title': 'Soccer practice', 'line': '🤝 Soccer practice works if the piano moves',
        'parts': [{'id': 'p-wired', 'member_id': 'm1', 'lever': 'shift_event',
                   'payload': {'event_id': 'e2', 'series_key': 's2'},
                   'ask_text': 'Move it?', 'state': 'open', 'request_id': None}],
        'state': 'draft'})
    found = [f for f in watchers._unassigned_findings(now) if f.subject_id == ev_id]
    check(len(found) == 1, f"exactly one finding for this event, got {found}")
    f = found[0]
    check('works if' in f.line, f"it carries the deal's own line, got {f.line!r}")
    check('No driver yet' not in f.line, f"not the siren, got {f.line!r}")
    check(f.action and f.action['action_type'] == 'ask_deal'
          and f.action['payload']['deal_id'] == did,
          f"and the one tap points at this deal, got {f.action}")
    check(f.severity == 'approve', f"a draft deal is a real tap, got {f.severity}")


def scenario_a_negotiation_failure_does_not_silence_the_warning():
    """Never fatal, never silent: if `negotiation.propose` blows up mid-sweep,
    the uncovered event still has to surface -- through the ladder, exactly as
    it would have if negotiation did not exist."""
    now = datetime.datetime.now()
    ev_id = 'ev-wired-raises'
    _mk_uncovered(ev_id, now)
    original_propose = negotiation.propose

    def _boom(*a, **kw):
        raise RuntimeError('the solver caught fire')

    negotiation.propose = _boom
    try:
        found = [f for f in watchers._unassigned_findings(now) if f.subject_id == ev_id]
    finally:
        negotiation.propose = original_propose
    check(len(found) == 1, f"the warning survives the failure, got {found}")
    check(found[0].kind == 'unassigned', f"still an unassigned finding, got {found[0]}")
    check('🚨' in found[0].line, f"the ladder's own voice, got {found[0].line!r}")


def scenario_asking_state_offers_nothing_to_tap():
    """Pins Finding 1: once the asks are out there is no button left to press,
    so the finding must not claim there is one. `list_open_findings`
    (services/agent_tools_v2.py) groups purely by severity -- 'approve' means
    'One tap each' whether or not an action rides along -- so severity is the
    only signal that can carry 'nothing to tap' through that surface."""
    now = datetime.datetime.now()
    ev_id = 'ev-wired-asking'
    ev, start = _mk_uncovered(ev_id, now)
    storage.add_deal({
        'date': start.date().isoformat(), 'seed_event_id': ev_id,
        'seed_title': 'Soccer practice', 'line': '🤝 Soccer practice works if the piano moves',
        'parts': [{'id': 'p-asking-1', 'member_id': 'm1', 'lever': 'shift_event',
                   'payload': {'event_id': 'e2', 'series_key': 's2'},
                   'ask_text': 'Move it?', 'state': 'accepted', 'request_id': 'r1'},
                  {'id': 'p-asking-2', 'member_id': 'm2', 'lever': 'shift_event',
                   'payload': {'event_id': 'e3', 'series_key': 's3'},
                   'ask_text': 'Move that too?', 'state': 'open', 'request_id': 'r2'}],
        'state': 'asking'})
    found = [f for f in watchers._unassigned_findings(now) if f.subject_id == ev_id]
    check(len(found) == 1, f"exactly one finding for this event, got {found}")
    f = found[0]
    check('said yes' in f.line, f"reports who has answered, got {f.line!r}")
    check(f.severity == 'fyi', f"nothing to tap, so 'fyi' not 'approve', got {f.severity}")
    check(f.action is None, f"and no action rides along, got {f.action}")


if __name__ == '__main__':
    scenario_a_deal_replaces_the_siren()
    scenario_no_deal_means_no_line()
    scenario_ask_deal_is_a_proposable_action()
    scenario_asking_needs_a_real_deal()
    scenario_the_sweep_actually_wires_the_deal_in()
    scenario_a_negotiation_failure_does_not_silence_the_warning()
    scenario_asking_state_offers_nothing_to_tap()
    print("test_negotiation_watcher OK")
