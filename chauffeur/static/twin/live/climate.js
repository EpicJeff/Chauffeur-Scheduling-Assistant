import { climateHeat, climateCool, climateIdle } from '../palette.js';

// Climate policy is independent of the renderer and HA transport.
const number = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value) : null;
const usable = state => state && !state.stale && !['unknown', 'unavailable'].includes(state.state);
const entities = device => [...new Set([device.entity_id, ...(device.entities || [])].filter(Boolean))];
const fmt = n => Number(n.toFixed(1)).toString();
export const climateRoomKey = room => `${room.building}:${room.room}`;
export const climateColors = {heat: climateHeat, cool: climateCool, idle: climateIdle};

function temperatures(room, devices, states) {
  const ids = [...new Set((devices || []).filter(d => room.area_id && d.area_id === room.area_id).flatMap(entities))];
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
  const sensor = sensors.length ? sensors.reduce((s, row) => s + convert(row), 0) / sensors.length : null;
  return {current: number(attrs.current_temperature) ?? sensor, sensor, unit};
}

// Room cards keep their existing thermostat-first reading and sensor averaging.
export function roomClimate(room, devices, states) {
  const {current, unit} = temperatures(room, devices, states);
  return {current, unit};
}

export function climateAction(state, stale = false) {
  if (stale || !usable(state)) return 'none';
  if (state.state === 'off') return 'off';
  const a = state.attributes || {}, action = a.hvac_action;
  if (action !== undefined && action !== null && action !== '')
    return ['heating', 'preheating'].includes(action) ? 'heat' : action === 'cooling' ? 'cool' : 'idle';
  const current = number(a.current_temperature), target = number(a.temperature);
  if (current === null) return 'idle';
  if (state.state === 'heat' && target !== null && current < target) return 'heat';
  if (state.state === 'cool' && target !== null && current > target) return 'cool';
  if (['heat_cool', 'auto'].includes(state.state)) {
    if (number(a.target_temp_low) !== null && current < Number(a.target_temp_low)) return 'heat';
    if (number(a.target_temp_high) !== null && current > Number(a.target_temp_high)) return 'cool';
  }
  return 'idle';
}

export function climateThermostats(layout) {
  const rows = new Map();
  for (const device of [...(layout.devices || []), ...(layout.markers || [])]) {
    for (const entity of entities(device).filter(id => id.startsWith('climate.'))) {
      const previous = rows.get(entity) || {};
      rows.set(entity, {...previous, ...device, entity, area_id: device.area_id || previous.area_id});
    }
  }
  return [...rows.values()].sort((a, b) => a.entity < b.entity ? -1 : a.entity > b.entity ? 1 : 0);
}

export function climateZone(thermostat, thermostats, saved = {}) {
  if (saved[thermostat.entity]) return {...saved[thermostat.entity], default: false};
  const placed = thermostat.placed && thermostat.building != null;
  const alone = thermostats.filter(t => t.placed && t.building === thermostat.building).length === 1;
  return {scope: placed ? alone ? 'house' : 'floor' : 'rooms', rooms: [], except: [], default: true,
    area: !placed};
}

export function resolveClimateZones(layout, states, stale = false) {
  const rooms = (layout.rooms || []).filter(r => r.state !== 'ghost');
  const thermostats = climateThermostats(layout), claims = new Map(), result = new Map();
  const ranks = {house: 0, floor: 1, rooms: 2};
  for (const thermostat of thermostats) {
    const zone = climateZone(thermostat, thermostats, layout.climate_zones);
    const own = thermostat.placed ? rooms.find(r => r.room === thermostat.room && r.building === thermostat.building) : null;
    const served = rooms.filter(room => {
      if (zone.area) return thermostat.area_id && room.area_id === thermostat.area_id;
      if (zone.scope === 'rooms') return room === own || zone.rooms?.includes(room.room);
      return thermostat.building != null && room.building === thermostat.building && !room.yard &&
        (zone.scope === 'house' || room.level === thermostat.level) && !zone.except?.includes(room.room);
    });
    for (const room of served) {
      const key = climateRoomKey(room), previous = claims.get(key);
      const rank = ranks[zone.scope], standing = room === own;
      if (!previous || rank > previous.rank || rank === previous.rank && standing && !previous.standing)
        claims.set(key, {thermostat, rank, standing, labelRoom: thermostat.placed ? own : served[0]});
    }
  }
  for (const room of rooms) {
    const key = climateRoomKey(room), claim = claims.get(key);
    if (!claim) continue;
    const {thermostat, labelRoom} = claim, state = states[thermostat.entity];
    const action = climateAction(state, stale), a = state?.attributes || {};
    const current = number(a.current_temperature), unit = a.unit_of_measurement || '°F';
    const target = number(a.temperature) ?? (number(a.target_temp_low) !== null && number(a.target_temp_high) !== null
      ? [Number(a.target_temp_low), Number(a.target_temp_high)] : null);
    let label = '';
    if (action !== 'none') {
      if (room === labelRoom && current !== null && target !== null) {
        const setpoint = Array.isArray(target) ? target.map(fmt).join('–') : fmt(target);
        label = `${room.name || ''} ${fmt(current)}° → ${setpoint}°${action === 'heat' ? ' Heating' : action === 'cool' ? ' Cooling' : ''}`;
      } else if (room !== labelRoom) {
        const reading = temperatures(room, layout.devices || layout.markers, states);
        if (reading.sensor !== null) label = `${room.name || ''} ${fmt(reading.sensor)}°`;
      }
    }
    result.set(key, {entity: thermostat.entity, action, current, target, unit, label});
  }
  return result;
}

export function registerClimate(registerMode) {
  registerMode({id: 'climate', label: 'Climate',
    foreground: (row, state) => row.kind === 'climate' || state?.attributes?.device_class === 'temperature',
    legend: 'Orange · Heating   |   Blue · Cooling   |   Grey · Idle',
    enter() {}, update() {}, leave() {}});
}
