import * as THREE from 'three';
import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';
import { MeshoptSimplifier } from '../vendor/meshoptimizer-1.3.0/meshopt_simplifier.js';

export const LOD_RATIOS = [.25, .05];
export const LOD_TEXTURE_SIZES = [1024, 512];
export const LOD_MAX_ERROR = .01;
export const LOD_SMALL_TRIANGLES = 1000;
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

export async function simplifyGeometry(source, ratio) {
  if ((source.index?.count || source.attributes.position.count) / 3 < LOD_SMALL_TRIANGLES) return source.clone();
  if (Object.keys(source.morphAttributes).length) throw new Error('Animated models keep their original version.');
  await MeshoptSimplifier.ready;
  // Welding all attributes restores the indexing lost by the material merge,
  // while retaining discontinuities at UV and normal seams.
  const geometry = mergeVertices(source), position = geometry.attributes.position;
  if (!geometry.attributes.normal) geometry.computeVertexNormals();
  const normal = geometry.attributes.normal, uv = geometry.attributes.uv, stride = uv ? 5 : 3;
  const attributes = new Float32Array(position.count * stride);
  for (let i = 0; i < position.count; ++i) {
    attributes.set([normal.getX(i), normal.getY(i), normal.getZ(i)], i * stride);
    if (uv) attributes.set([uv.getX(i), uv.getY(i)], i * stride + 3);
  }
  const [indices] = MeshoptSimplifier.simplifyWithAttributes(new Uint32Array(geometry.index.array),
    new Float32Array(position.array), 3, attributes, stride, uv ? [.5, .5, .5, .1, .1] : [.5, .5, .5],
    null, Math.max(3, Math.floor(geometry.index.count * ratio / 3) * 3), LOD_MAX_ERROR, ['LockBorder']);
  // Compact every attribute as well as the indices; otherwise GLB still stores
  // all of LOD0's vertices and is not actually lighter.
  const used = [...new Set(indices)], remap = new Map(used.map((v, i) => [v, i])), out = new THREE.BufferGeometry();
  for (const [name, attr] of Object.entries(geometry.attributes)) {
    const values = new attr.array.constructor(used.length * attr.itemSize);
    used.forEach((v, i) => { for (let c = 0; c < attr.itemSize; ++c) values[i * attr.itemSize + c] = attr.getComponent(v, c); });
    out.setAttribute(name, new THREE.BufferAttribute(values, attr.itemSize, attr.normalized));
  }
  out.setIndex(Array.from(indices, v => remap.get(v))); out.computeBoundingBox(); out.computeBoundingSphere(); geometry.dispose();
  return out;
}

export async function makeLod(source, level, signal) {
  const root = source.clone(true), materials = new Map(), textures = new Map(), meshes = [];
  root.traverse(o => { if (o.isMesh) meshes.push(o); });
  const textureCopy = texture => {
    if (!textures.has(texture)) {
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
      mesh.geometry = await simplifyGeometry(mesh.geometry, LOD_RATIOS[level - 1]);
      const copy = material => {
        if (!materials.has(material)) {
          const out = material.clone();
          for (const [key, value] of Object.entries(out)) if (value?.isTexture) out[key] = textureCopy(value);
          materials.set(material, out);
        }
        return materials.get(material);
      };
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map(copy) : copy(mesh.material);
    }
    cancelled(signal); return root;
  } catch (error) {
    // Unprocessed meshes still reference the original; release only our copies.
    root.traverse(o => { if (o.geometry && !meshes.some(m => m !== o && m.geometry === o.geometry) && !hasGeometry(source, o.geometry)) o.geometry.dispose(); });
    materials.forEach(m => m.dispose()); textures.forEach(t => t.dispose()); throw error;
  }
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
