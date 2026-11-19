import { slotDragTarget, sendSlotDrag } from './slot_row.js';
import { snapValue } from './snap.js';
import { createTypedValue } from './typed_value.js';
import { applyLocal } from './local_ops.js';
import { DRAG_THRESHOLD_PX } from './picking.js';
import * as THREE from 'three';
import { svgIcon } from '../live/glance_icons.js';
import { contains, FT, allPorches } from '../twin_generator.js';
import { ITEM_PARTS, kindRow } from '../surface_kinds.js';
import { groundAt, buildingGround, inPolygon, edgeDistance } from '../twin_ground.js';
import { kitMaterial, loadModel, disposeObject } from '../twin_library.js';
import { rememberImport, forgetImport, libUrl, materialUrl } from '../twin_library.js';
import { mountImports } from './imports.js';
import { objectShown, siteRecords, siteRecord, sitePoints, siteShapeKinds } from '../objects.js';
import { pathSurfacePolygons } from '../path_shapes.js';
import { request, report } from './api.js';

import { materialName, describeMaterial, readLibraryCatalog, surfaceDescription } from './material_catalog.js';
import { resolveSurfaceMaterial } from '../surface_material.js';
import { planes } from '../twin_roof.js';
export { materialName } from './material_catalog.js';
export const libraryMaterialHref = id => (window.chfBase ?? '../') + 'house/library?material=' + encodeURIComponent(id);

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
// the surface assigned by the row (the 3D drop keeps its scope chooser).
export function materialLines(record, plan, kit) {
  const { piece, building } = record;
  const kind = record.kind === 'roof' && building?.dormers?.some(d => d.id === piece.id) ? 'dormer' : record.kind;
  if (!building) return [];
  const level = building.levels?.find(l => l.id === piece.level) || (['roof','dormer'].includes(kind)
    ? [...(building.levels || [])].filter(l => l.elevation + .5 < piece.plate).sort((a,b) => b.elevation-a.elevation)[0] : null);
  const line = (label, role, override, target, roomMaterial, surface, extra = {}) => {
    const descriptor = () => ({ role, ref: override, building, level, ...extra,
      ...(extra.itemColour && !override?.id ? {building:null,level:null} : {}) });
    const description = () => {
      const itemColour = extra.itemColour && !override?.id;
      const result = surfaceDescription(itemColour ? {} : plan, descriptor(), kit);
      if (itemColour) result.current.id = null; // A raw item colour has no Library tile to reveal.
      return result;
    };
    const reset = override || roomMaterial ? null
      : level?.materials?.[role] ? { target: { level: level.id, role }, label: 'Clear for this floor' }
        : building.materials?.[role] ? { target: { building: building.id, role }, label: 'Clear for the building' } : null;
    const result = { label, get current() { return description().current; }, get text() { return description().text; },
      get inherited() { return description().inherited; }, get ref() { return override; }, get resolved() { return description().ref; },
      target, clear: !!override, reset: target.part ? null : reset };
    // Not enumerable: the card compares lines as text, never whole buildings.
    Object.defineProperty(result, 'surface', { value: { building, piece, kind, role, level: level?.id || piece.level, ...surface } });
    Object.defineProperty(result, 'setRef', { value: ref => { override = ref; } });
    return result;
  };
  const itemLine = (part, item = piece, targetKind = kind) => {
    const row = kindRow(part), fallback = row.fallback;
    const itemLevel = building.levels?.find(l => l.id === (item.level || building.walls?.find(w => w.id === item.wall)?.level));
    const colour = part === 'cabinet' ? item.body : part === 'counter' ? item.top : null;
    const parent = fallback.role ? resolveSurfaceMaterial(plan, {role:fallback.role, building,
      level:part === 'garage_door' ? itemLevel : null, kit}) : null;
    const labels = { window_frame: 'Frame', pane: 'Pane', door: 'Door', screen: 'Screen', stair_tread: 'Treads', stair_rail: 'Rail', counter: 'Counter' };
    const target = { [targetKind]: item.id, part };
    return line(labels[part] || row.label, part, item.materials?.[part], target, null,
      { kind: targetKind, piece: item, target, label: `${item.name || item.kind || targetKind} ${labels[part] || row.label}` },
      { level:itemLevel, itemColour:!!colour, fallback:colour ? {ref:{id:`Item colour ${colour}`,color:colour},source:{kind:'kit',id:`Item colour ${colour}`}} : parent,
        defaultRef:{id:fallback.builtin || fallback.look || 'ceramic'} });
  };
  if (kind === 'opening') {
    const parts = piece.kind === 'door' ? ['door', 'casing', 'window_frame', ...(piece.glass === 'half' ? ['pane'] : [])]
      : piece.kind === 'garage' ? ['garage_door', ...(piece.style === 'full_view' || piece.lites === 'top' ? ['pane'] : []), 'window_frame', 'casing'] : piece.kind === 'passage' ? [] : ['window_frame', 'casing', 'pane'];
    return parts.filter(part => ITEM_PARTS.opening.includes(part)).map(part => itemLine(part));
  }
  if (kind === 'stair') return ITEM_PARTS.stair.filter(part => part !== 'stair_rail' || (piece.rail || 'none') !== 'none' || piece.style === 'open').map(part => itemLine(part));
  if (['item', 'fixture'].includes(kind) && piece.rect) return (['counter', 'vanity'].includes(piece.kind) ? ['cabinet', 'counter']
    : piece.kind === 'shower' ? ['shower_tile', 'shower_glass'] : []).filter(part => ITEM_PARTS.fixture.includes(part)).map(part => itemLine(part, piece, 'item'));
  const porch = kind === 'room' && piece.kind === 'porch'
    ? [...allPorches(building), ...(building.porches_detail || [])].find(p => p.id === piece.id) || piece : kind === 'porch' ? piece : null;
  const porchLines = porch ? ITEM_PARTS.porch.filter(part => part !== 'screen' || porch.screened).map(part => itemLine(part, porch, 'porch')) : [];
  if (kind === 'porch') return porchLines;
  if (kind === 'wall') return ['left', 'right'].map(side => {
    const face = wallFace(building, piece, side);
    // Which face a line speaks for: the room it faces, or the outside.
    const label = face.room ? face.room.name || 'Room' : face.role === 'siding' ? 'Outside' : 'Inside';
    // Room scope on an outside face refers to the room behind that wall.
    const room = face.room || wallFace(building, piece, side === 'left' ? 'right' : 'left').room;
    return line(label, face.role, piece.faces?.[side], { wall: piece.id, side }, face.room?.wall_material,
      { side, room, label: `${label.toLowerCase()} face` }, { room:face.room, roomRole:'wall' });
  }).filter(Boolean);
  if (kind === 'room') return [line('Floor', 'floor', piece.floor_material, { room: piece.id, surface: 'floor' }, null, { room: piece, surface: 'floor', label: 'floor' }),
    line('Ceiling', piece.kind === 'porch' ? 'porch_ceiling' : 'ceiling', piece.ceiling_material, { room: piece.id, surface: 'ceiling' }, null, { room: piece, surface: 'ceiling', label: 'ceiling' }),
    line('Walls', 'interior_wall', piece.wall_material, { room: piece.id, surface: 'walls' }, null, { room: piece, surface: 'walls', label: 'walls' }), ...porchLines].filter(Boolean);
  if (kind === 'roof') {
    const id = piece.roof || piece.id, authored = building.roofs?.find(r => r.id === id);
    const sections = (building.roof?.sections || []).filter(s => !s.dormer_of && (s.roof || s.id) === id);
    const roof = authored || piece, planeRows = [], seen = new Set();
    for (const section of sections.length ? sections : piece.rect ? [piece] : []) for (const plane of planes(section)) {
      if (plane.edge === null || seen.has(plane.edge)) continue;
      seen.add(plane.edge);
      const normals = {x0:[-1,0],x1:[1,0],y0:[0,-1],y1:[0,1]}, normal = normals[plane.side];
      const angle = (building.rotation || 0) * Math.PI / 180;
      const x = normal && normal[0]*Math.cos(angle)-normal[1]*Math.sin(angle), y = normal && normal[0]*Math.sin(angle)+normal[1]*Math.cos(angle);
      const side = Math.abs(x) > .999 ? x > 0 ? 'Right' : 'Left' : Math.abs(y) > .999 ? y > 0 ? 'Back' : 'Front' : null;
      const label = side ? `${side} slope` : `Slope ${planeRows.length + 1}`;
      const target = {roof:id,plane:plane.edge};
      planeRows.push(line(label, 'roof', roof.plane_materials?.[plane.edge], target, null,
        {target, label:label.toLowerCase()}, {parents:[roof.material, section.materials?.roof], parentLabel:'From the roof'}));
    }
    // Concave roofs may have multiple authored edges on the same side.
    const counts = new Map(); for (const row of planeRows) counts.set(row.label, (counts.get(row.label) || 0) + 1);
    for (const row of planeRows) if (counts.get(row.label) > 1) row.label += ` ${row.target.plane + 1}`;
    return [line('Roof', 'roof', roof.material, { roof:id }, null, { label:'roof' }), ...planeRows];
  }
  if (kind === 'dormer') return [line('Roof', 'roof', piece.material, { dormer: piece.id }, null, { label: 'roof' })].filter(Boolean);
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
  if (role === 'water' && ['pool', 'spa'].includes(kind)) return kind === 'pool'
    ? { op: 'update_site_shape', list: 'pool', ...(piece.id ? { id: piece.id } : { index: 0 }), materials: { water: { id: material.id } } }
    : { op: 'update_pool_feature', id: piece.id, materials: { water: { id: material.id } } };
  if (surface.target?.part || scope === 'face' && surface.target?.plane !== undefined) return { op: 'set_material', building: building.id, target: surface.target, material: { id: material.id } };
  let target;
  if (scope === 'building') target = { building: building.id, role };
  else if (scope === 'level') {
    if (!surface.level) throw new Error('This surface is on no floor. Choose the surface or the whole building.');
    target = { level: surface.level, role };
  } else if (scope === 'room') {
    if (!room) throw new Error('This face has no room. Choose the face or the whole building.');
    target = { room: room.id, surface: kind === 'wall' ? 'walls' : surface.surface || 'floor' };
  } else target = kind === 'wall' ? { wall: piece.id, side }
    : kind === 'room' ? { room: piece.id, surface: surface.surface || 'floor' }
      : kind === 'dormer' ? { dormer: piece.id } : { roof: piece.roof || piece.id };
  return { op: 'set_material', building: building.id, target, material: { id: material.id } };
}

export function itemOperation(surface, item, ground) {
  if (item.id?.startsWith('import-')) {
    if (['door', 'window'].includes(item.kind)) {
      if (surface?.kind !== 'wall') throw new Error('Drop doors and windows onto a wall.');
      const wall = surface.piece, d = wall.to.map((v, i) => v - wall.from[i]), length = Math.hypot(...d);
      const at = surface.point.slice(0, 2).reduce((n, v, i) => n + (v - wall.from[i]) * d[i] / length, 0);
      return { op: 'add_opening', building: surface.building.id, wall: wall.id, kind: item.kind, model: item.id,
        at, width: item.kind === 'door' ? 3 : 4, sill: item.kind === 'door' ? 0 : 3, head: 7 };
    }
    if (item.kind === 'plant' || !surface) {
      if (!ground) throw new Error('Drop this model onto the ground.');
      return { op: 'add_site_item', list: item.kind === 'plant' ? 'planting' : 'furniture', asset: item.id, object_kind: item.kind, at: ground };
    }
    if (surface.kind !== 'room' || surface.surface === 'ceiling') throw new Error('Drop this model onto a floor or the ground.');
    return { ...itemOperation(surface, { ...item, id: 'placement-proxy', kind: 'furniture' }, ground), asset: item.id, object_kind: item.kind };
  }
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
    const key = JSON.stringify([material, entry.id, entry.color, entry.revision]);
    if (!cache.has(key)) cache.set(key, (async () => {
      if (material) {
        const ref = kit.materials?.[entry.id] || Object.values(kit.materials || {}).find(r => r.asset === entry.id);
        const finish = kitMaterial('preview', { ...kit, materials: { preview: { ...ref, asset: entry.id, color: entry.color } } }, 'low');
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

export function createLibrary({ view, kit, getPlan, tools, op, canEdit, signal, onInteract, dock, dialogs, createMenu }) {
  const el = id => document.getElementById(id), canvas = view.renderer3.domElement, host = el('library-panel');
  const raycaster = new THREE.Raycaster(), thumbnails = { current: null };
  let catalog = null, loading = null, tab = 'materials', drag = null, siteDrag = null, chooser = null;
  const importNodes = new Map();
  let browsePending = false, selection = null, dragRow = null, suppressClick = false, actionEntry = null;
  let browsing = null, catalogRevision = 0;
  const selectionListeners = new Set();
  const tiles = new Map();
  const hint = 'Drag a thumbnail onto the house or yard.';
  const outline = new THREE.Box3Helper(new THREE.Box3(), '#52ccff'); outline.visible = false; view.scene.add(outline);
  outline.material.fog = false;
  const listen = (node, type, action, options = {}) => node.addEventListener(type, action, { ...options, signal });
  const rowMenu = createMenu?.({ signal, items: target => target.actions.map(node => ({ label: node.textContent,
    disabled: node.disabled, run: () => node.click() })) });
  const asset = (entry, material = entry.kind === 'material') => ({ ...entry,
    kind: material ? 'material' : entry.kind || 'furniture',
    thumb: entry.thumbnail_url || (entry.thumbnail ? libUrl(entry.id, entry.thumbnail) : entry.thumb) || null });
  function assetActions(entry, material) {
    const actions = [];
    if (material) {
      const edit = document.createElement('a'); edit.textContent = 'Edit in Library'; edit.href = libraryMaterialHref(entry.id);
      edit.target = '_blank'; edit.rel = 'noopener'; edit.className = 'library-edit-link';
      edit.setAttribute('aria-label', 'Edit in Library'); actions.push(edit);
    }
    if (entry.id.startsWith('import-')) for (const action of ['Rename', 'Delete']) {
      const control = document.createElement('button'); control.type = 'button'; control.textContent = `${action} ${entry.name}`;
      control.dataset.libraryAction = action;
      control.disabled = !canEdit();
      control.addEventListener('click', async () => {
        if (!canEdit() || signal.aborted) return;
        try {
          if (action === 'Rename') {
            const name = await window.promptInput('Model name', 'Name this model.', { value: entry.name });
            if (name?.trim()) await changedImport(await request('imports/' + entry.id, 'PATCH', { name: name.trim() }));
          } else if (await window.promptConfirm(`Delete ${entry.name}?`, 'Placed models must be removed from the scene first. Earlier timeline placements retain their files.', 'Delete', 'Cancel')) {
            importsQueue?.cancel(entry.id);
            await request('imports/' + entry.id, 'DELETE');
            forgetImport(entry.id);
            await changedImport(entry, { removed: true });
          }
        } catch (error) { report(error); }
      });
      actions.push(control);
    }
    return actions;
  }
  function drawSelection() {
    for (const { button, entry, material } of tiles.values())
      button.setAttribute('aria-pressed', String(!!selection && selection.id === entry.id && selection.kind === asset(entry, material).kind));
    const bar = el('library-actions');
    if (!bar) return;
    bar.hidden = !selection;
    if (!selection) { bar.replaceChildren(); actionEntry = null; return; }
    if (actionEntry?.id === selection.id && (actionEntry.kind === 'material') === (selection.kind === 'material')) {
      Object.assign(actionEntry, selection);
      for (const node of bar.querySelectorAll('button')) if (node.dataset.libraryAction) {
        node.textContent = `${node.dataset.libraryAction} ${selection.name}`; node.disabled = !canEdit();
      }
      return;
    }
    actionEntry = { ...selection };
    bar.replaceChildren(); bar.append(...assetActions(actionEntry, selection.kind === 'material'));
    const clear = document.createElement('button'); clear.type = 'button'; clear.textContent = 'Clear selection';
    clear.addEventListener('click', () => select(null)); bar.append(clear);
  }
  function select(entry) {
    selection = entry ? asset(entry) : null;
    drawSelection();
    for (const fn of selectionListeners) fn(selection);
  }
  function syncSelection() {
    if (selection && catalog) {
      const entry = [...catalog.materials.map(e => asset(e, true)), ...catalog.items.map(e => asset(e, false)),
        ...(catalog.imports || []).filter(e => !e.archived).map(e => asset(e, false))]
        .find(e => e.id === selection.id);
      select(entry || null);
    } else drawSelection();
  }
  async function reveal(kind, id) {
    tab = kind === 'material' ? 'materials' : 'items';
    if (el('library-search')) el('library-search').value = '';
    host.hidden = false; el('rail-library').setAttribute('aria-pressed', 'true'); dock?.show('library');
    await browse();
    if (signal.aborted) return;
    const button = tiles.get(id)?.button;
    if (button) {
      button.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      button.classList.remove('library-revealed');
      // Restart the reveal ring even when the same swatch is pressed twice.
      void button.offsetWidth; button.classList.add('library-revealed');
    }
  }
  function updateDragRow(event, entry) {
    const next = slotDragTarget(document.elementFromPoint(event.clientX, event.clientY));
    if (next !== dragRow) sendSlotDrag(dragRow, 'leave', entry);
    dragRow = next; sendSlotDrag(dragRow, 'over', entry);
    return dragRow;
  }
  if (dialogs) listen(el('library-import-settings').querySelector('summary'), 'click', event => {
    event.preventDefault();
    dialogs.openDialog('library-import-settings-content', { title: 'Import settings' });
  });
  function ray(event) {
    const r = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - r.left) / r.width * 2 - 1, 1 - (event.clientY - r.top) / r.height * 2), view.camera);
    return raycaster.ray;
  }
  function local(building, p) {
    const a = -(building.rotation || 0) * Math.PI / 180, pos = building.position || [0, 0];
    const x = p.x / FT - pos[0], y = -p.z / FT - pos[1];
    return new THREE.Vector3(Math.cos(a) * x - Math.sin(a) * y, Math.sin(a) * x + Math.cos(a) * y,
      p.y / FT - (building.base || 0) - buildingGround(getPlan(), building));
  }
  function ground(event) {
    const r = ray(event), point = r.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), new THREE.Vector3());
    if (!point) return null;
    for (let i = 0; i < 3; i++) r.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -groundAt(getPlan(), point.x / FT, -point.z / FT) * FT), point);
    return [point.x / FT, -point.z / FT];
  }
  function surfaceAt(event, options) {
    const picked = view.pick(event.clientX, event.clientY, { ...options, water: true }); if (!picked) return null;
    const building = getPlan().buildings.find(b => b.id === (picked.building || picked.buildingId));
    let kind = picked.kind, id = picked.id || picked.pieceId;
    if (picked.part === 'water' && ['pool', 'spa'].includes(kind)) {
      const pool = getPlan().site?.pool;
      const piece = kind === 'pool' ? pool : pool?.features?.find(f => f.kind === 'spa' && f.id === id);
      return piece && { kind, piece, role: 'water', target: { [kind]: piece.id, part: 'water' }, label: `${piece.name || (kind === 'spa' ? 'Spa' : 'Pool')} water` };
    }
    const targetKind = kind === 'fixture' ? 'item' : kind;
    if (picked.part && ITEM_PARTS[targetKind === 'item' ? 'fixture' : targetKind]?.includes(picked.part)) {
      const pieces = kind === 'porch' ? [...allPorches(building || {}), ...(building?.porches_detail || [])]
        : kind === 'opening' ? building?.openings : kind === 'stair' ? building?.stairs : [...(building?.items || []), ...(building?.fixtures || [])];
      const piece = pieces?.find(p => p.id === id);
      if (piece) return { building, kind: targetKind, piece, role: picked.part, target: { [targetKind]: id, part: picked.part },
        level: piece.level, point: picked.point && local(building, new THREE.Vector3(...picked.point)).toArray(),
        label: `${piece.name || piece.kind || targetKind} ${picked.part.replaceAll('_', ' ')}` };
    }
    if (['opening', 'anchor', 'item', 'fixture', 'light'].includes(kind)) {
      const attached = ['openings', 'anchors', 'items', 'fixtures', 'lights'].flatMap(name => building?.[name] || []).find(p => p.id === id);
      const host = attached?.host;
      if (host?.wall || attached?.wall) { kind = 'wall'; id = host?.wall || attached.wall; }
      else if (host?.floor || host?.ceiling) { kind = 'room'; id = host.floor || host.ceiling; }
      else if (host?.roof) { kind = 'roof'; id = host.roof; }
    }
    const piece = building?.[kind === 'wall' ? 'walls' : kind === 'room' ? 'rooms' : 'unused']?.find(p => p.id === id)
      || (['roof', 'dormer'].includes(kind) && building?.roof?.sections.find(p => p.id === id || p.roof === id));
    // Dormer meshes are roof picks; their .roof names the parent, not the target.
    if (piece && building?.dormers?.some(d => d.id === piece.id)) kind = 'dormer';
    if (!piece || !['wall', 'room', 'roof', 'dormer'].includes(kind)) return null;
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
      surface = picked.part === 'ceiling' || direction.z > 0 ? 'ceiling' : 'floor'; role = surface === 'floor' ? 'floor' : piece.kind === 'porch' ? 'porch_ceiling' : 'ceiling';
      point = picked.part === 'ceiling' && picked.point ? local(building, new THREE.Vector3(...picked.point))
        : r.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), -elevation - (surface === 'ceiling' ? building.levels.find(l => l.id === piece.level).ceiling : (piece.floor_offset_ft || 0))), new THREE.Vector3());
    } else {
      point = picked.point && local(building, new THREE.Vector3(...picked.point));
      if(!point){const hit=raycaster.intersectObjects(view.scene.children,true).find(h=>h.object.userData.kind==='roof' && h.object.userData.buildingId===building.id);point=hit && local(building,hit.point);}
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
    return { building, kind: 'room', piece: room, point: point.toArray(), room, role: room.kind === 'porch' ? 'porch_ceiling' : 'ceiling', surface: 'ceiling', level: room.level };
  }
  function dismiss() { chooser?.remove(); chooser = null; }
  function choose(surface, material, event) {
    if (surface.target?.part) {
      if (!canEdit()) return;
      dismiss();
      op(surfaceOperation(surface, 'face', material)).then(() => {
        el('library-status').textContent = `Changed the ${surface.label || surface.role} material.`;
      }).catch(report);
      return;
    }
    dismiss(); chooser = document.createElement('div'); chooser.id = 'material-chooser'; chooser.setAttribute('role', 'group'); chooser.setAttribute('aria-label', 'Apply material');
    chooser.style.left = `${Math.max(96, Math.min(event.clientX, window.innerWidth - 240))}px`;
    chooser.style.top = `${Math.max(74, Math.min(event.clientY, window.innerHeight - 240))}px`;
    for (const [label, scope] of [...scopeChoices(surface), ['Cancel', null]]) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
      listen(button, 'click', () => {
        if (!scope) { dismiss(); return; }
        if (!canEdit()) return;
        try { const operation = surfaceOperation(surface, scope, material); dismiss(); op(operation).catch(report); } catch (error) { report(error); }
      }); chooser.append(button);
    }
    el('editor-scene').parentElement.append(chooser); chooser.querySelector('button').focus();
  }
  // Compatibility for old callers: browsing is never an assignment mode.
  async function pick(surface) {
    const line = surface?.building && materialLines(surface, getPlan(), kit).find(row =>
      JSON.stringify(row.target) === JSON.stringify(surface.target) ||
      (surface.target ? false : row.surface?.side === surface.side && row.surface?.surface === surface.surface));
    const ref = line?.current || describeMaterial(surface?.piece?.materials?.[surface.role]
      || surface?.building?.levels?.find(level => level.id === surface?.level)?.materials?.[surface?.role]
      || surface?.building?.materials?.[surface?.role] || getPlan().materials?.[surface?.role] || kit.materials?.[surface?.role], kit);
    await reveal('material', ref?.id);
  }
  function browse() {
    // Opening the dock and revealing a slot can request the same cold browse.
    // Share its completion so reveal always scrolls/flashes the final nodes.
    browsing ||= (async () => {
      let revision;
      do {
        revision = catalogRevision;
        await renderCatalog();
        if (revision !== catalogRevision) { catalog = null; loading = null; }
      } while (revision !== catalogRevision && !signal.aborted);
    })().finally(() => { browsing = null; });
    return browsing;
  }
  async function renderCatalog() {
    if (drag) { browsePending = true; return; }
    if (!catalog) {
      loading ||= readLibraryCatalog().catch(error => { loading = null; throw error; });
      catalog = await loading;
      const known = kit.manifest || (kit.manifest = window.twinManifest || {});
      for (const row of catalog.materials) {
        if (row.builtin || row.source === 'builtin' || !row.id.startsWith('material-')) continue;
        if (known[row.id]?.revision !== row.revision) {
          const entry = await request('materials/' + encodeURIComponent(row.id), 'GET', undefined, '');
          known[row.id] = { kind: 'material', household: true, revision: entry.revision, params: entry.params,
            maps: Object.fromEntries(Object.entries(entry.maps || {}).map(([slot, path]) => [slot, `materials/${entry.id}/${path}`])) };
        }
        if (known[row.id].maps.base_color) row.thumbnail_url = materialUrl(known[row.id].maps.base_color);
      }
    }
    if (signal.aborted) return;
    if (drag) { browsePending = true; return; }
    browsePending = false;
    thumbnails.current ||= createThumbnails(kit);
    const grid = el('library-entries'); grid.replaceChildren();
    importNodes.clear(); tiles.clear();
    if(tab==='items')for(const [tool,name,icon] of [['add-meter','Meter','gauge'],['add-electric-panel','Electric panel','utility-pole'],['add-charger','Charger','plug-zap'],['add-parking','Parking spot','car']]){
      const button=document.createElement('button');button.type='button';button.setAttribute('aria-label',name);button.append(svgIcon(icon),document.createTextNode(name));
      button.dataset.equipment=tool;
      button.addEventListener('click',()=>{if(canEdit()){if(!dock)host.hidden=true;el('rail-'+tool)?.click();}});grid.append(button);
    }
    const imports = tab === 'items' ? (catalog.imports || []).filter(e => !e.archived) : [];
    imports.forEach(rememberImport);
    if (el('library-import-limit')) el('library-import-limit').value = catalog.import_limit_mb || 50;
    const search = el('library-search')?.value?.toLowerCase() || '';
    for (const entry of [...catalog[tab], ...imports].filter(e => e.name.toLowerCase().includes(search))) {
      const material = tab === 'materials';
      const button = document.createElement('button'); button.type = 'button'; button.dataset[tab === 'materials' ? 'material' : 'item'] = entry.id;
      button.setAttribute('aria-label', entry.name); button.style.touchAction = 'none';
      const image = document.createElement('img'); image.alt = ''; image.draggable = false; image.width = 112; image.height = 96;
      const name = document.createElement('span'); name.textContent = entry.name; button.append(image, name);
      grid.append(button);
      tiles.set(entry.id, { button, entry, material });
      if (entry.thumbnail_url) image.src = entry.thumbnail_url;
      else if (entry.thumbnail) image.src = libUrl(entry.id, entry.thumbnail);
      else thumbnails.current.picture(entry, material).then(url => {
        if (!url || signal.aborted) return;
        image.src = url; entry.thumb = url;
        if (selection?.id === entry.id && [...(catalog?.materials || []), ...(catalog?.items || []), ...(catalog?.imports || [])].includes(entry))
          select(asset(entry, material));
      }).catch(report);
      if (entry.id.startsWith('import-')) {
        importNodes.set(entry.id, { nodes: [button], update(next) {
          // Handlers and an active drag keep this same entry object and node.
          Object.assign(entry, next); name.textContent = entry.name; button.setAttribute('aria-label', entry.name);
          if (entry.thumbnail) image.src = libUrl(entry.id, entry.thumbnail);
        } });
      }
      listen(button, 'pointerdown', event => {
        if (event.button !== 0 || !canEdit()) return;
        suppressClick = false;
        onInteract?.(); dismiss(); event.preventDefault(); button.focus(); button.setPointerCapture(event.pointerId);
        drag = { entry, material: tab === 'materials', x: event.clientX, y: event.clientY, pointer: event.pointerId };
      });
      if (rowMenu) listen(button, 'contextmenu', event => {
        event.preventDefault(); rowMenu.open(event, { actions: assetActions(entry, tab === 'materials') });
      });
      listen(button, 'click', event => {
        if (suppressClick && event.detail) { suppressClick = false; return; }
        const next = asset(entry, tab === 'materials');
        select(selection?.id === next.id && selection.kind === next.kind ? null : next);
      });
    }
    if (tab === 'items') {
      const hidden = [];
      for (const kind of ['planting', 'furniture']) for (const [index, piece] of (getPlan().site?.[kind] || []).entries())
        if (!objectShown(piece, true)) hidden.push({ piece, id: piece.id || `${kind}:${index}` });
      for (const building of getPlan().buildings) for (const piece of [...(building.items || []), ...(building.anchors || []).filter(a => !a.device)])
        if (!objectShown(piece, true)) hidden.push({ piece, id: piece.id, building: building.id });
      for (const row of hidden) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = `Select hidden: ${row.piece.name || row.id}`;
        listen(button, 'click', () => tools.select({ pieceId: row.id, buildingId: row.building })); grid.append(button);
        if (rowMenu) listen(button, 'contextmenu', event => { event.preventDefault(); rowMenu.open(event, { actions: [button] }); });
      }
    }
    syncSelection();
    host.querySelectorAll('[data-library-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.libraryTab === tab)));
    el('library-status').textContent = hint;
  }
  async function changedImport(entry, { added = false, removed = false } = {}) {
    if (signal.aborted) return;
    if (catalog) {
      const entries = catalog.imports ||= [], index = entries.findIndex(e => e.id === entry.id);
      if (removed) { if (index !== -1) entries.splice(index, 1); }
      else { if (index === -1) entries.push(entry); else entries[index] = entry; }
    }
    const row = importNodes.get(entry.id);
    if (removed) {
      if (drag) browsePending = true;
      else { row?.nodes.forEach(node => node.remove()); importNodes.delete(entry.id); tiles.delete(entry.id); }
    } else row?.update(entry);
    syncSelection();
    if (added) { tab = 'items'; host.hidden = false; dock?.show('library'); el('rail-library').setAttribute('aria-pressed', 'true'); }
    if (added && !row) await browse();
  }
  const importsQueue = mountImports({ canvas, kit, canEdit, signal, changed: changedImport });
  const invalidateCatalog = () => {
    catalogRevision++; catalog = null; loading = null;
    if (selection || (dock ? dock.current() === 'library' : !host.hidden)) browse().catch(report);
  };
  listen(window, 'focus', invalidateCatalog);
  listen(document, 'chf-materials-changed', invalidateCatalog);
  if (dock) {
    host.hidden = false;
    const off = dock.onShow(tab => {
      if (tab === 'library') browse().catch(error => { el('library-status').textContent = 'Could not load the library. Open it again to retry.'; report(error); });
    });
    signal.addEventListener('abort', off, { once: true });
  }
  if (new URLSearchParams(location.search).get('library') === '1') {
    tab = 'items'; host.hidden = false; el('rail-library').setAttribute('aria-pressed', 'true');
    dock?.show('library');
    browse().catch(report);
  }
  if (el('library-search')) listen(el('library-search'), 'input', () => browse().catch(report));
  listen(el('rail-library'), 'click', () => {
    if (dock) { dock.show('library'); host.scrollIntoView({ block: 'nearest' }); return; }
    host.hidden = !host.hidden; el('rail-library').setAttribute('aria-pressed', String(!host.hidden));
    if (!host.hidden) browse().catch(error => { el('library-status').textContent = 'Could not load the library. Open it again to retry.'; report(error); });
  });
  for (const button of host.querySelectorAll('[data-library-tab]')) listen(button, 'click', () => {
    tab = button.dataset.libraryTab; browse().catch(report);
  });
  listen(document, 'pointermove', event => {
    if (!drag || drag.pointer !== event.pointerId || Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 3) return;
    updateDragRow(event, asset(drag.entry, drag.material));
  });
  listen(document, 'pointerup', event => {
    if (!drag || drag.pointer !== event.pointerId) return;
    const moved = drag; drag = null;
    suppressClick = Math.hypot(event.clientX - moved.x, event.clientY - moved.y) >= 3;
    try {
      if (!canEdit() || Math.hypot(event.clientX - moved.x, event.clientY - moved.y) < 3) return;
      const row = updateDragRow(event, asset(moved.entry, moved.material));
      if (row) { sendSlotDrag(row, 'drop', asset(moved.entry, moved.material)); return; }
      if (!canvas.contains(document.elementFromPoint(event.clientX, event.clientY))) return;
      const surface = surfaceAt(event);
      if (moved.material) { if (surface) choose(surface, moved.entry, event); return; }
      const at = ground(event); if (!surface && (!at || !contains(getPlan().site?.lot || [], at))) return;
      try { op(itemOperation(surface, moved.entry, at)).catch(report); } catch (error) { report(error); }
    } finally { sendSlotDrag(dragRow, 'leave', asset(moved.entry, moved.material)); dragRow = null; if (browsePending) browse().catch(report); }
  }, { capture: true });
  listen(document, 'pointercancel', event => {
    if (!drag || drag.pointer !== event.pointerId) return;
    sendSlotDrag(dragRow, 'leave', asset(drag.entry, drag.material)); dragRow = null;
    drag = null; suppressClick = false; if (browsePending) browse().catch(report);
  });
  listen(document, 'keydown', event => {
    if (event.key !== 'Escape') return;
    if (chooser) dismiss();
    else if (selection && host.contains(document.activeElement) && (!dock || dock.current() === 'library')) select(null);
    else return;
    event.stopImmediatePropagation();
  }, { capture: true });

  function siteBox(piece, kind) {
    if (siteShapeKinds.includes(kind)) {
      const ps = sitePoints(piece), box = new THREE.Box3();
      for (const [x, y] of ps) {
        const z = groundAt(getPlan(), x, y) + (piece.elevation || 0), radius = piece.at ? (piece.radius || 2) : .3;
        box.expandByPoint(new THREE.Vector3((x - radius) * FT, z * FT, -(y + radius) * FT));
        box.expandByPoint(new THREE.Vector3((x + radius) * FT, (z + (piece.height || 1)) * FT, -(y - radius) * FT));
      }
      return box;
    }
    const height = (kind === 'planting' ? piece.height || 4 : 3) * (piece.scale ?? 1), radius = (kind === 'planting' ? Math.max(1, height * .18) : 2 * (piece.scale ?? 1));
    const y = groundAt(getPlan(), ...piece.at) + (piece.elevation || 0), [x, z] = piece.at;
    return new THREE.Box3(new THREE.Vector3((x - radius) * FT, y * FT, -(z + radius) * FT),
      new THREE.Vector3((x + radius) * FT, (y + height) * FT, -(z - radius) * FT));
  }
  function siteHits(x, y) {
    const r = ray({ clientX: x, clientY: y }), hits = [];
    for (const kind of ['planting', 'furniture']) for (const [index, piece] of (getPlan()?.site?.[kind] || []).entries()) {
      if (!piece.at || !objectShown(piece, true)) continue;
      const point = r.intersectBox(siteBox(piece, kind), new THREE.Vector3());
      if (!point) continue;
      const distance = point.distanceTo(r.origin);
      hits.push({ kind, id: piece.id || `${kind}:${index}`, building: null, distance, point: point.toArray() });
    }
    // Keep every footprint under the ray so repeated clicks can reach a bed
    // beneath a tree. The shared picker compares all sources by ray distance.
    const p = ground({ clientX: x, clientY: y });
    if (p) {
      const point = new THREE.Vector3(p[0] * FT, groundAt(getPlan(), ...p) * FT, -p[1] * FT);
      const distance = point.distanceTo(r.origin);
      for (const { kind, piece } of siteRecords(getPlan()).filter(r => siteShapeKinds.includes(r.kind)).reverse()) {
        if (!objectShown(piece, true)) continue;
        const ps = sitePoints(piece);
        const hit = kind === 'yard_rooms' ? ps.some((a, i) => edgeDistance(p, a, ps[(i + 1) % ps.length]) < .6)
          : piece.kind === 'path' ? pathSurfacePolygons(piece).some(poly => inPolygon(poly, ...p)) : piece.polygon ? inPolygon(ps, ...p) : piece.at ? Math.hypot(p[0] - piece.at[0], p[1] - piece.at[1]) < (piece.radius || 2)
          : ps.some((a, i) => i + 1 < ps.length && edgeDistance(p, a, ps[i + 1]) < .6);
        if (hit) hits.push({ kind, id: piece.id, building: null, distance, point: point.toArray() });
      }
    }
    return hits.sort((a, b) => a.distance - b.distance);
  }
  function pickSite(x, y) {
    const hit = siteHits(x, y)[0];
    // Legacy placement/Move callers still respect a nearer house surface;
    // the shared selection picker consumes the complete source instead.
    return hit && !(view.pickAll(x, y)[0]?.distance < hit.distance) ? hit : null;
  }
  function refresh() {
    const selected = tools.selection(), kind = selected.kind;
    const piece = !selected.building && siteRecord(getPlan(), selected.id)?.piece;
    Object.assign(outline.userData, {pieceId:selected.id,kind});
    outline.visible = !!piece && kind !== 'yard_rooms' && !view.isPieceHidden?.({id:selected.id,kind});
    if (piece) outline.box.copy(siteBox(piece, kind));
  }
  const typed = createTypedValue(canvas.parentElement);
  function pointerDown(event) {
    if (!canEdit() || event.button !== 0 || tools.handleAt?.(event)) return false;
    // Only Move can drag the already selected yard body. Other presses stay
    // with the scene arbiter so a click selects and a drag navigates.
    if (el('rail-move').getAttribute('aria-pressed') !== 'true') return false;
    const picked = pickSite(event.clientX, event.clientY); if (!picked) return false;
    if (view.isPiecePickable?.(picked) === false) return false;
    const selected = tools.selection();
    if (selected.building || selected.kind !== picked.kind || selected.id !== picked.id) return false;
    onInteract?.();
    const { index, piece } = siteRecord(getPlan(), picked.id);
    const start = ground(event); if (!start) return false;
    siteDrag = { ...picked, index, start, piece, pointerId: event.pointerId, event, x: event.clientX, y: event.clientY, enabled: view.controls.enabled };
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); return true;
  }
  function finishBody(cancel = false, exact) {
    const g = siteDrag; if (!g) return false;
    if (!cancel && Number.isFinite(exact)) pointerMove(g.event, exact);
    siteDrag = null; typed.hide(); view.controls.enabled = g.enabled;
    if (canvas.hasPointerCapture(g.pointerId)) canvas.releasePointerCapture(g.pointerId);
    refresh();
    if (!cancel && canEdit() && g.operation && g.by.some(v => Math.abs(v) > 1e-8))
      return Promise.resolve(op(g.operation, { drag: true, local: applyLocal(getPlan(), g.operation)?.plan, selection: { kind: g.kind, id: g.id },
        label: g.kind === 'planting' ? 'Moving the plant' : 'Moving the item' }));
    return true;
  }
  function pointerUp(event, cancel) {
    if (!siteDrag) return false;
    if (!cancel) pointerMove(event);
    Promise.resolve(finishBody(cancel)).catch(report); return true;
  }
  function pointerMove(event, exact) {
    if (!siteDrag) return false;
    siteDrag.event = event;
    if (!Number.isFinite(exact) && !siteDrag.operation && Math.hypot(event.clientX - siteDrag.x, event.clientY - siteDrag.y) < DRAG_THRESHOLD_PX) return true;
    const at = ground(event);
    if (at) {
      const g = siteDrag, piece = structuredClone(g.piece);
      let by = at.map((v, i) => v - g.start[i]);
      if (Number.isFinite(exact)) { const length = Math.hypot(...by); by = by.map((v, i) => exact * (length ? v / length : i === 0 ? 1 : 0)); }
      else by = by.map(v => snapValue('move', v, !!event.shiftKey));
      g.by = by; g.operation = { op: 'move_site_item', list: g.kind, index: g.index,
        ...(piece.at ? { at: piece.at.map((v, i) => v + by[i]) } : { by }) };
      typed.show('length', Math.hypot(...by), [event.clientX, event.clientY]);
      for (const key of ['at', 'polygon', 'points', 'polyline']) if (piece[key])
        piece[key] = key === 'at' ? piece[key].map((v, i) => v + by[i]) : piece[key].map(p => p.map((v, i) => v + by[i]));
      outline.box.copy(siteBox(piece, g.kind));
    }
    return true;
  }
  view.controls.addEventListener('change', refresh);
  listen(canvas.parentElement, 'twinrebuilt', refresh);
  signal.addEventListener('abort', () => {
    typed.hide(); dismiss(); sendSlotDrag(dragRow, 'leave', null); dragRow = null; selectionListeners.clear(); thumbnails.current?.dispose(); if (siteDrag) view.controls.enabled = siteDrag.enabled;
    view.controls.removeEventListener('change', refresh); outline.removeFromParent(); outline.geometry.dispose(); outline.material.dispose();
  }, { once: true });
  return { key: typed.key, typedValue: typed.value, commit: exact => finishBody(false, exact),
    preview(plan) { const selected = tools.selection(), record = !selected.building && siteRecord(plan, selected.id); if (record) outline.box.copy(siteBox(record.piece, record.kind)); },
    siteHits, pickSite, surfaceAt, ceilingAt, ground, pointerDown, pointerMove, pointerUp, refresh, pick,
    selected: () => selection, select, reveal,
    onSelect(fn) { selectionListeners.add(fn); return () => selectionListeners.delete(fn); } };
}
