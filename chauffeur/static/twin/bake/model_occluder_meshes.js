// Detached depth-pass meshes. The drawn material batches and LOD visibility
// remain untouched; each range shell shares its source's vertex/index buffers.
import * as THREE from 'three';
import { placedCopies } from './model_occluders.js';

const ranges = new WeakMap();
function cachedRange(geometry, start, count) {
  let cache = ranges.get(geometry);
  if (!cache) {
    ranges.set(geometry, cache = new Map());
    geometry.addEventListener('dispose', () => {
      for (const entry of cache.values()) entry.geometry.dispose();
      cache.clear(); ranges.delete(geometry);
    });
  }
  const key = `${start}:${count}`;
  if (!cache.has(key)) {
    const bounds = new THREE.Box3(), point = new THREE.Vector3();
    const position = geometry.attributes.position, index = geometry.index;
    for (let i = start; i < start + count; i++)
      bounds.expandByPoint(point.fromBufferAttribute(position, index ? index.getX(i) : i));
    const shell = new THREE.BufferGeometry();
    shell.index = index; shell.attributes = { ...geometry.attributes };
    shell.setDrawRange(start, count);
    shell.boundingBox = bounds.clone(); shell.boundingSphere = bounds.getBoundingSphere(new THREE.Sphere());
    cache.set(key, { bounds, geometry: shell });
  }
  return cache.get(key);
}

const copyId = d => d.pieceId == null ? null : ['item', 'opening'].includes(d.kind)
  ? `${d.kind}:${d.buildingId}:${d.pieceId}`
  : ['furniture', 'planting'].includes(d.kind) ? `${d.kind}:${d.pieceId}` : null;
const opaque = m => m && !Array.isArray(m) && (!m.transparent || m.userData.viewingOpaque)
  && !(m.alphaTest > 0) && !['fixture', 'glass'].includes(m.name);

export function modelOccluderMeshes(root, plan, source, range) {
  if (!root) return [];
  root.updateWorldMatrix(true, true);
  const casts = new Map(placedCopies(plan).map(c => [c.id, c.castsShadow]));
  // Also cover openings whose plan-only host cannot currently be resolved.
  for (const b of plan.buildings || []) for (const o of b.openings || [])
    casts.set(`opening:${b.id}:${o.id}`, o.casts_shadow !== false);
  const copies = new Map();
  function visit(node) {
    if (node.isLOD) {
      const mid = node.levels[1] || node.levels[0];
      if (mid) visit(mid.object);
      return; // Never walk the other detail levels, even when they are visible.
    }
    if (node.isMesh && node.geometry?.userData.bakeExcluded && !node.layers.isEnabled(31)) {
      const g = node.geometry, total = g.index?.count || g.attributes.position?.count || 0;
      for (const r of node.userData.snapRanges || g.userData.snapRanges || [{ ...node.userData, start: 0, count: total }]) {
        const id = copyId(r);
        if (!id || casts.get(id) === false || !total) continue;
        const start = Math.max(0, r.start), count = Math.min(r.count, total - start);
        if (!(count > 0)) continue;
        const entry = cachedRange(g, start, count), world = entry.bounds.clone().applyMatrix4(node.matrixWorld);
        if (!copies.has(id)) copies.set(id, { bounds: new THREE.Box3(), meshes: [] });
        const copy = copies.get(id);
        copy.bounds.union(world);
        if (opaque(node.material)) copy.meshes.push({ node, r, geometry: entry.geometry });
      }
    }
    for (const child of node.children) visit(child);
  }
  visit(root);
  const sphere = new THREE.Sphere(source, range), meshes = [];
  for (const [id, copy] of copies) {
    // Containment belongs to the whole copy, including parts in other material
    // batches. A bulb inside a shade must never black out its own room.
    if (copy.bounds.containsPoint(source) || !copy.bounds.intersectsSphere(sphere)) continue;
    for (const { node, r, geometry } of copy.meshes) {
      const mesh = new THREE.Mesh(geometry, node.material);
      mesh.userData = { ...r, modelCopyId: id };
      mesh.matrixAutoUpdate = false; mesh.matrix.copy(node.matrixWorld); mesh.frustumCulled = false;
      meshes.push(mesh);
    }
  }
  return meshes;
}
