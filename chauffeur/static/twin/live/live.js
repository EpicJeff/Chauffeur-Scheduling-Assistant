import * as THREE from 'three';
import { base } from '../twin_library.js';
import { groundAt } from '../twin_ground.js';
import { markerState, levelOfDetail, markerTexture, markerSprite } from './markers.js';
import { deviceActions, confirmUnsafe, mountRoomPanel } from './room_panel.js';
import { roomStates, mountModes, modeForeground } from './modes.js';
import { kindOf, unsafeLabel } from './kinds.js';
import { mountRing } from './ring.js';
import { isEnergyEntity } from './glance.js';
import { mappedEntities } from './energy_mapping.js';

const FT = .3048, unreachable = 'Home Assistant is not reachable.';
// Screen sizes in CSS px: a marker is a 44 px tap target (the page's own controls' hit height),
// a room badge a little larger; labels never cover another marker or another label.
const MARKER_PX = 44, BADGE_PX = 52, LABEL_GAP = 4, LABEL_H = 23, LABEL_MAX = 190;
// A request that has not answered in this long has failed: the poll goes stale and a control
// says Home Assistant is not reachable, instead of waiting on a dead network for minutes.
const REQUEST_MS = 15000;
// Page chrome drawn over the scene: no label goes under it, and a marker under it gets none.
const OVERLAYS = '#twin-controls > *, #twin-tier, #twin-hud, #twin-status, #panel-shelf, #panel-chat-orb, #chat-overlay-container, [data-ring], [data-ring] .twin-ring-side';
let measurer = null;
function labelWidth(text) {
  measurer ||= document.createElement('canvas').getContext('2d');
  measurer.font = '12px system-ui';
  return Math.min(LABEL_MAX, Math.ceil(measurer.measureText(text).width) + 14);
}
const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
const iconKind = row => kindOf(row).id;
const report = error => console.error('[twin live]', error);

// A signal that aborts when the layer stops or after `ms`, whichever comes first.
function deadline(stop, ms) {
  if (typeof AbortSignal.any === 'function' && typeof AbortSignal.timeout === 'function')
    return { signal: AbortSignal.any([stop, AbortSignal.timeout(ms)]), done() {} };
  const controller = new AbortController(), abort = () => controller.abort();
  const timer = setTimeout(abort, ms);
  stop.addEventListener('abort', abort, { once: true });
  return { signal: controller.signal, done() { clearTimeout(timer); stop.removeEventListener('abort', abort); } };
}

function readOverlays() {
  if (typeof getComputedStyle !== 'function' || typeof document.querySelectorAll !== 'function') return [];
  return [...document.querySelectorAll(OVERLAYS)].flatMap(node => {
    const style = getComputedStyle(node);
    if (node.hidden || style.display === 'none' || style.visibility === 'hidden') return [];
    const r = node.getBoundingClientRect();
    return r.width && r.height ? [{ left: r.left, top: r.top, right: r.right, bottom: r.bottom }] : [];
  });
}

// One read of the layout: the answer, or null when it failed or timed out.
async function readLayout(api, stop) {
  const limit = deadline(stop, REQUEST_MS);
  try {
    const response = await api('api/house/live', { signal: limit.signal });
    return response.ok ? await response.json() : null;
  } catch { return null; } finally { limit.done(); }
}

// What a layer draws from a layout; a re-read that matches it changes nothing on screen.
const layoutKey = layout => JSON.stringify([
  (layout?.markers || []).map(m => [m.device_id, m.name, m.kind, m.entity_id, m.entities, m.building, m.level, m.room, m.at, m.facing_deg, m.orientation, m.outdoor, m.location_valid, m.placed, m.offered]),
  (layout?.rooms || []).map(r => [r.building, r.room, r.level, r.area_id, r.name, r.lights, r.polygon_world]),
  (layout?.devices || []).map(d => [d.device_id, d.name, d.kind, d.entity_id, d.entities, d.area_id, d.offered])]);

// The wall keeps its live layer without a reload. A layer that could not mount (Home Assistant
// away, a read that failed or timed out) is tried again every 45 s; a mounted one re-reads the
// layout every 5 minutes and remounts only when what it draws changed. One timer at a time.
export const LIVE_RETRY_MS = 45000, LIVE_LAYOUT_MS = 300000;
export function keepLive(view, { api = (path, options) => fetch(base() + path, options) } = {}) {
  const halt = new AbortController();
  let timer = null, busy = null, live = null, readAt = 0;
  const schedule = ms => { clearTimeout(timer); timer = halt.signal.aborted ? null : setTimeout(() => { timer = null; check(); }, ms); };
  function check() {
    if (halt.signal.aborted) return Promise.resolve(live);
    if (busy) return busy;
    clearTimeout(timer); timer = null;
    busy = (async () => {
      try {
        if (live && view.live !== live) live = null;
        if (!live) { live = await mountLive(view, { api }); return; }
        readAt = Date.now();
        const layout = await readLayout(api, halt.signal);
        // Away or failed: the mounted layer stays; its own poll already shows it stale.
        if (halt.signal.aborted || !layout?.available || layoutKey(layout) === layoutKey(live.layout())) return;
        const old = live; live = null;
        old.stop(); if (view.live === old) view.live = null;
        live = await mountLive(view, { api, layout });
      } catch (error) { report(error); }
      finally {
        busy = null;
        if (halt.signal.aborted) { live?.stop(); if (live && view.live === live) view.live = null; live = null; }
        else schedule(live ? LIVE_LAYOUT_MS : LIVE_RETRY_MS);
      }
    })();
    return busy.then(() => live);
  }
  // A server push may mean a placement changed; at most one extra read in 30 s.
  const pushed = () => { if (live && Date.now() - readAt > 30000) check(); };
  if (typeof document.addEventListener === 'function') document.addEventListener('chf-server-update', pushed, { signal: halt.signal });
  check();
  return {
    check,
    live: () => live,
    stop() { if (halt.signal.aborted) return; halt.abort(); clearTimeout(timer); timer = null; },
  };
}

export async function mountLive(view, { api = (path, options) => fetch(base() + path, options), layout = null } = {}) {
  const events = new AbortController(), requests = new AbortController();
  layout ||= await readLayout(api, requests.signal);
  if (!layout?.available || !view.ready) return null;

  const canvas = view.renderer3.domElement, host = canvas.parentElement;
  const root = new THREE.Group();
  const labels = document.createElement('div'); labels.className = 'twin-live-labels';
  const sheet = document.createElement('aside'); sheet.className = 'twin-device-sheet'; sheet.hidden = true;
  sheet.setAttribute('role', 'dialog');
  // A control's call on its way, per entity, and the newest press waiting behind it (C10).
  const textures = new Map(), badges = new Map(), listeners = new Set(), busy = new Set(), waiting = new Map();
  const raycaster = new THREE.Raycaster(), projected = new THREE.Vector3(), scratch = new THREE.Vector3();
  let states = {}, stopped = false, stale = true, mode = null, timer = null, polling = Promise.resolve();
  let stream = null, pollChanges = null, pushed = false, warned = false, energyStreamKey = '';
  let selected = null, sheetKey = null, sheetStatus = null;
  let roomPanel = null, modes = null, ring = null, rows = [], levelKeys = [], resizeObserver = null;
  // Layout runs only when something it reads changed (review M1): the camera, the canvas,
  // the shown levels, a poll or mode (revision), or the page's overlays.
  const lastCamera = new Float64Array(32);
  let revision = 0, lastKey = '', overlays = null;
  const texture = (kind, look, count = null) => {
    const key = JSON.stringify([kind, look, count]);
    if (!textures.has(key)) textures.set(key, markerTexture(kind, look, count));
    return textures.get(key);
  };
  const plain = row => {
    const { sprite, labelNode, labelBox, labelAt, screen, ...data } = row;
    return { ...data, at: [...data.at], entities: [...data.entities] };
  };
  const devices = layout.devices || layout.markers;
  const roomRows = () => roomStates(layout.rooms, states);
  const stateOf = row => markerState(row.kind, states[row.entity_id]?.state ?? 'unavailable',
    states[row.entity_id]?.attributes, row.entity_id);
  function notify() {
    revision++; overlays = null;
    for (const row of rows) {
      row.stale = stale; row.dim = stale || !modeForeground(mode, row, states[row.entity_id]);
      row.sprite.material.map = texture(iconKind(row), row.look);
      row.sprite.material.opacity = row.dim ? .4 : 1;
      const text = `${row.name} · ${row.label}`;
      if (row.labelNode.textContent !== text) { row.labelNode.textContent = text; row.labelBox = null; }
      row.labelBox ||= { w: labelWidth(text), h: LABEL_H };
      const opacity = row.dim ? '.4' : '1';
      if (row.labelNode.style.opacity !== opacity) row.labelNode.style.opacity = opacity;
    }
    flagFloors();
    if (selected) showSheet(selected);
    // One broken listener never stops the others, or the polls that follow (review M3).
    for (const listener of [...listeners]) { try { listener(); } catch (error) { report(error); } }
  }
  // Attention pushes through at every level (twin design 5.1): the floor picker flags each
  // floor holding something that wants attention, so a person looking elsewhere sees which.
  function flagFloors() {
    if (typeof document.querySelectorAll !== 'function') return;
    const flagged = new Set(stopped ? [] : rows.filter(row => row.look === 'attention').map(row => `${row.building}:${row.level}`));
    for (const button of document.querySelectorAll('#twin-views [data-view]')) {
      const on = flagged.has(button.dataset.view);
      if (on === button.hasAttribute('data-attention')) continue;
      if (on) { button.setAttribute('data-attention', ''); button.setAttribute('aria-label', `${button.textContent}, needs attention`); }
      else { button.removeAttribute('data-attention'); button.removeAttribute('aria-label'); }
    }
  }
  function closeSheet() { selected = null; sheetKey = null; sheetStatus = null; sheet.hidden = true; sheet.replaceChildren(); }
  // A poll only refreshes the open sheet's status line; its buttons are rebuilt only when the
  // device or what it offers changes, so a press that spans a poll still lands (review M2).
  function showSheet(row) {
    roomPanel?.close();
    const key = JSON.stringify([row.device_id, row.kind, row.offered]);
    selected = row; sheet.hidden = false;
    if (key === sheetKey && sheetStatus) {
      if (sheetStatus.textContent !== row.label) sheetStatus.textContent = row.label;
      return;
    }
    sheetKey = key; sheet.replaceChildren();
    sheet.setAttribute('aria-label', row.name);
    const heading = document.createElement('h2'); heading.textContent = row.name;
    const status = document.createElement('p'); status.textContent = row.label; sheetStatus = status;
    // control() asks before an unlock, an open or a disarm; the sheet never asks a second time.
    const act = Object.assign(async (...args) => { closeSheet(); return control(...args); }, { confirmsUnsafe: true });
    const actions = deviceActions(row, states[row.entity_id], act, { compact: true });
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
    ring?.close(); closeSheet();
    const row = layout.rooms.find(r => r.building === building && r.room === room);
    const event = new CustomEvent('twinroom', { detail: row, cancelable: true });
    if (canvas.dispatchEvent(event)) {
      if (row?.area_id) roomPanel?.open(row);
      else if (fallback) showSheet(fallback);
      else roomPanel?.close();
    }
  }
  // The one control path for every surface (marker sheet, room panel, a tap). It asks
  // before an unlock, an open or a disarm (review I1), and reads no state of its own.
  // An entity is busy only while its question and its call are out (Ruling C10, review
  // H2): a press meanwhile is not dropped but waits, the newest replacing any earlier one
  // (whose promise says false), and goes once the call has answered. An unsafe press
  // while busy is never queued: it would ask its question a second time.
  async function control(entityId, service, data = {}) {
    if (stopped) return false;
    if (stale) { window.showGlobalAlert(unreachable); return false; }
    const device = devices.find(row => row.offered && (row.entity_id === entityId || row.entities?.includes(entityId)));
    if (!device) return false;
    if (busy.has(entityId)) {
      if (unsafeLabel(device, service, data, states[entityId])) {
        window.showGlobalAlert(`Still working on ${device.name}…`);
        return false;
      }
      waiting.get(entityId)?.resolve(false);
      return new Promise(resolve => waiting.set(entityId, {service, data, resolve}));
    }
    busy.add(entityId);
    let sent = false, ok = false;
    try { ({sent, ok} = await send(device, entityId, service, data)); }
    finally {
      busy.delete(entityId);
      const next = waiting.get(entityId);
      if (next) { waiting.delete(entityId); control(entityId, next.service, next.data).then(next.resolve, () => next.resolve(false)); }
    }
    // The confirming poll runs with the entity free: a press during it is sent.
    if (sent && !stopped) await refresh(true);
    return ok;
  }
  control.confirmsUnsafe = true;
  async function send(device, entityId, service, data) {
    if (!await confirmUnsafe(device.name, service, device, data, states[entityId]) || stopped) return {sent: false, ok: false};
    if (stale) { window.showGlobalAlert(unreachable); return {sent: false, ok: false}; }
    try {
      const response = await window.chfControlFetch(base() + 'api/ha/card/service', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: entityId.split('.')[0], service, data: { ...data, entity_id: entityId } }),
        // Read when each request starts: chfControlFetch reads it again for its retry after
        // "Who's asking?", so the time a person takes over the PIN is never counted.
        get signal() { return deadline(requests.signal, REQUEST_MS).signal; },
      });
      if (stopped) return {sent: false, ok: false};
      if (response.status === 503) { stale = true; notify(); window.showGlobalAlert(unreachable); }
      else if (!response.ok && response.status !== 403 && !response.chfControlShown) {
        const body = await response.json().catch(() => ({}));
        window.showGlobalAlert(typeof body.detail === 'string' ? body.detail : 'Home Assistant could not finish that request.');
      }
      return {sent: true, ok: response.ok};
    } catch {
      if (!stopped) { stale = true; notify(); window.showGlobalAlert(unreachable); }
      return {sent: false, ok: false};
    }
  }
  function tap(row) {
    if (stale) { window.showGlobalAlert(unreachable); return; }
    if (!row.offered) { showSheet(row); return; }
    const service = kindOf(row).quick;
    if (service) { closeSheet(); void control(row.entity_id, service); }
  }
  function changed(camera, rect) {
    let moved = false;
    const take = (i, value) => { if (lastCamera[i] !== value) { lastCamera[i] = value; moved = true; } };
    camera.matrixWorld.elements.forEach((value, i) => take(i, value));
    camera.projectionMatrix.elements.forEach((value, i) => take(16 + i, value));
    const target = view.controls?.target;
    const key = [camera.uuid, rect.left, rect.top, rect.width, rect.height, target?.x, target?.y, target?.z, revision,
      levelKeys.map(level => view.groups?.levels[level]?.visible === false ? 0 : 1).join('')].join('|');
    if (key !== lastKey) { lastKey = key; moved = true; }
    return moved;
  }
  function setLabel(row, spot) {
    const label = row.labelNode, at = spot ? `${spot.left}px ${spot.top}px` : null;
    if (label.hidden !== !spot) label.hidden = !spot;
    if (!spot || row.labelAt === at) return;
    row.labelAt = at; label.style.left = `${spot.left}px`; label.style.top = `${spot.top}px`;
  }
  function draw() {
    if (stopped) return;
    modes?.draw();
    const camera = view.camera, rect = canvas.getBoundingClientRect(); camera.updateMatrixWorld(true);
    if (!changed(camera, rect)) return;
    overlays ||= readOverlays();
    const blocked = overlays.map(o => ({ left: o.left - rect.left, top: o.top - rect.top, right: o.right - rect.left, bottom: o.bottom - rect.top }));
    const pixelSize = point => camera.isOrthographicCamera ? (camera.top - camera.bottom) / camera.zoom / Math.max(1, rect.height)
      : 2 * Math.max(.1, -scratch.copy(point).applyMatrix4(camera.matrixWorldInverse).z)
        * Math.tan(camera.fov * Math.PI / 360) / camera.zoom / Math.max(1, rect.height);
    const levelShown = row => view.groups?.levels[`${row.building}:${row.level}`]?.visible !== false;
    const shown = rows.filter(levelShown);
    const lod = levelOfDetail(shown, FT / pixelSize(view.controls.target));
    // A marker that wants attention stays drawn on its own while its floor is hidden (twin design 5.1).
    const pinned = rows.filter(row => row.look === 'attention' && !levelShown(row)).map(row => row.device_id);
    const individual = new Set([...lod.markers, ...pinned]), visibleBadges = new Set();
    const place = (sprite, size) => sprite.scale.setScalar(pixelSize(sprite.position) * size);
    const screen = position => {
      projected.copy(position).project(camera);
      return { x: (projected.x + 1) * rect.width / 2, y: (1 - projected.y) * rect.height / 2,
        front: projected.z >= -1 && projected.z <= 1 };
    };
    const half = MARKER_PX / 2;
    const onCanvas = at => at.x >= -half && at.y >= -half && at.x <= rect.width + half && at.y <= rect.height + half;
    const covered = at => blocked.some(b => at.x >= b.left && at.x <= b.right && at.y >= b.top && at.y <= b.bottom);
    const icons = [];
    for (const row of rows) {
      row.sprite.visible = individual.has(row.device_id); row.sprite.center.set(.5, .5); place(row.sprite, MARKER_PX);
      row.screen = row.sprite.visible ? screen(row.sprite.position) : null;
      // Only on-screen icons can be covered by a label.
      if (row.screen?.front && onCanvas(row.screen))
        icons.push({ row, left: row.screen.x - half, right: row.screen.x + half, top: row.screen.y - half, bottom: row.screen.y + half });
    }
    // Labels: attention first, then what is on; each takes the first side that covers no other
    // marker, no placed label and none of the page's overlays, inside the canvas, or stays
    // hidden until the camera comes closer. A marker under an overlay gets no label.
    const rank = row => row.look === 'attention' ? 0 : row.look === 'on' ? 1 : 2;
    const taken = [];
    for (const row of [...rows].sort((a, b) => rank(a) - rank(b))) {
      const at = row.screen;
      let spot = null;
      if (lod.labels && at?.front && row.labelBox && onCanvas(at) && !covered(at)) {
        const { w, h } = row.labelBox;
        const sides = [[at.x + half + LABEL_GAP, at.y - h / 2], [at.x - half - LABEL_GAP - w, at.y - h / 2],
          [at.x - w / 2, at.y + half + LABEL_GAP], [at.x - w / 2, at.y - half - LABEL_GAP - h]];
        for (const [left, top] of sides) {
          const box = { left, top, right: left + w, bottom: top + h };
          if (left < 0 || top < 0 || box.right > rect.width || box.bottom > rect.height) continue;
          if (blocked.some(other => overlaps(other, box))) continue;
          if (icons.some(icon => icon.row !== row && overlaps(icon, box)) || taken.some(other => overlaps(other, box))) continue;
          spot = box; break;
        }
      }
      if (spot) taken.push(spot);
      setLabel(row, spot);
    }
    const members = new Map();
    for (const row of shown) {
      const key = JSON.stringify([row.building, row.room]);
      if (!members.has(key)) members.set(key, []);
      members.get(key).push(row);
    }
    const shownBadges = [];
    for (const badge of lod.badges) {
      const key = JSON.stringify([badge.building, badge.room]); visibleBadges.add(key);
      let sprite = badges.get(key);
      if (!sprite) { sprite = markerSprite(null); badges.set(key, sprite); root.add(sprite); }
      const inRoom = members.get(key) || [];
      sprite.position.set(0, 0, 0); inRoom.forEach(row => sprite.position.add(row.sprite.position));
      sprite.position.divideScalar(Math.max(1, inRoom.length));
      sprite.material.map = texture('room', badge.attention ? 'attention' : 'off', badge.count);
      sprite.material.opacity = inRoom.every(row => row.dim) ? .4 : 1;
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
    ring?.draw();
  }
  // Resolves whatever the frame does: a throw in draw or render never strands a poll (review M3).
  const drawn = () => new Promise(resolve => requestAnimationFrame(() => {
    try { if (!stopped) { draw(); view.render(); } }
    catch (error) { report(error); }
    finally { resolve(); }
  }));
  async function poll(fresh) {
    if (stopped) return;
    pollChanges = new Map();
    const limit = deadline(requests.signal, REQUEST_MS);
    try {
      const response = await api(`api/ha/card/states?fresh=${fresh ? 1 : 0}`, { signal: limit.signal });
      if (!response.ok) throw new Error('states unavailable');
      const body = await response.json();
      // reachable:false is the route serving a stale or empty copy because Home Assistant did
      // not answer (Ruling Q13); an empty answer while markers exist is the same (Q12).
      if (body.reachable === false || !body.states || typeof body.states !== 'object' || rows.length && !Object.keys(body.states).length)
        throw new Error('states unavailable');
      if (stopped) return;
      states = body.states; stale = false;
      // Pushes received during this request are newer than its snapshot.
      for (const [entityId, state] of pollChanges) {
        if (state === null) delete states[entityId];
        else states[entityId] = state;
      }
      for (const row of rows) Object.assign(row, stateOf(row));
    } catch { if (!stopped) stale = true; } finally { pollChanges = null; limit.done(); }
    if (stopped) return;
    try { notify(); } catch (error) { report(error); }
    await drawn();
  }
  // Serialize polls: a pre-control response can never replace the fresh one. A poll that
  // failed never blocks the next.
  function refresh(fresh = false) {
    polling = polling.catch(report).then(() => poll(fresh));
    return polling;
  }
  // Pushes are drawn once per frame (review M3): a burst of pushes is one restate, one
  // notify and one render, never one of each per push.
  function flushPushes() {
    pushed = false;
    if (stopped) return;
    for (const row of rows) Object.assign(row, stateOf(row));
    try { notify(); } catch (error) { report(error); }
    try { draw(); view.render(); } catch (error) { report(error); }
  }
  function subscribeStates() {
    if (stopped || stream || typeof EventSource !== 'function') return;
    const entities = new Set([...Object.keys(states), ...(live.glanceEntities || []), ...mappedEntities(view.energySources?.mapping), ...rows.map(row => row.entity_id), ...devices.flatMap(row => row.entities || [row.entity_id]),
      ...(layout.rooms || []).flatMap(room => room.lights || [])].filter(Boolean));
    if (!entities.size) return;
    try {
      // No entity list in the URL (Ruling C11): the server derives the house's set from
      // its placements; this layer still applies only what it draws.
      const url = base() + 'api/ha/stream';
      stream = new EventSource(window.chfAuthUrl ? window.chfAuthUrl(url) : url);
      stream.onmessage = event => {
        if (stopped) return;
        let change;
        try { change = JSON.parse(event.data); } catch { return; }
        if (!change || typeof change.entity_id !== 'string' ||
          !(entities.has(change.entity_id) || mappedEntities(view.energySources?.mapping).includes(change.entity_id) ||
          view.plan?.buildings?.some(b=>b.solar_zones?.some(z=>z.state!=='ghost' && z.entity===change.entity_id)) || change.entity_id.startsWith('weather.') || isEnergyEntity(change.entity_id, change.state)) || !Object.hasOwn(change, 'state')) return;
        const state = change.state;
        if (state !== null && (typeof state !== 'object' || Array.isArray(state) || typeof state.state !== 'string')) return;
        if (state === null) delete states[change.entity_id];
        else states[change.entity_id] = state;
        pollChanges?.set(change.entity_id, state);
        stale = false;
        if (!pushed) { pushed = true; requestAnimationFrame(flushPushes); }
      };
      // EventSource retries transient drops itself; the poll stays armed even
      // if the browser closes this stream permanently (for example after a 401),
      // and that is said once in the console rather than not at all.
      stream.onerror = () => {
        if (warned || stopped || stream?.readyState !== 2) return;
        warned = true;
        console.warn('[twin live] the state stream was refused; changes arrive with the 10 s poll.');
      };
    } catch { /* Polling is also the path for browsers that cannot open a stream. */ }
  }
  function stop() {
    if (stopped) return;
    stopped = true; view.glance?.attach(null); clearTimeout(timer); events.abort(); requests.abort(); listeners.clear();
    stream?.close(); stream = null;
    try { flagFloors(); } catch (error) { report(error); }
    resizeObserver?.disconnect();
    for (const part of [ring, roomPanel, modes]) { try { part?.stop(); } catch (error) { report(error); } }
    root.traverse(object => object.material?.dispose()); root.removeFromParent();
    textures.forEach(value => value.dispose()); textures.clear(); labels.remove(); sheet.remove();
  }
  function hitMarker(event) {
    draw();
    const rect = canvas.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
    return rows.filter(row => row.screen?.front && Math.abs(row.screen.x - x) <= MARKER_PX / 2 &&
      Math.abs(row.screen.y - y) <= MARKER_PX / 2)
      .sort((a, b) => Math.hypot(a.screen.x - x, a.screen.y - y) - Math.hypot(b.screen.x - x, b.screen.y - y))[0];
  }
  function tapScene(event) {
    draw();
    const rect = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2), view.camera);
    const sprites = [...badges.values()].filter(sprite => sprite.visible);
    const hit = raycaster.intersectObjects(sprites, false)[0]?.object;
    if (hit?.userData.room) {
      if (stale) window.showGlobalAlert(unreachable);
      else openRoom(hit.userData.room.building, hit.userData.room.room);
    } else {
      const room = view.pick(event.clientX, event.clientY);
      if (room?.kind === 'room') openRoom(room.building, room.id);
      else { closeSheet(); roomPanel?.close(); }
    }
  }
  const live = {
    refresh, draw, control, openRoom, stop,
    configureGlance(tiles) {
      live.glanceEntities = (tiles || []).map(tile => typeof tile === 'string' ? tile : tile.entity);
      const key = JSON.stringify(live.glanceEntities);
      if (key === live.glanceStreamKey) return;
      live.glanceStreamKey = key; stream?.close(); stream = null; subscribeStates();
    },
    // From the room panel: the ring takes the keyboard focus, and gives it back (review L7).
    openRing: row => { const from = document.activeElement; roomPanel?.close(); ring?.open(row, {focus: from}); },
    ring: () => ring?.current() || null,
    setMode(name) { mode = modes?.setMode(name || 'all') || 'all'; notify(); draw(); view.render(); },
    closeRoom() { ring?.close(); roomPanel?.close(); closeSheet(); },
    markers: () => rows.map(plain),
    marker: id => { const row = rows.find(row => row.device_id === id); return row ? plain(row) : null; },
    rooms: roomRows,
    lights: () => modes?.lights() || [],
    energy: () => modes?.energy(),
    configureEnergy(value) {
      const nextKey = JSON.stringify([value.mapping, value.cars]);
      view.energySources = value; modes?.update(); view.glance?.update();
      // The server derives stream scope at connection time. A corrected mapping
      // must reconnect so newly chosen, unusually named entities push too.
      if (nextKey !== energyStreamKey) {energyStreamKey = nextKey; stream?.close(); stream = null; subscribeStates();}
      view.render();
    },
    devices: area => devices.filter(row => row.area_id === area).map(row => ({ ...row, ...stateOf(row) })),
    states: () => structuredClone(states),
    // Reads without a copy, for listeners that run on every push (review M3): never
    // written to by a reader.
    state: id => states[id],
    peek: () => states,
    stale: () => stale,
    layout: () => structuredClone(layout),
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  };
  view.live = live;
  // A layout the layer cannot draw (say a malformed spot) takes down only the layer: everything
  // it built so far is removed and the house carries on without markers (review M5).
  try {
    view.scene.add(root); host.append(labels); document.body.append(sheet);
    rows = layout.markers.map(marker => {
      const sprite = markerSprite(texture(iconKind(marker), 'unavailable'));
      sprite.userData.deviceId = marker.device_id;
      const building = view.plan.buildings.find(b => b.id === marker.building);
      const ground = groundAt(view.plan, ...(building?.position || [0, 0]));
      sprite.position.set(marker.at[0] * FT, (marker.at[2] + ground) * FT, -marker.at[1] * FT);
      root.add(sprite);
      const label = document.createElement('span'); labels.append(label);
      return { ...marker, ...markerState(marker.kind, 'unknown'), stale: true, dim: true, sprite, labelNode: label };
    });
    levelKeys = [...new Set(rows.map(row => `${row.building}:${row.level}`))];
    // A rebuild redraws the floor picker's buttons; flag them again.
    host?.addEventListener?.('twinrebuilt', () => queueMicrotask(flagFloors), { signal: events.signal });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') { closeSheet(); roomPanel?.close(); }
    }, { signal: events.signal });
    // The overlays are read again only when the page resizes, the controls reflow, or a poll lands.
    const reflow = () => { overlays = null; lastKey = ''; };
    if (typeof window.addEventListener === 'function') window.addEventListener('resize', reflow, { signal: events.signal });
    if (typeof ResizeObserver === 'function') {
      resizeObserver = new ResizeObserver(reflow);
      for (const id of ['twin-controls', 'panel-shelf']) { const node = document.getElementById(id); if (node) resizeObserver.observe(node); }
    }
    roomPanel = mountRoomPanel(live);
    modes = mountModes(view, live);
    ring = mountRing(view, live, {hit: hitMarker, tap, scene: tapScene,
      dismiss() { closeSheet(); roomPanel?.close(); },
      // The open ring is one of the page's overlays: the next frame places labels around it.
      moved() { overlays = null; lastKey = ''; },
      position(id) {
        const row = rows.find(row => row.device_id === id), rect = canvas.getBoundingClientRect();
        return row?.screen?.front ? {x: row.screen.x + rect.left, y: row.screen.y + rect.top} : null;
      }});
  } catch (error) {
    report(error); stop();
    if (view.live === live) view.live = null;
    return null;
  }
  await refresh();
  view.glance?.attach(live);
  view.glanceSettings?.refreshChoices();
  view.energySettings?.refreshChoices();
  subscribeStates();
  const schedule = () => {
    timer = setTimeout(async () => {
      try { await refresh(); } catch (error) { report(error); } finally { if (!stopped) schedule(); }
    }, 10000);
  };
  if (!stopped) schedule();
  return live;
}
