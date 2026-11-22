import { hostPoint } from '../twin_hosts.js';
import { Matrix4 } from 'three';
import { openingFloor } from '../twin_floors.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { contains } from '../twin_generator.js';
import { sitePieces, sitePoints, objectOperation } from '../objects.js';
import { fixtureReference } from '../live/emitters.js';
import { transformShape, shapeCentre, shapeOperation } from './site_shapes.js';

const FT = .3048, rad = a => a * Math.PI / 180;
const wrap = a => (a % 360 + 360) % 360;
const key = r => JSON.stringify([r.buildingId ?? null, r.pieceId]);
const shapes = ['terraces', 'hardscape', 'beds', 'edges', 'fence', 'fire_pit', 'yard_rooms'];
const collections = { wall: 'walls', opening: 'openings', item: 'items', anchor: 'anchors' };
export function groupRecord(plan, ref) {
  const id = ref.pieceId ?? ref.id, bid = ref.buildingId ?? ref.building;
  if (['light_fixture', 'effect_fixture'].includes(ref.kind)) {
    const effect = ref.kind === 'effect_fixture';
    const entity_id = ref.entity_id || Object.keys(plan.light_fixtures || {}).find(e => plan.light_fixtures[e].some(p => p.id === id));
    const piece = (effect ? plan.effect_fixtures : plan.light_fixtures?.[entity_id])?.find(p => p.id === id);
    return piece && { piece, kind: ref.kind, fixture: true, effect, entity_id, ref };
  }
  const building = bid && plan.buildings.find(b => b.id === bid), list = collections[ref.kind];
  if (ref.kind === 'device') {
    const piece = (building?.devices || (!bid && plan.site?.devices))?.find(p => p.id === id);
    return piece && { piece, kind: 'device', building, ref };
  }
  if (building && list) {
    const piece = building[list]?.find(p => p.id === id);
    return piece && { piece, kind: ref.kind, building, list, ref };
  }
  if (bid) return null;
  if (['spa', 'ledge', 'steps'].includes(ref.kind)) {
    const piece = plan.site?.pool?.features?.find(p => p.id === id);
    return piece && { piece, kind: ref.kind, pool: true, ref };
  }
  if (![...shapes, 'planting', 'furniture'].includes(ref.kind)) return null;
  const pieces = sitePieces(plan.site?.[ref.kind]), index = pieces.findIndex((p, i) => (p.id || `${ref.kind}:${i}`) === id);
  return index < 0 ? null : { piece: pieces[index], kind: ref.kind, index, shape: shapes.includes(ref.kind), ref };
}

export function canTransform(r, tool) {
  if (!r || r.piece.state === 'ghost') return false;
  if (r.kind === 'wall') return tool !== 'scale';
  if (r.kind === 'opening') return tool !== 'rotate';
  if (r.pool) return tool === 'move';
  if (r.fixture) return tool !== 'scale';
  if (['item', 'anchor'].includes(r.kind)) return !r.piece.device;
  return r.shape || ['planting', 'furniture'].includes(r.kind);
}

function toWorld(r, at) {
  const b = r.building, a = rad(b?.rotation || 0), p = b?.position || [0, 0];
  return [at[0] * Math.cos(a) - at[1] * Math.sin(a) + p[0], at[0] * Math.sin(a) + at[1] * Math.cos(a) + p[1]];
}
function toLocal(r, at) {
  const b = r.building, a = -rad(b?.rotation || 0), p = b?.position || [0, 0], x = at[0] - p[0], y = at[1] - p[1];
  return [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)];
}
function points(r) {
  const p = r.piece;
  if (r.kind === 'wall') return [p.from, p.to];
  if (r.kind === 'opening') {
    const w = r.building.walls.find(w => w.id === p.wall), d = w.to.map((v, i) => v - w.from[i]), length = Math.hypot(...d);
    return [p.at - p.width / 2, p.at + p.width / 2].map(at => w.from.map((v, i) => v + d[i] * at / length));
  }
  if (r.building) return [hostPoint(r.building, p.host, p.offset || 0)];
  return r.fixture ? p.path || [p.at] : sitePoints(p);
}

// Resolve once per gesture. World boxes are the same rendered bounds used by
// marquee and outlines; fallback points keep headless/undrawn pieces usable.
export function groupTransform(plan, refs, tool, { boxes = [], isPickable = () => true } = {}) {
  const records = refs.filter(isPickable).map(ref => groupRecord(plan, ref)).filter(r => canTransform(r, tool));
  if (!records.length) return null;
  const byRef = new Map(boxes.map(b => [key(b), b.box]));
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  for (const r of records) {
    const box = byRef.get(key(r.ref));
    let values;
    if (box) values = [[box.min.x / FT, -box.max.z / FT, box.min.y / FT], [box.max.x / FT, -box.min.z / FT, box.max.y / FT]];
    else values = points(r).map(p => {
      const at = toWorld(r, p), height = r.fixture ? (p[2] || 0) + fixtureReference(plan, r.piece, p) + (r.piece.offset_ft || 0)
        : r.building ? (p[2] || 0) + (r.building.base || 0) + buildingGround(plan, r.building) : groundAt(plan, ...at);
      return [...at, height];
    });
    for (const p of values) for (let i = 0; i < 3; ++i) { min[i] = Math.min(min[i], p[i]); max[i] = Math.max(max[i], p[i]); }
  }
  return { plan, records, tool, centre: min.map((v, i) => (v + max[i]) / 2) };
}

function hosted(r, at) {
  const { host } = r.piece;
  if (host.ground) return { ...host, at };
  if (host.wall || host.roof) {
    const w = r.building.walls.find(w => w.id === host.wall), roof = r.building.roofs?.find(p => p.id === host.roof);
    const a = w?.from || roof?.area[host.edge], b = w?.to || roof?.area[(host.edge + 1) % roof.area.length];
    const d = b.map((v, i) => v - a[i]), length = Math.hypot(...d);
    return { ...host, at: at.reduce((n, v, i) => n + (v - a[i]) * d[i] / length, 0) };
  }
  const source = r.building.rooms.find(p => p.id === (host.floor || host.ceiling));
  const room = r.building.rooms.find(p => p.state !== 'ghost' && p.level === source?.level && contains(p.polygon, at));
  if (!room || !contains(room.polygon, at)) throw new Error(`${r.piece.id} must stay on its surface.`);
  const lo = [0, 1].map(i => Math.min(...room.polygon.map(p => p[i]))), hi = [0, 1].map(i => Math.max(...room.polygon.map(p => p[i])));
  return { ...host, [host.ceiling ? 'ceiling' : 'floor']: room.id, u: (at[0] - lo[0]) / (hi[0] - lo[0]), v: (at[1] - lo[1]) / (hi[1] - lo[1]) };
}

export function transformOperations(g, { by = [0, 0], angle = 0, factor = 1 } = {}) {
  const ops = [], joints = new Map(), a = rad(angle), c = g.centre;
  const transform = p => g.tool === 'move' ? [p[0] + by[0], p[1] + by[1]]
    : g.tool === 'rotate' ? [c[0] + (p[0] - c[0]) * Math.cos(a) - (p[1] - c[1]) * Math.sin(a), c[1] + (p[0] - c[0]) * Math.sin(a) + (p[1] - c[1]) * Math.cos(a)]
      : [c[0] + (p[0] - c[0]) * factor, c[1] + (p[1] - c[1]) * factor];
  for (const r of g.records) {
    const p = r.piece, position = points(r)[0];
    if (r.kind === 'wall') {
      if (!joints.has(r.building.id)) joints.set(r.building.id, new Map());
      for (const id of p.joints) {
        const joint = r.building.joints.find(j => j.id === id);
        joints.get(r.building.id).set(id, { joint: id, to: toLocal(r, transform(toWorld(r, joint.at))) });
      }
    } else if (r.kind === 'opening') {
      const w = r.building.walls.find(w => w.id === p.wall), d = w.to.map((v, i) => v - w.from[i]), length = Math.hypot(...d);
      const mid = w.from.map((v, i) => v + d[i] * p.at / length), moved = toLocal(r, transform(toWorld(r, mid)));
      const at = moved.reduce((n, v, i) => n + (v - w.from[i]) * d[i] / length, 0);
      if (g.tool === 'move') {
        // If its wall is moving, the existing host-follow path already carries it.
        if (g.records.some(w => w.kind === 'wall' && w.building === r.building && w.piece.id === p.wall)) continue;
        ops.push({ op: 'move_hosted', building: r.building.id, id: p.id, at });
      } else ops.push({ op: 'resize_opening', building: r.building.id, id: p.id, at, width: p.width * factor, sill: p.sill, head: p.sill + (p.head - p.sill) * factor });
    } else if (r.fixture) {
      const placed = q => [...transform(q), q[2]];
      const change = p.path ? { path: p.path.map(placed) } : { at: placed(p.at) };
      if (p.path) { if (p.snap) change.snap = null; if (p.anchors) change.anchors = null; }
      if (p.aim) change.aim = placed(p.aim);
      if (!r.effect && !p.path && g.tool === 'rotate') change.rotation_deg = wrap((p.rotation_deg || 0) + angle);
      if (Array.isArray(p.facing) && g.tool === 'rotate') {
        change.facing = [p.facing[0] * Math.cos(a) - p.facing[1] * Math.sin(a), p.facing[0] * Math.sin(a) + p.facing[1] * Math.cos(a), p.facing[2]];
      }
      ops.push({ op: r.effect ? 'update_effect_fixture' : 'update_light_fixture', ...(!r.effect ? { entity_id: r.entity_id } : {}), id: p.id, change });
    } else if (r.shape || r.pool) {
      const origin = shapeCentre(p), centre = transform(origin);
      const change = transformShape(p, { centre, ...(g.tool === 'rotate' ? { rotation: wrap((p.rotation || 0) + angle) } : {}), ...(g.tool === 'scale' ? { scale: [factor, factor] } : {}) });
      if (g.tool === 'scale' && p.radius) change.radius = p.radius * factor;
      if (g.tool === 'scale' && r.kind === 'hardscape' && p.kind === 'path') change.width = (p.width ?? 3) * factor;
      ops.push(r.kind === 'terraces' ? { op: 'update_pad', id: p.id, ...change } : { ...shapeOperation(r, change), id: p.id });
    } else {
      const target = toLocal(r, transform(toWorld(r, position)));
      if (g.tool !== 'move') ops.push({ ...objectOperation(r, g.tool === 'rotate' ? { rotation: wrap((p.rotation || 0) + angle) } : { scale: (p.scale ?? 1) * factor }), id: p.id });
      if (r.building) {
        if (!g.records.some(w => w.kind === 'wall' && w.building === r.building && w.piece.id === p.host?.wall))
          ops.push({ op: 'move_hosted', building: r.building.id, id: p.id, host: hosted(r, target) });
      } else ops.push({ op: 'move_site_item', list: r.kind, id: p.id, index: r.index, at: target });
    }
  }
  for (const [building, values] of joints) ops.unshift({ op: 'move_joints', building, joints: [...values.values()] });
  return ops;
}

function pose(r, plan) {
  const p = r.piece;
  if (r.fixture) {
    const at = p.path?.[0] || p.at;
    return [at[0], at[1], at[2] + fixtureReference(plan, p, at) + (p.offset_ft || 0)];
  }
  let at;
  if (r.kind === 'opening') {
    const w = r.building.walls.find(w => w.id === p.wall), d = w.to.map((v, i) => v - w.from[i]), length = Math.hypot(...d);
    at = [...w.from.map((v, i) => v + d[i] * p.at / length), (r.building.levels.find(l => l.id === w.level)?.elevation || 0) + openingFloor(r.building, w, p.at).offset + p.sill];
  } else if (r.building) { at = hostPoint(r.building, p.host, p.offset || 0); at[2] += p.elevation || 0; }
  else at = [...(r.shape || r.pool ? shapeCentre(p) : p.at), groundAt(plan, ...(r.shape || r.pool ? shapeCentre(p) : p.at)) + (p.elevation || 0)];
  return [...toWorld(r, at), at[2] + (r.building ? (r.building.base || 0) + buildingGround(plan, r.building) : 0)];
}
const translate = p => new Matrix4().makeTranslation(p[0] * FT, p[2] * FT, -p[1] * FT);
// Preview the constrained result, not the mouse's raw affine transform. In
// particular, windows slide along walls and footprint scaling keeps pad height.
export function previewTransforms(g, transform, preview) {
  const specs = [];
  for (const r of g.records) {
    let matrix;
    if (r.kind === 'wall') matrix = translate(g.centre.map((v, i) => v + (transform.by?.[i] || 0)))
      .multiply(new Matrix4().makeRotationY(rad(transform.angle || 0))).multiply(translate(g.centre.map(v => -v)));
    else {
      const next = groupRecord(preview, r.ref), from = pose(r, g.plan), to = pose(next, preview);
      matrix = translate(to).multiply(new Matrix4().makeRotationY(rad(transform.angle || 0)));
      const factor = transform.factor || 1;
      if (r.kind === 'opening') {
        const wall = r.building.walls.find(w => w.id === r.piece.wall), angle = Math.atan2(wall.to[1] - wall.from[1], wall.to[0] - wall.from[0]) + rad(r.building.rotation || 0);
        matrix.multiply(new Matrix4().makeRotationY(angle)).multiply(new Matrix4().makeScale(factor, factor, 1)).multiply(new Matrix4().makeRotationY(-angle));
      } else matrix.multiply(new Matrix4().makeScale(factor, r.shape || r.pool ? 1 : factor, factor));
      matrix.multiply(translate(from.map(v => -v)));
    }
    specs.push({ ...r.ref, matrix });
  }
  return specs;
}

export function deleteOperations(plan, refs) {
  const ops = refs.map(ref => {
    const r = groupRecord(plan, ref), id = ref.pieceId;
    if (r?.fixture) return { op: r.effect ? 'delete_effect_fixture' : 'delete_light_fixture', id, ...(!r.effect ? { entity_id: r.entity_id } : {}) };
    if (r?.kind === 'device') return { op: 'unplace_device', device: r.piece.device || r.piece.device_id };
    if (ref.kind === 'terraces') return { op: 'delete_pad', id };
    if (r?.pool) return { op: 'delete_pool_feature', id };
    if (!ref.buildingId) return { op: 'delete_site_item', list: ref.kind, id };
    return { op: 'delete', building: ref.buildingId, id };
  });
  // Children before hosts: all still exist when their own delete is applied.
  const priority = op => op.op === 'unplace_device' ? 0 : op.op === 'delete_site_item' && ['pool', 'yard_rooms'].includes(op.list) ? 3
    : op.op === 'delete' && ['walls', 'rooms'].some(list => plan.buildings.find(p => p.id === op.building)?.[list].some(p => p.id === op.id)) ? 2 : 1;
  return ops.sort((a, b) => priority(a) - priority(b));
}
