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
#
# It is also a screen 1000px tall with a 90px shelf pinned to the bottom, a
# grid starting 100px down and a filled tile sitting 200px into it — the
# numbers `_bottomInset`/`measureFills` work in. jsdom does no layout, so this
# stub is the ONLY place in the suite where that arithmetic actually runs on
# stated boxes; the fill bug that reached a wall (a map drawn underneath the
# shelf) is invisible to every other harness.
HARNESS = r"""
const RECTS = {
  'tile-grid':   { top: 100, bottom: 900, height: 800 },
  'panel-shelf': { top: 910, bottom: 1000, height: 90 },
  'tile:map':    { top: 300, bottom: 700, height: 400 },
};
globalThis.window = {
  location: { search: '', pathname: '/home' },
  matchMedia: function () { return { matches: false }; },
  innerHeight: 1000, scrollY: 0,
  addEventListener: function () {}, removeEventListener: function () {}
};
function stubEl(key, extra) {
  return Object.assign({
    getBoundingClientRect: function () { return RECTS[key]; },
    // The board's padded container, which is what `_boardPadBottom` reads.
    parentElement: { __pad: true },
  }, extra || {});
}
globalThis.document = {
  documentElement: { getAttribute: function () { return 'dark'; } },
  getElementById: function (id) {
    if (id === 'tile-grid') return stubEl('tile-grid', { clientWidth: 1000 });
    // The shelf is `position: fixed`, so `offsetParent` is null on it whether
    // or not it is on screen — which is exactly the trap that let a filled
    // tile grow underneath it. Stated here so the stub cannot be kinder than
    // a browser.
    if (id === 'panel-shelf') return stubEl('panel-shelf', { offsetParent: null });
    return null;
  },
  querySelector: function (sel) {
    return /tile-id="map"/.test(sel) ? stubEl('tile:map') : null;
  },
  addEventListener: function () {}
};
globalThis.CSS = { escape: function (s) { return s; } };
globalThis.getComputedStyle = function (el) {
  return { columnGap: '16px',
           paddingBottom: (el && el.__pad) ? '24px' : '0px',
           borderBottomWidth: '0px' };
};
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

// The card grid's vertical unit is the BOARD's. 56px was Home Assistant's
// section row, borrowed when this grid was written and arbitrary inside a
// tile that was placed with a 200px row.
const gridVars = b.cardGridVars();

// While arranging, the DRAFT is the truth.
const draftSpan = b.spanStyle('drives');
b.arranging = false;
const serverSpan = b.spanStyle('drives');
b.arranging = true;

// A reorder, as the drag does it: move the first tile to the last slot.
const ws = page().widgets;
ws.splice(2, 0, ws.splice(0, 1)[0]);
const reordered = b.tiles().map(t => t.id);

// The HEIGHT SWITCHES, driven exactly as the two checkboxes drive them: read
// the value to render the box, click, read it back. `fill` shipped broken
// because only the writer was tested — the getter answered "1" for any axis it
// did not recognise, so the box was ticked on every tile and unticking it
// deleted a key that was not there.
const fillBefore = b.spanOf('weather', 'fill');
b.setSpan('weather', 'fill', true);
const fillOn = b.spanOf('weather', 'fill');
// Turning fit on has to clear it, and vice versa: a tile cannot be both as
// tall as its content and as tall as what is left.
b.setSpan('weather', 'auto', true);
const afterFit = JSON.stringify(page().spans.weather);
b.setSpan('weather', 'fill', true);
const afterFill = JSON.stringify(page().spans.weather);
b.setSpan('weather', 'fill', false);
const fillOff = b.spanOf('weather', 'fill');

// ── The SHELF picker, against a draft shaped the way loadSetup shapes it:
// the household's own boards AND the shipped board for every destination.
b.catalog = { tabs: [
    { slug: 'home', label: 'Home', kind: 'page' },
    { slug: 'chores', label: 'Chores', kind: 'page' },
    { slug: 'map', label: 'Map', kind: 'page' } ],
  builtin_pages: ['chores', 'map', 'drives', 'calendar'] };
b.draft.panel_pages = [
  { slug: 'home', name: 'Home', icon: 'H', spans: {}, widgets: [] },
  { slug: 'hallway', name: 'Hallway', icon: '🚪', spans: {}, widgets: [] },
  // Shipped boards for the app's own destinations — in the draft because
  // they are editable, NOT because they are extra shelf buttons.
  { slug: 'chores', name: 'Chores', icon: '⭐', spans: {}, widgets: [] },
  { slug: 'map', name: 'Map', icon: '🗺️', spans: {}, widgets: [] },
];
b.draft.panel_tabs = ['home'];
const shelfChoices = b.allTabs().map(t => t.slug);
// And a shelf somebody already saved with the duplicate chip on it.
const shelfCleaned = b.cleanTabs(['home', 'board:chores', 'chores',
                                  'board:hallway', 'board:home']);

// ── And what fill actually RESOLVES to, against the stated boxes above.
// A 1000px screen, a 90px shelf, 24px of board padding, a grid starting at
// 100 and the tile 200px into it: 1000 - 90 - 24 - 100 - 200 - gap.
b.arranging = false;
b.board = { page: { slug: 'home' }, columns: 12, row_height: 200, gap: 16,
            spans: { map: { cols: 12, fill: true } },
            tiles: [{ id: 'map', type: 'map', config: {} }] };
b.measureFills();
const fillResolved = b.fillPx['map'];
const inset = b._bottomInset();

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
  fillBefore: fillBefore,
  fillOn: fillOn,
  fillOff: fillOff,
  fillResolved: fillResolved,
  inset: inset,
  shelfChoices: shelfChoices,
  shelfCleaned: shelfCleaned,
  afterFit: afterFit,
  afterFill: afterFill,
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
  gridVars: gridVars,
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
    # No structural column-gap since the gutters became painted margins —
    # a column's pitch is exactly a track, 1000/12.
    want_col = 1000 / 12
    check(abs(got['cell']['col'] - want_col) < 0.01,
          f"a column measures {got['cell']['col']}, expected {want_col}")
    # The row comes from the PAGE's own height, not a constant — and since
    # v4 it is EXACTLY the row height: the gutter left the vertical skeleton
    # (row-gap 0, spacing painted inside each tile), so height stepping and
    # spacing are independent numbers and a drag steps by what the editor
    # says a row is.
    check(got['cell']['row'] == 200,
          f"a row measures {got['cell']['row']}, expected 200 for a 200px board")


def scenario_the_draft_is_the_truth_while_arranging():
    """That is what makes a drag show its result instead of describing it. A
    panel has no draft and must keep reading the server's payload."""
    got = _run()
    if got is None:
        return
    # The row span renders as PIXELS on the 1px lattice: the draft's 2 rows
    # at the home board's 200px rows, plus the one painted 16px gutter,
    # is span 416 — which is what makes a tile's box rows*row_height at any
    # gutter instead of shrinking when the gutter grows.
    check('span 6' in got['draftSpan'] and 'span 416' in got['draftSpan'],
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


def scenario_a_height_switch_survives_being_read_back():
    """How `fill` shipped broken, and the shape of the bug worth remembering.

    `spanOf` ends in `return String(span[axis] || 1)` — an unsized tile shows
    the width it is actually drawn at rather than a misleading 1. That default
    is right for a number in a text field and poison for a SWITCH: `"1"` is
    truthy, so a checkbox bound to an axis this getter does not recognise
    renders CHECKED on every tile on the board, and unticking it deletes a key
    that was never there — the getter answers "1" again and the box ticks
    itself straight back. The switch is on everywhere, refuses to turn off, and
    does nothing, because the value it reads was never the value it writes.

    `auto` had a line for this from the day it was written. `fill` was added to
    the writer and not to the reader, and the structural test only checked the
    writer. So this drives the pair the way the checkbox does: read to render,
    click, read back.
    """
    got = _run()
    if got is None:
        return
    check(got['fillBefore'] is False,
          f"a tile nobody has filled reports fill={got['fillBefore']!r} — the "
          "box renders ticked on every tile and cannot be cleared")
    check(got['fillOn'] is True,
          f"turning fill on did not come back on: {got['fillOn']!r}")
    check(got['fillOff'] is False,
          f"turning fill off did not come back off: {got['fillOff']!r}")
    # And they are exclusive in both directions: a tile cannot be both as tall
    # as its content and as tall as what is left.
    check('fill' not in got['afterFit'],
          f"turning fit on left fill set: {got['afterFit']}")
    check('auto' not in got['afterFill'],
          f"turning fill on left fit set: {got['afterFill']}")


def scenario_a_destinations_board_is_not_a_second_shelf_button():
    """The shelf picker was offering every destination twice — `+ Drives` and
    `+ 🚗 Drives`, `+ Chores` and `+ ⭐ Chores`, all the way down.

    `allTabs()` was written when `draft.panel_pages` WAS the household's own
    boards, so it mapped every page to a `board:<slug>` chip. v2.220 put the
    shipped board for each destination into the draft too — both are editable,
    which is the point — and this list silently doubled. Both chips went to the
    same screen, because `?panel=true` on /chores IS the Chores board, so the
    pair was never two things.

    The server has agreed all along: `resolve_tabs` validates against
    `own_boards`, which excludes a page whose slug is a destination, so a
    stored `board:chores` was dropped on the way to the wall. That is exactly
    what "I can add both Chores to the shelf, but only one actually shows"
    was — the editor offering a chip the shelf would never honour.
    """
    got = _run()
    if got is None:
        return
    picks = got['shelfChoices']
    check(picks.count('chores') == 1 and 'board:chores' not in picks,
          f"the Chores destination is offered twice: {picks}")
    check('board:map' not in picks,
          f"the Map destination is offered twice: {picks}")
    # The household's OWN boards must survive — that is the whole reason this
    # list walks the draft rather than the catalog, so a board made a moment
    # ago can go on the shelf without a save and a reload in between.
    check('board:hallway' in picks,
          f"a board somebody made can no longer be put on the shelf: {picks}")
    check('board:home' not in picks,
          f"the wall's home board is offered as a board as well: {picks}")

    # And a shelf somebody already saved with the duplicate on it is repaired
    # rather than shown as deleted — they never deleted anything.
    check(got['shelfCleaned'] == ['home', 'chores', 'board:hallway'],
          f"a saved shelf with the duplicate chip came back as "
          f"{got['shelfCleaned']}")


def scenario_a_filled_tile_stops_above_the_shelf():
    """The second wall report on fill: a filled map ran UNDERNEATH the shelf.

    `_bottomInset` guarded the shelf's height with `shelf.offsetParent !== null`
    — the usual "is this on screen" test, and wrong for precisely this element.
    `offsetParent` is defined to be null for anything `position: fixed`, and
    the shelf is fixed to the bottom of the panel. So the guard was never true,
    the shelf's height was never subtracted, and every filled tile was one
    shelf too tall.

    Nothing else in the suite can see this: jsdom does no layout, so every rect
    it reports is zero and the arithmetic reduces to 0 - 0 whether the inset is
    right or not. The stub at the top of this file states the boxes instead,
    which is the only way to check a measurement.

    A 1000px screen, a 90px shelf, 24px of board padding, a grid starting 100px
    down and the tile 200px into it, 16px gutter:
        1000 - (90 + 24) - 100 - 200 - 16 = 570
    """
    got = _run()
    if got is None:
        return
    check(got['inset'] == 114,
          f"the bottom inset is {got['inset']}, not the 90px shelf plus 24px "
          "of board padding — a filled tile grows under the shelf")
    check(got['fillResolved'] == 570,
          f"fill resolved to {got['fillResolved']}px, not 570 — the tile ends "
          f"{570 - (got['fillResolved'] or 0)}px past where it should")


def scenario_the_card_grid_takes_the_boards_row_and_gutter():
    """56px is Home Assistant's section row, and a Custom tile is not an HA
    dashboard. A card's rows should mean what a tile's rows mean on the board
    it was placed on — one vertical unit for the page, not two."""
    got = _run()
    if got is None:
        return
    check(got['gridVars'] == '--nc-row:200px;--nc-gap:16px',
          f"the card grid is not on the board's row and gutter: {got['gridVars']}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} arrange-runtime scenarios passed")
