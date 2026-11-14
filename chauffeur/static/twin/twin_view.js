import { roomFloor, openingFloor } from './twin_floors.js';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { buildTwin, FT, PICK_LAYER, polygon, mergeStatic, contains, stairHoles } from './twin_generator.js';
import { span as editSpan } from './edit_timing.js';
import { heightAt } from './twin_roof.js';
import { groundAt, buildingGround } from './twin_ground.js';
import { buildYard } from './twin_yard.js';
import { base, loadSky, disposeObject } from './twin_library.js';
import { TIERS, pickTier, rendererName } from './twin_tiers.js';
import { hostPoint } from './twin_hosts.js';
import { keepLive } from './live/live.js';
import { mountGlance } from './live/glance.js';
import { mountIdle } from './live/idle.js';
import { mountGlanceSettings } from './live/glance_settings.js';
import { mountEnergySettings } from './live/energy_settings.js';
import { mountBake } from './bake/runtime.js';
import { sunPosition, moonPosition, moonIllumination } from './sky/ephemeris.js';
import { lookAt, modelDirection, previewDate, resolveSite } from './sky/look.js';
import { createUnlit } from './unlit.js';
import { createViewing } from './viewing.js';
import { createLevels } from './levels.js';

export async function mountTwin(el, { plan, kit, tier, preserveCamera = false, round = null, bake = true, site = {} } = {}) {
  // Ruling B15: only the 3D house view bakes lights. The editor's scene is the house
  // mid-edit (a focused floor, faded floors, editable geometry), so it never bakes.
  const editor = !!el.closest?.('.editor-shell');
  const bakes = bake && !editor;
  const probe = document.createElement('canvas').getContext('webgl2');
  if (!probe) throw new Error('This screen needs WebGL 2 to show the house.');
  tier = new URLSearchParams(location.search).get('tier') || tier;
  if (!TIERS[tier]) tier = pickTier(new URLSearchParams(location.search), probe);
  probe.getExtension('WEBGL_lose_context')?.loseContext();
  const settings = TIERS[tier];
  const renderer3 = new THREE.WebGLRenderer({ antialias: settings.antialias });
  renderer3.setPixelRatio(settings.pixelRatio);
  renderer3.shadowMap.enabled = settings.shadows;
  renderer3.shadowMap.type = THREE.PCFShadowMap;
  renderer3.toneMapping = THREE.ACESFilmicToneMapping;
  renderer3.info.autoReset = false;
  renderer3.localClippingEnabled = !editor;
  el.appendChild(renderer3.domElement);
  const scene = new THREE.Scene(), perspective = new THREE.PerspectiveCamera(38, 1, 0.1, 1000);
  const orthographic = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 1000);
  let camera = perspective;
  const controls = new OrbitControls(camera, renderer3.domElement);
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.enableDamping = false;
  RectAreaLightUniformsLib.init();
  const SUN_INTENSITY = 3.0;
  const sun = new THREE.DirectionalLight('#fff0d4', SUN_INTENSITY);
  const moon = new THREE.DirectionalLight('#99b8ff', 0);
  sun.name = 'real-sun'; moon.name = 'real-moon';
  // Both lights remain in the program set. Only the sun casts a shadow.
  moon.castShadow = false;
  sun.castShadow = settings.shadows;
  sun.shadow.autoUpdate = false;
  if (settings.shadows) {
    sun.shadow.mapSize.set(4096, 4096);
    sun.shadow.bias = -0.0002; sun.shadow.normalBias = 0.025;
  }
  const ambient = new THREE.HemisphereLight('#d9e9ff', '#68764f', 1.8);
  scene.add(sun, sun.target, moon, moon.target, ambient);
  let yardGroup = null;
  // Even a missing optional sky has an environment: time changes only its
  // intensity, never the USE_ENVMAP shader key.
  const fallbackEnvironment = new THREE.DataTexture(new Uint8Array([185, 203, 215, 255, 185, 203, 215, 255]), 2, 1);
  fallbackEnvironment.mapping = THREE.EquirectangularReflectionMapping;
  fallbackEnvironment.needsUpdate = true;
  let twin = null, disposed = false, revision = 0, sky = null, environment = fallbackEnvironment, environmentTarget = null;
  scene.environment = environment;
  const state = { view: 'ext', time: editor ? 'day' : 'now', camera: 'front', unlit: false };
  const unlit = createUnlit();
  let viewing = null;
  let shadowAutoUpdate;
  let clock = null, previewIdle = null, timeTimer = null, timeLook = null, lastShadowUpdate = -Infinity;
  const clockNow = () => clock ? new Date(clock) : new Date();
  let liveLamps = false;
  let bounds = { x: 19, y: 11, span: 38 };
  let framed = false, cameraMoved = false;
  controls.addEventListener('start', () => { cameraMoved = true; });
  let lastStats = { drawCalls: 0, triangles: 0, tier, fps: 0 };
  let probeRun = null, fps = 0, fpsFrames = 0, fpsSince = performance.now();
  let visibleLevels = null, sheet = null, sheetSpec = null, sheetRevision = 0;
  const raycaster = new THREE.Raycaster(); raycaster.layers.set(PICK_LAYER);
  const visible = object => { for (let o = object; o; o = o.parent) if (!o.visible) return false; return true; };
  const faded = new Map();
  let editableLevel = null, selectionStyle = null;
  const selectedMaterials = new Map(), selectionMaterials = new Set(), selectionLines = [];
  function restoreSelection() {
    unlit.restore();
    for (const line of selectionLines) { line.removeFromParent(); line.geometry.dispose(); line.material.dispose(); }
    selectionLines.length = 0;
    for (const [object, material] of selectedMaterials) object.material = material;
    selectedMaterials.clear();
    selectionMaterials.forEach(material => material.dispose()); selectionMaterials.clear();
  }
  function paintSelection() {
    restoreSelection();
    if (!twin || !selectionStyle) {
      if (state.unlit) unlit.apply(twin?.root);
      return;
    }
    const { selected, hover, room } = selectionStyle;
    const allowed = new Set(room?.allowed || []), walls = new Set(room?.walls || []);
    const style = getComputedStyle(el.closest('.editor-shell') || el);
    const accent = new THREE.Color(style.getPropertyValue('--editor-accent').trim() || '#52ccff');
    const wallTint = new THREE.Color(style.getPropertyValue('--editor-room-wall').trim() || '#9b7cdb');
    const styled = new Set();
    for (const [key, objects] of twin.pieces) {
      const data = twin.pieceBounds.get(key)?.data;
      if (!data) continue;
      const inRoom = room && data.buildingId === room.building && allowed.has(data.pieceId);
      const ghost = room && !inRoom;
      const tint = inRoom ? data.pieceId === room.id ? accent : walls.has(data.pieceId) ? wallTint : null
        : !room && selected && data.buildingId === selected.building && (data.pieceId === selected.id
          || selected.kind === 'building' || selected.kind === 'level' && objects.some(o => {
            for (let p = o; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey === `${selected.building}:${selected.id}`;
            return false;
          })) ? accent : null;
      if (!ghost && !tint) continue;
      for (const object of objects) {
        if (styled.has(object) || !object.material) continue;
        styled.add(object); selectedMaterials.set(object, object.material);
        const clone = material => {
          const next = material.clone(); selectionMaterials.add(next);
          if (ghost) { next.opacity = 0.25; next.transparent = true; next.depthWrite = false; }
          else next.color?.lerp(tint, 0.32);
          return next;
        };
        object.material = Array.isArray(object.material) ? object.material.map(clone) : clone(object.material);
      }
    }
    if (room) twin.groups.site.traverse(object => {
      if (!object.material || selectedMaterials.has(object) || object.layers.isEnabled(PICK_LAYER)) return;
      selectedMaterials.set(object, object.material);
      const clone = material => {
        const next = material.clone(); next.opacity = .25; next.transparent = true; next.depthWrite = false;
        selectionMaterials.add(next); return next;
      };
      object.material = Array.isArray(object.material) ? object.material.map(clone) : clone(object.material);
    });
    outline(selected, false); outline(hover, true);
    render();
  }
  function outline(pick, isHover) {
    if (!pick) return;
    const accent = new THREE.Color(getComputedStyle(el.closest('.editor-shell') || el).getPropertyValue('--editor-accent').trim() || '#52ccff');
    const yard = !pick.building && plan.site?.yard_rooms?.find(r => r.id === pick.id);
    if (yard) {
      const geometry = new THREE.BufferGeometry().setFromPoints([...yard.polygon, yard.polygon[0]].map(p =>
        new THREE.Vector3(p[0], groundAt(plan, ...p) + .06, -p[1])));
      const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: isHover ? .4 : .65, depthTest: false }));
      line.userData.isHover = isHover; line.renderOrder = 10; twin.root.add(line); selectionLines.push(line); return;
    }
    const keys = [...twin.pieceBounds].filter(([, { data }]) => data.buildingId === pick.building
      && (data.pieceId === pick.id || pick.kind === 'building' || pick.kind === 'level'
        && plan.buildings.find(b => b.id === pick.building)?.levels.some(l => l.id === pick.id)
        && twin.pickObjects.get(`${data.buildingId}:${data.pieceId}`)?.parent?.userData.levelKey === `${pick.building}:${pick.id}`));
    for (const [key] of keys) {
      const proxy = twin.pickObjects.get(key); if (!proxy) continue;
      const material = new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: isHover ? .65 : 1, depthTest: false });
      let geometry;
      const b = plan.buildings.find(b => b.id === pick.building), r = b?.rooms?.find(r => r.id === pick.id);
      if (r && pick.kind === 'room') {
        const z = roomFloor(b.levels.find(l => l.id === r.level), r) + .04;
        geometry = new THREE.BufferGeometry().setFromPoints([...r.polygon, r.polygon[0]].map(p => new THREE.Vector3(p[0], z, -p[1])));
      } else geometry = new THREE.EdgesGeometry(proxy.geometry);
      const line = r && pick.kind === 'room' ? new THREE.Line(geometry, material) : new THREE.LineSegments(geometry, material);
      line.userData.selectionKey = key;
      line.userData.isHover = isHover;
      line.userData.roomOutline = !!r && pick.kind === 'room';
      line.renderOrder = isHover ? 11 : 10; proxy.parent.add(line); selectionLines.push(line);
    }
  }
  function paintHover() {
    for (let i = selectionLines.length - 1; i >= 0; i--) {
      const line = selectionLines[i];
      if (!line.userData.isHover) continue;
      line.removeFromParent(); line.geometry.dispose(); line.material.dispose(); selectionLines.splice(i, 1);
    }
    if (twin) outline(selectionStyle?.hover, true);
    render();
  }
  function restoreFloors() {
    unlit.restore();
    for (const [object, material] of faded) {
      [].concat(object.material).forEach(m => m.dispose()); object.material = material;
    }
    faded.clear();
  }
  function floorFrame(key) {
    const building = plan.buildings.find(b => b.levels.some(l => `${b.id}:${l.id}` === key));
    const level = building?.levels.find(l => `${building.id}:${l.id}` === key);
    return building && { building, level, elevation: buildingGround(plan, building) + (building.base || 0) + level.elevation };
  }
  // The selected room on this floor, else the floor's walls, in lot feet.
  function floorFocus(frame) {
    const room = selectionStyle?.room;
    const focused = room?.building === frame.building.id && room.level === frame.level.id
      ? frame.building.rooms.find(r => r.id === room.id)?.polygon : null;
    const points = focused || frame.building.walls.filter(w => w.level === frame.level.id).flatMap(w => [w.from, w.to]);
    const angle = (frame.building.rotation || 0) * Math.PI / 180;
    const world = points.map(([x, y]) => [Math.cos(angle) * x - Math.sin(angle) * y + (frame.building.position?.[0] || 0),
      Math.sin(angle) * x + Math.cos(angle) * y + (frame.building.position?.[1] || 0)]);
    const xs = world.map(p => p[0]), ys = world.map(p => p[1]);
    return world.length ? { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2,
      span: Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) } : bounds;
  }
  // Optional height is in feet above the level, using the same live camera
  // and building transform as the floor point.
  function projectFloor(x, y, key, height = 0) {
    const frame = floorFrame(key); if (!frame) return null;
    const b = frame.building, a = (b.rotation || 0) * Math.PI / 180;
    const wx = Math.cos(a) * x - Math.sin(a) * y + (b.position?.[0] || 0);
    const wy = Math.sin(a) * x + Math.cos(a) * y + (b.position?.[1] || 0);
    camera.updateMatrixWorld(true);
    const p = new THREE.Vector3(wx * FT, (frame.elevation + height) * FT, -wy * FT).project(camera);
    const r = renderer3.domElement.getBoundingClientRect();
    return [r.left + (p.x + 1) * r.width / 2, r.top + (1 - p.y) * r.height / 2];
  }
  function pieceKey(id, buildingId) {
    if (!twin) return null;
    if (buildingId !== undefined) {
      const key = `${buildingId}:${id}`;
      return twin.pieces.has(key) ? key : null;
    }
    const matches = [...twin.pieceBounds].filter(([, record]) => record.data.pieceId === id);
    return matches.length === 1 ? matches[0][0] : null;
  }
  function pieceBox(id, buildingId) {
    if (!twin) return null;
    twin.root.updateMatrixWorld(true);
    const bounds = twin.pieceBounds.get(pieceKey(id, buildingId));
    return bounds ? bounds.box.clone().applyMatrix4(bounds.group.matrixWorld) : null;
  }
  function clearSheet() {
    ++sheetRevision;
    if (sheet?.object) { sheet.object.removeFromParent(); disposeObject(sheet.object); }
    sheet = null;
  }
  function attachSheet() {
    if (!sheet?.object) return;
    sheet.object.removeFromParent();
    const spec = sheetSpec, building = plan.buildings.find(b => b.id === spec.buildingId);
    const level = building?.levels.find(l => l.id === spec.levelId);
    const parent = twin?.groups.levels[`${spec.buildingId}:${spec.levelId}`];
    if (!level || !parent) return;
    const position = building.position || [0, 0];
    sheet.elevationFt = buildingGround(plan, building) + (building.base || 0) + level.elevation;
    sheet.object.position.set(position[0], sheet.elevationFt, -position[1]);
    sheet.object.rotation.y = (building.rotation || 0) * Math.PI / 180;
    parent.add(sheet.object);
  }
  const editFrames = new Set();
  function render() {
    if (disposed) return;
    viewing?.update(performance.now());
    view.levels?.draw();
    view.live?.draw();
    view.cars?.draw();
    twin?.updateGhosts();
    if (state.unlit) {
      unlit.apply(twin?.root);
      // Skip the entire shadow pass, including an invalidation from a rebuild.
      renderer3.shadowMap.needsUpdate = false; sun.shadow.needsUpdate = false;
    }
    renderer3.info.reset();
    renderer3.render(scene, camera);
    lastStats = { drawCalls: renderer3.info.render.calls, triangles: renderer3.info.render.triangles, tier, fps };
    if (editFrames.size) {
      let meshes = 0;
      twin?.root.traverse(object => { if (object.isMesh) ++meshes; });
      const stats = { meshes, draw_calls: renderer3.info.render.calls, triangles: renderer3.info.render.triangles };
      const waiting = [...editFrames]; editFrames.clear();
      requestAnimationFrame(() => waiting.forEach(resolve => resolve(stats)));
    }
  }
  function resize() {
    const width = Math.max(1, el.clientWidth), height = Math.max(1, el.clientHeight);
    renderer3.setSize(width, height);
    perspective.aspect = width / height; perspective.updateProjectionMatrix();
    orthographic.left = -orthographic.top * width / height; orthographic.right = -orthographic.left;
    orthographic.updateProjectionMatrix();
    render();
  }
  const observer = new ResizeObserver(resize); observer.observe(el);
  const view = {
    ready: false, scene, renderer: rendererName(renderer3.getContext()), renderer3, camera, controls, state, tier,
    groups: null, roomLights: [], plan, round,
    viewingState() {
      return viewing?.snapshot() || {selected: state.view, pinned: state.view === 'ext' ? null : state.view, channels: []};
    },
    // Visualizations hide with the geometry they are tied to (user, 2026-11-13): a floor or a
    // building's roof counts as shown while it is more than half faded in.
    levelShown(key) { return !viewing || viewing.levelAlpha(key) > .5; },
    roofShown(id) { return !viewing || viewing.roofAlpha(id) > .5; },
    get site() { return site; },
    get roofSurfaces() { return twin?.roofSurfaces; },
    render,
    prepareViewingMaterial(source, material) { viewing?.adopt(source, material); },
    cameraKind() { return camera.isOrthographicCamera ? 'orthographic-top' : 'perspective'; },
    saveView() {
      return { camera, position: camera.position.clone(), quaternion: camera.quaternion.clone(), target: controls.target.clone(),
        zoom: camera.zoom, state: { ...state }, navigation: view.levels?.save(), levels: visibleLevels && [...visibleLevels],
        faint: [...new Set([...faded.keys()].map(o => { for (let p = o; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey; }).filter(Boolean))] };
    },
    restoreView(saved) {
      camera = saved.camera; view.camera = camera; controls.object = camera; controls.enableRotate = !camera.isOrthographicCamera;
      view.cancelCameraMotion?.();
      if (saved.navigation && view.levels) view.levels.restore(saved.navigation);
      else { view.setView(saved.state.view); view.showLevels(saved.levels, { faint: saved.faint }); }
      Object.assign(state, saved.state); camera.position.copy(saved.position); controls.target.copy(saved.target);
      // Restoring a camera is a framing change, not an outward zoom gesture.
      viewing?.rebasePin();
      camera.zoom = saved.zoom; controls.update(); camera.quaternion.copy(saved.quaternion); camera.updateProjectionMatrix(); render();
    },
    screenOfFloor: projectFloor,
    setSelection(value) {
      const sameMaterials = selectionStyle && JSON.stringify([selectionStyle.selected, selectionStyle.room])
        === JSON.stringify([value.selected, value.room]);
      selectionStyle = value;
      const focus = value.room || (value.selected?.kind === 'level' ? { building: value.selected.building, level: value.selected.id } : null);
      const key = focus ? `${focus.building}:${focus.level}` : null;
      if (key !== editableLevel) {
        editableLevel = key;
        view.rebuild(plan, { preserveYard: true }).catch(error => el.dispatchEvent(new CustomEvent('twinerror', { detail: error })));
      } else if (sameMaterials) paintHover();
      else paintSelection();
      return value.room ? [...(twin?.pieceBounds.values() || [])].filter(({ data }) =>
        data.buildingId !== value.room.building || !value.room.allowed.includes(data.pieceId)).length : 0;
    },
    async setEditableLevel(key) {
      if (key === editableLevel) return;
      editableLevel = key; await view.rebuild(plan, { preserveYard: true });
    },
    floorAt(clientX, clientY, key, height = 0) {
      const frame = floorFrame(key); if (!frame) return null;
      const r = renderer3.domElement.getBoundingClientRect();
      camera.updateMatrixWorld(true);
      raycaster.setFromCamera(new THREE.Vector2((clientX - r.left) / r.width * 2 - 1, 1 - (clientY - r.top) / r.height * 2), camera);
      const point = raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -(frame.elevation + height) * FT), new THREE.Vector3());
      if (!point) return null;
      const b = frame.building, a = -(b.rotation || 0) * Math.PI / 180;
      const x = point.x / FT - (b.position?.[0] || 0), y = -point.z / FT - (b.position?.[1] || 0);
      return [Math.cos(a) * x - Math.sin(a) * y, Math.sin(a) * x + Math.cos(a) * y];
    },
    // The Top camera in perspective, straight above the focused room or floor.
    setTopCamera(key) {
      view.setCamera('top');
      const frame = floorFrame(key); if (!frame) return;
      const focus = floorFocus(frame), height = Math.max(20, focus.span * 1.6);
      camera.position.set(focus.x * FT, (frame.elevation + height) * FT, -(focus.y - 0.01) * FT);
      controls.target.set(focus.x * FT, frame.elevation * FT, -focus.y * FT); controls.update(); render();
    },
    setPlanCamera(key) {
      const frame = floorFrame(key); if (!frame) return;
      const focus = floorFocus(frame);
      camera = orthographic; view.camera = camera; controls.object = camera;
      state.camera = 'top';
      orthographic.top = Math.max(20, focus.span * 0.72) * FT; orthographic.bottom = -orthographic.top;
      orthographic.zoom = 1;
      camera.position.set(focus.x * FT, (frame.elevation + 250) * FT, -focus.y * FT);
      controls.target.set(focus.x * FT, frame.elevation * FT, -focus.y * FT);
      controls.enableRotate = false; controls.update(); resize();
    },
    // `skip` names piece kinds the ray passes through (the opening tools look
    // through a porch's or a room's pick box for the wall behind it).
    pick(clientX, clientY, { skip = [] } = {}) {
      if (!twin) return null;
      const rect = renderer3.domElement.getBoundingClientRect();
      if (clientX < rect.left || clientX >= rect.right || clientY < rect.top || clientY >= rect.bottom) return null;
      twin.root.updateMatrixWorld(true); camera.updateMatrixWorld(true);
      raycaster.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, 1 - (clientY - rect.top) / rect.height * 2), camera);
      // The plan camera reaches pieces beneath the roof, as a floor editor
      // must; perspective views can select the roof itself.
      const candidates = [...twin.pickObjects.values()].filter(o => {
        const room = selectionStyle?.room, data = o.userData;
        if (room && (data.buildingId !== room.building || !room.allowed.includes(data.pieceId))) return false;
        if (!visible(o) || viewing?.faded(o) || (state.camera === 'top' && o.userData.kind === 'roof')) return false;
        if (camera.isOrthographicCamera && state.view !== 'ext') {
          for (let p = o; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey === state.view;
        }
        return true;
      });
      const hits = raycaster.intersectObjects(candidates, false).filter(hit => {
        const { kind, buildingId, pieceId } = hit.object.userData;
        if (skip.includes(kind)) return false;
        if (viewing && hit.point.y > viewing.cutAt(hit.object) + .02) return false;
        if (kind !== 'room') return true;
        const room = plan.buildings.find(b => b.id === buildingId)?.rooms?.find(r => r.id === pieceId);
        if (!room?.polygon?.length) return true;
        // Room proxies enclose the slab. Reject the empty corners of concave
        // rooms so a ray cannot select their floor through a neighbour.
        const point = hit.object.parent.worldToLocal(hit.point.clone()), x = point.x, y = -point.z;
        return contains(room.polygon, [x, y]);
      });
      let hit = state.camera === 'top' ? hits.find(h => h.object.userData.kind === 'wall') || hits[0] : hits[0];
      if (!hit) return null;
      const surface = hit.object.userData;
      const building = plan.buildings.find(b => b.id === surface.buildingId);
      // A proxy surrounds the wall/slab, so it can be slightly nearer than a
      // switch, window or item attached to that surface. Prefer its hosted hit.
      hit = hits.find(h => {
        const data = h.object.userData;
        if (data.buildingId !== surface.buildingId || Math.abs(h.distance - hit.distance) >= FT) return false;
        const list = { opening: 'openings', anchor: 'anchors', light: 'anchors', item: 'items', fixture: 'items' }[data.kind];
        const piece = list && building?.[list]?.find(p => p.id === data.pieceId);
        if (!piece) return false;
        return surface.kind === 'wall' && (piece.wall || piece.host?.wall) === surface.pieceId
          || surface.kind === 'room' && (piece.host?.floor === surface.pieceId || piece.host?.ceiling === surface.pieceId)
          || surface.kind === 'roof' && piece.host?.roof === surface.pieceId;
      }) || hit;
      const { pieceId, kind, buildingId } = hit.object.userData;
      let level = null;
      for (let p = hit.object; p; p = p.parent) if (p.userData.levelKey) { level = p.userData.levelKey.slice(buildingId.length + 1); break; }
      return { kind, id: pieceId, building: buildingId, level, pieceId, buildingId, point: hit.point.toArray() };
    },
    worldBox(id, buildingId) {
      const box = pieceBox(id, buildingId); if (!box) return null;
      return { min: [box.min.x / FT, -box.max.z / FT, box.min.y / FT], max: [box.max.x / FT, -box.min.z / FT, box.max.y / FT] };
    },
    showLevels(keys, { faint = [] } = {}) {
      if (!twin) return;
      restoreSelection();
      restoreFloors();
      visibleLevels = keys === null ? null : new Set(keys);
      for (const [key, group] of Object.entries(twin.groups.levels)) group.visible = !visibleLevels || visibleLevels.has(key);
      for (const key of faint) twin.groups.levels[key]?.traverse(object => {
        if (!object.material || object.layers.isEnabled(PICK_LAYER)) return;
        faded.set(object, object.material);
        const clone = m => { const next = m.clone(); next.transparent = true; next.opacity = 0.18; next.depthWrite = false; return next; };
        object.material = Array.isArray(object.material) ? object.material.map(clone) : clone(object.material);
      });
      const buildings = new Set(Object.values(twin.groups.levels).filter(g => g.visible).map(g => g.userData.buildingId));
      for (const domain of ['roof', 'gableFull', 'gableCut']) for (const group of twin.groups[domain].children) group.visible = buildings.has(group.userData.buildingId);
      sun.shadow.needsUpdate = true;
      applyLights(); paintSelection(); render();
    },
    setSheet(spec) {
      clearSheet(); sheetSpec = spec;
      if (!spec || !twin || disposed) return;
      const building = plan.buildings.find(b => b.id === spec.buildingId);
      const level = building?.levels.find(l => l.id === spec.levelId);
      const parent = twin.groups.levels[`${spec.buildingId}:${spec.levelId}`];
      if (!level || !parent || !(spec.reg?.scale > 0)) return;
      if (!spec.masterSize) console.warn('Drawing master size is unavailable; using the displayed image size for this sheet.');
      const version = sheetRevision;
      const elevation = buildingGround(plan, building) + (building.base || 0) + level.elevation;
      sheet = { ready: false, object: null, elevationFt: elevation,
        widthFt: (spec.masterSize?.[0] || 0) * spec.reg.scale, depthFt: (spec.masterSize?.[1] || 0) * spec.reg.scale };
      new THREE.TextureLoader().load(spec.url, texture => {
        if (disposed || version !== sheetRevision) { texture.dispose(); return; }
        const width = texture.image.naturalWidth || texture.image.width, height = texture.image.naturalHeight || texture.image.height;
        const master = spec.masterSize || [width, height], ratio = [master[0] / width, master[1] / height];
        const reg = spec.reg, angle = (reg.angle || 0) * Math.PI / 180, c = Math.cos(angle), s = Math.sin(angle);
        const at = (x, y) => {
          const u = (x * ratio[0] - reg.origin_px[0]) * reg.scale, v = (reg.origin_px[1] - y * ratio[1]) * reg.scale;
          return [c * u - s * v + reg.offset[0], 0.015, -(s * u + c * v + reg.offset[1])];
        };
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute([at(0, height), at(width, height), at(width, 0), at(0, 0)].flat(), 3));
        geometry.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
        geometry.setIndex([0, 1, 2, 0, 2, 3]); geometry.computeVertexNormals();
        texture.colorSpace = THREE.SRGBColorSpace;
        const material = new THREE.MeshBasicMaterial({ name: 'sheet', map: texture, transparent: true, opacity: spec.opacity ?? 0.6, depthWrite: false, side: THREE.DoubleSide });
        const object = new THREE.Mesh(geometry, material);
        Object.assign(object.userData, { pieceId: `${building.id}:sheet:${level.id}`, kind: 'sheet', buildingId: building.id });
        object.renderOrder = 1;
        sheet = { ready: true, object, elevationFt: elevation, widthFt: master[0] * reg.scale, depthFt: master[1] * reg.scale }; attachSheet(); render();
      }, undefined, () => { if (version === sheetRevision) { sheet = null; render(); } });
    },
    setView(id) {
      // P0 callers may still name a level without a building. Only resolve an
      // unambiguous match; all scene state and buttons use namespaced keys.
      if (twin && id !== 'ext' && !twin.groups.levels[id]) {
        const matches = Object.keys(twin.groups.levels).filter(key => key.endsWith(':' + id));
        if (matches.length === 1) id = matches[0];
      }
      if (!twin || (id !== 'ext' && !twin.groups.levels[id])) return;
      if (view.levels) {
        if (id === 'ext') view.levels.go({level: 'house'}, {immediate: true});
        else { const frame = floorFrame(id); view.levels.go({building: frame.building.id, floor: frame.level.id}, {immediate: true}); }
        return;
      }
      if (viewing) {
        if (id === 'ext') { viewing.select(id); view.setCamera('front'); }
        else {
          const frame = floorFrame(id), focus = floorFocus(frame);
          // Keep the orbit direction, centring and sizing it on this floor.
          const offset = camera.position.clone().sub(controls.target).normalize();
          controls.target.set(focus.x * FT, frame.elevation * FT, -focus.y * FT);
          camera.position.copy(controls.target).addScaledVector(offset, Math.max(20, focus.span * 1.4) * FT);
          viewing.select(id);
          controls.update();
        }
        render(); return;
      }
      restoreSelection(); restoreFloors();
      state.view = id;
      visibleLevels = null;
      const ext = id === 'ext', ids = Object.keys(twin.groups.levels).sort((a, b) => twin.levelElevations[a] - twin.levelElevations[b]);
      const buildingId = ext ? null : twin.groups.levels[id].userData.buildingId;
      const isFirst = id === ids.find(key => twin.groups.levels[key].userData.buildingId === buildingId);
      twin.groups.roof.visible = twin.groups.gableFull.visible = ext;
      twin.groups.gableCut.visible = !ext && !isFirst;
      for (const level of ids) twin.groups.levels[level].visible = ext || (twin.groups.levels[level].userData.buildingId === buildingId && twin.levelElevations[level] <= twin.levelElevations[id]);
      for (const domain of ['roof', 'gableFull', 'gableCut']) for (const group of twin.groups[domain].children) group.visible = ext || group.userData.buildingId === buildingId;
      sun.shadow.needsUpdate = true;
      applyLights(); paintSelection(); render();
    },
    setTime(time) {
      if (!['now', 'day', 'night'].includes(time)) return;
      state.time = time;
      resetPreviewIdle(); updateTime();
    },
    setUnlit(on) {
      on = !!on;
      if (state.unlit === on) return;
      unlit.restore();
      state.unlit = on;
      if (on) {
        shadowAutoUpdate = renderer3.shadowMap.autoUpdate;
        renderer3.shadowMap.autoUpdate = false;
        view.bake?.stop();
      } else {
        renderer3.shadowMap.autoUpdate = shadowAutoUpdate;
        sun.shadow.needsUpdate = true;
      }
      updateTime();
      if (!on && twin) startBake();
    },
    setSite(next) {
      if (JSON.stringify(site) === JSON.stringify(next || {})) return;
      site = next || {}; updateTime();
    },
    setLiveLamps(on) {
      // Drawn from the view's own state both ways, never restored from a copy:
      // a floor change, a late sky, a rebuild or Day/Night while in Lights mode
      // all show on leaving it.
      if (liveLamps === !!on) return;
      liveLamps = !!on;
      applyLights(); render();
    },
    setCamera(name) {
      if (!['front', 'back', 'orbit', 'porch', 'rear', 'top'].includes(name)) return;
      camera = perspective; view.camera = camera; controls.object = camera; controls.enableRotate = true;
      state.camera = name;
      const { x, y, span } = bounds, k = span / 38;
      const positions = { front: [x - 41 * k, 22 * k, y - 69 * k], porch: [x + 59 * k, 22 * k, y - 45 * k], rear: [x + 27 * k, 34 * k, y + 57 * k], top: [x, 105 * k, y - 0.01] };
      const [cx, cy, cz] = positions[name === 'back' ? 'rear' : name === 'orbit' ? 'porch' : name];
      camera.position.set(cx * FT, cy * FT, -cz * FT);
      controls.target.set(x * FT, (name === 'top' ? 3 : 8) * FT, -y * FT);
      // A named camera is a framing change, not an outward zoom gesture.
      viewing?.rebasePin(); controls.update(); render();
    },
    // Look from one lot point at another (feet; z above the ground). The editor
    // opens this way (M3); later rebuilds keep the camera as it was left.
    aim(position, target) {
      camera = perspective; view.camera = camera; controls.object = camera; controls.enableRotate = true;
      cameraMoved = true;
      camera.position.set(position[0] * FT, position[2] * FT, -position[1] * FT);
      controls.target.set(target[0] * FT, target[2] * FT, -target[1] * FT); controls.update(); render();
    },
    async capture(names, width = 1280, height = 800) {
      if (disposed) throw new Error('This twin has been disposed.');
      width = Math.max(1, Math.floor(width)); height = Math.max(1, Math.floor(height));
      const previous = {
        camera,
        position: camera.position.clone(), quaternion: camera.quaternion.clone(), target: controls.target.clone(),
        aspect: camera.aspect, name: state.camera, target3: renderer3.getRenderTarget(),
        size: renderer3.getSize(new THREE.Vector2()), pixelRatio: renderer3.getPixelRatio(),
      };
      const out = [];
      try {
        // r187 only applies the screen's tone mapping/exposure on the canvas.
        // Render and read synchronously, before the drawing buffer is cleared.
        renderer3.setRenderTarget(null);
        renderer3.setPixelRatio(1); renderer3.setSize(width, height, false);
        for (const name of names) {
          view.setCamera(name);
          camera.aspect = width / height; camera.updateProjectionMatrix();
          render(); out.push(renderer3.domElement.toDataURL('image/png'));
        }
        return out;
      } finally {
        renderer3.setPixelRatio(previous.pixelRatio); renderer3.setSize(previous.size.x, previous.size.y, false);
        renderer3.setRenderTarget(previous.target3);
        camera = previous.camera; view.camera = camera; controls.object = camera; controls.enableRotate = !camera.isOrthographicCamera;
        camera.position.copy(previous.position); controls.target.copy(previous.target); controls.update();
        camera.quaternion.copy(previous.quaternion); camera.aspect = previous.aspect; camera.updateProjectionMatrix();
        state.camera = previous.name; render();
      }
    },
    stats() { return { ...lastStats }; },
    afterNextRender() { return new Promise(resolve => editFrames.add(resolve)); },
    async runProbe(seconds = 20) {
      if (disposed || !view.ready) throw new Error('The twin is not ready.');
      if (probeRun) throw new Error('A performance probe is already running.');
      if (!Number.isFinite(seconds) || seconds <= 0) throw new Error('Probe seconds must be a positive finite number.');
      const previous = {
        camera,
        view: state.view, name: state.camera, position: camera.position.clone(),
        quaternion: camera.quaternion.clone(), target: controls.target.clone(), enabled: controls.enabled,
      };
      try {
        controls.enabled = false;
        view.setView('ext'); view.setCamera('front');
        const offset = camera.position.clone().sub(controls.target);
        return await new Promise((resolve, reject) => {
          probeRun = {
            resolve, reject, start: performance.now(), previous: performance.now(),
            exterior: seconds * 1000, floor: Math.max(1, Math.min(5, seconds / 4)) * 1000,
            floorIds: Object.keys(twin.groups.levels)
              .sort((a, b) => twin.levelElevations[a] - twin.levelElevations[b]).slice(0, 2),
            angle: Math.atan2(offset.z, offset.x), radius: Math.hypot(offset.x, offset.z), height: offset.y,
            stage: 'ext', frames: 0, samples: [], drawCalls: 0, triangles: 0,
          };
        });
      } finally {
        controls.enabled = previous.enabled;
        if (!disposed) {
          view.setView(previous.view);
          camera = previous.camera; view.camera = camera; controls.object = camera; controls.enableRotate = !camera.isOrthographicCamera;
          camera.position.copy(previous.position); controls.target.copy(previous.target); controls.update();
          camera.quaternion.copy(previous.quaternion); state.camera = previous.name; render();
        }
      }
    },
    rebuildLevel(buildingId, levelId, flat, touched = null) {
      const key = `${buildingId}:${levelId}`, group = twin?.groups.levels[key];
      const before = plan.buildings.find(b => b.id === buildingId), after = flat.buildings.find(b => b.id === buildingId);
      if (!group || !before || !after || twin.editableLevel !== key) return;
      view.bake?.stop();
      // The focused level has per-piece meshes (R42). Rebuild its changed
      // buffers in place: no roof, yard, texture or optional-model work per frame.
      // Keep selection materials alive throughout a gesture. Replacing every
      // tinted/ghosted material per update churns the renderer's shader cache.
      const changedPieces = new Set();
      const wallsBefore = new Map(before.walls.map(w => [w.id, w]));
      const roomsBefore = new Map(before.rooms.map(r => [r.id, r]));
      const affected = (list, pieces) => touched ? pieces.filter(p => touched[list]?.includes(p.id)) : pieces;
      const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
      const direction = wall => {
        const x = wall.to[0] - wall.from[0], y = wall.to[1] - wall.from[1], length = Math.hypot(x, y);
        return { x: x / length, y: y / length, length };
      };
      const update = (id, deform, room = null) => {
        const piece = `${buildingId}:${id}`, record = twin.pieceBounds.get(piece);
        if (!record) return;
        changedPieces.add(piece);
        const objects = twin.pieces.get(piece) || [], changed = new Set();
        const proxy = twin.pickObjects.get(piece);
        const box = new THREE.Box3();
        for (const object of [...objects, proxy].filter(Boolean)) {
          if (changed.has(object.geometry)) continue;
          changed.add(object.geometry);
          let geometry = object.geometry;
          if (!geometry?.attributes.position) continue;
          if (room && object !== proxy && object.isMesh) {
            geometry.computeBoundingBox();
            const { min, max } = geometry.boundingBox;
            const level = after.levels.find(l => l.id === levelId);
            const holes = stairHoles(after, level).filter(h => h.every(p => contains(room.polygon, p)));
            object.geometry = polygon(room.polygon, min.y, max.y, holes);
            geometry.dispose(); geometry = object.geometry;
          } else {
            const positions = geometry.attributes.position;
            for (let i = 0; i < positions.count; i++) {
              const p = deform(positions.getX(i), -positions.getZ(i), positions.getY(i));
              positions.setXYZ(i, p[0], p[2], -p[1]);
            }
            positions.needsUpdate = true; geometry.computeVertexNormals();
          }
          geometry.computeBoundingBox(); geometry.computeBoundingSphere();
          if (object !== proxy) box.union(geometry.boundingBox);
        }
        if (!box.isEmpty()) {
          record.box.copy(box);
          if (room && proxy) {
            const size = box.getSize(new THREE.Vector3()), centre = box.getCenter(new THREE.Vector3());
            proxy.geometry.dispose(); proxy.geometry = new THREE.BoxGeometry(Math.max(.01, size.x), Math.max(.01, size.y), Math.max(.01, size.z)).translate(...centre.toArray());
          }
        }
      };
      for (const wall of affected('walls', after.walls).filter(w => w.level === levelId)) {
        const old = wallsBefore.get(wall.id);
        if (!old || same([old.from, old.to], [wall.from, wall.to])) continue;
        const a = direction(old), b = direction(wall);
        // Preserve the distances and widths of hosted holes while stretching
        // the solid run beyond them as an attached end moves.
        const fixed = Math.max(0, ...(before.openings || []).filter(o => o.wall === wall.id).map(o => o.at + o.width / 2));
        update(wall.id, (x, y, z) => {
          const dx = x - old.from[0], dy = y - old.from[1];
          const u = dx * a.x + dy * a.y, v = -dx * a.y + dy * a.x;
          const along = u <= fixed ? u : fixed + (u - fixed) * (b.length - fixed) / Math.max(.0001, a.length - fixed);
          return [wall.from[0] + along * b.x - v * b.y, wall.from[1] + along * b.y + v * b.x, z];
        });
      }
      for (const room of affected('rooms', after.rooms).filter(r => r.level === levelId)) {
        const old = roomsBefore.get(room.id);
        if (!old || same(old.polygon, room.polygon)) continue;
        update(room.id, (x, y, z) => [x, y, z], room);
      }
      for (const list of ['openings', 'anchors', 'items']) {
        const piecesBefore = new Map((before[list] || []).map(p => [p.id, p]));
        for (const piece of affected(list, after[list] || [])) {
          const old = piecesBefore.get(piece.id);
          if (!old) continue;
          const point = (building, p) => {
            if (p.host) return hostPoint(building, p.host, p.offset || 0);
            const wall = building.walls.find(w => w.id === p.wall);
            return wall ? hostPoint(building, { wall: wall.id, at: p.at, sill: p.sill }) : null;
          };
          try {
            const a = point(before, old), b = point(after, piece);
            const record = twin.pieceBounds.get(`${buildingId}:${piece.id}`);
            let parent = record?.group;
            while (parent && !parent.userData.levelKey) parent = parent.parent;
            const wallId = piece.host?.wall || piece.wall;
            const oldWall = wallsBefore.get(old.host?.wall || old.wall), wall = after.walls.find(w => w.id === wallId);
            const angle = list !== 'items' && oldWall && wall ? Math.atan2(wall.to[1] - wall.from[1], wall.to[0] - wall.from[0])
              - Math.atan2(oldWall.to[1] - oldWall.from[1], oldWall.to[0] - oldWall.from[0])
              + (old.host?.side && piece.host?.side && old.host.side !== piece.host.side ? Math.PI : 0) : 0;
            const resized = list === 'openings' && !same([old.width, old.sill, old.head], [piece.width, piece.sill, piece.head]);
            if (!a || !b || same(a, b) && !angle && !resized || parent?.userData.levelKey !== key) continue;
            const c = Math.cos(angle), s = Math.sin(angle);
            update(piece.id, (x, y, z) => {
              let dx = x - a[0], dy = y - a[1], dz = z - a[2];
              if (list === 'openings' && oldWall) {
                const axis = direction(oldWall), extra = (dx * axis.x + dy * axis.y) * (piece.width / old.width - 1);
                dx += axis.x * extra; dy += axis.y * extra;
                dz *= (piece.head - piece.sill) / (old.head - old.sill);
              }
              return [b[0] + dx * c - dy * s, b[1] + dx * s + dy * c, b[2] + dz];
            });
          } catch { /* Missing hosts keep their ghost geometry. */ }
        }
      }
      plan = flat; view.plan = flat;
      for (const line of selectionLines) {
        const key = line.userData.selectionKey;
        if (!changedPieces.has(key)) continue;
        const proxy = twin.pickObjects.get(key), record = twin.pieceBounds.get(key);
        if (!proxy) continue;
        line.geometry.dispose();
        const room = line.userData.roomOutline && after.rooms.find(r => r.id === record.data.pieceId);
        const z = roomFloor(after.levels.find(l => l.id === room?.level), room) + .04;
        line.geometry = room ? new THREE.BufferGeometry().setFromPoints([...room.polygon, room.polygon[0]]
          .map(p => new THREE.Vector3(p[0], z, -p[1]))) : new THREE.EdgesGeometry(proxy.geometry);
      }
      render();
      el.dispatchEvent(new CustomEvent('twinlevelrebuilt', { detail: { buildingId, levelId } }));
    },
    async rebuild(nextPlan, { preserveYard = false, timing = null } = {}) {
      const detail = timing?.detail;
      const stopBake = editSpan(detail, 'bake_stop');
      view.bake?.stop();
      stopBake();
      const version = ++revision; view.ready = false;
      const structureKey = p => JSON.stringify([p.materials, p.buildings?.map(b => ({ ...b, foundation: undefined, foundation_src: undefined, base: undefined }))]);
      const stopMaterials = editSpan(detail, 'materials');
      const reuseMaterials = twin && structureKey(plan) === structureKey(nextPlan) ? twin.materials : null;
      stopMaterials();
      const next = buildTwin(nextPlan, kit, tier, { showAnchors: !!view.showAnchors, editableLevel, viewing: !editor, reuseMaterials, timing });
      const yardMaterials = JSON.stringify(nextPlan.materials) === JSON.stringify(plan.materials) ? yardGroup?.userData.materials : null;
      const keepMaterials = new Set([...(yardMaterials?.values() || []), ...(reuseMaterials?.values() || [])]);
      next.editableLevel = editableLevel;
      const extras = new Map();
      try {
        // The generator's structural floors cover room polygons; unattached
        // ghost openings cannot go through its wall-hole builder. Keep those
        // saved pieces visible and identifiable while the house is incomplete.
        for (const building of nextPlan.buildings || []) {
          for (const [kind, pieces] of [['room', building.rooms || []], ['opening', building.openings || []]]) {
            for (const piece of pieces) {
              const key = `${building.id}:${piece.id}`;
              if (next.pieces.has(key)) continue;
              const level = building.levels.find(l => l.id === piece.level);
              const group = next.groups.levels[`${building.id}:${piece.level}`]?.children.find(g => g.userData.buildingId === building.id);
              if (!level || !group || (kind === 'opening' && !piece.position)) continue;
              if (!extras.has(group)) { const extra = new THREE.Group(); group.add(extra); extras.set(group, extra); }
              const renderGroup = extras.get(group);
              const ghost = piece.state === 'ghost', data = { pieceId: piece.id, buildingId: building.id, kind, ghost };
              const material = next.materials.get(ghost ? 'ghost#38bdf8' : 'floor');
              const objects = [];
              const add = geometry => {
                const mesh = new THREE.Mesh(geometry, material);
                Object.assign(mesh.userData, data, { pieceObjects: objects }); renderGroup.add(mesh); objects.push(mesh);
                if (ghost) {
                  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), next.materials.get('ghostEdges'));
                  edge.computeLineDistances(); Object.assign(edge.userData, data); renderGroup.add(edge); objects.push(edge);
                }
              };
              if (kind === 'room') {
                const holes = stairHoles(building, level).filter(h => h.every(p => contains(piece.polygon, p)));
                add(polygon(piece.polygon, roomFloor(level, piece) + .012, roomFloor(level, piece) + .012, holes));
              } else {
                const [x, y] = piece.position, height = piece.head - piece.sill;
                const wall = building.walls.find(w => w.id === piece.wall);
                const angle = wall ? Math.atan2(wall.to[1] - wall.from[1], wall.to[0] - wall.from[0]) : 0;
                add(new THREE.BoxGeometry(piece.width, height, .08).rotateY(angle)
                  .translate(x, level.elevation + (wall ? openingFloor(building, wall, piece.at).offset : 0) + piece.sill + height / 2, -y));
              }
              next.pieces.set(key, objects);
              const geometry = objects[0].geometry; geometry.computeBoundingBox();
              next.pieceBounds.set(key, { box: geometry.boundingBox.clone(), group, data });
              const proxy = new THREE.Mesh(geometry.clone(), next.materials.get('pick'));
              Object.assign(proxy.userData, data); proxy.layers.set(PICK_LAYER); group.add(proxy); next.pickObjects.set(key, proxy);
            }
          }
        }
        const stopBatch = editSpan(detail, 'batch');
        for (const [parent, group] of extras) mergeStatic(group, { perPiece: !!editableLevel && parent.userData.levelKey === editableLevel });
        stopBatch();
        if (!preserveYard || !yardGroup) {
          const stopYard = editSpan(detail, 'yard');
          const yard = await buildYard(nextPlan, kit, tier, { viewing: !editor, materials: yardMaterials }); next.groups.site.add(yard.group);
          stopYard();
          next.yardGroup = yard.group;
        }
        const stopAssets = editSpan(detail, 'assets');
        await next.ready;
        stopAssets();
      } catch (error) { release(next, keepMaterials); throw error; }
      if (disposed || version !== revision) { release(next, keepMaterials); return; }
      const levelsToRestore = visibleLevels && [...visibleLevels];
      const faintToRestore = [...new Set([...faded.keys()].map(o => {
        for (let p = o; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey;
        return null;
      }).filter(Boolean))];
      restoreSelection(); restoreFloors();
      // The underlay owns its image independently of the rebuilt geometry.
      // Detach before releasing the old scene, then place the same object.
      // Keep the old fade programs referenced until the next geometry has
      // adopted them. Ordinary terrain edits must not delete/recreate shaders.
      const stopDispose = editSpan(detail, 'dispose');
      const releaseViewing = viewing?.dispose({ deferMaterials: true }); viewing = null;
      sheet?.object?.removeFromParent();
      if (!next.yardGroup && yardGroup) {
        yardGroup.removeFromParent(); next.groups.site.add(yardGroup); next.yardGroup = yardGroup;
      }
      if (twin) { scene.remove(twin.root); release(twin, keepMaterials); }
      stopDispose();
      yardGroup = next.yardGroup;
      twin = next; plan = nextPlan; scene.add(twin.root);
      // Read-only legacy property access for P0 embeds, never enumerable scene
      // keys and never a resolution when two buildings share the level name.
      view.groups = { ...twin.groups, levels: new Proxy(twin.groups.levels, { get(target, key) {
        if (typeof key !== 'string' || key in target) return target[key];
        const matches = Object.keys(target).filter(id => id.endsWith(':' + key));
        return matches.length === 1 ? target[matches[0]] : undefined;
      } }) };
      view.roomLights = twin.roomLights; view.plan = plan;
      const points = (plan.buildings || []).flatMap(b => {
        const angle = (b.rotation || 0) * Math.PI / 180, c = Math.cos(angle), s = Math.sin(angle);
        // Before any walls settle, the editor previews only a floor outline.
        // Frame that footprint with the same camera rule as a finished house.
        const points = b.walls?.length ? b.walls.flatMap(w => [w.from, w.to])
          : [...(b.levels || []).flatMap(l => l.outline || []), ...(b.rooms || []).flatMap(r => r.polygon || [])];
        return points.map(p => [c * p[0] - s * p[1] + (b.position?.[0] || 0), s * p[0] + c * p[1] + (b.position?.[1] || 0)]);
      });
      if (points.length) {
        const xs = points.map(p => p[0]), ys = points.map(p => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
        bounds = { x: (x0 + x1) / 2, y: (y0 + y1) / 2, span: Math.max(x1 - x0 + 7, y1 - y0, 20) };
      }
      const reach = Math.max(bounds.span * FT, 20);
      Object.assign(sun.shadow.camera, { left: -reach, right: reach, top: reach, bottom: -reach, near: 0.5, far: reach * 6 }); sun.shadow.camera.updateProjectionMatrix();
      // Geometry invalidation is independent of the once-a-minute clock move.
      sun.shadow.needsUpdate = true;
      if (!editor) {
        twin.groups.roof.visible = twin.groups.gableFull.visible = true;
        twin.groups.gableCut.visible = false;
        viewing = createViewing(view, twin, b => buildingGround(plan, b), key => {
          state.view = key; sun.shadow.needsUpdate = true; applyLights();
          el.dispatchEvent(new CustomEvent('twinviewchange', { detail: key }));
        }, {explicit: true});
      }
      if (!editor) {
        const saved = view.levels?.save(); view.levels?.stop();
        view.levels = createLevels(view, {host: el, visibility: key => {viewing.select(key); applyLights();}});
        if (!view.levels.go(saved?.state || {level: 'house'}, {immediate: true}))
          view.levels.go({level: 'house'}, {immediate: true});
      } else {
        view.setView(twin.groups.levels[state.view] ? state.view : 'ext');
        if (!(preserveCamera && (framed || cameraMoved))) view.setCamera(state.camera);
      }
      updateTime();
      if (points.length) framed = true;
      if (levelsToRestore) view.showLevels(levelsToRestore, { faint: faintToRestore });
      attachSheet();
      paintSelection();
      try { await viewing?.warm(); }
      finally { releaseViewing?.(); }
      view.ready = true;
      startBake();
      el.dispatchEvent(new CustomEvent('twinrebuilt', { detail: view }));
    },
    dispose() {
      if (disposed) return;
      disposed = true; ++revision; view.ready = false;
      view.levels?.stop();
      clearInterval(timeTimer); clearTimeout(previewIdle);
      for (const name of ['pointerdown', 'pointermove', 'keydown', 'input']) document.removeEventListener(name, previewActivity);
      view.bake?.stop();
      view.live?.stop();
      view.idle?.stop(); view.glance?.stop(); view.glanceSettings?.stop();
      view.energySettings?.stop();
      if (probeRun) {
        probeRun.reject(new Error('The twin was disposed during the probe.')); probeRun = null;
      }
      renderer3.setAnimationLoop(null); observer.disconnect(); controls.dispose();
      clearSheet(); sheetSpec = null;
      restoreSelection();
      restoreFloors();
      viewing?.dispose(); viewing = null;
      if (twin) { scene.remove(twin.root); release(twin); }
      unlit.dispose();
      sky?.dispose(); environmentTarget?.dispose(); fallbackEnvironment.dispose(); sun.shadow.dispose();
      renderer3.dispose(); renderer3.forceContextLoss(); renderer3.domElement.remove();
      if (window.__twin === view) delete window.__twin;
    },
  };
  function release(model, keepMaterials = new Set()) {
    model.root.traverse(o => o.userData.releasePlants?.(keepMaterials));
    disposeObject(model.root, { keepMaterials });
    // Materials with no geometry (e.g. an empty polygon) still own requests.
    model.materials.forEach(m => { if (!keepMaterials.has(m)) m.dispose(); });
  }
  function applyTimeLook() {
    if (state.unlit) {
      timeLook = lookAt(45);
      scene.background = new THREE.Color().setRGB(...timeLook.background, THREE.SRGBColorSpace);
      scene.environment = null; scene.environmentIntensity = 0;
      sun.intensity = moon.intensity = ambient.intensity = 0;
      renderer3.toneMappingExposure = 1;
      return;
    }
    const now = clockNow(), located = resolveSite(site, now), date = previewDate(now, state.time, located);
    const solar = sunPosition(date, located.lat, located.lon), lunar = moonPosition(date, located.lat, located.lon);
    timeLook = lookAt(solar.altitude * 180 / Math.PI, { altitude: lunar.altitude, fraction: moonIllumination(date).fraction });
    scene.background = new THREE.Color().setRGB(...timeLook.background, THREE.SRGBColorSpace);
    scene.environment = environment;
    scene.environmentIntensity = timeLook.environment;
    sun.intensity = timeLook.sun; moon.intensity = timeLook.moon;
    sun.color.setRGB(...timeLook.sunColor, THREE.SRGBColorSpace);
    moon.color.setRGB(...timeLook.moonColor, THREE.SRGBColorSpace);
    ambient.intensity = timeLook.ambient;
    renderer3.toneMappingExposure = timeLook.exposure;
    for (const [light, position] of [[sun, solar], [moon, lunar]]) {
      const [x, y, z] = modelDirection(position.azimuth, position.altitude, located.front_bearing_deg);
      const radius = Math.max(bounds.span * FT * 2, 40);
      light.target.position.set(bounds.x * FT, 0, -bounds.y * FT);
      light.position.set(bounds.x * FT + x * radius, y * radius, -bounds.y * FT + z * radius);
    }
    // Rendering and lamp changes do not refresh the sun map. The clock moves
    // it at most once per minute, including rapid preview/test-clock changes.
    if (performance.now() - lastShadowUpdate >= 60000) {
      sun.shadow.needsUpdate = true; lastShadowUpdate = performance.now();
    }
  }
  function updateTime() {
    if (disposed) return;
    applyTimeLook(); applyLights(); view.onTimeLook?.(); viewing?.warm(); render();
    el.dispatchEvent(new CustomEvent('twintimechange', { detail: state.time }));
  }
  function resetPreviewIdle() {
    clearTimeout(previewIdle);
    if (!editor && state.time !== 'now') previewIdle = setTimeout(expireTimePreview, 120000);
  }
  function expireTimePreview() { if (!editor && state.time !== 'now') view.setTime('now'); }
  function previewActivity() {
    if (state.time !== 'now') resetPreviewIdle();
  }
  function startBake() {
    view.bake?.stop();
    if (!bakes || state.unlit) return;
    mountBake(view, twin.root, { host: document.getElementById('twin-controls') });
  }
  function applyLights() {
    if (!twin) return;
    const night = !!timeLook?.lamps;
    twin.roomLights.forEach(l => {
      // Each lamp keeps its own intensity, so leaving Lights mode (even after a
      // rebuild in it) lights it again; visibility follows the shown levels.
      l.userData.intensity ??= l.intensity;
      const intensity = state.unlit || liveLamps || !night ? 0 : l.userData.intensity;
      l.userData.viewingIntensity = intensity;
      l.intensity = intensity * (viewing?.levelAlpha(l.userData.level) ?? 1);
      // Live lamps zero the intensity but keep visibility, so the shader's light
      // count never changes and the first tap on Lights recompiles nothing.
      l.visible = !editor || !!twin.groups.levels[l.userData.level]?.visible;
    });
    twin.root.traverse(o => { for (const m of o.material ? [].concat(o.material) : []) if (m.name === 'fixture') m.emissiveIntensity = !liveLamps && night ? 2 : 0; });
  }
  if (new URLSearchParams(location.search).get('test') === '1') Object.assign(view, {
    expireTimePreview,
    setClock(isoString) {
      if (isoString !== null && !Number.isFinite(Date.parse(isoString))) throw new Error('Give an ISO clock time or null.');
      clock = isoString; updateTime();
    },
    cameraState() { return { position: camera.position.toArray(), target: controls.target.toArray() }; },
    // The sky as loadSky's late callback hands it over (it can land after the page is up).
    applySky(texture) { applySky(texture); },
    setCameraState({ position, target }) {
      cameraMoved = true; camera.position.fromArray(position); controls.target.fromArray(target); controls.update(); render();
    },
    roofStats(buildingId) {
      let triangles = 0, maxError = 0;
      for (const [id, roof] of twin?.roofSurfaces || []) {
        if (buildingId && id !== buildingId) continue;
        const p = roof.positions;
        for (let i = 0; i < p.length; i += 9) {
          const x = (p[i] + p[i + 3] + p[i + 6]) / 3, y = (p[i + 1] + p[i + 4] + p[i + 7]) / 3, z = (p[i + 2] + p[i + 5] + p[i + 8]) / 3;
          maxError = Math.max(maxError, Math.abs(z - (heightAt(roof.sections, x, y) ?? z))); ++triangles;
        }
      }
      return { triangles, maxError };
    },
    pieceIds(buildingId) {
      return [...(twin?.pieceBounds.values() || [])].filter(record => record.data.buildingId === buildingId).map(record => record.data.pieceId);
    },
    pieceInfo(id, buildingId) {
      twin?.updateGhosts();
      const objects = twin?.pieces.get(pieceKey(id, buildingId)), object = objects?.[0]; if (!object) return null;
      return { material: object.material.name, opacity: object.material.opacity, merged: objects.every(o => !!o.userData.merged), depthWrite: object.material.depthWrite,
        drawCalls: objects.filter(o => visible(o) && (o.isMesh || o.isLine)).reduce((sum, o) => sum + (Array.isArray(o.material) ? o.geometry.groups.length : 1), 0), polygonOffset: object.material.polygonOffset };
    },
    screenOf(id, buildingId) {
      const box = pieceBox(id, buildingId); if (!box) return null;
      camera.updateMatrixWorld(true);
      const point = box.getCenter(new THREE.Vector3()).project(camera), rect = renderer3.domElement.getBoundingClientRect();
      return [rect.left + (point.x + 1) * rect.width / 2, rect.top + (1 - point.y) * rect.height / 2];
    },
    materialsWith(prop) {
      const materials = new Set();
      scene.traverse(o => { for (const m of o.material ? [].concat(o.material) : []) if (prop in m) materials.add(m); });
      return [...materials].map(m => m.name || m.type);
    },
    sheetInfo() {
      if (!sheet) return null;
      const { ready, elevationFt, widthFt, depthFt } = sheet;
      return { ready, visible: !!sheet.object?.parent && visible(sheet.object), elevationFt, widthFt, depthFt };
    },
    levelKeys() { return Object.keys(twin?.groups.levels || {}); },
    levelVisibility() { return Object.fromEntries(Object.entries(twin?.groups.levels || {}).map(([key, group]) => [key, group.visible])); },
  });
  window.__twin = view;
  resize();
  const applySky = texture => {
    if (disposed) { texture.dispose(); return; }
    sky?.dispose(); environmentTarget?.dispose(); sky = texture;
    environmentTarget = null; environment = fallbackEnvironment;
    // An optional sky must not prevent a useful plain-colour preview.
    let pmrem;
    try {
      pmrem = new THREE.PMREMGenerator(renderer3);
      environmentTarget = pmrem.fromEquirectangular(sky); environment = environmentTarget.texture;
    } catch { environment = fallbackEnvironment; }
    finally { pmrem?.dispose(); }
    updateTime();
  };
  try {
    const skyPromise = loadSky(kit, applySky);
    await view.rebuild(plan);
    view.ready = false;
    const loadedSky = await skyPromise;
    if (loadedSky) applySky(loadedSky);
    if (disposed) return view;
    renderer3.setAnimationLoop(() => {
      const now = performance.now(), run = probeRun;
      try {
      if (run) {
        const elapsed = now - run.start;
        const floorIndex = Math.min(run.floorIds.length - 1, Math.floor((elapsed - run.exterior) / run.floor));
        const stage = elapsed < run.exterior ? 'ext' : run.floorIds[floorIndex];
        if (stage !== run.stage) { view.setView(stage); view.setCamera('top'); run.stage = stage; }
        if (stage === 'ext') {
          const angle = run.angle + elapsed / run.exterior * Math.PI * 2;
          camera.position.set(controls.target.x + Math.cos(angle) * run.radius,
            controls.target.y + run.height, controls.target.z + Math.sin(angle) * run.radius);
        }
      }
      if (view.idle?.active()) view.idle.frame(now);
      else if (!view.cameraTransition) controls.update();
      render();
      ++fpsFrames;
      if (now - fpsSince >= 500) {
        fps = fpsFrames * 1000 / (now - fpsSince); fpsFrames = 0; fpsSince = now;
        lastStats.fps = fps;
      }
      if (run) {
        const delta = now - run.previous;
        if (delta > 0) { ++run.frames; run.samples.push(1000 / delta); }
        run.previous = now;
        run.drawCalls = Math.max(run.drawCalls, lastStats.drawCalls);
        run.triangles = Math.max(run.triangles, lastStats.triangles);
        const elapsed = now - run.start;
        if (elapsed >= run.exterior + run.floorIds.length * run.floor) {
          run.samples.sort((a, b) => a - b); probeRun = null;
          run.resolve({
            tier, fpsAvg: run.frames * 1000 / elapsed,
            fpsP5: run.samples[Math.max(0, Math.ceil(run.samples.length * 0.05) - 1)] || 0,
            drawCalls: run.drawCalls, triangles: run.triangles,
            gpu: view.renderer, ua: navigator.userAgent, at: new Date().toISOString(),
          });
        }
      }
      } catch (error) {
        if (!run) throw error;
        probeRun = null;
        run.reject(error); // runProbe's finally restores the camera, view and controls.
      }
    });
    view.ready = true;
    timeTimer = setInterval(updateTime, 60000);
    for (const name of ['pointerdown', 'pointermove', 'keydown', 'input']) document.addEventListener(name, previewActivity);
  } catch (error) { view.dispose(); throw error; }
  return view;
}

// The module also serves the hidden standalone preview. Embeds call mountTwin.
async function boot() {
  const host = document.getElementById('twin-canvas'); if (!host) return;
  const status = document.getElementById('twin-status');
  try {
    const response = await fetch(base() + 'api/house/twin');
    if (!response.ok) throw new Error('Could not load the house plan.');
    const snapshot = await response.json();
    if (!snapshot.plan) { status.textContent = 'No house plan has been saved yet.'; return; }
    const kitResponse = await fetch(base() + 'api/house/twin/kit/' + encodeURIComponent(snapshot.kit_id));
    if (!kitResponse.ok) throw new Error('Could not load the house style.');
    const kit = await kitResponse.json();
    const view = await mountTwin(host, { plan: snapshot.plan, kit, round: snapshot.round ?? null, site: snapshot.site });
    document.getElementById('twin-tier').textContent = view.tier === 'low' ? 'Low' : 'High';
    const sync = () => document.querySelectorAll('[data-time]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.time === view.state.time)));
    host.addEventListener('twintimechange', sync);
    host.addEventListener('twinviewchange', sync);
    const click = event => {
      const button = event.target.closest('button'); if (!button) return;
      if (button.dataset.time) view.setTime(button.dataset.time);
      sync();
    };
    document.getElementById('twin-time-preview')?.addEventListener('click', click);
    document.getElementById('twin-preview-gear')?.addEventListener('click', () => window.chfOpenSettings('twin', 'twin-time-preview'));
    host.addEventListener('twinrebuilt', sync);
    sync(); status.hidden = true;
    const hud = document.getElementById('twin-hud');
    const hudTimer = hud ? setInterval(() => {
      const stats = view.stats(); hud.textContent = `${stats.fps.toFixed(1)} fps · ${stats.drawCalls} draw calls`;
    }, 500) : null;
    // The live layer comes up on its own: a slow or absent Home Assistant never delays the
    // probe below, and a layer that fails never reaches this page's status line. The keeper
    // retries a layer that could not mount and re-reads the layout, so a wall never needs a reload.
    const idleQuery = new URLSearchParams(location.search);
    view.glance = mountGlance(document.getElementById('twin-glance-home'));
    view.idle = mountIdle(view, view.glance, {enabled: idleQuery.get('panel') === 'true',
      // Under test=1 the idle face waits for an explicit idle_ms, so long-running
      // scenarios on the panel never go idle mid-test (2^31-1 ms is setTimeout's ceiling).
      timeout: idleQuery.get('test') !== '1' ? 60000
        : idleQuery.has('idle_ms') ? Math.max(50, Number(idleQuery.get('idle_ms')) || 60000) : 2147483647});
    view.glanceSettings = mountGlanceSettings(view, view.glance, view.idle);
    view.energySettings = mountEnergySettings(view);
    const keeper = keepLive(view, { api: (path, options) => fetch(base() + path, options) });
    window.addEventListener('pagehide', () => { keeper.stop(); clearInterval(hudTimer); view.dispose(); }, { once: true });
    const query = new URLSearchParams(location.search);
    if (query.get('probe') === '1') {
      let result;
      try {
        await new Promise(resolve => requestAnimationFrame(resolve));
        result = await view.runProbe(query.has('probe_s') ? Number(query.get('probe_s')) : 20);
        const posted = await fetch(base() + 'api/house/twin/perf', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result),
        });
        if (!posted.ok) throw new Error(`Could not save the performance probe (HTTP ${posted.status}).`);
        window.__twinProbe = { ...result, posted: true };
      } catch (error) {
        window.__twinProbe = { ...result, posted: false, error: error.message || 'The performance probe failed.' };
        status.textContent = window.__twinProbe.error; status.hidden = false;
      } finally { sync(); }
    }
  } catch (error) { status.textContent = error.message || 'The house preview could not load.'; }
}
if (typeof document !== 'undefined') boot();
