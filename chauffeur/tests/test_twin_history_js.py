"""Execute the History list and real HTTP helper, including cross-tab pruning."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r'''
import assert from 'node:assert/strict';
class El {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.listeners = {}; this.dataset = {}; this.attributes = {}; this.hidden = false; this.disabled = false; this._text = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  setAttribute(k, v) { this.attributes[k] = v; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async click() { if (!this.disabled) for (const fn of this.listeners.click || []) await fn(); }
}
const ids = new Map(), node = id => { if (!ids.has(id)) ids.set(id, new El()); return ids.get(id); };
globalThis.document = {createElement: tag => new El(tag), getElementById: node};
const alerts = [], calls = [], previews = [], renders = [];
globalThis.window = {chfBase: '/ingress/history/', showGlobalAlert: text => alerts.push(text)};
for (const key of ['alert', 'confirm', 'prompt']) window[key] = () => {throw Error('Browser dialog');};
let state = {current_round: 55, rounds: Array.from({length: 51}, (_, i) => ({id: i + 5, kind: i === 0 ? 'load' : 'edit', note: `Change ${i + 5}`})), cost: {total: 0}}, server = state;
let missing = false;
globalThis.fetch = async (url, options) => {
  assert.ok(url.startsWith('/ingress/history/api/house/'));
  const path = url.replace('/ingress/history/api/house/', '');
  calls.push({path, ...options});
  let status = 200, data = {};
  if (path.startsWith('twin/rounds/')) {
    if (missing) { status = 404; data = {detail: 'No such round'}; }
    else data = {plan: {id: Number(path.split('/').at(-1)), buildings: []}};
  }
  if (path === 'editor/state') data = structuredClone(server);
  if (path === 'twin/revert') {
    server = {...server, current_round: 56, rounds: [...server.rounds.slice(-49), {id: 56, kind: 'revert'}]};
  }
  return {ok: status === 200, status, text: async () => JSON.stringify(data)};
};
const {createTimeline} = await import('./timeline.mjs');
const abort = new AbortController();
const timeline = createTimeline({getState: () => state, render: async () => renders.push(timeline.preview()),
  onPreview: value => previews.push(value), signal: abort.signal});
const buttons = () => node('editor-history-list').children.map(li => li.children[0]);
const flush = async () => {for (let i = 0; i < 50; i++) await Promise.resolve();};
let count = 0;
timeline.sync();
assert.equal(buttons().length, 50); assert.equal(buttons()[0].dataset.round, 55);
assert.equal(buttons().at(-1).dataset.round, 6); assert.equal(buttons()[0].attributes['aria-current'], 'step');
assert.match(buttons()[0].textContent, /Change 55.*Current/); count++;
await buttons()[1].click(); await flush();
assert.equal(timeline.preview().id, 54); assert.equal(previews.at(-1), true);
assert.equal(node('editor-history').open, true); assert.equal(node('time-return').disabled, false);
assert.equal(node('time-chip').hidden, false); count++;
await node('time-now').click();
assert.equal(timeline.preview(), null); assert.equal(previews.at(-1), false); assert.equal(node('time-chip').hidden, true); count++;
await buttons()[1].click(); await flush();
// Another tab advances the window after selection. Return must keep the selected ID.
state.rounds = state.rounds.slice(1); timeline.sync();
await node('time-return').click();
assert.equal(JSON.parse(calls.find(c => c.path === 'twin/revert').body).round, 54);
assert.equal(state.current_round, 56); assert.equal(timeline.preview(), null); count++;
await timeline.scrubTo(timeline.roundCount() - 1);
assert.equal(node('time-return').disabled, true); count++;
await node('time-now').click();
const staleButton = buttons().at(-1), staleID = staleButton.dataset.round;
missing = true; server = {...state, rounds: state.rounds.slice(1)};
state.rounds = server.rounds;
// A poll can replace state while a slow scene redraw still leaves the old row visible.
await staleButton.click(); await flush();
assert.equal(calls.at(-2).path, `twin/rounds/${staleID}`);
assert.deepEqual(alerts, ['That step is no longer kept.']); assert.equal(timeline.preview(), null);
assert.equal(buttons().length, server.rounds.length); assert.equal(previews.at(-1), false); count++;
// Simulate a pruned return too: the API helper must report 404 to the list.
globalThis.fetch = async (url) => url.endsWith('/revert')
  ? {ok: false, status: 404, text: async () => JSON.stringify({detail: 'No such round'})}
  : {ok: true, text: async () => JSON.stringify(server)};
missing = false;
// Restore a preview with an explicit real round reply before refusing its return.
const originalFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => url.includes('/rounds/')
  ? {ok: true, text: async () => JSON.stringify({plan: {id: 7, buildings: []}})} : originalFetch(url, options);
await timeline.scrubTo(0); await node('time-return').click();
assert.equal(alerts.at(-1), 'That step is no longer kept.'); assert.equal(timeline.preview(), null); count++;
state = {rounds: [{id: 1, kind: 'start_over'}]}; timeline.sync();
assert.equal(buttons().length, 0); assert.match(node('editor-history-note').textContent, /one step at a time/); count++;
abort.abort();
console.log(`${count}/${count} passed (History list, preview, return, and pruned steps)`);
'''


def run():
    node = shutil.which('node')
    if not node:
        raise RuntimeError('node is required')
    with tempfile.TemporaryDirectory(prefix='history_js_') as folder:
        work = Path(folder)
        for module in ('timeline', 'api'):
            source = (ROOT / f'static/twin/editor/{module}.js').read_text(encoding='utf-8')
            (work / f'{module}.mjs').write_text(source.replace("'./api.js'", "'./api.mjs'")
                .replace("'../edit_timing.js'", "'./edit_timing.mjs'"), encoding='utf-8')
        (work / 'edit_timing.mjs').write_text((ROOT / 'static/twin/edit_timing.js').read_text(encoding='utf-8'), encoding='utf-8')
        (work / 'driver.mjs').write_text(DRIVER, encoding='utf-8')
        result = subprocess.run([node, str(work / 'driver.mjs')], capture_output=True, text=True, timeout=30)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
        return result.returncode


if __name__ == '__main__':
    sys.exit(run())
