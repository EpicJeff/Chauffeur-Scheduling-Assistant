import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { HDRLoader } from 'three/addons/loaders/HDRLoader.js';

export const base = () => window.chfBase ?? '../';
export function libUrl(assetId, name) {
  const url = base() + 'api/house/twin/library/' + encodeURIComponent(assetId) + '/' + name.split('/').map(encodeURIComponent).join('/');
  return window.chfAuthUrl ? window.chfAuthUrl(url) : url;
}

// The page carries the vetted manifest, not a second list of filename guesses.
export function manifest(kit) { return kit?.manifest || window.twinManifest || {}; }

export function kitMaterial(role, kit, tier) {
  const ref = kit.materials?.[role] || {};
  const id = ref.id || ref.asset;
  const asset = manifest(kit)[id];
  const material = new THREE.MeshStandardMaterial({
    name: role, color: ref.color || '#c3c6c2', roughness: role === 'roof' ? 0.45 : 0.85,
    metalness: role === 'roof' ? 0.45 : 0,
    side: THREE.FrontSide,
  });
  if (asset?.kind !== 'material') return material;
  const loader = new THREE.TextureLoader();
  const pending = [];
  // A failed set is entirely plain kit colour, even if another map succeeds.
  let failed = false;
  const textures = new Set();
  const clear = () => {
    failed = true;
    for (const key of ['map', 'normalMap', 'roughnessMap']) material[key] = null;
    material.color.set(ref.color || '#c3c6c2');
    textures.forEach(t => t.dispose());
    material.needsUpdate = true;
  };
  for (const [property, pattern] of [['map', /_diff_/], ['normalMap', /_nor_gl_/], ['roughnessMap', /_rough_/]]) {
    if (tier === 'low' && property !== 'map') continue;
    const name = Object.keys(asset.files || {}).find(n => pattern.test(n));
    if (!name) continue;
    pending.push(new Promise(resolve => {
      const tex = loader.load(libUrl(id, name), texture => {
        if (failed) texture.dispose();
        else {
          material[property] = texture;
          if (property === 'map') material.color.set('#ffffff');
          material.needsUpdate = true;
        }
        resolve();
      }, undefined, () => { clear(); resolve(); });
      textures.add(tex);
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.repeat.setScalar(1 / (role === 'lawn' ? 8 : 4)); // generator UVs are in feet
      tex.anisotropy = tier === 'low' ? 1 : 4;
      if (property === 'map') tex.colorSpace = THREE.SRGBColorSpace;
    }));
  }
  material.userData.ready = Promise.all(pending);
  material.addEventListener('dispose', () => textures.forEach(t => t.dispose()));
  return material;
}

export async function loadModel(assetId, kit) {
  const asset = manifest(kit)[assetId];
  const name = Object.keys(asset?.files || {}).find(n => /\.(gltf|glb)$/i.test(n));
  if (!name) return null;
  // Authenticate buffers and textures as well as the top-level glTF. Resolving
  // each resource against a query-free directory avoids token loss on relatives.
  const directory = new URL(base() + 'api/house/twin/library/' + encodeURIComponent(assetId) + '/', window.location.href);
  const manager = new THREE.LoadingManager();
  manager.setURLModifier(raw => {
    if (/^(data:|blob:)/.test(raw)) return raw;
    const u = new URL(raw, directory);
    if (u.origin === directory.origin && u.pathname.startsWith(directory.pathname)) {
      u.search = '';
      return window.chfAuthUrl ? window.chfAuthUrl(u.href) : u.href;
    }
    return raw;
  });
  try {
    const result = await new GLTFLoader(manager).setResourcePath(directory.href).loadAsync(libUrl(assetId, name));
    result.scene.traverse(o => {
      if (!o.isMesh) return;
      o.castShadow = o.receiveShadow = true;
      o.material = [].concat(o.material).map(m => {
        // Library glass is subject to the same single-pass rule as plan glass.
        const out = new THREE.MeshStandardMaterial({
          name: m.name, color: m.color, map: m.map, normalMap: m.normalMap,
          roughnessMap: m.roughnessMap, metalnessMap: m.metalnessMap,
          roughness: m.roughness ?? 0.85, metalness: m.metalness || 0,
          transparent: m.transparent || (m.transmission || 0) > 0,
          opacity: (m.transmission || 0) > 0 ? 0.3 : m.opacity,
          alphaTest: m.alphaTest, side: m.side,
        });
        m.dispose();
        return out;
      });
      if (o.material.length === 1) o.material = o.material[0];
    });
    return result.scene;
  } catch { return null; }
}

export async function loadSky(kit) {
  const entries = Object.entries(manifest(kit));
  const entry = entries.find(([id, a]) => a.kind === 'hdri' && /partly_cloudy/.test(id)) || entries.find(([, a]) => a.kind === 'hdri');
  if (!entry) return null;
  const name = Object.keys(entry[1].files).find(n => n.endsWith('.hdr'));
  try { return name ? await new HDRLoader().loadAsync(libUrl(entry[0], name)) : null; }
  catch { return null; }
}

export function disposeObject(root) {
  const geometries = new Set(), materials = new Set(), textures = new Set();
  root.traverse(o => {
    if (o.isInstancedMesh) o.dispose();
    if (o.geometry) geometries.add(o.geometry);
    for (const m of o.material ? [].concat(o.material) : []) {
      materials.add(m);
      for (const value of Object.values(m)) if (value?.isTexture) textures.add(value);
    }
  });
  geometries.forEach(g => g.dispose());
  materials.forEach(m => m.dispose());
  textures.forEach(t => t.dispose());
}
