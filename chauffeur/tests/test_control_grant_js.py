""""Ask who" on the wall panel, run under node (Task 7 of
docs/superpowers/plans/2026-11-09-ha-control-permissions.md; brief in
.superpowers/sdd/2026-11-09-ha-control-permissions/task-7-brief.md).

A tap on the wall that the household lets the panel do only once it knows
who is asking gets a face picker and a PIN, then the one action runs. The PIN
buys a one-use grant; nothing is stored. Typed Argyle on the panel gets the
same step through a "Who's asking?" button on the chat bubble.

CONTRACT these tests fix (the names did not exist when they were written):

* templates/components/control_center.html defines, on window:
  - chfControlGrant() -> Promise<string|null>
      promptChoice("Who's asking?", '', [{value: member id, label}]) over the
      active members from chfBase + 'api/members'; a member with has_pin false
      is offered but, when picked, gets showGlobalAlert('Set a PIN to use this
      from the wall.') and the call returns null without a POST. Otherwise
      promptInput('Hi <name>!', 'Enter your PIN', {type: 'password'}) and a
      POST to chfBase + 'api/ha/control/grant' with {member_id, pin}:
      403 -> showGlobalAlert('Wrong PIN') and ask again; 429 ->
      showGlobalAlert('Too many tries — wait a moment') and null.
      Returns the grant; never writes it to storage.
  - chfControlFetch(url, opts) -> Promise<Response>
      403 with detail.needs === 'identify' -> chfControlGrant(), then ONE retry
      with header x-control-grant; any other refusal (and a second refusal)
      -> showGlobalAlert(detail.message), never retried again.
  - chfControlHeldButton(held) -> Element
      held is the /api/chat reply's control_held ({id, message}). Returns a
      <button> made with document.createElement whose click (onclick or a
      'click' listener) runs chfControlGrant(), POSTs chfBase +
      'api/ha/control/held/' + id with header x-control-grant, and shows the
      reply's `message`. The chat send path calls window.chfControlHeldButton
      when a reply carries control_held and attaches the element to the reply
      bubble.
  Every <script> block in control_center.html must still load under node with
  a stub DOM (they do today).
* templates/nav.html attachDeviceToken and components/admin_gate.html
  attachAdminToken keep X-Device-Token on control requests (api/ha/control/*,
  api/ha/toggle, api/ha/card/service, api/ha/card/climate,
  api/ha/media_players/<id>/command) while a house session or an admin
  session is present; every other request still drops it (unchanged).

alert, confirm and prompt throw in every run.

Run from chauffeur/ with HA_BASE_URL unset:  python tests/test_control_grant_js.py
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(HERE, 'templates')
CONTROL_CENTER = os.path.join(TPL, 'components', 'control_center.html')
NAV = os.path.join(TPL, 'nav.html')
ADMIN_GATE = os.path.join(TPL, 'components', 'admin_gate.html')
BASE = '/api/hassio_ingress/tok/'

MEMBERS = [
    {'id': 'mum', 'name': 'Mum', 'role': 'parent', 'has_pin': True, 'status': 'active'},
    {'id': 'dad', 'name': 'Dad', 'role': 'parent', 'has_pin': False, 'status': 'active'},
    {'id': 'gran', 'name': 'Gran', 'role': 'guest', 'has_pin': True, 'status': 'archived'},
]


def _node():
    node = shutil.which('node')
    if not node:
        raise unittest.SkipTest('node is not installed')
    return node


def run_node(harness, payload):
    d = tempfile.mkdtemp(prefix='chf_grant_js_')
    try:
        js = os.path.join(d, 'harness.js')
        data = os.path.join(d, 'input.json')
        with open(js, 'w', encoding='utf-8') as f:
            f.write(harness)
        with open(data, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
        r = subprocess.run([_node(), js, data], capture_output=True, text=True,
                           encoding='utf-8', timeout=60)
        if r.returncode != 0 or not r.stdout.strip():
            raise AssertionError(f'node failed ({r.returncode}): {r.stderr[-3000:]}')
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _cc_blocks():
    with open(CONTROL_CENTER, encoding='utf-8') as f:
        src = f.read()
    blocks = [body for attrs, body in re.findall(r'<script(\s[^>]*)?>(.*?)</script>', src, re.S)
              if 'src=' not in (attrs or '')]
    assert blocks, 'control_center.html has no inline scripts'
    return blocks


def _iife(path, name):
    """The wrapper's own text: from `(function name() {` to its `})();`."""
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    start = next(i for i, line in enumerate(lines) if f'(function {name}()' in line)
    indent = lines[start][:len(lines[start]) - len(lines[start].lstrip())]
    end = next(i for i in range(start + 1, len(lines)) if lines[i].rstrip() == indent + '})();')
    text = '\n'.join(lines[start:end + 1])
    assert '{{' not in text and '{%' not in text, f'{name} picked up template syntax'
    return text


# --- control_center under node ---------------------------------------------

CC_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
globalThis.window = globalThis;
const forbidden = [];
for (const name of ['alert', 'confirm', 'prompt']) {
  globalThis[name] = function () { forbidden.push(name); throw new Error('browser dialog: ' + name); };
}

// A DOM thin enough to be honest: elements remember text, children, ONE
// parent (appending elsewhere moves a node; remove() detaches it), classes,
// attributes and listeners, and a click runs onclick plus 'click' listeners.
const created = [];
function detach(c) {
  if (c && c._parent) {
    const i = c._parent.children.indexOf(c);
    if (i !== -1) c._parent.children.splice(i, 1);
    c._parent = null;
  }
}
function El(tag, id) {
  const classes = new Set();
  const el = {
    tagName: String(tag || 'div').toUpperCase(), id: id || '', dataset: {}, style: { setProperty() {} },
    children: [], _parent: null, _removed: false, _listeners: {}, _attrs: {}, textContent: '', innerHTML: '', innerText: '',
    value: '', disabled: false, onclick: null, className: '', type: '',
    get parentNode() { return el._parent; }, get parentElement() { return el._parent; },
    classList: {
      add(...cs) { cs.forEach(c => classes.add(c)); }, remove(...cs) { cs.forEach(c => classes.delete(c)); },
      contains(c) { return classes.has(c); },
      toggle(c, force) { const on = force === undefined ? !classes.has(c) : !!force; on ? classes.add(c) : classes.delete(c); return on; },
    },
    appendChild(c) { if (c && typeof c === 'object') { detach(c); c._parent = el; c._removed = false; el.children.push(c); } return c; },
    insertBefore(c) { return el.appendChild(c); }, prepend(c) { return el.appendChild(c); },
    append(...cs) { cs.forEach(c => typeof c === 'object' ? el.appendChild(c) : (el.textContent += String(c))); },
    replaceChildren(...cs) { el.children.slice().forEach(detach); cs.forEach(c => el.append(c)); },
    removeChild(c) { detach(c); if (c) c._removed = true; return c; },
    remove() { detach(el); el._removed = true; },
    contains() { return false; },
    addEventListener(t, fn) { (el._listeners[t] = el._listeners[t] || []).push(fn); }, removeEventListener() {},
    setAttribute(k, v) { el._attrs[k] = String(v); }, getAttribute(k) { return k in el._attrs ? el._attrs[k] : null; },
    removeAttribute(k) { delete el._attrs[k]; },
    querySelector() { return null; }, querySelectorAll() { return []; }, closest() { return null; },
    getBoundingClientRect() { return { top: 0, left: 0, bottom: 0, right: 0, width: 0, height: 0 }; },
    focus() {}, blur() {}, offsetHeight: 0, offsetWidth: 0,
    click() {
      const ev = { preventDefault() {}, stopPropagation() {}, target: el, currentTarget: el };
      if (typeof el.onclick === 'function') el.onclick(ev);
      (el._listeners.click || []).forEach(f => f(ev));
    },
  };
  created.push(el);
  return el;
}
const byId = {};
globalThis.document = {
  getElementById(id) { return byId[id] || (byId[id] = El('div', id)); },
  createElement(tag) { return El(tag); },
  createTextNode(t) { const n = El('#text'); n.textContent = String(t); return n; },
  querySelector() { return null; }, querySelectorAll() { return []; },
  addEventListener() {}, removeEventListener() {},
  body: El('body'), documentElement: El('html'), head: El('head'),
};
globalThis.location = { pathname: '/home', search: '?panel=true', origin: 'http://chauffeur.local',
                        href: 'http://chauffeur.local/home?panel=true' };
const store = { chauffeur_device_token: 'dev-tok' };
const storageWrites = [];
globalThis.localStorage = {
  getItem(k) { return k in store ? store[k] : null; },
  setItem(k, v) { storageWrites.push([k, String(v)]); store[k] = String(v); },
  removeItem(k) { delete store[k]; },
};
globalThis.sessionStorage = {
  getItem() { return null; }, setItem(k, v) { storageWrites.push([k, String(v)]); }, removeItem() {},
};
globalThis.requestAnimationFrame = (f) => setTimeout(f, 0);
globalThis.innerWidth = 1280; globalThis.innerHeight = 800; globalThis.scrollX = 0; globalThis.scrollY = 0;
globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = (o || {}).detail; } };
globalThis.dispatchEvent = () => true;
globalThis.addEventListener = () => {};
window.chfBase = input.base;

// fetch: routes are [substring, [responses]], first match wins, the last
// response repeats. A response {throw: true} rejects like a dropped network.
const calls = [];
const cursors = {};
globalThis.fetch = async function (url, opts) {
  opts = opts || {};
  const headers = {};
  new Headers(opts.headers || {}).forEach((v, k) => { headers[k.toLowerCase()] = v; });
  calls.push({ url: String(url), method: String(opts.method || 'GET').toUpperCase(), headers,
               body: opts.body === undefined ? null : String(opts.body) });
  for (const [needle, responses] of input.routes) {
    if (String(url).indexOf(needle) === -1) continue;
    const i = cursors[needle] || 0;
    cursors[needle] = i + 1;
    const r = responses[Math.min(i, responses.length - 1)];
    if (r.throw) throw new TypeError('Failed to fetch');
    return new Response(JSON.stringify(r.body === undefined ? {} : r.body),
                        { status: r.status || 200, headers: { 'Content-Type': 'application/json' } });
  }
  return new Response('{}', { status: 404, headers: { 'Content-Type': 'application/json' } });
};
const realSetTimeout = setTimeout;
const realClearTimeout = clearTimeout;
const flush = (ms) => new Promise(r => realSetTimeout(r, ms || 50));
let vnow = 0;
const virtual = [];
if (input.fakeTimers) {
  globalThis.setTimeout = function (fn, ms, ...args) {
    ms = Number(ms) || 0;
    if (ms < 1000) return realSetTimeout(fn, ms, ...args);
    const t = { fn, due: vnow + ms, args };
    virtual.push(t);
    return t;
  };
  globalThis.clearTimeout = function (t) {
    const i = virtual.indexOf(t);
    if (i !== -1) virtual.splice(i, 1); else realClearTimeout(t);
  };
}
// Move the virtual clock forward, running every long timer that falls due.
async function advance(ms) {
  const target = vnow + ms;
  while (true) {
    virtual.sort((a, b) => a.due - b.due);
    const t = virtual[0];
    if (!t || t.due > target) break;
    virtual.shift();
    vnow = t.due;
    if (typeof t.fn === 'function') t.fn(...t.args);
    await flush(20);
  }
  vnow = target;
  await flush(400);
}
const out = { forbidden, calls, storageWrites, alerts: [], choices: [], inputs: [] };

(async function () {
  try {
    for (const src of input.blocks) vm.runInThisContext(src);
    for (const src of (input.extra || [])) vm.runInThisContext(src);
    // What the page's own showGlobalAlert hands its ~30 existing callers.
    try {
      const r = window.showGlobalAlert('probe');
      out.realAlertReturn = r === undefined ? 'undefined'
        : (r && typeof r.then === 'function' ? 'promise' : typeof r);
    } catch (e) { out.realAlertReturn = 'threw: ' + e; }
    // The page's own prompt helpers are replaced by scripted answers.
    const choices = (input.choices || []).slice();
    const pins = (input.pins || []).slice();
    // alertPending: the alert behaves like a modal nobody has dismissed yet,
    // for a caller that (wrongly) waits on it.
    globalThis.showGlobalAlert = function (msg) {
      out.alerts.push(String(msg));
      return input.alertPending ? new Promise(() => {}) : undefined;
    };
    globalThis.promptConfirm = async function () { return true; };
    globalThis.promptChoice = async function (title, message, options) {
      out.choices.push({ title, message, options: (options || []).map(o => ({ value: o.value, label: o.label })) });
      const want = choices.length ? choices.shift() : null;
      if (want === null) return null;
      const hit = (options || []).find(o => o.value === want || String(o.label || '').indexOf(want) !== -1);
      return hit ? hit.value : null;
    };
    globalThis.promptInput = async function (title, message, opts) {
      out.inputs.push({ title, message, type: (opts || {}).type || null });
      return pins.length ? pins.shift() : null;
    };
    out.types = {
      grant: typeof window.chfControlGrant, fetch: typeof window.chfControlFetch,
      button: typeof window.chfControlHeldButton,
    };
    const scenario = new Function('out', 'flush', 'created', 'byId', 'advance',
                                  'return (async () => {' + input.scenario + '})();');
    await scenario(out, flush, created, byId, advance);
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  // A long timer the page left behind (a bubble's dismissal) must not hold
  // node open past the answer.
  process.stdout.write(JSON.stringify(out) + '\n', () => process.exit(0));
})();
"""


def ok(body):
    return {'status': 200, 'body': body}


def refused(status, message, needs=None, kinds=None):
    return {'status': status, 'body': {'detail': {'message': message, 'needs': needs, 'kinds': kinds or []}}}


IDENTIFY = refused(403, "Who's asking? Identify yourself and enter your PIN.", 'identify', ['locks'])


class ControlGrantJs(unittest.TestCase):
    def run_cc(self, scenario, routes, choices=(), pins=(), needs=(), **opts):
        out = run_node(CC_HARNESS, {
            'base': BASE, 'blocks': _cc_blocks(), 'scenario': scenario,
            'routes': [*routes, ['api/members', [ok(MEMBERS)]]],
            'choices': list(choices), 'pins': list(pins), **opts,
        })
        self.assertDefined(out, *needs)
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(out['forbidden'], [], 'alert/confirm/prompt are banned')
        return out

    NAMES = {'grant': 'chfControlGrant', 'fetch': 'chfControlFetch', 'button': 'chfControlHeldButton'}

    def assertDefined(self, out, *names):
        for name in names:
            self.assertEqual((out.get('types') or {}).get(name), 'function',
                             f'window.{self.NAMES[name]} is not defined')

    def grant_calls(self, out):
        return [c for c in out['calls'] if 'api/ha/control/grant' in c['url']]

    # --- chfControlGrant ---------------------------------------------------

    def test_grant_happy(self):
        out = self.run_cc('out.result = await window.chfControlGrant();',
                          [['api/ha/control/grant', [ok({'grant': 'g-1', 'expires_in': 60})]]],
                          choices=['mum'], pins=['4321'], needs=('grant',))
        self.assertEqual(out['result'], 'g-1')

        self.assertEqual(len(out['choices']), 1)
        self.assertEqual(out['choices'][0]['title'], "Who's asking?")
        offered = [o['value'] for o in out['choices'][0]['options']]
        self.assertIn('mum', offered)
        self.assertIn('dad', offered, 'a member without a PIN is shown')
        self.assertNotIn('gran', offered, 'only active members are offered')
        self.assertTrue(any(c['url'] == BASE + 'api/members' or c['url'].startswith(BASE + 'api/members?')
                            for c in out['calls']), 'members are read relative to chfBase')

        self.assertEqual(out['inputs'], [{'title': 'Hi Mum!', 'message': 'Enter your PIN', 'type': 'password'}])
        grants = self.grant_calls(out)
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]['url'], BASE + 'api/ha/control/grant', 'relative to chfBase, never root-relative')
        self.assertEqual(grants[0]['method'], 'POST')
        self.assertEqual(json.loads(grants[0]['body']), {'member_id': 'mum', 'pin': '4321'})
        self.assertFalse(any('g-1' in v for _, v in out['storageWrites']), 'a grant is never stored')

    def test_grant_wrong_then_right(self):
        out = self.run_cc('out.result = await window.chfControlGrant();',
                          [['api/ha/control/grant', [refused(403, 'Wrong PIN', 'pin'), ok({'grant': 'g-2'})]]],
                          choices=['mum', 'mum'], pins=['0000', '4321'], needs=('grant',))
        self.assertEqual(out['result'], 'g-2')
        self.assertIn('Wrong PIN', out['alerts'])
        grants = self.grant_calls(out)
        self.assertEqual([json.loads(c['body'])['pin'] for c in grants], ['0000', '4321'])

    def test_grant_too_many_tries(self):
        out = self.run_cc('out.result = await window.chfControlGrant();',
                          [['api/ha/control/grant', [{'status': 429, 'body': {'detail': 'Too many tries'}}]]],
                          choices=['mum', 'mum'], pins=['0000', '4321'], needs=('grant',))
        self.assertIsNone(out.get('result'))
        self.assertIn('Too many tries — wait a moment', out['alerts'])
        self.assertEqual(len(self.grant_calls(out)), 1, 'a rate limit stops asking')

    def test_grant_pinless_member(self):
        out = self.run_cc('out.result = await window.chfControlGrant();',
                          [['api/ha/control/grant', [ok({'grant': 'never'})]]],
                          choices=['dad'], pins=['1234'], needs=('grant',))
        self.assertIsNone(out.get('result'))
        self.assertIn('Set a PIN to use this from the wall.', out['alerts'])
        self.assertEqual(self.grant_calls(out), [], 'no POST for a member without a PIN')
        self.assertEqual(out['inputs'], [], 'no PIN pad for a member without a PIN')

    def test_grant_cancelled(self):
        out = self.run_cc('out.result = await window.chfControlGrant();',
                          [['api/ha/control/grant', [ok({'grant': 'never'})]]], choices=[None],
                          needs=('grant',))
        self.assertIsNone(out.get('result'))
        self.assertEqual(self.grant_calls(out), [])

    # --- chfControlFetch ---------------------------------------------------

    TOGGLE = """
      out.res = await window.chfControlFetch(window.chfBase + 'api/ha/toggle', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({entity_id: 'lock.front'})});
      out.status = out.res && out.res.status;
      delete out.res;
    """

    def toggles(self, out):
        return [c for c in out['calls'] if c['url'] == BASE + 'api/ha/toggle']

    def test_control_fetch_retries_once(self):
        out = self.run_cc(self.TOGGLE, [
            ['api/ha/control/grant', [ok({'grant': 'g-3'})]],
            ['api/ha/toggle', [IDENTIFY, ok({'ok': True})]],
        ], choices=['mum'], pins=['4321'], needs=('fetch', 'grant'))
        self.assertEqual(out['status'], 200)
        toggles = self.toggles(out)
        self.assertEqual(len(toggles), 2, toggles)
        self.assertNotIn('x-control-grant', toggles[0]['headers'])
        self.assertEqual(toggles[1]['headers'].get('x-control-grant'), 'g-3')
        self.assertEqual(toggles[1]['method'], 'POST')
        self.assertEqual(toggles[1]['headers'].get('content-type'), 'application/json')
        self.assertEqual(json.loads(toggles[1]['body']), {'entity_id': 'lock.front'})
        self.assertEqual(out['alerts'], [])

        # A second refusal is shown, never retried again.
        out = self.run_cc(self.TOGGLE, [
            ['api/ha/control/grant', [ok({'grant': 'g-3'})]],
            ['api/ha/toggle', [IDENTIFY, refused(403, 'Locks need a parent.', 'identify', ['locks'])]],
        ], choices=['mum', 'mum'], pins=['4321', '4321'], needs=('fetch', 'grant'))
        self.assertEqual(len(self.toggles(out)), 2)
        self.assertEqual(len(self.grant_calls(out)), 1, 'one grant, one retry')
        self.assertIn('Locks need a parent.', out['alerts'])

    def test_control_fetch_plain_refusal(self):
        out = self.run_cc(self.TOGGLE, [
            ['api/ha/control/grant', [ok({'grant': 'never'})]],
            ['api/ha/toggle', [refused(403, 'Locks need a parent.', None, ['locks'])]],
        ], choices=['mum'], pins=['4321'], needs=('fetch',))
        self.assertEqual(out['alerts'], ['Locks need a parent.'])
        self.assertEqual(out['choices'], [], 'no face picker for a plain refusal')
        self.assertEqual(self.grant_calls(out), [])
        self.assertEqual(len(self.toggles(out)), 1)

    # --- the chat bubble ---------------------------------------------------

    CHAT = r"""
      const real = window.chfControlHeldButton;
      const made = [];
      if (typeof real === 'function') {
        window.chfControlHeldButton = function () {
          const el = real.apply(this, arguments);
          made.push({ args: Array.from(arguments), el });
          return el;
        };
      }
      const bubbles = [];
      const realBubble = window.showAnchoredChatBubble;
      window.showAnchoredChatBubble = function () {
        bubbles.push(Array.from(arguments).map(a => typeof a === 'string' ? a : ''));
        try { return realBubble.apply(this, arguments); } catch (e) { return undefined; }
      };
      const input = byId['chat-input'];
      input.value = 'unlock the front door';
      for (const fn of (input._listeners.keydown || [])) fn({ key: 'Enter', shiftKey: false, preventDefault() {} });
      await flush(200);
      out.made = made.map(m => ({
        held: m.args[0], tag: m.el && m.el.tagName,
        text: m.el ? String(m.el.textContent || '') + ' ' + String(m.el.innerHTML || '') : '',
        attached: !!(m.el && m.el._parent),
      }));
      out.callsBeforeTap = out.calls.length;
      if (made.length && made[0].el) { made[0].el.click(); await flush(200); }
      out.bubbles = bubbles;
      out.texts = created.map(e => String(e.textContent || '') + ' ' + String(e.innerHTML || ''));
    """

    def test_chat_held_button(self):
        held = {'id': 'h-9', 'message': "Who's asking?"}
        out = self.run_cc(self.CHAT, [
            ['api/chat/conversation', [ok({'conversation': {'id': 'c1'}})]],
            ['api/chat?', [ok({'reply': "Who's asking?", 'control_held': held})]],
            ['api/ha/control/grant', [ok({'grant': 'g-4'})]],
            ['api/ha/control/held/', [ok({'status': 'ok', 'message': 'Unlocked the front door.'})]],
        ], choices=['mum'], pins=['4321'], needs=('button', 'grant'))
        self.assertTrue(any(c['url'].startswith(BASE + 'api/chat?') for c in out['calls']),
                        'the chat turn ran')

        self.assertEqual(len(out['made']), 1, 'the reply carrying control_held renders one button')
        made = out['made'][0]
        held_id = made['held'].get('id') if isinstance(made['held'], dict) else made['held']
        self.assertEqual(held_id, 'h-9')
        self.assertEqual(made['tag'], 'BUTTON')
        self.assertIn("Who's asking?", made['text'])
        self.assertTrue(made['attached'], 'the button is attached to the reply bubble')

        before = out['calls'][:out['callsBeforeTap']]
        self.assertFalse(any('api/ha/control/' in c['url'] for c in before), 'nothing is asked before the tap')
        helds = [c for c in out['calls'] if 'api/ha/control/held/' in c['url']]
        self.assertEqual(len(helds), 1, helds)
        self.assertEqual(helds[0]['url'], BASE + 'api/ha/control/held/h-9')
        self.assertEqual(helds[0]['method'], 'POST')
        self.assertEqual(helds[0]['headers'].get('x-control-grant'), 'g-4')
        shown = out['alerts'] + [s for b in out['bubbles'] for s in b] + out['texts']
        self.assertTrue(any('Unlocked the front door.' in s for s in shown), 'the reply message is shown')

    # --- no browser dialogs --------------------------------------------------

    def test_no_browser_dialogs(self):
        # Every unhappy path, with alert/confirm/prompt throwing (run_cc asserts
        # none was reached even where a try/catch would swallow the throw).
        scenario = r"""
          out.r1 = await window.chfControlGrant();                       // 429
          out.r2 = await window.chfControlGrant();                       // network down
          out.r3 = await window.chfControlGrant();                       // PIN-less member
          await window.chfControlFetch(window.chfBase + 'api/ha/card/service', {method: 'POST', body: '{}'});
          await window.chfControlFetch(window.chfBase + 'api/ha/card/climate', {method: 'POST', body: '{}'});
          const btn = window.chfControlHeldButton({ id: 'h-1', message: "Who's asking?" });
          btn.click(); await flush(100);                                 // cancelled picker
          out.sources = [window.chfControlGrant, window.chfControlFetch, window.chfControlHeldButton]
            .map(f => String(f));
        """
        out = self.run_cc(scenario, [
            ['api/ha/control/grant', [{'status': 429, 'body': {}}, {'throw': True}]],
            ['api/ha/card/service', [refused(403, 'Not from the wall.', None)]],
            ['api/ha/card/climate', [{'status': 403, 'body': {'detail': 'Not authenticated'}}]],
        ], choices=['mum', 'mum', 'dad', None], pins=['1', '2'], needs=('grant', 'fetch', 'button'))
        for src in out['sources']:
            self.assertIsNone(re.search(r'(?<![\w.$])(alert|confirm|prompt)\s*\(', src), src[:400])


# --- nav.html and admin_gate.html fetch wrappers ----------------------------

WRAP_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
globalThis.window = globalThis;
for (const name of ['alert', 'confirm', 'prompt']) {
  globalThis[name] = function () { throw new Error('browser dialog: ' + name); };
}
globalThis.location = { pathname: '/home', search: '', origin: 'http://chauffeur.local', href: 'http://chauffeur.local/home' };
const store = { chauffeur_device_token: 'dev-tok', chauffeur_device_id: 'did-1' };
globalThis.localStorage = {
  getItem(k) { return k in store ? store[k] : null; }, setItem(k, v) { store[k] = String(v); }, removeItem(k) { delete store[k]; },
};
const seen = [];
globalThis.fetch = async function (url, init) {
  const headers = {};
  new Headers((init || {}).headers || {}).forEach((v, k) => { headers[k.toLowerCase()] = v; });
  seen.push({ url: String(url), headers });
  return new Response('{}', { status: 200 });
};
if (input.house) window.chfHouseParent = () => ({ id: 'mum', token: 'house-tok' });
if (input.admin) window.chfAdminSession = () => ({ id: 'mum', token: 'admin-tok' });
(async function () {
  const out = { seen };
  try {
    // Page order: the admin gate is included above nav's own wrapper.
    if (input.gate) vm.runInThisContext(input.gate);
    if (input.nav) vm.runInThisContext(input.nav);
    for (const req of input.requests) {
      await window.fetch(req.url, { method: 'POST', headers: req.headers || {} });
    }
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  // A long timer the page left behind (a bubble's dismissal) must not hold
  // node open past the answer.
  process.stdout.write(JSON.stringify(out) + '\n', () => process.exit(0));
})();
"""

CONTROL_URLS = [
    BASE + 'api/ha/control/grant',
    BASE + 'api/ha/control/held/h-1',
    BASE + 'api/ha/toggle',
    BASE + 'api/ha/card/service',
    BASE + 'api/ha/card/climate',
    BASE + 'api/ha/media_players/media_player.kitchen/command',
]
ORDINARY_URLS = [BASE + 'api/members', BASE + 'api/schedule']


class FetchWrappers(unittest.TestCase):
    def run_wrap(self, nav=False, gate=False, house=False, admin=False, headers=None):
        reqs = [{'url': u, 'headers': dict(headers or {})} for u in CONTROL_URLS + ORDINARY_URLS]
        out = run_node(WRAP_HARNESS, {
            'nav': _iife(NAV, 'attachDeviceToken') if nav else None,
            'gate': _iife(ADMIN_GATE, 'attachAdminToken') if gate else None,
            'house': house, 'admin': admin, 'requests': reqs,
        })
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(len(out['seen']), len(reqs))
        return {s['url']: s['headers'] for s in out['seen']}

    def test_nav_keeps_device_token_on_control_during_house_session(self):
        seen = self.run_wrap(nav=True, house=True)
        for url in CONTROL_URLS:
            self.assertEqual(seen[url].get('x-device-token'), 'dev-tok',
                             f'Ask who needs the panel on {url} during a house session')
        for url in ORDINARY_URLS:
            self.assertNotIn('x-device-token', seen[url], f'{url}: the person outranks the furniture')
            self.assertEqual(seen[url].get('x-member-token'), 'house-tok')

    def test_nav_keeps_device_token_on_control_during_admin_session(self):
        seen = self.run_wrap(nav=True, admin=True)
        for url in CONTROL_URLS:
            self.assertEqual(seen[url].get('x-device-token'), 'dev-tok', url)
        for url in ORDINARY_URLS:
            self.assertNotIn('x-device-token', seen[url], url)
            self.assertEqual(seen[url].get('x-member-token'), 'admin-tok')

    def test_nav_unchanged_without_a_person(self):
        seen = self.run_wrap(nav=True)
        for url in CONTROL_URLS + ORDINARY_URLS:
            self.assertEqual(seen[url].get('x-device-token'), 'dev-tok', url)
            self.assertNotIn('x-member-token', seen[url], url)

    def test_admin_gate_keeps_device_token_on_control(self):
        seen = self.run_wrap(gate=True, admin=True, headers={'X-Device-Token': 'dev-tok'})
        for url in CONTROL_URLS:
            self.assertEqual(seen[url].get('x-device-token'), 'dev-tok', url)
        for url in ORDINARY_URLS:
            self.assertNotIn('x-device-token', seen[url], f'{url}: still dropped beside an admin session')
            self.assertEqual(seen[url].get('x-member-token'), 'admin-tok')

    def test_both_wrappers_chained(self):
        # On an admin page both are installed: nav's wrapper adds the device
        # token and hands the request to the gate's, which must not strip it.
        seen = self.run_wrap(nav=True, gate=True, admin=True)
        for url in CONTROL_URLS:
            self.assertEqual(seen[url].get('x-device-token'), 'dev-tok', url)
        for url in ORDINARY_URLS:
            self.assertNotIn('x-device-token', seen[url], url)


# --- review rulings (Claude review of f741261c) ------------------------------
#
# 1. Only a wrong PIN asks again; any other refusal of the PIN step is final.
# 2. The avatar/critter PIN pad (chfMemberToken) reopens after a wrong PIN
#    without waiting for the alert; showGlobalAlert returns nothing, as before.
# 3. The held-action bubble has a close control (a created element with a
#    click handler, not the action button), goes a few seconds after a
#    completed action, and by itself at about 120 s (the held lifetime). A 404
#    ("expired or already used") is final: no fresh face + PIN round.
# 4. A refusal chfControlFetch already showed is not shown again: the error
#    music_logic.js json() and the hosted card's callService throw carries
#    `shown === true`; an error nobody showed carries no such flag.
# 5. One window.chfIsControlUrl(url), defined in nav.html (in the script that
#    carries its fetch wrapper); admin_gate.html asks it at request time and
#    keeps a local fallback only for when it is absent; both agree.
# 6. Concurrent chfControlGrant() calls share one picker and one result.

STATIC = os.path.join(HERE, 'static')


def _static(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as f:
        return f.read()


HELD_SETUP = r"""
  const real = window.chfControlHeldButton;
  let button = null;
  window.chfControlHeldButton = function () { button = real.apply(this, arguments); return button; };
  const input = byId['chat-input'];
  input.value = 'unlock the front door';
  for (const fn of (input._listeners.keydown || [])) fn({ key: 'Enter', shiftKey: false, preventDefault() {} });
  await flush(200);
  if (!button) throw new Error('the chat reply made no held button');
  let bubble = button;
  while (bubble._parent && bubble._parent !== document.body) bubble = bubble._parent;
  const gone = () => bubble._removed || !bubble._parent || bubble.style.display === 'none'
    || bubble.classList.contains('hidden');
  const descendants = (el) => el.children.reduce((acc, c) => acc.concat([c], descendants(c)), []);
  const clickable = (el) => typeof el.onclick === 'function' || (el._listeners.click || []).length > 0;
  out.shownAtStart = !gone();
"""

HELD_ROUTES = [
    ['api/chat/conversation', [ok({'conversation': {'id': 'c1'}})]],
    ['api/chat?', [ok({'reply': "Who's asking?", 'control_held': {'id': 'h-9', 'message': "Who's asking?"}})]],
    ['api/ha/control/grant', [ok({'grant': 'g-4'})]],
]


class ReviewRulings(unittest.TestCase):
    run_cc = ControlGrantJs.run_cc
    assertDefined = ControlGrantJs.assertDefined
    grant_calls = ControlGrantJs.grant_calls
    NAMES = ControlGrantJs.NAMES

    # --- 1 ---------------------------------------------------------------

    def test_grant_other_403_is_final(self):
        for refusal, shown in (
            (refused(403, 'A paired wall panel is required.', None), 'A paired wall panel is required.'),
            ({'status': 403, 'body': {'detail': 'Not authenticated'}}, 'Not authenticated'),
        ):
            out = self.run_cc('out.result = await window.chfControlGrant();',
                              [['api/ha/control/grant', [refusal]]],
                              choices=['mum', 'mum', 'mum'], pins=['1111', '2222', '3333'], needs=('grant',))
            self.assertIsNone(out.get('result'))
            self.assertEqual(out['alerts'], [shown], 'shown once, never as "Wrong PIN"')
            self.assertEqual(len(self.grant_calls(out)), 1, 'a refusal that is not a wrong PIN is final')
            self.assertEqual(len(out['inputs']), 1)

        # A wrong PIN still asks again, whatever the server's sentence.
        out = self.run_cc('out.result = await window.chfControlGrant();',
                          [['api/ha/control/grant', [refused(403, 'That PIN is not right.', 'pin'),
                                                     ok({'grant': 'g-5'})]]],
                          choices=['mum', 'mum'], pins=['0000', '4321'], needs=('grant',))
        self.assertEqual(out['result'], 'g-5')
        self.assertIn('Wrong PIN', out['alerts'])

    # --- 2 ---------------------------------------------------------------

    def test_member_token_wrong_pin_does_not_wait_for_alert(self):
        out = self.run_cc(
            """const p = window.chfMemberToken({ id: 'mum', name: 'Mum', has_pin: true });
               out.result = await Promise.race([p, flush(600).then(() => '__still_waiting__')]);""",
            [['api/members/mum/auth', [{'status': 403, 'body': {'detail': 'Wrong PIN'}}, ok({'token': 'tok-1'})]]],
            pins=['0000', '4321'], alertPending=True)
        self.assertEqual(out['alerts'], ['Wrong PIN'])
        self.assertEqual(len(out['inputs']), 2, 'the PIN pad reopens without the alert being dismissed')
        self.assertEqual(out['result'], 'tok-1')

    def test_prompt_input_forgets_what_was_typed(self):
        """An alarm code typed on the shared wall must not sit in the page after the
        sheet closes (review L10): the field is cleared on OK, on Cancel and on Enter."""
        out = self.run_cc(r"""
          const field = document.getElementById('cc-input-field');
          const ask = () => window.__realPromptInput('Alarm', 'Enter the code', {type: 'password'});
          let p = ask(); field.value = '1234'; document.getElementById('cc-input-ok-btn').onclick();
          out.ok = await p; out.afterOk = field.value;
          p = ask(); field.value = '5678'; document.getElementById('cc-input-cancel-btn').onclick();
          out.cancel = await p; out.afterCancel = field.value;
          p = ask(); field.value = '9012'; field.onkeydown({key: 'Enter'});
          out.enter = await p; out.afterEnter = field.value;
        """, [], extra=['window.__realPromptInput = window.promptInput;'])
        self.assertEqual(out['ok'], '1234', 'OK still answers what was typed')
        self.assertEqual(out['enter'], '9012', 'and so does Enter')
        self.assertIsNone(out['cancel'])
        self.assertEqual([out['afterOk'], out['afterCancel'], out['afterEnter']], ['', '', ''],
                         'the typed code is gone from the page once the sheet closes')

    def test_show_global_alert_returns_nothing(self):
        out = self.run_cc('', [])
        self.assertEqual(out['realAlertReturn'], 'undefined',
                         'showGlobalAlert keeps its old return value for its existing callers')

    # --- 3 ---------------------------------------------------------------

    def test_held_bubble_has_close_control(self):
        out = self.run_cc(HELD_SETUP + r"""
          const own = new Set([button, ...descendants(button)]);
          const closers = descendants(bubble).filter(e => !own.has(e) && clickable(e));
          out.closers = closers.length;
          if (closers.length) { closers[0].click(); await flush(400); }
          out.goneAfterClose = gone();
        """, HELD_ROUTES, needs=('button',), fakeTimers=True)
        self.assertTrue(out['shownAtStart'])
        self.assertGreaterEqual(out['closers'], 1, 'the held bubble has a close control')
        self.assertTrue(out['goneAfterClose'], 'closing removes the bubble')

    def test_held_bubble_removed_after_completed_action(self):
        out = self.run_cc(HELD_SETUP + r"""
          button.click(); await flush(300);
          out.held = out.calls.filter(c => c.url.indexOf('api/ha/control/held/') !== -1).length;
          await advance(10000);
          out.goneLater = gone();
        """, HELD_ROUTES + [['api/ha/control/held/', [ok({'status': 'ok', 'message': 'Unlocked the front door.'})]]],
            choices=['mum'], pins=['4321'], needs=('button', 'grant'), fakeTimers=True)
        self.assertTrue(out['shownAtStart'])
        self.assertEqual(out['held'], 1)
        self.assertTrue(out['goneLater'], 'a completed action takes its bubble away within seconds')

    def test_held_bubble_auto_dismisses_at_held_lifetime(self):
        out = self.run_cc(HELD_SETUP + r"""
          await advance(60000);
          out.at60 = gone();
          await advance(70000);
          out.at130 = gone();
        """, HELD_ROUTES, needs=('button',), fakeTimers=True)
        self.assertTrue(out['shownAtStart'])
        self.assertFalse(out['at60'], 'still there while the held action can run')
        self.assertTrue(out['at130'], 'gone once the held action has expired (about 120 s)')

    def test_held_404_is_final(self):
        out = self.run_cc(HELD_SETUP + r"""
          button.click(); await flush(300);
          out.finalAfter404 = !!button.disabled || gone();
          if (!gone()) { button.click(); await flush(300); }
          out.texts = created.map(e => String(e.textContent || '') + ' ' + String(e.innerHTML || ''));
        """, HELD_ROUTES + [['api/ha/control/held/', [
            {'status': 404, 'body': {'detail': 'That action has expired or was already used.'}}]]],
            choices=['mum', 'mum'], pins=['4321', '4321'], needs=('button', 'grant'), fakeTimers=True)
        self.assertTrue(out['shownAtStart'])
        self.assertTrue(out['finalAfter404'], 'the button is disabled or the bubble removed')
        self.assertEqual(len(out['choices']), 1, 'no fresh face picker after a 404')
        self.assertEqual(len(self.grant_calls(out)), 1, 'no fresh PIN after a 404')
        self.assertEqual(len([c for c in out['calls'] if 'api/ha/control/held/' in c['url']]), 1)
        shown = out['alerts'] + out['texts']
        self.assertTrue(any('expired' in s for s in shown), 'the 404 is explained')

    # --- 4 ---------------------------------------------------------------

    def test_music_refusal_shown_once(self):
        out = self.run_cc(r"""
          const opts = { apiBase: window.chfBase };
          try { await window.MusicLogic.play('media_player.kitchen', 'uri:x', 'track', opts); out.played = true; }
          catch (e) { out.refusal = { message: e.message, shown: e.shown === true }; }
          try { await window.MusicLogic.queueCommand('media_player.kitchen', 'clear', {}, opts); }
          catch (e) { out.failure = { message: e.message, shown: e.shown === true }; }
        """, [['api/music/play', [refused(403, 'TV & music needs a parent.', None, ['media'])]],
              ['api/music/queue/command', [{'status': 500, 'body': {'detail': 'Music Assistant needs its token.'}}]]],
            needs=('fetch',), extra=[_static('music_logic.js')])
        self.assertEqual(out['alerts'], ['TV & music needs a parent.'])
        self.assertEqual(out.get('refusal', {}).get('message'), 'TV & music needs a parent.')
        self.assertTrue(out['refusal']['shown'], 'the thrown error says chfControlFetch already showed it')
        self.assertFalse(out.get('failure', {}).get('shown', True), 'an error nobody showed is not flagged')

    def test_card_refusal_shown_once(self):
        out = self.run_cc(r"""
          const hass = window.ChauffeurHaCards._makeHass({ states: {}, interactive: true, apiBase: window.chfBase });
          try { await hass.callService('lock', 'unlock', { entity_id: 'lock.front' }); out.called = true; }
          catch (e) { out.refusal = { message: e.message, shown: e.shown === true }; }
          try { await hass.callService('light', 'turn_on', { entity_id: 'light.a' }); }
          catch (e) { out.failure = { message: e.message, shown: e.shown === true }; }
        """, [['api/ha/card/service', [refused(403, 'Locks need a parent.', None, ['locks']),
                                       {'status': 502, 'body': {'detail': 'Home Assistant is away.'}}]]],
            needs=('fetch',), extra=[_static('ha_card_host.js')])
        self.assertEqual(out['alerts'], ['Locks need a parent.'])
        self.assertIn('refusal', out)
        self.assertTrue(out['refusal']['shown'], 'the card is told the refusal was already shown')
        self.assertFalse(out.get('failure', {}).get('shown', True), 'an error nobody showed is not flagged')

    # --- 6 ---------------------------------------------------------------

    def test_concurrent_grants_share_one_picker(self):
        out = self.run_cc(r"""
          const both = await Promise.all([window.chfControlGrant(), window.chfControlGrant()]);
          out.results = both;
        """, [['api/ha/control/grant', [ok({'grant': 'g-6'}), ok({'grant': 'g-7'})]]],
            choices=['mum', 'mum'], pins=['4321', '4321'], needs=('grant',))
        self.assertEqual(len(out['choices']), 1, 'one picker for both callers')
        self.assertEqual(len(self.grant_calls(out)), 1)
        self.assertEqual(out['results'], ['g-6', 'g-6'])


# --- 5: one chfIsControlUrl ---------------------------------------------------

_NAV_BLOCK = []


def _nav_wrapper_block():
    """nav.html's rendered script that carries its fetch wrapper (it holds Jinja)."""
    if not _NAV_BLOCK:
        import sys
        import types
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, HERE)
        import harness  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR before main loads)
        import main
        req = types.SimpleNamespace(url=types.SimpleNamespace(path='/home'), query_params={})
        page = main.templates.env.get_template('nav.html').render(request=req)
        blocks = [b for a, b in re.findall(r'<script(\s[^>]*)?>(.*?)</script>', page, re.S)
                  if 'attachDeviceToken' in b and 'src=' not in (a or '')]
        assert len(blocks) == 1, f'expected one nav wrapper script, found {len(blocks)}'
        _NAV_BLOCK.append(blocks[0])
    return _NAV_BLOCK[0]


URL_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
globalThis.window = globalThis;
for (const name of ['alert', 'confirm', 'prompt']) {
  globalThis[name] = function () { throw new Error('browser dialog: ' + name); };
}
function El() {
  const e = { style: { setProperty() {} }, dataset: {}, children: [],
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
    appendChild(c) { return c; }, insertBefore(c) { return c; }, prepend(c) { return c; },
    addEventListener() {}, removeEventListener() {}, setAttribute() {}, getAttribute() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; }, remove() {}, contains() { return false; } };
  return e;
}
globalThis.document = { getElementById() { return El(); }, createElement() { return El(); },
  querySelector() { return null; }, querySelectorAll() { return []; },
  addEventListener() {}, removeEventListener() {}, body: El(), documentElement: El(), head: El() };
globalThis.location = { pathname: '/home', search: '', hash: '', origin: 'http://chauffeur.local',
                        href: 'http://chauffeur.local/home' };
const store = { chauffeur_device_token: 'dev-tok', chauffeur_device_id: 'did-1' };
globalThis.localStorage = { getItem(k) { return k in store ? store[k] : null; },
  setItem(k, v) { store[k] = String(v); }, removeItem(k) { delete store[k]; } };
globalThis.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.addEventListener = () => {};
const seen = [];
globalThis.fetch = async function (url, init) {
  const headers = {};
  new Headers((init || {}).headers || {}).forEach((v, k) => { headers[k.toLowerCase()] = v; });
  seen.push({ url: String(url), headers });
  return new Response('{}', { status: 200 });
};
const out = { seen };
(async function () {
  try {
    const run = new Function('input', 'load', 'out',
                             'return (async () => {' + input.scenario + '})();');
    await run(input, (src) => vm.runInThisContext(src), out);
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  // A long timer the page left behind (a bubble's dismissal) must not hold
  // node open past the answer.
  process.stdout.write(JSON.stringify(out) + '\n', () => process.exit(0));
})();
"""

EDGE_URLS = [
    BASE + 'api/ha/toggle?x=1', BASE + 'api/music/play', BASE + 'api/music/queue/command',
    BASE + 'api/ha/control', BASE + 'api/ha/togglex', BASE + 'api/ha/card/services',
    'api/ha/toggle', 'http://chauffeur.local/api/ha/card/service',
    BASE + 'api/ha/media_players/x/command/extra', BASE + 'api/house/toggle', BASE + 'api/ha/states',
]


class OneControlUrlRule(unittest.TestCase):
    def run_url(self, scenario, **extra):
        out = run_node(URL_HARNESS, {'scenario': scenario, **extra})
        self.assertNotIn('error', out, out.get('error'))
        return out

    def nav_answers(self, urls):
        out = self.run_url(r"""
          load(input.nav);
          out.type = typeof window.chfIsControlUrl;
          if (out.type === 'function') out.answers = input.urls.map(u => !!window.chfIsControlUrl(u));
        """, nav=_nav_wrapper_block(), urls=urls)
        self.assertEqual(out['type'], 'function', 'nav.html defines window.chfIsControlUrl')
        return dict(zip(urls, out['answers']))

    def test_nav_defines_chf_is_control_url(self):
        answers = self.nav_answers(CONTROL_URLS + ORDINARY_URLS)
        for url in CONTROL_URLS:
            self.assertTrue(answers[url], url)
        for url in ORDINARY_URLS:
            self.assertFalse(answers[url], url)

    def test_admin_gate_reuses_chf_is_control_url(self):
        # The gate is installed ABOVE nav's script, so it must ask at request time.
        out = self.run_url(r"""
          window.chfAdminSession = () => ({ id: 'mum', token: 'admin-tok' });
          load(input.gate);
          out.asked = [];
          window.chfIsControlUrl = (u) => { out.asked.push(String(u)); return String(u).indexOf('api/custom/control') !== -1; };
          await window.fetch(input.base + 'api/custom/control', { headers: { 'X-Device-Token': 'dev-tok' } });
          await window.fetch(input.base + 'api/ha/toggle', { headers: { 'X-Device-Token': 'dev-tok' } });
        """, gate=_iife(ADMIN_GATE, 'attachAdminToken'), base=BASE)
        seen = {s['url']: s['headers'] for s in out['seen']}
        self.assertTrue(out['asked'], 'the gate never asked window.chfIsControlUrl')
        self.assertEqual(seen[BASE + 'api/custom/control'].get('x-device-token'), 'dev-tok',
                         "nav's answer decides, not a second copy of the rule")
        self.assertNotIn('x-device-token', seen[BASE + 'api/ha/toggle'])

    def test_wrappers_agree_on_control_urls(self):
        urls = CONTROL_URLS + ORDINARY_URLS + EDGE_URLS
        nav = self.nav_answers(urls)
        out = self.run_url(r"""
          window.chfAdminSession = () => ({ id: 'mum', token: 'admin-tok' });
          load(input.gate);
          for (const u of input.urls) await window.fetch(u, { headers: { 'X-Device-Token': 'dev-tok' } });
        """, gate=_iife(ADMIN_GATE, 'attachAdminToken'), urls=urls)
        gate = {s['url']: s['headers'].get('x-device-token') == 'dev-tok' for s in out['seen']}
        self.assertEqual(gate, nav, "the gate's fallback and nav's rule disagree")


class CallSites(unittest.TestCase):
    """Source check, beside the runtime tests above: the tile, hosted card
    bridge and music card posts go through chfControlFetch."""

    def test_control_posts_use_control_fetch(self):
        for path in (os.path.join(TPL, 'home.html'), os.path.join(HERE, 'static', 'ha_card_host.js'),
                     os.path.join(HERE, 'static', 'music_logic.js')):
            with open(path, encoding='utf-8') as f:
                self.assertTrue('chfControlFetch' in f.read(),
                                f'{os.path.basename(path)} posts control without chfControlFetch')


if __name__ == '__main__':
    unittest.main()
