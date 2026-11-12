import { applyObject, objectShown } from './objects.js';
import * as THREE from 'three';
import { Tree } from '@dgreenheck/ez-tree';
import { FT, addMesh, boxGeometry, boxRect, polygon, mergeStatic, allPorches } from './twin_generator.js';
import { kitMaterial, loadModel, disposeObject } from './twin_library.js';
import { groundAt } from './twin_ground.js';

function random(seed) {
  let n = seed | 0;
  return () => { n = n + 0x6d2b79f5 | 0; let t = Math.imul(n ^ n >>> 15, n | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

function standardTree(tree) {
  const converted = new Map();
  tree.traverse(o => {
    if (!o.isMesh) return;
    const convert = m => {
      if (!converted.has(m)) converted.set(m, new THREE.MeshStandardMaterial({
        name: m.name, color: m.map ? '#ffffff' : m.color, map: m.map, normalMap: m.normalMap,
        alphaMap: m.alphaMap, alphaTest: m.alphaTest > 0 ? Math.max(0.5, m.alphaTest) : 0,
        side: m.side, roughness: 0.9,
      }));
      return converted.get(m);
    };
    o.material = Array.isArray(o.material) ? o.material.map(convert) : convert(o.material);
    o.castShadow = o.receiveShadow = true;
  });
  converted.forEach((_, original) => original.dispose());
}

async function imagesReady(tree) {
  const textures = new Set();
  tree.traverse(o => {
    for (const m of o.material ? [].concat(o.material) : []) for (const property of ['map', 'normalMap', 'alphaMap']) {
      if (m[property]) textures.add(m[property]);
    }
  });
  await Promise.all([...textures].map(texture => new Promise(resolve => {
    // TextureLoader does not assign texture.image until its ImageLoader has
    // finished. Waiting only for existing images can bake a blank first tree.
    const deadline = performance.now() + 5000;
    const check = () => {
      const img = texture.image;
      if (img) Promise.resolve(img.decode ? img.decode() : undefined).catch(() => {}).then(resolve);
      else if (performance.now() >= deadline) resolve();
      else setTimeout(check, 16);
    };
    check();
  })));
}

// EZ-Tree owns module-level bark/leaf textures. Dispose generated geometry and
// converted materials here, leaving those shared textures for later presets.
function releasePlant(tree) {
  tree.traverse(o => { o.geometry?.dispose(); for (const m of o.material ? [].concat(o.material) : []) m.dispose(); });
}

async function bakePreset(preset, seed, renderer) {
  const tree = new Tree(); tree.loadPreset(preset); tree.options.seed = seed; tree.generate();
  standardTree(tree);
  await imagesReady(tree);
  const bounds = new THREE.Box3().setFromObject(tree), size = bounds.getSize(new THREE.Vector3()), center = bounds.getCenter(new THREE.Vector3());
  const height = Math.max(0.01, size.y), width = Math.max(size.x, size.z, height * 0.2) * 1.08;
  const scene = new THREE.Scene(); scene.add(tree);
  scene.add(new THREE.HemisphereLight('#ffffff', '#586c41', 2.2));
  const sun = new THREE.DirectionalLight('#fff3db', 2.5); sun.position.set(-height, height * 2, height * 2); scene.add(sun);
  const camera = new THREE.OrthographicCamera(-width / 2, width / 2, height * 0.54, -height * 0.54, 0.01, height * 12);
  camera.position.set(center.x, center.y, center.z + height * 4); camera.lookAt(center);
  renderer.setSize(256, 512, false); renderer.setClearColor(0, 0); renderer.render(scene, camera);
  // Copy pixels out of the baking context; render-target textures cannot be
  // shared between two WebGL contexts. CanvasTexture uploads on the main one.
  const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 512;
  canvas.getContext('2d').drawImage(renderer.domElement, 0, 0);
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.MeshStandardMaterial({ name: 'plant card: ' + preset, map: texture, alphaTest: 0.45, side: THREE.DoubleSide, roughness: 1 });
  const result = { material, aspect: width / (height * 1.08), texture };
  releasePlant(tree);
  return result;
}

export async function buildYard(plan, kit, tier, { viewing = false } = {}) {
  const group = new THREE.Group(); group.name = 'yard';
  const site = plan.site || {}, mats = new Map();
  const surface = (poly, z0, z1 = z0, holes = []) => {
    const ground = groundAt(plan, ...poly[0]);
    return polygon(poly, z0 + ground, z1 + ground, holes);
  };
  const materialKit = { ...kit, materials: { ...kit.materials } };
  const known = kit.manifest || window.twinManifest || {};
  for (const [role, ref] of Object.entries(plan.materials || {})) materialKit.materials[role] = {
    ...kit.materials?.[role], color: ref.color || kit.materials?.[role]?.color,
    asset: known[ref.id] ? ref.id : kit.materials?.[role]?.asset,
  };
  const mat = role => { if (!mats.has(role)) mats.set(role, kitMaterial(role, materialKit, tier)); return mats.get(role); };
  const plain = (name, color, extra = {}) => {
    if (!mats.has(name)) mats.set(name, new THREE.MeshStandardMaterial({ name, color, roughness: 0.85, ...extra }));
    return mats.get(name);
  };
  if (site.lot?.length >= 3) {
    // Actual lawn material; no procedural canvas noise or substitute blobs.
    const pool = site.pool?.polygon;
    const xs = site.lot.map(p => p[0]), ys = site.lot.map(p => p[1]), margin = 150;
    const x0 = Math.min(...xs) - margin, x1 = Math.max(...xs) + margin;
    const y0 = Math.min(...ys) - margin, y1 = Math.max(...ys) + margin;
    // Continue the terrain below the lot edge without covering the sunken pool.
    addMesh(group, surface([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], -0.06, -0.06, pool ? [pool] : []), mat('lawn'));
    addMesh(group, surface(site.lot, -0.04, -0.04, pool ? [pool] : []), mat('lawn'));
  }
  const pool = site.pool?.polygon;
  const inside = (p, poly) => { let v = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) if ((poly[i][1] > p[1]) !== (poly[j][1] > p[1]) && p[0] < (poly[j][0] - poly[i][0]) * (p[1] - poly[i][1]) / (poly[j][1] - poly[i][1]) + poly[i][0]) v = !v; return v; };
  for (const h of site.hardscape || []) if (h.polygon?.length >= 3) {
    const holes = pool && pool.every(p => inside(p, h.polygon)) ? [pool] : [];
    const role = h.material === 'concrete' ? 'patio_concrete' : kit.materials?.[h.material] ? h.material : 'paving';
    addMesh(group, surface(h.polygon, 0, 0.3, holes), mat(role));
  }
  if (pool?.length >= 3) {
    const d = site.pool.depth || 5, coping = site.pool.coping || 1;
    addMesh(group, surface(pool, -d - 0.2, -d), plain('pool tile', '#5fa8c4', { roughness: 0.35 }));
    // Offset each edge outwards by coping width. This works for the convex pool
    // polygons used by the plan and retains the original water outline.
    const area = pool.reduce((a, p, i) => a + p[0] * pool[(i + 1) % pool.length][1] - pool[(i + 1) % pool.length][0] * p[1], 0);
    const normal = (a, b) => { const l = Math.hypot(b[0] - a[0], b[1] - a[1]); return area > 0 ? [(b[1] - a[1]) / l, -(b[0] - a[0]) / l] : [-(b[1] - a[1]) / l, (b[0] - a[0]) / l]; };
    const outer = pool.map((p, i) => {
      const a = normal(pool[(i + pool.length - 1) % pool.length], p), b = normal(p, pool[(i + 1) % pool.length]), factor = coping / Math.max(0.1, 1 + a[0] * b[0] + a[1] * b[1]);
      return [p[0] + (a[0] + b[0]) * factor, p[1] + (a[1] + b[1]) * factor];
    });
    addMesh(group, surface(outer, 0.3, 0.45, [pool]), mat('paving'));
    for (let i = 0; i < pool.length; i++) {
      const a = pool[i], b = pool[(i + 1) % pool.length], n = normal(a, b);
      addMesh(group, surface([a, b, [b[0] + n[0] * 0.25, b[1] + n[1] * 0.25], [a[0] + n[0] * 0.25, a[1] + n[1] * 0.25]], -d, 0.3), plain('pool tile', '#5fa8c4'));
    }
    addMesh(group, surface(pool, -0.25), plain('water', '#7fd0e6', { transparent: true, opacity: 0.65, roughness: 0.12, depthWrite: false }));
  }
  if (site.fire_pit?.at) {
    const f = site.fire_pit;
    addMesh(group, new THREE.CylinderGeometry(f.radius, f.radius + 0.2, 1.4, 24, 1, true).translate(f.at[0], 0.7, -f.at[1]), mat('base'));
    addMesh(group, new THREE.CircleGeometry(f.radius + 2, 32).rotateX(-Math.PI / 2).translate(f.at[0], 0.02, -f.at[1]), plain('gravel', '#a59c8f'));
  }
  for (const bed of site.beds || []) if (bed.polygon?.length >= 3) addMesh(group, surface(bed.polygon, 0, 0.12), mat('mulch'));
  if (site.fence?.polyline?.length > 1) {
    const f = site.fence, height = f.height || 6;
    for (let i = 0; i < f.polyline.length - 1; i++) {
      const a = f.polyline[i], b = f.polyline[i + 1], dx = b[0] - a[0], dy = b[1] - a[1], length = Math.hypot(dx, dy), angle = Math.atan2(dy, dx);
      if (!length) continue;
      for (let d = 0.25; d < length; d += 0.5) addMesh(group, boxGeometry(0.46, height, 0.06).rotateY(angle).translate(a[0] + dx * d / length, height / 2 + 0.15, -a[1] - dy * d / length), mat('fence'));
      for (let d = 0; d <= length; d += 8) addMesh(group, boxRect(a[0] + dx * d / length - 0.17, a[1] + dy * d / length - 0.17, a[0] + dx * d / length + 0.17, a[1] + dy * d / length + 0.17, 0, height + 0.3), mat('fence'));
      for (const y of [1, height - 0.6]) addMesh(group, boxGeometry(length, 0.3, 0.12).rotateY(angle).translate((a[0] + b[0]) / 2, y, -(a[1] + b[1]) / 2), mat('fence'));
    }
  }
  const cards = new Map();
  let baker = null;
  try {
    if (tier === 'low' && site.planting?.length) baker = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
    for (let index = 0; index < (site.planting || []).length; index++) {
      const p = site.planting[index]; if (!objectShown(p, !viewing)) continue; if (!p.at || !p.preset || !(p.height > 0)) continue;
      if (tier === 'low') {
        const holder = new THREE.Group(); holder.userData.placedPlant = true; group.add(holder);
        if (viewing) { holder.userData.viewingTree = true; holder.name = `tree:${index}`; }
        if (!cards.has(p.preset)) cards.set(p.preset, await bakePreset(p.preset, p.seed ?? 1, baker));
        const card = cards.get(p.preset), h = p.height * 1.08;
        for (const angle of [0, Math.PI / 2]) {
          const geometry = new THREE.PlaneGeometry(h * card.aspect, h).translate(0, h / 2, 0).rotateY(angle + (p.seed || 0) * 2.39996);
          addMesh(holder, geometry, card.material);
        }
        applyObject(holder, p, { units: 1 }); holder.position.set(p.at[0], groundAt(plan, ...p.at) + (p.elevation || 0), -p.at[1]);
        if (viewing) mergeStatic(holder);
      } else {
        const tree = new Tree(); tree.loadPreset(p.preset); tree.options.seed = p.seed ?? 1; tree.generate(); standardTree(tree);
        const bounds = new THREE.Box3().setFromObject(tree), h = bounds.max.y - bounds.min.y, scale = p.height / Math.max(0.01, h);
        tree.scale.setScalar(scale);
        applyObject(tree, p, { units: 1 });
        tree.position.set(p.at[0], groundAt(plan, ...p.at) + (p.elevation || 0) - bounds.min.y * scale * (p.scale ?? 1) * (p.scale_axes?.[1] ?? 1), -p.at[1]);
        tree.rotation.y += (p.seed || 0) * 2.39996; group.add(tree);
        if (viewing) { tree.userData.viewingTree = true; tree.name = `tree:${index}`; }
      }
      // Let loading/status controls paint while full presets are generated.
      if (index % 4 === 0) await new Promise(resolve => setTimeout(resolve, 0));
    }
  } finally { if (baker) { baker.dispose(); baker.forceContextLoss(); } }
  // Merge only the static site and cards. Full trees keep their own materials
  // and EZ-Tree geometry; they are not traversed by this static merge.
  const plants = group.children.filter(o => o instanceof Tree || o.userData.placedPlant); plants.forEach(o => o.removeFromParent());
  mergeStatic(group); plants.forEach(o => group.add(o));

  const models = new Map(), latePlacements = new Map();
  const placements = await Promise.all([...(site.furniture || []), ...(site.planting || []).filter(p => p.asset?.startsWith('import-'))].filter(f => objectShown(f, !viewing)).map(async f => {
    const assetId = (f.asset || kit.furniture?.[f.kind] || '').replace(/^polyhaven:/, '');
    if (!assetId || !f.at) return;
    const place = (model, late = false) => {
      if (group.userData.disposed) { disposeObject(model); return; }
      applyObject(model, f, { id: `site:${f.id || f.at.join(',')}` });
      let elevation = groundAt(plan, ...f.at);
      for (const b of plan.buildings || []) for (const porch of allPorches(b)) if (porch.polygon) {
        const pos = b.position || [0, 0], angle = -(b.rotation || 0) * Math.PI / 180;
        const x = f.at[0] - pos[0], y = f.at[1] - pos[1];
        if (inside([Math.cos(angle) * x - Math.sin(angle) * y, Math.sin(angle) * x + Math.cos(angle) * y], porch.polygon)) elevation = groundAt(plan, ...pos) + (b.base || 0) + porch.floor;
      }
      model.position.set(f.at[0], elevation + (f.elevation || 0), -f.at[1]);
      if (late) { group.add(model); mergeStatic(model); }
      return model;
    };
    if (!models.has(assetId)) {
      latePlacements.set(assetId, []);
      models.set(assetId, loadModel(assetId, kit, source => {
        if (group.userData.disposed) { disposeObject(source); return; }
        for (const draw of latePlacements.get(assetId)) draw(source.clone(true), true);
      }, { tier }));
    }
    latePlacements.get(assetId).push(place);
    const source = await models.get(assetId);
    return source ? place(source.clone(true)) : null;
  }));
  placements.filter(Boolean).forEach(model => group.add(model));
  // Merge model instances by their shared material as well, without folding
  // in full plants. Multi-material glTF primitives remain independently drawn.
  plants.forEach(o => o.removeFromParent()); mergeStatic(group); plants.forEach(o => group.add(o));

  if (tier === 'high') {
    const placements = [], rng = random(1);
    for (const edge of site.edges || []) {
      const line = edge.points || edge.polyline || [];
      for (let i = 0; i < line.length - 1; i++) {
        const a = line[i], b = line[i + 1], length = Math.hypot(b[0] - a[0], b[1] - a[1]);
        for (let d = 0; d < length; d += 0.18) placements.push([a[0] + (b[0] - a[0]) * d / length + (rng() - 0.5) * 0.4, -a[1] - (b[1] - a[1]) * d / length + (rng() - 0.5) * 0.4, rng()]);
      }
    }
    if (placements.length) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute([-0.035, 0, 0, 0.035, 0, 0, 0.03, 0.45, 0], 3));
      geo.computeVertexNormals();
      const grass = new THREE.InstancedMesh(geo, plain('edge grass', '#56783a', { side: THREE.DoubleSide }), placements.length), dummy = new THREE.Object3D();
      placements.forEach(([x, z, n], i) => { dummy.position.set(x, groundAt(plan, x, -z) + 0.12, z); dummy.rotation.y = n * Math.PI * 2; dummy.scale.setScalar(0.6 + n); dummy.updateMatrix(); grass.setMatrixAt(i, dummy.matrix); });
      grass.receiveShadow = true; group.add(grass);
    }
  }
  await Promise.all([...mats.values()].map(m => m.userData.ready));
  let triangles = 0;
  group.traverse(o => { if (o.isMesh) triangles += (o.geometry.index?.count || o.geometry.attributes.position.count) / 3 * (o.isInstancedMesh ? o.count : 1); });
  // EZ-Tree textures are shared by its module, unlike all other yard resources.
  group.userData.releasePlants = () => { plants.forEach(p => { releasePlant(p); p.removeFromParent(); }); cards.forEach(c => { c.material.dispose(); c.texture.dispose(); }); };
  return { group, triangles };
}
