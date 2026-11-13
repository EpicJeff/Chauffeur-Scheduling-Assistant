import { request, report } from './api.js';

const LIMIT = 20 * 1024 * 1024;
const el = id => document.getElementById(id);

export function mountHouses({ history, afterLoad, capture, canLoad, signal, api = { request } }) {
  const panel = el('houses-panel'), list = el('houses-list'), status = el('houses-status');
  const picker = el('houses-file'), openButton = el('editor-houses');
  let busy = false;
  const listen = (node, type, fn) => node.addEventListener(type, fn, { signal });
  function sync() {
    panel.querySelectorAll('button').forEach(button => {
      button.disabled = busy || (button.dataset.load === 'true' && !canLoad());
    });
  }
  async function run(work) {
    if (busy) return;
    busy = true; sync();
    try { await work(); }
    catch (error) { status.textContent = error.message; report(error); }
    finally { busy = false; sync(); }
  }
  function button(label, action, parent) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = label;
    listen(node, 'click', () => run(action)); parent.append(node); return node;
  }
  const notes = result => {
    if (result.notes?.length) window.showGlobalAlert(result.notes.join('\n'));
  };
  async function download(path) {
    const documentData = await api.request(path);
    const blob = new Blob([JSON.stringify(documentData)], { type: 'application/json' });
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url;
    link.download = (documentData.name.replace(/[^\p{L}\p{N}_ .-]/gu, '-').replace(/^[ .]+|[ .]+$/g, '') || 'House') + '.chauffeur-house.json';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function refresh() {
    const result = await api.request('houses');
    if (signal.aborted) return;
    list.replaceChildren();
    for (const save of result.saves) {
      const row = document.createElement('article'); row.className = 'place-card houses-row';
      if (save.thumbnail) {
        const image = document.createElement('img'); image.src = save.thumbnail; image.alt = ''; row.append(image);
      }
      const details = document.createElement('div'), heading = document.createElement('h3');
      heading.textContent = save.name; details.append(heading);
      const meta = document.createElement('p'); meta.className = 'place-muted';
      meta.textContent = `${new Date(save.created_at).toLocaleString()} · ${save.summary.building_count} buildings · ${save.summary.room_count} rooms · ${Math.ceil(save.size / 1024)} KB`;
      details.append(meta);
      const actions = document.createElement('div'); actions.className = 'editor-actions'; details.append(actions);
      const path = `houses/${encodeURIComponent(save.id)}`;
      button('Load', async () => {
        if (!canLoad()) throw new Error('Stop the build and use Back to now before loading a house.');
        if (!await window.promptConfirm(`Load "${save.name}"?`, 'This replaces the current house. You can get the current house back with Undo.', 'Load', 'Cancel')) return;
        await history.perform(async () => {
          if (!canLoad()) throw new Error('Stop the build and use Back to now before loading a house.');
          const result = await api.request(path + '/load', 'POST');
          await afterLoad(result); notes(result);
        });
        close();
      }, actions).dataset.load = 'true';
      button('Rename', async () => {
        const name = await window.promptInput('Rename house', 'Use 1 to 80 characters.', { value: save.name, maxLength: 80 });
        if (name === null) return;
        await api.request(path, 'PATCH', { name }); await refresh();
      }, actions);
      button('Download', () => download(path + '/download'), actions);
      button('Delete', async () => {
        if (!await window.promptConfirm(`Delete "${save.name}"?`, 'This deletes the named save. The current house stays as it is.', 'Delete', 'Cancel')) return;
        await api.request(path, 'DELETE'); await refresh();
      }, actions);
      row.append(details); list.append(row);
    }
    status.textContent = result.saves.length ? `${result.saves.length} saved house${result.saves.length === 1 ? '' : 's'}` : 'No saved houses yet. Save a house before trying something new.';
    sync();
  }
  function close() { panel.hidden = true; openButton.focus(); }
  listen(openButton, 'click', () => {
    panel.hidden = false; el('editor-menu').open = false;
    el('houses-close').focus(); run(refresh);
  });
  listen(el('houses-close'), 'click', close);
  listen(el('houses-save'), 'click', () => run(async () => {
    const name = await window.promptInput('Save current house', 'Name this safe point. Use 1 to 80 characters.', { value: '', maxLength: 80 });
    if (name === null) return;
    let thumbnail = null;
    try { thumbnail = await capture?.(); } catch { /* A thumbnail is optional. */ }
    await api.request('houses', 'POST', { name, thumbnail }); await refresh();
  }));
  listen(el('houses-download-current'), 'click', () => run(() => download('houses/current/download')));
  listen(el('houses-upload'), 'click', () => { if (!busy) picker.click(); });
  listen(picker, 'change', () => run(async () => {
    const file = picker.files?.[0]; picker.value = '';
    if (!file) return;
    if (file.size > LIMIT) throw new Error('House files may be at most 20 MB.');
    const body = new FormData(); body.append('file', file);
    const result = await api.request('houses/upload', 'POST', body);
    await refresh(); notes(result);
    status.textContent = `Uploaded "${result.save.name}". Choose Load when you are ready.`;
  }));
  listen(document, 'keydown', event => {
    if (panel.hidden || document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden)')) return;
    if (event.key === 'Escape' && !busy) { event.preventDefault(); event.stopPropagation(); close(); }
    if (event.key === 'Tab') {
      const buttons = [...panel.querySelectorAll('button')].filter(b => !b.disabled);
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  return { refresh, sync };
}
