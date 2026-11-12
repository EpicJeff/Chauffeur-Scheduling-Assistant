import * as THREE from 'three';
import { importedModels, rememberImport, forgetImport, loadModel, disposeObject } from '../twin_library.js';
import { modelBudget, suggestKind, schema } from '../objects.js';
import { request, report } from './api.js';

// Files form one byte stream; chunk boundaries need not match file boundaries.
export async function uploadFiles(files, progress, signal, send = request) {
  const start = await send('imports/uploads', 'POST', {
    name: files[0].name.replace(/\.[^.]+$/, '').slice(0, 100),
    size: files.reduce((n, f) => n + f.size, 0),
    files: files.map(f => ({ name: f.webkitRelativePath || f.name, size: f.size })),
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
function details(entry, suggested, picture, signal) {
  if (signal.aborted) return Promise.resolve(null);
  return new Promise(resolve => {
    const card = document.createElement('form'); card.className = 'object-import'; card.setAttribute('role', 'dialog'); card.setAttribute('aria-label', 'Import model');
    const heading = document.createElement('h3'); heading.textContent = 'Import model'; card.append(heading);
    const image = document.createElement('img'); image.src = picture; image.alt = 'Model preview'; card.append(image);
    const nameLabel = document.createElement('label'); nameLabel.textContent = 'Name';
    const name = document.createElement('input'); name.value = entry.name; name.required = true; name.maxLength = 100; nameLabel.append(name); card.append(nameLabel);
    const kindLabel = document.createElement('label'); kindLabel.textContent = `Kind (suggested: ${suggested})`;
    const kind = document.createElement('select');
    for (const value of Object.keys(schema().kinds)) { const option = document.createElement('option'); option.value = value; option.textContent = value; kind.append(option); }
    kind.value = suggested; kindLabel.append(kind); card.append(kindLabel);
    if (entry.warning) { const note = document.createElement('p'); note.textContent = entry.warning; card.append(note); }
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
  const listen = (node, event, action) => node?.addEventListener(event, action, { signal });
  request('import-settings').then(settings => {
    if (signal.aborted) return;
    if (el('library-import-unpacked-limit')) el('library-import-unpacked-limit').value = settings.unpacked_limit_mb;
  }).catch(report);
  async function add(files) {
    if (!canEdit() || busy || !files.length) return;
    busy = true; let entry = null, accepted = false, model = null;
    try {
      const names = files.map(f => f.name.toLowerCase());
      if (names.some(n => n.endsWith('.skp'))) throw new Error('SketchUp .skp is a closed format and is not supported. Export glTF/GLB.');
      if (names.some(n => /\.(dae|kmz)$/.test(n))) throw new Error('Collada and KMZ are not available in this build. Export glTF/GLB.');
      const settings = await request('import-settings');
      if (files.reduce((n, file) => n + file.size, 0) > settings.limit_mb * 1024 * 1024) throw new Error(`Models may be at most ${settings.limit_mb} MB.`);
      status.textContent = 'Loading model…';
      entry = await uploadFiles(files, text => { status.textContent = text; }, signal); rememberImport(entry);
      model = await loadModel(entry.id, kit);
      if (!model) throw new Error('Could not load this model. Check that its buffers and textures are included.');
      const budget = modelBudget(model), size = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
      const picture = thumbnail(model);
      const answer = await details({ ...entry, warning: entry.warning || budget.warning }, suggestKind(size.toArray()), picture, signal);
      if (!answer || !canEdit()) return;
      rememberImport(await request('imports/' + entry.id, 'PATCH', { ...answer, size: size.toArray() })); accepted = true;
      await importedModels(true); await changed(); status.textContent = 'Model added. Drag its thumbnail onto a floor, the ground or a wall.';
    } catch (error) { status.textContent = error.message; report(error); }
    finally {
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
