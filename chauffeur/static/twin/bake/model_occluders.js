// Plan-only placement identity: no loaded meshes, import metadata or tier/LOD.
import { FT } from '../twin_light_math.js';
import { hostPoint } from '../twin_hosts.js';
import { buildingGround, groundAt } from '../twin_ground.js';
import { fingerprint } from './geometry_key.js';

export const MODEL_REACH_MARGIN_M = 5;

export function placedCopies(plan) {
  const copies = [];
  const add = (id, piece, at, yaw = 0) => {
    const axes = piece.scale_axes || [1, 1, 1], scale = piece.scale ?? 1;
    copies.push({ id, asset: piece.asset || piece.kind, at,
      rot: [piece.pitch || 0, (piece.rotation || 0) + yaw, piece.roll || 0],
      scale: [axes[0] * scale * (piece.mirror_x ? -1 : 1), axes[1] * scale,
        axes[2] * scale * (piece.mirror_y ? -1 : 1)],
      castsShadow: piece.casts_shadow !== false });
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

export function occluderHash(copies, source, range) {
  const limit = (range + MODEL_REACH_MARGIN_M) ** 2;
  const near = copies.filter(c => (c.at[0] - source.x) ** 2 + (c.at[1] - source.y) ** 2
    + (c.at[2] - source.z) ** 2 <= limit).sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  if (!near.length) return '';
  const round = (value, units) => Math.round(value * units) / units;
  const hash = fingerprint();
  hash.add(JSON.stringify(near.map(c => [c.id, c.asset, c.at.map(v => round(v, 1000)),
    c.rot.map(v => round(v, 10)), c.scale.map(v => round(v, 1e4)), c.castsShadow])));
  return hash.key();
}
