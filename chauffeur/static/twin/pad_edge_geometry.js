import * as THREE from 'three';
import { boxGeometry } from './twin_generator.js';
import { groundAt, segmentIntersection } from './twin_ground.js';
import { retainingWallGeometry } from './twin_retaining_wall.js';
import { buildRailing } from './fence_geometry.js';

// Emit only additions: the legacy wall's buffers and UVs are never altered.
export function buildPadEdge(plan, pad, index, emit) {
  const edge = pad.edges?.[index];
  if (edge?.edge !== 'sharp') return;
  const a = pad.polygon[index], b = pad.polygon[(index + 1) % pad.polygon.length];
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (!length) return;
  const axis = [(b[0] - a[0]) / length, (b[1] - a[1]) / length];
  const winding = Math.sign(pad.polygon.reduce((s, p, i) => {
    const q = pad.polygon[(i + 1) % pad.polygon.length]; return s + p[0] * q[1] - p[1] * q[0];
  }, 0));
  const out = [axis[1] * winding, -axis[0] * winding];
  const at = (u, v, h) => [a[0] + axis[0] * u + out[0] * v, a[1] + axis[1] * u + out[1] * v, h];
  const rail = (value, start, end, embed = 0, skipStart = false) => buildRailing(start, end, value,
    g => emit(g, 'rail', 'black_metal', value.materials?.rail), embed, skipStart);
  if (edge.wall) {
    const wall = edge.wall, runs = [], same = (a, b) => Math.hypot(...a.map((v, i) => v - b[i])) < 1e-5;
    if (wall.cap || wall.rail) {
      // Reuse the wall's one-sided layer samples, higher-side choice and cuts.
      const body = retainingWallGeometry(plan, pad, index), p = body.attributes.position;
      for (let start = 0; start < p.count; start += 36) {
        const ring = [24, 25, 26, 29].map(k => [p.getX(start + k), -p.getZ(start + k), p.getY(start + k)]);
        const cap = wall.cap, thickness = cap ? (cap.thickness_in ?? 2) / 12 : 0;
        const middle = k => [0, 1].map(j => (ring[k][j] + ring[3 - k][j]) / 2);
        if (wall.rail) {
          const a = [...middle(0), ring[0][2] + thickness], b = [...middle(1), ring[1][2] + thickness], last = runs.at(-1);
          const direction = (a, b) => { const d = b.map((v, i) => v - a[i]), length = Math.hypot(...d); return d.map(v => v / length); };
          // Keep straight runs together; follow any change of height/side in
          // layered terrain, without stamping posts at every terrain sample.
          if (last && same(last[1], a) && same(direction(...last), direction(a, b))) last[1] = b;
          else runs.push([a, b]);
        }
        if (!cap) continue;
        const overhang = (cap.overhang_in ?? 1) / 12;
        // Ring order may reverse where the lower side changes.
        const n = [ring[3][0] - ring[0][0], ring[3][1] - ring[0][1]], width = Math.hypot(...n);
        const expanded = ring.map((q, k) => [q[0] + n[0] / width * overhang * (k < 2 ? -1 : 1),
          q[1] + n[1] / width * overhang * (k < 2 ? -1 : 1), q[2]]);
        emit(capPrism(expanded, thickness), 'cap', 'patio_concrete', wall.materials?.cap);
      }
      body.dispose();
    }
    runs.forEach(([a, b], i) => rail(wall.rail, a, b, 0, i > 0 && same(runs[i - 1][1], a)));
    return;
  }
  const stair = edge.stair;
  if (!stair) return;
  const samples = Math.max(1, Math.ceil(length));
  let low = pad.height;
  for (const p of groundSamples(plan, at(0, 1e-5, 0), at(length, 1e-5, 0))) low = Math.min(low, groundAt(plan, p[0], p[1]));
  const drop = pad.height - low, count = Math.max(1, Math.ceil(drop / ((stair.riser_in ?? 7) / 12)));
  const riser = drop / count, tread = (stair.tread_in ?? 11) / 12, run = tread * count;
  // Sample the whole footprint, including the low ground at both open ends.
  // All blocks bury their closed bottoms below the lowest of these samples.
  let footing = low - .5;
  for (let v = 0; v <= Math.ceil(run); v++) for (const p of groundSamples(plan, at(0, run * v / Math.ceil(run), 0), at(length, run * v / Math.ceil(run), 0)))
    footing = Math.min(footing, groundAt(plan, p[0], p[1]) - .5);
  for (let u = 0; u <= samples; u++) for (const p of groundSamples(plan, at(length * u / samples, 0, 0), at(length * u / samples, run, 0)))
    footing = Math.min(footing, groundAt(plan, p[0], p[1]) - .5);
  const place = (width, height, depth, u, v, y) => {
    const p = at(u, v, y);
    return boxGeometry(width, height, depth).rotateY(Math.atan2(axis[1], axis[0])).translate(p[0], y, -p[1]);
  };
  const hasTreads = stair.treads !== false, slab = hasTreads ? 1.5 / 12 : 0, nose = 1 / 12;
  for (let i = 0; i < count; i++) {
    const top = pad.height - i * riser, bodyTop = top - slab;
    emit(place(length, bodyTop - footing, tread, length / 2, (i + .5) * tread, (bodyTop + footing) / 2),
      'riser', 'patio_concrete', stair.materials?.riser);
    if (hasTreads) emit(place(length + 2 * nose, slab, tread + nose, length / 2, (i + .5) * tread + nose / 2, top - slab / 2),
      'tread', 'patio_concrete', stair.materials?.tread);
  }
  // Posts stand a post's width inside the flight, so none hangs off an end or the bottom step.
  const inset = Math.min(1.5 / 12, length / 4, run / 4);
  if (stair.rail) for (const u of [inset, length - inset]) rail(stair.rail,
    at(u, inset, pad.height), at(u, run - inset, low + riser), riser);
}

// Include both sides of layer boundaries: a narrow, sharp depression between
// the one-foot terrain samples must still set the flight's drop and footing.
function groundSamples(plan, a, b) {
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]), cuts = [0, 1];
  if (!length) return [a];
  for (let d = 1; d < length; d++) cuts.push(d / length);
  for (const layer of plan.site?.terraces || []) layer.polygon.forEach((p, i) => {
    const hit = segmentIntersection(a, b, p, layer.polygon[(i + 1) % layer.polygon.length]);
    if (hit) {
      const t = Math.hypot(hit[0] - a[0], hit[1] - a[1]) / length;
      cuts.push(Math.max(0, t - 1e-7), Math.min(1, t + 1e-7));
    }
  });
  return cuts.map(t => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
}

function capPrism(ring, thickness) {
  const positions = [], uvs = [];
  const quad = (points, horizontal = false) => {
    const [a, b] = points, dx = b[0] - a[0], dy = b[1] - a[1], d = Math.hypot(dx, dy);
    for (const i of [0, 1, 2, 0, 2, 3]) {
      const p = points[i]; positions.push(p[0], p[2], -p[1]);
      uvs.push(horizontal ? p[0] : (p[0] * dx + p[1] * dy) / d, horizontal ? -p[1] : p[2]);
    }
  };
  const top = ring.map(p => [p[0], p[1], p[2] + thickness]);
  for (let i = 0; i < 4; i++) { const j = (i + 1) % 4; quad([ring[i], ring[j], top[j], top[i]]); }
  quad(top, true); quad([...ring].reverse(), true);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2)); g.computeVertexNormals(); return g;
}
