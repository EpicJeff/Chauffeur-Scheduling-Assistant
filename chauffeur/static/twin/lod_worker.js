// No import-map dependencies: module workers receive the page's versioned URL.
// Also used by the bounded main-thread fallback, with a yield between chunks.
export async function simplifyMesh(mesh, simplifier, yieldWork = async () => {}) {
  const { indices, attributes, ratio, error, weights, lockBorder } = mesh;
  const names = Object.keys(attributes), hashes = new Map(), source = [], welded = new Uint32Array(indices.length);
  // Match BufferGeometryUtils.mergeVertices' 1e-4 tolerance across ALL
  // attributes, preserving normal/UV/colour seams after the material merge.
  for (let start = 0; start < indices.length; start += 8192) {
    for (let i = start; i < Math.min(start + 8192, indices.length); ++i) {
      const vertex = indices[i]; let hash = '';
      for (const name of names) {
        const { array, itemSize } = attributes[name];
        for (let c = 0; c < itemSize; ++c) hash += `${Math.trunc(array[vertex * itemSize + c] * 1e4 + .5)},`;
      }
      let index = hashes.get(hash);
      if (index === undefined) { index = source.length; source.push(vertex); hashes.set(hash, index); }
      welded[i] = index;
    }
    await yieldWork();
  }
  const positions = new Float32Array(source.length * 3), normals = new Float32Array(source.length * 3);
  const uv = attributes.uv, stride = uv ? 5 : 3, values = new Float32Array(source.length * stride);
  for (let start = 0; start < source.length; start += 8192) {
    for (let i = start; i < Math.min(start + 8192, source.length); ++i) {
      const v = source[i];
      for (let c = 0; c < 3; ++c) {
        positions[i * 3 + c] = attributes.position.array[v * attributes.position.itemSize + c];
        if (attributes.normal) normals[i * 3 + c] = attributes.normal.array[v * 3 + c];
      }
    }
    await yieldWork();
  }
  if (!attributes.normal) {
    for (let start = 0; start < welded.length; start += 8190) {
      for (let i = start; i < Math.min(start + 8190, welded.length); i += 3) {
        const a = welded[i] * 3, b = welded[i + 1] * 3, c = welded[i + 2] * 3;
        const ab = [positions[a] - positions[b], positions[a + 1] - positions[b + 1], positions[a + 2] - positions[b + 2]];
        const cb = [positions[c] - positions[b], positions[c + 1] - positions[b + 1], positions[c + 2] - positions[b + 2]];
        const n = [cb[1] * ab[2] - cb[2] * ab[1], cb[2] * ab[0] - cb[0] * ab[2], cb[0] * ab[1] - cb[1] * ab[0]];
        for (const v of [a, b, c]) for (let k = 0; k < 3; ++k) normals[v + k] += n[k];
      }
      await yieldWork();
    }
  }
  for (let start = 0; start < source.length; start += 8192) {
    for (let i = start; i < Math.min(start + 8192, source.length); ++i) {
      const length = attributes.normal ? 1 : Math.hypot(...normals.subarray(i * 3, i * 3 + 3)) || 1;
      for (let c = 0; c < 3; ++c) values[i * stride + c] = normals[i * 3 + c] / length;
      if (uv) for (let c = 0; c < 2; ++c) values[i * stride + 3 + c] = uv.array[source[i] * uv.itemSize + c];
    }
    await yieldWork();
  }
  await simplifier.ready;
  await yieldWork();
  const [reduced] = simplifier.simplifyWithAttributes(welded, positions, 3, values, stride, weights,
    null, Math.max(3, Math.floor(indices.length * ratio / 3) * 3), error, lockBorder ? ['LockBorder'] : []);
  const used = [], remap = new Map(), compact = new Uint32Array(reduced.length);
  for (let i = 0; i < reduced.length; ++i) {
    const v = reduced[i];
    if (!remap.has(v)) { remap.set(v, used.length); used.push(v); }
    compact[i] = remap.get(v);
    if (i % 8192 === 8191) await yieldWork();
  }
  const vertices = Uint32Array.from(used, v => source[v]);
  const normal = attributes.normal ? null : Float32Array.from(used.flatMap(v => Array.from(values.subarray(v * stride, v * stride + 3))));
  return { indices: compact, vertices, normal };
}

// Kept separate so Node can exercise the real message protocol without a browser.
export async function handleLodMessage({ id, simplifierUrl, mesh }, send) {
  try {
    const { MeshoptSimplifier } = await import(simplifierUrl);
    const result = await simplifyMesh(mesh, MeshoptSimplifier);
    send({ id, ...result }, [result.indices.buffer, result.vertices.buffer, ...(result.normal ? [result.normal.buffer] : [])]);
  } catch (error) { send({ id, error: error.message || String(error) }); }
}
if (typeof WorkerGlobalScope !== 'undefined' && globalThis instanceof WorkerGlobalScope) {
  globalThis.onmessage = event => handleLodMessage(event.data, (message, transfers) => globalThis.postMessage(message, transfers));
}
