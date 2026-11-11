// Climate's data and colour policy is independent of the renderer and HA transport.
const number = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value) : null;
const usable = state => state && !['unknown', 'unavailable'].includes(state.state);
export const NEUTRAL = [145, 153, 151];
export function temperatureColor(value, band, unit = '°F') {
  if (value === null || !Number.isFinite(value)) return [...NEUTRAL];
  const delta = value < band[0] ? value - band[0] : value > band[1] ? value - band[1] : 0;
  const amount = Math.min(1, Math.abs(delta) / (unit === '°C' ? 5 : 10));
  const end = delta < 0 ? [65, 143, 232] : [230, 88, 65];
  return NEUTRAL.map((v, i) => Math.round(v + (end[i] - v) * amount));
}
export function roomClimate(room, devices, states) {
  const ids = [...new Set(devices.filter(d => room.area_id && d.area_id === room.area_id)
    .flatMap(d => d.entities || [d.entity_id]))];
  const thermostats = ids.filter(id => id.startsWith('climate.') && usable(states[id]));
  const thermostat = thermostats.find(id => number(states[id].attributes?.current_temperature) !== null) || thermostats[0];
  const attrs = states[thermostat]?.attributes || {};
  const sensors = ids.filter(id => id.startsWith('sensor.') && usable(states[id]) &&
    states[id].attributes?.device_class === 'temperature' && number(states[id].state) !== null).map(id => states[id]);
  const unit = attrs.unit_of_measurement || sensors[0]?.attributes?.unit_of_measurement || '°F';
  const convert = row => {
    const v = number(row.state), u = row.attributes.unit_of_measurement || unit;
    return u === unit ? v : unit === '°C' ? (v - 32) * 5 / 9 : v * 9 / 5 + 32;
  };
  const current = number(attrs.current_temperature) ?? (sensors.length ? sensors.reduce((s, row) => s + convert(row), 0) / sensors.length : null);
  const target = number(attrs.temperature), low = number(attrs.target_temp_low), high = number(attrs.target_temp_high);
  const band = target !== null ? [target - 1, target + 1] : low !== null && high !== null ? [low - 1, high + 1] : unit === '°C' ? [20, 23] : [68, 74];
  const fmt = n => Number(n.toFixed(1)).toString();
  const label = thermostat && current !== null && (target !== null || low !== null && high !== null)
    ? `${fmt(current)}${unit} → ${target !== null ? fmt(target) : `${fmt(low)}–${fmt(high)}`}${unit}` : '';
  return {current, unit, band, label, rgb: temperatureColor(current, band, unit)};
}
export function registerClimate(registerMode) {
  registerMode({id: 'climate', label: 'Climate',
    foreground: (row, state) => row.kind === 'climate' || state?.attributes?.device_class === 'temperature',
    legend: 'Cool · Below comfort   |   Grey · Comfort / no reading   |   Warm · Above comfort',
    enter() {}, update() {}, leave() {}});
}
