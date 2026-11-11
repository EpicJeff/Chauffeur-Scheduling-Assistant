"""The checks queue adopts the real pause controls and keeps adjustments live."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {createSceneTools} = await import(file('static/twin/editor/scene_tools.js'));
const {createPanel} = await import(file('static/twin/editor/panel.js'));
const {createPauses} = await import(file('static/twin/editor/pauses.js'));
const {createChecks} = await import(file('static/twin/editor/checks.js'));
const {flat, model, kit} = input;
// The DOM helper creates missing ids as divs; supply the template's real buttons.
for (const id of ['pause-accept', 'pause-reread', 'pause-drag', 'pause-pin', 'pause-cancel']) {
  const button = document.createElement('button'); button.id = id;
  document.getElementById('pause-card').append(button);
}
const panel = createPanel({afterSay: async () => {}}), lifetime = new AbortController();
const view = await mountTwin(document.createElement('div'), {plan: flat, kit, tier: 'low'});
const tools = createSceneTools({view, getPlan: () => flat, getModel: () => model, getSheets: () => ({}),
  edit: async () => {}, op: async () => {}, panel, canEdit: () => true, signal: lifetime.signal});
const requests = [];
globalThis.fetch = async (url, init) => {
  requests.push({url, body: JSON.parse(init.body)}); return {ok: true, text: async () => '{}'};
};
const b = flat.buildings[0];
let build = {id: 'b1', part: b.id, state: 'paused', steps: [{id: 'fit', label: 'Placement', status: 'paused'}], events: [],
  pause: {id: 'check1', kind: 'lot_placement', step: 'fit', why: 'Check the placement.',
    transform: {position: b.position, rotation: b.rotation}, registration: {scale: 1, angle: 0, origin_px: [0, 0], offset: [0, 0]}}};
const pauses = createPauses({view, getBuild: () => build, getGhost: () => null, getSheets: () => ({page_roles: []}),
  refresh: async () => {build = {...build, state: 'running', pause: null};}, preview: async () => {},
  canEdit: () => true, signal: lifetime.signal, guided: true});
pauses.sync();
const checks = createChecks(view, {api: {request: async () => ({}), report: e => {throw e;}},
  getBuild: () => build, getModel: () => model, getPlan: () => flat, tools, panel, canEdit: () => true,
  op: async () => {}, signal: lifetime.signal, pauses});

await test('one_pause_action_survives_sync_and_skip', async () => {
  for (let i=0; i<3; i++) {pauses.sync(); checks.sync(); tick();}
  assert.equal(visibleButtons('Looks right').length, 1, 'Looks right: '+textOf(document.getElementById('check-card')));
  assert.equal(visibleButtons(/^Read it again · about \$/).length, 1);
  assert.ok(document.getElementById('check-card').contains(document.getElementById('pause-accept')));
  assert.ok(shown(document.getElementById('pause-drag')), 'placement adjustment remains available');
  await click(visibleButtons('Skip for now')[0]);
  pauses.sync(); checks.sync();
  assert.equal(checks.current().kind, 'flag');
  assert.ok(!shown(document.getElementById('pause-card')), 'the skipped pause never covers the flag');
  assert.equal(requests.length, 0, 'the legacy accept path is not called by skip');
});
await test('the_adopted_action_posts_the_adjusted_transform', async () => {
  while(checks.current().kind !== 'pause') checks.next();
  pauses.setLotTransform({position: [12, 24], rotation: 30});
  await click(document.getElementById('pause-accept'));
  assert.deepEqual(requests.at(-1).body, {step: 'fit', decision: {transform: {position: [12,24], rotation:30}}});
  checks.sync();
  assert.ok(!checks.queue().some(r => r.kind === 'pause'));
});
lifetime.abort(); view.dispose(); finish();
"""


if __name__ == '__main__':
    from services.twin_model_bridge import assemble, flatten
    model = assemble(json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')))[0]
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'model': model, 'flat': flatten(model), 'kit': kit})
    print(out.strip())
    if code:
        sys.exit(1)
