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
segments are not meshes and are skipped. Materials keep their own side: roofs
are FrontSide with upward winding, so are not hit from below, as in the render.

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
  return { h, section: best, plate: best === null ? null : sections[best].plate,
           all: sections.map(s => roof.sectionHeight(s, x, y)) };
});
if (job.rays || job.bounds || job.triangles) {
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
    const targets = ray.roles ? meshes.filter(o => ray.roles.includes(o.material?.name)) : meshes;
    return caster.intersectObjects(targets, false).slice(0, ray.keep ?? 4).map(hit => {
      const m = Array.isArray(hit.object.material) ? hit.object.material[hit.face?.materialIndex ?? 0] : hit.object.material;
      const n = hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : new THREE.Vector3();
      return { role: m?.name || '', dist: hit.distance, p: [hit.point.x, -hit.point.z, hit.point.y - base], n: [n.x, -n.z, n.y] };
    });
  });
  // Triangles of the named material roles, in plan feet (x, y, height above
  // L1's base), world transforms applied: [ax, ay, az, bx, by, bz, cx, cy, cz].
  if (job.triangles) {
    result.triangles = {};
    const v = new THREE.Vector3();
    for (const role of job.triangles) {
      const out = result.triangles[role] = [];
      for (const o of meshes) {
        const m = Array.isArray(o.material) ? o.material[0] : o.material;
        if ((m?.name || '') !== role) continue;
        const pos = o.geometry.attributes.position, index = o.geometry.index;
        const count = index ? index.count : pos.count;
        for (let i = 0; i + 2 < count; i += 3) {
          const tri = [];
          for (let k = 0; k < 3; k++) {
            v.fromBufferAttribute(pos, index ? index.getX(i + k) : i + k).applyMatrix4(o.matrixWorld);
            tri.push(+v.x.toFixed(4), +(-v.z).toFixed(4), +(v.y - base).toFixed(4));
          }
          out.push(tri);
        }
      }
    }
  }
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


def run(p, rays=None, heights=None, bounds=None, triangles=None):
    d = tempfile.mkdtemp(prefix='twin_joints_js_')
    try:
        driver = os.path.join(d, 'driver.mjs')
        with open(driver, 'w', encoding='utf-8') as f:
            f.write(DRIVER)
        job = {'vendor': VENDOR, 'twin': TWIN, 'plan': p, 'building': BID,
               'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}},
               'rays': rays, 'heights': heights, 'bounds': bounds, 'triangles': triangles}
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


def test_upper_storey_walls_reach_own_roof():
    """Wing roofs cannot cut L2 walls short below the main eave."""
    p = plan()
    b = building(p)
    l2 = level(b, 'L2')
    rays, meta = [], []
    for w in exterior(b, 'L2'):
        d, n, length = wall_frame(w, l2['outline'])
        for z in (3, 6):
            count = 0
            for i in range(1, 20):
                u = length * i / 20
                # Windows are intentional holes; probe the wall beside them.
                if any(o.get('wall') == w['id'] and o['sill'] - 0.4 <= z <= o['head'] + 0.4
                       and abs(u - o['at']) <= o['width'] / 2 + 0.4 for o in b['openings']):
                    continue
                x, y = at(w, d, u)
                rays.append({'o': [x + 3 * n[0], y + 3 * n[1], l2['elevation'] + z],
                             'd': [-n[0], -n[1], 0], 'far': 4})
                meta.append((w['id'], round(u, 2), z))
                count += 1
            check(count > 0, ('no wall samples', w['id'], z))
    hits = run(p, rays=rays)['hits']
    bad = [m for m, hs in zip(meta, hits) if not any(classify(h) in ('wall', 'roof') for h in hs)]
    check(not bad, ('L2 wall rays missed within 4 ft (wall, along, height)', bad[:12]))


def test_upper_storey_windows_within_walls():
    """The complete drawn L2 window, including its trim, fits its wall."""
    p = plan()
    b = building(p)
    walls = {w['id']: w for w in exterior(b, 'L2')}
    openings = [o for o in b['openings'] if o.get('wall') in walls and o['kind'] == 'window']
    check(openings, 'no L2 windows tested')
    keys = [f'{BID}:{wid}' for wid in walls] + [f"{BID}:{o['id']}" for o in openings]
    boxes = run(p, bounds=keys)['bounds']
    rays, meta = [], []
    for o in openings:
        wall_box, window_box = boxes[f"{BID}:{o['wall']}"], boxes[f"{BID}:{o['id']}"]
        check(wall_box is not None and window_box is not None, ('missing wall/window', o['id']))
        check(window_box['min'][2] >= wall_box['min'][2] - 0.01
              and window_box['max'][2] <= wall_box['max'][2] + 0.01,
              ('L2 window extends beyond drawn wall', o['id'], window_box, wall_box))
        w = walls[o['wall']]
        d, n, _ = wall_frame(w, level(b, 'L2')['outline'])
        # Check the actual wall above and below the window across its width;
        # a tall end of a sloping wall must not hide a locally truncated top.
        for f in (-0.5, -0.25, 0, 0.25, 0.5):
            x, y = at(w, d, o['at'] + f * o['width'])
            for z in (window_box['min'][2] - 0.1, window_box['max'][2] + 0.1):
                rays.append({'o': [x + 3 * n[0], y + 3 * n[1], z],
                             'd': [-n[0], -n[1], 0], 'far': 4})
                meta.append((o['id'], f, z))
    hits = run(p, rays=rays)['hits']
    bad = [m for m, hs in zip(meta, hits) if not any(classify(h) == 'wall' for h in hs)]
    check(not bad, ('window lacks surrounding wall at its drawn limits', bad))


def test_lower_roof_stays_outside_upper_rooms():
    """A downward ray inside L2 reaches its floor, without a wing roof."""
    p = plan()
    hits = run(p, rays=[{'o': [34, 45, 18], 'd': [0, 0, -1], 'far': 20, 'keep': 1}])['hits'][0]
    check(hits and hits[0]['role'] == 'floor' and abs(hits[0]['p'][2] - 10.9) <= 0.1,
          ('lower roof intrudes into an L2 room', hits))


def test_storey_roof_plate_limits_and_upper_envelope():
    """R5''': strict lower plate bound, inclusive upper bound, highest cover."""
    p = plan()
    b = building(p)
    b['levels'] = [{'id': 'L1', 'elevation': 5, 'ceiling': 10,
                    'outline': [[0, 0], [10, 0], [10, 10], [0, 10]]}]
    b['walls'] = [{'id': 'probe', 'level': 'L1', 'from': [0, 0], 'to': [10, 0],
                   'height': 7, 'thickness': 0.5, 'exterior': True}]
    b['openings'], b['rooms'] = [], []
    b['roof']['extensions'] = []
    key = f'{BID}:probe'
    # The wall is covered only by the overhang, exercising that part of R5'''.
    def roof(plate):
        return {'kind': 'flat', 'rect': [0, 0.5, 10, 10], 'plate': plate,
                'pitch': 0, 'overhang': 1}
    for plates, expected in (([5.5], 7), ([5.5001], 9.9201),
                             ([17], 11.92), ([17.0001], 7),
                             ([10, 14, 30], 8.92), ([], 7)):
        b['roof']['sections'] = [dict(roof(h), id=f'r{i}') for i, h in enumerate(plates)]
        # A low-plate shed has a high surface here: R9's visible envelope does
        # not hide whether R5 excluded its plate at the strict lower bound.
        for s in b['roof']['sections']:
            if s['plate'] < 6:
                s.update(kind='shed', low_side='y1', pitch=12)
        box = run(p, bounds=[key])['bounds'][key]
        check(box is not None and abs(box['max'][2] - 5 - expected) < 0.001,
              ('storey plate selection / highest envelope', plates, box, expected))


def test_uncovered_knee_walls_capped_by_visible_roof():
    """R9 caps uncovered L2 knees at the lower of both visible roof faces."""
    p = plan()
    b = building(p)
    samples = [('k1', (0.1, 25.33)), ('k5', (58.9, 19.33))]
    points, rays = [], []
    for wid, (x, y) in samples:
        w = next(w for w in b['walls'] if w['id'] == wid)
        points += [[x, y - w['thickness'] / 2], [x, y + w['thickness'] / 2]]
        rays.append({'o': [x, y, 40], 'd': [0, 0, -1], 'far': 40,
                     'keep': 1, 'roles': ['interior_wall']})
    got = run(p, rays=rays, heights=points)
    # Probe the actual knee top outside the main block, rather than its whole
    # piece bounds: the other end of k1 legitimately rises under the main hip.
    for i, ((wid, _), hits) in enumerate(zip(samples, got['hits'])):
        expected = min(h['h'] for h in got['heights'][2 * i:2 * i + 2]) - 0.08
        check(hits and abs(hits[0]['p'][2] - expected) < 0.01,
              ('knee wall pierces visible roof', wid, hits, expected))


# ---- Task 3: roof steps are filled; the roof has thickness, fascia, rake trim
# and soffit (plan docs/superpowers/plans/
# 2026-11-08-house-editor-whole-building-draft.md, Task 3).

def section_bounds(s):
    """A section's plan rect with its overhang, as twin_roof.js bounds()."""
    x0, y0, x1, y1 = s['rect']
    o = s.get('overhang') or 0
    return (x0 - o, y0 - o, x1 + o, y1 + o)


def boundary_distance(poly, pt):
    x, y = pt
    best = math.inf
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best


def inside_spans(poly, o, d, length):
    """Where an axis-aligned plan ray o + t*d, t in [0, length], lies inside
    the polygon: a list of (t0, t1)."""
    ts = []
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
        if d[0]:   # moving along x at fixed y
            y = o[1]
            if (ay > y) != (by > y):
                x = ax + (y - ay) * (bx - ax) / (by - ay)
                ts.append((x - o[0]) / d[0])
        else:      # moving along y at fixed x
            x = o[0]
            if (ax > x) != (bx > x):
                y = ay + (x - ax) * (by - ay) / (bx - ax)
                ts.append((y - o[1]) / d[1])
    ts.sort()
    spans = []
    for t0, t1 in zip(ts[0::2], ts[1::2]):
        a, c = max(t0, 0.0), min(t1, length)
        if c > a:
            spans.append((a, c))
    return spans


def test_rear_seams_closed():
    """Horizontal rays from the rear (travelling -y) and from both sides
    (+x from the left, -x from the right), every 0.5 ft across the building
    (at k/2 + 1/4) and every 0.5 ft in height from 0.5 ft up. The building
    edge of a ray is the first point on its path that a roof section covers
    (rect plus overhang); a ray is cast at every height below heightAt
    there. Each such ray must hit a mesh before it reaches the inside of the
    house.

    Inside the house: a point on the ray's path more than 1 ft inside the
    ground floor's outline (deeper than any wall), more than 0.5 ft below the
    roof (heightAt) there, and not within 1 ft of the upper floor's outline
    when at or above that floor (its walls stand there). The plan's "every
    ray hits a mesh" alone is both too weak and too strong: a ray that slips
    through a seam still hits a floor or an interior wall deep inside, and a
    ray running along under an eave beside a wall hits nothing yet sees
    nothing of the inside. So: a ray that reaches the inside unhit, or
    crosses the house without a hit, fails."""
    p = plan()
    b = building(p)
    l1, l2 = level(b, 'L1'), level(b, 'L2')
    rects = [section_bounds(s) for s in b['roof']['sections']]
    X0, Y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    X1, Y1 = max(r[2] for r in rects), max(r[3] for r in rects)

    def across(lo, hi):
        v = math.floor(lo) + 0.25
        while v < hi:
            yield v
            v += 0.5

    starts = []   # (side, lateral, edge point, direction)
    for x in across(X0, X1):
        ys = [r[3] for r in rects if r[0] <= x <= r[2]]
        if ys:
            starts.append(('rear', x, (x, max(ys)), (0, -1)))
    for y in across(Y0, Y1):
        xs = [r for r in rects if r[1] <= y <= r[3]]
        if xs:
            starts.append(('left', y, (min(r[0] for r in xs), y), (1, 0)))
            starts.append(('right', y, (max(r[2] for r in xs), y), (-1, 0)))
    edge_h = run(p, heights=[list(e[2]) for e in starts])['heights']
    back, far = 3.0, 100.0
    rays, meta = [], []
    for (side, lat, (ex, ey), (dx, dy)), h in zip(starts, edge_h):
        if h['h'] is None:
            continue
        z = 0.5
        while z < h['h'] - 1e-9:
            o = (ex - back * dx, ey - back * dy)
            rays.append({'o': [o[0], o[1], l1['elevation'] + z], 'd': [dx, dy, 0], 'far': far, 'keep': 1})
            meta.append((side, lat, z, round(h['h'], 2), o, (dx, dy)))
            z += 0.5
    check(len(rays) >= 2000, ('too few rays to mean anything', len(rays)))
    hits = run(p, rays=rays)['hits']
    # The path each ray travels unhit, sampled every 0.25 ft wherever it is
    # more than 1 ft inside the ground floor's outline.
    probes, owner = [], []
    for k, ((side, lat, z, he, o, d), hs) in enumerate(zip(meta, hits)):
        reach = (hs[0]['dist'] if hs else far) - 0.05
        for t0, t1 in inside_spans(l1['outline'], o, d, reach):
            t = t0
            while t <= t1:
                q = (o[0] + d[0] * t, o[1] + d[1] * t)
                if boundary_distance(l1['outline'], q) > 1:
                    probes.append(q)
                    owner.append(k)
                t += 0.25
    roof_h = run(p, heights=[list(q) for q in probes])['heights'] if probes else []
    seen = {}
    for k, q, h in zip(owner, probes, roof_h):
        z = l1['elevation'] + meta[k][2]
        if k in seen or h['h'] is None or z >= h['h'] - 0.5:
            continue
        if z >= l2['elevation'] - 0.05 and boundary_distance(l2['outline'], q) <= 1:
            continue
        seen[k] = q
    bad = []
    for k in sorted(seen):
        side, lat, z, he, o, d = meta[k]
        hs = hits[k]
        first = (hs[0]['role'], [round(c, 2) for c in hs[0]['p']]) if hs else 'nothing'
        bad.append((side, lat, z, 'edge roof', he, 'inside at', [round(c, 2) for c in seen[k]], 'first hit', first))
    check(not bad, (f'{len(bad)}/{len(rays)} rays reach the inside of the house through a seam '
                    '(side, across, height, roof at the edge, first inside point, first hit)', bad[:12]))


def _tri_normal(t):
    u = [t[3] - t[0], t[4] - t[1], t[5] - t[2]]
    v = [t[6] - t[0], t[7] - t[1], t[8] - t[2]]
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    a = math.hypot(*n)
    return [c / a for c in n] if a > 1e-12 else None


def test_no_siding_on_roof_faces():
    """No siding lies on a roof face. A non-vertical siding triangle
    (|normal.z| > 0.3) fails when its three corners and its centroid all lie
    within 0.05 ft of the same roof section's surface (sectionHeight): it is
    coplanar with that roof face and fights it in the render. Step faces and
    gable ends are vertical, so they never trip this.

    Narrower than "no non-vertical siding at all", on purpose: every
    extruded wall and batten has flat top and bottom caps in siding (4,584
    horizontal triangles today, none of them on a roof face). The coplanar
    siding Task 2 saw on the front_wing roof face is of this kind: the top
    cap of a wall that follows a rake (the front_wing front gable, drawn as a
    0.5 ft wall because it has a window), lying in the roof plane."""
    p = plan()
    b = building(p)
    tris = run(p, triangles=['siding'])['triangles']['siding']
    sloped = []
    for t in tris:
        n = _tri_normal(t)
        if n is not None and abs(n[2]) > 0.3:
            sloped.append(t)
    check(tris, 'no siding at all')
    pts = []
    for t in sloped:
        pts += [[t[0], t[1]], [t[3], t[4]], [t[6], t[7]],
                [(t[0] + t[3] + t[6]) / 3, (t[1] + t[4] + t[7]) / 3]]
    heights = run(p, heights=pts)['heights'] if pts else []
    names = [s.get('id') or f'roof:{i}' for i, s in enumerate(b['roof']['sections'])]
    bad = []
    for k, t in enumerate(sloped):
        zs = [t[2], t[5], t[8], (t[2] + t[5] + t[8]) / 3]
        hs = heights[4 * k:4 * k + 4]
        for i in range(len(names)):
            if all(h['all'][i] is not None and abs(z - h['all'][i]) <= 0.05 for z, h in zip(zs, hs)):
                bad.append((names[i], [round(c, 2) for c in t], [round(c, 2) for c in _tri_normal(t)]))
                break
    check(not bad, (f'{len(bad)} siding triangles lie on a roof face (section, triangle, normal)', bad[:8]))


def _eave_sides(s):
    """The sides of a section whose edge is an eave (level along its length)."""
    kind = s.get('kind')
    if kind in ('hip', 'flat'):
        return ['x0', 'x1', 'y0', 'y1']
    if kind == 'gable':
        return ['x0', 'x1'] if s.get('ridge') == 'y' else ['y0', 'y1']
    if kind == 'shed':
        return [s['low_side']]
    return []


def free_eave_points(b, step=1.0, corner=0.75):
    """Points every `step` ft along each eave edge of each section's rect
    plus overhang, at least `corner` ft from the section's corners: (section
    index, side, plan point, outward unit normal). The caller keeps those
    where the section is the envelope there and nothing covers the point
    0.05 ft further out (a free edge, not a step onto another section)."""
    out = []
    for i, s in enumerate(b['roof']['sections']):
        X0, Y0, X1, Y1 = section_bounds(s)
        for side in _eave_sides(s):
            if side in ('y0', 'y1'):
                y, n = (Y0, (0, -1)) if side == 'y0' else (Y1, (0, 1))
                u, pts = X0 + corner, []
                while u <= X1 - corner + 1e-9:
                    pts.append((u, y))
                    u += step
            else:
                x, n = (X0, (-1, 0)) if side == 'x0' else (X1, (1, 0))
                u, pts = Y0 + corner, []
                while u <= Y1 - corner + 1e-9:
                    pts.append((x, u))
                    u += step
            out += [(i, side, q, n) for q in pts]
    return out


def _point_triangle_distance(p, t):
    """Distance from point p to triangle t (nine floats), 3D."""
    a, b_, c = t[0:3], t[3:6], t[6:9]
    sub_ = lambda u, v: (u[0] - v[0], u[1] - v[1], u[2] - v[2])
    dot = lambda u, v: u[0] * v[0] + u[1] * v[1] + u[2] * v[2]
    ab, ac, ap = sub_(b_, a), sub_(c, a), sub_(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        q = a
    else:
        bp = sub_(p, b_)
        d3, d4 = dot(ab, bp), dot(ac, bp)
        cp = sub_(p, c)
        d5, d6 = dot(ab, cp), dot(ac, cp)
        vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4
        if d3 >= 0 and d4 <= d3:
            q = b_
        elif vc <= 0 and d1 >= 0 and d3 <= 0:
            v = d1 / (d1 - d3)
            q = tuple(a[i] + v * ab[i] for i in range(3))
        elif d6 >= 0 and d5 <= d6:
            q = c
        elif vb <= 0 and d2 >= 0 and d6 <= 0:
            w = d2 / (d2 - d6)
            q = tuple(a[i] + w * ac[i] for i in range(3))
        elif va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
            w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
            q = tuple(b_[i] + w * (c[i] - b_[i]) for i in range(3))
        else:
            den = va + vb + vc
            if abs(den) < 1e-18:
                q = a
            else:
                v, w = vb / den, vc / den
                q = tuple(a[i] + ab[i] * v + ac[i] * w for i in range(3))
    return math.dist(p, q)


def test_eave_trim_present():
    """Every free eave edge of the envelope has trim (material 'trim', the
    fascia) within 0.3 ft, and the roof there has thickness of at least
    0.15 ft.

    Free eave edge: an eave side of a section (both sides of a hip, the
    long sides of a gable, the low side of a shed), its rect plus overhang,
    sampled every 1 ft at least 0.75 ft from the corners, kept where that
    section is the envelope (heightAt equals its sectionHeight) and nothing
    covers the point 0.05 ft further out. The edge point is at the section's
    height there: the roof's top outer corner.

    Thickness is measured at the same samples, moved in from the edge by
    half the overhang (0.5 ft here): under the overhang, clear of the wall
    whose outside face is on the rect edge (1 ft in, where the plan's
    wording puts it, an upward ray would run along that face). One ray
    straight down from 60 ft must first hit the roof (its top surface); one
    ray straight up from 3 ft below the envelope there finds the underside,
    whatever is first hit from below: the roof's own underside or a soffit
    (the soffit's material is the implementer's choice). Thickness = top hit
    minus underside hit. Today the roof is one double-sided surface, so both
    rays meet the same surface and the thickness is 0."""
    p = plan()
    b = building(p)
    sections = b['roof']['sections']
    cand = free_eave_points(b)
    beyond = [[q[0] + 0.05 * n[0], q[1] + 0.05 * n[1]] for _, _, q, n in cand]
    info = run(p, heights=[list(q) for _, _, q, _ in cand] + beyond)['heights']
    at, out = info[:len(cand)], info[len(cand):]
    free = []
    for (i, side, q, n), h, o in zip(cand, at, out):
        mine = h['all'][i]
        if mine is None or h['h'] is None or abs(h['h'] - mine) > 1e-6 or o['h'] is not None:
            continue
        free.append((i, side, q, n, mine))
    check(len(free) >= 40, ('too few free eave samples to mean anything', len(free)))
    elev = level(b, 'L1')['elevation']
    rays = []
    for i, side, q, n, z in free:
        inset = (sections[i].get('overhang') or 0) / 2
        m = (q[0] - inset * n[0], q[1] - inset * n[1])
        rays.append({'o': [m[0], m[1], 60], 'd': [0, 0, -1], 'far': 80, 'keep': 1})
        rays.append({'o': [m[0], m[1], elev + z - 3], 'd': [0, 0, 1], 'far': 3.5, 'keep': 1})
    got = run(p, rays=rays, triangles=['trim'])
    trim = got['triangles']['trim']
    boxes = [(min(t[0::3]), min(t[1::3]), min(t[2::3]), max(t[0::3]), max(t[1::3]), max(t[2::3])) for t in trim]
    names = [s.get('id') or f'roof:{i}' for i, s in enumerate(sections)]
    no_trim, thin = [], []
    for k, (i, side, q, n, z) in enumerate(free):
        pt = (q[0], q[1], elev + z)
        near = math.inf
        for t, bx in zip(trim, boxes):
            if (bx[0] - 0.3 <= pt[0] <= bx[3] + 0.3 and bx[1] - 0.3 <= pt[1] <= bx[4] + 0.3
                    and bx[2] - 0.3 <= pt[2] <= bx[5] + 0.3):
                near = min(near, _point_triangle_distance(pt, t))
                if near <= 0.3:
                    break
        if near > 0.3:
            no_trim.append((names[i], side, [round(c, 2) for c in pt]))
        down, up = got['hits'][2 * k], got['hits'][2 * k + 1]
        if not down or down[0]['role'] != 'roof':
            thin.append((names[i], side, [round(c, 2) for c in q], 'top is', down[0]['role'] if down else None))
            continue
        if not up:
            thin.append((names[i], side, [round(c, 2) for c in q], 'nothing underneath'))
            continue
        thickness = down[0]['p'][2] - up[0]['p'][2]
        if thickness < 0.15:
            thin.append((names[i], side, [round(c, 2) for c in q], 'thickness', round(thickness, 3), 'under', up[0]['role']))
    check(not no_trim and not thin,
          (f'{len(no_trim)}/{len(free)} free eave points with no trim within 0.3 ft (section, side, point)', no_trim[:8],
           f'{len(thin)}/{len(free)} points where the roof is thinner than 0.15 ft', thin[:8]))


TESTS = (
    test_no_band_under_eaves,
    test_no_wall_above_roof,
    test_corners_closed,
    test_outside_face_on_line,
    test_uncovered_wall_keeps_height,
    test_upper_floor_slab_own_outline,
    test_upper_storey_walls_reach_own_roof,
    test_upper_storey_windows_within_walls,
    test_lower_roof_stays_outside_upper_rooms,
    test_storey_roof_plate_limits_and_upper_envelope,
    test_uncovered_knee_walls_capped_by_visible_roof,
    test_rear_seams_closed,
    test_no_siding_on_roof_faces,
    test_eave_trim_present,
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
