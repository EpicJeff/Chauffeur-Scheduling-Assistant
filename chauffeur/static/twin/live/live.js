import * as THREE from 'three';
import { base } from '../twin_library.js';
import { groundAt } from '../twin_ground.js';
import { markerState, levelOfDetail, markerTexture, markerSprite } from './markers.js';
import { deviceActions, mountRoomPanel } from './room_panel.js';
import { roomStates, mountModes } from './modes.js';

const FT = .3048, unreachable = 'Home Assistant is not reachable.';
// Screen sizes in CSS px: a marker is a 44 px tap target (the page's own controls' hit height),
// a room badge a little larger; labels never cover another marker or another label.
const MARKER_PX = 44, BADGE_PX = 52, LABEL_GAP = 4, LABEL_H = 23, LABEL_MAX = 190;
let measurer = null;
function labelWidth(text) {
  measurer ||= document.createElement('canvas').getContext('2d');
  measurer.font = '12px system-ui';
  return Math.min(LABEL_MAX, Math.ceil(measurer.measureText(text).width) + 14);
}
const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
const iconKind = row => row.entity_id.startsWith('alarm_control_panel.') ? 'alarm' : row.kind;

export async function mountLive(view, { api = (path, options) => fetch(base() + path, options) } = {}) {
  let layout;
  try {
    const response = await api('api/house/live');
    if (!response.ok) return null;
    layout = await response.json();
  } catch { return null; }
  if (!layout.available || !view.ready) return null;

  const canvas = view.renderer3.domElement, host = canvas.parentElement;
  const root = new THREE.Group(); view.scene.add(root);
  const labels = document.createElement('div'); labels.className = 'twin-live-labels'; host.append(labels);
  const sheet = document.createElement('aside'); sheet.className = 'twin-device-sheet'; sheet.hidden = true;
  sheet.setAttribute('role', 'dialog'); document.body.append(sheet);
  const textures = new Map(), badges = new Map(), listeners = new Set(), busy = new Set();
  const events = new AbortController(), requests = new AbortController();
  const raycaster = new THREE.Raycaster(), projected = new THREE.Vector3();
  let states = {}, stopped = false, stale = true, mode = null, timer = null, polling = Promise.resolve();
  let selected = null, pointer = null;
  let roomPanel = null, modes = null;
  const texture = (kind, look, count = null) => {
    const key = JSON.stringify([kind, look, count]);
    if (!textures.has(key)) textures.set(key, markerTexture(kind, look, count));
    return textures.get(key);
  };
  const rows = layout.markers.map(marker => {
    const sprite = markerSprite(texture(iconKind(marker), 'unavailable'));
    sprite.userData.deviceId = marker.device_id;
    const building = view.plan.buildings.find(b => b.id === marker.building);
    const ground = groundAt(view.plan, ...(building?.position || [0, 0]));
    sprite.position.set(marker.at[0] * FT, (marker.at[2] + ground) * FT, -marker.at[1] * FT);
    root.add(sprite);
    const label = document.createElement('span'); labels.append(label);
    return { ...marker, ...markerState(marker.kind, 'unknown'), stale: true, dim: true, sprite, labelNode: label };
  });
  const plain = row => {
    const { sprite, labelNode, labelBox, screen, ...data } = row;
    return { ...data, at: [...data.at], entities: [...data.entities] };
  };
  const devices = layout.devices || layout.markers;
  const roomRows = () => roomStates(layout.rooms, states);
  function notify() {
    for (const row of rows) {
      row.stale = stale; row.dim = stale || mode === 'lights' && row.kind !== 'light';
      row.sprite.material.map = texture(iconKind(row), row.look);
      row.sprite.material.opacity = row.dim ? .4 : 1;
      const text = `${row.name} · ${row.label}`;
      if (row.labelNode.textContent !== text) { row.labelNode.textContent = text; row.labelBox = null; }
      row.labelBox ||= { w: labelWidth(text), h: LABEL_H };
      row.labelNode.style.opacity = row.dim ? '.4' : '1';
    }
    if (selected) showSheet(selected);
    listeners.forEach(listener => listener());
  }
  function closeSheet() { selected = null; sheet.hidden = true; sheet.replaceChildren(); }
  function showSheet(row) {
    roomPanel?.close();
    selected = row; sheet.replaceChildren(); sheet.hidden = false;
    sheet.setAttribute('aria-label', row.name);
    const heading = document.createElement('h2'); heading.textContent = row.name;
    const status = document.createElement('p'); status.textContent = row.label;
    const actions = deviceActions(row, states[row.entity_id], async (...args) => {
      closeSheet(); return control(...args);
    }, { compact: true });
    const button = (name, action) => {
      const node = document.createElement('button'); node.type = 'button'; node.textContent = name;
      node.addEventListener('click', action); actions.append(node);
    };
    button('Close', closeSheet);
    // Garage already has a Close action; the dismiss control has a distinct name.
    if (row.kind === 'garage' && row.offered) actions.lastChild.setAttribute('aria-label', 'Dismiss');
    sheet.append(heading, status, actions);
  }
  function openRoom(building, room, fallback) {
    closeSheet();
    const row = layout.rooms.find(r => r.building === building && r.room === room);
    const event = new CustomEvent('twinroom', { detail: row, cancelable: true });
    if (canvas.dispatchEvent(event)) {
      if (row?.area_id) roomPanel?.open(row);
      else if (fallback) showSheet(fallback);
      else roomPanel?.close();
    }
  }
  async function control(entityId, service, data = {}) {
    if (stopped || busy.has(entityId)) return false;
    if (stale) { window.showGlobalAlert(unreachable); return false; }
    if (!devices.some(row => row.entity_id === entityId && row.offered
      || row.entities.includes(entityId) && row.offered)) return false;
    busy.add(entityId);
    try {
      const response = await window.chfControlFetch(base() + 'api/ha/card/service', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: entityId.split('.')[0], service, data: { ...data, entity_id: entityId } }),
        signal: requests.signal,
      });
      if (stopped) return false;
      if (response.status === 503) { stale = true; notify(); window.showGlobalAlert(unreachable); }
      else if (!response.ok && response.status !== 403 && !response.chfControlShown) {
        const body = await response.json().catch(() => ({}));
        window.showGlobalAlert(typeof body.detail === 'string' ? body.detail : 'Home Assistant could not finish that request.');
      }
      await refresh(true);
      return response.ok;
    } catch {
      if (!stopped) { stale = true; notify(); window.showGlobalAlert(unreachable); }
      return false;
    } finally { busy.delete(entityId); }
  }
  function tap(row) {
    if (stale) { window.showGlobalAlert(unreachable); return; }
    if (!row.offered) { showSheet(row); return; }
    if (['light', 'switch'].includes(row.kind)) { closeSheet(); void control(row.entity_id, 'toggle'); }
    else if (['lock', 'garage', 'alarm'].includes(iconKind(row))) showSheet(row);
    else openRoom(row.building, row.room, row);
  }
  function draw() {
    if (stopped) return;
    modes?.draw();
    const camera = view.camera, rect = canvas.getBoundingClientRect(); camera.updateMatrixWorld(true);
    const pixelSize = point => camera.isOrthographicCamera ? (camera.top - camera.bottom) / camera.zoom / Math.max(1, rect.height)
      : 2 * Math.max(.1, -point.clone().applyMatrix4(camera.matrixWorldInverse).z)
        * Math.tan(camera.fov * Math.PI / 360) / camera.zoom / Math.max(1, rect.height);
    const shown = rows.filter(row => view.groups?.levels[`${row.building}:${row.level}`]?.visible !== false);
    const lod = levelOfDetail(shown, FT / pixelSize(view.controls.target));
    const individual = new Set(lod.markers), visibleBadges = new Set();
    const place = (sprite, size) => sprite.scale.setScalar(pixelSize(sprite.position) * size);
    const screen = position => {
      projected.copy(position).project(camera);
      return { x: (projected.x + 1) * rect.width / 2, y: (1 - projected.y) * rect.height / 2,
        front: projected.z >= -1 && projected.z <= 1 };
    };
    const icons = [];
    for (const row of rows) {
      row.sprite.visible = individual.has(row.device_id); row.sprite.center.set(.5, .5); place(row.sprite, MARKER_PX);
      row.screen = row.sprite.visible ? screen(row.sprite.position) : null;
      if (row.screen?.front) {
        const half = MARKER_PX / 2;
        icons.push({ row, left: row.screen.x - half, right: row.screen.x + half, top: row.screen.y - half, bottom: row.screen.y + half });
      }
    }
    // Labels: attention first, then what is on; each takes the first side that covers no other
    // marker and no placed label, inside the canvas, or stays hidden until the camera comes closer.
    const rank = row => row.look === 'attention' ? 0 : row.look === 'on' ? 1 : 2;
    const taken = [];
    for (const row of [...rows].sort((a, b) => rank(a) - rank(b))) {
      const label = row.labelNode, at = row.screen;
      let spot = null;
      if (lod.labels && at?.front && row.labelBox) {
        const { w, h } = row.labelBox, half = MARKER_PX / 2;
        const sides = [[at.x + half + LABEL_GAP, at.y - h / 2], [at.x - half - LABEL_GAP - w, at.y - h / 2],
          [at.x - w / 2, at.y + half + LABEL_GAP], [at.x - w / 2, at.y - half - LABEL_GAP - h]];
        for (const [left, top] of sides) {
          const box = { left, top, right: left + w, bottom: top + h };
          if (left < 0 || top < 0 || box.right > rect.width || box.bottom > rect.height) continue;
          if (icons.some(icon => icon.row !== row && overlaps(icon, box)) || taken.some(other => overlaps(other, box))) continue;
          spot = box; break;
        }
      }
      label.hidden = !spot;
      if (spot) { taken.push(spot); label.style.left = `${spot.left}px`; label.style.top = `${spot.top}px`; }
    }
    const shownBadges = [];
    for (const badge of lod.badges) {
      const key = JSON.stringify([badge.building, badge.room]); visibleBadges.add(key);
      let sprite = badges.get(key);
      if (!sprite) { sprite = markerSprite(null); badges.set(key, sprite); root.add(sprite); }
      const members = shown.filter(row => row.building === badge.building && row.room === badge.room);
      sprite.position.set(0, 0, 0); members.forEach(row => sprite.position.add(row.sprite.position));
      sprite.position.divideScalar(members.length);
      sprite.material.map = texture('room', badge.attention ? 'attention' : 'off', badge.count);
      sprite.material.opacity = members.every(row => row.dim) ? .4 : 1;
      sprite.userData.room = { building: badge.building, room: badge.room };
      sprite.visible = true; place(sprite, BADGE_PX);
      shownBadges.push({ sprite, ...screen(sprite.position), dx: 0, dy: 0 });
    }
    // Small neighbouring rooms put their badges on top of each other far out: push them apart on
    // screen (sprite.center moves the drawn badge and its tap target together) so each stays legible.
    const apart = BADGE_PX + 4;
    for (let pass = 0; pass < 12; pass++) {
      let moved = false;
      for (let i = 0; i < shownBadges.length; i++) for (let j = i + 1; j < shownBadges.length; j++) {
        const a = shownBadges[i], b = shownBadges[j];
        let vx = b.x + b.dx - a.x - a.dx, vy = b.y + b.dy - a.y - a.dy, d = Math.hypot(vx, vy);
        if (d >= apart - .5) continue;
        if (d < .01) { const turn = (i + j) * 2.4; vx = Math.cos(turn); vy = Math.sin(turn); d = 1; }
        else { vx /= d; vy /= d; }
        const push = (apart - Math.max(d, .01)) / 2;
        a.dx -= vx * push; a.dy -= vy * push; b.dx += vx * push; b.dy += vy * push; moved = true;
      }
      if (!moved) break;
    }
    for (const b of shownBadges) b.sprite.center.set(.5 - b.dx / BADGE_PX, .5 + b.dy / BADGE_PX);
    badges.forEach((sprite, key) => { sprite.visible = visibleBadges.has(key); });
    root.updateMatrixWorld(true);
  }
  const drawn = () => new Promise(resolve => requestAnimationFrame(() => {
    if (!stopped) { draw(); view.render(); }
    resolve();
  }));
  async function poll(fresh) {
    if (stopped) return;
    try {
      const response = await api(`api/ha/card/states?fresh=${fresh ? 1 : 0}`, { signal: requests.signal });
      if (!response.ok) throw new Error('states unavailable');
      const body = await response.json();
      if (body.reachable === false || !body.states || typeof body.states !== 'object' || rows.length && !Object.keys(body.states).length)
        throw new Error('states unavailable');
      if (stopped) return;
      states = body.states; stale = false;
      for (const row of rows) {
        const state = states[row.entity_id];
        Object.assign(row, markerState(row.kind, state?.state ?? 'unavailable', state?.attributes));
      }
    } catch { if (!stopped) stale = true; }
    if (!stopped) { notify(); await drawn(); }
  }
  // Serialize polls: a pre-control response can never replace the fresh one.
  function refresh(fresh = false) {
    polling = polling.then(() => poll(fresh));
    return polling;
  }
  canvas.addEventListener('pointerdown', event => { pointer = { x: event.clientX, y: event.clientY, id: event.pointerId }; }, { signal: events.signal });
  canvas.addEventListener('pointerup', event => {
    const start = pointer; pointer = null;
    if (!start || start.id !== event.pointerId || Math.hypot(start.x - event.clientX, start.y - event.clientY) > 6) return;
    draw();
    const rect = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2), view.camera);
    const sprites = [...rows.map(row => row.sprite), ...badges.values()].filter(sprite => sprite.visible);
    const hit = raycaster.intersectObjects(sprites, false)[0]?.object;
    if (hit?.userData.deviceId) tap(rows.find(row => row.device_id === hit.userData.deviceId));
    else if (hit?.userData.room) {
      if (stale) window.showGlobalAlert(unreachable);
      else openRoom(hit.userData.room.building, hit.userData.room.room);
    } else {
      const room = view.pick(event.clientX, event.clientY);
      if (room?.kind === 'room') openRoom(room.building, room.id);
      else { closeSheet(); roomPanel?.close(); }
    }
  }, { signal: events.signal });
  canvas.addEventListener('pointercancel', () => { pointer = null; }, { signal: events.signal });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { closeSheet(); roomPanel?.close(); }
  }, { signal: events.signal });
  const live = {
    refresh, draw, control, openRoom,
    setMode(name) { mode = name === 'lights' ? 'lights' : null; modes?.setMode(mode); notify(); draw(); view.render(); },
    closeRoom() { roomPanel?.close(); closeSheet(); },
    markers: () => rows.map(plain),
    rooms: roomRows,
    devices: area => devices.filter(row => row.area_id === area).map(row => ({ ...row,
      ...markerState(row.kind, states[row.entity_id]?.state ?? 'unavailable', states[row.entity_id]?.attributes) })),
    states: () => structuredClone(states),
    layout: () => structuredClone(layout),
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    stop() {
      if (stopped) return;
      stopped = true; clearTimeout(timer); events.abort(); requests.abort(); listeners.clear();
      roomPanel?.stop(); modes?.stop();
      root.traverse(object => object.material?.dispose()); root.removeFromParent();
      textures.forEach(value => value.dispose()); textures.clear(); labels.remove(); sheet.remove();
    },
  };
  view.live = live;
  roomPanel = mountRoomPanel(live);
  modes = mountModes(view, live);
  await refresh();
  const schedule = () => { timer = setTimeout(async () => { await refresh(); if (!stopped) schedule(); }, 10000); };
  if (!stopped) schedule();
  return live;
}
