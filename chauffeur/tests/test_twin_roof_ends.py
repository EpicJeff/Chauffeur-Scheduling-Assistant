"""Per-end integration: issue heights, generator siding and queued card edits.

Run from chauffeur/: env -u HA_BASE_URL python tests/test_twin_roof_ends.py
"""
import os
import shutil
import subprocess
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='twin_roof_ends_'))

from test_twin_joints_js import plan, building, run, check, TWIN  # noqa: E402
from test_twin_roof_issues import _one_level, issues_of  # noqa: E402
from test_twin_roof_js import Node  # noqa: E402
from services import twin_edit, twin_plan, twin_roof_issues  # noqa: E402


def test_issue_planes_match_rendered_heights():
    js = Node()
    for ridge in ('x', 'y'):
        for kind in ('gable', 'hip'):
            section = {'id': 'r', 'kind': kind, 'ridge': ridge, 'rect': [0, 0, 40, 20],
                       'plate': 10, 'pitch': 8, 'pitches': {'x0': 6, 'y1': 12}, 'overhang': 1,
                       'ends': {ridge + '0': 'clip', ridge + '1': 'hip'}}
            points = [(-.5, 10), (0, 10), (2, 10), (20, 10), (39, 10), (20, 0), (20, 19)]
            got = js.call('heightAt', *[[[section], x, y] for x, y in points])
            planes = twin_roof_issues._planes(section)
            want = [min(a * x + b * y + c for a, b, c in planes) for x, y in points]
            check(all(abs(a - b) < 1e-6 for a, b in zip(got, want)), (section, got, want))
    section = {'id': 'r', 'kind': 'hip', 'ridge': 'x', 'rect': [0, 0, 20, 40],
               'plate': 10, 'pitch': 8, 'overhang': 0}
    check(any(i['kind'] == 'hip_point' for i in issues_of(_one_level(section))), 'default hip flagged')
    check(not issues_of(_one_level({**section, 'ends': {'x0': 'gable', 'x1': 'gable'}})),
          'overridden gable ends are not a hip point')
    check(not issues_of(_one_level({**section, 'ends': {'x0': 'clip'}})), 'a clipped end is not a full hip')
    check(any(i['kind'] == 'hip_point' for i in issues_of(_one_level(
        {**section, 'kind': 'gable', 'ends': {'x0': 'hip', 'x1': 'hip'}}))), 'explicit hip ends flagged')


def test_generator_fill_and_windows_follow_each_end():
    p = plan()
    b = building(p)
    b.update(levels=[{'id': 'L1', 'elevation': 0, 'ceiling': 10,
                      'outline': [[0, 0], [40, 0], [40, 20], [0, 20]]}],
             walls=[], openings=[], rooms=[], stairs=[], fixtures=[], lights=[], porches=[])
    b.pop('porch', None)
    s = {'id': 'r', 'kind': 'hip', 'ridge': 'x', 'rect': [0, 0, 40, 20],
         'plate': 10, 'pitch': 12, 'overhang': 1, 'ends': {'x0': 'clip', 'x1': 'gable'}}
    b['roof'] = {'sections': [s], 'extensions': []}
    rays = [{'o': [-2, 10, z], 'd': [1, 0, 0], 'far': 4, 'roles': ['siding']} for z in (15, 18)]
    rays.append({'o': [42, 10, 18], 'd': [-1, 0, 0], 'far': 4, 'roles': ['siding']})
    hits = run(p, rays=rays)['hits']
    check(hits[0] and not hits[1] and hits[2], ('clip fill below its top; full opposite gable', hits))
    b['openings'] = [{'id': 'win', 'section': 'r', 'gable': 'rear', 'kind': 'window',
                      'y': 10, 'width': 3, 'sill': 2, 'head': 6}]
    normalized, notes = twin_plan.normalize(p)
    check(building(normalized)['openings'], ('window on an overridden hip survives', notes))
    hits = run(normalized, rays=[{'o': [42, 10, 14], 'd': [-1, 0, 0], 'far': 4}])['hits'][0]
    check(hits and hits[0]['role'] == 'glass', ('gable window is cut through the fill', hits))
    building(normalized)['openings'] = []
    edited, _ = twin_edit.apply(normalized, {'op': 'set', 'piece': 'r', 'field': 'ridge', 'value': 'y'})
    check(building(edited)['roof']['sections'][0]['ends'] == {'y0': 'clip', 'y1': 'gable'},
          'ridge change keeps both end choices')


def test_cards_set_both_ends_without_losing_queued_changes():
    # Minimal DOM, real cards.js and asynchronous save callbacks under node.
    driver = r"""
import { pathToFileURL } from 'node:url';
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.value = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  setAttribute() {}
  addEventListener(name, fn) { this.listeners[name] = fn; }
  querySelectorAll(tag) { return this.children.flatMap(c => [ ...(c.tag === tag ? [c] : []), ...c.querySelectorAll(tag)]); }
}
const host = new Element('aside');
globalThis.document = { getElementById: () => host, createElement: tag => new Element(tag), activeElement: null };
globalThis.window = { showGlobalAlert: message => { throw new Error(message); } };
const { createCards } = await import(pathToFileURL(process.argv[2]).href);
const section = { id: 'r', kind: 'hip', ridge: 'x', pitch: 8, plate: 10, overhang: 1 };
const plan = { buildings: [{ id: 'b', roof: { sections: [section] } }] };
let editable = true;
const edits = [];
const cards = createCards({ getPlan: () => plan, getLabel: () => 'roof', canEdit: () => editable,
  select: () => {}, ask: () => {}, edit: async edit => {
    await new Promise(r => setTimeout(r, 5)); edits.push(edit); section[edit.field] = edit.value;
  } });
const assert = (test, why) => { if (!test) throw new Error(why); };
const input = label => host.querySelectorAll('label').find(l => l.textContent === label)?.children[0];
cards.draw({ pieceId: 'r', buildingId: 'b' });
assert(input('Left end').value === 'hip' && input('Right end').value === 'hip', 'default hip controls');
for (const [name, value] of [['Left end', 'clip'], ['Right end', 'gable']]) {
  const node = input(name); node.value = value; node.listeners.change();
}
await new Promise(r => setTimeout(r, 50));
assert(JSON.stringify(section.ends) === JSON.stringify({ x0: 'clip', x1: 'gable' }), 'queued edits preserve both ends');
assert(edits.length === 2 && edits.every(e => e.field === 'ends'), 'whole mapping sent through set ends');
section.ridge = 'y'; section.ends = { y0: 'gable', y1: 'clip' }; cards.draw();
assert(input('Front end').value === 'gable' && input('Back end').value === 'clip' && !input('Left end'), 'ridge refresh');
section.ends.y0 = 'hip'; cards.draw(); assert(input('Front end').value === 'hip', 'poll refresh');
editable = false; cards.draw(); assert(input('Back end').disabled, 'read only card');
section.kind = 'flat'; cards.draw(); assert(!input('Front end'), 'flat roofs have no end controls');
console.log('card end controls passed');
"""
    with tempfile.TemporaryDirectory(prefix='twin_end_cards_') as tmp:
        module = os.path.join(tmp, 'cards.mjs')
        shutil.copy(os.path.join(TWIN, 'editor', 'cards.js'), module)
        path = os.path.join(tmp, 'driver.mjs')
        with open(path, 'w', encoding='utf-8') as file:
            file.write(driver)
        result = subprocess.run(['node', path, module], capture_output=True, text=True, timeout=30)
        check(result.returncode == 0, result.stderr)


if __name__ == '__main__':
    for test in (test_issue_planes_match_rendered_heights, test_generator_fill_and_windows_follow_each_end,
                 test_cards_set_both_ends_without_losing_queued_changes):
        test()
        print('  ok ', test.__name__)
