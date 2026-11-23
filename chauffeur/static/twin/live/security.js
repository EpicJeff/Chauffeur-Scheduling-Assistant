import * as THREE from 'three';
import { modeShows } from './mode_state.js';
import { FT } from '../twin_generator.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { buildingCentre, lotPoint } from './energy_geometry.js';
import { collectStaticOccluders, buildOccluderBVH, buildOccludedCone, createConeMaterials } from './cone_occluder.js';

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
  if (marker.camera_view) {
    const { aim } = marker.camera_view, dx = aim[0] - marker.at[0], dy = aim[1] - marker.at[1], length = Math.hypot(dx, dy);
    if (length > 1e-8) return [dx / length, dy / length];
  }
  const facing = marker.facing_deg ?? marker.orientation;
  if (Number.isFinite(facing)) return [Math.cos(facing * Math.PI / 180), Math.sin(facing * Math.PI / 180)];
  const indoor = marker.outdoor !== true && marker.room && roomCentre;
  const target = indoor ? roomCentre : houseCentre;
  const sign = indoor ? 1 : -1;
  const dx = sign * ((target?.[0] || 0) - marker.at[0]), dy = sign * ((target?.[1] || 0) - marker.at[1]);
  const length = Math.hypot(dx, dy);
  return length > .001 ? [dx / length || 0, dy / length || 0] : [0, -1];
}
const FALLBACK_FOV_DEG = 2 * Math.atan(0.45) * 180 / Math.PI;

function resolveConeSpec(marker, layout, plan) {
  const building = plan.buildings?.find(b => b.id === marker.building);
  const base = buildingGround(plan, building);
  const originFt = [marker.at[0], marker.at[1], marker.at[2] + base];
  const origin = new THREE.Vector3(originFt[0] * FT, originFt[2] * FT, -originFt[1] * FT);
  const saved = marker.camera_view || layout.camera_views?.[marker.entity_id] || plan.camera_views?.[marker.entity_id];
  if (saved?.aim) {
    const aim = new THREE.Vector3(saved.aim[0] * FT, saved.aim[2] * FT, -saved.aim[1] * FT);
    const axis = aim.clone().sub(origin);
    const length = axis.length();
    if (length > 1e-6) axis.divideScalar(length); else axis.set(0, 0, -1);
    const fovDeg = saved.fov_deg ?? 90;
    const lengthFt = Math.hypot(...saved.aim.map((v, i) => v - originFt[i]));
    return {
      origin, axis, length: Math.max(0.05, length), fovDeg,
      key: JSON.stringify([originFt, saved.aim, fovDeg]),
      meta: { device: marker.device_id, length_ft: lengthFt, fov_deg: saved.fov_deg },
    };
  }
  const room = layout.rooms?.find(r => r.building === marker.building && r.room === marker.room);
  let centre = null;
  if (room?.polygon_world?.length) centre = room.polygon_world.reduce((s, p) => [s[0] + p[0] / room.polygon_world.length, s[1] + p[1] / room.polygon_world.length], [0, 0]);
  if (!centre) {
    const planRoom = building?.rooms?.find(r => r.id === marker.room);
    if (planRoom?.polygon?.length) centre = lotPoint(building, [...planRoom.polygon.reduce((s, p) => s.map((v, i) => v + p[i] / planRoom.polygon.length), [0, 0]), 0], plan);
  }
  const house = building ? buildingCentre(building, plan) : [0, 0];
  const direction = cameraDirection(marker, centre, house), length = 25 * FT;
  const axis = new THREE.Vector3(direction[0], 0, -direction[1]);
  if (axis.lengthSq() > 1e-8) axis.normalize(); else axis.set(0, 0, -1);
  const fovDeg = Number.isFinite(marker.fov_deg) ? marker.fov_deg : FALLBACK_FOV_DEG;
  return {
    origin, axis, length, fovDeg,
    key: JSON.stringify([originFt, direction, 25, fovDeg]),
    meta: { device: marker.device_id, direction, length_ft: 25, fov_deg: fovDeg },
  };
}

function singleConeBox(spec) {
  const halfAngle = Math.max(10, Math.min(160, Number.isFinite(spec.fovDeg) ? spec.fovDeg : 90)) * Math.PI / 360;
  const dir = spec.axis.clone().normalize();
  const refUp = Math.abs(dir.y) < 0.95 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
  const u = new THREE.Vector3().crossVectors(dir, refUp).normalize();
  const v = new THREE.Vector3().crossVectors(dir, u).normalize();
  const box = new THREE.Box3().expandByPoint(spec.origin);
  box.expandByPoint(spec.origin.clone().addScaledVector(dir, spec.length));
  const c = Math.cos(halfAngle), s = Math.sin(halfAngle);
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2;
    const p = spec.origin.clone()
      .addScaledVector(dir, spec.length * c)
      .addScaledVector(u, spec.length * s * Math.cos(a))
      .addScaledVector(v, spec.length * s * Math.sin(a));
    box.expandByPoint(p);
  }
  box.expandByScalar(0.5);
  return box;
}

function coneBounds(specs) {
  return specs.map(singleConeBox);
}

export function mountSecurity({view, live, overlays = view.scene}) {
  const root = new THREE.Group(); root.userData.twinMode = 'security'; overlays.add(root);
  const emphasis = [], cones = [], layout = live.layout();
  const coneMaterials = createConeMaterials();
  const events = new AbortController();
  let occluder = null, occluderBox = null, occluderBuildMs = 0, rebuildCount = 0;

  for (const marker of layout.markers) {
    // Contacts may acquire their device class on the first live poll.
    if (!['lock', 'garage', 'camera', 'alarm', 'sensor'].includes(marker.kind) &&
        !/^(lock|camera|binary_sensor|alarm_control_panel|cover)\./.test(marker.entity_id)) continue;
    const building = view.plan.buildings?.find(b => b.id === marker.building);
    const base = buildingGround(view.plan, building);
    const at = new THREE.Vector3(marker.at[0] * FT, (marker.at[2] + base) * FT, -marker.at[1] * FT);
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(.42, 12, 8),
      new THREE.MeshBasicMaterial({color: '#ef4949', transparent: true, opacity: .75, depthTest: false, depthWrite: false, toneMapped: false}));
    mesh.position.copy(at); mesh.visible = false; mesh.renderOrder = 19;
    mesh.userData.securityAttention = marker.device_id; root.add(mesh); emphasis.push({marker, mesh});
    if (marker.kind !== 'camera' && !marker.entity_id.startsWith('camera.')) continue;
    const cone = new THREE.Group();
    cone.visible = false;
    cone.userData.noOcclusion = true;
    cone.userData.reflectionExclude = true;
    root.add(cone);
    cones.push({ marker, mesh: cone, key: '' });
  }

  function buildSceneOccluder(specs) {
    const t0 = performance.now();
    const boxes = coneBounds(specs);
    const meshes = collectStaticOccluders(view.scene, view);
    occluder = buildOccluderBVH(meshes, boxes);
    occluderBox = boxes;
    occluderBuildMs = performance.now() - t0;
  }

  function rebuildCones({ forceGeometry = false } = {}) {
    if (!cones.length) return;
    const currentLayout = live.layout();
    const specs = cones.map(entry => {
      const freshMarker = currentLayout.markers?.find(m => m.device_id === entry.marker.device_id) || entry.marker;
      entry.marker = freshMarker;
      return resolveConeSpec(freshMarker, currentLayout, view.plan);
    });
    const dirtyIndices = [];
    for (let i = 0; i < cones.length; i++) {
      if (forceGeometry || cones[i].key !== specs[i].key) dirtyIndices.push(i);
    }
    if (!dirtyIndices.length) return;
    const neededBoxes = coneBounds(specs);
    const outsideBox = !occluderBox || neededBoxes.some(b => !occluderBox.some(ob => ob.containsBox(b)));
    if (forceGeometry || !occluder || outsideBox) buildSceneOccluder(specs);
    rebuildCount++;
    for (const i of dirtyIndices) {
      const entry = cones[i], spec = specs[i];
      const built = buildOccludedCone({
        origin: spec.origin, axis: spec.axis, length: spec.length, fovDeg: spec.fovDeg,
        occluder, materials: coneMaterials, target: entry.mesh,
      });
      entry.key = spec.key;
      entry.mesh.userData.cameraCone = {
        ...spec.meta,
        rays: built.rays,
        triangles: built.triangles,
        hits: built.hits,
        buildMs: built.buildMs,
        occluderMs: occluderBuildMs,
        occluderTris: occluder?.triCount || 0,
        rebuilds: rebuildCount,
      };
    }
  }

  rebuildCones({ forceGeometry: true });

  const host = view.renderer3?.domElement?.parentElement;
  if (host?.addEventListener) {
    const onSceneRebuild = () => rebuildCones({ forceGeometry: true });
    host.addEventListener('twinrebuilt', onSceneRebuild, { signal: events.signal });
    host.addEventListener('twinyardrebuilt', onSceneRebuild, { signal: events.signal });
  }

  return {warmObjects: () => [...emphasis, ...cones].map(r => r.mesh),
    rebuild: () => rebuildCones({ forceGeometry: true }),
    update(mode) {
      rebuildCones({ forceGeometry: false });
      const on = modeShows(mode, 'security');
      for (const {marker, mesh} of emphasis) mesh.visible = on && !live.stale() && securityAttention(marker, live.state(marker.entity_id));
      for (const {mesh} of cones) mesh.visible = on;
    },
    legend() {
      const currentLayout = live.layout();
      const alarms = Object.entries(live.peek()).filter(([id]) => id.startsWith('alarm_control_panel.'));
      return 'Red · Open / unlocked   |   Camera view' + (cones.some(r => r.marker.camera_view || currentLayout.camera_views?.[r.marker.entity_id]) ? '' : ' · 25 ft') + alarms.map(([id, s]) => `   |   ${s.attributes?.friendly_name || id}: ${live.stale() ? 'unavailable' : s.state.replaceAll('_', ' ')}`).join('');
    },
    stop() {
      events.abort();
      root.removeFromParent();
      root.traverse(o => {
        o.geometry?.dispose();
        if (o.material && o.material !== coneMaterials.rim && o.material !== coneMaterials.fill) o.material.dispose();
      });
      coneMaterials.rim.dispose();
      coneMaterials.fill.dispose();
      occluder = null; occluderBox = null;
    }};
}
export function registerSecurity(registerMode) {
  registerMode({id: 'security', label: 'Security', foreground: securityItem, mount: mountSecurity});
}
