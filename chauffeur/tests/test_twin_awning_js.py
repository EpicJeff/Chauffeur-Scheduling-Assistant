"""Awning geometry in the generator (plan .superpowers/sdd/
2026-11-08-house-editor-whole-building-draft, Task 1): an awning hangs from
its wall's outside face and slopes DOWN and AWAY from it (high edge at the
wall at eave + depth * pitch / 12, low outer edge at eave). It may name its
wall; with none it picks one; with nothing near it draws nothing and records
'extension_skipped' in out.notes.

Runs static/twin/twin_generator.js under node with the vendored three, the
real modern_farmhouse kit and an empty manifest (as test_twin_materials_js.py).
Skips when node is unavailable.

Mesh selection (tag-free, in plan coordinates x, y = -three z, h = three y):
  * awning panel: a mesh under the roof section's piece key `poolhouse:main` whose top
    height is below 10 ft (the main roof's lowest vertex is above that) and
    whose longest horizontal extent is >= 0.9 * the awning span. Seam ribs and
    fascia are narrower than that and are not selected. Its top surface is the
    vertices whose world normal points up (ny > 0.9).
  * brackets: a mesh under any piece key of the building, narrow (<= 0.5 ft
    wide across the span axis), 1..6 ft long in the depth direction, below 9.3
    ft, inside the awning span; walls are excluded by being far longer.
Wall thickness is 0.5, so a wall's outside face is 0.25 ft off its centre line;
'at the wall' assertions accept the centre line or the outside face.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_awning_js.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_awning_js_'))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import twin_library as tl  # noqa: E402
from services import twin_plan  # noqa: E402

TWIN = os.path.join(ROOT, 'static', 'twin')
VENDOR = os.path.join(ROOT, 'static', 'vendor', 'three-r187')


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
const gen = await import(pathToFileURL(path.join(job.twin, 'twin_generator.js')).href);
const out = gen.buildTwin(job.plan, job.kit, 'low');
const FT = gen.FT, meshes = [];
for (const [key, objects] of out.pieces) for (const root of objects) {
  root.updateWorldMatrix(true, true);
  root.traverse(o => {
    const g = o.geometry, pos = g && g.attributes && g.attributes.position;
    if (!pos) return;
    const nrm = g.attributes.normal, e = o.matrixWorld.elements;
    const verts = [];
    let top = -1e9;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      const wx = e[0] * x + e[4] * y + e[8] * z + e[12], wy = e[1] * x + e[5] * y + e[9] * z + e[13], wz = e[2] * x + e[6] * y + e[10] * z + e[14];
      let ny = 0;
      if (nrm) {
        const nx = nrm.getX(i), nyy = nrm.getY(i), nz = nrm.getZ(i);
        const ax = e[0] * nx + e[4] * nyy + e[8] * nz, ay = e[1] * nx + e[5] * nyy + e[9] * nz, az = e[2] * nx + e[6] * nyy + e[10] * nz;
        ny = ay / (Math.hypot(ax, ay, az) || 1);
      }
      verts.push([wx / FT, -wz / FT, wy / FT, ny]);
      top = Math.max(top, wy / FT);
    }
    // The roof is one big merged mesh; keep it small by sending only vertices under 10.2 ft.
    const small = verts.length < 6000;
    const kept = small ? verts : verts.filter(p => p[2] < 10.2);
    if (kept.length) meshes.push({ key, material: o.material && o.material.name, full: small, verts: kept });
  });
}
console.log(JSON.stringify({ meshes, notes: out.notes === undefined ? null : out.notes }));
"""


def _node():
    return shutil.which('node')


def _wall(wid, a, b):
    return {'id': wid, 'level': 'L1', 'from': a, 'to': b, 'height': 9, 'thickness': 0.5,
            'exterior': True, 'state': 'settled'}


def _plan(awning, bay=False):
    if bay:
        pts = [[0, 0], [19, 0], [19, -1], [28, -1], [28, 0], [31, 0], [31, 22], [0, 22]]
        ids = ['front-a', 'bay-left', 'bay-front', 'bay-right', 'front-b', 'right', 'back', 'left']
    else:
        pts = [[0, 0], [31, 0], [31, 22], [0, 22]]
        ids = ['front', 'right', 'back', 'left']
    walls = [_wall(i, a, b) for i, (a, b) in zip(ids, zip(pts, pts[1:] + pts[:1]))]
    building = {'id': 'poolhouse', 'name': 'Pool house', 'position': [0, 0], 'rotation': 0,
                'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9,
                            'outline': [[0, 0], [31, 0], [31, 22], [0, 22]]}],
                'walls': walls, 'openings': [], 'rooms': [],
                'roof': {'sections': [{'id': 'main', 'kind': 'gable', 'rect': [0, 0, 31, 22], 'ridge': 'y',
                                       'plate': 10.9, 'pitch': 11, 'overhang': 1}],
                         'extensions': [awning]}}
    plan = {'units': 'ft', 'buildings': [building], 'site': {}}
    plan, _notes = twin_plan.normalize(plan)
    return plan


def _awning(**kw):
    a = {'kind': 'awning', 'section': 'main', 'x0': 17.15, 'x1': 30.14, 'depth': 4, 'pitch': 2,
         'eave': 8.75, 'brackets': 2}
    a.update(kw)
    return a


def build(plan):
    d = tempfile.mkdtemp(prefix='twin_awning_js_')
    try:
        with open(os.path.join(d, 'driver.mjs'), 'w', encoding='utf-8') as f:
            f.write(DRIVER)
        job = {'vendor': VENDOR, 'twin': TWIN, 'plan': plan, 'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}}}
        result = subprocess.run(['node', os.path.join(d, 'driver.mjs'), json.dumps(job)],
                                capture_output=True, text=True, timeout=120)
        check(result.returncode == 0, result.stderr[-3000:])
        return json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _extent(verts, axis):
    vals = [v[axis] for v in verts]
    return min(vals), max(vals)


def top_surface(out):
    """The awning's upward-facing roof-material vertices below 9.8 ft.

    The generator merges meshes by material, so the awning panel lives inside
    the main roof's merged mesh and cannot be picked by mesh. The main roof
    (plate 10.9, 1 ft overhang) never reaches below 9.9 ft on its top
    surface, so the roof-material top-surface vertices under 9.8 ft are the
    awning's (and its seam ribs, which share the slope).
    """
    return [p for m in out['meshes'] if m['key'] == 'poolhouse:main' and m['material'] == 'roof'
            for p in m['verts'] if p[3] > 0.9 and p[2] < 9.8]


def bracket_boxes(out):
    """Trim-material meshes chunked back into 24-vertex boxes (merging keeps box order)."""
    boxes = []
    for m in out['meshes']:
        if m['key'] == 'poolhouse:main' and m['material'] == 'trim' and m['full'] and len(m['verts']) % 24 == 0:
            boxes += [m['verts'][i:i + 24] for i in range(0, len(m['verts']), 24)]
    return boxes


def fit(points, axis):
    """Least-squares height = a + b * coordinate(axis); returns (a, b)."""
    n = len(points)
    sx = sum(p[axis] for p in points)
    sy = sum(p[2] for p in points)
    sxx = sum(p[axis] ** 2 for p in points)
    sxy = sum(p[axis] * p[2] for p in points)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return (sy - b * sx) / n, b


def _front_panel(awning=None, bay=False):
    awning = awning or _awning()
    out = build(_plan(awning, bay))
    top = top_surface(out)
    check(len(top) >= 4, ('no awning top surface drawn under the main roof', len(top)))
    return out, None, top


def scenario_awning_slopes_down_away_from_wall():
    out, found, top = _front_panel()
    a, b = fit(top, 1)  # height as a function of plan y; away from the wall is more negative y
    near, far = a + b * -0.2, a + b * -3.8
    check(near > far, ('the awning must be higher at the wall (y=-0.2) than away from it (y=-3.8)', near, far))
    # 3.6 ft of run at 2/12 is 0.60 ft (the brief rounds the 4 ft depth to 0.67).
    check(abs((near - far) - 0.60) <= 0.05 or abs((near - far) - 0.67) <= 0.05, ('drop over 3.6 ft', near - far))


def scenario_awning_low_edge_at_eave():
    out, found, top = _front_panel()
    low = min(p[2] for p in top)
    check(abs(low - 8.75) <= 0.2, ('lowest top vertex at the outer edge should be the eave 8.75', low))
    outer = [p for p in top if p[2] - low < 0.05]
    check(all(p[1] < -3.0 for p in outer), ('the low edge is the outer one (y near -4)', outer[:3]))


def scenario_awning_hangs_from_projecting_wall():
    awning = _awning(wall='bay-front')
    out, found, top = _front_panel(awning, bay=True)
    wall_edge = max(p[1] for p in top)
    # centre line -1, outside face -1.25
    check(-1.3 <= wall_edge <= -0.9, ('the wall-side edge should be at the bay front, plan y about -1, not 0', wall_edge))
    outer = min(p[1] for p in top)
    check(outer < -4.0, ('the outer edge is the depth further out', outer))


def scenario_awning_side_wall():
    awning = _awning(x0=4, x1=17, wall='right')  # span runs along the wall, plan y 4..17
    out = build(_plan(awning))
    top = top_surface(out)
    check(len(top) >= 4, ('no awning top surface on the side wall', len(top)))
    wall_edge_x, outer_x = min(p[0] for p in top), max(p[0] for p in top)
    check(outer_x > 31, ('the outer edge lies beyond the wall at x > 31', outer_x))
    check(30.7 <= wall_edge_x <= 31.4, ('the wall-side edge sits on the right wall', wall_edge_x))
    a, b = fit(top, 0)
    check(b < 0 and a + b * outer_x < a + b * wall_edge_x - 0.3,
          ('the outer edge is lower than the wall edge', a + b * outer_x, a + b * wall_edge_x))


def scenario_awning_without_wall_is_skipped():
    awning = _awning(x0=41, x1=50)  # span midpoint is 10+ ft from every wall
    out = build(_plan(awning))
    check(out['notes'] is not None and 'extension_skipped' in json.dumps(out['notes']),
          ('out.notes must record extension_skipped', out['notes']))
    check(not top_surface(out), 'an awning with no wall nearby must draw no panel')
    check(not bracket_boxes(out), 'an awning with no wall nearby must draw no brackets')


def scenario_awning_brackets_under_it():
    out, found, top = _front_panel()
    awning = _awning()
    a, b = fit(top, 1)
    brackets = []
    for v in bracket_boxes(out):
        xs, ys = _extent(v, 0), _extent(v, 1)
        if (xs[1] - xs[0] <= 0.5 and 1.0 <= ys[1] - ys[0] <= 6.0 and max(p[2] for p in v) < 9.3
                and xs[0] >= awning['x0'] - 0.1 and xs[1] <= awning['x1'] + 0.1):
            brackets.append({'verts': v})
    check(len(brackets) >= 2, ('expected two bracket meshes under the awning', len(brackets)))
    for m in brackets:
        for x, y, h, _n in m['verts']:
            underside = a + b * y - 0.3
            check(h <= underside + 0.05, ('bracket pokes through the awning', (x, y, h), underside))
        # and it actually props the awning: its highest point is within 0.6 ft of the underside there.
        hi = max(m['verts'], key=lambda p: p[2])
        check(a + b * hi[1] - 0.3 - hi[2] <= 0.6, ('bracket does not reach the awning underside', hi, a + b * hi[1] - 0.3))
        back = max(p[1] for p in m['verts'])
        check(-0.45 <= back <= 0.2, ('bracket back face should sit on the wall face (y 0 / -0.25)', back))


SCENARIOS = (
    scenario_awning_slopes_down_away_from_wall,
    scenario_awning_low_edge_at_eave,
    scenario_awning_hangs_from_projecting_wall,
    scenario_awning_side_wall,
    scenario_awning_without_wall_is_skipped,
    scenario_awning_brackets_under_it,
)


if __name__ == '__main__':
    if not _node():
        print('  skip  node is not available')
        sys.exit(0)
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)
