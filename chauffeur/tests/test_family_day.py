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

from services import family_day, outings  # noqa: E402


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


def scenario_day_in_focus_stays_on_today_during_the_drive_home():
    """(Moved from test_outings.py.) The turn-over point is the drive home,
    not the last event's end: a check ten minutes after the event ended but
    still inside a 25-minute drive home must still find today's outing
    ahead, and only turn over once the drive home itself is actually over --
    the widened rule must not lose the drive home."""
    sched = _sched([_ev('soccer', 16, dur=60)], {'soccer': 'd1'},
                   final_edges={'d1': {'soccer': {'from_event': 'soccer', 'travel_mins': 25}}})
    during_drive = datetime.datetime(2026, 9, 8, 17, 10)
    check(family_day.day_in_focus(during_drive, sched) == datetime.date(2026, 9, 8),
          "the day should stay on today while the drive home is still ahead")
    after_home = datetime.datetime(2026, 9, 8, 17, 30)
    check(family_day.day_in_focus(after_home, sched) == datetime.date(2026, 9, 9),
          "once the drive home is over the day should turn over to tomorrow")


# ── F2: whose event is it? ────────────────────────────────────────────────
#
# The card overrode every event's colour with the DRIVER's, and the household
# could not work out what the colours meant. Everywhere else in this app an
# event's colour is the colour of the calendar it lives on, which is the
# person's own. An event is a person's commitment; an outing is a logistics
# job. Passenger colour belongs to the event, driver colour to the trip.

_CAL_META = {
    'ellie@cal': {'summary': 'Ellie', 'backgroundColor': '#ec4899'},
    'sam@cal': {'summary': 'Sam', 'backgroundColor': '#22d3ee'},
}
_MEMBERS = [
    {'id': 'm-ellie', 'name': 'Ellie', 'calendar_ids': ['ellie@cal'],
     'color_code': '#ec4899'},
    {'id': 'm-sam', 'name': 'Sam', 'calendar_ids': ['sam@cal'],
     'color_code': '#22d3ee'},
]


def _pax_sched(events, assignments=None, **extra):
    return _sched(events, assignments, calendar_metadata=dict(_CAL_META),
                  members=[dict(m) for m in _MEMBERS], **extra)


def scenario_an_event_wears_its_own_persons_colour():
    ev = _ev('piano', 15, title='Piano')
    ev['calendar_ids'] = ['ellie@cal']
    got = family_day.blocks_for(DAY, _pax_sched([ev]))['blocks'][0]
    check(got['color'] == '#ec4899',
          f"the event should carry its calendar's colour, got {got.get('color')}")
    check([p['name'] for p in got['passengers']] == ['Ellie'],
          f"the event should name who it is for: {got.get('passengers')}")


def scenario_two_people_on_one_event_are_both_named():
    """Cleats for the wrong kid is the failure this prevents."""
    ev = _ev('swim', 14, title='Swim')
    ev['calendar_ids'] = ['ellie@cal', 'sam@cal']
    got = family_day.blocks_for(DAY, _pax_sched([ev]))['blocks'][0]
    check(sorted(p['name'] for p in got['passengers']) == ['Ellie', 'Sam'],
          f"both people should be named: {got.get('passengers')}")
    check(sorted(p['color'] for p in got['passengers']) == ['#22d3ee', '#ec4899'],
          f"each person brings their own colour: {got.get('passengers')}")


def scenario_an_outing_keeps_the_drivers_colour_but_its_events_do_not():
    """The colour law, in one scenario: the trip is the driver's, the events
    inside it belong to the people going."""
    a = _ev('soccer', 16, title='Soccer')
    a['calendar_ids'] = ['ellie@cal']
    b = _ev('band', 17, 30, title='Band')
    b['calendar_ids'] = ['sam@cal']
    sched = _pax_sched([a, b], {'soccer': 'd1', 'band': 'd1'},
                       route_edges={'d1': {'soccer': {'to_event': 'band',
                                                      'travel_mins': 15}}})
    out = family_day.blocks_for(DAY, sched)['blocks'][0]
    check(out['kind'] == 'outing', f"expected one outing: {out}")
    check('color' not in out or out.get('color') is None,
          "an outing must not claim an event colour - the driver colour is "
          "added by the endpoint, which is the only thing that knows drivers")
    lines = out['events']
    check([l['color'] for l in lines] == ['#ec4899', '#22d3ee'],
          f"inner lines should wear their own people's colours: {lines}")
    check(sorted(p['name'] for p in out['passengers']) == ['Ellie', 'Sam'],
          f"the outing should union its events' people: {out.get('passengers')}")


def scenario_nobody_is_invented_for_an_unmatched_calendar():
    ev = _ev('meeting', 10, title='Work thing')
    ev['calendar_ids'] = ['someone-elses@cal']
    got = family_day.blocks_for(DAY, _pax_sched([ev]))['blocks'][0]
    check(got['passengers'] == [], f"invented a person: {got['passengers']}")
    check(got.get('color') in (None, ''),
          f"an unknown calendar has no colour to borrow: {got.get('color')}")


# ── F3: prep is work, and work has a place in the day ────────────────────
#
# F1 drew the items on the outing they belong to, which means the list for a
# 4:00 PM departure appeared at 4:00 PM. That is a report, not help. A prep
# block is not an appointment -- it has no duration and never reaches the
# solver -- it is a POSITION in the list, placed where a household could
# actually do the packing.


def _kit_sched(events, assignments=None, **extra):
    return _pax_sched(events, assignments, **extra)


def _preps(day, sched, key, now=None):
    """`items_by_key` is how the caller says which blocks have anything to
    pack — family_day itself never touches kits or claims."""
    got = family_day.blocks_for(day, sched, now or datetime.datetime(2026, 9, 8, 6, 0),
                                items_by_key={key: 2})
    return [b for b in got['blocks'] if b['kind'] == 'prep']


def scenario_a_morning_outing_is_packed_the_night_before():
    """06:40 on the way out of the door is not a time anybody packs a bag."""
    ev = _ev('swim', 7, 30, title='Swim')
    ev['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([ev], {'swim': 'd1'})
    got = family_day.blocks_for(DAY, sched, datetime.datetime(2026, 9, 7, 9, 0),
                                items_by_key={'d1:swim': 2})
    prep = [b for b in got['blocks'] if b['kind'] == 'prep']
    check(prep == [], "a morning outing's prep belongs to the day BEFORE it")
    prior = family_day.blocks_for('2026-09-07', sched,
                                  datetime.datetime(2026, 9, 7, 9, 0),
                                  items_by_key={'d1:swim': 2})
    prep = [b for b in prior['blocks'] if b['kind'] == 'prep']
    check(len(prep) == 1, f"the night before should carry the prep: {prior['blocks']}")
    anchor = outings._parse(prep[0]['start'])
    check(anchor.hour == 17 and anchor.date() == datetime.date(2026, 9, 7),
          f"prep for a morning outing sits in the previous evening: {prep[0]}")
    check([t['for_key'] for t in prep[0]['tiles']] == ['d1:swim'],
          f"the tile must name its outing: {prep[0]}")


def scenario_an_afternoon_outing_is_packed_that_morning():
    ev = _ev('soccer', 16, title='Soccer')
    ev['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([ev], {'soccer': 'd1'})
    prep = _preps(DAY, sched, 'd1:soccer')
    check(len(prep) == 1, f"expected one prep block: {prep}")
    anchor = outings._parse(prep[0]['start'])
    check(anchor.hour == 0 and anchor.date() == datetime.date(2026, 9, 8),
          f"prep for an afternoon outing sits in that morning: {prep[0]}")


def scenario_an_evening_outing_is_packed_that_afternoon():
    """Not at dawn: a cooler packed ten hours early is its own kind of wrong,
    which is why the rule is bucket-shaped rather than everything-at-once."""
    ev = _ev('game', 19, title='Game')
    ev['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([ev], {'game': 'd1'})
    prep = _preps(DAY, sched, 'd1:game')
    anchor = outings._parse(prep[0]['start'])
    check(anchor.hour == 12, f"prep for an evening outing sits that afternoon: {prep[0]}")


def scenario_a_passed_window_keeps_asking():
    """A list you can act on beats a list that is filed correctly and
    invisible: if its window has gone and it is still unpacked, it moves to
    the front of what is left."""
    ev = _ev('soccer', 16, title='Soccer')
    ev['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([ev], {'soccer': 'd1'})
    late = datetime.datetime(2026, 9, 8, 14, 30)
    prep = _preps(DAY, sched, 'd1:soccer', now=late)
    anchor = outings._parse(prep[0]['start'])
    check(anchor >= late,
          f"a passed, unpacked prep block should move to now: {prep[0]}")


def scenario_an_outing_with_nothing_to_pack_has_no_prep_block():
    ev = _ev('soccer', 16, title='Soccer')
    ev['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([ev], {'soccer': 'd1'})
    got = family_day.blocks_for(DAY, sched, datetime.datetime(2026, 9, 8, 6, 0),
                                items_by_key={})
    check([b for b in got['blocks'] if b['kind'] == 'prep'] == [],
          "an outing with no items invented a prep block")


def scenario_a_tile_names_the_event_and_its_people():
    """You might pack cleats for the wrong kid if you do not know who the
    activity is for. (F4: the naming moved from the block to its tiles, since
    one block now serves a whole part of the day.)"""
    ev = _ev('soccer', 16, title='Soccer practice')
    ev['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([ev], {'soccer': 'd1'})
    prep = _preps(DAY, sched, 'd1:soccer')[0]
    check(prep['key'] == f'prep:{DAY}:morning',
          f"a prep block is now keyed by the part of the day: {prep['key']}")
    check(len(prep['tiles']) == 1, f"expected one tile: {prep['tiles']}")
    tile = prep['tiles'][0]
    check(tile['title'] == 'Soccer practice',
          f"the tile should name its event: {tile}")
    check([p['name'] for p in tile['passengers']] == ['Ellie'],
          f"the tile should name who it is for: {tile}")
    check(tile['for_key'] == 'd1:soccer',
          f"the tile must point at the block a claim is filed against: {tile}")


def scenario_one_block_holds_a_whole_part_of_the_day():
    """The incident: a Friday evening carrying four Saturday-morning trips
    drew FOUR blocks stacked at the same anchor, and — sharing a timestamp —
    they sorted by their internal keys, which is alphabetical by event id. To
    a household that is no order at all."""
    a = _ev('cages', 8, title='Cages')
    b = _ev('practice', 9, title='Practice')
    c = _ev('game', 11, 30, title='Game')
    for ev in (a, b, c):
        ev['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([a, b, c],
                       {'cages': 'd1', 'practice': 'd2', 'game': 'd3'})
    prior = family_day.blocks_for(
        '2026-09-07', sched, datetime.datetime(2026, 9, 7, 9, 0),
        items_by_key={'d1:cages': 2, 'd2:practice': 2, 'd3:game': 2})
    preps = [x for x in prior['blocks'] if x['kind'] == 'prep']
    check(len(preps) == 1,
          f"three morning trips should share ONE evening block: {len(preps)}")
    check([t['title'] for t in preps[0]['tiles']] == ['Cages', 'Practice', 'Game'],
          f"tiles must run in the order the day happens: "
          f"{[t['title'] for t in preps[0]['tiles']]}")


def scenario_an_outing_of_two_events_is_two_tiles():
    """You work one event's list at a time, so the tile is per event even
    when one trip covers two."""
    a, b = _ev('soccer', 16, title='Soccer'), _ev('band', 17, 30, title='Band')
    a['calendar_ids'] = b['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([a, b], {'soccer': 'd1', 'band': 'd1'},
                       route_edges={'d1': {'soccer': {'to_event': 'band',
                                                      'travel_mins': 15}}})
    prep = _preps(DAY, sched, 'd1:soccer')[0]
    check([t['title'] for t in prep['tiles']] == ['Soccer', 'Band'],
          f"one tile per event, in order: {prep['tiles']}")
    check(all(t['for_key'] == 'd1:soccer' for t in prep['tiles']),
          "both tiles file their claims against the one outing")


def scenario_buckets_do_not_merge_across_days():
    """Tomorrow's morning work is not tonight's morning work."""
    today = _ev('soccer', 16, title='Soccer')
    today['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([today], {'soccer': 'd1'})
    got = family_day.blocks_for(DAY, sched, datetime.datetime(2026, 9, 8, 6, 0),
                                items_by_key={'d1:soccer': 2})
    keys = [b['key'] for b in got['blocks'] if b['kind'] == 'prep']
    check(all(k.startswith(f'prep:{DAY}:') for k in keys),
          f"a block must belong to the day it is drawn on: {keys}")


def scenario_the_evening_block_sits_after_the_last_event_of_the_day():
    """Evening prep is TOMORROW's work, so it belongs at the end of the day.
    Anchored at a flat 17:00 it landed ahead of a 5:15 practice, which reads
    as "pack before you leave" when the truth is "pack when you get back"."""
    tonight = _ev('practice', 17, 15, dur=90, title='Practice')
    tonight['calendar_ids'] = ['ellie@cal']
    tomorrow = _ev('swim', 7, 30, title='Swim')
    tomorrow['start'] = '2026-09-09T07:30:00'
    tomorrow['end'] = '2026-09-09T08:30:00'
    tomorrow['calendar_ids'] = ['ellie@cal']
    sched = _kit_sched([tonight, tomorrow],
                       {'practice': 'd1', 'swim': 'd2'})
    got = family_day.blocks_for(DAY, sched, datetime.datetime(2026, 9, 8, 9, 0),
                                items_by_key={'d2:swim': 2})
    kinds = [b['kind'] for b in got['blocks']]
    check(kinds and kinds[-1] == 'prep',
          f"the evening block should come last on the day: {kinds}")
    prep = got['blocks'][-1]
    check(prep['start'] >= '2026-09-08T18:45:00',
          f"it should sit after the last event ends, not at a flat 17:00: {prep['start']}")


def scenario_an_unsolved_ride_is_flagged_not_camouflaged():
    """The agenda this card replaced flagged an unassigned event red and an
    unassignable one amber. The swap dropped both, and an unhandled ride
    drawn in its calendar's own colour reads as handled — the exact false
    calm the flags exist to break."""
    sched = _sched([_ev('game', 18, title='Practice')],
                   true_unassigned=['game'])
    b = family_day.blocks_for(DAY, sched)['blocks'][0]
    check(b['needs_driver'] and not b['conflict'],
          f"an unassigned event must say it needs a driver: {b}")

    # Unassignable: every diagnostic reason is a hard block — a conflict,
    # not a plea for a driver (same rule the calendar computes client-side).
    # Distinct reasons per driver: no single story to promote, so the
    # banner's generic sentence stands and `conflict_reason` stays None.
    sched = _sched([_ev('game', 18)], true_unassigned=['game'],
                   diagnostics={'game': {'d1': {'type': 'hard_conflict',
                                                'text': 'Away on a trip.'},
                                         'd2': {'type': 'unavailable',
                                                'text': 'Unavailable rule.'}}})
    b = family_day.blocks_for(DAY, sched)['blocks'][0]
    check(b['needs_driver'] and b['conflict'],
          f"all-hard-blocked must surface as a conflict: {b}")
    check(b['conflict_reason'] is None,
          f"mixed reasons must not promote one as THE cause: {b}")

    # One SHARED reason — a passenger double-booked blocks every driver
    # identically — is the actual cause, and the dialog must be able to say
    # it instead of blaming the drivers ("every driver is blocked" was read
    # as false the first time a household saw it).
    why = "Passenger cannot travel from/to 'Practice (Lions)' in time."
    sched = _sched([_ev('game', 18)], true_unassigned=['game'],
                   diagnostics={'game': {'d1': {'type': 'conflict', 'text': why},
                                         'd2': {'type': 'conflict', 'text': why}}})
    b = family_day.blocks_for(DAY, sched)['blocks'][0]
    check(b['conflict'] and b['conflict_reason'] == why,
          f"a reason every driver shares must ride the block: {b}")

    # One merely-optimization reason keeps it an actionable "needs driver".
    sched = _sched([_ev('game', 18)], true_unassigned=['game'],
                   diagnostics={'game': {'d1': {'type': 'optimization'}}})
    b = family_day.blocks_for(DAY, sched)['blocks'][0]
    check(b['needs_driver'] and not b['conflict'],
          f"an assignable event is not a conflict: {b}")

    # Covered outranks the solve (the coverage ladder's own rule), and a
    # canceled event needs nobody.
    sched = _sched([_ev('game', 18)], true_unassigned=['game'],
                   assist_assignments={'game': 'c9'},
                   assist_contacts=[{'id': 'c9', 'name': 'Carol'}])
    b = family_day.blocks_for(DAY, sched)['blocks'][0]
    check(not b['needs_driver'], f"a covered ride is handled: {b}")
    sched = _sched([_ev('game', 18, canceled=True)], true_unassigned=['game'])
    b = family_day.blocks_for(DAY, sched)['blocks'][0]
    check(not b['needs_driver'], f"a canceled event needs nobody: {b}")

    # The combined /api/schedule payloads publish the list as `unassigned`;
    # the flag must survive a sched shaped that way too.
    sched = _sched([_ev('game', 18)], unassigned=['game'])
    b = family_day.blocks_for(DAY, sched)['blocks'][0]
    check(b['needs_driver'], f"the `unassigned` spelling must count too: {b}")


def scenario_the_flags_reach_the_row_the_card_draws():
    """The hand path: the card's block→event adapter must pass the flags to
    `agendaEventRow`, whose badge ladder is what actually prints ⚠️ — and
    the slow /api/schedule combine must publish `true_unassigned`, or the
    calendar's own agenda loses the same flags whenever that path built
    (and cached) the range."""
    import inspect
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    card = open(os.path.join(root, 'templates', 'components',
                             'packing_card.html'), encoding='utf-8').read()
    check(card.count('isUnassigned: true') >= 2,
          "pkRowHtml/pkDetailsEv no longer hand the unassigned flag to the "
          "shared agenda row")
    check('isConflict: !!b.conflict' in card,
          "the conflict flavour of the flag was dropped on the way to the row")
    check('conflictReason: b.conflict_reason' in card,
          "the card's details adapter no longer hands the real reason to the "
          "dialog")
    cal = open(os.path.join(root, 'templates', 'components',
                            'family_calendar.html'), encoding='utf-8').read()
    check('props.conflictReason' in cal and 'conflictReason: conflictReason' in cal,
          "the dialog banner or the calendar's event builder lost the "
          "shared-reason path — conflicts blame the drivers again")
    import main
    src = inspect.getsource(main)
    check('"true_unassigned": combined_true_unassigned' in src,
          "the slow /api/schedule combine dropped true_unassigned again — "
          "agenda badges vanish on every range that path builds or caches")
    # The PWA Family tab speaks the same vocabulary: an unassignable event
    # wears the amber CONFLICT chip and its shared reason, never a red
    # "NEEDS DRIVER" that blames the drivers for a passenger's double-booking.
    app = open(os.path.join(root, 'templates', 'app.html'),
               encoding='utf-8').read()
    check('function conflictFor' in app and "r.type !== 'optimization'" in app,
          "the Family tab no longer classifies unassignable events")
    check("conflictChip('CONFLICT')" in app
          and 'conflictChip(`${label}: Conflict`)' in app,
          "the Family tab's card or leg chips lost the conflict flavour")
    check('card.conflictReason' in app,
          "the Family tab dropped the conflict's actual cause")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} family-day scenarios passed")
