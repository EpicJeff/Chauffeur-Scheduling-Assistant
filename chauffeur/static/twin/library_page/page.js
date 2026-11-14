import { base, libUrl, materialUrl } from '../twin_library.js';
import { createPreview } from './preview.js';
import { mountProperties, defaults, slots, node, button } from './properties.js';
import { slotForFilename } from './texture_slots.js';

// Nav owns authentication. Every endpoint stays relative to the ingress base.
export async function libraryApi(path, method = 'GET', body) {
  const response = await fetch(base() + 'api/house/' + path, { method,
    ...(method === 'PATCH' ? { keepalive: true } : {}),
    ...(body === undefined ? {} : body instanceof Blob
      ? { headers: { 'Content-Type': 'application/octet-stream' }, body }
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
  let data;
  try { data = await response.json(); }
  catch { throw new Error(`The Library could not answer (HTTP ${response.status}). Try again.`); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.error || 'The material could not be saved.');
  return data;
}

const copy = value => structuredClone(value);
const merge = (entry, change) => ({ ...entry, ...change, params: { ...entry.params, ...change.params } });
const normalized = entry => ({ ...entry, maps: entry.maps || {}, params: { ...defaults, ...entry.params } });

export function mountLibraryPage(root, { api = libraryApi } = {}) {
  const abort = new AbortController(), { signal } = abort;
  let stopped = false, uploading = false, rows = [], context, properties, propAbort, gridAbort, selection = 0;
  const contexts = new Set(), report = error => { if (!stopped) window.showGlobalAlert(error.message || String(error)); };
  root.replaceChildren();
  const toolbar = node('header', null, 'library-header'), heading = node('h1', 'Material library');
  const back = node('a', 'House editor'); back.href = base() + 'house/editor';
  toolbar.append(heading, back);
  const status = node('output', 'Opening Library…', 'place-muted'); status.setAttribute('role', 'status');
  root.append(toolbar, node('p', 'Changes here apply everywhere this material is used.', 'place-muted'),
    node('p', 'Undo and redo here affect this material. House history keeps material assignments.', 'place-muted'), status);
  const layout = node('div', null, 'library-layout'), left = node('section', null, 'library-browser'),
    centre = node('section', null, 'library-preview'), right = node('aside', null, 'library-properties');
  left.setAttribute('aria-label', 'Material catalogue'); centre.setAttribute('aria-label', 'Live material preview'); right.setAttribute('aria-label', 'Material properties');
  layout.append(left, centre, right); root.append(layout);
  const newButton = button('New material', 'new', async () => {
    if (newButton.disabled) return;
    newButton.disabled = true;
    try { await flush(context); const entry = await api('materials', 'POST', { name: 'New material' });
      search.value = ''; source.value = 'all';
      await refreshRows(); await select(entry.id, entry); } catch (error) { report(error); }
    finally { newButton.disabled = false; }
  }, signal);
  const search = node('input'); search.type = 'search'; search.placeholder = 'Search materials'; search.dataset.librarySearch = '';
  search.setAttribute('aria-label', 'Search materials');
  const source = node('select'); source.dataset.librarySource = ''; source.setAttribute('aria-label', 'Material source');
  for (const [value, label] of [['all', 'All sources'], ['builtin', 'Built-in'], ['downloaded', 'Downloaded'], ['mine', 'Mine']]) {
    const option = node('option', label); option.value = value; source.append(option);
  }
  source.value = 'all';
  const grid = node('div', null, 'library-grid');
  left.append(newButton, search, source, grid);
  search.addEventListener('input', drawGrid, { signal }); source.addEventListener('change', drawGrid, { signal });
  const shape = node('div', null, 'editor-actions'), lighting = node('div', null, 'editor-actions');
  shape.setAttribute('role', 'group'); shape.setAttribute('aria-label', 'Preview shape');
  lighting.setAttribute('role', 'group'); lighting.setAttribute('aria-label', 'Preview lighting');
  const canvas = node('canvas'); canvas.setAttribute('aria-label', 'Orbit material preview with 6 ft scale figure');
  centre.append(shape, canvas, node('p', '6 ft scale figure · Drag to orbit · Scroll or pinch to zoom', 'place-muted'), lighting);
  const preview = createPreview(canvas);
  for (const [value, title] of [['sphere', 'Sphere'], ['cube', 'Cube'], ['wall', 'Wall'], ['ground', 'Ground']]) {
    const control = button(title, value, () => { preview.setShape(value); shape.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === control))); }, signal);
    control.setAttribute('aria-pressed', String(value === 'sphere')); shape.append(control);
  }
  for (const [value, title] of [['studio', 'Neutral studio'], ['sun', 'House day sun']]) {
    const control = button(title, value, () => { preview.setLight(value); lighting.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === control))); }, signal);
    control.setAttribute('aria-pressed', String(value === 'studio')); lighting.append(control);
  }
  const actions = node('div', null, 'editor-actions'), props = node('div'); right.append(actions, props);
  // One listener on the whole panel also handles drops on the nested drop zone.
  right.addEventListener('dragover', event => {
    if (Array.from(event.dataTransfer?.types || []).includes('Files')) {
      event.preventDefault();
      event.dataTransfer.dropEffect = context && context.draft.source !== 'builtin' && !context.busy && !uploading ? 'copy' : 'none';
    }
  }, { signal });
  right.addEventListener('drop', event => {
    event.preventDefault();
    return uploadTextures(Array.from(event.dataTransfer?.files || []));
  }, { signal });
  const endpoint = ctx => 'materials/' + encodeURIComponent(ctx.draft.id);
  function setStatus(ctx, text) {
    if (!stopped && ctx === context) status.textContent = ctx.uploadStatus || text;
  }
  function show(ctx, rebuild = false) {
    if (stopped || ctx !== context) return;
    const params = ctx.localConvention ? { ...ctx.draft.params, normal_convention: ctx.localConvention } : ctx.draft.params;
    preview.setMaterial({ ...ctx.draft, previewMaps: ctx.localMaps }, params);
    if (rebuild) renderProperties(); else properties?.sync(ctx.draft);
  }
  function change(fields) {
    const ctx = context;
    if (!ctx || ctx.draft.source === 'builtin') return;
    ctx.draft = merge(ctx.draft, fields); ctx.pending = merge(ctx.pending, fields);
    show(ctx); setStatus(ctx, 'Unsaved changes');
    clearTimeout(ctx.timer); ctx.timer = setTimeout(() => flush(ctx), 300);
  }
  function accept(ctx, server, rebuild = false) {
    ctx.server = normalized(server); ctx.draft = merge(ctx.queued.reduce(merge, copy(ctx.server)), ctx.pending);
    show(ctx, rebuild); updateRow(ctx.draft);
  }
  function updateRow(entry) {
    const index = rows.findIndex(row => row.id === entry.id);
    const row = { ...entry, builtin: entry.source === 'builtin', color: entry.params.tint };
    if (index === -1) rows.push(row); else rows[index] = row;
    drawGrid();
  }
  function flush(ctx) {
    if (!ctx) return Promise.resolve();
    clearTimeout(ctx.timer);
    const patch = ctx.pending;
    if (!Object.keys(patch).some(k => k !== 'params') && !Object.keys(patch.params || {}).length) return ctx.chain;
    ctx.pending = {};
    ctx.queued.push(patch);
    ctx.chain = ctx.chain.then(async () => {
      try {
        const server = await api(endpoint(ctx), 'PATCH', patch);
        ctx.queued.splice(ctx.queued.indexOf(patch), 1);
        accept(ctx, server); setStatus(ctx, ctx.queued.length || Object.keys(ctx.pending).length ? 'Unsaved changes' : 'Saved');
      } catch (error) {
        // The server may have advanced in another tab. Read it before reverting.
        try { ctx.server = normalized(await api(endpoint(ctx))); } catch { /* Last acknowledged server value remains authoritative offline. */ }
        ctx.queued.splice(ctx.queued.indexOf(patch), 1);
        ctx.draft = merge(ctx.queued.reduce(merge, copy(ctx.server)), ctx.pending); show(ctx); report(error);
        setStatus(ctx, 'Save failed; restored server values');
      }
    });
    return ctx.chain;
  }
  async function mutate(ctx, suffix, method = 'POST', body) {
    await flush(ctx);
    const operation = ctx.chain.then(() => api(endpoint(ctx) + suffix, method, body));
    ctx.chain = operation.then(() => {}, () => {});
    return operation;
  }
  async function action(name) {
    const ctx = context;
    if (!ctx || ctx.busy) return;
    if (name === 'delete' && !await window.promptConfirm(`Delete ${ctx.draft.name}?`,
      'Materials used by the current house cannot be deleted. Earlier house history retains its files.', 'Delete', 'Cancel')) return;
    setBusy(ctx, true);
    try {
      const result = await mutate(ctx, name === 'delete' ? '' : '/' + name, name === 'delete' ? 'DELETE' : 'POST');
      if (name === 'delete') {
        rows = rows.filter(row => row.id !== ctx.draft.id); context = null; drawGrid();
        props.replaceChildren(); actions.replaceChildren();
        status.textContent = result.archived ? 'Material archived' : 'Material deleted';
        if (rows.length) await select(rows[0].id);
      } else if (name === 'duplicate') { search.value = ''; source.value = 'all'; await refreshRows(); await select(result.id, result); }
      else { accept(ctx, result, true); status.textContent = 'Saved'; }
    } catch (error) { report(error); }
    finally { setBusy(ctx, false); }
  }
  async function replaceMap(slot, file) {
    const ctx = context;
    if (stopped || uploading || !ctx || ctx.busy || ctx.draft.source === 'builtin') return;
    uploading = true;
    setBusy(ctx, true);
    try {
      const match = slotForFilename(file.name || '');
      const saved = await uploadMap(ctx, slot, file, slot === 'normal' && match?.slot === 'normal' ? match.convention : undefined);
      if (!stopped && ctx === context) status.textContent = saved ? 'Map saved' : 'Map upload failed';
    } finally { uploading = false; setBusy(ctx, false); }
  }
  function releaseLocal(ctx, slot, url) {
    // stop() may already have released it while the request was in flight.
    if (ctx.localMaps[slot] !== url) return;
    delete ctx.localMaps[slot]; URL.revokeObjectURL(url);
  }
  async function uploadMap(ctx, slot, file, convention) {
    const url = URL.createObjectURL(file); ctx.localMaps[slot] = url;
    ctx.localConvention = convention; show(ctx, true);
    try {
      let result = await mutate(ctx, '/maps/' + slot, 'POST', file);
      if (convention) {
        // The raw-byte route ingests and attaches. Keep its acknowledged map on
        // PATCH failure, and save the slot and its detected convention together.
        accept(ctx, result);
        result = await mutate(ctx, '', 'PATCH', { maps: { [slot]: result.maps[slot] }, params: { normal_convention: convention } });
      }
      releaseLocal(ctx, slot, url); delete ctx.localConvention;
      accept(ctx, result, true); return true;
    } catch (error) {
      releaseLocal(ctx, slot, url); delete ctx.localConvention;
      show(ctx, true); report(error); return false;
    } finally { releaseLocal(ctx, slot, url); }
  }
  async function uploadTextures(files) {
    // Capture the material once: switching selection cannot redirect a batch.
    const ctx = context;
    if (stopped || uploading || !ctx || ctx.busy || ctx.draft.source === 'builtin' || !files.length) return;
    uploading = true;
    setBusy(ctx, true);
    let uploaded = 0, skipped = 0, failed = 0;
    try {
      for (let index = 0; index < files.length && !stopped; index++) {
        const file = files[index];
        try {
          let match = slotForFilename(file.name);
          while (!match && !stopped) {
            const choice = await window.promptInput('Choose texture slot',
              `Which slot does ${file.name} fill?\n${slots.map(([slot, label]) => `${slot}: ${label}`).join('\n')}`,
              { placeholder: 'Enter a slot from the list', okText: 'Assign' });
            if (choice === null) break;
            const slot = choice.trim().toLowerCase();
            if (slots.some(([value]) => value === slot)) match = { slot };
          }
          if (stopped) break;
          if (!match) { skipped++; continue; }
          ctx.uploadStatus = `Uploading ${index + 1} of ${files.length}: ${file.name}`;
          setStatus(ctx, ctx.uploadStatus);
          if (await uploadMap(ctx, match.slot, file, match.convention)) uploaded++; else failed++;
        } catch (error) { failed++; report(error); }
      }
      delete ctx.uploadStatus;
      setStatus(ctx, `Textures: ${uploaded} uploaded, ${skipped} skipped, ${failed} failed`);
    } finally { delete ctx.uploadStatus; uploading = false; setBusy(ctx, false); }
  }
  async function clearMap(slot) {
    const ctx = context;
    if (stopped || uploading || !ctx || ctx.busy || ctx.draft.source === 'builtin') return;
    setBusy(ctx, true);
    try { accept(ctx, await mutate(ctx, '/maps/' + slot, 'DELETE'), true); }
    catch (error) { report(error); }
    finally { setBusy(ctx, false); }
  }
  function setBusy(ctx, busy) {
    ctx.busy = busy;
    if (!context || stopped) return;
    actions.querySelectorAll('button').forEach(control => { control.disabled = !!context.busy; });
    props.querySelectorAll('input[type="file"], [data-action="clear"]')
      .forEach(control => { control.disabled = !!context.busy || uploading; });
  }
  function renderProperties() {
    propAbort?.abort(); propAbort = new AbortController();
    properties = mountProperties(props, { ...context.draft, previewMaps: context.localMaps }, { change, replaceMap, clearMap, uploadTextures, signal: propAbort.signal });
    actions.replaceChildren(button('Duplicate', 'duplicate', () => action('duplicate'), propAbort.signal));
    if (context.draft.source !== 'builtin') {
      for (const [label, name] of [['Undo', 'undo'], ['Redo', 'redo'],
        ...(context.draft.source_snapshot ? [['Reset to source', 'reset']] : []), ['Delete', 'delete']]) {
        actions.append(button(label, name, () => action(name), propAbort.signal));
      }
    }
    setBusy(context, !!context.busy);
  }
  function thumbnail(row) {
    if (row.thumbnail_url) return window.chfAuthUrl ? window.chfAuthUrl(row.thumbnail_url) : row.thumbnail_url;
    const path = row.maps?.base_color || window.twinManifest?.[row.id]?.maps?.base_color;
    if (path) return materialUrl(path.startsWith('materials/') ? path : `materials/${row.id}/${path}`);
    const asset = window.twinManifest?.[row.id];
    const file = Object.keys(asset?.files || {}).find(name => name.includes('_diff_'));
    return file ? libUrl(row.id, file) : null;
  }
  function drawGrid() {
    if (stopped) return;
    gridAbort?.abort(); gridAbort = new AbortController();
    grid.replaceChildren(); const query = search.value.toLowerCase();
    for (const row of rows.filter(row => !row.archived && row.name.toLowerCase().includes(query)
      && (source.value === 'all' || source.value === 'builtin' && row.source === 'builtin'
        || source.value === 'mine' && ['user', 'gltf'].includes(row.source)
        || source.value === 'downloaded' && ['polyhaven', 'ambientcg'].includes(row.source)))) {
      const control = button('', 'select', () => select(row.id).catch(report), gridAbort.signal); control.dataset.material = row.id;
      control.setAttribute('aria-pressed', String(context?.draft.id === row.id));
      const image = node('img'); image.alt = ''; image.width = 112; image.height = 96;
      image.style.backgroundColor = row.color || row.params?.tint || '#b8b0a4';
      // A map that cannot load (offline, a missing file) leaves the colour swatch, not a broken image.
      image.addEventListener('error', () => image.removeAttribute('src'), { once: true });
      const url = thumbnail(row); if (url) image.src = url;
      control.append(image, node('span', row.name), node('small', row.source)); grid.append(control);
    }
    if (!grid.children.length) grid.append(node('p', 'No matching materials.', 'place-muted'));
  }
  async function refreshRows() {
    const catalogue = await api('materials');
    rows = catalogue.materials.map(row => ({ ...rows.find(old => old.id === row.id && old.revision === row.revision), ...row })); drawGrid();
  }
  async function select(id, entry) {
    const turn = ++selection; await flush(context);
    const result = entry || await api('materials/' + encodeURIComponent(id));
    if (stopped || turn !== selection) return;
    const server = normalized(result);
    context = { server, draft: copy(server), pending: {}, queued: [], localMaps: {}, chain: Promise.resolve() };
    contexts.add(context); show(context, true); updateRow(server); status.textContent = 'Saved';
  }
  const ready = (async () => {
    await refreshRows(); if (stopped) return;
    const id = new URLSearchParams(location.search).get('material') || rows[0]?.id;
    if (id) await select(id); else status.textContent = 'Create a material to begin.';
  })().catch(error => { if (!stopped) status.textContent = 'The Library could not open. Reload to try again.'; report(error); });
  const saveOnLeave = () => { flush(context); };
  window.addEventListener('pagehide', saveOnLeave, { signal });
  return { ready, stop() {
    if (stopped) return;
    contexts.forEach(ctx => { flush(ctx); Object.entries(ctx.localMaps).forEach(([slot, url]) => releaseLocal(ctx, slot, url)); });
    stopped = true; abort.abort(); propAbort?.abort(); gridAbort?.abort(); preview.dispose();
  } };
}
