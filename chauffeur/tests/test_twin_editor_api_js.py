"""The house editor's polling helper follows a build chain (plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1b-i.md Task 8,
amendment A11): when a polled build is done and carries `next`, the poller
itself switches to `next` after the current poll completes, so the editor
never awaits follow() from inside onBuild (which would wait on its own
pending poll forever).

Runs the REAL createPolling from static/twin/editor/api.js under node (copied
to a temp .mjs). Only the transport is stubbed: a fake fetch answers the
editor routes, so the real request() runs. /state never names a build, so the
only way to reach the next build is through `next`. Every wait is
timeout-guarded. Skips when node is unavailable.

Run from chauffeur/:  python tests/test_twin_editor_api_js.py
"""
import json
import os
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, 'static', 'twin', 'editor', 'api.js')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


DRIVER = r"""
const job = JSON.parse(process.argv[2]);
const log = [], seen = [], errors = [];
globalThis.window = { chfBase: '/', showGlobalAlert() {}, dispatchEvent() {}, promptConfirm: async () => false };
globalThis.document = { hidden: false };
globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
const counts = {};
const reply = (status, body) => ({ ok: status < 400, status, text: async () => JSON.stringify(body) });
globalThis.fetch = async (url) => {
  const path = String(url).replace(/^\/api\/house\/editor\//, '');
  log.push(path);
  if (path === 'state') return reply(200, { build: null, plan: null, rounds: [], cost: { total: 0 } });
  const m = path.match(/^build\/([^?]+)\?since=(\d+)$/);
  const list = m && job.builds[m[1]];
  if (!list) return reply(404, { detail: 'No such build or round.' });
  const i = Math.min(counts[m[1]] || 0, list.length - 1);
  counts[m[1]] = (counts[m[1]] || 0) + 1;
  return reply(200, list[i]);
};
const guard = (promise, ms, what) => Promise.race([promise,
  new Promise((_, reject) => setTimeout(() => reject(new Error('timed out: ' + what)), ms))]);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const api = await import('./api.mjs');
const polling = api.createPolling({
  onState: async () => {},
  onBuild: async build => { seen.push(build.id); },
  onTick: async () => {},
  onError: error => { errors.push(String(error && error.message)); },
});
let failure = null;
try {
  await guard(polling.follow(job.follow), 5000, 'follow(' + job.follow + ')');
  const until = Date.now() + job.waitMs;
  while (Date.now() < until && !(job.expect && log.some(p => p.startsWith('build/' + job.expect + '?')))) await sleep(50);
  if (!job.expect) await sleep(job.waitMs);
} catch (error) { failure = String(error.message); }
polling.stop();
console.log(JSON.stringify({ log, seen, errors, failure }));
process.exit(0);
"""


def run(job):
    d = tempfile.mkdtemp(prefix='twin_editor_api_js_')
    shutil.copy(MODULE, os.path.join(d, 'api.mjs'))
    with open(os.path.join(d, 'driver.mjs'), 'w', encoding='utf-8') as f:
        f.write(DRIVER)
    out = subprocess.run([shutil.which('node'), os.path.join(d, 'driver.mjs'), json.dumps(job)],
                         capture_output=True, text=True, timeout=60, cwd=d)
    if out.returncode != 0:
        raise AssertionError(out.stderr[-2000:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def _build(bid, state, nxt=None, seq=3):
    return {'id': bid, 'state': state, 'steps': [], 'events': [], 'seq': seq, 'pause': None, 'next': nxt}


def _builds_read(result):
    return [p for p in result['log'] if p.startswith('build/')]


def scenario_a_done_build_with_next_is_followed_by_the_poller():
    r = run({'follow': 'b1', 'expect': 'b2', 'waitMs': 3000,
             'builds': {'b1': [_build('b1', 'done', 'b2', seq=7)], 'b2': [_build('b2', 'running', seq=1),
                                                                          _build('b2', 'done', seq=2)]}})
    check(r['failure'] is None, ('follow resolves; no deadlock', r))
    reads = _builds_read(r)
    check(reads and reads[0] == 'build/b1?since=0', ('the followed build is read first', reads))
    check('build/b2?since=0' in reads, ('the poller fetches build/b2 next, from its own start', reads))
    check(reads.index('build/b2?since=0') > reads.index('build/b1?since=0'), reads)
    check(r['seen'][:2] == ['b1', 'b2'], ('onBuild sees b1, then b2', r['seen']))
    check(not r['errors'], r['errors'])


def scenario_a_chain_is_followed_link_by_link():
    r = run({'follow': 'b1', 'expect': 'b3', 'waitMs': 5000,
             'builds': {'b1': [_build('b1', 'done', 'b2')], 'b2': [_build('b2', 'done', 'b3')],
                        'b3': [_build('b3', 'done')]}})
    check(r['failure'] is None, r)
    reads = _builds_read(r)
    for bid in ('b1', 'b2', 'b3'):
        check(f'build/{bid}?since=0' in reads, (bid, reads))
    check([s for i, s in enumerate(r['seen']) if s not in r['seen'][:i]] == ['b1', 'b2', 'b3'], r['seen'])
    check(not r['errors'], r['errors'])


def scenario_a_done_build_without_next_is_not_followed_further():
    r = run({'follow': 'b1', 'expect': None, 'waitMs': 1500, 'builds': {'b1': [_build('b1', 'done')]}})
    check(r['failure'] is None, r)
    check(set(_builds_read(r)) == {'build/b1?since=0'}, ('nothing else is read', r['log']))
    check(not r['errors'], r['errors'])


if __name__ == '__main__':
    if not shutil.which('node'):
        print('  ..  skipped (node not available)')
    else:
        for fn in (scenario_a_done_build_with_next_is_followed_by_the_poller,
                   scenario_a_chain_is_followed_link_by_link,
                   scenario_a_done_build_without_next_is_not_followed_further):
            fn()
            print('  ok ', fn.__name__)
