"""A fit-to-content tile measures the right thing.

`rows` is a promise about height that a list cannot keep — four children with
eleven routine items each is a different height every morning — so a tile's
span can say `auto` and the client measures it instead. CSS cannot do this on
its own: the board's vertical lattice is 1px tracks, so a grid item with no row
span occupies one of them, and "as tall as the content" has to become a number.

The first cut of that measurement shipped to a wall and collapsed every fit
tile to its heading. It walked the tile's direct children and took the first
one's top and the last one's bottom, and a tile's direct children are not its
content:

  * `<template>` — Alpine's marker, no box, real node inserted beside it;
  * `<div class="contents">` — the built-in tile's body wrapper, `display:
    contents` deliberately (a box between a mosaic and its tile is a box that
    ends up zero pixels tall). It has NO BOX. Measuring it returns zeros;
  * the arrange nameplate and the resize grip — `x-show`, so present and
    `display: none` most of the time, absolutely positioned when shown.

The jsdom board probes could not see any of this, because jsdom does no layout:
every rect it hands back is already a fiction, so a measurement that reads the
WRONG elements looks exactly like one that reads the right ones. This file
drives the real function against a tile shaped like a real tile, with the boxes
stated, which is the only place that distinction is visible.

Run from chauffeur/:  python tests/test_fit_to_content.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_fit_'))

import tpl_source  # noqa: E402

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_fit_run_')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# A tile shaped like the real thing: the heading, the `display: contents` body
# wrapper the built-in tiles use, Alpine's leftover template markers, and the
# two arrange controls that are in the DOM at all times.
#
# The content runs y=100..900. Everything else is noise the measurement has to
# refuse, and the number to beat is 800 + the tile's own padding.
HARNESS = r"""
const box = (top, bottom) => ({ top, bottom, height: bottom - top, width: 300 });
const el = (spec) => ({
  tagName: spec.tag || 'DIV',
  _style: { display: spec.display || 'block', position: spec.position || 'static',
            paddingTop: spec.padTop || '0px', paddingBottom: spec.padBottom || '0px' },
  _rect: spec.rect || box(0, 0),
  children: spec.children || [],
  getBoundingClientRect() { return this._rect; },
});
globalThis.getComputedStyle = (n) => n._style;

const makeTile = () => {
  const content = el({ rect: box(150, 900) });      // the card
  const t = el({ padTop: '20px', padBottom: '20px', children: [
    // Alpine's marker for the heading row, then the heading it inserted.
    el({ tag: 'TEMPLATE' }),
    el({ rect: box(100, 140) }),
    // The built-in tile's body: `display: contents`, so NO BOX of its own —
    // a browser hands back zeros for it. The content is one level down.
    el({ display: 'contents', rect: box(0, 0), children: [
      el({ tag: 'TEMPLATE' }),
      content,
      el({ tag: 'TEMPLATE' }),
    ]}),
    // The arrange nameplate and the resize grip: in the DOM always.
    el({ display: 'none', rect: box(0, 0) }),
    el({ display: 'none', rect: box(0, 0) }),
  ]});
  t._content = content;
  return t;
};
const tile = makeTile();
const tile2 = makeTile();

// The same tile while ARRANGING: the chrome is shown, and it is absolutely
// positioned — a floating badge that must never inject layout height.
const arranging = el({ padTop: '20px', padBottom: '20px', children: [
  el({ rect: box(100, 140) }),
  el({ display: 'contents', children: [el({ rect: box(150, 900) })] }),
  el({ position: 'absolute', rect: box(60, 96) }),     // badge above the tile
  el({ position: 'absolute', rect: box(880, 920) }),   // grip past the bottom
]});

// And a tile whose content SHRANK, measured again from the same element.
const shrunk = el({ padTop: '20px', padBottom: '20px', children: [
  el({ rect: box(100, 140) }),
  el({ display: 'contents', children: [el({ rect: box(150, 300) })] }),
]});

// Drive watchAutoTile with stub observers and record what the
// ResizeObserver actually watches. The tile's height is imposed by us, so a
// tile-only watch measures once and goes stale — the RO has to reach the
// flow boxes.
const observed = [];
let mutate = null;
globalThis.ResizeObserver = class {
  observe(n) { observed.push(n); }
  disconnect() { observed.length = 0; }
};
globalThis.MutationObserver = class {
  constructor(cb) { mutate = cb; }
  observe() {} disconnect() {}
};
boardAuto.onMeasure = () => {};
watchAutoTile(tile, 't1');
const watched = observed.slice();
// A mutation swaps the children wholesale; the observer set must follow.
const swapped = el({ rect: box(100, 500) });
tile.children.length = 0;
tile.children.push(swapped);
mutate();
const rewatched = observed.slice();

console.log(JSON.stringify({
  settled: autoTileHeight(tile2),
  arranging: autoTileHeight(arranging),
  shrunk: autoTileHeight(shrunk),
  nothing: autoTileHeight(el({ children: [el({ tag: 'TEMPLATE' })] })),
  watchedContent: watched.includes(tile._content),
  watchedTile: watched.includes(tile),
  rewatchedSwap: rewatched.includes(swapped) && !rewatched.includes(tile._content),
}));
"""


_RESULT = {}


def _run():
    if _RESULT:
        return _RESULT.get('data')
    _RESULT['data'] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed')
        return None
    src = tpl_source.read('home.html')
    body = next(b for b in re.findall(r'<script>(.*?)</script>', src, re.S)
                if 'function autoTileHeight' in b)
    # Only the measuring half — the rest of that block is the Alpine component
    # and wants a DOM. Cut at the component's own factory.
    body = body[:body.index('function homeBoard()')]
    path = os.path.join(SCRATCH, 'run.mjs')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body + HARNESS)
    proc = subprocess.run([node, path], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=60)
    check(proc.returncode == 0, f"the measurement threw:\n{proc.stderr[-1500:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def scenario_the_measurement_finds_the_content_through_the_wrapper():
    """The bug that reached a wall. The body sits inside a `display: contents`
    element, which has no box — so a measurement that stops at the tile's
    direct children reads zeros for the only child that matters and every fit
    tile collapses to its heading."""
    got = _run()
    if got is None:
        return
    check(got['settled'] == 840,
          f"the content (y=100..900) plus 40px of tile padding is 840, "
          f"measured {got['settled']} — the `display: contents` body wrapper "
          f"is being measured instead of the content inside it")


def scenario_arrange_chrome_never_inflates_a_tile():
    """The nameplate is a floating badge and the grip hangs off the corner,
    both absolutely positioned. Out of flow is out of the measurement — a tile
    that grew while you were arranging it would fight the drag."""
    got = _run()
    if got is None:
        return
    check(got['arranging'] == 840,
          f"arrange chrome changed the measured height: {got['arranging']} "
          f"(the content is the same 840 either way)")


def scenario_a_tile_can_shrink_again():
    """The reason the tile's own `scrollHeight` is not used: the tile stretches
    to the area we gave it, so measuring the tile reports what we last set. It
    would converge upward and a lane that lost two items would keep its old
    height for the life of the page."""
    got = _run()
    if got is None:
        return
    check(got['shrunk'] == 240,
          f"a tile whose content shrank measured {got['shrunk']}, not 240")
    src = tpl_source.read('home.html')
    fn = src[src.index('function autoTileHeight'):]
    fn = fn[:fn.index(chr(10) + '        }') + 1]
    check('scrollHeight' not in fn and 'clientHeight' not in fn,
          "the measurement reads the tile's own box, which it also sets")


def scenario_an_empty_tile_measures_nothing_rather_than_guessing():
    """0 means "nothing to go on", and `spanStyle` falls back to the stored
    rows for it. Returning some minimum here would look like a measurement and
    pin every quiet tile to it."""
    got = _run()
    if got is None:
        return
    check(got['nothing'] == 0,
          f"a tile with no rendered content measured {got['nothing']}")
    src = tpl_source.read('home.html')
    span = src[src.index('spanStyle(key, type, config) {'):]
    span = span[:span.index(chr(10) + '                },')]
    check('this.autoPx[key] ||' in span,
          "a tile with no measurement yet does not fall back to its rows, so "
          "every board flashes a stack of one-pixel tiles on load")

def scenario_fit_survives_the_round_trip_to_settings_and_back():
    """The other half of "fit does nothing": a switch the editor sets and the
    server drops. `auto` rides in the tile's SPAN — the same dict `cols` and
    `rows` ride in — through the settings save, the page normaliser and the
    board payload the panel actually reads. Anything along there that assumed
    a span was two integers would silently take it back off."""
    from services import home_board
    saved = {'panel_pages': [
        {'slug': 'home', 'name': 'Home', 'v': 5, 'columns': 12,
         'widgets': [{'id': 'errand_list', 'type': 'errand_list', 'config': {}},
                     {'id': 'map', 'type': 'map', 'config': {}}],
         'spans': {'errand_list': {'cols': 6, 'auto': True},
                   'map': {'cols': 6, 'rows': 3}}},
    ]}
    page = home_board.find_page('home', saved)
    check(page['spans']['errand_list'].get('auto') is True,
          f"the page normaliser dropped `auto`: {page['spans']}")
    inst = next(w for w in page['widgets'] if w['id'] == 'errand_list')
    check((inst.get('span') or {}).get('auto') is True,
          f"the tile lost `auto` on its way through the instances: {inst}")
    check(page['spans']['map'] == {'cols': 6, 'rows': 3},
          f"a tile sized in rows was disturbed: {page['spans']['map']}")

    from services import storage
    real = storage.get_settings
    try:
        storage.get_settings = lambda: saved
        home_board._CACHE.clear()
        board = home_board.build(page='home')
        check(board['spans']['errand_list'].get('auto') is True,
              f"`auto` never reaches the panel: {board['spans']}")
    finally:
        storage.get_settings = real
        home_board._CACHE.clear()


def scenario_the_shipped_boards_ask_for_fit():
    """And the client honours it only where a height can be fitted TO — a map,
    a timeline and a mosaic are laid out into the tile, so `auto` would
    collapse them."""
    src = tpl_source.read('home.html')
    fn = src[src.index('isAuto(key, type, config) {'):]
    fn = fn[:fn.index(chr(10) + '                },')]
    check('canFit(type, config)' in fn,
          "a map or a mosaic can be set to fit, which collapses it")
    check('.auto' in fn,
          "isAuto reads something other than the span's own switch")


def scenario_fit_is_offered_per_instance_not_per_type():
    """Two questions were being answered by one list, and that is what made
    "which cards can fit" wrong twice.

      * `canFit` — does the content have a height of its OWN? Only this
        decides whether the toggle is offered.
      * `fillsTile` — does the tile IMPOSE its height on the content? That is
        the flex-vs-block question and it has a different answer.

    A calendar card is a mounted grid OR the payload-built list, so even
    `canFit` is per instance. The mounted halves must stay refused — a
    component handed no height draws an hour rail an inch tall — and `agenda`
    is a mount too (since v2.207) despite reading like a list, which is why
    the flowing view is named by INCLUSION rather than by excluding
    month/week/day. Exclusion is also how the NEXT view added to the component
    would silently get a fit it cannot honour.
    """
    src = tpl_source.read('home.html')
    fn = src[src.index('FLOWS_WHEN: {'):]
    fn = fn[:fn.index('},')]
    check("calendar:" in fn and "=== 'list'" in fn,
          f"the calendar's list view is not what decides this: {fn}")
    check('month' not in fn and 'week' not in fn,
          "the mounted views are decided by exclusion, so a view added to the "
          "component later defaults to fitting and collapses")

    # And every caller carries the instance, or the predicates above are
    # answering about a shape they cannot see.
    # `canFit` is asked in the tile's OVERLAY since v2.230.4 — the list row
    # that used to ask it as `canFit(w.type, w.config)` is gone.
    for call in ('tileFills(t)', 'cardFills(c)', 'fillsHere(t)',
                 'canFit(tileEd().type, tileEd().config)',
                 'spanStyle(t.id, t.type, t.config)',
                 'isAuto(t.id, t.type, t.config)'):
        check(call in src, f"`{call}` is not how fit is decided, so the "
                           f"toggle and the drawing can disagree")


def scenario_a_timeline_is_a_list_that_grows_downwards():
    """The claim that a drives card could only fit in Compact list was wrong,
    and challenged as such: "complex, but it is still essentially a list that
    grows vertically."

    It is. `renderSchedule` sizes each day section with an explicit
    `height: ${totalHeight}px` — the last block's end plus a margin, empty
    stretches already condensed — so there IS a number to fit to. Refusing it
    cost a household the one tile whose height changes most from one day to
    the next.

    The catch, and the reason this is not a one-line change: the timeline's
    wrapper carries `flex-1 min-h-0 overflow-auto`, and in a block parent
    `flex-1` is zero pixels tall. Worse, a scroll box would CAP the height
    being measured at whatever the tile already was, so the tile would fit its
    own current size forever. The wrapper has to flow when the tile fits.
    """
    tl = tpl_source.read('components/schedule_timeline.html')
    check('height: ${totalHeight}px' in tl,
          "the timeline no longer sizes its day sections in pixels, so there "
          "is nothing for `fit` to measure")

    body = tpl_source.read('components/board_tile_body.html')
    wrap = body[body.index("'board-timeline-scroll-' + t.id"):]
    wrap = wrap[:wrap.index('board-timeline"')]
    check('fillsHere(t)' in wrap,
          "the timeline's scroll box is unconditional, so a fitting drives "
          "tile measures a zero-height flex child or its own current size")
    check('flex-1' in wrap and 'overflow-auto' in wrap,
          "a drives tile that is NOT fitting lost its scroll box, so a busy "
          "day is clipped instead of scrolled")

def scenario_the_resize_observer_reaches_the_content():
    """The custom-tile report: fit measured once at mount and never again. The
    tile's height is imposed by us, so content growing INSIDE it — a hosted
    Home Assistant card settling, an image arriving in a cell — resizes
    nothing we were watching and mutates nothing. The ResizeObserver has to
    watch the flow boxes themselves, and re-collect them when a mutation
    swaps the children wholesale."""
    got = _run()
    if got is None:
        return
    check(got['watchedTile'] is True,
          "the tile itself is unwatched, so width rewraps go unseen")
    check(got['watchedContent'] is True,
          "the ResizeObserver never reaches the content, so a card that "
          "grows without a mutation is measured once at mount and never again")
    check(got['rewatchedSwap'] is True,
          "a mutation that replaced the children left the observer watching "
          "detached nodes")

# ── The second harness: a whole BOARD in jsdom, with stub observers that
# record which tiles were ever watched. jsdom does no layout, so this can say
# nothing about heights — but "was this tile measured at all" is a structural
# question, and it is the one both custom-tile fit reports turned out to be.
BOARD_HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});
const html = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');
const board = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const watched = [];
const errors = [];
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'http://localhost/home?panel=true',
  beforeParse(w) {
    w.fetch = (u) => Promise.resolve({ ok: true, text: () => Promise.resolve(''),
      json: () => Promise.resolve(String(u).includes('api/home_board') ? board : {}) });
    w.showGlobalAlert = () => {};
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.EventSource = function () { return { addEventListener() {}, close() {} }; };
    w.ResizeObserver = class { observe(n) { watched.push(n); } disconnect() {} };
  }
});
const win = dom.window;
win.addEventListener('error', e => {
  const m = (e.error && e.error.message) || e.message || '';
  if (!/EventSource/.test(m)) errors.push(m);
});
win.document.addEventListener('DOMContentLoaded', () => {
  const s = win.document.createElement('script');
  s.textContent = fs.readFileSync(require.resolve('alpinejs/dist/cdn.js'), 'utf8');
  win.document.head.appendChild(s);
});
setTimeout(() => {
  // Which TILE elements ended up under an observer.
  const ids = new Set();
  for (const n of watched) {
    const tile = n && n.closest ? n.closest('[data-tile-id]') : null;
    if (tile) ids.add(tile.dataset.tileId);
  }
  console.log(JSON.stringify({ errors: errors.slice(0, 3), watched: [...ids] }));
  process.exit(0);
}, 2500);
"""

# One built-in tile and one CUSTOM tile, both asked to fit. The custom tile's
# CARD is namespaced `tileid-cardid` — which is exactly how it went missing.
BOARD = {
    'tiles': [
        {'id': 'errand_list', 'type': 'errand_list', 'label': 'Errands',
         'locked': True, 'bare': False, 'config': {},
         'data': {'interactive': True, 'parts': {}},
         'cards': [{'id': 'errand_list', 'type': 'errand_list', 'icon': 'E',
                    'label': 'Errands', 'title': 'Errands', 'cols': 12,
                    'rows': 0, 'bare': False, 'config': {},
                    'data': {'interactive': True, 'parts': {}}}]},
        {'id': 'custom', 'type': 'custom', 'label': 'Mine', 'locked': False,
         'bare': False, 'config': {},
         'cards': [{'id': 'custom-weather', 'type': 'weather', 'icon': 'W',
                    'label': 'Weather', 'title': '', 'cols': 12, 'rows': 0,
                    'bare': True, 'config': {},
                    'data': {'days': [{'day': 'Mon', 'emoji': 'x',
                                       'hi': 80, 'lo': 60, 'rain': 0}]}}]},
    ],
    'spans': {'errand_list': {'cols': 6, 'auto': True},
              'custom': {'cols': 6, 'auto': True}},
    'columns': 12, 'row_height': 240, 'gap': 16,
    'hero': {}, 'page': {'slug': 'home', 'name': 'Home', 'icon': 'H'},
    'background': '', 'temp_now': None, 'statuses': [],
}


_BOARD_RESULT = {}


def _run_board():
    if _BOARD_RESULT:
        return _BOARD_RESULT.get('data')
    _BOARD_RESULT['data'] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed')
        return None
    have = subprocess.run([node, '-e',
                           "require.resolve('jsdom'); require.resolve('alpinejs')"],
                          capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom/alpinejs not resolvable')
        return None
    import types
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/home'),
                                query_params={})
    page = os.path.join(SCRATCH, 'board.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(main.templates.env.get_template('home.html').render(
            request=req, board_slug=''))
    data = os.path.join(SCRATCH, 'board.json')
    with open(data, 'w', encoding='utf-8') as f:
        json.dump(BOARD, f)
    probe = os.path.join(SCRATCH, 'board_probe.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(BOARD_HARNESS)
    proc = subprocess.run([node, probe, page, data], capture_output=True,
                          text=True, encoding='utf-8', errors='replace',
                          cwd=SCRATCH, timeout=180)
    check(proc.returncode == 0,
          "the board threw:\n" + proc.stderr[-1500:])
    _BOARD_RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _BOARD_RESULT['data']


def scenario_a_custom_tile_fits_too():
    """The wall's report, twice: fit works on built-in tiles and does nothing
    on custom ones — the tile just draws at whatever `rows` says.

    `syncAutoTiles` walked `drawnTiles()`, which flattens the board to CARDS.
    A built-in tile's card keeps the TILE's id (the card IS the tile), so the
    lookup found the element and fit worked. A custom tile's cards are
    namespaced `tileid-cardid`, so the tile's own id was never in that list,
    never looked up, never observed — and a span is a property of a TILE.
    """
    got = _run_board()
    if got is None:
        return
    check(not got['errors'],
          "the board threw while drawing: %s" % (got['errors'],))
    check('errand_list' in got['watched'],
          "a built-in tile set to fit was never measured: %s" % (got['watched'],))
    check('custom' in got['watched'],
          "a CUSTOM tile set to fit was never measured — it will draw at "
          "whatever `rows` says: %s" % (got['watched'],))
    src = tpl_source.read('home.html')
    fn = src[src.index('syncAutoTiles() {'):]
    fn = fn[:fn.index(chr(10) + '                },')]
    # The CALL, not the prose — the comment in there names the helper it
    # deliberately does not use.
    check('of this.drawnTiles()' not in fn,
          "syncAutoTiles walks the flattened CARD list again, so a custom "
          "tile's own id is not in it")

def scenario_a_missed_signal_cannot_outlive_a_second():
    """Three cuts of this have failed the same way: a fit tile is measured by
    EVENTS, one of the events turns out not to fire, the measurement lands
    once and the tile is wrong for the life of the page. A wall panel is up
    for weeks, so "wrong until something happens to it" is broken.

    The observers stay — they are what makes it feel instant — and the clock
    that is already ticking sweeps over them, so whatever they miss is
    corrected within a second and cannot persist.
    """
    src = tpl_source.read('home.html')
    check('remeasureAutoTiles()' in src,
          "nothing re-measures a fit tile that its observers missed")
    tick = src[src.index('tick() {'):]
    tick = tick[:tick.index(chr(10) + '                },')]
    check('remeasureAutoTiles' in tick,
          "the backstop exists but nothing runs it, so a missed signal is "
          "still permanent")
    # And the mutation watch covers STYLE, which is how half the height
    # changes on this board actually arrive (the digest sets its column count
    # with :style, so a 1-column strip settling into 4 adds no nodes at all).
    watch = src[src.index('function watchAutoTile'):]
    watch = watch[:watch.index(chr(10) + '        }')]
    check('attributes: true' in watch,
          "a height change that is only a style change goes unnoticed")


def scenario_a_fit_tile_says_what_it_measured():
    """Twice a fit tile came out the wrong height with nothing on screen to
    say whether the measurement was wrong or had never happened — two very
    different bugs. The arrange nameplate carries the number now."""
    src = tpl_source.read('home.html')
    fn = src[src.index('spanLabel(id, type, config) {'):]
    fn = fn[:fn.index(chr(10) + '                },')]
    check('autoPx' in fn and 'px' in fn,
          "the arrange label says `fit` without saying what it measured")
    check('measuring' in fn,
          "a tile that has not been measured yet is indistinguishable from "
          "one measured at zero")

def scenario_a_card_inside_a_tile_can_fit_too():
    """The third "fit is broken" report, and it was not the tile.

    A card in a custom tile gets `height: rows * --nc-row` when it has `rows`,
    and the only thing that ever SET rows was dragging the card's grip in
    arrange mode — nothing anywhere could put it back. A card left at a
    dragged height makes its TILE fit that height, which reads exactly as the
    tile's fit being broken: "says 512px but it's way too tall for the
    content." The tile was right; the card could not fit its own content.

    `rows: 0` has always meant "as tall as the content". It just had no
    control.
    """
    src = tpl_source.read('home.html')
    # The card's OVERLAY since v2.230.4, not its row in a list — the list is
    # gone, so the controls are read where they live now.
    card_row = src[src.index("setCardNum(cardEd(), 'cols'"):]
    card_row = card_row[:card_row.index('No panel behind this card')]
    check("setCardNum(cardEd(), 'rows'" in card_row,
          "a card's height cannot be edited, so a dragged one is permanent")
    check('fit' in card_row,
          "there is no way to put a dragged card back to fitting its content")
    # The cell only takes a height when the card HAS one — 0 stays auto.
    # The arithmetic moved into `cellStyle` when fill arrived (three heights
    # in one ternary chain is not markup), so the claim is checked there.
    cell = src[src.index('cellStyle(c) {'):]
    cell = cell[:cell.index(chr(10) + '                },')]
    check('if (c.rows)' in cell,
          "a card's cell is given a height unconditionally, so nothing can be "
          "content-sized")
    check('return s;' in cell,
          "a card with no height of its own is still given one, so `fit` on a "
          "card means nothing")

    # And the tile's arrange label names the cause, since the fix is one
    # level down and nothing else points at it.
    label = src[src.index('spanLabel(id, type, config) {'):]
    label = label[:label.index(chr(10) + '                },')]
    check('sized' in label,
          "a tile fitting a dragged card looks broken with nothing on screen "
          "to say the height came from the card")


def scenario_fill_asks_the_screen_instead_of_the_household():
    """The third height, and the report behind it: "what works on one display
    doesn't work on another if their resolutions are different." `rows` is a
    number somebody guesses and re-guesses per screen. `fit` answers it for
    lists and cannot answer it at all for a map, a frame or a calendar grid,
    whose content has no height of its own — those are exactly the tiles that
    single-subject boards are made of.

    Fill runs a tile from wherever it lands down to the bottom of the screen,
    on any display, with nothing to type. Offered on EVERY type, unlike fit:
    fill GIVES a height, and content that cannot fit is precisely content that
    wants to be given one.
    """
    src = tpl_source.read('home.html')

    # Exclusive with fit, enforced where the value is written rather than in
    # the markup — two checkboxes that can contradict each other put the
    # answer in whichever code path happens to read first.
    setter = src[src.index('setSpan(instanceId, axis, value) {'):]
    setter = setter[:setter.index(chr(10) + '                },')]
    check('SPAN_SWITCHES.includes(axis)' in setter
          and 'for (const k of this.SPAN_SWITCHES) delete cur[k]' in setter,
          "fit and fill can be on at once, so a tile claims two heights")
    check('!cur.auto && !cur.fill' in setter,
          "a fill tile at default width and one row is dropped from the "
          "spans, so fill does not survive a save")

    # Fit wins nothing when fill is set: a tile cannot be both as tall as its
    # content and as tall as what is left.
    auto = src[src.index('isAuto(key, type, config) {'):]
    auto = auto[:auto.index(chr(10) + '                },')]
    check('!s.fill' in auto,
          "a tile with both flags set still measures its content")

    fn = src[src.index('measureFills() {'):]
    fn = fn[:fn.index(chr(10) + '                    this.measureCardFills();')]
    # DOCUMENT coordinates. The obvious version measures the viewport rect
    # against innerHeight, and then the tile's height changes as you SCROLL —
    # both sides of that subtraction move. On any board tall enough to scroll
    # that is a tile growing under your thumb.
    check('window.scrollY' in fn,
          "fill is measured in viewport coordinates, so the tile resizes "
          "while the board is scrolled")
    check('_bottomInset()' in fn,
          "a filled tile grows under the shelf")
    check('Math.max(this.rowHeight()' in fn,
          "a fill tile placed below the fold collapses to nothing, which is "
          "indistinguishable from a broken one")

    # Read from the shelf ELEMENT, not from a number kept in step with
    # nav.html — and zero in a browser, where there is no shelf.
    #
    # `offsetParent` is BANNED here, and this assertion used to require it —
    # which is the whole lesson. A structural test can only encode the
    # assumption its author had: the guard `shelf.offsetParent !== null` reads
    # like a visibility check and is defined to be null for anything
    # `position: fixed`, which the shelf is. So the guard was never true, the
    # height was never subtracted, every filled tile ran a shelf too far, and
    # the test agreed with it.
    #
    # A `display:none` shelf already measures zero, so the rect IS the
    # visibility test and no guard is needed at all. What the inset actually
    # comes out at is checked against stated boxes in
    # test_board_arrange_runtime — the only harness in the suite that can, and
    # the one this claim now leans on.
    inset = src[src.index('_bottomInset() {'):]
    inset = inset[:inset.index(chr(10) + '                },')]
    check("getElementById('panel-shelf')" in inset,
          "the shelf's height is hardcoded rather than read off the element")
    check('offsetParent' not in inset,
          "the shelf is position:fixed, so offsetParent is always null on it "
          "and any guard using it silently skips the shelf entirely")
    check('getBoundingClientRect' in inset,
          "the shelf's height is not measured, so a taller shelf is ignored")

    # The screen changing is the one signal fill must never miss.
    check('resize' in src[src.index('measureFills();'):src.index('measureFills();') + 4000]
          or "addEventListener('resize', () => this.measureFills())" in src,
          "a rotated wall or a resized window leaves every fill tile wrong")

    # And the arrange nameplate says what it resolved to, for the same reason
    # fit's does: wrong-height and never-measured are different bugs.
    label = src[src.index('spanLabel(id, type, config) {'):]
    label = label[:label.index(chr(10) + '                },')]
    check('fill' in label and 'measuring' in label,
          "a fill tile's nameplate does not say what it came out at")


def scenario_a_card_can_fill_its_tile_but_not_a_fitting_one():
    """Fill one level down: as tall as what is LEFT of the tile, which is what
    somebody means by a heading card over a map card.

    A fill card inside a FITTING tile is circular — the tile is as tall as its
    content while the content is as tall as the tile. Refused rather than
    resolved: a rule that silently picks one side of a circle behaves
    differently depending on which measurement landed first.
    """
    src = tpl_source.read('home.html')
    fn = src[src.index('measureCardFills() {'):]
    fn = fn[:fn.index(chr(10) + '                },')]
    check('isAuto(t.id, t.type, t.config)) continue' in fn,
          "a fill card inside a fitting tile is measured, which is circular")
    check('paddingBottom' in fn,
          "a filled card runs into its tile's padding")

    # A sized card stops the stack stretching, and a filled one is sized.
    free = src[src.index('tileFree(t) {'):]
    free = free[:free.index(chr(10) + '                },')]
    check('cardIsFill(c)' in free,
          "a stack holding a filled card still stretches its cells, so that "
          "card's height drags its neighbours to match")

    # rows and fill are exclusive on a card too — including via the drag grip,
    # which is the control that writes rows without going near the checkbox.
    num = src[src.index('setCardNum(c, key, raw, dflt) {'):]
    num = num[:num.index(chr(10) + '                },')]
    check('delete c.config.fill' in num,
          "dragging a filled card taller leaves it claiming both heights")


def scenario_an_emoji_field_can_be_filled_without_a_keyboard():
    """Nine fields in this app take an emoji and every one was a bare text
    box. On the two surfaces this app is FOR — a wall panel with no keyboard,
    a phone in one hand — that is a field you cannot fill: a kiosk browser has
    no emoji key, so those fields could only ever hold what was already in
    them.

    One picker, not a tenth text box, and plain globals rather than an Alpine
    component: it has to open from Alpine markup (the board editor), from
    string-built onclick handlers (the chat) and from x-model fields on pages
    that use Alpine differently.
    """
    src = tpl_source.read('components/emoji_picker.html')
    check('window.EmojiPicker' in src and 'open:' in src,
          "the picker is not reachable by the three callers that need it")
    check('RECENT_KEY' in src,
          "the picker has no memory, so the eighth 🐶 costs the same as the "
          "first")
    check('multi' in src,
          "adding three reactions is three trips through the picker")
    # Search matches NAMES. Searching the glyphs would mean typing an emoji to
    # find an emoji, which is the problem this exists to solve.
    check('it.q.indexOf(q)' in src,
          "the picker cannot be searched by word")
    # Focusing a text field on a wall panel pops the on-screen keyboard over
    # the grid somebody opened the picker to avoid using.
    check("hasAttribute('data-panel')" in src,
          "the picker takes focus on a wall panel and summons the keyboard "
          "it exists to replace")

    # Every page holding an emoji field includes it, or the button throws.
    # `tpl_source` INLINES includes, so this looks for the component's own
    # code in the rendered page rather than for the include statement.
    for page in ('home.html', 'chores.html', 'routines.html', 'config.html',
                 'app.html'):
        rendered = tpl_source.read(page)
        check('window.EmojiPicker' in rendered,
              f"{page} has an emoji field and no picker behind it")
        check('EmojiPicker.open' in rendered,
              f"{page} includes the picker and never opens it")

    # The board's own icon option is declared as an emoji field, so the
    # editor renders the picker rather than a text box.
    from services import home_board
    opt = next(o for o in home_board.catalog()['widgets'][0]['options']
               if o['key'] == 'icon')
    check(opt['type'] == 'emoji',
          f"a tile's icon is still a plain text field: {opt}")
    opts = tpl_source.read('components/board_options.html')
    check("o.type === 'emoji'" in opts and 'EmojiPicker.open' in opts,
          "the board editor has no branch for an emoji option")


def scenario_a_fitting_heading_keeps_its_descenders():
    """Fit measures the CONTENT's box and hands the tile exactly that many
    pixels, so anything a glyph paints outside its own line box is clipped —
    and Tailwind pairs `text-5xl` with a line-height of exactly 1, which is
    less than the em box of any real face. The tail of a g or a y therefore
    hung below the heading's line box and the tile cut it off. Invisible while
    a heading had a typed `rows` (a stated height leaves slack under the text)
    and reported the moment one was set to Fit.

    A line-height, not padding: the measurement reads boxes, so the fix has to
    be in the box or the paint and the number go on disagreeing.
    """
    body = tpl_source.read('components/board_tile_body.html')
    head = body[body.index("t.type === 'heading'"):]
    head = head[:head.index('</template>')]
    check('text-5xl' in head, "the heading scenario is looking at the wrong tile")
    check('leading-tight' in head or 'leading-' in head,
          "the heading sets no line-height, so a fitting tile clips its "
          "descenders")
    # And the class has to actually exist in the precompiled sheet — a class
    # Tailwind never generated fails silently, which is the whole hazard of a
    # built stylesheet.
    for sheet in ('tailwind.css', 'tailwind-app.css'):
        css = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'static', sheet), encoding='utf-8').read()
        check('.leading-tight' in css,
              f"{sheet} has no .leading-tight rule; rebuild tools/build_tailwind.py")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} fit-to-content scenarios passed")
