import { gutterPlacement, gutterCandidates } from '../gutters.js';
import { roofArea } from '../roof_box_contract.js';
import { roofPoint } from '../roof_supports.js';
export { eaveEdgeIndices as eaveEdges } from '../gutters.js';
export const gutterSnapshot = gutterPlacement;

const FT = .3048;
const clamp = x => Math.max(0, Math.min(1, x));
export const roundAt = x => {
  const f = clamp(Number(x));
  return f === 0 || f === 1 ? f : Math.max(.0001, Math.min(.9999, Math.round(f * 1e4) / 1e4));
};

export const edgeOperation = (building, roof, edge, change) => ({ op: 'set_roof_edge', building, roof, edge, ...change });

export const isExact = entry => !!entry && typeof entry === 'object' && !Array.isArray(entry)
  && typeof entry.at === 'number' && Number.isFinite(entry.at);

export const entryFraction = entry => isExact(entry) ? entry.at
  : typeof entry === 'number' && Number.isFinite(entry) ? entry : NaN;

export const sameDownspoutEntry = (a, b) => isExact(a) && isExact(b)
  ? Math.abs(roundAt(a.at) - roundAt(b.at)) < 1e-8
  : typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) < 1e-8;

function roofRecord(plan, building, roof) {
  const b = plan?.buildings?.find(item => item.id === building);
  const r = b?.roofs?.find(item => item.id === roof);
  return { b, r };
}

function edgeSegment(roof, edge) {
  const area = roof ? roofArea(roof) : [];
  if (!Number.isInteger(edge) || edge < 0 || edge >= area.length) return null;
  const a = roofPoint(roof, area[edge]), b = roofPoint(roof, area[(edge + 1) % area.length]);
  const dx = b[0] - a[0], dy = b[1] - a[1], len2 = dx * dx + dy * dy, length = Math.sqrt(len2);
  return length > 0 ? { a, b, dx, dy, len2, length } : null;
}

function localXY(building, worldMetres) {
  const angle = (building.rotation || 0) * Math.PI / 180, c = Math.cos(angle), s = Math.sin(angle);
  const p = building.position || [0, 0];
  const u = worldMetres[0] / FT - p[0], v = -worldMetres[2] / FT - p[1];
  return [c * u + s * v, -s * u + c * v];
}

export function edgeCandidates(plan, building, roof, edge, candidates = null) {
  return (candidates ?? gutterCandidates(plan)).filter(c =>
    c.building === building && c.roof === roof && c.edge === edge);
}

export function freeCandidates(plan, building, roof, edge, { snapshot = null, candidates = null, excludeIndex = -1, ownFraction = null } = {}) {
  const snap = snapshot || gutterSnapshot(plan);
  const { r } = roofRecord(plan, building, roof);
  const seg = edgeSegment(r, edge);
  const values = downspoutValues(plan, building, roof, edge, snap);
  const otherPlaced = [];
  for (let i = 0; i < values.length; i++) {
    if (i === excludeIndex) continue;
    const p = placedFraction(plan, building, roof, edge, i, values[i], snap);
    if (Number.isFinite(p)) otherPlaced.push({ p, exact: isExact(values[i]) });
  }
  return edgeCandidates(plan, building, roof, edge, candidates).filter(c => {
    if (ownFraction !== null && Math.abs(c.fraction - ownFraction) < 1e-4) return true;
    if (c.occupied) return false;
    if (Array.isArray(c.nearExact)) {
      if (c.nearExact.some(n => !(n.roof === roof && n.edge === edge && n.index === excludeIndex))) return false;
    } else if (otherPlaced.some(o => o.exact && (seg ? Math.abs(o.p - c.fraction) * seg.length <= 1 + 1e-6 : Math.abs(o.p - c.fraction) < 1e-4))) {
      return false;
    }
    return !otherPlaced.some(o => !o.exact && Math.abs(o.p - c.fraction) < 1e-4);
  });
}

export function nearestFreeCandidate(plan, building, roof, edge, fraction, excludeIndex = -1, snapshot = null, candidates = null) {
  const list = freeCandidates(plan, building, roof, edge, { snapshot, candidates, excludeIndex });
  let best = null, bestGap = Infinity;
  for (const c of list) {
    const gap = Math.abs(c.fraction - fraction);
    if (gap < bestGap - 1e-9 || Math.abs(gap - bestGap) <= 1e-9 && (!best || c.fraction < best.fraction)) {
      best = c; bestGap = gap;
    }
  }
  return best ? best.fraction : null;
}

export function snapOrExact(plan, building, roof, edge, fraction, candidates = null) {
  const f = clamp(Number(fraction));
  const { r } = roofRecord(plan, building, roof);
  const seg = edgeSegment(r, edge);
  if (!seg) return { at: roundAt(f) };
  const list = edgeCandidates(plan, building, roof, edge, candidates);
  let best = null, bestGap = Infinity;
  for (const c of list) {
    const gap = Math.abs(f - c.fraction) * seg.length;
    if (gap <= 1 + 1e-6 && gap < bestGap) { best = c; bestGap = gap; }
  }
  return best ? best.fraction : { at: roundAt(f) };
}

export function downspoutValues(plan, building, roof, edge, snapshot = null) {
  const { r } = roofRecord(plan, building, roof);
  const record = r?.edges?.[edge];
  if (Array.isArray(record?.downspouts)) return record.downspouts.map(v => isExact(v) ? { at: v.at } : v);
  const { runs, spouts } = snapshot || gutterSnapshot(plan);
  const ids = new Set(runs.filter(run => run.building === building).map(run => run.id));
  return spouts.filter(s => ids.has(s.run) && s.edge.roof === roof && s.edge.edge === edge)
    .map(s => s.exact ? { at: s.authoredFraction ?? s.edge.fraction } : s.edge.fraction).slice(0, 8);
}

// Match authoredIndex when placement provides it; otherwise fall back to the
// nearest authored entry fraction (accepting both numbers and {at: f}).
export function downspoutIndex(values, fraction, authoredIndex = null) {
  if (Number.isInteger(authoredIndex) && authoredIndex >= 0 && authoredIndex < values.length) return authoredIndex;
  const target = entryFraction(fraction);
  if (!Number.isFinite(target)) return -1;
  return values.reduce((best, value, i) => {
    const f = entryFraction(value);
    if (!Number.isFinite(f)) return best;
    return best < 0 || Math.abs(f - target) < Math.abs(entryFraction(values[best]) - target) ? i : best;
  }, -1);
}

export function placedFraction(plan, building, roof, edge, index, entry, snapshot = null) {
  const { b, r } = roofRecord(plan, building, roof);
  const snap = snapshot || gutterSnapshot(plan);
  const ids = new Set(snap.runs.filter(run => run.building === building).map(run => run.id));
  const buildingSpouts = snap.spouts.filter(s => ids.has(s.run));
  const edgeSpouts = buildingSpouts.filter(s => s.edge.roof === roof && s.edge.edge === edge);
  const byIndex = edgeSpouts.find(s => Number.isInteger(s.authoredIndex) && s.authoredIndex === index);
  if (byIndex) return byIndex.edge.fraction;
  const authored = Array.isArray(r?.edges?.[edge]?.downspouts);
  if (!authored && edgeSpouts[index]) return edgeSpouts[index].edge.fraction;
  const f = entryFraction(entry), exact = isExact(entry);
  const byAuthored = edgeSpouts.find(s => Boolean(s.exact) === exact
    && Number.isFinite(s.authoredFraction) && Math.abs(s.authoredFraction - f) < 1e-5);
  if (byAuthored) return byAuthored.edge.fraction;
  if (!exact) {
    const byMerged = buildingSpouts.find(s => (s.merged || []).some(m =>
      m.roof === roof && m.edge === edge && Math.abs(m.fraction - f) < 1e-5));
    if (byMerged) {
      if (byMerged.edge.roof === roof && byMerged.edge.edge === edge) return byMerged.edge.fraction;
      const seg = edgeSegment(r, edge);
      if (seg && b && Array.isArray(byMerged.top)) {
        const p = localXY(b, byMerged.top);
        return clamp(((p[0] - seg.a[0]) * seg.dx + (p[1] - seg.a[1]) * seg.dy) / seg.len2);
      }
    }
    const cornerSpouts = edgeSpouts.filter(s => !s.exact);
    if (cornerSpouts.length) {
      let nearest = cornerSpouts[0], bestGap = Math.abs(cornerSpouts[0].edge.fraction - f);
      for (let i = 1; i < cornerSpouts.length; i++) {
        const gap = Math.abs(cornerSpouts[i].edge.fraction - f);
        if (gap < bestGap) { bestGap = gap; nearest = cornerSpouts[i]; }
      }
      return nearest.edge.fraction;
    }
  }
  const byPlaced = edgeSpouts.find(s => Math.abs(s.edge.fraction - f) < 1e-5);
  if (byPlaced) return byPlaced.edge.fraction;
  return f;
}

export function isMergedEntry(plan, building, roof, edge, index, entry, snapshot = null) {
  if (isExact(entry)) return false;
  const { r } = roofRecord(plan, building, roof);
  const record = r?.edges?.[edge];
  if (!Array.isArray(record?.downspouts)) return false;
  const snap = snapshot || gutterSnapshot(plan);
  const ids = new Set(snap.runs.filter(run => run.building === building).map(run => run.id));
  const buildingSpouts = snap.spouts.filter(s => ids.has(s.run));
  const edgeSpouts = buildingSpouts.filter(s => s.edge.roof === roof && s.edge.edge === edge);
  const f = entryFraction(entry);
  if (edgeSpouts.some(s => Number.isInteger(s.authoredIndex))) {
    if (edgeSpouts.some(s => s.authoredIndex === index)) return false;
  } else {
    const dupEarlier = record.downspouts.slice(0, index).some(v => !isExact(v) && Math.abs(entryFraction(v) - f) < 1e-5);
    if (!dupEarlier && edgeSpouts.some(s => !s.exact && Number.isFinite(s.authoredFraction) && Math.abs(s.authoredFraction - f) < 1e-5))
      return false;
  }
  if (buildingSpouts.some(s => (s.merged || []).some(m =>
    m.roof === roof && m.edge === edge && Math.abs(m.fraction - f) < 1e-5))) return true;
  return edgeSpouts.some(s => !s.exact);
}

function exposedEdgeIntervals(plan, building, roof, edge, snapshot = null) {
  const { b, r } = roofRecord(plan, building, roof);
  const seg = edgeSegment(r, edge);
  if (!b || !seg) return [];
  const snap = snapshot || gutterSnapshot(plan);
  const raw = [];
  for (const run of snap.runs) {
    if (run.building !== building) continue;
    for (const s of run.segments || []) {
      if (s.roof !== roof || s.edge !== edge || !Array.isArray(s.a) || !Array.isArray(s.b)) continue;
      const la = localXY(b, s.a), lb = localXY(b, s.b);
      const ta = clamp(((la[0] - seg.a[0]) * seg.dx + (la[1] - seg.a[1]) * seg.dy) / seg.len2);
      const tb = clamp(((lb[0] - seg.a[0]) * seg.dx + (lb[1] - seg.a[1]) * seg.dy) / seg.len2);
      const lo = Math.min(ta, tb), hi = Math.max(ta, tb);
      if ((hi - lo) * seg.length > 1e-4) raw.push([lo, hi]);
    }
  }
  raw.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged = [], tol = 1e-4 / seg.length;
  for (const interval of raw) {
    const last = merged.at(-1);
    if (last && interval[0] <= last[1] + tol) last[1] = Math.max(last[1], interval[1]);
    else merged.push([...interval]);
  }
  return merged;
}

export function addDownspout(plan, building, roof, edge, snapshot = null, candidates = null) {
  const { r } = roofRecord(plan, building, roof);
  const snap = snapshot || gutterSnapshot(plan);
  // Materialise only full automatic drops. Keep diagnostic stubs in the normal
  // row/handle snapshot until Add replaces them with a real authored outlet.
  const ids = new Set(snap.runs.filter(run => run.building === building).map(run => run.id));
  const full = Array.isArray(r?.edges?.[edge]?.downspouts) ? null : snap.spouts.filter(s =>
    ids.has(s.run) && s.edge.roof === roof && s.edge.edge === edge && !(s.flags || []).includes('stub'));
  const values = full ? full.map(s => s.exact ? { at: s.authoredFraction ?? s.edge.fraction } : s.edge.fraction)
    : downspoutValues(plan, building, roof, edge, snap);
  if (values.length >= 8) return null;
  const seg = edgeSegment(r, edge);
  const existing = (full ? full.map(s => s.edge.fraction)
    : values.map((entry, i) => placedFraction(plan, building, roof, edge, i, entry, snap))).filter(Number.isFinite);
  const clear = f => existing.every(v => seg ? Math.abs(f - v) * seg.length >= 1 - 1e-6 : Math.abs(f - v) >= 1e-5);
  const free = edgeCandidates(plan, building, roof, edge, candidates).find(c => !c.occupied && !(c.nearExact?.length) && clear(c.fraction));
  if (free) return [...values, free.fraction];
  if (!seg) return null;
  const pieces = exposedEdgeIntervals(plan, building, roof, edge, snap);
  if (!pieces.length) return null;
  const pad = 1 / seg.length;
  const byLength = [...pieces].sort((a, b) => (b[1] - b[0]) - (a[1] - a[0]) || a[0] - b[0]);
  for (const [lo, hi] of byLength) {
    const mid = (lo + hi) / 2;
    if (clear(mid)) return [...values, { at: roundAt(mid) }];
    let spans = [[lo, hi]];
    for (const v of existing) {
      const cutLo = v - pad, cutHi = v + pad;
      spans = spans.flatMap(([a, b]) => {
        if (cutHi <= a || cutLo >= b) return [[a, b]];
        const out = [];
        if (cutLo >= a - 1e-9) out.push([a, Math.max(a, cutLo)]);
        if (cutHi <= b + 1e-9) out.push([Math.min(b, cutHi), b]);
        return out;
      });
    }
    spans = spans.filter(([a, b]) => b >= a - 1e-9).sort((a, b) => (b[1] - b[0]) - (a[1] - a[0]) || a[0] - b[0]);
    for (const [a, b] of spans) {
      const cand = clamp((a + b) / 2);
      if (clear(cand)) return [...values, { at: roundAt(cand) }];
    }
  }
  return null;
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
  'placed-off-corner': 'This downspout was placed by hand away from an outside corner.',
  'over-opening': 'This downspout passes a door or window.',
  'no-support': 'This downspout has no wall or post to fasten to.',
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
