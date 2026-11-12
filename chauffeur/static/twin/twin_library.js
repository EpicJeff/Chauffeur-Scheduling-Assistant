import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { normaliseModel, modelBudget, mergeByMaterial, singlePassMaterial, heavyStandIn } from './objects.js';
import { HDRLoader } from 'three/addons/loaders/HDRLoader.js';

export const base = () => window.chfBase ?? '../';
export function libUrl(assetId, name) {
  const url = base() + (assetId.startsWith('import-') ? 'api/house/twin/imports/' : 'api/house/twin/library/') + encodeURIComponent(assetId) + '/' + name.split('/').map(encodeURIComponent).join('/');
  return window.chfAuthUrl ? window.chfAuthUrl(url) : url;
}

// The page carries the vetted manifest, not a second list of filename guesses.
export function manifest(kit) { return kit?.manifest || window.twinManifest || {}; }

// Optional finishes and furnishings must not hold scene readiness forever when
// a connection stays open without delivering its image, buffer or HDR.
const ASSET_TIMEOUT_MS = 15000;
const modelCache = new Map(), skyCache = new Map(), textureCache = new Map();
function optionalAsset(cache, key, load, copy, onLate) {
  let entry = cache.get(key);
  if (!entry) {
    entry = {}; cache.set(key, entry);
    // Issue the request before starting its readiness budget. Completion stays
    // alive after that budget, for this scene and subsequent builds.
    try { entry.complete = Promise.resolve(load()); }
    catch { entry.complete = Promise.resolve(null); }
    entry.complete = entry.complete.catch(() => null).then(value => {
      entry.done = true; entry.value = value;
      if (!value) cache.delete(key);
      return value;
    });
    entry.ready = new Promise(resolve => {
      const timer = setTimeout(() => resolve(null), ASSET_TIMEOUT_MS);
      entry.complete.then(value => { clearTimeout(timer); resolve(value); });
    });
  }
  return (entry.done ? Promise.resolve(entry.value) : entry.ready).then(value => {
    if (value) return copy(value);
    if (onLate) entry.complete.then(late => { if (late) onLate(copy(late)); });
    return null;
  });
}

function copyModel(source) {
  const model = source.clone(true), geometries = new Map(), materials = new Map(), textures = new Map();
  model.traverse(o => {
    if (o.geometry) {
      if (!geometries.has(o.geometry)) geometries.set(o.geometry, o.geometry.clone());
      o.geometry = geometries.get(o.geometry);
    }
    const copy = material => {
      if (!materials.has(material)) {
        const out = material.clone();
        for (const [key, texture] of Object.entries(out)) if (texture?.isTexture) {
          if (!textures.has(texture)) textures.set(texture, texture.clone());
          out[key] = textures.get(texture);
        }
        materials.set(material, out);
      }
      return materials.get(material);
    };
    if (o.material) o.material = Array.isArray(o.material) ? o.material.map(copy) : copy(o.material);
  });
  return model;
}

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
  const pending = [];
  // A failed set is entirely plain kit colour, even if another map succeeds.
  let failed = false;
  const textures = new Set();
  const completions = new Set();
  const settle = () => { completions.forEach(resolve => resolve()); completions.clear(); };
  const clear = () => {
    failed = true;
    for (const key of ['map', 'normalMap', 'roughnessMap']) material[key] = null;
    material.color.set(ref.color || '#c3c6c2');
    textures.forEach(t => t.dispose());
    textures.clear();
    material.needsUpdate = true;
    settle();
  };
  for (const [property, pattern] of [['map', /_diff_/], ['normalMap', /_nor_gl_/], ['roughnessMap', /_rough_/]]) {
    if (tier === 'low' && property !== 'map') continue;
    const name = Object.keys(asset.files || {}).find(n => pattern.test(n));
    if (!name) continue;
    pending.push(new Promise(resolve => {
      completions.add(resolve);
      const url = libUrl(id, name);
      if (!textureCache.has(url)) {
        const request = new Promise((done, reject) => new THREE.TextureLoader().load(url, done, undefined, reject))
          .catch(() => { textureCache.delete(url); return null; });
        textureCache.set(url, request);
      }
      textureCache.get(url).then(source => {
        if (!source) clear();
        else if (!failed) {
          const texture = source.clone(); textures.add(texture);
          texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
          texture.repeat.setScalar(1 / (role === 'lawn' ? 8 : 4)); // generator UVs are in feet
          texture.anisotropy = tier === 'low' ? 1 : 4;
          if (property === 'map') texture.colorSpace = THREE.SRGBColorSpace;
          material[property] = texture;
          if (property === 'map') material.color.set('#ffffff');
          material.needsUpdate = true;
        }
        completions.delete(resolve);
        resolve();
      });
    }));
  }
  const timer = pending.length ? setTimeout(settle, ASSET_TIMEOUT_MS) : null;
  material.userData.ready = Promise.all(pending).then(() => clearTimeout(timer));
  material.addEventListener('dispose', clear);
  return material;
}

const imported = new Map();
let importRead = null;
export function rememberImport(entry) { imported.set(entry.id, entry); }
export function forgetImport(assetId) {
  const asset = imported.get(assetId);
  if (asset?.model) {
    const key = libUrl(assetId, asset.model), cached = modelCache.get(key);
    modelCache.delete(key);
    cached?.complete.then(model => { if (model) disposeObject(model); });
  }
  imported.delete(assetId); importRead = null;
}
export async function importedModels(refresh = false) {
  if (refresh) importRead = null;
  importRead ||= fetch(base() + 'api/house/twin/imports').then(async response => {
    if (!response.ok) throw new Error('Could not read imported models.');
    const entries = await response.json(); entries.forEach(rememberImport); return entries;
  }).catch(error => { importRead = null; throw error; });
  return importRead;
}
export async function loadModel(assetId, kit, onLate, { tier = 'high', kind } = {}) {
  const isImport = assetId.startsWith('import-');
  if (isImport && !imported.has(assetId)) await importedModels();
  const asset = isImport ? imported.get(assetId) : manifest(kit)[assetId];
  if (isImport && tier === 'low' && asset?.triangles > 300000 && asset?.size) return heavyStandIn(asset.size, kind || asset.kind);
  const name = asset?.model || Object.keys(asset?.files || {}).find(n => /\.(gltf|glb)$/i.test(n));
  if (!name) return null;
  // Authenticate buffers and textures as well as the top-level glTF. Resolving
  // each resource against a query-free directory avoids token loss on relatives.
  const directory = new URL(base() + (assetId.startsWith('import-') ? 'api/house/twin/imports/' : 'api/house/twin/library/') + encodeURIComponent(assetId) + '/', window.location.href);
  const manager = new THREE.LoadingManager();
  manager.setURLModifier(raw => {
    if (/^(data:|blob:)/.test(raw)) return raw;
    // The model URL itself is page-relative (libUrl); resources arrive already absolute
    // through setResourcePath. Resolving against the page keeps both right.
    const u = new URL(raw, window.location.href);
    if (u.origin === directory.origin && u.pathname.startsWith(directory.pathname)) {
      u.search = '';
      return window.chfAuthUrl ? window.chfAuthUrl(u.href) : u.href;
    }
    if (isImport) throw new Error('Imported models must use their included resources.');
    return raw;
  });
  return optionalAsset(modelCache, libUrl(assetId, name), async () => {
    const result = await new GLTFLoader(manager).setResourcePath(new URL(name.slice(0, name.lastIndexOf('/') + 1), directory).href).loadAsync(libUrl(assetId, name));
    if (!result) return null;
    const converted = new Map();
    result.scene.traverse(o => {
      if (!o.isMesh) return;
      o.castShadow = o.receiveShadow = true;
      o.material = [].concat(o.material).map(m => {
        if (converted.has(m)) return converted.get(m);
        if (isImport) {
          const out = singlePassMaterial(m); converted.set(m, out);
          if (out !== m) m.dispose();
          return out;
        }
        // Library glass is subject to the same single-pass rule as plan glass.
        const out = new THREE.MeshStandardMaterial({
          name: m.name, color: m.color, map: m.map, normalMap: m.normalMap, vertexColors: m.vertexColors,
          roughnessMap: m.roughnessMap, metalnessMap: m.metalnessMap,
          roughness: m.roughness ?? 0.85, metalness: m.metalness || 0,
          transparent: m.transparent || (m.transmission || 0) > 0,
          opacity: (m.transmission || 0) > 0 ? 0.3 : m.opacity,
          alphaTest: m.alphaTest, side: m.side, emissive: m.emissive, emissiveMap: m.emissiveMap, emissiveIntensity: m.emissiveIntensity,
        });
        m.dispose();
        converted.set(m, out);
        return out;
      });
      if (o.material.length === 1) o.material = o.material[0];
    });
    if (isImport) { modelBudget(result.scene); return normaliseModel(mergeByMaterial(result.scene)); }
    return result.scene;
  }, model => tier === 'low' && isImport && asset?.triangles > 300000
    ? heavyStandIn(new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3()).toArray(), kind || asset.kind) : copyModel(model), onLate);
}

export async function loadSky(kit, onLate) {
  const entries = Object.entries(manifest(kit));
  const entry = entries.find(([id, a]) => a.kind === 'hdri' && /partly_cloudy/.test(id)) || entries.find(([, a]) => a.kind === 'hdri');
  if (!entry) return null;
  const name = Object.keys(entry[1].files).find(n => n.endsWith('.hdr'));
  const manager = new THREE.LoadingManager();
  return name ? optionalAsset(skyCache, libUrl(entry[0], name),
    () => new HDRLoader(manager).loadAsync(libUrl(entry[0], name)), texture => texture.clone(), onLate) : null;
}

export function disposeObject(root) {
  const geometries = new Set(), materials = new Set(), textures = new Set();
  root.traverse(o => {
    o.userData.disposed = true;
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
