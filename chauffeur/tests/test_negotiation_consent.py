"""Nothing happens to anybody's day until everybody has said yes."""
import datetime

from harness import check
from services import negotiation, storage

TODAY = datetime.date(2026, 9, 7).isoformat()


def _reset():
    # Every scenario below builds its own deal with the same static part ids
    # ('p0', 'p1', 'px') for readability -- fine as long as no earlier
    # scenario's deal is still sitting in the table, since `get_deal_by_part`
    # returns the FIRST deal it finds with a matching part id, not the
    # newest. Without this, scenario two's "accept p0" can silently land on
    # scenario one's leftover deal instead of its own.
    storage.deals_table.truncate()
    storage.shift_refusals_table.truncate()
    storage.protected_exceptions_table.truncate()
    storage.protected_commitments_table.truncate()


def _deal(parts_states=('open', 'open')):
    # Real events in the cache, not just references in the deal's payload --
    # `accept_part` pre-flights every part (checks the target still exists)
    # before applying any of them, and a skip_optional part whose event
    # cannot be found would fail pre-flight before the scenario below ever
    # reaches its monkeypatched `_apply_part`.
    parts, events = [], []
    for i, st in enumerate(parts_states):
        parts.append({'id': f'p{i}', 'member_id': f'm{i}',
                      'lever': 'skip_optional',
                      'payload': {'event_id': f'e{i}', 'title': 'Extra practice'},
                      'ask_text': 'Skip it?', 'state': st, 'request_id': None})
        events.append({'id': f'e{i}', 'title': 'Extra practice',
                       'start': f'{TODAY}T16:00:00-05:00',
                       'calendar_ids': ['cal1'], 'source_event_ids': [f'cal1::g{i}']})
    storage.set_cached_schedule({'events': events})
    return storage.add_deal({'date': TODAY, 'seed_event_id': 'seed',
                             'seed_title': 'Soccer', 'line': 'a deal',
                             'parts': parts, 'state': 'asking'})


def scenario_one_yes_applies_nothing():
    _reset()
    applied = []
    real = negotiation._apply_part
    negotiation._apply_part = lambda part, deal: applied.append(part['id'])
    try:
        did = _deal()
        negotiation.accept_part('p0', 'm0')
        check(applied == [],
              f"a partly agreed deal changes nothing, got {applied}")
        row = storage.get_deal(did)
        check(row['state'] == 'asking', f"and stays open, got {row['state']}")
    finally:
        negotiation._apply_part = real


def scenario_the_last_yes_applies_the_whole_deal():
    _reset()
    applied = []
    real = negotiation._apply_part
    negotiation._apply_part = lambda part, deal: applied.append(part['id'])
    try:
        did = _deal()
        negotiation.accept_part('p0', 'm0')
        negotiation.accept_part('p1', 'm1')
        check(sorted(applied) == ['p0', 'p1'],
              f"every part is applied together, got {applied}")
        check(storage.get_deal(did)['state'] == 'applied',
              "and the deal says so")
    finally:
        negotiation._apply_part = real


def scenario_one_no_kills_the_deal():
    _reset()
    did = _deal()
    negotiation.decline_part('p0', 'm0', reason='in a meeting')
    row = storage.get_deal(did)
    check(row['state'] == 'dead', f"one decline ends it, got {row['state']}")
    check('meeting' in (row.get('dead_reason') or ''),
          f"and the reason travels with it, got {row.get('dead_reason')}")


def scenario_a_refused_shift_is_remembered_against_the_series():
    _reset()
    did = storage.add_deal({
        'date': TODAY, 'seed_event_id': 'seed', 'seed_title': 'Soccer',
        'parts': [{'id': 'px', 'member_id': 'm0', 'lever': 'shift_event',
                   'payload': {'event_id': 'e9', 'series_key': 'series-9',
                               'title': 'Piano', 'delta_mins': 15},
                   'ask_text': 'Move it?', 'state': 'open', 'request_id': None}],
        'state': 'asking'})
    negotiation.decline_part('px', 'm0', reason="the lesson can't move")
    keys = {r['series_key'] for r in storage.get_shift_refusals()}
    check('series-9' in keys, f"the app learns what cannot move, got {keys}")
    check(storage.get_deal(did)['state'] == 'dead', "and the deal is over")


def scenario_a_person_can_kill_a_deal_by_hand():
    _reset()
    did = _deal()
    negotiation.kill(did, 'm0', reason='not worth it')
    check(storage.get_deal(did)['state'] == 'dead', "a deal can be dropped")


def scenario_shift_writes_the_real_calendar_id_with_a_zone():
    """The only real Google Calendar write in the arc. `source_event_ids`
    entries are 'calendar_id::google_event_id' (services/calendar.py's
    fetch), not a bare Google id, and the datetime it writes must carry an
    actual zone or Google rejects the patch outright."""
    from services import calendar as gcal
    calls = []
    real_patch, real_tz = gcal.patch_event, gcal.get_calendar_timezone
    gcal.patch_event = lambda cal_id, event_id, body: (
        calls.append((cal_id, event_id, body)) or True)
    gcal.get_calendar_timezone = lambda cal_id: 'America/Chicago'
    storage.set_cached_schedule({'events': [{
        'id': 'cal1::gid1', 'calendar_ids': ['cal1'],
        'source_event_ids': ['cal1::gid1'],
        'start': '2026-09-07T16:00:00-05:00',
        'end': '2026-09-07T16:30:00-05:00'}]})
    try:
        part = {'id': 'px', 'member_id': 'm0', 'lever': 'shift_event',
                'payload': {'event_id': 'cal1::gid1', 'series_key': 'series-x',
                            'title': 'Piano', 'delta_mins': 15}}
        negotiation._apply_part(part, {'date': TODAY})
        check(len(calls) == 1, f"exactly one calendar write, got {calls}")
        cal_id, event_id, body = calls[0]
        check(cal_id == 'cal1', f"the real calendar id, got {cal_id}")
        check(event_id == 'gid1',
              f"the bare google id, not the cal_id::id composite, got {event_id}")
        check(body['start']['dateTime'].startswith('2026-09-07T16:15:00'),
              f"shifted by the delta, got {body}")
        check(body['start'].get('timeZone') == 'America/Chicago',
              f"stamped with the calendar's own zone or Google rejects it, got {body}")
    finally:
        gcal.patch_event, gcal.get_calendar_timezone = real_patch, real_tz
        storage.set_cached_schedule({})


def scenario_a_failed_part_does_not_hide_what_already_happened():
    """A two-part deal: the local part (skip_optional) applies first and for
    real; the calendar part (shift_event) applies last and is made to fail,
    simulating the one kind of failure pre-flight cannot see coming -- the
    external write itself refusing for a reason nothing here can predict.

    The guarantee this implementation actually provides is RECORDING, not
    rollback: there is no undo for a calendar write already sent, so a local
    write that happened before it is not undone either -- it is left as it
    is, and the deal's own data says so. This does NOT claim atomicity; it
    claims honesty about what already happened.
    """
    _reset()
    from services import calendar as gcal, optional_events as opt
    real_patch, real_tz = gcal.patch_event, gcal.get_calendar_timezone
    gcal.patch_event = lambda cal_id, event_id, body: False
    gcal.get_calendar_timezone = lambda cal_id: 'America/Chicago'
    skip_ev = {'id': 'eA', 'title': 'Extra practice',
               'start': f'{TODAY}T15:00:00-05:00',
               'calendar_ids': ['cal1'], 'source_event_ids': ['cal1::gA']}
    shift_ev = {'id': 'eB', 'title': 'Piano',
                'start': f'{TODAY}T16:00:00-05:00',
                'end': f'{TODAY}T16:30:00-05:00',
                'calendar_ids': ['cal1'], 'source_event_ids': ['cal1::gB']}
    storage.set_cached_schedule({'events': [skip_ev, shift_ev]})
    did = storage.add_deal({
        'date': TODAY, 'seed_event_id': 'seed', 'seed_title': 'Soccer',
        'parts': [
            {'id': 'pA', 'member_id': 'm0', 'lever': 'skip_optional',
             'payload': {'event_id': 'eA', 'title': 'Extra practice'},
             'ask_text': 'Skip it?', 'state': 'open', 'request_id': None},
            {'id': 'pB', 'member_id': 'm1', 'lever': 'shift_event',
             'payload': {'event_id': 'eB', 'series_key': 'series-b',
                         'title': 'Piano', 'delta_mins': 15},
             'ask_text': 'Move it?', 'state': 'open', 'request_id': None}],
        'state': 'asking'})
    try:
        negotiation.accept_part('pA', 'm0')
        res = negotiation.accept_part('pB', 'm1')
        check(res['status'] == 'error', f"the calendar refusing ends the deal, got {res}")
        check('already happened' in res['message'],
              f"the failure must not claim nothing changed when something did, got {res['message']}")
        row = storage.get_deal(did)
        check(row['state'] == 'dead', f"the deal still dies loudly, got {row['state']}")
        check('skip_optional' in (row.get('dead_reason') or ''),
              f"the record names what already went through, got {row.get('dead_reason')}")
        parts_by_id = {p['id']: p for p in row['parts']}
        check(parts_by_id['pA'].get('applied') is True,
              f"the completed part is stamped as having happened, got {parts_by_id['pA']}")
        check(not parts_by_id['pB'].get('applied'),
              f"the failed part is not, got {parts_by_id['pB']}")
        decision = opt.decision_for(skip_ev)
        check(decision == 'skip',
              f"and it really did happen -- there is no rollback for the local "
              f"write either, got {decision}")
    finally:
        gcal.patch_event, gcal.get_calendar_timezone = real_patch, real_tz
        storage.set_cached_schedule({})


def scenario_a_partial_calendar_body_is_refused():
    """`shift_event` requires BOTH endpoints before it will write anything --
    a body with only `start` would move a real event's start and silently
    garble its duration, which is worse than refusing outright."""
    from services import calendar as gcal
    calls = []
    real_patch, real_tz = gcal.patch_event, gcal.get_calendar_timezone
    gcal.patch_event = lambda cal_id, event_id, body: calls.append(body) or True
    # Also stubbed even though a fully-refused body should never reach this
    # call: `_apply_part`'s real network call must not run just because a
    # test forgot to stub it (this test caught itself doing exactly that --
    # see the fix report).
    gcal.get_calendar_timezone = lambda cal_id: 'America/Chicago'
    storage.set_cached_schedule({'events': [{
        'id': 'cal1::gid2', 'calendar_ids': ['cal1'],
        'source_event_ids': ['cal1::gid2'],
        'start': f'{TODAY}T16:00:00-05:00', 'end': 'not-a-time'}]})
    try:
        part = {'id': 'py', 'member_id': 'm0', 'lever': 'shift_event',
                'payload': {'event_id': 'cal1::gid2', 'delta_mins': 15}}
        check(negotiation._check_part(part) != '',
              "pre-flight refuses a part whose event has only one readable endpoint")
        raised = False
        try:
            negotiation._apply_part(part, {'date': TODAY})
        except ValueError:
            raised = True
        check(raised, "and applying it directly raises rather than writing half a body")
        check(calls == [], f"the calendar is never called with a partial body, got {calls}")
    finally:
        gcal.patch_event, gcal.get_calendar_timezone = real_patch, real_tz
        storage.set_cached_schedule({})


def scenario_a_lift_is_dropped_only_for_its_own_date():
    _reset()
    rules = ['r0', 'r1', 'r2']
    index = {'c0': 0, 'c1': 1, 'c2': 2}
    storage.add_protected_exception('c1', TODAY)

    day_rules, day_index = negotiation.day_rules_for(TODAY, rules, index)
    check(day_rules == ['r0', 'r2'], f"the lifted rule is dropped, got {day_rules}")
    check('c1' not in day_index,
          f"and its commitment has no rule left to point at, got {day_index}")

    other_day = datetime.date(2026, 9, 8).isoformat()
    other_rules, other_index = negotiation.day_rules_for(other_day, rules, index)
    check(other_rules == rules,
          f"a different date keeps the standing rule, got {other_rules}")
    check(other_index == index, f"and its index untouched, got {other_index}")


def scenario_the_index_still_points_at_the_right_rule_after_a_lift():
    _reset()
    rules = ['keep-c0', 'drop-c1', 'keep-c2', 'keep-c3']
    index = {'c0': 0, 'c1': 1, 'c2': 2, 'c3': 3}
    storage.add_protected_exception('c1', TODAY)

    day_rules, day_index = negotiation.day_rules_for(TODAY, rules, index)
    for cid, original in (('c0', 'keep-c0'), ('c2', 'keep-c2'), ('c3', 'keep-c3')):
        check(day_rules[day_index[cid]] == original,
              f"{cid}'s index finds its OWN rule in the filtered list, "
              f"got rules={day_rules} index={day_index}")
    check('c1' not in day_index, "the lifted commitment has no rule left")


def scenario_accepting_a_lift_writes_an_exception_not_a_deletion():
    _reset()
    from models.schemas import ProtectedCommitment
    commitment = ProtectedCommitment(member_id='m0', title='Thursday run',
                                     days_of_week=[3]).model_dump()
    storage.add_protected_commitment(commitment)
    did = storage.add_deal({
        'date': TODAY, 'seed_event_id': 'seed', 'seed_title': 'Soccer',
        'parts': [{'id': 'pl', 'member_id': 'm0', 'lever': 'lift_protected',
                   'payload': {'commitment_id': commitment['id'],
                               'title': 'Thursday run'},
                   'ask_text': 'Give up your run this once?',
                   'state': 'open', 'request_id': None}],
        'state': 'asking'})

    res = negotiation.accept_part('pl', 'm0')
    check(res.get('applied') is True,
          f"a single-part deal applies on its own yes, got {res}")
    check(storage.get_deal(did)['state'] == 'applied', "the deal says so")

    exceptions = storage.get_protected_exceptions(commitment['id'])
    check(any(x['date'] == TODAY for x in exceptions),
          f"one evening is given up, got {exceptions}")
    still_there = storage.get_protected_commitments()
    check(any(c['id'] == commitment['id'] and c['title'] == 'Thursday run'
              for c in still_there),
          f"the commitment itself is never touched, got {still_there}")


if __name__ == '__main__':
    scenario_one_yes_applies_nothing()
    scenario_the_last_yes_applies_the_whole_deal()
    scenario_one_no_kills_the_deal()
    scenario_a_refused_shift_is_remembered_against_the_series()
    scenario_a_person_can_kill_a_deal_by_hand()
    scenario_shift_writes_the_real_calendar_id_with_a_zone()
    scenario_a_failed_part_does_not_hide_what_already_happened()
    scenario_a_partial_calendar_body_is_refused()
    scenario_a_lift_is_dropped_only_for_its_own_date()
    scenario_the_index_still_points_at_the_right_rule_after_a_lift()
    scenario_accepting_a_lift_writes_an_exception_not_a_deletion()
    print("test_negotiation_consent OK")
