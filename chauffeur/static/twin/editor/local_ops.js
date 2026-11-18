import { hostPoint } from '../twin_hosts.js';

const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const delta = (a, b) => a.map((v, i) => v - b[i]);
const shifted = (p, by) => p.map((v, i) => v + by[i]);

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
