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
from pathlib import Path
import re
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


def scenario_place_suggest_stays_enabled_for_unassigned_pages():
    """Run createPlace with a small DOM double; click Suggest and Confirm pages."""
    d = tempfile.mkdtemp(prefix='twin_place_js_')
    shutil.copy(os.path.join(ROOT, 'static', 'twin', 'editor', 'place.js'), os.path.join(d, 'place.mjs'))
    shutil.copy(MODULE, os.path.join(d, 'api.js'))
    with open(os.path.join(d, 'package.json'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'module'}, f)
    driver = r"""
import assert from 'node:assert/strict';
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.dataset = {}; this.attrs = {}; this.events = {}; this.style = {}; this.value = ''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) {
    this.attrs[key] = value;
    if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
  }
  getAttribute(key) { return this.attrs[key]; }
  addEventListener(name, fn) { this.events[name] = fn; }
  matches(selector) { return selector.split(',').some(s => s.trim().startsWith('[') ? s.trim().slice(1, -1) in this.attrs : s.trim() === this.tagName); }
  querySelectorAll(selector) { return this.children.flatMap(n => [ ...(n.matches(selector) ? [n] : []), ...n.querySelectorAll(selector)]); }
}
const els = new Map();
const get = id => { if (!els.has(id)) els.set(id, new Element()); return els.get(id); };
globalThis.document = { getElementById: get, createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag) };
globalThis.window = { promptConfirm: async () => true, showGlobalAlert: text => { throw new Error(text); } };
get('place-view').append(get('place-cards'));
const row = (page, building = 'home') => ({source: 'pdf', page, building, role: 'other', level: null, box: null});
const moved = row(2, 'garage');
let sheets = { sources: [{id: 'pdf', filename: 'shared.pdf', kind: 'drawing', pages: 3, part: 'home'}],
  page_roles: [moved], kinds: [], roles: {building: ['other'], lot: ['other']},
  place: {buildings: [{id: 'home', name: 'Home', kind: 'other', footprint: null},
                      {id: 'garage', name: 'Garage', kind: 'garage', footprint: null}], lot: {}, photo_tags: {}} };
let confirmed, placement;
const requests = [];
const {createPlace} = await import('./place.mjs');
const place = createPlace({ getSheets: () => sheets, canEdit: () => true, panel: {message() {}}, reload: async () => {}, follow: async () => {},
  request: async (path, method, body) => {
    requests.push(path);
    if (path === 'sheets/suggest') return {rows: [row(1), row(3)]};
    if (path === 'sheets/roles') { confirmed = body.rows; return {}; }
    if (path === 'place/lot/placement') { placement = body; return {}; }
    throw new Error(path);
  } });
place.sync(sheets, {});
const buttons = () => get('place-view').querySelectorAll('[data-place-suggest]');
assert.ok(buttons().length);
assert.ok(buttons().every(b => !b.disabled), 'a moved page must not disable suggestions for the remaining pages');
buttons()[0].events.click();
await new Promise(resolve => setImmediate(resolve));
get('place-confirm-pages').events.click();
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(requests, ['sheets/suggest', 'sheets/roles']);
assert.deepEqual(confirmed.find(r => r.page === 2), moved, 'keep the moved row');
assert.equal(confirmed.find(r => r.page === 1).building, 'home', 'keep the server assignment');
sheets = {...sheets, page_roles: confirmed};
place.sync(sheets, {});
assert.ok(buttons().every(b => b.disabled), 'a fully confirmed PDF needs no paid suggestion');
const outline = [[0,0], [40,0], [40,30], [0,30]];
sheets = {...sheets, place: {...sheets.place, lot: {
  placement: {outline, street_edge: [1,2], confirmed: true},
  read: {id: 'old', lot: outline, street_edge: [1,2]}
}}};
place.sync(sheets, {});
sheets = {...sheets, place: {...sheets.place, lot: {...sheets.place.lot,
  read: {id: 'new', lot: outline, street_edge: [2,3]}
}}};
place.sync(sheets, {});
get('place-confirm-placement').events.click();
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(placement.street_edge, [2,3], 'confirm must send the new read edge, never old placement indices');
console.log('ok');
"""
    path = os.path.join(d, 'place-driver.mjs')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(driver)
    result = subprocess.run([shutil.which('node'), path], capture_output=True, text=True, timeout=30, cwd=d)
    check(result.returncode == 0, result.stdout + result.stderr)


def scenario_shared_editor_chrome_survives_denied_storage():
    scripts = {}
    for name in ('control_center', 'admin_gate', 'panel_enrol'):
        source = (Path(ROOT) / 'templates/components' / (name + '.html')).read_text(encoding='utf-8')
        scripts[name] = re.findall(r'<script>(.*?)</script>', source, re.S)
    nav = (Path(ROOT) / 'templates/nav.html').read_text(encoding='utf-8')
    script = re.findall(r'<script>(.*?)</script>', nav, re.S)[-1]
    scripts['nav'] = [re.sub(r'{% for item in NAV_ITEMS %}.*?{% endfor %}', '', script, flags=re.S)]
    driver = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const scripts=JSON.parse(readFileSync(process.argv[2]));
for(const mode of ['getter','methods','available']) {
  const handlers=[], nodes=new Map();let reloads=0;
  const element=()=>({style:{},dataset:{},children:[],classList:{add(){},remove(){},toggle(){},contains(){return true;}},
    addEventListener(){},appendChild(){},querySelectorAll(){return [];},getBoundingClientRect(){return {height:0};},setAttribute(){},focus(){}});
  const get=id=>{if(id==='chat-input')return null;if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const context={console,URL,URLSearchParams,Headers,DOMException,
    location:{search:'',pathname:'/house/editor',origin:'http://localhost',reload(){reloads++;}},innerWidth:1600,
    document:{getElementById:get,querySelectorAll:()=>[],querySelector:()=>null,createElement:element,
      body:element(),documentElement:element(),addEventListener:(name,fn)=>{if(name==='DOMContentLoaded')handlers.push(fn);}},
    addEventListener(){},dispatchEvent(){},setTimeout(){},setInterval(){},clearTimeout(){},clearInterval(){},
    CustomEvent:class{},crypto:{randomUUID:()=> 'device'},
    fetch:async()=>({ok:true,status:200,json:async()=>({claimed:true,parents:[]})}),
    ensureMemberAuth:async()=>null};
  const data=new Map();
  const storage={getItem:k=>{if(mode==='methods')throw new DOMException('denied','SecurityError');return data.get(k)||null;},
    setItem:(k,v)=>{if(mode==='methods')throw new DOMException('denied','QuotaExceededError');data.set(k,v);},removeItem:k=>data.delete(k)};
  Object.defineProperty(context,'localStorage',{get(){if(mode==='getter')throw new DOMException('denied','SecurityError');return storage;}});
  context.window=context;vm.createContext(context);
  for(const name of ['admin_gate','control_center','panel_enrol'])for(const source of scripts[name])vm.runInContext(source,context,{filename:name+'.html'});
  for(const fn of handlers)await fn();
  // nav's real startup used to throw even on typeof localStorage.
  for(const source of scripts.nav)vm.runInContext(source,context,{filename:'nav.html'});
  context.toggleOperationsSidebar(false);
  context.chfStoreMemberToken('p1','pin-token');context.chfClearMemberToken('p1');
  assert.equal(await context.chfMemberToken({id:'p1',name:'Pat',has_pin:false}), '');
  assert.equal(await context.chfMemberToken({id:'p1',name:'Pat',has_pin:true}), null,'missing storage never bypasses a PIN');
  const panel=context.panelEnrol();panel.init();context.chfRequestPairing();
  const gate=context.adminGate();gate.store({token:'admin-token',member:{id:'p1'}});
  if(mode==='available') {assert.equal(reloads,1);assert.equal(context.chfAdminSession().token,'admin-token');}
  else {
    assert.equal(context.chfAdminSession(),null);assert.equal(panel.deviceId(),null);await panel.ask();
    assert.match(panel.error,/storage/);assert.equal(reloads,0);assert.match(gate.error,/storage/);
  }
}
console.log('ok shared chrome boots and its storage paths retain auth behavior under denied getters, denied methods and available storage');
"""
    paths = []
    try:
        for suffix, content in [('.mjs', driver), ('.json', json.dumps(scripts))]:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_storage_', delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run([shutil.which('node'), str(paths[0]), str(paths[1])], capture_output=True, text=True, timeout=20)
        check(result.returncode == 0, result.stdout + result.stderr)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    if not shutil.which('node'):
        print('  ..  skipped (node not available)')
    else:
        for fn in (scenario_shared_editor_chrome_survives_denied_storage,
                   scenario_place_suggest_stays_enabled_for_unassigned_pages,
                   scenario_a_done_build_with_next_is_followed_by_the_poller,
                   scenario_a_chain_is_followed_link_by_link,
                   scenario_a_done_build_without_next_is_not_followed_further):
            fn()
            print('  ok ', fn.__name__)
