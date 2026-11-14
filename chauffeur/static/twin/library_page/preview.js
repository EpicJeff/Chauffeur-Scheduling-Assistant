import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { applyMaterialParams, kitMaterial } from '../twin_library.js';
import { sunPosition } from '../sky/ephemeris.js';
import { resolveSite, previewDate, modelDirection, lookAt } from '../sky/look.js';

// Preview geometry uses feet just like generator UVs. World positions are metres.
const FT = .3048;
const mapProperties = { base_color: ['map'], normal: ['normalMap'], roughness: ['roughnessMap'],
  metalness: ['metalnessMap'], ao: ['aoMap'], orm: ['aoMap', 'roughnessMap', 'metalnessMap'] };

export function createPreview(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
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
  let material = new THREE.MeshStandardMaterial(), signature, generation = 0, stopped = false, currentParams, currentEntry;
  const sample = new THREE.Mesh(new THREE.SphereGeometry(2 * FT, 48, 32), material);
  sample.userData.librarySample = true; scene.add(sample);
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

  function updateParams() {
    if (!currentParams || currentEntry.source === 'builtin') return;
    const p = currentParams;
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
    currentEntry = entry; currentParams = params;
    const key = JSON.stringify([entry.id, entry.source, entry.maps, entry.previewMaps]);
    if (signature !== key) {
      signature = key; const turn = ++generation;
      material.dispose();
      if (entry.source === 'builtin') {
        const kit = window.twinKit || { materials: {}, manifest: window.twinManifest || {} };
        const role = Object.keys(kit.materials).find(role => kit.materials[role].asset === entry.id) || 'preview';
        material = kitMaterial(role, { ...kit, materials: { ...kit.materials, [role]: kit.materials[role] || { asset: entry.id, color: params.tint } } }, 'high');
      } else {
        material = applyMaterialParams(new THREE.MeshStandardMaterial(), {
          ...entry, params, maps: Object.fromEntries(Object.entries(entry.maps || {}).filter(([slot, path]) => path && !entry.previewMaps?.[slot]
            && !(entry.previewMaps?.orm && ['ao', 'roughness', 'metalness'].includes(slot)))
            .map(([slot, path]) => [slot, path.startsWith('materials/') ? path : `materials/${entry.id}/${path}`])),
        }, { id: entry.id }, 'preview', 'high');
      }
      sample.material = material;
      const active = material;
      const local = Object.entries(entry.previewMaps || {}).filter(([slot]) => mapProperties[slot]
        && !((entry.previewMaps?.orm || entry.maps?.orm) && ['ao', 'roughness', 'metalness'].includes(slot))).map(([slot, url]) => new Promise(resolve => {
        new THREE.TextureLoader().load(url, texture => {
          if (stopped || generation !== turn) { texture.dispose(); resolve(); return; }
          texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
          texture.colorSpace = slot === 'base_color' ? THREE.SRGBColorSpace : THREE.NoColorSpace;
          for (const property of mapProperties[slot]) active[property] = texture;
          active.addEventListener('dispose', () => texture.dispose()); active.needsUpdate = true; updateParams(); resolve();
        }, undefined, () => resolve());
      }));
      Promise.all([active.userData.ready, ...local]).then(() => { if (!stopped && generation === turn) updateParams(); });
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
  let frame;
  function draw() {
    if (stopped) return;
    // A late map attachment can restore the initial Auto multiplier. Always
    // draw with the latest draft, including maps arriving after ready's budget.
    updateParams(); controls.update(); renderer.render(scene, camera); frame = requestAnimationFrame(draw);
  }
  setShape('sphere'); setLight('studio'); draw();
  return { setMaterial, setShape, setLight, dispose() {
    stopped = true; ++generation; cancelAnimationFrame(frame); observer.disconnect(); controls.dispose();
    material.dispose(); const geometries = new Set();
    scene.traverse(object => { if (object.geometry) geometries.add(object.geometry); });
    geometries.forEach(g => g.dispose()); figureMaterial.dispose(); floor.material.dispose();
    environment?.dispose(); pmrem?.dispose(); renderer.dispose();
  } };
}
