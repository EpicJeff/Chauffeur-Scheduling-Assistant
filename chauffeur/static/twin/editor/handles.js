import { contains } from '../twin_generator.js';
import * as THREE from 'three';
import { hostPoint } from '../twin_hosts.js';
import { groundAt } from '../twin_ground.js';

const FT = .3048;
const inch = value => Math.round(value * 12) / 12;
const basis = wall => {
  const d = wall.to.map((v, i) => v - wall.from[i]), length = Math.hypot(...d);
  return { length, axis: d.map(v => v / length), normal: [-d[1] / length, d[0] / length, 0] };
};

// Screen affordances and hit testing share the same model points. Structural
// previews stay in drag.js; the server alone decides whether a release fits.
export function createHandles({ view, getPlan, getSelection, canEdit, drag, onCommit, onPreview, signal }) {
  const canvas = view.renderer3.domElement, host = canvas.parentElement;
  const layer = document.createElement('div'); layer.className = 'editor-handles'; host.append(layer);
  const raycaster = new THREE.Raycaster();
  let rows = [], gesture = null, preview = null, lastFrameMs = null;
  const plan = () => preview || getPlan();
  function world(building, point) {
    const a = (building.rotation || 0) * Math.PI / 180, [x, y, z] = point, p = building.position || [0, 0];
    return new THREE.Vector3((Math.cos(a) * x - Math.sin(a) * y + p[0]) * FT,
      (z + (building.base || 0) + groundAt(plan(), ...p)) * FT,
      -(Math.sin(a) * x + Math.cos(a) * y + p[1]) * FT);
  }
  function local(building, point) {
    const a = -(building.rotation || 0) * Math.PI / 180, p = building.position || [0, 0];
    const x = point.x / FT - p[0], y = -point.z / FT - p[1];
    return new THREE.Vector3(Math.cos(a) * x - Math.sin(a) * y, Math.sin(a) * x + Math.cos(a) * y,
      point.y / FT - (building.base || 0) - groundAt(plan(), ...p));
  }
  function ray(event, building) {
    const rect = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2), view.camera);
    const origin = local(building, raycaster.ray.origin);
    return new THREE.Ray(origin, local(building, raycaster.ray.origin.clone().add(raycaster.ray.direction)).sub(origin).normalize());
  }
  function onPlane(event, building, at, normal) {
    return ray(event, building).intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(
      new THREE.Vector3(...normal), new THREE.Vector3(...at)), new THREE.Vector3())?.toArray();
  }
  function project(building, at) {
    view.camera.updateMatrixWorld(true);
    const p = world(building, at).project(view.camera), rect = canvas.getBoundingClientRect();
    if (p.z < -1 || p.z > 1) return null;
    const x = rect.left + (p.x + 1) * rect.width / 2, y = rect.top + (1 - p.y) * rect.height / 2;
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom ? [x, y] : null;
  }
  function descriptors() {
    if (!canEdit()) return [];
    const selected = getSelection(), building = plan()?.buildings.find(b => b.id === selected.building);
    if (!building) return [];
    const result = [], add = (kind, id, at, level) => {
      if (view.groups?.levels[`${building.id}:${level}`]?.visible === false) return;
      result.push({ kind, id, at, building: building.id, level });
    };
    const room = building.rooms.find(r => r.id === selected.room || selected.kind === 'room' && r.id === selected.id);
    if (room && room.state !== 'ghost') {
      const z = building.levels.find(l => l.id === room.level)?.elevation || 0;
      for (const id of room.joints || []) {
        const joint = building.joints.find(j => j.id === id);
        if (joint) add('joint', id, [...joint.at, z], room.level);
      }
      let centre = [0, 1].map(i => room.polygon.reduce((n, p) => n + p[i], 0) / room.polygon.length);
      if (!contains(room.polygon, centre)) centre = room.polygon[0].map((v, i) => v * .99 + centre[i] * .01);
      add('room', room.id, [...centre, z], room.level);
    }
    const wall = building.walls.find(w => selected.kind === 'wall' && w.id === selected.id);
    if (wall && wall.state !== 'ghost') add('wall', wall.id, [...wall.from.map((v, i) => (v + wall.to[i]) / 2),
      building.levels.find(l => l.id === wall.level)?.elevation || 0], wall.level);
    const opening = building.openings.find(o => selected.kind === 'opening' && o.id === selected.id);
    if (opening && opening.state !== 'ghost') {
      const wall = building.walls.find(w => w.id === opening.wall);
      if (wall) {
        const { axis } = basis(wall), elevation = building.levels.find(l => l.id === wall.level)?.elevation || 0;
        const addOpening = (kind, at, height) => add(kind, opening.id,
          [...wall.from.map((v, i) => v + axis[i] * at), elevation + height], wall.level);
        const middle = (opening.sill + opening.head) / 2;
        addOpening('opening_middle', opening.at, middle);
        addOpening('opening_edge_left', opening.at - opening.width / 2, middle);
        addOpening('opening_edge_right', opening.at + opening.width / 2, middle);
        addOpening('opening_edge_top', opening.at, opening.head);
        addOpening('opening_edge_bottom', opening.at, opening.sill);
      }
    }
    const hosted = ['anchors', 'items'].flatMap(list => building[list] || []).find(p => p.id === selected.id);
    if (hosted && hosted.state !== 'ghost') {
      try {
        const surface = building.walls.find(w => w.id === hosted.host.wall)
          || building.rooms.find(r => [hosted.host.floor, hosted.host.ceiling].includes(r.id))
          || building.roofs?.find(r => r.id === hosted.host.roof);
        add('hosted', hosted.id, hostPoint(building, hosted.host, hosted.offset || 0), surface?.level || selected.level);
      } catch { /* Lost hosts are represented by their existing flags. */ }
    }
    return result;
  }
  function refresh() {
    const handles = descriptors(), building = plan()?.buildings.find(b => b.id === getSelection().building);
    let count = 0;
    for (const handle of handles) {
      const pixel = project(building, handle.at); if (!pixel) continue;
      let row = rows[count++];
      if (!row) {
        const node = document.createElement('span'); layer.append(node); row = { node }; rows.push(row);
      }
      Object.assign(row, { handle, pixel });
      row.node.className = `editor-handle editor-handle-${handle.kind}`;
      row.node.style.left = `${pixel[0]}px`; row.node.style.top = `${pixel[1]}px`;
      row.node.setAttribute('aria-hidden', 'true');
    }
    while (rows.length > count) rows.pop().node.remove();
  }
  function hit(event) {
    refresh();
    const close = rows.filter(r => Math.hypot(r.pixel[0] - event.clientX, r.pixel[1] - event.clientY) <= 10)
      .sort((a, b) => (a.handle.kind === 'joint' ? -1 : 0) - (b.handle.kind === 'joint' ? -1 : 0)
        || Math.hypot(a.pixel[0] - event.clientX, a.pixel[1] - event.clientY) - Math.hypot(b.pixel[0] - event.clientX, b.pixel[1] - event.clientY));
    if (close.length) return close[0].handle;
    const all = descriptors(), selected = getSelection(), building = plan()?.buildings.find(b => b.id === selected.building);
    const wallHandle = all.find(h => h.kind === 'wall');
    if (wallHandle) {
      const wall = building.walls.find(w => w.id === wallHandle.id), a = project(building, [...wall.from, wallHandle.at[2]]), b = project(building, [...wall.to, wallHandle.at[2]]);
      if (a && b) {
        const d = b.map((v, i) => v - a[i]), length2 = d[0] ** 2 + d[1] ** 2;
        const t = Math.max(0, Math.min(1, ((event.clientX - a[0]) * d[0] + (event.clientY - a[1]) * d[1]) / length2));
        if (Math.hypot(event.clientX - a[0] - t * d[0], event.clientY - a[1] - t * d[1]) <= 10) return wallHandle;
      }
      const picked = view.pick(event.clientX, event.clientY);
      if (picked?.id === wallHandle.id && picked.building === building.id) return wallHandle;
    }
    const roomHandle = all.find(h => h.kind === 'room');
    if (roomHandle) {
      const picked = view.pick(event.clientX, event.clientY);
      if (picked?.kind === 'room' && picked.id === roomHandle.id && picked.building === building.id) return roomHandle;
    }
    return null;
  }
  function begin(event) {
    if (gesture) return false;
    const handle = hit(event); if (!handle) return false;
    const source = getPlan(), building = source.buildings.find(b => b.id === handle.building);
    if (['wall', 'joint', 'room'].includes(handle.kind)) {
      lastFrameMs = null;
      const start = view.floorAt(event.clientX, event.clientY, `${building.id}:${handle.level}`);
      if (!drag.begin({ ...getSelection(), ...handle }, start)) return false;
      gesture = { handle, source, building }; return true;
    }
    const list = handle.kind === 'hosted' ? ['anchors', 'items'].find(list => building[list]?.some(p => p.id === handle.id)) : 'openings';
    const piece = building[list].find(p => p.id === handle.id), wall = building.walls.find(w => w.id === (piece.wall || piece.host?.wall));
    const normal = wall ? basis(wall).normal : [0, 0, 1];
    const start = onPlane(event, building, handle.at, normal); if (!start) return false;
    gesture = { handle, source, building, piece, list, wall, normal, start, operation: null };
    return true;
  }
  function wallHost(event, g) {
    const r = ray(event, g.building), old = g.piece.host, current = g.building.walls.find(w => w.id === (g.operation?.host?.wall || old.wall));
    let best = null;
    for (const wall of g.building.walls) {
      if (wall.level !== current.level || wall.state === 'ghost' || wall.kind === 'separator'
        || wall.id !== current.id && !wall.joints.some(id => current.joints.includes(id))) continue;
      const { axis, normal, length } = basis(wall);
      for (const side of ['left', 'right']) {
        const sign = side === 'left' ? 1 : -1, n = new THREE.Vector3(...normal).multiplyScalar(sign);
        if (r.direction.dot(n) >= -1e-6) continue;
        const distance = (wall.thickness || 0) / 2 + (g.piece.offset || 0);
        const at = [...wall.from.map((v, i) => v + normal[i] * sign * distance), 0];
        const point = r.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(n, new THREE.Vector3(...at)), new THREE.Vector3());
        if (!point) continue;
        const along = (point.x - wall.from[0]) * axis[0] + (point.y - wall.from[1]) * axis[1];
        const level = g.building.levels.find(l => l.id === wall.level), z = point.z - level.elevation;
        if (along < 0 || along > length || z < 0 || z > level.ceiling) continue;
        const depth = point.distanceTo(r.origin);
        if (!best || depth < best.depth) best = { depth, host: { wall: wall.id, side, at: inch(along), z: inch(z) } };
      }
    }
    return best?.host;
  }
  function update(event) {
    if (!gesture) return;
    const started = performance.now(), g = gesture, { handle, building, piece } = g;
    if (['wall', 'joint', 'room'].includes(handle.kind)) {
      drag.update(view.floorAt(event.clientX, event.clientY, `${building.id}:${handle.level}`)); return;
    }
    const point = onPlane(event, building, handle.at, g.normal); if (!point) return;
    const operation = { op: handle.kind.startsWith('opening_edge') ? 'resize_opening' : 'move_hosted', building: building.id, id: piece.id };
    if (handle.kind.startsWith('opening')) {
      const { axis } = basis(g.wall), along = inch((point[0] - g.start[0]) * axis[0] + (point[1] - g.start[1]) * axis[1]);
      const up = inch(point[2] - g.start[2]);
      if (handle.kind === 'opening_middle') operation.at = piece.at + along;
      else if (handle.kind === 'opening_edge_left') { operation.width = piece.width - along; operation.at = piece.at + along / 2; }
      else if (handle.kind === 'opening_edge_right') { operation.width = piece.width + along; operation.at = piece.at + along / 2; }
      else if (handle.kind === 'opening_edge_top') operation.head = piece.head + up;
      else operation.sill = piece.sill + up;
    } else if (piece.host.wall) {
      const host = wallHost(event, g); if (!host) return;
      operation.host = host;
    } else if (piece.host.roof) {
      const roof = building.roofs?.find(r => r.id === piece.host.roof), edge = piece.host.edge;
      const a = roof?.area[edge], b = roof?.area[(edge + 1) % roof.area.length];
      if (!a || !b) return;
      const d = b.map((v, i) => v - a[i]), length = Math.hypot(...d);
      operation.host = { ...piece.host, at: piece.host.at + inch(point.slice(0, 2).reduce((n, v, i) => n + (v - g.start[i]) * d[i] / length, 0)) };
    } else {
      const rooms = building.rooms.filter(r => r.state !== 'ghost' && r.level === handle.level);
      const room = rooms.find(r => contains(r.polygon, point));
      const surface = piece.host.ceiling ? 'ceiling' : 'floor';
      if (piece.host.ground) operation.host = { ground: true, at: point.slice(0, 2).map(inch) };
      else if (room) {
        const xs = room.polygon.map(p => p[0]), ys = room.polygon.map(p => p[1]), x0 = Math.min(...xs), y0 = Math.min(...ys);
        operation.host = { [surface]: room.id, u: (point[0] - x0) / (Math.max(...xs) - x0), v: (point[1] - y0) / (Math.max(...ys) - y0) };
      } else return;
    }
    g.operation = operation;
    preview = structuredClone(g.source);
    const nextBuilding = preview.buildings.find(b => b.id === building.id), next = nextBuilding[g.list].find(p => p.id === piece.id);
    for (const field of ['at', 'width', 'head', 'sill']) if (field in operation) next[field] = operation[field];
    if (operation.host) next.host = { ...operation.host };
    else if (next.host) { next.host.at = next.at; next.host.sill = next.sill; }
    // Keep the last drawable buffers if an edge passes its opposite edge.
    // Still send the release unchanged so refusal and its words come from the server.
    if (g.list !== 'openings' || next.width > 0 && next.head > next.sill)
      view.rebuildLevel(building.id, handle.level, preview, { [g.list]: [piece.id] });
    onPreview?.(preview, getSelection()); refresh();
    lastFrameMs = Math.max(.001, performance.now() - started);
  }
  async function finish(cancel = false) {
    const g = gesture; gesture = null; preview = null;
    if (!g) return;
    if (['wall', 'joint', 'room'].includes(g.handle.kind)) {
      try { await drag.finish(cancel); }
      finally { preview = null; refresh(); }
      return;
    }
    const restore = () => { view.rebuildLevel(g.building.id, g.handle.level, g.source, { [g.list]: [g.piece.id] }); onPreview?.(g.source, getSelection()); refresh(); };
    if (cancel || !g.operation) { restore(); return; }
    try { await onCommit(g.operation); }
    catch (error) { restore(); throw error; }
    refresh();
  }
  view.controls.addEventListener('change', refresh);
  host.addEventListener('twinrebuilt', refresh, { signal });
  window.addEventListener('resize', refresh, { signal });
  signal.addEventListener('abort', () => { view.controls.removeEventListener('change', refresh); layer.remove(); }, { once: true });
  return { begin, update, finish, refresh, hit, active: () => !!gesture,
    show(value) { preview = value; refresh(); },
    handles() { refresh(); return rows.map(({ handle }) => ({ kind: handle.kind, id: handle.id, at: [...handle.at] })); },
    get lastDragFrameMs() { return lastFrameMs ?? drag.lastDragFrameMs; } };
}
