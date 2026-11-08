"""The generator draws every porch in `porches`, and a screened porch draws
screen panels (task 7b of docs/superpowers/plans/
2026-11-08-house-editor-whole-building-draft.md; spec docs/superpowers/specs/
2026-11-08-house-editor-whole-building-draft-design.md section 3 "a screened
porch is a porch with its roof"; ruling R17). Written before the code.

static/twin/twin_generator.js draws each porch in building.porches the way it
draws `porch` today: a slab, and columns that reach the roof surface over each
column (not a hard-coded shed). A screened porch (screened: true) also draws
thin screen panels between its columns on its open sides, in one translucent
material, merged (no draw call per panel).

Runs the generator under node with the vendored three, as
tests/test_twin_joints_js.py does (the driver below is copied from it), on the
main-house whole-building draft fixture
(tests/fixtures/twin_reads/recorded/claude/draft-main-spike.json) run through
services.twin_plan.normalize, with its legacy `porch` moved into `porches` and
a rear porch added under the rear_porch roof section (rect [14.33, 50, 30.67,
66], gable, ridge y, pitch 9, plate 10).

Transforms. The building is pinned at [0, 0], rotation 0, and the driver sets
the root scale (gen.FT) back to 1, so world = (x, z + base, -y) for a plan
point (x, y, height z). Hits come back in plan feet.

How a hit is classed: by material role (material.name is the kit role): 'roof'
is roof; 'siding' or 'base' is an exterior wall; anything else is other. The
screen material's role name is the implementer's choice: a screen hit is a mesh
that is neither siding nor roof (nor porch_ceiling).

Skips (rather than fails) when node is unavailable.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_porches_js.py
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

# Before any services import: never the real data dir.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_porches_js_')
os.environ.pop('HA_BASE_URL', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import twin_library as tl  # noqa: E402
from services import twin_plan  # noqa: E402

TWIN = os.path.join(ROOT, 'static', 'twin')
VENDOR = os.path.join(ROOT, 'static', 'vendor', 'three-r187')
FIXTURE = os.path.join(ROOT, 'tests', 'fixtures', 'twin_reads', 'recorded', 'claude', 'draft-main-spike.json')
BID = 'main-house'

WALL_ROLES = {'siding', 'base'}
ROOF_ROLES = {'roof'}
UNDERSIDE_ROLES = {'porch_ceiling'}

REAR_POLYGON = [[14.33, 52], [30.67, 52], [30.67, 66], [14.33, 66]]
# Three posts along the rear edge (the middle one under the ridge, where the
# roof is 6 ft above the plate) and one on the open left side. None sits under
# another section's overhang.
REAR_COLUMNS = [{'at': [14.75, 65.58], 'size': 0.83}, {'at': [22.5, 65.58], 'size': 0.83},
                {'at': [30.25, 65.58], 'size': 0.83}, {'at': [14.75, 56.5], 'size': 0.83}]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


DRIVER = r"""
import { registerHooks } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const job = JSON.parse(process.argv[2]);
registerHooks({
  resolve(spec, ctx, next) {
    if (spec === 'three') return { url: pathToFileURL(path.join(job.vendor, 'three.module.js')).href, shortCircuit: true };
    if (spec.startsWith('three/addons/')) return { url: pathToFileURL(path.join(job.vendor, 'addons', spec.slice('three/addons/'.length))).href, shortCircuit: true };
    return next(spec, ctx);
  },
  load(url, ctx, next) {
    if (url.startsWith('file:') && url.endsWith('.js')) return { ...next(url, { ...ctx, format: 'module' }), format: 'module' };
    return next(url, ctx);
  },
});
globalThis.window = globalThis.window || {};
const roof = await import(pathToFileURL(path.join(job.twin, 'twin_roof.js')).href);
const building = job.plan.buildings.find(b => b.id === job.building);
const sections = building.roof?.sections || [];
const result = {};
result.heights = (job.heights || []).map(([x, y]) => roof.heightAt(sections, x, y));
const THREE = await import('three');
const gen = await import(pathToFileURL(path.join(job.twin, 'twin_generator.js')).href);
const out = gen.buildTwin(job.plan, job.kit, 'low');
const root = out.root;
// Work in plan feet: undo the FT scale on the root.
root.scale.setScalar(1);
root.updateMatrixWorld(true);
const first = building.levels.slice().sort((a, c) => a.elevation - c.elevation)[0];
const base = out.levelElevations[`${job.building}:${first.id}`] - first.elevation;
result.base = base;
const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
const meshes = [];
root.traverse(o => {
  if (!o.isMesh || !shown(o)) return;
  if (o.layers.isEnabled(gen.PICK_LAYER) || o.userData.ghost) return;
  const m = Array.isArray(o.material) ? o.material[0] : o.material;
  if (m && m.name === 'ghost') return;
  meshes.push(o);
});
result.meshCount = meshes.length;
// Shown meshes per material instance (a merged material is one draw call per group).
result.meshesByMaterial = {};
for (const o of meshes) {
  const m = Array.isArray(o.material) ? o.material[0] : o.material;
  result.meshesByMaterial[m.uuid] = (result.meshesByMaterial[m.uuid] || 0) + 1;
}
const toWorld = ([x, y, z]) => new THREE.Vector3(x, z + base, -y);
const caster = new THREE.Raycaster();
result.hits = (job.rays || []).map(ray => {
  const d = new THREE.Vector3(ray.d[0], ray.d[2], -ray.d[1]).normalize();
  caster.set(toWorld(ray.o), d); caster.near = 0; caster.far = ray.far ?? Infinity;
  return caster.intersectObjects(meshes, false).slice(0, ray.keep ?? 6).map(hit => {
    const m = Array.isArray(hit.object.material) ? hit.object.material[hit.face?.materialIndex ?? 0] : hit.object.material;
    const n = hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : new THREE.Vector3();
    return { role: m?.name || '', dist: hit.distance, p: [hit.point.x, -hit.point.z, hit.point.y - base], n: [n.x, -n.z, n.y],
             object: hit.object.uuid, material: m?.uuid || '', transparent: !!m?.transparent,
             opacity: m?.opacity ?? 1 };
  });
});
console.log(JSON.stringify(result));
"""


def _node():
    return shutil.which('node')


_PLAN = None


def plan(rear_screened=None, front_screened=None):
    """The normalized fixture, pinned at the origin with no rotation, its
    legacy porch moved into porches beside a rear porch."""
    global _PLAN
    if _PLAN is None:
        with open(FIXTURE, encoding='utf-8') as f:
            _PLAN = json.load(f)
    raw = copy.deepcopy(_PLAN)
    b = next(x for x in raw['buildings'] if x['id'] == BID)
    front = b.pop('porch')
    front['id'] = 'front'
    rear = {'id': 'rear', 'polygon': copy.deepcopy(REAR_POLYGON), 'floor': 0, 'columns': copy.deepcopy(REAR_COLUMNS)}
    if front_screened is not None:
        front['screened'] = front_screened
    if rear_screened is not None:
        rear['screened'] = rear_screened
    b['porches'] = [front, rear]
    normalized, _notes = twin_plan.normalize(raw)
    for x in normalized['buildings']:
        x['position'] = [0, 0]
        x['rotation'] = 0
    return normalized


def building(p):
    return next(b for b in p['buildings'] if b['id'] == BID)


def run(p, rays=None, heights=None):
    d = tempfile.mkdtemp(prefix='twin_porches_js_')
    try:
        driver = os.path.join(d, 'driver.mjs')
        with open(driver, 'w', encoding='utf-8') as f:
            f.write(DRIVER)
        job = {'vendor': VENDOR, 'twin': TWIN, 'plan': p, 'building': BID,
               'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}},
               'rays': rays, 'heights': heights}
        job_path = os.path.join(d, 'job.json')
        with open(job_path, 'w', encoding='utf-8') as f:
            json.dump(job, f)
        # The plan is large: pass it through a file, read back by a tiny shim.
        shim = os.path.join(d, 'shim.mjs')
        with open(shim, 'w', encoding='utf-8') as f:
            f.write("import fs from 'node:fs';\n"
                    "process.argv[2] = fs.readFileSync(process.argv[2], 'utf8');\n"
                    "await import('./driver.mjs');\n")
        result = subprocess.run(['node', shim, job_path], capture_output=True, text=True, timeout=300)
        check(result.returncode == 0, result.stderr[-3000:])
        return json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def classify(hit):
    role = hit['role']
    if role in ROOF_ROLES:
        return 'roof'
    if role in WALL_ROLES:
        return 'wall'
    if role:
        return 'other'
    return 'wall' if abs(hit['n'][2]) < 0.3 else 'roof'


def _r(v):
    return round(v, 2)


# ---- tests -----------------------------------------------------------------

def _columns(b):
    out = []
    for porch in b['porches']:
        for c in porch['columns']:
            # A horizontal ray at 4 ft starts 3 ft from the post, inside its
            # own porch (front posts sit at its front edge, rear-edge posts at
            # the rear edge), and runs toward the post.
            sign = 1 if porch['id'] == 'front' or c['at'][1] < 60 else -1
            out.append((porch['id'], c, sign))
    return out


def test_columns_reach_roof_for_both_porches():
    """Down from z = 40 at each column's centre: the roof first, then the
    column top within 0.3 ft below the roof. At 4 ft a horizontal ray meets the
    column body; the slab lies under each porch."""
    p = plan()
    b = building(p)
    check(len(b.get('porches') or []) == 2, ('the test plan keeps both porches', b.get('porches')))
    cols = _columns(b)
    rays = []
    for _pid, c, sign in cols:
        x, y = c['at']
        rays.append({'o': [x, y, 40], 'd': [0, 0, -1], 'far': 60, 'keep': 8})
        rays.append({'o': [x, y + sign * 3, 4], 'd': [0, -sign, 0], 'far': 6, 'keep': 2})
    slab_points = {'front': [18, 10], 'rear': [22.5, 60]}
    for pt in slab_points.values():
        rays.append({'o': [pt[0], pt[1], 8], 'd': [0, 0, -1], 'far': 10, 'keep': 2})
    info = run(p, rays=rays, heights=[c['at'] for _pid, c, _s in cols])
    hits, heights = info['hits'], info['heights']
    short, bodies = [], []
    for i, (pid, c, sign) in enumerate(cols):
        down, side = hits[2 * i], hits[2 * i + 1]
        tag = (pid, c['at'], 'roof height', heights[i] and _r(heights[i]))
        if not down or classify(down[0]) != 'roof':
            short.append(tag + ('first hit is not the roof', down and (down[0]['role'], _r(down[0]['p'][2]))))
        else:
            roof_z = down[0]['p'][2]
            below = [h for h in down[1:] if classify(h) != 'roof' and h['role'] not in UNDERSIDE_ROLES]
            top = below[0] if below else None
            if top is None or not (-0.02 <= roof_z - top['p'][2] <= 0.3) or top['n'][2] < 0.5:
                short.append(tag + ('roof at', _r(roof_z), 'next', top and (top['role'], _r(top['p'][2]))))
        body = side[0] if side else None
        if (body is None or classify(body) != 'other'
                or abs(body['p'][1] - c['at'][1]) > c['size'] / 2 + 0.05):
            bodies.append((pid, c['at'], body and (body['role'], [_r(v) for v in body['p']])))
    check(not short, (f'{len(short)}/{len(cols)} columns do not reach the roof over them '
                      '(porch, at, roof height, problem)', short))
    check(not bodies, ('a column stands from the slab at 4 ft (porch, at, first hit)', bodies))
    for k, (name, pt) in enumerate(slab_points.items()):
        hs = hits[2 * len(cols) + k]
        check(hs and classify(hs[0]) == 'other' and abs(hs[0]['p'][2]) <= 0.05,
              (f'the {name} porch slab is drawn at its floor', pt, hs and [(h['role'], _r(h['p'][2])) for h in hs]))


def test_screened_porch_draws_screens():
    """Through an open side of the screened rear porch, between two columns at
    4 ft: the first hit is the screen, one translucent merged material that is
    neither siding nor roof. The open front porch draws no screen."""
    p = plan(rear_screened=True, front_screened=False)
    rays = [
        # Rear side, between the posts at x 14.75 and 22.5, and 22.5 and 30.25.
        {'o': [18.6, 70, 4], 'd': [0, -1, 0], 'far': 20, 'keep': 3},
        {'o': [26.4, 70, 4], 'd': [0, -1, 0], 'far': 20, 'keep': 3},
        # Open left side, between the posts at y 56.5 and 65.58.
        {'o': [11, 61, 4], 'd': [1, 0, 0], 'far': 10, 'keep': 3},
        # The open front porch, between its posts at x 14.75 and 23.08.
        {'o': [19, 3, 4], 'd': [0, 1, 0], 'far': 15, 'keep': 3},
    ]
    info = run(p, rays=rays)
    hits = info['hits']
    screens = []
    for ray, hs, (axis, lo, hi) in zip(rays[:3], hits[:3], [(1, 65.0, 66.2), (1, 65.0, 66.2), (0, 14.2, 15.3)]):
        first = hs[0] if hs else None
        check(first is not None, ('the ray through the open side hits nothing', ray))
        check(classify(first) == 'other' and first['role'] not in UNDERSIDE_ROLES,
              ('a screen, neither siding nor roof, fills the open side', ray['o'], first['role'], [_r(v) for v in first['p']]))
        check(lo <= first['p'][axis] <= hi,
              ('the screen stands on the porch edge', ray['o'], [_r(v) for v in first['p']]))
        check(abs(first['p'][2] - 4) <= 0.01, first)
        screens.append(first)
    check(len({s['material'] for s in screens}) == 1, ('one screen material', [s['role'] for s in screens]))
    check(len({s['object'] for s in screens}) == 1, ('the panels are merged into one mesh', [s['object'] for s in screens]))
    check(info['meshesByMaterial'].get(screens[0]['material']) == 1,
          ('the screen material is one draw call', info['meshesByMaterial'].get(screens[0]['material'])))
    check(screens[0]['transparent'] or screens[0]['opacity'] < 1,
          ('the screen is translucent', screens[0]['role'], screens[0]['transparent'], screens[0]['opacity']))
    # Ruling R18: anything set in the house wall's plane (siding, a door, a
    # window frame, glass, trim, or any mesh within 0.6 ft of the wall line at
    # y 14.33) is the house wall. A screen mesh, or no hit at all, fails.
    front = hits[3][0] if hits[3] else None
    in_wall = front is not None and (
        classify(front) == 'wall' or front['role'] in ('door', 'window_frame', 'glass', 'trim')
        or abs(front['p'][1] - 14.33) <= 0.6)
    check(front is not None and front['material'] != screens[0]['material'] and in_wall,
          ('an open porch has no screen: the ray reaches the house wall', front and (front['role'], [_r(v) for v in front['p']])))


TESTS = (
    test_columns_reach_roof_for_both_porches,
    test_screened_porch_draws_screens,
)


if __name__ == '__main__':
    if not _node():
        print('  skip  node is not available')
        sys.exit(0)
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
