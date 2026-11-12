"""A fake DOM and a live-layer rig for the 3D house's node tests (plan
docs/superpowers/plans/2026-11-11-twin-device-controls.md, Tasks 1 and 3).

Imported by tests/test_twin_kinds_js.py and tests/test_twin_ring_js.py; never run
on its own. `PRELUDE` is JavaScript that a driver puts first: it registers the
`three` resolver, builds the fake DOM, and defines the rig. `run(driver, config)`
writes the driver beside a JSON config and runs it under node.

The fake DOM is small but honest about what browsers do:
- events run capture, target and bubble phases through element -> document ->
  window, so delegated listeners (on the ring root, on document, on window) work;
  a listener that throws is recorded in `domErrors`, never thrown at the sender;
  a disabled button, input, select or textarea gets no mouse or pointer event;
- `data-*` attributes and `dataset` are the same thing; `class` is `className`
  and `classList`; `disabled` and `hidden` reflect both ways;
- `document.createElement` / `createElementNS` / `createTextNode` /
  `createDocumentFragment` build nodes; `innerHTML = ''` clears, and any other
  `innerHTML` throws (build nodes, the fake does not parse markup);
- querySelector(All), closest and matches understand tag, *, #id, .class,
  [attr], [attr="value"], :not(...), and the descendant and child combinators;
- the canvas and its host are 1400 x 1000 at the page origin; other nodes have
  a zero rect unless a test sets `node._rect`;
- a 2D context records what it draws (`canvas.__log`), in canvas pixels with
  the current transform applied, so two ways of drawing the same picture match.
PointerEvent, MouseEvent and KeyboardEvent are minimal Event subclasses.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const config = JSON.parse(readFileSync(process.argv[2]));
const {root} = config;
const file = p => pathToFileURL(root + '/' + p).href;
registerHooks({resolve(spec, ctx, next) {
  if (spec === 'three') return {url: file('static/vendor/three-r187/three.module.js'), shortCircuit: true};
  if (spec.startsWith('three/addons/')) return {url: file('static/vendor/three-r187/addons/' + spec.slice(13)), shortCircuit: true};
  return next(spec, ctx);
}, load(url, ctx, next) {
  return url.startsWith('file:') && url.endsWith('.js') ? {...next(url, {...ctx, format:'module'}), format:'module'} : next(url, ctx);
}});

const escaped = [], domErrors = [];
process.on('uncaughtException', error => {escaped.push(String(error && error.stack || error)); process.exitCode=1; console.error(error);});
process.on('unhandledRejection', error => {escaped.push(String(error && error.stack || error)); process.exitCode=1; console.error(error);});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

// ------------------------------------------------------------------ fake DOM
const camel = s => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const kebab = s => s.replace(/[A-Z]/g, c => '-' + c.toLowerCase());
class FakeTarget {
  addEventListener(type, fn, options) {
    if (!fn) return;
    const capture = typeof options === 'boolean' ? options : !!(options && options.capture);
    const signal = options && typeof options === 'object' ? options.signal : null;
    if (signal && signal.aborted) return;
    const list = this.__listeners ||= [];
    if (list.some(l => l.type === type && l.fn === fn && l.capture === capture)) return;
    list.push({type, fn, capture, once: !!(options && options.once)});
    if (signal) signal.addEventListener('abort', () => this.removeEventListener(type, fn, {capture}), {once: true});
  }
  removeEventListener(type, fn, options) {
    const capture = typeof options === 'boolean' ? options : !!(options && options.capture);
    this.__listeners = (this.__listeners || []).filter(l => !(l.type === type && l.fn === fn && l.capture === capture));
  }
  dispatchEvent(event) { return dispatch(this, event); }
  __parent() { return null; }
}
// Browsers never deliver mouse or pointer clicks to a disabled form control.
const FORM = new Set(['button', 'input', 'select', 'textarea']);
function dispatch(target, event) {
  if (event instanceof MouseEvent && target.nodeType === 1 && FORM.has(target.localName) && target.disabled) return true;
  const path = [];
  for (let n = target.__parent(); n; n = n.__parent()) path.push(n);
  let stopped = false, immediate = false, prevented = false;
  const own = (k, v) => Object.defineProperty(event, k, {value: v, configurable: true, writable: true});
  own('target', target); own('srcElement', target);
  own('stopPropagation', () => { stopped = true; });
  own('stopImmediatePropagation', () => { stopped = true; immediate = true; });
  own('preventDefault', () => { if (event.cancelable) prevented = true; });
  own('composedPath', () => [target, ...path]);
  Object.defineProperty(event, 'defaultPrevented', {get: () => prevented, configurable: true});
  const fire = (node, phase) => {
    own('currentTarget', node); own('eventPhase', phase);
    for (const l of [...(node.__listeners || [])]) {
      if (immediate) break;
      if (l.type !== event.type || phase === 1 && !l.capture || phase === 3 && l.capture) continue;
      if (!(node.__listeners || []).includes(l)) continue;
      if (l.once) node.removeEventListener(l.type, l.fn, {capture: l.capture});
      try { typeof l.fn === 'function' ? l.fn.call(node, event) : l.fn.handleEvent(event); }
      catch (error) { domErrors.push(String(error && error.stack || error)); }
    }
  };
  for (const n of [...path].reverse()) { if (stopped) break; fire(n, 1); }
  if (!stopped) fire(target, 2);
  if (event.bubbles) for (const n of path) { if (stopped) break; fire(n, 3); }
  own('currentTarget', null);
  return !prevented;
}
class MouseEvent extends Event {
  constructor(type, init = {}) {
    super(type, init);
    for (const [k, v] of Object.entries({clientX: 0, clientY: 0, screenX: 0, screenY: 0, button: 0, buttons: 0,
      shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, ...init}))
      if (!['bubbles', 'cancelable', 'composed'].includes(k)) Object.defineProperty(this, k, {value: v, configurable: true, writable: true});
    Object.defineProperty(this, 'offsetX', {value: this.clientX, configurable: true, writable: true});
    Object.defineProperty(this, 'offsetY', {value: this.clientY, configurable: true, writable: true});
  }
}
class PointerEvent extends MouseEvent {
  constructor(type, init = {}) { super(type, {pointerId: 1, pointerType: 'mouse', isPrimary: true, width: 1, height: 1, pressure: .5, ...init}); }
}
class KeyboardEvent extends Event {
  constructor(type, init = {}) {
    super(type, init);
    for (const [k, v] of Object.entries({key: '', code: '', shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, repeat: false, ...init}))
      if (!['bubbles', 'cancelable', 'composed'].includes(k)) Object.defineProperty(this, k, {value: v, configurable: true, writable: true});
  }
}
globalThis.MouseEvent = MouseEvent; globalThis.PointerEvent = PointerEvent; globalThis.KeyboardEvent = KeyboardEvent;
globalThis.FocusEvent ||= class FocusEvent extends Event {};
globalThis.InputEvent ||= class InputEvent extends Event {};

class ClassList {
  constructor(node) { this.node = node; }
  get items() { return String(this.node.className || '').split(/\s+/).filter(Boolean); }
  add(...names) { this.node.className = [...new Set([...this.items, ...names])].join(' '); }
  remove(...names) { this.node.className = this.items.filter(n => !names.includes(n)).join(' '); }
  toggle(name, force) { const on = force === undefined ? !this.contains(name) : !!force; on ? this.add(name) : this.remove(name); return on; }
  contains(name) { return this.items.includes(name); }
  replace(a, b) { if (!this.contains(a)) return false; this.remove(a); this.add(b); return true; }
  get length() { return this.items.length; }
  get value() { return this.items.join(' '); }
  [Symbol.iterator]() { return this.items[Symbol.iterator](); }
}
class FakeStyle {
  setProperty(k, v) { this[k] = String(v); }
  getPropertyValue(k) { return this[k] ?? ''; }
  removeProperty(k) { const v = this[k]; delete this[k]; return v ?? ''; }
}
class TextNode extends FakeTarget {
  constructor(text) { super(); this.nodeType = 3; this.nodeName = '#text'; this.data = String(text); this.parentNode = null; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
  get nodeValue() { return this.data; }
  remove() { this.parentNode?.removeChild(this); }
  __parent() { return this.parentNode; }
}
const BOOLEAN = new Set(['disabled', 'hidden', 'checked', 'selected', 'readonly']);
const ZERO = {left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0};
class El extends FakeTarget {
  constructor(tag, ns) {
    super();
    this.nodeType = tag === '#fragment' ? 11 : 1;
    this.localName = tag.includes(':') ? tag : (ns && ns !== XHTML ? tag : tag.toLowerCase());
    this.tagName = this.nodeName = ns && ns !== XHTML ? tag : tag.toUpperCase();
    this.namespaceURI = ns || XHTML;
    this.childNodes = []; this.parentNode = null; this.attrs = {}; this.dataset = {};
    this.style = new FakeStyle(); this.className = ''; this.id = ''; this.scrollTop = 0; this.scrollLeft = 0;
    this.classList = new ClassList(this);
    for (const name of BOOLEAN) this[name] = false;
  }
  __parent() { return this.parentNode || (this === document.documentElement ? document : null); }
  get ownerDocument() { return document; }
  get children() { return this.childNodes.filter(n => n.nodeType === 1); }
  get childElementCount() { return this.children.length; }
  get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes.at(-1) || null; }
  get firstElementChild() { return this.children[0] || null; }
  get lastElementChild() { return this.children.at(-1) || null; }
  get nextSibling() { const s = this.parentNode?.childNodes; return s ? s[s.indexOf(this) + 1] || null : null; }
  get previousSibling() { const s = this.parentNode?.childNodes; return s ? s[s.indexOf(this) - 1] || null : null; }
  get nextElementSibling() { const s = this.parentNode?.children; return s ? s[s.indexOf(this) + 1] || null : null; }
  get previousElementSibling() { const s = this.parentNode?.children; return s ? s[s.indexOf(this) - 1] || null : null; }
  get isConnected() { for (let n = this; n; n = n.parentNode) if (n === document.documentElement) return true; return false; }
  get textContent() { return this.childNodes.map(n => n.textContent).join(''); }
  set textContent(v) { this.replaceChildren(...(v === '' || v === null || v === undefined ? [] : [new TextNode(v)])); }
  get innerText() { return this.textContent; }
  set innerText(v) { this.textContent = v; }
  get innerHTML() { return this.textContent; }
  set innerHTML(v) {
    if (v === '' || v === null || v === undefined) { this.replaceChildren(); return; }
    throw new Error('fake DOM: innerHTML is not parsed here; build the nodes with createElement');
  }
  get offsetWidth() { return this.getBoundingClientRect().width; }
  get offsetHeight() { return this.getBoundingClientRect().height; }
  get clientWidth() { return this.getBoundingClientRect().width; }
  get clientHeight() { return this.getBoundingClientRect().height; }
  __adopt(nodes) {
    const out = [];
    for (const node of nodes) {
      if (node === null || node === undefined) continue;
      if (typeof node !== 'object') { out.push(new TextNode(node)); continue; }
      if (node.nodeType === 11) { out.push(...node.childNodes); node.childNodes = []; continue; }
      out.push(node);
    }
    for (const node of out) { node.parentNode?.removeChild(node); node.parentNode = this; }
    return out;
  }
  append(...nodes) { this.childNodes.push(...this.__adopt(nodes)); }
  prepend(...nodes) { this.childNodes.unshift(...this.__adopt(nodes)); }
  appendChild(node) { this.append(node); return node; }
  insertBefore(node, ref) {
    if (!ref) return this.appendChild(node);
    const adopted = this.__adopt([node]);
    this.childNodes.splice(this.childNodes.indexOf(ref), 0, ...adopted);
    return node;
  }
  removeChild(node) { this.childNodes = this.childNodes.filter(n => n !== node); node.parentNode = null; return node; }
  replaceChild(node, old) { this.insertBefore(node, old); this.removeChild(old); return old; }
  replaceChildren(...nodes) { for (const n of this.childNodes) n.parentNode = null; this.childNodes = []; this.append(...nodes); }
  replaceWith(...nodes) { const p = this.parentNode; if (!p) return; const at = p.childNodes.indexOf(this); const adopted = p.__adopt(nodes); p.childNodes.splice(p.childNodes.indexOf(this), 1, ...adopted); this.parentNode = null; void at; }
  before(...nodes) { const p = this.parentNode; if (!p) return; const adopted = p.__adopt(nodes); p.childNodes.splice(p.childNodes.indexOf(this), 0, ...adopted); }
  after(...nodes) { const p = this.parentNode; if (!p) return; const adopted = p.__adopt(nodes); p.childNodes.splice(p.childNodes.indexOf(this) + 1, 0, ...adopted); }
  remove() { this.parentNode?.removeChild(this); }
  cloneNode() { throw new Error('fake DOM: cloneNode is not supported'); }
  contains(node) { for (let n = node; n; n = n.parentNode) if (n === this) return true; return false; }
  setAttribute(name, value) {
    name = String(name); value = String(value);
    if (name === 'class') this.className = value;
    else if (name === 'id') this.id = value;
    else if (name.startsWith('data-')) this.dataset[camel(name.slice(5))] = value;
    else if (name === 'style') { for (const part of value.split(';')) { const [k, ...v] = part.split(':'); if (k.trim()) this.style[camel(k.trim())] = v.join(':').trim(); } }
    else if (BOOLEAN.has(name)) this[name] = true;
    else this.attrs[name] = value;
  }
  getAttribute(name) {
    name = String(name);
    if (name === 'class') return this.className || null;
    if (name === 'id') return this.id || null;
    if (name.startsWith('data-')) { const v = this.dataset[camel(name.slice(5))]; return v === undefined ? null : String(v); }
    if (BOOLEAN.has(name)) return this[name] ? '' : null;
    return this.attrs[name] ?? null;
  }
  hasAttribute(name) { return this.getAttribute(name) !== null; }
  removeAttribute(name) {
    if (name === 'class') this.className = '';
    else if (name === 'id') this.id = '';
    else if (name.startsWith('data-')) delete this.dataset[camel(name.slice(5))];
    else if (BOOLEAN.has(name)) this[name] = false;
    else delete this.attrs[name];
  }
  toggleAttribute(name, force) { const on = force === undefined ? !this.hasAttribute(name) : !!force; on ? this.setAttribute(name, '') : this.removeAttribute(name); return on; }
  setAttributeNS(_ns, name, value) { this.setAttribute(name, value); }
  getAttributeNames() {
    return [...(this.className ? ['class'] : []), ...(this.id ? ['id'] : []), ...Object.keys(this.dataset).map(k => 'data-' + kebab(k)),
      ...[...BOOLEAN].filter(k => this[k]), ...Object.keys(this.attrs)];
  }
  querySelectorAll(selector) { const out = []; const walk = n => { for (const c of n.children) { if (matches(c, selector, this)) out.push(c); walk(c); } }; walk(this); return out; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  getElementsByTagName(tag) { return this.querySelectorAll(tag); }
  getElementsByClassName(name) { return this.querySelectorAll('.' + name); }
  matches(selector) { return matches(this, selector, null); }
  closest(selector) { for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (matches(n, selector, null)) return n; return null; }
  getBoundingClientRect() {
    const r = this._rect || (this.localName === 'canvas' || this.__host ? {left: 0, top: 0, width: 1400, height: 1000} : null);
    if (!r) return {...ZERO};
    return {left: r.left, top: r.top, width: r.width, height: r.height, right: r.left + r.width, bottom: r.top + r.height, x: r.left, y: r.top};
  }
  getClientRects() { return [this.getBoundingClientRect()]; }
  focus() { document.activeElement = this; }
  blur() { if (document.activeElement === this) document.activeElement = document.body; }
  click() { this.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true})); }
  setPointerCapture(id) { this.__captured = id; }
  releasePointerCapture() { this.__captured = undefined; }
  hasPointerCapture(id) { return this.__captured === id; }
  scrollIntoView() {}
  animate() { return {finished: Promise.resolve(), cancel() {}, finish() {}, addEventListener() {}}; }
  getContext() { if (!this.__ctx) { this.__log = []; this.__ctx = recorder(this.__log); } return this.__ctx; }
  getBBox() { return {x: 0, y: 0, width: 0, height: 0}; }
  getTotalLength() { return 0; }
  getPointAtLength() { return {x: 0, y: 0}; }
}
const XHTML = 'http://www.w3.org/1999/xhtml';

// A small selector engine: lists, descendant and child combinators, compounds.
function splitTop(text, sep) {
  const out = []; let depth = 0, quote = null, start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quote) { if (c === quote) quote = null; continue; }
    if (c === '"' || c === "'") quote = c;
    else if (c === '(' || c === '[') depth++;
    else if (c === ')' || c === ']') depth--;
    else if (c === sep && depth === 0) { out.push(text.slice(start, i)); start = i + 1; }
  }
  out.push(text.slice(start));
  return out.map(s => s.trim()).filter(Boolean);
}
function parseComplex(text) {
  const parts = []; let buf = '', depth = 0, quote = null, comb = ' ';
  const flush = () => { if (buf.trim()) { parts.push({comb, compound: buf.trim()}); comb = ' '; } buf = ''; };
  for (const c of text) {
    if (quote) { buf += c; if (c === quote) quote = null; continue; }
    if (c === '"' || c === "'") { quote = c; buf += c; continue; }
    if (c === '(' || c === '[') depth++;
    if (c === ')' || c === ']') depth--;
    if (depth === 0 && (c === ' ' || c === '>')) { flush(); if (c === '>') comb = '>'; continue; }
    buf += c;
  }
  flush();
  return parts;
}
function matchCompound(node, compound, scope) {
  let rest = compound;
  const take = re => { const m = rest.match(re); if (m) rest = rest.slice(m[0].length); return m; };
  let m = take(/^(\*|[a-zA-Z][\w-]*)/);
  if (m && m[1] !== '*' && node.localName.toLowerCase() !== m[1].toLowerCase()) return false;
  while (rest) {
    if ((m = take(/^#([\w-]+)/))) { if (node.id !== m[1]) return false; }
    else if ((m = take(/^\.([\w-]+)/))) { if (!node.classList.contains(m[1])) return false; }
    else if ((m = take(/^\[\s*([\w:-]+)\s*(?:([~|^$*]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\]\s]*)))?\s*\]/))) {
      const value = node.getAttribute(m[1]);
      if (value === null) return false;
      if (m[2]) {
        const want = m[3] ?? m[4] ?? m[5] ?? '';
        const ok = {'=': value === want, '~=': value.split(/\s+/).includes(want), '^=': value.startsWith(want),
          '$=': value.endsWith(want), '*=': value.includes(want), '|=': value === want || value.startsWith(want + '-')}[m[2]];
        if (!ok) return false;
      }
    }
    else if ((m = take(/^:not\(/))) {
      let depth = 1, i = 0;
      for (; i < rest.length && depth; i++) { if (rest[i] === '(') depth++; if (rest[i] === ')') depth--; }
      const inner = rest.slice(0, i - 1); rest = rest.slice(i);
      if (matches(node, inner, scope)) return false;
    }
    else if (take(/^:scope/)) { if (node !== scope) return false; }
    else if (take(/^:disabled/)) { if (!node.disabled) return false; }
    else if (take(/^:enabled/)) { if (node.disabled) return false; }
    else throw new Error(`fake DOM: selector part ${JSON.stringify(rest)} of ${JSON.stringify(compound)} is not supported`);
  }
  return true;
}
function matchComplex(node, parts, i, scope) {
  if (!matchCompound(node, parts[i].compound, scope)) return false;
  if (i === 0) return true;
  if (parts[i].comb === '>') { const p = node.parentNode; return !!p && p.nodeType === 1 && matchComplex(p, parts, i - 1, scope); }
  for (let p = node.parentNode; p && p.nodeType === 1; p = p.parentNode) if (matchComplex(p, parts, i - 1, scope)) return true;
  return false;
}
function matches(node, selector, scope) {
  if (!node || node.nodeType !== 1) return false;
  return splitTop(String(selector), ',').some(one => { const parts = parseComplex(one); return parts.length && matchComplex(node, parts, parts.length - 1, scope); });
}

// A 2D context that records what it draws, in canvas pixels with the transform applied.
function recorder(log) {
  const state = {fillStyle: '#000000', strokeStyle: '#000000', lineWidth: 1, lineCap: 'butt', lineJoin: 'miter',
    font: '10px sans-serif', textAlign: 'start', textBaseline: 'alphabetic', globalAlpha: 1, globalCompositeOperation: 'source-over'};
  let mat = [1, 0, 0, 1, 0, 0], path = [];
  const stack = [];
  const r = v => Math.round(v * 1000) / 1000;
  const T = (x, y) => [r(mat[0] * x + mat[2] * y + mat[4]), r(mat[1] * x + mat[3] * y + mat[5])];
  const M = () => mat.map(r);
  const pick = keys => Object.fromEntries(keys.map(k => [k, state[k]]));
  const STROKE = ['strokeStyle', 'lineWidth', 'lineCap', 'lineJoin', 'globalAlpha', 'globalCompositeOperation'];
  const FILL = ['fillStyle', 'globalAlpha', 'globalCompositeOperation'];
  const mul = (a, b) => [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3],
    a[1] * b[2] + a[3] * b[3], a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]];
  const ctx = {
    canvas: null,
    save() { stack.push([{...state}, [...mat]]); },
    restore() { const s = stack.pop(); if (s) { Object.assign(state, s[0]); mat = s[1]; } },
    translate(x, y) { mat = mul(mat, [1, 0, 0, 1, x, y]); },
    rotate(a) { const c = Math.cos(a), s = Math.sin(a); mat = mul(mat, [c, s, -s, c, 0, 0]); },
    scale(x, y) { mat = mul(mat, [x, 0, 0, y, 0, 0]); },
    transform(a, b, c, d, e, f) { mat = mul(mat, [a, b, c, d, e, f]); },
    setTransform(a = 1, b = 0, c = 0, d = 1, e = 0, f = 0) { mat = typeof a === 'object' ? [a.a, a.b, a.c, a.d, a.e, a.f] : [a, b, c, d, e, f]; },
    resetTransform() { mat = [1, 0, 0, 1, 0, 0]; },
    beginPath() { path = []; },
    closePath() { path.push(['Z']); },
    moveTo(x, y) { path.push(['M', ...T(x, y)]); },
    lineTo(x, y) { path.push(['L', ...T(x, y)]); },
    quadraticCurveTo(a, b, x, y) { path.push(['Q', ...T(a, b), ...T(x, y)]); },
    bezierCurveTo(a, b, c, d, x, y) { path.push(['C', ...T(a, b), ...T(c, d), ...T(x, y)]); },
    arc(x, y, rad, a0, a1, ccw) { path.push(['A', ...T(x, y), r(rad), r(a0), r(a1), !!ccw, M()]); },
    arcTo(a, b, c, d, rad) { path.push(['AT', ...T(a, b), ...T(c, d), r(rad)]); },
    ellipse(x, y, rx, ry, rot, a0, a1, ccw) { path.push(['E', ...T(x, y), r(rx), r(ry), r(rot), r(a0), r(a1), !!ccw, M()]); },
    rect(x, y, w, h) { path.push(['R', ...T(x, y), r(w), r(h), M()]); },
    roundRect(x, y, w, h, rad) { path.push(['RR', ...T(x, y), r(w), r(h), JSON.stringify(rad), M()]); },
    stroke() { log.push(['stroke', pick(STROKE), path.slice()]); },
    fill() { log.push(['fill', pick(FILL), path.slice()]); },
    clip() { log.push(['clip', path.slice()]); },
    strokeRect(x, y, w, h) { log.push(['strokeRect', pick(STROKE), ...T(x, y), r(w), r(h), M()]); },
    fillRect(x, y, w, h) { log.push(['fillRect', pick(FILL), ...T(x, y), r(w), r(h), M()]); },
    clearRect(x, y, w, h) { log.push(['clearRect', ...T(x, y), r(w), r(h)]); },
    fillText(t, x, y) { log.push(['fillText', pick([...FILL, 'font', 'textAlign', 'textBaseline']), String(t), ...T(x, y), M()]); },
    strokeText(t, x, y) { log.push(['strokeText', pick([...STROKE, 'font', 'textAlign', 'textBaseline']), String(t), ...T(x, y), M()]); },
    drawImage() { log.push(['drawImage']); },
    measureText: text => ({width: String(text).length * 6}),
    createLinearGradient() { return {addColorStop() {}}; },
    createRadialGradient() { return {addColorStop() {}}; },
    getImageData(x, y, w, h) { return {data: new Uint8ClampedArray(w * h * 4), width: w, height: h}; },
    putImageData() { log.push(['putImageData']); },
    setLineDash(d) { state.lineDash = JSON.stringify(d); },
    getLineDash() { return JSON.parse(state.lineDash || '[]'); },
  };
  return new Proxy(ctx, {
    get: (o, k) => k in o ? o[k] : k in state ? state[k] : typeof k === 'string' ? (() => {}) : undefined,
    set: (o, k, v) => { if (typeof v === 'function' || k === 'canvas') o[k] = v; else state[k] = v; return true; },
  });
}
const iconHash = log => createHash('sha256').update(JSON.stringify(log)).digest('hex').slice(0, 16);

class FakeDocument extends FakeTarget {
  constructor() {
    super();
    this.nodeType = 9; this.visibilityState = 'visible'; this.hidden = false; this.readyState = 'complete';
  }
  __parent() { return globalThis.window; }
  createElement(tag) { return new El(String(tag)); }
  createElementNS(ns, tag) { return new El(String(tag), ns); }
  createTextNode(text) { return new TextNode(text); }
  createDocumentFragment() { return new El('#fragment'); }
  getElementById(id) { return this.documentElement.querySelector('#' + id) || (this.documentElement.id === id ? this.documentElement : null); }
  querySelectorAll(selector) { return [this.documentElement, ...this.documentElement.querySelectorAll(selector)].filter(n => n === this.documentElement ? matches(n, selector, null) : true); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  elementFromPoint() { return null; }
  hasFocus() { return true; }
}
const document = new FakeDocument();
globalThis.document = document;
document.documentElement = new El('html');
document.head = new El('head'); document.body = new El('body');
document.documentElement.append(document.head, document.body);
document.activeElement = document.body;
const controlsBar = new El('div'); controlsBar.id = 'twin-controls'; document.body.append(controlsBar);

class FakeWindow extends FakeTarget {}
const win = new FakeWindow();
Object.assign(win, {chfBase: '../', devicePixelRatio: 1, innerWidth: 1400, innerHeight: 1000, document,
  matchMedia: query => ({matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}}),
  getComputedStyle: node => ({display: node.hidden ? 'none' : node.style.display || 'block', visibility: node.style.visibility || 'visible',
    getPropertyValue: k => node.style.getPropertyValue(k)}),
  requestAnimationFrame: callback => setImmediate(() => callback(performance.now())),
  cancelAnimationFrame: () => {},
  location: {search: '', href: 'http://localhost/house/twin', pathname: '/house/twin'},
});
globalThis.window = win;
globalThis.getComputedStyle = win.getComputedStyle;
globalThis.matchMedia = win.matchMedia;
globalThis.requestAnimationFrame = win.requestAnimationFrame;
globalThis.cancelAnimationFrame = win.cancelAnimationFrame;
globalThis.location = win.location;
globalThis.Node = El; globalThis.Element = El; globalThis.HTMLElement = El; globalThis.SVGElement = El;
globalThis.HTMLButtonElement = El; globalThis.HTMLInputElement = El;

// Serialise a node: tag, attributes, interesting properties, text and children.
function ser(node) {
  if (node.nodeType === 3) return node.data;
  const props = {};
  for (const k of ['type', 'min', 'max', 'step', 'value', 'checked', 'disabled', 'hidden'])
    if (node[k] !== undefined && node[k] !== false && node[k] !== '') props[k] = node[k];
  const attrs = {};
  for (const name of node.getAttributeNames().sort()) if (!BOOLEAN.has(name)) attrs[name] = node.getAttribute(name);
  return [node.localName, attrs, props, ...node.childNodes.map(ser)];
}
const isDisabled = node => {
  for (let n = node; n && n.nodeType === 1; n = n.parentNode)
    if (n.disabled === true || n.getAttribute('aria-disabled') === 'true' || n.inert === true) return true;
  return false;
};
const shown = node => { for (let n = node; n && n.nodeType === 1; n = n.parentNode) if (n.hidden || n.style.display === 'none' || n.style.visibility === 'hidden') return false; return node.isConnected; };

// ------------------------------------------------------------------ the rig
// A mounted live layer over a fake view, its own fake Home Assistant behind
// api() and window.chfControlFetch, and gestures on the canvas at a marker.
const THREE = await import('three');
const FT = .3048;
const liveModule = await import(file('static/twin/live/live.js'));

async function rig({devices, rooms = null, spacing = 8}) {
  const states = Object.fromEntries(devices.map(d => [d.entity_id, {entity_id: d.entity_id, state: d.state,
    attributes: structuredClone(d.attributes || {})}]));
  const layoutDevices = devices.map(d => ({device_id: d.device_id, name: d.name, entity_id: d.entity_id,
    entities: [d.entity_id], kind: d.kind, offered: d.offered !== false, area_id: d.area_id || 'kitchen'}));
  const roomRows = rooms || [{building: 'b', room: 'r', level: 'L1', name: 'Kitchen', area_id: 'kitchen',
    lights: devices.filter(d => d.kind === 'light').map(d => d.entity_id)}];
  const layout = {available: true, rooms: roomRows, devices: layoutDevices,
    markers: layoutDevices.map((d, i) => ({...d, building: 'b', level: 'L1', room: 'r',
      at: devices[i].at || [i * spacing - 24, 4, 2], placed: true}))};
  const t = {states, layout, requests: [], calls: [], confirms: [], alerts: [], confirm: true, frozen: new Set()};
  window.showGlobalAlert = message => t.alerts.push(message);
  window.promptConfirm = async (...args) => { t.confirms.push(args); return t.confirm; };
  window.promptInput = async () => null;
  window.chfControlFetch = async (url, options) => {
    const call = JSON.parse(options.body); t.calls.push({url, ...call});
    const row = states[call.data.entity_id];
    if (row && !t.frozen.has(call.data.entity_id)) {
      const a = row.attributes, d = call.data;
      const next = {unlock: 'unlocked', lock: 'locked', open_cover: 'open', close_cover: 'closed', turn_on: 'on', turn_off: 'off',
        alarm_disarm: 'disarmed', alarm_arm_home: 'armed_home', alarm_arm_away: 'armed_away', open: 'open', close: 'closed'}[call.service];
      if (next) row.state = next;
      if (call.service === 'toggle') row.state = row.state === 'on' ? 'off' : 'on';
      if (call.service === 'turn_on' && call.domain === 'light') {
        if (d.brightness_pct !== undefined) a.brightness = Math.round(d.brightness_pct * 255 / 100);
        else if (d.brightness !== undefined) a.brightness = d.brightness;
        else if (!a.brightness) a.brightness = 255;
        if (d.color_temp_kelvin !== undefined) { a.color_temp_kelvin = d.color_temp_kelvin; a.color_mode = 'color_temp'; delete a.rgb_color; delete a.hs_color; }
        if (d.rgb_color !== undefined) { a.rgb_color = d.rgb_color; a.color_mode = 'rgb'; }
        if (d.hs_color !== undefined) { a.hs_color = d.hs_color; a.color_mode = 'hs'; }
        if (d.effect !== undefined) a.effect = d.effect;
      }
      if (call.service === 'set_temperature' && d.temperature !== undefined) a.temperature = d.temperature;
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  t.api = async path => {
    t.requests.push(path);
    // A check may slow Home Assistant's confirming poll (fresh=1) by t.pollDelay ms.
    if (t.pollDelay && String(path).includes('fresh=1')) await wait(t.pollDelay);
    return {ok: true, json: async () => structuredClone(path === 'api/house/live' ? layout : {states})};
  };
  const canvas = new El('canvas'), host = new El('main'); host.__host = true; host.append(canvas); document.body.append(host);
  const camera = new THREE.PerspectiveCamera(38, 1.4, .1, 1000);
  camera.position.set(0, 50, 0); camera.up.set(0, 0, -1); camera.lookAt(0, 0, 0);
  const view = {ready: true, scene: new THREE.Scene(), renderer3: {domElement: canvas}, camera, controls: {target: new THREE.Vector3()},
    groups: {levels: {'b:L1': new THREE.Group()}},
    plan: {buildings: [{id: 'b', position: [0, 0], rotation: 0, base: 0, levels: [{id: 'L1', elevation: 0, ceiling: 9}],
      rooms: [{id: 'r', level: 'L1', polygon: [[-40, -10], [40, -10], [40, 20], [-40, 20]]}], stairs: []}]},
    pick: () => ({kind: 'room', building: 'b', id: 'r'}),
    render() { this.live?.draw(); }};
  t.view = view; t.canvas = canvas; t.host = host; t.camera = camera;
  t.live = await liveModule.mountLive(view, {api: t.api});
  assert.ok(t.live, 'mountLive mounts');
  t.cleanup = () => { try { t.live.stop(); } catch {} host.remove(); };
  t.sprite = id => { let out = null; view.scene.traverse(o => { if (o.isSprite && o.userData?.deviceId === id) out = o; }); return out; };
  // Client pixel of a marker's centre at the current camera.
  t.screenOf = id => {
    const sprite = t.sprite(id); assert.ok(sprite, `a sprite for ${id}`);
    view.render(); camera.updateMatrixWorld(true); sprite.updateMatrixWorld(true);
    const p = sprite.getWorldPosition(new THREE.Vector3()).project(camera);
    return [(p.x + 1) * 1400 / 2, (1 - p.y) * 1000 / 2];
  };
  t.pointer = (type, [x, y], extra = {}) => canvas.dispatchEvent(new PointerEvent(type,
    {bubbles: true, cancelable: true, clientX: x, clientY: y, pointerId: 1, button: 0, buttons: type === 'pointerup' ? 0 : 1, ...extra}));
  t.tapAt = async (at, extra = {}) => {
    t.pointer('pointerdown', at, extra); await wait(40); t.pointer('pointerup', at, extra);
    canvas.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, clientX: at[0], clientY: at[1]}));
    await wait(60);
  };
  t.tap = id => t.tapAt(t.screenOf(id));
  // A press held still for `ms`, then released where it started (a mouse also fires click).
  t.holdAt = async (at, ms = 650, extra = {}) => {
    t.pointer('pointerdown', at, extra); await wait(ms); t.pointer('pointerup', at, extra);
    canvas.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, clientX: at[0], clientY: at[1]}));
    await wait(60);
  };
  t.hold = (id, ms) => t.holdAt(t.screenOf(id), ms);
  t.serviceCalls = () => t.calls.map(c => [c.domain, c.service, c.data]);
  return t;
}
// Click a node the way a finger does: pointerdown, pointerup, click (all bubble).
async function press(node) {
  assert.ok(node, 'the control exists');
  for (const type of ['pointerdown', 'pointerup'])
    node.dispatchEvent(new PointerEvent(type, {bubbles: true, cancelable: true, pointerId: 7, buttons: type === 'pointerdown' ? 1 : 0}));
  node.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
  await wait(40);
}
const key = (node, name) => node.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, cancelable: true, key: name}));
"""


def run(driver, config=None, prefix='chauffeur_twin_node_', timeout=180, args=()):
    """Run PRELUDE + driver under node; print its output; return its exit code (0 when node is missing)."""
    node = shutil.which('node')
    if not node:
        print('  skip  node is unavailable')
        return 0
    paths = []
    try:
        cfg = {'root': ROOT.as_posix(), **(config or {})}
        for suffix, content in (('.mjs', PRELUDE + driver), ('.json', json.dumps(cfg))):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix=prefix, delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run([node, str(paths[0]), str(paths[1]), *args], capture_output=True, text=True,
                                encoding='utf-8', timeout=timeout)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-3000:], end='')
        return result.returncode
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
