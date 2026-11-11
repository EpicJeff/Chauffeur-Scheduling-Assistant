"""The step strip, run under node (plan docs/superpowers/plans/
2026-11-10-house-guided-build-piece-4.md, Task 7; brief
.superpowers/sdd/2026-11-10-house-guided-build-piece-4/task-7-brief.md).

static/twin/editor/steps.js exports createSteps(host, {state}) ->
{render(state), open(name)}. The strip shows five steps, always, in this order
and with these words: Your files, Your lot, Build, Check it, Link to Home
Assistant. Each shows done / now / not yet, derived from the model and the
stored sources.

What this test assumes (the DOM contract; the live file uses the same):
  - `state` is {model, sheets, build}: model is the connected model
    (GET api/house/editor/state's `model`, schema 3: buildings with walls,
    rooms, flags, proposals), sheets is GET api/house/editor/sheets (sources,
    page_roles, place {buildings, lot {read, placement}, photo_tags}), build is
    the current build or null. render(state) redraws from it.
  - each step is an element inside host carrying data-step="<its words>" and
    data-state="done" | "now" | "not-yet"; its text holds its words. The step
    is a button, or holds one; pressing it opens that step.
  - the open step's element has aria-expanded="true"; the others "false" or none.
  - the Check it step's text holds how many things wait to be checked (flags
    plus proposals) while there are any.

The derivation this test pins, case by case (only where the answer is plain):
  - nothing yet: Your files is now, every later step not yet;
  - pages confirmed (every page of every drawing has a saved role) and the lot
    read and placed: Your files and Your lot done, Build now, the rest not yet;
  - lot read but not placed: Your lot is now;
  - a build running: Build is now;
  - the house built with flags or proposals left: Build done, Check it now;
  - built with nothing to check: Check it done, Link to Home Assistant now;
  - every room linked to a Home Assistant area (room.ha_area): Link done.
  At most one step is now at a time.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_steps_js.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from twin_editor_dom import PRELUDE, run_node  # noqa: E402

DRIVER = PRELUDE + r"""
const LABELS = ['Your files', 'Your lot', 'Build', 'Check it', 'Link to Home Assistant'];
let createSteps;
try { ({createSteps} = await import(file('static/twin/editor/steps.js'))); }
catch (error) { console.log('  FAIL', 'step_state_from_model_and_sources', 'steps.js did not load: ' + error.message); console.log('0/2 passed'); process.exit(1); }

const emptySheets = () => ({sources: [], page_roles: [], kinds: [], estimates: {},
  place: {buildings: [], lot: {}, photo_tags: {}}});
const filedSheets = ({placed = true} = {}) => ({
  sources: [{id: 's1', kind: 'drawing', filename: 'two.pdf', pages: 2, part: 'house'}],
  page_roles: [
    {source: 's1', page: 1, role: 'floor', level: 'Main floor', building: 'house', box: null},
    {source: 's1', page: 2, role: 'plot', level: null, building: 'lot', box: null}],
  kinds: [{id: 'house', label: 'Main house'}], estimates: {build: {house: {total: 1.4}}},
  place: {buildings: [{id: 'house', name: 'Main house', kind: 'house'}], photo_tags: {},
    lot: {read: {id: 'read-1', suggestions: []},
      placement: placed ? {confirmed: true, street_edge: [0, 1], footprints: []} : null}}});
const builtModel = ({flags = 1, proposals = 1, linked = false} = {}) => ({buildings: [{
  id: 'house', name: 'Main house', position: [0, 0], rotation: 0, base: 0,
  levels: [{id: 'L1', name: 'Main floor', elevation: 0, ceiling: 9}],
  joints: [{id: 'j1', level: 'L1', at: [0, 0]}, {id: 'j2', level: 'L1', at: [20, 0]},
    {id: 'j3', level: 'L1', at: [20, 15]}, {id: 'j4', level: 'L1', at: [0, 15]}],
  walls: [['w1', 'j1', 'j2'], ['w2', 'j2', 'j3'], ['w3', 'j3', 'j4'], ['w4', 'j4', 'j1']]
    .map(([id, a, b]) => ({id, level: 'L1', joints: [a, b], kind: 'exterior', thickness: .5, src: {step: 'draft'}})),
  rooms: [{id: 'r1', level: 'L1', name: 'Kitchen', joints: ['j1', 'j2', 'j3', 'j4'], ...(linked ? {ha_area: 'kitchen'} : {})}],
  openings: [], anchors: [], items: [], roofs: [],
  flags: Array.from({length: flags}, (_, i) => ({text: `Check wall ${i + 1}.`, level: 'L1', at: [10, 0], piece: 'w1'})),
  proposals: Array.from({length: proposals}, (_, i) => ({id: `w2:proposal${i}`, kind: 'wall', against: 'w2',
    piece: {id: `w2:proposal${i}`, level: 'L1', from: [21, 0], to: [21, 15], state: 'proposal'}})),
}]});

const host = document.createElement('nav'); host.id = 'editor-steps'; document.body.append(host);
const stepNode = name => host.querySelector(`[data-step="${name}"]`);
const states = () => Object.fromEntries(LABELS.map(name => [name, stepNode(name)?.getAttribute('data-state') ?? null]));
const opener = name => { const n = stepNode(name); return n.matches('button') ? n : n.querySelector('button') || n; };

await test('step_state_from_model_and_sources', async () => {
  const empty = {model: null, sheets: emptySheets(), build: null};
  const steps = createSteps(host, {state: empty});
  steps.render(empty);
  const nodes = host.querySelectorAll('[data-step]');
  assert.deepEqual(nodes.map(n => n.getAttribute('data-step')), LABELS, 'five steps, in order, with these words');
  for (const name of LABELS) assert.ok(textOf(stepNode(name)).includes(name), `the ${name} step shows its words: ${textOf(stepNode(name))}`);
  const cases = [
    ['nothing yet', empty,
      {'Your files': 'now', 'Your lot': 'not-yet', 'Build': 'not-yet', 'Check it': 'not-yet', 'Link to Home Assistant': 'not-yet'}],
    ['pages confirmed, lot read and placed', {model: null, sheets: filedSheets(), build: null},
      {'Your files': 'done', 'Your lot': 'done', 'Build': 'now', 'Check it': 'not-yet', 'Link to Home Assistant': 'not-yet'}],
    ['lot read, not placed', {model: null, sheets: filedSheets({placed: false}), build: null},
      {'Your files': 'done', 'Your lot': 'now'}],
    ['a build running', {model: {buildings: []}, sheets: filedSheets(), build: {id: 'b1', state: 'running', steps: [], events: []}},
      {'Build': 'now'}],
    ['built, things to check', {model: builtModel(), sheets: filedSheets(), build: {id: 'b1', state: 'done', steps: [], events: []}},
      {'Your files': 'done', 'Your lot': 'done', 'Build': 'done', 'Check it': 'now', 'Link to Home Assistant': 'not-yet'}],
    ['built, nothing to check', {model: builtModel({flags: 0, proposals: 0}), sheets: filedSheets(), build: null},
      {'Build': 'done', 'Check it': 'done', 'Link to Home Assistant': 'now'}],
    ['every room linked', {model: builtModel({flags: 0, proposals: 0, linked: true}), sheets: filedSheets(), build: null},
      {'Check it': 'done', 'Link to Home Assistant': 'done'}],
  ];
  for (const [label, state, want] of cases) {
    steps.render(state);
    const got = states();
    for (const [name, value] of Object.entries(want))
      assert.equal(got[name], value, `${label}: ${name} reads ${value}; all: ${JSON.stringify(got)}`);
    assert.ok(Object.values(got).every(v => ['done', 'now', 'not-yet'].includes(v)), `${label}: every step says done, now or not yet: ${JSON.stringify(got)}`);
    assert.ok(Object.values(got).filter(v => v === 'now').length <= 1, `${label}: at most one step is now: ${JSON.stringify(got)}`);
    assert.ok(shown(host) && LABELS.every(name => shown(stepNode(name))), `${label}: the strip is always visible`);
  }
  steps.render({model: builtModel({flags: 1, proposals: 1}), sheets: filedSheets(), build: null});
  assert.match(textOf(stepNode('Check it')), /\b2\b/, 'Check it counts the flag and the proposal: ' + textOf(stepNode('Check it')));
  steps.render({model: builtModel({flags: 3, proposals: 0}), sheets: filedSheets(), build: null});
  assert.match(textOf(stepNode('Check it')), /\b3\b/, 'the count follows the model: ' + textOf(stepNode('Check it')));
});

await test('open_marks_one_step_and_a_press_opens_it', async () => {
  host.replaceChildren();
  const state = {model: null, sheets: filedSheets(), build: null};
  const steps = createSteps(host, {state});
  steps.render(state);
  steps.open('Build');
  const expanded = () => LABELS.filter(name => stepNode(name).getAttribute('aria-expanded') === 'true'
    || opener(name).getAttribute('aria-expanded') === 'true');
  assert.deepEqual(expanded(), ['Build'], 'open(name) marks that step open and no other');
  await click(opener('Your lot'));
  assert.deepEqual(expanded(), ['Your lot'], 'pressing a step opens it');
  await click(opener('Link to Home Assistant'));
  assert.deepEqual(expanded(), ['Link to Home Assistant'], 'a step that is not yet still opens when pressed');
  steps.render({model: builtModel(), sheets: filedSheets(), build: null});
  assert.deepEqual(expanded(), ['Link to Home Assistant'], 'a redraw keeps the open step');
});
finish();
"""


def run():
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(out.strip())
    if code is None:
        return
    if code:
        sys.exit(1)


if __name__ == '__main__':
    run()
