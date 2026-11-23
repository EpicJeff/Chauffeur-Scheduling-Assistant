import * as THREE from 'three';
import { base, copyMaterialParams, currentMaterial, applyMaterialParams } from '../twin_library.js';
import { contains, FT } from '../twin_generator.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { loadAtlas, lightmapUniforms, applyChartIndices, chartLightmapUniforms, patchLightmaps, setLightTintColor, tintSum, pickTranscode,
  setLightSource, setChartFill, setRoomFill, clearFills, roomRegions, patchWindowGlow, needsFixtureShader, bankLayerBases } from './lightmap_material.js';
import { lightSource } from './reach.js';
import { resolveEmitters, emitterSignature, lightMarkers } from '../live/emitters.js';
import { kindOf, exactRects } from './fixture_terms.js';
import { createBaker, bakeLayout, realtimeReason } from './baker.js';
import { mayBake, bakeHTTPError } from './bake_lock.js';
import { workerCodec } from './worker_codec.js';
import { covered } from './atlas_transport.js';
import { sameSlots } from './slots.js';
import { invalidateMaterialReach } from './reach.js';
import { releaseBakeSource, bakeReceiverRoots, bakeModelRoot, prepareBakeModels } from './source.js';
import { matchesEntry, pageDamage, cheapSignatures, realtimeCurrent } from './freshness.js';
import { keyInputs, sameKeyInputs } from './key_inputs.js';
import { gridLayout } from './grid_layout.js';
import { mountModelLighting } from './model_lighting.js';

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

export function mountBake(view, root, { host, mode = 'manual', parent = false, display = true, disabledReason = '', blocked = () => '', controls = view.controls, layout: requestedLayout, poll: pollMs = 10000,
  api: request = (path, init) => fetch(base() + path, init) } = {}) {
  let retained = view.bake?.snapshot?.();
  // A fetch that rejects is the network being away, which the poll rides out in silence.
  const offline = new WeakSet();
  const api = async (path, init) => {
    try {
      const r = await request(path, init);
      if (r.status === 401) throw bakeHTTPError('Could not access the bake', 401);
      return r;
    }
    catch (error) { if (error instanceof TypeError) offline.add(error); throw error; }
  };
  const round = view.bakePlan || view.plan, halt = new AbortController(), baked = [], fresh = new Set(), tints = new Map();
  const query = new URLSearchParams(location.search);
  // Only a parent's High or Max desk bakes (the lease is PARENTS: a child is refused, M4).
  const interactive = !query.has('panel') && !query.has('kiosk');
  const canBake = mode !== 'readonly' && !disabledReason && ['high', 'max'].includes(view.tier) && interactive;
  const automatic = mode === 'auto'; // Explicit legacy harness mode; neither mounted page uses it.
  const inspectOnly = mode === 'manual' && !display;
  let requested = automatic;
  const owner = [...globalThis.crypto.getRandomValues(new Uint32Array(4))].map(x => x.toString(16)).join('');
  let parentProbed = false;
  let stopped = false, allowed = false, permissionChecked = false, atlas = null, pending = null, layout = requestedLayout || options(8);
  let lights = [], lightsKey = '', packed = null, uniforms = null, pages = null;
  let models = null;
  let layers = [], bankBase = [], layerOverflow = false, baker = null, codec = null, running = false, pendingForce = false, pendingRun = false;
  let dragging = false, stillAt = performance.now(), generation = 0;
  let progress = { done: 0, total: 0 }, stale = [], timer = null, patched = false;
  let failure = '', failureSource = null, errorReason = null, manifestText = null, initialized = false, mounting = null, manifestRead = false;
  let editorKey = null, editorManifest = null, editedRound = false, materialDirty = false;
  let blockReason = blocked();
  let authPaused = false, manualWait = false, retryAt = null, retryTimer = null, retryAttempts = 0;
  let hiddenSince = document.hidden ? Date.now() : null, forceIntent = null, resumePending = false;
  const signOutMessage = 'Home Assistant signed this tab out. Open Chauffeur in Home Assistant (or use your usual app address), then press Resume.';
  const needsResume = () => allowed || canBake && !permissionChecked;
  function clearRetry() { clearTimeout(retryTimer); retryTimer = null; retryAt = null; }
  function clearFailure(source = null) {
    if (authPaused || layerOverflow || source && failureSource !== source) return;
    failure = ''; failureSource = null; errorReason = null;
    if (!allowed) { clearRetry(); retryAttempts = 0; manualWait = false; }
    showProgress();
  }
  function retryTick() {
    if (!valid()) { clearRetry(); return; }
    if (hiddenSince !== null && Date.now() - hiddenSince >= 60000) {
      clearRetry(); manualWait = true; showProgress(); return;
    }
    if (Date.now() >= retryAt && !document.hidden) {
      clearRetry();
      const retryBake = allowed && requested && failureSource === 'bake';
      (retryBake ? run(false) : refresh()).catch(error => reportError(error, retryBake ? 'bake' : 'refresh'));
      return;
    }
    showProgress(); retryTimer = setTimeout(retryTick, 1000);
  }
  function reportError(error, source = 'refresh') {
    if (!valid()) return;
    // A poll must not replace a failed step's reason or restart its backoff.
    if (source === 'refresh' && failureSource === 'bake' && error?.status !== 401) return;
    failureSource = source;
    errorReason = error?.message || String(error);
    authPaused ||= needsResume() && error?.status === 401;
    clearRetry();
    failure = authPaused ? signOutMessage : source === 'refresh' || !needsResume()
      ? `Could not read baked lighting (${errorReason}).` : `Could not bake lighting (${errorReason}).`;
    if (authPaused) { manualWait = true; baker?.cancel(); pendingForce = pendingRun = false; }
    else if (!needsResume() || mode === 'manual' && source === 'refresh') { manualWait = false; }
    else if (!manualWait && retryAttempts < 8) {
      const delay = [5000, 15000, 60000][retryAttempts] || 120000;
      retryAttempts++; retryAt = Date.now() + delay;
      retryTimer = setTimeout(retryTick, 1000);
    } else manualWait = true;
    console.error('House lighting bake failed:', error);
    showControls(); showProgress();
  }
  document.addEventListener?.('visibilitychange', () => {
    if (hiddenSince !== null && Date.now() - hiddenSince >= 60000 && retryAt !== null) {
      clearRetry(); manualWait = true; showProgress();
    }
    hiddenSince = document.hidden ? Date.now() : null;
    if (retryAt !== null) { clearTimeout(retryTimer); retryTick(); }
  }, { signal: halt.signal });
  const pageErrors = new Map(), etags = new Map(), present = new Set(), clones = [], textures = new Set();
  const preservePages = new Set();
  // page -> the manifest text and stored digest of a newer page not yet named
  // by a manifest (a publication in flight on another desk).
  const unpublished = new Map();
  let pageManifest = null;
  const pageSignature = (m,p) => JSON.stringify(Object.entries(m?.lights || {}).filter(([,e])=>(e.pages || [e.page]).includes(p))
    .map(([id,e])=>[id,e.key,e.location,e.channel,e.scale]).sort((a,b)=>a[0].localeCompare(b[0])));
  const pageReason = () => pageErrors.values().next().value || null;
  const valid = () => !stopped && (view.bakePlan || view.plan) === round;
  const paused = () => dragging || performance.now() - stillAt < 2000;
  const moved = () => { stillAt = performance.now(); };
  const pointers = new Set();
  const down = event => { pointers.add(event.pointerId); dragging = true; moved(); };
  const up = event => { pointers.delete(event.pointerId); dragging = pointers.size > 0; moved(); };
  // Capture sees gestures even when a handle/marquee owns and stops the event.
  view.renderer3.domElement.addEventListener('pointerdown', down, { signal: halt.signal, capture: true });
  if (mode === 'manual') {
    document.addEventListener('pointerdown', down, { signal: halt.signal, capture: true });
    document.addEventListener('pointerup', up, { signal: halt.signal, capture: true });
    document.addEventListener('pointercancel', up, { signal: halt.signal, capture: true });
  }
  window.addEventListener('pointerup', up, { signal: halt.signal, capture: true });
  window.addEventListener('pointercancel', up, { signal: halt.signal, capture: true });
  window.addEventListener('blur', () => { pointers.clear(); dragging = false; moved(); }, { signal: halt.signal });
  controls.addEventListener('start', moved); controls.addEventListener('change', moved); controls.addEventListener('end', moved);
  let strip = null, status = null, button = null, resumeButton = null, legend = null, startButton = null, meter = null;
  function showControls() {
    if (mode === 'readonly') {
      const message = layerOverflow ? failure : pageReason() ? `Could not read baked lighting (${pageReason()}).` : '';
      if (!host || !parent || !interactive || !manifestRead || !stale.length && !message) { strip?.remove(); strip = null; return; }
      if (!strip) {
        strip = document.createElement('span'); strip.id = 'twin-bake-status'; strip.setAttribute('role', 'status');
        host.append(strip);
      }
      strip.replaceChildren();
      if (stale.length) {
        const link = document.createElement('a'); link.href = base() + 'house/editor';
        link.textContent = 'Lighting is out of date. Bake it in the house editor.'; strip.append(link);
      }
      if (message) { const note = document.createElement('span'); note.textContent = ' ' + message; strip.append(note); }
      return;
    }
    if (mode === 'manual') {
      if (!host || !interactive) return;
      if (!strip) {
        strip = document.createElement('span'); strip.id = 'twin-bake-controls';
        status = document.createElement('output'); status.setAttribute('role', 'status');
        meter = document.createElement('progress'); meter.setAttribute('aria-label', 'Baking lights');
        startButton = document.createElement('button'); startButton.type = 'button'; startButton.textContent = 'Bake lighting';
        startButton.addEventListener('click', () => controller.start());
        resumeButton = document.createElement('button'); resumeButton.type = 'button'; resumeButton.textContent = 'Resume';
        resumeButton.id = 'twin-bake-resume'; resumeButton.addEventListener('click', () => controller.resume());
        button = document.createElement('button'); button.type = 'button'; button.textContent = 'Re-bake all lighting';
        button.addEventListener('click', () => controller.now());
        strip.append(status, meter, startButton, resumeButton, button); host.append(strip);
      }
      return;
    }
    const actions = allowed || canBake && !permissionChecked && authPaused;
    if (!host || !canBake || permissionChecked && !allowed || !actions && !failure) {
      strip?.remove(); strip = status = button = resumeButton = legend = null;
      return;
    }
    if (!strip) {
      strip = document.createElement('fieldset'); strip.id = 'twin-bake-controls';
      legend = document.createElement('legend'); legend.textContent = 'Lighting';
      status = document.createElement('output'); status.setAttribute('role', 'status'); status.hidden = true;
      strip.append(legend, status); host.append(strip);
    }
    if (!actions) {
      button?.remove(); resumeButton?.remove(); button = resumeButton = null;
      return;
    }
    if (button) return;
    button = document.createElement('button'); button.type = 'button'; button.textContent = 'Re-bake all lighting';
    button.disabled = true; button.addEventListener('click', () => controller.now());
    resumeButton = document.createElement('button'); resumeButton.type = 'button'; resumeButton.textContent = 'Resume';
    resumeButton.id = 'twin-bake-resume'; resumeButton.addEventListener('click', () => controller.resume());
    strip.replaceChildren(legend, button, resumeButton, status);
  }
  function bakeProgress() {
    const next = baker.progress();
    return {...next, grid: next.grid.points ? next.grid : progress.grid};
  }
  function showProgress() {
    showControls();
    if (!status) return;
    const message = failure || (pageReason() ? `Could not read baked lighting (${pageReason()}).` : '');
    status.hidden = mode !== 'manual' && !(running && progress.total) && !message;
    status.textContent = message ? message + (retryAt !== null ? ` Retrying in ${Math.max(0, Math.ceil((retryAt - Date.now()) / 1000))} s` : (!authPaused && manualWait ? ' Press Resume to continue.' : ''))
      : (running && progress.total ? `Baking lights ${progress.done} of ${progress.total}${progress.grid?.points ? ` · Grid ${progress.grid.points} points` : ''}` : '');
    if (mode === 'manual') {
      if (!message && !running) status.textContent = !['high', 'max'].includes(view.tier) ? 'Baking needs High or Max quality'
        : disabledReason ? disabledReason
        : !permissionChecked ? 'Checking baked lighting…' : !allowed ? 'Only a parent can bake lighting'
        : !manifestRead ? 'Checking baked lighting…' : !lights.length ? 'Lighting is up to date'
        : stale.length || inspectOnly && editorManifest?.complete !== true ? editedRound ? 'Lighting out of date since your edits' : `Lighting out of date: ${stale.length} light${stale.length === 1 ? '' : 's'}` : 'Lighting is up to date';
      if (blockReason) status.textContent = blockReason;
      meter.hidden = !running || !progress.total; meter.max = progress.total || 1; meter.value = progress.done;
      startButton.hidden = !allowed || !(stale.length || inspectOnly && lights.length && editorManifest?.complete !== true) || running || !!failure || resumePending;
      startButton.disabled = !manifestRead || authPaused || layerOverflow || !!blockReason;
      button.hidden = !allowed;
    }
    if (button) button.disabled = !allowed || !(atlas || inspectOnly && manifestRead) || running || authPaused || !!blockReason;
    if (resumeButton) { resumeButton.hidden = !(failure && (failureSource === 'bake' || authPaused)) && !resumePending || layerOverflow; resumeButton.disabled = running || !!blockReason; }
  }
  async function idle() {
    while (valid() && (paused() || !view.ready || view.yardSettling || blockReason)) {
      if (running && blockReason) throw new Error(blockReason);
      await wait(50);
    }
    if (!valid()) throw new Error('The bake round changed.');
    if (view.yardError) throw view.yardError;
    await new Promise(resolve => {
      if (globalThis.requestIdleCallback) requestIdleCallback(resolve, { timeout: 100 });
      else requestAnimationFrame(resolve);
    });
    if (!valid()) throw new Error('The bake round changed.');
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
    models?.setTint(slotId, tint);
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
    // The editor keeps its own Day/Night/Now/Unlit and selection materials.
    // Its bake publishes to viewers without replacing those edit-time materials.
    if (!display) return;
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
    models?.update([]).catch(reportError);
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
      Promise.resolve(view.live?.refresh?.()).catch(reportError);
      view.reflectionsChanged?.(); view.render(); showProgress();
      return;
    }
    if (inspectOnly) return; // The editor never draws or transcodes stored pages.
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
    if (!r.ok) throw bakeHTTPError('Could not read the bake manifest', r.status);
    return r.text();
  }
  async function loadEditorPages() {
    let latest;
    if (atlas) {
      // A pressed run has already discovered this plan's exact key. Another
      // desk publishing an older key must not hide its completed manifest.
      const text = await readManifest(atlas.key);
      latest = typeof text === 'string' ? {key: atlas.key, manifest: JSON.parse(text)} : null;
    } else {
      const response = await api('api/house/bakes');
      if (!response.ok) throw bakeHTTPError('Could not read the bake manifest', response.status);
      latest = await response.json();
    }
    if (!valid()) return;
    const mine = generation;
    const m = latest?.manifest, text = JSON.stringify(latest);
    editorKey = latest?.key || null; editorManifest = m;
    if (text !== manifestText || !manifestRead) {
      present.clear(); pageErrors.clear();
      for (const p of new Set(Object.values(m?.lights || {}).flatMap(e => e.pages || [e.page]))) {
        const saved = m?.pageIntegrity?.[p];
        // Unsigned legacy pages remain conservatively stale until a press.
        // Even those checks never download/decode/transcode page bytes here.
        if (!saved) continue;
        const r = await api(`api/house/bakes/${editorKey}/${p}.png`, { headers: { 'If-None-Match': '*' } });
        if (!valid() || mine !== generation) return;
        if (r.status !== 304 && !r.ok && r.status !== 404) throw bakeHTTPError('Could not read the lightmap page', r.status);
        if (r.status === 404) continue;
        const header = r.headers.get('X-Bake-Size');
        const damage = pageDamage(m, p, r.headers.get('X-Bake-Digest') || r.headers.get('etag'), header == null ? null : Number(header));
        if (damage) pageErrors.set(p, damage); else present.add(p);
      }
    }
    editorFreshness(m);
    manifestText = text; manifestRead = true; showProgress();
  }
  // Old rounds/manifests retain round-based freshness until a pressed bake.
  const lightingChanged = m => !!m && (m.lighting && view.lighting
    ? m.lighting !== view.lighting : m.round !== (view.round ?? null));
  function editorFreshness(m) {
    const cheap = cheapSignatures(lights, m?.ownership, m?.lights);
    editedRound = lightingChanged(m);
    const currentInputs = !editedRound && !materialDirty && sameKeyInputs(m?.keyInputs, keyInputs(view));
    fresh.clear();
    for (const l of lights) {
      const e = m?.lights?.[l.device];
      if (currentInputs && e?.cheap === cheap[l.device] && (l.kind !== 3 || e.scale > 0) &&
          (e.pages || [e.page]).every(p => present.has(p))) fresh.add(l.device);
    }
    resumePending = !!m?.forceRound;
    stale = lights.filter(l => !(currentInputs && !m?.lights?.[l.device] && realtimeCurrent(m, l.device, cheap[l.device])) &&
      (!fresh.has(l.device) || resumePending && m.lights[l.device]?.forceRound !== m.forceRound)).map(l => l.device);
    if (!running) progress = { done: lights.length - stale.length, total: lights.length, grid: progress.grid };
    showProgress();
  }
  async function loadPages() {
    if (inspectOnly) return loadEditorPages();
    if (!valid() || !pages) return;
    const text = await readManifest(atlas.key); if (!valid() || text === undefined) return;
    manifestRead = true;
    if (text === null) {
      if (manifestText === null && !present.size && !fresh.size) { showProgress(); return; }
      for (const id of fresh) light(id, [0, 0, 0], 0);
      for (const p of present) { const at = locate(p); if (at) writeLayer(at.texture, at.layer, null); }
      fresh.clear(); present.clear(); etags.clear(); pageErrors.clear(); unpublished.clear(); manifestText = null; resumePending = false;
      models?.update(fresh, {key:atlas.key, lights:{}}).catch(reportError);
      stale = lights.map(l => l.device); view.reflectionsChanged?.(); view.render();
      showProgress();
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
      if (r.status === 304) {
        const size = r.headers.get('X-Bake-Size');
        const damage = pageDamage(m, p, r.headers.get('X-Bake-Digest') || r.headers.get('etag'), size == null ? null : Number(size));
        if (damage) {
          pageErrors.set(p, damage); etags.delete(p);
          if (present.delete(p)) writeLayer(at.texture, at.layer, null);
          changed = true;
        }
        continue;
      }
      if (r.status === 404) {
        if (present.has(p)) { writeLayer(at.texture, at.layer, null); present.delete(p); changed = true; }
        etags.delete(p); unpublished.delete(p); continue;
      }
      if (!r.ok) continue;     // offline: keep the last complete page
      try {
        const bytes = new Uint8Array(await r.arrayBuffer());
        const digest = r.headers.get('X-Bake-Digest') || r.headers.get('etag');
        const damage = pageDamage(m, p, digest, bytes.length);
        if (damage) {
          // A desk stores its pages before the manifest that names them. A newer
          // page under the manifest this desk holds is a publication in flight:
          // keep the last complete page, which matches this manifest, and ask
          // again on the next poll. The same mismatch under the same manifest is damage.
          const prior = unpublished.get(p);
          if (present.has(p) && !(prior && prior.text === text && prior.digest === digest && prior.size === bytes.length)) {
            unpublished.set(p, { text, digest, size: bytes.length });
            continue;
          }
          throw new Error('damaged stored page');
        }
        unpublished.delete(p);
        const data = await codec.transcode(bytes, at.texture.format);
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
    if (!valid()) return;
    if (!changed) { models?.update(fresh).catch(reportError); return; }
    const previous = [...fresh]; fresh.clear();
    // The viewer is exact: entries at its own atlas key already carry every key
    // input. Cheap key-input stamps are evidence for the editor chip only; a
    // stamp-only difference must never drop valid baked channels here.
    const cheap = cheapSignatures(lights, m.ownership, m.lights);
    for (const l of lights) {
      const e = packed.entries[l.device], stored = m.lights[l.device];
      if (e && (l.kind !== 3 || e.scale > 0) && matchesEntry(e, stored) && e.pages.every(p => present.has(p))) fresh.add(l.device);
    }
    resumePending = !!m.forceRound;
    stale = lights.filter(l => !(!packed.entries[l.device] && realtimeCurrent(m, l.device, cheap[l.device], realtimeReason(packed, l.device))) &&
      (!fresh.has(l.device) || resumePending && m.lights[l.device]?.forceRound !== m.forceRound)).map(l => l.device);
    if (mode === 'manual' && !running) progress = { done: lights.length - stale.length, total: lights.length, grid: progress.grid };
    showProgress();
    pageManifest=m;
    if(!stale.length)preservePages.clear();
    setSources(m);fills(m);
    if (present.size) { await patch(); if (!valid()) return; }
    if (display) {
      const manifest = {...m, key:atlas.key};
      models ||= mountModelLighting(view, {manifest, layout:gridLayout(round), fresh, tints, api, lights});
      models.update(fresh, manifest, lights).catch(reportError);
    }
    for (const id of previous) if (!fresh.has(id)) light(id, [0, 0, 0], 0);
    for (const [id, tint] of tints) light(id, tint.rgb, tint.intensity);

    // Refresh the pool selection as soon as a light becomes fresh.
    await view.live?.refresh?.();
    view.reflectionsChanged?.();
    view.render();
  }
  // M3: a light placed or moved while the view is open follows the live layer's layout.
  async function relight() {
    if (mode === 'manual' && paused()) return;
    const layoutNow = view.live?.layout?.() || (mode === 'manual' ? await (await api('api/house/live')).json() : null);
    if (mode === 'manual') await idle();
    if (!layoutNow || !(atlas || pending || inspectOnly)) return;
    const next = bakeLights(layoutNow, root, round);
    if (JSON.stringify(next) === lightsKey) return;
    ++generation;
    if (running) { pendingRun = automatic; baker?.cancel(); }
    if (!automatic) { requested = false; clearRetry(); }
    if (inspectOnly) { lights = next; lightsKey = JSON.stringify(next); return; }
    const text=await readManifest(atlas.key);if(!valid())return;
    const manifest=typeof text==='string'?JSON.parse(text):null;
    prepare(next,manifest?.ownership || packed?.ownership,manifest);
    await loadPages();
    showProgress();
    if (automatic && allowed && !running) run();
  }
  async function run(force = false) {
    controller.syncBlocked();
    if (blockReason) { requested = false; return; }
    if (!valid() || !requested) return;
    if (!initialized) await initialize();
    if (!allowed || !valid() || !lights.length || !(atlas || pending || inspectOnly) || layerOverflow || authPaused || manualWait || !requested || blockReason) return;
    if (running) { pendingForce ||= force; return; }
    clearRetry();
    if (force) forceIntent = [...globalThis.crypto.getRandomValues(new Uint32Array(4))].map(x => x.toString(16)).join('');
    failure = ''; failureSource = null; errorReason = null;
    progress = {...(inspectOnly ? {done: force ? 0 : progress.done, total: lights.length} : {done: 0, total: 0}), grid: progress.grid};
    running = true; showProgress();
    const mine = generation, input = lightsKey;
    try {
      if (inspectOnly) {
        await idle();
        if (!valid() || !requested || blockReason || mine !== generation) return;
      }
      if (inspectOnly && !atlas) {
        pending ||= await loadAtlas(root, round, layout, { signal: halt.signal, apply: false });
        await idle();
        if (!valid() || !requested || blockReason || mine !== generation) return;
        atlas = pending.apply(); pending = null;
      }
      let damaged = [];
      if (inspectOnly) {
        if (materialDirty) {
          controller.refreshMaterials(Object.keys(view.materialManifest || {}));
          invalidateMaterialReach(atlas.room);
        }
        const text = await readManifest(atlas.key);
        await idle();
        if (!valid() || !requested || blockReason || mine !== generation) return;
        const manifest = typeof text === 'string' ? JSON.parse(text) : null;
        // A different desk may have repaired a page since the chip inspected
        // it. Only carry damage forward for the same published page version.
        if (editorKey === atlas.key) damaged = [...pageErrors.keys()].filter(p =>
          JSON.stringify(editorManifest?.pageIntegrity?.[p]) === JSON.stringify(manifest?.pageIntegrity?.[p]));
        prepare(lights, manifest?.ownership, manifest);
        if (layerOverflow) return;
        codec ||= workerCodec();
      }
      baker = createBaker(view, { renderer: view.renderer3, atlas, layout, lights, api, codec, forceRound: forceIntent, owner, damaged, inspectLegacy: inspectOnly,
        onGrid(grid) { if (grid.points) progress = {...progress, grid}; showProgress(); } });
      const initialStale = await baker.staleLights();
      if (!baker.forcePending()) forceIntent = null;
      if (!valid() || mine !== generation || input !== lightsKey) return;
      stale = initialStale; progress = bakeProgress(); showProgress();
      while (valid() && mine === generation && input === lightsKey && !layerOverflow) {
        await idle();
        const id = await baker.bakeNext();
        if (!baker.forcePending()) forceIntent = null;
        if (!id || !valid() || mine !== generation || input !== lightsKey) break;
        baked.push(id); progress = bakeProgress(); stale = await baker.staleLights(); showProgress();
        await loadPages();
      }
      // Publish completion for the current house round.
      if (valid() && mine === generation && input === lightsKey && !(await baker.staleLights()).length) {
        await baker.settle(); forceIntent = null; retryAttempts = 0;
        if (inspectOnly) { materialDirty = false; await loadPages(); }
        if (!automatic) requested = false;
        if (!authPaused) { clearRetry(); manualWait = false; clearFailure(); }
      }
    } catch (error) {
      if (baker && !baker.forcePending()) forceIntent = null;
      if (baker) progress = bakeProgress();
      if (valid() && mine === generation && input === lightsKey) reportError(error, 'bake');
    } finally {
      running = false; showProgress();
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
    if (automatic && allowed) run();
    initialized = true;
  }
  async function refresh() {
    controller.syncBlocked();
    if (!valid() || needsResume() && (authPaused || manualWait)) return;
    if (mode === 'manual' && blockReason) return;
    if (!initialized) { await initialize(); clearFailure('refresh'); return; }
    if (inspectOnly) { await idle(); await relight(); if (!running) await loadPages(); clearFailure('refresh'); return; }
    if (pending) {
      // A wall that opened before any bake applies the atlas when one lands (I1, M1).
      const text = await readManifest(pending.key);
      if (typeof text === 'string' && valid() && pending) { await begin(text); clearFailure('refresh'); }
      return;
    }
    if (!atlas) { clearFailure('refresh'); return; }
    await relight();
    if (!running) await loadPages();
    clearFailure('refresh');
  }
  const controller = {
    get models() { return models; },
    syncBlocked() {
      if (inspectOnly && manifestRead && editorManifest && editedRound !== lightingChanged(editorManifest))
        editorFreshness(editorManifest);
      const next = blocked();
      if (next === blockReason) return;
      blockReason = next;
      if (next) { ++generation; requested = false; pendingForce = pendingRun = false; baker?.cancel(); clearRetry(); }
      showProgress();
    },
    active: valid,
    state: () => ({ key: atlas?.key || pending?.key || editorKey, baking: running, paused: authPaused || manualWait || running && paused(), retryAt, retryAttempts,
      ...progress, grid: {...(progress.grid || {points: 0, bytes: 0, ms: 0, maskMs: 0})}, baked: [...baked], stale: [...stale], error: errorReason || pageReason() }),
    // Members of a fresh shared channel are fresh: the live layer asks by its own lamp ids.
    fresh: () => valid() ? [...fresh].flatMap(id => [id, ...(lights.find(l => l.device === id)?.members || [])]) : [], light, idle, refresh,
    occlusionRoot: () => atlas?.sourceRoot || root,
    modelRoot: () => bakeModelRoot(root),
    modelReady: () => prepareBakeModels(root),
    snapshot: () => atlas && pages ? {key:atlas.key,layers,bankBase,banks:pages.banks,present:[...present],etags:[...etags],manifest:pageManifest} : null,
    refreshMaterials(ids) {
      if (inspectOnly && (!running || !atlas)) return;
      const known = view.materialManifest;
      if (known) for (const receivers of bakeReceiverRoots(root)) if (receivers !== root) receivers.traverse(mesh => {
        for (const material of [].concat(mesh.material || [])) {
          const id = material.userData.materialId;
          if (ids.includes(id) && known[id] && !currentMaterial(material, known))
            applyMaterialParams(material, known[id], material.userData.materialRef, material.userData.materialRole || material.name, view.tier);
        }
      });
      for (const { original, material } of clones) if (ids.includes(original.userData.materialId)) copyMaterialParams(original, material);
    },
    materialsChanged(ids = null) {
      if (inspectOnly) {
        ++generation; baker?.cancel(); requested = false; clearRetry();
        materialDirty = true; fresh.clear(); stale = lights.map(l => l.device); showProgress();
        controller.refresh().catch(reportError); return true;
      }
      if (!valid() || !atlas || layerOverflow) return false;
      if(ids)controller.refreshMaterials(ids);
      if (!invalidateMaterialReach(atlas.room, ids)) return false;
      ++generation;
      baker?.cancel();
      pendingRun ||= automatic && running;
      if (!automatic) { requested = false; clearRetry(); }
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
      models?.update(fresh).catch(reportError);
      for(const p of present)preservePages.add(p);
      manifestText = null;
      Promise.resolve(view.live?.refresh?.()).catch(reportError);
      view.render();
      showProgress();
      if(automatic && allowed && !running)run();
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
    start: () => { requested = true; manualWait = false; retryAttempts = 0; return run(false).catch(error => reportError(error, 'bake')); },
    now: () => { requested = true; manualWait = false; retryAttempts = 0; return run(true).catch(error => reportError(error, 'bake')); },
    resume: async () => {
      clearRetry(); authPaused = manualWait = false; retryAttempts = 0;
      requested = true;
      try { if (!initialized || !allowed) await refresh(); await run(false); }
      catch (error) { reportError(error, 'bake'); }
    },
    stop() {
      if (stopped) return;
      stopped = true; clearRetry(); baker?.cancel(); halt.abort(); clearTimeout(timer); codec?.stop(); strip?.remove();
      models?.stop();
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
      if (mode === 'manual') {
        // Permission does not depend on geometry. Check before any atlas work;
        // the real key's lease is acquired only by the explicitly started run.
        allowed = canBake && await mayBake(api, 'api/house/bakes/0000000000000000', owner);
        permissionChecked = true;
        if (!allowed) { initialized = true; showProgress(); return; }
        showProgress();
        await idle();
      }
      if (disabledReason || !covered(root).length) { initialized = permissionChecked = manifestRead = true; showProgress(); return; }
      const response = await api('api/house/live'); const liveLayout = response.ok ? await response.json() : null;
      if (mode === 'manual') await idle();
      if (!valid()) return;
      lights = bakeLights(liveLayout, root, round);
      lightsKey = JSON.stringify(lights);
      stale = lights.map(l => l.device);
      if (inspectOnly) {
        await loadEditorPages();
        if (valid()) { initialized = true; showProgress(); }
        return;
      }
      // The worker lays the atlas out; it is applied to the meshes only once a bake
      // exists or this desk will make one (M1).
      if (!atlas && !pending) pending = await loadAtlas(root, round, layout, { signal: halt.signal, apply: false });
      if (!valid()) return;
      let text = await readManifest(pending?.key || atlas.key);
      const manifest = typeof text === 'string' ? JSON.parse(text) : null;
      if (manifest?.densities && (manifest.densities.room !== layout.room.density)) {
        layout = { room: { ...layout.room, density: manifest.densities.room } };
        if (mode === 'manual') await idle();
        pending = await loadAtlas(root, round, layout, { signal: halt.signal, apply: false });
        if (!valid()) return;
        text = await readManifest(pending.key);
      }
      if (mode !== 'manual') allowed = canBake && await mayBake(api, `api/house/bakes/${pending?.key || atlas.key}`, owner);
      permissionChecked = true;
      if (!valid()) return;
      failure = ''; errorReason = null;
      if (typeof text === 'string' || allowed) { manifestRead = true; await begin(text); }
      else manifestRead = true;
      if (!valid()) return;
      if (mode === 'readonly' && host && interactive && !parent && !parentProbed) {
        // The page HTML carries no member token (it lives in localStorage), so the
        // server-rendered flag cannot see a signed-in parent. Ask once through the
        // page's authenticated fetch: latest bake metadata is PARENTS-only and
        // touches no lease. Panels and kiosks never ask.
        parentProbed = true;
        try { parent = (await api('api/house/bakes')).ok; } catch { parent = false; }
        if (!valid()) return;
      }
      initialized = true; showProgress();
    })().finally(() => { mounting = null; });
    return mounting;
  }
  // The same poll retries incomplete mounts as well as finding later publications.
  const tick = async () => {
    if (!valid()) return;
    // Offline: keep the last complete page and say nothing; the next poll tries again.
    try { if (!needsResume() || !(authPaused || manualWait)) await refresh(); }
    catch (error) { if (!offline.has(error)) reportError(error); }
    finally { if (valid() && pollMs > 0) timer = setTimeout(tick, pollMs); }
  };
  (async () => {
    showProgress();
    try { await initialize(); }
    catch (error) { reportError(error); }
    finally { if (valid() && covered(root).length && pollMs > 0) timer = setTimeout(tick, pollMs); }
  })();
  return controller;
}
