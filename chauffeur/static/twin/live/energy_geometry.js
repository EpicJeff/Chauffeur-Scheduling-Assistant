import * as THREE from 'three';
import { FT } from '../twin_generator.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { hostPoint, parkingPoint } from '../twin_hosts.js';
import { solarZones, solarPoint } from '../twin_solar.js';
import { assignParking, migrateEnergy, carHome } from './energy_mapping.js';

export function lotPoint(building, [x, y, z = 0], plan) {
  const a = (building.rotation || 0) * Math.PI / 180, p = building.position || [0, 0];
  return [p[0] + Math.cos(a) * x - Math.sin(a) * y, p[1] + Math.sin(a) * x + Math.cos(a) * y,
    z + (building.base || 0) + buildingGround(plan, building)];
}
export const worldPoint = p => new THREE.Vector3(p[0] * FT, p[2] * FT, -p[1] * FT);
export function roofPoints(surfaces, plan) {
  const points = [];
  for (const [id, roof] of surfaces || []) {
    const building = plan.buildings.find(b => b.id === id); if (!building) continue;
    for (let i = 0; i < roof.positions.length; i += 3) points.push(worldPoint(lotPoint(building, roof.positions.slice(i, i + 3), plan)));
  }
  return points;
}
export const flowRoute = (from,to) => ({from:[...from],to:[...to]});
export function flowApex(curve) {
  const {v0:a, v1:c, v2:b} = curve, denominator = a.y - 2 * c.y + b.y;
  return curve.getPoint(denominator ? Math.max(0, Math.min(1, (a.y - c.y) / denominator)) : .5);
}
// Ribbons sharing an end whose headings are within this angle, or whose natural peaks would
// sit within four ribbon widths, can overlap or cross: they fan as one group.
const FAN_ANGLE = 35 * Math.PI / 180;
// Use a fixed width budget, not live power, so a push never moves a route.
// A group fans in the order its ribbons head away from the shared end (ties by id). Each
// bend stays inside the sector halfway to its distinct neighbours at BOTH ends. A
// ribbon alone in its heading bends half a slot to its own left: two ribbons leaving in
// opposite directions then part to opposite sides and their labels never stack.
export function flowFans(rows, width) {
  // Opposite transfers on one physical route never flow together. Give them one
  // representative (stable by id), so an inactive reverse cannot consume a slot
  // or choose the other end's fan when the power changes sign.
  const routes = [], representatives = new Map(), unmatched = new Map();
  for (const row of [...rows].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0)) {
    const forward = JSON.stringify([row.from, row.to]), reverse = JSON.stringify([row.to, row.from]);
    const peer = unmatched.get(reverse)?.pop();
    if (peer) representatives.set(row.id, peer.id);
    else {
      representatives.set(row.id, row.id); routes.push(row);
      if (!unmatched.has(forward)) unmatched.set(forward, []);
      unmatched.get(forward).push(row);
    }
  }
  const groups = new Map(), metrics = new Map(routes.map(row => {
    const curve = flowCurve(row.from, row.to), {v0:a, v1:c, v2:b} = curve;
    const apex = flowApex(curve), t = (a.y - c.y) / (a.y - 2 * c.y + b.y);
    return [row.id, {apex, rise: apex.y - Math.max(a.y, b.y), t, limit: Infinity}];
  }));
  for (const row of routes) for (const [end, other] of [[row.from, row.to], [row.to, row.from]]) {
    const key = JSON.stringify(end);
    if (!groups.has(key)) groups.set(key, new Map());
    const a = worldPoint(end), b = worldPoint(other), dx = b.x - a.x, dz = b.z - a.z;
    groups.get(key).set(row.id, {id: row.id, angle: Math.atan2(dz, dx), dx, dz,
      length: Math.hypot(dx, dz), ...metrics.get(row.id)});
  }
  const angleGap = (a, b) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));
  // Bound the control point at both ends. The entire ground track then stays
  // inside the sector halfway to every distinct neighbouring heading.
  for (const members of groups.values()) for (const member of members.values()) for (const peer of members.values()) {
    const gap = angleGap(member.angle, peer.angle);
    if (gap > 1e-9 && gap < Math.PI - 1e-9) {
      const metric = metrics.get(member.id);
      metric.limit = Math.min(metric.limit, member.length / 2 * Math.tan(gap / 2));
    }
  }
  const clusters = new Map();
  for (const [key, members] of groups) {
    const sorted = [...members.values()].sort((a, b) => a.angle - b.angle || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    const gap = i => i === sorted.length - 1 ? sorted[0].angle + 2 * Math.PI - sorted[i].angle : sorted[i + 1].angle - sorted[i].angle;
    // Walk the circle from just after the widest gap, so no group straddles the walk's start.
    let widest = sorted.length - 1;
    for (let i = 0; i < sorted.length; i++) if (gap(i) > gap(widest)) widest = i;
    const found = [];
    for (let i = 0; i < sorted.length; i++) {
      const member = sorted[(widest + 1 + i) % sorted.length], previous = found.at(-1)?.at(-1);
      if (!previous || gap((widest + i) % sorted.length) > FAN_ANGLE && member.apex.distanceTo(previous.apex) >= 4 * width) found.push([]);
      found.at(-1).push(member);
    }
    clusters.set(key, found);
  }
  const lane = (key, id) => {
    const cluster = clusters.get(key).find(c => c.some(m => m.id === id));
    const index = cluster.findIndex(m => m.id === id);
    const member = cluster[index], length = member.length || 1;
    // Slots one apart: -.5, +.5 for a pair; an odd group shifts half a slot (-.5, +.5, +1.5)
    // so its middle ribbon still leaves the shared centreline; a lone ribbon takes +.5.
    const slotAt = i => i - (cluster.length - 1) / 2 + (cluster.length % 2 ? .5 : 0);
    const slot = slotAt(index), sign = Math.sign(slot);
    const requested = (m, s) => Math.abs((s * 3 * width + Math.tan(Math.sign(s) * Math.PI / 15) * m.rise) / (2 * m.t * (1 - m.t)));
    const bend = Math.min(requested(member, slot), metrics.get(id).limit);
    return {slot, side: member.length ? [-member.dz / length, member.dx / length] : [1, 0], bend: sign * bend,
      shared: groups.get(key).size > 1, grouped: cluster.length > 1};
  };
  const fans = new Map(routes.map(row => {
    const ends = [lane(JSON.stringify(row.from), row.id), lane(JSON.stringify(row.to), row.id)];
    const chosen = ends.find(e => e.grouped) || ends.find(e => e.shared);
    if (!chosen) return [row.id, {offset: 0, tilt: 0}];
    return [row.id, {offset: chosen.slot * 3 * width, tilt: Math.sign(chosen.slot) * Math.PI / 15,
      side: chosen.side, bend: chosen.bend}];
  }));
  // Collinear routes share a sector. Nest them consistently across BOTH ends,
  // even when each route chose a different end's fan. With a common side and
  // bend / length² increasing by length, a longer track surrounds a shorter
  // one at either shared end. Equal lengths use id to keep distinct lanes.
  const parents = new Map(routes.map(row => [row.id, row.id]));
  const find = id => parents.get(id) === id ? id : find(parents.get(id));
  for (const members of groups.values()) for (const a of members.values()) for (const b of members.values()) {
    const gap = angleGap(a.angle, b.angle);
    if (a.length && b.length && (gap < 1e-9 || Math.PI - gap < 1e-9)) parents.set(find(a.id), find(b.id));
  }
  const parallel = new Map();
  for (const row of routes) {
    const fan = fans.get(row.id), a = worldPoint(row.from), b = worldPoint(row.to);
    let dx = b.x - a.x, dz = b.z - a.z;
    if (dx < 0 || dx === 0 && dz < 0) { dx = -dx; dz = -dz; }
    const length = Math.hypot(dx, dz); if (!length || !fan.bend) continue;
    const sign = Math.sign(fan.bend * (-dz * fan.side[0] + dx * fan.side[1]));
    const key = JSON.stringify([find(row.id), sign]);
    if (!parallel.has(key)) parallel.set(key, []);
    parallel.get(key).push({id: row.id, fan, length});
  }
  for (const members of parallel.values()) if (members.length > 1) {
    members.sort((a, b) => a.length - b.length || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    const factor = (m, i) => (i + .5) * m.length ** 2;
    let scale = Math.max(...members.map((m, i) => Math.abs(m.fan.bend) / factor(m, i)));
    scale = Math.min(scale, ...members.map((m, i) => metrics.get(m.id).limit / factor(m, i)));
    for (const [i, m] of members.entries()) m.fan.bend = Math.sign(m.fan.bend) * scale * factor(m, i);
  }
  return new Map(rows.map(row => [row.id, fans.get(representatives.get(row.id))]));
}
export function flowCurve(from, to, fan = {}) {
  const route = flowRoute(from, to), a = worldPoint(route.from), b = worldPoint(route.to);
  const span = Math.hypot(b.x - a.x, b.z - a.z) / FT;
  const rise = (span < 4 ? 2 + span / 4 : Math.max(3, Math.min(10, .3 * span))) * FT;
  const height = Math.max(a.y, b.y) + rise;
  const control = a.clone().add(b).multiplyScalar(.5);
  // Solve the quadratic's actual maximum, including unequal endpoint heights.
  control.y = height + Math.sqrt((height - a.y) * (height - b.y));
  const curve = new THREE.QuadraticBezierCurve3(a, control, b);
  const t = (a.y - control.y) / (a.y - 2 * control.y + b.y);
  const lateral = (fan.offset || 0) + Math.tan(fan.tilt || 0) * rise;
  // A quadratic remains planar through its three control points. Canonical
  // horizontal orientation keeps lanes consistent even for reversed flows.
  let dx = b.x - a.x, dz = b.z - a.z;
  if (dx < 0 || dx === 0 && dz < 0) {dx = -dx; dz = -dz;}
  const length = Math.hypot(dx, dz);
  // A fan names its own side (relative to the shared end's heading); otherwise canonical.
  const perpendicular = fan.side ? new THREE.Vector3(fan.side[0], 0, fan.side[1])
    : length ? new THREE.Vector3(-dz / length, 0, dx / length) : new THREE.Vector3(1, 0, 0);
  control.addScaledVector(perpendicular, fan.bend ?? lateral / (2 * t * (1 - t)));
  return curve;
}
// Security's indoor camera fallback still uses the building centre.
export function buildingCentre(building, plan) {
  const points=(building.rooms || []).flatMap(r=>r.polygon || []).concat((building.levels || []).flatMap(l=>l.outline || []));
  const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
  return lotPoint(building,points.length?[(Math.min(...xs)+Math.max(...xs))/2,(Math.min(...ys)+Math.max(...ys))/2,4]:[0,0,4],plan);
}
// Location references are explicit; an omitted preference only matches a placed
// HA device by its power entity. A removed reference never falls back elsewhere.
export function energyLocations(view, layout) {
  const options=[];
  for(const m of layout?.markers || [])if(m.placed && m.location_valid!==false)options.push({ref:{type:'device',id:m.device_id},label:'Placed device: '+(m.name || m.device_id),entities:[m.entity_id,...(m.entities || [])].filter(Boolean),
    marker:m, at:[m.at[0],m.at[1],m.at[2]+buildingGround(view.plan,view.plan?.buildings.find(b=>b.id===m.building))]});
  for(const b of view.plan?.buildings || [])for(const p of b.anchors || [])if(['meter','electric_panel','charger'].includes(p.kind) && p.state!=='ghost'){
    try{options.push({ref:{type:'object',id:p.id,building:b.id},kind:p.kind,host:p.host,label:(p.name || {meter:'Meter',electric_panel:'Electric panel',charger:'Charger'}[p.kind])+' object: '+(b.name || b.id)+' / '+p.id,at:lotPoint(b,hostPoint(b,p.host,(p.offset || 0)+.04),view.plan)});}catch{}
  }
  return options;
}
export function resolveEnergyLocation(options,ref,entity,kind) {
  return ref===undefined?options.find(o=>o.ref.type==='device' && entity && o.entities.includes(entity)):
    ref && options.find(o=>o.ref.type===ref.type && o.ref.id===ref.id && (ref.type==='device' || o.ref.building===ref.building && o.kind===kind));
}
export function parkingObjects(view) {
  const spots=[];
  for(const b of view.plan?.buildings || [])for(const p of b.anchors || [])if(p.kind==='parking' && p.state!=='ghost'){
    try{spots.push({id:p.id,building:b.id,assigned:p.car || null,at:lotPoint(b,parkingPoint(b,p,view.plan,(p.offset || 0)+.08,groundAt),view.plan)});}catch{}
  }
  return spots;
}
export const parkingSpots = (view,mapping,states = {}) => assignParking(mapping.cars || [],parkingObjects(view),states);
export function energyAnchors(view,layout,mapping,states = {}) {
  mapping=migrateEnergy(mapping);
  const options=energyLocations(view,layout),locations=mapping.locations || {};
  const resolve=(ref,entity,kind)=>{
    const option=resolveEnergyLocation(options,ref,entity,kind);
    return option?.at || null;
  };
  const zones=(view.plan?.buildings || []).flatMap(b=>solarZones(b).map(z=>({...z,building:b})));
  const roofs=[...new Set(zones.map(z=>JSON.stringify([z.building.id,z.zone.roof])))],only=roofs.length===1?JSON.parse(roofs[0]):null;
  const source=view.plan?.solar_source_roof || only?.[1] || null,owner=view.plan?.solar_source_roof?view.plan.solar_source_building:only?.[0];
  const matched=zones.filter(z=>z.zone.roof===source && (!owner || z.building.id===owner));
  const sourceZones=!owner && new Set(matched.map(z=>z.building.id)).size>1?[]:matched;
  let area=0,solar=[0,0,0];
  for(const {zone:z,building:b} of sourceZones){const r=z.rect,weight=(r[2]-r[0])*(r[3]-r[1]),at=lotPoint(b,solarPoint(z.plane,[(r[0]+r[2])/2,(r[1]+r[3])/2],.15),view.plan);area+=weight;solar=solar.map((v,i)=>v+at[i]*weight);}
  return {solar:area?solar.map(v=>v/area):null,source,zoneEntities:[...new Set(sourceZones.map(z=>z.zone.entity).filter(Boolean))],
    battery:resolve(locations.battery,mapping.battery_power),grid:resolve(locations.grid,mapping.grid_power,'meter'),house:resolve(locations.house,mapping.house_power,'electric_panel'),
    chargers:(mapping.chargers || []).map(c=>resolve(c.anchor,c.power,'charger')),
    parking:parkingObjects(view),spots:parkingSpots(view,mapping,states),homeCars:(mapping.cars || []).filter(c=>carHome(c,states)).map(c=>c.id)};
}
export function energyTopology(a,mapping) {
  mapping=migrateEnergy(mapping);
  // Precreate every physically possible transfer, including both directions of
  // the battery/grid pair. A power/sign push only changes visibility/uniforms.
  const rows=[];
  for(const [source,target] of [['solar','house'],['solar','battery'],['solar','grid'],
    ['battery','house'],['grid','house'],['grid','battery'],['battery','grid']])
    if(a[source] && a[target])rows.push({id:source+':'+target,from:a[source],to:a[target],source});
  for(const [i,charger] of (mapping.chargers || []).entries())if(charger.power && a.house && a.chargers[i])
    rows.push({id:'charger:'+i,from:a.house,to:a.chargers[i],source:'car'});
  return rows;
}
export function energyPlacementLegend(a,mapping) {
  const notes=[];
  if(!a.solar)notes.push('Place a solar zone and choose its source roof to see solar flow');
  if(!a.battery && mapping.battery_power)notes.push('Place the battery or inverter to see battery flow');
  if(!a.house)notes.push('Place the electric panel to see house flow');
  if(!a.grid)notes.push('Place the meter to see grid flow');
  for(const [i,c] of (mapping.chargers || []).entries())if(c.power && !a.chargers?.[i])notes.push('Place '+c.name+' to see charging flow');
  for(const c of mapping.cars || [])if((!a.homeCars || a.homeCars.includes(c.id)) && !a.spots?.some(s=>s.car===c.id))notes.push('Place a parking spot for '+c.name);
  return notes.join(' | ');
}
