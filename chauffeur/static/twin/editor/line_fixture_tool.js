import * as THREE from 'three';
import { groundAt, buildingGround } from '../twin_ground.js';
import { pathOutline } from '../path_shapes.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { fixturePoint, fixtureRotation, facingNormal } from '../live/fixture_glow.js';
import { createSiteDrawing } from './site_drawing.js';

const pieces = value => Array.isArray(value) ? value : value ? [value] : [];
const lerp = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
export const facingOptions = (kind, current) => kind === 'step' ? [...(current && current !== 'out' ? [[current, `${current[0].toUpperCase() + current.slice(1)} (stored)`]] : []), ['out', 'Downhill']]
  : [['down', 'Down'], ['out', kind === 'fence' ? 'Right of drawn direction' : kind === 'wall' ? 'Out (outside face)' : 'Out'], ['up', 'Up'], ['in', kind === 'wall' ? 'In (inside face)' : 'In']];

export function screenRay(ray, view, event) {
  const rect = view.renderer3.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, 1 - (event.clientY - rect.top) / rect.height * 2), view.camera);
  return rect;
}
export const FIXTURE_COLOR = '#9abfe5';
export function fixtureStroke(points, color = FIXTURE_COLOR) {
  const parts = [], ps = points.map(fixturePoint), radius = .06;
  for (let i = 1; i < ps.length; i++) {
    if (!ps[i].equals(ps[i-1])) parts.push(new THREE.TubeGeometry(new THREE.LineCurve3(ps[i-1], ps[i]), 1, radius, 8, false));
    if (i < ps.length - 1) parts.push(new THREE.SphereGeometry(radius, 8, 4).translate(...ps[i].toArray()));
  }
  const geometry = parts.length ? mergeGeometries(parts) : new THREE.BufferGeometry();
  for (const part of parts) part.dispose();
  return new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({color, toneMapped:false}));
}

// Same un-offset host edges as twin_fixtures._host_edges; the resolver owns mounting offsets.
export function snapEdges(plan) {
  const edges = [], site = plan.site || {};
  const add = (kind, id, a, b, context = {}) => { if (a && b && Math.hypot(...a.map((v, i) => v - b[i])) > 1e-8) edges.push({ host: { kind, id }, a, b, ...context }); };
  for (const kind of ['retaining_wall', 'hardscape', 'fence']) {
    const list = pieces(site[{retaining_wall:'terraces', hardscape:'hardscape', fence:'fence'}[kind]]);
    for (const p of list) {
      if (list.filter(q => q.id === p.id).length !== 1) continue;
      const path = kind === 'hardscape' && p.kind === 'path';
      const ps = path ? pathOutline(p) : p.polygon || p.polyline || p.points || [], closed = path || !!p.polygon;
      for (let i = 0; i < ps.length - (closed ? 0 : 1); i++) {
        const a = ps[i], b = ps[(i + 1) % ps.length], edge = p.edges?.[i];
        if (kind === 'retaining_wall' && (edge?.edge !== 'sharp' || !edge.wall)) continue;
        const z = q => kind === 'retaining_wall' ? p.height + (edge.wall.above_in || 0) / 12
          : (p.elevation ?? groundAt(plan, ...q)) + (kind === 'fence' ? p.height ?? 6 : 0);
        add(kind, p.id, [...a, z(a)], [...b, z(b)]);
      }
    }
  }
  const counts = Object.fromEntries(['wall','step'].map(kind => {
    const ids = new Map(); for (const b of plan.buildings || []) for (const p of b[kind === 'wall' ? 'walls' : 'stairs'] || []) if (!['ghost','proposal'].includes(p.state)) ids.set(p.id, (ids.get(p.id) || 0) + 1);
    return [kind, ids];
  }));
  for (const b of plan.buildings || []) {
    const lift = buildingGround(plan, b);
    const angle = (b.rotation || 0) * Math.PI / 180, pos = b.position || [0, 0];
    const world = p => [pos[0] + p[0] * Math.cos(angle) - p[1] * Math.sin(angle), pos[1] + p[0] * Math.sin(angle) + p[1] * Math.cos(angle)];
    for (const kind of ['wall', 'step']) for (const p of b[kind === 'wall' ? 'walls' : 'stairs'] || []) {
      if (['ghost', 'proposal'].includes(p.state)) continue;
      if (counts[kind].get(p.id) !== 1) continue;
      const level = b.levels?.find(l => l.id === p.level); if (!level) continue;
      const base = (b.base || 0) + level.elevation, context = { building: b.id, level: level.id, lift };
      if (kind === 'wall') {
        const ends = p.joints?.map(id => b.joints?.find(j => j.id === id)?.at) || [];
        if (ends.length === 2 && ends.every(Boolean)) add(kind, p.id, [...world(ends[0]), base + (p.height ?? level.ceiling ?? 9)], [...world(ends[1]), base + (p.height ?? level.ceiling ?? 9)], context);
      } else if (p.from && p.to && p.width > 0 && p.risers >= 1 && p.risers <= 1000 && Number.isFinite(p.rise_to)) {
        const dx = p.to[0] - p.from[0], dy = p.to[1] - p.from[1], length = Math.hypot(dx, dy); if (!length) continue;
        for (let i = 0; i < Math.floor(p.risers); i++) {
          const c = lerp(p.from, p.to, i / p.risers), z = base + (p.rise_to - level.elevation) * (i + 1) / p.risers;
          const end = sign => [...world([c[0] - sign * dy / length * p.width / 2, c[1] + sign * dx / length * p.width / 2]), z];
          add(kind, p.id, end(-1), end(1), context);
        }
      }
    }
  }
  return edges;
}

export function areaOutline(f) {
  const rotation = fixtureRotation({ ...f, normal: facingNormal(f.facing) });
  return [[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]].map(([x, y]) => {
    const v = new THREE.Vector3(x * f.size_ft[0] / 2, y * f.size_ft[1] / 2, 0).applyQuaternion(rotation);
    return [f.at[0] + v.x, f.at[1] - v.z, f.at[2] + v.y];
  });
}

export function createLineFixtureTool({ view, getPlan, surface, commit, canEdit, report, host, onDone, encode = f => f }) {
  const preview = new THREE.Group(), ray = new THREE.Raycaster(), canvas = view.renderer3.domElement;
  let active = null, gesture = null, rectangle = null, selected = null, anchor = null, facing = 'down', facingChosen = false, busy = false, controls = null, facingSelect = null, finishButton = null, edgeKey = null, cachedEdges = [];
  const drawing = () => createSiteDrawing({ getPlan, commit: o => save(encode({ shape: 'line', ref: 'absolute', path: o.polyline, snap: null, facing, width_in: active.fixture?.width_in ?? .5 }, anchor)) });
  let draft = drawing();
  const node = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const button = (text, fn) => { const n = node('button', text); n.type = 'button'; n.addEventListener('click', () => { if (canEdit() && !busy) Promise.resolve().then(fn).catch(report); }); controls.append(n); return n; };
  function clear() { for (const child of [...preview.children]) { child.geometry.dispose(); child.material.dispose(); child.removeFromParent(); } }
  function line(points, color = FIXTURE_COLOR) {
    if (points.length < 2) return;
    preview.add(fixtureStroke(points, color));
  }
  function graphics(hover) {
    clear();
    if (!active) return;
    if (active.kind === 'draw') line(draft.preview());
    else if (active.kind === 'area' && rectangle) line(areaOutline(rectangle));
    else if (active.kind === 'snap') {
      const edge = gesture?.edge || hover || selected;
      if (edge) {
        const lift = p => [p[0], p[1], p[2] + (edge.lift || 0)];
        line([lift(edge.a), lift(edge.b)], '#ffffff');
        if (gesture?.edge) line([lift(lerp(edge.a, edge.b, gesture.t0)), lift(lerp(edge.a, edge.b, gesture.t1))]);
      }
    }
  }
  function selectFacing(kind, value) {
    facingSelect.replaceChildren();
    const options = kind === 'area' ? [['down','Down'],['out','Out'],['up','Up'],['surface','Clicked face']] : facingOptions(kind);
    for (const [v, text] of options) { const option = node('option', text); option.value = v; facingSelect.append(option); }
    facing = options.some(([v]) => v === value) ? value : options[0][0]; facingSelect.value = facing;
  }
  function choose(kind) {
    draft.cancel(); gesture = rectangle = selected = anchor = null; active.kind = kind; facingChosen = !!active.fixture; edgeKey = null; cachedEdges = [];
    finishButton.hidden = kind === 'snap'; if (kind === 'snap') edges();
    if (kind === 'draw') draft.start('fence');
    selectFacing(kind === 'area' ? 'area' : null, typeof active.fixture?.facing === 'string' ? active.fixture.facing : 'down'); graphics();
  }
  function start(value) {
    stop(); draft = drawing(); active = value; controls = node('div'); controls.className = 'editor-material-actions'; host.append(controls);
    if (value.kind !== 'area') { button('Draw line', () => choose('draw')); button('Snap to edge', () => choose('snap')); }
    finishButton = button('Finish', finish);
    const label = node('label', 'Facing'); facingSelect = node('select'); facingSelect.setAttribute('aria-label', 'Facing'); label.append(facingSelect); controls.append(label);
    facingSelect.addEventListener('change', () => { if (!canEdit() || busy) return; facing = facingSelect.value; facingChosen = true; if (rectangle) { rectangle.facing = facing === 'surface' ? rectangle.surfaceNormal : facing; graphics(); } });
    choose(value.kind);
  }
  function stop() { draft.cancel(); clear(); controls?.remove(); controls = facingSelect = finishButton = null; edgeKey = null; cachedEdges = []; active = gesture = rectangle = selected = anchor = null; }
  async function save(fixture) {
    if (!active || !canEdit() || busy) return false;
    const current = active; busy = true;
    try { return await commit(current, fixture); } finally { busy = false; }
  }
  function edges() {
    const plan = getPlan(), key = JSON.stringify([plan.buildings, plan.site?.terraces, plan.site?.hardscape, plan.site?.fence]);
    if (key !== edgeKey) { cachedEdges = snapEdges(plan); edgeKey = key; }
    return cachedEdges;
  }
  function pick(event) {
    const rect = screenRay(ray, view, event);
    const near = [];
    for (const edge of edges()) {
      if (edge.building && view.groups?.levels[`${edge.building}:${edge.level}`]?.visible === false) continue;
      const a = fixturePoint(edge.a), b = fixturePoint(edge.b); a.y += (edge.lift || 0) * .3048; b.y += (edge.lift || 0) * .3048;
      const onRay = new THREE.Vector3(), onEdge = new THREE.Vector3(); ray.ray.distanceSqToSegment(a, b, onRay, onEdge);
      const screen = onEdge.clone().project(view.camera); if (screen.z < -1 || screen.z > 1) continue;
      const pixels = Math.hypot((screen.x + 1) * rect.width / 2 + rect.left - event.clientX, (1 - screen.y) * rect.height / 2 + rect.top - event.clientY);
      const depth = ray.ray.origin.distanceTo(onRay);
      if (pixels <= 12) near.push({ edge, onEdge, screen, pixels, depth });
    }
    // Nearest on screen first, so the occlusion pick runs only until one visible edge is found.
    near.sort((p, q) => Math.abs(p.pixels - q.pixels) <= .25 ? p.depth - q.depth : p.pixels - q.pixels);
    for (const { edge, onEdge, screen } of near) {
      const x = (screen.x + 1) * rect.width / 2 + rect.left, y = (1 - screen.y) * rect.height / 2 + rect.top;
      const hit = view.pick(x, y), ownHost = hit?.kind === (edge.host.kind === 'step' ? 'stair' : edge.host.kind) && (hit.id || hit.pieceId) === edge.host.id && (!edge.building || (hit.building || hit.buildingId) === edge.building);
      if (!ownHost && hit?.point && ray.ray.origin.distanceTo(new THREE.Vector3(...hit.point)) < ray.ray.origin.distanceTo(onEdge) - .15) continue;
      return edge;
    }
    return null;
  }
  function parameter(event, edge) {
    screenRay(ray, view, event);
    const a = fixturePoint(edge.a), b = fixturePoint(edge.b); a.y += (edge.lift || 0) * .3048; b.y += (edge.lift || 0) * .3048;
    const p = new THREE.Vector3(); ray.ray.distanceSqToSegment(a, b, new THREE.Vector3(), p);
    return Math.max(0, Math.min(1, p.sub(a).dot(b.clone().sub(a)) / a.distanceToSquared(b)));
  }
  function down(event) {
    if (!active || busy) return false;
    if (active.kind === 'snap') {
      const edge = pick(event); if (!edge) return true;
      selected = edge; selectFacing(edge.host.kind, facingChosen ? facing : active.fixture?.facing ?? (edge.host.kind === 'hardscape' || edge.host.kind === 'step' ? 'out' : facing));
      gesture = { edge, t0: parameter(event, edge), t1: parameter(event, edge), x: event.clientX, y: event.clientY };
    } else {
      const hit = surface(event, true); if (!hit) return true;
      gesture = { hit, x: event.clientX, y: event.clientY };
      if (active.kind === 'area') {
        rectangle = null; anchor = hit;
        if (!facingChosen) { facing = Math.abs(hit.normal?.[2] ?? 1) < .9 ? 'surface' : hit.ceiling ? 'down' : 'up'; facingSelect.value = facing; }
      }
    }
    graphics(); return true;
  }
  function move(event) {
    if (!active || busy) return false;
    if (active.kind === 'snap') {
      if (gesture?.edge) gesture.t1 = parameter(event, gesture.edge);
      graphics(pick(event)); return true;
    }
    const hit = surface(event, true); if (!hit) return true;
    if (active.kind === 'draw') { draft.move(hit.at, true); graphics(); return true; }
    if (!gesture) return true;
    const normal = gesture.hit.normal || [0,0,1], face = facing === 'surface' ? normal : facing;
    const q = fixtureRotation({ facing: face, normal: facingNormal(face) });
    const start = new THREE.Vector3(gesture.hit.at[0], gesture.hit.at[2], -gesture.hit.at[1]);
    const delta = new THREE.Vector3(hit.at[0], hit.at[2], -hit.at[1]).sub(start).applyQuaternion(q.clone().invert());
    const centre = new THREE.Vector3(delta.x / 2, delta.y / 2, 0).applyQuaternion(q).add(start);
    rectangle = { shape: 'area', ref: 'absolute', at: [centre.x, -centre.z, centre.y], size_ft: [Math.abs(delta.x), Math.abs(delta.y)], facing: face, rotation_deg: 0, surfaceNormal: normal };
    graphics(); return true;
  }
  async function up(event, cancelled) {
    if (!active || busy) return;
    if (!canEdit()) { cancelGesture(); return; }
    if (cancelled) { if (active.kind === 'draw') { gesture = null; graphics(); } else cancelGesture(); return; }
    const g = gesture; if (!g) return;
    move(event); gesture = null;
    if (active.kind === 'draw') {
      if (Math.hypot(event.clientX - g.x, event.clientY - g.y) < 3) {
        if (draft.current().points.length >= 64) throw new Error('A line can have at most 64 points.');
        if (!draft.current().points.length) anchor = g.hit;
        draft.add(g.hit.at, true);
        if (!facingChosen) {
          const ps = draft.current().points, normal = anchor.normal || [0,0,1];
          if (Math.abs(normal[2]) >= .9) facing = anchor.ceiling ? 'down' : 'up';
          else if (ps.length >= 2) { const a = ps[0], b = ps.at(-1); facing = (b[1]-a[1])*normal[0] - (b[0]-a[0])*normal[1] >= 0 ? 'out' : 'in'; }
          facingSelect.value = facing;
        }
      }
    } else if (active.kind === 'snap') {
      const current = active;
      const dragged = Math.hypot(event.clientX - g.x, event.clientY - g.y) >= 3;
      const t0 = dragged ? g.t0 : 0, t1 = dragged ? g.t1 : 1;
      if (Math.abs(t1 - t0) <= 1e-8) { graphics(); return; }
      const edge = g.edge, snap = { host: edge.host, edge: {from: edge.a.slice(0,2), to: edge.b.slice(0,2)}, t0, t1 };
      if (await save({ shape:'line', ref:'absolute', path:[lerp(edge.a,edge.b,t0),lerp(edge.a,edge.b,t1)], snap, facing, width_in:active.fixture?.width_in ?? .5 }) !== false && active === current) onDone();
    }
    graphics();
  }
  async function finish() {
    if (!active || busy || !canEdit()) return;
    const current = active, d = draft;
    if (active.kind === 'draw') { if (await d.finish() && active === current) onDone(); }
    else if (active.kind === 'area') {
      if (!rectangle || Math.min(...rectangle.size_ft) <= .001) throw new Error('Drag a rectangle with a positive width and height.');
      const { surfaceNormal, ...fixture } = rectangle; if (await save(encode(fixture, anchor)) !== false && active === current) onDone();
    }
  }
  async function done() {
    if (!active || busy || !canEdit()) return;
    if (active.kind === 'draw' && draft.current()?.points.length >= 2 || active.kind === 'area' && rectangle && Math.min(...rectangle.size_ft) > .001) await finish();
    else onDone();
  }
  function cancelGesture() {
    const drawing = active?.kind === 'draw', had = !!gesture || !!rectangle || !!draft.current()?.points.length;
    gesture = rectangle = selected = anchor = null; draft.cancel(); if (drawing) draft.start('fence'); graphics(); return had;
  }
  function key(event) {
    if (!active) return false;
    if (event.key === 'Escape') return cancelGesture();
    if (event.key === 'Backspace' && active.kind === 'draw') { draft.back(); graphics(); return true; }
    if (event.key === 'Enter') { finish().catch(report); return true; }
    return false;
  }
  return { start, stop, down, move, up, key, preview, cancelGesture, done };
}
