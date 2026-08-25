"""The day as BLOCKS: the event is the atom, the outing is a container.

The wall answered "what is happening and are we ready" in four cards, and a
person had to join them in their head. The block spine is the join: driven
trips come from the outing machinery, at-home events come from the same event
feed the calendar card reads, covered rides come back from the dead (an event
Grandma drives has no household driver, so `outings_for` never saw it and its
packing vanished — a repair, not a feature), and all-day events become a
banner because they have no time to anchor a block to.

Run from chauffeur/:  python tests/test_family_day.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_famday_'))

import datetime  # noqa: E402

from services import family_day  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


DAY = '2026-09-08'


def _ev(eid, hh, mm=0, dur=60, title=None, **extra):
    start = datetime.datetime(2026, 9, 8, hh, mm)
    return {'id': eid, 'title': title or eid,
            'start': start.isoformat(),
            'end': (start + datetime.timedelta(minutes=dur)).isoformat(),
            **extra}


def _sched(events, assignments=None, route_edges=None, **extra):
    return {'events': events, 'assignments': assignments or {},
            'route_edges': route_edges or {}, 'initial_edges': {},
            'final_edges': {}, **extra}


def scenario_a_driven_event_is_an_outing_block():
    got = family_day.blocks_for(DAY, _sched([_ev('soccer', 16)], {'soccer': 'd1'}))
    check([b['kind'] for b in got['blocks']] == ['outing'],
          f"a driven event should be an outing block: {got['blocks']}")
    check(got['blocks'][0]['events'][0]['title'] == 'soccer',
          f"the outing block should carry its inner event lines: {got['blocks'][0]}")


def scenario_an_undriven_event_is_a_home_block():
    """The at-home birthday party: no assignment, still a happening."""
    got = family_day.blocks_for(DAY, _sched([_ev('party', 12, title='Birthday')]))
    b = got['blocks']
    check([x['kind'] for x in b] == ['event'], f"an undriven event is a bare block: {b}")
    check(b[0]['key'] == 'home:party', f"home blocks key as home:<event_id>: {b[0]}")


def scenario_a_covered_ride_names_its_hand():
    """Grandma driving does not mean the bag packs itself."""
    sched = _sched([_ev('swim', 15, 30)],
                   assist_assignments={'swim': 'c9'},
                   assist_contacts=[{'id': 'c9', 'name': 'Carol',
                                     'relation_label': 'Grandma'}])
    got = family_day.blocks_for(DAY, sched)
    b = got['blocks']
    check(len(b) == 1 and b[0]['covered_by'] == 'Grandma',
          f"a covered ride is a block naming its hand: {b}")


def scenario_blocks_interleave_in_time_order():
    sched = _sched([_ev('party', 12, title='Birthday'), _ev('soccer', 9)],
                   {'soccer': 'd1'})
    got = family_day.blocks_for(DAY, sched)
    check([b['kind'] for b in got['blocks']] == ['outing', 'event'],
          f"blocks interleave by start time: {got['blocks']}")


def scenario_all_day_events_are_a_banner_not_blocks():
    sched = _sched([_ev('spirit', 0, title='Spirit Week', all_day=True),
                    _ev('soccer', 16)], {'soccer': 'd1'})
    got = family_day.blocks_for(DAY, sched)
    check(got['all_day'] == ['Spirit Week'], f"all-day is a banner: {got['all_day']}")
    check(len(got['blocks']) == 1, f"all-day never becomes a block: {got['blocks']}")


def scenario_a_skipped_optional_event_is_not_a_happening():
    """The family decided not to go. Drawing it anyway would nag the decision."""
    sched = _sched([_ev('fair', 10, optional_decision='skip')])
    check(family_day.blocks_for(DAY, sched)['blocks'] == [],
          "a skip-decided event became a block")


def scenario_a_canceled_event_is_a_struck_block():
    """Canceled is drawn, not hidden — the household needs to know it fell
    through (the cancellations arc's own rule) — but it carries no items."""
    got = family_day.blocks_for(DAY, _sched([_ev('game', 14, canceled=True)]))
    b = got['blocks']
    check(len(b) == 1 and b[0]['canceled'], f"a canceled event draws, struck: {b}")


def scenario_background_trips_are_not_blocks():
    got = family_day.blocks_for(DAY, _sched(
        [_ev('bg', 8, event_type='background_trip')]))
    check(got['blocks'] == [], f"a background trip leaked into the day: {got}")


def scenario_a_driven_events_block_is_not_doubled():
    """An event inside an outing must not also appear as a home block."""
    got = family_day.blocks_for(DAY, _sched([_ev('soccer', 16)], {'soccer': 'd1'}))
    check(len(got['blocks']) == 1, f"a driven event appeared twice: {got['blocks']}")


def scenario_the_day_turns_over_when_the_last_block_ends():
    """The turnover rule, widened: a day ending with an at-home party must not
    flip to tomorrow mid-party. (Moved here from test_outings.py where it
    watched only outings — the rule now watches blocks.)"""
    sched = _sched([_ev('party', 19, dur=120, title='Birthday')])
    mid = datetime.datetime(2026, 9, 8, 20, 0)
    check(family_day.day_in_focus(mid, sched) == datetime.date(2026, 9, 8),
          "a live home block should keep the day on today")
    after = datetime.datetime(2026, 9, 8, 21, 30)
    check(family_day.day_in_focus(after, sched) == datetime.date(2026, 9, 9),
          "once the last block ends the day turns over")


def scenario_a_canceled_block_does_not_hold_the_day():
    sched = _sched([_ev('game', 20, canceled=True)])
    quiet = datetime.datetime(2026, 9, 8, 9, 0)
    check(family_day.day_in_focus(quiet, sched) == datetime.date(2026, 9, 9),
          "a canceled event held the day on today")


def scenario_an_empty_day_is_already_tomorrow():
    """(Moved from test_outings.py, same meaning, wider input.)"""
    quiet = datetime.datetime(2026, 9, 8, 9, 0)
    check(family_day.day_in_focus(quiet, _sched([])) == datetime.date(2026, 9, 9),
          "a day with no blocks should already be looking at tomorrow")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} family-day scenarios passed")
