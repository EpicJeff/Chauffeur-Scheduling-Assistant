"""The wall panel's home board (services/home_board.py).

Three properties are load-bearing, and all three are about what the board does
when it has nothing:

  1. A tile with nothing to say is ABSENT, not empty. A grid of six boxes each
     explaining that it is empty is the characteristic failure of every wall
     dashboard, and it teaches the family the panel is usually wrong.
  2. An empty CONFIGURATION means the defaults, never a blank screen. A blank
     display bolted to a wall is indistinguishable from a crashed one, so
     "nothing selected" can never resolve to "show nothing".
  3. The hero is the next thing that actually happens — which means done
     drives drop out, an in-progress drive outranks a later one, and "they are
     all behind us" is said out loud rather than left blank.

Run from chauffeur/:  python tests/test_home_board.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import home_board, storage


def _clear_cache():
    home_board._CACHE.update(key=None, at=0.0, data=None)


def _sched(*events):
    """A cached-schedule stand-in: events plus an assignment for each."""
    return {'events': [e for e, _ in events],
            'assignments': {e['id']: d for e, d in events},
            'scheduled_errands': []}


def _at(hour, minute=0):
    return datetime.datetime.combine(datetime.date.today(),
                                     datetime.time(hour, minute))


# --- configuration resolution ---------------------------------------------

def scenario_the_url_beats_the_profile_which_beats_the_defaults():
    """An HA dashboard card is a second panel with different needs, and its
    only config channel is its own address — so the URL has to win. The stored
    profile exists for the display that has no one to type a URL at it."""
    check(home_board.resolve_widgets(None, {}) == home_board.DEFAULT_WIDGETS,
          "nothing configured -> the defaults")
    check(home_board.resolve_widgets(None, {'panel_widgets': ['meals']}) == ['meals'],
          "the stored profile is used when the URL says nothing")
    check(home_board.resolve_widgets('chores', {'panel_widgets': ['meals']}) == ['chores'],
          "the URL overrides the stored profile")


def scenario_an_empty_selection_is_never_a_blank_screen():
    """Property 2. Every path that could resolve to nothing resolves to the
    defaults instead."""
    for requested, settings in ((None, {'panel_widgets': []}),
                                ('', {}),
                                ('bogus,also-bogus', {}),
                                (None, {'panel_widgets': ['nonsense']})):
        got = home_board.resolve_widgets(requested, settings)
        check(got == home_board.DEFAULT_WIDGETS,
              f"resolve_widgets({requested!r}, {settings}) blanked the board: {got}")
    check(home_board.resolve_tabs(None, {'panel_tabs': []}) == home_board.DEFAULT_TABS,
          "an empty tab profile falls back to the defaults")


def scenario_tabs_none_really_does_mean_none():
    """The one case where showing nothing IS the request: `?tabs=none` marks an
    embedded card that wants no chrome at all."""
    check(home_board.resolve_tabs('none', {}) == [], "?tabs=none -> no tabs")
    check(home_board.resolve_tabs('', {}) == [], "?tabs= (empty) -> no tabs")


def scenario_unknown_keys_are_dropped_not_rendered():
    got = home_board.resolve_widgets('chores,drives,made-up', {})
    check(got == ['chores', 'drives'], f"unknown keys dropped, got {got}")


def scenario_the_same_tile_can_appear_twice():
    """This used to be impossible by construction: `resolve_widgets` deduped,
    so a second calendar was silently discarded and the household had no way to
    find out why. Repeating a type is now the point of the thing — two calendar
    tiles set to two different people is the case the arc exists for — so the
    only rule left is that the two must be TELLABLE APART."""
    got = home_board.resolve_instances('chores,drives,chores', {})
    check([i['type'] for i in got] == ['chores', 'drives', 'chores'],
          f"a repeated tile is still being collapsed: {got}")
    ids = [i['id'] for i in got]
    check(len(set(ids)) == 3, f"two instances share an id: {ids}")
    check(ids[0] == 'chores',
          "the first instance of a type no longer takes the bare type as its "
          "id — every stored tile size is keyed by that string, so this is "
          "what keeps an upgrade from resetting the board's layout")


def scenario_a_stored_board_of_plain_names_still_works():
    """Every install that predates this arc has `panel_widgets` stored as a
    list of type names. Nothing rewrites it behind their back, so the upgrade
    has to happen on read, and their tile sizes have to survive it."""
    settings = {'panel_widgets': ['drives', 'map'],
                'panel_tile_spans': {'map': {'cols': 6, 'rows': 2}}}
    got = home_board.resolve_instances(None, settings)
    check([i['type'] for i in got] == ['drives', 'map'],
          f"the old shape no longer resolves: {got}")
    check(got[1]['span'] == {'cols': 6, 'rows': 2},
          f"the map's stored size did not survive the upgrade: {got[1]}")


def scenario_a_card_can_ask_for_a_configured_board():
    """`?widgets=a,b` is what people type and what every existing HA card
    sends, so it keeps working exactly as it did. A card that wants a
    CONFIGURED board has nowhere to say so in a comma-separated list, and
    inventing a mini-language in a query string would be worse than admitting
    it is JSON."""
    got = home_board.resolve_instances(
        '[{"type": "calendar", "config": {"days": 3}}]', {})
    check(len(got) == 1 and got[0]['type'] == 'calendar',
          f"a JSON board did not resolve: {got}")
    check(got[0]['config'] == {'days': 3},
          f"the card's config was dropped: {got[0]}")
    check(home_board.resolve_instances('[not json', {}),
          "malformed JSON emptied the board — a blank wall panel is "
          "indistinguishable from a crash, so it must fall back")


def scenario_an_unset_idle_timer_means_the_default_not_disabled():
    """storage.get_settings() returns the STORED dict — model defaults are not
    in it. Reading absent as 0 would ship the feature silently switched off on
    every install that predates it, while an explicit 0 is a real choice."""
    orig = storage.get_settings
    try:
        storage.get_settings = lambda: {}
        check(home_board.profile()['idle_seconds'] == 180,
              "an unset idle timer resolves to the 180s default")
        storage.get_settings = lambda: {'panel_idle_return_seconds': 0}
        check(home_board.profile()['idle_seconds'] == 0,
              "an explicit zero stays off")
        storage.get_settings = lambda: {'panel_idle_return_seconds': 600}
        check(home_board.profile()['idle_seconds'] == 600, "a set value is used")
    finally:
        storage.get_settings = orig


# --- the runs and the hero ------------------------------------------------

def scenario_the_hero_is_the_next_drive_that_has_not_happened():
    ev = lambda i, h: ({'id': i, 'title': i, 'start': _at(h).isoformat(),
                        'end': _at(h + 1).isoformat()}, 'drv1')
    orig_s, orig_d, orig_c, orig_p = (storage.get_cached_schedule, storage.get_all_drivers,
                                      storage.get_completed_drives, storage.get_in_progress_drives)
    try:
        storage.get_cached_schedule = lambda: _sched(ev('morning', 8), ev('evening', 18))
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Sam', 'color_code': '#fff'}]
        storage.get_completed_drives = lambda: []
        storage.get_in_progress_drives = lambda: []

        runs = home_board.todays_runs(now=_at(12))
        check([r['id'] for r in runs] == ['morning', 'evening'], "runs sort by time")

        hero = home_board._hero(_at(12), runs)
        check(hero['next']['id'] == 'evening', "midday: the evening drive is next")
        check(hero['remaining'] == 1,
              "the morning drive is behind us even though nobody marked it done")

        # Property 3, the part a blank hero gets wrong: after everything, say so.
        hero = home_board._hero(_at(22), home_board.todays_runs(now=_at(22)))
        check(hero['next'] is None and hero['all_done'],
              "after the last drive the hero says everyone is home")
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_completed_drives, storage.get_in_progress_drives) = (orig_s, orig_d, orig_c, orig_p)


def scenario_the_hero_says_when_to_leave():
    """Asked for from the wall: *"it would be nice if the hero said 'leave at
    4:20pm' or 'leave in 1 hr 46 min' instead of just telling me the event
    starts in 2 hr 26 min — the leave time is the more important of the two."*

    The app has always had the number: the solver computes the travel into
    every drive it assigns, and the kid digest has printed "🚀 Leave by 8:47 AM"
    since arc K5. It lived inside `main.member_day`, out of reach of the board.
    One rule now (services/leave_by), or the kitchen and the phone eventually
    disagree about when to put your shoes on.

    The rule includes its own silence: **no travel time, no leave time**. A
    guessed departure gets a household burned once and then the whole board is
    never believed again."""
    orig = (storage.get_cached_schedule, storage.get_cached_daily_schedule,
            storage.get_all_drivers, storage.get_completed_drives,
            storage.get_in_progress_drives)
    try:
        sched = {
            'events': [
                {'id': 'ballet', 'title': 'Pre Jazz/Ballet',
                 'start': _at(17).isoformat(), 'end': _at(18).isoformat()},
                {'id': 'later', 'title': 'Pickup',
                 'start': _at(19).isoformat(), 'end': _at(19, 30).isoformat()},
                {'id': 'blind', 'title': 'Unknown route',
                 'start': _at(21).isoformat(), 'end': _at(22).isoformat()},
            ],
            'assignments': {'ballet': 'drv1', 'later': 'drv1', 'blind': 'drv1'},
            'scheduled_errands': [],
            # From home for the first, mid-chain for the second, nothing at all
            # for the third.
            'initial_edges': {'drv1': {'ballet': {'travel_mins': 26,
                                                  'buffer_before_mins': 14}}},
            'route_edges': {'drv1': {'ballet': {'from_event': 'ballet',
                                                'to_event': 'later',
                                                'travel_mins': 10}}},
        }
        storage.get_cached_schedule = lambda: sched
        storage.get_cached_daily_schedule = lambda d: None
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Vovo',
                                            'color_code': '#fff'}]
        storage.get_completed_drives = lambda: []
        storage.get_in_progress_drives = lambda: []

        runs = {r['id']: r for r in home_board.todays_runs(now=_at(14, 34))}
        check(runs['ballet']['leave_label'] == '4:20 PM',
              f"5:00 start − 26 min drive − 14 min buffer = 4:20, got "
              f"{runs['ballet'].get('leave_label')}")
        check(runs['ballet']['from_home'],
              "an initial edge is the driver setting out from home")
        check(runs['later']['leave_label'] == '6:50 PM' and not runs['later']['from_home'],
              f"a mid-chain drive has a real departure too, got {runs['later']}")
        check('leave_at' not in runs['blind'],
              "no travel time means no leave time — a guessed departure is "
              "worse than none")

        hero = home_board._hero(_at(14, 34), list(runs.values()))
        check(hero['next']['id'] == 'ballet', "the hero is still the next drive")
        check(hero['next']['minutes_to_leave'] == 106,
              f"1 hr 46 min to leave, not 2 hr 26 min to start, got "
              f"{hero['next']['minutes_to_leave']}")
        check(hero['next']['minutes_until'] == 146,
              "and the start time is still carried, because it is still true")

        hero = home_board._hero(_at(21, 30), [runs['blind']])
        check(hero['next'].get('minutes_to_leave') is None,
              "a drive with no known travel leaves the countdown on the start")
    finally:
        (storage.get_cached_schedule, storage.get_cached_daily_schedule,
         storage.get_all_drivers, storage.get_completed_drives,
         storage.get_in_progress_drives) = orig


def scenario_next_up_is_the_one_you_leave_for_first():
    """Reported from the wall with two 5:00 events: the hero FLIPPED between
    them on refetches (ties fell through to the assignments dict's order from
    the last solve), and when it settled it showed the 4:47 departure while
    the other event needed leaving at 4:43. Both wrong for the same reason:
    the board's own language says the leave time is the one somebody sets an
    alarm by, so "next" is sorted by when somebody must ACT — the departure
    when the schedule knows it — with an id tail so the order is total and
    two same-time events can never trade places between refetches."""
    orig = (storage.get_cached_schedule, storage.get_cached_daily_schedule,
            storage.get_all_drivers, storage.get_completed_drives,
            storage.get_in_progress_drives)
    try:
        def sched_with(assignments):
            return {
                'events': [
                    {'id': 'lab', 'title': 'Practice: Girls 2033',
                     'start': _at(17).isoformat(), 'end': _at(18).isoformat()},
                    {'id': 'gym', 'title': 'Open Gym',
                     'start': _at(17).isoformat(), 'end': _at(18).isoformat()},
                ],
                'assignments': assignments,
                'scheduled_errands': [],
                'initial_edges': {'d1': {'lab': {'travel_mins': 17}},
                                  'd2': {'gym': {'travel_mins': 13}}},
                'route_edges': {},
            }
        storage.get_cached_daily_schedule = lambda d: None
        storage.get_all_drivers = lambda: [
            {'id': 'd1', 'name': 'Sarah', 'color_code': '#fff'},
            {'id': 'd2', 'name': 'Mom', 'color_code': '#fff'}]
        storage.get_completed_drives = lambda: []
        storage.get_in_progress_drives = lambda: []

        firsts = []
        for assignments in ({'lab': 'd1', 'gym': 'd2'}, {'gym': 'd2', 'lab': 'd1'}):
            storage.get_cached_schedule = lambda a=assignments: sched_with(a)
            runs = home_board.todays_runs(now=_at(14))
            firsts.append(runs[0]['id'])
            hero = home_board._hero(_at(14), runs)
            check(hero['next']['id'] == 'lab',
                  f"the 4:43 departure outranks the 4:47 one, got {hero['next']['id']}")
        check(firsts == ['lab', 'lab'],
              f"and the order ignores the solve's dict order entirely: {firsts}")

        # An earlier START with a KNOWN later departure still yields to the
        # drive that must leave first — the sort key is when you act.
        sched = sched_with({'lab': 'd1', 'gym': 'd2'})
        sched['events'][1]['start'] = _at(17, 30).isoformat()  # gym starts later
        sched['initial_edges']['d2']['gym']['travel_mins'] = 90  # but leaves 16:00
        storage.get_cached_schedule = lambda: sched
        hero = home_board._hero(_at(14), home_board.todays_runs(now=_at(14)))
        check(hero['next']['id'] == 'gym',
              f"a later start with the earlier departure is still what's next, "
              f"got {hero['next']['id']}")
    finally:
        (storage.get_cached_schedule, storage.get_cached_daily_schedule,
         storage.get_all_drivers, storage.get_completed_drives,
         storage.get_in_progress_drives) = orig


def scenario_the_hero_says_when_the_thing_is_optional():
    """Reported from the wall: the hero asserted 'Next up' for a drop-in
    event exactly like a firm commitment — the false urgency the optional
    flag exists to end. The runs carry the flag and the decision, and the
    hero card wears them ('optional' undecided, '✓ going' once answered)."""
    orig = (storage.get_cached_schedule, storage.get_cached_daily_schedule,
            storage.get_all_drivers, storage.get_completed_drives,
            storage.get_in_progress_drives)
    try:
        sched = {
            'events': [
                {'id': 'gym', 'title': 'Open Gym',
                 'start': _at(17).isoformat(), 'end': _at(18).isoformat(),
                 'app_config': {'is_optional': True},
                 'optional_decision': None},
            ],
            'assignments': {'gym': 'd1'},
            'scheduled_errands': [], 'initial_edges': {}, 'route_edges': {},
        }
        storage.get_cached_schedule = lambda: sched
        storage.get_cached_daily_schedule = lambda d: None
        storage.get_all_drivers = lambda: [{'id': 'd1', 'name': 'Sarah',
                                            'color_code': '#fff'}]
        storage.get_completed_drives = lambda: []
        storage.get_in_progress_drives = lambda: []

        hero = home_board._hero(_at(14), home_board.todays_runs(now=_at(14)))
        check(hero['next']['optional'] is True,
              f"the hero knows the event is the soft kind: {hero['next']}")
        check(hero['next']['optional_decision'] is None,
              "and that nobody has answered yet")

        sched['events'][0]['optional_decision'] = 'attend'
        hero = home_board._hero(_at(14), home_board.todays_runs(now=_at(14)))
        check(hero['next']['optional_decision'] == 'attend',
              "an answered occurrence carries the confirmation through")
    finally:
        (storage.get_cached_schedule, storage.get_cached_daily_schedule,
         storage.get_all_drivers, storage.get_completed_drives,
         storage.get_in_progress_drives) = orig


def scenario_a_thing_that_has_started_is_not_next():
    """Photographed from the wall at 1:53 PM: **"NEXT UP · 53 min ago — Pre
    Jazz/Ballet"**, for a class that began at one o'clock and still had ten
    minutes to run. Both halves were right on their own and the sentence they
    made together was nonsense.

    The cause is the one that has bitten this board twice already: `live` is a
    MANUAL flag from somebody tapping a leg as started, and nobody taps. So
    "under way" is read off the clock, exactly as `over` already is, and the
    hero says so instead of counting down to something in progress."""
    orig = (storage.get_cached_schedule, storage.get_all_drivers,
            storage.get_completed_drives, storage.get_in_progress_drives)
    try:
        storage.get_cached_schedule = lambda: _sched(
            ({'id': 'ballet', 'title': 'Pre Jazz/Ballet', 'start': _at(13).isoformat(),
              'end': _at(14).isoformat()}, 'drv1'),
            ({'id': 'bus', 'title': 'Kesem Bus Pick-Up', 'start': _at(17, 45).isoformat(),
              'end': _at(18).isoformat()}, 'drv1'))
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Vovo',
                                            'color_code': '#fff'}]
        storage.get_completed_drives = lambda: []
        storage.get_in_progress_drives = lambda: []       # nobody ever taps this

        # 1:53 PM, the moment in the photograph.
        now = _at(13, 53)
        runs = home_board.todays_runs(now=now)
        ballet = next(r for r in runs if r['id'] == 'ballet')
        check(ballet['underway'] and not ballet['live'],
              "a class between its start and its end is on, whatever anybody "
              f"remembered to press: {ballet}")
        check(not ballet['over'], "and it is certainly not behind us")

        hero = home_board._hero(now, runs)
        check(hero['next']['id'] == 'ballet', "the thing happening is the hero")
        check(hero['next']['underway'],
              "and the panel is told so, or it prints NEXT UP over it")
        check(hero['next']['minutes_left'] == 7,
              f"what is LEFT of it is the useful number, got "
              f"{hero['next']['minutes_left']}")

        # The moment it ends, the board moves on and counts down again.
        after = _at(14, 1)
        hero = home_board._hero(after, home_board.todays_runs(now=after))
        check(hero['next']['id'] == 'bus', "once it is over, the next one is next")
        check(not hero['next']['underway'] and hero['next']['minutes_until'] == 224,
              f"and it is a countdown again, got {hero['next']}")

        # Before it starts it is exactly what it says: next up.
        before = _at(12, 30)
        hero = home_board._hero(before, home_board.todays_runs(now=before))
        check(hero['next']['id'] == 'ballet' and not hero['next']['underway'],
              "before one o'clock the ballet class really is next")
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_completed_drives, storage.get_in_progress_drives) = orig


def scenario_the_events_end_time_is_when_the_event_ends():
    """Photographed from the wall at 4:07 PM: **"HAPPENING NOW · under way —
    Guitar"**, for a 3:00-3:30 lesson. Jeff tapped Start Drive at 2:35 and
    nobody ever marked the leg complete, so `live` held `over` false forever.

    The family's ruling, verbatim in spirit: the hero's subject is the EVENT,
    and the event has an end time. The live flag is a claim about a DRIVE —
    an away game an hour from home would otherwise read "happening now" for
    the whole ride back. Whether people are home yet is presence's business;
    past its end time the event is over, no grace, whatever any leg says."""
    orig = (storage.get_cached_schedule, storage.get_all_drivers,
            storage.get_completed_drives, storage.get_in_progress_drives)
    try:
        storage.get_cached_schedule = lambda: _sched(
            ({'id': 'guitar', 'title': 'Guitar', 'start': _at(15).isoformat(),
              'end': _at(15, 30).isoformat()}, 'drv1'),
            ({'id': 'dinner', 'title': 'Team Dinner', 'start': _at(18).isoformat(),
              'end': _at(19).isoformat()}, 'drv1'))
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Jeff',
                                            'color_code': '#fff'}]
        storage.get_completed_drives = lambda: []
        # The stale leg: started, never completed.
        storage.get_in_progress_drives = lambda: ['init_guitar']

        # During the lesson the live leg is welcome to elevate it.
        during = _at(15, 10)
        hero = home_board._hero(during, home_board.todays_runs(now=during))
        check(hero['next']['id'] == 'guitar' and hero['next']['live'],
              "while the clock is inside the event, it is genuinely on")

        # 3:31: the event is over. Not at 3:50, not after a grace — at its
        # own end time, exactly as the calendar printed it.
        just_after = _at(15, 31)
        runs = home_board.todays_runs(now=just_after)
        guitar = next(r for r in runs if r['id'] == 'guitar')
        check(guitar['over'],
              f"one minute past its end the event is over, live leg or not: {guitar}")
        hero = home_board._hero(just_after, runs)
        check(hero['next']['id'] == 'dinner',
              f"and the board moves on to the real next thing, got {hero['next']['id']}")
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_completed_drives, storage.get_in_progress_drives) = orig


def scenario_a_drive_under_way_outranks_a_later_one():
    """Somebody walking past needs to see the drive that is happening, even
    though its start time is behind them."""
    orig_s, orig_d, orig_c, orig_p = (storage.get_cached_schedule, storage.get_all_drivers,
                                      storage.get_completed_drives, storage.get_in_progress_drives)
    try:
        storage.get_cached_schedule = lambda: _sched(
            ({'id': 'now', 'title': 'Practice', 'start': _at(16).isoformat(),
              'end': _at(17, 30).isoformat()}, 'drv1'),
            ({'id': 'later', 'title': 'Pickup', 'start': _at(19).isoformat(),
              'end': _at(20).isoformat()}, 'drv1'))
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Sam', 'color_code': '#fff'}]
        storage.get_completed_drives = lambda: []
        storage.get_in_progress_drives = lambda: ['init_now']

        hero = home_board._hero(_at(16, 40), home_board.todays_runs(now=_at(16, 40)))
        check(hero['next']['id'] == 'now', "the in-progress drive is the hero")
        check(hero['next']['live'], "and it is marked live")

        # The live flag never outlives the event. "Never over while under
        # way" was the rule here, then a 20-minute grace; the family struck
        # both — the tile's subject is the EVENT, and its end time is when it
        # ends. The drive home is the map's story.
        after = home_board.todays_runs(now=_at(17, 31))
        check(next(r for r in after if r['id'] == 'now')['over'],
              "past its end time the event is over, live leg or not")
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_completed_drives, storage.get_in_progress_drives) = (orig_s, orig_d, orig_c, orig_p)


def scenario_the_hero_and_the_drives_tile_cannot_contradict_each_other():
    """The bug a photograph of the real panel caught: "Everyone's home 🏠 /
    Nothing left to drive today" printed directly above a tile headed "the
    rest of the day" listing a 5:00 PM drive, at 6:34 PM.

    The hero treated a drive as behind us once its end time passed; the tile
    only believed the manual completed flag, and nobody marks drives complete.
    Two definitions of "done" on one screen. `over` is now computed once, in
    todays_runs, and both consumers read it.

    The tile's side of the promise has changed shape once since: it used to
    swap to "Nothing left to drive today." prose, which repeated the hero's
    sentence across a quarter of the board. Now the timeline stays up all
    evening and `next_event_id` goes None — the panel scrolls to the bottom
    of the day instead of presenting anything as still to come."""
    orig_s, orig_d, orig_c, orig_p = (storage.get_cached_schedule, storage.get_all_drivers,
                                      storage.get_completed_drives, storage.get_in_progress_drives)
    try:
        storage.get_cached_schedule = lambda: _sched(
            ({'id': 'past', 'title': 'Academy - Dribble and Swish',
              'start': _at(17).isoformat(), 'end': _at(18).isoformat()}, 'drv1'))
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Vovo', 'color_code': '#f00'}]
        storage.get_completed_drives = lambda: []      # nobody ever taps this
        storage.get_in_progress_drives = lambda: []

        evening = _at(18, 34)
        runs = home_board.todays_runs(now=evening)
        hero = home_board._hero(evening, runs)
        tile = home_board._tile_drives(evening, runs=runs)

        check(hero['all_done'], "the hero says the driving is done")
        check(tile is not None and 'schedule' in tile,
              f"the timeline stays up after the last drive, got {tile}")
        check(tile.get('next_event_id') is None,
              "but nothing may be presented as still to come — None is what "
              f"scrolls the panel to the bottom of the day, got {tile}")
        check(not tile.get('empty'),
              "and the hero's sentence is not repeated as tile prose")
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_completed_drives, storage.get_in_progress_drives) = (orig_s, orig_d, orig_c, orig_p)


def scenario_the_board_reads_the_day_the_drives_page_reads():
    """Reported from the wall: an event changed, the schedule re-solved, and
    the board said there was nothing left to drive today — while the Drives
    page, two taps away, listed the drives. It came back on its own several
    minutes later.

    The two surfaces were reading different caches. `/api/schedule?start&end`
    (the page) assembles its answer from the PER-DAY rows, rewritten the moment
    the solver finishes a day. `get_cached_schedule()` (the board) returns the
    combined global cache, which `main.refresh_schedule_logic` writes **only
    when called with no date range** — so a single day re-solving never touches
    it, and the five-minute poller is what eventually repairs it.

    The daily row can never be the staler of the two, because the global cache
    is compiled from those rows. So the board reads the day's own row first."""
    orig = (storage.get_cached_schedule, storage.get_cached_daily_schedule,
            storage.get_all_drivers, storage.get_completed_drives,
            storage.get_in_progress_drives)
    try:
        today = datetime.date.today()
        # The global cache: yesterday's compile. The 5pm practice is there but
        # nobody is assigned to it any more, and it names a drive that has since
        # been dropped from the day.
        storage.get_cached_schedule = lambda: {
            'events': [{'id': 'stale', 'title': 'Cancelled thing',
                        'start': _at(17).isoformat(), 'end': _at(18).isoformat()},
                       {'id': 'ballet', 'title': 'Ballet',
                        'start': _at(19).isoformat(), 'end': _at(20).isoformat()}],
            'assignments': {'stale': 'drv1'},
            'scheduled_errands': [],
            'initial_edges': {'drv1': {'stale': {'travel_mins': 30}}},
        }
        # The day's own row, written by the solve that has just finished.
        storage.get_cached_daily_schedule = lambda d: ({
            'schedule': {
                'events': [{'id': 'ballet', 'title': 'Pre Jazz/Ballet',
                            'start': _at(17, 30).isoformat(),
                            'end': _at(18, 30).isoformat()}],
                'assignments': {'ballet': 'drv1'},
                'scheduled_errands': [],
                'initial_edges': {'drv1': {'ballet': {'travel_mins': 12}}},
            }} if d == today.isoformat() else None)
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Vovo',
                                            'color_code': '#fff'}]
        storage.get_completed_drives = lambda: []
        storage.get_in_progress_drives = lambda: []

        sched = home_board.day_schedule(today)
        titles = {e['id']: e['title'] for e in sched['events']}
        check(titles['ballet'] == 'Pre Jazz/Ballet',
              f"the day's own copy of the event wins, got {titles}")
        check(sched['assignments'] == {'ballet': 'drv1'},
              "an assignment the re-solve took away must not survive the merge — "
              f"that is a driver's name on the wall for a drive nobody is doing: "
              f"{sched['assignments']}")
        check(sched['initial_edges'] == {'drv1': {'ballet': {'travel_mins': 12}}},
              f"the edge maps prune with their events, got {sched['initial_edges']}")

        now = _at(16)
        runs = home_board.todays_runs(now=now, sched=sched)
        check([r['id'] for r in runs] == ['ballet'],
              f"the board sees exactly what the Drives page sees, got {runs}")
        check(home_board._hero(now, runs)['next']['id'] == 'ballet',
              "and the hero stops saying the day is empty")

        # No row for the day at all -> the global cache is all there is, and
        # nothing about it may be broken by the merge.
        storage.get_cached_daily_schedule = lambda d: None
        check(home_board.day_schedule(today)['assignments'] == {'stale': 'drv1'},
              "without a daily row the global cache is used untouched")
    finally:
        (storage.get_cached_schedule, storage.get_cached_daily_schedule,
         storage.get_all_drivers, storage.get_completed_drives,
         storage.get_in_progress_drives) = orig


def scenario_an_empty_cache_is_not_a_day_with_no_drives():
    """Two different sentences. "No drives today" is a claim about the day;
    an empty cache is the absence of any claim — a fresh install, a cleared
    cache, the minute before the first refresh lands. A wall panel that says
    the first when it means the second is how a board stops being believed."""
    orig = (storage.get_cached_schedule, storage.get_cached_daily_schedule,
            storage.get_all_drivers)
    try:
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Vovo'}]
        storage.get_cached_daily_schedule = lambda d: None

        storage.get_cached_schedule = lambda: {}
        tile = home_board._tile_drives(_at(12), runs=[], sched={})
        check('Waiting' in tile['empty'],
              f"an empty cache must say so, got {tile}")
        check(home_board._hero_unbuilt({}), "and the hero must know too")

        # A real day that simply has no drives on it still says the confident
        # thing, because there it is true.
        sched = {'events': [{'id': 'x', 'title': 'Dentist',
                             'start': _at(9).isoformat(), 'end': _at(10).isoformat()}],
                 'assignments': {}}
        tile = home_board._tile_drives(_at(12), runs=[], sched=sched)
        check(tile['empty'] == "No drives on the schedule today.",
              f"a real empty day keeps its own sentence, got {tile}")
        check(not home_board._hero_unbuilt(sched), "which is not the unbuilt state")
    finally:
        (storage.get_cached_schedule, storage.get_cached_daily_schedule,
         storage.get_all_drivers) = orig


def scenario_ghost_drivers_never_reach_the_wall():
    """A ghost driver is the solver's "nobody real can do this" placeholder.
    Naming one on the kitchen wall would be inventing a person."""
    orig_s, orig_d = storage.get_cached_schedule, storage.get_all_drivers
    try:
        storage.get_cached_schedule = lambda: _sched(
            ({'id': 'x', 'title': 'Unassignable', 'start': _at(9).isoformat(),
              'end': _at(10).isoformat()}, 'ghost_1'))
        storage.get_all_drivers = lambda: []
        check(home_board.todays_runs() == [], "ghost assignments are dropped")
    finally:
        storage.get_cached_schedule, storage.get_all_drivers = orig_s, orig_d


def scenario_mixed_timezone_stamps_do_not_raise():
    """The schedule cache mixes aware and naive stamps depending on which
    calendar an event came from; comparing them raises, and a wall panel that
    500s is a black rectangle in the kitchen."""
    orig_s, orig_d, orig_c, orig_p = (storage.get_cached_schedule, storage.get_all_drivers,
                                      storage.get_completed_drives, storage.get_in_progress_drives)
    try:
        aware = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=20, minute=0, second=0, microsecond=0)
        storage.get_cached_schedule = lambda: _sched(
            ({'id': 'aware', 'title': 'Aware', 'start': aware.isoformat(),
              'end': aware.isoformat()}, 'drv1'),
            ({'id': 'naive', 'title': 'Naive', 'start': _at(9).isoformat(),
              'end': _at(10).isoformat()}, 'drv1'))
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Sam', 'color_code': '#fff'}]
        storage.get_completed_drives = lambda: []
        storage.get_in_progress_drives = lambda: []
        runs = home_board.todays_runs()          # must not raise
        home_board._hero(_at(12), runs)          # nor must this
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_completed_drives, storage.get_in_progress_drives) = (orig_s, orig_d, orig_c, orig_p)


# --- the tiles ------------------------------------------------------------

def scenario_an_unconfigured_feature_has_no_tile():
    """Property 1, first half. A household that has never made a shopping list
    or an errand wants no tile for either — asking for all fourteen on a blank
    install yields nothing."""
    _clear_cache()
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: {}
        # `web` is excluded because it is a CONTAINER, not a summary of a
        # household feature. There is nothing for it to be unconfigured about
        # except its own address, and a tile somebody just added asking for
        # one is the opposite of the placeholder this rule forbids — the rule
        # is about features nobody uses, not about a box waiting to be told
        # what to show.
        asked = [k for k in home_board.WIDGET_KEYS if k != 'web']
        board = home_board.build(requested=','.join(asked))
        keys = [t['type'] for t in board['tiles']]
        # The calendar is never hidden — a family calendar is not a feature you
        # opt into, and a missing calendar tile reads as a broken panel. Every
        # other tile belongs to something this blank install has not set up.
        check(keys == ['calendar'],
              f"blank install -> the calendar and nothing else, got {keys}")
        check(board['tiles'][0]['data'].get('empty'),
              "and it says what it is quiet about")
        check(board['hero']['next'] is None and not board['hero']['all_done'],
              "no drives at all is distinct from all drives done")
    finally:
        storage.get_cached_schedule = orig
        _clear_cache()


def scenario_a_configured_feature_that_is_quiet_still_shows():
    """Property 1, second half, and the correction that mattered: the panel
    kept dropping to four tiles and the family could not tell whether the map
    was empty or the app was broken. A feature that IS set up shows up, with a
    sentence saying what it is quiet about."""
    _clear_cache()
    orig_lists, orig_items, orig_err = (storage.get_shopping_lists,
                                        storage.get_shopping_items,
                                        storage.get_all_errands)
    try:
        # A list exists but everything on it is checked off.
        storage.get_shopping_lists = lambda: [{'id': 'l1', 'name': 'Groceries'}]
        storage.get_shopping_items = lambda *a, **kw: [{'is_checked': True}]
        tile = home_board._tile_shopping(datetime.datetime.now())
        check(tile and tile.get('empty'),
              f"a configured-but-empty list must still render, got {tile}")

        # An errand exists but it is done.
        storage.get_all_errands = lambda: [{'title': 'x', 'is_completed': True}]
        tile = home_board._tile_errands(datetime.datetime.now())
        check(tile and tile.get('empty'),
              f"errands that are all finished still render, got {tile}")

        # Nothing at all, either way -> genuinely unconfigured, so hidden.
        storage.get_shopping_lists = lambda: []
        storage.get_all_errands = lambda: []
        check(home_board._tile_shopping(datetime.datetime.now()) is None,
              "no lists ever -> no tile")
        check(home_board._tile_errands(datetime.datetime.now()) is None,
              "no errands ever -> no tile")
    finally:
        (storage.get_shopping_lists, storage.get_shopping_items,
         storage.get_all_errands) = orig_lists, orig_items, orig_err
        _clear_cache()


def scenario_the_map_is_never_hidden_for_being_quiet():
    """Where everyone is has no empty day. A member with no tracking appears as
    unknown rather than silently missing — you cannot otherwise tell "not
    tracked" from "not home"."""
    orig = storage.get_all_members
    try:
        storage.get_all_members = lambda *a, **kw: [
            {'id': 'm1', 'name': 'Sam', 'role': 'parent'},      # no HA entity
            {'id': 'm2', 'name': 'Kit', 'role': 'child'},
        ]
        tile = home_board._tile_map(datetime.datetime.now(), runs=[])
        check(tile and len(tile['people']) == 2,
              f"everyone appears whether tracked or not, got {tile}")
        storage.get_all_members = lambda *a, **kw: []
        check(home_board._tile_map(datetime.datetime.now(), runs=[]) is None,
              "no family members at all -> no tile")
    finally:
        storage.get_all_members = orig


def scenario_the_map_tile_carries_pins_not_just_zone_words():
    """Six names beside six zone words is a table of contents for a map:
    "not_home" is true and tells you nothing, while a pin two streets away
    tells you they are walking back.

    The coordinates cost nothing — this builder was already reading each
    member's HA state and keeping only the zone word. What it must NOT do is
    invent a second vocabulary for them: the payload speaks
    /api/family/locations' field names (`latitude`, `driving.leg_title`) so the
    one shared renderer takes either source without a translation layer.
    """
    from services import ha_api
    orig_m, orig_s, orig_c = (storage.get_all_members, ha_api.get_state,
                              storage.get_all_cars)
    try:
        storage.get_all_members = lambda *a, **kw: [
            {'id': 'm1', 'name': 'Sam', 'role': 'parent', 'driver_id': 'drv1',
             'ha_person_entity': 'person.sam'},
            {'id': 'm2', 'name': 'Kit', 'role': 'child'},       # untracked
        ]
        storage.get_all_cars = lambda *a, **kw: []
        ha_api.get_state = lambda ent: {
            'state': 'not_home',
            'attributes': {'latitude': 41.5, 'longitude': -81.6}}

        runs = [{'driver_id': 'drv1', 'title': 'Practice', 'live': True}]
        tile = home_board._tile_map(datetime.datetime.now(), runs=runs)
        sam = next(p for p in tile['people'] if p['name'] == 'Sam')
        kit = next(p for p in tile['people'] if p['name'] == 'Kit')
        check(sam['latitude'] == 41.5 and sam['longitude'] == -81.6,
              f"a tracked member carries coordinates, got {sam}")
        check(sam.get('driving', {}).get('leg_title') == 'Practice',
              "driving is the shape the map component reads, not a bare string")
        check(kit['latitude'] is None and kit['member_id'] == 'm2',
              "an untracked member is still on the list, without a pin")
        check(tile['mapped'] == 1,
              f"the panel is told how many pins there are, got {tile.get('mapped')}")
    finally:
        (storage.get_all_members, ha_api.get_state,
         storage.get_all_cars) = orig_m, orig_s, orig_c


def scenario_the_drives_tile_hands_over_a_schedule_not_a_drawing():
    """The tile draws the Drives page's OWN timeline now — same renderer, from
    components/schedule_timeline.html — so what it sends is the schedule that
    renderer reads, sliced to one day.

    What it must never do is call `GET /api/schedule`: that endpoint SAVES a
    combined range cache and kicks a background refresh, so a panel polling it
    would keep the solver warm forever for a display nobody is looking at.
    Rule 3, in the one place it would be easiest to break."""
    orig = (storage.get_cached_schedule, storage.get_all_drivers,
            storage.get_completed_drives, storage.get_in_progress_drives)
    try:
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        sched = {
            'events': [
                {'id': 'a', 'title': 'Practice', 'start': _at(16).isoformat(),
                 'end': _at(17, 30).isoformat()},
                {'id': 'b', 'title': 'Pickup', 'start': _at(18).isoformat(),
                 'end': _at(19).isoformat()},
                {'id': 'far', 'title': 'Next week',
                 'start': datetime.datetime.combine(tomorrow, datetime.time(9)).isoformat(),
                 'end': datetime.datetime.combine(tomorrow, datetime.time(10)).isoformat()},
            ],
            'assignments': {'a': 'drv1', 'b': 'drv2', 'far': 'drv1'},
            'scheduled_errands': [],
            'initial_edges': {'drv1': {'a': {'travel_mins': 12}, 'far': {'travel_mins': 40}}},
            'route_edges': {'drv2': {'b': {'travel_mins': 8}}},
            'unassigned': ['far'],
        }
        storage.get_cached_schedule = lambda: sched
        storage.get_all_drivers = lambda: [
            {'id': 'drv1', 'name': 'Sam', 'color_code': '#f00'},
            {'id': 'drv2', 'name': 'Vovo', 'color_code': '#00f'}]
        storage.get_completed_drives = lambda: []
        storage.get_in_progress_drives = lambda: []

        now = _at(15, 20)
        tile = home_board._tile_drives(now, runs=home_board.todays_runs(now=now),
                                       sched=sched)
        slice_ = tile['schedule']
        check([e['id'] for e in slice_['events']] == ['a', 'b'],
              f"one day, not the whole horizon: {[e['id'] for e in slice_['events']]}")
        check(slice_['date'] == datetime.date.today().isoformat(),
              "the slice names its day, which is what dateFilter matches on")
        check('far' not in slice_['assignments'] and 'far' not in slice_['unassigned'],
              "tomorrow's event must not drag its assignment along")
        check(slice_['initial_edges']['drv1'] == {'a': {'travel_mins': 12}},
              f"edges prune to the same day's events, got {slice_['initial_edges']}")
        check([d['id'] for d in slice_['drivers']] == ['drv1', 'drv2'],
              "the renderer names its columns from `drivers`, so they travel too")
        check(tile['next_event_id'] == 'a',
              "the tile says where to open, or it opens on breakfast")
        for control in ('ai_metadata', 'duplicate_groups', 'solving_dates'):
            check(control not in slice_,
                  f"`{control}` renders a BUTTON, and a wall board is a display")
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_completed_drives, storage.get_in_progress_drives) = orig


def scenario_the_calendar_tile_is_an_agenda_of_days():
    """A flat list of the next six things cannot say that Thursday is empty,
    and "Thursday is empty" is a thing families read a calendar to find out.
    The agenda's day cards say it by existing.

    Today's finished events STAY, greyed — the calendar page's own agenda shows
    the whole day and always has. The first cut dropped them, which also made a
    busy morning invisible: two things left at four in the afternoon read as a
    quiet day rather than as a day nearly done."""
    orig = (storage.get_cached_schedule, storage.get_all_drivers,
            storage.get_all_members)
    try:
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        storage.get_cached_schedule = lambda: {
            'events': [
                {'id': 'past', 'title': 'Dentist', 'start': _at(8).isoformat(),
                 'end': _at(9).isoformat()},
                {'id': 'later', 'title': 'Practice', 'start': _at(17).isoformat(),
                 'end': _at(18).isoformat()},
                {'id': 'trip', 'title': 'Disney', 'event_type': 'background_trip',
                 'start': _at(0).isoformat(), 'end': _at(23).isoformat()},
                {'id': 'orphan', 'title': 'Recital',
                 'start': datetime.datetime.combine(tomorrow, datetime.time(19)).isoformat(),
                 'end': datetime.datetime.combine(tomorrow, datetime.time(20)).isoformat()},
            ],
            'assignments': {'later': 'drv1'},
            'unassigned': ['orphan'],
            'scheduled_errands': []}
        storage.get_all_drivers = lambda: [{'id': 'drv1', 'name': 'Sam',
                                            'color_code': '#ff0000'}]
        storage.get_all_members = lambda *a, **kw: []

        tile = home_board._tile_calendar(_at(12))
        days = {d['day']: d for d in tile['days']}
        check(len(tile['days']) == home_board.AGENDA_DAYS,
              f"a card per day whether or not it has anything on it, got {len(tile['days'])}")
        check(len(home_board._tile_calendar(_at(12), settings={'panel_agenda_days': 9})['days']) == 9,
              "how many days is the household's call — it depends on how wide "
              "they made the tile and what they use the board for")
        for bad, want in ((0, 1), (99, 14), ('a week', home_board.AGENDA_DAYS)):
            got = home_board.agenda_days({'panel_agenda_days': bad})
            check(got == want, f"agenda_days({bad!r}) -> {got}, wanted {want}")
        check(days['Today']['today'] and days['Today']['dom'] == datetime.date.today().day,
              "today knows it is today")
        titles = [e['title'] for e in days['Today']['events']]
        check(titles == ['Dentist', 'Practice'],
              f"the whole day is on the card, in order, got {titles}")
        by_title = {e['title']: e for e in days['Today']['events']}
        check(by_title['Dentist']['past'] and not by_title['Practice']['past'],
              "what has already happened is flagged for greying, not dropped")
        check('Disney' not in str(tile),
              "a trip's own span event would print on all five cards; trips have "
              "their own tile")
        check(by_title['Practice']['driver'] == 'Sam',
              "an assigned event names its driver")

        # A day that does not fit loses what has already happened, from the
        # top. Keeping this morning's school run by dropping this evening's
        # pickup would be answering the wrong question.
        busy = {'events': [
            {'id': f'p{i}', 'title': f'Past {i}', 'start': _at(6 + i).isoformat(),
             'end': _at(6 + i, 30).isoformat()} for i in range(5)
        ] + [{'id': 'soon', 'title': 'Pickup', 'start': _at(17).isoformat(),
              'end': _at(18).isoformat()}],
            'assignments': {}, 'unassigned': [], 'scheduled_errands': []}
        card = home_board._tile_calendar(_at(12), sched=busy)['days'][0]
        shown = [e['title'] for e in card['events']]
        check('Pickup' in shown and card['earlier'] == 1,
              f"the day trims from the front: showed {shown}, earlier={card['earlier']}")
        recital = days['Tomorrow']['events'][0]
        check(recital['needs_driver'] and recital['color'] == '#ef4444',
              f"the one thing somebody must act on is coloured for it, got {recital}")
        check(not any(d['events'] for d in tile['days'][2:]),
              "the quiet days are present and empty, which is the whole point")
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_all_members) = orig


def scenario_the_meals_tile_reads_and_never_composes():
    """Composing a plate here would make the wall panel a writer of meal plans,
    on a timer, forever. The tile shows a PINNED plate or nothing."""
    _clear_cache()
    orig_plate, orig_dishes = storage.get_plate, storage.get_dishes_by_ids
    composed = []
    try:
        from services import meals
        orig_compose = meals.get_or_compose_plate
        meals.get_or_compose_plate = lambda *a, **kw: composed.append(1)

        storage.get_plate = lambda d: None
        check(home_board._tile_meals(datetime.datetime.now()) is None,
              "no pinned plate -> no tile")

        storage.get_plate = lambda d: {'items': [{'dish_id': 'd1'}], 'edited': True}
        storage.get_dishes_by_ids = lambda ids: [{'id': 'd1', 'name': 'roasted potatoes',
                                                  'short_name': 'potatoes'}]
        tile = home_board._tile_meals(datetime.datetime.now())
        check(tile and tile['dishes'][0]['name'] == 'potatoes',
              "a pinned plate renders the family's own short name")
        check(not composed, "the board never composed a plate")
    finally:
        storage.get_plate, storage.get_dishes_by_ids = orig_plate, orig_dishes
        meals.get_or_compose_plate = orig_compose
        _clear_cache()


def scenario_one_bad_tile_does_not_take_the_board_down():
    """A wall panel shows the other five rather than a stack trace."""
    _clear_cache()
    orig = home_board._BUILDERS['chores']
    def boom(*a, **kw):
        raise RuntimeError("the points ledger exploded")
    try:
        home_board._BUILDERS['chores'] = boom
        board = home_board.build(requested='chores,drives')
        check(isinstance(board.get('tiles'), list), "the board still built")
        check('chores' not in [t['type'] for t in board['tiles']],
              "the failing tile is simply absent")
    finally:
        home_board._BUILDERS['chores'] = orig
        _clear_cache()


def scenario_the_board_is_cached_so_a_second_panel_costs_nothing():
    _clear_cache()
    calls = []
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: (calls.append(1), {})[1]
        home_board.build(requested='drives')
        home_board.build(requested='drives')
        check(len(calls) == 1, f"the second build hit the cache, got {len(calls)} reads")
        # A different tile set is a different board and must not be served the
        # cached one.
        home_board.build(requested='chores')
        check(len(calls) == 2, "a different widget set rebuilds")
    finally:
        storage.get_cached_schedule = orig
        _clear_cache()


def scenario_a_trip_you_are_currently_on_is_not_hidden():
    """The bug: the panel said "No trips planned" while the family was ON a
    trip, with another six days out and a draft after that.

    Two causes. A real trip's dates live on its Google calendar event, not on
    its TripMetadata — the tile was reading `mock_start_date`, which only
    drafts have. And it filtered out anything starting before today, which is
    exactly what a trip you are in the middle of looks like."""
    orig = (storage.get_cached_trips, storage.get_all_trip_metadata,
            storage.get_cached_schedule, storage.get_trip_metadata)
    try:
        today = datetime.date.today()
        storage.get_cached_trips = lambda: {'trips': [
            {'id': 't1', 'title': 'Disney', 'location': 'Orlando',
             'start': (today - datetime.timedelta(days=2)).isoformat(),
             'end': (today + datetime.timedelta(days=3)).isoformat()},
            {'id': 't2', 'title': 'Grandma',
             'start': (today + datetime.timedelta(days=5)).isoformat(),
             'end': (today + datetime.timedelta(days=7)).isoformat()},
        ]}
        storage.get_all_trip_metadata = lambda: [
            {'event_id': 't3', 'is_draft': True, 'title': 'Paris',
             'mock_start_date': None, 'mock_end_date': None}]
        storage.get_cached_schedule = lambda: {}
        storage.get_trip_metadata = lambda tid: {}

        tile = home_board._tile_trips(datetime.datetime.now())
        got = {t['title']: t for t in tile['trips']}
        check('Disney' in got, f"the trip we are ON must appear, got {tile}")
        check(got['Disney']['live'], "and be flagged as under way")
        check(got['Disney']['days'] == 0, "never a negative countdown")
        check(list(got)[0] == 'Disney', "the live one leads")
        check('Grandma' in got, "the upcoming one appears too")
    finally:
        (storage.get_cached_trips, storage.get_all_trip_metadata,
         storage.get_cached_schedule, storage.get_trip_metadata) = orig


def scenario_a_trip_is_found_without_calling_google():
    """The safety net: no snapshot yet, but the trip's activities are sitting
    in the schedule cache with real dates on them. /api/trips reads Google
    live and a board polling every 60s can never do that."""
    orig = (storage.get_cached_trips, storage.get_all_trip_metadata,
            storage.get_cached_schedule, storage.get_trip_metadata)
    try:
        soon = datetime.datetime.combine(
            datetime.date.today() + datetime.timedelta(days=6), datetime.time(12))
        storage.get_cached_trips = lambda: {}
        storage.get_all_trip_metadata = lambda: [{'event_id': 'tX'}]
        storage.get_cached_schedule = lambda: {'events': [
            {'id': 'a', 'trip_id': 'tX', 'start': soon.isoformat(),
             'end': (soon + datetime.timedelta(hours=2)).isoformat()},
            {'id': 'b', 'trip_id': 'tX',
             'start': (soon + datetime.timedelta(days=2)).isoformat(),
             'end': (soon + datetime.timedelta(days=2, hours=1)).isoformat()},
        ]}
        storage.get_trip_metadata = lambda tid: {'title': 'Disney'}
        tile = home_board._tile_trips(datetime.datetime.now())
        check(tile.get('trips') and tile['trips'][0]['days'] == 6,
              f"span derived from the cached activities, got {tile}")
    finally:
        (storage.get_cached_trips, storage.get_all_trip_metadata,
         storage.get_cached_schedule, storage.get_trip_metadata) = orig


def scenario_a_search_phrase_is_not_used_as_an_image():
    """`background_url` has held things like "disney world" since long before
    this board existed. As an <img src> that is a broken image on the wall."""
    orig = (storage.get_cached_trips, storage.get_all_trip_metadata,
            storage.get_cached_schedule, storage.get_trip_metadata)
    try:
        storage.get_cached_trips = lambda: {'trips': [
            {'id': 't1', 'title': 'Disney', 'background_url': 'disney world',
             'start': datetime.date.today().isoformat(),
             'end': datetime.date.today().isoformat()}]}
        storage.get_all_trip_metadata = lambda: []
        storage.get_cached_schedule = lambda: {}
        storage.get_trip_metadata = lambda tid: {}
        tile = home_board._tile_trips(datetime.datetime.now())
        check(tile['trips'][0]['image'] is None,
              f"a bare phrase is not an image src, got {tile['trips'][0]['image']!r}")
    finally:
        (storage.get_cached_trips, storage.get_all_trip_metadata,
         storage.get_cached_schedule, storage.get_trip_metadata) = orig


def scenario_the_kids_ride_in_the_hero_not_a_tile():
    """The hero band is full width and was spending it restating the drives
    tile. The kids move into it as columns, and must not also remain a tile —
    the same content twice is how the board got called wasted space."""
    _clear_cache()
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: {}
        board = home_board.build(
            requested='kids,calendar',
            kid_digest_fn=lambda: {'label': 'Today', 'kids': {
                'k1': {'name': 'Addison', 'lines': ['5:00 PM — practice']}}})
        check(board['hero']['kids'] and board['hero']['kids'][0]['name'] == 'Addison',
              f"kids ride in the hero, got {board['hero'].get('kids')}")
        check('kids' not in [t['type'] for t in board['tiles']],
              "and are not repeated as a tile")
    finally:
        storage.get_cached_schedule = orig
        _clear_cache()


def scenario_the_background_takes_a_phrase_not_just_a_url():
    """Nobody wants to go and find an image URL to hang a picture on their
    kitchen wall. A phrase is handed to the Unsplash endpoint that already
    backs trip artwork; a real URL is passed through untouched."""
    check(home_board._background_url({'panel_background': 'https://x/y.jpg'})
          == 'https://x/y.jpg', "a URL is used as-is")
    check(home_board._background_url({'panel_background': 'mountains at dusk'})
          == 'api/unsplash/background?query=mountains%20at%20dusk',
          "a phrase becomes a lookup")
    check(home_board._background_url({}) is None, "unset -> the built-in gradient")
    check(home_board._background_url({'panel_background': '   '}) is None,
          "whitespace is not a search")


def scenario_every_page_in_the_nav_can_be_a_tile():
    """The panel is the whole app on a wall, so every destination on the shelf
    has to have a glance on the board — otherwise the board quietly says some
    parts of Chauffeur are less real than others. `home` is the board itself
    and `schedule` is the drives tile under its nav slug."""
    covered = set(home_board.WIDGET_KEYS) | {'home', 'schedule'}
    missing = [s for s in home_board.NAV_SLUGS if s not in covered]
    check(not missing, f"nav pages with no home-board tile: {missing}")


def scenario_the_catalog_offers_only_things_that_exist():
    cat = home_board.catalog()
    keys = {w['key'] for w in cat['widgets']}
    check(keys == set(home_board.WIDGET_KEYS), "the catalog lists every widget")
    check(all(k in keys for k in cat['widget_defaults']),
          "every default is a real widget")
    check(all(w.get('label') and w.get('blurb') for w in cat['widgets']),
          "every widget explains itself to whoever is picking six of nine")
    check(all(k in home_board.NAV_SLUGS for k in cat['tab_defaults']),
          "every default tab is a real destination")
    check(all(b['key'] in home_board._BUILDERS for b in cat['widgets']),
          "every offered widget has a builder behind it")


def scenario_a_row_is_a_real_unit_not_whatever_the_neighbours_did():
    """Reported from the wall: setting a tile to 2 rows guaranteed nothing.

    The grid sized its rows to content, so "2 rows tall" meant "as tall as
    whatever those two rows happened to be" — a height decided by the OTHER
    tiles in them — and in the last row it did nothing at all, because there
    was no second row there to occupy. A fixed unit is what makes `rows` a
    measurement: Home Assistant's grid works the same way, and it is the only
    version where the number the household picked is the number they get.
    """
    import os
    check(home_board.grid_row_height({}) == 240, "an unset row height has a default")
    check(home_board.grid_row_height({'panel_grid_row_height': 200}) == 200,
          "the household's number is used as given")
    # The clamps are JUDGEMENT, not a technical limit — `grid-auto-rows` takes
    # any length. They are read from the module rather than written down here,
    # so widening them is one edit and this still guards what it is for: a
    # value that breaks the arithmetic (a 5px row makes every span meaningless)
    # rather than one that offends taste.
    for bad, want in (({'panel_grid_row_height': 0}, home_board.ROW_MIN),
                      ({'panel_grid_row_height': 50000}, home_board.ROW_MAX),
                      ({'panel_grid_row_height': 'tall'}, 240)):
        got = home_board.grid_row_height(bad)
        check(got == want, f"{bad} -> {got}, wanted {want}")

    check(home_board.grid_columns({}) == 12,
          "twelve columns by default — it divides by 2, 3, 4 and 6, so halves, "
          "thirds and quarters all exist. At four, a quarter of the board was "
          "the NARROWEST thing anybody could ask for")
    check(home_board.grid_columns({'panel_grid_columns': 16}) == 16, "and it is settable")
    for bad, want in (({'panel_grid_columns': 0}, 1),
                      ({'panel_grid_columns': 99999}, home_board.COLUMN_MAX),
                      ({'panel_grid_columns': None}, 12)):
        got = home_board.grid_columns(bad)
        check(got == want, f"{bad} -> {got}, wanted {want}")

    board = home_board.build()
    for key in ('row_height', 'columns'):
        check(board.get(key), f"the board must carry `{key}` to the panel — a grid "
              "whose units are guessed on the page is the same number decided twice")

    # The grid has to declare the unit, or every span is back to being a
    # consequence of its neighbours. `grid-auto-rows` covers IMPLICIT rows,
    # which is precisely what the last row of the board is made of.
    tpl = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'templates', 'home.html'), encoding='utf-8').read()
    grid = tpl[tpl.index('<!-- ── The glances.'):]
    grid = grid[:grid.index('</template>')]
    check('grid-auto-rows' in grid,
          "the tile grid no longer fixes its row height, so a span means nothing again")
    # The first cut of this used minmax(Xpx, auto) to protect tiles from
    # clipping, and that made the whole feature a NO-OP: tile content is
    # already taller than any sane minimum, so every row went on being sized by
    # content and a 2-row span changed nothing anybody could see. A span
    # multiplies only if the row is a ceiling as well as a floor.
    check('minmax(' not in grid,
          "a row is a floor again, which means spans do nothing visible again")
    check('overflow-y-auto' in grid,
          "a fixed row must be paired with scrolling, or the board silently cuts "
          "off what a tile has to say — and a clipped tile reads as a broken one")
    # Columns are the household's number too, so the tracks cannot be Tailwind's
    # fixed `grid-cols-N` classes — those exist only for the handful of numbers
    # Tailwind ships, and the CDN build only generates what it can see anyway.
    check('grid-cols-' not in grid,
          "the tile grid is back on fixed Tailwind columns, so the column count "
          "setting does nothing")
    check('--c-lg' in grid,
          "the grid no longer takes its column count from the board payload")

    # A picture tile's whole job is showing pictures, so its mosaic has to be
    # as tall as the tile is — a fixed stack of rows left a band of empty card
    # under the photographs on any tile somebody made taller, which is the one
    # kind of tile where size is the entire point.
    body = tpl[tpl.index("t.type === 'meals'"):tpl.index("t.type === 'calendar'")]
    check(body.count('grid-auto-rows: minmax(0, 1fr)') >= 2,
          "a mosaic is back to fixed-height rows, so it no longer fills its tile")
    check('flex-1 min-h-0' in body,
          "the mosaic does not claim the space its tile has left over")
    check('fillsTile(t.type)' in tpl and 'isMosaic(key)' in tpl,
          "tiles drawn INTO their slot (the mosaics, the map, the timeline) are "
          "no longer distinguished from tiles read down a list, so either they "
          "scroll a photograph or every text tile is stretched to fill")
    # The DECLARATION, not the first mention. This used to search from the
    # first occurrence of the bare name anywhere in the file, so a comment
    # that referred to the list — in a stylesheet four hundred lines above it —
    # moved the window and failed the check with a message about maps.
    _decl = tpl.index('DRAWN_TILES:')
    for key in ("'map'", "'drives'"):
        check(key in tpl[_decl:_decl + 200],
              f"{key} is drawn to fit its tile and must be listed as such — "
              "a map given its content height is a map an inch tall")


def scenario_a_page_is_configured_in_one_place():
    """The shelf buttons and the per-page pictures were two lists of the same
    twelve destinations: you picked Meals in one section and scrolled to
    another to say what the meals page looks like. They are the same thing —
    a page the panel shows — so the picture rides on the page's own row, the
    way a tile's size rides on the tile's row."""
    import os
    tpl = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'templates', 'home.html'), encoding='utf-8').read()
    setup = tpl[tpl.index('id="panel-setup"'):]
    check('A different picture per page' not in setup,
          "the per-page pictures are a separate list again, so the same "
          "destinations are configured in two places")
    row = setup[setup.index('x-for="(slug, i) in draft.panel_tabs"'):]
    row = row[:row.index('</template>')]
    check('panel_page_backgrounds[slug]' in row,
          "a page's picture is not on the page's own row")
    for control in ('move(draft.panel_tabs', 'panel_tabs.splice'):
        check(control in row, f"the row lost its {control} control in the merge")


# ── "Follow the sun" (panel_theme: sun)
#
# This mode exists because `auto` — a CSS media query — silently reads "light"
# whenever nothing is there to answer it, which is every way of opening the
# panel except inside a Home Assistant dashboard. So the arithmetic below is
# the whole feature, and it is arithmetic nobody can eyeball on a wall panel:
# a wrong answer just looks like a panel that is light at 11pm.

_UTC = datetime.timezone.utc


def _sun_state(rising, setting, state='above_horizon'):
    """A `sun.sun` as HA serves it: ISO strings with an offset."""
    return {'entity_id': 'sun.sun', 'state': state,
            'attributes': {'next_rising': rising.isoformat(),
                           'next_setting': setting.isoformat()}}


def _with_sun(payload, fn):
    from services import ha_api
    real = ha_api.get_state
    ha_api.get_state = lambda entity_id: payload if entity_id == 'sun.sun' else None
    try:
        return fn()
    finally:
        ha_api.get_state = real


def scenario_sun_reads_the_next_change_to_decide_what_is_true_now():
    """Midday: the sun sets before it rises again, so the panel is light."""
    now = datetime.datetime(2026, 8, 9, 16, 0, tzinfo=_UTC)
    payload = _sun_state(rising=datetime.datetime(2026, 8, 10, 10, 30, tzinfo=_UTC),
                         setting=datetime.datetime(2026, 8, 10, 0, 15, tzinfo=_UTC))
    got = _with_sun(payload, lambda: home_board.sun_theme({}, now=now))
    check(got['theme'] == 'light', f"midday should be light, got {got}")
    check(got['next_flip'].startswith('2026-08-10T00:15'),
          f"the next flip should be tonight's sunset, got {got['next_flip']}")

    # Small hours: the next change is to light, so right now it is dark.
    got = _with_sun(payload, lambda: home_board.sun_theme(
        {}, now=datetime.datetime(2026, 8, 10, 3, 0, tzinfo=_UTC)))
    check(got['theme'] == 'dark', f"3am should be dark, got {got}")
    check(got['next_flip'].startswith('2026-08-10T10:30'),
          f"the next flip should be sunrise, got {got['next_flip']}")


def scenario_a_positive_sunset_offset_still_fires_tonight():
    """The one the naive version gets wrong. Five minutes AFTER sunset with a
    +30 offset, `next_setting` has already rolled over to tomorrow — so adding
    the offset to it says "goes dark in 24 hours" when the real switch is 25
    minutes away, and the panel stays light through the whole evening."""
    now = datetime.datetime(2026, 8, 10, 0, 20, tzinfo=_UTC)     # sunset was 00:15
    payload = _sun_state(rising=datetime.datetime(2026, 8, 10, 10, 30, tzinfo=_UTC),
                         setting=datetime.datetime(2026, 8, 11, 0, 13, tzinfo=_UTC))
    got = _with_sun(payload, lambda: home_board.sun_theme(
        {'panel_theme_sunset_offset_minutes': 30}, now=now))
    check(got['theme'] == 'light', f"still 25 min of grace left, got {got}")
    check(got['next_flip'].startswith('2026-08-10T00:43'),
          f"tonight's switch, not tomorrow's: {got['next_flip']}")

    # And once it passes, it is dark — not light again until sunrise +offset.
    got = _with_sun(payload, lambda: home_board.sun_theme(
        {'panel_theme_sunset_offset_minutes': 30},
        now=datetime.datetime(2026, 8, 10, 0, 50, tzinfo=_UTC)))
    check(got['theme'] == 'dark', f"past the offset it should be dark, got {got}")


def scenario_a_negative_sunrise_offset_fires_before_sunrise():
    """The household's own argument for two offsets: matching the sunset's +30
    means going light 30 minutes BEFORE sunrise, so the offset drags a
    still-future `next_rising` into the past and it must be honoured now."""
    now = datetime.datetime(2026, 8, 10, 10, 15, tzinfo=_UTC)    # sunrise is 10:30
    payload = _sun_state(rising=datetime.datetime(2026, 8, 10, 10, 30, tzinfo=_UTC),
                         setting=datetime.datetime(2026, 8, 11, 0, 13, tzinfo=_UTC))
    got = _with_sun(payload, lambda: home_board.sun_theme(
        {'panel_theme_sunrise_offset_minutes': -30}, now=now))
    check(got['theme'] == 'light',
          f"10:00 was the switch, 10:15 should already be light: {got}")
    check(got['next_flip'].startswith('2026-08-11T00:13'),
          f"next change is tonight's sunset: {got['next_flip']}")


def scenario_sun_falls_back_to_dark_when_home_assistant_says_nothing():
    """A panel that has lost HA at 2am must not decide to light the kitchen."""
    got = _with_sun(None, lambda: home_board.sun_theme({}))
    check(got == {'theme': 'dark', 'next_flip': None},
          f"no HA should mean dark with no timer, got {got}")

    # Garbage timestamps fall back the same way as absent ones — but the
    # entity's own state is still a real answer when it got that far.
    payload = {'state': 'below_horizon', 'attributes': {'next_rising': 'soon'}}
    got = _with_sun(payload, lambda: home_board.sun_theme({}))
    check(got['theme'] == 'dark' and got['next_flip'] is None,
          f"unparseable times should fall back to the state, got {got}")
    payload = {'state': 'above_horizon', 'attributes': {}}
    check(_with_sun(payload, lambda: home_board.sun_theme({}))['theme'] == 'light',
          "above_horizon with no attributes should still read light")


def scenario_the_panel_profile_never_ships_the_word_sun():
    """Everything downstream — ha_theme's cached attribute, every
    [data-panel-theme="light"] rule in the skin — predates this mode and must
    never have to learn it. The profile resolves to a literal."""
    payload = _sun_state(rising=datetime.datetime(2036, 8, 10, 10, 30, tzinfo=_UTC),
                         setting=datetime.datetime(2036, 8, 10, 0, 15, tzinfo=_UTC))
    orig = storage.get_settings
    try:
        storage.get_settings = lambda: {'panel_theme': 'sun'}
        got = _with_sun(payload, lambda: home_board.profile())
        check(got['theme'] in ('light', 'dark'),
              f"the profile leaked a mode the client cannot render: {got['theme']}")
        check(got['next_flip'], "sun mode shipped no flip time, so a panel left "
                                "up for a week never changes")

        # An unknown value is still dark, and a hand-picked one passes through.
        storage.get_settings = lambda: {'panel_theme': 'nonsense'}
        check(home_board.profile()['theme'] == 'dark',
              "unknown themes must fall back to dark")
        storage.get_settings = lambda: {'panel_theme': 'auto'}
        got = home_board.profile()
        check(got['theme'] == 'auto' and got['next_flip'] is None,
              f"auto must survive untouched and schedule nothing, got {got}")
    finally:
        storage.get_settings = orig


def scenario_the_panel_reasks_at_the_flip_instead_of_flipping_itself():
    """A tablet that slept through the boundary, or a household that changed
    the offset this afternoon, both have to come back correct — so the timer
    re-fetches rather than toggling the attribute on a number it cached hours
    ago. And the delay has to be capped: setTimeout's 32-bit delay fires
    INSTANTLY past ~24.9 days, which would be a poll loop, not a timer."""
    import os
    nav = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'templates', 'nav.html'), encoding='utf-8').read()
    check('scheduleThemeFlip(p.next_flip)' in nav,
          "the profile no longer arms the theme timer")
    body = nav[nav.index('function scheduleThemeFlip'):]
    body = body[:body.index('function panelProfile')]
    check('_profile = null' in body and 'panelProfile()' in body,
          "the flip timer no longer re-asks the server")
    check('6 * 3600 * 1000' in body, "the setTimeout delay is no longer capped")
    check('clearTimeout(_flipTimer)' in body,
          "navigating between pages would stack a timer per page load")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} home-board scenarios passed")
