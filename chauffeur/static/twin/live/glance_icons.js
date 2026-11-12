import { LUCIDE } from '../../vendor/lucide/icons.js';
import { twinOpen, twinCyan, twinLight, twinHeat, twinAttention, twinDevice } from '../palette.js';

// Semantic ids are stored with tiles. Geometry stays in the licensed vendor.
export const GLANCE_ICONS = Object.fromEntries([
  ['solar', 'sun', twinLight, 'Solar'], ['house', 'house', twinDevice, 'House'],
  ['battery', 'battery', '#86dca0', 'Battery'], ['battery-charging', 'battery-charging', '#a3e635', 'Battery charging'],
  ['car', 'car', '#c4b5fd', 'Car'], ['ev-plug', 'plug-zap', '#b6a0ff', 'EV charging'],
  ['grid', 'utility-pole', '#93c5fd', 'Grid'], ['plug', 'plug', '#a5b4fc', 'Plug'],
  ['thermometer', 'thermometer', '#fda4af', 'Temperature'], ['humidity', 'droplet', '#7dd3fc', 'Humidity'],
  ['water', 'droplets', '#67e8f9', 'Water'], ['gas', 'flame', twinHeat, 'Gas / heat'],
  ['fan', 'fan', '#99f6e4', 'Fan'], ['cooling', 'snowflake', '#bae6fd', 'Cooling'],
  ['bulb', 'lightbulb', twinLight, 'Light'], ['lock', 'lock', '#a7f3d0', 'Lock'],
  ['door', 'door-open', twinOpen, 'Door'], ['window', 'panels-top-left', '#a5d8ff', 'Window'],
  ['garage', 'warehouse', '#cbd5e1', 'Garage'], ['camera', 'camera', '#c7d2fe', 'Camera'],
  ['alarm', 'shield', '#fca5a5', 'Alarm'], ['wifi', 'wifi', '#a5f3fc', 'Wi-Fi'],
  ['server', 'server', '#d8b4fe', 'Router / server'], ['trash', 'trash-2', '#bef264', 'Trash'],
  ['washer', 'washing-machine', '#93d7ee', 'Washer'], ['dryer', 'wind', twinCyan, 'Dryer'],
  ['dishwasher', 'utensils-crossed', '#b3d9cc', 'Dishwasher'], ['oven', 'cooking-pot', twinHeat, 'Oven'],
  ['tv', 'tv', '#c4c9f5', 'TV'], ['speaker', 'speaker', '#f0abfc', 'Speaker'],
  ['sprinkler', 'shower-head', '#6ee7b7', 'Sprinkler'], ['pool', 'waves', '#67cbee', 'Pool'],
  ['leaf', 'leaf', '#bbdf92', 'Tree / leaf'], ['cloud', 'cloud', '#d1d9e6', 'Cloud'],
  ['gauge', 'gauge', twinCyan, 'Gauge'], ['clock', 'clock', '#ddd6fe', 'Clock'],
  ['person', 'person-standing', '#fecdd3', 'Person'], ['pet', 'paw-print', '#e5b9e8', 'Pet'],
  ['bell', 'bell', twinAttention, 'Bell'], ['power', 'power', '#a5dbc1', 'Power'],
].map(([id, shape, color, name]) => [id, {shape, color, name}]));

export function defaultGlanceIcon(entity, row = {}, kind = '') {
  const dc = row.attributes?.device_class;
  const classes = {battery: 'battery', humidity: 'humidity', temperature: 'thermometer',
    power: 'power', energy: 'power', gas: 'gas', water: 'water', moisture: 'water',
    door: 'door', opening: 'door', window: 'window', garage_door: 'garage', lock: 'lock',
    motion: 'person', occupancy: 'person', presence: 'person', smoke: 'alarm', safety: 'alarm'};
  const kinds = {weather: 'cloud', climate: 'thermometer', water_heater: 'thermometer', humidifier: 'humidity',
    light: 'bulb', switch: 'plug', outlet: 'plug', fan: 'fan', lock: 'lock', cover: 'window',
    camera: 'camera', alarm_control_panel: 'alarm', alarm: 'alarm', media_player: 'speaker', person: 'person', device_tracker: 'person'};
  return classes[dc] || kinds[kind] || kinds[entity.split('.')[0]] || 'gauge';
}
export function glanceIcon(id) {
  const item = GLANCE_ICONS[id] || GLANCE_ICONS.gauge;
  return svgIcon(item.shape, item.color, id);
}
export function svgIcon(shape, color = '#d1d9e6', id = shape) {
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  for (const [key, value] of Object.entries({viewBox: '0 0 24 24', width: '24', height: '24', fill: 'none',
    stroke: color, 'stroke-width': '1.75', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false'})) svg.setAttribute(key, value);
  svg.dataset.glanceIcon = id;
  for (const [tag, attrs] of LUCIDE[shape] || LUCIDE.cloud) {
    const node = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    svg.append(node);
  }
  return svg;
}
