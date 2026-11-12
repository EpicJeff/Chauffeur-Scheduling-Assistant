// Building-local feet. Ceilings and wall tops remain relative to the level.
export const roomFloor = (level, room) => (level?.elevation || 0) + (room?.floor_offset_ft || 0);
function inside(poly, x, y) {
  let yes = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) yes = !yes;
  }
  return yes;
}
export function roomAt(building, level, point) {
  return (building.rooms || []).find(r => r.level === level && r.state !== 'ghost' && r.polygon?.length >= 3 && inside(r.polygon, ...point));
}
export function wallRooms(building, wall, at) {
  const a = wall.from, b = wall.to, length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (!length) return [];
  const dx = (b[0] - a[0]) / length, dy = (b[1] - a[1]) / length;
  const x = a[0] + dx * at, y = a[1] + dy * at, inset = (wall.thickness || 0) + .05;
  return [...new Set([-1, 1].map(sign => roomAt(building, wall.level, [x - sign * dy * inset, y + sign * dx * inset])).filter(Boolean))];
}
export function openingFloor(building, wall, at) {
  const offsets = wallRooms(building, wall, at).map(r => r.floor_offset_ft || 0);
  return { offset: offsets.length ? Math.max(...offsets) : 0,
    step_down_ft: offsets.length > 1 ? Math.max(...offsets) - Math.min(...offsets) : 0 };
}
export function wallFloorProfile(building, wall) {
  const changed = (building.rooms || []).filter(r => r.level === wall.level && r.state !== 'ghost' && r.floor_offset_ft);
  if (!changed.length) return { cuts: [], bottom: () => 0 };
  const dx = wall.to[0] - wall.from[0], dy = wall.to[1] - wall.from[1], length = Math.hypot(dx, dy);
  const cuts = [0, length];
  for (const r of changed)
    for (const p of r.polygon || []) {
      const u = ((p[0] - wall.from[0]) * dx + (p[1] - wall.from[1]) * dy) / length;
      if (u > 0 && u < length) cuts.push(u);
    }
  return { cuts, bottom: u => {
    const rooms = wallRooms(building, wall, Math.max(.00001, Math.min(length - .00001, u)));
    return rooms.length ? Math.min(...rooms.map(r => r.floor_offset_ft || 0)) : 0;
  } };
}
// Partition foundation triangles at changed room boundaries. Outside the room
// lines (the wall footprint), the nearest room owns the concrete too, so a
// sunken garage cannot retain a narrow plinth along its exterior wall.
export function foundationPieces(building, level, triangles) {
  const rooms = (building.rooms || []).filter(r => r.level === level.id && r.state !== 'ghost' && r.polygon?.length >= 3);
  let parts = triangles;
  for (const room of rooms.filter(r => r.floor_offset_ft)) room.polygon.forEach((a, i) => {
    const b = room.polygon[(i + 1) % room.polygon.length];
    const distance = p => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    parts = parts.flatMap(poly => {
      const values = poly.map(distance);
      if (Math.min(...values) >= -1e-8 || Math.max(...values) <= 1e-8) return [poly];
      return [-1, 1].map(sign => poly.flatMap((p, j) => {
        const q = poly[(j + 1) % poly.length], d = values[j], e = values[(j + 1) % poly.length];
        const out = sign * d >= 0 ? [p] : [];
        if (d * e < 0) out.push(p.map((v, k) => v + (q[k] - v) * d / (d - e)));
        return out;
      })).filter(p => p.length >= 3);
    });
  });
  const edgeDistance = (p, a, b) => {
    const dx = b[0] - a[0], dy = b[1] - a[1], length = dx * dx + dy * dy;
    const t = length ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length)) : 0;
    return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
  };
  return parts.map(polygon => {
    const p = [0, 1].map(k => polygon.reduce((sum, q) => sum + q[k], 0) / polygon.length);
    const room = roomAt(building, level.id, p) || rooms.map(r => ({ r, d: Math.min(...r.polygon.map((a, i) => edgeDistance(p, a, r.polygon[(i + 1) % r.polygon.length]))) }))
      .sort((a, b) => a.d - b.d)[0]?.r;
    return { polygon, top: roomFloor(level, room) };
  });
}
