// Plan -> geometry. Plan x/y map to world X/-Z; heights are world Y.
// All geometry is in plan feet; only the returned root converts to metres.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { kitMaterial } from './twin_library.js';
import { roofMesh, heightAt, stepFaces } from './twin_roof.js';
import { groundAt } from './twin_ground.js';

export const FT = 0.3048;
export const PICK_LAYER = 31;
const ROOF_THICKNESS = 0.25;
export function mergeStatic(group) {
  group.updateMatrixWorld(true);
  const inverse = group.matrixWorld.clone().invert(), buckets = new Map();
  group.traverse(o => {
    if (!o.isMesh || o.userData.ghost || o.layers.isEnabled(PICK_LAYER) || o.isInstancedMesh || o.isSkinnedMesh || Array.isArray(o.material) ||
        !o.geometry?.attributes.position || Object.keys(o.geometry.morphAttributes || {}).length) return;
    let g;
    try {
      g = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone();
      const count = g.attributes.position.count;
      if (g.attributes.position.itemSize !== 3 || !count || count % 3) { g.dispose(); return; }
      for (const key of Object.keys(g.attributes)) if (!['position', 'normal', 'uv'].includes(key)) g.deleteAttribute(key);
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
      g.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inverse, o.matrixWorld));
      if (!buckets.has(o.material)) buckets.set(o.material, []);
      buckets.get(o.material).push({ geometry: g, mesh: o });
    } catch { g?.dispose(); } // An odd optional model stays independently drawn.
  });
  const old = new Set();
  for (const [mat, entries] of buckets) {
    let geometry;
    try { geometry = mergeGeometries(entries.map(e => e.geometry)); }
    catch { /* Keep the originals if a model cannot be merged. */ }
    finally { entries.forEach(e => e.geometry.dispose()); }
    if (!geometry) continue;
    entries.forEach(e => { e.mesh.removeFromParent(); old.add(e.mesh.geometry); });
    const mesh = new THREE.Mesh(geometry, mat);
    mesh.userData.merged = true;
    // Keep the piece registry pointing at live render objects after batching.
    entries.forEach(e => {
      const objects = e.mesh.userData.pieceObjects;
      if (objects) {
        const index = objects.indexOf(e.mesh);
        if (index >= 0) objects.splice(index, 1);
        if (!objects.includes(mesh)) objects.push(mesh);
      }
    });
    mesh.castShadow = !mat.transparent;
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  const retained = new Set(); group.traverse(o => { if (o.geometry) retained.add(o.geometry); });
  old.forEach(g => { if (!retained.has(g)) g.dispose(); });
}

// BoxGeometry's face UVs span 0..1; the kit repeats every 4 (or 8) feet.
// Scale before rotating so each face has the same physical texture density.
export function boxGeometry(width, height, depth) {
  const g = new THREE.BoxGeometry(width, height, depth), uv = g.attributes.uv, normal = g.attributes.normal;
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
export function polygon(poly, z0, z1 = z0, holes = []) {
  const s = new THREE.Shape(poly.map(p => new THREE.Vector2(...p)));
  holes.filter(h => h.length >= 3).forEach(h => s.holes.push(new THREE.Path(h.map(p => new THREE.Vector2(...p)))));
  const g = z1 === z0 ? new THREE.ShapeGeometry(s) : new THREE.ExtrudeGeometry(s, { depth: z1 - z0, bevelEnabled: false, steps: 1 });
  return g.rotateX(-Math.PI / 2).translate(0, z0, 0);
}
export function addMesh(group, geometry, material) {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = !material.transparent; mesh.receiveShadow = true;
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
  const remaining = walls.filter(w => w.exterior).map(w => [w.from, w.to]), out = [];
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
function contains(poly, [x, y]) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [ax, ay] = poly[j], [bx, by] = poly[i], dx = bx - ax, dy = by - ay;
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy || 1)));
    if (Math.hypot(x - ax - t * dx, y - ay - t * dy) < 1e-7) return true;
    if ((ay > y) !== (by > y) && x < ax + dx * (y - ay) / dy) inside = !inside;
  }
  return inside;
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

export function buildTwin(plan, kit, tier) {
  const root = new THREE.Group(); root.scale.setScalar(FT);
  const pieces = new Map(), pieceBounds = new Map(), pickObjects = new Map(), roofSurfaces = new Map(), mergeGroups = [], ghostBatches = [];
  const groups = { site: new THREE.Group(), roof: new THREE.Group(), gableFull: new THREE.Group(), gableCut: new THREE.Group(), lights: new THREE.Group(), levels: {} };
  for (const [id, group] of Object.entries(groups)) if (group.isGroup) { group.name = id; root.add(group); }
  const materialKitFor = refs => {
    const materialKit = { ...kit, materials: { ...kit.materials } };
    for (const [role, ref] of Object.entries(refs || {})) {
      const known = kit.manifest || window.twinManifest || {};
      // Semantic ids resolve through the kit's role; actual asset ids win.
      materialKit.materials[role] = { ...kit.materials?.[role], color: ref.color || kit.materials?.[role]?.color,
        asset: known[ref.id] ? ref.id : kit.materials?.[role]?.asset };
    }
    return materialKit;
  };
  const materials = new Map();
  const plain = (name, color, extra = {}) => {
    const key = name + color;
    if (!materials.has(key)) materials.set(key, new THREE.MeshStandardMaterial({ name, color, roughness: 0.8, ...extra }));
    return materials.get(key);
  };
  const glass = plain('glass', '#b9d7db', { transparent: true, opacity: 0.26, roughness: 0.1, depthWrite: false });
  const fixture = plain('fixture', '#fff4e0', { emissive: '#ffd59a', emissiveIntensity: 0 });
  const ghost = plain('ghost', '#38bdf8', { opacity: 0.35, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 });
  const ghostEdges = new THREE.LineDashedMaterial({ color: '#38bdf8', dashSize: 0.4, gapSize: 0.25, transparent: true, opacity: 0.8, depthWrite: false });
  const pickMaterial = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide });
  const roomLights = [], levelElevations = {}, notes = [];
  for (const b of plan.buildings || []) {
    const materialKit = materialKitFor({ ...plan.materials, ...b.materials });
    const mat = role => {
      const key = Object.hasOwn(b.materials || {}, role) ? JSON.stringify([b.id, role]) : role;
      if (!materials.has(key)) materials.set(key, kitMaterial(role, materialKit, tier));
      return materials.get(key);
    };
    const levels = Object.fromEntries(b.levels.map(l => [l.id, l]));
    const ordered = [...b.levels].sort((a, c) => a.elevation - c.elevation), first = ordered[0];
    if (!first) continue;
    const local = {};
    const position = b.position || [0, 0];
    const base = groundAt(plan, ...position) + (b.base || 0);
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
      g.rotation.y = (b.rotation || 0) * Math.PI / 180;
      g.userData.buildingId = b.id; g.userData.levelKey = levels[id] ? key : null;
      (groups[id] || groups.levels[key]).add(g);
      if (id !== 'lights') mergeGroups.push(g);
    }
    ordered.forEach(l => { levelElevations[levelKey(l.id)] = base + l.elevation; });
    const sections = b.roof?.sections || [];
    const envelope = roofMesh(sections);
    const outlines = new Map(ordered.map(l => [l.id, l.outline?.length >= 3 ? [l.outline] : footprints(b.walls.filter(w => w.level === l.id))]));
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
    const roofLayers = roofMesh(sections, { retainLower: true, exclude });
    const visibleRoof = envelope;
    const storeyRoofs = new Map(ordered.map(l => {
      const own = sections.filter(s => l.elevation + 0.5 < s.plate && s.plate <= l.elevation + l.ceiling + 2);
      return [l.id, { sections: own,
        positions: new Float32Array([...roofMesh(own).positions, ...envelope.positions]) }];
    }));
    let activePiece = null;
    const records = new Map();
    const use = (piece, kind, fallback) => { activePiece = { pieceId: piece.id || fallback, kind, buildingId: b.id, ghost: piece.state === 'ghost' }; };
    const mesh = (group, geometry, material) => {
      const data = activePiece || { pieceId: 'structure', kind: 'building', buildingId: b.id };
      const key = `${b.id}:${data.pieceId}`;
      const object = addMesh(group, geometry, data.ghost ? ghost : material);
      Object.assign(object.userData, data);
      if (!pieces.has(key)) pieces.set(key, []);
      const objects = pieces.get(key); objects.push(object);
      // Non-enumerable: this back-reference is used only while merging.
      Object.defineProperty(object.userData, 'pieceObjects', { value: objects });
      if (!records.has(key)) records.set(key, { data, group, box: new THREE.Box3() });
      geometry.computeBoundingBox(); records.get(key).box.union(geometry.boundingBox);
      return object;
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
    const supportingWalls = [];
    function wall(group, from, to, elevation, thickness, top, holes, exterior, role = null, clipRoof = true, profile = {}) {
      const { matrix, length, z } = wallBasis(from, to, elevation);
      if (!length) return;
      const start = -(profile.extendStart || 0), end = length + (profile.extendEnd || 0), offset = profile.offset || 0;
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
      const cuts = [...new Set([start, end, ...samples, ...holes.flatMap(h => [h.u0, h.u1])].filter(u => u >= start && u <= end))].sort((a, c) => a - c);
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
      // Leave roof-covered wall tops open beneath the roof shell. Keep the
      // original profiles (R5''' / R9), window sills and uncovered wall caps.
      const omitCoveredCap = (geo, a, c, ta, tc, faceOffset) => {
        const p = geo.attributes.position, n = geo.attributes.normal, indices = [];
        const point = new THREE.Vector3();
        for (let i = 0; i < p.count; i += 3) {
          let cap = exterior && clipRoof && n.getY(i) > 1e-5;
          for (let j = i; cap && j < i + 3; j++) {
            const expected = ta + (tc - ta) * (p.getX(j) - a) / (c - a);
            point.set(p.getX(j), p.getY(j), p.getZ(j) + faceOffset).applyMatrix4(matrix);
            cap = p.getY(j) >= expected - 1e-5 && heightAt(sections, point.x, -point.z) !== null;
          }
          if (!cap) indices.push(i, i + 1, i + 2);
        }
        if (indices.length < p.count) geo.setIndex(indices);
      };
      for (let i = 0; i < cuts.length - 1; i++) {
        const a = cuts[i], c = cuts[i + 1], mid = (a + c) / 2;
        if (c - a < 0.0001) continue;
        if (!role) profile.panels?.push([a, c, top(a, mid), top(c, mid)]);
        let intervals = [[0, Infinity]];
        holes.filter(h => mid > h.u0 && mid < h.u1).forEach(h => {
          intervals = intervals.flatMap(([lo, hi]) => [[lo, Math.min(hi, h.v0)], [Math.max(lo, h.v1), hi]].filter(([p, q]) => q > p));
        });
        for (const [lo, hi] of intervals) {
          // Evaluate from this interval's side of a roof/floor boundary. A
          // single shared height at a step would interpolate siding across it.
          const ta = Math.min(hi, top(a, mid)), tc = Math.min(hi, top(c, mid));
          if (ta <= lo && tc <= lo) continue;
          const shape = new THREE.Shape([[a, lo], [c, lo], [c, Math.max(lo, tc)], [a, Math.max(lo, ta)]].map(p => new THREE.Vector2(...p)));
          const geo = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false, steps: 1 });
          omitCoveredCap(geo, a, c, top(a, mid), top(c, mid), offset - thickness / 2);
          geo.translate(0, 0, offset - thickness / 2).applyMatrix4(matrix);
          mesh(group, geo, wallMat);
        }
      }
      const sign = profile.sign || Math.sign(z.dot(new THREE.Vector3((from[0] + to[0]) / 2 - center[0], 0, -(from[1] + to[1]) / 2 + center[1]))) || 1;
      const localBox = (u, v, w, h, d, material, faceOffset = 0) => mesh(group, boxGeometry(w, h, d).translate(u, v, offset + faceOffset).applyMatrix4(matrix), material);
      if (exterior && materialKit.materials.siding?.asset === 'board_and_batten' && !role) {
        for (let u = 0.5; u < length; u += 1) {
          let intervals = [[0, Infinity]];
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
            omitCoveredCap(geo, a, c, top(a, mid), top(c, mid), offset + sign * (thickness / 2 + 0.045) - 0.045);
            geo.translate(0, 0, offset + sign * (thickness / 2 + 0.045) - 0.045).applyMatrix4(matrix);
            mesh(group, geo, wallMat);
          }
        }
      }
      const wallPiece = activePiece;
      for (const h of holes) {
        if (h.kind === 'passage') continue;
        use({ ...h, state: wallPiece.ghost ? 'ghost' : h.state }, 'opening', `opening:${h.wall || h.section}:${h.u0}`);
        const width = h.u1 - h.u0, height = h.v1 - h.v0, cu = (h.u0 + h.u1) / 2, cv = (h.v0 + h.v1) / 2;
        const fw = 0.16;
        for (const u of [h.u0, h.u1]) {
          localBox(u, cv, fw, height, 0.22, mat('window_frame'));
          if (exterior) localBox(u + (u === h.u0 ? -0.18 : 0.18), cv, 0.33, height + 0.66, 0.12, mat('trim'), sign * (thickness / 2 + 0.06));
        }
        for (const v of [h.v0, h.v1]) localBox(cu, v, width, fw, 0.22, mat('window_frame'));
        if (exterior) for (const v of [h.v0, h.v1]) if (v > 0.01) localBox(cu, v + (v === h.v0 ? -0.18 : 0.18), width + 0.66, 0.33, 0.12, mat('trim'), sign * (thickness / 2 + 0.06));
        if (h.kind === 'door') {
          if (h.glass === 'half') {
            localBox(cu, h.v0 + height / 4, width - fw, height / 2, 0.15, mat('door'));
            localBox(cu, h.v0 + height * 0.75, width - fw, height / 2 - fw, 0.025, glass);
            localBox(cu, cv, width, fw, 0.22, mat('window_frame'));
          } else localBox(cu, cv, width - fw, height - fw, 0.15, mat('door'));
        } else {
          for (let i = 1; i < (h.panels || 1); i++) localBox(h.u0 + width * i / h.panels, cv, fw, height, 0.22, mat('window_frame'));
          if (h.split === 'double_hung') localBox(cu, cv, width, fw, 0.22, mat('window_frame'));
          localBox(cu, cv, width - fw, height - fw, 0.025, glass);
        }
      }
      activePiece = wallPiece;
    }
    const opening = (o, at = o.at) => ({ ...o, u0: at - o.width / 2, u1: at + o.width / 2, v0: o.sill, v1: o.head });
    const ownsGable = (w, section, end) => {
      const axis = section.ridge === 'y' ? 1 : 0, other = 1 - axis;
      return w.state !== 'ghost' && w.level === ordered.at(-1).id &&
        Math.abs(w.from[axis] - end) < 1e-4 && Math.abs(w.to[axis] - end) < 1e-4 &&
        Math.max(w.from[other], w.to[other]) > section.rect[other] && Math.min(w.from[other], w.to[other]) < section.rect[other + 2];
    };
    for (const w of b.walls) {
      const l = levels[w.level]; if (!l) continue;
      use(w, 'wall', w.id);
      const length = Math.hypot(w.to[0] - w.from[0], w.to[1] - w.from[1]);
      if (!length) continue;
      const dx = (w.to[0] - w.from[0]) / length, dy = (w.to[1] - w.from[1]) / length;
      const { sign, outward } = wallNormal(w);
      // Outside face stays on the drawn line. Interior walls retain their
      // centreline and sample both faces to avoid piercing a sloping roof.
      const faces = w.exterior ? [[0, 0], outward.map(v => -v * w.thickness)]
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
      const gables = sections.filter(s => s.kind === 'gable').flatMap(section => {
        const axis = section.ridge === 'y' ? 1 : 0;
        return [section.rect[axis], section.rect[axis + 2]].filter(end => ownsGable(w, section, end)).map(end => ({ section, end, axis }));
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
      const profile = { offset: w.exterior ? -sign * w.thickness / 2 : 0, sign,
        extendStart: extension(w.from), extendEnd: extension(w.to), faces, limits, positions: storeyRoof.positions,
        edges: above.flatMap(poly => poly.map((p, i) => [p, poly[(i + 1) % poly.length]])), panels: [] };
      const holes = (b.openings || []).filter(o => o.wall === w.id).map(o => opening(o));
      for (const { section, end, axis } of gables) for (const o of b.openings || []) {
        if (o.section !== section.id || o.gable !== (end === section.rect[axis] ? 'front' : 'rear')) continue;
        // Gable sill/head are relative to the plate. Project its span onto
        // the owning wall, including reversed and partial wall segments.
        const other = 1 - axis, direction = (w.to[other] - w.from[other]) / length;
        const at = (o.x - w.from[other]) / direction;
        if (at + o.width / 2 <= 0 || at - o.width / 2 >= length) continue;
        holes.push(opening({ ...o, sill: o.sill + section.plate - l.elevation, head: o.head + section.plate - l.elevation }, at));
      }
      wall(local[w.level], w.from, w.to, l.elevation, w.thickness, top, holes, w.exterior, null, true, profile);
      if (w.exterior && w.state !== 'ghost') supportingWalls.push({ w, l, outward, dx, dy, panels: profile.panels });
      if (w.exterior && l.elevation > 0 && w.level === first.id) wall(local[w.level], w.from, w.to, 0, w.thickness + 0.12, () => l.elevation, [], false, 'base', false, profile);
    }
    const roofGeometry = positions => {
      const geometry = new THREE.BufferGeometry(), mapped = [], uv = [];
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
    roofSurfaces.set(b.id, { sections, positions: envelope.positions });
    for (let index = 0; index < sections.length; index++) {
      const section = sections[index], positions = [];
      use(section, 'roof', `roof:${index}`);
      for (let t = 0; t < roofLayers.section.length; t++) if (roofLayers.section[t] === index) positions.push(...roofLayers.positions.slice(t * 9, t * 9 + 9));
      if (positions.length) mesh(local.roof, roofGeometry(positions), mat('roof'));
      const underside = [], edges = new Map(), stitching = [], trim = [];
      const below = p => [p[0], p[1], p[2] - ROOF_THICKNESS];
      const edgeKey = (a, c) => [a, c].map(p => p.map(v => Math.round(v * 1e6)).join(',')).sort().join(':');
      const band = (a, c, output, depth = ROOF_THICKNESS) => {
        const low = p => [p[0], p[1], p[2] - depth];
        // Triangle edges run counter-clockwise above, so this faces out.
        output.push(...a, ...low(a), ...low(c), ...a, ...low(c), ...c);
      };
      for (let t = 0; t < positions.length; t += 9) {
        const triangle = [0, 3, 6].map(i => positions.slice(t + i, t + i + 3));
        underside.push(...below(triangle[0]), ...below(triangle[2]), ...below(triangle[1]));
        for (let i = 0; i < 3; i++) {
          const a = triangle[i], c = triangle[(i + 1) % 3], key = edgeKey(a, c);
          if (edges.has(key)) edges.delete(key); else edges.set(key, [a, c]);
        }
      }
      for (const [a, c] of edges.values()) band(a, c, stitching);
      if (underside.length) mesh(local.roof, roofGeometry(underside), mat('porch_ceiling'));
      if (stitching.length) mesh(local.roof, roofGeometry(stitching), mat('roof'));
      // Only exposed section perimeters receive fascia / rake boards. Face
      // intersections and triangulation edges never grow decorative trim.
      const oh = section.overhang || 0, rect = section.rect.map((v, i) => v + (i < 2 ? -oh : oh));
      for (let t = 0; t < visibleRoof.section.length; t++) {
        if (visibleRoof.section[t] !== index) continue;
        const triangle = [0, 3, 6].map(i => Array.from(visibleRoof.positions.slice(t * 9 + i, t * 9 + i + 3)));
        for (let i = 0; i < 3; i++) {
          const a = triangle[i], c = triangle[(i + 1) % 3];
          for (let axis = 0; axis < 2; axis++) for (const sign of [-1, 1]) {
            const end = rect[axis + (sign > 0 ? 2 : 0)];
            if (Math.abs(a[axis] - end) > 1e-5 || Math.abs(c[axis] - end) > 1e-5) continue;
            const mid = [(a[0] + c[0]) / 2, (a[1] + c[1]) / 2];
            mid[axis] += sign * 1e-4;
            const outside = heightAt(sections, ...mid);
            if (outside !== null && outside >= (a[2] + c[2]) / 2 - 1e-3) continue;
            // Keep the finish just proud of the solid shell's edge so the
            // roof and trim materials never occupy the same vertical plane.
            const proud = p => p.map((v, i) => i === axis ? v + sign * 0.01 : v);
            band(proud(a), proud(c), trim, ROOF_THICKNESS + 0.1);
          }
        }
      }
      if (trim.length) mesh(local.roof, roofGeometry(trim), mat('trim'));
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
      const steps = stepFaces(sections, { section: index, exclude, wallCover });
      if (steps.length) mesh(local.roof, roofGeometry(steps), mat('siding'));
      // Clip standing seams to each face triangle, running down its gradient.
      // Adjacent triangles meet at the same seam spacing in plan feet.
      if (materialKit.materials.roof?.asset === 'standing_seam') for (let t = 0; t < positions.length; t += 9) {
        const points = [0, 3, 6].map(i => new THREE.Vector3(...positions.slice(t + i, t + i + 3)));
        const normal = new THREE.Vector3().crossVectors(points[1].clone().sub(points[0]), points[2].clone().sub(points[0]));
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
          geometry.translate(...a.add(c).multiplyScalar(0.5).toArray()); mesh(local.roof, geometry, mat('roof'));
        }
      }
    }
    for (const gable of envelope.gables) {
      const section = sections[gable.section], [x0, y0, x1, y1] = section.rect;
      const alongX = section.ridge !== 'y';
      use(section, 'roof', `roof:${gable.section}`);
      for (const end of (alongX ? [x0, x1] : [y0, y1])) {
        const axis = alongX ? 0 : 1;
        // Walls own gable fill wherever a top-level wall already follows it.
        const owned = b.walls.some(w => ownsGable(w, section, end));
        if (owned) continue;
        const endPositions = [];
        for (let i = 0; i < gable.positions.length; i += 9) if (Math.abs(gable.positions[i + axis] - end) < 1e-4) endPositions.push(...gable.positions.slice(i, i + 9));
        if (!endPositions.length) continue;
        const front = end === (alongX ? x0 : y0);
        // Retain P0's gable plate and corner trim on the supporting floor.
        if (!alongX && section.id === 'roof-main' && b.roof?.extensions?.some(e => e.section === section.id && ['shed_continuation', 'awning'].includes(e.kind))) {
          mesh(local[first.id], boxRect(x0 - 0.35, end - 0.35, x1 + 0.35, end + 0.35, section.plate - 0.65, section.plate), mat('trim'));
          for (const x of [x0, x1]) mesh(local[first.id], boxRect(x - 0.3, end - 0.3, x + 0.3, end + 0.3, first.elevation, section.plate - 0.65), mat('trim'));
        }
        const holes = (b.openings || []).filter(o => o.section === section.id && o.gable === (front ? 'front' : 'rear'));
        if (holes.length && !alongX) {
          const from = [front ? x0 : x1, end], to = [front ? x1 : x0, end];
          // This separate windowed gable extrusion must sit under the roof
          // shell; its top cap previously lay directly on the rake surface.
          const top = u => Math.max(0, roofHeight(front ? x0 + u : x1 - u, end) - section.plate - ROOF_THICKNESS);
          const openings = holes.map(o => opening(o, front ? o.x - x0 : x1 - o.x));
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
    for (const extension of b.roof?.extensions || []) {
      const section = sections.find(s => s.id === extension.section); if (!section) continue;
      use(section, 'roof', `roof:${sections.indexOf(section)}`);
      const [x0, y0, x1, y1] = section.rect, oh = section.overhang || 0;
      const roofPlane = (a, c, start, end) => {
        const angle = Math.atan2(c[1] - a[1], c[0] - a[0]), length = Math.hypot(c[0] - a[0], c[1] - a[1]);
        const at = (g, offset = 0) => g.rotateZ(angle).translate((a[0] + c[0]) / 2 - Math.sin(angle) * offset, (a[1] + c[1]) / 2 + Math.cos(angle) * offset, -(start + end) / 2);
        mesh(local.roof, at(new THREE.BoxGeometry(length, 0.4, end - start), 0.2), mat('roof'));
        if (materialKit.materials.roof?.asset === 'standing_seam') for (let y = start + 0.75; y < end; y += 1.5) mesh(local.roof, at(new THREE.BoxGeometry(length, 0.08, 0.065), 0.44).translate(0, 0, -y + (start + end) / 2), mat('roof'));
        for (const y of [start, end]) mesh(local.roof, at(new THREE.BoxGeometry(length, 0.65, 0.14)).translate(0, 0, -y + (start + end) / 2), mat('trim'));
      };
      if (extension.kind === 'shed_continuation') {
        const end = extension.to_x + (extension.overhang || 0);
        roofPlane([x1, section.plate], [end, section.plate - (end - x1) * extension.pitch / 12], y0 - oh, y1 + oh);
      } else if (extension.kind === 'awning') {
        const aw = extension, exterior = b.walls.filter(w => w.exterior);
        let support = exterior.find(w => w.id === aw.wall);
        if (!aw.wall) {
          // Prefer the section's front wall with the largest covered span.
          let overlap = 0;
          for (const w of exterior) {
            if (Math.abs(w.from[1] - y0) > 1e-4 || Math.abs(w.to[1] - y0) > 1e-4) continue;
            const covered = Math.min(aw.x1, Math.max(w.from[0], w.to[0])) - Math.max(aw.x0, Math.min(w.from[0], w.to[0]));
            if (covered > overlap) { support = w; overlap = covered; }
          }
          if (!support) {
            const midpoint = [(aw.x0 + aw.x1) / 2, y0];
            let nearest = 2 + 1e-6;
            for (const w of exterior) {
              const dx = w.to[0] - w.from[0], dy = w.to[1] - w.from[1];
              const t = Math.max(0, Math.min(1, ((midpoint[0] - w.from[0]) * dx + (midpoint[1] - w.from[1]) * dy) / (dx * dx + dy * dy)));
              const distance = Math.hypot(midpoint[0] - w.from[0] - t * dx, midpoint[1] - w.from[1] - t * dy);
              if (distance < nearest) { support = w; nearest = distance; }
            }
          }
        }
        if (!support) {
          notes.push({ code: 'extension_skipped', building: b.id, section: section.id, kind: aw.kind, reason: 'No exterior wall near the awning span.' });
          continue;
        }
        // Use the same outside face as the wall's siding. Span coordinates
        // run along plan x for front/back walls, or plan y for side walls.
        const n = wallNormal(support).outward, outward = new THREE.Vector3(n[0], 0, -n[1]);
        const tangent = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), outward);
        const axis = Math.abs(tangent.x) >= Math.abs(tangent.z) ? 0 : 1;
        const spanMid = (aw.x0 + aw.x1) / 2;
        const t = (spanMid - support.from[axis]) / (support.to[axis] - support.from[axis]);
        const origin = new THREE.Vector3(support.from[0] + t * (support.to[0] - support.from[0]), 0, -support.from[1] - t * (support.to[1] - support.from[1]));
        const frame = new THREE.Matrix4().makeBasis(tangent, new THREE.Vector3(0, 1, 0), outward).setPosition(origin);
        const width = (aw.x1 - aw.x0) / Math.abs(axis === 0 ? tangent.x : tangent.z);
        const slope = aw.pitch / 12, rise = aw.depth * slope;
        // Shear the boxes so their top edges meet the face and eave exactly;
        // thickness stays below that plane rather than lifting the low edge.
        const slopedBox = (w, h, depth, gradient, u, height) => {
          const g = new THREE.BoxGeometry(w, h, depth), p = g.attributes.position;
          for (let i = 0; i < p.count; i++) p.setY(i, p.getY(i) + gradient * p.getZ(i));
          g.computeVertexNormals();
          return g.translate(u, height, depth / 2).applyMatrix4(frame);
        };
        const topMid = aw.eave + rise / 2;
        mesh(local.roof, slopedBox(width, 0.3, aw.depth, -slope, 0, topMid - 0.15), mat('roof'));
        if (materialKit.materials.roof?.asset === 'standing_seam') for (let u = -width / 2 + 0.75; u < width / 2; u += 1.5) {
          mesh(local.roof, slopedBox(0.065, 0.08, aw.depth, -slope, u, topMid + 0.04), mat('roof'));
        }
        const run = Math.min(3, aw.depth * 0.8), bracketRise = run * 2.6 / 3;
        const bracketMid = aw.eave + rise - run * slope - 0.3 - 0.15 - 0.04 - bracketRise / 2;
        for (let i = 0; i < (aw.brackets || 0); i++) {
          const inset = Math.min(0.6, width / 2);
          const u = -width / 2 + inset + i * (width - 2 * inset) / Math.max(1, aw.brackets - 1);
          mesh(local[support.level], slopedBox(0.3, 0.3, run, bracketRise / run, u, bracketMid), mat('trim'));
        }
      }
    }
    for (const l of ordered) {
      use({ ...l, id: `floor:${l.id}` }, 'floor', `floor:${l.id}`);
      const floorOutlines = outlines.get(l.id);
      const polys = floorOutlines.length ? floorOutlines : (b.rooms || []).filter(r => r.level === l.id).map(r => r.polygon);
      const holes = (b.stairs || []).filter(s => s.rise_to >= l.elevation && l.elevation > first.elevation).map(s => {
        const dx = s.to[0] - s.from[0], dy = s.to[1] - s.from[1], length = Math.hypot(dx, dy), nx = -dy / length * s.width / 2, ny = dx / length * s.width / 2;
        return [[s.from[0] + nx, s.from[1] + ny], [s.to[0] + nx, s.to[1] + ny], [s.to[0] - nx, s.to[1] - ny], [s.from[0] - nx, s.from[1] - ny]];
      });
      for (const poly of polys) {
        // Only insert stair holes fully contained in this footprint.
        const inside = p => { let v = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) if ((poly[i][1] > p[1]) !== (poly[j][1] > p[1]) && p[0] < (poly[j][0] - poly[i][0]) * (p[1] - poly[i][1]) / (poly[j][1] - poly[i][1]) + poly[i][0]) v = !v; return v; };
        const cuts = holes.filter(h => h.every(inside));
        mesh(local[l.id], polygon(poly, l.id === first.id ? 0 : l.elevation - 0.8, l.elevation - 0.02, cuts), mat(l.id === first.id ? 'patio_concrete' : 'interior_wall'));
        mesh(local[l.id], polygon(poly, l.elevation, l.elevation, cuts), mat('floor'));
      }
    }
    if (b.porch?.polygon) {
      const po = b.porch; use(po, 'porch', 'porch'); mesh(local[first.id], polygon(po.polygon, 0, po.floor), mat('patio_concrete'));
      const shed = b.roof?.extensions?.find(e => e.kind === 'shed_continuation');
      const section = sections.find(s => s.id === shed?.section);
      const main = section && { plate: section.plate, x1: section.rect[2] };
      for (const c of po.columns || []) {
        const top = main && shed ? main.plate - (c.at[0] - main.x1) * shed.pitch / 12 : first.elevation + first.ceiling;
        mesh(local[first.id], boxRect(c.at[0] - c.size / 2, c.at[1] - c.size / 2, c.at[0] + c.size / 2, c.at[1] + c.size / 2, po.floor, top), mat('trim'));
      }
      if (main && shed) {
        const xs = po.polygon.map(p => p[0]), ys = po.polygon.map(p => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
        // Beadboard is actual repeated strips under the porch pitch.
        const beadboard = materialKit.materials.porch_ceiling?.asset === 'beadboard';
        for (let y = y0; y < y1; y += beadboard ? 0.33 : y1 - y0) {
          const angle = -Math.atan(shed.pitch / 12), len = (x1 - x0) / Math.cos(angle);
          const width = Math.min(beadboard ? 0.31 : y1 - y0, y1 - y);
          mesh(local.roof, new THREE.BoxGeometry(len, 0.06, width).rotateZ(angle).translate((x0 + x1) / 2, main.plate - ((x0 + x1) / 2 - main.x1) * shed.pitch / 12 - 0.12, -y - width / 2), mat('porch_ceiling'));
        }
      }
    }
    for (const [index, s] of (b.stairs || []).entries()) {
      use(s, 'stair', `stair:${index}`);
      const l = levels[s.level] || first, dx = s.to[0] - s.from[0], dy = s.to[1] - s.from[1], length = Math.hypot(dx, dy), angle = Math.atan2(dy, dx);
      for (let i = 0; i < s.risers; i++) {
        const run = length / s.risers, height = (s.rise_to - l.elevation) * (i + 1) / s.risers;
        mesh(local[l.id], boxGeometry(run, height, s.width).rotateY(angle).translate(s.from[0] + dx * (i + 0.5) / s.risers, l.elevation + height / 2, -s.from[1] - dy * (i + 0.5) / s.risers), mat('floor'));
      }
    }
    for (const [index, f] of (b.fixtures || []).entries()) {
      use(f, 'fixture', `fixture:${index}`);
      const l = levels[f.level]; if (!l || !f.rect) continue;
      const g = local[l.id], [x0, y0, x1, y1] = f.rect, z = l.elevation + (f.z0 || 0), h = f.height || 1;
      const box = (a, c, d, e, lo, hi, m) => mesh(g, boxRect(a, c, d, e, lo, hi), m);
      if (['counter', 'vanity'].includes(f.kind)) {
        box(x0, y0, x1, y1, z, z + h - 0.12, plain('cabinet', f.body || '#3a4a52'));
        box(x0 - 0.05, y0 - 0.05, x1 + 0.05, y1 + 0.05, z + h - 0.12, z + h, f.top ? plain('counter', f.top) : mat('counter'));
      } else if (f.kind === 'shower') {
        box(x0, y0, x1, y1, z, z + 0.2, plain('ceramic', '#f4f4f2'));
        box(x0, y0, x1, y0 + 0.04, z + 0.2, z + h, glass);
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
    }
    for (const [index, l] of (b.lights || []).entries()) {
      use(l, 'light', `light:${index}`);
      const level = levels[l.level] || first;
      const y = l.room === 'Porch' ? level.elevation + level.ceiling - 2 : Math.min(level.elevation + level.ceiling - 0.25, roofHeight(...l.at) - 0.5);
      const size = l.kind === 'recessed' ? 0.6 : 1.4;
      const light = new THREE.RectAreaLight('#ffc98a', l.kind === 'recessed' ? 9 : 6, size, size);
      light.position.set(l.at[0], y, -l.at[1]); light.lookAt(l.at[0], y - 1, -l.at[1]);
      light.userData.level = levelKey(l.level); light.userData.elevation = base + level.elevation; light.visible = false;
      local.lights.add(light); roomLights.push(light);
      mesh(local[level.id], boxRect(l.at[0] - size / 2, l.at[1] - size / 2, l.at[0] + size / 2, l.at[1] + size / 2, y, y + 0.05), fixture);
    }
    // Proxies retain identity after settled render meshes are merged. Their
    // layer is never enabled on a rendering camera (including shadow cameras).
    for (const [key, { data, group, box }] of records) {
      if (box.isEmpty()) continue;
      pieceBounds.set(key, { box: box.clone(), group, data });
      const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
      const wall = b.walls.find(w => w.id === data.pieceId);
      let geometry;
      if (wall) {
        const basis = wallBasis(wall.from, wall.to, box.min.y);
        geometry = boxGeometry(basis.length, size.y, wall.thickness + 0.2).translate(basis.length / 2, size.y / 2, 0).applyMatrix4(basis.matrix);
      } else if (data.kind === 'roof') {
        const index = sections.findIndex((s, i) => (s.id || `roof:${i}`) === data.pieceId), positions = [];
        for (let t = 0; t < roofLayers.section.length; t++) if (roofLayers.section[t] === index) positions.push(...roofLayers.positions.slice(t * 9, t * 9 + 9));
        geometry = roofGeometry(positions);
      } else geometry = boxGeometry(Math.max(0.01, size.x), Math.max(0.01, size.y), Math.max(0.01, size.z)).translate(...center.toArray());
      const proxy = new THREE.Mesh(geometry, pickMaterial);
      Object.assign(proxy.userData, data); proxy.layers.set(PICK_LAYER);
      group.add(proxy); pickObjects.set(key, proxy);
    }
    for (const [key, { data }] of records) if (data.ghost) ghostBatches.push(batchGhost(root, pieces.get(key), ghost, ghostEdges));
  }
  // Merge within independently switchable domains, never across a floor cut.
  for (const g of mergeGroups) mergeStatic(g);
  groups.gableCut.visible = false;
  const updateGhosts = () => ghostBatches.forEach(update => update());
  updateGhosts();
  // The view's supplementary room meshes still use the plan's floor role.
  if (plan.buildings?.length && !materials.has('floor')) materials.set('floor', kitMaterial('floor', materialKitFor(plan.materials), tier));
  const ready = Promise.all([...materials.values()].map(m => m.userData.ready));
  // These two shared materials may have no objects in a settled-only plan.
  materials.set('ghostEdges', ghostEdges); materials.set('pick', pickMaterial);
  return { root, groups, pieces, pieceBounds, pickObjects, roofSurfaces, roomLights, levelElevations, materials, ready, updateGhosts, notes };
}
