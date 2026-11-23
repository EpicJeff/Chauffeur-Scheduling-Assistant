// Binary chunk codec for per-light visibility grid data.
// Uncompressed payload: magic 'MVG1' (4 bytes), little-endian u32 header length (4 bytes),
// UTF-8 JSON header { layoutHash, device, emitters, count }, 4-byte alignment padding,
// little-endian Uint32Array indices (count * 4 bytes), Uint8Array values (count * emitters bytes),
// where values[i * emitters + emitter] holds visibility 0..254 (or 255 = invalid).
// The full payload is gzipped with the Web Streams CompressionStream / DecompressionStream API.

export const GRID_CHUNK_MAGIC = 'MVG1';
export const MAX_CHUNK_BYTES = 8 * 1024 * 1024;
const MAX_EXPANDED_BYTES = 64 * 1024 * 1024;

const MAGIC = [77, 86, 71, 49]; // 'MVG1'
const encoder = new TextEncoder();
const decoder = new TextDecoder();

const aligned4 = n => (n + 3) & ~3;
const cancelled = signal => { if (signal?.aborted) throw new Error('Grid chunk cancelled.'); };

async function streamBytes(stream, signal, limit = MAX_EXPANDED_BYTES) {
  const reader = stream.getReader();
  const parts = [];
  let length = 0;
  const abort = () => { reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', abort, { once: true });
  try {
    cancelled(signal);
    while (true) {
      const { value, done } = await reader.read();
      cancelled(signal);
      if (done) break;
      length += value.byteLength;
      if (length > limit) throw new Error('Grid chunk exceeds its size limit.');
      parts.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const part of parts) {
      bytes.set(part, offset);
      offset += part.byteLength;
    }
    return bytes;
  } finally {
    abort();
    signal?.removeEventListener('abort', abort);
  }
}

export async function encodeGridChunk({ layoutHash, device, emitters, indices, values }, { compress = true, signal } = {}) {
  cancelled(signal);
  if (typeof layoutHash !== 'string' || !layoutHash.length) throw new Error('Invalid grid chunk layoutHash.');
  if (typeof device !== 'string' || !device.length) throw new Error('Invalid grid chunk device.');
  if (!Number.isInteger(emitters) || emitters < 1) throw new Error('Invalid grid chunk emitter count.');
  if (!(indices instanceof Uint32Array)) throw new Error('Grid chunk indices must be a Uint32Array.');
  if (!(values instanceof Uint8Array)) throw new Error('Grid chunk values must be a Uint8Array.');
  const count = indices.length;
  if (values.length !== count * emitters) {
    throw new Error(`Grid chunk values length (${values.length}) does not match indices * emitters (${count * emitters}).`);
  }

  const headerBytes = encoder.encode(JSON.stringify({ layoutHash, device, emitters, count }));
  const indicesStart = aligned4(8 + headerBytes.length);
  const valuesStart = indicesStart + count * 4;
  const totalBytes = valuesStart + values.length;
  if (totalBytes > MAX_EXPANDED_BYTES) throw new Error('Expanded grid chunk exceeds size limit.');

  const raw = new Uint8Array(totalBytes);
  raw.set(MAGIC, 0);
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  view.setUint32(4, headerBytes.length, true);
  raw.set(headerBytes, 8);
  for (let i = 0; i < count; i++) {
    view.setUint32(indicesStart + i * 4, indices[i], true);
  }
  raw.set(values, valuesStart);

  cancelled(signal);
  if (compress && globalThis.CompressionStream) {
    return streamBytes(new Blob([raw]).stream().pipeThrough(new CompressionStream('gzip')), signal, MAX_CHUNK_BYTES);
  }
  if (raw.length > MAX_CHUNK_BYTES) throw new Error('Grid chunk exceeds size limit.');
  return raw;
}

export async function decodeGridChunk(input, { signal } = {}) {
  cancelled(signal);
  let bytes = input instanceof Uint8Array
    ? input
    : ArrayBuffer.isView(input)
      ? new Uint8Array(input.buffer, input.byteOffset, input.byteLength)
      : new Uint8Array(input);
  if (bytes.length > MAX_CHUNK_BYTES) throw new Error('Grid chunk exceeds size limit.');
  if (bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b) {
    bytes = await streamBytes(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')), signal, MAX_EXPANDED_BYTES);
  }
  if (bytes.length < 8 || bytes.length > MAX_EXPANDED_BYTES ||
      bytes[0] !== MAGIC[0] || bytes[1] !== MAGIC[1] || bytes[2] !== MAGIC[2] || bytes[3] !== MAGIC[3]) {
    throw new Error('Invalid grid chunk magic (expected MVG1).');
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerLen = view.getUint32(4, true);
  const indicesStart = aligned4(8 + headerLen);
  if (indicesStart > bytes.length) throw new Error('Truncated grid chunk header.');

  const header = JSON.parse(decoder.decode(bytes.subarray(8, 8 + headerLen)));
  const { layoutHash, device, emitters, count } = header || {};
  if (typeof layoutHash !== 'string' || typeof device !== 'string' ||
      !Number.isInteger(emitters) || emitters < 1 ||
      !Number.isInteger(count) || count < 0) {
    throw new Error('Invalid grid chunk header fields.');
  }
  const valuesStart = indicesStart + count * 4;
  const expectedBytes = valuesStart + count * emitters;
  if (expectedBytes !== bytes.length) {
    throw new Error(`Invalid grid chunk length: expected ${expectedBytes}, got ${bytes.length}.`);
  }

  const indices = new Uint32Array(count);
  for (let i = 0; i < count; i++) {
    indices[i] = view.getUint32(indicesStart + i * 4, true);
  }
  const values = bytes.slice(valuesStart, expectedBytes);
  cancelled(signal);
  return { layoutHash, device, emitters, indices, values };
}
