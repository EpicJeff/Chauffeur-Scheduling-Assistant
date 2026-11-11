"""Checks one at a time, run under node with the real scene (plan
docs/superpowers/plans/2026-11-10-house-guided-build-piece-4.md, Task 8;
brief .superpowers/sdd/2026-11-10-house-guided-build-piece-4/task-8-brief.md).

static/twin/editor/checks.js exports createChecks(view, {api, ...}) ->
{queue(), current(), next()}. One queue holds a build pause, the model's flags
and its proposals; one check shows at a time, on the model, the camera on it.
Looks right answers a pause (accept) or a flag (flag_ok); a proposal shows Use
this and Dismiss instead; Fix it opens the piece and leaves the build waiting;
Skip for now moves on and keeps the item. A pause's re-read stays as
`Read it again · about $x.xx`.

The household's real model (tests/fixtures/twin_model/household-2026-11-09.json,
11 flags) is mounted in the real twin_view (CPU renderer doubles, as
tests/test_twin_flags_js.py does), plus one proposal on the pool house and a
paused build at its fit step (a lot_placement pause).

What this test assumes:
  - createChecks gets, besides view and api: getBuild, getModel, getPlan,
    tools (scene tools), panel, canEdit, signal, op. The test passes all of
    them; the module uses those it needs. When `signal` aborts, the module
    takes away what it drew (as flags.js does); each test starts a fresh one.
  - api.request(path, method, body) is the editor's request (path relative to
    api/house/editor/). A pause is answered with
    request('build/<id>/answer', 'POST', {step, decision: {accept: true}}).
  - flag and proposal answers go through op(operation) (or api.op; both record
    to the same list): {op:'set', building, field:'flag_ok', value:{index, ...}},
    {op:'accept_proposal', building, id}, {op:'dismiss_proposal', building, id}.
  - queue() items carry kind 'pause' | 'flag' | 'proposal'; a pause item names
    its step, a flag its building and index, a proposal its building and id.
    The pause comes first; flags in model order (building, then index); then
    proposals. next() wraps from the last item to the first.
  - the shown check's actions are buttons with exactly these words.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_checks_js.py
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from twin_editor_dom import PRELUDE, run_node  # noqa: E402

NAMES = ['queue_merges_pause_flags_and_proposals', 'skip_moves_on_and_keeps_the_item',
         'fix_it_leaves_the_build_waiting']

DRIVER = PRELUDE + r"""
const NAMES = %s;
let createChecks;
try { ({createChecks} = await import(file('static/twin/editor/checks.js'))); }
catch (error) {
  for (const name of NAMES) console.log('  FAIL', name, 'checks.js did not load: ' + error.message);
  console.log(`0/${NAMES.length} passed`); process.exit(1);
}
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {createSceneTools} = await import(file('static/twin/editor/scene_tools.js'));
const {createPanel} = await import(file('static/twin/editor/panel.js'));
const THREE = await import(three);
const {model, flat, kit} = input;
const B = 'pool-house', NORTH = 'wall:d60289b4c26b487db5145bdeb22d530e';
const north = flat.buildings.find(b => b.id === B).walls.find(w => w.id === NORTH);
const proposal = {id: NORTH + ':proposal', kind: 'wall', against: NORTH,
  piece: {...north, id: NORTH + ':proposal', from: [north.from[0], north.from[1] + 2], to: [north.to[0], north.to[1] + 2], state: 'proposal'}};
model.buildings.find(b => b.id === B).proposals = [proposal];
flat.buildings.find(b => b.id === B).proposals = [proposal];
const flagRows = model.buildings.flatMap(b => (b.flags || []).map((flag, index) => ({building: b.id, index, flag})));
document.getElementById('editor-say').append(document.createElement('button'));
const view = await mountTwin(document.createElement('div'), {plan: {buildings: [], site: {}, materials: {}}, kit, tier: 'low', preserveCamera: true});
await view.rebuild(flat);
const panel = createPanel({afterSay: async () => {}});
const signal = new AbortController().signal;
const tools = createSceneTools({view, getPlan: () => flat, getModel: () => model, getSheets: () => ({}),
  edit: async () => {}, op: async () => {}, panel, canEdit: () => true, signal});
tools.refresh();
const pausedBuild = () => ({id: 'b1', part: B, state: 'paused', events: [],
  steps: [{id: 'fit', kind: 'fit', label: 'Place the pool house', status: 'paused', last_cost: 0.42, estimate: 0.42}],
  pause: {kind: 'lot_placement', step: 'fit', why: 'Check where the pool house sits on the lot.',
    transform: {position: [60, 80], rotation: 37}, registration: {scale: 1, angle: 0, origin_px: [0, 0], offset: [0, 0]}}});
let build, requests, ops, lifetime = null;
function make() {
  // Each test starts its own checks; the previous one is ended through its signal.
  lifetime?.abort(); lifetime = new AbortController();
  build = pausedBuild(); requests = []; ops = [];
  const op = async operation => { ops.push(operation); return {}; };
  const api = {request: async (path, method, body) => { requests.push({path, method, body}); return {}; }, op,
    report: error => { throw error; }};
  return createChecks(view, {api, getBuild: () => build, getModel: () => model, getPlan: () => flat, tools, panel,
    canEdit: () => true, signal: lifetime.signal, op, getSheets: () => ({sources: [], page_roles: [], place: {buildings: [], lot: {}, photo_tags: {}}})});
}
const settle = async () => { for (let i = 0; i < 3; i++) { tick(); await new Promise(r => setTimeout(r, 5)); } };
const button = text => { const found = visibleButtons(text); assert.equal(found.length, 1, `exactly one ${text} button shows (found ${found.length})`); return found[0]; };
const none = text => assert.equal(visibleButtons(text).length, 0, `no ${text} button shows`);
const answers = () => requests.filter(r => /build\/b1\/answer$/.test(r.path));
const key = item => item.kind === 'pause' ? `pause:${item.step}` : item.kind === 'flag' ? `flag:${item.building}:${item.index}` : `proposal:${item.building}:${item.id}`;
const world = (b, p) => {
  const a = (b.rotation || 0) * Math.PI / 180, pos = b.position || [0, 0];
  return new THREE.Vector3((Math.cos(a) * p[0] - Math.sin(a) * p[1] + pos[0]) * .3048,
    (p[2] + (b.base || 0)) * .3048, -(Math.sin(a) * p[0] + Math.cos(a) * p[1] + pos[1]) * .3048);
};
async function goTo(checks, want) {
  for (let i = 0; i <= checks.queue().length + 1; i++) {
    if (want(checks.current())) return checks.current();
    checks.next(); await settle();
  }
  throw new Error('never reached the wanted check');
}

await test('queue_merges_pause_flags_and_proposals', async () => {
  const checks = make(); await settle();
  const queue = checks.queue();
  assert.equal(queue.length, 1 + flagRows.length + 1, `one pause, ${flagRows.length} flags and one proposal: ${queue.map(key)}`);
  assert.equal(queue[0].kind, 'pause'); assert.equal(queue[0].step, 'fit');
  assert.deepEqual(queue.filter(i => i.kind === 'flag').map(i => [i.building, i.index]), flagRows.map(r => [r.building, r.index]),
    'every flag of the model, in model order');
  assert.deepEqual(queue.filter(i => i.kind === 'proposal').map(i => [i.building, i.id]), [[B, proposal.id]], 'the proposal');
  assert.deepEqual(queue.map(i => i.kind), ['pause', ...flagRows.map(() => 'flag'), 'proposal'], 'pause, then flags, then proposals');
  assert.equal(key(checks.current()), 'pause:fit', 'the pause shows first');

  // One check at a time, with its actions.
  button('Looks right'); button('Fix it'); button('Skip for now');
  const reread = visibleButtons(/^Read it again/);
  assert.equal(reread.length, 1, 'the pause keeps its re-read');
  assert.match(textOf(reread[0]), /^Read it again · about \$\d+\.\d\d$/, textOf(reread[0]));
  none('Use this'); none('Dismiss');

  await click(button('Looks right')); await settle();
  assert.deepEqual(answers().map(r => [r.method, r.body]), [['POST', {step: 'fit', decision: {accept: true}}]],
    'Looks right answers the pause once: ' + JSON.stringify(requests));
  assert.equal(ops.length, 0, 'answering a pause changes no piece');
  build = {...build, state: 'running', pause: null}; await settle();
  assert.ok(!checks.queue().some(i => i.kind === 'pause'), 'an answered pause leaves the queue');

  // A flag: the camera on its point, Looks right posts flag_ok.
  const flagged = await goTo(checks, item => item?.kind === 'flag'
    && !!flagRows.find(r => r.building === item.building && r.index === item.index)?.flag.level);
  const row = flagRows.find(r => r.building === flagged.building && r.index === flagged.index);
  assert.ok(row, 'the shown flag is one of the model\'s');
  const b = model.buildings.find(x => x.id === row.building), level = b.levels.find(l => l.id === row.flag.level);
  if (level) {
    await settle(); view.camera.updateMatrixWorld(true);
    const p = world(b, [...row.flag.at, level.elevation]).project(view.camera);
    assert.ok(Math.abs(p.x) < .05 && Math.abs(p.y) < .05, `the camera is on the flag: ${p.x}, ${p.y}`);
  }
  button('Skip for now'); none('Use this');
  await click(button('Looks right')); await settle();
  const flagOk = ops.filter(o => o.field === 'flag_ok');
  assert.equal(flagOk.length, 1, 'Looks right on a flag posts flag_ok once: ' + JSON.stringify(ops));
  assert.equal(flagOk[0].op, 'set'); assert.equal(flagOk[0].building, row.building);
  assert.equal(flagOk[0].value.index, row.index);
  assert.equal(answers().length, 1, 'a flag answer never answers the build');

  // A proposal: Use this and Dismiss instead of Looks right.
  await goTo(checks, item => item?.kind === 'proposal');
  none('Looks right'); button('Dismiss');
  await click(button('Use this')); await settle();
  assert.deepEqual(ops.at(-1), {op: 'accept_proposal', building: B, id: proposal.id});
  await goTo(checks, item => item?.kind === 'proposal');
  await click(button('Dismiss')); await settle();
  assert.deepEqual(ops.at(-1), {op: 'dismiss_proposal', building: B, id: proposal.id});
});

await test('skip_moves_on_and_keeps_the_item', async () => {
  const checks = make(); await settle();
  const before = checks.queue().map(key);
  assert.equal(key(checks.current()), 'pause:fit');
  await click(button('Skip for now')); await settle();
  assert.notEqual(key(checks.current()), 'pause:fit', 'Skip for now shows the next check');
  assert.equal(key(checks.current()), before[1], 'the next one in the queue');
  assert.deepEqual(checks.queue().map(key), before, 'the skipped pause stays in the queue');
  assert.ok(answers().every(r => !r.body?.decision?.accept && !r.body?.decision?.transform && !r.body?.decision?.registration),
    'a skipped pause is never accepted: ' + JSON.stringify(requests));
  assert.equal(ops.length, 0, 'skipping changes nothing');
  assert.equal(build.state, 'paused', 'the build still waits on the person');
  // A skipped flag stays too; next() walks every item and comes back around.
  const flagKey = key(checks.current());
  await click(button('Skip for now')); await settle();
  assert.ok(checks.queue().map(key).includes(flagKey), 'a skipped flag stays in the queue');
  const seen = [key(checks.current())];
  for (let i = 1; i < before.length; i++) { checks.next(); await settle(); seen.push(key(checks.current())); }
  assert.deepEqual([...seen].sort(), [...before].sort(), 'next() visits every check once');
  checks.next(); await settle();
  assert.equal(key(checks.current()), seen[0], 'after the last check it comes back to the first');
  assert.equal(visibleButtons('Skip for now').length, 1, 'still one check at a time');
});

await test('fix_it_leaves_the_build_waiting', async () => {
  const checks = make(); await settle();
  assert.equal(key(checks.current()), 'pause:fit');
  await click(button('Fix it')); await settle();
  assert.equal(answers().length, 0, 'Fix it on a pause answers nothing: ' + JSON.stringify(requests));
  assert.ok(checks.queue().some(i => i.kind === 'pause'), 'the pause waits in the queue while the person fixes');
  const wall = flagRows.find(r => r.building === B && typeof r.flag.piece === 'string'
    && flat.buildings.find(b => b.id === B).walls.some(w => w.id === r.flag.piece));
  assert.ok(wall, 'test setup: a pool house flag names a wall');
  await goTo(checks, item => item?.kind === 'flag' && item.building === B && item.index === wall.index);
  await click(button('Fix it')); await settle();
  assert.equal(tools.selection().id, wall.flag.piece, 'Fix it selects the flagged piece for editing');
  assert.equal(ops.length, 0, 'Fix it changes nothing by itself');
  assert.ok(checks.queue().some(i => i.kind === 'flag' && i.building === B && i.index === wall.index), 'the flag stays until it is fixed or looks right');
});
finish();
""" % json.dumps(NAMES)


def run():
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = assemble(fixture)[0]
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'model': model, 'flat': flatten(model), 'kit': kit})
    print(out.strip())
    if code is None:
        return
    if code:
        sys.exit(1)


if __name__ == '__main__':
    run()
