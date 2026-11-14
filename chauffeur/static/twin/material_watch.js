import { base, refreshMaterials } from './twin_library.js';

export function watchMaterialCatalogue(view, { api = (path, init) => fetch(base() + path, init) } = {}) {
  const halt = new AbortController(), known = view.materialManifest;
  const revisions = new Map(Object.entries(known).filter(([, e]) => e.household).map(([id, e]) => [id, e.revision]));
  let revision = null, busy = null, rerun = false, stream = null, debounce = null, timer = null;
  function stop() {
    halt.abort(); clearInterval(timer); clearTimeout(debounce); stream?.close();
  }
  function check() {
    if (halt.signal.aborted) return Promise.resolve();
    if (busy) { rerun = true; return busy; }
    busy = (async () => {
      let response;
      try {
        response = await api('api/house/twin/materials/manifest', { signal: halt.signal });
      } catch (error) {
        // Fetch's TypeError is the browser's offline/network-failure response.
        if (!halt.signal.aborted && !(error instanceof TypeError)) console.error('Material manifest read failed:', error);
        return;
      }
      if (halt.signal.aborted) return;
      if (response.status === 401 || response.status === 403) { stop(); return; }
      if (!response.ok) { console.error('Material manifest read failed: HTTP', response.status); return; }
      const catalogue = await response.json();
      if (catalogue.revision === revision) return;
      const entries = Object.entries(catalogue.entries);
      const ids = entries.filter(([id, entry]) => revisions.get(id) !== entry.revision).map(([id]) => id);
      for (const [id, entry] of entries) known[id] = entry;
      if (ids.length) {
        refreshMaterials(ids, known);
        await view.refreshMaterials(ids);
        if (halt.signal.aborted) return;
        view.render();
      }
      for (const [id, entry] of entries) revisions.set(id, entry.revision);
      revision = catalogue.revision;
      document.dispatchEvent(new CustomEvent('chf-materials-changed', { detail: { ids } }));
    })().catch(error => {
      if (!halt.signal.aborted) console.error('Material refresh failed:', error);
    }).finally(async () => {
      busy = null;
      if (rerun && !halt.signal.aborted) { rerun = false; await check(); }
    });
    return busy;
  }
  window.addEventListener('focus', check, { signal: halt.signal });
  document.addEventListener('chf-server-update', check, { signal: halt.signal });
  // Picker reads remain parent-only; they signal a fresh viewer-safe read.
  document.addEventListener('chf-material-catalogue', check, { signal: halt.signal });
  // Nav already forwards this stream on panels. Other viewers own one debounced
  // subscription with exactly the same 1.5 s burst window as nav.
  if (new URLSearchParams(location.search).get('panel') !== 'true' && typeof EventSource === 'function') {
    try {
      const url = base() + 'api/stream';
      stream = new EventSource(window.chfAuthUrl ? window.chfAuthUrl(url) : url);
      stream.onmessage = event => {
        if (event.data !== 'update' || halt.signal.aborted) return;
        clearTimeout(debounce); debounce = setTimeout(check, 1500);
      };
    } catch (error) { console.error('Material update stream failed:', error); }
  }
  timer = setInterval(check, 60000);
  check();
  return { check, stop };
}
