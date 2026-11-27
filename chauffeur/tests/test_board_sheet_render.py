"""Presentation boards UI rendering and interactions (Task 6).

Tests the board card (`renderBoardCard` and `renderMissionDoneCard` in
templates/app.html), the pure sheet renderers and deep-link parser in
static/board_sheet.js (via tests/pwa_pure.py), and the live DOM sheet lifecycle
(fetch, navigation, Escape, 404 state) in jsdom — all against the Task 1
contract fixture tests/fixtures/board_view_v1.json.

Named `test_board_sheet_render.py` because `tests/test_board_render.py` already
belongs to the wall home board (`home.html`).

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_board_sheet_render.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import ROOT, STATIC, TEMPLATES, check, pure_source, read, run_node  # noqa: E402

FIXTURE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'board_view_v1.json')
FIXTURE = json.load(open(FIXTURE_PATH, encoding='utf-8'))
SCRATCH = tempfile.mkdtemp(prefix='chauffeur_board_sheet_render_')


def _app_card_chunk():
    src = read(TEMPLATES, 'app.html')
    start = src.index('function renderCard(card)')
    end = src.index('async function answerAsk(', start)
    return src[start:end]


CARD_HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const [,, chunkPath, casesPath] = process.argv;
const cases = JSON.parse(fs.readFileSync(casesPath, 'utf8'));
const dom = new JSDOM('<!doctype html><body></body>');
global.window = dom.window;
global.document = dom.window.document;
function myRole() { return 'parent'; }
function mfEscape(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
eval(fs.readFileSync(chunkPath, 'utf8'));
const out = {};
for (const [name, card] of Object.entries(cases)) {
  try {
    const html = renderCard(card);
    const wrap = dom.window.document.createElement('div');
    wrap.innerHTML = html;
    const inlineHandlers = [];
    for (const el of Array.from(wrap.querySelectorAll('*'))) {
      for (const attr of Array.from(el.attributes)) {
        if (/^on/i.test(attr.name)) inlineHandlers.push(el.tagName + ':' + attr.name);
      }
    }
    out[name] = {
      html,
      text: wrap.textContent,
      scripts: wrap.querySelectorAll('script').length,
      inlineHandlers,
      imgs: Array.from(wrap.querySelectorAll('img')).map(i => i.getAttribute('src')),
      openBtns: Array.from(wrap.querySelectorAll('[data-board-open]')).map(b => ({
        tag: b.tagName,
        projectId: b.getAttribute('data-project-id'),
        boardId: b.getAttribute('data-board-id'),
        text: b.textContent.trim(),
      })),
    };
  } catch (e) {
    out[name] = { error: String(e && e.stack || e) };
  }
}
console.log(JSON.stringify(out));
"""


_CARDS_CACHE = {}


def _run_cards():
    if 'v' in _CARDS_CACHE:
        return _CARDS_CACHE['v']
    node = shutil.which('node')
    if not node:
        _CARDS_CACHE['v'] = None
        return None
    chunk_path = os.path.join(SCRATCH, 'card_chunk.js')
    with open(chunk_path, 'w', encoding='utf-8') as f:
        f.write(_app_card_chunk())
    harness_path = os.path.join(SCRATCH, 'card_harness.js')
    with open(harness_path, 'w', encoding='utf-8') as f:
        f.write(CARD_HARNESS)
    cases = {
        'card0': FIXTURE['cards'][0],
        'card1': FIXTURE['cards'][1],
        'card2': FIXTURE['cards'][2],
        'many_hero': {
            **FIXTURE['cards'][0],
            'hero': [
                f'api/projects/0f1e2d3c4b5a69788796a5b4c3d2e1f0/boards/b0a7d1e2f3a4b5c6d7e8f90a1b2c3d4e/image/lk_000000000{i}'
                for i in range(1, 7)
            ],
        },
        'hostile': {
            'kind': 'board',
            'board_id': "b1' onclick='alert(1)",
            'project_id': 'p1" onmouseover="alert(2)',
            'title': FIXTURE['views']['options']['options'][2]['title'],
            'summary_line': '<img src=x onerror=alert(1)> · O\'Neil "&" <b>',
            'kept': 1,
            'hero': [FIXTURE['cards'][0]['hero'][0]],
            'note': "O'Neil \"&\" <b> <script>x</script>",
        },
        'done_with_board': FIXTURE['mission_done'],
        'done_without_board': {**FIXTURE['mission_done'], 'boards': []},
        'done_hostile_board': {
            **FIXTURE['mission_done'],
            'boards': [{
                'board_id': "bid'1",
                'project_id': "pid'2",
                'title': FIXTURE['views']['options']['options'][2]['title'],
            }],
        },
        'done_null_board_entries': {
            **FIXTURE['mission_done'],
            'boards': [
                None,
                {},
                {'board_id': '', 'project_id': 'p0', 'title': 'Missing id'},
                {'board_id': 'b0a7d1e2f3a4b5c6d7e8f90a1b2c3d4e', 'project_id': '0f1e2d3c4b5a69788796a5b4c3d2e1f0', 'title': 'Valid board'},
            ],
        },
        'bad_hero_paths': {
            **FIXTURE['cards'][0],
            'hero': [
                '\\\\evil.com/x',
                '//evil.com/x',
                'https://evil.com/x.jpg',
                'api/../x',
                '/api/projects/0f1e2d3c4b5a69788796a5b4c3d2e1f0/boards/b0a7d1e2f3a4b5c6d7e8f90a1b2c3d4e/image/lk_0000000001',
            ],
        },
    }
    cases_path = os.path.join(SCRATCH, 'card_cases.json')
    with open(cases_path, 'w', encoding='utf-8') as f:
        json.dump(cases, f)
    proc = subprocess.run([node, harness_path, chunk_path, cases_path],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=60)
    check(proc.returncode == 0, f"card harness failed:\n{proc.stderr[-1500:]}")
    _CARDS_CACHE['v'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _CARDS_CACHE['v']


PURE_WANTED = [
    'boardSheetHtml',
    'boardCompareHtml',
    'boardListHtml',
    'boardHeroHtml',
    'parseBoardHash',
]

PURE_PROBE = r"""
const fixture = %(fixture)s;
const out = {
  document_defined: typeof document !== 'undefined',
  window_defined: typeof window !== 'undefined',
  optionsHtml: boardSheetHtml(fixture.views.options),
  compareHtml: boardSheetHtml(fixture.views.compare),
  compareDirect: boardCompareHtml(fixture.views.compare),
  listHtml: boardSheetHtml(fixture.views.list),
  listDirect: boardListHtml(fixture.views.list),
  unknownHtml: boardSheetHtml(Object.assign({}, fixture.views.list, { layout: 'map' })),
  hero1: boardHeroHtml(fixture.views.options.options[0]),
  hero2: boardHeroHtml(fixture.views.options.options[1]),
  hashSimple: parseBoardHash('#board-abc-def'),
  hashGood: parseBoardHash(fixture.deep_links.good),
  hashBad: fixture.deep_links.bad.map(h => parseBoardHash(h)),
  hashEmpty: [parseBoardHash(''), parseBoardHash('#other'), parseBoardHash(null)],
  badImgSheet: boardSheetHtml((() => {
    const v = JSON.parse(JSON.stringify(fixture.views.options));
    v.options[0].items = [
      { id: 'b1', slot_id: 's0', title: 'Bad1', url: 'https://demo.invalid/1', store: 'S', image: '\\\\evil.com/x', price: null, facts: [] },
      { id: 'b2', slot_id: 's1', title: 'Bad2', url: 'https://demo.invalid/2', store: 'S', image: '//evil.com/x', price: null, facts: [] },
      { id: 'b3', slot_id: 's2', title: 'Bad3', url: 'https://demo.invalid/3', store: 'S', image: 'https://evil.com/x.jpg', price: null, facts: [] },
      { id: 'b4', slot_id: 's3', title: 'Bad4', url: 'https://demo.invalid/4', store: 'S', image: 'api/../x', price: null, facts: [] },
    ];
    v.options = [v.options[0]];
    return v;
  })()),
};
console.log(JSON.stringify(out));
"""


_PURE_CACHE = {}


def _run_pure():
    if 'v' in _PURE_CACHE:
        return _PURE_CACHE['v']
    src = pure_source('board_sheet.js', PURE_WANTED)
    script = src + '\n' + (PURE_PROBE % {'fixture': json.dumps(FIXTURE)})
    _PURE_CACHE['v'] = run_node(script)
    return _PURE_CACHE['v']


JSDOM_INSPECT = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const [,, inputPath] = process.argv;
const inputs = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const out = {};
for (const [key, html] of Object.entries(inputs)) {
  const dom = new JSDOM('<!doctype html><body>' + html + '</body>');
  const doc = dom.window.document;
  const all = Array.from(doc.querySelectorAll('*'));
  const inlineHandlers = [];
  for (const el of all) {
    for (const attr of Array.from(el.attributes)) {
      if (/^on/i.test(attr.name)) inlineHandlers.push(el.tagName + ':' + attr.name);
    }
  }
  const forbiddenAttrs = ['data-board-react', 'data-board-keep', 'data-board-more', 'data-board-copy', 'data-board-commit'];
  const foundForbidden = [];
  for (const attr of forbiddenAttrs) {
    if (doc.querySelector('[' + attr + ']')) foundForbidden.push(attr);
  }
  const screens = Array.from(doc.querySelectorAll('[data-board-screen]'));
  out[key] = {
    text: doc.body.textContent,
    scripts: doc.querySelectorAll('script').length,
    inlineHandlers,
    foundForbidden,
    screens: screens.map(s => ({
      text: s.textContent,
      hasTotal: !!s.querySelector('[data-board-total]'),
      totalText: s.querySelector('[data-board-total]') ? s.querySelector('[data-board-total]').textContent.trim() : null,
      imgs: Array.from(s.querySelectorAll('img')).map(i => ({
        src: i.getAttribute('src'),
        loading: i.getAttribute('loading'),
      })),
      placeholders: s.querySelectorAll('[data-board-img-placeholder]').length,
    })),
    links: Array.from(doc.querySelectorAll('a[href]')).map(a => ({
      href: a.getAttribute('href'),
      rel: a.getAttribute('rel'),
      target: a.getAttribute('target'),
      text: a.textContent.trim(),
    })),
    tables: doc.querySelectorAll('table').length,
    tableHeaders: Array.from(doc.querySelectorAll('table thead th')).map(th => th.textContent.trim()),
    tableRowLabels: Array.from(doc.querySelectorAll('table tbody tr th, table tbody tr td:first-child')).map(c => c.textContent.trim()),
    scrollHint: doc.querySelector('[data-board-scroll-hint]') ? doc.querySelector('[data-board-scroll-hint]').textContent.trim() : null,
    listItems: doc.querySelectorAll('[data-board-list-item]').length,
    imgs: Array.from(doc.querySelectorAll('img')).map(i => i.getAttribute('src')),
    placeholders: doc.querySelectorAll('[data-board-img-placeholder]').length,
  };
}
console.log(JSON.stringify(out));
"""


def _inspect_html(html_map):
    node = shutil.which('node')
    if not node:
        return None
    inp = os.path.join(SCRATCH, 'inspect_in.json')
    script = os.path.join(SCRATCH, 'inspect.js')
    with open(inp, 'w', encoding='utf-8') as f:
        json.dump(html_map, f)
    with open(script, 'w', encoding='utf-8') as f:
        f.write(JSDOM_INSPECT)
    proc = subprocess.run([node, script, inp], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', cwd=SCRATCH, timeout=60)
    check(proc.returncode == 0, f"jsdom inspect failed:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


SHEET_RUNTIME_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const { JSDOM } = require('jsdom');
const [,, tplPath, jsPath, fixturePath] = process.argv;
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const tplRaw = fs.readFileSync(tplPath, 'utf8')
  .replace(/<script[^>]*src=[^>]*><\/script>/gi, '')
  .replace(/\{#[\s\S]*?#\}/g, '')
  .replace(/\{%[\s\S]*?%\}/g, '')
  .replace(/\{\{[\s\S]*?\}\}/g, '');
const jsSrc = fs.readFileSync(jsPath, 'utf8');

async function runCase(mode) {
  const dom = new JSDOM('<!doctype html><body>' + tplRaw + '</body>', {
    url: 'http://localhost/app',
    runScripts: 'outside-only',
  });
  const w = dom.window;
  const calls = [];
  w.chfBase = mode === 'nested' ? '../' : '';
  w.fetch = async (url) => {
    calls.push(String(url));
    if (mode === '404') {
      return { ok: false, status: 404, json: async () => ({ detail: 'This board is no longer available.' }) };
    }
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(fixture.views.options)) };
  };
  const vmc = dom.getInternalVMContext();
  new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc);

  const pid = fixture.views.options.project_id;
  const bid = fixture.views.options.id;
  w.dispatchEvent(new w.CustomEvent('chf-board-open', { detail: { projectId: pid, boardId: bid } }));
  await new Promise(r => setTimeout(r, 30));

  const overlay = w.document.querySelector('[data-board-sheet]');
  const openHidden = overlay ? overlay.hidden : null;
  const bodyText = overlay ? overlay.textContent : '';
  const activeBefore = overlay ? overlay.getAttribute('data-active-index') : null;

  // ArrowRight advances screen
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  const activeAfterRight = overlay ? overlay.getAttribute('data-active-index') : null;

  // Escape closes
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  const closedHidden = overlay ? overlay.hidden : null;

  w.close();
  return { calls, openHidden, bodyText, activeBefore, activeAfterRight, closedHidden };
}

(async () => {
  const out = {
    ok: await runCase('ok'),
    nested: await runCase('nested'),
    notFound: await runCase('404'),
  };
  console.log(JSON.stringify(out));
})();
"""


def _run_sheet_runtime():
    node = shutil.which('node')
    if not node:
        return None
    tpl_path = os.path.join(TEMPLATES, 'components', 'board_sheet.html')
    js_path = os.path.join(STATIC, 'board_sheet.js')
    check(os.path.exists(tpl_path), f"missing {tpl_path}")
    check(os.path.exists(js_path), f"missing {js_path}")
    script = os.path.join(SCRATCH, 'sheet_runtime.js')
    with open(script, 'w', encoding='utf-8') as f:
        f.write(SHEET_RUNTIME_HARNESS)
    proc = subprocess.run([node, script, tpl_path, js_path, FIXTURE_PATH],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=60)
    check(proc.returncode == 0, f"sheet runtime failed:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


# --- Scenarios ---------------------------------------------------------------

def scenario_card_renders():
    got = _run_cards()
    if got is None:
        return
    c0 = got['card0']
    check('error' not in c0, c0.get('error'))
    check('Concert outfit' in c0['text'], f"card title missing: {c0['html']}")
    check('3 looks · from $118' in c0['text'], f"summary_line missing: {c0['html']}")
    check('0 kept' not in c0['text'], f"zero kept must not be drawn: {c0['html']}")
    check(len(c0['imgs']) == 3, f"3 hero imgs expected, got {c0['imgs']}")
    for src in c0['imgs']:
        check(src and not src.startswith('/'), f"image src must be relative: {src}")
    check(len(c0['openBtns']) == 1, f"one Open button expected: {c0['openBtns']}")
    btn = c0['openBtns'][0]
    check(btn['projectId'] == FIXTURE['cards'][0]['project_id'] and btn['boardId'] == FIXTURE['cards'][0]['board_id'],
          f"Open button data attributes wrong: {btn}")
    check('onclick=' not in c0['html'].lower(), f"no onclick allowed in generated HTML: {c0['html']}")

    c2 = got['card2']
    check('2 kept' in c2['text'], f"kept count > 0 must show: {c2['text']}")
    check('3 more looks around your kept dress and heels' in c2['text'], f"note must show: {c2['text']}")

    many = got['many_hero']
    check(len(many['imgs']) <= 4, f"at most 4 hero images on card, got {len(many['imgs'])}")


def scenario_card_hostile_strings():
    got = _run_cards()
    if got is None:
        return
    h = got['hostile']
    check('error' not in h, h.get('error'))
    check(h['scripts'] == 0, f"<script> executed/parsed in card: {h['html']}")
    check(not h['inlineHandlers'], f"inline handler leaked into card DOM: {h['inlineHandlers']}")
    check("Look \"3\" <script>x</script> it's" in h['text'], f"hostile title did not render as text: {h['text']}")
    check("O'Neil \"&\" <b>" in h['text'], f"hostile store/note did not render as text: {h['text']}")
    check('&#39;' in h['html'], f"single quotes must be escaped: {h['html']}")
    check(len(h['openBtns']) == 1 and h['openBtns'][0]['boardId'] == "b1' onclick='alert(1)",
          f"single quote broke attribute boundary: {h['openBtns']}")

    pure = _run_pure()
    if pure is None:
        return
    insp = _inspect_html({'options': pure['optionsHtml']})['options']
    check(insp['scripts'] == 0, "no <script> elements in sheet HTML")
    check(not insp['inlineHandlers'], f"no inline event handlers in sheet HTML: {insp['inlineHandlers']}")
    check("Look \"3\" <script>x</script> it's" in insp['text'], "option 3 hostile title renders as text")
    check("O'Neil \"&\" <b>" in insp['text'], "hostile store renders as text")
    check('<img src=x onerror=alert(1)>' in insp['text'], "hostile note renders as text")
    check('&#39;' in pure['optionsHtml'], "sheet escapes single quotes")


def scenario_sheet_options_compare_list():
    pure = _run_pure()
    if pure is None:
        return
    check(not pure['document_defined'] and not pure['window_defined'],
          "pure functions must run without document or window")
    insp = _inspect_html({
        'options': pure['optionsHtml'],
        'compare': pure['compareHtml'],
        'list': pure['listHtml'],
        'unknown': pure['unknownHtml'],
        'hero1': pure['hero1'],
        'hero2': pure['hero2'],
    })

    # Options layout
    opt = insp['options']
    check('Concert outfit' in opt['text'] and '3 looks · from $118' in opt['text'], "header shows title and summary_line")
    check(len(opt['screens']) == 3, f"options board must render 3 screens, got {len(opt['screens'])}")
    check(opt['screens'][0]['hasTotal'] and '$118' in opt['screens'][0]['totalText'],
          f"option 1 shows $118 total: {opt['screens'][0]}")
    check(not opt['screens'][1]['hasTotal'], f"option 2 with null total must show no total: {opt['screens'][1]}")
    check('null' not in opt['screens'][1]['text'].lower(), f"null leaked into option 2 text: {opt['screens'][1]['text']}")
    check(opt['screens'][2]['hasTotal'] and '$167' in opt['screens'][2]['totalText'],
          f"option 3 shows $167 total: {opt['screens'][2]}")
    # Facts on option 1
    check('Heel' in opt['screens'][0]['text'] and '2 in' in opt['screens'][0]['text'], "facts render as label/value")
    # Off-screen options load images lazily
    check(all(i['loading'] == 'lazy' for i in opt['screens'][1]['imgs']),
          f"off-screen option 2 images should be lazy: {opt['screens'][1]['imgs']}")
    check(all(i['loading'] == 'lazy' for i in opt['screens'][2]['imgs']),
          f"off-screen option 3 images should be lazy: {opt['screens'][2]['imgs']}")
    # Null image renders placeholder, not broken <img>
    check(opt['screens'][1]['placeholders'] >= 1, "null image renders a placeholder tile")
    check(all(i['src'] and not i['src'].startswith('/') for s in opt['screens'] for i in s['imgs']),
          "every sheet image src is relative")

    # Hero collage
    check(len(insp['hero1']['imgs']) == 3, f"look 1 hero collage has 3 images: {insp['hero1']['imgs']}")

    # Compare layout
    cmp_ = insp['compare']
    check(cmp_['tables'] >= 1, "compare board renders a table")
    # 1 label column + 3 item columns = 4 headers
    check(len(cmp_['tableHeaders']) == 4, f"compare table should have 1 label + 3 item columns: {cmp_['tableHeaders']}")
    for want in ('Lakeside Day Camp', 'Maker Camp', 'Nature Explorers'):
        check(any(want in h for h in cmp_['tableHeaders']), f"column header {want} missing: {cmp_['tableHeaders']}")
    for row_lbl in ('Price', 'Store', 'Dates', 'Ages', 'Distance', 'Hours'):
        check(any(row_lbl.lower() in r.lower() for r in cmp_['tableRowLabels']),
              f"compare row {row_lbl} missing: {cmp_['tableRowLabels']}")

    # List layout
    lst = insp['list']
    check(lst['listItems'] == 3, f"list board renders 3 items, got {lst['listItems']}")
    check('Water bottle, 24 oz' in lst['text'] and '$18' in lst['text'] and '$8.50' in lst['text'],
          f"list items and formatted prices render: {lst['text']}")

    # Unknown layout falls back to list
    check(insp['unknown']['listItems'] == 3, "unknown layout falls back to list layout")

    # Every outbound link across all layouts has rel="noopener noreferrer" and target="_blank"
    for name in ('options', 'compare', 'list'):
        links = insp[name]['links']
        check(len(links) >= 3, f"{name} board should have outbound links, got {len(links)}")
        for lk in links:
            check(lk['href'].startswith(('http://', 'https://')), f"{name} link scheme must be http(s): {lk}")
            check(lk['target'] == '_blank', f"{name} link missing target=_blank: {lk}")
            check(lk['rel'] == 'noopener noreferrer', f"{name} link missing rel=noopener noreferrer: {lk}")


def scenario_sheet_draws_no_controls_when_can_false():
    pure = _run_pure()
    if pure is None:
        return
    insp = _inspect_html({
        'options': pure['optionsHtml'],
        'compare': pure['compareHtml'],
        'list': pure['listHtml'],
    })
    for name, data in insp.items():
        check(not data['foundForbidden'], f"{name} board drew gated controls when can is all false: {data['foundForbidden']}")


def scenario_done_card_board_line():
    got = _run_cards()
    if got is None:
        return
    d = got['done_with_board']
    check('error' not in d, d.get('error'))
    check('Three looks from $118 to $167.' in d['text'], "done card keeps summary")
    check('Concert outfit' in d['text'], f"done card shows board title: {d['html']}")
    check(len(d['openBtns']) == 1, f"done card has Open button for board: {d['openBtns']}")
    btn = d['openBtns'][0]
    check(btn['projectId'] == FIXTURE['mission_done']['boards'][0]['project_id']
          and btn['boardId'] == FIXTURE['mission_done']['boards'][0]['board_id'],
          f"done card Open button attrs: {btn}")
    check('onclick=' not in d['html'].lower(), "done card board line uses no onclick")

    empty = got['done_without_board']
    check(len(empty['openBtns']) == 0, "done card with empty boards draws no Open button")

    hostile = got['done_hostile_board']
    check(hostile['scripts'] == 0 and '&#39;' in hostile['html'], f"done card escapes hostile board title: {hostile['html']}")


def scenario_deep_link_parses():
    pure = _run_pure()
    if pure is None:
        return
    check(pure['hashSimple'] == {'projectId': 'abc', 'boardId': 'def'}, f"simple hash: {pure['hashSimple']}")
    check(pure['hashGood'] == {
        'projectId': FIXTURE['views']['options']['project_id'],
        'boardId': FIXTURE['views']['options']['id'],
    }, f"good fixture hash: {pure['hashGood']}")
    for raw, parsed in zip(FIXTURE['deep_links']['bad'], pure['hashBad']):
        check(parsed is None, f"bad hash {raw!r} must return null, got {parsed!r}")
    for parsed in pure['hashEmpty']:
        check(parsed is None, f"empty/other hash must return null, got {parsed!r}")


def scenario_sheet_runtime_and_wiring():
    rt = _run_sheet_runtime()
    if rt is None:
        return
    pid = FIXTURE['views']['options']['project_id']
    bid = FIXTURE['views']['options']['id']
    check(rt['ok']['calls'] == [f'api/projects/{pid}/boards/{bid}'], f"expected fetch URL: {rt['ok']['calls']}")
    check(rt['ok']['openHidden'] is False, "sheet becomes visible on chf-board-open")
    check('Concert outfit' in rt['ok']['bodyText'], "sheet renders fetched board")
    check(rt['ok']['activeBefore'] == '0' and rt['ok']['activeAfterRight'] == '1',
          f"ArrowRight advances active option: {rt['ok']['activeBefore']} -> {rt['ok']['activeAfterRight']}")
    check(rt['ok']['closedHidden'] is True, "Escape closes sheet")

    check(rt['nested']['calls'] == [f'../api/projects/{pid}/boards/{bid}'],
          f"nested base prefix respected: {rt['nested']['calls']}")

    check('This board is no longer available.' in rt['notFound']['bodyText'],
          f"404 state copy missing: {rt['notFound']['bodyText']}")

    # Template wiring checks
    app_src = read(TEMPLATES, 'app.html')
    check("components/board_sheet.html" in app_src, "app.html includes components/board_sheet.html")
    check("chf-board-open" in app_src and "hashchange" in app_src, "app.html wires delegated click and hashchange")
    admin_src = read(TEMPLATES, 'components', 'projects_admin.html')
    check("components/board_sheet.html" in admin_src, "projects_admin.html includes components/board_sheet.html")
    proj_src = read(TEMPLATES, 'components', 'projects_page.html')
    check("r.kind === 'board'" in proj_src and "chf-board-open" in proj_src,
          "projects_page.html openRow dispatches chf-board-open for board rows")


FIX1_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const { JSDOM } = require('jsdom');
const [,, tplPath, jsPath, cssPath, fixturePath] = process.argv;
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const tplRaw = fs.readFileSync(tplPath, 'utf8')
  .replace(/<script[^>]*src=[^>]*><\/script>/gi, '')
  .replace(/\{#[\s\S]*?#\}/g, '')
  .replace(/\{%[\s\S]*?%\}/g, '')
  .replace(/\{\{[\s\S]*?\}\}/g, '');
const jsSrc = fs.readFileSync(jsPath, 'utf8');
const pwaCss = fs.readFileSync(cssPath, 'utf8');
const argyleRuleMatch = pwaCss.match(/\[data-audience="adult"\]\s*\.pwa-argyle\s*\{[^}]*\}/);
const argyleRule = argyleRuleMatch ? argyleRuleMatch[0] : '';

const flush = (ms) => new Promise(r => setTimeout(r, ms || 30));

function makeDom(url) {
  const html = '<!doctype html><html data-audience="adult"><head><style>' + argyleRule + '</style></head><body>'
    + '<button id="opener" type="button">Open board</button>'
    + '<div id="pwa-argyle-overlay" class="pwa-argyle"></div>'
    + tplRaw
    + '</body></html>';
  const dom = new JSDOM(html, { url: url || 'http://localhost/app', runScripts: 'outside-only' });
  const w = dom.window;
  w.chfBase = '';
  const vmc = dom.getInternalVMContext();
  return { dom, w, vmc };
}

function nextPop(w) {
  return new Promise(resolve => {
    let done = false;
    const fin = v => { if (!done) { done = true; resolve(v); } };
    w.addEventListener('popstate', () => setTimeout(() => fin('pop'), 0), { once: true });
    setTimeout(() => fin('timeout'), 200);
  });
}

async function runAll() {
  const out = {};

  // 1. z-index above .pwa-argyle and below 400 + overscroll-behavior: contain
  {
    const { w } = makeDom('http://localhost/app');
    const ov = w.document.querySelector('[data-board-sheet]');
    const argyle = w.document.getElementById('pwa-argyle-overlay');
    const ovStyle = w.getComputedStyle(ov);
    const argStyle = w.getComputedStyle(argyle);
    out.zindex = {
      boardZ: parseInt(ovStyle.zIndex, 10),
      argyleZ: parseInt(argStyle.zIndex, 10),
      overscroll: ovStyle.overscrollBehavior || ovStyle.getPropertyValue('overscroll-behavior'),
    };
    w.close();
  }

  // 2. Stale 500 error for board A (slow res.json() after fetch resolves) must not overwrite newer board B
  {
    const { w, vmc } = makeDom('http://localhost/app');
    let releaseAJson, markAJsonStarted;
    const aJsonStarted = new Promise(r => { markAJsonStarted = r; });
    const aJsonPromise = new Promise(r => { releaseAJson = r; });
    w.fetch = async (url) => {
      if (String(url).includes('boarda')) {
        return {
          ok: false,
          status: 500,
          json: async () => { markAJsonStarted(); return await aJsonPromise; },
        };
      }
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(fixture.views.options)) };
    };
    new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc);
    const pA = w.openBoardSheet('0f1e2d3c4b5a69788796a5b4c3d2e1f0', 'boarda');
    await aJsonStarted; // A is now parked inside `await res.json()` of the non-ok branch!
    const pB = w.openBoardSheet('0f1e2d3c4b5a69788796a5b4c3d2e1f0', fixture.views.options.id);
    await pB;
    releaseAJson({ detail: 'Server exploded for A' });
    await pA;
    await flush();
    const ov = w.document.querySelector('[data-board-sheet]');
    out.staleError = {
      hidden: ov.hidden,
      text: ov.textContent,
    };
    w.close();
  }

  // 3 & 10a. Deep link open -> close button clears hash & leaves clean history
  {
    const pid = fixture.views.options.project_id;
    const bid = fixture.views.options.id;
    const { w, vmc } = makeDom('http://localhost/app#board-' + pid + '-' + bid);
    let backCalls = 0;
    const realBack = w.history.back.bind(w.history);
    w.history.back = () => { backCalls++; return realBack(); };
    w.fetch = async () => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(fixture.views.options)) });
    new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc);
    const lenBefore = w.history.length;
    await w.openBoardSheet(pid, bid);
    const hashWhileOpen = w.location.hash;
    const stateWhileOpen = w.history.state;
    const p = nextPop(w);
    w.document.querySelector('[data-board-close]').click();
    await p;
    await flush(40);
    out.deepLinkCloseBtn = {
      lenBefore,
      lenAfter: w.history.length,
      hashWhileOpen,
      stateWhileOpen,
      hashAfterClose: w.location.hash,
      stateAfterClose: w.history.state,
      backCalls,
      hidden: w.document.querySelector('[data-board-sheet]').hidden,
    };
    w.close();
  }

  // 10b. Normal open -> Android Back (popstate) closes without calling history.back() again
  {
    const pid = fixture.views.options.project_id;
    const bid = fixture.views.options.id;
    const { w, vmc } = makeDom('http://localhost/app');
    w.history.replaceState({ pwaOverlay: 'argyle' }, '');
    let backCalls = 0;
    const realBack = w.history.back.bind(w.history);
    w.history.back = () => { backCalls++; return realBack(); };
    w.fetch = async () => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(fixture.views.options)) });
    new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc);
    await w.openBoardSheet(pid, bid);
    const stateOpen = w.history.state;
    const p = nextPop(w);
    realBack(); // simulated hardware Back
    await p;
    await flush(40);
    out.androidBack = {
      stateOpen,
      stateAfterBack: w.history.state,
      hidden: w.document.querySelector('[data-board-sheet]').hidden,
      extraBackCalls: backCalls,
    };
    w.close();
  }

  // 6 & 8. Focus restore, Tab trap, and Escape blocked by .pwa-prompt-overlay
  {
    const pid = fixture.views.options.project_id;
    const bid = fixture.views.options.id;
    const { w, vmc } = makeDom('http://localhost/app');
    w.fetch = async () => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(fixture.views.options)) });
    new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc);
    const opener = w.document.getElementById('opener');
    opener.focus();
    await w.openBoardSheet(pid, bid);
    const ov = w.document.querySelector('[data-board-sheet]');

    // Escape ignored when .pwa-prompt-overlay is present
    const promptDiv = w.document.createElement('div');
    promptDiv.className = 'pwa-prompt-overlay';
    w.document.body.appendChild(promptDiv);
    w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    const openUnderPrompt = !ov.hidden;
    promptDiv.remove();

    // Tab wraps from last focusable back to first inside dialog
    const focusables = Array.from(ov.querySelectorAll('a[href], button:not([disabled])')).filter(el => !el.closest('[hidden]'));
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    let tabWrappedToFirst = false;
    if (first && last) {
      last.focus();
      const tabEv = new w.KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
      w.document.dispatchEvent(tabEv);
      tabWrappedToFirst = w.document.activeElement === first && tabEv.defaultPrevented;
    }

    // Escape closes and restores focus to opener
    const escEv = new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    const p = nextPop(w);
    w.document.dispatchEvent(escEv);
    await p;
    await flush(30);
    out.focusAndEscape = {
      openUnderPrompt,
      tabWrappedToFirst,
      escPrevented: escEv.defaultPrevented,
      closed: ov.hidden,
      focusRestored: w.document.activeElement === opener,
    };
    w.close();
  }

  // 5. Compare scroll cue toggles has-more-right on overflow and clears at end
  {
    const pid = fixture.views.compare.project_id;
    const bid = fixture.views.compare.id;
    const { w, vmc } = makeDom('http://localhost/app');
    w.fetch = async () => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(fixture.views.compare)) });
    new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc);
    await w.openBoardSheet(pid, bid);
    const stage = w.document.querySelector('[data-board-compare-stage]');
    const wrap = w.document.querySelector('[data-board-table-wrap]');
    const hint = w.document.querySelector('[data-board-scroll-hint]');
    let scrollLeft = 0;
    if (wrap) {
      Object.defineProperty(wrap, 'clientWidth', { configurable: true, get: () => 350 });
      Object.defineProperty(wrap, 'scrollWidth', { configurable: true, get: () => 560 });
      Object.defineProperty(wrap, 'scrollLeft', { configurable: true, get: () => scrollLeft, set: v => { scrollLeft = v; } });
      wrap.dispatchEvent(new w.Event('scroll'));
    }
    const atStart = {
      hasMore: !!(stage && stage.classList.contains('has-more-right')),
      hintHidden: hint ? hint.hidden : null,
      hintText: hint ? hint.textContent.trim() : null,
    };
    if (wrap) {
      scrollLeft = 210;
      wrap.dispatchEvent(new w.Event('scroll'));
    }
    const atEnd = {
      hasMore: !!(stage && stage.classList.contains('has-more-right')),
    };
    out.compareScroll = { atStart, atEnd };
    w.close();
  }

  console.log(JSON.stringify(out));
}

runAll().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


_FIX1_CACHE = {}


def _run_fix1():
    if 'v' in _FIX1_CACHE:
        return _FIX1_CACHE['v']
    node = shutil.which('node')
    if not node:
        _FIX1_CACHE['v'] = None
        return None
    tpl_path = os.path.join(TEMPLATES, 'components', 'board_sheet.html')
    js_path = os.path.join(STATIC, 'board_sheet.js')
    css_path = os.path.join(STATIC, 'pwa_shell.css')
    script = os.path.join(SCRATCH, 'fix1_runtime.js')
    with open(script, 'w', encoding='utf-8') as f:
        f.write(FIX1_HARNESS)
    proc = subprocess.run([node, script, tpl_path, js_path, css_path, FIXTURE_PATH],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=60)
    check(proc.returncode == 0, f"fix1 harness failed:\n{proc.stderr[-1500:]}")
    _FIX1_CACHE['v'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _FIX1_CACHE['v']


def scenario_fix1_zindex_and_overscroll():
    got = _run_fix1()
    if got is None:
        return
    z = got['zindex']
    check(z['argyleZ'] == 300, f"expected .pwa-argyle z-index 300, got {z}")
    check(z['argyleZ'] < z['boardZ'] < 400, f"board overlay z-index must be > 300 and < 400, got {z}")
    check(z['overscroll'] == 'contain', f"overlay must set overscroll-behavior: contain, got {z}")


def scenario_fix1_stale_error_does_not_overwrite():
    got = _run_fix1()
    if got is None:
        return
    se = got['staleError']
    check(se['hidden'] is False, "newer board B stays open")
    check('Concert outfit' in se['text'] and 'Server exploded for A' not in se['text'],
          f"stale 500 from board A overwrote board B: {se['text'][:200]}")


def scenario_fix1_image_paths_held_to_contract():
    cards = _run_cards()
    if cards is None:
        return
    bad_card = cards['bad_hero_paths']
    check('error' not in bad_card, bad_card.get('error'))
    check(bad_card['imgs'] == [], f"card hero must drop non-contract image paths: {bad_card['imgs']}")

    pure = _run_pure()
    if pure is None:
        return
    insp = _inspect_html({'bad': pure['badImgSheet']})['bad']
    check(insp['imgs'] == [], f"sheet must emit no <img> for non-contract paths: {insp['imgs']}")
    check(insp['placeholders'] >= 4, f"non-contract image paths must render placeholders: {insp['placeholders']}")


def scenario_fix1_done_card_null_guard():
    cards = _run_cards()
    if cards is None:
        return
    d = cards['done_null_board_entries']
    check('error' not in d, d.get('error'))
    check(len(d['openBtns']) == 1 and d['openBtns'][0]['boardId'] == 'b0a7d1e2f3a4b5c6d7e8f90a1b2c3d4e',
          f"done card should skip null/empty board entries cleanly: {d['openBtns']}")


def scenario_fix1_deep_link_clear_and_android_back():
    got = _run_fix1()
    if got is None:
        return
    dl = got['deepLinkCloseBtn']
    check(dl['hidden'] is True, "sheet closed")
    check(dl['hashAfterClose'] == '', f"closing deep-linked sheet must clear hash: {dl}")
    check(dl['stateWhileOpen'] and dl['stateWhileOpen'].get('pwaOverlay') == 'board',
          f"opening sheet pushes pwaOverlay board state: {dl}")
    check(dl['backCalls'] == 1, f"button close pops pushed board state once: {dl}")

    ab = got['androidBack']
    check(ab['stateOpen'] and ab['stateOpen'].get('pwaOverlay') == 'board', f"board state pushed: {ab}")
    check(ab['hidden'] is True, f"Android Back closes sheet: {ab}")
    check(ab['stateAfterBack'] and ab['stateAfterBack'].get('pwaOverlay') == 'argyle',
          f"Back returns cleanly to underlying Argyle state: {ab}")
    check(ab['extraBackCalls'] == 0, f"Back close must not call history.back() a second time: {ab}")


def scenario_fix1_focus_trap_restore_and_prompt_escape():
    got = _run_fix1()
    if got is None:
        return
    fe = got['focusAndEscape']
    check(fe['openUnderPrompt'] is True, "Escape must not close sheet while .pwa-prompt-overlay is present")
    check(fe['tabWrappedToFirst'] is True, "Tab must stay trapped inside open board dialog")
    check(fe['escPrevented'] is True and fe['closed'] is True, "Escape closes sheet and prevents underlying overlay close")
    check(fe['focusRestored'] is True, "closing sheet must restore focus to opener")


def scenario_fix1_compare_scroll_cue():
    got = _run_fix1()
    if got is None:
        return
    cs = got['compareScroll']
    check(cs['atStart']['hasMore'] is True, f"overflowing compare table must show right-edge cue: {cs}")
    check(cs['atStart']['hintHidden'] is False and cs['atStart']['hintText'] == 'Swipe to see all 3',
          f"overflowing compare table must show 'Swipe to see all 3' hint: {cs}")
    check(cs['atEnd']['hasMore'] is False, f"right-edge fade must clear when scrolled to the end: {cs}")


FIX2_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const { JSDOM } = require('jsdom');
const [,, tplPath, jsPath, fixturePath] = process.argv;
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const tplRaw = fs.readFileSync(tplPath, 'utf8')
  .replace(/<script[^>]*src=[^>]*><\/script>/gi, '')
  .replace(/\{#[\s\S]*?#\}/g, '')
  .replace(/\{%[\s\S]*?%\}/g, '')
  .replace(/\{\{[\s\S]*?\}\}/g, '');
const jsSrc = fs.readFileSync(jsPath, 'utf8');

const flush = (ms) => new Promise(r => setTimeout(r, ms || 30));

function makeDom(url) {
  const html = '<!doctype html><html data-audience="adult"><body>'
    + '<button id="opener" type="button">Open board</button>'
    + tplRaw
    + '</body></html>';
  const dom = new JSDOM(html, { url: url || 'http://localhost/app', runScripts: 'outside-only' });
  const w = dom.window;
  w.chfBase = '';
  const vmc = dom.getInternalVMContext();
  return { dom, w, vmc };
}

function nextEvent(w, name, timeoutMs) {
  return new Promise(resolve => {
    let done = false;
    const fin = v => { if (!done) { done = true; resolve(v); } };
    w.addEventListener(name, ev => setTimeout(() => fin({ fired: true, state: ev.state }), 0), { once: true });
    setTimeout(() => fin({ fired: false, state: null }), timeoutMs || 250);
  });
}

async function runAll() {
  const out = {};
  const pid = fixture.views.options.project_id;
  const bid = fixture.views.options.id;
  const bid2 = fixture.views.compare.id;

  // 1. Stale {pwaOverlay: 'board'} left on current history entry after a reload while sheet is closed.
  {
    const { w, vmc } = makeDom('http://localhost/app?prev=1');
    w.history.replaceState({ marker: 'prev' }, '');
    w.history.pushState({ pwaOverlay: 'board', marker: 'reloaded' }, '', 'http://localhost/app?cur=1');
    const realBack = w.history.back.bind(w.history);
    w.fetch = async () => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(fixture.views.options)) });
    new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc);

    const hrefBefore = w.location.href;
    const lenBefore = w.history.length;

    await w.openBoardSheet(pid, bid);
    const lenWhileOpen = w.history.length;
    const pClose = nextEvent(w, 'popstate');
    w.document.querySelector('[data-board-close]').click();
    await pClose;
    await flush(40);

    const hrefAfterClose = w.location.href;
    const stateAfterClose = w.history.state;
    const lenAfterClose = w.history.length;
    const hiddenAfterClose = w.document.querySelector('[data-board-sheet]').hidden;

    const pBack = nextEvent(w, 'popstate');
    realBack();
    await pBack;
    await flush(40);

    out.staleAfterReload = {
      hrefBefore,
      lenBefore,
      lenWhileOpen,
      hrefAfterClose,
      stateAfterClose,
      lenAfterClose,
      hiddenAfterClose,
      hrefAfterExtraBack: w.location.href,
      stateAfterExtraBack: w.history.state,
    };
    w.close();
  }

  // 2. Fast reopen immediately after close survives the late popstate from close's history.back().
  {
    const { w, vmc } = makeDom('http://localhost/app');
    w.history.replaceState({ marker: 'home' }, '');
    w.fetch = async (url) => {
      const view = String(url).includes(bid2) ? fixture.views.compare : fixture.views.options;
      return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(view)) };
    };
    new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc);

    await w.openBoardSheet(pid, bid);
    const popLog = [];
    w.addEventListener('popstate', ev => { popLog.push(ev.state); });

    // Close triggers async history.back(), then immediately reopen before popstate fires.
    // Simulate browser delivering the in-flight popstate for the prior 'home' entry after reopen.
    const pPop = nextEvent(w, 'popstate');
    w.document.querySelector('[data-board-close]').click();
    const reopenPromise = w.openBoardSheet(pid, bid2);
    // Also dispatch a late popstate carrying the prior non-board state if jsdom's relative back landed on pushed state
    const popRes = await pPop;
    await reopenPromise;
    await flush(40);

    // Also test the exact Chromium ordering where history.back()'s popstate carries the pre-sheet state
    const { w: w2, vmc: vmc2 } = makeDom('http://localhost/app');
    w2.history.replaceState({ marker: 'home' }, '');
    w2.fetch = async () => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(fixture.views.compare)) });
    new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc2);
    // Intercept history.back to deliver the late popstate with the underlying 'home' state asynchronously
    w2.history.back = () => {
      setTimeout(() => {
        w2.dispatchEvent(new w2.PopStateEvent('popstate', { state: { marker: 'home' } }));
      }, 15);
    };
    await w2.openBoardSheet(pid, bid);
    const pLate = nextEvent(w2, 'popstate');
    w2.document.querySelector('[data-board-close]').click();
    const reopenPromise2 = w2.openBoardSheet(pid, bid2);
    await pLate;
    await reopenPromise2;
    await flush(40);

    const ov1 = w.document.querySelector('[data-board-sheet]');
    const ov2 = w2.document.querySelector('[data-board-sheet]');
    const nativeHiddenAfterPop = ov1.hidden;
    const nativeTextAfterPop = ov1.textContent.slice(0, 120);
    // Closing the reopened sheet afterwards returns cleanly to home
    const pClose2 = nextEvent(w, 'popstate');
    w.document.querySelector('[data-board-close]').click();
    await pClose2;
    await flush(40);
    out.fastReopen = {
      nativePopFired: popRes.fired,
      nativePopState: popRes.state,
      nativeHidden: nativeHiddenAfterPop,
      nativeText: nativeTextAfterPop,
      nativeStateAfterSecondClose: w.history.state,
      latePopHidden: ov2.hidden,
      latePopText: ov2.textContent.slice(0, 120),
    };
    w.close();
    w2.close();
  }

  // 3. Hash navigation into a running page: location.hash = '#board-...' fires hashchange.
  {
    const { w, vmc } = makeDom('http://localhost/app?prior=1');
    w.history.replaceState({ marker: 'prior' }, '');
    w.history.pushState({ marker: 'app' }, '', 'http://localhost/app');
    const realBack = w.history.back.bind(w.history);
    w.fetch = async () => ({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(fixture.views.options)) });
    new vm.Script(jsSrc, { filename: 'board_sheet.js' }).runInContext(vmc);

    // Wire the app.html hashchange listener (dispatches chf-board-open)
    w.addEventListener('hashchange', () => {
      const parsed = w.parseBoardHash(w.location.hash);
      if (parsed) {
        w.dispatchEvent(new w.CustomEvent('chf-board-open', {
          detail: Object.assign({}, parsed, { fromHashChange: true }),
        }));
      }
    });

    const lenBefore = w.history.length;
    const pHash = nextEvent(w, 'hashchange');
    w.location.hash = '#board-' + pid + '-' + bid;
    await pHash;
    await flush(50);

    const ov = w.document.querySelector('[data-board-sheet]');
    const openHidden = ov.hidden;
    const lenWhileOpen = w.history.length;
    const stateWhileOpen = w.history.state;

    const pClose = nextEvent(w, 'popstate');
    w.document.querySelector('[data-board-close]').click();
    await pClose;
    await flush(40);

    const closedHidden = ov.hidden;
    const hashAfterClose = w.location.hash;
    const hrefAfterClose = w.location.href;
    const stateAfterClose = w.history.state;
    const lenAfterClose = w.history.length;

    const pBack = nextEvent(w, 'popstate');
    realBack();
    await pBack;
    await flush(40);

    out.hashNavRunning = {
      lenBefore,
      openHidden,
      lenWhileOpen,
      stateWhileOpen,
      closedHidden,
      hashAfterClose,
      hrefAfterClose,
      stateAfterClose,
      lenAfterClose,
      hrefAfterBack: w.location.href,
      stateAfterBack: w.history.state,
    };
    w.close();
  }

  console.log(JSON.stringify(out));
}

runAll().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""

_FIX2_CACHE = {}


def _run_fix2():
    if 'v' in _FIX2_CACHE:
        return _FIX2_CACHE['v']
    node = shutil.which('node')
    if not node:
        _FIX2_CACHE['v'] = None
        return None
    tpl_path = os.path.join(TEMPLATES, 'components', 'board_sheet.html')
    js_path = os.path.join(STATIC, 'board_sheet.js')
    script = os.path.join(SCRATCH, 'fix2_runtime.js')
    with open(script, 'w', encoding='utf-8') as f:
        f.write(FIX2_HARNESS)
    proc = subprocess.run([node, script, tpl_path, js_path, FIXTURE_PATH],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=60)
    check(proc.returncode == 0, f"fix2 harness failed:\n{proc.stderr[-1500:]}")
    _FIX2_CACHE['v'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _FIX2_CACHE['v']


def scenario_fix2_stale_board_state_after_reload():
    got = _run_fix2()
    if got is None:
        return
    sr = got['staleAfterReload']
    check(sr['hiddenAfterClose'] is True, f"sheet must close on X: {sr}")
    check(sr['hrefAfterClose'] == sr['hrefBefore'],
          f"closing after stale reloaded board state must keep starting location: {sr}")
    check(sr['stateAfterClose'] and sr['stateAfterClose'].get('marker') == 'reloaded',
          f"closing must land back on the starting entry, not pop below it: {sr}")
    check(sr['lenWhileOpen'] == sr['lenBefore'] + 1,
          f"opening over stale board state must still push its own entry: {sr}")
    check(sr['hrefAfterExtraBack'] == 'http://localhost/app?prev=1'
          and sr['stateAfterExtraBack'] and sr['stateAfterExtraBack'].get('marker') == 'prev',
          f"entry below starting one must remain intact for Back: {sr}")


def scenario_fix2_fast_reopen_survives_late_popstate():
    got = _run_fix2()
    if got is None:
        return
    fr = got['fastReopen']
    check(fr['nativeHidden'] is False, f"sheet must stay open after fast reopen (native jsdom): {fr}")
    check(fr['nativeStateAfterSecondClose'] and fr['nativeStateAfterSecondClose'].get('marker') == 'home',
          f"closing reopened sheet afterwards must land back on home: {fr}")
    check(fr['latePopHidden'] is False, f"sheet must stay open when late popstate from close arrives: {fr}")
    check('Summer camp' in fr['latePopText'] or 'Lakeside' in fr['latePopText'],
          f"reopened compare board should remain rendered: {fr}")


def scenario_fix2_hash_navigation_into_running_page():
    got = _run_fix2()
    if got is None:
        return
    hn = got['hashNavRunning']
    check(hn['openHidden'] is False, f"hashchange navigation must open sheet: {hn}")
    check(hn['stateWhileOpen'] and hn['stateWhileOpen'].get('pwaOverlay') == 'board',
          f"hash-navigated entry should be marked as board overlay: {hn}")
    check(hn['closedHidden'] is True, f"sheet must close on X: {hn}")
    check(hn['hashAfterClose'] == '', f"closing hash-navigated sheet must leave no #board- hash: {hn}")
    check(hn['lenAfterClose'] <= hn['lenBefore'] + 1,
          f"history.length must grow by at most 1 compared with before navigation: {hn}")
    check(hn['hrefAfterClose'] == 'http://localhost/app'
          and hn['stateAfterClose'] and hn['stateAfterClose'].get('marker') == 'app',
          f"closing must return to the running app entry: {hn}")
    check(hn['hrefAfterBack'] == 'http://localhost/app?prior=1'
          and hn['stateAfterBack'] and hn['stateAfterBack'].get('marker') == 'prior',
          f"single Back after closing must reach prior entry, never a duplicate /app: {hn}")


SCENARIOS = [
    scenario_card_renders,
    scenario_card_hostile_strings,
    scenario_sheet_options_compare_list,
    scenario_sheet_draws_no_controls_when_can_false,
    scenario_done_card_board_line,
    scenario_deep_link_parses,
    scenario_sheet_runtime_and_wiring,
    scenario_fix1_zindex_and_overscroll,
    scenario_fix1_stale_error_does_not_overwrite,
    scenario_fix1_image_paths_held_to_contract,
    scenario_fix1_done_card_null_guard,
    scenario_fix1_deep_link_clear_and_android_back,
    scenario_fix1_focus_trap_restore_and_prompt_escape,
    scenario_fix1_compare_scroll_cue,
    scenario_fix2_stale_board_state_after_reload,
    scenario_fix2_fast_reopen_survives_late_popstate,
    scenario_fix2_hash_navigation_into_running_page,
]

if __name__ == '__main__':
    failed = 0
    try:
        for fn in SCENARIOS:
            try:
                fn()
                print(f"PASS {fn.__name__}")
            except Exception:
                failed += 1
                print(f"FAIL {fn.__name__}")
                traceback.print_exc()
        print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    raise SystemExit(1 if failed else 0)
