import * as THREE from 'three';
import { TIERS } from '../twin_tiers.js';
import { CANDELA, FT } from '../twin_light_math.js';
import { fixturePoint, fixtureRotation, linePieces } from './fixture_glow.js';

import { paletteColour } from './light_colours.js';
export { lightColor } from './light_colours.js';
export { CANDELA };
const clamp = (value, max = 255) => Math.max(0, Math.min(max, value));

export function lightIntensity(attributes = {}) {
  const value = Number(attributes?.brightness ?? 255);
  return Number.isFinite(value) ? clamp(value) / 255 : 1;
}

export function pickReal(candidates, target, cap) {
  const distance = row => row.at.reduce((sum, value, i) => sum + (value - target[i]) ** 2, 0);
  return candidates.filter(row => row.intensity > 0)
    .sort((a, b) => distance(a) - distance(b) || (b.output ?? b.intensity) - (a.output ?? a.intensity))
    .slice(0, Math.max(0, Math.floor(cap))).map(row => row.device);
}

export function createRealLights(view, { tier = view.tier || 'low', fixtures = true } = {}) {
  // A fixture-free house keeps the original point-only profile, including its shadows.
  const quotas = fixtures ? (TIERS[tier] || TIERS.low).realLights
    : {point: {low: 4, medium: 8, high: 16, max: 16}[tier] || 4, spot: 0, area: 0, shadows: ['high', 'max'].includes(tier) ? 2 : 0};
  // three.js keys programs on the number of visible lights and shadow casters, so
  // per-type counts stay fixed and both distributions of the single caster are warmed.
  // Outside Lights/All the pool is hidden: every lit fragment would otherwise loop
  // over dark lights (Low measured +17% frame time in All). mountModes warms the
  // pool variant with the current environment before the first Lights entry.
  const pools = Object.fromEntries(['point', 'spot', 'area'].map(type => [type, Array.from({ length: quotas[type] }, (_, index) => {
    const light = type === 'area' ? new THREE.RectAreaLight('#fff1c9', 0, 1, 1)
      : type === 'spot' ? new THREE.SpotLight('#fff1c9', 0, 1, Math.PI / 4, .3, 2) : new THREE.PointLight('#fff1c9', 0, 1, 2);
    light.visible = false;
    light.castShadow = type === 'point' && index < quotas.shadows;
    if (light.shadow) {
      light.shadow.mapSize.set(512, 512);
      light.shadow.bias = -.0002; light.shadow.normalBias = .025;
      light.shadow.camera.near = .05;
      light.shadow.autoUpdate = false;
    }
    if (light.isSpotLight) view.scene.add(light.target);
    view.scene.add(light);
    return light;
  })]));
  const pool = Object.values(pools).flat();
  let shown = false, overflow = false;
  function shadows(type) {
    for (const [kind, lights] of Object.entries(pools)) lights.forEach((light, index) => {
      const cast = kind === type && index < quotas.shadows;
      if (light.castShadow !== cast) { light.castShadow = cast; if (cast) light.shadow.needsUpdate = true; }
    });
  }
  return {
    update(candidates, target) {
      const baked = new Set(view.bake?.fresh() || []);
      const expanded = {point: [], spot: [], area: []};
      for (const row of candidates) {
        const e = row.emitter;
        if (baked.has(row.device) && (!e || e.legacy)) continue;
        const type = !e || e.legacy ? 'point' : e.shape === 'line' ? 'area' : e.shape;
        const pieces = e?.shape === 'line' ? linePieces(e) : [null];
        pieces.forEach((piece, i) => expanded[type].push({...row, piece,
          device: `${row.device}:${i}`, owner: row.device,
          rgb: piece && (row.palette || e.palette) ? paletteColour(row.palette || e.palette, piece.t) : row.rgb,
          at: piece ? [piece.position.x / FT, -piece.position.z / FT, piece.position.y / FT] : row.at,
          output: !e || e.legacy ? row.intensity * CANDELA * 4 * Math.PI : e.output_lm_share / pieces.length,
          intensity: !e || e.legacy ? row.intensity : e.shape === 'point' || e.shape === 'spot' ? e.cd : e.luminance}));
      }
      const nearest = pickReal([...expanded.point, ...expanded.spot], target, 1)[0];
      shadows(expanded.spot.some(row => row.device === nearest) ? 'spot' : 'point');
      const selected = new Set(); overflow = false;
      for (const [type, lights] of Object.entries(pools)) {
        const rows = expanded[type], ids = pickReal(rows, target, quotas[type]), byId = new Map(rows.map(row => [row.device, row]));
        overflow ||= fixtures && rows.some(row => row.emitter && !row.emitter.legacy && row.intensity > 0 && !ids.includes(row.device));
        lights.forEach((light, index) => {
          const row = byId.get(ids[index]);
          if (!row) { light.intensity = 0; return; }
          selected.add(row.owner);
          const e = row.emitter, position = row.piece?.position || row.position;
          const aim = e?.shape === 'spot' ? fixturePoint(e.aim) : null;
          const moved = !light.position.equals(position) || light.distance !== row.distance || light.intensity === 0 ||
            aim && (!light.target.position.equals(aim) || light.angle !== e.cone_deg * Math.PI / 360 || light.penumbra !== e.softness);
          light.position.copy(position);
          light.color.setRGB(...row.rgb.map(value => value / 255), THREE.SRGBColorSpace);
          light.intensity = !e || e.legacy ? row.intensity * CANDELA : row.intensity;
          if (type !== 'area') light.distance = row.distance;
          if (type === 'spot') { light.target.position.copy(aim); light.angle = e.cone_deg * Math.PI / 360; light.penumbra = e.softness; }
          if (type === 'area') {
            light.width = row.piece?.width ?? e.size_ft[0] * FT;
            light.height = row.piece?.height ?? e.size_ft[1] * FT;
            light.quaternion.copy(row.piece?.rotation || fixtureRotation(e));
          }
          if (light.castShadow && (moved || light.shadow.camera.far !== row.distance)) {
            light.shadow.camera.far = row.distance;
            light.shadow.camera.updateProjectionMatrix();
            light.shadow.needsUpdate = true;
          }
        });
      }
      return selected;
    },
    overflow: () => overflow,
    warm(compile) {
      const type = pools.spot.some(light => light.castShadow) ? 'spot' : 'point';
      try {
        shadows('point'); compile();
        if (quotas.shadows && pools.spot.length) { shadows('spot'); compile(); }
      } finally { shadows(type); }
    },
    show(on) { shown = !!on; for (const light of pool) light.visible = shown; },
    shown: () => shown,
    stop() {
      for (const light of pool) { light.removeFromParent(); light.target?.removeFromParent(); light.shadow?.dispose(); }
    },
  };
}
