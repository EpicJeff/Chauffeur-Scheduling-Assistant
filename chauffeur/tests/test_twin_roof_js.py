"""Roof surfaces for the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md section 8; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 3): section
heights, the envelope that makes valleys and hips where sections meet, and a
mesh whose every triangle lies on that envelope. Runs static/twin/twin_roof.js
under node (copied to a temp .mjs so node loads it as a module).

Skips (rather than fails) when node is unavailable.

Run from chauffeur/:  python tests/test_twin_roof_js.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, 'static', 'twin', 'twin_roof.js')
LOT58 = os.path.join(ROOT, 'tests', 'fixtures', 'twin_lot58_roof.json')

HIP = {'kind': 'hip', 'rect': [0, 0, 40, 20], 'ridge': 'x', 'pitch': 12, 'plate': 10, 'overhang': 0}
GABLE_X = {**HIP, 'kind': 'gable'}
CROSS = {'kind': 'gable', 'rect': [15, 15, 25, 35], 'ridge': 'y', 'pitch': 12, 'plate': 10, 'overhang': 0}
SHED = {'kind': 'shed', 'rect': [0, 0, 10, 20], 'low_side': 'x1', 'pitch': 3, 'plate': 9, 'overhang': 1}
FLAT = {'kind': 'flat', 'rect': [0, 0, 10, 10], 'pitch': 0, 'plate': 9, 'overhang': 0.5}
UNEVEN = {'kind': 'hip', 'rect': [0, 0, 40, 20], 'ridge': 'x', 'pitch': 12, 'plate': 10, 'overhang': 0,
          'pitches': {'y0': 6, 'y1': 12, 'x0': 12, 'x1': 12}}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-6):
    return len(a) == len(b) and all(x is not None and abs(x - y) <= tol for x, y in zip(a, b))


DRIVER = r"""
import * as roof from './twin_roof.mjs';
const job = JSON.parse(process.argv[2]);
if (job.cover) {
  const sections = job.cover, mesh = roof.roofMesh(sections), p = mesh.positions, n = p.length / 9;
  const pts = job.points || [];
  if (!job.points) for (const s of sections) {
    const [x0, y0, x1, y1] = s.rect;
    for (let x = x0 + 0.25; x < x1; x += 0.5) for (let y = y0 + 0.25; y < y1; y += 0.5) pts.push([x, y]);
  }
  let holes = 0, wrong = 0;
  const holeSamples = [];
  for (const [x, y] of pts) {
    let hit = null;
    for (let i = 0; i < n && hit === null; i++) {
      const ax = p[i*9], ay = p[i*9+1], bx = p[i*9+3], by = p[i*9+4], cx = p[i*9+6], cy = p[i*9+7];
      const d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
      if (Math.abs(d) < 1e-12) continue;
      const l1 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / d;
      const l2 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / d;
      const l3 = 1 - l1 - l2;
      if (l1 >= -1e-9 && l2 >= -1e-9 && l3 >= -1e-9) hit = l1 * p[i*9+2] + l2 * p[i*9+5] + l3 * p[i*9+8];
    }
    const h = roof.heightAt(sections, x, y);
    if (hit === null) { holes++; if (holeSamples.length < 5) holeSamples.push([x, y]); }
    else if (Math.abs(hit - h) > 0.01) wrong++;
  }
  console.log(JSON.stringify({points: pts.length, holes, wrong, holeSamples}));
} else if (job.steps) {
  // stepFaces(sections): triangles in plan feet, z up, nine floats each.
  const q = roof.stepFaces(job.steps);
  console.log(JSON.stringify({float32: q instanceof Float32Array, positions: Array.from(q)}));
} else if (job.call) {
  console.log(JSON.stringify(job.args.map(a => roof[job.call](...a))));
} else {
  const sections = job.mesh;
  const mesh = roof.roofMesh(sections);
  const p = mesh.positions, n = p.length / 9;
  let maxError = 0, buried = 0, uncovered = 0;
  for (let i = 0; i < n; i++) {
    const cx = (p[i*9] + p[i*9+3] + p[i*9+6]) / 3, cy = (p[i*9+1] + p[i*9+4] + p[i*9+7]) / 3,
          cz = (p[i*9+2] + p[i*9+5] + p[i*9+8]) / 3;
    const h = roof.heightAt(sections, cx, cy);
    if (h === null) { uncovered++; continue; }
    maxError = Math.max(maxError, Math.abs(cz - h));
    if (cz < h - 0.01) buried++;
  }
  let gableAbove = 0;
  for (const g of mesh.gables || []) {
    const q = g.positions;
    for (let i = 0; i < q.length / 9; i++) {
      const cx = (q[i*9] + q[i*9+3] + q[i*9+6]) / 3, cy = (q[i*9+1] + q[i*9+4] + q[i*9+7]) / 3,
            cz = (q[i*9+2] + q[i*9+5] + q[i*9+8]) / 3;
      const h = roof.heightAt(sections, cx, cy);
      if (h !== null && cz > h + 0.01) gableAbove++;
    }
  }
  const area = (q, i) => {
    const ax = q[i*9+3]-q[i*9], ay = q[i*9+4]-q[i*9+1], az = q[i*9+5]-q[i*9+2];
    const bx = q[i*9+6]-q[i*9], by = q[i*9+7]-q[i*9+1], bz = q[i*9+8]-q[i*9+2];
    const cx = ay*bz-az*by, cy = az*bx-ax*bz, cz = ax*by-ay*bx;
    return [Math.hypot(cx, cy, cz) / 2, cz];
  };
  let downward = 0;
  for (let i = 0; i < n; i++) if (area(p, i)[1] <= 0) downward++;
  const gableAreas = (mesh.gables || []).map(g => {
    let a = 0; for (let i = 0; i < g.positions.length / 9; i++) a += area(g.positions, i)[0]; return a;
  });
  const gableTriangles = (mesh.gables || []).reduce((t, g) => t + g.positions.length / 9, 0);
  console.log(JSON.stringify({triangles: n, sectionOf: mesh.section.length, maxError, buried, uncovered, gableAbove,
                              downward, gableAreas, gableTriangles}));
}
"""


class Node:
    def __init__(self):
        self.node = shutil.which('node')
        self.dir = tempfile.mkdtemp(prefix='twin_roof_js_')
        shutil.copy(MODULE, os.path.join(self.dir, 'twin_roof.mjs'))
        with open(os.path.join(self.dir, 'driver.mjs'), 'w', encoding='utf-8') as f:
            f.write(DRIVER)

    def run(self, job):
        out = subprocess.run([self.node, os.path.join(self.dir, 'driver.mjs'), json.dumps(job)],
                             capture_output=True, text=True, timeout=60, cwd=self.dir)
        if out.returncode != 0:
            raise AssertionError(out.stderr[-2000:])
        return json.loads(out.stdout.strip().splitlines()[-1])

    def call(self, name, *args):
        return self.run({'call': name, 'args': [list(a) for a in args]})

    def mesh(self, sections):
        return self.run({'mesh': sections})


def scenario_section_heights(js):
    h = js.call('sectionHeight', [HIP, 20, 10], [HIP, 5, 10], [HIP, 20, 2], [GABLE_X, 5, 10], [HIP, 50, 50])
    check(h[:4] == [20, 15, 12, 20] and h[4] is None, h)


def scenario_shed_flat_and_overhang(js):
    h = js.call('sectionHeight', [SHED, 10, 5], [SHED, 0, 5], [SHED, 10.5, 5], [FLAT, 5, 5], [FLAT, 10.4, 5])
    check(close(h, [9, 11.5, 8.875, 9, 9]), h)


def scenario_uneven_pitches(js):
    h = js.call('sectionHeight', [UNEVEN, 20, 2], [UNEVEN, 20, 18])
    check(close(h, [11, 12]), h)   # front slope 6:12 two feet in, rear slope 12:12 two feet in


def scenario_envelope_makes_the_valley(js):
    h = js.call('heightAt', [[HIP, CROSS], 20, 18], [[HIP, CROSS], 16, 18], [[HIP, CROSS], 20, 30],
                [[HIP, CROSS], 100, 100])
    check(close(h[:3], [15, 12, 15]) and h[3] is None, h)


def scenario_every_triangle_lies_on_the_envelope(js):
    with open(LOT58, encoding='utf-8') as f:
        lot58 = json.load(f)['sections']
    for name, sections in (('hip', [HIP]), ('gable', [GABLE_X]), ('cross', [HIP, CROSS]),
                           ('shed', [SHED]), ('lot58', lot58)):
        r = js.mesh(sections)
        check(r['triangles'] > 0 and r['sectionOf'] == r['triangles'], (name, r))
        check(r['maxError'] < 0.01 and r['uncovered'] == 0, (name, r))


def scenario_the_roof_has_no_holes(js):
    # Review finding (Codex, 2026-11-07): subtracting another section's whole
    # footprint instead of its active face removes valid surface; at (16, 18)
    # the HIP is 12 and the CROSS 11, but the CROSS's far plane extended is 19.
    r = js.run({'cover': [HIP, CROSS], 'points': [[16, 18], [20, 18], [16, 10], [20, 30], [24, 16]]})
    check(r['holes'] == 0 and r['wrong'] == 0, r)
    with open(LOT58, encoding='utf-8') as f:
        lot58 = json.load(f)['sections']
    for name, sections in (('hip', [HIP]), ('cross', [HIP, CROSS]), ('shed', [SHED]), ('lot58', lot58)):
        r = js.run({'cover': sections})
        check(r['points'] > 0 and r['holes'] == 0 and r['wrong'] == 0, (name, r))


def scenario_nothing_hides_under_another_section(js):
    with open(LOT58, encoding='utf-8') as f:
        lot58 = json.load(f)['sections']
    for name, sections in (('cross', [HIP, CROSS]), ('lot58', lot58)):
        r = js.mesh(sections)
        check(r['buried'] == 0 and r['gableAbove'] == 0, (name, r))


def scenario_gable_ends_exist_and_face_out(js):
    # Review finding: gableAbove == 0 passes when no gable ends are produced.
    r = js.mesh([GABLE_X])
    check(r['gableTriangles'] == 2 and abs(sum(r['gableAreas']) - 200) < 1e-3, r)   # two ends of 20 x 10 / 2
    flat_over = {'kind': 'flat', 'rect': [-5, -5, 3, 25], 'pitch': 0, 'plate': 12, 'overhang': 0}
    gable = {'kind': 'gable', 'rect': [0, 0, 40, 20], 'ridge': 'x', 'pitch': 12, 'plate': 10, 'overhang': 0}
    r = js.mesh([gable, flat_over])
    check(abs(sum(r['gableAreas']) - (100 + 64)) < 1e-3, r)   # far end whole (100); near end only above z=12: 8 high x 16 wide / 2 = 64


def scenario_every_roof_triangle_faces_up(js):
    with open(LOT58, encoding='utf-8') as f:
        lot58 = json.load(f)['sections']
    for name, sections in (('hip', [HIP]), ('cross', [HIP, CROSS]), ('shed', [SHED]), ('lot58', lot58)):
        r = js.mesh(sections)
        check(r['downward'] == 0, (name, r))


# ---- step faces (plan docs/superpowers/plans/2026-11-08-house-editor-whole-building-draft.md, Task 3)

STEP_A = {'kind': 'hip', 'rect': [0, 0, 20, 20], 'ridge': 'x', 'pitch': 6, 'plate': 10, 'overhang': 0}
STEP_B = {'kind': 'hip', 'rect': [20, 5, 30, 15], 'ridge': 'x', 'pitch': 6, 'plate': 8, 'overhang': 0}


def _triangles(flat):
    return [flat[i:i + 9] for i in range(0, len(flat) - 8, 9)]


def _normal(t):
    """Unit normal (by winding) and area of one triangle of nine floats."""
    u = [t[3] - t[0], t[4] - t[1], t[5] - t[2]]
    v = [t[6] - t[0], t[7] - t[1], t[8] - t[2]]
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    a = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
    return ([c / a for c in n] if a > 1e-12 else [0, 0, 0]), a / 2


def _in_triangle_2d(p, a, b, c, eps=1e-6):
    d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(d) < 1e-12:
        return False
    l1 = ((b[1] - c[1]) * (p[0] - c[0]) + (c[0] - b[0]) * (p[1] - c[1])) / d
    l2 = ((c[1] - a[1]) * (p[0] - c[0]) + (a[0] - c[0]) * (p[1] - c[1])) / d
    return l1 >= -eps and l2 >= -eps and 1 - l1 - l2 >= -eps


def test_step_face_between_overlapping_hips(js):
    """Hip A (plate 10) meets the lower hip B (plate 8) along x = 20, both
    pitch 6, no overhang. The step faces fill the vertical gap there: their
    area is within 2% of the integral of (A - B) over the shared boundary
    (y 5..15, where both sections stand), they lie in the plane x = 20, cover
    every point of the gap, and face +x: outward from the upper section
    towards the lower one, as gable ends face out of theirs. A's other edges
    drop to nothing (free eaves), which is not a step, so they add no area."""
    ys = [5 + (i + 0.5) * 10 / 100 for i in range(100)]
    a = js.call('sectionHeight', *[[STEP_A, 20, y] for y in ys])
    b = js.call('sectionHeight', *[[STEP_B, 20, y] for y in ys])
    integral = sum(ha - hb for ha, hb in zip(a, b)) * 10 / 100
    check(abs(integral - 20) < 1e-6, ('fixture: A is 10 and B is 8 along x = 20, y 5..15', integral))
    r = js.run({'steps': [STEP_A, STEP_B]})
    check(r['float32'], 'stepFaces must return a Float32Array')
    flat = r['positions']
    check(flat and len(flat) % 9 == 0, ('no step faces', len(flat)))
    tris = _triangles(flat)
    area = sum(_normal(t)[1] for t in tris)
    check(abs(area - integral) <= 0.02 * integral, ('step face area', round(area, 4), 'want', integral))
    off_plane = [t for t in tris if any(abs(t[i] - 20) > 1e-3 for i in (0, 3, 6))]
    check(not off_plane, ('step triangles off the x = 20 plane', off_plane[:3]))
    inward = [t for t in tris if _normal(t)[1] > 1e-9 and _normal(t)[0][0] < 0.99]
    check(not inward, ('step triangles must face +x (towards the lower section)', inward[:3]))
    holes = []
    for i in range(20):
        y = 5.25 + i * 0.5
        for z in (8.05, 8.5, 9.0, 9.5, 9.95):
            if not any(_in_triangle_2d((y, z), (t[1], t[2]), (t[4], t[5]), (t[7], t[8])) for t in tris):
                holes.append((y, z))
    check(not holes, (f'{len(holes)}/100 points of the gap are open (y, z)', holes[:8]))


def test_no_step_where_continuous(js):
    """Two coplanar sections that touch give no step faces, with their
    overhangs reaching over each other (a drop to nothing at a free edge is
    not a step either)."""
    flat_a = {'kind': 'flat', 'rect': [0, 0, 10, 10], 'pitch': 0, 'plate': 9, 'overhang': 0.5}
    flat_b = {**flat_a, 'rect': [10, 0, 20, 10]}
    gable_a = {'kind': 'gable', 'rect': [0, 0, 20, 20], 'ridge': 'x', 'pitch': 9, 'plate': 10, 'overhang': 1}
    gable_b = {**gable_a, 'rect': [20, 0, 40, 20]}
    for name, sections in (('flats', [flat_a, flat_b]), ('gables', [gable_a, gable_b])):
        r = js.run({'steps': sections})
        check(r['float32'], 'stepFaces must return a Float32Array')
        area = sum(_normal(t)[1] for t in _triangles(r['positions']))
        check(area < 1e-6, (name, 'step faces where the roof is continuous', len(r['positions']) // 9, round(area, 4)))


if __name__ == '__main__':
    if not shutil.which('node'):
        print('  ..  skipped (node not available)')
    else:
        js = Node()
        failed = []
        for fn in (scenario_section_heights,
                   scenario_shed_flat_and_overhang,
                   scenario_uneven_pitches,
                   scenario_envelope_makes_the_valley,
                   scenario_every_triangle_lies_on_the_envelope,
                   scenario_the_roof_has_no_holes,
                   scenario_nothing_hides_under_another_section,
                   scenario_gable_ends_exist_and_face_out,
                   scenario_every_roof_triangle_faces_up,
                   test_step_face_between_overlapping_hips,
                   test_no_step_where_continuous):
            try:
                fn(js)
            except Exception:
                failed.append(fn.__name__)
                print('  FAIL', fn.__name__)
                traceback.print_exc()
            else:
                print('  ok ', fn.__name__)
        sys.exit(1 if failed else 0)
