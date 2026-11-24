export const SUPPORT_KINDS = ['walls', 'bracket', 'corbel', 'brace', 'cable', 'post'];

export function isSupported(section) {
  return !!section.support?.kind && section.support.kind !== 'walls';
}

/** Authored outer-edge points in building feet. u is distance along the edge. */
export function supportPoints(roof) {
  if (!isSupported(roof)) return [];
  const area = roof.area || [[roof.rect[0], roof.rect[1]], [roof.rect[2], roof.rect[1]],
    [roof.rect[2], roof.rect[3]], [roof.rect[0], roof.rect[3]]];
  const segments = area.map((a, i) => [a, area[(i + 1) % area.length]]);
  const axis = (a, b) => Math.abs(a[0] - b[0]) <= 1e-8 ? 0 : Math.abs(a[1] - b[1]) <= 1e-8 ? 1 : null;
  const host = roof.host?.edge;
  let edge;
  if (Number.isInteger(host) && host >= 0 && host < area.length) {
    const [a, b] = segments[host], dx = b[0] - a[0], dy = b[1] - a[1];
    const orientation = segments.reduce((n, [p, q]) => n + p[0] * q[1] - p[1] * q[0], 0);
    const sign = orientation > 0 ? 1 : -1, inward = [-dy * sign, dx * sign];
    const candidates = segments.flatMap(([p, q], i) => i !== host && axis(p, q) === axis(a, b)
      && (q[0] - p[0]) * dx + (q[1] - p[1]) * dy < 0
      ? [[i, (p[0] - a[0]) * inward[0] + (p[1] - a[1]) * inward[1]]] : []);
    candidates.sort((a, b) => b[1] - a[1] || a[0] - b[0]);
    edge = candidates[0]?.[0] ?? host;
  } else {
    // All authored eaves bear at plate; gable/clip edges rise above it.
    edge = roof.edges?.findIndex(e => e.setting === 'sloped') ?? 0;
    if (edge < 0) edge = 0;
  }
  const [a, b] = segments[edge], width = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const support = roof.support, count = support.count ?? 2, inset = Math.min(support.inset_ft ?? .6, width / 2);
  return Array.from({length: count}, (_, i) => {
    let u = inset + i * (width - 2 * inset) / Math.max(1, count - 1);
    let at = support.at?.[String(i)];
    if (!at) at = a.map((v, k) => v + (b[k] - v) * u / width);
    else { at = [...at]; u = at.reduce((n, v, k) => n + (v - a[k]) * (b[k] - a[k]) / width, 0); }
    return {id: `support:${i}`, edge, u, at};
  });
}
