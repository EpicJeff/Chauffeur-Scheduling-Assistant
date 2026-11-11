"""The lightmap atlases (Task 1 of docs/superpowers/plans/2026-11-10-house-baked-lights.md,
as amended by Rulings B2, B3 and B5 in .superpowers/sdd/2026-11-10-house-baked-lights/progress.md;
spec docs/superpowers/specs/2026-11-10-house-baked-lights-design.md, decision 3).

Runs static/twin/twin_generator.js and static/twin/bake/atlas.js under node with
the vendored three (static/vendor/three-r187) resolved for the bare 'three'
imports through a module resolve hook. The house is the household's real one:
tests/fixtures/twin_model/household-2026-11-09.json pushed through
twin_store.push_round (schema 3 assembly) and read back as the flat plan the
scene draws (twin_store.current()), built at tier 'high' with the real
modern_farmhouse kit and an empty manifest (plain materials, nothing fetched).
The driver awaits `ready` before it builds an atlas.

Ruling B2: two layouts.
  - SKY atlas, in uv2: every covered mesh (below), 2 texels/ft, per-vertex
    `lmSkyPage` (the page of the face's sky chart).
  - ROOM-LIGHT atlas, in uv3: only the faces a room's light can reach (that
    room's floor, its ceiling, the wall faces looking into it, opening
    reveals), 4 texels/ft by default and 8 on High/Max bakes (B3). Per-vertex
    `lmRoom` (index into atlas.room.rooms,
    -1 for every other face: exterior walls, roof tops) and `lmLightPage` (the
    page of the face's room chart). Each room's charts are packed into the
    room's own region of a shared page. Pages ship as two-channel textures
    (EAC RG11 / BC5, B4), so a bank is two channels (B5): a room's first two
    lights take R and G of its region, a third light opens a second bank.

Interface pinned (the ruling's, with the room it leaves decided here):

    import { buildAtlas, assignChannels } from './static/twin/bake/atlas.js';
    buildAtlas(group, plan, { sky: {density, page, gutter}, room: {density, page, gutter} })
      -> { key,
           sky:  { pages, charts: [{ mesh, faces, page, rect }] },
           room: { pages, rooms: [{ building, level, id, region }],
                   charts: [{ mesh, faces, room, page, rect }] } }
    assignChannels(rooms, lights) -> { [device]: { room, bank, channel } }

  - `plan` is the flat plan the twin was built from (room polygons come from
    it). Defaults: sky {density: 2, page: 2048, gutter: 2}, room {density: 4,
    page: 2048, gutter: 2}; High/Max pass room {density: 8}. A partial layout
    object takes the rest from the defaults. buildAtlas(group, plan) equals buildAtlas(group, plan, defaults).
  - Covered meshes: every mesh under `group` with userData.merged whose material
    is opaque (not material.transparent) and not named 'fixture'. Fixture boxes
    are out of both atlases, so adding or moving lights changes no attribute and
    no key (Review Focus 4). Glass and screens get neither layout.
  - Attributes on every covered mesh, one entry per position: uv2 (itemSize 2),
    lmSkyPage and lmRoom (itemSize 1). uv3 (itemSize 2) and lmLightPage
    (itemSize 1) on every covered mesh that has a room face. Page and room
    values are whole numbers and the same at a face's three vertices. A face
    with lmRoom -1 is in no room chart (its uv3 and lmLightPage mean nothing).
  - uv2 and uv3 are normalised to their own layout's page: texel = uv * page,
    inside the chart's rect.
  - atlas.room.rooms lists every room of the plan with a polygon (porches
    included), buildings in plan order, rooms in plan order, as {building,
    level, id, region}. region is {page, x, y, w, h} in texels (null only for a
    room with no faces); every room chart lies inside its room's region, on the
    region's page; regions on one page never overlap.
  - Charts (both layouts): rects are {x, y, w, h}, whole texels, w and h at
    least 1, inside the page, no wider or taller than their chart's extent
    plus one; on one page any two rects are at least `gutter` texels apart
    along x or along y. chart.mesh is the mesh object; faces are triangle
    indices into its geometry. A chart is one coplanar (normals within 1
    degree, vertices within 0.02 ft of the plane) patch, connected through
    shared vertex positions, of one mesh (and, for the room layout, one room).
    The mapping is an isometry times density: every edge of 0.05 ft or more
    measures density * its length in feet within 1%. At most two charts for
    every three charted faces.
  - Coverage: every face of 1e-6 sq ft or more of a covered mesh is in exactly
    one sky chart; every such face with lmRoom >= 0 is in exactly one room
    chart, of that room.
  - Key: lowercase hex, 16 to 64 characters, the same across processes. It
    changes with either layout's parameters, with an opening removed and with
    a building moved on the lot; never with lights.
  - assignChannels: rooms is any list of {building, id, ...} (atlas.room.rooms
    in use); lights is [{device, building, room}] with room a room id. A light
    takes the next free slot of its room in list order: slot k is bank
    floor(k / 2), channel k % 2. `room` in the answer is the room's index. A
    light whose room is not in the list is left out (it draws real-time).
    Appending a light never moves the lights already placed.

The probes. Rays are cast in the twin's own frame through each building's
level group, against the covered meshes a camera would draw (the hidden gable
cutaway is skipped; FrontSide faces are hit only from the front, as in a
render). The kitchen is the main house's L1 room
room:14e8bce101b54e1aba698138e2a56ddb, x 37-59, y 0-24.67; its neighbour
across the wall at y 24.67 (x 46.33-59) is room:56144f5bfc4d44b0b2796a3c7d7d20a7.
Above the kitchen the first surfaces are the upper floor's slab (interior_wall)
and, at x 40, a sloped roof soffit (porch_ceiling) higher than the level's
ceiling. Those merged faces run over several rooms below, so a face must be
split along the room outlines (or built per room) before it can carry one
lmRoom: a face classified by its centroid lands in the wrong room.

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
DEFAULTS = {'sky': {'density': 2, 'page': 2048, 'gutter': 2}, 'room': {'density': 4, 'page': 2048, 'gutter': 2}}
KEY_RE = re.compile(r'^[0-9a-f]{16,64}$')
LEVELS = ('main-house:L1', 'main-house:L2', 'main-house:L3', 'pool-house:L1', 'pool-house:L2')
HOUSE = 'main-house'
KITCHEN = 'room:14e8bce101b54e1aba698138e2a56ddb'      # L1, x 37-59, y 0-24.67
NEIGHBOUR = 'room:56144f5bfc4d44b0b2796a3c7d7d20a7'    # L1, x 46.33-59, y 24.67-32.5
ATTRS = ('uv2', 'uv3', 'lmSkyPage', 'lmRoom', 'lmLightPage')


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
const { buildAtlas, assignChannels } = await import(pathToFileURL(job.atlas).href);
const output = {};
if (job.assignCases) output.assign = job.assignCases.map(c => assignChannels(c.rooms, c.lights));

if (job.plan) {
const gen = await import(pathToFileURL(path.join(job.twin, 'twin_generator.js')).href);
const out = gen.buildTwin(job.plan, job.kit, 'high');
await out.ready;
out.root.updateMatrixWorld(true);

const merged = [];
out.root.traverse(o => { if (o.isMesh && o.userData.merged && !o.layers.isEnabled(gen.PICK_LAYER)) merged.push(o); });
const index = new Map(merged.map((m, i) => [m, i]));
const levelOf = o => { for (let p = o.parent; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey; return null; };
const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
const covered = m => !m.material.transparent && m.material.name !== 'fixture';
const originalTriangles = merged.filter(covered).reduce((n, m) => n + (m.geometry.index?.count ?? m.geometry.attributes.position.count) / 3, 0);
const vtx = (g, f, k) => g.index ? g.index.getX(3 * f + k) : 3 * f + k;
const tris = g => (g.index ? g.index.count : g.attributes.position.count) / 3;
const P = (g, i) => new THREE.Vector3().fromBufferAttribute(g.attributes.position, i);
const area = (g, f) => { const a = P(g, vtx(g, f, 0)), b = P(g, vtx(g, f, 1)), c = P(g, vtx(g, f, 2)); return b.sub(a).cross(c.sub(a)).length() / 2; };
const normal = (g, f) => { const a = P(g, vtx(g, f, 0)), b = P(g, vtx(g, f, 1)), c = P(g, vtx(g, f, 2)); return b.sub(a).cross(c.sub(a)).normalize(); };
const keyOf = v => `${Math.round(v.x * 1e4)},${Math.round(v.y * 1e4)},${Math.round(v.z * 1e4)}`;
const COS1 = Math.cos(Math.PI / 180);
const merge = o => ({ sky: { ...job.defaults.sky, ...(o?.sky || {}) }, room: { ...job.defaults.room, ...(o?.room || {}) } });
// A face's value of a one-component attribute; NaN when its corners disagree or it is not whole.
const faceValue = (g, name, f) => {
  const a = g.attributes[name]; if (!a) return undefined;
  const v = [0, 1, 2].map(k => a.getX(vtx(g, f, k)));
  return v[0] === v[1] && v[1] === v[2] && Number.isInteger(v[0]) ? v[0] : NaN;
};

function summarise(atlas, o) {
  const errors = {};
  const push = (k, v) => { const e = errors[k] = errors[k] || { count: 0, examples: [] }; e.count++; if (e.examples.length < 6) e.examples.push(v); };
  const rooms = atlas.room?.rooms || [];
  const n = merged.map(m => tris(m.geometry));
  let roomFaces = 0, solidFaces = 0;
  // Attributes.
  merged.forEach((m, i) => {
    if (!covered(m)) return;
    const g = m.geometry, count = g.attributes.position.count;
    const ok = (name, size) => { const a = g.attributes[name]; return !!a && a.itemSize === size && a.count === count; };
    for (const [name, size] of [['uv2', 2], ['lmSkyPage', 1], ['lmRoom', 1]]) if (!ok(name, size)) push('attrs', { i, role: m.material.name, name });
    if (!ok('lmRoom', 1) || !ok('lmSkyPage', 1)) return;
    let mine = 0;
    for (let f = 0; f < n[i]; f++) {
      const r = faceValue(g, 'lmRoom', f), s = faceValue(g, 'lmSkyPage', f);
      if (Number.isNaN(r) || Number.isNaN(s)) { push('faceValues', { i, f, r, s }); continue; }
      if (r < -1 || r >= rooms.length) push('faceValues', { i, f, r, rooms: rooms.length });
      if (area(g, f) >= 1e-6) { solidFaces++; if (r >= 0) { mine++; roomFaces++; } }
    }
    if (mine) {
      for (const [name, size] of [['uv3', 2], ['lmLightPage', 1]]) if (!ok(name, size)) push('attrs', { i, role: m.material.name, name });
      if (ok('lmLightPage', 1)) for (let f = 0; f < n[i]; f++) if (faceValue(g, 'lmRoom', f) >= 0 && Number.isNaN(faceValue(g, 'lmLightPage', f))) push('faceValues', { i, f, name: 'lmLightPage' });
    }
  });
  // Room regions.
  const regionsByPage = new Map();
  rooms.forEach((r, ri) => {
    const g = r.region;
    if (g == null) return;
    if (![g.page, g.x, g.y, g.w, g.h].every(Number.isInteger) || g.x < 0 || g.y < 0 || g.x + g.w > o.room.page || g.y + g.h > o.room.page || g.page < 0 || g.page >= atlas.room.pages) push('region', { ri, region: g });
    if (!regionsByPage.has(g.page)) regionsByPage.set(g.page, []);
    regionsByPage.get(g.page).push({ ri, ...g });
  });
  for (const [p, list] of regionsByPage) for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
    const a = list[i], b = list[j];
    if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) push('regionOverlap', { page: p, a, b });
  }
  const roomChartOf = new Map(merged.map(m => [m, new Int32Array(n[index.get(m)]).fill(-1)]));
  const layout = (kind, L, lo, uvName) => {
    const counts = new Map(merged.map(m => [m, new Uint8Array(n[index.get(m)])]));
    const perPage = new Map();
    let chartedFaces = 0, rectArea = 0;
    const charts = L?.charts || [];
    const E = k => `${kind}.${k}`;
    charts.forEach((c, ci) => {
      const r = c.rect || {};
      if (!index.has(c.mesh)) { push(E('mesh'), { ci, why: 'chart.mesh is not a merged mesh of the group' }); return; }
      if (!covered(c.mesh)) { push(E('mesh'), { ci, why: 'chart on an uncovered mesh', role: c.mesh.material.name }); return; }
      if (![r.x, r.y, r.w, r.h].every(Number.isInteger) || r.w < 1 || r.h < 1 || r.x < 0 || r.y < 0 || r.x + r.w > lo.page || r.y + r.h > lo.page) push(E('rect'), { ci, rect: r });
      if (!Number.isInteger(c.page) || c.page < 0 || c.page >= L.pages) { push(E('page'), { ci, page: c.page, pages: L.pages }); return; }
      const g = c.mesh.geometry, uv = g.attributes[uvName];
      if (!Array.isArray(c.faces) || !c.faces.length || !c.faces.every(f => Number.isInteger(f) && f >= 0 && f < n[index.get(c.mesh)])) { push(E('faces'), { ci }); return; }
      if (kind === 'room') {
        const room = rooms[c.room];
        if (!Number.isInteger(c.room) || !room) { push('room.chartRoom', { ci, room: c.room }); return; }
        const R = room.region;
        if (!R || R.page !== c.page || r.x < R.x || r.y < R.y || r.x + r.w > R.x + R.w || r.y + r.h > R.y + R.h) push('room.outsideRegion', { ci, rect: r, page: c.page, region: R });
        for (const f of c.faces) {
          if (faceValue(g, 'lmRoom', f) !== c.room) { push('room.faceRoom', { ci, f, lmRoom: faceValue(g, 'lmRoom', f), chartRoom: c.room }); break; }
          if (faceValue(g, 'lmLightPage', f) !== c.page) { push('room.facePage', { ci, f, lmLightPage: faceValue(g, 'lmLightPage', f), page: c.page }); break; }
        }
        const of = roomChartOf.get(c.mesh);
        for (const f of c.faces) of[f] = of[f] === -1 ? c.room : -2;
      } else {
        for (const f of c.faces) if (faceValue(g, 'lmSkyPage', f) !== c.page) { push('sky.facePage', { ci, f, lmSkyPage: faceValue(g, 'lmSkyPage', f), page: c.page }); break; }
      }
      if (!perPage.has(c.page)) perPage.set(c.page, []);
      perPage.get(c.page).push({ ci, ...r });
      rectArea += r.w * r.h;
      const seen = counts.get(c.mesh);
      for (const f of c.faces) { if (seen[f]) push(E('twice'), { ci, f }); seen[f]++; }
      chartedFaces += c.faces.length;
      if (!uv) { push(E('noUv'), { ci, uvName }); return; }
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const f of c.faces) for (let k = 0; k < 3; k++) {
        const i = vtx(g, f, k), tx = uv.getX(i) * lo.page, ty = uv.getY(i) * lo.page;
        minX = Math.min(minX, tx); maxX = Math.max(maxX, tx); minY = Math.min(minY, ty); maxY = Math.max(maxY, ty);
        if (tx < r.x - 1e-3 || tx > r.x + r.w + 1e-3 || ty < r.y - 1e-3 || ty > r.y + r.h + 1e-3) push(E('uvOutside'), { ci, f, tx, ty, rect: r });
      }
      if (r.w > Math.ceil(maxX - minX) + 1 || r.h > Math.ceil(maxY - minY) + 1) push(E('padded'), { ci, rect: r, extent: [maxX - minX, maxY - minY] });
      for (const f of c.faces) {
        if (area(g, f) < 1e-4) continue;
        for (let k = 0; k < 3; k++) {
          const i = vtx(g, f, k), j = vtx(g, f, (k + 1) % 3);
          const len = P(g, i).distanceTo(P(g, j));
          if (len < 0.05) continue;
          const t = Math.hypot((uv.getX(i) - uv.getX(j)) * lo.page, (uv.getY(i) - uv.getY(j)) * lo.page);
          const ratio = t / (len * lo.density);
          if (Math.abs(ratio - 1) > 0.01) { push(E('density'), { ci, f, len, texels: t, ratio }); break; }
        }
      }
      let ref = c.faces[0], best = -1;
      for (const f of c.faces) { const a = area(g, f); if (a > best) { best = a; ref = f; } }
      const n0 = normal(g, ref), p0 = P(g, vtx(g, ref, 0));
      for (const f of c.faces) {
        if (area(g, f) >= 1e-4 && normal(g, f).dot(n0) < COS1) { push(E('coplanar'), { ci, f, dot: normal(g, f).dot(n0) }); break; }
        let off = false;
        for (let k = 0; k < 3; k++) if (Math.abs(P(g, vtx(g, f, k)).sub(p0).dot(n0)) > 0.02) off = true;
        if (off) { push(E('coplanar'), { ci, f, why: 'off the plane' }); break; }
      }
      const parent = new Map();
      const find = x => { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; };
      const byVertex = new Map();
      for (const f of c.faces) {
        parent.set(f, f);
        for (let k = 0; k < 3; k++) {
          const key = keyOf(P(g, vtx(g, f, k)));
          if (byVertex.has(key)) parent.set(find(f), find(byVertex.get(key))); else byVertex.set(key, f);
        }
      }
      const roots = new Set(c.faces.map(find));
      if (roots.size > 1) push(E('connected'), { ci, parts: roots.size, faces: c.faces.length });
    });
    for (const [p, rects] of perPage) {
      rects.sort((a, b) => a.x - b.x || a.y - b.y);
      for (let i = 0; i < rects.length; i++) {
        const a = rects[i];
        for (let j = i + 1; j < rects.length; j++) {
          const b = rects[j];
          if (b.x >= a.x + a.w + lo.gutter) break;
          const gapX = Math.max(b.x - (a.x + a.w), a.x - (b.x + b.w));
          const gapY = Math.max(b.y - (a.y + a.h), a.y - (b.y + b.h));
          if (Math.max(gapX, gapY) < lo.gutter) push(E('overlap'), { page: p, a, b, gapX, gapY });
        }
      }
    }
    // Coverage.
    merged.forEach((m, i) => {
      if (!covered(m) || !m.geometry.attributes.lmRoom) return;
      const g = m.geometry, seen = counts.get(m);
      for (let f = 0; f < n[i]; f++) {
        const inRoom = faceValue(g, 'lmRoom', f) >= 0;
        if (kind === 'room' && !inRoom) { if (seen[f]) push('room.stray', { i, role: m.material.name, f }); continue; }
        if (area(g, f) >= 1e-6 && !seen[f]) push(E('uncharted'), { i, role: m.material.name, f });
      }
    });
    return { pages: L?.pages, charts: charts.length, chartedFaces, rectArea,
             pagesUsed: [...perPage.keys()].sort((a, b) => a - b) };
  };
  const sky = layout('sky', atlas.sky, o.sky, 'uv2');
  const room = layout('room', atlas.room, o.room, 'uv3');
  const hash = a => a ? createHash('sha256').update(Buffer.from(a.array.buffer, a.array.byteOffset, a.array.byteLength)).digest('hex') : null;
  const meshes = merged.map((m, i) => ({ i, role: m.material.name, level: levelOf(m), covered: covered(m),
    hashes: Object.fromEntries(job.attrs.map(name => [name, hash(m.geometry.attributes[name])])) }));
  // Probes: plan feet through a building's level group; the first covered, shown mesh hit.
  const targets = merged.filter(m => covered(m) && shown(m));
  const groupOf = key => { let found = null; out.root.traverse(o => { if (!found && o.userData.levelKey === key) found = o; }); return found; };
  const probes = (job.probes || []).map(pr => {
    const g = groupOf(`${pr.building}:${pr.level}`);
    if (!g) return { name: pr.name, error: 'no level group' };
    const toWorld = ([x, y, h]) => g.localToWorld(new THREE.Vector3(x, h, -y));
    const from = toWorld(pr.from), to = toWorld(pr.to);
    const ray = new THREE.Raycaster(from, to.clone().sub(from).normalize());
    const hit = ray.intersectObjects(targets, false)[0];
    if (!hit) return { name: pr.name, hit: false };
    const m = hit.object, geo = m.geometry, f = hit.faceIndex;
    const local = g.worldToLocal(hit.point.clone());
    const nn = normal(geo, f);
    return { name: pr.name, hit: true, role: m.material.name, level: levelOf(m), dist: hit.distance / gen.FT,
             point: [local.x, -local.z, local.y], normal: [nn.x, -nn.z, nn.y],
             lmRoom: faceValue(geo, 'lmRoom', f) ?? null, lmLightPage: faceValue(geo, 'lmLightPage', f) ?? null,
             roomChart: roomChartOf.get(m)[f], mesh: index.get(m), face: f };
  });
  return { key: atlas.key, sky, room, roomFaces, solidFaces, meshes, probes, errors,
           rooms: rooms.map(r => ({ building: r.building, level: r.level, id: r.id, region: r.region ?? null })) };
}

output.atlases = [];
let last = null;
for (const o of job.atlases) {
  const start = performance.now();
  last = o ? buildAtlas(out.root, job.plan, o) : buildAtlas(out.root, job.plan);
  const buildMs = performance.now() - start;
  output.atlases.push(summarise(last, merge(o)));
  Object.assign(output.atlases.at(-1), { buildMs, originalTriangles,
    triangles: merged.filter(covered).reduce((n, m) => n + tris(m.geometry), 0) });
}
if (job.lights) output.lights = assignChannels(last.room.rooms, job.lights);
if (job.lights && job.sparseBanks) {
  const banks = last.room.packBanks(job.lights);
  output.emptyBanks = last.room.packBanks([]);
  output.bankRemapsExact = banks.every(b => b.charts.every(c => {
    const source = last.room.charts.find(s => s.mesh === c.mesh && s.faces === c.faces);
    const r = b.rooms.find(r => r.room === c.room);
    return source && r && c.rect.w === source.rect.w && c.rect.h === source.rect.h &&
      c.rect.x - source.rect.x === r.region.x - r.sourceRegion.x &&
      c.rect.y - source.rect.y === r.region.y - r.sourceRegion.y;
  }));
  output.banks = banks.map(b => ({ bank: b.bank, pages: b.pages, rooms: b.rooms,
    charts: b.charts.map(c => ({ room: c.room, page: c.page, rect: c.rect, faces: c.faces,
      mesh: index.get(c.mesh) })) }));
}
}
if (job.clipCase) {
  // An indexed, sloped ceiling crosses a concave room, another room, and exterior.
  // Both winding and all interpolated source attributes must survive the rebuild.
  const root = new THREE.Group(), level = new THREE.Group();
  level.userData.buildingId = 'b'; level.userData.levelKey = 'b:L2'; root.add(level);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute([-1, 9.9, 1, 9, 10.9, 1, 9, 10.9, -9, -1, 9.9, -9], 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute([-1, -1, 9, -1, 9, 9, -1, 9], 2));
  g.setAttribute('colourWeight', new THREE.Float32BufferAttribute([-3, 7, 27, 17], 1));
  g.setIndex([0, 2, 1, 0, 3, 2]); g.computeVertexNormals(); // down-facing
  const mesh = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ name: 'interior_wall' }));
  mesh.userData.merged = true; level.add(mesh);
  const plan = { buildings: [{ id: 'b', levels: [{ id: 'L1', elevation: 0 }, { id: 'L2', elevation: 11 }], rooms: [
    { id: 'concave', level: 'L1', polygon: [[0, 0], [5, 0], [5, 3], [3, 3], [3, 8], [0, 8]] },
    { id: 'right', level: 'L1', polygon: [[5, 0], [8, 0], [8, 8], [5, 8]] },
    { id: 'upper', level: 'L2', polygon: [[0, 0], [8, 0], [8, 8], [0, 8]] }
  ] }] };
  const atlas = buildAtlas(root, plan), geo = mesh.geometry, a = geo.attributes;
  output.clip = { indexed: !!geo.index, replaced: geo !== g,
    positions: Array.from(a.position.array), uv: Array.from(a.uv.array),
    weight: Array.from(a.colourWeight.array), normal: Array.from(a.normal.array),
    room: Array.from(a.lmRoom.array), rooms: atlas.room.rooms,
    chartFaces: atlas.room.charts.flatMap(c => c.faces) };
}
console.log(JSON.stringify(output));
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
    building(plan, HOUSE).setdefault('lights', []).append(
        {'id': 'bake-test-light', 'at': list(at), 'level': 'L1', 'kind': 'pendant', 'room': 'Kitchen'})
    return plan


def _center(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]


def forty_lights():
    """The household with 40 lights: six in the kitchen (three banks), the rest round
    the other rooms (at most two each, one bank)."""
    plan = household()
    rooms = [(b, r) for b in plan['buildings'] for r in b['rooms'] if len(r.get('polygon') or []) >= 3]
    kitchen = next(x for x in rooms if x[1]['id'] == KITCHEN)
    others = [x for x in rooms if x is not kitchen]
    placed = [kitchen] * 6 + [others[i % len(others)] for i in range(34)]
    lights = []
    for n, (b, r) in enumerate(placed):
        at = _center(r['polygon'])
        b.setdefault('lights', []).append({'id': f'bake-light-{n:02d}', 'at': [at[0] + (n % 3), at[1]], 'level': r['level'],
                                           'kind': 'recessed', 'room': r.get('name') or 'Room'})
        lights.append({'device': f'light.bake_{n:02d}', 'building': b['id'], 'room': r['id']})
    return plan, lights


_RUNS = {}


def run(name, plan_fn=None, atlases=(None,), probes=(), lights=None, assign_cases=None, sparse_banks=False, clip_case=False):
    """One fresh node process: build the plan once, atlas it once per options
    entry (None = the defaults), probe each; cached per name for the file."""
    if name in _RUNS:
        return _RUNS[name]
    d = tempfile.mkdtemp(prefix='twin_bake_atlas_js_')
    try:
        driver, job_path = os.path.join(d, 'driver.mjs'), os.path.join(d, 'job.json')
        with open(driver, 'w', encoding='utf-8') as f:
            f.write(DRIVER)
        job = {'vendor': VENDOR, 'twin': TWIN, 'atlas': ATLAS, 'plan': plan_fn() if plan_fn else None,
               'defaults': DEFAULTS, 'kit': {**tl.kit('modern_farmhouse'), 'manifest': {}}, 'atlases': list(atlases),
               'probes': list(probes), 'lights': lights, 'assignCases': assign_cases, 'attrs': list(ATTRS)}
        job.update(sparseBanks=sparse_banks, clipCase=clip_case)
        with open(job_path, 'w', encoding='utf-8') as f:
            json.dump(job, f)
        result = subprocess.run(['node', driver, job_path], capture_output=True, text=True, timeout=300)
        check(result.returncode == 0, f'node driver failed ({name}):\n{result.stderr[-3000:]}')
        _RUNS[name] = json.loads(result.stdout.strip().splitlines()[-1])
        return _RUNS[name]
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- probes (plan feet: [x, y, height above the building's base]) -------------

FLOOR_SPOTS = ((40.0, 4.0), (48.0, 12.3), (56.0, 20.0))
WALL_XS = (47.5, 49.0, 50.5, 52.0, 53.5, 55.0, 56.5, 58.0)
OUTSIDE_XS = (40.0, 44.0, 48.0, 52.0, 56.0)
PROBES = (
    [{'name': f'floor@{x},{y}', 'building': HOUSE, 'level': 'L1', 'from': [x, y, 1.5], 'to': [x, y, -5]} for x, y in FLOOR_SPOTS]
    + [{'name': f'ceiling@{x},{y}', 'building': HOUSE, 'level': 'L1', 'from': [x, y, 1.5], 'to': [x, y, 60]} for x, y in FLOOR_SPOTS]
    + [{'name': f'roof@{x},{y}', 'building': HOUSE, 'level': 'L1', 'from': [x, y, 200], 'to': [x, y, -5]} for x, y in FLOOR_SPOTS]
    + [{'name': f'kitchen-side@{x}', 'building': HOUSE, 'level': 'L1', 'from': [x, 22.0, 1.5], 'to': [x, 40.0, 1.5]} for x in WALL_XS]
    + [{'name': f'neighbour-side@{x}', 'building': HOUSE, 'level': 'L1', 'from': [x, 27.5, 1.5], 'to': [x, 0.0, 1.5]} for x in WALL_XS]
    + [{'name': f'outside@{x}', 'building': HOUSE, 'level': 'L1', 'from': [x, -20.0, 1.5], 'to': [x, 10.0, 1.5]} for x in OUTSIDE_XS]
)

# The main build: one process, several atlases on the same meshes, in place.
MAIN_ATLASES = [None, copy.deepcopy(DEFAULTS), {'sky': {'gutter': 4}, 'room': {'gutter': 4}},
                {'room': {'density': 8}}, {'sky': {'density': 4}},
                {'sky': {'page': 256}, 'room': {'page': 1024}}]
DEFAULT, EXPLICIT, WIDE_GUTTER, HIGH, SKY_DENSE, SMALL_PAGES = range(len(MAIN_ATLASES))


def main_run():
    return run('main', household, MAIN_ATLASES, PROBES)['atlases']


def errors_of(summary, *prefixes):
    return {k: v for k, v in summary['errors'].items() if v['count'] and k.startswith(prefixes)}


def layout(summary):
    """The covered meshes in traversal order: role, level and every atlas attribute's hash."""
    return [(m['role'], m['level'], tuple(m['hashes'][a] for a in ATTRS)) for m in summary['meshes'] if m['covered']]


def room_index(summary, rid, bid=HOUSE):
    found = [i for i, r in enumerate(summary['rooms']) if r['building'] == bid and r['id'] == rid]
    check(len(found) == 1, f'{bid}/{rid} is listed once in atlas.room.rooms: {found}')
    return found[0]


def probes(summary, prefix):
    return [p for p in summary['probes'] if p['name'].startswith(prefix)]


def inside(poly, x, y):
    hit = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


# --- the guarantees kept from the single-atlas tests -------------------------

def scenario_same_model_same_atlas():
    first = main_run()[DEFAULT]
    check(isinstance(first['key'], str) and KEY_RE.match(first['key']), f'key is lowercase hex, 16-64 chars: {first["key"]!r}')
    check(all(h[0] and h[2] and h[3] for _, _, h in layout(first)), 'every covered mesh has uv2, lmSkyPage and lmRoom to compare')
    check(any(h[1] and h[4] for _, _, h in layout(first)), 'some covered mesh has uv3 and lmLightPage to compare')
    # Same model, a separate process (fresh material uuids): the same atlases.
    again = run('again', household)['atlases'][0]
    check(again['key'] == first['key'], ('same model, same key', first['key'], again['key']))
    check((again['sky']['pages'], again['room']['pages']) == (first['sky']['pages'], first['room']['pages']), 'same pages')
    check(again['rooms'] == first['rooms'], 'same rooms and regions')
    check(layout(again) == layout(first), 'same model, the same bytes in every atlas attribute of every covered mesh')
    explicit = main_run()[EXPLICIT]
    check(explicit['key'] == first['key'] and layout(explicit) == layout(first),
          'buildAtlas(group, plan) == buildAtlas(group, plan, defaults), rebuilt in place')
    for i, what in ((WIDE_GUTTER, 'gutter'), (HIGH, 'room density (High)'), (SKY_DENSE, 'sky density'), (SMALL_PAGES, 'page')):
        check(main_run()[i]['key'] != first['key'], f'a different {what} gives a different key')

    def fewer_openings():
        plan = household()
        b = building(plan, HOUSE)
        check(b['openings'], 'the household has openings to remove')
        b['openings'] = b['openings'][1:]
        return plan

    def pool_house_moved():
        plan = household()
        b = building(plan, 'pool-house')
        b['position'] = [b['position'][0] + 5, b['position'][1]]
        return plan
    check(run('fewer-openings', fewer_openings)['atlases'][0]['key'] != first['key'], 'an opening removed changes the key')
    check(run('pool-moved', pool_house_moved)['atlases'][0]['key'] != first['key'], 'a building moved on the lot changes the key')


def scenario_a_light_added_or_moved_changes_no_atlas():
    first = main_run()[DEFAULT]
    here = run('light-here', lambda: with_light((44.0, 10.0)))['atlases'][0]
    there = run('light-there', lambda: with_light((52.0, 18.5)))['atlases'][0]
    check(here['key'] == first['key'] and there['key'] == first['key'],
          ('adding or moving a light never changes the atlas key', first['key'], here['key'], there['key']))
    check(layout(here) == layout(first) and layout(there) == layout(first),
          'adding or moving a light leaves every atlas attribute of every covered mesh as it was')
    check(here['rooms'] == first['rooms'], 'and every room region')
    check(any(m['role'] == 'fixture' and not m['covered'] for m in here['meshes']),
          'the added light\'s fixture box exists and is left out of both atlases')


def scenario_charts_never_overlap_and_keep_gutters():
    for i in (DEFAULT, WIDE_GUTTER, HIGH, SMALL_PAGES):
        s = main_run()[i]
        check(s['sky']['charts'] > 0 and s['room']['charts'] > 0, f'charts were made in both layouts (atlas {i})')
        bad = errors_of(s, 'sky.mesh', 'sky.rect', 'sky.page', 'sky.faces', 'sky.overlap', 'sky.uvOutside', 'sky.noUv',
                        'room.mesh', 'room.rect', 'room.page', 'room.faces', 'room.overlap', 'room.uvOutside', 'room.noUv',
                        'room.chartRoom', 'room.outsideRegion', 'region')
        check(not bad, (f'atlas {i} ({MAIN_ATLASES[i]}): rects whole, inside their page and their room region, '
                        f'gutters kept, uv inside each rect, regions apart', bad))


def scenario_texel_density_matches_world_size():
    for i in (DEFAULT, HIGH, SKY_DENSE, SMALL_PAGES):
        s = main_run()[i]
        bad = errors_of(s, 'sky.density', 'sky.padded', 'sky.coplanar', 'sky.connected',
                        'room.density', 'room.padded', 'room.coplanar', 'room.connected')
        check(not bad, (f'atlas {i} ({MAIN_ATLASES[i]}): each layout at its own texels per foot, rects fit their '
                        f'chart, each chart one coplanar connected patch', bad))
    d, high, sky = main_run()[DEFAULT], main_run()[HIGH], main_run()[SKY_DENSE]
    check(3.0 < sky['sky']['rectArea'] / d['sky']['rectArea'] < 4.6, ('sky at 4 is about four times sky at 2', d['sky'], sky['sky']))
    check(3.0 < high['room']['rectArea'] / d['room']['rectArea'] < 4.6, ('room at 8 (High) is about four times room at 4', d['room'], high['room']))
    check(high['sky']['rectArea'] == d['sky']['rectArea'], 'the room density leaves the sky layout alone')


def scenario_every_interior_face_has_uv2():
    s = main_run()[DEFAULT]
    covered = [m for m in s['meshes'] if m['covered']]
    for level in LEVELS:
        for role in ('floor', 'interior_wall'):
            check(any(m['level'] == level and m['role'] == role for m in covered),
                  f'{level} has a covered {role} mesh (the check is not vacuous)')
    check(any(m['role'] == 'roof' for m in covered), 'roof meshes are covered by the sky atlas')
    check(all(not m['covered'] for m in s['meshes'] if m['role'] in ('glass', 'screen')), 'glass and screens get neither layout')
    bad = errors_of(s, 'attrs', 'faceValues', 'sky.uncharted', 'sky.twice', 'sky.facePage',
                    'room.uncharted', 'room.twice', 'room.stray', 'room.faceRoom', 'room.facePage')
    check(not bad, ('every covered face in one sky chart; every room face in one chart of its room; no other face '
                    'in a room chart', bad))
    check(0 < s['roomFaces'] < s['solidFaces'], ('some faces are room faces, not all', s['roomFaces'], s['solidFaces']))
    check(not errors_of(main_run()[HIGH], 'attrs', 'faceValues', 'room.uncharted', 'room.twice', 'room.stray',
                        'room.faceRoom', 'room.facePage'), ('High room layout keeps the same coverage',
                        errors_of(main_run()[HIGH], 'attrs', 'faceValues', 'room.')))
    for kind in ('sky', 'room'):
        check(s[kind]['charts'] * 3 <= s[kind]['chartedFaces'] * 2,
              (f'{kind}: charts join coplanar connected faces, not one per triangle', s[kind]))
    plan_rooms = [(b['id'], r['level'], r['id']) for b in household()['buildings'] for r in b['rooms']
                  if len(r.get('polygon') or []) >= 3]
    check([(r['building'], r['level'], r['id']) for r in s['rooms']] == plan_rooms,
          'atlas.room.rooms is every plan room with a polygon, in plan order')
    check(all(r['region'] for r in s['rooms'] if r['level'] == 'L1' and r['building'] == HOUSE),
          'every main-house L1 room has a region')


def scenario_pages_grow_when_one_is_full():
    small, high = main_run()[SMALL_PAGES], main_run()[DEFAULT]
    check(high['sky']['pages'] == 1 and high['sky']['pagesUsed'] == [0], ('sky at 2 texels/ft fits one 2048 page', high['sky']))
    for kind, size in (('sky', 256), ('room', 1024)):
        L = small[kind]
        check(L['pages'] >= 2, (f'{kind} on {size} pages spills onto more', L['pages']))
        check(L['pages'] >= math.ceil(L['rectArea'] / size ** 2), (f'{kind}: pages hold no more than their area', L))
        check(L['pagesUsed'] == list(range(L['pages'])), (f'{kind}: every page in use, none skipped', L))
    for kind in ('sky', 'room'):
        check(high[kind]['pagesUsed'] == list(range(high[kind]['pages'])), (f'{kind} default: every page in use', high[kind]))
    bad = errors_of(small, 'sky.overlap', 'sky.rect', 'sky.page', 'sky.uncharted', 'sky.twice',
                    'room.overlap', 'room.rect', 'room.page', 'room.uncharted', 'room.twice', 'room.outsideRegion',
                    'region')
    check(not bad, ('spilled pages keep every rule', bad))
    check(not errors_of(high, 'regionOverlap') and not errors_of(small, 'regionOverlap'),
          ('room regions never overlap', errors_of(high, 'regionOverlap'), errors_of(small, 'regionOverlap')))


# --- Ruling B2 ----------------------------------------------------------------

def _room_face(p, room, s, what):
    check(p.get('hit'), (what, 'the ray hit something', p))
    check(p['lmRoom'] == room, (what, f'lmRoom is the room ({room})', p))
    check(p['roomChart'] == room, (what, 'the face is in one room chart of that room', p))
    region = s['rooms'][room]['region']
    check(region and p['lmLightPage'] == region['page'], (what, 'lmLightPage is the room region\'s page', p, region))


def _no_room(p, what):
    check(p['lmRoom'] == -1, (what, 'lmRoom is -1', p))
    check(p['roomChart'] == -1, (what, 'the face is in no room chart (no uv3)', p))


def scenario_room_faces_belong_to_their_room():
    for i in (DEFAULT, HIGH):
        _room_faces(main_run()[i])


def _room_faces(s):
    k = room_index(s, KITCHEN)
    for p in probes(s, 'floor@'):
        check(p.get('hit') and p['dist'] < 1.6, ('the kitchen floor is under the probe', p))
        _room_face(p, k, s, 'kitchen floor')
    for p in probes(s, 'ceiling@'):
        _room_face(p, k, s, 'kitchen ceiling')
    walls = [p for p in probes(s, 'kitchen-side@') if p.get('hit') and p['dist'] < 3.2]
    check(walls, ('the kitchen\'s inner wall faces the probes somewhere', probes(s, 'kitchen-side@')))
    for p in walls:
        _room_face(p, k, s, 'kitchen inner wall face')
    # Exterior wall faces: the hit's outside lies in no room or porch of the level.
    plan = household()
    polys = [r['polygon'] for r in building(plan, HOUSE)['rooms'] if r['level'] == 'L1' and len(r.get('polygon') or []) >= 3]
    outside = []
    for p in probes(s, 'outside@'):
        if not (p.get('hit') and p['dist'] < 21):
            continue
        x, y = p['point'][0] + p['normal'][0], p['point'][1] + p['normal'][1]
        if not any(inside(poly, x, y) for poly in polys):
            outside.append(p)
    check(outside, ('an exterior wall face of the kitchen faces the outside probes', probes(s, 'outside@')))
    for p in outside:
        _no_room(p, 'exterior wall face')
    roofs = [p for p in probes(s, 'roof@') if p.get('hit') and p['role'] == 'roof']
    check(roofs, ('the roof is above the kitchen', probes(s, 'roof@')))
    for p in roofs:
        check(p['normal'][2] > 0, ('a roof hit from above faces up', p))
        _no_room(p, 'roof top')


def scenario_a_wall_between_two_rooms_has_a_chart_on_each_side():
    for i in (DEFAULT, HIGH):
        _wall_between(main_run()[i])


def _wall_between(s):
    k, nb = room_index(s, KITCHEN), room_index(s, NEIGHBOUR)
    sides = {p['name'].split('@')[1]: p for p in probes(s, 'kitchen-side@')}
    other = {p['name'].split('@')[1]: p for p in probes(s, 'neighbour-side@')}
    pairs = [(sides[x], other[x]) for x in sides
             if sides[x].get('hit') and other[x].get('hit') and sides[x]['dist'] < 3.2 and other[x]['dist'] < 3.2]
    check(pairs, ('the shared wall is hit from both rooms somewhere along it', sides, other))
    for a, b in pairs:
        _room_face(a, k, s, 'the kitchen side')
        _room_face(b, nb, s, 'the neighbour side')
        check((a['mesh'], a['face']) != (b['mesh'], b['face']), ('two different faces', a, b))
        check(a['normal'][1] < -0.9 and b['normal'][1] > 0.9, ('each side faces its own room', a['normal'], b['normal']))


def scenario_a_room_with_three_lights_needs_a_second_bank():
    rooms = [{'building': 'b', 'id': 'kitchen', 'level': 'L1'}, {'building': 'b', 'id': 'hall', 'level': 'L1'},
             {'building': 'c', 'id': 'kitchen', 'level': 'L1'}]
    first = ([{'device': f'light.k{i}', 'building': 'b', 'room': 'kitchen'} for i in range(1, 4)]
             + [{'device': f'light.h{i}', 'building': 'b', 'room': 'hall'} for i in range(1, 3)]
             + [{'device': 'light.x1', 'building': 'c', 'room': 'kitchen'},
                {'device': 'light.ghost', 'building': 'b', 'room': 'nowhere'}])
    more = first + [{'device': f'light.k{i}', 'building': 'b', 'room': 'kitchen'} for i in (4, 5)]
    a, again, grown = run('assign', assign_cases=[{'rooms': rooms, 'lights': first}, {'rooms': rooms, 'lights': first},
                                                  {'rooms': rooms, 'lights': more}])['assign']
    check(a == again, 'the same lights, the same slots')
    check('light.ghost' not in a, ('a light in no known room is left out (it draws real-time)', a))
    kitchen = [a[f'light.k{i}'] for i in range(1, 4)]
    check(all(x['room'] == 0 for x in kitchen) and a['light.x1']['room'] == 2 and a['light.h1']['room'] == 1,
          ('room is the room\'s index; the same id in another building is another room', a))
    check([(x['bank'], x['channel']) for x in kitchen] == [(0, 0), (0, 1), (1, 0)],
          ('two lights fill bank 0 (R, G) in list order; the third opens bank 1', kitchen))
    check(all(x['channel'] in (0, 1) for x in a.values()), ('a bank has two channels only', a))
    hall = [a[f'light.h{i}'] for i in range(1, 3)]
    check([(x['bank'], x['channel']) for x in hall] == [(0, 0), (0, 1)],
          ('another room reuses bank 0 R and G in its own region', hall))
    check((a['light.x1']['bank'], a['light.x1']['channel']) == (0, 0), a['light.x1'])
    check(all(grown[d] == a[d] for d in a), ('appending a light moves no light already placed', a, grown))
    check([(grown[d]['bank'], grown[d]['channel']) for d in ('light.k4', 'light.k5')] == [(1, 1), (2, 0)],
          ('the fourth light fills bank 1 G; the fifth opens bank 2', grown['light.k4'], grown['light.k5']))


def scenario_memory_stays_bounded():
    _, lights = forty_lights()
    check(len(lights) == 40, len(lights))
    out = run('forty', lambda: forty_lights()[0], lights=lights)
    s, placed = out['atlases'][0], out['lights']
    check(set(placed) == {x['device'] for x in lights}, ('every light has a slot', sorted({x['device'] for x in lights} - set(placed))))
    banks = 1 + max(x['bank'] for x in placed.values())
    check(banks == 3, ('six kitchen lights take three two-channel banks; no room needs a fourth', banks))
    pages = s['room']['pages']
    check(pages * banks <= 4, ('at 4 texels/ft, room-light pages x banks stays within four 2048 RG pages', pages, banks))
    check(s['sky']['pages'] == 1, ('the sky at 2 texels/ft is one page', s['sky']['pages']))
    check(s['key'] == main_run()[DEFAULT]['key'] and layout(s) == layout(main_run()[DEFAULT]),
          'forty light fixtures change no atlas')


def scenario_horizontal_faces_are_clipped_and_buffers_rebuilt():
    s = run('clip', clip_case=True)['clip']
    check(s['replaced'] and not s['indexed'], 'split faces rebuild non-indexed merged buffers')
    pos = [s['positions'][i:i + 3] for i in range(0, len(s['positions']), 3)]
    check(len(pos) > 6, 'the original two triangles must split')
    polys = [[[0, 0], [5, 0], [5, 3], [3, 3], [3, 8], [0, 8]],
             [[5, 0], [8, 0], [8, 8], [5, 8]]]
    areas = {-1: 0, 0: 0, 1: 0}
    room_faces = []
    for f in range(len(pos) // 3):
        tri = pos[3 * f:3 * f + 3]
        rs = s['room'][3 * f:3 * f + 3]
        check(rs[0] == rs[1] == rs[2] and rs[0] in areas, ('one lower-level room per face', rs))
        r = rs[0]
        if r >= 0:
            room_faces.append(f)
        # Projected area, and winding: this slab is a downward-facing ceiling.
        a, b, c = tri
        cross = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
        check(cross < 0, ('winding retained, no degenerate pieces', tri))
        areas[r] += abs(cross) / 2
        for wa, wb in ((0.1, 0.1), (0.8, 0.1), (0.1, 0.8), (1 / 3, 1 / 3)):
            x = a[0] * wa + b[0] * wb + c[0] * (1 - wa - wb)
            y = -(a[2] * wa + b[2] * wb + c[2] * (1 - wa - wb))
            expected = next((i for i, p in enumerate(polys) if inside(p, x, y)), -1)
            check(r == expected, ('no triangle spans two room regions or exterior', f, r, expected, x, y))
    check(all(abs(areas[k] - v) < 1e-4 for k, v in {-1: 46, 0: 30, 1: 24}.items()),
          ('clipping conserves the whole slab, including exterior', areas))
    check(sorted(s['chartFaces']) == room_faces, 'each clipped room face gets one room chart')
    for i, (x, h, z) in enumerate(pos):
        check(abs(h - (10 + x * 0.1)) < 2e-6, 'sloped height interpolated')
        check(abs(s['uv'][2 * i] - x) < 2e-6 and abs(s['uv'][2 * i + 1] + z) < 2e-6, 'source uv interpolated')
        check(abs(s['weight'][i] - (x - 2 * z)) < 2e-6, 'custom attribute interpolated')
        check(s['normal'][3 * i + 1] < -0.99, 'source normal retained')
    d = main_run()[DEFAULT]
    check(0 < d['triangles'] - d['originalTriangles'] <= d['originalTriangles'] * 0.25,
          ('household splitting stays within +25% triangles', d['originalTriangles'], d['triangles']))


def scenario_high_sparse_banks_stay_within_six_pages():
    _, lights = forty_lights()
    out = run('forty-high-sparse', lambda: forty_lights()[0], atlases=({'room': {'density': 8}},),
              lights=lights, sparse_banks=True)
    banks, slots = out['banks'], out['lights']
    s = out['atlases'][0]
    check(out['emptyBanks'] == [], 'no lights allocate no bank pages')
    check(out['bankRemapsExact'], 'every sparse chart preserves its faces, dimensions and exact base uv3 offset')
    check([b['bank'] for b in banks] == [0, 1, 2], 'three two-channel banks')
    check(sum(b['pages'] for b in banks) <= 6, ('High sparse banks fit six 2048 RG pages total', banks))
    check(sum(b['pages'] for b in banks) + s['sky']['pages'] <= 6,
          ('High sparse banks plus the sky fit six pages total', [b['pages'] for b in banks], s['sky']['pages']))
    for bank in banks:
        expected = {v['room'] for v in slots.values() if v['bank'] >= bank['bank']}
        check({r['room'] for r in bank['rooms']} == expected, 'only rooms using this bank occupy regions')
        check({c['room'] for c in bank['charts']} == expected, 'only active room charts occupy pages')
        regions = {r['room']: r for r in bank['rooms']}
        for r in regions.values():
            a, source = r['region'], r['sourceRegion']
            check(source == s['rooms'][r['room']]['region'], 'base uv3 source region is explicit')
            check((a['w'], a['h']) == (source['w'], source['h']), 'bank remap keeps isometric scale')
            check(0 <= a['page'] < bank['pages'] and 0 <= a['x'] <= 2048 - a['w']
                  and 0 <= a['y'] <= 2048 - a['h'], 'bank region within page')
        for i, r in enumerate(bank['rooms']):
            a = r['region']
            for t in bank['rooms'][i + 1:]:
                b = t['region']
                if a['page'] == b['page']:
                    check(max(b['x'] - a['x'] - a['w'], a['x'] - b['x'] - b['w'],
                              b['y'] - a['y'] - a['h'], a['y'] - b['y'] - b['h']) >= 2, 'bank regions keep gutters')
        for c in bank['charts']:
            r, a = regions[c['room']]['region'], c['rect']
            check(c['page'] == r['page'] and r['x'] <= a['x'] <= r['x'] + r['w'] - a['w']
                  and r['y'] <= a['y'] <= r['y'] + r['h'] - a['h'], 'remapped charts stay in bank region')
    check(not run('no-bank', assign_cases=[{'rooms': [], 'lights': []}])['assign'][0], 'no light gets a phantom slot')


SCENARIOS = (
    scenario_same_model_same_atlas,
    scenario_a_light_added_or_moved_changes_no_atlas,
    scenario_charts_never_overlap_and_keep_gutters,
    scenario_texel_density_matches_world_size,
    scenario_every_interior_face_has_uv2,
    scenario_pages_grow_when_one_is_full,
    scenario_room_faces_belong_to_their_room,
    scenario_a_wall_between_two_rooms_has_a_chart_on_each_side,
    scenario_a_room_with_three_lights_needs_a_second_bank,
    scenario_memory_stays_bounded,
    scenario_horizontal_faces_are_clipped_and_buffers_rebuilt,
    scenario_high_sparse_banks_stay_within_six_pages,
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
