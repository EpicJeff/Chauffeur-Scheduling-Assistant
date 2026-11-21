// Shared, renderer-independent slot inheritance. Callers supply the receiving
// role and the owning objects (or their IDs); refs never change the bake role.
// `ref` is the local slot. `parents` holds enclosing slots, e.g. plane -> roof
// or ledge -> pool. `roomRole` is wall/floor/ceiling for a facing room.
// `fallback` may be another resolution, for a kind that follows another role.
// Kit refs stay role aliases so existing procedural defaults keep their look.
export function resolveSurfaceMaterial(plan, surface) {
  const { role, roomRole } = surface;
  const building = typeof surface.building === 'string'
    ? plan.buildings?.find(b => b.id === surface.building) : surface.building;
  const level = typeof surface.level === 'string'
    ? building?.levels?.find(l => l.id === surface.level) : surface.level;
  const room = typeof surface.room === 'string'
    ? building?.rooms?.find(r => r.id === surface.room) : surface.room;
  const chain = [
    ['surface', surface.ref], ...(surface.parents || []).map(ref => ['surface', ref]),
    ['room', room?.[`${roomRole || role}_material`]],
    ['level', level?.materials?.[role]], ['building', building?.materials?.[role]],
    ['house', plan.materials?.[role]],
    [surface.fallback?.source.kind || 'kit', surface.fallback?.ref || surface.defaultRef || { id: role }],
  ];
  const ref = {};
  for (const [kind, value] of chain) {
    if (!value) continue;
    if (ref.color === undefined && value.color !== undefined) ref.color = value.color;
    if (ref.uv === undefined && value.uv !== undefined) ref.uv = { ...value.uv };
    if (value.id) {
      // Selecting another material uses its own tint/offset defaults; only an
      // id-less ref composes its properties with an inherited slot.
      const kitRef = surface.kit?.materials?.[value.id];
      return { ref: { id: value.id, ...ref }, source: { kind, id: kitRef?.id || kitRef?.asset || value.id } };
    }
  }
  return { ref: { id: role, ...ref }, source: { kind: 'kit', id: role } };
}
