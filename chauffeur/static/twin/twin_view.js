import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { buildTwin, FT, PICK_LAYER, polygon, mergeStatic } from './twin_generator.js';
import { heightAt } from './twin_roof.js';
import { groundAt } from './twin_ground.js';
import { buildYard } from './twin_yard.js';
import { base, loadSky, disposeObject } from './twin_library.js';
import { TIERS, pickTier, rendererName } from './twin_tiers.js';

export async function mountTwin(el, { plan, kit, tier, preserveCamera = false } = {}) {
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
  el.appendChild(renderer3.domElement);
  const scene = new THREE.Scene(), perspective = new THREE.PerspectiveCamera(38, 1, 0.1, 1000);
  const orthographic = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 1000);
  let camera = perspective;
  const controls = new OrbitControls(camera, renderer3.domElement);
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.enableDamping = false;
  RectAreaLightUniformsLib.init();
  const sun = new THREE.DirectionalLight('#fff0d4', 3.0);
  sun.castShadow = settings.shadows;
  if (settings.shadows) {
    sun.shadow.mapSize.set(4096, 4096);
    sun.shadow.bias = -0.0002; sun.shadow.normalBias = 0.025;
  }
  const ambient = new THREE.HemisphereLight('#d9e9ff', '#68764f', 1.8);
  scene.add(sun, sun.target, ambient);
  let twin = null, disposed = false, revision = 0, sky = null, environment = null, environmentTarget = null;
  const state = { view: 'ext', time: 'day', camera: 'front' };
  let bounds = { x: 19, y: 11, span: 38 };
  let framed = false, cameraMoved = false;
  controls.addEventListener('start', () => { cameraMoved = true; });
  let lastStats = { drawCalls: 0, triangles: 0, tier, fps: 0 };
  let probeRun = null, fps = 0, fpsFrames = 0, fpsSince = performance.now();
  let visibleLevels = null, sheet = null, sheetSpec = null, sheetRevision = 0;
  const raycaster = new THREE.Raycaster(); raycaster.layers.set(PICK_LAYER);
  const visible = object => { for (let o = object; o; o = o.parent) if (!o.visible) return false; return true; };
  const faded = new Map();
  function restoreFloors() {
    for (const [object, material] of faded) {
      [].concat(object.material).forEach(m => m.dispose()); object.material = material;
    }
    faded.clear();
  }
  function floorFrame(key) {
    const building = plan.buildings.find(b => b.levels.some(l => `${b.id}:${l.id}` === key));
    const level = building?.levels.find(l => `${building.id}:${l.id}` === key);
    return building && { building, elevation: groundAt(plan, ...(building.position || [0, 0])) + (building.base || 0) + level.elevation };
  }
  function projectFloor(x, y, key) {
    const frame = floorFrame(key); if (!frame) return null;
    const b = frame.building, a = (b.rotation || 0) * Math.PI / 180;
    const wx = Math.cos(a) * x - Math.sin(a) * y + (b.position?.[0] || 0);
    const wy = Math.sin(a) * x + Math.cos(a) * y + (b.position?.[1] || 0);
    camera.updateMatrixWorld(true);
    const p = new THREE.Vector3(wx * FT, frame.elevation * FT, -wy * FT).project(camera);
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
    sheet.elevationFt = groundAt(plan, ...position) + (building.base || 0) + level.elevation;
    sheet.object.position.set(position[0], sheet.elevationFt, -position[1]);
    sheet.object.rotation.y = (building.rotation || 0) * Math.PI / 180;
    parent.add(sheet.object);
  }
  function render() {
    if (disposed) return;
    twin?.updateGhosts();
    renderer3.info.reset();
    renderer3.render(scene, camera);
    lastStats = { drawCalls: renderer3.info.render.calls, triangles: renderer3.info.render.triangles, tier, fps };
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
    groups: null, roomLights: [], plan,
    cameraKind() { return camera.isOrthographicCamera ? 'orthographic-top' : 'perspective'; },
    saveView() {
      return { camera, position: camera.position.clone(), quaternion: camera.quaternion.clone(), target: controls.target.clone(),
        zoom: camera.zoom, state: { ...state }, levels: visibleLevels && [...visibleLevels],
        faint: [...new Set([...faded.keys()].map(o => { for (let p = o; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey; }).filter(Boolean))] };
    },
    restoreView(saved) {
      camera = saved.camera; view.camera = camera; controls.object = camera; controls.enableRotate = !camera.isOrthographicCamera;
      view.setView(saved.state.view); view.showLevels(saved.levels, { faint: saved.faint });
      Object.assign(state, saved.state); camera.position.copy(saved.position); controls.target.copy(saved.target);
      camera.zoom = saved.zoom; controls.update(); camera.quaternion.copy(saved.quaternion); camera.updateProjectionMatrix(); render();
    },
    screenOfFloor: projectFloor,
    floorAt(clientX, clientY, key) {
      const frame = floorFrame(key); if (!frame) return null;
      const r = renderer3.domElement.getBoundingClientRect();
      camera.updateMatrixWorld(true);
      raycaster.setFromCamera(new THREE.Vector2((clientX - r.left) / r.width * 2 - 1, 1 - (clientY - r.top) / r.height * 2), camera);
      const point = raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -frame.elevation * FT), new THREE.Vector3());
      if (!point) return null;
      const b = frame.building, a = -(b.rotation || 0) * Math.PI / 180;
      const x = point.x / FT - (b.position?.[0] || 0), y = -point.z / FT - (b.position?.[1] || 0);
      return [Math.cos(a) * x - Math.sin(a) * y, Math.sin(a) * x + Math.cos(a) * y];
    },
    setPlanCamera(key) {
      const frame = floorFrame(key); if (!frame) return;
      camera = orthographic; view.camera = camera; controls.object = camera;
      state.camera = 'top';
      orthographic.top = Math.max(20, bounds.span * 0.72) * FT; orthographic.bottom = -orthographic.top;
      orthographic.zoom = 1;
      camera.position.set(bounds.x * FT, (frame.elevation + 250) * FT, -bounds.y * FT);
      controls.target.set(bounds.x * FT, frame.elevation * FT, -bounds.y * FT);
      controls.enableRotate = false; controls.update(); resize();
    },
    pick(clientX, clientY) {
      if (!twin) return null;
      const rect = renderer3.domElement.getBoundingClientRect();
      if (clientX < rect.left || clientX >= rect.right || clientY < rect.top || clientY >= rect.bottom) return null;
      twin.root.updateMatrixWorld(true); camera.updateMatrixWorld(true);
      raycaster.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, 1 - (clientY - rect.top) / rect.height * 2), camera);
      // The plan camera reaches pieces beneath the roof, as a floor editor
      // must; perspective views can select the roof itself.
      const candidates = [...twin.pickObjects.values()].filter(o => {
        if (!visible(o) || (state.camera === 'top' && o.userData.kind === 'roof')) return false;
        if (camera.isOrthographicCamera && state.view !== 'ext') {
          for (let p = o; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey === state.view;
        }
        return true;
      });
      const hits = raycaster.intersectObjects(candidates, false);
      const hit = state.camera === 'top' ? hits.find(h => h.object.userData.kind === 'wall') || hits[0] : hits[0];
      if (!hit) return null;
      const { pieceId, kind, buildingId } = hit.object.userData;
      return { pieceId, kind, buildingId };
    },
    worldBox(id, buildingId) {
      const box = pieceBox(id, buildingId); if (!box) return null;
      return { min: [box.min.x / FT, -box.max.z / FT, box.min.y / FT], max: [box.max.x / FT, -box.min.z / FT, box.max.y / FT] };
    },
    showLevels(keys, { faint = [] } = {}) {
      if (!twin) return;
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
      applyLights(); render();
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
      const elevation = groundAt(plan, ...(building.position || [0, 0])) + (building.base || 0) + level.elevation;
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
      restoreFloors();
      state.view = id;
      visibleLevels = null;
      const ext = id === 'ext', ids = Object.keys(twin.groups.levels).sort((a, b) => twin.levelElevations[a] - twin.levelElevations[b]);
      const buildingId = ext ? null : twin.groups.levels[id].userData.buildingId;
      const isFirst = id === ids.find(key => twin.groups.levels[key].userData.buildingId === buildingId);
      twin.groups.roof.visible = twin.groups.gableFull.visible = ext;
      twin.groups.gableCut.visible = !ext && !isFirst;
      for (const level of ids) twin.groups.levels[level].visible = ext || (twin.groups.levels[level].userData.buildingId === buildingId && twin.levelElevations[level] <= twin.levelElevations[id]);
      for (const domain of ['roof', 'gableFull', 'gableCut']) for (const group of twin.groups[domain].children) group.visible = ext || group.userData.buildingId === buildingId;
      applyLights(); render();
    },
    setTime(time) {
      if (!['day', 'night'].includes(time)) return;
      state.time = time;
      const night = time === 'night';
      scene.background = new THREE.Color(night ? '#101b31' : '#b9cbd7');
      scene.environment = night ? null : environment;
      scene.environmentIntensity = 0.65;
      sun.visible = !night; ambient.intensity = night ? 0.24 : 1.8;
      renderer3.toneMappingExposure = night ? 1.2 : 1;
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
      controls.target.set(x * FT, (name === 'top' ? 3 : 8) * FT, -y * FT); controls.update(); render();
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
    async rebuild(nextPlan) {
      const version = ++revision; view.ready = false;
      const next = buildTwin(nextPlan, kit, tier);
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
                const first = Math.min(...building.levels.map(l => l.elevation));
                const holes = (building.stairs || []).filter(s => s.rise_to >= level.elevation && level.elevation > first).map(s => {
                  const dx = s.to[0] - s.from[0], dy = s.to[1] - s.from[1], length = Math.hypot(dx, dy);
                  const nx = -dy / length * s.width / 2, ny = dx / length * s.width / 2;
                  return [[s.from[0] + nx, s.from[1] + ny], [s.to[0] + nx, s.to[1] + ny], [s.to[0] - nx, s.to[1] - ny], [s.from[0] - nx, s.from[1] - ny]];
                });
                const inside = p => {
                  const poly = piece.polygon; let inside = false;
                  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) if ((poly[i][1] > p[1]) !== (poly[j][1] > p[1]) && p[0] < (poly[j][0] - poly[i][0]) * (p[1] - poly[i][1]) / (poly[j][1] - poly[i][1]) + poly[i][0]) inside = !inside;
                  return inside;
                };
                add(polygon(piece.polygon, level.elevation + .012, level.elevation + .012, holes.filter(h => h.every(inside))));
              } else {
                const [x, y] = piece.position, height = piece.head - piece.sill;
                const wall = building.walls.find(w => w.id === piece.wall);
                const angle = wall ? Math.atan2(wall.to[1] - wall.from[1], wall.to[0] - wall.from[0]) : 0;
                add(new THREE.BoxGeometry(piece.width, height, .08).rotateY(angle)
                  .translate(x, level.elevation + piece.sill + height / 2, -y));
              }
              next.pieces.set(key, objects);
              const geometry = objects[0].geometry; geometry.computeBoundingBox();
              next.pieceBounds.set(key, { box: geometry.boundingBox.clone(), group, data });
              const proxy = new THREE.Mesh(geometry.clone(), next.materials.get('pick'));
              Object.assign(proxy.userData, data); proxy.layers.set(PICK_LAYER); group.add(proxy); next.pickObjects.set(key, proxy);
            }
          }
        }
        for (const group of extras.values()) mergeStatic(group);
        const yard = await buildYard(nextPlan, kit, tier); next.groups.site.add(yard.group); await next.ready;
      } catch (error) { release(next); throw error; }
      if (disposed || version !== revision) { release(next); return; }
      const levelsToRestore = visibleLevels && [...visibleLevels];
      const faintToRestore = [...new Set([...faded.keys()].map(o => {
        for (let p = o; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey;
        return null;
      }).filter(Boolean))];
      restoreFloors();
      // The underlay owns its image independently of the rebuilt geometry.
      // Detach before releasing the old scene, then place the same object.
      sheet?.object?.removeFromParent();
      if (twin) { scene.remove(twin.root); release(twin); }
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
      sun.position.set((bounds.x - 25) * FT, 35 * FT, -(bounds.y - 30) * FT);
      sun.target.position.set(bounds.x * FT, 0, -bounds.y * FT);
      const reach = Math.max(bounds.span * FT, 20);
      Object.assign(sun.shadow.camera, { left: -reach, right: reach, top: reach, bottom: -reach, near: 0.5, far: reach * 6 }); sun.shadow.camera.updateProjectionMatrix();
      view.setView(twin.groups.levels[state.view] ? state.view : 'ext'); view.setTime(state.time);
      if (!(preserveCamera && (framed || cameraMoved))) view.setCamera(state.camera);
      if (points.length) framed = true;
      if (levelsToRestore) view.showLevels(levelsToRestore, { faint: faintToRestore });
      attachSheet();
      view.ready = true;
      el.dispatchEvent(new CustomEvent('twinrebuilt', { detail: view }));
    },
    dispose() {
      if (disposed) return;
      disposed = true; ++revision; view.ready = false;
      if (probeRun) {
        probeRun.reject(new Error('The twin was disposed during the probe.')); probeRun = null;
      }
      renderer3.setAnimationLoop(null); observer.disconnect(); controls.dispose();
      clearSheet(); sheetSpec = null;
      restoreFloors();
      if (twin) { scene.remove(twin.root); release(twin); }
      sky?.dispose(); environmentTarget?.dispose(); sun.shadow.dispose();
      renderer3.dispose(); renderer3.forceContextLoss(); renderer3.domElement.remove();
      if (window.__twin === view) delete window.__twin;
    },
  };
  function release(model) {
    model.root.traverse(o => o.userData.releasePlants?.());
    disposeObject(model.root);
    // Materials with no geometry (e.g. an empty polygon) still own requests.
    model.materials.forEach(m => m.dispose());
  }
  function applyLights() {
    if (!twin) return;
    const night = state.time === 'night';
    twin.roomLights.forEach(l => { l.visible = night && !!twin.groups.levels[l.userData.level]?.visible; });
    twin.root.traverse(o => { for (const m of o.material ? [].concat(o.material) : []) if (m.name === 'fixture') m.emissiveIntensity = night ? 2 : 0; });
  }
  if (new URLSearchParams(location.search).get('test') === '1') Object.assign(view, {
    cameraState() { return { position: camera.position.toArray(), target: controls.target.toArray() }; },
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
  try {
    const skyPromise = loadSky(kit);
    await view.rebuild(plan);
    view.ready = false;
    sky = await skyPromise;
    if (disposed) { sky?.dispose(); return view; }
    if (sky) {
      // An optional sky must not prevent a useful plain-colour preview.
      let pmrem;
      try {
        pmrem = new THREE.PMREMGenerator(renderer3);
        environmentTarget = pmrem.fromEquirectangular(sky); environment = environmentTarget.texture;
      } catch { environment = null; }
      finally { pmrem?.dispose(); }
      view.setTime(state.time);
    }
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
      controls.update(); render();
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
    const view = await mountTwin(host, { plan: snapshot.plan, kit });
    document.getElementById('twin-tier').textContent = view.tier === 'low' ? 'Low' : 'High';
    const views = document.getElementById('twin-views');
    const syncViews = () => {
      views.replaceChildren();
      for (const [id, label] of [['ext', 'Exterior'], ...view.plan.buildings.flatMap(b => b.levels.map(l => [`${b.id}:${l.id}`, (view.plan.buildings.length > 1 ? (b.name || b.id) + ' · ' : '') + (l.name || l.id)]))]) {
        const button = document.createElement('button'); button.type = 'button'; button.dataset.view = id; button.textContent = label; views.appendChild(button);
      }
    };
    syncViews();
    const sync = () => document.querySelectorAll('[data-view], [data-time], [data-camera]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view ? b.dataset.view === view.state.view : b.dataset.time ? b.dataset.time === view.state.time : b.dataset.camera === view.state.camera)));
    const click = event => {
      const button = event.target.closest('button'); if (!button) return;
      if (button.dataset.view) { view.setView(button.dataset.view); if (button.dataset.view !== 'ext') view.setCamera('top'); }
      if (button.dataset.time) view.setTime(button.dataset.time);
      if (button.dataset.camera) view.setCamera(button.dataset.camera);
      sync();
    };
    document.getElementById('twin-controls').addEventListener('click', click);
    host.addEventListener('twinrebuilt', () => { syncViews(); sync(); });
    sync(); status.hidden = true;
    const hud = document.getElementById('twin-hud');
    const hudTimer = hud ? setInterval(() => {
      const stats = view.stats(); hud.textContent = `${stats.fps.toFixed(1)} fps · ${stats.drawCalls} draw calls`;
    }, 500) : null;
    window.addEventListener('pagehide', () => { clearInterval(hudTimer); view.dispose(); }, { once: true });
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
