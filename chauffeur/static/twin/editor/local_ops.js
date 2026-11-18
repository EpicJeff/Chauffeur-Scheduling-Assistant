import { hostPoint } from '../twin_hosts.js';
import { sitePieces } from '../objects.js';

const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const delta = (a, b) => a.map((v, i) => v - b[i]);
const shifted = (p, by) => p.map((v, i) => v + by[i]);
const EPS = 1e-9, MIN_CLEAR = .5;
const SHORT = 'A wall must be at least 1 ft long.';
const NARROW = 'That would leave the door narrower than its wall.';
const CROSS = 'That would cross another wall.';
const cross = (a, b) => a[0] * b[1] - a[1] * b[0];

// Same open-segment intersection and collinear overlap as twin_model_ops.
function crosses(a, b, c, d) {
  const v = delta(b, a), w = delta(d, c), between = delta(c, a), denominator = cross(v, w);
  if (Math.abs(denominator) > EPS) {
    const t = cross(between, w) / denominator, u = cross(between, v) / denominator;
    if (t > EPS && t < 1 - EPS && u > EPS && u < 1 - EPS) return true;
  }
  const length = Math.hypot(...v);
  if (length <= EPS) return false;
  const axis = v.map(n => n / length);
  if ([c, d].some(p => Math.abs(cross(axis, delta(p, a))) > EPS)) return false;
  const ends = [dot(delta(c, a), axis), dot(delta(d, a), axis)].sort((x, y) => x - y);
  return Math.min(length, ends[1]) - Math.max(0, ends[0]) > EPS;
}

function wallLines(building) {
  const positions = new Map((building.joints || []).map(j => [j.id, j.at]));
  const lines = new Map();
  for (const wall of building.walls || []) {
    if (wall.state === 'ghost' || wall.joints?.length !== 2) continue;
    const [a, b] = wall.joints.map(id => positions.get(id));
    if (a && b && Math.hypot(...delta(b, a)) > EPS) lines.set(wall.id, { ...wall, a, b });
  }
  return lines;
}

export function moveProblem(before, after, buildingId) {
  // movePreview's null sentinel means an attached wall lost its direction.
  if (after === null) return SHORT;
  const previous = before?.buildings.find(b => b.id === buildingId);
  const building = after?.buildings.find(b => b.id === buildingId);
  if (!previous || !building) return null;
  const oldLines = wallLines(previous), lines = wallLines(building), changed = [];
  for (const [id, wall] of lines) {
    const old = oldLines.get(id);
    if (old && wall.level === old.level && (wall.thickness || 0) === (old.thickness || 0)
      && wall.joints.every((j, i) => j === old.joints[i])
      && wall.a.every((v, i) => v === old.a[i]) && wall.b.every((v, i) => v === old.b[i])) continue;
    changed.push(wall);
    const length = Math.hypot(...delta(wall.b, wall.a));
    if (length < 1 - EPS) return SHORT;
    if (old && length < Math.hypot(...delta(old.b, old.a)) - EPS) {
      const widths = ['openings', 'anchors', 'items'].flatMap(name => (building[name] || [])
        .filter(p => (name === 'openings' ? p : p.host)?.wall === id).map(p => p.width || 0));
      if (widths.length && length < Math.max(...widths) + 2 * MIN_CLEAR - EPS) return NARROW;
    }
  }
  // The server snapshot omits collapsed walls and checks them separately.
  if (building.walls.some(w => w.state !== 'ghost' && oldLines.has(w.id) && !lines.has(w.id))) return SHORT;
  const levels = new Map();
  for (const wall of lines.values()) {
    if (!levels.has(wall.level)) levels.set(wall.level, []);
    levels.get(wall.level).push(wall);
  }
  // Only changed walls against their level, never every pair in the house.
  const checked = new Set();
  for (const wall of changed) {
    for (const other of levels.get(wall.level)) {
      if (other.id === wall.id || checked.has(other.id)) continue;
      if (!crosses(wall.a, wall.b, other.a, other.b)) continue;
      const old = oldLines.get(wall.id), prior = oldLines.get(other.id);
      if (!old || !prior || !crosses(old.a, old.b, prior.a, prior.b)) return CROSS;
    }
    checked.add(wall.id);
  }
  return null;
}

// Geometry and hosts that can change when these joints move. Crossings used
// by room cycles are included even when they are not persisted wall ends.
export function piecesOnMovedJoints(building, joints) {
  const moved = new Set(joints);
  const walls = building.walls.filter(w => w.joints?.some(id => moved.has(id))).map(w => w.id);
  const rooms = building.rooms.filter(r => r.joints?.some(id => moved.has(id))).map(r => r.id);
  const wallIds = new Set(walls), roomIds = new Set(rooms);
  const result = { walls, rooms };
  for (const list of ['openings', 'anchors', 'items']) result[list] = (building[list] || []).filter(piece =>
    wallIds.has(piece.wall) || wallIds.has(piece.host?.wall)
      || roomIds.has(piece.host?.floor) || roomIds.has(piece.host?.ceiling)).map(piece => piece.id);
  return result;
}

export class LocalMissing extends Error {
  constructor(message) { super(message); this.name = 'LocalMissing'; }
}

export function moveGesture(plan, selection) {
  const building = plan?.buildings?.find(b => b.id === selection.building);
  if (!building) throw new LocalMissing(`Missing building: ${selection.building}`);
  const list = { wall: 'walls', joint: 'joints', room: 'rooms' }[selection.kind];
  const piece = building?.[list]?.find(p => p.id === selection.id);
  if (!piece || piece.state === 'ghost') throw new LocalMissing(`Missing ${selection.kind}: ${selection.id}`);
  const moved = new Set(piece.joints || [piece.id]);
  let normal = null;
  if (selection.kind === 'wall') {
    const d = delta(piece.to, piece.from), length = Math.hypot(...d);
    if (length) {
      normal = [-d[1] / length, d[0] / length];
      // A room cycle may use derived T/crossing joints within this wall (R25).
      for (const joint of building.joints || []) {
        const v = delta(joint.at, piece.from), along = dot(v, d) / (length * length);
        if (joint.level === piece.level && along >= -1e-6 && along <= 1 + 1e-6
          && Math.abs(dot(v, normal)) < 1e-5) moved.add(joint.id);
      }
    }
  }
  const touched = piecesOnMovedJoints(building, moved);
  const oldWalls = new Map(building.walls.map(w => [w.id, w]));
  return { building, piece, moved, touched, oldWalls, normal };
}

export function movePreview(plan, gesture, by) {
  const g = gesture, b = g.building;
  const preview = structuredClone(plan), building = preview.buildings.find(row => row.id === b.id);
  const positions = new Map();
  for (const joint of building.joints) {
    if (g.moved.has(joint.id)) joint.at = shifted(joint.at, by);
    positions.set(joint.id, joint.at);
  }
  const wallIds = new Set(g.touched.walls), roomIds = new Set(g.touched.rooms);
  for (const wall of building.walls) {
    if (!wallIds.has(wall.id)) continue;
    const old = g.oldWalls.get(wall.id);
    wall.from = [...positions.get(wall.joints[0])]; wall.to = [...positions.get(wall.joints[1])];
    // Transport each end's face offsets with the connected joint.
    if (wall.footprint) wall.footprint = wall.footprint.map((p, i) =>
      shifted(p, delta(i === 0 || i === 3 ? wall.from : wall.to, i === 0 || i === 3 ? old.from : old.to)));
  }
  // A collapsed wall has no direction and would deform the scene into NaN.
  if (building.walls.some(w => wallIds.has(w.id) && Math.hypot(...delta(w.to, w.from)) < 1e-6)) return null;
  for (const room of building.rooms) if (roomIds.has(room.id) && room.joints?.every(id => positions.has(id)))
    room.polygon = room.joints.map(id => [...positions.get(id)]);
  for (const l of building.levels) {
    const original = b.levels.find(row => row.id === l.id);
    if (l.footprint?.every(id => positions.has(id))) l.outline = l.footprint.map(id => [...positions.get(id)]);
    else if (l.outline) l.outline = original.outline.map(p => {
      const joint = b.joints.find(j => j.level === l.id && g.moved.has(j.id) && Math.hypot(...delta(p, j.at)) < .01);
      return joint ? [...positions.get(joint.id)] : [...p];
    });
  }
  for (const list of ['openings', 'anchors', 'items']) for (const piece of building[list] || []) {
    if (!piece.host || !g.touched[list].includes(piece.id)) continue;
    try { piece.position = hostPoint(building, piece.host, piece.offset || 0); }
    catch { /* Missing hosts retain their existing ghost representation. */ }
  }
  return preview;
}

export function applyLocal(plan, operation) {
  if (operation.op === 'set_object' || operation.op === 'move_hosted') {
    // Opening slides use {at}, not a replacement object host.
    if (operation.op === 'move_hosted' && !operation.host) return null;
    const properties = operation.op === 'move_hosted' ? { host: operation.host } : operation.properties;
    if (!properties || Object.keys(properties).some(k => !['rotation', 'scale', 'scale_axes', 'host'].includes(k))) return null;
    const preview = structuredClone(plan), building = preview.buildings.find(b => b.id === operation.building);
    const list = building && ['items', 'anchors', 'openings'].find(name => building[name]?.some(p => p.id === operation.id));
    const piece = list ? building[list].find(p => p.id === operation.id) : !operation.building && sitePieces(preview.site?.[operation.list])[operation.index];
    if (!piece || piece.device) throw new LocalMissing(`Missing object: ${operation.id || operation.list}`);
    Object.assign(piece, structuredClone(properties));
    if (piece.host && building) {
      try { piece.position = hostPoint(building, piece.host, piece.offset || 0); } catch { /* Server judges missing hosts. */ }
    }
    return { plan: preview, building: building?.id || null, level: building?.walls.find(w => w.id === (piece.wall || piece.host?.wall))?.level
      || building?.rooms.find(r => r.id === (piece.host?.floor || piece.host?.ceiling))?.level || building?.levels[0]?.id || null,
      touched: list ? { [list]: [piece.id] } : { site: [operation.list] } };
  }
  if (operation.op === 'update_site_shape') {
    if (Object.keys(operation).some(k => !['op', 'list', 'index', 'id', 'polygon', 'points', 'polyline', 'at', 'radius', 'rotation', 'features'].includes(k))) return null;
    const preview = structuredClone(plan);
    const pieces = sitePieces(preview.site?.[operation.list]);
    const index = operation.id ? pieces.findIndex(p => p.id === operation.id) : operation.index ?? 0, piece = pieces[index];
    if (!piece) throw new LocalMissing(`Missing site shape: ${operation.id || operation.list}`);
    for (const [key, value] of Object.entries(operation)) if (!['op', 'list', 'index', 'id'].includes(key)) piece[key] = structuredClone(value);
    return { plan: preview, building: null, level: null, touched: { site: [operation.list] } };
  }
  if (operation.op === 'update_light_fixture') {
    if (Object.keys(operation.change).some(k => !['at', 'aim', 'rotation_deg'].includes(k))) return null;
    const preview = structuredClone(plan), piece = preview.light_fixtures?.[operation.entity_id]?.find(f => f.id === operation.id);
    if (!piece) throw new LocalMissing(`Missing light fixture: ${operation.id}`);
    Object.assign(piece, structuredClone(operation.change));
    return { plan: preview, building: null, level: null, touched: { light_fixtures: [operation.id] } };
  }
  const kind = operation.op === 'move_wall' ? 'wall' : operation.op === 'move_joint' ? 'joint'
    : operation.op === 'move_room' ? 'room' : null;
  if (kind) {
    const gesture = moveGesture(plan, { kind, building: operation.building, id: operation[kind] });
    if (kind === 'wall' && !gesture.normal) return null;
    const by = kind === 'joint' ? delta(operation.to, gesture.piece.at)
      : kind === 'wall' && typeof operation.by === 'number' ? gesture.normal.map(v => v * operation.by) : operation.by;
    const preview = movePreview(plan, gesture, by);
    return preview && { plan: preview, building: gesture.building.id, level: gesture.piece.level, touched: gesture.touched };
  }
  if (operation.op !== 'move_site_item') return null;
  const name = operation.list, value = plan.site?.[name];
  const singleton = ['pool', 'fire_pit', 'fence'].includes(name) && !Array.isArray(value);
  const pieces = singleton ? value ? [value] : [] : value || [];
  const index = operation.id ? pieces.findIndex(p => p.id === operation.id) : operation.index ?? (singleton ? 0 : null);
  if (!Number.isInteger(index) || index < 0 || index >= pieces.length) throw new LocalMissing(`Missing site item: ${name}`);
  if (!('by' in operation) && !('at' in pieces[index])) return null;
  const preview = structuredClone(plan), piece = singleton ? preview.site[name] : preview.site[name][index];
  if ('by' in operation) {
    // As the server does: plan x and y only.
    const by = p => [p[0] + operation.by[0], p[1] + operation.by[1]];
    for (const key of ['at', 'polygon', 'points', 'polyline']) {
      if (!(key in piece)) continue;
      piece[key] = key === 'at' ? by(piece[key]) : piece[key].map(by);
    }
    if (name === 'pool') for (const feature of piece.features || [])
      feature.polygon = feature.polygon.map(by);
  } else piece.at = [operation.at[0], operation.at[1]];
  return { plan: preview, building: null, level: null, touched: { site: [name] } };
}
