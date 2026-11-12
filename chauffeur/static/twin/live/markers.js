import * as THREE from 'three';

import { kindOf, stateLabel } from './kinds.js';
import { markerOnColor, markerInk, twinMarkerOff, twinMarkerRing, twinMarkerUnavailable,
  twinMarkerUnavailableText, twinAttention, twinAttentionRing, twinDanger, twinSelectedText, twinText } from '../palette.js';

export function markerState(kind, state, attributes, entityId = '') {
  const resolved = kindOf({kind, entity_id: entityId});
  return { look: resolved.look({state, attributes}), color: markerOnColor(resolved.id, {state, attributes}),
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
export function markerTexture(kind, look, count = null, color = markerOnColor(kind)) {
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 96;
  const ctx = canvas.getContext('2d');
  // Faults keep attention semantics (badges, hidden-floor pins), with their specified red disc.
  ctx.fillStyle = { on: color, off: twinMarkerOff, attention: color === twinDanger ? color : twinAttention,
    unavailable: twinMarkerUnavailable }[look];
  ctx.beginPath(); ctx.arc(48, 48, 42, 0, Math.PI * 2); ctx.fill();
  if (look !== 'unavailable') {
    ctx.strokeStyle = look === 'attention' ? twinAttentionRing : twinMarkerRing;
    ctx.lineWidth = 3; ctx.stroke();
  }
  ctx.fillStyle = look === 'on' ? markerInk(color) : look === 'attention' ? twinSelectedText
    : look === 'unavailable' ? twinMarkerUnavailableText : twinText;
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

// Only colour-bearing device textures enter the bounded LRU. Off/unavailable/count
// textures ignore state colours. Owners pin entries even when their sprites are hidden.
export function markerTextureCache(limit = 48) {
  const textures = new Map(), colors = new Map(), owners = new Map();
  function prune() {
    for (const [key, entry] of colors) {
      if (colors.size <= limit) break;
      if (entry.users) continue;
      colors.delete(key); textures.delete(key); entry.texture.dispose();
    }
  }
  return {
    assign(sprite, kind, look, count = null, color = markerOnColor(kind)) {
      if (kind === 'light' && look === 'on') {
        // Sixteen-channel steps, with 255 retained as the top bucket (pure primaries).
        color = '#' + color.slice(1).match(/../g).map(v =>
          Math.min(255, Math.round(parseInt(v, 16) / 16) * 16).toString(16).padStart(2, '0')).join('');
      }
      const keyed = count === null && (look === 'on' || look === 'attention');
      const key = JSON.stringify([kind, look, count, keyed ? color : null]);
      let entry = textures.get(key);
      if (!entry) {
        entry = {texture: markerTexture(kind, look, count, color), users: 0};
        textures.set(key, entry);
      }
      if (keyed) { colors.delete(key); colors.set(key, entry); }
      const previous = owners.get(sprite);
      if (previous !== entry) {
        if (previous) previous.users--;
        entry.users++; owners.set(sprite, entry);
      }
      // Re-key before disposing anything: no sprite ever holds an evicted map.
      sprite.material.map = entry.texture;
      prune();
      return entry.texture;
    },
    dispose() {
      for (const sprite of owners.keys()) sprite.material.map = null;
      owners.clear();
      textures.forEach(entry => entry.texture.dispose()); textures.clear(); colors.clear();
    },
  };
}
