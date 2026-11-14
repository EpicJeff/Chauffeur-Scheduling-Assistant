import * as THREE from '../../vendor/three-r187/three.module.js';
import { atlasJob, buffers, applyAtlas } from './atlas_transport.js';
import { CANDELA } from '../twin_light_math.js';

const floatTexture = (width, height) => {
  const t = new THREE.DataTexture(new Float32Array(Math.max(1, width) * Math.max(1, height) * 4),
    Math.max(1, width), Math.max(1, height), THREE.RGBAFormat, THREE.FloatType);
  t.needsUpdate = true; return t;
};
// The baked pages are a shadowmask: per light, how much of its emitter a texel sees. The
// material lights each pixel as the live PointLight does (three's RE_Direct: falloff, N.L
// with the shading normal, diffuse and specular by the material's own metalness), times the
// visibility from the page, coloured by the tint. Two data textures carry everything, so the
// lightmap holds as many samplers as before the shadowmask (lmTints, lmRegions and a sampler
// per bank: a fully mapped material, the sun and two point shadows still link on ANGLE's 16).
//   lmTints   rows [0, R)    live colour x brightness by (slot, row): the switch, never a rebake
//             rows [R, 2R)   the light's world position (m) and reach (m)
//             rows [2R, 3R)  its shape: x = kind (0 point). Slice C (spot cone, line, area)
//                            adds kinds and their parameters here and a term in lmPoint.
//   lmRegions rows [0, Q)    a chart's (or room's) region per bank: offset, layer, owners
//             rows [Q, 2Q)   the same address: the room fill of channel a (r) and b (g)
// Chart mode: R = 1 and a slot per light index; Q rows of 1024 chart x bank addresses. Room
// mode: R = a row per room, a slot per bank channel; Q = a row per room, a column per bank.
// Every lookup is by data, never by a uniform array index, so merged batches need nothing more.
const rowsOf = t => Math.max(1, Math.floor(t.image.height / 3));
export function lightmapUniforms(roomCount, slotCount) {
  return { lmTints: { value: floatTexture(slotCount, 3 * Math.max(1, roomCount)) } };
}
// Where a light is: its bake source, as the shadowmask was rendered from (reach.js).
export function setLightSource(uniforms, room, slot, position, reach, kind = 0) {
  const t = uniforms.lmTints.value, rows = rowsOf(t);
  if (room < 0 || room >= rows || slot < 0 || slot >= t.image.width) return;
  t.image.data.set([position.x, position.y, position.z, reach], ((rows + room) * t.image.width + slot) * 4);
  t.image.data.set([kind, 0, 0, 0], ((2 * rows + room) * t.image.width + slot) * 4);
  t.needsUpdate = true;
}
const fillAt = (t, x, y, channel, value) => {
  const rows = Math.floor(t.image.height / 2);
  if (y < 0 || y >= rows || x < 0 || x >= t.image.width) return;
  t.image.data[((rows + y) * t.image.width + x) * 4 + channel] = value; t.needsUpdate = true;
};
// Room mode: a slot's fill in irradiance units (bank = slot / 2, channel = slot % 2).
export function setRoomFill(uniforms, room, slot, value) {
  if (uniforms.lmRegions) fillAt(uniforms.lmRegions.value, slot >> 1, room, slot & 1, value);
}
// Chart mode: the fill one channel of a chart's bank carries.
export function setChartFill(uniforms, chart, bank, banks, channel, value) {
  const [x, y] = chartAddress(chart, bank, banks);
  fillAt(uniforms.lmRegions.value, x, y, channel, value);
}
export function clearFills(uniforms) {
  const t = uniforms.lmRegions?.value; if (!t) return;
  const rows = Math.floor(t.image.height / 2);
  t.image.data.fill(0, rows * t.image.width * 4); t.needsUpdate = true;
}
export function setLightTint(uniforms, room, slot, rgb, intensity) {
  const t = uniforms.lmTints.value;
  if (room < 0 || room >= rowsOf(t) || slot < 0 || slot >= t.image.width) return;
  const c = new THREE.Color().setRGB(...rgb.map(x => x / 255), THREE.SRGBColorSpace).multiplyScalar(intensity);
  const i = (room * t.image.width + slot) * 4;
  t.image.data.set([c.r, c.g, c.b, 0], i); t.needsUpdate = true;
}
// A room-mode region texture: a column per bank, a row per room, then the fills.
export const roomRegions = (banks, rooms) => floatTexture(Math.max(1, banks), 2 * Math.max(1, rooms));
// Flat chart addressing stays below WebGL2's minimum texture-size limit even
// when a detailed house has more charts than texture rows.
export const chartAddress = (chart, bank, banks) => [((chart * banks + bank) % 1024), Math.floor((chart * banks + bank) / 1024)];
export function applyChartIndices(atlas) {
  const arrays = new Map(), ArrayType = atlas.room.charts.length < 32768 ? Int16Array : Float32Array;
  for (const c of atlas.room.charts) {
    // A proxy (a batten face, a trim edge) reads its host chart's texels and lights.
    for (const part of [{ mesh: c.mesh, faces: c.faces }, ...(c.proxies || [])]) {
      const g=part.mesh.geometry;
      if (!arrays.has(g)) arrays.set(g,new ArrayType(g.attributes.position.count).fill(-1));
      for (const f of part.faces) arrays.get(g).fill(c.id,f*3,f*3+3);
    }
  }
  for (const [g,data] of arrays) {
    g.setAttribute('lmRoom',new THREE.BufferAttribute(data,1));
    g.deleteAttribute('lmLightPage'); // Bank pages now come from chart metadata.
  }
}
export function chartLightmapUniforms(chartCount, packed, lights, pageSize, layers) {
  if (lights.length > 4095) throw new Error('Too many light indices for a chart owner texture.');
  const uniforms = lightmapUniforms(1, Math.max(1, lights.length)), banks = Math.max(1, packed.banks.length);
  // Regions in the first half of the rows, each address's fills in the second (lmFillsAt).
  const texture = floatTexture(1024, 2 * Math.max(1, Math.ceil(chartCount*banks/1024)));
  const owners = new Map();
  lights.forEach((l,index) => {
    const slot = packed.slots[l.device]; if (!slot) return;
    for (const a of slot.assignments || (slot.receivingCharts || []).map(chart=>({chart,bank:slot.bank,channel:slot.channel}))) {
      const key = a.chart*banks+a.bank;
      if (!owners.has(key)) owners.set(key,[0,0]);
      owners.get(key)[a.channel] = index+1;
    }
  });
  packed.banks.forEach((bank,b) => bank.charts.forEach(c => {
    const [x,y] = chartAddress(c.id,b,banks), owner = owners.get(c.id*banks+b) || [0,0];
    texture.image.data.set([(c.rect.x-c.sourceRegion.x)/pageSize, (c.rect.y-c.sourceRegion.y)/pageSize,
      Math.max(0,layers[b].indexOf(c.page)), owner[0]+owner[1]*4096], (y*1024+x)*4);
  }));
  texture.needsUpdate=true; uniforms.lmRegions={value:texture}; uniforms.lmChartMode={value:1};
  return uniforms;
}
export function chartLookupGLSL(banks) {
  return `ivec2 lmAddress(int bank, int chart) { int id = chart * ${Math.max(1,banks)} + bank; return ivec2(id % 1024, id / 1024); }
vec3 lmOwnerTint(float owner) { return owner < 0.5 ? vec3(0.0) : texelFetch(lmTints, ivec2(int(owner)-1, 0), 0).rgb; }`;
}
// The live PointLight at a view-space point: three's decay-2 falloff with its distance cutoff
// (real_lights.js). lmPoint answers the falloff (1/d^2 x cutoff), the unit direction and the
// cutoff alone (the room fill fades with it, so nothing glows past a light's reach). Kind 0
// is a point; other kinds (Slice C) answer 0 until built.
export const SHADE_GLSL = `int lmRows() { return max(1, textureSize(lmTints, 0).y / 3); }
vec3 lmTintAt(int slot, int row) { return texelFetch(lmTints, ivec2(slot, row), 0).rgb; }
vec4 lmFillsAt(ivec2 address) { return texelFetch(lmRegions, address + ivec2(0, textureSize(lmRegions, 0).y / 2), 0); }
float lmPoint(int slot, int row, vec3 posV, out vec3 direction, out float cutoff) {
  vec4 src = texelFetch(lmTints, ivec2(slot, lmRows() + row), 0), kind = texelFetch(lmTints, ivec2(slot, 2 * lmRows() + row), 0);
  direction = vec3(0.0, 0.0, 1.0); cutoff = 0.0;
  if (kind.x > 0.5 || src.w <= 0.0) return 0.0;
  vec3 toward = (viewMatrix * vec4(src.xyz, 1.0)).xyz - posV; float d = length(toward);
  direction = toward / max(d, 1e-4);
  cutoff = pow(clamp(1.0 - pow(d / src.w, 4.0), 0.0, 1.0), 2.0);
  return cutoff / max(d * d, 0.01);
}
int lmOwnerSlot(float owner) { return max(0, int(owner) - 1); }`;
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

// One baked light's term in a lit material's main(), after lights_fragment_end: three's own
// RE_Direct with an IncidentLight of the live light's colour, so diffuse (by metalness),
// specular and the material's normal match the live PointLight and nothing pops when a light
// goes fresh. The fill is indirect, faded by the light's reach cutoff at the pixel.
const directTerm = (tint, slot, row, visibility, fill) => `{ vec3 lmTint = ${tint};
  if (lmTint.r + lmTint.g + lmTint.b > 0.0) {
    vec3 lmDir; float lmCut, lmFall = lmPoint(${slot}, ${row}, geometryPosition, lmDir, lmCut);
    IncidentLight lmIncident; lmIncident.color = lmTint * (${CANDELA.toFixed(1)} * lmFall * ${visibility});
    lmIncident.direction = lmDir; lmIncident.visible = true;
    RE_Direct(lmIncident, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight);
    lmFill += lmTint * (${fill}) * lmCut;
  } }`;
export function patchLightmaps(materials, pages, uniforms) {
  const chartMode = !!uniforms.lmChartMode;
  // M8: a room's region sits two texels from its neighbours on a shared page. Sample no
  // coarser than mip 1 (gradients clamped to two texels a pixel), so a far-off room never
  // blends a neighbour's light into its border under its own tint. The gradients are
  // taken outside the room branch, where derivatives are defined. A bank no light owns here
  // skips its page fetch and its lights (the per-bank early-out).
  const bankCode = pages.banks.map((t, b) => {
    const s = lightSwizzle(t.format);
    const address = chartMode ? `lmAddress(${b}, int(vLmRoom + 0.5))` : `ivec2(${b}, lmRow)`;
    const owner = k => chartMode ? [`mod(region${b}.w, 4096.0)`, `floor(region${b}.w / 4096.0)`][k] : null;
    const term = k => chartMode
      ? directTerm(`lmOwnerTint(${owner(k)})`, `lmOwnerSlot(${owner(k)})`, '0', `bank${b}.${s[k]}`, `fill${b}.${'rg'[k]}`)
      : directTerm(`lmTintAt(${2 * b + k}, lmRow)`, `${2 * b + k}`, 'lmRow', `bank${b}.${s[k]}`, `fill${b}.${'rg'[k]}`);
    const live = chartMode ? `region${b}.w > 0.5`
      : `dot(lmTintAt(${2 * b}, lmRow) + lmTintAt(${2 * b + 1}, lmRow), vec3(1.0)) > 0.0`;
    return `vec4 region${b} = texelFetch(lmRegions, ${address}, 0);
if (${live}) {
  vec4 fill${b} = lmFillsAt(${address});
  float lmSpan${b} = max(length(lmDx), length(lmDy)) * float(textureSize(lmBank${b}, 0).x);
  float lmClamp${b} = lmSpan${b} > 2.0 ? 2.0 / lmSpan${b} : 1.0;
  vec4 bank${b} = textureGrad(lmBank${b}, vec3(vLmUV + region${b}.xy, region${b}.z), lmDx * lmClamp${b}, lmDy * lmClamp${b});
  ${term(0)}
  ${term(1)}
}`;
  }).join('\n');
  const declarations = `uniform sampler2D lmTints;
uniform sampler2D lmRegions;
varying vec2 vLmUV; varying float vLmRoom;
${pages.banks.map((t, b) => `uniform highp sampler2DArray lmBank${b};`).join('\n')}
${SHADE_GLSL}
${chartMode ? chartLookupGLSL(pages.banks.length) : ''}`;
  const slots = uniforms.lmTints.value.image.width, rooms = rowsOf(uniforms.lmTints.value);
  if (!uniforms.lmRegions) uniforms.lmRegions = { value: roomRegions(pages.banks.length, rooms) };
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
      // The baked lights shade with the fragment's own normal (normal maps, a batten's front
      // and sides) at its own position; the page says only how much of each light reaches it.
      shader.fragmentShader = shader.fragmentShader.replace('#include <lights_fragment_end>', `vec2 lmDx = dFdx(vLmUV), lmDy = dFdy(vLmUV);
#include <lights_fragment_end>
#if defined( STANDARD ) && !( NUM_SUN_LIGHTS > 0 || NUM_DIR_LIGHTS > 0 || NUM_POINT_LIGHTS > 0 || NUM_SPOT_LIGHTS > 0 )
  // three sets this only when a live punctual light exists; a baked light needs it too, or
  // its specular vanishes whenever the live pool is hidden.
  material.multiScatteringCompensation = 1.0 + material.specularColorBlended * ( 1.0 / ( material.dfg.x + material.dfg.y ) - 1.0 );
#endif
vec3 lmFill = vec3(0.0);
int lmRow = int(vLmRoom + 0.5);
if (vLmRoom > -0.5) {
${bankCode}
  RE_IndirectDiffuse(lmFill, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight);
}`);
    };
    material.customProgramCacheKey = () => `${key}|lm-7-shadowmask-direct|${chartMode ? 'charts-2|' : ''}${slots}|${pages.banks.map(t => lightSwizzle(t.format)).join(',')}`;
    material.needsUpdate = true;
  }
}

// A window pane glows with its room's baked light: the pane reads the shadowmask of the inside
// wall around it (glowRoom, glowUV) and lights it from its own point, with its normal on
// whichever side faces the lamp, standing in for that wall. Emissive, so no lighting chunks.
export function patchWindowGlow(material, pages, uniforms) {
  const chartMode = !!uniforms.lmChartMode, banks = pages.banks;
  const sum = banks.map((t, b) => {
    const s = lightSwizzle(t.format);
    const address = chartMode ? `lmAddress(${b}, int(vGlowRoom + 0.5))` : `ivec2(${b}, glowRow)`;
    const owner = k => [`mod(region${b}.w, 4096.0)`, `floor(region${b}.w / 4096.0)`][k];
    const term = k => {
      const tint = chartMode ? `lmOwnerTint(${owner(k)})` : `lmTintAt(${2 * b + k}, glowRow)`;
      const slot = chartMode ? `lmOwnerSlot(${owner(k)})` : `${2 * b + k}`, row = chartMode ? '0' : 'glowRow';
      return `{ vec3 lmTint = ${tint}; if (lmTint.r + lmTint.g + lmTint.b > 0.0) {
    vec3 lmDir; float lmCut, lmFall = lmPoint(${slot}, ${row}, glowPos, lmDir, lmCut);
    glow += lmTint * (${CANDELA.toFixed(1)} * lmFall * abs(dot(glowNormal, lmDir)) * value${b}.${s[k]} + fill${b}.${'rg'[k]} * lmCut); } }`;
    };
    return `vec4 region${b} = texelFetch(lmRegions, ${address}, 0);
vec4 fill${b} = lmFillsAt(${address});
vec4 value${b} = textureLod(glowBank${b}, vec3(vGlowUV + region${b}.xy, region${b}.z), 0.0);
${term(0)}
${term(1)}`;
  }).join('\n');
  material.onBeforeCompile = shader => {
    Object.assign(shader.uniforms, uniforms);
    banks.forEach((t, b) => { shader.uniforms[`glowBank${b}`] = { value: t }; });
    shader.vertexShader = 'attribute float glowRoom; attribute vec2 glowUV; varying float vGlowRoom; varying vec2 vGlowUV;\n' + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>
vGlowRoom = glowRoom; vGlowUV = glowUV;`);
    shader.fragmentShader = `uniform sampler2D lmTints; uniform sampler2D lmRegions;
varying float vGlowRoom; varying vec2 vGlowUV;
${banks.map((t, b) => `uniform highp sampler2DArray glowBank${b};`).join('\n')}
${SHADE_GLSL}
${chartMode ? chartLookupGLSL(banks.length) : ''}
` + shader.fragmentShader;
    // Irradiance / 16 x 8, as the pane glowed when the page held irradiance / 16.
    shader.fragmentShader = shader.fragmentShader.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
if (vGlowRoom > -0.5) {
  vec3 glow = vec3(0.0), glowPos = -vViewPosition, glowNormal = normalize(normal);
  int glowRow = int(vGlowRoom + 0.5);
  ${sum}
  totalEmissiveRadiance += glow * 0.5;
}`);
  };
  material.customProgramCacheKey = () => `twin-window-glow-6-shadowmask-${chartMode ? 'charts-' : ''}${banks.map(t => lightSwizzle(t.format)).join(',')}`;
  material.needsUpdate = true;
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
      const finish = () => { clearTimeout(timeout); w.terminate(); signal?.removeEventListener('abort', cancel); };
      // A worker which neither answers nor errors must not leave key:null forever.
      const timeout=setTimeout(() => { finish(); reject(new Error('Atlas worker timed out after 30 seconds.')); },30000);
      w.onmessage = e => { finish(); e.data.error ? reject(new Error(e.data.error)) : resolve(e.data); };
      w.onerror = e => { finish(); reject(e.error || new Error(e.message || 'Atlas worker failed.')); };
      w.onmessageerror = () => { finish(); reject(new Error('Atlas worker returned an unreadable message.')); };
      signal?.addEventListener('abort', cancel, { once: true });
      if (signal?.aborted) { cancel(); return; }
      try { w.postMessage(job, buffers(job.meshes)); }
      catch (error) { finish(); reject(error); }
    });
    await cached(db, data.key, data).catch(() => null);
    await cached(db, 'input:' + job.cacheKey, data.key).catch(() => null);
    await remember(db, data.key, job.cacheKey).catch(() => null);
    check();
    return answer(data);
  } finally { db?.close(); }
}
