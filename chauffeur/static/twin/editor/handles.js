import { applyLocal } from './local_ops.js';
import { roomFloor, openingFloor } from '../twin_floors.js';
import { siteRecord, siteShapeKinds, sitePoints, sitePieces } from '../objects.js';
import { solarPoint, solarFrame, solarUV } from '../twin_solar.js';
import { contains } from '../twin_generator.js';
import * as THREE from 'three';
import { hostPoint, parkingPoint } from '../twin_hosts.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { roofEdge } from './roof_tools.js';
import { isSupported, supportPoints, roofPoint } from '../roof_supports.js';
import { vertexHandles, editVertex } from './polygon_handles.js';
import { shapeKey, shapeCentre, transformShape, shapeOperation, closedShape } from './site_shapes.js';
import { pathOutline } from '../path_shapes.js';
import { roundPit, firePitOutline } from '../fire_pits.js';
import { HANDLE_HIT_PX } from './picking.js';
import { snapValue } from './snap.js';
import { createTypedValue } from './typed_value.js';
import { gutterSnapshot, downspoutValues, downspoutIndex, edgeOperation, freeCandidates, snapOrExact, entryFraction, isExact, sameDownspoutEntry } from './gutter_controls.js';
import { findPost } from '../porch_posts.js';
import { buildPostSnapTargets, snapPostPoint } from './porch_post_shelf.js';

const FT = .3048;
const inch = value => Math.round(value * 12) / 12;
const sameValue = (a, b) => Array.isArray(a) && Array.isArray(b)
  ? a.length === b.length && a.every((v, i) => sameValue(v, b[i]))
  : typeof a === 'number' && typeof b === 'number' ? Math.abs(a - b) < 1e-8 : a === b;
const basis = wall => {
  const d = wall.to.map((v, i) => v - wall.from[i]), length = Math.hypot(...d);
  return { length, axis: d.map(v => v / length), normal: [-d[1] / length, d[0] / length, 0] };
};

// Screen affordances and hit testing share the same model points. Structural
// previews stay in drag.js; the server alone decides whether a release fits.
export function createHandles({ view, getPlan, getSelection, getTool = () => 'move', canEdit, drag, onCommit, onPreview, onClick, signal }) {
  const canvas = view.renderer3.domElement, host = canvas.parentElement;
  const layer = document.createElement('div'); layer.className = 'editor-handles'; host.append(layer);
  const typed = createTypedValue(layer);
  const raycaster = new THREE.Raycaster();
  let rows = [], gesture = null, preview = null, lastFrameMs = null;
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
  function descriptors() {
    if (!canEdit()) return [];
    const selected = getSelection(), building = plan()?.buildings.find(b => b.id === selected.building);
    if (!building) {
      const record = siteRecord(plan(), selected.id);
      if (!record || !siteShapeKinds.includes(record.kind)) return [];
      const ps = sitePoints(record.piece); if (!ps.length) return [];
      const centre = shapeCentre(record.piece), z = groundAt(plan(), ...centre) + (record.piece.elevation || 0);
      const round = record.kind === 'fire_pit' && roundPit(record.piece);
      const radius = round ? record.piece.radius ?? 2 : Math.max(2, ...ps.map(p => Math.hypot(p[0] - centre[0], p[1] - centre[1]) + 2));
      const add = (kind, at, extra = {}) => ({ kind, id: selected.id, building: null, at: [...at, z], centre: [...centre, z], ...extra });
      let move = centre;
      if (!closedShape(record) && record.kind !== 'fire_pit') {
        const frame = coordinateBuilding(null), middle = project(frame, [...centre, z]), edge = project(frame, [centre[0], centre[1] - 2, z]);
        const distance = middle && edge ? Math.max(2, 64 / Math.max(.1, Math.hypot(edge[0] - middle[0], edge[1] - middle[1]))) : 2;
        move = [centre[0], centre[1] - distance];
      }
      const result = [add('site_move', move)];
      if (round) return [...result, add('site_radius', [centre[0] + radius, centre[1]])];
      result.push(...vertexHandles(ps, closedShape(record)).map(({ at, ...h }) => add(h.insert ? 'site_insert' : 'site_vertex', at, h)));
      return result;
    }
    const result = [], add = (kind, id, at, level, extra = {}) => {
      if (view.groups?.levels[`${building.id}:${level}`]?.visible === false) return;
      result.push({ kind, id, at, building: building.id, level, ...extra });
    };
    const room = building.rooms.find(r => r.id === selected.room || selected.kind === 'room' && r.id === selected.id);
    if (room && room.state !== 'ghost') {
      const z = roomFloor(building.levels.find(l => l.id === room.level), room);
      for (const id of room.joints || []) {
        const joint = building.joints.find(j => j.id === id);
        if (joint) add('joint', id, [...joint.at, z], room.level);
      }
      let centre = [0, 1].map(i => room.polygon.reduce((n, p) => n + p[i], 0) / room.polygon.length);
      if (!contains(room.polygon, centre)) centre = room.polygon[0].map((v, i) => v * .99 + centre[i] * .01);
      add('room', room.id, [...centre, z], room.level);
    }
    const wall = building.walls.find(w => selected.kind === 'wall' && w.id === selected.id);
    const stair = building.stairs?.find(s => selected.kind === 'stair' && s.id === selected.id);
    if (stair && stair.state !== 'ghost') for (const end of ['from', 'to'])
      add('stair_end', stair.id, [...stair[end], end === 'to' ? stair.rise_to
        : building.levels.find(l => l.id === stair.level)?.elevation || 0], stair.level, { end });
    if (wall && wall.state !== 'ghost') {
      const z = building.levels.find(l => l.id === wall.level)?.elevation || 0;
      add('wall', wall.id, [...wall.from.map((v, i) => (v + wall.to[i]) / 2), z], wall.level);
      for (const id of wall.joints || []) {
        const joint = building.joints.find(j => j.id === id);
        if (joint && !result.some(h => h.kind === 'joint' && h.id === id)) add('joint', id, [...joint.at, z], wall.level);
      }
    }
    const opening = building.openings.find(o => selected.kind === 'opening' && o.id === selected.id);
    if (opening && opening.state !== 'ghost') {
      const wall = building.walls.find(w => w.id === opening.wall);
      if (wall) {
        const { axis } = basis(wall), elevation = (building.levels.find(l => l.id === wall.level)?.elevation || 0) + openingFloor(building, wall, opening.at).offset;
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
    if (roof && roof.state !== 'ghost' && isSupported(roof)) {
      for (const [index, p] of supportPoints(roof).entries())
        add('roof_support', roof.id, [...p.at, roof.plate], roof.level, { index });
      const centre = roofPoint(roof, [0, 1].map(i => roof.area.reduce((n, p) => n+p[i], 0)/roof.area.length));
      add('roof_height', roof.id, [...centre, roof.plate], roof.level, { offset: [0, -32] });
    }
    if (roof && roof.state !== 'ghost' && roof.edges.some(e => e.gutter)) {
      const snapshot = gesture?.handle.kind === 'downspout' ? gesture.snapshot : gutterSnapshot(getPlan());
      const runs = new Set(snapshot.runs.filter(r => r.building === building.id).map(r => r.id));
      for (const spout of snapshot.spouts) {
        if (!runs.has(spout.run) || spout.edge.roof !== roof.id || !Number.isInteger(spout.edge.edge)) continue;
        const at = local(building, new THREE.Vector3(...spout.top)).toArray();
        if (gesture?.handle.spout === spout.id && gesture.point) at.splice(0, 2, ...gesture.point);
        add('downspout', roof.id, at, roof.level, {
          edge: spout.edge.edge, fraction: spout.authoredFraction ?? spout.edge.fraction,
          placedFraction: spout.edge.fraction, exact: !!spout.exact,
          ...(Number.isInteger(spout.authoredIndex) ? { authoredIndex: spout.authoredIndex } : {}),
          spout: spout.id, run: spout.run,
        });
      }
    }
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
    if (selected.kind === 'porch_post') {
      const post = findPost(building, selected.id);
      if (post && post.porch.state !== 'ghost') {
        const room = building.rooms?.find(r => r.id === post.porchId);
        const levelId = post.porch.level || room?.level || building.levels?.[0]?.id;
        const level = building.levels?.find(l => l.id === levelId);
        const z = (post.porch.floor ?? level?.elevation ?? 0) + (room?.floor_offset_ft || 0);
        add('porch_post', post.id, [...post.piece.at, z], levelId, { porchId: post.porchId, index: post.index, size: post.piece.size ?? 0.5 });
      }
    }
    return result;
  }
  function refresh() {
    const handles = descriptors(), building = coordinateBuilding(getSelection().building);
    let count = 0;
    for (const handle of handles) {
      const pixel = project(building, handle.at); if (!pixel) continue;
      if (handle.offset) for (const i of [0, 1]) pixel[i] += handle.offset[i];
      let row = rows[count++];
      if (!row) {
        const node = document.createElement('span'); layer.append(node); row = { node }; rows.push(row);
      }
      Object.assign(row, { handle, pixel });
      row.node.className = `editor-handle editor-handle-${handle.kind}`;
      row.node.style.left = `${pixel[0]}px`; row.node.style.top = `${pixel[1]}px`;
      row.node.setAttribute('aria-hidden', 'true');
      if (handle.kind === 'roof_height') row.node.textContent = '\u2195';
      else if (handle.kind === 'site_insert') row.node.textContent = '+';
      else row.node.textContent = '';
    }
    while (rows.length > count) rows.pop().node.remove();
  }
  function hit(event) {
    refresh();
    const close = rows.filter(r => Math.hypot(r.pixel[0] - event.clientX, r.pixel[1] - event.clientY) <= HANDLE_HIT_PX)
      .sort((a, b) => (a.handle.kind === 'joint' ? -1 : 0) - (b.handle.kind === 'joint' ? -1 : 0)
        || Math.hypot(a.pixel[0] - event.clientX, a.pixel[1] - event.clientY) - Math.hypot(b.pixel[0] - event.clientX, b.pixel[1] - event.clientY));
    if (close.length) return close[0].handle;
    if (getTool() === 'select') return null;
    const all = descriptors(), selected = getSelection(), building = plan()?.buildings.find(b => b.id === selected.building);
    const wallHandle = all.find(h => h.kind === 'wall');
    if (wallHandle) {
      const wall = building.walls.find(w => w.id === wallHandle.id), a = project(building, [...wall.from, wallHandle.at[2]]), b = project(building, [...wall.to, wallHandle.at[2]]);
      if (a && b) {
        const d = b.map((v, i) => v - a[i]), length2 = d[0] ** 2 + d[1] ** 2;
        const t = Math.max(0, Math.min(1, ((event.clientX - a[0]) * d[0] + (event.clientY - a[1]) * d[1]) / length2));
        if (Math.hypot(event.clientX - a[0] - t * d[0], event.clientY - a[1] - t * d[1]) <= HANDLE_HIT_PX) return wallHandle;
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
  function begin(event, handle = hit(event)) {
    if (gesture) return false;
    if (!canEdit() || !handle) return false;
    lastFrameMs = null; drag.clearDragFrame?.();
    const source = getPlan(), building = coordinateBuilding(handle.building);
    if (handle.kind === 'porch_post') {
      const post = findPost(building, handle.id);
      if (!post) return false;
      const normal = [0, 0, 1], start = onPlane(event, building, handle.at, normal);
      if (!start) return false;
      const snapTargets = buildPostSnapTargets(post.porch, post.index, post.piece.size ?? 0.5);
      gesture = { handle, source, building, piece: post.piece, post, normal, start, snapTargets, event, operation: null };
      typed.show('length', 0, [event.clientX, event.clientY]);
      return true;
    }
    if (handle.kind === 'roof_support' || handle.kind === 'roof_height') {
      const piece = building.roofs.find(r => r.id === handle.id);
      // Height uses a vertical plane facing the camera, points use the roof plane.
      const normal = handle.kind === 'roof_height' ? local(building, view.camera.position).sub(new THREE.Vector3(...handle.at)).setZ(0).normalize().toArray() : [0, 0, 1];
      const start = onPlane(event, building, handle.at, normal); if (!start) return false;
      gesture = { handle, source, building, piece, list: 'roofs', normal, start, event, operation: null };
      typed.show('length', handle.kind === 'roof_height' ? piece.plate : 0, [event.clientX, event.clientY]);
      return true;
    }
    if (handle.kind === 'downspout') {
      const piece = building.roofs.find(r => r.id === handle.id), normal = [0, 0, 1];
      const start = onPlane(event, building, handle.at, normal); if (!start) return false;
      const snapshot = gutterSnapshot(source);
      const values = downspoutValues(source, building.id, piece.id, handle.edge, snapshot);
      const index = downspoutIndex(values, handle.fraction, handle.authoredIndex);
      const { a, b, length, axis } = roofEdge(piece, handle.edge), d = b.map((v, i) => v - a[i]), len2 = d[0] ** 2 + d[1] ** 2 || 1;
      const tOf = p => ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / len2;
      const rest = Number.isFinite(handle.placedFraction) ? handle.placedFraction : Math.max(0, Math.min(1, tOf(handle.at)));
      const handleT = tOf(handle.at), startT = tOf(start);
      const rel = [handle.at[0] - a[0], handle.at[1] - a[1]], along = rel[0] * axis[0] + rel[1] * axis[1];
      const perp = [rel[0] - along * axis[0], rel[1] - along * axis[1]];
      const candidates = freeCandidates(source, building.id, piece.id, handle.edge, {
        snapshot, excludeIndex: index, ownFraction: handle.exact ? null : rest,
      });
      const endPoints = snapshot.runs.filter(r => r.building === building.id).flatMap(r => (r.segments || [])
        .filter(s => s.roof === piece.id && s.edge === handle.edge && Array.isArray(s.a) && Array.isArray(s.b))
        .flatMap(s => [s.a, s.b].map(p => local(building, new THREE.Vector3(...p)).toArray())));
      const dripFor = f => {
        let bestEnd = null, bestGap = 1e-4;
        for (const p of endPoints) {
          const gap = Math.abs(Math.max(0, Math.min(1, tOf(p))) - f);
          if (gap < bestGap) { bestGap = gap; bestEnd = p; }
        }
        if (!bestEnd) return null;
        const cAlong = (bestEnd[0] - a[0]) * axis[0] + (bestEnd[1] - a[1]) * axis[1];
        return [a[0] + axis[0] * cAlong + perp[0], a[1] + axis[1] * cAlong + perp[1]];
      };
      const candidatePoints = new Map();
      for (const c of candidates)
        candidatePoints.set(c.fraction, dripFor(c.fraction) || [a[0] + axis[0] * (c.fraction * length) + perp[0], a[1] + axis[1] * (c.fraction * length) + perp[1]]);
      const endDrip = new Map();
      for (const endF of [0, 1]) {
        const pt = dripFor(endF);
        if (pt) endDrip.set(endF, pt);
      }
      gesture = { handle, source, snapshot, building, piece, normal, start, values, candidates, candidatePoints, endDrip,
        index, original: index >= 0 ? values[index] : undefined, rest, handleT, startT, perp, operation: null };
      return true;
    }
    if (handle.kind === 'stair_end') {
      const piece = building.stairs.find(s => s.id === handle.id), normal = [0, 0, 1];
      const start = onPlane(event, building, handle.at, normal); if (!start) return false;
      gesture = { handle, source, building, piece, normal, start, operation: null }; return true;
    }
    if (handle.kind.startsWith('site_')) {
      const start = onPlane(event, building, handle.at, [0, 0, 1]); if (!start) return false;
      const record = siteRecord(source, handle.id);
      gesture = { handle, source, building, record, piece: record.piece, start, normal: [0, 0, 1], operation: null, remove: !!event.altKey };
      // Midpoint click inserts; Alt-click removes. Both post only on release.
      if (handle.kind === 'site_insert' || handle.kind === 'site_vertex' && event.altKey) update(event);
      return true;
    }
    if (['wall', 'joint', 'room'].includes(handle.kind)) {
      lastFrameMs = null;
      const floorOffset = handle.at[2] - (building.levels.find(l => l.id === handle.level)?.elevation || 0);
      const start = view.floorAt(event.clientX, event.clientY, `${building.id}:${handle.level}`, floorOffset);
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
  function wallHost(event, g, free) {
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
        if (!best || depth < best.depth) best = { depth, host: { wall: wall.id, side,
          at: free ? along : inch(along), z: free ? z : inch(z) } };
      }
    }
    return best?.host;
  }
  function update(event, { free = !!event.shiftKey, typed: exact } = {}) {
    if (!gesture) return;
    const started = performance.now(), g = gesture, { handle, building, piece } = g;
    g.event = event;
    const inch = value => free ? value : Math.round(value * 12) / 12;
    const move = value => snapValue('move', value, free);
    const showValue = (kind, value) => typed.show(kind, value, [event.clientX, event.clientY]);
    if (['wall', 'joint', 'room'].includes(handle.kind)) {
      const floorOffset = handle.at[2] - (building.levels.find(l => l.id === handle.level)?.elevation || 0);
      drag.update(view.floorAt(event.clientX, event.clientY, `${building.id}:${handle.level}`, floorOffset), { free });
      showValue('length', drag.value()); return;
    }
    let point = onPlane(event, building, handle.at, g.normal); if (!point) return;
    if (handle.kind === 'porch_post') {
      let raw = point.slice(0, 2).map((v, i) => handle.at[i] + (v - g.start[i]));
      if (Number.isFinite(exact)) {
        const delta = raw.map((v, i) => v - handle.at[i]), length = Math.hypot(...delta);
        raw = handle.at.slice(0, 2).map((v, i) => v + exact * (length ? delta[i] / length : i === 0 ? 1 : 0));
      }
      const at = Number.isFinite(exact) ? raw : snapPostPoint(raw, g.snapTargets, free).point;
      showValue('length', Math.hypot(at[0] - handle.at[0], at[1] - handle.at[1]));
      g.operation = sameValue(at, handle.at.slice(0, 2)) ? null : {
        op: 'update_porch_post', building: building.id, porch: g.post.porchId, post: g.post.id, at,
      };
      g.postAt = at;
      preview = structuredClone(g.source);
      const nextPost = findPost(preview.buildings.find(b => b.id === building.id), g.post.id);
      if (nextPost) nextPost.piece.at = [...at];
      const half = (g.post.piece.size ?? 0.5) / 2;
      const box = [[at[0] - half, at[1] - half], [at[0] + half, at[1] - half], [at[0] + half, at[1] + half], [at[0] - half, at[1] + half], [at[0] - half, at[1] - half]];
      document.getElementById('editor-drag-outline')?.setAttribute('points', box.map(p => project(building, [...p, handle.at[2]])).filter(Boolean).map(p => p.join(',')).join(' '));
      onPreview?.(preview, getSelection()); refresh(); lastFrameMs = Math.max(.001, performance.now() - started); return;
    }
    if (handle.kind === 'roof_support' || handle.kind === 'roof_height') {
      if (handle.kind === 'roof_support') {
        const at = point.slice(0, 2).map((v, i) => handle.at[i]+move(v-g.start[i]));
        g.operation = sameValue(at, handle.at.slice(0, 2)) ? null : { op: 'set_roof_support', building: building.id, id: piece.id,
          at: { [handle.index]: at } };
        g.supportAt = at;
      } else {
        const value = Number.isFinite(exact) ? exact : piece.plate+inch(point[2]-g.start[2]);
        g.operation = value === piece.plate ? null : { op: 'set', building: building.id, id: piece.id, field: 'plate', value };
        g.plate = value;
        showValue('length', value);
      }
      preview = structuredClone(g.source);
      const next = preview.buildings.find(b => b.id === building.id).roofs.find(r => r.id === piece.id);
      if (handle.kind === 'roof_support') next.support.at = { ...(piece.support.at || {}), [handle.index]: g.supportAt };
      else next.plate = g.plate;
      onPreview?.(preview, getSelection()); refresh(); lastFrameMs = Math.max(.001, performance.now()-started); return;
    }
    if (handle.kind === 'downspout') {
      const { a, b } = roofEdge(piece, handle.edge), d = b.map((v, i) => v - a[i]), len2 = d[0] ** 2 + d[1] ** 2 || 1;
      const pointerT = ((point[0] - a[0]) * d[0] + (point[1] - a[1]) * d[1]) / len2;
      const rawFraction = Math.max(0, Math.min(1, g.handleT + pointerT - g.startT));
      const entry = snapOrExact(g.source, building.id, piece.id, handle.edge, rawFraction, g.candidates);
      const unchanged = sameDownspoutEntry(entry, g.original)
        || (typeof g.original === 'number' && typeof entry === 'number' && Math.abs(entry - g.rest) < 1e-6);
      if (unchanged) {
        g.operation = null;
      } else {
        const values = g.values.map(v => typeof v === 'object' && v ? { ...v } : v);
        if (g.index < 0) { if (values.length >= 8) return; values.push(entry); } else values[g.index] = entry;
        g.operation = edgeOperation(building.id, piece.id, handle.edge, { downspouts: values });
      }
      if (typeof entry === 'number' && g.candidatePoints.has(entry)) {
        g.point = g.candidatePoints.get(entry);
      } else if (isExact(entry) && (entry.at === 0 || entry.at === 1) && g.endDrip.has(entry.at)) {
        g.point = g.endDrip.get(entry.at);
      } else {
        const displayFraction = entryFraction(entry);
        g.point = [a[0] + displayFraction * d[0] + g.perp[0], a[1] + displayFraction * d[1] + g.perp[1]];
      }
      // Only move the screen handle during the gesture; placement/roof geometry
      // rebuild once on release, through the normal editor operation path.
      refresh(); lastFrameMs = Math.max(.001, performance.now() - started); return;
    }
    if (handle.kind === 'hosted' && !piece.host.wall && !piece.host.roof)
      point = point.map((v, i) => g.start[i] + move(v - g.start[i]));
    if (Number.isFinite(exact) && handle.kind === 'site_move') {
      const by = point.slice(0, 2).map((v, i) => v - g.start[i]), length = Math.hypot(...by);
      point = [...g.start.slice(0, 2).map((v, i) => v + exact * (length ? by[i] / length : i === 0 ? 1 : 0)), point[2]];
    }
    if (handle.kind === 'stair_end') {
      const to = piece[handle.end].map((v, i) => v + inch(point[i] - g.start[i]));
      g.operation = sameValue(to, piece[handle.end]) ? null
        : { op: 'update_stair', building: building.id, id: piece.id, [handle.end]: to };
      preview = structuredClone(g.source);
      const next = preview.buildings.find(b => b.id === building.id).stairs.find(s => s.id === piece.id);
      next[handle.end] = to;
      const points = [next.from, next.to].map((p, i) => project(building, [...p, i ? next.rise_to
        : building.levels.find(l => l.id === next.level)?.elevation || 0])).filter(Boolean);
      document.getElementById('editor-drag-outline')?.setAttribute('points', points.map(p => p.join(',')).join(' '));
      onPreview?.(preview, getSelection()); refresh(); lastFrameMs = Math.max(.001, performance.now() - started); return;
    }
    if (handle.kind.startsWith('site_')) {
      const centre = handle.centre, b = point.slice(0, 2).map((v, i) => v - centre[i]);
      let change;
      if (handle.kind === 'site_move') {
        const by = point.slice(0, 2).map((v, i) => move(v - g.start[i]));
        change = transformShape(piece, { centre: centre.slice(0, 2).map((v, i) => v + by[i]) });
        showValue('length', Math.hypot(...by));
      }
      else if (handle.kind === 'site_radius') change = { radius: Math.max(.1, move(Math.hypot(...b))) };
      else {
        // Snap the movement, preserving an already rotated corner's coordinates.
        const target = handle.kind === 'site_vertex' ? sitePoints(piece)[handle.index].map((v, i) => v + inch(point[i] - g.start[i]))
          : point.slice(0, 2).map(v => inch(v) || 0);
        change = { [shapeKey(piece)]: editVertex(sitePoints(piece), { ...handle, insert: handle.kind === 'site_insert' }, target, { remove: g.remove, closed: closedShape(g.record) }) };
      }
      g.operation = handle.kind === 'site_move'
        ? { op: 'move_site_item', list: g.record.kind, index: g.record.index, by: point.slice(0, 2).map((v, i) => move(v - g.start[i])) }
        : shapeOperation(g.record, change);
      preview = structuredClone(g.source);
      const next = sitePieces(preview.site[g.record.kind])[g.record.index];
      Object.assign(next, change);
      const outline = g.record.kind === 'fire_pit' ? firePitOutline(next) : next.kind === 'path' ? pathOutline(next) : sitePoints(next);
      const points = outline.map(p => project(building, [...p, handle.at[2]])).filter(Boolean);
      document.getElementById('editor-drag-outline')?.setAttribute('points', points.map(p => p.join(',')).join(' '));
      refresh(); lastFrameMs = Math.max(.001, performance.now() - started); return;
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
        const angle = -(piece.roof_frame?.angle || 0), c = Math.cos(angle), s = Math.sin(angle);
        const normal = [c*frame.normal[0]-s*frame.normal[1], s*frame.normal[0]+c*frame.normal[1]];
        for (const index of [edge, (edge + 1) % next.area.length])
          next.area[index] = next.area[index].map((v, i) => v + normal[i] * operation.by);
      } else { next.at = operation.at; if ('width' in operation && operation.width > 0) next.width = operation.width; }
      // Preview the edited boundary without rebuilding the yard and roof union
      // on every pointer event. The committed model rebuilds the roof planes.
      const boundary = handle.kind === 'roof_edge' ? next.area.map(p => roofPoint(next, p)) : [
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
      const host = wallHost(event, g, free); if (!host) return;
      operation.host = host;
    } else if (piece.host.roof) {
      const roof = building.roofs?.find(r => r.id === piece.host.roof), edge = piece.host.edge;
      const a = roof?.area[edge], b = roof?.area[(edge + 1) % roof.area.length];
      if (!a || !b) return;
      const d = b.map((v, i) => v - a[i]), length = Math.hypot(...d);
      operation.host = { ...piece.host, at: piece.host.at + inch(point.slice(0, 2).reduce((n, v, i) => n + (v - g.start[i]) * d[i] / length, 0)) };
    } else if (piece.host.ground) {
      operation.host={ground:true,at:piece.host.at.map((v,i)=>v+point[i]-g.start[i])};
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
  async function finish(cancel = false, clicked = false, exact) {
    if (!cancel && Number.isFinite(exact) && gesture?.event && !['wall', 'joint', 'room'].includes(gesture.handle.kind))
      update(gesture.event, { free: true, typed: exact });
    const g = gesture, released = preview; gesture = null; preview = null;
    typed.hide();
    if (!g) return;
    if (g.handle.kind === 'porch_post') {
      document.getElementById('editor-drag-outline')?.setAttribute('points', '');
      const saving = !cancel && canEdit() && g.operation;
      if (saving) preview = released;
      try { if (saving) await onCommit(g.operation); }
      finally {
        if (saving && preview === released) preview = null;
        onPreview?.(plan(), getSelection()); refresh();
      }
      return;
    }
    if (g.handle.kind === 'downspout') {
      if (clicked) onClick?.(g.handle);
      try { if (!cancel && canEdit() && g.operation) await onCommit(g.operation); }
      finally { refresh(); }
      return;
    }
    if (g.handle.kind === 'stair_end') {
      document.getElementById('editor-drag-outline')?.setAttribute('points', '');
      const saving = !cancel && canEdit() && g.operation;
      if (saving) preview = released;
      try { if (saving) await onCommit(g.operation); }
      finally { if (preview === released) preview = null; onPreview?.(plan(), getSelection()); refresh(); }
      return;
    }
    if (g.handle.kind.startsWith('site_')) {
      document.getElementById('editor-drag-outline')?.setAttribute('points', '');
      const cornerClick = clicked && (g.handle.kind === 'site_insert' || g.handle.kind === 'site_vertex' && g.remove);
      const changed = g.operation && (g.operation.op === 'move_site_item' ? g.operation.by.some(v => Math.abs(v) > 1e-8)
        : Object.entries(g.operation).some(([k, v]) => !['op', 'list', 'index'].includes(k) && !sameValue(v, g.piece[k] ?? (k === 'rotation' ? 0 : undefined))));
      try { if ((!cancel || cornerClick) && changed) await onCommit(g.operation, { local: applyLocal(getPlan(), g.operation)?.plan || released }); }
      finally { refresh(); }
      return;
    }
    if (g.handle.kind.startsWith('roof_') || g.handle.kind.startsWith('dormer_') || g.handle.kind.startsWith('solar_')) {
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
      try { await drag.finish(cancel, exact); }
      finally { preview = null; refresh(); }
      return;
    }
    const restore = () => { view.rebuildLevel(g.building.id, g.handle.level, g.source, { [g.list]: [g.piece.id] }); onPreview?.(g.source, getSelection()); refresh(); };
    if (cancel || !g.operation) { restore(); return; }
    try { await onCommit(g.operation, { local: released }); }
    catch (error) { if (!error.refused && !error.dropped) restore(); throw error; }
    refresh();
  }
  view.controls.addEventListener('change', refresh);
  host.addEventListener('twinrebuilt', refresh, { signal });
  window.addEventListener('resize', refresh, { signal });
  signal.addEventListener('abort', () => { typed.hide(); view.controls.removeEventListener('change', refresh); layer.remove(); }, { once: true });
  async function removeAt(event) {
    if (!canEdit() || gesture) return false;
    const handle = hit(event); if (handle?.kind !== 'downspout') return false;
    const values = downspoutValues(getPlan(), handle.building, handle.id, handle.edge);
    const index = downspoutIndex(values, handle.fraction, handle.authoredIndex);
    if (index >= 0) values.splice(index, 1);
    await onCommit(edgeOperation(handle.building, handle.id, handle.edge, { downspouts: values }));
    refresh(); return true;
  }
  return { begin, update, finish, refresh, hit, removeAt, active: () => !!gesture,
    key: typed.key, typedValue: typed.value, commit: exact => finish(false, false, exact),
    show(value) { preview = value; refresh(); },
    handles() {
      refresh();
      // Roof edges can span more than the current camera frame. Keep their
      // model points discoverable so looking at an edge reveals its handle.
      const all = descriptors(), roof = all.filter(h => h.kind === 'roof_edge' || h.kind.startsWith('dormer_'));
      return [...rows.map(({ handle }) => handle).filter(h => h.kind !== 'roof_edge' && !h.kind.startsWith('dormer_')), ...roof]
        .map(handle => ({ kind: handle.kind, id: handle.id, at: [...handle.at],
          ...(handle.offset ? { offset: [...handle.offset] } : {}),
          ...(handle.kind === 'downspout' ? { building: handle.building, edge: handle.edge, spout: handle.spout,
            ...(Number.isInteger(handle.authoredIndex) ? { authoredIndex: handle.authoredIndex } : {}) } : {}) }));
    },
    clearDragFrame() { lastFrameMs = null; drag.clearDragFrame?.(); },
    get lastDragFrameMs() { return lastFrameMs ?? drag.lastDragFrameMs; } };
}
