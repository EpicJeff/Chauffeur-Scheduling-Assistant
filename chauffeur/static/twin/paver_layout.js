import { pathCentreline } from './path_shapes.js';
import { PAVER_DEFAULTS } from './paver_defaults.js';
export { PAVER_DEFAULTS } from './paver_defaults.js';

// Pure lot-foot geometry; nothing derived here is written over the authored path.
export const MAX_PAVERS = 5000;
const EPS = 1e-8;
const add = (a, b) => a.map((v, i) => v + b[i]);
const sub = (a, b) => a.map((v, i) => v - b[i]);
const mul = (a, n) => a.map(v => v * n);
const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const cross = (a, b) => a[0] * b[1] - a[1] * b[0];
const turn = (p, a) => [p[0] * Math.cos(a) - p[1] * Math.sin(a), p[0] * Math.sin(a) + p[1] * Math.cos(a)];
const area = p => Math.abs(p.reduce((sum, a, i) => sum + cross(a, p[(i + 1) % p.length]), 0)) / 2;
const rectangle = (x, y) => [[-x / 2, -y / 2], [x / 2, -y / 2], [x / 2, y / 2], [-x / 2, y / 2]];

export function paverSettings(path) { return path.pavers == null ? null : { ...PAVER_DEFAULTS, ...path.pavers }; }
export function paverEstimate(path) {
  const p = paverSettings(path);
  if (!p) return 0;
  const ps = pathCentreline(path), length = ps.slice(1).reduce((sum, v, i) => sum + Math.hypot(...sub(v, ps[i])), 0);
  return Math.ceil(length * (p.layout === 'stepping' ? p.width_in / 12 : path.width ?? 3)
    / (((p.length_in + p.gap_in) / 12) * ((p.width_in + p.gap_in) / 12)));
}

function clip(poly, boundary) {
  for (let i = 0; i < boundary.length && poly.length; i++) {
    const a = boundary[i], edge = sub(boundary[(i + 1) % boundary.length], a), input = poly;
    poly = [];
    input.forEach((q, j) => {
      const p = input[(j + input.length - 1) % input.length], u = cross(edge, sub(p, a)), v = cross(edge, sub(q, a));
      if ((u >= -EPS) !== (v >= -EPS)) poly.push(add(p, mul(sub(q, p), u / (u - v))));
      if (v >= -EPS) poly.push(q);
    });
  }
  return poly.filter((p, i) => Math.hypot(...sub(p, poly[(i + poly.length - 1) % poly.length])) > EPS);
}

function centreline(path) {
  const ps = pathCentreline(path), distances = [0];
  ps.slice(1).forEach((p, i) => distances.push(distances[i] + Math.hypot(...sub(p, ps[i]))));
  const length = distances.at(-1);
  return { length, frame(s) {
    let low = 0, high = ps.length - 2;
    while (low < high) { const mid = (low + high) >> 1; if (distances[mid + 1] < s) low = mid + 1; else high = mid; }
    const d = sub(ps[low + 1], ps[low]), tangent = mul(d, 1 / Math.hypot(...d));
    return { at: add(ps[low], mul(tangent, s - distances[low])), angle: Math.atan2(tangent[1], tangent[0]) };
  } };
}

function spatial(size) {
  const cells = new Map();
  const keys = poly => {
    const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]), result = [];
    for (let x = Math.floor(Math.min(...xs) / size); x <= Math.floor(Math.max(...xs) / size); x++)
      for (let y = Math.floor(Math.min(...ys) / size); y <= Math.floor(Math.max(...ys) / size); y++) result.push(`${x},${y}`);
    return result;
  };
  return { near: poly => [...new Set(keys(poly).flatMap(k => cells.get(k) || []))],
    put(p) { for (const k of keys(p.polygon)) { if (!cells.has(k)) cells.set(k, []); cells.get(k).push(p); } } };
}

// Enumerate a lattice inside the strip, solving the second coordinate per row.
// A rotated, long narrow path must not scan its whole bounding square.
function lattice(origin, u, v, length, half, reach, visit) {
  const bounds = [[-reach, length + reach], [-half - reach, half + reach]], det = cross(u, v);
  const corners = [[bounds[0][0], bounds[1][0]], [bounds[0][1], bounds[1][0]], [bounds[0][1], bounds[1][1]], [bounds[0][0], bounds[1][1]]];
  const is = corners.map(p => cross(sub(p, origin), v) / det);
  for (let i = Math.ceil(Math.min(...is)); i <= Math.floor(Math.max(...is)); i++) {
    const base = add(origin, mul(u, i)); let low = -Infinity, high = Infinity;
    for (let k = 0; k < 2; k++) {
      if (Math.abs(v[k]) < EPS) { if (base[k] < bounds[k][0] || base[k] > bounds[k][1]) high = -Infinity; }
      else { const a = (bounds[k][0] - base[k]) / v[k], b = (bounds[k][1] - base[k]) / v[k]; low = Math.max(low, Math.min(a, b)); high = Math.min(high, Math.max(a, b)); }
    }
    for (let j = Math.ceil(low); j <= Math.floor(high); j++) visit(add(base, mul(v, j)));
  }
}

// Remove every interval inside a stone, including stones on a different bend.
function clearSegments(a, b, nearby) {
  const d = sub(b, a); let spans = [[0, 1]];
  for (const p of nearby) {
    let low = 0, high = 1;
    for (let i = 0; i < p.polygon.length; i++) {
      const start = p.polygon[i], edge = sub(p.polygon[(i + 1) % p.polygon.length], start);
      const c = cross(edge, sub(a, start)) + 1e-6 * Math.hypot(...edge), slope = cross(edge, d);
      if (Math.abs(slope) < EPS) { if (c < 0) high = -1; }
      else if (slope > 0) low = Math.max(low, -c / slope); else high = Math.min(high, -c / slope);
    }
    if (low <= high) spans = spans.flatMap(([x, y]) => high < x || low > y ? [[x, y]] : [[x, Math.min(y, low)], [Math.max(x, high), y]].filter(([s, t]) => t - s > 1e-6));
  }
  return spans.map(([s, t]) => [add(a, mul(d, s)), add(a, mul(d, t))]);
}

function jointLines(pavers, grid, gap) {
  if (!gap) return [];
  const joints = [];
  for (const p of pavers) {
    const expanded = p.polygon.flatMap(v => [add(v, [-gap * 2, -gap * 2]), add(v, [gap * 2, gap * 2])]);
    for (const q of grid.near(expanded)) {
      if (q.index <= p.index) continue;
      p.polygon.forEach((a, i) => {
        const b = p.polygon[(i + 1) % p.polygon.length], edge = sub(b, a), unit = mul(edge, 1 / Math.hypot(...edge)), outward = [unit[1], -unit[0]];
        q.polygon.forEach((c, j) => {
          const d = q.polygon[(j + 1) % q.polygon.length], other = sub(d, c), otherUnit = mul(other, 1 / Math.hypot(...other));
          if (dot(unit, otherUnit) > -.8) return;
          // The averaged edge direction also bisects a fanned joint on a bend.
          const delta = sub(unit, otherUnit), along = mul(delta, 1 / Math.hypot(...delta));
          const low = Math.max(0, Math.min(dot(sub(c, a), along), dot(sub(d, a), along)));
          const high = Math.min(dot(edge, along), Math.max(dot(sub(c, a), along), dot(sub(d, a), along)));
          if (high - low < EPS) return;
          const on = (p, q, t) => add(p, mul(sub(q, p), (t - dot(sub(p, a), along)) / dot(sub(q, p), along)));
          const middle = t => mul(add(on(a, b, t), on(c, d, t)), .5);
          const distance = dot(sub(on(c, d, (low + high) / 2), on(a, b, (low + high) / 2)), outward);
          if (distance < EPS || distance > gap * 2 + EPS) return;
          const start = middle(low), end = middle(high);
          joints.push(...clearSegments(start, end, grid.near([start, end])));
        });
      });
    }
  }
  return joints;
}

export function paverLayout(path) {
  const settings = paverSettings(path), empty = { pavers: [], joints: [], jointWidth: 0 };
  if (!settings) return empty;
  if (paverEstimate(path) > MAX_PAVERS) throw new Error('Use larger pavers or a shorter path.');
  const line = centreline(path);
  if (!line.length) return empty;
  const l = settings.length_in / 12, w = settings.width_in / 12, gap = settings.gap_in / 12, pavers = [];
  const herring = settings.layout === 'herringbone' && Math.abs(l - w) > EPS;
  const angle = settings.rotation * Math.PI / 180 + (settings.layout === 'diagonal' || herring ? Math.PI / 4 : 0);
  const stepping = settings.layout === 'stepping', single = stepping || ['grid', 'running_bond'].includes(settings.layout) && (path.width ?? 3) < w;
  // The explicit one-across exception keeps an oversized whole stone visible.
  const across = Math.abs(l * Math.sin(angle)) + Math.abs(w * Math.cos(angle));
  const half = stepping ? across / 2 : single && settings.edge === 'whole' ? Math.max(path.width ?? 3, across) / 2 : (path.width ?? 3) / 2;
  const boundary = [[0, -half], [line.length, -half], [line.length, half], [0, half]], grid = spatial(Math.hypot(l, w) + gap);
  let index = 0;
  const place = (centre, a = angle, length = l, width = w) => {
    const id = index++;
    let local = rectangle(length, width).map(p => add(centre, turn(p, a)));
    if (settings.edge === 'cut') { local = clip(local, boundary); if (area(local) < length * width / 10 - EPS) return; }
    else if (local.some(([s, t]) => s < -EPS || s > line.length + EPS || Math.abs(t) > half + EPS)) return;
    const frame = line.frame(centre[0]), polygon = local.map(p => add(frame.at, turn(sub(p, [centre[0], 0]), frame.angle)));
    const size = area(polygon);
    if (grid.near(polygon).some(p => area(clip(polygon, p.polygon)) > .1 * Math.min(size, area(p.polygon)) + EPS)) return;
    const p = { polygon, centre: add(frame.at, turn([0, centre[1]], frame.angle)), angle: frame.angle + a, index: id };
    pavers.push(p); grid.put(p);
    if (pavers.length > MAX_PAVERS) throw new Error('Use larger pavers or a shorter path.');
  };
  if (single) {
    for (let s = l / 2; s <= line.length + l / 2; s += l + gap) place([s, 0]);
  } else if (herring) {
    // Two inset rectangles tile an L on the (A,A), (B,-B) lattice.
    // Inflating both dimensions by the joint gives the same grout at every edge.
    const long = Math.max(l, w), short = Math.min(l, w), A = long + gap, B = short + gap;
    const u = turn([A, A], angle), v = turn([B, -B], angle);
    for (const [centre, a] of [[[A / 2, B / 2], angle], [[A + B / 2, A / 2], angle + Math.PI / 2]])
      lattice(turn(centre, angle), u, v, line.length, half, Math.hypot(l, w), p => place(p, a, long, short));
  } else {
    const count = Math.max(1, Math.floor(((path.width ?? 3) + gap + EPS) / (w + gap)));
    const origin = [l / 2, -(count - 1) * (w + gap) / 2];
    const u = turn([l + gap, settings.layout === 'running_bond' ? (w + gap) / 2 : 0], angle), v = turn([0, w + gap], angle);
    lattice(origin, u, v, line.length, half, Math.hypot(l, w), p => place(p));
  }
  return { pavers, joints: jointLines(pavers, grid, gap), jointWidth: gap };
}
