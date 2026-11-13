// Lot feet throughout. Derived geometry is never written back over the centre line.
const add = (a, b) => a.map((v, i) => v + b[i]);
const sub = (a, b) => a.map((v, i) => v - b[i]);
const mul = (a, s) => a.map(v => v * s);
const length = a => Math.hypot(...a);
const unit = a => mul(a, 1 / (length(a) || 1));
const cross = (a, b) => a[0] * b[1] - a[1] * b[0];
const normal = a => [-a[1], a[0]];
export const pathPresets = {
  sidewalk: { width: 4, material: 'patio_concrete', corner: 'mitred', smooth: false, edging: 'none' },
  paver: { width: 3, material: 'paving', corner: 'rounded', smooth: false, edging: 'none' },
  driveway: { width: 10, material: 'patio_concrete', corner: 'mitred', smooth: false, edging: 'none' },
};

export function pathCentreline(path) {
  const ps = (path.points || []).filter((p, i, all) => !i || length(sub(p, all[i - 1])) > 1e-8);
  if (ps.length < 2) return ps;
  if (path.smooth) {
    const dense = [ps[0]], knots = new Set();
    for (let i = 0; i < ps.length - 1; i++) {
      const a = ps[Math.max(0, i - 1)], b = ps[i], c = ps[i + 1], d = ps[Math.min(ps.length - 1, i + 2)];
      const n = Math.max(8, Math.ceil((length(sub(b, a)) + length(sub(c, b)) + length(sub(d, c))) * 4));
      for (let j = 1; j <= n; j++) {
        const t = j / n;
        dense.push(j === n ? c : b.map((v, k) => .5 * (2 * v + (-a[k] + c[k]) * t + (2 * a[k] - 5 * v + 4 * c[k] - d[k]) * t * t + (-a[k] + 3 * v - 3 * c[k] + d[k]) * t * t * t)));
      }
      knots.add(dense.length - 1);
    }
    // Walk the dense curve at one-foot distances, preserving the final point.
    const out = [dense[0]]; let remaining = 1, previous = dense[0];
    for (let i = 1; i < dense.length; i++) {
      const target = dense[i];
      let gap = length(sub(target, previous));
      while (gap >= remaining) { previous = add(previous, mul(unit(sub(target, previous)), remaining)); out.push(previous); gap = length(sub(target, previous)); remaining = 1; }
      remaining -= gap; previous = target;
      if (knots.has(i)) { if (length(sub(out.at(-1), target)) > 1e-8) out.push(target); remaining = 1; }
    }
    if (length(sub(out.at(-1), ps.at(-1))) > 1e-8) out.push(ps.at(-1));
    return out;
  }
  if (path.corner !== 'rounded' || ps.length < 3) return ps;
  const out = [ps[0]];
  for (let i = 1; i < ps.length - 1; i++) {
    const p = ps[i], incoming = unit(sub(p, ps[i - 1])), outgoing = unit(sub(ps[i + 1], p));
    const turn = Math.atan2(cross(incoming, outgoing), incoming[0] * outgoing[0] + incoming[1] * outgoing[1]);
    if (Math.abs(turn) < 1e-5 || Math.abs(turn) > Math.PI - .01) { out.push(p); continue; }
    const tangent = Math.tan(Math.abs(turn) / 2), radius = path.radius ?? path.width ?? 3;
    const cut = Math.min(radius * tangent, length(sub(p, ps[i - 1])) * .49, length(sub(ps[i + 1], p)) * .49);
    const r = cut / tangent, start = sub(p, mul(incoming, cut)), centre = add(start, mul(normal(incoming), Math.sign(turn) * r));
    const angle = Math.atan2(start[1] - centre[1], start[0] - centre[0]), n = Math.max(2, Math.ceil(Math.abs(turn) * r / .5));
    for (let j = 0; j <= n; j++) out.push(add(centre, [Math.cos(angle + turn * j / n) * r, Math.sin(angle + turn * j / n) * r]));
  }
  out.push(ps.at(-1)); return out;
}

export function pathBoundaries(path, half = (path.width ?? 3) / 2) {
  const ps = pathCentreline(path);
  if (ps.length < 2) return { left: [], right: [] };
  const side = sign => ps.flatMap((p, i) => {
    const a = unit(sub(p, ps[Math.max(0, i - 1)])), b = unit(sub(ps[Math.min(ps.length - 1, i + 1)], p));
    if (!i || i === ps.length - 1) return [add(p, mul(normal(!i ? b : a), half * sign))];
    const na = mul(normal(a), half * sign), nb = mul(normal(b), half * sign), den = cross(a, b);
    if (Math.abs(den) < 1e-8) return a[0] * b[0] + a[1] * b[1] > 0 ? [add(p, nb)] : [add(p, na), add(p, nb)];
    const m = add(na, mul(a, cross(sub(nb, na), b) / den));
    // Bevel a sharp reversal instead of allowing an unbounded mitre spike.
    return length(m) <= half * 2 ? [add(p, m)] : [add(p, na), add(p, nb)];
  });
  return { left: side(1), right: side(-1) };
}
export function pathOutline(path) { const { left, right } = pathBoundaries(path); return [...left, ...right.reverse()]; }

export function simpleOutline(poly) {
  const on = (p, a, b) => Math.abs(cross(sub(b, a), sub(p, a))) < 1e-8
    && p.every((v, i) => v >= Math.min(a[i], b[i]) - 1e-8 && v <= Math.max(a[i], b[i]) + 1e-8);
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    if (length(sub(b, a)) < 1e-8) return false;
    for (let j = i + 2; j < poly.length; j++) {
      if (i === 0 && j === poly.length - 1) continue;
      const c = poly[j], d = poly[(j + 1) % poly.length];
      const side = (p, q, r) => cross(sub(q, p), sub(r, p));
      if (side(a, b, c) * side(a, b, d) < 0 && side(c, d, a) * side(c, d, b) < 0
        || on(c, a, b) || on(d, a, b) || on(a, c, d) || on(b, c, d)) return false;
    }
  }
  return true;
}

// Ordinary paths are one continuous receiver without interior walls or
// coplanar faces at bends. At crossings/hairpins use swept pieces so the
// user's overlap stays filled rather than cancelling under even/odd fill.
export function pathSurfacePolygons(path) {
  const outline = pathOutline(path);
  if (outline.length >= 4 && simpleOutline(outline)) return [outline];
  const ps = pathCentreline(path), half = (path.width ?? 3) / 2, parts = [];
  const normals = ps.slice(1).map((p, i) => mul(normal(unit(sub(p, ps[i]))), half));
  normals.forEach((n, i) => {
    parts.push([add(ps[i], n), sub(ps[i], n), sub(ps[i + 1], n), add(ps[i + 1], n)]);
    if (i) {
      const a = normals[i - 1], b = n, p = ps[i];
      const turn = cross(sub(ps[i], ps[i - 1]), sub(ps[i + 1], ps[i]));
      const sign = turn >= 0 ? -1 : 1, na = mul(a, sign), nb = mul(b, sign);
      const dot = (a[0] * b[0] + a[1] * b[1]) / (half * half), factor = 1 / Math.max(1e-8, 1 + dot), m = mul(add(na, nb), factor);
      if (Math.abs(turn) > 1e-9) parts.push(length(m) <= half * 2 ? [p, add(p, na), add(p, m), add(p, nb)] : [p, add(p, na), add(p, nb)]);
    }
  });
  return parts;
}
