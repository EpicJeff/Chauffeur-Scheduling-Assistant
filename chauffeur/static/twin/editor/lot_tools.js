import * as THREE from 'three';
import { contains } from '../twin_generator.js';
import { groundAt } from '../twin_ground.js';
import { snapRotation } from './snap.js';
import { plotSuggestionCard } from './place.js';
import { request, report } from './api.js';

const FT = .3048;
const rotate = (p, degrees) => {
  const a = degrees * Math.PI / 180;
  return [Math.cos(a) * p[0] - Math.sin(a) * p[1], Math.sin(a) * p[0] + Math.cos(a) * p[1]];
};
const add = (p, q) => p.map((v, i) => v + q[i]);
const subtract = (p, q) => p.map((v, i) => v - q[i]);
const distance = (p, q) => Math.hypot(...subtract(p, q));
const centre = points => [0, 1].map(i => points.reduce((n, p) => n + p[i], 0) / points.length);
const boxCentre = points => [0, 1].map(i => (Math.min(...points.map(p => p[i])) + Math.max(...points.map(p => p[i]))) / 2);
const degrees = angle => (angle % 360 + 360) % 360;
const angleOff = (a, b) => Math.abs((a - b + 540) % 360 - 180);
const placed = (building, points) => points.map(p => add(rotate(p, building.rotation || 0), building.position || [0, 0]));
function footprint(building) {
  const level = [...(building.levels || [])].sort((a, b) => a.elevation - b.elevation)[0];
  if (level?.outline?.length >= 3) return level.outline;
  const points = (building.walls || []).flatMap(w => [w.from, w.to]);
  if (!points.length) return [];
  const [x0, y0] = [0, 1].map(i => Math.min(...points.map(p => p[i])));
  const [x1, y1] = [0, 1].map(i => Math.max(...points.map(p => p[i])));
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
}

// Compare rigid footprints, including different starting corners and winding.
// A near centroid alone must never snap a differently sized building.
export function snapFootprint(building, outline, suggestions) {
  const current = placed(building, outline), localCentre = centre(outline);
  let best = null;
  for (const suggestion of suggestions) {
    if (suggestion.outline.length !== outline.length) continue;
    for (const direction of [1, -1]) for (let start = 0; start < outline.length; start++) {
      const target = outline.map((_, i) => suggestion.outline[(start + direction * i + outline.length) % outline.length]);
      const gap = Math.max(...target.map((p, i) => distance(p, current[i])));
      if (gap > 2 + 1e-9 || best && gap >= best.gap) continue;
      const targetCentre = centre(target);
      let dot = 0, cross = 0;
      outline.forEach((p, i) => {
        const a = subtract(p, localCentre), b = subtract(target[i], targetCentre);
        dot += a[0] * b[0] + a[1] * b[1]; cross += a[0] * b[1] - a[1] * b[0];
      });
      const rotation = degrees(Math.atan2(cross, dot) * 180 / Math.PI);
      if (angleOff(rotation, building.rotation || 0) > 7 + 1e-9) continue;
      const position = subtract(targetCentre, rotate(localCentre, rotation));
      if (Math.max(...placed({ position, rotation }, outline).map((p, i) => distance(p, target[i]))) > .25) continue;
      best = { position, rotation, gap };
    }
  }
  return best && { position: best.position, rotation: best.rotation };
}

export function createLotTools({ view, getPlan, getSheets, getSelection, select, pauses, op, reload, canEdit, signal }) {
  const canvas = view.renderer3.domElement, parent = canvas.parentElement;
  const layer = document.createElement('div'); layer.className = 'editor-handles'; parent.append(layer);
  const card = document.createElement('aside'); card.className = 'place-card editor-lot-card'; card.hidden = true;
  card.setAttribute('aria-label', 'Lot placement'); document.querySelector('.editor-shell').append(card);
  const graphics = new THREE.Group(); view.scene.add(graphics);
  const raycaster = new THREE.Raycaster(), plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  let sheet = null, sheetKey = '', sheetVersion = 0, graphicKey = '', rows = [], gesture = null, selected = null;
  let drawing = null, openCard = null, busy = false, frame = null, disposed = false;
  const drafts = new Map();
  const place = () => getSheets().place || { buildings: [], lot: {} };
  const read = () => place().lot?.read;
  const suggestions = () => (read()?.suggestions || []).filter(s => s.state === 'open');
  const lotOutline = () => read()?.lot || place().lot?.placement?.outline || getPlan()?.site?.lot || [];
  // Handles and the card stay shown while a change saves (no blink after each
  // drop); only new gestures and actions wait for it.
  const available = () => canEdit() && document.getElementById('place-view').hidden;
  const enabled = () => available() && !busy;
  const sceneTool = () => ['select', 'move', 'rotate'].find(id => document.getElementById(`rail-${id}`).getAttribute('aria-pressed') === 'true');
  const pauseBuilding = () => pauses.lotPlacement()?.building;
  function building(id) {
    // The saved plan answers first: the scene may still be rebuilding the last change.
    const built = getPlan()?.buildings.find(b => b.id === id) || view.plan?.buildings.find(b => b.id === id);
    if (built) return built;
    const part = place().buildings.find(b => b.id === id);
    return part?.footprint?.length ? { id, name: part.name, position: [0, 0], rotation: 0,
      levels: [{ elevation: 0, outline: part.footprint }], unbuilt: true } : null;
  }
  function current() {
    if (gesture?.preview) return gesture.preview;
    const selection = getSelection();
    return building(pauseBuilding() || (selection.kind === 'building' ? selection.id : !selection.id && selected));
  }
  function ground(event) {
    const rect = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2), view.camera);
    const point = raycaster.ray.intersectPlane(plane, new THREE.Vector3());
    return point && [point.x / FT, -point.z / FT];
  }
  function project(point) {
    view.camera.updateMatrixWorld(true);
    const p = new THREE.Vector3(point[0] * FT, 0, -point[1] * FT).project(view.camera), r = canvas.getBoundingClientRect();
    return p.z >= -1 && p.z <= 1 ? [r.left + (p.x + 1) * r.width / 2, r.top + (1 - p.y) * r.height / 2] : null;
  }
  function handles() {
    const b = current(); if (!available() || !b || !pauseBuilding() && view.state.view !== 'ext') return [];
    const outline = footprint(b); if (!outline.length) return [];
    const mid = boxCentre(outline);
    const front = outline.map((p, i) => [p, outline[(i + 1) % outline.length]])
      .sort((a, b) => a[0][1] + a[1][1] - b[0][1] - b[1][1] || distance(...b) - distance(...a))[0];
    const at = [mid, front[0].map((v, i) => (v + front[1][i]) / 2)];
    const rect = canvas.getBoundingClientRect();
    return ['move', 'turn'].map((kind, i) => {
      const point = placed(b, [at[i]])[0]; return { kind, building: b.id, at: point, screen: project(point) };
    }).filter(h => h.screen && h.screen[0] >= rect.left && h.screen[0] <= rect.right && h.screen[1] >= rect.top && h.screen[1] <= rect.bottom);
  }
  function clearGroup(group) {
    for (const object of [...group.children]) {
      object.removeFromParent(); object.geometry?.dispose(); object.material?.dispose();
    }
  }
  function line(outline, dashed, color) {
    const geometry = new THREE.BufferGeometry().setFromPoints([...outline, outline[0]].map(p => new THREE.Vector3(p[0] * FT, .025, -p[1] * FT)));
    const material = dashed ? new THREE.LineDashedMaterial({ color, dashSize: .6, gapSize: .3, depthTest: false })
      : new THREE.LineBasicMaterial({ color, depthTest: false });
    const object = new THREE.Line(geometry, material); object.computeLineDistances(); object.renderOrder = 2; graphics.add(object);
    return object;
  }
  function syncGraphics() {
    const unbuilt = place().buildings.filter(b => b.footprint?.length && !view.plan?.buildings.some(p => p.id === b.id));
    const key = JSON.stringify([lotOutline(), read()?.street_edge, suggestions(), unbuilt]);
    if (key === graphicKey) return;
    graphicKey = key; clearGroup(graphics);
    const outline = lotOutline();
    if (outline.length) {
      line(outline, false, '#a0afc1');
      const edge = read()?.street_edge || place().lot?.placement?.street_edge;
      if (edge?.length === 2 && edge.every(i => outline[i])) line(edge.map(i => outline[i]), false, '#52ccff');
    }
    suggestions().forEach(s => line(s.outline, true, '#52ccff'));
    unbuilt.forEach(b => line(b.footprint, false, '#52ccff'));
    if (openCard?.suggestion && !suggestions().some(s => s.id === openCard.suggestion)) closeCard();
  }
  function disposeSheet() {
    if (!sheet) return;
    sheet.removeFromParent(); sheet.geometry.dispose(); sheet.material.map?.dispose(); sheet.material.dispose(); sheet = null;
  }
  function syncSheet() {
    const r = read(), key = JSON.stringify(r && [r.source, r.page, r.matrix]);
    if (key === sheetKey) return;
    sheetKey = key; const version = ++sheetVersion; disposeSheet();
    if (!r?.matrix) return;
    let url = (window.chfBase ?? '../') + `api/house/editor/sheets/${encodeURIComponent(r.source)}/${r.page}.png`;
    if (window.chfAuthUrl) url = window.chfAuthUrl(url);
    new THREE.TextureLoader().load(url, texture => {
      if (disposed || version !== sheetVersion) { texture.dispose(); return; }
      const [a, b, c, d, e, f] = r.matrix;
      const at = (u, v) => [(a * u + c * v + e) * FT, .006, -(b * u + d * v + f) * FT];
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute([at(0, 1), at(1, 1), at(1, 0), at(0, 0)].flat(), 3));
      geometry.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
      geometry.setIndex([0, 1, 2, 0, 2, 3]); texture.colorSpace = THREE.SRGBColorSpace;
      sheet = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ map: texture, side: THREE.DoubleSide,
        transparent: true, opacity: .6, depthWrite: false, toneMapped: false }));
      sheet.renderOrder = 1; view.scene.add(sheet);
    }, undefined, () => { if (version === sheetVersion) report(new Error('The plot plan image could not load. Try reopening the editor.')); });
  }
  function refresh() {
    if (disposed) return;
    syncSheet(); syncGraphics();
    if (gesture?.client && (gesture.hit || gesture.drawing)) update({ pointerId: gesture.pointer,
      clientX: gesture.client[0], clientY: gesture.client[1] });
    if (openCard?.building && current()?.id !== openCard.building) closeCard();
    const descriptors = handles();
    while (rows.length < descriptors.length) {
      const node = document.createElement('span'); node.className = 'editor-handle editor-lot-handle'; layer.append(node); rows.push(node);
    }
    while (rows.length > descriptors.length) rows.pop().remove();
    descriptors.forEach((h, i) => {
      rows[i].textContent = h.kind === 'move' ? '↔' : '↻'; rows[i].title = h.kind === 'move' ? 'Move building' : 'Turn building';
      rows[i].style.left = `${h.screen[0]}px`; rows[i].style.top = `${h.screen[1]}px`;
    });
    card.hidden = !openCard || !available();
    frame = requestAnimationFrame(refresh);
  }
  function closeCard() { openCard = null; card.hidden = true; card.replaceChildren(); }
  function button(text, action) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.addEventListener('click', action, { signal }); return node;
  }
  // An answer (suggestion, street, confirm) closes its card; a building's own
  // move keeps the building card open so the person can go on or confirm.
  async function mutate(path, method, body, { keepCard = false } = {}) {
    if (!enabled()) return;
    busy = true; card.querySelectorAll('button, input, select').forEach(n => { n.disabled = true; });
    try { await request(path, method, body); if (!keepCard) closeCard(); await reload(); }
    catch (error) { report(error); }
    finally { busy = false; card.querySelectorAll('button, input, select').forEach(n => { n.disabled = false; }); }
  }
  function showCard() {
    card.hidden = false;
    card.append(button('Close', closeCard));
  }
  function suggestionCard(suggestion) {
    closeCard(); openCard = { suggestion: suggestion.id };
    const key = `${read().id}:${suggestion.id}`;
    if (!drafts.has(key)) drafts.set(key, { name: suggestion.name || '', kind: 'other', building: '' });
    card.append(plotSuggestionCard({ read: read(), suggestion, buildings: place().buildings,
      kinds: (getSheets().kinds || []).map(k => [k.id, k.label]), draft: drafts.get(key),
      answer: (path, body) => mutate(path, 'POST', body) })); showCard();
  }
  function streetCard(index) {
    closeCard(); openCard = { edge: index };
    card.append(button('This edge is the street', () => mutate('place/lot/placement', 'PUT', {
      street_edge: [index, (index + 1) % lotOutline().length], footprints: [] }))); showCard();
  }
  function buildingCard(b) {
    closeCard(); openCard = { building: b.id };
    const title = document.createElement('h3'); title.textContent = b.name || b.id; card.append(title);
    const note = document.createElement('p'); note.textContent = 'Drag the centre to move; drag the edge to turn. Arrow keys move one foot.'; card.append(note);
    card.append(button('Turn 90 degrees', () => {
      const h = handles().find(h => h.kind === 'move'); if (!h || !enabled()) return;
      const target = building(b.id), rotation = degrees((target.rotation || 0) + 90);
      const position = add(h.at, rotate(subtract(target.position, h.at), 90));
      commit(target, { rotation, position }, 'turn', h.at).catch(report);
    }));
    if (read()) card.append(button('These are in the right place', () => mutate('place/lot/placement', 'PUT', {
      street_edge: read().street_edge, footprints: [] })));
    showCard();
  }
  function focusBuilding(id) {
    drawing = null; selected = id; frameLot();
    const b = building(id); if (!b) { tools.drawFootprint(id); return; }
    if (!b.unbuilt) select({ id, building: id }); else select(null);
    canvas.tabIndex = 0; canvas.focus(); buildingCard(b);
  }
  function frameLot() {
    const outline = lotOutline(); if (!outline.length) return;
    view.setView('ext'); view.showLevels(Object.keys(view.groups.levels)); view.setCamera('front');
    const mid = centre(outline), span = Math.max(...[0, 1].map(i => Math.max(...outline.map(p => p[i])) - Math.min(...outline.map(p => p[i]))));
    view.controls.target.set(mid[0] * FT, 0, -mid[1] * FT);
    view.camera.position.set(mid[0] * FT, span * FT * 1.7, -(mid[1] - .01) * FT); view.controls.update();
  }
  function showLot() {
    frameLot(); drawing = null; selected = null; select(null); closeCard(); openCard = { lot: true };
    const title = document.createElement('h3'); title.textContent = 'Place on the lot'; card.append(title);
    for (const part of place().buildings) card.append(button(part.name, () => focusBuilding(part.id)));
    if (read()) lotOutline().forEach((_, i) => card.append(button(`Lot edge ${i + 1}`, () => streetCard(i))));
    showCard();
  }
  function previewBuilding(b) {
    if (b.unbuilt) return;
    const groups = [view.groups.roof, view.groups.gableFull, view.groups.gableCut, view.groups.lights, ...Object.values(view.groups.levels)];
    for (const parent of groups) for (const g of parent?.children || []) if (g.userData.buildingId === b.id) {
      g.position.set(b.position[0], groundAt(getPlan(), ...b.position) + (b.base || 0), -b.position[1]);
      g.rotation.y = (b.rotation || 0) * Math.PI / 180; g.updateMatrixWorld(true);
    }
  }
  async function commit(before, after, kind, about) {
    if (pauseBuilding() === before.id) { pauses.setLotTransform(after); return; }
    if (before.unbuilt) {
      await mutate(`place/buildings/${encodeURIComponent(before.id)}`, 'PATCH', { footprint: placed(after, footprint(before)), footprint_from: 'drawn' }, { keepCard: true });
      return;
    }
    busy = true;
    try {
      const operations = [], turned = angleOff(before.rotation || 0, after.rotation) > 1e-7;
      if (turned && kind === 'move') {
        // A snap that also turns is one rigid motion: one turn about its fixed
        // point lands the building exactly, in one round with no halfway state.
        const delta = after.rotation - (before.rotation || 0), a = delta * Math.PI / 180;
        const t = subtract(after.position, rotate(before.position || [0, 0], delta));
        const c = 1 - Math.cos(a), s = Math.sin(a), det = c * c + s * s;
        operations.push({ op: 'rotate_building', building: before.id, rotation: after.rotation,
          about: [(c * t[0] - s * t[1]) / det, (s * t[0] + c * t[1]) / det] });
      } else {
        if (turned) operations.push({ op: 'rotate_building', building: before.id, rotation: after.rotation, about });
        if (kind === 'move') operations.push({ op: 'move_building', building: before.id, to: after.position });
      }
      await op(operations);
    } finally { busy = false; previewBuilding(building(before.id) || before); }
  }
  function begin(event) {
    if (!enabled() || event.button !== 0) return false;
    if (!drawing && !pauseBuilding() && !sceneTool()) return false;
    const point = ground(event); if (!point) return false;
    const descriptors = handles();
    let hit = descriptors.find(h => distance(h.screen, [event.clientX, event.clientY]) <= 18);
    if (!hit && descriptors.length && !pauseBuilding()) {
      const kind = ['move', 'rotate'].find(id => document.getElementById(`rail-${id}`).getAttribute('aria-pressed') === 'true');
      const picked = kind && view.pick(event.clientX, event.clientY);
      if (picked?.building === current()?.id) hit = descriptors.find(h => h.kind === (kind === 'move' ? 'move' : 'turn'));
    }
    if (hit || drawing) {
      const b = hit && structuredClone(current());
      gesture = { pointer: event.pointerId, start: point, b, hit, drawing, x: event.clientX, y: event.clientY,
        client: [event.clientX, event.clientY], about: b && placed(b, [boxCentre(footprint(b))])[0], enabled: view.controls.enabled };
      view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); return true;
    }
    if (pauseBuilding() || view.state.view !== 'ext' || getSelection().room) return false;
    // Only outlines on open ground take precedence over the normal piece picker.
    if (view.pick(event.clientX, event.clientY)) return false;
    const outline = lotOutline();
    const edge = outline.findIndex((p, i) => {
      const a = project(p), b = project(outline[(i + 1) % outline.length]); if (!a || !b) return false;
      const d = subtract(b, a), q = subtract([event.clientX, event.clientY], a), n = d[0] ** 2 + d[1] ** 2;
      const t = n ? Math.max(0, Math.min(1, (q[0] * d[0] + q[1] * d[1]) / n)) : 0;
      return distance([event.clientX, event.clientY], add(a, d.map(v => v * t))) <= 10;
    });
    const suggestion = suggestions().find(s => contains(s.outline, point));
    const part = place().buildings.find(b => b.footprint?.length && !getPlan()?.buildings.some(p => p.id === b.id) && contains(b.footprint, point));
    if (edge < 0 && !suggestion && !part) { if (selected) selected = null; closeCard(); return false; }
    gesture = { pointer: event.pointerId, x: event.clientX, y: event.clientY, edge, suggestion, part };
    return true;
  }
  function update(event) {
    if (!gesture || gesture.pointer !== event.pointerId) return false;
    const g = gesture; g.client = [event.clientX, event.clientY];
    const point = ground(event); if (!point || !g.hit && !g.drawing) return true;
    g.moved = Math.hypot(event.clientX - g.x, event.clientY - g.y) >= 3;
    if (g.drawing) {
      const [x, y] = g.start, [a, b] = point;
      g.outline = [[Math.min(x, a), Math.min(y, b)], [Math.max(x, a), Math.min(y, b)], [Math.max(x, a), Math.max(y, b)], [Math.min(x, a), Math.max(y, b)]];
    } else {
      const before = g.b;
      let position = add(before.position || [0, 0], subtract(point, g.start)), rotation = before.rotation || 0;
      if (g.hit.kind === 'turn') {
        const a = subtract(g.start, g.about), b = subtract(point, g.about);
        const delta = Math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]) * 180 / Math.PI;
        rotation = degrees(snapRotation(rotation + delta));
        position = add(g.about, rotate(subtract(before.position, g.about), rotation - (before.rotation || 0)));
      }
      let transform = { position, rotation };
      if (g.moved && g.hit.kind === 'move') transform = snapFootprint(transform, footprint(before), suggestions()) || transform;
      g.preview = { ...before, ...transform }; previewBuilding(g.preview); g.outline = placed(g.preview, footprint(before));
    }
    document.getElementById('editor-drag-outline').setAttribute('points', g.outline.map(project).filter(Boolean).map(p => p.join(',')).join(' '));
    return true;
  }
  function finish(event, cancel) {
    if (!gesture || gesture.pointer !== event.pointerId) return false;
    if (!cancel) update(event);
    const g = gesture; gesture = null;
    if (g.enabled !== undefined) view.controls.enabled = g.enabled;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    document.getElementById('editor-drag-outline').setAttribute('points', '');
    if (cancel) { if (g.b) previewBuilding(g.b); return true; }
    if (g.drawing) {
      drawing = null; closeCard();
      if (g.moved) mutate(`place/buildings/${encodeURIComponent(g.drawing)}`, 'PATCH', { footprint: g.outline, footprint_from: 'drawn' });
    } else if (g.preview && g.moved) commit(g.b, g.preview, g.hit.kind, g.about).catch(report);
    else if (g.hit) previewBuilding(g.b);
    else if (!g.hit && Math.hypot(event.clientX - g.x, event.clientY - g.y) < 3) {
      if (g.edge >= 0 && read()) streetCard(g.edge);
      else if (g.suggestion) suggestionCard(g.suggestion);
      else if (g.part) focusBuilding(g.part.id);
    }
    return true;
  }
  document.addEventListener('keydown', event => {
    if (!enabled() || event.defaultPrevented || event.target.closest?.('input, textarea, select, [contenteditable="true"]')) return;
    if (event.key === 'Escape') { if (gesture) finish({ pointerId: gesture.pointer }, true); drawing = null; closeCard(); return; }
    const by = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[event.key];
    const b = current(), about = handles().find(h => h.kind === 'move')?.at;
    if (by && b && about) { event.preventDefault(); commit(b, { position: add(b.position, by), rotation: b.rotation || 0 }, 'move', about).catch(report); }
  }, { signal });
  signal.addEventListener('abort', () => {
    disposed = true; cancelAnimationFrame(frame); ++sheetVersion;
    if (gesture) finish({ pointerId: gesture.pointer }, true);
    disposeSheet(); clearGroup(graphics); graphics.removeFromParent(); layer.remove(); card.remove();
  }, { once: true });
  refresh();
  const tools = { pointerDown: begin, pointerMove: update, pointerUp: finish, focusBuilding, showLot,
    dragging: () => !!gesture?.hit || !!gesture?.drawing,
    lotHandles: handles,
    handles: () => handles().map(h => ({ kind: `building_${h.kind}`, id: h.building, at: [...h.at, 0] })),
    underlay: () => read() && sheet ? { source: read().source, page: read().page, opacity: .6, visible: sheet.visible && !!sheet.parent } : null,
    lotSuggestions: () => suggestions().map(s => ({ id: s.id, outline: s.outline, dashed: true })),
    drawFootprint(id) {
      frameLot(); selected = id; select(null); drawing = id; closeCard(); openCard = { drawing: id };
      const note = document.createElement('p'); note.textContent = 'Drag a rectangle on the ground for this building.'; card.append(note);
      card.append(button('Cancel drawing', () => { drawing = null; closeCard(); })); showCard();
    },
  };
  return tools;
}
