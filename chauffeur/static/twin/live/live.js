import * as THREE from 'three';
import { base } from '../twin_library.js';
import { groundAt } from '../twin_ground.js';
import { markerState, levelOfDetail, markerTexture, markerSprite } from './markers.js';

const FT = .3048, unreachable = 'Home Assistant is not reachable.';
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
    const { sprite, labelNode, ...data } = row;
    return { ...data, at: [...data.at], entities: [...data.entities] };
  };
  const roomRows = () => layout.rooms.filter(room => room.area_id).map(room => {
    const on = room.lights.map(id => states[id]).filter(state => state?.state === 'on');
    return { ...room, glow: on.length ? on.reduce((sum, state) => sum + (state.attributes?.brightness ?? 255) / 255, 0) / on.length : 0,
      rgb: on.find(state => Array.isArray(state.attributes?.rgb_color))?.attributes.rgb_color || null };
  });
  function notify() {
    for (const row of rows) {
      row.stale = stale; row.dim = stale || mode === 'lights' && row.kind !== 'light';
      row.sprite.material.map = texture(iconKind(row), row.look);
      row.sprite.material.opacity = row.dim ? .4 : 1;
      row.labelNode.textContent = `${row.name} · ${row.label}`;
      row.labelNode.style.opacity = row.dim ? '.4' : '1';
    }
    if (selected) showSheet(selected);
    listeners.forEach(listener => listener());
  }
  function closeSheet() { selected = null; sheet.hidden = true; sheet.replaceChildren(); }
  function showSheet(row) {
    selected = row; sheet.replaceChildren(); sheet.hidden = false;
    sheet.setAttribute('aria-label', row.name);
    const heading = document.createElement('h2'); heading.textContent = row.name;
    const status = document.createElement('p'); status.textContent = row.label;
    const actions = document.createElement('div'); actions.className = 'twin-device-actions';
    const button = (name, action) => {
      const node = document.createElement('button'); node.type = 'button'; node.textContent = name;
      node.addEventListener('click', action); actions.append(node);
    };
    if (row.offered) {
      const action = (name, service, confirm = false) => button(name, async () => {
        if (confirm && !await window.promptConfirm(`${name} ${row.name}?`, 'Are you sure?', name, 'Cancel')) return;
        closeSheet(); await control(row.entity_id, service);
      });
      if (row.kind === 'lock') { action('Lock', 'lock'); action('Unlock', 'unlock', true); }
      if (row.kind === 'garage') { action('Open', 'open_cover', true); action('Close', 'close_cover'); }
      if (iconKind(row) === 'alarm') {
        action('Arm home', 'alarm_arm_home'); action('Arm away', 'alarm_arm_away'); action('Disarm', 'alarm_disarm', true);
      }
    }
    button('Close', closeSheet);
    // Garage already has a Close action; the dismiss control has a distinct name.
    if (row.kind === 'garage' && row.offered) actions.lastChild.setAttribute('aria-label', 'Dismiss');
    sheet.append(heading, status, actions);
  }
  function openRoom(building, room, fallback) {
    closeSheet();
    const row = layout.rooms.find(r => r.building === building && r.room === room);
    const event = new CustomEvent('twinroom', { detail: row, cancelable: true });
    if (canvas.dispatchEvent(event) && fallback) showSheet(fallback);
  }
  async function control(entityId, service, data = {}) {
    if (stopped || busy.has(entityId)) return false;
    if (stale) { window.showGlobalAlert(unreachable); return false; }
    if (!rows.some(row => row.entity_id === entityId && row.offered
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
    const camera = view.camera, rect = canvas.getBoundingClientRect(); camera.updateMatrixWorld(true);
    const pixelSize = point => camera.isOrthographicCamera ? (camera.top - camera.bottom) / camera.zoom / Math.max(1, rect.height)
      : 2 * Math.max(.1, -point.clone().applyMatrix4(camera.matrixWorldInverse).z)
        * Math.tan(camera.fov * Math.PI / 360) / camera.zoom / Math.max(1, rect.height);
    const shown = rows.filter(row => view.groups?.levels[`${row.building}:${row.level}`]?.visible !== false);
    const lod = levelOfDetail(shown, FT / pixelSize(view.controls.target));
    const individual = new Set(lod.markers), visibleBadges = new Set();
    const place = (sprite, size = 34) => sprite.scale.setScalar(pixelSize(sprite.position) * size);
    for (const row of rows) {
      row.sprite.visible = individual.has(row.device_id); place(row.sprite);
      projected.copy(row.sprite.position).project(camera);
      const label = row.labelNode;
      label.hidden = !row.sprite.visible || !lod.labels || projected.z < -1 || projected.z > 1;
      if (!label.hidden) {
        label.style.left = `${(projected.x + 1) * rect.width / 2 + 22}px`;
        label.style.top = `${(1 - projected.y) * rect.height / 2}px`;
      }
    }
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
      sprite.visible = true; place(sprite, 40);
    }
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
      if (!body.states || typeof body.states !== 'object' || rows.length && !Object.keys(body.states).length)
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
    } else closeSheet();
  }, { signal: events.signal });
  canvas.addEventListener('pointercancel', () => { pointer = null; }, { signal: events.signal });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeSheet(); }, { signal: events.signal });
  const live = {
    refresh, draw, control, openRoom,
    setMode(name) { mode = name; notify(); draw(); },
    markers: () => rows.map(plain),
    rooms: roomRows,
    states: () => structuredClone(states),
    layout: () => structuredClone(layout),
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    stop() {
      if (stopped) return;
      stopped = true; clearTimeout(timer); events.abort(); requests.abort(); listeners.clear();
      root.traverse(object => object.material?.dispose()); root.removeFromParent();
      textures.forEach(value => value.dispose()); textures.clear(); labels.remove(); sheet.remove();
    },
  };
  view.live = live;
  await refresh();
  const schedule = () => { timer = setTimeout(async () => { await refresh(); if (!stopped) schedule(); }, 10000); };
  if (!stopped) schedule();
  return live;
}
