"""Pushed screens on the History API (PWA reimagined slice 0, task 4), run in
a real DOM.

Pinned shapes (static/pwa_nav.js sets window.PwaNav):
  * `PwaNav.push({ id, title, render, onPop })` appends
    `<section class="pwa-screen" data-screen=id>` to `#pwa-stack` with a
    `.pwa-back` button reading '‹ {parent title}' (the first screen's parent
    is the current tab's label, a later screen's parent is the screen under
    it), an `h1` with the title and a `.pwa-screen-body` that `render(body)`
    fills; shows `#pwa-stack`, sets `html[data-pwa-stack]` to the depth and
    calls `history.pushState({ pwaScreen: id, pwaDepth: <depth after push> }, '')`;
  * `pop()` removes the top screen, calls its onPop, hides the stack when it
    empties; `depth()` and `current()` (null when empty) report the stack;
  * popstate (controller ruling 2026-11-03): an empty stack does nothing; a
    null state or a numeric `pwaDepth` pops while depth() > (pwaDepth || 0);
    a non-null state without `pwaDepth` (the moments gallery's
    `{ momentsEvent }`) is foreign and ignored;
  * `clear()` pops every screen (each onPop once) and, when depth was > 0,
    undoes the pushes with ONE `history.go(-depth)`.

jsdom 30 dispatches popstate asynchronously on history.back()/go() (checked
empirically), so the harness waits for the next popstate or 200 ms.

Run from chauffeur/:  python tests/test_pwa_nav.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_pwa_nav_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_pwa_nav_run_')
NAV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'pwa_nav.js')

BACK = '‹'  # the single left-pointing angle quote on the Back button


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


HARNESS = r"""
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');
const [,, navPath, casesPath] = process.argv;
const cases = JSON.parse(fs.readFileSync(casesPath, 'utf8'));
const src = fs.existsSync(navPath) ? fs.readFileSync(navPath, 'utf8') : null;
const HTML = '<!doctype html><html><body>'
  + '<div id="pwa-stack" hidden></div>'
  + '<div id="pwa-more-container"></div>'
  + '<nav id="pwa-tab-bar"><button aria-current="page"><span>Household</span></button><button><span>More</span></button></nav>'
  + '</body></html>';

function fresh() {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(String(e && e.message || e)));
  const dom = new JSDOM(HTML, { url: 'http://localhost/app', runScripts: 'outside-only', virtualConsole: vc });
  const w = dom.window;
  if (src === null) throw new Error('static/pwa_nav.js is missing, PwaNav undefined');
  w.eval(src);
  if (!w.PwaNav) throw new Error('static/pwa_nav.js loaded but window.PwaNav is undefined');
  return { w, errors };
}

// Resolves on the next popstate or after 200 ms, whichever first.
function nextPop(w) {
  return new Promise(resolve => {
    let done = false;
    const finish = how => { if (!done) { done = true; resolve(how); } };
    w.addEventListener('popstate', () => setTimeout(() => finish('popstate'), 0), { once: true });
    setTimeout(() => finish('timeout'), 200);
  });
}

function snap(w) {
  const d = w.document;
  const stack = d.getElementById('pwa-stack');
  const screens = Array.from(d.querySelectorAll('#pwa-stack .pwa-screen'));
  const cur = w.PwaNav.current();
  return {
    stackHidden: stack ? !!stack.hidden : null,
    screens: screens.map(s => ({
      screen: s.getAttribute('data-screen'),
      back: (s.querySelector('.pwa-back') || {}).textContent || null,
      h1: (s.querySelector('h1') || {}).textContent || null,
      body: (s.querySelector('.pwa-screen-body') || {}).textContent || null,
    })),
    dataPwaStack: d.documentElement.hasAttribute('data-pwa-stack') ? d.documentElement.getAttribute('data-pwa-stack') : '__absent__',
    historyState: w.history.state === undefined ? '__undefined__' : w.history.state,
    historyLength: w.history.length,
    depth: w.PwaNav.depth(),
    current: cur === null ? null : (cur === undefined ? '__undefined__' : { id: cur.id }),
  };
}

function screen(id, title, counts) {
  counts[id] = 0;
  return { id, title, render(body) { body.textContent = 'body-' + id; }, onPop() { counts[id] += 1; } };
}

const RUN = {
  async push_draws_chrome() {
    const { w, errors } = fresh();
    const lenBefore = w.history.length;
    w.PwaNav.push({ id: 'chores', title: 'Chores', render(body) { body.textContent = 'hi'; } });
    return { ...snap(w), lenBefore, errors };
  },
  async second_screen_backs_to_the_first() {
    const { w, errors } = fresh();
    const counts = {};
    w.PwaNav.push(screen('a', 'Chores', counts));
    w.PwaNav.push(screen('b', 'Detail', counts));
    return { ...snap(w), counts, errors };
  },
  async pop_calls_onpop() {
    const { w, errors } = fresh();
    const counts = {};
    w.PwaNav.push(screen('a', 'Chores', counts));
    const p = nextPop(w);
    w.PwaNav.pop();
    const after = await p;   // pop may or may not walk history back; either way let it land
    return { ...snap(w), counts, after, errors };
  },
  async back_pops_one() {
    const { w, errors } = fresh();
    const counts = {};
    w.PwaNav.push(screen('a', 'Chores', counts));
    w.PwaNav.push(screen('b', 'Detail', counts));
    const p = nextPop(w);
    w.history.back();
    const after = await p;
    return { ...snap(w), counts, after, errors };
  },
  async back_with_empty_stack_is_inert() {
    const { w, errors } = fresh();
    let thrown = null, after = null;
    try {
      w.history.pushState({ other: true }, '');
      const p = nextPop(w);
      w.history.back();
      after = await p;
    } catch (e) { thrown = String(e && e.stack || e); }
    return { ...snap(w), thrown, after, errors };
  },
  async foreign_state_is_ignored() {
    const { w, errors } = fresh();
    const counts = {};
    w.PwaNav.push(screen('a', 'Chores', counts));
    w.history.pushState({ momentsEvent: 'x' }, '');
    w.dispatchEvent(new w.PopStateEvent('popstate', { state: { momentsEvent: 'x' } }));
    await new Promise(r => setTimeout(r, 20));
    return { ...snap(w), counts, errors };
  },
  async clear_empties() {
    const { w, errors } = fresh();
    const counts = {};
    w.PwaNav.push(screen('a', 'Chores', counts));
    w.PwaNav.push(screen('b', 'Detail', counts));
    const p = nextPop(w);
    w.PwaNav.clear();
    const sync = snap(w);
    const countsSync = { ...counts };
    const after = await p;
    return { sync, countsSync, ...snap(w), counts, after, errors };
  },
  async clear_then_push_keeps_the_new_screen() {
    // setView(x) then PwaNav.push(...) inside the traversal delay: clear()'s own
    // history walk must not pop the screen pushed after it.
    const { w, errors } = fresh();
    const counts = {};
    w.PwaNav.push(screen('a', 'Chores', counts));
    w.PwaNav.push(screen('b', 'Detail', counts));
    w.PwaNav.clear();
    w.PwaNav.push(screen('c', 'Lists', counts));
    await new Promise(r => setTimeout(r, 250));   // let the go(-2) land
    const settled = snap(w);
    const p = nextPop(w);
    w.history.back();                               // Back now closes c, nothing else
    const after = await p;
    return { settled, ...snap(w), counts, after, errors };
  },
  async pop_walks_history_back() {
    // A programmatic pop() must leave history in step: the next Back press
    // closes the next screen instead of landing on a stale entry.
    const { w, errors } = fresh();
    const counts = {};
    w.PwaNav.push(screen('a', 'Chores', counts));
    const p1 = nextPop(w);
    w.PwaNav.pop();
    await p1;
    w.PwaNav.push(screen('b', 'Detail', counts));
    const p2 = nextPop(w);
    w.history.back();
    const after = await p2;
    return { ...snap(w), counts, after, errors };
  },
  async push_over_a_bare_root_state() {
    // app.html writes history.replaceState({}, ...) on deep links; a {} root
    // must not read as a foreign state when Back lands on it.
    const { w, errors } = fresh();
    const counts = {};
    w.history.replaceState({}, '');
    w.PwaNav.push(screen('a', 'Chores', counts));
    const p = nextPop(w);
    w.history.back();
    const after = await p;
    return { ...snap(w), counts, after, errors };
  },
  async back_button_pops_through_pwanav() {
    // The on-screen Back must be the same path as pop(): a screen pushed
    // during a pending walk has no history entry yet, and a raw history.back()
    // would walk below the app's root.
    const { w, errors } = fresh();
    const counts = {};
    w.PwaNav.push(screen('a', 'Chores', counts));
    w.PwaNav.push(screen('b', 'Detail', counts));
    const btn = w.document.querySelector('#pwa-stack .pwa-screen[data-screen="b"] .pwa-back');
    const label = btn.getAttribute('aria-label');
    const p = nextPop(w);
    btn.click();
    const after = await p;
    return { ...snap(w), counts, after, label, errors };
  },
};

(async () => {
  const out = {};
  for (const name of cases) {
    try { out[name] = await RUN[name](); }
    catch (e) { out[name] = { error: String(e && e.message || e) }; }
  }
  console.log(JSON.stringify(out));
})();
"""

CASES = ['push_draws_chrome', 'second_screen_backs_to_the_first', 'pop_calls_onpop', 'back_pops_one',
         'back_with_empty_stack_is_inert', 'foreign_state_is_ignored', 'clear_empties',
         'clear_then_push_keeps_the_new_screen', 'pop_walks_history_back',
         'push_over_a_bare_root_state', 'back_button_pops_through_pwanav']

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
        print('  skip  node is not installed — the stack was not run')
        return None
    have = subprocess.run([node, '-e', "require.resolve('jsdom')"], capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom not resolvable')
        return None
    harness = os.path.join(SCRATCH, 'harness.js')
    with open(harness, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    cases = os.path.join(SCRATCH, 'cases.json')
    with open(cases, 'w', encoding='utf-8') as f:
        json.dump(CASES, f)
    proc = subprocess.run([node, harness, NAV, cases], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0, f"the harness threw:\n{proc.stderr[-2000:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def _case(name):
    got = _run()
    if got is None:
        return None
    r = got[name]
    check('error' not in r, f"{name}: {r.get('error')}")
    check(not r.get('errors'), f"{name}: the page logged errors: {r.get('errors')}")
    return r


def scenario_push_draws_the_chrome():
    r = _case('push_draws_chrome')
    if r is None:
        return
    check(r['stackHidden'] is False, f"#pwa-stack shows once a screen is pushed: {r}")
    check(len(r['screens']) == 1 and r['screens'][0]['screen'] == 'chores', f"one .pwa-screen data-screen=chores: {r['screens']}")
    s = r['screens'][0]
    check((s['back'] or '').strip() == f'{BACK} Household', f"the first screen backs to the current tab's label: {s['back']!r}")
    check(s['h1'] == 'Chores', f"h1 carries the title: {s['h1']!r}")
    check(s['body'] == 'hi', f"render(body) filled .pwa-screen-body: {s['body']!r}")
    check(r['dataPwaStack'] == '1', f"html[data-pwa-stack] is the depth: {r['dataPwaStack']!r}")
    check(r['historyState'] == {'pwaScreen': 'chores', 'pwaDepth': 1}, f"pushState carries id and depth: {r['historyState']}")
    check(r['historyLength'] == r['lenBefore'] + 1, f"one history entry per push: {r['lenBefore']} -> {r['historyLength']}")
    check(r['depth'] == 1, f"depth() is 1: {r['depth']}")
    check(r['current'] == {'id': 'chores'}, f"current() is the pushed screen: {r['current']}")


def scenario_a_second_screen_backs_to_the_first():
    r = _case('second_screen_backs_to_the_first')
    if r is None:
        return
    check([s['screen'] for s in r['screens']] == ['a', 'b'], f"both screens stacked in order: {r['screens']}")
    check((r['screens'][1]['back'] or '').strip() == f'{BACK} Chores', f"b backs to a's title: {r['screens'][1]['back']!r}")
    check(r['depth'] == 2, f"depth() is 2: {r['depth']}")
    check(r['dataPwaStack'] == '2', f"html[data-pwa-stack] is 2: {r['dataPwaStack']!r}")
    check(r['historyState'] == {'pwaScreen': 'b', 'pwaDepth': 2}, f"the second push records depth 2: {r['historyState']}")


def scenario_pop_calls_onpop():
    r = _case('pop_calls_onpop')
    if r is None:
        return
    check(r['screens'] == [], f"no screens left: {r['screens']}")
    check(r['stackHidden'] is True, f"the empty stack hides: {r}")
    check(r['counts'] == {'a': 1}, f"onPop ran exactly once: {r['counts']}")
    check(r['dataPwaStack'] in ('__absent__', '0'), f"html[data-pwa-stack] removed or 0: {r['dataPwaStack']!r}")
    check(r['depth'] == 0, f"depth() is 0: {r['depth']}")
    check(r['current'] is None, f"current() is null on an empty stack: {r['current']}")


def scenario_hardware_back_pops_one_screen():
    r = _case('back_pops_one')
    if r is None:
        return
    check(r['after'] == 'popstate', f"jsdom delivered the popstate: {r['after']}")
    check(r['depth'] == 1, f"Back pops exactly one screen: depth {r['depth']}")
    check(r['current'] == {'id': 'a'}, f"a is on top again: {r['current']}")
    check([s['screen'] for s in r['screens']] == ['a'], f"one .pwa-screen left: {r['screens']}")
    check(r['counts'] == {'a': 0, 'b': 1}, f"b's onPop once, a's never: {r['counts']}")
    check(r['historyState'] == {'pwaScreen': 'a', 'pwaDepth': 1}, f"history sits on a's entry: {r['historyState']}")


def scenario_back_with_an_empty_stack_is_inert():
    r = _case('back_with_empty_stack_is_inert')
    if r is None:
        return
    check(r['thrown'] is None, f"nothing threw: {r['thrown']}")
    check(r['after'] == 'popstate', f"jsdom delivered the popstate: {r['after']}")
    check(r['depth'] == 0, f"depth stays 0: {r['depth']}")
    check(r['stackHidden'] is True, f"the stack stays hidden: {r}")
    check(r['screens'] == [], f"no screen drawn: {r['screens']}")


def scenario_a_foreign_popstate_is_ignored():
    r = _case('foreign_state_is_ignored')
    if r is None:
        return
    check(r['depth'] == 1, f"a {{momentsEvent}} popstate leaves the stack alone: depth {r['depth']}")
    check([s['screen'] for s in r['screens']] == ['a'], f"a stays drawn: {r['screens']}")
    check(r['counts'] == {'a': 0}, f"no onPop for a foreign state: {r['counts']}")


def scenario_clear_empties_with_one_history_walk():
    r = _case('clear_empties')
    if r is None:
        return
    check(r['sync']['depth'] == 0 and r['sync']['screens'] == [], f"clear() empties at once: {r['sync']}")
    check(r['sync']['stackHidden'] is True, f"the stack hides at once: {r['sync']}")
    check(r['countsSync'] == {'a': 1, 'b': 1}, f"each onPop once: {r['countsSync']}")
    check(r['after'] == 'popstate', f"clear() walked history back: {r['after']}")
    check(r['historyState'] is None, f"both pushes undone with one go(-2): {r['historyState']}")
    check(r['depth'] == 0 and r['stackHidden'] is True, f"still empty after the walk: {r}")
    check(r['counts'] == {'a': 1, 'b': 1}, f"the walk's popstate pops nothing more: {r['counts']}")


def scenario_a_push_right_after_clear_survives_the_walk():
    r = _case('clear_then_push_keeps_the_new_screen')
    if r is None:
        return
    check(r['settled']['depth'] == 1 and [x['screen'] for x in r['settled']['screens']] == ['c'],
          f"the screen pushed after clear() is still there once the walk lands: {r['settled']}")
    check(r['settled']['stackHidden'] is False, f"the stack stays visible: {r['settled']}")
    check(r['counts'].get('c', 0) == 0 or r['after'] == 'popstate',
          f"c was popped by clear()'s own walk: {r['counts']}")
    check(r['after'] == 'popstate' and r['depth'] == 0 and r['counts'] == {'a': 1, 'b': 1, 'c': 1},
          f"one Back closes c and only c: after={r['after']} depth={r['depth']} counts={r['counts']}")
    check(r['historyState'] is None, f"history is back at the root: {r['historyState']}")
    check(r['errors'] == [], f"no listener errors: {r['errors']}")


def scenario_pop_keeps_history_in_step():
    r = _case('pop_walks_history_back')
    if r is None:
        return
    check(r['after'] == 'popstate', f"Back after pop() reached the listener: {r['after']}")
    check(r['depth'] == 0 and r['screens'] == [], f"one Back closes the screen pushed after pop(): {r}")
    check(r['counts'] == {'a': 1, 'b': 1}, f"each onPop once: {r['counts']}")
    check(r['historyState'] is None, f"no stale entry left behind: {r['historyState']}")
    check(r['errors'] == [], f"no listener errors: {r['errors']}")


def scenario_a_bare_root_state_still_takes_back():
    r = _case('push_over_a_bare_root_state')
    if r is None:
        return
    check(r['after'] == 'popstate', f"Back reached the listener: {r['after']}")
    check(r['depth'] == 0 and r['screens'] == [], f"Back over a {{}} root closes the screen: {r}")
    check(r['counts'] == {'a': 1}, f"onPop once: {r['counts']}")
    check(r['stackHidden'] is True, f"the stack hides: {r}")
    check(r['errors'] == [], f"no listener errors: {r['errors']}")


def scenario_the_back_button_is_pop():
    r = _case('back_button_pops_through_pwanav')
    if r is None:
        return
    check(r['after'] == 'popstate', f"the button walked history: {r['after']}")
    check(r['depth'] == 1 and [x['screen'] for x in r['screens']] == ['a'], f"one tap closes b only: {r}")
    check(r['counts'] == {'a': 0, 'b': 1}, f"b's onPop once, a's never: {r['counts']}")
    check(r['historyState'] == {'pwaScreen': 'a', 'pwaDepth': 1}, f"history sits on a: {r['historyState']}")
    check(r['label'] in (None, 'Back to Chores'), f"the label names the parent or is absent: {r['label']!r}")
    check(r['errors'] == [], f"no listener errors: {r['errors']}")


SCENARIOS = [
    scenario_push_draws_the_chrome,
    scenario_a_second_screen_backs_to_the_first,
    scenario_pop_calls_onpop,
    scenario_hardware_back_pops_one_screen,
    scenario_back_with_an_empty_stack_is_inert,
    scenario_a_foreign_popstate_is_ignored,
    scenario_clear_empties_with_one_history_walk,
    scenario_a_push_right_after_clear_survives_the_walk,
    scenario_pop_keeps_history_in_step,
    scenario_a_bare_root_state_still_takes_back,
    scenario_the_back_button_is_pop,
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
