import * as THREE from 'three';
import { hostPoint } from '../twin_hosts.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { markerTexture, markerSprite } from '../live/markers.js';
import { itemOperation, wallFace } from './library.js';
import { report } from './api.js';

const FT = .3048, badHost = 'Pick a wall, floor, ceiling or door for it.';

// Device placement uses the library's surface ray and host coordinates. It
// never controls a device: Blink belongs to the guarded identify route.
export function createDevicePlacement({ view, tools, library, getPlan, op, canEdit, signal, prepare }) {
  const canvas = view.renderer3.domElement, link = tools.haLink;
  const el = id => document.getElementById(id);
  const listen = (node, type, action, options = {}) => node.addEventListener(type, action, { ...options, signal });
  const root = new THREE.Group(), textures = new Map(), sprites = new Map();
  root.name = 'editor-device-markers';
  view.scene.add(root);
  let armed = null, press = null, drag = null, stopped = false;

  function anchors(room) {
    const building = getPlan()?.buildings.find(b => b.id === room.building);
    return (building?.anchors || []).filter(a => {
      if (a.state === 'ghost') return false;
      const host = a.host || {};
      if (host.floor === room.id || host.ceiling === room.id) return true;
      const wall = building.walls.find(w => w.id === host.wall && w.state !== 'ghost');
      return wall && wallFace(building, wall, host.side).room?.id === room.id;
    });
  }

  function openingHost(building, opening, side) {
    const wall = building.walls.find(w => w.id === (opening.wall || opening.host?.wall));
    if (!wall) return null;
    const inside = wallFace(building, wall, 'left').room ? 'left' : 'right';
    return { opening: opening.id, side: side === inside ? 'in' : 'out' };
  }

  // The room's doors (any opening but a window), each with the host that puts a device on
  // this room's face of it: a lock or a contact sensor belongs on its door.
  function doors(room) {
    const building = getPlan()?.buildings.find(b => b.id === room.building);
    const out = [];
    for (const opening of building?.openings || []) {
      if (opening.kind === 'window' || opening.state === 'ghost') continue;
      const wall = building.walls.find(w => w.id === (opening.wall || opening.host?.wall) && w.state !== 'ghost');
      if (!wall) continue;
      const left = wallFace(building, wall, 'left').room, right = wallFace(building, wall, 'right').room;
      const side = left?.id === room.id ? 'left' : right?.id === room.id ? 'right' : null;
      const host = side && openingHost(building, opening, side);
      if (!host) continue;
      const other = side === 'left' ? right : left, noun = opening.kind === 'garage' ? 'garage door' : 'door';
      const label = opening.name || (other ? `${noun[0].toUpperCase()}${noun.slice(1)} to ${other.name || 'the next room'}` : `Outside ${noun}`);
      out.push({ id: opening.id, building: building.id, host, label });
    }
    // Doors that read the same are told apart by number.
    const seen = new Map();
    for (const door of out) seen.set(door.label, (seen.get(door.label) || 0) + 1);
    const count = new Map();
    for (const door of out) if (seen.get(door.label) > 1) {
      count.set(door.label, (count.get(door.label) || 0) + 1);
      door.label = `${door.label} ${count.get(door.label)}`;
    }
    return out;
  }

  function operation(device, event, surfaceKind = null) {
    const picked = view.pick(event.clientX, event.clientY);
    const building = getPlan()?.buildings.find(b => b.id === (picked?.building ?? picked?.buildingId));
    if (!surfaceKind && building) {
      const id = picked.id ?? picked.pieceId;
      const anchor = building.anchors?.find(a => a.id === id);
      if (anchor) return { op: 'place_device', device: device.device_id, anchor: anchor.id };
      const opening = building.openings?.find(o => o.id === id && o.kind !== 'window' && o.state !== 'ghost');
      if (opening) {
        const surface = library.surfaceAt(event);
        const host = surface && openingHost(building, opening, surface.side);
        if (host) return { op: 'place_device', device: device.device_id, building: building.id, host };
      }
    }
    const surface = surfaceKind === 'ceiling' ? library.ceilingAt(event)
      : library.surfaceAt(event) || (!surfaceKind && library.ceilingAt(event, true));
    if (!surface || !['wall', 'room'].includes(surface.kind)
      || surfaceKind === 'wall' && surface.kind !== 'wall'
      || surfaceKind === 'ceiling' && (surface.kind !== 'room' || surface.surface !== 'ceiling')) throw new Error(badHost);
    const { host } = itemOperation(surface, { kind: 'furniture' });
    return { op: 'place_device', device: device.device_id, building: surface.building.id, host };
  }

  function releasePress() {
    if (!press) return;
    const previous = press; press = null;
    view.controls.enabled = previous.enabled;
    if (canvas.hasPointerCapture(previous.pointer)) canvas.releasePointerCapture(previous.pointer);
  }
  function cancel() {
    releasePress();
    if (drag) {
      const previous = drag; drag = null;
      if (previous.row.hasPointerCapture(previous.pointer)) previous.row.releasePointerCapture(previous.pointer);
    }
    armed = null; el('device-tools').hidden = true; el('device-tools').classList.remove('editor-device-dragging');
    canvas.style.cursor = ''; document.body.style.cursor = '';
  }
  function arm(device, kind) {
    cancel(); prepare(); tools.setTool('select');
    armed = { device, kind };
    el('device-note').textContent = `Click ${kind === 'wall' ? 'a wall' : 'the ceiling'} for ${device.name}. Escape cancels.`;
    el('device-tools').hidden = false; canvas.style.cursor = 'crosshair';
  }
  function startDrag(event, device) {
    if (event.button !== 0 || !canEdit() || event.target.closest('button')) return;
    cancel(); prepare(); tools.setTool('select');
    event.preventDefault();
    const row = event.currentTarget; row.setPointerCapture(event.pointerId);
    drag = { row, device, pointer: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
  }
  // A carried row says what a drop does; the note lets pointer presses through
  // (editor-device-dragging), so a drop under it still reaches the scene.
  listen(document, 'pointermove', event => {
    if (!drag || drag.pointer !== event.pointerId || drag.moved
      || Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 3) return;
    drag.moved = true;
    el('device-note').textContent = `Drop ${drag.device.name} on a wall, the floor, the ceiling or a spot. Escape cancels.`;
    el('device-tools').classList.add('editor-device-dragging');
    el('device-tools').hidden = false; document.body.style.cursor = 'grabbing';
  }, { capture: true });
  function pointerDown(event) {
    if (!armed || !canEdit() || event.button !== 0) return false;
    press = { pointer: event.pointerId, x: event.clientX, y: event.clientY, enabled: view.controls.enabled };
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId);
    return true;
  }
  function pointerUp(event, cancelled) {
    if (!press || press.pointer !== event.pointerId) return false;
    const previous = press; releasePress();
    if (!cancelled && armed && canEdit() && Math.hypot(event.clientX - previous.x, event.clientY - previous.y) < 3) {
      try { const next = operation(armed.device, event, armed.kind); cancel(); op(next).catch(report); }
      catch (error) { report(error); }
    }
    return true;
  }
  listen(document, 'pointerup', event => {
    if (!drag || drag.pointer !== event.pointerId) return;
    const previous = drag; cancel();
    if (!canEdit() || Math.hypot(event.clientX - previous.x, event.clientY - previous.y) < 3
      || !canvas.contains(document.elementFromPoint(event.clientX, event.clientY))) return;
    try { op(operation(previous.device, event)).catch(report); } catch (error) { report(error); }
  }, { capture: true });
  listen(document, 'pointercancel', cancel, { capture: true });
  listen(document, 'keydown', event => {
    if (event.key !== 'Escape' || !armed && !drag) return;
    cancel(); event.preventDefault(); event.stopImmediatePropagation();
  }, { capture: true });
  listen(el('device-cancel'), 'click', cancel);

  // Positions come from the link's auto spots and the current saved plan, so
  // a slow HA read never delays a rebuild or a person's saved placement.
  function spot(device) {
    const plan = getPlan();
    for (const building of plan?.buildings || []) {
      const piece = building.anchors?.find(a => a.device === device.device_id)
        || building.devices?.find(d => d.device === device.device_id);
      if (!piece) continue;
      const host = piece.host || {};
      let resolved = host;
      if (host.opening) {
        const opening = building.openings?.find(o => o.id === host.opening);
        if (!opening) return null;
        const wall = building.walls.find(w => w.id === (opening.wall || opening.host?.wall));
        if (!wall) return null;
        const inside = wallFace(building, wall, 'left').room ? 'left' : 'right';
        const side = host.side === 'in' ? inside : inside === 'left' ? 'right' : 'left';
        resolved = { wall: wall.id, side, at: opening.at ?? opening.host?.at,
          z: opening.kind === 'window' ? (opening.sill || 0) + 1 : 3.5 };
      }
      try {
        const point = hostPoint(building, resolved, piece.offset || 0);
        const surface = building.walls.find(w => w.id === resolved.wall)
          || building.rooms.find(r => r.id === (resolved.floor || resolved.ceiling));
        const room = resolved.floor || resolved.ceiling
          || (resolved.wall && wallFace(building, surface, resolved.side).room?.id);
        return { building, point, level: surface?.level, room };
      } catch { return null; }
    }
    const auto = device.auto, building = plan?.buildings.find(b => b.id === auto?.building);
    return building && auto ? { building, point: [...auto.at, auto.z], level: auto.level, room: auto.room } : null;
  }
  function draw() {
    if (stopped) return;
    const selected = tools.selection(), camera = view.camera, rect = canvas.getBoundingClientRect();
    camera.updateMatrixWorld(true);
    for (const { at, sprite } of sprites.values()) {
      sprite.visible = !!at && view.groups?.levels[`${at.building.id}:${at.level}`]?.visible !== false;
      if (!at || !sprite.visible) continue;
      const pixel = camera.isOrthographicCamera ? (camera.top - camera.bottom) / camera.zoom / Math.max(1, rect.height)
        : 2 * Math.max(.1, -sprite.position.clone().applyMatrix4(camera.matrixWorldInverse).z)
          * Math.tan(camera.fov * Math.PI / 360) / camera.zoom / Math.max(1, rect.height);
      sprite.scale.setScalar(pixel * 22);
      const inRoom = !selected.room || selected.building === at.building.id && at.room === selected.room;
      sprite.material.opacity = inRoom ? 1 : .2;
    }
  }
  const saved = device => getPlan()?.buildings.some(b => b.anchors?.some(a => a.device === device.device_id)
    || b.devices?.some(d => d.device === device.device_id));
  // Like the wall: a device in a Home Assistant area draws; with no room linked to its area
  // only a saved placement says where (the building card flags it to move or remove).
  function refresh() {
    if (stopped) return;
    const state = link.state(), shown = new Set();
    for (const device of state?.available ? state.devices || [] : []) {
      if (!state.areas?.some(a => a.area_id === device.area_id)) continue;
      if (!state.rooms?.some(r => r.ha_area === device.area_id && !r.gone) && !saved(device)) continue;
      shown.add(device.device_id);
      let row = sprites.get(device.device_id);
      if (!row) {
        if (!textures.has(device.kind)) textures.set(device.kind, markerTexture(device.kind, 'off'));
        const sprite = markerSprite(textures.get(device.kind)); root.add(sprite);
        sprite.userData.deviceId = device.device_id;
        row = { sprite }; sprites.set(device.device_id, row);
      }
      row.at = spot(device);
      if (row.at) {
        const { building, point } = row.at, a = (building.rotation || 0) * Math.PI / 180, p = building.position || [0, 0];
        row.sprite.position.set((Math.cos(a) * point[0] - Math.sin(a) * point[1] + p[0]) * FT,
          (point[2] + (building.base || 0) + buildingGround(getPlan(), building)) * FT,
          -(Math.sin(a) * point[0] + Math.cos(a) * point[1] + p[1]) * FT);
      }
    }
    for (const [id, row] of sprites) if (!shown.has(id)) { row.sprite.removeFromParent(); row.sprite.material.dispose(); sprites.delete(id); }
    draw();
  }
  function stop() {
    if (stopped) return;
    stopped = true;
    cancel(); link.setPlacement(null); root.removeFromParent();
    sprites.forEach(row => row.sprite.material.dispose()); textures.forEach(texture => texture.dispose());
    sprites.clear(); textures.clear();
  }
  const controller = { anchors, doors, arm, startDrag, pointerDown, pointerUp, cancel, refresh, draw, stop };
  link.setPlacement(controller);
  signal.addEventListener('abort', stop, { once: true });
  return controller;
}
