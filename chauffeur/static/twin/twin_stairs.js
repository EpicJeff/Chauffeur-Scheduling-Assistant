import * as THREE from 'three';
import { wallRooms, roomAt, roomFloor, openingFloor } from './twin_floors.js';

// Closed boxes with the generator's physical UVs. Feet, building-local X/-Z.
export function stairGeometry(s, elevation, box) {
  const dx = s.to[0] - s.from[0], dy = s.to[1] - s.from[1], length = Math.hypot(dx, dy), angle = Math.atan2(dy, dx);
  const rise = s.rise_to - elevation, run = length / s.risers, step = rise / s.risers, parts = [];
  if (!(length > 0 && rise > 0 && s.risers > 0)) return parts;
  const open = s.style === 'open';
  for (let i = 0; i < s.risers; i++) {
    const height = rise * (i + 1) / s.risers, thickness = open ? Math.min(.15, step / 3) : height;
    parts.push({ part: open ? 'tread' : 'solid', role: 'floor', geometry: box(run, thickness, s.width).rotateY(angle)
      .translate(s.from[0] + dx * (i + .5) / s.risers, elevation + height - thickness / 2, -s.from[1] - dy * (i + .5) / s.risers) });
  }
  const point = (u, side, z) => new THREE.Vector3(s.from[0] + dx / length * u - dy / length * side,
    elevation + z, -s.from[1] - dy / length * u - dx / length * side);
  const beam = (a, b, width, depth, part, role) => {
    const direction = b.clone().sub(a), geometry = box(width, direction.length(), depth);
    geometry.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize()));
    geometry.translate(...a.clone().add(b).multiplyScalar(.5).toArray());
    parts.push({ part, role, geometry });
  };
  if (open) for (const side of [-1, 1]) {
    const across = side * (s.width / 2 - .2);
    beam(point(0, across, -.2), point(length, across, rise - .2), .18, .25, 'stringer', 'porch_ceiling');
  }
  const sides = { none: [], left: [1], right: [-1], both: [-1, 1] }[s.rail || 'none'] || [];
  for (const side of sides) {
    const across = side * (s.width / 2 - .08), end = Math.max(0, length - run);
    const posts = Math.max(1, Math.ceil(end / 4));
    for (let i = 0; i <= posts; i++) {
      const u = end * i / posts, z = step + u / length * rise;
      beam(point(u, across, z), point(u, across, z + 3), .12, .12, 'post', 'porch_ceiling');
    }
    beam(point(0, across, step + 3), point(end, across, rise + 3), .16, .16, 'handrail', 'porch_ceiling');
  }
  return parts;
}

// Derived on every build: neither a stored stair nor a tier-dependent detail.
export function doorwaySteps(building, opening) {
  if (!['door', 'slider', 'bifold', 'passage', 'garage'].includes(opening.kind) || opening.state === 'ghost') return [];
  const wall = building.walls.find(w => w.id === opening.wall);
  if (!wall || wall.state === 'ghost') return [];
  const reference = openingFloor(building, wall, opening.at), step = reference.step_down_ft;
  if (!(step > 0)) return [];
  const rooms = wallRooms(building, wall, opening.at), lower = rooms.reduce((a, b) => (a.floor_offset_ft || 0) < (b.floor_offset_ft || 0) ? a : b);
  const dx = wall.to[0] - wall.from[0], dy = wall.to[1] - wall.from[1], length = Math.hypot(dx, dy);
  const axis = [dx / length, dy / length], normal = [-axis[1], axis[0]];
  const centre = wall.from.map((v, i) => v + axis[i] * opening.at), inset = (wall.thickness || 0) + .05;
  const sign = roomAt(building, wall.level, centre.map((v, i) => v + normal[i] * inset)) === lower ? 1 : -1;
  const n = Math.ceil(step / (7.5 / 12)), tread = 11 / 12;
  const floor = roomFloor(building.levels.find(l => l.id === wall.level), lower);
  return Array.from({ length: n }, (_, i) => {
    const corner = (along, out) => centre.map((v, k) => v + axis[k] * along + sign * normal[k] * ((wall.thickness || 0) / 2 + out));
    return { polygon: [corner(-opening.width / 2, i * tread), corner(opening.width / 2, i * tread),
      corner(opening.width / 2, (i + 1) * tread), corner(-opening.width / 2, (i + 1) * tread)],
      bottom: floor, top: floor + step * (n - i) / n, riser: step / n, room: lower, level: wall.level };
  });
}
