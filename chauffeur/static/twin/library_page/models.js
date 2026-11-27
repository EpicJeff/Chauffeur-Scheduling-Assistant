import * as THREE from 'three';
import {
  libUrl, materialUrl, rememberImport, forgetImport, loadModel,
  applyPartMaterials, modelMaterialKit, kitMaterial, disposeObject,
} from '../twin_library.js';
import { uploadFiles, buildLevels, pendingLevels } from '../model_levels.js';
import { DEFAULT_LOD_PERCENT, resolvePart } from '../model_parts.js';
import { modelBudget, suggestKind } from '../objects.js';
import { createThumbnailRenderer } from '../model_thumbnails.js';
import { createSlotRow, slotDragTarget, sendSlotDrag } from '../editor/slot_row.js';
import { createPreview } from './preview.js';
import { node, button } from './properties.js';

const KINDS = [
  ['furniture', 'Furniture'], ['decor', 'Decor'], ['plant', 'Plant'],
  ['door', 'Door'], ['window', 'Window'], ['car', 'Car'], ['lamp', 'Lamp'], ['other', 'Other'],
];
const MODEL_FILES = /\.(glb|gltf|dae|zip|kmz)$/i;
const METRES_PER_INCH = 0.0254;
const LEVEL_NAMES = ['Full', 'Mid', 'Far'];
const LOD_FILES = ['lod0.glb', 'lod1.glb', 'lod2.glb'];

function formatBytes(bytes) {
  if (!(bytes >= 0)) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatTriangles(triangles) {
  if (!(triangles >= 0)) return '';
  return `${Math.round(triangles).toLocaleString()} tris`;
}

function metresToFeetInches(metres) {
  if (!(metres > 0)) return { feet: '', inches: '' };
  const totalInches = Math.round((metres / METRES_PER_INCH) * 100) / 100;
  const feet = Math.floor(totalInches / 12);
  const inches = Math.round((totalInches - feet * 12) * 100) / 100;
  return { feet: String(feet), inches: String(inches) };
}

function feetInchesToMetres(feetRaw, inchesRaw) {
  const fText = String(feetRaw ?? '').trim(), iText = String(inchesRaw ?? '').trim();
  if (!fText && !iText) return null;
  const feet = fText ? Number(fText) : 0, inches = iText ? Number(iText) : 0;
  if (!Number.isFinite(feet) || !Number.isFinite(inches) || feet < 0 || inches < 0) return NaN;
  const totalInches = feet * 12 + inches;
  if (totalInches <= 0) return null;
  return Math.round(totalInches * METRES_PER_INCH * 1e6) / 1e6;
}

function materialThumb(row) {
  if (!row) return null;
  if (row.thumbnail_url) return window.chfAuthUrl ? window.chfAuthUrl(row.thumbnail_url) : row.thumbnail_url;
  const path = row.maps?.base_color || window.twinManifest?.[row.id]?.maps?.base_color;
  if (path) return materialUrl(path.startsWith('materials/') ? path : `materials/${row.id}/${path}`);
  const asset = window.twinManifest?.[row.id];
  const file = Object.keys(asset?.files || {}).find(name => name.includes('_diff_'));
  return file ? libUrl(row.id, file) : null;
}

function visualKey(row, matGen = 0) {
  return JSON.stringify([row?.revision || 0, row?.fix || null, row?.materials || null, Object.keys(row?.materials || {}).length ? matGen : 0]);
}

function modelThumb(row, localEntry, matGen) {
  if (localEntry?.url && localEntry.key === visualKey(row, matGen)) return localEntry.url;
  if (!row?.thumbnail) return null;
  const url = libUrl(row.id, row.thumbnail);
  return row.revision ? `${url}${url.includes('?') ? '&' : '?'}v=${row.revision}` : url;
}

function countTriangles(object) {
  let triangles = 0;
  object?.traverse(o => {
    if (o.isMesh && o.geometry) triangles += (o.geometry.index?.count || o.geometry.attributes.position?.count || 0) / 3;
  });
  return Math.round(triangles);
}

export function mountModels(root, {
  api,
  initialModelId = null,
  materials: initialMaterials = [],
  onOpenMaterial = null,
  buildLevels: buildLevelsFn = buildLevels,
  uploadFiles: uploadFilesFn = uploadFiles,
  loadModel: loadModelFn = loadModel,
  createPreview: createPreviewFn = createPreview,
} = {}) {
  const abort = new AbortController(), { signal } = abort;
  let stopped = false, importing = false, rows = [], materialRows = [...(initialMaterials || [])];
  let materialsLoaded = (initialMaterials || []).length > 0;
  let current = null, currentLevel = 0, currentObject = null, currentObjectRecord = null, currentObjectLease = null, loadedTriangles = null;
  let selectTurn = 0, previewTurn = 0, previewPending = false, materialGen = 0, cacheGen = 0;
  let gridAbort = null, paletteAbort = null, propAbort = null;
  let selectedMaterial = null, dragState = null;
  let writeChain = Promise.resolve(), thumbQueue = Promise.resolve();
  let propsSignature = null, propSyncFns = [];
  const slotRows = [], slotSubscribers = new Set();
  const buildState = new Map(); // id -> { token, controller }
  const originalBytes = new Map(); // id -> number
  const localThumbs = new Map(); // id -> { url, key }
  const gridImages = new Map(); // id -> img element
  const thumbInFlight = new Map(); // key -> Promise<string|null>
  const ownedGeometries = new WeakMap(); // Object3D -> Set<BufferGeometry>

  const createCache = () => ({ id: ++cacheGen, map: new Map(), users: 0, retired: false });
  let activeCache = createCache();
  const retiredCaches = new Set();

  const report = error => {
    if (!stopped && !error?.cancelled) window.showGlobalAlert(error?.message || String(error));
  };
  const sendEditor = (path, method, body) => api('editor/' + path, method, body);
  const latestRecord = id => rows.find(r => r.id === id) || (current?.id === id ? current : null);
  const isSelected = (id, turn) => !stopped && current?.id === id && selectTurn === turn;

  function drainCache(cache) {
    if (!cache) return;
    const materials = new Set(cache.map.values()), textures = new Set();
    for (const m of materials) {
      if (!m || typeof m.dispose !== 'function') continue;
      for (const [key, value] of Object.entries(m)) {
        if (value?.isTexture && key !== 'envMap') textures.add(value);
      }
      m.dispose();
    }
    textures.forEach(t => t.dispose());
    cache.map.clear();
    retiredCaches.delete(cache);
  }

  function keepCacheMaterials() {
    const keep = new Set(activeCache.map.values());
    for (const cache of retiredCaches) for (const m of cache.map.values()) keep.add(m);
    return keep;
  }

  function trackGeometries(object) {
    if (!object) return;
    let set = ownedGeometries.get(object);
    if (!set) { set = new Set(); ownedGeometries.set(object, set); }
    object.traverse(o => { if (o.geometry) set.add(o.geometry); });
  }

  function releaseModelObject(object, record, kit) {
    if (!object) return;
    trackGeometries(object);
    const tracked = ownedGeometries.get(object) || new Set();
    // Restore original copyModel-owned geometries and materials so UV variants and
    // originals are both released while cache-owned materials remain managed by drainCache.
    if (record) applyPartMaterials(object, { id: record.id, parts: record.parts || [], materials: {} }, {}, kit || {});
    trackGeometries(object);
    const keepMaterials = keepCacheMaterials();
    const disposed = new Set();
    object.traverse(o => { if (o.geometry) disposed.add(o.geometry); });
    disposeObject(object, { keepMaterials });
    for (const g of tracked) {
      if (!disposed.has(g)) g.dispose();
    }
    ownedGeometries.delete(object);
  }

  function buildKitForCache(cacheMap) {
    const manifest = { ...(window.twinManifest || {}) };
    // page_manifest() includes archived household materials without an archived flag.
    // Mark any household material absent from the active catalogue as archived so
    // applyPartMaterials falls back to the original and logs once (Review Focus 1).
    if (materialsLoaded) {
      const activeIds = new Set(materialRows.filter(r => !r.archived).map(r => r.id));
      for (const [id, entry] of Object.entries(manifest)) {
        if (entry?.kind === 'material' && entry.household && !activeIds.has(id)) {
          manifest[id] = { ...entry, archived: true };
        }
      }
    }
    for (const row of materialRows) {
      if (row.source === 'builtin' || row.builtin) continue;
      if (row.params && row.maps) {
        manifest[row.id] = {
          kind: 'material', household: true, revision: row.revision, params: row.params,
          ...(row.archived ? { archived: true } : {}),
          maps: Object.fromEntries(Object.entries(row.maps).filter(([, p]) => p)
            .map(([slot, path]) => [slot, path.startsWith('materials/') ? path : `materials/${row.id}/${path}`])),
        };
      }
    }
    const baseKit = { ...(window.twinKit || { materials: {} }), manifest };
    const roleMaterial = role => {
      if (!cacheMap.has('role:' + role)) cacheMap.set('role:' + role, kitMaterial(role, baseKit, 'high'));
      return cacheMap.get('role:' + role);
    };
    return modelMaterialKit(baseKit, 'high', cacheMap, roleMaterial);
  }

  function acquireKit() {
    const cache = activeCache;
    cache.users++;
    const kit = buildKitForCache(cache.map);
    let released = false;
    return {
      kit,
      cache,
      release() {
        if (released) return;
        released = true;
        cache.users--;
        if (cache.retired && cache.users <= 0) drainCache(cache);
      },
    };
  }

  const thumbRenderer = createThumbnailRenderer({ width: 112, height: 96, fallbackBox: false });

  function renderMissingThumbnail(record) {
    const expectedKey = visualKey(record, materialGen);
    const flightKey = `${record.id}:${expectedKey}`;
    if (thumbInFlight.has(flightKey)) return thumbInFlight.get(flightKey);
    const job = thumbQueue.then(async () => {
      if (stopped || thumbRenderer.disposed) return null;
      const lease = acquireKit();
      let object = null;
      try {
        object = await loadModelFn(record.id, lease.kit, undefined, { editor: true });
        if (!object) return null;
        trackGeometries(object);
        if (stopped || thumbRenderer.disposed || lease.cache.retired) {
          releaseModelObject(object, record, lease.kit);
          object = null;
          return null;
        }
        applyPartMaterials(object, record, {}, lease.kit);
        trackGeometries(object);
        const handed = object;
        object = null;
        return thumbRenderer.render(handed, { release: o => releaseModelObject(o, record, lease.kit) });
      } catch {
        return null;
      } finally {
        if (object) releaseModelObject(object, record, lease.kit);
        lease.release();
        thumbInFlight.delete(flightKey);
      }
    });
    thumbQueue = job.then(() => {}, () => {});
    thumbInFlight.set(flightKey, job);
    return job;
  }

  function materialEntry(id) {
    const row = materialRows.find(m => m.id === id && !m.archived);
    if (!row) return id ? { id, kind: 'material', name: id } : null;
    return { id: row.id, kind: 'material', name: row.name, color: row.color || row.params?.tint || '#b8b0a4', thumb: materialThumb(row) };
  }

  const slotLibrary = {
    selected: () => selectedMaterial,
    onSelect: fn => { slotSubscribers.add(fn); return () => slotSubscribers.delete(fn); },
    reveal: async (kind, id) => { if (kind === 'material' && id) onOpenMaterial?.(id); },
  };
  function setSelectedMaterial(entry) {
    selectedMaterial = entry;
    paletteGrid.querySelectorAll('[data-palette-material]').forEach(btn => {
      btn.setAttribute('aria-pressed', String(btn.dataset.paletteMaterial === entry?.id));
    });
    for (const fn of slotSubscribers) fn(entry);
  }

  root.replaceChildren();
  const status = node('output', 'Opening Models…', 'place-muted'); status.setAttribute('role', 'status');
  root.append(
    node('p', 'Changes here apply to every copy of this model unless overridden on a placed copy.', 'place-muted'),
    status,
  );
  const layout = node('div', null, 'library-layout');
  const left = node('section', null, 'library-browser'); left.setAttribute('aria-label', 'Model catalogue');
  const centre = node('section', null, 'library-preview'); centre.setAttribute('aria-label', 'Live model preview');
  const right = node('aside', null, 'library-properties'); right.setAttribute('aria-label', 'Model properties');
  layout.append(left, centre, right);
  root.append(layout);

  // Left column: import, filters, model grid, and materials palette for dragging / Use selected.
  const importInput = node('input'); importInput.type = 'file'; importInput.multiple = true; importInput.hidden = true;
  importInput.dataset.modelFiles = '';
  importInput.accept = '.glb,.gltf,.dae,.zip,.kmz,.bin,.png,.jpg,.jpeg,.webp';
  importInput.setAttribute('aria-label', 'Import model files');
  const importButton = button('Import model', 'import-model', () => { if (!importing) importInput.click(); }, signal);
  importInput.addEventListener('change', async () => {
    try { await importModel(Array.from(importInput.files || [])); }
    finally { importInput.value = ''; }
  }, { signal });
  const search = node('input'); search.type = 'search'; search.placeholder = 'Search models';
  search.dataset.modelSearch = ''; search.setAttribute('aria-label', 'Search models');
  const sourceFilter = node('select'); sourceFilter.dataset.modelSource = ''; sourceFilter.setAttribute('aria-label', 'Model source');
  for (const [value, label] of [['all', 'All'], ['builtin', 'Built-in'], ['mine', 'Mine']]) {
    const opt = node('option', label); opt.value = value; sourceFilter.append(opt);
  }
  sourceFilter.value = 'all';
  const kindFilter = node('select'); kindFilter.dataset.modelKind = ''; kindFilter.setAttribute('aria-label', 'Model kind');
  const allKindsOpt = node('option', 'All kinds'); allKindsOpt.value = 'all'; kindFilter.append(allKindsOpt);
  for (const [value, label] of KINDS) {
    const opt = node('option', label); opt.value = value; kindFilter.append(opt);
  }
  kindFilter.value = 'all';
  const grid = node('div', null, 'library-grid'); grid.dataset.modelGrid = '';

  const palette = node('section', null, 'library-palette'); palette.setAttribute('aria-label', 'Materials to apply');
  palette.append(node('h3', 'Materials'), node('p', 'Drag onto a part or select and click Use selected.', 'place-muted'));
  const paletteSearch = node('input'); paletteSearch.type = 'search'; paletteSearch.placeholder = 'Search materials';
  paletteSearch.dataset.paletteSearch = ''; paletteSearch.setAttribute('aria-label', 'Search materials to apply');
  const paletteGrid = node('div', null, 'library-grid library-palette-grid'); paletteGrid.dataset.paletteGrid = '';
  palette.append(paletteSearch, paletteGrid);

  left.append(importButton, importInput, search, sourceFilter, kindFilter, grid, palette);
  search.addEventListener('input', drawGrid, { signal });
  sourceFilter.addEventListener('change', drawGrid, { signal });
  kindFilter.addEventListener('change', drawGrid, { signal });
  paletteSearch.addEventListener('input', drawPalette, { signal });

  // Centre column: level switcher, wireframe toggle, lighting, 3D preview canvas, progress.
  const levelBar = node('div', null, 'editor-actions library-level-row');
  levelBar.setAttribute('role', 'group'); levelBar.setAttribute('aria-label', 'Detail level');
  const levelButtons = LEVEL_NAMES.map((label, level) => {
    const btn = button(label, `level-${level}`, () => setLevel(level), signal);
    btn.dataset.modelLevel = String(level);
    btn.setAttribute('aria-pressed', String(level === 0));
    levelBar.append(btn);
    return btn;
  });
  const wireframeButton = button('Wireframe', 'wireframe', () => {
    const next = !preview.isWireframe();
    preview.setWireframe(next);
    wireframeButton.setAttribute('aria-pressed', String(next));
  }, signal);
  wireframeButton.setAttribute('aria-pressed', 'false');
  levelBar.append(wireframeButton);

  const levelStats = node('p', '', 'place-muted library-level-meta'); levelStats.dataset.levelStats = '';
  const canvas = node('canvas'); canvas.setAttribute('aria-label', 'Orbit model preview with 6 ft scale figure');
  const progressOut = node('output', '', 'place-muted'); progressOut.dataset.modelProgress = ''; progressOut.setAttribute('aria-live', 'polite');
  const lighting = node('div', null, 'editor-actions');
  lighting.setAttribute('role', 'group'); lighting.setAttribute('aria-label', 'Preview lighting');
  centre.append(
    levelBar, levelStats, canvas,
    node('p', '6 ft scale figure · Drag to orbit · Scroll or pinch to zoom · Drop a material onto a part', 'place-muted'),
    lighting, progressOut,
  );
  const preview = createPreviewFn(canvas, { onPartDrop: (partKey, materialId) => applyPartMaterial(partKey, materialId) });
  for (const [value, title] of [['studio', 'Neutral studio'], ['sun', 'House day sun']]) {
    const control = button(title, value, () => {
      preview.setLight(value);
      lighting.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === control)));
    }, signal);
    control.setAttribute('aria-pressed', String(value === 'studio')); lighting.append(control);
  }

  // Right column: actions + properties.
  const actionsBar = node('div', null, 'editor-actions'); actionsBar.dataset.modelActions = '';
  const propsHost = node('div');
  right.append(actionsBar, propsHost);

  // File drop imports a model on the Models tab (right panel or left panel).
  for (const dropZone of [right, left]) {
    dropZone.addEventListener('dragover', event => {
      if (Array.from(event.dataTransfer?.types || []).includes('Files')) {
        event.preventDefault();
        event.dataTransfer.dropEffect = importing ? 'none' : 'copy';
      }
    }, { signal });
    dropZone.addEventListener('drop', event => {
      const files = Array.from(event.dataTransfer?.files || []);
      if (!files.length) return;
      event.preventDefault();
      importModel(files);
    }, { signal });
  }

  // Pointer drag from palette onto 3D preview or slot rows (touch + mouse).
  let hoveredSlotRow = null;
  document.addEventListener('pointermove', event => {
    if (!dragState || dragState.pointer !== event.pointerId) return;
    if (!dragState.moved && Math.hypot(event.clientX - dragState.x, event.clientY - dragState.y) < 4) return;
    dragState.moved = true;
    const hitEl = typeof document.elementFromPoint === 'function' ? document.elementFromPoint(event.clientX, event.clientY) : null;
    const row = slotDragTarget(hitEl);
    if (hoveredSlotRow && hoveredSlotRow !== row) sendSlotDrag(hoveredSlotRow, 'leave', dragState.entry);
    hoveredSlotRow = row;
    if (row) {
      preview.highlightPart(null);
      sendSlotDrag(row, 'over', dragState.entry);
      return;
    }
    const key = preview.partAt(event.clientX, event.clientY);
    preview.highlightPart(key);
  }, { signal });
  document.addEventListener('pointerup', event => {
    if (!dragState || dragState.pointer !== event.pointerId) return;
    const state = dragState; dragState = null;
    const prevRow = hoveredSlotRow; hoveredSlotRow = null;
    if (!state.moved) return;
    state.suppressClick = true;
    if (prevRow) { sendSlotDrag(prevRow, 'drop', state.entry); return; }
    const key = preview.partAt(event.clientX, event.clientY);
    preview.highlightPart(null);
    if (key) applyPartMaterial(key, state.entry.id);
  }, { signal });

  function updateRow(record) {
    const idx = rows.findIndex(r => r.id === record.id);
    if (idx === -1) rows.push(record); else rows[idx] = record;
    drawGrid();
  }

  function levelInfo(record, level) {
    if (!record) return { triangles: null, bytes: null, percent: DEFAULT_LOD_PERCENT[level], available: false };
    const percent = record.lod_percent?.[level] ?? DEFAULT_LOD_PERCENT[level];
    if (level === 0) {
      const lod0 = percent < 100 ? record.lods?.find(l => l.name === 'lod0.glb') : null;
      if (lod0) return { triangles: lod0.triangles, bytes: lod0.bytes, percent: lod0.percent ?? percent, available: true, file: 'lod0.glb' };
      const tris = record.triangles ?? (record.parts?.length ? record.parts.reduce((s, p) => s + (p.triangles || 0), 0) : loadedTriangles);
      const bytes = record.bytes ?? originalBytes.get(record.id) ?? null;
      return { triangles: tris, bytes, percent, available: true, file: null };
    }
    const lodName = LOD_FILES[level];
    const lod = record.lods?.find(l => l.name === lodName);
    if (lod) return { triangles: lod.triangles, bytes: lod.bytes, percent: lod.percent ?? percent, available: true, file: lodName };
    return { triangles: null, bytes: null, percent, available: false, file: lodName };
  }

  function paintLevelBar() {
    if (!current) { levelStats.textContent = ''; return; }
    for (let i = 0; i < 3; i++) {
      const btn = levelButtons[i];
      if (current.builtin && i > 0) { btn.hidden = true; continue; }
      btn.hidden = false;
      const info = levelInfo(current, i);
      const bits = [LEVEL_NAMES[i]];
      if (info.triangles != null) bits.push(formatTriangles(info.triangles));
      if (info.bytes != null) bits.push(formatBytes(info.bytes));
      btn.textContent = bits.join(' · ');
      btn.disabled = i > 0 && !info.available;
      btn.setAttribute('aria-pressed', String(currentLevel === i));
    }
    const active = levelInfo(current, currentLevel);
    const parts = [`${LEVEL_NAMES[currentLevel]} (${active.percent}%)`];
    if (active.triangles != null) parts.push(`${Math.round(active.triangles).toLocaleString()} triangles`);
    if (active.bytes != null) parts.push(formatBytes(active.bytes));
    if (currentLevel > 0 && !active.available) parts.push('Building…');
    levelStats.textContent = parts.join(' · ');
  }

  async function ensureOriginalBytes(record) {
    if (!record || record.builtin || record.bytes != null || originalBytes.has(record.id) || !record.model) return;
    try {
      const res = await fetch(libUrl(record.id, record.model));
      if (!res.ok) return;
      const headerLen = Number(res.headers.get('content-length'));
      const size = Number.isFinite(headerLen) && headerLen > 0 ? headerLen : (await res.arrayBuffer()).byteLength;
      if (size > 0) { originalBytes.set(record.id, size); if (current?.id === record.id) paintLevelBar(); }
    } catch { /* Offline or unreadable size leaves bytes blank. */ }
  }

  async function showPreview({ refit = false, reapplyOnly = false, skipAutoThumb = false } = {}) {
    if (!current || stopped) return;
    if (reapplyOnly && currentObject) {
      const lease = acquireKit();
      try {
        applyPartMaterials(currentObject, current, {}, lease.kit);
        trackGeometries(currentObject);
        currentObjectRecord = current;
        const oldLease = currentObjectLease;
        currentObjectLease = lease;
        oldLease?.release();
        paintLevelBar();
      } catch (error) {
        lease.release();
        throw error;
      }
      return;
    }
    const turn = ++previewTurn;
    const selTurn = selectTurn;
    const record = current;
    if (currentLevel > 0 && !record.lods?.some(l => l.name === LOD_FILES[currentLevel])) {
      currentLevel = 0;
    }
    const requestedLod = currentLevel ? LOD_FILES[currentLevel] : null;
    rememberImport(record);
    const lease = acquireKit();
    let pendingObject = null;
    let leaseTransferred = false;
    previewPending = true;
    try {
      const loaded = await loadModelFn(record.id, lease.kit, undefined, { editor: true, lodName: requestedLod });
      if (!loaded) {
        if (!stopped && turn === previewTurn && !lease.cache.retired && isSelected(record.id, selTurn)) paintLevelBar();
        return;
      }
      pendingObject = loaded;
      trackGeometries(loaded);
      if (stopped || turn !== previewTurn || lease.cache.retired || !isSelected(record.id, selTurn)) {
        return;
      }
      applyPartMaterials(loaded, record, {}, lease.kit);
      trackGeometries(loaded);
      loadedTriangles = countTriangles(loaded);
      const oldObject = currentObject, oldRecord = currentObjectRecord, oldLease = currentObjectLease;
      currentObject = loaded;
      currentObjectRecord = record;
      currentObjectLease = lease;
      pendingObject = null;
      leaseTransferred = true;
      preview.setModel(loaded, { refit });
      releaseModelObject(oldObject, oldRecord, oldLease?.kit || lease.kit);
      oldLease?.release();
      paintLevelBar();
      // If this model has no cached/saved thumbnail for its current visuals, populate its card from the live preview.
      const expectedKey = visualKey(record, materialGen);
      const cachedThumb = localThumbs.get(record.id);
      if (!skipAutoThumb && !record.thumbnail && (!cachedThumb || cachedThumb.key !== expectedKey)) {
        const url = preview.captureThumbnail();
        if (url && typeof canvas.toDataURL === 'function') {
          localThumbs.set(record.id, { url, key: expectedKey });
          const img = gridImages.get(record.id);
          if (img) img.src = url;
        }
      }
    } catch (error) {
      if (!stopped && turn === previewTurn && !lease.cache.retired && isSelected(record.id, selTurn)) report(error);
    } finally {
      if (pendingObject) releaseModelObject(pendingObject, record, lease.kit);
      if (turn === previewTurn) previewPending = false;
      if (!leaseTransferred) lease.release();
    }
  }

  async function setLevel(level) {
    if (!current || level === currentLevel) return;
    if (current.builtin && level > 0) return;
    if (level > 0 && !current.lods?.some(l => l.name === LOD_FILES[level])) return;
    currentLevel = level;
    paintLevelBar();
    await showPreview({ refit: false });
  }

  function queueWrite(fn) {
    const task = writeChain.then(fn, fn);
    writeChain = task.then(() => {}, () => {});
    return task;
  }

  async function refreshThumbnail(record, targetTurn) {
    if (!record || stopped || !isSelected(record.id, targetTurn)) return;
    const dataUrl = preview.captureThumbnail();
    if (!dataUrl || !dataUrl.startsWith('data:image/png;base64,')) return;
    localThumbs.set(record.id, { url: dataUrl, key: visualKey(record, materialGen) });
    const img = gridImages.get(record.id);
    if (img) img.src = dataUrl;
    // Built-ins keep their generated thumbnails client-side; never PATCH imports for them.
    if (record.builtin) return;
    try {
      const latest = latestRecord(record.id) || record;
      const payload = { name: latest.name, thumbnail: dataUrl };
      if (/\.(dae|kmz)$/i.test(latest.model || '') && latest.triangles != null) payload.triangles = Math.round(latest.triangles);
      const updated = await api('editor/imports/' + encodeURIComponent(record.id), 'PATCH', payload);
      if (stopped) return;
      const merged = { ...(latestRecord(record.id) || record), ...updated, builtin: false };
      localThumbs.set(merged.id, { url: dataUrl, key: visualKey(merged, materialGen) });
      rememberImport(merged);
      if (isSelected(record.id, targetTurn)) current = merged;
      updateRow(merged);
    } catch { /* Thumbnail save is best-effort; model changes remain saved. */ }
  }

  async function handleConflict(targetId, targetTurn, error) {
    window.showGlobalAlert(error.message || 'This model changed in another tab. Reload its current record.');
    let fresh = error.record;
    if (!fresh) {
      try { fresh = await api('models/' + encodeURIComponent(targetId)); } catch { return; }
    }
    if (stopped || !fresh) return;
    rememberImport(fresh);
    updateRow(fresh);
    if (isSelected(targetId, targetTurn)) {
      current = fresh;
      syncOrRenderProperties();
      await showPreview({ refit: false });
      if (isSelected(targetId, targetTurn)) status.textContent = 'Reloaded latest model record';
    }
  }

  async function patchModel(makeChanges, { rebuildLevels = false, rerenderThumb = false, refitPreview = false } = {}) {
    if (!current || stopped) return null;
    const targetId = current.id, targetTurn = selectTurn;
    return queueWrite(async () => {
      if (stopped) return null;
      const latest = latestRecord(targetId);
      if (!latest) return null;
      const changes = typeof makeChanges === 'function' ? makeChanges(latest) : makeChanges;
      if (!changes || !Object.keys(changes).length) return latest;
      if (isSelected(targetId, targetTurn)) status.textContent = 'Saving…';
      try {
        const updated = await api('models/' + encodeURIComponent(targetId), 'PATCH', { revision: latest.revision || 0, ...changes });
        if (stopped) return null;
        rememberImport(updated);
        updateRow(updated);
        if (isSelected(targetId, targetTurn)) {
          current = updated;
          syncOrRenderProperties();
          if (changes.lod_percent) {
            ++previewTurn;
            if (currentLevel > 0 && !updated.lods?.some(l => l.name === LOD_FILES[currentLevel])) currentLevel = 0;
            await showPreview({ refit: false });
          } else if (changes.fix) {
            await showPreview({ refit: refitPreview, skipAutoThumb: rerenderThumb });
          } else if (changes.materials) {
            await showPreview({ reapplyOnly: true, skipAutoThumb: rerenderThumb });
          } else {
            paintLevelBar();
          }
          if (rerenderThumb && isSelected(targetId, targetTurn)) await refreshThumbnail(updated, targetTurn);
          if (isSelected(targetId, targetTurn)) status.textContent = 'Saved';
        }
        if (rebuildLevels && !updated.builtin && pendingLevels(updated).length) {
          startBuildLevels(updated);
        }
        return updated;
      } catch (error) {
        if (error.status === 409) {
          await handleConflict(targetId, targetTurn, error);
          return null;
        }
        report(error);
        if (isSelected(targetId, targetTurn)) {
          syncOrRenderProperties();
          status.textContent = 'Save failed';
        }
        return null;
      }
    });
  }

  async function runHistoryAction(op) {
    if (!current || stopped) return;
    const targetId = current.id, targetTurn = selectTurn;
    return queueWrite(async () => {
      if (stopped) return;
      const before = latestRecord(targetId);
      if (!before) return;
      if (isSelected(targetId, targetTurn)) status.textContent = 'Saving…';
      try {
        const updated = await api(`models/${encodeURIComponent(targetId)}/${op}`, 'POST', { revision: before.revision || 0 });
        if (stopped) return;
        rememberImport(updated);
        updateRow(updated);
        if (isSelected(targetId, targetTurn)) {
          current = updated;
          if (currentLevel > 0 && !updated.lods?.some(l => l.name === LOD_FILES[currentLevel])) currentLevel = 0;
          syncOrRenderProperties();
          const visualsChanged = JSON.stringify(before.fix) !== JSON.stringify(updated.fix)
            || JSON.stringify(before.materials) !== JSON.stringify(updated.materials);
          await showPreview({ refit: false, skipAutoThumb: visualsChanged });
          if (visualsChanged && isSelected(targetId, targetTurn)) await refreshThumbnail(updated, targetTurn);
          if (isSelected(targetId, targetTurn)) status.textContent = 'Saved';
        }
        if (!updated.builtin && pendingLevels(updated).length) startBuildLevels(updated);
      } catch (error) {
        if (error.status === 409) { await handleConflict(targetId, targetTurn, error); return; }
        report(error);
        if (isSelected(targetId, targetTurn)) status.textContent = 'Action failed';
      }
    });
  }

  async function applyPartMaterial(partKey, materialId) {
    if (!current || !partKey || !materialId) return;
    await patchModel(latest => {
      const part = latest.parts?.find(p => p.key === partKey);
      if (!part) return null;
      const prev = latest.materials?.[partKey];
      const nextEntry = prev?.texture === 'model' && part.has_uv
        ? { material: materialId, texture: 'model', ...(prev.tiles ? { tiles: prev.tiles } : {}) }
        : { material: materialId, texture: 'real' };
      return { materials: { ...(latest.materials || {}), [partKey]: nextEntry } };
    }, { rerenderThumb: true });
  }

  async function setPartTexture(partKey, texture, tiles) {
    if (!current || !partKey) return;
    await patchModel(latest => {
      const part = latest.parts?.find(p => p.key === partKey);
      const prev = latest.materials?.[partKey];
      if (!part || !prev) return null;
      if (texture === 'model' && !part.has_uv) return null;
      const nextEntry = texture === 'model'
        ? { material: prev.material, texture: 'model', tiles: tiles > 0 ? tiles : (prev.tiles || 1) }
        : { material: prev.material, texture: 'real' };
      return { materials: { ...(latest.materials || {}), [partKey]: nextEntry } };
    }, { rerenderThumb: true });
  }

  async function clearPartMaterial(partKey) {
    if (!current) return;
    await patchModel(latest => {
      if (!latest.materials?.[partKey]) return null;
      const nextMaterials = { ...(latest.materials || {}) };
      delete nextMaterials[partKey];
      return { materials: nextMaterials };
    }, { rerenderThumb: true });
  }

  function cancelBuild(id) {
    const existing = buildState.get(id);
    if (!existing) return;
    existing.controller.abort();
  }

  function startBuildLevels(record, preloadedSource = null) {
    if (stopped || !record) return;
    const prev = buildState.get(record.id);
    prev?.controller.abort();
    const token = (prev?.token || 0) + 1;
    const controller = new AbortController();
    const state = { token, controller };
    buildState.set(record.id, state);
    const isCurrent = () => !stopped && buildState.get(record.id)?.token === token;

    const onAbort = () => controller.abort();
    signal.addEventListener('abort', onAbort, { once: true });

    (async () => {
      let source = preloadedSource;
      const lease = acquireKit();
      try {
        if (current?.id === record.id) progressOut.textContent = 'Preparing lighter versions…';
        source ||= await loadModelFn(record.id, lease.kit, undefined, { editor: true, source: true });
        if (!source || !isCurrent()) return;
        const result = await buildLevelsFn(record, source, {
          signal: controller.signal,
          progress: text => {
            if (isCurrent() && current?.id === record.id) progressOut.textContent = text;
          },
          patch: async changes => {
            const latest = latestRecord(record.id) || record;
            const res = await api('models/' + encodeURIComponent(record.id), 'PATCH', { revision: latest.revision || 0, ...changes });
            rememberImport(res);
            updateRow(res);
            if (isCurrent() && current?.id === record.id) { current = res; syncOrRenderProperties(); }
            return res;
          },
          upload: (files, prog, sig, derived) => uploadFilesFn(files, prog, sig, sendEditor, derived),
          levelReady: async (_model, level, updated) => {
            if (!isCurrent()) return;
            rememberImport(updated);
            updateRow(updated);
            if (current?.id === record.id) {
              current = updated;
              paintLevelBar();
              if (level === currentLevel) await showPreview({ refit: false });
            }
          },
        });
        if (!isCurrent()) return;
        if (result) {
          rememberImport(result);
          updateRow(result);
          if (current?.id === record.id) {
            current = result;
            syncOrRenderProperties();
            await showPreview({ refit: false });
          }
        }
        if (current?.id === record.id) progressOut.textContent = '';
      } catch (error) {
        if (!isCurrent() || error?.cancelled) return;
        if (error?.status === 409) {
          const latest = latestRecord(record.id);
          if (latest && JSON.stringify(latest.lod_percent) !== JSON.stringify(record.lod_percent)) return;
          await handleConflict(record.id, selectTurn, error);
          return;
        }
        if (current?.id === record.id) progressOut.textContent = error.message || 'Lighter versions could not be made.';
        if (!error?.lodSkipped) report(error);
      } finally {
        signal.removeEventListener('abort', onAbort);
        if (source) disposeObject(source);
        lease.release();
        if (buildState.get(record.id)?.token === token) buildState.delete(record.id);
      }
    })();
  }

  async function importModel(files) {
    if (stopped || importing || !files.length) return;
    const names = files.map(f => (f.name || '').toLowerCase());
    if (names.some(n => n.endsWith('.skp'))) {
      report(new Error('SketchUp .skp is not supported; export Collada or glTF from SketchUp.'));
      return;
    }
    if (!names.some(n => MODEL_FILES.test(n))) {
      report(new Error('Choose a .glb, .gltf, .dae, .zip or .kmz model file.'));
      return;
    }
    importing = true;
    importButton.disabled = true;
    let entry = null, source = null, handedOff = false;
    const lease = acquireKit();
    try {
      status.textContent = 'Uploading model…';
      entry = await uploadFilesFn(files, text => { if (!stopped) status.textContent = text; }, signal, sendEditor);
      if (stopped) return;
      rememberImport(entry);
      status.textContent = 'Reading model…';
      source = await loadModelFn(entry.id, lease.kit, undefined, { editor: true, source: true });
      if (stopped) return;
      if (!source) throw new Error('Could not load this model. Check that its buffers and textures are included.');
      const budget = modelBudget(source, { resizeTextures: false });
      const size = new THREE.Box3().setFromObject(source).getSize(new THREE.Vector3()).toArray();
      const suggested = suggestKind(size);
      const patched = await api('editor/imports/' + encodeURIComponent(entry.id), 'PATCH', {
        name: entry.name, kind: suggested, size, triangles: Math.round(budget.triangles),
      });
      if (stopped) return;
      const fullEntry = { ...entry, ...patched, builtin: false };
      rememberImport(fullEntry);
      updateRow(fullEntry);
      search.value = ''; sourceFilter.value = 'all'; kindFilter.value = 'all';
      drawGrid();
      await select(fullEntry.id, fullEntry, { skipAutoBuild: true });
      if (stopped) return;
      const turn = selectTurn;
      await refreshThumbnail(current, turn);
      if (stopped) return;
      handedOff = true;
      startBuildLevels(latestRecord(fullEntry.id) || current, source);
      status.textContent = 'Model imported';
    } catch (error) {
      if (!stopped) status.textContent = 'Model import failed';
      report(error);
    } finally {
      if (source && !handedOff) disposeObject(source);
      lease.release();
      importing = false;
      importButton.disabled = false;
    }
  }

  async function deleteCurrent() {
    if (!current || current.builtin || stopped) return;
    const record = current, turn = selectTurn;
    const ok = await window.promptConfirm(
      `Delete ${record.name}?`,
      'Models placed in the house cannot be deleted until removed. Earlier house history keeps its files.',
      'Delete', 'Cancel',
    );
    if (!ok || stopped) return;
    cancelBuild(record.id);
    try {
      await api('editor/imports/' + encodeURIComponent(record.id), 'DELETE');
      if (stopped) return;
      forgetImport(record.id);
      localThumbs.delete(record.id);
      rows = rows.filter(r => r.id !== record.id);
      if (isSelected(record.id, turn)) {
        ++previewTurn;
        previewPending = false;
        const oldObj = currentObject, oldRec = currentObjectRecord, oldLease = currentObjectLease;
        current = null; currentObject = null; currentObjectRecord = null; currentObjectLease = null; propsSignature = null;
        preview.setModel(null);
        releaseModelObject(oldObj, oldRec, oldLease?.kit);
        oldLease?.release();
        propsHost.replaceChildren(); actionsBar.replaceChildren();
        drawGrid();
        status.textContent = 'Model deleted';
        if (rows.length) await select(rows[0].id);
      } else {
        drawGrid();
      }
    } catch (error) { report(error); }
  }

  function propertiesShapeKey(record) {
    if (!record) return null;
    const isOpening = record.kind === 'door' || record.kind === 'window';
    const partKeys = (record.parts || []).map(p => `${p.key}:${p.has_uv ? 1 : 0}`).join('|');
    return JSON.stringify([record.id, !!record.builtin, isOpening, partKeys, !!record.parts_version]);
  }

  // Sync in place when the model's structure has not changed, so focus and
  // rapid consecutive edits on inputs/part controls are never dropped.
  function syncOrRenderProperties() {
    const key = propertiesShapeKey(current);
    if (key && key === propsSignature && propSyncFns.length) {
      for (const fn of propSyncFns) fn();
      return;
    }
    renderProperties();
  }

  function renderProperties() {
    for (const row of slotRows.splice(0)) row.dispose();
    propAbort?.abort(); propAbort = new AbortController();
    propSyncFns = [];
    propsSignature = propertiesShapeKey(current);
    const ps = propAbort.signal;
    actionsBar.replaceChildren();
    propsHost.replaceChildren();
    if (!current) return;
    const record = current;

    // Top action buttons: Undo, Redo, Reset, plus Delete for imports.
    actionsBar.append(
      button('Undo', 'undo', () => runHistoryAction('undo'), ps),
      button('Redo', 'redo', () => runHistoryAction('redo'), ps),
      button('Reset', 'reset', () => runHistoryAction('reset'), ps),
    );
    if (!record.builtin) {
      actionsBar.append(button('Delete', 'delete', () => deleteCurrent(), ps));
    }

    propsHost.append(node('h2', 'Properties'));
    if (record.builtin) {
      propsHost.append(
        node('p', `Name: ${record.name}`),
        node('p', `Kind: ${record.kind || 'furniture'}`),
        node('p', 'Built-in model. Parts and size fixes apply everywhere it is used.', 'place-muted'),
      );
    } else {
      const nameLabel = node('label', 'Name'), nameInput = node('input');
      nameInput.type = 'text'; nameInput.value = record.name || ''; nameInput.maxLength = 100;
      nameInput.dataset.modelField = 'name';
      nameInput.addEventListener('change', async () => {
        const targetId = current?.id, targetTurn = selectTurn;
        if (!targetId) return;
        const nextName = nameInput.value.trim();
        if (!nextName) { nameInput.value = latestRecord(targetId)?.name || ''; return; }
        await queueWrite(async () => {
          const latest = latestRecord(targetId);
          if (!latest || stopped) return;
          try {
            const payload = { name: nextName, kind: latest.kind };
            if (/\.(dae|kmz)$/i.test(latest.model || '') && latest.triangles != null) payload.triangles = Math.round(latest.triangles);
            const updated = await api('editor/imports/' + encodeURIComponent(targetId), 'PATCH', payload);
            if (stopped) return;
            const merged = { ...latest, ...updated, builtin: false };
            rememberImport(merged);
            if (isSelected(targetId, targetTurn)) { current = merged; status.textContent = 'Saved'; }
            updateRow(merged);
          } catch (error) {
            if (isSelected(targetId, targetTurn)) nameInput.value = latest.name || '';
            report(error);
          }
        });
      }, { signal: ps });
      propSyncFns.push(() => { if (document.activeElement !== nameInput) nameInput.value = current.name || ''; });
      nameLabel.append(nameInput); propsHost.append(nameLabel);

      const kindLabel = node('label', 'Kind'), kindSelect = node('select');
      kindSelect.dataset.modelField = 'kind';
      for (const [value, label] of KINDS) {
        const opt = node('option', label); opt.value = value; kindSelect.append(opt);
      }
      kindSelect.value = record.kind || 'furniture';
      kindSelect.addEventListener('change', async () => {
        const targetId = current?.id, targetTurn = selectTurn, nextKind = kindSelect.value;
        if (!targetId) return;
        await queueWrite(async () => {
          const latest = latestRecord(targetId);
          if (!latest || stopped) return;
          try {
            const payload = { name: latest.name, kind: nextKind };
            if (/\.(dae|kmz)$/i.test(latest.model || '') && latest.triangles != null) payload.triangles = Math.round(latest.triangles);
            const updated = await api('editor/imports/' + encodeURIComponent(targetId), 'PATCH', payload);
            if (stopped) return;
            const merged = { ...latest, ...updated, builtin: false };
            rememberImport(merged);
            updateRow(merged);
            if (isSelected(targetId, targetTurn)) { current = merged; syncOrRenderProperties(); status.textContent = 'Saved'; }
          } catch (error) {
            if (isSelected(targetId, targetTurn)) kindSelect.value = latest.kind || 'furniture';
            report(error);
          }
        });
      }, { signal: ps });
      propSyncFns.push(() => { kindSelect.value = current.kind || 'furniture'; });
      kindLabel.append(kindSelect); propsHost.append(kindLabel);
    }

    // Size & orientation section.
    const fixSection = node('section', null, 'library-map'); fixSection.dataset.modelFix = '';
    fixSection.append(node('h3', 'Size & orientation'));
    const isOpening = record.kind === 'door' || record.kind === 'window';
    if (isOpening) {
      fixSection.append(node('p', 'Door and window models stretch to fit each opening; only the turn fix applies.', 'place-muted'));
    } else {
      const axisLabel = node('label', 'Real dimension'), axisSelect = node('select');
      axisSelect.dataset.fixAxis = ''; axisSelect.setAttribute('aria-label', 'Real dimension');
      for (const [value, label] of [['height_m', 'Real height'], ['width_m', 'Real width']]) {
        const opt = node('option', label); opt.value = value; axisSelect.append(opt);
      }
      axisLabel.append(axisSelect);

      const dimRow = node('div', null, 'library-fix-row');
      const ftLabel = node('label', 'Feet'), ftInput = node('input');
      ftInput.type = 'number'; ftInput.min = '0'; ftInput.max = '98'; ftInput.step = '1';
      ftInput.dataset.fixFeet = ''; ftInput.setAttribute('aria-label', 'Real size feet');
      ftLabel.append(ftInput);
      const inLabel = node('label', 'Inches'), inInput = node('input');
      inInput.type = 'number'; inInput.min = '0'; inInput.max = '11.99'; inInput.step = '0.5';
      inInput.dataset.fixInches = ''; inInput.setAttribute('aria-label', 'Real size inches');
      inLabel.append(inInput);
      dimRow.append(ftLabel, inLabel);

      const clearSizeBtn = button('Clear size', 'clear-size', () => {
        patchModel(latest => ({ fix: { turn: latest.fix?.turn || 0 } }), { rerenderThumb: true, refitPreview: true });
      }, ps);

      const syncSize = () => {
        const axis = current.fix?.width_m ? 'width_m' : 'height_m';
        const activeMetres = current.fix?.[axis] || 0;
        const { feet, inches } = metresToFeetInches(activeMetres);
        axisSelect.value = axis;
        if (document.activeElement !== ftInput) ftInput.value = feet;
        if (document.activeElement !== inInput) inInput.value = inches;
        clearSizeBtn.hidden = !(activeMetres > 0);
      };
      syncSize();
      propSyncFns.push(syncSize);

      const commitSize = () => {
        const metres = feetInchesToMetres(ftInput.value, inInput.value);
        if (Number.isNaN(metres)) { report(new Error('Enter non-negative feet and inches.')); syncSize(); return; }
        if (metres !== null && metres > 30) { report(new Error('The real size must be at most 30 m.')); syncSize(); return; }
        const chosenAxis = axisSelect.value;
        patchModel(latest => ({
          fix: { turn: latest.fix?.turn || 0, ...(metres !== null ? { [chosenAxis]: metres } : {}) },
        }), { rerenderThumb: true, refitPreview: true });
      };
      ftInput.addEventListener('change', commitSize, { signal: ps });
      inInput.addEventListener('change', commitSize, { signal: ps });
      axisSelect.addEventListener('change', () => {
        if (ftInput.value.trim() || inInput.value.trim()) commitSize();
      }, { signal: ps });
      fixSection.append(axisLabel, dimRow, clearSizeBtn);
    }

    const turnRow = node('div', null, 'editor-actions'); turnRow.dataset.fixTurn = '';
    turnRow.append(button('Turn 90°', 'turn-90', () => {
      patchModel(latest => ({
        fix: { ...(latest.fix || {}), turn: ((latest.fix?.turn || 0) + 90) % 360 },
      }), { rerenderThumb: true });
    }, ps));
    const turnButtons = [0, 90, 180, 270].map(deg => {
      const btn = button(`${deg}°`, `turn-${deg}`, () => {
        patchModel(latest => ({ fix: { ...(latest.fix || {}), turn: deg } }), { rerenderThumb: true });
      }, ps);
      btn.dataset.turn = String(deg);
      turnRow.append(btn);
      return [deg, btn];
    });
    const syncTurn = () => {
      const turn = current.fix?.turn || 0;
      for (const [deg, btn] of turnButtons) btn.setAttribute('aria-pressed', String(turn === deg));
    };
    syncTurn();
    propSyncFns.push(syncTurn);
    fixSection.append(node('p', 'Quarter turns', 'place-muted'), turnRow);
    propsHost.append(fixSection);

    // Detail levels section (hidden for built-ins).
    if (!record.builtin) {
      const lodSection = node('section', null, 'library-map'); lodSection.dataset.modelLevels = '';
      lodSection.append(node('h3', 'Detail levels'), node('p', 'Percentages of the original triangles (1–100, Full ≥ Mid ≥ Far).', 'place-muted'));
      const lodGrid = node('div', null, 'library-lod-grid');
      const lodInputs = LEVEL_NAMES.map((label, i) => {
        const wrap = node('label', `${label} (%)`);
        const input = node('input');
        input.type = 'number'; input.min = '1'; input.max = '100'; input.step = '1';
        input.dataset.lodPercent = String(i);
        input.setAttribute('aria-label', `${label} detail percentage`);
        wrap.append(input); lodGrid.append(wrap);
        return input;
      });
      const syncLods = () => {
        const percents = current.lod_percent || DEFAULT_LOD_PERCENT;
        lodInputs.forEach((el, i) => {
          if (document.activeElement !== el) el.value = String(percents[i] ?? DEFAULT_LOD_PERCENT[i]);
        });
      };
      syncLods();
      propSyncFns.push(syncLods);
      const commitPercents = () => {
        const next = lodInputs.map(el => Number(el.value));
        if (next.some(v => !Number.isInteger(v) || v < 1 || v > 100) || !(next[0] >= next[1] && next[1] >= next[2])) {
          report(new Error('Detail levels must be whole percentages from 1 to 100, with Full ≥ Mid ≥ Far.'));
          syncLods();
          return;
        }
        cancelBuild(current.id);
        patchModel(latest => (JSON.stringify(next) === JSON.stringify(latest.lod_percent) ? null : { lod_percent: next }), { rebuildLevels: true });
      };
      lodInputs.forEach(input => input.addEventListener('change', commitPercents, { signal: ps }));
      lodSection.append(lodGrid);
      propsHost.append(lodSection);
    }

    // Parts section: one createSlotRow per part, plus Real size / Model's own + Tiles.
    const partsSection = node('section', null, 'library-map'); partsSection.dataset.modelParts = '';
    partsSection.append(node('h3', 'Parts'));
    const parts = record.parts || [];
    if (!parts.length) {
      partsSection.append(node('p', record.parts_version ? 'No parts found.' : 'Reading model parts…', 'place-muted'));
    } else {
      for (const part of parts) {
        const wrap = node('div', null, 'library-part'); wrap.dataset.modelPart = part.key;
        const label = part.key.includes('~') ? part.key : (part.name || part.key);
        const getResolved = () => resolvePart(part, current?.materials || {}, {});
        const slot = createSlotRow({
          label,
          subject: `${part.key} part material`,
          accepts: entry => entry?.kind === 'material',
          current: () => {
            const matId = getResolved().material;
            return matId ? materialEntry(matId) : null;
          },
          detail: () => {
            const matId = getResolved().material;
            return matId ? (materialEntry(matId)?.name || matId) : 'from the original';
          },
          inherited: () => !current?.materials?.[part.key],
          apply: entry => applyPartMaterial(part.key, entry.id),
          clear: { enabled: () => !!current?.materials?.[part.key], run: () => clearPartMaterial(part.key) },
          library: slotLibrary,
        });
        slotRows.push(slot);
        slot.element.addEventListener('dragover', event => {
          const types = Array.from(event.dataTransfer?.types || []);
          if (!types.includes('application/x-chauffeur-material') && !window.__chfDragMaterial) return;
          event.preventDefault();
          slot.element.classList.add('editor-slot-dragover');
          if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        }, { signal: ps });
        slot.element.addEventListener('dragleave', () => slot.element.classList.remove('editor-slot-dragover'), { signal: ps });
        slot.element.addEventListener('drop', event => {
          const matId = event.dataTransfer?.getData?.('application/x-chauffeur-material') || window.__chfDragMaterial;
          if (!matId) return;
          event.preventDefault();
          slot.element.classList.remove('editor-slot-dragover');
          applyPartMaterial(part.key, matId);
        }, { signal: ps });

        const texBar = node('div', null, 'library-part-texture');
        const realBtn = button('Real size', 'texture-real', () => setPartTexture(part.key, 'real'), ps);
        realBtn.dataset.partTexture = 'real';
        const ownBtn = button("Model's own", 'texture-model', () => setPartTexture(part.key, 'model', getResolved().tiles || 1), ps);
        ownBtn.dataset.partTexture = 'model';
        ownBtn.disabled = !part.has_uv;
        if (!part.has_uv) ownBtn.title = 'This part has no UVs';

        const tilesWrap = node('label', 'Tiles', 'library-part-tiles');
        const tilesInput = node('input');
        tilesInput.type = 'number'; tilesInput.min = '0.1'; tilesInput.max = '100'; tilesInput.step = '0.5';
        tilesInput.dataset.partTiles = '';
        tilesInput.setAttribute('aria-label', `${label} tiles`);
        tilesInput.addEventListener('change', () => {
          const val = Number(tilesInput.value);
          if (!Number.isFinite(val) || val <= 0 || val > 100) {
            report(new Error('Tiles must be above 0 and at most 100.'));
            tilesInput.value = String(getResolved().tiles || 1);
            return;
          }
          setPartTexture(part.key, 'model', val);
        }, { signal: ps });
        tilesWrap.append(tilesInput);
        texBar.append(realBtn, ownBtn, tilesWrap);
        wrap.append(slot.element, texBar);
        partsSection.append(wrap);

        const syncPart = () => {
          const r = getResolved();
          slot.refresh();
          realBtn.setAttribute('aria-pressed', String(r.texture === 'real'));
          ownBtn.setAttribute('aria-pressed', String(r.texture === 'model'));
          ownBtn.disabled = !part.has_uv;
          tilesWrap.hidden = r.texture !== 'model';
          if (document.activeElement !== tilesInput) tilesInput.value = String(r.tiles || 1);
        };
        syncPart();
        propSyncFns.push(syncPart);
      }
    }
    propsHost.append(partsSection);
  }

  function drawGrid() {
    if (stopped) return;
    gridAbort?.abort(); gridAbort = new AbortController();
    grid.replaceChildren();
    gridImages.clear();
    const query = search.value.trim().toLowerCase();
    const filtered = rows.filter(row => {
      if (row.archived) return false;
      if (query && !(row.name || row.id).toLowerCase().includes(query)) return false;
      if (sourceFilter.value === 'builtin' && !row.builtin) return false;
      if (sourceFilter.value === 'mine' && row.builtin) return false;
      if (kindFilter.value !== 'all' && (row.kind || 'furniture') !== kindFilter.value) return false;
      return true;
    });
    for (const row of filtered) {
      const btn = button('', 'select-model', () => select(row.id).catch(report), gridAbort.signal);
      btn.dataset.model = row.id;
      btn.setAttribute('aria-pressed', String(current?.id === row.id));
      const img = node('img'); img.alt = ''; img.width = 112; img.height = 96;
      img.style.backgroundColor = '#242933';
      img.addEventListener('error', () => img.removeAttribute('src'), { once: true });
      const url = modelThumb(row, localThumbs.get(row.id), materialGen);
      if (url) img.src = url;
      else if (row.id !== current?.id) {
        const expectedKey = visualKey(row, materialGen);
        renderMissingThumbnail(row).then(generated => {
          if (stopped || !generated) return;
          const latest = latestRecord(row.id);
          if (latest && visualKey(latest, materialGen) !== expectedKey) return;
          localThumbs.set(row.id, { url: generated, key: expectedKey });
          const targetImg = gridImages.get(row.id);
          if (targetImg) targetImg.src = generated;
        });
      }
      gridImages.set(row.id, img);
      const meta = row.builtin ? `Built-in · ${row.kind || 'model'}` : (row.kind || 'furniture');
      btn.append(img, node('span', row.name || row.id), node('small', meta));
      grid.append(btn);
    }
    if (!grid.children.length) grid.append(node('p', 'No matching models.', 'place-muted'));
  }

  function drawPalette() {
    if (stopped) return;
    paletteAbort?.abort(); paletteAbort = new AbortController();
    paletteGrid.replaceChildren();
    const query = paletteSearch.value.trim().toLowerCase();
    const visible = materialRows.filter(row => !row.archived && (row.name || row.id).toLowerCase().includes(query));
    for (const row of visible) {
      const entry = materialEntry(row.id);
      const btn = node('button'); btn.type = 'button';
      btn.dataset.paletteMaterial = row.id;
      btn.setAttribute('aria-pressed', String(selectedMaterial?.id === row.id));
      btn.draggable = true;
      const img = node('img'); img.alt = ''; img.draggable = false; img.width = 64; img.height = 48;
      img.style.backgroundColor = entry.color || '#b8b0a4';
      img.addEventListener('error', () => img.removeAttribute('src'), { once: true });
      if (entry.thumb) img.src = entry.thumb;
      btn.append(img, node('span', row.name || row.id));
      btn.addEventListener('click', () => {
        if (dragState?.suppressClick) { dragState.suppressClick = false; return; }
        setSelectedMaterial(selectedMaterial?.id === entry.id ? null : entry);
      }, { signal: paletteAbort.signal });
      btn.addEventListener('dragstart', event => {
        window.__chfDragMaterial = entry.id;
        if (event.dataTransfer) {
          event.dataTransfer.setData('application/x-chauffeur-material', entry.id);
          event.dataTransfer.setData('text/plain', entry.id);
          event.dataTransfer.effectAllowed = 'copy';
        }
      }, { signal: paletteAbort.signal });
      btn.addEventListener('dragend', () => {
        if (window.__chfDragMaterial === entry.id) window.__chfDragMaterial = null;
        preview.highlightPart(null);
      }, { signal: paletteAbort.signal });
      btn.addEventListener('pointerdown', event => {
        if (event.button !== 0 || event.pointerType === 'mouse' && btn.draggable) return;
        dragState = { entry, pointer: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
      }, { signal: paletteAbort.signal });
      paletteGrid.append(btn);
    }
    if (!paletteGrid.children.length) paletteGrid.append(node('p', 'No matching materials.', 'place-muted'));
  }

  async function refreshModels() {
    const data = await api('models');
    rows = (data.models || []).map(row => { rememberImport(row); return row; });
    drawGrid();
  }

  async function select(id, entry = null, { skipAutoBuild = false } = {}) {
    const turn = ++selectTurn;
    const record = entry || await api('models/' + encodeURIComponent(id));
    if (stopped || turn !== selectTurn) return;
    rememberImport(record);
    current = record;
    currentLevel = 0;
    loadedTriangles = null;
    updateRow(record);
    syncOrRenderProperties();
    paintLevelBar();
    status.textContent = 'Saved';
    ensureOriginalBytes(record);
    await showPreview({ refit: true });
    if (stopped || turn !== selectTurn) return;
    if (!skipAutoBuild && (!record.parts_version || (!record.builtin && pendingLevels(record).length))) {
      if (!buildState.has(record.id)) startBuildLevels(record);
    }
  }

  const ready = (async () => {
    if (!materialRows.length) {
      try {
        const res = await api('materials');
        materialRows = res.materials || [];
        materialsLoaded = true;
      } catch { /* Palette stays empty offline. */ }
    }
    drawPalette();
    await refreshModels();
    if (stopped) return;
    const pick = (initialModelId && rows.some(r => r.id === initialModelId) ? initialModelId : null) || rows[0]?.id;
    if (pick) await select(pick);
    else status.textContent = 'Import a model to begin.';
  })().catch(error => {
    if (!stopped) status.textContent = 'Models could not open. Reload to try again.';
    report(error);
  });

  return {
    ready,
    select,
    preview,
    setMaterials(nextRows) {
      materialRows = [...(nextRows || [])];
      materialsLoaded = true;
      materialGen++;
      const oldCache = activeCache;
      oldCache.retired = true;
      retiredCaches.add(oldCache);
      activeCache = createCache();
      const hadPendingPreview = previewPending;
      ++previewTurn;
      previewPending = false;
      drawPalette();
      drawGrid();
      if (current) {
        syncOrRenderProperties();
        if (hadPendingPreview || !currentObject) showPreview({ refit: false });
        else showPreview({ reapplyOnly: true });
      }
      // Dispose the retired cache right away when idle; otherwise its last active user drains it on release.
      if (oldCache.users <= 0) drainCache(oldCache);
    },
    setActive(on) { preview.setActive(on); },
    stop() {
      if (stopped) return;
      stopped = true;
      ++previewTurn;
      ++materialGen;
      previewPending = false;
      for (const state of buildState.values()) state.controller.abort();
      buildState.clear();
      for (const row of slotRows.splice(0)) row.dispose();
      abort.abort(); gridAbort?.abort(); paletteAbort?.abort(); propAbort?.abort();
      preview.setModel(null);
      const oldObj = currentObject, oldRec = currentObjectRecord, oldLease = currentObjectLease;
      currentObject = null; currentObjectRecord = null; currentObjectLease = null;
      releaseModelObject(oldObj, oldRec, oldLease?.kit);
      oldLease?.release();
      thumbRenderer.dispose();
      activeCache.retired = true;
      retiredCaches.add(activeCache);
      for (const cache of [...retiredCaches]) {
        if (cache.users <= 0) drainCache(cache);
      }
      preview.dispose();
    },
  };
}
