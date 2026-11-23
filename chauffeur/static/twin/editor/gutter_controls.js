import { gutterRuns, downspouts } from '../gutters.js';
import { endKind } from '../twin_roof.js';

// Cards, handles and Check consume one placement result per immutable plan.
// Never rebuild placement on every camera/control frame.
const snapshots = new WeakMap();
export function gutterSnapshot(plan) {
  if (!plan) return { runs: [], spouts: [] };
  if (!snapshots.has(plan)) {
    const enabled = plan.buildings?.some(b => b.roofs?.some(r => r.edges?.some(e => e.gutter))
      || b.roof?.sections?.some(s => Object.values(s.gutters || {}).some(Boolean))
      || [...(b.porches || []), ...(b.porches_detail || []), b.porch, ...(b.roof?.extensions || [])].some(p => p?.gutter));
    const runs = enabled ? gutterRuns(plan) : [];
    snapshots.set(plan, { runs, spouts: runs.length ? downspouts(plan, runs) : [] });
  }
  return snapshots.get(plan);
}

export function eaveEdges(building, roof) {
  const sections = building.roof?.sections?.filter(s => (s.roof || s.id) === roof.id) || [];
  return roof.edges.flatMap((edge, index) => {
    if (edge.setting !== 'sloped') return [];
    const eave = !sections.length || sections.some(s => Object.entries(s.plane_edges || {}).some(([side, i]) => i === index
      && (s.kind === 'flat' || (s.kind === 'shed' ? s.low_side === side
        : ['hip', 'gable'].includes(s.kind) && (side[0] !== s.ridge || endKind(s, side) === 'hip')))));
    return eave ? [index] : [];
  });
}

export const edgeOperation = (building, roof, edge, change) => ({ op: 'set_roof_edge', building, roof, edge, ...change });

export function downspoutValues(plan, building, roof, edge) {
  const record = plan.buildings.find(b => b.id === building)?.roofs?.find(r => r.id === roof)?.edges[edge];
  if (Array.isArray(record?.downspouts)) return [...record.downspouts];
  const { runs, spouts } = gutterSnapshot(plan), ids = new Set(runs.filter(r => r.building === building).map(r => r.id));
  return spouts.filter(s => ids.has(s.run) && s.edge.roof === roof && s.edge.edge === edge).map(s => s.edge.fraction).slice(0, 8);
}

// A stored fraction can snap to a corner. Match the nearest authored entry,
// keeping all the other overrides (including ones merged by placement).
export function downspoutIndex(values, fraction) {
  return values.reduce((best, value, i) => best < 0 || Math.abs(value - fraction) < Math.abs(values[best] - fraction) ? i : best, -1);
}

export function addDownspout(values) {
  if (values.length >= 8) return null;
  const sorted = [0, ...values.slice().sort((a, b) => a - b), 1];
  let start = 0, size = -1;
  for (let i = 1; i < sorted.length; i++) if (sorted[i] - sorted[i - 1] > size) { start = sorted[i - 1]; size = sorted[i] - sorted[i - 1]; }
  return [...values, start + size / 2];
}

const reasons = {
  'no-outside-corner': 'This gutter run has no usable outside corner for a downspout.',
  hang: 'This downspout has no wall or porch post to run down.',
  stub: 'This downspout ends in a short outlet instead of a full drop.',
  'inner-end': 'This gutter ends at an inside corner; check its drainage.',
  'clipped-end': 'This gutter ends where another roof clips the eave.',
  'no-safe-landing': 'This outlet has no safe grass, bed or driveway landing.',
  'no-outlet': 'This gutter has no owned outlet; an emergency outlet carries its water.',
  'outlet-blocked': 'The receiving surface blocks this downspout outlet.',
  'merged-override': 'Several downspout overrides share one outlet.',
};
export function gutterCheckItems(plan, snapshot = gutterSnapshot(plan)) {
  const items = [];
  for (const run of snapshot.runs) {
    const spouts = snapshot.spouts.filter(s => s.run === run.id);
    const add = (flag, spout = null) => {
      if (!reasons[flag]) return;
      const segment = run.segments.find(s => s.roof !== null) || run.segments[0];
      const merged = flag === 'merged-override' ? (spout?.merged || []).map(m => `${m.run} at fraction ${m.fraction}`).join('; ') : '';
      items.push({ kind: 'gutter', id: `${spout?.id || run.id}:${flag}`, building: run.building,
        roof: spout?.edge.roof ?? segment?.roof, edge: spout?.edge.edge ?? segment?.edge,
        porch: spout?.edge.porch ?? segment?.porch, run: run.id, spout: spout?.id || spouts[0]?.id,
        top: spout?.top || spouts[0]?.top || segment?.a, flag,
        reason: reasons[flag] + (merged ? ` Merged: ${merged}.` : '') });
    };
    for (const flag of run.flags || []) if (!spouts.some(s => s.flags?.includes(flag))) add(flag);
    for (const spout of spouts) for (const flag of spout.flags || []) add(flag, spout);
  }
  return items;
}
