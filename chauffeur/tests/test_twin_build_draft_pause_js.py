"""Run the actual pause card under node: draft failures offer Try again."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import re

ROOT = Path(__file__).resolve().parents[1] / 'static' / 'twin' / 'editor'
DRIVER = r'''
import assert from 'node:assert/strict';
import { createPauses } from './pauses.mjs';
import { createPanel } from './panel.mjs';
const elements = new Map();
const node = () => ({ hidden: false, style: {}, dataset: {}, listeners: {}, children: [],
  offsetWidth: 300, offsetHeight: 200, value: '', textContent: '',
  setAttribute() {}, before() {}, replaceChildren() { this.children = []; }, querySelectorAll: () => [],
  querySelector: () => node(), append(child) { child.parent = this; this.children.push(child); },
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); },
  addEventListener(event, fn) { this.listeners[event] = fn; } });
const el = id => {
  if (!elements.has(id)) elements.set(id, node());
  return elements.get(id);
};
globalThis.document = { getElementById: el, createElement: node };
const confirms = [];
globalThis.window = { chfBase: '/', promptConfirm: async (...args) => { confirms.push(args); return true; } };
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
assert.equal(confirms[0][0], 'Read the drawings again?');
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
for (const state of ['paused', 'stopped', 'failed']) {
  const pause = { kind: 'draft', step: 'draft', why: 'The drawings could not be read as one building.' };
  panel.events({ id: `cleanup-${state}`, state, pause: state === 'paused' ? pause : null,
    events: [{ seq: 1, type: 'ghost', step: 'draft', piece: { id: 'draft-outline:1' }, why: firstLook },
      { seq: 2, type: 'question', step: 'draft', text: pause.why }] });
  assert.equal(el('editor-log').children.length, 0, state);
  if (state === 'paused') {
    const text = el('editor-messages').children.at(-1).textContent;
    assert.equal(text.split(pause.why).length - 1, 1);
    assert.match(text, /Try again.*Stop/);
    assert.doesNotMatch(text, /Drag|Looks right|unsure/);
    assert.ok(!el('editor-quick-replies').children.some(n => n.textContent === 'Keep going'));
  }
}
panel.events({ id: 'upper-failure', state: 'running', events: [
  ...['wall:1', 'wall:2', 'L2'].map((id, i) => ({ seq: i + 1, type: 'ghost', step: 'draft',
    piece: { id }, why: 'The upper floor extends more than 2 ft beyond the floor below.' }))] });
assert.equal(el('editor-log').children.length, 1);
assert.match(el('editor-log').children[0].textContent, /^3 pieces need checking:/);
const reasons = [
  ['roof', 'This porch roof has no porch or columns beneath it.', 'These porch roofs have no porch or columns beneath them'],
  ['roof', 'This roof section does not meet its bearing walls within 3 ft.', 'These roof sections do not meet their bearing walls within 3 ft'],
  ['opening', 'This opening extends beyond its wall span or height.', 'These openings extend beyond their wall span or height'],
  ['room', "This room extends outside its floor's outline.", "These rooms extend outside their floors' outlines"],
  ['wall', "This wall extends outside its floor's outline.", "These walls extend outside their floors' outlines"],
  ['L2', 'The upper floor extends more than 2 ft beyond the floor below.', 'The upper floors extend more than 2 ft beyond the floors below'],
  ['L2', 'The upper floor is less than a fifth of the floor below.', 'The upper floors are less than a fifth of the floors below'],
  ['wall', "This floor's exterior walls do not close.", "These floors' exterior walls do not close"],
  ['opening', 'No replacement wall is within 1 ft of this opening.', 'No replacement wall is within 1 ft of these openings'],
  ['opening', 'The opening was clamped to the replacement wall span.', 'The openings were clamped to the replacement wall span'],
  ['opening', 'There is no wall on this floor.', 'There is no wall on these floors'],
];
for (const [kind, why, plural] of reasons) {
  const events = [0, 1].map(i => ({ seq: i + 1, type: 'ghost', step: 'draft', piece: { id: `${kind}:${i}` }, why }));
  panel.events({ id: why, state: 'running', events: events.slice(0, 1) });
  const singular = el('editor-log').children[0].textContent;
  assert.match(singular, new RegExp(`^1 ${kind === 'roof' ? 'roof section' : kind === 'L2' ? 'piece' : kind} needs checking:`));
  panel.events({ id: why, state: 'running', events });
  const noun = kind === 'roof' ? 'roof sections' : kind === 'L2' ? 'pieces' : `${kind}s`;
  assert.equal(el('editor-log').children[0].textContent, `2 ${noun} need checking: ${plural}`);
  panel.events({ id: why, state: 'running', events });
  assert.equal(el('editor-log').children.length, 1);
}
console.log('6/6 passed (draft pause, reread wording, first look, cleanup, one reason summary, plural reasons)');
'''

EDITOR_STUBS = r'''
export const session = { signedOut: false }, idleInterval = 60000, buildInterval = 1000;
export const plain = String, active = b => ['running', 'paused', 'checkpoint'].includes(b?.state);
export const report = e => { throw e; }, checkpoint = async () => true;
export const request = async path => path === 'sheets' ? globalThis.sheets : {};
export function createPolling(config) {
  globalThis.poll = config;
  return { refreshState: async () => {}, resume: async () => {}, stop() {}, follow: async () => {}, pollNow: async () => {} };
}
export const mountTwin = async () => ({ scene: {}, rebuild: async p => { globalThis.rendered = p; } });
export const runDirector = async () => {};
export const createPanel = () => ({ message() {}, readOnly() {}, events() {}, reset() {} });
const tools = { refresh() {}, drawFloors() {}, delegate() {}, selected() {}, dragging: () => false };
export const createSceneTools = () => tools;
export const createHistory = () => ({ perform: action => action(), sync() {}, clear() {} });
export const createDraw = () => ({ cancel() {} });
export const createLotTools = () => ({ dragging: () => false });
export const streetView = () => null, streetSegment = () => null;
export const createRoofTools = () => ({ cancel() {}, addDormer() {},
  pointerDown: () => false, pointerMove: () => false, pointerUp: () => false });
export const createLibrary = () => ({ refresh() {}, pick: () => false, pickSite: () => false,
  pointerDown: () => false, pointerMove: () => false, pointerUp: () => false });
export const createFlags = () => ({ refresh() {}, pick: () => null, flags: () => ({}), proposals: () => [] });
export const createPlanView = () => ({});
export const createPauses = () => ({ sync() {}, current: () => null, dismissed: () => false });
export const applyRegistration = (_, p) => p, invertRegistration = (_, p) => p;
export const createTimeline = () => ({ sync() {}, preview: () => null });
export const createPlace = () => ({ sync() {}, isOpen: () => false });
'''

EDITOR_DRIVER = r'''
import assert from 'node:assert/strict';
import { boot } from './editor.mjs';
const elements = new Map();
const node = () => ({ hidden: false, dataset: {}, style: {}, children: [],
  textContent: '', addEventListener() {}, querySelector: () => node(), querySelectorAll: () => [],
  append() {}, setAttribute() {}, replaceChildren() {} });
globalThis.document = { getElementById: id => {
  if (!elements.has(id)) elements.set(id, node()); return elements.get(id);
}, addEventListener() {}, createElement: node };
globalThis.window = { addEventListener() {} };
globalThis.location = { search: '' };
globalThis.sheets = { sources: [], page_roles: [], place: { buildings: [{ id: 'pool-house' }] } };
await boot();
const plan = { buildings: [
  { id: 'house', position: [1, 2], rotation: 0, levels: [] },
  { id: 'pool-house', position: [60, 80], rotation: 37, levels: [] }
], site: {} };
const first = { seq: 1, step: 'draft', type: 'ghost',
  why: 'First look at the outline while the drawings are read.',
  piece: { id: 'draft-outline:0', outline: [[0, 0], [10, 0], [10, 10]] } };
for (const state of ['paused', 'stopped', 'failed']) {
  const build = { id: state, part: 'pool-house', state: 'running', events: [first],
    steps: [{ id: 'draft', kind: 'draft', status: 'running' }] };
  await poll.onState({ plan, rounds: [], build: state });
  await poll.onBuild(build); await poll.onTick();
  let ghost = rendered.buildings.find(b => b.id.startsWith('editor-preview:'));
  assert.deepEqual(ghost.position, [60, 80]); assert.equal(ghost.rotation, 37);
  await poll.onBuild({ ...build, state }); await poll.onTick();
  assert.ok(!rendered.buildings.some(b => b.id.startsWith('editor-preview:')), state);
}
console.log('3/3 passed (whole-place first-look owner and pause/stop/failure cleanup)');
'''

PLACE_DRIVER = r'''
import assert from 'node:assert/strict';
import { createPlace } from './place.mjs';
const all = [], elements = new Map();
const node = () => {
  const n = { hidden: false, value: '', dataset: {}, children: [], listeners: {}, style: {},
    setAttribute(k, v) { if (k.startsWith('data-')) this.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v; },
    replaceChildren(...children) { this.children = children; }, append(...children) { this.children.push(...children); },
    querySelectorAll: () => [], querySelector: () => node(), focus() {},
    addEventListener(k, fn) { this.listeners[k] = fn; } };
  all.push(n); return n;
};
const el = id => { if (!elements.has(id)) elements.set(id, node()); return elements.get(id); };
globalThis.document = { getElementById: el, createElement: node, querySelector: () => ({ children: [] }) };
const confirms = [];
globalThis.window = { promptConfirm: async (...args) => { confirms.push(args); return false; } };
const sheets = { kinds: [], sources: [{ id: 'doc', part: 'house', kind: 'drawing', pages: 1 }],
  page_roles: [{ source: 'doc', page: 1, role: 'floor', level: 'Main floor', building: 'house', box: null }],
  estimates: { build: { house: { total: 1.4 }, pool: { total: .8 } } }, lot_build_estimate: .2,
  place: { buildings: [{ id: 'house', name: 'Main house' }, { id: 'pool', name: 'Pool house',
    shell: { storeys: 1, ceiling: 9, roof: 'gable', pitch: 6 } }], lot: {}, photo_tags: {} } };
const place = createPlace({ request: async () => { throw Error('cancelled confirm must not start a build'); },
  getSheets: () => sheets, reload: async () => {}, follow() {}, canEdit: () => true, panel: {} });
place.sync(sheets, {});
await all.find(n => n.dataset.placeBuild === 'house').listeners.click();
assert.match(confirms.at(-1)[1], /Main house drawings and photos, about \$1\.40 at most/);
await el('place-build').listeners.click();
assert.match(confirms.at(-1)[1], /your place, about \$2\.40 at most/);
await all.find(n => n.dataset.placeBuild === 'lot').listeners.click();
assert.match(confirms.at(-1)[1], /lot drawings, about \$0\.20 at most/);
console.log('3/3 passed (building, whole-place and lot pre-build estimates)');
'''

if __name__ == '__main__':
    if not shutil.which('node'):
        raise RuntimeError('node is required for the draft pause runtime check')
    work = Path(tempfile.mkdtemp(prefix='twin_draft_pause_js_'))
    # cards now shares contains with the generator. Load that real dependency
    # and its vendored three.js imports; keep the assertions below unchanged.
    loader = work / 'loader.mjs'
    twin = ROOT.parent.as_uri()
    vendor = (ROOT.parents[1] / 'vendor' / 'three-r187').as_uri()
    loader.write_text(f"""
import {{registerHooks}} from 'node:module';
registerHooks({{resolve(spec, ctx, next) {{
  if (spec === '../twin_generator.mjs') return {{url: '{twin}/twin_generator.js', shortCircuit: true}};
  if (spec === 'three') return {{url: '{vendor}/three.module.js', shortCircuit: true}};
  if (spec.startsWith('three/addons/')) return {{url: '{vendor}/addons/' + spec.slice(13), shortCircuit: true}};
  return next(spec, ctx);
}}, load(url, ctx, next) {{
  return url.startsWith('{twin}/') && url.endsWith('.js')
    ? {{...next(url, {{...ctx, format:'module'}}), format:'module'}} : next(url, ctx);
}}}});
""", encoding='utf-8')
    for name in ('api', 'cards', 'snap', 'words', 'pauses', 'panel', 'place'):
        source = (ROOT / (name + '.js')).read_text(encoding='utf-8')
        (work / (name + '.mjs')).write_text(source.replace(".js'", ".mjs'"), encoding='utf-8')
    # cards names library's material lines; the library itself loads three.js
    # assets the pause card never uses, so it is stubbed like the editor's.
    (work / 'library.mjs').write_text('export const materialLines = () => [];\n', encoding='utf-8')
    (work / 'driver.mjs').write_text(DRIVER, encoding='utf-8')
    result = subprocess.run(['node', '--import', loader.as_uri(), str(work / 'driver.mjs')], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    print(result.stdout.strip())
    source = (ROOT / 'editor.js').read_text(encoding='utf-8')
    source = re.sub(r"from '[^']+'", "from './editor-stubs.mjs'", source)
    (work / 'editor.mjs').write_text(source, encoding='utf-8')
    (work / 'editor-stubs.mjs').write_text(EDITOR_STUBS, encoding='utf-8')
    for name, driver in [('editor-driver', EDITOR_DRIVER), ('place-driver', PLACE_DRIVER)]:
        (work / (name + '.mjs')).write_text(driver, encoding='utf-8')
        result = subprocess.run(['node', '--import', loader.as_uri(), str(work / (name + '.mjs'))], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        print(result.stdout.strip())
