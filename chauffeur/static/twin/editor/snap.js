// Building-local feet. Endpoint priority is intentional, even when a line is nearer.
export function snapPoint(p, walls = [], { grid = 0.5, reach = 1.0 } = {}) {
  const distance = q => Math.hypot(q[0] - p[0], q[1] - p[1]);
  const nearest = points => points.filter(q => distance(q) <= reach).sort((a, b) => distance(a) - distance(b))[0];
  const endpoint = nearest(walls.flatMap(w => [w.from, w.to]));
  if (endpoint) return [...endpoint];
  const line = nearest(walls.map(w => {
    const d = [w.to[0] - w.from[0], w.to[1] - w.from[1]], n = d[0] ** 2 + d[1] ** 2;
    const t = n ? Math.max(0, Math.min(1, ((p[0] - w.from[0]) * d[0] + (p[1] - w.from[1]) * d[1]) / n)) : 0;
    return [w.from[0] + t * d[0], w.from[1] + t * d[1]];
  }));
  return line || p.map(v => grid > 0 ? Math.round(v / grid) * grid : v);
}

export function snapRotation(deg) {
  const quarter = Math.round(deg / 90) * 90;
  return Math.abs(quarter - deg) <= 7 + 1e-10 ? (quarter || 0) : deg;
}

export function snapAngle(from, to) {
  const dx = to[0] - from[0], dy = to[1] - from[1];
  const angle = Math.atan2(dy, dx) * 180 / Math.PI;
  const snapped = snapRotation(angle);
  if (snapped !== angle || Math.abs(angle % 90) < 1e-10) {
    return Math.abs(Math.round(snapped / 90) % 2) ? [from[0], to[1]] : [to[0], from[1]];
  }
  return [...to];
}
