import { report } from './api.js';
import { snapTo } from './snap.js';
import { hostPoint } from '../twin_hosts.js';
import { contains } from '../twin_generator.js';

const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const drawingTools = ['draw-room', 'draw-wall', 'split-room', 'add-door', 'add-window', 'add-anchor'];

export function createDraw({ view, tools, getPlan, op, gesture, canEdit, signal, onInteract, panel }) {
  const el = id => document.getElementById(id), canvas = view.renderer3.domElement;
  let tool = null, points = [], press = null, busy = false, anchorKind = 'light';
  let saving = Promise.resolve(), pending = 0;
  const note = text => { el('draw-note').textContent = text; el('draw-tools').hidden = !text; };
  const outline = polygon => {
    const key = tools.floor()?.key;
    const screen = polygon.map(p => view.screenOfFloor(...p, key)).filter(Boolean);
    el('editor-drag-outline').setAttribute('points', screen.map(p => p.join(',')).join(' '));
  };
  function release() {
    if (!press) return;
    const previous = press; press = null;
    view.controls.enabled = previous.enabled;
    if (canvas.hasPointerCapture(previous.id)) canvas.releasePointerCapture(previous.id);
  }
  function cancel() {
    release(); tool = null; points = []; outline([]); note(''); tools.setTool('select');
    for (const name of drawingTools) el(`rail-${name}`).setAttribute('aria-pressed', 'false');
  }
  function snap(p, from) {
    const { building, level } = tools.floor();
    const below = building.levels.filter(l => l.elevation < level.elevation).sort((a, b) => b.elevation - a.elevation)[0];
    const anchors = (building.anchors || []).flatMap(a => {
      try { return [hostPoint(building, a.host).slice(0, 2)]; } catch { return []; }
    });
    const screen = view.screenOfFloor(...p, tools.floor().key);
    const nearby = screen && view.floorAt(screen[0] + 12, screen[1], tools.floor().key);
    const reach = Math.max(.25, Math.min(1, nearby ? distance(nearby, p) : 1));
    return snapTo(p, { from, reach, joints: (building.joints || []).filter(j => j.level === level.id),
      walls: building.walls.filter(w => w.level === level.id), anchors,
      below: building.walls.filter(w => w.level === below?.id) }).point;
  }
  function wallAt(p, walls = tools.floor().building.walls.filter(w => w.level === tools.floor().level.id)) {
    return walls.map(wall => {
      const d = wall.to.map((v, i) => v - wall.from[i]), length = Math.hypot(...d);
      const at = length ? Math.max(0, Math.min(length, d.reduce((n, v, i) => n + (p[i] - wall.from[i]) * v, 0) / length)) : 0;
      const point = wall.from.map((v, i) => v + d[i] * at / (length || 1));
      return { wall, at, point, length, distance: distance(p, point) };
    }).filter(row => row.distance <= 1).sort((a, b) => a.distance - b.distance)[0];
  }
  function save(operation, nameRoom = false) {
    busy = true; ++pending;
    // Keep every corner even when the person clicks faster than a round saves.
    const result = saving.then(() => gesture(async () => {
      const old = new Set(getPlan().buildings.find(b => b.id === operation.building).rooms.map(r => r.id));
      await op(operation);
      const added = getPlan().buildings.find(b => b.id === operation.building).rooms.filter(r => !old.has(r.id));
      if (nameRoom) for (const room of added) {
        const answer = window.promptInput('Name the new room', 'What is the new room called? Skip keeps Room.', { value: '', placeholder: 'Room' });
        const button = el('cc-input-cancel-btn'), label = button.textContent;
        button.textContent = 'Skip';
        let name;
        try { name = await answer; } finally { button.textContent = label; }
        if (name?.trim()) await op({ op: 'set', building: operation.building, id: room.id, field: 'name', value: name.trim() });
      }
    }));
    saving = result.catch(() => {});
    return result.finally(() => { busy = --pending > 0; });
  }
  async function choose(name) {
    if (!canEdit() || busy) return;
    cancel();
    if (!tools.floor()) { panel.message('Add a floor before drawing.'); return; }
    if (name === 'split-room' && !tools.selection().room) { panel.message('Select the room to split first.'); return; }
    if (name === 'add-anchor') {
      const kind = await window.promptChoice('Add anchor', 'What belongs here?',
        ['light', 'switch', 'outlet', 'fan', 'camera', 'sensor'].map(value => ({ value, label: value[0].toUpperCase() + value.slice(1) })));
      if (!kind || !canEdit()) return;
      anchorKind = kind;
    }
    tool = name; tools.setTool(name); el(`rail-${name}`).setAttribute('aria-pressed', 'true');
    note(({ 'draw-room': 'Drag a rectangle, or click corners and close on the first corner.',
      'draw-wall': 'Click wall corners. Escape or a double click ends the chain.',
      'split-room': 'Click two walls of this room to draw the split.',
      'add-anchor': 'Click a wall or a room surface. Lights and fans go on its ceiling.' })[name] || 'Click a wall. The opening starts 3 feet wide.');
  }
  function splitPoint(p) {
    const { building } = tools.floor(), room = building.rooms.find(r => r.id === tools.selection().room);
    if (!room) return null;
    const edges = room.polygon.map((from, i) => ({ from, to: room.polygon[(i + 1) % room.polygon.length] }));
    const boundary = wallAt(p, edges);
    return boundary && wallAt(boundary.point)?.point;
  }
  function click(p) {
    const { building, level } = tools.floor();
    if (tool === 'draw-room') {
      if (points.length >= 3 && distance(p, points[0]) <= 1) {
        const polygon = points; points = []; outline([]);
        save({ op: 'draw_room', building: building.id, level: level.id, polygon }, true).catch(report);
      } else { points.push(snap(p, points.at(-1))); outline(points); }
    } else if (tool === 'draw-wall' || tool === 'split-room') {
      const point = tool === 'split-room' ? splitPoint(p) : snap(p, points.at(-1));
      if (!point) { note('Click a wall of the focused room.'); return; }
      if (!points.length) { points = [point]; outline(points); return; }
      const from = points[0];
      if (distance(from, point) < 1) return;
      const splitting = tool === 'split-room', room = tools.selection().room;
      points = splitting ? [] : [point]; outline(points);
      save({ op: splitting ? 'split_room' : 'add_wall', building: building.id, level: level.id,
        ...(splitting ? { room } : {}), from, to: point }, true).then(() => { if (splitting) cancel(); }).catch(report);
    } else {
      const target = wallAt(p, building.walls.filter(w => w.level === level.id && w.kind !== 'separator'));
      if (tool === 'add-anchor') {
        let host;
        if (target) {
          const d = target.wall.to.map((v, i) => v - target.wall.from[i]);
          const side = d[0] * (p[1] - target.point[1]) - d[1] * (p[0] - target.point[0]) >= 0 ? 'left' : 'right';
          host = { wall: target.wall.id, side, at: target.at, z: Math.min(4, level.ceiling / 2) };
        } else {
          const room = building.rooms.find(r => r.level === level.id && r.state !== 'ghost' && contains(r.polygon, p));
          if (!room) { note('Click a wall or a room surface.'); return; }
          const xs = room.polygon.map(q => q[0]), ys = room.polygon.map(q => q[1]);
          host = { [['light', 'fan'].includes(anchorKind) ? 'ceiling' : 'floor']: room.id,
            u: (p[0] - Math.min(...xs)) / (Math.max(...xs) - Math.min(...xs)),
            v: (p[1] - Math.min(...ys)) / (Math.max(...ys) - Math.min(...ys)) };
        }
        save({ op: 'add_anchor', building: building.id, kind: anchorKind, host }).then(cancel).catch(report); return;
      }
      if (!target) { note('Click a solid wall.'); return; }
      const operation = { op: 'add_opening', building: building.id, wall: target.wall.id, kind: tool === 'add-door' ? 'door' : 'window',
        width: 3, at: Math.max(2, Math.min(target.length - 2, target.at)) };
      save(operation).then(cancel).catch(report);
    }
  }
  for (const name of drawingTools) {
    el(`rail-${name}`).disabled = false;
    el(`rail-${name}`).addEventListener('click', () => choose(name).catch(report), { signal });
  }
  el('draw-cancel').addEventListener('click', cancel, { signal });
  el('rail-delete').disabled = false;
  el('rail-delete').addEventListener('click', () => {
    if (!canEdit() || busy) return;
    const selection = tools.selection(); cancel();
    if (!selection.id) { panel.message('Select a piece to delete first.'); return; }
    save({ op: 'delete', building: selection.building, id: selection.id }).catch(report);
  }, { signal });
  el('rail-add-level').disabled = false;
  el('rail-add-level').addEventListener('click', async () => {
    if (!canEdit() || busy || !tools.floor()) return;
    cancel();
    const { building } = tools.floor();
    const name = await window.promptInput('Add floor', 'Name the new floor.', { value: `Floor ${building.levels.length + 1}` });
    if (!name?.trim() || !canEdit()) return;
    const highest = [...building.levels].sort((a, b) => b.elevation - a.elevation)[0];
    try { await save({ op: 'add_level', building: building.id, name: name.trim(),
      elevation: highest.elevation + highest.ceiling, ceiling: highest.ceiling }); } catch (error) { report(error); }
  }, { signal });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !tool || event.defaultPrevented
      || event.target.closest?.('input, textarea, select, [contenteditable="true"]')
      || document.querySelector('#cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden), #cc-confirm-modal:not(.hidden)')) return;
    event.preventDefault(); event.stopImmediatePropagation(); cancel();
  }, { capture: true, signal });
  canvas.addEventListener('dblclick', event => {
    if (!tool) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (tool === 'draw-wall') cancel();
  }, { capture: true, signal });
  signal.addEventListener('abort', release, { once: true });
  return {
    cancel, floorChanged: cancel,
    pointerDown(event) {
      if (!tool || !canEdit()) return false;
      if (busy && tool !== 'draw-wall') return true;
      const p = view.floorAt(event.clientX, event.clientY, tools.floor().key);
      if (!p) return true;
      onInteract?.();
      press = { id: event.pointerId, p, x: event.clientX, y: event.clientY, enabled: view.controls.enabled };
      view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); return true;
    },
    pointerMove(event) {
      if (!tool) return false;
      const p = view.floorAt(event.clientX, event.clientY, tools.floor().key); if (!p) return true;
      if (tool === 'draw-room' && press && !points.length && Math.hypot(event.clientX - press.x, event.clientY - press.y) >= 3) {
        const a = snap(press.p), b = snap(p);
        outline([a, [b[0], a[1]], b, [a[0], b[1]]]);
      } else if (points.length) outline([...points, snap(p, points.at(-1))]);
      return true;
    },
    pointerUp(event, cancelled) {
      if (!tool && !press) return false;
      if (!press) return true;
      const start = press, p = view.floorAt(event.clientX, event.clientY, tools.floor().key); release();
      if (cancelled || !p || busy && tool !== 'draw-wall') return true;
      if (tool === 'draw-room' && !points.length && Math.hypot(event.clientX - start.x, event.clientY - start.y) >= 3) {
        const a = snap(start.p), b = snap(p), { building, level } = tools.floor(); outline([]);
        if (Math.abs(a[0] - b[0]) >= 1 && Math.abs(a[1] - b[1]) >= 1)
          save({ op: 'draw_room', building: building.id, level: level.id,
            polygon: [a, [b[0], a[1]], b, [a[0], b[1]]] }, true).catch(report);
      } else click(p);
      return true;
    },
  };
}
