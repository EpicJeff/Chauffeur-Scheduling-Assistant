import { Matrix4 } from 'three';

// Keep the editor's existing selection vocabulary; layers use these domains.
const KIND_ALIASES = { tree: 'planting', plants: 'planting', terraces: 'pad',
  retaining_wall: 'pad', beds: 'bed', edges: 'edge', light: 'fixture', light_fixture: 'fixture', effect_fixture: 'effect', floor: 'room',
  porch: 'room', porch_post: 'room', solar_zone: 'roof', dormer: 'roof', spa: 'pool', pool_step: 'pool',
  pool_ledge: 'pool', ledge: 'pool', steps: 'pool', yard_rooms: 'yard_room' };
export const visibilityKind = kind => KIND_ALIASES[kind] || kind;

// No materials or shader hooks. Backups belong to the current buffers, never
// the plan: restore before a deform, then take fresh backups of the result.
export function createPieceVisibility() {
  let ids = new Set(), kinds = new Set();
  let seen = new WeakMap();
  const ownerFields = ['pieceId', 'id', 'kind', 'visibilityKind', 'parentPieceId', 'buildingId', 'building', 'levelId', 'levelKey'];
  const positions = new Map(), instances = new Map(), objects = new Map(), geometries = new Map();
  const hidden = data => ids.has(data.pieceId ?? data.id) || ids.has(data.parentPieceId) || ids.has(data.buildingId ?? data.building)
    || kinds.has(visibilityKind(data.visibilityKind ?? data.kind));
  function restore() {
    for (const [attribute, ranges] of positions) {
      for (const { start, values } of ranges) attribute.array.set(values, start);
      attribute.needsUpdate = true;
    }
    for (const [mesh, rows] of instances) {
      for (const [index, matrix] of rows) mesh.setMatrixAt(index, matrix);
      mesh.instanceMatrix.needsUpdate = true;
    }
    for (const [object, value] of objects) {
      if (object.isLight) object.intensity = value;
      else object.visible = value;
    }
    for (const [object, original] of geometries) { object.geometry.dispose(); object.geometry = original; }
    positions.clear(); instances.clear(); objects.clear();
    geometries.clear();
    seen = new WeakMap();
  }
  function suppress(object) {
    // Removing a light from the render list changes NUM_*_LIGHTS and compiles
    // a new program. Zero its contribution while retaining the light count.
    if (objects.has(object)) return;
    objects.set(object, object.isLight ? object.intensity : object.visible);
    if (object.isLight) object.intensity = 0;
    else object.visible = false;
  }
  function enforce(root) {
    // Optional imports and editor marker layers can arrive after rebuild.
    if (root && (ids.size || kinds.size)) root.traverse(visit);
    // Effect poses and editor marker draws own visible on every frame.
    for (const object of objects.keys()) {
      if (object.isLight) object.intensity = 0;
      else object.visible = false;
    }
  }
  function apply(root) {
    restore();
    if (!root || !ids.size && !kinds.size) return;
    root.traverse(visit);
  }
  function visit(object) {
      const data = object.userData;
      const previous = seen.get(object);
      if (previous && previous.geometry === object.geometry && ownerFields.every(field => previous[field] === data[field])) return;
      // Editor selection helpers and device markers reuse objects for a new
      // owner. Their draw has already set the new visibility for this frame.
      if (previous) objects.delete(object);
      const expanded = data.visibilityGeometry?.(hidden);
      if (expanded) { geometries.set(object, object.geometry); object.geometry = expanded; }
      seen.set(object, {geometry:object.geometry, ...Object.fromEntries(ownerFields.map(field => [field, data[field]]))});
      const ranges = data.snapRanges ?? object.geometry?.userData.snapRanges;
      if ((data.levelId && ids.has(data.levelId)) || (data.levelKey && ids.has(data.levelKey.split(':').at(-1)))) {
        object.traverse(child => { if (child.isMesh || child.isSprite || child.isLight || child.isLine) suppress(child); });
        return;
      }
      if (object.isInstancedMesh && (data.instances || data.instancePiece)) {
        const rows = [];
        // Grass count grows as the camera approaches. Hide its entire buffer
        // once so newly submitted clumps retain the editor's pad visibility.
        const count=data.yardGrass?object.instanceMatrix.count:object.count;
        for (let index = 0; index < count; index++) {
          const piece = data.instances?.[index] ?? data.instancePiece?.(index);
          if (!piece || !hidden(piece)) continue;
          const matrix = new Matrix4(); object.getMatrixAt(index, matrix); rows.push([index, matrix]);
          const zero = matrix.clone(); zero.elements[0] = zero.elements[1] = zero.elements[2] = 0;
          zero.elements[4] = zero.elements[5] = zero.elements[6] = 0;
          zero.elements[8] = zero.elements[9] = zero.elements[10] = 0;
          object.setMatrixAt(index, zero);
        }
        if (rows.length) { instances.set(object, rows); object.instanceMatrix.needsUpdate = true; }
      } else if (ranges && object.geometry?.attributes.position) {
        const attribute = object.geometry.attributes.position, rows = [];
        // Multiple registry entries can point at the same material batch.
        if (positions.has(attribute)) return;
        for (const range of ranges) {
          if (!hidden(range) || !range.count) continue;
          const start = range.start * 3, end = (range.start + range.count) * 3;
          const values = attribute.array.slice(start, end); rows.push({ start, values });
          for (let i = start; i < end; i++) attribute.array[i] = values[(i - start) % 3];
        }
        if (rows.length) { positions.set(attribute, rows); attribute.needsUpdate = true; }
      } else if (hidden(data)) {
        let lights = false; object.traverse(child => { if (child.isLight) lights = true; });
        if (lights && !object.isLight) object.traverse(child => { if (child.isMesh || child.isSprite || child.isLight) suppress(child); });
        else suppress(object);
      }
  }
  return { set(nextIds, nextKinds) { ids = new Set(nextIds); kinds = new Set([...nextKinds].map(visibilityKind)); },
    setLightIntensity(object, intensity) {
      if (objects.has(object)) { objects.set(object, intensity); object.intensity = 0; }
      else object.intensity = intensity;
    }, hidden, apply, restore, enforce };
}
