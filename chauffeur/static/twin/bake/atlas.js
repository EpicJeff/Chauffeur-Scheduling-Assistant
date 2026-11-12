// Geometry/UV density use plan feet; reach queries use world metres.
import * as THREE from '../../vendor/three-r187/three.module.js';
import { reachLights } from './reach.js';
import { fingerprint } from './fingerprint.js';
export { fingerprint } from './fingerprint.js';

const VERSION = 'reach-atlas-6';
const EPS = 1e-6;
const prepared = new WeakMap();
const bankPacking = new WeakMap();
const atlasAttributes = new Set(['uv2', 'uv3', 'lmRoom', 'lmSkyPage', 'lmLightPage']);
const defaults = { room: { density: 4, page: 2048, gutter: 2 } };

function options(input, kind) {
  const o = { ...defaults[kind], ...input };
  if (!(Number.isFinite(o.density) && o.density > 0 && Number.isInteger(o.page) && o.page > 0 &&
    Number.isInteger(o.gutter) && o.gutter >= 0)) throw new Error('Invalid atlas parameters');
  return o;
}

function inside(poly, x, y) {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if ((a[1] > y) !== (b[1] > y) && x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])) hit = !hit;
  }
  return hit;
}

function cross2(a, b, c) {
  return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function convexParts(poly) {
  if (poly.every((p, i) => cross2(p, poly[(i + 1) % poly.length], poly[(i + 2) % poly.length]) >= -EPS)) return [poly];
  const parts = THREE.ShapeUtils.triangulateShape(poly.map(p => new THREE.Vector2(...p)), []).map(t => t.map(i => poly[i]));
  // Remove triangulation diagonals wherever their union is convex. Otherwise a
  // clipped triangle acquires needless vertices along these internal diagonals.
  let changed = true;
  while (changed) {
    changed = false;
    outer: for (let i = 0; i < parts.length; i++) for (let j = i + 1; j < parts.length; j++) {
      const a = parts[i], b = parts[j];
      for (let e = 0; e < a.length; e++) for (let f = 0; f < b.length; f++) {
        if (a[e] !== b[(f + 1) % b.length] || a[(e + 1) % a.length] !== b[f]) continue;
        const joined = Array.from({ length: a.length }, (_, k) => a[(e + 1 + k) % a.length])
          .concat(Array.from({ length: b.length - 2 }, (_, k) => b[(f + 2 + k) % b.length]));
        if (!joined.every((p, k) => cross2(p, joined[(k + 1) % joined.length], joined[(k + 2) % joined.length]) >= -EPS)) continue;
        parts[i] = joined; parts.splice(j, 1); changed = true; break outer;
      }
    }
  }
  return parts;
}

function roomData(plan) {
  const rooms = [], buildings = new Map();
  for (const b of plan.buildings || []) {
    const levels = [...(b.levels || [])].sort((a, c) => a.elevation - c.elevation);
    const list = [];
    for (const r of b.rooms || []) {
      if (r.polygon?.length < 3 || !r.polygon) continue;
      let poly = r.polygon.map(p => [...p]);
      if (poly.length > 3 && poly[0][0] === poly.at(-1)[0] && poly[0][1] === poly.at(-1)[1]) poly.pop();
      let area = 0;
      for (let i = 0; i < poly.length; i++) area += cross2([0, 0], poly[i], poly[(i + 1) % poly.length]);
      if (area < 0) poly.reverse();
      const parts = convexParts(poly);
      const entry = { index: rooms.length, level: r.level, poly, parts,
        bounds: [Math.min(...poly.map(p => p[0])), Math.min(...poly.map(p => p[1])),
          Math.max(...poly.map(p => p[0])), Math.max(...poly.map(p => p[1]))] };
      list.push(entry);
      rooms.push({ building: b.id, level: r.level, id: r.id, region: null });
    }
    buildings.set(b.id, { levels, rooms: list });
  }
  return { rooms, buildings };
}

// Cut a convex polygon into its intersection with a convex room part and its
// disjoint exterior pieces. Retaining the exterior preserves render geometry.
function cut(poly, boundary, minHeight = -Infinity) {
  let rest = poly;
  const outside = [];
  for (let e = 0; e <= boundary.length && rest.length >= 3; e++) {
    if (e === boundary.length && minHeight === -Infinity) break;
    const a = boundary[e], b = boundary[(e + 1) % boundary.length];
    const distance = e === boundary.length ? v => v[1] - minHeight : v => cross2(a, b, [v[0], -v[2]]);
    const positive = [], negative = [];
    for (let i = 0; i < rest.length; i++) {
      const p = rest[i], q = rest[(i + 1) % rest.length];
      const dp = distance(p), dq = distance(q);
      if (dp >= -EPS) positive.push(p);
      if (dp <= EPS) negative.push(p);
      if (dp > EPS && dq < -EPS || dp < -EPS && dq > EPS) {
        const t = dp / (dp - dq), v = p.map((x, k) => x + t * (q[k] - x));
        positive.push(v); negative.push(v);
      }
    }
    if (negative.length >= 3 && rest.some(p => distance(p) < -EPS)) outside.push(negative);
    rest = positive;
  }
  return { inside: rest, outside };
}

function faceNormal(a, b, c) {
  return new THREE.Vector3(b[0] - a[0], b[1] - a[1], b[2] - a[2])
    .cross(new THREE.Vector3(c[0] - a[0], c[1] - a[1], c[2] - a[2]));
}

function hasArea(poly) {
  return poly.length >= 3 && poly.slice(1, -1).some((v, i) => faceNormal(poly[0], v, poly[i + 2]).length() > 2e-9);
}

function projectedArea(poly) {
  let a = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i], q = poly[(i + 1) % poly.length];
    a += p[0] * q[2] - p[2] * q[0];
  }
  return Math.abs(a) / 2;
}

function joinPieces(pieces, normal) {
  const hull = points => {
    const sorted = [...points].sort((a, b) => a[0] - b[0] || a[2] - b[2]);
    const half = list => {
      const h = [];
      for (const p of list) {
        while (h.length > 1 && cross2([h.at(-2)[0], h.at(-2)[2]], [h.at(-1)[0], h.at(-1)[2]], [p[0], p[2]]) <= 1e-10) h.pop();
        h.push(p);
      }
      return h.slice(0, -1);
    };
    const result = half(sorted).concat(half([...sorted].reverse()));
    if (result.length >= 3 && faceNormal(result[0], result[1], result[2]).dot(normal) < 0) result.reverse();
    return result;
  };
  let changed = true;
  while (changed) {
    changed = false;
    outer: for (let i = 0; i < pieces.length; i++) for (let j = i + 1; j < pieces.length; j++) {
      const union = hull([...pieces[i], ...pieces[j]]);
      const area = projectedArea(pieces[i]) + projectedArea(pieces[j]);
      if (Math.abs(projectedArea(union) - area) > 1e-8 * Math.max(1, area)) continue;
      pieces[i] = union; pieces.splice(j, 1); changed = true; break outer;
    }
  }
  return pieces;
}

function prepare(mesh, data) {
  const old = mesh.geometry;
  if (prepared.has(old)) return prepared.get(old);
  let building;
  for (let p = mesh; p && !building; p = p.parent) building = data.buildings.get(p.userData.buildingId);
  const names = Object.keys(old.attributes).filter(n => !atlasAttributes.has(n));
  names.splice(names.indexOf('position'), 1); names.unshift('position');
  const attrs = names.map(n => old.attributes[n]), offsets = [];
  let stride = 0;
  for (const a of attrs) { offsets.push(stride); stride += a.itemSize; }
  let capacity=old.index?.count ?? old.attributes.position.count, written=0;
  const buffers = attrs.map(a => new Float32Array(capacity*a.itemSize)), owners = [];
  const read = i => {
    const v=new Array(stride);
    for (let j=0;j<attrs.length;j++) for (let k=0;k<attrs[j].itemSize;k++) v[offsets[j]+k]=attrs[j].getComponent(i,k);
    return v;
  };
  const emitTriangle = (poly, room) => {
    poly = [...poly];
    for (let i = 0; i < poly.length && poly.length > 3;) {
      const a = poly[(i + poly.length - 1) % poly.length], b = poly[i], c = poly[(i + 1) % poly.length];
      const span = Math.hypot(c[0] - a[0], c[1] - a[1], c[2] - a[2]);
      if (faceNormal(a, b, c).length() <= 1e-9 * span) { poly.splice(i, 1); i = 0; }
      else i++;
    }
    for (let i = 1; i + 1 < poly.length; i++) {
      const tri = [poly[0], poly[i], poly[i + 1]];
      if (faceNormal(...tri).length() / 2 < 1e-10) continue;
      if (written+3>capacity) {
        capacity=Math.max(written+3,Math.ceil(capacity*1.5));
        attrs.forEach((a,j)=>{const next=new Float32Array(capacity*a.itemSize);next.set(buffers[j]);buffers[j]=next;});
      }
      for (const v of tri) {
        attrs.forEach((a,j)=>{for (let k=0;k<a.itemSize;k++) buffers[j][written*a.itemSize+k]=v[offsets[j]+k];});
        written++;
      }
      owners.push(room);
    }
  };
  const emit = (poly, room) => {
    if (room >= 0) return emitTriangle(poly, room);
    // Vertical wall and trim triangles are already small. Cutting them at
    // every yard grid line inflates the house's render buffers unnecessarily.
    if (Math.abs(faceNormal(poly[0], poly[1], poly[2]).normalize().y) < .1) return emitTriangle(poly, room);
    // Small exterior tiles keep a nearby lamp from reserving the entire yard.
    const xs = poly.map(p => p[0]), ys = poly.map(p => -p[2]), tile = 64;
    if (Math.max(...xs) - Math.min(...xs) <= tile && Math.max(...ys) - Math.min(...ys) <= tile)
      return emitTriangle(poly, room);
    const x0 = Math.floor(Math.min(...xs) / tile), x1 = Math.max(x0, Math.ceil(Math.max(...xs) / tile) - 1);
    const y0 = Math.floor(Math.min(...ys) / tile), y1 = Math.max(y0, Math.ceil(Math.max(...ys) / tile) - 1);
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) {
      const a = x * tile, b = y * tile;
      const piece = cut(poly, [[a,b], [a+tile,b], [a+tile,b+tile], [a,b+tile]]).inside;
      if (hasArea(piece)) emitTriangle(piece, room);
    }
  };
  const count = (old.index?.count ?? old.attributes.position.count) / 3;
  for (let f = 0; f < count; f++) {
    const tri = [0, 1, 2].map(k => read(old.index ? old.index.getX(f * 3 + k) : f * 3 + k));
    const n = faceNormal(...tri).normalize();
    const center = [0, 1, 2].map(k => (tri[0][k] + tri[1][k] + tri[2][k]) / 3);
    const role = mesh.material.name;
    if (!building || role === 'roof' || role === 'base') { emit(tri, -1); continue; }
    // Downward faces use the highest occupied room below each clipped piece,
    // even when a slab was batched in L2 or a soffit in the roof group.
    let level;
    for (const l of building.levels) if (l.elevation <= center[1] + 0.05) level = l;
    const candidates = n.y < -0.1 ? [...building.levels].reverse().flatMap(l =>
      Math.max(...tri.map(p => p[1])) > l.elevation + 0.05
        ? building.rooms.filter(r => r.level === l.id) : []) : building.rooms.filter(r => r.level === level?.id);
    if (Math.abs(n.y) < 0.1) {
      const x = center[0] + n.x * 0.04, y = -center[2] - n.z * 0.04;
      emit(tri, candidates.find(r => inside(r.poly, x, y))?.index ?? -1);
      continue;
    }
    let pending = [tri];
    for (const r of candidates) {
      const next = [];
      for (const poly of pending) {
        const xs = poly.map(v => v[0]), ys = poly.map(v => -v[2]), b = r.bounds;
        if (Math.max(...xs) <= b[0] + EPS || Math.min(...xs) >= b[2] - EPS ||
            Math.max(...ys) <= b[1] + EPS || Math.min(...ys) >= b[3] - EPS) { next.push(poly); continue; }
        let remainder = [poly];
        const hits = [];
        for (const part of r.parts) {
          const out = [];
          for (const piece of remainder) {
            const elevation = building.levels.find(l => l.id === r.level)?.elevation ?? 0;
            const split = cut(piece, part, n.y < -0.1 ? elevation + 0.05 : -Infinity);
            if (hasArea(split.inside)) hits.push(split.inside);
            out.push(...split.outside.filter(hasArea));
          }
          remainder = out;
        }
        // Ear triangulation is only a clipping aid, never a reason to split a
        // triangle that was already wholly inside the original concave room.
        if (!hits.length) next.push(poly);
        else if (!remainder.length) emit(poly, r.index);
        else { joinPieces(hits, n).forEach(p => emit(p, r.index)); next.push(...joinPieces(remainder, n)); }
      }
      pending = next;
    }
    pending.forEach(p => emit(p, -1));
  }
  const geometry = new THREE.BufferGeometry();
  names.forEach((name, i) => geometry.setAttribute(name, new THREE.BufferAttribute(buffers[i].slice(0,written*attrs[i].itemSize), attrs[i].itemSize)));
  geometry.name = old.name;
  geometry.userData = { ...old.userData };
  geometry.computeBoundingBox(); geometry.computeBoundingSphere();
  mesh.geometry = geometry;
  old.dispose();
  const state = { owners, room: null };
  prepared.set(geometry, state);
  return state;
}

function vertexKey(p) {
  return `${Math.round(p.x * 1e4)},${Math.round(p.y * 1e4)},${Math.round(p.z * 1e4)}`;
}

function chartsFor(mesh, owners) {
  const pos = mesh.geometry.attributes.position, faces = [], atVertex = new Map();
  const p = i => new THREE.Vector3().fromBufferAttribute(pos, i);
  for (let f = 0; f < pos.count / 3; f++) {
    const v = [p(3 * f), p(3 * f + 1), p(3 * f + 2)];
    const n = v[1].clone().sub(v[0]).cross(v[2].clone().sub(v[0]));
    if (n.length() / 2 < 1e-6) continue;
    n.normalize();
    const centre = v.reduce((a, p) => a.add(p), new THREE.Vector3()).multiplyScalar(1 / 3);
    const tile = `${Math.floor(centre.x / 64)},${Math.floor(-centre.z / 64)}`;
    const face = { f, v, n, keys: v.map(vertexKey), tile };
    faces[f] = face;
    for (const key of face.keys) {
      if (!atVertex.has(key)) atVertex.set(key, []);
      atVertex.get(key).push(f);
    }
  }
  const visited = new Uint8Array(faces.length), charts = [];
  for (const ref of faces) {
    if (!ref || visited[ref.f]) continue;
    const queue = [ref.f]; visited[ref.f] = 1;
    for (let q = 0; q < queue.length; q++) {
      const face = faces[queue[q]];
      for (const key of face.keys) for (const f of atVertex.get(key)) {
        if (visited[f] || owners[f] !== owners[ref.f]) continue;
        const other = faces[f];
        if (owners[f] < 0 && other.tile !== ref.tile) continue;
        // Tight planes avoid accumulating curvature in a flood-fill isometry.
        if (ref.n.dot(other.n) < 0.999999 || other.v.some(v => Math.abs(v.clone().sub(ref.v[0]).dot(ref.n)) > 1e-4)) continue;
        visited[f] = 1; queue.push(f);
      }
    }
    const axis = Math.abs(ref.n.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
    const u = axis.addScaledVector(ref.n, -axis.dot(ref.n)).normalize(), v = ref.n.clone().cross(u);
    let minU = Infinity, minV = Infinity, maxU = -Infinity, maxV = -Infinity;
    for (const f of queue) for (const point of faces[f].v) {
      const x = point.dot(u), y = point.dot(v);
      minU = Math.min(minU, x); maxU = Math.max(maxU, x); minV = Math.min(minV, y); maxV = Math.max(maxV, y);
    }
    charts.push({ mesh, faces: queue.sort((a, b) => a - b), room: owners[ref.f], tile: ref.tile, u, v, minU, minV,
      width: maxU - minU, height: maxV - minV });
  }
  return charts;
}

// First-fit decreasing shelves, deterministic even for equal rectangles. A later
// small chart can fill an earlier shelf's tail; empty pages are never allocated.
function shelves(items, width, height, gutter, ordered = null) {
  const pages = [];
  const sorted = ordered || [...items].sort((a, b) => b.h - a.h || b.w - a.w || a.id - b.id);
  // In a width trial heights descend, so every prior shelf is tall enough.
  // A max tree finds the first shelf with room in log(n), preserving first fit.
  const leaves=ordered && items.length>32 ? 2**Math.ceil(Math.log2(items.length)) : 0;
  const space=leaves ? new Float64Array(leaves*2) : null;
  for (const item of sorted) {
    if (item.w > width || item.h > height) throw new Error(`Atlas region exceeds page (${item.w} x ${item.h})`);
    let placed = false;
    for (let page = 0; page <= pages.length && !placed; page++) {
      // Base-room width trials only need to know whether one page suffices.
      if (ordered && page>0) return 2;
      if (page === pages.length) pages.push({ shelves: [], bottom: 0 });
      const p = pages[page];
      let shelf,slot=-1;
      if (space) {
        if (space[1]>=item.w) {
          let i=1;
          while (i<leaves) i=space[i*2]>=item.w ? i*2 : i*2+1;
          slot=i-leaves;shelf=p.shelves[slot];
        }
      } else for (const s of p.shelves) if (item.h<=s.h && s.x+item.w<=width) {shelf=s;break;}
      if (!shelf && p.bottom + item.h <= height) {
        shelf = { x: 0, y: p.bottom, h: item.h };slot=p.shelves.length; p.shelves.push(shelf); p.bottom += item.h + gutter;
      }
      if (shelf) {
        // Width trials own these rectangles; reuse them instead of allocating
        // millions of throwaway objects while choosing a room's base region.
        if (ordered && item.rect) Object.assign(item.rect,{ x:shelf.x,y:shelf.y,w:item.w,h:item.h });
        else item.rect = { x: shelf.x, y: shelf.y, w: item.w, h: item.h };
        item.page = page;
        shelf.x += item.w + gutter; placed = true;
        if (space) {
          let i=leaves+slot;space[i]=Math.max(0,width-shelf.x);
          while (i>1) {i=Math.floor(i/2);space[i]=Math.max(space[i*2],space[i*2+1]);}
        }
      }
    }
  }
  return pages.length;
}

function scaled(charts, o) {
  return charts.map((c, id) => {
    const density = c.outdoor ? Math.min(1, o.density, (o.page - 4) / Math.max(c.width, c.height)) : o.density;
    return { ...c, id, density, w: Math.max(1, Math.ceil(c.width * density)), h: Math.max(1, Math.ceil(c.height * density)) };
  });
}

function roomLayout(charts, rooms, o) {
  const regions = [];
  for (let room = 0; room < rooms.length; room++) {
    const mine = charts.filter(c => c.room === room);
    if (!mine.length) continue;
    // Try shelf widths; choosing a compact rectangle reduces whole-room waste
    // while keeping every room on one shared page and every chart unrotated.
    const ordered=[...mine].sort((a,b)=>b.h-a.h || b.w-a.w || a.id-b.id);
    const min = Math.max(...mine.map(c => c.w));
    let best = null;
    for (let width = min; width <= o.page; width += 16) {
      if (shelves(mine, width, o.page, o.gutter, ordered) !== 1) continue;
      let w=0,h=0;
      for (const c of mine) {w=Math.max(w,c.rect.x+c.w);h=Math.max(h,c.rect.y+c.h);}
      const score = w * h + 0.2 * (w * w + h * h);
      if (!best || score < best.score || score === best.score && w < best.w) {
        best = { w, h, score, rects: mine.map(c => ({ ...c.rect })) };
      }
    }
    if (!best) {
      if (shelves(mine, o.page, o.page, o.gutter, ordered) !== 1) throw new Error(`Room ${rooms[room].id} exceeds one atlas page`);
      best = { w: Math.max(...mine.map(c => c.rect.x + c.w)), h: Math.max(...mine.map(c => c.rect.y + c.h)),
        rects: mine.map(c => ({ ...c.rect })) };
    }
    mine.forEach((c, i) => { c.rect = best.rects[i]; });
    regions.push({ id: room, w: best.w, h: best.h, mine });
  }
  const pages = shelves(regions, o.page, o.page, o.gutter);
  for (const r of regions) {
    rooms[r.id].region = { page: r.page, ...r.rect };
    for (const c of r.mine) { c.page = r.page; c.rect.x += r.rect.x; c.rect.y += r.rect.y; }
  }
  return pages;
}

function writeUV(charts, o, name, pageName) {
  const buffers = new Map();
  for (const c of charts) {
    const g = c.mesh.geometry;
    if (!buffers.has(g)) buffers.set(g, { uv: new Float32Array(g.attributes.position.count * 2),
      page: new Float32Array(g.attributes.position.count).fill(-1) });
    const b = buffers.get(g), pos = g.attributes.position, point = new THREE.Vector3();
    for (const f of c.faces) for (let k = 0; k < 3; k++) {
      const i = f * 3 + k; point.fromBufferAttribute(pos, i);
      b.uv[i * 2] = (c.rect.x + (point.dot(c.u) - c.minU) * c.density) / o.page;
      b.uv[i * 2 + 1] = (c.rect.y + (point.dot(c.v) - c.minV) * c.density) / o.page;
      b.page[i] = c.page;
    }
  }
  for (const [g, b] of buffers) {
    g.setAttribute(name, new THREE.Float32BufferAttribute(b.uv, 2));
    g.setAttribute(pageName, new THREE.Float32BufferAttribute(b.page, 1));
  }
}

// A small streaming 128-bit fingerprint; no WebCrypto async boundary, UUIDs, or
// light records. Hashing generated buffers also captures generator changes.
// The surfaces a bake covers: merged, opaque, solid house and yard geometry.
// Cut-out cards (the Low tier's merged plant cards, alphaTest) are left out on
// every tier, so a Low panel builds the same atlas key as the desk that baked.
export function atlasMesh(mesh) {
  return !!(mesh.isMesh && mesh.userData.merged && !mesh.layers.isEnabled(31) && !Array.isArray(mesh.material) &&
    (!mesh.material.transparent || mesh.material.userData.viewingOpaque) && !(mesh.material.alphaTest > 0) && !['fixture', 'glass'].includes(mesh.material.name) &&
    mesh.geometry?.attributes.position);
}

export const CHANNEL_FALLBACK = Symbol('channel fallback');
export const CHART_STATS = Symbol('chart ranking statistics');
export function assignChannels(rooms, lights, previous = new Map()) {
  const byBuilding = new Map(), result = {};
  rooms.forEach((r, i) => {
    if (!byBuilding.has(r.building)) byBuilding.set(r.building, new Map());
    byBuilding.get(r.building).set(r.id, i);
  });
  const nodes = [];
  for (const light of lights) {
    const room = byBuilding.get(light.building)?.get(light.room);
    if (room === undefined || nodes.some(n => n.light.device === light.device)) continue;
    nodes.push({ light, room });
  }
  if (nodes.some(n => n.light.receivingCharts)) {
    const at = new Map();
    for (const n of nodes) {
      n.assignments=[];
      for (const chart of n.light.receivingCharts || []) {
        const d=n.light.distances?.[chart] ?? 0, range=n.light.range || 1;
        const attenuation=Math.max(0,1-(Math.sqrt(d)/range)**4)**2/Math.max(d,.01);
        const score=(n.light.intensity ?? 1)*(n.light.scores?.[chart] ?? attenuation);
        const key=n.light.chartKeys?.[chart] || String(chart);
        // Equal contributors share priority fairly across stable spatial charts,
        // rather than excluding the same coincident lamp everywhere.
        let tie=0x811c9dc5;
        for (const c of key+'|'+n.light.device) tie=Math.imul(tie^c.charCodeAt(0),0x01000193);
        tie=Math.imul(tie^(tie>>>16),0x85ebca6b);
        tie=Math.imul(tie^(tie>>>13),0xc2b2ae35);tie^=tie>>>16;
        if (!at.has(chart)) at.set(chart,[]);
        at.get(chart).push({n,score,tie:tie>>>0,key});
      }
    }
    const stats={worstDroppedFraction:0,worstChart:null,droppedCharts:0};
    for (const [chart, candidates] of at) {
      candidates.sort((a,b)=>b.score-a.score || a.tie-b.tie || a.n.light.device.localeCompare(b.n.light.device));
      const total=candidates.reduce((sum,c)=>sum+c.score,0), dropped=candidates.slice(6).reduce((sum,c)=>sum+c.score,0);
      const fraction=total ? dropped/total : 0;
      if (candidates.length>6) stats.droppedCharts++;
      if (fraction>stats.worstDroppedFraction) {stats.worstDroppedFraction=fraction;stats.worstChart=chart;}
      // Rank selects members only. Surviving members keep their old channels;
      // first-bake/new members take free slots in stable device-id order.
      const members=candidates.slice(0,6);
      members.forEach((c,rank)=>{c.rank=rank;});
      members.sort((a,b)=>a.n.light.device<b.n.light.device?-1:a.n.light.device>b.n.light.device?1:0);
      let used=0;const old=previous.get(chart);
      for(const c of members) {
        const slot=old?.get(c.n.light.device);
        if(Number.isInteger(slot)&&slot>=0&&slot<6&&!(used&(1<<slot))) {c.slot=slot;used|=1<<slot;}
      }
      for(const c of members) {
        if(c.slot===undefined) {let slot=0;while(used&(1<<slot))slot++;c.slot=slot;used|=1<<slot;}
        c.n.assignments.push({chart,chartKey:c.key,bank:Math.floor(c.slot/2),channel:c.slot%2,rank:c.rank,score:c.score});
      }
    }
    const fallback=[];
    for (const n of nodes) {
      if (!n.assignments.length) {fallback.push(n.light.device);continue;}
      n.assignments.sort((a,b)=>a.chart-b.chart);
      const first=n.assignments[0];
      Object.defineProperty(result,n.light.device,{enumerable:true,value:{room:n.room,bank:first.bank,channel:first.channel,
        receivers:n.light.receivers,receivingCharts:n.assignments.map(a=>a.chart),assignments:n.assignments}});
    }
    Object.defineProperty(result,CHANNEL_FALLBACK,{value:fallback.sort()});
    Object.defineProperty(result,CHART_STATS,{value:stats});
    return result;
  }
  // Legacy geometry-only callers have no positions/reach data.
  const counts=new Map();
  for (const n of nodes) {
    const slot=counts.get(n.room)||0;counts.set(n.room,slot+1);
    Object.defineProperty(result,n.light.device,{enumerable:true,value:{room:n.room,bank:Math.floor(slot/2),channel:slot%2}});
  }
  Object.defineProperty(result, CHANNEL_FALLBACK, { value: [] });
  return result;
}

export function packBanks(layout, lights, o, assigned) {
  lights=reachLights(layout,lights);
  const slots = Object.values(assigned || assignChannels(layout.rooms, lights)), banks = [];
  const physical=lights.some(l=>Array.isArray(l.receivingCharts));
  const count = physical ? 3 : slots.length ? 1 + Math.max(...slots.map(s => s.bank)) : 0;
  // Pack geometry once, independently of which lamps currently reach it.
  // Filtering before packing made a remote move relocate untouched texels.
  // Each bank still exposes only its owned charts, and the runtime holds only
  // pages a placed light uses; unlit geometry reserves addresses, not GPU layers.
  let compact=[],compactPages=0;
  if (physical) {
    if (!bankPacking.has(layout)) bankPacking.set(layout,new Map());
    const cache=bankPacking.get(layout),key=JSON.stringify([o.page,o.gutter]);
    if (!cache.has(key)) {
      const charts=layout.charts.map(c=>({...c,w:c.rect.w,h:c.rect.h,sourceRegion:{page:c.page,...c.rect}}));
      // Nearly full-page outdoor charts go last, on their own pages. A distant
      // unlit surface must not push every ordinary receiving chart to a new page.
      const islands=charts.filter(c=>c.w+2*o.gutter>=o.page && c.h+2*o.gutter>=o.page),large=new Set(islands);
      let pages=shelves(charts.filter(c=>!large.has(c)),o.page,o.page,o.gutter);
      for (const c of islands) {c.page=pages++;c.rect={x:0,y:0,w:c.w,h:c.h};}
      cache.set(key,{charts,pages});
    }
    ({charts:compact,pages:compactPages}=cache.get(key));
  }
  const used=new Set(slots.flatMap(s=>s.receivingCharts || []));
  const extent=physical ? compact.reduce((n,c)=>used.has(c.id)?Math.max(n,c.page+1):n,0) : 0;
  for (let bank = 0; bank < count; bank++) {
    if (physical) {
      const active=new Set(slots.flatMap(s=>s.assignments.filter(a=>a.bank===bank).map(a=>a.chart)));
      const charts = compact.filter(c=>active.has(c.id));
      banks.push({ bank, pages:extent, addressPages:compactPages, chartPacking:true, charts,
        rooms: [...new Set(charts.map(c => c.room))].map(room => ({room})) });
      continue;
    }
    const active = new Set(bank === 0 ? layout.rooms.map((r, i) => i) : slots.filter(s => s.bank === bank).flatMap(s => s.conflicts || s.receivers || [s.room]));
    const regions = layout.rooms.flatMap((r, room) => active.has(room) && r.region
      ? [{ id: room, w: r.region.w, h: r.region.h, sourceRegion: r.region }] : []);
    const pages = shelves(regions, o.page, o.page, o.gutter);
    const rooms = regions.map(r => ({ room: r.id, sourceRegion: { ...r.sourceRegion }, region: { page: r.page, ...r.rect } }));
    const byRoom = new Map(rooms.map(r => [r.room, r]));
    const charts = layout.charts.filter(c => byRoom.has(c.room)).map(c => {
      const r = byRoom.get(c.room);
      return { ...c, page: r.region.page, rect: { ...c.rect,
        x: c.rect.x + r.region.x - r.sourceRegion.x, y: c.rect.y + r.region.y - r.sourceRegion.y } };
    });
    banks.push({ bank, pages, rooms, charts });
  }
  return banks;
}

export function buildAtlas(group, plan, { room } = {}) {
  const ro = options(room, 'room'), data = roomData(plan);
  const roomCharts = [], hash = fingerprint();
  hash.add(JSON.stringify([VERSION, plan.generatorVersion ?? null, ro, [...data.buildings], data.rooms]));
  group.updateMatrixWorld(true);
  group.traverse(mesh => {
    if (!atlasMesh(mesh)) return;
    const state = prepare(mesh, data), g = mesh.geometry;
    if (!state.room) state.room = chartsFor(mesh, state.owners);
    const outdoors = new Map();
    const mine = state.room.map(c => {
      if (c.room >= 0) return c;
      if (!outdoors.has(c.tile)) {
        outdoors.set(c.tile, data.rooms.length);
        data.rooms.push({ id: `outdoor:${data.rooms.length}`, outdoor: true, region: null });
      }
      const room = outdoors.get(c.tile);
      return { ...c, room, outdoor: true };
    });
    roomCharts.push(...mine);
    const owner = new Float32Array(g.attributes.position.count).fill(-1);
    for (const c of mine) for (const f of c.faces) owner.fill(c.room, f * 3, f * 3 + 3);
    g.setAttribute('lmRoom', new THREE.Float32BufferAttribute(owner, 1));
    g.deleteAttribute('uv3'); g.deleteAttribute('lmLightPage');
    hash.add(mesh.material.name || ''); hash.add(JSON.stringify(mesh.matrixWorld.elements));
    for (const name of ['position', 'normal', 'uv']) if (g.attributes[name]) hash.add(g.attributes[name].array);
  });
  const rc = scaled(roomCharts, ro);
  const roomPages = roomLayout(rc, data.rooms, ro);
  writeUV(rc, ro, 'uv3', 'lmLightPage');
  const matrices=new WeakMap(), xyz=new Float32Array(3);
  const publicChart = c => {
    const identity=fingerprint(),pos=c.mesh.geometry.attributes.position;
    if (!matrices.has(c.mesh)) {
      const h=fingerprint(); h.add(new Float64Array(c.mesh.matrixWorld.elements)); matrices.set(c.mesh,h.key());
    }
    identity.add(matrices.get(c.mesh));
    for (const f of c.faces) for (let k=0;k<3;k++) {
      const i=f*3+k; xyz[0]=pos.getX(i);xyz[1]=pos.getY(i);xyz[2]=pos.getZ(i);identity.add(xyz);
    }
    return { id:c.id, key:identity.key(), mesh: c.mesh, faces: c.faces, page: c.page, rect: c.rect, outdoor: !!c.outdoor, density: c.density };
  };
  const lightLayout = { pages: roomPages, rooms: data.rooms, plan,
    charts: rc.map(c => ({ ...publicChart(c), room: c.room })) };
  // uv3 remains the stable base layout. For a sparse bank, add
  // (region.xy - sourceRegion.xy) / page to uv3 and use region.page.
  lightLayout.packBanks = (lights, slots) => packBanks(lightLayout, lights, ro, slots);
  return { key: hash.key(), room: lightLayout };
}
