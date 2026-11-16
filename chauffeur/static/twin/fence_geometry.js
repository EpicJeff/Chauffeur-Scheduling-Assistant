import * as THREE from 'three';
import { boxGeometry } from './twin_generator.js';

// Feet throughout, before the yard drapes each piece and batches by material.
export function buildFence(fence, emit, { maxBay } = {}) {
  const height = fence.height || 6, type = fence.type;
  const post = type === 'metal' || type === 'cable' ? 2 / 12 : type === 'panel' ? 2.5 / 12 : 4 / 12;
  for (let i = 0; i < fence.polyline.length - 1; i++) {
    const a = fence.polyline[i], b = fence.polyline[i + 1], dx = b[0] - a[0], dy = b[1] - a[1];
    const length = Math.hypot(dx, dy), angle = Math.atan2(dy, dx);
    if (!length) continue;
    const place = (geometry, part, d, ...seed) => emit(geometry.rotateY(angle)
      .translate(a[0] + dx * d / length, 0, -a[1] - dy * d / length), part, i, ...seed);
    const bays = Math.max(1, Math.ceil(length / (maxBay ?? (type === 'metal' ? 6 : 8)))), bay = length / bays;
    for (let n = 0; n <= bays; n++) {
      const top = height + (type === 'picket' ? .2 : 0);
      place(boxGeometry(post, top, post).translate(0, top / 2, 0), 'posts', n * bay, n);
      if (type === 'picket') place(boxGeometry(post + 1 / 12, 1 / 12, post + 1 / 12)
        .translate(0, top + 1 / 24, 0), 'posts', n * bay, n, 'cap');
    }
    if (type === 'panel') {
      const bottom = Math.min(1 / 12, height * .15), railHeight = Math.min(1 / 12, height * .15);
      for (let n = 0; n < bays; n++) {
        const width = Math.max(.001, bay - Math.min(post, bay * .8));
        place(boxGeometry(width, height - bottom - railHeight, .04, Math.max(1, Math.ceil(width / .5)))
          .translate(0, (height + bottom - railHeight) / 2, 0), 'boards', (n + .5) * bay, n);
      }
      place(boxGeometry(length, railHeight, post, Math.max(1, Math.ceil(length / .5)))
        .translate(0, height - railHeight / 2, 0), 'rails', length / 2, 'top');
    } else if (type === 'cable') {
      place(boxGeometry(length, 1.5 / 12, post).translate(0, height - 1.5 / 24, 0), 'rails', length / 2, 'top');
      const rows = Math.max(1, Math.ceil((height - .3) / (3 / 12)));
      for (let k = 1; k < rows; k++) place(boxGeometry(length, 1 / 48, 1 / 48)
        .translate(0, height * k / rows, 0), 'boards', length / 2, k);
    } else if (type === 'metal') {
      const bottom = Math.min(3 / 12, height * .15), railHeight = Math.min(1.5 / 12, height * .1);
      const low = bottom + railHeight, top = height - railHeight;
      for (const [y, label] of [[bottom + railHeight / 2, 'low'], [height - railHeight / 2, 'high']])
        place(boxGeometry(length, railHeight, 1 / 12, Math.max(1, Math.ceil(length / .5)))
          .translate(0, y, 0), 'rails', length / 2, label);
      for (let n = 0; n < bays; n++) {
        const count = Math.max(1, Math.round(bay / (4 / 12)));
        for (let k = 0; k < count; k++) place(boxGeometry(5 / 96, top - low, 5 / 96)
          .translate(0, (top + low) / 2, 0), 'boards', n * bay + (k + .5) * bay / count, n, k);
      }
    } else {
      const count = Math.max(1, Math.round(length / .5)), width = Math.min(3.5 / 12, length * .8), bottom = Math.min(2 / 12, height * .15);
      const tip = Math.min(.25, (height - bottom) / 3);
      const shape = new THREE.Shape();
      shape.moveTo(-width / 2, bottom); shape.lineTo(width / 2, bottom);
      shape.lineTo(width / 2, height - tip); shape.lineTo(0, height); shape.lineTo(-width / 2, height - tip); shape.closePath();
      for (let n = 0; n < count; n++) place(new THREE.ExtrudeGeometry(shape, { depth: .75 / 12, bevelEnabled: false, steps: 1 })
        .translate(0, 0, -.75 / 24), 'boards', (n + .5) * length / count, n);
      for (const [y, label] of [[height * .3, 'low'], [height * .75, 'high']])
        place(boxGeometry(length, 3 / 12, 1.5 / 12, Math.max(1, Math.ceil(length / .5)))
          .translate(0, y, .1), 'rails', length / 2, label);
    }
  }
}

// Same metal/panel construction as fences, with vertical posts and infill
// sheared onto a sloped flight. All coordinates and texture units are feet.
export function buildRailing(a, b, rail, emit, embed = 0, skipStartPost = false) {
  const dx = b[0] - a[0], dy = b[1] - a[1], length = Math.hypot(dx, dy);
  if (length < 1e-8) return;
  buildFence({ polyline: [[0, 0], [length, 0]], height: (rail.height_in ?? 36) / 12,
    type: { pickets: 'metal', cable: 'cable', panel: 'panel' }[rail.style] }, (geometry, part, segment, postIndex) => {
    if (skipStartPost && part === 'posts' && postIndex === 0) { geometry.dispose(); return; }
    const p = geometry.attributes.position;
    for (let i = 0; i < p.count; i++) p.setY(i, p.getY(i) - (part === 'posts' && p.getY(i) < 1e-6 ? embed : 0)
      + a[2] + (b[2] - a[2]) * Math.max(0, Math.min(1, p.getX(i) / length)));
    geometry.rotateY(Math.atan2(dy, dx)).translate(a[0], 0, -a[1]);
    geometry.computeVertexNormals(); emit(geometry);
  }, { maxBay: 4 });
}
