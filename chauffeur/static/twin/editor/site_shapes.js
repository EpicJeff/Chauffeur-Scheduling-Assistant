import { sitePoints } from '../objects.js';

export const shapeKey = piece => ['polygon', 'points', 'polyline'].find(key => piece[key]);
export const closedShape = record => record.kind !== 'fence' && (record.kind !== 'edges' || !!record.piece.polygon);
export function shapeCentre(piece) {
  const points = sitePoints(piece);
  if (piece.polygon) {
    let area = 0, x = 0, y = 0;
    points.forEach((p, i) => {
      const q = points[(i + 1) % points.length], a = p[0] * q[1] - q[0] * p[1];
      area += a; x += (p[0] + q[0]) * a; y += (p[1] + q[1]) * a;
    });
    if (Math.abs(area) > 1e-9) return [x / (3 * area), y / (3 * area)];
  }
  return [0, 1].map(i => points.reduce((n, p) => n + p[i], 0) / points.length);
}
export function shapeSize(piece) {
  const points = sitePoints(piece);
  return [0, 1].map(i => Math.max(...points.map(p => p[i])) - Math.min(...points.map(p => p[i])));
}
const clean = v => Math.round(v * 1e9) / 1e9;
export function transformShape(piece, { rotation, scale = [1, 1], centre = shapeCentre(piece) } = {}) {
  const origin = shapeCentre(piece), angle = ((rotation ?? piece.rotation ?? 0) - (piece.rotation || 0)) * Math.PI / 180;
  const key = shapeKey(piece);
  const points = sitePoints(piece).map(p => {
    const x = (p[0] - origin[0]) * scale[0], y = (p[1] - origin[1]) * scale[1];
    return [clean(centre[0] + x * Math.cos(angle) - y * Math.sin(angle)), clean(centre[1] + x * Math.sin(angle) + y * Math.cos(angle))];
  });
  return { ...(key ? { [key]: points } : { at: points[0] }), ...(rotation === undefined ? {} : { rotation: (rotation % 360 + 360) % 360 }) };
}
export const shapeOperation = (record, change) => ({ op: 'update_site_shape', list: record.kind, index: record.index, ...change });
