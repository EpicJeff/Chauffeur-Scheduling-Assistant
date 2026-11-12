import * as THREE from 'three';
import { FT } from '../twin_generator.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { pieceGhostGeometry, ghostGroup, fadeGhost } from './ghost_geometry.js';

// Like flags.js's proposals, these are an editor layer in building feet.
// Each event adds geometry without rebuilding the saved house.
export function createBuildGhosts(view) {
  const root = new THREE.Group(), pieces = new Map(), levels = new Map(), walls = new Map(), frames = new Map();
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
  // Where the engine will put a building that is not in the plan yet: right of every building,
  // as twin_build._base places a new one. Used only when no stage event sent the frame.
  function fallbackFrame(id) {
    let right = -Infinity;
    for (const b of view.plan?.buildings || []) {
      const a = (b.rotation || 0) * Math.PI / 180, px = (b.position || [0, 0])[0];
      for (const level of b.levels || []) for (const p of level.outline || [])
        right = Math.max(right, Math.cos(a) * p[0] - Math.sin(a) * p[1] + px);
    }
    return { id, position: Number.isFinite(right) ? [right + 10, 0] : [0, 0], rotation: 0, base: 0, levels: [] };
  }
  // The building's frame: the scene's own once the first round lands, else the one the engine sent.
  const frameOf = id => view.plan?.buildings?.find(b => b.id === id) || frames.get(id) || fallbackFrame(id);
  function geometry(event, building) {
    const bid = event.building;
    const level = id => levels.get(key(bid, id)) || building.levels?.find(l => l.id === id);
    const wall = id => walls.get(key(bid, id)) || building.walls?.find(w => w.id === id);
    return pieceGhostGeometry(event.kind, event.piece, { level, wall });
  }
  function add(event) {
    if (event?.type === 'stage' && event.frame?.id) { frames.set(event.frame.id, event.frame); return; }
    if (event?.type !== 'piece' || pieces.has(event.seq)) return;
    // A streamed piece is the reply as written: one that cannot be drawn is skipped, never thrown,
    // so the poll that carried it still advances.
    try {
      const p = event.piece;
      if (!p || typeof p !== 'object') throw new Error('the piece is not an object');
      const b = frameOf(event.building);
      if (event.kind === 'level' && typeof p.id === 'string') levels.set(key(b.id, p.id), p);
      if (event.kind === 'wall' && typeof p.id === 'string') walls.set(key(b.id, p.id), p);
      const shape = geometry(event, b);
      if (!shape) throw new Error('the piece has too little to draw');
      const { group } = ghostGroup(shape), position = b.position || [0, 0];
      group.scale.setScalar(FT); group.rotation.y = (b.rotation || 0) * Math.PI / 180;
      group.position.set(position[0] * FT, ((b.base || 0) + buildingGround(view.plan, b)) * FT, -position[1] * FT);
      root.add(group);
      pieces.set(event.seq, { group, step: event.step, level: p.level || (event.kind === 'level' ? p.id : null), building: b.id });
    } catch (error) {
      console.warn(`Skipped a ${event.kind || 'piece'} the build could not draw (${error.message}).`);
    }
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
        fadeGhost(row.group, left);
      }
      if (left && rows.some(([seq]) => pieces.has(seq))) requestAnimationFrame(fade);
    }
    requestAnimationFrame(fade);
  }
  // clear() takes every ghost away; clear(step) those of one step; clear(step, after) only that
  // step's ghosts after the seq (a read that started over keeps the floors read before it).
  function clear(step, after) {
    for (const [seq, row] of pieces) if (!step || (row.step === step && !(seq <= after))) remove(seq);
    if (!step || !pieces.size) { levels.clear(); walls.clear(); }
    if (!step) frames.clear();
  }
  function sync() {
    for (const row of pieces.values()) {
      const floor = row.level && view.groups?.levels?.[`${row.building}:${row.level}`];
      row.group.visible = !floor || floor.visible;
    }
  }
  return { add, settle, clear, sync, count: () => pieces.size, seqs: () => [...pieces.keys()] };
}
