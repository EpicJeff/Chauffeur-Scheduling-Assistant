import { roomFloor } from '../twin_floors.js';
import * as THREE from 'three';
import { FT, polygon, contains, stairHoles } from '../twin_generator.js';
export { lightRange, LAMP_HEIGHT } from '../twin_light_math.js';
import { buildingGround, groundAt } from '../twin_ground.js';
import { lightColor, createRealLights, paletteLineEntities } from './real_lights.js';
import { resolveEmitters, emission, fireEffectEmitters } from './emitters.js';
import { createFixtureGlow } from './fixture_glow.js';
import { registerClimate, resolveClimateZones, climateRoomKey, climateColors } from './climate.js';
import { registerEnergy } from './energy.js';
import { registerSecurity } from './security.js';
import { svgIcon } from './glance_icons.js';
import { garageEntity, garagePose } from '../garage_door.js';
import { modeShows, modeName, readModes, saveModes } from './mode_state.js';
export { modeShows } from './mode_state.js';

const registry = new Map();
export function registerMode(mode) { registry.set(mode.id, mode); return mode; }
export function modes() { return [...registry.values()]; }
export const modeForeground = (selection, row, state) => {
  let owned = false;
  for (const mode of registry.values()) if (mode.foreground?.(row, state)) {
    owned = true;
    if (modeShows(selection, mode.id)) return true;
  }
  return !owned;
};
const MODE_ICONS = {all: 'layers', lights: 'lightbulb', climate: 'thermometer', energy: 'zap', security: 'shield'};

// All is every visualization at once: lit rooms, active HVAC, energy ribbons, security
// emphasis and camera cones (user, 2026-11-12). It is registered first so its icon leads.
registerMode({id: 'all', label: 'All', icon: 'layers'});
registerMode({id: 'lights', label: 'Lights', icon: 'lightbulb',
  foreground: row => row.kind === 'light',
  enter: ({lighting}) => lighting(true), update() {}, leave: ({lighting}) => lighting(false)});
registerClimate(registerMode);
registerEnergy(registerMode);
registerSecurity(registerMode);

export function roomStates(rooms, states) {
  return rooms.filter(room => room.area_id).map(room => {
    const on = [...new Set(room.lights)].map(id => states[id]).filter(state => state?.state === 'on');
    return { building: room.building, room: room.room,
      glow: on.length ? on.reduce((sum, state) => sum + Math.max(0, Math.min(255, state.attributes?.brightness ?? 255)) / 255, 0) / on.length : 0,
      rgb: on.find(state => Array.isArray(state.attributes?.rgb_color))?.attributes.rgb_color || null };
  });
}

export function mountModes(view, live) {
  // Mode icons, centred at the top: the viewer's only controls besides the path chip (spec).
  const ids = modes().map(mode => mode.id).filter(id => id !== 'all');
  let enabled = readModes(ids);
  const timers = new Set();
  const strip = document.createElement('fieldset'); strip.id = 'twin-modes';
  const legend = document.createElement('legend'); legend.textContent = 'Show'; strip.append(legend);
  const buttons = new Map();
  for (const mode of modes()) {
    const button = document.createElement('button'); button.type = 'button';
    button.setAttribute('aria-label', mode.label); button.dataset.mode = mode.id;
    const description = mode.id === 'all' ? 'Toggle all modes on or off.'
      : 'Tap to toggle. Hold, right-click, Shift+click or Shift+Enter to show only this mode.';
    button.title = `${mode.label}: ${description}`;
    button.setAttribute('aria-description', description);
    const shape = mode.icon || MODE_ICONS[mode.id];
    if (shape && typeof document.createElementNS === 'function') {
      button.append(svgIcon(shape, 'currentColor', 'mode-' + mode.id));
      const tip = document.createElement('span'); tip.className = 'twin-mode-tip'; tip.textContent = button.title; tip.hidden = true;
      button.append(tip);
    } else button.textContent = mode.label;
    let hold = null, suppressClick = false;
    const cancel = () => { clearTimeout(hold); timers.delete(hold); hold = null; };
    if (mode.id !== 'all') {
      button.addEventListener('pointerdown', event => {
        cancel(); suppressClick = false;
        if (event.button !== 0 || event.isPrimary === false) return;
        hold = setTimeout(() => {
          timers.delete(hold); hold = null; suppressClick = true; live.setMode(mode.id);
        }, 500);
        timers.add(hold);
      });
      for (const name of ['pointerup', 'pointerleave', 'pointercancel', 'lostpointercapture', 'blur']) button.addEventListener(name, cancel);
      button.addEventListener('contextmenu', event => { event.preventDefault(); cancel(); suppressClick = true; live.setMode(mode.id); });
      button.addEventListener('keydown', event => {
        suppressClick = false;
        if (event.shiftKey && event.key === 'Enter') {
          event.preventDefault(); cancel(); live.setMode(mode.id);
        }
      });
    }
    button.addEventListener('click', event => {
      if (suppressClick) { suppressClick = false; event.preventDefault(); return; }
      if (event.shiftKey && mode.id !== 'all') live.setMode(mode.id);
      else live.toggleMode(mode.id);
    });
    strip.append(button); buttons.set(mode.id, button);
  }
  (document.getElementById('twin-mode-bar') || document.getElementById('twin-controls')).append(strip);
  const climateLabels = document.createElement('div'); climateLabels.className = 'twin-mode-labels twin-climate-labels';
  const modeLegend = document.createElement('output'); modeLegend.id = 'twin-mode-legend'; modeLegend.hidden = true;
  const legendText = document.createElement('span'), legendContent = document.createElement('div'); modeLegend.append(legendText, legendContent);
  document.getElementById('twin-controls').append(modeLegend);
  document.body.append(climateLabels);
  let lastKey = '', revision = 0, effectLampKey = '';
  const floors = [], lamps = [];
  // Older embeds do not expose a render tier. Keep their room overview until
  // they mount the current view, whose tier supplies the real-light budget.
  const realLighting = !!view.tier;
  let legacyRooms = [];
  const layout = live.layout(), emitters = resolveEmitters(layout, {}, view.plan);
  const fixtures = emitters.some(e => !e.legacy && !e.fire_pit), rig = createRealLights(view, {fixtures});
  const hasEmitters = fixtures || emitters.some(e => e.fire_pit);
  const effects = new Map();
  const overlays = new THREE.Group(); overlays.userData.twinMode = 'modes'; view.scene.add(overlays);
  const context = {view, live, warm, overlays, lighting(on) { view.setLiveLamps?.(on); rig.show(on); }};
  for (const definition of modes()) if (definition.mount) effects.set(definition.id, definition.mount(context));
  for (const id of enabled) registry.get(id)?.enter?.(context);
  context.lighting(enabled.has('lights'));
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const lowTier = view.tier?.id === 'low' || view.tier === 'low';
  const washOpacity = () => lowTier || reducedMotion?.matches
    ? .72 : .65 + .15 * Math.sin(performance.now() * 2 * Math.PI / 3000);
  const breathing = [];
  // Placement, vertical references and mounting offsets have one owner.
  // A small shared low-poly bulb adds no shadow draw calls.
  const bulbGeometry = new THREE.SphereGeometry(.1, 8, 6);
  // Above 1 only where the view glows what is brighter than white.
  const gain = view.emitterGain ?? 1;
  for (const emitter of emitters) {
    const position = new THREE.Vector3(...emitter.position);
    const marker = emitter.legacy ? emitter.marker : {...emitter, at: [position.x / FT, -position.z / FT, position.y / FT]};
    const glow = !emitter.fire_pit && ['line', 'area'].includes(emitter.shape) ? createFixtureGlow(view.scene, emitter, gain) : null;
    const bulb = glow?.mesh || new THREE.Mesh(bulbGeometry, new THREE.MeshBasicMaterial({ color: '#fff1c9', toneMapped: false }));
    if (!glow) { bulb.position.copy(position); bulb.userData.bulb = marker.device_id; view.scene.add(bulb); }
    bulb.visible = false;
    lamps.push({ marker, emitter, key: emitter.legacy ? marker.device_id : emitter.fixture_id,
      bulb, glow, position, distance: emitter.range * FT, intensity: 0, rgb: lightColor(), real: false });
  }
  // Object lamps join the same fixed-budget real-light pool as HA lamps.
  // Material instances survive batching and are changed in place on pushes.
  view.scene.updateMatrixWorld(true);
  const objectLamps = new Map();
  const flames = [];
  const garageDoors = [];
  view.scene.traverse(mesh => {
    if (mesh.userData.garageOpening) {
      const { building, opening } = mesh.userData.garageOpening;
      garageDoors.push({ group: mesh, entity: garageEntity(layout, building, opening) });
    }
    if (mesh.userData.fireFlame) flames.push(mesh);
    for (const material of mesh.material ? [].concat(mesh.material) : []) {
      const object = material.userData?.objectLight;
      if (!object) continue;
      if (!objectLamps.has(object.id)) objectLamps.set(object.id, { object, materials: new Set(), box: new THREE.Box3(), firePosition: null });
      const row = objectLamps.get(object.id); row.materials.add(material); row.box.expandByObject(mesh);
      if (object.fireLightAt) row.firePosition = mesh.parent.localToWorld(new THREE.Vector3(...object.fireLightAt));
    }
  });
  for (const { object, materials, box, firePosition } of objectLamps.values()) {
    const derived = object.fire && lamps.find(lamp => lamp.emitter?.fire_pit && lamp.emitter.device_id === 'object:' + object.id);
    if (derived) {derived.objectMaterials = [...materials];continue;}
    const position = firePosition || box.getCenter(new THREE.Vector3());
    if (!firePosition) position.y = box.max.y + .05;
    const at = [position.x / FT, -position.z / FT, position.y / FT];
    // A fire only takes over a legacy marker lamp; authored fixtures keep theirs.
    const existing = object.entity && lamps.find(lamp => lamp.marker.entity_id === object.entity &&
      (!object.fire || (!lamp.objectSource && (!lamp.emitter || lamp.emitter.legacy))));
    if (existing) {
      existing.objectMaterials = [...(existing.objectMaterials || []), ...materials];
      if (object.fire) {
        // A light-domain pit can also have an auto-placed room marker. Its
        // physical fire owns the light position, and never an indoor bake.
        existing.objectSource = object; existing.position.copy(position); existing.distance = 18 * FT;
        existing.marker = { device_id: 'object:' + object.id, entity_id: object.entity, at };
        existing.key = existing.marker.device_id; existing.emitter = null;
        existing.bulb.position.copy(position);
      }
      continue;
    }
    const bulb = new THREE.Mesh(bulbGeometry, new THREE.MeshBasicMaterial({ color: object.color, toneMapped: false }));
    bulb.position.copy(position); bulb.visible = false; view.scene.add(bulb);
    const rgb = new THREE.Color(object.color).getRGB(new THREE.Color(), THREE.SRGBColorSpace);
    const owner = view.plan.buildings.find(b => object.id.startsWith(b.id + ':'));
    const piece = owner && [...(owner.items || []), ...(owner.anchors || [])].find(p => object.id === `${owner.id}:${p.id}`);
    const level = owner?.walls?.find(w => w.id === piece?.host?.wall)?.level
      || owner?.rooms?.find(r => r.id === (piece?.host?.floor || piece?.host?.ceiling))?.level;
    lamps.push({ marker: { device_id: 'object:' + object.id, entity_id: object.entity, at, building: owner?.id, level },
      key: 'object:' + object.id,
      bulb, position, distance: 18 * FT, intensity: 0, rgb: [rgb.r * 255, rgb.g * 255, rgb.b * 255], real: false,
      objectSource: object, objectMaterials: [...materials] });
  }
  // Use the generator's slab shape, stair holes and building transform. Overlaying the
  // floor keeps shared/merged house materials intact and costs one draw per room.
  for (const room of layout.rooms.filter(room => room.state !== 'ghost')) {
    const building = view.plan.buildings.find(b => b.id === room.building);
    const planRoom = room.yard ? view.plan.site?.yard_rooms?.find(r => r.id === room.room) : building?.rooms?.find(r => r.id === room.room);
    const level = room.yard ? {elevation: 0} : building?.levels.find(l => l.id === room.level);
    const parent = room.yard ? view.groups.site : view.groups.levels[`${room.building}:${room.level}`];
    if (!planRoom?.polygon?.length || planRoom.state === 'ghost' || !level || !parent) continue;
    const cuts = room.yard ? [] : stairHoles(building, level).filter(h => h.every(p => contains(planRoom.polygon, p)));
    const material = new THREE.MeshBasicMaterial({ color: '#fff1c9', transparent: true, opacity: 0,
      depthWrite: false, toneMapped: false, side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(polygon(planRoom.polygon, roomFloor(level, planRoom) + .035, roomFloor(level, planRoom) + .035, cuts), material);
    if (room.yard) {
      const points = mesh.geometry.attributes.position;
      for (let i = 0; i < points.count; i++) points.setY(i, points.getY(i) + groundAt(view.plan, points.getX(i), -points.getZ(i)));
    }
    mesh.userData.lightWash = { building: room.building, room: room.room };
    // The merged floor under it sorts as transparent, and by distance it can draw
    // after the wash and cover it. A later order keeps the wash on top of its floor.
    mesh.renderOrder = 2;
    const group = new THREE.Group(); group.scale.setScalar(FT);
    const position = building?.position || [0, 0];
    group.position.set(position[0] * FT, (building ? (building.base || 0) + buildingGround(view.plan, building) : 0) * FT, -position[1] * FT);
    group.rotation.y = (building?.rotation || 0) * Math.PI / 180;
    group.visible = false;
    const label = document.createElement('span'); label.hidden = true; climateLabels.append(label);
    const centre = planRoom.polygon.reduce((sum, p) => [sum[0] + p[0], sum[1] + p[1]], [0, 0]).map(v => v / planRoom.polygon.length);
    const point = new THREE.Vector3(centre[0], roomFloor(level, planRoom) + .1, -centre[1]);
    if (room.yard) point.y += groundAt(view.plan, ...centre);
    group.add(mesh); view.scene.add(group); floors.push({ room, mesh, group, parent, label, point });
  }
  // Compile Lights mode's shader programs now, with the pool, bulbs and washes
  // shown, so the first tap on Lights does
  // not stall while every material compiles (three.js keeps both variants per
  // material). compile() reads the scene synchronously; only the wait for the
  // GPU runs after, so the scene is put back at once. Real renderers only.
  // The time look (Day/Night) changes the light set every program is keyed on,
  // so the warm-up runs again for the new look (view.onTimeLook), restoring
  // exactly what was shown, whether Lights mode is on or not.
  function warm() {
    if (!realLighting || typeof view.renderer3?.compileAsync !== 'function' || !view.camera) return;
    const extras = [...flames, ...lamps.map(lamp => lamp.bulb), ...floors.map(floor => floor.group),
      ...[...effects.values()].flatMap(effect => effect.warmObjects?.() || [])];
    const shown = extras.map(object => object.visible), poolShown = rig.shown?.();
    rig.show(true); for (const object of extras) object.visible = true;
    try {
      rig.warm(() => view.renderer3.compileAsync(view.scene, view.camera).catch(() => {}));
      // Programs are keyed on the light set too. All shows the pool and the effects at
      // once (slice 2c-2), so compile the overlays a second time with the pool hidden,
      // the light set Climate, Energy and Security draw them under.
      rig.show(false);
      view.renderer3.compileAsync(view.scene, view.camera).catch(() => {});
      for (const effect of effects.values()) effect.warm?.();
    }
    catch { /* a failed warm-up only leaves the first entry its compile */ }
    finally { rig.show(!!poolShown); extras.forEach((object, i) => { object.visible = shown[i]; }); }
  }
  warm();
  view.onTimeLook = warm;
  function update() {
    // Read without copying the house: this runs on every push (review M3).
    const states = live.peek(), stale = live.stale();
    for (const door of garageDoors) garagePose(door.group, !stale && ['open', 'opening'].includes(states[door.entity]?.state));
    const resolved = new Map((hasEmitters ? resolveEmitters(layout, stale ? {} : states, view.plan, {looks: live.looks?.() || {}}) : []).map(e => [e.fixture_id, e]));
    for (const flame of flames) flame.visible = !stale && states[flame.material.userData.objectLight.entity]?.state === 'on';
    legacyRooms = !realLighting && !stale ? live.rooms() : [];
    for (const lamp of lamps) {
      const state = states[lamp.marker.entity_id];
      const object = lamp.objectSource;
      const emitted = emission(stale ? null : state, lamp.marker.entity_id?.split('.')[0], live.looks?.()[lamp.marker.entity_id]);
      lamp.intensity = object && !object.entity ? (object.on ? 1 : 0) : emitted.brightness;
      if (lamp.emitter && !lamp.emitter.legacy) {
        lamp.emitter = resolved.get(lamp.emitter.fixture_id);
        lamp.intensity = lamp.emitter?.on ? lamp.emitter.brightness * (lamp.emitter.intensityScale ?? 1) : 0;
      }
      if (object?.fire) lamp.intensity *= object.intensityScale ?? .5;
      if (object && (!object.entity || object.fire)) {
        const color = new THREE.Color(object.color).getRGB(new THREE.Color(), THREE.SRGBColorSpace);
        lamp.rgb = [color.r * 255, color.g * 255, color.b * 255];
      } else lamp.rgb = lamp.emitter?.fire_pit ? lamp.emitter.rgb : emitted.rgb;
      lamp.palette = (object && (!object.entity || object.fire)) || lamp.emitter?.fire_pit ? undefined : emitted.palette;
      for (const material of lamp.objectMaterials || []) {
        if (!material.emissive) continue; // Flame shaders carry the lamp tag too.
        material.emissive.setRGB(...lamp.rgb.map(value => value / 255), THREE.SRGBColorSpace);
        material.emissiveIntensity = lamp.intensity * gain;
      }
    }
    revision++;
    const zones = resolveClimateZones(layout, states, stale);
    for (const floor of floors) floor.climate = zones.get(climateRoomKey(floor.room));
    for (const effect of effects.values()) effect.update?.(enabled);
    const content = [...enabled].flatMap(id => effects.get(id)?.legendContent?.() || []);
    if (content.length !== legendContent.children.length || content.some((node, i) => legendContent.children[i] !== node))
      legendContent.replaceChildren(...content);
    for (const [value, button] of buttons) button.setAttribute('aria-pressed', String(value === 'all' ? enabled.size === ids.length : enabled.has(value)));
    for (const id of enabled) registry.get(id)?.update?.(context);
    draw();
  }
  function draw() {
    if (lamps.some(lamp => lamp.emitter?.fire_effect)) {
      const rows = fireEffectEmitters(view.plan, live.peek(), live.stale(), view.effects?.fixtures);
      const key = rows.map(e => `${e.fixture_id}:${e.brightness}`).join('|');
      if (key !== effectLampKey) {
        effectLampKey = key; revision++;
      }
      for (const lamp of lamps) if (lamp.emitter?.fire_effect) {
        lamp.emitter = rows.find(e => e.fixture_id === lamp.emitter.fixture_id);
        lamp.intensity = lamp.emitter?.on ? lamp.emitter.brightness * lamp.emitter.intensityScale : 0;
        lamp.rgb = lamp.emitter?.rgb || [255,154,60];
      }
    }
    for (const flame of flames) flame.material.uniforms.time.value = performance.now() / 1000;
    climateLabels.hidden = !enabled.has('climate');
    for (const effect of effects.values()) effect.draw?.(enabled);
    const target = view.controls?.target;
    const key = [revision, target?.x, target?.y, target?.z,
      ...floors.map(floor => floor.parent.visible),
      ...lamps.map(lamp => view.groups.levels[`${lamp.marker.building}:${lamp.marker.level}`]?.visible !== false)].join('|');
    // Labels follow the camera, including the idle orbit; their floors are reused.
    for (const floor of floors) {
      const show = enabled.has('climate') && floor.parent.visible && !!floor.climate?.label;
      floor.label.hidden = !show;
      if (show) {
        floor.group.updateMatrixWorld(true); view.camera.updateMatrixWorld(true);
        const p = floor.group.localToWorld(floor.point.clone()).project(view.camera);
        const rect = view.renderer3.domElement.getBoundingClientRect();
        floor.label.hidden = p.z < -1 || p.z > 1;
        floor.label.textContent = floor.climate.label;
        floor.label.style.left = `${rect.left + (p.x + 1) * rect.width / 2}px`;
        floor.label.style.top = `${rect.top + (1 - p.y) * rect.height / 2}px`;
      }
    }
    // Breathing only changes shown wash materials; lamp selection and bake stay cached.
    if (!lowTier && breathing.length) {
      const opacity = washOpacity();
      for (const floor of breathing) if (floor.group.visible && floor.parent.visible) floor.mesh.material.opacity = opacity;
    }
    if (key === lastKey) return;
    lastKey = key;
    const candidates = lamps.filter(lamp => enabled.has('lights') && lamp.intensity > 0 &&
      view.groups.levels[`${lamp.marker.building}:${lamp.marker.level}`]?.visible !== false)
      .map(lamp => ({ device: lamp.key, at: lamp.marker.at, ...lamp }));
    const fresh = new Set(view.bake?.fresh() || []);
    for (const id of paletteLineEntities(lamps)) fresh.delete(id);
    const selected = rig.update(realLighting ? candidates : [], target ? [target.x / FT, -target.z / FT, target.y / FT] : [0, 0, 0], fresh);
    const overflowText = enabled.has('lights') && rig.overflow() ? 'Some lights are shown as glow only on this tier' : '';
    legendText.textContent = [...enabled].map(id => effects.get(id)?.legend?.() || registry.get(id)?.legend || '').concat(overflowText).filter(Boolean).join(' · ');
    modeLegend.hidden = !modeLegend.textContent;
    const bakeTints = new Map();
    for (const lamp of lamps) {
      const bakeId = lamp.emitter && !lamp.emitter.legacy ? lamp.emitter.entity_id : lamp.marker.device_id;
      const baked = fresh.has(bakeId);
      const shown = candidates.some(row => row.device === lamp.key);
      // Clear a former bake too: losing freshness must never leave its tint on.
      if (baked || lamp.baked) {
        // Sum slots carry each pit's half output in their samples. One tint
        // cannot also carry the pit's flame colour beside arbitrary HA colours.
        const sum = lamp.emitter && !lamp.emitter.legacy && lamps.some(other =>
          other !== lamp && other.emitter?.entity_id === lamp.emitter.entity_id);
        const intensity = baked && shown ? (sum ? lamp.emitter.brightness : lamp.intensity) : 0, previous = bakeTints.get(bakeId);
        if (!previous || intensity > previous.intensity || intensity === previous.intensity && lamp.intensity > 0 && !lamp.emitter?.fire_pit)
          bakeTints.set(bakeId, {rgb: lamp.rgb, intensity});
      }
      lamp.baked = baked;
      lamp.real = selected.has(lamp.key);
      if (lamp.glow) lamp.glow.update(lamp.rgb, lamp.intensity, shown, lamp.palette);
      else {
        lamp.bulb.visible = shown && !lamp.objectSource?.fire && !lamp.emitter?.fire_pit;
        lamp.bulb.material.color.setRGB(...lamp.rgb.map(value => value / 255), THREE.SRGBColorSpace).multiplyScalar(gain);
      }
    }
    for (const [id, tint] of bakeTints) view.bake?.light(id, tint.rgb, tint.intensity);
    breathing.length = 0;
    for (const floor of floors) {
      const { room, mesh, group, parent } = floor;
      const overflow = candidates.filter(lamp => (!lamp.emitter || lamp.emitter.legacy) && !selected.has(lamp.device) && !fresh.has(lamp.device) &&
        lamp.marker.building === room.building && lamp.marker.room === room.room);
      const legacy = legacyRooms.find(row => row.building === room.building && row.room === room.room);
      const glow = realLighting ? (overflow.length ? overflow.reduce((sum, lamp) => sum + lamp.intensity, 0) / overflow.length : 0) : legacy?.glow || 0;
      const active = ['heat', 'cool'].includes(floor.climate?.action);
      const tint = enabled.has('climate') && (active || enabled.size === 1 && floor.climate?.action === 'idle');
      group.visible = parent.visible && (tint || enabled.has('lights') && glow > 0);
      mesh.material.opacity = tint ? active ? washOpacity() : .35 : glow * .85;
      if (tint && active && group.visible) breathing.push(floor);
      const rgb = tint ? climateColors[floor.climate.action] : (realLighting ? overflow[0]?.rgb : legacy?.rgb) || [255, 241, 201];
      mesh.material.color.setRGB(...rgb.map(value => value / 255), THREE.SRGBColorSpace);
    }
  }
  const unsubscribe = live.subscribe(update); update();
  function setModes(values) {
    const next = new Set(ids.filter(id => values.includes(id)));
    for (const id of enabled) if (!next.has(id)) registry.get(id)?.leave?.(context);
    for (const id of next) if (!enabled.has(id)) registry.get(id)?.enter?.(context);
    enabled = next; saveModes(enabled); update();
    return [...enabled];
  }
  return {
    setMode(value) {
      setModes(ids.includes(value) ? [value] : ids);
      return modeName(enabled, ids);
    },
    setModes,
    toggleMode(id) {
      return setModes(id === 'all' ? enabled.size === ids.length ? [] : ids
        : enabled.has(id) ? [...enabled].filter(value => value !== id) : [...enabled, id]);
    },
    modes: () => [...enabled],
    get mode() { return modeName(enabled, ids); },
    draw, update,
    energy: () => effects.get('energy')?.snapshot(),
    lights: () => lamps.map(lamp => ({ device: lamp.marker.device_id, fixture_id: lamp.emitter?.fixture_id, at: [...lamp.marker.at],
      rgb: [...lamp.rgb], intensity: lamp.intensity, real: lamp.real, baked: !!lamp.baked })),
    stop() {
      for (const timer of timers) clearTimeout(timer);
      for (const door of garageDoors) garagePose(door.group, false);
      for (const flame of flames) flame.visible = false;
      for (const lamp of lamps) if (lamp.baked) view.bake?.light(lamp.emitter && !lamp.emitter.legacy ? lamp.emitter.entity_id : lamp.marker.device_id, lamp.rgb, 0);
      unsubscribe(); strip.remove(); climateLabels.remove(); modeLegend.remove();
      for (const id of enabled) registry.get(id)?.leave?.(context);
      rig.stop();
      for (const effect of effects.values()) effect.stop?.();
      overlays.removeFromParent();
      if (view.onTimeLook === warm) view.onTimeLook = null;
      for (const { bulb, glow } of lamps) { if (glow) glow.stop(); else { bulb.removeFromParent(); bulb.material.dispose(); } }
      bulbGeometry.dispose();
      for (const { group, mesh } of floors) { group.removeFromParent(); mesh.geometry.dispose(); mesh.material.dispose(); }
    },
  };
}
