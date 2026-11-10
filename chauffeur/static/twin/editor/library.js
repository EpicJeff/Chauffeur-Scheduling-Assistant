import * as THREE from 'three';
import { contains, FT } from '../twin_generator.js';
import { groundAt } from '../twin_ground.js';
import { kitMaterial, loadModel, disposeObject } from '../twin_library.js';
import { request, report } from './api.js';

export const materialName = id => String(id || 'Material').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());

export function wallFace(building, wall, side) {
  const [a, b] = [wall.from, wall.to], length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const sign = side === 'left' ? 1 : -1, offset = (wall.thickness || 0) / 2 + .05;
  const point = [(a[0] + b[0]) / 2 - sign * (b[1] - a[1]) / length * offset,
    (a[1] + b[1]) / 2 + sign * (b[0] - a[0]) / length * offset];
  const room = building.rooms?.find(r => r.level === wall.level && r.state !== 'ghost' && contains(r.polygon, point));
  return { room, role: wall.exterior && !room ? 'siding' : 'interior_wall' };
}

// Each line names its material and where it comes from. `clear` is set when the
// surface itself holds it (Clear returns it to the inherited one); `reset` is the
// building's or the floor's own role, cleared from the card (I4); `surface` is
// what the card's Change applies to, through the same scope chooser as a drop.
export function materialLines(record, plan, kit) {
  const { piece, building, kind } = record;
  if (!building) return [];
  const level = building.levels?.find(l => l.id === piece.level);
  const line = (label, role, override, target, roomMaterial, surface) => {
    const ref = override || roomMaterial || level?.materials?.[role] || building.materials?.[role]
      || plan.materials?.[role] || kit?.materials?.[role];
    if (!ref) return null;
    const source = override ? 'set here' : `from the ${roomMaterial ? 'room' : level?.materials?.[role] ? 'level' : 'building'}`;
    const reset = override || roomMaterial ? null
      : level?.materials?.[role] ? { target: { level: level.id, role }, label: 'Clear for this floor' }
        : building.materials?.[role] ? { target: { building: building.id, role }, label: 'Clear for the building' } : null;
    const result = { label, text: `${materialName(ref.id || ref.asset)}, ${source}`, target, clear: !!override, reset };
    // Not enumerable: the card compares lines as text, never whole buildings.
    Object.defineProperty(result, 'surface', { value: { building, piece, kind, role, level: piece.level, ...surface } });
    return result;
  };
  if (kind === 'wall') return ['left', 'right'].map(side => {
    const face = wallFace(building, piece, side);
    // Which face a line speaks for: the room it faces, or the outside.
    const label = face.room ? face.room.name || 'Room' : face.role === 'siding' ? 'Outside' : 'Inside';
    // Room scope on an outside face refers to the room behind that wall.
    const room = face.room || wallFace(building, piece, side === 'left' ? 'right' : 'left').room;
    return line(label, face.role, piece.faces?.[side], { wall: piece.id, side }, face.room?.wall_material,
      { side, room, label: `${label.toLowerCase()} face` });
  }).filter(Boolean);
  if (kind === 'room') return [line('Floor', 'floor', piece.floor_material, { room: piece.id, surface: 'floor' }, null, { room: piece, surface: 'floor', label: 'floor' }),
    line('Ceiling', 'porch_ceiling', piece.ceiling_material, { room: piece.id, surface: 'ceiling' }, null, { room: piece, surface: 'ceiling', label: 'ceiling' }),
    piece.wall_material && line('Walls', 'interior_wall', piece.wall_material, { room: piece.id, surface: 'walls' }, null, { room: piece, surface: 'walls', label: 'walls' })].filter(Boolean);
  if (kind === 'roof') return [line('Roof', 'roof', piece.material, { roof: piece.roof || piece.id }, null, { label: 'roof' })].filter(Boolean);
  return [];
}

// The scope chooser's choices, surface first and the whole building last
// (spec 5.7: the surface, the room, the floor, the building).
export function scopeChoices(surface) {
  const floor = surface.level ? [['This floor', 'level']] : [];
  if (surface.kind === 'wall') return [['This wall face', 'face'], ['This room', 'room'], ...floor, ['The whole building', 'building']];
  if (surface.kind === 'room') return [['This room', 'face'], ...floor, ['The whole building', 'building']];
  return [['This roof', 'face'], ...floor, ['The whole building', 'building']];
}

export function surfaceOperation(surface, scope, material) {
  const { building, piece, kind, side, room, role } = surface;
  let target;
  if (scope === 'building') target = { building: building.id, role };
  else if (scope === 'level') {
    if (!surface.level) throw new Error('This surface is on no floor. Choose the surface or the whole building.');
    target = { level: surface.level, role };
  } else if (scope === 'room') {
    if (!room) throw new Error('This face has no room. Choose the face or the whole building.');
    target = { room: room.id, surface: kind === 'wall' ? 'walls' : surface.surface || 'floor' };
  } else target = kind === 'wall' ? { wall: piece.id, side }
    : kind === 'room' ? { room: piece.id, surface: surface.surface || 'floor' } : { roof: piece.roof || piece.id };
  return { op: 'set_material', building: building.id, target, material: { id: material.id, color: material.color } };
}

export function itemOperation(surface, item, ground) {
  if (item.kind !== 'furniture' || !surface) return { op: 'add_site_item',
    list: item.kind === 'furniture' ? 'furniture' : 'planting', asset: item.id, at: ground };
  const { building, piece, kind, point, side } = surface;
  let host;
  if (kind === 'wall') {
    const d = piece.to.map((v, i) => v - piece.from[i]), length = Math.hypot(...d);
    const elevation = building.levels.find(l => l.id === piece.level)?.elevation || 0;
    host = { wall: piece.id, side, at: point.slice(0, 2).reduce((n, v, i) => n + (v - piece.from[i]) * d[i] / length, 0), z: point[2] - elevation };
  } else if (kind === 'room') {
    const low = [0, 1].map(i => Math.min(...piece.polygon.map(p => p[i])));
    const high = [0, 1].map(i => Math.max(...piece.polygon.map(p => p[i])));
    host = { [surface.surface || 'floor']: piece.id, u: (point[0] - low[0]) / (high[0] - low[0]), v: (point[1] - low[1]) / (high[1] - low[1]) };
  } else {
    const area = building.roofs?.find(r => r.id === (piece.roof || piece.id))?.area || piece.area
      || [[piece.rect[0], piece.rect[1]], [piece.rect[2], piece.rect[1]], [piece.rect[2], piece.rect[3]], [piece.rect[0], piece.rect[3]]];
    const edges = area.map((a, i) => {
      const b = area[(i + 1) % area.length], d = b.map((v, k) => v - a[k]), length = Math.hypot(...d);
      const at = Math.max(0, Math.min(length, d.reduce((n, v, k) => n + v * (point[k] - a[k]) / length, 0)));
      return { edge: i, at, distance: Math.hypot(...a.map((v, k) => v + d[k] * at / length - point[k])) };
    }).sort((a, b) => a.distance - b.distance);
    host = { roof: piece.roof || piece.id, edge: edges[0].edge, at: edges[0].at, z: point[2] - (piece.plate || 0) };
  }
  return { op: 'add_item', building: building.id, asset: item.id, host };
}

// One detached canvas serves all thumbnails; only images remain in the panel.
function createThumbnails(kit) {
  const renderer = new THREE.WebGLRenderer({ canvas: document.createElement('canvas'), alpha: true, antialias: true });
  renderer.setSize(112, 96, false); renderer.setPixelRatio(1);
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(36, 112 / 96, .01, 100);
  const sun = new THREE.DirectionalLight('#fff3de', 3); sun.position.set(3, 5, 4);
  scene.add(new THREE.HemisphereLight('#ffffff', '#68764f', 2), sun);
  const cache = new Map(); let disposed = false;
  function render(object) {
    if (disposed) { disposeObject(object); return null; }
    const box = new THREE.Box3().setFromObject(object);
    if (box.isEmpty()) { disposeObject(object); object = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ color: '#b8b0a4' })); box.setFromObject(object); }
    const centre = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
    object.position.sub(centre); const distance = Math.max(size.x, size.y, size.z) * 2.3;
    camera.position.set(distance, distance * .65, distance); camera.lookAt(0, 0, 0);
    scene.add(object); renderer.render(scene, camera);
    const url = renderer.domElement.toDataURL('image/png'); object.removeFromParent(); disposeObject(object); return url;
  }
  function picture(entry, material) {
    const key = JSON.stringify([material, entry.id, entry.color]);
    if (!cache.has(key)) cache.set(key, (async () => {
      if (material) {
        const finish = kitMaterial('preview', { ...kit, materials: { preview: { asset: entry.id, color: entry.color } } }, 'low');
        await finish.userData.ready;
        return render(new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), finish));
      }
      if (entry.kind === 'furniture') return render(await loadModel(entry.id, kit) || new THREE.Group());
      const { Tree } = await import('@dgreenheck/ez-tree');
      const tree = new Tree(); tree.loadPreset(entry.id); tree.options.seed = 1; tree.generate();
      // EZ-Tree owns shared texture maps. Release only this preview's geometry.
      tree.traverse(o => {
        if (!o.isMesh) return;
        const convert = m => new THREE.MeshStandardMaterial({ color: m.map ? '#ffffff' : m.color,
          map: m.map?.clone(), alphaMap: m.alphaMap?.clone(), alphaTest: Math.max(.5, m.alphaTest || 0), side: m.side, roughness: .9 });
        o.material = Array.isArray(o.material) ? o.material.map(convert) : convert(o.material);
      });
      return render(tree);
    })());
    return cache.get(key);
  }
  return { picture, dispose() { disposed = true; renderer.dispose(); renderer.forceContextLoss(); } };
}

export function createLibrary({ view, kit, getPlan, tools, op, canEdit, signal, onInteract }) {
  const el = id => document.getElementById(id), canvas = view.renderer3.domElement, host = el('library-panel');
  const raycaster = new THREE.Raycaster(), thumbnails = { current: null };
  let catalog = null, loading = null, tab = 'materials', drag = null, siteDrag = null, chooser = null, picking = null;
  const hint = 'Drag a thumbnail onto the house or yard.';
  const outline = new THREE.Box3Helper(new THREE.Box3(), '#52ccff'); outline.visible = false; view.scene.add(outline);
  const listen = (node, type, action, options = {}) => node.addEventListener(type, action, { ...options, signal });
  function ray(event) {
    const r = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - r.left) / r.width * 2 - 1, 1 - (event.clientY - r.top) / r.height * 2), view.camera);
    return raycaster.ray;
  }
  function local(building, p) {
    const a = -(building.rotation || 0) * Math.PI / 180, pos = building.position || [0, 0];
    const x = p.x / FT - pos[0], y = -p.z / FT - pos[1];
    return new THREE.Vector3(Math.cos(a) * x - Math.sin(a) * y, Math.sin(a) * x + Math.cos(a) * y,
      p.y / FT - (building.base || 0) - groundAt(getPlan(), ...pos));
  }
  function ground(event) {
    const r = ray(event), point = r.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), new THREE.Vector3());
    if (!point) return null;
    for (let i = 0; i < 3; i++) r.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -groundAt(getPlan(), point.x / FT, -point.z / FT) * FT), point);
    return [point.x / FT, -point.z / FT];
  }
  function surfaceAt(event) {
    const picked = view.pick(event.clientX, event.clientY); if (!picked) return null;
    const building = getPlan().buildings.find(b => b.id === picked.building);
    let kind = picked.kind, id = picked.id;
    if (['opening', 'anchor', 'item', 'fixture', 'light'].includes(kind)) {
      const attached = ['openings', 'anchors', 'items'].flatMap(name => building?.[name] || []).find(p => p.id === id);
      const host = attached?.host;
      if (host?.wall || attached?.wall) { kind = 'wall'; id = host?.wall || attached.wall; }
      else if (host?.floor || host?.ceiling) { kind = 'room'; id = host.floor || host.ceiling; }
      else if (host?.roof) { kind = 'roof'; id = host.roof; }
    }
    const piece = building?.[kind === 'wall' ? 'walls' : kind === 'room' ? 'rooms' : 'unused']?.find(p => p.id === id)
      || (kind === 'roof' && building?.roof?.sections.find(p => p.id === id || p.roof === id));
    if (!piece || !['wall', 'room', 'roof'].includes(kind)) return null;
    const worldRay = ray(event), origin = local(building, worldRay.origin), direction = local(building, worldRay.origin.clone().add(worldRay.direction)).sub(origin).normalize();
    const r = new THREE.Ray(origin, direction), elevation = building.levels.find(l => l.id === piece.level)?.elevation || 0;
    let point, side, room = kind === 'room' ? piece : null, role = kind === 'room' ? 'floor' : 'roof', surface = 'floor';
    if (kind === 'wall') {
      const d = piece.to.map((v, i) => v - piece.from[i]), length = Math.hypot(...d), normal = new THREE.Vector3(-d[1] / length, d[0] / length, 0);
      side = normal.dot(origin.clone().sub(new THREE.Vector3(...piece.from, 0))) >= 0 ? 'left' : 'right';
      point = r.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(normal, new THREE.Vector3(...piece.from, 0)), new THREE.Vector3());
      const face = wallFace(building, piece, side); role = face.role; room = face.room;
      // Room scope on an outside face refers to the room behind that wall.
      room ||= wallFace(building, piece, side === 'left' ? 'right' : 'left').room;
    } else if (kind === 'room') {
      surface = direction.z > 0 ? 'ceiling' : 'floor'; role = surface === 'floor' ? 'floor' : 'porch_ceiling';
      point = r.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), -elevation - (surface === 'ceiling' ? building.levels.find(l => l.id === piece.level).ceiling : 0)), new THREE.Vector3());
    } else {
      const hit = raycaster.intersectObjects(view.scene.children, true).find(h => h.object.userData.kind === 'roof' && h.object.userData.buildingId === building.id);
      point = hit && local(building, hit.point);
    }
    return point && { building, kind, piece, point: point.toArray(), side, room, role, surface, level: piece.level };
  }
  // In the floor cutaway the ceiling has no rendered slab to raycast. An
  // explicit ceiling placement still uses its real plane and room boundary.
  function ceilingAt(event, fromBelow = false) {
    const selected = tools.selection();
    const building = getPlan()?.buildings.find(b => b.id === selected.building);
    const room = building?.rooms.find(r => r.id === selected.room && r.state !== 'ghost');
    if (!room) return null;
    const level = building.levels.find(l => l.id === room.level);
    if (!level) return null;
    const worldRay = ray(event), origin = local(building, worldRay.origin);
    const direction = local(building, worldRay.origin.clone().add(worldRay.direction)).sub(origin).normalize();
    if (fromBelow && direction.z <= 0) return null;
    const point = new THREE.Ray(origin, direction).intersectPlane(
      new THREE.Plane(new THREE.Vector3(0, 0, 1), -(level.elevation || 0) - level.ceiling), new THREE.Vector3());
    if (!point || !contains(room.polygon, [point.x, point.y])) return null;
    return { building, kind: 'room', piece: room, point: point.toArray(), room, role: 'porch_ceiling', surface: 'ceiling', level: room.level };
  }
  function dismiss() { chooser?.remove(); chooser = null; }
  const pickingWords = () => `Choose a material for the ${picking?.label || 'surface'}.`;
  function stopPicking() {
    if (!picking) return;
    picking = null; el('library-status').textContent = hint;
  }
  function choose(surface, material, event) {
    dismiss(); chooser = document.createElement('div'); chooser.id = 'material-chooser'; chooser.setAttribute('role', 'group'); chooser.setAttribute('aria-label', 'Apply material');
    chooser.style.left = `${Math.max(96, Math.min(event.clientX, window.innerWidth - 240))}px`;
    chooser.style.top = `${Math.max(74, Math.min(event.clientY, window.innerHeight - 240))}px`;
    for (const [label, scope] of [...scopeChoices(surface), ['Cancel', null]]) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
      listen(button, 'click', () => {
        if (!scope) { dismiss(); return; }
        if (!canEdit()) return;
        try { const operation = surfaceOperation(surface, scope, material); dismiss(); stopPicking(); op(operation).catch(report); } catch (error) { report(error); }
      }); chooser.append(button);
    }
    el('editor-scene').parentElement.append(chooser); chooser.querySelector('button').focus();
  }
  // The card's Change (spec 5.7, pick it on the card): the same list opens on
  // its materials, and a thumbnail pressed (mouse, Enter or Space) goes to the
  // same scope chooser as a drop.
  async function pick(surface) {
    if (!canEdit()) return;
    dismiss(); picking = surface; tab = 'materials';
    if (host.hidden) { host.hidden = false; el('rail-library').setAttribute('aria-pressed', 'true'); }
    el('library-status').textContent = pickingWords();
    await browse();
    el('library-entries').querySelector('button')?.focus();
  }
  async function browse() {
    if (!catalog) {
      loading ||= request('library').catch(error => { loading = null; throw error; });
      catalog = await loading;
    }
    if (signal.aborted) return;
    thumbnails.current ||= createThumbnails(kit);
    const grid = el('library-entries'); grid.replaceChildren();
    for (const entry of catalog[tab]) {
      const button = document.createElement('button'); button.type = 'button'; button.dataset[tab === 'materials' ? 'material' : 'item'] = entry.id;
      button.setAttribute('aria-label', entry.name); button.style.touchAction = 'none';
      const image = document.createElement('img'); image.alt = ''; image.draggable = false; image.width = 112; image.height = 96;
      const name = document.createElement('span'); name.textContent = entry.name; button.append(image, name); grid.append(button);
      thumbnails.current.picture(entry, tab === 'materials').then(url => { if (url && !signal.aborted) image.src = url; }).catch(report);
      listen(button, 'pointerdown', event => {
        if (event.button !== 0 || !canEdit()) return;
        onInteract?.(); dismiss(); event.preventDefault(); button.setPointerCapture(event.pointerId);
        drag = { entry, material: tab === 'materials', x: event.clientX, y: event.clientY, pointer: event.pointerId };
      });
      listen(button, 'click', () => {
        if (!picking || tab !== 'materials' || !canEdit()) return;
        const r = button.getBoundingClientRect?.() || { left: 0, top: 0, width: 0 };
        choose(picking, entry, { clientX: r.left + r.width / 2, clientY: r.top });
      });
    }
    host.querySelectorAll('[data-library-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.libraryTab === tab)));
    el('library-status').textContent = picking ? pickingWords() : hint;
  }
  listen(el('rail-library'), 'click', () => {
    host.hidden = !host.hidden; el('rail-library').setAttribute('aria-pressed', String(!host.hidden));
    if (host.hidden) stopPicking();
    if (!host.hidden) browse().catch(error => { el('library-status').textContent = 'Could not load the library. Open it again to retry.'; report(error); });
  });
  for (const button of host.querySelectorAll('[data-library-tab]')) listen(button, 'click', () => {
    tab = button.dataset.libraryTab; if (tab !== 'materials') stopPicking(); browse().catch(report);
  });
  listen(document, 'pointerup', event => {
    if (!drag || drag.pointer !== event.pointerId) return;
    const moved = drag; drag = null;
    if (!canEdit() || Math.hypot(event.clientX - moved.x, event.clientY - moved.y) < 3) return;
    if (!canvas.contains(document.elementFromPoint(event.clientX, event.clientY))) return;
    const surface = surfaceAt(event);
    if (moved.material) { if (surface) choose(surface, moved.entry, event); return; }
    const at = ground(event); if (!surface && (!at || !contains(getPlan().site?.lot || [], at))) return;
    op(itemOperation(surface, moved.entry, at)).catch(report);
  }, { capture: true });
  listen(document, 'pointercancel', () => { drag = null; });
  listen(document, 'keydown', event => {
    if (event.key !== 'Escape' || !chooser && !picking) return;
    if (chooser) dismiss(); else stopPicking();
    event.stopImmediatePropagation();
  }, { capture: true });

  function siteBox(piece, kind) {
    const height = kind === 'planting' ? piece.height || 4 : 3, radius = kind === 'planting' ? Math.max(1, height * .18) : 2;
    const y = groundAt(getPlan(), ...piece.at), [x, z] = piece.at;
    return new THREE.Box3(new THREE.Vector3((x - radius) * FT, y * FT, -(z + radius) * FT),
      new THREE.Vector3((x + radius) * FT, (y + height) * FT, -(z - radius) * FT));
  }
  function pickSite(x, y) {
    const r = ray({ clientX: x, clientY: y }); let nearest = null;
    for (const kind of ['planting', 'furniture']) for (const [index, piece] of (getPlan()?.site?.[kind] || []).entries()) {
      if (!piece.at) continue;
      const point = r.intersectBox(siteBox(piece, kind), new THREE.Vector3());
      if (!point) continue;
      const distance = point.distanceTo(r.origin);
      if (!nearest || distance < nearest.distance) nearest = { kind, id: piece.id || `${kind}:${index}`, distance };
    }
    if (!nearest) return null;
    const picked = view.pick(x, y), box = picked && view.worldBox(picked.id, picked.building);
    if (box) {
      const point = r.intersectBox(new THREE.Box3(new THREE.Vector3(box.min[0] * FT, box.min[2] * FT, -box.max[1] * FT),
        new THREE.Vector3(box.max[0] * FT, box.max[2] * FT, -box.min[1] * FT)), new THREE.Vector3());
      if (point && point.distanceTo(r.origin) < nearest.distance) return null;
    }
    return { kind: nearest.kind, id: nearest.id };
  }
  function refresh() {
    const selected = tools.selection(), kind = selected.kind;
    const piece = ['planting', 'furniture'].includes(kind) && getPlan()?.site?.[kind]?.find((p, i) => (p.id || `${kind}:${i}`) === selected.id);
    outline.visible = !!piece;
    if (piece) outline.box.copy(siteBox(piece, kind));
  }
  function pointerDown(event) {
    if (!canEdit() || event.button !== 0 || tools.handleAt?.(event)) return false;
    const picked = pickSite(event.clientX, event.clientY); if (!picked) return false;
    onInteract?.(); tools.select(picked);
    refresh();
    const index = getPlan().site[picked.kind].findIndex((p, i) => (p.id || `${picked.kind}:${i}`) === picked.id), piece = getPlan().site[picked.kind][index];
    const start = ground(event); if (!start) return false;
    siteDrag = { ...picked, index, start, at: [...piece.at], x: event.clientX, y: event.clientY, enabled: view.controls.enabled };
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); return true;
  }
  function pointerUp(event, cancel) {
    if (!siteDrag) return false;
    const g = siteDrag; siteDrag = null; view.controls.enabled = g.enabled;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    refresh();
    if (!cancel && canEdit() && Math.hypot(event.clientX - g.x, event.clientY - g.y) >= 3) {
      const at = ground(event);
      if (at) op({ op: 'move_site_item', list: g.kind, index: g.index, at: at.map((v, i) => v + g.at[i] - g.start[i]) }).catch(report);
    }
    return true;
  }
  function pointerMove(event) {
    if (!siteDrag) return false;
    const at = ground(event), piece = getPlan().site[siteDrag.kind][siteDrag.index];
    if (at) outline.box.copy(siteBox({ ...piece, at: at.map((v, i) => v + siteDrag.at[i] - siteDrag.start[i]) }, siteDrag.kind));
    return true;
  }
  view.controls.addEventListener('change', refresh);
  listen(canvas.parentElement, 'twinrebuilt', refresh);
  signal.addEventListener('abort', () => {
    dismiss(); thumbnails.current?.dispose(); if (siteDrag) view.controls.enabled = siteDrag.enabled;
    view.controls.removeEventListener('change', refresh); outline.removeFromParent(); outline.geometry.dispose(); outline.material.dispose();
  }, { once: true });
  return { pickSite, surfaceAt, ceilingAt, pointerDown, pointerMove, pointerUp, refresh, pick };
}
