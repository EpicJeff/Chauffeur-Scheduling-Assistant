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


def _deal(parts_states=('open', 'open')):
    parts = []
    for i, st in enumerate(parts_states):
        parts.append({'id': f'p{i}', 'member_id': f'm{i}',
                      'lever': 'skip_optional',
                      'payload': {'event_id': f'e{i}', 'title': 'Extra practice'},
                      'ask_text': 'Skip it?', 'state': st, 'request_id': None})
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


if __name__ == '__main__':
    scenario_one_yes_applies_nothing()
    scenario_the_last_yes_applies_the_whole_deal()
    scenario_one_no_kills_the_deal()
    scenario_a_refused_shift_is_remembered_against_the_series()
    scenario_a_person_can_kill_a_deal_by_hand()
    scenario_shift_writes_the_real_calendar_id_with_a_zone()
    print("test_negotiation_consent OK")
