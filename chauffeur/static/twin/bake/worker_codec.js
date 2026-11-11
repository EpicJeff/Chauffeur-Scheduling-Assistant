export function workerCodec() {
  const worker = new Worker(new URL('./codec_worker.js', import.meta.url));
  let serial = 0, stopped = false;
  const pending = new Map();
  worker.onmessage = ({ data }) => {
    const p = pending.get(data.id); if (!p) return;
    pending.delete(data.id); data.error ? p.reject(new Error(data.error)) : p.resolve(data.result);
  };
  const fail = error => { for (const p of pending.values()) p.reject(error); pending.clear(); };
  worker.onerror = e => { stopped = true; worker.terminate(); fail(new Error(e.message || 'Lightmap worker failed.')); };
  const call = (kind, data) => new Promise((resolve, reject) => {
    if (stopped) { reject(new Error('Lightmap worker stopped.')); return; }
    const id = ++serial; pending.set(id, { resolve, reject });
    // Keep caller-owned channel buffers: they can be reused to preserve a page.
    worker.postMessage({ id, kind, ...data });
  });
  return { encode: job => call('encode', { job }), decode: bytes => call('decode', { bytes }),
    transcode: (bytes, format) => call('transcode', { bytes, format }),
    stop() { stopped = true; worker.terminate(); fail(new Error('Lightmap worker stopped.')); } };
}
