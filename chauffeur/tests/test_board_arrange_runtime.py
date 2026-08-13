"""Laying a board out ON the board: the arithmetic, run.

Dragging is the kind of feature whose failures are all silent. A resize that
runs at half the pointer's speed, a reorder that writes into the board you are
not looking at, a cancel that does not put anything back — none of them raise,
and all of them look like the app not quite working.

So the parts that can be checked without a browser are: the grid cell
measurement (a resize that disagrees with the grid runs ahead of or behind the
hand), the reorder itself, the draft-vs-server switch that makes a drag show
its result, and the lock between the board being LOOKED AT and the board being
EDITED — which is the one that can quietly rearrange the wrong wall.

Same technique as the other runtime tests: pull the script out of the template,
run it in node against a DOM thin enough to be honest.

Run from chauffeur/:  python tests/test_board_arrange_runtime.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# A grid 1000px wide, 12 columns, 16px gaps — so one column plus its gap is
# ((1000 - 16*11) / 12) + 16 = 84.66…, and a 2-column drag is ~169px.
HARNESS = r"""
globalThis.window = {
  location: { search: '', pathname: '/home' },
  matchMedia: function () { return { matches: false }; },
  addEventListener: function () {}, removeEventListener: function () {}
};
globalThis.document = {
  documentElement: { getAttribute: function () { return 'dark'; } },
  getElementById: function (id) {
    if (id !== 'tile-grid') return null;
    return { clientWidth: 1000 };
  },
  addEventListener: function () {}
};
globalThis.getComputedStyle = function () { return { columnGap: '16px' }; };
globalThis.setInterval = function () { return 0; };
"""

PROBE = r"""
const b = homeBoard();
const page = () => b.draft.panel_pages[b.pageIndex];

b.draft.panel_pages = [
  { slug: 'home', name: 'Home', icon: 'H', columns: 12, row_height: 200,
    background: '', spans: { drives: { cols: 6, rows: 2 } },
    widgets: [{ id: 'drives', type: 'drives', config: {} },
              { id: 'calendar', type: 'calendar', config: {} },
              { id: 'map', type: 'map', config: {} }] },
  { slug: 'hallway', name: 'Hallway', icon: 'X', columns: 4, row_height: 300,
    background: '', spans: {}, widgets: [] },
];
// The board being LOOKED AT is the hallway, while the editor happens to be
// sitting on the home board.
b.board = {
  page: { slug: 'hallway', name: 'Hallway' }, columns: 4, row_height: 300,
  spans: { map: { cols: 2, rows: 1 } },
  tiles: [{ id: 'map', type: 'map' }],
};
b.pageIndex = 0;
b.startArrange();
const lockedTo = page().slug;

// Back to the home board for the rest, which is where the tiles are.
b.arranging = false;
b.board = {
  page: { slug: 'home', name: 'Home' }, columns: 12, row_height: 200,
  spans: { drives: { cols: 3, rows: 1 } },
  tiles: [{ id: 'drives', type: 'drives' }, { id: 'calendar', type: 'calendar' },
          { id: 'map', type: 'map' }],
};
b.pageIndex = 0;
b.startArrange();

const cell = b._cell();

// --- Arranging the cards INSIDE a tile is the same gesture one level down.
// What gets dragged is a PATH — `0.1` is the second card of the first column —
// because the drawing is an HTML string and there is no object to point at.
const cardTree = { type: 'horizontal-stack', cards: [
  { type: 'vertical-stack', cards: [
    { type: 'gauge', entity: 'sensor.a' },
    { type: 'gauge', entity: 'sensor.b' } ] },
  { type: 'gauge', entity: 'sensor.c' } ] };
const deep = b.cardParent(cardTree, '0.1');
const top = b.cardParent(cardTree, '1');
deep.list.splice(0, 0, deep.list.splice(deep.index, 1)[0]);
const cardOrder = cardTree.cards[0].cards.map(c => c.entity);

const leaf = { kind: 'gauge', name: 'A', value: 1, pct: 0.5, min: 0, max: 2, missing: false };
// startArrange() above left the board arranging, so the IDLE drawing has to
// say so explicitly — the handles are markup, and drawing them when nobody is
// arranging puts them on the wall.
b.arranging = false;
const idleDraw = b.drawCard({ kind: 'stack', direction: 'horizontal', cards: [
  { kind: 'stack', direction: 'vertical', cards: [leaf] }, leaf ] }, []);
b.arranging = true;
const armedDraw = b.drawCard({ kind: 'stack', direction: 'vertical', cards: [leaf] }, []);

// One card given a height, one not — the case where a stretched neighbour used
// to grow along with the card being dragged.
const sizedDraw = b.drawCard({ kind: 'stack', direction: 'horizontal', cards: [
  Object.assign({}, leaf, { grid: { cols: 6, rows: 3 } }), leaf ] }, []);
const plainDraw = b.drawCard({ kind: 'stack', direction: 'horizontal',
  cards: [leaf, leaf] }, []);

// --- The cards inside a CUSTOM TILE. Different machinery from the stack of
// Home Assistant cards above: these are ordinary settings, so a drag is a
// splice in the draft and the drawing follows it without a round trip.
b.page().widgets.push({ id: 'mine', type: 'custom', config: { cards: [
  { id: 'chores', type: 'chores', config: {} },
  { id: 'weather', type: 'weather', config: {} } ] } });
b.board.tiles.push({ id: 'mine', type: 'custom', locked: false, cards: [
  { id: 'mine-chores', type: 'chores', cols: 12, rows: 0, config: {}, data: {} },
  { id: 'mine-weather', type: 'weather', cols: 12, rows: 0, config: {}, data: {} } ] });
const mine = () => b.board.tiles.find(t => t.id === 'mine');
const drawnFirst = b.cardsOf(mine()).map(c => c.id);
// A reorder, as the drag does it.
const draftCards = b._cardsOf('mine');
draftCards.splice(1, 0, draftCards.splice(0, 1)[0]);
const drawnAfter = b.cardsOf(mine()).map(c => c.id);
// A resize, as the grip does it: the draft carries it, the drawing reads it.
b.setCardNum(draftCards[0], 'cols', 6, 12);
b.setCardNum(draftCards[0], 'rows', 3, 0);
const sized = b.cardsOf(mine())[0];
// Defaults stop being stored; nonsense is clamped rather than drawn.
b.setCardNum(draftCards[1], 'cols', 12, 12);
b.setCardNum(draftCards[1], 'rows', 900, 0);
const tidy = JSON.stringify(draftCards[1].config);
// A LOCKED tile is never re-ordered off the draft — it has no card list.
const lockedDraw = b.cardsOf({ id: 'calendar', locked: true,
  cards: [{ id: 'calendar', cols: 12, rows: 0 }] }).map(c => c.id);
// The overlay opens on the card that was tapped, addressed by its DRAWN id.
b.openCardEditor('mine', 'mine-weather');
const editingId = b.editing && b.editing.id;
b.closeCardEditor();

// While arranging, the DRAFT is the truth.
const draftSpan = b.spanStyle('drives');
b.arranging = false;
const serverSpan = b.spanStyle('drives');
b.arranging = true;

// A reorder, as the drag does it: move the first tile to the last slot.
const ws = page().widgets;
ws.splice(2, 0, ws.splice(0, 1)[0]);
const reordered = b.tiles().map(t => t.id);

// A resize, then a cancel.
b.setSpan('drives', 'cols', 8);
b.setSpan('drives', 'rows', 4);
const afterResize = JSON.stringify(page().spans.drives);
b.cancelArrange();
const afterCancel = JSON.stringify(page().spans.drives);
const orderAfterCancel = page().widgets.map(w => w.id);

console.log(JSON.stringify({
  lockedTo: lockedTo,
  cell: cell,
  draftSpan: draftSpan,
  serverSpan: serverSpan,
  reordered: reordered,
  afterResize: afterResize,
  afterCancel: afterCancel,
  orderAfterCancel: orderAfterCancel,
  arrangingAfterCancel: b.arranging,
  cardDeepIsColumn: deep.list === cardTree.cards[0].cards && deep.index === 1,
  cardTopIsRow: top.list === cardTree.cards && top.index === 1,
  cardReordered: cardOrder,
  cardPaths: (idleDraw.match(/data-path="[\d.]+"/g) || []),
  handlesIdle: /nc-card-move/.test(idleDraw),
  handlesArmed: /nc-card-move/.test(armedDraw) && /nc-card-size/.test(armedDraw),
  sizedFrees: /nc-stack-grid nc-free/.test(sizedDraw),
  plainStretches: !/nc-free/.test(plainDraw),
  sizedHeights: (sizedDraw.match(/height:calc\(\d+ \* var\(--nc-row\)\)/g) || []),
  drawnFirst: drawnFirst,
  drawnAfter: drawnAfter,
  sizedCard: { id: sized.id, cols: sized.cols, rows: sized.rows },
  tidy: tidy,
  lockedDraw: lockedDraw,
  editingId: editingId,
  editingCleared: b.editing === null,
}));
"""


def _run():
    node = shutil.which('node')
    if not node:
        return None
    src = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    body = next(b for b in re.findall(r'<script>(.*?)</script>', src, re.S)
                if 'function homeBoard()' in b)
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'run.mjs')
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(HARNESS + body + PROBE)
        proc = subprocess.run([node, f], capture_output=True, text=True, timeout=60)
    check(proc.returncode == 0, f"the board script threw:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_arranging_locks_to_the_board_you_are_looking_at():
    """The worst bug this feature could have. The editor below can be pointed
    at any board; dragging tiles around a picture of one while writing them
    into another rearranges a wall nobody is standing in front of."""
    got = _run()
    if got is None:
        print('  skip  node is not installed')
        return
    check(got['lockedTo'] == 'hallway',
          f"arrange mode edited {got['lockedTo']!r} while showing the hallway board")


def scenario_a_grid_cell_is_measured_not_assumed():
    """A resize that disagrees with the grid runs ahead of or behind the hand,
    and the household's column count and the stylesheet's gap are both things
    that change without this code being touched."""
    got = _run()
    if got is None:
        return
    # (1000 - 16*11)/12 + 16
    want_col = (1000 - 16 * 11) / 12 + 16
    check(abs(got['cell']['col'] - want_col) < 0.01,
          f"a column measures {got['cell']['col']}, expected {want_col}")
    # The row comes from the PAGE's own height, not a constant.
    check(got['cell']['row'] == 200 + 16,
          f"a row measures {got['cell']['row']}, expected 216 for a 200px board")


def scenario_the_draft_is_the_truth_while_arranging():
    """That is what makes a drag show its result instead of describing it. A
    panel has no draft and must keep reading the server's payload."""
    got = _run()
    if got is None:
        return
    check('span 6' in got['draftSpan'] and 'span 2' in got['draftSpan'],
          f"arranging did not read the draft: {got['draftSpan']}")
    check('span 3' in got['serverSpan'],
          f"a board that is not being arranged stopped reading the server: "
          f"{got['serverSpan']}")


def scenario_a_drag_reorders_the_tiles_that_are_drawn():
    """The grid renders the SERVER's tiles; the order being dragged lives in
    the draft. If the two are not joined, a tile moves in the settings and
    stays put on the board."""
    got = _run()
    if got is None:
        return
    # 'mine' is the custom tile the card scenarios add; it stays where it was
    # put, which is itself worth seeing — a drag moves ONE tile.
    check(got['reordered'] == ['calendar', 'map', 'drives', 'mine'],
          f"the drawn order did not follow the drag: {got['reordered']}")


def scenario_cancel_puts_everything_back():
    """Both halves — the sizes AND the order. A cancel that restores one of
    them is worse than no cancel, because it looks like it worked."""
    got = _run()
    if got is None:
        return
    check(got['afterResize'] == '{"cols":8,"rows":4}',
          f"the resize did not take: {got['afterResize']}")
    check(got['afterCancel'] == '{"cols":6,"rows":2}',
          f"cancel did not restore the tile's size: {got['afterCancel']}")
    check(got['orderAfterCancel'] == ['drives', 'calendar', 'map'],
          f"cancel did not restore the tile ORDER: {got['orderAfterCancel']}")
    check(got['arrangingAfterCancel'] is False, "cancel left the board in arrange mode")


def scenario_the_cards_inside_a_tile_arrange_too():
    """A tile made of a stack of cards is a layout as much as the board is, and
    the reason to drag it is the reason tiles got dragging: typing numbers into
    a list and scrolling up to see what happened is the long way round.

    What moves is a PATH into the config tree. The drawing is one HTML string,
    so there is no object on the page to point at — `0.1` is the second card of
    the first column, and it has to address the parsed config or a drag would
    change something nobody can see.
    """
    got = _run()
    if got is None:
        return
    check(got['cardDeepIsColumn'],
          "a nested path does not resolve to the list its card sits in, so a "
          "drag would splice the wrong stack")
    check(got['cardTopIsRow'], "a top-level path resolves to the wrong list")
    check(got['cardReordered'] == ['sensor.b', 'sensor.a'],
          f"reordering inside a column did not take: {got['cardReordered']}")
    check(got['cardPaths'] == ['data-path="0"', 'data-path="0.0"', 'data-path="1"'],
          f"the drawing does not carry each card's address: {got['cardPaths']}")
    # The handles are markup, not an overlay — the drawing is a string, so
    # anything positioned against a cell has to be inside it. Which means they
    # must NOT be drawn when nobody is arranging.
    check(not got['handlesIdle'],
          "the drag handles are drawn on a board nobody is arranging, which "
          "puts them on the wall")
    check(got['handlesArmed'], "arrange mode draws no handles inside a tile")


def scenario_a_card_can_be_sized_without_sizing_its_neighbours():
    """A grid row is as tall as its tallest cell, and a stretched neighbour
    grows with it — so dragging one card taller dragged everything beside it,
    which is the uniform resize the sizes exist to escape. A stack holding any
    sized card stops stretching; a stack holding none keeps stretching, because
    ragged bottoms on a row nobody has touched look like a mistake.

    The height is a `height`, not a `min-height`: a minimum can only grow a
    card, so dragging the grip upwards did nothing and the card looked stuck.
    """
    got = _run()
    if got is None:
        return
    check(got['sizedFrees'],
          "a stack with a sized card still stretches its cells, so resizing "
          "one card resizes the ones beside it")
    check(got['plainStretches'],
          "a stack nobody has sized stopped stretching, which leaves a row of "
          "cards with ragged bottoms")
    check(got['sizedHeights'] == ['height:calc(3 * var(--nc-row))'],
          f"exactly the sized card should carry a height: {got['sizedHeights']}")


def scenario_a_custom_tiles_cards_are_drawn_off_the_draft_while_arranging():
    """Same reason the tiles themselves are: a drag that only shows its result
    after a save and a refetch is a drag nobody can aim. A card's CONTENT still
    comes from the server — only the server can build it — but where it sits
    and how big it is are settings, and the settings are right here.

    A built-in tile is exempt, and must be: it has no card list to sort
    against, and reading one would sort its single card against nothing.
    """
    got = _run()
    if got is None:
        print('  skip  node is not installed')
        return
    check(got['drawnFirst'] == ['mine-chores', 'mine-weather'],
          f"the cards did not draw in their stored order: {got['drawnFirst']}")
    check(got['drawnAfter'] == ['mine-weather', 'mine-chores'],
          f"reordering the draft did not move the drawn card: {got['drawnAfter']}")
    check(got['sizedCard'] == {'id': 'mine-weather', 'cols': 6, 'rows': 3},
          f"a resize did not reach the drawing: {got['sizedCard']}")
    check(got['lockedDraw'] == ['calendar'],
          f"a built-in tile's card was re-sorted against a list it has "
          f"none of: {got['lockedDraw']}")


def scenario_a_card_at_its_default_size_stores_nothing():
    """Otherwise opening a card's settings and closing them again writes out
    numbers nobody chose, and those numbers stop tracking the default the day
    it moves. Rows are clamped separately from columns because their floor is
    ZERO — "as tall as the content" is the answer for a card nobody has sized,
    not a missing value.
    """
    got = _run()
    if got is None:
        return
    check(got['tidy'] == '{"rows":40}',
          f"a default was stored, or nonsense was not clamped: {got['tidy']}")


def scenario_the_overlay_opens_on_the_card_that_was_tapped():
    """The drawn card's id is namespaced by its tile and the stored one is not,
    so the overlay has to translate. Getting it wrong opens somebody else's
    settings, which is the kind of bug that only shows up as a change made to
    the wrong card.
    """
    got = _run()
    if got is None:
        return
    check(got['editingId'] == 'weather',
          f"the overlay opened on {got['editingId']!r}, not the tapped card")
    check(got['editingCleared'], "closing the overlay left a card being edited")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} arrange-runtime scenarios passed")
