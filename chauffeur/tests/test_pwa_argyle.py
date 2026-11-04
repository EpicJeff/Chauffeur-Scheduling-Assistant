"""Argyle from anywhere (PWA reimagined slice 2, Task 1): the overlay module
static/pwa_argyle.js, checked by RUNNING it.

Two halves.

PURE (node, no `document`, no `window`; extracted with tests/pwa_pure.py):
  * `PWA_ARGYLE_HOLD_MS = 350`;
  * `pwaArgyleGesture()` -> `{ down(t), up(t), cancel(), tick(t), state }`:
    `up` before the threshold is 'tap'; `tick` at or after the threshold is
    'hold-start' once; `up` after a hold is 'hold-end'; `cancel` returns to
    idle so the next `up` is silent (null); times are plain ms numbers;
  * `pwaArgyleNewestReply(messages, afterId, argyleId)`: the last Argyle
    message after the message `afterId` (any Argyle message when afterId is
    null); null when there is none.

JSDOM (fresh window per case, runScripts 'outside-only', url
http://localhost/app). The page globals are stubbed the way app.html makes
them: `renderCard`, `updateAgentFab`, `showGlobalAlert`, `ArgyleOrb`,
`ChauffeurPhoneVoice` and `fetch` are window properties, while `apiBase`
(`const`), `selectedMemberId` and `currentView` (`let`) are script-level
lexical globals, NOT window properties, exactly as app.html:798-825
declares them. Stubs and module both run as classic scripts in the
window's VM context, so a module that reads `window.apiBase` fails here as
it would on the phone. Pinned (task-1-brief.md):
  * `PwaArgyle.open({mode:'type'})` builds ONE `#pwa-argyle-overlay.pwa-argyle`
    in body (dim, glow, ask with a six-bar wave, you, reply with body + card,
    status role=status, form.pwa-argyle-bar with input placeholder 'Or type…'
    and a submit `button.pwa-argyle-send.argyle-orb` carrying the glyph, hint
    'Swipe down to dismiss · ' + button.pwa-argyle-to-messages), sets
    html[data-pwa-argyle]='1', pushes `{pwaOverlay:'argyle'}`, focuses the
    input, calls updateAgentFab, and ensures the DM: POST api/channels/dm
    `{member_id, other_member_id:'argyle'}` once per member;
  * submit POSTs api/channels/dm_argyle/messages `{sender_member_id, body}`,
    writes .pwa-argyle-you, says 'Thinking…'; empty text sends nothing;
  * `onStream('dm_argyle')` while open GETs `?limit=20`, draws the newest
    Argyle reply after the POST's own id (escaped) and `renderCard(card)`
    once, state idle; a second stream event does not redraw; a closed overlay
    fetches nothing and reopens clean;
  * Escape (keydown on document), a dim tap, Back (popstate) and a swipe
    down of >= 60 px on .pwa-argyle-ask close it. A close that is not from
    popstate walks history back ONCE (its own entry); a Back close never
    walks it again. Counted: popstate events, and history.back()/go(-1) calls
    through a wrapper installed before the module loads;
  * a refused DM (403 {detail}) shows the detail in .pwa-argyle-status with
    class is-refused and hides the bar; Escape still closes;
  * pwa_shell.css: the reduced-motion block names .pwa-argyle-glow and
    .pwa-argyle-wave, `.pwa-argyle` sits at z-index 300, the adult orb has
    touch-action none.
  Final review (hold-to-talk), the ChauffeurPhoneVoice.start stub keeps
  `opts.host` as ctx.host:
  * a voice turn never draws an OLD Argyle reply: the transcript's own
    stream event leaves the bubble hidden and the status Thinking; the
    turn's reply (host.reply + its stream event) is what shows;
  * host.status labels are the overlay's own words (Listening…, Thinking…,
    Speaking…), never the thread's 'press Done'; an error keeps the voice
    client's words;
  * pwa_shell.css: the input's :focus-visible outline is none and the pill
    (.pwa-argyle-bar:focus-within) carries the ring.

jsdom dispatches popstate asynchronously on history.back() (as in
test_pwa_nav.py), so the harness waits for the next popstate or 200 ms.
A missing module FAILS every case; missing node or jsdom prints `  skip`.

Run from chauffeur/ with HA_BASE_URL unset:  python tests/test_pwa_argyle.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import STATIC, check, pure_source, read, run_node  # noqa: E402

MODULE = os.path.join(STATIC, 'pwa_argyle.js')
SCRATCH = tempfile.mkdtemp(prefix='chauffeur_pwa_argyle_run_')
ASK_TEXT = 'Can Grandma take Kate Thursday?'
REPLY_TEXT = 'Grandma Ruth is free Thursday at 5:10.'
HINT = 'Swipe down to dismiss · '
TO_MESSAGES = 'full conversation in Messages'


# --- pure half ---------------------------------------------------------------

PURE_WANTED = ['pwaArgyleGesture', 'pwaArgyleNewestReply', 'PWA_ARGYLE_HOLD_MS']

PURE_PROBE = r"""
const out = {document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', cases: {}};
const U = v => v === undefined ? '__undefined__' : v;
function run(name, fn) {
  try { out.cases[name] = {value: fn()}; }
  catch (e) { out.cases[name] = {error: String(e && e.stack || e)}; }
}
const MSGS = [
  {id: 'm1', sender_member_id: 'parent', body: 'one'},
  {id: 'm2', sender_member_id: 'argyle', body: 'two'},
  {id: 'm3', sender_member_id: 'parent', body: 'three'},
  {id: 'm4', sender_member_id: 'argyle', body: 'four'},
];
const pick = (msgs, after) => {
  const r = pwaArgyleNewestReply(msgs, after, 'argyle');
  return r === null ? null : (r === undefined ? '__undefined__' : r.id);
};
run('hold_ms', () => PWA_ARGYLE_HOLD_MS);
run('tap_under_threshold', () => {
  const g = pwaArgyleGesture();
  g.down(0);
  const tick100 = U(g.tick(100));
  const up = U(g.up(200));
  const tick400 = U(g.tick(400));
  const up_again = U(g.up(500));
  return {tick100, up, tick400, up_again};
});
run('hold_gesture', () => {
  const g = pwaArgyleGesture();
  g.down(0);
  const tick349 = U(g.tick(349));
  const tick350 = U(g.tick(350));
  const tick400 = U(g.tick(400));
  const tick800 = U(g.tick(800));
  const up = U(g.up(900));
  const tick1000 = U(g.tick(1000));
  return {tick349, tick350, tick400, tick800, up, tick1000};
});
run('cancel_is_silent', () => {
  const g = pwaArgyleGesture();
  const up_without_down = U(g.up(50));
  g.down(100); g.cancel();
  const up_after_cancel = U(g.up(200));
  const tick_after_cancel = U(g.tick(600));
  g.down(1000);
  const hold = U(g.tick(1350));
  g.cancel();
  const up_after_held_cancel = U(g.up(1900));
  g.down(2000);
  const fresh_tap = U(g.up(2100));
  return {up_without_down, up_after_cancel, tick_after_cancel, hold, up_after_held_cancel, fresh_tap};
});
run('newest_reply_after_mine', () => ({after_m3: pick(MSGS, 'm3'), after_m1: pick(MSGS, 'm1')}));
run('no_reply_yet', () => ({after_m3: pick(MSGS.slice(0, 3), 'm3'), after_m4: pick(MSGS, 'm4'),
                            empty: pick([], 'm3'), empty_null: pick([], null)}));
run('first_open_takes_latest', () => ({latest: pick(MSGS, null), mine_only: pick([MSGS[0]], null)}));
console.log(JSON.stringify(out));
"""

_PURE = {}


def _pure():
    if 'error' in _PURE:
        raise _PURE['error']
    if 'out' not in _PURE:
        try:
            _PURE['out'] = run_node(pure_source('pwa_argyle.js', PURE_WANTED) + '\n' + PURE_PROBE)
        except AssertionError as e:
            _PURE['error'] = e
            raise
    return _PURE['out']


def _pure_case(name):
    out = _pure()
    if out is None:
        print(f"  skip  {name}: node is not installed")
        return None, False
    got = out['cases'][name]
    check('error' not in got, f"{name} threw under node with no document/window:\n{got.get('error')}")
    return got['value'], True


def scenario_pure_is_pure():
    """The gesture and the reply picker never reach for the page: node
    defines neither `document` nor `window`, so a single touch throws."""
    out = _pure()
    if out is None:
        print("  skip  is_pure: node is not installed")
        return
    check(not out['document_defined'] and not out['window_defined'], "the probe leaked a document/window global")
    for name, got in out['cases'].items():
        check('error' not in got, f"{name} threw with no document/window:\n{got.get('error')}")


def scenario_pure_tap_under_threshold():
    v, ran = _pure_case('tap_under_threshold')
    if not ran:
        return
    check(v['tick100'] is None, f"tick(100) before the 350 ms threshold is null, got {v['tick100']!r}")
    check(v['up'] == 'tap', f"down(0) then up(200) is a 'tap', got {v['up']!r}")
    check(v['tick400'] is None, f"a tick after the tap ended is null (no late hold-start), got {v['tick400']!r}")
    check(v['up_again'] is None, f"a second up with no down is silent (null), got {v['up_again']!r}")


def scenario_pure_hold_gesture():
    ms, ran = _pure_case('hold_ms')
    if not ran:
        return
    check(ms == 350, f"PWA_ARGYLE_HOLD_MS is 350, got {ms!r}")
    v, _ = _pure_case('hold_gesture')
    check(v['tick349'] is None, f"tick(349) is still under the threshold: null, got {v['tick349']!r}")
    check(v['tick350'] == 'hold-start', f"tick(350) at the threshold is 'hold-start', got {v['tick350']!r}")
    check(v['tick400'] is None and v['tick800'] is None,
          f"'hold-start' fires once; later ticks are null, got {v['tick400']!r}, {v['tick800']!r}")
    check(v['up'] == 'hold-end', f"up(900) after a hold is 'hold-end' (never 'tap'), got {v['up']!r}")
    check(v['tick1000'] is None, f"a tick after the hold ended is null, got {v['tick1000']!r}")


def scenario_pure_cancel_is_silent():
    v, ran = _pure_case('cancel_is_silent')
    if not ran:
        return
    check(v['up_without_down'] is None, f"an up with no down is null, got {v['up_without_down']!r}")
    check(v['up_after_cancel'] is None, f"cancel then up is silent, no tap: got {v['up_after_cancel']!r}")
    check(v['tick_after_cancel'] is None, f"cancel then tick past the threshold is null: got {v['tick_after_cancel']!r}")
    check(v['hold'] == 'hold-start', f"a second press still holds: got {v['hold']!r}")
    check(v['up_after_held_cancel'] is None,
          f"cancel after a hold-start returns to idle: the next up is null, got {v['up_after_held_cancel']!r}")
    check(v['fresh_tap'] == 'tap', f"the gesture is reusable after a cancel: a fresh down/up is a 'tap', got {v['fresh_tap']!r}")


def scenario_pure_newest_reply_after_mine():
    v, ran = _pure_case('newest_reply_after_mine')
    if not ran:
        return
    check(v['after_m3'] == 'm4', f"[me m1, argyle m2, me m3, argyle m4] after m3 -> m4, got {v['after_m3']!r}")
    check(v['after_m1'] == 'm4', f"after m1 the LAST Argyle message wins (m4, not m2), got {v['after_m1']!r}")


def scenario_pure_no_reply_yet():
    v, ran = _pure_case('no_reply_yet')
    if not ran:
        return
    check(v['after_m3'] is None, f"no Argyle message after mine -> null (m2 is older), got {v['after_m3']!r}")
    check(v['after_m4'] is None, f"the afterId message itself is never the reply -> null, got {v['after_m4']!r}")
    check(v['empty'] is None and v['empty_null'] is None, f"an empty thread -> null, got {v['empty']!r}, {v['empty_null']!r}")


def scenario_pure_first_open_takes_latest():
    v, ran = _pure_case('first_open_takes_latest')
    if not ran:
        return
    check(v['latest'] == 'm4', f"afterId null takes the latest Argyle message m4, got {v['latest']!r}")
    check(v['mine_only'] is None, f"afterId null with no Argyle message -> null, got {v['mine_only']!r}")


# --- jsdom half --------------------------------------------------------------

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const { JSDOM, VirtualConsole } = require('jsdom');
const [,, modPath, casesPath] = process.argv;
const cases = JSON.parse(fs.readFileSync(casesPath, 'utf8'));
const src = fs.existsSync(modPath) ? fs.readFileSync(modPath, 'utf8') : null;
const HTML = '<!doctype html><html><body>'
  + '<nav id="pwa-tab-bar"><button><span>My Day</span></button><button id="tab-argyle" class="argyle-orb"></button></nav>'
  + '<div id="pwa-stack" hidden></div>'
  + '</body></html>';
const ASK_TEXT = %(ask)s, REPLY_TEXT = %(reply)s;

let current = null;           // the running case's ctx, for stray rejections
const windows = [];
process.on('unhandledRejection', e => {
  if (current) current.errors.push('unhandledRejection: ' + String(e && e.stack || e));
});

function makeFetch(ctx) {
  return async function fetch(url, opts) {
    opts = opts || {};
    const method = String(opts.method || 'GET').toUpperCase();
    let body = null;
    if (opts.body != null) { try { body = JSON.parse(opts.body); } catch (e) { body = String(opts.body); } }
    const call = { url: String(url), method, body };
    ctx.calls.push(call);
    const res = (status, data) => ({
      ok: status >= 200 && status < 300, status, statusText: String(status),
      headers: { get: () => 'application/json' },
      json: async () => JSON.parse(JSON.stringify(data)),
      text: async () => JSON.stringify(data),
    });
    if (method === 'POST' && call.url === 'api/channels/dm') {
      return ctx.dmStatus === 403
        ? res(403, { detail: 'Requires chat.agent' })
        : res(200, { id: 'dm_argyle', kind: 'dm', member_ids: ['parent', 'argyle'] });
    }
    if (method === 'POST' && call.url === 'api/channels/dm_argyle/messages') {
      return res(200, { id: 'm3', sender_member_id: body && body.sender_member_id, body: body && body.body });
    }
    if (method === 'GET' && call.url === 'api/channels/dm_argyle/messages?limit=20') {
      return res(200, ctx.messages);
    }
    return res(404, { detail: 'unscripted ' + method + ' ' + call.url });
  };
}

function fresh() {
  const ctx = { errors: [], calls: [], cards: [], fabCalls: 0, stops: [], starts: [], dones: 0, alerts: [],
                pops: 0, backCalls: 0, dmStatus: 200, messages: [] };
  current = ctx;
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => ctx.errors.push(String(e && e.message || e)));
  const dom = new JSDOM(HTML, { url: 'http://localhost/app', runScripts: 'outside-only', virtualConsole: vc });
  const w = dom.window;
  windows.push(w);
  // Window-property page globals (function declarations / window.X = in the app).
  w.ArgyleOrb = { glyph: () => '<svg></svg>' };
  w.renderCard = (card) => { ctx.cards.push(card); return '<div class="card-stub"><button>Ask her</button></div>'; };
  w.updateAgentFab = () => { ctx.fabCalls++; };
  w.ChauffeurPhoneVoice = { stop: (s) => ctx.stops.push(s === undefined ? '__undefined__' : s),
                            start: (o) => { ctx.starts.push(!!o); ctx.host = (o && o.host) || null; },
                            done: () => { ctx.dones++; } };
  w.showGlobalAlert = (m) => ctx.alerts.push(String(m));
  w.fetch = makeFetch(ctx);
  w.addEventListener('popstate', () => { ctx.pops++; });
  const realBack = w.history.back.bind(w.history);
  const realGo = w.history.go.bind(w.history);
  w.history.back = function () { ctx.backCalls++; return realBack(); };
  w.history.go = function (n) { if (n === -1) ctx.backCalls++; return realGo(n); };
  const vmc = dom.getInternalVMContext();
  // Script-level lexical globals, exactly as app.html declares them (not window props).
  new vm.Script("const apiBase = '';\nlet selectedMemberId = 'parent';\nlet currentView = 'myday';",
                { filename: 'app-globals.js' }).runInContext(vmc);
  if (src === null) throw new Error('static/pwa_argyle.js is missing, window.PwaArgyle undefined');
  try { new vm.Script(src, { filename: 'pwa_argyle.js' }).runInContext(vmc); }
  catch (e) { throw new Error('static/pwa_argyle.js threw on load: ' + String(e && e.stack || e)); }
  if (!w.PwaArgyle) throw new Error('static/pwa_argyle.js loaded but window.PwaArgyle is undefined');
  return { w, ctx };
}

const flush = (ms) => new Promise(r => setTimeout(r, ms || 20));

// Resolves on the next popstate or after 200 ms, whichever first.
function nextPop(w) {
  return new Promise(resolve => {
    let done = false;
    const finish = how => { if (!done) { done = true; resolve(how); } };
    w.addEventListener('popstate', () => setTimeout(() => finish('popstate'), 0), { once: true });
    setTimeout(() => finish('timeout'), 200);
  });
}

function q(w, sel) { const ov = w.document.getElementById('pwa-argyle-overlay'); return ov ? ov.querySelector(sel) : null; }
function txt(el) { return el ? el.textContent : null; }
function hiddenish(el) {
  if (!el) return null;
  return !!(el.hidden || el.hasAttribute('hidden') || (el.style && el.style.display === 'none'));
}

function lite(w) {
  const d = w.document;
  const ov = d.getElementById('pwa-argyle-overlay');
  return {
    overlays: d.querySelectorAll('#pwa-argyle-overlay').length,
    hidden: ov ? !!ov.hidden : null,
    isOpen: w.PwaArgyle.isOpen(),
    flag: ('pwaArgyle' in d.documentElement.dataset) ? d.documentElement.dataset.pwaArgyle : '__absent__',
    historyState: w.history.state === undefined ? '__undefined__' : w.history.state,
  };
}

function snap(w) {
  const d = w.document;
  const ov = d.getElementById('pwa-argyle-overlay');
  const input = q(w, 'form.pwa-argyle-bar input.pwa-argyle-input');
  const send = q(w, 'form.pwa-argyle-bar button.pwa-argyle-send');
  const status = q(w, '.pwa-argyle-status');
  const replyBody = q(w, '.pwa-argyle-reply .pwa-argyle-reply-body');
  const replyCard = q(w, '.pwa-argyle-reply .pwa-argyle-reply-card');
  const hint = q(w, '.pwa-argyle-hint');
  const toMessages = hint ? hint.querySelector('button.pwa-argyle-to-messages') : null;
  return {
    ...lite(w),
    inBody: !!(ov && ov.parentNode === d.body),
    overlayClass: ov ? ov.className : null,
    has: {
      dim: !!q(w, '.pwa-argyle-dim'), glow: !!q(w, '.pwa-argyle-glow'), ask: !!q(w, '.pwa-argyle-ask'),
      wave: !!q(w, '.pwa-argyle-ask .pwa-argyle-wave'), you: !!q(w, '.pwa-argyle-ask .pwa-argyle-you'),
      reply: !!q(w, '.pwa-argyle-reply'), replyBody: !!replyBody, replyCard: !!replyCard,
      status: !!status, bar: !!q(w, 'form.pwa-argyle-bar'), input: !!input, send: !!send, hint: !!hint,
    },
    waveBars: ov ? ov.querySelectorAll('.pwa-argyle-wave i').length : 0,
    you: txt(q(w, '.pwa-argyle-you')),
    replyHidden: hiddenish(q(w, '.pwa-argyle-reply')),
    replyBody: txt(replyBody),
    replyBodyElements: replyBody ? replyBody.querySelectorAll('*').length : null,
    replyCardHtml: replyCard ? replyCard.innerHTML : null,
    replyCardButtons: replyCard ? Array.from(replyCard.querySelectorAll('button')).map(b => b.textContent) : null,
    status: txt(status),
    statusRole: status ? status.getAttribute('role') : null,
    statusClass: status ? status.className : null,
    barHidden: hiddenish(q(w, 'form.pwa-argyle-bar')),
    inputFocused: !!input && d.activeElement === input,
    placeholder: input ? input.getAttribute('placeholder') : null,
    sendType: send ? send.getAttribute('type') : null,
    sendIsOrb: send ? send.classList.contains('argyle-orb') : null,
    sendHtml: send ? send.innerHTML : null,
    hint: txt(hint),
    hintFirstText: hint && hint.firstChild && hint.firstChild.nodeType === 3 ? hint.firstChild.textContent : null,
    toMessages: txt(toMessages),
    channelId: w.PwaArgyle.channelId() === undefined ? '__undefined__' : w.PwaArgyle.channelId(),
  };
}

function typeAndSubmit(w, text) {
  const input = q(w, 'form.pwa-argyle-bar input.pwa-argyle-input');
  const send = q(w, 'form.pwa-argyle-bar button.pwa-argyle-send');
  if (!input || !send) throw new Error('no form.pwa-argyle-bar input.pwa-argyle-input / button.pwa-argyle-send to type into');
  input.value = text;
  input.dispatchEvent(new w.Event('input', { bubbles: true }));
  send.click();          // the real submit path: an unprevented submit logs a jsdom "Not implemented"
}

function touch(w, el, type, y, x) {
  x = x === undefined ? 200 : x;
  const e = new w.Event(type, { bubbles: true, cancelable: true });
  const pt = [{ identifier: 0, target: el, clientX: x, pageX: x, screenX: x, clientY: y, pageY: y, screenY: y }];
  const list = type === 'touchend' ? [] : pt.slice();
  const withItem = a => Object.assign(a, { item: i => a[i] || null });
  Object.defineProperty(e, 'touches', { value: withItem(list) });
  Object.defineProperty(e, 'targetTouches', { value: withItem(list.slice()) });
  Object.defineProperty(e, 'changedTouches', { value: withItem(pt) });
  el.dispatchEvent(e);
}

function escape(w) {
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true, cancelable: true }));
}

const dmPosts = ctx => ctx.calls.filter(c => c.method === 'POST' && c.url === 'api/channels/dm');
const msgPosts = ctx => ctx.calls.filter(c => c.method === 'POST' && /\/messages/.test(c.url));
const API = ['open', 'close', 'isOpen', 'channelId', 'send', 'pull', 'onStream', 'setState', 'ensureChannel'];

const RUN = {
  async open_builds_chrome() {
    const { w, ctx } = fresh();
    const api = API.filter(k => typeof w.PwaArgyle[k] !== 'function');
    const lenBefore = w.history.length;
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    return { ...snap(w), missingApi: api, lenBefore, historyLength: w.history.length,
             fabCalls: ctx.fabCalls, dmPosts: dmPosts(ctx), calls: ctx.calls, errors: ctx.errors };
  },
  async send_posts_to_the_dm() {
    const { w, ctx } = fresh();
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    typeAndSubmit(w, ASK_TEXT);
    await flush();
    return { ...snap(w), calls: ctx.calls, errors: ctx.errors };
  },
  async pull_draws_the_reply_and_card() {
    const { w, ctx } = fresh();
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    typeAndSubmit(w, ASK_TEXT);
    await flush();
    const thinking = snap(w);
    ctx.messages = [
      { id: 'm3', sender_member_id: 'parent', body: ASK_TEXT },
      { id: 'm4', sender_member_id: 'argyle', body: REPLY_TEXT, card: { kind: 'ask', ask_id: 'a1' } },
    ];
    const before = ctx.calls.length;
    w.PwaArgyle.onStream('dm_argyle');
    await flush();
    const first = { ...snap(w), cards: ctx.cards.slice(), gets: ctx.calls.slice(before) };
    w.PwaArgyle.onStream('dm_argyle');
    await flush();
    const second = { ...snap(w), cards: ctx.cards.slice() };
    const beforeOther = ctx.calls.length;
    w.PwaArgyle.onStream('dm_someone_else');
    await flush();
    return { thinking, first, second, otherFetches: ctx.calls.slice(beforeOther), errors: ctx.errors };
  },
  async closed_overlay_ignores_events() {
    const { w, ctx } = fresh();
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    // 1. a drawn reply (with markup in it) must not survive a close.
    typeAndSubmit(w, 'first');
    await flush();
    ctx.messages = [
      { id: 'm3', sender_member_id: 'parent', body: 'first' },
      { id: 'm4', sender_member_id: 'argyle', body: 'Use <b>Tuesday</b> & go' },
    ];
    w.PwaArgyle.onStream('dm_argyle');
    await flush();
    const drawn = snap(w);
    let p = nextPop(w);
    w.PwaArgyle.close('test');
    await p;
    await flush();
    const n1 = ctx.calls.length;
    w.PwaArgyle.onStream('dm_argyle');
    await flush();
    const whileClosed1 = ctx.calls.slice(n1);
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    const reopen1 = snap(w);
    // 2. a thinking state must not survive a close either.
    typeAndSubmit(w, 'second');
    await flush();
    const thinking = snap(w);
    p = nextPop(w);
    w.PwaArgyle.close('test');
    await p;
    await flush();
    const n2 = ctx.calls.length;
    w.PwaArgyle.onStream('dm_argyle');
    await flush();
    const whileClosed2 = ctx.calls.slice(n2);
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    const reopen2 = snap(w);
    return { drawn, whileClosed1, reopen1, thinking, whileClosed2, reopen2, dmPosts: dmPosts(ctx),
             errors: ctx.errors };
  },
  async dismissals() {
    const { w, ctx } = fresh();
    w.history.pushState({ base: 1 }, '');
    const steps = {};
    const measure = async (name, act) => {
      const pops0 = ctx.pops, backs0 = ctx.backCalls, fab0 = ctx.fabCalls;
      const p = nextPop(w);
      act();
      const sync = lite(w);
      const waited = await p;
      await flush(60);         // room for a stray second walk to land
      steps[name] = { sync, ...lite(w), waited, pops: ctx.pops - pops0, backs: ctx.backCalls - backs0,
                      fab: ctx.fabCalls - fab0 };
    };
    const reopen = async () => { w.PwaArgyle.open({ mode: 'type' }); await flush(); return lite(w); };

    steps.open = await reopen();
    await measure('escape', () => escape(w));

    steps.reopen_ask = await reopen();
    const ask = q(w, '.pwa-argyle-ask');
    if (ask) ask.click();
    await flush();
    steps.ask_click = lite(w);

    const dim = q(w, '.pwa-argyle-dim');
    // The ghost-click guard ignores a dim tap within 400 ms of open() (the
    // compatibility click after the tap that opened it); a real dismissal
    // comes later, so wait past the window first.
    await new Promise(r => setTimeout(r, 450));
    await measure('dim', () => { if (dim) dim.click(); });

    steps.reopen_back = await reopen();
    await measure('back', () => w.history.back());

    steps.reopen_swipe = await reopen();
    const ask2 = q(w, '.pwa-argyle-ask');
    if (ask2) { touch(w, ask2, 'touchstart', 500); touch(w, ask2, 'touchend', 530); }
    await flush();
    steps.short_swipe = lite(w);
    await measure('swipe', () => { if (ask2) { touch(w, ask2, 'touchstart', 500); touch(w, ask2, 'touchend', 580); } });

    steps.overlays = w.document.querySelectorAll('#pwa-argyle-overlay').length;
    return { steps, errors: ctx.errors };
  },
  async refusal_shows_detail() {
    const { w, ctx } = fresh();
    ctx.dmStatus = 403;
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    const refused = snap(w);
    w.PwaArgyle.send('hello');
    await flush();
    const afterSend = { msgPosts: msgPosts(ctx) };
    const p = nextPop(w);
    escape(w);
    await p;
    await flush();
    return { refused, afterSend, closed: lite(w), dmPosts: dmPosts(ctx), errors: ctx.errors };
  },
  async send_ignores_empty() {
    const { w, ctx } = fresh();
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    typeAndSubmit(w, '');
    await flush();
    typeAndSubmit(w, '   ');
    await flush();
    w.PwaArgyle.send('');
    await flush();
    return { ...snap(w), msgPosts: msgPosts(ctx), errors: ctx.errors };
  },
  async voice_turn_never_draws_an_old_reply() {
    const { w, ctx } = fresh();
    // The thread as the server holds it once the voice turn posted the
    // transcript: an OLD Argyle reply (m2) and our words (m3), no reply yet.
    const HISTORY = [
      { id: 'm1', sender_member_id: 'parent', body: 'Is practice on?' },
      { id: 'm2', sender_member_id: 'argyle', body: 'Yes, 5pm.' },
      { id: 'm3', sender_member_id: 'parent', body: ASK_TEXT },
    ];
    ctx.messages = HISTORY.slice();
    w.PwaArgyle.open({ mode: 'talk' });
    await flush();
    const host = ctx.host;
    if (!host) throw new Error('open({mode:"talk"}) never called ChauffeurPhoneVoice.start({host})');
    host.status('Listening…', 'listening');
    host.transcript(ASK_TEXT);
    host.status('Thinking…', 'thinking');
    const before = ctx.calls.length;
    w.PwaArgyle.onStream('dm_argyle');          // the transcript's own SSE
    await flush();
    const transcriptStream = { ...snap(w), cards: ctx.cards.slice(), gets: ctx.calls.slice(before) };
    ctx.messages = HISTORY.concat([{ id: 'm4', sender_member_id: 'argyle', body: REPLY_TEXT }]);
    host.reply(REPLY_TEXT, { continue_conversation: false });
    await flush();
    w.PwaArgyle.onStream('dm_argyle');          // the reply's SSE
    await flush();
    const replied = { ...snap(w), cards: ctx.cards.slice() };
    return { starts: ctx.starts.length, transcriptStream, replied, errors: ctx.errors };
  },
  async host_labels_are_the_overlays_own() {
    const { w, ctx } = fresh();
    w.PwaArgyle.open({ mode: 'talk' });
    await flush();
    const host = ctx.host;
    if (!host) throw new Error('open({mode:"talk"}) never called ChauffeurPhoneVoice.start({host})');
    const said = [];
    const say = (label, name) => {
      host.status(label, name);
      const s = snap(w);
      said.push({ label, name, status: s.status, waveHidden: hiddenish(q(w, '.pwa-argyle-wave')) });
    };
    say('Listening — press Done when you finish.', 'listening');
    say('Recognizing speech…', 'thinking');
    say('Reply ready. Preparing speech…', 'thinking');
    say('Speaking', 'speaking');
    say('Microphone access was denied. Allow it in Settings or use text.', 'error');
    await flush();
    return { said, errors: ctx.errors };
  },
  async swipe_ignores_a_scrolling_reply() {
    const { w, ctx } = fresh();
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    typeAndSubmit(w, ASK_TEXT);
    await flush();
    ctx.messages = [
      { id: 'm3', sender_member_id: 'parent', body: ASK_TEXT },
      { id: 'm4', sender_member_id: 'argyle', body: REPLY_TEXT },
    ];
    w.PwaArgyle.onStream('dm_argyle');
    await flush();
    const body = q(w, '.pwa-argyle-ask .pwa-argyle-reply-body');
    const reply = q(w, '.pwa-argyle-ask .pwa-argyle-reply');
    const dim = q(w, '.pwa-argyle-dim');
    const ask = q(w, '.pwa-argyle-ask');
    // jsdom has no layout: make the reply's containers scrollers by every sign.
    const tops = {};
    const scroller = (el, key) => {
      tops[key] = 0;
      Object.defineProperty(el, 'scrollTop', { configurable: true, get: () => tops[key], set: v => { tops[key] = v; } });
      Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => 400 });
      Object.defineProperty(el, 'clientHeight', { configurable: true, get: () => 100 });
      el.style.overflowY = 'auto';
    };
    scroller(body, 'body'); scroller(reply, 'reply');
    const setTop = v => { tops.body = v; tops.reply = v; };
    const gesture = async (name, from, startTop, endTop, dy, dx) => {
      setTop(startTop);
      touch(w, from, 'touchstart', 500, 200);
      setTop(endTop);
      touch(w, from, 'touchend', 500 + dy, 200 + dx);
      await flush(250);
      const r = { name, ...lite(w) };
      if (!r.isOpen) { w.PwaArgyle.open({ mode: 'type' }); await flush(); }
      return r;
    };
    const steps = [];
    steps.push(await gesture('scrolled_reply', body, 40, 40, 100, 0));
    steps.push(await gesture('top_reply', body, 0, 0, 100, 0));
    steps.push(await gesture('scrolled_during', body, 0, 40, 100, 0));
    steps.push(await gesture('diagonal', ask, 0, 0, 80, 60));
    steps.push(await gesture('on_dim', dim, 0, 0, 100, 0));
    return { steps, errors: ctx.errors };
  },
  async dismiss_control_closes_and_returns_focus() {
    const { w, ctx } = fresh();
    const orb = w.document.getElementById('tab-argyle');
    orb.focus();
    w.PwaArgyle.open({ mode: 'type', keyboard: true, via: 'keyboard' });
    await flush();
    const btn = q(w, 'button.pwa-argyle-dismiss');
    const input = q(w, 'form.pwa-argyle-bar input.pwa-argyle-input');
    const info = {
      exists: !!btn, label: btn ? btn.getAttribute('aria-label') : null, type: btn ? btn.getAttribute('type') : null,
      before_input: !!(btn && input && (btn.compareDocumentPosition(input) & w.Node.DOCUMENT_POSITION_FOLLOWING)),
      hidden: btn ? hiddenish(btn) : null, text: btn ? btn.textContent : null,
      focusableByTab: btn ? btn.tabIndex >= 0 : null,
    };
    info.hint = txt(q(w, '.pwa-argyle-hint'));
    if (btn) btn.click();
    await flush(250);
    return { info, closed: lite(w), focusIsOrb: w.document.activeElement === orb, errors: ctx.errors };
  },
  async reply_refreshes_today_once() {
    const { w, ctx } = fresh();
    const calls = [];
    w.refreshTodaySurfaces = (quiet) => { calls.push(quiet === undefined ? '__undefined__' : quiet); };
    w.PwaArgyle.open({ mode: 'type' });
    await flush();
    typeAndSubmit(w, ASK_TEXT);
    await flush();
    const afterSend = calls.slice();
    ctx.messages = [
      { id: 'm3', sender_member_id: 'parent', body: ASK_TEXT },
      { id: 'm4', sender_member_id: 'argyle', body: REPLY_TEXT, card: { kind: 'ask', ask_id: 'a1' } },
    ];
    w.PwaArgyle.onStream('dm_argyle');
    await flush();
    const afterReply = calls.slice();
    w.PwaArgyle.onStream('dm_argyle');
    await flush();
    await w.PwaArgyle.pull();
    await flush();
    const btn = q(w, '.pwa-argyle-reply-card button');
    if (btn) btn.click();
    await flush(450);
    const afterRepulls = calls.slice();
    ctx.messages = ctx.messages.concat([{ id: 'm5', sender_member_id: 'argyle', body: 'And she can stay for dinner.' }]);
    w.PwaArgyle.onStream('dm_argyle');
    await flush();
    const afterNew = calls.slice();
    return { afterSend, afterReply, afterRepulls, afterNew, errors: ctx.errors };
  },
};

(async () => {
  const out = {};
  for (const name of cases) {
    try { out[name] = await RUN[name](); }
    catch (e) { out[name] = { error: String(e && e.message || e) }; }
  }
  current = null;
  for (const w of windows) { try { w.close(); } catch (e) { /* closing only stops timers */ } }
  process.stdout.write(JSON.stringify(out) + '\n', () => process.exit(0));
})();
"""

CASES = ['open_builds_chrome', 'send_posts_to_the_dm', 'pull_draws_the_reply_and_card',
         'closed_overlay_ignores_events', 'dismissals', 'refusal_shows_detail', 'send_ignores_empty',
         'voice_turn_never_draws_an_old_reply', 'host_labels_are_the_overlays_own',
         'swipe_ignores_a_scrolling_reply', 'dismiss_control_closes_and_returns_focus',
         'reply_refreshes_today_once']

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
        _RESULT['skip'] = 'node is not installed'
        return None
    have = subprocess.run([node, '-e', "require.resolve('jsdom')"], capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        _RESULT['skip'] = 'jsdom not resolvable'
        return None
    harness = os.path.join(SCRATCH, 'harness.js')
    with open(harness, 'w', encoding='utf-8') as f:
        f.write(HARNESS % {'ask': json.dumps(ASK_TEXT), 'reply': json.dumps(REPLY_TEXT)})
    cases = os.path.join(SCRATCH, 'cases.json')
    with open(cases, 'w', encoding='utf-8') as f:
        json.dump(CASES, f)
    proc = subprocess.run([node, harness, MODULE, cases], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0, f"the harness threw:\n{proc.stderr[-2000:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def _case(name):
    got = _run()
    if got is None:
        print(f"  skip  {name}: {_RESULT.get('skip')}")
        return None
    r = got[name]
    check('error' not in r, f"{name}: {r.get('error')}")
    check(not r.get('errors'), f"{name}: the page logged errors: {r.get('errors')}")
    return r


def _posts(calls, url):
    return [c for c in calls if c['method'] == 'POST' and c['url'] == url]


def scenario_open_builds_chrome():
    r = _case('open_builds_chrome')
    if r is None:
        return
    check(r['missingApi'] == [], f"window.PwaArgyle lacks {r['missingApi']}")
    check(r['overlays'] == 1 and r['inBody'], f"open() appends ONE #pwa-argyle-overlay to body: count={r['overlays']} inBody={r['inBody']}")
    check('pwa-argyle' in (r['overlayClass'] or '').split(), f"the overlay carries class pwa-argyle: {r['overlayClass']!r}")
    check(r['hidden'] is False and r['isOpen'] is True, f"open() shows it and isOpen() is true: hidden={r['hidden']} isOpen={r['isOpen']}")
    missing = [k for k, v in r['has'].items() if not v]
    check(not missing, f"the overlay is missing parts of the DOM contract: {missing}")
    check(r['waveBars'] == 6, f".pwa-argyle-wave holds six bars (<i>), got {r['waveBars']}")
    check((r['hint'] or '') == HINT + TO_MESSAGES, f"the hint reads {HINT + TO_MESSAGES!r}, got {r['hint']!r}")
    check(r['hintFirstText'] == HINT, f"the hint opens with the text {HINT!r} before the button, got {r['hintFirstText']!r}")
    check(r['toMessages'] == TO_MESSAGES, f"button.pwa-argyle-to-messages reads {TO_MESSAGES!r}, got {r['toMessages']!r}")
    check(r['placeholder'] == 'Or type…', f"the input's placeholder is 'Or type…', got {r['placeholder']!r}")
    check(r['sendType'] == 'submit' and r['sendIsOrb'], f"the send button is type=submit with class argyle-orb: {r['sendType']!r} orb={r['sendIsOrb']}")
    check('<svg' in (r['sendHtml'] or ''), f"the send button carries ArgyleOrb.glyph(): {r['sendHtml']!r}")
    check(r['statusRole'] == 'status', f".pwa-argyle-status has role=status, got {r['statusRole']!r}")
    check(r['replyHidden'] is True, "the reply stays hidden until a reply lands")
    check(r['inputFocused'], "type mode focuses input.pwa-argyle-input (document.activeElement)")
    check(r['flag'] == '1', f"html[data-pwa-argyle] is '1', got {r['flag']!r}")
    check(r['historyState'] == {'pwaOverlay': 'argyle'}, f"open() pushes {{pwaOverlay:'argyle'}}, history.state is {r['historyState']!r}")
    check(r['historyLength'] == r['lenBefore'] + 1, f"one history entry for the overlay: {r['lenBefore']} -> {r['historyLength']}")
    check(r['fabCalls'] >= 1, f"open() calls updateAgentFab() so the orb hides: {r['fabCalls']} calls")
    check(len(r['dmPosts']) == 1, f"open() ensures the DM with one POST api/channels/dm (apiBase-relative, never root-relative); calls: {r['calls']}")
    check(r['dmPosts'][0]['body'] == {'member_id': 'parent', 'other_member_id': 'argyle'},
          f"the DM ensure posts {{member_id: selectedMemberId, other_member_id: 'argyle'}}, got {r['dmPosts'][0]['body']!r}")
    check(r['channelId'] == 'dm_argyle', f"channelId() is the DM's id once ensured, got {r['channelId']!r}")


def scenario_send_posts_to_the_dm():
    r = _case('send_posts_to_the_dm')
    if r is None:
        return
    calls = r['calls']
    dm = [i for i, c in enumerate(calls) if c['method'] == 'POST' and c['url'] == 'api/channels/dm']
    msg = [i for i, c in enumerate(calls) if c['method'] == 'POST' and c['url'] == 'api/channels/dm_argyle/messages']
    check(dm and msg, f"submit POSTs api/channels/dm then api/channels/dm_argyle/messages; calls: {calls}")
    check(dm[0] < msg[0], f"the DM is ensured before the message posts; calls: {calls}")
    check(len(msg) == 1, f"one submit posts one message, got {len(msg)}: {calls}")
    check(calls[msg[0]]['body'] == {'sender_member_id': 'parent', 'body': ASK_TEXT},
          f"the message POST is {{sender_member_id: selectedMemberId, body}}, got {calls[msg[0]]['body']!r}")
    check((r['you'] or '').strip() == ASK_TEXT, f".pwa-argyle-you shows your words, got {r['you']!r}")
    check('Thinking' in (r['status'] or ''), f".pwa-argyle-status says Thinking…, got {r['status']!r}")


def scenario_pull_draws_the_reply_and_card():
    r = _case('pull_draws_the_reply_and_card')
    if r is None:
        return
    check('Thinking' in (r['thinking']['status'] or ''), f"thinking before the reply: {r['thinking']['status']!r}")
    f = r['first']
    gets = [c for c in f['gets'] if c['method'] == 'GET']
    check([c['url'] for c in gets] == ['api/channels/dm_argyle/messages?limit=20'],
          f"onStream('dm_argyle') makes one GET api/channels/dm_argyle/messages?limit=20, got {f['gets']}")
    check((f['replyBody'] or '').strip() == REPLY_TEXT, f".pwa-argyle-reply-body shows the reply, got {f['replyBody']!r}")
    check(f['replyHidden'] is False, "the reply bubble shows once a reply lands")
    check(f['cards'] == [{'kind': 'ask', 'ask_id': 'a1'}], f"renderCard called once with the reply's card, got {f['cards']}")
    check('card-stub' in (f['replyCardHtml'] or '') and f['replyCardButtons'] == ['Ask her'],
          f".pwa-argyle-reply-card holds renderCard's output, got {f['replyCardHtml']!r}")
    check((f['status'] or '').strip() == '', f"state idle: .pwa-argyle-status is empty, got {f['status']!r}")
    s = r['second']
    check(len(s['cards']) == 1, f"a second stream event does not redraw the same reply: renderCard called {len(s['cards'])} times")
    check((s['replyBody'] or '').strip() == REPLY_TEXT, f"the reply stays drawn, got {s['replyBody']!r}")
    check(r['otherFetches'] == [], f"onStream for another channel fetches nothing, got {r['otherFetches']}")


def scenario_closed_overlay_ignores_events():
    r = _case('closed_overlay_ignores_events')
    if r is None:
        return
    d = r['drawn']
    check((d['replyBody'] or '').strip() == 'Use <b>Tuesday</b> & go' and d['replyBodyElements'] == 0,
          f"the reply body is escaped text, never markup: text={d['replyBody']!r} elements={d['replyBodyElements']}")
    check(r['whileClosed1'] == [] and r['whileClosed2'] == [],
          f"a stream event while closed fetches nothing: {r['whileClosed1']} / {r['whileClosed2']}")
    a = r['reopen1']
    check(a['replyHidden'] is True and (a['replyBody'] or '').strip() == '',
          f"reopening shows no stale reply: hidden={a['replyHidden']} body={a['replyBody']!r}")
    check((a['you'] or '').strip() == '', f"reopening shows no stale words, got {a['you']!r}")
    check('Thinking' in (r['thinking']['status'] or ''), f"the second send was thinking: {r['thinking']['status']!r}")
    b = r['reopen2']
    check('Thinking' not in (b['status'] or ''), f"reopening after a close mid-thought shows no stale Thinking: {b['status']!r}")
    check((b['you'] or '').strip() == '', f"reopening clears .pwa-argyle-you, got {b['you']!r}")
    check(b['replyHidden'] is True, "reopening keeps the reply hidden")
    check(b['overlays'] == 1, f"reopening reuses the one overlay, got {b['overlays']}")
    check(len(r['dmPosts']) == 1, f"the DM is ensured once per member, not per open: {len(r['dmPosts'])} POSTs")


def _closed(step, name, base):
    check(step['hidden'] is True and step['isOpen'] is False, f"{name} closes the overlay: {step}")
    check(step['flag'] == '__absent__', f"{name} removes html[data-pwa-argyle]: {step['flag']!r}")
    st = step['historyState']
    check(st is None or st == base, f"after {name} history no longer sits on the overlay entry: {st!r}")


def scenario_dismissals():
    r = _case('dismissals')
    if r is None:
        return
    s = r['steps']
    base = {'base': 1}
    check(s['open']['isOpen'] and s['open']['historyState'] == {'pwaOverlay': 'argyle'}, f"opened over the base entry: {s['open']}")

    e = s['escape']
    check(e['sync']['hidden'] is True, f"Escape (keydown on document) hides the overlay at once: {e['sync']}")
    _closed(e, 'Escape', base)
    check(e['pops'] == 1 and e['backs'] == 1,
          f"an Escape close walks history back exactly once (its own entry): popstates={e['pops']} back()={e['backs']}")
    check(e['fab'] >= 1, f"close() calls updateAgentFab() so the orb returns: {e['fab']}")

    check(s['ask_click']['isOpen'] and s['ask_click']['hidden'] is False,
          f"a click inside .pwa-argyle-ask does not close (only the dim does): {s['ask_click']}")

    m = s['dim']
    check(m['sync']['hidden'] is True, f"a tap on .pwa-argyle-dim hides the overlay: {m['sync']}")
    _closed(m, 'the dim tap', base)
    check(m['pops'] == 1 and m['backs'] == 1, f"a dim close walks history back exactly once: popstates={m['pops']} back()={m['backs']}")

    b = s['back']
    check(b['waited'] == 'popstate', f"jsdom delivered the Back popstate: {b['waited']}")
    _closed(b, 'Back', base)
    check(b['historyState'] == base, f"Back lands on the entry under the overlay: {b['historyState']!r}")
    check(b['pops'] == 1 and b['backs'] == 1,
          f"a Back close never walks history again: popstates={b['pops']} back()={b['backs']} (1 and 1 = only the user's Back)")

    check(s['short_swipe']['isOpen'] and s['short_swipe']['hidden'] is False,
          f"a 30 px swipe down does not close: {s['short_swipe']}")
    w = s['swipe']
    check(w['sync']['hidden'] is True, f"a 80 px swipe down on .pwa-argyle-ask closes: {w['sync']}")
    _closed(w, 'the swipe', base)
    check(w['pops'] == 1 and w['backs'] == 1, f"a swipe close walks history back exactly once: popstates={w['pops']} back()={w['backs']}")
    check(s['overlays'] == 1, f"four opens build one overlay, got {s['overlays']}")


def scenario_refusal_shows_detail():
    r = _case('refusal_shows_detail')
    if r is None:
        return
    f = r['refused']
    check('Requires chat.agent' in (f['status'] or ''), f".pwa-argyle-status shows the server's detail, got {f['status']!r}")
    check('is-refused' in (f['statusClass'] or '').split(), f".pwa-argyle-status has class is-refused, got {f['statusClass']!r}")
    check(f['barHidden'] is True, "a refused DM hides form.pwa-argyle-bar")
    check(r['afterSend']['msgPosts'] == [], f"send() with no channel posts nothing, got {r['afterSend']['msgPosts']}")
    _closed(r['closed'], 'Escape on a refused overlay', None)


def scenario_send_ignores_empty():
    r = _case('send_ignores_empty')
    if r is None:
        return
    check(r['msgPosts'] == [], f"empty or blank text posts nothing, got {r['msgPosts']}")
    check((r['you'] or '').strip() == '', f".pwa-argyle-you stays empty, got {r['you']!r}")
    check('Thinking' not in (r['status'] or ''), f"no Thinking for an empty send, got {r['status']!r}")


def scenario_voice_turn_never_draws_an_old_reply():
    """A hold-to-talk turn has no POST of its own (the voice client posts the
    transcript), so the overlay never learns an anchor id. The transcript's
    own SSE must not draw the OLD Argyle reply above it ("Yes, 5pm."): the
    bubble waits for the reply this turn asked for."""
    r = _case('voice_turn_never_draws_an_old_reply')
    if r is None:
        return
    check(r['starts'] == 1, f"talk mode starts one voice turn, got {r['starts']}")
    t = r['transcriptStream']
    check(t['replyHidden'] is True and 'Yes, 5pm.' not in (t['replyBody'] or ''),
          f"the transcript's stream event drew an OLD reply: hidden={t['replyHidden']} body={t['replyBody']!r}")
    check((t['replyBody'] or '').strip() == '', f"no reply body before the turn's reply lands, got {t['replyBody']!r}")
    check('Thinking' in (t['status'] or ''), f"still thinking after the transcript's stream event, got {t['status']!r}")
    check(t['cards'] == [], f"renderCard is not called for an old reply, got {t['cards']}")
    check((t['you'] or '').strip() == ASK_TEXT, f".pwa-argyle-you shows the transcript, got {t['you']!r}")
    p = r['replied']
    check(p['replyHidden'] is False, "the turn's own reply shows the bubble")
    check((p['replyBody'] or '').strip() == REPLY_TEXT,
          f"the bubble shows this turn's reply {REPLY_TEXT!r}, got {p['replyBody']!r}")


VOICE_LABELS = [
    ('Listening — press Done when you finish.', 'listening', 'Listening…'),
    ('Recognizing speech…', 'thinking', 'Thinking…'),
    ('Reply ready. Preparing speech…', 'thinking', 'Thinking…'),
    ('Speaking', 'speaking', 'Speaking…'),
    ('Microphone access was denied. Allow it in Settings or use text.', 'error',
     'Microphone access was denied. Allow it in Settings or use text.'),
]


def scenario_host_labels_are_the_overlays_own():
    """The voice client speaks the thread's labels ('press Done' belongs to
    the Messages composer). The overlay draws its own word for each state;
    only an error keeps the voice client's words."""
    r = _case('host_labels_are_the_overlays_own')
    if r is None:
        return
    said = r['said']
    check(len(said) == len(VOICE_LABELS), f"every host.status call was recorded, got {said}")
    for got, (label, name, want) in zip(said, VOICE_LABELS):
        check(got['status'] == want,
              f"host.status({label!r}, {name!r}) draws {want!r} in .pwa-argyle-status, got {got['status']!r}")
    check(said[0]['waveHidden'] is False, f"'listening' shows the wave: {said[0]}")


def scenario_swipe_ignores_a_scrolling_reply():
    """A downward drag that starts inside a scrolled reply is the reply
    scrolling back up, not a dismissal. Close only when dy >= 60, |dy| > 2|dx|
    and no scroller under the finger was scrolled (at start or at the end)."""
    r = _case('swipe_ignores_a_scrolling_reply')
    if r is None:
        return
    s = {x['name']: x for x in r['steps']}
    check(s['scrolled_reply']['isOpen'], "a 100 px drag starting inside a reply scroller at scrollTop 40 must NOT close the overlay")
    check(not s['top_reply']['isOpen'], "the same drag with the reply scroller at scrollTop 0 closes the overlay")
    check(s['scrolled_during']['isOpen'], "a scroller at 0 at touchstart but at 40 at touchend (the drag scrolled it) must NOT close")
    check(s['diagonal']['isOpen'], "a diagonal drag (dy 80, dx 60) breaks |dy| > 2|dx| and must NOT close")
    check(not s['on_dim']['isOpen'], "a swipe down starting on .pwa-argyle-dim always closes")


def scenario_dismiss_control_closes_and_returns_focus():
    r = _case('dismiss_control_closes_and_returns_focus')
    if r is None:
        return
    i = r['info']
    check(i['exists'], "the overlay has no button.pwa-argyle-dismiss")
    check(i['label'] == 'Dismiss' and i['type'] == 'button', f"the dismiss control is type=button aria-label=Dismiss: {i}")
    check(i['hidden'] is False and i['focusableByTab'], f"the dismiss control is visible and in the tab order: {i}")
    check((i['text'] or '').strip() in ('\u00d7', 'x', 'X'), f"the dismiss control shows a multiplication sign: {i['text']!r}")
    check(i['before_input'], "the dismiss control precedes input.pwa-argyle-input in DOM order (tab order)")
    check((i['hint'] or '').startswith(HINT), f"the hint keeps 'Swipe down to dismiss', got {i['hint']!r}")
    c = r['closed']
    check(c['hidden'] is True and c['isOpen'] is False, f"activating the dismiss control closes the overlay: {c}")
    check(r['focusIsOrb'], "a keyboard-opened overlay closed by the dismiss control returns focus to #tab-argyle")


def scenario_reply_refreshes_today_once():
    """When a reply lands in the overlay, My Day and Plan must hear of it:
    window.refreshTodaySurfaces(true) once per reply message id."""
    r = _case('reply_refreshes_today_once')
    if r is None:
        return
    check(r['afterSend'] == [], f"sending alone refreshes nothing, got {r['afterSend']}")
    check(r['afterReply'] == [True], f"a landed reply calls refreshTodaySurfaces(true) exactly once, got {r['afterReply']}")
    check(r['afterRepulls'] == [True], f"a re-pull of the same reply (stream, pull(), card-tap re-pull) does not call again, got {r['afterRepulls']}")
    check(r['afterNew'] == [True, True], f"a NEW reply (new message id) calls once more, got {r['afterNew']}")


# --- the skin (source) -------------------------------------------------------

def _rules(css):
    """(selectors, body) for every innermost rule, inside @media or not."""
    out = []
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
        sel = re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S).strip()
        out.append(([s.strip() for s in sel.split(',')], m.group(2)))
    return out


def _media_blocks(css, needle):
    blocks = []
    for m in re.finditer(r'@media[^{]*' + needle + r'[^{]*\{', css):
        depth, i = 1, m.end()
        while i < len(css) and depth:
            depth += {'{': 1, '}': -1}.get(css[i], 0)
            i += 1
        blocks.append(css[m.end():i - 1])
    return blocks


def scenario_reduced_motion_rule():
    css = re.sub(r'/\*.*?\*/', '', read(STATIC, 'pwa_shell.css'), flags=re.S)
    blocks = _media_blocks(css, r'prefers-reduced-motion:\s*reduce')
    hit = [b for b in blocks if '.pwa-argyle-glow' in b and '.pwa-argyle-wave' in b and re.search(r'animation:\s*none', b)]
    check(hit, "static/pwa_shell.css has no @media (prefers-reduced-motion: reduce) block that stops "
               ".pwa-argyle-glow and .pwa-argyle-wave (animation: none)")
    rules = _rules(css)
    root = [body for sels, body in rules
            if any(re.search(r'(?:^|\s)\.pwa-argyle$', s) for s in sels) and re.search(r'z-index:\s*300\b', body)]
    check(root, "static/pwa_shell.css has no `.pwa-argyle { ... z-index: 300 }` rule "
                "(above the tab bar and #pwa-stack, below _pwaModal 400)")
    orb = [body for sels, body in rules
           if any('[data-audience="adult"]' in s and re.search(r'#tab-argyle$', s) for s in sels)
           and re.search(r'touch-action:\s*none', body)]
    check(orb, "static/pwa_shell.css has no `[data-audience=\"adult\"] #tab-argyle { touch-action: none }` rule "
               "(a held orb must not scroll or open the OS menu)")


def scenario_focus_ring_follows_the_pill():
    """The global 3 px accent :focus-visible rectangle must not sit inside the
    white pill: the input drops its own outline and the pill (.pwa-argyle-bar)
    carries the ring through :focus-within."""
    css = re.sub(r'/\*.*?\*/', '', read(STATIC, 'pwa_shell.css'), flags=re.S)
    rules = _rules(css)
    inp = [body for sels, body in rules
           if any(re.search(r'\.pwa-argyle-input:focus-visible$', s) for s in sels)
           and re.search(r'outline:\s*none\b', body)]
    check(inp, "static/pwa_shell.css has no `.pwa-argyle-input:focus-visible { outline: none }` rule "
               "(the accent rectangle sits inside the white pill)")
    bar = [body for sels, body in rules
           if any(re.search(r'\.pwa-argyle-bar:focus-within$', s) for s in sels)
           and re.search(r'\b(outline|box-shadow|border)(-[a-z]+)?\s*:', body)]
    check(bar, "static/pwa_shell.css has no `.pwa-argyle-bar:focus-within { ... }` rule that draws the ring "
               "(outline / box-shadow / border) on the pill")


SCENARIOS = [
    scenario_pure_is_pure,
    scenario_pure_tap_under_threshold,
    scenario_pure_hold_gesture,
    scenario_pure_cancel_is_silent,
    scenario_pure_newest_reply_after_mine,
    scenario_pure_no_reply_yet,
    scenario_pure_first_open_takes_latest,
    scenario_open_builds_chrome,
    scenario_send_posts_to_the_dm,
    scenario_pull_draws_the_reply_and_card,
    scenario_closed_overlay_ignores_events,
    scenario_dismissals,
    scenario_refusal_shows_detail,
    scenario_send_ignores_empty,
    scenario_reduced_motion_rule,
    scenario_voice_turn_never_draws_an_old_reply,
    scenario_host_labels_are_the_overlays_own,
    scenario_focus_ring_follows_the_pill,
    scenario_swipe_ignores_a_scrolling_reply,
    scenario_dismiss_control_closes_and_returns_focus,
    scenario_reply_refreshes_today_once,
]

if __name__ == "__main__":
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} pwa argyle overlay scenarios passed")
    sys.exit(1 if failed else 0)
