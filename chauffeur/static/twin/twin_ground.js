// Lot coordinates and returned heights are feet relative to datum zero.
export function edgeDistance(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], d = dx * dx + dy * dy;
  const t = d ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / d)) : 0;
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}
export function inPolygon(poly, x, y) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[j], b = poly[i];
    if (edgeDistance([x, y], a, b) < 1e-9) return true;
    if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}
export function segmentIntersection(a, b, c, d) {
  const v = b.map((x, i) => x - a[i]), w = d.map((x, i) => x - c[i]), q = c.map((x, i) => x - a[i]);
  const cross = (u, v) => u[0] * v[1] - u[1] * v[0], den = cross(v, w);
  if (Math.abs(den) < 1e-10) return null;
  const t = cross(q, w) / den, u = cross(q, v) / den;
  return t >= 0 && t <= 1 && u >= 0 && u <= 1 ? a.map((x, i) => x + t * v[i]) : null;
}
export function groundAt(plan, x, y) {
  const pads = plan?.site?.terraces || [];
  for (let i = pads.length - 1; i >= 0; i--) if (inPolygon(pads[i].polygon, x, y)) return pads[i].height;
  let total = 0, weight = 0;
  for (const pad of pads) {
    const blend = pad.blend ?? 6;
    if (!blend) continue;
    const ds = pad.polygon.map((a, i) => edgeDistance([x, y], a, pad.polygon[(i + 1) % pad.polygon.length]));
    const d = Math.min(...ds), i = ds.indexOf(d);
    if (d >= blend || (pad.edges?.[i]?.edge ?? 'slope') === 'sharp') continue;
    const t = 1 - d / blend, influence = t * t * (3 - 2 * t);
    // Smoothstep for a lone band; distance odds combine overlapping bands
    // without exceeding any contributing height or spiking at boundaries.
    const w = influence / Math.max(1e-12, 1 - influence);
    total += w * pad.height; weight += w;
  }
  return total / (1 + weight);
}
export function buildingFootprint(b) {
  const first = [...(b.levels || [])].sort((a, c) => a.elevation - c.elevation)[0];
  if (first?.outline?.length >= 3) return first.outline;
  const points = (b.rooms || []).filter(r => r.level === first?.id).flatMap(r => r.polygon || [])
    .concat((b.walls || []).flatMap(w => w.from ? [w.from, w.to] : []));
  if (!points.length) return [];
  const lo = [0, 1].map(i => Math.min(...points.map(p => p[i]))), hi = [0, 1].map(i => Math.max(...points.map(p => p[i])));
  return [[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]];
}
const footprintCache = new WeakMap();
export function footprintGround(plan, b) {
  const poly = buildingFootprint(b), a = (b.rotation || 0) * Math.PI / 180, pos = b.position || [0, 0];
  const key = JSON.stringify([poly, pos, a, plan?.site?.terraces]);
  const cached = footprintCache.get(b); if (cached?.key === key) return cached.value;
  const world = p => [pos[0] + p[0] * Math.cos(a) - p[1] * Math.sin(a), pos[1] + p[0] * Math.sin(a) + p[1] * Math.cos(a)];
  const heights = [], sample = p => heights.push(groundAt(plan, ...world(p)));
  if (!poly.length) return { low: groundAt(plan, ...pos), high: groundAt(plan, ...pos) };
  poly.forEach((p, i) => { const q = poly[(i + 1) % poly.length], n = Math.ceil(Math.hypot(q[0] - p[0], q[1] - p[1]));
    for (let j = 0; j <= n; j++) sample(p.map((v, k) => v + (q[k] - v) * j / Math.max(1, n))); });
  const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
  for (let x = Math.min(...xs); x <= Math.max(...xs); x += 1) for (let y = Math.min(...ys); y <= Math.max(...ys); y += 1)
    if (inPolygon(poly, x, y)) sample([x, y]);
  const local = p => { const x = p[0] - pos[0], y = p[1] - pos[1]; return [x * Math.cos(a) + y * Math.sin(a), -x * Math.sin(a) + y * Math.cos(a)]; };
  for (const pad of plan?.site?.terraces || []) for (const p of pad.polygon) if (inPolygon(poly, ...local(p))) heights.push(groundAt(plan, ...p));
  const outline = poly.map(world);
  for (const pad of plan?.site?.terraces || []) for (let i = 0; i < pad.polygon.length; i++) for (let j = 0; j < outline.length; j++) {
    const p = segmentIntersection(pad.polygon[i], pad.polygon[(i + 1) % pad.polygon.length], outline[j], outline[(j + 1) % outline.length]);
    if (p) heights.push(groundAt(plan, ...p));
  }
  const value = { low: heights.reduce((v, h) => Math.min(v, h), Infinity), high: heights.reduce((v, h) => Math.max(v, h), -Infinity) };
  footprintCache.set(b, { key, value }); return value;
}
export function buildingBase(plan, b) {
  return b?.foundation?.mode === 'auto' ? footprintGround(plan, b).high + (b.foundation.offset_ft || 0) : b?.base || 0;
}
// Existing marker/host consumers add the saved base themselves.
export const buildingGround = (plan, b) => buildingBase(plan, b) - (b?.base || 0);
export function foundationShape(plan, b) {
  const base = buildingBase(plan, b), ground = footprintGround(plan, b);
  return { polygon: buildingFootprint(b), top: base, bottom: Math.min(ground.low, base - (b.foundation?.thickness_ft ?? 1)), base };
}
