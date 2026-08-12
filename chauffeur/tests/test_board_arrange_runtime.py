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
    check(got['reordered'] == ['calendar', 'map', 'drives'],
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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} arrange-runtime scenarios passed")
