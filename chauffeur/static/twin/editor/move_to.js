import { hostPoint } from '../twin_hosts.js';
import { roomAt } from '../twin_floors.js';
import { inPolygon } from '../twin_ground.js';
import { toLot, toLocal, hostedAt } from './lot_frame.js';

const WALL_ROOF = 'Wall and roof pieces stay on their wall or roof.';
const normalRotation = angle => ((angle % 360) + 360) % 360;
function properties(piece) {
  const copy = structuredClone(Object.fromEntries(Object.entries(piece)
    .filter(([key]) => !['id', 'at', 'src', 'state', 'host', 'offset', 'device', 'device_id'].includes(key))));
  // Add ops accept elevation, not the separate hosted offset. Ceiling hosts
  // subtract that offset, so fold its signed contribution into elevation.
  if (piece.offset) copy.elevation = (piece.elevation || 0) + (piece.host?.ceiling ? -piece.offset : piece.offset);
  return copy;
}

function record(plan, ref) {
  if (ref.kind === 'item') {
    const building = plan.buildings?.find(b => b.id === ref.buildingId);
    const piece = building?.items?.find(p => p.id === ref.pieceId);
    return piece ? { building, piece } : null;
  }
  if (['furniture', 'planting'].includes(ref.kind) && !ref.buildingId) {
    const piece = plan.site?.[ref.kind]?.find(p => p.id === ref.pieceId);
    return piece ? { piece } : null;
  }
  return null;
}

function place(record) {
  if (!record) return null;
  const { building, piece } = record;
  if (!building) return 'site';
  const host = piece.host || {};
  const surface = [...(building.rooms || []), ...(building.walls || []), ...(building.roofs || [])]
    .find(p => p.id === (host.floor || host.ceiling || host.wall || host.roof));
  return surface?.level ? `${building.id}:${surface.level}` : null;
}

/** Destinations are ownership places, independent of the editor's current view. */
export function moveTargets(plan, refs) {
  if (!refs.length) return [];
  const records = refs.map(ref => record(plan, ref));
  const disabled = records.some(r => r?.piece.host?.wall || r?.piece.host?.roof);
  return [{ key: 'site', label: 'Site' }, ...(plan.buildings || []).flatMap(building =>
    (building.levels || []).map(level => ({ key: `${building.id}:${level.id}`, label: `${building.name} · ${level.name}` })))]
    .filter(target => !records.every(r => place(r) === target.key))
    .map(target => ({ ...target, disabled, ...(disabled ? { reason: WALL_ROOF } : {}) }));
}

/** Build one flat applyBatch payload; a single blocker discards every operation. */
export function moveOps(plan, refs, targetKey) {
  const ops = [], selection = [], refused = [];
  const building = plan.buildings?.find(b => b.levels?.some(l => `${b.id}:${l.id}` === targetKey));
  const level = building?.levels.find(l => `${building.id}:${l.id}` === targetKey);
  for (const ref of refs) {
    const r = record(plan, ref);
    let reason;
    if (ref.kind === 'planting') reason = 'Plants stay on the site.';
    else if (!['item', 'furniture'].includes(ref.kind)) reason = 'This piece cannot move between places.';
    else if (!r) reason = 'That piece is missing.';
    else if (r.piece.host?.wall || r.piece.host?.roof) reason = WALL_ROOF;
    else if (targetKey === 'site' && r.piece.host?.ceiling) reason = 'Ceiling pieces cannot go to the site.';
    else if (targetKey !== 'site' && !level) reason = 'That destination is missing.';
    if (reason) { refused.push({ ref, reason }); continue; }
    if (place(r) === targetKey) { selection.push({ ...ref }); continue; }

    const { piece, building: source } = r;
    let at, sourcePoint;
    try {
      sourcePoint = source && hostPoint(source, piece.host, piece.offset || 0).slice(0, 2);
      at = source ? toLot(source, sourcePoint) : [...piece.at];
    }
    catch { refused.push({ ref, reason: 'The host surface is missing.' }); continue; }
    const rotation = (piece.rotation || 0) + (source?.rotation || 0);
    if (targetKey === 'site') {
      const lot = plan.site?.lot;
      if (lot?.length && !inPolygon(lot, ...at)) { refused.push({ ref, reason: 'Outside the lot.' }); continue; }
      ops.push({ op: 'delete', building: source.id, id: piece.id },
        { ...properties(piece), op: 'add_site_item', list: 'furniture', id: piece.id, require_inside: true,
          at, rotation: normalRotation(rotation) });
      // Both schemas store elevation above the new support. Do not carry the
      // source level, raised floor or foundation's absolute height to the yard.
      selection.push({ kind: 'furniture', pieceId: piece.id });
    } else {
      const local = source === building ? sourcePoint : toLocal(building, at), room = roomAt(building, level.id, local);
      if (!room) { refused.push({ ref, reason: `No room under it on ${level.name}.` }); continue; }
      let host;
      try { host = hostedAt(building, { [piece.host?.ceiling ? 'ceiling' : 'floor']: room.id }, local); }
      catch { refused.push({ ref, reason: `No room under it on ${level.name}.` }); continue; }
      if (source?.id === building.id) ops.push({ op: 'move_hosted', building: building.id, id: piece.id, host });
      else ops.push(source ? { op: 'delete', building: source.id, id: piece.id }
        : { op: 'delete_site_item', list: 'furniture', id: piece.id },
      { ...properties(piece), op: 'add_item', building: building.id, id: piece.id, host,
        rotation: normalRotation(rotation - (building.rotation || 0)) });
      selection.push({ kind: 'item', pieceId: piece.id, buildingId: building.id });
    }
  }
  return refused.length ? { refused } : { ops, selection };
}
