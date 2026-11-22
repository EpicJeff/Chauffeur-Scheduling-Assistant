import { fingerprint } from './geometry_key.js';

// Shared with the exact atlas/cache keys. Advance the generator stamp whenever
// generated receiving geometry changes (including changes outside atlas.js).
export const ATLAS_VERSION = 'reach-atlas-12';
export const ATLAS_WORKER_VERSION = 'atlas-worker-reach-12';
export const BAKE_GENERATOR_VERSION = 'wet-drip-line-1';

const hash = value => { const h = fingerprint(); h.add(JSON.stringify(value)); return h.key(); };
export function keyInputs(view) {
  const plan = view.bakePlan || view.plan;
  // reach.js uses colour, material id and revision; alpha classification also
  // controls which surfaces exist. Never inspect drawn/faded editor materials.
  const materials = Object.entries(view.materialManifest || {}).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
    .map(([id, e]) => [id, e.revision ?? null, e.params?.tint ?? null, e.params?.alpha_mode || 'opaque',
      e.params?.opacity ?? null, e.params?.alpha_cutoff ?? null]);
  const stage = view.stage;
  return { atlas: ATLAS_VERSION, worker: ATLAS_WORKER_VERSION, generator: BAKE_GENERATOR_VERSION,
    planGenerator: plan?.generatorVersion ?? null, materials: hash(materials),
    stage: hash([stage?.centre ?? null, stage?.radius ?? null, view.site ?? null]) };
}
export const sameKeyInputs = (a, b) => !!a && !!b && JSON.stringify(a) === JSON.stringify(b);
