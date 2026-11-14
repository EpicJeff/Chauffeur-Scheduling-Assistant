import { objectOperation, transformObject } from '../objects.js';
import { isObject } from './object_shelf.js';
import { report, idleInterval } from './api.js';
import { createCards, findPiece, feetInches } from './cards.js';
import { createHaLink } from './ha_link.js';
import { snapPoint, snapRotation } from './snap.js';
import { sheetMaster, localCentre } from './words.js';
import { createSelection } from './selection.js';
import { createDrag } from './drag.js';
import { createDimensions } from './dimensions.js';
import { createHandles } from './handles.js';
import { contains } from '../twin_generator.js';

const rotatePoint = (p, angle) => {
  const a = angle * Math.PI / 180;
  return [Math.cos(a) * p[0] - Math.sin(a) * p[1], Math.sin(a) * p[0] + Math.cos(a) * p[1]];
};

export function createSceneTools({ view, getPlan, getModel, getKit, getSheets, edit, op, panel, canEdit, signal, onInteract, addDormer, pickSite, pickMaterial, api, onDrawFeature }) {
  const el = id => document.getElementById(id), canvas = view.renderer3.domElement;
  let selection = null, tool = 'select', levelKey = null, sheetOn = false, gesture = null, delegate = null, pointerId = null;
  let ownsGesture = false, handles = null;
  let roofRooms = new Set(), roofRoomBuilding = null;
  const pointers = new Set();
  const dimensions = createDimensions({ view, onCommit: op, canEdit, signal, getHandles: () => handles?.handles() || [] });
  function drawDimensions(plan = getPlan(), state = roomSelection.current()) {
    const building = plan?.buildings.find(b => b.id === state.building);
    dimensions.show({ building, piece: building?.walls.find(w => state.kind === 'wall' && w.id === state.id),
      room: building?.rooms.find(r => r.id === state.room) });
  }
  const drag = createDrag({ view, model: getPlan, onPreview(plan, state) {
    handles?.show(plan); drawDimensions(plan, state);
  }, onCommit(operation) {
    if (operation.op === 'move_wall') {
      const wall = getPlan().buildings.find(b => b.id === operation.building).walls.find(w => w.id === operation.wall);
      const d = wall.to.map((v, i) => v - wall.from[i]), length = Math.hypot(...d);
      operation = { ...operation, by: (-d[1] * operation.by[0] + d[0] * operation.by[1]) / length };
    }
    return op(operation);
  } });
  const getLabel = item => getSheets().piece_labels?.find(p => p.piece === item.pieceId && p.building === item.buildingId)?.label || 'this piece';
  const roomSelection = createSelection({ view, getModel, onChange(state) {
    if (!state.room || state.building !== roofRoomBuilding || !roofRooms.has(state.room)) {
      roofRooms = new Set(state.room ? [state.room] : []); roofRoomBuilding = state.building;
    }
    selection = state.id ? { pieceId: state.id, buildingId: state.building, kind: state.kind, room: state.room } : null;
    if (!selection) panel.clearSelection();
    if (state.level) levelKey = `${state.building}:${state.level}`;
    cards.draw(selection);
    handles?.refresh();
    drawDimensions(getPlan(), state);
  } });
  // Area picks and placements wait behind the card's own field saves (cards.queue).
  const haLink = createHaLink({ api, onCommit: operation => cards.queue(() => op(operation)), signal, getPlan, canEdit });
  let linkReadAt = 0;
  const cards = createCards({ getPlan, getKit, getLabel, getSelection: roomSelection.current, getFieldLabels: () => getSheets().field_labels || {}, edit: change => change.op === 'set' && change.field === 'rotation'
    ? rotate(change.building, change.value - (getPlan().buildings.find(b => b.id === change.building)?.rotation || 0)) : edit(change),
    op, addDormer, canEdit, select, pickMaterial, haLink, onDrawFeature, preview: plan => view.rebuild(plan, { preserveYard: true }), ask: item => panel.focusSelection(item, getLabel(item)) });
  handles = createHandles({ view, getPlan, getSelection: roomSelection.current, canEdit, drag, onCommit: op,
    onPreview: drawDimensions, onClick: cards.edge, signal });
  const hasHandles = ({ kind, piece, building }) => piece.state !== 'ghost'
    && (['wall', 'joint', 'room', 'roof', 'dormer', 'solar_zone', 'stair'].includes(kind)
      || kind === 'opening' && building.walls.some(w => w.id === piece.wall)
      || ['anchor', 'item'].includes(kind) && !!piece.host);
  const listen = (node, event, fn, options = {}) => node.addEventListener(event, fn, { ...options, signal });
  function levels() {
    const buildings = getPlan()?.buildings || [];
    return buildings.flatMap(b => [...b.levels].sort((a, c) => a.elevation - c.elevation)
      .map((l, i) => ({ key: `${b.id}:${l.id}`, building: b, level: l,
        label: (buildings.length > 1 ? `${b.name || b.id} \u00b7 ` : '') + (l.name || `Floor ${i + 1}`) })));
  }
  function floor() {
    const list = levels();
    return list.find(l => l.key === levelKey) || list[0];
  }
  function select(item) {
    if (!canEdit() && item) return;
    if (!item) { roomSelection.clear(); return; }
    const record = findPiece(getPlan(), item.id ?? item.pieceId, item.building ?? item.buildingId);
    if (!record) return;
    if (!record.building) {
      roomSelection.clear(); roomSelection.select({ kind: record.kind, id: record.piece.id }); return;
    }
    const level = record.kind === 'level' ? record.piece.id : record.piece.level
      || record.building.walls.find(w => w.id === (record.piece.wall || record.piece.host?.wall))?.level;
    if (['roof', 'dormer', 'solar_zone'].includes(record.kind) && roomSelection.current().room) roomSelection.clear();
    roomSelection.select({ kind: record.kind, id: record.piece.id, building: record.building.id, level });
  }
  function pick(x, y) {
    const proposed = delegate?.pick?.(x, y);
    if (proposed) return proposed;
    const site = pickSite?.(x, y); if (site) return site;
    let item = view.pick(x, y);
    if (item?.kind === 'roof') {
      const building = getPlan()?.buildings.find(b => b.id === item.building);
      const section = building?.roof?.sections.find(s => s.id === item.id);
      const dormer = building?.dormers?.find(d => d.id === item.id);
      if (dormer) return { ...item, kind: 'dormer', level: section?.level };
      if (section?.roof) item = { ...item, id: section.roof, pieceId: section.roof, level: section.level };
    }
    const record = item?.kind === 'roof' && findPiece(getPlan(), item.id, item.building);
    const markedRoof = record && (record.piece.state === 'ghost' || record.piece.block
      && record.building.roof.flags?.some(flag => flag.block_rect?.length === 4
        && flag.block_rect.every((v, i) => Math.abs(v - record.piece.block[i]) <= 1)));
    // Existing needs-checking markers still open their own correction card.
    if (item && !['solar_zone','anchor'].includes(item.kind) && !markedRoof && view.state.view === 'ext' && !roomSelection.current().id)
      return { kind: 'building', id: item.building, building: item.building, level: null };
    return item;
  }
  function setTool(name) {
    if (name !== 'select') haLink.cancelPlacement();
    tool = name; onInteract?.();
    for (const id of ['select', 'move', 'rotate', 'draw-room', 'draw-wall', 'split-room', 'add-door', 'add-window', 'add-anchor', 'add-stair', 'add-solar-zone', 'add-meter', 'add-electric-panel', 'add-charger', 'add-parking']) el(`rail-${id}`).setAttribute('aria-pressed', String(id === name));
    canvas.style.cursor = name === 'move' ? 'grab' : name === 'select' ? '' : 'crosshair';
  }
  async function sheet(key = floor()?.key, show = !sheetOn) {
    const target = levels().find(l => l.key === key); if (!target) return;
    sheetOn = show; el('rail-sheet').setAttribute('aria-pressed', String(show));
    if (!show) { view.setSheet(null); return; }
    const sheets = getSheets();
    const registration = sheets.registrations?.find(row => row.level === target.level.id && sheets.page_roles.some(role =>
      role.source === row.source && role.page === row.page && (role.building || 'house') === target.building.id));
    if (!registration) {
      sheetOn = false; el('rail-sheet').setAttribute('aria-pressed', 'false');
      panel.message('This floor does not have a lined-up drawing yet. Check its outline with Argyle first.'); return;
    }
    let url = (window.chfBase ?? '../') + `api/house/editor/sheets/${encodeURIComponent(registration.source)}/${registration.page}.png`;
    if (window.chfAuthUrl) url = window.chfAuthUrl(url);
    view.setSheet({ url, buildingId: target.building.id, levelId: target.level.id, reg: registration.reg,
      masterSize: sheetMaster(sheets, registration.source, registration.page) });
  }
  function chooseFloor(key) {
    levelKey = key; onInteract?.(); view.setView(key); view.showLevels([key]);
    roomSelection.clear();
    const target = levels().find(row => row.key === key);
    if (target) select({ pieceId: target.level.id, buildingId: target.building.id });
    if (sheetOn) sheet(key, true).catch(report);
    delegate?.floorChanged?.(); drawFloors();
  }
  function drawFloors() {
    const host = el('editor-floors'), focused = document.activeElement?.dataset.floor;
    const signature = JSON.stringify(levels().map(row => [row.key, row.label]));
    if (host.dataset.levels !== signature) {
      host.dataset.levels = signature; host.replaceChildren();
      const title = document.createElement('span'); title.textContent = 'Floors'; host.append(title);
      for (const row of levels().reverse()) {
        const group = document.createElement('div'); group.className = 'editor-floor-row';
        const button = document.createElement('button'); button.type = 'button'; button.dataset.floor = row.key;
        button.textContent = row.label; button.addEventListener('click', () => chooseFloor(row.key));
        const toggle = document.createElement('button'); toggle.type = 'button'; toggle.dataset.floorVisible = row.key;
        toggle.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>';
        toggle.setAttribute('aria-label', `Show ${row.label}`);
        toggle.addEventListener('click', () => {
          onInteract?.();
          toggle.setAttribute('aria-pressed', String(toggle.getAttribute('aria-pressed') !== 'true'));
          const keys = [...host.querySelectorAll('[data-floor-visible][aria-pressed="true"]')].map(node => node.dataset.floorVisible);
          view.showLevels(keys); drawFloors();
        });
        group.append(toggle, button); host.append(group);
        if (focused === row.key) button.focus({ preventScroll: true });
      }
      const all = document.createElement('button'); all.type = 'button'; all.textContent = 'All floors';
      all.addEventListener('click', () => {
        onInteract?.();
        if (!['roof', 'dormer'].includes(roomSelection.current().kind)) roomSelection.clear();
        view.setView('ext'); view.showLevels(null);
        view.setEditableLevel(null).catch(report); drawFloors();
      }); host.append(all);
      for (const kind of ['Floor', 'Building']) {
        const details = document.createElement('button'); details.type = 'button'; details.textContent = kind === 'Floor' ? 'Change this floor' : 'Change the house';
        details.addEventListener('click', () => {
          const target = floor(); if (!target) return;
          onInteract?.(); select({ pieceId: kind === 'Floor' ? target.level.id : target.building.id, buildingId: target.building.id });
        }); host.append(details);
      }
      if (!levels().length) { const note = document.createElement('p'); note.textContent = 'No floors yet'; host.append(note); }
    }
    host.querySelectorAll('[data-floor]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.floor === floor()?.key)));
    host.querySelectorAll('[data-floor-visible]').forEach(node => node.setAttribute('aria-pressed', String(!!view.groups?.levels[node.dataset.floorVisible]?.visible)));
  }
  function pieceAnchor(item) {
    const record = findPiece(getPlan(), item.pieceId, item.buildingId); if (!record) return null;
    const { piece, building, kind } = record;
    const level = piece.level || building.walls.find(w => w.id === piece.wall)?.level || building.levels[0]?.id;
    const points = piece.from ? [piece.from, piece.to] : piece.polygon || piece.rect && [[piece.rect[0], piece.rect[1]], [piece.rect[2], piece.rect[3]]];
    const wall = kind === 'opening' && building.walls.find(w => w.id === piece.wall);
    const length = wall && Math.hypot(wall.to[0] - wall.from[0], wall.to[1] - wall.from[1]);
    const point = wall && length ? wall.from.map((v, i) => v + (wall.to[i] - v) * piece.at / length)
      : piece.from || (points?.length ? [0, 1].map(axis => points.reduce((n, p) => n + p[axis], 0) / points.length) : piece.position || [0, 0]);
    return { point, key: `${building.id}:${level}`, record };
  }
  async function move(item, from, to) {
    if (!canEdit() || !from || !to) return;
    const anchor = pieceAnchor(item); if (!anchor) return;
    const walls = anchor.record.building.walls.filter(w => w.level === anchor.key.slice(item.buildingId.length + 1) && w.id !== item.pieceId);
    const by = [to[0] - from[0], to[1] - from[1]];
    const { kind, piece, building } = anchor.record;
    if (hasHandles(anchor.record)) return;
    let destination = anchor.point.map((v, i) => v + by[i]);
    if (kind === 'opening') {
      const wall = building.walls.find(w => w.id === piece.wall); if (!wall) return;
      const d = wall.to.map((v, i) => v - wall.from[i]), length = Math.hypot(...d);
      const at = Math.max(piece.width / 2, Math.min(length - piece.width / 2, destination.reduce((n, v, i) => n + (v - wall.from[i]) * d[i] / length, 0)));
      destination = wall.from.map((v, i) => v + d[i] * at / length);
    } else destination = snapPoint(destination, walls, { exclude: kind === 'wall' ? [piece.from, piece.to] : [] });
    const delta = destination.map((v, i) => v - anchor.point[i]);
    if (Math.hypot(...delta) < .001) return;
    await edit({ op: 'move', piece: item.pieceId, building: item.buildingId, by: delta }); cards.draw(selection);
  }
  async function rotate(buildingId, delta) {
    if (!canEdit()) return;
    const building = getPlan()?.buildings.find(b => b.id === buildingId); if (!building) return;
    const to = snapRotation((building.rotation || 0) + delta);
    if (Math.abs(to - (building.rotation || 0)) < .001) return;
    await edit({ op: 'rotate', building: buildingId, to, about: localCentre(building) }); cards.draw(selection);
  }
  async function dragPiece(pieceId, buildingId, dx, dy) {
    const item = { pieceId, buildingId }; select(item);
    const anchor = pieceAnchor(item); if (!anchor) return;
    if (hasHandles(anchor.record)) return;
    const p = view.screenOfFloor(...anchor.point, anchor.key); if (!p) return;
    await move(item, view.floorAt(...p, anchor.key), view.floorAt(p[0] + dx, p[1] + dy, anchor.key));
  }
  // Capture before OrbitControls so a floor drag never turns into a camera drag.
  listen(canvas, 'pointerdown', event => {
    pointers.add(event.pointerId);
    if (pointerId !== null) {
      if (ownsGesture) event.stopImmediatePropagation();
      else { gesture = null; pointerId = null; } // A pinch cancels the passive tap.
      return;
    }
    if (pointers.size > 1) return;
    if (event.button !== 0 || !canEdit()) return;
    pointerId = event.pointerId;
    if (delegate?.pointerDown?.(event)) { ownsGesture = true; event.stopImmediatePropagation(); return; }
    if (event.shiftKey && tool === 'select' && !handles.hit(event)) {
      gesture = { x: event.clientX, y: event.clientY, pointerId, selecting: true, addRoom: true }; return;
    }
    if (handles.begin(event)) {
      gesture = { x: event.clientX, y: event.clientY, pointerId, dragging: true, enabled: view.controls.enabled };
      ownsGesture = true; onInteract?.(); view.controls.enabled = false;
      canvas.setPointerCapture(event.pointerId); event.stopImmediatePropagation(); return;
    }
    if (tool === 'select') {
      gesture = { x: event.clientX, y: event.clientY, pointerId, selecting: true }; return;
    }
    let picked = view.pick(event.clientX, event.clientY);
    if (picked && view.state.view === 'ext' && ['building', null].includes(roomSelection.current().kind))
      picked = { pieceId: picked.buildingId, buildingId: picked.buildingId, kind: 'building' };
    if (!picked || !findPiece(getPlan(), picked.pieceId, picked.buildingId)) return;
    onInteract?.(); select(picked);
    const anchor = pieceAnchor(picked); if (!anchor) return;
    if (hasHandles(anchor.record)) {
      gesture = { x: event.clientX, y: event.clientY, pointerId, selecting: true }; return;
    }
    const start = view.floorAt(event.clientX, event.clientY, anchor.key); if (!start) return;
    const centre = localCentre(anchor.record.building);
    gesture = { item: picked, start, key: anchor.key, centre, pointerId, x: event.clientX, y: event.clientY, enabled: view.controls.enabled };
    ownsGesture = true;
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); event.stopImmediatePropagation();
  }, { capture: true });
  listen(canvas, 'pointermove', event => {
    if (pointerId === null && tool === 'select' && canEdit()) roomSelection.hover(pick(event.clientX, event.clientY));
    if (event.pointerId !== pointerId) return;
    if (delegate?.pointerMove?.(event)) return;
    if (!gesture || gesture.selecting) return;
    if (gesture.dragging) {
      if (gesture.moved || Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) >= 3) {
        gesture.moved = true;
        try { handles.update(event); } catch (error) { finish(event, true); report(error); }
      }
      return;
    }
    const end = view.floorAt(event.clientX, event.clientY, gesture.key); if (!end) return;
    const hint = el('editor-drag-hint'); hint.hidden = false; hint.style.left = `${event.clientX + 18}px`; hint.style.top = `${event.clientY + 18}px`;
    hint.textContent = tool === 'move' ? `${feetInches(Math.hypot(end[0] - gesture.start[0], end[1] - gesture.start[1]))} along the floor` : `${Math.round(turn(gesture, end))}°`;
    const record = findPiece(getPlan(), gesture.item.pieceId, gesture.item.buildingId);
    const piece = record?.piece;
    let outline = piece?.polygon || (piece?.from ? [piece.from, piece.to] : null);
    if (piece?.rect) { const [x0, y0, x1, y1] = piece.rect; outline = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]; }
    if (tool === 'rotate') outline = record?.building.levels[0]?.outline || record?.building.walls.flatMap(w => [w.from, w.to]);
    if (outline) {
      const angle = (snapRotation((record.building.rotation || 0) + turn(gesture, end)) - (record.building.rotation || 0)) * Math.PI / 180;
      const points = outline.map(point => {
        if (tool === 'move') return point.map((v, i) => v + end[i] - gesture.start[i]);
        const x = point[0] - gesture.centre[0], y = point[1] - gesture.centre[1];
        return [gesture.centre[0] + Math.cos(angle) * x - Math.sin(angle) * y, gesture.centre[1] + Math.sin(angle) * x + Math.cos(angle) * y];
      }).map(p => view.screenOfFloor(...p, gesture.key)).filter(Boolean);
      el('editor-drag-outline').setAttribute('points', points.map(p => p.join(',')).join(' '));
    }
  });
  function turn(g, end) {
    let delta = (Math.atan2(end[1] - g.centre[1], end[0] - g.centre[0]) - Math.atan2(g.start[1] - g.centre[1], g.start[0] - g.centre[0])) * 180 / Math.PI;
    delta = (delta + 540) % 360 - 180; return delta;
  }
  const finish = (event, cancel = false) => {
    const tracked = pointers.delete(event.pointerId);
    if (event.pointerId !== pointerId) { if (ownsGesture && tracked) event.stopImmediatePropagation(); return; }
    pointerId = null; ownsGesture = false;
    if (delegate?.pointerUp?.(event, cancel)) return;
    if (!gesture) return;
    const g = gesture; gesture = null; el('editor-drag-hint').hidden = true;
    if (g.dragging) {
      view.controls.enabled = g.enabled;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      handles.finish(cancel || !g.moved, !cancel && !g.moved).catch(report); return;
    }
    if (g.selecting) {
      if (!cancel && Math.hypot(event.clientX - g.x, event.clientY - g.y) < 3) {
        onInteract?.();
        if (g.addRoom) {
          const target = floor(), p = target && view.floorAt(event.clientX, event.clientY, target.key);
          const room = p && target.building.rooms.find(r => r.level === target.level.id && r.state !== 'ghost' && contains(r.polygon, p));
          if (room) {
            if (roofRoomBuilding !== target.building.id || !roofRooms.size) roomSelection.focusRoom(room.id, target.building.id);
            roofRooms.add(room.id); roofRoomBuilding = target.building.id;
          }
        } else {
          roofRooms.clear(); roomSelection.select(pick(event.clientX, event.clientY));
        }
      }
      return;
    }
    el('editor-drag-outline').setAttribute('points', '');
    view.controls.enabled = g.enabled;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (cancel || Math.hypot(event.clientX - g.x, event.clientY - g.y) < 3) return;
    const end = view.floorAt(event.clientX, event.clientY, g.key);
    if (end) (tool === 'rotate' ? rotate(g.item.buildingId, turn(g, end)) : move(g.item, g.start, end)).catch(report);
  };
  listen(canvas, 'pointerup', finish);
  listen(canvas, 'pointercancel', event => finish(event, true));
  listen(window, 'pointerup', finish, { capture: true });
  listen(window, 'pointercancel', event => finish(event, true), { capture: true });
  listen(document, 'pointerup', finish, { capture: true });
  listen(document, 'pointercancel', event => finish(event, true), { capture: true });
  listen(canvas, 'lostpointercapture', event => finish(event, true));
  listen(canvas, 'pointerleave', () => roomSelection.hover(null));
  listen(canvas.parentElement, 'twinerror', event => report(event.detail));
  listen(document, 'keydown', event => {
    if (event.defaultPrevented || !canEdit() || event.ctrlKey || event.metaKey || event.altKey
      || event.target.closest?.('input, textarea, select, [contenteditable="true"]')
      || document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), [role="dialog"]')) return;
    const record = selection && findPiece(getPlan(), selection.pieceId, selection.buildingId);
    if (!record || !isObject(record) && record.kind !== 'opening' && record.building) return;
    if (event.key === 'Delete') { event.preventDefault(); cards.remove().catch(report); return; }
    if (!record.building && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      const by = [{ ArrowLeft: -1, ArrowRight: 1 }[event.key] || 0, { ArrowDown: -1, ArrowUp: 1 }[event.key] || 0];
      cards.queue(() => canEdit() && op({ op: 'move_site_item', list: record.kind, index: record.index, by })).catch(report); return;
    }
    if (!isObject(record)) return;
    const key = event.key.toLowerCase();
    if (!['r', '[', ']'].includes(key)) return;
    event.preventDefault();
    const target = { id: record.piece.id, building: record.building?.id };
    cards.queue(() => {
      if (!canEdit()) return;
      const current = findPiece(getPlan(), target.id, target.building);
      if (!current) return;
      return op(objectOperation(current, transformObject(current.piece, key === 'r' ? 'rotate' : 'scale', key === 'r' ? event.shiftKey : key === '[')));
    }).catch(report);
  });
  listen(document, 'keydown', event => {
    if (event.key !== 'Escape' || event.defaultPrevented || event.target.closest?.('input, textarea, select, [contenteditable="true"]')
      || document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), dialog[open]')) return;
    if (gesture?.dragging) { finish({ pointerId }, true); return; }
    roomSelection.back();
  });
  signal.addEventListener('abort', () => { if (gesture && !gesture.selecting) view.controls.enabled = gesture.enabled;
    if (handles.active()) handles.finish(true).catch(report);
    gesture = null; pointerId = null; ownsGesture = false; pointers.clear(); }, { once: true });
  for (const id of ['select', 'move', 'rotate']) {
    el(`rail-${id}`).disabled = false; listen(el(`rail-${id}`), 'click', () => { delegate?.cancel?.(); setTool(id); });
  }
  el('rail-sheet').disabled = false; listen(el('rail-sheet'), 'click', () => { onInteract?.(); sheet().catch(report); });
  document.querySelectorAll('[data-editor-camera]').forEach(button => listen(button, 'click', () => {
    onInteract?.(); delegate?.cancel?.();
    if (button.dataset.editorCamera === 'top' && floor()) view.setTopCamera(floor().key);
    else view.setCamera(button.dataset.editorCamera);
  }));
  return {
    haLink,
    deleteSelected: () => cards.remove(),
    select, selected: () => selection, selection: roomSelection.current, dragPiece, rotateBuilding: rotate, floor, chooseFloor, drawFloors, sheet, setTool,
    handles: handles.handles,
    selectedRooms: () => roofRooms.size ? [...roofRooms] : null,
    // A press on the selected piece's handle belongs to the handle, never to a yard item behind it.
    handleAt: event => !!handles.hit(event),
    get lastDragFrameMs() { return handles.lastDragFrameMs; }, dragging: handles.active,
    buildingCentre(id) { const b = getPlan()?.buildings.find(b => b.id === id); return b && rotatePoint(localCentre(b), b.rotation || 0).map((v, i) => v + (b.position?.[i] || 0)); },
    delegate(value) { delegate = value; },
    refresh() { drawFloors(); if (selection && !findPiece(getPlan(), selection.pieceId, selection.buildingId)) select(null); else roomSelection.refresh(); },
    refreshCard() { cards.draw(selection); },
    // The card's area section redraws once the link answers; the scene never waits on it.
    // The link is read when the house changed, while a room, building or anchor card
    // is open, and otherwise once per idle interval: never on every build poll.
    refreshLink(changed = true) {
      const record = selection && findPiece(getPlan(), selection.pieceId, selection.buildingId);
      const open = ['room', 'building', 'anchor'].includes(record?.kind);
      if (!changed && !open && haLink.state() && Date.now() - linkReadAt < idleInterval) return Promise.resolve(haLink.state());
      linkReadAt = Date.now();
      return haLink.refresh().then(() => { if (!signal?.aborted) cards.draw(selection); }).catch(report);
    },
  };
}
