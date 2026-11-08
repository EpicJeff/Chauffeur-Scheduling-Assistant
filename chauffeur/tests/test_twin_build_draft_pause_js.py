"""Run the actual pause card under node: draft failures offer Try again."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1] / 'static' / 'twin' / 'editor'
DRIVER = r'''
import assert from 'node:assert/strict';
import { createPauses } from './pauses.mjs';
const elements = new Map();
const el = id => {
  if (!elements.has(id)) elements.set(id, { hidden: false, style: {}, dataset: {}, listeners: {},
    offsetWidth: 300, offsetHeight: 200, value: '', textContent: '',
    setAttribute() {}, replaceChildren() {}, querySelectorAll: () => [],
    addEventListener(event, fn) { this.listeners[event] = fn; } });
  return elements.get(id);
};
globalThis.document = { getElementById: el };
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
await el('pause-reread').listeners.click();
assert.deepEqual(requests, [{ url: '/api/house/editor/build/b1/reread', body: { step: 'draft' } }]);
build = { ...build, pause: { kind: 'lot_placement', step: 'fit', transform: { position: [0, 0], rotation: 0 } },
  steps: [{ id: 'fit', label: 'Placement' }] };
pauses.sync();
assert.equal(el('pause-accept').hidden, false);
assert.equal(el('pause-drag').hidden, false);
assert.match(el('pause-reread').textContent, /Re-read/);
console.log('1/1 passed');
'''

if __name__ == '__main__':
    if not shutil.which('node'):
        raise RuntimeError('node is required for the draft pause runtime check')
    work = Path(tempfile.mkdtemp(prefix='twin_draft_pause_js_'))
    for name in ('api', 'cards', 'snap', 'words', 'pauses'):
        source = (ROOT / (name + '.js')).read_text(encoding='utf-8')
        (work / (name + '.mjs')).write_text(source.replace(".js'", ".mjs'"), encoding='utf-8')
    (work / 'driver.mjs').write_text(DRIVER, encoding='utf-8')
    result = subprocess.run(['node', str(work / 'driver.mjs')], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    print(result.stdout.strip())
