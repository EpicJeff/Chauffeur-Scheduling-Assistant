// Ridge routing for solar conduit, in lot feet with z up. Pure: no THREE, no DOM.
//
// The user's rule (2026-11-13): "go from solar zone up to ridge of its roof, then
// follow ridge towards main solar zone as far as that ridge goes, when you hit the
// end of that ridge go up whatever you ran into until you hit another ridge, then
// follow that ridge towards the main solar zone, repeat until you reach the main
// solar zone, conduit must always lay on the surface of the building."
//
// So a conduit may only travel (1) straight up a roof plane, (2) along a ridge, and
// (3) up whatever a ridge end runs into: the roof surface it meets, or the wall
// below that roof. Those moves form a small network; each satellite roof takes the
// shortest way through it to the main solar roof. Nothing ever runs down to eaves
// or along walls, so a route cannot wander. All zones on one roof count as one.
export const CONDUIT_OFFSET = 2.5 / 12;
const TOP = 0.05, JOIN = 1, REACH = 1.5, RISE = 0.3, SNAP = 0.02;

const sub = (a, b) => a.map((v, i) => v - b[i]);
const add = (a, b) => a.map((v, i) => v + b[i]);
const mul = (a, s) => a.map(v => v * s);
const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const unit = a => { const l = Math.hypot(...a) || 1; return a.map(v => v / l); };
const distance = (a, b) => Math.hypot(...sub(a, b));
const key = p => p.map(v => v.toFixed(4)).join(',');

function plane(input, index) {
  const tris = input.tris.filter(t => t.every(p => p.every(Number.isFinite)));
  let n = [0, 0, 1];
  for (const t of tris) { const c = cross(sub(t[1], t[0]), sub(t[2], t[0])); if (Math.hypot(...c) > 1e-9) { n = unit(c); break; } }
  if (n[2] < 0) n = mul(n, -1);
  const origin = tris[0]?.[0] || [0, 0, 0], counts = new Map();
  for (const t of tris) for (let i = 0; i < 3; i++) {
    const a = t[i], b = t[(i + 1) % 3], k = [key(a), key(b)].sort().join('|');
    const row = counts.get(k) || { a, b, n: 0 }; row.n++; counts.set(k, row);
  }
  const boundary = [...counts.values()].filter(e => e.n === 1).map(({ a, b }) => ({ a, b }));
  const maxZ = Math.max(...tris.flat().map(p => p[2]));
  const flat = Math.hypot(n[0], n[1]) < 0.02;
  for (const e of boundary) e.top = !flat && e.a[2] >= maxZ - TOP && e.b[2] >= maxZ - TOP;
  const zAt = (x, y) => origin[2] - (n[0] * (x - origin[0]) + n[1] * (y - origin[1])) / n[2];
  const centroid = tris.length ? mul(tris.flat().reduce(add, [0, 0, 0]), 1 / (tris.length * 3)) : origin;
  return { index, building: input.building, roof: input.roof, tris, n, boundary, maxZ, flat, zAt,
    centroid: [centroid[0], centroid[1], zAt(centroid[0], centroid[1])], uphill: unit([-n[0], -n[1], 0]).slice(0, 2) };
}

function insideTriangle([x, y], [a, b, c], tol = 1e-6) {
  const d = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1]); if (Math.abs(d) < 1e-12) return false;
  const l1 = ((b[1]-c[1])*(x-c[0]) + (c[0]-b[0])*(y-c[1])) / d, l2 = ((c[1]-a[1])*(x-c[0]) + (a[0]-c[0])*(y-c[1])) / d;
  return l1 >= -tol && l2 >= -tol && 1 - l1 - l2 >= -tol;
}
function segmentPoint2(p, a, b) {
  const d = [b[0]-a[0], b[1]-a[1]], l = d[0]*d[0] + d[1]*d[1];
  const t = l ? Math.max(0, Math.min(1, ((p[0]-a[0])*d[0] + (p[1]-a[1])*d[1]) / l)) : 0;
  return { t, at: [a[0] + d[0]*t, a[1] + d[1]*t] };
}
function segmentPoint3(p, a, b) {
  const d = sub(b, a), l = dot(d, d), t = l ? Math.max(0, Math.min(1, dot(sub(p, a), d) / l)) : 0;
  return { t, at: add(a, mul(d, t)) };
}
// Nearest point of a plane's footprint to (x, y), in plan view.
function nearestOn(pl, [x, y]) {
  if (pl.tris.some(t => insideTriangle([x, y], t))) return { at: [x, y], d: 0 };
  let best = { at: null, d: Infinity };
  for (const e of pl.boundary) { const q = segmentPoint2([x, y], e.a, e.b), d = Math.hypot(q.at[0]-x, q.at[1]-y); if (d < best.d) best = { at: q.at, d }; }
  return best;
}
// First boundary edge hit by a ray in plan view.
function rayExit(edges, p, dir) {
  let best = null;
  for (const e of edges) {
    const ex = e.b[0]-e.a[0], ey = e.b[1]-e.a[1], den = dir[0]*ey - dir[1]*ex; if (Math.abs(den) < 1e-12) continue;
    const wx = e.a[0]-p[0], wy = e.a[1]-p[1], t = (wx*ey - wy*ex) / den, s = (wx*dir[1] - wy*dir[0]) / den;
    if (t > 1e-6 && s >= -1e-9 && s <= 1 + 1e-9 && (!best || t < best.t)) best = { t, s: Math.max(0, Math.min(1, s)), e };
  }
  return best;
}

export function ridgeNetwork(input) {
  const planes = input.planes.map(plane), nodes = [], links = [], grid = new Map(), segments = [];
  function node(p) {
    const cell = p.map(v => Math.round(v / SNAP)).join(',');
    if (grid.has(cell)) return grid.get(cell);
    const id = nodes.length; nodes.push(p); links.push(new Map()); grid.set(cell, id); return id;
  }
  function link(a, b) { if (a === b) return; const c = distance(nodes[a], nodes[b]); if (c < (links[a].get(b) ?? Infinity)) { links[a].set(b, c); links[b].set(a, c); } }
  // A point on a ridge is on every coincident ridge too: the two sides of a gable each
  // carry their own top edge, and a route must cross over at the point, not the ends.
  function onSegment(seg, p) {
    const q = segmentPoint3(p, seg.a, seg.b), id = node(q.at); seg.pts.push({ t: q.t, id });
    for (const other of segments) if (other !== seg) {
      const r = segmentPoint3(q.at, other.a, other.b);
      if (distance(r.at, q.at) <= 0.05) { const o = node(r.at); other.pts.push({ t: r.t, id: o }); link(id, o); }
    }
    return id;
  }
  // Ridges: the horizontal top edges of every sloped plane.
  for (const pl of planes) for (const e of pl.boundary) if (e.top) {
    const seg = { a: e.a, b: e.b, plane: pl, pts: [] }; seg.pts.push({ t: 0, id: node(e.a) }, { t: 1, id: node(e.b) }); segments.push(seg); e.segment = seg;
  }
  const hubs = new Map(); // flat planes: everything on them meets at their centroid
  const hub = pl => { if (!hubs.has(pl)) hubs.set(pl, node(pl.centroid)); return hubs.get(pl); };
  // Straight up a plane from p (on its surface) to its ridge. Returns the top node.
  function climb(pl, p, from) {
    if (pl.flat) { const h = hub(pl); link(from, h); return h; }
    const hit = rayExit(pl.boundary, p, pl.uphill); if (!hit) return null;
    const at2 = [p[0] + pl.uphill[0] * hit.t, p[1] + pl.uphill[1] * hit.t], e = hit.e;
    const at = [...at2, e.a[2] + (e.b[2] - e.a[2]) * hit.s];
    if (e.top) { const id = onSegment(e.segment, at); link(from, id); return id; }
    // A hip or rake edge: follow it up to its high end, which meets the ridge.
    const x = node(at), high = e.a[2] >= e.b[2] ? e.a : e.b, h = node(high);
    link(from, x); link(x, h); return h;
  }
  // Key points: ridge ends, plus the apex of planes with no ridge (hip ends).
  const keys = [];
  for (const seg of segments) keys.push({ p: seg.a, id: seg.pts[0].id, plane: seg.plane }, { p: seg.b, id: seg.pts[1].id, plane: seg.plane });
  for (const pl of planes) if (!pl.flat && !pl.boundary.some(e => e.top)) {
    const apex = pl.tris.flat().reduce((a, b) => b[2] > a[2] ? b : a); keys.push({ p: apex, id: node(apex), plane: pl });
  }
  // Ridges that meet (both sides of one gable, T and hip junctions) join.
  for (const k of keys) for (const seg of segments) {
    if (seg.pts.slice(0, 2).some(s => s.id === k.id)) continue;
    const q = segmentPoint3(k.p, seg.a, seg.b); if (distance(q.at, k.p) <= JOIN) link(k.id, onSegment(seg, k.p));
  }
  // A ridge end runs into another roof: climb that roof, or the wall below it first.
  for (const k of keys) for (const pl of planes) {
    if (pl === k.plane || pl.maxZ < k.p[2] + RISE) continue;
    const near = nearestOn(pl, k.p); if (near.d > REACH) continue;
    const z = pl.zAt(...near.at); if (z < k.p[2] - RISE) continue;
    let from = k.id;
    if (z > k.p[2] + RISE) { const r = node([...near.at, k.p[2]]); link(from, r); from = r; }
    const s = node([...near.at, z]); link(from, s); climb(pl, [...near.at, z], s);
  }
  // Flat roofs: a ridge end at their level steps onto them.
  for (const pl of planes) if (pl.flat) for (const k of keys) {
    const near = nearestOn(pl, k.p); if (near.d <= REACH && Math.abs(pl.zAt(...near.at) - k.p[2]) <= RISE) link(k.id, hub(pl));
  }
  // A flat roof's edge meets a neighbour: another flat roof at its level, or a
  // taller roof whose wall or surface it runs into.
  for (const f of planes) if (f.flat) for (const pl of planes) {
    if (pl === f) continue;
    let best = null;
    for (const e of f.boundary) for (const t of [0, .25, .5, .75, 1]) {
      const p = add(e.a, mul(sub(e.b, e.a), t)), near = nearestOn(pl, p);
      if (near.d <= REACH && (!best || near.d < best.near.d)) best = { p, near };
    }
    if (!best) continue;
    const z = pl.zAt(...best.near.at);
    if (pl.flat) { if (Math.abs(z - best.p[2]) <= RISE && f.index < pl.index) link(hub(f), hub(pl)); continue; }
    if (z < best.p[2] - RISE) continue;
    const edge = node(best.p); link(hub(f), edge);
    let from = edge;
    if (z > best.p[2] + RISE) { const r = node([...best.near.at, best.p[2]]); link(from, r); from = r; }
    const s = node([...best.near.at, z]); link(from, s); climb(pl, [...best.near.at, z], s);
  }
  function finish() {
    for (const seg of segments) { seg.pts.sort((a, b) => a.t - b.t); for (let i = 1; i < seg.pts.length; i++) link(seg.pts[i-1].id, seg.pts[i].id); }
  }
  // A zone enters the network at the top edge of its panels, straight up-slope.
  function enter(zone) {
    const pl = planes[zone.plane]; if (!pl) return null;
    const rect = zone.rect.map((p, i) => ({ a: p, b: zone.rect[(i + 1) % zone.rect.length] }));
    let start = zone.centre;
    if (!pl.flat) { const hit = rayExit(rect, zone.centre, pl.uphill); if (hit) { const x = zone.centre[0] + pl.uphill[0] * hit.t, y = zone.centre[1] + pl.uphill[1] * hit.t; start = [x, y, pl.zAt(x, y)]; } }
    const id = node(start); return climb(pl, start, id) === null ? null : id;
  }
  return { planes, nodes, links, segments, enter, finish };
}

function shortest(links, from, targets) {
  const dist = new Map([[from, 0]]), prev = new Map(), heap = [[0, from]], done = new Set();
  while (heap.length) {
    let bi = 0; for (let i = 1; i < heap.length; i++) if (heap[i][0] < heap[bi][0]) bi = i;
    const [d, n] = heap.splice(bi, 1)[0]; if (done.has(n)) continue; done.add(n);
    if (targets.has(n)) { const path = [n]; while (prev.has(path[0])) path.unshift(prev.get(path[0])); return { cost: d, path }; }
    for (const [m, c] of links[n]) { const nd = d + c; if (nd < (dist.get(m) ?? Infinity)) { dist.set(m, nd); prev.set(m, n); heap.push([nd, m]); } }
  }
  return null;
}

function compact(points) {
  const out = [];
  for (const p of points) {
    if (out.length && distance(out.at(-1), p) < 1e-6) continue;
    if (out.length >= 2) {
      const a = out.at(-2), b = out.at(-1), u = unit(sub(b, a)), v = unit(sub(p, b));
      if (dot(u, v) > 1 - 1e-9) { out[out.length - 1] = p; continue; }
    }
    out.push(p);
  }
  return out;
}

// input: {planes:[{building, roof, tris}], groups:[{id, entity, zones:[{plane, centre, rect}]}],
//         sources:[{plane, centre, rect}], source:[x, y, z]}
export function routeConduits(input, { debug = message => console.debug(message) } = {}) {
  if (!input?.groups?.length || !input.sources?.length) return [];
  const net = ridgeNetwork(input), targets = new Set();
  for (const s of input.sources) { const id = net.enter(s); if (id !== null) targets.add(id); }
  const entries = input.groups.map(g => ({ g, ids: g.zones.map(z => net.enter(z)).filter(id => id !== null) }));
  net.finish();
  const routes = []; let logged = false;
  for (const { g, ids } of entries) {
    let best = null;
    for (const id of ids) { const r = targets.size && shortest(net.links, id, targets); if (r && (!best || r.cost < best.cost)) best = r; }
    if (!best) { if (!logged) { debug('Solar conduit skipped: a solar roof has no ridge path to the main solar roof'); logged = true; } continue; }
    const points = compact(best.path.map(id => net.nodes[id])).map(p => [p[0], p[1], p[2] + CONDUIT_OFFSET]);
    routes.push({ id: g.id, entity: g.entity ?? null, points, source: input.source });
  }
  return routes;
}
