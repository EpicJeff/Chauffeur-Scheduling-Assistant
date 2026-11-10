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

// A DOM thin enough to be honest: elements remember text, children, parent,
// attributes and listeners, and a click runs onclick plus 'click' listeners.
const created = [];
function El(tag, id) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(), id: id || '', dataset: {}, style: { setProperty() {} },
    children: [], _parent: null, _listeners: {}, _attrs: {}, textContent: '', innerHTML: '', innerText: '',
    value: '', disabled: false, onclick: null, className: '', type: '',
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
    appendChild(c) { if (c && typeof c === 'object') { c._parent = el; el.children.push(c); } return c; },
    insertBefore(c) { return el.appendChild(c); }, prepend(c) { return el.appendChild(c); },
    append(...cs) { cs.forEach(c => typeof c === 'object' ? el.appendChild(c) : (el.textContent += String(c))); },
    replaceChildren(...cs) { el.children = []; cs.forEach(c => el.append(c)); },
    removeChild(c) { return c; }, remove() {}, contains() { return false; },
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
  body: El('body'), documentElement: El('html'),
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
const flush = (ms) => new Promise(r => setTimeout(r, ms || 50));
const out = { forbidden, calls, storageWrites, alerts: [], choices: [], inputs: [] };

(async function () {
  try {
    for (const src of input.blocks) vm.runInThisContext(src);
    // The page's own prompt helpers are replaced by scripted answers.
    const choices = (input.choices || []).slice();
    const pins = (input.pins || []).slice();
    globalThis.showGlobalAlert = function (msg) { out.alerts.push(String(msg)); };
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
    const scenario = new Function('out', 'flush', 'created', 'byId',
                                  'return (async () => {' + input.scenario + '})();');
    await scenario(out, flush, created, byId);
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  console.log(JSON.stringify(out));
})();
"""


def ok(body):
    return {'status': 200, 'body': body}


def refused(status, message, needs=None, kinds=None):
    return {'status': status, 'body': {'detail': {'message': message, 'needs': needs, 'kinds': kinds or []}}}


IDENTIFY = refused(403, "Who's asking? Identify yourself and enter your PIN.", 'identify', ['locks'])


class ControlGrantJs(unittest.TestCase):
    def run_cc(self, scenario, routes, choices=(), pins=(), needs=()):
        out = run_node(CC_HARNESS, {
            'base': BASE, 'blocks': _cc_blocks(), 'scenario': scenario,
            'routes': [['api/members', [ok(MEMBERS)]], *routes],
            'choices': list(choices), 'pins': list(pins),
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
  console.log(JSON.stringify(out));
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
