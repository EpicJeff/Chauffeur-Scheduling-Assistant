"""The service worker's notification actions actually RUN, in node.

Reading `sw.js` proves nothing here. The file is only ever executed by a
browser, off the back of a lock-screen tap, with no page open and nobody
watching — so a mistake in it is invisible until a driver taps Mark Completed
and their drive quietly stays open. That is precisely the failure this test
exists for, because it is the failure that was already there: until v2.383.0
the complete action posted `/api/drive_status` with no credential and never
looked at the response. It worked only because the app served every request to
anybody, and it would have started failing SILENTLY the moment auth
enforcement was switched on.

So: load the real `static/sw.js` in node with `self`, `caches`, `fetch` and
`clients` stubbed, fire real `notificationclick` events at it, and look at what
it did.

**Skips** (rather than fails) when node is unavailable, in the same spirit as
test_nav_runtime and test_board_render.

Run from chauffeur/:  python tests/test_sw_runtime.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_sw_runtime_')
SW_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'static', 'sw.js')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# The harness: a minimal service-worker global, then one notificationclick.
# Everything the worker touched comes back as one line of JSON on stdout.
HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

const scenario = JSON.parse(process.argv[3]);
const out = { fetches: [], notifications: [], navigated: [], opened: [], focused: 0 };

// --- the shelf the app mirrors the token onto ---------------------------
const shelf = new Map();
const caches = {
    open: async () => ({
        match: async (key) => {
            if (!shelf.has(key)) return undefined;
            const v = shelf.get(key);
            return { text: async () => v };
        },
        put: async (key, res) => { shelf.set(key, await res.text()); },
        delete: async (key) => shelf.delete(key)
    })
};
if (scenario.token !== null) shelf.set('/__sw/member-token', scenario.token);

// --- the network ---------------------------------------------------------
async function fetchStub(url, opts) {
    out.fetches.push({ url, headers: (opts || {}).headers || {}, body: (opts || {}).body || '' });
    if (scenario.network === 'throw') throw new Error('offline');
    return { ok: scenario.network === 'ok', status: scenario.network === 'ok' ? 200 : 403 };
}

// --- open windows --------------------------------------------------------
const windowClients = (scenario.openWindows || []).map(url => ({
    url,
    focus: () => { out.focused++; },
    navigate: (u) => { out.navigated.push(u); }
}));
const clients = {
    matchAll: async () => windowClients,
    claim: async () => {},
    openWindow: async (u) => { out.opened.push(u); }
};

// --- the worker global ---------------------------------------------------
const listeners = {};
const self = {
    addEventListener: (name, fn) => { listeners[name] = fn; },
    skipWaiting: () => {},
    registration: {
        showNotification: async (title, options) => {
            out.notifications.push({ title, options });
        }
    }
};

const sandbox = { self, caches, clients, fetch: fetchStub, console,
                  Response, JSON, Promise, Error, setTimeout };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), sandbox);

(async () => {
    const waits = [];
    const event = {
        action: scenario.action,
        notification: { data: scenario.data || {}, close: () => {} },
        waitUntil: (p) => { waits.push(p); }
    };
    listeners['notificationclick'](event);
    await Promise.all(waits);
    console.log(JSON.stringify(out));
})();
"""

_NODE = shutil.which('node')
_HARNESS_PATH = None


def _run(scenario):
    """Fire one notificationclick at the real sw.js; return what it did."""
    global _HARNESS_PATH
    if not _NODE:
        return None
    if _HARNESS_PATH is None:
        _HARNESS_PATH = os.path.join(SCRATCH, 'sw_harness.js')
        with open(_HARNESS_PATH, 'w', encoding='utf-8') as f:
            f.write(HARNESS)
    base = {'action': 'complete', 'token': 'tok-abc', 'network': 'ok',
            'data': {'leg_id': 'leg-1', 'navigate_url': '/app?arrival=leg-1'},
            'openWindows': []}
    base.update(scenario)
    proc = subprocess.run([_NODE, _HARNESS_PATH, SW_PATH, json.dumps(base)],
                          capture_output=True, text=True, cwd=SCRATCH, timeout=60)
    check(proc.returncode == 0,
          f"the service worker threw while handling the tap:\n{proc.stderr[:2000]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_complete_sends_the_member_token():
    """The whole point. A lock-screen tap must prove who it is.

    Without the header this request is anonymous, and `/api/drive_status` is
    SIGNED_IN in the auth table — so at the flip it becomes a 403 that nobody
    ever sees.
    """
    got = _run({})
    if got is None:
        print("  skip  node is not installed — the worker was not run")
        return
    check(len(got['fetches']) == 1,
          f"expected one drive_status post, got {len(got['fetches'])}")
    f = got['fetches'][0]
    check('/api/drive_status' in f['url'], f"posted the wrong url: {f['url']}")
    check(f['headers'].get('X-Member-Token') == 'tok-abc',
          f"the tap went out without the member token: {f['headers']}")
    check(json.loads(f['body'])['status'] == 'completed',
          f"the leg was not marked completed: {f['body']}")
    check(not got['notifications'],
          "a successful tap should say nothing — the drive is simply done")


def scenario_no_token_opens_the_app_instead():
    """A device nobody has signed in on cannot complete a drive.

    Firing the request anyway would earn a 403 and, before this change, look
    exactly like success. Handing the job to the app costs the driver one more
    tap and actually finishes it.
    """
    got = _run({'token': None, 'openWindows': []})
    if got is None:
        return
    check(not got['fetches'],
          "a tokenless device posted the drive anyway — that is the 403 nobody sees")
    check(got['opened'] == ['/app?arrival=leg-1'],
          f"the app was not opened at the arrival deep link: {got['opened']}")


def scenario_refusal_is_not_silent():
    """A refused tap must TELL the driver.

    This is the bug the arc is really about: a drive the driver believes is
    checked off, and isn't, is worse than one they know is still open.
    """
    got = _run({'network': 'refused'})
    if got is None:
        return
    check(len(got['fetches']) == 1, "the post was never attempted")
    check(len(got['notifications']) == 1,
          f"a refused tap raised {len(got['notifications'])} notifications — "
          f"silence here is the whole defect")
    note = got['notifications'][0]
    check('/app?arrival=leg-1' == note['options']['data']['navigate_url'],
          f"the recovery notification cannot be tapped back to the drive: {note}")


def scenario_offline_is_not_silent_either():
    """A thrown fetch is the same class of failure as a refused one."""
    got = _run({'network': 'throw'})
    if got is None:
        return
    check(len(got['notifications']) == 1,
          "an offline tap vanished without telling anybody")


def scenario_navigate_action_focuses_an_open_app():
    """The other two actions kept working when `openApp` was extracted.

    They were duplicated inline before; this is the behaviour-preservation
    half of that refactor.
    """
    got = _run({'action': 'navigate', 'openWindows': ['https://host/app']})
    if got is None:
        return
    check(not got['fetches'], "the navigate action posted something")
    check(got['navigated'] == ['/app?arrival=leg-1'],
          f"the open app was not navigated: {got['navigated']}")
    check(got['focused'] == 1, "the open app was not focused")
    check(not got['opened'], "a second window was opened over the existing one")


def scenario_body_tap_opens_the_app():
    """Tapping the notification itself, with nothing already open."""
    got = _run({'action': '', 'openWindows': []})
    if got is None:
        return
    check(got['opened'] == ['/app?arrival=leg-1'],
          f"the body tap did not open the app: {got['opened']}")


def scenario_body_tap_without_a_url_still_lands_somewhere():
    """No navigate_url in the payload — the default is the app itself."""
    got = _run({'action': '', 'data': {}, 'openWindows': []})
    if got is None:
        return
    check(got['opened'] == ['/app'],
          f"a bare notification tap went nowhere: {got['opened']}")


def scenario_the_app_and_the_worker_agree_on_the_shelf():
    """Two files, one contract, no runtime error if they drift.

    The app writes the token into a named cache under a named key and the
    worker reads it back. Nothing connects them but the strings themselves —
    a typo in either produces no exception anywhere, just a worker that never
    finds a token and quietly falls back to opening the app forever. So the
    strings are asserted equal here, which is the only place that can notice.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(SW_PATH, encoding='utf-8') as f:
        sw = f.read()
    with open(os.path.join(root, 'templates', 'app.html'), encoding='utf-8') as f:
        app = f.read()
    for const in ("'chauffeur-auth-v1'", "'/__sw/member-token'"):
        check(const in sw, f"sw.js no longer names {const}")
        check(const in app,
              f"app.html no longer names {const} — the worker will never find "
              f"a token, and nothing will throw to tell you")
    check('mirrorTokenToServiceWorker' in app,
          "app.html no longer mirrors the token, so the worker's shelf is never filled")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    try:
        for fn in SCENARIOS:
            fn()
            print(f"  ok  {fn.__name__}")
        print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} service-worker runtime scenarios passed")
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
