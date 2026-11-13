import * as THREE from 'three';
import { base } from '../twin_library.js';
import { contains, FT } from '../twin_generator.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { loadAtlas, lightmapUniforms, applyChartIndices, chartLightmapUniforms, chartLookupGLSL, patchLightmaps, setLightTint, pickTranscode, lightSwizzle } from './lightmap_material.js';
import { createBaker, bakeLayout } from './baker.js';
import { mayBake } from './bake_lock.js';
import { workerCodec } from './worker_codec.js';
import { covered } from './atlas_transport.js';
import { sameSlots } from './slots.js';

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
// Every tier lays its atlas out at the desk's 8 texels/ft, so a wall that opens before
// any bake polls the very key the desk will bake (I1).
const options = density => ({ room: { density, page: 2048, gutter: 2 } });

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
// One page into its layer of an array texture, in place: only that layer uploads (I2).
// The texture's own mip arrays are the one CPU copy; no transcoded page is kept.
function writeLayer(texture, layer, page) {
  const depth = texture.image.depth;
  texture.mipmaps.forEach((mip, level) => {
    const per = mip.data.length / depth, src = page?.mipmaps[level];
    if (src && src.data.length !== per) throw new Error('A lightmap page does not fit its array.');
    if (src) mip.data.set(src.data, per * layer); else mip.data.fill(0, per * layer, per * (layer + 1));
  });
  texture.addLayerUpdate(layer); texture.needsUpdate = true;
}
// Baked light lands on indoor surfaces only. Yard and fire-pit lights (no building) light the
// lot through the live pool; baking them never completes and kept the bake from settling.
export const lightsOf = layout => (layout?.markers || []).filter(m => m.kind === 'light' && m.placed && m.at && m.room && m.building)
  .map(m => ({ device: m.device_id, building: m.building, level: m.level, room: m.room, at: [...m.at] }));

export function mountBake(view, root, { host, controls = view.controls, layout: requestedLayout, poll: pollMs = 10000,
  api = (path, init) => fetch(base() + path, init) } = {}) {
  const round = view.plan, halt = new AbortController(), baked = [], fresh = new Set(), tints = new Map();
  const query = new URLSearchParams(location.search);
  // Only a parent's High or Max desk bakes (the lease is PARENTS: a child is refused, M4).
  const canBake = ['high', 'max'].includes(view.tier) && !query.has('panel') && !query.has('kiosk');
  const owner = [...globalThis.crypto.getRandomValues(new Uint32Array(4))].map(x => x.toString(16)).join('');
  let stopped = false, allowed = false, atlas = null, pending = null, layout = requestedLayout || options(8);
  let lights = [], lightsKey = '', packed = null, uniforms = null, pages = null;
  let layers = [], baker = null, codec = null, running = false, pendingForce = false, pendingRun = false;
  let dragging = false, stillAt = performance.now();
  let progress = { done: 0, total: 0 }, stale = [], timer = null, patched = false;
  let failure = '', errorReason = null, manifestText = null;
  function reportError(error) {
    if (!valid()) return;
    errorReason=error?.message || String(error);
    // Say why, so a failure can be reported and fixed (user, 2026-11-13).
    failure=`Could not bake lighting (${errorReason}). Try Bake lighting now.`;
    console.error('House lighting bake failed:', error);
    showProgress();
  }
  const etags = new Map(), present = new Set(), clones = [], textures = new Set();
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
  function showControls() {
    if (!allowed || !host || strip) return;
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
  function light(device, rgb, intensity) {
    tints.set(device, { rgb: [...rgb], intensity });
    const s = packed?.slots[device];
    if (s && uniforms) {
      if (uniforms.lmChartMode) setLightTint(uniforms, 0, lights.findIndex(l => l.device === device), rgb, fresh.has(device) ? intensity : 0);
      else for (const room of s.receivers || [s.room])
        setLightTint(uniforms, room, s.bank * 2 + s.channel, rgb, fresh.has(device) ? intensity : 0);
    }
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
      view.prepareViewingMaterial?.(original, material);
      m.material = material; clones.push({ mesh: m, original, material }); materials.add(material);
    }
    patchLightmaps([...materials], pages, uniforms);
    patchWindows();
  }
  function unpatch() {
    for (const { mesh, original, material } of clones) { if (mesh.material === material) mesh.material = original; material.dispose(); }
    clones.length = 0; patched = false;
  }
  function patchWindows() {
    // Charts by room, and each chart mesh's inverse matrix once (M2).
    const byRoom = new Map(), inverse = new Map();
    for (const chart of atlas.room.charts) {
      if (!byRoom.has(chart.room)) byRoom.set(chart.room, []);
      byRoom.get(chart.room).push(chart);
    }
    const invert = mesh => {
      let m = inverse.get(mesh);
      if (!m) { m = mesh.matrixWorld.clone().invert(); inverse.set(mesh, m); }
      return m;
    };
    const triangle = new THREE.Triangle(), point = new THREE.Vector3(), bary = new THREE.Vector3();
    const normal = new THREE.Vector3(), local = new THREE.Vector3();
    function windowSample(centre, room, paneNormal) {
      if (room < 0) return null;
      let closest = Infinity, uv = null, chartId = -1;
      for (const chart of byRoom.get(room) || []) {
        const g = chart.mesh.geometry, pos = g.attributes.position, tex = g.attributes.uv3;
        local.copy(centre).applyMatrix4(invert(chart.mesh));
        for (const face of chart.faces) {
          const index = face * 3;
          triangle.a.fromBufferAttribute(pos, index); triangle.b.fromBufferAttribute(pos, index + 1); triangle.c.fromBufferAttribute(pos, index + 2);
          // Prefer the inside wall around the pane over its thin side reveal.
          triangle.getNormal(normal).transformDirection(chart.mesh.matrixWorld);
          if (Math.abs(normal.dot(paneNormal)) < .7) continue;
          triangle.closestPointToPoint(local, point);
          const distance = point.distanceToSquared(local);
          if (distance >= closest) continue;
          closest = distance; triangle.getBarycoord(point, bary);
          chartId = chart.id;
          uv = [0, 1].map(k => bary.x * tex.array[index * 2 + k] +
            bary.y * tex.array[(index + 1) * 2 + k] + bary.z * tex.array[(index + 2) * 2 + k]);
        }
      }
      return uv ? {uv, chartId} : null;
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
      const centre = new THREE.Vector3(), paneNormal = new THREE.Vector3(), pane = new THREE.Triangle();
      for (let i = 0; i < pos.count; i += 3) {
        centre.set(0, 0, 0);
        for (let k = 0; k < 3; k++) centre.add(p.fromBufferAttribute(pos, i + k));
        centre.multiplyScalar(1 / 3).applyMatrix4(mesh.matrixWorld);
        const dx = centre.x / FT - (building.position?.[0] || 0), dy = -centre.z / FT - (building.position?.[1] || 0);
        const x = Math.cos(angle) * dx - Math.sin(angle) * dy, y = Math.sin(angle) * dx + Math.cos(angle) * dy;
        const height = centre.y / FT - (building.base || 0) - buildingGround(round, building);
        const room = building.rooms.find(r => {
          const level = building.levels.find(l => l.id === r.level);
          return level && height >= level.elevation + (r.floor_offset_ft || 0) && height <= level.elevation + level.ceiling &&
            [[0, 0], [.5, 0], [-.5, 0], [0, .5], [0, -.5]].some(([a, b]) => contains(r.polygon, [x + a, y + b]));
        });
        const owner = atlas.room.rooms.findIndex(r => r.building === buildingId && r.id === room?.id);
        pane.a.fromBufferAttribute(pos, i); pane.b.fromBufferAttribute(pos, i + 1); pane.c.fromBufferAttribute(pos, i + 2);
        pane.getNormal(paneNormal).transformDirection(mesh.matrixWorld);
        const sample = windowSample(centre, owner, paneNormal);
        if (sample) {
          owners.fill(uniforms.lmChartMode ? sample.chartId : owner, i, i + 3);
          for (let k = 0; k < 3; k++) glowUV.set(sample.uv, (i + k) * 2);
        }
      }
      mesh.geometry.setAttribute('glowRoom', new THREE.BufferAttribute(owners, 1));
      mesh.geometry.setAttribute('glowUV', new THREE.BufferAttribute(glowUV, 2));
      const original = mesh.material, material = original.clone(); mesh.material = material;
      view.prepareViewingMaterial?.(original, material);
      clones.push({ mesh, original, material });
      const banks = pages.banks;
      material.onBeforeCompile = shader => {
        Object.assign(shader.uniforms, uniforms);
        banks.forEach((t, b) => { shader.uniforms[`glowBank${b}`] = { value: t }; });
        shader.vertexShader = 'attribute float glowRoom; attribute vec2 glowUV; varying float vGlowRoom; varying vec2 vGlowUV;\n' + shader.vertexShader;
        shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>
vGlowRoom = glowRoom; vGlowUV = glowUV;`);
        shader.fragmentShader = `uniform sampler2D lmTints; uniform sampler2D lmRegions;
varying float vGlowRoom; varying vec2 vGlowUV;
${banks.map((t, b) => `uniform highp sampler2DArray glowBank${b};`).join('\n')}
${uniforms.lmChartMode ? chartLookupGLSL(banks.length) : ''}
` + shader.fragmentShader;
        const sum = banks.map((t, b) => `
vec4 region${b} = texelFetch(lmRegions, ${uniforms.lmChartMode ? `lmAddress(${b}, int(vGlowRoom + 0.5))` : `ivec2(${b}, int(vGlowRoom + 0.5))`}, 0);
vec4 value${b} = textureLod(glowBank${b}, vec3(vGlowUV + region${b}.xy, region${b}.z), 0.0);
vec3 tint${b}a = ${uniforms.lmChartMode ? `lmOwnerTint(mod(region${b}.w, 4096.0))` : `texelFetch(lmTints, ivec2(${2*b}, int(vGlowRoom + 0.5)), 0).rgb`};
vec3 tint${b}b = ${uniforms.lmChartMode ? `lmOwnerTint(floor(region${b}.w / 4096.0))` : `texelFetch(lmTints, ivec2(${2*b+1}, int(vGlowRoom + 0.5)), 0).rgb`};
totalEmissiveRadiance += (value${b}.r * tint${b}a + value${b}.${lightSwizzle(t.format)[1]} * tint${b}b) * 8.0;
`).join('\n');
        shader.fragmentShader = shader.fragmentShader.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
if (vGlowRoom > -0.5) { ${sum} }`);
      };
      material.customProgramCacheKey = () => `twin-window-glow-4-${banks.map(t => lightSwizzle(t.format)).join(',')}`;
    });
  }
  // The light list's layout: banks, layers, tints and the blank arrays it draws from.
  function prepare(list, history = packed?.ownership) {
    unpatch();
    for (const t of textures) t.dispose();
    textures.clear();
    if (uniforms) { uniforms.lmTints.value.dispose(); uniforms.lmRegions.value.dispose(); }
    lights = list; lightsKey = JSON.stringify(list);
    packed = bakeLayout(atlas, layout, lights, history);
    if (packed.banks.some(b => b.chartPacking)) applyChartIndices(atlas);
    // A bank page no placed light writes to (bank zero reserves unlit rooms,
    // Ruling B12) is never fetched or held on the GPU: each bank's array keeps
    // only its lit pages, and lmRegions maps a page to its layer.
    layers = packed.banks.map((b, i) => [...new Set(Object.values(packed.entries).flatMap(e => e.pages || [e.page]).map(p => p - packed.offsets[i])
      .filter(p => p >= 0 && p < b.pages))].sort((a, c) => a - c));
    uniforms = packed.banks.some(b => b.chartPacking)
      ? chartLightmapUniforms(atlas.room.charts.length, packed, lights, layout.room.page, layers)
      : lightmapUniforms(atlas.room.rooms.length, Math.max(2, packed.banks.length * 2));
    if (!uniforms.lmRegions) uniforms.lmRegions = { value: regions() };
    const roomFormat = pickTranscode(view.renderer3.extensions, 2);
    pages = {
      // A bank with no lit page holds one 4x4 placeholder layer (one compressed block).
      banks: packed.banks.map((b, i) => layers[i].length ? blankArray(layers[i].length, roomFormat, layout.room.page)
        : blankArray(1, roomFormat, 4)) };
    pages.banks.forEach(t => textures.add(t));
    etags.clear(); present.clear(); manifestText = null; fresh.clear();
    stale = lights.map(l => l.device);
    for (const [id, tint] of tints) light(id, tint.rgb, tint.intensity);
  }
  function locate(p) {
    for (let i = 0; i < layers.length; i++) {
      const layer = layers[i].indexOf(p - packed.offsets[i]);
      if (layer >= 0) return { texture: pages.banks[i], layer };
    }
    return null;
  }
  // null: no bake for this key (404); undefined: the server could not say (keep what is drawn).
  async function readManifest(key) {
    const r = await api(`api/house/bakes/${key}`);
    if (r.status === 404) return null;
    if (!r.ok) return undefined;
    return r.text();
  }
  async function loadPages() {
    if (!valid() || !pages) return;
    const text = await readManifest(atlas.key); if (!valid() || text === undefined) return;
    if (text === null) {
      if (manifestText === null && !present.size && !fresh.size) return;
      for (const id of fresh) light(id, [0, 0, 0], 0);
      for (const p of present) { const at = locate(p); if (at) writeLayer(at.texture, at.layer, null); }
      fresh.clear(); present.clear(); etags.clear(); manifestText = null;
      stale = lights.map(l => l.device); view.render();
      return;
    }
    const m = JSON.parse(text);
    // A reopened panel or another desk's publication adopts the persisted
    // channels. Never reset survivors to a fresh assignment on reload/poll.
    if(m.ownership && text!==manifestText && !sameSlots(m.ownership,packed.ownership)) {
      const next=bakeLayout(atlas,layout,lights,m.ownership);
      if(!sameSlots(next.ownership,packed.ownership)) prepare(lights,m.ownership);
    }
    let changed = text !== manifestText;
    manifestText = text;
    const wanted = new Set();
    layers.forEach((list, i) => list.forEach(p => wanted.add(packed.offsets[i] + p)));
    for (const p of [...wanted].sort((a, c) => a - c)) {
      const etag = etags.get(p), at = locate(p);
      const r = await api(`api/house/bakes/${atlas.key}/${p}.png`, { headers: etag ? { 'If-None-Match': etag } : {} });
      if (!valid()) return;
      if (r.status === 304) continue;
      if (r.status === 404) {
        if (present.has(p)) { writeLayer(at.texture, at.layer, null); present.delete(p); changed = true; }
        etags.delete(p); continue;
      }
      if (!r.ok) continue;     // offline: keep the last complete page
      try {
        const data = await codec.transcode(new Uint8Array(await r.arrayBuffer()), at.texture.format);
        if (!valid()) return;
        writeLayer(at.texture, at.layer, data); present.add(p); etags.set(p, r.headers.get('etag')); changed = true;
      } catch {
        // A damaged page keeps its lights real-time.
        if (present.has(p)) { writeLayer(at.texture, at.layer, null); present.delete(p); changed = true; }
        etags.delete(p);
      }
    }
    // An unchanged manifest and every page 304: nothing to rebuild, upload or redraw (I2).
    if (!changed || !valid()) return;
    const previous = [...fresh]; fresh.clear();
    for (const l of lights) {
      const e = packed.entries[l.device], stored = m.lights[l.device];
      if (e && stored?.key === e.key && stored.location === e.location && stored.channel === e.channel &&
        JSON.stringify(stored.pages) === JSON.stringify(e.pages) && e.pages.every(p => present.has(p))) fresh.add(l.device);
    }
    stale = lights.filter(l => !fresh.has(l.device)).map(l => l.device);
    if (present.size) patch();
    for (const id of previous) if (!fresh.has(id)) light(id, [0, 0, 0], 0);
    for (const [id, tint] of tints) light(id, tint.rgb, tint.intensity);

    // Refresh the pool selection as soon as a light becomes fresh.
    if (view.live) await view.live.refresh();
    view.render();
  }
  // M3: a light placed or moved while the view is open follows the live layer's layout.
  async function relight() {
    const layoutNow = view.live?.layout?.();
    if (!layoutNow || !atlas) return;
    const next = lightsOf(layoutNow);
    if (JSON.stringify(next) === lightsKey) return;
    if (running) { pendingRun = true; baker?.cancel(); }
    const text=await readManifest(atlas.key);if(!valid())return;
    prepare(next,typeof text==='string'?JSON.parse(text).ownership || packed?.ownership:packed?.ownership);
    await loadPages();
    if (allowed && !running) run();
  }
  async function run(force = false) {
    if (!allowed || !valid() || !atlas) return;
    if (running) { pendingForce ||= force; return; }
    failure = ''; errorReason = null; progress = { done: 0, total: force ? lights.length : stale.length };
    running = true; showProgress();
    const mine = lightsKey;
    try {
      baker = createBaker(view, { renderer: view.renderer3, atlas, layout, lights, api, codec, force, owner });
      stale = await baker.staleLights(); progress = baker.progress(); showProgress();
      while (valid() && mine === lightsKey) {
        await idle();
        const id = await baker.bakeNext(); if (!id || !valid() || mine !== lightsKey) break;
        baked.push(id); progress = baker.progress(); stale = await baker.staleLights(); showProgress();
        await loadPages();
      }
      // Tell the editor's chip this round's lights are whole (Ruling B15).
      if (valid() && mine === lightsKey && !(await baker.staleLights()).length) await baker.settle();
    } catch (error) {
      reportError(error);
    } finally {
      running = false; progress = { done: 0, total: 0 }; showProgress();
      if (valid() && (pendingForce || pendingRun)) { const f = pendingForce; pendingForce = pendingRun = false; run(f); }
    }
  }
  async function begin(text) {
    atlas = pending.apply(); pending = null;
    codec = workerCodec();
    prepare(lights,typeof text==='string'?JSON.parse(text).ownership:undefined);
    await loadPages(); if (!valid()) return;
    showProgress();
    if (allowed) run();
  }
  async function refresh() {
    if (!valid()) return;
    if (pending) {
      // A wall that opened before any bake applies the atlas when one lands (I1, M1).
      const text = await readManifest(pending.key);
      if (typeof text === 'string' && valid() && pending) await begin(text);
      return;
    }
    if (!atlas) return;
    await relight();
    if (!running) await loadPages();
  }
  const controller = {
    state: () => ({ key: atlas?.key || pending?.key || null, baking: running, paused: running && paused(),
      ...progress, baked: [...baked], stale: [...stale], error: errorReason }),
    fresh: () => valid() ? [...fresh] : [], light, idle, refresh,
    // The lightmap arrays as held: per array its layer size and layer count, plus what
    // the GPU has been told to upload (test hooks).
    held: () => pages ? {
      banks: pages.banks.map((t, i) => ({ size: t.image.width, layers: t.image.depth, pages: packed.banks[i].pages, lit: [...layers[i]] })),
      versions: { banks: pages.banks.map(t => t.version) },
      ids: { banks: pages.banks.map(t => t.uuid) },
      updates: { banks: pages.banks.map(t => [...t.layerUpdates]) },
      textures: { banks: [...pages.banks] } } : null,
    now: () => run(true),
    stop() {
      if (stopped) return;
      stopped = true; baker?.cancel(); halt.abort(); clearTimeout(timer); codec?.stop(); strip?.remove();
      controls.removeEventListener('start', moved); controls.removeEventListener('change', moved); controls.removeEventListener('end', moved);
      unpatch();
      for (const t of textures) t.dispose();
      if (uniforms) { uniforms.lmTints.value.dispose(); uniforms.lmRegions.value.dispose(); }
    },
  };
  view.bake = controller;
  (async () => {
    try {
      if (!covered(root).length) return;
      const response = await api('api/house/live'); const liveLayout = response.ok ? await response.json() : null;
      if (!valid()) return;
      lights = lightsOf(liveLayout);
      // The worker lays the atlas out; it is applied to the meshes only once a bake
      // exists or this desk will make one (M1).
      pending = await loadAtlas(root, round, layout, { signal: halt.signal, apply: false });
      if (!valid()) return;
      let text = await readManifest(pending.key);
      const manifest = typeof text === 'string' ? JSON.parse(text) : null;
      if (manifest?.densities && (manifest.densities.room !== layout.room.density)) {
        layout = { room: { ...layout.room, density: manifest.densities.room } };
        pending = await loadAtlas(root, round, layout, { signal: halt.signal, apply: false });
        if (!valid()) return;
        text = await readManifest(pending.key);
      }
      allowed = canBake && await mayBake(api, `api/house/bakes/${pending.key}`, owner);
      if (!valid()) return;
      showControls();
      if (typeof text === 'string' || allowed) await begin(text);
      if (!valid()) return;
      // Panels and other tabs pick up pages as another desktop publishes them.
      const tick = async () => {
        if (!valid()) return;
        try { await refresh(); } catch { /* offline: retain the last complete page */ }
        if (valid()) timer = setTimeout(tick, pollMs);
      };
      if (pollMs > 0) timer = setTimeout(tick, pollMs);
    } catch (error) { reportError(error); }
  })();
  return controller;
}
