// Viewer-only bridge from fresh lamp grids to merged/LOD placed-model copies.
import * as THREE from '../../vendor/three-r187/three.module.js';
import { base, copyMaterialParams } from '../twin_library.js';
import { FT } from '../twin_light_math.js';
import { inPolygon } from '../twin_ground.js';
import { tintSum } from './lightmap_material.js';
import { decodeGridChunk } from './grid_chunk.js';
import { emitterTable, chooseEmitters, buildBrick, createModelLightTextures, fillFor } from './model_bricks.js';
import { patchModelLighting } from './model_light_material.js';

// Grid keys survive bake-controller remounts after a save. The view owns their
// lifetime; each load prunes keys no longer named by its compatible manifest.
const viewCaches = new WeakMap();
function cacheFor(view) {
  if (!viewCaches.has(view)) viewCaches.set(view, {chunks:new Map(), colors:new Map(), failures:new Map(), ownGeometry:new WeakSet()});
  return viewCaches.get(view);
}

// Rooms use their actual polygon and authored ceiling, not the grid's rounded
// cell bounds. Outdoor copies must never inherit a nearby room's fill.
function roomAt(layout, centre) {
  const p = new THREE.Vector3();
  for (const block of layout.blocks) {
    if (block.kind !== 'room') continue;
    p.copy(centre).applyMatrix4(block.toLocal);
    const sp = block.spacing / FT;
    if (p.z < -1e-6 || p.z * sp >= block.heightFt - 1e-6) continue;
    if (inPolygon(block.poly, block.origin[0] + p.x * sp, block.origin[1] + p.y * sp)) return block.atlasRoom;
  }
  return null;
}

function shallowGeometry(source) {
  const g = new THREE.BufferGeometry();
  g.index = source.index;
  g.attributes = { ...source.attributes };
  g.morphAttributes = { ...source.morphAttributes };
  g.morphTargetsRelative = source.morphTargetsRelative;
  g.groups = source.groups.map(group => ({ ...group }));
  g.drawRange = { ...source.drawRange };
  g.boundingBox = source.boundingBox?.clone() || null;
  g.boundingSphere = source.boundingSphere?.clone() || null;
  g.userData = { ...source.userData };
  return g;
}

function placedMesh(mesh) {
  const g = mesh.geometry, d = mesh.userData;
  if (!mesh.isMesh || !g?.userData.bakeExcluded || !g.attributes.position ||
      g.userData.bakeHeightfield || d.terrain || d.fireFlame || d.effectFixture || d.garageDoor || mesh.isInstancedMesh || mesh.layers.isEnabled(31)) return false;
  for (let p = mesh; p; p = p.parent) if (p.userData.ghost || p.userData.pendingImport) return false;
  return true;
}

// lights are the runtime's already-resolved bakeLights records (including shared
// channels and object lamps); don't resolve them a second, subtly different way.
export function mountModelLighting(view, { manifest, layout, fresh, tints, api = (path, init) => fetch(base() + path, init), lights = null }) {
  let stopped = false, serial = 0, textures = null, copies = [], table = [], builds = 0, buildMs = 0, loadedSignature = '';
  let initialized = false, copiesDirty = true, indicesInstalled = false, collections = 0, collectMs = 0, pendingCollectMs = 0, installedPalette = '', installedFills = '';
  let freshIds = new Set(fresh), active = new Set(), paletteKey = '', palette = new Set();
  const saved = cacheFor(view), cache = saved.chunks, colors = saved.colors, failures = saved.failures;
  const pending = new Map(), chunks = new Map(), rows = new Map(), installed = new Map();
  const geometries = new Set(), ownGeometry = saved.ownGeometry, materialCopies = new WeakMap(), ownMaterials = new WeakSet();
  let surfaceMaterials = new Set();
  const shared = { mvBricks: {value:null}, mvLamps: {value:null}, mvSize: {value:null} };
  const halt = new AbortController();
  const inferLights = lights === null;
  const atlasKey = () => manifest.key || view.bake?.state?.().key;
  let folded = 0, dropped = 0, foldedOrDropped = 0, fills = [], fillIds = new Set();
  const listeners = new Set();
  const notify = () => { for (const fn of listeners) fn(); };
  const black = new THREE.Color(0,0,0);
  for (const [id, tint] of tints || []) if (!colors.has(id)) colors.set(id, tint?.rgb ? tintSum([tint], true) : new THREE.Color(tint?.r || 0, tint?.g || 0, tint?.b || 0));

  function colorFor(device) {
    let color = colors.get(device);
    if (!color) {
      color = new THREE.Color(0,0,0); colors.set(device, color);
      if (device.startsWith('shared:')) for (const member of device.slice(7).split('+')) {
        const tint = colors.get(member); if (tint) color.add(tint);
      }
    }
    return color;
  }

  function clearIndices() {
    for (const g of geometries) {
      g.attributes.mvBrick.array.fill(0); g.attributes.mvBrick.needsUpdate = true;
    }
  }
  function attribute(mesh, separate) {
    if (separate && !ownGeometry.has(mesh.geometry)) {
      mesh.geometry = shallowGeometry(mesh.geometry); ownGeometry.add(mesh.geometry);
    }
    const g = mesh.geometry;
    if (!geometries.has(g)) {
      if (g.attributes.mvBrick?.count !== g.attributes.position.count) {
        g.setAttribute('mvBrick', new THREE.Float32BufferAttribute(new Float32Array(g.attributes.position.count), 1));
      } else g.attributes.mvBrick.array.fill(0);
      geometries.add(g);
    }
    return g.attributes.mvBrick;
  }
  function collect() {
    const start = performance.now();
    const byCopy = new Map(), point = new THREE.Vector3();
    surfaceMaterials = new Set();
    view.scene.updateMatrixWorld(true);
    view.scene.traverse(mesh => {
      const g = mesh.geometry, d = mesh.userData;
      if (!placedMesh(mesh)) {
        if (mesh.isMesh) for (const material of [].concat(mesh.material || [])) surfaceMaterials.add(material);
        return;
      }
      let owner = mesh;
      for (let p = mesh; p; p = p.parent) {
        if (p.userData.ghost || p.userData.pendingImport) return;
        if (p.isLOD || p.userData.pieceId) owner = p;
      }
      const ranges = d.snapRanges || [{start:0, count:g.attributes.position.count, ...owner.userData}];
      for (const r of ranges) {
        if (r.terrain || r.ghost || r.part === 'fire_flame') continue;
        // Every material/part/LOD of one placement shares its world-space brick.
        const key = r.pieceId != null ? `${r.buildingId || ''}:${r.pieceId}` : owner;
        let copy = byCopy.get(key);
        if (!copy) { copy = {box:new THREE.Box3(), ranges:[]}; byCopy.set(key, copy); }
        const end = Math.min(g.attributes.position.count, r.start + r.count);
        for (let i = r.start; i < end; i++) copy.box.expandByPoint(point.fromBufferAttribute(g.attributes.position, i).applyMatrix4(mesh.matrixWorld));
        copy.ranges.push({mesh, start:r.start, end, separate:!d.snapRanges || !!d.modelLod});
      }
    });
    const result = [...byCopy.values()].filter(copy => !copy.box.isEmpty());
    for (const copy of result) copy.room = roomAt(layout, copy.box.getCenter(point));
    collections++; collectMs = performance.now() - start; pendingCollectMs += collectMs;
    return result;
  }
  function patch(mesh) {
    const bind = original => {
      // Model caches already isolate their materials. Keep their live emissive
      // owners and late texture updates intact; clone only a material that is
      // also used by a non-model surface in this scene.
      if (!surfaceMaterials.has(original)) {
        patchModelLighting(original, shared);
        return original;
      }
      let material = original;
      if (!ownMaterials.has(material)) {
        material = materialCopies.get(original);
        if (!material) {
          material = original.clone();
          material.onBeforeCompile = original.onBeforeCompile;
          material.customProgramCacheKey = original.customProgramCacheKey;
          view.prepareViewingMaterial?.(original, material);
          const sync = () => copyMaterialParams(original, material);
          original.addEventListener('materialparamschange', sync);
          material.addEventListener('dispose', () => {
            original.removeEventListener('materialparamschange', sync);
            if (materialCopies.get(original) === material) materialCopies.delete(original);
          });
          if (original.userData.ready?.then) original.userData.ready.then(sync);
          materialCopies.set(original, material); ownMaterials.add(material);
        }
      }
      patchModelLighting(material, shared);
      return material;
    };
    mesh.material = Array.isArray(mesh.material) ? mesh.material.map(bind) : bind(mesh.material);
  }
  function readPalette() {
    const next = view.live?.paletteLines?.() || [], key = [...next].sort().join('\n');
    if (key === paletteKey) return false;
    paletteKey = key; palette = new Set(next); return true;
  }
  const excluded = id => palette.has(id) || palette.has(lights?.find(l => l.device === id)?.entity);
  const deviceSignature = id => JSON.stringify([manifest.lights[id]?.grid, lights?.find(l => l.device === id)]);
  const fillSignature = () => JSON.stringify(Object.entries(manifest.lights || {}).map(([id,e]) => [id,e.fill]));
  function availableIds() {
    const available = new Set();
    for (const id of freshIds) {
      const e = manifest.lights?.[id], chunk = cache.get(e?.grid);
      if (!excluded(id) && e?.gridLayout === layout.hash && chunk?.layoutHash === layout.hash && chunk.device === id) available.add(id);
    }
    return available;
  }
  function writeFills() {
    if (!textures) return;
    for (let i = 0; i < fills.length; i++) {
      const copy = fills[i], fill = copy.fill;
      fill.setRGB(0,0,0);
      for (let j = 0; j < copy.terms.length; j++) {
        const term = copy.terms[j];
        if (!fillIds.has(term.device)) continue;
        fill.r += term.color.r * term.weight; fill.g += term.color.g * term.weight; fill.b += term.color.b * term.weight;
      }
      textures.writeBrickFill(i, fill);
    }
  }
  function syncFreshness() {
    const next = availableIds();
    for (const id of next) if (installed.get(id) !== deviceSignature(id)) next.delete(id);
    let changed = false;
    for (const [device, indices] of rows) if (active.has(device) !== next.has(device)) {
      changed = true;
      for (const row of indices) textures.setTint(row, next.has(device) ? colorFor(device) : black);
    }
    active = next;
    const nextFill = new Set([...freshIds].filter(id => manifest.lights?.[id] && !excluded(id)));
    const fillChanged = nextFill.size !== fillIds.size || [...nextFill].some(id => !fillIds.has(id));
    fillIds = nextFill;
    if (changed || fillChanged) writeFills();
    return changed || fillChanged;
  }
  function collectCopies() {
    if (!copiesDirty) return;
    copies = collect(); copiesDirty = false; indicesInstalled = false;
  }
  function fillTerms(copy) {
    const terms = [];
    if (copy.room !== null) for (const [device,e] of Object.entries(manifest.lights || {})) {
      const weight = e.fill?.[copy.room];
      if (weight > 0) terms.push({device, color:colorFor(device), weight});
    }
    return terms;
  }
  function needsBuild(available) {
    if (!available.size) return false;
    return !loadedSignature || !textures || installedPalette !== paletteKey ||
      [...available].some(id => installed.get(id) !== deviceSignature(id));
  }
  function rebuild() {
    if (stopped || !initialized) return;
    const start = performance.now();
    readPalette(); collectCopies(); syncFreshness();
    const available = availableIds();
    const nextTable = emitterTable(lights, available, manifest, {paletteLines:palette, plan:view.bakePlan || view.plan});
    if (!copies.length || !nextTable.length) return; // No grid: no texture, attribute, material or program.
    chunks.clear();
    for (const id of available) chunks.set(id, cache.get(manifest.lights[id].grid));
    for (const record of nextTable) colorFor(record.device);
    // Prepare every brick before touching the live bindings/indices. The
    // following synchronous upload/attribute phase swaps the complete result.
    const built = copies.map(copy => {
      const chosen = chooseEmitters(copy.box, nextTable, {layout, chunks});
      const terms = fillTerms(copy), fill = fillFor(manifest, copy.room, colors, fillIds);
      return {chosen, data:buildBrick({layout, chunks}, copy.box, chosen.ids), fill, terms};
    });
    let old = null;
    if (!textures) textures = createModelLightTextures({maxBricks:copies.length, maxEmitters:nextTable.length});
    else if (copies.length > textures.maxBricks || nextTable.length > textures.maxEmitters) {
      old = textures; textures = old.grow(copies.length, nextTable.length);
    }
    table = nextTable; active = available; installed.clear(); rows.clear(); fills = []; folded = dropped = foldedOrDropped = 0;
    for (const record of table) {
      installed.set(record.device, deviceSignature(record.device));
      if (!rows.has(record.device)) rows.set(record.device, []);
      rows.get(record.device).push(record.row);
      textures.writeEmitter(record.row, record); textures.setTint(record.row, colorFor(record.device));
    }
    // Copy order is the brick assignment. Lamp-only builds reuse that order
    // and its vertex buffers; recollection invalidates the assignment.
    if (!indicesInstalled) { clearIndices(); geometries.clear(); }
    for (let i = 0; i < copies.length; i++) {
      const copy = copies[i], ready = built[i];
      copy.fill = ready.fill; copy.terms = ready.terms; fills.push(copy);
      textures.writeBrick(i, ready.data, ready.chosen, ready.fill, copy.box);
      folded += ready.chosen.folded; dropped += ready.chosen.dropped;
      if (ready.chosen.folded > 0 || ready.chosen.dropped > 0) foldedOrDropped++;
      for (const range of copy.ranges) {
        if (!indicesInstalled) {
          const a = attribute(range.mesh, range.separate);
          range.geometry = range.mesh.geometry;
          a.array.fill(i + 1, range.start, range.end); a.needsUpdate = true;
        }
        patch(range.mesh);
      }
    }
    indicesInstalled = true;
    shared.mvBricks.value = textures.bricks; shared.mvLamps.value = textures.lamps; shared.mvSize.value = textures.mvSize;
    old?.dispose();
    installedPalette = paletteKey; installedFills = fillSignature();
    loadedSignature = JSON.stringify([...installed]);
    builds++; buildMs = performance.now() - start + pendingCollectMs; pendingCollectMs = 0;
    notify();
    const ready = view.renderer3.compileAsync?.(view.scene, view.camera) || view.compileBehind?.();
    ready?.catch?.(error => console.warn('Model lighting program unavailable:', error));
    view.render?.();
  }
  function prune() {
    // Stale but still authored lamp grids remain wanted for their next rebake;
    // deleted lamps, changed keys and incompatible layouts cannot grow the cache.
    const wanted = new Set(Object.values(manifest.lights || {}).filter(e => e.grid && e.gridLayout === layout.hash).map(e => e.grid));
    for (const key of cache.keys()) if (!wanted.has(key)) cache.delete(key);
    for (const key of failures.keys()) if (!wanted.has(key)) failures.delete(key);
  }
  async function update(nextFresh, nextManifest = manifest, nextLights = lights) {
    if (stopped) return;
    freshIds = new Set(nextFresh); manifest = nextManifest; lights = nextLights;
    observeLive(); readPalette();
    const mine = ++serial;
    // Retire only departing rows. Other lamps and every existing brick remain
    // live while missing chunks download; no geometry walk on a lamp change.
    if (syncFreshness()) view.render?.();
    if (inferLights && (!lights || copiesDirty)) {
      const {bakeLights} = await import('./runtime.js');
      if (stopped || mine !== serial) return;
      lights = bakeLights(view.live?.layout?.() || {}, view.scene, view.bakePlan || view.plan);
    }
    initialized = true;
    const geometryChanged = copiesDirty;
    collectCopies(); prune();
    const syncDebugChunks = () => {
      chunks.clear();
      for (const id of availableIds()) chunks.set(id, cache.get(manifest.lights[id].grid));
      notify();
    };
    if (!copies.length) {
      clearIndices(); geometries.clear(); table = []; fills = []; rows.clear(); installed.clear();
      loadedSignature = '';
      if (!view.gridDebug) return;
      syncDebugChunks();
    }
    if (copies.length && textures && installedFills !== fillSignature()) {
      for (const copy of fills) copy.terms = fillTerms(copy);
      installedFills = fillSignature(); writeFills(); view.render?.();
    }
    if (copies.length && (geometryChanged || needsBuild(availableIds()))) rebuild(); // Cache hits install before the first await.
    const atlas = atlasKey(), wanted = [];
    if (atlas) for (const id of freshIds) {
      const e = manifest.lights?.[id];
      if (!e?.grid || e.gridLayout !== layout.hash || excluded(id)) continue;
      const key = e.grid;
      if (cache.has(key) || (failures.get(key)?.next || 0) > Date.now()) continue;
      wanted.push({id, key});
      if (!pending.has(key)) pending.set(key, Promise.resolve().then(async () => {
        try {
          const response = await api(`api/house/bakes/${atlas}/grid/${key}.bin`, {signal:halt.signal});
          if (!response.ok) throw new Error(`Grid read returned HTTP ${response.status}.`);
          const chunk = await decodeGridChunk(await response.arrayBuffer(), {signal:halt.signal});
          if (chunk.layoutHash !== layout.hash || chunk.device !== id || chunk.indices.some(i => i >= layout.count)) throw new Error('Grid chunk does not match its lamp/layout.');
          if (!stopped && Object.values(manifest.lights || {}).some(e => e.grid === key && e.gridLayout === layout.hash)) {
            cache.set(key, chunk); failures.delete(key);
          }
        } catch (error) {
          if (!stopped) {
            const previous = failures.get(key), attempts = (previous?.attempts || 0) + 1;
            failures.set(key, {attempts, next:Date.now() + Math.min(300000, 5000 * 2 ** Math.min(attempts - 1, 6))});
            if (!previous) console.warn('Model lighting grid unavailable; retrying with backoff:', id, error);
          }
        } finally { pending.delete(key); }
      }));
    }
    if (!wanted.length) return;
    await Promise.all(wanted.map(({key}) => pending.get(key)));
    if (stopped || mine !== serial) return;
    prune();
    if (copies.length) { if (needsBuild(availableIds())) rebuild(); }
    else if (view.gridDebug) syncDebugChunks();
  }
  // Called from the existing lamp tint path, including mode-hidden zero. A
  // device gets one stored colour on first sight; subsequent calls allocate
  // nothing and only update emitter/fill rows, never bricks or geometry.
  function setTint(device, tint) {
    if (stopped) return;
    const color = colorFor(device);
    color.setRGB(tint?.r || 0, tint?.g || 0, tint?.b || 0);
    const indices = rows.get(device);
    if (textures && indices) for (let i = 0; i < indices.length; i++) textures.setTint(indices[i], active.has(device) ? color : black);
    writeFills();
  }
  const host = view.renderer3.domElement.parentElement;
  const rebuilt = () => {
    copiesDirty = true;
    update(freshIds).catch(error => console.warn('Model lighting rebuild failed:', error));
  };
  host?.addEventListener('twinrebuilt', rebuilt);
  host?.addEventListener('twinyardrebuilt', rebuilt);
  let subscribed = null, unsubscribe = null;
  function observeLive() {
    if (subscribed === view.live) return;
    unsubscribe?.(); subscribed = view.live;
    unsubscribe = subscribed?.subscribe?.(() => {
      if (readPalette()) update(freshIds).catch(error => console.warn('Model lighting palette update failed:', error));
    });
  }
  observeLive();
  return {
    update, setTint, rebuild,
    get textures() { return textures; },
    get layout() { return layout; },
    get chunks() { return chunks; },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    stats: () => ({bricks:copies.length, emitters:table.length, folded, dropped, foldedOrDropped, builds, buildMs, collections, collectMs, cachedChunks:cache.size, loadedSignature,
      bricksSize:textures ? [textures.bricks.image.width,textures.bricks.image.height,textures.bricks.image.depth] : null,
      lampsSize:textures ? [textures.lamps.image.width,textures.lamps.image.height] : null,
      bytes:textures ? textures.bricks.image.data.byteLength + textures.lamps.image.data.byteLength : 0}),
    stop() {
      if (stopped) return;
      stopped = true; ++serial; halt.abort(); unsubscribe?.(); listeners.clear();
      host?.removeEventListener('twinrebuilt', rebuilt); host?.removeEventListener('twinyardrebuilt', rebuilt);
      clearIndices(); textures?.dispose(); chunks.clear(); geometries.clear();
      // Materials stay patched between mounts. Null samplers cannot re-upload
      // disposed textures; zero mvBrick indices skip model lighting.
      shared.mvBricks.value = null; shared.mvLamps.value = null;
    },
  };
}
