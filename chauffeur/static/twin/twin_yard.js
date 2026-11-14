import { applyObject, objectShown, objectMaterialKey, sitePieces } from './objects.js';
import * as THREE from 'three';
import * as EZTree from '@dgreenheck/ez-tree';
const { Tree } = EZTree;

// EZ-Tree's loadPreset() copies the preset and generates the whole tree; the saved seed then
// needs a second generate(), so every plant was built twice and the first thrown away (about
// half of all yard build time, found 2026-11-13). Copy the preset's options, set the seed,
// generate once. Without a preset table (a stand-in Tree) it falls back to loadPreset.
export function presetTree(preset, seed) {
  const tree = new Tree(), options = EZTree.TreePreset?.[preset];
  if (options && tree.options?.copy) tree.options.copy(structuredClone(options));
  else tree.loadPreset(preset);
  tree.options.seed = seed; tree.generate();
  return tree;
}
import { FT, addMesh, boxGeometry, boxRect, polygon, mergeStatic, allPorches } from './twin_generator.js';
import { kitMaterial, materialSlot, materialKey, loadModel, disposeObject, cacheModelMaterials, manifest, modelAssetKey } from './twin_library.js';
import { groundAt, buildingBase, buildingFootprint } from './twin_ground.js';
import { span as editSpan } from './edit_timing.js';
import { terrainGeometry, terrainSlabGeometry, drapeGeometry, tintGrade } from './twin_terrain_mesh.js';
import { pathBoundaries, pathSurfacePolygons } from './path_shapes.js';
import { firePitRings, firePitOptions, roundPit, buildFirePit, fireFlameMaterial } from './fire_pits.js';
import { porchFoundationRole } from './twin_porch_foundation.js';
import { retainingWallGeometry, retainingWallRole } from './twin_retaining_wall.js';
import { buildPoolFeatures, cutSurface } from './pool_features.js';

function random(seed) {
  let n = seed | 0;
  return () => { n = n + 0x6d2b79f5 | 0; let t = Math.imul(n ^ n >>> 15, n | 1); t ^= t + Math.imul(t ^ t >>> 7, t | 61); return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

function standardTree(tree, cache = null) {
  const converted = new Map();
  tree.traverse(o => {
    if (!o.isMesh) return;
    const convert = m => {
      const key = 'tree:' + JSON.stringify([m.name, m.map?.uuid, m.normalMap?.uuid, m.alphaMap?.uuid, m.alphaTest, m.side, m.color?.getHex()]);
      if (!converted.has(m)) converted.set(m, cache?.get(key) || new THREE.MeshStandardMaterial({
        name: m.name, color: m.map ? '#ffffff' : m.color, map: m.map, normalMap: m.normalMap,
        alphaMap: m.alphaMap, alphaTest: m.alphaTest > 0 ? Math.max(0.5, m.alphaTest) : 0,
        side: m.side, roughness: 0.9,
      }));
      if (cache) cache.set(key, converted.get(m));
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
function releasePlant(tree, keepMaterials = new Set()) {
  tree.traverse(o => { o.geometry?.dispose(); for (const m of o.material ? [].concat(o.material) : []) if (!keepMaterials.has(m)) m.dispose(); });
}

async function bakePreset(preset, seed, renderer) {
  const tree = presetTree(preset, seed);
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

function yardMaterialKit(plan, kit) {
  const materialKit = { ...kit, materials: { ...kit.materials } }, known = manifest(kit);
  for (const [role, ref] of Object.entries(plan.materials || {})) {
    const source = kit.materials?.[ref.id] || kit.materials?.[role];
    materialKit.materials[role] = { ...source, color: ref.color || (known[ref.id]?.household ? undefined : source?.color), asset: known[ref.id] ? ref.id : source?.asset };
  }
  return materialKit;
}

function yardMaterialInputs(plan, kit) {
  const site = plan.site || {}, refs = yardMaterialKit(plan, kit).materials, known = manifest(kit);
  // Only yard roles participate: a siding override must not invalidate the
  // yard. Mirror mat/materialSlot's named-or-asset-alias resolution, retaining
  // full refs/manifest metadata so material revisions also invalidate caches.
  const roles = new Set(), slots = [];
  const use = (fallback, value) => {
    if (value) {
      const role = refs[value.id] ? value.id : Object.keys(refs).find(k => refs[k].asset === value.id);
      const ref = refs[role];
      slots.push([value, role, ref, known[ref?.id || ref?.asset || value.id]]);
    } else roles.add(fallback);
  };
  const authoredRole = (value, fallback) => kit.materials?.[value] ? value : fallback;
  if (site.lot?.length >= 3) use('lawn');
  for (const pad of site.terraces || []) pad.polygon.forEach((_, edge) => {
    const e = pad.edges?.[edge];
    if (e?.edge === 'sharp' && e.wall) use(retainingWallRole(e.wall.material), e.wall.materials?.face);
  });
  for (const h of site.hardscape || []) if (h.kind === 'path' || h.polygon?.length >= 3) {
    use(h.material === 'concrete' ? 'patio_concrete' : authoredRole(h.material, 'paving'), h.materials?.surface);
    if (h.kind === 'path' && h.edging === 'curb') use('patio_concrete', h.materials?.edging);
  }
  if (site.pool?.polygon?.length >= 3) {
    if (site.pool.materials?.interior) use('paving', site.pool.materials.interior);
    if ((site.pool.coping ?? 1) > 0) use(authoredRole(site.pool.material, 'paving'), site.pool.materials?.coping);
    for (const f of site.pool.features || []) if (f.kind === 'spa') {
      use(authoredRole(site.pool.material, 'paving'), f.materials?.coping || site.pool.materials?.coping);
      if (f.materials?.interior || site.pool.materials?.interior) use('paving', f.materials?.interior || site.pool.materials?.interior);
      use('base', f.materials?.wall);
    }
  }
  for (const f of sitePieces(site.fire_pit)) {
    const options = firePitOptions(f);
    use(porchFoundationRole(options.body), f.materials?.body);
    if (options.top !== 'none') use(options.top === 'granite' ? 'granite' : 'patio_concrete', f.materials?.top);
    if (options.fuel !== 'gas') use('counter');
  }
  for (const bed of site.beds || []) if (bed.polygon?.length >= 3) use(authoredRole(bed.material, 'mulch'), bed.materials?.fill);
  for (const edge of site.edges || []) if (edge.polygon?.length >= 3) use(authoredRole(edge.material, 'lawn'), edge.materials?.strip);
  for (const f of sitePieces(site.fence)) if (f.polyline?.length > 1)
    for (const part of ['boards', 'posts', 'rails']) use('fence', f.materials?.[part]);
  return { roles: [...roles].sort().map(role => [role, refs[role], known[refs[role]?.id || refs[role]?.asset]]), slots };
}

export const yardMaterialKey = (plan, kit, tier) => JSON.stringify([tier, yardMaterialInputs(plan, kit)]);

const fields = (value, names) => names.split(' ').map(k => value?.[k]);
const objectFields = 'id kind asset at elevation visible_in scale scale_axes pitch rotation roll tint casts_shadow object_kind emissive emissive_color light_entity preset height seed';
function yardSiteInputs(site) {
  return [site.lot, (site.terraces || []).map(p => [p.polygon, p.height, p.blend,
    (p.edges || []).map(e => [e.edge, e.wall && fields(e.wall, 'material thickness_in above_in materials')])]),
    (site.hardscape || []).map(h => fields(h, 'kind polygon points width corner smooth radius edging elevation material materials')),
    site.pool && fields(site.pool, 'polygon depth coping elevation material materials features'),
    sitePieces(site.fire_pit).map(f => fields(f, 'id shape at radius rotation polygon fuel body top height_in glass entity elevation materials')),
    (site.beds || []).map(b => fields(b, 'polygon elevation material materials')),
    (site.edges || []).map(e => fields(e, 'polygon points polyline elevation material materials')),
    sitePieces(site.fence).map(f => fields(f, 'polyline height elevation materials')),
    (site.planting || []).map(p => fields(p, objectFields)), (site.furniture || []).map(f => fields(f, objectFields))];
}

// Yard inputs: site.lot; ordered terraces (polygon/height/blend/edges/walls);
// hardscape, pool, fire_pit, beds, edges, fence, planting and furniture records
// (geometry, elevations, material slots, visibility, transforms, tint, shadows,
// lights, presets/seeds and asset refs). The projections above omit authoring
// metadata. yard_rooms are navigation only, not drawn here.
// Building inputs are placement/rotation, base and auto-foundation mode/offset,
// buildingFootprint (levels' elevation/id/outline, or rooms' level/polygon and
// walls' from/to fallback), first level id,
// allPorches' polygon/level/floor and porch rooms' level/state/polygon/floor offset.
// These position furniture on porches; building/porch foundations are drawn by
// buildTwin, not the yard. Terrain holes/skirts read only terraces and the pool.
// Materials: kit.materials with plan.materials overrides for used yard roles,
// slot id/color refs and alias selection; kit.manifest || window.twinManifest
// entries, including any household revisions;
// model refs resolve through kit.furniture and manifest/import metadata (LODs).
// Finally tier and viewing affect tessellation, maps, trees/cards and visibility.
// No building finish, roof, opening, anchor or indoor furnishing is a yard input.
// Equal outlines compare equal. The server can re-derive a porch or footprint outline
// with extra collinear corners and float noise (found in Chromium, 2026-11-13: the first
// edit after a load re-derived a porch and rebuilt the yard). Rounded to 0.01 ft, repeated
// and collinear corners dropped, counter-clockwise, starting at the lowest-leftmost corner.
export function canonicalOutline(points) {
  if (!Array.isArray(points)) return points ?? null;
  const r = v => Math.round(v * 100) / 100;
  const p = points.map(q => [r(q[0]), r(q[1])])
    .filter((q, i, a) => i === 0 || q[0] !== a[i - 1][0] || q[1] !== a[i - 1][1]);
  if (p.length > 1 && p[0][0] === p.at(-1)[0] && p[0][1] === p.at(-1)[1]) p.pop();
  for (let i = 0; p.length > 3 && i < p.length;) {
    const a = p[(i + p.length - 1) % p.length], b = p[i], c = p[(i + 1) % p.length];
    if (Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1e-3) { p.splice(i, 1); i = 0; } else i++;
  }
  if (p.reduce((sum, q, i) => sum + q[0] * p[(i + 1) % p.length][1] - p[(i + 1) % p.length][0] * q[1], 0) < 0) p.reverse();
  const start = p.reduce((m, q, i) => q[1] < p[m][1] || q[1] === p[m][1] && q[0] < p[m][0] ? i : m, 0);
  return [...p.slice(start), ...p.slice(0, start)];
}

export function yardKey(plan, kit, tier, { viewing = false } = {}) {
  const site = plan.site || {};
  const models = [...(site.furniture || []), ...(site.planting || []).filter(p => p.asset?.startsWith('import-'))]
    .map(f => (f.asset || kit.furniture?.[f.kind] || '').replace(/^polyhaven:/, ''));
  return JSON.stringify([tier, viewing,
    yardSiteInputs(site),
    (plan.buildings || []).map(b => [b.position, b.rotation, b.base, b.foundation?.mode, b.foundation?.offset_ft,
      canonicalOutline(buildingFootprint(b)), b.levels?.[0]?.id, allPorches(b).map(p => [canonicalOutline(p.polygon), p.level, p.floor]),
      (b.rooms || []).filter(r => r.kind === 'porch').map(r => [r.level, r.state, canonicalOutline(r.polygon), r.floor_offset_ft])]),
    yardMaterialInputs(plan, kit), models.map(id => [id, modelAssetKey(id, kit)])]);
}

export async function buildYard(plan, kit, tier, { viewing = false, materials = null, timing = null } = {}) {
  const group = new THREE.Group(); group.name = 'yard';
  const site = plan.site || {}, mats = materials || new Map();
  const spas = (site.pool?.features || []).filter(f => f.kind === 'spa').map(f => f.polygon);
  group.userData.materials = mats;
  const surface = (poly, z0, z1 = z0, holes = []) => {
    if (z0 === z1) return terrainGeometry(plan, poly, tier, { holes, offset: z0 });
    return terrainSlabGeometry(plan, poly, tier, z0, z1, holes);
  };
  const materialKit = yardMaterialKit(plan, kit);
  const mat = (role, slot = null) => {
    if (slot) return materialSlot(slot, role, materialKit, tier, mats, mat);
    const sourceRole = role === 'terrain_lawn' ? 'lawn' : role;
    const key = materialKey(materialKit.materials[sourceRole] || {}, role, tier, manifest(materialKit));
    if (!mats.has(key)) mats.set(key, kitMaterial(sourceRole, materialKit, tier));
    return mats.get(key);
  };
  const plain = (name, color, extra = {}) => {
    if (!mats.has(name)) mats.set(name, extra.fireShader ? fireFlameMaterial() : new THREE.MeshStandardMaterial({ name, color, roughness: 0.85, ...extra }));
    return mats.get(name);
  };
  const part = name => editSpan(timing, 'yard_' + name);
  if (timing) for (const name of ['terrain', 'grass', 'plants', 'fences', 'hardscape', 'pool', 'fire_pits', 'retaining_walls', 'cards', 'batch', 'models', 'materials']) timing['yard_' + name] = 0;
  const stopTerrain = part('terrain');
  if (site.lot?.length >= 3) {
    // Actual lawn material; no procedural canvas noise or substitute blobs.
    const pool = site.pool?.polygon;
    const xs = site.lot.map(p => p[0]), ys = site.lot.map(p => p[1]), margin = 150;
    const x0 = Math.min(...xs) - margin, x1 = Math.max(...xs) + margin;
    const y0 = Math.min(...ys) - margin, y1 = Math.max(...ys) + margin;
    // Continue the terrain below the lot edge without covering the sunken pool.
    // The distant continuation is flat and cheap. The lot and its blend bands
    // are the sampled surface; don't put a flat sheet through descending pads.
    const reach = 50;
    const terrainOutline = [[x0 + margin - reach, y0 + margin - reach], [x1 - margin + reach, y0 + margin - reach],
      [x1 - margin + reach, y1 - margin + reach], [x0 + margin - reach, y1 - margin + reach]];
    addMesh(group, polygon([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], -.06, -.06, [terrainOutline]), mat('lawn'));
    const terrain = new THREE.Group(); terrain.userData.viewingWalls = 'terrain'; group.add(terrain);
    const lawn = mat('terrain_lawn');
    // Same kit role, same texture. Vertex colours are always enabled; Grade
    // changes the buffer, never a material define or shader program.
    lawn.vertexColors = true; lawn.side = THREE.DoubleSide;
    const mesh = addMesh(terrain, terrainGeometry(plan, terrainOutline, tier, { holes: [...(pool ? [pool] : []), ...spas], offset: -.04, skirts: true }), lawn);
    mesh.userData.terrain = true;
    // Grade's vertex colours already keep this grid out of static merging.
    // Keep the exclusion explicit if a future merge path accepts colours.
    mesh.geometry.userData.bakeExcluded = true;
    // Yard lights bake onto the ground (user, 2026-11-13): the atlas charts it top-down.
    mesh.geometry.userData.bakeHeightfield = true;
    tintGrade(mesh.geometry, false);
  }
  stopTerrain();
  const stopWalls = part('retaining_walls');
  for (const pad of site.terraces || []) pad.polygon.forEach((_, edge) => {
    if (pad.edges?.[edge]?.edge !== 'sharp' || !pad.edges[edge].wall) return;
    const wall = pad.edges[edge].wall;
    addMesh(group, retainingWallGeometry(plan, pad, edge), mat(retainingWallRole(wall.material), wall.materials?.face));
  });
  stopWalls();
  const pool = site.pool?.polygon;
  const stopHardscape = part('hardscape');
  const inside = (p, poly) => { let v = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) if ((poly[i][1] > p[1]) !== (poly[j][1] > p[1]) && p[0] < (poly[j][0] - poly[i][0]) * (p[1] - poly[i][1]) / (poly[j][1] - poly[i][1]) + poly[i][0]) v = !v; return v; };
  for (const h of site.hardscape || []) if (h.kind === 'path' || h.polygon?.length >= 3) {
    const role = h.material === 'concrete' ? 'patio_concrete' : kit.materials?.[h.material] ? h.material : 'paving';
    if (h.kind === 'path') {
      // Swept pieces retain user-drawn crossings without even/odd cancellation.
      for (const poly of pathSurfacePolygons(h)) addMesh(group, surface(poly, h.elevation || 0, .3 + (h.elevation || 0), spas), mat(role, h.materials?.surface));
      if (h.edging === 'curb') {
        const inner = pathBoundaries(h), outer = pathBoundaries(h, (h.width ?? 3) / 2 + .5);
        for (const side of ['left', 'right']) for (let i = 1; i < inner[side].length; i++) {
          const poly = [inner[side][i - 1], inner[side][i], outer[side][i], outer[side][i - 1]];
          // Both offsets have the same mitre/bevel topology.
          const curb = addMesh(group, surface(poly, .3 + (h.elevation || 0), .55 + (h.elevation || 0), spas), mat('patio_concrete', h.materials?.edging));
          curb.geometry.userData.pathCurb = true;
        }
      }
      continue;
    }
    const holes = [...(pool && pool.every(p => inside(p, h.polygon)) ? [pool] : []), ...spas];
    addMesh(group, surface(h.polygon, h.elevation || 0, .3 + (h.elevation || 0), holes), mat(role, h.materials?.surface));
  }
  stopHardscape();
  const stopPool = part('pool');
  if (pool?.length >= 3) {
    const d = site.pool.depth ?? 5, coping = site.pool.coping ?? 1;
    const poolHeight = groundAt(plan, ...pool[0]) + (site.pool.elevation || 0);
    const poolSurface = (poly, z0, z1 = z0, holes = []) => spas.length
      ? cutSurface(poly, spas, poolHeight + z0, poolHeight + z1, holes)
      : polygon(poly, poolHeight + z0, poolHeight + z1, holes);
    const interior = site.pool.materials?.interior;
    addMesh(group, poolSurface(pool, -d - 0.2, -d), interior ? mat('paving', interior) : plain('pool tile', '#5fa8c4', { roughness: 0.35 }));
    // Offset each edge outwards by coping width. This works for the convex pool
    // polygons used by the plan and retains the original water outline.
    const area = pool.reduce((a, p, i) => a + p[0] * pool[(i + 1) % pool.length][1] - pool[(i + 1) % pool.length][0] * p[1], 0);
    const normal = (a, b) => { const l = Math.hypot(b[0] - a[0], b[1] - a[1]); return area > 0 ? [(b[1] - a[1]) / l, -(b[0] - a[0]) / l] : [-(b[1] - a[1]) / l, (b[0] - a[0]) / l]; };
    const outer = pool.map((p, i) => {
      const a = normal(pool[(i + pool.length - 1) % pool.length], p), b = normal(p, pool[(i + 1) % pool.length]), factor = coping / Math.max(0.1, 1 + a[0] * b[0] + a[1] * b[1]);
      return [p[0] + (a[0] + b[0]) * factor, p[1] + (a[1] + b[1]) * factor];
    });
    if (coping > 0) addMesh(group, poolSurface(outer, 0.3, 0.45, [pool]), mat(kit.materials?.[site.pool.material] ? site.pool.material : 'paving', site.pool.materials?.coping));
    for (let i = 0; i < pool.length; i++) {
      const a = pool[i], b = pool[(i + 1) % pool.length], n = normal(a, b);
      addMesh(group, poolSurface([a, b, [b[0] + n[0] * 0.25, b[1] + n[1] * 0.25], [a[0] + n[0] * 0.25, a[1] + n[1] * 0.25]], -d, 0.3), interior ? mat('paving', interior) : plain('pool tile', '#5fa8c4'));
    }
    const water = plain('water', '#7fd0e6', { transparent: true, opacity: 0.65, roughness: 0.12, depthWrite: false });
    addMesh(group, poolSurface(pool, -0.25), water);
    buildPoolFeatures(group, site.pool, poolHeight, { mat, plain, water, copingRole: kit.materials?.[site.pool.material] ? site.pool.material : 'paving' });
  }
  stopPool();
  const stopFirePits = part('fire_pits');
  for (const [index, f] of sitePieces(site.fire_pit).entries()) {
    const { outer } = firePitRings(f);
    const centre = outer.reduce((s,p)=>s.map((v,i)=>v+p[i]/outer.length),[0,0]);
    const height = groundAt(plan, ...centre) + (f.elevation || 0);
    buildFirePit(group,f,height,{mat,plain,id:'fire_pit:'+(f.id || index)});
    if (roundPit(f)) addMesh(group, drapeGeometry(new THREE.CircleGeometry((f.radius ?? 2) + 2, 32).rotateX(-Math.PI / 2).translate(f.at[0], 0.02, -f.at[1]), plan, f.elevation || 0), plain('gravel', '#a59c8f'));
  }
  stopFirePits();
  const stopBeds = part('hardscape');
  for (const bed of site.beds || []) if (bed.polygon?.length >= 3) addMesh(group, surface(bed.polygon, bed.elevation || 0, .12 + (bed.elevation || 0)), mat(kit.materials?.[bed.material] ? bed.material : 'mulch', bed.materials?.fill));
  for (const edge of site.edges || []) if (edge.polygon?.length >= 3) {
    // Edge planting remains a closed border. Give its ground strip the same
    // authored finish on every tier; High also keeps the existing grass blades.
    for (const poly of pathSurfacePolygons({ points: [...edge.polygon, edge.polygon[0]], width: .5 }))
      addMesh(group, surface(poly, edge.elevation || 0, .06 + (edge.elevation || 0)), mat(kit.materials?.[edge.material] ? edge.material : 'lawn', edge.materials?.strip));
  }
  stopBeds();
  const stopFences = part('fences');
  for (const f of sitePieces(site.fence).filter(f => f.polyline?.length > 1)) {
    const height = f.height || 6;
    const fenceMesh = (geometry, part) => addMesh(group, drapeGeometry(geometry, plan, f.elevation || 0), mat('fence', f.materials?.[part]));
    for (let i = 0; i < f.polyline.length - 1; i++) {
      const a = f.polyline[i], b = f.polyline[i + 1], dx = b[0] - a[0], dy = b[1] - a[1], length = Math.hypot(dx, dy), angle = Math.atan2(dy, dx);
      if (!length) continue;
      for (let d = 0.25; d < length; d += 0.5) fenceMesh(boxGeometry(0.46, height, 0.06).rotateY(angle).translate(a[0] + dx * d / length, height / 2 + 0.15, -a[1] - dy * d / length), 'boards');
      for (let d = 0; d <= length; d += 8) fenceMesh(boxRect(a[0] + dx * d / length - 0.17, a[1] + dy * d / length - 0.17, a[0] + dx * d / length + 0.17, a[1] + dy * d / length + 0.17, 0, height + 0.3), 'posts');
      // Rails bend with the ground at the slat spacing, so on a slope or a pad step they ride
      // the slat tops instead of spanning end to end in one straight piece.
      for (const y of [1, height - 0.6]) fenceMesh(boxGeometry(length, 0.3, 0.12, Math.max(1, Math.ceil(length / 0.5))).rotateY(angle).translate((a[0] + b[0]) / 2, y, -(a[1] + b[1]) / 2), 'rails');
    }
  }
  stopFences();
  const stopPlants = part(tier === 'low' ? 'cards' : 'plants');
  const cards = new Map();
  let baker = null;
  try {
    if (tier === 'low' && site.planting?.some(p => !mats.has('plant_card:' + p.preset))) baker = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
    for (let index = 0; index < (site.planting || []).length; index++) {
      const p = site.planting[index]; if (!objectShown(p, !viewing)) continue; if (!p.at || !p.preset || !(p.height > 0)) continue;
      if (tier === 'low') {
        const holder = new THREE.Group(); holder.userData.placedPlant = true; group.add(holder);
        if (viewing) { holder.userData.viewingTree = true; holder.name = `tree:${index}`; }
        if (!cards.has(p.preset)) {
          const cached = mats.get('plant_card:' + p.preset);
          const card = cached ? { material: cached, texture: cached.map, aspect: cached.userData.cardAspect }
            : await bakePreset(p.preset, p.seed ?? 1, baker);
          card.material.userData.cardAspect = card.aspect; mats.set('plant_card:' + p.preset, card.material); cards.set(p.preset, card);
        }
        const card = cards.get(p.preset), h = p.height * 1.08;
        for (const angle of [0, Math.PI / 2]) {
          const geometry = new THREE.PlaneGeometry(h * card.aspect, h).translate(0, h / 2, 0).rotateY(angle + (p.seed || 0) * 2.39996);
          addMesh(holder, geometry, card.material);
        }
        applyObject(holder, p, { units: 1 }); holder.position.set(p.at[0], groundAt(plan, ...p.at) + (p.elevation || 0), -p.at[1]);
        cacheModelMaterials(holder, 'plant-card:' + p.preset + ':' + objectMaterialKey(p, p.id || index), mats);
        if (viewing) mergeStatic(holder);
      } else {
        const tree = presetTree(p.preset, p.seed ?? 1); standardTree(tree, mats);
        const bounds = new THREE.Box3().setFromObject(tree), h = bounds.max.y - bounds.min.y, scale = p.height / Math.max(0.01, h);
        tree.scale.setScalar(scale);
        applyObject(tree, p, { units: 1 });
        cacheModelMaterials(tree, 'plant:' + p.preset + ':' + objectMaterialKey(p, p.id || index), mats);
        tree.position.set(p.at[0], groundAt(plan, ...p.at) + (p.elevation || 0) - bounds.min.y * scale * (p.scale ?? 1) * (p.scale_axes?.[1] ?? 1), -p.at[1]);
        tree.rotation.y += (p.seed || 0) * 2.39996; group.add(tree);
        if (viewing) { tree.userData.viewingTree = true; tree.name = `tree:${index}`; }
      }
      // Let loading/status controls paint while full presets are generated.
      if (index % 4 === 0) await new Promise(resolve => setTimeout(resolve, 0));
    }
  } finally { if (baker) { baker.dispose(); baker.forceContextLoss(); } }
  stopPlants();
  const stopBatch = part('batch');
  // Merge only the static site and cards. Full trees keep their own materials
  // and EZ-Tree geometry; they are not traversed by this static merge.
  const plants = group.children.filter(o => o instanceof Tree || o.userData.placedPlant); plants.forEach(o => o.removeFromParent());
  mergeStatic(group); plants.forEach(o => group.add(o));

  stopBatch();
  const stopModels = part('models');
  const models = new Map(), latePlacements = new Map();
  const placements = await Promise.all([...(site.furniture || []), ...(site.planting || []).filter(p => p.asset?.startsWith('import-'))].filter(f => objectShown(f, !viewing)).map(async f => {
    const assetId = (f.asset || kit.furniture?.[f.kind] || '').replace(/^polyhaven:/, '');
    if (!assetId || !f.at) return;
    const place = (model, late = false) => {
      if (group.userData.disposed) { disposeObject(model); return; }
      applyObject(model, f, { id: `site:${f.id || f.at.join(',')}` });
      cacheModelMaterials(model, 'yard:' + assetId + ':' + objectMaterialKey(f, `site:${f.id || f.at.join(',')}`), mats);
      let elevation = groundAt(plan, ...f.at);
      for (const b of plan.buildings || []) for (const porch of allPorches(b)) if (porch.polygon) {
        const pos = b.position || [0, 0], angle = -(b.rotation || 0) * Math.PI / 180;
        const x = f.at[0] - pos[0], y = f.at[1] - pos[1];
        const point = [Math.cos(angle) * x - Math.sin(angle) * y, Math.sin(angle) * x + Math.cos(angle) * y];
        if (inside(point, porch.polygon)) {
          const room = (b.rooms || []).find(r => r.kind === 'porch' && r.state !== 'ghost'
            && r.level === (porch.level || b.levels[0]?.id) && inside(point, r.polygon));
          elevation = buildingBase(plan, b) + porch.floor + (room?.floor_offset_ft || 0);
        }
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
      }, { tier, editor: !viewing }));
    }
    latePlacements.get(assetId).push(place);
    const source = await models.get(assetId);
    return source ? place(source.clone(true)) : null;
  }));
  placements.filter(Boolean).forEach(model => group.add(model));
  stopModels();
  const stopModelBatch = part('batch');
  // Merge model instances by their shared material as well, without folding
  // in full plants. Multi-material glTF primitives remain independently drawn.
  plants.forEach(o => o.removeFromParent()); mergeStatic(group); plants.forEach(o => group.add(o));

  stopModelBatch();
  const stopGrass = part('grass');
  if (tier === 'high') {
    const placements = [], rng = random(1);
    for (const edge of site.edges || []) {
      const line = edge.polygon ? [...edge.polygon, edge.polygon[0]] : edge.points || edge.polyline || [];
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
  stopGrass();
  const stopMaterials = part('materials');
  await Promise.all([...mats.values()].map(m => m.userData.ready));
  stopMaterials();
  let triangles = 0;
  group.traverse(o => { if (o.isMesh) triangles += (o.geometry.index?.count || o.geometry.attributes.position.count) / 3 * (o.isInstancedMesh ? o.count : 1); });
  // EZ-Tree textures are shared by its module, unlike all other yard resources.
  group.userData.releasePlants = (keepMaterials = new Set()) => {
    plants.forEach(p => { releasePlant(p, keepMaterials); p.removeFromParent(); });
    const textures = new Set(), kept = new Set([...keepMaterials].flatMap(m => Object.values(m).filter(v => v?.isTexture)));
    for (const [key, material] of mats) if (!keepMaterials.has(material)) {
      material.dispose();
      // EZ-Tree's module retains its bark/leaf textures, even after this view.
      if (!key.startsWith('tree:') && !key.startsWith('model:plant:')) for (const value of Object.values(material)) if (value?.isTexture && !kept.has(value)) textures.add(value);
    }
    textures.forEach(t => t.dispose());
  };
  // Snapshot after loads have resolved imported model metadata. Never compare
  // against a mutable old plan/kit; editor operations can update them in place.
  group.userData.yardKey = yardKey(plan, kit, tier, { viewing });
  group.userData.yardMaterialKey = yardMaterialKey(plan, kit, tier);
  return { group, triangles };
}
