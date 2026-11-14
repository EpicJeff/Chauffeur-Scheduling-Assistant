import * as THREE from 'three';
import { floorOutline } from './viewing.js';
import { groundAt } from './twin_ground.js';
import { twinGlassStrong, twinText, twinBorder } from './palette.js';

// Viewer navigation's tuning surface. Distances and heights are in lot feet;
// zoom ratios are relative to the level's fitted camera distance.
export const LEVEL_TUNING = Object.freeze({
  easeMs: 400, orbitPolarMin: Math.PI * .22, orbitPolarMax: Math.PI * .46,
  orbitPolarDefault: Math.PI * .36, orbitYawDefault: -Math.PI * .28,
  zoom: Object.freeze({house: [.85, 1.15], building: [.85, 1.15], floor: [.9, 1.1], room: [.8, 1.2]}),
  zoomCommit: .18, zoomHardMin: .45, zoomHardMax: 1.8, wheelEndMs: 160,
  swipeConeDegrees: 45, swipeMinPx: 32, tapSlopPx: 6, neighbourTieFeet: .01,
  framePadding: 1.35, yardFramePadding: 1.1, minSpanFeet: 3, iconPx: 52, iconGapPx: 72, iconOffsetFeet: 7,
  topOffsetFeet: .001,
  topPolarMax: .0001,
});
const FT = .3048;
const transform = (b, [x, y]) => {
  const a = (b.rotation || 0) * Math.PI / 180;
  return [Math.cos(a) * x - Math.sin(a) * y + (b.position?.[0] || 0),
    Math.sin(a) * x + Math.cos(a) * y + (b.position?.[1] || 0)];
};
export function centroid(poly) {
  let area = 0, x = 0, y = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i], q = poly[(i + 1) % poly.length], cross = p[0] * q[1] - q[0] * p[1];
    area += cross; x += (p[0] + q[0]) * cross; y += (p[1] + q[1]) * cross;
  }
  return Math.abs(area) > 1e-8 ? [x / (3 * area), y / (3 * area)]
    : [0, 1].map(i => poly.reduce((sum, p) => sum + p[i], 0) / Math.max(1, poly.length));
}
function sharedWall(a, b) {
  let total = 0;
  for (let i = 0; i < a.length; i++) for (let j = 0; j < b.length; j++) {
    const p = a[i], q = a[(i + 1) % a.length], r = b[j], s = b[(j + 1) % b.length];
    const dx = q[0] - p[0], dy = q[1] - p[1], length = Math.hypot(dx, dy);
    if (!length || Math.abs(dx * (r[1] - p[1]) - dy * (r[0] - p[0])) / length > LEVEL_TUNING.neighbourTieFeet
      || Math.abs(dx * (s[1] - p[1]) - dy * (s[0] - p[0])) / length > LEVEL_TUNING.neighbourTieFeet) continue;
    const project = t => ((t[0] - p[0]) * dx + (t[1] - p[1]) * dy) / length;
    total += Math.max(0, Math.min(length, Math.max(project(r), project(s))) - Math.max(0, Math.min(project(r), project(s))));
  }
  return total;
}
export function roomNeighbour(rooms, current, direction) {
  const from = rooms.find(r => r.id === current); if (!from) return null;
  const start = centroid(from.polygon), length = Math.hypot(...direction); if (!length) return null;
  const cone = Math.cos(LEVEL_TUNING.swipeConeDegrees * Math.PI / 180);
  const candidates = rooms.filter(r => r.id !== current && r.level === from.level).flatMap(r => {
    const end = centroid(r.polygon), dx = end[0] - start[0], dy = end[1] - start[1], distance = Math.hypot(dx, dy);
    return distance && (dx * direction[0] + dy * direction[1]) / (distance * length) >= cone - 1e-8
      ? [{room: r, distance, wall: sharedWall(from.polygon, r.polygon)}] : [];
  });
  candidates.sort((a, b) => Math.abs(a.distance - b.distance) > LEVEL_TUNING.neighbourTieFeet
    ? a.distance - b.distance : b.wall - a.wall || a.room.id.localeCompare(b.room.id));
  return candidates[0]?.room || null;
}
export function deviceAtLevel(state, row) {
  // Outside rooms behave like inside ones: their devices show once that room is focused (user,
  // 2026-11-14: "hiding until you focus that area"); the room's own icon stands for them before.
  if (row.yard) return row.look === 'attention' && state.level === 'house' || state.level === 'room' && state.building == null && row.room === state.room;
  if (row.fire_pit) return state.level === 'house';
  return row.look === 'attention' || state.level === 'room' && row.building === state.building && row.room === state.room;
}

// The 2b ease, shared by level transitions and marker clumps. OrbitControls is
// still the sole interaction controller. It resumes after the blended pose lands.
export function animateCamera(view, target, distance, zoom = view.camera.zoom, done = () => {}, direction = null) {
  view.cancelCameraMotion?.();
  const camera = view.camera, controls = view.controls, from = camera.position.clone(), start = controls.target.clone();
  const startZoom = camera.zoom, axis = direction || from.clone().sub(start).normalize();
  const to = target.clone().addScaledVector(axis, distance), started = performance.now();
  let cancelled = false;
  const cancel = () => { cancelled = true; view.cameraTransition = false; };
  view.cancelCameraMotion = cancel; view.cameraTransition = true;
  const step = () => {
    if (cancelled) return;
    const t = Math.min(1, (performance.now() - started) / LEVEL_TUNING.easeMs), ease = t * t * (3 - 2 * t);
    camera.position.lerpVectors(from, to, ease); controls.target.lerpVectors(start, target, ease);
    camera.zoom = startZoom + (zoom - startZoom) * ease; camera.updateProjectionMatrix(); camera.lookAt(controls.target);
    view.render();
    if (t < 1) requestAnimationFrame(step);
    else { view.cameraTransition = false; controls.update?.(); done(); }
  };
  requestAnimationFrame(step);
  return cancel;
}

export function createLevels(view, {visibility, host = view.renderer3.domElement.parentElement} = {}) {
  const canvas = view.renderer3.domElement, controls = view.controls, events = new AbortController();
  const root = new THREE.Group(), targets = document.createElement('div'), chip = document.createElement('nav');
  root.name = 'level-targets'; targets.className = 'twin-level-targets'; chip.id = 'twin-path'; chip.setAttribute('aria-label', 'House path');
  host.append(targets, chip); view.scene.add(root);
  const textures = new Map(), icons = [], pointers = new Map();
  let state = {level: 'house', building: null, floor: null, room: null}, distance = 1, wheelTimer = null, pinch = false, gestureState = null, center = null;
  let orbit = new THREE.Vector3(Math.sin(LEVEL_TUNING.orbitYawDefault) * Math.sin(LEVEL_TUNING.orbitPolarDefault),
    Math.cos(LEVEL_TUNING.orbitPolarDefault), Math.cos(LEVEL_TUNING.orbitYawDefault) * Math.sin(LEVEL_TUNING.orbitPolarDefault));
  const buildings = () => view.plan.buildings || [];
  const yardRooms = () => view.plan.site?.yard_rooms || [];
  const yardRoom = () => state.building == null && state.room != null ? yardRooms().find(r => r.id === state.room) : null;
  const building = () => buildings().find(b => b.id === state.building);
  const floors = b => [...(b?.levels || [])].sort((a, b) => a.elevation - b.elevation);
  function normalize(next, idle = false) {
    const yard = next.building == null && next.room != null ? yardRooms().find(r => r.id === next.room) : null;
    if (yard) return {level: 'room', building: null, floor: null, room: yard.id};
    let b = buildings().find(b => b.id === next.building), f = b?.levels.find(l => l.id === next.floor);
    if (next.building != null && !b) return null;
    const r = next.room != null ? b?.rooms?.find(r => r.id === next.room) : null;
    if (r) f = b.levels.find(l => l.id === r.level);
    if (next.room != null && !r || next.floor != null && !f) return null;
    let level = next.level || (r ? 'room' : f ? 'floor' : b ? 'building' : 'house');
    if (!['house', 'building', 'floor', 'room'].includes(level)) return null;
    if (!idle && level === 'house' && buildings().length === 1 && !yardRooms().length) { b = buildings()[0]; level = 'building'; }
    if (!idle && level === 'building' && b?.levels.length === 1) { level = 'floor'; f = b.levels[0]; }
    if (level !== 'house' && !b || ['floor', 'room'].includes(level) && !f || level === 'room' && !r) return null;
    return {level, building: level === 'house' ? null : b.id, floor: ['floor', 'room'].includes(level) ? f.id : null, room: level === 'room' ? r.id : null};
  }
  const base = b => groundAt(view.plan, ...(b.position || [0, 0])) + (b.base || 0);
  function heights(b) {
    const box = new THREE.Box3();
    for (const group of [...Object.values(view.groups?.levels || {}), ...(view.groups?.roof?.children || [])])
      if (group.userData.buildingId === b.id) box.union(new THREE.Box3().setFromObject(group));
    return box.isEmpty() ? [base(b), base(b) + Math.max(0, ...b.levels.map(l => l.elevation + (l.ceiling || 8)))] : [box.min.y / FT, box.max.y / FT];
  }
  function framing() {
    const b = building(), f = b?.levels.find(l => l.id === state.floor), yard = yardRoom(), r = yard || b?.rooms?.find(r => r.id === state.room);
    const list = b ? [b] : buildings();
    const points = r ? yard ? r.polygon : r.polygon.map(p => transform(b, p))
      : [...list.flatMap(b => (f ? [f] : b.levels).flatMap(l => floorOutline(b, l))), ...(state.level === 'house' ? yardRooms().flatMap(r => r.polygon) : [])];
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    const x0 = Math.min(...xs, ...(points.length ? [] : [0])), x1 = Math.max(...xs, ...(points.length ? [] : [20]));
    const y0 = Math.min(...ys, ...(points.length ? [] : [0])), y1 = Math.max(...ys, ...(points.length ? [] : [20]));
    // An outside room orbits (nothing to cut through outdoors); inside rooms and floors look down.
    const top = ['floor', 'room'].includes(state.level) && !yard;
    const ranges = top || yard ? [] : list.map(heights), low = ranges.length ? Math.min(...ranges.map(r => r[0])) : 0,
      high = ranges.length ? Math.max(...ranges.map(r => r[1])) : 0;
    const height = yard ? groundAt(view.plan, ...centroid(yard.polygon)) : top ? base(b) + f.elevation : (low + high) / 2;
    // At House, orbit the centroid of building centroids, rather than a lot or an outlier's bbox centre.
    const centres = list.map(b => centroid(floorOutline(b, floors(b)[0] || {})));
    const at = yard ? centroid(yard.polygon) : state.level === 'house' && centres.length ? [0, 1].map(i => centres.reduce((sum, p) => sum + p[i], 0) / centres.length) : [(x0 + x1) / 2, (y0 + y1) / 2];
    const span = Math.max(LEVEL_TUNING.minSpanFeet, 2 * Math.max(at[0] - x0, x1 - at[0]) / (view.camera.aspect || 1),
      2 * Math.max(at[1] - y0, y1 - at[1]), top ? 0 : high - low);
    const target = new THREE.Vector3(at[0] * FT, height * FT, -at[1] * FT);
    if (yard && !top && view.camera.isPerspectiveCamera) {
      // Orbit framing for an outside room: fit its corners in camera space along the orbit
      // direction, so the foreshortened ground still fills the screen.
      const inverse = new THREE.Quaternion().setFromRotationMatrix(
        new THREE.Matrix4().lookAt(orbit, new THREE.Vector3(), view.camera.up)).invert();
      const tan = Math.tan(view.camera.fov * Math.PI / 360) / (view.camera.zoom || 1), aspect = view.camera.aspect || 1;
      const padding = LEVEL_TUNING.yardFramePadding;
      const distance = Math.max(...yard.polygon.map(p => {
        const q = new THREE.Vector3(p[0] * FT, height * FT, -p[1] * FT).sub(target).applyQuaternion(inverse);
        return q.z + Math.max(view.camera.near * 2, Math.abs(q.x) * padding / (tan * aspect), Math.abs(q.y) * padding / tan);
      }));
      return {target, distance, top};
    }
    return {target,
      distance: span * FT * LEVEL_TUNING.framePadding / (2 * Math.tan(view.camera.fov * Math.PI / 360)), top};
  }
  function configure() {
    const top = (state.level === 'floor' || state.level === 'room') && !yardRoom();
    controls.enablePan = false; controls.enableRotate = !top; controls.enableZoom = true;
    controls.minPolarAngle = top ? 0 : LEVEL_TUNING.orbitPolarMin;
    controls.maxPolarAngle = top ? LEVEL_TUNING.topPolarMax : LEVEL_TUNING.orbitPolarMax;
    controls.minDistance = distance * LEVEL_TUNING.zoomHardMin; controls.maxDistance = distance * LEVEL_TUNING.zoomHardMax;
  }
  function path() {
    const b = building(), f = b?.levels.find(l => l.id === state.floor), r = yardRoom() || b?.rooms?.find(r => r.id === state.room);
    return [ ...(buildings().length !== 1 || yardRooms().length ? [{text: 'House', state: {level: 'house'}}] : []),
      ...(b ? [{text: b.name || b.id, state: {building: b.id}}] : []),
      ...(f ? [{text: f.name || f.id, state: {building: b.id, floor: f.id}}] : []),
      ...(r ? [{text: r.name || r.id, state: {building: b?.id || null, room: r.id}}] : [])];
  }
  function syncPath() {
    chip.replaceChildren();
    const parts = path();
    parts.forEach((part, i) => {
      if (i) { const sep = document.createElement('span'); sep.textContent = ' › '; sep.setAttribute('aria-hidden', 'true'); chip.append(sep); }
      const button = document.createElement('button'); button.type = 'button'; button.textContent = part.text;
      button.dataset.pathLevel = part.state.room ? 'room' : part.state.floor ? 'floor' : part.state.building ? 'building' : 'house';
      if (i === parts.length - 1) button.setAttribute('aria-current', 'location');
      button.addEventListener('click', () => go(part.state)); chip.append(button);
    });
  }
  function go(next, {immediate = false, idle = false} = {}) {
    const resolved = normalize(next, idle); if (!resolved) return false;
    clearTimeout(wheelTimer); view.cancelCameraMotion?.();
    if ((state.level === 'house' || state.level === 'building') && view.camera.position.distanceTo(controls.target) > .01)
      orbit.copy(view.camera.position).sub(controls.target).normalize();
    state = resolved; view.live?.closeRoom();
    const frame = framing(); distance = frame.distance;
    configure(); visibility(frame.top && state.building != null ? `${state.building}:${state.floor}` : 'ext');
    for (const icon of icons) if (icon.outline) icon.outline.visible = icon.r === state.room && state.building == null;
    view.state.camera = frame.top ? 'top' : 'orbit'; syncPath();
    const axis = frame.top ? new THREE.Vector3(0, 1, LEVEL_TUNING.topOffsetFeet / (distance / FT)).normalize() : orbit;
    if (immediate) {
      controls.target.copy(frame.target); view.camera.position.copy(frame.target).addScaledVector(axis, distance); view.camera.zoom = 1;
      view.camera.updateProjectionMatrix(); controls.update(); view.render();
    } else animateCamera(view, frame.target, distance, 1, () => { configure(); view.render(); }, axis);
    host.dispatchEvent(new CustomEvent('twinlevelchange', {detail: snapshot()}));
    if (yardRoom()) view.live?.openRoom(null, state.room);
    return true;
  }
  function down(point = center) {
    if (state.level === 'house') {
      const rect = canvas.getBoundingClientRect(), at = point || [rect.left + rect.width / 2, rect.top + rect.height / 2];
      const nearest = icons.filter(i => !i.f).map(icon => { const p = icon.sprite.position.clone().project(view.camera);
        return {icon, d: Math.hypot(rect.left + (p.x + 1) * rect.width / 2 - at[0], rect.top + (1 - p.y) * rect.height / 2 - at[1])};
      }).sort((a, b) => a.d - b.d)[0];
      return nearest ? go(nearest.icon.r ? {room: nearest.icon.r} : {building: nearest.icon.b}) : false;
    }
    if (state.level === 'building') return go({building: state.building, floor: floors(building())[0]?.id});
    if (state.level === 'floor') {
      const rect = canvas.getBoundingClientRect(), at = point || [rect.left + rect.width / 2, rect.top + rect.height / 2];
      const pick = view.pick(...at);
      if (pick?.kind === 'room' && pick.building === state.building) return go({building: state.building, room: pick.id});
      const local = view.floorAt(...at, `${state.building}:${state.floor}`);
      const room = building()?.rooms?.find(r => r.level === state.floor && local && inside(r.polygon, local));
      return room ? go({building: state.building, room: room.id}) : false;
    }
    return false;
  }
  function up() {
    if (yardRoom()) return go({level: 'house'});
    if (!yardRooms().length && buildings().length === 1 && (state.level === 'building' || state.level === 'floor' && building()?.levels.length === 1)) return false;
    if (state.level === 'room') return go({building: state.building, floor: state.floor});
    if (state.level === 'floor') return building()?.levels.length === 1 ? go({level: 'house'}) : go({building: state.building});
    if (state.level === 'building') return go({level: 'house'});
    return false;
  }
  function zoomEnd(ratio = view.camera.position.distanceTo(controls.target) / distance, point = center) {
    const [min, max] = LEVEL_TUNING.zoom[state.level];
    if (ratio < min * (1 - LEVEL_TUNING.zoomCommit) && down(point)) return 'down';
    if (ratio > max * (1 + LEVEL_TUNING.zoomCommit) && up()) return 'up';
    if (ratio < min || ratio > max) {
      const axis = view.camera.position.clone().sub(controls.target).normalize();
      animateCamera(view, controls.target.clone(), distance * Math.max(min, Math.min(max, ratio)), view.camera.zoom, () => {}, axis);
      return 'spring';
    }
    return 'stay';
  }
  function swipe(dx, dy) {
    if (state.level !== 'room' || Math.hypot(dx, dy) < LEVEL_TUNING.swipeMinPx) return false;
    const b = building();
    if (!b) {
      const next = roomNeighbour(yardRooms(), state.room, [dx, -dy]);
      return next ? go({room: next.id}) : false;
    }
    const a = -(b.rotation || 0) * Math.PI / 180;
    // The top camera's screen right is world +x, screen down is world -y.
    const direction = [Math.cos(a) * dx + Math.sin(a) * dy, Math.sin(a) * dx - Math.cos(a) * dy];
    const next = roomNeighbour(b.rooms || [], state.room, direction);
    if (next) return go({building: b.id, room: next.id});
    const current = b.rooms.find(r => r.id === state.room);
    const outdoor = current && roomNeighbour([{...current, level: undefined, polygon: current.polygon.map(p => transform(b, p))}, ...yardRooms()], state.room, [dx, -dy]);
    return outdoor ? go({room: outdoor.id}) : false;
  }
  function framingBuilding(b) {
    const at = centroid(floorOutline(b, floors(b)[0] || {}));
    return new THREE.Vector3(at[0] * FT, base(b) * FT, -at[1] * FT);
  }
  function texture(kind) {
    if (textures.has(kind)) return textures.get(kind);
    const c = document.createElement('canvas'); c.width = c.height = 96;
    const ctx = c.getContext('2d'); ctx.fillStyle = twinGlassStrong; ctx.strokeStyle = twinBorder; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(48, 48, 44, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.strokeStyle = twinText; ctx.lineWidth = 4; ctx.beginPath();
    const points = kind === 'building' ? [[22,44],[48,23],[74,44],[74,73],[22,73],[22,44]] : [[22,46],[48,30],[74,46],[48,62],[22,46]];
    points.forEach(([x,y], i) => i ? ctx.lineTo(x,y) : ctx.moveTo(x,y)); ctx.stroke();
    if (kind === 'floor') {ctx.beginPath();ctx.moveTo(22,57);ctx.lineTo(48,73);ctx.lineTo(74,57);ctx.stroke();}
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; textures.set(kind, t); return t;
  }
  for (const b of buildings()) for (const f of [null, ...floors(b)]) {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture(f ? 'floor' : 'building'), depthTest: false, depthWrite: false, toneMapped: false}));
    sprite.renderOrder = 21; root.add(sprite);
    const button = document.createElement('button'); button.type = 'button'; button.textContent = f?.name || f?.id || b.name || b.id;
    button.dataset.levelBuilding = b.id; if (f) button.dataset.levelFloor = f.id;
    button.setAttribute('aria-label', `Open ${button.textContent}`); button.addEventListener('click', () => go({building: b.id, ...(f ? {floor: f.id} : {})})); targets.append(button);
    const position = framingBuilding(b);
    if (f) {
      const outline = floorOutline(b, f); position.x = (Math.max(...outline.map(p => p[0]), position.x / FT) + LEVEL_TUNING.iconOffsetFeet) * FT;
      position.y = (base(b) + f.elevation + (f.ceiling || 8) / 2) * FT;
    }
    sprite.position.copy(position); icons.push({b: b.id, f: f?.id, sprite, button});
  }
  for (const room of yardRooms()) {
    const at = centroid(room.polygon), sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture('floor'), depthTest: false, depthWrite: false, toneMapped: false}));
    sprite.renderOrder = 21; sprite.position.set(at[0] * FT, groundAt(view.plan, ...at) * FT, -at[1] * FT); root.add(sprite);
    const button = document.createElement('button'); button.type = 'button'; button.textContent = room.name || room.id;
    button.dataset.levelRoom = room.id; button.setAttribute('aria-label', `Open ${button.textContent}`);
    button.addEventListener('click', () => go({room: room.id})); targets.append(button);
    const points = [];
    for (let i = 0; i < room.polygon.length; i++) {
      const p = room.polygon[i], q = room.polygon[(i + 1) % room.polygon.length], steps = Math.max(1, Math.min(128, Math.ceil(Math.hypot(q[0] - p[0], q[1] - p[1]))));
      for (let j = 0; j < steps; j++) { const x = p[0] + (q[0] - p[0]) * j / steps, y = p[1] + (q[1] - p[1]) * j / steps;
        points.push(new THREE.Vector3(x * FT, (groundAt(view.plan, x, y) + .04) * FT, -y * FT)); }
    }
    if (points.length) points.push(points[0].clone());
    const outline = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({color: twinText, transparent: true, opacity: .5, depthWrite: false}));
    outline.name = `yard-room-outline:${room.id}`; outline.visible = false; root.add(outline);
    icons.push({r: room.id, sprite, button, outline});
  }
  // Include both target kinds in initial warm-up, including a house which skips
  // straight to its sole floor. A later idle House pose introduces no program.
  view.renderer3.compileAsync?.(view.scene, view.camera).catch(() => {});
  function draw() {
    const rect = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    let lastY = -Infinity;
    for (const icon of [...icons].reverse()) {
      const visible = !view.idle?.active() && (state.level === 'house' ? !icon.f : state.level === 'building' && icon.b === state.building && !!icon.f);
      icon.sprite.visible = visible; icon.button.hidden = !visible; if (!visible) continue;
      const p = icon.sprite.position.clone().project(view.camera);
      if (Math.abs(p.z) > 1) { icon.sprite.visible = false; icon.button.hidden = true; continue; }
      const x = rect.left + (p.x + 1) * rect.width / 2, originalY = rect.top + (1 - p.y) * rect.height / 2;
      const y = icon.f ? Math.max(originalY, lastY + LEVEL_TUNING.iconGapPx) : originalY; if (icon.f) lastY = y;
      const size = 2 * icon.sprite.position.distanceTo(view.camera.position) * Math.tan(view.camera.fov * Math.PI / 360) / rect.height * LEVEL_TUNING.iconPx;
      icon.sprite.scale.setScalar(size); icon.sprite.center.set(.5, .5 + (y - originalY) / LEVEL_TUNING.iconPx);
      icon.button.style.left = `${x}px`; icon.button.style.top = `${y - LEVEL_TUNING.iconPx / 2}px`;
    }
  }
  function tap(event) {
    const rect = canvas.getBoundingClientRect(), ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2), view.camera);
    const icon = ray.intersectObjects(icons.filter(i => i.sprite.visible).map(i => i.sprite), false)[0]?.object;
    const target = icons.find(i => i.sprite === icon);
    if (target) return go(target.r ? {room: target.r} : {building: target.b, ...(target.f ? {floor: target.f} : {})});
    const pick = view.pick(event.clientX, event.clientY);
    if (state.level === 'house' && pick?.building) return go({building: pick.building});
    if (state.level === 'floor' && pick?.kind === 'room' && pick.building === state.building) return go({building: pick.building, room: pick.id});
    return false;
  }
  const snapshot = () => ({...state});
  canvas.addEventListener('wheel', event => {
    if (!controls.enabled) return;
    view.cancelCameraMotion?.(); center = [event.clientX, event.clientY];
    clearTimeout(wheelTimer); wheelTimer = setTimeout(() => zoomEnd(), LEVEL_TUNING.wheelEndMs);
  }, {capture: true, passive: true, signal: events.signal});
  canvas.addEventListener('pointerdown', event => {
    if (!controls.enabled || event.button > 0) return;
    view.cancelCameraMotion?.(); gestureState = snapshot();
    pointers.set(event.pointerId, {x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY});
    if (pointers.size > 1) pinch = true;
  }, {capture: true, signal: events.signal});
  const move = event => { const p = pointers.get(event.pointerId); if (p) {p.x = event.clientX; p.y = event.clientY;}
    if (pointers.size > 1) { const all = [...pointers.values()]; center = [all.reduce((s,p)=>s+p.x/all.length,0), all.reduce((s,p)=>s+p.y/all.length,0)]; }
  };
  const end = event => {
    const p = pointers.get(event.pointerId); if (!p) return;
    move(event); pointers.delete(event.pointerId);
    if (event.type === 'pointercancel') { if (!pointers.size) {pinch = false; zoomEnd();} return; }
    if (pointers.size) return;
    if (pinch) { pinch = false; zoomEnd(); }
    else if (gestureState?.level === state.level) {
      const dx = p.x - p.startX, dy = p.y - p.startY;
      if (Math.hypot(dx, dy) >= LEVEL_TUNING.swipeMinPx) swipe(dx, dy);
      else if (!view.live && Math.hypot(dx, dy) <= LEVEL_TUNING.tapSlopPx) tap(event);
    }
  };
  canvas.addEventListener('pointermove', move, {capture: true, signal: events.signal});
  for (const name of ['pointerup', 'pointercancel']) canvas.addEventListener(name, end, {capture: true, signal: events.signal});
  controls.addEventListener('start', cancelMotion);
  function cancelMotion() {view.cancelCameraMotion?.();}
  return {go, up, down, zoomEnd, swipe, tap, draw, snapshot, path, configure,
    distance: () => distance,
    restore(saved) {go(saved.state, {immediate: true, idle: saved.state.level === 'house'}); distance = saved.distance; configure();},
    save: () => ({state: snapshot(), distance}),
    stop() {view.cancelCameraMotion?.(); clearTimeout(wheelTimer); events.abort(); controls.removeEventListener('start', cancelMotion);
      root.removeFromParent(); icons.forEach(i => { i.sprite.material.dispose(); i.outline?.geometry.dispose(); i.outline?.material.dispose(); }); textures.forEach(t => t.dispose()); targets.remove(); chip.remove();},
  };
}
function inside(poly, [x, y]) {
  let yes = false;
  for (let i=0,j=poly.length-1;i<poly.length;j=i++) {
    const a=poly[i],b=poly[j]; if ((a[1]>y)!==(b[1]>y) && x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]) yes=!yes;
  }
  return yes;
}
