"""Execute the real Houses panel, request helper and Undo history in node."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r'''
import assert from 'node:assert/strict';
class El {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.listeners = {}; this.dataset = {}; this.hidden = false; this.disabled = false; this._text = ''; this.files = []; }
  append(...nodes) { this.children.push(...nodes); nodes.forEach(n => n.parent = this); }
  replaceChildren(...nodes) { this.children = []; this._text = ''; this.append(...nodes); }
  get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async fire(type, event = {}) { for (const fn of this.listeners[type] || []) await fn(event); }
  click() { if (!this.disabled) return this.fire('click'); }
  querySelectorAll(selector) { return this.children.flatMap(n => [n, ...n.querySelectorAll(selector)]).filter(n => selector === 'button' && n.tagName === 'button'); }
  focus() { document.activeElement = this; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); }
}
const ids = new Map(), node = id => { if (!ids.has(id)) ids.set(id, new El(id.includes('panel') || id.includes('list') ? 'div' : 'button')); return ids.get(id); };
globalThis.document = new El(); document.body = new El();
document.createElement = tag => new El(tag); document.getElementById = node; document.querySelector = () => null;
const panel = node('houses-panel'); panel.hidden = true;
panel.append(node('houses-close'), node('houses-save'), node('houses-download-current'), node('houses-upload'), node('houses-list'));
const prompts = [], confirms = [], alerts = [], calls = [];
let answer = 'Safe point', confirmed = true, rows = [], round = 2, performCount = 0, loaded = 0;
globalThis.window = {chfBase: '/ingress/token/', showGlobalAlert: x => alerts.push(x),
  promptInput: async (...args) => { prompts.push(args); return answer; },
  promptConfirm: async (...args) => { confirms.push(args); return confirmed; },
  alert() { throw Error('browser alert banned'); }, confirm() { throw Error('browser confirm banned'); }, prompt() { throw Error('browser prompt banned'); }};
const saved = {id: 'a'.repeat(32), name: 'Before <experiment>', created_at: '2026-11-13T12:00:00Z', created_by: 'mum', size: 4096, summary: {building_count: 2, room_count: 5}, thumbnail: null};
const portable = {format: 'chauffeur-house', format_version: 1, name: saved.name, model: {}};
globalThis.fetch = async (url, options) => {
  assert.ok(url.startsWith('/ingress/token/api/house/'), 'all requests keep the ingress prefix');
  const path = url.replace('/ingress/token/api/house/', ''); calls.push({path, ...options});
  let result = {};
  if (path === 'editor/houses' && options.method === 'GET') result = {saves: rows};
  if (path === 'editor/houses' && options.method === 'POST') { rows = [saved]; result = {save: saved}; }
  if (path.endsWith('/load')) { round = 3; result = {round, notes: ['Reset invalid field.']}; }
  if (path === 'twin/revert') { round = 4; result = {round}; }
  if (path.endsWith('/download')) result = portable;
  if (path === 'editor/houses/upload') { rows = [saved]; result = {save: saved, notes: []}; }
  if (options.method === 'DELETE') rows = [];
  return {ok: true, text: async () => JSON.stringify(result)};
};
const {createHistory} = await import('./history.mjs');
const {mountHouses} = await import('./houses.mjs');
let current = 2;
const history = createHistory({getRound: () => current, getBuild: () => null, canEdit: () => true,
  refresh: async () => {current = round;}, signal: new AbortController().signal});
const originalPerform = history.perform;
history.perform = work => {performCount++; return originalPerform(work);};
let canLoad = true;
const ui = mountHouses({history, afterLoad: async () => {loaded++; current = round;},
  capture: async () => 'data:image/png;base64,test', canLoad: () => canLoad, signal: new AbortController().signal});
const flush = async () => {for (let i = 0; i < 30; ++i) await Promise.resolve();};
const press = async id => {await node(id).click(); await flush();};
const action = label => node('houses-list').querySelectorAll('button').find(b => b.textContent === label);
let count = 0;
await press('editor-houses');
assert.equal(panel.hidden, false); assert.match(node('houses-status').textContent, /No saved houses/); count++;
await press('houses-save');
assert.equal(prompts.length, 1); assert.match(prompts[0][0], /Save current house/);
assert.equal(calls.filter(c => c.method === 'POST' && c.path === 'editor/houses').length, 1);
assert.deepEqual(JSON.parse(calls.find(c => c.method === 'POST').body), {name: answer, thumbnail: 'data:image/png;base64,test'});
assert.match(node('houses-list').textContent, /Before <experiment>/); assert.match(node('houses-list').textContent, /2 buildings · 5 rooms/); count++;
answer = null; await press('houses-save');
assert.equal(calls.filter(c => c.method === 'POST' && c.path === 'editor/houses').length, 1); count++;
confirmed = false; await action('Load').click(); await flush(); assert.equal(loaded, 0); count++;
confirmed = true; await action('Load').click(); await flush();
assert.match(confirms.at(-1)[1], /back with Undo/); assert.equal(loaded, 1); assert.equal(performCount, 1);
assert.equal(calls.filter(c => c.path.endsWith('/load')).length, 1);
assert.deepEqual(alerts, ['Reset invalid field.']); assert.equal(panel.hidden, true);
assert.equal(node('rail-undo').disabled, false); count++;
await press('rail-undo');
assert.equal(JSON.parse(calls.find(c => c.path === 'twin/revert').body).round, 2); assert.equal(current, 4); count++;
await press('editor-houses'); answer = 'New name'; await action('Rename').click(); await flush();
assert.deepEqual(JSON.parse(calls.find(c => c.method === 'PATCH').body), {name: 'New name'}); count++;
confirmed = false; await action('Delete').click(); await flush(); assert.ok(action('Load'));
confirmed = true; await action('Delete').click(); await flush(); assert.equal(rows.length, 0); count++;
const links = []; const create = document.createElement;
document.createElement = tag => {const n = create(tag); if (tag === 'a') links.push(n); return n;};
await press('houses-download-current'); assert.equal(links.length, 1); assert.match(links[0].download, /\.chauffeur-house\.json$/); count++;
node('houses-file').files = [new File(['{}'], 'house.json')]; await node('houses-file').fire('change'); await flush();
assert.ok(calls.find(c => c.path === 'editor/houses/upload').body instanceof FormData);
assert.match(node('houses-status').textContent, /Choose Load/); assert.equal(loaded, 1); count++;
canLoad = false; ui.sync(); assert.equal(action('Load').disabled, true); count++;
let resolve; window.promptInput = () => new Promise(r => {resolve = r;});
const first = node('houses-save').click(); await flush(); await node('houses-save').click(); resolve(null); await first; await flush();
assert.equal(calls.filter(c => c.method === 'POST' && c.path === 'editor/houses').length, 1); count++;
console.log(`${count}/${count} passed (real Houses panel, API, and Undo)`);
'''


def run():
    node = shutil.which('node')
    if not node:
        raise RuntimeError('node is required')
    with tempfile.TemporaryDirectory(prefix='house_saves_js_') as folder:
        work = Path(folder)
        for module in ('houses', 'history', 'api'):
            source = (ROOT / f'static/twin/editor/{module}.js').read_text(encoding='utf-8')
            (work / f'{module}.mjs').write_text(source.replace("'./api.js'", "'./api.mjs'"), encoding='utf-8')
        (work / 'driver.mjs').write_text(DRIVER, encoding='utf-8')
        result = subprocess.run([node, str(work / 'driver.mjs')], capture_output=True, text=True, timeout=30)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
        return result.returncode


if __name__ == '__main__':
    sys.exit(run())
