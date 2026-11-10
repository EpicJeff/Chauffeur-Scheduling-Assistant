import * as THREE from 'three';
import { FT, polygon, contains, stairHoles } from '../twin_generator.js';
import { groundAt } from '../twin_ground.js';

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
  for (const [label, mode] of [['Lights', 'lights'], ['All', null]]) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.addEventListener('click', () => live.setMode(mode)); strip.append(button); buttons.set(mode, button);
  }
  document.getElementById('twin-controls').append(strip);
  let mode = null;
  const floors = [];
  // Use the generator's slab shape, stair holes and building transform. Overlaying the
  // floor keeps shared/merged house materials intact and costs one draw per room.
  for (const room of live.layout().rooms.filter(room => room.area_id)) {
    const building = view.plan.buildings.find(b => b.id === room.building);
    const planRoom = building?.rooms?.find(r => r.id === room.room);
    const level = building?.levels.find(l => l.id === room.level);
    const parent = view.groups.levels[`${room.building}:${room.level}`];
    if (!planRoom?.polygon?.length || !level || !parent) continue;
    const cuts = stairHoles(building, level).filter(h => h.every(p => contains(planRoom.polygon, p)));
    const material = new THREE.MeshBasicMaterial({ color: '#fff1c9', transparent: true, opacity: 0,
      depthWrite: false, toneMapped: false, side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(polygon(planRoom.polygon, level.elevation + .035, level.elevation + .035, cuts), material);
    const group = new THREE.Group(); group.scale.setScalar(FT);
    const position = building.position || [0, 0];
    group.position.set(position[0] * FT, ((building.base || 0) + groundAt(view.plan, ...position)) * FT, -position[1] * FT);
    group.rotation.y = (building.rotation || 0) * Math.PI / 180;
    group.add(mesh); view.scene.add(group); floors.push({ room, mesh, group, parent, lit: false });
  }
  function update() {
    const rooms = live.rooms();
    for (const [value, button] of buttons) button.setAttribute('aria-pressed', String(value === mode));
    for (const floor of floors) {
      const { room, mesh, group, parent } = floor;
      const state = rooms.find(r => r.building === room.building && r.room === room.room);
      floor.lit = state?.glow > 0;
      group.visible = mode === 'lights' && parent.visible && floor.lit;
      mesh.material.opacity = (state?.glow || 0) * .85;
      if (state?.rgb) mesh.material.color.setRGB(...state.rgb.map(value => value / 255), THREE.SRGBColorSpace);
      else mesh.material.color.set('#fff1c9');
    }
  }
  const unsubscribe = live.subscribe(update); update();
  return {
    setMode(value) { mode = value; update(); },
    draw() { for (const { group, parent, lit } of floors) group.visible = mode === 'lights' && parent.visible && lit; },
    stop() {
      unsubscribe(); strip.remove();
      for (const { group, mesh } of floors) { group.removeFromParent(); mesh.geometry.dispose(); mesh.material.dispose(); }
    },
  };
}
