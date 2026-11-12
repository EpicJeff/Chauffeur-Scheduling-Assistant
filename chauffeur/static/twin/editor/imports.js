import * as THREE from 'three';
import { importedModels, rememberImport, forgetImport, loadModel, disposeObject } from '../twin_library.js';
import { modelBudget, suggestKind, schema } from '../objects.js';
import { request, report } from './api.js';
import { makeLod, idle, frame } from '../model_lods.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';

// Files form one byte stream; chunk boundaries need not match file boundaries.
export async function uploadFiles(files, progress, signal, send = request, derived = {}) {
  const start = await send('imports/uploads', 'POST', {
    name: files[0].name.replace(/\.[^.]+$/, '').slice(0, 100),
    size: files.reduce((n, f) => n + f.size, 0),
    files: files.map(f => ({ name: f.webkitRelativePath || f.name, size: f.size })),
    ...derived,
  });
  const path = 'imports/uploads/' + start.upload_id, body = new Blob(files);
  let bytes = Math.min(start.chunk_bytes, 4 * 1024 * 1024), offset = 0, index = 0, finished = false;
  try {
    progress(`Uploading 0 of ${Math.ceil(body.size / 1048576)} MB…`);
    while (offset < body.size) {
      if (signal?.aborted) throw Object.assign(new Error('Model upload cancelled.'), { cancelled: true });
      const chunk = body.slice(offset, offset + bytes);
      try { await send(`${path}/${index}`, 'PUT', chunk); }
      catch (error) {
        if (error.status !== 413) throw error;
        if (bytes <= 256 * 1024) throw new Error('Home Assistant refused even a 256 KB model chunk. Check its ingress upload limit and try again.');
        bytes = Math.max(256 * 1024, Math.floor(bytes / 2)); continue;
      }
      offset += chunk.size; ++index;
      progress(`Uploading ${Math.ceil(offset / 1048576)} of ${Math.ceil(body.size / 1048576)} MB…`);
    }
    if (signal?.aborted) throw Object.assign(new Error('Model upload cancelled.'), { cancelled: true });
    progress('Preparing model…');
    const entry = await send(path + '/finish', 'POST'); finished = true; return entry;
  } finally {
    if (!finished) await send(path, 'DELETE').catch(() => {});
  }
}

function thumbnail(model) {
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(160, 128, false); renderer.setPixelRatio(1);
  const scene = new THREE.Scene(), box = new THREE.Box3().setFromObject(model);
  const centre = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
  const distance = Math.max(size.x, size.y, size.z) * 2.5;
  const camera = new THREE.PerspectiveCamera(36, 160 / 128, .001, Math.max(100, distance * 10));
  camera.position.copy(centre).add(new THREE.Vector3(distance, distance * .6, distance)); camera.lookAt(centre);
  const sun = new THREE.DirectionalLight('#ffffff', 3); sun.position.set(3, 5, 4);
  scene.add(model, sun, new THREE.HemisphereLight('#ffffff', '#687078', 2));
  try { renderer.render(scene, camera); return renderer.domElement.toDataURL('image/png'); }
  finally { model.removeFromParent(); renderer.dispose(); renderer.forceContextLoss(); }
}

// This uses the piece card's native labels and controls. No browser dialogs.
function details(entry, suggested, picture, signal, versions, updates) {
  if (signal.aborted) return Promise.resolve(null);
  return new Promise(resolve => {
    const card = document.createElement('form'); card.className = 'object-import'; card.setAttribute('role', 'dialog'); card.setAttribute('aria-label', 'Import model');
    const heading = document.createElement('h3'); heading.textContent = 'Import model'; card.append(heading);
    const previews = document.createElement('div'); previews.className = 'object-import-versions'; card.append(previews);
    const preview = (name, src, triangles) => {
      const figure = document.createElement('figure'), image = document.createElement('img'), caption = document.createElement('figcaption');
      image.src = src; image.alt = name; caption.textContent = `${name}: ${Math.round(triangles).toLocaleString()} triangles`;
      figure.append(image, caption); previews.append(figure);
    };
    preview('Original', picture, entry.triangles);
    let warningNote = null;
    const progress = document.createElement('p'); progress.textContent = 'Making lighter versions…'; card.append(progress);
    updates.update = text => { if (card.isConnected) progress.textContent = text; };
    versions.then(rows => {
      if (!card.isConnected) return;
      rows.forEach(row => preview(row.name, row.picture, row.triangles));
      progress.textContent = rows.note || (rows.length === 2 ? 'Lighter versions ready.' : 'Model kept. Lighter versions could not be made this time.');
      if (rows.length === 2 && entry.heavy && warningNote) warningNote.textContent = 'Heavy original. The wall panel will use the lightest real version.';
    });
    const nameLabel = document.createElement('label'); nameLabel.textContent = 'Name';
    const name = document.createElement('input'); name.value = entry.name; name.required = true; name.maxLength = 100; nameLabel.append(name); card.append(nameLabel);
    const kindLabel = document.createElement('label'); kindLabel.textContent = `Kind (suggested: ${suggested})`;
    const kind = document.createElement('select');
    for (const value of Object.keys(schema().kinds)) { const option = document.createElement('option'); option.value = value; option.textContent = value; kind.append(option); }
    kind.value = suggested; kindLabel.append(kind); card.append(kindLabel);
    if (entry.warning) { warningNote = document.createElement('p'); warningNote.textContent = entry.warning; card.append(warningNote); }
    const done = value => { card.remove(); signal.removeEventListener('abort', abort); resolve(value); };
    const abort = () => done(null); signal.addEventListener('abort', abort, { once: true });
    const save = document.createElement('button'); save.type = 'submit'; save.textContent = 'Add to library'; card.append(save);
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel'; cancel.addEventListener('click', abort); card.append(cancel);
    card.addEventListener('submit', event => { event.preventDefault(); if (name.value.trim()) done({ name: name.value.trim(), kind: kind.value, thumbnail: picture }); });
    document.getElementById('editor-scene').parentElement.append(card); name.focus();
  });
}

export function mountImports({ canvas, kit, canEdit, signal, changed }) {
  const el = id => document.getElementById(id), picker = el('library-import-files');
  if (!picker) return;
  const status = el('library-status'); let busy = false;
  const jobs = new AbortController();
  signal.addEventListener('abort', () => jobs.abort(), { once: true });
  // Sequential idle work: closing the editor cancels generation and uploads.
  (async () => {
    await idle(jobs.signal);
    for (const entry of await importedModels()) {
      if (!canEdit() || jobs.signal.aborted) break;
      if (entry.archived || entry.lods?.length === 2) continue;
      while (busy) await idle(jobs.signal);
      await idle(jobs.signal);
      let source;
      try {
        source = await loadModel(entry.id, kit, undefined, { editor: true });
        if (source) await generateVersions(entry, source, jobs.signal);
      } catch { /* An old import stays usable if deriving a version fails. */ }
      finally { if (source) disposeObject(source); }
    }
  })().catch(() => {});
  const listen = (node, event, action) => node?.addEventListener(event, action, { signal });
  request('import-settings').then(settings => {
    if (signal.aborted) return;
    if (el('library-import-unpacked-limit')) el('library-import-unpacked-limit').value = settings.unpacked_limit_mb;
  }).catch(report);
  async function add(files) {
    if (!canEdit() || busy || !files.length) return;
    busy = true; let entry = null, accepted = false, model = null, generation;
    const generationEvents = new AbortController();
    const cancelGeneration = () => generationEvents.abort(); signal.addEventListener('abort', cancelGeneration, { once: true });
    try {
      const names = files.map(f => f.name.toLowerCase());
      if (names.some(n => n.endsWith('.skp'))) throw new Error('SketchUp .skp is not supported; export Collada or glTF from SketchUp.');
      const settings = await request('import-settings');
      if (files.reduce((n, file) => n + file.size, 0) > settings.limit_mb * 1024 * 1024) throw new Error(`Models may be at most ${settings.limit_mb} MB.`);
      status.textContent = 'Loading model…';
      entry = await uploadFiles(files, text => { status.textContent = text; }, signal); rememberImport(entry);
      model = await loadModel(entry.id, kit, undefined, { editor: true });
      if (!model) throw new Error('Could not load this model. Check that its buffers and textures are included.');
      const budget = modelBudget(model, { resizeTextures: false }), size = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
      const picture = thumbnail(model);
      const updates = { update: () => {} };
      generation = (async () => {
        try {
          // details() appends synchronously below. A second frame ensures a
          // paint happens before optional generation can do any CPU work.
          await frame(generationEvents.signal); await frame(generationEvents.signal);
          return await generateVersions(entry, model, generationEvents.signal, text => updates.update(text));
        } catch { return []; }
      })();
      const answer = await details({ ...entry, triangles: budget.triangles, heavy: budget.heavy, warning: entry.warning || budget.warning }, suggestKind(size.toArray()), picture, signal, generation, updates);
      if (!answer || !canEdit()) return;
      rememberImport(await request('imports/' + entry.id, 'PATCH', { ...answer, size: size.toArray(), triangles: budget.triangles })); accepted = true;
      await importedModels(true); await changed(); status.textContent = 'Model added. Drag its thumbnail onto a floor, the ground or a wall.';
      const versions = await generation;
      if (versions.length < 2 && !signal.aborted) status.textContent += ' ' + (versions.note || 'Lighter versions could not all be made this time.');
      await changed();
    } catch (error) { status.textContent = error.message; report(error); }
    finally {
      generationEvents.abort(); await generation; signal.removeEventListener('abort', cancelGeneration);
      if (model) disposeObject(model);
      if (entry && !accepted) {
        await request('imports/' + entry.id, 'DELETE').catch(report);
        forgetImport(entry.id);
      }
      busy = false; picker.value = '';
    }
  }
  listen(el('library-import'), 'click', () => { if (canEdit() && !busy) picker.click(); });
  listen(picker, 'change', () => add([...picker.files]));
  listen(canvas, 'dragover', event => { if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } });
  listen(canvas, 'drop', event => { if (event.dataTransfer?.files.length) { event.preventDefault(); add([...event.dataTransfer.files]); } });
  listen(el('library-import-limit'), 'change', async () => {
    if (!canEdit()) return;
    try { await request('import-settings', 'PUT', { limit_mb: Number(el('library-import-limit').value) }); }
    catch (error) { report(error); }
  });
  listen(el('library-import-unpacked-limit'), 'change', async () => {
    if (!canEdit()) return;
    try { await request('import-settings', 'PUT', { unpacked_limit_mb: Number(el('library-import-unpacked-limit').value) }); }
    catch (error) { report(error); }
  });
}

export async function generateVersions(entry, source, signal, progress = () => {}) {
  const rows = [];
  for (const level of [1, 2]) {
    let model;
    try {
      if (signal.aborted) break;
      progress(`Making lighter versions… ${level} of 2`);
      await frame(signal);
      model = await makeLod(source, level, signal);
      await frame(signal);
      const triangles = modelBudget(model, { resizeTextures: false }).triangles, picture = thumbnail(model);
      await frame(signal);
      const buffer = await new GLTFExporter().parseAsync(model, { binary: true, onlyVisible: true });
      if (signal.aborted) break;
      const name = `lod${level}.glb`;
      if (buffer.byteLength > 50 * 1024 * 1024) throw new Error('Each lighter version may be at most 50 MB.');
      rememberImport(await uploadFiles([new File([buffer], name)], () => {}, signal, request, { asset_id: entry.id, lod: name }));
      rows.push({ name: `LOD${level}`, picture, triangles });
    } catch (error) {
      // Optional derived files never prevent accepting the original.
      if (error.lodSkipped) { rows.note = error.message; progress(error.message); break; }
    }
    finally { if (model) disposeObject(model); }
    if (signal.aborted) break;
  }
  return rows;
}
