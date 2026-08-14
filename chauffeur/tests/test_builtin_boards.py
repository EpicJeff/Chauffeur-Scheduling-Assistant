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
    may not: there the height decides the content, so they take a stated
    `rows` or, since v2.225.0, `fill`.

    `fill` is the third answer and it is the right one for a single-subject
    board: the tile runs from where it lands down to the shelf, on any
    display. It is legal for BOTH shapes — it hands the tile a height, which
    is exactly what content that cannot fit is asking for — so the only thing
    still forbidden is a laid-in tile set to `auto`, which collapses it.
    """
    laid_in = {'map', 'drives', 'calendar', 'trips', 'moments',
               'moments_gallery'}
    for slug, spec in home_board.BUILTIN_PAGES.items():
        page = home_board.builtin_page(slug, {})
        for w in page['widgets']:
            span = page['spans'].get(w['id']) or {}
            if w['type'] in laid_in:
                check(span.get('rows') or span.get('fill'),
                      f"{slug}'s {w['type']} has no height, and its content "
                      f"cannot supply one")
                check(not span.get('auto'),
                      f"{slug}'s {w['type']} is set to fit, which collapses a "
                      f"tile whose content is drawn into it")
            else:
                check(span.get('auto') or span.get('fill'),
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
    span = tpl[tpl.index('spanStyle(key, type, config) {'):]
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


def scenario_the_other_cards_with_taps_have_them_too():
    """The calendar card earned `interactive` first; three more cards had taps
    worth having and no way to switch them on.

      * Drives — the timeline's event blocks have carried an onclick since
        before this board existed, and the board had nowhere to send it, so
        every drive on the wall was inert.
      * Moments — a mosaic of thumbnails whose only affordance was "leave for
        the gallery" is a worse version of tapping the photo you are looking
        at.
      * Map — the one map in this app you could not pan.

    Defaults follow the paradigm (on where there are taps) with the map as the
    deliberate exception: panning is the only interaction here that PERSISTS,
    and on a wall panel nobody owns the pan.
    """
    import datetime
    now = datetime.datetime(2026, 8, 13, 12, 0)

    keys = {w['key']: w for w in home_board.WIDGETS}
    for key, default in (('drives', True), ('moments', True), ('map', False)):
        opt = next((o for o in keys[key]['options'] if o['key'] == 'interactive'),
                   None)
        check(opt is not None, f"the {key} card cannot be made interactive")
        check(opt['default'] is default,
              f"the {key} card's interactive default is {opt['default']}, "
              f"not {default}")

    # It reaches the payload, which is what the door logic and the renderers
    # read — an option the builder drops is an option that does nothing.
    tile = home_board._tile_drives(now, runs=[], sched={'events': [1]},
                                   config={'view': 'list'})
    check(tile.get('interactive') is True or tile.get('empty'),
          f"a Drives card nobody configured came up inert: {tile}")
    off = home_board._tile_drives(now, runs=[], sched={'events': [1]},
                                  config={'view': 'list', 'interactive': False})
    check(off.get('interactive') is False or off.get('empty'),
          f"display-only did not stick on the Drives card: {off}")

    tpl = tpl_source.read('home.html')
    # Interactive content is never ALSO a door: an <a> around a tap that opens
    # an overlay navigates out from under it.
    opens = tpl[tpl.index('opens(t) {'):]
    opens = opens[:opens.index(chr(10) + '                },')]
    check('INTERACTIVE_TILES' in opens,
          "an interactive drives/map/moments tile is still an <a> around its "
          "own taps, so every tap navigates mid-overlay")
    decl = tpl[tpl.index('INTERACTIVE_TILES:'):]
    decl = decl[:decl.index(']')]
    for key in ("'drives'", "'map'", "'moments'"):
        check(key in decl, f"{key} is interactive and still a door")

    # The Map BOARD is the exception to the exception: it is the map page, so
    # there is no door to protect and a map you cannot pan is a screenshot.
    page = home_board.builtin_page('map', {})
    check(page['widgets'][0]['config'].get('interactive') is True,
          f"the shipped Map board serves a map nobody can pan: {page['widgets']}")


def scenario_a_generic_tile_can_wear_its_own_icon():
    """Every entry in the catalog ships an emoji saying what KIND of thing it
    is, and for the generic ones that is all it can ever say: Custom, Card,
    Entities, Camera and Web page are 🧩 🃏 🏠 📷 🌐 whatever they were pointed
    at. A board with the back-door camera, the front-door camera and the radar
    on it was three tiles wearing the same 📷.

    Offered on EVERY type rather than those five, for the same reason `title`
    is: it means one thing everywhere, and a tile with a good default loses
    nothing by being able to override it.
    """
    cat = home_board.catalog()
    for w in cat['widgets']:
        check(any(o['key'] == 'icon' for o in w['options']),
              f"the {w['key']} tile cannot be given its own icon")

    import datetime
    now = datetime.datetime(2026, 8, 13, 12, 0)
    built = home_board._build_tile(
        {'id': 'w', 'type': 'heading', 'config': {'title': 'Ours', 'icon': '🚌'}},
        now)
    check(built['icon'] == '🚌',
          f"a typed icon never reached the wall: {built['icon']!r}")
    plain = home_board._build_tile(
        {'id': 'w', 'type': 'heading', 'config': {'title': 'Ours'}}, now)
    check(plain['icon'] == '🔤',
          f"a tile nobody re-iconed lost its own: {plain['icon']!r}")
    # A glyph slot, not a second title — but the cap has to clear a multi-code
    # -point emoji or a family renders as rubble.
    long_ = home_board._build_tile(
        {'id': 'w', 'type': 'heading',
         'config': {'title': 'Ours', 'icon': 'the back door camera'}}, now)
    check(len(long_['icon']) <= 8,
          f"an 'icon' that is a sentence pushes the title off the row: "
          f"{long_['icon']!r}")
    family = home_board._build_tile(
        {'id': 'w', 'type': 'heading',
         'config': {'title': 'Ours', 'icon': '\U0001f468‍\U0001f469‍\U0001f467'}},
        now)
    check(family['icon'] == '\U0001f468‍\U0001f469‍\U0001f467',
          f"a joined emoji was sliced in half: {family['icon']!r}")

    # And the EDITOR shows the override, or it can only be checked by walking
    # to the wall — which is the surface the icon exists to disambiguate.
    tpl = tpl_source.read('home.html')
    check('instanceIcon(w)' in tpl and 'instanceIcon(c)' in tpl,
          "the editor's rows still wear the type's emoji, so three cameras "
          "are three identical rows")


def scenario_the_moments_board_is_the_moments_page():
    """The last board still answering the wrong question.

    `moments` (the tile) and the Moments PAGE are two different drawings, and
    only one of them belongs on a board about moments. The tile is a GLANCE —
    a mosaic of the last few photos, right beside eight other tiles on a home
    board. The page is a two-level gallery: a block per ACTIVITY, tapping one
    opens that activity's photos, with a way back. `?panel=true` on /moments
    drew the mosaic, so a family walking up to the Moments screen got "here
    are six recent pictures" where the page says "here is every activity you
    have ever shared, pick one."

    This is the same trap as v2.221.0's kid digest, from the other direction:
    there a stale tile drawing had never been seen on a wall, here a perfectly
    good tile drawing was put on a wall that wanted a different one. **A tile
    that summarises a page is not a substitute for the page.**
    """
    page = home_board.builtin_page('moments', {})
    types = [w['type'] for w in page['widgets']]
    check(types == ['moments_gallery'],
          f"the Moments board is not the Moments page: {types}")
    check(page['widgets'][0].get('require'),
          "the Moments board can lose the only card it is about")
    # It pages on scroll, so a stated number of rows is an arbitrary window
    # onto a history that has no length. Fill is the honest answer.
    span = page['spans']['moments_gallery']
    check(span.get('fill') and not span.get('auto'),
          f"the gallery is not filling the screen it is the only thing on: {span}")

    # The GLANCE survives. It is the right card for a home board and the
    # conversion must not have quietly replaced it.
    keys = {w['key'] for w in home_board.WIDGETS}
    check('moments' in keys and 'moments_gallery' in keys,
          "the mosaic and the gallery are not both offered")

    # ONE drawing, in a component both callers mount — the page must not keep
    # a private copy, which is how a wall and a browser drift apart.
    gal = tpl_source.read('components/moments_gallery.html')
    check('window.MomentsGallery' in gal and 'function mount' in gal,
          "the gallery is not mountable, so only one surface can have it")
    # The RAW file, not `tpl_source.read` — that inlines includes, so the
    # component's own `renderEvents` would come back as the page's and this
    # assertion would pass while proving nothing.
    pagesrc = open(os.path.join(TPL, 'moments.html'), encoding='utf-8').read()
    check('MomentsGallery.mount' in pagesrc,
          "the Moments page draws its own gallery again")
    for gone in ('renderEvents', 'loadEventsPage', 'refreshEventInPlace'):
        check(gone not in pagesrc,
              f"the page kept its own {gone} — two gallery renderers is how "
              f"the wall and the browser start disagreeing")

    # The way back up belongs to the COMPONENT, not to whichever caller
    # remembered one. The page had a sticky bar; a card had nothing, so
    # drilling into an event on a wall panel was a one-way trip.
    check('All moments' in gal,
          "the gallery has no way back to the activities")
    board = tpl_source.read('home.html')
    check('board-moments-' in board and 'syncGalleries' in board,
          "nothing on the board mounts the gallery")
    # A board tile must never push history: the panel's back gesture would
    # undo a tap inside one card, and two gallery cards would fight over one
    # stack. The PAGE does push, so a phone's back swipe pops a level.
    sync = board[board.index('syncGalleries() {'):]
    sync = sync[:sync.index(chr(10) + '                },')]
    check('history: false' in sync,
          "a gallery card hijacks the browser's history")
    check('history: true' in pagesrc,
          "the Moments page stopped popping a level on the back gesture")
    # And it is not ALSO a door — its own taps are the point.
    check("'moments_gallery'" in board[board.index('INTERACTIVE_TILES:'):
                                       board.index('INTERACTIVE_TILES:') + 160],
          "an interactive gallery is still an <a> around its own taps")


def scenario_the_gallery_card_ships_config_not_history():
    """Rule 4: an interactive card self-fetches. This one has no choice — it
    is the family's whole history, two levels deep, paged on scroll, and none
    of that can ride in a board payload five other cards are waiting on.

    What the builder DOES owe is the one fact the client cannot answer for
    itself: whether this household has any moments at all. Rule 1 hides a
    feature nobody has set up, and by the time the component has fetched
    enough to know, it has already drawn an empty grid where a tile should not
    have been.
    """
    import datetime
    from services import presence
    now = datetime.datetime(2026, 8, 13, 12, 0)

    real = presence.moment_events
    try:
        presence.moment_events = lambda offset=0, limit=24: {'items': [], 'total': 0}
        check(home_board._tile_moments_gallery(now, config={}) is None,
              "a household with no moments is shown a gallery tile anyway")

        presence.moment_events = lambda offset=0, limit=24: {'items': [], 'total': 7}
        data = home_board._tile_moments_gallery(now, config={})
        check(data and data['events'] == 7,
              f"the builder did not report what it found: {data}")
        # No moments in the payload. If this ever carries `items`, the whole
        # history is being pushed through a 20-second cache.
        check('items' not in data and 'moments' not in data,
              f"the gallery card is shipping history in the board payload: {data}")
        check(data['interactive'] is True and data['lightbox'] is True,
              f"a gallery nobody configured came up inert: {data}")
        check(data['show'] == {'count': True, 'who': True, 'when': True,
                               'body': True, 'reactions': True},
              f"the conversion paradigm's defaults are not all on: {data['show']}")

        off = home_board._tile_moments_gallery(
            now, config={'interactive': False, 'show_who': False,
                         'tile_width': 400})
        check(off['interactive'] is False and off['show']['who'] is False
              and off['tile_width'] == 400,
              f"display-only and the toggles did not stick: {off}")
        # Clamped, not trusted: a stored 9999 would make one block per screen.
        wide = home_board._tile_moments_gallery(now, config={'tile_width': 9999})
        check(wide['tile_width'] == 600,
              f"the block width is unbounded: {wide['tile_width']}")
    finally:
        presence.moment_events = real


def scenario_a_boards_picture_is_the_boards_own_field():
    """Reported as "the field in the board settings appears to do absolutely
    nothing", and it did nothing for two separate reasons.

      * `builtin_page()` SET `background` from the legacy
        `panel_page_backgrounds` after building the page, so whatever the
        household had typed on the board was overwritten every single time.
      * `backgrounds()` — the map the panel actually applies through nav.html —
        was built straight from that legacy key and filtered to NAV_SLUGS. So a
        board's own `background` never entered into it at all, and a CUSTOM
        board (whose slug is not a nav slug) was not even in the map: on a wall
        it fell back to the household default, and the field appeared to work
        only in a browser, where home.html applies the board payload directly.

    The map is GONE rather than deprecated. There is one install of this app
    and nothing was stored under that key, so a compatibility path would only
    be a second way for this to go wrong again.
    """
    saved = {
        'panel_background': 'https://e/default.jpg',
        'panel_pages': [
            {'slug': 'home', 'name': 'Home', 'v': 5, 'widgets': [],
             'background': 'https://e/home-own.jpg'},
            {'slug': 'hallway', 'name': 'Hallway', 'v': 5, 'widgets': [],
             'background': 'https://e/hallway-own.jpg'},
            {'slug': 'chores', 'name': 'Chores', 'v': 5, 'widgets': [],
             'background': 'https://e/chores-own.jpg'},
        ],
    }
    # A board's own field survives the round trip, shipped-slug or not.
    for slug, want in (('hallway', 'https://e/hallway-own.jpg'),
                       ('chores', 'https://e/chores-own.jpg')):
        page = next(p for p in home_board.normalize_pages(saved)
                    if p['slug'] == slug)
        check(page['background'] == want,
              f"{slug} lost the picture set on the board: {page['background']}")
    # A shipped board nobody has edited has no picture of its own and takes
    # the household's — two levels of "not set", never three.
    check(home_board.builtin_page('map', saved)['background'] == '',
          "a shipped board invents a picture of its own")

    # THE MAP THE WALL APPLIES. Every board is in it, keyed by its own slug —
    # including the household's own, which were missing entirely.
    bg = home_board.backgrounds(saved)
    check(bg['default'] == 'https://e/default.jpg', f"the household default moved: {bg}")
    check(bg.get('hallway') == 'https://e/hallway-own.jpg',
          f"a custom board's picture never reaches the wall: {bg}")
    check(bg.get('home') == 'https://e/home-own.jpg',
          f"the home board's own picture is not in the map: {bg}")
    check(bg.get('chores') == 'https://e/chores-own.jpg',
          f"an edited destination board's picture is not in the map: {bg}")
    check('map' not in bg,
          f"a board with no picture is claiming one: {bg}")

    # And there is exactly ONE setting for this. The second one is gone from
    # the schema and the registry too, not just from the editor — a setting
    # nothing writes and nothing reads is a trap for the next person.
    import os
    for path in ('models/schemas.py', 'services/settings_registry.py',
                 'services/home_board.py'):
        src = open(os.path.join(ROOT, path), encoding='utf-8').read()
        # The NAME survives in prose explaining the removal, which is the
        # point of the prose. What must not survive is code: the key quoted
        # as a string, declared as a field, or assigned.
        for form in ("'panel_page_backgrounds'", '"panel_page_backgrounds"',
                     'panel_page_backgrounds:', 'panel_page_backgrounds ='):
            check(form not in src,
                  f"{path} still handles panel_page_backgrounds ({form})")

    # And the panel APPLIES the board's own answer, not only the profile map —
    # skipping it in panel mode was the other half of "it does nothing".
    tpl = tpl_source.read('home.html')
    load = tpl[tpl.index('async load() {'):]
    load = load[:load.index('this.recount();')]
    check('!this.isPanelMode) this.applyBackground' not in load
          and 'this.applyBackground();' in load,
          "the board's own picture is still skipped on a wall panel")
    # nav resolves /board/<slug>, or a custom board looks itself up under ''.
    nav = tpl_source.read('nav.html')
    fn = nav[nav.index('function currentSlug() {'):]
    fn = fn[:fn.index(chr(10) + '        }')]
    check("'board'" in fn,
          "nav cannot name a custom board, so every one of them falls back to "
          "the household's default picture")


def scenario_the_trips_board_is_the_trips_page():
    """Third board caught answering the wrong question, and the second of this
    exact shape (Moments was the first).

    `trips` is the GLANCE — the next trip and how long until it starts, as a
    small collage beside eight other tiles. The PAGE is a gallery you browse:
    a photograph per trip with its status, dates, where it is and how many
    stops are planned, each one opening that trip. `?panel=true` on /trips
    drew the collage, so the Trips screen was one trip block with no way into
    any of them.
    """
    page = home_board.builtin_page('trips', {})
    types = [w['type'] for w in page['widgets']]
    check(types == ['trips_gallery'],
          f"the Trips board is not the Trips page: {types}")
    span = page['spans']['trips_gallery']
    check(span.get('fill'),
          f"the gallery is not filling the screen it is the only thing on: {span}")
    keys = {w['key'] for w in home_board.WIDGETS}
    check('trips' in keys and 'trips_gallery' in keys,
          "the collage and the gallery are not both offered")

    # ONE drawing. The page must not keep a private card renderer.
    gal = tpl_source.read('components/trip_gallery.html')
    check('window.TripGallery' in gal and 'function render' in gal,
          "the gallery is not shared, so only one surface can have it")
    raw = open(os.path.join(TPL, 'trips.html'), encoding='utf-8').read()
    check('TripGallery.render' in raw, "the Trips page draws its own cards again")
    check('trip-card' not in raw,
          "the page kept its own card markup — two renderers is how a wall and "
          "a browser start disagreeing about what a trip looks like")

    # It rides the PAYLOAD, and that is a rule: the page's own /api/trips calls
    # Google Calendar and writes a snapshot on the way past, so a board polling
    # it every minute would keep the calendar warm and rewrite a cache for a
    # display nobody is looking at.
    board = tpl_source.read('home.html')
    sync = board[board.index('syncTripGalleries() {'):]
    sync = sync[:sync.index(chr(10) + '                },')]
    check('api/trips' not in sync,
          "the trips gallery card fetches the page's endpoint, which writes")
    check('tile.data.trips' in sync, "the card is not drawn from the payload")


def scenario_the_gallery_rows_carry_what_the_page_shows():
    """The card is only the page if the payload carries what the page draws.
    Two things were missing and both are visible from across a room: how many
    stops are planned, and a PICTURE — `_trip_rows` nulled anything that was
    not already a URL, while the page turned the same phrase into a photograph
    through the Unsplash endpoint that backs trip artwork.
    """
    import datetime
    from services import storage
    now = datetime.datetime(2026, 8, 14, 12, 0)

    real_cached = storage.get_cached_trips
    real_meta = storage.get_all_trip_metadata
    real_one = storage.get_trip_metadata
    real_sched = storage.get_cached_schedule
    try:
        storage.get_cached_trips = lambda: {'trips': [
            {'id': 't1', 'title': 'Disney World: spring', 'location': 'Orlando',
             'start': '2026-08-20', 'end': '2026-08-27',
             'background_url': 'disney world castle'},
            # FIVE MONTHS ago — the case the report was actually about. A
            # family's past trips are seasons back, and until the look-back
            # became a year this one could not be known by any surface in the
            # app, the trips page included.
            {'id': 't2', 'title': 'Ski week', 'location': 'Boone',
             'start': '2026-03-02', 'end': '2026-03-09',
             'background_url': 'https://e/ski.jpg'},
        ]}
        storage.get_all_trip_metadata = lambda: []
        storage.get_trip_metadata = lambda tid: (
            {'pois': [1, 2, 3]} if tid == 't1' else {})
        storage.get_cached_schedule = lambda: {}

        rows = {r['id']: r for r in home_board._trip_rows(now)}
        check('t2' not in rows,
              "a trip that is over is in the glance tile's rows")
        check(rows['t1']['poi_count'] == 3,
              f"the stop count never reaches the card: {rows['t1']}")
        # A phrase becomes a photograph, exactly as the page does it.
        check(rows['t1']['image'] is None,
              "a search phrase is being used as an <img src>")
        check('unsplash' in rows['t1']['art'],
              f"a trip with no photograph got no picture found for it: "
              f"{rows['t1']['art']}")

        # The GALLERY asks for a window back, so trips that are over still
        # appear — badged as past, at the bottom, which is what the page does.
        back = {r['id']: r for r in
                home_board._trip_rows(now, back_days=home_board.TRIPS_BACK_DAYS)}
        check('t2' in back and back['t2']['past'] is True,
              f"the gallery cannot show a trip that is over: {list(back)}")
        check(list(back)[-1] == 't2',
              f"a trip you got home from is sorted among the plans: {list(back)}")
        # A URL is left exactly alone.
        check(back['t2']['art'] == 'https://e/ski.jpg',
              f"a real photograph was replaced by a search: {back['t2']['art']}")

        # And the card honours the toggle both ways.
        on = home_board._tile_trips_gallery(now, config={})
        off = home_board._tile_trips_gallery(now, config={'show_past': False})
        check(any(t['id'] == 't2' for t in on['trips']),
              "the gallery drops past trips the page shows")
        check(not any(t['id'] == 't2' for t in off['trips']),
              "turning past trips off did not stick")
    finally:
        storage.get_cached_trips = real_cached
        storage.get_all_trip_metadata = real_meta
        storage.get_trip_metadata = real_one
        storage.get_cached_schedule = real_sched


def scenario_a_past_trip_can_actually_be_known():
    """"Past trips are not showing even when the setting to show them is
    enabled" — and the toggle was working perfectly. Two things underneath it
    were not, and neither was visible from the card:

    1. `/api/trips` fetched Google from `now - 30 days`. A month is the wrong
       unit for "your upcoming and past adventures": nothing older than that
       was ever fetched by ANY surface, the trips page included, because a
       real trip's dates live on its Google event and nowhere else. The card
       could look back as far as it liked at data that stopped a month ago.
    2. The snapshot those dates land in is written as a side effect of loading
       the trips PAGE — and since v2.216 `?panel=true` on /trips serves the
       board, so a wall-only household refreshed it never.

    The window is one number now, shared by the fetch and the card, because a
    card looking back further than the fetch does is asking for something
    nothing went and got.
    """
    import re as _re
    from services import home_board as hb
    check(hb.TRIPS_BACK_DAYS >= 180,
          f"the look-back is {hb.TRIPS_BACK_DAYS} days — a family's past "
          f"trips are seasons back, not weeks")

    src = open(os.path.join(ROOT, 'main.py'), encoding='utf-8').read()
    check('TRIPS_BACK_DAYS' in src,
          "the trips fetch has its own look-back again, so the card can ask "
          "for a year and be handed a month")
    check('timedelta(days=30)' not in
          src[src.index('def assemble_trips'):src.index('def assemble_trips') + 900],
          "the 30-day window is back")

    # The card asks for the same window it can be answered from.
    gal = src  # noqa: F841  (read for the assertions above)
    hbsrc = open(os.path.join(ROOT, 'services', 'home_board.py'),
                 encoding='utf-8').read()
    fn = hbsrc[hbsrc.index('def _tile_trips_gallery'):]
    fn = fn[:fn.index('\n\n\n')]
    check('TRIPS_BACK_DAYS' in fn,
          "the gallery's look-back is a second number, free to disagree")

    # And something refreshes the snapshot without a browser in the loop.
    check('def refresh_trips_snapshot' in src,
          "nothing rebuilds the trips snapshot, so a wall-only household's "
          "trips freeze at the last browser visit")
    loop = src[src.index('async def poll_schedule'):]
    loop = loop[:loop.index('async def push_notification_loop')]
    check('refresh_trips_snapshot' in loop,
          "the refresh exists and nothing calls it")
    fn2 = src[src.index('def refresh_trips_snapshot'):]
    fn2 = fn2[:fn2.index('\n\n\n')] if '\n\n\n' in fn2 else fn2
    check('TRIPS_SNAPSHOT_MAX_AGE' in fn2,
          "the refresh is not throttled, so a 5-minute loop calls Google "
          "every 5 minutes")
    check('trip_hashtags' in fn2,
          "a household that does not use trips is polled anyway")

    # A failed calendar call must NOT write an empty snapshot — that would
    # blank every trip on the wall for a network blip.
    asm = src[src.index('def assemble_trips'):]
    asm = asm[:asm.index('trips_map = {}')]
    check('return []' in asm and 'set_cached_trips' not in asm,
          "a calendar outage erases the snapshot")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} builtin-board scenarios passed")
