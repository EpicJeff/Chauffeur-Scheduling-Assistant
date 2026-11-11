// Classic worker: Basis's vendored glue exports BASIS through importScripts.
let encoder, transcoder;
const library = async encode => {
  if (encode) {
    if (!encoder) {
      importScripts('../../vendor/basis-universal/basis_encoder.js');
      encoder = BASIS({ locateFile: f => new URL('../../vendor/basis-universal/' + f, self.location.href).href });
      encoder = encoder.then(m => { m.initializeBasis(); return m; });
    }
    return encoder;
  }
  if (!transcoder) {
    importScripts('../../vendor/three-r187/addons/libs/basis/basis_transcoder.js');
    transcoder = BASIS({ locateFile: f => new URL('../../vendor/three-r187/addons/libs/basis/' + f, self.location.href).href });
    transcoder = transcoder.then(m => { m.initializeBasis(); return m; });
  }
  return transcoder;
};
// Serial jobs avoid sharing an encoder's wasm heap between requests.
let queue = Promise.resolve();
self.onmessage = event => {
  queue = queue.then(async () => {
    const { id, kind, job, bytes, format } = event.data;
    try {
      const module = await library(kind === 'encode');
      let result;
      if (kind === 'transcode') {
        const { transcodePage } = await import('./lightmap_material.js');
        result = transcodePage(module, bytes, format);
      } else {
        const { encodePage, decodePage } = await import('./codec.js');
        result = kind === 'encode' ? encodePage(module, job) : decodePage(module, bytes);
      }
      const transfer = result instanceof Uint8Array ? [result.buffer] :
        (result.mipmaps || result.channels).map(x => (x.data || x).buffer);
      self.postMessage({ id, result }, transfer);
    } catch (error) { self.postMessage({ id, error: error.message || String(error) }); }
  });
};
