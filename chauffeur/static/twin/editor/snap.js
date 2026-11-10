// Building-local feet. A higher-ranked target wins even if another is nearer.
export function snapTo(p, { joints = [], walls = [], below = [], anchors = [], from,
  grid = 1 / 12, reach = 1, exclude = [] } = {}) {
  const distance = q => Math.hypot(q[0] - p[0], q[1] - p[1]);
  const nearest = points => points.filter(q => q && distance(q) <= reach + 1e-10
    && !exclude.some(e => Math.hypot(e[0] - q[0], e[1] - q[1]) < 1e-6))
    .sort((a, b) => distance(a) - distance(b))[0];
  const project = wall => {
    const d = wall.to.map((v, i) => v - wall.from[i]), n = d[0] ** 2 + d[1] ** 2;
    if (!n) return null;
    const t = d.reduce((s, v, i) => s + (p[i] - wall.from[i]) * v, 0) / n;
    return { point: wall.from.map((v, i) => v + t * d[i]), target: t >= 0 && t <= 1 ? 'line' : 'extension' };
  };
  const joint = nearest(joints.map(j => j.at ?? j));
  if (joint) return { point: [...joint], target: 'joint' };
  const lines = walls.map(project).filter(Boolean);
  for (const target of ['line', 'extension']) {
    const point = nearest(lines.filter(row => row.target === target).map(row => row.point));
    if (point) return { point, target };
  }
  if (from) {
    const point = snapAngle(from, p);
    const aligned = Math.abs(point[0] - from[0]) < 1e-10 || Math.abs(point[1] - from[1]) < 1e-10;
    if (aligned && distance(point) <= reach) return { point, target: 'right_angle' };
  }
  const anchor = nearest(anchors);
  if (anchor) return { point: [...anchor], target: 'anchor' };
  const lower = nearest(below.map(project).filter(Boolean).map(row => row.point));
  if (lower) return { point: lower, target: 'below' };
  return { point: p.map(v => grid > 0 ? Math.round(v / grid) * grid : v), target: 'grid' };
}

// Slice-1 callers retain their half-foot grid and endpoint semantics.
export function snapPoint(p, walls = [], { grid = 0.5, reach = 1.0, exclude = [] } = {}) {
  const distance = q => Math.hypot(q[0] - p[0], q[1] - p[1]);
  const nearest = points => points.filter(q => !exclude.some(e => Math.hypot(e[0] - q[0], e[1] - q[1]) < 1e-6)
    && distance(q) <= reach).sort((a, b) => distance(a) - distance(b))[0];
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
