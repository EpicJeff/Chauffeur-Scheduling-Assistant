import { kindOf } from './kinds.js';
import { mappedEntities, energyValue } from './energy_mapping.js';

const valid = row => row && !['unknown', 'unavailable', ''].includes(String(row.state));
export const isEnergyEntity = (id, state) => ['power', 'energy', 'battery'].includes(state?.attributes?.device_class) ||
  id.startsWith('sensor.') && /solar|grid|battery|powerwall|car.?charg/i.test(id + ' ' + (state?.attributes?.friendly_name || ''));
export function defaultEntities(states, devices = [], mapping = {}) {
  const weather = Object.keys(states).find(id => id.startsWith('weather.') && Number.isFinite(Number(states[id]?.attributes?.temperature)) && states[id]?.attributes?.temperature != null);
  const energy = [...new Set([...mappedEntities(mapping, true), ...Object.keys(states).filter(id => isEnergyEntity(id, states[id]))])].slice(0, 12 - (weather ? 1 : 0));
  if (!mappedEntities(mapping, true).length) energy.splice(4);
  return [...(weather ? [weather] : []), ...energy];
}
// HA sends no unit on climate entities: take the house's temperature unit from a
// temperature sensor (as Climate mode does), else Fahrenheit.
export function houseTempUnit(states = {}) {
  for (const row of Object.values(states)) {
    const unit = row?.attributes?.unit_of_measurement;
    if (row?.attributes?.device_class === 'temperature' && /°[CF]/.test(unit || '')) return unit;
  }
  return '°F';
}
export function glanceValue(id, row, stale = false, states = {}, mapping = {}) {
  if (!valid(row) || stale) return '—';
  const domain = id.split('.')[0], weather = domain === 'weather', a = row.attributes || {};
  const reading = v => v !== null && v !== undefined && String(v).trim() !== '' && Number.isFinite(Number(v)) ? v : null;
  let value = weather ? a.temperature : row.state;
  let unit = weather ? a.temperature_unit || a.unit_of_measurement || '' : a.unit_of_measurement || '';
  if (domain === 'climate' || domain === 'water_heater') {
    value = reading(a.current_temperature) ?? reading(a.temperature);
    if (value === null && reading(a.target_temp_low) !== null && reading(a.target_temp_high) !== null)
      value = `${a.target_temp_low}–${a.target_temp_high}`;
    unit = a.unit_of_measurement || a.temperature_unit || houseTempUnit(states);
  } else if (domain === 'humidifier') {
    value = reading(a.current_humidity) ?? reading(a.humidity); unit = '%';
  }
  if (value === null || value === undefined) return '—';
  if (!weather && !['climate', 'water_heater', 'humidifier'].includes(domain)) {
    const energy = energyValue(id, row, mapping); if (energy !== null) return energy;
  }
  return `${value}${unit ? ' ' + unit : ''}`;
}
export function mountGlance(host) {
  // This node belongs to the page, not the remountable live layer.
  const bar = document.createElement('div'); bar.id = 'twin-glance'; bar.hidden = true;
  bar.setAttribute('role', 'list'); bar.setAttribute('aria-label', 'House readings'); host.append(bar);
  let live = null, unsubscribe = null, configured = null, stopped = false, devices = [], energyMapping = {};
  // Follow the actual Argyle footprint, as control_center.html does for its
  // scrolling pages. On desks it is the chat bar; panels collapse it to an orb.
  const chrome = ['panel-chat-orb', 'chat-overlay-container', 'panel-shelf']
    .map(id => document.getElementById(id)).filter(Boolean);
  function measure() {
    let floor = 0;
    for (const element of chrome) {
      if (element.id === 'panel-shelf') continue;
      const rect = element.getBoundingClientRect();
      if (rect.height && getComputedStyle(element).display !== 'none')
        floor = Math.max(floor, window.innerHeight - rect.top + 12);
    }
    host.style.setProperty('--twin-glance-clearance', `${floor}px`);
  }
  const resize = window.ResizeObserver ? new window.ResizeObserver(measure) : null;
  const mutations = window.MutationObserver ? new window.MutationObserver(measure) : null;
  for (const element of chrome) {
    resize?.observe(element);
    mutations?.observe(element, {attributes: true, attributeFilter: ['class', 'style', 'hidden']});
    element.addEventListener('transitionend', measure);
  }
  window.addEventListener('resize', measure); measure();
  function update() {
    if (stopped) return;
    measure();
    const states = live?.peek() || {};
    const mapping = live?.energy?.()?.mapping || energyMapping;
    const ids = configured ?? defaultEntities(states, devices, mapping);
    // Reuse the same cells while values change; a stream burst never rebuilds icons.
    if (JSON.stringify(ids) !== bar.dataset.entities) {
      bar.dataset.entities = JSON.stringify(ids); bar.replaceChildren();
      for (const id of ids) {
        const cell = document.createElement('div'); cell.setAttribute('role', 'listitem'); cell.dataset.entity = id;
        const icon = document.createElement('canvas'); icon.width = icon.height = 96; icon.setAttribute('aria-hidden', 'true');
        const device = devices.find(d => d.entities?.includes(id) || d.entity_id === id);
        const row = {...device, entity_id: id, kind: id.startsWith('weather.') ? 'climate' : device?.entity_id === id ? device.kind : id.split('.')[0]};
        const ctx = icon.getContext('2d'); ctx.strokeStyle = '#f0e6cf'; ctx.lineWidth = 5; kindOf(row).icon(ctx);
        const name = document.createElement('span'); name.dataset.glanceName = '';
        const value = document.createElement('strong'); value.dataset.glanceValue = '';
        cell.append(icon, name, value); bar.append(cell);
      }
    }
    for (const cell of bar.children) {
      const id = cell.dataset.entity;
      cell.querySelector('[data-glance-name]').textContent = states[id]?.attributes?.friendly_name || id.split('.')[1].replaceAll('_', ' ');
      cell.querySelector('[data-glance-value]').textContent = glanceValue(id, states[id], live?.stale(), states, mapping);
    }
    bar.hidden = !ids.length;
  }
  return {bar, update,
    configure(ids) { configured = ids; update(); },
    energy(mapping) { energyMapping = mapping; update(); },
    attach(next) { unsubscribe?.(); live = next; devices = next?.layout().devices || []; unsubscribe = next?.subscribe(update); update(); },
    move(parent) { parent.append(bar); measure(); },
    stop() {
      stopped = true; unsubscribe?.(); resize?.disconnect(); mutations?.disconnect();
      window.removeEventListener('resize', measure);
      for (const element of chrome) element.removeEventListener('transitionend', measure);
      bar.remove();
    },
  };
}
