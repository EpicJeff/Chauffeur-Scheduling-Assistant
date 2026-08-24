"""The card grid, measured.

A card inside a Custom tile is placed with a column span and — until this was
fixed — sized with a bare CSS height, which is not the same thing. A height
does not make a cell a participant in the grid's vertical geometry, so every
cell owned exactly one row: a tall card inflated that row and the next card
wrapped below its bottom edge instead of into the empty space beside it. That
is a layout somebody asked for and could not have.

jsdom does no layout, so this is the one harness that can tell whether the
cells actually land where the spans say. Same bargain as the other browser
tests: skip when playwright is absent.

Run from chauffeur/:  python tests/test_board_card_grid.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_card_grid_'))

import tpl_source  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# The real `.nc-stack-grid` rules, lifted out of home.html so a renamed
# variable or a dropped `gap` fails here rather than on the wall.
PAGE = """
<style>
  body { margin: 0 }
  .tile { width: 480px }
{grid_css}
</style>
<div class="tile"><div class="nc-stack-grid" id="g" style="{vars}">
  <div class="nc-cell" id="tall"  style="{tall}">tall
    <!-- A Home Assistant stack drawn INSIDE a Custom tile's card: it carries
         the SAME class as the outer grid, and never sets --nc-row/--nc-gap
         inline the way the outer one does — so it has to fall back to the
         class's own 56px/12px, not inherit the board's numbers from its
         ancestor. That is the split Decision 1b turns on. -->
    <div class="nc-stack-grid" id="inner">
      <div class="nc-cell" id="innerCell" style="{inner}">nested</div>
    </div>
  </div>
  <div class="nc-cell" id="topA"  style="{short}">a</div>
  <div class="nc-cell" id="topB"  style="{short}">b</div>
</div></div>
"""

PROBE = """
() => {
  const box = id => {
    const r = document.getElementById(id).getBoundingClientRect();
    return { top: Math.round(r.top), bottom: Math.round(r.bottom),
             left: Math.round(r.left), height: Math.round(r.height) };
  };
  return { tall: box('tall'), a: box('topA'), b: box('topB'),
           innerCell: box('innerCell') };
}
"""


def _measure(row, gap, tall_rows, short_rows):
    """Lay three cells out in chromium and hand back their boxes."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  skip  playwright not installed — the grid was not laid out")
        return None
    tpl = tpl_source.read('home.html')
    rules = re.findall(r'^\s*\.nc-stack-grid[^{\n]*\{[^}]*\}', tpl, re.M)
    check(rules, "home.html no longer has any .nc-stack-grid rules to measure")

    def cell(cols, rows):
        return (f'grid-column:span {cols};grid-row:span {rows};'
                f'height:calc({rows} * var(--nc-row) + {rows - 1} * var(--nc-gap))')

    page = (PAGE.replace('{grid_css}', chr(10).join(rules))
                .replace('{vars}', f'--nc-row:{row}px;--nc-gap:{gap}px')
                .replace('{tall}', cell(6, tall_rows))
                .replace('{short}', cell(6, short_rows))
                # A fixed 2-row cell inside the nested grid: this is checked
                # only by the cross-grid scenario below, but it has to be laid
                # out for every scenario since it lives inside `tall`.
                .replace('{inner}', cell(12, 2)))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        tab = browser.new_page()
        tab.set_content(page)
        got = tab.evaluate(PROBE)
        browser.close()
    return got


def scenario_two_short_cards_stack_beside_a_tall_one():
    """The request, measured. Two two-row cards beside a four-row card have to
    occupy the SAME column band and different rows, with the second one still
    above the tall card's bottom edge — which is exactly what a cell that owns
    a single grid row can never do."""
    got = _measure(row=56, gap=12, tall_rows=4, short_rows=2)
    if got is None:
        return
    check(got['a']['left'] == got['b']['left'] > got['tall']['left'],
          f"the short cards are not stacked in the column band beside the tall "
          f"one: {got}")
    check(got['b']['top'] > got['a']['top'],
          f"the second short card did not stack under the first: {got}")
    check(got['b']['bottom'] <= got['tall']['bottom'] + 1,
          f"the second short card fell past the tall card's bottom edge, which "
          f"is the old behaviour: {got}")


def scenario_a_span_equals_the_stack_beside_it_at_any_row_and_gutter():
    """`N` rows must equal `a + b = N` rows plus the gutter between them, or a
    tall card and the stack beside it drift apart. The card grid uses real CSS
    gaps rather than the board's painted ones, so this holds at every row
    height and gutter — which is what makes taking the board's numbers safe."""
    for row, gap in ((56, 12), (10, 20), (16, 24)):
        got = _measure(row=row, gap=gap, tall_rows=4, short_rows=2)
        if got is None:
            return
        check(abs(got['b']['bottom'] - got['tall']['bottom']) <= 1,
              f"at row={row} gap={gap} the stack and the tall card do not "
              f"bottom-align: {got}")
        check(got['tall']['height'] == 4 * row + 3 * gap,
              f"a four-row card at row={row} gap={gap} is "
              f"{got['tall']['height']}px, not {4 * row + 3 * gap}px")


def scenario_a_nested_ha_stack_keeps_its_own_row_unit():
    """The cascade the design leans on: a Custom tile's grid takes the
    board's row and gutter through an INLINE style, and a Home Assistant
    stack nested inside one of its cards carries the same `.nc-stack-grid`
    class but never sets that inline override, so it falls back to the
    class's own 56px row and 12px (0.75rem) gutter rather than inheriting the
    board's numbers from its ancestor. Proven at a board row (10px) and
    gutter (20px) far enough from 56/12 that inheriting them would be
    obviously wrong."""
    got = _measure(row=10, gap=20, tall_rows=4, short_rows=2)
    if got is None:
        return
    want = 2 * 56 + 1 * 12
    check(got['innerCell']['height'] == want,
          f"a nested Home Assistant stack's cell measures "
          f"{got['innerCell']['height']}px, not {want}px — it inherited the "
          f"outer Custom tile grid's row/gutter instead of keeping HA's own")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} card-grid scenarios passed")
