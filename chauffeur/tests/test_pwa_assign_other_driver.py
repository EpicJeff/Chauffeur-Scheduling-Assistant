"""A parent assigns a family drive to ANY family driver from the PWA event
sheet (the hand path behind Argyle's reassign_driver), run in a real DOM.

Pinned shapes:
  * `renderAssignButtons(ev, wrap)` draws, for a PARENT on a non-errand,
    ONE tagged button (`data-assign-other`) reading "Assign
    driver", or "Change driver" when somebody already holds the drive, and
    nothing else (the user's call 2026-10-14: two buttons is clutter); an
    adult or a teen driver keeps the self-claim buttons and gets no picker
    (the user's call, same day: only a parent assigns others); an errand
    gets neither;
  * `assignDriver(ev)` asks who with promptChoice: Me first, then the
    family's other drivers (never the one already on it), asks which leg when
    the event has two (values: the leg ids, plus '__both__'), dry-runs the
    solver check, then POSTs one override per leg: `source: 'pwa'` when Me
    (a self-claim, no push about yourself) and `source: 'pwa_parent'` for
    anybody else (so the person assigned still gets the "you gained this"
    push); cancel at either question posts nothing;
  * no browser dialogs: promptChoice/promptConfirm/showGlobalAlert only.

Run from chauffeur/:  python tests/test_pwa_assign_other_driver.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_assign_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_assign_run_')
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'app.html')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _chunk():
    """renderAssignButtons and assignOtherDriver, which sit together right
    before the outside-hands section."""
    with open(APP, encoding='utf-8') as f:
        src = f.read()
    start = src.index('function renderAssignButtons(ev, wrap)')
    end = src.index('// --- Outside hands on a drive', start)
    return src[start:end]


HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const [,, chunkPath, casesPath] = process.argv;
const cases = JSON.parse(fs.readFileSync(casesPath, 'utf8'));
const dom = new JSDOM('<!doctype html><body><div id="em-claim-container"></div></body>');
global.window = dom.window; global.document = dom.window.document;
let role = 'parent', selectedDriverId = 'jeff', driversData = [], answers = [], posts = [], checks = [], alerts = [], closed = 0, offered = [];
const apiBase = '';
const CLAIM_ICON = '', CLAIM_SPINNER = '';
function currentMemberRole() { return role; }
function mfEscape(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
async function claimEvent() {}
async function promptChoice(title, body, options) { const vals = (options || []).map(o => o.value); offered.push(vals); const a = answers.shift(); if (a === undefined || a === '__cancel__' || !vals.includes(a)) return null; return a; }
async function promptConfirm() { return true; }
function showGlobalAlert(m) { alerts.push(m); }
function closeEventModal() { closed += 1; }
function fetchSchedule() {}
global.fetch = async (url, opts) => {
  if (/overrides\/check$/.test(url)) { checks.push(JSON.parse(opts.body)); return { ok: true, json: async () => ({ conflicts: [] }) }; }
  if (/api\/overrides$/.test(url)) { posts.push(JSON.parse(opts.body)); return { ok: true, json: async () => ({ status: 'created' }) }; }
  return { ok: false, json: async () => ({}) };
};
eval(fs.readFileSync(chunkPath, 'utf8'));
(async () => {
  const out = {};
  for (const [name, c] of Object.entries(cases)) {
    role = c.role || 'parent'; driversData = c.drivers || []; answers = (c.answers || []).slice(); posts = []; checks = []; alerts = []; closed = 0; offered = [];
    const wrap = document.getElementById('em-claim-container');
    wrap.innerHTML = '';
    try {
      renderAssignButtons(c.ev, wrap);
      const btn = wrap.querySelector('[data-assign-other]');
      const r = { button: btn ? btn.textContent.trim() : null, buttons: Array.from(wrap.querySelectorAll('button')).map(b => b.textContent.trim()) };
      if (c.tap && btn) { await assignDriver(c.ev); }
      r.posts = posts; r.checks = checks; r.alerts = alerts; r.closed = closed; r.offered = offered;
      out[name] = r;
    } catch (e) { out[name] = { error: String(e && e.stack || e) }; }
  }
  console.log(JSON.stringify(out));
})();
"""

DRIVERS = [{'id': 'jeff', 'name': 'Jeff'}, {'id': 'gran', 'name': 'Grandma'}, {'id': 'sarah', 'name': 'Sarah'}]
EV_OPEN = {'id': 'ev1', 'title': 'Team Pictures', 'timeStr': '8:30 AM', 'dateStr': '2026-10-17', 'isErrand': False,
           'suppressed': False, 'legs': [], 'driverIds': [], 'canClaim': True}
EV_LEGS = {**EV_OPEN, 'id': 'ev2', 'legs': [{'id': 'ev2_dropoff', 'type': 'dropoff', 'timeStr': '8:00 AM', 'mine': False},
                                            {'id': 'ev2_pickup', 'type': 'pickup', 'timeStr': '10:00 AM', 'mine': False}]}
EV_HELD = {**EV_OPEN, 'id': 'ev3', 'driverIds': ['sarah'], 'canClaim': True}
EV_ERRAND = {**EV_OPEN, 'id': 'ev4', 'isErrand': True, 'canClaim': False}

_RESULT = {}


def _run():
    if 'error' in _RESULT:
        raise _RESULT['error']          # every scenario fails, none passes by accident
    if _RESULT:
        return _RESULT.get('data')
    try:
        return _run_once()
    except Exception as e:
        _RESULT['error'] = e
        raise


def _run_once():
    _RESULT['data'] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — the sheet was not drawn')
        return None
    have = subprocess.run([node, '-e', "require.resolve('jsdom')"], capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom not resolvable')
        return None
    chunk = os.path.join(SCRATCH, 'chunk.js')
    with open(chunk, 'w', encoding='utf-8') as f:
        f.write(_chunk())
    harness = os.path.join(SCRATCH, 'harness.js')
    with open(harness, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    cases = os.path.join(SCRATCH, 'cases.json')
    with open(cases, 'w', encoding='utf-8') as f:
        json.dump({
            'parent_open': {'ev': EV_OPEN, 'drivers': DRIVERS},
            'assign_me': {'ev': EV_OPEN, 'drivers': DRIVERS, 'tap': True, 'answers': ['jeff']},
            'parent_held': {'ev': EV_HELD, 'drivers': DRIVERS},
            'child': {'ev': EV_OPEN, 'drivers': DRIVERS, 'role': 'child'},
            'adult': {'ev': EV_OPEN, 'drivers': DRIVERS, 'role': 'adult'},
            'errand': {'ev': EV_ERRAND, 'drivers': DRIVERS},
            'assign_gran': {'ev': EV_OPEN, 'drivers': DRIVERS, 'tap': True, 'answers': ['gran']},
            'assign_both_legs': {'ev': EV_LEGS, 'drivers': DRIVERS, 'tap': True, 'answers': ['gran', '__both__']},
            'assign_one_leg': {'ev': EV_LEGS, 'drivers': DRIVERS, 'tap': True, 'answers': ['gran', 'ev2_pickup']},
            'cancel_who': {'ev': EV_OPEN, 'drivers': DRIVERS, 'tap': True, 'answers': ['__cancel__']},
            'cancel_leg': {'ev': EV_LEGS, 'drivers': DRIVERS, 'tap': True, 'answers': ['gran', '__cancel__']},
            'held_excludes_holder': {'ev': EV_HELD, 'drivers': DRIVERS, 'tap': True, 'answers': ['sarah']},
        }, f)
    proc = subprocess.run([node, harness, chunk, cases], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0, f"the sheet threw:\n{proc.stderr[-2000:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def _case(name):
    got = _run()
    if got is None:
        return None
    r = got[name]
    check('error' not in r, f"{name} threw: {r.get('error')}")
    return r


def scenario_only_a_parent_gets_the_button():
    r = _case('parent_open')
    if r is None:
        return
    check(r['button'] == 'Assign driver', f"an open drive offers the picker: {r}")
    check(r['buttons'] == ['Assign driver'], f"one button, not a self-claim row beside it: {r['buttons']}")
    held = _case('parent_held')
    check(held['button'] == 'Change driver', f"a held drive reads Change driver: {held}")
    child = _case('child')
    check(child['button'] is None, f"a child never assigns the family's drives: {child}")
    check(child['buttons'] == ['Assign to Me'], f"a child driver keeps the self-claim: {child['buttons']}")
    adult = _case('adult')
    check(adult['button'] is None and adult['buttons'] == ['Assign to Me'],
          f"an adult assigns only themselves: {adult}")
    errand = _case('errand')
    check(errand['button'] is None, f"an errand is the household's own job: {errand}")


def scenario_picking_grandma_posts_one_override_with_the_parent_source():
    r = _case('assign_gran')
    if r is None:
        return
    check(len(r['posts']) == 1 and r['posts'][0]['event_id'] == 'ev1' and r['posts'][0]['driver_id'] == 'gran'
          and r['posts'][0]['source'] == 'pwa_parent' and r['posts'][0]['event_title'] == 'Team Pictures',
          f"one override for Grandma, tagged as a parent's assignment: {r['posts']}")
    check(r['checks'] and r['checks'][0] == {'event_id': 'ev1', 'driver_id': 'gran'}, f"the solver dry-run ran first: {r['checks']}")
    check(r['closed'] == 1 and any('Grandma' in a for a in r['alerts']), f"the sheet closes and the toast names her: {r}")


def scenario_me_leads_the_picker_and_stays_a_self_claim():
    r = _case('assign_me')
    if r is None:
        return
    check(r['offered'] and r['offered'][0][0] == 'jeff', f"Me is the first choice: {r['offered']}")
    check(len(r['posts']) == 1 and r['posts'][0]['driver_id'] == 'jeff' and r['posts'][0]['source'] == 'pwa',
          f"picking Me is the self-claim the push logic already knows: {r['posts']}")
    check(any('you' in a for a in r['alerts']), f"the toast says you: {r['alerts']}")


def scenario_two_legs_ask_which_and_both_posts_two():
    r = _case('assign_both_legs')
    if r is None:
        return
    check(sorted(p['event_id'] for p in r['posts']) == ['ev2_dropoff', 'ev2_pickup'] and all(p['driver_id'] == 'gran' for p in r['posts']),
          f"Both means one override per leg: {r['posts']}")
    one = _case('assign_one_leg')
    check([p['event_id'] for p in one['posts']] == ['ev2_pickup'], f"one leg means that leg only: {one['posts']}")


def scenario_cancel_at_either_question_posts_nothing():
    r = _case('cancel_who')
    if r is None:
        return
    check(not r['posts'] and not r['checks'] and r['closed'] == 0, f"cancel on who: {r}")
    leg = _case('cancel_leg')
    check(not leg['posts'] and not leg['checks'] and leg['closed'] == 0, f"cancel on which leg: {leg}")


def scenario_the_holder_is_not_offered_again():
    r = _case('held_excludes_holder')
    if r is None:
        return
    # Sarah holds it: the picker never lists her, so the scripted 'sarah'
    # answer is not among the offered values (the stub cancels) and nothing posts.
    check(r['offered'] and 'sarah' not in r['offered'][0] and 'gran' in r['offered'][0] and 'jeff' in r['offered'][0],
          f"the holder is not offered, the others are: {r['offered']}")
    check(not r['posts'], f"nothing posted: {r['posts']}")


SCENARIOS = [
    scenario_only_a_parent_gets_the_button,
    scenario_picking_grandma_posts_one_override_with_the_parent_source,
    scenario_me_leads_the_picker_and_stays_a_self_claim,
    scenario_two_legs_ask_which_and_both_posts_two,
    scenario_cancel_at_either_question_posts_nothing,
    scenario_the_holder_is_not_offered_again,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
