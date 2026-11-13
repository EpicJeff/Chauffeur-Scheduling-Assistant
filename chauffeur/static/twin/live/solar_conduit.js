// Surface routes in lot feet (z up). Rendering converts them to scene metres.
import { solarPlanes, solarZones, solarPoint, solarUV } from '../twin_solar.js';
import { buildingFootprint, groundAt } from '../twin_ground.js';
import { lotPoint } from './energy_geometry.js';

export const CONDUIT_OFFSET = 2 / 12;
const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
const cross = (a, b) => a[0] * b[1] - a[1] * b[0];
const centre = z => [(z.rect[0] + z.rect[2]) / 2, (z.rect[1] + z.rect[3]) / 2];
const near = (a, b) => distance(a, b) < 1e-6;

// Triangulation interiors cancel. The remaining edges include cutouts, so a
// downhill ray stops at the exposed edge rather than crossing a missing roof.
function boundary(plane) {
  const edges = new Map(), key = p => p.map(v => v.toFixed(6)).join(',');
  for (const triangle of plane.triangles) for (let i = 0; i < 3; i++) {
    const a = solarPoint(plane.plane, triangle[i]), b = solarPoint(plane.plane, triangle[(i + 1) % 3]);
    const id = [key(a), key(b)].sort().join(':');
    if (edges.has(id)) edges.delete(id); else edges.set(id, [a, b]);
  }
  return [...edges.values()];
}
function projection(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length)) : 0;
  return {t, at: [a[0] + t * dx, a[1] + t * dy]};
}
function eave(plane, uv) {
  const p = solarPoint(plane.plane, uv), edges = boundary(plane), [a, b, c] = plane.plane;
  const length = Math.hypot(a, b), direction = length ? [-a / length, -b / length] : null;
  let best = null, span = Infinity;
  for (const [start, end] of edges) {
    let at;
    if (direction) {
      const edge = [end[0] - start[0], end[1] - start[1]], delta = [start[0] - p[0], start[1] - p[1]];
      const den = cross(direction, edge); if (Math.abs(den) < 1e-9) continue;
      const t = cross(delta, edge) / den, u = cross(delta, direction) / den;
      if (t < -1e-6 || u < -1e-6 || u > 1 + 1e-6) continue;
      at = [p[0] + Math.max(0, t) * direction[0], p[1] + Math.max(0, t) * direction[1]];
    } else at = projection(p, start, end).at; // Flat roofs use their nearest edge.
    const d = Math.hypot(at[0] - p[0], at[1] - p[1]);
    if (d < span) {span = d; best = [...at, a * at[0] + b * at[1] + c];}
  }
  if (!best) return null;
  const norm = Math.hypot(a, b, 1), n = [-a / norm, -b / norm, 1 / norm];
  return {surface: best, at: best.map((v, i) => v + n[i] * CONDUIT_OFFSET)};
}

// Offset a wall perimeter outward, with mitred corners. Both windings work.
function perimeter(building, plan) {
  const poly = buildingFootprint(building).map(p => lotPoint(building, p, plan));
  if (poly.length < 3) return null;
  const winding = Math.sign(poly.reduce((s, p, i) => s + cross(p, poly[(i + 1) % poly.length]), 0)) || 1;
  const normals = poly.map((p, i) => {
    const q = poly[(i + 1) % poly.length], length = Math.hypot(q[0] - p[0], q[1] - p[1]);
    return length ? [winding * (q[1] - p[1]) / length, -winding * (q[0] - p[0]) / length] : [0, 0];
  });
  return poly.map((p, i) => {
    const a = normals[(i + poly.length - 1) % poly.length], b = normals[i], divisor = 1 + a[0] * b[0] + a[1] * b[1];
    return p.slice(0, 2).map((v, j) => v + CONDUIT_OFFSET * (a[j] + b[j]) / Math.max(.1, divisor));
  });
}
function wall(poly, p) {
  return poly.map((a, i) => ({...projection(p, a, poly[(i + 1) % poly.length]), edge: i}))
    .sort((a, b) => distance(a.at, p.slice(0, 2)) - distance(b.at, p.slice(0, 2)))[0];
}
function wallRun(poly, a, b, height) {
  const forward = (start, end) => {
    const out = [start.at];
    if (start.edge !== end.edge || start.t > end.t) {
      for (let i = (start.edge + 1) % poly.length; ; i = (i + 1) % poly.length) {
        out.push(poly[i]); if (i === end.edge) break;
      }
    }
    out.push(end.at); return out;
  };
  const candidates = [forward(a, b), forward(b, a).reverse()];
  const length = points => points.slice(1).reduce((s, p, i) => s + distance(p, points[i]), 0);
  return candidates.sort((a, b) => length(a) - length(b))[0].map(p => [...p, height]);
}
function groundLink(from, to) {
  // The closest pair faces the gap. Dropping from an eave on the far side
  // and immediately drawing toward the source could cross the satellite.
  const pairs = [
    ...from.map(p => ({from: wall(from, p), to: wall(to, p)})),
    ...to.map(p => ({from: wall(from, p), to: wall(to, p)}))
  ];
  return pairs.sort((a, b) => distance(a.from.at, a.to.at) - distance(b.from.at, b.to.at))[0];
}
function groundRun(plan, a, b) {
  // One-foot sampling follows blended terrain. Sharp terrace edges get both
  // heights at the crossing so the conduit follows the step, too.
  const ts = new Set([0, 1]), length = Math.hypot(a[0] - b[0], a[1] - b[1]);
  for (let i = 1; i < Math.ceil(length); i++) ts.add(i / Math.ceil(length));
  const delta = b.map((v, i) => v - a[i]);
  for (const pad of plan.site?.terraces || []) for (let i = 0; i < pad.polygon.length; i++) {
    const p = pad.polygon[i], q = pad.polygon[(i + 1) % pad.polygon.length], edge = q.map((v, j) => v - p[j]);
    const den = cross(delta, edge); if (Math.abs(den) < 1e-9) continue;
    const v = p.map((v, j) => v - a[j]), t = cross(v, edge) / den, u = cross(v, delta) / den;
    if (t > 0 && t < 1 && u >= 0 && u <= 1) for (const d of [-1e-6, 0, 1e-6]) ts.add(Math.max(0, Math.min(1, t + d)));
  }
  return [...ts].sort((a, b) => a - b).map(t => {
    const x = a[0] + delta[0] * t, y = a[1] + delta[1] * t;
    return [x, y, groundAt(plan, x, y) + CONDUIT_OFFSET];
  });
}

export function solarConduits(plan, anchors) {
  if (!anchors?.solar || !anchors.source) return [];
  const zones = (plan?.buildings || []).flatMap(building => solarZones(building).map(({zone}) => ({zone, building})));
  const sources = zones.filter(({zone, building}) => zone.roof === anchors.source &&
    (!plan.solar_source_building || building.id === plan.solar_source_building));
  if (!sources.length || new Set(sources.map(s => s.building.id)).size !== 1) return [];
  const source = sources.sort((a, b) => distance(lotPoint(a.building, solarPoint(a.zone.plane, centre(a.zone)), plan), anchors.solar) -
    distance(lotPoint(b.building, solarPoint(b.zone.plane, centre(b.zone)), plan), anchors.solar))[0];
  const planeFor = ({zone, building}) => solarPlanes(building).find(p => p.roof === zone.roof && p.plane.every((v, i) => Math.abs(v - zone.plane[i]) < 1e-5));
  // Project the shared anchor onto the selected source plane before climbing.
  const pos = source.building.position || [0, 0], angle = -(source.building.rotation || 0) * Math.PI / 180;
  const dx = anchors.solar[0] - pos[0], dy = anchors.solar[1] - pos[1];
  const local = [Math.cos(angle) * dx - Math.sin(angle) * dy, Math.sin(angle) * dx + Math.cos(angle) * dy];
  const sourcePlane = planeFor(source), [a, b, c] = source.zone.plane;
  const onRoof = [local[0], local[1], a * local[0] + b * local[1] + c];
  // UV basis is shared with panel placement, including roof slope.
  if (!sourcePlane) return [];
  const targetEave = eave(sourcePlane, solarUV(source.zone.plane, onRoof));
  const targetPoly = perimeter(source.building, plan); if (!targetEave || !targetPoly) return [];
  const targetAt = lotPoint(source.building, targetEave.at, plan), targetSurface = lotPoint(source.building, targetEave.surface, plan);
  const targetWall = wall(targetPoly, targetAt), routes = [];
  for (const satellite of zones) {
    if (satellite.building.id === source.building.id && satellite.zone.roof === anchors.source) continue;
    const edge = eave(planeFor(satellite), centre(satellite.zone)), poly = perimeter(satellite.building, plan);
    if (!edge || !poly) continue;
    const start = lotPoint(satellite.building, solarPoint(satellite.zone.plane, centre(satellite.zone), CONDUIT_OFFSET), plan);
    const at = lotPoint(satellite.building, edge.at, plan), surface = lotPoint(satellite.building, edge.surface, plan), from = wall(poly, at);
    const points = [start, at], same = satellite.building.id === source.building.id;
    const height = Math.min(surface[2], targetSurface[2]);
    if (same) {
      points.push([...from.at, surface[2]], ...wallRun(poly, from, targetWall, height), [...targetWall.at, targetSurface[2]]);
    } else {
      const link = groundLink(poly, targetPoly), lead = wallRun(poly, from, link.from, 0);
      points.push([...from.at, surface[2]]);
      for (let i = 1; i < lead.length; i++) points.push(...groundRun(plan, lead[i - 1], lead[i]));
      points.push(...groundRun(plan, link.from.at, link.to.at),
        ...wallRun(targetPoly, link.to, targetWall, targetSurface[2]));
    }
    points.push(targetAt, anchors.solar);
    routes.push({id: satellite.building.id + ':' + satellite.zone.id, entity: satellite.zone.entity || null,
      points: points.filter((p, i) => !i || !near(p, points[i - 1]))});
  }
  return routes;
}
