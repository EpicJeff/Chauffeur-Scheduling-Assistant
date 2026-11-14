// Resolved geometry uses absolute lot feet [x, y, height]. Photometry uses SI:
// candela for point/spot, cd/m² for area/line (three's RectAreaLight convention).
// No DOM, scene objects, state mutation or bake dependency in this resolver.
import { roomFloor } from '../twin_floors.js';
import { FT, LAMP_HEIGHT, lightRange } from '../twin_light_math.js';
import { groundAt, buildingGround, edgeDistance } from '../twin_ground.js';
import { pathOutline } from '../path_shapes.js';
import { firePitOptions, firePitLayout, gasTableLayout } from '../fire_pits.js';
import { lightColor, lightIntensity } from './real_lights.js';

export const DEFAULT_OUTPUT_LM = 503;
const pieces = value => Array.isArray(value) ? value : value ? [value] : [];
const length = path => path.slice(1).reduce((sum, p, i) => sum + Math.hypot(...p.map((v, k) => v - path[i][k])), 0);
const spanOf = room => room?.polygon?.length ? Math.max(...[0, 1].map(k =>
  Math.max(...room.polygon.map(p => p[k])) - Math.min(...room.polygon.map(p => p[k]))), 1) : 10;
const world = at => [at[0] * FT, at[2] * FT, -at[1] * FT];
const domainOf = entity => entity?.split('.')[0];
// Plain on/off sources light at full output in 2700 K, like a switch.
const ON_OFF = ['switch', 'input_boolean', 'fan'];

// Staleness is explicit, as in the live feed. HA's last_changed is not freshness:
// a lamp may legitimately have stayed on for days.
export function emission(state, domain) {
  const attributes = state?.attributes || {};
  const rgb = ON_OFF.includes(domain) ? lightColor({color_temp_kelvin: 2700})
    : domain === 'media_player' ? lightColor({color_temp_kelvin: 6500}) : lightColor(attributes);
  const on = !!state && !state.stale && state.reachable !== false &&
    (domain === 'media_player' ? ['on', 'playing', 'paused'].includes(state.state)
      : (domain === 'light' || ON_OFF.includes(domain)) && state.state === 'on');
  return {on, brightness: !on ? 0 : domain === 'light' ? lightIntensity(attributes) : domain === 'media_player' ? .3 : 1, rgb};
}

function reference(plan, fixture, point) {
  // A snapped run's heights were resolved by the server, whose building frame
  // has no auto-foundation lift (buildingGround): wall and step tops are
  // base + elevation + height there, while site hosts are true lot heights.
  // So a snapped run gets the lift from its host, never from its ref.
  const snapped = fixture.shape === 'line' && !!fixture.snap;
  const hostKind = fixture.snap?.host?.kind;
  const host = hostKind === 'wall' || hostKind === 'step' ? plan.buildings?.find(b =>
    (b[hostKind === 'wall' ? 'walls' : 'stairs'] || []).some(p => p.id === fixture.snap.host.id)) : null;
  const lift = snapped && host ? buildingGround(plan, host) : 0;
  if (fixture.ref === 'ground') return groundAt(plan, ...point) + lift;
  if (fixture.ref === 'floor') {
    const b = plan.buildings?.find(b => b.id === fixture.building);
    const l = b?.levels?.find(l => l.id === fixture.level);
    // Orphaned fixtures keep their stored coordinates when the floor is gone.
    return l ? (b.base || 0) + l.elevation + (snapped ? lift : buildingGround(plan, b)) : 0;
  }
  return lift;
}

// Outward, in lot feet. Unsnapped geometry uses the right of its drawn path.
function hostNormal(fixture, plan) {
  const snap = fixture.snap;
  const path = fixture.path || [fixture.at, fixture.at?.map((v, i) => v + (i === 0 ? 1 : 0))];
  const a = snap?.edge?.from || path[0], b = snap?.edge?.to || path.at(-1);
  const dx = b[0] - a[0], dy = b[1] - a[1], distance = Math.hypot(dx, dy) || 1;
  let normal = [dy / distance, -dx / distance, 0];
  const host = snap?.host;
  if (host?.kind === 'step') {
    // services/twin_fixtures.py builds each tread's leading edge across the
    // run, climbing from the stair's from to its to. Outward is downhill (the
    // negated run), so a riser light sits off the nosing, not inside the step.
    const owner = plan.buildings?.find(b => b.stairs?.some(s => s.id === host.id));
    const stair = owner?.stairs?.find(s => s.id === host.id);
    if (stair?.from && stair?.to) {
      const angle = (owner.rotation || 0) * Math.PI / 180;
      const rx = stair.to[0] - stair.from[0], ry = stair.to[1] - stair.from[1];
      const run = [rx * Math.cos(angle) - ry * Math.sin(angle), rx * Math.sin(angle) + ry * Math.cos(angle)];
      const d = Math.hypot(...run);
      if (d > 0) return [-run[0] / d, -run[1] / d, 0];
    }
    return normal;
  }
  if (host?.kind === 'fence') {
    // A fence has no inside. 'out' is the right of the fence's drawn
    // direction (its polyline order), whatever order the snap stored.
    const line = pieces(plan.site?.fence).find(p => p.id === host.id)?.polyline || [];
    const segments = line.slice(1).map((q, i) => ({p: line[i], q}));
    segments.sort((u, v) => edgeDistance(a, u.p, u.q) + edgeDistance(b, u.p, u.q)
      - edgeDistance(a, v.p, v.q) - edgeDistance(b, v.p, v.q));
    if (segments.length) {
      const {p, q} = segments[0], d = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1;
      normal = [(q[1] - p[1]) / d, -(q[0] - p[0]) / d, 0];
    }
    return normal;
  }
  let outline;
  if (host?.kind === 'retaining_wall') outline = plan.site?.terraces?.find(p => p.id === host.id)?.polygon;
  if (host?.kind === 'hardscape') {
    const p = pieces(plan.site?.hardscape).find(p => p.id === host.id);
    outline = p?.kind === 'path' ? pathOutline(p) : p?.polygon;
  }
  if (host?.kind === 'wall') {
    const owner = plan.buildings?.find(b => b.walls?.some(w => w.id === host.id));
    const wall = owner?.walls?.find(w => w.id === host.id);
    const room = owner?.rooms?.find(r => r.level === wall.level && r.polygon?.some((p, i) =>
      edgeDistance(wall.from, p, r.polygon[(i + 1) % r.polygon.length]) < .5 &&
      edgeDistance(wall.to, p, r.polygon[(i + 1) % r.polygon.length]) < .5));
    if (room) {
      const angle = (owner.rotation || 0) * Math.PI / 180, pos = owner.position || [0, 0];
      outline = room.polygon.map(([x, y]) => [pos[0] + x * Math.cos(angle) - y * Math.sin(angle),
        pos[1] + x * Math.sin(angle) + y * Math.cos(angle)]);
    }
  }
  if (outline?.length >= 3) {
    const winding = Math.sign(outline.reduce((sum, p, i) => {
      const q = outline[(i + 1) % outline.length]; return sum + p[0] * q[1] - p[1] * q[0];
    }, 0)) || 1;
    // Match the physical boundary, independent of the snap's endpoint order.
    const edges = outline.map((p, i) => ({p, q: outline[(i + 1) % outline.length]}));
    edges.sort((u, v) => edgeDistance(a, u.p, u.q) + edgeDistance(b, u.p, u.q)
      - edgeDistance(a, v.p, v.q) - edgeDistance(b, v.p, v.q));
    const {p, q} = edges[0], d = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1;
    normal = [winding * (q[1] - p[1]) / d, -winding * (q[0] - p[0]) / d, 0];
    if (host.kind === 'retaining_wall') {
      const mid = a.map((v, i) => (v + b[i]) / 2);
      const inside = groundAt(plan, mid[0] - normal[0] * .05, mid[1] - normal[1] * .05);
      const outside = groundAt(plan, mid[0] + normal[0] * .05, mid[1] + normal[1] * .05);
      if (outside > inside) normal = normal.map(v => -v);
    }
  }
  return normal;
}

function resolveFixture(fixture, plan) {
  const f = {...fixture};
  const lift = p => [p[0], p[1], p[2] + reference(plan, f, p)];
  if (f.at) f.at = lift(f.at);
  if (f.aim) f.aim = lift(f.aim);
  if (f.path) f.path = f.path.map(lift);
  if (f.shape === 'line' || f.shape === 'area') {
    f.facing ??= 'down';
    const normal = hostNormal(f, plan);
    f.normal = Array.isArray(f.facing) ? [...f.facing] : f.facing === 'up' ? [0, 0, 1]
      : f.facing === 'down' ? [0, 0, -1] : normal.map(v => v * (f.facing === 'in' ? -1 : 1));
    // Lines store the drawn attachment path. Only a host has a face to stand
    // off, so an unsnapped drawn line keeps its plan position and only drops
    // under (down) or lifts over (up) its path. Derived burners already sit on
    // the burning bed.
    if (!f.fire_pit && (f.shape === 'line' || f.snap)) {
      const outward = !f.snap ? 0 : f.facing === 'down' || f.facing === 'out' ? 1 / 12 : f.facing === 'in' ? -1 / 12 : 0;
      const dz = f.facing === 'down' ? -2 / 12 : f.facing === 'up' ? 1 / 12 : 0;
      const offset = p => [p[0] + normal[0] * outward, p[1] + normal[1] * outward, p[2] + dz];
      if (f.path) f.path = f.path.map(offset);
      if (f.at) f.at = offset(f.at);
    }
    if (f.shape === 'line') f.width_in ??= .5;
  }
  if (f.shape === 'spot') { f.cone_deg ??= 90; f.softness ??= .3; }
  return f;
}

function weight(f) {
  return f.share ?? (f.shape === 'line' ? length(f.path) : f.shape === 'area' ? f.size_ft[0] * f.size_ft[1] : 1);
}
function photometry(f, lumens) {
  if (f.shape === 'point') return {cd: lumens / (4 * Math.PI)};
  if (f.shape === 'spot') return {cd: lumens / (2 * Math.PI * (1 - Math.cos(f.cone_deg * Math.PI / 360)))};
  const area = f.shape === 'line' ? length(f.path) * f.width_in / 12 : f.size_ft[0] * f.size_ft[1];
  return {luminance: area > 0 ? lumens / (Math.PI * area * FT ** 2) : 0};
}
function resolved(f, entity, device, output, fraction, state) {
  const lumens = output * fraction * state.brightness;
  return {...f, fixture_id: f.id, entity_id: entity, device_id: device, legacy: false,
    output_lm: output, output_fraction: fraction, output_lm_share: lumens, ...photometry(f, lumens),
    rgb: state.rgb, brightness: state.brightness, on: state.on && lumens > 0};
}

// Geometry comes from the same bowl/pan helpers used to build the pit. These
// fixtures are absolute: they must never get lamp-height or host-face offsets.
export function firePitEmitters(pit, plan) {
  const options = firePitOptions(pit), gas = options.fuel === 'gas';
  const burner = gas ? gasTableLayout(pit) : firePitLayout(pit);
  const {centre, outer} = burner;
  const mean = outer.reduce((s, p) => s.map((v, i) => v + p[i] / outer.length), [0, 0]);
  const base = groundAt(plan, ...mean) + (pit.elevation || 0);
  const common = {id: `fixture:fire_pit:${pit.id}`, ref: 'absolute', fire_pit: true, range: 18};
  let f;
  if (!gas) {
    // fire_pits.js stacks four logs: bed .15, radius r, centres r*.55 apart.
    const r = Math.min(.14, burner.radius * .12), logsTop = base + .15 + r * (2 + 3 * .55);
    f = {...common, shape: 'point', at: [...centre, logsTop + 1]};
  }
  else {
    const height = base + options.height + (options.top === 'none' ? 0 : burner.slabThickness) - .075 + .07;
    const u = burner.u, v = [-u[1], u[0]];
    const widths = [u, v].map(axis => {
      const points = burner.glass.map(p => p[0] * axis[0] + p[1] * axis[1]);
      return Math.max(...points) - Math.min(...points);
    });
    if (burner.lineLength > 0 && widths[0] / widths[1] >= 4) {
      f = {...common, shape: 'line', path: [-1, 1].map(sign =>
        [centre[0] + sign * u[0] * burner.lineLength / 2, centre[1] + sign * u[1] * burner.lineLength / 2, height]),
      facing: 'up', width_in: widths[1] * 12};
    } else f = {...common, shape: 'area', at: [...centre, height], size_ft: widths, facing: 'up',
      rotation_deg: Math.atan2(u[1], u[0]) * 180 / Math.PI};
  }
  return [resolved(resolveFixture(f, plan), pit.entity, `object:fire_pit:${pit.id}`, DEFAULT_OUTPUT_LM, 1,
    emission(null, domainOf(pit.entity)))];
}

function legacyEmitter(marker, plan, state) {
  const building = plan.buildings?.find(b => b.id === marker.building);
  const room = marker.yard ? plan.site?.yard_rooms?.find(r => r.id === marker.room) : building?.rooms?.find(r => r.id === marker.room);
  const level = building?.levels?.find(l => l.id === marker.level);
  const floor = (building?.base || 0) + roomFloor(level, room);
  const standing = !!level && marker.at[2] <= floor + .1;
  const z = standing ? floor + LAMP_HEIGHT : marker.at[2];
  const range = lightRange({...marker, at: [marker.at[0], marker.at[1], z]}, building, level, room, spanOf(room));
  // Preserve the arithmetic order too: subtracting .2 ft after converting to
  // metres is the old live placement, snapshotted from main in the tests.
  const position = [marker.at[0] * FT,
    (z + (marker.yard ? groundAt(plan, marker.at[0], marker.at[1]) : buildingGround(plan, building))) * FT, -marker.at[1] * FT];
  if (level && !standing && marker.at[2] >= (building?.base || 0) + level.elevation + level.ceiling - .1) position[1] -= .2 * FT;
  // A legacy lamp is a default fixture: same lumens, same point photometry.
  const lumens = DEFAULT_OUTPUT_LM * state.brightness;
  return {...marker, marker, fixture_id: `legacy:${marker.device_id}`, shape: 'point', legacy: true, position, range,
    at: [position[0] / FT, -position[2] / FT, position[1] / FT], output_lm: DEFAULT_OUTPUT_LM,
    output_fraction: 1, output_lm_share: lumens, ...photometry({shape: 'point'}, lumens),
    rgb: state.rgb, brightness: state.brightness, on: state.on};
}

// firePits: false leaves derived fire-pit emitters out (live keeps pits on its
// object-lamp path until the bake slice moves them); their entity's markers
// then resolve through the legacy rules exactly as before fixtures existed.
export function resolveEmitters(layout, states = {}, plan = {}, {firePits = true} = {}) {
  // Accept either live.peek()'s map or the HA card-state response envelope.
  const stale = states?.stale || states?.reachable === false;
  const readings = states?.states || states || {};
  const stateOf = entity => emission(stale ? null : readings[entity], domainOf(entity));
  const fixtures = layout.light_fixtures || {}, devices = layout.devices || layout.markers || [];
  const groups = new Map(Object.entries(fixtures).filter(([, rows]) => rows.length).map(([entity, rows]) =>
    [entity, rows.map(f => resolveFixture(f, plan))]));
  // Pit ids follow twin_yard.js, which names an unnamed pit by its index.
  const pits = firePits ? pieces(plan.site?.fire_pit) : [];
  for (const [index, pit] of pits.entries()) if (pit.entity) {
    const rows = groups.get(pit.entity) || [];
    rows.push(...firePitEmitters({...pit, id: pit.id || index}, plan)); groups.set(pit.entity, rows);
  }
  const emitters = [];
  for (const [entity, rows] of groups) {
    const owner = (layout.markers || []).find(d => d.entity_id === entity || d.entities?.includes(entity))
      || devices.find(d => d.entity_id === entity || d.entities?.includes(entity));
    const weights = rows.map(weight), total = weights.reduce((a, b) => a + b, 0);
    const output = layout.light_fixtures_meta?.[entity]?.output_lm ?? DEFAULT_OUTPUT_LM;
    rows.forEach((f, i) => {
      const e = resolved(f, entity, f.fire_pit ? f.device_id : owner?.device_id ?? entity, output, total ? weights[i] / total : 0, stateOf(entity));
      for (const field of ['building', 'level', 'room', 'yard']) e[field] ??= owner?.[field];
      e.position = world(e.at || e.path.reduce((s, p) => s.map((v, k) => v + p[k] / e.path.length), [0, 0, 0]));
      e.range ??= 18;
      emitters.push(e);
    });
  }
  for (const marker of layout.markers || []) if (marker.kind === 'light' && !groups.has(marker.entity_id))
    emitters.push(legacyEmitter(marker, plan, stateOf(marker.entity_id)));
  return emitters;
}

// A transport signature is independent of HA state. Include full authored
// output and its normalized share so dimming or switching never stales a bake.
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().filter(k => value[k] !== undefined).map(k => [k, canonical(value[k])])) : value;
export function emitterSignature(emitters) {
  const fields = ['fixture_id', 'entity_id', 'device_id', 'shape', 'at', 'path', 'aim', 'size_ft', 'rotation_deg',
    'facing', 'normal', 'cone_deg', 'softness', 'width_in', 'output_lm', 'output_fraction', 'share',
    'building', 'level', 'room', 'legacy', 'orphaned', 'detached'];
  return JSON.stringify(emitters.map(e => canonical(Object.fromEntries(fields.map(k => [k, e[k]]))))
    .sort((a, b) => { const x = JSON.stringify(a), y = JSON.stringify(b); return x < y ? -1 : x > y ? 1 : 0; }));
}
