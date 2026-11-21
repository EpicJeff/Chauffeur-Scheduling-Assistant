import { Box3, Matrix4, Vector3 } from 'three';
import { PICK_LAYER } from '../twin_generator.js';

// Single bounds source for marquee selection and view outlines:
// structural proxies already retain their boxes; yard batches and instanced
// meshes retain ownership metadata (`instances` / `instancePiece` / `snapRanges`).
const EXCLUDED_KINDS = new Set(['floor', 'level', 'building', 'sheet', 'proposal']);
const YARD_ALIASES = { pad: 'terraces', retaining_wall: 'terraces', bed: 'beds', edge: 'edges', yard_room: 'yard_rooms' };
const SITE_COLLECTIONS = ['planting', 'furniture', 'terraces', 'hardscape', 'beds', 'edges', 'fence', 'fire_pit', 'yard_rooms'];

const rangeCache = new WeakMap();
const rangeWorldCache = new WeakMap();
const instanceCache = new WeakMap();

const _mat = new Matrix4();
const _box = new Box3();
const _vec = new Vector3();
const _corner = new Vector3();
const _eye = new Vector3();

const keyOf = r => JSON.stringify([r.buildingId ?? null, r.pieceId]);

function sameMatrix(a, b) {
  if (!a || !b) return false;
  for (let i = 0; i < 16; i++) if (a[i] !== b[i]) return false;
  return true;
}

function copyMatrixElements(target, source) {
  for (let i = 0; i < 16; i++) target[i] = source[i];
}

function ghostYardIdsFor(plan) {
  const ghosts = new Set();
  const site = plan?.site;
  if (!site) return ghosts;
  for (const key of SITE_COLLECTIONS) {
    const val = site[key];
    const list = Array.isArray(val) ? val : val ? [val] : [];
    for (const p of list) if (p?.state === 'ghost' && p.id) ghosts.add(p.id);
  }
  if (site.pool?.state === 'ghost' && site.pool.id) ghosts.add(site.pool.id);
  for (const f of site.pool?.features || []) if (f?.state === 'ghost' && f.id) ghosts.add(f.id);
  return ghosts;
}

function cachedInstanceRecords(object, localBox) {
  const { instances, instancePiece, pieceIds, kind: defaultKind } = object.userData;
  const matrixAttr = object.instanceMatrix;
  const version = matrixAttr?.version ?? -1;
  let cached = instanceCache.get(object);
  if (!cached
      || cached.geometry !== object.geometry
      || cached.count !== object.count
      || cached.matrixAttr !== matrixAttr
      || cached.version !== version
      || cached.instances !== instances
      || cached.instancePiece !== instancePiece
      || cached.pieceIds !== pieceIds) {
    const localRecords = [];
    for (let i = 0; i < object.count; i++) {
      const data = instances?.[i]
        ?? instancePiece?.(i)
        ?? (pieceIds?.[i] ? { pieceId: pieceIds[i], kind: defaultKind ?? 'planting' } : null);
      if (!data || data.ghost) continue;
      object.getMatrixAt(i, _mat);
      const e = _mat.elements;
      // Skip instances hidden by twin_visibility (zeroed 3x3 basis columns).
      const basisSq = e[0] * e[0] + e[1] * e[1] + e[2] * e[2]
        + e[4] * e[4] + e[5] * e[5] + e[6] * e[6]
        + e[8] * e[8] + e[9] * e[9] + e[10] * e[10];
      if (basisSq < 1e-12) continue;
      localRecords.push({ data, box: localBox.clone().applyMatrix4(_mat) });
    }
    cached = {
      geometry: object.geometry,
      count: object.count,
      matrixAttr,
      version,
      instances,
      instancePiece,
      pieceIds,
      localRecords,
      worldElements: new Float64Array(16),
      worldValid: false,
      worldBoxes: localRecords.map(() => new Box3()),
    };
    instanceCache.set(object, cached);
  }
  if (!cached.worldValid || !sameMatrix(cached.worldElements, object.matrixWorld.elements)) {
    copyMatrixElements(cached.worldElements, object.matrixWorld.elements);
    for (let i = 0; i < cached.localRecords.length; i++) {
      cached.worldBoxes[i].copy(cached.localRecords[i].box).applyMatrix4(object.matrixWorld);
    }
    cached.worldValid = true;
  }
  return cached;
}

function cachedRangeRecords(object, geometry, ranges) {
  const position = geometry.attributes.position;
  let cached = rangeCache.get(geometry);
  if (!cached || cached.version !== position.version || cached.ranges !== ranges) {
    const records = [];
    for (const range of ranges) {
      if (!range || range.ghost || !range.count) continue;
      const box = new Box3();
      for (let i = range.start; i < range.start + range.count; i++) {
        _vec.fromBufferAttribute(position, i);
        box.expandByPoint(_vec);
      }
      if (!box.isEmpty()) records.push({ range, box });
    }
    cached = { version: position.version, ranges, records };
    rangeCache.set(geometry, cached);
  }
  let world = rangeWorldCache.get(object);
  if (!world || world.cached !== cached) {
    world = {
      cached,
      worldElements: new Float64Array(16),
      worldValid: false,
      worldBoxes: cached.records.map(() => new Box3()),
    };
    rangeWorldCache.set(object, world);
  }
  if (!world.worldValid || !sameMatrix(world.worldElements, object.matrixWorld.elements)) {
    copyMatrixElements(world.worldElements, object.matrixWorld.elements);
    for (let i = 0; i < cached.records.length; i++) {
      world.worldBoxes[i].copy(cached.records[i].box).applyMatrix4(object.matrixWorld);
    }
    world.worldValid = true;
  }
  return { records: cached.records, worldBoxes: world.worldBoxes };
}

function ownerFromData(data, inherited = {}) {
  if (!data) return inherited;
  if (data.fixtureId) {
    return {
      kind: data.effectId ? 'effect_fixture' : 'light_fixture',
      pieceId: data.effectId || data.fixtureId,
      buildingId: data.building || undefined,
      level: data.level,
      visibilityKind: data.effectId ? 'effect' : 'fixture',
      fixtureId: data.fixtureId,
      effectId: data.effectId,
      entity_id: data.entity_id,
    };
  }
  return data.pieceId ? {
    ...inherited,
    kind: data.kind || inherited.kind,
    pieceId: data.pieceId,
    buildingId: data.buildingId ?? inherited.buildingId,
    level: data.level ?? inherited.level,
    visibilityKind: data.visibilityKind ?? inherited.visibilityKind,
    ghost: data.ghost || inherited.ghost,
  } : inherited;
}

// Editor fixture markers live as direct children of `editor-light-fixtures`
// (or directly on scene.children in isolated tests). Avoid full scene.traverse.
function fixtureMarkerObjects(scene) {
  if (!scene?.children) return [];
  const out = [];
  for (const child of scene.children) {
    if (child.name === 'editor-light-fixtures') {
      for (const marker of child.children) if (marker.userData?.fixtureId) out.push(marker);
    } else if (child.userData?.fixtureId) {
      out.push(child);
    }
  }
  return out;
}

function normalizeOwnerRef(ref, plan, ghostYardIds) {
  if (!ref?.pieceId || !ref.kind || ref.ghost) return null;
  if (EXCLUDED_KINDS.has(ref.kind) || String(ref.pieceId).startsWith('floor:')) return null;
  const b = ref.buildingId ? plan?.buildings?.find(x => x.id === ref.buildingId) : null;
  if (!b && ghostYardIds.has(ref.pieceId)) return null;
  if (!b && YARD_ALIASES[ref.kind]) ref = { ...ref, kind: YARD_ALIASES[ref.kind] };
  if (b) {
    if (ref.kind === 'roof') {
      const dormer = b.dormers?.find(d => d.id === ref.pieceId);
      const section = b.roof?.sections?.find(s => s.id === ref.pieceId);
      if (dormer) {
        if (dormer.state === 'ghost') return null;
        ref = { ...ref, kind: 'dormer', level: ref.level ?? section?.level ?? b.roofs?.find(r => r.id === dormer.roof)?.level };
      } else if (section?.roof) {
        const roof = b.roofs?.find(r => r.id === section.roof);
        if (roof?.state === 'ghost' || section.state === 'ghost') return null;
        ref = { ...ref, pieceId: section.roof, level: ref.level ?? section.level ?? roof?.level };
      } else {
        const roof = b.roofs?.find(r => r.id === ref.pieceId);
        if (roof?.state === 'ghost' || section?.state === 'ghost') return null;
        ref = { ...ref, level: ref.level ?? section?.level ?? roof?.level };
      }
    } else if (b.dormers?.some(d => d.id === ref.pieceId)) {
      if (b.dormers.find(d => d.id === ref.pieceId)?.state === 'ghost') return null;
      ref = { ...ref, kind: 'dormer' };
    }
  }
  return ref;
}

function visitSubtree(object, inherited, visible, onBox, targetId = null) {
  if (!object || !visible(object) || object.isLine || object.isSprite) return;
  if (object.layers?.isEnabled?.(PICK_LAYER)) return;
  const ud = object.userData || {};
  // Never walk or allocate per lawn/edge grass blade, and skip ghosts.
  if (ud.yardGrass || ud.yardPart === 'grass' || ud.ghost) return;
  const ref = ownerFromData(ud, inherited);
  // If targeting a single id and this subtree is owned by a different piece, skip it.
  if (targetId && ref?.pieceId && ref.pieceId !== targetId && !ud.snapRanges && !object.geometry?.userData?.snapRanges && !ud.instances && !ud.instancePiece && !ud.pieceIds) {
    return;
  }
  const geometry = object.geometry;
  if (object.isMesh && geometry) {
    if (!geometry.boundingBox) geometry.computeBoundingBox();
    const localBox = geometry.boundingBox;
    const ranges = ud.snapRanges || geometry.userData?.snapRanges;
    if (object.isInstancedMesh && (ud.instances || ud.instancePiece || ud.pieceIds)) {
      if (localBox && !localBox.isEmpty() && object.count > 0) {
        const cached = cachedInstanceRecords(object, localBox);
        for (let i = 0; i < cached.localRecords.length; i++) {
          const itemRef = ownerFromData(cached.localRecords[i].data, ref);
          if (targetId && itemRef?.pieceId !== targetId) continue;
          onBox(itemRef, cached.worldBoxes[i]);
        }
      }
    } else if (ranges && geometry.attributes?.position) {
      if (!targetId || ranges.some(r => r && (r.pieceId === targetId || r.effectId === targetId || r.fixtureId === targetId))) {
        const { records, worldBoxes } = cachedRangeRecords(object, geometry, ranges);
        for (let i = 0; i < records.length; i++) {
          const itemRef = ownerFromData(records[i].range, ref);
          if (targetId && itemRef?.pieceId !== targetId) continue;
          onBox(itemRef, worldBoxes[i]);
        }
      }
    } else if (ref?.pieceId && localBox && !localBox.isEmpty() && (!targetId || ref.pieceId === targetId)) {
      _box.copy(localBox).applyMatrix4(object.matrixWorld);
      onBox(ref, _box);
    }
  }
  for (const child of object.children) visitSubtree(child, ref, visible, onBox, targetId);
}

// Compute the rendered world Box3 for one specific yard item or fixture id
// without traversing the full scene or cloning boxes for unrelated pieces.
export function selectionBoxFor({ yard, scene, plan, visible = () => true, pieceId, buildingId = null, kind = null } = {}) {
  if (!pieceId) return null;
  const ghostYardIds = ghostYardIdsFor(plan);
  let matchedRef = null, box = null;
  const collect = (rawRef, itemBox) => {
    if (!itemBox || itemBox.isEmpty()) return;
    const ref = normalizeOwnerRef(rawRef, plan, ghostYardIds);
    if (!ref || ref.pieceId !== pieceId || (ref.buildingId ?? null) !== (buildingId ?? null)) return;
    if (!box) { box = itemBox.clone(); matchedRef = ref; }
    else box.union(itemBox);
  };
  if (kind === 'light_fixture' || kind === 'effect_fixture' || buildingId) {
    for (const marker of fixtureMarkerObjects(scene)) {
      const id = marker.userData.effectId || marker.userData.fixtureId;
      if (id !== pieceId || !visible(marker)) continue;
      marker.updateWorldMatrix(true, true);
      visitSubtree(marker, {}, visible, collect, pieceId);
    }
    if (matchedRef) return { ...matchedRef, box };
  }
  if (!buildingId && yard && visible(yard)) {
    visitSubtree(yard, {}, visible, collect, pieceId);
    if (matchedRef) return { ...matchedRef, box };
  }
  if (!kind || !['light_fixture', 'effect_fixture'].includes(kind)) {
    for (const marker of fixtureMarkerObjects(scene)) {
      const id = marker.userData.effectId || marker.userData.fixtureId;
      if (id !== pieceId || !visible(marker)) continue;
      marker.updateWorldMatrix(true, true);
      visitSubtree(marker, {}, visible, collect, pieceId);
    }
  }
  return matchedRef ? { ...matchedRef, box } : null;
}

export function selectionBoxes({ twin, yard, scene, plan, visible = () => true } = {}) {
  const boxes = new Map();
  const ghostYardIds = ghostYardIdsFor(plan);
  const add = (rawRef, box) => {
    if (!box || box.isEmpty()) return;
    const ref = normalizeOwnerRef(rawRef, plan, ghostYardIds);
    if (!ref) return;
    const k = keyOf(ref);
    const old = boxes.get(k);
    if (old) old.box.union(box);
    else boxes.set(k, { ...ref, box: box.clone() });
  };

  twin?.root?.updateMatrixWorld(true);
  for (const [id, entry] of twin?.pieceBounds || []) {
    const { data, box, group } = entry;
    if (!data || data.ghost || EXCLUDED_KINDS.has(data.kind)) continue;
    const proxy = twin.pickObjects.get(id);
    if (!proxy || !visible(proxy)) continue;
    let level;
    for (let p = proxy; p; p = p.parent) {
      if (p.userData.levelKey) {
        level = p.userData.levelKey.slice((data.buildingId?.length || 0) + 1);
        break;
      }
    }
    _box.copy(box).applyMatrix4(group.matrixWorld);
    add({
      kind: data.kind,
      pieceId: data.pieceId,
      buildingId: data.buildingId,
      level,
      visibilityKind: data.visibilityKind,
    }, _box);
  }

  if (yard) {
    yard.updateMatrixWorld(true);
    visitSubtree(yard, {}, visible, add);
  }
  // Editor fixtures live under `editor-light-fixtures` (no full scene.traverse).
  for (const marker of fixtureMarkerObjects(scene)) {
    if (!visible(marker)) continue;
    marker.updateWorldMatrix(true, true);
    visitSubtree(marker, {}, visible, add);
  }
  return [...boxes.values()];
}

export function projectSelectionBoxes(boxes, camera, rect) {
  if (!camera || !rect?.width || !rect?.height) return [];
  camera.updateMatrixWorld(true);
  const out = [];
  for (const entry of boxes) {
    const { box, ...ref } = entry;
    const xs = [box.min.x, box.max.x], ys = [box.min.y, box.max.y], zs = [box.min.z, box.max.z];
    let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
    let valid = true;
    for (let ix = 0; ix < 2 && valid; ix++) {
      for (let iy = 0; iy < 2 && valid; iy++) {
        for (let iz = 0; iz < 2 && valid; iz++) {
          _corner.set(xs[ix], ys[iy], zs[iz]);
          if (camera.isPerspectiveCamera) {
            _eye.copy(_corner).applyMatrix4(camera.matrixWorldInverse);
            if (_eye.z >= -camera.near) { valid = false; break; }
          }
          _corner.project(camera);
          if (!Number.isFinite(_corner.x) || !Number.isFinite(_corner.y) || !Number.isFinite(_corner.z)
              || _corner.z < -1 || _corner.z > 1) {
            valid = false;
            break;
          }
          const sx = rect.left + (_corner.x + 1) * rect.width / 2;
          const sy = rect.top + (1 - _corner.y) * rect.height / 2;
          if (sx < left) left = sx;
          if (sx > right) right = sx;
          if (sy < top) top = sy;
          if (sy > bottom) bottom = sy;
        }
      }
    }
    if (valid) out.push({ ...ref, bounds: { left, right, top, bottom } });
  }
  return out;
}
