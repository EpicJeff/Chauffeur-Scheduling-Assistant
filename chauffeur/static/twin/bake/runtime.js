import * as THREE from 'three';
import { base, copyMaterialParams } from '../twin_library.js';
import { contains, FT } from '../twin_generator.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { loadAtlas, lightmapUniforms, applyChartIndices, chartLightmapUniforms, patchLightmaps, setLightTintColor, tintSum, pickTranscode,
  setLightSource, setChartFill, setRoomFill, clearFills, roomRegions, patchWindowGlow, needsFixtureShader, bankLayerBases } from './lightmap_material.js';
import { lightSource } from './reach.js';
import { resolveEmitters, emitterSignature, lightMarkers } from '../live/emitters.js';
import { kindOf, exactRects } from './fixture_terms.js';
import { createBaker, bakeLayout } from './baker.js';
import { mayBake } from './bake_lock.js';
import { workerCodec } from './worker_codec.js';
import { covered } from './atlas_transport.js';
import { sameSlots } from './slots.js';
import { invalidateMaterialReach } from './reach.js';
import { releaseBakeSource } from './source.js';

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
// Every placed light bakes, on or off, indoors or in a yard room (user, 2026-11-13: "It seems
// silly to have some lights baked and some not"), including a light entity on another kind of
// device, such as a camera's spotlight (lightMarkers, 2026-11-20). A yard-room light has no
// building; its z is height above the ground.
export const lightsOf = layout => lightMarkers(layout).filter(m => m.placed && m.at && m.room && (m.building || m.yard))
  .map(m => ({ device: m.device_id, building: m.building || null, level: m.level || null, room: m.room, at: [...m.at],
    ...(m.building ? {} : { yard: true }) }));

// Object lamps (fire pits, lamp furniture) as live modes.js makes them: 'object:<id>', at the
// fire's light point or the lamp's top, 18 ft reach. A light-domain pit also owns its marker's
// light (modes.js moves that lamp to the fire); a lamp object with a marker is that marker.
export function objectLightsOf(root, layout) {
  const markers = lightMarkers(layout);
  const rows = new Map();
  root.updateMatrixWorld(true);
  root.traverse(mesh => {
    for (const material of mesh.material ? [].concat(mesh.material) : []) {
      const object = material.userData?.objectLight;
      if (!object) continue;
      if (!rows.has(object.id)) rows.set(object.id, { object, box: new THREE.Box3(), fire: null });
      const row = rows.get(object.id); row.box.expandByObject(mesh);
      if (object.fireLightAt) row.fire = mesh.parent.localToWorld(new THREE.Vector3(...object.fireLightAt));
    }
  });
  const lights = [], replaced = new Set();
  for (const { object, box, fire } of rows.values()) {
    const owner = object.entity && markers.find(m => m.entity_id === object.entity);
    if (owner && !object.fire) continue;
    if (owner) replaced.add(owner.device_id);
    const p = fire || box.getCenter(new THREE.Vector3()); if (!fire) p.y = box.max.y + .05;
    lights.push({ device: 'object:' + object.id, building: null, level: null, room: null,
      at: [p.x / FT, -p.z / FT, p.y / FT], absolute: true, range: 18 });
  }
  return { lights, replaced };
}
// Plain marker lights at one spot (a recessed main and its trim ring, a camera spotlight and a
// stale twin entity) see exactly the same geometry: a channel stores visibility only, falloff
// and colour are per pixel. They share one channel and the slot's tint is their sum (owner
// 2026-11-21), so a trim ring no longer takes channels from its main. A lone light keeps its
// own id, so a house without co-located lights keeps every manifest entry it has.
export const SHARED_PREFIX = 'shared:';
export function shareColocated(lights) {
  const spot = l => !l.emitters && !l.absolute && Array.isArray(l.at)
    ? JSON.stringify([l.building, l.level, l.room, !!l.yard, ...l.at.map(v => Math.round(v * 1000))]) : null;
  const groups = new Map(), out = [];
  for (const l of lights) {
    const key = spot(l);
    if (key === null) { out.push(l); continue; }
    if (!groups.has(key)) { groups.set(key, []); out.push(key); }
    groups.get(key).push(l);
  }
  return out.map(item => {
    if (typeof item !== 'string') return item;
    const list = groups.get(item);
    if (list.length === 1) return list[0];
    const members = list.map(l => l.device).sort();
    return {...list[0], device: SHARED_PREFIX + members.join('+'), members};
  });
}
export function bakeLights(layout, root, plan = {}) {
  return shareColocated(separateLights(layout, root, plan));
}
function separateLights(layout, root, plan = {}) {
  const groups = new Map();
  for (const e of resolveEmitters(layout || {}, {}, plan)) {
    if (e.legacy) continue;
    if (!groups.has(e.entity_id)) groups.set(e.entity_id, []);
    groups.get(e.entity_id).push(e);
  }
  for (const emitters of groups.values()) emitters.sort((a,b) => a.fixture_id < b.fixture_id ? -1 : a.fixture_id > b.fixture_id ? 1 : 0);
  const fixtures = [...groups].map(([entity, emitters]) => ({device: entity, entity, emitters,
    kind: kindOf(emitters), signature: emitterSignature(emitters), at: [...(emitters[0].at || emitters[0].path[0])],
    building: emitters[0].building || null, level: emitters[0].level || null, room: emitters[0].room || null}));
  const objects = root ? objectLightsOf(root, layout) : { lights: [], replaced: new Set() };
  const replaced = new Set(lightMarkers(layout).filter(m => groups.has(m.entity_id)).map(m => m.device_id));
  const pitIds = new Set([...groups.values()].flat().filter(e => e.fire_pit).map(e => e.device_id));
  return [...lightsOf(layout).filter(l => !objects.replaced.has(l.device) && !replaced.has(l.device)),
    ...objects.lights.filter(l => !pitIds.has(l.device)), ...fixtures];
}

export function mountBake(view, root, { host, controls = view.controls, layout: requestedLayout, poll: pollMs = 10000,
  api: request = (path, init) => fetch(base() + path, init) } = {}) {
  let retained = view.bake?.snapshot?.();
  // A fetch that rejects is the network being away, which the poll rides out in silence.
  const offline = new WeakSet();
  const api = async (path, init) => {
    try { return await request(path, init); }
    catch (error) { if (error instanceof TypeError) offline.add(error); throw error; }
  };
  const round = view.plan, halt = new AbortController(), baked = [], fresh = new Set(), tints = new Map();
  const query = new URLSearchParams(location.search);
  // Only a parent's High or Max desk bakes (the lease is PARENTS: a child is refused, M4).
  const canBake = ['high', 'max'].includes(view.tier) && !query.has('panel') && !query.has('kiosk');
  const owner = [...globalThis.crypto.getRandomValues(new Uint32Array(4))].map(x => x.toString(16)).join('');
  let stopped = false, allowed = false, atlas = null, pending = null, layout = requestedLayout || options(8);
  let lights = [], lightsKey = '', packed = null, uniforms = null, pages = null;
  let layers = [], bankBase = [], layerOverflow = false, baker = null, codec = null, running = false, pendingForce = false, pendingRun = false;
  let dragging = false, stillAt = performance.now(), generation = 0;
  let progress = { done: 0, total: 0 }, stale = [], timer = null, patched = false;
  let failure = '', errorReason = null, manifestText = null, initialized = false, mounting = null;
  function reportError(error) {
    if (!valid()) return;
    errorReason=error?.message || String(error);
    // Say why, so a failure can be reported and fixed (user, 2026-11-13).
    failure=`Could not bake lighting (${errorReason}). Try Bake lighting now.`;
    console.error('House lighting bake failed:', error);
    showProgress();
  }
  const pageErrors = new Map(), etags = new Map(), present = new Set(), clones = [], textures = new Set();
  const preservePages = new Set();
  let pageManifest = null;
  const pageSignature = (m,p) => JSON.stringify(Object.entries(m?.lights || {}).filter(([,e])=>(e.pages || [e.page]).includes(p))
    .map(([id,e])=>[id,e.key,e.location,e.channel,e.scale]).sort((a,b)=>a[0].localeCompare(b[0])));
  const pageReason = () => pageErrors.values().next().value || null;
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
    const message = failure || (pageReason() ? `Could not read baked lighting (${pageReason()}).` : '');
    status.hidden = !(running && progress.total) && !message;
    status.textContent = message || (running && progress.total ? `Baking lights ${Math.min(progress.total, progress.done + 1)} of ${progress.total}` : '');
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
  // A member of a shared channel (shareColocated) is driven by its own id; its slot is the group's.
  const groupOf = id => lights.find(l => l.members?.includes(id));
  function light(device, rgb, intensity) {
    // A shared slot's own id (the runtime clearing or replaying a slot) recomputes from its
    // members; it never stores a tint that would later overwrite their sum.
    const own = lights.find(l => l.device === device && l.members);
    if (!own) {
      const previous = tints.get(device);
      if (!previous || previous.intensity !== intensity || previous.rgb.some((v,i) => v !== rgb[i])) view.reflectionsChanged?.('lamp');
      tints.set(device, { rgb: [...rgb], intensity });
    }
    const group = own || groupOf(device), slotId = group ? group.device : device;
    const s = packed?.slots[slotId];
    if (!s || !uniforms) return;
    const on = fresh.has(slotId);
    // The slot carries the sum of its members' linear colours.
    const tint = group ? tintSum(group.members.map(id => tints.get(id)).filter(Boolean), on)
      : tintSum([{ rgb, intensity }], on);
    if (uniforms.lmChartMode) setLightTintColor(uniforms, 0, lights.findIndex(l => l.device === slotId), tint);
    else for (const room of s.receivers || [s.room]) setLightTintColor(uniforms, room, s.bank * 2 + s.channel, tint);
  }
  function regions() {
    // A column per bank, a row per room; the fills sit below the rooms (lightmap_material.js).
    const width = Math.max(1, packed.banks.length), t = roomRegions(packed.banks.length, atlas.room.rooms.length);
    packed.banks.forEach((bank, b) => bank.rooms.forEach(({ room, sourceRegion, region }) => {
      t.image.data.set([(region.x - sourceRegion.x) / layout.room.page,
        (region.y - sourceRegion.y) / layout.room.page, bankBase[b] + Math.max(0, layers[b].indexOf(region.page)), 0], (room * width + b) * 4);
    }));
    t.needsUpdate = true; return t;
  }
  let patchRound = 0;
  async function patch() {
    if (patched) return;
    patched = true;
    const mine = ++patchRound, materials = new Set();
    // Atlas attributes exist only on covered meshes. Give those meshes their own
    // materials; props sharing a kit material must not sample uninitialised UVs.
    for (const m of covered(root)) {
      const original = m.material, material = original.clone();
      view.prepareViewingMaterial?.(original, material);
      m.material = material; clones.push({ mesh: m, original, material }); materials.add(material);
    }
    patchLightmaps([...materials], pages, uniforms);
    patchWindows();
    // The lightmapped programs compile off the main thread before a frame draws
    // them; the unlit materials stay on screen meanwhile. A first draw compiles
    // synchronously, which froze the page for seconds on a full house.
    const ready = view.compileBehind ? view.compileBehind() : view.renderer3.compileAsync?.(view.scene, view.camera);
    if (!ready) return;
    const shown = clones.slice();
    for (const { mesh, original } of shown) mesh.material = original;
    await ready.catch(() => {});
    if (mine !== patchRound || !patched) return;
    for (const { mesh, material } of shown) mesh.material = material;
  }
  function unpatch() {
    ++patchRound;
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
      patchWindowGlow(material, pages, uniforms);
    });
  }
  function setSources(manifest = null) {
    // Each slot's light, where its shadowmask was rendered from (the shader's falloff and N.L).
    const exact = exactRects(lights, view.tier);
    lights.forEach((input, index) => {
      const l = packed.lights[index], s = packed.slots[l.device]; if (!s) return;
      const { source, range } = lightSource(view.plan, l);
      // Only the baker's published scale can decode a sum channel.
      const slotLight = l.kind === 3 ? {...l, scale: manifest?.lights[l.device]?.scale ?? 1} : l;
      if (uniforms.lmChartMode) setLightSource(uniforms, 0, index, source, range, l.kind || 0, slotLight, exact.has(l.device));
      else for (const room of s.receivers || [s.room]) setLightSource(uniforms, room, s.bank * 2 + s.channel, source, range, l.kind || 0, slotLight, exact.has(l.device));
    });
  }
  // The light list's layout: banks, layers, tints and the blank arrays it draws from.
  function prepare(list, history = packed?.ownership, manifest = null) {
    unpatch();
    for (const t of textures) t.dispose();
    textures.clear();
    if (uniforms) for (const name of ['lmTints', 'lmRegions']) uniforms[name]?.value.dispose();
    pages = uniforms = null;
    etags.clear(); present.clear(); pageErrors.clear(); manifestText = null; fresh.clear();
    lights = list; lightsKey = JSON.stringify(list);
    packed = bakeLayout(atlas, layout, lights, history, manifest?.lights);
    if (packed.banks.some(b => b.chartPacking)) applyChartIndices(atlas);
    // A bank page no placed light writes to (bank zero reserves unlit rooms,
    // Ruling B12) is never fetched or held on the GPU. All lit pages share one
    // array, ordered by bank then page; lmRegions carries the merged layer.
    layers = packed.banks.map((b, i) => [...new Set(Object.values(packed.entries).flatMap(e => e.pages || [e.page]).map(p => p - packed.offsets[i])
      .filter(p => p >= 0 && p < b.pages))].sort((a, c) => a - c));
    bankBase = bankLayerBases(layers);
    const layerCount = layers.reduce((n, list) => n + list.length, 0);
    const gl = view.renderer3.getContext?.();
    const maxLayers = gl?.getParameter?.(gl.MAX_ARRAY_TEXTURE_LAYERS) ?? 256;
    if (layerOverflow && layerCount <= maxLayers) { failure = ''; errorReason = null; }
    layerOverflow = layerCount > maxLayers;
    stale = lights.map(l => l.device);
    if (layerOverflow) {
      // Never split into more samplers or draw a partial bake. The live rig
      // already handles stale lights on every tier, including read-only panels.
      errorReason = `Baked lighting needs ${layerCount} array layers; this GPU supports ${maxLayers}. Using real-time lighting.`;
      failure = errorReason; retained = null;
      Promise.resolve(view.live?.refresh()).catch(reportError);
      view.reflectionsChanged?.(); view.render(); showProgress();
      return;
    }
    uniforms = packed.banks.some(b => b.chartPacking)
      ? chartLightmapUniforms(atlas.room.charts.length, packed, lights, layout.room.page, layers)
      : lightmapUniforms(atlas.room.rooms.length, Math.max(2, packed.banks.length * 2), {fixtures: needsFixtureShader(lights)});
    if (!uniforms.lmRegions) uniforms.lmRegions = { value: regions() };
    const roomFormat = pickTranscode(view.renderer3.extensions, 2);
    // Keep the texture-list hook shape, now with exactly one physical array.
    // Empty banks cost no layers; an entirely empty bake needs one tiny placeholder.
    pages = { banks: [blankArray(layerCount, roomFormat, layerCount ? layout.room.page : 4)],
      bankBase, bankLayers: layers.map(list => list.length) };
    pages.banks.forEach(t => textures.add(t));
    setSources();
    if(retained?.key===atlas.key && JSON.stringify(retained.layers)===JSON.stringify(layers) &&
        retained.banks.length===pages.banks.length && retained.banks.every((t,i)=>t.format===pages.banks[i].format &&
          t.image.width===pages.banks[i].image.width && t.image.depth===pages.banks[i].image.depth)) {
      retained.banks.forEach((t,i)=>{t.mipmaps.forEach((m,j)=>pages.banks[i].mipmaps[j].data.set(m.data));pages.banks[i].needsUpdate=true;});
      for(const p of retained.present){present.add(p);preservePages.add(p);}
      for(const [p,e] of retained.etags)etags.set(p,e);
      pageManifest=retained.manifest;
    }
    retained=null; // The new arrays now own the bytes; release the stopped controller's copy.
    stale = lights.map(l => l.device);
    for (const [id, tint] of tints) light(id, tint.rgb, tint.intensity);
  }
  // The room fill each baked light published with its pages (baker.js), onto the slots
  // that light owns. A light with no fill (none reached its room) adds none.
  function fills(m) {
    clearFills(uniforms);
    const banks = Math.max(1, packed.banks.length);
    for (const l of lights) {
      const fill = m.lights[l.device]?.fill, s = packed.slots[l.device];
      if (!fill || !s) continue;
      if (uniforms.lmChartMode) for (const a of s.assignments || []) {
        const value = fill[atlas.room.charts[a.chart]?.room];
        if (value) setChartFill(uniforms, a.chart, a.bank, banks, a.channel, value);
      } else for (const room of s.receivers || [s.room]) if (fill[room]) setRoomFill(uniforms, room, s.bank * 2 + s.channel, fill[room]);
    }
  }
  function locate(p) {
    for (let i = 0; i < layers.length; i++) {
      const layer = layers[i].indexOf(p - packed.offsets[i]);
      if (layer >= 0) return { texture: pages.banks[0], layer: bankBase[i] + layer };
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
      stale = lights.map(l => l.device); view.reflectionsChanged?.(); view.render();
      return;
    }
    let m = JSON.parse(text);
    // A reopened panel or another desk's publication adopts the persisted
    // channels. Never reset survivors to a fresh assignment on reload/poll.
    if(text!==manifestText && (packed.ownershipReset || m.ownership && !sameSlots(m.ownership,packed.ownership) ||
      packed.lights.some(l=>l.kind===3 && l.scale!==m.lights[l.device]?.scale))) {
      // Held bytes were encoded with the previous scale. Do not mark them
      // fresh under a new scale if its replacement page is offline or damaged.
      for (const l of packed.lights) if (l.kind === 3 && l.scale !== m.lights[l.device]?.scale)
        for (const p of packed.entries[l.device]?.pages || []) { present.delete(p); etags.delete(p); }
      const next=bakeLayout(atlas,layout,lights,m.ownership || packed.ownership,m.lights);
      if(!sameSlots(next.ownership,packed.ownership)) prepare(lights,m.ownership,m);
      else packed=next;
    }
    if (!pages) return; // A new ownership layout may exceed the GPU's layer limit.
    if(packed.ownershipReset)m={...m,lights:{}};
    let changed = text !== manifestText;
    manifestText = text;
    const wanted = new Set();
    layers.forEach((list, i) => list.forEach(p => wanted.add(packed.offsets[i] + p)));
    for (const p of [...wanted].sort((a, c) => a - c)) {
      if(preservePages.has(p) && present.has(p) && pageSignature(pageManifest,p)===pageSignature(m,p))continue;
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
        if (pageErrors.delete(p)) showProgress();
      } catch (error) {
        // A damaged page keeps its lights real-time; a broken build stays visible.
        if (!pageErrors.has(p)) {
          pageErrors.set(p, `Lightmap page ${p}: ${error.message || error}`);
          console.error('House lighting bake failed:', error); showProgress();
        }
        if (present.has(p)) { writeLayer(at.texture, at.layer, null); present.delete(p); changed = true; }
        etags.delete(p);
      }
    }
    // An unchanged manifest and every page 304: nothing to rebuild, upload or redraw (I2).
    if (!changed || !valid()) return;
    const previous = [...fresh]; fresh.clear();
    for (const l of lights) {
      const e = packed.entries[l.device], stored = m.lights[l.device];
      if (e && (l.kind !== 3 || e.scale > 0) && stored?.key === e.key && stored.scale === e.scale && stored.location === e.location && stored.channel === e.channel &&
        JSON.stringify(stored.pages) === JSON.stringify(e.pages) && e.pages.every(p => present.has(p))) fresh.add(l.device);
    }
    stale = lights.filter(l => !fresh.has(l.device)).map(l => l.device);
    pageManifest=m;
    if(!stale.length)preservePages.clear();
    setSources(m);fills(m);
    if (present.size) { await patch(); if (!valid()) return; }
    for (const id of previous) if (!fresh.has(id)) light(id, [0, 0, 0], 0);
    for (const [id, tint] of tints) light(id, tint.rgb, tint.intensity);

    // Refresh the pool selection as soon as a light becomes fresh.
    if (view.live) await view.live.refresh();
    view.reflectionsChanged?.();
    view.render();
  }
  // M3: a light placed or moved while the view is open follows the live layer's layout.
  async function relight() {
    const layoutNow = view.live?.layout?.();
    if (!layoutNow || !atlas) return;
    const next = bakeLights(layoutNow, root, view.plan);
    if (JSON.stringify(next) === lightsKey) return;
    if (running) { pendingRun = true; baker?.cancel(); }
    const text=await readManifest(atlas.key);if(!valid())return;
    const manifest=typeof text==='string'?JSON.parse(text):null;
    prepare(next,manifest?.ownership || packed?.ownership,manifest);
    await loadPages();
    if (allowed && !running) run();
  }
  async function run(force = false) {
    if (!allowed || !valid() || !atlas || layerOverflow) return;
    if (running) { pendingForce ||= force; return; }
    failure = ''; errorReason = null; progress = { done: 0, total: force ? lights.length : stale.length };
    running = true; showProgress();
    const mine = generation, input = lightsKey;
    try {
      baker = createBaker(view, { renderer: view.renderer3, atlas, layout, lights, api, codec, force, owner });
      const initialStale = await baker.staleLights();
      if (!valid() || mine !== generation || input !== lightsKey) return;
      stale = initialStale; progress = baker.progress(); showProgress();
      while (valid() && mine === generation && input === lightsKey && !layerOverflow) {
        await idle();
        const id = await baker.bakeNext(); if (!id || !valid() || mine !== generation || input !== lightsKey) break;
        baked.push(id); progress = baker.progress(); stale = await baker.staleLights(); showProgress();
        await loadPages();
      }
      // Tell the editor's chip this round's lights are whole (Ruling B15).
      if (valid() && mine === generation && input === lightsKey && !(await baker.staleLights()).length) await baker.settle();
    } catch (error) {
      reportError(error);
    } finally {
      running = false; progress = { done: 0, total: 0 }; showProgress();
      if (valid() && (pendingForce || pendingRun)) { const f = pendingForce; pendingForce = pendingRun = false; run(f); }
    }
  }
  async function begin(text) {
    initialized = false;
    // A retry after a later mount step failed resumes the already applied atlas.
    if (pending) { atlas = pending.apply(); pending = null; }
    codec?.stop(); codec = workerCodec();
    const manifest=typeof text==='string'?JSON.parse(text):null;
    prepare(lights,manifest?.ownership,manifest);
    await loadPages(); if (!valid()) return;
    showProgress();
    if (allowed) run();
    initialized = true;
  }
  async function refresh() {
    if (!valid()) return;
    if (!initialized) { await initialize(); return; }
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
      ...progress, baked: [...baked], stale: [...stale], error: errorReason || pageReason() }),
    // Members of a fresh shared channel are fresh: the live layer asks by its own lamp ids.
    fresh: () => valid() ? [...fresh].flatMap(id => [id, ...(lights.find(l => l.device === id)?.members || [])]) : [], light, idle, refresh,
    occlusionRoot: () => atlas?.sourceRoot || root,
    snapshot: () => atlas && pages ? {key:atlas.key,layers,bankBase,banks:pages.banks,present:[...present],etags:[...etags],manifest:pageManifest} : null,
    refreshMaterials(ids) {
      for (const { original, material } of clones) if (ids.includes(original.userData.materialId)) copyMaterialParams(original, material);
    },
    materialsChanged(ids = null) {
      if (!valid() || !atlas || layerOverflow) return false;
      if(ids)controller.refreshMaterials(ids);
      if (!invalidateMaterialReach(atlas.room, ids)) return false;
      ++generation;
      baker?.cancel();
      pendingRun ||= running;
      // Material edits do not move charts or change their channel assignment.
      // Retain the arrays, shader bindings and unrelated lights' fresh masks.
      const previous = packed;
      packed = bakeLayout(atlas, layout, lights, packed.ownership, packed.entries);
      if(packed.ownershipReset) {
        fresh.clear(); present.clear(); etags.clear(); preservePages.clear();
        prepare(lights, packed.ownership);
      }
      setSources({lights:packed.entries});
      for (const id of [...fresh]) if (previous.entries[id]?.key !== packed.entries[id]?.key) {
        fresh.delete(id); light(id, [0, 0, 0], 0);
      }
      stale = lights.filter(l => !fresh.has(l.device)).map(l => l.device);
      for(const p of present)preservePages.add(p);
      manifestText = null;
      Promise.resolve(view.live?.refresh()).catch(reportError);
      view.render();
      if(allowed && !running)run();
      return true;
    },
    // Logical banks retain their lit-page metadata; the texture/version/update
    // lists describe the single physical array and its merged layer indices.
    held: () => pages ? {
      banks: packed.banks.map((b, i) => ({ size: pages.banks[0].image.width, layers: layers[i].length, base: bankBase[i], pages: b.pages, lit: [...layers[i]] })),
      versions: { banks: pages.banks.map(t => t.version) },
      ids: { banks: pages.banks.map(t => t.uuid) },
      updates: { banks: pages.banks.map(t => [...t.layerUpdates]) },
      textures: { banks: [...pages.banks] } } : null,
    // Which charts each light was given and where (test hook, as held()).
    packing: () => packed && atlas ? { entries: packed.entries, fallback: packed.fallback || [],
      offsets: [...packed.offsets],
      slots: Object.fromEntries(Object.entries(packed.slots).map(([id, s]) => [id, (s.assignments || []).map(a => [a.chart, a.bank, a.channel])])),
      charts: atlas.room.charts.map(c => ({ id: c.id, room: c.room, page: c.page, rect: c.rect, heightfield: !!c.heightfield, outdoor: !!c.outdoor })),
      banks: packed.banks.map(b => ({ pages: b.pages, charts: b.charts.map(c => [c.id, c.page, c.rect]) })), layers: layers.map(l => [...l]) } : null,
    now: () => run(true),
    stop() {
      if (stopped) return;
      stopped = true; baker?.cancel(); halt.abort(); clearTimeout(timer); codec?.stop(); strip?.remove();
      controls.removeEventListener('start', moved); controls.removeEventListener('change', moved); controls.removeEventListener('end', moved);
      unpatch();
      releaseBakeSource(root);
      for (const t of textures) t.dispose();
      if (uniforms) for (const name of ['lmTints', 'lmRegions']) uniforms[name]?.value.dispose();
    },
  };
  view.bake = controller;
  function initialize() {
    if (mounting) return mounting;
    mounting = (async () => {
      if (!covered(root).length) return;
      const response = await api('api/house/live'); const liveLayout = response.ok ? await response.json() : null;
      if (!valid()) return;
      lights = bakeLights(liveLayout, root, view.plan);
      // The worker lays the atlas out; it is applied to the meshes only once a bake
      // exists or this desk will make one (M1).
      if (!atlas && !pending) pending = await loadAtlas(root, round, layout, { signal: halt.signal, apply: false });
      if (!valid()) return;
      let text = await readManifest(pending?.key || atlas.key);
      const manifest = typeof text === 'string' ? JSON.parse(text) : null;
      if (manifest?.densities && (manifest.densities.room !== layout.room.density)) {
        layout = { room: { ...layout.room, density: manifest.densities.room } };
        pending = await loadAtlas(root, round, layout, { signal: halt.signal, apply: false });
        if (!valid()) return;
        text = await readManifest(pending.key);
      }
      allowed = canBake && await mayBake(api, `api/house/bakes/${pending?.key || atlas.key}`, owner);
      if (!valid()) return;
      showControls();
      failure = ''; errorReason = null;
      if (typeof text === 'string' || allowed) await begin(text);
      if (!valid()) return;
      initialized = true; showProgress();
    })().finally(() => { mounting = null; });
    return mounting;
  }
  // The same poll retries incomplete mounts as well as finding later publications.
  const tick = async () => {
    if (!valid()) return;
    // Offline: keep the last complete page and say nothing; the next poll tries again.
    try { await refresh(); } catch (error) { if (!offline.has(error)) reportError(error); }
    finally { if (valid() && pollMs > 0) timer = setTimeout(tick, pollMs); }
  };
  (async () => {
    try { await initialize(); }
    catch (error) { reportError(error); }
    finally { if (valid() && covered(root).length && pollMs > 0) timer = setTimeout(tick, pollMs); }
  })();
  return controller;
}
