import { span as editSpan } from './edit_timing.js';
import { createSkyCover, writeWeatherOpen } from './sky/sky_cover.js';
import { reflectionMaterial } from './reflection_probes.js';
import { applyObject, bakeMatrix, fitOpening, objectShown, objectMaterialKey } from './objects.js';
// Plan -> geometry. Plan x/y map to world X/-Z; heights are world Y.
// All geometry is in plan feet; only the returned root converts to metres.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { kitMaterial, materialSlot, materialKey, loadModel, disposeObject, cacheModelMaterials, currentMaterial, manifest, modelAssetKey, offsetSurfaceUvs, offsetSurfaceUvParts, alphaModeOf, copyMaterialParams } from './twin_library.js';
import { resolveSurfaceMaterial } from './surface_material.js';
import { supportMaterialSurface } from './support_material.js';
import { undersideMaterialSurface } from './underside_material.js';
import { withoutSurfaceMaterials, fingerprint } from './bake/geometry_key.js';
import { captureBakeMaterials, registerBakeSource, defaultBuildingFinishes, cloneBakeGeometry, BAKE_SOURCE_TIER } from './bake/source.js';
import { KINDS, BUILTIN_LOOKS, builtinAlphaMode, kindRow, resolveSlot } from './surface_kinds.js';
import { hostPoint, parkingPoint } from './twin_hosts.js';
import { roofEnvelope, roofMesh, roofBounds, heightAt, supportedRoofAbove, supportedRoofCutters, stepFaces, endKind, planes, authoredRoofShape } from './twin_roof.js';
import { isSupported, supportPoints, supportGeometry, supportFrame, roofPoint } from './roof_supports.js';
import { prepareUnderside, undersideGeometry } from './roof_underside.js';
import { GUTTER, gutterPlacement, buildingHasGutters, _gutterPlacementStats } from './gutters.js';
import { allPorches } from './gutter_presence.js';
export { allPorches } from './gutter_presence.js';
import { solarZones, solarPoint, solarRect } from './twin_solar.js';
import { groundAt, buildingBase, foundationShape } from './twin_ground.js';
import { PORCH_SLAB_FT, POST_SLAB_FT, porchFoundation, porchOnGrade, porchSupportGeometry, porchPlinthGeometry } from './twin_porch_foundation.js';
import { stairGeometry, doorwaySteps } from './twin_stairs.js';
import { roomFloor, roomAt, openingFloor, wallFloorProfile, foundationPieces, cutHeight } from './twin_floors.js';
import { ceilingPatches } from './twin_ceilings.js';
import { buildGarageDoor } from './garage_door.js';
import { buildEffects } from './effects/index.js';
import { LUCIDE } from '../vendor/lucide/icons.js';

import { FT } from './twin_light_math.js';
import { ROOF_THICKNESS, FASCIA } from './trim_dims.js';
export { FT } from './twin_light_math.js';
export { ROOF_THICKNESS, FASCIA } from './trim_dims.js';
export const PICK_LAYER = 31;

// Selection sees the slab and one bounded box per support, never the model's
// triangle soup. At count 40 this adds at most 480 triangles to EdgesGeometry.
export function roofOutlinePositions(slab, parts) {
  const positions = [...slab], boxes = new Map();
  for (const object of parts) {
    const id = object.userData.part;
    if (!/^support:\d+$/.test(id) || Number(id.slice(8)) >= 40) continue;
    object.geometry.computeBoundingBox();
    if (!boxes.has(id)) boxes.set(id, new THREE.Box3());
    boxes.get(id).union(object.geometry.boundingBox);
  }
  for (const box of boxes.values()) {
    if (box.isEmpty()) continue;
    const size = box.getSize(new THREE.Vector3()), centre = box.getCenter(new THREE.Vector3());
    const indexed = new THREE.BoxGeometry(size.x, size.y, size.z).translate(...centre.toArray());
    const geometry = indexed.toNonIndexed();
    positions.push(...geometry.attributes.position.array); geometry.dispose(); indexed.dispose();
  }
  return new Float32Array(positions);
}
export function mergeStatic(group, { perPiece = false } = {}) {
  group.updateMatrixWorld(true);
  const inverse = group.matrixWorld.clone().invert(), buckets = new Map();
  group.traverse(o => {
    // Independently faded viewing domains must never merge into their parent.
    for (let p = o.parent; p && p !== group; p = p.parent)
      if (p.userData.viewingWalls || p.userData.viewingTree || p.userData.supportedRoof) return;
    if (!o.isMesh || o.userData.part === 'ceiling' || o.userData.effectFixture || o.userData.garageDoor || o.userData.fireFlame || o.userData.modelLod || o.userData.pendingImport || o.userData.ghost || o.layers.isEnabled(PICK_LAYER) || o.isInstancedMesh || o.isSkinnedMesh || Array.isArray(o.material) || o.material?.vertexColors ||
        !o.geometry?.attributes.position || Object.keys(o.geometry.morphAttributes || {}).length) return;
    let g;
    try {
      g = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone();
      const count = g.attributes.position.count;
      if (g.attributes.position.itemSize !== 3 || !count || count % 3) { g.dispose(); return; }
      for (const key of Object.keys(g.attributes)) if (!['position', 'normal', 'uv', 'reflectionBodyCentre', 'seasonLeaf', 'weatherOpen'].includes(key)) g.deleteAttribute(key);
      if (!g.attributes.weatherOpen) g.setAttribute('weatherOpen', new THREE.Float32BufferAttribute(new Float32Array(count).fill(1), 1));
      if (g.attributes.normal?.count !== count || g.attributes.normal.itemSize !== 3) {
        g.deleteAttribute('normal'); g.computeVertexNormals();
      }
      if (g.attributes.uv?.count !== count || g.attributes.uv.itemSize !== 2) {
        g.setAttribute('uv', new THREE.Float32BufferAttribute(new Float32Array(count * 2), 2));
      }
      // glTF may supply interleaved, quantized or normalized attributes. Merge
      // a common float layout, including normals on position-only primitives.
      for (const key of ['position', 'normal', 'uv']) {
        const attr = g.attributes[key], data = new Float32Array(count * attr.itemSize);
        for (let i = 0; i < count; i++) for (let c = 0; c < attr.itemSize; c++) data[i * attr.itemSize + c] = attr.getComponent(i, c);
        g.setAttribute(key, new THREE.Float32BufferAttribute(data, attr.itemSize));
      }
      g.morphTargetsRelative = false;
      g.clearGroups();
      bakeMatrix(g, new THREE.Matrix4().multiplyMatrices(inverse, o.matrixWorld));
      // Models can use stand-ins/LODs: never fold their render-only geometry
      // into the same receiver as a house surface with a shared material.
      const key = `${o.material.uuid}:${!!o.geometry.userData.bakeExcluded}:${perPiece ? o.userData.pieceId || '' : ''}`;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push({ geometry: g, mesh: o });
    } catch { g?.dispose(); } // An odd optional model stays independently drawn.
  });
  const old = new Set();
  for (const entries of buckets.values()) {
    const mat = entries[0].mesh.material;
    let geometry;
    try { geometry = mergeGeometries(entries.map(e => e.geometry)); }
    catch { /* Keep the originals if a model cannot be merged. */ }
    finally { entries.forEach(e => e.geometry.dispose()); }
    if (!geometry) continue;
    entries.forEach(e => { e.mesh.removeFromParent(); old.add(e.mesh.geometry); });
    const mesh = new THREE.Mesh(geometry, mat);
    geometry.userData.bakeExcluded = !!entries[0].mesh.geometry.userData.bakeExcluded;
    mesh.userData.merged = true;
    if (entries.every(e => e.mesh.userData.surfaceKind === 'gutter')) mesh.userData.surfaceKind = 'gutter';
    // Preserve ownership through material batching, without splitting draw calls.
    // Ranges refer to the merged non-indexed position buffer.
    let start = 0;
    mesh.userData.snapRanges = entries.flatMap(e => {
      const d = e.mesh.userData, count = e.geometry.attributes.position.count;
      const ranges = d.snapRanges?.map(r => ({...r, start: r.start + start}))
        || [{start, count, kind: d.kind, visibilityKind: d.visibilityKind, pieceId: d.pieceId, parentPieceId: d.parentPieceId, buildingId: d.buildingId, part: d.part, bakePart:d.bakePart, ghost: d.ghost, terrain: d.terrain, ...(d.surfaceKind ? { surfaceKind: d.surfaceKind } : {})}];
      start += count; return ranges;
    });
    geometry.userData.snapRanges = mesh.userData.snapRanges;
    // Keep the piece registry pointing at live render objects after batching.
    entries.forEach(e => {
      const objects = e.mesh.userData.pieceObjects;
      if (objects) {
        const index = objects.indexOf(e.mesh);
        if (index >= 0) objects.splice(index, 1);
        if (!objects.includes(mesh)) objects.push(mesh);
      }
    });
    mesh.castShadow = (mat.userData?.castsShadow ?? true) && !mat.transparent;
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  const retained = new Set(); group.traverse(o => { if (o.geometry) retained.add(o.geometry); });
  old.forEach(g => { if (!retained.has(g)) g.dispose(); });
}

// BoxGeometry's face UVs span 0..1; the kit repeats every 4 (or 8) feet.
// Scale before rotating so each face has the same physical texture density.
export function boxGeometry(width, height, depth, widthSegments = 1) {
  const g = new THREE.BoxGeometry(width, height, depth, widthSegments), uv = g.attributes.uv, normal = g.attributes.normal;
  for (let i = 0; i < uv.count; i++) {
    const xFace = Math.abs(normal.getX(i)) > 0.5, yFace = Math.abs(normal.getY(i)) > 0.5;
    uv.setXY(i, uv.getX(i) * (xFace ? depth : width), uv.getY(i) * (yFace ? depth : height));
  }
  return g;
}

export function boxRect(x0, y0, x1, y1, z0, z1) {
  const g = boxGeometry(Math.abs(x1 - x0), Math.abs(z1 - z0), Math.abs(y1 - y0));
  return g.translate((x0 + x1) / 2, (z0 + z1) / 2, -(y0 + y1) / 2);
}
// A structural slab tops out this far under the floor finish laid on it.
const FLOOR_GAP_FT = 0.02;
export function polygon(poly, z0, z1 = z0, holes = []) {
  const s = new THREE.Shape(poly.map(p => new THREE.Vector2(...p)));
  holes.filter(h => h.length >= 3).forEach(h => s.holes.push(new THREE.Path(h.map(p => new THREE.Vector2(...p)))));
  const g = z1 === z0 ? new THREE.ShapeGeometry(s) : new THREE.ExtrudeGeometry(s, { depth: z1 - z0, bevelEnabled: false, steps: 1 });
  return g.rotateX(-Math.PI / 2).translate(0, z0, 0);
}
export function addMesh(group, geometry, material) {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = [].concat(material).some(m => (m.userData?.castsShadow ?? true) && !m.transparent); mesh.receiveShadow = true;
  group.add(mesh); return mesh;
}

function wallBasis(from, to, elevation) {
  const dx = to[0] - from[0], dy = to[1] - from[1], length = Math.hypot(dx, dy);
  const x = new THREE.Vector3(dx / length, 0, -dy / length), y = new THREE.Vector3(0, 1, 0);
  const z = new THREE.Vector3().crossVectors(x, y);
  const matrix = new THREE.Matrix4().makeBasis(x, y, z).setPosition(from[0], elevation, -from[1]);
  return { matrix, length, z };
}

// Join exterior walls rather than assuming the spike's 31 x 22 rectangle.
function footprints(walls) {
  const remaining = walls.filter(w => w.exterior && w.kind !== 'separator').map(w => [w.from, w.to]), out = [];
  const near = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) < 0.001;
  while (remaining.length) {
    const chain = remaining.shift().slice();
    while (!near(chain[0], chain.at(-1))) {
      const i = remaining.findIndex(([a, b]) => near(a, chain.at(-1)) || near(b, chain.at(-1)));
      if (i < 0) break;
      const [a, b] = remaining.splice(i, 1)[0];
      chain.push(near(a, chain.at(-1)) ? b : a);
    }
    if (chain.length > 3 && near(chain[0], chain.at(-1))) out.push(chain.slice(0, -1));
  }
  return out;
}

// Include edges: a wall on the next floor's outline supports its slab too.
export function contains(poly, [x, y]) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [ax, ay] = poly[j], [bx, by] = poly[i], dx = bx - ax, dy = by - ay;
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy || 1)));
    if (Math.hypot(x - ax - t * dx, y - ay - t * dy) < 1e-7) return true;
    if ((ay > y) !== (by > y) && x < ax + dx * (y - ay) / dy) inside = !inside;
  }
  return inside;
}

// The same stair cutouts serve authoritative floors and drag previews.
export function stairHoles(building, level) {
  return (building.stairs || []).filter(s => s.rise_to >= level.elevation
    && level.elevation > (building.levels.find(l => l.id === s.level)?.elevation ?? Infinity)).map(s => {
    const dx = s.to[0] - s.from[0], dy = s.to[1] - s.from[1], length = Math.hypot(dx, dy);
    const nx = -dy / length * s.width / 2, ny = dx / length * s.width / 2;
    return [[s.from[0] + nx, s.from[1] + ny], [s.to[0] + nx, s.to[1] + ny],
      [s.to[0] - nx, s.to[1] - ny], [s.from[0] - nx, s.from[1] - ny]];
  });
}

// One render mesh and one dashed line per ghost, even when wall openings or
// roof seams split it into many primitives. Domain index ranges retain floor
// and full/cut gable visibility without splitting the ghost into more draws.
function batchGhost(root, objects, material, edgeMaterial) {
  const sources = objects.slice(), geometries = [], edges = [], domains = new Map();
  let vertex = 0, edgeVertex = 0;
  for (const source of sources) {
    const geometry = source.geometry.index ? source.geometry.toNonIndexed() : source.geometry.clone();
    geometry.clearGroups();
    const edge = new THREE.EdgesGeometry(source.geometry);
    geometries.push(geometry); edges.push(edge);
    if (!domains.has(source.parent)) domains.set(source.parent, { faces: [], edges: [] });
    const domain = domains.get(source.parent);
    for (let i = 0; i < geometry.attributes.position.count; i++) domain.faces.push(vertex++);
    for (let i = 0; i < edge.attributes.position.count; i++) domain.edges.push(edgeVertex++);
  }
  const geometry = mergeGeometries(geometries), edgeGeometry = mergeGeometries(edges);
  geometries.forEach(g => g.dispose()); edges.forEach(g => g.dispose());
  const group = new THREE.Group(), parent = sources[0].parent;
  group.position.copy(parent.position); group.quaternion.copy(parent.quaternion); root.add(group);
  const mesh = addMesh(group, geometry, material), line = new THREE.LineSegments(edgeGeometry, edgeMaterial);
  Object.assign(mesh.userData, sources[0].userData); Object.assign(line.userData, mesh.userData);
  line.computeLineDistances(); group.add(line);
  // Retain the GPU index buffers when changing floors or gable cutaways.
  geometry.setIndex(new THREE.Uint32BufferAttribute(new Uint32Array(vertex), 1));
  edgeGeometry.setIndex(new THREE.Uint32BufferAttribute(new Uint32Array(edgeVertex), 1));
  sources.forEach(o => { o.removeFromParent(); o.geometry.dispose(); });
  objects.splice(0, objects.length, mesh, line);
  let previous = null;
  return () => {
    const shown = [...domains].filter(([domain]) => {
      for (let o = domain; o; o = o.parent) if (!o.visible) return false;
      return true;
    });
    const signature = shown.map(([domain]) => domain.uuid).join(':');
    if (signature === previous) return;
    previous = signature; group.visible = shown.length > 0;
    for (const [target, key] of [[geometry, 'faces'], [edgeGeometry, 'edges']]) {
      let count = 0;
      for (const [, ranges] of shown) { target.index.array.set(ranges[key], count); count += ranges[key].length; }
      target.index.needsUpdate = true; target.setDrawRange(0, count);
    }
  };
}

// A panel keeps the wall's mitred cross-section, clipped at opening edges.
// Its top is linear between roof samples, just like the legacy extrusion.
function footprintPanel(footprint, a, c, lo, ta, tc) {
  const height = x => ta + (tc - ta) * (x - a) / (c - a);
  let poly = footprint;
  for (const distance of [p => p[0] - a, p => c - p[0], p => height(p[0]) - lo]) {
    const clipped = [];
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i], q = poly[(i + 1) % poly.length], dp = distance(p), dq = distance(q);
      if (dp >= 0) clipped.push(p);
      if ((dp < 0) !== (dq < 0)) {
        const t = dp / (dp - dq);
        clipped.push(p.map((v, j) => v + t * (q[j] - v)));
      }
    }
    poly = clipped;
  }
  if (poly.length < 3) return [];
  const parts = { body: [], left: [], right: [] };
  const emit = (part, ...points) => parts[part].push(...points.flat());
  const bottom = p => [p[0], lo, p[1]], top = p => [p[0], Math.max(lo, height(p[0])), p[1]];
  // The footprint runs counter-clockwise in local x/depth.
  const onEdge = (p, edge) => {
    const q = footprint[edge], r = footprint[(edge + 1) % 4];
    return Math.abs((p[0] - q[0]) * (r[1] - q[1]) - (p[1] - q[1]) * (r[0] - q[0])) < 1e-6;
  };
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i], q = poly[(i + 1) % poly.length];
    const side = onEdge(p, 0) && onEdge(q, 0) ? 'left' : onEdge(p, 2) && onEdge(q, 2) ? 'right' : 'body';
    emit(side, bottom(q), bottom(p), top(p), bottom(q), top(p), top(q));
  }
  for (const indices of THREE.ShapeUtils.triangulateShape(poly.map(p => new THREE.Vector2(...p)), [])) {
    const [p, q, r] = indices.map(i => poly[i]);
    // triangulateShape returns CCW triangles in x/depth: their normal is down.
    emit('body', bottom(p), bottom(q), bottom(r), top(p), top(r), top(q));
  }
  return Object.entries(parts).filter(([, positions]) => positions.length).map(([side, positions]) => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.computeVertexNormals();
    const uv = [], normal = geometry.attributes.normal;
    for (let i = 0; i < positions.length; i += 3)
      uv.push(positions[i], Math.abs(normal.getY(i / 3)) > 0.5 ? positions[i + 2] : positions[i + 1]);
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    return [side, geometry];
  });
}

function materialKitWithRefs(kit, refs) {
  const materialKit = { ...kit, materials: { ...kit.materials } }, known = manifest(kit);
  for (const [role, ref] of Object.entries(refs || {})) {
    const source = kit.materials?.[ref.id] || kit.materials?.[role];
    materialKit.materials[role] = { ...source, color: ref.color || (known[ref.id]?.household ? undefined : source?.color),
      asset: known[ref.id] ? ref.id : source?.asset };
    if (known[ref.id]?.household) materialKit.materials[role].id = ref.id;
    else if (known[ref.id]) delete materialKit.materials[role].id;
  }
  return materialKit;
}

// Building inputs: the complete building record (including levels, walls/joints,
// rooms/floor offsets, openings, roof/roofs/solar zones, both porch forms, stairs,
// foundation, placement/base, fixtures/lights, anchors, items and their appearance).
// Finishes resolve plan -> building -> level/face/room/porch slot, against the
// kit's named roles/asset aliases and page_manifest (kit.manifest or the page's
// twinManifest), including household revisions. Only building roles participate;
// overridden plan refs and unrelated yard finishes/models do not invalidate it,
// except the supplementary plan-floor material explicitly built below.
// Ordered terrain pads within groundAt's reach of the building/porches/parking
// contribute polygon, height, blend and edge sharpness (never wall finishes).
// Imported opening/item metadata/LODs, tier, viewing, showAnchors, the building's
// editableLevel and global edit-mode object visibility also participate.
// Keep the mutation guard alongside these inputs.
function buildingKeyParts(plan, b, kit, tier, { viewing = false, showAnchors = false, editableLevel = null, gutters = null, modelTier = tier } = {}) {
  const known = manifest(kit), refs = { ...plan.materials, ...b.materials };
  const materialKit = materialKitWithRefs(kit, refs);
  const roles = new Set(['floor', 'patio_concrete', 'base']);
  if (b.levels?.length > 1) roles.add('interior_wall');
  if (b.walls?.length) { roles.add('siding'); roles.add('interior_wall'); }
  if (b.roof?.sections?.length) for (const r of ['roof', 'siding', 'trim', 'porch_ceiling']) roles.add(r);
  if (b.openings?.length) for (const r of ['window_frame', 'trim', 'door']) roles.add(r);
  if (b.stairs?.length) roles.add('porch_ceiling');
  const porches = allPorches(b);
  if (porches.length) for (const r of ['base', 'trim', 'lattice', 'patio_concrete', 'porch_ceiling']) roles.add(r);
  for (const f of b.fixtures || []) {
    if (['counter', 'vanity'].includes(f.kind) && !f.top) roles.add('counter');
    if (['fridge', 'grill'].includes(f.kind)) roles.add('stainless');
  }
  const resolved = (role, override = null) => {
    const ref = override || refs[role], source = kit.materials?.[ref?.id] || kit.materials?.[role];
    const effective = override ? materialKitWithRefs(kit, { ...refs, [role]: override }).materials[role] : materialKit.materials[role];
    return [role, ref, source, effective, known[effective?.id || effective?.asset]];
  };
  const finishes = [...roles].sort().map(role => resolved(role));
  const planFloor = materialKitWithRefs(kit, plan.materials).materials.floor;
  finishes.push(['supplementary-floor', planFloor, known[planFloor?.id || planFloor?.asset]]);
  for (const l of b.levels || []) for (const [role, ref] of Object.entries(l.materials || {})) if (roles.has(role)) finishes.push(resolved(role, ref));
  for (const w of b.walls || []) for (const ref of Object.values(w.faces || {})) finishes.push(resolved('siding', ref), resolved('interior_wall', ref));
  for (const r of b.rooms || []) {
    if (r.ceiling_material) finishes.push(resolved('ceiling', r.ceiling_material));
    if (r.wall_material) finishes.push(resolved('interior_wall', r.wall_material));
    if (r.floor_material) {
      finishes.push(resolved('floor', r.floor_material)); // also used by derived doorway steps
      if (r.kind === 'porch') finishes.push(resolved('patio_concrete', r.floor_material));
    }
  }
  // Flat sections include dormers and every part of a split model roof.
  // Their Library revisions must invalidate retained materials as room slots do.
  for (const s of b.roof?.sections || []) if (s.material) finishes.push(resolved('roof', s.material));
  for (const s of b.roof?.sections || []) for (const [edge, ref] of Object.entries(s.plane_materials || {}))
    finishes.push(['roof-plane', s.id, edge, resolved('roof', resolveSurfaceMaterial(plan,
      {role:'roof', building:b, level:(b.levels || []).find(l => l.id === s.level), ref, parents:[s.material], kit}).ref)]);
  for (const s of b.roof?.sections || []) if (s.materials?.gutter)
    finishes.push(['roof-section-surface', s.id, 'gutter', resolved('gutter', s.materials.gutter)]);
  for (const item of [...(b.openings || []), ...porches, ...(b.stairs || []), ...(b.fixtures || []), ...(b.items || []).filter(i => i.rect)])
    for (const [kind, slot] of Object.entries(item.materials || {}))
      if (slot && kindRow(kind)) finishes.push(['item-surface', item.id, kind, resolved(kind, slot)]);
  const slab = b.foundation?.materials?.slab;
  if (slab) finishes.push(['slab', slab, resolved('patio_concrete', slab), known[slab.id]]);
  for (const p of porches) for (const [slot, ref] of Object.entries(porchFoundation(p.foundation).materials)) if (ref) {
    const role = materialKit.materials[ref.id] ? ref.id : Object.keys(materialKit.materials).find(r => materialKit.materials[r].asset === ref.id);
    finishes.push([slot, ref, role, resolved(role || ref.id), known[ref.id]]);
  }
  // Existing kit roles already participate above. Append only authored new
  // kinds, including level defaults, to preserve every legacy key when unset.
  for (const row of KINDS) if (row.scope === 'building' && !roles.has(row.kind)) {
    const slot = resolveSlot(row.kind, { building: b });
    if (slot) finishes.push(['surface-kind', row.kind, resolved(row.kind, slot)]);
    for (const level of b.levels || []) if (level.materials?.[row.kind])
      finishes.push(['surface-kind', level.id, row.kind, resolved(row.kind, level.materials[row.kind])]);
  }
  const local = [...(b.walls || []).flatMap(w => [w.from, w.to]), ...(b.levels || []).flatMap(l => l.outline || []),
    ...(b.rooms || []).flatMap(r => r.polygon || []), ...porches.flatMap(p => p.polygon || []),
    ...(b.anchors || []).filter(a => a.host?.ground).map(a => a.host.at)].filter(Boolean);
  const angle = (b.rotation || 0) * Math.PI / 180, pos = b.position || [0, 0];
  const points = (local.length ? local : [[0, 0]]).map(([x, y]) => [pos[0] + x * Math.cos(angle) - y * Math.sin(angle), pos[1] + x * Math.sin(angle) + y * Math.cos(angle)]);
  const bounds = [0, 1].map(i => [Math.min(...points.map(p => p[i])), Math.max(...points.map(p => p[i]))]);
  const grade = (plan.site?.terraces || []).filter(p => [0, 1].every(i =>
    Math.max(...p.polygon.map(q => q[i])) + (p.blend ?? 6) >= bounds[i][0] &&
    Math.min(...p.polygon.map(q => q[i])) - (p.blend ?? 6) <= bounds[i][1]))
    .map(p => [p.polygon, p.height, p.blend, p.edges?.map(e => e.edge)]);
  const models = [...(b.items || []).filter(i => i.asset).map(i => i.asset.replace(/^polyhaven:/, '')),
    ...(b.openings || []).filter(o => o.model).map(o => o.model)].map(id => [id, modelAssetKey(id, kit)]);
  const editorObjects = !!(b.items?.length || b.fixtures?.length)
    || [...(b.lights || []), ...(b.anchors || [])].some(o => !o.device)
    || (b.openings || []).some(o => o.model);
  const fixedParts = [b, finishes, grade, tier, viewing, showAnchors,
    editableLevel?.startsWith(b.id + ':') ? editableLevel : null, editorObjects && !!editableLevel];
  if (buildingHasGutters(b, b.roof?.sections || [])) {
    const slice = gutters || sliceForBuilding(resolveGutterPlacement(plan), b.id);
    fixedParts.push(gutterSliceHash(slice));
  }
  return {
    fixed: JSON.stringify(fixedParts),
    finishes: JSON.stringify([finishes, tier]),
    models: JSON.stringify(modelTier === tier ? models : [...models, ['modelTier', modelTier]]),
  };
}
const keyFromParts = parts => JSON.stringify([parts.fixed, parts.models]);
export const buildingKey = (plan, building, kit, tier, opts) => keyFromParts(buildingKeyParts(plan, building, kit, tier, opts));

// A late import must publish into the currently adopted twin, even after its
// building has survived several rebuilds. The owner changes only at adoption.
class BuildingRegistry extends Map {
  revision = 0;
  touch() { ++this.revision; this.owner?.touch?.(); }
  set(key, value) { super.set(key, value); ++this.revision; this.owner?.set(key, value); return this; }
  delete(key) { this.owner?.delete(key); const removed = super.delete(key); if (removed) ++this.revision; return removed; }
}
const registries = ['pieces', 'pieceBounds', 'pickObjects', 'roofSurfaces'];

export function buildTwin(plan, kit, tier, { previous = null, ...opts } = {}) {
  const root = new THREE.Group(); root.scale.setScalar(FT);
  const groups = { site: new THREE.Group(), roof: new THREE.Group(), gableFull: new THREE.Group(), gableCut: new THREE.Group(), lights: new THREE.Group(), levels: {} };
  for (const [name, group] of Object.entries(groups)) if (group.isGroup) { group.name = name; root.add(group); }
  groups.gableCut.visible = false;
  const effects = buildEffects(plan, {tier, editor: !opts.viewing});
  if (effects) root.add(effects.group);
  const next = { root, groups, buildings: new Map(), materials: new Map(), roomLights: [], levelElevations: {}, notes: [], effects };
  for (const name of registries) next[name] = new BuildingRegistry();
  if (!opts.bakeSource) { _gutterPlacementStats.lastPlacementMs = 0; _gutterPlacementStats.lastGeometryMs = 0; }
  const placement = opts.gutters ?? resolveGutterPlacement(plan, opts.timing);
  next.gutters = placement;
  const reused = [], rebuilt = [];
  const copy = (entry, source = entry.model) => {
    for (const name of registries) for (const [key, value] of source[name])
      if (name === 'roofSurfaces' ? key === entry.id : key.startsWith(entry.id + ':')) next[name].set(key, value);
    for (const [key, value] of entry.model.materials) {
      // Preserve the public single-building role cache (reuseMaterials callers
      // feed it back verbatim); namespace only genuinely different instances.
      next.materials.set(next.materials.has(key) && next.materials.get(key) !== value ? `${entry.id}:${key}` : key, value);
    }
  };
  const attach = entry => {
    const model = entry.model;
    model.root.scale.setScalar(1); root.add(model.root); // ghost batches + late import lifetime
    for (const [name, domains] of Object.entries(entry.domains)) for (const group of domains) groups[name].add(group);
    for (const [key, group] of Object.entries(model.groups.levels)) { groups.levels[key] = group; root.add(group); }
    for (const name of registries) model[name].owner = next[name];
  };
  for (const b of plan.buildings || []) {
    const bOpts = { ...opts, gutters: sliceForBuilding(placement, b.id) };
    const inputs = buildingKeyParts(plan, b, kit, tier, bOpts), key = keyFromParts(inputs), old = previous?.buildings?.get(b.id);
    const reuse = old?.key === key && !old.model.stale && !old.model.degraded;
    const reuseMaterials = old && !old.model.degraded && old.finishes === inputs.finishes ? old.model.materials : opts.reuseMaterials;
    const entry = { id: b.id, key, inputs: inputs.fixed, finishes: inputs.finishes,
      model: reuse ? old.model : generateTwin({ ...plan, buildings: [b] }, kit, tier, { ...bOpts, reuseMaterials }) };
    entry.domains = reuse ? old.domains : Object.fromEntries(['roof', 'gableFull', 'gableCut', 'lights'].map(name => [name, [...entry.model.groups[name].children]]));
    next.buildings.set(b.id, entry); (reuse ? reused : rebuilt).push(b.id);
    // References are safe to copy now; scene ownership stays untouched until
    // twin_view's asynchronous work and revision check have both completed.
    copy(entry, reuse ? previous : entry.model);
    if (!reuse) attach(entry);
    else {
      for (const [key, group] of Object.entries(entry.model.groups.levels)) groups.levels[key] = group;
      if (opts.timing) {
        opts.timing.buildings.push({ id: b.id, generate: 0, levels: [] });
        ++opts.timing.counts.buildings; opts.timing.counts.levels += b.levels.length;
      }
    }
    next.roomLights.push(...entry.model.roomLights); Object.assign(next.levelElevations, entry.model.levelElevations); next.notes.push(...entry.model.notes);
  }
  let adopted = false;
  next.skyCover = createSkyCover(plan, next.roofSurfaces);
  writeWeatherOpen(root, next.skyCover);
  // Call after ready and the view's revision check, like yard.adoptParts.
  next.adoptBuildings = () => {
    if (adopted) return;
    for (const id of reused) { const entry = next.buildings.get(id); copy(entry, previous); attach(entry); }
    writeWeatherOpen(root, next.skyCover);
    adopted = true;
    previous = null; // Do not retain a chain of disposed twins across edits.
  };
  next.ready = Promise.all([...next.buildings.values()].map(e => e.model.ready)).then(() => {
    if (!adopted) for (const entry of next.buildings.values()) copy(entry, reused.includes(entry.id) ? previous : entry.model);
    // Import discovery may fill in model metadata during the asset wait. Never
    // certify a changed manifest/plan as the input that generated these buffers.
    for (const b of plan.buildings || []) {
      const entry = next.buildings.get(b.id), resolved = buildingKeyParts(plan, b, kit, tier, { ...opts, gutters: sliceForBuilding(placement, b.id) });
      if (resolved.fixed === entry.inputs) entry.key = keyFromParts(resolved);
    }
    writeWeatherOpen(root, next.skyCover);
    if (!opts.bakeSource) captureBakeMaterials(root);
  });
  next.updateGhosts = () => { for (const entry of next.buildings.values()) entry.model.updateGhosts(); };
  next.buildingsReused = reused; next.buildingsRebuilt = rebuilt;
  if (opts.timing) { opts.timing.buildings_reused = reused; opts.timing.buildings_rebuilt = rebuilt; }
  if (!opts.bakeSource) captureBakeMaterials(root);
  if (!opts.bakeSource) {
    const owned=[...root.children,...[...next.buildings.values()].map(entry=>entry.model.root),...Object.values(groups.levels)];
    registerBakeSource(root, () => !opts.editableLevel && defaultBuildingFinishes(plan,kit) ? cloneBakeGeometry(root,owned)
      : buildTwin(withoutSurfaceMaterials(plan), {...kit,manifest:{}}, BAKE_SOURCE_TIER,
        {viewing: !!opts.viewing, bakeSource: true, gutters: placement}).root, {children:owned});
  }
  return next;
}

const GUTTER_U0 = FASCIA.proudFt + 0.002;
// Lazily built so importing gutters.js before twin_generator.js never hits TDZ on GUTTER.
let _gutterProfileCache = null;
function gutterProfile() {
  if (_gutterProfileCache) return _gutterProfileCache;
  const depth = GUTTER.profileIn / 12;
  // 5 in K-style profile (7 vertices, open top, back flush against fascia face, bottom matching gutters.js gutterBottom).
  const profile = [
    [GUTTER_U0, 0],
    [GUTTER_U0, -depth],
    [GUTTER_U0 + 3.5 / 12, -depth],
    [GUTTER_U0 + 3.75 / 12, -3.4 / 12],
    [GUTTER_U0 + 4.45 / 12, -1.8 / 12],
    [GUTTER_U0 + 4.70 / 12, -0.7 / 12],
    [GUTTER_U0 + GUTTER.profileIn / 12, 0],
  ];
  const v = profile.reduce((acc, p, i) => {
    acc.push(i ? acc[i - 1] + Math.hypot(p[0] - profile[i - 1][0], p[1] - profile[i - 1][1]) : 0);
    return acc;
  }, []);
  _gutterProfileCache = { profile, v };
  return _gutterProfileCache;
}

export { _gutterPlacementStats } from './gutters.js';
function resolveGutterPlacement(plan, timing = null) { return gutterPlacement(plan, timing); }

function sliceForBuilding(placement, buildingId) {
  if (!placement || (!placement.runs?.length && !placement.spouts?.length)) return { runs: [], spouts: [] };
  const runs = (placement.runs || []).filter(r => r.building === buildingId);
  const runIds = new Set(runs.map(r => r.id));
  const spouts = (placement.spouts || []).filter(s => runIds.has(s.run));
  return { runs, spouts };
}

function gutterSliceHash(slice) {
  const h = fingerprint();
  h.add(JSON.stringify(slice));
  return h.key();
}

function buildGutterGeometry(b, base, runs, spouts, resolveFinish) {
  const { profile: GUTTER_PROFILE, v: GUTTER_PROFILE_V } = gutterProfile();
  const angle = (b.rotation || 0) * Math.PI / 180, cosA = Math.cos(angle), sinA = Math.sin(angle);
  const bx = b.position?.[0] || 0, by = b.position?.[1] || 0;
  const toLocal = ([wx, wy, wz]) => {
    const u = wx / FT - bx, v = -wz / FT - by;
    return [cosA * u + sinA * v, wy / FT - base, sinA * u - cosA * v];
  };
  const dirLocal = ([dx, dy, dz]) => {
    const u = dx, v = -dz;
    return [cosA * u + sinA * v, dy, sinA * u - cosA * v];
  };
  const unitXZ = ([x, , z]) => { const l = Math.hypot(x, z) || 1; return [x / l, 0, z / l]; };
  const touchJoint = (p, q) => Math.hypot(p[0] - q[0], p[2] - q[2]) <= GUTTER.runJoinFt + 0.02
    && Math.abs(p[1] - q[1]) <= 3 / 12 + 0.02;

  const buckets = new Map();
  let cur = null, gutterOwner = null;
  const selectBucket = info => {
    let bucket = buckets.get(info.key);
    if (!bucket) {
      bucket = { mat: info.mat, ref: info.ref, seed: info.seed, positions: [], uvs: [] };
      if (info.supportedRoof) bucket.supportedRoof = info.supportedRoof;
      if (info.supportedLevel) { bucket.supportedLevel = info.supportedLevel; bucket.ranges = []; }
      buckets.set(info.key, bucket);
    }
    cur = bucket;
    gutterOwner = info.supportedRoof || null;
  };
  const pushTri = (a, bPt, c, ua, ub, uc) => {
    if (gutterOwner) {
      const start = cur.positions.length / 3, previous = cur.ranges.at(-1);
      if (previous?.pieceId === gutterOwner && previous.start + previous.count === start) previous.count += 3;
      else cur.ranges.push({ start, count: 3, pieceId: gutterOwner, kind: 'roof', buildingId: b.id,
        part: 'gutter', bakePart: 'gutter', surfaceKind: 'gutter' });
    }
    cur.positions.push(a[0], a[1], a[2], bPt[0], bPt[1], bPt[2], c[0], c[1], c[2]);
    cur.uvs.push(ua[0], ua[1], ub[0], ub[1], uc[0], uc[1]);
  };
  const pushQuad = (a, bPt, c, d, ua, ub, uc, ud) => {
    pushTri(a, bPt, c, ua, ub, uc);
    pushTri(a, c, d, ua, uc, ud);
  };
  const ringPoint = (pt, mitre, p) => [pt[0] + mitre[0] * p[0], pt[1] + p[1], pt[2] + mitre[2] * p[0]];

  const runMap = new Map();
  for (const run of runs) {
    if (run.building !== b.id || !run.segments?.length) continue;
    runMap.set(run.id, run);
    const segs = run.segments.map(s => {
      const a = toLocal(s.a), bPt = toLocal(s.b), n = unitXZ([s.outward[0], 0, -s.outward[1]]);
      return { raw: s, a, b: bPt, n, startPt: [...a], endPt: [...bPt], startM: [...n], endM: [...n], hasStart: false, hasEnd: false };
    });
    const joinPair = (prev, next) => {
      if (!touchJoint(prev.b, next.a)) return;
      prev.hasEnd = true; next.hasStart = true;
      const sx = prev.n[0] + next.n[0], sz = prev.n[2] + next.n[2];
      const denom = prev.n[0] * sx + prev.n[2] * sz;
      if (denom > 0.25) {
        let mx = sx / denom, mz = sz / denom;
        const ml = Math.hypot(mx, mz);
        if (ml > 2.5) { mx *= 2.5 / ml; mz *= 2.5 / ml; }
        prev.endM = [mx, 0, mz]; next.startM = [mx, 0, mz];
      }
      const jx = (prev.b[0] + next.a[0]) / 2, jz = (prev.b[2] + next.a[2]) / 2;
      prev.endPt[0] = jx; prev.endPt[2] = jz;
      next.startPt[0] = jx; next.startPt[2] = jz;
      if (Math.abs(prev.b[1] - next.a[1]) <= 0.02) {
        const jy = (prev.b[1] + next.a[1]) / 2;
        prev.endPt[1] = jy; next.startPt[1] = jy;
      }
    };
    for (let i = 0; i + 1 < segs.length; i++) joinPair(segs[i], segs[i + 1]);
    if (segs.length >= 3) joinPair(segs[segs.length - 1], segs[0]);

    let runU = 0;
    for (let i = 0; i < segs.length; i++) {
      const s = segs[i];
      const dx = s.endPt[0] - s.startPt[0], dz = s.endPt[2] - s.startPt[2], len = Math.hypot(dx, dz);
      if (len < 1e-4) continue;
      selectBucket(resolveFinish(s.raw));
      const tx = dx / len, tz = dz / len;
      const flip = (tz * s.n[0] - tx * s.n[2]) > 0;
      const ringA = GUTTER_PROFILE.map(p => ringPoint(s.startPt, s.startM, p));
      const ringB = GUTTER_PROFILE.map(p => ringPoint(s.endPt, s.endM, p));
      for (let k = 0; k + 1 < GUTTER_PROFILE.length; k++) {
        const a0 = ringA[k], a1 = ringA[k + 1], b0 = ringB[k], b1 = ringB[k + 1];
        const v0 = GUTTER_PROFILE_V[k], v1 = GUTTER_PROFILE_V[k + 1];
        const u0 = runU, u1 = runU + len;
        if (!flip) {
          pushQuad(a0, b0, b1, a1, [u0, v0], [u1, v0], [u1, v1], [u0, v1]);
          pushQuad(a0, a1, b1, b0, [u0, v0], [u0, v1], [u1, v1], [u1, v0]);
        } else {
          pushQuad(a0, a1, b1, b0, [u0, v0], [u0, v1], [u1, v1], [u1, v0]);
          pushQuad(a0, b0, b1, a1, [u0, v0], [u1, v0], [u1, v1], [u0, v1]);
        }
      }
      const emitCap = (ring, outwardEnd) => {
        const outOrder = outwardEnd ? flip : !flip;
        for (let k = 1; k + 1 < GUTTER_PROFILE.length; k++) {
          const p0 = ring[0], p1 = ring[k], p2 = ring[k + 1];
          const u0 = GUTTER_PROFILE[0], u1 = GUTTER_PROFILE[k], u2 = GUTTER_PROFILE[k + 1];
          if (outOrder) {
            pushTri(p0, p1, p2, u0, u1, u2);
            pushTri(p0, p2, p1, u0, u2, u1);
          } else {
            pushTri(p0, p2, p1, u0, u2, u1);
            pushTri(p0, p1, p2, u0, u1, u2);
          }
        }
      };
      if (!s.hasStart) emitCap(ringA, false);
      if (!s.hasEnd) emitCap(ringB, true);
      // Close any small vertical step (2-3 in) at a joined pitched hip wrap.
      const next = i + 1 < segs.length ? segs[i + 1] : (segs.length >= 3 && s.hasEnd ? segs[0] : null);
      if (next && s.hasEnd && Math.abs(s.endPt[1] - next.startPt[1]) > 0.02) {
        const nextRing = GUTTER_PROFILE.map(p => ringPoint(next.startPt, next.startM, p));
        for (let k = 0; k + 1 < GUTTER_PROFILE.length; k++) {
          const v0 = GUTTER_PROFILE_V[k], v1 = GUTTER_PROFILE_V[k + 1];
          pushQuad(ringB[k], nextRing[k], nextRing[k + 1], ringB[k + 1], [0, v0], [0.2, v0], [0.2, v1], [0, v1]);
          pushQuad(ringB[k], ringB[k + 1], nextRing[k + 1], nextRing[k], [0, v0], [0, v1], [0.2, v1], [0.2, v0]);
        }
      }
      runU += len;
    }
  }

  // Downspouts: 2 x 3 in rectangular section (3 in side faces along the wall).
  const halfW = (GUTTER.spoutIn[1] / 2) / 12; // 1.5 in -> 3 in along wall
  const halfD = (GUTTER.spoutIn[0] / 2) / 12; // 1.0 in -> 2 in deep
  const CORNERS = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
  const emitBoxTube = (pTop, pBot, uVec, vVec, capTop = true) => {
    const h = pTop[1] - pBot[1];
    if (h < 1e-4) return;
    // Right-handed check with T = (0,-1,0): T x U = (u.z, 0, -u.x). Ensure V matches T x U.
    const tVec = new THREE.Vector3(0, -1, 0);
    const U = uVec.clone().normalize();
    const V = new THREE.Vector3().crossVectors(tVec, U).normalize();
    const ring = y => CORNERS.map(([cu, cv]) => [
      pTop[0] + cu * halfW * U.x + cv * halfD * V.x,
      y,
      pTop[2] + cu * halfW * U.z + cv * halfD * V.z,
    ]);
    const r0 = ring(pTop[1]), r1 = ring(pBot[1]);
    for (let k = 0; k < 4; k++) {
      const n = (k + 1) % 4, w = k % 2 === 0 ? halfW * 2 : halfD * 2;
      pushQuad(r0[k], r0[n], r1[n], r1[k], [0, 0], [w, 0], [w, h], [0, h]);
    }
    if (capTop) {
      pushQuad(r0[0], r0[3], r0[2], r0[1], [0, 0], [0, halfD * 2], [halfW * 2, halfD * 2], [halfW * 2, 0]);
    }
  };

  for (const spout of spouts) {
    const run = runMap.get(spout.run);
    if (!run) continue;
    const rawPts = (spout.path || []).map(toLocal);
    const owningSeg = run.segments.find(s => s.roof === spout.edge?.roof && s.edge === spout.edge?.edge && s.porch === spout.edge?.porch) || run.segments[0];
    selectBucket(resolveFinish(owningSeg));

    const isBlocked = (spout.flags || []).includes('outlet-blocked');
    if (isBlocked) {
      // Outlet jammed against a lower roof: emit only a flush 2 x 3 in outlet hole collar seated on the gutter floor.
      const outArr = owningSeg?.outward ? unitXZ([owningSeg.outward[0], 0, -owningSeg.outward[1]]) : unitXZ(dirLocal(spout.outlet?.dir || [0, 0, 1]));
      const V = new THREE.Vector3(outArr[0], 0, outArr[2]).normalize();
      // Match emitBoxTube handedness: T = (0, -1, 0) and T x U = V => U = (V.z, 0, -V.x).
      const U = new THREE.Vector3(V.z, 0, -V.x).normalize();
      const c = rawPts[0];
      if (c && c.every(Number.isFinite)) {
        const segA = owningSeg ? toLocal(owningSeg.a) : null;
        const segB = owningSeg ? toLocal(owningSeg.b) : null;
        const eaveY = segA && segB ? Math.min(segA[1], segB[1]) : c[1] + GUTTER.profileIn / 12;
        const gutterBotY = eaveY - GUTTER.profileIn / 12;
        const rimW = halfW + 0.03, rimD = halfD + 0.03, collarH = 0.018;
        // Keep the collar tucked cleanly inside open gutter end caps when blocked.top lies on an endpoint.
        let cx = c[0], cz = c[2];
        if (segA && segB) {
          const sdx = segB[0] - segA[0], sdz = segB[2] - segA[2], sLen = Math.hypot(sdx, sdz);
          const inset = rimW + 0.02;
          if (sLen > 2 * inset) {
            const tx = sdx / sLen, tz = sdz / sLen;
            const t = (cx - segA[0]) * tx + (cz - segA[2]) * tz;
            const tc = Math.max(inset, Math.min(sLen - inset, t));
            cx += (tc - t) * tx;
            cz += (tc - t) * tz;
          }
        }
        const pt = (u, v, y) => [cx + u * U.x + v * V.x, y, cz + u * U.z + v * V.z];
        const yBot = Math.min(c[1], gutterBotY), yTop = yBot + collarH;
        const outR = CORNERS.map(([cu, cv]) => [cu * rimW, cv * rimD]);
        const inR = CORNERS.map(([cu, cv]) => [cu * halfW, cv * halfD]);
        for (let k = 0; k < 4; k++) {
          const n = (k + 1) % 4;
          const aTop = pt(outR[k][0], outR[k][1], yTop), bTop = pt(outR[n][0], outR[n][1], yTop);
          const aBot = pt(outR[k][0], outR[k][1], yBot), bBot = pt(outR[n][0], outR[n][1], yBot);
          const aiTop = pt(inR[k][0], inR[k][1], yTop), biTop = pt(inR[n][0], inR[n][1], yTop);
          pushQuad(aTop, bTop, bBot, aBot, [0, 0], [0.2, 0], [0.2, collarH], [0, collarH]);
          pushQuad(aTop, aiTop, biTop, bTop, [0, 0], [0, 0.03], [0.2, 0.03], [0.2, 0]);
        }
      }
      continue;
    }

    const pts = [];
    for (const p of rawPts) {
      if (!p.every(Number.isFinite)) continue;
      const prev = pts.at(-1);
      if (!prev || Math.hypot(p[0] - prev[0], p[1] - prev[1], p[2] - prev[2]) > 1e-4) pts.push(p);
    }
    if (pts.length < 2) continue;

    // Pick wall-outward direction: prefer the kick-out start vector leaving the
    // LAST vertical segment (the wall/post drop, not the top 1 in vertical outlet drop).
    const P = pts.map(p => new THREE.Vector3(p[0], p[1], p[2]));
    const computeTangents = () => {
      const out = [];
      for (let i = 0; i + 1 < P.length; i++) out.push(P[i + 1].clone().sub(P[i]).normalize());
      return out;
    };
    let T = computeTangents();
    let anchor = -1;
    for (let i = T.length - 1; i >= 0; i--) {
      if (Math.abs(T[i].y) > 0.95) { anchor = i; break; }
    }
    let outArr = null;
    if (anchor >= 0 && anchor + 2 < P.length) {
      const kx = P[anchor + 2].x - P[anchor + 1].x, kz = P[anchor + 2].z - P[anchor + 1].z;
      if (Math.hypot(kx, kz) > 1e-4) outArr = unitXZ([kx, 0, kz]);
    }
    if (!outArr) outArr = owningSeg?.outward ? unitXZ([owningSeg.outward[0], 0, -owningSeg.outward[1]]) : unitXZ(dirLocal(spout.outlet?.dir || [0, 0, 1]));
    const wallOut = new THREE.Vector3(outArr[0], 0, outArr[2]).normalize();
    const wallAlong = new THREE.Vector3(-wallOut.z, 0, wallOut.x).normalize();

    // Freestanding exact drops use this same closed sweep and normal elbow.
    const isHang = spout.mount === 'hang' || (spout.flags || []).includes('hang') || (spout.flags || []).includes('stub');
    if (isHang) {
      // Short vertical stub only: no wall drop and no kick-out.
      emitBoxTube(pts[0], pts[1], wallAlong, wallOut, true);
      continue;
    }

    // Replace the bottom corner [wallBottom, outlet] with a smooth formed circular-arc elbow
    // (centreline radius 4 in, turning 75 deg from vertical to 15 deg below horizontal in 5 segments)
    // ending right at outlet.at (mouth centre ~4 in above surface, bottom lip ~3 in above surface).
    if (anchor >= 0 && anchor + 2 === P.length - 1) {
      const wallTopPt = P[anchor], wallBotPt = P[anchor + 1], outPt = P[anchor + 2];
      const ex = outPt.x - wallBotPt.x, ez = outPt.z - wallBotPt.z;
      const reach = Math.hypot(ex, ez);
      const availDrop = wallTopPt.y - outPt.y;
      if (reach > 0.05 && availDrop > 0.15) {
        const dirX = ex / reach, dirZ = ez / reach;
        const theta = (75 * Math.PI) / 180; // 75 deg from vertical -> outward & 15 deg below horizontal
        const sinT = Math.sin(theta), cosT = Math.cos(theta);
        const arcSegs = 5;
        let R = 4 / 12;
        const maxRReach = (reach * 0.85) / (1 - cosT);
        const maxRDrop = Math.max(0.08, (availDrop - 0.08) / (sinT + (1 - cosT) * (cosT / sinT)));
        R = Math.min(R, maxRReach, maxRDrop);
        const arcOut = R * (1 - cosT);
        const arcDrop = R * sinT;
        const cuffHoriz = Math.max(0, reach - arcOut);
        const cuffDrop = cuffHoriz * (cosT / sinT);
        let yStart = outPt.y + arcDrop + cuffDrop;
        if (yStart > wallTopPt.y - 0.04) yStart = wallTopPt.y - 0.04;
        const arcPts = [];
        for (let k = 0; k <= arcSegs; k++) {
          const a = (theta * k) / arcSegs;
          const rOut = R * (1 - Math.cos(a));
          const rDrop = R * Math.sin(a);
          arcPts.push(new THREE.Vector3(
            wallBotPt.x + dirX * rOut,
            yStart - rDrop,
            wallBotPt.z + dirZ * rOut,
          ));
        }
        if (cuffHoriz > 0.01) arcPts.push(outPt.clone());
        P.splice(anchor + 1, 2, ...arcPts);
        T = computeTangents();
      }
    }

    // Parallel-transport mitred sweep of 2 x 3 in section directly along path from path[0].
    // Anchor the frame at the vertical wall-drop segment so the 3 in face
    // always lies strictly along the wall, even when a corner overhang elbow runs diagonally.
    const U = new Array(P.length - 1), V = new Array(P.length - 1);
    if (anchor < 0) anchor = 0;
    let uAnchor = wallAlong.clone().addScaledVector(T[anchor], -wallAlong.dot(T[anchor]));
    if (uAnchor.lengthSq() < 1e-6) uAnchor = new THREE.Vector3(0, 1, 0).cross(T[anchor]);
    if (uAnchor.lengthSq() < 1e-6) uAnchor = new THREE.Vector3(1, 0, 0);
    uAnchor.normalize();
    U[anchor] = uAnchor;
    V[anchor] = new THREE.Vector3().crossVectors(T[anchor], uAnchor).normalize();
    const q = new THREE.Quaternion();
    for (let i = anchor + 1; i < T.length; i++) {
      q.setFromUnitVectors(T[i - 1], T[i]);
      U[i] = U[i - 1].clone().applyQuaternion(q).normalize();
      V[i] = new THREE.Vector3().crossVectors(T[i], U[i]).normalize();
    }
    for (let i = anchor - 1; i >= 0; i--) {
      q.setFromUnitVectors(T[i + 1], T[i]);
      U[i] = U[i + 1].clone().applyQuaternion(q).normalize();
      V[i] = new THREE.Vector3().crossVectors(T[i], U[i]).normalize();
    }
    const rings = [];
    const offsetOf = (u, v, cu, cv) => u.clone().multiplyScalar(cu * halfW).addScaledVector(v, cv * halfD);
    rings.push(CORNERS.map(([cu, cv]) => {
      const off = offsetOf(U[0], V[0], cu, cv);
      const tHit = T[0].y < -0.1 ? Math.max(-0.5, Math.min(0.5, -off.y / T[0].y)) : 0;
      return P[0].clone().add(off).addScaledVector(T[0], tHit).toArray();
    }));
    for (let i = 1; i < P.length - 1; i++) {
      const prevLen = P[i].distanceTo(P[i - 1]);
      const nextLen = P[i + 1].distanceTo(P[i]);
      const minT = -Math.min(0.5, prevLen * 0.92);
      const maxT = Math.min(0.5, nextLen * 0.92);
      const mVec = T[i - 1].clone().add(T[i]);
      const mLen = mVec.length();
      if (mLen > 1e-4) {
        mVec.divideScalar(mLen);
        const denom = T[i - 1].dot(mVec);
        if (Math.abs(denom) > 0.2) {
          rings.push(CORNERS.map(([cu, cv]) => {
            const off = offsetOf(U[i - 1], V[i - 1], cu, cv);
            const tHit = Math.max(minT, Math.min(maxT, -off.dot(mVec) / denom));
            return P[i].clone().add(off).addScaledVector(T[i - 1], tHit).toArray();
          }));
          continue;
        }
      }
      rings.push(CORNERS.map(([cu, cv]) => P[i].clone().add(offsetOf(U[i - 1], V[i - 1], cu, cv)).toArray()));
    }
    const last = T.length - 1;
    rings.push(CORNERS.map(([cu, cv]) => P[P.length - 1].clone().add(offsetOf(U[last], V[last], cu, cv)).toArray()));

    // Clean top cap at path[0] so the outlet joint closes cleanly against the gutter bottom.
    pushQuad(rings[0][0], rings[0][3], rings[0][2], rings[0][1], [0, 0], [0, halfD * 2], [halfW * 2, halfD * 2], [halfW * 2, 0]);
    let distAlong = 0;
    for (let i = 0; i < T.length; i++) {
      const segLen = P[i + 1].distanceTo(P[i]);
      const r0 = rings[i], r1 = rings[i + 1];
      for (let k = 0; k < 4; k++) {
        const n = (k + 1) % 4, w = k % 2 === 0 ? halfW * 2 : halfD * 2;
        pushQuad(r0[k], r0[n], r1[n], r1[k], [0, distAlong], [w, distAlong], [w, distAlong + segLen], [0, distAlong + segLen]);
      }
      distAlong += segLen;
    }
    if (spout.mount === 'free') {
      const mouth = rings.at(-1);
      pushQuad(mouth[0], mouth[1], mouth[2], mouth[3], [0, 0], [halfW * 2, 0], [halfW * 2, halfD * 2], [0, halfD * 2]);
    }
  }

  const parts = [];
  for (const bucket of buckets.values()) {
    if (!bucket.positions.length) continue;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(bucket.positions, 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(bucket.uvs, 2));
    geometry.computeVertexNormals();
    if (bucket.supportedRoof) geometry.userData.supportedRoof = bucket.supportedRoof;
    if (bucket.supportedLevel) {
      geometry.userData.supportedLevel = bucket.supportedLevel;
      geometry.userData.snapRanges = bucket.ranges;
    }
    parts.push({ geometry, mat: bucket.mat, ref: bucket.ref, seed: bucket.seed });
  }
  return parts;
}

function generateTwin(plan, kit, tier, { showAnchors = false, editableLevel = null, viewing = false, reuseMaterials = null, timing = null, gutters = null, modelTier = tier } = {}) {
  let failedModel = false;
  const onAssetFailure = () => { failedModel = true; };
  const detail = timing?.detail;
  const generationStart = timing ? performance.now() : 0;
  const materialBefore = detail?.materials || 0, batchBefore = detail?.batch || 0;
  let materialDepth = 0;
  const material = fn => {
    if (materialDepth) return fn();
    const stop = editSpan(detail, 'materials');
    ++materialDepth;
    try { return fn(); } finally { --materialDepth; stop(); }
  };
  const batch = (...args) => {
    const stop = editSpan(detail, 'batch');
    try { return mergeStatic(...args); } finally { stop(); }
  };
  const root = new THREE.Group(); root.scale.setScalar(FT);
  const pieces = new BuildingRegistry(), pieceBounds = new BuildingRegistry(), pickObjects = new BuildingRegistry(), roofSurfaces = new BuildingRegistry(), mergeGroups = [], ghostBatches = [];
  const ghostRoofCover = new Map();
  const groups = { site: new THREE.Group(), roof: new THREE.Group(), gableFull: new THREE.Group(), gableCut: new THREE.Group(), lights: new THREE.Group(), levels: {} };
  for (const [id, group] of Object.entries(groups)) if (group.isGroup) { group.name = id; root.add(group); }
  const materialKitFor = refs => materialKitWithRefs(kit, refs);
  const materials = material(() => new Map([...(reuseMaterials || [])].filter(([, m]) => currentMaterial(m, manifest(kit)))));
  let parkingIcon = materials.get('parking_icon#ffffff') || null;
  const plain = (name, color, extra = {}) => material(() => {
    const key = name + color;
    if (!materials.has(key)) materials.set(key, new THREE.MeshStandardMaterial({ name, color, roughness: 0.8, ...extra }));
    return materials.get(key);
  });
  const glass = plain('glass', '#b9d7db', { transparent: true, opacity: 0.26, roughness: 0.1, depthWrite: false });
  const screen = plain('screen', '#59615d', { transparent: true, opacity: 0.3, depthWrite: false, side: THREE.DoubleSide });
  const fixture = plain('fixture', '#fff4e0', { emissive: '#ffd59a', emissiveIntensity: 0 });
  const ghost = plain('ghost', '#38bdf8', { fog: false, opacity: 0.35, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 });
  const ghostEdges = material(() => materials.get('ghostEdges') || new THREE.LineDashedMaterial({ fog: false, color: '#38bdf8', dashSize: 0.4, gapSize: 0.25, transparent: true, opacity: 0.8, depthWrite: false }));
  const pickMaterial = material(() => materials.get('pick') || new THREE.MeshBasicMaterial({ fog: false, side: THREE.DoubleSide }));
  const roomLights = [], levelElevations = {}, notes = [], pendingModels = [];
  for (const b of plan.buildings || []) {
    const buildingStart = timing ? performance.now() : 0;
    const buildingMaterials = detail?.materials || 0, buildingBatch = detail?.batch || 0;
    const materialKit = material(() => materialKitFor(Object.fromEntries(
      [...new Set([...Object.keys(plan.materials || {}), ...Object.keys(b.materials || {})])]
        .map(role => [role, resolveSurfaceMaterial(plan, {role, building:b, kit}).ref]))));
    const surfaceRef = (role, level = null, ref = null, extra = {}) =>
      resolveSurfaceMaterial(plan, { role, building: b, level, ref, kit, ...extra }).ref;
    const mat = (role, level = null, override = null, extra = {}) => material(() => {
      const ref = surfaceRef(role, level, override, extra);
      // UVs belong to the geometry; neither the cache nor a shared material
      // records the slot that happened to request it.
      const look = { id: ref.id, ...(ref.color !== undefined ? { color: ref.color } : {}) };
      if (Object.hasOwn(BUILTIN_LOOKS, look.id))
        return materialSlot(look, role, materialKit, tier, materials, mat);
      const resolvedKit = materialKitFor({ [role]: look });
      const key = materialKey(resolvedKit.materials[role] || {}, role, tier, manifest(kit));
      // Retain the public role aliases used by view/reuseMaterials callers.
      // They point into the resolved cache; a slot's authorship is never an
      // instance key and cannot create another batch.
      const defaultRequest = !override && !level?.materials?.[role] && !extra.parents;
      const alias = Object.hasOwn(b.materials || {}, role) ? JSON.stringify([b.id, role]) : role;
      if (!materials.has(key) && defaultRequest && materials.has(alias)) materials.set(key, materials.get(alias));
      if (!materials.has(key)) materials.set(key, kitMaterial(role, resolvedKit, tier));
      if (defaultRequest) materials.set(alias, materials.get(key));
      return materials.get(key);
    });
    const kindResolution = (kind, item = null) => {
      const fallback = kindRow(kind).fallback;
      const level = b.levels.find(l => l.id === (item?.level || b.walls?.find(w => w.id === item?.wall)?.level));
      return resolveSurfaceMaterial(plan, {role:kind, building:b, level, kit,
          ref:kind === 'ceiling' ? item?.ceiling_material : item?.materials?.[kind],
          fallback: fallback.role ? resolveSurfaceMaterial(plan, {role:fallback.role, building:b,
          level:kind === 'garage_door' ? level : null, kit}) : null,
          defaultRef:{ id: fallback.builtin || fallback.look || 'ceramic' } });
    };
    const kindRef = (kind, item = null) => kindResolution(kind, item).ref;
    const resolveKindMat = (kind, item = null) => material(() => {
      const row = kindRow(kind), fallback = row.fallback;
      const levelId = item?.level || b.walls?.find(w => w.id === item?.wall)?.level;
      const level = b.levels.find(l => l.id === levelId);
      // A person's existing per-fixture colour wins over a house default.
      const own = item?.materials?.[kind];
      if (!own?.id && kind === 'cabinet' && item?.body) return plain('cabinet', own?.color || item.body);
      if (!own?.id && kind === 'counter' && item?.top) return plain('counter', own?.color || item.top);
      // Existing role defaults already resolve through mat. Keep their shared
      // instances (notably roof covering and standing seams) and legacy tint.
      if (!own && (fallback.role === kind || kind === 'counter')) return mat(kind, level);
      const chosen = (kind === 'ceiling' && item?.ceiling_material) || resolveSlot(kind, { item, building: b, level }) || plan.materials?.[kind];
      const resolution = chosen ? kindResolution(kind, item) : null, slot = resolution?.ref;
      if (slot && resolution.source.kind === 'kit' && !fallback.role && fallback.look && !kit.materials?.[slot.id] && !manifest(kit)[slot.id]
          && slot.id === fallback.look) {
        if (kind === 'counter') return mat('counter', level, slot);
        return plain(kind === 'cabinet' ? 'cabinet' : 'ceramic', slot.color || (kind === 'cabinet' ? '#3a4a52' : '#f4f4f2'));
      }
      if (!slot) {
        if (fallback.role) return mat(fallback.role, kind === 'garage_door' ? level : null);
        if (fallback.builtin) return fallback.builtin === 'screen' ? screen : glass;
        if (kind === 'cabinet') return plain('cabinet', '#3a4a52');
        return plain('ceramic', '#f4f4f2');
      }
      const ref = materialKit.materials?.[slot.id], known = manifest(kit);
      const mode = Object.hasOwn(BUILTIN_LOOKS, slot.id) ? builtinAlphaMode(slot.id) : alphaModeOf(known[slot.id] || known[ref?.id || ref?.asset], ref);
      const name = kind === 'pane' || kind === 'shower_glass' ? (mode === 'opaque' ? 'pane' : 'glass')
        : fallback.role || (kind === 'shower_tile' ? 'ceramic' : kind);
      if (fallback.role || kind === 'counter') return mat(name, level, slot);
      // materialSlot's legacy alias cache keeps its original role. Namespace
      // this receiving role so a kit alias in a pane cannot rename a wall.
      const prefix = 'surface-kind:' + name + ':';
      const cache = { has: key => materials.has(prefix + key), get: key => materials.get(prefix + key),
        set: (key, value) => materials.set(prefix + key, value) };
      const result = materialSlot(slot, name, materialKit, tier, cache, role => {
        if (role === name) return mat(role);
        const result = kitMaterial(role, materialKit, tier); result.name = name; return result;
      });
      // Tinted kit aliases are built inside materialSlot instead of calling
      // roleMaterial. This isolated cache still owns their receiving name.
      result.name = name;
      return result;
    });
    const kindMat = (kind, item = null) => {
      const source = resolveKindMat(kind, item);
      const wall = b.walls?.find(w => w.id === item?.wall);
      if (tier === 'low' || kind !== 'pane' || wall?.exterior === false || !source.transparent || source.alphaTest > 0) return source;
      const key = 'reflection-pane:' + b.id + ':' + source.uuid;
      if (!materials.has(key)) {
        const target = source.clone();
        target.onBeforeCompile = source.onBeforeCompile; target.customProgramCacheKey = source.customProgramCacheKey;
        reflectionMaterial(target, 'exterior', b.id);
        // Library textures arrive after geometry is batched. Keep the original
        // slot as their owner and propagate late maps into every viewing clone.
        const sync = () => { for (const m of target.userData.reflection.materials) copyMaterialParams(source, m); };
        source.addEventListener('materialparamschange', sync);
        target.addEventListener('dispose', () => source.removeEventListener('materialparamschange', sync));
        target.userData.ready = Promise.resolve(source.userData.ready).then(sync);
        materials.set(key, target);
      }
      return materials.get(key);
    };
    // Walls/openings (including CSG) and floor slabs are attributable by level;
    // roof, foundation and shared preparation stay at building granularity.
    const levelTiming = timing ? b.levels.map(l => ({ id: l.id, walls: 0, floors: 0 })) : [];
    const levelSpan = (id, phase) => editSpan(levelTiming.find(l => l.id === id), phase);
    const levels = Object.fromEntries(b.levels.map(l => [l.id, l]));
    const ordered = [...b.levels].sort((a, c) => a.elevation - c.elevation), first = ordered[0];
    if (!first) continue;
    const local = {};
    const position = b.position || [0, 0];
    const base = buildingBase(plan, b);
    const levelKey = id => `${b.id}:${id}`;
    // Every independently switchable domain gets the same rigid placement.
    for (const id of ['roof', 'gableFull', 'gableCut', 'lights', ...b.levels.map(l => l.id)]) {
      const key = levelKey(id);
      if (levels[id] && !groups.levels[key]) {
        groups.levels[key] = new THREE.Group(); groups.levels[key].name = key; root.add(groups.levels[key]);
        groups.levels[key].userData.buildingId = b.id;
        groups.levels[key].userData.levelId = id;
      }
      const g = local[id] = new THREE.Group(); g.position.set(position[0], base, -position[1]);
      g.name = key;
      g.rotation.y = (b.rotation || 0) * Math.PI / 180;
      g.userData.buildingId = b.id; g.userData.levelKey = levels[id] ? key : null;
      (groups[id] || groups.levels[key]).add(g);
      if (id !== 'lights') mergeGroups.push(g);
    }
    ordered.forEach(l => { levelElevations[levelKey(l.id)] = base + l.elevation; });
    const wallFull = {}, wallCut = {};
    if (viewing) for (const l of ordered) {
      for (const [kind, collection] of [['full', wallFull], ['cut', wallCut]]) {
        const group = collection[l.id] = new THREE.Group();
        group.name = `${levelKey(l.id)}:walls:${kind}`; group.userData.viewingWalls = kind;
        local[l.id].add(group); mergeGroups.push(group);
      }
    }
    const allSections = b.roof?.sections || [], sections = [], supportedSections = [], sectionIndices = [], supportedIndices = [];
    allSections.forEach((section, index) => {
      if (isSupported(section)) { supportedSections.push(section); supportedIndices.push(index); }
      else { sections.push(section); sectionIndices.push(index); }
    });
    const roofSidePlanes = sections.map(planes);
    const roofLevel = section => levels[section.level] || (isSupported(section) ? first
      : [...ordered].reverse().find(l => l.elevation + .5 < section.plate));
    const roofRef = (section, edge = null) => surfaceRef('roof', roofLevel(section),
      edge === null || edge < 0 ? null : section.plane_materials?.[String(edge)],
      { parents: [section.material, section.materials?.roof] });
    const roofIdentities = new Map();
    const roofIdentity = face => {
      const key = `${face.section}:${face.edge}`;
      if (roofIdentities.has(key)) return roofIdentities.get(key);
      const section = sections[face.section], ref = roofRef(section, face.edge);
      const identity = JSON.stringify([mat('roof', roofLevel(section), ref).uuid, ref.uv || null]);
      roofIdentities.set(key, identity); return identity;
    };
    const envelope = roofEnvelope(sections, { materialKey: roofIdentity }).walled;
    const outlines = new Map(ordered.map(l => [l.id, l.outline?.length >= 3 ? [l.outline] : footprints(b.walls.filter(w => w.level === l.id))]));
    const uvParts = [];
    // This belongs to the lowest floor domain, including its viewing fade and
    // peel. Its finish never inherits siding or room wall materials.
    const foundation = foundationShape(plan, b);
    const lowered = (b.rooms || []).filter(r => r.level === first.id && r.state !== 'ghost' && r.floor_offset_ft);
    if (foundation.polygon.length >= 3 && foundation.top > foundation.bottom) {
      const triangles = THREE.ShapeUtils.triangulateShape(foundation.polygon.map(p => new THREE.Vector2(...p)), [])
        .map(indices => indices.map(i => foundation.polygon[i]));
      const parts = lowered.length ? foundationPieces(b, first, triangles) : [{polygon: foundation.polygon, top: 0}];
      const slab = b.foundation?.materials?.slab;
      const finish = material(() => materialSlot(slab, 'patio_concrete', materialKit, tier, materials, mat));
      const add = geometry => {
        const uv = surfaceRef('patio_concrete', null, slab).uv;
        if (slab || uv) {
          const seed = `${b.id}:foundation`;
          if (uv) uvParts.push({geometry,material:finish,seed,offset:uv,key:seed});
          else offsetSurfaceUvs(geometry, finish, seed);
        }
        addMesh(local[first.id], geometry, finish);
      };
      // The slab stops just under the floor finish, like every upper slab, so the two never share a plane.
      for (const {polygon: area, top} of parts)
        add(polygon(area, Math.min(foundation.bottom - base, top - (b.foundation?.thickness_ft ?? 1)), top - FLOOR_GAP_FT));
      // Exterior walls stand on the slab itself: their mitred footprints carry it up to the floor line.
      for (const wall of b.walls.filter(w => w.level === first.id && w.exterior
        && w.kind !== 'separator' && w.state !== 'ghost' && w.footprint?.length === 4)) {
        const strip = THREE.ShapeUtils.triangulateShape(wall.footprint.map(p => new THREE.Vector2(...p)), [])
          .map(indices => indices.map(i => wall.footprint[i]));
        for (const {polygon: area, top} of lowered.length ? foundationPieces(b, first, strip) : [{polygon: wall.footprint, top: 0}])
          add(polygon(area, top - FLOOR_GAP_FT, top));
      }
    }
    // Triangulate concave floor outlines into convex roof cutters. A floor at
    // the roof's plate also occupies the space above that roof (e.g. L2).
    const floorCutters = new Map(ordered.map(l => [l.id, outlines.get(l.id).flatMap(poly => {
      const contour = poly.map(p => new THREE.Vector2(...p));
      return THREE.ShapeUtils.triangulateShape(contour, []).map(indices => {
        const triangle = indices.map(i => poly[i]);
        if (THREE.ShapeUtils.isClockWise(triangle.map(p => new THREE.Vector2(...p)))) triangle.reverse();
        return triangle;
      });
    })]));
    const exclude = sections.map(s => ordered.filter(l => l.elevation >= s.plate)
      .flatMap(l => floorCutters.get(l.id)));
    // Retained lower roofs serve walls under overhangs, never upper rooms;
    // the visible envelope remains above occupied attic outlines.
    const roofLayers = roofEnvelope(sections, { retainLower: true, exclude, materialKey: roofIdentity }).walled;
    const visibleRoof = envelope;
    // Supported roofs retain their own envelopes, even below another roof.
    // Stored floors own visibility. Only storeys reaching the slab cut it.
    const roofGroups = [{ sections, indices: sectionIndices, roofLayers, visibleRoof, exclude,
      roofSidePlanes, roofIdentity, supported: false, group: local.roof }];
    const supportedGroups = new Map(), supportedLevels = new Map(), supportCuts = new Map();
    supportedSections.forEach((section, index) => {
      const key = section.roof || section.id || supportedIndices[index];
      if (!supportedGroups.has(key)) supportedGroups.set(key, { sections: [], indices: [] });
      const entry = supportedGroups.get(key); entry.sections.push(section); entry.indices.push(supportedIndices[index]);
    });
    for (const entry of supportedGroups.values()) {
      const level = levels[entry.sections[0].level] || first;
      if (!supportedLevels.has(level.id)) {
        const group = new THREE.Group();
        group.name = `${b.id}:supported:${level.id}`;
        group.userData.supportedRoof = true;
        local[level.id].add(group); mergeGroups.push(group);
        supportedLevels.set(level.id, group);
      }
      const group = supportedLevels.get(level.id);
      const identity = face => {
        const section = entry.sections[face.section], ref = roofRef(section, face.edge);
        return JSON.stringify([mat('roof', roofLevel(section), ref).uuid, ref.uv || null]);
      };
      const cuts = entry.sections.map(section => {
        const cutters = supportedRoofCutters(section, ordered, floorCutters, section.thickness_ft ?? ROOF_THICKNESS);
        supportCuts.set(section, cutters); return cutters;
      });
      const mesh = roofMesh(entry.sections, { exclude: cuts, cutAll: true, materialKey: identity });
      roofGroups.push({ ...entry, roofLayers: mesh, visibleRoof: mesh, exclude: cuts,
        roofSidePlanes: entry.sections.map(planes), roofIdentity: identity, supported: true, group });
    }
    const combinedRoof = field => {
      if (!supportedSections.length) return field === 'roofLayers' ? roofLayers : envelope;
      const rows = roofGroups.map(g => ({ mesh: g[field], indices: g.indices }));
      return { positions: new Float32Array(rows.flatMap(r => Array.from(r.mesh.positions))),
        section: new Int32Array(rows.flatMap(r => Array.from(r.mesh.section, i => r.indices[i]))),
        side: rows.flatMap(r => r.mesh.side), edge: new Int32Array(rows.flatMap(r => Array.from(r.mesh.edge))) };
    };
    const allEnvelope = combinedRoof('visibleRoof'), allRoofLayers = combinedRoof('roofLayers');
    const storeyRoofs = new Map(ordered.map(l => {
      const own = sections.filter(s => l.elevation + 0.5 < s.plate && s.plate <= l.elevation + l.ceiling + 2);
      return [l.id, { sections: own,
        positions: new Float32Array([...roofEnvelope(own).walled.positions, ...envelope.positions]) }];
    }));
    let activePiece = null, activeSurface = null;
    const records = new Map(), wallProfiles = new Map();
    const use = (piece, kind, fallback) => { activeSurface = piece; activePiece = { pieceId: piece.id || fallback, kind, visibilityKind: piece.device ? 'device' : piece.object_kind === 'lamp' ? 'fixture' : undefined, buildingId: b.id, ghost: piece.state === 'ghost' }; };
    // seed: a random-offset origin shared by several pieces (one per level for floors).
    const mesh = (group, geometry, material, retained = null, seed = null, ref = null, part = '') => {
      const data = activePiece || { pieceId: 'structure', kind: 'building', buildingId: b.id };
      const key = `${b.id}:${data.pieceId}`;
      // A random-offset material shifts this piece's base uv by its own seed, before batching.
      if ((!retained || ref?.uv) && !data.ghost && activePiece) {
        const uv = (ref || surfaceRef(material.name, levels[activeSurface?.level])).uv;
        if (uv) uvParts.push({geometry, material, seed: seed || key, offset: uv,
          key: JSON.stringify([part.startsWith('roof-plane:') ? b.id : key, part || material.name, uv])});
        else offsetSurfaceUvs(geometry, material, seed || key);
      }
      const object = retained || addMesh(group, geometry, data.ghost ? ghost : material);
      if (retained && data.ghost) object.material = ghost;
      Object.assign(object.userData, data);
      if(part && !geometry.userData.bakePlaneSurface)object.userData.bakePart=part;
      if (!pieces.has(key)) pieces.set(key, []);
      const objects = pieces.get(key); objects.push(object);
      // Non-enumerable: this back-reference is used only while merging.
      Object.defineProperty(object.userData, 'pieceObjects', { value: objects });
      if (!records.has(key)) records.set(key, { data, group, box: new THREE.Box3() });
      geometry.computeBoundingBox(); const bounds = geometry.boundingBox.clone();
      if (retained) {
        object.updateWorldMatrix(true, false); group.updateWorldMatrix(true, false);
        bounds.applyMatrix4(group.matrixWorld.clone().invert().multiply(object.matrixWorld));
      }
      records.get(key).box.union(bounds);
      if (activeSurface && isSupported(activeSurface) && part.startsWith('roof-plane:')) tagPart(object, part);
      return object;
    };
    // Keep the original geometry for precise part hits after static batching.
    // These are the meshes already made above, never extra scene meshes.
    const tagPart = (object, part) => {
      object.userData.part = part;
      const key = `${b.id}:${object.userData.pieceId}`, record = records.get(key);
      (record.partObjects ||= []).push({ object, group: object.parent });
      return object;
    };
    const retainLod = (group, model) => {
      group.add(model); model.updateWorldMatrix(true, true);
      model.traverse(object => { if (object.isMesh) mesh(group, object.geometry, object.material, object); });
    };
    const center = b.walls.length ? b.walls.reduce((a, w) => [a[0] + w.from[0] / b.walls.length, a[1] + w.from[1] / b.walls.length], [0, 0]) : [0, 0];
    const wallNormal = w => {
      const length = Math.hypot(w.to[0] - w.from[0], w.to[1] - w.from[1]);
      const dx = (w.to[0] - w.from[0]) / length, dy = (w.to[1] - w.from[1]) / length;
      const polys = outlines.get(w.level) || [], mid = [(w.from[0] + w.to[0]) / 2, (w.from[1] + w.to[1]) / 2];
      const sign = polys.length ? (polys.some(poly => contains(poly, [mid[0] + dy * 0.1, mid[1] - dx * 0.1])) ? -1 : 1)
        : Math.sign(dy * (mid[0] - center[0]) - dx * (mid[1] - center[1])) || 1;
      return { sign, outward: [sign * dy, -sign * dx] };
    };
    const roofHeight = (x, y) => heightAt(sections, x, y) ?? Infinity;
    // Row 5: preserve the walled query exactly; only a lower covering
    // supported roof above this floor may replace it with its underside.
    const supportedCeilings = new Map();
    const supportCap = (x, y, floor, currentHeight) => {
      if (!supportedSections.length) return currentHeight;
      const height = supportedRoofAbove(supportedSections, x, y, floor, currentHeight,
        { cuts: section => supportCuts.get(section), thickness: ROOF_THICKNESS, underside: true,
          ceilingAt: section => supportedCeilings.get(section.roof || section.id) ?? null });
      return height === null ? currentHeight : height;
    };
    const supportingWalls = [];
    function wall(group, from, to, elevation, thickness, top, holes, exterior, role = null, clipRoof = true, profile = {}) {
      const { matrix, length, z } = wallBasis(from, to, elevation);
      if (!length) return;
      const ghostOpenings = holes.filter(h => h.state === 'ghost');
      holes = holes.filter(h => h.state !== 'ghost');
      const start = profile.footprint ? Math.min(...profile.footprint.map(p => p[0])) : -(profile.extendStart || 0);
      const end = profile.footprint ? Math.max(...profile.footprint.map(p => p[0])) : length + (profile.extendEnd || 0), offset = profile.offset || 0;
      const samples = Array.from({ length: 17 }, (_, i) => start + (end - start) * i / 16);
      // Include every envelope face boundary crossed by this wall. Uniform
      // samples alone can bridge a narrow valley and put siding above it.
      const dx = to[0] - from[0], dy = to[1] - from[1], positions = profile.positions || envelope.positions;
      const edges = [];
      for (let i = 0; clipRoof && i < positions.length; i += 9) for (let j = 0; j < 3; j++) {
        const a = i + j * 3, c = i + ((j + 1) % 3) * 3;
        edges.push([[positions[a], positions[a + 1]], [positions[c], positions[c + 1]]]);
      }
      edges.push(...(profile.edges || []));
      for (const face of profile.faces || [[0, 0]]) for (const [a, c] of edges) {
        const ex = c[0] - a[0], ey = c[1] - a[1], denominator = dx * ey - dy * ex;
        if (Math.abs(denominator) < 1e-8) continue;
        const ax = a[0] - from[0] - face[0], ay = a[1] - from[1] - face[1];
        const u = (ax * ey - ay * ex) / denominator, v = (ax * dy - ay * dx) / denominator;
        if (u * length > start && u * length < end && v >= -1e-8 && v <= 1 + 1e-8) samples.push(u * length);
      }
      // Partition the surface at opening edges. This treats doors touching the
      // floor as notches (not invalid polygon holes), and clips all upper pieces
      // under the sampled roof, including gable windows near a slope.
      const cuts = [...new Set([start, end, ...samples, ...(profile.floorCuts || []), ...holes.flatMap(h => [h.u0, h.u1])].filter(u => u >= start && u <= end))].sort((a, c) => a - c);
      // Between face boundaries each height limit is linear. Split where
      // the two faces (or a slab cap) exchange which one is lower.
      if (profile.limits) {
        const crossings = [];
        for (let i = 0; i + 1 < cuts.length; i++) {
          const a = cuts[i], c = cuts[i + 1], mid = (a + c) / 2;
          const left = profile.limits(a, mid), right = profile.limits(c, mid);
          for (let j = 0; j < left.length; j++) for (let k = j + 1; k < left.length; k++) {
            const da = left[j] - left[k], dc = right[j] - right[k];
            if (Number.isFinite(da) && Number.isFinite(dc) && da * dc < 0) crossings.push(a + (c - a) * da / (da - dc));
          }
        }
        cuts.push(...crossings); cuts.sort((a, c) => a - c);
      }
      const wallMat = role ? mat(role) : mat(exterior ? 'siding' : 'interior_wall');
      const panel = (geo, material, ref = null, side = '') => {
        if (!profile.cutaway) return mesh(group, geo.applyMatrix4(matrix), material, null, null, ref, side);
        // Cut variants have plain solid tops, without cladding relief. Batch
        // these triangles into one plan-tone draw per floor at construction.
        const parts = { side: [], top: [] }, normal = geo.attributes.normal;
        for (let i = 0; i < normal.count; i += 3)
          parts[normal.getY(i) > .9 ? 'top' : 'side'].push(i, i + 1, i + 2);
        for (const [face, indices] of Object.entries(parts)) if (indices.length) {
          const part = new THREE.BufferGeometry();
          for (const [name, attr] of Object.entries(geo.attributes))
            part.setAttribute(name, new THREE.Float32BufferAttribute(indices.flatMap(i =>
              Array.from({ length: attr.itemSize }, (_, c) => attr.getComponent(i, c))), attr.itemSize));
          mesh(group, part.applyMatrix4(matrix), face === 'top'
            ? plain('viewing_wall_top', '#a6a59b') : material, null, null, face === 'top' ? {} : ref, side || face);
        }
        geo.dispose();
      };
      // Keep closed wall/batten tops in floor views. Only nudge an extrusion
      // whose top actually coincides with a roof face, rather than removing
      // every cap with a roof somewhere overhead. A slab-limited top embeds
      // into that slab only for a wall body beneath its footprint; battens
      // and other contacts move down inside the roof shell.
      const separateRoofContact = (geo, a, c, ta, tc, faceOffset, wallBody = false) => {
        if (!exterior || !clipRoof || group === local.gableCut) return;
        const p = geo.attributes.position, n = geo.attributes.normal;
        const expected = j => ta + (tc - ta) * (p.getX(j) - a) / (c - a);
        const points = [], point = new THREE.Vector3();
        for (let i = 0; i < p.count; i += 3) {
          if (n.getY(i) <= 0.3 || ![i, i + 1, i + 2].every(j => Math.abs(p.getY(j) - expected(j)) < 1e-5)) continue;
          const tri = [i, i + 1, i + 2].map(j => {
            point.set(p.getX(j), p.getY(j), p.getZ(j) + faceOffset).applyMatrix4(matrix);
            return [point.x, -point.z, point.y];
          });
          tri.push([0, 1, 2].map(axis => (tri[0][axis] + tri[1][axis] + tri[2][axis]) / 3));
          if (sections.some(s => tri.every(([x, y, z]) => {
            const h = heightAt([s], x, y);
            return h !== null && Math.abs(z - h) <= 0.05;
          }))) points.push(i);
        }
        if (!points.length) return;
        const atSlab = wallBody && Math.abs(elevation + ta - profile.slabCap) < 1e-5 && Math.abs(elevation + tc - profile.slabCap) < 1e-5 &&
          [a, c].every(u => [0, thickness].every(depth => {
            point.set(u, 0, depth + faceOffset).applyMatrix4(matrix);
            return profile.slabOutlines.some(poly => contains(poly, [point.x, -point.z]));
          }));
        for (let j = 0; j < p.count; j++) if (Math.abs(p.getY(j) - expected(j)) < 1e-5) p.setY(j, p.getY(j) + (atSlab ? 0.11 : -0.11));
        geo.computeVertexNormals();
      };
      for (let i = 0; i < cuts.length - 1; i++) {
        const a = cuts[i], c = cuts[i + 1], mid = (a + c) / 2;
        if (c - a < 0.0001) continue;
        if (!role) profile.panels?.push([a, c, top(a, mid), top(c, mid)]);
        let intervals = [[profile.bottom?.(mid) ?? 0, Infinity]];
        holes.filter(h => mid > h.u0 && mid < h.u1).forEach(h => {
          intervals = intervals.flatMap(([lo, hi]) => [[lo, Math.min(hi, h.v0)], [Math.max(lo, h.v1), hi]].filter(([p, q]) => q > p));
        });
        for (const [lo, hi] of intervals) {
          // Evaluate from this interval's side of a roof/floor boundary. A
          // single shared height at a step would interpolate siding across it.
          const ta = Math.min(hi, top(a, mid)), tc = Math.min(hi, top(c, mid));
          if (ta <= lo && tc <= lo) continue;
          if (profile.footprint && !role) {
            for (const [side, geo] of footprintPanel(profile.footprint, a, c, lo, ta, tc)) {
              separateRoofContact(geo, a, c, top(a, mid), top(c, mid), 0, true);
              panel(geo, profile.materials[side] || wallMat, profile.refs?.[side], side);
            }
            continue;
          }
          const shape = new THREE.Shape([[a, lo], [c, lo], [c, Math.max(lo, tc)], [a, Math.max(lo, ta)]].map(p => new THREE.Vector2(...p)));
          const geo = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false, steps: 1 });
          separateRoofContact(geo, a, c, top(a, mid), top(c, mid), offset - thickness / 2, true);
          geo.translate(0, 0, offset - thickness / 2);
          if (profile.materials && !role) {
            const parts = { body: [], left: [], right: [] }, normal = geo.attributes.normal;
            for (let j = 0; j < normal.count; j += 3) {
              const side = normal.getZ(j) < -0.5 ? 'left' : normal.getZ(j) > 0.5 ? 'right' : 'body';
              parts[side].push(j, j + 1, j + 2);
            }
            for (const [side, indices] of Object.entries(parts)) if (indices.length) {
              const part = new THREE.BufferGeometry();
              for (const [name, attr] of Object.entries(geo.attributes)) {
                const values = indices.flatMap(i => Array.from({ length: attr.itemSize }, (_, c) => attr.getComponent(i, c)));
                part.setAttribute(name, new THREE.Float32BufferAttribute(values, attr.itemSize));
              }
              panel(part, profile.materials[side] || wallMat, profile.refs?.[side], side);
            }
            geo.dispose();
          } else panel(geo, wallMat);
        }
      }
      const sign = profile.sign || Math.sign(z.dot(new THREE.Vector3((from[0] + to[0]) / 2 - center[0], 0, -(from[1] + to[1]) / 2 + center[1]))) || 1;
      const localBox = (u, v, w, h, d, material, faceOffset = 0, ref = null, part = '') => mesh(group,
        boxGeometry(w, h, d).translate(u, v, offset + faceOffset).applyMatrix4(matrix), material, null, null, ref, part);
      if (!profile.cutaway && exterior && (profile.sidingAsset || materialKit.materials.siding?.asset) === 'board_and_batten' && !role) {
        for (let u = 0.5; u < length; u += 1) {
          let intervals = [[profile.bottom?.(u) ?? 0, Infinity]];
          holes.filter(h => u > h.u0 - 0.4 && u < h.u1 + 0.4).forEach(h => {
            intervals = intervals.flatMap(([a, c]) => [[a, Math.min(c, h.v0 - 0.35)], [Math.max(a, h.v1 + 0.35), c]].filter(([a, c]) => c - a > 0.1));
          });
          const edges = [Math.max(start, u - 0.07), ...cuts.filter(c => c > u - 0.07 && c < u + 0.07), Math.min(end, u + 0.07)];
          for (let i = 0; i + 1 < edges.length; i++) for (const [lo, hi] of intervals) {
            const a = edges[i], c = edges[i + 1], mid = (a + c) / 2;
            const ta = Math.min(hi, top(a, mid)), tc = Math.min(hi, top(c, mid));
            if (ta <= lo && tc <= lo) continue;
            const shape = new THREE.Shape([[a, lo], [c, lo], [c, Math.max(lo, tc)], [a, Math.max(lo, ta)]].map(p => new THREE.Vector2(...p)));
            const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.09, bevelEnabled: false, steps: 1 });
            separateRoofContact(geo, a, c, top(a, mid), top(c, mid), offset + sign * (thickness / 2 + 0.045) - 0.045);
            geo.translate(0, 0, offset + sign * (thickness / 2 + 0.045) - 0.045).applyMatrix4(matrix);
            const side = sign > 0 ? 'right' : 'left';
            mesh(group, geo, profile.materials?.[side] || wallMat, null, null, profile.refs?.[side], side);
          }
        }
      }
      const wallPiece = activePiece, wallSurface = activeSurface;
      for (const h of holes) {
        if (h.kind === 'passage') continue;
        use({ ...h, state: wallPiece.ghost ? 'ghost' : h.state }, 'opening', `opening:${h.wall || h.section}:${h.u0}`);
        const width = h.u1 - h.u0, height = h.v1 - h.v0, cu = (h.u0 + h.u1) / 2, cv = (h.v0 + h.v1) / 2;
        const openingBox = (part, u, v, w, height, depth, faceOffset = 0) =>
          tagPart(localBox(u, v, w, height, depth, kindMat(part, h), faceOffset, kindRef(part, h), part), part);
        if (h.model) {
          // The hole above has already been cut using opening dimensions alone.
          const placeholder = localBox(cu, cv, width, height, Math.min(thickness, .08), kindMat('window_frame', h), 0, kindRef('window_frame', h), 'window_frame');
          if (placeholder) placeholder.userData.pendingImport = true;
          const openingData = activePiece;
          pendingModels.push(loadModel(h.model, kit, undefined, { tier: modelTier, editor: !viewing, onFailure: onAssetFailure }).then(source => {
            if (!source) return;
            if (root.userData.disposed) { disposeObject(source); return; }
            const livePlaceholder = pieces.get(`${b.id}:${openingData.pieceId}`)?.find(o => o === placeholder);
            if (livePlaceholder?.parent) {
              livePlaceholder.removeFromParent(); livePlaceholder.geometry.dispose();
              const objects = pieces.get(`${b.id}:${openingData.pieceId}`); objects.splice(objects.indexOf(livePlaceholder), 1);
            }
            const fitted = fitOpening(source, width, height, thickness);
            fitted.position.set(cu, h.v0, offset);
            if (h.hinge === 'right') fitted.scale.x *= -1;
            if (h.swing === 'out') fitted.scale.z *= -1;
            fitted.updateMatrixWorld(true);
            const saved = activePiece; activePiece = openingData;
            if (source.isLOD) {
              const transform = new THREE.Group(); transform.applyMatrix4(matrix); transform.add(fitted);
              retainLod(group, transform); activePiece = saved; registerRecords(); return;
            }
            fitted.traverse(object => {
              if (object.isMesh) mesh(group, bakeMatrix(object.geometry.clone(), matrix.clone().multiply(object.matrixWorld)), object.material);
            });
            activePiece = saved;
            const geometries = new Set(); fitted.traverse(o => { if (o.geometry) geometries.add(o.geometry); }); geometries.forEach(g => g.dispose());
            registerRecords();
            batch(group, { perPiece: !!editableLevel });
          }));
          continue;
        }
        const fw = 0.16;
        for (const u of [h.u0, h.u1]) {
          openingBox('window_frame', u, cv, fw, height, 0.22);
          if (exterior) openingBox('casing', u + (u === h.u0 ? -0.18 : 0.18), cv, 0.33, height + 0.66, 0.12, sign * (thickness / 2 + 0.06));
        }
        for (const v of [h.v0, h.v1]) openingBox('window_frame', cu, v, width, fw, 0.22);
        if (exterior) for (const v of [h.v0, h.v1]) if (v > 0.01) openingBox('casing', cu, v + (v === h.v0 ? -0.18 : 0.18), width + 0.66, 0.33, 0.12, sign * (thickness / 2 + 0.06));
        if (h.kind === 'door') {
          if (h.glass === 'half') {
            openingBox('door', cu, h.v0 + height / 4, width - fw, height / 2, 0.15);
            openingBox('pane', cu, h.v0 + height * 0.75, width - fw, height / 2 - fw, 0.025);
            openingBox('window_frame', cu, cv, width, fw, 0.22);
          } else openingBox('door', cu, cv, width - fw, height - fw, 0.15);
        } else if (h.kind === 'garage') {
          if (profile.cutaway) continue;
          const door = buildGarageDoor({ ...h, width, head: height, sill: 0 }, {
            material: part => kindMat(part, h), inward: -sign, setback: thickness / 2 + .16,
          });
          door.userData.garageOpening.building = b.id;
          const placement = new THREE.Group();
          placement.applyMatrix4(matrix.clone().multiply(new THREE.Matrix4().makeTranslation(cu, h.v0, offset)));
          // The floor's shared body owns the door in both full and cut views.
          const doorLevel = h.level || b.walls.find(w => w.id === h.wall)?.level;
          placement.add(door); (local[doorLevel] || group).add(placement);
          door.updateWorldMatrix(true, true);
          for (const object of door.children) tagPart(mesh(group, object.geometry, object.material, object, null,
            kindRef(object.userData.part, h), object.userData.part), object.userData.part);
        } else {
          for (let i = 1; i < (h.panels || 1); i++) openingBox('window_frame', h.u0 + width * i / h.panels, cv, fw, height, 0.22);
          if (h.split === 'double_hung') openingBox('window_frame', cu, cv, width, fw, 0.22);
          openingBox('pane', cu, cv, width - fw, height - fw, 0.025);
        }
      }
      // Saved failures stay visible and selectable without cutting siding or
      // drawing a frame at the model's possibly far-outside coordinates.
      // mesh() / batchGhost() supply the shared translucent, dashed outline.
      for (const h of ghostOpenings) {
        const width = Math.min(length, h.u1 - h.u0);
        const cu = Math.max(width / 2, Math.min(length - width / 2, (h.u0 + h.u1) / 2));
        const ceiling = Math.max(0, Math.min(top(cu - width / 2, cu), top(cu), top(cu + width / 2, cu)));
        const height = Math.min(ceiling, h.v1 - h.v0);
        if (width <= 0 || height <= 0) continue;
        const sill = Math.max(0, Math.min(ceiling - height, h.v0));
        use(h, 'opening', `opening:${h.wall || h.section}:${h.u0}`);
        localBox(cu, sill + height / 2, width, height, 0.08, ghost, sign * (thickness / 2 + 0.05));
      }
      activePiece = wallPiece;
      activeSurface = wallSurface;
    }
    const opening = (o, at = o.at) => ({ ...o, u0: at - o.width / 2, u1: at + o.width / 2, v0: o.sill, v1: o.head });
    const ownsGable = (w, section, end) => {
      const axis = section.ridge === 'y' ? 1 : 0, other = 1 - axis;
      return w.kind !== 'separator' && w.state !== 'ghost' && w.level === ordered.at(-1).id &&
        Math.abs(w.from[axis] - end) < 1e-4 && Math.abs(w.to[axis] - end) < 1e-4 &&
        Math.max(w.from[other], w.to[other]) > section.rect[other] && Math.min(w.from[other], w.to[other]) < section.rect[other + 2];
    };
    // Half-storey knee walls use this same path and retain the roof caps.
    for (const w of b.walls) {
      if (w.kind === 'separator') continue;
      const l = levels[w.level]; if (!l) continue;
      use(w, 'wall', w.id);
      const length = Math.hypot(w.to[0] - w.from[0], w.to[1] - w.from[1]);
      if (!length) continue;
      const stopLevel = levelSpan(w.level, 'walls');
      const dx = (w.to[0] - w.from[0]) / length, dy = (w.to[1] - w.from[1]) / length;
      const { sign, outward } = wallNormal(w);
      // Outside face stays on the drawn line. Interior walls retain their
      // centreline and sample both faces to avoid piercing a sloping roof.
      const faces = w.footprint ? [-0.5, 0.5].map(f => outward.map(v => v * w.thickness * f))
        : w.exterior ? [[0, 0], outward.map(v => -v * w.thickness)]
        : [-0.5, 0.5].map(f => outward.map(v => v * w.thickness * f));
      const extension = vertex => {
        if (!w.exterior) return 0;
        const concave = b.walls.some(other => {
          if (other === w || !other.exterior || other.level !== w.level) return false;
          const near = p => Math.hypot(p[0] - vertex[0], p[1] - vertex[1]) < 1e-4;
          const away = near(other.from) ? other.to : near(other.to) ? other.from : null;
          return away && (away[0] - vertex[0]) * outward[0] + (away[1] - vertex[1]) * outward[1] > 1e-6;
        });
        return concave ? w.thickness : 0;
      };
      const next = ordered[ordered.indexOf(l) + 1], above = next ? outlines.get(next.id) : [];
      const storeyRoof = storeyRoofs.get(l.id);
      const at = (u, face) => [w.from[0] + dx * u + face[0], w.from[1] + dy * u + face[1]];
      const gables = sections.filter(s => ['gable', 'hip'].includes(s.kind)).flatMap(section => {
        const axis = section.ridge === 'y' ? 1 : 0;
        return [section.rect[axis], section.rect[axis + 2]].filter((end, i) =>
          endKind(section, `${section.ridge}${i}`) !== 'hip' && ownsGable(w, section, end)).map(end => ({ section, end, axis }));
      });
      const limits = (u, toward = u) => {
        // Stay on this side of a discontinuity, including a section rect's
        // boundary, without moving the actual wall vertices off that boundary.
        const sample = u + Math.sign(toward - u) * Math.min(1e-6, Math.abs(toward - u) / 2);
        const points = faces.map(face => at(sample, face));
        const heights = points.map(p => heightAt(storeyRoof.sections, ...p));
        const roof = heights[0] === null ? [w.height]
          : heights.filter(h => h !== null).map(h => h - l.elevation - 0.08);
        // R9: even an otherwise uncovered knee wall cannot pierce the visible
        // roof. Apply the all-section envelope cap after R5's storey rule.
        const visible = points.map(p => heightAt(sections, ...p)).filter(h => h !== null)
          .map(h => h - l.elevation - 0.08);
        const cap = next && points.some(p => above.some(poly => contains(poly, p))) ? next.elevation - 0.8 - l.elevation : Infinity;
        return [...roof, ...visible, cap];
      };
      const top = (u, toward = u) => Math.max(0, Math.min(...limits(u, toward)));
      const floorProfile = wallFloorProfile(b, w);
      const profile = { bottom: floorProfile.bottom, floorCuts: floorProfile.cuts,
        offset: w.footprint ? 0 : w.exterior ? -sign * w.thickness / 2 : 0, sign,
        slabCap: next ? next.elevation - 0.8 : NaN,
        slabOutlines: above,
        extendStart: extension(w.from), extendEnd: extension(w.to), faces, limits, positions: storeyRoof.positions,
        edges: above.flatMap(poly => poly.map((p, i) => [p, poly[(i + 1) % poly.length]])), panels: [] };
      const sideRef = side => {
        const direction = side === 'left' ? 1 : -1;
        const mid = [(w.from[0] + w.to[0]) / 2 - direction * dy * (w.thickness / 2 + 0.05),
          (w.from[1] + w.to[1]) / 2 + direction * dx * (w.thickness / 2 + 0.05)];
        const outside = w.exterior && (side === 'right' ? sign > 0 : sign < 0);
        const room = outside ? null : (b.rooms || []).find(r => r.level === w.level && r.state !== 'ghost' && contains(r.polygon, mid));
        const role = outside ? 'siding' : 'interior_wall';
        return {role, ref:surfaceRef(role, l, w.faces?.[side], {room, roomRole:'wall'})};
      };
      if (w.footprint || w.faces || l.materials || (b.rooms || []).some(r => r.level === w.level && r.wall_material)) {
        const left = sideRef('left'), right = sideRef('right'), role = w.exterior ? 'siding' : 'interior_wall';
        profile.materials = { body: mat(role, l), left: mat(left.role, l, left.ref), right: mat(right.role, l, right.ref) };
        profile.refs = {body:surfaceRef(role, l), left:left.ref, right:right.ref};
      }
      // A UV/tint-only face still inherits its asset. Reading the raw partial
      // ref here would substitute kit siding and add procedural boards to a
      // wall whose inherited household finish has no board geometry.
      const sidingRef = sideRef(sign > 0 ? 'right' : 'left').ref;
      profile.sidingAsset = materialKitFor({siding:sidingRef}).materials.siding?.asset;
      if (w.footprint?.length === 4) profile.footprint = w.footprint.map(p => {
        const x = p[0] - w.from[0], y = p[1] - w.from[1];
        return [x * dx + y * dy, x * dy - y * dx];
      });
      const holes = (b.openings || []).filter(o => o.wall === w.id).map(o => {
        const reference = openingFloor(b, w, o.at);
        return opening({ ...o, step_down_ft: reference.step_down_ft,
          sill: o.sill + reference.offset, head: o.head + reference.offset });
      });
      for (const { section, end, axis } of gables) for (const o of b.openings || []) {
        if (o.section !== section.id || o.gable !== (end === section.rect[axis] ? 'front' : 'rear')) continue;
        // Gable sill/head are relative to the plate. Project its span onto
        // the owning wall, including reversed and partial wall segments.
        const other = 1 - axis, direction = (w.to[other] - w.from[other]) / length;
        const at = (o[axis === 0 ? 'y' : 'x'] - w.from[other]) / direction;
        if (at + o.width / 2 <= 0 || at - o.width / 2 >= length) continue;
        holes.push(opening({ ...o, sill: o.sill + section.plate - l.elevation, head: o.head + section.plate - l.elevation }, at));
      }
      wall(wallFull[w.level] || local[w.level], w.from, w.to, l.elevation, w.thickness, top, holes, w.exterior, null, true, profile);
      if (viewing) {
        // Closed plain slabs, including opening notches. Built once;
        // the view only cross-fades these and the unchanged exterior walls.
        const height = cutHeight(l);
        wall(wallCut[w.level], w.from, w.to, l.elevation, w.thickness, () => height,
          holes, w.exterior, null, false, { ...profile, cutaway: true, limits: null, panels: [] });
      }
      wallProfiles.set(w.id, { panels: profile.panels, elevation: l.elevation });
      if (w.exterior && w.state !== 'ghost') supportingWalls.push({ w, l, outward, dx, dy, panels: profile.panels });
      if (w.exterior && l.elevation > 0 && w.level === first.id) wall(local[w.level], w.from, w.to, 0, w.thickness + 0.12, () => l.elevation, [], false, 'base', false, profile);
      stopLevel();
    }
    const roofGeometry = positions => {
      const geometry = new THREE.BufferGeometry(), mapped = [], uv = [];
      geometry.userData.bakePlaneSurface=true;
      for (let i = 0; i < positions.length; i += 3) {
        // This is a rotation, with determinant +1: upward winding survives.
        mapped.push(positions[i], positions[i + 2], -positions[i + 1]);
        uv.push(positions[i], positions[i + 1]);
      }
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(mapped, 3));
      geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
      geometry.computeVertexNormals(); return geometry;
    };
    // Retain the actual envelope geometry for diagnostics after it is merged.
    roofSurfaces.set(b.id, { sections: allSections, positions: allEnvelope.positions, section: allEnvelope.section, side: allEnvelope.side, edge: allEnvelope.edge });
    for (const {zone,panels} of solarZones(b,allEnvelope)) {
      const roofGroup = zone.roof !== undefined && roofGroups.find(g => g.supported && g.sections.some(s => (s.roof || s.id) === zone.roof))?.group || local.roof;
      const positions=[];
      for(const rect of panels){const corners=solarRect(rect).map(p=>solarPoint(zone.plane,p,.15));
        for(const i of [0,1,2,0,2,3])positions.push(...corners[i]);}
      // A zero-count zone remains selectable and resizable in the editor.
      use(zone,'solar_zone',zone.id);
      if(positions.length)mesh(roofGroup,roofGeometry(positions),plain('solar_panel','#285888'));
      else if(showAnchors){const p=solarRect(zone.rect).map(p=>solarPoint(zone.plane,p,.15)),empty=[];
        for(const i of [0,1,2,0,2,3])empty.push(...p[i]);
        const object=mesh(roofGroup,roofGeometry(empty),plain('solar_zone','#285888')); object.material.transparent=true; object.material.opacity=.2;}
    }
    for (const {sections, indices, roofLayers, visibleRoof, exclude, roofSidePlanes, roofIdentity, supported, group: roofGroup} of roofGroups) {
    const boxSection = supported ? sections[sections.length - 1] : null;
    const boxRecord = boxSection ? b.roofs?.find(r => r.id === (boxSection.roof || boxSection.id)) || boxSection : null;
    const boxThickness = boxSection?.thickness_ft ?? ROOF_THICKNESS;
    const rawSlabBottomAt = (x, y) => {
      const z = heightAt(sections, x, y);
      return z === null ? null : z - boxThickness;
    };
    const supportWallFaceAt = (x, y, out) => {
      let best = 0;
      for (const { w, dx, dy } of supportingWalls) {
        if (!w.footprint?.length) continue;
        const len = Math.hypot(w.to[0] - w.from[0], w.to[1] - w.from[1]);
        if (!(len > 1e-6)) continue;
        if (out && Math.abs(dx * out[0] + dy * out[1]) > 0.25) continue;
        const ux = (x - w.from[0]) * dx + (y - w.from[1]) * dy;
        const dist = Math.abs((x - w.from[0]) * dy - (y - w.from[1]) * dx);
        if (dist > (w.thickness || 0.5) / 2 + 0.15 || ux < -0.25 || ux > len + 0.25) continue;
        const proj = Math.max(...w.footprint.map(p => (p[0] - x) * out[0] + (p[1] - y) * out[1]));
        if (proj > best && proj <= (w.thickness || 0.5) + 0.1) best = proj;
      }
      return best;
    };
    const underShape = boxSection ? authoredRoofShape(boxRecord, boxSection) : null;
    const prepared = underShape ? prepareUnderside(underShape, {
      THREE, slabBottomAt: rawSlabBottomAt, wallFaceAt: supportWallFaceAt, recordEdges: boxRecord.edges,
    }) : null;
    if (prepared?.hasFlat) supportedCeilings.set(boxSection.roof || boxSection.id, prepared.ceilingZ);
    for (let index = 0; index < sections.length; index++) {
      const section = sections[index], positions = [];
      const thickness = supported ? section.thickness_ft ?? ROOF_THICKNESS : ROOF_THICKNESS;
      const bare = supported && section.fascia === false;
      const supRec = supported ? (b.roofs?.find(r => r.id === (section.roof || section.id)) || section) : null;
      const supUnder = supRec?.underside ?? section.underside;
      const supEnds = supRec?.ends ?? section.ends;
      const flatDrop = supUnder?.kind === 'flat' && Number.isFinite(supUnder.drop_ft) ? Math.max(0, Math.min(3, supUnder.drop_ft)) : 0;
      const coplanarFlatUnderside = supported && supUnder?.kind === 'flat' && flatDrop === 0
        && ((section.kind || supRec?.kind) === 'flat' || !(section.pitch || 0));
      // Only an end that draws its own frame replaces the default rake board,
      // and only a box closed on every side hides the slab's underside.
      const framedEndAt = (a, c, axis, sign) => !!prepared && prepared.isFramedShedEnd.some((framed, i) => {
        if (!framed || prepared.outs[i][axis] * sign < 0.99) return false;
        const p = prepared.drawnPoly[i], q = prepared.drawnPoly[(i + 1) % prepared.n], along = 1 - axis;
        const lo = Math.min(p[along], q[along]) - 1e-3, hi = Math.max(p[along], q[along]) + 1e-3;
        return [a, c].every(v => Math.abs(v[axis] - p[axis]) < 1e-3 && v[along] >= lo && v[along] <= hi);
      });
      const fullyClosedShedBox = !!prepared?.hasFlat && !prepared.hasAnyOpenEnd && (section.kind || supRec?.kind) === 'shed';
      use(section, 'roof', `roof:${indices[index]}`);
      const finishes = new Map(), triangleFinishes = [];
      for (let t = 0; t < roofLayers.section.length; t++) if (roofLayers.section[t] === index) {
        const ref = roofRef(section, roofLayers.edge[t]), key = JSON.stringify([ref, ref.uv ? roofLayers.edge[t] : null]);
        if (!finishes.has(key)) finishes.set(key, { ref, positions: [], stitching: [], edge: roofLayers.edge[t],
          material: mat('roof', roofLevel(section), ref) });
        const finish = finishes.get(key), triangle = Array.from(roofLayers.positions.slice(t*9,t*9+9));
        finish.positions.push(...triangle); positions.push(...triangle); triangleFinishes.push(finish);
      }
      const planePart = edge => `roof-plane:${section.roof || section.id || indices[index]}:${edge}`;
      const boxed = !coplanarFlatUnderside && bare && finishes.size === 1 && positions.length === 18
        && [0,3,6,9,12,15].every(i => {
          const r=roofBounds(section.roof_frame?{...section,roof_frame:null}:section);
          const p=section.roof_frame?roofPoint(section,positions.slice(i,i+2),true):positions.slice(i,i+2);
          return [0,1].every(axis => Math.min(Math.abs(p[axis]-r[axis]),Math.abs(p[axis]-r[axis+2]))<1e-5);
        });
      if (boxed) {
        const {origin,outward,tangent,width,depth}=supportFrame(section), slope=(section.pitch||0)/12;
        const geometry=new THREE.BoxGeometry(width,thickness,depth), p=geometry.attributes.position;
        for(let i=0;i<p.count;i++)p.setY(i,p.getY(i)-slope*p.getZ(i));
        geometry.computeVertexNormals();
        const frame=new THREE.Matrix4().makeBasis(new THREE.Vector3(tangent[0],0,-tangent[1]),
          new THREE.Vector3(0,1,0),new THREE.Vector3(outward[0],0,-outward[1])).setPosition(origin[0],0,-origin[1]);
        geometry.translate(0,section.plate+depth*slope/2-thickness/2,depth/2).applyMatrix4(frame);
        const finish=finishes.values().next().value;
        mesh(roofGroup,geometry,finish.material,null,null,finish.ref,planePart(finish.edge));
      } else for (const finish of finishes.values()) if (finish.positions.length)
        mesh(roofGroup, roofGeometry(finish.positions), finish.material, null, null, finish.ref, planePart(finish.edge));
      const block = section.block || section.rect;
      // Editor only: the live house view and wall panels never show the check marker (user,
      // 2026-11-14: "no idea why it shows on the panel").
      if (!viewing && positions.length && !section.dormer_of
          && section.rect.every((v, i) => Math.abs(v - block[i]) <= 1)
          && Array.isArray(b.roof?.flags) && b.roof.flags.some(flag => Array.isArray(flag?.block_rect)
            && flag.block_rect.length === 4 && typeof flag.text === 'string'
            && flag.block_rect.every((v, i) => Number.isFinite(v) && Math.abs(v - block[i]) <= 1))) {
        // The shared needs-checking outline keeps the settled roof and its
        // existing pick proxy, so tapping it opens the normal roof card.
        const geometry = roofGeometry(positions);
        const marker = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), ghostEdges);
        geometry.dispose();
        Object.assign(marker.userData, activePiece);
        marker.computeLineDistances(); roofGroup.add(marker);
      }
      const underside = [], edges = new Map(), trim = [];
      const below = p => [p[0], p[1], p[2] - thickness];
      const edgeKey = (a, c) => [a, c].map(p => p.map(v => Math.round(v * 1e6)).join(',')).sort().join(':');
      const band = (a, c, output, depth = thickness) => {
        const low = p => [p[0], p[1], p[2] - depth];
        // Triangle edges run counter-clockwise above, so this faces out.
        output.push(...a, ...low(a), ...low(c), ...a, ...low(c), ...c);
      };
      for (let t = 0; t < positions.length; t += 9) {
        const triangle = [0, 3, 6].map(i => positions.slice(t + i, t + i + 3));
        underside.push(...below(triangle[0]), ...below(triangle[2]), ...below(triangle[1]));
        for (let i = 0; i < 3; i++) {
          const a = triangle[i], c = triangle[(i + 1) % 3], key = edgeKey(a, c);
          if (edges.has(key)) edges.delete(key); else edges.set(key, [a, c, triangleFinishes[t/9], triangle]);
        }
      }
      for (const [a, c, finish, triangle] of edges.values()) {
        const identity = JSON.stringify([finish.material.uuid,finish.ref.uv || null]);
        const shared = sections.some((other,j) => j !== index && roofSidePlanes[j].some(plane => {
          if (roofIdentity({section:j,edge:plane.edge}) === identity
              || !triangle.every(p => Math.abs(plane[0]*p[0]+plane[1]*p[1]+plane[2]-p[2]) < 1e-5)) return false;
          const r = roofBounds(other);
          return [a,c,a.map((v,i)=>(v+c[i])/2)].every(p => p[0] >= r[0]-1e-5 && p[0] <= r[2]+1e-5
            && p[1] >= r[1]-1e-5 && p[1] <= r[3]+1e-5
            && Math.abs(Math.min(...roofSidePlanes[j].map(q=>q[0]*p[0]+q[1]*p[1]+q[2]))-p[2]) < 1e-5);
        }));
        // A shared coplanar material seam has no exposed thickness. Two bands
        // here would occupy the same plane (and fight for double-sided looks).
        if (!shared) band(a, c, finish.stitching);
      }
      if (!boxed && !coplanarFlatUnderside && !fullyClosedShedBox && underside.length) mesh(roofGroup, roofGeometry(underside), bare ? mat('roof', roofLevel(section), roofRef(section)) : kindMat('soffit', section), null, null, bare ? roofRef(section) : kindRef('soffit', section), bare ? planePart(finishes.values().next().value?.edge) : '');
      // These outward-facing shell edges are the visible covering thickness.
      for (const finish of finishes.values()) if (!boxed && finish.stitching.length)
        mesh(roofGroup, roofGeometry(finish.stitching), finish.material, null, null, finish.ref, planePart(finish.edge));
      // Only exposed section perimeters receive fascia / rake boards. Face
      // intersections and triangulation edges never grow decorative trim.
      const rect = roofBounds(section.roof_frame ? {...section, roof_frame:null} : section);
      for (let t = 0; !bare && t < visibleRoof.section.length; t++) {
        if (visibleRoof.section[t] !== index) continue;
        const triangle = [0, 3, 6].map(i => Array.from(visibleRoof.positions.slice(t * 9 + i, t * 9 + i + 3)));
        for (let i = 0; i < 3; i++) {
          const a = triangle[i], c = triangle[(i + 1) % 3];
          const edgeA = section.roof_frame ? roofPoint(section,a,true) : a,
            edgeC = section.roof_frame ? roofPoint(section,c,true) : c;
          for (let axis = 0; axis < 2; axis++) for (const sign of [-1, 1]) {
            if (framedEndAt(edgeA, edgeC, axis, sign)) continue;
            const end = rect[axis + (sign > 0 ? 2 : 0)];
            if (Math.abs(edgeA[axis] - end) > 1e-5 || Math.abs(edgeC[axis] - end) > 1e-5) continue;
            const mid = [(edgeA[0] + edgeC[0]) / 2, (edgeA[1] + edgeC[1]) / 2];
            mid[axis] += sign * 1e-4;
            const outside = heightAt(sections, ...(section.roof_frame ? roofPoint(section,mid) : mid));
            if (outside !== null && outside >= (a[2] + c[2]) / 2 - 1e-3) continue;
            // Keep the finish just proud of the solid shell's edge so the
            // roof and trim materials never occupy the same vertical plane.
            const proud = p => section.roof_frame
              ? roofPoint(section,roofPoint(section,p,true).map((v,i)=>i===axis?v+sign*FASCIA.proudFt:v))
              : p.map((v, i) => i === axis ? v + sign * FASCIA.proudFt : v);
            band(proud(a), proud(c), trim, FASCIA.depthFt);
          }
        }
      }
      if (trim.length) mesh(roofGroup, roofGeometry(trim), kindMat('fascia', section), null, null, kindRef('fascia', section));
      const wallCover = (index, axis, sign, end) => supportingWalls.flatMap(({ w, l, outward, dx, dy, panels }) => {
        const s = sections[index], along = 1 - axis;
        if (!(l.elevation + 0.5 < s.plate && s.plate <= l.elevation + l.ceiling + 2) ||
            outward[axis] * sign < 0.99 || Math.abs(w.from[axis] - w.to[axis]) > 1e-5 ||
            sign * (w.from[axis] - end) > 1e-5 || w.from[axis] < s.rect[axis] || w.from[axis] > s.rect[axis + 2]) return [];
        const direction = along === 0 ? dx : dy;
        return panels.filter(([, , ta, tc]) => Math.max(ta, tc) > 1e-5).map(([a, c, ta, tc]) => {
          const u = w.from[along] + direction * a, v = w.from[along] + direction * c;
          const poly = [[u, l.elevation], [v, l.elevation], [v, l.elevation + tc], [u, l.elevation + ta]];
          return direction > 0 ? poly : poly.reverse();
        });
      });
      const steps = supported ? [] : stepFaces(sections, { section: index, exclude, wallCover });
      if (steps.length) mesh(roofGroup, roofGeometry(steps), mat('siding'));
      // Clip standing seams to each face triangle, running down its gradient.
      // Adjacent triangles meet at the same seam spacing in plan feet.
      if (bare && materialKit.materials.roof?.asset === 'standing_seam') {
        // Seams are laid from the roof's edge, at the same spacing as an awning.
        // Merge triangle intervals so a triangulation diagonal adds no caps.
        const {origin, outward, tangent, width} = supportFrame(section);
        const frame = new THREE.Matrix4().makeBasis(new THREE.Vector3(tangent[0], 0, -tangent[1]),
          new THREE.Vector3(0, 1, 0), new THREE.Vector3(outward[0], 0, -outward[1]))
          .setPosition(origin[0], 0, -origin[1]);
        const slope = (section.pitch || 0) / 12;
        for (let u = -width / 2 + .75; u < width / 2; u += 1.5) {
          const spans = [];
          for (let t = 0; t < positions.length; t += 9) {
            const points = [0,3,6].map(i => positions.slice(t+i,t+i+3));
            const coords = points.map(p => [(p[0]-origin[0])*tangent[0]+(p[1]-origin[1])*tangent[1],
              (p[0]-origin[0])*outward[0]+(p[1]-origin[1])*outward[1], p[2]]);
            const hits = [];
            for (let i = 0; i < 3; i++) {
              const a = coords[i], c = coords[(i+1)%3], d = c[0]-a[0];
              if (Math.abs(d) < 1e-9) continue;
              const f = (u-a[0])/d;
              if (f >= -1e-8 && f <= 1+1e-8) hits.push([a[1]+f*(c[1]-a[1]),a[2]+f*(c[2]-a[2])]);
            }
            hits.sort((a,c)=>a[0]-c[0]);
            if (hits.length >= 2 && hits.at(-1)[0]-hits[0][0] > 1e-7) spans.push([hits[0],hits.at(-1)]);
          }
          spans.sort((a,c)=>a[0][0]-c[0][0]);
          const joined = [];
          for (const span of spans) {
            const last = joined.at(-1);
            if (last && span[0][0] <= last[1][0]+1e-6) { if(span[1][0]>last[1][0])last[1]=span[1]; }
            else joined.push(span);
          }
          for (const [a,c] of joined) {
            const geometry = new THREE.BoxGeometry(.065,.08,c[0]-a[0]), p = geometry.attributes.position;
            for(let i=0;i<p.count;i++)p.setY(i,p.getY(i)-slope*p.getZ(i));
            geometry.computeVertexNormals();
            geometry.translate(u,(a[1]+c[1])/2+.04,(a[0]+c[0])/2).applyMatrix4(frame);
            const finish = finishes.values().next().value;
            if(finish)mesh(roofGroup,geometry,finish.material,null,null,finish.ref,planePart(finish.edge));
          }
        }
      }
      if (!bare && materialKit.materials.roof?.asset === 'standing_seam') for (let t = 0; t < positions.length; t += 9) {
        const finish = triangleFinishes[t/9];
        const points = [0, 3, 6].map(i => new THREE.Vector3(...positions.slice(t + i, t + i + 3)));
        const normal = new THREE.Vector3().crossVectors(points[1].clone().sub(points[0]), points[2].clone().sub(points[0]));
        if (Math.abs(normal.z) < 1e-9) continue;
        const gradient = new THREE.Vector2(-normal.x / normal.z, -normal.y / normal.z);
        if (gradient.lengthSq() < 1e-10) continue;
        const across = new THREE.Vector2(-gradient.y, gradient.x).normalize();
        const values = points.map(p => across.x * p.x + across.y * p.y);
        for (let d = Math.ceil(Math.min(...values) / 1.5) * 1.5; d < Math.max(...values) - 1e-6; d += 1.5) {
          const hits = [];
          for (let i = 0; i < 3; i++) {
            const j = (i + 1) % 3;
            if (Math.abs(values[j] - values[i]) < 1e-8) continue;
            const f = (d - values[i]) / (values[j] - values[i]);
            if (f >= 0 && f <= 1) hits.push(points[i].clone().lerp(points[j], f));
          }
          if (hits.length < 2) continue;
          const a = new THREE.Vector3(hits[0].x, hits[0].z + 0.04, -hits[0].y);
          const c = new THREE.Vector3(hits[1].x, hits[1].z + 0.04, -hits[1].y);
          const delta = c.clone().sub(a), length = delta.length();
          if (length < 1e-5) continue;
          const geometry = new THREE.BoxGeometry(0.065, 0.08, length);
          geometry.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), delta.normalize()));
          geometry.translate(...a.add(c).multiplyScalar(0.5).toArray());
          mesh(roofGroup, geometry, finish.material, null, null, finish.ref, planePart(finish.edge));
        }
      }
      if (supported && index === sections.length - 1) {
        const record = b.roofs?.find(r => r.id === (section.roof || section.id)) || section;
        const shape = authoredRoofShape(record, section);
        const bAngle = (b.rotation || 0) * Math.PI / 180, cosB = Math.cos(bAngle), sinB = Math.sin(bAngle);
        const roofPorches = allPorches(b);
        const supportWallTopAt = (x, y, out = null) => {
          let best = -Infinity;
          for (const { w, l, dx, dy, panels } of supportingWalls) {
            const len = Math.hypot(w.to[0] - w.from[0], w.to[1] - w.from[1]);
            if (!(len > 1e-6)) continue;
            if (out && Math.abs(dx * out[0] + dy * out[1]) > 0.25) continue;
            const ux = (x - w.from[0]) * dx + (y - w.from[1]) * dy;
            const dist = Math.abs((x - w.from[0]) * dy - (y - w.from[1]) * dx);
            if (dist > (w.thickness || 0.5) / 2 + 0.15 || ux < -0.25 || ux > len + 0.25) continue;
            const uc = Math.max(0, Math.min(len, ux));
            let h = w.height;
            if (panels?.length) {
              const p = panels.find(([a, c]) => uc >= a - 1e-4 && uc <= c + 1e-4)
                || panels.reduce((q, r) => Math.abs((r[0] + r[1]) / 2 - uc) < Math.abs((q[0] + q[1]) / 2 - uc) ? r : q);
              h = p[1] > p[0] ? p[2] + (p[3] - p[2]) * Math.max(0, Math.min(1, (uc - p[0]) / (p[1] - p[0]))) : Math.max(p[2], p[3]);
            }
            const top = l.elevation + h;
            if (top > best) best = top;
          }
          return best > -Infinity ? best : null;
        };
        const roofSidingRef = surfaceRef('siding', roofLevel(section), record.materials?.siding);
        const roofSidingAsset = materialKitFor({ siding: roofSidingRef }).materials.siding?.asset || materialKit.materials.siding?.asset;
        const sidingIsBatten = roofSidingAsset === 'board_and_batten';
        const ceilingHeight = prepared?.hasFlat && Number.isFinite(prepared.ceilingZ) ? prepared.ceilingZ : null;
        const slabBottomAt = Number.isFinite(ceilingHeight) ? () => ceilingHeight : rawSlabBottomAt;
        const supportGroundAt = (x, y) => {
          const limit = slabBottomAt(x, y) ?? (section.plate - thickness);
          let floor = -Infinity;
          for (const po of roofPorches) {
            if (!po.polygon || po.polygon.length < 3 || !contains(po.polygon, [x, y])) continue;
            const pr = (b.rooms || []).find(r => r.kind === 'porch' && r.polygon?.length >= 3
              && r.level === (po.level || first.id)
              && (r.id === po.id || (r.polygon.every(p => contains(po.polygon, p)) && po.polygon.every(p => contains(r.polygon, p)))));
            const z = (po.floor ?? 0) + (pr?.floor_offset_ft || 0);
            if (z < limit - 0.05 && z > floor) floor = z;
          }
          for (const r of b.rooms || []) {
            if (r.state === 'ghost' || !r.polygon || r.polygon.length < 3 || !contains(r.polygon, [x, y])) continue;
            const lv = levels[r.level];
            if (!lv) continue;
            const z = roomFloor(lv, r);
            if (z < limit - 0.05 && z > floor) floor = z;
          }
          for (const lv of ordered) {
            if (lv.elevation < limit - 0.05 && lv.elevation > floor
                && (outlines.get(lv.id) || []).some(poly => contains(poly, [x, y]))) floor = lv.elevation;
          }
          if (floor > -Infinity) return floor;
          const wx = position[0] + x * cosB - y * sinB, wy = position[1] + x * sinB + y * cosB;
          return groundAt(plan, wx, wy) - base;
        };
        const underParts = prepared ? undersideGeometry(underShape, {
          THREE, groundAt: supportGroundAt, wallTopAt: supportWallTopAt,
          slabBottomAt: rawSlabBottomAt, wallFaceAt: supportWallFaceAt,
          cuts: exclude.flat(), recordEdges: record.edges, sidingIsBatten, _prepared: prepared,
        }) : [];
        for (const part of underParts) {
          let partRef, partMat;
          if (part.slot === 'underside') {
            const ownRef = resolveSlot('underside', { item: record, building: b, level: roofLevel(section) }) || plan.materials?.underside;
            partRef = ownRef ? resolveSurfaceMaterial(plan, undersideMaterialSurface(plan, b, record, kit)).ref : kindRef('soffit', record);
            partMat = ownRef ? mat('porch_ceiling', roofLevel(section), partRef) : kindMat('soffit', record);
          } else if (part.slot === 'fascia') {
            partRef = kindRef('fascia', record);
            partMat = kindMat('fascia', record);
          } else if (part.slot === 'siding') {
            partRef = roofSidingRef;
            partMat = mat('siding', roofLevel(section), record.materials?.siding);
          } else {
            partRef = kindRef('trim', record);
            partMat = kindMat('trim', record);
          }
          tagPart(mesh(roofGroup, part.geometry, partMat, null, null, partRef, part.part), part.part);
        }
        const supportSlabBottomAt = record.support?.kind === 'cable' ? rawSlabBottomAt : slabBottomAt;
        for (const part of supportGeometry(shape, supportPoints(record), {
          THREE, groundAt: supportGroundAt, wallTopAt: supportWallTopAt,
          slabBottomAt: supportSlabBottomAt, wallFaceAt: supportWallFaceAt,
        })) {
          const partSlot = part.slot || 'support';
          const postDefault = partSlot === 'column' && !record.materials?.support;
          const partRef = postDefault ? kindRef('column', record)
            : resolveSurfaceMaterial(plan, supportMaterialSurface(plan, b, record, kit)).ref;
          const partMat = postDefault ? kindMat('column', record)
            : mat('trim', roofLevel(section), partRef);
          tagPart(mesh(roofGroup, part.geometry, partMat, null, null, partRef, part.part), part.part);
        }
      }
    }
    }
    for (const gable of envelope.gables) {
      const section = sections[gable.section], [x0, y0, x1, y1] = section.rect;
      const alongX = section.ridge !== 'y';
      use(section, 'roof', `roof:${sectionIndices[gable.section]}`);
      for (const end of (alongX ? [x0, x1] : [y0, y1])) {
        const axis = alongX ? 0 : 1;
        if (endKind(section, `${section.ridge}${end === section.rect[axis] ? 0 : 1}`) === 'hip') continue;
        // Walls own gable fill wherever a top-level wall already follows it.
        const owned = b.walls.some(w => ownsGable(w, section, end));
        if (owned) continue;
        const endPositions = [];
        for (let i = 0; i < gable.positions.length; i += 9) if (Math.abs(gable.positions[i + axis] - end) < 1e-4) endPositions.push(...gable.positions.slice(i, i + 9));
        if (!endPositions.length) continue;
        const front = end === (alongX ? x0 : y0);
        // Retain P0's gable plate and corner trim on the supporting floor.
        if (section.gable_beam === true) {
          mesh(local[first.id], alongX
            ? boxRect(end - .35, y0 - .35, end + .35, y1 + .35, section.plate - .65, section.plate)
            : boxRect(x0 - .35, end - .35, x1 + .35, end + .35, section.plate - .65, section.plate), mat('trim'));
          for (const u of alongX ? [y0,y1] : [x0,x1]) mesh(local[first.id], alongX
            ? boxRect(end - .3, u - .3, end + .3, u + .3, first.elevation, section.plate - .65)
            : boxRect(u - .3, end - .3, u + .3, end + .3, first.elevation, section.plate - .65), mat('trim'));
        }
        const holes = (b.openings || []).filter(o => o.section === section.id && o.gable === (front ? 'front' : 'rear'));
        if (holes.length) {
          const from = alongX ? [end, front ? y1 : y0] : [front ? x0 : x1, end];
          const to = alongX ? [end, front ? y0 : y1] : [front ? x1 : x0, end];
          const other = 1 - axis, direction = Math.sign(to[other] - from[other]);
          // This separate windowed gable extrusion must sit under the roof
          // shell; its top cap previously lay directly on the rake surface.
          const top = u => Math.max(0, roofHeight(from[0] + (alongX ? 0 : direction * u), from[1] + (alongX ? direction * u : 0)) - section.plate - ROOF_THICKNESS);
          const openings = holes.map(o => opening(o, (o[alongX ? 'y' : 'x'] - from[other]) * direction));
          wall(local.gableFull, from, to, section.plate, 0.5, top, openings, true);
          wall(local.gableCut, from, to, section.plate, 0.5, u => Math.min(8, top(u)), openings.filter(o => o.v1 <= 8), true);
        } else {
          mesh(local.gableFull, roofGeometry(endPositions), mat('siding'));
          // Clip each triangle to the same eight-foot cutaway used by P0.
          const cut = [];
          for (let i = 0; i < endPositions.length; i += 9) {
            const poly = [0, 3, 6].map(j => endPositions.slice(i + j, i + j + 3)), clipped = [], ceiling = section.plate + 8;
            let previous = poly.at(-1);
            for (const point of poly) {
              if ((previous[2] <= ceiling) !== (point[2] <= ceiling)) {
                const f = (ceiling - previous[2]) / (point[2] - previous[2]);
                clipped.push(previous.map((v, k) => v + f * (point[k] - v)));
              }
              if (point[2] <= ceiling) clipped.push(point);
              previous = point;
            }
            for (let j = 1; j + 1 < clipped.length; j++) cut.push(...clipped[0], ...clipped[j], ...clipped[j + 1]);
          }
          if (cut.length) mesh(local.gableCut, roofGeometry(cut), mat('siding'));
        }
      }
    }
    if (buildingHasGutters(b, allSections)) {
      const sections = allSections;
      const slice = gutters || sliceForBuilding(resolveGutterPlacement(plan, timing), b.id);
      const bAngle = (b.rotation || 0) * Math.PI / 180, cosB = Math.cos(bAngle), sinB = Math.sin(bAngle);
      const bx0 = b.position?.[0] || 0, by0 = b.position?.[1] || 0;
      const gutterOwner = seg => {
        if (!seg) return null;
        const midLocal = seg.a && seg.b ? (() => {
          const u = (seg.a[0] + seg.b[0]) * 0.5 / FT - bx0, v = -(seg.a[2] + seg.b[2]) * 0.5 / FT - by0;
          return [cosB * u + sinB * v, -sinB * u + cosB * v];
        })() : null;
        const pickClosest = list => {
          if (list.length <= 1 || !midLocal) return list[0] || null;
          let best = list[0], bestD = Infinity;
          for (const s of list) {
            const oh = s.overhang || 0, [x0, y0, x1, y1] = s.rect;
            const cx = Math.max(x0 - oh, Math.min(x1 + oh, midLocal[0]));
            const cy = Math.max(y0 - oh, Math.min(y1 + oh, midLocal[1]));
            const d = Math.hypot(cx - midLocal[0], cy - midLocal[1]);
            if (d < bestD) { bestD = d; best = s; }
          }
          return best;
        };
        const withLevel = section => section ? (section.level ? section : { ...section, level: roofLevel(section)?.id }) : null;
        if (seg.roof !== null && seg.roof !== undefined) {
          const matching = sections.filter(s => (s.roof || s.id) === seg.roof);
          return withLevel(pickClosest(matching));
        }
        if (seg.porch !== null && seg.porch !== undefined) {
          const po = allPorches(b).find(p => p.id === seg.porch);
          if (po) {
            if (po.materials?.gutter) return po;
            const matching = po.polygon?.length >= 3
              ? sections.filter(s => contains(po.polygon, [(s.rect[0] + s.rect[2]) / 2, (s.rect[1] + s.rect[3]) / 2]))
              : [];
            const sec = pickClosest(matching);
            return sec ? withLevel(sec) : po;
          }
        }
        return null;
      };
      const gStart = performance.now();
      const gutterParts = buildGutterGeometry(b, base, slice.runs, slice.spouts, seg => {
        const owner = gutterOwner(seg);
        const matGutter = kindMat('gutter', owner), refGutter = kindRef('gutter', owner);
        const supportedRoof = owner && isSupported(owner) ? owner.roof || owner.id : null;
        const supportedLevel = supportedRoof ? roofLevel(owner).id : null;
        return { mat: matGutter, ref: refGutter, key: `${matGutter.uuid}:${JSON.stringify(refGutter?.uv || null)}${supportedLevel ? ':supported:' + supportedLevel : ''}`,
          seed: `${b.id}:gutter:${owner?.id || 'default'}`, supportedRoof, supportedLevel };
      });
      const gMs = performance.now() - gStart;
      _gutterPlacementStats.lastGeometryMs += gMs;
      if (timing) timing.gutter_geometry_ms = (timing.gutter_geometry_ms || 0) + gMs;
      for (const { geometry: gutterGeo, mat: matGutter, ref: refGutter, seed } of gutterParts) {
        if (refGutter?.uv) uvParts.push({ geometry: gutterGeo, material: matGutter, seed, offset: refGutter.uv, key: JSON.stringify([b.id, seed, refGutter.uv]) });
        else offsetSurfaceUvs(gutterGeo, matGutter, seed);
        const roofGroup = supportedLevels.get(gutterGeo.userData.supportedLevel) || local.roof;
        const gMesh = addMesh(roofGroup, gutterGeo, matGutter);
        gMesh.userData.surfaceKind = 'gutter';
        gMesh.userData.buildingId = b.id;
        gMesh.userData.kind = 'roof';
        gMesh.userData.part = 'gutter';
        gMesh.userData.bakePart = 'gutter';
        if (gutterGeo.userData.snapRanges) gMesh.userData.snapRanges = gutterGeo.userData.snapRanges;
      }
    }
    const porches = allPorches(b);
    const ceilingSlabs = [];
    const hasCeilings = (b.rooms || []).some(r => r.ceiling_material || resolveSlot('ceiling', { building: b, level: levels[r.level] }) || plan.materials?.ceiling);
    const porchRoom = po => (b.rooms || []).find(r => r.kind === 'porch' && r.polygon?.length >= 3
      && (r.level === (po.level || first.id)) && (r.id === po.id
        || r.polygon.every(p => contains(po.polygon, p)) && po.polygon.every(p => contains(r.polygon, p))));
    // A half-storey gets its own outline-based slab just like a full level.
    for (const l of ordered) {
      const stopLevel = levelSpan(l.id, 'floors');
      use({ ...l, id: `floor:${l.id}` }, 'floor', `floor:${l.id}`);
      const floorOutlines = outlines.get(l.id);
      const rooms = (b.rooms || []).filter(r => r.level === l.id && r.polygon?.length >= 3);
      const surfaces = rooms.length ? rooms : floorOutlines.map(polygon => ({ polygon }));
      const holes = stairHoles(b, l);
      for (const room of surfaces) {
        const poly = room.polygon;
        const porch = room.kind === 'porch' && porches.find(po => po.polygon && porchRoom(po) === room);
        const elevation = (porch ? porch.floor : l.elevation) + (room.floor_offset_ft || 0);
        use(room.id ? room : { ...l, id: `floor:${l.id}` }, room.id ? 'room' : 'floor', `floor:${l.id}`);
        // Only insert stair holes fully contained in this footprint.
        const cuts = holes.filter(h => h.every(p => contains(poly, p)));
        const slabBottom = porch ? elevation - (porchFoundation(porch.foundation).type === 'solid' ? PORCH_SLAB_FT : POST_SLAB_FT)
          : l.id === first.id && !room.floor_offset_ft ? 0 : elevation - .8;
        // Rooms stay their own pieces for selection; the level is one floor origin, so a
        // finish running through several rooms stays continuous.
        const floorSeed = `${b.id}:floor:${l.id}`;
        // The lowest floor at grade rests on the foundation, which already fills to this line.
        if (slabBottom < elevation - FLOOR_GAP_FT) {
          const slab = polygon(poly, slabBottom, elevation - FLOOR_GAP_FT, cuts);
          // A porch slab's edges show, so they wear the floor's own finish.
          mesh(local[l.id], slab, porch ? mat('patio_concrete', l, room.floor_material)
            : mat(l.id === first.id ? 'patio_concrete' : 'interior_wall'), null, floorSeed,
            porch ? surfaceRef('patio_concrete', l, room.floor_material) : null);
          // Keep only bottom faces, in plan x/y/z feet, before static merging.
          if (hasCeilings) {
            const g = slab.index ? slab.toNonIndexed() : slab, p = g.attributes.position, n = g.attributes.normal, positions = [];
            for (let i = 0; i < p.count; i += 3) if (n.getY(i) < -.99)
              for (let j = i; j < i + 3; j++) positions.push(p.getX(j), -p.getZ(j), p.getY(j));
            if (g !== slab) g.dispose();
            ceilingSlabs.push({ group: local[l.id], level: l, elevation: slabBottom, positions });
          }
        }
        const role = porch ? 'patio_concrete' : 'floor';
        mesh(local[l.id], polygon(poly, elevation, elevation, cuts), mat(role, l, room.floor_material), null, floorSeed,
          surfaceRef(role, l, room.floor_material));
      }
      // Room boundaries stop at the wall lines. Their slab plus these mitred
      // wall footprints fills the level through to its exterior faces.
      if (l.id !== first.id) for (const wall of b.walls.filter(w => w.level === l.id && w.exterior
        && w.kind !== 'separator' && w.state !== 'ghost' && w.footprint?.length === 4)) {
        use({ ...l, id: `floor:${l.id}` }, 'floor', `floor:${l.id}`);
        const triangles = THREE.ShapeUtils.triangulateShape(wall.footprint.map(p => new THREE.Vector2(...p)), [])
          .map(indices => indices.map(i => wall.footprint[i]));
        const parts = rooms.some(r => r.floor_offset_ft) ? foundationPieces(b, l, triangles)
          : [{polygon: wall.footprint, top: l.elevation}];
        for (const {polygon: area, top} of parts) mesh(local[l.id], polygon(area, top - .8, top), mat('siding', l));
      }
      stopLevel();
    }
    for (const room of b.rooms || []) {
      const level = levels[room.level], slot = room.ceiling_material || resolveSlot('ceiling', { building: b, level }) || plan.materials?.ceiling;
      if (!slot || !level || !(room.polygon?.length >= 3)) continue;
      const supports = ceilingSlabs.filter(s => s.level.elevation > level.elevation && s.elevation > roomFloor(level, room))
        .sort((a, c) => a.elevation - c.elevation);
      const roof = roofEnvelope(sections.filter(s => s.plate > level.elevation + .5)).walled;
      const positions = Array.from(roof.positions, (v, i) => i % 3 === 2 ? v - ROOF_THICKNESS : v);
      supports.push({ group: local.roof, positions });
      use(room, 'room', room.id);
      for (const [group, patch] of ceilingPatches(room, supports)) {
        const ceiling = mesh(group, roofGeometry(patch), kindMat('ceiling', room), null, null, kindRef('ceiling', room), 'ceiling');
        tagPart(ceiling, 'ceiling');
      }
    }
    for (const [index, po] of porches.entries()) {
      if (!po.polygon) continue;
      use(po, 'porch', po === b.porch ? 'porch' : `porch:${index}`);
      const room = porchRoom(po), foundation = porchFoundation(po.foundation), solid = foundation.type === 'solid';
      const floor = po.floor + (room?.floor_offset_ft || 0);
      const slabBottom = floor - (solid ? PORCH_SLAB_FT : POST_SLAB_FT);
      const slot = (name, role) => material(() => materialSlot(foundation.materials[name], role, materialKit, tier, materials, mat));
      if (!room) mesh(local[first.id], polygon(po.polygon, slabBottom, floor), mat('patio_concrete'));
      if (solid || porchOnGrade(plan, b, po, floor, base)) {
        mesh(local[first.id], porchPlinthGeometry(plan, b, po, slabBottom, base),
          solid ? slot('solid', 'base') : mat('patio_concrete'), null, null,
          solid ? surfaceRef('base', null, foundation.materials.solid) : null, 'foundation');
      } else {
        const geometry = porchSupportGeometry(plan, b, po, floor, base);
        if (geometry.supports) mesh(local[first.id], geometry.supports, slot('posts', 'trim'), null, null,
          surfaceRef('trim', null, foundation.materials.posts), 'foundation-posts');
        if (geometry.skirt) mesh(local[first.id], geometry.skirt, slot('skirt', 'lattice'), null, null,
          surfaceRef('lattice', null, foundation.materials.skirt), 'foundation-skirt');
      }
      const topAt = (x, y) => {
        const roof = heightAt(sections, x, y);
        // Tuck into the roof shell, allowing for the triangulated surface's
        // small difference from the analytic height at overlapping sections.
        const height = roof !== null && roof !== undefined ? roof - ROOF_THICKNESS + 0.05
          : first.elevation + first.ceiling;
        return supportCap(x, y, floor, height);
      };
      for (const c of po.columns || []) {
        const top = topAt(...c.at);
        if (solid && top <= floor) continue;
        tagPart(mesh(local[first.id], boxRect(c.at[0] - c.size / 2, c.at[1] - c.size / 2, c.at[0] + c.size / 2, c.at[1] + c.size / 2, floor, top), kindMat('column', po), null, null, kindRef('column', po), 'column'), 'column');
      }
      const porchWalls = b.walls.filter(w => w.exterior && (levels[w.level]?.elevation ?? 0) <= floor
        && (levels[w.level]?.elevation ?? 0) + w.height > floor);
      if (po.screened === true) for (let i = 0; i < po.polygon.length; i++) {
        const a = po.polygon[i], endPoint = po.polygon[(i + 1) % po.polygon.length];
        const dx = endPoint[0] - a[0], dy = endPoint[1] - a[1], length = Math.hypot(dx, dy);
        if (!length) continue;
        const project = p => ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length;
        const distance = p => Math.abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / length;
        const posts = (po.columns || []).filter(c => distance(c.at) <= c.size / 2 + 0.1
          && project(c.at) >= 0 && project(c.at) <= length).sort((c, d) => project(c.at) - project(d.at));
        // Polygon corners close the ends too: an attached side needs a panel
        // from the house wall to its single outside post (R19).
        posts.unshift({ at: a, size: 0 });
        posts.push({ at: endPoint, size: 0 });
        for (let j = 1; j < posts.length; j++) {
          const c = posts[j - 1], d = posts[j], span = Math.hypot(d.at[0] - c.at[0], d.at[1] - c.at[1]);
          if (span <= (c.size + d.size) / 2) continue;
          const basis = wallBasis(c.at, d.at, floor);
          // Subtract wall spans so an attached side never receives a screen.
          let gaps = [[c.size / 2, span - d.size / 2]];
          for (const w of porchWalls) {
            if (distance(w.from) > w.thickness + 0.1 || distance(w.to) > w.thickness + 0.1) continue;
            const lo = Math.min(project(w.from), project(w.to)) - project(c.at), hi = Math.max(project(w.from), project(w.to)) - project(c.at);
            gaps = gaps.flatMap(([s, e]) => hi <= s || lo >= e ? [[s, e]] : [[s, Math.max(s, lo)], [Math.min(e, hi), e]].filter(([u, v]) => v > u));
          }
          for (const [start, end] of gaps) {
            const shape = new THREE.Shape(); shape.moveTo(start, 0); shape.lineTo(end, 0);
            const count = Math.max(1, Math.ceil((end - start) * 2));
            for (let k = count; k >= 0; k--) {
              const t = start + (end - start) * k / count;
              shape.lineTo(t, Math.max(0, topAt(c.at[0] + (d.at[0] - c.at[0]) * t / span, c.at[1] + (d.at[1] - c.at[1]) * t / span) - floor));
            }
            shape.closePath();
            tagPart(mesh(local[first.id], new THREE.ShapeGeometry(shape).applyMatrix4(basis.matrix), kindMat('screen', po), null, null, kindRef('screen', po), 'screen'), 'screen');
          }
        }
      }
    }
    for (const [index, s] of (b.stairs || []).entries()) {
      use(s, 'stair', `stair:${index}`);
      const l = levels[s.level] || first;
      for (const part of stairGeometry(s, l.elevation, boxGeometry)) tagPart(mesh(local[l.id], part.geometry, kindMat(part.kind, s), null, null, kindRef(part.kind, s), part.kind), part.kind);
    }
    for (const opening of b.openings || []) {
      use(opening, 'opening', `opening:${opening.wall}:${opening.at}`);
      for (const step of doorwaySteps(b, opening)) mesh(local[step.level], polygon(step.polygon, step.bottom, step.top),
        mat('floor', levels[step.level], step.room.floor_material), null, null,
        surfaceRef('floor', levels[step.level], step.room.floor_material));
    }
    const itemIds = new Set((b.items || []).filter(item => item.asset).map(item => item.id));
    const fixtureFallbacks = new Map();
    const drawFixture = (f, index, group = null, owner = null) => {
      if (!objectShown(f, showAnchors || !!editableLevel)) return;
      use(owner || f, owner ? 'item' : 'fixture', `fixture:${index}`);
      const l = levels[f.level]; if (!l || !f.rect) return;
      const g = group || local[l.id], [x0, y0, x1, y1] = f.rect;
      const floorRoom = f.host && !f.host.floor ? null
        : b.rooms?.find(r => r.id === f.host?.floor) || roomAt(b, l.id, [(x0+x1)/2, (y0+y1)/2]);
      const z = roomFloor(l, floorRoom) + (f.z0 || 0), h = f.height || 1;
      const box = (a, c, d, e, lo, hi, m, part = null) => {
        const origin = [(x0 + x1) / 2, z, -(y0 + y1) / 2];
        const geometry = boxRect(a, c, d, e, lo, hi).translate(-origin[0], -origin[1], -origin[2]);
        const object = applyObject(new THREE.Mesh(geometry, m), f, { units: 1, id: `${b.id}:${f.id}` });
        object.position.set(origin[0], origin[1] + (f.elevation || 0), origin[2]); object.updateMatrixWorld(true);
        bakeMatrix(geometry, object.matrixWorld);
        const result = mesh(g, geometry, object.material, null, null, part ? kindRef(part, f) : null, part || '');
        return part ? tagPart(result, part) : result;
      };
      if (['counter', 'vanity'].includes(f.kind)) {
        box(x0, y0, x1, y1, z, z + h - 0.12, kindMat('cabinet', f), 'cabinet');
        box(x0 - 0.05, y0 - 0.05, x1 + 0.05, y1 + 0.05, z + h - 0.12, z + h, kindMat('counter', f), 'counter');
      } else if (f.kind === 'shower') {
        box(x0, y0, x1, y1, z, z + 0.2, kindMat('shower_tile', f), 'shower_tile');
        box(x0, y0, x1, y0 + 0.04, z + 0.2, z + h, kindMat('shower_glass', f), 'shower_glass');
      } else if (f.kind === 'sofa') {
        box(x0, y0, x1, y1, z, z + h / 2, plain('fabric', '#8c8f94'));
        box(x0, y1 - 0.8, x1, y1, z, z + h, plain('fabric', '#8c8f94'));
      } else if (['table', 'bench'].includes(f.kind)) {
        box(x0, y0, x1, y1, z + h - 0.15, z + h, mat('floor'));
        for (const x of [x0 + 0.2, x1 - 0.2]) for (const y of [y0 + 0.2, y1 - 0.2]) box(x - 0.08, y - 0.08, x + 0.08, y + 0.08, z, z + h - 0.15, mat('floor'));
      } else {
        const m = ['fridge', 'grill'].includes(f.kind) ? mat('stainless') : plain(f.kind, f.color || (f.kind === 'toilet' ? '#f4f4f2' : '#2f3338'));
        box(x0, y0, x1, y1, z, z + h, m);
      }
    };
    for (const [index, f] of (b.fixtures || []).entries()) {
      if (itemIds.has(f.id)) fixtureFallbacks.set(f.id, { piece: f, index });
      else drawFixture(f, index);
    }
    for (const [index, l] of (b.lights || []).entries()) {
      if (!l.device && !objectShown(l, showAnchors || !!editableLevel)) continue;
      use(l, 'light', `light:${index}`);
      const level = levels[l.level] || first;
      const height = l.room === 'Porch' ? level.elevation + level.ceiling - 2 : Math.min(level.elevation + level.ceiling - 0.25, roofHeight(...l.at) - 0.5);
      let y = height;
      if (supportedSections.length) {
        const porch = l.room === 'Porch' && porches.find(po => (po.level || first.id) === level.id && contains(po.polygon, l.at));
        const room = (b.rooms || []).find(r => r.level === level.id && r.polygon?.length >= 3 && contains(r.polygon, l.at));
        const floor = porch ? porch.floor + (porchRoom(porch)?.floor_offset_ft || 0) : room ? roomFloor(level, room) : level.elevation;
        y = supportCap(...l.at, floor, height);
      }
      const size = l.kind === 'recessed' ? 0.6 : 1.4;
      const light = new THREE.RectAreaLight('#ffc98a', l.kind === 'recessed' ? 9 : 6, size, size);
      light.position.set(l.at[0], y, -l.at[1]); light.lookAt(l.at[0], y - 1, -l.at[1]);
      light.userData.level = levelKey(l.level); light.userData.elevation = base + level.elevation; light.visible = false;
      Object.assign(light.userData, activePiece);
      local.lights.add(light); roomLights.push(light);
      const geometry = boxRect(-size / 2, -size / 2, size / 2, size / 2, 0, .05);
      const object = applyObject(new THREE.Mesh(geometry, fixture), l, { units: 1, id: `${b.id}:${l.id}` });
      object.position.set(l.at[0], y + (l.elevation || 0), -l.at[1]); object.updateMatrixWorld(true);
      bakeMatrix(geometry, object.matrixWorld); mesh(local[level.id], geometry, object.material);
    }
    const hostLevel = host => {
      const surface = 'wall' in host ? b.walls.find(w => w.id === host.wall)
        : 'floor' in host || 'ceiling' in host ? (b.rooms || []).find(r => r.id === (host.floor ?? host.ceiling))
        : (b.roofs || []).find(r => r.id === host.roof);
      return levels[surface?.level] || first;
    };
    for (const anchor of b.anchors || []) {
      if (!anchor.device && !objectShown(anchor, showAnchors || !!editableLevel)) continue;
      const equipment=['meter','electric_panel','charger'].includes(anchor.kind);
      if(!showAnchors && !equipment)continue;
      // A light already has a fixture registered under this same identity.
      if (anchor.kind === 'light') continue;
      let point;
      try { point = anchor.kind==='parking'?parkingPoint(b,anchor,plan,(anchor.offset || 0)+.04,groundAt):hostPoint(b, anchor.host, (anchor.offset || 0) + 0.04); }
      catch { continue; } // Missing hosts remain represented by model flags.
      use(anchor, 'anchor', anchor.id);
      if(anchor.kind==='parking'){
        const width=anchor.width || 9,depth=anchor.depth || 18,angle=(anchor.rotation || 0)*Math.PI/180;
        const material=plain('parking_outline','#d7dbe0');
        const segment=(x,y,w,d)=>{const g=boxRect(x-w/2,y-d/2,x+w/2,y+d/2,point[2],point[2]+.025);
          g.rotateY(angle);g.translate(point[0],0,-point[1]);mesh(local[hostLevel(anchor.host).id],g,material);};
        for(let x=-width/2;x<width/2;x+=1.5)for(const y of [-depth/2,depth/2])segment(Math.min(x+.5,width/2),y,Math.min(1,width/2-x),.12);
        for(let y=-depth/2;y<depth/2;y+=1.5)for(const x of [-width/2,width/2])segment(x,Math.min(y+.5,depth/2),.12,Math.min(1,depth/2-y));
        if(!parkingIcon){
          const canvas=document.createElement('canvas');canvas.width=canvas.height=192;const ctx=canvas.getContext('2d');
          ctx.scale(8,8);ctx.strokeStyle='#d7dbe0';ctx.lineWidth=1.5;ctx.lineCap='round';ctx.lineJoin='round';
          for(const [tag,a] of LUCIDE.car){
            if(tag==='path' && typeof Path2D==='function')ctx.stroke(new Path2D(a.d));
            if(tag==='circle'){ctx.beginPath();ctx.arc(Number(a.cx),Number(a.cy),Number(a.r),0,Math.PI*2);ctx.stroke();}
          }
          const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
          parkingIcon=plain('parking_icon','#ffffff',{map:texture,transparent:true,alphaTest:.05,depthWrite:false,side:THREE.DoubleSide});
        }
        const glyph=new THREE.PlaneGeometry(4,4).rotateX(-Math.PI/2).rotateY(angle).translate(point[0],point[2]+.04,-point[1]);
        mesh(local[hostLevel(anchor.host).id],glyph,parkingIcon);
        continue;
      }
      const geometry = equipment ? new THREE.BoxGeometry(1.2,.4,anchor.kind==='meter'?1.5:2) : new THREE.CylinderGeometry(0.22, 0.22, 0.06, 16);
      const wall = b.walls.find(w => w.id === anchor.host.wall);
      if (wall) {
        const dx = wall.to[0] - wall.from[0], dy = wall.to[1] - wall.from[1];
        const direction = anchor.host.side === 'right' ? -1 : 1;
        geometry.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0),
          new THREE.Vector3(-dy * direction, 0, -dx * direction).normalize()));
      }
      let anchorMaterial = plain(equipment?'equipment':'anchor',equipment?'#8c9399':'#38bdf8');
      if (!anchor.device) {
        const object = applyObject(new THREE.Mesh(geometry, anchorMaterial), anchor, { units: 1, id: `${b.id}:${anchor.id}` });
        object.updateMatrixWorld(true); bakeMatrix(geometry, object.matrixWorld); anchorMaterial = object.material;
      }
      geometry.translate(point[0], point[2] + (anchor.elevation || 0), -point[1]);
      mesh(local[hostLevel(anchor.host).id], geometry, anchorMaterial);
      if(anchor.kind==='meter' && wall){
        const dial=new THREE.CylinderGeometry(.4,.4,.07,24);
        const dx=wall.to[0]-wall.from[0],dy=wall.to[1]-wall.from[1],direction=anchor.host.side==='right'?-1:1;
        const normal=new THREE.Vector3(-dy*direction,0,-dx*direction).normalize();
        dial.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),normal));
        dial.translate(point[0]+normal.x*.25,point[2],-point[1]+normal.z*.25);
        mesh(local[hostLevel(anchor.host).id],dial,plain('meter_dial','#e7e9e5'));
      }
    }
    // Proxies retain identity after settled render meshes are merged. Their
    // layer is never enabled on a rendering camera (including shadow cameras).
    const registerRecords = () => {
      offsetSurfaceUvParts(uvParts.splice(0));
      for (const [key, { data, group, box, partObjects }] of records) {
        if (box.isEmpty() || pieceBounds.has(key)) continue;
        pieceBounds.set(key, { box: box.clone(), group, data });
        const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
        const wall = b.walls.find(w => w.id === data.pieceId);
        let geometry, outlinePositions;
        const profile = wall && wallProfiles.get(wall.id), panels = profile?.panels.filter(([a, c]) => c > a);
        if (panels?.length) {
          // Follow the wall's drawn top (gables, dormer cheeks, steps), so a
          // tall wall's pick never stands above the roof that covers it.
          const bottom = box.min.y - profile.elevation, depth = wall.thickness + 0.2;
          const outline = [[panels[0][0], bottom], [panels.at(-1)[1], bottom]];
          for (const [a, c, ta, tc] of [...panels].reverse()) outline.push([c, Math.max(bottom, tc)], [a, Math.max(bottom, ta)]);
          geometry = new THREE.ExtrudeGeometry(new THREE.Shape(outline.map(p => new THREE.Vector2(...p))), { depth, bevelEnabled: false, steps: 1 })
            .translate(0, 0, -depth / 2).applyMatrix4(wallBasis(wall.from, wall.to, profile.elevation).matrix);
        } else if (wall) {
          const basis = wallBasis(wall.from, wall.to, box.min.y);
          geometry = boxGeometry(basis.length, size.y, wall.thickness + 0.2).translate(basis.length / 2, size.y / 2, 0).applyMatrix4(basis.matrix);
        } else if (data.kind === 'roof') {
          const index = allSections.findIndex((s, i) => (s.id || `roof:${i}`) === data.pieceId), positions = [];
          for (let t = 0; t < allRoofLayers.section.length; t++) if (allRoofLayers.section[t] === index) positions.push(...allRoofLayers.positions.slice(t * 9, t * 9 + 9));
          geometry = roofGeometry(positions);
          // Roof and support hits share one identity, visibility and lock path.
          // These pick-only triangles never enter a render or shadow camera.
          const supportParts = (partObjects || []).map(p => p.object).filter(o => (o.userData.part || '').startsWith('support:'));
          if (supportParts.length) {
            outlinePositions = roofOutlinePositions(geometry.attributes.position.array, supportParts);
            const picks = [geometry, ...supportParts.map(o => o.geometry)].map(g => {
              const copy = g.index ? g.toNonIndexed() : g.clone();
              for (const name of Object.keys(copy.attributes)) if (!['position', 'normal', 'uv'].includes(name)) copy.deleteAttribute(name);
              return copy;
            });
            const combined = mergeGeometries(picks);
            for (const g of picks) g.dispose();
            if (combined) { geometry.dispose(); geometry = combined; }
          }
        } else geometry = boxGeometry(Math.max(0.01, size.x), Math.max(0.01, size.y), Math.max(0.01, size.z)).translate(...center.toArray());
        const proxy = new THREE.Mesh(geometry, pickMaterial);
        Object.assign(proxy.userData, data); proxy.layers.set(PICK_LAYER);
        if (outlinePositions) Object.defineProperty(proxy.userData, 'outlinePositions', { value: outlinePositions });
        if (data.kind === 'roof' && (partObjects || []).some(p => (p.object.userData.part || '').startsWith('support:'))) proxy.userData.supportPick = true;
        if (partObjects) Object.defineProperty(proxy.userData, 'partObjects', { value: partObjects });
        group.add(proxy); pickObjects.set(key, proxy);
      }
      pieces.touch();
    };
    registerRecords();
    // Ghost batching disposes its source meshes. Retain the drawn slab and
    // seams for rain first: legacy ghost awnings still intercepted rain,
    // although their gutter flag never created a solid gutter or spout.
    // Supports must not become little rain-catching roof surfaces.
    for (const [level, group] of supportedLevels) group.traverse(o => {
      const record = b.roofs?.find(r => r.id === o.userData.pieceId) || allSections.find(s => (s.roof || s.id) === o.userData.pieceId);
      if (!o.isMesh || o.layers.isEnabled(PICK_LAYER) || !o.userData.ghost || o.userData.kind !== 'roof'
          || record?.position && record?.why
          || (o.userData.part || '').startsWith('support:')
          || o.userData.surfaceKind === 'gutter' || !o.geometry?.attributes.position) return;
      if (!ghostRoofCover.has(b.id)) ghostRoofCover.set(b.id, []);
      const target = ghostRoofCover.get(b.id), p = o.geometry.attributes.position, index = o.geometry.index;
      const chain = [], matrix = new THREE.Matrix4();
      for (let parent = o; parent && parent !== local[level]; parent = parent.parent) {
        if (parent.matrixAutoUpdate) parent.updateMatrix();
        chain.push(parent.matrix);
      }
      for (let i = chain.length - 1; i >= 0; i--) matrix.multiply(chain[i]);
      const vertices = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()], normal = new THREE.Vector3();
      for (let i = 0; i < (index?.count ?? p.count); i += 3) {
        vertices.forEach((v, j) => v.fromBufferAttribute(p, index ? index.getX(i+j) : i+j).applyMatrix4(matrix));
        THREE.Triangle.getNormal(...vertices, normal);
        if (normal.y > .001) for (const v of vertices) target.push(v.x, -v.z, v.y);
      }
    });
    for (const [key, { data }] of records) if (data.ghost) ghostBatches.push(batchGhost(root, pieces.get(key), ghost, ghostEdges));
    const models = new Map(), lateItems = new Map(), itemGroups = new Map();
    const jobs = (b.items || []).filter(item => item.asset && objectShown(item, showAnchors || !!editableLevel)).map(async item => {
      const asset = item.asset.replace(/^polyhaven:/, '');
      let point, source;
      try { point = hostPoint(b, item.host, item.offset || 0); }
      catch { /* Retain any legacy fixture when its host is unavailable. */ }
      const fallback = fixtureFallbacks.get(item.id);
      // Keep an expired request's fallback separate from shared batches, so a
      // late model can replace just that item without disturbing its neighbours.
      const holder = new THREE.Group();
      let ghostUpdate = null;
      const draw = (source, late = false) => {
        if (root.userData.disposed) { if (source) disposeObject(source); return; }
        if (!source && !fallback) return;
        const level = !source && fallback ? levels[fallback.piece.level] : hostLevel(item.host);
        if (!level) { if (source) disposeObject(source); return; }
        const key = `${b.id}:${item.id}`;
        const proxy = pickObjects.get(key);
        if (proxy) { proxy.removeFromParent(); proxy.geometry.dispose(); pickObjects.delete(key); }
        for (const object of pieces.get(key) || []) {
          const parent = object.parent; object.removeFromParent(); object.geometry?.dispose();
          if (parent && parent !== holder && !parent.children.length) parent.removeFromParent();
        }
        if (ghostUpdate) { ghostBatches.splice(ghostBatches.indexOf(ghostUpdate), 1); ghostUpdate = null; }
        holder.clear(); holder.removeFromParent();
        pieces.delete(key); pieceBounds.delete(key); records.delete(key);
        if (!itemGroups.has(level.id)) {
          const group = new THREE.Group(); local[level.id].add(group); itemGroups.set(level.id, group);
        }
        const group = source && !late ? itemGroups.get(level.id) : holder;
        if (group === holder) local[level.id].add(holder);
        if (source) {
          const model = source;
          applyObject(model, item, { id: `${b.id}:${item.id}` });
          // Structural finish reuse must not give a replacement asset the old
          // item's imported materials (even when its piece id is unchanged).
          cacheModelMaterials(model, 'item:' + b.id + ':' + item.id + ':' + JSON.stringify([asset, modelAssetKey(asset, kit)])
            + ':' + objectMaterialKey(item, `${b.id}:${item.id}`), materials);
          model.position.set(point[0], point[2] + (item.elevation || 0), -point[1]);
          model.updateMatrixWorld(true);
          use(item, 'item', item.id);
          if (model.isLOD) {
            retainLod(group, model); registerRecords(); return;
          }
          model.traverse(object => {
            if (object.isMesh) mesh(group, bakeMatrix(object.geometry.clone(), object.matrixWorld), object.material);
          });
          const geometries = new Set(); model.traverse(o => { if (o.geometry) geometries.add(o.geometry); });
          geometries.forEach(g => g.dispose());
        } else drawFixture(fallback.piece, fallback.index, group, item);
        registerRecords();
        if (item.state === 'ghost' && pieces.has(key)) {
          ghostUpdate = batchGhost(root, pieces.get(key), ghost, ghostEdges); ghostBatches.push(ghostUpdate);
        }
        if (late) {
          batch(holder, { perPiece: levelKey(level.id) === editableLevel });
          writeWeatherOpen(holder, createSkyCover(plan, roofSurfaces));
        }
      };
      if (point) {
        if (!models.has(asset)) {
          lateItems.set(asset, []);
          models.set(asset, loadModel(asset, kit, model => {
            if (root.userData.disposed) { disposeObject(model); return; }
            for (const update of lateItems.get(asset)) update(model.clone(true), true);
          }, { tier: modelTier, editor: !viewing, onFailure: onAssetFailure }));
        }
        lateItems.get(asset).push(draw);
        source = await models.get(asset);
      }
      draw(source?.clone(true));
    });
    pendingModels.push(Promise.all(jobs).then(() => {
      for (const [level, group] of itemGroups) batch(group, { perPiece: levelKey(level) === editableLevel });
    }));
    if (timing) {
      timing.buildings.push({ id: b.id, levels: levelTiming,
        generate: Math.max(0, performance.now() - buildingStart - (detail.materials - buildingMaterials) - (detail.batch - buildingBatch)) });
      ++timing.counts.buildings; timing.counts.levels += b.levels.length;
    }
  }
  // Merge within independently switchable domains, never across a floor cut.
  // Capture the actual roof surfaces, including supported roofs,
  // before material batching loses their independent transforms.
  for (const b of plan.buildings || []) {
    const domain = groups.roof.children.find(g => g.userData.buildingId === b.id);
    const supportedIds = new Set((b.roof?.sections || []).flatMap((s, i) => isSupported(s) ? [s.id || `roof:${i}`] : []));
    const positions = [...(ghostRoofCover.get(b.id) || [])], slabs = [], attachments = new Map(), a = new THREE.Vector3(), c = new THREE.Vector3(), d = new THREE.Vector3(), n = new THREE.Vector3();
    const capture = (o, target, ceiling = false, space = domain) => {
      if (!o.isMesh || o.userData.ghost || o.userData.surfaceKind === 'gutter' || !o.geometry?.attributes.position) return;
      const p = o.geometry.attributes.position, index = o.geometry.index;
      // Stay in building-local feet. Updating parent world matrices here
      // introduces the root's metre scale before mergeStatic runs, changing
      // its float roundoff (and the otherwise byte-identical UV golden).
      const chain = [], matrix = new THREE.Matrix4();
      for (let parent = o; parent && parent !== space; parent = parent.parent) {
        if (parent.matrixAutoUpdate) parent.updateMatrix();
        chain.push(parent.matrix);
      }
      for (let i = chain.length - 1; i >= 0; i--) matrix.multiply(chain[i]);
      for (let i = 0; i < (index?.count ?? p.count); i += 3) {
        for (const [v, j] of [[a, 0], [c, 1], [d, 2]]) v.fromBufferAttribute(p, index ? index.getX(i+j) : i+j).applyMatrix4(matrix);
        THREE.Triangle.getNormal(a, c, d, n);
        if (ceiling ? Math.abs(n.y) <= .001 : n.y <= .001) continue;
        for (const v of [a, c, d]) target.push(v.x, -v.z, v.y);
      }
    };
    domain?.traverse(o => {
      capture(o, positions);
      if(Number.isInteger(o.userData.eaveAttachment)){
        const section=o.userData.eaveAttachment;
        if(!attachments.has(section))attachments.set(section,[]);
        capture(o, attachments.get(section));
      }
    });
    for (const group of Object.values(groups.levels)) if (group.userData.buildingId === b.id)
      for (const space of group.children) space.traverse(o => {
        const partName = o.userData.part || '';
        if (o.userData.kind === 'roof' && !o.layers.isEnabled(PICK_LAYER) && supportedIds.has(o.userData.pieceId)
            && !partName.startsWith('support:') && partName !== 'underside'
            && partName !== 'underside:front' && !partName.startsWith('end:')) capture(o, positions, false, space);
        if (o.userData.part === 'ceiling' || ['floor', 'room'].includes(o.userData.kind)) capture(o, slabs, o.userData.part === 'ceiling', space);
      });
    if (roofSurfaces.has(b.id)) Object.assign(roofSurfaces.get(b.id), {coverPositions: positions, slabPositions: slabs,
      eaveAttachments:[...attachments].map(([section,positions])=>({section,positions}))});
  }
  for (const g of mergeGroups) batch(g, { perPiece: !!editableLevel && g.userData.levelKey === editableLevel });
  groups.gableCut.visible = false;
  const updateGhosts = () => ghostBatches.forEach(update => update());
  updateGhosts();
  // The view's supplementary room meshes still use the plan's floor role.
  if (plan.buildings?.length && !materials.has('floor')) material(() => materials.set('floor', kitMaterial('floor', materialKitFor(plan.materials), tier)));
  const ready = Promise.all(pendingModels).then(() => Promise.all([...materials.values()].map(m => m.userData.ready)));
  // These two shared materials may have no objects in a settled-only plan.
  materials.set('ghostEdges', ghostEdges); materials.set('pick', pickMaterial);
  if (timing) detail.generate += Math.max(0, performance.now() - generationStart - (detail.materials - materialBefore) - (detail.batch - batchBefore));
  return { root, groups, pieces, pieceBounds, pickObjects, roofSurfaces, roomLights, levelElevations, materials, ready, updateGhosts, notes,
    stale: false, get degraded() { return failedModel || [...materials.values()].some(m => m.userData.assetFailed); } };
}
