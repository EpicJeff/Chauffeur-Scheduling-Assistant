"""The Shopping page became two: Meals & Groceries, and Shopping & Lists.

`/shopping` was never about shopping in general. It plans dinners, works out
what those dinners need, and keeps the ONE standing list a grocery run empties
— so it is `/meals`, Meals & Groceries, and it owns the household's main list
and nothing else. Every other list a family keeps (the pharmacy, the hardware
store) lives on `/lists`, Shopping & Lists, which is where they are made,
named, shared and deleted.

What this file defends, in the order the failures would reach a wall:

  * THE OLD ADDRESS STILL WORKS. A wall panel bookmarked on
    `/shopping?panel=true`, a prep push sent last night and a link somebody put
    in a chat message all have to land where they meant to, query string
    included — that is what a redirect is for and it is the only part of this
    rename a household can't route around;

  * THE STORED VOCABULARY IS MIGRATED AND ALIASED. A shelf, a board order, a
    hidden set and a shipped board's photograph are all keyed by slug, and an
    unknown slug VANISHES rather than erroring. Same for a tile type: the Lists
    glance was keyed `shopping`, and `normalize_instances` drops what it does
    not recognise, so a household's board would have lost the tile silently;

  * THE TWO PAGES OWN DISJOINT LISTS, and between them every list. A list that
    neither page shows is a list nobody can reach — the one failure of this
    split that loses data rather than merely looking wrong;

  * ONE TEMPLATE, TWO MODES. A list is one entity with one drawing, and two
    templates is how two lists pages start disagreeing about what a list looks
    like. `/lists` must also not pay for the meals machinery it does not draw.

Run from chauffeur/:  python tests/test_meals_lists_split.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_split_'))

import tpl_source  # noqa: E402
from services import home_board  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_the_old_address_still_lands_where_it_meant_to():
    """The only part of a rename a household cannot route around. A wall panel
    is bookmarked, a push was sent last night, a link is in a chat message —
    and all three carry a query string that has to survive: `?panel=true` is
    the difference between a board and an admin page, and `?list=` names which
    list was meant."""
    import types
    import main

    def _hit(query=''):
        req = types.SimpleNamespace(
            url=types.SimpleNamespace(path='/shopping', query=query),
            query_params=dict(p.split('=', 1) for p in query.split('&') if p))
        return main.shopping_page_moved(req)

    r = _hit()
    check(r.status_code in (301, 302, 307, 308),
          f"/shopping did not redirect: {r.status_code}")
    loc = r.headers['location']
    check(loc.split('?')[0].endswith('meals'),
          f"/shopping went somewhere other than meals: {loc}")
    # RELATIVE. An absolute /meals is wrong behind a Home Assistant ingress
    # path, which is most of this app's traffic.
    check(not loc.startswith('/'),
          f"the redirect is absolute and breaks under ingress: {loc}")

    loc = _hit('panel=true&list=abc').headers['location']
    check('panel=true' in loc and 'list=abc' in loc,
          f"the redirect dropped the query string: {loc}")

    # And both destinations are real routes with a template behind them.
    paths = {getattr(r_, 'path', None) for r_ in main.app.routes}
    for path in ('/meals', '/lists'):
        check(path in paths, f"{path} is not a route on the app")


def scenario_a_stored_shelf_keeps_its_meals_button():
    """`resolve_tabs` DROPS a slug it does not know, so the day `shopping`
    stopped being a slug, every household that had ever arranged their shelf
    lost its Meals button — and `panel_board_hidden` is worse than the order:
    a board somebody deliberately took off the shelf comes back.

    Two mechanisms, deliberately both. The migration rewrites what is STORED;
    the alias catches what is not ours to rewrite — a `?tabs=` on a bookmarked
    wall panel URL.
    """
    tabs = home_board.resolve_tabs('home,shopping,chores')
    check('meals' in tabs and 'shopping' not in tabs,
          f"an old ?tabs= lost its Meals button: {tabs}")
    # Not duplicated when both words appear, which is what a half-migrated
    # household's URL looks like.
    tabs = home_board.resolve_tabs('shopping,meals')
    check(tabs.count('meals') == 1, f"the alias doubled the button: {tabs}")

    from services import migrations
    from services import storage
    import asyncio

    orig_get, orig_save, orig_state, orig_set = (
        storage.get_settings, storage.update_settings,
        storage.get_app_state, storage.set_app_state)
    stored = {
        'panel_tabs': ['home', 'shopping', 'chores'],
        'panel_board_order': ['home', 'shopping'],
        'panel_board_hidden': ['shopping'],
        'panel_shipped_backgrounds': {'shopping': 'a kitchen at dusk'},
    }
    written = {}
    try:
        storage.get_settings = lambda *a, **k: dict(stored)
        storage.update_settings = lambda d, *a, **k: written.update(d)
        storage.get_app_state = lambda *a, **k: None
        storage.set_app_state = lambda *a, **k: None
        asyncio.run(migrations.migrate_shopping_slug_v2351())
    finally:
        (storage.get_settings, storage.update_settings,
         storage.get_app_state, storage.set_app_state) = (
            orig_get, orig_save, orig_state, orig_set)

    for key in ('panel_tabs', 'panel_board_order', 'panel_board_hidden'):
        check('shopping' not in written[key] and 'meals' in written[key],
              f"{key} was not migrated: {written.get(key)}")
    check(written['panel_shipped_backgrounds'] == {'meals': 'a kitchen at dusk'},
          f"the board's photograph did not follow its slug: "
          f"{written['panel_shipped_backgrounds']}")
    # The hidden set is the one that fails LOUDLY if the order is right and it
    # is wrong: a board comes back onto a wall somebody took it off.
    check(written['panel_board_hidden'] == ['meals'],
          f"a hidden board reappeared: {written['panel_board_hidden']}")


def scenario_a_stored_board_keeps_its_lists_tile():
    """The Lists glance was keyed `shopping`. `normalize_instances` DROPS a
    type it does not know — that is the right rule, and it means a rename with
    no alias silently deletes the tile off every board that has one, on the
    next boot, with nothing anywhere saying why."""
    got = home_board.normalize_instances([{'type': 'shopping'}])
    check([w['type'] for w in got] == ['lists'],
          f"an old board's Lists tile did not survive the rename: {got}")
    # The config comes with it, or the alias saves the tile and loses the
    # setting, which is the same bug one level down.
    got = home_board.normalize_instances(
        [{'type': 'shopping', 'config': {'items': 3}}])
    check(got[0]['config'].get('items') == 3,
          f"the aliased tile lost its config: {got}")
    check('lists' in home_board._BUILDERS,
          "the Lists glance has no builder under its new key")


def scenario_the_two_pages_between_them_own_every_list():
    """The split's one data-losing failure: a list neither page shows is a list
    nobody can reach. `is_default` is the seam — Meals & Groceries owns the
    main list, Shopping & Lists owns the rest — and the two predicates have to
    be exact complements, not merely different."""
    page = open(os.path.join(TPL, 'shopping.html'), encoding='utf-8').read()
    fn = page[page.index('shownLists() {'):]
    fn = fn[:fn.index('},')]
    check('is_default' in fn,
          "the page scopes its lists by something other than the main-list flag")
    check('isLists ?' in fn or 'isLists?' in fn,
          "both destinations show the same lists, so the split does nothing")
    # `?list=` overrides BOTH, or an occasion's link lands on a page that then
    # refuses to show the list it linked to.
    check('pinnedList' in fn,
          "a linked-to list is not shown when it falls outside the page's scope")

    # The card's scopes are complements too, and they are what the shipped
    # boards use — a shipped board cannot name a household's list by id.
    opts = {o['key']: o for w in home_board.WIDGETS
            if w['key'] == 'shopping_list' for o in w['options']}
    values = {c['value'] for c in opts['scope']['choices']}
    check(values == {'all', 'default', 'others'},
          f"the card's list scopes are not all/default/others: {values}")
    meals = home_board.builtin_page('meals', {})
    lists = home_board.builtin_page('lists', {})
    scopes = {}
    for slug, page_ in (('meals', meals), ('lists', lists)):
        for w in page_['widgets']:
            if w['type'] == 'shopping_list':
                scopes[slug] = w['config'].get('scope')
    check(scopes == {'meals': 'default', 'lists': 'others'},
          f"the shipped boards do not divide the lists between them: {scopes}")


def scenario_one_template_two_modes_and_lists_pays_for_no_meals():
    """A list is one entity with one drawing. Two templates is how two lists
    pages start disagreeing about what a list looks like — the same reasoning
    that put the list, the staples and the week into a shared component.

    The other half is the PAYLOAD. Sharing a template must not mean sharing a
    load: opening the pharmacy list on a phone has no business composing a
    week, deriving a plate and reading the whole dish repertoire to draw four
    ticks.
    """
    src = open(os.path.join(os.path.dirname(TPL), 'main.py'), encoding='utf-8').read()
    routes = src[src.index('@app.get("/meals")'):src.index('@app.get("/intake")')]
    check(routes.count('"shopping.html"') == 2,
          "the two destinations no longer share one template, so they can drift")

    page = open(os.path.join(TPL, 'shopping.html'), encoding='utf-8').read()
    init = page[page.index('async init() {'):]
    init = init[:init.index('async loadRepertoire()')]
    guard = init[init.index('if (!this.isLists) {'):]
    for call in ('loadWeek()', 'loadRepertoire()', 'loadPlate()',
                 'loadCategories()', 'loadKitchen()'):
        check(call in guard,
              f"/lists still fetches {call}, which it never draws")
    # …and the list itself is fetched for BOTH, outside the guard.
    before = init[:init.index('if (!this.isLists) {')]
    check('loadItems()' in before and 'loadLists()' in before,
          "the list is inside the meals-only guard, so /lists draws nothing")


def scenario_the_shelf_tells_the_two_apart():
    """Siblings on a shelf read from across a kitchen. Two buttons wearing the
    same icon is the failure `test_panel_chrome` already guards in general;
    this is the pair most likely to hit it."""
    nav = open(os.path.join(TPL, 'nav.html'), encoding='utf-8').read()
    rows = dict(re.findall(r"\{'slug': '(\w+)'.*?'paths': (\[.*?\])\}", nav, re.S))
    for slug in ('meals', 'lists'):
        check(slug in rows, f"the shelf has no {slug} button")
    check(rows['meals'] != rows['lists'],
          "Meals & Groceries and Shopping & Lists wear the same icon")
    check("'label': 'Meals & Groceries'" in nav and "'label': 'Shopping & Lists'" in nav,
          "the shelf still calls a destination by its old name")
    for slug in ('meals', 'lists'):
        check(slug in home_board.NAV_SLUGS and slug in home_board.DEFAULT_TABS,
              f"{slug} is not in the shelf vocabulary")
    check('shopping' not in home_board.NAV_SLUGS,
          "the old slug is still a real destination, so the alias can double it")


# ── The two pages, actually SERVED, against real data.
#
# Which chips a page draws is decided by Alpine at runtime out of a fetch, so
# the source assertions above can only say the predicate looks right. The
# failure being defended is a list NOBODY can reach, and the only place that is
# visible is a running app.
def _serve(lists):
    """The app on a port, seeded, with playwright pointed at it. Returns None
    (and says so) when either half is unavailable, the same bargain the node
    probes elsewhere make."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  skip  playwright not installed — the pages were not served")
        return None
    import socket
    import threading
    import time as _time
    from services import storage
    from models.schemas import ShoppingList, ShoppingItem

    made = {}
    for name, default in lists:
        lid = storage.add_shopping_list(
            ShoppingList(name=name, is_default=default).model_dump())
        storage.add_shopping_item(
            ShoppingItem(list_id=lid, name=name.lower() + ' thing').model_dump())
        made[name] = lid

    import uvicorn
    import main
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1',
                                           port=port, log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        _time.sleep(0.25)
    check(server.started, "the app never came up")
    return sync_playwright, port, made, server


# Every VISIBLE button's label, whitespace collapsed and the open-count suffix
# dropped. Two things that are not cosmetic. Collapsing: a chip is multi-line
# markup, so a raw textContent equals nothing and every assertion here passes
# vacuously. Visibility: `x-show` hides with `display: none` and leaves the
# text in the DOM, so "this page does not offer + List" is only a real claim
# about a button somebody can actually press.
CHIPS = """() => [...document.querySelectorAll('button')]
    .filter(b => b.offsetParent !== null)
    .map(b => (b.textContent || '').replace(/\s+/g, ' ').trim()
                                   .split(' · ')[0])"""


def scenario_neither_page_can_strand_a_list():
    """Every list a family keeps has to be reachable from exactly one of the
    two pages. Both showing one is a duplicate; NEITHER showing one is a list
    that can still be written to by voice and never read by a person — the one
    failure of this split that loses something rather than merely looking
    wrong."""
    made = _serve([('Groceries', True), ('Pharmacy', False), ('Hardware', False)])
    if made is None:
        return
    sync_playwright, port, ids, server = made
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            def chips(path):
                pg = browser.new_page()
                pg.goto(f'http://127.0.0.1:{port}/{path}', wait_until='networkidle')
                pg.wait_for_timeout(1800)
                got = set(pg.evaluate(CHIPS))
                pg.close()
                return got

            meals, lists_ = chips('meals'), chips('lists')
            check('Pharmacy' not in meals and 'Hardware' not in meals,
                  f"Meals & Groceries is still offering the other lists: {meals}")
            check({'Pharmacy', 'Hardware'} <= lists_,
                  f"Shopping & Lists did not draw the household's lists: {lists_}")
            check('Groceries' not in lists_,
                  f"the grocery list is on both pages: {lists_}")
            # Making a list belongs to the page that owns them.
            check('+ List' in lists_ and '+ List' not in meals,
                  "the wrong page offers to make a list")

            # `?list=` beats the scope on BOTH, or an occasion's shopping drain
            # links to a list the page it lands on refuses to show.
            pinned = chips('meals?list=' + ids['Pharmacy'])
            check('Pharmacy' in pinned,
                  f"a linked-to list was refused by the page it linked to: {pinned}")
            browser.close()
    finally:
        server.should_exit = True


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} meals/lists split scenarios passed")
