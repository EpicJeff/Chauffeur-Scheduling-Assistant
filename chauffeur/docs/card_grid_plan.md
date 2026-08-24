# Card row spans and cross-tile card moves — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A card inside a Custom tile can be as tall as several rows *and* have
two shorter cards stacked beside it, and a card can be dragged from one Custom
tile into another instead of being copied as YAML.

**Architecture:** The card grid (`.nc-stack-grid`) stops sizing cells with a
bare CSS `height` and starts spanning grid rows, so a cell participates in the
grid's vertical geometry the way it already does horizontally. The row unit and
gutter become CSS variables: the panel's own card grid takes them from the
board's `row_height` / `gap`, while a Home Assistant stack keeps HA's 56px
because its numbers were written against HA's row. The cross-tile drag extends
the existing pointer handler with a second `closest()` lookup for the tile under
the pointer.

**Tech Stack:** Alpine.js in `templates/home.html` (no build step for the
component itself), a precompiled Tailwind sheet, FastAPI + plain dicts on the
server, and the repo's own test harnesses — node for handler arithmetic,
chromium via playwright for anything geometric.

**Spec:** `docs/card_grid_design.md`

## Global Constraints

- **Run tests with `python tools/test.py`** (parallel). `--focus <file>` for the
  inner loop; a full sweep before any commit that touches code.
- **Bump `config.yaml`'s version and commit on every change.** Version format
  `X.Y.Z`; the commit subject ends with `(vX.Y.Z)`.
- **Never use `alert()` / `confirm()` / `prompt()`.** The panel's own
  `showGlobalAlert(...)` is the only way to say something went wrong.
- **`python tools/build_tailwind.py` after touching a template**, or
  `test_tailwind_build.py` fails on a stale sheet.
- **No commit message may contain a double quote** (PowerShell splits the args);
  write multi-line messages through a file with `git commit -F`.
- **Both grids get row spans; only the panel's own grid gets the board's row.**
  A Home Assistant stack keeps `--nc-row: 56px` and a 12px gutter.
- **Nothing on the wall changes height.** No card on any board carries `cols` or
  `rows` today; this is new capability, not a re-layout.

---

### Task 1: Name the row and the gutter, and take them from the board

The grid's two magic numbers become variables, and the panel's own card grid
gets the board's values. No layout changes yet — a cell is still sized by a CSS
height — so this task is provably inert on screen.

**Files:**
- Modify: `templates/home.html:73-79` (the `.nc-stack-grid` rule)
- Modify: `templates/home.html:941-945` (the Custom tile's grid element)
- Modify: `templates/home.html` (a new `cardGridVars()` beside `cellStyle`, ~:2301)
- Test: `tests/test_board_arrange_runtime.py`

**Interfaces:**
- Consumes: `rowHeight()` and `gapPx()`, the board accessors at
  `home.html:1981` and `:1988`.
- Produces: `cardGridVars()` → a style string
  `"--nc-row:<px>px;--nc-gap:<px>px"`, used by Task 3's resize pitch and by
  Task 2's height formula.

- [ ] **Step 1: Write the failing test**

In `tests/test_board_arrange_runtime.py`, inside the existing `PROBE` (after the
custom-tile block that pushes the `mine` widget), add:

```js
// The card grid's vertical unit is the BOARD's. 56px was Home Assistant's
// section row, borrowed when this grid was written and arbitrary inside a
// tile that was placed with a 200px row.
const gridVars = b.cardGridVars();
```

and add to the `console.log(JSON.stringify({...}))` payload:

```js
  gridVars: gridVars,
```

Then add the scenario at the end of the file, before `SCENARIOS = [...]`:

```python
def scenario_the_card_grid_takes_the_boards_row_and_gutter():
    """56px is Home Assistant's section row, and a Custom tile is not an HA
    dashboard. A card's rows should mean what a tile's rows mean on the board
    it was placed on — one vertical unit for the page, not two."""
    got = _run()
    if got is None:
        return
    check(got['gridVars'] == '--nc-row:200px;--nc-gap:16px',
          f"the card grid is not on the board's row and gutter: {got['gridVars']}")
```

(The fixture board in this file is `row_height: 200`, and the harness's
`getComputedStyle` reports a 16px gap; `gapPx()` falls back to 16 when the
board carries none.)

- [ ] **Step 2: Run the test and watch it fail**

Run: `python tests/test_board_arrange_runtime.py`
Expected: FAIL — `b.cardGridVars is not a function`, surfaced as "the board's
helpers threw in node".

- [ ] **Step 3: Add the helper**

In `templates/home.html`, immediately above `cellStyle(c) {` (~line 2301):

```js
                // The two numbers a card's height is measured in. They are the
                // BOARD's: 56px was Home Assistant's section row, borrowed when
                // this grid was written, and inside a tile that was placed on a
                // 10px lattice it is a unit nobody chose. Set on the grid
                // element, so a nested stack of Home Assistant cards — which
                // re-declares them on its own class — keeps HA's row and does
                // not inherit ours.
                cardGridVars() {
                    return `--nc-row:${this.rowHeight()}px;`
                         + `--nc-gap:${this.gapPx()}px`;
                },
```

- [ ] **Step 4: Declare the variables in CSS and put them on the grid**

`templates/home.html:73-79` becomes:

```css
        .nc-stack-grid {
            --nc-row: 56px;
            --nc-gap: 0.75rem;
            display: grid;
            grid-template-columns: repeat(12, minmax(0, 1fr));
            gap: var(--nc-gap);
            align-items: stretch;
        }
```

and the Custom tile's grid element at `templates/home.html:941`:

```html
                            <div class="nc-stack-grid" :data-cards="t.id"
                                :style="cardGridVars()"
                                @pointerdown="arranging && startTileCardDrag($event, t.id)"
                                :class="tileFree(t) ? 'nc-free' : ''"
                                x-show="cardsOf(t).length">
```

- [ ] **Step 5: Run the test and watch it pass**

Run: `python tests/test_board_arrange_runtime.py`
Expected: PASS, and every other scenario in the file still passes.

- [ ] **Step 6: Rebuild Tailwind, sweep, bump, commit**

```bash
python tools/build_tailwind.py
python tools/test.py
```

Bump `config.yaml` to the next patch version, then:

```bash
git add -A
git commit -F /tmp/msg.txt   # subject: The card grid gets a named row and gutter (vX.Y.Z)
```

---

### Task 2: `rows` becomes a row span

The feature itself, on both grids.

**Files:**
- Modify: `templates/home.html:2301-2316` (`cellStyle`)
- Modify: `templates/home.html:3326-3352` (the `stack` case of `drawCard`)
- Test: `tests/test_board_card_grid.py` (create), `tests/test_board_arrange_runtime.py`

**Interfaces:**
- Consumes: `--nc-row` / `--nc-gap` from Task 1.
- Produces: cells carrying `grid-row: span N` and
  `height: calc(N * var(--nc-row) + (N-1) * var(--nc-gap))`. Task 3's resize
  handlers write the same two properties live.

- [ ] **Step 1: Write the failing geometry test**

Create `tests/test_board_card_grid.py`:

```python
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
  <div class="nc-cell" id="tall"  style="{tall}">tall</div>
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
  return { tall: box('tall'), a: box('topA'), b: box('topB') };
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
                .replace('{short}', cell(6, short_rows)))
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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} card-grid scenarios passed")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python tests/test_board_card_grid.py`
Expected: this test lays out cells with the *new* style strings, so it passes
even before the renderers change — which is the point of Step 3: it proves the
CSS half is sound. Run it now and confirm PASS; if it fails, the `.nc-stack-grid`
rules are wrong, not the renderers.

- [ ] **Step 3: Write the failing renderer test**

In `tests/test_board_arrange_runtime.py`'s `PROBE`, the existing `sizedDraw`
already draws a stack with `grid: {cols: 6, rows: 3}`. Add to the JSON payload:

```js
  sizedSpan: /grid-row:span 3/.test(sizedDraw),
  sizedHeight: /calc\(3 \* var\(--nc-row\) \+ 2 \* var\(--nc-gap\)\)/.test(sizedDraw),
  cellSized: b.cellStyle({ id: 'c', cols: 6, rows: 3, type: 'chores', config: {} }),
  cellUnsized: b.cellStyle({ id: 'd', cols: 12, rows: 0, type: 'chores', config: {} }),
```

and the scenario:

```python
def scenario_a_sized_card_spans_rows_rather_than_owning_one():
    """A CSS height does not make a cell part of the grid's vertical geometry.
    Spanning rows is what lets a shorter card sit beside a taller one instead
    of below it, and it is what Home Assistant's own sections view does."""
    got = _run()
    if got is None:
        return
    check(got['sizedSpan'],
          "a sized card in a Home Assistant stack still owns a single row")
    check(got['sizedHeight'],
          "the stack cell's height is not the span formula")
    check('grid-row:span 3' in got['cellSized']
          and 'var(--nc-gap)' in got['cellSized'],
          f"a sized card in a Custom tile does not span rows: {got['cellSized']}")
    check('grid-row' not in got['cellUnsized'],
          f"an unsized card should span one automatic row, not a stated one: "
          f"{got['cellUnsized']}")
```

- [ ] **Step 4: Run it and watch it fail**

Run: `python tests/test_board_arrange_runtime.py`
Expected: FAIL — "a sized card in a Home Assistant stack still owns a single row".

- [ ] **Step 5: Span the rows in both renderers**

`templates/home.html`, `cellStyle` (~:2301):

```js
                cellStyle(c) {
                    let s = `grid-column:span ${c.cols};`;
                    if (this.cardIsFill(c) && this.cardFillPx[c.id]) {
                        return s + `height:${this.cardFillPx[c.id]}px`;
                    }
                    // A stated height SPANS: a cell that merely stands N rows
                    // tall still owns one row track, so the card beside it
                    // wraps under its bottom edge instead of stacking in the
                    // space it left. The gutters between the spanned rows are
                    // the card's too, or a tall card and the stack beside it
                    // drift apart by a gutter per row.
                    if (c.rows) {
                        return s + `grid-row:span ${c.rows};`
                            + `height:calc(${c.rows} * var(--nc-row)`
                            + ` + ${c.rows - 1} * var(--nc-gap))`;
                    }
                    // A DRAWN card with no height of its own (a map, a mounted
                    // calendar, a camera) is the one case where "as tall as the
                    // content" has no answer: the content is laid out INTO the
                    // box, so with no box there is nothing to lay it into and
                    // the card collapsed to its padding. An absolute floor, not
                    // four rows of one: on a board whose row is 10px, four rows
                    // is a collapsed card again.
                    if (this.cardFills(c)) return s + 'min-height:224px';
                    return s;
                },
```

`templates/home.html`, the `stack` case of `drawCard` (~:3332):

```js
                                const rows = g.rows
                                    ? `grid-row:span ${g.rows};height:calc(${g.rows}`
                                      + ` * var(--nc-row) + ${g.rows - 1} * var(--nc-gap))`
                                    : '';
```

- [ ] **Step 6: Run both test files and watch them pass**

```bash
python tests/test_board_arrange_runtime.py
python tests/test_board_card_grid.py
```
Expected: PASS.

- [ ] **Step 7: Sweep, bump, commit**

```bash
python tools/test.py
```
Bump `config.yaml`; commit with subject
`A card spans rows, so a short card can sit beside a tall one (vX.Y.Z)`.

---

### Task 3: The caps and the drag pitch follow the row

At a 10px board row, a cap of 40 rows tops a card out at 400px, and a resize
pitch hardcoded to 56 runs at five times the hand.

**Files:**
- Modify: `templates/home.html:4738-4745` (`setCardNum`'s clamp)
- Modify: `templates/home.html:1089` (the rows input's `max`)
- Modify: `templates/home.html:4864-4891` (`resizeTileCard`)
- Modify: `templates/home.html:3910-3956` (`resizeCardCell`)
- Modify: `services/home_board.py:3566` and `:3611` (the server's clamp)
- Test: `tests/test_board_cards.py`, `tests/test_board_arrange_runtime.py`

**Interfaces:**
- Consumes: `--nc-row` / `--nc-gap` on the grid element (Task 1), and the span
  formula (Task 2).
- Produces: card `rows` accepted in 0..1000 on both client and server.

- [ ] **Step 1: Write the failing server test**

In `tests/test_board_cards.py`, extend `scenario_a_card_is_sized_in_twelfths_of_its_tile`
by appending:

```python
    # The row is the BOARD's now, and a board row is 10px on every board in
    # this house. Forty of them is 400px — shorter than most tiles, which is a
    # cap that would stop a card being told to fill one.
    tall = _with_builders({'chores': _Spy()}, lambda: _custom(
        [{'type': 'chores', 'config': {'rows': 200}}]))
    check(tall['cards'][0]['rows'] == 200,
          f"a card's height is capped below what a board row now needs: "
          f"{tall['cards'][0]}")
    silly = _with_builders({'chores': _Spy()}, lambda: _custom(
        [{'type': 'chores', 'config': {'rows': 90000}}]))
    check(silly['cards'][0]['rows'] == 1000, "a card's height is not clamped")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python tests/test_board_cards.py`
Expected: FAIL — a card's `rows` comes back as 40, not 200.

- [ ] **Step 3: Raise the server's clamp**

`services/home_board.py`, both places that read a card's rows (`:3566` in
`_build_card` and `:3611` in the editing stub):

```python
        'rows': _cfg_int(config, 'rows', 0, 0, 1000),
```

- [ ] **Step 4: Run it and watch it pass**

Run: `python tests/test_board_cards.py`
Expected: PASS.

- [ ] **Step 5: Write the failing client test**

In `tests/test_board_arrange_runtime.py`'s `PROBE`, after the existing
`setCardNum` calls, add:

```js
// The rows a board row's worth of card actually needs.
b.setCardNum(draftCards[0], 'rows', 200, 0);
const tallRows = draftCards[0].config.rows;
b.setCardNum(draftCards[0], 'rows', 90000, 0);
const clampedRows = draftCards[0].config.rows;
b.setCardNum(draftCards[0], 'rows', 3, 0);
```

and to the payload:

```js
  tallRows: tallRows,
  clampedRows: clampedRows,
```

with the scenario:

```python
def scenario_a_card_can_be_as_tall_as_the_board_allows():
    """The cap was forty 56px rows. On a 10px board row that is 400px, so the
    number that used to mean 'taller than any tile' now means 'shorter than
    most of them'."""
    got = _run()
    if got is None:
        return
    check(got['tallRows'] == 200,
          f"a card cannot be told to stand 200 board rows tall: {got['tallRows']}")
    check(got['clampedRows'] == 1000,
          f"a pasted absurdity is not clamped: {got['clampedRows']}")
```

- [ ] **Step 6: Run it and watch it fail**

Run: `python tests/test_board_arrange_runtime.py`
Expected: FAIL — `tallRows` is 40.

- [ ] **Step 7: Raise the client clamp, the input, and both pitches**

`setCardNum` (~:4740):

```js
                    v = key === 'rows' ? Math.max(0, Math.min(1000, v))
                                       : Math.max(1, Math.min(12, v));
```

The rows input at `templates/home.html:1089`:

```html
                            <input type="number" min="0" max="1000" step="1"
```

`resizeTileCard` (~:4866), replacing the hardcoded pitch and writing the span:

```js
                    const cs = grid ? getComputedStyle(grid) : null;
                    const gap = cs ? (parseFloat(cs.columnGap) || 0) : 12;
                    // A twelfth of the TILE, not of the board: a card's
                    // columns are spans of the grid its own tile lays out on.
                    const colW = ((grid ? grid.clientWidth : 0) - gap * 11) / 12 + gap;
                    // The row the GRID is on, not a number typed in here. The
                    // two disagreed for as long as 56 was written twice.
                    const rowUnit = cs
                        ? (parseFloat(cs.getPropertyValue('--nc-row')) || 56) : 56;
                    const rowGap = cs ? (parseFloat(cs.rowGap) || gap) : gap;
                    const rowH = rowUnit + rowGap;
```

and inside its `move`:

```js
                        cell.style.gridColumn = 'span ' + cols;
                        cell.style.gridRow = 'span ' + rows;
                        cell.style.height = 'calc(' + rows + ' * var(--nc-row) + '
                            + (rows - 1) + ' * var(--nc-gap))';
```

with the clamp on that line becoming `Math.min(1000, …)`.

`resizeCardCell` (~:3918) takes the same two reads (its grid resolves to 56px,
which is the point — the value comes from the grid either way) and the same
two-property write in its `move`.

- [ ] **Step 8: Run the client tests and watch them pass**

Run: `python tests/test_board_arrange_runtime.py`
Expected: PASS.

- [ ] **Step 9: Sweep, bump, commit**

```bash
python tools/build_tailwind.py
python tools/test.py
```
Bump `config.yaml`; subject
`A card is measured in board rows, all the way through (vX.Y.Z)`.

---

### Task 4: A card can be dragged into another Custom tile

**Files:**
- Modify: `templates/home.html:4836-4862` (`moveTileCard`)
- Modify: `templates/home.html:4812-4815` (`_cardsOf`, plus a new
  `_containerCards`)
- Test: `tests/test_board_arrange_runtime.py`

**Interfaces:**
- Consumes: `_cardsOf(tileId)`, `widgetMeta(type).container`, `tileCards(w)`,
  `showGlobalAlert(msg)`.
- Produces: `_containerCards(tileId)` → the draft card list of an unlocked
  container tile, or `null`. `moveTileCard` moves a card between draft lists.

- [ ] **Step 1: Write the failing test**

In `tests/test_board_arrange_runtime.py`, extend the harness's `document` with
an `elementFromPoint` the drag can steer, by adding above `globalThis.document`:

```js
// The cells and grids a cross-tile drag walks over. `elementFromPoint` is the
// only way the handler learns where the pointer is, so the stub answers with
// whichever cell the probe last aimed at.
globalThis.AIM = null;
function cardCell(tileId, cardId) {
  const grid = { dataset: { cards: tileId } };
  grid.closest = sel => sel === '[data-cards]' ? grid : null;
  const cell = { dataset: { path: `${tileId}-${cardId}` }, classList: {
    add: function () {}, remove: function () {} } };
  cell.closest = sel => sel === '[data-cards]' ? grid
                      : sel === '[data-path]' ? cell : null;
  return cell;
}
function emptyGrid(tileId) {
  const grid = { dataset: { cards: tileId } };
  grid.closest = sel => sel === '[data-cards]' ? grid : null;
  return grid;
}
```

and inside the `document` object:

```js
  elementFromPoint: function () { return globalThis.AIM; },
```

Then in `PROBE`, after the existing custom-tile block:

```js
// --- Dragging a card from one Custom tile into another.
b.page().widgets.push({ id: 'yours', type: 'custom', config: { cards: [
  { id: 'weather', type: 'weather', config: {} } ] } });
b.board.tiles.push({ id: 'yours', type: 'custom', locked: false, cards: [
  { id: 'yours-weather', type: 'weather', cols: 12, rows: 0, config: {}, data: {} } ] });
b.catalog = { widgets: [{ key: 'custom', container: true },
                        { key: 'chores' }, { key: 'weather' }, { key: 'map' }] };
b.load = () => {};                    // the redraw is a fetch; not this test's job

const drag = (fromTile, cardId, aim) => {
  const cards = b._cardsOf(fromTile);
  const at = cards.findIndex(c => c.id === cardId);
  const cell = cardCell(fromTile, cardId);
  b.moveTileCard({ clientX: 0, clientY: 0 }, cards, at, cell, fromTile);
  globalThis.AIM = aim;
  b.__move({ clientX: 400, clientY: 400 });     // past the 6px slack
  b.__up();
};

drag('mine', 'weather', cardCell('yours', 'weather'));
const afterCross = { mine: b._cardsOf('mine').map(c => c.id),
                     yours: b._cardsOf('yours').map(c => c.id) };

// A full tile refuses. Twelve is the server's limit, so a thirteenth would be
// dropped on the way in and the card would simply vanish.
const alerts = [];
globalThis.showGlobalAlert = m => alerts.push(m);
b.page().widgets.find(w => w.id === 'yours').config.cards =
  Array.from({ length: 12 }, (_, i) => ({ id: 'x' + i, type: 'chores', config: {} }));
drag('mine', 'chores', cardCell('yours', 'x0'));
const afterFull = { mine: b._cardsOf('mine').map(c => c.id),
                    yours: b._cardsOf('yours').length, said: alerts.length };

// A built-in tile is a locked container of one synthetic card. It has no card
// list to join, and inventing one for it would put a card somewhere the server
// will not keep it.
drag('mine', 'chores', cardCell('drives', 'drives'));
const afterLocked = b._cardsOf('mine').map(c => c.id);
```

with these lines added to the payload:

```js
  afterCross: afterCross,
  afterFull: afterFull,
  afterLocked: afterLocked,
```

The probe drives the handler's own listeners, so `moveTileCard` must expose
them: that is what `b.__move` / `b.__up` are, and Step 3 adds them.

Add the scenarios:

```python
def scenario_a_card_can_be_dragged_into_another_custom_tile():
    """The alternative was copying a card's YAML out of one tile and pasting it
    into a new card on the other, which is the long way round dragging already
    replaced for position and size."""
    got = _run()
    if got is None:
        return
    check(got['afterCross']['mine'] == ['chores'],
          f"the card did not leave the tile it was dragged out of: "
          f"{got['afterCross']}")
    check(got['afterCross']['yours'] == ['weather', 'weather-2'],
          f"the card did not land in the tile it was dropped on, with an id "
          f"the destination did not already hold: {got['afterCross']}")


def scenario_a_full_tile_refuses_a_card_and_says_so():
    """Twelve cards is the server's limit. A thirteenth would be dropped on the
    way in — the card would leave one tile and never arrive at the other."""
    got = _run()
    if got is None:
        return
    check(got['afterFull']['yours'] == 12,
          f"a thirteenth card was accepted: {got['afterFull']}")
    check(got['afterFull']['mine'] == ['chores'],
          f"the card left its tile anyway: {got['afterFull']}")
    check(got['afterFull']['said'] == 1,
          f"a refused drop said nothing, or said it once per pointer move: "
          f"{got['afterFull']}")


def scenario_a_built_in_tile_is_not_a_destination():
    """A built-in tile is a locked container of one synthetic card. Handing it
    a second one writes a card list the server will not keep."""
    got = _run()
    if got is None:
        return
    check(got['afterLocked'] == ['chores'],
          f"a card was dropped into a tile that cannot hold one: "
          f"{got['afterLocked']}")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python tests/test_board_arrange_runtime.py`
Expected: FAIL — `b.__move is not a function`.

- [ ] **Step 3: Add the container lookup**

In `templates/home.html`, beside `_cardsOf` (~:4812):

```js
                // The draft card list of a tile that can actually hold cards.
                // `tileCards` CREATES the list if it is missing, so asking it
                // about a built-in tile would quietly give that tile a card
                // list the server refuses to keep — the check has to come
                // first.
                _containerCards(tileId) {
                    const w = (this.page().widgets || []).find(x => x.id === tileId);
                    if (!w || !this.widgetMeta(w.type).container) return null;
                    return this.tileCards(w);
                },
```

- [ ] **Step 4: Teach the drag to cross tiles**

Replace `moveTileCard` (`templates/home.html:4836-4862`) with:

```js
                // A drag that leaves its tile MOVES the card. The alternative
                // a household had was copying the card's YAML out of one tile
                // and pasting it into a new card on the other, which is the
                // long way round this gesture already replaced for position
                // and size.
                //
                // Both lists are drafts, so a cross-tile move is two splices
                // and nothing else: no endpoint, no re-parse, and Cancel puts
                // both tiles back because it restores the whole page.
                moveTileCard(e, cards, at, cell, tileId) {
                    const startX = e.clientX, startY = e.clientY;
                    let moved = false, from = at, list = cards, host = tileId;
                    let said = false;
                    const move = (ev) => {
                        if (!moved) {
                            if (Math.hypot(ev.clientX - startX, ev.clientY - startY) < 6) return;
                            moved = true;
                            cell.classList.add('tile-dragging');
                        }
                        const over = document.elementFromPoint(ev.clientX, ev.clientY);
                        const grid = over && over.closest('[data-cards]');
                        if (!grid) return;
                        const onto = grid.dataset.cards;
                        const target = over.closest('[data-path]');
                        const seat = (l, tile) => {
                            if (!target) return l.length;
                            const id = String(target.dataset.path).slice(tile.length + 1);
                            const j = l.findIndex(c => c.id === id);
                            return j === -1 ? l.length : j;
                        };
                        if (onto === host) {
                            if (!target || target === cell) return;
                            const to = seat(list, host);
                            if (to === from) return;
                            list.splice(to, 0, list.splice(from, 1)[0]);
                            from = to;
                            return;
                        }
                        // A different tile. Only a container has a card list to
                        // join, and only twelve cards fit in one — a thirteenth
                        // is dropped server-side, which would look like a card
                        // that left one tile and never arrived at the other.
                        const dest = this._containerCards(onto);
                        if (!dest) return;
                        if (dest.length >= 12) {
                            if (!said) {
                                said = true;
                                showGlobalAlert('That tile is full — twelve cards '
                                    + 'is as many as one tile holds.');
                            }
                            return;
                        }
                        const card = list.splice(from, 1)[0];
                        // Ids are unique WITHIN a tile, and the destination may
                        // already hold a card of this type. Same mint as adding
                        // one by hand: the bare type, then type-2.
                        const taken = new Set(dest.map(c => c.id));
                        if (taken.has(card.id)) {
                            let id = card.type, n = 2;
                            while (taken.has(id)) id = `${card.type}-${n++}`;
                            card.id = id;
                        }
                        const to = seat(dest, onto);
                        dest.splice(to, 0, card);
                        list = dest; host = onto; from = to; said = false;
                    };
                    const up = () => {
                        window.removeEventListener('pointermove', move);
                        window.removeEventListener('pointerup', up);
                        window.removeEventListener('pointercancel', up);
                        cell.classList.remove('tile-dragging');
                        // The card is drawn from the SERVER's payload, which
                        // still has it in the tile it left; only a redraw can
                        // show it where the draft now says it is.
                        if (moved) this.load();
                    };
                    // Named on the component so the runtime test can drive the
                    // gesture: node has no pointer, and a drag nobody can run
                    // is a drag nobody can test.
                    this.__move = move;
                    this.__up = up;
                    window.addEventListener('pointermove', move);
                    window.addEventListener('pointerup', up);
                    window.addEventListener('pointercancel', up);
                },
```

- [ ] **Step 5: Run it and watch it pass**

Run: `python tests/test_board_arrange_runtime.py`
Expected: PASS on all three new scenarios.

- [ ] **Step 6: Sweep, bump, commit**

```bash
python tools/build_tailwind.py
python tools/test.py
```
Bump `config.yaml`; subject
`A card can be dragged from one Custom tile into another (vX.Y.Z)`.

---

### Task 5: The swallowed sub-card drag

A Home Assistant card inside a Custom tile takes the gesture and does nothing
with it.

**Files:**
- Modify: `templates/home.html:3846-3863` (`startCardDrag`)
- Test: `tests/test_board_arrange_runtime.py`

**Interfaces:**
- Produces: `_cardConfigHolder(drawnId)` → the record whose `config.config`
  holds a card's YAML: the widget itself for a top-level tile, or the card
  record inside a container tile.

- [ ] **Step 1: Write the failing test**

In `PROBE`:

```js
// An HA card INSIDE a Custom tile. Its drawn id is namespaced by the tile, so
// a straight lookup in `widgets` finds nothing — and the handler had already
// eaten the gesture by the time it discovered that.
b.page().widgets.push({ id: 'holder', type: 'custom', config: { cards: [
  { id: 'ha_card', type: 'ha_card', config: { config: 'type: gauge' } } ] } });
const holder = b._cardConfigHolder('holder-ha_card');
const topLevel = b._cardConfigHolder('mine');
const nobody = b._cardConfigHolder('holder-nothing');
```

payload:

```js
  holderYaml: (holder && holder.config || {}).config || null,
  holderTop: !!(topLevel && topLevel.type === 'custom'),
  holderMiss: nobody,
```

scenario:

```python
def scenario_a_card_inside_a_custom_tile_can_be_dragged():
    """A Home Assistant card sitting in a Custom tile is drawn with an id
    namespaced by its tile, which never appears in the page's widget list. The
    handler looked there, found nothing, and returned — having already called
    preventDefault, so the gesture was eaten with nothing said anywhere."""
    got = _run()
    if got is None:
        return
    check(got['holderYaml'] == 'type: gauge',
          f"a card inside a Custom tile cannot be resolved to its config: "
          f"{got['holderYaml']}")
    check(got['holderTop'], "a top-level tile is no longer its own holder")
    check(got['holderMiss'] is None,
          f"an id belonging to nothing resolved to something: {got['holderMiss']}")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python tests/test_board_arrange_runtime.py`
Expected: FAIL — `b._cardConfigHolder is not a function`.

- [ ] **Step 3: Add the lookup and stop swallowing the gesture**

In `templates/home.html`, above `startCardDrag` (~:3846):

```js
                // The record whose `config.config` holds a card's YAML. A
                // top-level tile is its own; a Home Assistant card sitting
                // INSIDE a Custom tile is one of that tile's cards, drawn with
                // an id namespaced by the tile — which is why looking it up in
                // `widgets` found nothing, and why dragging its sub-cards did
                // nothing at all with no error anywhere.
                _cardConfigHolder(drawnId) {
                    const widgets = this.page().widgets || [];
                    const direct = widgets.find(w => w.id === drawnId);
                    if (direct) return direct;
                    for (const w of widgets) {
                        for (const c of ((w.config || {}).cards || [])) {
                            if (`${w.id}-${c.id}` === drawnId) return c;
                        }
                    }
                    return null;
                },
```

and `startCardDrag` becomes:

```js
                async startCardDrag(e, tile) {
                    if (e.button > 0) return;
                    const grip = e.target.closest('.nc-card-move');
                    const grab = e.target.closest('.nc-card-size');
                    const cell = e.target.closest('[data-path]');
                    if (!cell || (!grip && !grab)) return;
                    // Resolved BEFORE the gesture is claimed: a drag with
                    // nowhere to go should reach whatever is under it rather
                    // than being eaten by a handler that then gives up.
                    const inst = this._cardConfigHolder(tile.id);
                    if (!inst) return;
                    e.preventDefault();
                    e.stopPropagation();          // never also drag the TILE

                    const config = await this.cardConfigOf(inst);
                    if (!config) return;

                    if (grab) return this.resizeCardCell(e, inst, config, cell);
                    return this.moveCardCell(e, inst, config, cell);
                },
```

- [ ] **Step 4: Run it and watch it pass**

Run: `python tests/test_board_arrange_runtime.py`
Expected: PASS.

- [ ] **Step 5: Sweep, bump, commit**

```bash
python tools/build_tailwind.py
python tools/test.py
```
Bump `config.yaml`; subject
`A card inside a Custom tile stops eating its own drag (vX.Y.Z)`.

---

### Task 6: Say what changed

**Files:**
- Modify: `system_capabilities.md` (the board/cards section)
- Modify: `chauffeur/config.yaml` (final version bump, if the previous task did
  not already land one)

- [ ] **Step 1: Update the capabilities document**

Add to the boards section, in the same voice as its neighbours: a card's `rows`
is a grid row span measured in the board's own `row_height` and `gap` (a Home
Assistant stack keeps HA's 56px, because those numbers were written against
HA's row); the cap is 1000; a card with no intrinsic height keeps a 224px floor;
and a card can be dragged from one Custom tile into another, refusing a full or
built-in destination and re-minting a colliding id.

- [ ] **Step 2: Full sweep**

Run: `python tools/test.py`
Expected: every file passes except any pre-existing failure recorded before this
work began (`test_coverage_ladder.py::scenario_nudges_come_when_a_reply_would_exist`
fails on a clean checkout and is not this work's).

- [ ] **Step 3: Commit and push**

```bash
git add -A
git commit -F /tmp/msg.txt   # subject: Cards span board rows and move between tiles (vX.Y.Z)
git push
```

- [ ] **Step 4: Deploy and look at it**

The add-on store caches the repository: *Check for updates* → rebuild → confirm
the version. Then, on a board with a Custom tile: give one card four rows and
two others two rows each, and confirm the two short ones stack beside the tall
one; drag a card into another Custom tile; drag one into a full tile and read
the refusal.

---

## Self-review

**Spec coverage.** Decision 1 (row spans, both grids) → Task 2. Decision 1b (the
board's row and gutter, the 1000 cap, the absolute floor, both resize pitches) →
Tasks 1 and 3. Decision 2 (cross-tile drag, container-only destinations, the
twelve cap, id re-mint, sizes travel unchanged, draft persistence) → Task 4. The
uncovered bug → Task 5. The spec's testing section → the tests in Tasks 2–5 plus
the deploy check in Task 6.

**Names.** `cardGridVars`, `_containerCards`, `_cardConfigHolder`, `__move`,
`__up` are each defined in the task that first uses them and referenced with the
same spelling afterwards. `--nc-row` and `--nc-gap` are declared in Task 1 and
read in Tasks 2 and 3.

**Deliberately not done:** dragging a card out onto the board or between boards,
a no-drag "Move to tile…" control, and per-tile row/gutter overrides — all three
are recorded as out of scope in the design.
