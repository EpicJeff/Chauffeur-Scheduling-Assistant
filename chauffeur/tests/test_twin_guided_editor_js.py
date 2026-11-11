"""Run the real editor's event wiring and poll cadence without Chromium."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from test_twin_build_draft_pause_js import EDITOR_STUBS, EDITOR_DRIVER

ROOT = Path(__file__).resolve().parents[1] / 'static/twin/editor'
DRIVER = EDITOR_DRIVER.split('await boot();')[0] + r'''
location.search = '?test=1';
await boot();
assert.equal(window.__editor.ready, true, 'the real boot reaches ready');
const plan = {buildings: [{id: 'pool-house', levels: [], walls: []}], site: {}};
const piece = seq => ({type: 'piece', seq, step: 'draft', kind: 'wall', stage: 'walls', piece: {id: 'W' + seq}});
const build = {id: 'b', part: 'pool-house', state: 'running', steps: [{id: 'draft', status: 'running'}]};
await poll.onState({plan, rounds: [], cost: {total: .6, estimate: 1.5}, build: 'b'});
await poll.onBuild({...build, events: [piece(3)]}); await poll.onTick();
assert.deepEqual(window.__editor.buildGhosts.seqs(), [3], 'a tab joining a running read draws its first batch');
await poll.onBuild({...build, events: [piece(3), piece(4)]}); await poll.onTick();
assert.deepEqual(window.__editor.buildGhosts.seqs(), [3, 4], 'duplicate polls never duplicate ghosts');
assert.equal(chip.state, 'running'); assert.equal(chip.cost, .6); assert.equal(chip.estimate, 1.5);
await poll.onBuild({...build, state: 'stopped', stopping: true, events: []}); await poll.onTick();
assert.equal(window.__editor.buildGhosts.count(), 2, 'Stop keeps ghosts until the partial round arrives');
await poll.onState({plan, rounds: [{id: 1, kind: 'build', step: {id: 'draft'}, partial: true}],
  cost: {total: .9, estimate: null}, build: 'b'});
await poll.onBuild({...build, state: 'stopped', stopping: false, events: []}); await poll.onTick();
assert.equal(window.__editor.buildGhosts.count(), 0, 'the partial round settles the ghosts');
assert.equal(chip.state, 'stopped'); assert.equal(chip.cost, .9); assert.equal(chip.estimate, null);
// Old partial rounds cannot settle a fresh read of the same step.
await poll.onBuild({...build, events: [{type: 'stream_reset', step: 'draft'}, piece(8)]}); await poll.onTick();
assert.deepEqual(window.__editor.buildGhosts.seqs(), [8]);
await poll.onBuild({...build, events: [{type: 'stream_reset', step: 'draft'}, piece(10)]}); await poll.onTick();
assert.deepEqual(window.__editor.buildGhosts.seqs(), [10], 'fallback resets abandoned whole-read ghosts');
console.log('1/1 passed (editor event wiring, late tab, Stop, partial round, reread and spend)');
'''
API_DRIVER = r'''
import assert from 'node:assert/strict';
globalThis.window = {chfBase: '/'}; globalThis.document = {hidden: false};
let build = {id: 'b', state: 'running', streaming: true, seq: 1, events: []};
globalThis.fetch = async url => ({ok: true, text: async () => JSON.stringify(
  url.endsWith('/state') ? {build: 'b'} : build)});
const {createPolling} = await import('./api.mjs');
const polling = createPolling({onState() {}, onBuild() {}, onTick() {}, onError(e) {throw e;}});
await polling.follow('b'); assert.equal(polling.currentInterval(), 500, 'live pieces poll at 500 ms');
build = {...build, state: 'stopped', streaming: false, stopping: true};
await polling.pollNow(); assert.equal(polling.currentInterval(), 500, 'finish the Stop grace and publish before going idle');
build = {...build, stopping: false};
await polling.pollNow(); assert.equal(polling.currentInterval(), 60000, 'settled stopped builds go idle');
polling.stop();
console.log('1/1 passed (streaming and stopping cadence)');
'''


if __name__ == '__main__':
    if not shutil.which('node'):
        raise RuntimeError('node is required')
    with tempfile.TemporaryDirectory(prefix='twin_guided_editor_js_') as directory:
        work = Path(directory)
        source = re.sub(r"from '[^']+'", "from './editor-stubs.mjs'", (ROOT / 'editor.js').read_text(encoding='utf-8'))
        (work / 'editor.mjs').write_text(source, encoding='utf-8')
        stubs = EDITOR_STUBS.replace('export const createBuildGhosts = () =>', 'export const unusedBuildGhosts = () =>')
        stubs = stubs.replace('export const createStatusChip = () =>', 'export const unusedStatusChip = () =>')
        stubs += r'''
export const createStatusChip = () => ({update(v) {globalThis.chip = v;}});
export const createBuildGhosts = () => {
  const pieces = new Map();
  return {add(e) {pieces.set(e.seq, e);}, clear(step) {for (const [s, e] of pieces) if (!step || e.step === step) pieces.delete(s);},
    sync() {}, count: () => pieces.size, seqs: () => [...pieces.keys()],
    settle(r) {for (const [s,e] of pieces) if (e.step === r.step?.id) pieces.delete(s);}};
};
'''
        (work / 'editor-stubs.mjs').write_text(stubs, encoding='utf-8')
        (work / 'api.mjs').write_text((ROOT / 'api.js').read_text(encoding='utf-8'), encoding='utf-8')
        for name, driver in [('editor-driver', DRIVER), ('api-driver', API_DRIVER)]:
            (work / f'{name}.mjs').write_text(driver, encoding='utf-8')
            result = subprocess.run(['node', str(work / f'{name}.mjs')], capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            print(result.stdout.strip())
    print('2/2 passed')
