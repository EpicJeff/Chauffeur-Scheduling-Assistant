import { snapTo } from './snap.js';
import { hostPoint } from '../twin_hosts.js';
import { LocalMissing, moveGesture, movePreview, moveProblem } from './local_ops.js';

const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const delta = (a, b) => a.map((v, i) => v - b[i]);
const shifted = (p, by) => p.map((v, i) => v + by[i]);

export { piecesOnMovedJoints } from './local_ops.js';

// Flat-plan preview only. The op response supplies authoritative topology on release.
export function createDrag({ view, model, onPreview, onCommit }) {
  let gesture = null, lastDragFrameMs = null;
  const flat = () => typeof model === 'function' ? model() : model;
  function begin(selection, start) {
    if (gesture || !start) return false;
    const source = flat();
    let move;
    try { move = moveGesture(source, selection); }
    catch (error) { if (error instanceof LocalMissing) return false; throw error; }
    if (selection.kind === 'wall' && !move.normal) return false;
    lastDragFrameMs = null;
    gesture = { source, ...move, selection, start: [...start], by: [0, 0], preview: null };
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
    const key = `${b.id}:${level.id}`;
    const screen = view.screenOfFloor(...destination, key);
    const nearby = screen && view.floorAt(screen[0] + 12, screen[1], key);
    const reach = Math.max(.25, Math.min(1, nearby ? Math.hypot(...delta(nearby, destination)) : 1));
    const snap = snapTo(destination, { joints, walls, anchors, reach,
      below: b.walls.filter(w => w.level === below?.id) });
    // A wall has one degree of freedom. Reject a snap that would pull it along itself.
    const correction = delta(snap.point, destination);
    if (!g.normal || Math.abs(correction[0] * g.normal[1] - correction[1] * g.normal[0]) < 1e-5)
      by = delta(snap.point, origin);
    else if (g.normal) by = g.normal.map(v => v * Math.round(dot(by, g.normal) * 12) / 12);
    const preview = movePreview(g.source, g, by);
    // Snapping onto a joint can collapse an attached wall to nothing (a wall
    // dragged onto its neighbour's corner). That shape has no direction and
    // would deform the scene into NaN, so keep the last drawn frame instead.
    if (!preview) return true;
    g.by = by; g.preview = preview;
    view.rebuildLevel(b.id, level.id, preview, g.touched);
    // The server stays the judge: a problem is shown, the release still sends.
    onPreview?.(preview, g.selection, moveProblem(g.source, preview, b.id));
    lastDragFrameMs = Math.max(.001, performance.now() - started);
    return true;
  }
  async function finish(cancel = false) {
    const g = gesture; gesture = null;
    if (!g) return;
    // Clear the advisory before the server answers, keeping the released plan.
    if (g.preview) onPreview?.(g.preview, g.selection, null);
    if (cancel || !g.preview || Math.hypot(...g.by) < .001) {
      if (g.preview) { view.rebuildLevel(g.building.id, g.piece.level, g.source, g.touched); onPreview?.(g.source, g.selection); }
      return;
    }
    const { kind, id, building } = g.selection;
    const operation = kind === 'joint' ? { op: 'move_joint', building, joint: id, to: shifted(g.piece.at, g.by) }
      : { op: kind === 'wall' ? 'move_wall' : 'move_room', building, [kind]: id, by: g.by };
    try { await onCommit(operation, { local: g.preview }); }
    catch (error) {
      if (!error.refused && !error.dropped) {
        view.rebuildLevel(building, g.piece.level, g.source, g.touched); onPreview?.(g.source, g.selection);
      }
      throw error;
    }
  }
  return { begin, update, finish, active: () => !!gesture, clearDragFrame() { lastDragFrameMs = null; },
    get lastDragFrameMs() { return lastDragFrameMs; } };
}
