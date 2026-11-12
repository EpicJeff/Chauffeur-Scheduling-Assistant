import * as THREE from 'three';

import { kindOf, stateLabel } from './kinds.js';

export function markerState(kind, state, attributes, entityId = '') {
  return { look: kindOf({kind, entity_id: entityId}).look({state, attributes}),
    label: stateLabel(kind, state, attributes) };
}

export function levelOfDetail(markers, pxPerFoot) {
  if (pxPerFoot >= 7) return { badges: [], markers: markers.map(m => m.device_id), labels: pxPerFoot >= 20 };
  const rooms = new Map();
  for (const marker of markers) {
    const key = JSON.stringify([marker.building, marker.room]);
    if (!rooms.has(key)) rooms.set(key, { building: marker.building, room: marker.room, count: 0, attention: false });
    const badge = rooms.get(key);
    ++badge.count;
    badge.attention ||= marker.look === 'attention';
  }
  return { badges: [...rooms.values()], markers: [], labels: false };
}

// Single-link components, with a wider release distance for yesterday's neighbours.
// Sorting makes both the greedy sweep and the keys independent of placement order.
export function clusterMarkers(points, previous = new Map()) {
  const sorted = [...points].sort((a, b) => String(a.id).localeCompare(String(b.id)));
  const parent = sorted.map((_, i) => i);
  const find = i => parent[i] === i ? i : (parent[i] = find(parent[i]));
  for (let i = 0; i < sorted.length; i++) for (let j = i + 1; j < sorted.length; j++) {
    const a = sorted[i], b = sorted[j], distance = Math.hypot(a.x - b.x, a.y - b.y);
    const held = previous.has(a.id) && previous.get(a.id) === previous.get(b.id);
    if (distance < 40 || held && distance <= 48) parent[find(j)] = find(i);
  }
  const groups = new Map();
  sorted.forEach((p, i) => {
    const key = sorted[find(i)].id;
    if (!groups.has(key)) groups.set(key, {key, ids: [], x: 0, y: 0, attention: false});
    const group = groups.get(key);
    group.ids.push(p.id); group.x += p.x; group.y += p.y; group.attention ||= p.look === 'attention';
  });
  return [...groups.values()].map(g => ({...g, x: g.x / g.ids.length, y: g.y / g.ids.length}));
}

// All textures are owned by the mounted layer's cache, not by its sprites.
export function markerTexture(kind, look, count = null) {
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 96;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = { on: '#e3d3ab', off: '#363b43', attention: '#edaa48', unavailable: '#686e77' }[look];
  ctx.beginPath(); ctx.arc(48, 48, 42, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = look === 'attention' ? '#fff0d4' : '#e3d3ab'; ctx.lineWidth = 3; ctx.stroke();
  ctx.fillStyle = look === 'on' || look === 'attention' ? '#1c1710' : '#f0e6cf';
  ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 4; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  if (count !== null) {
    ctx.font = 'bold 38px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(String(count), 48, 48);
  } else kindOf({kind}).icon(ctx);
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export function markerSprite(texture) {
  const material = new THREE.SpriteMaterial({ map: texture, depthTest: false, depthWrite: false, toneMapped: false });
  const sprite = new THREE.Sprite(material); sprite.renderOrder = 20;
  return sprite;
}
