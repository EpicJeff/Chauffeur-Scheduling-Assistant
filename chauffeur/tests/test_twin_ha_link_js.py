"""Node checks for the editor's Home Assistant area link (piece 3 Task 4 of
docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md; brief
.superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-4-brief.md).

static/twin/editor/ha_link.js runs in node against a small DOM double:

    createHaLink({ api, onCommit, signal })
      -> { refresh(): Promise, roomSection(room), buildingSection(building), state() }

What the double assumes of ha_link.js (the implementer matches these):
- `api` is the editor's own api.js module namespace (editor.js passes
  `import * as api from './api.js'`); the link is read with a fetch whose URL
  ends in `api/house/ha/link`, ingress-relative (window.chfBase + 'api/...'),
  never root-relative. The double answers fetch by URL.
- The DOM is built with document.createElement / append / textContent and
  event listeners (or on<event> properties), never innerHTML.
- `roomSection(room)` takes the plan's room piece with its building id added
  ({id, name, level, ha_area, building}; `room` repeats the id).
  `buildingSection(building)` takes the plan's building ({id, name, rooms, levels}).
- `onCommit(operation)` receives the model op
  {op: 'set', building, id: <room id>, field: 'ha_area', value: <area id or ''>}.
- A room row's `suggested` is either an area id or {area_id, name}; both read the same.
- The pick-list is a <select> labelled `Home Assistant area` (a wrapping <label>,
  a <label for>, or aria-label), first option `No area` (value ''), then each
  area by name with its area id as value, in an <optgroup label="{floor name}">
  per floor when floors exist.
- The unlinked list: heading text `Areas with no room`, one button per area
  whose text holds the area's name; tapping it calls window.promptChoice(title,
  message, [{value, label}]) over the building's rooms, labels holding the room names.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_ha_link_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

DRIVER = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const {root} = JSON.parse(readFileSync(process.argv[2]));
const file = p => pathToFileURL(root + '/' + p).href;
const data = source => 'data:text/javascript,' + encodeURIComponent(source);
const three = file('static/vendor/three-r187/three.module.js');
registerHooks({resolve(spec, ctx, next) {
  if (spec === 'three') return {url: three, shortCircuit: true};
  if (spec.startsWith('three/addons/')) return {url: file('static/vendor/three-r187/addons/' + spec.slice(13)), shortCircuit: true};
  return next(spec, ctx);
}, load(url, ctx, next) {
  return url.startsWith('file:') && url.endsWith('.js') ? {...next(url, {...ctx, format:'module'}), format:'module'} : next(url, ctx);
}});

const NO_HA = 'Home Assistant is not connected, so areas and devices are hidden.';
const GONE = "This room's Home Assistant area is gone; pick another.";

// ---------------------------------------------------------------- a small DOM double
class El {
  constructor(tag) {
    this.tagName = String(tag || 'div').toUpperCase(); this.localName = String(tag || 'div').toLowerCase();
    this.children = []; this.parentElement = null; this.style = {}; this.dataset = {}; this.attrs = {};
    this._text = ''; this.hidden = false; this.disabled = false; this.className = ''; this.listeners = [];
    const self = this;
    this.classList = {
      add: (...c) => { const s = new Set(self.className.split(/\s+/).filter(Boolean)); c.forEach(x => s.add(x)); self.className = [...s].join(' '); },
      remove: (...c) => { self.className = self.className.split(/\s+/).filter(x => x && !c.includes(x)).join(' '); },
      toggle: (c, on) => { const has = self.className.split(/\s+/).includes(c); const want = on === undefined ? !has : !!on;
        if (want) self.classList.add(c); else self.classList.remove(c); return want; },
      contains: c => self.className.split(/\s+/).includes(c),
    };
  }
  get childNodes() { return this.children; }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children.at(-1) || null; }
  get firstElementChild() { return this.children.find(c => c.tagName !== '#TEXT') || null; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set textContent(v) { this.replaceChildren(); this._text = String(v ?? ''); }
  get innerText() { return this.textContent; }
  set innerText(v) { this.textContent = v; }
  get innerHTML() { return ''; }
  set innerHTML(v) {
    if (String(v ?? '') === '') { this.replaceChildren(); this._text = ''; return; }
    throw new Error('ha_link.js must build its DOM with createElement, not innerHTML (the node double has no HTML parser)');
  }
  get id() { return this.attrs.id || ''; }
  set id(v) { this.attrs.id = String(v); }
  get htmlFor() { return this.attrs.for || ''; }
  set htmlFor(v) { this.attrs.for = String(v); }
  get label() { return this.attrs.label ?? ''; }
  set label(v) { this.attrs.label = String(v); }
  get type() { return this.attrs.type ?? (this.localName === 'button' ? 'submit' : ''); }
  set type(v) { this.attrs.type = String(v); }
  // <select> and <option> value semantics
  get options() { return this.localName === 'select' ? descendants(this).filter(n => n.localName === 'option') : undefined; }
  get value() {
    if (this.localName === 'option') return this._value !== undefined ? this._value : (this.attrs.value ?? this.textContent);
    if (this.localName === 'select') {
      const options = this.options;
      const chosen = options.find(o => o.selected);
      if (chosen) return chosen.value;
      return options.length ? options[0].value : '';
    }
    return this._value ?? '';
  }
  set value(v) {
    v = String(v ?? '');
    if (this.localName === 'select') { for (const o of this.options) o._selected = o.value === v; return; }
    this._value = v;
  }
  get selected() { return !!this._selected || (this._selected === undefined && 'selected' in this.attrs); }
  set selected(v) {
    if (v && this.localName === 'option') {
      let p = this.parentElement; while (p && p.localName !== 'select') p = p.parentElement;
      if (p) for (const o of p.options) o._selected = false;
    }
    this._selected = !!v;
  }
  get selectedIndex() { return this.localName === 'select' ? this.options.findIndex(o => o.value === this.value) : -1; }
  set selectedIndex(i) { if (this.localName === 'select') this.options.forEach((o, k) => { o._selected = k === i; }); }
  get selectedOptions() { return this.localName === 'select' ? this.options.filter(o => o.value === this.value) : []; }
  add(option) { this.append(option); }
  // tree
  _adopt(n) {
    if (typeof n === 'string' || typeof n === 'number') { const t = new El('#text'); t._text = String(n); n = t; }
    if (n.localName === '#fragment') return [...n.children].flatMap(c => this._adopt(c));
    if (n.parentElement) n.remove();
    n.parentElement = this; return [n];
  }
  append(...nodes) { for (const n of nodes) this.children.push(...this._adopt(n)); }
  appendChild(n) { this.append(n); return n; }
  prepend(...nodes) { this.children.unshift(...nodes.flatMap(n => this._adopt(n))); }
  insertBefore(n, ref) { const adopted = this._adopt(n); const i = ref ? this.children.indexOf(ref) : -1;
    if (i < 0) this.children.push(...adopted); else this.children.splice(i, 0, ...adopted); return n; }
  replaceChildren(...nodes) { for (const c of this.children) c.parentElement = null; this.children = []; this._text = ''; this.append(...nodes); }
  remove() { const p = this.parentElement; if (p) { p.children = p.children.filter(c => c !== this); this.parentElement = null; } }
  replaceWith(...nodes) { const p = this.parentElement; if (!p) return; const i = p.children.indexOf(this); this.remove();
    p.children.splice(i, 0, ...nodes.flatMap(n => p._adopt(n))); }
  before(...nodes) { const p = this.parentElement; if (!p) return; const i = p.children.indexOf(this);
    p.children.splice(i, 0, ...nodes.flatMap(n => p._adopt(n))); }
  after(...nodes) { const p = this.parentElement; if (!p) return; const i = p.children.indexOf(this);
    p.children.splice(i + 1, 0, ...nodes.flatMap(n => p._adopt(n))); }
  contains(n) { return n === this || descendants(this).includes(n); }
  closest(sel) { for (let n = this; n; n = n.parentElement) if (matches(n, sel)) return n; return null; }
  matches(sel) { return matches(this, sel); }
  querySelectorAll(sel) { return descendants(this).filter(n => matches(n, sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  // attributes
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k.startsWith('data-')) this.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(v);
    if (k === 'class') this.className = String(v);
    if (k === 'hidden') this.hidden = true;
    if (k === 'disabled') this.disabled = true;
  }
  getAttribute(k) { return k === 'class' ? this.className : (k in this.attrs ? this.attrs[k] : null); }
  hasAttribute(k) { return k in this.attrs || (k === 'hidden' && this.hidden); }
  removeAttribute(k) { delete this.attrs[k]; if (k === 'hidden') this.hidden = false; if (k === 'disabled') this.disabled = false; }
  toggleAttribute(k, on) { const want = on === undefined ? !this.hasAttribute(k) : !!on; if (want) this.setAttribute(k, ''); else this.removeAttribute(k); return want; }
  // events: a listener registry with bubbling and on<type> properties
  addEventListener(type, fn, opts) {
    const signal = opts && typeof opts === 'object' ? opts.signal : null;
    if (signal?.aborted) return;
    const row = { type, fn };
    this.listeners.push(row);
    signal?.addEventListener('abort', () => { this.listeners = this.listeners.filter(r => r !== row); });
  }
  removeEventListener(type, fn) { this.listeners = this.listeners.filter(r => !(r.type === type && r.fn === fn)); }
  dispatchEvent(event) {
    let stopped = false;
    const e = Object.assign(Object.create(null), {
      type: event.type, target: this, bubbles: event.bubbles !== false, defaultPrevented: false, key: event.key,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() { stopped = true; }, stopImmediatePropagation() { stopped = true; },
    });
    for (let n = this; n && !stopped; n = e.bubbles ? n.parentElement : null) {
      e.currentTarget = n;
      for (const r of [...n.listeners]) if (r.type === e.type) (typeof r.fn === 'function' ? r.fn : r.fn.handleEvent).call(n, e);
      if (typeof n['on' + e.type] === 'function') n['on' + e.type].call(n, e);
    }
    return !e.defaultPrevented;
  }
  click() { if (!this.disabled) this.dispatchEvent({ type: 'click' }); }
  focus() {} blur() {} scrollIntoView() {}
  getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
}
const descendants = node => node.children.flatMap(c => [c, ...descendants(c)]);
function matches(n, sel) {
  return String(sel).split(',').map(s => s.trim()).some(s => {
    const m = s.match(/^([a-zA-Z0-9-]*)((?:[.#][\w-]+|\[[^\]]+\])*)$/);
    if (!m) return false;
    if (m[1] && n.localName !== m[1].toLowerCase()) return false;
    for (const part of m[2].match(/[.#][\w-]+|\[[^\]]+\]/g) || []) {
      if (part[0] === '.' && !n.classList.contains(part.slice(1))) return false;
      if (part[0] === '#' && n.id !== part.slice(1)) return false;
      if (part[0] === '[') {
        const [, k, v] = part.match(/^\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]$/) || [];
        if (!k || n.getAttribute(k) === null && !(k === 'hidden' && n.hidden)) return false;
        if (v !== undefined && n.getAttribute(k) !== v) return false;
      }
    }
    return true;
  });
}
const ids = new Map();
globalThis.window = globalThis;
globalThis.document = {
  createElement: tag => new El(tag),
  createTextNode: text => { const t = new El('#text'); t._text = String(text); return t; },
  createDocumentFragment: () => new El('#fragment'),
  getElementById: id => ids.get(id) || null,
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {},
  body: new El('body'), hidden: false,
};
globalThis.Option = function (text = '', value, defaultSelected = false, selected = false) {
  const o = new El('option'); o.textContent = text; if (value !== undefined) o.value = value;
  if (defaultSelected || selected) o._selected = true; return o;
};
globalThis.location = { search: '?test=1', pathname: '/house/editor', href: 'http://127.0.0.1/house/editor?test=1' };
window.chfBase = '../';
const alerts = [];
window.showGlobalAlert = text => { alerts.push(String(text)); };
window.promptConfirm = async () => true;
const choices = [];
let choose = () => null;
window.promptChoice = async (title, message, options) => { choices.push({ title, message, options }); return choose(options); };

// The house's answer to GET api/house/ha/link, set per check.
let linkBody = null;
const fetched = [];
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === 'string' ? input : input.url;
  fetched.push({ url, method: (init.method || 'GET').toUpperCase() });
  if (/api\/house\/ha\/link(\?|$)/.test(url)) {
    const text = JSON.stringify(linkBody);
    return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => text, json: async () => JSON.parse(text) };
  }
  const text = JSON.stringify({ detail: 'not in this double' });
  return { ok: false, status: 404, headers: { get: () => 'application/json' }, text: async () => text, json: async () => JSON.parse(text) };
};

// ---------------------------------------------------------------- helpers
const visible = n => { for (let p = n; p; p = p.parentElement) if (p.hidden || p.style?.display === 'none') return false; return true; };
const shownText = n => !visible(n) ? '' : n._text + n.children.filter(c => !c.hidden && c.style?.display !== 'none').map(shownText).join(' ');
const words = n => shownText(n).replace(/\s+/g, ' ').trim();
const own = n => (n._text + n.children.filter(c => c.localName === '#text').map(c => c._text).join('')).trim();
function areaSelect(section) {
  const selects = descendants(section).filter(n => n.localName === 'select' && visible(n));
  const labelled = selects.filter(s => {
    if ((s.getAttribute('aria-label') || '').trim() === 'Home Assistant area') return true;
    for (let p = s.parentElement; p; p = p.parentElement) if (p.localName === 'label' && words(p).includes('Home Assistant area')) return true;
    return descendants(section).some(l => l.localName === 'label' && s.id && l.htmlFor === s.id && words(l).includes('Home Assistant area'));
  });
  return labelled[0] || null;
}
function buttonNamed(section, text) {
  return descendants(section).find(n => n.localName === 'button' && visible(n) && words(n) === text) || null;
}
function buttonHolding(section, text) {
  return descendants(section).find(n => n.localName === 'button' && visible(n) && words(n).includes(text)) || null;
}
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setTimeout(r, 0)); };
const subset = (got, want) => Object.entries(want).every(([k, v]) => JSON.stringify(got?.[k]) === JSON.stringify(v));

const { createHaLink } = await import(file('static/twin/editor/ha_link.js'));
const api = await import(file('static/twin/editor/api.js'));

function mount(body) {
  linkBody = body; fetched.length = 0; alerts.length = 0; choices.length = 0;
  const commits = [], abort = new AbortController();
  const link = createHaLink({ api, signal: abort.signal, onCommit: async op => { commits.push(op); return {}; } });
  for (const key of ['refresh', 'roomSection', 'buildingSection', 'state']) assert.equal(typeof link[key], 'function', `createHaLink returns ${key}()`);
  return { link, commits, abort };
}
const room = (id, name, ha_area = '', level = 'L1') => ({ id, room: id, building: 'B1', name, level, ha_area, kind: 'room' });
const BUILDING = { id: 'B1', name: 'House', levels: [{ id: 'L1', name: 'Main floor' }, { id: 'L2', name: 'Upstairs' }],
  rooms: [room('r-den', 'Den', 'kitchen'), room('r-dining', 'Dining'), room('r-study', 'Study', '', 'L2')] };
const row = (r, extra = {}) => ({ building: 'B1', level: r.level, room: r.id, name: r.name, ha_area: r.ha_area, gone: false, notes: [], ...extra });
const FLOORS = [{ floor_id: 'ground', name: 'Ground floor', level: 0 }, { floor_id: 'upstairs', name: 'Upstairs', level: 1 }];
const AREAS = [
  { area_id: 'kitchen', name: 'Kitchen', floor_id: 'ground', floor_name: 'Ground floor', floor_level: 0 },
  { area_id: 'dining_area', name: 'Dining', floor_id: 'ground', floor_name: 'Ground floor', floor_level: 0 },
  { area_id: 'office', name: 'Office', floor_id: 'upstairs', floor_name: 'Upstairs', floor_level: 1 },
  { area_id: 'patio', name: 'Patio', floor_id: null, floor_name: null, floor_level: null },
];
const linked = (extraRooms = {}) => ({
  available: true, areas: AREAS, floors: FLOORS,
  rooms: BUILDING.rooms.map(r => row(r, extraRooms[r.id] || {})),
  unlinked: [{ area_id: 'office', name: 'Office' }, { area_id: 'patio', name: 'Patio' }], devices: [],
});

let passed = 0;
const ok = label => { passed++; console.log('  ok ' + label); };
const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check('pick_list_groups_by_floor', async () => {
  const { link, commits, abort } = mount(linked({ 'r-dining': { suggested: 'dining_area' } }));
  await link.refresh();
  const hit = fetched.find(f => /api\/house\/ha\/link(\?|$)/.test(f.url));
  assert.ok(hit, `refresh() reads api/house/ha/link: ${JSON.stringify(fetched)}`);
  assert.ok(!hit.url.startsWith('/'), `the link URL is ingress-relative (base() + 'api/...'), never root-relative: ${hit.url}`);
  assert.equal(link.state()?.available, true, 'state() returns the link answer once refresh() resolves');
  const section = link.roomSection(BUILDING.rooms[0]);
  assert.ok(section && typeof section === 'object' && Array.isArray(section.children), 'roomSection returns an element');
  const select = areaSelect(section);
  assert.ok(select, `a <select> labelled 'Home Assistant area': ${words(section)}`);
  const options = select.options;
  assert.equal(own(options[0]) || words(options[0]), 'No area', 'the first option reads No area');
  assert.equal(options[0].value, '', 'No area has the empty value');
  const groups = descendants(select).filter(n => n.localName === 'optgroup');
  const byLabel = Object.fromEntries(groups.map(g => [g.label || g.getAttribute('label'), g]));
  for (const [floor, names] of [['Ground floor', ['Kitchen', 'Dining']], ['Upstairs', ['Office']]]) {
    assert.ok(byLabel[floor], `an optgroup per floor: ${floor} in ${Object.keys(byLabel)}`);
    const inGroup = descendants(byLabel[floor]).filter(n => n.localName === 'option');
    assert.deepEqual(inGroup.map(o => words(o)).sort(), [...names].sort(), `${floor} holds its areas`);
  }
  const patio = options.find(o => o.value === 'patio');
  assert.ok(patio && words(patio) === 'Patio', 'an area with no floor is still offered');
  assert.ok(!descendants(byLabel['Ground floor']).includes(patio) && !descendants(byLabel['Upstairs']).includes(patio), 'and sits in no floor group');
  for (const area of AREAS) assert.equal(words(options.find(o => o.value === area.area_id) || new El('x')), area.name, `option ${area.area_id} reads ${area.name}`);
  assert.equal(options.length, 1 + AREAS.length, 'No area plus one option per area');
  assert.equal(select.value, 'kitchen', 'the linked area is selected');
  // Picking commits set ha_area; No area commits ''.
  select.value = 'office'; select.dispatchEvent({ type: 'change' }); select.dispatchEvent({ type: 'input' }); await settle();
  assert.equal(commits.length, 1, `one commit per pick: ${JSON.stringify(commits)}`);
  assert.ok(subset(commits[0], { op: 'set', building: 'B1', id: 'r-den', field: 'ha_area', value: 'office' }), JSON.stringify(commits[0]));
  select.value = ''; select.dispatchEvent({ type: 'change' }); await settle();
  assert.equal(commits.length, 2, JSON.stringify(commits));
  assert.ok(subset(commits[1], { op: 'set', building: 'B1', id: 'r-den', field: 'ha_area', value: '' }), JSON.stringify(commits[1]));
  abort.abort();
  // No floors in Home Assistant: the areas are listed flat, with no groups.
  const flat = linked(); flat.floors = []; flat.areas = AREAS.map(a => ({ ...a, floor_id: null, floor_name: null, floor_level: null }));
  const second = mount(flat);
  await second.link.refresh();
  const plain = areaSelect(second.link.roomSection(BUILDING.rooms[1]));
  assert.ok(plain, 'the pick-list is there without floors');
  assert.equal(descendants(plain).filter(n => n.localName === 'optgroup').length, 0, 'no optgroups without floors');
  assert.deepEqual(plain.options.map(o => words(o)), ['No area', 'Kitchen', 'Dining', 'Office', 'Patio'], 'No area, then every area by name');
  assert.equal(plain.value, '', 'an unlinked room shows No area');
  second.abort.abort();
});

check('suggestion_use_commits_set', async () => {
  for (const suggested of ['dining_area', { area_id: 'dining_area', name: 'Dining' }]) {
    const { link, commits, abort } = mount(linked({ 'r-dining': { suggested } }));
    await link.refresh();
    const section = link.roomSection(BUILDING.rooms[1]);
    assert.ok(words(section).includes('Suggested: Dining'), `the suggestion line (${JSON.stringify(suggested)}): ${words(section)}`);
    const use = buttonNamed(section, 'Use');
    assert.ok(use, `a Use button: ${words(section)}`);
    use.click(); await settle();
    assert.equal(commits.length, 1, `Use commits once: ${JSON.stringify(commits)}`);
    assert.ok(subset(commits[0], { op: 'set', building: 'B1', id: 'r-dining', field: 'ha_area', value: 'dining_area' }), JSON.stringify(commits[0]));
    // A linked room offers no suggestion.
    const den = link.roomSection(BUILDING.rooms[0]);
    assert.ok(!words(den).includes('Suggested:') && !buttonNamed(den, 'Use'), `a linked room has no suggestion: ${words(den)}`);
    abort.abort();
  }
  // A room whose area Home Assistant no longer has says so, and still offers the pick-list.
  const gone = linked({ 'r-den': { gone: true, ha_area: 'old_area' } });
  gone.rooms[0].ha_area = 'old_area';
  const { link, abort } = mount(gone);
  await link.refresh();
  const section = link.roomSection({ ...BUILDING.rooms[0], ha_area: 'old_area' });
  assert.ok(words(section).includes(GONE), `the gone-area line: ${words(section)}`);
  assert.ok(areaSelect(section), 'a gone room can pick another area');
  abort.abort();
});

check('unlinked_area_asks_for_a_room', async () => {
  const { link, commits, abort } = mount(linked());
  await link.refresh();
  const section = link.buildingSection(BUILDING);
  assert.ok(words(section).includes('Areas with no room'), `the unlinked heading: ${words(section)}`);
  for (const name of ['Office', 'Patio']) assert.ok(buttonHolding(section, name), `${name} is listed as a button: ${words(section)}`);
  assert.ok(!buttonHolding(section, 'Kitchen'), 'a linked area is not listed');
  // Cancelled: nothing is committed.
  choose = () => null;
  buttonHolding(section, 'Patio').click(); await settle();
  assert.equal(choices.length, 1, 'tapping an area asks which room with promptChoice');
  assert.equal(commits.length, 0, 'a cancelled choice commits nothing');
  // Chosen: the room's area is set.
  choose = options => (options.find(o => String(o.label).includes('Study')) || {}).value ?? null;
  buttonHolding(link.buildingSection(BUILDING), 'Office').click(); await settle();
  const asked = choices.at(-1).options.map(o => String(o.label));
  for (const name of ['Den', 'Dining', 'Study']) assert.ok(asked.some(l => l.includes(name)), `the building's rooms are offered: ${asked}`);
  assert.equal(commits.length, 1, JSON.stringify(commits));
  assert.ok(subset(commits[0], { op: 'set', building: 'B1', id: 'r-study', field: 'ha_area', value: 'office' }), JSON.stringify(commits[0]));
  abort.abort();
});

check('no_ha_shows_the_line', async () => {
  const body = { available: false, areas: [], floors: [], unlinked: [], devices: [],
    rooms: BUILDING.rooms.map(r => row({ ...r, ha_area: '' })) };
  const { link, commits, abort } = mount(body);
  await link.refresh();
  assert.equal(link.state()?.available, false, 'state() says Home Assistant is not connected');
  const section = link.roomSection(BUILDING.rooms[1]);
  assert.ok(words(section).includes(NO_HA), `the no-HA line: ${words(section)}`);
  assert.equal(areaSelect(section), null, 'no area pick-list with no Home Assistant');
  assert.ok(!words(section).includes('Suggested:') && !buttonNamed(section, 'Use'), 'no suggestion');
  const building = link.buildingSection(BUILDING);
  assert.ok(!building || !words(building).includes('Areas with no room'), `no unlinked list: ${building && words(building)}`);
  assert.equal(commits.length, 0);
  assert.deepEqual(alerts, [], `nothing alerts: ${alerts}`);
  abort.abort();
});

for (const [name, fn] of checks) {
  try { await fn(); ok(name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + String(error && error.message || error).split('\n')[0].slice(0, 400)); }
}
console.log(`${passed}/${checks.length} passed`);
process.exit(passed === checks.length ? 0 : 1);
"""


def run():
    node = shutil.which('node')
    if not node:
        print('  skip  node is unavailable')
        return 0
    paths = []
    try:
        for suffix, content in (('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix()}))):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_ha_link_',
                                             delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run([node, str(paths[0]), str(paths[1])], capture_output=True, text=True, timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-3000:], end='')
        return result.returncode
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(1 if run() else 0)
