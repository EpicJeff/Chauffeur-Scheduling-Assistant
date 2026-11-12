import { energyBalance, energyFlows, flowReading, watts, chargingDecision, carHome, carCharging, migrateEnergy } from './energy_mapping.js';
import { energyAnchors, energyLocations, resolveEnergyLocation, energyTopology } from './energy_geometry.js';
import { formatGlanceValue } from './glance.js';

const labels = {solar:'Solar', battery:'Battery / inverter', grid:'Meter / grid', house:'Electric panel / house'};
const roleName = id => labels[id] || 'Car charger';
const stem = id => (id || '').replace(/_(?:battery_power|charging_power|charge_power|power|charge|battery_level|battery|soc)$/, '');

// The renderer consumes this same decision, including the unfiltered allocation.
// No diagnostic-only guesses may supply an anchor or change the power balance.
export function energyCheck(view, layout, mapping, states = {}, stale = false, anchors = energyAnchors(view, layout, mapping, states)) {
  mapping=migrateEnergy(mapping);
  const options = energyLocations(view, layout), roles = [];
  const buildings = view.plan?.buildings || [];
  const locationName = option => {
    if (option.ref.type === 'object') {
      const b = buildings.find(b => b.id === option.ref.building), wall = b?.walls?.find(w => w.id === option.host.wall);
      const floor = b?.levels?.find(l => l.id === wall?.level);
      const where = b?.name ? `${wall?.exterior ? 'exterior wall' : 'wall'} of ${b.name}${floor?.name ? ', ' + floor.name : ''}` : 'a wall';
      return `${option.kind.replaceAll('_',' ')} object on ${where}`;
    }
    const m = option.marker, b = buildings.find(b => b.id === m.building);
    const floor = b?.levels?.find(l => l.id === m.level);
    return `placed device ${m.name || ''}${b?.name ? ' in ' + b.name : ''} on ${floor?.name || 'a floor'}`;
  };
  function role(id, entity, ref, kind, at, sign, name = roleName(id)) {
    const entities = id === 'solar' && !entity ? anchors.zoneEntities : [entity].filter(Boolean);
    let status = 'ok', state = 'available';
    if (!entities.length) {status = 'unset'; state = 'not set';}
    else if (stale) {status = 'unavailable'; state = 'unavailable (live readings are stale)';}
    else if (entities.some(e => !states[e] || ['unavailable', 'unknown'].includes(states[e].state))) {status = 'unavailable'; state = 'unavailable';}
    else if (entities.some(e => watts(e, states) === null)) {status = 'invalid'; state = 'not an instantaneous power reading (choose W or kW)';}
    let location;
    if (id === 'solar') {
      const b = buildings.find(b => (!view.plan?.solar_source_building || b.id === view.plan.solar_source_building) &&
        b.solar_zones?.some(z => z.roof === anchors.source && z.state !== 'ghost'));
      location = at ? `solar zone on ${b?.name ? 'roof of ' + b.name : 'a roof'} (source)` : 'not placed: add a solar zone in the editor and choose its source roof';
    }
    else {
      const selected = resolveEnergyLocation(options, ref, entity, kind);
      location = at && selected ? locationName(selected) : `not placed: place ${entity || name} in the editor${kind ? ', or add a ' + kind.replaceAll('_',' ') + ' object and choose it above' : ''}`;
      if (!at && entity) {
        // Device identity from the catalogue is stronger evidence than naming.
        // Names/stems only explain a likely mismatch; they never place anything.
        const device = layout?.devices?.find(d => d.entity_id === entity || d.entities?.includes(entity));
        const pattern = {battery:/battery|powerwall|inverter/i, grid:/meter|grid|site/i, house:/panel|house|home|load/i}[id];
        const other = options.find(o => o.marker && !o.entities.includes(entity) &&
          (device?.device_id === o.ref.id || o.entities.some(e => stem(e) === stem(entity)) ||
            pattern?.test(`${o.marker.name} ${o.entities.join(' ')}`)));
        if (other) location += `. ${other.marker.name || 'A device'} is placed via ${other.marker.entity_id}, but the ${id.startsWith('car:') ? name : id} role uses ${entity}`;
        if (ref !== undefined) location += '. Check the selected location above';
      }
    }
    if (status === 'ok' && !at) status = 'unplaced';
    const power = entities.length ? entities.map(e => `${e}: ${formatGlanceValue({entity:e}, states, mapping)}`).join('; ') : 'not set: choose it above';
    const row = {id, name, entities, status, symbol:status === 'ok' ? '✓' : ['unset', 'unplaced'].includes(status) ? '✗' : '⚠', power, state, sign, location};
    roles.push(row); return row;
  }
  role('solar', mapping.solar_power, null, null, anchors.solar, 'positive = producing');
  role('battery', mapping.battery_power, mapping.locations?.battery, null, anchors.battery,
    `positive = ${mapping.battery_positive === 'charge' ? 'charging' : 'discharging'}`);
  role('grid', mapping.grid_power, mapping.locations?.grid, 'meter', anchors.grid,
    `positive = ${mapping.grid_positive === 'export' ? 'exporting' : 'importing'}`);
  role('house', mapping.house_power, mapping.locations?.house, 'electric_panel', anchors.house,
    `positive = consuming; ${mapping.home_includes_chargers === false ? 'excludes' : 'includes'} car chargers`);
  const matches=(mapping.chargers || []).map((charger,i)=>chargingDecision({...charger,at:anchors.chargers[i]},mapping.cars || [],states,anchors.spots));
  for (const [i, charger] of (mapping.chargers || []).entries()) {
    const row=role('charger:' + i, charger.power, charger.anchor, 'charger', anchors.chargers[i], 'positive = charging', charger.name);
    row.state += matches[i].car ? `; charging ${matches[i].car.name}` : `; car unknown: ${matches[i].reason}`;
    row.car=matches[i].car?.id || null;row.reason=matches[i].reason;
  }
  for(const car of mapping.cars || []){
    const spot=anchors.spots.find(s=>s.car===car.id),home=carHome(car,states);
    roles.push({id:'car:'+car.id,name:car.name,entities:[car.charging,car.charge_power,car.battery_level].filter(Boolean),
      status:spot || !home?'ok':'unplaced',symbol:spot || !home?'✓':'✗',
      power:car.charge_power?`${car.charge_power}: ${formatGlanceValue({entity:car.charge_power},states,mapping)}`:'optional — the car’s own reading is not set',
      state:!home?'away':carCharging(car,states)?'charging':'home; not reporting charging',
      sign:car.charging?`charging state: ${car.charging} (${states[car.charging]?.state || 'unavailable'})`:'no charging sensor',
      location:spot?`Parking spot ${spot.id} in ${buildings.find(b=>b.id===spot.building)?.name || 'the house'}`:`Place a parking spot for ${car.name}`});
  }

  const balance = energyBalance(mapping, states, anchors.zoneEntities);
  const roleOf = key => key === 'home' ? 'house' : key;  // the balance says home; the role is the house panel
  const nameOf = key => roles.find(r => r.id === roleOf(key))?.name || roleName(roleOf(key));
  const unknownBalance = balance.known ? '' : `balance unknown: ${balance.missing.map(nameOf).join(' and ')} not readable`;
  if (!stale && balance.unbalanced) {
    const house = roles.find(r => r.id === 'house');
    house.status = 'unbalanced'; house.symbol = '⚠';
    house.state += `; readings don't balance: solar + battery + grid = ${(balance.supply / 1000).toFixed(1)} kW, house reads ${(balance.totals.home / 1000).toFixed(1)} kW — is the house sensor right? (${mapping.house_power})`;
  }
  const allocated = energyFlows(mapping, states, anchors.zoneEntities, true);
  const topology = new Set(energyTopology(anchors, mapping).map(row => row.id));
  const flows = Object.entries(allocated).map(([id, watts]) => {
    const endpoints = id.startsWith('charger:') ? ['house', id] : id.split(':');
    const missing = endpoints.find(id => !roles.find(r => r.id === id)?.location ||
      !(id.startsWith('charger:') ? anchors.chargers[Number(id.split(':')[1])] : anchors[id]));
    const status = stale ? 'hidden: live readings unavailable' : unknownBalance && !id.startsWith('charger:') ? `hidden: ${unknownBalance}` :
      !flowReading(watts).visible ? balance.unbalanced && !id.startsWith('charger:') ? "hidden: readings don't balance — check the Electric panel / house sensor" : 'hidden (under 50 W)' :
      !topology.has(id) ? `no ribbon: ${roles.find(r => r.id === missing)?.name || roleName(missing)} not placed` : 'shown';
    return {id, watts, status, shown:status === 'shown', name:endpoints.map(id => roles.find(r => r.id === id)?.name || roleName(id)).join(' → ')};
  });
  const showing = flows.filter(f => f.shown).length;
  const blocked = flows.find(f => f.watts >= 50 && !f.shown);
  // Battery and grid are optional to the balance. Never blame an unused role
  // when every allocated transfer is simply below the display threshold.
  const missingInput = roles.find(r => r.status === 'unavailable' || r.status === 'invalid' ||
    r.status === 'unset' && r.id === 'house');
  const reason = stale ? 'live readings are unavailable' : unknownBalance ||
    (balance.unbalanced && !flows.some(f => f.watts >= 50) ? "the readings don't balance — check the Electric panel / house sensor" : '') || blocked?.status.replace(/^no ribbon: /, '') ||
    (missingInput ? `${missingInput.name} power ${missingInput.state}` : 'all allocated flows are under 50 W');
  const derivedNote = stale ? '' : Object.keys(balance.derived).map(key => `${nameOf(key)} worked out from the other three readings`).join('; ');
  return {roles, flows, showing, derived: derivedNote,
    summary:(showing ? `Ribbons showing: ${showing}` : `No ribbons because ${reason}`) + (derivedNote ? ` (${derivedNote})` : '')};
}

// One builder for the drawer and the read-only Energy legend on wall panels.
export function renderEnergyCheck(host, check) {
  host.replaceChildren();
  const summary = document.createElement('p'); summary.dataset.energySummary = ''; summary.textContent = check.summary; host.append(summary);
  for (const row of check.roles) {
    const group = document.createElement('fieldset'), title = document.createElement('legend');
    group.dataset.energyRole = row.id; group.dataset.status = row.status;
    const mark = document.createElement('span'), name = document.createElement('strong');
    mark.dataset.energyMark = row.symbol === '✓' ? 'ok' : row.symbol === '⚠' ? 'warning' : 'error';
    mark.textContent = row.symbol; name.textContent = row.name;
    title.append(mark, document.createTextNode(' '), name); group.append(title);
    for (const [label, text] of [['Power entity', row.power], ['State', row.state], ['Sign', row.sign], ['Location', row.location]]) {
      const line = document.createElement('p'); line.textContent = `${label}: ${text}`; group.append(line);
    }
    host.append(group);
  }
  const title = document.createElement('h4'); title.textContent = 'Flows'; host.append(title);
  for (const row of check.flows) {
    const line = document.createElement('p'); line.dataset.energyFlow = row.id;
    line.dataset.status = row.shown ? 'shown' : row.status.startsWith('hidden (') ? 'hidden' : 'blocked';
    line.textContent = `${row.name}: ${Number(row.watts.toFixed(1))} W — ${row.status}`; host.append(line);
  }
}
