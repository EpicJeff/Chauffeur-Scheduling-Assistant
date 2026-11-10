import { feetInches, parseLength } from './cards.js';
import { report } from './api.js';

// Labels share the work surface's buttons, accent and floating hint treatment.
export function createDimensions({ view, onCommit, canEdit, signal }) {
  const host = view.renderer3.domElement.parentElement;
  const layer = document.createElement('div'); layer.className = 'editor-dimensions'; host.append(layer);
  let context = null, rows = [], busy = false;
  function position() {
    if (!context) return;
    const { building, piece } = context, key = `${building.id}:${piece.level}`;
    const bounds = view.renderer3.domElement.getBoundingClientRect();
    for (const row of rows) {
      const p = view.screenOfFloor(...row.at, key);
      row.node.hidden = !p || p[0] < bounds.left || p[0] > bounds.right || p[1] < bounds.top || p[1] > bounds.bottom;
      if (p) { row.node.style.left = `${p[0]}px`; row.node.style.top = `${p[1]}px`; }
    }
  }
  function clear() { context = null; rows = []; layer.replaceChildren(); }
  function show(ctx) {
    const building = ctx?.building, piece = ctx?.piece;
    if (!building || !piece?.from || !canEdit()) { clear(); return; }
    if (context?.building.id !== building.id || context?.piece.id !== piece.id) clear();
    context = ctx;
    const dx = piece.to[0] - piece.from[0], dy = piece.to[1] - piece.from[1], length = Math.hypot(dx, dy);
    if (!length) { clear(); return; }
    let count = 0;
    const axis = [dx / length, dy / length], normal = [-axis[1], axis[0]];
    const centre = piece.from.map((v, i) => (v + piece.to[i]) / 2);
    function label(value, at, name, operation) {
      let row = rows[count++];
      if (!row) {
        const node = document.createElement('button'); node.type = 'button';
        row = { node }; rows.push(row); layer.append(node);
        node.addEventListener('click', async () => {
          if (busy || !canEdit()) return;
          busy = true;
          try {
            const text = await window.promptInput('Set distance', 'Enter feet and inches.',
              { value: feetInches(row.value), placeholder: feetInches(row.value), okText: 'Apply' });
            if (text === null || !canEdit()) return;
            const desired = parseLength(text);
            if (desired <= 0) throw new Error('Enter a distance greater than zero.');
            if (Math.abs(desired - row.value) > 1e-6) await onCommit(row.operation(desired));
          } catch (error) { report(error); }
          finally { busy = false; }
        }, { signal });
      }
      Object.assign(row, { at, value, operation });
      const text = feetInches(value), { node } = row;
      if (node.textContent !== text) { node.textContent = text; node.setAttribute('aria-label', `${name}: ${text}`); }
      node.dataset.dimension = name; node.disabled = !operation;
    }
    label(length, centre.map((v, i) => v + normal[i] * .7), 'Wall length', value => ({
      op: 'move_joint', building: building.id, joint: piece.joints[1], to: piece.from.map((v, i) => v + axis[i] * value),
    }));
    const neighbours = [null, null];
    for (const wall of building.walls) {
      if (wall.id === piece.id || wall.level !== piece.level || wall.kind === 'separator' || wall.state === 'ghost') continue;
      const d = wall.to.map((v, i) => v - wall.from[i]), size = Math.hypot(...d);
      if (!size || Math.abs((d[0] * axis[1] - d[1] * axis[0]) / size) > .01) continue;
      const along = wall.from.map((v, i) => (centre[i] - v) * axis[i]).reduce((a, b) => a + b, 0);
      const end = d[0] * axis[0] + d[1] * axis[1];
      if (along < Math.min(0, end) - .01 || along > Math.max(0, end) + .01) continue;
      const distance = wall.from.map((v, i) => (v - centre[i]) * normal[i]).reduce((a, b) => a + b, 0);
      if (Math.abs(distance) < .01) continue;
      const side = distance > 0 ? 1 : 0;
      if (!neighbours[side] || Math.abs(distance) < Math.abs(neighbours[side].distance)) neighbours[side] = { wall, distance };
    }
    for (const neighbour of neighbours.filter(Boolean)) {
      const { distance } = neighbour, value = Math.abs(distance), sign = Math.sign(distance);
      label(value, centre.map((v, i) => v + normal[i] * distance / 2), 'Distance to wall', desired => ({
        op: 'move_wall', building: building.id, wall: piece.id, by: normal.map(v => v * sign * (value - desired)),
      }));
    }
    while (rows.length > count) rows.pop().node.remove();
    position();
  }
  view.controls.addEventListener('change', position);
  host.addEventListener('twinrebuilt', position, { signal });
  window.addEventListener('resize', position, { signal });
  signal.addEventListener('abort', () => { view.controls.removeEventListener('change', position); layer.remove(); }, { once: true });
  return { show, clear, position };
}
