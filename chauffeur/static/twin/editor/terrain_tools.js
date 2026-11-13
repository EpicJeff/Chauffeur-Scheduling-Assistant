import * as THREE from 'three';
import { groundAt, edgeDistance } from '../twin_ground.js';
import { tintGrade } from '../twin_terrain_mesh.js';
import { report } from './api.js';
import { twinText } from '../palette.js';
import { siteRecords, siteShapeKinds, siteShapeLabels, sitePieces } from '../objects.js';
import { vertexHandles, editVertex } from './polygon_handles.js';
import { createSiteDrawing, snapSitePoint, polygonArea } from './site_drawing.js';
import { pathPresets, pathOutline } from '../path_shapes.js';
import { placedPit, firePitOutline } from '../fire_pits.js';

const FT = .3048;
const words = { terraces: 'Terrace pad', ...siteShapeLabels };
const mid = poly => [0, 1].map(i => poly.reduce((n, p) => n + p[i], 0) / poly.length);
export function siteRows(plan) {
  return siteRecords(plan).filter(record => siteShapeKinds.includes(record.kind));
}
export const snapPadPoint = snapSitePoint;

// Separate lot tools keep the object-library/placed-item merge seam small.
export function createTerrainTools({ view, tools, getPlan, op, canEdit, signal, prepare = () => {}, pickObject }) {
  const canvas = view.renderer3.domElement, shell = document.querySelector('.editor-shell');
  const card = document.createElement('aside'); card.className = 'place-card editor-lot-card'; card.id = 'terrain-card'; card.hidden = true; shell.append(card);
  const layer = document.createElement('div'); layer.className = 'editor-handles'; canvas.parentElement.append(layer);
  const group = new THREE.Group(); view.scene.add(group);
  const material = new THREE.LineBasicMaterial({ color: twinText, depthTest: false });
  // Keep a drawable (degenerate when idle) preview from mount onwards. The
  // renderer warms its material before the first corner, just like pad lines.
  const previewLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), material);
  previewLine.renderOrder = 10; group.add(previewLine);
  const raycaster = new THREE.Raycaster();
  let chosen = null, drawing = null, gesture = null, handles = [], busy = false, grade = false, signature = '', menu = false;
  let padDrag = null;
  const drawingOptions = { height: 0, blend: 6 };
  const draft = createSiteDrawing({ getPlan, commit: save });
  const listen = (node, type, fn, options = {}) => node.addEventListener(type, fn, { ...options, signal });
  const node = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const button = (text, fn) => { const b = node('button', text); b.type = 'button'; listen(b, 'click', fn); return b; };
  const current = () => chosen && getPlan().site?.terraces?.find(p => p.id === chosen.id);
  function ray(event) {
    const r = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - r.left) / r.width * 2 - 1, 1 - (event.clientY - r.top) / r.height * 2), view.camera);
    return raycaster.ray;
  }
  function ground(event, height) {
    const r = ray(event), p = new THREE.Vector3();
    if (!r.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -(height || 0) * FT), p)) return null;
    if (height === undefined) for (let i = 0; i < 6; i++) r.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -groundAt(getPlan(), p.x / FT, -p.z / FT) * FT), p);
    return [p.x / FT, -p.z / FT];
  }
  function project(p, height = groundAt(getPlan(), ...p)) {
    const r = canvas.getBoundingClientRect(), v = new THREE.Vector3(p[0] * FT, (height + .08) * FT, -p[1] * FT).project(view.camera);
    return v.z >= -1 && v.z <= 1 ? [r.left + (v.x + 1) * r.width / 2, r.top + (1 - v.y) * r.height / 2] : null;
  }
  function clearGraphics() { for (const o of [...group.children]) if (o !== previewLine) { o.removeFromParent(); o.geometry.dispose(); } layer.replaceChildren(); handles = []; }
  function line(poly, height, close, target) {
    if (poly.length < 2) return;
    const ps = close ? [...poly, poly[0]] : poly;
    const geo = new THREE.BufferGeometry().setFromPoints(ps.map(p => new THREE.Vector3(p[0] * FT, ((height ?? groundAt(getPlan(), ...p)) + .08) * FT, -p[1] * FT)));
    if (target) { target.geometry.dispose(); target.geometry = geo; }
    else { const object = new THREE.Line(geo, material); object.renderOrder = 10; group.add(object); }
  }
  function label(text, p, height, handle) {
    const screen = project(p, height); if (!screen) return;
    const n = node('span', text); n.className = handle ? 'editor-handle editor-lot-handle' : 'editor-terrain-label';
    n.style.left = `${screen[0]}px`; n.style.top = `${screen[1]}px`; layer.append(n);
    if (handle) handles.push({ ...handle, at: p, screen });
  }
  function graphics() {
    clearGraphics();
    previewLine.geometry.dispose(); previewLine.geometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
    group.visible = view.state.view === 'ext'; if (!group.visible) return;
    const pads = getPlan()?.site?.terraces || [];
    for (const pad of pads) {
      const poly = gesture?.kind === 'vertex' && chosen?.id === pad.id ? gesture.polygon : pad.polygon;
      const centre = mid(poly), height = groundAt(getPlan(), ...centre), shown = Math.round(height * 1000) / 1000;
      line(poly, undefined, true); label(`${shown > 0 ? '+' : ''}${shown} ft`, centre, height);
      if (chosen?.id === pad.id) vertexHandles(poly).forEach(h => label(h.insert ? '+' : '•', h.at, groundAt(getPlan(), ...h.at), h));
    }
    if (drawing) {
      const points = draft.preview(), path = drawing.kind === 'path', fence = drawing.kind === 'fence';
      if (drawing.kind === 'fire_pit' && drawing.options.shape !== 'outline') {
        if (points.length) line(firePitOutline(placedPit(drawing.options.shape, points.at(-1), drawing.options)), undefined, true, previewLine);
        return;
      }
      if (path && points.length >= 2) line(pathOutline({ ...drawing.options, points }), undefined, true, previewLine);
      line(points, undefined, !path && !fence && points.length >= 3, path ? undefined : previewLine); drawing.points.forEach(p => label('•', p));
      if (points.length >= 3 && !path && !fence) label(`${polygonArea(points).toFixed(1)} sq ft`, mid(points));
    }
  }
  function tint() {
    view.groups.site?.traverse(o => { if (o.userData.terrain) tintGrade(o.geometry, grade); }); view.render();
  }
  function close() {
    cancelPadDrag();
    const g = gesture; gesture = null;
    if (g) {
      view.controls.enabled = g.enabled;
      if (canvas.hasPointerCapture(g.pointer)) canvas.releasePointerCapture(g.pointer);
    }
    draft.cancel(); drawing = null; chosen = null; menu = false; card.hidden = true; graphics();
  }
  async function save(operation) {
    if (!canEdit() || busy) return;
    busy = true; card.querySelectorAll('button,input,select').forEach(n => { n.disabled = true; });
    try { await op(operation); }
    catch (error) { report(error); return false; }
    finally { busy = false; signature = ''; refresh(); }
    return true;
  }
  function field(text, value, saveValue, choices, numeric = true) {
    const l = node('label', text), input = node(choices ? 'select' : 'input');
    if (choices) for (const choice of choices) { const [value, title] = Array.isArray(choice) ? choice : [choice, choice]; const o = node('option', title); o.value = value; input.append(o); }
    else { input.type = numeric ? 'number' : 'text'; input.step = '.5'; input.required = true; }
    input.value = value; input.setAttribute('aria-label', text); input.disabled = !canEdit();
    listen(input, 'change', () => {
      if (!canEdit()) return;
      if (!choices && numeric && (!input.value.trim() || !Number.isFinite(Number(input.value)))) { report(new Error('Use a finite number of feet.')); return; }
      saveValue(choices || !numeric ? input.value : Number(input.value));
    }); l.append(input); card.append(l); return input;
  }
  function cancelPadDrag() {
    const drag = padDrag; padDrag = null;
    if (!drag) return;
    drag.indicator.hidden = true; drag.row.dataset.dragging = 'false';
    if (drag.row.hasPointerCapture(drag.pointer)) drag.row.releasePointerCapture(drag.pointer);
  }
  function focusPadRow(id) {
    [...card.querySelectorAll('button')].find(row => row.dataset.padId === id)?.focus();
  }
  async function reorderPad(id, to, focus = false) {
    const pads = getPlan().site?.terraces || [], from = pads.findIndex(pad => pad.id === id);
    if (!canEdit() || busy || from < 0 || to < 0 || to >= pads.length || to === from) return;
    await save({ op: 'reorder_pad', id, to });
    if (focus && !card.hidden) focusPadRow(id);
  }
  function drawPadList() {
    card.append(node('h3', 'Pads'));
    const pads = getPlan().site?.terraces || [];
    if (!pads.length) { card.append(node('p', 'No pads yet.')); return; }
    const list = node('div'); list.className = 'editor-pad-list'; list.setAttribute('role', 'group'); list.setAttribute('aria-label', 'Pads, topmost first');
    const indicator = node('div'); indicator.className = 'editor-pad-drop'; indicator.hidden = true; indicator.setAttribute('aria-hidden', 'true');
    const rows = [];
    for (let index = pads.length - 1; index >= 0; index--) {
      const pad = pads[index], height = pad.height < 0 ? `−${Math.abs(pad.height)}` : `${pad.height > 0 ? '+' : ''}${pad.height}`;
      let suppressClick = false;
      const row = button(undefined, event => {
        if (suppressClick) { suppressClick = false; event.preventDefault(); return; }
        choose('terraces', pad.id); focusPadRow(pad.id);
      });
      row.className = 'editor-pad-row'; row.dataset.padId = pad.id;
      row.setAttribute('aria-pressed', String(chosen?.id === pad.id));
      if (canEdit()) {
        row.title = 'Drag to reorder, or use Alt+ArrowUp / Alt+ArrowDown';
        const grip = node('span', '⠿'); grip.className = 'editor-pad-grip'; grip.setAttribute('aria-hidden', 'true'); row.append(grip);
      }
      row.append(node('span', `Pad ${index + 1} · ${height} ft`));
      if (pad.edges?.some(edge => edge.wall)) {
        const badge = node('span', 'Wall'); badge.className = 'editor-pad-wall'; badge.title = 'Retaining wall'; row.append(badge);
      }
      listen(row, 'keydown', event => {
        if (!event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
        // Do not let the scene's arrow handlers nudge geometry as well.
        event.preventDefault(); event.stopPropagation();
        const from = (getPlan().site?.terraces || []).findIndex(p => p.id === pad.id);
        reorderPad(pad.id, from + (event.key === 'ArrowUp' ? 1 : -1), true).catch(report);
      });
      listen(row, 'pointerdown', event => {
        if (!canEdit() || busy || padDrag || event.button !== 0 || event.isPrimary === false) return;
        // As with device rows, touch scrolls over words and drags on the grip.
        if (event.pointerType !== 'mouse' && !event.target.closest?.('.editor-pad-grip')) return;
        suppressClick = false;
        padDrag = { row, pointer: event.pointerId, start: [event.clientX, event.clientY], to: pads.length - 1 - index,
          order: pads.map(p => p.id), indicator, moved: false };
        row.setPointerCapture(event.pointerId); event.stopPropagation();
      });
      const move = event => {
        const drag = padDrag;
        if (!drag || drag.row !== row || drag.pointer !== event.pointerId) return;
        if (!canEdit() || busy) { cancelPadDrag(); return; }
        if (!drag.moved && Math.hypot(event.clientX - drag.start[0], event.clientY - drag.start[1]) < 4) return;
        drag.moved = true; suppressClick = true; row.dataset.dragging = 'true';
        const remaining = rows.filter(r => r !== row);
        const next = remaining.findIndex(r => { const rect = r.getBoundingClientRect(); return event.clientY < rect.top + rect.height / 2; });
        drag.to = next < 0 ? remaining.length : next;
        const target = remaining[drag.to] || remaining.at(-1);
        const bounds = target?.getBoundingClientRect();
        indicator.style.top = `${(bounds ? (remaining[drag.to] ? bounds.top : bounds.bottom) : row.getBoundingClientRect().top) - list.getBoundingClientRect().top}px`;
        indicator.hidden = false; event.preventDefault(); event.stopPropagation();
      };
      listen(row, 'pointermove', move);
      listen(row, 'pointerup', event => {
        if (padDrag?.row !== row || padDrag.pointer !== event.pointerId) return;
        move(event);
        const drag = padDrag; cancelPadDrag();
        if (!drag?.moved) return;
        event.preventDefault(); event.stopPropagation();
        // A refresh/remote edit must not apply an index from an older stack.
        if (JSON.stringify(drag.order) !== JSON.stringify((getPlan().site?.terraces || []).map(p => p.id))) return;
        // Display index 0 is the last stored pad. Emit only the final move.
        reorderPad(pad.id, pads.length - 1 - drag.to, true).catch(report);
      });
      for (const type of ['pointercancel', 'lostpointercapture']) listen(row, type, event => {
        if (padDrag?.row === row && padDrag.pointer === event.pointerId) cancelPadDrag();
      });
      rows.push(row); list.append(row);
    }
    list.append(indicator); card.append(list);
  }
  function drawCard() {
    cancelPadDrag();
    card.replaceChildren(); card.hidden = false;
    card.append(button('Close', close));
    drawPadList();
    if (drawing) {
      if (drawing.kind === 'fire_pit') {
        field('Shape', drawing.options.shape, shape => startDrawing('fire_pit', shape === 'round' ? { shape, radius: 2 } : shape === 'square' ? { shape, side: 4 } : shape === 'rect' ? { shape, width: 4, depth: 6 } : { shape }),
          [['round', 'Round'], ['square', 'Square'], ['rect', 'Rectangle'], ['outline', 'Drawn outline']]);
        if (drawing.options.shape !== 'outline') {
          card.append(node('h3', 'Add fire pit'), node('p', 'Click the ground to place the fire pit. Hold Shift for free placement. Escape cancels.'));
          for (const [key, title] of drawing.options.shape === 'round' ? [['radius', 'Radius (ft)']] : drawing.options.shape === 'square' ? [['side', 'Side (ft)']] : [['width', 'Width (ft)'], ['depth', 'Depth (ft)']])
            field(title, drawing.options[key], value => { drawing.options[key] = value; graphics(); });
          return;
        }
      }
      const title = drawing.kind === 'terraces' ? 'a terrace pad' : drawing.kind === 'path' ? 'a path' : words[drawing.kind].toLowerCase();
      card.append(node('h3', `Draw ${title}`), node('p', 'Tap corners. Snap to yard edges, outside walls and the lot. Hold Shift for free placement. Enter or Finish completes; Backspace removes a point; Escape cancels.'));
      card.append(button(drawing.kind === 'terraces' ? 'Finish pad' : 'Finish', finishDrawing));
      if (drawing.kind === 'terraces') {
        field('Pad height (ft)', drawing.options.height, value => { drawing.options.height = value; });
        field('Blend (ft)', drawing.options.blend, value => { drawing.options.blend = value; });
      }
      if (drawing.kind === 'fence') {
        const height = field('Height (ft)', drawing.options.height, value => { drawing.options.height = value; }); height.min = '2'; height.max = '10';
        if ('style' in drawing.options) field('Style', drawing.options.style, value => { drawing.options.style = value; }, undefined, false);
      }
      if (drawing.kind === 'path') {
        field('Preset', drawing.options.preset || 'sidewalk', value => { Object.assign(drawing.options, pathPresets[value], { preset: value }); drawCard(); graphics(); }, Object.keys(pathPresets));
        const width = field('Width (ft)', drawing.options.width, value => { drawing.options.width = value; graphics(); }); width.min = '1'; width.max = '30';
        field('Corner style', drawing.options.corner, value => { drawing.options.corner = value; graphics(); }, ['mitred', 'rounded']);
        field('Smooth curve', drawing.options.smooth ? 'yes' : 'no', value => { drawing.options.smooth = value === 'yes'; graphics(); }, ['no', 'yes']);
      } else if (!['terraces', 'fence'].includes(drawing.kind)) card.append(button('Rectangle', () => {
        if (drawing.points.length !== 2) { report(new Error('Place two opposite corners, then choose Rectangle.')); return; }
        const [a, b] = drawing.points; drawing.points = [a, [b[0], a[1]], b, [a[0], b[1]]]; finishDrawing();
      }));
      return;
    }
    const piece = current();
    if (!piece || menu) {
      card.append(node('h3', 'Ground and yard'));
      card.append(button('Add pad', () => startDrawing('terraces', drawingOptions)));
      for (const [kind, title] of [['beds', 'Draw bed'], ['hardscape', 'Draw patio / hard surface'], ['pool', 'Draw pool'], ['edges', 'Draw planting edge']])
        card.append(button(title, () => startDrawing(kind)));
      for (const [preset, title] of [['sidewalk', 'Sidewalk'], ['paver', 'Paver path'], ['driveway', 'Driveway']])
        card.append(button(title, () => startDrawing('path', { ...pathPresets[preset], preset })));
      card.append(button('Add fire pit', () => startDrawing('fire_pit', { shape: 'round', radius: 2 })));
      card.append(button('Draw fence', () => {
        const existing = sitePieces(getPlan().site?.fence).find(f => f.style);
        startDrawing('fence', { height: 6, ...(existing ? { style: existing.style } : {}) });
      }));
      const toggle = button('Grade', () => { grade = !grade; toggle.setAttribute('aria-pressed', String(grade)); tint(); });
      toggle.setAttribute('aria-pressed', String(grade)); card.append(toggle);
      card.append(node('p', 'Grade: blue is lower, orange is higher. Heights are feet from the lot datum.'));
      for (const row of siteRows(getPlan())) card.append(button(`${words[row.kind]} ${row.index + 1}`, () => choose(row.kind, row.piece.id)));
      return;
    }
    card.append(node('h3', words[chosen.kind]));
    if (chosen.kind === 'terraces') {
      const pads = getPlan().site.terraces, index = pads.findIndex(p => p.id === piece.id);
      card.append(node('p', `Layer ${index + 1} of ${pads.length}`));
      const reorder = by => {
        const to = getPlan().site.terraces.findIndex(p => p.id === piece.id) + by;
        if (to >= 0 && to < getPlan().site.terraces.length) return save({ op: 'reorder_pad', id: piece.id, to });
      };
      const forward = button('Bring forward', () => reorder(1)), back = button('Send back', () => reorder(-1));
      forward.disabled = !canEdit() || index === pads.length - 1; back.disabled = !canEdit() || index === 0;
      card.append(forward, back);
      const update = change => save({ op: 'update_pad', id: piece.id, ...change });
      field('Pad height (ft)', piece.height, height => update({ height }));
      card.append(button('Down 0.5 ft', () => update({ height: current().height - .5 })), button('Up 0.5 ft', () => update({ height: current().height + .5 })));
      field('Blend (ft)', piece.blend ?? 6, blend => update({ blend }));
      piece.polygon.forEach((_, i) => {
        const edge = piece.edges?.[i] || { edge: 'slope' };
        const updateEdge = change => {
          const edges = current().polygon.map((_, j) => structuredClone(current().edges?.[j] || { edge: 'slope' }));
          edges[i] = { ...edges[i], ...change };
          if (edges[i].edge === 'slope' || !edges[i].wall) delete edges[i].wall;
          update({ edges });
        };
        field(`Edge ${i + 1}`, edge.edge, edge => updateEdge({ edge }), ['slope', 'sharp']);
        if (edge.edge !== 'sharp') return;
        field(`Edge ${i + 1} Wall`, edge.wall?.material || '', material => updateEdge({ wall: material
          ? { thickness_in: 8, above_in: 0, ...edge.wall, material } : null }),
          [['', 'None'], ['stone', 'Stone'], ['block', 'Block'], ['concrete', 'Concrete'], ['brick', 'Brick'], ['timber', 'Timber']]);
        if (!edge.wall) return;
        for (const [key, title, fallback, min, max] of [['thickness_in', 'Thickness (in)', 8, 4, 24], ['above_in', 'Above ground (in)', 0, 0, 36]]) {
          const input = field(`Edge ${i + 1} ${title}`, edge.wall[key] ?? fallback, value => updateEdge({ wall: { ...edge.wall, [key]: value } }));
          input.min = String(min); input.max = String(max);
        }
      });
      card.append(node('p', 'Drag corners to reshape. Tap + to add a corner. Alt-click a corner to remove it (at least three remain).'));
    }
    card.append(button('Delete', remove), button('Ground and yard', show));
  }
  function startDrawing(kind, options = {}) {
    if (!canEdit() || busy) return;
    prepare(); tools.setTool('select'); view.setView('ext'); tools.select(null);
    if (kind === 'terraces') Object.assign(drawingOptions, options);
    draft.start(kind, kind === 'terraces' ? drawingOptions : { ...options }); drawing = draft.current(); chosen = null; menu = false; drawCard(); graphics();
  }
  async function finishDrawing() {
    if (!canEdit() || busy) return;
    try { if (await draft.finish()) { drawing = null; show(); } }
    catch (error) { report(error); }
  }
  function choose(kind, id) {
    prepare(); tools.setTool('select'); view.setView('ext');
    if (kind !== 'terraces') { close(); tools.select({ kind, id }); return; }
    tools.select(null); chosen = { kind, id }; menu = false; drawing = null; signature = ''; refresh();
  }
  async function remove() {
    const piece = current(); if (!piece || !canEdit() || busy) return;
    if (!await window.promptConfirm(`Delete ${words[chosen.kind]}?`, 'Undo restores it.', 'Delete', 'Cancel')) return;
    await save({ op: 'delete_pad', id: piece.id });
    if (!current()) show();
  }
  function show() { prepare(); view.setView('ext'); tools.select(null); menu = true; chosen = null; drawing = null; signature = ''; refresh(); }
  function refresh() {
    if (chosen && !current()) { chosen = null; menu = true; }
    const key = JSON.stringify([chosen, current(), drawing?.points.length, menu, canEdit(), getPlan()?.site]);
    if ((menu || chosen || drawing) && key !== signature) { signature = key; drawCard(); }
    graphics(); tint();
  }
  function pointerDown(event) {
    if (!canEdit() || busy || event.button !== 0 || view.state.view !== 'ext') return false;
    if (!drawing && !['select', 'move'].some(id => document.getElementById(`rail-${id}`)?.getAttribute('aria-pressed') === 'true')) return false;
    if (drawing) {
      const p = ground(event); if (p) { draft.add(p, event.shiftKey); drawCard(); graphics(); }
      gesture = { kind: 'draw', enabled: view.controls.enabled, pointer: event.pointerId }; view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); return true;
    }
    const hit = handles.find(h => Math.hypot(h.screen[0] - event.clientX, h.screen[1] - event.clientY) < 16);
    // Plants/furniture keep their existing selection and drag path even when
    // they stand in a bed or on hardscape. A selected pad handle still wins.
    if (!hit && pickObject?.(event.clientX, event.clientY)) { close(); return false; }
    const piece = current();
    if (hit && piece) {
      const start = ground(event, chosen.kind === 'terraces' ? piece.height : undefined); if (!start) return false;
      gesture = { kind: 'vertex', index: hit.index, handle: hit, source: piece.polygon, remove: event.altKey, polygon: editVertex(piece.polygon, hit, hit.at, { remove: event.altKey }), start, enabled: view.controls.enabled, height: piece.height, client: [event.clientX, event.clientY], pointer: event.pointerId };
    } else {
      // A pad's filled area is selectable only in its own ground menu; its
      // outline is always selectable, leaving house and tree picks reachable.
      const p = ground(event); if (!p) return false;
      for (const pad of [...(getPlan().site?.terraces || [])].reverse()) {
        const q = ground(event, pad.height); if (!q) continue;
        if (pad.polygon.some((a, i) => edgeDistance(q, a, pad.polygon[(i + 1) % pad.polygon.length]) < .6)) { choose('terraces', pad.id); return true; }
      }
      return false;
    }
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); return true;
  }
  function pointerMove(event) {
    if (drawing && !busy) { const p = ground(event); if (p) { draft.move(p, event.shiftKey); graphics(); } return true; }
    if (!gesture) return false;
    if (gesture.kind === 'draw') return true;
    const p = ground(event, gesture.height); if (!p) return true;
    gesture.moved = !gesture.client || Math.hypot(event.clientX - gesture.client[0], event.clientY - gesture.client[1]) >= 3;
    if (gesture.kind === 'vertex') gesture.polygon = editVertex(gesture.source, gesture.handle, event.shiftKey ? p : snapPadPoint(p, getPlan(), chosen.id), { remove: gesture.remove });
    else gesture.by = p.map((v, i) => v - gesture.start[i]);
    graphics(); return true;
  }
  function pointerUp(event, cancel) {
    if (!gesture) return false;
    const g = gesture; gesture = null; view.controls.enabled = g.enabled;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (!cancel && canEdit() && g.kind !== 'draw') {
      if (g.kind === 'vertex' && (g.moved || g.handle.insert || g.remove) && JSON.stringify(g.polygon) !== JSON.stringify(g.source)) {
        const edges = current().edges?.map(e => ({ ...e })) || g.source.map(() => ({ edge: 'slope' }));
        if (g.remove && g.polygon.length < g.source.length) edges.splice(g.index, 1);
        else if (g.handle.insert) edges.splice(g.index + 1, 0, { ...edges[g.index] });
        save({ op: 'update_pad', id: chosen.id, polygon: g.polygon, edges }).catch(report);
      }
    }
    if (g.kind === 'draw' && drawing?.kind === 'fire_pit' && drawing.options.shape !== 'outline') {
      if (cancel) draft.back(); else finishDrawing();
    }
    graphics(); return true;
  }
  const open = button('Ground and yard', show); open.id = 'rail-ground'; document.getElementById('editor-rail').append(open);
  listen(document.getElementById('editor-rail'), 'click', event => {
    const b = event.target.closest?.('button');
    if (b && b !== open && !['rail-undo', 'rail-redo'].includes(b.id)) close();
  }, { capture: true });
  listen(document, 'keydown', event => {
    if (card.hidden || event.target.closest?.('input,textarea,select,[contenteditable="true"]')) return;
    if (document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), dialog[open]')) return;
    if (event.key === 'Escape') { close(); event.stopImmediatePropagation(); }
    else if (drawing && event.key === 'Enter') { event.preventDefault(); event.stopImmediatePropagation(); finishDrawing(); }
    else if (drawing && event.key === 'Backspace') { event.preventDefault(); event.stopImmediatePropagation(); draft.back(); drawCard(); graphics(); }
    else if (chosen && event.key === 'Delete') { event.stopImmediatePropagation(); remove().catch(report); }
  }, { capture: true });
  listen(canvas, 'pointermove', event => { if (drawing && !gesture) pointerMove(event); });
  view.controls.addEventListener('change', graphics);
  listen(canvas.parentElement, 'twinrebuilt', refresh);
  signal.addEventListener('abort', () => { cancelPadDrag(); if (gesture) view.controls.enabled = gesture.enabled; clearGraphics(); previewLine.geometry.dispose(); group.removeFromParent(); material.dispose(); layer.remove(); card.remove(); open.remove(); view.controls.removeEventListener('change', graphics); }, { once: true });
  return { show, choose, startDrawing, refresh, pointerDown, pointerMove, pointerUp, cancel: close, handles: () => handles };
}
