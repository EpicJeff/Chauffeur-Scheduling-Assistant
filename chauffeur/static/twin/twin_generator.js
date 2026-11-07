// Schema 1 -> geometry. Plan x/y map to world X/-Z; heights are world Y.
// All geometry is in plan feet; only the returned root converts to metres.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { kitMaterial } from './twin_library.js';

export const FT = 0.3048;
export function mergeStatic(group) {
  group.updateMatrixWorld(true);
  const inverse = group.matrixWorld.clone().invert(), buckets = new Map();
  group.traverse(o => {
    if (!o.isMesh || o.isInstancedMesh || o.isSkinnedMesh || Array.isArray(o.material) ||
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

export function buildTwin(plan, kit, tier) {
  const root = new THREE.Group(); root.scale.setScalar(FT);
  const groups = { site: new THREE.Group(), roof: new THREE.Group(), gableFull: new THREE.Group(), gableCut: new THREE.Group(), lights: new THREE.Group(), levels: {} };
  for (const [id, group] of Object.entries(groups)) if (group.isGroup) { group.name = id; root.add(group); }
  const materialKit = { ...kit, materials: { ...kit.materials } };
  for (const [role, ref] of Object.entries(plan.materials || {})) {
    const known = kit.manifest || window.twinManifest || {};
    // Old normalized plans can carry semantic ids (wood_plank, mahogany).
    // Resolve those through the role in the kit; actual asset ids win.
    materialKit.materials[role] = { ...kit.materials?.[role], color: ref.color || kit.materials?.[role]?.color,
      asset: known[ref.id] ? ref.id : kit.materials?.[role]?.asset };
  }
  const materials = new Map();
  const mat = role => {
    if (!materials.has(role)) materials.set(role, kitMaterial(role, materialKit, tier));
    return materials.get(role);
  };
  const plain = (name, color, extra = {}) => {
    const key = name + color;
    if (!materials.has(key)) materials.set(key, new THREE.MeshStandardMaterial({ name, color, roughness: 0.8, ...extra }));
    return materials.get(key);
  };
  const glass = plain('glass', '#b9d7db', { transparent: true, opacity: 0.26, roughness: 0.1, depthWrite: false });
  const fixture = plain('fixture', '#fff4e0', { emissive: '#ffd59a', emissiveIntensity: 0 });
  const roomLights = [], levelElevations = {};
  for (const b of plan.buildings || []) {
    const levels = Object.fromEntries(b.levels.map(l => [l.id, l]));
    const ordered = [...b.levels].sort((a, c) => a.elevation - c.elevation), first = ordered[0];
    const local = {};
    const position = b.position || [0, 0];
    // Local containers preserve a building's translation before the final merge.
    for (const id of ['roof', 'gableFull', 'gableCut', 'lights', ...b.levels.map(l => l.id)]) {
      if (levels[id] && !groups.levels[id]) {
        groups.levels[id] = new THREE.Group(); groups.levels[id].name = id; root.add(groups.levels[id]);
      }
      const g = local[id] = new THREE.Group(); g.position.set(position[0], 0, -position[1]);
      (groups[id] || groups.levels[id]).add(g);
    }
    ordered.forEach(l => { levelElevations[l.id] = l.elevation; });
    const main = b.roof?.main;
    const center = b.walls.length ? b.walls.reduce((a, w) => [a[0] + w.from[0] / b.walls.length, a[1] + w.from[1] / b.walls.length], [0, 0]) : [0, 0];
    const roofHeight = x => main ? main.plate + Math.max(0, (main.x1 - main.x0) / 2 - Math.abs(x - (main.x0 + main.x1) / 2)) * main.pitch / 12 : Infinity;
    function wall(group, from, to, elevation, thickness, top, holes, exterior, role = null) {
      const { matrix, length, z } = wallBasis(from, to, elevation);
      if (!length) return;
      const samples = Array.from({ length: 17 }, (_, i) => length * i / 16);
      // Partition the surface at opening edges. This treats doors touching the
      // floor as notches (not invalid polygon holes), and clips all upper pieces
      // under the sampled roof, including gable windows near a slope.
      const cuts = [...new Set([0, length, ...samples, ...holes.flatMap(h => [Math.max(0, h.u0), Math.min(length, h.u1)])])].sort((a, c) => a - c);
      const wallMat = role ? mat(role) : mat(exterior ? 'siding' : 'interior_wall');
      for (let i = 0; i < cuts.length - 1; i++) {
        const a = cuts[i], c = cuts[i + 1], mid = (a + c) / 2;
        if (c - a < 0.0001) continue;
        let intervals = [[0, Infinity]];
        holes.filter(h => mid > h.u0 && mid < h.u1).forEach(h => {
          intervals = intervals.flatMap(([lo, hi]) => [[lo, Math.min(hi, h.v0)], [Math.max(lo, h.v1), hi]].filter(([p, q]) => q > p));
        });
        for (const [lo, hi] of intervals) {
          const ta = Math.min(hi, top(a)), tc = Math.min(hi, top(c));
          if (ta <= lo && tc <= lo) continue;
          const shape = new THREE.Shape([[a, lo], [c, lo], [c, Math.max(lo, tc)], [a, Math.max(lo, ta)]].map(p => new THREE.Vector2(...p)));
          const geo = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false, steps: 1 });
          geo.translate(0, 0, -thickness / 2).applyMatrix4(matrix);
          addMesh(group, geo, wallMat);
        }
      }
      const sign = Math.sign(z.dot(new THREE.Vector3((from[0] + to[0]) / 2 - center[0], 0, -(from[1] + to[1]) / 2 + center[1]))) || 1;
      const localBox = (u, v, w, h, d, material, offset = 0) => addMesh(group, boxGeometry(w, h, d).translate(u, v, offset).applyMatrix4(matrix), material);
      if (exterior && materialKit.materials.siding?.asset === 'board_and_batten' && !role) {
        for (let u = 0.5; u < length; u += 1) {
          let intervals = [[0, top(u)]];
          holes.filter(h => u > h.u0 - 0.4 && u < h.u1 + 0.4).forEach(h => {
            intervals = intervals.flatMap(([a, c]) => [[a, Math.min(c, h.v0 - 0.35)], [Math.max(a, h.v1 + 0.35), c]].filter(([a, c]) => c - a > 0.1));
          });
          intervals.forEach(([a, c]) => localBox(u, (a + c) / 2, 0.14, c - a, 0.09, wallMat, sign * (thickness / 2 + 0.045)));
        }
      }
      for (const h of holes) {
        if (h.kind === 'passage') continue;
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
    }
    const opening = (o, at = o.at) => ({ ...o, u0: at - o.width / 2, u1: at + o.width / 2, v0: o.sill, v1: o.head });
    for (const w of b.walls) {
      const l = levels[w.level]; if (!l) continue;
      const length = Math.hypot(w.to[0] - w.from[0], w.to[1] - w.from[1]);
      const top = u => Math.min(w.height, w.level === first.id ? Infinity : roofHeight(w.from[0] + (w.to[0] - w.from[0]) * u / length) - l.elevation - 0.08);
      wall(local[w.level], w.from, w.to, l.elevation, w.thickness, top, (b.openings || []).filter(o => o.wall === w.id).map(o => opening(o)), w.exterior);
      if (w.exterior && l.elevation > 0 && w.level === first.id) wall(local[w.level], w.from, w.to, 0, w.thickness + 0.12, () => l.elevation, [], false, 'base');
    }
    if (main) {
      const span = main.x1 - main.x0, half = span / 2, rise = half * main.pitch / 12;
      for (const end of ['front', 'rear']) {
        const front = end === 'front', y = front ? main.y0 : main.y1;
        const from = [front ? main.x0 : main.x1, y], to = [front ? main.x1 : main.x0, y];
        const holes = (b.openings || []).filter(o => o.gable === end).map(o => opening(o, front ? o.x - main.x0 : main.x1 - o.x));
        const top = u => Math.max(0.01, rise * (1 - Math.abs(u - half) / half));
        wall(local.gableFull, from, to, main.plate, 0.5, top, holes, true);
        wall(local.gableCut, from, to, main.plate, 0.5, u => Math.min(8, top(u)), holes.filter(o => o.v1 <= 8), true);
        addMesh(local[first.id], boxRect(main.x0 - 0.35, y - 0.35, main.x1 + 0.35, y + 0.35, main.plate - 0.65, main.plate), mat('trim'));
      }
      for (const x of [main.x0, main.x1]) for (const y of [main.y0, main.y1]) addMesh(local[first.id], boxRect(x - 0.3, y - 0.3, x + 0.3, y + 0.3, first.elevation, main.plate - 0.65), mat('trim'));
      const extensions = b.roof.extensions || [], shed = extensions.find(e => e.kind === 'shed_continuation');
      function roofPlane(a, c, y0, y1) {
        const angle = Math.atan2(c[1] - a[1], c[0] - a[0]), length = Math.hypot(c[0] - a[0], c[1] - a[1]);
        const at = (g, offset = 0) => g.rotateZ(angle).translate((a[0] + c[0]) / 2 - Math.sin(angle) * offset, (a[1] + c[1]) / 2 + Math.cos(angle) * offset, -(y0 + y1) / 2);
        addMesh(local.roof, at(new THREE.BoxGeometry(length, 0.4, y1 - y0), 0.2), mat('roof'));
        if (materialKit.materials.roof?.asset === 'standing_seam') for (let y = y0 + 0.75; y < y1; y += 1.5) {
          const g = at(new THREE.BoxGeometry(length, 0.08, 0.065), 0.44); g.translate(0, 0, -y + (y0 + y1) / 2); addMesh(local.roof, g, mat('roof'));
        }
        for (const y of [y0, y1]) {
          const g = at(new THREE.BoxGeometry(length, 0.65, 0.14)); g.translate(0, 0, -y + (y0 + y1) / 2); addMesh(local.roof, g, mat('trim'));
        }
      }
      const oh = main.overhang || 0, p = main.pitch / 12, ridge = [(main.x0 + main.x1) / 2, main.plate + rise];
      roofPlane([main.x0 - oh, main.plate - oh * p], ridge, main.y0 - oh, main.y1 + oh);
      roofPlane(ridge, [main.x1 + (shed ? 0 : oh), main.plate - (shed ? 0 : oh * p)], main.y0 - oh, main.y1 + oh);
      if (shed) roofPlane([main.x1, main.plate], [shed.to_x + (shed.overhang || 0), main.plate - (shed.to_x + (shed.overhang || 0) - main.x1) * shed.pitch / 12], main.y0 - oh, main.y1 + oh);
      for (const aw of extensions.filter(e => e.kind === 'awning')) {
        const rise = aw.depth * aw.pitch / 12, angle = -Math.atan2(rise, aw.depth), length = Math.hypot(aw.depth, rise);
        const g = new THREE.BoxGeometry(aw.x1 - aw.x0, 0.3, length).rotateX(angle).translate((aw.x0 + aw.x1) / 2, aw.eave + rise / 2, -main.y0 + aw.depth / 2);
        addMesh(local.roof, g, mat('roof'));
        for (let x = aw.x0 + 0.75; x < aw.x1; x += 1.5) if (materialKit.materials.roof?.asset === 'standing_seam') addMesh(local.roof, new THREE.BoxGeometry(0.065, 0.08, length).rotateX(angle).translate(x, aw.eave + rise / 2 + 0.2, -main.y0 + aw.depth / 2), mat('roof'));
        for (let i = 0; i < (aw.brackets || 0); i++) addMesh(local[first.id], new THREE.BoxGeometry(0.3, 0.3, Math.hypot(3, 2.6)).rotateX(-Math.atan2(2.6, 3)).translate(aw.x0 + 0.6 + i * (aw.x1 - aw.x0 - 1.2) / Math.max(1, aw.brackets - 1), aw.eave - 1.4, -main.y0 + 1.6), mat('trim'));
      }
    }
    const outlines = footprints(b.walls.filter(w => w.level === first.id));
    for (const l of ordered) {
      const polys = outlines.length ? outlines : (b.rooms || []).filter(r => r.level === l.id).map(r => r.polygon);
      const holes = (b.stairs || []).filter(s => s.rise_to >= l.elevation && l.elevation > first.elevation).map(s => {
        const dx = s.to[0] - s.from[0], dy = s.to[1] - s.from[1], length = Math.hypot(dx, dy), nx = -dy / length * s.width / 2, ny = dx / length * s.width / 2;
        return [[s.from[0] + nx, s.from[1] + ny], [s.to[0] + nx, s.to[1] + ny], [s.to[0] - nx, s.to[1] - ny], [s.from[0] - nx, s.from[1] - ny]];
      });
      for (const poly of polys) {
        // Only insert stair holes fully contained in this footprint.
        const inside = p => { let v = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) if ((poly[i][1] > p[1]) !== (poly[j][1] > p[1]) && p[0] < (poly[j][0] - poly[i][0]) * (p[1] - poly[i][1]) / (poly[j][1] - poly[i][1]) + poly[i][0]) v = !v; return v; };
        const cuts = holes.filter(h => h.every(inside));
        addMesh(local[l.id], polygon(poly, l.id === first.id ? 0 : l.elevation - 0.8, l.elevation - 0.02, cuts), mat(l.id === first.id ? 'patio_concrete' : 'interior_wall'));
        addMesh(local[l.id], polygon(poly, l.elevation, l.elevation, cuts), mat('floor'));
      }
    }
    if (b.porch?.polygon) {
      const po = b.porch; addMesh(local[first.id], polygon(po.polygon, 0, po.floor), mat('patio_concrete'));
      const shed = b.roof?.extensions?.find(e => e.kind === 'shed_continuation');
      for (const c of po.columns || []) {
        const top = main && shed ? main.plate - (c.at[0] - main.x1) * shed.pitch / 12 : first.elevation + first.ceiling;
        addMesh(local[first.id], boxRect(c.at[0] - c.size / 2, c.at[1] - c.size / 2, c.at[0] + c.size / 2, c.at[1] + c.size / 2, po.floor, top), mat('trim'));
      }
      if (main && shed) {
        const xs = po.polygon.map(p => p[0]), ys = po.polygon.map(p => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
        // Beadboard is actual repeated strips under the porch pitch.
        const beadboard = materialKit.materials.porch_ceiling?.asset === 'beadboard';
        for (let y = y0; y < y1; y += beadboard ? 0.33 : y1 - y0) {
          const angle = -Math.atan(shed.pitch / 12), len = (x1 - x0) / Math.cos(angle);
          const width = Math.min(beadboard ? 0.31 : y1 - y0, y1 - y);
          addMesh(local.roof, new THREE.BoxGeometry(len, 0.06, width).rotateZ(angle).translate((x0 + x1) / 2, main.plate - ((x0 + x1) / 2 - main.x1) * shed.pitch / 12 - 0.12, -y - width / 2), mat('porch_ceiling'));
        }
      }
    }
    for (const s of b.stairs || []) {
      const l = levels[s.level] || first, dx = s.to[0] - s.from[0], dy = s.to[1] - s.from[1], length = Math.hypot(dx, dy), angle = Math.atan2(dy, dx);
      for (let i = 0; i < s.risers; i++) {
        const run = length / s.risers, height = (s.rise_to - l.elevation) * (i + 1) / s.risers;
        addMesh(local[l.id], boxGeometry(run, height, s.width).rotateY(angle).translate(s.from[0] + dx * (i + 0.5) / s.risers, l.elevation + height / 2, -s.from[1] - dy * (i + 0.5) / s.risers), mat('floor'));
      }
    }
    for (const f of b.fixtures || []) {
      const l = levels[f.level]; if (!l || !f.rect) continue;
      const g = local[l.id], [x0, y0, x1, y1] = f.rect, z = l.elevation + (f.z0 || 0), h = f.height || 1;
      const box = (a, c, d, e, lo, hi, m) => addMesh(g, boxRect(a, c, d, e, lo, hi), m);
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
    for (const l of b.lights || []) {
      const level = levels[l.level] || first;
      const y = l.room === 'Porch' ? level.elevation + level.ceiling - 2 : Math.min(level.elevation + level.ceiling - 0.25, roofHeight(l.at[0]) - 0.5);
      const size = l.kind === 'recessed' ? 0.6 : 1.4;
      const light = new THREE.RectAreaLight('#ffc98a', l.kind === 'recessed' ? 9 : 6, size, size);
      light.position.set(l.at[0], y, -l.at[1]); light.lookAt(l.at[0], y - 1, -l.at[1]);
      light.userData.level = l.level; light.userData.elevation = level.elevation; light.visible = false;
      local.lights.add(light); roomLights.push(light);
      addMesh(local[level.id], boxRect(l.at[0] - size / 2, l.at[1] - size / 2, l.at[0] + size / 2, l.at[1] + size / 2, y, y + 0.05), fixture);
    }
  }
  // Merge within independently switchable domains, never across a floor cut.
  for (const g of [groups.roof, groups.gableFull, groups.gableCut, ...Object.values(groups.levels)]) mergeStatic(g);
  groups.gableCut.visible = false;
  const ready = Promise.all([...materials.values()].map(m => m.userData.ready));
  return { root, groups, roomLights, levelElevations, materials, ready };
}
