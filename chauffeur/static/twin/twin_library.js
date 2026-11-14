import * as THREE from 'three';
import { modelLoader, colladaTexturesReady } from './import_loaders.js';
import { normaliseModel, modelBudget, mergeByMaterial, singlePassMaterial, heavyStandIn } from './objects.js';
import { HDRLoader } from 'three/addons/loaders/HDRLoader.js';
import { tierModel } from './model_lods.js';

export const base = () => window.chfBase ?? '../';
export function libUrl(assetId, name) {
  const url = base() + (assetId.startsWith('import-') ? 'api/house/twin/imports/' : 'api/house/twin/library/') + encodeURIComponent(assetId) + '/' + name.split('/').map(encodeURIComponent).join('/');
  return window.chfAuthUrl ? window.chfAuthUrl(url) : url;
}

export function materialUrl(path) {
  const parts = path.split('/');
  if (parts[0] !== 'materials' || parts.length < 3 || parts.some(part => {
    const decoded = decodeURIComponent(part);
    return !part || decoded === '.' || decoded === '..' || /[\\/]/.test(decoded);
  })) throw new Error('Choose a valid household material map path.');
  const url = base() + 'api/house/twin/' + parts.map(encodeURIComponent).join('/');
  return window.chfAuthUrl ? window.chfAuthUrl(url) : url;
}

// The page carries the vetted manifest, not a second list of filename guesses.
export function manifest(kit) { return kit?.manifest || window.twinManifest || {}; }

// Optional finishes and furnishings must not hold scene readiness forever when
// a connection stays open without delivering its image, buffer or HDR.
const ASSET_TIMEOUT_MS = 15000;
const modelCache = new Map(), skyCache = new Map(), textureCache = new Map();
function loadTexture(url) {
  if (!textureCache.has(url)) {
    const request = new Promise((done, reject) => new THREE.TextureLoader().load(url, done, undefined, reject))
      .catch(() => { if (textureCache.get(url) === request) textureCache.delete(url); return null; });
    textureCache.set(url, request);
  }
  return textureCache.get(url);
}
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
      if (!value && cache.get(key) === entry) cache.delete(key);
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

// One seamless tile of crossing 45-degree strips, 1.5 in wide / 4 in centres
// measured perpendicular to each strip. No DOM, network or external image.
function latticeTexture() {
  const size = 128, data = new Uint8Array(size * size * 4);
  const distance = v => Math.abs(v - Math.round(v));
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const u = (x + .5) / size, v = (y + .5) / size;
    const strip = Math.min(distance(u + v), distance(u - v)) < 1.5 / 4 / 2;
    const i = (y * size + x) * 4;
    data[i] = data[i + 1] = data[i + 2] = strip ? 255 : 0; data[i + 3] = 255;
  }
  const texture = new THREE.DataTexture(data, size, size);
  texture.name = 'generated lattice: 1.5in strips / 4in centres';
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.setScalar(1 / (Math.SQRT2 * 4 / 12)); // UVs in feet
  texture.magFilter = THREE.LinearFilter; texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.generateMipmaps = true; texture.needsUpdate = true;
  return texture;
}

function applyGraniteShader(material) {
  // Keep a neutral stone response under orange firelight/reflections. Retain
  // the chosen tint and luminance/speckle, rather than baking in a warm cast.
  material.onBeforeCompile = shader => {
    shader.uniforms.graniteTint = { value: material.color };
    shader.fragmentShader = 'uniform vec3 graniteTint;\n' + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace('#include <opaque_fragment>', `
        vec3 graniteLuma = vec3(.2126,.7152,.0722);
        vec3 neutralStone = vec3(dot(outgoingLight,graniteLuma)) * graniteTint / max(dot(graniteTint,graniteLuma),.001);
        outgoingLight = mix(outgoingLight,neutralStone,.95);
        #include <opaque_fragment>`);
  };
  material.customProgramCacheKey = () => 'granite-neutral-light-1';
}

// Include the receiving role: the bake classifies surfaces by material.name.
export function materialKey(value, role, tier, manifest) {
  const id = value.id || value.asset || role;
  const flags = [role === 'granite' && 'granite', value.pattern === 'lattice' && 'lattice', role === 'roof' && 'roof'].filter(Boolean);
  return JSON.stringify(['m', id, manifest[id]?.revision ?? 0, tier, role, value.color || null, flags]);
}

// Immutable master URLs are decoded once; each tier image is resized once.
// Material-owned clones share pixels, never repeat/rotation or GPU lifecycle.
const householdTextureCache = new Map();
const householdUrls = new Map(), textureOwners = new Map(), retiredTextures = new Map();
function releaseRetired(url) {
  if (textureOwners.get(url)?.size) return;
  textureOwners.delete(url);
  const retired = retiredTextures.get(url);
  retiredTextures.delete(url);
  for (const request of retired || []) Promise.resolve(request).then(texture => texture?.dispose());
}

// Retire obsolete immutable URLs immediately from both lookup caches. Existing
// material owners (including requests still in flight) retain their pixels until
// disposal; a later undo may load the URL afresh without reviving an old entry.
export function refreshMaterials(ids, known = null) {
  for (const id of ids) {
    const keep = new Set(Object.values(known?.[id]?.maps || {}).map(materialUrl));
    for (const url of householdUrls.get(id) || []) {
      if (keep.has(url)) continue;
      const retired = retiredTextures.get(url) || [];
      if (textureCache.has(url)) { retired.push(textureCache.get(url)); textureCache.delete(url); }
      for (const [key, entry] of householdTextureCache) if (JSON.parse(key)[0] === url) {
        retired.push(entry.complete); householdTextureCache.delete(key);
      }
      retiredTextures.set(url, retired); householdUrls.get(id).delete(url);
      releaseRetired(url);
    }
  }
}

export function currentMaterial(material, known) {
  const id = material.userData.materialId;
  return !id || material.userData.materialRevision === known[id]?.revision;
}

// Copy only the surface values. Viewing opacity/clipping and bake shader hooks
// belong to the receiving clone and must survive a material revision.
export function copyMaterialParams(source, target) {
  for (const key of ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'alphaMap',
    'roughness', 'metalness', 'aoMapIntensity', 'alphaTest', 'side']) target[key] = source[key];
  target.color.copy(source.color); target.normalScale.copy(source.normalScale);
  for (const key of ['materialId', 'materialRevision', 'materialKey', 'materialRef', 'materialRole'])
    target.userData[key] = source.userData[key];
  target.needsUpdate = true;
}

function householdTexture(path, tier, onLate) {
  const url = materialUrl(path), key = JSON.stringify([url, tier]);
  return optionalAsset(householdTextureCache, key, async () => {
    const source = await loadTexture(url);
    if (!source) return null;
    let image = source.image;
    const width = image.width, height = image.height;
    const cap = tier === 'low' ? 512 : tier === 'medium' ? 1024 : 2048;
    if (Math.max(width, height) > cap) {
      const canvas = document.createElement('canvas'), ratio = cap / Math.max(width, height);
      canvas.width = Math.max(1, Math.round(width * ratio)); canvas.height = Math.max(1, Math.round(height * ratio));
      canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
      image = canvas;
    }
    // Texture.clone shares Source; assigning clone.image would resize the master.
    const texture = new THREE.Texture(image); texture.name = url; texture.needsUpdate = true;
    return texture;
  }, texture => texture.clone(), onLate);
}

// Also used by the Library preview. Returns immediately; ready is bounded by
// the same optional-asset budget as built-ins and late maps still attach.
export function applyMaterialParams(material, entry, ref, role, tier) {
  // A preview may apply another revision to the same material while maps load.
  material.userData.releaseMaterialParams?.();
  const params = entry.params || {}, maps = entry.maps || {};
  material.name = role;
  const id = ref.id || ref.asset || role;
  material.userData.materialKey = materialKey(ref, role, tier, { [id]: entry });
  material.userData.materialId = id;
  material.userData.materialRevision = entry.revision;
  material.userData.materialRef = { ...ref };
  material.userData.materialRole = role;
  material.color.set(ref.color || params.tint || '#ffffff');
  // Auto is flat until this tier actually attaches the corresponding map.
  material.roughness = params.roughness ?? .85;
  material.metalness = params.metalness ?? 0;
  material.aoMapIntensity = params.ao_intensity ?? 1;
  const scale = params.normal_scale ?? 1;
  material.normalScale.set(scale, params.normal_convention === 'dx' ? -scale : scale);
  const tile = params.tile_ft || [4, 4];
  const properties = ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap'];
  for (const property of properties) material[property] = null;
  if (role === 'granite') applyGraniteShader(material);
  let disposed = false;
  const textures = new Set();
  const urls = new Set();
  material.alphaMap = null; material.alphaTest = 0; material.side = THREE.FrontSide;
  if (ref.pattern === 'lattice') {
    material.alphaMap = latticeTexture(); material.alphaTest = .5; material.side = THREE.DoubleSide;
    textures.add(material.alphaMap);
  }
  const release = () => {
    disposed = true;
    textures.forEach(texture => texture.dispose()); textures.clear();
    for (const url of urls) { textureOwners.get(url)?.delete(material); releaseRetired(url); }
    material.removeEventListener('dispose', release);
  };
  material.userData.releaseMaterialParams = release;
  material.addEventListener('dispose', release);
  const attach = properties => texture => {
    if (disposed) { texture.dispose(); return; }
    textures.add(texture);
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(1 / tile[0], 1 / tile[1]);
    texture.rotation = (params.rotation_deg ?? 0) * Math.PI / 180;
    texture.anisotropy = tier === 'low' ? 1 : 4;
    texture.colorSpace = properties.includes('map') ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    for (const property of properties) material[property] = texture;
    if (properties.includes('roughnessMap')) material.roughness = params.roughness ?? 1;
    if (properties.includes('metalnessMap')) material.metalness = params.metalness ?? 1;
    material.needsUpdate = true;
    material.dispatchEvent({ type: 'materialparamschange' });
  };
  const slots = [['base_color', ['map']]];
  if (tier !== 'low') {
    slots.push(['normal', ['normalMap']]);
    if (maps.orm) slots.push(['orm', ['roughnessMap', 'metalnessMap', 'aoMap']]);
    else slots.push(['roughness', ['roughnessMap']], ['metalness', ['metalnessMap']], ['ao', ['aoMap']]);
  }
  material.userData.ready = Promise.all(slots.filter(([slot]) => maps[slot]).map(([slot, properties]) => {
    const url = materialUrl(maps[slot]); urls.add(url);
    if (!householdUrls.has(id)) householdUrls.set(id, new Set());
    householdUrls.get(id).add(url);
    if (!textureOwners.has(url)) textureOwners.set(url, new Set());
    textureOwners.get(url).add(material);
    const apply = attach(properties);
    return householdTexture(maps[slot], tier, apply).then(texture => { if (texture) apply(texture); });
  }));
  material.needsUpdate = true;
  return material;
}

export function kitMaterial(role, kit, tier) {
  const ref = kit.materials?.[role] || {};
  const id = ref.id || ref.asset;
  const asset = manifest(kit)[id];
  if (asset?.household) return applyMaterialParams(new THREE.MeshStandardMaterial({ side: THREE.FrontSide }), asset, ref, role, tier);
  const material = new THREE.MeshStandardMaterial({
    name: role, color: ref.color || '#c3c6c2', roughness: ref.roughness ?? (role === 'roof' ? 0.45 : 0.85),
    metalness: role === 'roof' ? 0.45 : 0,
    side: THREE.FrontSide,
  });
  if (ref.pattern === 'lattice') {
    material.alphaMap = latticeTexture(); material.alphaTest = .5; material.side = THREE.DoubleSide;
    // r187 WebGLShadowMap caches depth/distance variants by this material's
    // UUID and copies alphaMap/alphaTest/DoubleSide, including after batching.
    // atlasMesh excludes cutouts as both bake receivers and bake occluders.
    return material;
  }
  if (role === 'granite') applyGraniteShader(material);
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
      loadTexture(url).then(source => {
        if (!source) clear();
        else if (!failed) {
          const texture = source.clone(); textures.add(texture);
          texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
          texture.repeat.setScalar(1 / (role === 'lawn' ? 8 : 4)); // generator UVs are in feet
          texture.anisotropy = tier === 'low' ? 1 : 4;
          if (property === 'map') texture.colorSpace = THREE.SRGBColorSpace;
          material[property] = texture;
          if (property === 'map') material.color.set(role === 'granite' ? ref.color || '#3b3d40' : ref.tint ? ref.color || '#ffffff' : '#ffffff');
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

// Feature slots share the scene's role cache, including across rebuilds and yard.
// Household instances retain their receiving role; built-in aliases keep their
// original path and appearance, including the kit's special shader behaviour.
export function materialSlot(value, defaultRole, kit, tier, cache, roleMaterial) {
  if (!value) return roleMaterial(defaultRole);
  const refs = kit.materials || {}, named = refs[value.id];
  const known = manifest(kit), id = known[value.id]?.household ? value.id : named?.id || named?.asset;
  if (known[id]?.household) {
    const roleRef = refs[defaultRole];
    if (!value.color && (roleRef?.id || roleRef?.asset) === id) {
      const role = roleMaterial(defaultRole);
      if (role?.name === defaultRole && role.userData.materialKey === materialKey(roleRef, defaultRole, tier, known)) return role;
    }
    const ref = { ...(named || {}), id, color: value.color || named?.color };
    const key = materialKey(ref, defaultRole, tier, known);
    if (!cache.has(key)) cache.set(key, kitMaterial(defaultRole,
      { ...kit, materials: { ...refs, [defaultRole]: ref } }, tier));
    return cache.get(key);
  }
  const role = named ? value.id : Object.keys(refs).find(key => refs[key].asset === value.id);
  const ref = named || (role && refs[role]) || { asset: value.id, color: '#b8b0a4' };
  const key = JSON.stringify(['material-slot', value.id, value.color || null, named || null]);
  if (!cache.has(key)) {
    const material = (!value.color || ref.pattern === 'lattice' && value.color === ref.color) && role ? roleMaterial(role)
      : kitMaterial(role || 'material', { ...kit, materials: { ...refs,
        [role || 'material']: { ...ref, asset: ref.asset || value.id, color: value.color || ref.color, tint: true } } }, tier);
    cache.set(key, material);
  }
  return cache.get(key);
}

const imported = new Map();
// Include the metadata used by loadModel (including LOD/file revisions) in
// callers' retained-geometry keys. An unknown import is resolved during load.
export const modelAssetKey = (id, kit) => id.startsWith('import-') ? imported.get(id) : manifest(kit)[id];
let importRead = null;
export function rememberImport(entry) { imported.set(entry.id, entry); }
export function forgetImport(assetId) {
  const asset = imported.get(assetId);
  for (const name of [asset?.model, ...(asset?.lods || []).map(l => l.name)].filter(Boolean)) {
    const key = libUrl(assetId, name), cached = modelCache.get(key);
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
export async function loadModel(assetId, kit, onLate, { tier = 'high', kind, editor = false, shared = false, lodName = null } = {}) {
  // Optional models may arrive late or use a tier-specific stand-in/LOD.
  // They remain visible and cast shadows, but cannot own shared lightmap UVs.
  const renderOnly = model => {
    model?.traverse(o => { if (o.geometry) o.geometry.userData.bakeExcluded = true; });
    return model;
  };
  const isImport = assetId.startsWith('import-');
  if (isImport && !imported.has(assetId)) await importedModels();
  const asset = isImport ? imported.get(assetId) : manifest(kit)[assetId];
  if (isImport && !editor && !lodName && asset?.lods?.length && (tier !== 'low' || asset.lods.some(l => l.name === 'lod2.glb'))) {
    const names = new Set(asset.lods.map(l => l.name));
    if (tier === 'low' && names.has('lod2.glb')) return loadModel(assetId, kit, onLate, { tier, kind, shared, lodName: 'lod2.glb' });
    const levels = [null, null, null]; let initial = true, delivered = false;
    const late = i => model => {
      levels[i] = model;
      if (!initial && !delivered && levels[0]) { delivered = true; onLate?.(renderOnly(tierModel(levels, tier))); }
    };
    await Promise.all([null, 'lod1.glb', tier === 'medium' ? null : 'lod2.glb'].map(async (name, i) => {
      if (i && (!name || !names.has(name))) return;
      const model = await loadModel(assetId, kit, onLate ? late(i) : undefined, { tier: 'high', kind, shared, editor: true, lodName: name });
      if (model) levels[i] = model;
    }));
    initial = false;
    if (levels[0]) { delivered = true; return renderOnly(tierModel(levels, tier)); }
    return null;
  }
  if (!editor && !lodName && isImport && tier === 'low' && asset?.triangles > 300000 && asset?.size) return renderOnly(heavyStandIn(asset.size, kind || asset.kind));
  const name = lodName || asset?.model || Object.keys(asset?.files || {}).find(n => /\.(gltf|glb|dae|kmz)$/i.test(n));
  if (!name) return null;
  // Authenticate buffers and textures as well as the top-level model. Resolving
  // each resource against a query-free directory avoids token loss on relatives.
  const directory = new URL(base() + (assetId.startsWith('import-') ? 'api/house/twin/imports/' : 'api/house/twin/library/') + encodeURIComponent(assetId) + '/', window.location.href);
  const manager = new THREE.LoadingManager();
  manager.setURLModifier(raw => {
    if (/^(data:|blob:)/.test(raw)) return raw;
    // The model URL itself is page-relative (libUrl); resources arrive already absolute
    // through setResourcePath. Resolving against the page keeps both right.
    const u = new URL(raw, window.location.href);
    if (u.origin === directory.origin && u.pathname.startsWith(directory.pathname)) {
      const path = decodeURIComponent(u.pathname.slice(directory.pathname.length));
      if (isImport && !Object.hasOwn(asset.files || {}, path)) throw new Error('Imported models must use their included resources.');
      u.search = '';
      return window.chfAuthUrl ? window.chfAuthUrl(u.href) : u.href;
    }
    if (isImport) throw new Error('Imported models must use their included resources.');
    return raw;
  });
  return optionalAsset(modelCache, libUrl(assetId, name), async () => {
    const loader = modelLoader(name, manager, asset.files || {});
    let result;
    try {
      result = await loader.setResourcePath(new URL(name.slice(0, name.lastIndexOf('/') + 1), directory).href).loadAsync(libUrl(assetId, name));
      if (result && /\.(dae|kmz)$/i.test(name)) await colladaTexturesReady(result.scene);
    } catch (error) {
      if (result?.scene) disposeObject(result.scene);
      throw error;
    } finally { loader.release?.(); }
    if (!result) return null;
    const converted = new Map();
    result.scene.traverse(o => {
      if (!o.isMesh) return;
      o.castShadow = o.receiveShadow = true;
      o.material = [].concat(o.material).map(m => {
        if (converted.has(m)) return converted.get(m);
        if (isImport) {
          const out = /\.(dae|kmz)$/i.test(name) && (m.isMeshPhongMaterial || m.isMeshLambertMaterial || m.isMeshBasicMaterial)
            ? new THREE.MeshStandardMaterial({
              name: m.name, color: m.color, map: m.map, normalMap: m.normalMap,
              opacity: m.opacity, transparent: m.transparent, alphaTest: m.alphaTest,
              side: m.side, vertexColors: m.vertexColors, roughness: .7, metalness: 0,
              ...(m.emissive ? { emissive: m.emissive, emissiveMap: m.emissiveMap } : {}),
            }) : singlePassMaterial(m);
          converted.set(m, out);
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
    if (isImport) { modelBudget(result.scene, { resizeTextures: false }); return lodName ? result.scene : normaliseModel(mergeByMaterial(result.scene)); }
    return result.scene;
  }, model => renderOnly(!editor && !lodName && tier === 'low' && isImport && asset?.triangles > 300000
    ? heavyStandIn(new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3()).toArray(), kind || asset.kind) : shared ? model.clone(true) : copyModel(model)), onLate);
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

// Geometry rebuilds of the same asset keep its compiled material instances.
// The caller owns this cache and releases it with the rest of its view.
export function cacheModelMaterials(root, key, cache) {
  const seen = new Map(), retired = new Set();
  root.traverse(o => {
    const reuse = m => {
      if (!seen.has(m)) {
        const id = `model:${key}:${seen.size}`, cached = cache.get(id);
        if (cached && cached !== m) retired.add(m);
        const material = cached || m; cache.set(id, material); seen.set(m, material);
      }
      return seen.get(m);
    };
    if (o.material) o.material = Array.isArray(o.material) ? o.material.map(reuse) : reuse(o.material);
  });
  const keepTextures = new Set([...cache.values()].flatMap(m => Object.values(m).filter(v => v?.isTexture)));
  const textures = new Set();
  for (const m of retired) {
    for (const value of Object.values(m)) if (value?.isTexture && !keepTextures.has(value)) textures.add(value);
    m.dispose();
  }
  textures.forEach(t => t.dispose()); return root;
}

export function disposeObject(root, { keepMaterials = new Set() } = {}) {
  const geometries = new Set(), materials = new Set(), textures = new Set();
  root.traverse(o => {
    o.userData.disposed = true;
    if (o.isInstancedMesh) o.dispose();
    if (o.geometry) geometries.add(o.geometry);
    for (const m of o.material ? [].concat(o.material) : []) {
      if (keepMaterials.has(m)) continue;
      materials.add(m);
      for (const value of Object.values(m)) if (value?.isTexture) textures.add(value);
    }
  });
  geometries.forEach(g => g.dispose());
  materials.forEach(m => m.dispose());
  textures.forEach(t => t.dispose());
}
