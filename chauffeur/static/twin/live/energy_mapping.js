// Pure mapping policy: only instantaneous power drives ribbons; kWh never means kW.
export const ROLES = ['solar_power', 'battery_power', 'battery_level', 'grid_power', 'house_power'];
export function migrateEnergy(mapping = {}) {
  const result = structuredClone(mapping);
  if (!Object.hasOwn(result, 'chargers') && result.cars?.some(c => c.charge_power || c.anchor)) {
    result.chargers = [];
    for (const car of result.cars) if (car.charge_power || car.anchor) {
      result.chargers.push({id:'charger-' + car.id, name:(car.name || 'Car').slice(0,92) + ' charger', power:car.charge_power ?? null, anchor:car.anchor ?? null, car:car.id});
      car.charge_power = null; car.anchor = null;
    }
  }
  return result;
}
export const mappedEntities = (mapping, readingsOnly = false) => [...new Set([
  ...ROLES.map(k => mapping?.[k]), ...(mapping?.chargers || []).map(c=>c.power),
  ...(mapping?.cars || []).flatMap(c => [c.charge_power, c.battery_level, c.charging, c.range_entity, ...(!readingsOnly ? [c.location] : [])])
].filter(Boolean))];
const text = (id, row) => `${id} ${row?.attributes?.friendly_name || ''}`.toLowerCase();
const power = row => row?.attributes?.device_class === 'power' || /^(w|kw|mw)$/i.test(row?.attributes?.unit_of_measurement || '');
const battery = (id, row) => row?.attributes?.device_class === 'battery' || /charge|battery.*level|state.of.charge|soc/.test(text(id, row)) && row?.attributes?.unit_of_measurement === '%';
export function guessEnergy(states = {}, saved = {}, fleet = [], plan = {}) {
  saved = migrateEnergy(saved);
  const ids = Object.keys(states).sort();
  // Saved choices win, including None, and cannot be borrowed by an automatic role.
  const used = new Set(ROLES.map(key => saved[key]).filter(Boolean));
  const specific = /load|home|house|battery|grid|site|solar|(?:^|[_. ])pv(?:[_. ]|$)|charg/;
  const candidates = ids.filter(id => power(states[id]) &&
    /^(w|kw|mw)$/i.test(states[id].attributes?.unit_of_measurement || 'W') &&
    (!/charger|wallbox|tesla|vehicle|car[_. ]/.test(text(id, states[id])) || /powerwall/.test(text(id, states[id]))));
  const pick = (key, patterns, exclude = /$^/) => {
    if (Object.hasOwn(saved, key)) return saved[key];
    // A specific id describes the reading; a shared device name such as
    // "Home Energy Gateway" must not relabel battery or site power as home.
    for (const pattern of patterns) for (const byId of [true, false]) {
      const id = candidates.find(id => {
        if (used.has(id) || !byId && specific.test(id)) return false;
        const name = byId ? id.toLowerCase() : text(id, states[id]);
        return pattern.test(name) && !exclude.test(name);
      });
      if (id) {used.add(id); return id;}
    }
    return null;
  };
  const guessed = {
    solar_power: pick('solar_power', [/solar|(?:^|[_. ])pv(?:[_. ]|$)/]),
    battery_power: pick('battery_power', [/battery/]),
    battery_level: ids.find(id => battery(id, states[id]) && /powerwall|battery/.test(text(id, states[id])) &&
      (!/tesla|car[_. ]|vehicle/.test(text(id, states[id])) || /powerwall/.test(text(id, states[id])))) || null,
    grid_power: pick('grid_power', [/grid|site/], /battery|solar|(?:^|[_. ])pv(?:[_. ]|$)/),
    house_power: pick('house_power', [/load/, /home|house/], /battery|grid|site|solar|(?:^|[_. ])pv(?:[_. ]|$)|charg/),
    // HA Powerwall: positive battery = discharge; positive site = import.
    battery_positive: 'discharge', grid_positive: 'import', home_includes_chargers: true,
    panels: {visible: true, plane: null}, cars: [], chargers: []
  };
  const groups = new Map();
  const telemetryStem = id => (id || '').split('.').pop().replace(/_(?:(?:charger|charging|charge)_power|charging_state|battery_level|device_tracker|charging|power|battery|charge|location|presence|range)$/, '');
  for (const c of fleet) groups.set(String(c.id), {...c, charge_power: null});
  // Battery/tracker stems identify a car before generic charger names do.
  for (const id of ids) if ((battery(id,states[id]) || /^(device_tracker|person)\./.test(id)) &&
      /tesla|vehicle|car[_. ]|ev[_. ]|_ev_/.test(text(id,states[id])) && !/powerwall/.test(id)) {
    const stem = telemetryStem(id);
    if (![...groups.values()].some(c=>[c.battery_level,c.location].some(e=>telemetryStem(e)===stem)))
      groups.set(stem,{id:stem,name:stem.replaceAll('_',' ')});
  }
  // Match fleet telemetry stems before making inferred cars, so Tesla telemetry
  // and the household's named car are one vehicle.
  for (const id of ids) {
    const row = states[id], name = text(id, row);
    if (/powerwall/.test(name)) continue;
    const stem = telemetryStem(id);
    let car = [...groups.values()].find(c => [c.battery_level, c.location].some(e => e && telemetryStem(e)===stem) || c.id===stem);
    if (!car && power(row) && /^(w|kw|mw)$/i.test(row.attributes?.unit_of_measurement || 'W') && /wall.?connector|wallbox|charger|evse/.test(name) && !/battery/.test(name)) {
      guessed.chargers.push({id:'charger-'+stem,name:row.attributes?.friendly_name || stem.replaceAll('_',' '),power:id}); continue;
    }
    if (!car && !/tesla|vehicle|car[_. ]/.test(name)) continue;
    if (!car) { if (!groups.has(stem)) groups.set(stem, {id: stem, name: stem.replaceAll('_', ' ')}); car = groups.get(stem); }
    if (power(row)) car.charge_power ||= id;
    if (battery(id, row)) car.battery_level ||= id;
    if (/^binary_sensor\..*charging/.test(id) || /^sensor\..*charging_state/.test(id)) car.charging ||= id;
    if (/^(device_tracker|person)\./.test(id) || row.attributes?.device_class === 'presence') car.location ||= id;
  }
  guessed.cars = [...groups.values()].filter(c => c.charge_power || c.battery_level || c.location || fleet.some(f => String(f.id) === String(c.id))).slice(0, 12);
  guessed.chargers = guessed.chargers.slice(0,8);
  const result = {...guessed, ...saved, panels: {...guessed.panels, ...saved.panels}};
  // Appearance and range belong to the fleet, even after a mapping is saved.
  result.cars = result.cars.map(c=>({...fleet.find(f=>String(f.id)===String(c.id)),...c}));
  const fleetOrder=new Map(fleet.map((c,i)=>[String(c.id),i]));
  result.cars.sort((a,b)=>(fleetOrder.get(String(a.id)) ?? Infinity)-(fleetOrder.get(String(b.id)) ?? Infinity));
  for(const b of plan.buildings || [])for(const p of b.anchors || [])if(p.kind==='charger' && p.state!=='ghost'){
    const ref={type:'object',building:b.id,id:p.id};
    const existing=result.chargers.find(c=>c.anchor?.type==='object' && c.anchor.building===b.id && c.anchor.id===p.id || p.power && c.power===p.power);
    if(existing){
      if(existing.anchor===undefined)existing.anchor=ref;
      if(existing.anchor?.type==='object' && existing.anchor.id===p.id && existing.anchor.building===b.id)
        for(const key of ['name','power','car'])if(Object.hasOwn(p,key))existing[key]=p[key];
    }
    else if(p.power && result.chargers.length<8)result.chargers.push({id:`charger-${b.id}-${p.id}`,name:p.name || 'Charger',power:p.power,car:p.car || null,anchor:ref});
  }
  return result;
}
export function watts(id, states) {
  const row = states[id], value = row?.state;
  if (value == null || String(value).trim() === '' || !Number.isFinite(Number(value)) || !power(row)) return null;
  const unit = (row.attributes?.unit_of_measurement || 'W').toLowerCase();
  // Instantaneous power only: an energy counter (Wh/kWh) is not a flow, even with device_class power.
  if (!['w', 'kw', 'mw'].includes(unit)) return null;
  return Number(value) * (unit === 'kw' ? 1000 : unit === 'mw' ? 1000000 : 1);
}
export function carHome(car, states) {
  if (!car.location) return true; // cars.py's no-tracker rule
  const row = states[car.location];
  return row?.state === 'home' || row?.attributes?.device_class === 'presence' && row.state === 'on';
}
export const carCharging = (car, states) => {
  const state = String(states[car.charging]?.state || '').toLowerCase();
  return state === 'charging' || car.charging?.startsWith('binary_sensor.') && state === 'on';
};

// All positions here are lot feet, not WebGL metres. Ties never pick a car
// arbitrarily. A dedicated but away car does not redirect a dedicated charger.
export function chargingDecision(charger, cars, states = {}, spots = []) {
  const home = cars.filter(c=>carHome(c,states));
  if (charger.car && home.some(c=>c.id===charger.car)) return {car:home.find(c=>c.id===charger.car), reason:'dedicated car'};
  const charging = home.filter(c=>carCharging(c,states));
  if (charging.length === 1) return {car:charging[0],reason:'charging sensor'};
  if (charging.length > 1) return {car:null,reason:'both cars report charging'};
  const power = watts(charger.power,states);
  const match = power > 50 ? home.filter(c=>{
    const own=watts(c.charge_power,states);return own > 50 && Math.abs(own-power)<=Math.max(.2*power,300);
  }) : [];
  if (match.length === 1) return {car:match[0],reason:'matching car power'};
  if (match.length > 1) return {car:null,reason:'multiple cars have matching charge power'};
  const at=charger.at || (Array.isArray(charger.anchor)?charger.anchor:null);
  const near=at?home.map(car=>({car,spot:spots.find(s=>s.car===car.id)})).filter(r=>r.spot?.at)
    .map(r=>({...r,d:Math.hypot(at[0]-r.spot.at[0],at[1]-r.spot.at[1])})).filter(r=>r.d<=30).sort((a,b)=>a.d-b.d):[];
  if (near.length && (near.length===1 || Math.abs(near[0].d-near[1].d)>.01)) return {car:near[0].car,reason:'nearest parking spot'};
  return {car:null,reason:'no charging sensor; place parking spots or set a charging sensor'};
}
export const chargingCar = (charger,cars,states,spots) => chargingDecision(charger,cars,states,spots).car;

export function assignParking(cars, spots, states = {}) {
  const taken=new Set(), result=[];
  const home=cars.filter(c=>carHome(c,states));
  // Reserve assigned spots before a car without a preference takes one.
  for (const car of home) {
    const spot=spots.find(s=>s.assigned===car.id) || spots.find(s=>s.id===car.parking && !s.assigned);
    if(spot && !taken.has(spot)){taken.add(spot);result.push({...spot,car:car.id});}
  }
  for(const car of home)if(!result.some(s=>s.car===car.id)){
    const spot=spots.find(s=>!s.assigned && !taken.has(s));
    if(spot){taken.add(spot);result.push({...spot,car:car.id});}
  }
  return result;
}

// Instantaneous watts only. Allocate before applying the display threshold so
// dropping a small flow never redirects it to a different destination.
export function allocateEnergyFlows(totals, mapping = {}, includeHidden = false) {
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
    ...chargers.map((value, i) => ['charger:' + i, value])
  ].map(([id, value]) => [id, Math.max(0, value)]).filter(([,value]) => includeHidden || flowReading(value).visible));
}

// The four totals always balance: home = solar + battery discharge + grid import
// (in the mapping's signs). One unknown total is derived from the other three;
// with two or more unknown the balance cannot be split, and energyBalance says why.
export function energyBalance(mapping, states, zoneEntities = []) {
  const zoneReadings = zoneEntities.map(id => watts(id, states));
  const read = id => id ? watts(id, states) : undefined;  // undefined = not set, null = unreadable
  const totals = {
    solar: mapping.solar_power ? read(mapping.solar_power)
      : zoneEntities.length ? (zoneReadings.some(v => v === null) ? null : zoneReadings.reduce((s, v) => s + Math.max(0, v), 0)) : undefined,
    battery: read(mapping.battery_power), grid: read(mapping.grid_power), home: read(mapping.house_power)};
  // Roles that do not exist in this house (no battery, no solar) are zero, not unknown.
  const absent = {solar: !mapping.solar_power && !zoneEntities.length, battery: !mapping.battery_power};
  for (const key of ['solar', 'battery']) if (absent[key]) totals[key] = 0;
  const bSign = mapping.battery_positive === 'charge' ? -1 : 1, gSign = mapping.grid_positive === 'export' ? -1 : 1;
  const unknown = Object.keys(totals).filter(key => totals[key] === undefined || totals[key] === null);
  const derived = {};
  if (unknown.length === 1) {
    const [key] = unknown, t = totals;
    if (key === 'home') t.home = Math.max(0, t.solar + bSign * t.battery + gSign * t.grid);
    else if (key === 'grid') t.grid = gSign * (t.home - t.solar - bSign * t.battery);
    else if (key === 'battery') t.battery = bSign * (t.home - t.solar - gSign * t.grid);
    else if (key === 'solar') t.solar = Math.max(0, t.home - bSign * t.battery - gSign * t.grid);
    derived[key] = true;
  }
  const missing = unknown.length > 1 ? unknown : [];
  const supply = totals.solar + bSign * totals.battery + gSign * totals.grid;
  // A derived reading cannot independently prove (or disprove) the balance.
  const residual = unknown.length ? null : totals.home - supply;
  return {totals, derived, missing, known: !missing.length, supply, residual,
    unbalanced: residual !== null && Math.abs(residual) > Math.max(200, .2 * Math.abs(totals.home))};
}

export function energyFlows(mapping, states, zoneEntities = [], includeHidden = false) {
  mapping = migrateEnergy(mapping);
  const balance = energyBalance(mapping, states, zoneEntities), t = balance.totals;
  // An unknown balance is not zero consumption: only direct charger telemetry can still show.
  return allocateEnergyFlows({solar: balance.known ? t.solar : 0, battery: balance.known ? t.battery : 0,
    grid: balance.known ? t.grid : 0, home: balance.known ? t.home : 0,
    chargers: (mapping.chargers || []).map(charger => watts(charger.power, states))}, mapping, includeHidden);
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
