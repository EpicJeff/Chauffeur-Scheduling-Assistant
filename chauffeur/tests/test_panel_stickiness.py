"""Panel mode has to survive a child tapping on things.

Reported from the wall: the kids kept getting the panel onto the admin pages
just by tapping around. The cause was not one bad link, it was the mechanism.
`nav.html` propagated the query string onto `a[href]` ONCE, in a
DOMContentLoaded pass — and these pages build most of their links afterwards,
from API data: a renderer's template string, an Alpine `:href`, a modal built
on open. Every one of those was a door out of panel mode. So was every
`window.location.href = 'trips'`. And the pass skipped any link containing
`#`, which is every row on /settings.

Two mechanisms replace it, both in ha_theme.html:
  - a CLICK-time interceptor, so a card rendered five minutes later obeys the
    same rule as one rendered at load;
  - a sessionStorage LATCH, so a link that still slips through is recovered on
    arrival rather than being load-bearing.

The script is executed here rather than grepped, because "the handler runs and
rewrites the href" is the only claim worth making. A DOM stub thin enough to be
honest about what it fakes; skips when node is unavailable.

Run from chauffeur/:  python tests/test_panel_stickiness.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
THEME = open(os.path.join(TPL, 'ha_theme.html'), encoding='utf-8').read()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _panel_script():
    """ha_theme's first script block — the one that runs before the body."""
    m = re.search(r'<script>(.*?)</script>', THEME, re.S)
    check(m, "ha_theme.html no longer opens with a script block")
    src = m.group(1)
    check('{%' not in src and '{{' not in src,
          "the panel-mode block now contains Jinja, so it cannot be executed "
          "straight out of the template any more")
    return src


# A DOM thin enough to be honest. Anchors are modelled properly — attribute
# get/set and `closest` — because rewriting an anchor's href at click time IS
# the behaviour under test, and a stub that swallowed setAttribute would agree
# with anything.
HARNESS = r"""
let clickHandler = null;
function A(href, target) {
  const el = {
    tagName: 'A', target: target || '', style: {}, dataset: {},
    _attrs: { href: href },
    getAttribute: function (k) { return k in this._attrs ? this._attrs[k] : null; },
    setAttribute: function (k, v) { this._attrs[k] = v; },
    closest: function (sel) { return sel === 'a[href]' ? this : null; },
    // What the browser would resolve and then follow.
    get href() {
      try { return new URL(this._attrs.href, global.window.location.href).href; }
      catch (e) { return this._attrs.href; }
    },
  };
  return el;
}

const _store = {};
global.sessionStorage = {
  getItem: function (k) { return k in _store ? _store[k] : null; },
  setItem: function (k, v) { _store[k] = String(v); },
  removeItem: function (k) { delete _store[k]; },
};
global.localStorage = {
  _d: {},
  getItem: function (k) { return k in this._d ? this._d[k] : null; },
  setItem: function (k, v) { this._d[k] = String(v); },
  removeItem: function (k) { delete this._d[k]; },
};

function mk(tag) {
  return {
    tagName: tag, id: '', style: {}, textContent: '',
    _attrs: {},
    setAttribute: function (k, v) { this._attrs[k] = v; },
    getAttribute: function (k) { return k in this._attrs ? this._attrs[k] : null; },
    appendChild: function () { },
  };
}

const root = mk('html');
global.document = {
  documentElement: root,
  head: mk('head'),
  body: mk('body'),
  createElement: mk,
  querySelector: function () { return null; },
  querySelectorAll: function () { return []; },
  getElementById: function () { return null; },
  addEventListener: function (ev, fn, capture) {
    if (ev === 'click' && capture === true) clickHandler = fn;
  },
};

let replaced = null;
global.window = {
  location: {
    pathname: __PATH__, search: __SEARCH__, hash: '',
    origin: 'http://panel.local',
    get href() { return this.origin + this.pathname + this.search + this.hash; },
  },
  addEventListener: function () { },
  matchMedia: function () { return { matches: false }; },
  getComputedStyle: function () { return { getPropertyValue: function () { return ''; } }; },
};
global.history = {
  replaceState: function (a, b, url) {
    replaced = url;
    const q = url.indexOf('?');
    global.window.location.search = q === -1 ? '' : url.slice(q);
  },
};
global.URL = URL;
global.URLSearchParams = URLSearchParams;
global.setInterval = function () { };
global.getComputedStyle = global.window.getComputedStyle;

__SCRIPT__

// Click every case and report what the browser would have followed.
function clickResult(href, target) {
  if (!clickHandler) return null;
  const a = A(href, target);
  clickHandler({ target: a });
  return a.getAttribute('href');
}

console.log(JSON.stringify({
  url: replaced,
  search: global.window.location.search,
  latched: _store['chauffeurPanelSession'] || null,
  intercepted: clickHandler !== null,
  results: {
    plain: clickResult('shopping'),
    withQuery: clickResult('trip?event_id=abc'),
    fragment: clickResult('#top'),
    pageFragment: clickResult('config#car-alerts'),
    external: clickResult('https://example.com/x'),
    blank: clickResult('moments', '_blank'),
    tel: clickResult('tel:5551234'),
    js: clickResult('javascript:void(0)'),
    alreadyHas: clickResult('home?panel=true&kiosk=true'),
  },
}));
"""


def run(path='/home', search='?panel=true'):
    node = shutil.which('node')
    if not node:
        print('  SKIP  node not installed')
        return None
    src = (HARNESS
           .replace('__SCRIPT__', _panel_script())
           .replace('__PATH__', json.dumps(path))
           .replace('__SEARCH__', json.dumps(search)))
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'run.mjs')
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(src)
        proc = subprocess.run([node, f], capture_output=True, text=True)
    check(proc.returncode == 0,
          f"the panel-mode script threw:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_a_link_built_after_load_still_carries_the_panel():
    """The whole bug. A card rendered from an API response is invisible to
    nav.html's one-shot pass, so it used to be a plain `shopping` href and
    tapping it dropped the panel onto the admin site."""
    r = run()
    if r is None:
        return
    check(r['intercepted'], "nothing is listening for clicks in capture phase, "
                            "so a link rendered after load carries nothing")
    for key, href in (('plain', r['results']['plain']),
                      ('withQuery', r['results']['withQuery'])):
        check('panel=true' in href and 'kiosk=true' in href,
              f"a {key} link still leaves panel mode: {href}")
    check('event_id=abc' in r['results']['withQuery'],
          "the link's own query was destroyed on the way past")


def scenario_a_fragment_link_is_not_a_page_but_a_page_anchor_is():
    """nav.html skipped every href containing '#', which quietly exempted
    /settings — its rows are `page#anchor` and navigate to another page. A bare
    `#top` really does stay put and must be left alone."""
    r = run()
    if r is None:
        return
    check(r['results']['fragment'] == '#top',
          "a same-page anchor was rewritten into a navigation")
    frag = r['results']['pageFragment']
    check('panel=true' in frag and frag.endswith('#car-alerts'),
          f"a page#anchor link lost the panel flag or its anchor: {frag}")


def scenario_links_that_do_not_leave_the_panel_are_left_alone():
    """Rewriting these would be its own bug — a tel: with a query string, an
    external site handed our internal flags, a _blank that is not this tab."""
    r = run()
    if r is None:
        return
    for key, expect in (('external', 'https://example.com/x'),
                        ('blank', 'moments'),
                        ('tel', 'tel:5551234'),
                        ('js', 'javascript:void(0)')):
        check(r['results'][key] == expect,
              f"{key} link was rewritten to {r['results'][key]!r}")


def scenario_an_ordinary_browser_session_is_untouched():
    """The interceptor sits above the panel-only return so kiosk and readonly
    surfaces get it too — which means it also runs for somebody at a laptop,
    where it must do precisely nothing."""
    r = run(path='/shopping', search='?list=3')
    if r is None:
        return
    check(r['results']['plain'] == 'shopping',
          f"an admin browser had its links rewritten: {r['results']['plain']}")
    check('list=3' not in (r['results']['withQuery'] or ''),
          "page params are being dragged onto every link")


def scenario_the_latch_recovers_a_link_that_still_slipped_through():
    """Belt and braces. A JS navigation cannot be intercepted at all, so the
    session remembers what kind of surface this is and puts the flag back."""
    first = run()
    if first is None:
        return
    check(first['latched'] == '1',
          "arriving with ?panel=true does not latch the session, so any missed "
          "link is a one-way trip to the admin pages")

    # Same tab, now arriving somewhere with no flags at all — the leaked link
    # that started all this. Each node run is its own process with an empty
    # store, so the already-latched session is set up explicitly.
    r = run_with_latch(path='/config', search='')
    check('panel=true' in (r['search'] or ''),
          f"a bare /config in a latched session stays bare: {r['search']!r}")
    check('kiosk=true' in (r['search'] or ''),
          "panel mode was restored without the kiosk flag it implies")


def scenario_panel_false_is_the_way_out():
    """A parent has to be able to reach the admin pages ON the panel. Without
    an escape hatch the latch would be a trap."""
    r = run_with_latch(path='/config', search='?panel=false')
    check('panel=true' not in (r['search'] or ''),
          "?panel=false did not drop panel mode")
    check(r['latched'] is None,
          "?panel=false left the session latched, so the next page snaps back")


def run_with_latch(path, search):
    """Same as run(), but the session is already latched before the script runs."""
    node = shutil.which('node')
    if not node:
        print('  SKIP  node not installed')
        return {'search': search, 'latched': None}
    src = (HARNESS
           .replace('__SCRIPT__', _panel_script())
           .replace('__PATH__', json.dumps(path))
           .replace('__SEARCH__', json.dumps(search))
           .replace("const _store = {};",
                    "const _store = {chauffeurPanelSession: '1'};"))
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'run.mjs')
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(src)
        proc = subprocess.run([node, f], capture_output=True, text=True)
    check(proc.returncode == 0, f"script threw:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_no_js_navigation_walks_off_the_panel_by_itself():
    """`window.location.href = 'trips'` cannot be intercepted by anything —
    not nav.html's pass, not the click handler. Every internal one has to carry
    the flags by hand, so this is the guard that a new one does too."""
    pages = ('app', 'home', 'config', 'dashboard', 'calendar', 'chores',
             'routines', 'shopping', 'errands', 'intake', 'moments',
             'occasions', 'settings', 'trips', 'trip', 'map')
    pattern = re.compile(
        r'location\.href\s*=\s*[`\'"]([^`\'"]+)[`\'"]')
    offenders = []
    for base, _, files in os.walk(TPL):
        for name in sorted(files):
            if not name.endswith('.html'):
                continue
            path = os.path.join(base, name)
            for i, line in enumerate(open(path, encoding='utf-8'), 1):
                # Prose, not code — this rule is discussed in comments as often
                # as it is applied, including in ha_theme's own explanation.
                if line.lstrip().startswith(('//', '*', '/*', '{#', '#')):
                    continue
                for dest in pattern.findall(line):
                    if dest.startswith(('http', '/', '#', '${')):
                        continue
                    page = dest.split('?')[0].split('#')[0].strip('/')
                    if page not in pages:
                        continue
                    if ('location.search' in line or 'chfDisplayUrl' in line
                            or 'carryParams' in line or 'CarryParams' in line):
                        continue
                    offenders.append(f'{name}:{i} -> {dest}')
    check(not offenders,
          "these JS navigations drop the display flags, so a tap on one takes "
          "the wall panel to the admin site:\n    " + "\n    ".join(offenders)
          + "\n  Wrap the destination in window.chfDisplayUrl(...).")


def scenario_no_internal_link_is_an_absolute_path():
    """An absolute `/config` is worse than a lost flag under Home Assistant
    ingress: the app is served from `/api/hassio_ingress/<token>/`, so `/config`
    leaves Chauffeur entirely and lands on HOME ASSISTANT's settings — which is
    quite a lot of admin for one tap."""
    offenders = []
    pattern = re.compile(r'href="(/(?!/|api/|static/)[a-z_]+)"')
    for base, _, files in os.walk(TPL):
        for name in sorted(files):
            if not name.endswith('.html'):
                continue
            for i, line in enumerate(open(os.path.join(base, name), encoding='utf-8'), 1):
                for dest in pattern.findall(line):
                    offenders.append(f'{name}:{i} -> {dest}')
    check(not offenders,
          "absolute internal links escape the ingress prefix:\n    "
          + "\n    ".join(offenders))


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} panel-stickiness scenarios passed")
