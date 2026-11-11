import * as THREE from 'three';
import { base } from '../twin_library.js';
import { contains, FT } from '../twin_generator.js';
import { groundAt } from '../twin_ground.js';
import { loadAtlas, lightmapUniforms, patchLightmaps, setLightTint, pickTranscode, lightSwizzle } from './lightmap_material.js';
import { createBaker, bakeLayout } from './baker.js';
import { workerCodec } from './worker_codec.js';
import { covered, geometryData, geometryFrom } from './atlas_transport.js';

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const options = density => ({ sky: { density: 2, page: 2048, gutter: 2 }, room: { density, page: 2048, gutter: 2 } });

function arrayTexture(results, count, format, size) {
  const example = results.find(Boolean);
  if (!example) return null;
  const mipmaps = example.mipmaps.map((m, level) => {
    const data = new Uint8Array(m.data.length * count);
    for (let page = 0; page < count; page++) if (results[page]) data.set(results[page].mipmaps[level].data, m.data.length * page);
    return { data, width: m.width, height: m.height };
  });
  // r187's CompressedArrayTexture also uploads RGBA32's explicit mip chain.
  // DataArrayTexture only uploads level zero, ignoring supplied mipmaps.
  const t = new THREE.CompressedArrayTexture(mipmaps, size, size, count, format);
  t.minFilter = THREE.LinearMipmapLinearFilter; t.magFilter = THREE.LinearFilter;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping; t.generateMipmaps = false; t.needsUpdate = true;
  return t;
}
function blankArray(count, format, size) {
  const block = format === THREE.RGBAFormat ? 0 :
    [THREE.RED_RGTC1_Format, THREE.R11_EAC_Format].includes(format) ? 8 : 16;
  const mipmaps = [];
  for (let n = size; n >= 1; n = Math.floor(n / 2)) mipmaps.push({ width: n, height: n,
    data: new Uint8Array(block ? Math.ceil(n / 4) ** 2 * block : n * n * 4) });
  return arrayTexture([{ mipmaps }], Math.max(1, count), format, size);
}
function replaceTexture(to, from) {
  to.mipmaps = from.mipmaps; to.image = from.image; to.needsUpdate = true; from.dispose();
}

export function mountBake(view, root, { host, controls = view.controls, layout: requestedLayout,
  api = (path, init) => fetch(base() + path, init) } = {}) {
  const round = view.plan, halt = new AbortController(), baked = [], fresh = new Set(), tints = new Map();
  const allowed = ['high', 'max'].includes(view.tier) && !new URLSearchParams(location.search).has('panel') &&
    !new URLSearchParams(location.search).has('kiosk');
  let stopped = false, atlas = null, layout = requestedLayout || options(8), lights = [], packed = null, uniforms = null, pages = null;
  let layers = [], baker = null, codec = null, running = false, pendingForce = false, dragging = false, stillAt = performance.now();
  let progress = { done: 0, total: 0 }, stale = [], timer = null, patched = false, skyReady = false;
  let failure = '';
  const cache = new Map(), clones = [], textures = new Set();
  const valid = () => !stopped && view.plan === round;
  const paused = () => dragging || performance.now() - stillAt < 2000;
  const moved = () => { stillAt = performance.now(); };
  const pointers = new Set();
  const down = event => { pointers.add(event.pointerId); dragging = true; moved(); };
  const up = event => { pointers.delete(event.pointerId); dragging = pointers.size > 0; moved(); };
  view.renderer3.domElement.addEventListener('pointerdown', down, { signal: halt.signal });
  window.addEventListener('pointerup', up, { signal: halt.signal });
  window.addEventListener('pointercancel', up, { signal: halt.signal });
  controls.addEventListener('start', moved); controls.addEventListener('change', moved); controls.addEventListener('end', moved);
  let strip = null, status = null, button = null;
  if (allowed && host) {
    strip = document.createElement('fieldset'); strip.id = 'twin-bake-controls';
    const legend = document.createElement('legend'); legend.textContent = 'Lighting';
    button = document.createElement('button'); button.type = 'button'; button.textContent = 'Bake lighting now';
    button.disabled = true; button.addEventListener('click', () => controller.now());
    status = document.createElement('output'); status.setAttribute('role', 'status'); status.hidden = true;
    strip.append(legend, button, status); host.append(strip);
  }
  function showProgress() {
    if (!status) return;
    status.hidden = !(running && progress.total) && !failure;
    status.textContent = running && progress.total ? `Baking lights ${Math.min(progress.total, progress.done + 1)} of ${progress.total}` : failure;
    button.disabled = !atlas || running;
  }
  async function idle() {
    while (valid() && (paused() || !view.ready)) await wait(50);
    if (!valid()) throw new Error('The bake round changed.');
    await new Promise(resolve => {
      if (globalThis.requestIdleCallback) requestIdleCallback(resolve, { timeout: 100 });
      else requestAnimationFrame(resolve);
    });
    if (paused()) return idle();
  }
  function skyTint(color, intensity) {
    if (uniforms) uniforms.skyTint.value.copy(color).multiplyScalar(skyReady ? intensity : 0);
  }
  function light(device, rgb, intensity) {
    tints.set(device, { rgb: [...rgb], intensity });
    const s = packed?.slots[device];
    if (s && uniforms) setLightTint(uniforms, s.room, s.bank * 2 + s.channel, rgb, fresh.has(device) ? intensity : 0);
  }
  function regions() {
    const width = Math.max(1, packed.banks.length), height = Math.max(1, atlas.room.rooms.length);
    const t = new THREE.DataTexture(new Float32Array(width * height * 4), width, height, THREE.RGBAFormat, THREE.FloatType);
    packed.banks.forEach((bank, b) => bank.rooms.forEach(({ room, sourceRegion, region }) => {
      t.image.data.set([(region.x - sourceRegion.x) / layout.room.page,
        (region.y - sourceRegion.y) / layout.room.page, Math.max(0, layers[b].indexOf(region.page)), 0], (room * width + b) * 4);
    }));
    t.needsUpdate = true; return t;
  }
  function patch() {
    if (patched) return;
    patched = true;
    const materials = new Set();
    // Atlas attributes exist only on covered meshes. Give those meshes their own
    // materials; props sharing a kit material must not sample uninitialised UVs.
    for (const m of covered(root)) {
      const original = m.material, material = original.clone();
      m.material = material; clones.push({ mesh: m, original, material }); materials.add(material);
    }
    patchLightmaps([...materials], pages, uniforms);
    patchWindows();
  }
  function patchWindows() {
    function windowSample(centre, room, paneNormal) {
      if (room < 0) return null;
      const triangle = new THREE.Triangle(), point = new THREE.Vector3(), bary = new THREE.Vector3();
      let closest = Infinity, uv = null;
      for (const chart of atlas.room.charts) {
        if (chart.room !== room) continue;
        const g = chart.mesh.geometry, pos = g.attributes.position, tex = g.attributes.uv3;
        const local = centre.clone().applyMatrix4(chart.mesh.matrixWorld.clone().invert());
        for (const face of chart.faces) {
          const index = face * 3;
          triangle.a.fromBufferAttribute(pos, index); triangle.b.fromBufferAttribute(pos, index + 1); triangle.c.fromBufferAttribute(pos, index + 2);
          // Prefer the inside wall around the pane over its thin side reveal.
          const normal = triangle.getNormal(new THREE.Vector3());
          normal.transformDirection(chart.mesh.matrixWorld);
          if (Math.abs(normal.dot(paneNormal)) < .7) continue;
          triangle.closestPointToPoint(local, point);
          const distance = point.distanceToSquared(local);
          if (distance >= closest) continue;
          closest = distance; triangle.getBarycoord(point, bary);
          uv = [0, 1].map(k => bary.x * tex.array[index * 2 + k] +
            bary.y * tex.array[(index + 1) * 2 + k] + bary.z * tex.array[(index + 2) * 2 + k]);
        }
      }
      return uv;
    }
    root.updateMatrixWorld(true);
    root.traverse(mesh => {
      if (!mesh.isMesh || mesh.material?.name !== 'glass' || mesh.layers.isEnabled(31)) return;
      let buildingId;
      for (let p = mesh; p && !buildingId; p = p.parent) buildingId = p.userData.buildingId;
      const building = round.buildings.find(b => b.id === buildingId); if (!building) return;
      if (mesh.geometry.index) mesh.geometry = mesh.geometry.toNonIndexed();
      const pos = mesh.geometry.attributes.position, owners = new Float32Array(pos.count).fill(-1), p = new THREE.Vector3();
      const glowUV = new Float32Array(pos.count * 2);
      const angle = -(building.rotation || 0) * Math.PI / 180;
      for (let i = 0; i < pos.count; i += 3) {
        const centre = new THREE.Vector3();
        for (let k = 0; k < 3; k++) centre.add(p.fromBufferAttribute(pos, i + k));
        centre.multiplyScalar(1 / 3).applyMatrix4(mesh.matrixWorld);
        const dx = centre.x / FT - (building.position?.[0] || 0), dy = -centre.z / FT - (building.position?.[1] || 0);
        const x = Math.cos(angle) * dx - Math.sin(angle) * dy, y = Math.sin(angle) * dx + Math.cos(angle) * dy;
        const height = centre.y / FT - (building.base || 0) - groundAt(round, ...(building.position || [0, 0]));
        const room = building.rooms.find(r => {
          const level = building.levels.find(l => l.id === r.level);
          return level && height >= level.elevation && height <= level.elevation + level.ceiling &&
            [[0, 0], [.5, 0], [-.5, 0], [0, .5], [0, -.5]].some(([a, b]) => contains(r.polygon, [x + a, y + b]));
        });
        const owner = atlas.room.rooms.findIndex(r => r.building === buildingId && r.id === room?.id);
        const paneNormal = new THREE.Triangle(...[0, 1, 2].map(k => new THREE.Vector3().fromBufferAttribute(pos, i + k)))
          .getNormal(new THREE.Vector3()).transformDirection(mesh.matrixWorld);
        const sample = windowSample(centre, owner, paneNormal);
        if (sample) {
          owners.fill(owner, i, i + 3);
          for (let k = 0; k < 3; k++) glowUV.set(sample, (i + k) * 2);
        }
      }
      mesh.geometry.setAttribute('glowRoom', new THREE.BufferAttribute(owners, 1));
      mesh.geometry.setAttribute('glowUV', new THREE.BufferAttribute(glowUV, 2));
      const original = mesh.material, material = original.clone(); mesh.material = material;
      clones.push({ mesh, original, material });
      material.onBeforeCompile = shader => {
        Object.assign(shader.uniforms, uniforms);
        pages.banks.forEach((t, b) => { shader.uniforms[`glowBank${b}`] = { value: t }; });
        shader.vertexShader = 'attribute float glowRoom; attribute vec2 glowUV; varying float vGlowRoom; varying vec2 vGlowUV;\n' + shader.vertexShader;
        shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>
vGlowRoom = glowRoom; vGlowUV = glowUV;`);
        shader.fragmentShader = `uniform sampler2D lmTints; uniform sampler2D lmRegions;
varying float vGlowRoom; varying vec2 vGlowUV;
${pages.banks.map((t, b) => `uniform highp sampler2DArray glowBank${b};`).join('\n')}
` + shader.fragmentShader;
        const sum = pages.banks.map((t, b) => `
vec4 region${b} = texelFetch(lmRegions, ivec2(${b}, int(vGlowRoom + 0.5)), 0);
vec4 value${b} = texture(glowBank${b}, vec3(vGlowUV + region${b}.xy, region${b}.z));
vec3 tint${b}a = texelFetch(lmTints, ivec2(${2*b}, int(vGlowRoom + 0.5)), 0).rgb;
vec3 tint${b}b = texelFetch(lmTints, ivec2(${2*b+1}, int(vGlowRoom + 0.5)), 0).rgb;
totalEmissiveRadiance += (value${b}.r * tint${b}a + value${b}.${lightSwizzle(t.format)[1]} * tint${b}b) * 8.0;
`).join('\n');
        shader.fragmentShader = shader.fragmentShader.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
if (vGlowRoom > -0.5) { ${sum} }`);
      };
      material.customProgramCacheKey = () => `twin-window-glow-2-${pages.banks.map(t => lightSwizzle(t.format)).join(',')}`;
    });
  }
  async function readManifest() {
    const r = await api(`api/house/bakes/${atlas.key}`); return r.ok ? r.json() : null;
  }
  async function loadPages() {
    if (!valid()) return;
    const m = await readManifest(); if (!valid()) return;
    if (!m) {
      for (const id of fresh) light(id, [0, 0, 0], 0);
      fresh.clear(); skyReady = false; stale = lights.map(l => l.device); view.bakeSky?.();
      return;
    }
    const success = new Set(), results = new Map();
    const wanted = new Set(Array.from({ length: atlas.sky.pages }, (_, p) => p));
    layers.forEach((list, i) => list.forEach(p => wanted.add(packed.offsets[i] + p)));
    for (const p of [...wanted].sort((a, c) => a - c)) {
      const entry = cache.get(p);
      const r = await api(`api/house/bakes/${atlas.key}/${p}.png`, { headers: entry?.etag ? { 'If-None-Match': entry.etag } : {} });
      if (!valid()) return;
      try {
        let data;
        if (r.status === 304) data = entry?.data;
        else if (r.ok) {
          const format = p < atlas.sky.pages ? pages.sky.format : pages.banks[0]?.format;
          data = await codec.transcode(new Uint8Array(await r.arrayBuffer()), format);
          cache.set(p, { etag: r.headers.get('etag'), data });
        }
        if (data) { success.add(p); results.set(p, data); }
      } catch { /* A missing or damaged page keeps its lights real-time. */ }
    }
    if (!valid()) return;
    const put = (texture, offset, count, size) => {
      const t = arrayTexture(Array.from({ length: count }, (_, p) => results.get(offset + p)), count, texture.format, size);
      if (t) replaceTexture(texture, t);
    };
    put(pages.sky, 0, atlas.sky.pages, layout.sky.page);
    packed.banks.forEach((b, i) => {
      if (!layers[i].length) return;
      const t = arrayTexture(layers[i].map(p => results.get(packed.offsets[i] + p)), layers[i].length, pages.banks[i].format, layout.room.page);
      if (t) replaceTexture(pages.banks[i], t);
    });
    const previous = [...fresh]; fresh.clear();
    for (const l of lights) {
      const e = packed.entries[l.device], stored = m.lights[l.device];
      if (e && stored?.key === e.key && stored.page === e.page && stored.channel === e.channel && success.has(e.page)) fresh.add(l.device);
    }
    stale = lights.filter(l => !fresh.has(l.device)).map(l => l.device);
    skyReady = Array.from({ length: atlas.sky.pages }, (_, p) => p).every(p => success.has(p));
    if (success.size) patch();
    for (const id of previous) if (!fresh.has(id)) light(id, [0, 0, 0], 0);
    for (const [id, tint] of tints) light(id, tint.rgb, tint.intensity);
    view.bakeSky?.();
    // Refresh the pool selection as soon as a light becomes fresh.
    if (view.live) await view.live.refresh();
    view.render();
  }
  async function run(force = false) {
    if (!allowed || !valid() || !atlas) return;
    if (running) { pendingForce ||= force; return; }
    failure = ''; progress = { done: 0, total: force ? lights.length : stale.length };
    running = true; showProgress();
    try {
      baker = createBaker(view, { renderer: view.renderer3, atlas, layout, lights, api, codec, force });
      stale = await baker.staleLights(); progress = baker.progress(); showProgress();
      while (valid()) {
        await idle();
        const id = await baker.bakeNext(); if (!id || !valid()) break;
        baked.push(id); progress = baker.progress(); stale = await baker.staleLights(); showProgress();
        await loadPages();
      }
    } catch (error) {
      if (valid()) failure = 'Could not bake lighting. Try Bake lighting now.';
    } finally {
      running = false; progress = { done: 0, total: 0 }; showProgress();
      if (valid() && pendingForce) { pendingForce = false; run(true); }
    }
  }
  const controller = {
    state: () => ({ key: atlas?.key || null, baking: running, paused: running && paused(),
      ...progress, baked: [...baked], stale: [...stale] }),
    fresh: () => valid() ? [...fresh] : [], light, sky: skyTint, idle,
    // The lightmap arrays as held: per array its layer size and layer count.
    held: () => pages ? { sky: { size: pages.sky.image.width, layers: pages.sky.image.depth },
      banks: pages.banks.map((t, i) => ({ size: t.image.width, layers: t.image.depth, pages: packed.banks[i].pages, lit: [...layers[i]] })) } : null,
    now: () => run(true),
    stop() {
      if (stopped) return;
      stopped = true; baker?.cancel(); halt.abort(); clearTimeout(timer); codec?.stop(); strip?.remove();
      controls.removeEventListener('start', moved); controls.removeEventListener('change', moved); controls.removeEventListener('end', moved);
      for (const { mesh, original, material } of clones) { if (mesh.material === material) mesh.material = original; material.dispose(); }
      for (const t of textures) t.dispose();
      if (uniforms) { uniforms.lmTints.value.dispose(); uniforms.lmRegions.value.dispose(); }
    },
  };
  view.bake = controller;
  (async () => {
    try {
      // A desktop writes 8 texels/ft. Probe that shared layout on every tier,
      // then use the tier default only when there is no stored bake.
      const original = covered(root).map(m => geometryData(m.geometry));
      if (!original.length) return;
      atlas = await loadAtlas(root, round, layout, { signal: halt.signal });
      if (!valid()) return;
      let manifest = await readManifest();
      if (!manifest && !['high', 'max'].includes(view.tier)) {
        covered(root).forEach((m, i) => { m.geometry.dispose(); m.geometry = geometryFrom(original[i]); });
        layout = options(4); atlas = await loadAtlas(root, round, layout, { signal: halt.signal }); manifest = await readManifest();
      }
      if (!valid()) return;
      if (manifest?.densities && (manifest.densities.sky !== layout.sky.density || manifest.densities.room !== layout.room.density)) {
        layout = { sky: { ...layout.sky, density: manifest.densities.sky }, room: { ...layout.room, density: manifest.densities.room } };
        covered(root).forEach((m, i) => { m.geometry.dispose(); m.geometry = geometryFrom(original[i]); });
        atlas = await loadAtlas(root, round, layout, { signal: halt.signal });
      }
      const response = await api('api/house/live'); const liveLayout = response.ok ? await response.json() : null;
      if (!valid()) return;
      lights = (liveLayout?.markers || []).filter(m => m.kind === 'light' && m.placed && m.at && m.room)
        .map(m => ({ device: m.device_id, building: m.building, level: m.level, room: m.room, at: [...m.at] }));
      packed = bakeLayout(atlas, layout, lights);
      // A bank page no placed light writes to (bank zero reserves unlit rooms,
      // Ruling B12) is never fetched or held on the GPU: each bank's array keeps
      // only its lit pages, and lmRegions maps a page to its layer.
      layers = packed.banks.map((b, i) => [...new Set(Object.values(packed.entries).map(e => e.page - packed.offsets[i])
        .filter(p => p >= 0 && p < b.pages))].sort((a, c) => a - c));
      uniforms = lightmapUniforms(atlas.room.rooms.length, Math.max(2, packed.banks.length * 2));
      uniforms.lmRegions = { value: regions() };
      const skyFormat = pickTranscode(view.renderer3.extensions, 1), roomFormat = pickTranscode(view.renderer3.extensions, 2);
      pages = { sky: blankArray(atlas.sky.pages, skyFormat, layout.sky.page),
        // A bank with no lit page holds one 4x4 placeholder layer (one compressed block).
        banks: packed.banks.map((b, i) => layers[i].length ? blankArray(layers[i].length, roomFormat, layout.room.page)
          : blankArray(1, roomFormat, 4)) };
      textures.add(pages.sky); pages.banks.forEach(t => textures.add(t));
      codec = workerCodec();
      await loadPages(); if (!valid()) return;
      showProgress();
      if (allowed) run();
      // Panels and other tabs pick up pages as another desktop publishes them.
      const poll = async () => {
        if (!valid()) return;
        try { if (!running) await loadPages(); } catch { /* offline: retain the last complete page */ }
        if (valid()) timer = setTimeout(poll, 10000);
      };
      timer = setTimeout(poll, 10000);
    } catch { /* Worker/storage failure keeps v2.499.783's real-time lighting. */ }
  })();
  return controller;
}
