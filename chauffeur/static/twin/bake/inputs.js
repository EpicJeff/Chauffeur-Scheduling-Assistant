// Cheap freshness receipts for the non-drawing editor. Geometry is already
// identified by the atlas key; light inputs and authored finishes identify the
// remaining inputs without allocating/transcoding the viewer's page arrays.
import { fingerprint } from './atlas.js';
export function bakeInputs(plan, lights, materials = {}) {
  const fields = new Set(['materials', 'material', 'faces', 'plane_materials', 'floor_material', 'ceiling_material', 'wall_material', 'tint']);
  const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
  const finishes = (value, path = []) => !value || typeof value !== 'object' ? [] :
    Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).flatMap(([key, item]) => fields.has(key) ? [[...path, key, item]] : finishes(item, [...path, key]));
  const hash = fingerprint(); hash.add(JSON.stringify(canonical([finishes(plan), materials])));
  const finish = hash.key();
  return Object.fromEntries(lights.map(light => {
    const hash = fingerprint(); hash.add(JSON.stringify(canonical([finish, light])));
    return [light.device, hash.key()];
  }));
}
