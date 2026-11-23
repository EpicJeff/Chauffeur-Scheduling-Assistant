// Static-scene BVH raycaster and visibility-shell builder for security camera cones.
// Runs only at mount / house rebuild / camera aim change, never per frame.
import * as THREE from 'three';

const PICK_LAYER = 31;
const LEAF_MAX = 24;
const EXCLUDED_YARD_PARTS = new Set(['plants', 'grass', 'furniture']);
const EXCLUDED_PREFIXES = ['weather-', 'season-', 'twin-celestial', 'twin-atmosphere', 'editor-', 'eave-'];

function materialExcluded(m) {
  if (!m) return false;
  const d = m.userData;
  return !!(d?.plantWind || d?.seasonFoliage || d?.seasonLawn || d?.noOcclusion) ||
    m.name === 'anchor' || m.name === 'sheet' || m.name === 'ghost';
}

function subtreeExcluded(o, view) {
  if (!o) return true;
  if (o === view?.groups?.gableCut) return true;
  const d = o.userData;
  if (d) {
    if (d.twinMode || d.twinCars || d.carModel || d.cameraCone || d.cameraConePart ||
        d.securityAttention || d.lightWash || d.bulb || d.effectFixtures || d.effectFixture ||
        d.fireFlame || d.ghost || d.preview || d.aimHandle || d.fixtureId || d.noOcclusion ||
        d.yardGrass || d.viewingWalls === 'cut' || d.kind === 'anchor' || d.kind === 'sheet') return true;
    if (d.yardPart && EXCLUDED_YARD_PARTS.has(d.yardPart)) return true;
  }
  const name = typeof o.name === 'string' ? o.name : '';
  if (name && EXCLUDED_PREFIXES.some(prefix => name.startsWith(prefix))) return true;
  return false;
}

// Collect static architectural and yard meshes (walls, floors, ceilings, roofs,
// terrain, hardscape, fences, retaining walls, pool/fire pits; never swaying
// plants, grass, weather, cars, pick proxies, cutaway duplicates, or overlays).
export function collectStaticOccluders(scene, view = null) {
  if (!scene) return [];
  scene.updateMatrixWorld(true);
  const structural = new Set([view?.groups?.roof, view?.groups?.gableFull].filter(Boolean));
  const meshes = [];
  const walk = (o, forceVisible) => {
    if (subtreeExcluded(o, view)) return;
    const isStructural = structural.has(o) || !!o.userData?.levelKey;
    const keepVisible = forceVisible || isStructural;
    if (!o.visible && !keepVisible) return;
    if (o.isMesh && !o.isInstancedMesh && !o.isSkinnedMesh && !o.layers.isEnabled(PICK_LAYER) && o.geometry?.attributes?.position) {
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      if (!mats.some(materialExcluded)) meshes.push(o);
    }
    const children = o.children;
    if (children) for (let i = 0; i < children.length; i++) walk(children[i], keepVisible);
  };
  walk(scene, false);
  return meshes;
}

// Flat AABB BVH over world-space triangles inside optional bounding box(es).
// Double-sided Möller–Trumbore ensures single-sided roofs, ceilings, floors and
// walls stop rays from either side.
export function buildOccluderBVH(meshes, bounds = null) {
  const boxes = !bounds ? null : Array.isArray(bounds) ? bounds : [bounds];
  const boxCount = boxes ? boxes.length : 0;
  const bMinX = new Float32Array(boxCount), bMinY = new Float32Array(boxCount), bMinZ = new Float32Array(boxCount);
  const bMaxX = new Float32Array(boxCount), bMaxY = new Float32Array(boxCount), bMaxZ = new Float32Array(boxCount);
  for (let i = 0; i < boxCount; i++) {
    bMinX[i] = boxes[i].min.x; bMinY[i] = boxes[i].min.y; bMinZ[i] = boxes[i].min.z;
    bMaxX[i] = boxes[i].max.x; bMaxY[i] = boxes[i].max.y; bMaxZ[i] = boxes[i].max.z;
  }
  const overlapsAny = (mnX, mnY, mnZ, mxX, mxY, mxZ) => {
    for (let i = 0; i < boxCount; i++) {
      if (mxX >= bMinX[i] && mnX <= bMaxX[i] && mxY >= bMinY[i] && mnY <= bMaxY[i] && mxZ >= bMinZ[i] && mnZ <= bMaxZ[i]) return true;
    }
    return false;
  };

  const meshBox = new THREE.Box3();
  const keptMeshes = [];
  let maxTris = 0;
  for (let m = 0; m < meshes.length; m++) {
    const mesh = meshes[m], geom = mesh.geometry, pos = geom?.attributes?.position;
    if (!pos || pos.itemSize < 3) continue;
    if (boxCount) {
      if (!geom.boundingBox) geom.computeBoundingBox();
      if (geom.boundingBox) {
        meshBox.copy(geom.boundingBox).applyMatrix4(mesh.matrixWorld);
        if (!overlapsAny(meshBox.min.x, meshBox.min.y, meshBox.min.z, meshBox.max.x, meshBox.max.y, meshBox.max.z)) continue;
      }
    }
    const count = geom.index ? geom.index.count : pos.count;
    if (count < 3) continue;
    keptMeshes.push(mesh);
    maxTris += (count / 3) | 0;
  }

  if (!maxTris) return { triCount: 0, nodeCount: 0, castRay: (_ox, _oy, _oz, _dx, _dy, _dz, _tMin, tMax) => tMax };

  const tris = new Float32Array(maxTris * 9);
  let triCount = 0;
  for (let m = 0; m < keptMeshes.length; m++) {
    const mesh = keptMeshes[m], geom = mesh.geometry, pos = geom.attributes.position;
    const idx = geom.index, idxArr = idx?.array, count = idx ? idx.count : pos.count;
    const pArr = pos.array, stride = pos.isInterleavedBufferAttribute ? pos.data.stride : pos.itemSize;
    const offset = pos.isInterleavedBufferAttribute ? pos.offset : 0;
    const e = mesh.matrixWorld.elements;
    const e0 = e[0], e1 = e[1], e2 = e[2], e4 = e[4], e5 = e[5], e6 = e[6], e8 = e[8], e9 = e[9], e10 = e[10], e12 = e[12], e13 = e[13], e14 = e[14];
    for (let i = 0; i + 2 < count; i += 3) {
      const a = (idxArr ? idxArr[i] : i) * stride + offset;
      const b = (idxArr ? idxArr[i + 1] : i + 1) * stride + offset;
      const c = (idxArr ? idxArr[i + 2] : i + 2) * stride + offset;
      const ax = pArr[a], ay = pArr[a + 1], az = pArr[a + 2];
      const v0x = e0 * ax + e4 * ay + e8 * az + e12;
      const v0y = e1 * ax + e5 * ay + e9 * az + e13;
      const v0z = e2 * ax + e6 * ay + e10 * az + e14;
      const bx = pArr[b], by = pArr[b + 1], bz = pArr[b + 2];
      const v1x = e0 * bx + e4 * by + e8 * bz + e12;
      const v1y = e1 * bx + e5 * by + e9 * bz + e13;
      const v1z = e2 * bx + e6 * by + e10 * bz + e14;
      const cx = pArr[c], cy = pArr[c + 1], cz = pArr[c + 2];
      const v2x = e0 * cx + e4 * cy + e8 * cz + e12;
      const v2y = e1 * cx + e5 * cy + e9 * cz + e13;
      const v2z = e2 * cx + e6 * cy + e10 * cz + e14;
      if (boxCount) {
        const mnX = v0x < v1x ? (v0x < v2x ? v0x : v2x) : (v1x < v2x ? v1x : v2x);
        const mxX = v0x > v1x ? (v0x > v2x ? v0x : v2x) : (v1x > v2x ? v1x : v2x);
        const mnY = v0y < v1y ? (v0y < v2y ? v0y : v2y) : (v1y < v2y ? v1y : v2y);
        const mxY = v0y > v1y ? (v0y > v2y ? v0y : v2y) : (v1y > v2y ? v1y : v2y);
        const mnZ = v0z < v1z ? (v0z < v2z ? v0z : v2z) : (v1z < v2z ? v1z : v2z);
        const mxZ = v0z > v1z ? (v0z > v2z ? v0z : v2z) : (v1z > v2z ? v1z : v2z);
        if (!overlapsAny(mnX, mnY, mnZ, mxX, mxY, mxZ)) continue;
      }
      const o = triCount * 9;
      tris[o] = v0x; tris[o + 1] = v0y; tris[o + 2] = v0z;
      tris[o + 3] = v1x - v0x; tris[o + 4] = v1y - v0y; tris[o + 5] = v1z - v0z;
      tris[o + 6] = v2x - v0x; tris[o + 7] = v2y - v0y; tris[o + 8] = v2z - v0z;
      triCount++;
    }
  }

  if (!triCount) return { triCount: 0, nodeCount: 0, castRay: (_ox, _oy, _oz, _dx, _dy, _dz, _tMin, tMax) => tMax };
  const tBounds = new Float32Array(triCount * 6);
  const centroids = new Float32Array(triCount * 3);
  const order = new Int32Array(triCount);
  for (let i = 0; i < triCount; i++) {
    order[i] = i;
    const o = i * 9, ax = tris[o], ay = tris[o + 1], az = tris[o + 2];
    const bx = ax + tris[o + 3], by = ay + tris[o + 4], bz = az + tris[o + 5];
    const cx = ax + tris[o + 6], cy = ay + tris[o + 7], cz = az + tris[o + 8];
    const b = i * 6;
    tBounds[b] = ax < bx ? (ax < cx ? ax : cx) : (bx < cx ? bx : cx);
    tBounds[b + 1] = ay < by ? (ay < cy ? ay : cy) : (by < cy ? by : cy);
    tBounds[b + 2] = az < bz ? (az < cz ? az : cz) : (bz < cz ? bz : cz);
    tBounds[b + 3] = ax > bx ? (ax > cx ? ax : cx) : (bx > cx ? bx : cx);
    tBounds[b + 4] = ay > by ? (ay > cy ? ay : cy) : (by > cy ? by : cy);
    tBounds[b + 5] = az > bz ? (az > cz ? az : cz) : (bz > cz ? bz : cz);
    const c = i * 3;
    centroids[c] = (ax + bx + cx) / 3;
    centroids[c + 1] = (ay + by + cy) / 3;
    centroids[c + 2] = (az + bz + cz) / 3;
  }

  const maxNodes = triCount * 2 + 2;
  const nodeBounds = new Float32Array(maxNodes * 6);
  const nodeMeta = new Int32Array(maxNodes * 2);
  let nodeCount = 0;

  function buildNode(start, end) {
    const id = nodeCount++;
    const nb = id * 6;
    let mnX = Infinity, mnY = Infinity, mnZ = Infinity, mxX = -Infinity, mxY = -Infinity, mxZ = -Infinity;
    let cMnX = Infinity, cMnY = Infinity, cMnZ = Infinity, cMxX = -Infinity, cMxY = -Infinity, cMxZ = -Infinity;
    for (let i = start; i < end; i++) {
      const ti = order[i], b = ti * 6, c = ti * 3;
      if (tBounds[b] < mnX) mnX = tBounds[b];
      if (tBounds[b + 1] < mnY) mnY = tBounds[b + 1];
      if (tBounds[b + 2] < mnZ) mnZ = tBounds[b + 2];
      if (tBounds[b + 3] > mxX) mxX = tBounds[b + 3];
      if (tBounds[b + 4] > mxY) mxY = tBounds[b + 4];
      if (tBounds[b + 5] > mxZ) mxZ = tBounds[b + 5];
      if (centroids[c] < cMnX) cMnX = centroids[c];
      if (centroids[c + 1] < cMnY) cMnY = centroids[c + 1];
      if (centroids[c + 2] < cMnZ) cMnZ = centroids[c + 2];
      if (centroids[c] > cMxX) cMxX = centroids[c];
      if (centroids[c + 1] > cMxY) cMxY = centroids[c + 1];
      if (centroids[c + 2] > cMxZ) cMxZ = centroids[c + 2];
    }
    nodeBounds[nb] = mnX; nodeBounds[nb + 1] = mnY; nodeBounds[nb + 2] = mnZ;
    nodeBounds[nb + 3] = mxX; nodeBounds[nb + 4] = mxY; nodeBounds[nb + 5] = mxZ;
    const count = end - start;
    if (count <= LEAF_MAX) {
      nodeMeta[id * 2] = start; nodeMeta[id * 2 + 1] = -count;
      return id;
    }
    const ex = cMxX - cMnX, ey = cMxY - cMnY, ez = cMxZ - cMnZ;
    const axis = ex >= ey && ex >= ez ? 0 : ey >= ez ? 1 : 2;
    const extent = axis === 0 ? ex : axis === 1 ? ey : ez;
    let mid = start;
    if (extent > 1e-6) {
      const split = (axis === 0 ? cMnX + cMxX : axis === 1 ? cMnY + cMxY : cMnZ + cMxZ) * 0.5;
      let left = start, right = end - 1;
      while (left <= right) {
        if (centroids[order[left] * 3 + axis] < split) left++;
        else { const tmp = order[left]; order[left] = order[right]; order[right] = tmp; right--; }
      }
      mid = left;
    }
    if (mid <= start || mid >= end) mid = (start + end) >>> 1;
    const leftId = buildNode(start, mid), rightId = buildNode(mid, end);
    nodeMeta[id * 2] = leftId; nodeMeta[id * 2 + 1] = rightId;
    return id;
  }
  buildNode(0, triCount);

  // Reorder triangles into leaf-contiguous layout for tight cache locality.
  const packed = new Float32Array(triCount * 9);
  for (let i = 0; i < triCount; i++) {
    const src = order[i] * 9, dst = i * 9;
    for (let k = 0; k < 9; k++) packed[dst + k] = tris[src + k];
  }

  const stack = new Int32Array(128);
  function hitBox(nb, ox, oy, oz, ix, iy, iz, tMin, closest) {
    let t1 = (nodeBounds[nb] - ox) * ix, t2 = (nodeBounds[nb + 3] - ox) * ix;
    let tEnter = t1 < t2 ? t1 : t2, tExit = t1 > t2 ? t1 : t2;
    t1 = (nodeBounds[nb + 1] - oy) * iy; t2 = (nodeBounds[nb + 4] - oy) * iy;
    const tyMin = t1 < t2 ? t1 : t2, tyMax = t1 > t2 ? t1 : t2;
    if (tyMin > tEnter) tEnter = tyMin;
    if (tyMax < tExit) tExit = tyMax;
    t1 = (nodeBounds[nb + 2] - oz) * iz; t2 = (nodeBounds[nb + 5] - oz) * iz;
    const tzMin = t1 < t2 ? t1 : t2, tzMax = t1 > t2 ? t1 : t2;
    if (tzMin > tEnter) tEnter = tzMin;
    if (tzMax < tExit) tExit = tzMax;
    return tExit >= tEnter && tExit >= tMin && tEnter <= closest ? (tEnter > tMin ? tEnter : tMin) : -1;
  }

  function castRay(ox, oy, oz, dx, dy, dz, tMin, tMax) {
    const ix = Math.abs(dx) > 1e-12 ? 1 / dx : (dx >= 0 ? 1e30 : -1e30);
    const iy = Math.abs(dy) > 1e-12 ? 1 / dy : (dy >= 0 ? 1e30 : -1e30);
    const iz = Math.abs(dz) > 1e-12 ? 1 / dz : (dz >= 0 ? 1e30 : -1e30);
    let closest = tMax;
    if (hitBox(0, ox, oy, oz, ix, iy, iz, tMin, closest) < 0) return tMax;
    let sp = 0;
    stack[sp++] = 0;
    while (sp > 0) {
      const id = stack[--sp], m0 = nodeMeta[id * 2], m1 = nodeMeta[id * 2 + 1];
      if (m1 <= 0) {
        const end = m0 - m1;
        for (let i = m0; i < end; i++) {
          const o = i * 9;
          const v0x = packed[o], v0y = packed[o + 1], v0z = packed[o + 2];
          const e1x = packed[o + 3], e1y = packed[o + 4], e1z = packed[o + 5];
          const e2x = packed[o + 6], e2y = packed[o + 7], e2z = packed[o + 8];
          const px = dy * e2z - dz * e2y, py = dz * e2x - dx * e2z, pz = dx * e2y - dy * e2x;
          const det = e1x * px + e1y * py + e1z * pz;
          if (det > -1e-10 && det < 1e-10) continue;
          const invDet = 1 / det;
          const tx = ox - v0x, ty = oy - v0y, tz = oz - v0z;
          const u = (tx * px + ty * py + tz * pz) * invDet;
          if (u < -1e-6 || u > 1 + 1e-6) continue;
          const qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
          const v = (dx * qx + dy * qy + dz * qz) * invDet;
          if (v < -1e-6 || u + v > 1 + 1e-6) continue;
          const t = (e2x * qx + e2y * qy + e2z * qz) * invDet;
          if (t >= tMin && t < closest) closest = t;
        }
      } else {
        const dL = hitBox(m0 * 6, ox, oy, oz, ix, iy, iz, tMin, closest);
        const dR = hitBox(m1 * 6, ox, oy, oz, ix, iy, iz, tMin, closest);
        if (dL >= 0 && dR >= 0) {
          if (dL < dR) { stack[sp++] = m1; stack[sp++] = m0; }
          else { stack[sp++] = m0; stack[sp++] = m1; }
        } else if (dL >= 0) {
          stack[sp++] = m0;
        } else if (dR >= 0) {
          stack[sp++] = m1;
        }
      }
    }
    return closest;
  }

  return { triCount, nodeCount, castRay };
}

export function createConeMaterials() {
  return {
    rim: new THREE.LineBasicMaterial({
      color: '#9abfe5', transparent: true, opacity: 0.18,
      depthTest: true, depthWrite: false, toneMapped: false, fog: false,
    }),
    fill: new THREE.MeshBasicMaterial({
      color: '#7eaee0', transparent: true, opacity: 0.018, side: THREE.DoubleSide,
      depthTest: true, depthWrite: false, toneMapped: false, fog: false,
    }),
  };
}

export const CONE_SECTORS = 24;
export const CONE_RINGS = 12;

// Build a clipped visibility volume for a camera cone:
// - children[0]: depth-tested clipped rim + 4 cardinal ribs (LineSegments, starting at origin)
// - children[1]: depth-tested translucent visibility shell (side skirt + clipped far surface)
export function buildOccludedCone({
  origin, axis, length, fovDeg = 90, occluder = null,
  sectors = CONE_SECTORS, rings = CONE_RINGS, materials = null, target = null,
}) {
  const t0 = performance.now();
  const safeLength = Math.max(0.05, Number.isFinite(length) ? length : 0.05);
  const clampedFov = Math.max(10, Math.min(160, Number.isFinite(fovDeg) ? fovDeg : 90));
  const halfAngle = clampedFov * Math.PI / 360;
  const dirAxis = axis.clone().normalize();
  if (dirAxis.lengthSq() < 1e-8) dirAxis.set(0, 0, -1);
  const refUp = Math.abs(dirAxis.y) < 0.95 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
  const u = new THREE.Vector3().crossVectors(dirAxis, refUp).normalize();
  const v = new THREE.Vector3().crossVectors(dirAxis, u).normalize();

  // Start rays a few cm forward along the camera axis so a camera mounted flush
  // on a wall, ceiling, or bracket never self-hits its own mounting surface,
  // while wide-FOV rays angled back toward that wall still stop cleanly at it.
  const axialOffset = Math.min(0.05, safeLength * 0.05);
  const tMin = 0.02;
  const pullback = 0.02;
  const roX = origin.x + dirAxis.x * axialOffset;
  const roY = origin.y + dirAxis.y * axialOffset;
  const roZ = origin.z + dirAxis.z * axialOffset;

  const vertCount = 2 + rings * sectors; // 0 = origin, 1 = center hit, 2.. = rings 1..rings
  const positions = new Float32Array(vertCount * 3);
  positions[0] = origin.x; positions[1] = origin.y; positions[2] = origin.z;

  let hits = 0;
  const sample = (dx, dy, dz, outIndex) => {
    const tx = origin.x + dx * safeLength, ty = origin.y + dy * safeLength, tz = origin.z + dz * safeLength;
    const vx = tx - roX, vy = ty - roY, vz = tz - roZ;
    const rayLen = Math.hypot(vx, vy, vz);
    let px = tx, py = ty, pz = tz;
    if (occluder && rayLen > tMin) {
      const inv = 1 / rayLen;
      const rdx = vx * inv, rdy = vy * inv, rdz = vz * inv;
      const hitT = occluder.castRay(roX, roY, roZ, rdx, rdy, rdz, tMin, rayLen);
      if (hitT < rayLen - 1e-6) {
        hits++;
        const d = Math.max(0.015, hitT - pullback);
        px = roX + rdx * d; py = roY + rdy * d; pz = roZ + rdz * d;
      }
    }
    const o = outIndex * 3;
    positions[o] = px; positions[o + 1] = py; positions[o + 2] = pz;
  };

  sample(dirAxis.x, dirAxis.y, dirAxis.z, 1);
  const cosTheta = new Float32Array(sectors), sinTheta = new Float32Array(sectors);
  for (let s = 0; s < sectors; s++) {
    const theta = (s / sectors) * Math.PI * 2;
    cosTheta[s] = Math.cos(theta); sinTheta[s] = Math.sin(theta);
  }
  for (let r = 1; r <= rings; r++) {
    const phi = (r / rings) * halfAngle;
    const cp = Math.cos(phi), sp = Math.sin(phi);
    const baseIndex = 2 + (r - 1) * sectors;
    for (let s = 0; s < sectors; s++) {
      const ct = cosTheta[s], st = sinTheta[s];
      const rx = u.x * ct + v.x * st, ry = u.y * ct + v.y * st, rz = u.z * ct + v.z * st;
      sample(dirAxis.x * cp + rx * sp, dirAxis.y * cp + ry * sp, dirAxis.z * cp + rz * sp, baseIndex + s);
    }
  }

  // Indexed shell: side skirt (sectors tris) + center fan (sectors tris) + (rings-1)*sectors*2 cap tris.
  const triCount = sectors + sectors + (rings - 1) * sectors * 2;
  const indices = new Uint16Array(triCount * 3);
  let idx = 0;
  const rimStart = 2 + (rings - 1) * sectors;
  for (let s = 0; s < sectors; s++) {
    const sNext = (s + 1) % sectors;
    // Side skirt from apex to outer rim
    indices[idx++] = 0; indices[idx++] = rimStart + s; indices[idx++] = rimStart + sNext;
    // Center cap fan
    indices[idx++] = 1; indices[idx++] = 2 + s; indices[idx++] = 2 + sNext;
  }
  for (let r = 1; r < rings; r++) {
    const rowA = 2 + (r - 1) * sectors, rowB = 2 + r * sectors;
    for (let s = 0; s < sectors; s++) {
      const sNext = (s + 1) % sectors;
      const a0 = rowA + s, a1 = rowA + sNext, b0 = rowB + s, b1 = rowB + sNext;
      indices[idx++] = a0; indices[idx++] = b0; indices[idx++] = b1;
      indices[idx++] = a0; indices[idx++] = b1; indices[idx++] = a1;
    }
  }

  const shellGeometry = new THREE.BufferGeometry();
  shellGeometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  shellGeometry.setIndex(new THREE.BufferAttribute(indices, 1));
  shellGeometry.computeBoundingSphere();

  // Rim loop + 4 cardinal ribs from origin (keeps children[0] as LineSegments starting at origin).
  const ribStep = Math.max(1, Math.round(sectors / 4));
  const ribIndices = [];
  for (let s = 0; s < sectors; s += ribStep) ribIndices.push(s);
  const linePositions = new Float32Array((sectors + ribIndices.length) * 6);
  let lp = 0;
  for (let s = 0; s < sectors; s++) {
    const a = (rimStart + s) * 3, b = (rimStart + (s + 1) % sectors) * 3;
    linePositions[lp++] = positions[a]; linePositions[lp++] = positions[a + 1]; linePositions[lp++] = positions[a + 2];
    linePositions[lp++] = positions[b]; linePositions[lp++] = positions[b + 1]; linePositions[lp++] = positions[b + 2];
  }
  for (const s of ribIndices) {
    const b = (rimStart + s) * 3;
    linePositions[lp++] = origin.x; linePositions[lp++] = origin.y; linePositions[lp++] = origin.z;
    linePositions[lp++] = positions[b]; linePositions[lp++] = positions[b + 1]; linePositions[lp++] = positions[b + 2];
  }
  const rimGeometry = new THREE.BufferGeometry();
  rimGeometry.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
  rimGeometry.computeBoundingSphere();

  const mats = materials || createConeMaterials();
  const group = target || new THREE.Group();
  if (target) {
    for (const child of [...target.children]) {
      child.geometry?.dispose();
      if (!materials) child.material?.dispose();
      target.remove(child);
    }
  }
  const rim = new THREE.LineSegments(rimGeometry, mats.rim);
  rim.renderOrder = 5;
  rim.userData.noOcclusion = true; rim.userData.reflectionExclude = true; rim.userData.cameraConePart = true;
  const fill = new THREE.Mesh(shellGeometry, mats.fill);
  fill.renderOrder = 5;
  fill.userData.noOcclusion = true; fill.userData.reflectionExclude = true; fill.userData.cameraConePart = true;
  group.add(rim, fill);
  return {
    group,
    rays: 1 + rings * sectors,
    triangles: triCount,
    hits,
    buildMs: performance.now() - t0,
  };
}
