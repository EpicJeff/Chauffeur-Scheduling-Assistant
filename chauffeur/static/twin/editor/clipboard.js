import { Vector3 } from 'three';
import { groupRecord, deleteOperations } from './group_transform.js';
import { findPiece } from './piece_operations.js';
import { hostPoint } from '../twin_hosts.js';
import { groundAt, buildingGround, inPolygon, segmentIntersection, edgeDistance } from '../twin_ground.js';
import { contains } from '../twin_generator.js';
import { sitePoints } from '../objects.js';
import { shapeCentre } from './site_shapes.js';
import { pieceMaterialSlots, sharedMaterialRows } from './selection_materials.js';
import { SNAP } from './snap.js';
import { fixtureReference } from '../live/emitters.js';
import { wallFace } from './library.js';
import { planes } from '../twin_roof.js';
import { openingFloor } from '../twin_floors.js';
import { pointAnchor } from './point_snap.js';
import { pathSurfacePolygons } from '../path_shapes.js';

const clone = value => structuredClone(value);
const key = r => JSON.stringify([r.buildingId ?? null, r.pieceId]);
const idOf = r => r?.pieceId ?? r?.piece?.id ?? r?.id;
const bidOf = r => r?.buildingId ?? (typeof r?.building === 'string' ? r.building : r?.building?.id);
const refOf = r => ({ kind: r.kind, pieceId: idOf(r), ...(bidOf(r) ? { buildingId: bidOf(r) } : {}) });
const shapes = ['terraces', 'hardscape', 'beds', 'edges', 'fence', 'fire_pit'];
const free = ['planting', 'furniture', ...shapes];
const rotate = (p, degrees) => {
  const a = degrees * Math.PI / 180;
  return [p[0] * Math.cos(a) - p[1] * Math.sin(a), p[0] * Math.sin(a) + p[1] * Math.cos(a), ...p.slice(2)];
};
const world = (b, p) => rotate(p, b?.rotation || 0).map((v, i) => v + (b?.position?.[i] || 0));
const local = (b, p) => rotate(p.map((v, i) => v - (b?.position?.[i] || 0)), -(b?.rotation || 0));
const centre = points => [0, 1].map(i => (Math.min(...points.map(p => p[i])) + Math.max(...points.map(p => p[i]))) / 2);
const fields = (p, names) => Object.fromEntries(names.filter(k => p[k] !== undefined).map(k => [k, clone(p[k])]));
const without = (p, names) => Object.fromEntries(Object.entries(p).filter(([k]) => !names.includes(k)));
function freshId(kind) {
  // Home Assistant may be opened over LAN HTTP, where randomUUID is absent.
  let uuid = globalThis.crypto.randomUUID?.();
  if (!uuid) {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = bytes[6] & 15 | 64; bytes[8] = bytes[8] & 63 | 128;
    const hex = [...bytes].map(v => v.toString(16).padStart(2, '0')).join('');
    uuid = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return `${kind}:${uuid}`;
}
const surfaceKinds = ['wall', 'room', 'porch', 'floor', 'roof', 'terraces', 'hardscape', 'beds', 'ground', 'pool', 'spa', 'ledge', 'steps', 'stair', 'item', 'fixture', 'anchor'];
const footprintCentre = p => p.rect ? centre([p.rect.slice(0, 2), p.rect.slice(2)])
  : p.area ? centre(p.area) : shapeCentre(p);

function inLot(lot, points) {
  if (points.some(p => !inPolygon(lot, ...p))) return false;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i], intersections = [a, b];
    for (let j = 0; j < lot.length; j++) {
      const c = lot[j], d = lot[(j + 1) % lot.length], hit = segmentIntersection(a, b, c, d);
      if (hit) intersections.push(hit);
      if (edgeDistance(c, a, b) < 1e-8) intersections.push(c);
    }
    const axis = Math.abs(b[0] - a[0]) > Math.abs(b[1] - a[1]) ? 0 : 1;
    intersections.sort((p, q) => p[axis] - q[axis]);
    for (let j = 1; j < intersections.length; j++) if (!inPolygon(lot,
      (intersections[j - 1][0] + intersections[j][0]) / 2, (intersections[j - 1][1] + intersections[j][1]) / 2)) return false;
  }
  return true;
}

function record(plan, ref) {
  return groupRecord(plan, ref) || findPiece(plan, ref.pieceId, ref.buildingId);
}
function resolvedHost(b, host) {
  if (!host?.opening) return host;
  const opening = b.openings.find(o => o.id === host.opening), wall = b.walls.find(w => w.id === opening?.wall);
  if (!wall) throw new Error('The original device’s door or window is gone. Choose a surface first.');
  const inside = wallFace(b, wall, 'left').room ? 'left' : 'right';
  return { wall: wall.id, at: opening.at, z: opening.kind === 'window' ? opening.sill + 1 : 3.5,
    side: host.side === 'in' ? inside : inside === 'left' ? 'right' : 'left' };
}
function pointsOf(r, plan) {
  if (r.kind === 'opening') {
    const w = r.building.walls.find(w => w.id === r.piece.wall);
    if (!w && r.piece.gable) {
      const section = r.building.roof?.sections?.find(s => s.id === r.piece.section);
      if (section?.rect) {
        const axis = section.ridge === 'x' ? 0 : 1, point = [];
        point[axis] = section.rect[axis + (r.piece.gable === 'front' ? 0 : 2)];
        point[1 - axis] = r.piece[axis === 0 ? 'y' : 'x'];
        if (point.every(Number.isFinite)) return [world(r.building, point)];
      }
    }
    if (!w) throw new Error('The original opening’s wall is gone. A window needs a wall.');
    const d = w.to.map((v, i) => v - w.from[i]), length = Math.hypot(...d);
    return [world(r.building, w.from.map((v, i) => v + d[i] * r.piece.at / length))];
  }
  if (r.building) return [world(r.building, hostPoint(r.building, resolvedHost(r.building, r.piece.host), r.piece.offset || 0))];
  if (r.kind === 'device') {
    const room = plan?.site?.yard_rooms?.find(p => p.id === r.piece.host?.yard_room), h = r.piece.host;
    if (!room) throw new Error('The original yard device’s room is gone. Choose a surface first.');
    const lo = [0, 1].map(i => Math.min(...room.polygon.map(p => p[i]))), hi = [0, 1].map(i => Math.max(...room.polygon.map(p => p[i])));
    return [[lo[0] + (hi[0] - lo[0]) * h.u, lo[1] + (hi[1] - lo[1]) * h.v]];
  }
  return r.fixture ? r.piece.path || [r.piece.at] : sitePoints(r.piece);
}
function translated(p, by) {
  const next = clone(p);
  for (const k of ['at', 'aim']) if (Array.isArray(next[k])) next[k] = next[k].map((v, i) => v + (by[i] || 0));
  for (const k of ['polygon', 'points', 'polyline', 'path']) if (next[k]) next[k] = next[k].map(p => p.map((v, i) => v + (by[i] || 0)));
  return next;
}

function hostedAt(b, host, at) {
  if (host.ground) return { ...host, at: at.slice(0, 2) };
  if (host.wall || host.roof) {
    const w = b.walls.find(w => w.id === host.wall), roof = b.roofs?.find(r => r.id === host.roof);
    const a = w?.from || roof?.area?.[host.edge], z = w?.to || roof?.area?.[(host.edge + 1) % roof.area.length];
    if (!a || !z) throw new Error('The original host is gone. Choose a surface first.');
    const d = z.map((v, i) => v - a[i]), n = Math.hypot(...d);
    return { ...host, at: d.reduce((sum, v, i) => sum + v * (at[i] - a[i]) / n, 0) };
  }
  const room = b.rooms.find(r => r.id === (host.floor || host.ceiling));
  if (!room || !contains(room.polygon, at)) throw new Error('The copied piece does not fit on that floor.');
  const lo = [0, 1].map(i => Math.min(...room.polygon.map(p => p[i]))), hi = [0, 1].map(i => Math.max(...room.polygon.map(p => p[i])));
  return { ...host, u: (at[0] - lo[0]) / (hi[0] - lo[0]), v: (at[1] - lo[1]) / (hi[1] - lo[1]) };
}

// No persistence: one instance belongs to the mounted editor, across its floors
// and dock tabs. A page reload (or another browser tab) gets an empty instance.
export function createClipboard({ getPlan = () => null, getModel = () => null, getKit = () => ({}), selection,
  applyBatch, canEdit = () => true, setStatus = () => {}, view, visibility, onChange = () => {} } = {}) {
  let buffer = null, material = null, busy = false, lastPaste = null;
  const sameRefs = (a, b) => a.length === b.length && a.every(r => b.some(s => key(r) === key(s)));
  const followsPaste = refs => lastPaste && (!refs.length || sameRefs(refs, lastPaste.refs));
  const say = reason => { setStatus(reason); return { ok: false, reason }; };
  const contents = () => buffer && clone(buffer);
  function capture(refs) {
    if (!refs?.length) throw new Error('Select pieces to copy.');
    const plan = getPlan();
    const visibilityState = visibility?.snapshot?.();
    const entries = refs.map(ref => {
      const r = record(plan, ref);
      if (!r || ![...free, 'opening', 'item', 'anchor', 'device', 'light_fixture', 'effect_fixture', 'spa', 'ledge', 'steps'].includes(r.kind))
        throw new Error('Structure cannot be copied as objects. Use Copy material to copy its look.');
      const raw = record(getModel() || plan, ref)?.piece || r.piece;
      // The shown plan can include an edit still travelling through the queue.
      // Copy what the person sees, retaining canonical-only record fields.
      const piece = { ...clone(raw), ...clone(r.piece) };
      // A generated opening can inherit a different look on another building.
      // Remember its receiving parts for a cross-building paste. Imported models carry their own
      // materials; only their authored overrides travel alongside the model.
      const inheritedMaterials = r.kind === 'opening' && !piece.model ? Object.fromEntries(
        pieceMaterialSlots(plan, ref, getKit()).filter(s => s.resolved && Object.keys(s.resolved).length).map(s => [s.key, clone(s.resolved)])) : null;
      const points = pointsOf(r, plan);
      const heights = r.fixture ? points.map(p => p[2] + fixtureReference(plan, r.piece, p) + (r.piece.offset_ft || 0)) : [];
      const height = heights.length ? (Math.min(...heights) + Math.max(...heights)) / 2 : null;
      const at = centre(points);
      const baseHeight = free.includes(r.kind) ? (r.kind === 'terraces' ? piece.height : groundAt(plan, ...at) + (piece.elevation || 0))
        : r.kind === 'item' ? (points[0][2] || 0) + (r.building.base || 0) + buildingGround(plan, r.building) + (piece.elevation || 0) : null;
      return { ref: refOf(ref), kind: r.kind, piece, inheritedMaterials, points, at, height, baseHeight,
        building: r.building?.id, buildingRotation: r.building?.rotation || 0, pool: r.pool ? plan.site?.pool?.id : null,
        entity_id: r.entity_id, hidden: visibilityState ? visibilityState.hidden.includes(idOf(ref)) : !!visibility?.isHidden(idOf(ref), ref.kind),
        locked: visibilityState ? visibilityState.locked.includes(idOf(ref)) : !!visibility?.isLocked(idOf(ref), ref.kind) };
    });
    // Placement follows record geometry even before the queued redraw lands.
    const origin = centre(entries.flatMap(e => e.points));
    const heights = entries.filter(e => e.height !== null).map(e => e.height);
    const bases = entries.filter(e => e.baseHeight !== null).map(e => e.baseHeight);
    return { entries: entries.map(e => ({ ...e, relative: e.at.map((v, i) => v - origin[i]) })), centre: origin,
      fixtureHeight: bases.length ? Math.min(...bases) : heights.length ? (Math.min(...heights) + Math.max(...heights)) / 2 : 0,
      cut: false, firstPaste: false };
  }
  function copy(refs = selection?.members()) {
    if (busy) return say('Wait for the clipboard change to finish.');
    try {
      buffer = capture(refs); lastPaste = null; onChange();
      const binding = buffer.entries.some(e => e.kind === 'device' || e.kind === 'anchor' && e.piece.device);
      setStatus(binding ? 'Copied without the device binding. Light and effect fixture bindings are kept.' : `Copied ${refs.length} piece${refs.length === 1 ? '' : 's'}.`);
      return { ok: true };
    } catch (error) { return say(error.message); }
  }
  async function cut(refs = selection?.members()) {
    if (busy || !canEdit()) return say('The editor is not ready to cut.');
    let next;
    try {
      next = capture(refs); busy = true; onChange();
      await applyBatch(deleteOperations(getPlan(), refs, getModel()), { label: 'The cut pieces' });
      buffer = { ...next, cut: true, firstPaste: true }; lastPaste = null; selection?.clear();
      setStatus(`Cut ${refs.length} piece${refs.length === 1 ? '' : 's'}. Paste keeps their identity.`);
      return { ok: true };
    } catch (error) { return say(error.editorStatus || error.message); }
    finally { busy = false; onChange(); }
  }
  function targetRecord(target) {
    if (!target) return null;
    const ref = refOf(target), plan = getPlan();
    const r = record(plan, ref);
    if (r) return { ...r, ref, surface: target };
    if (ref.kind === 'ground') return { kind: 'ground', piece: {}, ref, surface: target };
    return null;
  }
  function accepts(e, t) {
    if (!t) return false;
    if (e.kind === 'opening') return t.kind === 'wall' && t.piece.kind !== 'separator';
    if (e.kind === 'terraces') return ['ground', 'terraces', 'beds'].includes(t.kind);
    if (e.pool) return t.kind === 'pool' && (t.piece.id || 'pool:0') === (e.pool || 'pool:0');
    if (e.kind.endsWith('_fixture')) return surfaceKinds.includes(t.kind) && !['pane', 'glass', 'shower_glass'].includes(t.surface?.slot || t.surface?.part);
    if (e.kind === 'anchor' || e.kind === 'device') return !!t.building && ['wall', 'room', 'porch'].includes(t.kind);
    return ['room', 'porch', 'floor', 'terraces', 'hardscape', 'beds', 'ground'].includes(t.kind);
  }
  function refusal(e) {
    return e.kind === 'opening' ? `A ${e.piece.kind === 'window' ? 'window' : 'door'} needs a wall.`
      : e.kind === 'terraces' ? 'A terrain pad needs ground or another pad.'
      : e.pool ? 'A pool feature must stay within the same pool.' : e.kind.endsWith('_fixture') ? 'A fixture needs a solid surface, not glass.' : 'This piece needs ground, a pad, a deck or a room floor.';
  }
  function canPaste(target, { mode } = {}) {
    if (!buffer) return { ok: false, reason: 'Copy or cut some pieces first.' };
    if (busy || !canEdit()) return { ok: false, reason: 'The editor is not ready to paste.' };
    let t = targetRecord(target);
    if (!target && mode !== 3) {
      const refs = selection?.members() || [], same = refs.length === buffer.entries.length && refs.every(r => buffer.entries.some(e => key(e.ref) === key(r)));
      if (!same && !followsPaste(refs)) t = refs.map(targetRecord).find(t => buffer.entries.some(e => accepts(e, t)));
    }
    if (target || t) {
      const invalid = buffer.entries.find(e => !accepts(e, t));
      if (invalid) return { ok: false, reason: refusal(invalid) };
    } else {
      const missing = buffer.entries.find(e => e.kind === 'opening' && !getPlan()?.buildings?.find(b => b.id === e.building)?.walls?.some(w => w.id === e.piece.wall && w.state !== 'ghost'));
      if (missing) return { ok: false, reason: missing.piece.gable ? 'Choose a wall for this gable window; it has no original wall to slide along.'
        : 'The original opening’s wall is gone. A window needs a wall.' };
    }
    return { ok: true, reason: '' };
  }
  function offset() {
    const q = view?.camera?.quaternion;
    const a = new Vector3(1, 0, 0), b = new Vector3(0, -1, 0), back = new Vector3(0, 0, 1);
    if (q) { a.applyQuaternion(q); b.applyQuaternion(q); back.applyQuaternion(q); }
    const flat = (v, fallback) => { const n = Math.hypot(v.x, v.z); return n > 1e-8 ? [v.x / n, -v.z / n] : fallback; };
    const right = flat(a, [1, 0]), down = flat(b, flat(back, [0, -1])), by = right.map((v, i) => (v + down[i]) * SNAP.move_ft);
    return Math.hypot(...by) > 1e-8 ? by : right.map(v => v * SNAP.move_ft);
  }
  function hostFor(t, at, original = {}) {
    const b = t.building, p = local(b, at);
    if (t.kind === 'wall') return hostedAt(b, { wall: t.piece.id, side: t.surface?.side || 'left', z: original.z || 0 }, p);
    return hostedAt(b, { [original.ceiling ? 'ceiling' : 'floor']: t.piece.id }, p);
  }
  function create(e, id, by, t, mode, openingAt, keepIdentity, destination) {
    const plan = getPlan(); let p = translated(e.piece, by), b = plan.buildings.find(b => b.id === e.building);
    if (e.kind === 'opening') {
      b = mode === 3 ? b : t.building;
      if (b.id !== e.building && e.inheritedMaterials) p.materials = { ...e.inheritedMaterials, ...p.materials };
      const wallId = mode === 3 ? e.piece.wall : t.piece.id;
      return { ...without(p, ['id', 'src', 'state', 'level', 'height', 'floor_reference_ft']), op: 'add_opening', building: b.id, id, wall: wallId, at: openingAt };
    }
    if (e.kind.endsWith('_fixture')) {
      p = without(p, ['orphaned', 'orphan_reason']);
      // Translated runs must not snap back to the source attachment on normalize.
      delete p.snap; delete p.anchors;
      if (t) {
        const levelId = t.piece.level || t.building?.walls?.find(w => w.id === (t.piece.wall || t.piece.host?.wall))?.level
          || t.building?.rooms?.find(r => r.id === (t.piece.host?.floor || t.piece.host?.ceiling))?.level;
        p.ref = t.building ? levelId ? 'floor' : 'absolute' : 'ground';
        if (t.building && levelId) { p.building = t.building.id; p.level = levelId; }
        else { delete p.building; delete p.level; }
        const oldReference = fixtureReference(plan, e.piece, e.piece.path?.[0] || e.piece.at);
        const level = t.building?.levels.find(l => l.id === levelId);
        const base = t.building ? (t.building.base || 0) + buildingGround(plan, t.building) : 0;
        const roofPoint = t.building && local(t.building, destination);
        const roofHeight = t.kind === 'roof' && t.piece.rect ? Math.min(...planes(t.piece).map(p => p[0] * roofPoint[0] + p[1] * roofPoint[1] + p[2])) : t.piece.plate;
        const ceiling = (t.surface?.slot || t.surface?.surface) === 'ceiling';
        const z = mode === 1 && destination.length > 2 ? destination[2] + base
          : t.kind === 'roof' ? base + (roofHeight || 0)
            : base + (level?.elevation || 0) + (t.kind === 'wall' ? (t.piece.height || level?.ceiling || 8) / 2
              : t.building ? ceiling ? level?.ceiling || 0 : t.piece.floor_offset_ft || 0 : groundAt(plan, ...destination));
        for (const at of p.path || [p.at]) at[2] += oldReference + z - buffer.fixtureHeight - fixtureReference(plan, p, at);
        if (p.aim) p.aim[2] += oldReference + z - buffer.fixtureHeight - fixtureReference(plan, p, p.aim);
      }
      if (p.path) {
        const absolute = p.path.map(at => [at[0], at[1], at[2] + fixtureReference(plan, p, at)]);
        const anchors = absolute.map((at, i) => {
          const host = t && t.kind !== 'ground' ? { kind: t.kind === 'terraces' ? 'terrace' : t.kind,
            id: t.piece.id, ...(t.building ? { building: t.building.id } : {}) }
            : mode === 3 ? e.piece.anchors?.[i]?.host || e.piece.snap?.host : null;
          return host ? pointAnchor(plan, host, at) : null;
        });
        if (anchors.some(Boolean)) {
          p.path = absolute; p.anchors = anchors; p.ref = 'absolute'; delete p.building; delete p.level;
        }
      }
      if (t?.kind === 'wall') for (const at of p.path || [p.at]) {
        const q = local(t.building, at), w = t.piece, d = w.to.map((v, i) => v - w.from[i]), length = Math.hypot(...d);
        const along = d.reduce((n, v, i) => n + (q[i] - w.from[i]) * v / length, 0);
        const across = Math.abs((q[0] - w.from[0]) * d[1] - (q[1] - w.from[1]) * d[0]) / length;
        if (along < 0 || along > length || across > (w.thickness || .5) + 1 / 12)
          throw new Error('The fixtures do not fit on that wall. Choose a clear surface with the same arrangement.');
      }
      return { op: e.kind === 'light_fixture' ? 'add_light_fixture' : 'add_effect_fixture',
        ...(e.entity_id ? { entity_id: e.entity_id } : {}), fixture: { ...p, id } };
    }
    if (e.kind === 'item' || e.kind === 'anchor' || e.kind === 'device') {
      const at = e.at.map((v, i) => v + by[i]);
      const rotation = (e.piece.rotation || 0) + e.buildingRotation;
      if (mode !== 3) b = t.building;
      if (e.kind === 'item' && !b) return { ...without(e.piece, ['id', 'host', 'src', 'state', 'device', 'device_id']),
        op: 'add_site_item', list: 'furniture', id, at, rotation: (rotation % 360 + 360) % 360 };
      if (!b && e.kind === 'device' && mode === 3) {
        const room = plan.site.yard_rooms?.find(r => r.id === e.piece.host?.yard_room);
        if (!room || !contains(room.polygon, at)) throw new Error('The device does not fit in its original yard room.');
        if (keepIdentity) {
          const lo = [0, 1].map(i => Math.min(...room.polygon.map(p => p[i]))), hi = [0, 1].map(i => Math.max(...room.polygon.map(p => p[i])));
          return { op: 'place_device', device: e.piece.device, host: { yard_room: room.id,
            u: (at[0] - lo[0]) / (hi[0] - lo[0]), v: (at[1] - lo[1]) / (hi[1] - lo[1]) }, offset: e.piece.offset || 0,
            ...fields(e.piece, ['facing_deg', 'orientation', 'rotation']) };
        }
        // Unbound device spots use the existing neutral sensor anchor. A ground
        // host stores lot coordinates in one building's frame; it claims no HA
        // entity and remains a visible/editable spot through the ordinary card.
        b = plan.buildings[0];
        if (!b) throw new Error('An unbound device spot needs a building.');
        return { op: 'add_anchor', id, building: b.id, kind: 'sensor', host: { ground: true, at: local(b, at) },
          offset: groundAt(plan, ...at) - buildingGround(plan, b) - (b.base || 0) + (e.piece.offset || 0) };
      }
      if (!b) throw new Error('A device anchor needs a building surface.');
      const host = mode === 3 ? hostedAt(b, resolvedHost(b, e.piece.host), local(b, at)) : hostFor(t, at, e.piece.host);
      if (e.kind === 'device' && keepIdentity) return { op: 'place_device', id, building: b.id, device: e.piece.device, host, offset: e.piece.offset || 0,
        ...fields(e.piece, ['facing_deg', 'orientation', 'rotation']) };
      return { ...without(e.piece, ['id', 'device', 'device_id', 'src', 'state']), op: e.kind === 'item' ? 'add_item'
        : ['meter', 'electric_panel', 'charger', 'parking'].includes(e.piece.kind) ? 'add_equipment' : 'add_anchor',
        kind: e.piece.kind || 'sensor', id, building: b.id, host,
        ...(e.kind === 'item' && (e.building !== b.id || e.buildingRotation !== (b.rotation || 0))
          ? { rotation: ((rotation - (b.rotation || 0)) % 360 + 360) % 360 } : {}),
        ...(keepIdentity && e.piece.device ? { device: e.piece.device } : {}) };
    }
    if (mode !== 3 && t && free.includes(e.kind) && e.kind !== 'terraces') {
      const at = e.at.map((v, i) => v + by[i]);
      const level = t.building?.levels.find(l => l.id === t.piece.level);
      const z = t.building ? (t.building.base || 0) + buildingGround(plan, t.building) + (level?.elevation || 0) + (t.piece.floor_offset_ft || 0)
        : groundAt(plan, ...at) + (t.kind === 'hardscape' ? (t.piece.elevation || 0) + .3 : 0);
      if (e.kind === 'furniture' && t.building) return { ...without(p, ['id', 'at', 'src', 'state']), op: 'add_item', id,
        building: t.building.id, host: hostFor(t, at), rotation: (((p.rotation || 0) - (t.building.rotation || 0)) % 360 + 360) % 360 };
      p.elevation = z - groundAt(plan, ...at) + (e.piece.elevation || 0);
      if (t.building && shapes.includes(e.kind) && e.points.some(q => Math.abs(groundAt(plan, q[0] + by[0], q[1] + by[1]) - groundAt(plan, ...at)) > 1 / 12))
        throw new Error('A yard piece needs a level surface on that floor.');
    }
    if (mode !== 3 && t?.building && e.kind === 'terraces') throw new Error('A terrain pad needs ground or another pad.');
    if (e.pool) return { ...without(p, ['id', 'src', 'state']), op: 'add_pool_feature', id };
    if (e.kind === 'terraces') return { ...fields(p, ['polygon', 'height', 'blend', 'edges']), op: 'add_pad', id };
    if (shapes.includes(e.kind)) return { ...fields(p, ['rotation', 'elevation']), ...fields(p, e.kind === 'fence' ? ['polyline', 'height', 'style', 'type', 'materials']
      : e.kind === 'fire_pit' ? ['shape', 'polygon', 'at', 'radius', 'fuel', 'body', 'top', 'height_in', 'glass', 'entity', 'materials']
        : p.kind === 'path' ? ['kind', 'points', 'width', 'corner', 'radius', 'smooth', 'material', 'edging', 'preset', 'pavers', 'materials']
          : ['polygon', 'material', 'materials']), op: 'add_site_shape', list: e.kind, id };
    return { ...without(p, ['id', 'src', 'state']), op: 'add_site_item', list: e.kind, id, asset: p.asset || p.preset };
  }
  async function paste({ mode, target, point } = {}) {
    const ready = canPaste(target, { mode }); if (!ready.ok) return say(ready.reason);
    let fallback = false;
    try {
      const plan = getPlan(), entries = buffer.entries;
      let t = targetRecord(target);
      if (!mode && target) mode = point ? 1 : 2;
      if (!mode) {
        const selected = selection?.members() || [], same = selected.length === entries.length && selected.every(r => entries.some(e => key(e.ref) === key(r)));
        if (!selected.length || same || followsPaste(selected)) mode = 3;
        else {
          t = selected.map(targetRecord).find(t => entries.some(e => accepts(e, t)));
          mode = t ? 2 : 3; fallback = !t;
        }
      }
      if (![1, 2, 3].includes(mode)) throw new Error('Choose paste mode 1, 2 or 3.');
      if (mode !== 3) {
        if (!t && selection?.primary()) t = targetRecord(selection.primary());
        const invalid = entries.find(e => !accepts(e, t));
        if (invalid) throw new Error(refusal(invalid));
      } else t = null;
      let destination;
      if (mode === 1) {
        const clicked = point || t?.surface?.point;
        if (!Array.isArray(clicked)) throw new Error('Choose a visible surface point for Paste.');
        destination = t.building ? world(t.building, clicked) : clicked;
      } else if (mode === 2) {
        const p = t.piece;
        destination = t.kind === 'wall' ? world(t.building, centre([p.from, p.to]))
            : t.kind === 'ground' ? point : t.building && p.host ? pointsOf(t, plan)[0]
            : t.building ? world(t.building, footprintCentre(p)) : footprintCentre(p);
        if (!destination) throw new Error('Choose a ground point for Paste.');
      }
      const firstCut = buffer.cut && buffer.firstPaste;
      const step = mode === 3 ? firstCut ? 0 : (lastPaste?.step || 0) + 1 : 0;
      const by = mode === 3 ? offset().map(v => v * step) : destination.map((v, i) => v - (buffer.centre[i] || 0)).slice(0, 2);
      const lot = plan.site?.lot;
      if (lot?.length) for (const e of entries.filter(e => e.kind !== 'opening')) {
        const polygons = e.piece.kind === 'path' ? pathSurfacePolygons(e.piece)
          : e.kind === 'fire_pit' && !e.piece.polygon ? [Array.from({ length: 64 }, (_, i) => [0, 1].map(a =>
            e.at[a] + (e.piece.radius || 2) * (a ? Math.sin : Math.cos)(i * Math.PI / 32)))] : [e.points];
        if (polygons.some(points => !inLot(lot, [...points, ...(points.length > 2 ? [points[0]] : [])].map(p => [p[0] + by[0], p[1] + by[1]]))))
          throw new Error('The pasted pieces would extend outside the lot. Choose a point inside the lot.');
      }
      if (t?.piece.polygon) for (const e of entries.filter(e => free.includes(e.kind))) {
        if (e.points.some(p => !contains(t.piece.polygon, t.building ? local(t.building, p.map((v, i) => v + (by[i] || 0))) : p.map((v, i) => v + (by[i] || 0)))))
          throw new Error('The copied set does not fit on that surface. Choose a larger pad or floor.');
      }
      const openings = entries.filter(e => e.kind === 'opening'), placements = new Map(), pending = [];
      const openingCentre = openings.length ? centre(openings.map(e => [e.piece.at, 0]))[0] : 0;
      for (const e of openings) {
        const b = mode === 3 ? plan.buildings.find(b => b.id === e.building) : t.building;
        const w = b?.walls.find(w => w.id === (mode === 3 ? e.piece.wall : t.piece.id) && w.state !== 'ghost');
        if (!w) throw new Error('The original opening’s wall is gone. A window needs a wall.');
        const length = Math.hypot(...w.to.map((v, i) => v - w.from[i]));
        const p = e.piece, width = p.width, existing = [...b.openings, ...(mode === 3 ? lastPaste?.placed || [] : []).filter(o => o.building === b.id), ...pending.filter(o => o.building === b.id),
          ...(mode === 3 && !firstCut ? openings.filter(o => o.building === b.id).map(o => o.piece) : [])];
        const clear = at => {
          if (at - width / 2 < -1e-8 || at + width / 2 > length + 1e-8) return false;
          const height = openingFloor(b, w, at).offset;
          return !existing.some(o => {
            if (o.wall !== w.id || o.state === 'ghost') return false;
            const other = o.floor_reference_ft ?? openingFloor(b, w, o.at).offset;
            return Math.min(o.at + o.width / 2, at + width / 2) - Math.max(o.at - o.width / 2, at - width / 2) > 1e-8
              && Math.min(o.head + other, p.head + height) - Math.max(o.sill + other, p.sill + height) > 1e-8;
          });
        };
        let at;
        if (mode === 3 && firstCut) {
          at = p.at;
          if (!clear(at)) throw new Error('The cut opening no longer fits on its original wall.');
        } else if (mode === 3) {
          // Search in grid steps, including the original still in the model.
          for (const direction of [1, -1]) {
            for (let n = 1; n * SNAP.move_ft <= length + 1e-8; n++) {
              const candidate = (lastPaste?.openings?.[key(e.ref)] ?? p.at) + direction * n * SNAP.move_ft;
              if (clear(candidate)) { at = candidate; break; }
            }
            if (at !== undefined) break;
          }
          if (at === undefined) throw new Error(`No free spot beside ${p.kind || 'the opening'} on its original wall.`);
        } else {
          const d = w.to.map((v, i) => v - w.from[i]);
          const clicked = local(b, destination);
          const anchor = mode === 2 ? length / 2 : d.reduce((sum, v, i) => sum + (clicked[i] - w.from[i]) * v / length, 0);
          at = anchor + p.at - openingCentre;
          if (!clear(at)) throw new Error('The openings do not fit on that wall there. Choose a longer, clear stretch.');
        }
        placements.set(e, at); pending.push({ ...p, at, wall: w.id, building: b.id, floor_reference_ft: openingFloor(b, w, at).offset });
      }
      const owner = e => mode === 3 ? e.building : ['opening', 'item', 'anchor', 'device', 'furniture'].includes(e.kind) ? t?.building?.id : undefined;
      const keep = entries.map(e => firstCut && owner(e) === e.building && !record(plan, e.ref));
      const ids = entries.map((e, i) => keep[i] ? e.piece.id : freshId(e.kind === 'light_fixture' ? 'fixture' : e.kind === 'effect_fixture' ? 'effect' : e.kind));
      const ops = entries.map((e, i) => create(e, ids[i], by, t, mode, placements.get(e), keep[i], destination));
      busy = true; onChange();
      await applyBatch(ops, { label: 'The pasted pieces' });
      if (firstCut) {
        buffer.firstPaste = false;
        for (const e of entries.filter((e, i) => keep[i])) {
          // Kind filters are independent of this piece's stored flags. Restoring
          // a visible piece must never show/unlock every other piece of its kind.
          visibility?.[e.hidden ? 'hide' : 'show']?.(e.ref.pieceId);
          visibility?.[e.locked ? 'lock' : 'unlock']?.(e.ref.pieceId);
        }
      }
      const refs = entries.map((e, i) => ({ kind: ['add_anchor', 'add_equipment'].includes(ops[i].op) ? 'anchor' : ops[i].op === 'add_item' ? 'item' : ops[i].list || e.kind, pieceId: ids[i],
        ...(ops[i].building || ops[i].fixture?.building ? { buildingId: ops[i].building || ops[i].fixture.building } : {}) }));
      lastPaste = { refs, step, placed: [...(lastPaste?.placed || []), ...pending], openings: Object.fromEntries(openings.map(e => [key(e.ref), placements.get(e)])) };
      selection?.set(refs);
      setStatus(`${fallback ? 'No valid host selected; pasted beside the originals. ' : ''}Pasted ${entries.length} piece${entries.length === 1 ? '' : 's'}.${firstCut && keep.some(k => !k) ? ' The piece got a new identity in its receiving owner.' : ''}${entries.some((e, i) => !keep[i] && (e.kind === 'device' || e.piece.device)) ? ' Device binding omitted.' : ''}`);
      return { ok: true };
    } catch (error) { return say(error.editorStatus || error.message); }
    finally { busy = false; onChange(); }
  }
  async function duplicate(refs = selection?.members()) {
    if (busy || !canEdit()) return say('The editor is not ready to duplicate.');
    // Use the same placement path with a private, short-lived buffer. The
    // person's object and material clipboards remain intact during the save.
    const temporary = createClipboard({ getPlan, getModel, getKit, selection, applyBatch, canEdit, setStatus, view, visibility });
    busy = true; onChange();
    try { const result = temporary.copy(refs); return result.ok ? await temporary.paste({ mode: 3 }) : result; }
    catch (error) { return say(error.message); }
    finally { busy = false; onChange(); }
  }
  function slotFor(surface) {
    if (!surface) return null;
    if (surface.slotDescriptor) return { owner: refOf(surface), slot: surface.slotDescriptor };
    const owner = refOf(surface), slots = pieceMaterialSlots(getPlan(), owner, getKit());
    const slotKey = surface.slot || surface.side || surface.part;
    const slot = slots.find(s => slotKey ? s.key === slotKey : surface.target
      ? Object.entries(surface.target).every(([k, v]) => s.target?.[k] === v) : slots.length === 1);
    return slot && { owner, slot };
  }
  function copyMaterial(surface) {
    const found = slotFor(surface);
    if (!found) return say('Choose a material slot or a surface with a material.');
    material = clone(found.slot.resolved); setStatus('Copied material, tint and UV offset.'); onChange(); return { ok: true };
  }
  async function pasteMaterial(surface) {
    if (!material) return say('Copy a material first.');
    if (busy || !canEdit()) return say('The editor is not ready to paste material.');
    const found = slotFor(surface); if (!found) return say('Choose a receiving material slot.');
    try {
      const refs = (selection?.members() || []).filter(r => r.kind === found.owner.kind);
      const shared = refs.length > 1 && refs.some(r => key(r) === key(found.owner))
        ? sharedMaterialRows(getPlan(), refs, getKit()).find(row => row.matches.some(m => key(m.owner) === key(found.owner) && m.slot.key === found.slot.key)) : null;
      const slots = shared ? shared.matches.map(m => m.slot) : [found.slot];
      busy = true; onChange(); await applyBatch(slots.map(s => s.operation(clone(material))), { label: 'The pasted material' });
      setStatus(`Pasted material on ${slots.length} slot${slots.length === 1 ? '' : 's'}.`); return { ok: true };
    } catch (error) { return say(error.editorStatus || error.message); }
    finally { busy = false; onChange(); }
  }
  return { copy, cut, paste, duplicate, canPaste, contents, copyMaterial, pasteMaterial, slotFor,
    clear() { if (!busy) { buffer = material = lastPaste = null; onChange(); } },
    hasMaterial: () => !!material, canCopy(refs = selection?.members()) {
      if (busy) return { ok: false, reason: 'Wait for the clipboard change to finish.' };
      try { capture(refs); return { ok: true, reason: '' }; } catch (e) { return { ok: false, reason: e.message }; }
    } };
}

export function clipboardKey(event, clipboard, { dialogOpen = false, canEdit = true } = {}) {
  if (event.shiftKey) return false;
  const duplicate = (event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'd';
  if (event.defaultPrevented || !(event.ctrlKey || event.metaKey) || event.altKey || dialogOpen
    || event.target?.isContentEditable || event.target?.closest?.('input, textarea, select, [contenteditable]')) {
    if (duplicate) event.preventDefault();
    return false;
  }
  const action = { c: 'copy', x: 'cut', v: 'paste', d: 'duplicate' }[event.key.toLowerCase()];
  if (!action) return false;
  if (['copy', 'cut'].includes(action) && globalThis.getSelection?.()?.isCollapsed === false) return false;
  // Always consume Ctrl+D here: an unavailable duplicate must not bookmark.
  event.preventDefault();
  if (event.repeat && ['paste', 'duplicate'].includes(action)) return false;
  if (canEdit || action === 'copy') return clipboard[action]();
  return false;
}
