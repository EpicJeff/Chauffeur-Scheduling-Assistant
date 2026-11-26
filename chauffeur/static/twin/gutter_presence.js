// Leaf-only authored gutter presence. Safe before generator/placement imports.
// Keep in step with twin_plan.porches: ids win, polygon fallback for aliases
// without an id. Return the original pieces, preferring collection entries.
export function allPorches(building) {
  const result = [];
  const collection = building.porches || [];
  for (const [index, porch] of [...collection, building.porch].entries()) {
    if (!porch || result.some(p => p.id && porch.id ? p.id === porch.id
      : JSON.stringify(p.polygon) === JSON.stringify(porch.polygon))) continue;
    if (index === collection.length) result.unshift(porch);
    else result.push(porch);
  }
  return result;
}

export function buildingHasGutters(b, sections = b.roof?.sections || []) {
  return (b.roofs || []).some(r => (r.edges || []).some(e => e?.gutter === true))
    || sections.some(s => s.gutters && Object.values(s.gutters).some(v => v === true))
    || allPorches(b).some(p => p?.gutter === true && p.state !== 'ghost' && p.state !== 'proposal');
}

export function planHasGutters(plan) {
  return (plan?.buildings || []).some(b => buildingHasGutters(b));
}
