import { energyFlows, flowReading, watts } from './energy_mapping.js';
import { energyAnchors, energyLocations, resolveEnergyLocation, energyTopology } from './energy_geometry.js';
import { formatGlanceValue } from './glance.js';

const labels = {solar:'Solar', battery:'Battery / inverter', grid:'Meter / grid', house:'Electric panel / house'};
const roleName = id => labels[id] || 'Car charger';
const stem = id => (id || '').replace(/_(?:battery_power|charging_power|charge_power|power|charge|battery_level|battery|soc)$/, '');

// The renderer consumes this same decision, including the unfiltered allocation.
// No diagnostic-only guesses may supply an anchor or change the power balance.
export function energyCheck(view, layout, mapping, states = {}, stale = false, anchors = energyAnchors(view, layout, mapping)) {
  const options = energyLocations(view, layout), roles = [];
  const locationName = option => {
    if (option.ref.type === 'object') return `${option.kind === 'meter' ? 'meter' : 'electric panel'} object on wall ${option.host.wall}`;
    const m = option.marker, b = view.plan?.buildings.find(b => b.id === m.building);
    const floor = b?.levels?.find(l => l.id === m.level);
    return `placed device ${m.name || m.device_id} on ${floor?.name || m.level || 'floor not named'}`;
  };
  function role(id, entity, ref, kind, at, sign, name = roleName(id)) {
    const entities = id === 'solar' && !entity ? anchors.zoneEntities : [entity].filter(Boolean);
    let status = 'ok', state = 'available';
    if (!entities.length) {status = 'unset'; state = 'not set';}
    else if (stale) {status = 'unavailable'; state = 'unavailable (live readings are stale)';}
    else if (entities.some(e => !states[e] || ['unavailable', 'unknown'].includes(states[e].state))) {status = 'unavailable'; state = 'unavailable';}
    else if (entities.some(e => watts(e, states) === null)) {status = 'invalid'; state = 'not an instantaneous power reading (choose W or kW)';}
    let location;
    if (id === 'solar') location = at ? `solar zone on roof ${anchors.source} (source)` : 'not placed: add a solar zone in the editor and choose its source roof';
    else {
      const selected = resolveEnergyLocation(options, ref, entity, kind);
      location = at && selected ? locationName(selected) : `not placed: place ${entity || name} in the editor${kind ? ', or add ' + (kind === 'meter' ? 'a meter' : 'an electric panel') + ' object and choose it above' : ''}`;
      if (!at && entity) {
        // Device identity from the catalogue is stronger evidence than naming.
        // Names/stems only explain a likely mismatch; they never place anything.
        const device = layout?.devices?.find(d => d.entity_id === entity || d.entities?.includes(entity));
        const pattern = {battery:/battery|powerwall|inverter/i, grid:/meter|grid|site/i, house:/panel|house|home|load/i}[id];
        const other = options.find(o => o.marker && !o.entities.includes(entity) &&
          (device?.device_id === o.ref.id || o.entities.some(e => stem(e) === stem(entity)) ||
            pattern?.test(`${o.marker.name} ${o.entities.join(' ')}`)));
        if (other) location += `. ${other.marker.name || other.ref.id} is placed via ${other.marker.entity_id}, but the ${id.startsWith('car:') ? name : id} role uses ${entity}`;
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
  for (const [i, car] of (mapping.cars || []).entries())
    role('car:' + i, car.charge_power, car.anchor, null, anchors.cars[i], 'positive = charging', `${car.name} charger`);

  const allocated = energyFlows(mapping, states, anchors.zoneEntities, true);
  const topology = new Set(energyTopology(anchors, mapping).map(row => row.id));
  const flows = Object.entries(allocated).map(([id, watts]) => {
    const endpoints = id.startsWith('car:') ? ['house', id] : id.split(':');
    const missing = endpoints.find(id => !roles.find(r => r.id === id)?.location ||
      !(id.startsWith('car:') ? anchors.cars[Number(id.split(':')[1])] : anchors[id]));
    const status = stale ? 'hidden: live readings unavailable' : !flowReading(watts).visible ? 'hidden (under 50 W)' :
      !topology.has(id) ? `no ribbon: ${roles.find(r => r.id === missing)?.name || roleName(missing)} not placed` : 'shown';
    return {id, watts, status, shown:status === 'shown', name:endpoints.map(id => roles.find(r => r.id === id)?.name || roleName(id)).join(' → ')};
  });
  const showing = flows.filter(f => f.shown).length;
  const blocked = flows.find(f => f.watts >= 50 && !f.shown);
  // Battery and grid are optional to the balance. Never blame an unused role
  // when every allocated transfer is simply below the display threshold.
  const missingInput = roles.find(r => r.status === 'unavailable' || r.status === 'invalid' ||
    r.status === 'unset' && r.id === 'house');
  const reason = stale ? 'live readings are unavailable' : blocked?.status.replace(/^no ribbon: /, '') ||
    (missingInput ? `${missingInput.name} power ${missingInput.state}` : 'all allocated flows are under 50 W');
  return {roles, flows, showing, summary:showing ? `Ribbons showing: ${showing}` : `No ribbons because ${reason}`};
}

// One builder for the drawer and the read-only Energy legend on wall panels.
export function renderEnergyCheck(host, check) {
  host.replaceChildren();
  const summary = document.createElement('p'); summary.dataset.energySummary = ''; summary.textContent = check.summary; host.append(summary);
  for (const row of check.roles) {
    const group = document.createElement('fieldset'), title = document.createElement('legend');
    group.dataset.energyRole = row.id; group.dataset.status = row.status; title.textContent = `${row.symbol} ${row.name}`; group.append(title);
    for (const [label, text] of [['Power entity', row.power], ['State', row.state], ['Sign', row.sign], ['Location', row.location]]) {
      const line = document.createElement('p'); line.textContent = `${label}: ${text}`; group.append(line);
    }
    host.append(group);
  }
  const title = document.createElement('h4'); title.textContent = 'Flows'; host.append(title);
  for (const row of check.flows) {
    const line = document.createElement('p'); line.dataset.energyFlow = row.id;
    line.textContent = `${row.name}: ${Number(row.watts.toFixed(1))} W — ${row.status}`; host.append(line);
  }
}
