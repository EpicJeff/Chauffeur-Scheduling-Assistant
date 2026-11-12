import { roomClimate } from './climate.js';
import { kindOf, stateLabel } from './kinds.js';
import { formatGlanceValue } from './glance.js';
import { defaultGlanceIcon, GLANCE_ICONS, svgIcon } from './glance_icons.js';

export function roomFacts(room, rows, states, unit) {
  const members = rows.filter(row => room.area_id ? row.area_id === room.area_id
    : row.building === room.building && row.room === room.room);
  const facts = [], attention = members.filter(row => kindOf(row).look(states[row.entity_id]) === 'attention');
  if (attention.length) {
    const words = attention.map(row => stateLabel(row.kind, states[row.entity_id]?.state, states[row.entity_id]?.attributes));
    const word = words.every(w => w === words[0]) ? words[0] : 'need attention';
    const row = attention[0], icon = defaultGlanceIcon(row.entity_id, states[row.entity_id], row.kind);
    facts.push({icon: GLANCE_ICONS[icon].shape, text: `${attention.length} ${word}`, tone: 'attention'});
  }
  const climate = roomClimate(room, members, states);
  if (climate.current !== null) {
    let value = climate.current;
    unit ||= climate.unit;
    if (unit !== climate.unit) value = unit === '°C' ? (value - 32) * 5 / 9 : value * 9 / 5 + 32;
    const text = formatGlanceValue({state: String(value), attributes: {device_class: 'temperature', unit_of_measurement: unit}});
    facts.push({icon: 'thermometer', text: text.replace(/\s*°[CF]$/, '°'), tone: 'plain'});
  }
  const entities = [...new Set(members.flatMap(row => row.entities || [row.entity_id]))];
  const lights = [...new Set([...(room.lights || []), ...entities.filter(id => id.startsWith('light.'))])]
    .filter(id => states[id]?.state === 'on');
  if (lights.length) facts.push({icon: 'lightbulb', text: `${lights.length} on`, tone: 'on'});
  if (entities.some(id => id.startsWith('binary_sensor.') && states[id]?.state === 'on'
      && ['motion', 'occupancy'].includes(states[id].attributes?.device_class)))
    facts.push({icon: 'person-standing', text: 'Occupied', tone: 'on'});
  return facts.slice(0, 3);
}

// Rectangular version of the room-badge separation pass. If the available screen
// cannot fit every card, protect attention first, then temperature, then the rest.
export function layoutRoomCards(items, blocked, width, height) {
  const boxes = items.map(item => ({...item, x: item.x, y: item.y}));
  const box = item => ({left: item.x - item.w / 2, right: item.x + item.w / 2,
    top: item.y - item.h / 2, bottom: item.y + item.h / 2});
  const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  for (let pass = 0; pass < 12; pass++) {
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j], dx = b.x - a.x, dy = b.y - a.y;
      const px = (a.w + b.w) / 2 + 4 - Math.abs(dx), py = (a.h + b.h) / 2 + 4 - Math.abs(dy);
      if (px <= 0 || py <= 0) continue;
      if (px < py) { const push = Math.sign(dx || 1) * px / 2; a.x -= push; b.x += push; }
      else { const push = Math.sign(dy || 1) * py / 2; a.y -= push; b.y += push; }
    }
    for (const item of boxes) {
      item.x = Math.max(item.w / 2, Math.min(width - item.w / 2, item.x));
      item.y = Math.max(item.h / 2, Math.min(height - item.h / 2, item.y));
    }
  }
  const accepted = [];
  for (const item of [...boxes].sort((a, b) => b.priority - a.priority)) {
    const r = box(item);
    item.collapsed = item.w > width || item.h > height || blocked.some(b => overlaps(r, b))
      || accepted.some(b => overlaps(r, b));
    if (!item.collapsed) accepted.push(r);
  }
  return boxes;
}

export function mountRoomCards(host, open) {
  const root = document.createElement('div'); root.className = 'twin-room-cards'; host.append(root);
  const measurer = document.createElement('canvas').getContext('2d');
  const cards = new Map();
  return {
    update(room, facts, count, dim) {
      const key = JSON.stringify([room.building, room.room]);
      let card = cards.get(key);
      if (!card) {
        const node = document.createElement('button'); node.type = 'button'; node.hidden = true;
        node.dataset.roomCard = key;
        const name = document.createElement('strong'), values = document.createElement('div');
        node.append(name, values); root.append(node);
        node.addEventListener('click', () => open(room.building, room.room));
        card = {node, name, values, slots: []}; cards.set(key, card);
      }
      if (card.name.textContent !== room.name) card.name.textContent = room.name;
      card.node.style.opacity = dim ? '.4' : '1';
      card.node.dataset.attention = String(facts.some(f => f.tone === 'attention'));
      card.priority = facts.some(f => f.tone === 'attention') ? 2 : facts.some(f => f.icon === 'thermometer') ? 1 : 0;
      const values = facts.length ? facts : [{icon: null, text: `${count} ${count === 1 ? "device" : "devices"}`, tone: 'plain'}];
      values.forEach((fact, i) => {
        let slot = card.slots[i];
        if (!slot) {
          const node = document.createElement('span'), text = document.createElement('small'); node.append(text);
          card.values.append(node); slot = {node, text, icon: null, svg: null}; card.slots.push(slot);
        }
        slot.node.hidden = false; slot.node.dataset.tone = fact.tone;
        if (slot.text.textContent !== fact.text) slot.text.textContent = fact.text;
        if (slot.icon !== fact.icon) {
          slot.svg?.remove(); slot.svg = fact.icon ? svgIcon(fact.icon, 'currentColor') : null;
          if (slot.svg) slot.node.append(slot.svg);
          slot.icon = fact.icon;
        }
      });
      card.slots.forEach((slot, i) => { slot.node.hidden = i >= values.length; });
      // Fixed height and measured text width also work while the card is hidden.
      measurer.font = '300 12px system-ui';
      const measure = text => Math.ceil(measurer.measureText(text).width);
      const valuesWidth = values.reduce((w, f) => w + measure(f.text) + (f.icon ? 18 : 0) + 10, -10);
      measurer.font = '400 13px system-ui';
      card.w = Math.max(Math.min(140, measure(room.name)), valuesWidth) + 26;
      card.h = 62;
    },
    get: key => cards.get(key),
    display(keys) { cards.forEach((card, key) => {
      const hidden = !keys.has(key);
      if (card.node.hidden !== hidden) card.node.hidden = hidden;
    }); },
    stop() { root.remove(); cards.clear(); },
  };
}
