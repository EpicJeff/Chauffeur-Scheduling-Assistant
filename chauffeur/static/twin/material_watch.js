import { base, refreshMaterials } from './twin_library.js';

// Each mounted view keeps its own observed revisions, even when two views share
// the same merged manifest. Updating that object must not hide a second view's work.
export function watchMaterialCatalogue(view, { api = (path, init) => fetch(base() + path, init) } = {}) {
  const halt = new AbortController(), known = view.materialManifest;
  const revisions = new Map(Object.entries(known).filter(([, e]) => e.household).map(([id, e]) => [id, e.revision]));
  let revision = null, busy = null;
  async function read(path) {
    const response = await api(path, { signal: halt.signal });
    if (!response.ok) throw new Error('Could not read the material library.');
    return response.json();
  }
  function check(supplied = null) {
    if (halt.signal.aborted) return Promise.resolve();
    if (busy) return busy;
    busy = (async () => {
      try {
        const catalogue = supplied?.materials ? supplied : await read('api/house/materials');
        if (halt.signal.aborted || catalogue.revision === revision) return;
        const rows = catalogue.materials.filter(row => !row.builtin);
        const changed = rows.filter(row => revisions.get(row.id) !== row.revision);
        // Fetch complete records: catalogue rows intentionally contain no maps.
        const entries = await Promise.all(changed.map(async row => [row.id, await read('api/house/materials/' + encodeURIComponent(row.id))]));
        if (halt.signal.aborted) return;
        for (const [id, record] of entries) known[id] = { kind: 'material', household: true, revision: record.revision,
          params: record.params, maps: Object.fromEntries(Object.entries(record.maps || {}).map(([slot, path]) => [slot, `materials/${id}/${path}`])) };
        const ids = entries.map(([id]) => id);
        if (ids.length) {
          refreshMaterials(ids, known);
          await view.refreshMaterials(ids);
          if (halt.signal.aborted) return;
          view.render();
        }
        for (const [id, record] of entries) revisions.set(id, record.revision);
        revision = catalogue.revision;
        document.dispatchEvent(new CustomEvent('chf-materials-changed', { detail: { ids, catalogue } }));
      } catch { /* Offline or expired ingress: retain this view and retry on the next signal. */ }
      finally { busy = null; }
    })();
    return busy;
  }
  window.addEventListener('focus', check, { signal: halt.signal });
  document.addEventListener('chf-server-update', check, { signal: halt.signal });
  document.addEventListener('chf-material-catalogue', event => check(event.detail), { signal: halt.signal });
  // Nav forwards this stream on panels only. Ordinary house/editor tabs need
  // the same server signal too; EventSource retries transient disconnects.
  let stream = null;
  if (typeof EventSource === 'function') {
    try {
      const url = base() + 'api/stream';
      stream = new EventSource(window.chfAuthUrl ? window.chfAuthUrl(url) : url);
      stream.onmessage = event => { if (event.data === 'update') check(); };
    } catch { /* Focus and the catalogue poll remain available offline. */ }
  }
  const timer = setInterval(check, 60000);
  check();
  return { check, stop() { halt.abort(); clearInterval(timer); stream?.close(); } };
}
