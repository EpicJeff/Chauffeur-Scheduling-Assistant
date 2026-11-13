import { roomFloor, roomAt } from './twin_floors.js';
// Viewing LOD uses lot feet (x, y, height). No work here depends on frame rate.
import * as THREE from 'three';

const smooth = t => { t = Math.max(0, Math.min(1, t)); return t * t * (3 - 2 * t); };
export const cutHeight = level => Math.max(1, (level.ceiling || 8) - 4);
export const fadeAlpha = (distance, near, far) => smooth((distance - near) / (far - near));
export function bandActive(distance, threshold, active, margin) {
  return active ? distance < threshold + margin : distance < threshold - margin;
}
export function nearestFloor(levels, height) {
  return [...levels].sort((a, b) => Math.abs(a.elevation - height) - Math.abs(b.elevation - height))[0];
}
function inside(poly, [x, y]) {
  let yes = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) yes = !yes;
  }
  return yes;
}
const world = (b, [x, y]) => {
  const a = (b.rotation || 0) * Math.PI / 180;
  return [Math.cos(a) * x - Math.sin(a) * y + (b.position?.[0] || 0),
    Math.sin(a) * x + Math.cos(a) * y + (b.position?.[1] || 0)];
};
export function floorOutline(b, l) {
  if (l.outline?.length) return l.outline.map(p => world(b, p));
  const rooms = (b.rooms || []).filter(r => r.level === l.id).flatMap(r => r.polygon || []);
  const points = rooms.length ? rooms : b.walls.filter(w => w.level === l.id).flatMap(w => [w.from, w.to]);
  if (!points.length) return [];
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  return [[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.min(...ys)],
    [Math.max(...xs), Math.max(...ys)], [Math.min(...xs), Math.max(...ys)]].map(p => world(b, p));
}
// Segment/AABB slab test: samples end at the floor, so objects behind it cannot peel.
export function blocks(camera, point, box) {
  let near = 0, far = .995;
  for (let i = 0; i < 3; i++) {
    const delta = point[i] - camera[i];
    if (Math.abs(delta) < 1e-8) { if (camera[i] < box.min[i] || camera[i] > box.max[i]) return false; }
    else {
      const a = (box.min[i] - camera[i]) / delta, b = (box.max[i] - camera[i]) / delta;
      near = Math.max(near, Math.min(a, b)); far = Math.min(far, Math.max(a, b));
      if (near > far) return false;
    }
  }
  return far > 0 && near < .995;
}
export function peelSet(camera, samples, obstacles) {
  return new Set(obstacles.filter(o => samples.some(p => blocks(camera, p, o.box))).map(o => o.id));
}

export function createViewing(view, model, ground, changed, {explicit = false} = {}) {
  const channels = [], buildings = [], obstacles = [];
  const bindings = new Map(), replacements = [];
  let pinned = null, active = false, signature = '', selected = 'ext', transition = 0, previous = 0;
  let pinnedDistance = 0;
  const distanceToTarget = () => view.camera.position.distanceTo(view.controls.target) / .3048;
  const domains = ['roof', 'gableFull', 'gableCut'].map(id => model.groups[id]);
  const domainVisibility = [...domains, ...model.groups.gableCut.children].map(group => [group, group.visible]);
  // Viewing uses closed, flat wall variants in each level, rather than the
  // editor's old sloped gable cuts. Keep the public domain flags meaningful.
  model.groups.gableCut.children.forEach(group => { group.visible = false; });
  const vector = p => [p.x / .3048, -p.z / .3048, p.y / .3048];
  function channel(group, skipWalls = false) {
    const plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);
    const materials = [], originals = new Map(), shadows = [];
    function visit(object) {
      if (skipWalls && object.userData.viewingWalls) return;
      if (object.material && !object.layers.isEnabled(31)) {
        if (object.isMesh) shadows.push({object, cast: object.castShadow});
        const clone = source => {
          if (!originals.has(source)) {
            const m = source.clone();
            // Prepared once: no transparent or clipping-count changes while zooming.
            m.userData.viewingOpaque = !source.transparent;
            m.transparent = true; m.clippingPlanes = [plane];
            if (source.alphaTest > 0) m.forceSinglePass = true;
            const binding = {m, opacity: source.opacity, depth: source.depthWrite};
            originals.set(source, m); materials.push(binding); bindings.set(m, {materials, binding, plane});
          }
          return originals.get(source);
        };
        const source = object.material;
        object.material = Array.isArray(source) ? source.map(clone) : clone(source);
        replacements.push({object, source, next: object.material});
      }
      object.children.forEach(visit);
    }
    visit(group);
    const result = {group, plane, materials, shadows, alpha: 1, from: 1, to: 1}; channels.push(result); return result;
  }
  model.root.updateMatrixWorld(true);
  for (const b of view.plan.buildings) {
    const levels = [...b.levels].sort((a, c) => a.elevation - c.elevation);
    const outlines = levels.map(l => floorOutline(b, l));
    const points = outlines.flat(); if (!points.length) continue;
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    const span = Math.max(12, Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
    const base = ground(b) + (b.base || 0);
    const roofs = ['roof', 'gableFull'].flatMap(domain => model.groups[domain].children.filter(g => g.userData.buildingId === b.id)).map(g => channel(g));
    const floors = levels.map((l, i) => {
      const key = `${b.id}:${l.id}`, group = model.groups.levels[key];
      const body = channel(group, true), full = [], cut = [];
      group.traverse(o => { if (o.userData.viewingWalls) (o.userData.viewingWalls === 'cut' ? cut : full).push(channel(o)); });
      cut.forEach(c => { c.alpha = c.from = c.to = 0; c.group.visible = false; });
      return {l, key, outline: outlines[i], body, full, cut};
    });
    buildings.push({b, base, span, floors, roofs});
    const box = new THREE.Box3();
    [...roofs, ...floors.map(f => f.body)].forEach(c => box.union(new THREE.Box3().setFromObject(c.group)));
    obstacles.push({id: b.id, box: {min: [box.min.x / .3048, -box.max.z / .3048, box.min.y / .3048],
      max: [box.max.x / .3048, -box.min.z / .3048, box.max.y / .3048]}});
  }
  model.groups.site.traverse(o => {
    if (!o.userData.viewingTree) return;
    const box = new THREE.Box3().setFromObject(o);
    const id = `tree:${obstacles.length}`, fade = channel(o);
    obstacles.push({id, fade, box: {min: [box.min.x / .3048, -box.max.z / .3048, box.min.y / .3048],
      max: [box.max.x / .3048, -box.min.z / .3048, box.max.y / .3048]}});
  });
  function set(c, alpha, height = 1e6) { c.to = alpha; c.plane.constant = height * .3048; }
  function update(now) {
    const camera = vector(view.camera.position), target = vector(view.controls.target);
    const nextSignature = [...camera, ...target, pinned].join(',');
    if (signature !== nextSignature) {
      signature = nextSignature;
      const focused = buildings.find(b => b.floors.some(f => inside(f.outline, target)));
      let building = pinned ? buildings.find(b => b.floors.some(f => f.key === pinned)) : focused;
      const distance = Math.hypot(...camera.map((v, i) => v - target[i]));
      // An explicit floor selection is valid even at exterior distance. Only
      // a clear outward zoom after that selection can release it.
      if (!explicit && pinned && distance > Math.max(pinnedDistance * 1.25, building.span * 1.85)) {
        pinned = null; building = focused;
      }
      active = !!building && bandActive(distance, building.span * 1.6, active, building.span * .04);
      let floor = null;
      if (explicit) {
        floor = pinned ? building?.floors.find(f => f.key === pinned) : null;
        if (!floor) building = null;
      } else if (building && (pinned || active)) {
        const nearest = nearestFloor(building.floors.map(f => f.l), target[2] - building.base);
        const desired = pinned ? building.floors.findIndex(f => f.key === pinned) : building.floors.findIndex(f => f.l === nearest);
        // Each upper storey has its own distance band. Never descend below the target's level.
        let index = Math.max(desired, building.floors.findIndex(f => f.key === selected));
        if (selected === 'ext' || !building.floors.some(f => f.key === selected)) index = building.floors.length - 1;
        const threshold = i => building.span * Math.max(.25, 1.15 - (building.floors.length - 1 - i) * .3);
        while (index > desired && distance < threshold(index) - building.span * .025) index--;
        while (index < building.floors.length - 1 && distance > threshold(index + 1) + building.span * .025) index++;
        floor = pinned ? building.floors[desired] : building.floors[index];
      }
      const key = floor?.key || 'ext';
      if (key !== selected) { selected = key; changed(key); }
      const outline = floor?.outline || [], center = outline.length ? outline.reduce((a, p) => [a[0] + p[0] / outline.length, a[1] + p[1] / outline.length], [0, 0]) : [];
      // Centre and four inset outline vertices, a bounded five rays per obstacle.
      const samples = floor ? [center, ...outline.filter((_, i) => i % Math.max(1, Math.ceil(outline.length / 4)) === 0).slice(0, 4)
        .map(p => p.map((v, i) => v * .8 + center[i] * .2))].map(p => { const local = p.map((v, i) => v - (building.b.position?.[i] || 0)), a = -(building.b.rotation || 0) * Math.PI / 180;
          const room = roomAt(building.b, floor.l.id, [local[0] * Math.cos(a) - local[1] * Math.sin(a), local[0] * Math.sin(a) + local[1] * Math.cos(a)]);
          return [...p, building.base + roomFloor(floor.l, room) + 1]; }) : [];
      const peeled = floor ? peelSet(camera, samples, obstacles.filter(o => o.id !== building.b.id)) : new Set();
      channels.forEach(c => { c.from = c.alpha; set(c, 1); });
      for (const b of buildings) {
        const other = peeled.has(b.b.id) ? 0 : 1;
        b.roofs.forEach(c => set(c, b === building && floor ? pinned ? 0 : fadeAlpha(distance, b.span * 1.25, b.span * 1.6) : other));
        for (let i = 0; i < b.floors.length; i++) {
          const f = b.floors[i], upper = b === building && floor && f.l.elevation > floor.l.elevation;
          const band = b.span * Math.max(.25, 1.15 - (b.floors.length - 1 - i) * .3);
          const alpha = upper ? pinned ? 0 : fadeAlpha(distance, band - b.span * .2, band) : other;
          const cut = b === building && (f === floor || upper);
          set(f.body, alpha, cut ? b.base + f.l.elevation + cutHeight(f.l) : 1e6);
          f.full.forEach(c => set(c, cut ? 0 : alpha));
          // The variant is already closed at the cut. Leave its cap strictly
          // inside the plane: a coplanar GPU clip can slice triangles into teeth.
          f.cut.forEach(c => set(c, cut ? alpha : 0, b.base + f.l.elevation + cutHeight(f.l) + .002));
        }
      }
      obstacles.filter(o => o.fade).forEach(o => set(o.fade, peeled.has(o.id) ? 0 : 1));
      transition = now;
    }
    const step = 1 - Math.exp(-Math.max(0, now - previous) / 60); previous = now;
    for (const c of channels) {
      const alpha = now - transition >= 250 ? c.to : c.alpha + (c.to - c.alpha) * step;
      if (alpha === c.alpha && c.group.visible === (alpha > .001)) continue;
      c.alpha = alpha; c.group.visible = alpha > .001;
      if (c.group.userData.levelId) for (const light of view.roomLights)
        if (light.userData.level === c.group.name) light.intensity = (light.userData.viewingIntensity || 0) * alpha;
      for (const {m, opacity, depth} of c.materials) { m.opacity = opacity * alpha; m.depthWrite = depth && alpha > .999; }
      for (const {object, cast} of c.shadows) {
        const next = cast && alpha > .999;
        if (object.castShadow !== next) { object.castShadow = next; view.renderer3.shadowMap.needsUpdate = true; }
      }
    }
    for (const domain of [model.groups.roof, model.groups.gableFull])
      domain.visible = domain.children.some(group => group.visible);
    model.groups.gableCut.visible = buildings.some(b => b.floors.slice(1).some(f => f.cut.some(c => c.group.visible)));
  }
  return {
    update,
    levelAlpha(key) { return buildings.flatMap(b => b.floors).find(f => f.key === key)?.body.alpha ?? 1; },
    roofAlpha(id) { const b = buildings.find(b => b.b.id === id); return b?.roofs.length ? Math.max(...b.roofs.map(c => c.alpha)) : 1; },
    select(key) {
      pinned = key === 'ext' ? null : key; pinnedDistance = distanceToTarget();
      active = false; signature = ''; selected = key; changed(key);
    },
    rebasePin() { if (pinned) pinnedDistance = distanceToTarget(); },
    // A piece faded more than halfway out is see-through: taps pass through it to what is behind
    // (its pick proxy is not inside the faded group, so plain visibility does not catch it).
    // World height (m) where the object's floor is cut away; Infinity when it is not cut.
    // Pick proxies keep the full wall height, so a tap above the cut must pass through.
    cutAt(object) {
      for (let o = object; o; o = o.parent) if (o.userData.levelKey) {
        const floor = buildings.flatMap(b => b.floors).find(f => f.key === o.userData.levelKey);
        return floor ? floor.body.plane.constant : Infinity;
      }
      return Infinity;
    },
    faded(object) {
      for (let o = object; o; o = o.parent) if (o.userData.levelKey) {
        const floor = buildings.flatMap(b => b.floors).find(f => f.key === o.userData.levelKey);
        return !!floor && floor.body.alpha < .5;
      }
      if (object.userData.kind !== 'roof') return false;
      const b = buildings.find(b => b.b.id === object.userData.buildingId);
      return !!b?.roofs.length && Math.max(...b.roofs.map(c => c.alpha)) < .5;
    },
    snapshot() { return {selected, pinned, channels: channels.map(c => ({name: c.group.name, alpha: c.alpha, target: c.to}))}; },
    adopt(source, material) {
      const record = bindings.get(source); if (!record) return;
      const binding = {...record.binding, m: material};
      material.clippingPlanes = [record.plane]; record.materials.push(binding);
      bindings.set(material, {...record, binding});
      material.addEventListener('dispose', () => {
        const index = record.materials.indexOf(binding); if (index >= 0) record.materials.splice(index, 1);
        bindings.delete(material);
      });
    },
    dispose({ deferMaterials = false } = {}) {
      domainVisibility.forEach(([group, visible]) => { group.visible = visible; });
      for (const {object, source, next} of replacements) if (object.material === next) object.material = source;
      for (const c of channels) for (const {object, cast} of c.shadows) object.castShadow = cast;
      const materials = [...bindings.keys()];
      const release = () => materials.forEach(material => material.dispose());
      if (!deferMaterials) release();
      bindings.clear();
      return release;
    },
    warm() {
      if (!view.renderer3.compileAsync) return;
      const visible = []; model.root.traverse(o => { visible.push([o, o.visible]); o.visible = true; });
      try { return view.renderer3.compileAsync(view.scene, view.camera).catch(() => {}); }
      finally { visible.forEach(([o, value]) => { o.visible = value; }); }
    },
  };
}
