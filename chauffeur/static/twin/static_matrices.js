import * as THREE from 'three';

// Allow only adopted generator domains and the yard's authored parts. Effects,
// live cars/markers/labels, navigation, sky, probe cameras and live light pools
// are siblings outside these domains. Wind, water, grass and foliage animate
// shader uniforms/attributes, not their Object3D transforms.
const yardParts = new Set(['terrain','plants','fences','hardscape','pool','fire_pits','retaining_walls','furniture','grass']);
const frozen = new WeakSet();
function freeze(object) {
  object.updateMatrix();
  object.matrixAutoUpdate = false;
  frozen.add(object);
}
function freezeBranch(object, yard) {
  // The garage pivot moves with HA state. Imported skeletons and unfamiliar
  // object types remain automatic too; only rigid Groups/Meshes/Lines qualify.
  if (object.userData.garageOpening || object.isSkinnedMesh ||
      !(object.isGroup || object.isMesh || object.isLine)) return;
  if (yard && object === yard) {
    freeze(object);
    for (const child of object.children) if (yardParts.has(child.userData.yardPart)) freezeBranch(child);
    return;
  }
  freeze(object);
  for (const child of object.children) freezeBranch(child, yard);
}

export function freezeViewerMatrices(model, {editor=false} = {}) {
  if (editor) return;
  freeze(model.root);
  for (const domain of ['site','roof','gableFull','gableCut'])
    freezeBranch(model.groups[domain], model.yardGroup);
  for (const group of Object.values(model.groups.levels)) freezeBranch(group);
  // The per-building root holds ghost batches, whose runtime update changes
  // indices/visibility only. Its other domains have already been reparented.
  for (const entry of model.buildings.values()) freezeBranch(entry.model.root);
}

// Opt-in development/test assertion: no production per-frame walk or compose.
// A legitimate edit to a frozen transform must call updateMatrix() explicitly
// (e.g. reusing/repositioning a plant at adoption). Parent movement is fine.
export function assertStaticMatrices(root) {
  const local = new THREE.Matrix4();
  root.traverse(object => {
    if (!frozen.has(object)) return;
    local.compose(object.position, object.quaternion, object.scale);
    if (!local.equals(object.matrix)) throw new Error(`Moved static twin object: ${object.name || object.uuid}`);
  });
}
