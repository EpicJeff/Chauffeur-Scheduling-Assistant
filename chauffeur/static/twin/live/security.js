import * as THREE from 'three';
import { FT } from '../twin_generator.js';
import { groundAt } from '../twin_ground.js';
import { buildingCentre, lotPoint } from './energy_geometry.js';

export function securityItem(row, state) {
  const domain = row.entity_id?.split('.')[0], kind = row.kind, dc = state?.attributes?.device_class;
  return ['lock', 'garage', 'camera', 'alarm'].includes(kind) || ['lock', 'camera', 'alarm_control_panel'].includes(domain) ||
    domain === 'binary_sensor' && ['door', 'window', 'opening', 'garage_door'].includes(dc) ||
    domain === 'cover' && ['garage', 'door', 'gate'].includes(dc);
}
export function securityAttention(row, state) {
  if (!securityItem(row, state)) return false;
  if (row.kind === 'camera' || row.entity_id?.startsWith('camera.')) return false;
  return ['unlocked', 'open', 'opening', 'triggered', 'pending'].includes(state?.state) ||
    row.entity_id?.startsWith('binary_sensor.') && state?.state === 'on' ||
    (row.kind === 'garage' || row.entity_id?.startsWith('cover.')) && Number(state?.attributes?.current_position) > 0;
}
// Lot-frame facing is degrees, counterclockwise from +X toward plan +Y.
export function cameraDirection(marker, roomCentre, houseCentre) {
  const facing = marker.facing_deg ?? marker.orientation;
  if (Number.isFinite(facing)) return [Math.cos(facing * Math.PI / 180), Math.sin(facing * Math.PI / 180)];
  const indoor = marker.outdoor !== true && marker.room && roomCentre;
  const target = indoor ? roomCentre : houseCentre;
  const sign = indoor ? 1 : -1;
  const dx = sign * ((target?.[0] || 0) - marker.at[0]), dy = sign * ((target?.[1] || 0) - marker.at[1]);
  const length = Math.hypot(dx, dy);
  return length > .001 ? [dx / length || 0, dy / length || 0] : [0, -1];
}
export function mountSecurity({view, live, overlays = view.scene}) {
  const root = new THREE.Group(); root.userData.twinMode = 'security'; overlays.add(root);
  const emphasis = [], cones = [], layout = live.layout();
  for (const marker of layout.markers) {
    // Contacts may acquire their device class on the first live poll.
    if (!['lock', 'garage', 'camera', 'alarm', 'sensor'].includes(marker.kind) &&
        !/^(lock|camera|binary_sensor|alarm_control_panel|cover)\./.test(marker.entity_id)) continue;
    const building = view.plan.buildings.find(b => b.id === marker.building);
    const base = groundAt(view.plan, ...(building?.position || [0, 0]));
    const at = new THREE.Vector3(marker.at[0] * FT, (marker.at[2] + base) * FT, -marker.at[1] * FT);
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(.42, 12, 8),
      new THREE.MeshBasicMaterial({color: '#ef4949', transparent: true, opacity: .75, depthTest: false, depthWrite: false, toneMapped: false}));
    mesh.position.copy(at); mesh.visible = false; mesh.renderOrder = 19;
    mesh.userData.securityAttention = marker.device_id; root.add(mesh); emphasis.push({marker, mesh});
    if (marker.kind !== 'camera' && !marker.entity_id.startsWith('camera.')) continue;
    const room = layout.rooms.find(r => r.building === marker.building && r.room === marker.room);
    let centre = null;
    if (room?.polygon_world?.length) centre = room.polygon_world.reduce((s, p) => [s[0] + p[0] / room.polygon_world.length, s[1] + p[1] / room.polygon_world.length], [0, 0]);
    if (!centre) {
      const planRoom = building?.rooms?.find(r => r.id === marker.room);
      if (planRoom?.polygon?.length) centre = lotPoint(building, [...planRoom.polygon.reduce((s, p) => s.map((v, i) => v + p[i] / planRoom.polygon.length), [0, 0]), 0], view.plan);
    }
    const house = building ? buildingCentre(building, view.plan) : [0, 0];
    const direction = cameraDirection(marker, centre, house), length = 25 * FT;
    const cone = new THREE.Mesh(new THREE.ConeGeometry(length * .45, length, 16, 1, true).translate(0, -length / 2, 0),
      new THREE.MeshBasicMaterial({color: '#9abfe5', transparent: true, opacity: .12, side: THREE.DoubleSide, depthWrite: false, toneMapped: false}));
    cone.position.copy(at); cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, -1, 0), new THREE.Vector3(direction[0], 0, -direction[1]));
    cone.userData.cameraCone = {device: marker.device_id, direction, length_ft: 25}; cone.visible = false;
    root.add(cone); cones.push({marker, mesh: cone});
  }
  return {warmObjects: () => [...emphasis, ...cones].map(r => r.mesh),
    update(mode) {
      for (const {marker, mesh} of emphasis) mesh.visible = mode === 'security' && !live.stale() && securityAttention(marker, live.state(marker.entity_id));
      for (const {mesh} of cones) mesh.visible = mode === 'security';
    },
    legend() {
      const alarms = Object.entries(live.peek()).filter(([id]) => id.startsWith('alarm_control_panel.'));
      return 'Red · Open / unlocked   |   Camera view · 25 ft' + alarms.map(([id, s]) => `   |   ${s.attributes?.friendly_name || id}: ${live.stale() ? 'unavailable' : s.state.replaceAll('_', ' ')}`).join('');
    },
    stop() { root.removeFromParent(); root.traverse(o => {o.geometry?.dispose(); o.material?.dispose();}); }};
}
export function registerSecurity(registerMode) {
  registerMode({id: 'security', label: 'Security', foreground: securityItem, mount: mountSecurity});
}
