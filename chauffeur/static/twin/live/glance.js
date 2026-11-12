import { defaultGlanceIcon, glanceIcon } from './glance_icons.js';

const valid = row => row && !['unknown', 'unavailable', 'none', ''].includes(String(row.state).trim().toLowerCase());
const reading = value => value !== null && value !== undefined && String(value).trim() !== '' && Number.isFinite(Number(value)) ? Number(value) : null;
export const isEnergyEntity = (id, state) => ['power', 'energy', 'battery'].includes(state?.attributes?.device_class) ||
  id.startsWith('sensor.') && /solar|grid|battery|powerwall|car.?charg/i.test(id + ' ' + (state?.attributes?.friendly_name || ''));
export function humanise(value) {
  const text = ({partlycloudy: 'partly cloudy', 'windy-variant': 'windy', 'snowy-rainy': 'snow and rain',
    'lightning-rainy': 'thunderstorms', 'clear-night': 'clear night'}[value] || String(value).replaceAll('_', ' ').replaceAll('-', ' '));
  return text.charAt(0).toUpperCase() + text.slice(1);
}
export function houseTempUnit(states = {}) {
  for (const row of Object.values(states)) {
    const unit = row?.attributes?.unit_of_measurement;
    if (row?.attributes?.device_class === 'temperature' && /°[CF]/.test(unit || '')) return unit;
  }
  return '°F';
}
const BINARY_WORDS = {
  battery: ['Normal', 'Low'], battery_charging: ['Not charging', 'Charging'], cold: ['Normal', 'Cold'],
  connectivity: ['Disconnected', 'Connected'], door: ['Closed', 'Open'], garage_door: ['Closed', 'Open'],
  window: ['Closed', 'Open'], opening: ['Closed', 'Open'], lock: ['Locked', 'Unlocked'],
  gas: ['Clear', 'Detected'], smoke: ['Clear', 'Detected'], motion: ['Clear', 'Detected'],
  occupancy: ['Clear', 'Detected'], presence: ['Away', 'Home'], moisture: ['Dry', 'Wet'],
  heat: ['Normal', 'Hot'], light: ['No light', 'Light'], moving: ['Stopped', 'Moving'],
  plug: ['Unplugged', 'Plugged in'], power: ['Off', 'On'], problem: ['OK', 'Problem'],
  running: ['Stopped', 'Running'], safety: ['Safe', 'Unsafe'], sound: ['Clear', 'Detected'],
  tamper: ['Clear', 'Detected'], update: ['Up to date', 'Update available'], vibration: ['Clear', 'Detected'],
};
// One formatter for both presentations. Mapping words apply only to mapped power roles.
export function formatGlanceValue(row, states = {}, mapping = {}) {
  const entity = row?.entity || row?.entity_id || '';
  if (row?.entity) row = states[entity];
  if (!valid(row)) return '—';
  const id = entity, domain = id.split('.')[0], a = row.attributes || {};
  let value = row.state, unit = a.unit_of_measurement || '';
  const temperature = ['climate', 'water_heater', 'weather'].includes(domain) || a.device_class === 'temperature' || /^(°[CF]|[CF])$/.test(unit);
  if (domain === 'climate' || domain === 'water_heater') {
    value = reading(a.current_temperature) ?? reading(a.temperature);
    if (value === null && reading(a.target_temp_low) !== null && reading(a.target_temp_high) !== null)
      return `${Math.round(Number(a.target_temp_low))}–${Math.round(Number(a.target_temp_high))} ${a.unit_of_measurement || a.temperature_unit || houseTempUnit(states)}`;
  } else if (domain === 'weather') value = a.temperature;
  else if (domain === 'humidifier') { value = reading(a.current_humidity) ?? reading(a.humidity); unit = '%'; }
  if (domain === 'binary_sensor' && ['on', 'off'].includes(value)) return (BINARY_WORDS[a.device_class] || ['Off', 'On'])[value === 'on' ? 1 : 0];
  if (['lock', 'cover'].includes(domain)) return humanise(value);
  const n = reading(value);
  if (temperature) {
    unit = a.temperature_unit || unit || houseTempUnit(states);
    if (/^[CF]$/.test(unit)) unit = '°' + unit;
    return n === null ? '—' : `${Math.round(n)} ${unit}`;
  }
  if (unit === '%' || ['battery', 'humidity'].includes(a.device_class)) return n === null ? '—' : `${Math.round(n)} %`;
  if (!unit && a.device_class === 'power') unit = 'W';
  if (n !== null && /^(w|kw|mw|wh|kwh|mwh)$/i.test(unit)) {
    const energy = /h$/i.test(unit), scaled = n * (/^m/i.test(unit) ? 1000000 : /^k/i.test(unit) ? 1000 : 1), magnitude = Math.abs(scaled);
    const amount = magnitude >= 1000 ? `${(magnitude / 1000).toFixed(1)} k${energy ? 'Wh' : 'W'}` : `${Math.round(magnitude)} ${energy ? 'Wh' : 'W'}`;
    if (!energy && scaled !== 0) {
      if (id === mapping.battery_power) return `${(scaled > 0) === (mapping.battery_positive !== 'charge') ? 'discharging' : 'charging'} ${amount}`;
      if (id === mapping.grid_power) return `${(scaled > 0) === (mapping.grid_positive !== 'export') ? 'importing' : 'exporting'} ${amount}`;
    }
    return (scaled < 0 ? '-' : '') + amount;
  }
  if (value === null || value === undefined) return '—';
  return n === null ? humanise(value) : `${Number(n.toFixed(1))}${unit ? ' ' + unit : ''}`;
}
export function glanceValue(id, row, stale = false, states = {}, mapping = {}) {
  return stale ? '—' : formatGlanceValue(row && {...row, entity_id: id}, states, mapping);
}
export function migrateGlanceTiles(tiles, states = {}, devices = []) {
  return (tiles || []).map(tile => typeof tile === 'string' ? {entity: tile,
    icon: defaultGlanceIcon(tile, states[tile], devices.find(d => d.entity_id === tile || d.entities?.includes(tile))?.kind), label: ''} : {...tile});
}
export function buildGlanceTile(tile) {
  const cell = document.createElement('div'); cell.setAttribute('role', 'listitem'); cell.dataset.entity = tile.entity;
  const text = document.createElement('div'), value = document.createElement('strong'); value.dataset.glanceValue = '';
  text.append(value);
  if (tile.label) { const label = document.createElement('small'); label.dataset.glanceLabel = ''; label.textContent = tile.label; text.append(label); }
  cell.append(glanceIcon(tile.icon), text);
  return cell;
}
function setValue(node, text) {
  const parts = text.match(/^(.*) ([^ ]+)$/);
  node.replaceChildren();
  if (parts && /\d/.test(parts[1]) && !/\d/.test(parts[2])) {
    const unit = document.createElement('span'); unit.dataset.glanceUnit = ''; unit.textContent = parts[2];
    node.append(document.createTextNode(parts[1] + ' '), unit);
  } else node.textContent = text;
}
export function mountGlance(host) {
  const bar = document.createElement('div'); bar.id = 'twin-glance'; bar.hidden = true;
  bar.setAttribute('role', 'list'); bar.setAttribute('aria-label', 'House readings'); host.append(bar);
  let live = null, unsubscribe = null, configured = [], stopped = false, devices = [], energyMapping = {};
  const chrome = ['panel-chat-orb', 'chat-overlay-container', 'panel-shelf'].map(id => document.getElementById(id)).filter(Boolean);
  function measure() {
    let floor = 0;
    for (const element of chrome) {
      if (element.id === 'panel-shelf') continue;
      const rect = element.getBoundingClientRect();
      if (rect.height && getComputedStyle(element).display !== 'none') floor = Math.max(floor, window.innerHeight - rect.top + 12);
    }
    host.style.setProperty('--twin-glance-clearance', `${floor}px`);
  }
  const resize = window.ResizeObserver ? new window.ResizeObserver(measure) : null;
  const mutations = window.MutationObserver ? new window.MutationObserver(measure) : null;
  for (const element of chrome) {
    resize?.observe(element); mutations?.observe(element, {attributes: true, attributeFilter: ['class', 'style', 'hidden']});
    element.addEventListener('transitionend', measure);
  }
  window.addEventListener('resize', measure); measure();
  function update() {
    if (stopped) return;
    measure();
    const states = live?.peek() || {}, mapping = live?.energy?.()?.mapping || energyMapping;
    const tiles = migrateGlanceTiles(configured, states, devices);
    if (JSON.stringify(tiles) !== bar.dataset.tiles) {
      bar.dataset.tiles = JSON.stringify(tiles); bar.replaceChildren();
      for (const tile of tiles) bar.append(buildGlanceTile(tile));
    }
    for (const cell of bar.children) setValue(cell.querySelector('[data-glance-value]'), glanceValue(cell.dataset.entity, states[cell.dataset.entity], !live || live.stale(), states, mapping));
    bar.hidden = !tiles.length;
  }
  return {bar, update,
    configure(tiles) { configured = tiles || []; live?.configureGlance?.(configured); update(); },
    energy(mapping) { energyMapping = mapping; update(); },
    attach(next) { unsubscribe?.(); live = next; devices = next?.layout().devices || []; unsubscribe = next?.subscribe(update); live?.configureGlance?.(configured); update(); },
    move(parent) { parent.append(bar); measure(); },
    stop() {
      stopped = true; unsubscribe?.(); resize?.disconnect(); mutations?.disconnect(); window.removeEventListener('resize', measure);
      for (const element of chrome) element.removeEventListener('transitionend', measure);
      bar.remove();
    },
  };
}
