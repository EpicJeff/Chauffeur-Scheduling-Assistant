import { porchFoundation } from '../twin_porch_foundation.js';
import { hostPoint } from '../twin_hosts.js';
import { sitePieces } from '../objects.js';
import { allPorches } from '../gutter_presence.js';
import { postRef, commonPostSize } from '../porch_posts.js';

const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const delta = (a, b) => a.map((v, i) => v - b[i]);
const shifted = (p, by) => p.map((v, i) => v + by[i]);
const EPS = 1e-9, MIN_CLEAR = .5;
const SHORT = 'A wall must be at least 1 ft long.';
const NARROW = 'That would leave the door narrower than its wall.';
const CROSS = 'That would cross another wall.';
const cross = (a, b) => a[0] * b[1] - a[1] * b[0];

// Same open-segment intersection and collinear overlap as twin_model_ops.
function crosses(a, b, c, d) {
  const v = delta(b, a), w = delta(d, c), between = delta(c, a), denominator = cross(v, w);
  if (Math.abs(denominator) > EPS) {
    const t = cross(between, w) / denominator, u = cross(between, v) / denominator;
    if (t > EPS && t < 1 - EPS && u > EPS && u < 1 - EPS) return true;
  }
  const length = Math.hypot(...v);
  if (length <= EPS) return false;
  const axis = v.map(n => n / length);
  if ([c, d].some(p => Math.abs(cross(axis, delta(p, a))) > EPS)) return false;
  const ends = [dot(delta(c, a), axis), dot(delta(d, a), axis)].sort((x, y) => x - y);
  return Math.min(length, ends[1]) - Math.max(0, ends[0]) > EPS;
}

function wallLines(building) {
  const positions = new Map((building.joints || []).map(j => [j.id, j.at]));
  const lines = new Map();
  for (const wall of building.walls || []) {
    if (wall.state === 'ghost' || wall.joints?.length !== 2) continue;
    const [a, b] = wall.joints.map(id => positions.get(id));
    if (a && b && Math.hypot(...delta(b, a)) > EPS) lines.set(wall.id, { ...wall, a, b });
  }
  return lines;
}

export function moveProblem(before, after, buildingId) {
  // movePreview's null sentinel means an attached wall lost its direction.
  if (after === null) return SHORT;
  const previous = before?.buildings.find(b => b.id === buildingId);
  const building = after?.buildings.find(b => b.id === buildingId);
  if (!previous || !building) return null;
  const oldLines = wallLines(previous), lines = wallLines(building), changed = [];
  for (const [id, wall] of lines) {
    const old = oldLines.get(id);
    if (old && wall.level === old.level && (wall.thickness || 0) === (old.thickness || 0)
      && wall.joints.every((j, i) => j === old.joints[i])
      && wall.a.every((v, i) => v === old.a[i]) && wall.b.every((v, i) => v === old.b[i])) continue;
    changed.push(wall);
    const length = Math.hypot(...delta(wall.b, wall.a));
    if (length < 1 - EPS) return SHORT;
    if (old && length < Math.hypot(...delta(old.b, old.a)) - EPS) {
      const widths = ['openings', 'anchors', 'items'].flatMap(name => (building[name] || [])
        .filter(p => (name === 'openings' ? p : p.host)?.wall === id).map(p => p.width || 0));
      if (widths.length && length < Math.max(...widths) + 2 * MIN_CLEAR - EPS) return NARROW;
    }
  }
  // The server snapshot omits collapsed walls and checks them separately.
  if (building.walls.some(w => w.state !== 'ghost' && oldLines.has(w.id) && !lines.has(w.id))) return SHORT;
  const levels = new Map();
  for (const wall of lines.values()) {
    if (!levels.has(wall.level)) levels.set(wall.level, []);
    levels.get(wall.level).push(wall);
  }
  // Only changed walls against their level, never every pair in the house.
  const checked = new Set();
  for (const wall of changed) {
    for (const other of levels.get(wall.level)) {
      if (other.id === wall.id || checked.has(other.id)) continue;
      if (!crosses(wall.a, wall.b, other.a, other.b)) continue;
      const old = oldLines.get(wall.id), prior = oldLines.get(other.id);
      if (!old || !prior || !crosses(old.a, old.b, prior.a, prior.b)) return CROSS;
    }
    checked.add(wall.id);
  }
  return null;
}

// Geometry and hosts that can change when these joints move. Crossings used
// by room cycles are included even when they are not persisted wall ends.
export function piecesOnMovedJoints(building, joints) {
  const moved = new Set(joints);
  const walls = building.walls.filter(w => w.joints?.some(id => moved.has(id))).map(w => w.id);
  const rooms = building.rooms.filter(r => r.joints?.some(id => moved.has(id))).map(r => r.id);
  const wallIds = new Set(walls), roomIds = new Set(rooms);
  const result = { walls, rooms };
  for (const list of ['openings', 'anchors', 'items']) result[list] = (building[list] || []).filter(piece =>
    wallIds.has(piece.wall) || wallIds.has(piece.host?.wall)
      || roomIds.has(piece.host?.floor) || roomIds.has(piece.host?.ceiling)).map(piece => piece.id);
  return result;
}

export class LocalMissing extends Error {
  constructor(message) { super(message); this.name = 'LocalMissing'; }
}

export function moveGesture(plan, selection) {
  const building = plan?.buildings?.find(b => b.id === selection.building);
  if (!building) throw new LocalMissing(`Missing building: ${selection.building}`);
  const list = { wall: 'walls', joint: 'joints', room: 'rooms' }[selection.kind];
  const piece = building?.[list]?.find(p => p.id === selection.id);
  if (!piece || piece.state === 'ghost') throw new LocalMissing(`Missing ${selection.kind}: ${selection.id}`);
  const moved = new Set(piece.joints || [piece.id]);
  let normal = null;
  if (selection.kind === 'wall') {
    const d = delta(piece.to, piece.from), length = Math.hypot(...d);
    if (length) {
      normal = [-d[1] / length, d[0] / length];
      // A room cycle may use derived T/crossing joints within this wall (R25).
      for (const joint of building.joints || []) {
        const v = delta(joint.at, piece.from), along = dot(v, d) / (length * length);
        if (joint.level === piece.level && along >= -1e-6 && along <= 1 + 1e-6
          && Math.abs(dot(v, normal)) < 1e-5) moved.add(joint.id);
      }
    }
  }
  const touched = piecesOnMovedJoints(building, moved);
  const oldWalls = new Map(building.walls.map(w => [w.id, w]));
  return { building, piece, moved, touched, oldWalls, normal };
}

export function movePreview(plan, gesture, by, follow = true) {
  const g = gesture, b = g.building;
  const preview = structuredClone(plan), building = preview.buildings.find(row => row.id === b.id);
  const positions = new Map();
  for (const joint of building.joints) {
    if (g.moved.has(joint.id)) joint.at = shifted(joint.at, by);
    positions.set(joint.id, joint.at);
  }
  const wallIds = new Set(g.touched.walls), roomIds = new Set(g.touched.rooms);
  for (const wall of building.walls) {
    if (!wallIds.has(wall.id)) continue;
    const old = g.oldWalls.get(wall.id);
    wall.from = [...positions.get(wall.joints[0])]; wall.to = [...positions.get(wall.joints[1])];
    // Transport each end's face offsets with the connected joint.
    if (wall.footprint) wall.footprint = wall.footprint.map((p, i) =>
      shifted(p, delta(i === 0 || i === 3 ? wall.from : wall.to, i === 0 || i === 3 ? old.from : old.to)));
  }
  // A collapsed wall has no direction and would deform the scene into NaN.
  if (building.walls.some(w => wallIds.has(w.id) && Math.hypot(...delta(w.to, w.from)) < 1e-6)) return null;
  for (const room of building.rooms) if (roomIds.has(room.id) && room.joints?.every(id => positions.has(id)))
    room.polygon = room.joints.map(id => [...positions.get(id)]);
  for (const l of building.levels) {
    const original = b.levels.find(row => row.id === l.id);
    if (l.footprint?.every(id => positions.has(id))) l.outline = l.footprint.map(id => [...positions.get(id)]);
    else if (l.outline) l.outline = original.outline.map(p => {
      const joint = b.joints.find(j => j.level === l.id && g.moved.has(j.id) && Math.hypot(...delta(p, j.at)) < .01);
      return joint ? [...positions.get(joint.id)] : [...p];
    });
  }
  for (const list of ['openings', 'anchors', 'items']) for (const piece of building[list] || []) {
    if (!piece.host || !g.touched[list].includes(piece.id)) continue;
    try { piece.position = hostPoint(building, piece.host, piece.offset || 0); }
    catch { /* Missing hosts retain their existing ghost representation. */ }
  }
  if (follow) followLocalPosts(plan, preview);
  return preview;
}

function weldMove(plan, buildingId, moved) {
  const b = plan.buildings.find(b => b.id === buildingId), replacements = new Map();
  for (const joint of b.joints.filter(j => moved.has(j.id))) {
    const neighbours = new Set(b.walls.filter(w => w.joints.includes(joint.id)).flatMap(w => w.joints));
    const target = b.joints.filter(j => j.level === joint.level && !moved.has(j.id) && !neighbours.has(j.id)
      && Math.hypot(...delta(j.at, joint.at)) < 1).sort((a, c) => Math.hypot(...delta(a.at, joint.at)) - Math.hypot(...delta(c.at, joint.at)))[0];
    if (target) replacements.set(joint.id, target.id);
  }
  if (!replacements.size) return;
  for (const piece of [...b.walls, ...b.rooms]) piece.joints = piece.joints?.map(id => replacements.get(id) || id);
  b.joints = b.joints.filter(j => !replacements.has(j.id));
  const positions = new Map(b.joints.map(j => [j.id, j.at]));
  for (const wall of b.walls) {
    const [from, to] = wall.joints.map(id => positions.get(id));
    if (wall.footprint) wall.footprint = wall.footprint.map((p, i) => shifted(p,
      delta(i === 0 || i === 3 ? from : to, i === 0 || i === 3 ? wall.from : wall.to)));
    wall.from = [...from]; wall.to = [...to];
  }
  for (const room of b.rooms) if (room.joints?.every(id => positions.has(id))) room.polygon = room.joints.map(id => [...positions.get(id)]);
  for (const level of b.levels) if (level.footprint) {
    level.footprint = level.footprint.map(id => replacements.get(id) || id);
    if (level.footprint.every(id => positions.has(id))) level.outline = level.footprint.map(id => [...positions.get(id)]);
  }
  for (const piece of [...(b.items || []), ...(b.anchors || [])]) if (piece.host) {
    try { piece.position = hostPoint(b, piece.host, piece.offset || 0); } catch { /* Server judges missing hosts. */ }
  }
}

function splitWall(plan, operation) {
  const preview = structuredClone(plan), b = preview.buildings.find(b => b.id === operation.building);
  const wall = b?.walls.find(w => w.id === operation.wall && w.state !== 'ghost');
  if (!wall) throw new LocalMissing(`Missing wall: ${operation.wall}`);
  const [a, z] = wall.joints.map(id => b.joints.find(j => j.id === id).at), length = Math.hypot(...delta(z, a)), at = operation.at;
  if (!Number.isFinite(at) || at < 1 - EPS || length - at < 1 - EPS) return null;
  // The graph keeps a wall whole at a T inside an opening's span (R55).
  if (b.openings?.some(o => o.wall === wall.id && Math.abs(o.at - at) < o.width / 2 - EPS)) return null;
  const point = a.map((v, i) => v + (z[i] - v) * at / length);
  let joint = b.joints.find(j => j.level === wall.level && Math.hypot(...delta(j.at, point)) < EPS);
  if (!joint) { joint = { id: `local:split:${wall.id}:${at}`, level: wall.level, at: point }; b.joints.push(joint); }
  let suffix = 2; while (b.walls.some(w => w.id === `${wall.id}~${suffix}`)) ++suffix;
  const second = structuredClone(wall), end = wall.joints[1]; second.id = `${wall.id}~${suffix}`;
  wall.joints[1] = joint.id; wall.to = [...point]; second.joints = [joint.id, end]; second.from = [...point]; second.to = [...z];
  if (wall.footprint) {
    const [p, q, r, s] = wall.footprint, half = (wall.thickness ?? .5) / 2;
    const normal = [-(z[1] - a[1]) / length, (z[0] - a[0]) / length];
    const left = shifted(point, normal.map(v => v * half)), right = shifted(point, normal.map(v => -v * half));
    wall.footprint = [p, left, right, s]; second.footprint = [left, q, r, right];
  }
  b.walls.splice(b.walls.indexOf(wall) + 1, 0, second);
  for (const room of b.rooms) if (room.joints) {
    const ids = room.joints; room.joints = ids.flatMap((id, i) =>
      [wall.joints[0], end].includes(id) && [wall.joints[0], end].includes(ids[(i + 1) % ids.length]) ? [id, joint.id] : [id]);
    room.polygon = room.joints.map(id => [...b.joints.find(j => j.id === id).at]);
  }
  for (const name of ['openings', 'items', 'anchors', 'devices']) for (const piece of b[name] || []) {
    const host = name === 'openings' ? piece : piece.host;
    if (host?.wall === wall.id && host.at > at) { host.wall = second.id; host.at -= at; }
  }
  return { plan: preview, building: b.id, level: wall.level, touched: { walls: [wall.id, second.id], rooms: b.rooms.map(r => r.id),
    openings: (b.openings || []).map(p => p.id), items: (b.items || []).map(p => p.id), anchors: (b.anchors || []).map(p => p.id) } };
}

export function applyLocal(plan, operation) {
  if (operation.op !== 'batch') {
    const result = applyOne(plan, operation);
    if (result && FOLLOW_OPS.includes(operation.op)) followLocalPosts(plan, result.plan);
    return result;
  }
  // A batch owns one private copy, so 200 plants never clone the whole house
  // 200 times. An unsupported/refused member discards the entire preview.
  let result = { plan: structuredClone(plan), building: null, level: null, touched: null };
  const members = structuredClone(operation.ops);
  for (const member of members) if (['add_porch_post', 'update_porch_post', 'delete_porch_post'].includes(member.op)) {
    const b = result.plan.buildings.find(b => b.id === member.building), porch = b && allPorches(b).find(p => p.id === member.porch);
    if (porch && !mintColumns(b,porch)) return null;
  }
  for (const member of members) {
    const before = FOLLOW_OPS.includes(member.op) ? structuredClone(result.plan) : null;
    const next = applyOne(result.plan, member, true);
    if (!next) return null;
    if (before) followLocalPosts(before, next.plan);
    result = { ...next, building: null, level: null, touched: null };
  }
  return result;
}

function postIds(building, derived = true) {
  const ids = new Set();
  const collect = value => { if (Array.isArray(value)) value.forEach(collect); else if (value && typeof value === 'object') {
    if (typeof value.id === 'string') ids.add(value.id); Object.values(value).forEach(collect);
  } }; collect(building);
  if (derived) for (const p of allPorches(building)) for (const [i,c] of (p.columns || []).entries()) ids.add(postRef(p,i));
  return ids;
}
function mintColumns(building, porch) {
  const used=postIds(building,false),pending=[];
  for(const [i,c] of (porch.columns||[]).entries())if(!c.id){
    const ref=`post:${porch.id}:${i}`;if(used.has(ref))return false;
    used.add(ref);pending.push([c,ref]);
  }
  for(const [c,ref] of pending)c.id=ref;
  return true;
}
const FOLLOW_OPS = ['move_joint', 'move_joints', 'move_wall', 'move_room'];
function mintPostId(detail) {
  const ids = new Set((detail.columns || []).map(c => c.id));
  let n = (detail.columns || []).length;
  while (ids.has(`post:${detail.id}:${n}`)) ++n;
  return `post:${detail.id}:${n}`;
}
function projectPost(p,a,b) {
  const d=delta(b,a),length2=dot(d,d),t=length2?Math.max(0,Math.min(1,dot(delta(p,a),d)/length2)):0;
  const q=shifted(a,d.map(v=>v*t));return {distance:Math.hypot(...delta(p,q)),t,q};
}
function followLocalPosts(before, after) {
  for(const b of after.buildings||[]) {
    const old=before.buildings?.find(v=>v.id===b.id);if(!old)continue;
    for(const room of b.rooms||[]) {
      const prior=old.rooms?.find(r=>r.id===room.id&&r.kind==='porch');
      if(!prior||room.kind!=='porch')continue;
      const c=room.polygon;
      const oldPositions=new Map(old.joints.map(j=>[j.id,j.at]));
      const cycle=(prior.joints||[]).map(id=>oldPositions.get(id));
      const a=cycle.length>=3&&cycle.every(Boolean)?cycle:prior.polygon;
      if([[a,c],[c,a]].every(([points,q])=>points.every(p=>Math.min(...q.map((v,i)=>projectPost(p,v,q[(i+1)%q.length]).distance))<=.01)))continue;
      const detail=allPorches(b).find(p=>p.id===room.id);
      if(!detail)continue;
      const cycles=c.map((_,i)=>[...c.slice(i),...c.slice(0,i)]);
      const fallback=a.length===c.length?[...cycles,...cycles.map(p=>[...p].reverse())].map(p=>({p,score:p.reduce((s,q,i)=>s+dot(delta(q,a[i]),delta(q,a[i])),0)})).sort((x,y)=>x.score-y.score)[0].p:
        a.map(p=>c.map((q,i)=>projectPost(p,q,c[(i+1)%c.length])).sort((x,y)=>x.distance-y.distance)[0].q);
      const positions=new Map(b.joints.map(j=>[j.id,j.at]));
      const targets=a.map((p,i)=>{const joint=old.joints.find(j=>prior.joints?.includes(j.id)&&Math.hypot(...delta(p,j.at))<=.01);return joint&&positions.get(joint.id)||fallback[i];});
      const vectors=targets.map((p,i)=>delta(p,a[i])),translation=vectors.every(v=>Math.hypot(...delta(v,vectors[0]))<=1e-8);
      let moved=false;
      for(const column of detail.columns||[]) {
        const point=column.at;let by;
        if(translation)by=vectors[0];
        else {
          const corner=a.map((p,i)=>({i,d:Math.hypot(...delta(point,p))})).sort((x,y)=>x.d-y.d||x.i-y.i)[0];
          if(corner.d<=1+column.size/2)by=vectors[corner.i];
          else {
            const {distance,t,edge}=a.map((p,i)=>({...projectPost(point,p,a[(i+1)%a.length]),edge:i})).sort((x,y)=>x.distance-y.distance||x.edge-y.edge)[0];
            if(distance>4)continue;
            const end=(edge+1)%a.length,d=delta(a[end],a[edge]),length=Math.hypot(...d),normal=length?[-d[1]/length,d[0]/length]:[0,0];
            const displacement=[0,1].map(i=>(1-t)*vectors[edge][i]+t*vectors[end][i]);
            by=normal.map(v=>v*dot(displacement,normal));
          }
        }
        if(Math.hypot(...by)>.01){column.at=shifted(point,by);moved=true;}
      }
      if(!moved)continue;
      detail.read_geometry ||= {polygon:structuredClone(detail.polygon||a)};
      detail.polygon=structuredClone(c);(detail.src||={}).person=true;
      const stored=b.porches_detail?.find(p=>p.id===detail.id);
      if(stored)for(const key of ['columns','polygon','read_geometry','src'])stored[key]=structuredClone(detail[key]);
    }
  }
}

function applyOne(plan, operation, mutable = false) {
  const copy = () => mutable ? plan : structuredClone(plan);
  if (['add_porch_post', 'update_porch_post', 'delete_porch_post'].includes(operation.op)) {
    const preview = copy(), building = preview.buildings.find(b => b.id === operation.building);
    const porch = building && allPorches(building).find(p => p.id === operation.porch);
    const room = building?.rooms?.find(r => r.id === operation.porch && r.kind === 'porch');
    if (!building || !porch && !room) throw new LocalMissing('That porch is missing.');
    if ([porch, room].some(p => ['ghost', 'proposal'].includes(p?.state))) return null;
    const detail = porch || { id: room.id, polygon: structuredClone(room.polygon), level: room.level,
      floor: building.levels.find(l => l.id === room.level).elevation, columns: [] };
    const columns = detail.columns || [], adding = operation.op === 'add_porch_post';
    const index = columns.findIndex((c, i) => postRef(detail, i) === operation.post);
    if (!adding && index < 0) throw new LocalMissing('That post is missing.');
    if (operation.op === 'update_porch_post' && !('at' in operation || 'size' in operation)) return null;
    if ('at' in operation && (!Array.isArray(operation.at) || operation.at.length !== 2 || !operation.at.every(v => Number.isFinite(v) && Math.abs(v) <= 1e5))) return null;
    if ('size' in operation && (!Number.isFinite(operation.size) || operation.size < .05 || operation.size > 3)) return null;
    const ids = postIds(building);
    if (adding && (columns.length >= 40 || 'id' in operation &&
      (typeof operation.id !== 'string' || !operation.id.startsWith('post:') || [...operation.id].length > 120 || ids.has(operation.id)))) return null;
    if ('id' in operation) ids.add(operation.id);
    const mint = () => mintPostId(detail);
    let at, size;
    if (adding) {
      size = 'size' in operation ? operation.size : commonPostSize(detail);
      if (!Number.isFinite(size) || size < .05 || size > 3) return null;
      at = 'at' in operation ? [...operation.at] : defaultPostAt(building, detail, size);
      if (!at) return null;
    }
    if (!mintColumns(building,detail)) return null;
    detail.columns = columns;
    if (adding) { const id = 'id' in operation ? operation.id : mint(); if (!('id' in operation) && ids.has(id)) return null; columns.push({ id, at, size }); }
    else if (operation.op === 'delete_porch_post') columns.splice(index, 1);
    else for (const key of ['at', 'size']) if (key in operation) columns[index][key] = structuredClone(operation[key]);
    detail.columns = columns; (detail.src ||= {}).person = true;
    if (!porch) (building.porches ||= []).push(detail);
    // The flat bridge also retains connected details. Keep that source copy
    // in sync without copying renderer-derived foundation fields into it.
    if (building.porches_detail) {
      let stored = building.porches_detail.find(p => p.id === detail.id);
      if (!stored) {
        stored = { id: detail.id, level: detail.level || room?.level, polygon: structuredClone(detail.polygon), floor: detail.floor, columns: [] };
        building.porches_detail.push(stored);
      }
      stored.columns = structuredClone(columns); (stored.src ||= {}).person = true;
    }
    return { plan: preview, building: building.id, level: detail.level || room?.level, touched: null };
  }
  if (operation.op === 'set_room_kind' && operation.kind === 'porch') {
    const preview=copy(),b=preview.buildings.find(b=>b.id===operation.building),room=b?.rooms.find(r=>r.id===operation.room);
    if(!room)throw new LocalMissing('That room is missing.');
    room.kind='porch';room.foundation ||= porchFoundation();
    if(!allPorches(b).some(p=>p.id===room.id)) {
      const detail={id:room.id,name:room.name,level:room.level,polygon:structuredClone(room.polygon),floor:b.levels.find(l=>l.id===room.level).elevation,
        state:room.state||'settled',screened:false,columns:room.polygon.map(p=>({at:[...p],size:.5,shape:'square'}))};
      (b.porches||=[]).push(detail);(b.porches_detail||=[]).push(structuredClone(detail));
    }
    return {plan:preview,building:b.id,level:room.level,touched:null};
  }
  if (operation.op === 'move_joints') {
    const preview = copy(), b = preview.buildings.find(b => b.id === operation.building);
    if (!b) throw new LocalMissing(`Missing building: ${operation.building}`);
    for (const { joint, to } of operation.joints) {
      const p = b.joints.find(p => p.id === joint);
      if (!p) throw new LocalMissing(`Missing joint: ${joint}`);
      p.at = [...to];
    }
    // Rebuild the flat geometry once, carrying each shared joint only once.
    const positions = new Map(b.joints.map(j => [j.id, j.at]));
    for (const wall of b.walls) {
      const [from, to] = wall.joints.map(id => positions.get(id));
      if (wall.footprint) wall.footprint = wall.footprint.map((p, i) => shifted(p,
        delta(i === 0 || i === 3 ? from : to, i === 0 || i === 3 ? wall.from : wall.to)));
      wall.from = [...from]; wall.to = [...to];
    }
    for (const room of b.rooms) if (room.joints?.every(id => positions.has(id))) room.polygon = room.joints.map(id => [...positions.get(id)]);
    for (const level of b.levels) if (level.footprint?.every(id => positions.has(id))) level.outline = level.footprint.map(id => [...positions.get(id)]);
    for (const p of [...(b.items || []), ...(b.anchors || [])]) if (p.host) {
      try { p.position = hostPoint(b, p.host, p.offset || 0); } catch { /* The server judges it. */ }
    }
    return { plan: preview, building: b.id, level: null, touched: null };
  }
  if (operation.op === 'update_pad' || operation.op === 'update_pool_feature') {
    const preview = copy(), pieces = operation.op === 'update_pad' ? preview.site.terraces : preview.site.pool?.features;
    const p = pieces?.find(p => p.id === operation.id);
    if (!p) throw new LocalMissing(`Missing piece: ${operation.id}`);
    for (const [k, v] of Object.entries(operation)) if (!['op', 'id'].includes(k)) p[k] = structuredClone(v);
    return { plan: preview, building: null, level: null, touched: null };
  }
  if (operation.op === 'resize_opening' || operation.op === 'move_hosted' && !operation.host) {
    const preview = copy(), b = preview.buildings.find(b => b.id === operation.building), p = b?.openings?.find(p => p.id === operation.id);
    if (!p) throw new LocalMissing(`Missing opening: ${operation.id}`);
    for (const k of ['at', 'width', 'sill', 'head']) if (k in operation) p[k] = operation[k];
    return { plan: preview, building: b.id, level: b.walls.find(w => w.id === p.wall)?.level, touched: { openings: [p.id] } };
  }
  if (operation.op === 'split_wall') return splitWall(plan, operation);
  if (operation.op === 'set_object' || operation.op === 'move_hosted') {
    // Opening slides use {at}, not a replacement object host.
    if (operation.op === 'move_hosted' && !operation.host) return null;
    const properties = operation.op === 'move_hosted' ? { host: operation.host } : operation.properties;
    if (!properties || Object.keys(properties).some(k => !['rotation', 'scale', 'scale_axes', 'mirror_x', 'mirror_y', 'host'].includes(k))) return null;
    const preview = copy(), building = preview.buildings.find(b => b.id === operation.building);
    const list = building && ['items', 'anchors', 'openings'].find(name => building[name]?.some(p => p.id === operation.id));
    const site = !operation.building && sitePieces(preview.site?.[operation.list]);
    const piece = list ? building[list].find(p => p.id === operation.id) : site && (operation.id ? site.find(p => p.id === operation.id) : site[operation.index]);
    if (!piece || piece.device) throw new LocalMissing(`Missing object: ${operation.id || operation.list}`);
    Object.assign(piece, structuredClone(properties));
    for (const key of ['mirror_x', 'mirror_y']) if (properties[key] === false) delete piece[key];
    if (piece.host && building) {
      try { piece.position = hostPoint(building, piece.host, piece.offset || 0); } catch { /* Server judges missing hosts. */ }
    }
    return { plan: preview, building: building?.id || null, level: building?.walls.find(w => w.id === (piece.wall || piece.host?.wall))?.level
      || building?.rooms.find(r => r.id === (piece.host?.floor || piece.host?.ceiling))?.level || building?.levels[0]?.id || null,
      touched: list ? { [list]: [piece.id] } : { site: [operation.list] } };
  }
  if (operation.op === 'update_site_shape') {
    if (Object.keys(operation).some(k => !['op', 'list', 'index', 'id', 'polygon', 'points', 'polyline', 'at', 'radius', 'width', 'rotation', 'features'].includes(k))) return null;
    const preview = copy();
    const pieces = sitePieces(preview.site?.[operation.list]);
    const index = operation.id ? pieces.findIndex(p => p.id === operation.id) : operation.index ?? 0, piece = pieces[index];
    if (!piece) throw new LocalMissing(`Missing site shape: ${operation.id || operation.list}`);
    for (const [key, value] of Object.entries(operation)) if (!['op', 'list', 'index', 'id'].includes(key)) piece[key] = structuredClone(value);
    return { plan: preview, building: null, level: null, touched: { site: [operation.list] } };
  }
  if (['update_light_fixture', 'update_effect_fixture'].includes(operation.op)) {
    if (Object.keys(operation.change).some(k => !['at', 'aim', 'rotation_deg', 'path', 'snap', 'anchors', 'facing'].includes(k))) return null;
    const preview = copy(), piece = (operation.op === 'update_effect_fixture' ? preview.effect_fixtures : preview.light_fixtures?.[operation.entity_id])?.find(f => f.id === operation.id);
    if (!piece) throw new LocalMissing(`Missing light fixture: ${operation.id}`);
    Object.assign(piece, structuredClone(operation.change));
    for (const k of ['snap', 'anchors']) if (piece[k] === null) delete piece[k];
    return { plan: preview, building: null, level: null, touched: { light_fixtures: [operation.id] } };
  }
  const kind = operation.op === 'move_wall' ? 'wall' : operation.op === 'move_joint' ? 'joint'
    : operation.op === 'move_room' ? 'room' : null;
  if (kind) {
    const gesture = moveGesture(plan, { kind, building: operation.building, id: operation[kind] });
    if (kind === 'wall' && !gesture.normal) return null;
    const by = kind === 'joint' ? delta(operation.to, gesture.piece.at)
      : kind === 'wall' && typeof operation.by === 'number' ? gesture.normal.map(v => v * operation.by) : operation.by;
    const preview = movePreview(plan, gesture, by, false);
    if (preview) weldMove(preview, gesture.building.id, gesture.moved);
    return preview && { plan: preview, building: gesture.building.id, level: gesture.piece.level, touched: gesture.touched };
  }
  if (operation.op !== 'move_site_item') return null;
  const name = operation.list, value = plan.site?.[name];
  const singleton = ['pool', 'fire_pit', 'fence'].includes(name) && !Array.isArray(value);
  const pieces = singleton ? value ? [value] : [] : value || [];
  const index = operation.id ? pieces.findIndex(p => p.id === operation.id) : operation.index ?? (singleton ? 0 : null);
  if (!Number.isInteger(index) || index < 0 || index >= pieces.length) throw new LocalMissing(`Missing site item: ${name}`);
  if (!('by' in operation) && !('at' in pieces[index])) return null;
  const preview = copy(), piece = singleton ? preview.site[name] : preview.site[name][index];
  if ('by' in operation) {
    // As the server does: plan x and y only.
    const by = p => [p[0] + operation.by[0], p[1] + operation.by[1]];
    for (const key of ['at', 'polygon', 'points', 'polyline']) {
      if (!(key in piece)) continue;
      piece[key] = key === 'at' ? by(piece[key]) : piece[key].map(by);
    }
    if (name === 'pool') for (const feature of piece.features || [])
      feature.polygon = feature.polygon.map(by);
  } else piece.at = [operation.at[0], operation.at[1]];
  return { plan: preview, building: null, level: null, touched: { site: [name] } };
}

function defaultPostAt(building, porch, size) {
  const room = building.rooms?.find(r=>r.id===porch.id);
  const polygon = (room || porch).polygon, joints = new Map((building.joints || []).map(j => [j.id, j.at]));
  const walls = (building.walls || []).filter(w => w.kind !== 'separator' && w.state !== 'ghost' && w.level === (room?.level || porch.level || building.levels[0].id))
    .map(w => [joints.get(w.joints?.[0]) || w.from, joints.get(w.joints?.[1]) || w.to]).filter(w => w.every(Boolean));
  const project = (p, a, b) => { const d = delta(b, a), length2 = dot(d, d), t = length2 ? Math.max(0, Math.min(1, dot(delta(p, a), d) / length2)) : 0;
    return [Math.hypot(...delta(p, shifted(a, d.map(v => v * t)))), t]; };
  const winding = polygon.reduce((s, a, i) => s + cross(a, polygon[(i + 1) % polygon.length]), 0) > 0 ? 1 : -1;
  let best = null;
  for (const [i, a] of polygon.entries()) {
    const b = polygon[(i + 1) % polygon.length], d = delta(b, a), length = Math.hypot(...d);
    if (!length) continue;
    let spans = [[0, 1]];
    for (const [c,e] of walls) {
      if ([c,e].some(p => Math.abs(cross(delta(p,a),d))/length >= .05)) continue;
      const [lo,hi]=[c,e].map(p=>Math.max(0,Math.min(1,dot(delta(p,a),d)/(length*length)))).sort((a,b)=>a-b);
      spans=spans.flatMap(([start,end])=>[[start,Math.min(end,lo)],[Math.max(start,hi),end]].filter(([s,e])=>e-s>1e-9));
    }
    const gaps=[];
    for (const [start,end] of spans) {
      const cuts=[start,end];
      for (const c of porch.columns || []) { const [distance,t]=project(c.at,a,b);if(distance<=c.size/2+.1&&t>start&&t<end)cuts.push(t); }
      cuts.sort((a,b)=>a-b);for(let j=1;j<cuts.length;j++)gaps.push([cuts[j-1],cuts[j]]);
    }
    for (const [lo,hi] of gaps) {
      const gap = (hi-lo) * length, t = (hi+lo) / 2;
      if (!best || gap > best.gap) best = { gap, at: [a[0] + t * d[0] - winding * d[1] / length * size / 2,
        a[1] + t * d[1] + winding * d[0] / length * size / 2] };
    }
  }
  return best?.at || null;
}
