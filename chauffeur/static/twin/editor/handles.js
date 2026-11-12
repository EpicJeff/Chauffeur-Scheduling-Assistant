import { objectOperation, siteRecord, siteShapeKinds, sitePoints } from '../objects.js';
import { solarPoint, solarFrame, solarUV } from '../twin_solar.js';
import { contains } from '../twin_generator.js';
import * as THREE from 'three';
import { hostPoint, parkingPoint } from '../twin_hosts.js';
import { groundAt, buildingGround, edgeDistance } from '../twin_ground.js';
import { roofEdge } from './roof_tools.js';
import { vertexHandles, editVertex } from './polygon_handles.js';
import { shapeKey, shapeCentre, transformShape, shapeOperation, closedShape } from './site_shapes.js';

const FT = .3048;
const inch = value => Math.round(value * 12) / 12;
const basis = wall => {
  const d = wall.to.map((v, i) => v - wall.from[i]), length = Math.hypot(...d);
  return { length, axis: d.map(v => v / length), normal: [-d[1] / length, d[0] / length, 0] };
};

// Screen affordances and hit testing share the same model points. Structural
// previews stay in drag.js; the server alone decides whether a release fits.
export function createHandles({ view, getPlan, getSelection, canEdit, drag, onCommit, onPreview, onClick, signal }) {
  const canvas = view.renderer3.domElement, host = canvas.parentElement;
  const layer = document.createElement('div'); layer.className = 'editor-handles'; host.append(layer);
  const ring = document.createElement('span'); ring.className = 'editor-site-ring'; ring.hidden = true; layer.append(ring);
  const raycaster = new THREE.Raycaster();
  let rows = [], gesture = null, preview = null, lastFrameMs = null, ringPoints = [];
  const plan = () => preview || getPlan();
  function world(building, point) {
    const a = (building.rotation || 0) * Math.PI / 180, [x, y, z] = point, p = building.position || [0, 0];
    return new THREE.Vector3((Math.cos(a) * x - Math.sin(a) * y + p[0]) * FT,
      (z + (building.base || 0) + (building.id === null ? 0 : buildingGround(plan(), building))) * FT,
      -(Math.sin(a) * x + Math.cos(a) * y + p[1]) * FT);
  }
  function local(building, point) {
    const a = -(building.rotation || 0) * Math.PI / 180, p = building.position || [0, 0];
    const x = point.x / FT - p[0], y = -point.z / FT - p[1];
    return new THREE.Vector3(Math.cos(a) * x - Math.sin(a) * y, Math.sin(a) * x + Math.cos(a) * y,
      point.y / FT - (building.base || 0) - (building.id === null ? 0 : buildingGround(plan(), building)));
  }
  function ray(event, building) {
    const rect = canvas.getBoundingClientRect(); view.camera.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      1 - (event.clientY - rect.top) / rect.height * 2), view.camera);
    const origin = local(building, raycaster.ray.origin);
    return new THREE.Ray(origin, local(building, raycaster.ray.origin.clone().add(raycaster.ray.direction)).sub(origin).normalize());
  }
  function onPlane(event, building, at, normal) {
    return ray(event, building).intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(
      new THREE.Vector3(...normal), new THREE.Vector3(...at)), new THREE.Vector3())?.toArray();
  }
  function project(building, at) {
    view.camera.updateMatrixWorld(true);
    const p = world(building, at).project(view.camera), rect = canvas.getBoundingClientRect();
    if (p.z < -1 || p.z > 1) return null;
    const x = rect.left + (p.x + 1) * rect.width / 2, y = rect.top + (1 - p.y) * rect.height / 2;
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom ? [x, y] : null;
  }
  const coordinateBuilding = id => plan()?.buildings.find(b => b.id === id) || { id: null, position: [0, 0], base: 0 };
  function objectRecord(source = plan()) {
    const selected = getSelection();
    if (['planting', 'furniture'].includes(selected.kind)) {
      const index = source.site?.[selected.kind]?.findIndex((p, i) => (p.id || `${selected.kind}:${i}`) === selected.id) ?? -1;
      if (index >= 0) return { piece: source.site[selected.kind][index], kind: selected.kind, index, building: null };
    }
    const building = source?.buildings.find(b => b.id === selected.building);
    if (!building) return null;
    for (const [list, kind] of [['items', 'item'], ['anchors', 'anchor']]) {
      const piece = building[list]?.find(p => p.id === selected.id);
      if (piece && !piece.device) return { piece, kind, building, list };
    }
    return null;
  }
  function objectDescriptors() {
    const record = objectRecord(); if (!record || record.piece.state === 'ghost') return [];
    const { piece, building } = record;
    let centre;
    try { centre = building ? hostPoint(building, piece.host, piece.offset || 0)
      : [...piece.at, groundAt(plan(), ...piece.at)]; } catch { return []; }
    centre[2] += piece.elevation || 0;
    let radius = Math.max(.5, 2 * (piece.scale ?? 1));
    // At lot zoom a two-foot handle can project onto the move target itself.
    // Keep the transform controls outside that target at every camera distance.
    const frame = building || coordinateBuilding(null), middle = project(frame, centre);
    const edge = project(frame, [centre[0] + radius, centre[1], centre[2]]);
    if (middle && edge) radius *= Math.max(1, 32 / Math.max(.1, Math.hypot(edge[0] - middle[0], edge[1] - middle[1])));
    const level = building && (building.walls.find(w => w.id === piece.host?.wall)?.level
      || building.rooms.find(r => r.id === (piece.host?.floor || piece.host?.ceiling))?.level || getSelection().level || building.levels[0]?.id);
    if (building && view.groups?.levels[`${building.id}:${level}`]?.visible === false) return [];
    return [['object_rotate', [radius, 0, 0]], ['object_scale', [radius, radius, 0]]].map(([kind, delta]) => ({ kind, id: getSelection().id,
      at: centre.map((v, i) => v + delta[i]), centre, level, building: building?.id || null }));
  }
  function descriptors() {
    if (!canEdit()) return [];
    const selected = getSelection(), building = plan()?.buildings.find(b => b.id === selected.building);
    if (!building) {
      const record = siteRecord(plan(), selected.id);
      if (!record || !siteShapeKinds.includes(record.kind)) return objectDescriptors();
      const ps = sitePoints(record.piece); if (!ps.length) return [];
      const centre = shapeCentre(record.piece), z = groundAt(plan(), ...centre) + (record.piece.elevation || 0);
      const radius = record.kind === 'fire_pit' ? record.piece.radius : Math.max(2, ...ps.map(p => Math.hypot(p[0] - centre[0], p[1] - centre[1]) + 2));
      const add = (kind, at, extra = {}) => ({ kind, id: selected.id, building: null, at: [...at, z], centre: [...centre, z], ...extra });
      let move = centre;
      if (!closedShape(record) && record.kind !== 'fire_pit') {
        const frame = coordinateBuilding(null), middle = project(frame, [...centre, z]), edge = project(frame, [centre[0], centre[1] - 2, z]);
        const distance = middle && edge ? Math.max(2, 64 / Math.max(.1, Math.hypot(edge[0] - middle[0], edge[1] - middle[1]))) : 2;
        move = [centre[0], centre[1] - distance];
      }
      const result = [add('site_move', move)];
      if (record.kind === 'fire_pit') return [...result, add('site_radius', [centre[0] + radius, centre[1]])];
      result.push(...vertexHandles(ps, closedShape(record)).map(({ at, ...h }) => add(h.insert ? 'site_insert' : 'site_vertex', at, h)));
      if (record.kind !== 'fence') result.push(add('site_rotate', [centre[0] + radius, centre[1]]), add('site_scale', [centre[0] + radius, centre[1] + radius]));
      return result;
    }
    const result = objectDescriptors(), add = (kind, id, at, level, extra = {}) => {
      if (view.groups?.levels[`${building.id}:${level}`]?.visible === false) return;
      result.push({ kind, id, at, building: building.id, level, ...extra });
    };
    const room = building.rooms.find(r => r.id === selected.room || selected.kind === 'room' && r.id === selected.id);
    if (room && room.state !== 'ghost') {
      const z = building.levels.find(l => l.id === room.level)?.elevation || 0;
      for (const id of room.joints || []) {
        const joint = building.joints.find(j => j.id === id);
        if (joint) add('joint', id, [...joint.at, z], room.level);
      }
      let centre = [0, 1].map(i => room.polygon.reduce((n, p) => n + p[i], 0) / room.polygon.length);
      if (!contains(room.polygon, centre)) centre = room.polygon[0].map((v, i) => v * .99 + centre[i] * .01);
      add('room', room.id, [...centre, z], room.level);
    }
    const wall = building.walls.find(w => selected.kind === 'wall' && w.id === selected.id);
    if (wall && wall.state !== 'ghost') add('wall', wall.id, [...wall.from.map((v, i) => (v + wall.to[i]) / 2),
      building.levels.find(l => l.id === wall.level)?.elevation || 0], wall.level);
    const opening = building.openings.find(o => selected.kind === 'opening' && o.id === selected.id);
    if (opening && opening.state !== 'ghost') {
      const wall = building.walls.find(w => w.id === opening.wall);
      if (wall) {
        const { axis } = basis(wall), elevation = building.levels.find(l => l.id === wall.level)?.elevation || 0;
        const addOpening = (kind, at, height) => add(kind, opening.id,
          [...wall.from.map((v, i) => v + axis[i] * at), elevation + height], wall.level);
        const middle = (opening.sill + opening.head) / 2;
        addOpening('opening_middle', opening.at, middle);
        addOpening('opening_edge_left', opening.at - opening.width / 2, middle);
        addOpening('opening_edge_right', opening.at + opening.width / 2, middle);
        addOpening('opening_edge_top', opening.at, opening.head);
        addOpening('opening_edge_bottom', opening.at, opening.sill);
      }
    }
    const zone=building.solar_zones?.find(z=>selected.kind==='solar_zone' && z.id===selected.id);
    if(zone && zone.state!=='ghost'){
      const r=zone.rect,roof=building.roofs?.find(p=>p.id===zone.roof);
      for(const [kind,uv,edge] of [['solar_middle',[(r[0]+r[2])/2,(r[1]+r[3])/2]],['solar_left',[r[0],(r[1]+r[3])/2],0],['solar_right',[r[2],(r[1]+r[3])/2],2],['solar_bottom',[(r[0]+r[2])/2,r[1]],1],['solar_top',[(r[0]+r[2])/2,r[3]],3]])
        add(kind,zone.id,solarPoint(zone.plane,uv,.15),roof?.level,{edge});
    }
    const roof = building.roofs?.find(r => selected.kind === 'roof' && r.id === selected.id);
    if (roof && roof.state !== 'ghost') roof.edges.forEach((edge, index) => {
      const { a, b } = roofEdge(roof, index);
      add('roof_edge', roof.id, [...a.map((v, i) => (v + b[i]) / 2), roof.plate], roof.level, { edge: index });
    });
    const dormer = building.dormers?.find(d => selected.kind === 'dormer' && d.id === selected.id);
    const parent = dormer && building.roofs?.find(r => r.id === dormer.roof);
    if (parent && dormer.state !== 'ghost') {
      const { a, axis } = roofEdge(parent, dormer.edge), z = parent.plate + (dormer.plate_offset || 0);
      const addDormer = (kind, offset, side) => add(kind, dormer.id,
        [...a.map((v, i) => v + axis[i] * (dormer.at + offset)), z], parent.level, { side });
      addDormer('dormer_middle', 0);
      addDormer('dormer_edge', -dormer.width / 2, -1);
      addDormer('dormer_edge', dormer.width / 2, 1);
    }
    const hosted = ['anchors', 'items'].flatMap(list => building[list] || []).find(p => p.id === selected.id);
    if (hosted && hosted.state !== 'ghost') {
      try {
        const surface = building.walls.find(w => w.id === hosted.host.wall)
          || building.rooms.find(r => [hosted.host.floor, hosted.host.ceiling].includes(r.id))
          || building.roofs?.find(r => r.id === hosted.host.roof);
        add('hosted', hosted.id, hosted.kind==='parking'?parkingPoint(building,hosted,plan(),hosted.offset || 0,groundAt):hostPoint(building, hosted.host, hosted.offset || 0), surface?.level || selected.level || building.levels[0]?.id);
      } catch { /* Lost hosts are represented by their existing flags. */ }
    }
    return result;
  }
  function refresh() {
    const handles = descriptors(), building = coordinateBuilding(getSelection().building);
    const turn = handles.find(h => h.kind === 'site_rotate');
    ring.hidden = !turn;
    ringPoints = [];
    if (turn) {
      const radius = turn.at[0] - turn.centre[0];
      ringPoints = Array.from({ length: 49 }, (_, i) => project(building, [turn.centre[0] + radius * Math.cos(i * Math.PI / 24), turn.centre[1] + radius * Math.sin(i * Math.PI / 24), turn.at[2]]));
    }
    let segments = 0;
    for (let i = 1; i < ringPoints.length; i++) {
      const a = ringPoints[i - 1], b = ringPoints[i]; if (!a || !b) continue;
      let line = ring.children[segments++];
      if (!line) { line = document.createElement('span'); ring.append(line); }
      line.style.left = `${a[0]}px`; line.style.top = `${a[1]}px`;
      line.style.width = `${Math.hypot(b[0] - a[0], b[1] - a[1])}px`;
      line.style.transform = `rotate(${Math.atan2(b[1] - a[1], b[0] - a[0])}rad)`;
    }
    while (ring.children.length > segments) ring.children[ring.children.length - 1].remove();
    let count = 0;
    for (const handle of handles) {
      const pixel = project(building, handle.at); if (!pixel) continue;
      let row = rows[count++];
      if (!row) {
        const node = document.createElement('span'); layer.append(node); row = { node }; rows.push(row);
      }
      Object.assign(row, { handle, pixel });
      row.node.className = `editor-handle editor-handle-${handle.kind}`;
      row.node.style.left = `${pixel[0]}px`; row.node.style.top = `${pixel[1]}px`;
      row.node.setAttribute('aria-hidden', 'true');
      if (handle.kind === 'site_insert') row.node.textContent = '+';
      else row.node.textContent = '';
    }
    while (rows.length > count) rows.pop().node.remove();
  }
  function hit(event) {
    refresh();
    const close = rows.filter(r => Math.hypot(r.pixel[0] - event.clientX, r.pixel[1] - event.clientY) <= 10)
      .sort((a, b) => (a.handle.kind === 'joint' ? -1 : 0) - (b.handle.kind === 'joint' ? -1 : 0)
        || Math.hypot(a.pixel[0] - event.clientX, a.pixel[1] - event.clientY) - Math.hypot(b.pixel[0] - event.clientX, b.pixel[1] - event.clientY));
    if (close.length) return close[0].handle;
    const turn = descriptors().find(h => h.kind === 'site_rotate');
    if (turn) {
      if (ringPoints.some((p, i) => i && p && ringPoints[i - 1] && edgeDistance([event.clientX, event.clientY], ringPoints[i - 1], p) <= 8)) return turn;
    }
    const all = descriptors(), selected = getSelection(), building = plan()?.buildings.find(b => b.id === selected.building);
    const wallHandle = all.find(h => h.kind === 'wall');
    if (wallHandle) {
      const wall = building.walls.find(w => w.id === wallHandle.id), a = project(building, [...wall.from, wallHandle.at[2]]), b = project(building, [...wall.to, wallHandle.at[2]]);
      if (a && b) {
        const d = b.map((v, i) => v - a[i]), length2 = d[0] ** 2 + d[1] ** 2;
        const t = Math.max(0, Math.min(1, ((event.clientX - a[0]) * d[0] + (event.clientY - a[1]) * d[1]) / length2));
        if (Math.hypot(event.clientX - a[0] - t * d[0], event.clientY - a[1] - t * d[1]) <= 10) return wallHandle;
      }
      const picked = view.pick(event.clientX, event.clientY);
      if (picked?.id === wallHandle.id && picked.building === building.id) return wallHandle;
    }
    const roomHandle = all.find(h => h.kind === 'room');
    if (roomHandle) {
      const picked = view.pick(event.clientX, event.clientY);
      if (picked?.kind === 'room' && picked.id === roomHandle.id && picked.building === building.id) return roomHandle;
    }
    return null;
  }
  function begin(event) {
    if (gesture) return false;
    const handle = hit(event); if (!handle) return false;
    const source = getPlan(), building = coordinateBuilding(handle.building);
    if (handle.kind.startsWith('site_')) {
      const start = onPlane(event, building, handle.at, [0, 0, 1]); if (!start) return false;
      const record = siteRecord(source, handle.id);
      gesture = { handle, source, building, record, piece: record.piece, start, normal: [0, 0, 1], operation: null, remove: !!event.altKey };
      // Midpoint click inserts; Alt-click removes. Both post only on release.
      if (handle.kind === 'site_insert' || handle.kind === 'site_vertex' && event.altKey) update(event);
      return true;
    }
    if (handle.kind.startsWith('object_')) {
      const start = onPlane(event, building, handle.centre, [0, 0, 1]);
      if (!start) return false;
      const record = objectRecord(source);
      gesture = { handle, source, building, record, piece: record.piece, normal: [0, 0, 1], start, operation: null }; return true;
    }
    if (['wall', 'joint', 'room'].includes(handle.kind)) {
      lastFrameMs = null;
      const start = view.floorAt(event.clientX, event.clientY, `${building.id}:${handle.level}`);
      if (!drag.begin({ ...getSelection(), ...handle }, start)) return false;
      gesture = { handle, source, building }; return true;
    }
    if(handle.kind.startsWith('solar_')){
      const piece=building.solar_zones.find(z=>z.id===handle.id),normal=solarFrame(piece.plane).n;
      const start=onPlane(event,building,handle.at,normal);if(!start)return false;
      gesture={handle,source,building,piece,list:'solar_zones',normal,start,operation:null};return true;
    }
    if (handle.kind === 'roof_edge' || handle.kind.startsWith('dormer_')) {
      // Start from the shown plan: a released drag is still held while it saves.
      const shown = plan(), building = shown.buildings.find(b => b.id === handle.building);
      const list = handle.kind === 'roof_edge' ? 'roofs' : 'dormers', piece = building[list].find(p => p.id === handle.id);
      const roof = list === 'roofs' ? piece : building.roofs.find(r => r.id === piece.roof);
      const normal = [0, 0, 1], start = onPlane(event, building, handle.at, normal);
      if (!start) return false;
      gesture = { handle, source: shown, building, piece, list, roof, normal, start, operation: null }; return true;
    }
    const list = handle.kind === 'hosted' ? ['anchors', 'items'].find(list => building[list]?.some(p => p.id === handle.id)) : 'openings';
    const piece = building[list].find(p => p.id === handle.id), wall = building.walls.find(w => w.id === (piece.wall || piece.host?.wall));
    const normal = wall ? basis(wall).normal : [0, 0, 1];
    const start = onPlane(event, building, handle.at, normal); if (!start) return false;
    gesture = { handle, source, building, piece, list, wall, normal, start, operation: null };
    return true;
  }
  function wallHost(event, g) {
    const r = ray(event, g.building), old = g.piece.host, current = g.building.walls.find(w => w.id === (g.operation?.host?.wall || old.wall));
    let best = null;
    for (const wall of g.building.walls) {
      if (wall.level !== current.level || wall.state === 'ghost' || wall.kind === 'separator'
        || wall.id !== current.id && !wall.joints.some(id => current.joints.includes(id))) continue;
      const { axis, normal, length } = basis(wall);
      for (const side of ['left', 'right']) {
        const sign = side === 'left' ? 1 : -1, n = new THREE.Vector3(...normal).multiplyScalar(sign);
        if (r.direction.dot(n) >= -1e-6) continue;
        const distance = (wall.thickness || 0) / 2 + (g.piece.offset || 0);
        const at = [...wall.from.map((v, i) => v + normal[i] * sign * distance), 0];
        const point = r.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(n, new THREE.Vector3(...at)), new THREE.Vector3());
        if (!point) continue;
        const along = (point.x - wall.from[0]) * axis[0] + (point.y - wall.from[1]) * axis[1];
        const level = g.building.levels.find(l => l.id === wall.level), z = point.z - level.elevation;
        if (along < 0 || along > length || z < 0 || z > level.ceiling) continue;
        const depth = point.distanceTo(r.origin);
        if (!best || depth < best.depth) best = { depth, host: { wall: wall.id, side, at: inch(along), z: inch(z) } };
      }
    }
    return best?.host;
  }
  function update(event) {
    if (!gesture) return;
    const started = performance.now(), g = gesture, { handle, building, piece } = g;
    if (['wall', 'joint', 'room'].includes(handle.kind)) {
      drag.update(view.floorAt(event.clientX, event.clientY, `${building.id}:${handle.level}`)); return;
    }
    const point = onPlane(event, building, handle.at, g.normal); if (!point) return;
    if (handle.kind.startsWith('site_')) {
      const centre = handle.centre, a = g.start.slice(0, 2).map((v, i) => v - centre[i]), b = point.slice(0, 2).map((v, i) => v - centre[i]);
      let change;
      if (handle.kind === 'site_move') change = transformShape(piece, { centre: centre.slice(0, 2).map((v, i) => v + inch(point[i] - g.start[i])) });
      else if (handle.kind === 'site_radius') change = { radius: Math.max(.1, Math.hypot(...b)) };
      else if (handle.kind === 'site_rotate') {
        let angle = (piece.rotation || 0) + (Math.atan2(b[1], b[0]) - Math.atan2(a[1], a[0])) * 180 / Math.PI;
        if (!event.shiftKey) angle = Math.round(angle / 15) * 15;
        change = transformShape(piece, { rotation: angle });
      } else if (handle.kind === 'site_scale') {
        const scale = Math.max(.001, Math.hypot(...b) / Math.max(.01, Math.hypot(...a)));
        change = transformShape(piece, { scale: [scale, scale] });
      } else change = { [shapeKey(piece)]: editVertex(sitePoints(piece), { ...handle, insert: handle.kind === 'site_insert' }, point.slice(0, 2).map(v => inch(v) || 0), { remove: g.remove, closed: closedShape(g.record) }) };
      g.operation = handle.kind === 'site_move'
        ? { op: 'move_site_item', list: g.record.kind, index: g.record.index, by: point.slice(0, 2).map((v, i) => inch(v - g.start[i])) }
        : shapeOperation(g.record, change);
      preview = structuredClone(g.source);
      const next = ['pool', 'fire_pit', 'fence'].includes(g.record.kind) ? preview.site[g.record.kind] : preview.site[g.record.kind][g.record.index];
      Object.assign(next, change);
      const outline = next.at ? Array.from({ length: 33 }, (_, i) => [next.at[0] + next.radius * Math.cos(i * Math.PI / 16), next.at[1] + next.radius * Math.sin(i * Math.PI / 16)]) : sitePoints(next);
      const points = outline.map(p => project(building, [...p, handle.at[2]])).filter(Boolean);
      document.getElementById('editor-drag-outline')?.setAttribute('points', points.map(p => p.join(',')).join(' '));
      refresh(); lastFrameMs = Math.max(.001, performance.now() - started); return;
    }
    if (handle.kind.startsWith('object_')) {
      const centre = handle.centre, delta = p => p.slice(0, 2).map((v, i) => v - centre[i]);
      const a = delta(g.start), b = delta(point);
      const properties = handle.kind === 'object_rotate'
        ? { rotation: ((piece.rotation || 0) + (Math.atan2(b[1], b[0]) - Math.atan2(a[1], a[0])) * 180 / Math.PI + 720) % 360 }
        : { scale: Math.max(.05, Math.min(20, (piece.scale ?? 1) * Math.hypot(...b) / Math.max(.01, Math.hypot(...a)))) };
      g.operation = objectOperation(g.record, properties);
      preview = structuredClone(g.source);
      const next = g.record.building ? preview.buildings.find(b => b.id === g.building.id)[g.record.list].find(p => p.id === piece.id)
        : preview.site[g.record.kind][g.record.index];
      Object.assign(next, properties);
      if (g.record.building) view.rebuildLevel(g.building.id, handle.level, preview, { [g.record.list]: [piece.id] });
      onPreview?.(preview, getSelection()); refresh(); lastFrameMs = Math.max(.001, performance.now() - started); return;
    }
    if (handle.kind === 'roof_edge' || handle.kind.startsWith('dormer_')) {
      const edge = handle.kind === 'roof_edge' ? handle.edge : piece.edge, frame = roofEdge(g.roof, edge);
      const change = point.slice(0, 2).map((v, i) => v - g.start[i]);
      let operation;
      if (handle.kind === 'roof_edge') {
        const by = inch(change.reduce((n, v, i) => n + v * frame.normal[i], 0));
        const attachment = piece.edges[edge], wall = building.walls.find(w => w.id === attachment.wall);
        let detach = false;
        if (wall) {
          const axis = Math.abs(frame.axis[0]) < .5 ? 0 : 1;
          detach = Math.abs(frame.a[axis] + frame.normal[axis] * by - wall.from[axis]) > 1 + 1e-6;
        }
        operation = { op: 'move_roof_edge', building: building.id, roof: piece.id, edge, by, detach };
      } else {
        const along = inch(change.reduce((n, v, i) => n + v * frame.axis[i], 0));
        operation = { op: 'move_dormer', building: building.id, id: piece.id,
          at: piece.at + along / (handle.kind === 'dormer_middle' ? 1 : 2) };
        if (handle.kind === 'dormer_edge') operation.width = piece.width + handle.side * along;
      }
      g.operation = operation; preview = structuredClone(g.source);
      const nextBuilding = preview.buildings.find(b => b.id === building.id), next = nextBuilding[g.list].find(p => p.id === piece.id);
      if (handle.kind === 'roof_edge') {
        for (const index of [edge, (edge + 1) % next.area.length])
          next.area[index] = next.area[index].map((v, i) => v + frame.normal[i] * operation.by);
      } else { next.at = operation.at; if ('width' in operation && operation.width > 0) next.width = operation.width; }
      // Preview the edited boundary without rebuilding the yard and roof union
      // on every pointer event. The committed model rebuilds the roof planes.
      const boundary = handle.kind === 'roof_edge' ? next.area : [
        frame.a.map((v, i) => v + frame.axis[i] * (next.at - next.width / 2)),
        frame.a.map((v, i) => v + frame.axis[i] * (next.at + next.width / 2))];
      document.getElementById('editor-drag-outline')?.setAttribute('points', boundary.map(p => project(building, [...p, handle.at[2]]))
        .filter(Boolean).map(p => p.join(',')).join(' '));
      onPreview?.(preview, getSelection()); refresh();
      lastFrameMs = Math.max(.001, performance.now() - started); return;
    }
    if(handle.kind.startsWith('solar_')){
      const a=solarUV(piece.plane,g.start),b=solarUV(piece.plane,point),delta=b.map((v,i)=>inch(v-a[i])),rect=[...piece.rect];
      if(handle.kind==='solar_middle')for(let i=0;i<4;i++)rect[i]+=delta[i%2];
      else rect[handle.edge]+=delta[handle.edge%2];
      g.operation={op:'update_solar_zone',building:building.id,id:piece.id,rect};
      preview=structuredClone(g.source);preview.buildings.find(b=>b.id===building.id).solar_zones.find(z=>z.id===piece.id).rect=rect;
      const points=[[rect[0],rect[1]],[rect[2],rect[1]],[rect[2],rect[3]],[rect[0],rect[3]]].map(p=>project(building,solarPoint(piece.plane,p,.15))).filter(Boolean);
      document.getElementById('editor-drag-outline')?.setAttribute('points',points.map(p=>p.join(',')).join(' '));
      onPreview?.(preview,getSelection());refresh();lastFrameMs=Math.max(.001,performance.now()-started);return;
    }
    const operation = { op: handle.kind.startsWith('opening_edge') ? 'resize_opening' : 'move_hosted', building: building.id, id: piece.id };
    if (handle.kind.startsWith('opening')) {
      const { axis } = basis(g.wall), along = inch((point[0] - g.start[0]) * axis[0] + (point[1] - g.start[1]) * axis[1]);
      const up = inch(point[2] - g.start[2]);
      if (handle.kind === 'opening_middle') operation.at = piece.at + along;
      else if (handle.kind === 'opening_edge_left') { operation.width = piece.width - along; operation.at = piece.at + along / 2; }
      else if (handle.kind === 'opening_edge_right') { operation.width = piece.width + along; operation.at = piece.at + along / 2; }
      else if (handle.kind === 'opening_edge_top') operation.head = piece.head + up;
      else operation.sill = piece.sill + up;
    } else if (piece.host.wall) {
      const host = wallHost(event, g); if (!host) return;
      operation.host = host;
    } else if (piece.host.roof) {
      const roof = building.roofs?.find(r => r.id === piece.host.roof), edge = piece.host.edge;
      const a = roof?.area[edge], b = roof?.area[(edge + 1) % roof.area.length];
      if (!a || !b) return;
      const d = b.map((v, i) => v - a[i]), length = Math.hypot(...d);
      operation.host = { ...piece.host, at: piece.host.at + inch(point.slice(0, 2).reduce((n, v, i) => n + (v - g.start[i]) * d[i] / length, 0)) };
    } else if (piece.host.ground) {
      operation.host={ground:true,at:piece.host.at.map((v,i)=>inch(v+point[i]-g.start[i]))};
    } else {
      const rooms = building.rooms.filter(r => r.state !== 'ghost' && r.level === handle.level);
      const room = rooms.find(r => contains(r.polygon, point));
      const surface = piece.host.ceiling ? 'ceiling' : 'floor';
      if (piece.host.ground) operation.host = { ground: true, at: point.slice(0, 2).map(inch) };
      else if (room) {
        const xs = room.polygon.map(p => p[0]), ys = room.polygon.map(p => p[1]), x0 = Math.min(...xs), y0 = Math.min(...ys);
        operation.host = { [surface]: room.id, u: (point[0] - x0) / (Math.max(...xs) - x0), v: (point[1] - y0) / (Math.max(...ys) - y0) };
      } else return;
    }
    g.operation = operation;
    preview = structuredClone(g.source);
    const nextBuilding = preview.buildings.find(b => b.id === building.id), next = nextBuilding[g.list].find(p => p.id === piece.id);
    for (const field of ['at', 'width', 'head', 'sill']) if (field in operation) next[field] = operation[field];
    if (operation.host) next.host = { ...operation.host };
    else if (next.host) { next.host.at = next.at; next.host.sill = next.sill; }
    // Keep the last drawable buffers if an edge passes its opposite edge.
    // Still send the release unchanged so refusal and its words come from the server.
    if (g.list !== 'openings' || next.width > 0 && next.head > next.sill)
      view.rebuildLevel(building.id, handle.level, preview, { [g.list]: [piece.id] });
    onPreview?.(preview, getSelection()); refresh();
    lastFrameMs = Math.max(.001, performance.now() - started);
  }
  async function finish(cancel = false, clicked = false) {
    const g = gesture, released = preview; gesture = null; preview = null;
    if (!g) return;
    if (g.handle.kind.startsWith('site_')) {
      document.getElementById('editor-drag-outline')?.setAttribute('points', '');
      const cornerClick = clicked && (g.handle.kind === 'site_insert' || g.handle.kind === 'site_vertex' && g.remove);
      try { if ((!cancel || cornerClick) && g.operation && Object.entries(g.operation).some(([k, v]) => !['op', 'list', 'index'].includes(k) && JSON.stringify(v) !== JSON.stringify(g.piece[k]))) await onCommit(g.operation); }
      finally { refresh(); }
      return;
    }
    if (g.handle.kind.startsWith('object_')) {
      try { if (!cancel && g.operation) await onCommit(g.operation); }
      finally {
        if (g.record.building) view.rebuildLevel(g.building.id, g.handle.level, getPlan(), { [g.record.list]: [g.piece.id] });
        onPreview?.(getPlan(), getSelection()); refresh();
      }
      return;
    }
    if (g.handle.kind === 'roof_edge' || g.handle.kind.startsWith('dormer_') || g.handle.kind.startsWith('solar_')) {
      document.getElementById('editor-drag-outline')?.setAttribute('points', '');
      if (clicked && g.handle.kind === 'roof_edge') onClick?.(g.handle);
      const saving = !cancel && g.operation;
      // Handles stay where they were released until the save answers;
      // a refusal drops the held plan and they return to the stored piece.
      if (saving) preview = released;
      try { if (saving) await onCommit(g.operation); }
      finally {
        if (saving && preview === released) preview = null;
        onPreview?.(plan(), getSelection()); refresh();
      }
      return;
    }
    if (['wall', 'joint', 'room'].includes(g.handle.kind)) {
      try { await drag.finish(cancel); }
      finally { preview = null; refresh(); }
      return;
    }
    const restore = () => { view.rebuildLevel(g.building.id, g.handle.level, g.source, { [g.list]: [g.piece.id] }); onPreview?.(g.source, getSelection()); refresh(); };
    if (cancel || !g.operation) { restore(); return; }
    try { await onCommit(g.operation); }
    catch (error) { restore(); throw error; }
    refresh();
  }
  view.controls.addEventListener('change', refresh);
  host.addEventListener('twinrebuilt', refresh, { signal });
  window.addEventListener('resize', refresh, { signal });
  signal.addEventListener('abort', () => { view.controls.removeEventListener('change', refresh); layer.remove(); }, { once: true });
  return { begin, update, finish, refresh, hit, active: () => !!gesture,
    show(value) { preview = value; refresh(); },
    handles() {
      refresh();
      // Roof edges can span more than the current camera frame. Keep their
      // model points discoverable so looking at an edge reveals its handle.
      const all = descriptors(), roof = all.filter(h => h.kind === 'roof_edge' || h.kind.startsWith('dormer_'));
      return [...rows.map(({ handle }) => handle).filter(h => h.kind !== 'roof_edge' && !h.kind.startsWith('dormer_')), ...roof]
        .map(handle => ({ kind: handle.kind, id: handle.id, at: [...handle.at] }));
    },
    get lastDragFrameMs() { return lastFrameMs ?? drag.lastDragFrameMs; } };
}
