import { modelRecord, rememberImport, loadModel, disposeObject } from '../twin_library.js';
import { request } from './api.js';

const preparing = new Map();
const failures = new Map();

// Imports stamp through their existing background level queue. Built-ins have
// no level job, so prepare their server-side part contract on the first hand
// path. Share that work between a Properties read and a simultaneous drop.
export async function prepareModelParts(asset, kit = {}) {
  const record = await modelRecord(asset);
  if (record.parts?.length || record.parts_version || asset.startsWith('import-')) {
    failures.delete(asset); return record;
  }
  const failure = failures.get(asset);
  if (failure && failure.until > Date.now()) throw failure.error;
  if (!preparing.has(asset)) {
    const work = (async () => {
      // Authored source loads are uncached and owned by this caller. Never
      // dispose a clone borrowed from the rendered scene/model cache.
      const source = await loadModel(asset, kit, undefined, { editor:true, source:true });
      if (!source) throw new Error('Could not load model parts.');
      try {
        const parts = source.userData.modelParts;
        if (!parts?.length) return record;
        const stamp = revision => request('models/' + encodeURIComponent(asset), 'PATCH',
          { revision, parts, parts_version:1 }, '');
        try {
          const stamped = await stamp(record.revision);
          rememberImport(stamped); return stamped;
        } catch (error) {
          if (error.status !== 409) throw error;
          // Another tab may have prepared the same metadata in the meantime.
          const current = await modelRecord(asset, { refresh:true });
          if (current.parts?.length || current.parts_version) return current;
          // A fix/level edit need not stamp parts. Retry metadata once against
          // that revision, keeping every unrelated field on the server.
          const stamped = await stamp(current.revision);
          rememberImport(stamped); return stamped;
        }
      } finally { disposeObject(source); }
    })().catch(error => {
      failures.set(asset, { error, until:Date.now() + 30000 }); throw error;
    }).finally(() => preparing.delete(asset));
    preparing.set(asset, work);
  }
  return preparing.get(asset);
}
