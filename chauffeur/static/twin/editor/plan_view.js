import { report } from './api.js';
import { snapPoint, snapAngle } from './snap.js';

export function createPlanView({ view, tools, edit, canEdit, signal, onInteract }) {
  let active = false, adding = null, first = null;
  const el = id => document.getElementById(id);
  const note = text => { el('plan-note').textContent = text; };
  function floorChanged() {
    if (!active || !tools.floor()) return;
    const { key, building, level } = tools.floor();
    const below = building.levels.filter(l => l.elevation < level.elevation).sort((a, b) => b.elevation - a.elevation)[0];
    view.setView(key); view.showLevels([key, ...(below ? [`${building.id}:${below.id}`] : [])], { faint: below ? [`${building.id}:${below.id}`] : [] });
    view.setPlanCamera(key); first = null;
  }
  function cancel() {
    adding = null; first = null;
    for (const id of ['wall', 'door', 'window']) el(`plan-add-${id}`).setAttribute('aria-pressed', 'false');
    note('Select a piece to change it, or add a wall, door or window.');
  }
  function leavePlan() {
    if (!active) return;
    active = false; cancel(); el('plan-tools').hidden = true; el('rail-plan').setAttribute('aria-pressed', 'false');
    view.setView(tools.floor()?.key || 'ext'); view.setCamera('orbit');
  }
  el('rail-plan').disabled = false;
  el('rail-plan').addEventListener('click', () => {
    onInteract?.();
    if (active) { leavePlan(); return; }
    if (!tools.floor()) return;
    active = true; el('rail-plan').setAttribute('aria-pressed', 'true'); el('plan-tools').hidden = false;
    cancel(); floorChanged();
  }, { signal });
  for (const kind of ['wall', 'door', 'window']) el(`plan-add-${kind}`).addEventListener('click', () => {
    if (!canEdit()) return;
    tools.setTool('select'); cancel(); adding = kind;
    el(`plan-add-${kind}`).setAttribute('aria-pressed', 'true');
    note(kind === 'wall' ? 'Tap where the wall starts, then where it ends.' : `Tap a wall where the ${kind} belongs. It starts 3 feet wide.`);
  }, { signal });
  el('plan-cancel').addEventListener('click', cancel, { signal });
  return {
    active: () => active, floorChanged, leavePlan, cancel,
    pointerDown(event) {
      if (!active || !adding || !canEdit()) return false;
      const { key, building, level } = tools.floor();
      const p = view.floorAt(event.clientX, event.clientY, key); if (!p) return true;
      const walls = building.walls.filter(w => w.level === level.id);
      if (adding === 'wall') {
        const point = snapPoint(p, walls);
        if (!first) { first = point; note('Now tap the other end. Walls line up with nearby walls and right angles.'); }
        else {
          const start = first, end = snapAngle(start, point); first = null;
          if (Math.hypot(end[0] - start[0], end[1] - start[1]) < .1) { note('Choose two different places for the wall ends.'); return true; }
          edit({ op: 'add_wall', building: building.id, level: level.id, from: start, to: end }).then(cancel).catch(report);
        }
      } else {
        const candidates = walls.map(w => {
          const dx = w.to[0] - w.from[0], dy = w.to[1] - w.from[1], length = Math.hypot(dx, dy);
          const at = length ? Math.max(0, Math.min(length, ((p[0] - w.from[0]) * dx + (p[1] - w.from[1]) * dy) / length)) : 0;
          return { wall: w, length, at, distance: Math.hypot(p[0] - w.from[0] - dx * at / length, p[1] - w.from[1] - dy * at / length) };
        }).filter(c => c.length >= 3 && c.distance < 2).sort((a, b) => a.distance - b.distance);
        const target = candidates[0];
        if (!target) { note('Tap a wall at least 3 feet long.'); return true; }
        edit({ op: 'add_opening', building: building.id, wall: target.wall.id, kind: adding, width: 3,
          at: Math.max(1.5, Math.min(target.length - 1.5, target.at)) }).then(cancel).catch(report);
      }
      return true;
    },
  };
}
