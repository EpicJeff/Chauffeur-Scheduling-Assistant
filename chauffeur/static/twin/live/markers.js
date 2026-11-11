import * as THREE from 'three';

const CONTACTS = ['door', 'window', 'opening', 'garage_door'];

// entityId is optional: an alarm panel is known by its domain (the catalogue may not kind it 'alarm').
export function markerState(kind, state, attributes, entityId = '') {
  const attrs = attributes || {}, value = String(state ?? 'unknown');
  // A door or window contact is on when open: it reads open or closed, and open wants attention.
  const contact = kind === 'sensor' && CONTACTS.includes(attrs.device_class) && ['on', 'off'].includes(value);
  const label = contact ? (value === 'on' ? 'open' : 'closed')
    : value + (kind === 'sensor' && attrs.unit_of_measurement ? ` ${attrs.unit_of_measurement}` : '');
  if (['unknown', 'unavailable'].includes(value)) return { look: 'unavailable', label };
  const alarm = kind === 'alarm' || String(entityId).startsWith('alarm_control_panel.');
  const attention = kind === 'lock' && ['unlocked', 'unlocking', 'open', 'opening', 'jammed'].includes(value)
    || kind === 'garage' && ['open', 'opening'].includes(value)
    || alarm && ['triggered', 'pending', 'arming'].includes(value)
    || kind === 'sensor' && ['smoke', 'moisture', 'gas'].includes(attrs.device_class) && value === 'on'
    || contact && value === 'on';
  const off = ['off', 'closed', 'locked', 'idle', 'standby'].includes(value) || alarm && value === 'disarmed';
  return { look: attention ? 'attention' : off ? 'off' : 'on', label };
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

// All textures are owned by the mounted layer's cache, not by its sprites.
export function markerTexture(kind, look, count = null) {
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 96;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = { on: '#e3d3ab', off: '#363b43', attention: '#edaa48', unavailable: '#686e77' }[look];
  ctx.beginPath(); ctx.arc(48, 48, 42, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = look === 'attention' ? '#fff0d4' : '#e3d3ab'; ctx.lineWidth = 3; ctx.stroke();
  ctx.fillStyle = look === 'on' || look === 'attention' ? '#1c1710' : '#f0e6cf';
  ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 4; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  const line = points => { ctx.beginPath(); points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.stroke(); };
  const circle = (x, y, r) => { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke(); };
  if (count !== null) {
    ctx.font = 'bold 38px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(String(count), 48, 48);
  } else if (kind === 'light') {
    circle(48, 39, 17); line([[38, 55], [39, 65], [57, 65], [58, 55]]); line([[41, 73], [55, 73]]);
  } else if (kind === 'lock') {
    ctx.strokeRect(29, 43, 38, 29); ctx.beginPath(); ctx.arc(48, 43, 13, Math.PI, 0); ctx.stroke();
    line([[48, 54], [48, 62]]);
  } else if (kind === 'garage' || kind === 'blinds') {
    line([[24, 69], [24, 32], [72, 32], [72, 69]]);
    for (const y of [42, 52, 62]) line([[30, y], [66, y]]);
  } else if (kind === 'switch' || kind === 'outlet') {
    ctx.beginPath(); ctx.arc(48, 49, 23, -Math.PI * .32, Math.PI * 1.32); ctx.stroke(); line([[48, 22], [48, 46]]);
  } else if (kind === 'fan') {
    circle(48, 48, 5);
    for (let i = 0; i < 3; i++) {
      ctx.save(); ctx.translate(48, 48); ctx.rotate(i * Math.PI * 2 / 3);
      ctx.beginPath(); ctx.ellipse(0, -18, 11, 16, .3, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
    }
  } else if (kind === 'climate') {
    circle(48, 64, 10); line([[43, 54], [43, 26], [53, 26], [53, 54]]);
  } else if (kind === 'sensor') {
    circle(48, 48, 25); line([[31, 49], [39, 49], [44, 36], [51, 61], [57, 49], [65, 49]]);
  } else if (kind === 'camera') {
    ctx.strokeRect(23, 33, 50, 35); circle(48, 50, 12);
  } else if (kind === 'media') {
    line([[38, 27], [66, 48], [38, 69], [38, 27]]);
  } else if (kind === 'alarm') {
    line([[48, 22], [72, 32], [67, 60], [48, 74], [29, 60], [24, 32], [48, 22]]);
  } else {
    circle(48, 48, 24); line([[48, 37], [48, 59]]); line([[37, 48], [59, 48]]);
  }
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export function markerSprite(texture) {
  const material = new THREE.SpriteMaterial({ map: texture, depthTest: false, depthWrite: false, toneMapped: false });
  const sprite = new THREE.Sprite(material); sprite.renderOrder = 20;
  return sprite;
}
