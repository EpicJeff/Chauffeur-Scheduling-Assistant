// Light-visibility grid layout, point generation, range query, and inside-solid mask.
// Indoor blocks: 1 ft (0.3048 m) spacing, cell centres inset half a spacing.
// Yard blocks: 2 ft horizontal & vertical spacing, 5 layers from groundAt to groundAt + 10 ft.
import * as THREE from '../../vendor/three-r187/three.module.js';
import { FT } from '../twin_light_math.js';
import { groundAt, buildingBase, inPolygon } from '../twin_ground.js';
import { roomData } from './atlas.js';
import { fingerprint } from './geometry_key.js';

export const INDOOR_SPACING_FT = 1;
export const INDOOR_SPACING = INDOOR_SPACING_FT * FT;
export const YARD_SPACING_FT = 2;
export const YARD_SPACING = YARD_SPACING_FT * FT;
export const YARD_HEIGHT_FT = 10;
export const YARD_LAYERS = 5;
export const GRID_INVALID = 255;
// Cheap manifest evidence for the editor, and part of grid-only chunk identity.
export const GRID_MASK_RULE = 'backface-3-close-2-0.5';

// Fixed 8-degree rotation about a skew axis avoids grazing lattice-aligned
// siding and stair faces while keeping six balanced, deterministic directions.
const tilt = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 2, 3).normalize(), 8 * Math.PI / 180);
const RAY_DIRS = [
  [1, 0, 0], [-1, 0, 0],
  [0, 1, 0], [0, -1, 0],
  [0, 0, 1], [0, 0, -1],
].map(v => new THREE.Vector3(...v).applyQuaternion(tilt).toArray());
const RAY_EPS = 1e-4;
const RAY_MAX = 1e4;

const quant = v => Math.round((v || 0) * 1e6);

function makeRoomToLocal(building, plan, x0, y0, floorFt, spacingFt) {
  const pos = building.position || [0, 0];
  const base = buildingBase(plan, building);
  const rad = (building.rotation || 0) * Math.PI / 180;
  const c = Math.cos(rad), s = Math.sin(rad);
  const sp = spacingFt * FT;
  const ox = (pos[0] + x0 * c - y0 * s) * FT;
  const oy = (base + floorFt) * FT;
  const oz = -(pos[1] + x0 * s + y0 * c) * FT;
  const fromLocal = new THREE.Matrix4().set(
    c * sp, -s * sp, 0, ox,
    0, 0, sp, oy,
    -s * sp, -c * sp, 0, oz,
    0, 0, 0, 1,
  );
  return fromLocal.invert();
}

function makeYardToLocal(x0, y0, spacingFt) {
  const sp = spacingFt * FT;
  const fromLocal = new THREE.Matrix4().set(
    sp, 0, 0, x0 * FT,
    0, 0, sp, 0,
    0, -sp, 0, -y0 * FT,
    0, 0, 0, 1,
  );
  return fromLocal.invert();
}

function boxDistSq(q, maxX, maxY, maxZ, spacing) {
  const dx = q.x < 0 ? -q.x : q.x > maxX ? q.x - maxX : 0;
  const dy = q.y < 0 ? -q.y : q.y > maxY ? q.y - maxY : 0;
  const dz = q.z < 0 ? -q.z : q.z > maxZ ? q.z - maxZ : 0;
  return (dx * dx + dy * dy + dz * dz) * spacing * spacing;
}

// Layout identity depends only on geometry, never the changing lamp set.
// Keep the optional second argument for callers using the original API.
export function gridLayout(plan, _lamps = []) {
  const blocks = [];
  let count = 0;

  // 1. Indoor room blocks
  const data = roomData(plan || {});
  const planBuildings = new Map((plan?.buildings || []).map(b => [b.id, b]));
  for (const [bId, bData] of data.buildings) {
    const b = planBuildings.get(bId);
    if (!b) continue;
    const levelMap = new Map(bData.levels.map(l => [l.id, l]));
    for (const r of bData.rooms) {
      const level = levelMap.get(r.level);
      if (!level || !Number.isFinite(level.ceiling)) continue;
      const ceilingFt = (level.elevation || 0) + level.ceiling;
      const heightFt = ceilingFt - r.floor;
      const [x0, y0, x1, y1] = r.bounds;
      const spanX = x1 - x0, spanY = y1 - y0;
      if (!(spanX > 1e-4 && spanY > 1e-4 && heightFt > 1e-4)) continue;

      const toLocal = makeRoomToLocal(b, plan, x0, y0, r.floor, INDOOR_SPACING_FT);
      const maxX = spanX / INDOOR_SPACING_FT;
      const maxY = spanY / INDOOR_SPACING_FT;
      const maxZ = heightFt / INDOOR_SPACING_FT;

      const nx = Math.max(1, Math.ceil(maxX - 1e-6));
      const ny = Math.max(1, Math.ceil(maxY - 1e-6));
      const nz = Math.max(1, Math.ceil(maxZ - 1e-6));
      const roomMeta = data.rooms[r.index];
      const block = {
        id: `${bId}:${roomMeta?.id ?? r.index}`,
        kind: 'room',
        atlasRoom: r.index,
        building: bId,
        level: r.level,
        spacing: INDOOR_SPACING,
        dims: [nx, ny, nz],
        first: count,
        toLocal,
        origin: [x0, y0, r.floor],
        heightFt,
        poly: r.poly,
      };
      blocks.push(block);
      count += nx * ny * nz;
    }
  }

  // 2. One terrain-following block over the whole lot bounding rectangle.
  // Polygon-exterior cells remain addressable but are invalid in the mask.
  const lot = plan?.site?.lot;
  if (lot?.length >= 3) {
    const lotX0 = Math.min(...lot.map(p => p[0])), lotY0 = Math.min(...lot.map(p => p[1]));
    const lotX1 = Math.max(...lot.map(p => p[0])), lotY1 = Math.max(...lot.map(p => p[1]));
    const nx = Math.max(1, Math.ceil((lotX1 - lotX0) / YARD_SPACING_FT - 1e-6));
    const ny = Math.max(1, Math.ceil((lotY1 - lotY0) / YARD_SPACING_FT - 1e-6));
    const nz = YARD_LAYERS, originX = lotX0, originY = lotY0;
    const ground = new Float32Array(nx * ny);
    let minG = Infinity, maxG = -Infinity;
    for (let iy = 0; iy < ny; iy++) {
      const cy = originY + (iy + 0.5) * YARD_SPACING_FT;
      for (let ix = 0; ix < nx; ix++) {
        const cx = originX + (ix + 0.5) * YARD_SPACING_FT;
        const gM = groundAt(plan, cx, cy) * FT;
        ground[iy * nx + ix] = gM;
        if (gM < minG) minG = gM;
        if (gM > maxG) maxG = gM;
      }
    }
    const toLocal = makeYardToLocal(originX, originY, YARD_SPACING_FT);
    const block = {
      id: 'yard:0',
      kind: 'yard',
      spacing: YARD_SPACING,
      dims: [nx, ny, nz],
      first: count,
      toLocal,
      ground,
      origin: [originX, originY],
      groundBounds: [minG, maxG],
      poly: lot,
    };
    blocks.push(block);
    count += nx * ny * nz;
  }

  // 3. Deterministic layout hash (independent of placed models and lamp order)
  const h = fingerprint();
  h.add('grid-layout-2');
  for (const b of blocks) {
    h.add(JSON.stringify([
      b.id, b.kind, b.atlasRoom ?? null, b.building ?? null, b.level ?? null,
      quant(b.spacing), b.dims, b.first,
      Array.from(b.toLocal.elements, quant),
      b.origin.map(quant),
      b.heightFt !== undefined ? quant(b.heightFt) : null,
      b.poly.map(p => [quant(p[0]), quant(p[1])]),
    ]));
    if (b.ground) {
      const qg = new Int32Array(b.ground.length);
      for (let i = 0; i < b.ground.length; i++) qg[i] = Math.round(b.ground[i] * 1e5);
      h.add(qg);
    }
  }

  return { hash: h.key(), count, blocks };
}

// Returns Float32Array of xyz world metres per global index (length = layout.count * 3).
// Flat index within a block: block.first + (iz * ny + iy) * nx + ix.
export function gridPoints(layout) {
  const out = new Float32Array(layout.count * 3);
  const fromLocal = new THREE.Matrix4();
  const p = new THREE.Vector3();
  for (const b of layout.blocks) {
    fromLocal.copy(b.toLocal).invert();
    const [nx, ny, nz] = b.dims;
    const isYard = b.kind === 'yard';
    const invSp = 1 / b.spacing;
    for (let iz = 0; iz < nz; iz++) {
      const zCell = iz + 0.5;
      for (let iy = 0; iy < ny; iy++) {
        const yCell = iy + 0.5;
        const rowOff = (iz * ny + iy) * nx;
        const gRow = iy * nx;
        for (let ix = 0; ix < nx; ix++) {
          const cz = isYard ? b.ground[gRow + ix] * invSp + zCell : zCell;
          p.set(ix + 0.5, yCell, cz).applyMatrix4(fromLocal);
          const o = (b.first + rowOff + ix) * 3;
          out[o] = p.x;
          out[o + 1] = p.y;
          out[o + 2] = p.z;
        }
      }
    }
  }
  return out;
}

// Returns Uint32Array of global point indices strictly within `range` metres of `source`.
export function pointsInRange(layout, points, source, range) {
  if (!(range > 0) || !points?.length) return new Uint32Array(0);
  const sx = source.x, sy = source.y, sz = source.z;
  const r2 = range * range;
  const hits = [];

  if (!layout?.blocks) {
    const total = (points.length / 3) | 0;
    for (let i = 0; i < total; i++) {
      const o = i * 3;
      const dx = points[o] - sx, dy = points[o + 1] - sy, dz = points[o + 2] - sz;
      if (dx * dx + dy * dy + dz * dz < r2) hits.push(i);
    }
    return new Uint32Array(hits);
  }

  const q = new THREE.Vector3();
  for (const b of layout.blocks) {
    const [nx, ny, nz] = b.dims;
    q.set(sx, sy, sz).applyMatrix4(b.toLocal);
    if (b.kind === 'room') {
      if (boxDistSq(q, nx, ny, nz, b.spacing) >= r2) continue;
    } else {
      const minZ = (b.groundBounds ? b.groundBounds[0] : 0) / b.spacing;
      const maxZ = (b.groundBounds ? b.groundBounds[1] : 0) / b.spacing + nz;
      const dx = q.x < 0 ? -q.x : q.x > nx ? q.x - nx : 0;
      const dy = q.y < 0 ? -q.y : q.y > ny ? q.y - ny : 0;
      const dz = q.z < minZ ? minZ - q.z : q.z > maxZ ? q.z - maxZ : 0;
      if ((dx * dx + dy * dy + dz * dz) * b.spacing * b.spacing >= r2) continue;
    }
    const start = b.first;
    const end = start + nx * ny * nz;
    for (let i = start; i < end; i++) {
      const o = i * 3;
      const dx = points[o] - sx, dy = points[o + 1] - sy, dz = points[o + 2] - sz;
      if (dx * dx + dy * dy + dz * dz < r2) hits.push(i);
    }
  }
  return new Uint32Array(hits);
}

// Cell is the block-local flat address, including rectangular padding cells.
// Keep these addresses in chunks for interpolation, but omit them in debug.
export function cellInBlock(layout, b, cell) {
  const [nx, ny, nz] = b.dims;
  if (cell < 0 || cell >= nx * ny * nz) return false;
  const ix = cell % nx, iy = Math.floor(cell / nx) % ny, iz = Math.floor(cell / (nx * ny));
  const spFt = b.spacing / FT;
  return !(b.poly?.length >= 3 && !inPolygon(b.poly, b.origin[0] + (ix + .5) * spFt, b.origin[1] + (iy + .5) * spFt) ||
    b.kind === 'room' && Number.isFinite(b.heightFt) && (iz + .5) * spFt > b.heightFt + 1e-6);
}

// Optional indices produce a compact mask in that exact order. The baker uses
// small subsets; legacy callers can still request the complete mask explicitly.
export function insideMask(points, bvh, layout, indices = null) {
  const count = indices ? indices.length : layout.count;
  const mask = new Uint8Array(count);
  for (let n = 0; n < count; n++) {
    const i = indices ? indices[n] : n;
    // Blocks have contiguous global addresses, including polygon-exterior cells.
    let lo = 0, hi = layout.blocks.length;
    while (lo + 1 < hi) {
      const mid = (lo + hi) >>> 1;
      if (layout.blocks[mid].first <= i) lo = mid; else hi = mid;
    }
    const b = layout.blocks[lo];
    if (!cellInBlock(layout, b, i - b.first)) {
      mask[n] = 1; continue;
    }
    if (!bvh?.triCount) continue;
    const o = i * 3, ox = points[o], oy = points[o + 1], oz = points[o + 2];
    let back = 0, close = 0;
    for (let d = 0; d < 6; d++) {
      const [dx, dy, dz] = RAY_DIRS[d];
      // Signed nearest t: negative means back face, positive is front/miss.
      const t = bvh.castRayFacing(ox, oy, oz, dx, dy, dz, RAY_EPS, RAY_MAX);
      if (t < 0) { back++; if (-t <= .5) close++; }
      if (back >= 3 && close >= 2) { mask[n] = 1; break; }
      if (back + (5 - d) < 3 || close + (5 - d) < 2) break;
    }
  }
  return mask;
}

export const GRID_MASK_SLICE_MS = 1;

// One channel per mask operation, reused across slices and closed on every exit.
// MessageChannel tasks do not inherit the nested-timer clamp.
function gridYielder() {
  let channel = null, resume = null;
  return {
    yield() {
      if (globalThis.scheduler?.yield) return globalThis.scheduler.yield();
      if (typeof globalThis.MessageChannel === 'function') {
        if (!channel) {
          channel = new globalThis.MessageChannel();
          channel.port1.onmessage = () => { const done = resume; resume = null; done(); };
        }
        return new Promise(resolve => { resume = resolve; channel.port2.postMessage(0); });
      }
      return new Promise(resolve => setTimeout(resolve, 0));
    },
    dispose() { channel?.port1.close(); channel?.port2.close(); },
  };
}

// cache: 0 unknown, 1 valid, 2 invalid. Never scan unrelated layout points.
// Check lease/pause/cancellation once per slice; scheduling is owned here.
export async function maskGridIndices(points, bvh, layout, indices, cache, checkpoint) {
  let maskMs = 0, maskMaxMs = 0, maskPoints = 0, maskSlices = 0, maskYields = 0, next = 0;
  const yielder = gridYielder();
  const skipKnown = () => { while (next < indices.length && cache[indices[next]] !== 0) next++; };
  try {
    skipKnown();
    while (next < indices.length) {
      await checkpoint();
      const start = performance.now();
      do {
        const i = indices[next];
        if (cache[i] === 0) {
          cache[i] = insideMask(points, bvh, layout, indices.subarray(next, next + 1))[0] ? 2 : 1;
          maskPoints++;
        }
        next++;
      } while (next < indices.length && performance.now() - start < GRID_MASK_SLICE_MS);
      const ms = performance.now() - start;
      maskMs += ms; maskMaxMs = Math.max(maskMaxMs, ms); maskSlices++;
      skipKnown();
      if (next < indices.length) { await yielder.yield(); maskYields++; }
    }
  } finally {
    yielder.dispose();
  }
  return {maskMs, maskMaxMs, maskPoints, maskSlices, maskYields};
}
