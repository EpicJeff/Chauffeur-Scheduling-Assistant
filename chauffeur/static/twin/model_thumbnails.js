import * as THREE from 'three';
import { disposeObject } from './twin_library.js';

const DEFAULT_DIRECTION = [1, 0.65, 1];

// Fit a bounding box's projected corners to the camera's aspect ratio with modest
// padding (~12-14% total), keeping every corner inside the frame.
export function frameThumbnailCamera(box, camera, { direction = DEFAULT_DIRECTION, padding = 0.14 } = {}) {
  if (!box || box.isEmpty()) return;
  const centre = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const dir = new THREE.Vector3(...direction).normalize();
  const corners = [];
  for (const x of [box.min.x, box.max.x]) {
    for (const y of [box.min.y, box.max.y]) {
      for (const z of [box.min.z, box.max.z]) corners.push(new THREE.Vector3(x, y, z));
    }
  }
  let minZ = Infinity, maxZ = -Infinity;
  const offset = new THREE.Vector3();
  for (const c of corners) {
    const z = offset.subVectors(c, centre).dot(dir);
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }
  const targetFill = Math.max(0.5, Math.min(0.94, 1 - padding));
  const maxAllowedAbs = Math.min(0.95, 1 - padding * 0.4);
  const projected = new THREE.Vector3();
  const measure = distance => {
    camera.position.copy(centre).addScaledVector(dir, distance);
    camera.lookAt(centre);
    camera.near = Math.max(0.01, (distance - maxZ) * 0.25);
    camera.far = Math.max(100, (distance - minZ) * 4);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const c of corners) {
      projected.copy(c).project(camera);
      if (projected.x < minX) minX = projected.x;
      if (projected.x > maxX) maxX = projected.x;
      if (projected.y < minY) minY = projected.y;
      if (projected.y > maxY) maxY = projected.y;
    }
    const spanX = (maxX - minX) / 2, spanY = (maxY - minY) / 2;
    const maxAbs = Math.max(Math.abs(minX), Math.abs(maxX), Math.abs(minY), Math.abs(maxY));
    return { spanX, spanY, limiting: Math.max(spanX, spanY), maxAbs };
  };
  const diag = Math.max(size.length(), 0.1);
  let lo = maxZ + Math.max(diag * 0.05, 0.02);
  let hi = maxZ + Math.max(diag * 16, 10);
  while (measure(hi).limiting > targetFill && hi < 1e5) hi *= 2;
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2;
    const m = measure(mid);
    if (m.limiting > targetFill || m.maxAbs > maxAllowedAbs) lo = mid;
    else hi = mid;
  }
  return measure(hi);
}

// One detached canvas serves all model thumbnails; callers own load & release policy.
// Lighting, clipping and tone-mapping match editor/library.js's thumbnail look.
export function createThumbnailRenderer({ width = 112, height = 96, fov = 36, padding = 0.14, fallbackBox = false } = {}) {
  let renderer = null, scene = null, camera = null, disposed = false;

  function ensure() {
    if (renderer || disposed) return renderer;
    const canvas = document.createElement('canvas');
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
    renderer.setSize(width, height, false);
    renderer.setPixelRatio(1);
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(fov, width / height, .01, 100);
    const sun = new THREE.DirectionalLight('#fff3de', 3);
    sun.position.set(3, 5, 4);
    scene.add(new THREE.HemisphereLight('#ffffff', '#68764f', 2), sun);
    return renderer;
  }

  function render(object, { release = o => disposeObject(o), fallback = fallbackBox } = {}) {
    if (!object) return null;
    if (disposed) { release(object); return null; }
    let target = object, usedFallback = false;
    try {
      const r = ensure();
      if (!r || disposed) return null;
      const box = new THREE.Box3().setFromObject(target);
      if (box.isEmpty()) {
        if (!fallback) return null;
        release(target);
        target = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ color: '#b8b0a4' }));
        usedFallback = true;
        box.setFromObject(target);
      }
      frameThumbnailCamera(box, camera, { padding });
      scene.add(target);
      r.render(scene, camera);
      const url = typeof r.domElement?.toDataURL === 'function' ? r.domElement.toDataURL('image/png') : null;
      target.removeFromParent();
      return url || null;
    } finally {
      if (target) {
        target.removeFromParent();
        if (usedFallback) disposeObject(target);
        else release(target);
      }
    }
  }

  return {
    render,
    get disposed() { return disposed; },
    dispose() {
      disposed = true;
      if (renderer) {
        renderer.dispose();
        renderer.forceContextLoss?.();
        renderer = null;
      }
      scene = null;
      camera = null;
    },
  };
}
