import { findPiece } from './piece_operations.js';
import { materialLines } from './library.js';
import { siteMaterialSlots, siteMaterialDescription } from './site_shape_shelf.js';
import { shapeOperation } from './site_shapes.js';
import { sceneRows } from './scene_tree.js';
import { surfaceDescription, materialName } from './material_catalog.js';
import { porchFoundation } from '../twin_porch_foundation.js';
import { retainingWallRole } from '../twin_retaining_wall.js';
import { planes } from '../twin_roof.js';

const copy = value => value == null ? value : structuredClone(value);
const pieceId = ref => ref.pieceId ?? ref.id;
const buildingId = ref => ref.buildingId ?? (typeof ref.building === 'string' ? ref.building : ref.building?.id);
const ownerKey = ref => JSON.stringify([buildingId(ref) || null, pieceId(ref)]);
const canonicalOwner = (plan, ref) => {
  const record = findPiece(plan, pieceId(ref), buildingId(ref));
  return record?.kind === 'roof' && record.piece.roof ? { ...ref, pieceId: record.piece.roof } : ref;
};
const effectiveId = (ref, kit) => kit.materials?.[ref?.id]?.id || kit.materials?.[ref?.id]?.asset || ref?.id;
const allowedSlots = (owner, slots) => !Array.isArray(owner.slots) ? slots : slots.filter(slot => owner.slots.includes(slot.key));

function descriptor(key, label, local, description, operation, extra = {}) {
  return { key, label, ref: copy(local || null), resolved: copy(description.ref), current: { ...description.current },
    inherited: description.inherited, text: description.text, operation, ...extra };
}

// Enumerate the same receiving slots as the ordinary Properties shelves. Slot
// inheritance remains entirely in materialLines/siteMaterialDescription and the
// surface resolver used by those builders. No building/house role is a target.
export function pieceMaterialSlots(plan, owner, kit = {}) {
  const id = pieceId(owner), bid = buildingId(owner);
  const record = findPiece(plan, id, bid);
  if (owner.kind === 'terraces' || !record && !bid && plan.site?.terraces?.some(p => p.id === id)) {
    const pad = plan.site?.terraces?.find(p => p.id === id);
    if (!pad) return [];
    const slots = [];
    pad.edges?.forEach((edge, index) => {
      if (edge.edge !== 'sharp') return;
      const kind = edge.wall ? 'wall' : edge.stair ? 'stair' : null;
      if (!kind) return;
      const value = edge[kind];
      const add = (key, label, role, nested = false) => {
        const local = (nested ? value.rail : value)?.materials?.[key];
        slots.push(descriptor(`edge:${index}:${kind}:${nested ? 'rail:' : ''}${key}`, `Edge ${index + 1} ${label}`,
          local, surfaceDescription(plan, { ref: local, role }, kit), (next, previous) => {
            const edges = copy(previous?.edges || pad.edges);
            const receiver = nested ? edges[index][kind].rail : edges[index][kind];
            receiver.materials = { ...receiver.materials, [key]: copy(next) };
            if (!next) delete receiver.materials[key];
            return { op: 'update_pad', id, edges };
          }));
      };
      if (kind === 'wall') {
        add('face', 'Wall face', retainingWallRole(value.material));
        if (value.cap) add('cap', 'Cap', 'patio_concrete');
      } else {
        add('riser', 'Risers', 'patio_concrete');
        if (value.treads !== false) add('tread', 'Treads material', 'patio_concrete');
      }
      if (value.rail) add('rail', 'Railing material', 'black_metal', true);
    });
    return slots;
  }
  if (!record) return [];
  const { piece, building, kind } = record;
  if (!building) return siteMaterialSlots(kind, piece).map(([part, label]) => {
    const local = piece.materials?.[part];
    const collection = plan.site?.[kind];
    const stored = Array.isArray(collection) ? collection[record.index] : collection;
    return descriptor(part, label, local, siteMaterialDescription(plan, kind, piece, part, local, kit), (next, previous) =>
      ({ ...shapeOperation(record, { materials: { ...previous?.materials, [part]: copy(next) } }), ...(stored?.id ? { id: stored.id } : {}) }));
  });
  const slots = materialLines(record, plan, kit).map(line => {
    const target = line.target;
    const key = target.side || target.part || target.surface || (target.plane !== undefined ? `plane:${target.plane}` : 'roof');
    return descriptor(key, line.label, line.ref, { ref: line.resolved, current: line.current, inherited: line.inherited, text: line.text },
      next => ({ op: 'set_material', building: building.id, target: { ...target }, material: copy(next) }),
      { target: { ...target }, surface: line.surface, aggregate: kind === 'roof' && target.plane === undefined });
  });
  if (kind === 'building') {
    const local = building.foundation?.materials?.slab;
    slots.push(descriptor('foundation:slab', 'Slab', local,
      surfaceDescription(plan, { role: 'patio_concrete', building, ref: local }, kit), (next, previous) => {
        const foundation = copy(previous?.foundation || building.foundation || { mode: 'fixed', offset_ft: 0, thickness_ft: 1 });
        foundation.materials = { ...foundation.materials, slab: copy(next) };
        if (!next) delete foundation.materials.slab;
        return { op: 'set_foundation', building: building.id, foundation };
      }));
  }
  if ((kind === 'room' || kind === 'porch') && piece.kind === 'porch') {
    const value = porchFoundation(piece.foundation);
    const parts = value.type === 'solid' ? [['solid', 'Solid base', 'base']]
      : [['posts', 'Posts and beam', 'trim'], ...(value.type === 'enclosed' ? [['skirt', 'Skirt', 'lattice']] : [])];
    for (const [part, label, role] of parts) {
      const local = value.materials[part];
      slots.push(descriptor(`foundation:${part}`, label, local,
        surfaceDescription(plan, { role, building, ref: local }, kit), (next, previous) => {
          const foundation = copy(previous?.foundation || value);
          foundation.materials[part] = copy(next); delete foundation.material;
          return { op: 'set_porch_foundation', building: building.id, id, foundation };
        }));
    }
  }
  return slots;
}

function countedSlots(plan, owner, kit) {
  const slots = pieceMaterialSlots(plan, owner, kit);
  // The whole-roof row is an inheritance parent, not one more rendered slope.
  return allowedSlots(owner, slots.filter(slot => !slot.aggregate || !slots.some(row => row.key.startsWith('plane:'))));
}

export function materialsInSelection(plan, refs, kit = {}) {
  const groups = new Map(), seen = new Set();
  for (const owner of refs || []) {
    for (const slot of countedSlots(plan, owner, kit)) {
      const key = JSON.stringify([ownerKey(canonicalOwner(plan, owner)), slot.key]);
      if (seen.has(key)) continue;
      seen.add(key);
      const id = slot.current?.id || effectiveId(slot.resolved, kit);
      if (!id) continue;
      if (!groups.has(id)) groups.set(id, { id, name: slot.current?.name || materialName(id),
        current: { ...slot.current, id: slot.current?.id === null ? null : id }, count: 0, slots: [] });
      const group = groups.get(id); group.count++; group.slots.push({ ...slot, owner });
    }
  }
  return [...groups.values()];
}

function aggregateKey(operation) {
  if (operation.op === 'set_material') return null;
  return JSON.stringify([operation.op, operation.building || null, operation.list || null, operation.id ?? operation.index ?? null]);
}

// Return payloads only: the caller sends exactly one applyBatch for the action.
// Coalesce whole-foundation/pad writes so two matching parts cannot overwrite
// each other's overrides within the same batch.
export function replacementOperations(plan, refs, materialId, nextMaterial, kit = {}) {
  const replacement = typeof nextMaterial === 'string' ? nextMaterial : nextMaterial?.id;
  if (!replacement) return [];
  const operations = [], aggregates = new Map();
  const group = materialsInSelection(plan, refs, kit).find(row => row.id === materialId);
  for (const slot of group?.slots || []) {
    const next = { id: replacement };
    if (slot.resolved?.color !== undefined) next.color = slot.resolved.color;
    if (slot.resolved?.uv !== undefined) next.uv = copy(slot.resolved.uv);
    if (JSON.stringify(slot.ref) === JSON.stringify(next)) continue;
    const initial = slot.operation(next), key = aggregateKey(initial);
    if (key && aggregates.has(key)) {
      const index = aggregates.get(key); operations[index] = slot.operation(next, operations[index]);
    } else {
      if (key) aggregates.set(key, operations.length);
      operations.push(initial);
    }
  }
  return operations;
}

export function selectUsingMaterial(plan, materialId, { refs = [], limit = 'all', view, visibility, kit = {} } = {}) {
  const buildings = new Set(refs.map(buildingId).filter(Boolean)), yardSelected = refs.some(ref => !buildingId(ref));
  const floor = typeof view === 'string' ? view : view?.selectionFloor?.() || view?.state?.view || 'ext';
  const floorLimited = floor && !['ext', 'house'].includes(floor);
  const selected = [], seen = new Set();
  for (const row of sceneRows(plan)) {
    if (['group', 'building', 'level'].includes(row.kind)) continue;
    const owner = canonicalOwner(plan, { kind: row.kind, pieceId: row.id, ...(row.building ? { buildingId: row.building } : {}) });
    if (seen.has(ownerKey(owner))) continue;
    const record = findPiece(plan, row.id, row.building);
    let level = row.piece?.level || record?.piece.level;
    for (let parent = row; parent && !level; parent = parent.parent) if (parent.kind === 'level') level = parent.id;
    if (row.building && floorLimited && `${row.building}:${level}` !== floor) continue;
    if (limit === 'yard' && row.building) continue;
    if (['buildings', 'building'].includes(limit) && (!row.building || !buildings.has(row.building))) continue;
    if (['selection', 'current'].includes(limit) && (row.building ? !buildings.has(row.building) : !yardSelected)) continue;
    const candidate = { ...owner, id: owner.pieceId, building: row.building, level, visibilityKind: row.visibilityKind };
    if (visibility?.isHidden?.(owner.pieceId, owner.kind) || visibility?.isLocked?.(owner.pieceId, owner.kind)) continue;
    if (visibility?.isPickable?.(candidate) === false || view?.isPiecePickable?.(candidate) === false || view?.isPieceHidden?.(candidate)) continue;
    let excluded = false;
    for (let parent = row; parent; parent = parent.parent) {
      if (visibility?.isHidden?.(parent.id, parent.visibilityKind || parent.kind)
        || visibility?.isLocked?.(parent.id, parent.visibilityKind || parent.kind)) { excluded = true; break; }
    }
    if (excluded) continue;
    const slots = countedSlots(plan, owner, kit).filter(slot => (slot.current?.id || effectiveId(slot.resolved, kit)) === materialId).map(slot => slot.key);
    if (!slots.length) continue;
    seen.add(ownerKey(owner));
    selected.push({ ...owner, ...(level ? { level } : {}), ...(row.poolId ? { poolId: row.poolId } : {}), slots });
  }
  return selected;
}

// The picker/library already owns the receiving surface; map its exact target
// back to the shared slots instead of guessing a material from the piece.
export function materialIdForSurface(plan, surface, kit = {}) {
  if (!surface) return null;
  const bid = typeof surface.building === 'string' ? surface.building : surface.building?.id;
  const owner = { kind: surface.kind, pieceId: surface.piece?.id || surface.pieceId || surface.id, buildingId: bid || surface.buildingId };
  const slots = pieceMaterialSlots(plan, owner, kit), target = surface.target;
  let surfaceKey = surface.slot || target?.slot || surface.side || surface.part;
  if (!surfaceKey && surface.kind === 'roof') {
    let edge = surface.plane;
    if (edge === undefined && surface.piece?.rect && surface.point) {
      // surfaceAt supplies building-local, z-up coordinates. Use the roof's
      // existing side-plane equations to identify the slope under that point.
      const [x, y] = surface.point;
      const plane = planes(surface.piece).reduce((best, candidate) =>
        !best || candidate[0] * x + candidate[1] * y + candidate[2] < best[0] * x + best[1] * y + best[2] ? candidate : best, null);
      edge = plane?.edge;
    }
    surfaceKey = edge != null ? `plane:${edge}` : 'roof';
  }
  if (!surfaceKey && surface.kind === 'dormer') surfaceKey = 'roof';
  if (!surfaceKey && typeof surface.surface === 'string') surfaceKey = surface.surface;
  if (!surfaceKey && slots.some(slot => slot.key === surface.role)) surfaceKey = surface.role;
  const matches = slot => surface.slot || target?.slot ? slot.key === surfaceKey : target ? (target.part && !slot.target ? slot.key === target.part : Object.entries(target).every(([key, value]) => slot.target?.[key] === value))
    : surfaceKey ? slot.key === surfaceKey : slots.length === 1;
  const slot = slots.find(matches);
  if (slot) return slot.current?.id || effectiveId(slot.resolved, kit);
  if (surface.renderedMaterialId) return effectiveId({ id: surface.renderedMaterialId }, kit);
  if (surface.role && ('ref' in surface || !slots.length)) {
    const description = surfaceDescription(plan, surface, kit);
    return description.current?.id || effectiveId(description.ref, kit);
  }
  return null;
}
