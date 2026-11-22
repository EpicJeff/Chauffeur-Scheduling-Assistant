import { snapTo } from './snap.js';
import { feetInches } from './cards.js';
import { hostPoint } from '../twin_hosts.js';
import { DRAG_THRESHOLD_PX } from './picking.js';
import * as THREE from 'three';
import { groundAt } from '../twin_ground.js';

// Ephemeral building-local feet, projected with the same canvas rect as handles.
// A camera drag remains navigation; only two clicks make the dimension.
export function createMeasure({ view, getPlan, layer }) {
  const canvas = view.renderer3.domElement;
  let armed = false, press = null, pinching = false, points = [], key = null, previousStatus = '', previousCursor = '';
  const status = () => document.getElementById('editor-status');
  const ray = new THREE.Raycaster();
  function ground(event) {
    const r = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    ray.setFromCamera(new THREE.Vector2((event.clientX - r.left) / r.width * 2 - 1, 1 - (event.clientY - r.top) / r.height * 2), view.camera);
    const p = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), new THREE.Vector3());
    if (!p) return null;
    for (let i = 0; i < 3; i++) ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -groundAt(getPlan(), p.x / .3048, -p.z / .3048) * .3048), p);
    return [p.x / .3048, -p.z / .3048];
  }
  function project(p) {
    if (key !== 'ext') return view.screenOfFloor(...p, key);
    view.camera.updateMatrixWorld(true);
    const q = new THREE.Vector3(p[0] * .3048, groundAt(getPlan(), ...p) * .3048, -p[1] * .3048).project(view.camera);
    if (q.z < -1 || q.z > 1) return null;
    const r = canvas.getBoundingClientRect(); return [r.left + (q.x + 1) * r.width / 2, r.top + (1 - q.y) * r.height / 2];
  }
  const note = () => { if (status()) status().textContent = points.length === 2
    ? `${feetInches(Math.hypot(...points[1].map((v, i) => v - points[0][i])))}. Esc clears the measurement.`
    : `Click ${points.length ? 'the second' : 'the first'} point to measure. Shift turns snapping off. Esc cancels.`; };
  function draw() {
    layer.replaceChildren();
    if (points.length !== 2) return;
    const projected = points.map(project);
    if (projected.some(p => !p)) return;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'editor-measure-line'); svg.setAttribute('aria-hidden', 'true');
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    for (const [i, p] of projected.entries()) for (const [j, axis] of ['x', 'y'].entries()) line.setAttribute(`${axis}${i + 1}`, String(p[j]));
    svg.append(line);
    const label = document.createElement('output'); label.className = 'editor-measure-label';
    label.textContent = feetInches(Math.hypot(...points[1].map((v, i) => v - points[0][i])));
    label.style.left = `${(projected[0][0] + projected[1][0]) / 2}px`;
    label.style.top = `${(projected[0][1] + projected[1][1]) / 2}px`;
    layer.append(svg, label);
  }
  function point(event) {
    const plan = getPlan();
    const current = points.length ? key : view.state.view;
    const building = plan?.buildings?.find(b => b.levels.some(l => `${b.id}:${l.id}` === current));
    const level = building?.levels.find(l => `${building.id}:${l.id}` === current);
    const floorKey = level ? current : 'ext';
    const p = floorKey === 'ext' ? ground(event) : view.floorAt(event.clientX, event.clientY, floorKey);
    if (!p) return null;
    if (!points.length) key = floorKey;
    if (event.shiftKey) return p;
    const screen = project(p), nearby = screen && (key === 'ext' ? ground({ clientX: screen[0] + 12, clientY: screen[1] }) : view.floorAt(screen[0] + 12, screen[1], key));
    const reach = Math.max(.25, Math.min(1, nearby ? Math.hypot(...nearby.map((v, i) => v - p[i])) : 1));
    const below = building?.levels.filter(l => l.elevation < level.elevation).sort((a, b) => b.elevation - a.elevation)[0];
    const anchors = (building?.anchors || []).flatMap(a => { try { return [hostPoint(building, a.host).slice(0, 2)]; } catch { return []; } });
    const walls = building?.walls || [];
    const snapped = snapTo(p, { from: points[0], reach, anchors,
      joints: (building?.joints || []).filter(j => j.level === level?.id),
      walls: walls.filter(w => w.level === level?.id), below: below ? walls.filter(w => w.level === below.id) : [] });
    if (snapped.target === 'right_angle') {
      const axis = snapped.point[0] === points[0][0] ? 1 : 0;
      snapped.point[axis] = Math.round(snapped.point[axis] * 12) / 12;
    } else if (['line', 'extension', 'below'].includes(snapped.target)) {
      const wall = walls.filter(w => w.level === (snapped.target === 'below' ? below?.id : level?.id)).find(w => {
        const d = w.to.map((v, i) => v - w.from[i]);
        return Math.abs(d[0] * (snapped.point[1] - w.from[1]) - d[1] * (snapped.point[0] - w.from[0])) < 1e-8;
      });
      const axis = wall && (Math.abs(wall.to[0] - wall.from[0]) < 1e-8 ? 1 : Math.abs(wall.to[1] - wall.from[1]) < 1e-8 ? 0 : null);
      if (axis != null) snapped.point[axis] = Math.round(snapped.point[axis] * 12) / 12;
    }
    return snapped.point;
  }
  function down(event) {
    if (view.editorCamera && event.pointerType !== 'touch' && event.altKey) return;
    if (!armed || event.button !== 0 || points.length === 2) return;
    if (press && press.id !== event.pointerId) { press = null; pinching = true; return; }
    if (!pinching) press = { x: event.clientX, y: event.clientY, id: event.pointerId, moved: false };
  }
  function move(event) {
    if (press?.id === event.pointerId && Math.hypot(event.clientX - press.x, event.clientY - press.y) >= DRAG_THRESHOLD_PX) press.moved = true;
  }
  function up(event) {
    if (pinching) { pinching = false; press = null; return; }
    const start = press; press = null;
    if (!armed || !start || start.moved || start.id !== event.pointerId || Math.hypot(event.clientX - start.x, event.clientY - start.y) >= DRAG_THRESHOLD_PX) return;
    const p = point(event); if (!p) return;
    points.push(p); draw(); note();
  }
  function escape(event) {
    if (!armed || event.key !== 'Escape' || event.defaultPrevented
      || event.target.closest?.('input, textarea, select, [contenteditable="true"]')
      || document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden), dialog[open]')) return;
    disarm(); event.preventDefault(); event.stopImmediatePropagation();
  }
  function disarm() {
    if (!armed) return;
    armed = false; press = null; pinching = false; points = []; key = null; layer.replaceChildren();
    canvas.style.cursor = previousCursor;
    if (status()) status().textContent = previousStatus;
    document.getElementById('rail-measure')?.setAttribute('aria-pressed', 'false');
    canvas.removeEventListener('pointerdown', down, true); canvas.removeEventListener('pointerup', up, true);
    canvas.removeEventListener('pointermove', move, true);
    canvas.removeEventListener('pointercancel', cancelPress, true);
    document.removeEventListener('keydown', escape, true); view.controls.removeEventListener('change', draw);
    window.removeEventListener('resize', draw); canvas.parentElement?.removeEventListener('twinrebuilt', draw);
  }
  const cancelPress = () => { press = null; };
  function arm() {
    disarm(); armed = true; previousStatus = status()?.textContent || ''; previousCursor = canvas.style.cursor;
    canvas.style.cursor = 'crosshair'; document.getElementById('rail-measure')?.setAttribute('aria-pressed', 'true'); note();
    canvas.addEventListener('pointerdown', down, true); canvas.addEventListener('pointerup', up, true);
    canvas.addEventListener('pointermove', move, true);
    canvas.addEventListener('pointercancel', cancelPress, true);
    document.addEventListener('keydown', escape, true); view.controls.addEventListener('change', draw);
    window.addEventListener('resize', draw); canvas.parentElement?.addEventListener('twinrebuilt', draw);
  }
  return { arm, disarm, active: () => armed };
}
