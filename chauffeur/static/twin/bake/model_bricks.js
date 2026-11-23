// Per-copy visibility bricks, emitter selection/folding, and GPU light textures
// (mvBricks 3D texture + mvLamps float data texture) for placed-model lighting.
import * as THREE from '../../vendor/three-r187/three.module.js';
import { FT, CANDELA } from '../twin_light_math.js';
import { inPolygon } from '../twin_ground.js';
import { fixturePoint, fixtureRotation, linePieces } from '../live/fixture_geometry.js';
import { coneWindow } from './fixture_terms.js';
import { lightSource } from './reach.js';
import { tintSum } from './lightmap_material.js';
import { GRID_INVALID } from './grid_layout.js';

export const BRICK_SIZE = 5;
export const BRICK_MAX_EMITTERS = 8;
export const BRICK_TEX_WIDTH = BRICK_SIZE * 2; // 10 RGBA texels: two 5-wide slabs (x = 0..4 for emitters 0..3, x = 5..9 for emitters 4..7)
export const BRICK_TEX_HEIGHT = BRICK_SIZE;    // 5
export const BRICK_BYTES = BRICK_SIZE * BRICK_SIZE * BRICK_SIZE * BRICK_MAX_EMITTERS; // 1000
export const EMITTER_PACK_STRIDE = 4096;       // 12-bit packed (index + 1) pairs; 0 = unused
export const LAMPS_MAX_WIDTH = 1024;

export const EMITTER_SHAPE = Object.freeze({
  point: 0,
  spot: 1,
  rect: 2,
  area: 2,
  line: 3,
});

// Shared row and slab layout contract between Task 6 (model_bricks.js) and Task 7 (model_material.js).
//
// mvBricks (Data3DTexture, RGBA8, LinearFilter, ClampToEdge; 10 x 5 x 5*maxBricks):
//   Two 5-wide slabs along X: emitter e (0..7) at brick point (ix, iy, iz) sits at
//   texel ((e >> 2) * 5 + ix, iy, brickIndex * 5 + iz), channel (e & 3).
//   The shader samples group g (0 or 1) at:
//     u = clamp(g * 5.0 + 0.5 + localU * 4.0, g * 5.0 + 0.5, g * 5.0 + 4.5) / 10.0
//     v = clamp(0.5 + localV * 4.0, 0.5, 4.5) / 5.0
//     w = (zOffset + clamp(0.5 + localW * 4.0, 0.5, 4.5)) / (5.0 * maxBricks)
//   so hardware LinearFilter provides true trilinear filtering without blending across
//   emitter groups or adjacent bricks.
//
// mvLamps (DataTexture, RGBA32F, NearestFilter):
//   mvSize = vec4(maxEmitters, maxBricks, lampsTextureWidth, firstBrickRow).
//   Emitter row j at (j % W, floor(j / W) * EMITTER_ROWS + row).
//     Each emitterTable record carries `row` (its mvLamps emitter table index, distinct
//     from `index`/`column` within its light). chooseEmitters returns `rows` alongside
//     `ids` and `scales`; writeBrick takes `rows` (or the chooseEmitters result).
//   Brick i at (i % W, firstBrickRow + floor(i / W) * BRICK_ROWS + row).
//     Valid brick slots are compacted contiguously into 0..count-1 (matching scales and
//     brick channels) so BRICK_ROW_META.x == count guarantees slots 0..count-1 are all
//     valid when the shader loops `for (int k = 0; k < count; k++)`.
export const MODEL_LIGHT_LAYOUT = Object.freeze({
  BRICK_SIZE,
  MAX_EMITTERS_PER_BRICK: BRICK_MAX_EMITTERS,
  BRICK_TEX_WIDTH,
  BRICK_TEX_HEIGHT,
  BRICK_SLAB_WIDTH: BRICK_SIZE, // group g occupies x in [g*5+0.5, g*5+4.5] / 10.0
  BRICK_BYTES,
  EMITTER_PACK_STRIDE,
  EMITTER_ROWS: 4,
  EMITTER_ROW_POS_RANGE: 0,    // (pos.x, pos.y, pos.z, range)
  EMITTER_ROW_AXIS_OR_QUAT: 1, // point/spot: (axis.x, axis.y, axis.z, cosOuter); rect/line: (qx, qy, qz, qw)
  EMITTER_ROW_SHAPE_SIZE: 2,   // (cosInner, shape, halfW, halfH)
  EMITTER_ROW_COLOR_SCALE: 3,  // (tint.r * outputScale, tint.g * outputScale, tint.b * outputScale, outputScale)
  BRICK_ROWS: 7,
  BRICK_ROW_EMITTERS: 0,       // 4 floats packing 8 (emitterIndex + 1) pairs with EMITTER_PACK_STRIDE
  BRICK_ROW_META: 1,           // (count, zOffset, 0, 0)
  BRICK_ROW_FILL: 2,           // (fill.r, fill.g, fill.b, 0)
  BRICK_ROW_BOX_MIN: 3,        // (box.min.x, box.min.y, box.min.z, 0)
  BRICK_ROW_BOX_INV: 4,        // (invSpan.x, invSpan.y, invSpan.z, 0); 0 samples brick centre 0.5
  BRICK_ROW_SCALES_0: 5,       // per-slot folding output scale for slots 0..3 (1 when not folded)
  BRICK_ROW_SCALES_1: 6,       // per-slot folding output scale for slots 4..7 (1 when not folded)
});

const DEFAULT_OUTPUT_LM = CANDELA * 4 * Math.PI;
const ZERO_AXIS = new THREE.Vector3(0, -1, 0);
const UNIT_QUAT = new THREE.Quaternion();
const chunkLookupCache = new WeakMap();

function toVec3(v) {
  if (v?.isVector3) return v.clone();
  if (Array.isArray(v)) return new THREE.Vector3(v[0], v[1], v[2]);
  if (v && typeof v === 'object') return new THREE.Vector3(v.x || 0, v.y || 0, v.z || 0);
  return new THREE.Vector3();
}

function buildEmitterRecords(light, e, emitterIndex) {
  const shapeName = e.shape || 'point';
  const shape = Object.hasOwn(EMITTER_SHAPE, shapeName) ? EMITTER_SHAPE[shapeName] : 0;
  const range = (e.range ?? 18) * FT;
  const lumens = (e.output_lm ?? DEFAULT_OUTPUT_LM) * (e.output_fraction ?? 1);
  const halfFire = (light.emitters?.length || 0) > 1 && e.fire_pit ? 0.5 : 1;

  if (shape === 0) {
    const position = e.position ? toVec3(e.position) : fixturePoint(e.at || light.at || [0, 0, 0]);
    return [{
      id: `${light.device}#${emitterIndex}`,
      device: light.device,
      index: emitterIndex,
      column: emitterIndex,
      shape: 0,
      position,
      range,
      axis: ZERO_AXIS.clone(),
      cosOuter: -1,
      cosInner: -1,
      halfSize: [0, 0],
      rotation: UNIT_QUAT.clone(),
      outputScale: (lumens * halfFire) / (4 * Math.PI),
    }];
  }

  if (shape === 1) {
    const position = e.position ? toVec3(e.position) : fixturePoint(e.at || light.at || [0, 0, 0]);
    const coneRad = ((e.cone_deg ?? 60) * Math.PI) / 360;
    const softness = e.softness ?? 0.3;
    const cosOuter = Math.cos(coneRad);
    const cosInner = Math.cos(coneRad * (1 - softness));
    const axis = e.aim ? fixturePoint(e.aim).sub(position) : ZERO_AXIS.clone();
    if (axis.lengthSq() > 1e-10) axis.normalize();
    else axis.copy(ZERO_AXIS);
    const solidAngle = Math.max(1e-6, 2 * Math.PI * (1 - cosOuter));
    return [{
      id: `${light.device}#${emitterIndex}`,
      device: light.device,
      index: emitterIndex,
      column: emitterIndex,
      shape: 1,
      position,
      range,
      axis,
      cosOuter,
      cosInner,
      halfSize: [0, 0],
      rotation: UNIT_QUAT.clone(),
      outputScale: (lumens * halfFire) / solidAngle,
    }];
  }

  if (shape === 2) {
    const position = e.position ? toVec3(e.position) : fixturePoint(e.at || light.at || [0, 0, 0]);
    const rotation = fixtureRotation(e);
    const axis = new THREE.Vector3(0, 0, -1).applyQuaternion(rotation).normalize();
    const w = (e.size_ft?.[0] ?? 1) * FT;
    const h = (e.size_ft?.[1] ?? 1) * FT;
    return [{
      id: `${light.device}#${emitterIndex}`,
      device: light.device,
      index: emitterIndex,
      column: emitterIndex,
      shape: 2,
      position,
      range,
      axis,
      cosOuter: -1,
      cosInner: -1,
      halfSize: [w * 0.5, h * 0.5],
      rotation,
      outputScale: lumens / Math.PI,
    }];
  }

  // shape === 3 (line): one table record per linePieces() segment, sharing chunk column.
  const pieces = e.path?.length >= 2 ? linePieces(e) : [];
  const baseScale = lumens / Math.PI;
  if (!pieces.length) {
    const position = e.position ? toVec3(e.position) : fixturePoint(e.at || light.at || [0, 0, 0]);
    const rotation = fixtureRotation(e);
    const axis = new THREE.Vector3(0, 0, -1).applyQuaternion(rotation).normalize();
    return [{
      id: `${light.device}#${emitterIndex}`,
      device: light.device,
      index: emitterIndex,
      column: emitterIndex,
      shape: 3,
      position,
      range,
      axis,
      cosOuter: -1,
      cosInner: -1,
      halfSize: [0, ((e.width_in ?? 1) / 12) * FT * 0.5],
      rotation,
      outputScale: baseScale,
    }];
  }

  const totalLen = pieces.reduce((sum, p) => sum + p.width, 0);
  return pieces.map((p, pieceIndex) => {
    const share = totalLen > 0 ? p.width / totalLen : 1 / pieces.length;
    const rotation = p.rotation.clone();
    const axis = new THREE.Vector3(0, 0, -1).applyQuaternion(rotation).normalize();
    return {
      id: pieces.length === 1 ? `${light.device}#${emitterIndex}` : `${light.device}#${emitterIndex}:${pieceIndex}`,
      device: light.device,
      index: emitterIndex,
      pieceIndex,
      column: emitterIndex,
      shape: 3,
      position: p.position.clone(),
      range,
      axis,
      cosOuter: -1,
      cosInner: -1,
      halfSize: [p.width * 0.5, p.height * 0.5],
      rotation,
      outputScale: baseScale * share,
    };
  });
}

function legacyRecord(light, plan) {
  const { source, range } = lightSource(plan || {}, light);
  return {
    id: `${light.device}#0`,
    device: light.device,
    index: 0,
    column: 0,
    shape: 0,
    position: source,
    range,
    axis: ZERO_AXIS.clone(),
    cosOuter: -1,
    cosInner: -1,
    halfSize: [0, 0],
    rotation: UNIT_QUAT.clone(),
    outputScale: CANDELA,
  };
}

// Build the flat emitter table for fresh baked lights that have a grid chunk
// and are not in the caller-supplied paletteLines set.
export function emitterTable(lights, freshIds, manifest = null, { paletteLines = null, plan = null } = {}) {
  const list = lights || [];
  const freshSet = freshIds instanceof Set ? freshIds : new Set(freshIds || []);
  const excludedPalette = paletteLines instanceof Set ? paletteLines : new Set(paletteLines || []);

  const records = [];
  for (const l of list) {
    if (!l || !freshSet.has(l.device)) continue;
    const hasGrid = manifest ? Boolean(manifest.lights?.[l.device]?.grid) : Boolean(l.grid);
    if (!hasGrid) continue;
    const entityId = l.entity ?? l.device;
    if (excludedPalette.has(entityId) || excludedPalette.has(l.device)) continue;
    if (l.emitters?.length) {
      for (let i = 0; i < l.emitters.length; i++) {
        records.push(...buildEmitterRecords(l, l.emitters[i], i));
      }
    } else {
      records.push(legacyRecord(l, plan));
    }
  }
  for (let r = 0; r < records.length; r++) records[r].row = r;
  return records;
}

function getChunk(chunks, device) {
  if (!chunks) return null;
  return chunks instanceof Map ? chunks.get(device) || null : chunks[device] || null;
}

function getChunkLookup(chunk) {
  let map = chunkLookupCache.get(chunk);
  if (!map) {
    map = new Map();
    const idx = chunk.indices;
    for (let i = 0; i < idx.length; i++) map.set(idx[i], i);
    chunkLookupCache.set(chunk, map);
  }
  return map;
}

function parseEmitterId(emitterId) {
  const sep = emitterId.lastIndexOf('#');
  if (sep < 0) return { device: emitterId, column: 0 };
  const suffix = emitterId.slice(sep + 1);
  const colon = suffix.indexOf(':');
  const colStr = colon >= 0 ? suffix.slice(0, colon) : suffix;
  return { device: emitterId.slice(0, sep), column: Number(colStr) };
}

function bilinearGround(block, gx, gy) {
  const [nx, ny] = block.dims;
  const cx = Math.max(0, Math.min(nx - 1, gx));
  const cy = Math.max(0, Math.min(ny - 1, gy));
  const x0 = Math.floor(cx), x1 = Math.min(nx - 1, x0 + 1), fx = cx - x0;
  const y0 = Math.floor(cy), y1 = Math.min(ny - 1, y0 + 1), fy = cy - y0;
  const g = block.ground;
  const g00 = g[y0 * nx + x0], g10 = g[y0 * nx + x1];
  const g01 = g[y1 * nx + x0], g11 = g[y1 * nx + x1];
  return (g00 * (1 - fx) + g10 * fx) * (1 - fy) + (g01 * (1 - fx) + g11 * fx) * fy;
}

const sampleTmp = new THREE.Vector3();

function findContainingBlock(layout, p) {
  if (!layout?.blocks?.length) return null;
  let fallbackRoom = null;
  let fallbackYard = null;

  // Priority: (1) exact room polygon match, (2) exact yard polygon match,
  // (3) room AABB fallback, (4) yard AABB fallback.
  // Room z uses half-open [-1e-6, nz - 1e-6) so stacked levels never both claim
  // the shared plane even under float rounding of (nz * FT) * (1 / FT).
  for (const b of layout.blocks) {
    if (b.kind !== 'room') continue;
    sampleTmp.copy(p).applyMatrix4(b.toLocal);
    const [nx, ny, nz] = b.dims;
    if (sampleTmp.x < 0 || sampleTmp.x > nx || sampleTmp.y < 0 || sampleTmp.y > ny ||
        sampleTmp.z < -1e-6 || sampleTmp.z >= nz - 1e-6) continue;
    const hit = { block: b, lx: sampleTmp.x, ly: sampleTmp.y, lz: sampleTmp.z };
    if (!b.poly?.length || !b.origin) return hit;
    const spFt = b.spacing / FT;
    if (inPolygon(b.poly, b.origin[0] + sampleTmp.x * spFt, b.origin[1] + sampleTmp.y * spFt)) return hit;
    if (!fallbackRoom) fallbackRoom = hit;
  }

  for (const b of layout.blocks) {
    if (b.kind !== 'yard') continue;
    sampleTmp.copy(p).applyMatrix4(b.toLocal);
    const [nx, ny, nz] = b.dims;
    if (sampleTmp.x < 0 || sampleTmp.x > nx || sampleTmp.y < 0 || sampleTmp.y > ny) continue;
    const gM = bilinearGround(b, sampleTmp.x - 0.5, sampleTmp.y - 0.5);
    const lz = sampleTmp.z - gM / b.spacing;
    if (lz < 0 || lz > nz) continue;
    const hit = { block: b, lx: sampleTmp.x, ly: sampleTmp.y, lz };
    if (!b.poly?.length || !b.origin) return hit;
    const spFt = b.spacing / FT;
    if (inPolygon(b.poly, b.origin[0] + sampleTmp.x * spFt, b.origin[1] + sampleTmp.y * spFt)) return hit;
    if (!fallbackYard) fallbackYard = hit;
  }
  return fallbackRoom || fallbackYard;
}

const cornerIndices = new Int32Array(8);
const cornerWeights = new Float64Array(8);

function computeStencil(located) {
  const { block, lx, ly, lz } = located;
  const [nx, ny, nz] = block.dims;
  const cx = Math.max(0, Math.min(nx - 1, lx - 0.5));
  const cy = Math.max(0, Math.min(ny - 1, ly - 0.5));
  const cz = Math.max(0, Math.min(nz - 1, lz - 0.5));

  const x0 = Math.floor(cx), x1 = Math.min(nx - 1, x0 + 1), tx = cx - x0;
  const y0 = Math.floor(cy), y1 = Math.min(ny - 1, y0 + 1), ty = cy - y0;
  const z0 = Math.floor(cz), z1 = Math.min(nz - 1, z0 + 1), tz = cz - z0;

  let n = 0;
  for (let dz = 0; dz < 2; dz++) {
    const wz = dz ? tz : 1 - tz;
    if (wz === 0) continue;
    const iz = dz ? z1 : z0;
    for (let dy = 0; dy < 2; dy++) {
      const wy = wz * (dy ? ty : 1 - ty);
      if (wy === 0) continue;
      const iy = dy ? y1 : y0;
      const rowBase = block.first + (iz * ny + iy) * nx;
      for (let dx = 0; dx < 2; dx++) {
        const w = wy * (dx ? tx : 1 - tx);
        if (w === 0) continue;
        cornerIndices[n] = rowBase + (dx ? x1 : x0);
        cornerWeights[n] = w;
        n++;
      }
    }
  }
  return n;
}

function sampleFromStencil(stencilCount, chunk, lookup, column) {
  const vals = chunk.values;
  const stride = chunk.emitters;
  let wSum = 0;
  let vSum = 0;
  for (let k = 0; k < stencilCount; k++) {
    const w = cornerWeights[k];
    const pos = lookup.get(cornerIndices[k]);
    if (pos === undefined) {
      wSum += w;
      continue;
    }
    const byte = vals[pos * stride + column];
    if (byte === GRID_INVALID) continue;
    vSum += w * (byte / 254);
    wSum += w;
  }
  return wSum > 0 ? vSum / wSum : null;
}

// Trilinear sample of visibility [0, 1] at world point p (Vector3, metres) for emitterId.
// Skips 255 (invalid) corners with renormalised weights; returns null when all 8 are invalid
// or no block contains p (or chunk/emitter is missing).
export function sampleGrid(grid, p, emitterId) {
  if (!grid?.layout || !p || !emitterId) return null;
  const { device, column } = parseEmitterId(emitterId);
  const chunk = getChunk(grid.chunks, device);
  if (!chunk || !Number.isInteger(column) || column < 0 || column >= chunk.emitters) return null;
  const located = findContainingBlock(grid.layout, p);
  if (!located) return null;
  const stencilCount = computeStencil(located);
  return sampleFromStencil(stencilCount, chunk, getChunkLookup(chunk), column);
}

const closestTmp = new THREE.Vector3();
const deltaTmp = new THREE.Vector3();
const uTmp = new THREE.Vector3();
const vTmp = new THREE.Vector3();

function emitterGeomWeight(pt, rec) {
  let d;
  if ((rec.shape === 2 || rec.shape === 3) && rec.rotation && rec.halfSize) {
    const hw = rec.halfSize[0] || 0;
    const hh = rec.shape === 3 ? 0 : (rec.halfSize[1] || 0);
    deltaTmp.copy(pt).sub(rec.position);
    uTmp.set(1, 0, 0).applyQuaternion(rec.rotation);
    const tu = Math.max(-hw, Math.min(hw, deltaTmp.dot(uTmp)));
    closestTmp.copy(rec.position).addScaledVector(uTmp, tu);
    if (hh > 0) {
      vTmp.set(0, 1, 0).applyQuaternion(rec.rotation);
      const tv = Math.max(-hh, Math.min(hh, deltaTmp.dot(vTmp)));
      closestTmp.addScaledVector(vTmp, tv);
    }
    deltaTmp.copy(pt).sub(closestTmp);
    d = deltaTmp.length();
  } else {
    deltaTmp.copy(pt).sub(rec.position);
    d = deltaTmp.length();
  }

  const falloff = emitterFalloff(d, rec.range);
  if (!(falloff > 0)) return 0;

  if (rec.shape === 1) {
    // Spot cone window: dot(-dirToEmitter, axis) = dot(dirFromEmitter, axis).
    const inv = 1 / Math.max(d, 1e-6);
    const cosAngle = (deltaTmp.x * rec.axis.x + deltaTmp.y * rec.axis.y + deltaTmp.z * rec.axis.z) * inv;
    return falloff * coneWindow(cosAngle, rec.cosOuter, rec.cosInner);
  }
  if (rec.shape === 2 || rec.shape === 3) {
    // Rect/line facing: max(0, dot(normal, toCopy)).
    const inv = 1 / Math.max(d, 1e-6);
    const facing = Math.max(0, (deltaTmp.x * rec.axis.x + deltaTmp.y * rec.axis.y + deltaTmp.z * rec.axis.z) * inv);
    return falloff * facing;
  }
  return falloff;
}

export function emitterFalloff(d, range) {
  if (!(range > 0) || d >= range) return 0;
  const r = d / range;
  const cutoff = Math.pow(Math.max(0, 1 - r * r * r * r), 2);
  return cutoff / Math.max(d * d, 0.01);
}

function boxCorners(box) {
  const { min, max } = box;
  return [
    new THREE.Vector3(min.x, min.y, min.z),
    new THREE.Vector3(max.x, min.y, min.z),
    new THREE.Vector3(min.x, max.y, min.z),
    new THREE.Vector3(max.x, max.y, min.z),
    new THREE.Vector3(min.x, min.y, max.z),
    new THREE.Vector3(max.x, min.y, max.z),
    new THREE.Vector3(min.x, max.y, max.z),
    new THREE.Vector3(max.x, max.y, max.z),
  ];
}

// Rank emitters by outputScale * best(falloff * cone/facing) * visibility.
// Accepts either (box: Box3, table, grid, max) or (centre: Vector3, table, grid, max, box?).
// Cones and facing are evaluated at the best of centre and the 8 box corners (when box is provided).
// When centre visibility is null, falls back to the max non-null visibility over the 8 box corners.
// Over max: folds weakest non-strongest siblings of multi-emitter devices into their device's
// strongest emitter (conserving outputScale and returning per-slot folding `scales`), then drops excess.
export function chooseEmitters(centreOrBox, table, grid, maxOrOpts = BRICK_MAX_EMITTERS, boxArg = null) {
  let centre, box;
  if (centreOrBox?.isBox3) {
    box = centreOrBox;
    centre = box.getCenter(new THREE.Vector3());
  } else {
    centre = toVec3(centreOrBox);
    box = boxArg || (maxOrOpts && typeof maxOrOpts === 'object' ? maxOrOpts.box : null) || null;
  }
  const cap = Math.max(0, (maxOrOpts && typeof maxOrOpts === 'object' ? (maxOrOpts.max ?? BRICK_MAX_EMITTERS) : maxOrOpts) | 0);
  if (!cap || !table?.length) return { ids: [], rows: [], folded: 0, dropped: 0, emitters: [], scales: [] };

  const corners = box ? boxCorners(box) : [];
  const probes = [centre, ...corners];

  // Precompute block stencil once per probe point so sampling many emitters is cheap.
  const probeStencils = probes.map(pt => {
    const located = grid?.layout ? findContainingBlock(grid.layout, pt) : null;
    if (!located) return null;
    const count = computeStencil(located);
    return {
      count,
      indices: cornerIndices.slice(0, count),
      weights: cornerWeights.slice(0, count),
    };
  });

  const sampleProbe = (stencil, chunk, lookup, column) => {
    if (!stencil) return null;
    const vals = chunk.values;
    const stride = chunk.emitters;
    let wSum = 0, vSum = 0;
    for (let k = 0; k < stencil.count; k++) {
      const w = stencil.weights[k];
      const pos = lookup.get(stencil.indices[k]);
      if (pos === undefined) { wSum += w; continue; }
      const byte = vals[pos * stride + column];
      if (byte === GRID_INVALID) continue;
      vSum += w * (byte / 254);
      wSum += w;
    }
    return wSum > 0 ? vSum / wSum : null;
  };

  const candidates = [];
  for (let tableIdx = 0; tableIdx < table.length; tableIdx++) {
    const rec = table[tableIdx];
    let bestGeom = 0;
    for (let k = 0; k < probes.length; k++) {
      const g = emitterGeomWeight(probes[k], rec);
      if (g > bestGeom) bestGeom = g;
    }
    if (!(bestGeom > 0)) continue;

    const column = Number.isInteger(rec.column) ? rec.column : parseEmitterId(rec.id).column;
    const chunk = getChunk(grid?.chunks, rec.device);
    if (!chunk || column < 0 || column >= chunk.emitters) continue;
    const lookup = getChunkLookup(chunk);

    let vis = sampleProbe(probeStencils[0], chunk, lookup, column);
    if (vis === null && corners.length) {
      let maxCorner = null;
      for (let k = 1; k < probeStencils.length; k++) {
        const cv = sampleProbe(probeStencils[k], chunk, lookup, column);
        if (cv !== null && (maxCorner === null || cv > maxCorner)) maxCorner = cv;
      }
      vis = maxCorner ?? 0;
    }
    if (!(vis > 0)) continue;

    const score = rec.outputScale * bestGeom * vis;
    if (!(score > 0)) continue;
    const row = Number.isInteger(rec.row) ? rec.row : tableIdx;
    candidates.push({
      id: rec.id,
      row,
      device: rec.device,
      score,
      baseScale: rec.outputScale,
      record: { ...rec, row },
    });
  }

  const byScoreDesc = (a, b) => b.score - a.score || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  candidates.sort(byScoreDesc);

  let folded = 0;
  if (candidates.length > cap) {
    const groups = new Map();
    for (const c of candidates) {
      let g = groups.get(c.device);
      if (!g) { g = []; groups.set(c.device, g); }
      g.push(c);
    }
    while (candidates.length > cap) {
      let victim = null;
      let victimGroup = null;
      for (const g of groups.values()) {
        if (g.length < 2) continue;
        const weak = g[g.length - 1];
        if (!victim || weak.score < victim.score || (weak.score === victim.score && weak.id > victim.id)) {
          victim = weak;
          victimGroup = g;
        }
      }
      if (!victim) break;
      const strongest = victimGroup[0];
      strongest.record.outputScale += victim.record.outputScale;
      strongest.score += victim.score;
      victimGroup.pop();
      const pos = candidates.indexOf(victim);
      if (pos >= 0) candidates.splice(pos, 1);
      folded++;
    }
    candidates.sort(byScoreDesc);
  }

  let dropped = 0;
  if (candidates.length > cap) {
    dropped = candidates.length - cap;
    candidates.length = cap;
  }

  return {
    ids: candidates.map(c => c.id),
    rows: candidates.map(c => c.row),
    folded,
    dropped,
    emitters: candidates.map(c => c.record),
    scales: candidates.map(c => (c.baseScale > 0 ? c.record.outputScale / c.baseScale : 1)),
  };
}

// Build a 5 x 5 x 5 x 8 visibility brick (Uint8Array of 1000 bytes) over `box: Box3`.
// Two 5-wide slab layout: point (ix, iy, iz) emitter e (0..7) sits at texel
// ((e >> 2) * 5 + ix, iy, iz), channel (e & 3).
// Locates the containing block once per brick point and samples all emitter ids from it.
// Null samples are filled from the nearest valid point in the same brick, else 0.
export function buildBrick(grid, box, ids) {
  const out = new Uint8Array(BRICK_BYTES);
  const count = Math.min(BRICK_MAX_EMITTERS, ids?.length || 0);
  if (!count || !box || !grid?.layout) return out;

  const N = BRICK_SIZE;
  const totalPts = N * N * N;

  // Resolve each emitter's chunk & lookup once.
  const slots = new Array(count);
  for (let e = 0; e < count; e++) {
    const id = ids[e];
    if (!id) { slots[e] = null; continue; }
    const { device, column } = parseEmitterId(id);
    const chunk = getChunk(grid.chunks, device);
    if (!chunk || !Number.isInteger(column) || column < 0 || column >= chunk.emitters) {
      slots[e] = null;
      continue;
    }
    slots[e] = { chunk, lookup: getChunkLookup(chunk), column };
  }

  const samples = new Float32Array(count * totalPts);
  samples.fill(NaN);
  const validLists = Array.from({ length: count }, () => []);

  const minX = box.min.x, minY = box.min.y, minZ = box.min.z;
  const spanX = box.max.x - minX;
  const spanY = box.max.y - minY;
  const spanZ = box.max.z - minZ;
  const p = new THREE.Vector3();

  // Locate the containing block ONCE per brick point, compute its stencil once,
  // and sample all emitter slots from that stencil.
  for (let iz = 0; iz < N; iz++) {
    const wz = minZ + spanZ * (iz / (N - 1));
    for (let iy = 0; iy < N; iy++) {
      const wy = minY + spanY * (iy / (N - 1));
      for (let ix = 0; ix < N; ix++) {
        const wx = minX + spanX * (ix / (N - 1));
        p.set(wx, wy, wz);
        const located = findContainingBlock(grid.layout, p);
        if (!located) continue;
        const stencilCount = computeStencil(located);
        const flat = (iz * N + iy) * N + ix;
        for (let e = 0; e < count; e++) {
          const s = slots[e];
          if (!s) continue;
          const v = sampleFromStencil(stencilCount, s.chunk, s.lookup, s.column);
          if (v !== null) {
            samples[e * totalPts + flat] = v;
            validLists[e].push(flat);
          }
        }
      }
    }
  }

  // Fill null points per emitter from the nearest valid point in the brick, then write slabs.
  for (let e = 0; e < count; e++) {
    const valid = validLists[e];
    if (!valid.length) continue;
    const base = e * totalPts;

    if (valid.length < totalPts) {
      for (let iz = 0; iz < N; iz++) {
        for (let iy = 0; iy < N; iy++) {
          for (let ix = 0; ix < N; ix++) {
            const flat = (iz * N + iy) * N + ix;
            if (!Number.isNaN(samples[base + flat])) continue;
            let bestDist = Infinity;
            let bestVal = 0;
            for (let k = 0; k < valid.length; k++) {
              const q = valid[k];
              const qx = q % N;
              const qy = ((q - qx) / N) % N;
              const qz = Math.floor(q / (N * N));
              const d2 = (qx - ix) * (qx - ix) + (qy - iy) * (qy - iy) + (qz - iz) * (qz - iz);
              if (d2 < bestDist) {
                bestDist = d2;
                bestVal = samples[base + q];
              }
            }
            samples[base + flat] = bestVal;
          }
        }
      }
    }

    // Two 5-wide slabs: x = (e >> 2) * 5 + ix, channel = e & 3.
    const slabX = (e >> 2) * BRICK_SIZE;
    const ch = e & 3;
    for (let iz = 0; iz < N; iz++) {
      for (let iy = 0; iy < N; iy++) {
        for (let ix = 0; ix < N; ix++) {
          const flat = (iz * N + iy) * N + ix;
          const byte = Math.round(Math.min(1, Math.max(0, samples[base + flat])) * 254);
          const texelOffset = ((iz * BRICK_TEX_HEIGHT + iy) * BRICK_TEX_WIDTH + (slabX + ix)) * 4 + ch;
          out[texelOffset] = byte;
        }
      }
    }
  }
  return out;
}

// Compute the room's linear fill sum across fresh lights, matching lightmap_material.js
// directTerm's lmFill (tintSum * fill[atlasRoomIndex]).
// freshIds is required (throws if missing).
export function fillFor(manifest, atlasRoomIndex, tints, freshIds) {
  if (!freshIds || typeof freshIds[Symbol.iterator] !== 'function') {
    throw new Error('fillFor requires freshIds (Set or iterable of fresh device ids).');
  }
  const sum = new THREE.Color(0, 0, 0);
  if (!manifest?.lights || !tints || !Number.isInteger(atlasRoomIndex) || atlasRoomIndex < 0) return sum;
  const freshSet = freshIds instanceof Set ? freshIds : new Set(freshIds);

  const getTintEntry = id => (tints instanceof Map ? tints.get(id) : tints[id]);
  const toLinear = entry => {
    if (!entry) return null;
    if (Array.isArray(entry.rgb)) return tintSum([entry], true);
    if (entry.isColor || typeof entry.r === 'number') return new THREE.Color(entry.r || 0, entry.g || 0, entry.b || 0);
    return null;
  };

  for (const [device, entry] of Object.entries(manifest.lights)) {
    if (!freshSet.has(device)) continue;
    const f = entry?.fill?.[atlasRoomIndex];
    if (!(f > 0)) continue;
    let color = toLinear(getTintEntry(device));
    if (!color && device.startsWith('shared:')) {
      const members = device.slice(7).split('+');
      const acc = new THREE.Color(0, 0, 0);
      let any = false;
      for (const m of members) {
        const mc = toLinear(getTintEntry(m));
        if (mc) { acc.add(mc); any = true; }
      }
      if (any) color = acc;
    }
    if (!color) continue;
    sum.r += color.r * f;
    sum.g += color.g * f;
    sum.b += color.b * f;
  }
  return sum;
}

function packEmitterPair(a, b) {
  const pa = a >= 0 ? a + 1 : 0;
  const pb = b >= 0 ? b + 1 : 0;
  return pa + pb * EMITTER_PACK_STRIDE;
}

// Create the two GPU textures placed-model materials read:
// - bricks: Data3DTexture (RGBA, UnsignedByte, LinearFilter, ClampToEdge; 10 x 5 x 5*maxBricks)
// - lamps:  DataTexture   (RGBA, Float, NearestFilter; emitter rows followed by brick rows)
// - mvSize: Vector4(maxEmitters, maxBricks, lampsTextureWidth, firstBrickRow)
export function createModelLightTextures({ maxBricks = 1, maxEmitters = 1 } = {}) {
  const capBricks = Math.max(1, maxBricks | 0);
  const capEmitters = Math.max(1, maxEmitters | 0);
  if (capEmitters >= EMITTER_PACK_STRIDE) {
    throw new Error(`maxEmitters (${capEmitters}) exceeds packed limit (${EMITTER_PACK_STRIDE - 1}).`);
  }

  const L = MODEL_LIGHT_LAYOUT;
  const bricksData = new Uint8Array(BRICK_BYTES * capBricks);
  const bricks = new THREE.Data3DTexture(bricksData, BRICK_TEX_WIDTH, BRICK_TEX_HEIGHT, BRICK_SIZE * capBricks);
  bricks.format = THREE.RGBAFormat;
  bricks.type = THREE.UnsignedByteType;
  bricks.minFilter = THREE.LinearFilter;
  bricks.magFilter = THREE.LinearFilter;
  bricks.wrapS = THREE.ClampToEdgeWrapping;
  bricks.wrapT = THREE.ClampToEdgeWrapping;
  bricks.wrapR = THREE.ClampToEdgeWrapping;
  bricks.generateMipmaps = false;
  bricks.unpackAlignment = 1;
  bricks.needsUpdate = true;

  const lampsWidth = Math.min(LAMPS_MAX_WIDTH, Math.max(1, capEmitters, capBricks));
  const firstBrickRow = Math.ceil(capEmitters / lampsWidth) * L.EMITTER_ROWS;
  const brickRowCount = Math.ceil(capBricks / lampsWidth) * L.BRICK_ROWS;
  const lampsHeight = firstBrickRow + brickRowCount;
  const lampsData = new Float32Array(lampsWidth * lampsHeight * 4);
  const lamps = new THREE.DataTexture(lampsData, lampsWidth, lampsHeight, THREE.RGBAFormat, THREE.FloatType);
  lamps.minFilter = THREE.NearestFilter;
  lamps.magFilter = THREE.NearestFilter;
  lamps.generateMipmaps = false;
  lamps.flipY = false;
  lamps.needsUpdate = true;

  const mvSize = new THREE.Vector4(capEmitters, capBricks, lampsWidth, firstBrickRow);
  const outputScales = new Float32Array(capEmitters);
  const emitterTints = new Float32Array(capEmitters * 3);

  const emitterRowOffset = (j, row) => {
    const x = j % lampsWidth;
    const y = Math.floor(j / lampsWidth) * L.EMITTER_ROWS + row;
    return (y * lampsWidth + x) * 4;
  };
  const brickRowOffset = (i, row) => {
    const x = i % lampsWidth;
    const y = firstBrickRow + Math.floor(i / lampsWidth) * L.BRICK_ROWS + row;
    return (y * lampsWidth + x) * 4;
  };
  const set4 = (off, a, b, c, d) => {
    lampsData[off] = a;
    lampsData[off + 1] = b;
    lampsData[off + 2] = c;
    lampsData[off + 3] = d;
  };

  function writeEmitter(j, record) {
    if (j < 0 || j >= capEmitters) throw new RangeError(`Emitter index ${j} out of range [0, ${capEmitters}).`);
    const pos = record.position || { x: 0, y: 0, z: 0 };
    const shape = record.shape ?? 0;
    const scale = record.outputScale ?? 0;
    outputScales[j] = scale;

    set4(emitterRowOffset(j, L.EMITTER_ROW_POS_RANGE), pos.x || 0, pos.y || 0, pos.z || 0, record.range || 0);
    if (shape === 2 || shape === 3) {
      const q = record.rotation || UNIT_QUAT;
      set4(emitterRowOffset(j, L.EMITTER_ROW_AXIS_OR_QUAT), q.x, q.y, q.z, q.w);
    } else {
      const ax = record.axis || ZERO_AXIS;
      set4(emitterRowOffset(j, L.EMITTER_ROW_AXIS_OR_QUAT), ax.x || 0, ax.y || 0, ax.z || 0, record.cosOuter ?? -1);
    }
    set4(
      emitterRowOffset(j, L.EMITTER_ROW_SHAPE_SIZE),
      record.cosInner ?? -1,
      shape,
      record.halfSize?.[0] ?? 0,
      record.halfSize?.[1] ?? 0,
    );
    const tOff = j * 3;
    set4(
      emitterRowOffset(j, L.EMITTER_ROW_COLOR_SCALE),
      emitterTints[tOff] * scale,
      emitterTints[tOff + 1] * scale,
      emitterTints[tOff + 2] * scale,
      scale,
    );
    lamps.needsUpdate = true;
  }

  function setTint(j, linearColor) {
    if (j < 0 || j >= capEmitters) throw new RangeError(`Emitter index ${j} out of range [0, ${capEmitters}).`);
    const r = Array.isArray(linearColor) ? (linearColor[0] || 0) : (linearColor?.r || 0);
    const g = Array.isArray(linearColor) ? (linearColor[1] || 0) : (linearColor?.g || 0);
    const b = Array.isArray(linearColor) ? (linearColor[2] || 0) : (linearColor?.b || 0);
    const tOff = j * 3;
    emitterTints[tOff] = r;
    emitterTints[tOff + 1] = g;
    emitterTints[tOff + 2] = b;
    const scale = outputScales[j];
    set4(emitterRowOffset(j, L.EMITTER_ROW_COLOR_SCALE), r * scale, g * scale, b * scale, scale);
    lamps.needsUpdate = true;
  }

  function writeBrickFill(i, fill) {
    if (i < 0 || i >= capBricks) throw new RangeError(`Brick index ${i} out of range [0, ${capBricks}).`);
    set4(brickRowOffset(i, L.BRICK_ROW_FILL), fill?.r || 0, fill?.g || 0, fill?.b || 0, 0);
    lamps.needsUpdate = true;
  }

  // writeBrick(i, data, rowsOrChosen, fill, box, scalesOrChosen):
  // - rowsOrChosen: array of integer mvLamps emitter rows (0..maxEmitters-1, or -1 for unused),
  //   or a chooseEmitters result ({ rows, scales }), or { indices, scales }. Throws on non-integers.
  // - Valid slots (>= 0) are compacted contiguously into slots 0..count-1 (along with their scales
  //   and brick visibility channels) so BRICK_ROW_META.x == count means every slot k < count is valid.
  function writeBrick(i, data, rowsOrChosen, fill = null, box = null, scalesOrChosen = null) {
    if (i < 0 || i >= capBricks) throw new RangeError(`Brick index ${i} out of range [0, ${capBricks}).`);

    let rawRows = rowsOrChosen || [];
    let rawScales = scalesOrChosen;
    if (rawRows && !Array.isArray(rawRows) && !ArrayBuffer.isView(rawRows)) {
      if (Array.isArray(rawRows.rows)) {
        if (rawScales == null) rawScales = rawRows.scales ?? null;
        rawRows = rawRows.rows;
      } else if (Array.isArray(rawRows.indices)) {
        if (rawScales == null) rawScales = rawRows.scales ?? null;
        rawRows = rawRows.indices;
      }
    }
    const scaleList = Array.isArray(rawScales) || ArrayBuffer.isView(rawScales)
      ? rawScales
      : rawScales?.scales ?? null;

    const slots = new Int32Array(BRICK_MAX_EMITTERS).fill(-1);
    const slotScales = new Float32Array(BRICK_MAX_EMITTERS).fill(1);
    const srcSlotOf = new Int32Array(BRICK_MAX_EMITTERS).fill(-1);
    const n = Math.min(BRICK_MAX_EMITTERS, rawRows.length);
    let validCount = 0;
    let shifted = false;
    for (let k = 0; k < n; k++) {
      const idx = rawRows[k];
      if (!Number.isInteger(idx)) {
        throw new TypeError(`Brick emitter row at slot ${k} must be an integer, got ${idx}.`);
      }
      if (idx < -1 || idx >= capEmitters) {
        throw new RangeError(`Brick emitter row ${idx} at slot ${k} out of range [-1, ${capEmitters}).`);
      }
      if (idx >= 0) {
        if (validCount !== k) shifted = true;
        slots[validCount] = idx;
        srcSlotOf[validCount] = k;
        if (scaleList && k < scaleList.length && Number.isFinite(scaleList[k])) {
          slotScales[validCount] = scaleList[k];
        }
        validCount++;
      }
    }

    if (data) {
      if (data.length !== BRICK_BYTES) {
        throw new Error(`Brick data length (${data.length}) must be ${BRICK_BYTES}.`);
      }
      const dstBase = i * BRICK_BYTES;
      if (!shifted) {
        bricksData.set(data, dstBase);
      } else {
        bricksData.fill(0, dstBase, dstBase + BRICK_BYTES);
        for (let dst = 0; dst < validCount; dst++) {
          const src = srcSlotOf[dst];
          const srcSlab = (src >> 2) * BRICK_SIZE, srcCh = src & 3;
          const dstSlab = (dst >> 2) * BRICK_SIZE, dstCh = dst & 3;
          for (let iz = 0; iz < BRICK_SIZE; iz++) {
            for (let iy = 0; iy < BRICK_SIZE; iy++) {
              const row = (iz * BRICK_TEX_HEIGHT + iy) * BRICK_TEX_WIDTH;
              for (let ix = 0; ix < BRICK_SIZE; ix++) {
                const srcOff = (row + srcSlab + ix) * 4 + srcCh;
                const dstOff = dstBase + (row + dstSlab + ix) * 4 + dstCh;
                bricksData[dstOff] = data[srcOff];
              }
            }
          }
        }
      }
      bricks.needsUpdate = true;
    }

    set4(
      brickRowOffset(i, L.BRICK_ROW_EMITTERS),
      packEmitterPair(slots[0], slots[1]),
      packEmitterPair(slots[2], slots[3]),
      packEmitterPair(slots[4], slots[5]),
      packEmitterPair(slots[6], slots[7]),
    );
    set4(brickRowOffset(i, L.BRICK_ROW_META), validCount, i * BRICK_SIZE, 0, 0);
    set4(brickRowOffset(i, L.BRICK_ROW_FILL), fill?.r || 0, fill?.g || 0, fill?.b || 0, 0);
    if (box) {
      const sx = box.max.x - box.min.x;
      const sy = box.max.y - box.min.y;
      const sz = box.max.z - box.min.z;
      set4(brickRowOffset(i, L.BRICK_ROW_BOX_MIN), box.min.x, box.min.y, box.min.z, 0);
      set4(brickRowOffset(i, L.BRICK_ROW_BOX_INV), sx > 1e-6 ? 1 / sx : 0, sy > 1e-6 ? 1 / sy : 0, sz > 1e-6 ? 1 / sz : 0, 0);
    } else {
      set4(brickRowOffset(i, L.BRICK_ROW_BOX_MIN), 0, 0, 0, 0);
      set4(brickRowOffset(i, L.BRICK_ROW_BOX_INV), 0, 0, 0, 0);
    }
    set4(brickRowOffset(i, L.BRICK_ROW_SCALES_0), slotScales[0], slotScales[1], slotScales[2], slotScales[3]);
    set4(brickRowOffset(i, L.BRICK_ROW_SCALES_1), slotScales[4], slotScales[5], slotScales[6], slotScales[7]);
    lamps.needsUpdate = true;
  }

  function grow(newMaxBricks, newMaxEmitters = capEmitters) {
    const nextBricks = Math.max(capBricks, newMaxBricks | 0);
    const nextEmitters = Math.max(capEmitters, newMaxEmitters | 0);
    const next = createModelLightTextures({ maxBricks: nextBricks, maxEmitters: nextEmitters });
    next.bricks.image.data.set(bricksData, 0);
    next.bricks.needsUpdate = true;

    const nextLampsData = next.lamps.image.data;
    const nextW = next.mvSize.z;
    const nextFirstBrick = next.mvSize.w;

    for (let j = 0; j < capEmitters; j++) {
      for (let r = 0; r < L.EMITTER_ROWS; r++) {
        const src = emitterRowOffset(j, r);
        const dst = ((Math.floor(j / nextW) * L.EMITTER_ROWS + r) * nextW + (j % nextW)) * 4;
        nextLampsData[dst] = lampsData[src];
        nextLampsData[dst + 1] = lampsData[src + 1];
        nextLampsData[dst + 2] = lampsData[src + 2];
        nextLampsData[dst + 3] = lampsData[src + 3];
      }
      next._copyEmitterState(j, outputScales[j], emitterTints[j * 3], emitterTints[j * 3 + 1], emitterTints[j * 3 + 2]);
    }

    for (let i = 0; i < capBricks; i++) {
      for (let r = 0; r < L.BRICK_ROWS; r++) {
        const src = brickRowOffset(i, r);
        const dst = ((nextFirstBrick + Math.floor(i / nextW) * L.BRICK_ROWS + r) * nextW + (i % nextW)) * 4;
        nextLampsData[dst] = lampsData[src];
        nextLampsData[dst + 1] = lampsData[src + 1];
        nextLampsData[dst + 2] = lampsData[src + 2];
        nextLampsData[dst + 3] = lampsData[src + 3];
      }
    }
    next.lamps.needsUpdate = true;
    return next;
  }

  function _copyEmitterState(j, scale, tr, tg, tb) {
    outputScales[j] = scale;
    emitterTints[j * 3] = tr;
    emitterTints[j * 3 + 1] = tg;
    emitterTints[j * 3 + 2] = tb;
  }

  function dispose() {
    bricks.dispose();
    lamps.dispose();
  }

  return {
    bricks,
    lamps,
    mvSize,
    maxBricks: capBricks,
    maxEmitters: capEmitters,
    writeBrick,
    writeBrickFill,
    writeEmitter,
    setTint,
    grow,
    dispose,
    _copyEmitterState,
  };
}
