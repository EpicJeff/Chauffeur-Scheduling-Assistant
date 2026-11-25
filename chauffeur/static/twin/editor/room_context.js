import { contains } from '../twin_generator.js';
import { allPorches } from '../gutter_presence.js';

// Editing context is independent of visual focus. Prefer the selected room,
// then explicit room focus, then the room hosting the object being edited.
export function roomInQuestion(plan, selected = {}, host = null) {
  selected ||= {};
  const buildingId = selected.building ?? selected.buildingId;
  const building = plan?.buildings?.find(b => b.id === buildingId) || host?.building;
  const id = ['room', 'porch', 'yard_rooms'].includes(selected.kind) ? selected.id ?? selected.pieceId : null;
  const rooms = [...(building?.rooms || []), ...allPorches(building || {})];
  for (const candidate of [id, selected.focusKind !== 'level' ? selected.room : null]) {
    const room = rooms.find(r => candidate && r.id === candidate && r.state !== 'ghost');
    if (room) return { building, room };
  }
  if (selected.kind === 'yard_rooms') {
    const room = plan?.site?.yard_rooms?.find(r => r.id === id);
    if (room) return { building: null, room };
  }
  const owner = host?.building || building;
  const piece = host?.piece || (host?.building ? null : host) || ['anchors', 'devices', 'items', 'fixtures', 'lights', 'openings', 'walls'].flatMap(list => owner?.[list] || [])
    .find(p => p.id === (selected.id ?? selected.pieceId));
  const binding = piece?.host || piece;
  const hosted = owner?.rooms?.find(r => r.state !== 'ghost' && [binding?.floor, binding?.ceiling].includes(r.id));
  if (hosted) return { building: owner, room: hosted };
  const opening = owner?.openings?.find(o => o.id === binding?.opening);
  const wall = owner?.walls?.find(w => w.id === (binding?.wall || piece?.wall || opening?.wall || opening?.host?.wall || (selected.kind === 'wall' ? selected.id : null)));
  if (wall) {
    const dx = wall.to[0] - wall.from[0], dy = wall.to[1] - wall.from[1], length = Math.hypot(dx, dy);
    if (!length) return null;
    const faces = [1, -1].map(sign => {
      const offset = (wall.thickness || 0) / 2 + .05;
      const point = [(wall.from[0] + wall.to[0]) / 2 - sign * dy / length * offset,
        (wall.from[1] + wall.to[1]) / 2 + sign * dx / length * offset];
      return owner.rooms?.find(r => r.state !== 'ghost' && r.level === wall.level && contains(r.polygon, point));
    });
    const room = binding?.side === 'left' ? faces[0] : binding?.side === 'right' ? faces[1]
      : binding?.side === 'out' ? (faces[0] ? faces[1] : faces[0]) : faces[0] || faces[1];
    if (room) return { building: owner, room };
  }
  return null;
}
