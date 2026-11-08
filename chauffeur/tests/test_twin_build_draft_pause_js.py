"""Run the actual pause card under node: draft failures offer Try again."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1] / 'static' / 'twin' / 'editor'
DRIVER = r'''
import assert from 'node:assert/strict';
import { createPauses } from './pauses.mjs';
import { createPanel } from './panel.mjs';
const elements = new Map();
const node = () => ({ hidden: false, style: {}, dataset: {}, listeners: {}, children: [],
  offsetWidth: 300, offsetHeight: 200, value: '', textContent: '',
  setAttribute() {}, replaceChildren() { this.children = []; }, querySelectorAll: () => [],
  querySelector: () => node(), append(child) { child.parent = this; this.children.push(child); },
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); },
  addEventListener(event, fn) { this.listeners[event] = fn; } });
const el = id => {
  if (!elements.has(id)) elements.set(id, node());
  return elements.get(id);
};
globalThis.document = { getElementById: el, createElement: node };
globalThis.window = { chfBase: '/', promptConfirm: async () => true };
const requests = [];
globalThis.fetch = async (url, options) => {
  requests.push({ url, body: JSON.parse(options.body) });
  return { ok: true, text: async () => '{}' };
};
const view = { plan: { buildings: [{ id: 'house', levels: [{ id: 'L1', elevation: 0 }] }] },
  groups: { levels: {} }, renderer3: { domElement: {
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 1000, bottom: 800 }) } } };
let build = { id: 'b1', part: 'house', state: 'paused', events: [],
  steps: [{ id: 'draft', kind: 'draft', label: 'Reading the drawings' }],
  pause: { kind: 'draft', step: 'draft', registration: null,
    why: 'The drawings could not be read as one building.' } };
const pauses = createPauses({ view, getBuild: () => build, getGhost: () => null,
  getSheets: () => ({ page_roles: [] }), refresh: async () => {}, canEdit: () => true,
  signal: new AbortController().signal });
pauses.sync();
assert.equal(el('pause-card').hidden, false);
assert.equal(el('pause-reread').textContent, 'Try again');
assert.equal(el('pause-accept').hidden, true);
assert.equal(el('pause-drag').hidden, true);
assert.doesNotMatch(el('pause-reason').textContent, /unsure/i);
assert.equal(el('pause-reason').textContent, build.pause.why);
await el('pause-reread').listeners.click();
assert.deepEqual(requests, [{ url: '/api/house/editor/build/b1/reread', body: { step: 'draft' } }]);
build = { ...build, pause: { kind: 'lot_placement', step: 'fit', transform: { position: [0, 0], rotation: 0 } },
  steps: [{ id: 'fit', label: 'Placement' }] };
pauses.sync();
assert.equal(el('pause-accept').hidden, false);
assert.equal(el('pause-drag').hidden, false);
assert.match(el('pause-reread').textContent, /Re-read/);
assert.match(el('pause-reason').textContent, /I am unsure/);
const panel = createPanel({ afterSay: async () => {} });
const firstLook = 'First look at the outline while the drawings are read.';
const events = [];
for (let i = 0; i < 4; i++) {
  events.push({ seq: 2 * i + 1, type: 'ghost', step: 'draft', piece: { id: `draft-outline:${i}` }, why: firstLook });
  events.push({ seq: 2 * i + 2, type: 'log', step: 'draft', text: firstLook });
  panel.events({ id: 'b2', state: 'running', events: [...events] });
  assert.deepEqual(el('editor-log').children.map(row => row.textContent), [firstLook]);
  assert.ok(el('editor-log').children.every(row => !row.textContent.includes('need checking')));
}
events.push({ seq: 9, type: 'ghost', step: 'walls:L1', piece: { id: 'wall:1' }, why: 'Wall ends are apart.' });
panel.events({ id: 'b2', state: 'running', events });
assert.equal(el('editor-log').children[1].textContent, '1 wall needs checking: apart');
events.push({ seq: 10, type: 'settled', step: 'draft' });
panel.events({ id: 'b2', state: 'running', events });
assert.deepEqual(el('editor-log').children.map(row => row.textContent), ['1 wall needs checking: apart']);
console.log('2/2 passed (draft pause and first-look panel)');
'''

if __name__ == '__main__':
    if not shutil.which('node'):
        raise RuntimeError('node is required for the draft pause runtime check')
    work = Path(tempfile.mkdtemp(prefix='twin_draft_pause_js_'))
    for name in ('api', 'cards', 'snap', 'words', 'pauses', 'panel'):
        source = (ROOT / (name + '.js')).read_text(encoding='utf-8')
        (work / (name + '.mjs')).write_text(source.replace(".js'", ".mjs'"), encoding='utf-8')
    (work / 'driver.mjs').write_text(DRIVER, encoding='utf-8')
    result = subprocess.run(['node', str(work / 'driver.mjs')], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    print(result.stdout.strip())
