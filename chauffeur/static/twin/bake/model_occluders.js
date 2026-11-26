// Plan-only placement identity, extended by the shared model-record contract.
import { FT } from '../twin_light_math.js';
import { hostPoint } from '../twin_hosts.js';
import { buildingGround, groundAt } from '../twin_ground.js';
import { fingerprint } from './geometry_key.js';
import { occluderInputs } from '../model_parts.js';
import { bakeHTTPError } from './bake_lock.js';

export const MODEL_REACH_MARGIN_M = 5;

// Optional until the model-record route ships. One snapshot per bake/status read.
export async function modelRecords(api) {
  try {
    const response = await api('api/house/models');
    if (response.status === 401) throw bakeHTTPError('Could not read the model catalog', 401);
    if (response.status === 404) return {};
    if (!response.ok) return null;
    const data = await response.json();
    if (!Array.isArray(data?.models)) return null;
    return Object.fromEntries(data.models
      .filter(r => r && typeof r.id === 'string').map(r => [r.id, r]));
  } catch (error) { if (error.status === 401) throw error; return null; }
}

export const copyInputs = (records = {}, materialsById = {}) => copy =>
  occluderInputs(records[copy.asset], copy.model_materials, materialsById);

export function placedCopies(plan) {
  const copies = [];
  const add = (id, piece, at, yaw = 0) => {
    const axes = piece.scale_axes || [1, 1, 1], scale = piece.scale ?? 1;
    copies.push({ id, asset: piece.asset || piece.kind, at,
      rot: [piece.pitch || 0, (piece.rotation || 0) + yaw, piece.roll || 0],
      scale: [axes[0] * scale * (piece.mirror_x ? -1 : 1), axes[1] * scale,
        axes[2] * scale * (piece.mirror_y ? -1 : 1)],
      castsShadow: piece.casts_shadow !== false,
      ...(piece.model_materials ? {model_materials: piece.model_materials} : {}) });
  };
  for (const b of plan.buildings || []) {
    const yaw = b.rotation || 0, angle = yaw * Math.PI / 180, pos = b.position || [0, 0];
    const cos = Math.cos(angle), sin = Math.sin(angle);
    for (const item of b.items || []) {
      if (!item.asset) continue;
      let point;
      try { point = hostPoint(b, item.host, item.offset || 0); }
      catch { continue; } // The builder also skips models with unavailable hosts.
      const [x, y, z] = point;
      add(`item:${b.id}:${item.id}`, item, [
        (pos[0] + cos * x - sin * y) * FT,
        (z + (item.elevation || 0) + buildingGround(plan, b)) * FT,
        -(pos[1] + sin * x + cos * y) * FT], yaw);
    }
    for (const o of b.openings || []) {
      if (!o.model) continue;
      const wall = (b.walls || []).find(w => w.id === o.wall && w.state !== 'ghost');
      let point, wallYaw;
      try {
        // fitOpening needs loaded bounds. The plan-only equivalent for reach
        // is the opening centre, including its level and shared floor reference.
        const head = o.head ?? ((o.sill || 0) + (o.height || 0));
        const centre = ((o.sill || 0) + head) / 2;
        if (wall) {
          point = hostPoint(b, {...o, head, sill: centre});
          wallYaw = Math.atan2(wall.to[1] - wall.from[1], wall.to[0] - wall.from[0]) * 180 / Math.PI;
        } else {
          // Gable openings use section coordinates and heights above its plate,
          // as in the generator's projection onto the owning wall.
          const section = (b.roof?.sections || []).find(s => s.id === o.section);
          if (!section?.rect || !['front', 'rear'].includes(o.gable)) continue;
          const axis = section.ridge === 'y' ? 1 : 0;
          point = [o.x, o.y, section.plate + centre];
          point[axis] = section.rect[axis + (o.gable === 'rear' ? 2 : 0)];
          wallYaw = axis === 0 ? 90 : 0;
        }
        if (!point.every(Number.isFinite)) continue;
      } catch { continue; }
      const [x, y, z] = point;
      copies.push({id: `opening:${b.id}:${o.id}`, asset: o.model,
        at: [(pos[0] + cos * x - sin * y) * FT,
          (z + buildingGround(plan, b)) * FT, -(pos[1] + sin * x + cos * y) * FT],
        rot: [0, yaw + wallYaw, 0],
        scale: [1, 1, 1], castsShadow: o.casts_shadow !== false,
        ...(o.model_materials ? {model_materials: o.model_materials} : {})});
    }
  }
  const site = plan.site || {};
  for (const [kind, pieces] of [['furniture', site.furniture || []],
    ['planting', (site.planting || []).filter(p => p.asset?.startsWith('import-'))]]) {
    for (const piece of pieces) {
      if (!piece.at || !(piece.asset || piece.kind)) continue;
      const [x, y] = piece.at;
      add(`${kind}:${piece.id}`, piece, [x * FT, (groundAt(plan, x, y) + (piece.elevation || 0)) * FT, -y * FT]);
    }
  }
  return copies;
}

export function occluderHash(copies, source, range, inputs = () => '') {
  const limit = (range + MODEL_REACH_MARGIN_M) ** 2;
  const near = copies.filter(c => (c.at[0] - source.x) ** 2 + (c.at[1] - source.y) ** 2
    + (c.at[2] - source.z) ** 2 <= limit).sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  const round = (value, units) => Math.round(value * units) / units;
  const tuples = near.flatMap(c => {
    const extra = inputs(c) || '';
    // Openings already belong to receiving geometry. Add them here only for
    // the new record inputs; a legacy/merely regenerated model adds no bytes.
    if (c.id.startsWith('opening:') && !extra) return [];
    return [[c.id, c.asset, c.at.map(v => round(v, 1000)), c.rot.map(v => round(v, 10)),
      c.scale.map(v => round(v, 1e4)), c.castsShadow, ...(extra ? [extra] : [])]];
  });
  if (!tuples.length) return '';
  const hash = fingerprint();
  hash.add(JSON.stringify(tuples));
  return hash.key();
}
