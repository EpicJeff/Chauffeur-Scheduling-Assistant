import * as THREE from 'three';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { generateLevel, frame, LOD_TEXTURE_SIZES } from './model_lods.js';
import { partKeys, DEFAULT_LOD_PERCENT } from './model_parts.js';
import { base, rememberImport, disposeObject } from './twin_library.js';

const check = signal => { if (signal?.aborted) throw Object.assign(new Error('Making lighter versions cancelled.'), { cancelled: true }); };

// A part is an original material instance, including duplicate/empty names.
// Existing extras are authoritative when reading a generated level.
export function stampParts(root) {
  const materials = [], stats = new Map();
  root.traverse(mesh => {
    if (!mesh.isMesh) return;
    const geo = mesh.geometry, count = geo.index?.count || geo.attributes.position?.count || 0;
    const slots = [].concat(mesh.material), ranges = Array.isArray(mesh.material) ? geo.groups : [{ start: 0, count, materialIndex: 0 }];
    for (const range of ranges) {
      const m = slots[range.materialIndex]; if (!m) continue;
      if (!stats.has(m)) {
        materials.push(m); stats.set(m, { name: m.name || 'unnamed', triangles: 0, has_uv: true,
          opaque: (!m.transparent || !!m.userData.viewingOpaque) && !(m.alphaTest > 0) && !['fixture', 'glass'].includes(m.name) });
      }
      const s = stats.get(m); s.triangles += Math.max(0, Math.min(range.start + range.count, geo.drawRange.start + geo.drawRange.count, count) - Math.max(range.start, geo.drawRange.start)) / 3;
      s.has_uv &&= !!geo.attributes.uv;
    }
  });
  const keys = partKeys(materials.map(m => m.name));
  return materials.map((m, i) => {
    m.userData.partKey ||= keys[i];
    return { key: m.userData.partKey, ...stats.get(m) };
  });
}

// Files form one byte stream; chunk boundaries need not match file boundaries.
// send uses the editor import route, and can be supplied by another host page.
export async function uploadFiles(files, progress = () => {}, signal, send, derived = {}) {
  send ||= async (path, method, body) => {
    const response = await fetch(base() + 'api/house/editor/' + path, {
      method, ...(body === undefined ? {} : body instanceof Blob ? { headers: { 'Content-Type': 'application/octet-stream' }, body }
        : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    });
    let data;
    try { data = JSON.parse(await response.text()); }
    catch {
      const message = response.status === 401
        ? 'Home Assistant signed this tab out. Open Chauffeur from the Home Assistant sidebar, then try again.'
        : response.status === 413 ? 'That upload is larger than Home Assistant lets through. Try a smaller model or a zip.'
          : `The house could not answer (HTTP ${response.status}). Try again.`;
      throw Object.assign(new Error(message), { status: response.status });
    }
    if (!response.ok) throw Object.assign(new Error(data.detail || `Model upload failed (HTTP ${response.status}).`), { status: response.status, record: data.record });
    return data;
  };
  const start = await send('imports/uploads', 'POST', {
    name: files[0].name.replace(/\.[^.]+$/, '').slice(0, 100), size: files.reduce((n, f) => n + f.size, 0),
    files: files.map(f => ({ name: f.webkitRelativePath || f.name, size: f.size })), ...derived,
  });
  const path = 'imports/uploads/' + start.upload_id, body = new Blob(files);
  let bytes = Math.min(start.chunk_bytes, 4 * 1024 * 1024), offset = 0, index = 0, finished = false;
  try {
    progress(`Uploading 0 of ${Math.ceil(body.size / 1048576)} MB…`);
    while (offset < body.size) {
      check(signal); const chunk = body.slice(offset, offset + bytes);
      try { await send(`${path}/${index}`, 'PUT', chunk); }
      catch (error) {
        if (error.status !== 413) throw error;
        if (bytes <= 256 * 1024) throw new Error('Home Assistant refused even a 256 KB model chunk. Check its ingress upload limit and try again.');
        bytes = Math.max(256 * 1024, Math.floor(bytes / 2)); continue;
      }
      offset += chunk.size; ++index; progress(`Uploading ${Math.ceil(offset / 1048576)} of ${Math.ceil(body.size / 1048576)} MB…`);
    }
    check(signal); progress('Preparing model…');
    const entry = await send(path + '/finish', 'POST'); finished = true; return entry;
  } finally { if (!finished) await send(path, 'DELETE').catch(() => {}); }
}

export function thumbnail(model) {
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(160, 128, false); renderer.setPixelRatio(1);
  const scene = new THREE.Scene(), box = new THREE.Box3().setFromObject(model);
  const centre = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()), distance = Math.max(size.x, size.y, size.z) * 2.5;
  const camera = new THREE.PerspectiveCamera(36, 160 / 128, .001, Math.max(100, distance * 10));
  camera.position.copy(centre).add(new THREE.Vector3(distance, distance * .6, distance)); camera.lookAt(centre);
  const sun = new THREE.DirectionalLight('#ffffff', 3); sun.position.set(3, 5, 4);
  scene.add(model, sun, new THREE.HemisphereLight('#ffffff', '#687078', 2));
  try { renderer.render(scene, camera); return renderer.domElement.toDataURL('image/png'); }
  finally { model.removeFromParent(); renderer.dispose(); renderer.forceContextLoss(); }
}

export function pendingLevels(record, regenerate = !record.parts_version) {
  return (record.lod_percent || DEFAULT_LOD_PERCENT).map((percent, level) => ({ percent, level, name: `lod${level}.glb` })).filter(({ percent, level, name }) => {
    if (!level && percent === 100) return false;
    const old = record.lods?.find(l => l.name === name);
    return regenerate || !old || !(old.revision >= 1) || (old.percent ?? DEFAULT_LOD_PERCENT[level]) !== percent;
  });
}

export async function buildLevels(record, source, { signal, progress = () => {}, upload = (files, progress, signal, derived) => uploadFiles(files, progress, signal, undefined, derived), patch, levelReady = () => {} } = {}) {
  check(signal);
  const regenerate = !record.parts_version;
  const parts = stampParts(source);
  // The server refuses an empty stamp. A built-in stays unstamped, as the
  // editor's first-use path leaves it; an import without surfaces says so.
  if (regenerate && !parts.length) {
    if (record.builtin) return record;
    throw new Error('This model has no surfaces, so it has no parts or lighter versions.');
  }
  if (regenerate) {
    const changes = { parts, parts_version: 1 };
    if (!patch) patch = async changes => {
      const response = await fetch(base() + 'api/house/models/' + encodeURIComponent(record.id), {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: record.revision || 0, ...changes }),
      });
      const data = await response.json();
      if (!response.ok) throw Object.assign(new Error(data.detail || `Could not stamp model parts (HTTP ${response.status}).`), { status: response.status, record: data.record });
      return data;
    };
    record = await patch(changes); rememberImport(record);
  }
  if (record.builtin) return record;
  // Snapshot the work list: uploads return a new record and must never enqueue a
  // second upload of the same level during a legacy regeneration.
  const pending = pendingLevels(record, regenerate);
  // Every level, including generated Full, uses the immutable authored origin
  // and size. Editing Full cannot invalidate the mid/far alignment metadata.
  const sourceBounds = new THREE.Box3().setFromObject(source);
  for (const [index, { percent, level, name }] of pending.entries()) {
    let model;
    try {
      check(signal); progress(`Making lighter versions… ${index + 1} of ${pending.length}`); await frame(signal);
      model = await generateLevel(source, percent, signal, level ? LOD_TEXTURE_SIZES[level - 1] : Infinity); await frame(signal);
      model.userData.modelLevelAnchor = { original:[record.model,100,0],
        min:sourceBounds.min.toArray(), max:sourceBounds.max.toArray() };
      // GLTFExporter writes material.userData as extras. Do not strip it.
      const buffer = await new GLTFExporter().parseAsync(model, { binary: true, onlyVisible: true });
      check(signal);
      if (buffer.byteLength > 50 * 1024 * 1024) throw new Error('Each lighter version may be at most 50 MB.');
      record = await upload([new File([buffer], name)], () => {}, signal, { asset_id: record.id, lod: name, percent });
      check(signal); rememberImport(record); await levelReady(model, level, record);
    } finally { if (model) disposeObject(model); }
  }
  return record;
}

// Compatibility adapter for the editor's optional preview/queue contract.
export async function generateVersions(entry, source, signal, progress = () => {}, changed = () => {}) {
  const rows = [];
  try {
    await buildLevels(entry, source, { signal, progress, levelReady: async (model, level, record) => {
      let triangles = 0; model.traverse(o => { if (o.isMesh) triangles += (o.geometry.index?.count || o.geometry.attributes.position.count) / 3; });
      rows.push({ name: `LOD${level}`, picture: thumbnail(model), triangles }); await changed(record);
    } });
  } catch (error) {
    if (error.lodSkipped) { rows.note = error.message; progress(error.message); }
    else if (error.status === 409) { rows.note = error.message; window.showGlobalAlert?.(error.message); }
  }
  return rows;
}
