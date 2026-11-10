import { contains } from '../twin_generator.js';
import { feetInches, parseLength } from './cards.js';
import { report } from './api.js';

// All points and sizes are in screen pixels. A neighbour supplies a distance
// label; without one the label sits outside the selected wall. `avoid` is the
// ordered convex silhouette; bounds constrain the entire button to the canvas.
// `paths` are lines (two points each) a handle travels along while dragged:
// the selected wall's handle runs across the gap, so the gap label would sit
// on the very track the pointer follows. Labels keep the same 24px off them.
export function placeDimensionLabel({ wall: [a, b], neighbour = null, avoid = null, handles = [], paths = [], size, outside = 1, bounds = null }) {
  const width = size.width, height = Math.max(44, size.height);
  const dx = b[0] - a[0], dy = b[1] - a[1], length = Math.hypot(dx, dy);
  if (!length || !Number.isFinite(length + width + height) || width <= 0) return null;
  const axis = [dx / length, dy / length], normal = [-axis[1], axis[0]];
  const at = a.map((v, i) => v + (b[i] - v) / 4);
  let point;
  if (neighbour) {
    const [c, d] = neighbour, ex = d[0] - c[0], ey = d[1] - c[1];
    const denominator = normal[0] * ey - normal[1] * ex;
    if (Math.abs(denominator) < 1e-6) return null;
    const gap = ((c[0] - at[0]) * ey - (c[1] - at[1]) * ex) / denominator;
    point = at.map((v, i) => v + normal[i] * gap / 2);
  } else {
    const support = (Math.abs(normal[0]) * width + Math.abs(normal[1]) * height) / 2;
    point = at.map((v, i) => v + normal[i] * (outside < 0 ? -1 : 1) * (16 + support));
  }
  const polygon = avoid || [a.map((v, i) => (v + b[i]) / 2)];
  if (!polygon.length || ![...polygon, ...handles, ...paths.flat()].every(p => p.every(Number.isFinite))) return null;
  const dot = (p, n) => p[0] * n[0] + p[1] * n[1];
  // A track is an unbounded line; a long segment stands in for it.
  const tracks = paths.map(([p, q]) => {
    const run = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (run < 1e-6) return [p];
    const reach = 1e5 / run;
    return [p.map((v, i) => v - (q[i] - v) * reach), p.map((v, i) => v + (q[i] - v) * reach)];
  });
  // Separating axes turn collision with a convex wall quad (or a handle)
  // into one forbidden shift interval. Expand the whole box by 24px plus
  // one pixel for CSS rounding; vertices alone do not protect the face.
  const half = [width / 2 + 25, height / 2 + 25];
  function fit(origin) {
    let low = -Infinity, high = Infinity;
    if (bounds) for (let i = 0; i < 2; i++) {
      const start = (i ? bounds.top : bounds.left) + (i ? height : width) / 2;
      const end = (i ? bounds.bottom : bounds.right) - (i ? height : width) / 2;
      if (start > end) return null;
      if (Math.abs(axis[i]) < 1e-6) {
        if (origin[i] < start || origin[i] > end) return null;
      } else {
        const ends = [(start - origin[i]) / axis[i], (end - origin[i]) / axis[i]];
        low = Math.max(low, Math.min(...ends)); high = Math.min(high, Math.max(...ends));
      }
    }
    if (low > high) return null;
    const intervals = [];
    for (const shape of [polygon, ...handles.map(p => [p]), ...tracks]) {
      const axes = [[1, 0], [0, 1]];
      for (let i = 0; i < shape.length; i++) {
        const p = shape[i], q = shape[(i + 1) % shape.length];
        if (Math.hypot(q[0] - p[0], q[1] - p[1]) > 1e-6) axes.push([p[1] - q[1], q[0] - p[0]]);
      }
      let lo = -Infinity, hi = Infinity;
      for (const n of axes) {
        const values = shape.map(p => dot(p, n)), centre = dot(origin, n), speed = dot(axis, n);
        const support = Math.abs(n[0]) * half[0] + Math.abs(n[1]) * half[1];
        const start = Math.min(...values) - support - centre, end = Math.max(...values) + support - centre;
        if (Math.abs(speed) < 1e-6) {
          if (start >= -1e-7 || end <= 1e-7) { lo = Infinity; hi = -Infinity; break; }
        } else {
          lo = Math.max(lo, Math.min(start / speed, end / speed));
          hi = Math.min(hi, Math.max(start / speed, end / speed));
        }
      }
      if (lo <= hi) intervals.push([lo, hi]);
    }
    intervals.sort((x, y) => x[0] - y[0]);
    const merged = [];
    for (const interval of intervals) {
      const last = merged.at(-1);
      if (last && interval[0] <= last[1]) last[1] = Math.max(last[1], interval[1]);
      else merged.push([...interval]);
    }
    const nearest = Math.max(low, Math.min(high, 0));
    const blocked = merged.find(([lo, hi]) => lo < nearest && hi > nearest);
    const candidates = blocked ? blocked.filter(t => t >= low && t <= high) : [nearest];
    if (!candidates.length) return null;
    const shift = candidates.reduce((best, t) => Math.abs(t) < Math.abs(best) ? t : best);
    return origin.map((v, i) => v + axis[i] * shift);
  }
  const placed = fit(point);
  if (placed) return placed;
  // No along-wall shift fits on this side. Try beyond the opposite edge of
  // the silhouette; if that box cannot fit either, leave the wall clickable.
  const side = Math.sign(dot(point.map((v, i) => v - at[i]), normal)) || outside;
  const edges = polygon.map(p => dot(p.map((v, i) => v - at[i]), normal));
  const support = Math.abs(normal[0]) * half[0] + Math.abs(normal[1]) * half[1];
  const offset = side > 0 ? Math.min(...edges) - support : Math.max(...edges) + support;
  return fit(at.map((v, i) => v + normal[i] * offset));
}

// Labels share the work surface's buttons, accent and floating hint treatment.
export function createDimensions({ view, onCommit, canEdit, signal, getHandles = () => [] }) {
  const host = view.renderer3.domElement.parentElement;
  const layer = document.createElement('div'); layer.className = 'editor-dimensions'; host.append(layer);
  let context = null, rows = [], busy = false;
  const sizeObserver = new ResizeObserver(entries => {
    if (entries.some(entry => !entry.target.hidden)) position();
  });
  function position() {
    if (!context) return;
    const { building, piece } = context, key = `${building.id}:${piece.level}`;
    const bounds = view.renderer3.domElement.getBoundingClientRect();
    const a = view.screenOfFloor(...piece.from, key), b = view.screenOfFloor(...piece.to, key);
    const level = building.levels?.find(l => l.id === piece.level);
    const height = piece.height ?? level?.ceiling ?? 0;
    const topA = view.screenOfFloor(...piece.from, key, height), topB = view.screenOfFloor(...piece.to, key, height);
    const handleList = getHandles();
    const project = (h, step = [0, 0]) => {
      const handleLevel = h.level || piece.level;
      const elevation = building.levels?.find(l => l.id === handleLevel)?.elevation || 0;
      return view.screenOfFloor(h.at[0] + step[0], h.at[1] + step[1], `${h.building || building.id}:${handleLevel}`, (h.at[2] || 0) - elevation);
    };
    const handlePoints = handleList.map(h => project(h)).filter(Boolean);
    // The wall's own handle drags it along its normal: keep that track clear.
    const wallHandle = handleList.find(h => h.kind === 'wall' && h.id === piece.id);
    const length = Math.hypot(piece.to[0] - piece.from[0], piece.to[1] - piece.from[1]);
    const track = wallHandle && length && [project(wallHandle),
      project(wallHandle, [(piece.from[1] - piece.to[1]) / length, (piece.to[0] - piece.from[0]) / length])];
    const paths = track && track.every(Boolean) ? [track] : [];
    // Read every current box before moving any labels. Font/CSS changes can
    // resize a retained button without changing its distance text.
    for (const row of rows) row.node.hidden = false;
    const boxes = rows.map(({ node }) => {
      const rect = node.getBoundingClientRect();
      return { width: Math.max(rect.width, node.offsetWidth || 0), height: Math.max(44, rect.height, node.offsetHeight || 0) };
    });
    for (const [index, row] of rows.entries()) {
      const size = boxes[index];
      const c = row.neighbour && view.screenOfFloor(...row.neighbour.from, key);
      const d = row.neighbour && view.screenOfFloor(...row.neighbour.to, key);
      const away = row.away && view.screenOfFloor(...row.at, key);
      const middle = row.away && view.screenOfFloor(...row.away, key);
      const outside = a && b && away && middle
        ? Math.sign((away[0] - middle[0]) * (a[1] - b[1]) + (away[1] - middle[1]) * (b[0] - a[0])) : 1;
      const p = a && b && topA && topB && (!row.neighbour || c && d) ? placeDimensionLabel({
        wall: [a, b], neighbour: row.neighbour ? [c, d] : null, avoid: [a, b, topB, topA], handles: handlePoints, paths, size, outside, bounds,
      }) : null;
      row.node.hidden = !p;
      if (p) { row.node.style.left = `${p[0]}px`; row.node.style.top = `${p[1]}px`; }
    }
  }
  function clear() { context = null; rows.forEach(row => sizeObserver.unobserve?.(row.node)); rows = []; layer.replaceChildren(); }
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
    function label(value, at, name, operation, away = null, neighbour = null) {
      let row = rows[count++];
      if (!row) {
        const node = document.createElement('button'); node.type = 'button';
        row = { node }; rows.push(row); layer.append(node); sizeObserver.observe(node);
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
      Object.assign(row, { at, value, operation, away, neighbour });
      const text = feetInches(value), { node } = row;
      if (node.textContent !== text) { node.textContent = text; node.setAttribute('aria-label', `${name}: ${text}`); }
      node.dataset.dimension = name; node.disabled = !operation;
    }
    const outside = ctx.room && contains(ctx.room.polygon, centre.map((v, i) => v + normal[i] * .25)) ? -1 : 1;
    label(length, centre.map((v, i) => v + normal[i] * outside * 1.5), 'Wall length', value => ({
      op: 'move_joint', building: building.id, joint: piece.joints[1], to: piece.from.map((v, i) => v + axis[i] * value),
    }), centre);
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
      label(value, piece.from.map((v, i) => v + (piece.to[i] - v) / 4 + normal[i] * distance / 2), 'Distance to wall', desired => ({
        op: 'move_wall', building: building.id, wall: piece.id, by: normal.map(v => v * sign * (value - desired)),
      }), null, neighbour.wall);
    }
    while (rows.length > count) { const row = rows.pop(); sizeObserver.unobserve?.(row.node); row.node.remove(); }
    position();
  }
  view.controls.addEventListener('change', position);
  host.addEventListener('twinrebuilt', position, { signal });
  window.addEventListener('resize', position, { signal });
  signal.addEventListener('abort', () => { sizeObserver.disconnect(); view.controls.removeEventListener('change', position); layer.remove(); }, { once: true });
  return { show, clear, position };
}
