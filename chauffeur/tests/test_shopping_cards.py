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
import os
import re
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
        check(set(li) == {'interactive', 'list', 'parts'},
              f"the list card ships more than config: {sorted(li)}")
        check(li['parts']['cart'] is False and li['parts']['runs'] is True,
              f"a section toggle did not reach the card: {li['parts']}")
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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} shopping-card scenarios passed")
