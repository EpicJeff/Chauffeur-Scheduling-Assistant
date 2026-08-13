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
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_pages_'))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')

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
    ids = [w['id'] for w in home['widgets']]
    # A v1 board was DRAWN under the clock strip and the hero band — template
    # chrome, above the grid. v2 made them tiles, so the upgrade keeps the
    # wall looking like itself by making them the first two tiles.
    check(ids[:2] == ['clock', 'hero'],
          f"a v1 board did not keep its chrome as tiles: {ids}")
    check(ids[2:] == ['calendar', 'calendar-2', 'drives', 'map'],
          f"the tiles or their ORDER changed on upgrade: {home['widgets']}")
    check(home['widgets'][2]['config'] == {'days': 7},
          "a tile's configuration was dropped on upgrade")
    own = {k: v for k, v in home['spans'].items() if k not in ('clock', 'hero')}
    check(own == LEGACY['panel_tile_spans'],
          f"tile sizes did not survive: {home['spans']}")
    check(home['spans']['clock'] == {'cols': 16, 'rows': 1},
          f"the migrated chrome is not full width: {home['spans']}")
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
         'columns': 8, 'row_height': 300, 'v': 2},
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
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives'], 'v': 2},
        {'slug': 'hallway', 'name': 'Hallway', 'widgets': [], 'v': 2},
    ]}
    hallway = home_board.find_page('hallway', settings)
    check(hallway['widgets'] == [],
          f"a new board filled itself with defaults: {hallway['widgets']}")
    board = home_board.resolve_instances(None, settings, page=hallway)
    check(board == [], f"an empty board resolved to something: {board}")


def scenario_a_v1_board_keeps_its_chrome_and_a_v2_board_means_what_it_says():
    """The clock strip and the hero band were template chrome until v2.209 —
    drawn above the grid on EVERY board, unconditionally. As tiles they are
    optional, so the upgrade has to preserve what each stored board was
    actually showing: a v1 board (no `v`) gets both prepended full width; a
    v2 board is exactly its own list, chrome or no chrome."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives']},
        {'slug': 'blank', 'name': 'Blank', 'widgets': [], 'v': 2},
    ]}
    v1 = home_board.find_page('home', settings)
    check([w['type'] for w in v1['widgets']] == ['clock', 'hero', 'drives'],
          f"a v1 board lost the chrome it was drawn under: {v1['widgets']}")
    check(v1['spans'].get('clock') == {'cols': 12, 'rows': 1}
          and v1['spans'].get('hero') == {'cols': 12, 'rows': 1},
          f"the migrated chrome is not full width: {v1['spans']}")
    check(v1['v'] == 2, "a normalised page does not say which shape it is")
    v2 = home_board.find_page('blank', settings)
    check(v2['widgets'] == [],
          f"a v2 board grew chrome nobody asked for: {v2['widgets']}")
    # Migrating a board that already HAS a clock must not add a second one.
    twice = home_board.normalize_pages({'panel_pages': [
        {'slug': 'home', 'name': 'Home',
         'widgets': [{'id': 'clock', 'type': 'clock'}, 'drives']},
    ]})[0]
    check([w['type'] for w in twice['widgets']] == ['clock', 'hero', 'drives'],
          f"migration doubled the chrome: {twice['widgets']}")


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
             'columns': 12, 'row_height': 240, 'v': 2},
            {'slug': 'hallway', 'name': 'Hallway', 'icon': '🚪',
             'widgets': ['map', 'moments'], 'columns': 6, 'row_height': 320,
             'spans': {'map': {'cols': 6, 'rows': 2}},
             'background': 'https://example.test/hall.jpg', 'v': 2},
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


def scenario_a_board_is_reachable_from_a_wall_panel():
    """A board nobody can tap is a board that does not exist. The shelf lists
    the household's own boards ahead of the app's pages — a board is something
    somebody made on purpose for this wall, and nothing the app ships has a
    stronger claim on the first buttons than that."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives'], 'v': 2},
        {'slug': 'hallway', 'name': 'Hallway', 'icon': '🚪', 'widgets': ['map'],
         'v': 2},
    ]}
    rows = home_board.page_summaries(settings)
    check([r['slug'] for r in rows] == ['home', 'hallway'],
          f"the shelf cannot see every board: {rows}")
    check(rows[1]['icon'] == '🚪' and rows[1]['name'] == 'Hallway',
          f"a board reached the shelf without its own name or icon: {rows[1]}")
    check(rows[1]['tiles'] == 1, f"the summary lost the tile count: {rows[1]}")
    check(not any('widgets' in r for r in rows),
          "the shelf is being sent every tile on every board, which is the "
          "expensive half of the payload and the half it does not use")


def scenario_a_board_survives_the_panel_asking_what_it_shows():
    """The bug that shipped in v2.189.0, and the reason it hid.

    A panel with no `?tabs=` asks `/api/panel/profile` what it shows and then
    HIDES every shelf button the answer does not name. Boards were rendered
    into the shelf server-side but were not in that answer, so they appeared
    for a fraction of a second on every load and then vanished — and panel mode
    is the only place the shelf exists, so it was the only place it showed.

    The v2.189.0 tests checked `resolve_tabs('home,board:chores')` — the
    EXPLICIT path — and never the default one the wall actually takes.
    """
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives']},
        {'slug': 'hallway', 'name': 'Hallway', 'widgets': ['map']},
        {'slug': 'kitchen', 'name': 'Kitchen', 'widgets': ['meals']},
    ]}
    # No URL param: the wall's own case.
    tabs = home_board.resolve_tabs(None, settings)
    for slug in ('board:hallway', 'board:kitchen'):
        check(slug in tabs,
              f"{slug} is missing from the panel profile, so the shelf will "
              f"render it and then hide it: {tabs}")
    # Right after Home — the boards are one group, the app's pages another.
    check(tabs.index('board:hallway') == tabs.index('home') + 1,
          f"the boards are not grouped with Home: {tabs}")
    check(tabs.index('board:hallway') < tabs.index('board:kitchen'),
          f"board order is shelf order, and it was not kept: {tabs}")

    # (A shelf somebody has curated is a different case and stays exactly as
    # they left it — see scenario_a_curated_shelf_is_left_alone.)

    # And the profile — which is what the panel actually reads — agrees.
    from services import storage
    real = storage.get_settings
    try:
        storage.get_settings = lambda: settings
        prof = home_board.profile()
        check('board:hallway' in prof['tabs'],
              f"the profile the panel reads has no boards in it: {prof['tabs']}")
    finally:
        storage.get_settings = real


def scenario_an_explicit_tabs_list_is_still_exactly_what_was_asked_for():
    """The other half. A Home Assistant card that says `?tabs=home,chores`
    wants two buttons; quietly adding the household's boards would make that
    card unconfigurable."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives']},
        {'slug': 'hallway', 'name': 'Hallway', 'widgets': ['map']},
    ]}
    check(home_board.resolve_tabs('home,chores', settings) == ['home', 'chores'],
          "an explicit tabs list picked up boards nobody asked for")
    check(home_board.resolve_tabs('', settings) == [],
          "?tabs= (no chrome at all) stopped meaning that")


def scenario_the_shelf_editor_can_reach_the_boards():
    """The hand path. Boards being on the shelf by default is only half of it —
    a household that wants their hallway board FIRST, or does not want the
    kitchen one there at all, has to be able to say so in the same list they
    already order the app's destinations in."""
    from services import storage
    real = storage.get_settings
    try:
        storage.get_settings = lambda: {'panel_pages': [
            {'slug': 'home', 'name': 'Home', 'widgets': ['drives']},
            {'slug': 'hallway', 'name': 'Hallway', 'icon': '🚪', 'widgets': []},
        ]}
        cat = home_board.catalog()
        board = next((t for t in cat['tabs'] if t['slug'] == 'board:hallway'), None)
        check(board, f"the shelf editor cannot offer a board: {cat['tabs']}")
        check(board['label'] == 'Hallway' and board['icon'] == '🚪',
              f"a board reached the editor without its name or icon: {board}")
        check(board['kind'] == 'board',
              "a board and a page are indistinguishable in the editor's list, "
              "and they are not the same thing to arrange")
        check(all(t.get('kind') for t in cat['tabs']),
              "some shelf entries do not say which kind they are")
        # The defaults shown are the ones the panel would ACTUALLY use, so an
        # untouched shelf and the picker agree about what is on it.
        check('board:hallway' in cat['tab_defaults'],
              f"the editor's idea of an untouched shelf omits the boards: "
              f"{cat['tab_defaults']}")
    finally:
        storage.get_settings = real


def scenario_a_curated_shelf_is_left_alone():
    """Once somebody has picked their buttons, that list IS the shelf. Helpfully
    re-adding a board they removed would make the ✕ beside it do nothing, which
    is worse than the board being absent."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives']},
        {'slug': 'hallway', 'name': 'Hallway', 'widgets': ['map']},
    ], 'panel_tabs': ['home', 'chores']}
    check(home_board.resolve_tabs(None, settings) == ['home', 'chores'],
          "a board was added back to a shelf somebody had curated")
    # And a curated shelf can put a board wherever it likes.
    ordered = dict(settings, panel_tabs=['board:hallway', 'home'])
    check(home_board.resolve_tabs(None, ordered) == ['board:hallway', 'home'],
          "a curated shelf could not put a board first")


def scenario_the_shelf_renders_one_list_not_two():
    """Two loops over two orders is how the boards ended up in a position the
    profile did not know about. The shelf builds from ONE order that holds both
    kinds, so what is rendered and what the panel keeps cannot diverge."""
    tpl = open(os.path.join(TPL, 'nav.html'), encoding='utf-8').read()
    shelf = tpl[tpl.index('id="panel-shelf-items"'):]
    shelf = shelf[:shelf.index('panel-shelf-more')]
    check(shelf.count('{% for slug in _order %}') == 1,
          "the shelf is no longer built from a single order")
    check('shelf_boards(request)' in tpl,
          "the shelf cannot resolve a board slug to a board")


def scenario_a_board_can_be_named_in_a_tabs_filter():
    """`?tabs=` is how an HA card says what chrome it wants. Boards join that
    vocabulary PREFIXED, so a board somebody names "Chores" cannot quietly
    shadow the Chores page."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives']},
        {'slug': 'chores', 'name': 'Chores', 'widgets': ['map']},
    ]}
    picked = home_board.resolve_tabs('home,board:chores', settings)
    check(picked == ['home', 'board:chores'],
          f"a board could not be named in a tabs filter: {picked}")
    # The page and the board are different destinations with similar names.
    check(home_board.resolve_tabs('chores', settings) == ['chores'],
          "a board shadowed the app's own page of the same name")
    # An unknown board name is dropped, which empties the request and falls
    # back to the household's own shelf — boards included, since that is now
    # what the default IS.
    fallback = home_board.resolve_tabs('board:nope', settings)
    check('board:nope' not in fallback,
          f"a board that does not exist produced a button that goes nowhere: "
          f"{fallback}")
    check(fallback == home_board.resolve_tabs(None, settings),
          f"an all-unknown request did not fall back to the household's shelf: "
          f"{fallback}")


def scenario_every_nav_link_survives_a_two_segment_route():
    """`/board/{slug}` is the first route in this app that is two path segments
    deep. Every link in the nav is relative, so a bare `href="chores"` from a
    board resolves to `/board/chores` and the whole nav goes nowhere — while
    still looking perfectly fine in the markup."""
    tpl = open(os.path.join(TPL, 'nav.html'), encoding='utf-8').read()
    hrefs = re.findall(r'<a\s+href="([^"]*)"', tpl)
    check(hrefs, "no links found in nav.html — the check itself is broken")
    for href in hrefs:
        check(href.startswith('{{ _up }}') or href.startswith('#')
              or '://' in href,
              f"nav link {href!r} is not depth-aware, so it breaks on /board/*")
    # And the climb must be counted against the one-segment case, never from
    # the root: under ingress the path carries /api/hassio_ingress/<token>/ in
    # front of everything, and climbing out of that leaves the add-on.
    check("'/board/' in _path" in tpl,
          "the nav decides its depth some other way than 'am I on a board'")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} board-page scenarios passed")
