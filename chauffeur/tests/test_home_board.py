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
    got = home_board.resolve_widgets('chores,drives,chores,made-up', {})
    check(got == ['chores', 'drives'],
          f"unknown keys dropped and duplicates collapsed, got {got}")


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

        # A live drive is never "over", however far past its end time it runs.
        late = home_board.todays_runs(now=_at(23))
        check(not next(r for r in late if r['id'] == 'now')['over'],
              "a drive still under way at 11pm is not behind us")
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
    todays_runs, and both consumers read it."""
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
        check(tile is not None and tile.get('empty'),
              "so the drives tile must say it is done rather than list the 5pm "
              f"drive under 'the rest of the day', got {tile}")
        check('drivers' not in (tile or {}),
              "and it must not still be rendering the finished drive")
    finally:
        (storage.get_cached_schedule, storage.get_all_drivers,
         storage.get_completed_drives, storage.get_in_progress_drives) = (orig_s, orig_d, orig_c, orig_p)


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
        board = home_board.build(requested=','.join(home_board.WIDGET_KEYS))
        keys = [t['key'] for t in board['tiles']]
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
        check('chores' not in [t['key'] for t in board['tiles']],
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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} home-board scenarios passed")
