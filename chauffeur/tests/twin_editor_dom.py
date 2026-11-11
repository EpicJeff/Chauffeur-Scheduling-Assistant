"""A small DOM for running the house editor's ES modules under node.

Used by tests/test_twin_steps_js.py and tests/test_twin_checks_js.py (plan
docs/superpowers/plans/2026-11-10-house-guided-build-piece-4.md, Tasks 7-8).
It is enough DOM for modules that build their own controls: elements with
attributes, data-* through dataset, text, hidden, simple selectors (tag, #id,
.class, [attr], [attr="value"], descendant and child combinators, comma
lists), closest/matches, bubbling events with a real target, and
getElementById that finds any element carrying the id or, failing that, makes
one under document.body (the template would have it).

PRELUDE also wires the module loader the way tests/test_twin_drag_js.py does:
`three` resolves to the vendored r187 with a stub WebGLRenderer, OrbitControls
is a plain stub, the yard is an empty group, and every .js file loads as an ES
module. So a test can mount the real twin_view when a module needs one.

    from twin_editor_dom import PRELUDE, run_node
    out = run_node(PRELUDE + DRIVER, {'root': ROOT.as_posix(), ...})

Helpers the driver gets: file(path), Element, document, fire(node, type, extra),
click(node), shown(node), visibleButtons(text|RegExp), textOf(node), tick()
(runs one round of requestAnimationFrame callbacks), and `input` (the JSON).
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

PRELUDE = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const input = JSON.parse(readFileSync(process.argv[2]));
const file = p => pathToFileURL(input.root + '/' + p).href;
const data = source => 'data:text/javascript,' + encodeURIComponent(source);
const three = file('static/vendor/three-r187/three.module.js');
registerHooks({resolve(spec, ctx, next) {
  if (spec === 'three') return {url: data(`export * from '${three}'; export const WebGLRenderer = globalThis.Renderer;`), shortCircuit: true};
  if (spec === 'three/addons/controls/OrbitControls.js') return {url: data(`import {EventDispatcher,Vector3} from '${three}';
    export class OrbitControls extends EventDispatcher {
      constructor(camera){super();this.object=camera;this.target=new Vector3();this.enabled=true;}
      update(){this.object.lookAt(this.target);this.object.updateMatrixWorld();} dispose(){}
    }`), shortCircuit: true};
  if (spec.startsWith('three/addons/')) return {url: file('static/vendor/three-r187/addons/' + spec.slice(13)), shortCircuit: true};
  if (spec === './twin_yard.js') return {url: data(`import {Group} from '${three}'; export async function buildYard(){const group=new Group();group.name='test-yard';return {group};}`), shortCircuit: true};
  return next(spec, ctx);
}, load(url, ctx, next) {
  return url.startsWith('file:') && url.endsWith('.js') ? {...next(url, {...ctx, format:'module'}), format:'module'} : next(url, ctx);
}});

const ALL = [];
const camel = k => k.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const kebab = k => k.replace(/[A-Z]/g, c => '-' + c.toLowerCase());
function splitTop(text, sep) {
  const out = []; let depth = 0, quote = null, cur = '';
  for (const ch of text) {
    if (quote) { cur += ch; if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === '[' || ch === '(') depth++;
    if (ch === ']' || ch === ')') depth--;
    if (depth === 0 && sep(ch)) { out.push(cur); cur = ''; continue; }
    cur += ch;
  }
  out.push(cur); return out;
}
function compound(text) {
  const parts = []; let rest = text;
  const tag = rest.match(/^([a-zA-Z*][\w-]*)/);
  if (tag) { parts.push({tag: tag[1].toLowerCase()}); rest = rest.slice(tag[1].length); }
  while (rest) {
    let m;
    if ((m = rest.match(/^#([\w-]+)/))) parts.push({id: m[1]});
    else if ((m = rest.match(/^\.([\w-]+)/))) parts.push({cls: m[1]});
    else if ((m = rest.match(/^\[\s*([\w-]+)\s*(?:([~^$*]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\]\s]*)))?\s*\]/)))
      parts.push({attr: m[1], op: m[2], value: m[3] ?? m[4] ?? m[5]});
    else if ((m = rest.match(/^:not\((.*)\)$/))) parts.push({not: m[1]});
    else if ((m = rest.match(/^:(scope|first-child)/))) parts.push({pseudo: m[1]});
    else throw new Error('dom shim: unsupported selector ' + text);
    rest = rest.slice(m[0].length);
  }
  return parts;
}
function matchCompound(node, parts) {
  if (!node || node.nodeType !== 1) return false;
  for (const p of parts) {
    if (p.tag && p.tag !== '*' && node.localName !== p.tag) return false;
    if (p.id && node.id !== p.id) return false;
    if (p.cls && !node.className.split(/\s+/).includes(p.cls)) return false;
    if (p.not && node.matches(p.not)) return false;
    if (p.attr) {
      const v = node.getAttribute(p.attr);
      if (v === null) return false;
      if (p.op === '=' && v !== p.value) return false;
      if (p.op === '^=' && !v.startsWith(p.value)) return false;
      if (p.op === '$=' && !v.endsWith(p.value)) return false;
      if (p.op === '*=' && !v.includes(p.value)) return false;
      if (p.op === '~=' && !v.split(/\s+/).includes(p.value)) return false;
    }
  }
  return true;
}
function matchesSelector(node, selector) {
  return splitTop(selector, ch => ch === ',').some(one => {
    const tokens = splitTop(one.trim().replace(/\s*>\s*/g, ' > '), ch => /\s/.test(ch)).filter(Boolean);
    const steps = []; let combinator = ' ';
    for (const token of tokens) {
      if (token === '>') { combinator = '>'; continue; }
      steps.push({parts: compound(token), combinator}); combinator = ' ';
    }
    const walk = (n, i) => {
      if (!matchCompound(n, steps[i].parts)) return false;
      if (i === 0) return true;
      if (steps[i].combinator === '>') return walk(n.parentElement, i - 1);
      for (let a = n.parentElement; a; a = a.parentElement) if (walk(a, i - 1)) return true;
      return false;
    };
    return walk(node, steps.length - 1);
  });
}
class Text {
  constructor(text) { this.nodeType = 3; this.data = String(text); this.parentElement = null; }
  get textContent() { return this.data; } set textContent(v) { this.data = String(v); }
  remove() { this.parentElement?._detach(this); }
}
class Element {
  constructor(tag = 'div') {
    this.nodeType = 1; this.localName = String(tag).toLowerCase(); this.tagName = this.localName.toUpperCase();
    this.childNodes = []; this.parentElement = null; this.style = {}; this.dataset = {}; this._attrs = {};
    this._listeners = {}; this.hidden = false; this.disabled = false; this.value = ''; this.checked = false;
    this.clientWidth = 1440; this.clientHeight = 900; this.offsetWidth = 300; this.offsetHeight = 200;
    this.scrollTop = 0; this.open = false;
    const self = this;
    this.classList = {
      add: (...c) => { const s = new Set(self.className.split(/\s+/).filter(Boolean)); c.forEach(x => s.add(x)); self.className = [...s].join(' '); },
      remove: (...c) => { self.className = self.className.split(/\s+/).filter(x => x && !c.includes(x)).join(' '); },
      toggle: (c, on) => { const has = self.classList.contains(c); const want = on === undefined ? !has : !!on; want ? self.classList.add(c) : self.classList.remove(c); return want; },
      contains: c => self.className.split(/\s+/).includes(c),
    };
    ALL.push(this);
  }
  get children() { return this.childNodes.filter(n => n.nodeType === 1); }
  get firstElementChild() { return this.children[0] || null; }
  get lastElementChild() { return this.children.at(-1) || null; }
  get childElementCount() { return this.children.length; }
  get id() { return this._attrs.id || ''; } set id(v) { this._attrs.id = String(v); }
  get className() { return this._attrs.class || ''; } set className(v) { this._attrs.class = String(v); }
  get textContent() { return this.childNodes.map(n => n.textContent).join(''); }
  set textContent(v) { this.replaceChildren(); if (v !== null && v !== undefined && String(v) !== '') this.append(String(v)); }
  get innerText() { return this.textContent; } set innerText(v) { this.textContent = v; }
  get innerHTML() { return this.textContent; } set innerHTML(v) { this.textContent = String(v).replace(/<[^>]*>/g, ''); }
  get isConnected() { let n = this; while (n.parentElement) n = n.parentElement; return n === globalThis.document; }
  get ownerDocument() { return globalThis.document; }
  get type() { return this._attrs.type || (this.localName === 'button' ? 'submit' : ''); } set type(v) { this._attrs.type = String(v); }
  get name() { return this._attrs.name || ''; } set name(v) { this._attrs.name = String(v); }
  get title() { return this._attrs.title || ''; } set title(v) { this._attrs.title = String(v); }
  get href() { return this._attrs.href || ''; } set href(v) { this._attrs.href = String(v); }
  setAttribute(k, v) {
    v = String(v);
    if (k.startsWith('data-')) this.dataset[camel(k.slice(5))] = v;
    else if (k === 'hidden') this.hidden = true;
    else if (k === 'disabled') this.disabled = true;
    else this._attrs[k] = v;
  }
  getAttribute(k) {
    if (k.startsWith('data-')) { const v = this.dataset[camel(k.slice(5))]; return v === undefined ? null : String(v); }
    if (k === 'hidden') return this.hidden ? '' : null;
    if (k === 'disabled') return this.disabled ? '' : null;
    return k in this._attrs ? this._attrs[k] : null;
  }
  hasAttribute(k) { return this.getAttribute(k) !== null; }
  removeAttribute(k) {
    if (k.startsWith('data-')) delete this.dataset[camel(k.slice(5))];
    else if (k === 'hidden') this.hidden = false;
    else if (k === 'disabled') this.disabled = false;
    else delete this._attrs[k];
  }
  toggleAttribute(k, force) {
    const want = force === undefined ? !this.hasAttribute(k) : !!force;
    want ? this.setAttribute(k, '') : this.removeAttribute(k); return want;
  }
  _adopt(n) {
    if (typeof n === 'string' || typeof n === 'number') n = new Text(n);
    n.parentElement?._detach(n); n.parentElement = this; return n;
  }
  _detach(n) { this.childNodes = this.childNodes.filter(c => c !== n); n.parentElement = null; }
  append(...nodes) { for (const n of nodes) this.childNodes.push(this._adopt(n)); }
  appendChild(n) { this.append(n); return n; }
  prepend(...nodes) { this.childNodes.unshift(...nodes.map(n => this._adopt(n))); }
  insertBefore(n, ref) {
    if (!ref) return this.appendChild(n);
    const node = this._adopt(n); this.childNodes.splice(this.childNodes.indexOf(ref), 0, node); return node;
  }
  before(...nodes) { const p = this.parentElement; if (p) for (const n of nodes) p.insertBefore(n, this); }
  after(...nodes) {
    const p = this.parentElement; if (!p) return;
    let ref = p.childNodes[p.childNodes.indexOf(this) + 1] || null;
    for (const n of nodes) p.insertBefore(n, ref);
  }
  remove() { this.parentElement?._detach(this); }
  replaceChildren(...nodes) { for (const n of [...this.childNodes]) this._detach(n); this.append(...nodes); }
  replaceWith(...nodes) { this.before(...nodes); this.remove(); }
  contains(n) { for (let a = n; a; a = a.parentElement) if (a === this) return true; return false; }
  descendants() { return this.children.flatMap(c => [c, ...c.descendants()]); }
  matches(sel) { return matchesSelector(this, sel); }
  closest(sel) { for (let a = this; a && a.nodeType === 1; a = a.parentElement) if (a.matches(sel)) return a; return null; }
  querySelectorAll(sel) { return this.descendants().filter(n => n.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getElementsByTagName(tag) { return this.querySelectorAll(tag); }
  addEventListener(type, fn, options) {
    const signal = typeof options === 'object' ? options?.signal : null;
    if (signal?.aborted || !fn) return;
    const entry = {fn, once: typeof options === 'object' && !!options?.once};
    (this._listeners[type] ||= []).push(entry);
    signal?.addEventListener('abort', () => { this._listeners[type] = (this._listeners[type] || []).filter(e => e !== entry); }, {once: true});
  }
  removeEventListener(type, fn) { this._listeners[type] = (this._listeners[type] || []).filter(e => e.fn !== fn); }
  dispatchEvent(event) {
    const ev = event.__shim ? event : makeEvent(event.type, {bubbles: event.bubbles, key: event.key,
      clientX: event.clientX, clientY: event.clientY, pointerId: event.pointerId, button: event.button, detail: event.detail});
    if (!ev.target) ev.target = this;
    for (let n = this; n && !ev._stopped; n = ev.bubbles ? n.parentElement : null) {
      ev.currentTarget = n;
      for (const entry of [...(n._listeners[ev.type] || [])]) {
        if (entry.once) n.removeEventListener(ev.type, entry.fn);
        const result = typeof entry.fn === 'function' ? entry.fn.call(n, ev) : entry.fn.handleEvent(ev);
        if (result && typeof result.then === 'function') ev._promises.push(result);
      }
      if (!ev.bubbles) break;
    }
    return !ev.defaultPrevented;
  }
  click() { if (!this.disabled) fire(this, 'click'); }
  focus() { globalThis.document.activeElement = this; }
  blur() { if (globalThis.document.activeElement === this) globalThis.document.activeElement = null; }
  scrollIntoView() {} scrollTo() {}
  getBoundingClientRect() { return {left: 0, top: 0, right: 1440, bottom: 900, width: 1440, height: 900, x: 0, y: 0}; }
  getClientRects() { return shown(this) ? [this.getBoundingClientRect()] : []; }
  getContext() { return {getExtension: () => null}; }
  hasPointerCapture() { return false; } setPointerCapture() {} releasePointerCapture() {}
  showModal() { this.open = true; } show() { this.open = true; } close() { this.open = false; }
  animate() { return {finished: Promise.resolve(), cancel() {}}; }
}
function makeEvent(type, extra = {}) {
  return {__shim: true, type, bubbles: true, target: null, currentTarget: null, defaultPrevented: false,
    _stopped: false, _promises: [], preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this._stopped = true; }, stopImmediatePropagation() { this._stopped = true; }, ...extra};
}
// Fire an event on a node; resolves after any promises its handlers returned.
async function fire(node, type, extra = {}) {
  const ev = makeEvent(type, extra); node.dispatchEvent(ev);
  await Promise.allSettled(ev._promises);
  for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 0));
  return ev;
}
const click = node => fire(node, 'click');
class Document extends Element {
  constructor() {
    super('#document'); this.nodeType = 9;
    this.documentElement = new Element('html'); this.head = new Element('head'); this.body = new Element('body');
    this.childNodes = [this.documentElement]; this.documentElement.parentElement = this;
    this.documentElement.append(this.head, this.body); this.activeElement = null;
  }
  get isConnected() { return true; }
  createElement(tag) { return new Element(tag); }
  createElementNS(_, tag) { return new Element(tag); }
  createTextNode(text) { return new Text(text); }
  createDocumentFragment() { return new Element('#fragment'); }
  getElementById(id) {
    const found = ALL.find(n => n.id === id && n.isConnected) || ALL.find(n => n.id === id);
    if (found) return found;
    const made = new Element(); made.id = id; this.body.append(made); return made;
  }
}
// Visible: attached to the document, and neither it nor an ancestor is hidden.
function shown(node) {
  if (!node?.isConnected) return false;
  for (let n = node; n && n.nodeType === 1; n = n.parentElement)
    if (n.hidden || n.style?.display === 'none') return false;
  return true;
}
const textOf = node => (node?.textContent || '').replace(/\s+/g, ' ').trim();
function visibleButtons(text, within = globalThis.document) {
  const ok = t => text instanceof RegExp ? text.test(t) : t === text;
  return within.querySelectorAll('button').filter(b => shown(b) && ok(textOf(b)));
}
globalThis.document = new Document();
globalThis.window = new Element('window');
Object.assign(globalThis.window, {chfBase: '/', devicePixelRatio: 1, innerWidth: 1440, innerHeight: 900,
  promptConfirm: async () => true, promptInput: async () => null, promptChoice: async () => null,
  showGlobalAlert: () => {}});
globalThis.location = {search: '?test=1&tier=low', pathname: '/house/editor', href: 'http://test/house/editor?test=1&tier=low'};
globalThis.getComputedStyle = () => ({getPropertyValue: () => ''});
globalThis.CustomEvent = class extends Event {constructor(name, opts) {super(name); this.detail = opts?.detail;}};
globalThis.ResizeObserver = class {observe() {} disconnect() {}};
globalThis.HTMLElement = Element;
let rafId = 0; const frames = new Map();
globalThis.requestAnimationFrame = fn => { frames.set(++rafId, fn); return rafId; };
globalThis.cancelAnimationFrame = id => frames.delete(id);
const tick = () => { const batch = [...frames]; frames.clear(); for (const [, fn] of batch) fn(performance.now()); };
globalThis.Renderer = class {
  constructor() { this.domElement = new Element('canvas'); this.shadowMap = {}; this.info = {render: {calls: 0, triangles: 0}, reset() {}}; }
  setPixelRatio() {} getContext() { return {getExtension: () => null}; } setSize() {} setAnimationLoop() {}
  render(scene) { scene.updateMatrixWorld(true); } dispose() {} forceContextLoss() {}
};
// Each named test runs alone; the driver reports N/M and exits non-zero on any failure.
const results = [];
async function test(name, fn) {
  try { await fn(); results.push([name, null]); console.log('  ok  ', name); }
  catch (error) { results.push([name, error]); console.log('  FAIL', name, String(error?.message || error).replace(/\s+/g, ' ').slice(0, 900)); }
}
function finish() {
  const failed = results.filter(([, e]) => e).length;
  console.log(`${results.length - failed}/${results.length} passed`);
  process.exit(failed ? 1 : 0);
}
"""


def run_node(driver, payload, timeout=120):
    """Run a node driver with `payload` as its JSON input. Returns (exit code, output)."""
    node = shutil.which('node')
    if not node:
        return None, 'SKIP node is unavailable'
    paths = []
    try:
        for suffix, content in (('.mjs', driver), ('.json', json.dumps(payload))):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix,
                                             prefix='chauffeur_editor_dom_', delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run([node, str(paths[0]), str(paths[1])], capture_output=True,
                                text=True, encoding='utf-8', timeout=timeout)
        return result.returncode, result.stdout + result.stderr
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
