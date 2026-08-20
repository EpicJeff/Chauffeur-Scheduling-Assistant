"""The shopping kiosk became three cards.

The wall panel's Meals button opened the shopping page, which is a planner: a
dish repertoire, a rules drawer, a photo picker, a Walmart cart and every meals
setting the household has. What a wall actually wants is three things, and the
page already knew which three because its `?kiosk=true` mode had been hiding
everything else for a year — the week's dinners, a chip to say we have run out
of something, and the list.

Those three moved into components/shopping_lists.html as macros over
`mealWeekLogic` / `shoppingListsLogic`, which the page spreads in and the
`meals_week` / `shopping_staples` / `shopping_list` cards wrap. What this file
defends:

  * the page still draws all three, and the SHARED logic is what draws them —
    a second copy on the page is the drift the extraction exists to stop;
  * a card carries no destructive control: no ✕ on a line, no Clear on the
    cart. A wall panel is reachable by every child in the house;
  * the builders ship CONFIG, never rows, because these cards self-fetch;
  * NOTHING on this surface composes or persists a meal plan. `compose_week`
    reads; `get_or_compose_plate` writes, and a wall polling it every quarter
    of an hour would make the panel the author of the family's dinners;
  * the spread does not freeze anything: a getter evaluated on the way through
    `{...factory()}` is a value, not a getter, which would have pinned the
    list to whatever it held at mount.

Run from chauffeur/:  python tests/test_shopping_cards.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_shopcards_'))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')

import tpl_source  # noqa: E402
from services import home_board  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _rendered(name, **ctx):
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/' + name),
                                query_params={})
    return main.templates.env.get_template(name + '.html').render(
        request=req, **ctx)


def scenario_the_page_and_the_cards_are_one_drawing():
    """`import` renders nothing and `include` renders everything. Mixing them
    up is how a page ends up with two copies of the same function, the second
    quietly winning — and how a wall starts disagreeing with the kitchen."""
    for name in ('shopping.html', 'home.html'):
        src = tpl_source.read(name)
        for fn in ('function shoppingListsLogic', 'function mealWeekLogic'):
            check(src.count(fn) == 1,
                  f"{name} emits {fn} {src.count(fn)} times")
    page = open(os.path.join(TPL, 'shopping.html'), encoding='utf-8').read()
    check("import 'components/shopping_lists.html'" in page,
          "the shopping page stopped rendering the shared macros")
    # And the page must not have kept its own copy of what moved.
    body = page[page.index('function shoppingPage()'):]
    for gone in ('dayHeadline(day) {', 'daySqueeze(day) {', 'async outOf(',
                 'isOnList(name) {', 'async setChecked(', 'byline(it) {',
                 'async loadItems(', 'async loadStaples('):
        check(gone not in body,
              f"the page kept its own {gone!r} — two drawings again")


def scenario_the_page_still_draws_all_three():
    html = _rendered('shopping')
    for want in ('Drop in the cart', 'In the cart', 'Nothing planned yet.',
                 'Split by which shop RUN'):
        check(want in html, f"the page lost {want!r}")
    # The week board, the chips and the list are all inside the x-data root —
    # an Alpine directive with no x-data ancestor is silently inert, which is
    # how a dialog once spent a release unable to open at all.
    check(html.index('x-data="shoppingPage()"') < html.index('Drop in the cart'),
          "a shared drawing landed outside the page's Alpine root")


def scenario_a_card_has_no_destructive_control():
    """The page passes `remove` and `clear`; a card passes nothing, so the ✕
    and the Clear button are not in the DOM at all. Not hidden — absent."""
    body = open(os.path.join(TPL, 'components', 'board_tile_body.html'),
                encoding='utf-8').read()
    block = body[body.index("t.type === 'shopping_list'"):]
    block = block[:block.index('</template>')]
    check('remove=' not in block and 'clear=' not in block,
          "the shopping list card is drawing the page's destructive controls")
    check('listsInteractive' in block,
          "the shopping list card does not pass its interactive flag")
    # The page, on the other hand, must still offer both.
    page = open(os.path.join(TPL, 'shopping.html'), encoding='utf-8').read()
    check('removeItem' in page and 'clearChecked' in page,
          "the page lost the hand path for taking a line off the list")


def scenario_the_builders_ship_config_and_never_rows():
    from services import storage
    real_lists, real_dishes = storage.get_shopping_lists, storage.get_dishes
    try:
        storage.get_shopping_lists = lambda *a, **k: [{'id': 'l1', 'name': 'G'}]
        storage.get_dishes = lambda *a, **k: [{'id': 'd1', 'name': 'x'}]
        wk = home_board._tile_meals_week(None, config={'nights': 3,
                                                      'show_image': False})
        st = home_board._tile_shopping_staples(None, config={'list': 'l1'})
        li = home_board._tile_shopping_list(None, config={'show_cart': False})
        check(set(wk) == {'nights', 'parts'}, f"the week card ships rows: {sorted(wk)}")
        check(wk['nights'] == 3 and wk['parts']['image'] is False,
              f"a week option did not reach the card: {wk}")
        check(set(st) == {'interactive', 'list', 'parts'},
              f"the staples card ships more than config: {sorted(st)}")
        check(set(li) == {'interactive', 'list', 'columns', 'parts'},
              f"the list card ships more than config: {sorted(li)}")
        check(li['parts']['cart'] is False and li['parts']['runs'] is True,
              f"a section toggle did not reach the card: {li['parts']}")
        # `columns` is the LAYOUT, and it is resolved in the browser against
        # the tile's own width — so the builder ships the word and never a
        # number of pixels. An unset one is 'auto', not blank: the client
        # would read a blank as a stated column count of nothing.
        check(li['columns'] == 'auto',
              f"an unset lists-per-row did not default to auto: {li['columns']}")
        check(st['interactive'] is True and li['interactive'] is True,
              "the shopping cards came up inert by default")

        # Unconfigured features get no tile — the one question a self-fetching
        # card cannot answer for itself.
        storage.get_shopping_lists = lambda *a, **k: []
        storage.get_dishes = lambda *a, **k: []
        check(home_board._tile_shopping_list(None) is None
              and home_board._tile_shopping_staples(None) is None,
              "a household with no list gets tiles about lists")
        check(home_board._tile_meals_week(None) is None,
              "a household that has never used meals gets a week board")
    finally:
        storage.get_shopping_lists, storage.get_dishes = real_lists, real_dishes


def scenario_the_wall_never_writes_a_meal_plan():
    """Board rule 3, and the sharpest edge in this slice. `compose_week` reads
    the cache and the plates and persists nothing, which is what makes it safe
    for a panel to ask every fifteen minutes. `get_or_compose_plate` persists a
    proposal — a display that changes what it is displaying is not a display.
    """
    src = tpl_source.read('components/shopping_lists.html')
    logic = src[src.index('function mealWeekLogic'):]
    logic = logic[:logic.index('function shoppingListsLogic')]
    check("method: 'POST'" not in logic and 'repropose' not in logic,
          "the shared week logic can reach a proposing endpoint, so a wall "
          "panel can re-plan the family's dinners on a timer")
    # The page keeps repropose — it is a button somebody presses.
    page = open(os.path.join(TPL, 'shopping.html'), encoding='utf-8').read()
    check('api/meals/week/repropose' in page,
          "the page lost the hand path for asking for a different week")
    # And the server's read really is a read.
    import inspect
    from services import meals
    body = inspect.getsource(meals.compose_week)
    check(not re.search(r'storage\.(save|set|add|upsert|put|update|delete)', body),
          "compose_week writes, so nothing may poll it from a wall")


def scenario_nothing_shared_is_a_getter():
    """`{...factory()}` EVALUATES a getter on the way past, so a getter defined
    in a shared factory arrives at the page as a frozen value — the list would
    show whatever it held at mount, forever, and nothing would error."""
    src = tpl_source.read('components/shopping_lists.html')
    logic = src[src.index('function mealWeekLogic'):]
    check(not re.search(r'\n\s+get\s+\w+\s*\(', logic),
          "a shared factory defines a getter; spreading it freezes the value")
    page = open(os.path.join(TPL, 'shopping.html'), encoding='utf-8').read()
    for name in ('open', 'checked', 'allDays'):
        check(f'get {name}()' in page,
              f"the page lost its `{name}` getter, which its markup reads")


def scenario_the_shopping_board_is_the_kiosk():
    page = home_board.builtin_page('shopping', {})
    # Chrome dropped before comparing: shipped boards open with a heading now,
    # and what this defends is the order of the three drawings.
    types_ = [w['type'] for w in page['widgets']
              if w['type'] not in home_board.BARE_TILES]
    check(types_ == ['meals_week', 'shopping_staples', 'shopping_list'],
          f"the shopping board is not the kiosk's three drawings: {types_}")
    # The week leads, full width, the way the kiosk reads.
    check(page['spans']['meals_week']['cols'] == page['columns'],
          f"the week is not the width of the board: {page['spans']}")
    # And nothing from the planner came with it.
    src = tpl_source.read('home.html')
    for editor in ('openDishPicker', 'saveRule(', 'uploadPhoto('):
        check(editor not in src, f"the planner's {editor} was pulled onto the board")


def scenario_all_means_all_and_a_blank_picker_says_what_it_means():
    """The list card's picker offered "All" and did not mean it.

    Blank fell through to `loadLists`, which selects the household's DEFAULT
    list — the groceries, on every real install. So a board set to All showed
    the groceries and nothing else, and a second list somebody made could not
    be put on a wall at all. Reported from a wall.

    Two halves to the fix and both are defended here. The card draws a PANE per
    list when nothing is pinned (a merged list would collapse two stores into
    one "Saturday's shop"); and the blank entry in the editor stops claiming
    "All" on the pickers where it cannot mean it — a staples tap goes on
    exactly one list, and a blank trip means whatever is next.
    """
    src = tpl_source.read('components/shopping_lists.html')
    check('function shoppingListPane' in src,
          "there is no per-list pane, so the card still draws one list")
    card = src[src.index('function shoppingListCard'):
               src.index('function shoppingListPane')]
    # The old fallback, by its shape: the card must not resolve a list itself.
    check('loadLists()' not in card and 'activeId' not in card,
          "the list card still picks an active list, which is the default one")
    check('cfg.list' in card, "the card ignores a pinned list")

    body = tpl_source.read('components/board_tile_body.html')
    pane = body[body.index("t.type === 'shopping_list'"):]
    pane = pane[:pane.index('</template>', pane.index('shopping_items'))]
    check('x-for="p in panes"' in pane and 'shoppingListPane(p.id' in pane,
          "the card body does not render a pane per list")

    # The blank entry says which blank it is.
    opts = tpl_source.read('components/board_options.html')
    check("o.empty || 'All'" in opts,
          "the editor's blank option is hardcoded to All")
    by_key = {w['key']: w for w in home_board.WIDGETS}
    def _list_opt(tile):
        return next(o for o in by_key[tile]['options'] if o['key'] == 'list')
    check(_list_opt('shopping_staples').get('empty'),
          "the staples picker still claims All for a tap that goes on one list")
    check(not _list_opt('shopping_list').get('empty'),
          "the list card's blank is All and should stay All — it draws them all")
    check(not _list_opt('shopping').get('empty'),
          "the Lists glance already meant All and should still say so")


# ── The list card, actually RUN.
#
# Which list a board shows is a decision made entirely in the browser, so a
# source assertion can only say the code LOOKS right — and the bug it is
# defending against (blank meaning "the default list") was code that looked
# perfectly right. Same technique as test_home_board_runtime: pull the shared
# script out of the component, run it in node against a stub `fetch`, and
# assert on the lists it actually asked for.
SHOP_HARNESS = r"""
globalThis.LISTS = LISTS_JSON;
globalThis.ASKED = [];
globalThis.setInterval = function () { return 0; };
globalThis.fetch = async function (url) {
  ASKED.push(url);
  if (url.indexOf('api/shopping/lists') >= 0) {
    return { ok: true, json: async () => LISTS };
  }
  if (url.indexOf('api/shopping/items') >= 0) {
    const id = decodeURIComponent(url.split('list_id=')[1] || '');
    return { ok: true, json: async () => [{ id: id + '-i1', name: 'thing on ' + id }] };
  }
  if (url.indexOf('api/shopping/runs') >= 0) {
    return { ok: true, json: async () => ({ groups: [] }) };
  }
  return { ok: true, json: async () => [] };
};
globalThis.showGlobalAlert = function () {};
"""

SHOP_PROBE = r"""
(async () => {
  const card = shoppingListCard({ data: CFG_JSON }, '');
  await card.startShopping();
  const panes = [];
  for (const p of card.panes) {
    const pane = shoppingListPane(p.id, '', CFG_JSON);
    await pane.startPane();
    panes.push({ id: pane.activeId, items: pane.items.map(i => i.name),
                 interactive: pane.listsInteractive,
                 runs: pane.listShow('runs') });
  }
  console.log(JSON.stringify({ panes: card.panes, gone: card.gone,
                               drawn: panes, asked: ASKED }));
})();
"""


def _run_card(cfg, lists):
    node = shutil.which('node')
    if not node:
        print("  skip  node not installed — the list card was not executed")
        return None
    src = tpl_source.read('components/shopping_lists.html')
    body = re.findall(r'<script>(.*?)</script>', src, re.S)
    body = next((b for b in body if 'function shoppingListCard' in b), None)
    check(body, "components/shopping_lists.html no longer defines shoppingListCard")
    js = (SHOP_HARNESS.replace('LISTS_JSON', json.dumps(lists)) + body
          + SHOP_PROBE.replace('CFG_JSON', json.dumps(cfg)))
    path = os.path.join(tempfile.gettempdir(), 'chauffeur_shopping_card_probe.js')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(js)
    proc = subprocess.run([node, path], capture_output=True, text=True, timeout=30)
    check(proc.returncode == 0,
          "the list card threw in node:" + chr(10) + proc.stderr[:2000])
    return json.loads(proc.stdout.strip().splitlines()[-1])


TWO_LISTS = [{'id': 'groceries', 'name': 'Groceries', 'is_default': True},
             {'id': 'pharmacy', 'name': 'Pharmacy'}]


def scenario_a_blank_picker_draws_every_list():
    """The report, exactly: "it seems to only ever show the grocery list".
    Blank fell through to the household DEFAULT, which is the groceries — so a
    second list was unreachable from any board."""
    got = _run_card({'parts': {}}, TWO_LISTS)
    if got is None:
        return
    check([p['id'] for p in got['panes']] == ['groceries', 'pharmacy'],
          f"blank did not draw every list: {got['panes']}")
    check([p['id'] for p in got['drawn']] == ['groceries', 'pharmacy'],
          f"a pane drew the wrong list: {got['drawn']}")
    # Each pane asked for ITS OWN items, which is the half that actually
    # reaches the wall — two panes both fetching the default list would look
    # identical to the bug being fixed.
    check(any('list_id=pharmacy' in u for u in got['asked']),
          f"nothing ever asked for the second list's items: {got['asked']}")


def scenario_a_pinned_list_is_the_only_one_drawn():
    got = _run_card({'list': 'pharmacy', 'parts': {}}, TWO_LISTS)
    if got is None:
        return
    check([p['id'] for p in got['panes']] == ['pharmacy'],
          f"a pinned list did not win: {got['panes']}")
    check(not got['gone'], "a pinned list that exists was reported as gone")
    check(not any('list_id=groceries' in u for u in got['asked']),
          f"a card pinned to the pharmacy fetched the groceries: {got['asked']}")


def scenario_a_deleted_pin_says_so_instead_of_showing_everything():
    """The same answer the Lists glance gives. Falling back to every list would
    read as the setting doing nothing, which is the bug this arc just fixed."""
    got = _run_card({'list': 'gone-list', 'parts': {}}, TWO_LISTS)
    if got is None:
        return
    check(got['panes'] == [], f"a deleted pin still drew lists: {got['panes']}")
    check(got['gone'], "a deleted pin drew nothing and said nothing")


def scenario_the_card_toggles_reach_every_pane():
    """The panes carry the card's configuration — `interactive` and the
    section toggles. A pane that quietly reverted to the defaults would make
    a read-only board tappable, on a surface every child can reach."""
    got = _run_card({'interactive': False, 'parts': {'runs': False}}, TWO_LISTS)
    if got is None:
        return
    for pane in got['drawn']:
        check(pane['interactive'] is False,
              f"a pane ignored `interactive`: {pane}")
        check(pane['runs'] is False, f"a pane ignored a section toggle: {pane}")


# ── How many lists go across, measured in a real layout engine.
#
# jsdom does no layout, so the node probes above can only see the STRING
# `paneGrid()` builds — and a grid template is exactly the kind of string that
# is plausible and wrong. The browser is the only place the answer exists, so
# this one drives the real function through chromium: the component's own
# script, the real `paneGrid()`, a real grid, and a count of how many blocks
# share the first row. Skips (rather than fails) when playwright is absent,
# the same bargain the node scenarios make.
LAYOUT_PAGE = """
<style>
  body { margin: 0; font-size: 16px }
  .tile { background: #eee }
  .g > div { background: #ccd; min-width: 0 }
</style>
<div id="host"></div>
"""

LAYOUT_PROBE = r"""
([tileWidth, columns, lists]) => {   // playwright passes ONE argument
  const card = shoppingListCard({ data: { columns } }, '');
  const host = document.getElementById('host');
  host.innerHTML = '';
  const tile = document.createElement('div');
  tile.className = 'tile';
  tile.style.width = tileWidth + 'px';
  const g = document.createElement('div');
  g.className = 'g';
  g.style.cssText = 'display:grid;gap:1.5rem;align-items:start;' + card.paneGrid();
  for (let i = 0; i < lists; i++) {
    const d = document.createElement('div');
    d.textContent = 'a list';
    g.appendChild(d);
  }
  tile.appendChild(g);
  host.appendChild(tile);
  const tops = [...g.children].map(c => Math.round(c.getBoundingClientRect().top));
  return {
    perRow: tops.filter(t => t === tops[0]).length,
    width: Math.round(g.children[0].getBoundingClientRect().width),
    overflows: g.scrollWidth > Math.round(tile.getBoundingClientRect().width) + 1,
    // An unapplied template is left verbatim in the computed style; a valid
    // one has been resolved to pixel tracks. This is what catches a typo in
    // the calc, which otherwise fails silently as "one column, always".
    applied: !/repeat|minmax/.test(getComputedStyle(g).gridTemplateColumns),
  };
}
"""


def _layout_probe():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  skip  playwright not installed — the grid was not laid out")
        return None
    src = tpl_source.read('components/shopping_lists.html')
    body = re.findall(r'<script>(.*?)</script>', src, re.S)
    body = next((b for b in body if 'function shoppingListCard' in b), None)
    check(body, "components/shopping_lists.html no longer defines shoppingListCard")
    return sync_playwright, LAYOUT_PAGE + '<script>' + body + '</script>'


def scenario_the_lists_go_across_a_wide_tile_and_never_off_it():
    """A list is narrow and a wall is landscape, so several of them stacked
    down a tile is a column of text with a field of empty panel beside it.

    Three properties, and the third is why this is measured rather than
    asserted: as many as fit when the card says `auto`; AT MOST the stated
    number when it says one; and never, at any width, a column narrower than a
    list can be read at or wider than the tile it is in. The last one is the
    trap — a stated 4 on a phone-width tile has to become 1, and a template
    that squeezes instead is a wall panel nobody can shop from.
    """
    made = _layout_probe()
    if made is None:
        return
    sync_playwright, page = made
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        tab = browser.new_page()
        tab.set_content(page)
        run = lambda w, c, n: tab.evaluate(LAYOUT_PROBE, [w, c, n])
        try:
            # Wide wall, three lists: `auto` uses the room it has.
            got = run(1600, 'auto', 3)
            check(got['applied'], "paneGrid() produced a template the browser rejected")
            check(got['perRow'] == 3,
                  f"a 1600px tile stacked its lists instead of spreading them: {got}")

            # A stated number is a CEILING. Two, on the same wall, means two.
            got = run(1600, '2', 3)
            check(got['perRow'] == 2, f"`two per row` did not hold at 1600px: {got}")

            # …and it degrades rather than squeezing. Four on a narrow tile is
            # one, because a 95px shopping list is not a shopping list.
            for columns in ('auto', '2', '4'):
                got = run(380, columns, 3)
                check(got['perRow'] == 1,
                      f"a 380px tile put {got['perRow']} lists across at "
                      f"columns={columns}: {got}")
                check(not got['overflows'],
                      f"the grid ran off a 380px tile at columns={columns}: {got}")

            # Nothing overflows at any width the board can produce.
            for width in (2400, 1600, 1000, 700, 520, 380, 280):
                for columns in ('auto', '1', '2', '3', '4'):
                    got = run(width, columns, 3)
                    check(not got['overflows'],
                          f"columns={columns} overflowed a {width}px tile: {got}")

            # A card pinned to ONE list is full width whatever this says —
            # empty tracks collapse, which is why the option says it is
            # ignored there rather than pretending to apply.
            for columns in ('auto', '3', '4'):
                got = run(1600, columns, 1)
                check(got['width'] == 1600,
                      f"a single list was penned into a column at "
                      f"columns={columns}: {got}")
        finally:
            browser.close()


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} shopping-card scenarios passed")
