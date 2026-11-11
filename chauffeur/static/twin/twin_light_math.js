// Pure lamp geometry shared by the live rig and the atlas module worker.
export const FT = 0.3048;

// A real light reaches the far corner of its own room and little beyond: the
// farthest floor corner from the fixture (lot feet, 3D), with a margin so the
// range's smooth cut-off leaves that corner lit. Without shadows a light shines
// through walls, so a tighter range is also less light in the next room and on
// the lawn outside. Bounded to the room's larger span (0.6x to 2x).
// Feet above the floor at which a floor lamp's bulb hangs (Ruling R1).
export const LAMP_HEIGHT = 4.5;

export function lightRange(marker, building, level, room, span) {
  if (!room?.polygon?.length || !building) return span * 1.5;
  const angle = (building.rotation || 0) * Math.PI / 180, [px, py] = building.position || [0, 0];
  const floor = (building.base || 0) + (level?.elevation || 0), dz = Math.max(0, marker.at[2] - floor);
  const reach = Math.max(...room.polygon.map(([x, y]) => Math.hypot(
    Math.cos(angle) * x - Math.sin(angle) * y + px - marker.at[0],
    Math.sin(angle) * x + Math.cos(angle) * y + py - marker.at[1], dz)));
  return Math.max(.6 * span, Math.min(2 * span, reach * 1.5));
}

