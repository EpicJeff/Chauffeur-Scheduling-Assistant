import * as THREE from 'three';
import { TIERS } from '../twin_tiers.js';

const clamp = (value, max = 255) => Math.max(0, Math.min(max, value));
// Candela at full brightness. A ceiling light 10 ft up leaves the floor under it
// bright but not clipped under the evening look's exposure, and the far corner lit.
export const CANDELA = 40;

export function lightColor(attributes = {}) {
  const { rgb_color: rgb, color_temp_kelvin: kelvin, color_temp: mireds } = attributes || {};
  if (Array.isArray(rgb) && rgb.length >= 3 && rgb.slice(0, 3).every(Number.isFinite))
    return rgb.slice(0, 3).map(value => Math.round(clamp(value)));
  const temperature = Number(kelvin) > 0 ? Number(kelvin) : Number(mireds) > 0 ? 1e6 / Number(mireds) : null;
  if (!Number.isFinite(temperature) || temperature === null) return [255, 241, 201];
  // Black-body approximation, with HA's temperatures expressed in kelvin.
  const t = Math.max(1000, Math.min(40000, temperature)) / 100;
  return [t <= 66 ? 255 : 329.698727446 * Math.pow(t - 60, -.1332047592),
    t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * Math.pow(t - 60, -.0755148492),
    t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307]
    .map(value => Math.round(clamp(value)));
}

export function lightIntensity(attributes = {}) {
  const value = Number(attributes?.brightness ?? 255);
  return Number.isFinite(value) ? clamp(value) / 255 : 1;
}

export function pickReal(candidates, target, cap) {
  const distance = row => row.at.reduce((sum, value, i) => sum + (value - target[i]) ** 2, 0);
  return candidates.filter(row => row.intensity > 0)
    .sort((a, b) => distance(a) - distance(b) || b.intensity - a.intensity)
    .slice(0, Math.max(0, Math.floor(cap))).map(row => row.device);
}

export function createRealLights(view, { tier = view.tier || 'low' } = {}) {
  const cap = TIERS[tier]?.realLights ?? ({ medium: 8, max: 16 }[tier] || TIERS.low.realLights);
  // three.js keys programs on the number of visible lights and shadow casters, so
  // inside Lights mode the whole pool stays visible and only intensity and placement
  // change. Outside it the pool is hidden: every lit fragment would otherwise loop
  // over dark lights (Low measured +17% frame time in All). Showing it rides the
  // program switch the evening look makes anyway (the environment map goes).
  const pool = Array.from({ length: cap }, (_, index) => {
    const light = new THREE.PointLight('#fff1c9', 0, 1, 2);
    light.visible = false;
    light.castShadow = (tier === 'high' || tier === 'max') && index < 2;
    if (light.castShadow) {
      light.shadow.mapSize.set(512, 512);
      light.shadow.bias = -.0002; light.shadow.normalBias = .025;
      light.shadow.camera.near = .05;
      light.shadow.autoUpdate = false;
    }
    view.scene.add(light);
    return light;
  });
  return {
    update(candidates, target) {
      const baked = new Set(view.bake?.fresh() || []);
      const selected = pickReal(candidates.filter(row => !baked.has(row.device)), target, cap);
      const byId = new Map(candidates.map(row => [row.device, row]));
      pool.forEach((light, index) => {
        const row = byId.get(selected[index]);
        if (!row) { light.intensity = 0; return; }
        const moved = !light.position.equals(row.position) || light.distance !== row.distance || light.intensity === 0;
        light.position.copy(row.position);
        light.color.setRGB(...row.rgb.map(value => value / 255), THREE.SRGBColorSpace);
        light.distance = row.distance;
        light.intensity = row.intensity * CANDELA;
        if (light.castShadow && moved) {
          light.shadow.camera.far = row.distance;
          light.shadow.camera.updateProjectionMatrix();
          light.shadow.needsUpdate = true;
        }
      });
      return new Set(selected);
    },
    show(on) { for (const light of pool) light.visible = !!on; },
    stop() {
      for (const light of pool) { light.removeFromParent(); light.shadow.dispose(); }
    },
  };
}
