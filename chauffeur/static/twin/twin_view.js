import { roomFloor, openingFloor } from './twin_floors.js';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { mountEditorCamera } from './editor/camera_controls.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { buildTwin, FT, PICK_LAYER, polygon, mergeStatic, contains, stairHoles } from './twin_generator.js';
import { span as editSpan } from './edit_timing.js';
import { heightAt } from './twin_roof.js';
import { groundAt, buildingGround } from './twin_ground.js';
import { buildYard, yardKey, yardMaterialKey, yardPartKeys } from './twin_yard.js';
import { base, disposeObject, manifest, currentMaterial, applyMaterialParams, copyMaterialParams, alphaModeOf, scaleStyledFadeAlpha } from './twin_library.js';
import { watchMaterialCatalogue } from './material_watch.js';
import { grassLawn } from './yard_grass.js';
import { TIERS, pickTier, rendererName } from './twin_tiers.js';
import { hostPoint } from './twin_hosts.js';
import { siteRecord, siteShapeKinds, sitePoints } from './objects.js';
import { selectionBoxes, selectionBoxFor, projectSelectionBoxes } from './editor/selection_bounds.js';
import { keepLive } from './live/live.js';
import { mountGlance } from './live/glance.js';
import { mountIdle } from './live/idle.js';
import { mountGlanceSettings } from './live/glance_settings.js';
import { mountEnergySettings } from './live/energy_settings.js';
import { mountBake } from './bake/runtime.js';
import { registerBakeSource, bakeAuthoredMaterial } from './bake/source.js';
import { withoutSurfaceMaterials } from './bake/geometry_key.js';
import { atlasMesh } from './bake/atlas.js';
import { sunPosition, moonPosition, moonIllumination, localSiderealTime } from './sky/ephemeris.js';
import { lookAt, modelDirection, previewDate, resolveSite, readNightBrightness, writeNightBrightness, clampNightBrightness } from './sky/look.js';
import { createSky, sampleSkyIrradiance, transmittance, fogColour } from './sky/atmosphere.js';
import { createCloudPass } from './sky/cloud_pass.js';
import { createWeatherClock, sourceEntity, neutralWeather, createWeatherPreview, mountWeatherState, weatherHaze, weatherExtinction, weatherLightingKey, sunAirVisibility, sunDiscVisibility } from './sky/weather.js';
import { installPlantWind } from './sky/wind.js';
import { installStageHaze, startEnvironmentFrame } from './sky/stage_haze.js';
import { installCloudShadow } from './sky/cloud_shadow.js';
import { installWeatherSurface } from './sky/weather_surface.js';
import { createRoofWater, eaveRunoff } from './sky/roof_water.js';
import { seasonState, createSeasonPreview, installSeasons } from './sky/seasons.js';
import { createPrecipitation } from './sky/precipitation.js';
import { createEaveStreams } from './sky/eave_streams.js';
import { createSkyCover, writeWeatherOpen, refreshSlabCover } from './sky/sky_cover.js';
import { createSeasonTouches } from './sky/season_touches.js';
import { mountTimeScrub, mountNightBrightness } from './sky/time_scrub.js';
import { defaultStage, mountStageSettings } from './stage_settings.js';
import { mountWeatherSettings } from './weather_settings.js';
import { weatherState as pickWeather } from './sky/overcast.js';
import { createUnlit } from './unlit.js';
import { createViewing } from './viewing.js';
import { createLevels } from './levels.js';
import { mountFrameMeter } from './frame_meter.js';
import { createPost, EMITTER_GAIN } from './post.js';
import { createReflectionProbes } from './reflection_probes.js';
import { createPieceVisibility } from './twin_visibility.js';
import { freezeViewerMatrices } from './static_matrices.js';

export async function mountTwin(el, { plan, kit, tier, preserveCamera = false, round = null, bake = true, site = {}, stage = null } = {}) {
  kit = kit || {};
  kit.manifest ||= manifest(kit);
  // Owner decision 2026-11-21 supersedes B15: the editor bakes on request;
  // the viewer only draws stored lighting. Both use the neutral bake source.
  const editor = !!el.closest?.('.editor-shell');
  const pieceVisibility = editor ? createPieceVisibility() : null;
  const bakes = bake !== false;
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
  const clouds = createCloudPass(renderer3, {tier});
  const post = settings.occlusion ? createPost(renderer3, scene, camera, {samples: settings.antialias ? 4 : 0, clouds, tier}) : null;
  clouds.warm(post?.target);
  // three keys every program on where it draws. With the composer on, the
  // picture draws into its half-float target (linear, no tone mapping), so a
  // warm-up compiled for the canvas warmed programs nothing draws, and the real
  // ones compiled on the main thread at first draw: seconds of frozen page each
  // time the light set or the bake changed on a full house. Every warm-up
  // compiles for where the picture draws. While one is in flight, render()
  // keeps the last picture (HOLD_MS at most): a frame drawn with a program
  // still compiling waits for the GPU on the main thread.
  const compileFor = renderer3.compileAsync?.bind(renderer3), HOLD_MS = 15000;
  let compiling = 0, holdSince = 0;
  const compileBehind = (target, eye, targetScene = null) => {
    const saved = [renderer3.getRenderTarget(), renderer3.getActiveCubeFace(), renderer3.getActiveMipmapLevel()];
    try {
      stageHaze.prepare(target);
      cloudShadow.prepare(target);
      plantWind.prepare(target);
      seasons.prepare(target);
      weatherSurface.prepare(target);
      // Never undefined: three reads the target's fields when it is not null.
      renderer3.setRenderTarget((!state.unlit && post?.target) || null);
      return compileFor(target, eye, targetScene);
    } finally { renderer3.setRenderTarget(...saved); }
  };
  if (compileFor) renderer3.compileAsync = (target, eye, targetScene = null) => {
    const ready = compileBehind(target, eye, targetScene);
    if (!compiling++) holdSince = performance.now();
    return ready.finally(() => { if (!--compiling && !disposed) render(); });
  };
  const controls = new OrbitControls(camera, renderer3.domElement);
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.enableDamping = false;
  if (!THREE.UniformsLib.LTC_FLOAT_1) RectAreaLightUniformsLib.init();
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
  const sky = createSky(renderer3, {tier, clouds}), environment = sky.environment;
  const stageHaze = installStageHaze(scene, sky);
  const cloudShadow = installCloudShadow(scene, clouds);
  const plantWind = installPlantWind(scene,{tier});
  const weatherSurface = installWeatherSurface(scene);
  const roofWater = createRoofWater();
  const seasons = installSeasons(scene);
  const precipitation = createPrecipitation(scene,{tier});
  const eaves = createEaveStreams(scene,{tier}),runoff={};
  const eaveLamps=()=>view.live?.lights?.()||[];
  post?.setWetGround({weatherSurface:weatherSurface.uniforms.weatherSurface,...precipitation.uniforms});
  const seasonTouches = createSeasonTouches(scene,{tier});
  let precipitationPlan=null,precipitationRoofs=null,precipitationCover=null;
  let eavePlan=null,eaveRoofs=null,eaveGutters=null;
  let cloudCentre=[0,0];
  let stageOverride = stage?.radius_override === undefined ? stage?.radius ?? null : stage.radius_override;
  const stageForPlan = nextPlan => {
    const automatic = defaultStage(nextPlan);
    return {...automatic, radius:stageOverride ?? automatic.radius, radius_override:stageOverride};
  };
  function syncStage(nextPlan) {
    const value = stageForPlan(nextPlan);
    cloudCentre=value.centre.map(v => v*FT);
    stageHaze.set({centre:value.centre.map(v => v*FT), radius:value.radius*FT});
    cloudShadow.set({centre:value.centre.map(v => v*FT), radius:value.radius*FT});
    precipitation.setStage({centre:value.centre.map(v => v*FT), radius:value.radius*FT});
    seasonTouches.setStage({centre:value.centre.map(v => v*FT), radius:value.radius*FT});
  }
  syncStage(plan);
  scene.add(sky.object);
  let twin = null, disposed = false, revision = 0, bakeSignature = null;
  let rebuildWork = null;
  const materialBindings = new Map();
  scene.environment = environment;
  scene.background = sky.clearCube;
  const state = { view: 'ext', time: editor ? 'day' : 'now', previewHour:null, camera: 'front', unlit: false, liveWeather:false, weatherPreview:null, seasonPreview:null };
  const unlit = createUnlit();
  let viewing = null;
  let shadowAutoUpdate;
  let clock = null, previewIdle = null, timeTimer = null, timeLook = null, lastShadowUpdate = -Infinity;
  let nightBrightness = readNightBrightness();
  const clockNow = () => clock ? new Date(clock) : new Date();
  let liveLamps = false;
  let weatherEntity = null, lastWeather = '', groundWeather = {}, weatherPoll = null;
  const liveWeatherClock=createWeatherClock();
  const weatherPreview=createWeatherPreview(()=>{
    state.weatherPreview=weatherPreview.get()?.preview || null;
    updateTime(false,true);
  });
  const seasonPreview=createSeasonPreview(()=>{
    state.seasonPreview=seasonPreview.get();
    updateTime(false,true);
  });
  function currentWeather() {
    const preview=weatherPreview.get();
    if(preview)return preview;
    if(editor && !state.liveWeather)return neutralWeather();
    const states=view.live?.peek?.(), stale=view.live?.stale?.();
    const entity=states ? pickWeather(states,weatherEntity,stale ?? true) : sourceEntity(groundWeather);
    const sensors={...groundWeather.source?.sensors};
    for(const [role,sensor] of Object.entries(sensors)){
      if(states && sensor.entity && Object.hasOwn(states,sensor.entity))sensors[role]={...states[sensor.entity],unit:states[sensor.entity]?.attributes?.unit_of_measurement};
    }
    // Modern HA forecasts arrive only through the server's hourly service read.
    // Never reuse one for a different condition after an existing-stream push.
    const values=groundWeather.source?.values;
    const observed=entity && values?.condition===entity.state && Number.isFinite(values.precipitation)
      ? {...entity,normalizedRate:values.precipitation} : entity;
    return liveWeatherClock(observed,groundWeather,sensors);
  }
  let bounds = { x: 19, y: 11, span: 38 };
  let framed = false, cameraMoved = false;
  controls.addEventListener('start', () => { cameraMoved = true; });
  let lastStats = { drawCalls: 0, triangles: 0, tier, fps: 0 };
  let probeRun = null, fps = 0, fpsFrames = 0, fpsSince = performance.now();
  let visibleLevels = null, sheet = null, sheetSpec = null, sheetRevision = 0;
  const reflections = createReflectionProbes({scene, renderer:renderer3, tier,
    extras:() => [sky.object, precipitation.group, eaves.group, seasonTouches.group, sheet?.object, ...selectionLines], sky:() => sky.cube, uncut:() => viewing?.uncut?.()});
  reflections.setMirrorStillHz(stage?.mirror_still_hz ?? 10);
  reflections.setProbeCloudSeconds(stage?.probe_cloud_s ?? 30);
  const raycaster = new THREE.Raycaster(); raycaster.layers.set(PICK_LAYER);
  const visible = object => { for (let o = object; o; o = o.parent) if (!o.visible) return false; return true; };
  const faded = new Map();
  let editableLevel = null, selectionStyle = null, boundsCache = null, selectionBoundsRevision = 0;
  const hoverBoxCache = new Map();
  const invalidateSelectionBounds = () => { boundsCache = null; hoverBoxCache.clear(); ++selectionBoundsRevision; };
  // Deferred yard adoption changes the rendered bounds without a camera move.
  // Existing handles and overlays already share this projection redraw hook.
  const redrawAfterYard = () => controls.dispatchEvent({ type: 'change' });
  el.addEventListener('twinyardrebuilt', redrawAfterYard);
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
    const members = Array.isArray(selectionStyle.members) ? selectionStyle.members : selected ? [selected] : [];
    const allowed = new Set(room?.allowed || []), walls = new Set(room?.walls || []);
    const style = getComputedStyle(el.closest('.editor-shell') || el);
    const accent = new THREE.Color(style.getPropertyValue('--editor-accent').trim() || '#52ccff');
    const wallTint = new THREE.Color(style.getPropertyValue('--editor-room-wall').trim() || '#9b7cdb');
    const matchesMember = (data, objects, m) => {
      const mid = m.id ?? m.pieceId, mb = m.building ?? m.buildingId ?? null;
      if (data.buildingId !== mb) return false;
      if (data.pieceId === mid || m.kind === 'building') return true;
      if (m.kind === 'roof') {
        const section = plan.buildings?.find(b => b.id === mb)?.roof?.sections?.find(s => s.id === data.pieceId);
        if (section?.roof === mid) return true;
      }
      if (m.kind === 'level') {
        return objects.some(o => {
          for (let p = o; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey === `${mb}:${mid}`;
          return false;
        });
      }
      return false;
    };
    const styled = new Set();
    for (const [key, objects] of twin.pieces) {
      const data = twin.pieceBounds.get(key)?.data;
      if (!data) continue;
      const inRoom = room && data.buildingId === room.building && allowed.has(data.pieceId);
      const ghost = room && !inRoom;
      const tint = inRoom ? data.pieceId === room.id ? accent : walls.has(data.pieceId) ? wallTint : null
        : !room && members.some(m => matchesMember(data, objects, m)) ? accent : null;
      if (!ghost && !tint) continue;
      for (const object of objects) {
        if (styled.has(object) || !object.material) continue;
        styled.add(object); selectedMaterials.set(object, object.material);
        const clone = material => {
          const next = material.clone(); selectionMaterials.add(next);
          if (ghost) { next.userData.styledFade = true; next.opacity = 0.25; next.transparent = true; next.depthWrite = false; scaleStyledFadeAlpha(material, next); }
          else { next.color?.lerp(tint, 0.32); next.userData.selectionTint = tint.getHex(); }
          return next;
        };
        object.material = Array.isArray(object.material) ? object.material.map(clone) : clone(object.material);
      }
    }
    if (room) twin.groups.site.traverse(object => {
      if (!object.material || selectedMaterials.has(object) || object.layers.isEnabled(PICK_LAYER)) return;
      selectedMaterials.set(object, object.material);
      const clone = material => {
        const next = material.clone(); next.userData.styledFade = true; next.opacity = .25; next.transparent = true; next.depthWrite = false; scaleStyledFadeAlpha(material, next);
        selectionMaterials.add(next); return next;
      };
      object.material = Array.isArray(object.material) ? object.material.map(clone) : clone(object.material);
    });
    const single = members.length <= 1;
    for (const member of members) outline(member, false, { single });
    outline(hover, true, { single: true });
    render();
  }
  function currentSelectionBoxes({ fresh = false } = {}) {
    if (fresh || !boundsCache) {
      const list = selectionBoxes({ twin, yard: twin?.groups.site || yardGroup, scene, plan, visible });
      const map = new Map(list.map(e => [JSON.stringify([e.buildingId ?? null, e.pieceId]), e]));
      boundsCache = { list, map };
    }
    return boundsCache;
  }
  function lookupSelectionBox(pick, { single = false } = {}) {
    const id = pick.id ?? pick.pieceId, buildingId = pick.building ?? pick.buildingId ?? null;
    const key = JSON.stringify([buildingId, id]);
    if (boundsCache) return boundsCache.map.get(key) || null;
    if (single) {
      if (hoverBoxCache.has(key)) return hoverBoxCache.get(key);
      const entry = selectionBoxFor({ yard: twin?.groups.site || yardGroup, scene, plan, visible, pieceId: id, buildingId, kind: pick.kind });
      hoverBoxCache.set(key, entry);
      return entry;
    }
    return currentSelectionBoxes().map.get(key) || null;
  }
  function fallbackSiteBox(id) {
    const site = siteRecord(plan, id);
    if (!site) return null;
    const box = new THREE.Box3();
    if (siteShapeKinds.includes(site.kind)) {
      for (const [x, y] of sitePoints(site.piece)) {
        const z = groundAt(plan, x, y) + (site.piece.elevation || 0);
        const rad = site.piece.at ? (site.piece.radius || 2) : 0.3;
        box.expandByPoint(new THREE.Vector3((x - rad) * FT, z * FT, -(y + rad) * FT));
        box.expandByPoint(new THREE.Vector3((x + rad) * FT, (z + (site.piece.height || 1)) * FT, -(y - rad) * FT));
      }
    } else if (site.piece.at) {
      const [x, y] = site.piece.at;
      const h = (site.kind === 'planting' ? site.piece.height || 4 : 3) * (site.piece.scale ?? 1);
      const rad = site.kind === 'planting' ? Math.max(1, h * 0.18) : 2 * (site.piece.scale ?? 1);
      const z = groundAt(plan, x, y) + (site.piece.elevation || 0);
      box.expandByPoint(new THREE.Vector3((x - rad) * FT, z * FT, -(y + rad) * FT));
      box.expandByPoint(new THREE.Vector3((x + rad) * FT, (z + h) * FT, -(y - rad) * FT));
    }
    return box.isEmpty() ? null : { box, kind: site.kind };
  }
  function outline(pick, isHover, { single = false } = {}) {
    if (!pick) return;
    const id = pick.id ?? pick.pieceId;
    const buildingId = pick.building ?? pick.buildingId ?? null;
    if (!id) return;
    const accent = new THREE.Color(getComputedStyle(el.closest('.editor-shell') || el).getPropertyValue('--editor-accent').trim() || '#52ccff');
    const yard = !buildingId && plan.site?.yard_rooms?.find(r => r.id === id);
    if (yard) {
      const geometry = new THREE.BufferGeometry().setFromPoints([...yard.polygon, yard.polygon[0]].map(p =>
        new THREE.Vector3(p[0], groundAt(plan, ...p) + .06, -p[1])));
      const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ fog: false, color: accent, transparent: true, opacity: isHover ? .4 : .65, depthTest: false }));
      Object.assign(line.userData, { pieceId: id, kind: 'yard_room' });
      line.userData.isHover = isHover; line.renderOrder = 10; twin.root.add(line); selectionLines.push(line); return;
    }
    const bldg = buildingId ? plan.buildings.find(b => b.id === buildingId) : null;
    const keys = [...twin.pieceBounds].filter(([, { data }]) => data.buildingId === buildingId
      && (data.pieceId === id || pick.kind === 'building'
        || (pick.kind === 'roof' && bldg?.roof?.sections?.find(s => s.id === data.pieceId)?.roof === id)
        || pick.kind === 'level'
          && bldg?.levels.some(l => l.id === id)
          && twin.pickObjects.get(`${data.buildingId}:${data.pieceId}`)?.parent?.userData.levelKey === `${buildingId}:${id}`));
    for (const [key] of keys) {
      const proxy = twin.pickObjects.get(key); if (!proxy) continue;
      const material = new THREE.LineBasicMaterial({ fog: false, color: accent, transparent: true, opacity: isHover ? .65 : 1, depthTest: false });
      let geometry;
      const b = bldg, r = b?.rooms?.find(r => r.id === id);
      if (r && pick.kind === 'room') {
        const z = roomFloor(b.levels.find(l => l.id === r.level), r) + .04;
        geometry = new THREE.BufferGeometry().setFromPoints([...r.polygon, r.polygon[0]].map(p => new THREE.Vector3(p[0], z, -p[1])));
      } else geometry = new THREE.EdgesGeometry(proxy.geometry);
      const line = r && pick.kind === 'room' ? new THREE.Line(geometry, material) : new THREE.LineSegments(geometry, material);
      line.userData.selectionKey = key;
      Object.assign(line.userData, proxy.userData);
      line.userData.isHover = isHover;
      line.userData.roomOutline = !!r && pick.kind === 'room';
      line.renderOrder = isHover ? 11 : 10; proxy.parent.add(line); selectionLines.push(line);
    }
    if (keys.length) return;
    // Non-building pieces (yard items, instanced plants, fixtures): use the
    // shared rendered bounds from selection_bounds.js (zero new samplers/uniforms).
    let entry = lookupSelectionBox(pick, { single });
    let fallbackBox = false;
    if (!entry && !isHover && !buildingId && !pieceVisibility?.hidden({ id, kind: pick.kind })) {
      entry = fallbackSiteBox(id);
      fallbackBox = !!entry;
    }
    if (!entry) return;
    const helper = new THREE.Box3Helper(entry.box.clone(), accent);
    helper.material.depthTest = false;
    helper.material.fog = false;
    helper.material.transparent = true;
    helper.material.opacity = isHover ? .65 : 1;
    helper.renderOrder = isHover ? 11 : 10;
    helper.userData.selectionKey = `${buildingId ?? ''}:${id}`;
    Object.assign(helper.userData, { pieceId: id, kind: pick.kind ?? entry.kind ?? null, buildingId, isHover, fallbackBox });
    scene.add(helper);
    selectionLines.push(helper);
  }
  function paintHover() {
    for (let i = selectionLines.length - 1; i >= 0; i--) {
      const line = selectionLines[i];
      if (!line.userData.isHover) continue;
      line.removeFromParent(); line.geometry.dispose(); line.material.dispose(); selectionLines.splice(i, 1);
    }
    if (twin) outline(selectionStyle?.hover, true, { single: true });
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
  function pickIntersections(clientX, clientY, { skip = [], water = false } = {}) {
    if (!twin) return { hits: [], waterHits: [] };
    const rect = renderer3.domElement.getBoundingClientRect();
    if (clientX < rect.left || clientX >= rect.right || clientY < rect.top || clientY >= rect.bottom) return { hits: [], waterHits: [] };
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
    // Water uses the existing drawn geometry, retained through yard batching.
    // It has no structural proxy and adds no selection mesh or draw call. Only a
    // caller that asks gets a water hit, so every other tool still sees open ground.
    const waterHits = [];
    if (water && yardGroup && visible(yardGroup)) for (const object of yardGroup.userData.waterSurfaces || []) {
      object.matrixWorld.multiplyMatrices(yardGroup.matrixWorld, object.matrix);
      object.raycast(raycaster, waterHits);
    }
    waterHits.sort((a, b) => a.distance - b.distance);
    return { hits, waterHits };
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
  // A room under its roof sees a fraction of the sky. At the yard's full share
  // it sits as bright as the lawn and a window reads as nothing. Lifting the
  // roof away (a floor view, the editor's level buttons) gives the sky back.
  const INDOOR_SKY = .3, INDOOR = new Set(['interior_wall', 'floor', 'ceiling']);
  let indoorSky = null;
  function applyIndoorSky() {
    if (!twin || !settings.shadows) return;
    // The meshes are found once a build; their materials are read each frame,
    // because the bake and the level fades swap in copies of their own.
    indoorSky ??= Object.values(twin.groups.levels).map(group => {
      const meshes = [];
      group.traverse(o => { if ([].concat(o.material || []).some(m => INDOOR.has(m.name))) meshes.push(o); });
      return { id: group.userData.buildingId, meshes };
    });
    const map = state.unlit ? null : environment;
    for (const { id, meshes } of indoorSky) {
      const roofed = viewing ? viewing.roofAlpha(id) : +twin.groups.roof.visible;
      const share = (timeLook?.environment ?? 0) * (1 + (INDOOR_SKY - 1) * roofed);
      for (const mesh of meshes) for (const m of [].concat(mesh.material)) if (INDOOR.has(m.name)) { m.envMap = map; m.envMapIntensity = share; }
    }
  }
  function render() {
    if (disposed) return;
    if (compiling && performance.now() - holdSince < HOLD_MS) return;
    // The live keeper can replace its layer. Read its current snapshot, without another stream.
    const weather=currentWeather();
    if (weatherLightingKey(weather) !== lastWeather) applyTimeLook();
    else view.weather=weather;
    const flash=clouds.flash(performance.now()/1000,{enabled:(!editor||state.liveWeather||!!state.weatherPreview)&&!state.unlit,
      centre:cloudCentre});
    // Reuse the one existing hemisphere light. No lit-material uniform, light
    // count, program key or device/lamp state changes for a flash.
    ambient.intensity=state.unlit?0:(timeLook?.ambient ?? 1.8)+1.5*flash;
    cloudShadow.frame(performance.now()/1000);
    if(timeLook)timeLook.sun=timeLook.sunClear*cloudShadow.centre();
    viewing?.update(performance.now());
    applyIndoorSky();
    view.levels?.draw();
    view.cars?.draw();
    // Effect water is unlit: it follows the sun down to a night floor.
    if (twin?.effects) twin.effects.update(view.live?.peek?.() || {}, view.live?.stale?.() ?? true, performance.now() / 1000,
      .18 + .82 * Math.min(1, (timeLook?.sunClear ?? 3) / 3));
    yardGroup?.userData.water?.update(twin?.effects?.fixtures || [], performance.now() / 1000, {
      renderer: renderer3, camera, sun: timeLook?.sunClear ?? 3,
      sunDirection: sun.position.clone().sub(sun.target.position).normalize(),
    });
    yardGroup?.userData.grass?.update(performance.now() / 1000,view.weather,site.front_bearing_deg ?? 180,camera);
    const weatherNow = performance.now() / 1000;
    const roofState = roofWater.update(view.weather, weatherNow);
    weatherSurface.update(view.weather, weatherNow, roofState);
    if(precipitationPlan!==plan || precipitationRoofs!==twin?.roofSurfaces || precipitationCover!==twin?.skyCover){
      seasonTouches.setPlan(plan,twin?.roofSurfaces,twin?.skyCover);
      precipitation.setPlan(plan,twin?.roofSurfaces,twin?.skyCover);precipitationPlan=plan;precipitationRoofs=twin?.roofSurfaces;precipitationCover=twin?.skyCover;
    }
    splashSunDirection.copy(sun.position).sub(sun.target.position).normalize();
    splashSunColour.copy(sun.color).multiplyScalar(sun.intensity);
    // A focused yard room is outdoors with every roof in view (levels.js never
    // cuts the house for it), so weather treats it like the whole-house view.
    const levelSnap=view.levels?.snapshot();
    const weatherLevel=levelSnap ? (levelSnap.level==='room'&&levelSnap.building==null ? 'house' : levelSnap.level)
      : (state.view==='ext'?'house':'floor');
    precipitation.update(performance.now()/1000,view.weather,camera,{target:controls.target,bearing:site.front_bearing_deg ?? 180,
      level:weatherLevel,unlit:state.unlit,colour:timeLook?.skyColor,
      light:leafLight(),sunDirection:splashSunDirection,sunColour:splashSunColour,
      sunVisibility:timeLook?.sunClear>0?sunDiscVisibility(view.weather,timeLook.sun/timeLook.sunClear):0});
    // Eave runoff follows the roof's own drying ladder (roof_water.js), so the
    // streams thin to drips and stop as the roof drains after the rain.
    runoff.flow=eaveRunoff(roofState);runoff.wet=roofState.wet;
    if(eavePlan!==plan||eaveRoofs!==twin?.roofSurfaces||eaveGutters!==twin?.gutters){
      // Optional HA absence and a dry neutral editor allocate no water mesh.
      // Once rain needs it, build once for this immutable roof snapshot.
      if(runoff.flow>.002&&runoff.wet>0){eaves.setPlan(plan,twin?.roofSurfaces,kit,twin?.gutters);eavePlan=plan;eaveRoofs=twin?.roofSurfaces;eaveGutters=twin?.gutters;}
      else if(eavePlan){eaves.setPlan({});eavePlan=null;eaveRoofs=null;eaveGutters=null;}
    }
    eaves.update(runoff,performance.now()/1000,{camera,target:controls.target,
      level:weatherLevel,unlit:state.unlit,neutral:view.weather?.neutral,
      fog:weatherExtinction(view.weather),light:leafLight(),lamps:eaveLamps,
      viewportHeight:renderer3.domElement.height||el.clientHeight||720});
    const touchEnabled=(!editor||state.liveWeather)&&!state.unlit&&state.view==='ext'&&(!view.levels||weatherLevel==='house');
    const sunDir=sun.position.clone().sub(sun.target.position).normalize().toArray();
    const sunAltDeg=Math.asin(Math.max(-1,Math.min(1,sunDir[1])))*180/Math.PI;
    seasonTouches.update(performance.now()/1000,view.season,view.weather,camera,{target:controls.target,plants:yardGroup,
      date:clockNow(),sunAltDeg,enabled:touchEnabled,lawn:yardGroup?.userData.grass?.growsGrass ?? false,bearing:site.front_bearing_deg ?? 180,
      light:leafLight()});
    post?.setSun({sunDir,sunAltDeg,enabled:touchEnabled,transmittance:1-weatherHaze(view.weather)});
    view.live?.draw();
    twin?.updateGhosts();
    pieceVisibility?.enforce(scene);
    if (state.unlit) {
      unlit.apply(twin?.root);
      // Skip the entire shadow pass, including an invalidation from a rebuild.
      renderer3.shadowMap.needsUpdate = false; sun.shadow.needsUpdate = false;
    }
    renderer3.info.reset();
    startEnvironmentFrame(scene);
    plantWind.update(performance.now()/1000,view.weather,site.front_bearing_deg ?? 180);
    seasons.update(view.season);
    // three recomputes every object's world matrix at the start of each render
    // call; a frame makes five or more (mirror, AO, beauty, transparent, shadow
    // faces) and nothing moves between them. Owner trace 2026-11-20: 13% of the
    // frame. Compute once here; the passes reuse it.
    scene.updateMatrixWorld();
    const matrixAuto = scene.matrixWorldAutoUpdate;
    scene.matrixWorldAutoUpdate = false;
    let picture;
    try {
      // The pool's mirror image belongs to this frame's camera.
      if (!state.unlit) {
        const background=scene.background;
        try {scene.background=sky.cube;reflections.mirror(camera);}
        finally {scene.background=background;}
      }
      post?.setCamera(camera);
      // Count only the beauty pass: AO depth and fullscreen draws are extra work,
      // not extra house geometry. createPost snapshots the RenderPass counters.
      if (post && !state.unlit) picture = post.render();
      else { renderer3.render(scene, camera); picture = renderer3.info.render; }
    } finally { scene.matrixWorldAutoUpdate = matrixAuto; }
    lastStats = { drawCalls: picture.calls, triangles: picture.triangles, tier, fps };
    if (editFrames.size) {
      let meshes = 0;
      twin?.root.traverse(object => { if (object.isMesh) ++meshes; });
      const stats = { meshes, draw_calls: lastStats.drawCalls, triangles: lastStats.triangles };
      const waiting = [...editFrames]; editFrames.clear();
      requestAnimationFrame(() => waiting.forEach(resolve => resolve(stats)));
    }
  }
  // Irradiance on a leaf card, scene-linear: hemisphere sky plus a little over half of
  // the sun and moon (a tumbling card faces them at random), over pi as for Lambert.
  const leafScratch = new THREE.Color(), leafIrradiance = [0,0,0];
  const splashSunDirection = new THREE.Vector3(), splashSunColour = new THREE.Color();
  function leafLight() {
    leafScratch.copy(ambient.color).multiplyScalar(ambient.intensity);
    leafScratch.r += (sun.color.r * sun.intensity + moon.color.r * moon.intensity) * .6;
    leafScratch.g += (sun.color.g * sun.intensity + moon.color.g * moon.intensity) * .6;
    leafScratch.b += (sun.color.b * sun.intensity + moon.color.b * moon.intensity) * .6;
    leafIrradiance[0]=leafScratch.r/Math.PI;leafIrradiance[1]=leafScratch.g/Math.PI;leafIrradiance[2]=leafScratch.b/Math.PI;
    return leafIrradiance;
  }
  function resize() {
    const width = Math.max(1, el.clientWidth), height = Math.max(1, el.clientHeight);
    renderer3.setSize(width, height);
    post?.setSize(width, height, renderer3.getPixelRatio());
    perspective.aspect = width / height; perspective.updateProjectionMatrix();
    orthographic.left = -orthographic.top * width / height; orthographic.right = -orthographic.left;
    orthographic.updateProjectionMatrix();
    render();
  }
  const observer = new ResizeObserver(resize); observer.observe(el);
  const view = {
    ready: false, scene, post, clouds, cloudShadow, weatherSurface, roofWater, precipitation, eaves, seasonTouches, emitterGain: post ? EMITTER_GAIN : 1, renderer: rendererName(renderer3.getContext()), renderer3, camera, controls, state, tier,
    groups: null, roomLights: [], plan, round,
    weather:neutralWeather(), season:seasonState(clockNow(),resolveSite(site,clockNow()).lat,{}, {neutral:editor}), seasons,
    refreshWeather:()=>weatherPoll?.refresh(),
    weatherChanged:id=>weatherPoll?.changed(id),
    setWeatherPreview(name) { weatherPreview.set(name);resetPreviewIdle(); },
    setSeasonPreview(name) { seasonPreview.set(name);resetPreviewIdle(); },
    setLiveWeather(on) { state.liveWeather=!!on; updateTime(false,true); },
    setWeatherEntity(entity) {
      entity ||= null;
      if(weatherEntity===entity)return;
      weatherEntity=entity; weatherPoll?.refresh(); updateTime();
    },
    get nightBrightness() { return nightBrightness; },
    setNightBrightness(value, { persist = true, commit = false } = {}) {
      const next = clampNightBrightness(value);
      nightBrightness = persist ? writeNightBrightness(next) : next;
      applyTimeLook(false, false, !commit);
      applyLights();
      if (commit) reflections.request();
      render();
      el.dispatchEvent(new CustomEvent('twintimechange', { detail: state.time }));
      return nightBrightness;
    },
    get stage() { return stageForPlan(plan); },
    get timeHour() {
      if (state.time === 'scrub') return state.previewHour;
      if (state.time === 'day') return 12;
      if (state.time === 'night') return 23;
      const now = clockNow(), located = resolveSite(site, now);
      try {
        if (located.timezone) {
          const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone:located.timezone,
            hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).formatToParts(now).map(p => [p.type,p.value]));
          return +parts.hour + +parts.minute/60;
        }
      } catch { /* Use the same longitude clock as previewDate. */ }
      const local = new Date(+now + located.lon/15*3600000);
      return local.getUTCHours() + local.getUTCMinutes()/60;
    },
    get effects() { return twin?.effects; },
    viewingState() {
      return viewing?.snapshot() || {selected: state.view, pinned: state.view === 'ext' ? null : state.view, channels: []};
    },
    // Visualizations hide with the geometry they are tied to (user, 2026-11-13): a floor or a
    // building's roof counts as shown while it is more than half faded in.
    levelShown(key) { return !viewing || viewing.levelAlpha(key) > .5; },
    roofShown(id) { return !viewing || viewing.roofAlpha(id) > .5; },
    get site() { return site; },
    get materialManifest() { return manifest(kit); },
    async refreshMaterials(ids) {
      while (rebuildWork) await rebuildWork;
      if (disposed || !twin) return;
      const known = manifest(kit), caches = [twin.materials, yardGroup?.userData.materials].filter(Boolean);
      const changed = [...new Set(caches.flatMap(cache => [...cache.values()]))]
        .filter(m => ids.includes(m.userData.materialId) && !currentMaterial(m, known));
      // Vegetation is geometry. Reuse the watcher's existing rebuild path when
      // the lawn's switch changes, before acknowledging its new revision.
      if (TIERS[tier].lawnBlades && yardGroup?.userData.grass && changed.some(m =>
        m.userData.materialRole === 'lawn' && grassLawn({ materials: { lawn: m.userData.materialRef }, manifest: known })
          !== yardGroup.userData.grass.growsGrass)) {
        await view.rebuild(plan); return;
      }
      // A deleted catalogue entry needs fallback geometry. Refresh surviving ids
      // first so one missing record cannot abort the rest of this batch.
      const needsRebuild = changed.some(m => !known[m.userData.materialId]);
      const materials = changed.filter(m => known[m.userData.materialId]);
      if (!materials.length) {
        if (needsRebuild) await view.rebuild(plan);
        return;
      }
      for (const m of materials) if (!m.userData.materialRef
        || m.userData.alphaMode !== alphaModeOf(known[m.userData.materialId], m.userData.materialRef)) {
        console.warn('Material refresh requires a geometry rebuild:', m.userData.materialId, 'missing reference or changed alpha/cutout pattern or mode');
        await view.rebuild(plan); return;
      }
      // random_offset lives in surface geometry (offsetSurfaceUvs), so turning it on or
      // off regenerates the buildings and yard parts that use the material.
      if (materials.some(m => !!known[m.userData.materialId]?.params?.random_offset !== !!m.userData.randomOffset)) {
        await view.rebuild(plan); return;
      }
      const syncStyled = (source, target) => {
        if (Array.isArray(source)) { source.forEach((m, i) => syncStyled(m, target[i])); return; }
        if (!ids.includes(source.userData.materialId)) return;
        copyMaterialParams(source, target);
        if (source.userData.waterSurface) { target.transparent = true; target.depthWrite = false; }
        if (target.userData.selectionTint !== undefined) target.color.lerp(new THREE.Color(target.userData.selectionTint), .32);
      };
      const sync = source => {
        if (disposed) return;
        reflections.request();
        view.prepareViewingMaterial(source);
        for (const [object, original] of faded) syncStyled(original, object.material);
        for (const [object, original] of selectedMaterials) syncStyled(original, object.material);
        view.bake?.refreshMaterials([source.userData.materialId]);
        render();
      };
      for (const material of materials) {
        if (!materialBindings.has(material)) {
          const changed = () => sync(material);
          const release = () => { material.removeEventListener('materialparamschange', changed); material.removeEventListener('dispose', release); materialBindings.delete(material); };
          material.addEventListener('materialparamschange', changed); material.addEventListener('dispose', release);
          materialBindings.set(material, release);
        }
        applyMaterialParams(material, known[material.userData.materialId], material.userData.materialRef,
          material.userData.materialRole || material.name, tier);
        sync(material);
      }
      // Revision-bearing slot/yard cache keys must follow the retained instance.
      for (const cache of caches) for (const [key, material] of [...cache]) if (materials.includes(material) && key.startsWith('["m",')) {
        const parts = JSON.parse(key); parts[2] = material.userData.materialRevision;
        cache.delete(key); cache.set(JSON.stringify(parts), material);
      }
      if (yardGroup) Object.assign(yardGroup.userData, { yardKey: yardKey(plan, kit, tier, { viewing: !editor, stage:stageForPlan(plan) }),
        yardMaterialKey: yardMaterialKey(plan, kit, tier), yardPartKeys: yardPartKeys(plan, kit, tier, { viewing: !editor, stage:stageForPlan(plan) }) });
      view.bake?.materialsChanged([...new Set(materials.map(m => m.userData.materialId))]);
      await Promise.all(materials.map(m => m.userData.ready));
      materials.forEach(sync);
      if (needsRebuild) await view.rebuild(plan);
    },
    get roofSurfaces() { return twin?.roofSurfaces; },
    render,
    reflectionsChanged: reason => reason === 'lamp' ? reflections.requestLamp() : reflections.request(),
    setHiddenPieces(ids, kinds) {
      if (!pieceVisibility) return;
      pieceVisibility.set(ids, kinds);
      pieceVisibility.apply(scene);
      invalidateSelectionBounds();
      sun.shadow.needsUpdate = true; reflections.request(); render();
    },
    isPieceHidden: candidate => pieceVisibility?.hidden(candidate) || false,
    // A warm-up for a change not yet on screen: the picture keeps drawing.
    compileBehind: () => compileFor ? compileBehind(scene, camera) : null,
    prepareViewingMaterial(source, material) { if (material) viewing?.adopt(source, material); else viewing?.refresh(source); },
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
      state.weatherPreview=weatherPreview.get()?.preview || null;
      state.seasonPreview=seasonPreview.get();
      // Restoring a camera is a framing change, not an outward zoom gesture.
      viewing?.rebasePin();
      camera.zoom = saved.zoom; controls.update(); camera.quaternion.copy(saved.quaternion); camera.updateProjectionMatrix(); render();
    },
    screenOfFloor: projectFloor,
    selectionFloor() { const room = selectionStyle?.room; return room ? `${room.building}:${room.level}` : state.view; },
    selectionBounds() { return projectSelectionBoxes(currentSelectionBoxes({ fresh: true }).list, camera, renderer3.domElement.getBoundingClientRect()); },
    selectionWorldBounds() { return currentSelectionBoxes().list.map(row => ({ ...row, box: row.box.clone() })); },
    get selectionBoundsRevision() { return selectionBoundsRevision; },
    refreshSelection() {
      invalidateSelectionBounds();
      if (selectionStyle) paintSelection();
    },
    previewSelectionBox(id, spec = null) {
      if (!id) {
        let restored = false;
        for (const line of selectionLines) {
          if (line.userData.groupBase) {
            const base = line.userData.groupBase;
            line.matrix.copy(base.matrix); line.matrixAutoUpdate = base.auto;
            if (base.box) line.box.copy(base.box);
            delete line.userData.groupBase; restored = true;
          }
          if (line instanceof THREE.Box3Helper && line.userData.baseBox) {
            line.box.copy(line.userData.baseBox);
            delete line.userData.baseBox;
            restored = true;
          }
        }
        if (restored) render();
        return;
      }
      const helper = selectionLines.find(l => l instanceof THREE.Box3Helper && !l.userData.isHover && l.userData.pieceId === id && !l.userData.buildingId);
      if (!helper) return;
      helper.userData.baseBox ||= helper.box.clone();
      if (spec?.delta && !helper.userData.fallbackBox) {
        helper.box.copy(helper.userData.baseBox).translate(new THREE.Vector3(...spec.delta));
      } else if (spec?.box) {
        helper.box.copy(spec.box);
      }
      render();
    },
    previewSelectionGroup(specs) {
      const members = new Map(specs.map(r => [JSON.stringify([r.buildingId ?? null, r.pieceId]), r.matrix]));
      for (const line of selectionLines) {
        const matrix = members.get(JSON.stringify([line.userData.buildingId ?? null, line.userData.pieceId]));
        if (line.userData.isHover || !matrix) continue;
        if (!line.userData.groupBase) {
          line.updateWorldMatrix(true, false);
          line.userData.groupBase = { matrix: line.matrix.clone(), world: line.matrixWorld.clone(), auto: line.matrixAutoUpdate,
            ...(line instanceof THREE.Box3Helper ? { box: line.box.clone() } : {}) };
        }
        const base = line.userData.groupBase;
        if (base.box) line.box.copy(base.box).applyMatrix4(matrix);
        else {
          line.matrixAutoUpdate = false;
          line.matrix.copy(line.parent.matrixWorld).invert().multiply(matrix).multiply(base.world);
          line.matrixWorldNeedsUpdate = true;
        }
      }
      if (!view.looping) render();
    },
    setSelection(value) {
      const sameMaterials = selectionStyle && JSON.stringify([selectionStyle.selected, selectionStyle.members, selectionStyle.room])
        === JSON.stringify([value.selected, value.members, value.room]);
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
    pickAll(clientX, clientY, options = {}) {
      const { hits, waterHits } = pickIntersections(clientX, clientY, options), seen = new Set();
      return [...hits, ...waterHits].sort((a, b) => a.distance - b.distance).flatMap(hit => {
        const { kind, pieceId, buildingId = null, part } = hit.object.userData;
        const key = JSON.stringify([buildingId, pieceId]); if (seen.has(key)) return [];
        seen.add(key);
        let level = null;
        for (let p = hit.object; p; p = p.parent) if (p.userData.levelKey) { level = p.userData.levelKey.slice(buildingId.length + 1); break; }
        return [{ kind, id: pieceId, building: buildingId, pieceId, buildingId, level, distance: hit.distance, part, point: hit.point.toArray() }];
      });
    },
    pick(clientX, clientY, { skip = [], water = false } = {}) {
      const { hits, waterHits } = pickIntersections(clientX, clientY, { skip, water });
      let hit = state.camera === 'top' ? hits.find(h => h.object.userData.kind === 'wall') || hits[0] : hits[0];
      if (waterHits[0] && (!hit || waterHits[0].distance < hit.distance)) {
        const water = waterHits[0], { kind, pieceId, part } = water.object.userData;
        return { kind, id: pieceId, pieceId, part, point: water.point.toArray() };
      }
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
      // A single proxy still selects the whole object. Refine its hit against
      // the original part meshes, whose CPU geometry survives static batching.
      const partHits = [];
      for (const { object, group } of hit.object.userData.partObjects || []) {
        if (!visible(group) || viewing?.faded(group)) continue;
        object.matrixWorld.multiplyMatrices(group.matrixWorld, object.matrix);
        object.raycast(raycaster, partHits);
      }
      partHits.sort((a, b) => a.distance - b.distance);
      const exact = partHits.find(h => !viewing || h.point.y <= viewing.cutAt(h.object) + .02);
      const proxy = hit.object;
      if (exact) hit = exact;
      const { pieceId, kind, buildingId, part } = hit.object.userData;
      let level = null;
      for (let p = proxy; p; p = p.parent) if (p.userData.levelKey) { level = p.userData.levelKey.slice(buildingId.length + 1); break; }
      return { kind, id: pieceId, building: buildingId, level, pieceId, buildingId, part, point: hit.point.toArray() };
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
        const clone = m => { const next = m.clone(); next.userData.styledFade = true; next.transparent = true; next.opacity = 0.18; next.depthWrite = false; scaleStyledFadeAlpha(m, next); return next; };
        object.material = Array.isArray(object.material) ? object.material.map(clone) : clone(object.material);
      });
      const buildings = new Set(Object.values(twin.groups.levels).filter(g => g.visible).map(g => g.userData.buildingId));
      for (const domain of ['roof', 'gableFull', 'gableCut']) for (const group of twin.groups[domain].children) group.visible = buildings.has(group.userData.buildingId);
      sun.shadow.needsUpdate = true;
      invalidateSelectionBounds();
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
        const material = new THREE.MeshBasicMaterial({ fog: false, name: 'sheet', map: texture, transparent: true, opacity: spec.opacity ?? 0.6, depthWrite: false, side: THREE.DoubleSide });
        const object = new THREE.Mesh(geometry, material);
        Object.assign(object.userData, { pieceId: `${building.id}:sheet:${level.id}`, kind: 'sheet', noOcclusion: true, buildingId: building.id });
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
      invalidateSelectionBounds();
      applyLights(); paintSelection(); render();
    },
    setTime(time) {
      // Idle restores the saved state before asking to reapply its clock look.
      if (time === 'scrub' && Number.isFinite(state.previewHour)) return view.scrubTime(state.previewHour, {commit:true});
      if (!['now', 'day', 'night'].includes(time)) return;
      const moved = state.time !== time;
      state.time = time;
      if(time==='now' && state.weatherPreview)weatherPreview.set(null);
      if(time==='now' && state.seasonPreview)seasonPreview.set(null);
      state.previewHour = null;
      resetPreviewIdle(); updateTime(moved);
    },
    scrubTime(hour, {commit = false} = {}) {
      if (!Number.isFinite(hour)) return;
      state.time = 'scrub';
      state.previewHour = Math.round(Math.max(0, Math.min(24, hour)) * 12) / 12;
      resetPreviewIdle();
      if (commit) updateTime(true, true);
      else {
        applyTimeLook(false, true, true); render();
        el.dispatchEvent(new CustomEvent('twintimechange', {detail:state.time}));
      }
    },
    setMirrorStillHz(hz) { reflections.setMirrorStillHz(hz); render(); },
    setProbeCloudSeconds(seconds) { reflections.setProbeCloudSeconds(seconds); },
    async setStage(next) {
      if (next?.mirror_still_hz !== undefined) reflections.setMirrorStillHz(next.mirror_still_hz);
      if (next?.probe_cloud_s !== undefined) reflections.setProbeCloudSeconds(next.probe_cloud_s);
      if (!next || !Number.isFinite(next.radius) || next.radius < 30 || next.radius > 1000) return;
      const radius = next.radius_override === undefined ? next.radius : next.radius_override;
      if (radius !== null && (!Number.isFinite(radius) || radius < 30 || radius > 1000)) return;
      const before = JSON.stringify(stageForPlan(plan));
      stageOverride = radius;
      syncStage(plan);
      if (before !== JSON.stringify(stageForPlan(plan))) await view.rebuild(plan);
    },
    setUnlit(on) {
      on = !!on;
      if (state.unlit === on) return;
      unlit.restore();
      state.unlit = on;
      reflections.setUnlit(on);
      if (on) {
        shadowAutoUpdate = renderer3.shadowMap.autoUpdate;
        renderer3.shadowMap.autoUpdate = false;
        view.bake?.stop();
      } else {
        renderer3.shadowMap.autoUpdate = shadowAutoUpdate;
        sun.shadow.needsUpdate = true;
      }
      updateTime();
      if ((!on || editor) && twin) startBake();
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
      reflections.request();
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
        // Read the canvas after the same output transform as the screen.
        // Render and read synchronously, before the drawing buffer is cleared.
        renderer3.setRenderTarget(null);
        renderer3.setPixelRatio(1); renderer3.setSize(width, height, false);
        post?.setSize(width, height, 1);
        for (const name of names) {
          view.setCamera(name);
          camera.aspect = width / height; camera.updateProjectionMatrix();
          render(); out.push(renderer3.domElement.toDataURL('image/png'));
        }
        return out;
      } finally {
        renderer3.setPixelRatio(previous.pixelRatio); renderer3.setSize(previous.size.x, previous.size.y, false);
        post?.setSize(previous.size.x, previous.size.y, previous.pixelRatio);
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
    rebuildLevel(buildingId, levelId, flat, touched = null, { keep = false } = {}) {
      const key = `${buildingId}:${levelId}`, group = twin?.groups.levels[key];
      const before = plan.buildings.find(b => b.id === buildingId), after = flat.buildings.find(b => b.id === buildingId);
      if (!group || !before || !after) return;
      pieceVisibility?.restore();
      // A drag preview is reversible. Its detached bake keeps the authored plan
      // and waits on the gesture; committing it calls syncBake below.
      if (!editor || keep) view.bake?.stop();
      // Focused levels have per-piece meshes (R42); unfocused levels retain
      // material batches. Both update only owned geometry, without changing focus.
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
          const ranges = object.userData.snapRanges;
          const owned = ranges?.filter(r => r.pieceId === id && r.buildingId === buildingId);
          if (ranges && !owned.length) continue;
          // A batch without ownership metadata cannot safely move as a whole.
          // The pick proxy and explicitly tagged single-piece meshes are safe.
          if (!ranges && (object.userData.merged || twin.editableLevel !== key && object !== proxy
              && (object.userData.pieceId !== id || object.userData.buildingId !== buildingId))) continue;
          // Bounds for batches stay conservative during a gesture. Scan the
          // complete buffer only once, then expand them from the changed ranges.
          if (owned && !geometry.boundingBox) geometry.computeBoundingBox();
          if (room && object !== proxy && object.isMesh) {
            const level = after.levels.find(l => l.id === levelId);
            const holes = stairHoles(after, level).filter(h => h.every(p => contains(room.polygon, p)));
            if (ranges) {
              // Unfocused levels batch several pieces into one buffer. Replace
              // only this room's ranges, preserving the other pieces and calls.
              const chunks = ranges.map(r => {
                if (!owned.includes(r)) return null;
                let min = Infinity, max = -Infinity;
                for (let i = r.start; i < r.start + r.count; i++) {
                  const y = geometry.attributes.position.getY(i); min = Math.min(min, y); max = Math.max(max, y);
                }
                // Rotating a flat floor into X/Z leaves sub-micron Y noise;
                // keep it flat instead of adding extrusion faces each frame.
                const poly = polygon(room.polygon, min, max - min < 1e-6 ? min : max, holes);
                if (!poly.index) return poly;
                const triangles = poly.toNonIndexed(); poly.dispose(); return triangles;
              });
              const sameCounts = chunks.every((g, i) => !g || g.attributes.position.count === ranges[i].count);
              if (sameCounts) {
                // Most drag frames keep the triangulation size: reuse every
                // attribute array and upload only this room's changed ranges.
                for (const [name, attribute] of Object.entries(geometry.attributes)) {
                  chunks.forEach((chunk, index) => {
                    if (!chunk) return;
                    const r = ranges[index], source = chunk.attributes[name];
                    for (let i = 0; i < r.count; i++) for (let c = 0; c < attribute.itemSize; c++)
                      attribute.setComponent(r.start + i, c, source ? source.getComponent(i, c) : 0);
                    attribute.addUpdateRange(r.start * attribute.itemSize, r.count * attribute.itemSize);
                  });
                  attribute.needsUpdate = true;
                }
              } else {
                const replacement = new THREE.BufferGeometry();
                for (const [name, attribute] of Object.entries(geometry.attributes)) {
                  const values = [];
                  ranges.forEach((r, index) => {
                    const chunk = chunks[index], attr = chunk?.attributes[name] || attribute;
                    const start = chunk ? 0 : r.start, count = chunk ? chunk.attributes.position.count : r.count;
                    for (let i = start; i < start + count; i++) for (let c = 0; c < attribute.itemSize; c++)
                      values.push(chunk && !chunk.attributes[name] ? 0 : attr.getComponent(i, c));
                  });
                  replacement.setAttribute(name, new THREE.Float32BufferAttribute(values, attribute.itemSize));
                }
                let start = 0;
                ranges.forEach((r, i) => { r.start = start; r.count = chunks[i]?.attributes.position.count ?? r.count; start += r.count; });
                replacement.userData = { ...geometry.userData, snapRanges: ranges };
                replacement.boundingBox = geometry.boundingBox.clone();
                object.geometry = replacement;
              }
              chunks.forEach(g => g?.dispose());
            } else {
              geometry.computeBoundingBox();
              object.geometry = polygon(room.polygon, geometry.boundingBox.min.y, geometry.boundingBox.max.y, holes);
            }
            if (geometry !== object.geometry) geometry.dispose();
            geometry = object.geometry;
          } else {
            const positions = geometry.attributes.position;
            for (const range of owned || [{ start: 0, count: positions.count }]) {
              for (let i = range.start; i < range.start + range.count; i++) {
                const p = deform(positions.getX(i), -positions.getZ(i), positions.getY(i));
                positions.setXYZ(i, p[0], p[2], -p[1]);
              }
              if (owned) positions.addUpdateRange(range.start * 3, range.count * 3);
            }
            positions.needsUpdate = true;
            if (owned) {
              // snapRanges describe non-indexed triangles. Recompute only
              // their normals, preserving every neighbour's attributes.
              const normal = geometry.attributes.normal;
              const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), n = new THREE.Vector3();
              for (const r of owned) {
                for (let i = r.start; i < r.start + r.count; i += 3) {
                  a.fromBufferAttribute(positions, i); b.fromBufferAttribute(positions, i + 1); c.fromBufferAttribute(positions, i + 2);
                  THREE.Triangle.getNormal(a, b, c, n);
                  for (let j = i; j < i + 3; j++) normal.setXYZ(j, n.x, n.y, n.z);
                }
                normal.addUpdateRange(r.start * 3, r.count * 3);
              }
              normal.needsUpdate = true;
            } else geometry.computeVertexNormals();
          }
          if (owned) {
            const point = new THREE.Vector3();
            for (const r of owned) for (let i = r.start; i < r.start + r.count; i++)
              geometry.boundingBox.expandByPoint(point.fromBufferAttribute(geometry.attributes.position, i));
            geometry.boundingBox.getBoundingSphere(geometry.boundingSphere ||= new THREE.Sphere());
          } else { geometry.computeBoundingBox(); geometry.computeBoundingSphere(); }
          if (object !== proxy) {
            if (owned) for (const r of owned) for (let i = r.start; i < r.start + r.count; i++)
              box.expandByPoint(new THREE.Vector3().fromBufferAttribute(geometry.attributes.position, i));
            else box.union(geometry.boundingBox);
          }
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
      refreshSlabCover(twin.root, flat, twin.roofSurfaces, buildingId);
      twin.skyCover = createSkyCover(flat, twin.roofSurfaces);
      writeWeatherOpen(twin.root, twin.skyCover);
      // A gesture deforms retained buffers in place; the next full rebuild
      // must regenerate this building from its final authoritative record.
      if (!keep && twin.buildings?.has(buildingId)) twin.buildings.get(buildingId).model.stale = true;
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
      pieceVisibility?.apply(scene);
      invalidateSelectionBounds();
      sun.shadow.needsUpdate = true; reflections.request(); render();
      el.dispatchEvent(new CustomEvent('twinlevelrebuilt', { detail: { buildingId, levelId } }));
    },
    async settle(nextPlan, { buildingId = null, levelId = null, touched = null, selection = null } = {}) {
      const beforePlan = plan, same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
      const previous = new Map((beforePlan.buildings || []).map(b => [b.id, b]));
      const onLevel = (b, list, id) => (b[list] || []).filter(p =>
        (p.level || b.walls?.find(w => w.id === (p.wall || p.host?.wall))?.level
          || b.rooms?.find(r => r.id === (p.host?.floor ?? p.host?.ceiling))?.level
          || b.roofs?.find(r => r.id === p.host?.roof)?.level
          || b.levels?.[0]?.id) === id);
      const ids = list => list.map(p => p.id).sort();
      const changed = [];
      let rebuild = previous.size !== (nextPlan.buildings || []).length || !same(beforePlan.materials, nextPlan.materials);
      for (const after of nextPlan.buildings || []) {
        const before = previous.get(after.id);
        if (!before || !same(ids(before.levels || []), ids(after.levels || []))) { rebuild = true; continue; }
        // Changes outside the deformable level records still need the complete
        // generator (roofs, placement, materials, fixtures, and so on).
        const fixed = b => Object.fromEntries(Object.entries(b).filter(([k]) => !['walls', 'rooms', 'openings', 'anchors', 'items', 'joints'].includes(k)));
        if (!same(fixed(before), fixed(after))) rebuild = true;
        for (const level of after.levels || []) {
          for (const list of ['walls', 'rooms', 'openings'])
            if (!same(ids(onLevel(before, list, level.id)), ids(onLevel(after, list, level.id)))) rebuild = true;
          const lists = ['walls', 'rooms', 'openings', 'anchors', 'items'];
          if (lists.some(list => !same(onLevel(before, list, level.id), onLevel(after, list, level.id))))
            changed.push({ buildingId: after.id, levelId: level.id });
        }
      }
      // Selection shapes from the scene tools and direct callers are both used.
      const selectedBuilding = selection?.buildingId ?? selection?.building ?? buildingId;
      const selectedId = selection?.pieceId ?? selection?.id;
      const oldWall = previous.get(selectedBuilding)?.walls?.find(w => w.id === selectedId);
      const newBuilding = nextPlan.buildings?.find(b => b.id === selectedBuilding);
      if (oldWall && !newBuilding?.walls?.some(w => w.id === selectedId)) {
        const midpoint = oldWall.from.map((v, i) => (v + oldWall.to[i]) / 2);
        const replacement = newBuilding?.walls?.find(w => {
          if (w.level !== oldWall.level) return false;
          const dx = w.to[0] - w.from[0], dy = w.to[1] - w.from[1], length2 = dx * dx + dy * dy;
          const t = length2 ? Math.max(0, Math.min(1, ((midpoint[0] - w.from[0]) * dx + (midpoint[1] - w.from[1]) * dy) / length2)) : 0;
          return Math.hypot(midpoint[0] - w.from[0] - t * dx, midpoint[1] - w.from[1] - t * dy) <= .05;
        });
        selection = replacement ? { ...selection, [selection.pieceId !== undefined ? 'pieceId' : 'id']: replacement.id } : null;
      }
      if (rebuild) {
        // rebuild owns the single bake restart on this path.
        await view.rebuild(nextPlan, { yardLater: true });
        return { path: 'rebuild', selection };
      }
      const version = ++revision;
      view.yardSettling = false; view.yardError = null;
      // Each level compares against the same shown plan; rebuildLevel updates
      // plan itself, so restore that baseline between synchronous deforms.
      for (const change of changed) {
        plan = beforePlan;
        const after = nextPlan.buildings.find(b => b.id === change.buildingId);
        // Hosts may move without changing a hosted record. Visit the level's
        // hosted pieces as well as the hinted ids; rebuildLevel skips equals.
        const hint = Object.fromEntries(['walls', 'rooms', 'openings', 'anchors', 'items'].map(list => [list,
          [...new Set([...(change.buildingId === buildingId && change.levelId === levelId ? touched?.[list] || [] : []),
            ...onLevel(after, list, change.levelId).map(p => p.id)])]]));
        view.rebuildLevel(change.buildingId, change.levelId, nextPlan, hint, { keep: true });
      }
      plan = nextPlan; view.plan = nextPlan; syncStage(plan);
      pieceVisibility?.apply(scene);
      invalidateSelectionBounds();
      view.ready = !disposed && !!twin;
      sun.shadow.needsUpdate = true; reflections.request();
      deferYard(nextPlan, version);
      startBake();
      return { path: 'deform', selection };
    },
    syncBake() { if (bakeSignature !== JSON.stringify(plan) || !view.bake?.active?.()) startBake(); },
    rebuild(nextPlan, { preserveYard = false, timing = null, yardLater = false, force = false } = {}) {
      const work = (async () => {
      const version = ++revision; view.ready = false;
      view.yardSettling = false; view.yardError = null;
      try {
      const detail = timing?.detail;
      const stopBake = editSpan(detail, 'bake_stop');
      view.bake?.stop();
      stopBake();
      pieceVisibility?.restore();
      let next;
      try { next = buildTwin(nextPlan, kit, tier, { showAnchors: !!view.showAnchors, editableLevel, viewing: !editor, previous: force ? null : twin, timing }); }
      finally { pieceVisibility?.apply(scene); }
      const reuseYard = !!yardGroup && (preserveYard || yardGroup.userData.yardKey === yardKey(nextPlan, kit, tier, { viewing: !editor, stage:stageForPlan(nextPlan) }));
      if (timing) timing.yard_reused = reuseYard;
      const yardMaterials = reuseYard || yardGroup?.userData.yardMaterialKey === yardMaterialKey(nextPlan, kit, tier)
        ? yardGroup?.userData.materials : new Map(yardGroup?.userData.materials);
      const keepMaterials = new Set([...(yardMaterials?.values() || []), ...(twin?.materials.values() || [])]);
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
              const buildingMaterials = next.buildings.get(building.id).model.materials;
              const material = buildingMaterials.get(ghost ? 'ghost#38bdf8' : 'floor');
              const objects = [];
              const add = geometry => {
                const mesh = new THREE.Mesh(geometry, material);
                Object.assign(mesh.userData, data, { pieceObjects: objects }); renderGroup.add(mesh); objects.push(mesh);
                if (ghost) {
                  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), buildingMaterials.get('ghostEdges'));
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
              const proxy = new THREE.Mesh(geometry.clone(), buildingMaterials.get('pick'));
              Object.assign(proxy.userData, data); proxy.layers.set(PICK_LAYER); group.add(proxy); next.pickObjects.set(key, proxy);
            }
          }
        }
        const stopBatch = editSpan(detail, 'batch');
        for (const [parent, group] of extras) mergeStatic(group, { perPiece: !!editableLevel && parent.userData.levelKey === editableLevel });
        stopBatch();
        if (!reuseYard && !yardLater) {
          const stopYard = editSpan(detail, 'yard');
          const yard = await buildYard(nextPlan, kit, tier, { viewing: !editor, stage:stageForPlan(nextPlan), materials: yardMaterials, timing: detail, previous: yardGroup, skyCover: next.skyCover }); next.groups.site.add(yard.group);
          stopYard();
          next.yardGroup = yard.group;
        }
        const stopAssets = editSpan(detail, 'assets');
        await next.ready;
        stopAssets();
      } catch (error) { release(next, keepMaterials); throw error; }
      if (disposed || version !== revision) { release(next, keepMaterials); return; }
      next.yardGroup?.userData.adoptParts?.();
      // Both caches now own exactly the resources surviving the accepted build.
      const keepAfter = new Set([...((next.yardGroup || yardGroup)?.userData.materials?.values() || []), ...next.materials.values()]);
      if (timing) {
        timing.yard_reused_parts = reuseYard ? Object.keys(yardGroup?.userData.yardPartKeys || {}) : next.yardGroup?.userData.yardReusedParts || [];
        timing.yard_rebuilt_parts = reuseYard ? [] : next.yardGroup?.userData.yardRebuiltParts || [];
      }
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
      next.adoptBuildings();
      sheet?.object?.removeFromParent();
      if (!next.yardGroup && yardGroup) {
        yardGroup.removeFromParent(); next.groups.site.add(yardGroup); next.yardGroup = yardGroup;
      }
      if (twin) { scene.remove(twin.root); release(twin, keepAfter); }
      stopDispose();
      yardGroup = next.yardGroup;
      twin = next; plan = nextPlan; scene.add(twin.root);
      freezeViewerMatrices(twin, {editor});
      // A roof edit can reuse the entire yard. Its cover still follows the
      // accepted building geometry, including furniture and pool features.
      if (yardGroup) writeWeatherOpen(yardGroup, twin.skyCover);
      // Read-only legacy property access for P0 embeds, never enumerable scene
      // keys and never a resolution when two buildings share the level name.
      view.groups = { ...twin.groups, levels: new Proxy(twin.groups.levels, { get(target, key) {
        if (typeof key !== 'string' || key in target) return target[key];
        const matches = Object.keys(target).filter(id => id.endsWith(':' + key));
        return matches.length === 1 ? target[matches[0]] : undefined;
      } }) };
      view.roomLights = twin.roomLights; view.plan = plan; syncStage(plan);
      // Register originals before unlit/viewing presentation swaps their materials.
      reflections.rebuild(plan, twin.root);
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
      // The filter is counted in texels: hold the soft edge near 5 cm on any lot.
      sun.shadow.radius = Math.min(4, Math.max(1, .05 / (2 * reach / sun.shadow.mapSize.x)));
      // Geometry invalidation is independent of the once-a-minute clock move.
      sun.shadow.needsUpdate = true; indoorSky = null;
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
      invalidateSelectionBounds();
      paintSelection();
      try { await viewing?.warm(); }
      finally { releaseViewing?.(); }
      if (disposed || version !== revision) return;
      view.ready = true;
      pieceVisibility?.apply(scene);
      reflections.request();
      if (yardLater && !reuseYard) deferYard(nextPlan, version, timing);
      startBake();
      el.dispatchEvent(new CustomEvent('twinrebuilt', { detail: view }));
      } finally { if (version === revision) view.ready = !disposed && !!twin; }
      })();
      rebuildWork = work;
      return work.finally(() => { if (rebuildWork === work) rebuildWork = null; });
    },
    dispose() {
      pieceVisibility?.restore();
      reflections.dispose();
      if (disposed) return;
      disposed = true; ++revision; view.ready = false;
      el.removeEventListener('twinyardrebuilt', redrawAfterYard);
      view.meter?.stop();
      view.materialWatcher?.stop();
      for (const release of [...materialBindings.values()]) release();
      view.levels?.stop();
      clearInterval(timeTimer); clearTimeout(previewIdle);
      weatherPoll?.stop(); weatherPreview.stop(); plantWind.dispose();
      seasonPreview.stop(); seasons.dispose();
      for (const name of ['pointerdown', 'pointermove', 'keydown', 'input']) document.removeEventListener(name, previewActivity);
      view.bake?.stop();
      view.live?.stop();
      view.idle?.stop(); view.glance?.stop(); view.glanceSettings?.stop();
      view.energySettings?.stop(); view.stageSettings?.stop(); view.weatherSettings?.stop(); view.timeScrub?.stop(); view.nightBrightnessControl?.stop();
      if (probeRun) {
        probeRun.reject(new Error('The twin was disposed during the probe.')); probeRun = null;
      }
      renderer3.setAnimationLoop(null); view.looping = false; observer.disconnect(); controls.dispose();
      view.editorCamera?.dispose();
      clearSheet(); sheetSpec = null;
      restoreSelection();
      restoreFloors();
      viewing?.dispose(); viewing = null;
      if (twin) { scene.remove(twin.root); release(twin); }
      unlit.dispose();
      seasonTouches.dispose(); eaves.dispose(); precipitation.dispose(); weatherSurface.dispose(); cloudShadow.dispose(); stageHaze.dispose(); sky.dispose(); sun.shadow.dispose();
      post?.dispose();
      clouds.dispose();
      renderer3.dispose(); renderer3.forceContextLoss(); renderer3.domElement.remove();
      if (window.__twin === view) delete window.__twin;
    },
  };
  function deferYard(nextPlan, version, timing = null) {
    // A task boundary lets the accepted house paint before synchronous yard
    // builders run. The complete old yard stays attached until adoption.
    view.yardSettling = true; view.yardError = null;
    setTimeout(async () => {
      try {
      if (disposed || version !== revision || yardGroup?.userData.yardKey === yardKey(nextPlan, kit, tier, { viewing: !editor, stage:stageForPlan(nextPlan) })) return;
      const previous = yardGroup, materials = new Map(previous?.userData.materials);
      const retained = () => new Set([...(twin?.materials.values() || []), ...(yardGroup?.userData.materials?.values() || [])]);
      let group;
      try {
        const stop = editSpan(timing?.detail, 'yard');
        try { ({ group } = await buildYard(nextPlan, kit, tier, { viewing: !editor, stage:stageForPlan(nextPlan), materials, timing: timing?.detail, previous, skyCover: twin?.skyCover })); }
        finally { stop(); }
        if (disposed || version !== revision) {
          const keep = retained(); group.userData.releasePlants?.(keep); disposeObject(group, { keepMaterials: keep }); return;
        }
        const selected = viewing?.snapshot().pinned;
        const releaseViewing = viewing?.dispose({ deferMaterials: true }); viewing = null;
        group.userData.adoptParts?.();
        twin.groups.site.add(group); twin.yardGroup = group; yardGroup = group;
        freezeViewerMatrices(twin, {editor});
        if (previous) {
          const keep = retained(); previous.removeFromParent();
          previous.userData.releasePlants?.(keep); disposeObject(previous, { keepMaterials: keep });
        }
        if (timing) {
          timing.yard_reused_parts = group.userData.yardReusedParts || [];
          timing.yard_rebuilt_parts = group.userData.yardRebuiltParts || [];
        }
        reflections.rebuild(plan, twin.root);
        if (!editor) {
          viewing = createViewing(view, twin, b => buildingGround(plan, b), key => {
            state.view = key; sun.shadow.needsUpdate = true; applyLights();
            el.dispatchEvent(new CustomEvent('twinviewchange', { detail: key }));
          }, { explicit: true });
          viewing.select(selected || 'ext');
        }
        releaseViewing?.();
        pieceVisibility?.apply(scene);
        invalidateSelectionBounds();
        sun.shadow.needsUpdate = true; reflections.request();
        if (selectionStyle) paintSelection(); else render();
        el.dispatchEvent(new CustomEvent('twinyardrebuilt', { detail: view }));
      } catch (error) { if (version === revision) view.yardError = error; el.dispatchEvent(new CustomEvent('twinerror', { detail: error })); }
      } finally { if (version === revision) view.yardSettling = false; }
    }, 0);
  }
  function release(model, keepMaterials = new Set()) {
    model.root.traverse(o => o.userData.releasePlants?.(keepMaterials));
    disposeObject(model.root, { keepMaterials });
    // Materials with no geometry (e.g. an empty polygon) still own requests.
    model.materials.forEach(m => { if (!keepMaterials.has(m)) m.dispose(); });
  }
  function applyTimeLook(moved = false, forceSky = false, cheap = false) {
    view.weather=currentWeather();lastWeather=weatherLightingKey(view.weather);
    const seasonNow=clockNow(),seasonSite=resolveSite(site,seasonNow);
    view.season=seasonState(seasonNow,seasonSite.lat,groundWeather,{neutral:editor&&!state.liveWeather,preview:seasonPreview.get()});
    seasons.update(view.season);
    stageHaze.set({enabled:!state.unlit,extinction:weatherExtinction(view.weather),sunAirVisibility:sunAirVisibility(view.weather)});
    cloudShadow.set({enabled:!state.unlit});
    sky.setEnabled(!state.unlit);
    if (state.unlit) {
      timeLook = lookAt(45);
      scene.background = new THREE.Color('#171e27');
      scene.environment = null; scene.environmentIntensity = 0;
      sun.intensity = moon.intensity = ambient.intensity = 0;
      renderer3.toneMappingExposure = 1;
      return;
    }
    const now = clockNow(), located = resolveSite(site, now), date = previewDate(now, state.time === 'scrub' ? state.previewHour : state.time, located);
    const solar = sunPosition(date, located.lat, located.lon), lunar = moonPosition(date, located.lat, located.lon);
    const illumination = moonIllumination(date), overcast = view.weather.clouds.coverage;
    const sunDir = modelDirection(solar.azimuth, solar.altitude, located.front_bearing_deg);
    const moonDir = modelDirection(lunar.azimuth, lunar.altitude, located.front_bearing_deg);
    const cloudWeather=view.weather.clouds,extinction=weatherExtinction(view.weather),fog=weatherHaze(view.weather),radianceInput={sunDir,moonDir,moonFraction:illumination.fraction,overcast,fog};
    stageHaze.set({fogColour:fogColour(radianceInput)});
    const cloudIrradiance=sampleSkyIrradiance(radianceInput);
    clouds.update(cloudWeather,{sunDir,moonDir,frontBearingDeg:located.front_bearing_deg,
      sunRadiance:transmittance([sunDir[0],Math.max(0,sunDir[1]),sunDir[2]]).map(v=>v*10),
      moonRadiance:transmittance(moonDir).map(v=>v*.02*illumination.fraction),
      ambientTop:cloudIrradiance.top,ambientBottom:cloudIrradiance.bottom,extinction,fogColour:fogColour(radianceInput)});
    cloudShadow.set({sunDir,moonDir});
    cloudShadow.frame(performance.now()/1000);
    const skyChanged = sky.update({sunDir, moonDir, moonPhase:illumination.phase, moonFraction:illumination.fraction,
      moonDistanceKm:lunar.distance, siderealTime:localSiderealTime(date,located.lon),
      frontBearingDeg:located.front_bearing_deg, overcast, fog, extinction, latitude:located.lat, force:moved || forceSky});
    if (skyChanged) stageHaze.refresh();
    timeLook = lookAt(solar.altitude * 180 / Math.PI, { altitude: lunar.altitude, fraction: illumination.fraction },
      { shadows: settings.shadows, overcast, sunTransmittance:cloudShadow.centre(), zenith:sky.horizon([0,1,0]).toArray(), ground:sky.horizon([0,-1,0]).toArray(), nightBrightness });
    scene.background = sky.clearCube; scene.backgroundIntensity = 1;
    scene.environment = environment;
    scene.environmentIntensity = timeLook.environment;
    sun.intensity = timeLook.sunClear; moon.intensity = timeLook.moon;
    sun.color.setRGB(...timeLook.sunColor, THREE.SRGBColorSpace);
    moon.color.setRGB(...timeLook.moonColor, THREE.SRGBColorSpace);
    ambient.intensity = timeLook.ambient;
    ambient.color.setRGB(...timeLook.skyColor); ambient.groundColor.setRGB(...timeLook.groundColor);
    renderer3.toneMappingExposure = timeLook.exposure;
    for (const [light, position] of [[sun, solar], [moon, lunar]]) {
      const [x, y, z] = modelDirection(position.azimuth, position.altitude, located.front_bearing_deg);
      const radius = Math.max(bounds.span * FT * 2, 40);
      light.target.position.set(bounds.x * FT, 0, -bounds.y * FT);
      light.position.set(bounds.x * FT + x * radius, y * radius, -bounds.y * FT + z * radius);
    }
    // Rendering and lamp changes do not refresh the sun map. The clock moves
    // it at most once per minute, including rapid test-clock changes. A person
    // choosing another time of day sees its shadows at once.
    if (!cheap && (moved || performance.now() - lastShadowUpdate >= 60000)) {
      sun.shadow.needsUpdate = true; lastShadowUpdate = performance.now();
    }
    if (!cheap && (skyChanged || moved)) reflections.request();
  }
  function updateTime(moved = false, forceSky = false) {
    if (disposed) return;
    applyTimeLook(moved, forceSky); applyLights(); view.onTimeLook?.(); viewing?.warm(); render();
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
    if (!bakes || state.unlit && !editor) return;
    view.bakePlan = plan;
    bakeSignature = JSON.stringify(plan);
    if (editor) {
      // Re-read the final plan after in-place deforms. Never clone the edited
      // scene: it contains sheets, handles and temporarily ghosted finishes.
      // The viewer's full-wall topology preserves its existing atlas keys.
      const bakePlan = plan;
      let physical = null, physicalYard = null;
      const yardMaterials = new Set();
      const copyReceivers = node => {
        const original = bakeAuthoredMaterial(yardGroup, node) || selectedMaterials.get(node) || faded.get(node) || node.material;
        const shown = node.material;
        node.material = original;
        const receives = atlasMesh(node);
        node.material = shown;
        const children = node.children.map(copyReceivers).filter(Boolean);
        if (!receives && !children.length) return null;
        // Skip trees, grass instances, props and editor layers entirely. Only
        // receiving buffers are copied; authored materials remain shared.
        const copy = receives ? node.clone(false) : new THREE.Group();
        copy.name = node.name; copy.userData = { ...node.userData };
        copy.position.copy(node.position); copy.quaternion.copy(node.quaternion); copy.scale.copy(node.scale);
        if (receives) { copy.geometry = node.geometry.clone(); copy.material = original; yardMaterials.add(original); }
        if (children.length) copy.add(...children);
        return copy;
      };
      registerBakeSource(twin.root, () => buildTwin(withoutSurfaceMaterials(bakePlan), { ...kit, manifest: {} }, tier,
        { viewing: true, bakeSource: true }).root, { extras: false,
          // Authored viewer-shaped materials classify alpha and supply physical
          // reach inputs. Drawn editor fades, focus and selection never enter.
          alphaRoots: () => {
            physical ||= buildTwin(bakePlan, kit, tier, { viewing: true, bakeSource: true, gutters: twin?.gutters });
            physical.root.updateMatrixWorld(true);
            return [physical.root, ...(yardGroup ? [yardGroup] : [])];
          },
          receiverRoots: () => {
            physical ||= buildTwin(bakePlan, kit, tier, { viewing: true, bakeSource: true, gutters: twin?.gutters });
            if (!physicalYard && yardGroup) {
              physicalYard = copyReceivers(yardGroup) || new THREE.Group();
              physicalYard.matrixAutoUpdate = false; physicalYard.matrix.copy(yardGroup.matrixWorld);
            }
            return [physical.root, ...(physicalYard ? [physicalYard] : [])];
          },
          dispose: () => {
            if (physical) release(physical);
            if (physicalYard) disposeObject(physicalYard, { keepMaterials: yardMaterials });
            physical = physicalYard = null; yardMaterials.clear();
          } });
    }
    const host = document.getElementById('twin-controls');
    mountBake(view, twin.root, { ...(typeof bake === 'object' ? bake : {}),
      host: editor ? bake.host : host, mode: editor ? 'manual' : 'readonly', display: !editor,
      disabledReason: editor && state.unlit ? 'Switch from Unlit to bake lighting' : '', parent: host?.dataset.bakeParent === 'true' });
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
      const shownIntensity = intensity * (viewing?.levelAlpha(l.userData.level) ?? 1);
      if (pieceVisibility) pieceVisibility.setLightIntensity(l, shownIntensity);
      else l.intensity = shownIntensity;
      // Live lamps zero the intensity but keep visibility, so the shader's light
      // count never changes and the first tap on Lights recompiles nothing.
      l.visible = !editor || !!twin.groups.levels[l.userData.level]?.visible;
    });
    twin.root.traverse(o => { for (const m of o.material ? [].concat(o.material) : []) if (m.name === 'fixture') m.emissiveIntensity = !liveLamps && night ? 2 : 0; });
  }
  if (new URLSearchParams(location.search).get('test') === '1') Object.assign(view, {
    grassInfo() {
      const {instances = 0, draws = 0, regions = 0, animated = false} = yardGroup?.userData.grass || {};
      return {tier, instances, draws, regions, animated};
    },
    reflectionInfo: () => reflections.info(),
    weatherPreviewDeadline: () => weatherPreview.deadline,
    seasonPreviewDeadline: () => seasonPreview.deadline,
    expireTimePreview,
    setClock(isoString) {
      if (isoString !== null && !Number.isFinite(Date.parse(isoString))) throw new Error('Give an ISO clock time or null.');
      clock = isoString; updateTime(false, true);
    },
    cameraState() { return { position: camera.position.toArray(), target: controls.target.toArray() }; },
    // Retain the late-sky/test hook; the atmosphere now owns the fixed environment.
    applySky(texture) { texture?.dispose(); updateTime(false, true); },
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
  if (editor) view.editorCamera = mountEditorCamera(view, el);
  resize();
  try {
    await view.rebuild(plan);
    // The viewer warms the whole scene through viewing.warm(). The neutral
    // editor has no viewing layer: warm its hidden weather objects explicitly,
    // against the same picture target, before Live weather can reveal them.
    if (editor && compileFor) await renderer3.compileAsync(precipitation.group,camera,scene);
    // Compile both hidden seasonal programs for the actual picture target in
    // viewers too: viewing.warm only expands the house's domain objects.
    if (compileFor) await renderer3.compileAsync(seasonTouches.group,camera,scene);
    view.ready = false;
    if (disposed) return view;
    view.materialWatcher = watchMaterialCatalogue(view);
    // Live pushes draw through this loop instead of rendering a second time.
    view.looping = true;
    renderer3.setAnimationLoop(() => {
      const now = performance.now(), run = probeRun;
      if(!compiling || now-holdSince>=HOLD_MS) {
        clouds.frame(now/1000);
        const skyRefresh=sky.frame(now/1000);
        if(skyRefresh==='drift')reflections.requestSky();
        else if(skyRefresh)reflections.request();
      }
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
      else if (!view.cameraTransition) {
        view.editorCamera?.frame(now);
        controls.update();
      }
      const drawn = view.meter ? performance.now() : 0;
      render();
      // Captures belong only to animation frames, never synchronous editor
      // render/rebuild/apply calls. One cube after 1.5 seconds of quiet.
      if (view.ready && !rebuildWork) reflections.frame();
      view.meter?.frame(now, performance.now() - drawn);
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
    if (new URLSearchParams(location.search).get('perf') === '1')
      view.meter = mountFrameMeter(el, { renderer3, gpu: view.renderer, tier, pixelRatio: settings.pixelRatio, stats: () => lastStats });
    view.ready = true;
    weatherPoll=mountWeatherState({onChange:ground=>{
      groundWeather=ground;
      if(typeof ground.source.configured_entity==='string')weatherEntity=ground.source.configured_entity || null;
      updateTime(false,true);
    }});
    // Uniform texture/geometry contents arrive without changing shader programs.
    sky.loadAssets(() => { if (!disposed) updateTime(false,true); });
    timeTimer = setInterval(() => updateTime(false, true), 60000);
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
    const view = await mountTwin(host, { plan: snapshot.plan, kit, round: snapshot.round ?? null, site: snapshot.site, stage:snapshot.stage });
    document.getElementById('twin-tier').textContent = view.tier[0].toUpperCase() + view.tier.slice(1);
    const sync = () => {
      document.querySelectorAll('[data-time]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.time === view.state.time)));
      document.querySelectorAll('[data-weather-preview]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.weatherPreview === view.state.weatherPreview)));
      document.querySelectorAll('[data-season-preview]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.seasonPreview === view.state.seasonPreview)));
    };
    host.addEventListener('twintimechange', sync);
    host.addEventListener('twinviewchange', sync);
    const click = event => {
      const button = event.target.closest('button'); if (!button) return;
      if (button.dataset.time) view.setTime(button.dataset.time);
      if (button.dataset.weatherPreview) view.setWeatherPreview(button.dataset.weatherPreview);
      if (button.dataset.seasonPreview) view.setSeasonPreview(button.dataset.seasonPreview);
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
    view.stageSettings = mountStageSettings(view);
    view.weatherSettings = mountWeatherSettings(view);
    view.timeScrub = mountTimeScrub(view, document.getElementById('twin-time-scrub'));
    view.nightBrightnessControl = mountNightBrightness(view, document.getElementById('twin-night-brightness'));
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
