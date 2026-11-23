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

const RAY_DIRS = [
  [1, 0, 0], [-1, 0, 0],
  [0, 1, 0], [0, -1, 0],
  [0, 0, 1], [0, 0, -1],
];
const RAY_EPS = 1e-4;
const RAY_MAX = 1e4;
const RAY_MAX_HITS = 256;

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

function mergeRects(rects) {
  if (rects.length <= 1) return rects;
  const list = rects
    .map(r => [r[0], r[1], r[2], r[3]])
    .sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || a[3] - b[3]);
  let changed = true;
  while (changed) {
    changed = false;
    outer: for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const a = list[i], b = list[j];
        // Merge overlapping or adjacent (touching) cell rectangles so trilinear
        // interpolation across neighbouring yard lamps stays inside one block.
        if (a[0] <= b[2] + 1 && b[0] <= a[2] + 1 && a[1] <= b[3] + 1 && b[1] <= a[3] + 1) {
          a[0] = Math.min(a[0], b[0]);
          a[1] = Math.min(a[1], b[1]);
          a[2] = Math.max(a[2], b[2]);
          a[3] = Math.max(a[3], b[3]);
          list.splice(j, 1);
          changed = true;
          break outer;
        }
      }
    }
  }
  return list.sort((a, b) => a[1] - b[1] || a[0] - b[0] || a[3] - b[3] || a[2] - b[2]);
}

// Pure function of plan rooms, levels, lot/terraces, and lamp ranges.
// lamps: [{ source: { x, y, z }, range, outdoor: boolean }]
export function gridLayout(plan, lamps = []) {
  const validLamps = (lamps || []).filter(l => l && l.source && Number.isFinite(l.range) && l.range > 0);
  const blocks = [];
  let count = 0;
  const tmp = new THREE.Vector3();

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

      let reached = false;
      for (const lamp of validLamps) {
        tmp.set(lamp.source.x, lamp.source.y, lamp.source.z).applyMatrix4(toLocal);
        if (boxDistSq(tmp, maxX, maxY, maxZ, INDOOR_SPACING) < lamp.range * lamp.range) {
          reached = true;
          break;
        }
      }
      if (!reached) continue;

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

  // 2. Yard blocks (lot cells within an outdoor lamp's range)
  const lot = plan?.site?.lot;
  const outdoorLamps = validLamps.filter(l => l.outdoor);
  if (lot?.length >= 3 && outdoorLamps.length) {
    let lotX0 = Infinity, lotY0 = Infinity, lotX1 = -Infinity, lotY1 = -Infinity;
    for (const p of lot) {
      if (p[0] < lotX0) lotX0 = p[0];
      if (p[0] > lotX1) lotX1 = p[0];
      if (p[1] < lotY0) lotY0 = p[1];
      if (p[1] > lotY1) lotY1 = p[1];
    }
    const lotNx = Math.max(1, Math.ceil((lotX1 - lotX0) / YARD_SPACING_FT - 1e-6));
    const lotNy = Math.max(1, Math.ceil((lotY1 - lotY0) / YARD_SPACING_FT - 1e-6));

    const lampRects = [];
    for (const lamp of outdoorLamps) {
      const lx = lamp.source.x / FT;
      const ly = -lamp.source.z / FT;
      const lz = lamp.source.y / FT;
      const rFt = lamp.range / FT;
      const r2 = rFt * rFt;
      const gx0 = Math.max(0, Math.floor((lx - rFt - lotX0) / YARD_SPACING_FT));
      const gx1 = Math.min(lotNx - 1, Math.floor((lx + rFt - lotX0) / YARD_SPACING_FT));
      const gy0 = Math.max(0, Math.floor((ly - rFt - lotY0) / YARD_SPACING_FT));
      const gy1 = Math.min(lotNy - 1, Math.floor((ly + rFt - lotY0) / YARD_SPACING_FT));
      if (gx0 > gx1 || gy0 > gy1) continue;

      let minGx = Infinity, minGy = Infinity, maxGx = -Infinity, maxGy = -Infinity;
      for (let gy = gy0; gy <= gy1; gy++) {
        const cy = lotY0 + (gy + 0.5) * YARD_SPACING_FT;
        const dy = cy - ly;
        const dy2 = dy * dy;
        if (dy2 >= r2) continue;
        for (let gx = gx0; gx <= gx1; gx++) {
          const cx = lotX0 + (gx + 0.5) * YARD_SPACING_FT;
          const dx = cx - lx;
          if (dx * dx + dy2 >= r2) continue;
          if (!inPolygon(lot, cx, cy)) continue;
          const g = groundAt(plan, cx, cy);
          const cz = lz < g ? g : lz > g + YARD_HEIGHT_FT ? g + YARD_HEIGHT_FT : lz;
          const dz = cz - lz;
          if (dx * dx + dy2 + dz * dz >= r2) continue;
          if (gx < minGx) minGx = gx;
          if (gx > maxGx) maxGx = gx;
          if (gy < minGy) minGy = gy;
          if (gy > maxGy) maxGy = gy;
        }
      }
      if (minGx <= maxGx && minGy <= maxGy) lampRects.push([minGx, minGy, maxGx, maxGy]);
    }

    const merged = mergeRects(lampRects);
    merged.forEach(([gx0, gy0, gx1, gy1], idx) => {
      const nx = gx1 - gx0 + 1;
      const ny = gy1 - gy0 + 1;
      const nz = YARD_LAYERS;
      const originX = lotX0 + gx0 * YARD_SPACING_FT;
      const originY = lotY0 + gy0 * YARD_SPACING_FT;
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
        id: `yard:${idx}`,
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
    });
  }

  // 3. Deterministic layout hash (independent of placed models and lamp order)
  const h = fingerprint();
  h.add('grid-layout-1');
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

// Returns Uint8Array of length layout.count (1 = invalid, 0 = valid open air).
// A point is invalid if it lies outside its room/lot polygon (or above a fractional
// room ceiling), or inside a solid occluder by +-x/+-y/+-z ray parity (majority >= 4 of 6).
export function insideMask(points, bvh, layout) {
  const mask = new Uint8Array(layout.count);

  // 1. Polygon / volume validity per block
  for (const b of layout.blocks) {
    const [nx, ny, nz] = b.dims;
    const spFt = b.spacing / FT;
    const ox = b.origin[0], oy = b.origin[1];
    const hasPoly = b.poly?.length >= 3;
    const heightLimit = b.kind === 'room' && Number.isFinite(b.heightFt) ? b.heightFt + 1e-6 : Infinity;

    for (let iy = 0; iy < ny; iy++) {
      const py = oy + (iy + 0.5) * spFt;
      for (let ix = 0; ix < nx; ix++) {
        const px = ox + (ix + 0.5) * spFt;
        const outPoly = hasPoly && !inPolygon(b.poly, px, py);
        if (outPoly) {
          for (let iz = 0; iz < nz; iz++) {
            mask[b.first + (iz * ny + iy) * nx + ix] = 1;
          }
        } else if (heightLimit < Infinity) {
          for (let iz = 0; iz < nz; iz++) {
            if ((iz + 0.5) * spFt > heightLimit) {
              mask[b.first + (iz * ny + iy) * nx + ix] = 1;
            }
          }
        }
      }
    }
  }

  // 2. Ray-parity solid test along +-x, +-y, +-z (majority of 6 -> odd >= 4)
  if (!bvh || !bvh.triCount) return mask;
  for (let i = 0; i < layout.count; i++) {
    if (mask[i]) continue;
    const o = i * 3;
    const ox = points[o], oy = points[o + 1], oz = points[o + 2];
    let odd = 0;
    for (let d = 0; d < 6; d++) {
      const dir = RAY_DIRS[d];
      const dx = dir[0], dy = dir[1], dz = dir[2];
      let hits = 0, tMin = RAY_EPS;
      while (hits < RAY_MAX_HITS) {
        const t = bvh.castRay(ox, oy, oz, dx, dy, dz, tMin, RAY_MAX);
        if (!(t < RAY_MAX)) break;
        hits++;
        tMin = t + RAY_EPS;
      }
      if (hits & 1) {
        odd++;
        if (odd >= 4) { mask[i] = 1; break; }
      } else if (odd + (5 - d) < 4) {
        break;
      }
    }
  }
  return mask;
}
