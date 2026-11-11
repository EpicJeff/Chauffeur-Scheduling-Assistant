"""The lightmap atlas (Task 1 of docs/superpowers/plans/2026-11-10-house-baked-lights.md;
spec docs/superpowers/specs/2026-11-10-house-baked-lights-design.md, decision 3).

Runs static/twin/twin_generator.js and static/twin/bake/atlas.js under node with
the vendored three (static/vendor/three-r187) resolved for the bare 'three'
imports through a module resolve hook. The house is the household's real one:
tests/fixtures/twin_model/household-2026-11-09.json pushed through
twin_store.push_round (schema 3 assembly) and read back as the flat plan the
scene draws (twin_store.current()), built at tier 'high' with the real
modern_farmhouse kit and an empty manifest (plain materials, nothing fetched).
The driver awaits `ready` before it builds an atlas.

Interface pinned (the plan's, with the room it leaves decided here):

    import { buildAtlas } from './static/twin/bake/atlas.js';
    buildAtlas(group, { density, page, gutter })
      -> { pages, charts: [{ mesh, faces, page, rect }], key }

  - Defaults: density 8 texels/ft, page 2048, gutter 2 (the plan's High values);
    buildAtlas(group) equals buildAtlas(group, {density: 8, page: 2048, gutter: 2}).
  - Which meshes: every mesh under `group` with userData.merged whose material
    is opaque (not material.transparent) and whose material name is not
    'fixture'. Fixture boxes are left out on purpose: the bake key is the
    geometry of walls, openings, roofs, rooms, levels and buildings, not light
    spots, so moving a light by hand must leave the atlas (uv2 and key) exactly
    as it was (Review Focus 4). Transparent meshes (glass, screen) get no chart.
    That covers floors, ceilings (slab undersides, roof undersides, porch
    ceilings) and interior wall faces, along with the exterior faces sharing
    their merged meshes.
  - uv2: a Float32 `uv2` attribute (itemSize 2, one entry per position) set on
    each covered mesh in place. Coordinates are normalised to the chart's page:
    texel = uv2 * page, with the texel inside the chart's rect.
  - charts[i].mesh is the mesh object itself; faces is an array of triangle
    indices into that mesh's geometry (triangle f is vertices 3f..3f+2 for the
    non-indexed merged geometry, or index[3f..3f+2] when indexed); page is an
    integer in [0, pages); rect is {x, y, w, h}, integers in texels, w and h at
    least 1, inside [0, page] on both axes.
  - Gutters: on one page, any two rects are separated by at least `gutter`
    texels along x or along y.
  - Density: within a chart, mapping is an isometry times density: every
    triangle edge of 0.05 ft or more measures density * its length in feet
    (within 1%) in texels. Lengths are in the mesh's own geometry units (plan
    feet; the root's FT scale is outside every level group). A rect is not
    padded beyond its chart's extent (w <= ceil(extent) + 1, same for h).
  - Charts: each chart is one connected (through shared vertex positions),
    coplanar (normals within 1 degree, vertices within 0.02 ft of the plane)
    patch of one mesh. Every face of 1e-6 sq ft or more of a covered mesh is in
    exactly one chart. Charts are not one per triangle: there are at most two
    charts for every three charted faces.
  - Key: a lowercase hex string of 16 to 64 characters, deterministic across
    processes (no material uuids, no Map-order accidents). It changes with the
    atlas parameters, with the geometry (an opening removed) and with a
    building moved on the lot; it does not change when a light is added or
    moved.

Skips (rather than fails) when node is unavailable.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_bake_atlas_js.py
"""
import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_bake_atlas_js_')
os.environ.pop('HA_BASE_URL', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import twin_library as tl  # noqa: E402
from services import twin_store  # noqa: E402

TWIN = os.path.join(ROOT, 'static', 'twin')
ATLAS = os.path.join(TWIN, 'bake', 'atlas.js')
VENDOR = os.path.join(ROOT, 'static', 'vendor', 'three-r187')
HOUSEHOLD = os.path.join(ROOT, 'tests', 'fixtures', 'twin_model', 'household-2026-11-09.json')
DEFAULTS = {'density': 8, 'page': 2048, 'gutter': 2}
KEY_RE = re.compile(r'^[0-9a-f]{16,64}$')
LEVELS = ('main-house:L1', 'main-house:L2', 'main-house:L3', 'pool-house:L1', 'pool-house:L2')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


DRIVER = r"""
import { registerHooks } from 'node:module';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
const job = JSON.parse(readFileSync(process.argv[2], 'utf8'));
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
const THREE = await import('three');
const gen = await import(pathToFileURL(path.join(job.twin, 'twin_generator.js')).href);
const { buildAtlas } = await import(pathToFileURL(job.atlas).href);
const out = gen.buildTwin(job.plan, job.kit, 'high');
await out.ready;
out.root.updateMatrixWorld(true);

const merged = [];
out.root.traverse(o => { if (o.isMesh && o.userData.merged && !o.layers.isEnabled(gen.PICK_LAYER)) merged.push(o); });
const index = new Map(merged.map((m, i) => [m, i]));
const levelOf = o => { for (let p = o.parent; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey; return null; };
const covered = m => !m.material.transparent && m.material.name !== 'fixture';
const vtx = (g, f, k) => g.index ? g.index.getX(3 * f + k) : 3 * f + k;
const tris = g => (g.index ? g.index.count : g.attributes.position.count) / 3;
const P = (g, i) => new THREE.Vector3().fromBufferAttribute(g.attributes.position, i);
const area = (g, f) => { const a = P(g, vtx(g, f, 0)), b = P(g, vtx(g, f, 1)), c = P(g, vtx(g, f, 2)); return b.sub(a).cross(c.sub(a)).length() / 2; };
const normal = (g, f) => { const a = P(g, vtx(g, f, 0)), b = P(g, vtx(g, f, 1)), c = P(g, vtx(g, f, 2)); return b.sub(a).cross(c.sub(a)).normalize(); };
const keyOf = v => `${Math.round(v.x * 1e4)},${Math.round(v.y * 1e4)},${Math.round(v.z * 1e4)}`;
const COS1 = Math.cos(Math.PI / 180);

function summarise(atlas, o) {
  const errors = { rect: [], page: [], faces: [], mesh: [], uvOutside: [], density: [], padded: [], coplanar: [], connected: [], overlap: [], twice: [], uncharted: [], uv2: [] };
  const push = (k, v) => { if (errors[k].length < 6) errors[k].push(v); errors[k].count = (errors[k].count || 0) + 1; };
  const counts = new Map(merged.map(m => [m, new Uint8Array(tris(m.geometry))]));
  const perPage = new Map();
  let chartedFaces = 0, rectArea = 0;
  const charts = atlas.charts || [];
  charts.forEach((c, ci) => {
    const r = c.rect || {};
    if (!index.has(c.mesh)) { push('mesh', { ci, why: 'chart.mesh is not a merged mesh of the group' }); return; }
    if (!covered(c.mesh)) { push('mesh', { ci, why: 'chart on an uncovered mesh', role: c.mesh.material.name }); return; }
    if (![r.x, r.y, r.w, r.h].every(Number.isInteger) || r.w < 1 || r.h < 1 || r.x < 0 || r.y < 0 || r.x + r.w > o.page || r.y + r.h > o.page) push('rect', { ci, rect: r });
    if (!Number.isInteger(c.page) || c.page < 0 || c.page >= atlas.pages) { push('page', { ci, page: c.page, pages: atlas.pages }); return; }
    const g = c.mesh.geometry, n = tris(g), uv2 = g.attributes.uv2;
    if (!Array.isArray(c.faces) || !c.faces.length || !c.faces.every(f => Number.isInteger(f) && f >= 0 && f < n)) { push('faces', { ci }); return; }
    if (!perPage.has(c.page)) perPage.set(c.page, []);
    perPage.get(c.page).push({ ci, ...r });
    rectArea += r.w * r.h;
    const seen = counts.get(c.mesh);
    for (const f of c.faces) { if (seen[f]) push('twice', { ci, f }); seen[f]++; }
    chartedFaces += c.faces.length;
    if (!uv2) return;
    // uv2 inside the rect, and how far the chart's texels actually reach.
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const f of c.faces) for (let k = 0; k < 3; k++) {
      const i = vtx(g, f, k), tx = uv2.getX(i) * o.page, ty = uv2.getY(i) * o.page;
      minX = Math.min(minX, tx); maxX = Math.max(maxX, tx); minY = Math.min(minY, ty); maxY = Math.max(maxY, ty);
      if (tx < r.x - 1e-3 || tx > r.x + r.w + 1e-3 || ty < r.y - 1e-3 || ty > r.y + r.h + 1e-3) push('uvOutside', { ci, f, tx, ty, rect: r });
    }
    if (r.w > Math.ceil(maxX - minX) + 1 || r.h > Math.ceil(maxY - minY) + 1) push('padded', { ci, rect: r, extent: [maxX - minX, maxY - minY] });
    // An isometry times density, edge by edge.
    for (const f of c.faces) {
      if (area(g, f) < 1e-4) continue;
      for (let k = 0; k < 3; k++) {
        const i = vtx(g, f, k), j = vtx(g, f, (k + 1) % 3);
        const len = P(g, i).distanceTo(P(g, j));
        if (len < 0.05) continue;
        const t = Math.hypot((uv2.getX(i) - uv2.getX(j)) * o.page, (uv2.getY(i) - uv2.getY(j)) * o.page);
        const ratio = t / (len * o.density);
        if (Math.abs(ratio - 1) > 0.01) { push('density', { ci, f, len, texels: t, ratio }); break; }
      }
    }
    // One coplanar patch: the largest face sets the plane.
    let ref = c.faces[0], best = -1;
    for (const f of c.faces) { const a = area(g, f); if (a > best) { best = a; ref = f; } }
    const n0 = normal(g, ref), p0 = P(g, vtx(g, ref, 0));
    for (const f of c.faces) {
      if (area(g, f) >= 1e-4 && normal(g, f).dot(n0) < COS1) { push('coplanar', { ci, f, dot: normal(g, f).dot(n0) }); break; }
      let off = false;
      for (let k = 0; k < 3; k++) if (Math.abs(P(g, vtx(g, f, k)).sub(p0).dot(n0)) > 0.02) off = true;
      if (off) { push('coplanar', { ci, f, why: 'off the plane' }); break; }
    }
    // One connected patch through shared vertex positions.
    const parent = new Map();
    const find = x => { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; };
    const join = (a, b) => { parent.set(find(a), find(b)); };
    const byVertex = new Map();
    for (const f of c.faces) {
      parent.set(f, f);
      for (let k = 0; k < 3; k++) {
        const key = keyOf(P(g, vtx(g, f, k)));
        if (byVertex.has(key)) join(f, byVertex.get(key)); else byVertex.set(key, f);
      }
    }
    const roots = new Set(c.faces.map(find));
    if (roots.size > 1) push('connected', { ci, parts: roots.size, faces: c.faces.length });
  });
  // Gutters: any two rects on a page are at least `gutter` apart along x or y.
  for (const [p, rects] of perPage) {
    rects.sort((a, b) => a.x - b.x || a.y - b.y);
    for (let i = 0; i < rects.length; i++) {
      const a = rects[i];
      for (let j = i + 1; j < rects.length; j++) {
        const b = rects[j];
        if (b.x >= a.x + a.w + o.gutter) break;
        const gapX = Math.max(b.x - (a.x + a.w), a.x - (b.x + b.w));
        const gapY = Math.max(b.y - (a.y + a.h), a.y - (b.y + b.h));
        if (Math.max(gapX, gapY) < o.gutter) push('overlap', { page: p, a, b, gapX, gapY });
      }
    }
  }
  const meshes = merged.map((m, i) => {
    const g = m.geometry, uv2 = g.attributes.uv2, n = tris(g);
    let solid = 0;
    for (let f = 0; f < n; f++) {
      if (area(g, f) < 1e-6) continue;
      solid++;
      if (covered(m) && !counts.get(m)[f]) push('uncharted', { i, role: m.material.name, f });
    }
    const ok = !!uv2 && uv2.itemSize === 2 && uv2.count === g.attributes.position.count;
    if (covered(m) && !ok) push('uv2', { i, role: m.material.name, has: !!uv2, itemSize: uv2?.itemSize, count: uv2?.count, positions: g.attributes.position.count });
    const hash = uv2 ? createHash('sha256').update(Buffer.from(uv2.array.buffer, uv2.array.byteOffset, uv2.array.byteLength)).digest('hex') : null;
    return { i, role: m.material.name, level: levelOf(m), covered: covered(m), uv2: ok, hash, faces: n, solid,
             charted: [...counts.get(m)].filter(Boolean).length };
  });
  const pagesUsed = [...perPage.keys()].sort((a, b) => a - b);
  return { key: atlas.key, pages: atlas.pages, charts: charts.length, chartedFaces, rectArea, pagesUsed, meshes,
           errors: Object.fromEntries(Object.entries(errors).map(([k, v]) => [k, { count: v.count || 0, examples: v }])) };
}

const results = [];
for (const opts of job.atlases) {
  const atlas = opts ? buildAtlas(out.root, opts) : buildAtlas(out.root);
  results.push(summarise(atlas, opts || job.defaults));
}
console.log(JSON.stringify(results));
"""


def _node():
    return shutil.which('node')


_FLAT = {}


def household():
    """The flat plan the scene draws for the household's house (a fresh copy)."""
    if 'plan' not in _FLAT:
        with open(HOUSEHOLD, encoding='utf-8') as f:
            twin_store.push_round(json.load(f), 'build')
        _FLAT['plan'] = twin_store.current()
    return copy.deepcopy(_FLAT['plan'])


def building(plan, bid):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def with_light(at):
    plan = household()
    building(plan, 'main-house').setdefault('lights', []).append(
        {'id': 'bake-test-light', 'at': list(at), 'level': 'L1', 'kind': 'pendant', 'room': 'Kitchen'})
    return plan


_RUNS = {}


def run(name, plan_fn, atlases):
    """Build the plan once in a fresh node process and atlas it once per options
    entry (None = the defaults); cached per name for the whole file."""
    if name in _RUNS:
        return _RUNS[name]
    d = tempfile.mkdtemp(prefix='twin_bake_atlas_js_')
    try:
        driver, job_path = os.path.join(d, 'driver.mjs'), os.path.join(d, 'job.json')
        with open(driver, 'w', encoding='utf-8') as f:
            f.write(DRIVER)
        job = {'vendor': VENDOR, 'twin': TWIN, 'atlas': ATLAS, 'plan': plan_fn(), 'defaults': DEFAULTS,
               'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}}, 'atlases': atlases}
        with open(job_path, 'w', encoding='utf-8') as f:
            json.dump(job, f)
        result = subprocess.run(['node', driver, job_path], capture_output=True, text=True, timeout=300)
        check(result.returncode == 0, f'node driver failed ({name}):\n{result.stderr[-3000:]}')
        _RUNS[name] = json.loads(result.stdout.strip().splitlines()[-1])
        return _RUNS[name]
    finally:
        shutil.rmtree(d, ignore_errors=True)


# The main build: one process, several atlases on the same meshes, in place.
MAIN_ATLASES = [None, dict(DEFAULTS), {**DEFAULTS, 'gutter': 4}, {**DEFAULTS, 'density': 4},
                {'density': 2, 'page': 2048, 'gutter': 2}, {'density': 2, 'page': 256, 'gutter': 2}]
DEFAULT, EXPLICIT, WIDE_GUTTER, HALF_DENSITY, SMALL_FEW, SMALL_PAGES = range(len(MAIN_ATLASES))


def main_run():
    return run('main', household, MAIN_ATLASES)


def errors_of(summary, *kinds):
    return {k: summary['errors'][k] for k in kinds if summary['errors'][k]['count']}


def layout(summary):
    """The covered meshes in traversal order: role, level and the uv2 bytes' hash."""
    return [(m['role'], m['level'], m['hash']) for m in summary['meshes'] if m['covered']]


def scenario_same_model_same_atlas():
    first = main_run()[DEFAULT]
    check(isinstance(first['key'], str) and KEY_RE.match(first['key']), f'key is lowercase hex, 16-64 chars: {first["key"]!r}')
    check(all(h for _, _, h in layout(first)), 'every covered mesh has uv2 to compare')
    # Same model, a separate process (fresh material uuids): the same atlas.
    again = run('again', household, [None])[0]
    check(again['key'] == first['key'], ('same model, same key', first['key'], again['key']))
    check(again['pages'] == first['pages'], ('same pages', first['pages'], again['pages']))
    check(layout(again) == layout(first), 'same model, same uv2 bytes on every covered mesh')
    # The defaults are the High values, and an atlas rebuilt in place is the same.
    explicit = main_run()[EXPLICIT]
    check(explicit['key'] == first['key'] and layout(explicit) == layout(first),
          'buildAtlas(group) == buildAtlas(group, {density: 8, page: 2048, gutter: 2}), rebuilt in place')
    # Parameters are in the key.
    for i, what in ((WIDE_GUTTER, 'gutter'), (HALF_DENSITY, 'density'), (SMALL_PAGES, 'page')):
        check(main_run()[i]['key'] != first['key'], f'a different {what} gives a different key')
    # A light added, then moved by hand: fixtures are not in the atlas (Review Focus 4).
    here = run('light-here', lambda: with_light((20.0, 20.0)), [None])[0]
    there = run('light-there', lambda: with_light((26.0, 23.5)), [None])[0]
    check(here['key'] == first['key'] and there['key'] == first['key'],
          ('adding or moving a light never changes the atlas key', first['key'], here['key'], there['key']))
    check(layout(here) == layout(first) and layout(there) == layout(first),
          'adding or moving a light leaves every covered mesh\'s uv2 as it was')
    check(any(m['role'] == 'fixture' and not m['covered'] for m in here['meshes']),
          'the added light\'s fixture box exists and is left out of the atlas')

    # Geometry is in the key: an opening removed, a building moved on the lot.
    def fewer_openings():
        plan = household()
        b = building(plan, 'main-house')
        check(b['openings'], 'the household has openings to remove')
        b['openings'] = b['openings'][1:]
        return plan

    def pool_house_moved():
        plan = household()
        b = building(plan, 'pool-house')
        b['position'] = [b['position'][0] + 5, b['position'][1]]
        return plan
    check(run('fewer-openings', fewer_openings, [None])[0]['key'] != first['key'], 'an opening removed changes the key')
    check(run('pool-moved', pool_house_moved, [None])[0]['key'] != first['key'], 'a building moved on the lot changes the key')


def scenario_charts_never_overlap_and_keep_gutters():
    for i, gutter in ((DEFAULT, 2), (WIDE_GUTTER, 4), (SMALL_PAGES, 2)):
        s = main_run()[i]
        check(s['charts'] > 0, f'charts were made (atlas {i})')
        bad = errors_of(s, 'mesh', 'rect', 'page', 'faces', 'overlap', 'uvOutside')
        check(not bad, (f'atlas {i}: rects integer, inside the page, at least {gutter} texels apart, '
                        f'uv2 inside each rect', bad))


def scenario_texel_density_matches_world_size():
    for i, density in ((DEFAULT, 8), (HALF_DENSITY, 4), (SMALL_PAGES, 2)):
        s = main_run()[i]
        bad = errors_of(s, 'density', 'padded', 'coplanar', 'connected')
        check(not bad, (f'atlas {i}: {density} texels per foot edge by edge, rects fit their chart, '
                        f'each chart one coplanar connected patch', bad))
    # Twice the density, about four times the texels.
    full, half = main_run()[DEFAULT]['rectArea'], main_run()[HALF_DENSITY]['rectArea']
    check(3.0 < full / half < 4.6, ('rect area scales with density squared', full, half))


def scenario_every_interior_face_has_uv2():
    s = main_run()[DEFAULT]
    covered = [m for m in s['meshes'] if m['covered']]
    for level in LEVELS:
        for role in ('floor', 'interior_wall'):
            check(any(m['level'] == level and m['role'] == role for m in covered),
                  f'{level} has a covered {role} mesh (the check is not vacuous)')
    check(any(m['role'] == 'roof' for m in covered), 'roof meshes (top-floor ceilings) are covered')
    check(all(not m['covered'] for m in s['meshes'] if m['role'] in ('glass', 'screen')),
          'glass and screens are not in the atlas')
    bad = errors_of(s, 'uv2', 'uncharted', 'twice', 'mesh')
    check(not bad, ('every covered mesh has uv2 and every face of it is in exactly one chart', bad))
    check(s['charts'] * 3 <= s['chartedFaces'] * 2,
          ('charts join coplanar connected faces, not one per triangle', s['charts'], s['chartedFaces']))


def scenario_pages_grow_when_one_is_full():
    few, many, high = main_run()[SMALL_FEW], main_run()[SMALL_PAGES], main_run()[DEFAULT]
    check(few['pages'] == 1 and few['pagesUsed'] == [0], ('2 texels/ft fits one 2048 page', few['pages'], few['pagesUsed']))
    check(many['pages'] >= 2, ('the same atlas on 256 pages spills onto more', many['pages']))
    check(many['pages'] >= math.ceil(many['rectArea'] / 256 ** 2), ('pages hold no more than their area', many))
    check(many['pagesUsed'] == list(range(many['pages'])), ('every page in use, none skipped', many['pagesUsed'], many['pages']))
    # The household at High (8 texels/ft) is more than one 2048 page.
    check(high['pages'] >= max(2, math.ceil(high['rectArea'] / 2048 ** 2)), ('High needs more than one page', high['pages'], high['rectArea']))
    check(high['pagesUsed'] == list(range(high['pages'])), ('every High page in use', high['pagesUsed'], high['pages']))
    bad = errors_of(many, 'overlap', 'rect', 'page', 'uncharted', 'twice')
    check(not bad, ('spilled pages keep every rule', bad))


SCENARIOS = (
    scenario_same_model_same_atlas,
    scenario_charts_never_overlap_and_keep_gutters,
    scenario_texel_density_matches_world_size,
    scenario_every_interior_face_has_uv2,
    scenario_pages_grow_when_one_is_full,
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
