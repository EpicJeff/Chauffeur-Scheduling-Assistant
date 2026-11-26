// Shared contract for Library Models mode (spec 2026-11-23-library-models-mode-design.md).
// Pure functions only: part keys, override resolution, the size/turn fix, part UVs
// and the bake's occluder inputs. services/twin_model_parts.py mirrors the
// validation half; keep the two in step.

export const DEFAULT_LOD_PERCENT = Object.freeze([100, 25, 5]);
export const FEET_PER_METRE = 3.28084;
const TURNS = [0, 90, 180, 270];

// A part is everything using one original material. Keys are the material's
// name; repeats and unnamed materials are numbered by first appearance.
export function partKeys(names) {
  const seen = new Map();
  return names.map(raw => {
    const name = typeof raw === 'string' && raw.trim() ? raw : 'unnamed';
    const n = (seen.get(name) || 0) + 1;
    seen.set(name, n);
    return n === 1 ? name : `${name}~${n}`;
  });
}

// Copy entry, then model entry, then the original material.
export function resolvePart(part, modelMaterials = {}, copyMaterials = {}) {
  const copy = copyMaterials?.[part.key], model = modelMaterials?.[part.key];
  const entry = copy || model;
  if (!entry) return { source: 'original', material: null, texture: 'real', tiles: 1 };
  const source = copy ? 'copy' : 'model';
  if (entry.material === 'original') return { source, material: null, texture: 'real', tiles: 1 };
  const texture = part.has_uv && entry.texture === 'model' ? 'model' : 'real';
  const tiles = texture === 'model' && entry.tiles > 0 ? entry.tiles : 1;
  return { source, material: entry.material, texture, tiles };
}

export function fixScale(fix, sizeM) {
  if (fix?.height_m > 0 && sizeM?.[1] > 0) return fix.height_m / sizeM[1];
  if (fix?.width_m > 0 && sizeM?.[0] > 0) return fix.width_m / sizeM[0];
  return 1;
}

export function fixTurnRadians(fix) {
  return TURNS.includes(fix?.turn) ? fix.turn * Math.PI / 180 : 0;
}

// The author's unwrap with `tiles` repeats per 0..1 square under the shared
// texture.repeat = 1/tile_ft.
export function modelUv(uv, tiles, tileFt) {
  const out = new Float32Array(uv.length), su = tiles * (tileFt?.[0] || 4), sv = tiles * (tileFt?.[1] || 4);
  for (let i = 0; i < uv.length; i += 2) { out[i] = uv[i] * su; out[i + 1] = uv[i + 1] * sv; }
  return out;
}

// Real-size UVs in feet, projected on each vertex's dominant normal axis:
// side faces run u horizontally and v up (the wall convention), tops use x/z.
export function boxUvFeet(position, normal, scale = 1) {
  const count = position.length / 3, out = new Float32Array(count * 2), k = scale * FEET_PER_METRE;
  for (let i = 0; i < count; i++) {
    const x = position[i * 3] * k, y = position[i * 3 + 1] * k, z = position[i * 3 + 2] * k;
    const ax = Math.abs(normal[i * 3]), ay = Math.abs(normal[i * 3 + 1]), az = Math.abs(normal[i * 3 + 2]);
    let u, v;
    if (ay >= ax && ay >= az) { u = x; v = z; }
    else if (ax >= az) { u = z; v = y; }
    else { u = x; v = y; }
    out[i * 2] = u; out[i * 2 + 1] = v;
  }
  return out;
}

// Library-record form of the occluder walk's opaque test
// (bake/model_occluder_meshes.js): blend and cutout records, and glass or
// fixture roles, cast no baked shadow.
export function materialCastsShadow(record) {
  if (!record) return true;
  if (['glass', 'fixture'].includes(record.id) || ['glass', 'fixture'].includes(record.role)) return false;
  return (record.params?.alpha_mode || 'opaque') === 'opaque';
}

// What a model record adds to a lamp's occluder hash. Members appear only when
// they differ from a legacy record, so untouched models keep today's keys.
export function occluderInputs(record, copyMaterials = {}, materialsById = {}) {
  if (!record) return '';
  const out = {};
  const fix = record.fix || {};
  if (TURNS.includes(fix.turn) && fix.turn) out.turn = fix.turn;
  if (fix.height_m > 0) out.height_m = Math.round(fix.height_m * 1e4) / 1e4;
  if (fix.width_m > 0) out.width_m = Math.round(fix.width_m * 1e4) / 1e4;
  const percent = record.lod_percent?.[1] ?? DEFAULT_LOD_PERCENT[1];
  const revision = (record.lods || []).find(l => l.name === 'lod1.glb')?.revision ?? null;
  if (percent !== DEFAULT_LOD_PERCENT[1] || revision > 1) out.mid = [percent, revision];
  const parts = record.parts || [];
  let differs = false;
  const shadow = parts.map(part => {
    const resolved = resolvePart(part, record.materials, copyMaterials);
    const casts = resolved.material == null ? part.opaque !== false : materialCastsShadow(materialsById[resolved.material]);
    if (casts !== (part.opaque !== false)) differs = true;
    return casts ? '1' : '0';
  }).join('');
  if (differs) out.shadow = shadow;
  return Object.keys(out).length ? JSON.stringify(out) : '';
}
