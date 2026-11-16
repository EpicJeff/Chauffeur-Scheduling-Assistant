import * as THREE from 'three';
import { boxGeometry } from './twin_generator.js';

// Feet throughout, before the yard drapes each piece and batches by material.
export function buildFence(fence, emit) {
  const height = fence.height || 6, type = fence.type;
  const post = type === 'metal' ? 2 / 12 : type === 'panel' ? 2.5 / 12 : 4 / 12;
  for (let i = 0; i < fence.polyline.length - 1; i++) {
    const a = fence.polyline[i], b = fence.polyline[i + 1], dx = b[0] - a[0], dy = b[1] - a[1];
    const length = Math.hypot(dx, dy), angle = Math.atan2(dy, dx);
    if (!length) continue;
    const place = (geometry, part, d, ...seed) => emit(geometry.rotateY(angle)
      .translate(a[0] + dx * d / length, 0, -a[1] - dy * d / length), part, i, ...seed);
    const bays = Math.max(1, Math.ceil(length / (type === 'metal' ? 6 : 8))), bay = length / bays;
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
