import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

// Feet, with the pivot at the head. All sections move as one overhead door.
export function buildGarageDoor(opening, { material, inward = -1, setback = .4 } = {}) {
  const width = opening.width, height = opening.head - opening.sill;
  const sections = Math.max(3, Math.round(height / (21 / 12)));
  const columns = opening.panels > 1 ? opening.panels : Math.max(2, Math.round(width / 4));
  const style = opening.style || 'raised', depth = 2 / 12, joint = .025, frame = .12;
  const group = new THREE.Group(), parts = new Map();
  group.position.y = height;
  group.userData.garageOpening = { opening: opening.id, sections, columns, inward, setback, height };
  const box = (part, x, y, w, h, d = depth, z = 0) => {
    if (!(w > 0 && h > 0 && d > 0)) return;
    const geometry = new THREE.BoxGeometry(w, h, d).toNonIndexed();
    geometry.translate(x, y, z);
    if (!parts.has(part)) parts.set(part, []);
    parts.get(part).push(geometry);
  };
  const cellWidth = (width - .16) / columns, sectionHeight = (height - .16) / sections;
  for (let row = 0; row < sections; row++) {
    const y = -.08 - sectionHeight * (row + .5), h = sectionHeight - joint;
    const glazed = style === 'full_view' || row === 0 && opening.lites === 'top';
    if (style === 'flat' && !glazed) {
      box('garage_door', 0, y, width - .16, h);
      continue;
    }
    for (let column = 0; column < columns; column++) {
      const x = -(width - .16) / 2 + cellWidth * (column + .5), w = cellWidth - joint;
      const part = style === 'full_view' ? 'window_frame' : 'garage_door';
      if (glazed || style === 'raised') {
        // A shallow inset bounded by real rails and stiles, on both faces.
        const rail = glazed ? frame : Math.min(.22, w / 5, h / 5), groove = Math.min(.1, rail / 2);
        for (const side of [-1, 1]) {
          box(part, x + side * (w - rail) / 2, y, rail, h);
          box(part, x, y + side * (h - rail) / 2, w - 2 * rail, rail);
        }
        box(glazed ? 'pane' : part, x, y, w - 2 * rail, h - 2 * rail,
          glazed ? .025 : depth - .11);
        // The raised field stands proud of a groove round it.
        if (!glazed) box(part, x, y, w - 2 * rail - 2 * groove, h - 2 * rail - 2 * groove, depth - .02);
      } else {
        const boards = Math.max(2, Math.round(w / .5));
        for (let i = 0; i < boards; i++) box(part, x - w / 2 + w * (i + .5) / boards, y, w / boards - .035, h);
      }
    }
  }
  if (style === 'carriage') {
    box('garage_door', 0, -height / 2, .3, height - .16, .07, depth / 2 + .035);
    for (const side of [-1, 1]) box('garage_door', side * (width - .16 + .3) / 4,
      -.08 - sectionHeight, (width - .16 - .3) / 2, .3, .07, depth / 2 + .035);
  }
  for (const [part, geometries] of parts) {
    const geometry = mergeGeometries(geometries);
    geometries.forEach(g => g.dispose());
    geometry.userData.bakeExcluded = true;
    const mesh = new THREE.Mesh(geometry, material(part));
    mesh.userData.garageDoor = true; mesh.userData.part = part;
    mesh.castShadow = !mesh.material.transparent; mesh.receiveShadow = true;
    group.add(mesh);
  }
  return group;
}

export function garagePose(group, open) {
  const { inward, setback } = group.userData.garageOpening;
  group.rotation.x = open ? -inward * Math.PI / 2 : 0;
  group.position.z = open ? inward * setback : 0;
  group.updateMatrixWorld(true);
}

export function garageEntity(layout, building, opening) {
  return (layout.devices || layout.markers || []).find(device => device.kind === 'garage'
    && device.entity_id?.startsWith('cover.') && device.building === building
    && device.host?.opening === opening)?.entity_id;
}
