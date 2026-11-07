import { report } from './api.js';
import { createCards, findPiece, feetInches } from './cards.js';
import { snapPoint, snapRotation } from './snap.js';

export function createSceneTools({ view, getPlan, getSheets, edit, panel, canEdit, signal, onInteract }) {
  const el = id => document.getElementById(id), canvas = view.renderer3.domElement;
  let selection = null, tool = 'select', levelKey = null, sheetOn = false, gesture = null, delegate = null;
  const cards = createCards({ getPlan, edit, canEdit, select, ask: item => panel.focusSelection(item) });
  const listen = (node, event, fn, options = {}) => node.addEventListener(event, fn, { ...options, signal });
  function levels() { return (getPlan()?.buildings || []).flatMap(b => b.levels.map(l => ({ key: `${b.id}:${l.id}`, building: b, level: l }))); }
  function floor() {
    const list = levels();
    return list.find(l => l.key === levelKey) || list[0];
  }
  function select(item) {
    if (!canEdit() && item) return;
    selection = item;
    if (item) {
      const record = findPiece(getPlan(), item.pieceId, item.buildingId);
      const level = record?.piece.level || record?.building.walls.find(w => w.id === record.piece.wall)?.level;
      if (level) levelKey = `${item.buildingId}:${level}`;
    }
    cards.draw(selection);
  }
  function setTool(name) {
    tool = name; onInteract?.();
    for (const id of ['select', 'move', 'rotate']) el(`rail-${id}`).setAttribute('aria-pressed', String(id === name));
    canvas.style.cursor = name === 'move' ? 'grab' : name === 'rotate' ? 'crosshair' : '';
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
    view.setSheet({ url, buildingId: target.building.id, levelId: target.level.id, reg: registration.reg });
  }
  function chooseFloor(key) {
    levelKey = key; onInteract?.(); view.setView(key); view.showLevels([key]);
    if (sheetOn) sheet(key, true).catch(report);
    delegate?.floorChanged?.(); drawFloors();
  }
  function drawFloors() {
    const host = el('editor-floors'), focused = document.activeElement?.dataset.floor;
    const signature = JSON.stringify(levels().map(row => [row.key, row.level.name]));
    if (host.dataset.levels !== signature) {
      host.dataset.levels = signature; host.replaceChildren();
      const title = document.createElement('span'); title.textContent = 'Floors'; host.append(title);
      for (const row of levels().reverse()) {
        const group = document.createElement('div'); group.className = 'editor-floor-row';
        const button = document.createElement('button'); button.type = 'button'; button.dataset.floor = row.key;
        button.textContent = row.level.name || row.level.id; button.addEventListener('click', () => chooseFloor(row.key));
        const toggle = document.createElement('input'); toggle.type = 'checkbox'; toggle.dataset.floorVisible = row.key;
        toggle.setAttribute('aria-label', `Show ${row.level.name || row.level.id}`);
        toggle.addEventListener('change', () => {
          onInteract?.();
          const keys = [...host.querySelectorAll('[data-floor-visible]:checked')].map(node => node.dataset.floorVisible);
          view.showLevels(keys);
        });
        group.append(toggle, button); host.append(group);
        if (focused === row.key) button.focus({ preventScroll: true });
      }
      const all = document.createElement('button'); all.type = 'button'; all.textContent = 'All floors';
      all.addEventListener('click', () => { onInteract?.(); view.setView('ext'); view.showLevels(null); drawFloors(); }); host.append(all);
      for (const kind of ['Floor', 'Building']) {
        const details = document.createElement('button'); details.type = 'button'; details.textContent = `${kind} details`;
        details.addEventListener('click', () => {
          const target = floor(); if (!target) return;
          onInteract?.(); select({ pieceId: kind === 'Floor' ? target.level.id : target.building.id, buildingId: target.building.id });
        }); host.append(details);
      }
      if (!levels().length) { const note = document.createElement('p'); note.textContent = 'No floors yet'; host.append(note); }
    }
    host.querySelectorAll('[data-floor]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.floor === floor()?.key)));
    host.querySelectorAll('[data-floor-visible]').forEach(node => { node.checked = !!view.groups?.levels[node.dataset.floorVisible]?.visible; });
  }
  function pieceAnchor(item) {
    const record = findPiece(getPlan(), item.pieceId, item.buildingId); if (!record) return null;
    const { piece, building } = record;
    const level = piece.level || building.walls.find(w => w.id === piece.wall)?.level || building.levels[0]?.id;
    const points = piece.from ? [piece.from, piece.to] : piece.polygon || piece.rect && [[piece.rect[0], piece.rect[1]], [piece.rect[2], piece.rect[3]]];
    const point = piece.from || (points?.length ? [0, 1].map(axis => points.reduce((n, p) => n + p[axis], 0) / points.length) : piece.position || [0, 0]);
    return { point, key: `${building.id}:${level}`, record };
  }
  async function move(item, from, to) {
    if (!canEdit() || !from || !to) return;
    const anchor = pieceAnchor(item); if (!anchor) return;
    const walls = anchor.record.building.walls.filter(w => w.level === anchor.key.slice(item.buildingId.length + 1) && w.id !== item.pieceId);
    const by = [to[0] - from[0], to[1] - from[1]];
    const destination = snapPoint(anchor.point.map((v, i) => v + by[i]), walls);
    const delta = destination.map((v, i) => v - anchor.point[i]);
    if (Math.hypot(...delta) < .001) return;
    await edit({ op: 'move', piece: item.pieceId, building: item.buildingId, by: delta }); cards.draw(selection);
  }
  async function rotate(buildingId, delta) {
    if (!canEdit()) return;
    const building = getPlan()?.buildings.find(b => b.id === buildingId); if (!building) return;
    const to = snapRotation((building.rotation || 0) + delta);
    if (Math.abs(to - (building.rotation || 0)) < .001) return;
    await edit({ op: 'rotate', building: buildingId, to }); cards.draw(selection);
  }
  async function dragPiece(pieceId, buildingId, dx, dy) {
    const item = { pieceId, buildingId }; select(item);
    const anchor = pieceAnchor(item); if (!anchor) return;
    const p = view.screenOfFloor(...anchor.point, anchor.key); if (!p) return;
    await move(item, view.floorAt(...p, anchor.key), view.floorAt(p[0] + dx, p[1] + dy, anchor.key));
  }
  // Capture before OrbitControls so a floor drag never turns into a camera drag.
  listen(canvas, 'pointerdown', event => {
    if (event.button !== 0 || !canEdit()) return;
    if (delegate?.pointerDown?.(event)) { event.stopImmediatePropagation(); return; }
    const picked = view.pick(event.clientX, event.clientY);
    if (!picked || !findPiece(getPlan(), picked.pieceId, picked.buildingId)) return;
    onInteract?.(); select(picked);
    if (tool === 'select') return;
    const anchor = pieceAnchor(picked); if (!anchor) return;
    const start = view.floorAt(event.clientX, event.clientY, anchor.key); if (!start) return;
    const b = anchor.record.building, pts = b.walls.flatMap(w => [w.from, w.to]);
    const centre = pts.length ? [0, 1].map(i => (Math.min(...pts.map(p => p[i])) + Math.max(...pts.map(p => p[i]))) / 2) : [0, 0];
    gesture = { item: picked, start, key: anchor.key, centre, x: event.clientX, y: event.clientY, enabled: view.controls.enabled };
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); event.stopImmediatePropagation();
  }, { capture: true });
  listen(canvas, 'pointermove', event => {
    if (delegate?.pointerMove?.(event)) return;
    if (!gesture) return;
    const end = view.floorAt(event.clientX, event.clientY, gesture.key); if (!end) return;
    const hint = el('editor-drag-hint'); hint.hidden = false; hint.style.left = `${event.clientX + 18}px`; hint.style.top = `${event.clientY + 18}px`;
    hint.textContent = tool === 'move' ? `${feetInches(Math.hypot(end[0] - gesture.start[0], end[1] - gesture.start[1]))} along the floor` : `${Math.round(turn(gesture, end))}°`;
    const record = findPiece(getPlan(), gesture.item.pieceId, gesture.item.buildingId);
    const piece = record?.piece;
    let outline = piece?.polygon || (piece?.from ? [piece.from, piece.to] : null);
    if (piece?.rect) { const [x0, y0, x1, y1] = piece.rect; outline = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]; }
    if (tool === 'rotate') outline = record?.building.levels[0]?.outline || record?.building.walls.flatMap(w => [w.from, w.to]);
    if (outline) {
      const angle = turn(gesture, end) * Math.PI / 180;
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
    if (delegate?.pointerUp?.(event, cancel)) return;
    if (!gesture) return;
    const g = gesture; gesture = null; el('editor-drag-hint').hidden = true;
    el('editor-drag-outline').setAttribute('points', '');
    view.controls.enabled = g.enabled;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (cancel || Math.hypot(event.clientX - g.x, event.clientY - g.y) < 3) return;
    const end = view.floorAt(event.clientX, event.clientY, g.key);
    if (end) (tool === 'rotate' ? rotate(g.item.buildingId, turn(g, end)) : move(g.item, g.start, end)).catch(report);
  };
  listen(canvas, 'pointerup', finish);
  listen(canvas, 'pointercancel', event => finish(event, true));
  for (const id of ['select', 'move', 'rotate']) {
    el(`rail-${id}`).disabled = false; listen(el(`rail-${id}`), 'click', () => { delegate?.cancel?.(); setTool(id); });
  }
  el('rail-sheet').disabled = false; listen(el('rail-sheet'), 'click', () => { onInteract?.(); sheet().catch(report); });
  document.querySelectorAll('[data-editor-camera]').forEach(button => listen(button, 'click', () => {
    onInteract?.(); delegate?.leavePlan?.(); view.setCamera(button.dataset.editorCamera);
  }));
  return {
    select, selected: () => selection, dragPiece, rotateBuilding: rotate, floor, chooseFloor, drawFloors, sheet, setTool,
    delegate(value) { delegate = value; },
    refresh() { drawFloors(); if (selection && !findPiece(getPlan(), selection.pieceId, selection.buildingId)) select(null); },
    refreshCard() { cards.draw(selection); },
  };
}
