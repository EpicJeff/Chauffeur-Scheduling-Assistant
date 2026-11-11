// Web Locks require HTTPS. HA's LAN HTTP pages use an IndexedDB lease instead.
export async function withBakeLock(key, work) {
  if (globalThis.navigator?.locks) return navigator.locks.request('twin-bake-' + key, work);
  if (!globalThis.indexedDB) return work();
  const db = await new Promise((resolve, reject) => {
    const r = indexedDB.open('twin-bake-locks', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('leases');
    r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error);
  });
  const owner = [...globalThis.crypto.getRandomValues(new Uint32Array(4))].join('-');
  function lease(release = false) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction('leases', 'readwrite'), store = tx.objectStore('leases');
      let held = false;
      const r = store.get(key);
      r.onsuccess = () => {
        const row = r.result;
        if (release) { if (row?.owner === owner) store.delete(key); }
        else if (!row || row.owner === owner || row.until < Date.now()) {
          store.put({ owner, until: Date.now() + 120000 }, key); held = true;
        }
      };
      tx.oncomplete = () => resolve(held); tx.onerror = tx.onabort = () => reject(tx.error || new Error('Bake lock failed.'));
    });
  }
  let heartbeat;
  try {
    while (!(await lease())) await new Promise(resolve => setTimeout(resolve, 200));
    heartbeat = setInterval(() => { lease().catch(() => {}); }, 15000);
    return await work();
  } finally { clearInterval(heartbeat); await lease(true).catch(() => {}); db.close(); }
}
