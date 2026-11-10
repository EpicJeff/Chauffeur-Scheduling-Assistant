"""Pieces appear in the house as ghosts that settle (plan
docs/superpowers/plans/2026-11-10-house-guided-build-piece-4.md, Task 5;
brief .superpowers/sdd/2026-11-10-house-guided-build-piece-4/task-5-brief.md).

Runs the REAL static/twin/editor/build_ghosts.js under node against the real
twin_view (the household's flat plan, the same renderer and DOM doubles as
test_twin_handles_js / test_twin_drag_js). Interface under test:

    createBuildGhosts(view) -> {add(event), settle(round), clear(), count()}

A piece event is the build's event as Task 3 publishes it,
{seq, type: 'piece', step, stage, kind, piece}, plus `building`: the id of the
building being built (the build's `part`; the editor adds it when the server
does not). `piece` is the reply's item as written, in that building's own
feet. A round is a twin_store round record ({id, kind: 'build',
step: {id}, partial}).

What counts as a ghost in the scene: a visible mesh or line whose material is
transparent with opacity below 1 and whose world bounding box (small, under
30 m across) contains the point. The pool house stands at position
[70.55, 142.20] turned 270 degrees, so a piece drawn without its building's
transform lands far from where it belongs.

Tests:
  a_piece_event_adds_one_ghost
  settle_replaces_ghosts_with_the_round

Run from chauffeur/:  python tests/test_twin_build_ghosts_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_twin_drag_js import DRIVER as DRAG_DRIVER  # noqa: E402

PRELUDE = DRAG_DRIVER.split('const {createDrag, piecesOnMovedJoints}')[0]

DRIVER = PRELUDE + r"""
globalThis.requestAnimationFrame = fn => setTimeout(() => fn(performance.now()), 16);
globalThis.cancelAnimationFrame = id => clearTimeout(id);
const THREE = await import(three);
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const which = process.argv[3];
let mod;
try { mod = await import(file('static/twin/editor/build_ghosts.js')); }
catch (error) { console.log('FAIL ' + which + ': static/twin/editor/build_ghosts.js does not load: ' + error.message.split('\n')[0]); process.exit(1); }
const {createBuildGhosts} = mod;
assert.equal(typeof createBuildGhosts, 'function', 'build_ghosts.js exports createBuildGhosts');
const B = 'pool-house', FT = .3048;
const b = flat.buildings.find(x => x.id === B);
const view = await mountTwin(new Element(), {plan: flat, kit, tier: 'low', preserveCamera: true});
const sleep = ms => new Promise(r => setTimeout(r, ms));
const settleFrames = async () => { await sleep(60); while (!view.ready) await sleep(5); };
await settleFrames();
const world = p => {
  const a = (b.rotation || 0) * Math.PI / 180, pos = b.position || [0, 0];
  return new THREE.Vector3((Math.cos(a) * p[0] - Math.sin(a) * p[1] + pos[0]) * FT,
    (p[2] + (b.base || 0)) * FT, -(Math.sin(a) * p[0] + Math.cos(a) * p[1] + pos[1]) * FT);
};
const raw = p => new THREE.Vector3(p[0] * FT, p[2] * FT, -p[1] * FT);   // the same feet with no building transform
const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
const mats = o => (Array.isArray(o.material) ? o.material : [o.material]).filter(Boolean);
const translucent = o => mats(o).some(m => m.transparent && m.opacity < 1);
function box(o) {
  if (o.isInstancedMesh) { o.computeBoundingBox(); return o.boundingBox && o.boundingBox.clone().applyMatrix4(o.matrixWorld); }
  if (!o.geometry) return null;
  if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
  return o.geometry.boundingBox && o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld);
}
function ghostsAt(point) {
  view.scene.updateMatrixWorld(true);
  const out = [];
  view.scene.traverse(o => {
    if (!(o.isMesh || o.isLine) || !shown(o) || !translucent(o)) return;
    const bx = box(o);
    if (!bx || bx.isEmpty() || bx.getSize(new THREE.Vector3()).length() > 30) return;
    if (bx.expandByScalar(.15).containsPoint(point)) out.push(o);
  });
  return out;
}
const wall = (id, from, to) => ({id, level: 'L1', from, to, height: 10, thickness: .33, exterior: true});
const piece = (seq, step, kind, stage, item) => ({seq, type: 'piece', step, stage, kind, building: B, piece: item});
// A spot beside the pool house where the real house has nothing translucent.
const W9 = wall('W9', [40, 30], [50, 30]), mid = [45, 30, 5], ends = [[41, 30, 5], [49, 30, 5]];
const R1 = {id: 'R1', name: 'Shed', level: 'L1', polygon: [[40, 36], [50, 36], [50, 46], [40, 46]]};
const roomAt = [45, 41, .5];
assert.equal(ghostsAt(world(mid)).length, 0, 'test setup: nothing translucent where the ghost will go');
assert.equal(ghostsAt(world(roomAt)).length, 0, 'test setup: nothing translucent where the room ghost will go');
const rawBefore = new Set(ghostsAt(raw(mid)));
const ghosts = createBuildGhosts(view);
for (const name of ['add', 'settle', 'clear', 'count']) assert.equal(typeof ghosts[name], 'function', 'createBuildGhosts(view).' + name);
assert.equal(ghosts.count(), 0, 'no ghosts before any piece arrives');

if (which === 'a_piece_event_adds_one_ghost') {
  await ghosts.add(piece(5, 'draft', 'wall', 'walls', W9));
  await settleFrames();
  assert.equal(ghosts.count(), 1, 'one piece event, one ghost');
  assert.ok(ghostsAt(world(mid)).length > 0,
    'the wall is drawn translucent where it stands in the pool house (its building\'s position and turn)');
  for (const end of ends) assert.ok(ghostsAt(world(end)).length > 0, 'the ghost runs along the wall: ' + end);
  assert.ok(ghostsAt(raw(mid)).every(o => rawBefore.has(o)),
    'the ghost is not drawn at the reply\'s raw feet, without the building\'s transform');
  await ghosts.add(piece(6, 'draft', 'wall', 'walls', wall('W10', [40, 32], [40, 34])));
  await settleFrames();
  assert.equal(ghosts.count(), 2, 'each further piece adds one more ghost');
  console.log('  ok a_piece_event_adds_one_ghost');
} else {
  await ghosts.add(piece(5, 'draft', 'wall', 'walls', W9));
  await ghosts.add(piece(6, 'draft', 'wall', 'walls', wall('W10', [40, 32], [40, 34])));
  await ghosts.add(piece(9, 'draft_rooms', 'room', 'rooms', R1));
  await settleFrames();
  assert.equal(ghosts.count(), 3, 'three pieces, three ghosts');
  assert.ok(ghostsAt(world(mid)).length > 0, 'test setup: the wall ghost is drawn');
  assert.ok(ghostsAt(world(roomAt)).length > 0, 'the room ghost is drawn translucent on its floor');
  // A stopped build's kept pieces land as a partial round of their step.
  await ghosts.settle({id: 7, kind: 'build', step: {id: 'draft', label: 'Reading the drawings'}, partial: true});
  const until = Date.now() + 3000;
  while (Date.now() < until && (ghosts.count() !== 1 || ghostsAt(world(mid)).length)) await sleep(50);
  assert.equal(ghosts.count(), 1, 'the draft round settles its own ghosts; the rooms step\'s ghost waits for its round');
  assert.equal(ghostsAt(world(mid)).length, 0, 'within 3 s the settled wall\'s ghost has faded into the round and is gone');
  assert.ok(ghostsAt(world(roomAt)).length > 0, 'a ghost of a step whose round has not landed stays');
  ghosts.clear();
  await settleFrames();
  assert.equal(ghosts.count(), 0, 'clear removes every ghost');
  assert.equal(ghostsAt(world(roomAt)).length, 0, 'clear takes the drawn ghosts out of the scene');
  console.log('  ok settle_replaces_ghosts_with_the_round');
}
view.dispose();
process.exit(0);
"""

TESTS = ['a_piece_event_adds_one_ghost', 'settle_replaces_ghosts_with_the_round']


def run():
    if not shutil.which('node'):
        print('SKIP node is unavailable')
        return
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    flat = flatten(assemble(fixture)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    paths, failed = [], []
    try:
        for suffix, content in [('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix(), 'flat': flat, 'kit': kit}))]:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_build_ghosts_',
                                             delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        for name in TESTS:
            try:
                result = subprocess.run([shutil.which('node'), str(paths[0]), str(paths[1]), name],
                                        capture_output=True, text=True, timeout=90)
            except subprocess.TimeoutExpired:
                failed.append(name)
                print(f'  FAIL {name} timed out')
                continue
            print(result.stdout, end='')
            if result.returncode:
                failed.append(name)
                if 'FAIL' not in result.stdout:
                    lines = [line for line in result.stderr.strip().splitlines() if line.strip()]
                    print(f'  FAIL {name}', ' '.join(lines[:6])[:600])
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    run()
