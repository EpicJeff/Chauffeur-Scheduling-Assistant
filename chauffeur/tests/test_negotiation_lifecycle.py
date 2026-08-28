"""What happens to a deal that nobody finishes.

The joins between the negotiation pieces, which each passed their own gate:
an unanswered ask has to reach the DEAL, a dead deal has to stop asking, two
simultaneous yeses must apply once, a refusal has to survive into the next
search, and a hopeless seed must stop being re-searched every half hour.

Run from chauffeur/:  python tests/test_negotiation_lifecycle.py
"""
import datetime
import time

from harness import check
from models.schemas import Driver, Event
from services import negotiation, requests as reqs, solve_pack, storage, watchers

TODAY = datetime.date(2026, 9, 7).isoformat()
MONDAY = datetime.datetime(2026, 9, 7, 17, 0)


def _reset():
    storage.deals_table.truncate()
    storage.requests_table.truncate()
    storage.shift_refusals_table.truncate()
    storage.app_state_table.truncate()


def _asking_deal(seed='seed-ev', n=2, lever='skip_optional'):
    """A deal with its asks already out — one real `services.requests` row per
    part, exactly as `start_asks` creates them, because the whole point of
    these scenarios is what the request rail and the deal do to each other."""
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent'})
    parts, events = [], []
    for i in range(n):
        parts.append({'id': f'lp{i}', 'member_id': ['mom', 'dad'][i % 2],
                      'lever': lever,
                      'payload': {'event_id': f'le{i}', 'title': 'Extra practice'},
                      'ask_text': 'Skip it?', 'state': 'open', 'request_id': None})
        events.append({'id': f'le{i}', 'title': 'Extra practice',
                       'start': f'{TODAY}T16:00:00-05:00',
                       'calendar_ids': ['cal1'], 'source_event_ids': [f'cal1::g{i}']})
    storage.set_cached_schedule({'events': events})
    did = storage.add_deal({'date': TODAY, 'seed_event_id': seed,
                            'seed_title': 'Soccer', 'line': 'a deal',
                            'parts': parts, 'state': 'draft'})
    negotiation.start_asks(did, 'mom')
    return did


def scenario_an_unanswered_ask_expires_the_whole_deal():
    """`requests.sweep` expires the row and DMs both parties, but before this
    the DEAL heard nothing: parts stayed open, the deal stayed `asking`
    forever, and every reader downstream took that for a live negotiation."""
    _reset()
    did = _asking_deal()
    check(storage.get_deal(did)['state'] == 'asking', "the asks went out")
    reqs.sweep(now_ts=time.time() + (reqs.DEFAULT_TTL_HOURS + 1) * 3600)
    row = storage.get_deal(did)
    check(row['state'] == 'expired',
          f"a deal nobody answered is expired, not stranded, got {row['state']}")


def scenario_a_dead_deals_other_asks_are_closed_with_it():
    """A two-part deal, one decline. The other person's ask is moot the
    instant the deal dies — leaving it to grind out its own 20h TTL means two
    people get DMed about a deal that ended yesterday."""
    _reset()
    did = _asking_deal()
    parts = storage.get_deal(did)['parts']
    negotiation.decline_part('lp0', 'mom', reason='in a meeting')
    check(storage.get_deal(did)['state'] == 'dead', "one no ends it")
    other = storage.get_request(parts[1]['request_id'])
    check(other['status'] != 'open',
          f"the other half's ask is closed with it, got {other['status']}")


def scenario_a_killed_deals_asks_are_closed_too():
    _reset()
    did = _asking_deal()
    parts = storage.get_deal(did)['parts']
    negotiation.kill(did, 'mom', reason='not worth it')
    for p in parts:
        req = storage.get_request(p['request_id'])
        check(req['status'] != 'open',
              f"a dropped deal stops asking, got {req['status']}")


def scenario_an_expired_deal_hands_the_event_back_to_the_ladder():
    """The failure this whole thread of fixes is about. A stranded `asking`
    deal made `watchers._deal_line` print 'N of M said yes, waiting on the
    rest' with nothing to tap, forever, and the coverage ladder — somebody is
    free / an outside hand covered this / here is why nobody can — never came
    back for that event."""
    _reset()
    did = _asking_deal(seed='ladder-ev')
    line, action = watchers._deal_line('ladder-ev')
    check(line and action is None,
          f"while it is asking, it holds the line with nothing to tap: {line}")
    reqs.sweep(now_ts=time.time() + (reqs.DEFAULT_TTL_HOURS + 1) * 3600)
    check(storage.get_deal(did)['state'] == 'expired', "the deal expired")
    check(watchers._deal_line('ladder-ev') == (None, None),
          "and the event is the ladder's again")


def scenario_propose_does_not_reuse_an_expired_deal():
    """`propose` returns an OPEN deal rather than re-solving. An expired one
    is not open, and handing it back is how the seed stopped being searched."""
    _reset()
    did = _asking_deal(seed='reuse-ev')
    reqs.sweep(now_ts=time.time() + (reqs.DEFAULT_TTL_HOURS + 1) * 3600)
    check(storage.get_deal(did)['state'] == 'expired', "expired")
    # No pack for that date, so a real search returns None -- which is the
    # point: it SEARCHED rather than handing back the expired row.
    check(negotiation.propose(TODAY, 'reuse-ev') is None,
          "an expired deal must not be re-served as the answer")


def scenario_a_deal_applies_exactly_once():
    """The two last yeses can land in the same second (FastAPI runs sync
    handlers in a threadpool). Everything between 'all parts accepted' and
    `state='applied'` — a Google Calendar round trip included — is a window
    both could walk through, applying the deal twice: an event shifted 15
    minutes twice is 30 minutes from where anybody agreed.

    Simulated deterministically rather than with threads: the second caller is
    let in at exactly the moment the first has seen every part accepted and
    has not yet claimed. Without the compare-and-set both apply.
    """
    _reset()
    did = _asking_deal(seed='once-ev')
    applied = []
    real_apply = negotiation._apply_part
    real_claim = storage.claim_deal
    reentered = []

    def claim_once(deal_id, expected, new):
        # The instant before the first caller claims, a second caller arrives
        # having seen the same "everybody said yes".
        if not reentered:
            reentered.append(1)
            negotiation.accept_part('lp1', 'dad')
        return real_claim(deal_id, expected, new)

    negotiation._apply_part = lambda part, deal: applied.append(part['id'])
    storage.claim_deal = claim_once
    try:
        storage.update_deal_part('lp0', {'state': 'accepted'})
        negotiation.accept_part('lp1', 'dad')
    finally:
        negotiation._apply_part = real_apply
        storage.claim_deal = real_claim
    check(reentered, "the scenario must actually have re-entered, or it proves nothing")
    check(sorted(applied) == ['lp0', 'lp1'],
          f"each part applies exactly once, got {applied}")
    check(storage.get_deal(did)['state'] == 'applied', "and the deal says so")


def scenario_a_refused_part_is_excluded_from_the_next_search():
    """Design rule 5: one decline kills the deal and the RUNNER-UP is offered
    — the next candidate that does not contain the refused part. Only
    `shift_event` records a refusal of its own, so without this the other
    three levers re-propose the identical deal on the next sweep and re-ask
    the person who just said no."""
    _reset()
    did = _asking_deal(seed='runner-ev')
    part = storage.get_deal(did)['parts'][0]
    negotiation.decline_part(part['id'], 'mom', reason='no')
    row = storage.get_deal(did)
    check(negotiation.part_key(part) in (row.get('refused_parts') or []),
          f"the deal records what was refused, got {row.get('refused_parts')}")
    check(negotiation._refused_part_keys('runner-ev') == {negotiation.part_key(part)},
          "and the next search for this seed excludes exactly that")


def scenario_the_exclusion_really_reaches_the_search():
    """Not just the helper: `propose` has to hand the exclusion to `search`,
    and `search` has to drop a candidate carrying it."""
    _reset()
    seen = {}
    real = negotiation.search
    negotiation.search = lambda pack, seed, budget=8, exclude=None: (
        seen.update(exclude=exclude) or [])
    storage.save_solve_pack(TODAY, solve_pack.build(
        TODAY, events=[], drivers=[], rules=[], priority_rules=[], overrides=[],
        passengers=[], cars=[], driver_events={}, trip_metadata=[],
        driver_passenger_map={}, previous_assignments={}, load_balancing=False,
        load_balancing_metric='occupied_time', protected_rule_index={}))
    did = _asking_deal(seed='wired-ev')
    part = storage.get_deal(did)['parts'][0]
    try:
        negotiation.decline_part(part['id'], 'mom', reason='no')
        negotiation.propose(TODAY, 'wired-ev')
    finally:
        negotiation.search = real
    check(seen.get('exclude') == {negotiation.part_key(part)},
          f"propose must pass the refusal down to the search, got {seen}")


def scenario_a_hopeless_seed_is_not_re_searched_until_the_pack_changes():
    """The sweep runs every 30 minutes for a 14-day window, and a genuinely
    broken day is the COMMON case for an uncovered event. Without a memo, one
    such event costs a baseline plus the sweep budget, 48 times a day, forever,
    always reaching the same answer."""
    _reset()
    pack = solve_pack.build(
        TODAY, events=[], drivers=[], rules=[], priority_rules=[], overrides=[],
        passengers=[], cars=[], driver_events={}, trip_metadata=[],
        driver_passenger_map={}, previous_assignments={}, load_balancing=False,
        load_balancing_metric='occupied_time', protected_rule_index={})
    storage.save_solve_pack(TODAY, pack)
    searches = []
    real = negotiation.search
    negotiation.search = lambda *a, **kw: (searches.append(1), [])[1]
    try:
        negotiation.propose(TODAY, 'hopeless-ev')
        negotiation.propose(TODAY, 'hopeless-ev')
        negotiation.propose(TODAY, 'hopeless-ev')
        check(len(searches) == 1,
              f"one search, then the memo answers, got {len(searches)}")
        # A refresh rewrites the pack; that is the only thing that can change
        # the answer, so it is the only thing that clears the memo.
        pack['written_at'] = pack['written_at'] + 1
        storage.save_solve_pack(TODAY, pack)
        negotiation.propose(TODAY, 'hopeless-ev')
        check(len(searches) == 2,
              f"a rewritten pack is a new question, got {len(searches)}")
    finally:
        negotiation.search = real


def scenario_settled_deals_are_pruned_and_open_ones_are_not():
    _reset()
    old = time.time() - 60 * 86400
    dead = storage.add_deal({'date': TODAY, 'seed_event_id': 'x', 'state': 'dead',
                             'created_at': old})
    still_asking = storage.add_deal({'date': TODAY, 'seed_event_id': 'y',
                                     'state': 'asking', 'created_at': old})
    storage.prune_deals(time.time() - negotiation.MEMORY_DAYS * 86400)
    check(storage.get_deal(dead) is None, "a settled deal is answering nobody")
    check(storage.get_deal(still_asking) is not None,
          "but somebody may still be about to answer an open one")


def scenario_a_shift_is_refused_when_the_event_moved_after_the_ask():
    """The ask quoted a clock time computed from where the event was. If it
    has moved since, that sentence is no longer true about anything, and
    adding `delta_mins` to the new start lands somewhere nobody agreed to."""
    _reset()
    storage.set_cached_schedule({'events': [{
        'id': 'cal1::moved', 'calendar_ids': ['cal1'],
        'source_event_ids': ['cal1::moved'],
        'start': f'{TODAY}T17:00:00-05:00',
        'end': f'{TODAY}T18:00:00-05:00'}]})
    part = {'id': 'pm', 'member_id': 'mom', 'lever': 'shift_event',
            'payload': {'event_id': 'cal1::moved', 'delta_mins': 15,
                        'from_start': f'{TODAY}T16:30:00-05:00',
                        'target_start': f'{TODAY}T16:45:00-05:00',
                        'target_end': f'{TODAY}T17:45:00-05:00'}}
    reason = negotiation._check_part(part)
    check('moved' in reason,
          f"a deal about a time that no longer exists must not apply, got {reason!r}")
    part['payload']['from_start'] = f'{TODAY}T17:00:00-05:00'
    check(negotiation._check_part(part) == '',
          "and an event still where the ask said it was is fine")
    body = negotiation._shift_body(
        {'start': f'{TODAY}T17:00:00-05:00', 'end': f'{TODAY}T18:00:00-05:00'},
        part['payload'], 'America/Chicago')
    check(body['start']['dateTime'].startswith(f'{TODAY}T16:45:00'),
          f"the write uses the time that was AGREED, not start+delta, got {body}")
    storage.set_cached_schedule({})


if __name__ == '__main__':
    scenario_an_unanswered_ask_expires_the_whole_deal()
    scenario_a_dead_deals_other_asks_are_closed_with_it()
    scenario_a_killed_deals_asks_are_closed_too()
    scenario_an_expired_deal_hands_the_event_back_to_the_ladder()
    scenario_propose_does_not_reuse_an_expired_deal()
    scenario_a_deal_applies_exactly_once()
    scenario_a_refused_part_is_excluded_from_the_next_search()
    scenario_the_exclusion_really_reaches_the_search()
    scenario_a_hopeless_seed_is_not_re_searched_until_the_pack_changes()
    scenario_settled_deals_are_pruned_and_open_ones_are_not()
    scenario_a_shift_is_refused_when_the_event_moved_after_the_ask()
    print("test_negotiation_lifecycle OK")
