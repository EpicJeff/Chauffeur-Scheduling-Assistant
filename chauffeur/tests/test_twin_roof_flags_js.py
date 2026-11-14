"""A roof that needs a look is marked in the editor, and the mark selects it
(brief .superpowers/sdd/2026-11-08-house-editor-roofs-from-photos/task-6-brief.md;
spec docs/superpowers/specs/2026-11-08-house-editor-roofs-from-photos-design.md
section 6 "In the editor" and "Left to the builder": the marker reuses the
existing ghost and needs-checking visuals and the roof card).

The plan carries the build's roof flags as building.roof.flags =
[{block_rect, text}]. static/twin/twin_generator.js marks the roof section
whose block (section.block, within 1 ft of the flag's block_rect) is flagged,
with the shared ghost visuals: the translucent 'ghost' material or the shared
dashed ghostEdges line. Only that block's own roof is marked: not its
neighbour, and not a dormer on it (a dormer carries its block's rect too,
spec section 6: a dormer is its own section). The mark carries the roof's
identity, so a tap on it picks that roof (view.pick casts against
pickObjects on PICK_LAYER and reads userData.pieceId), and the editor then
opens its roof card (scene_tools select, live test).

How a marker is found: any shown Mesh or Line (visible up its parent chain,
not on PICK_LAYER) whose material is the 'ghost' material or the shared
ghostEdges material, read with its userData.pieceId. The plan is settled, so
nothing else is drawn as a ghost.

Runs the generator under node with the vendored three, as
tests/test_twin_porches_js.py does (driver hooks copied from it), on a small
one-storey building: two derived side-by-side blocks and a dormer, run through
services.twin_plan.normalize. Transforms: the building sits at [0, 0],
rotation 0, and the driver sets the root scale back to 1, so world =
(x, height, -y) for a plan point (x, y).

Skips (rather than fails) when node is unavailable.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_roof_flags_js.py
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_roof_flags_js_')
os.environ.pop('HA_BASE_URL', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import twin_library as tl  # noqa: E402
from services import twin_plan  # noqa: E402

TWIN = os.path.join(ROOT, 'static', 'twin')
VENDOR = os.path.join(ROOT, 'static', 'vendor', 'three-r187')
BID = 'house'
LEFT = [0, 0, 20, 30]
RIGHT = [20, 0, 40, 30]
FLAG = {'block_rect': list(RIGHT), 'text': 'The right roof: the right side was not visible in the photos; please check it.'}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


DRIVER = r"""
import { registerHooks } from 'node:module';
import { pathToFileURL } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
registerHooks({
  resolve(spec, ctx, next) {
    if (spec === '@dgreenheck/ez-tree') return { url: 'test:tree', shortCircuit: true };
    if (spec === 'three') return { url: pathToFileURL(path.join(job.vendor, 'three.module.js')).href, shortCircuit: true };
    if (spec.startsWith('three/addons/')) return { url: pathToFileURL(path.join(job.vendor, 'addons', spec.slice('three/addons/'.length))).href, shortCircuit: true };
    return next(spec, ctx);
  },
  load(url, ctx, next) {
    if (url === 'test:tree') return { format: 'module', shortCircuit: true, source: 'export class Tree {}' };
    if (url.startsWith('file:') && url.endsWith('.js')) return { ...next(url, { ...ctx, format: 'module' }), format: 'module' };
    return next(url, ctx);
  },
});
globalThis.window = globalThis.window || {};
const THREE = await import('three');
const gen = await import(pathToFileURL(path.join(job.twin, 'twin_generator.js')).href);
const out = gen.buildTwin(job.plan, job.kit, 'low', { viewing: !!job.viewing });
const root = out.root;
root.scale.setScalar(1);
root.updateMatrixWorld(true);
out.updateGhosts();
const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
const ghostEdges = out.materials.get('ghostEdges');
const ghostVisual = m => !!m && (m.name === 'ghost' || m === ghostEdges);
const markers = [];
root.traverse(o => {
  if (!(o.isMesh || o.isLine) || o.layers.isEnabled(gen.PICK_LAYER) || !shown(o)) return;
  if (![].concat(o.material || []).some(ghostVisual)) return;
  const box = new THREE.Box3().setFromObject(o);
  markers.push({ pieceId: o.userData.pieceId ?? null, kind: o.userData.kind ?? null,
                 buildingId: o.userData.buildingId ?? null, line: !!o.isLine,
                 min: box.min.toArray(), max: box.max.toArray() });
});
const caster = new THREE.Raycaster();
caster.layers.set(gen.PICK_LAYER);
const picks = [...out.pickObjects.values()].filter(shown);
const pickAt = (x, z) => {
  caster.set(new THREE.Vector3(x, 1000, z), new THREE.Vector3(0, -1, 0));
  const hit = caster.intersectObjects(picks, false)[0];
  return hit ? { pieceId: hit.object.userData.pieceId, kind: hit.object.userData.kind, buildingId: hit.object.userData.buildingId } : null;
};
const result = { markers };
// A tap at the middle of each marked roof's mark, straight down (world x, z).
result.markerPicks = {};
for (const id of new Set(markers.map(m => m.pieceId))) {
  const own = markers.filter(m => m.pieceId === id);
  const box = new THREE.Box3();
  for (const m of own) box.union(new THREE.Box3(new THREE.Vector3(...m.min), new THREE.Vector3(...m.max)));
  const c = box.getCenter(new THREE.Vector3());
  result.markerPicks[id] = { at: [c.x, -c.z], pick: pickAt(c.x, c.z) };
}
result.points = (job.points || []).map(([x, y]) => pickAt(x, -y));
console.log(JSON.stringify(result));
"""


def _sections():
    src = {'sheet': '', 'page': 0, 'step': 'roof_blocks'}
    common = {'level': 'L1', 'plate': 9, 'pitch': 8, 'overhang': 1, 'pitch_source': 'photos',
              'state': 'settled', 'src': dict(src)}
    return [
        {**copy.deepcopy(common), 'id': 'roof-A', 'kind': 'gable', 'ridge': 'y',
         'ends': {'y0': 'gable', 'y1': 'gable'}, 'rect': list(LEFT), 'block': list(LEFT)},
        {**copy.deepcopy(common), 'id': 'roof-B', 'kind': 'gable', 'ridge': 'x',
         'ends': {'x0': 'gable', 'x1': 'gable'}, 'rect': list(RIGHT), 'block': list(RIGHT)},
        # The front dormer on the right block: a cross gable from the eave to the main ridge.
        {**copy.deepcopy(common), 'id': 'roof-B-dormer-1', 'kind': 'gable', 'ridge': 'y',
         'rect': [32, 0, 38, 15], 'block': list(RIGHT)},
    ]


def raw_plan(flags=None):
    outline = [[0, 0], [40, 0], [40, 30], [0, 30]]
    walls = [{'id': f'w{i}', 'level': 'L1', 'from': a, 'to': b, 'height': 9, 'thickness': 0.5,
              'exterior': True, 'state': 'settled', 'src': {'sheet': '', 'page': 0, 'step': 'draft'}}
             for i, (a, b) in enumerate(zip(outline, outline[1:] + outline[:1]))]
    roof = {'sections': _sections(), 'extensions': []}
    if flags is not None:
        roof['flags'] = copy.deepcopy(flags)
    building = {'id': BID, 'name': 'Main house', 'kind': 'main_house', 'position': [0, 0], 'rotation': 0,
                'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9, 'outline': outline,
                            'state': 'settled'}],
                'walls': walls, 'openings': [], 'rooms': [], 'roof': roof}
    return {'units': 'ft', 'buildings': [building], 'site': {}, 'materials': {}}


def plan(flags=None):
    """The normalized plan. The flags are put back after normalize, so the
    generator is tested on its own (normalize is checked separately)."""
    normalized, _ = twin_plan.normalize(raw_plan(flags))
    b = normalized['buildings'][0]
    b['position'], b['rotation'] = [0, 0], 0
    check({s['id'] for s in b['roof']['sections']} == {'roof-A', 'roof-B', 'roof-B-dormer-1'},
          ('test setup: every section survives normalize', [s['id'] for s in b['roof']['sections']]))
    check(all(s.get('block') for s in b['roof']['sections']), 'test setup: sections keep their block')
    if flags is not None:
        b['roof']['flags'] = copy.deepcopy(flags)
    return normalized


def run(p, points=None, viewing=False):
    d = tempfile.mkdtemp(prefix='twin_roof_flags_js_')
    try:
        driver = os.path.join(d, 'driver.mjs')
        with open(driver, 'w', encoding='utf-8') as f:
            f.write(DRIVER)
        job = {'vendor': VENDOR, 'twin': TWIN, 'plan': p, 'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}},
               'points': points or [], 'viewing': viewing}
        job_path = os.path.join(d, 'job.json')
        with open(job_path, 'w', encoding='utf-8') as f:
            json.dump(job, f)
        result = subprocess.run(['node', driver, job_path], capture_output=True, text=True, timeout=300)
        check(result.returncode == 0, result.stderr[-3000:])
        return json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _summary(markers):
    return sorted({(m['pieceId'], m['kind'], m['line']) for m in markers}, key=str)


# ---- tests -----------------------------------------------------------------

def test_malformed_roof_metadata_normalizes_and_builds():
    bad = [None, {}, {'rect': [0, 1, 2]}, {'block_rect': RIGHT},
           {'block_rect': ['bad', 0, 1, 2], 'text': 'Bad.'}, {'block_rect': RIGHT, 'text': None}]
    raw = raw_plan(bad + [FLAG])
    choice = {'rect': RIGHT, 'pitch': 6}
    raw['buildings'][0]['roof']['choices'] = bad + [choice]
    normalized, _ = twin_plan.normalize(raw)
    roof = normalized['buildings'][0]['roof']
    check(roof['flags'] == [FLAG] and roof['choices'] == [choice], roof)
    # Bypass normalize too: the real generator must tolerate malformed metadata.
    unfiltered = plan(bad + [FLAG])
    unfiltered['buildings'][0]['roof']['choices'] = bad + [choice]
    out = run(unfiltered)
    check({m['pieceId'] for m in out['markers']} == {'roof-B'}, out)
    malformed_only = run(plan(bad))
    check(malformed_only['markers'] == [], malformed_only)


def test_flags_survive_normalize():
    normalized, _ = twin_plan.normalize(raw_plan([FLAG]))
    flags = normalized['buildings'][0]['roof'].get('flags')
    check(flags == [FLAG], ('twin_plan.normalize keeps building.roof.flags as [{block_rect, text}]', flags))


def test_flagged_roof_is_marked_and_a_tap_selects_it():
    out = run(plan([FLAG]), points=[[10, 15], [36, 22]])
    markers = out['markers']
    check(markers, ('the flagged block\'s roof is drawn with the needs-checking (ghost) marker', markers))
    check({m['pieceId'] for m in markers} == {'roof-B'},
          ('only the flagged block\'s own roof is marked: not its neighbour, not the dormer on it', _summary(markers)))
    check(all(m['kind'] == 'roof' and m['buildingId'] == BID for m in markers),
          ('the marker carries the roof\'s identity', _summary(markers)))
    tap = out['markerPicks'].get('roof-B') or {}
    check(tap.get('pick') == {'pieceId': 'roof-B', 'kind': 'roof', 'buildingId': BID},
          ('a tap on the marker picks that roof, so its card opens', tap))
    # The rest of the roof picks as before.
    check(out['points'][0] == {'pieceId': 'roof-A', 'kind': 'roof', 'buildingId': BID},
          ('the unflagged roof still picks as itself', out['points'][0]))
    check(out['points'][1] == {'pieceId': 'roof-B', 'kind': 'roof', 'buildingId': BID},
          ('the flagged roof picks as itself away from the mark too', out['points'][1]))


def test_live_view_and_panels_never_show_the_check_marker():
    # User, 2026-11-14: the dashed outline on the pool house roof "has been there forever and I
    # have no idea why it shows on the panel". The marker is an editor aid only.
    out = run(plan([FLAG]), points=[[36, 22]], viewing=True)
    check(out['markers'] == [], ('the live house view draws no needs-checking marker', _summary(out['markers'])))
    check(out['points'][0] == {'pieceId': 'roof-B', 'kind': 'roof', 'buildingId': BID},
          ('the flagged roof still picks as itself in the live view', out['points'][0]))


def test_no_flags_no_marker():
    for flags, why in ((None, 'no flags key'), ([], 'an empty list'),
                       ([{'block_rect': [100, 100, 120, 120], 'text': 'Somewhere else.'}], 'a flag over no roof')):
        out = run(plan(flags))
        check(out['markers'] == [], (why, 'a settled roof with no flag of its own has no marker', _summary(out['markers'])))


def test_flag_matches_its_block_within_a_foot():
    near = {'block_rect': [20.6, -0.4, 40.5, 30.7], 'text': FLAG['text']}
    out = run(plan([near]))
    check({m['pieceId'] for m in out['markers']} == {'roof-B'},
          ('a flag matches its block within 1 ft', _summary(out['markers'])))
    far = {'block_rect': [22, 0, 40, 30], 'text': FLAG['text']}
    out = run(plan([far]))
    check(out['markers'] == [], ('a rect 2 ft off is another block', _summary(out['markers'])))


def test_flagged_roof_card_confirms_through_accept():
    driver = r"""
import { pathToFileURL } from 'node:url';
import { registerHooks } from 'node:module';
// cards now shares the room-title geometry helper with the scene. Resolve
// that dependency from the real source when this driver copies the card.
registerHooks({resolve(spec, ctx, next) {
  if (spec === '../twin_generator.js') return {url: pathToFileURL(process.argv[3] + '/twin_generator.js').href, shortCircuit: true};
  // cards keeps gaining shelf modules: a relative import from the copied card loads from
  // the real editor folder (siblings) or the twin folder (../).
  if (ctx.parentURL === pathToFileURL(process.argv[2]).href && /^\.\.?\//.test(spec))
    return {url: pathToFileURL(process.argv[3] + (spec.startsWith('../') ? '/' + spec.slice(3) : '/editor/' + spec.slice(2))).href, shortCircuit: true};
  if (spec === 'three') return {url: pathToFileURL(process.argv[4] + '/three.module.js').href, shortCircuit: true};
  if (spec.startsWith('three/addons/')) return {url: pathToFileURL(process.argv[4] + '/addons/' + spec.slice(13)).href, shortCircuit: true};
  return next(spec, ctx);
}, load(url, ctx, next) {
  return url.startsWith('file:') && url.endsWith('.js') ? {...next(url, {...ctx, format: 'module'}), format: 'module'} : next(url, ctx);
}});
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.value = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  setAttribute() {}
  addEventListener(name, fn) { this.listeners[name] = fn; }
  querySelectorAll(tag) { return this.children.flatMap(c => [...(c.tag === tag ? [c] : []), ...c.querySelectorAll(tag)]); }
}
const host = new Element('aside');
globalThis.document = { getElementById: () => host, createElement: tag => new Element(tag), activeElement: null };
globalThis.window = { showGlobalAlert: message => { throw new Error(message); } };
const { createCards } = await import(pathToFileURL(process.argv[2]).href);
const block = [20, 0, 40, 30], text = 'The right roof: its right end was not visible in the photos; I made it a gable.';
const section = { id: 'r', kind: 'gable', ridge: 'x', pitch: 8, plate: 10, overhang: 1, block, state: 'settled' };
const roof = { sections: [section], flags: [{ block_rect: [20.5, 0, 40, 30], text }] };
const plan = { buildings: [{ id: 'b', roof }] }, edits = [];
let editable = true;
const cards = createCards({ getPlan: () => plan, getLabel: () => 'roof', canEdit: () => editable,
  select() {}, ask() {}, edit: async change => { edits.push(change); roof.flags = []; } });
const assert = (test, why) => { if (!test) throw new Error(why); };
const accept = () => host.querySelectorAll('button').find(b => b.textContent === 'Looks right');
cards.draw({ pieceId: 'r', buildingId: 'b' });
assert(host.querySelectorAll('p').some(p => p.textContent === text), 'card shows the exact flag text');
assert(accept() && !accept().hidden, 'settled flagged roof can be confirmed');
editable = false; cards.draw(); assert(accept().disabled, 'confirmation respects read-only mode');
editable = true; cards.draw(); accept().listeners.click();
await new Promise(resolve => setTimeout(resolve, 30));
assert(edits.length === 1 && edits[0].op === 'accept' && edits[0].building === 'b' && edits[0].pieces[0] === 'r', 'same accept operation as ghosts');
assert(!accept() && !host.querySelectorAll('p').some(p => p.textContent === text), 'poll/save clears confirmation and text');
roof.flags = [{ block_rect: block, text }]; cards.draw(); assert(accept(), 'a newly arriving flag refreshes the card');
section.dormer_of = block; cards.draw(); assert(!accept(), 'dormer is not the block choice');
console.log('flagged roof card passed');
"""
    with tempfile.TemporaryDirectory(prefix='twin_flag_cards_') as tmp:
        module = os.path.join(tmp, 'cards.mjs')
        shutil.copy(os.path.join(TWIN, 'editor', 'cards.js'), module)
        path = os.path.join(tmp, 'driver.mjs')
        with open(path, 'w', encoding='utf-8') as file:
            file.write(driver)
        result = subprocess.run(['node', path, module, TWIN, VENDOR], capture_output=True, text=True, timeout=30)
        check(result.returncode == 0, result.stderr)


TESTS = (
    test_flagged_roof_card_confirms_through_accept,
    test_malformed_roof_metadata_normalizes_and_builds,
    test_flags_survive_normalize,
    test_flagged_roof_is_marked_and_a_tap_selects_it,
    test_live_view_and_panels_never_show_the_check_marker,
    test_no_flags_no_marker,
    test_flag_matches_its_block_within_a_foot,
)


if __name__ == '__main__':
    if not shutil.which('node'):
        print('  ..  skipped (node not available)')
        sys.exit(0)
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
