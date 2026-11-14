import { edgeDistance, inPolygon } from '../twin_ground.js';
import { pathOutline } from '../path_shapes.js';

export function snapSitePoint(point, plan, exclude) {
  const segments = [], polygon = ps => { if (ps?.length) ps.forEach((p, i) => segments.push([p, ps[(i + 1) % ps.length]])); };
  polygon(plan.site?.lot);
  for (const kind of ['terraces', 'beds', 'hardscape', 'edges', 'yard_rooms']) for (const piece of plan.site?.[kind] || []) if (!exclude || piece.id !== exclude) {
    if (piece.kind === 'path') polygon(pathOutline(piece));
    else if (piece.polygon) polygon(piece.polygon);
    else for (let i = 1; i < (piece.points || []).length; i++) segments.push([piece.points[i - 1], piece.points[i]]);
  }
  if (!exclude || plan.site?.pool?.id !== exclude) polygon(plan.site?.pool?.polygon);
  for (const f of plan.site?.pool?.features || []) if (f.id !== exclude) polygon(f.polygon);
  for (const pit of Array.isArray(plan.site?.fire_pit) ? plan.site.fire_pit : plan.site?.fire_pit ? [plan.site.fire_pit] : []) if (!exclude || pit.id !== exclude) polygon(pit.polygon);
  for (const b of plan.buildings || []) {
    const angle = (b.rotation || 0) * Math.PI / 180;
    const placed = p => [Math.cos(angle) * p[0] - Math.sin(angle) * p[1] + (b.position?.[0] || 0), Math.sin(angle) * p[0] + Math.cos(angle) * p[1] + (b.position?.[1] || 0)];
    for (const w of b.walls || []) if (w.exterior && w.state !== 'ghost') {
      // Connected-model footprints run along the two wall faces. Choose the
      // face outside the interior rooms; old plans use the outside datum.
      let face = [w.from, w.to];
      if (w.footprint?.length === 4) {
        const rooms = (b.rooms || []).filter(r => r.level === w.level && r.state !== 'ghost' && r.polygon?.length && r.kind !== 'porch');
        const interiors = rooms.map(r => r.polygon);
        if (!interiors.length) { const outline = b.levels?.find(l => l.id === w.level)?.outline; if (outline?.length) interiors.push(outline); }
        const faces = [[w.footprint[0], w.footprint[1]], [w.footprint[3], w.footprint[2]]];
        face = faces.find(f => !interiors.some(poly => inPolygon(poly, ...f[0].map((v, i) => (v + f[1][i]) / 2)))) || faces[0];
      }
      if (face.every(Boolean)) segments.push(face.map(placed));
    }
  }
  let best = point, distance = .75;
  for (const [a, b] of segments) {
    const d = edgeDistance(point, a, b); if (d >= distance) continue;
    const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy;
    const t = l ? Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / l)) : 0;
    best = [a[0] + t * dx, a[1] + t * dy]; distance = d;
  }
  return best.map(v => Math.round(v * 1000) / 1000);
}
export const polygonArea = ps => Math.abs(ps.reduce((sum, p, i) => sum + p[0] * ps[(i + 1) % ps.length][1] - p[1] * ps[(i + 1) % ps.length][0], 0)) / 2;

// One draft and one completed operation: clicks and previews never enter history.
export function createSiteDrawing({ getPlan, commit }) {
  let draft = null, hover = null, saving = false;
  return {
    start(kind, options = {}) { draft = { kind, options, points: [] }; hover = null; },
    current: () => draft,
    point(p, free = false) { return free ? p.map(v => Math.round(v * 1000) / 1000) : snapSitePoint(p, getPlan()); },
    add(p, free = false) { if (!draft || saving) return; const q = this.point(p, free); if (!draft.points.length || Math.hypot(...q.map((v, i) => v - draft.points.at(-1)[i])) >= .01) draft.points.push(q); hover = null; },
    move(p, free = false) { if (draft) hover = this.point(p, free); },
    preview() { return draft ? [...draft.points, ...(hover ? [hover] : [])] : []; },
    back() { if (!saving) { draft?.points.pop(); hover = null; } },
    cancel() { if (!saving) { draft = null; hover = null; } },
    async finish() {
      if (!draft || saving) return false;
      const d = draft, path = d.kind === 'path', fence = d.kind === 'fence', placement = d.kind === 'fire_pit' && d.options.shape !== 'outline';
      if (d.points.length < (placement ? 1 : path || fence ? 2 : 3)) throw new Error(`Add at least ${placement ? 'one point' : path || fence ? 'two points' : 'three corners'}.`);
      const operation = ['ledge', 'steps', 'spa'].includes(d.kind) ? { op: 'add_pool_feature', kind: d.kind, polygon: d.points, ...d.options }
        : d.kind === 'terraces' ? { op: 'add_pad', polygon: d.points, ...d.options }
        : { op: 'add_site_shape', list: path ? 'hardscape' : d.kind, ...(d.kind === 'yard_rooms' ? { name: 'Yard room' } : {}), ...(placement ? { at: d.points[0] } : fence ? { polyline: d.points } : path ? { kind: 'path', points: d.points } : { polygon: d.points }), ...d.options };
      saving = true;
      try { if (await commit(operation) === false) return false; draft = null; hover = null; return true; }
      finally { saving = false; }
    },
  };
}
