import { snapTo } from './snap.js';
import { report } from './api.js';
import { heightAt } from '../twin_roof.js';
import * as THREE from 'three';
import { PICK_LAYER } from '../twin_generator.js';

// Edge directions are shared by placement, handles and the operation's outward by.
export function roofEdge(roof, edge) {
  const a = roof.area[edge], b = roof.area[(edge + 1) % roof.area.length];
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const axis = b.map((v, i) => (v - a[i]) / length);
  const signed = roof.area.reduce((n, p, i) => {
    const q = roof.area[(i + 1) % roof.area.length]; return n + p[0] * q[1] - p[1] * q[0];
  }, 0);
  const sign = signed > 0 ? 1 : -1;
  return { a, b, length, axis, normal: [sign * axis[1], -sign * axis[0]] };
}

export function createRoofTools({ view, tools, getPlan, op, canEdit, panel, signal, onInteract, cancelDrawing }) {
  const el = id => document.getElementById(id), canvas = view.renderer3.domElement;
  let mode = null, points = [], press = null, busy = false;
  const listen = (node, type, fn, options = {}) => node.addEventListener(type, fn, { ...options, signal });
  const caster = new THREE.Raycaster();
  function roofPoint(event, building, pieceId) {
    const rect = canvas.getBoundingClientRect(), position = building.position || [0, 0];
    view.camera.updateMatrixWorld(true); view.scene.updateMatrixWorld(true); caster.layers.set(PICK_LAYER);
    caster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2), view.camera);
    const point = caster.intersectObjects(view.scene.children, true).find(hit => hit.object.userData.kind === 'roof'
      && hit.object.userData.buildingId === building.id && hit.object.userData.pieceId === pieceId)?.point;
    if (!point) return null;
    const x = point.x / .3048 - position[0], y = -point.z / .3048 - position[1], a = -(building.rotation || 0) * Math.PI / 180;
    return [Math.cos(a) * x - Math.sin(a) * y, Math.sin(a) * x + Math.cos(a) * y];
  }
  function outline(polygon) {
    const screen = polygon.map(p => view.screenOfFloor(...p, tools.floor()?.key)).filter(Boolean);
    el('editor-drag-outline').setAttribute('points', screen.map(p => p.join(',')).join(' '));
  }
  function release() {
    if (!press) return;
    const previous = press; press = null; view.controls.enabled = previous.enabled;
    if (canvas.hasPointerCapture(previous.id)) canvas.releasePointerCapture(previous.id);
  }
  function cancel(resetTool = true) {
    const wasActive = !!mode;
    release(); mode = null; points = []; outline([]);
    el('roof-tools').hidden = true; el('rail-roof').setAttribute('aria-pressed', 'false');
    if (wasActive && resetTool) tools.setTool('select');
  }
  function choose(next) {
    if (!canEdit() || busy) return;
    cancelDrawing?.(); cancel(); onInteract?.();
    if (!tools.floor()) { panel.message('Add a floor before adding a roof.'); return; }
    mode = next; tools.setTool('roof'); el('rail-roof').setAttribute('aria-pressed', 'true');
    el('roof-tools').hidden = false; el('roof-choices').hidden = next !== 'choices';
    el('roof-note').textContent = next === 'draw' ? 'Click roof corners and close on the first corner.'
      : next === 'dormer' ? 'Click a sloping roof surface to place a dormer.'
        : 'Roof over the selected rooms, or draw a roof area.';
  }
  async function save(operation) {
    if (!canEdit() || busy) return;
    busy = true;
    const list = operation.op === 'add_dormer' ? 'dormers' : 'roofs';
    const before = new Set(getPlan().buildings.find(b => b.id === operation.building)[list]?.map(p => p.id));
    // Select the new piece as soon as the saved plan arrives, before the
    // scene rebuild finishes, so a later click is never overridden.
    let done = false;
    const saved = () => {
      if (done) return; done = true; cancel();
      const added = getPlan().buildings.find(b => b.id === operation.building)[list]?.find(p => !before.has(p.id));
      if (added) tools.select({ pieceId: added.id, buildingId: operation.building });
    };
    try { await op(operation, saved); saved(); }
    finally { busy = false; }
  }
  function snap(p) {
    const { building, level, key } = tools.floor();
    const screen = view.screenOfFloor(...p, key), near = screen && view.floorAt(screen[0] + 12, screen[1], key);
    const reach = Math.max(.25, Math.min(1, near ? Math.hypot(near[0] - p[0], near[1] - p[1]) : 1));
    return snapTo(p, { reach, from: points.at(-1), joints: building.joints?.filter(j => j.level === level.id),
      walls: building.walls.filter(w => w.level === level.id) }).point;
  }
  function dormerAt(event) {
    const picked = view.pick(event.clientX, event.clientY), bid = picked?.building ?? picked?.buildingId;
    const building = getPlan()?.buildings.find(b => b.id === bid), pid = picked?.id ?? picked?.pieceId;
    const section = building?.roof?.sections.find(s => s.id === pid && !s.dormer_of);
    const roof = building?.roofs?.find(r => r.id === (section?.roof || pid));
    if (!roof || !section || picked.kind !== 'roof') return null;
    // Use the renderer's roof pick mesh, including oblique views and valleys.
    const p = roofPoint(event, building, pid); if (!p) return null;
    const edges = roof.edges.flatMap((edge, index) => {
      if (edge.setting !== 'sloped') return [];
      const frame = roofEdge(roof, index), at = Math.max(0, Math.min(frame.length,
        p.reduce((n, v, i) => n + (v - frame.a[i]) * frame.axis[i], 0)));
      // The lowest eave plane owns the surface. Distance alone would choose
      // the wrong slope when different edge pitches move the ridge.
      const height = roof.plate - p.reduce((n, v, i) => n + (v - frame.a[i]) * frame.normal[i], 0) * (edge.pitch ?? roof.pitch ?? 6) / 12;
      const distance = Math.abs(height - heightAt([section], ...p));
      return [{ index, at, distance }];
    }).sort((a, b) => a.distance - b.distance);
    return edges.length ? { op: 'add_dormer', building: bid, roof: roof.id, edge: edges[0].index,
      at: edges[0].at, width: 4, pitch: 8 } : null;
  }
  listen(el('rail-roof'), 'click', () => choose('choices')); el('rail-roof').disabled = false;
  listen(el('roof-over'), 'click', () => {
    if (!canEdit() || busy) return;
    const state = tools.selection(), target = getPlan()?.buildings.find(b => b.id === state.building) || tools.floor()?.building;
    if (target) save({ op: 'roof_over', building: target.id, rooms: tools.selectedRooms() || null }).catch(report);
  });
  listen(el('roof-draw'), 'click', () => choose('draw'));
  listen(el('roof-dormer'), 'click', () => choose('dormer'));
  listen(el('roof-cancel'), 'click', cancel);
  for (const button of document.querySelectorAll('#editor-rail button:not(#rail-roof)')) listen(button, 'click', () => cancel(false));
  listen(document, 'keydown', event => {
    if (event.key !== 'Escape' || !mode || event.defaultPrevented
      || event.target.closest?.('input, textarea, select, [contenteditable="true"]')) return;
    event.preventDefault(); event.stopImmediatePropagation(); cancel();
  }, { capture: true });
  signal.addEventListener('abort', release, { once: true });
  return {
    cancel, floorChanged: cancel, addDormer: () => choose('dormer'),
    pointerDown(event) {
      if (!mode || mode === 'choices' || !canEdit()) return false;
      if (busy) return true;
      onInteract?.(); press = { id: event.pointerId, x: event.clientX, y: event.clientY, enabled: view.controls.enabled };
      view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); return true;
    },
    pointerMove(event) {
      if (!mode || mode === 'choices') return false;
      const p = mode === 'draw' && view.floorAt(event.clientX, event.clientY, tools.floor().key);
      if (p && points.length) outline([...points, snap(p)]);
      return true;
    },
    pointerUp(event, cancelled) {
      if (!press) return false;
      const start = press; release();
      if (cancelled || busy || Math.hypot(event.clientX - start.x, event.clientY - start.y) >= 3) return true;
      if (mode === 'dormer') {
        const operation = dormerAt(event);
        if (operation) save(operation).catch(report);
        else el('roof-note').textContent = 'Click a sloping roof surface.';
      } else if (mode === 'draw') {
        const p = view.floorAt(event.clientX, event.clientY, tools.floor().key); if (!p) return true;
        const point = snap(p);
        if (points.length >= 3 && Math.hypot(...point.map((v, i) => v - points[0][i])) < .25) {
          const { building, level } = tools.floor();
          save({ op: 'draw_roof', building: building.id, level: level.id, area: points }).catch(report);
        } else { points.push(point); outline(points); }
      }
      return true;
    },
  };
}
