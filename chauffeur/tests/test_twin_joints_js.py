"""Walls meet the roof, sit inside the line and close at the corners (plan
docs/superpowers/plans/2026-11-08-house-editor-whole-building-draft.md,
Task 2; spec docs/superpowers/specs/
2026-11-08-house-editor-whole-building-draft-design.md, "Joints").

Runs static/twin/twin_generator.js under node with the vendored three
(static/vendor/three-r187) resolved for the bare 'three' imports through a
module resolve hook, on the main-house whole-building draft fixture
(tests/fixtures/twin_reads/recorded/claude/draft-main-spike.json) run through
services.twin_plan.normalize. The kit is the real modern_farmhouse kit with an
empty manifest, so every material is a plain coloured one and nothing is
fetched. No renderer: THREE.Raycaster is cast against the built meshes.

Transforms. The test copy pins the building at position [0, 0], rotation 0,
and the driver sets the root scale (FT) back to 1, so world = (x, z + base,
-y) for a plan point (x, y, height z), with base = levelElevations of L1
(groundAt plus building base). Hits are reported back in plan feet.

What a ray may hit. Only meshes a camera would draw: visible all the way up
the parent chain (the gable cutaway group is hidden), not on PICK_LAYER (the
pick proxies), not a ghost (userData.ghost or the 'ghost' material). Line
segments are not meshes and are skipped. Materials keep their own side, so a
roof (front side up) is not hit from below, as in the render.

How a hit is classed. Settled meshes are merged per material, so a hit is
classed by its material role (material.name is the kit role):
  - roof: role 'roof';
  - exterior wall: role 'siding' or 'base' (exterior wall finishes; gable
    fill is siding too, and is a wall face);
  - everything else (trim, window_frame, door, glass, floor, patio_concrete,
    and 'interior_wall', which is also the upper floor slab's edge) is
    neither. A material with no name falls back to its face normal: a face
    whose normal is within 0.3 of horizontal (|n.z| < 0.3) is a wall, any
    other face is a roof.

Two rules beyond the plan's wording, both from the spec's joint check:
  - test_corners_closed also measures each wall's outside face and fails a
    corner whose first hit lies more than 1 inch behind where the two faces
    meet (the square notch). The plan's "within 0.5 ft of the corner" alone
    cannot see a 0.25 ft notch: its deepest point is 0.354 ft away.
  - test_no_wall_above_roof treats hits within 0.02 ft of the first hit as one
    surface, so a piece lying coplanar on the roof does not count as above it.

Skips (rather than fails) when node is unavailable.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_joints_js.py
"""
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

# Before any services import: never the real data dir.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_joints_js_')
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
// Roof height (twin_roof.heightAt) and the section that sets it, per point.
result.heights = (job.heights || []).map(([x, y]) => {
  const h = roof.heightAt(sections, x, y);
  let best = null, top = -Infinity;
  sections.forEach((s, i) => { const z = roof.sectionHeight(s, x, y); if (z !== null && z > top) { top = z; best = i; } });
  return { h, section: best, plate: best === null ? null : sections[best].plate };
});
if (job.rays || job.bounds) {
  const THREE = await import('three');
  const gen = await import(pathToFileURL(path.join(job.twin, 'twin_generator.js')).href);
  const out = gen.buildTwin(job.plan, job.kit, 'low');
  const root = out.root;
  // Work in plan feet: undo the FT scale on the root.
  root.scale.setScalar(1);
  root.updateMatrixWorld(true);
  const base = out.levelElevations[`${job.building}:${building.levels.slice().sort((a, c) => a.elevation - c.elevation)[0].id}`] -
    building.levels.slice().sort((a, c) => a.elevation - c.elevation)[0].elevation;
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
  const toWorld = ([x, y, z]) => new THREE.Vector3(x, z + base, -y);
  const caster = new THREE.Raycaster();
  result.hits = (job.rays || []).map(ray => {
    const d = new THREE.Vector3(ray.d[0], ray.d[2], -ray.d[1]).normalize();
    caster.set(toWorld(ray.o), d); caster.near = 0; caster.far = ray.far ?? Infinity;
    return caster.intersectObjects(meshes, false).slice(0, ray.keep ?? 4).map(hit => {
      const m = Array.isArray(hit.object.material) ? hit.object.material[hit.face?.materialIndex ?? 0] : hit.object.material;
      const n = hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : new THREE.Vector3();
      return { role: m?.name || '', dist: hit.distance, p: [hit.point.x, -hit.point.z, hit.point.y - base], n: [n.x, -n.z, n.y] };
    });
  });
  // Piece bounds are in the building's local frame: plan feet, x, height, -y.
  result.bounds = {};
  for (const key of job.bounds || []) {
    const entry = out.pieceBounds.get(key);
    if (!entry) { result.bounds[key] = null; continue; }
    const { min, max } = entry.box;
    result.bounds[key] = { min: [min.x, -max.z, min.y], max: [max.x, -min.z, max.y] };
  }
}
console.log(JSON.stringify(result));
"""


def _node():
    return shutil.which('node')


_PLAN = None


def plan():
    """The normalized fixture, pinned at the origin with no rotation."""
    global _PLAN
    if _PLAN is None:
        with open(FIXTURE, encoding='utf-8') as f:
            raw = json.load(f)
        normalized, _notes = twin_plan.normalize(raw)
        for b in normalized['buildings']:
            b['position'] = [0, 0]
            b['rotation'] = 0
        _PLAN = normalized
    return copy.deepcopy(_PLAN)


def building(p):
    return next(b for b in p['buildings'] if b['id'] == BID)


def run(p, rays=None, heights=None, bounds=None):
    d = tempfile.mkdtemp(prefix='twin_joints_js_')
    try:
        driver = os.path.join(d, 'driver.mjs')
        with open(driver, 'w', encoding='utf-8') as f:
            f.write(DRIVER)
        job = {'vendor': VENDOR, 'twin': TWIN, 'plan': p, 'building': BID,
               'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}},
               'rays': rays, 'heights': heights, 'bounds': bounds}
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
    # No material role: a near-horizontal normal is a wall face, else a roof face.
    return 'wall' if abs(hit['n'][2]) < 0.3 else 'roof'


# ---- plan geometry helpers -------------------------------------------------

def level(b, lid):
    return next(l for l in b['levels'] if l['id'] == lid)


def inside(poly, pt):
    x, y = pt
    v = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            v = not v
        j = i
    return v


def near_boundary(poly, pt, tol):
    x, y = pt
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) <= tol:
            return True
    return False


def covered(poly, pt, tol=0.05):
    return inside(poly, pt) or near_boundary(poly, pt, tol)


def wall_frame(w, outline):
    """Unit direction along the wall and the outward unit normal (away from the outline)."""
    (x0, y0), (x1, y1) = w['from'], w['to']
    L = math.hypot(x1 - x0, y1 - y0)
    d = ((x1 - x0) / L, (y1 - y0) / L)
    n = (d[1], -d[0])
    mid = ((x0 + x1) / 2, (y0 + y1) / 2)
    if inside(outline, (mid[0] + 0.2 * n[0], mid[1] + 0.2 * n[1])):
        n = (-n[0], -n[1])
    return d, n, L


def at(w, d, u):
    return (w['from'][0] + d[0] * u, w['from'][1] + d[1] * u)


def exterior(b, lid):
    return [w for w in b['walls'] if w.get('exterior') and w['level'] == lid]


# ---- tests -----------------------------------------------------------------

def test_no_band_under_eaves():
    """Rays at 10.2 and 10.7 from 3 ft outside each ground-floor wall under a
    plate-10.9 section meet a wall or the roof before the line + 1 ft."""
    p = plan()
    b = building(p)
    l1, l2 = level(b, 'L1'), level(b, 'L2')
    samples = []
    for w in exterior(b, 'L1'):
        d, n, L = wall_frame(w, l1['outline'])
        for f in (0.1, 0.3, 0.5, 0.7, 0.9):
            samples.append((w, d, n, at(w, d, f * L)))
    info = run(p, heights=[list(s[3]) for s in samples])['heights']
    rays, meta = [], []
    for (w, d, n, pt), h in zip(samples, info):
        # Only where a one-storey (plate 10.9) section sets the roof over the
        # line, the roof there is at least the plate, and no upper floor
        # stands on the line (those walls stop at the floor above instead).
        if h['plate'] is None or abs(h['plate'] - 10.9) > 1e-6 or h['h'] < 10.85:
            continue
        if covered(l2['outline'], pt):
            continue
        for z in (10.2, 10.7):
            rays.append({'o': [pt[0] + 3 * n[0], pt[1] + 3 * n[1], l1['elevation'] + z],
                         'd': [-n[0], -n[1], 0], 'far': 3 + 1})
            meta.append((w['id'], round(pt[0], 2), round(pt[1], 2), z))
    check(len(rays) >= 20, ('too few eave samples to mean anything', len(rays)))
    hits = run(p, rays=rays)['hits']
    open_ = [m for m, hs in zip(meta, hits) if not any(classify(x) in ('wall', 'roof') for x in hs)]
    check(not open_, (f'{len(open_)}/{len(rays)} rays pass through the band under the eaves '
                      '(wall id, x, y, height)', open_[:12]))


def test_no_wall_above_roof():
    """Down from z = 40 just inside each exterior wall's outside face: the
    first thing hit is the roof wherever a section covers the point."""
    p = plan()
    b = building(p)
    outlines = {l['id']: l['outline'] for l in b['levels']}
    samples = []
    for w in b['walls']:
        if not w.get('exterior') or w['level'] not in outlines:
            continue
        d, n, L = wall_frame(w, outlines[w['level']])
        for i in range(20):
            x, y = at(w, d, (i + 0.5) / 20 * L)
            # 0.1 ft in from the outside face line: inside the wall body
            # whether the wall is centred (today) or inside the line (spec).
            samples.append((w['id'], (x - 0.1 * n[0], y - 0.1 * n[1])))
    info = run(p, heights=[list(s[1]) for s in samples])['heights']
    rays = [{'o': [pt[0], pt[1], 40], 'd': [0, 0, -1], 'far': 60, 'keep': 4} for _, pt in samples]
    hits = run(p, rays=rays)['hits']
    bad, uncovered = [], 0
    for (wid, pt), h, hs in zip(samples, info, hits):
        first = hs[0] if hs else None
        if h['h'] is None:
            # No section over the point: there is no roof to stand above.
            uncovered += 1
            continue
        # Hits within 0.02 ft of the first are one surface (coplanar pieces):
        # the roof being among them is the roof being first.
        tied = [x for x in hs if first is not None and x['dist'] - first['dist'] <= 0.02]
        if first is None or not any(classify(x) == 'roof' for x in tied):
            bad.append((wid, round(pt[0], 2), round(pt[1], 2), first and first['role'],
                        first and round(first['p'][2], 2), round(h['h'], 2)))
    check(not bad, (f'{len(bad)}/{len(samples)} points: something stands above the roof '
                    '(wall id, x, y, first role, its height, roof height)', bad[:12]))


def _corners(b, lid):
    """Each exterior corner of a level: the vertex and its two walls."""
    walls = exterior(b, lid)
    out = []
    for a in walls:
        for c in walls:
            if a is c:
                continue
            if math.hypot(a['to'][0] - c['from'][0], a['to'][1] - c['from'][1]) < 1e-6:
                out.append((a, c, tuple(a['to'])))
    return out


def measure_faces(p, b, lids, height=5):
    """Each exterior wall's outside and inside face, as signed offsets from its
    from-to line along the outward normal (outside of the line is positive).

    Rays run perpendicular to the wall at `height` above the level, from 3 ft
    outside inwards and from 3 ft inside outwards, at u every 0.1 ft clear of
    the wall ends (0.75 ft, where a neighbour wall or its corner stands) and of
    openings with their trim (0.6 ft). Battens stand proud of the outside face,
    so the deepest outside hit is the face itself. Walls with fewer than three
    clear samples are not measured."""
    rays, meta, frames = [], [], {}
    for lid in lids:
        l = level(b, lid)
        for w in exterior(b, lid):
            d, n, L = wall_frame(w, l['outline'])
            holes = [(o['at'] - o['width'] / 2, o['at'] + o['width'] / 2)
                     for o in b.get('openings', []) if o.get('wall') == w['id']]
            us, u = [], 0.75
            while u <= L - 0.75 + 1e-9:
                if not any(u0 - 0.6 <= u <= u1 + 0.6 for u0, u1 in holes):
                    us.append(u)
                u += 0.1
            if len(us) < 3:
                continue
            frames[w['id']] = (w, d, n)
            z = l['elevation'] + height
            for u in us:
                x, y = at(w, d, u)
                rays.append({'o': [x + 3 * n[0], y + 3 * n[1], z], 'd': [-n[0], -n[1], 0], 'far': 6, 'keep': 6})
                meta.append((w['id'], 'out', (x, y)))
                rays.append({'o': [x - 3 * n[0], y - 3 * n[1], z], 'd': [n[0], n[1], 0], 'far': 6, 'keep': 6})
                meta.append((w['id'], 'in', (x, y)))
    hits = run(p, rays=rays)['hits'] if rays else []
    found = {}
    for (wid, side, (x, y)), hs in zip(meta, hits):
        walls = [h for h in hs if classify(h) == 'wall']
        if walls:
            n = frames[wid][2]
            off = (walls[0]['p'][0] - x) * n[0] + (walls[0]['p'][1] - y) * n[1]
            found.setdefault((wid, side), []).append(off)
    faces = {}
    for wid in frames:
        outs, ins = found.get((wid, 'out'), []), found.get((wid, 'in'), [])
        faces[wid] = (min(outs) if outs else None, max(ins) if ins else None)
    return faces, frames


def test_corners_closed():
    """At every exterior ground-floor corner, 45 degree rays from outside at
    heights 1, 5 and 9 ft hit a wall within 0.5 ft of the corner.

    Closed also means no notch: the first wall hit is where the two walls'
    outside faces meet (within 1 inch, the spec's joint-check gap), not in a
    square notch behind them. The faces are measured, not assumed, so this
    checks the corner itself; where the walls stand is the face test's job."""
    p = plan()
    b = building(p)
    l1 = level(b, 'L1')
    outline = l1['outline']
    faces, _frames = measure_faces(p, b, ['L1'])
    rays, meta, outward = [], [], {}
    for a, c, v in _corners(b, 'L1'):
        _, na, _ = wall_frame(a, outline)
        _, nc, _ = wall_frame(c, outline)
        # Bisector of the two outward normals: 45 degrees to both walls.
        bx, by = na[0] + nc[0], na[1] + nc[1]
        m = math.hypot(bx, by)
        if m < 1e-9:
            continue
        bx, by = bx / m, by / m
        # Where the two outside faces meet (the walls here are square to each other).
        oa, oc = faces.get(a['id'], (None,))[0], faces.get(c['id'], (None,))[0]
        meet = None if oa is None or oc is None else (v[0] + oa * na[0] + oc * nc[0], v[1] + oa * na[1] + oc * nc[1])
        outward[(a['id'], c['id'])] = (bx, by)
        for z in (1, 5, 9):
            rays.append({'o': [v[0] + 3 * bx, v[1] + 3 * by, l1['elevation'] + z],
                         'd': [-bx, -by, 0], 'far': 6})
            meta.append((a['id'], c['id'], v, meet, z))
    check(len(rays) >= 3 * 20, ('expected every ground-floor corner', len(rays)))
    check(sum(1 for m in meta if m[3] is not None) >= 3 * 10, ('too few corners with both faces measured', len(meta)))
    hits = run(p, rays=rays)['hits']
    bad = []
    for (aid, cid, v, meet, z), hs in zip(meta, hits):
        walls = [x for x in hs if classify(x) == 'wall']
        first = walls[0] if walls else None
        gap = None if first is None else math.hypot(first['p'][0] - v[0], first['p'][1] - v[1])
        if gap is None or gap > 0.5:
            bad.append((aid, cid, v, z, 'off the corner', gap and round(gap, 3)))
            continue
        if meet is not None:
            # How far behind the faces' meeting point the ray went, along the
            # ray. Anything proud of the faces (a batten) reads negative.
            ox, oy = outward[(aid, cid)]
            notch = -((first['p'][0] - meet[0]) * ox + (first['p'][1] - meet[1]) * oy)
            if notch > 1 / 12:
                bad.append((aid, cid, v, z, 'notch behind the faces', round(notch, 3)))
    check(not bad, (f'{len(bad)}/{len(rays)} corner rays find an open corner '
                    '(walls, corner, height, what, ft)', bad[:12]))


def test_outside_face_on_line():
    """Front-facing exterior walls (outside towards -y, the [0,0]-[70,0] style
    segments): the outside face is on the from-to line within 0.02 and the
    inside face is line + thickness."""
    p = plan()
    b = building(p)
    faces, frames = measure_faces(p, b, ['L1', 'L2'])
    front = {wid for wid, (w, d, n) in frames.items() if abs(n[0]) < 1e-6 and n[1] < -0.5}
    check({'w1', 'w3', 'w5', 'w9'} <= front, ('front walls not sampled', sorted(front)))
    bad = []
    for wid in sorted(front):
        w = frames[wid][0]
        out, inn = faces[wid]
        line = w['from'][1]
        # Offsets are outward-positive and outward is -y, so plan y = line - offset.
        if out is None or abs(out) > 0.02:
            bad.append((wid, 'outside face y', out is not None and round(line - out, 3), 'line', line))
        if inn is None or abs(inn + w['thickness']) > 0.02:
            bad.append((wid, 'inside face y', inn is not None and round(line - inn, 3),
                        'want', round(line + w['thickness'], 3)))
    check(not bad, ('walls are not inside the line', bad))


def test_uncovered_wall_keeps_height():
    """With no roof sections, every wall's top is its own height, never infinite."""
    p = plan()
    b = building(p)
    b['roof']['sections'] = []
    b['roof']['extensions'] = []
    keys = [f"{BID}:{w['id']}" for w in b['walls']]
    bounds = run(p, bounds=keys)['bounds']
    elev = {l['id']: l['elevation'] for l in b['levels']}
    bad = []
    for w in b['walls']:
        box = bounds.get(f"{BID}:{w['id']}")
        if box is None:
            bad.append((w['id'], 'no mesh'))
            continue
        top = box['max'][2] - elev[w['level']]
        if not math.isfinite(top) or abs(top - w['height']) > 0.01:
            bad.append((w['id'], 'top', top, 'height', w['height']))
    check(not bad, ('wall tops without a roof', bad))


def test_upper_floor_slab_own_outline():
    """The L2 slab's plan bounds are L2's outline bounds, not L1's."""
    p = plan()
    b = building(p)
    l2 = level(b, 'L2')
    key = f'{BID}:floor:L2'
    box = run(p, bounds=[key])['bounds'][key]
    check(box is not None, 'no L2 floor piece')
    xs = [q[0] for q in l2['outline']]
    ys = [q[1] for q in l2['outline']]
    want = (min(xs), min(ys), max(xs), max(ys))
    got = (box['min'][0], box['min'][1], box['max'][0], box['max'][1])
    check(all(abs(g - e) <= 0.05 for g, e in zip(got, want)),
          ('L2 slab bounds (x0, y0, x1, y1)', [round(g, 3) for g in got], 'want', want))


TESTS = (
    test_no_band_under_eaves,
    test_no_wall_above_roof,
    test_corners_closed,
    test_outside_face_on_line,
    test_uncovered_wall_keeps_height,
    test_upper_floor_slab_own_outline,
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
