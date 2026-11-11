import * as THREE from 'three';
import { FT, polygon } from '../twin_generator.js';
import { roofMesh } from '../twin_roof.js';
import { groundAt } from '../twin_ground.js';

// Like flags.js's proposals, these are an editor layer in building feet.
// Each event adds geometry without rebuilding the saved house.
export function createBuildGhosts(view) {
  const root = new THREE.Group(), pieces = new Map(), levels = new Map(), walls = new Map(), queued = new Map();
  root.name = 'editor-build-ghosts'; view.scene.add(root);
  const key = (building, id) => `${building}:${id}`;
  function remove(seq) {
    const row = pieces.get(seq);
    if (!row) return;
    row.group.removeFromParent();
    row.group.traverse(o => { o.geometry?.dispose();
      for (const material of [].concat(o.material || [])) material.dispose(); });
    pieces.delete(seq);
  }
  function geometry(event, building) {
    const p = event.piece, bid = event.building;
    const level = levels.get(key(bid, p.level)) || building.levels?.find(l => l.id === p.level);
    const elevation = level?.elevation || 0;
    if (event.kind === 'level') return p.outline?.length >= 3 ? polygon(p.outline, p.elevation + .03) : null;
    if (event.kind === 'wall') {
      const [a, b] = [p.from, p.to], height = p.height ?? level?.ceiling ?? 9;
      if (!a || !b) return null;
      return new THREE.BoxGeometry(Math.hypot(b[0] - a[0], b[1] - a[1]), height, Math.max(.08, p.thickness || .08))
        .rotateY(Math.atan2(b[1] - a[1], b[0] - a[0]))
        .translate((a[0] + b[0]) / 2, elevation + height / 2, -(a[1] + b[1]) / 2);
    }
    if (event.kind === 'opening') {
      const wall = walls.get(key(bid, p.wall)) || building.walls?.find(w => w.id === p.wall);
      if (!wall) return null;
      const length = Math.hypot(wall.to[0] - wall.from[0], wall.to[1] - wall.from[1]);
      if (!length) return null;
      const at = wall.from.map((v, i) => v + (wall.to[i] - v) * p.at / length);
      const floor = levels.get(key(bid, wall.level)) || building.levels?.find(l => l.id === wall.level);
      return new THREE.BoxGeometry(p.width, p.head - p.sill, .18)
        .rotateY(Math.atan2(wall.to[1] - wall.from[1], wall.to[0] - wall.from[0]))
        .translate(at[0], (floor?.elevation || 0) + (p.head + p.sill) / 2, -at[1]);
    }
    if (event.kind === 'room') return p.polygon?.length >= 3 ? polygon(p.polygon, elevation + .04) : null;
    if (event.kind === 'fixture') {
      if (!p.at) return null;
      const z = elevation + (p.surface === 'ceiling' ? level?.ceiling ?? 9 : p.surface === 'wall' ? 4 : .15);
      return new THREE.BoxGeometry(.5, .3, .5).translate(p.at[0], z, -p.at[1]);
    }
    if (event.kind === 'roof') {
      const roof = roofMesh([p]), vertices = roof.positions;
      const positions = new Float32Array(vertices.length);
      for (let i = 0; i < vertices.length; i += 3) {
        positions[i] = vertices[i]; positions[i + 1] = vertices[i + 2]; positions[i + 2] = -vertices[i + 1];
      }
      return new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(positions, 3));
    }
    return null;
  }
  function add(event) {
    if (event.type !== 'piece' || pieces.has(event.seq)) return;
    const b = view.plan?.buildings?.find(b => b.id === event.building);
    if (!b) { queued.set(event.seq, event); return; }
    queued.delete(event.seq);
    if (event.kind === 'level') levels.set(key(b.id, event.piece.id), event.piece);
    if (event.kind === 'wall') walls.set(key(b.id, event.piece.id), event.piece);
    const shape = geometry(event, b);
    if (!shape) return;
    const group = new THREE.Group(), position = b.position || [0, 0];
    group.scale.setScalar(FT); group.rotation.y = (b.rotation || 0) * Math.PI / 180;
    group.position.set(position[0] * FT, ((b.base || 0) + groundAt(view.plan, ...position)) * FT, -position[1] * FT);
    const mesh = new THREE.Mesh(shape, new THREE.MeshBasicMaterial({ color: '#38bdf8', transparent: true,
      opacity: .35, depthWrite: false, side: THREE.DoubleSide }));
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(shape), new THREE.LineDashedMaterial({
      color: '#38bdf8', dashSize: .4, gapSize: .25, transparent: true, opacity: .8, depthWrite: false }));
    edge.computeLineDistances(); group.add(mesh, edge); root.add(group);
    pieces.set(event.seq, { group, step: event.step, level: event.piece.level || (event.kind === 'level' ? event.piece.id : null), building: b.id });
  }
  function settle(round) {
    if (round.kind !== 'build') return;
    const rows = [...pieces].filter(([, row]) => row.step === round.step?.id && !row.settling);
    for (const [, row] of rows) row.settling = true;
    if (!rows.length) return;
    const started = performance.now(), duration = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : 220;
    function fade(now) {
      const left = duration ? Math.max(0, 1 - (now - started) / duration) : 0;
      for (const [seq, row] of rows) {
        if (!pieces.has(seq)) continue;
        if (!left) { remove(seq); continue; }
        row.group.traverse(o => { if (o.material) o.material.opacity = (o.isMesh ? .35 : .8) * left; });
      }
      if (left && rows.some(([seq]) => pieces.has(seq))) requestAnimationFrame(fade);
    }
    requestAnimationFrame(fade);
  }
  function clear(step) {
    for (const [seq, row] of pieces) if (!step || row.step === step) remove(seq);
    for (const [seq, row] of queued) if (!step || row.step === step) queued.delete(seq);
    if (!step || !pieces.size) { levels.clear(); walls.clear(); }
  }
  function sync() {
    for (const event of queued.values()) add(event);
    for (const row of pieces.values()) {
      const floor = row.level && view.groups?.levels?.[`${row.building}:${row.level}`];
      row.group.visible = !floor || floor.visible;
    }
  }
  return { add, settle, clear, sync, count: () => pieces.size, seqs: () => [...pieces.keys()] };
}
