import * as THREE from 'three';

// Code-side looks: these retain the generator and yard's existing defaults.
export const BUILTIN_LOOKS = {
  glass: { color: '#b9d7db', transparent: true, opacity: 0.26, roughness: 0.1, depthWrite: false },
  screen: { color: '#59615d', transparent: true, opacity: 0.3, depthWrite: false, doubleSide: true },
  water: { color: '#7fd0e6', transparent: true, opacity: 0.65, roughness: 0.12, depthWrite: false },
};

export function builtinMaterial(id, name = id) {
  const { doubleSide, ...params } = BUILTIN_LOOKS[id];
  const material = new THREE.MeshStandardMaterial({
    name, roughness: 0.8, ...params, side: doubleSide ? THREE.DoubleSide : THREE.FrontSide,
  });
  material.userData.alphaMode = 'blend';
  return material;
}
