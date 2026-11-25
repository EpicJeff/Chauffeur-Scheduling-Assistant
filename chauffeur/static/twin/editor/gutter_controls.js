import { gutterPlacement, gutterCandidates } from '../gutters.js';
import { roofArea } from '../roof_box_contract.js';
export { eaveEdgeIndices as eaveEdges } from '../gutters.js';
export const gutterSnapshot = gutterPlacement;

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

export function addDownspout(plan, building, roof, edge) {
  const values = downspoutValues(plan, building, roof, edge);
  if (values.length >= 8) return null;
  const free = gutterCandidates(plan).find(c => c.building === building && c.roof === roof && c.edge === edge
    && !c.occupied && !values.some(v => Math.abs(v - c.fraction) < 1e-5));
  return free ? [...values, free.fraction] : null;
}

export function gutterOwner(plan, buildingId, ref) {
  const b = plan?.buildings?.find(b => b.id === buildingId);
  if (!b) return null;
  if (ref.roof != null) {
    const roof = b.roofs?.find(r => r.id === ref.roof);
    return roof?.edges?.[ref.edge] ? { record: roof.edges[ref.edge], roof,
      name: roof.name || `${b.name || 'House'} roof ${b.roofs.indexOf(roof) + 1}` } : null;
  }
  const record = [...(b.porches || []), ...(b.porches_detail || []), b.porch].find(p => p?.id === ref.porch);
  return record ? { record, name: record.name || b.rooms?.find(r => r.id === record.id)?.name
    || 'Porch' } : null;
}

export function gutterLocation(plan, buildingId, ref, fraction = null) {
  const owner = gutterOwner(plan, buildingId, ref);
  let label = owner?.name || 'Roof section';
  if (owner?.roof && Number.isInteger(ref.edge)) {
    const area = roofArea(owner.roof), a = area[ref.edge], b = area[(ref.edge + 1) % area.length];
    const centre = [0, 1].map(i => area.reduce((n, p) => n + p[i], 0) / area.length);
    const edge = Math.abs(b[0] - a[0]) > Math.abs(b[1] - a[1]) ? (a[1] < centre[1] ? 'front' : 'back') : (a[0] < centre[0] ? 'left' : 'right');
    label += `, ${edge} edge`;
    if (fraction != null) label += fraction <= .025 ? ', at the start' : fraction >= .975 ? ', at the far end'
      : `, ${Math.round(fraction * Math.hypot(b[0] - a[0], b[1] - a[1]))} ft from the start`;
  } else if (fraction != null) label += fraction <= .025 ? ', at the start' : fraction >= .975 ? ', at the far end' : ', along the eave';
  return label;
}

export function gutterAcknowledgement(plan, item) {
  const owner = gutterOwner(plan, item.building, item);
  const flags = [...new Set([...(owner?.record.gutter_ack || []), ...item.flags])];
  return item.roof != null ? edgeOperation(item.building, item.roof, item.edge, { gutter_ack: flags })
    : { op: 'set', building: item.building, id: item.porch, field: 'gutter_ack', value: flags };
}

const reasons = {
  'no-outside-corner': 'This gutter run has no usable outside corner for a downspout.',
  hang: 'This downspout has no wall or porch post to run down.',
  stub: 'This downspout ends in a short outlet instead of a full drop.',
  'inner-end': 'This gutter ends at an inside corner; check its drainage.',
  'clipped-end': 'This gutter ends where another roof clips the eave.',
  'no-safe-landing': 'This outlet has no safe grass, bed or driveway landing.',
  'no-outlet': 'No downspout location could be placed on this building; water spills from a short stub.',
  'outlet-blocked': 'The receiving surface blocks this downspout outlet.',
  'merged-override': 'Several downspout overrides share one outlet.',
};
export function gutterCheckItems(plan, snapshot = gutterPlacement(plan)) {
  const items = [];
  for (const run of snapshot.runs) {
    const spouts = snapshot.spouts.filter(s => s.run === run.id);
    const add = (issueFlags, spout = null) => {
      const segment = run.segments.find(s => s.roof != null) || run.segments[0];
      const ref = spout?.edge || segment;
      if (!ref) return;
      const owner = gutterOwner(plan, run.building, ref);
      const flags = [...new Set(issueFlags)].filter(f => reasons[f] && !owner?.record.gutter_ack?.includes(f));
      if (!flags.length) return;
      const label = gutterLocation(plan, run.building, ref, spout?.edge.fraction);
      const merged = flags.includes('merged-override') ? (spout?.merged || []).map(m => {
        const other = snapshot.runs.find(r => r.id === m.run);
        return gutterLocation(plan, other?.building || run.building, m, m.fraction);
      }).join('; ') : '';
      const explained = flags.filter(f => !(f === 'stub' && flags.includes('hang')));
      items.push({ kind: 'gutter', id: spout?.id || run.id, building: run.building,
        roof: ref.roof, edge: ref.edge, porch: ref.porch, run: run.id, spout: spout?.id || spouts[0]?.id,
        top: spout?.top || spouts[0]?.top || segment.a, flags, label,
        reason: explained.map(f => reasons[f]).join(' ') + (merged ? ` Merged locations: ${merged}.` : '') });
    };
    const runFlags = (run.flags || []).filter(f => !spouts.some(s => s.flags?.includes(f)));
    if (runFlags.length) add(runFlags);
    for (const spout of spouts) add(spout.flags || [], spout);
  }
  return items;
}
