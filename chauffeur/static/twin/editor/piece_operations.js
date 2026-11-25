import { allPorches } from '../twin_generator.js';
import { siteRecord, siteRecords } from '../objects.js';

// A set resolves many owners against one immutable plan. Build the yard index
// once; retain findPiece's precedence and fallback for all building records.
export function createPieceLookup(plan) {
  const yard = new Map();
  for (const record of siteRecords(plan)) if (!yard.has(record.piece.id)) yard.set(record.piece.id, record);
  const cache = new Map();
  return (pieceId, buildingId) => {
    const key = JSON.stringify([buildingId || null, pieceId]);
    if (!cache.has(key)) cache.set(key, !buildingId && yard.get(pieceId) || findPiece(plan, pieceId, buildingId));
    return cache.get(key);
  };
}

export function findPiece(plan, pieceId, buildingId) {
  const site = !buildingId && siteRecord(plan, pieceId);
  if (site) return site;
  if (!buildingId) {
    const feature = plan?.site?.pool?.features?.find(f => f.id === pieceId);
    if (feature) return { piece: feature, kind: feature.kind, building: null, poolId: plan.site.pool.id };
  }
  const building = plan?.buildings.find(b => b.id === buildingId);
  if (!building) return null;
  if (building.id === pieceId) return { piece: building, building, kind: 'building' };
  for (const [list, kind] of [['solar_zones', 'solar_zone'], ['levels', 'level'], ['walls', 'wall'], ['openings', 'opening'], ['rooms', 'room'], ['stairs', 'stair'], ['anchors', 'anchor'], ['items', 'item'], ['fixtures', 'fixture'], ['lights', 'light']]) {
    const piece = building[list]?.find(p => p.id === pieceId);
    if (piece) return { piece, building, kind };
  }
  const porch = allPorches(building).find(p => p.id === pieceId);
  if (porch) return { piece: porch, building, kind: 'porch' };
  const section = building.roof?.sections?.find(p => p.id === pieceId);
  const dormer = building.dormers?.find(p => p.id === pieceId);
  if (dormer) return { piece: section || dormer, building, kind: 'dormer' };
  const piece = section || building.roofs?.find(p => p.id === pieceId);
  if (piece) return { piece, building, kind: 'roof' };
  const proposal = building.proposals?.find(p => (p.id || p.piece.id) === pieceId);
  return proposal ? { piece: { ...proposal.piece, id: proposal.id || proposal.piece.id }, building, kind: 'proposal' } : null;
}

const MODEL_LISTS = ['walls', 'joints', 'rooms', 'openings', 'anchors', 'items', 'roofs', 'dormers', 'extensions', 'stairs', 'solar_zones'];
// The card and selection set must choose the same model/legacy hand path.
export function deleteOperation(plan, ref, model = null) {
  const id = ref.pieceId ?? ref.id, bid = ref.buildingId ?? ref.building;
  if (['light_fixture', 'effect_fixture'].includes(ref.kind)) {
    const effect = ref.kind === 'effect_fixture';
    const entity_id = ref.entity_id || Object.keys(plan.light_fixtures || {}).find(e => plan.light_fixtures[e].some(p => p.id === id));
    return { op: effect ? 'delete_effect_fixture' : 'delete_light_fixture', id, ...(!effect ? { entity_id } : {}) };
  }
  if (ref.kind === 'device') {
    const piece = (bid ? plan.buildings.find(b => b.id === bid)?.devices : plan.site?.devices)?.find(p => p.id === id);
    if (!piece) throw new Error(`Missing device: ${id}`);
    return { op: 'unplace_device', device: piece.device || piece.device_id };
  }
  if (ref.kind === 'terraces') return { op: 'delete_pad', id };
  const record = findPiece(plan, id, bid);
  if (!record && !bid) return { op: 'delete_site_item', list: ref.kind, id };
  if (!record) throw new Error(`Missing ${ref.kind}: ${id}`);
  const { kind, piece, building } = record;
  if (record.poolId) return { op: 'delete_pool_feature', id };
  if (!building) return { op: 'delete_site_item', list: kind, id, index: record.index };
  const owner = model?.buildings?.find(b => b.id === building.id);
  const inModel = owner && MODEL_LISTS.some(list => owner[list]?.some(p => p.id === id));
  const modern = inModel || kind === 'solar_zone' || kind === 'porch' || kind === 'room' && piece.kind === 'porch'
    || kind === 'roof' && !piece.rect;
  return { op: 'delete', building: building.id, [modern ? 'id' : 'piece']: id };
}
