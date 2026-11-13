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
      pointerType: event.pointerType, button: event.button ?? 0, pointerId: event.pointerId ?? 1,
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
  focus() { document.activeElement = this; } blur() {} scrollIntoView() {}
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
  createElementNS: (ns, tag) => new El(tag),
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

check('camera_device_row_keeps_camera_identity_and_icon', async () => {
  const body = linked();
  body.devices = [{device_id:'front', name:'Front camera', kind:'camera', entity_id:'camera.front',
    entities:['light.front_spotlight','switch.front_privacy','camera.front'], area_id:'kitchen'}];
  const {link, abort} = mount(body);
  try {
    await link.refresh();
    const section = link.roomSection(BUILDING.rooms[0]);
    assert.ok(words(section).includes('Front camera') && words(section).includes('camera'));
    assert.ok(descendants(section).some(n => n.localName === 'svg' && n.dataset.glanceIcon === 'camera'));
    assert.equal(buttonNamed(section, 'Blink'), null, 'camera is not guessed from its spotlight');
    assert.ok(buttonNamed(section, 'Pick a spot'), 'camera keeps manual placement');
  } finally {abort.abort();}
});

check('show_as_controls_and_hide_are_house_only_edits', async () => {
  // User, 2026-11-13: a toggle between controls on the device and separate entities, and
  // hiding things from the house view without touching Home Assistant.
  const body = linked();
  body.devices = [{device_id:'pool', name:'Pool controller', kind:'light', entity_id:'light.pool', area_id:'kitchen',
    show_as:'controls', hidden:false, controls:[{entity_id:'switch.pump', name:'Pump', hidden:false}, {entity_id:'switch.falls', name:'Waterfall', hidden:true}]}];
  let {link, commits, abort} = mount(body);
  try {
    await link.refresh();
    let section = link.roomSection(BUILDING.rooms[0]);
    const select = descendants(section).find(n => n.localName === 'select' && n.getAttribute('aria-label') === 'Show as');
    assert.ok(select && select.value === 'controls', 'a device with controls offers Show as');
    assert.ok(words(section).includes('Controls (2)') && words(section).includes('Waterfall (hidden)'));
    select.value = 'entities'; select.dispatchEvent({ type: 'change' }); await settle();
    assert.ok(subset(commits.at(-1), {op:'set_ha_display', device:'pool', show_as:'entities'}), JSON.stringify(commits));
    descendants(section).find(n => n.localName === 'button' && n.getAttribute('aria-label') === 'Hide Pump').click(); await settle();
    assert.ok(subset(commits.at(-1), {op:'set_ha_display', kind:'entities', item:'switch.pump', hidden:true}));
    descendants(section).find(n => n.localName === 'button' && n.getAttribute('aria-label') === 'Hide Pool controller').click(); await settle();
    assert.ok(subset(commits.at(-1), {op:'set_ha_display', kind:'devices', item:'pool', hidden:true}));
  } finally {abort.abort();}
  // Separate entities: items grouped under their device, each placeable and hideable;
  // hidden items fold into a Hidden section with Show.
  const items = linked();
  const item = (eid, name, extra = {}) => ({device_id:'entity:' + eid, entity_id:eid, entities:[eid], name, kind:'switch', area_id:'kitchen',
    parent_device_id:'pool', parent_name:'Pool controller', show_as:'entities', hidden:false, device_hidden:false, controls:[], ...extra});
  items.devices = [item('switch.pump', 'Pump'), item('switch.falls', 'Waterfall', {hidden:true})];
  ({link, commits, abort} = mount(items));
  try {
    await link.refresh();
    const section = link.roomSection(BUILDING.rooms[0]);
    assert.ok(words(section).includes('Pool controller') && words(section).includes('Separate entities'));
    assert.ok(buttonNamed(section, 'Pick a spot'), 'an entity item is placed on its own');
    assert.ok(words(section).includes('Hidden (1)'), 'hidden items fold away');
    descendants(section).find(n => n.localName === 'button' && n.getAttribute('aria-label') === 'Show Waterfall').click(); await settle();
    assert.ok(subset(commits.at(-1), {op:'set_ha_display', kind:'entities', item:'switch.falls', hidden:false}));
  } finally {abort.abort();}
});

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

// ---------------------------------------------------------------- fix round 1 (task-4-review.md)
// I1: two refreshes while the first read is out end on the newer answer, after exactly two reads.
check('concurrent_refresh_keeps_the_newest_answer', async () => {
  const before = linked(), after = linked({ 'r-dining': { ha_area: 'dining_area' } });
  after.unlinked = [{ area_id: 'patio', name: 'Patio' }];
  const { link, abort } = mount(before);
  const realFetch = globalThis.fetch, waiting = [];
  globalThis.fetch = (input, init = {}) => {
    fetched.push({ url: String(input), method: (init.method || 'GET').toUpperCase() });
    return new Promise(resolve => waiting.push(resolve));
  };
  const answer = body => {
    const text = JSON.stringify(body);
    waiting.shift()({ ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => text, json: async () => JSON.parse(text) });
  };
  try {
    const first = link.refresh();
    await settle();
    const second = link.refresh();   // a save landed while the first read was out
    await settle();
    assert.equal(waiting.length, 1, 'the second refresh waits for the read already out, never a parallel read');
    answer(before);
    await first; await settle();
    assert.equal(waiting.length, 1, 'then exactly one follow-up read goes out');
    answer(after);
    await second; await settle();
    assert.equal(fetched.filter(f => /api\/house\/ha\/link/.test(f.url)).length, 2, `two reads: ${JSON.stringify(fetched)}`);
    assert.deepEqual(link.state().unlinked, after.unlinked, 'state() ends on the post-save answer');
  } finally { globalThis.fetch = realFetch; abort.abort(); }
});

// M2: a dropped read keeps the last good answer.
check('failed_read_keeps_the_last_answer', async () => {
  const { link, abort } = mount(linked());
  await link.refresh();
  const realFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await link.refresh();
    assert.equal(link.state()?.available, true, 'a network drop keeps the good answer');
    globalThis.fetch = async () => ({ ok: false, status: 502, headers: { get: () => 'text/html' }, text: async () => '<html>', json: async () => { throw new Error('x'); } });
    await link.refresh();
    assert.equal(link.state()?.available, true, 'a 502 keeps the good answer');
    const section = link.roomSection(BUILDING.rooms[0]);
    assert.ok(areaSelect(section) && !words(section).includes(NO_HA), `the pick-list stays: ${words(section)}`);
  } finally { globalThis.fetch = realFetch; abort.abort(); }
  // With nothing read yet, a failure reads as not connected.
  const second = mount(linked());
  try {
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await second.link.refresh();
    assert.equal(second.link.state()?.available, false, 'a first read that fails says not connected');
  } finally { globalThis.fetch = realFetch; second.abort.abort(); }
});

// M5: the unlinked-area room chooser names each room's floor and leaves out ghost rooms.
check('room_chooser_names_the_floor_and_skips_ghosts', async () => {
  const { link, commits, abort } = mount(linked());
  await link.refresh();
  const building = { ...BUILDING, rooms: [...BUILDING.rooms, room('r-den2', 'Den', '', 'L2'),
    { ...room('r-ghost', 'Proposed room'), state: 'ghost' }] };
  choose = options => (options.find(o => String(o.label) === 'Den · Upstairs') || {}).value ?? null;
  buttonHolding(link.buildingSection(building), 'Office').click(); await settle();
  const asked = choices.at(-1).options.map(o => String(o.label));
  assert.ok(asked.includes('Den · Main floor') && asked.includes('Den · Upstairs'), `each room names its floor: ${asked}`);
  assert.ok(!asked.some(l => l.includes('Proposed room')), `a ghost room is not offered: ${asked}`);
  assert.equal(commits.length, 1, JSON.stringify(commits));
  assert.ok(subset(commits[0], { id: 'r-den2', value: 'office' }), JSON.stringify(commits[0]));
  abort.abort();
});

// N1: a gone area shows as the current choice; No area can still be picked.
check('gone_area_shows_in_the_select', async () => {
  const gone = linked({ 'r-den': { gone: true, ha_area: 'old_area' } });
  const { link, commits, abort } = mount(gone);
  await link.refresh();
  const select = areaSelect(link.roomSection({ ...BUILDING.rooms[0], ha_area: 'old_area' }));
  assert.equal(select.value, 'old_area', 'the select shows the gone area, not a blank');
  const option = select.options.find(o => o.value === 'old_area');
  assert.ok(option && option.disabled, 'the gone area cannot be picked again');
  select.value = ''; select.dispatchEvent({ type: 'change' }); await settle();
  assert.ok(subset(commits[0], { value: '' }), JSON.stringify(commits));
  abort.abort();
});

// N3: floors are grouped by level, a floor with no level last, whatever the registry order.
check('floors_ordered_by_level', async () => {
  const body = linked();
  body.floors = [{ floor_id: 'attic', name: 'Attic', level: null }, { floor_id: 'upstairs', name: 'Upstairs', level: 1 },
    { floor_id: 'ground', name: 'Ground floor', level: 0 }];
  body.areas = [...AREAS, { area_id: 'loft', name: 'Loft', floor_id: 'attic', floor_name: 'Attic', floor_level: null }];
  const { link, abort } = mount(body);
  await link.refresh();
  const select = areaSelect(link.roomSection(BUILDING.rooms[0]));
  const groups = descendants(select).filter(n => n.localName === 'optgroup').map(g => g.label);
  assert.deepEqual(groups, ['Ground floor', 'Upstairs', 'Attic'], `by level: ${groups}`);
  abort.abort();
});

// M3 + M4: draw(host, record) redraws only when what the section shows changes,
// keeps a focused area select in place, and hands focus on to a redrawn control.
check('draw_keeps_focus_and_skips_unchanged', async () => {
  const body = linked();
  body.devices = [{ device_id: 'd1', name: 'Den lamp', kind: 'light', area_id: 'kitchen' }];
  const { link, abort } = mount(body);
  await link.refresh();
  const host = new El('section');
  const record = { kind: 'room', piece: BUILDING.rooms[0], building: BUILDING };
  assert.equal(link.draw(host, record), true, 'the first draw draws');
  assert.equal(link.draw(host, record), false, 'an unchanged answer does not redraw');
  // A device in another area changes nothing this card shows.
  linkBody = { ...body, devices: [...body.devices, { device_id: 'd2', name: 'Patio light', kind: 'light', area_id: 'patio' }] };
  await link.refresh();
  assert.equal(link.draw(host, record), false, 'another area\'s device does not redraw this room');
  // The person is in the select when a new answer lands: the same select stays.
  const select = areaSelect(host);
  document.activeElement = select;
  linkBody = { ...linkBody, devices: [...linkBody.devices, { device_id: 'd3', name: 'Den fan', kind: 'fan', area_id: 'kitchen' }] };
  await link.refresh();
  assert.equal(link.draw(host, record), true, 'a new device in the area redraws');
  assert.equal(areaSelect(host), select, 'the focused select is the same node: focus and an open list survive');
  assert.ok(words(host).includes('Den fan'), `the rest of the section is fresh: ${words(host)}`);
  // Focus on a device button hands on to its successor after a redraw.
  const blinkButton = descendants(host).find(n => n.localName === 'button' && words(n) === 'Blink');
  document.activeElement = blinkButton;
  linkBody = { ...linkBody, devices: linkBody.devices.map(d => d.device_id === 'd1' ? { ...d, name: 'Den lamp 2' } : d) };
  await link.refresh();
  assert.equal(link.draw(host, record), true);
  const successor = descendants(host).find(n => n.localName === 'button' && words(n) === 'Blink');
  assert.ok(successor && successor !== blinkButton && document.activeElement === successor, 'focus moves to the redrawn Blink');
  document.activeElement = null;
  abort.abort();
});

// Browser fix round (Task 5): an unnamed spot says what it is for and where it sits.
check('pick_a_spot_names_each_spot', async () => {
  const body = linked();
  body.devices = [{ device_id: 'd-plug', name: 'Kettle plug', kind: 'switch', area_id: 'kitchen' }];
  const { link, commits, abort } = mount(body);
  await link.refresh();
  link.setPlacement({ cancel() {}, arm() {}, startDrag() {},
    anchors: () => [{ id: 'a1', kind: 'switch', host: { wall: 'w1', side: 'left', at: 2, z: 4 } },
      { id: 'a2', kind: 'switch', host: { wall: 'w2', side: 'left', at: 2, z: 4 }, device: 'd-other' },
      { id: 'a3', kind: 'light', host: { ceiling: 'r-den', u: .5, v: .5 } },
      { id: 'a4', kind: 'switch', name: 'By the fridge', host: { wall: 'w3', side: 'left', at: 1, z: 4 } }] });
  const section = link.roomSection(BUILDING.rooms[0]);
  choose = options => (options.find(o => o.label === 'Switch spot 1 on a wall') || {}).value ?? null;
  buttonNamed(section, 'Pick a spot').click(); await settle();
  const asked = choices.at(-1).options.map(o => o.label);
  assert.deepEqual(asked, ['Switch spot 1 on a wall', 'By the fridge', 'On a wall', 'On the ceiling'],
    `free spots of the device's kind, named, then the surfaces: ${asked}`);
  assert.ok(subset(commits[0], { op: 'place_device', device: 'd-plug', anchor: 'a1' }), JSON.stringify(commits));
  abort.abort();
});

// ---------------------------------------------------------------- final review fix wave
// A placement double: records what the rows ask of it.
function placementDouble(extra = {}) {
  const asked = { drags: [], armed: [] };
  return { asked, cancel() {}, arm(device, kind) { asked.armed.push([device.device_id, kind]); },
    startDrag(event, device) { asked.drags.push([device.device_id, event.pointerType]); },
    anchors: () => [], doors: () => [], ...extra };
}
const deviceRowOf = (section, name) => descendants(section).find(n => n.classList?.contains('editor-device-row') && words(n).includes(name)) || null;

// I1: a placed device's row in the room card has Remove, through the editor's op path.
check('i1_placed_row_offers_remove', async () => {
  const body = linked();
  body.devices = [
    { device_id: 'd-lock', name: 'Back door lock', kind: 'lock', area_id: 'kitchen', placed: { kind: 'host', building: 'B1' } },
    { device_id: 'd-lamp', name: 'Den lamp', kind: 'light', area_id: 'kitchen', placed: null }];
  const { link, commits, abort } = mount(body);
  await link.refresh();
  const section = link.roomSection(BUILDING.rooms[0]);
  const placedRow = deviceRowOf(section, 'Back door lock'), freeRow = deviceRowOf(section, 'Den lamp');
  assert.ok(placedRow && freeRow, `both rows: ${words(section)}`);
  assert.ok(!buttonNamed(freeRow, 'Remove'), 'an unplaced device has nothing to remove');
  const remove = buttonNamed(placedRow, 'Remove');
  assert.ok(remove, `a placed device's row has Remove: ${words(placedRow)}`);
  remove.click(); await settle();
  assert.deepEqual(commits, [{ op: 'unplace_device', device: 'd-lock' }], JSON.stringify(commits));
  abort.abort();
});

// I3: a touch that starts on a row's words scrolls the card; only the grip carries the row.
check('i3_touch_drags_only_from_the_grip', async () => {
  const body = linked();
  body.devices = [{ device_id: 'd-lamp', name: 'Den lamp', kind: 'light', area_id: 'kitchen' }];
  const { link, abort } = mount(body);
  await link.refresh();
  const placement = placementDouble(); link.setPlacement(placement);
  const row = deviceRowOf(link.roomSection(BUILDING.rooms[0]), 'Den lamp');
  const grip = descendants(row).find(n => n.classList?.contains('editor-device-grip'));
  assert.ok(grip, 'the row has a grip handle');
  const name = descendants(row).find(n => n.localName === 'p');
  name.dispatchEvent({ type: 'pointerdown', pointerType: 'touch' });
  assert.deepEqual(placement.asked.drags, [], 'a touch on the words never starts a drag (the card scrolls)');
  grip.dispatchEvent({ type: 'pointerdown', pointerType: 'touch' });
  name.dispatchEvent({ type: 'pointerdown', pointerType: 'mouse' });
  assert.deepEqual(placement.asked.drags.map(d => d[0]), ['d-lamp', 'd-lamp'], 'the grip (touch) and a mouse anywhere carry it');
  abort.abort();
});

// M3: Pick a spot offers the room's doors to a lock or a contact sensor, and only to them.
check('m3_pick_a_spot_offers_doors', async () => {
  const body = linked();
  body.devices = [{ device_id: 'd-lock', name: 'Back door lock', kind: 'lock', area_id: 'kitchen' },
    { device_id: 'd-contact', name: 'Back door sensor', kind: 'sensor', area_id: 'kitchen' },
    { device_id: 'd-lamp', name: 'Den lamp', kind: 'light', area_id: 'kitchen' }];
  const { link, commits, abort } = mount(body);
  await link.refresh();
  const doors = [{ id: 'o-back', building: 'B1', label: 'Outside door', host: { opening: 'o-back', side: 'in' } },
    { id: 'o-hall', building: 'B1', label: 'Door to Hall', host: { opening: 'o-hall', side: 'out' } }];
  link.setPlacement(placementDouble({ doors: () => doors }));
  const section = link.roomSection(BUILDING.rooms[0]);
  choose = options => (options.find(o => o.label === 'Door to Hall') || {}).value ?? null;
  buttonNamed(deviceRowOf(section, 'Back door lock'), 'Pick a spot').click(); await settle();
  const asked = choices.at(-1).options.map(o => o.label);
  assert.deepEqual(asked, ['Outside door', 'Door to Hall', 'On a wall', 'On the ceiling'], `doors first: ${asked}`);
  assert.deepEqual(commits.at(-1), { op: 'place_device', device: 'd-lock', building: 'B1', host: { opening: 'o-hall', side: 'out' } },
    JSON.stringify(commits));
  choose = () => null;
  buttonNamed(deviceRowOf(section, 'Back door sensor'), 'Pick a spot').click(); await settle();
  assert.ok(choices.at(-1).options.some(o => o.label === 'Outside door'), 'a contact sensor is offered the doors too');
  buttonNamed(deviceRowOf(section, 'Den lamp'), 'Pick a spot').click(); await settle();
  assert.ok(!choices.at(-1).options.some(o => o.label === 'Outside door'), 'a light is not offered a door');
  abort.abort();
});

// M4: a placed device whose Home Assistant area has no room shows on its building's card,
// flagged, with Remove and a grip to move it.
check('m4_placed_device_in_a_roomless_area_is_flagged', async () => {
  const body = linked();
  body.areas = [...AREAS, { area_id: 'studio', name: 'Studio', floor_id: 'ground', floor_name: 'Ground floor', floor_level: 0 }];
  body.unlinked = [...body.unlinked, { area_id: 'studio', name: 'Studio' }];
  body.devices = [
    { device_id: 'd-hue', name: 'Hue lamp', kind: 'light', area_id: 'studio', placed: { kind: 'host', building: 'B1' } },
    { device_id: 'd-free', name: 'Studio fan', kind: 'fan', area_id: 'studio', placed: null },
    { device_id: 'd-other', name: 'Shed lamp', kind: 'light', area_id: 'studio', placed: { kind: 'host', building: 'B2' } }];
  const { link, commits, abort } = mount(body);
  await link.refresh();
  link.setPlacement(placementDouble());
  const section = link.buildingSection(BUILDING);
  const row = deviceRowOf(section, 'Hue lamp');
  assert.ok(row, `the building card lists the placed device: ${words(section)}`);
  assert.ok(words(section).includes('Studio has no room'), `flagged with its area: ${words(section)}`);
  assert.ok(!deviceRowOf(section, 'Studio fan'), 'an unplaced device stays with its area, not listed here');
  assert.ok(!deviceRowOf(section, 'Shed lamp'), "another building's device is not this card's");
  assert.ok(descendants(row).some(n => n.classList?.contains('editor-device-grip')), 'it can be carried to a new spot');
  buttonNamed(row, 'Remove').click(); await settle();
  assert.deepEqual(commits, [{ op: 'unplace_device', device: 'd-hue' }], JSON.stringify(commits));
  abort.abort();
});

// M5: Blink after the session expired shows the signed-out notice alone.
check('m5_blink_signed_out_shows_one_notice', async () => {
  const body = linked();
  body.devices = [{ device_id: 'd-lamp', name: 'Den lamp', kind: 'light', area_id: 'kitchen' }];
  const { link, abort } = mount(body);
  await link.refresh();
  const realFetch = globalThis.fetch, realDispatch = window.dispatchEvent;
  window.dispatchEvent = () => true;
  globalThis.fetch = async (input, init = {}) => /identify/.test(String(input))
    ? { ok: false, status: 401, headers: { get: () => 'text/plain' }, text: async () => 'Unauthorized' }
    : realFetch(input, init);
  try {
    buttonNamed(deviceRowOf(link.roomSection(BUILDING.rooms[0]), 'Den lamp'), 'Blink').click(); await settle();
    assert.equal(alerts.length, 1, `one notice: ${JSON.stringify(alerts)}`);
    assert.ok(!alerts.includes('Could not blink that light.'), 'no second, misleading alert');
    // A real failure still says so.
    alerts.length = 0;
    globalThis.fetch = async () => ({ ok: false, status: 502, headers: { get: () => 'application/json' },
      text: async () => '{"detail": "upstream"}' });
    buttonNamed(deviceRowOf(link.roomSection(BUILDING.rooms[0]), 'Den lamp'), 'Blink').click(); await settle();
    assert.deepEqual(alerts, ['Could not blink that light.']);
  } finally { globalThis.fetch = realFetch; window.dispatchEvent = realDispatch; abort.abort(); }
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
