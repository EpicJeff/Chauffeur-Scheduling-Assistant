import * as THREE from 'three';
import { FT } from '../twin_generator.js';
import { groundAt } from '../twin_ground.js';
import { hostPoint, parkingPoint } from '../twin_hosts.js';
import { solarZones, solarPoint } from '../twin_solar.js';
import { assignParking, migrateEnergy, carHome } from './energy_mapping.js';

export function lotPoint(building, [x, y, z = 0], plan) {
  const a = (building.rotation || 0) * Math.PI / 180, p = building.position || [0, 0];
  return [p[0] + Math.cos(a) * x - Math.sin(a) * y, p[1] + Math.sin(a) * x + Math.cos(a) * y,
    z + (building.base || 0) + groundAt(plan, ...p)];
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
// Use a fixed width budget, not live power, so a push never moves a route.
export function flowFans(rows, width) {
  const groups = new Map();
  for (const row of rows) for (const key of new Set([JSON.stringify(row.from), JSON.stringify(row.to)])) {
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row.id);
  }
  for (const ids of groups.values()) ids.sort();
  return new Map(rows.map(row => {
    const departures = groups.get(JSON.stringify(row.from));
    const peers = departures.length > 1 ? departures : groups.get(JSON.stringify(row.to));
    const index = peers.indexOf(row.id);
    // Paired slots: -.5, +.5, -1.5, +1.5, ... . Odd groups must not
    // leave their middle ribbon on the unfanned centreline either.
    const lane = peers.length > 1 ? (Math.floor(index / 2) + .5) * (index % 2 ? 1 : -1) : 0;
    return [row.id, {offset: lane * 3 * width, tilt: Math.sign(lane) * Math.PI / 15}];
  }));
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
  const length = Math.hypot(dx, dz), perpendicular = length ? new THREE.Vector3(-dz / length, 0, dx / length) : new THREE.Vector3(1, 0, 0);
  control.addScaledVector(perpendicular, lateral / (2 * t * (1 - t)));
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
    marker:m, at:[m.at[0],m.at[1],m.at[2]+groundAt(view.plan,...(view.plan?.buildings.find(b=>b.id===m.building)?.position || [0,0]))]});
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
