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
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_builtin_'))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, 'templates')

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


def scenario_the_spec_is_never_handed_out():
    """`BUILTIN_PAGES` is module state and `_page_from` hands its spans dict to
    whoever asked. One caller resizing a tile would otherwise resize it for
    every household on the install, for the life of the process."""
    a = home_board.builtin_page('errands', {})
    a['spans']['errands'] = {'cols': 1, 'rows': 1}
    a['widgets'][0]['config']['count'] = 99
    b = home_board.builtin_page('errands', {})
    check(b['spans']['errands'] != {'cols': 1, 'rows': 1},
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
    check([w['type'] for w in shipped['widgets']] == ['tasks', 'errands'],
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
    """It cannot come from `/api/home_board/pages` — that is the STORED list,
    and putting ten shipped boards in it would freeze all ten into settings the
    first time somebody nudged one tile."""
    from services import storage
    real = storage.get_settings
    try:
        storage.get_settings = lambda: {'panel_pages': [
            {'slug': 'home', 'name': 'Home', 'widgets': ['drives'], 'v': 5}]}
        stored = [p['slug'] for p in home_board.normalize_pages()]
        check(stored == ['home'],
              f"the shipped boards leaked into the stored list: {stored}")
        one = home_board.find_page('chores')
        check(one['slug'] == 'chores' and one['widgets'],
              f"the editor cannot fetch an unsaved board: {one}")
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
    # And the editor has to be able to load a board that is not in settings.
    check('api/home_board/page/' in tpl,
          "the editor cannot open a board nobody has saved yet")
    check('isBuiltinPage' in tpl,
          "the editor calls resetting a shipped board 'Delete'")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} builtin-board scenarios passed")
