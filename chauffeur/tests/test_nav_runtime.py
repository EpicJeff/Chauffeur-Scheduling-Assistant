"""nav.html's script actually RUNS, against a stub DOM.

Written after a one-line ordering mistake took the entire wall panel down and
survived every check we had. `panelProfile()` was called near the top of the
DOMContentLoaded handler while `let _profile = null;` sat two hundred lines
below it. Function declarations hoist; `let` does not — it stays in the
temporal dead zone until its own line executes. So the call threw
ReferenceError and aborted the rest of the handler: no shelf, no tab
filtering, no background, no idle return, and the desktop nav bar left sitting
on a wall panel.

Nothing caught it. It is valid syntax, so `node --check` passes. Every
template rendered fine, because the failure is in the browser. The only thing
that finds this class of bug is executing the script, so that is what this
does: a DOM stub thin enough to be honest about what it fakes, and one
assertion that matters — the handler runs to completion in panel mode.

Skips (rather than fails) when node is unavailable, so a machine without it
does not report a false problem.

Run from chauffeur/:  python tests/test_nav_runtime.py
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

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _nav_script(path='/home'):
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(TPL))
    req = types.SimpleNamespace(url=types.SimpleNamespace(path=path))
    html = env.get_template('nav.html').render(request=req)
    blocks = re.findall(r'<script>(.*?)</script>', html, re.S)
    check(blocks, "nav.html no longer has a script block")
    return blocks[-1]


# A DOM thin enough to be honest: elements remember their id, class list and
# style, listeners are recorded, and fetch resolves a realistic panel profile.
HARNESS = r"""
const listeners = {};
function El(tag) {
  return {
    tagName: tag, id: '', dataset: {}, style: {}, children: [],
    _classes: new Set(['hidden']),
    classList: {
      add: function (c) { this._o._classes.add(c); },
      remove: function (c) { this._o._classes.delete(c); },
      contains: function (c) { return this._o._classes.has(c); },
    },
    clientWidth: 1280,
    appendChild: function (c) { this.children.push(c); return c; },
    insertBefore: function (c) { this.children.push(c); return c; },
    prepend: function (c) { this.children.unshift(c); return c; },
    querySelectorAll: function () { return []; },
    querySelector: function () { return null; },
    addEventListener: function () { },
    removeEventListener: function () { },
    remove: function () { },
    contains: function () { return false; },
    getAttribute: function () { return null; },
    setAttribute: function () { },
  };
}
function mk(tag, id) { const e = El(tag); e.id = id || ''; e.classList._o = e; return e; }

const els = {};
for (const id of ['top-nav-bar', 'panel-shelf', 'panel-fade', 'panel-shelf-items',
                  'panel-shelf-more', 'panel-shelf-flyout', 'panel-shelf-flyout-items',
                  'mobile-menu', 'settings-nav-item', 'control-center-nav-item',
                  'panel-early-tabs', 'panel-bg-image', 'panel-bg-scrim']) {
  els[id] = mk('div', id);
}

global.document = {
  documentElement: mk('html'),
  body: mk('body'),
  getElementById: function (id) { return els[id] || null; },
  querySelectorAll: function () { return []; },
  querySelector: function (s) { return s === 'nav' ? mk('nav') : null; },
  createElement: function (t) { return mk(t); },
  addEventListener: function (ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
};
global.window = {
  location: { pathname: '/home', search: '?panel=true', hash: '', origin: 'http://x' },
  addEventListener: function () { },
  matchMedia: function () { return { matches: false }; },
};
global.localStorage = {
  _d: {},
  getItem: function (k) { return k in this._d ? this._d[k] : null; },
  setItem: function (k, v) { this._d[k] = String(v); },
  removeItem: function (k) { delete this._d[k]; },
};
global.URL = URL;
global.URLSearchParams = URLSearchParams;
global.setTimeout = setTimeout;
global.clearTimeout = clearTimeout;
global.fetch = function () {
  return Promise.resolve({
    ok: true,
    json: function () {
      return Promise.resolve(__PROFILE__);
    },
  });
};

__SCRIPT__

// Fire the handler the script registered, and surface anything it throws.
const handlers = listeners['DOMContentLoaded'] || [];
if (!handlers.length) { console.log('NOHANDLER'); process.exit(3); }
try {
  handlers.forEach(function (fn) { fn(); });
} catch (e) {
  console.log('THREW:' + (e && e.message ? e.message : String(e)));
  process.exit(4);
}
// Let the profile promise settle so the background/theme work runs too.
setTimeout(function () {
  console.log(JSON.stringify({
    topNavHidden: els['top-nav-bar'].style.display === 'none',
    bgImage: els['panel-bg-image'].style.backgroundImage || '',
    theme: document.documentElement._theme || null,
    cachedBg: Object.keys(localStorage._d).filter(k => k.indexOf('chauffeurPanelBg:') === 0),
  }));
}, 20);
"""

PROFILE = {
    "tabs": ["home", "schedule", "chores"],
    "widgets": ["drives"],
    "spans": {},
    "theme": "dark",
    "backgrounds": {"default": "api/unsplash/background?query=mountains"},
    "idle_seconds": 180,
}


def _run():
    node = shutil.which('node')
    if not node:
        return None
    js = (HARNESS
          .replace('__SCRIPT__', _nav_script())
          .replace('__PROFILE__', json.dumps(PROFILE)))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'nav_runtime.js')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(js)
        return subprocess.run([node, path], capture_output=True, text=True, timeout=60)


def scenario_the_nav_script_runs_to_completion_in_panel_mode():
    """The whole point. A ReferenceError anywhere in the handler leaves the
    panel looking like an ordinary web page, and every static check passes."""
    res = _run()
    if res is None:
        print('  ..  skipped (node not available)')
        return
    check('THREW:' not in res.stdout,
          f"the nav script threw in panel mode: {res.stdout.strip()}")
    check('NOHANDLER' not in res.stdout,
          "the script no longer registers a DOMContentLoaded handler")
    check(res.returncode == 0,
          f"node exited {res.returncode}: {(res.stderr or res.stdout).strip()[:400]}")


def scenario_the_panel_gets_its_background():
    """The symptom that exposed the crash: the picture showed in a browser (the
    board sets its own) but never in panel mode, because nav.html — which owns
    it there — had already died."""
    res = _run()
    if res is None:
        print('  ..  skipped (node not available)')
        return
    out = [l for l in res.stdout.strip().splitlines() if l.startswith('{')]
    check(out, f"no result from the run: {res.stdout.strip()[:300]}")
    data = json.loads(out[-1])
    check('unsplash' in data['bgImage'],
          f"the panel never applied its background: {data['bgImage']!r}")
    check(data['cachedBg'],
          "the resolved picture is not cached, so the next load will flash")


def scenario_a_let_is_never_used_before_it_is_declared():
    """The specific ordering that caused it, guarded cheaply and readably so a
    future edit that moves the declaration back down fails immediately rather
    than at the next photograph of the wall."""
    body = open(os.path.join(TPL, 'nav.html'), encoding='utf-8').read()
    decl = body.find('let _profile = null;')
    # The real call site, not the prose about it — the comment beside the
    # declaration mentions `panelProfile()` and would otherwise match first.
    call = body.find('if (isPanel) panelProfile();')
    check(decl != -1 and call != -1, "panelProfile/_profile have been renamed")
    check(decl < call,
          "`let _profile` is declared after the first panelProfile() call — "
          "that is a temporal-dead-zone ReferenceError at runtime, and it kills "
          "the whole handler")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} nav-runtime scenarios passed")
