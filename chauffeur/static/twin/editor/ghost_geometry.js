import * as THREE from 'three';
import { polygon } from '../twin_generator.js';
import { roofMesh } from '../twin_roof.js';

// One look and one builder for every editor ghost: a piece the build is reading now and a piece a
// new reading proposes are the same concept (docs/ui_design_guide.md, same concept, same builder).
// Geometry is in the building's own feet; the caller places the group with the building's frame.
export const GHOST_COLOR = '#38bdf8';
export const GHOST_FILL = .3;
export const GHOST_EDGE = .8;
const OPENING_DEPTH = .18;

const num = value => typeof value === 'number' && Number.isFinite(value);
const point = value => Array.isArray(value) && value.length >= 2 && num(value[0]) && num(value[1]);
const ring = value => Array.isArray(value) && value.length >= 3 && value.every(point);

// kind: level, wall, opening, room, fixture, roof, or any other proposal kind (stairs, porches,
// anchors, items). ctx: level(id) -> {elevation, ceiling}; wall(id) -> {from, to, level};
// joint(id) -> [x, y]; host(host, offset) -> [x, y, z]. A piece that cannot be drawn gives null.
export function pieceGhostGeometry(kind, piece, ctx = {}) {
  if (!piece || typeof piece !== 'object') return null;
  const level = ctx.level?.(piece.level);
  const elevation = num(level?.elevation) ? level.elevation : 0;
  if (kind === 'level' && ring(piece.outline))
    return polygon(piece.outline, (num(piece.elevation) ? piece.elevation : elevation) + .03);
  if (kind === 'wall') {
    const [a, b] = piece.from ? [piece.from, piece.to] : (Array.isArray(piece.joints) ? piece.joints : []).map(id => ctx.joint?.(id));
    const length = point(a) && point(b) ? Math.hypot(b[0] - a[0], b[1] - a[1]) : 0;
    if (length) {
      const height = num(piece.height) ? piece.height : num(level?.ceiling) ? level.ceiling : 9;
      return new THREE.BoxGeometry(length, height, Math.max(.08, num(piece.thickness) ? piece.thickness : .08))
        .rotateY(Math.atan2(b[1] - a[1], b[0] - a[0])).translate((a[0] + b[0]) / 2, elevation + height / 2, -(a[1] + b[1]) / 2);
    }
  }
  if (kind === 'opening') {
    const wall = ctx.wall?.(piece.wall);
    const length = wall && point(wall.from) && point(wall.to) ? Math.hypot(wall.to[0] - wall.from[0], wall.to[1] - wall.from[1]) : 0;
    if (length && [piece.at, piece.width, piece.sill, piece.head].every(num) && piece.width > 0 && piece.head > piece.sill) {
      const at = wall.from.map((v, i) => v + (wall.to[i] - v) * piece.at / length);
      const floor = ctx.level?.(wall.level)?.elevation;
      return new THREE.BoxGeometry(piece.width, piece.head - piece.sill, OPENING_DEPTH)
        .rotateY(Math.atan2(wall.to[1] - wall.from[1], wall.to[0] - wall.from[0]))
        .translate(at[0], (num(floor) ? floor : 0) + (piece.head + piece.sill) / 2, -at[1]);
    }
  }
  if (kind === 'room' && ring(piece.polygon)) return polygon(piece.polygon, elevation + .04);
  if (kind === 'fixture' && point(piece.at)) {
    const z = elevation + (piece.surface === 'ceiling' ? (num(level?.ceiling) ? level.ceiling : 9) : piece.surface === 'wall' ? 4 : .15);
    return new THREE.BoxGeometry(.5, .3, .5).translate(piece.at[0], z, -piece.at[1]);
  }
  if (kind === 'roof' && Array.isArray(piece.rect) && piece.rect.length === 4 && piece.rect.every(num)) {
    const vertices = roofMesh([piece]).positions;
    if (vertices?.length) {
      const positions = new Float32Array(vertices.length);
      for (let i = 0; i < vertices.length; i += 3) {
        positions[i] = vertices[i]; positions[i + 1] = vertices[i + 2]; positions[i + 2] = -vertices[i + 1];
      }
      return new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(positions, 3));
    }
  }
  // Every other shape (and a proposal's model piece: an area, a host or a position).
  const area = piece.area || piece.polygon;
  if (ring(area)) return polygon(area, num(piece.plate) ? piece.plate : elevation + .03);
  const at = piece.host && ctx.host ? ctx.host(piece.host, num(piece.offset) ? piece.offset : 0) : piece.position;
  if (point(at)) return new THREE.BoxGeometry(.8, .8, .8).translate(at[0], num(at[2]) ? at[2] : elevation + .4, -at[1]);
  return null;
}

// The ghost's fill and dashed edge. The group holds both; `mesh` is the fill (it takes picks).
export function ghostGroup(geometry) {
  const group = new THREE.Group();
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: GHOST_COLOR, transparent: true,
    opacity: GHOST_FILL, depthWrite: false, side: THREE.DoubleSide }));
  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineDashedMaterial({
    color: GHOST_COLOR, dashSize: .4, gapSize: .25, transparent: true, opacity: GHOST_EDGE, depthWrite: false }));
  edge.computeLineDistances(); group.add(mesh, edge);
  return { group, mesh };
}

// How a ghost fades as its round lands: left runs from 1 to 0.
export function fadeGhost(group, left) {
  group.traverse(object => { if (object.material) object.material.opacity = (object.isMesh ? GHOST_FILL : GHOST_EDGE) * left; });
}
