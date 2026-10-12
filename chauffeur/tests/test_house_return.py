"""static/house_return.js, actually run: when the "Back to house" button appears.

User report 2026-10-12, with screenshots: the House switched off, the regular
Home board on the wall — and every page, the Routines board included, wore
a "← Back to house" button. The button mounted on one condition: a return
address in sessionStorage. That address was written the first time a parent
visit started on the House (or a room linked out) and NEVER cleared, and a
wall panel's tab lives for weeks. Three rules, pinned here:

  1. Arriving at the House consumes the return address. The button is a way
     back from a page the House opened, not a permanent fixture of the tab.
  2. A panel page (?panel=true) never wears it. The House only ever links
     out with panel=false; a panel page has the shelf, which has the House.
  3. A household with the House switched off never wears it. nav.html hands
     the script the setting as data-house-home.

Run from chauffeur/:  python tests/test_house_return.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'static')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


SCRIPT = r'''
const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
function run({ path = '/routines', query = '', stored = {}, houseHome = 'true' } = {}) {
  const appended = [];
  const storage = {
    getItem: k => (k in stored ? stored[k] : null),
    setItem: (k, v) => { stored[k] = v; },
    removeItem: k => { delete stored[k]; },
  };
  const dataset = houseHome === null ? {} : { houseHome };
  const ctx = {
    URL, URLSearchParams, JSON, Date, Object,
    sessionStorage: storage,
    location: { href: 'https://example.test' + path + query, pathname: path,
                search: query, replace() {} },
    history: { state: null, replaceState() {} },
    fetch: () => Promise.resolve(),
    setInterval: () => 0, clearInterval() {},
    document: {
      readyState: 'complete', documentElement: { style: {} },
      currentScript: { dataset },
      addEventListener() {},
      createElement: () => ({ style: {}, addEventListener() {} }),
      body: { appendChild: e => appended.push(e) },
    },
  };
  ctx.window = ctx;
  vm.runInNewContext(source, ctx);
  return { appended, stored };
}
const RETURN = { chauffeur_house_return: JSON.stringify('https://example.test/house?panel=true') };

// A page the House opened: the button, as before.
let r = run({ path: '/trip', query: '?event_id=1&panel=false', stored: { ...RETURN } });
assert.equal(r.appended.length, 1, 'a page the House opened lost its way back');
assert.equal(r.appended[0].textContent, '← Back to house');
// An admin page with no panel flag at all (the next nav click): still a way back.
assert.equal(run({ path: '/mind', stored: { ...RETURN } }).appended.length, 1);
// The script included without the attribute reads as enabled.
assert.equal(run({ path: '/mind', stored: { ...RETURN }, houseHome: null }).appended.length, 1);

// Rule 2: a panel page never wears it.
assert.equal(run({ query: '?panel=true&kiosk=true', stored: { ...RETURN } }).appended.length, 0,
  'a panel page wears the house button');
// Rule 3: the House switched off, nothing wears it.
assert.equal(run({ path: '/trip', query: '?panel=false', stored: { ...RETURN }, houseHome: 'false' }).appended.length, 0,
  'the House is off and a page still offers a way back to it');
// No return address, no button.
assert.equal(run({ path: '/trip', query: '?panel=false' }).appended.length, 0);

// Rule 1: arriving at the House consumes the address.
r = run({ path: '/house', query: '?panel=true', stored: { ...RETURN } });
assert.equal(r.appended.length, 0);
assert.equal(r.stored.chauffeur_house_return, undefined, 'arriving home kept the return address');
// ...under ingress too (the pathname carries the prefix on both sides).
r = run({ path: '/api/hassio_ingress/abc/house', stored: { ...RETURN } });
assert.equal(r.stored.chauffeur_house_return, undefined);
// So the next page in that tab is clean.
assert.equal(run({ query: '?panel=true', stored: r.stored }).appended.length, 0);
'''


def scenario_the_button_is_a_way_back_not_a_fixture():
    node = shutil.which('node')
    if not node:
        print("  skip  node is not installed")
        return
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                     encoding='utf-8') as fh:
        fh.write(SCRIPT)
        path = fh.name
    try:
        out = subprocess.run([node, path, os.path.join(STATIC, 'house_return.js')],
                             capture_output=True, text=True, timeout=60)
        check(out.returncode == 0, f"house_return.js: {out.stderr[-800:]}")
    finally:
        os.unlink(path)


def scenario_nav_hands_the_script_the_setting():
    """The script can only honour rule 3 if the page tells it. nav.html is
    the one include every page has, so the attribute lives on its tag."""
    tpl = os.path.join(os.path.dirname(STATIC), 'templates', 'nav.html')
    src = open(tpl, encoding='utf-8').read()
    at = src.index('house_return.js')
    tag = src[src.rfind('<script', 0, at):src.index('>', at) + 1]
    check('data-house-home=' in tag and 'house_home_on()' in tag,
          f"nav's house_return tag does not carry the House setting: {tag}")


def scenario_the_pages_that_name_the_setting_still_render():
    """v2.499.403 shipped a template global called `house_home_enabled`
    while /home and /house pass a context VARIABLE of that name: the
    variable shadowed the callable and every page with nav 500'd
    ("'bool' object is not callable", the add-on log). The routes
    themselves, rendered."""
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app)
    for path in ('/home', '/house', '/routines?panel=true&kiosk=true'):
        r = client.get(path)
        check(r.status_code == 200, f"{path} answered {r.status_code}")
        check('data-house-home="false"' in r.text or 'data-house-home="true"' in r.text,
              f"{path} does not hand house_return.js the setting")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} house return scenarios passed")
