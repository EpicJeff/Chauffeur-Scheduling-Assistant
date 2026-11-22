import * as THREE from '../../vendor/three-r187/three.module.js';
import { packBanks, fingerprint, atlasMesh, heightfieldExtent, prepareReceivers } from './atlas.js';
import { authoredGeometry } from './geometry_key.js';
import { bakeSource, bakeReceiverRoots } from './source.js';
import { bindReceivers } from './bindings.js';
import { ATLAS_WORKER_VERSION } from './key_inputs.js';

export function covered(root) {
  const meshes = [];
  root.traverse(m => { if (atlasMesh(m)) meshes.push(m); });
  return meshes;
}
export function geometryData(g) {
  return { attributes: Object.fromEntries(Object.entries(g.attributes).map(([name, a]) =>
    [name, { array: a.array.slice(), itemSize: a.itemSize, normalized: a.normalized }])),
    index: g.index?.array.slice() || null, userData: g.userData };
}
export function geometryFrom(data) {
  const g = new THREE.BufferGeometry();
  for (const [name, a] of Object.entries(data.attributes)) g.setAttribute(name, new THREE.BufferAttribute(a.array, a.itemSize, a.normalized));
  if (data.index) g.setIndex(new THREE.BufferAttribute(data.index, 1));
  g.userData = data.userData; return g;
}
export function buffers(data) {
  const list = [];
  const visit = v => {
    if (!v || typeof v !== 'object') return;
    if (ArrayBuffer.isView(v)) { if (!list.includes(v.buffer)) list.push(v.buffer); }
    else for (const x of Object.values(v)) visit(x);
  };
  visit(data); return list;
}
export function atlasJob(root, plan, layout) {
  const source=bakeSource(root),neutral=source!==root;root=source;
  root.updateMatrixWorld(true);
  const meshes = covered(root).map(m => {
    let buildingId;
    for (let p = m; p && !buildingId; p = p.parent) buildingId = p.userData.buildingId;
    return { geometry: geometryData(m.geometry), matrix: m.matrixWorld.toArray(), name: m.material.name, buildingId };
  });
  const hash = fingerprint(), uvs = fingerprint();
  // Geometry and room outlines drive the cache. Device movement does not.
  hash.add(ATLAS_WORKER_VERSION); hash.add(authoredGeometry(plan)); hash.add(JSON.stringify(layout));
  for (const m of meshes) {
    hash.add(JSON.stringify([m.matrix, m.name, m.buildingId]));
    // Graded terrain's grid is tiered; its shape is authored (lot, terraces): one key per house.
    if (m.geometry.userData?.bakeHeightfield) { hash.add(JSON.stringify(['heightfield', heightfieldExtent(geometryFrom(m.geometry))])); continue; }
    // Base uv is hashed once, into uvKey, which the input key then folds in.
    for (const [name, a] of Object.entries(m.geometry.attributes)) { hash.add(name); if (name !== 'uv') hash.add(a.array); }
    if (m.geometry.index) hash.add(m.geometry.index);
    uvs.add(m.geometry.attributes.uv?.array || new Float32Array(0)); uvs.add('|');
  }
  if(!neutral)hash.add('uv:' + uvs.key());
  // The layout key ignores base uv, but the cached result carries clipped geometry with
  // it: uvKey says which base uv that geometry holds (see loadAtlas).
  return { meshes, plan, layout, cacheKey: hash.key(), uvKey: neutral?'neutral-surface-topology':uvs.key() };
}
export function packAtlas(atlas, meshes) {
  if (atlas.sourceRoot) meshes=atlas.transportMeshes || covered(atlas.sourceRoot);
  const charts = list => list.map(c => ({ ...c, mesh: meshes.indexOf(c.mesh),
    ...(c.proxies ? { proxies: c.proxies.map(p => ({ mesh: meshes.indexOf(p.mesh), faces: p.faces })) } : {}) }));
  return { key: atlas.key,
    room: { pages: atlas.room.pages, rooms: atlas.room.rooms, plan: atlas.room.plan, charts: charts(atlas.room.charts) },
    geometries: meshes.map(m => geometryData(m.geometry)) };
}
export function applyAtlas(data, root, layout) {
  const source=bakeSource(root),meshes = covered(source);
  data.geometries.forEach((g, i) => { const old = meshes[i].geometry; meshes[i].geometry = geometryFrom(g); old.dispose(); });
  const charts = list => list.map(c => ({ ...c, mesh: meshes[c.mesh],
    ...(c.proxies ? { proxies: c.proxies.map(p => ({ mesh: meshes[p.mesh], faces: p.faces })) } : {}) }));
  const room = { ...data.room, charts: charts(data.room.charts) };
  room.packBanks = (lights, slots) => packBanks(room, lights, layout.room, slots);
  const atlas={key:data.key,room};
  if(source!==root){atlas.sourceRoot=source;bindReceivers(atlas,bakeReceiverRoots(root).flatMap(node=>prepareReceivers(node,room.plan)));}
  return atlas;
}

// ATL1: magic (4 bytes), little-endian JSON byte length (4), UTF-8 header,
// padding to 8 bytes, then one buffer. Paths in a separate descriptor table
// preserve arbitrary userData objects, even ones resembling array descriptors.
const arrayTypes = Object.fromEntries([Int8Array, Uint8Array, Uint8ClampedArray,
  Int16Array, Uint16Array, Int32Array, Uint32Array, Float32Array, Float64Array]
  .map(Type => [Type.name, Type]));
const aligned = n => Math.ceil(n / 8) * 8;
export const MAX_ATLAS_BYTES = 64 * 1024 * 1024;
// Bound inflation separately: the owner's 7 MiB upload expands to about 60 MiB.
const MAX_EXPANDED_BYTES = 256 * 1024 * 1024;
const cancelled = signal => { if (signal?.aborted) throw new Error('Atlas cancelled.'); };

async function streamBytes(stream, signal, limit = MAX_EXPANDED_BYTES) {
  const reader = stream.getReader(), parts = [];
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
      if (length > limit) throw new Error('Atlas container exceeds its size limit.');
      parts.push(value);
    }
    const bytes = new Uint8Array(length); let offset = 0;
    for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
    return bytes;
  } finally { abort(); signal?.removeEventListener('abort', abort); }
}

export async function encodeAtlas(data, { signal, compress = true } = {}) {
  cancelled(signal);
  const arrays = [], chunks = []; let size = 0;
  const visit = (value, path = []) => {
    if (ArrayBuffer.isView(value)) {
      if (!Object.hasOwn(arrayTypes, value.constructor.name)) throw new Error('Unsupported atlas array.');
      size = aligned(size);
      arrays.push({ path, type: value.constructor.name, offset: size, length: value.length });
      chunks.push({ offset: size, bytes: new Uint8Array(value.buffer, value.byteOffset, value.byteLength) });
      size += value.byteLength;
      return null;
    }
    if (Array.isArray(value)) return value.map((v, i) => visit(v, [...path, i]));
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, visit(v, [...path, k])]));
    return value;
  };
  const header = new TextEncoder().encode(JSON.stringify({ data: visit(data), arrays }));
  const start = aligned(8 + header.length);
  if (start + size > MAX_EXPANDED_BYTES) throw new Error('Expanded atlas exceeds 256 MiB.');
  const bytes = new Uint8Array(start + size);
  bytes.set([65, 84, 76, 49]); new DataView(bytes.buffer).setUint32(4, header.length, true);
  bytes.set(header, 8);
  for (const chunk of chunks) bytes.set(chunk.bytes, start + chunk.offset);
  cancelled(signal);
  if (compress && globalThis.CompressionStream) {
    return streamBytes(new Blob([bytes]).stream().pipeThrough(new CompressionStream('gzip')), signal, MAX_ATLAS_BYTES);
  }
  if (bytes.length > MAX_ATLAS_BYTES) throw new Error('Atlas exceeds 64 MiB without compression.');
  return bytes;
}

export async function decodeAtlas(input, { signal } = {}) {
  cancelled(signal);
  let bytes = new Uint8Array(input);
  if (bytes.length > MAX_ATLAS_BYTES) throw new Error('Atlas exceeds 64 MiB.');
  if (bytes[0] === 31 && bytes[1] === 139) {
    bytes = await streamBytes(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')), signal);
  }
  if (bytes.length < 8 || bytes.length > MAX_EXPANDED_BYTES ||
      bytes[0] !== 65 || bytes[1] !== 84 || bytes[2] !== 76 || bytes[3] !== 49) throw new Error('Invalid atlas container.');
  const length = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(4, true);
  const start = aligned(8 + length);
  if (start > bytes.length) throw new Error('Truncated atlas header.');
  const { data, arrays } = JSON.parse(new TextDecoder().decode(bytes.subarray(8, 8 + length)));
  for (const { path, type, offset, length: count } of arrays) {
    const Type = Object.hasOwn(arrayTypes, type) && arrayTypes[type];
    if (!Type || !Number.isSafeInteger(offset) || offset < 0 || offset % 8 ||
        !Number.isSafeInteger(count) || count < 0 || start + offset + count * Type.BYTES_PER_ELEMENT > bytes.length ||
        !Array.isArray(path) || !path.length) throw new Error('Invalid atlas array.');
    let parent = data;
    for (const key of path.slice(0, -1)) {
      if (!parent || !Object.hasOwn(parent, key)) throw new Error('Invalid atlas array path.');
      parent = parent[key];
    }
    const key = path.at(-1);
    if (!parent || !Object.hasOwn(parent, key) || parent[key] !== null) throw new Error('Invalid atlas array path.');
    // Own each array independently, as the worker transport/IndexedDB do today.
    Object.defineProperty(parent, key, { value: new Type(bytes.buffer.slice(bytes.byteOffset + start + offset,
      bytes.byteOffset + start + offset + count * Type.BYTES_PER_ELEMENT)), enumerable: true, writable: true, configurable: true });
  }
  cancelled(signal);
  return data;
}
