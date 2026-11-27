import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { alphaModeOf, applyMaterialParams, kitMaterial } from '../twin_library.js';
import { frameThumbnailCamera } from '../model_thumbnails.js';
import { BUILTIN_LOOKS, builtinMaterial } from '../surface_kinds.js';
import { sunPosition } from '../sky/ephemeris.js';
import { resolveSite, previewDate, modelDirection, lookAt } from '../sky/look.js';

// Preview geometry uses feet just like generator UVs. World positions are metres.
const FT = .3048;
const FALLBACK_PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
const mapProperties = { base_color: ['map'], normal: ['normalMap'], roughness: ['roughnessMap'],
  metalness: ['metalnessMap'], ao: ['aoMap'], orm: ['aoMap', 'roughnessMap', 'metalnessMap'], opacity: ['alphaMap'] };

function meshPartKey(mesh, face) {
  if (!mesh) return null;
  if (mesh.userData?.partKey) return mesh.userData.partKey;
  const mat = Array.isArray(mesh.material) ? mesh.material[face?.materialIndex || 0] : mesh.material;
  return mat?.userData?.partKey || null;
}

export function createPreview(canvas, { onPartDrop = null } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(40, 1, .05, 100);
  camera.position.set(4, 2.8, 5);
  const controls = new OrbitControls(camera, canvas); controls.target.set(0, 1, 0);
  controls.enableDamping = true; controls.minDistance = 1; controls.maxDistance = 15; controls.update();
  const studio = new THREE.Group();
  for (const [x, y, z, intensity] of [[3, 5, 4, 3], [-4, 2, 1, 1.5], [0, 3, -4, 2]]) {
    const light = new THREE.DirectionalLight(0xffffff, intensity); light.position.set(x, y, z); studio.add(light);
  }
  const ambient = new THREE.HemisphereLight(0xffffff, 0x434851, 1.5), sun = new THREE.DirectionalLight(0xffffff, 3);
  scene.add(studio, ambient, sun); sun.visible = false;
  // PMREM supplies the specular response needed to judge metalness and roughness.
  let pmrem, environment;
  if (typeof renderer.compile === 'function') {
    const room = new THREE.Scene(); room.background = new THREE.Color('#606773');
    const cardMaterial = new THREE.MeshBasicMaterial({ color: '#ffffff', side: THREE.DoubleSide });
    for (const [x, y, z, w, h] of [[-4, 3, 0, 3, 6], [4, 4, 2, 2, 5], [0, 6, -3, 5, 2]]) {
      const card = new THREE.Mesh(new THREE.PlaneGeometry(w, h), cardMaterial);
      card.position.set(x, y, z); card.lookAt(0, 1, 0); room.add(card);
    }
    pmrem = new THREE.PMREMGenerator(renderer); environment = pmrem.fromScene(room); scene.environment = environment.texture;
    room.traverse(object => object.geometry?.dispose()); cardMaterial.dispose();
  }
  let material = new THREE.MeshStandardMaterial(), signature, generation = 0, stopped = false, active = true, currentParams, currentEntry;
  const sample = new THREE.Mesh(new THREE.SphereGeometry(2 * FT, 48, 32), material);
  sample.userData.librarySample = true; scene.add(sample);

  // Model preview holder and non-destructive overlays (never mutate shared materials or dispose cached model geometry).
  const modelHolder = new THREE.Group(); modelHolder.name = 'library-model-holder'; scene.add(modelHolder);
  const wireGroup = new THREE.Group(); wireGroup.userData.helper = true; scene.add(wireGroup);
  const highlightGroup = new THREE.Group(); highlightGroup.userData.helper = true; scene.add(highlightGroup);
  const wireMaterial = new THREE.MeshBasicMaterial({ color: '#38bdf8', wireframe: true, transparent: true, opacity: .55, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 });
  const highlightFillMat = new THREE.MeshBasicMaterial({ color: '#22d3ee', transparent: true, opacity: .42, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  const highlightOutlineMat = new THREE.MeshBasicMaterial({ color: '#00f0ff', side: THREE.BackSide, depthWrite: false });
  const highlightEdgeMat = new THREE.MeshBasicMaterial({ color: '#a5f3fc', wireframe: true, transparent: true, opacity: .45, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 });
  const raycaster = new THREE.Raycaster();
  let currentModel = null, wireframe = false, activeHighlight = null, dropHandler = onPartDrop;

  // Simple neutral human silhouette: exactly six feet from soles to crown.
  const figure = new THREE.Group(), figureMaterial = new THREE.MeshStandardMaterial({ color: '#a3a9b6', roughness: .8 });
  for (const [geometry, x, y] of [
    [new THREE.SphereGeometry(.4 * FT, 16, 12), 0, 5.6 * FT],
    [new THREE.BoxGeometry(.9 * FT, 2 * FT, .45 * FT), 0, 4.2 * FT],
    [new THREE.BoxGeometry(.32 * FT, 3.2 * FT, .4 * FT), -.27 * FT, 1.6 * FT],
    [new THREE.BoxGeometry(.32 * FT, 3.2 * FT, .4 * FT), .27 * FT, 1.6 * FT],
    [new THREE.BoxGeometry(.25 * FT, 2.2 * FT, .3 * FT), -.7 * FT, 4 * FT],
    [new THREE.BoxGeometry(.25 * FT, 2.2 * FT, .3 * FT), .7 * FT, 4 * FT],
  ]) { const mesh = new THREE.Mesh(geometry, figureMaterial); mesh.position.set(x, y, 0); figure.add(mesh); }
  figure.name = '6 ft scale figure'; figure.position.x = -2; scene.add(figure);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(20, 20), new THREE.MeshStandardMaterial({ color: '#525866', roughness: 1 }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -.01; scene.add(floor);

  function syncWireframe() {
    wireGroup.clear();
    if (!wireframe || !currentModel) return;
    modelHolder.updateMatrixWorld(true);
    currentModel.traverse(mesh => {
      if (!mesh.isMesh || !mesh.geometry) return;
      const overlay = new THREE.Mesh(mesh.geometry, wireMaterial);
      overlay.matrixAutoUpdate = false;
      overlay.matrix.copy(mesh.matrixWorld);
      overlay.userData.helper = true;
      wireGroup.add(overlay);
    });
  }
  function syncHighlight() {
    highlightGroup.clear();
    if (!activeHighlight || !currentModel) return;
    modelHolder.updateMatrixWorld(true);
    const center = new THREE.Vector3(), toCenter = new THREE.Matrix4(), scaleM = new THREE.Matrix4(), fromCenter = new THREE.Matrix4();
    currentModel.traverse(mesh => {
      if (!mesh.isMesh || !mesh.geometry || meshPartKey(mesh) !== activeHighlight) return;
      const fill = new THREE.Mesh(mesh.geometry, highlightFillMat);
      fill.matrixAutoUpdate = false; fill.matrix.copy(mesh.matrixWorld); fill.renderOrder = 10;
      highlightGroup.add(fill);
      const edge = new THREE.Mesh(mesh.geometry, highlightEdgeMat);
      edge.matrixAutoUpdate = false; edge.matrix.copy(mesh.matrixWorld); edge.renderOrder = 11;
      highlightGroup.add(edge);
      if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
      mesh.geometry.boundingBox?.getCenter(center);
      toCenter.makeTranslation(center.x, center.y, center.z);
      scaleM.makeScale(1.14, 1.14, 1.14);
      fromCenter.makeTranslation(-center.x, -center.y, -center.z);
      const outline = new THREE.Mesh(mesh.geometry, highlightOutlineMat);
      outline.matrixAutoUpdate = false;
      outline.matrix.copy(mesh.matrixWorld).multiply(toCenter).multiply(scaleM).multiply(fromCenter);
      outline.renderOrder = 9;
      highlightGroup.add(outline);
    });
  }
  function setModel(object3d, { refit = false } = {}) {
    activeHighlight = null;
    highlightGroup.clear();
    wireGroup.clear();
    modelHolder.clear();
    currentModel = object3d || null;
    sample.visible = !currentModel;
    if (currentModel) {
      modelHolder.add(currentModel);
      modelHolder.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(currentModel);
      if (!box.isEmpty()) {
        figure.position.x = Math.min(-1.2, box.min.x - .85);
        if (refit) {
          const centre = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
          const span = Math.max(size.x, size.y, size.z, .7);
          controls.target.set(centre.x, Math.max(centre.y, .25), centre.z);
          camera.position.set(centre.x + span * 1.4, Math.max(centre.y + span * .7, .85), centre.z + span * 1.75);
          controls.minDistance = Math.max(.35, span * .3);
          controls.maxDistance = Math.max(15, span * 8);
          controls.update();
        }
      }
      syncWireframe();
    } else {
      figure.position.x = -2;
      controls.minDistance = 1; controls.maxDistance = 15;
    }
  }
  function setWireframe(on) { wireframe = !!on; syncWireframe(); }
  function partAt(x, y) {
    if (!currentModel) return null;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return null;
    const ndc = new THREE.Vector2(((x - rect.left) / rect.width) * 2 - 1, -((y - rect.top) / rect.height) * 2 + 1);
    camera.updateMatrixWorld(true);
    modelHolder.updateMatrixWorld(true);
    raycaster.setFromCamera(ndc, camera);
    const meshes = [];
    currentModel.traverse(o => { if (o.isMesh && o.visible && o.geometry) meshes.push(o); });
    for (const hit of raycaster.intersectObjects(meshes, false)) {
      const key = meshPartKey(hit.object, hit.face);
      if (key) return key;
    }
    return null;
  }
  function highlightPart(partKey) {
    const next = partKey || null;
    if (next === activeHighlight && (!next || highlightGroup.children.length)) return;
    activeHighlight = next;
    syncHighlight();
  }
  function partScreenPoint(partKey) {
    if (!currentModel || !partKey) return null;
    modelHolder.updateMatrixWorld(true);
    camera.updateMatrixWorld(true);
    const box = new THREE.Box3();
    currentModel.traverse(o => {
      if (o.isMesh && meshPartKey(o) === partKey) box.expandByObject(o);
    });
    if (box.isEmpty()) return null;
    const point = box.getCenter(new THREE.Vector3()).project(camera);
    const rect = canvas.getBoundingClientRect();
    return { x: rect.left + (point.x * .5 + .5) * rect.width, y: rect.top + (-point.y * .5 + .5) * rect.height };
  }
  function captureThumbnail() {
    if (!currentModel) return null;
    modelHolder.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(modelHolder);
    if (box.isEmpty()) return FALLBACK_PNG;
    const thumbCamera = new THREE.PerspectiveCamera(36, 160 / 128, .01, 100);
    frameThumbnailCamera(box, thumbCamera);
    const prevBg = scene.background, prevRatio = renderer.getPixelRatio();
    const prevFigure = figure.visible, prevFloor = floor.visible, prevWire = wireGroup.visible, prevHi = highlightGroup.visible;
    figure.visible = floor.visible = wireGroup.visible = highlightGroup.visible = false;
    scene.background = null;
    let url = FALLBACK_PNG;
    try {
      renderer.setClearAlpha(0);
      renderer.setPixelRatio(1);
      renderer.setSize(160, 128, false);
      renderer.render(scene, thumbCamera);
      if (typeof canvas.toDataURL === 'function') url = canvas.toDataURL('image/png') || FALLBACK_PNG;
    } finally {
      figure.visible = prevFigure; floor.visible = prevFloor; wireGroup.visible = prevWire; highlightGroup.visible = prevHi;
      scene.background = prevBg;
      renderer.setClearAlpha(1);
      renderer.setPixelRatio(prevRatio);
      resize();
      renderer.render(scene, camera);
    }
    return url;
  }

  const canvasAbort = new AbortController();
  const isMaterialDrag = event => {
    const types = Array.from(event.dataTransfer?.types || []);
    return types.includes('application/x-chauffeur-material') || !!window.__chfDragMaterial;
  };
  canvas.addEventListener('dragover', event => {
    if (!currentModel || !dropHandler || !isMaterialDrag(event)) return;
    event.preventDefault();
    const key = partAt(event.clientX, event.clientY);
    highlightPart(key);
    if (event.dataTransfer) event.dataTransfer.dropEffect = key ? 'copy' : 'none';
  }, { signal: canvasAbort.signal });
  canvas.addEventListener('dragleave', () => { highlightPart(null); }, { signal: canvasAbort.signal });
  canvas.addEventListener('drop', event => {
    if (!currentModel || !dropHandler) return;
    const materialId = event.dataTransfer?.getData?.('application/x-chauffeur-material') || window.__chfDragMaterial;
    if (!materialId) return;
    event.preventDefault();
    const key = partAt(event.clientX, event.clientY);
    highlightPart(null);
    if (key) dropHandler(key, materialId);
  }, { signal: canvasAbort.signal });

  function updateParams() {
    if (!currentParams || currentEntry.source === 'builtin') return;
    const p = currentParams;
    if (material.userData.alphaMode === 'blend') material.opacity = p.opacity ?? 1;
    if (material.userData.alphaMode === 'cutout') material.alphaTest = Math.max(p.alpha_cutoff ?? .5, .01);
    material.color.set(p.tint || '#ffffff');
    material.roughness = p.roughness ?? (material.roughnessMap ? 1 : .85);
    material.metalness = p.metalness ?? (material.metalnessMap ? 1 : 0);
    material.normalScale.set(p.normal_scale ?? 1, (p.normal_convention === 'dx' ? -1 : 1) * (p.normal_scale ?? 1));
    material.aoMapIntensity = p.ao_intensity ?? 1;
    const tile = p.tile_ft || [4, 4];
    for (const texture of new Set(Object.values(mapProperties).flat().map(key => material[key]).filter(Boolean))) {
      texture.repeat.set(1 / tile[0], 1 / tile[1]); texture.rotation = (p.rotation_deg ?? 0) * Math.PI / 180;
    }
  }
  function setMaterial(entry, params = entry.params || {}) {
    if (currentModel) setModel(null);
    currentEntry = entry; currentParams = params;
    const key = JSON.stringify([entry.id, entry.source, entry.maps, entry.previewMaps, alphaModeOf({ ...entry, params })]);
    if (signature !== key) {
      signature = key; const turn = ++generation;
      material.dispose();
      if (entry.source === 'builtin') {
        const kit = window.twinKit || { materials: {}, manifest: window.twinManifest || {} };
        const role = Object.keys(kit.materials).find(role => kit.materials[role].asset === entry.id) || 'preview';
        material = Object.hasOwn(BUILTIN_LOOKS, entry.id) ? builtinMaterial(entry.id, 'preview')
          : kitMaterial(role, { ...kit, materials: { ...kit.materials, [role]: kit.materials[role] || { asset: entry.id, color: params.tint } } }, 'high');
      } else {
        material = applyMaterialParams(new THREE.MeshStandardMaterial(), {
          ...entry, params, maps: Object.fromEntries(Object.entries(entry.maps || {}).filter(([slot, path]) => path && !entry.previewMaps?.[slot]
            && !(entry.previewMaps?.orm && ['ao', 'roughness', 'metalness'].includes(slot)))
            .map(([slot, path]) => [slot, path.startsWith('materials/') ? path : `materials/${entry.id}/${path}`])),
        }, { id: entry.id }, 'preview', 'high');
      }
      sample.material = material;
      const activeMat = material;
      const local = Object.entries(entry.previewMaps || {}).filter(([slot]) => mapProperties[slot]
        && (slot !== 'opacity' || activeMat.userData.alphaMode !== 'opaque')
        && !((entry.previewMaps?.orm || entry.maps?.orm) && ['ao', 'roughness', 'metalness'].includes(slot))).map(([slot, url]) => new Promise(resolve => {
        new THREE.TextureLoader().load(url, texture => {
          if (stopped || generation !== turn) { texture.dispose(); resolve(); return; }
          texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
          texture.colorSpace = slot === 'base_color' ? THREE.SRGBColorSpace : THREE.NoColorSpace;
          for (const property of mapProperties[slot]) activeMat[property] = texture;
          activeMat.addEventListener('dispose', () => texture.dispose()); activeMat.needsUpdate = true; updateParams(); resolve();
        }, undefined, () => resolve());
      }));
      Promise.all([activeMat.userData.ready, ...local]).then(() => { if (!stopped && generation === turn) updateParams(); });
    }
    updateParams();
  }
  function setShape(shape) {
    let geometry;
    if (shape === 'sphere') geometry = new THREE.SphereGeometry(2 * FT, 48, 32);
    else if (shape === 'cube') geometry = new THREE.BoxGeometry(4 * FT, 4 * FT, 4 * FT);
    else if (shape === 'wall' || shape === 'ground') geometry = new THREE.PlaneGeometry(8 * FT, (shape === 'wall' ? 8 : 12) * FT);
    else return;
    // Three's generated UVs are normalized; convert to physical feet.
    const uv = geometry.attributes.uv;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * (shape === 'sphere' ? 4 * Math.PI : shape === 'cube' ? 4 : 8), uv.getY(i) * (shape === 'ground' ? 12 : shape === 'wall' ? 8 : shape === 'sphere' ? 2 * Math.PI : 4));
    sample.geometry.dispose(); sample.geometry = geometry;
    sample.rotation.x = shape === 'ground' ? -Math.PI / 2 : 0;
    sample.position.y = shape === 'ground' ? .005 : shape === 'wall' ? 4 * FT : 2 * FT;
  }
  function setLight(choice) {
    studio.visible = choice !== 'sun'; sun.visible = choice === 'sun';
    if (choice === 'sun') {
      const site = resolveSite(window.twinSite || {}), date = previewDate(new Date(), 'day', site);
      const solar = sunPosition(date, site.lat, site.lon), look = lookAt(solar.altitude * 180 / Math.PI);
      sun.position.fromArray(modelDirection(solar.azimuth, solar.altitude, site.front_bearing_deg)).multiplyScalar(10);
      sun.color.setRGB(...look.sunColor, THREE.SRGBColorSpace); sun.intensity = look.sun;
      ambient.color.set('#d9e9ff'); ambient.groundColor.set('#68764f'); ambient.intensity = look.ambient;
      scene.background = new THREE.Color().setRGB(...look.background, THREE.SRGBColorSpace);
      scene.environmentIntensity = look.environment; renderer.toneMappingExposure = look.exposure;
    } else {
      ambient.color.set('#ffffff'); ambient.groundColor.set('#434851'); ambient.intensity = 1.5;
      scene.background = new THREE.Color('#303640'); scene.environmentIntensity = 1; renderer.toneMappingExposure = 1;
    }
  }
  function resize() {
    const width = canvas.clientWidth || 400, height = canvas.clientHeight || 400;
    renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
  }
  const observer = new ResizeObserver(resize); observer.observe(canvas); resize();
  let frame = null;
  function draw() {
    if (stopped || !active) { frame = null; return; }
    // A late map attachment can restore the initial Auto multiplier. Always
    // draw with the latest draft, including maps arriving after ready's budget.
    if (!currentModel) updateParams();
    controls.update(); renderer.render(scene, camera); frame = requestAnimationFrame(draw);
  }
  function setActive(on) {
    active = !!on;
    if (active && !stopped && frame === null) { resize(); draw(); }
    else if (!active && frame !== null) { cancelAnimationFrame(frame); frame = null; }
  }
  setShape('sphere'); setLight('studio'); draw();
  return {
    setMaterial, setShape, setLight, setModel, setWireframe, isWireframe: () => wireframe,
    partAt, highlightPart, highlightedPart: () => activeHighlight, partScreenPoint,
    captureThumbnail, setDropHandler: fn => { dropHandler = fn; }, setActive, resize,
    get currentModel() { return currentModel; },
    dispose() {
      stopped = true; ++generation; cancelAnimationFrame(frame); frame = null;
      canvasAbort.abort(); observer.disconnect(); controls.dispose();
      // Detach borrowed model & overlays before disposing preview-owned geometries.
      modelHolder.clear(); wireGroup.clear(); highlightGroup.clear(); currentModel = null;
      material.dispose(); wireMaterial.dispose(); highlightFillMat.dispose(); highlightOutlineMat.dispose(); highlightEdgeMat.dispose();
      const geometries = new Set();
      scene.traverse(object => { if (object.geometry) geometries.add(object.geometry); });
      geometries.forEach(g => g.dispose()); figureMaterial.dispose(); floor.material.dispose();
      environment?.dispose(); pmrem?.dispose(); renderer.dispose();
    },
  };
}
