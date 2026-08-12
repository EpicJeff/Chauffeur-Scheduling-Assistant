"""More than one board.

A board stopped being THE board. Everything before this arc assumed one wall
panel showing one set of tiles, and the settings said so — `panel_widgets`,
`panel_tile_spans`, `panel_grid_columns`, `panel_grid_row_height` were single
household-wide keys. Instanceable tiles pointing at specific Home Assistant
entities are what broke that: a driveway camera belongs on the hallway panel
and nowhere else.

The half of this that can silently ruin somebody's evening is the MIGRATION.
A household that has spent an hour arranging their kitchen board must open the
app after this upgrade and find that board, unchanged, in the same order, at
the same sizes, on the same grid, with the same picture behind it. So most of
what follows is about the board that already exists rather than the ones that
can now be made.

Run from chauffeur/:  python tests/test_board_pages.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_pages_'))

from services import home_board  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# A household mid-arrangement: a board they have edited, on a grid they chose.
LEGACY = {
    'panel_widgets': [
        {'id': 'calendar', 'type': 'calendar', 'config': {'days': 7}},
        {'id': 'calendar-2', 'type': 'calendar', 'config': {'title': "Emma's week"}},
        'drives', 'map',
    ],
    'panel_tile_spans': {'calendar': {'cols': 6, 'rows': 2}, 'map': {'cols': 4, 'rows': 3}},
    'panel_grid_columns': 16,
    'panel_grid_row_height': 205,
    'panel_page_backgrounds': {'home': 'mountains at dusk'},
}


def scenario_the_board_they_already_have_becomes_the_home_page():
    """The upgrade, and the only part of this arc that can lose work."""
    pages = home_board.normalize_pages(LEGACY)
    check(len(pages) == 1, f"an un-migrated household has exactly one board: {len(pages)}")
    home = pages[0]
    check(home['slug'] == 'home', f"the existing board is the home board: {home['slug']}")
    check([w['id'] for w in home['widgets']] ==
          ['calendar', 'calendar-2', 'drives', 'map'],
          f"the tiles or their ORDER changed on upgrade: {home['widgets']}")
    check(home['widgets'][0]['config'] == {'days': 7},
          "a tile's configuration was dropped on upgrade")
    check(home['spans'] == LEGACY['panel_tile_spans'],
          f"tile sizes did not survive: {home['spans']}")
    check(home['columns'] == 16 and home['row_height'] == 205,
          f"the household's grid was reset to somebody else's default: {home}")
    check(home['background'] == 'mountains at dusk',
          f"the board's picture was lost: {home['background']!r}")


def scenario_nothing_is_rewritten_behind_their_back():
    """Lazy, like the instance-shape upgrade before it. Reading the board must
    not change what is stored — a household that never opens the editor keeps
    what they have, and a migration that runs on read is a migration that runs
    on a wall panel at 3am with no way to undo it."""
    before = dict(LEGACY)
    home_board.normalize_pages(LEGACY)
    home_board.find_page('home', LEGACY)
    home_board.page_summaries(LEGACY)
    check(LEGACY == before, "reading the pages mutated the stored settings")
    check('panel_pages' not in LEGACY, "the migration was written back on a read")


def scenario_pages_win_entirely_once_they_exist():
    """No half-migrated state. A board reading its columns from a page and its
    row height from a legacy key is a split brain nobody can debug."""
    settings = dict(LEGACY, panel_pages=[
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives'],
         'columns': 8, 'row_height': 300},
    ])
    home = home_board.find_page('home', settings)
    check(home['columns'] == 8 and home['row_height'] == 300,
          f"the legacy grid leaked into a page that set its own: {home}")
    check([w['type'] for w in home['widgets']] == ['drives'],
          f"the legacy tiles leaked into a page: {home['widgets']}")


def scenario_a_new_board_is_empty_and_stays_empty():
    """The defaults exist so a household that has never configured anything
    gets a full board rather than a blank wall. A board somebody just MADE is a
    different thing entirely — filling it with thirteen tiles nobody asked for
    would be the app arguing with a deliberate act."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives']},
        {'slug': 'hallway', 'name': 'Hallway', 'widgets': []},
    ]}
    hallway = home_board.find_page('hallway', settings)
    check(hallway['widgets'] == [],
          f"a new board filled itself with defaults: {hallway['widgets']}")
    board = home_board.resolve_instances(None, settings, page=hallway)
    check(board == [], f"an empty board resolved to something: {board}")


def scenario_a_deleted_board_lands_on_a_real_one():
    """The address that asks for a missing board is a wall panel's bookmark.
    A screen bolted to a wall showing a 404 is worse than the same screen
    showing the home board."""
    settings = {'panel_pages': [{'slug': 'home', 'name': 'Home', 'widgets': ['drives']}]}
    for asked in ('kitchen', '', None, 'HOME', '../etc/passwd'):
        got = home_board.find_page(asked, settings)
        check(got['slug'] == 'home',
              f"asking for {asked!r} did not land on a real board: {got['slug']}")


def scenario_something_is_always_the_wall_s_own_board():
    """An idle panel returns to the home board, and the shelf's Home button
    means it. A settings file with no page claiming that slug — hand-edited, or
    written by some future editor — must not leave the panel with nowhere to
    go back to."""
    settings = {'panel_pages': [
        {'slug': 'hallway', 'name': 'Hallway', 'widgets': ['map']},
        {'slug': 'kitchen', 'name': 'Kitchen', 'widgets': ['meals']},
    ]}
    pages = home_board.normalize_pages(settings)
    check(pages[0]['slug'] == 'home',
          f"nothing claimed the home slug and nothing was promoted: {pages}")
    check(pages[0]['name'] == 'Hallway',
          "promoting a board to home renamed it, which is not the same thing")
    check(pages[1]['slug'] == 'kitchen', f"the other board was disturbed: {pages[1]}")


def scenario_a_board_is_never_nothing():
    """Every degenerate stored value lands on a real board with real tiles. A
    blank wall is indistinguishable from a crash, which is the rule this whole
    module is built on."""
    for broken in ({'panel_pages': []}, {'panel_pages': 'nonsense'},
                   {'panel_pages': [None, 7, 'x']}, {}, {'panel_pages': None}):
        pages = home_board.normalize_pages(broken)
        check(pages and pages[0]['widgets'],
              f"{broken} produced a board with nothing on it: {pages}")
        check(pages[0]['slug'] == 'home', f"{broken} produced no home board")


def scenario_slugs_are_addresses_so_they_are_unique_and_safe():
    """A slug goes in a URL. Two boards sharing one is a board you cannot
    reach; a slug with a slash in it is a route that means something else."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives']},
        {'name': 'Kitchen Wall', 'widgets': []},
        {'name': 'Kitchen Wall', 'widgets': []},
        {'slug': '../../etc', 'name': 'Sneaky', 'widgets': []},
        {'slug': 'UPPER CASE', 'name': 'Shouty', 'widgets': []},
    ]}
    slugs = [p['slug'] for p in home_board.normalize_pages(settings)]
    check(len(slugs) == len(set(slugs)), f"two boards share an address: {slugs}")
    check(slugs[1] == 'kitchen-wall' and slugs[2] == 'kitchen-wall-2',
          f"a repeated name did not get its own address: {slugs}")
    for s in slugs:
        check(home_board.PAGE_SLUG_RE.match(s), f"{s!r} is not a usable address")


def scenario_two_boards_do_not_share_a_cached_answer():
    """The board cache used to be one slot. Two panels on two boards would have
    evicted each other on every poll — each request a full rebuild, the cache
    doing worse than nothing."""
    check(home_board._CACHE_MAX >= 2,
          "the board cache cannot hold two boards at once")
    home_board._CACHE.clear()
    for n in range(home_board._CACHE_MAX + 3):
        home_board._CACHE[f'k{n}'] = {'at': 0, 'data': n}
        while len(home_board._CACHE) > home_board._CACHE_MAX:
            home_board._CACHE.pop(next(iter(home_board._CACHE)), None)
    check(len(home_board._CACHE) <= home_board._CACHE_MAX,
          f"the board cache is unbounded: {len(home_board._CACHE)}")
    home_board._CACHE.clear()


def scenario_the_url_still_beats_the_board():
    """`?widgets=` is how every existing Home Assistant card configures itself.
    A page must not take that away — the address a card was given is still the
    most specific thing in the system."""
    settings = {'panel_pages': [{'slug': 'home', 'name': 'Home', 'widgets': ['drives']}]}
    page = home_board.find_page('home', settings)
    picked = home_board.resolve_instances('meals,chores', settings, page=page)
    check([w['type'] for w in picked] == ['meals', 'chores'],
          f"the URL lost to the stored board: {picked}")


def scenario_the_payload_carries_the_board_it_was_built_for():
    """End to end: ask `build` for a board and get THAT board's tiles on THAT
    board's grid. The failure this catches is the quiet one — a payload built
    from the right tiles and the wrong columns draws the hallway board at the
    kitchen's proportions, and nothing anywhere errors."""
    from services import storage
    real = storage.get_settings
    try:
        storage.get_settings = lambda: {'panel_pages': [
            {'slug': 'home', 'name': 'Home', 'widgets': ['drives'],
             'columns': 12, 'row_height': 240},
            {'slug': 'hallway', 'name': 'Hallway', 'icon': '🚪',
             'widgets': ['map', 'moments'], 'columns': 6, 'row_height': 320,
             'spans': {'map': {'cols': 6, 'rows': 2}},
             'background': 'https://example.test/hall.jpg'},
        ]}
        home_board._CACHE.clear()
        board = home_board.build(page='hallway')
        check(board['columns'] == 6 and board['row_height'] == 320,
              f"the hallway board was drawn on another board's grid: "
              f"{board['columns']}x{board['row_height']}")
        check(board['spans'] == {'map': {'cols': 6, 'rows': 2}},
              f"the board's tile sizes did not travel: {board['spans']}")
        check(board['page'] == {'slug': 'hallway', 'name': 'Hallway', 'icon': '🚪'},
              f"the payload does not say which board it is: {board.get('page')}")
        check(board['background'] == 'https://example.test/hall.jpg',
              f"the board's own picture was not used: {board['background']!r}")
        check(all(t['type'] in ('map', 'moments') for t in board['tiles']),
              f"a board drew tiles from another board: "
              f"{[t['type'] for t in board['tiles']]}")

        # And the two boards must not share a cached answer.
        home_board._CACHE.clear()
        home = home_board.build(page='home')
        again = home_board.build(page='hallway')
        check(home['columns'] == 12 and again['columns'] == 6,
              f"one board served the other from cache: {home['columns']} / "
              f"{again['columns']}")
    finally:
        storage.get_settings = real
        home_board._CACHE.clear()


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} board-page scenarios passed")
