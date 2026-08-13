"""Every kiosk page is a board.

The panel shelf's buttons opened the ADMIN page. Tap Errands on a wall panel
and you got the page whose top half is a task editor, an owner dropdown, a
recurrence select and a natural-language errand parser — on a screen with no
keyboard, mounted where every child in the house can reach it. Same story for
Routines (a form per member) and, less dramatically, for every other
destination: the page a browser wants and the page a wall wants are not the
same page, and only one of them was being served.

So each destination has a BOARD, shipped in `home_board.BUILTIN_PAGES`, and
`?panel=true` on that destination draws it. The things this file is defending:

  * the address does not change, so a wall bookmarked on /errands?panel=true
    gets the better screen without anybody re-pointing a tablet;
  * a browser, and the older `?kiosk=true` surfaces, are untouched;
  * nothing is written to settings until somebody edits one — which is what
    lets these boards keep improving for households that never open the editor;
  * once edited, the household's version wins and the shipped one is gone until
    they reset it;
  * a destination's board never appears on the shelf a SECOND time as "a board
    somebody made".

Run from chauffeur/:  python tests/test_builtin_boards.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_builtin_'))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, 'templates')

import tpl_source  # noqa: E402
from services import home_board  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_every_shelf_destination_has_a_board():
    """A shelf button that opens an admin page is the bug. Intake is the one
    deliberate exception — it is mail approval and IMAP settings, and the kiosk
    rule has always been to keep it off shared screens."""
    missing = [s for s in home_board.NAV_SLUGS
               if s not in ('home', 'intake')
               and s not in home_board.BUILTIN_PAGES]
    check(not missing, f"these destinations still open their admin page on a "
                       f"wall panel: {missing}")
    check('intake' not in home_board.BUILTIN_PAGES,
          "the intake page grew a board, and it is an admin surface")
    check('home' not in home_board.BUILTIN_PAGES,
          "home is the household's own board, not a shipped one")


def scenario_a_shipped_board_is_a_real_board():
    """Every one of them goes through the same normaliser a stored page does,
    so a typo in the spec is a broken wall rather than a crash somewhere later.
    Tiles must be real types, spans must fit the grid, and nothing may arrive
    carrying the v1 chrome migration."""
    known = {w['key'] for w in home_board.WIDGETS}
    for slug in home_board.BUILTIN_PAGES:
        page = home_board.builtin_page(slug, {})
        check(page and page['slug'] == slug,
              f"{slug} did not resolve to its own board: {page}")
        check(page['widgets'], f"{slug}'s board has no tiles on it")
        for w in page['widgets']:
            check(w['type'] in known,
                  f"{slug} names a tile type that does not exist: {w['type']}")
            span = page['spans'].get(w['id']) or {}
            check(span.get('cols', 1) <= page['columns'],
                  f"{slug}'s {w['id']} is wider than the board: {span}")
        types = [w['type'] for w in page['widgets']]
        check('clock' not in types and 'hero' not in types,
              f"{slug} picked up the v1 chrome migration: {types}")
        check(page['v'] == 5, f"{slug} is not on the current page shape")


def scenario_every_card_in_the_catalog_has_something_drawing_it():
    """The failure mode of adding a card type: the builder ships, the option
    list ships, the picker offers it — and the tile draws an empty panel,
    because nothing in the board's body branches on it. Silent, and only
    visible on a wall.

    `custom` is the one exception: it is the CONTAINER, and its cells are
    drawn by home.html's own loop rather than by a type branch.
    """
    src = tpl_source.read('home.html')
    for w in home_board.WIDGETS:
        if w['key'] == 'custom':
            continue
        check(f"t.type === '{w['key']}'" in src,
              f"the {w['key']} card is offered in the picker and drawn by "
              f"nothing — a tile of it is an empty panel")
        check(w['key'] in home_board._BUILDERS,
              f"the {w['key']} card has no builder, so it never reaches a board")


def scenario_the_spec_is_never_handed_out():
    """`BUILTIN_PAGES` is module state and `_page_from` hands its spans dict to
    whoever asked. One caller resizing a tile would otherwise resize it for
    every household on the install, for the life of the process."""
    a = home_board.builtin_page('errands', {})
    first = a['widgets'][0]['id']
    a['spans'][first] = {'cols': 1, 'rows': 1}
    a['widgets'][0]['config']['count'] = 99
    b = home_board.builtin_page('errands', {})
    check(b['spans'][first] != {'cols': 1, 'rows': 1},
          f"editing one copy of a shipped board edited the spec: {b['spans']}")
    check(b['widgets'][0]['config'].get('count') != 99,
          f"a tile's config leaked back into the spec: {b['widgets'][0]}")


def scenario_stored_wins_and_nothing_is_stored_until_they_edit():
    """The whole bargain. A household that never opens the editor tracks
    whatever ships; the moment they save one it is theirs and the shipped board
    stops applying — no merging, because a board half theirs and half ours is a
    board nobody can explain."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives'], 'v': 5},
    ]}
    shipped = home_board.find_page('errands', settings)
    check([w['type'] for w in shipped['widgets']] == ['task_list', 'errand_list'],
          f"the shipped errands board was not used: {shipped['widgets']}")

    theirs = {'panel_pages': settings['panel_pages'] + [
        {'slug': 'errands', 'name': 'Errands', 'widgets': ['errands'],
         'columns': 6, 'v': 5},
    ]}
    got = home_board.find_page('errands', theirs)
    check([w['type'] for w in got['widgets']] == ['errands'],
          f"a household's own errands board lost to the shipped one: {got}")
    check(got['columns'] == 6, f"their grid was overridden: {got['columns']}")

    # And reading never writes: the same lazy rule the rest of this layer has.
    before = dict(theirs)
    home_board.find_page('chores', theirs)
    home_board.own_boards(theirs)
    check(theirs == before, "resolving a shipped board rewrote the settings")


def scenario_a_destination_s_board_is_not_a_second_shelf_button():
    """The failure this prevents is visible and silly: edit the Errands board
    once, and the shelf grows a second Errands button beside the first one —
    same screen, different icon, and the editor asking which you meant."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives'], 'v': 5},
        {'slug': 'errands', 'name': 'Errands', 'widgets': ['errands'], 'v': 5},
        {'slug': 'hallway', 'name': 'Hallway', 'widgets': ['map'], 'v': 5},
    ]}
    own = [p['slug'] for p in home_board.own_boards(settings)]
    check(own == ['hallway'],
          f"a destination's own board is being offered as a custom one: {own}")
    tabs = home_board.resolve_tabs(None, settings)
    check('board:errands' not in tabs,
          f"the shelf grew a second Errands button: {tabs}")
    check('errands' in tabs and 'board:hallway' in tabs,
          f"the shelf lost a destination or a real board: {tabs}")
    # The still-reachable half: the page's own button is what opens it.
    check(home_board.resolve_tabs('board:errands', settings) != ['board:errands'],
          "an unknown board slug produced a button that goes nowhere")


def scenario_the_editor_can_reach_a_board_nobody_has_saved():
    """A board you cannot find in the editor's list is a board you cannot fix,
    and the first thing anybody wanted to do with these was fix their heights.

    So `/api/home_board/pages` answers with TWO lists: `pages` is what is
    stored and `shipped` is the rest. Folding them into one would have the
    editor write all ten into settings the first time somebody nudged a tile,
    freezing every board this app will ever improve — which is the whole
    bargain these are offered under.
    """
    from services import storage
    real = storage.get_settings
    try:
        storage.get_settings = lambda: {'panel_pages': [
            {'slug': 'home', 'name': 'Home', 'widgets': ['drives'], 'v': 5},
            {'slug': 'errands', 'name': 'Errands', 'widgets': ['errands'],
             'v': 5},
        ]}
        stored = [p['slug'] for p in home_board.normalize_pages()]
        check(stored == ['home', 'errands'],
              f"the shipped boards leaked into the stored list: {stored}")
        import main
        got = main.home_board_pages()
        shipped = [p['slug'] for p in got['shipped']]
        check([p['slug'] for p in got['pages']] == ['home', 'errands'],
              f"the stored list changed shape: {got['pages']}")
        check('chores' in shipped and all(p['widgets'] for p in got['shipped']),
              f"the editor cannot see an unsaved board: {shipped}")
        # A board they HAVE customised must not appear twice — once as theirs
        # and once as ours, with the editor asking which they meant.
        check('errands' not in shipped,
              f"a customised board is listed as shipped as well: {shipped}")
        cat = home_board.catalog()
        check('errands' in (cat.get('builtin_pages') or []),
              f"the editor cannot tell a shipped board from a made one: "
              f"{cat.get('builtin_pages')}")
    finally:
        storage.get_settings = real


def scenario_an_unknown_slug_still_lands_on_a_real_board():
    """Unchanged, and it has to stay that way: the address that produces one is
    a wall panel's bookmark for a board somebody deleted."""
    settings = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'widgets': ['drives'], 'v': 5}]}
    for asked in ('kitchen', '', None, '../etc/passwd', 'intake'):
        got = home_board.find_page(asked, settings)
        check(got['slug'] == 'home',
              f"asking for {asked!r} did not land on a real board: {got['slug']}")
    # And the app's own destinations are case-folded like every other slug.
    check(home_board.find_page('ERRANDS', settings)['slug'] == 'errands',
          "a shipped board could not be found by a shouted slug")


def scenario_only_panel_mode_takes_the_board():
    """Three doors, and each one has to keep working. A browser gets the page
    it always got — the editors are the whole reason that page exists. The
    older `?kiosk=true` surfaces (chores, shopping, trips) answer as they did,
    because a board replacing a family's daily kiosk before anybody has stood
    in front of it is not a migration, it is a surprise."""
    src = open(os.path.join(ROOT, 'main.py'), encoding='utf-8').read()
    fn = src[src.index('def _page_or_board('):]
    fn = fn[:fn.index('\n# --- UI Routes')]
    check("query_params.get('panel') == 'true'" in fn,
          "the board is served on something other than panel mode")
    check('BUILTIN_PAGES' in fn,
          "the route decides for itself which destinations have a board")
    check('kiosk' not in fn.split('"""')[2],
          "?kiosk=true was folded into panel mode, which retires a family's "
          "daily surface without anybody having looked at the new one")

    # Every destination with a board actually routes through it.
    for slug in home_board.BUILTIN_PAGES:
        check(re.search(r'_page_or_board\(request,\s*"%s"' % slug, src),
              f"/{slug} still serves its admin page to a wall panel")


def scenario_the_board_knows_which_board_it_is():
    """`/errands?panel=true` renders the board template at an address with no
    `/board/` in it. Reading the slug out of the URL — which is all the page
    could do before — finds nothing there and quietly draws HOME instead, on
    every destination, which looks exactly like the feature not shipping."""
    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    check('data-board-slug="{{ board_slug' in tpl,
          "the server never tells the board which board it is")
    block = tpl[tpl.index('pageSlug: (function'):]
    block = block[:block.index('})(),')]
    check('boardSlug' in block,
          "the board still guesses its own slug from the address")
    check('location.pathname' in block,
          "the /board/<slug> route lost the only place its slug is written")
    # And it must stay OUT of the script: the jsdom harnesses run that block as
    # plain JavaScript, so a Jinja expression in it is a syntax error that takes
    # every board runtime test down at once.
    body = next(b for b in re.findall(r'<script>(.*?)</script>', tpl, re.S)
                if 'function homeBoard()' in b)
    check('{{' not in body and '{%' not in body,
          "server-side templating leaked into the board script")
    # And the editor has to list a board that is not in settings, while
    # writing back only the ones that changed.
    check('pg.shipped' in tpl,
          "the editor no longer lists the boards nobody has saved yet")
    check('_shippedPristine' in tpl,
          "the editor saves every shipped board on the first save, which "
          "freezes all of them against anything this app ships later")
    check('isBuiltinPage' in tpl,
          "the editor calls resetting a shipped board 'Delete'")

def scenario_a_list_is_as_tall_as_its_list():
    """`rows` is a promise about height, and for a list it is a promise nobody
    can keep: four children with eleven routine items each is a different
    height every morning. Every one of these boards shipped with a typed number
    and every one of them cut its content off on a real wall.

    So the list-shaped tiles say `auto` and the client measures them. The ones
    whose content is laid out INTO the tile — a map, a timeline, a mosaic —
    keep a stated `rows`, because there the height decides the content.
    """
    laid_in = {'map', 'drives', 'calendar', 'trips', 'moments'}
    for slug, spec in home_board.BUILTIN_PAGES.items():
        page = home_board.builtin_page(slug, {})
        for w in page['widgets']:
            span = page['spans'].get(w['id']) or {}
            if w['type'] in laid_in:
                check(span.get('rows'),
                      f"{slug}'s {w['type']} has no height, and its content "
                      f"cannot supply one")
                check(not span.get('auto'),
                      f"{slug}'s {w['type']} is set to fit, which collapses a "
                      f"tile whose content is drawn into it")
            else:
                check(span.get('auto'),
                      f"{slug}'s {w['type']} is a list on a typed height — it "
                      f"will cut its content off or leave a band of empty panel")


def scenario_fit_to_content_is_measured_not_guessed():
    """CSS cannot do this alone: the lattice is 1px tracks, so a grid item with
    no row span occupies one of them and "as tall as the content" has to become
    a number. The measurement reads the CHILDREN, never the tile's own box —
    the tile stretches to the area it was given, so measuring it would report
    whatever was last set and could never shrink again."""
    tpl = tpl_source.read('home.html')
    check('function autoTileHeight' in tpl,
          "nothing measures a fit-to-content tile")
    # What it measures — which elements, and how — is pinned against a tile
    # shaped like a real one in tests/test_fit_to_content.py. jsdom does no
    # layout, so only that harness can tell a measurement that reads the right
    # elements from one that reads the wrong ones.
    check('function autoFlowEls' in tpl,
          "the measurement no longer walks for the content, so a `display: "
          "contents` wrapper or a hidden control is being measured instead")
    # Both observers, because content arrives two different ways: these cards
    # self-fetch (mutation) and the board is responsive (resize).
    check('new ResizeObserver' in tpl and 'new MutationObserver' in tpl,
          "a fit-to-content tile only notices one of the two ways its content "
          "can change, so it is right on the first paint and wrong after")
    # And the arithmetic is the lattice's: pixels plus one gutter, same as a
    # tile sized in rows, so an auto tile sits in a row of fixed ones.
    span = tpl[tpl.index('spanStyle(key, type) {'):]
    span = span[:span.index(chr(10) + '                },')]
    check('this.gapPx()' in span and 'autoPx' in span,
          "an auto tile does not spend its pixels on the same lattice as the "
          "tiles beside it")


def scenario_a_board_never_loses_the_card_it_is_about():
    """Rule 1 hides a feature nobody has set up. That is right on a mixed board
    and wrong on a board ABOUT that feature: an Errands board with no errands
    card is a half-empty screen that reads as broken, which is exactly how it
    reached a wall."""
    from services import storage
    real_e, real_t = storage.get_all_errands, storage.get_household_tasks
    try:
        storage.get_all_errands = lambda: []
        storage.get_household_tasks = lambda **kw: []
        home_board._CACHE.clear()
        board = home_board.build(page='errands')
        types_ = [t['type'] for t in board['tiles']]
        check(types_ == ['task_list', 'errand_list'],
              f"the errands board lost a card it is about: {types_}")
        for t in board['tiles']:
            said = (t['cards'][0]['data'] or {}).get('empty')
            check(said, f"{t['type']} is present but says nothing: {t}")
    finally:
        storage.get_all_errands, storage.get_household_tasks = real_e, real_t
        home_board._CACHE.clear()
    # `require` is the shipped boards' alone — a household's own board is a mix,
    # where hiding an unused feature is still the right answer.
    for spec in home_board.BUILTIN_PAGES.values():
        for w in spec['widgets']:
            check(w.get('require'),
                  f"{w['type']} on a shipped board can still vanish")


def scenario_the_kids_strip_survives_a_board_with_no_hero():
    """The digest is folded into the hero band on the home board. The Routines
    board has no hero — it is lanes, not drives — so the fold dropped the tile
    into an object nothing on that page draws, and it vanished with no error
    anywhere."""
    home_board._CACHE.clear()
    digest = lambda: {'label': 'Today', 'kids': {
        'k1': {'name': 'Addison', 'lines': ['5:00 PM — practice']}}}
    board = home_board.build(page='routines', kid_digest_fn=digest)
    check(any(t['type'] == 'kids' for t in board['tiles']),
          f"the routines board lost its kid strip: "
          f"{[t['type'] for t in board['tiles']]}")
    home_board._CACHE.clear()

def scenario_the_calendar_card_is_the_page_so_it_taps_like_the_page():
    """`?panel=true` on /calendar serves the BOARD, which makes the calendar
    card the calendar page's content — and the page's one irreplaceable tap is
    opening an event. The card mounts the same component the page does, so
    interactivity is the two mount options the board used to hardcode off:
    `details` (the shared dialog behind every event tap) and `legend` (the
    per-person chips). Overlay in place, never a navigation.
    """
    # The builder resolves the options; the paradigm default is ON.
    import datetime
    now = datetime.datetime(2026, 8, 13, 12, 0)
    t = home_board._tile_calendar(now, sched={}, config={'view': 'agenda'})
    check(t.get('interactive') is True and t['grid'].get('details') is True,
          f"a calendar card nobody configured came up inert: {t}")
    check(t['grid'].get('legend') is True,
          f"the legend did not follow the paradigm default: {t['grid']}")
    off = home_board._tile_calendar(now, sched={},
                                    config={'view': 'month',
                                            'interactive': False,
                                            'show_legend': False})
    check(off.get('interactive') is False
          and off['grid'].get('details') is False
          and off['grid'].get('legend') is False,
          f"display-only did not stick: {off}")

    tpl = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    # The mount passes both through instead of hardcoding them off…
    sync = tpl[tpl.index('async syncCalendars()'):]
    sync = sync[:sync.index('async syncMap()')]
    check('details: !!g.details' in sync and 'legend: !!g.legend' in sync,
          "syncCalendars still hardcodes the page's affordances off")
    # …and remounts when a card's CONFIG changes, not only when its id is new —
    # without this, toggling interactive (or changing the view) in the editor
    # did nothing until a full page reload.
    check('JSON.stringify(g)' in sync,
          "a calendar card's config change is ignored until a reload")

    # An interactive calendar is NOT a door: its events open a dialog, and an
    # <a> around them would navigate mid-overlay. Display-only stays a door.
    opens = tpl[tpl.index('opens(t) {'):]
    opens = opens[:opens.index(chr(10) + '                },')]
    check("t.type === 'calendar'" in opens and 'interactive' in opens,
          "an interactive calendar tile is still an <a> around its events")

    # And the shipped calendar board needs no config to get all of it.
    page = home_board.builtin_page('calendar', {})
    cfg = page['widgets'][0]['config']
    check(cfg.get('interactive') is None,
          f"the shipped board hardcodes what the default already says: {cfg}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} builtin-board scenarios passed")
