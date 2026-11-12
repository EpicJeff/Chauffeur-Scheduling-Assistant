import * as THREE from 'three';
import { FT, polygon, contains, stairHoles } from '../twin_generator.js';
import { lightRange, LAMP_HEIGHT } from '../twin_light_math.js';
export { lightRange, LAMP_HEIGHT } from '../twin_light_math.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { lightColor, lightIntensity, createRealLights } from './real_lights.js';
import { registerClimate, roomClimate } from './climate.js';
import { registerEnergy } from './energy.js';
import { registerSecurity } from './security.js';

const registry = new Map();
export function registerMode(mode) { registry.set(mode.id, mode); return mode; }
export function modes() { return [...registry.values()]; }
export const modeForeground = (id, row, state) => registry.get(id)?.foreground?.(row, state) ?? true;

registerMode({id: 'lights', label: 'Lights',
  foreground: row => row.kind === 'light',
  enter: ({lighting}) => lighting(true), update() {}, leave: ({lighting}) => lighting(false)});
registerMode({id: 'all', label: 'All', enter() {}, update() {}, leave() {}});
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
  const strip = document.createElement('fieldset'); strip.id = 'twin-modes';
  const legend = document.createElement('legend'); legend.textContent = 'Devices'; strip.append(legend);
  const buttons = new Map();
  for (const mode of modes()) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = mode.label;
    button.addEventListener('click', () => live.setMode(mode.id)); strip.append(button); buttons.set(mode.id, button);
  }
  document.getElementById('twin-controls').append(strip);
  const climateLabels = document.createElement('div'); climateLabels.className = 'twin-mode-labels twin-climate-labels';
  const modeLegend = document.createElement('output'); modeLegend.id = 'twin-mode-legend'; modeLegend.hidden = true;
  const legendText = document.createElement('span'), legendContent = document.createElement('div'); modeLegend.append(legendText, legendContent);
  document.getElementById('twin-controls').append(modeLegend);
  document.body.append(climateLabels);
  let mode = 'all', lastKey = '', revision = 0;
  const floors = [], lamps = [];
  // Older embeds do not expose a render tier. Keep their room overview until
  // they mount the current view, whose tier supplies the real-light budget.
  const realLighting = !!view.tier;
  let legacyRooms = [];
  const rig = createRealLights(view);
  const effects = new Map();
  const overlays = new THREE.Group(); overlays.userData.twinMode = 'modes'; view.scene.add(overlays);
  const context = {view, live, warm, overlays, lighting(on) { view.setLiveLamps?.(on); rig.show(on); }};
  for (const definition of modes()) if (definition.mount) effects.set(definition.id, definition.mount(context));
  registry.get(mode).enter(context);
  const layout = live.layout();
  const climateDevices = layout.devices || layout.markers;
  // The same world transform as the marker, including lot ground elevation.
  // A small shared low-poly bulb adds no shadow draw calls.
  const bulbGeometry = new THREE.SphereGeometry(.1, 8, 6);
  for (const marker of layout.markers.filter(row => row.kind === 'light')) {
    const building = view.plan.buildings.find(b => b.id === marker.building);
    const room = building?.rooms?.find(r => r.id === marker.room);
    const xs = room?.polygon?.map(p => p[0]) || [], ys = room?.polygon?.map(p => p[1]) || [];
    const span = xs.length ? Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1) : 10;
    const level = building?.levels.find(l => l.id === marker.level);
    // A light standing on the floor is a floor lamp: its bulb, and so its light,
    // hangs LAMP_HEIGHT above the floor (a bulb on the floor makes one hot spot
    // and lights nothing). The marker stays where the person put it.
    const floor = (building?.base || 0) + (level?.elevation || 0);
    const standing = !!level && marker.at[2] <= floor + .1;
    const z = standing ? floor + LAMP_HEIGHT : marker.at[2];
    const range = lightRange({ ...marker, at: [marker.at[0], marker.at[1], z] }, building, level, room, span);
    const position = new THREE.Vector3(marker.at[0] * FT,
      (z + buildingGround(view.plan, building)) * FT, -marker.at[1] * FT);
    // Ceiling placements sit just below the slab so their own fixture cannot
    // occlude them. Wall placements retain the person's chosen height.
    if (level && !standing && marker.at[2] >= floor + level.ceiling - .1) position.y -= .2 * FT;
    const bulb = new THREE.Mesh(bulbGeometry, new THREE.MeshBasicMaterial({ color: '#fff1c9', toneMapped: false }));
    bulb.position.copy(position); bulb.userData.bulb = marker.device_id; bulb.visible = false;
    view.scene.add(bulb);
    lamps.push({ marker, bulb, position, distance: range * FT, intensity: 0, rgb: lightColor(), real: false });
  }
  // Object lamps join the same fixed-budget real-light pool as HA lamps.
  // Material instances survive batching and are changed in place on pushes.
  view.scene.updateMatrixWorld(true);
  const objectLamps = new Map();
  view.scene.traverse(mesh => {
    for (const material of mesh.material ? [].concat(mesh.material) : []) {
      const object = material.userData?.objectLight;
      if (!object) continue;
      if (!objectLamps.has(object.id)) objectLamps.set(object.id, { object, materials: new Set(), box: new THREE.Box3() });
      const row = objectLamps.get(object.id); row.materials.add(material); row.box.expandByObject(mesh);
    }
  });
  for (const { object, materials, box } of objectLamps.values()) {
    const existing = object.entity && lamps.find(lamp => lamp.marker.entity_id === object.entity);
    if (existing) { existing.objectMaterials = [...(existing.objectMaterials || []), ...materials]; continue; }
    const position = box.getCenter(new THREE.Vector3()); position.y = box.max.y + .05;
    const at = [position.x / FT, -position.z / FT, position.y / FT];
    const bulb = new THREE.Mesh(bulbGeometry, new THREE.MeshBasicMaterial({ color: object.color, toneMapped: false }));
    bulb.position.copy(position); bulb.visible = false; view.scene.add(bulb);
    const rgb = new THREE.Color(object.color).getRGB(new THREE.Color(), THREE.SRGBColorSpace);
    const owner = view.plan.buildings.find(b => object.id.startsWith(b.id + ':'));
    const piece = owner && [...(owner.items || []), ...(owner.anchors || [])].find(p => object.id === `${owner.id}:${p.id}`);
    const level = owner?.walls?.find(w => w.id === piece?.host?.wall)?.level
      || owner?.rooms?.find(r => r.id === (piece?.host?.floor || piece?.host?.ceiling))?.level;
    lamps.push({ marker: { device_id: 'object:' + object.id, entity_id: object.entity, at, building: owner?.id, level },
      bulb, position, distance: 18 * FT, intensity: 0, rgb: [rgb.r * 255, rgb.g * 255, rgb.b * 255], real: false,
      objectSource: object, objectMaterials: [...materials] });
  }
  // Use the generator's slab shape, stair holes and building transform. Overlaying the
  // floor keeps shared/merged house materials intact and costs one draw per room.
  for (const room of layout.rooms.filter(room => room.area_id)) {
    const building = view.plan.buildings.find(b => b.id === room.building);
    const planRoom = building?.rooms?.find(r => r.id === room.room);
    const level = building?.levels.find(l => l.id === room.level);
    const parent = view.groups.levels[`${room.building}:${room.level}`];
    if (!planRoom?.polygon?.length || !level || !parent) continue;
    const cuts = stairHoles(building, level).filter(h => h.every(p => contains(planRoom.polygon, p)));
    const material = new THREE.MeshBasicMaterial({ color: '#fff1c9', transparent: true, opacity: 0,
      depthWrite: false, toneMapped: false, side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(polygon(planRoom.polygon, level.elevation + .035, level.elevation + .035, cuts), material);
    mesh.userData.lightWash = { building: room.building, room: room.room };
    const group = new THREE.Group(); group.scale.setScalar(FT);
    const position = building.position || [0, 0];
    group.position.set(position[0] * FT, ((building.base || 0) + buildingGround(view.plan, building)) * FT, -position[1] * FT);
    group.rotation.y = (building.rotation || 0) * Math.PI / 180;
    group.visible = false;
    const label = document.createElement('span'); label.hidden = true; climateLabels.append(label);
    const centre = planRoom.polygon.reduce((sum, p) => [sum[0] + p[0], sum[1] + p[1]], [0, 0]).map(v => v / planRoom.polygon.length);
    const point = new THREE.Vector3(centre[0], level.elevation + .1, -centre[1]);
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
    const extras = [...lamps.map(lamp => lamp.bulb), ...floors.map(floor => floor.group),
      ...[...effects.values()].flatMap(effect => effect.warmObjects?.() || [])];
    const shown = extras.map(object => object.visible), poolShown = rig.shown?.();
    rig.show(true); for (const object of extras) object.visible = true;
    try {
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
    legacyRooms = !realLighting && !stale ? live.rooms() : [];
    for (const lamp of lamps) {
      const state = states[lamp.marker.entity_id];
      const object = lamp.objectSource;
      lamp.intensity = object && !object.entity ? (object.on ? 1 : 0) : !stale && state?.state === 'on' ? lightIntensity(state.attributes) : 0;
      if (object && !object.entity) {
        const color = new THREE.Color(object.color).getRGB(new THREE.Color(), THREE.SRGBColorSpace);
        lamp.rgb = [color.r * 255, color.g * 255, color.b * 255];
      } else lamp.rgb = lightColor(state?.attributes);
      for (const material of lamp.objectMaterials || []) {
        material.emissive.setRGB(...lamp.rgb.map(value => value / 255), THREE.SRGBColorSpace);
        material.emissiveIntensity = lamp.intensity;
      }
    }
    revision++;
    for (const floor of floors) floor.climate = roomClimate(floor.room, climateDevices, stale ? {} : states);
    for (const effect of effects.values()) effect.update?.(mode);
    legendText.textContent = effects.get(mode)?.legend?.() || registry.get(mode)?.legend || '';
    const content = effects.get(mode)?.legendContent?.();
    if (legendContent.firstChild !== (content || null)) legendContent.replaceChildren(...(content ? [content] : []));
    modeLegend.hidden = !modeLegend.textContent;
    for (const [value, button] of buttons) button.setAttribute('aria-pressed', String(value === mode));
    registry.get(mode)?.update?.(context);
    draw();
  }
  function draw() {
    climateLabels.hidden = mode !== 'climate';
    for (const effect of effects.values()) effect.draw?.(mode);
    const target = view.controls?.target;
    const key = [revision, mode, target?.x, target?.y, target?.z,
      ...floors.map(floor => floor.parent.visible),
      ...lamps.map(lamp => view.groups.levels[`${lamp.marker.building}:${lamp.marker.level}`]?.visible !== false)].join('|');
    // Labels follow the camera, including the idle orbit; their floors are reused.
    for (const floor of floors) {
      const show = mode === 'climate' && floor.parent.visible && !!floor.climate?.label;
      floor.label.hidden = !show;
      if (show) {
        floor.group.updateMatrixWorld(true); view.camera.updateMatrixWorld(true);
        const p = floor.group.localToWorld(floor.point.clone()).project(view.camera);
        const rect = view.renderer3.domElement.getBoundingClientRect();
        floor.label.hidden = p.z < -1 || p.z > 1;
        floor.label.textContent = `${floor.room.name || ''} ${floor.climate.label}`;
        floor.label.style.left = `${rect.left + (p.x + 1) * rect.width / 2}px`;
        floor.label.style.top = `${rect.top + (1 - p.y) * rect.height / 2}px`;
      }
    }
    if (key === lastKey) return;
    lastKey = key;
    const candidates = lamps.filter(lamp => mode === 'lights' && lamp.intensity > 0 &&
      view.groups.levels[`${lamp.marker.building}:${lamp.marker.level}`]?.visible !== false)
      .map(lamp => ({ device: lamp.marker.device_id, at: lamp.marker.at, ...lamp }));
    const fresh = new Set(view.bake?.fresh() || []);
    const selected = rig.update(realLighting ? candidates : [], target ? [target.x / FT, -target.z / FT, target.y / FT] : [0, 0, 0]);
    for (const lamp of lamps) {
      const baked = fresh.has(lamp.marker.device_id);
      const shown = candidates.some(row => row.device === lamp.marker.device_id);
      // Clear a former bake too: losing freshness must never leave its tint on.
      if (baked || lamp.baked) view.bake?.light(lamp.marker.device_id, lamp.rgb, baked && shown ? lamp.intensity : 0);
      lamp.baked = baked;
      lamp.real = selected.has(lamp.marker.device_id);
      lamp.bulb.visible = shown;
      lamp.bulb.material.color.setRGB(...lamp.rgb.map(value => value / 255), THREE.SRGBColorSpace);
    }
    for (const floor of floors) {
      const { room, mesh, group, parent } = floor;
      const overflow = candidates.filter(lamp => !selected.has(lamp.device) && !fresh.has(lamp.device) &&
        lamp.marker.building === room.building && lamp.marker.room === room.room);
      const legacy = legacyRooms.find(row => row.building === room.building && row.room === room.room);
      const glow = realLighting ? (overflow.length ? overflow.reduce((sum, lamp) => sum + lamp.intensity, 0) / overflow.length : 0) : legacy?.glow || 0;
      group.visible = parent.visible && (mode === 'climate' || mode === 'lights' && glow > 0);
      mesh.material.opacity = mode === 'climate' ? .72 : glow * .85;
      const rgb = mode === 'climate' ? floor.climate.rgb : (realLighting ? overflow[0]?.rgb : legacy?.rgb) || [255, 241, 201];
      mesh.material.color.setRGB(...rgb.map(value => value / 255), THREE.SRGBColorSpace);
    }
  }
  const unsubscribe = live.subscribe(update); update();
  return {
    setMode(value) {
      value = registry.has(value) ? value : 'all';
      if (mode !== value) {
        registry.get(mode)?.leave?.(context); mode = value; registry.get(mode)?.enter?.(context);
      }
      update();
      return mode;
    },
    draw, update,
    energy: () => effects.get('energy')?.snapshot(),
    lights: () => lamps.map(lamp => ({ device: lamp.marker.device_id, at: [...lamp.marker.at],
      rgb: [...lamp.rgb], intensity: lamp.intensity, real: lamp.real, baked: !!lamp.baked })),
    stop() {
      for (const lamp of lamps) if (lamp.baked) view.bake?.light(lamp.marker.device_id, lamp.rgb, 0);
      unsubscribe(); strip.remove(); climateLabels.remove(); modeLegend.remove();
      registry.get(mode)?.leave?.(context);
      rig.stop();
      for (const effect of effects.values()) effect.stop?.();
      overlays.removeFromParent();
      if (view.onTimeLook === warm) view.onTimeLook = null;
      for (const { bulb } of lamps) { bulb.removeFromParent(); bulb.material.dispose(); }
      bulbGeometry.dispose();
      for (const { group, mesh } of floors) { group.removeFromParent(); mesh.geometry.dispose(); mesh.material.dispose(); }
    },
  };
}
