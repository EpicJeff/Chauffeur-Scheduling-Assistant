import * as THREE from 'three';
import { hostPoint } from '../twin_hosts.js';
import { groundAt, buildingGround, edgeDistance } from '../twin_ground.js';
import { contains } from '../twin_generator.js';
import { objectOperation, siteRecord, siteShapeKinds, sitePoints, sitePieces } from '../objects.js';
import { fixtureReference } from '../live/emitters.js';
import { shapeCentre, transformShape, shapeOperation } from './site_shapes.js';
import { HANDLE_HIT_PX, DRAG_THRESHOLD_PX } from './picking.js';
import { snapValue } from './snap.js';
import { createTypedValue } from './typed_value.js';
import { applyLocal } from './local_ops.js';
import { groupTransform, transformOperations, previewTransforms } from './group_transform.js';
import { isSupported, roofPoint, supportPoints } from '../roof_supports.js';

const FT = .3048, clamp = v => Math.max(.05, Math.min(20, v));
const wrap = v => (v % 360 + 360) % 360;
const same = (a, b) => typeof a === 'number' && typeof b === 'number' ? Math.abs(a - b) < 1e-8
  : a && b && typeof a === 'object' && typeof b === 'object' ? Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => same(a[k], b[k])) : a === b;
// One handle source for placed things. Structural controls stay in handles.js.
export function createGizmo({ getPlan, getSelection, getMembers = () => [], isPickable = () => true, getStructuralHandles = () => [], getTool, view, layer, op, applyBatch = (ops, options) => op({ op: 'batch', ops }, options), typed = createTypedValue(layer), canEdit = () => true, onPreview }) {
  const canvas = view.renderer3.domElement, raycaster = new THREE.Raycaster();
  const root = document.createElement('div'); root.className = 'editor-handles'; layer.append(root);
  let rows = [], lines = [], gesture = null, preview = null, ring = [], lastFrameMs = null, groupCache = null;
  function record(tool = getTool()) {
    if (!canEdit()) return null;
    const plan = getPlan(), members = getMembers();
    if (members.length > 1) {
      const keys = JSON.stringify(members.map(r => [r.kind, r.buildingId ?? r.building ?? null, r.pieceId ?? r.id, r.entity_id ?? null, !!isPickable(r)]));
      const boundsRevision = view.selectionBoundsRevision;
      if (!groupCache || groupCache.plan !== plan || groupCache.keys !== keys || groupCache.tool !== tool || groupCache.boundsRevision !== boundsRevision) {
        const group = groupTransform(plan, members, tool, { boxes: view.selectionWorldBounds?.() || [], isPickable });
        groupCache = { plan, keys, tool, boundsRevision, record: group && { group, piece: { id: '__selection__' } } };
      }
      return groupCache.record;
    }
    groupCache = null;
    const selected = getSelection(); if (!selected?.id || !plan) return null;
    if (selected.kind === 'roof' && tool === 'move' && isPickable(selected)) {
      const building = plan.buildings.find(b => b.id === selected.building);
      const piece = building?.roofs?.find(r => r.id === selected.id);
      return piece && isSupported(piece) && piece.state !== 'ghost' ? { piece, building, list: 'roofs', level: piece.level, roof: true } : null;
    }
    if (selected.kind === 'light_fixture') {
      const entity_id = selected.entity_id || Object.keys(plan.light_fixtures || {}).find(id => plan.light_fixtures[id].some(f => f.id === selected.id));
      const piece = plan.light_fixtures?.[entity_id]?.find(f => f.id === selected.id);
      return piece && ['point', 'spot'].includes(piece.shape) ? { piece, entity_id, fixture: true, level: piece.level } : null;
    }
    if (['item', 'anchor'].includes(selected.kind)) {
      const building = plan.buildings.find(b => b.id === selected.building), list = selected.kind === 'item' ? 'items' : 'anchors';
      const piece = building?.[list]?.find(p => p.id === selected.id);
      if (!piece || piece.device || piece.state === 'ghost') return null;
      const level = building.walls.find(w => w.id === piece.host?.wall)?.level
        || building.rooms.find(r => r.id === (piece.host?.floor || piece.host?.ceiling))?.level
        || selected.level || building.levels[0]?.id;
      return { piece, building, list, level };
    }
    const site = siteRecord(plan, selected.id);
    return site && (['planting', 'furniture'].includes(site.kind) || siteShapeKinds.includes(site.kind)) ? { ...site, shape: siteShapeKinds.includes(site.kind) } : null;
  }
  function world(building, point) {
    const a = (building?.rotation || 0) * Math.PI / 180, p = building?.position || [0, 0], [x, y, z] = point;
    return new THREE.Vector3((x * Math.cos(a) - y * Math.sin(a) + p[0]) * FT,
      (z + (building?.base || 0) + (building ? buildingGround(getPlan(), building) : 0)) * FT,
      -(x * Math.sin(a) + y * Math.cos(a) + p[1]) * FT);
  }
  function local(building, point) {
    const a = -(building?.rotation || 0) * Math.PI / 180, p = building?.position || [0, 0];
    const x = point.x / FT - p[0], y = -point.z / FT - p[1];
    return new THREE.Vector3(x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a),
      point.y / FT - (building?.base || 0) - (building ? buildingGround(getPlan(), building) : 0));
  }
  function project(building, at) {
    view.camera.updateMatrixWorld(true);
    const p = world(building, at).project(view.camera), rect = canvas.getBoundingClientRect();
    return p.z < -1 || p.z > 1 ? null : [rect.left + (p.x + 1) * rect.width / 2, rect.top + (1 - p.y) * rect.height / 2];
  }
  function point(event, g) {
    const rect = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2), view.camera);
    const origin = local(g.record.building, raycaster.ray.origin);
    const ray = new THREE.Ray(origin, local(g.record.building, raycaster.ray.origin.clone().add(raycaster.ray.direction)).sub(origin).normalize());
    return ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), -g.centre[2]), new THREE.Vector3())?.toArray();
  }
  function centre(r, plan = getPlan()) {
    if (r.group) return gesture?.previewCentre || r.group.centre;
    const p = r.piece;
    if (r.roof) return [...roofPoint(p, [0, 1].map(i => p.area.reduce((n, q) => n+q[i], 0)/p.area.length)), p.plate];
    if (r.fixture) return [p.at[0], p.at[1], p.at[2] + fixtureReference(plan, p, p.at) + (p.offset_ft || 0)];
    if (r.building) { const at = hostPoint(r.building, p.host, p.offset || 0); at[2] += p.elevation || 0; return at; }
    const at = r.shape ? shapeCentre(p) : p.at;
    return [...at, groundAt(plan, ...at) + (p.elevation || 0)];
  }
  const pieceIn = (plan, r) => r.building ? plan.buildings.find(b => b.id === r.building.id)[r.list].find(p => p.id === r.piece.id)
    : r.fixture ? plan.light_fixtures[r.entity_id].find(f => f.id === r.piece.id) : sitePieces(plan.site[r.kind])[r.index];
  function clear() { root.replaceChildren(); rows = []; lines = []; ring = []; }
  function draw() {
    const tool = gesture?.tool || getTool();
    if (!['move', 'rotate', 'scale'].includes(tool)) { clear(); return; }
    const r = gesture?.record || record(tool);
    if (!r || r.fixture && tool === 'scale'
      || view.groups?.levels?.[`${r.building?.id || r.piece.building}:${r.level}`]?.visible === false) { clear(); return; }
    let c; try { c = r.group ? centre(r) : preview ? centre({ ...r, piece: pieceIn(preview, r) }, preview) : centre(r); } catch { clear(); return; }
    if (r.roof) {
      // Dock outside all structural controls in screen space. The 100 px
      // clearance includes the 52 px arrows and their hit radius at any zoom.
      const structural = getStructuralHandles();
      const points = structural.length ? structural : [
        ...r.piece.area.map(p => ({ at: [...roofPoint(r.piece, p), c[2]] })),
        ...supportPoints(r.piece).map(p => ({ at: [...p.at, c[2]] }))];
      const pixels = points.map(h => { const p = project(r.building, h.at); return p && p.map((v,i) => v+(h.offset?.[i] || 0)); }).filter(Boolean);
      if (pixels.length) {
        const dock = point({ clientX: Math.max(...pixels.map(p => p[0]))+100, clientY: Math.max(...pixels.map(p => p[1]))+100 }, { record: r, centre: c });
        if (dock) c = dock;
      }
    }
    const middle = project(r.building, c); if (!middle) { clear(); return; }
    const radius = [0, 1].map(i => {
      const p = project(r.building, c.map((v, k) => v + (i === k ? 1 : 0)));
      return 52 / Math.max(.1, p ? Math.hypot(p[0] - middle[0], p[1] - middle[1]) : 1);
    });
    const specs = tool === 'move' ? [['gizmo_move_x', radius[0], 0], ['gizmo_move_y', 0, radius[1]], ['gizmo_move_free', 0, 0]]
      : tool === 'rotate' ? [['gizmo_turn', radius[0], 0]]
      : r.group ? [['gizmo_scale', radius[0], radius[1]]] : [['gizmo_scale', radius[0], radius[1]], ['gizmo_scale_x', radius[0], 0], ['gizmo_scale_y', 0, radius[1]]];
    let count = 0;
    for (const [kind, x, y] of specs) {
      const at = [c[0] + x, c[1] + y, c[2]], pixel = project(r.building, at); if (!pixel) continue;
      let row = rows[count++];
      if (!row) { const node = document.createElement('span'); root.append(node); rows.push(row = { node }); }
      row.handle = { kind, id: r.piece.id, building: r.building?.id || null, level: r.level, at, centre: c };
      row.pixel = pixel; row.node.dataset.gizmo = kind;
      row.node.className = `editor-handle editor-gizmo editor-${kind}`;
      row.node.style.left = `${pixel[0]}px`; row.node.style.top = `${pixel[1]}px`;
      row.node.setAttribute('aria-hidden', 'true');
      const arrow = ['gizmo_move_x', 'gizmo_move_y'].includes(kind);
      row.node.textContent = arrow ? '\u2194' : '';
      row.node.style.transform = `translate(-50%, -50%)${arrow ? ` rotate(${Math.atan2(pixel[1] - middle[1], pixel[0] - middle[0])}rad)` : ''}`;
    }
    while (rows.length > count) rows.pop().node.remove();
    ring = tool === 'rotate' ? Array.from({ length: 49 }, (_, i) => project(r.building,
      [c[0] + radius[0] * Math.cos(i * Math.PI / 24), c[1] + radius[1] * Math.sin(i * Math.PI / 24), c[2]])) : [];
    const segments = tool === 'rotate' ? ring.slice(1).map((p, i) => [ring[i], p])
      : rows.filter(row => row.handle.kind !== 'gizmo_move_free').map(row => [middle, row.pixel]);
    count = 0;
    for (const [a, b] of segments) {
      if (!a || !b) continue;
      let line = lines[count++]; if (!line) { line = document.createElement('span'); root.append(line); lines.push(line); }
      line.className = 'editor-gizmo-line'; line.style.left = `${a[0]}px`; line.style.top = `${a[1]}px`;
      line.style.width = `${Math.hypot(b[0] - a[0], b[1] - a[1])}px`;
      line.style.transform = `rotate(${Math.atan2(b[1] - a[1], b[0] - a[0])}rad)`;
    }
    while (lines.length > count) lines.pop().remove();
  }
  function hit(event) {
    draw();
    const close = rows.slice().sort((a, b) => Math.hypot(a.pixel[0] - event.clientX, a.pixel[1] - event.clientY) - Math.hypot(b.pixel[0] - event.clientX, b.pixel[1] - event.clientY));
    if (close[0] && Math.hypot(close[0].pixel[0] - event.clientX, close[0].pixel[1] - event.clientY) <= HANDLE_HIT_PX) return close[0].handle;
    if (ring.some((p, i) => i && p && ring[i - 1] && edgeDistance([event.clientX, event.clientY], ring[i - 1], p) <= HANDLE_HIT_PX)) return rows[0]?.handle || null;
    return null;
  }
  function begin(event, handle = hit(event)) {
    if (gesture || !handle || !canEdit()) return false;
    const r = record(); if (!r) return false;
    const g = { record: r, handle, centre: centre(r), source: getPlan(), tool: getTool(), operation: null, event, press: event, moved: false };
    g.start = point(event, g); if (!g.start) return false;
    gesture = g; lastFrameMs = null;
    typed.show(g.tool === 'rotate' ? 'angle' : g.tool === 'scale' ? 'factor' : 'length', g.tool === 'scale' ? 1 : 0, [event.clientX, event.clientY]);
    return true;
  }
  function moveHost(g, by) {
    const { piece, building } = g.record, host = piece.host;
    if (host.ground) return { ...host, at: host.at.map((v, i) => v + (by[i] || 0)) };
    if (host.wall || host.roof) {
      const wall = building.walls.find(w => w.id === host.wall), roof = building.roofs?.find(r => r.id === host.roof);
      const a = wall?.from || roof?.area[host.edge], b = wall?.to || roof?.area[(host.edge + 1) % roof.area.length];
      if (!a || !b) return null;
      const d = b.map((v, i) => v - a[i]), length = Math.hypot(...d);
      return { ...host, at: host.at + by.reduce((n, v, i) => n + v * d[i] / length, 0) };
    }
    const at = g.centre.map((v, i) => v + (by[i] || 0));
    const room = building.rooms.find(r => r.state !== 'ghost' && r.level === g.record.level && contains(r.polygon, at));
    if (!room) return null;
    const bounds = [0, 1].map(i => room.polygon.map(p => p[i]));
    return { [host.ceiling ? 'ceiling' : 'floor']: room.id,
      u: (at[0] - Math.min(...bounds[0])) / (Math.max(...bounds[0]) - Math.min(...bounds[0])),
      v: (at[1] - Math.min(...bounds[1])) / (Math.max(...bounds[1]) - Math.min(...bounds[1])) };
  }
  function update(event, { free = !!event.shiftKey, typed: exact } = {}) {
    const g = gesture; if (!g) return;
    if (!Number.isFinite(exact) && !g.moved && Math.hypot(event.clientX - g.press.clientX, event.clientY - g.press.clientY) < DRAG_THRESHOLD_PX) return;
    g.moved = true;
    const started = performance.now(), p = point(event, g); if (!p) return;
    g.event = event;
    const r = g.record, piece = r.piece, kind = g.handle.kind, c = g.centre;
    const axis = kind.endsWith('_x') ? 0 : kind.endsWith('_y') ? 1 : null;
    const a = g.start.slice(0, 2).map((v, i) => v - c[i]), b = p.slice(0, 2).map((v, i) => v - c[i]);
    if (r.group) {
      let value, transform;
      if (g.tool === 'move') {
        let by = p.slice(0, 2).map((v, i) => axis !== null && axis !== i ? 0 : v - g.start[i]);
        if (Number.isFinite(exact)) {
          const length = Math.hypot(...by);
          by = by.map((v, i) => axis !== null ? (axis === i ? exact : 0) : exact * (length ? v / length : i === 0 ? 1 : 0));
        } else by = by.map(v => snapValue('move', v, free));
        transform = { by }; value = axis === null ? Math.hypot(...by) : by[axis];
      } else if (g.tool === 'rotate') {
        const angle = (Math.atan2(b[1], b[0]) - Math.atan2(a[1], a[0])) * 180 / Math.PI;
        value = Number.isFinite(exact) ? exact : snapValue('angle', (angle + 540) % 360 - 180, free);
        transform = { angle: value };
      } else {
        value = clamp(Number.isFinite(exact) ? exact : snapValue('scale', Math.hypot(...b) / Math.max(.01, Math.hypot(...a)), free));
        transform = { factor: value };
      }
      try {
        g.operation = { op: 'batch', ops: transformOperations(r.group, transform) };
        preview = applyLocal(g.source, g.operation)?.plan;
      } catch (error) {
        g.changed = false; g.operation = null;
        document.getElementById('editor-status').textContent = error.message;
        lastFrameMs = Math.max(.001, performance.now() - started); return;
      }
      g.changed = Math.abs(value - (g.tool === 'scale' ? 1 : 0)) > 1e-8;
      g.previewCentre = g.tool === 'move' ? c.map((v, i) => v + (transform.by[i] || 0)) : c;
      typed.show(g.tool === 'move' ? 'length' : g.tool === 'rotate' ? 'angle' : 'factor', value, [event.clientX, event.clientY]);
      // Reuse selected rendered outlines; no geometry rebuild or network work
      // occurs in a frame. Cached records/bounds keep cost linear in the set.
      if (preview) view.previewSelectionGroup?.(previewTransforms(r.group, transform, preview));
      draw(); lastFrameMs = Math.max(.001, performance.now() - started); return;
    }
    let change, live, valueKind;
    if (g.tool === 'move') {
      let by = p.slice(0, 2).map((v, i) => axis !== null && axis !== i ? 0 : v - g.start[i]);
      if (Number.isFinite(exact)) {
        const length = Math.hypot(...by);
        by = by.map((v, i) => axis !== null ? (axis === i ? exact : 0) : exact * (length ? v / length : i === 0 ? 1 : 0));
      } else by = by.map(v => snapValue('move', v, free));
      live = axis === null ? Math.hypot(...by) : by[axis]; valueKind = 'length';
      if (r.roof) {
        change = { area: piece.area.map(p => p.map((v, i) => v+by[i])),
          ...(piece.roof_frame ? { roof_frame: { ...piece.roof_frame, origin: piece.roof_frame.origin.map((v, i) => v+by[i]) } } : {}) };
        g.operation = { op: 'move_roof', building: r.building.id, id: piece.id, by };
      }
      else if (r.building) { const host = moveHost(g, by); if (!host) return; change = { host }; g.operation = { op: 'move_hosted', building: r.building.id, id: piece.id, host }; }
      else if (r.fixture) {
        change = { at: piece.at.map((v, i) => v + (by[i] || 0)), ...(piece.aim ? { aim: piece.aim.map((v, i) => v + (by[i] || 0)) } : {}) };
        g.operation = { op: 'update_light_fixture', entity_id: r.entity_id, id: piece.id, change };
      } else {
        change = r.shape ? transformShape(piece, { centre: c.slice(0, 2).map((v, i) => v + by[i]) }) : { at: piece.at.map((v, i) => v + by[i]) };
        g.operation = { op: 'move_site_item', list: r.kind, index: r.index, ...(r.shape ? { by } : change) };
      }
    } else if (g.tool === 'rotate') {
      const angle = (Math.atan2(b[1], b[0]) - Math.atan2(a[1], a[0])) * 180 / Math.PI;
      const delta = Number.isFinite(exact) ? exact : snapValue('angle', (angle + 540) % 360 - 180, free);
      live = delta; valueKind = 'angle';
      const rotation = wrap((r.fixture ? piece.rotation_deg || 0 : piece.rotation || 0) + delta);
      change = r.shape ? transformShape(piece, { rotation }) : r.fixture ? { rotation_deg: rotation } : { rotation };
      if (r.fixture && piece.aim) {
        const a = delta * Math.PI / 180, x = piece.aim[0] - piece.at[0], y = piece.aim[1] - piece.at[1];
        const aim = [piece.at[0] + x * Math.cos(a) - y * Math.sin(a), piece.at[1] + x * Math.sin(a) + y * Math.cos(a), piece.aim[2]];
        aim[2] += fixtureReference(g.source, piece, piece.aim) - fixtureReference(g.source, piece, aim);
        change.aim = aim;
      }
      g.operation = r.shape ? shapeOperation(r, change) : r.fixture
        ? { op: 'update_light_fixture', entity_id: r.entity_id, id: piece.id, change } : objectOperation(r, change);
    } else {
      const raw = Number.isFinite(exact) ? exact : snapValue('scale', axis === null ? Math.hypot(...b) / Math.max(.01, Math.hypot(...a)) : b[axis] / (a[axis] || .01), free);
      live = clamp(raw); valueKind = 'factor';
      if (r.shape) {
        const scale = [axis === 1 ? 1 : live, axis === 0 ? 1 : live];
        change = transformShape(piece, { scale });
        if (!piece.polygon && !piece.points && !piece.polyline && piece.radius) change.radius = piece.radius * live;
        g.operation = shapeOperation(r, change);
      } else {
        if (axis === null) { change = { scale: clamp((piece.scale ?? 1) * raw) }; live = change.scale / (piece.scale ?? 1); }
        else { const axes = [...(piece.scale_axes || [1, 1, 1])], index = axis === 0 ? 0 : 2; axes[index] = clamp(axes[index] * raw); change = { scale_axes: axes }; live = axes[index] / (piece.scale_axes?.[index] ?? 1); }
        g.operation = objectOperation(r, change);
      }
    }
    typed.show(valueKind, live, [event.clientX, event.clientY]);
    preview = structuredClone(g.source);
    const next = pieceIn(preview, r);
    Object.assign(next, change);
    g.changed = Object.entries(change).some(([k, v]) => !same(v, piece[k] ?? (k === 'rotation' || k === 'rotation_deg' ? 0 : k === 'scale' ? 1 : k === 'scale_axes' ? [1, 1, 1] : undefined)));
    if (r.roof) {
      const outline = next.area.map(p => project(r.building, [...roofPoint(next, p), c[2]])).filter(Boolean);
      if (outline.length) outline.push(outline[0]);
      document.getElementById('editor-drag-outline')?.setAttribute('points', outline.map(p => p.join(',')).join(' '));
    }
    else if (r.building) view.rebuildLevel(r.building.id, r.level, preview, { [r.list]: [piece.id] });
    else {
      const points = r.shape ? sitePoints(next) : [g.centre, centre({ ...r, piece: next }, preview)];
      const outline = points.map(p => project(null, p.length === 3 ? p : [...p, c[2]])).filter(Boolean);
      document.getElementById('editor-drag-outline')?.setAttribute('points', outline.map(p => p.join(',')).join(' '));
    }
    onPreview?.(preview); draw(); lastFrameMs = Math.max(.001, performance.now() - started);
  }
  async function finish(cancel = false, exact) {
    const g = gesture; if (!g) return;
    if (!cancel && Number.isFinite(exact)) update(g.event, { free: true, typed: exact });
    gesture = null; preview = null; typed.hide();
    view.previewSelectionBox?.(null);
    document.getElementById('editor-drag-outline')?.setAttribute('points', '');
    try { if (!cancel && canEdit() && g.changed && g.operation?.op === 'batch') await applyBatch(g.operation.ops, { drag: true, local: applyLocal(getPlan(), g.operation)?.plan });
      else if (!cancel && canEdit() && g.changed) await op(g.operation, { drag: true,
      ...(g.operation.op === 'move_site_item' ? { local: applyLocal(getPlan(), g.operation)?.plan } : {}) }); }
    finally {
      if (g.record.building && !g.record.roof) view.rebuildLevel(g.record.building.id, g.record.level, getPlan(), { [g.record.list]: [g.record.piece.id] });
      onPreview?.(getPlan()); draw();
    }
  }
  return { hit, begin, update, finish, draw, clear, key: typed.key, typedValue: typed.value,
    commit: exact => finish(false, exact), pointerMove: update, pointerUp: (event, cancel) => finish(cancel),
    handles: () => { draw(); return rows.map(row => row.handle); }, active: () => !!gesture,
    clearDragFrame: () => { lastFrameMs = null; }, get lastDragFrameMs() { return lastFrameMs; } };
}
