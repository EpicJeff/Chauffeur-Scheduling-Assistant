// Pure mapping policy: only instantaneous power drives ribbons; kWh never means kW.
export const ROLES = ['solar_power', 'battery_power', 'battery_level', 'grid_power', 'house_power'];
export const mappedEntities = (mapping, readingsOnly = false) => [...new Set([
  ...ROLES.map(k => mapping?.[k]), ...(mapping?.cars || []).flatMap(c => [c.charge_power, c.battery_level, ...(!readingsOnly ? [c.location] : [])])
].filter(Boolean))];
const text = (id, row) => `${id} ${row?.attributes?.friendly_name || ''}`.toLowerCase();
const power = row => row?.attributes?.device_class === 'power' || /^(w|kw|mw)$/i.test(row?.attributes?.unit_of_measurement || '');
const battery = (id, row) => row?.attributes?.device_class === 'battery' || /charge|battery.*level|state.of.charge|soc/.test(text(id, row)) && row?.attributes?.unit_of_measurement === '%';
export function guessEnergy(states = {}, saved = {}, fleet = []) {
  const ids = Object.keys(states).sort();
  const pick = pattern => ids.find(id => power(states[id]) && pattern.test(text(id, states[id])) &&
    (!/charger|wallbox|tesla|vehicle|car[_. ]/.test(text(id, states[id])) || /powerwall/.test(text(id, states[id])))) || null;
  const guessed = {
    solar_power: pick(/solar|(?:^|[_. ])pv(?:[_. ]|$)/), battery_power: pick(/battery/),
    battery_level: ids.find(id => battery(id, states[id]) && /powerwall|battery/.test(text(id, states[id])) &&
      (!/tesla|car[_. ]|vehicle/.test(text(id, states[id])) || /powerwall/.test(text(id, states[id])))) || null,
    grid_power: pick(/grid|site/), house_power: pick(/load|home|house/),
    // HA Powerwall: positive battery = discharge; positive site = import.
    battery_positive: 'discharge', grid_positive: 'import', home_includes_chargers: true,
    panels: {visible: true, plane: null}, cars: []
  };
  const groups = new Map();
  for (const c of fleet) groups.set(String(c.id), {...c, charge_power: null});
  // Match fleet telemetry stems before making inferred cars, so Tesla telemetry
  // and the household's named car are one vehicle.
  for (const id of ids) {
    const row = states[id], name = text(id, row);
    if (!/charger|wallbox|tesla|vehicle|car[_. ]/.test(name) || /powerwall/.test(name)) continue;
    const stem = id.split('.')[1].replace(/_(?:charger_)?(?:charging_power|charge_power|power|battery_level|battery|charge|location|presence|device_tracker)$/, '');
    let car = [...groups.values()].find(c => [c.battery_level, c.location].some(e => e && e.split('.')[1].startsWith(stem)));
    if (!car) { if (!groups.has(stem)) groups.set(stem, {id: stem, name: stem.replaceAll('_', ' ')}); car = groups.get(stem); }
    if (power(row)) car.charge_power ||= id;
    if (battery(id, row)) car.battery_level ||= id;
    if (/^(device_tracker|person)\./.test(id) || row.attributes?.device_class === 'presence') car.location ||= id;
  }
  guessed.cars = [...groups.values()].filter(c => c.charge_power || c.battery_level || c.location || fleet.some(f => String(f.id) === String(c.id))).slice(0, 12);
  return {...guessed, ...saved, panels: {...guessed.panels, ...saved.panels}};
}
export function watts(id, states) {
  const row = states[id], value = row?.state;
  if (value == null || String(value).trim() === '' || !Number.isFinite(Number(value)) || !power(row)) return null;
  const unit = (row.attributes?.unit_of_measurement || 'W').toLowerCase();
  return Number(value) * (unit === 'kw' ? 1000 : unit === 'mw' ? 1000000 : 1);
}
export function carHome(car, states) {
  if (!car.location) return true; // cars.py's no-tracker rule
  const row = states[car.location];
  return row?.state === 'home' || row?.attributes?.device_class === 'presence' && row.state === 'on';
}

// Instantaneous watts only. Allocate before applying the display threshold so
// dropping a small flow never redirects it to a different destination.
export function allocateEnergyFlows(totals, mapping = {}) {
  const number = value => Number.isFinite(value) ? value : 0;
  const positive = value => Math.max(0, number(value));
  const solar = positive(totals.solar);
  const battery = number(totals.battery) * (mapping.battery_positive === 'charge' ? -1 : 1);
  const grid = number(totals.grid) * (mapping.grid_positive === 'export' ? -1 : 1);
  const chargers = (totals.chargers || []).map(positive);
  const home = positive(totals.home) + (mapping.home_includes_chargers === false ? chargers.reduce((a,b) => a+b, 0) : 0);
  const charging = Math.max(0, -battery), discharging = Math.max(0, battery);
  const importing = Math.max(0, grid);
  const solarHome = Math.min(solar, home);
  const solarBattery = Math.min(solar - solarHome, charging);
  const solarGrid = solar - solarHome - solarBattery;
  const batteryHome = Math.min(discharging, home - solarHome);
  const gridHome = Math.min(importing, home - solarHome - batteryHome);
  // The meter's import first covers home, then the remaining battery charge.
  const gridBattery = Math.min(charging - solarBattery, importing - gridHome);
  const batteryGrid = discharging - batteryHome;
  return Object.fromEntries([
    ['solar:house', solarHome], ['solar:battery', solarBattery], ['solar:grid', solarGrid],
    ['battery:house', batteryHome], ['grid:house', gridHome],
    ['grid:battery', gridBattery], ['battery:grid', batteryGrid],
    ...chargers.map((value, i) => ['car:' + i, value])
  ].map(([id, value]) => [id, Math.max(0, value)]).filter(([,value]) => value >= 50));
}

export function energyFlows(mapping, states, zoneEntities = []) {
  const zoneReadings = zoneEntities.map(id => watts(id, states));
  const solar = mapping.solar_power ? watts(mapping.solar_power, states)
    : zoneReadings.some(value => value === null) ? null : zoneReadings.reduce((sum,value) => sum + Math.max(0, value), 0);
  const battery = watts(mapping.battery_power, states), grid = watts(mapping.grid_power, states), home = watts(mapping.house_power, states);
  // An unavailable total is unknown, not zero consumption/production. Direct
  // charger telemetry can still be shown when the balance cannot be inferred.
  const known = home !== null && solar !== null && (!mapping.battery_power || battery !== null) && (!mapping.grid_power || grid !== null);
  return allocateEnergyFlows({solar: known ? solar : 0, battery: known ? battery : 0,
    grid: known ? grid : 0, home: known ? home : 0,
    chargers: (mapping.cars || []).map(car => carHome(car, states) ? watts(car.charge_power, states) : 0)}, mapping);
}
export function flowReading(value, positive = true) {
  const magnitude = Math.abs(value || 0);
  return {visible: magnitude >= 50, direction: (value < 0 ? -1 : 1) * (positive ? 1 : -1),
    // Full core width, in world metres: 0.4–1.5 ft. The halo is wider.
    width: (.4 + Math.min(1.1, Math.sqrt(magnitude / 4000) * 1.1)) * .3048,
    speed: .15 + Math.min(1.5, Math.sqrt(magnitude / 1000) * .35), label: `${Number((magnitude / 1000).toFixed(2))} kW`};
}

export function energyValue(id, row, mapping = {}) {
  const unit = row?.attributes?.unit_of_measurement || (row?.attributes?.device_class === 'power' ? 'W' : '');
  if (!/^(w|kw|mw|wh|kwh|mwh)$/i.test(unit) || row.state == null || String(row.state).trim() === '' || !Number.isFinite(Number(row.state))) return null;
  const energy = /h$/i.test(unit), kilo = /^k/i.test(unit), mega = /^m/i.test(unit);
  const value = Number(row.state) * (mega ? 1000000 : kilo ? 1000 : 1), magnitude = Math.abs(value);
  const amount = magnitude >= 1000 ? `${(magnitude / 1000).toFixed(1)} k${energy ? 'Wh' : 'W'}` : `${Number(magnitude.toFixed(1))} ${energy ? 'Wh' : 'W'}`;
  if (!energy && value !== 0) {
    if (id === mapping.battery_power) return `${(value > 0) === (mapping.battery_positive !== 'charge') ? 'discharging' : 'charging'} ${amount}`;
    if (id === mapping.grid_power) return `${(value > 0) === (mapping.grid_positive !== 'export') ? 'importing' : 'exporting'} ${amount}`;
  }
  return (value < 0 ? '-' : '') + amount;
}
