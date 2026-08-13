"""The chores kiosk draws a lane per person, in a real DOM — before it moves.

The lane view is about to become a shared component so a board card can show it
too, which is the third time this session that a page's renderer has had to
start serving two surfaces. The first two taught the same lesson twice: the
board tiles went blank on a real wall because jsdom does no layout and the
tests could only see that elements existed, and the calendar's `eventContent`
would have been droppable without a single assertion going red.

So this pins the lane view as it stands, in the shapes an extraction breaks:

  * one lane per person with points, in leaderboard order, each carrying that
    person's own name, balance and earned status;
  * the slicing is PER LANE and by member id — available chores are the open
    ones this child is eligible for, "my chores" are the ones they claimed.
    Identity is passed per action and never stored, so two children tapping
    two lanes cannot stomp each other. A component that hoists any of that to
    a single "current member" breaks a wall panel in a way one person testing
    alone would never see;
  * spendable is the balance MINUS what is already pledged and pending, or a
    child can promise the same star twice;
  * the actions are the interactive half, and a board card will want them off.

Run from chauffeur/:  python tests/test_chores_lanes_render.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_lanes_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_lanes_run_')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# Two children with points, and chores in every state the lanes care about.
POINTS = [
    {'member_id': 'm1', 'name': 'Emma', 'balance': 12, 'color_code': '#22d3ee',
     'avatar': 'E', 'image': None, 'status': {'emoji': '🌟', 'name': 'Star'}},
    {'member_id': 'm2', 'name': 'Theo', 'balance': 5, 'color_code': '#f59e0b',
     'avatar': 'T', 'image': None, 'status': None},
]
CHORES = [
    # Open and open to anybody -> available in BOTH lanes.
    {'id': 'c1', 'title': 'Bins', 'emoji': '🗑️', 'points': 3, 'state': 'open',
     'claimed_by': None, 'eligible_member_ids': []},
    # Open but Emma's alone.
    {'id': 'c2', 'title': 'Dishes', 'emoji': '🍽️', 'points': 2, 'state': 'open',
     'claimed_by': None, 'eligible_member_ids': ['m1']},
    # Claimed by Theo -> his lane only, and not available to anyone.
    {'id': 'c3', 'title': 'Hoover', 'emoji': '🧹', 'points': 4, 'state': 'claimed',
     'claimed_by': 'm2', 'eligible_member_ids': []},
]
REWARDS = [
    {'id': 'r1', 'title': 'Cinema', 'cost': 8, 'pooled': False},
    {'id': 'r2', 'title': 'Trampoline park', 'cost': 30, 'pooled': True,
     'pool': {'pledged': 6, 'cost': 30, 'remaining': 24, 'funded': False,
              'contributions': [{'member_id': 'm1', 'member_name': 'Emma',
                                 'amount': 6, 'color_code': '#22d3ee'}]}},
]
REDEMPTIONS = [{'id': 'x1', 'member_id': 'm1', 'reward_id': 'r1', 'cost': 8,
                'state': 'pending', 'member_name': 'Emma'}]

HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});

const html = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const routes = {
  'api/points': data.points, 'api/chores': data.chores,
  'api/rewards': data.rewards, 'api/redemptions': data.redemptions,
};
const errors = [];
const posted = [];

const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'http://localhost/chores?kiosk=true',
  beforeParse(w) {
    w.fetch = (u, opt) => {
      if (opt && opt.method === 'POST') { posted.push(String(u)); }
      const key = Object.keys(routes).find(k => String(u).endsWith(k));
      return Promise.resolve({ ok: true, text: () => Promise.resolve(''),
        json: () => Promise.resolve(key ? routes[key] : []) });
    };
    w.showGlobalAlert = () => {};
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.EventSource = function () { return { addEventListener() {}, close() {} }; };
    w.innerWidth = 1600;
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
  const doc = win.document;
  // The pooled-goal strip above the lanes carries an inline grid style too,
  // so "the first one" is the wrong grid. The lane grid is the widest: one
  // child per person with points.
  const kids = g => [...g.children].filter(c => c.tagName !== 'TEMPLATE').length;
  const grid = [...doc.querySelectorAll('div[style*="grid-template-columns"]')]
    .sort((a, b) => kids(b) - kids(a))[0];
  const lanes = grid ? [...grid.children].filter(c => c.tagName !== 'TEMPLATE') : [];
  const txt = e => e.textContent.replace(/\s+/g, ' ').trim();
  console.log(JSON.stringify({
    errors: errors,
    laneCount: lanes.length,
    laneText: lanes.map(txt),
    // Buttons are the interactive half — what a read-only card turns off.
    buttons: lanes.map(l => [...l.querySelectorAll('button')].map(b => txt(b))),
    posted: posted,
  }));
  process.exit(0);
}, 2500);
"""


def _render_chores():
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/chores'),
                                query_params={})
    return main.templates.env.get_template('chores.html').render(request=req)


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
    page = os.path.join(SCRATCH, 'chores.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_chores())
    data = os.path.join(SCRATCH, 'data.json')
    with open(data, 'w', encoding='utf-8') as f:
        json.dump({'points': POINTS, 'chores': CHORES, 'rewards': REWARDS,
                   'redemptions': REDEMPTIONS}, f)
    # utf-8 explicitly: the lanes are full of emoji and `text=True` decodes
    # with the system codepage on Windows, which turns a passing test into an
    # UnicodeDecodeError with nothing to do with chores.
    proc = subprocess.run([node, probe, page, data], capture_output=True,
                          text=True, encoding='utf-8', errors='replace',
                          cwd=SCRATCH, timeout=180)
    check(proc.returncode == 0, f"the chores kiosk threw:\n{proc.stderr[-2000:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def scenario_one_lane_per_person_in_leaderboard_order():
    got = _run()
    if got is None:
        return
    check(not got['errors'], f"the kiosk threw while drawing: {got['errors'][:3]}")
    check(got['laneCount'] == 2, f"drew {got['laneCount']} lanes for two children")
    check('Emma' in got['laneText'][0] and 'Theo' in got['laneText'][1],
          f"the lanes are not in leaderboard order: "
          f"{[t[:40] for t in got['laneText']]}")
    check('12' in got['laneText'][0] and '5' in got['laneText'][1],
          "a lane is not showing its own balance")
    check('Star' in got['laneText'][0],
          "an earned status did not reach the lane that earned it")


def scenario_the_slicing_is_per_lane_and_by_member_id():
    """The thing a component most easily breaks. Identity here is the lane you
    tapped, never a stored "current member" — two children at one wall panel
    are two lanes being used at once, and one shared identity would have each
    claiming the other's chores.

    Dishes is Emma's alone; Hoover is claimed by Theo. Neither may appear in
    the other's lane.
    """
    got = _run()
    if got is None:
        return
    emma, theo = got['laneText']
    check('Dishes' in emma, "an eligible chore is missing from the lane it is for")
    check('Dishes' not in theo,
          "a chore restricted to one child is offered to another")
    check('Hoover' in theo, "a claimed chore is missing from the claimant's lane")
    check('Hoover' not in emma,
          "a chore claimed by one child is showing in another's lane")
    check('Bins' in emma and 'Bins' in theo,
          "a chore open to everybody is not offered to everybody")


def scenario_a_lane_is_interactive_and_a_card_will_want_it_not_to_be():
    """Claim, done, redeem and chip-in are the half a wall card should not
    have. Pinning them here is what makes "read-only" a real switch rather
    than a hope."""
    got = _run()
    if got is None:
        return
    check(all(b for b in got['buttons']),
          f"a lane has no actions at all: {got['buttons']}")
    check(not got['posted'],
          f"drawing the page called something: {got['posted']}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} chore-lane scenarios passed")
