import * as THREE from '../../vendor/three-r187/three.module.js';
import { buildAtlas } from './atlas.js';
import { geometryFrom, covered, packAtlas, buffers } from './atlas_transport.js';

self.onmessage = event => {
  try {
    const { meshes, plan, layout } = event.data, root = new THREE.Group();
    for (const m of meshes) {
      const mesh = new THREE.Mesh(geometryFrom(m.geometry), new THREE.MeshStandardMaterial({ name: m.name }));
      mesh.matrixAutoUpdate = false; mesh.matrix.fromArray(m.matrix);
      mesh.userData = { merged: true, buildingId: m.buildingId }; root.add(mesh);
    }
    const atlas = buildAtlas(root, plan, layout), data = packAtlas(atlas, covered(root));
    self.postMessage(data, buffers(data));
  } catch (error) { self.postMessage({ error: error.message || String(error) }); }
};
