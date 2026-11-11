import * as THREE from '../../vendor/three-r187/three.module.js';
import { atlasJob, buffers, applyAtlas } from './atlas_transport.js';

export function lightmapUniforms(roomCount, slotCount) {
  const t = new THREE.DataTexture(new Float32Array(Math.max(1, roomCount) * Math.max(1, slotCount) * 4),
    Math.max(1, slotCount), Math.max(1, roomCount), THREE.RGBAFormat, THREE.FloatType);
  t.needsUpdate = true;
  return { lmTints: { value: t } };
}
export function setLightTint(uniforms, room, slot, rgb, intensity) {
  const t = uniforms.lmTints.value;
  if (room < 0 || room >= t.image.height || slot < 0 || slot >= t.image.width) return;
  const c = new THREE.Color().setRGB(...rgb.map(x => x / 255), THREE.SRGBColorSpace).multiplyScalar(intensity);
  const i = (room * t.image.width + slot) * 4;
  t.image.data.set([c.r, c.g, c.b, 0], i); t.needsUpdate = true;
}
export const lightSwizzle = format => format === THREE.RGBAFormat ? 'ra' : 'rg';
export function pickTranscode(extensions, channels) {
  if (extensions.has('EXT_texture_compression_rgtc')) return channels === 1 ? THREE.RED_RGTC1_Format : THREE.RED_GREEN_RGTC2_Format;
  if (extensions.has('WEBGL_compressed_texture_etc')) return channels === 1 ? THREE.R11_EAC_Format : THREE.RG11_EAC_Format;
  return THREE.RGBAFormat;
}
export function transcodePage(module, bytes, format) {
  const names = new Map([[THREE.RED_RGTC1_Format, 'cTFBC4_R'], [THREE.RED_GREEN_RGTC2_Format, 'cTFBC5_RG'],
    [THREE.R11_EAC_Format, 'cTFETC2_EAC_R11'], [THREE.RG11_EAC_Format, 'cTFETC2_EAC_RG11'], [THREE.RGBAFormat, 'cTFRGBA32']]);
  const fmt = module.transcoder_texture_format[names.get(format)]?.value;
  const k = new module.KTX2File(new Uint8Array(bytes));
  try {
    if (fmt === undefined || !k.isValid() || !k.startTranscoding()) throw new Error('Invalid compressed lightmap.');
    const width = k.getWidth(), height = k.getHeight(), mipmaps = [];
    for (let level = 0; level < k.getLevels(); level++) {
      const data = new Uint8Array(k.getImageTranscodedSizeInBytes(level, 0, 0, fmt));
      if (!k.transcodeImage(data, level, 0, 0, fmt, 0, -1, -1)) throw new Error('Could not transcode the lightmap.');
      mipmaps.push({ data, width: Math.max(1, width >> level), height: Math.max(1, height >> level) });
    }
    return { width, height, format, mipmaps };
  } finally { k.close(); k.delete(); }
}

export function patchLightmaps(materials, pages, uniforms) {
  // M8: a room's region sits two texels from its neighbours on a shared page. Sample no
  // coarser than mip 1 (gradients clamped to two texels a pixel), so a far-off room never
  // blends a neighbour's light into its border under its own tint. The gradients are
  // taken outside the room branch, where derivatives are defined.
  const bankCode = pages.banks.map((t, b) => {
    const s = lightSwizzle(t.format);
    return `vec4 region${b} = texelFetch(lmRegions, ivec2(${b}, int(vLmRoom + 0.5)), 0);
float lmSpan${b} = max(length(lmDx), length(lmDy)) * float(textureSize(lmBank${b}, 0).x);
float lmClamp${b} = lmSpan${b} > 2.0 ? 2.0 / lmSpan${b} : 1.0;
vec4 bank${b} = textureGrad(lmBank${b}, vec3(vLmUV + region${b}.xy, region${b}.z), lmDx * lmClamp${b}, lmDy * lmClamp${b});
vec3 tint${b}a = texelFetch(lmTints, ivec2(${2*b}, int(vLmRoom + 0.5)), 0).rgb;
vec3 tint${b}b = texelFetch(lmTints, ivec2(${2*b+1}, int(vLmRoom + 0.5)), 0).rgb;
lmLight += bank${b}.r * tint${b}a + bank${b}.${s[1]} * tint${b}b;`;
  }).join('\n');
  const declarations = `uniform sampler2D lmTints;
uniform sampler2D lmRegions;
varying vec2 vLmUV; varying float vLmRoom;
${pages.banks.map((t, b) => `uniform highp sampler2DArray lmBank${b};`).join('\n')}`;
  const slots = uniforms.lmTints.value.image.width, rooms = uniforms.lmTints.value.image.height;
  if (!uniforms.lmRegions) {
    const t = new THREE.DataTexture(new Float32Array(Math.max(1, pages.banks.length) * rooms * 4),
      Math.max(1, pages.banks.length), rooms, THREE.RGBAFormat, THREE.FloatType); t.needsUpdate = true;
    uniforms.lmRegions = { value: t };
  }
  for (const material of new Set(materials)) {
    const before = material.userData.lmBefore || material.onBeforeCompile;
    const originalKey = material.userData.lmKey || material.customProgramCacheKey.bind(material);
    // Save the pre-patch key now; three's default key stringifies onBeforeCompile.
    const key = material.userData.lmOriginalKey ?? originalKey();
    material.userData.lmBefore = before; material.userData.lmOriginalKey = key;
    material.onBeforeCompile = (shader, renderer) => {
      before.call(material, shader, renderer);
      Object.assign(shader.uniforms, uniforms);
      pages.banks.forEach((t, b) => { shader.uniforms[`lmBank${b}`] = { value: t }; });
      shader.vertexShader = `#ifndef USE_UV3
attribute vec2 uv3;
#endif
attribute float lmRoom;
varying vec2 vLmUV; varying float vLmRoom;\n` + shader.vertexShader;
      shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>
vLmUV = uv3; vLmRoom = lmRoom;`);
      shader.fragmentShader = declarations + '\n' + shader.fragmentShader;
      shader.fragmentShader = shader.fragmentShader.replace('#include <lights_fragment_end>', `vec2 lmDx = dFdx(vLmUV), lmDy = dFdy(vLmUV);
#include <lights_fragment_end>
vec3 lmLight = vec3(0.0);
if (vLmRoom > -0.5) { ${bankCode} }
reflectedLight.indirectDiffuse += lmLight * 16.0 * RECIPROCAL_PI * diffuseColor.rgb;`);
    };
    material.customProgramCacheKey = () => `${key}|lm-4|${slots}|${pages.banks.map(t => lightSwizzle(t.format)).join(',')}`;
    material.needsUpdate = true;
  }
}

async function openCache(indexedDB) {
  if (!indexedDB) return null;
  return new Promise(resolve => {
    const r = indexedDB.open('twin-lightmap-atlases', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('atlases');
    r.onsuccess = () => resolve(r.result); r.onerror = r.onblocked = () => resolve(null);
  });
}
async function cached(db, key, data) {
  if (!db) return null;
  return new Promise(resolve => {
    const tx = db.transaction('atlases', data ? 'readwrite' : 'readonly'), store = tx.objectStore('atlases');
    const r = data ? store.put(data, key) : store.get(key);
    r.onsuccess = () => { if (!data) resolve(r.result); };
    tx.oncomplete = () => resolve(data); tx.onerror = tx.onabort = () => resolve(null); r.onerror = () => resolve(null);
  });
}
// A browser keeps its two most recently used atlases (I3): each holds the clipped house,
// about 14 MB, under Home Assistant's own origin. 'recent' lists them newest first with
// the input fingerprints that point at them; every other entry is deleted.
export const KEEP_ATLASES = 2;
async function remember(db, key, input) {
  if (!db) return;
  await new Promise(resolve => {
    const tx = db.transaction('atlases', 'readwrite'), store = tx.objectStore('atlases');
    const r = store.get('recent');
    r.onsuccess = () => {
      const list = (Array.isArray(r.result) ? r.result : []).filter(row => row && row.key);
      const mine = list.find(row => row.key === key) || { key, inputs: [] };
      if (!mine.inputs.includes(input)) mine.inputs.push(input);
      const keep = [mine, ...list.filter(row => row.key !== key)].slice(0, KEEP_ATLASES);
      store.put(keep, 'recent');
      const live = new Set(['recent', ...keep.flatMap(row => [row.key, ...row.inputs.map(i => 'input:' + i)])]);
      if (store.getAllKeys) {
        const all = store.getAllKeys();
        all.onsuccess = () => { for (const k of all.result) if (!live.has(k)) store.delete(k); };
      }
    };
    tx.oncomplete = resolve; tx.onerror = tx.onabort = resolve;
  });
}
// A module's URL as this page's import map versions it (I9): a worker script is never
// served from last week's cache.
export function versioned(spec, from = import.meta.url) {
  const plain = new URL(spec, from).href;
  try { return import.meta.resolve ? import.meta.resolve(plain) : plain; } catch { return plain; }
}
// apply: false answers {key, apply()} and leaves the meshes alone until apply() (M1).
export async function loadAtlas(root, plan, layout, { Worker = globalThis.Worker, indexedDB = globalThis.indexedDB, signal, apply = true } = {}) {
  const check = () => { if (signal?.aborted) throw new Error('Atlas cancelled.'); };
  check();
  const job = atlasJob(root, plan, layout), db = await openCache(indexedDB).catch(() => null);
  const answer = data => apply ? applyAtlas(data, root, layout) : { key: data.key, apply: () => applyAtlas(data, root, layout) };
  try {
    const key = await cached(db, 'input:' + job.cacheKey).catch(() => null);
    const hit = key && await cached(db, key).catch(() => null);
    check();
    if (hit) { await remember(db, hit.key, job.cacheKey).catch(() => null); return answer(hit); }
    const data = await new Promise((resolve, reject) => {
      const w = new Worker(versioned('./atlas_worker.js'), { type: 'module' });
      const cancel = () => { finish(); reject(new Error('Atlas cancelled.')); };
      const finish = () => { w.terminate(); signal?.removeEventListener('abort', cancel); };
      w.onmessage = e => { finish(); e.data.error ? reject(new Error(e.data.error)) : resolve(e.data); };
      w.onerror = e => { finish(); reject(e.error || new Error(e.message || 'Atlas worker failed.')); };
      signal?.addEventListener('abort', cancel, { once: true });
      if (signal?.aborted) { cancel(); return; }
      w.postMessage(job, buffers(job.meshes));
    });
    await cached(db, data.key, data).catch(() => null);
    await cached(db, 'input:' + job.cacheKey, data.key).catch(() => null);
    await remember(db, data.key, job.cacheKey).catch(() => null);
    check();
    return answer(data);
  } finally { db?.close(); }
}
