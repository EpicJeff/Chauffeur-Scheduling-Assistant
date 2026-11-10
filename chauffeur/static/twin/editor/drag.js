import { snapTo } from './snap.js';
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

// Flat-plan preview only. The op response supplies authoritative topology on release.
export function createDrag({ view, model, onPreview, onCommit }) {
  let gesture = null, lastDragFrameMs = null;
  const flat = () => typeof model === 'function' ? model() : model;
  function begin(selection, start) {
    if (gesture || !start) return false;
    const source = flat(), building = source?.buildings.find(b => b.id === selection.building);
    const list = { wall: 'walls', joint: 'joints', room: 'rooms' }[selection.kind];
    const piece = building?.[list]?.find(p => p.id === selection.id);
    if (!piece || piece.state === 'ghost') return false;
    const moved = new Set(piece.joints || [piece.id]);
    let normal = null;
    if (selection.kind === 'wall') {
      const d = delta(piece.to, piece.from), length = Math.hypot(...d);
      if (!length) return false;
      normal = [-d[1] / length, d[0] / length];
      // A room cycle may use derived T/crossing joints within this wall (R25).
      for (const joint of building.joints || []) {
        const v = delta(joint.at, piece.from), along = dot(v, d) / (length * length);
        if (joint.level === piece.level && along >= -1e-6 && along <= 1 + 1e-6
          && Math.abs(dot(v, normal)) < 1e-5) moved.add(joint.id);
      }
    }
    const touched = piecesOnMovedJoints(building, moved);
    const oldWalls = new Map(building.walls.map(w => [w.id, w]));
    gesture = { source, building, piece, selection, moved, touched, oldWalls, normal, start: [...start], by: [0, 0], preview: null };
    return true;
  }
  function update(point) {
    if (!gesture || !point) return false;
    const started = performance.now(), g = gesture, b = g.building;
    let by = delta(point, g.start);
    const level = b.levels.find(l => l.id === g.piece.level);
    const below = b.levels.filter(l => l.elevation < level.elevation).sort((a, c) => c.elevation - a.elevation)[0];
    const walls = b.walls.filter(w => w.level === level.id && !w.joints?.some(id => g.moved.has(id)));
    const joints = b.joints.filter(j => j.level === level.id && !g.moved.has(j.id));
    const anchors = (b.anchors || []).flatMap(a => {
      try { return [hostPoint(b, a.host).slice(0, 2)]; } catch { return []; }
    });
    const origin = g.normal ? g.piece.from.map((v, i) => (v + g.piece.to[i]) / 2)
      : g.piece.at || b.joints.find(j => j.id === g.piece.joints[0]).at;
    if (g.normal) by = g.normal.map(v => v * dot(by, g.normal));
    const destination = shifted(origin, by);
    // Two inches keeps a constrained wall drag from jumping to a distant
    // extension across another room; snapTo's general-purpose reach is a foot.
    const snap = snapTo(destination, { joints, walls, anchors, reach: 1 / 6,
      below: b.walls.filter(w => w.level === below?.id) });
    // A wall has one degree of freedom. Reject a snap that would pull it along itself.
    const correction = delta(snap.point, destination);
    if (!g.normal || Math.abs(correction[0] * g.normal[1] - correction[1] * g.normal[0]) < 1e-5)
      by = delta(snap.point, origin);
    else if (g.normal) by = g.normal.map(v => v * Math.round(dot(by, g.normal) * 12) / 12);
    const preview = structuredClone(g.source), building = preview.buildings.find(row => row.id === b.id);
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
    g.by = by; g.preview = preview;
    view.rebuildLevel(b.id, level.id, preview, g.touched);
    onPreview?.(preview, g.selection);
    lastDragFrameMs = Math.max(.001, performance.now() - started);
    return true;
  }
  async function finish(cancel = false) {
    const g = gesture; gesture = null;
    if (!g) return;
    if (cancel || !g.preview || Math.hypot(...g.by) < .001) {
      if (g.preview) { view.rebuildLevel(g.building.id, g.piece.level, g.source, g.touched); onPreview?.(g.source, g.selection); }
      return;
    }
    const { kind, id, building } = g.selection;
    const operation = kind === 'joint' ? { op: 'move_joint', building, joint: id, to: shifted(g.piece.at, g.by) }
      : { op: kind === 'wall' ? 'move_wall' : 'move_room', building, [kind]: id, by: g.by };
    try { await onCommit(operation); }
    catch (error) {
      view.rebuildLevel(building, g.piece.level, g.source, g.touched); onPreview?.(g.source, g.selection); throw error;
    }
  }
  return { begin, update, finish, active: () => !!gesture, get lastDragFrameMs() { return lastDragFrameMs; } };
}
