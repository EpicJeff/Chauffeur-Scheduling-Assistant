import * as THREE from 'three';
import { MeshoptSimplifier } from '../vendor/meshoptimizer-1.3.0/meshopt_simplifier.js';
import { simplifyMesh } from './lod_worker.js';

export const LOD_RATIOS = [.25, .05];
export const LOD_TEXTURE_SIZES = [1024, 512];
export const LOD_MAX_ERROR = .01;
export const LOD_SMALL_TRIANGLES = 1000;
export const LOD_FALLBACK_MAX_TRIANGLES = 200000;
export const LOD_NEAR_RADII = 8;
export const LOD_FAR_RADII = 24;
export const LOD_HYSTERESIS = .1;
export const lodLevel = (tier, distance, radius) => tier === 'low' ? 2 : distance < radius * LOD_NEAR_RADII ? 0 : tier === 'medium' || distance < radius * LOD_FAR_RADII ? 1 : 2;

const cancelled = signal => { if (signal?.aborted) throw Object.assign(new Error('Making lighter versions cancelled.'), { cancelled: true }); };
export function idle(signal) {
  cancelled(signal);
  return new Promise((resolve, reject) => {
    const finish = () => { signal?.removeEventListener('abort', abort); try { cancelled(signal); resolve(); } catch (e) { reject(e); } };
    const abort = () => { clearTimeout(timer); if (handle !== null) globalThis.cancelIdleCallback?.(handle); signal?.removeEventListener('abort', abort); reject(Object.assign(new Error('Making lighter versions cancelled.'), { cancelled: true })); };
    let handle = null;
    const timer = setTimeout(finish, 250);
    if (globalThis.requestIdleCallback) handle = requestIdleCallback(() => { clearTimeout(timer); finish(); }, { timeout: 250 });
    signal?.addEventListener('abort', abort, { once: true });
  });
}

// rAF callbacks precede paint; two frames let the dialog/progress actually paint.
export async function frame(signal) {
  cancelled(signal);
  await new Promise((resolve, reject) => {
    const finish = () => { signal?.removeEventListener('abort', abort); resolve(); };
    const abort = () => {
      if (globalThis.requestAnimationFrame) globalThis.cancelAnimationFrame?.(handle); else clearTimeout(handle);
      signal?.removeEventListener('abort', abort);
      reject(Object.assign(new Error('Making lighter versions cancelled.'), { cancelled: true }));
    };
    const handle = globalThis.requestAnimationFrame ? requestAnimationFrame(finish) : setTimeout(finish, 0);
    signal?.addEventListener('abort', abort, { once: true });
  });
  cancelled(signal);
}

function workerSession(signal) {
  let worker, pending, disabled = false, serial = 0;
  const close = () => { worker?.terminate(); worker = null; clearTimeout(pending?.timer); };
  const abort = () => { close(); pending?.reject(Object.assign(new Error('Making lighter versions cancelled.'), { cancelled: true })); pending = null; };
  signal?.addEventListener('abort', abort, { once: true });
  return {
    async run(mesh) {
      cancelled(signal);
      const urls = globalThis.window?.chfLodWorker;
      if (disabled || !globalThis.Worker || !urls) return null;
      try {
        if (!worker) {
          worker = new Worker(urls.worker, { type: 'module', name: 'model-lods' });
          worker.onmessage = ({ data }) => {
            if (!pending || data.id !== pending.id) return;
            const job = pending; clearTimeout(job.timer); pending = null;
            data.error ? job.reject(new Error(data.error)) : job.resolve(data);
          };
          worker.onerror = worker.onmessageerror = () => { clearTimeout(pending?.timer); pending?.reject(new Error('Lighter-version worker failed.')); pending = null; };
        }
        return await new Promise((resolve, reject) => {
          const id = ++serial; pending = { id, resolve, reject };
          pending.timer = setTimeout(() => reject(new Error('Lighter-version worker did not answer.')), 60000);
          const transfers = [mesh.indices.buffer, ...Object.values(mesh.attributes).map(a => a.array.buffer)];
          worker.postMessage({ id, mesh, simplifierUrl: urls.simplifier }, transfers);
        });
      } catch (error) {
        close(); pending = null; disabled = true;
        cancelled(signal); return null;
      }
    },
    dispose() { close(); signal?.removeEventListener('abort', abort); },
  };
}

async function meshCopy(source, ratio, signal) {
  const count = source.index?.count || source.attributes.position.count;
  const indices = new Uint32Array(count), attributes = {};
  for (let start = 0; start < count; start += 8192) {
    for (let i = start; i < Math.min(start + 8192, count); ++i) indices[i] = source.index ? source.index.getX(i) : i;
    await frame(signal);
  }
  for (const [name, attr] of Object.entries(source.attributes)) {
    const array = new Float32Array(attr.count * attr.itemSize);
    for (let start = 0; start < attr.count; start += 8192) {
      for (let i = start; i < Math.min(start + 8192, attr.count); ++i)
        for (let c = 0; c < attr.itemSize; ++c) array[i * attr.itemSize + c] = attr.getComponent(i, c);
      await frame(signal);
    }
    attributes[name] = { array, itemSize: attr.itemSize };
  }
  return { indices, attributes, ratio, error: LOD_MAX_ERROR, weights: attributes.uv ? [.5, .5, .5, .1, .1] : [.5, .5, .5], lockBorder: true };
}

export async function simplifyGeometry(source, ratio, signal, session) {
  cancelled(signal);
  const triangles = (source.index?.count || source.attributes.position.count) / 3;
  if (triangles < LOD_SMALL_TRIANGLES) return source.clone();
  if (Object.keys(source.morphAttributes).length) throw new Error('Animated models keep their original version.');
  const ownSession = !session; session ||= workerSession(signal);
  const skip = () => { throw Object.assign(new Error('Original kept. Lighter versions skipped: this mesh exceeds 200,000 triangles and a worker is unavailable.'), { lodSkipped: true }); };
  let out;
  try {
    // Reject an oversized fallback BEFORE copying or welding its vertices.
    if (triangles > LOD_FALLBACK_MAX_TRIANGLES && (!globalThis.Worker || !globalThis.window?.chfLodWorker)) skip();
    let result = await session.run(await meshCopy(source, ratio, signal));
    if (!result) {
      if (triangles > LOD_FALLBACK_MAX_TRIANGLES) skip();
      // The worker may have detached its inputs before failing. Recopy LOD0.
      result = await simplifyMesh(await meshCopy(source, ratio, signal), MeshoptSimplifier, () => frame(signal));
    }
    cancelled(signal);
    out = new THREE.BufferGeometry();
    for (const [name, attr] of Object.entries(source.attributes)) {
      const array = new attr.array.constructor(result.vertices.length * attr.itemSize);
      const copy = new THREE.BufferAttribute(array, attr.itemSize, attr.normalized);
      for (let start = 0; start < result.vertices.length; start += 8192) {
        for (let i = start; i < Math.min(start + 8192, result.vertices.length); ++i)
          for (let c = 0; c < attr.itemSize; ++c) copy.setComponent(i, c, attr.getComponent(result.vertices[i], c));
        await frame(signal);
      }
      out.setAttribute(name, copy);
    }
    if (result.normal) out.setAttribute('normal', new THREE.BufferAttribute(result.normal, 3));
    out.setIndex(new THREE.BufferAttribute(result.indices, 1)); out.computeBoundingBox(); out.computeBoundingSphere();
    return out;
  } catch (error) { out?.dispose(); throw error; }
  finally { if (ownSession) session.dispose(); }
}

export async function makeLod(source, level, signal) {
  cancelled(signal);
  const session = workerSession(signal);
  const root = source.clone(true), materials = new Map(), textures = new Map(), meshes = [];
  root.traverse(o => { if (o.isMesh) meshes.push(o); });
  const textureCopy = async texture => {
    if (!textures.has(texture)) {
      await frame(signal);
      const copy = texture.clone(), image = texture.image, max = LOD_TEXTURE_SIZES[level - 1];
      if (image && Math.max(image.width, image.height) > max) {
        const canvas = document.createElement('canvas'), ratio = max / Math.max(image.width, image.height);
        canvas.width = Math.max(1, Math.round(image.width * ratio)); canvas.height = Math.max(1, Math.round(image.height * ratio));
        canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
        // Texture.clone shares its Source; assigning image would shrink LOD0 too.
        copy.source = new THREE.TextureSource(canvas);
      }
      copy.needsUpdate = true; textures.set(texture, copy);
    }
    return textures.get(texture);
  };
  try {
    for (const mesh of meshes) {
      await idle(signal);
      if (mesh.isSkinnedMesh || mesh.isInstancedMesh) throw new Error('Animated models keep their original version.');
      mesh.geometry = await simplifyGeometry(mesh.geometry, LOD_RATIOS[level - 1], signal, session);
      const copy = async material => {
        if (!materials.has(material)) {
          const out = material.clone();
          materials.set(material, out);
          for (const [key, value] of Object.entries(out)) if (value?.isTexture) out[key] = await textureCopy(value);
        }
        return materials.get(material);
      };
      const copies = [];
      for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) copies.push(await copy(material));
      mesh.material = Array.isArray(mesh.material) ? copies : copies[0];
    }
    cancelled(signal); return root;
  } catch (error) {
    // Unprocessed meshes still reference the original; release only our copies.
    root.traverse(o => { if (o.geometry && !meshes.some(m => m !== o && m.geometry === o.geometry) && !hasGeometry(source, o.geometry)) o.geometry.dispose(); });
    materials.forEach(m => m.dispose()); textures.forEach(t => t.dispose()); throw error;
  } finally { session.dispose(); }
}
function hasGeometry(root, geometry) { let found = false; root.traverse(o => { if (o.geometry === geometry) found = true; }); return found; }

export function tierModel(levels, tier) {
  if (tier === 'low') return levels[2] || levels[0];
  if (!levels[1] && (tier === 'medium' || !levels[2])) return levels[0];
  const radius = Math.max(.01, new THREE.Box3().setFromObject(levels[0]).getBoundingSphere(new THREE.Sphere()).radius);
  const lod = new THREE.LOD(); lod.addLevel(levels[0], 0);
  if (levels[1]) lod.addLevel(levels[1], radius * LOD_NEAR_RADII, LOD_HYSTERESIS);
  if (tier !== 'medium' && levels[2]) lod.addLevel(levels[2], radius * LOD_FAR_RADII, LOD_HYSTERESIS);
  // Flattening these meshes would render every level simultaneously.
  lod.traverse(o => { o.userData.modelLod = true; });
  return lod;
}
