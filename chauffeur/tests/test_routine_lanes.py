"""The routines kiosk lanes became a card.

The Routines shelf button opened an editing surface: a routine editor per
member, a copy-from-somebody-else control, the prep kits. The kiosk mode of
that same page already knew the right answer — today's checklist per child,
tapped off with that child's identity — and it now lives in
components/routine_lanes.html, rendered by the page AND by the
`routines_lanes` board card.

What this file defends is what an extraction breaks:

  * IDENTITY IS PER LANE. Every check takes the tapped child's member_id from
    its own lane, passed per call and never stored. Two children at one kiosk
    are two lanes in use at once, and a hoisted "current member" would have
    each ticking off the other's routine — a bug one person testing alone
    would never see;
  * the celebration stays on the PAGE. It is a full-screen overlay, and a wall
    with four lane cards firing one each is a fault, not a party;
  * the section toggles gate real sections and the member filter slices the
    card's own copy;
  * `interactive: false` gives a DIV, not a dead button;
  * the builder ships config, never rows — the card self-fetches.

Run from chauffeur/:  python tests/test_routine_lanes.py
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
                      tempfile.mkdtemp(prefix='chauffeur_rlanes_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_rlanes_run_')
TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')

import tpl_source  # noqa: E402
from services import home_board  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


STREAKS = [
    {'member_id': 'm1', 'name': 'Emma', 'color_code': '#22d3ee', 'avatar': 'E',
     'image': None, 'status': {'emoji': '🌟', 'name': 'Star'},
     'streak': {'current': 4, 'today_done': 1, 'today_total': 2,
                'today_complete': False}},
    {'member_id': 'm2', 'name': 'Theo', 'color_code': '#f59e0b', 'avatar': 'T',
     'image': None, 'status': None,
     'streak': {'current': 0, 'today_done': 0, 'today_total': 1,
                'today_complete': False}},
]
DAY = {
    'm1': [{'id': 'r1', 'title': 'Brush teeth', 'time_of_day': '07:30', 'checked': False},
           {'id': 'r2', 'title': 'Homework', 'time_of_day': '16:00', 'checked': True}],
    'm2': [{'id': 'r3', 'title': 'Feed the cat', 'time_of_day': '18:00', 'checked': False}],
}

HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});
const html = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const errors = [], wrote = [];
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'http://localhost/routines?kiosk=true',
  beforeParse(w) {
    w.fetch = (u, opt) => {
      const s = String(u), m = (opt && opt.method) || 'GET';
      if (m !== 'GET') wrote.push(m + ' ' + s + ' ' + ((opt && opt.body) || ''));
      let body = [];
      if (s.includes('routines/streaks')) body = data.streaks;
      else if (s.includes('routines/day')) {
        const id = decodeURIComponent(s.split('member_id=')[1] || '');
        body = { items: data.day[id] || [] };
      } else if (s.includes('kids/digests')) body = { kids: {}, label: 'Tomorrow' };
      else if (s.includes('meals/plan')) body = { lines: [] };
      else if (s.includes('settings')) body = {};
      return Promise.resolve({ ok: true, text: () => Promise.resolve(''),
        json: () => Promise.resolve(body) });
    };
    w.showGlobalAlert = () => {};
    w.promptConfirm = () => Promise.resolve(false);
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.EventSource = function () { return { addEventListener() {}, close() {} }; };
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
  const doc = win.document, txt = e => e.textContent.replace(/\s+/g, ' ').trim();
  const kids = g => [...g.children].filter(c => c.tagName !== 'TEMPLATE').length;
  const grid = [...doc.querySelectorAll('div[style*="grid-template-columns"]')]
    .sort((a, b) => kids(b) - kids(a))[0];
  const lanes = grid ? [...grid.children].filter(c => c.tagName !== 'TEMPLATE') : [];

  // The card wrapper, driven directly — the slicing is what a card changes.
  const card = cfg => {
    const c = win.routineLanesCard({ data: cfg }, '');
    const rows = JSON.parse(JSON.stringify(data.streaks));
    c.lanesOnStreaks(rows);
    c.streaks = rows;
    return c;
  };
  const onlyEmma = card({ members: ['m1'] });
  const inert = card({ interactive: false });
  const noBar = card({ parts: { progress: false } });

  console.log(JSON.stringify({
    errors, wrote,
    laneCount: lanes.length,
    laneText: lanes.map(txt),
    // Each lane's tap has to carry ITS OWN member id.
    laneChecks: lanes.map(l => [...l.querySelectorAll('button')].length),
    cards: {
      filtered: onlyEmma.streaks.map(s => s.name),
      cols: onlyEmma.laneColumns(),
      inert: inert.lanesInteractive,
      defaultInteractive: card({}).lanesInteractive,
      progressOff: noBar.routineShow('progress'),
      itemsStillOn: noBar.routineShow('items'),
      // A card must not celebrate: the overlay is full-screen.
      celebrates: String(card({}).lanesOnChecked).includes('maybeCelebrate'),
    },
  }));
  process.exit(0);
}, 2500);
"""


def _render_routines():
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/routines'),
                                query_params={})
    return main.templates.env.get_template('routines.html').render(request=req)


_RESULT = {}


def _run():
    if _RESULT:
        return _RESULT.get('data')
    _RESULT['data'] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — the lanes were not drawn')
        return None
    have = subprocess.run([node, '-e',
                           "require.resolve('jsdom'); require.resolve('alpinejs')"],
                          capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom/alpinejs not resolvable')
        return None
    probe = os.path.join(SCRATCH, 'harness.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    page = os.path.join(SCRATCH, 'routines.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_routines())
    data = os.path.join(SCRATCH, 'data.json')
    with open(data, 'w', encoding='utf-8') as f:
        json.dump({'streaks': STREAKS, 'day': DAY}, f)
    proc = subprocess.run([node, probe, page, data], capture_output=True,
                          text=True, encoding='utf-8', errors='replace',
                          cwd=SCRATCH, timeout=180)
    check(proc.returncode == 0, f"the routines kiosk threw:\n{proc.stderr[-2000:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def scenario_one_lane_per_child_with_their_own_day():
    got = _run()
    if got is None:
        return
    check(not got['errors'], f"the kiosk threw while drawing: {got['errors'][:3]}")
    check(got['laneCount'] == 2, f"drew {got['laneCount']} lanes for two children")
    emma, theo = got['laneText']
    check('Emma' in emma and 'Theo' in theo, f"lanes are not in order: {got['laneText']}")
    check('Star' in emma, "an earned status did not reach the lane that earned it")
    check('4' in emma, "a lane is not showing its own streak")
    # The slicing is per lane and by member id: one child's checklist must
    # never appear in another's.
    check('Brush teeth' in emma and 'Brush teeth' not in theo,
          "a child's routine item is showing in another child's lane")
    check('Feed the cat' in theo and 'Feed the cat' not in emma,
          "a child's routine item is missing from their own lane")
    # And the household's clock, not the stored 24-hour string.
    check('7:30 AM' in emma, f"a routine time was printed raw: {emma[:120]}")


def scenario_looking_at_the_page_writes_nothing():
    got = _run()
    if got is None:
        return
    check(not got['wrote'], f"drawing the page called something: {got['wrote']}")


def scenario_identity_is_per_lane_and_never_stored():
    """The one unforgivable break. Every action takes the tapped child's
    member_id from its own lane's `s.member_id` — a hoisted "current member"
    would have two children at one kiosk ticking off each other's routine."""
    src = tpl_source.read('components/routine_lanes.html')
    check('toggleRoutineCheck(it.id, s.member_id' in src,
          "the check no longer passes the LANE's member id")
    logic = src[src.index('function routineLanesLogic'):]
    check('currentMember' not in logic and 'this.memberId' not in logic,
          "the lane logic holds an identity of its own")
    check('member_id: memberId' in logic,
          "the check does not send the member it was given")


def scenario_the_celebration_stays_on_the_page():
    got = _run()
    if got is None:
        return
    check(got['cards']['celebrates'] is False,
          "a lane card fires the full-screen status overlay; four of them on a "
          "wall is a fault, not a party")
    page = open(os.path.join(TPL, 'routines.html'), encoding='utf-8').read()
    check('maybeCelebrateStatusKiosk' in page,
          "the page lost the celebration at the tap that earned it")
    src = tpl_source.read('components/routine_lanes.html')
    check('maybeCelebrate' not in src,
          "the shared logic reaches for a helper a board need not include")


def scenario_a_card_filters_and_gates_its_own_copy():
    got = _run()
    if got is None:
        return
    c = got['cards']
    check(c['filtered'] == ['Emma'],
          f"the member filter did not slice the card: {c['filtered']}")
    check(c['cols'] == 1, f"one lane should be one column, got {c['cols']}")
    check(c['progressOff'] is False and c['itemsStillOn'] is True,
          f"turning one section off took another with it: {c}")
    check(c['defaultInteractive'] is True and c['inert'] is False,
          f"interactive is not on by default, or off does not stick: {c}")


def scenario_an_inert_lane_draws_no_button():
    """A display that draws dead buttons reads as broken. Alpine has no dynamic
    tag, so the row is a <button> in one branch and a <div> in the other, over
    one shared inside."""
    src = open(os.path.join(TPL, 'components', 'routine_lanes.html'),
               encoding='utf-8').read()
    check('{% macro routine_row()' in src,
          "the two row branches no longer share one inside, so they will drift")
    check(src.count('routine_row()') >= 3,
          "the row macro is defined and not used in both branches")
    check('<component' not in src,
          "the lane row uses a dynamic tag, which Alpine does not have")


def scenario_the_builder_ships_config_and_never_rows():
    from services import storage
    real = storage.get_routines
    try:
        storage.get_routines = lambda *a, **k: [{'id': 'r1'}]
        t = home_board._tile_routines_lanes(None, config={'show_streak': False,
                                                          'members': ['m1']})
        check(set(t) == {'interactive', 'members', 'parts'},
              f"the lanes payload carries more than config: {sorted(t)}")
        check(t['parts']['streak'] is False and t['parts']['items'] is True,
              f"a section toggle did not reach the card: {t['parts']}")
        check(t['members'] == ['m1'], f"the member filter was dropped: {t}")
        storage.get_routines = lambda *a, **k: []
        check(home_board._tile_routines_lanes(None) is None,
              "a household with no routines gets a tile about routines")
    finally:
        storage.get_routines = real


def scenario_the_routines_board_is_the_kiosk():
    page = home_board.builtin_page('routines', {})
    types_ = [w['type'] for w in page['widgets']]
    check(types_ == ['kids', 'routines_lanes'],
          f"the routines board is not the kiosk's own order: {types_}")
    # And the page's editors did not come with it.
    src = tpl_source.read('home.html')
    for editor in ('startEditItem(', 'saveEditItem(', 'copyRoutine('):
        check(editor not in src, f"the routines editor's {editor} is on the board")


def scenario_the_shared_logic_is_emitted_once_per_page():
    for name in ('routines.html', 'home.html'):
        src = tpl_source.read(name)
        check(src.count('function routineLanesLogic') == 1,
              f"{name} emits the shared lane logic "
              f"{src.count('function routineLanesLogic')} times")
    page = open(os.path.join(TPL, 'routines.html'), encoding='utf-8').read()
    check("import 'components/routine_lanes.html'" in page,
          "the routines page stopped rendering the shared macro")
    body = page[page.index('function routinesPage()'):]
    for gone in ('async loadStreaks(', 'async loadAllDayItems(',
                 'async toggleRoutineCheck(', 'formatClock(hhmm) {'):
        check(gone not in body,
              f"the page kept its own {gone!r} — two drawings again")
    for block in re.findall(r'<script>(.*?)</script>',
                            open(os.path.join(TPL, 'components',
                                              'routine_lanes.html'),
                                 encoding='utf-8').read(), re.S):
        check('{{' not in block and '{%' not in block,
              "Jinja leaked into the shared lane script")

def scenario_the_kid_digest_is_one_drawing_on_both_surfaces():
    """The tile predates the page's digest strip and drew a flat name-and-lines
    list. Nobody noticed for months because every board WITH a hero folds the
    kids into it — the Routines board was the first to actually show the tile,
    and it shipped the stale drawing to a wall. One macro now; this pins it.
    """
    # RENDERED, not include-inlined: `tpl_source` expands `include` and a
    # macro only expands where it is CALLED, so the raw text of a page that
    # imports the component never contains the lane markup.
    check('border-indigo-900/60' in _render_routines(),
          "the routines page no longer draws the digest lanes")
    check('border-indigo-900/60' in tpl_source.read('home.html'),
          "the board no longer draws the digest lanes")
    page = open(os.path.join(TPL, 'routines.html'), encoding='utf-8').read()
    check("import 'components/kid_digest_lanes.html'" in page,
          "the routines page stopped rendering the shared digest macro")
    check('border-indigo-900/60' not in page,
          "the routines page kept its own copy of the digest lanes — two "
          "drawings again, which is exactly how this drifted the first time")
    body = open(os.path.join(TPL, 'components', 'board_tile_body.html'),
                encoding='utf-8').read()
    check("import 'components/kid_digest_lanes.html'" in body
          and 'kidDigestCard(t)' in body,
          "the kids tile stopped rendering the shared digest macro")

    # And the builder speaks the macro's contract: entries carry the id the
    # rows are keyed by (the old member filter compared against a field that
    # did not exist and silently emptied every filtered tile), the day label
    # and the weather ride along, and the order is the page's.
    digest = {'label': 'Tomorrow', 'weather': 'Sunny.', 'kids': {
        'k2': {'name': 'Theo', 'lines': ['x'], 'tasks': [],
               'routine_count': 0, 'streak': 0},
        'k1': {'name': 'Emma', 'lines': [], 'tasks': ['Math due'],
               'routine_count': 2, 'streak': 4},
    }}
    t = home_board._tile_kids(None, kid_digest_fn=lambda: digest, config={})
    check([k['name'] for k in t['kids']] == ['Emma', 'Theo'],
          f"the tile's lanes are not in the page's order: {t['kids']}")
    check(all(k.get('id') for k in t['kids']),
          "a digest entry has no id, so the lane rows have no key")
    check(t.get('weather') == 'Sunny.' and t.get('label') == 'Tomorrow',
          f"the label or the weather was dropped: {t}")
    # Emma has no rides but has tasks and routines — the page shows her
    # ("free day" + the task), so the tile must not drop her.
    check(any(k['name'] == 'Emma' for k in t['kids']),
          "a kid with a quiet day but real tasks was dropped from the tile")
    filtered = home_board._tile_kids(None, kid_digest_fn=lambda: digest,
                                     config={'members': ['k1']})
    check([k['name'] for k in filtered['kids']] == ['Emma'],
          f"the member filter is comparing against a missing field again: "
          f"{filtered['kids']}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} routine-lane scenarios passed")
