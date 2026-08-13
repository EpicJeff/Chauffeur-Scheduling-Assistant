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
    span = src[src.index('spanStyle(key, type) {'):]
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
    fn = src[src.index('isAuto(key, type) {'):]
    fn = fn[:fn.index(chr(10) + '                },')]
    check('fillsTile(type)' in fn,
          "a map or a timeline can be set to fit, which collapses it")
    check('.auto' in fn,
          "isAuto reads something other than the span's own switch")

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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} fit-to-content scenarios passed")
