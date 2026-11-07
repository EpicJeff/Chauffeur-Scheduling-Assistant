import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { buildTwin, FT } from './twin_generator.js';
import { buildYard } from './twin_yard.js';
import { base, loadSky, disposeObject } from './twin_library.js';
import { TIERS, pickTier, rendererName } from './twin_tiers.js';

export async function mountTwin(el, { plan, kit, tier } = {}) {
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
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(38, 1, 0.1, 1000);
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
  let lastStats = { drawCalls: 0, triangles: 0, tier };
  function render() {
    if (disposed) return;
    renderer3.info.reset();
    renderer3.render(scene, camera);
    lastStats = { drawCalls: renderer3.info.render.calls, triangles: renderer3.info.render.triangles, tier };
  }
  function resize() {
    const width = Math.max(1, el.clientWidth), height = Math.max(1, el.clientHeight);
    renderer3.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix();
    render();
  }
  const observer = new ResizeObserver(resize); observer.observe(el);
  const view = {
    ready: false, scene, renderer: rendererName(renderer3.getContext()), renderer3, camera, controls, state, tier,
    groups: null, roomLights: [], plan,
    setView(id) {
      if (!twin || (id !== 'ext' && !twin.groups.levels[id])) return;
      state.view = id;
      const ext = id === 'ext', ids = Object.keys(twin.groups.levels).sort((a, b) => twin.levelElevations[a] - twin.levelElevations[b]);
      const isFirst = id === ids[0];
      twin.groups.roof.visible = twin.groups.gableFull.visible = ext;
      twin.groups.gableCut.visible = !ext && !isFirst;
      for (const level of ids) twin.groups.levels[level].visible = ext || twin.levelElevations[level] <= twin.levelElevations[id];
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
      if (!['front', 'porch', 'rear', 'top'].includes(name)) return;
      state.camera = name;
      const { x, y, span } = bounds, k = span / 38;
      const positions = { front: [x - 41 * k, 22 * k, y - 69 * k], porch: [x + 59 * k, 22 * k, y - 45 * k], rear: [x + 27 * k, 34 * k, y + 57 * k], top: [x, 105 * k, y - 0.01] };
      const [cx, cy, cz] = positions[name];
      camera.position.set(cx * FT, cy * FT, -cz * FT);
      controls.target.set(x * FT, (name === 'top' ? 3 : 8) * FT, -y * FT); controls.update(); render();
    },
    async capture(names, width = 1280, height = 800) {
      if (disposed) throw new Error('This twin has been disposed.');
      width = Math.max(1, Math.floor(width)); height = Math.max(1, Math.floor(height));
      const previous = {
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
        camera.position.copy(previous.position); controls.target.copy(previous.target); controls.update();
        camera.quaternion.copy(previous.quaternion); camera.aspect = previous.aspect; camera.updateProjectionMatrix();
        state.camera = previous.name; render();
      }
    },
    stats() { return { ...lastStats }; },
    async rebuild(nextPlan) {
      const version = ++revision; view.ready = false;
      const next = buildTwin(nextPlan, kit, tier);
      try {
        const yard = await buildYard(nextPlan, kit, tier); next.groups.site.add(yard.group); await next.ready;
      } catch (error) { release(next); throw error; }
      if (disposed || version !== revision) { release(next); return; }
      if (twin) { scene.remove(twin.root); release(twin); }
      twin = next; plan = nextPlan; scene.add(twin.root);
      view.groups = twin.groups; view.roomLights = twin.roomLights; view.plan = plan;
      const points = (plan.buildings || []).flatMap(b => (b.walls || []).flatMap(w => [w.from, w.to].map(p => [p[0] + (b.position?.[0] || 0), p[1] + (b.position?.[1] || 0)])));
      if (points.length) {
        const xs = points.map(p => p[0]), ys = points.map(p => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
        bounds = { x: (x0 + x1) / 2, y: (y0 + y1) / 2, span: Math.max(x1 - x0 + 7, y1 - y0, 20) };
      }
      sun.position.set((bounds.x - 25) * FT, 35 * FT, -(bounds.y - 30) * FT);
      sun.target.position.set(bounds.x * FT, 0, -bounds.y * FT);
      const reach = Math.max(bounds.span * FT, 20);
      Object.assign(sun.shadow.camera, { left: -reach, right: reach, top: reach, bottom: -reach, near: 0.5, far: reach * 6 }); sun.shadow.camera.updateProjectionMatrix();
      view.setView(twin.groups.levels[state.view] ? state.view : 'ext'); view.setTime(state.time); view.setCamera(state.camera);
      view.ready = true;
      el.dispatchEvent(new CustomEvent('twinrebuilt', { detail: view }));
    },
    dispose() {
      if (disposed) return;
      disposed = true; ++revision; view.ready = false;
      renderer3.setAnimationLoop(null); observer.disconnect(); controls.dispose();
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
    const night = state.time === 'night', elevation = twin.levelElevations[state.view];
    twin.roomLights.forEach(l => { l.visible = night && (state.view === 'ext' || l.userData.elevation <= elevation); });
    twin.root.traverse(o => { for (const m of o.material ? [].concat(o.material) : []) if (m.name === 'fixture') m.emissiveIntensity = night ? 2 : 0; });
  }
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
    renderer3.setAnimationLoop(() => { controls.update(); render(); });
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
      for (const [id, label] of [['ext', 'Exterior'], ...Object.keys(view.groups.levels).map(id => [id, view.plan.buildings.flatMap(b => b.levels).find(l => l.id === id)?.name || id])]) {
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
    window.addEventListener('pagehide', () => view.dispose(), { once: true });
  } catch (error) { status.textContent = error.message || 'The house preview could not load.'; }
}
if (typeof document !== 'undefined') boot();
