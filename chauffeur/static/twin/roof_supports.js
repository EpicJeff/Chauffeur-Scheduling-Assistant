export const SUPPORT_KINDS = ['walls', 'bracket', 'corbel', 'brace', 'cable', 'post'];

export function isSupported(section) {
  return !!section.support?.kind && section.support.kind !== 'walls';
}

/** Optional ordinary roof-local rotation about a point in building feet. */
export function roofPoint(roof, point, inverse = false) {
  const frame = roof.roof_frame;
  if (!frame) return [...point];
  const angle = frame.angle * (inverse ? -1 : 1), c = Math.cos(angle), s = Math.sin(angle);
  const x = point[0] - frame.origin[0], y = point[1] - frame.origin[1];
  return [frame.origin[0] + c*x - s*y, frame.origin[1] + s*x + c*y, ...point.slice(2)];
}

/** Authored outer-edge points in building feet. u is distance along the edge. */
export function supportPoints(roof) {
  if (!isSupported(roof) || roof.support.count === 0) return [];
  const area = roof.area || [[roof.rect[0], roof.rect[1]], [roof.rect[2], roof.rect[1]],
    [roof.rect[2], roof.rect[3]], [roof.rect[0], roof.rect[3]]];
  const segments = area.map((a, i) => [a, area[(i + 1) % area.length]]);
  const axis = (a, b) => Math.abs(a[0] - b[0]) <= 1e-8 ? 0 : Math.abs(a[1] - b[1]) <= 1e-8 ? 1 : null;
  const host = roof.host?.edge;
  let edge;
  if (Number.isInteger(host) && host >= 0 && host < area.length) {
    const [a, b] = segments[host], dx = b[0] - a[0], dy = b[1] - a[1];
    const orientation = segments.reduce((n, [p, q]) => n + p[0] * q[1] - p[1] * q[0], 0);
    const sign = orientation > 0 ? 1 : -1, inward = [-dy * sign, dx * sign];
    const candidates = segments.flatMap(([p, q], i) => i !== host && axis(p, q) === axis(a, b)
      && (q[0] - p[0]) * dx + (q[1] - p[1]) * dy < 0
      ? [[i, (p[0] - a[0]) * inward[0] + (p[1] - a[1]) * inward[1]]] : []);
    candidates.sort((a, b) => b[1] - a[1] || a[0] - b[0]);
    edge = candidates[0]?.[0] ?? host;
  } else {
    // All authored eaves bear at plate; gable/clip edges rise above it.
    edge = roof.edges?.findIndex(e => e.setting === 'sloped') ?? 0;
    if (edge < 0) edge = 0;
  }
  const [a, b] = segments[edge], width = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const support = roof.support, count = Number.isInteger(support.count) && support.count >= 0 && support.count <= 40 ? support.count : 2;
  const inset = Math.min(support.inset_ft ?? .6, width / 2);
  return Array.from({length: count}, (_, i) => {
    let u = inset + i * (width - 2 * inset) / Math.max(1, count - 1);
    let at = support.at?.[String(i)];
    if (!at) at = roofPoint(roof, a.map((v, k) => v + (b[k] - v) * u / width));
    else { at = [...at]; u = roofPoint(roof, at, true).reduce((n, v, k) => n + (v - a[k]) * (b[k] - a[k]) / width, 0); }
    return {id: `support:${i}`, edge, u, at};
  });
}

/** A shed's frame, in plan feet. The depth axis runs from wall to eave. */
export function supportFrame(roof) {
  if (roof.roof_frame) {
    const frame = supportFrame({...roof, roof_frame: null}), angle = roof.roof_frame.angle;
    const c = Math.cos(angle), s = Math.sin(angle), rotate = p => [c*p[0]-s*p[1],s*p[0]+c*p[1]];
    return {...frame, origin: roofPoint(roof, frame.origin), outward: rotate(frame.outward), tangent: rotate(frame.tangent)};
  }
  const r = roof.rect || [Math.min(...roof.area.map(p => p[0])), Math.min(...roof.area.map(p => p[1])),
    Math.max(...roof.area.map(p => p[0])), Math.max(...roof.area.map(p => p[1]))];
  const area = roof.area || [[r[0],r[1]],[r[2],r[1]],[r[2],r[3]],[r[0],r[3]]];
  if (Number.isInteger(roof.host?.edge) && area[roof.host.edge]) {
    const a=area[roof.host.edge], b=area[(roof.host.edge+1)%area.length];
    const width=Math.hypot(b[0]-a[0],b[1]-a[1]);
    const sign=area.reduce((n,p,i)=>{const q=area[(i+1)%area.length];return n+p[0]*q[1]-p[1]*q[0];},0)>0?1:-1;
    const outward=[-(b[1]-a[1])*sign/width,(b[0]-a[0])*sign/width];
    const origin=a.map((v,i)=>(v+b[i])/2);
    return {origin,outward,tangent:[-outward[1],outward[0]],width,
      depth:Math.max(...area.map(p=>(p[0]-origin[0])*outward[0]+(p[1]-origin[1])*outward[1]))};
  }
  const side = roof.low_side || ['y0', 'x1', 'y1', 'x0'][roof.edges?.findIndex(e => e.setting === 'sloped')] || 'y0';
  const outward = {x0: [-1, 0], x1: [1, 0], y0: [0, -1], y1: [0, 1]}[side];
  const axis = side[0] === 'x' ? 0 : 1, across = 1 - axis;
  const origin = [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2];
  origin[axis] = r[axis + (side[1] === '0' ? 2 : 0)];
  return {origin, outward, tangent: [-outward[1], outward[0]],
    depth: r[axis + 2] - r[axis], width: r[across + 2] - r[across]};
}

const DEFAULT_SIZES = { bracket: 0.3, corbel: 0.5, brace: 0.45, cable: 0.08, post: 0.5 };

function validSize(value, fallback) {
  if (!Number.isFinite(value) || value <= 0) return fallback;
  return Math.max(0.05, Math.min(3, value));
}

function roofTopFallback(roof, x, y) {
  const [lx, ly] = roofPoint(roof, [x, y], true);
  const r = roof.rect || [
    Math.min(...roof.area.map(p => p[0])), Math.min(...roof.area.map(p => p[1])),
    Math.max(...roof.area.map(p => p[0])), Math.max(...roof.area.map(p => p[1])),
  ];
  const [x0, y0, x1, y1] = r, plate = roof.plate ?? 8;
  const side = name => (roof.pitches?.[name] ?? roof.pitch ?? 0) / 12;
  const kind = roof.kind || (roof.low_side || roof.host ? 'shed' : 'flat');
  if (kind === 'flat') return plate;
  const edgeVal = {
    x0: () => plate + (lx - x0) * side('x0'),
    x1: () => plate + (x1 - lx) * side('x1'),
    y0: () => plate + (ly - y0) * side('y0'),
    y1: () => plate + (y1 - ly) * side('y1'),
  };
  if (kind === 'shed') {
    const low = roof.low_side || ['y0', 'x1', 'y1', 'x0'][roof.edges?.findIndex(e => e.setting === 'sloped')] || 'y0';
    return (edgeVal[low] || edgeVal.y0)();
  }
  const endKind = end => roof.ends?.[end] ?? kind;
  let sides = kind === 'gable' ? (roof.ridge === 'y' ? ['x0', 'x1'] : ['y0', 'y1']) : ['x0', 'x1', 'y0', 'y1'];
  const ends = roof.ridge === 'y' ? ['y0', 'y1'] : ['x0', 'x1'];
  sides = sides.filter(n => !ends.includes(n) || endKind(n) !== 'gable');
  for (const end of ends) if (endKind(end) !== 'gable' && !sides.includes(end)) sides.push(end);
  const across = roof.ridge === 'y' ? ['x0', 'x1'] : ['y0', 'y1'];
  const span = roof.ridge === 'y' ? x1 - x0 : y1 - y0;
  const a = side(across[0]), b = side(across[1]);
  const rise = a + b > 1e-9 ? span * a * b / (a + b) : 0;
  return Math.min(...sides.map(n => edgeVal[n]() + (ends.includes(n) && endKind(n) === 'clip' ? rise * 2 / 3 : 0)));
}

function sliceBoundsAt(areaUW, u, wAt, defaultDepth) {
  const sample = queryU => {
    const hits = [];
    for (let i = 0; i < areaUW.length; i++) {
      const a = areaUW[i], b = areaUW[(i + 1) % areaUW.length];
      if ((a[0] <= queryU && b[0] > queryU) || (b[0] <= queryU && a[0] > queryU)) {
        const t = (queryU - a[0]) / (b[0] - a[0]);
        hits.push(a[1] + t * (b[1] - a[1]));
      }
    }
    hits.sort((p, q) => p - q);
    return hits;
  };
  let hits = sample(u);
  if (hits.length < 2) hits = sample(u + 1e-4);
  if (hits.length < 2) hits = sample(u - 1e-4);
  if (hits.length < 2) return { wWall: 0, wEdge: Math.max(0.5, wAt > 0.05 ? wAt : defaultDepth) };
  let best = null, bestDist = Infinity;
  for (let i = 0; i + 1 < hits.length; i += 2) {
    const lo = hits[i], hi = hits[i + 1];
    if (hi - lo < 1e-4) continue;
    const d = wAt < lo ? lo - wAt : wAt > hi ? wAt - hi : 0;
    if (d < bestDist) { bestDist = d; best = { wWall: lo, wEdge: hi }; }
  }
  return best || { wWall: 0, wEdge: Math.max(0.5, wAt > 0.05 ? wAt : defaultDepth) };
}

function createBuilder() {
  const positions = [], normals = [], uvs = [];
  const pushVertex = (p, n, uv) => {
    positions.push(p[0], p[1], p[2]);
    normals.push(n[0], n[1], n[2]);
    uvs.push(uv[0], uv[1]);
  };
  const finite3 = p => Number.isFinite(p[0]) && Number.isFinite(p[1]) && Number.isFinite(p[2]);
  const addTri = (a, b, c, nA = null, nB = null, nC = null, uvA = null, uvB = null, uvC = null) => {
    if (!finite3(a) || !finite3(b) || !finite3(c)) return;
    const e1x = b[0] - a[0], e1y = b[1] - a[1], e1z = b[2] - a[2];
    const e2x = c[0] - a[0], e2y = c[1] - a[1], e2z = c[2] - a[2];
    const nx = e1y * e2z - e1z * e2y, ny = e1z * e2x - e1x * e2z, nz = e1x * e2y - e1y * e2x;
    const area2 = Math.hypot(nx, ny, nz);
    if (!(area2 > 1e-9)) return;
    const fn = [nx / area2, ny / area2, nz / area2];
    if (!uvA || !uvB || !uvC) {
      const l1 = Math.hypot(e1x, e1y, e1z);
      const t1 = [e1x / l1, e1y / l1, e1z / l1];
      const t2 = [fn[1] * t1[2] - fn[2] * t1[1], fn[2] * t1[0] - fn[0] * t1[2], fn[0] * t1[1] - fn[1] * t1[0]];
      const proj = p => {
        const dx = p[0] - a[0], dy = p[1] - a[1], dz = p[2] - a[2];
        return [dx * t1[0] + dy * t1[1] + dz * t1[2], dx * t2[0] + dy * t2[1] + dz * t2[2]];
      };
      uvA = uvA || proj(a); uvB = uvB || proj(b); uvC = uvC || proj(c);
    }
    pushVertex(a, nA || fn, uvA);
    pushVertex(b, nB || fn, uvB);
    pushVertex(c, nC || fn, uvC);
  };
  const addQuad = (a, b, c, d, n0 = null, n1 = null, uv0 = null, uv1 = null, uv2 = null, uv3 = null) => {
    if (!uv0) {
      const e1x = b[0] - a[0], e1y = b[1] - a[1], e1z = b[2] - a[2];
      const e2x = c[0] - a[0], e2y = c[1] - a[1], e2z = c[2] - a[2];
      const nx = e1y * e2z - e1z * e2y, ny = e1z * e2x - e1x * e2z, nz = e1x * e2y - e1y * e2x;
      const area2 = Math.hypot(nx, ny, nz), l1 = Math.hypot(e1x, e1y, e1z);
      if (area2 > 1e-9 && l1 > 1e-9) {
        const fn = [nx / area2, ny / area2, nz / area2];
        const t1 = [e1x / l1, e1y / l1, e1z / l1];
        const t2 = [fn[1] * t1[2] - fn[2] * t1[1], fn[2] * t1[0] - fn[0] * t1[2], fn[0] * t1[1] - fn[1] * t1[0]];
        const proj = p => {
          const dx = p[0] - a[0], dy = p[1] - a[1], dz = p[2] - a[2];
          return [dx * t1[0] + dy * t1[1] + dz * t1[2], dx * t2[0] + dy * t2[1] + dz * t2[2]];
        };
        uv0 = proj(a); uv1 = proj(b); uv2 = proj(c); uv3 = proj(d);
      }
    }
    addTri(a, b, c, n0, n0, n1, uv0, uv1, uv2);
    addTri(a, c, d, n0, n1, n1, uv0, uv2, uv3);
  };
  const addHexahedron = (p000, p100, p110, p010, p001, p101, p111, p011) => {
    addQuad(p100, p000, p010, p110); // -Z
    addQuad(p001, p101, p111, p011); // +Z
    addQuad(p000, p001, p011, p010); // -X
    addQuad(p101, p100, p110, p111); // +X
    addQuad(p000, p100, p101, p001); // -Y
    addQuad(p011, p111, p110, p010); // +Y
  };
  const addSquarePyramid = (b0, b1, b2, b3, apex) => {
    addQuad(b0, b3, b2, b1);
    addTri(b0, b1, apex);
    addTri(b1, b2, apex);
    addTri(b2, b3, apex);
    addTri(b3, b0, apex);
  };
  const build = (THREE, frame) => {
    if (!positions.length) return null;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
    geometry.applyMatrix4(frame);
    return geometry;
  };
  return { addTri, addQuad, addHexahedron, addSquarePyramid, build };
}

function cubicBezier(p0, p1, p2, p3, t) {
  const mt = 1 - t, mt2 = mt * mt, t2 = t * t;
  const a = mt2 * mt, b = 3 * mt2 * t, c = 3 * mt * t2, d = t2 * t;
  return [a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]];
}

function corbelProfile(style) {
  if (style === 'plain') {
    return [[0, 0], [1, 0], [1, 0.14], [0.74, 0.14], [0.64, 0.38], [0.40, 0.42], [0.24, 0.78], [0.16, 1.0], [0, 1.0]];
  }
  const pts = [[0, 0], [1, 0], [1, 0.13], [0.94, 0.19], [0.85, 0.20]];
  const c1 = [[0.85, 0.20], [0.62, 0.19], [0.58, 0.34], [0.56, 0.46]];
  const c2 = [[0.56, 0.46], [0.54, 0.62], [0.34, 0.74], [0.22, 0.86]];
  for (let i = 1; i <= 8; i++) pts.push(cubicBezier(...c1, i / 8));
  for (let i = 1; i <= 8; i++) pts.push(cubicBezier(...c2, i / 8));
  pts.push([0.21, 0.94], [0.14, 1.0], [0, 1.0]);
  return pts;
}

function buildCorbel(THREE, frame, { u, wWall, wEdge, wAt, size, style, slabBot, groundAtLocal }) {
  const availRun = Math.max(0.3, Math.min(wEdge, wAt > wWall + 0.3 ? wAt : wEdge) - wWall - 0.06);
  const run = Math.min(availRun, Math.max(0.45, size * 4.5));
  if (!(run > 0.1)) return null;
  const hw = Math.max(0.15, Math.min(1.5, size * 0.8)) / 2;
  const yTop0P = slabBot(u + hw, wWall), yTop1P = slabBot(u + hw, wWall + run);
  const yTop0M = slabBot(u - hw, wWall), yTop1M = slabBot(u - hw, wWall + run);
  const yTopMin = Math.min(yTop0P, yTop0M);
  const ground = groundAtLocal(u, wWall);
  const maxDrop = Number.isFinite(ground) ? Math.max(0.35, yTopMin - ground - 0.1) : 4.5;
  const drop = Math.min(maxDrop, Math.max(0.45, Math.min(run * 1.15, 4.0)));
  const raw = corbelProfile(style);
  const plus = raw.map(([fw, fy]) => [u + hw, yTop0P + (yTop1P - yTop0P) * fw - fy * drop, wWall + fw * run]);
  const minus = raw.map(([fw, fy]) => [u - hw, yTop0M + (yTop1M - yTop0M) * fw - fy * drop, wWall + fw * run]);
  const b = createBuilder();
  const uvPlus = plus.map(p => [p[2] - wWall, p[1] - (yTop0P - drop)]);
  const uvMinus = minus.map(p => [p[2] - wWall, p[1] - (yTop0M - drop)]);
  for (let i = 1; i + 1 < raw.length; i++) {
    b.addTri(plus[0], plus[i], plus[i + 1], [1, 0, 0], [1, 0, 0], [1, 0, 0], uvPlus[0], uvPlus[i], uvPlus[i + 1]);
    b.addTri(minus[0], minus[i + 1], minus[i], [-1, 0, 0], [-1, 0, 0], [-1, 0, 0], uvMinus[0], uvMinus[i + 1], uvMinus[i]);
  }
  const quadNormal = i => {
    const j = (i + 1) % raw.length, a = plus[i], m = minus[i], c = plus[j];
    const e1x = m[0] - a[0], e1y = m[1] - a[1], e1z = m[2] - a[2];
    const e2x = c[0] - a[0], e2y = c[1] - a[1], e2z = c[2] - a[2];
    const nx = e1y * e2z - e1z * e2y, ny = e1z * e2x - e1x * e2z, nz = e1x * e2y - e1y * e2x;
    const len = Math.hypot(nx, ny, nz) || 1;
    return [nx / len, ny / len, nz / len];
  };
  const smooth = style !== 'plain';
  let arc = 0;
  for (let i = 0; i < raw.length; i++) {
    const j = (i + 1) % raw.length;
    const len = Math.hypot(plus[j][2] - plus[i][2], (plus[j][1] + minus[j][1] - plus[i][1] - minus[i][1]) * 0.5);
    let n0 = null, n1 = null;
    if (smooth && i >= 3 && i <= raw.length - 4) {
      const avg = idx => {
        const na = quadNormal((idx - 1 + raw.length) % raw.length), nb = quadNormal(idx);
        const nx = na[0] + nb[0], ny = na[1] + nb[1], nz = na[2] + nb[2], l = Math.hypot(nx, ny, nz) || 1;
        return [nx / l, ny / l, nz / l];
      };
      n0 = i === 3 ? quadNormal(i) : avg(i);
      n1 = i === raw.length - 4 ? quadNormal(i) : avg(j);
    }
    b.addQuad(plus[i], minus[i], minus[j], plus[j], n0, n1,
      [0, arc], [hw * 2, arc], [hw * 2, arc + len], [0, arc + len]);
    arc += len;
  }
  return b.build(THREE, frame);
}

function buildBrace(THREE, frame, { u, wWall, wEdge, wAt, size, slabBot, groundAtLocal }) {
  const s = Math.max(0.14, Math.min(1.0, size)), hs = s / 2;
  const availRun = Math.max(s + 0.25, Math.min(wEdge, wAt > wWall + 0.3 ? wAt : wEdge) - wWall - 0.06);
  const run = Math.min(availRun, Math.max(s * 4.5, Math.min(availRun, Math.max(2.8, size * 9.5))));
  if (!(run > s + 0.05)) return null;
  const yTop0M = slabBot(u - hs, wWall), yTop0P = slabBot(u + hs, wWall);
  const yTopPostM = slabBot(u - hs, wWall + s), yTopPostP = slabBot(u + hs, wWall + s);
  const yTopEndM = slabBot(u - hs, wWall + run), yTopEndP = slabBot(u + hs, wWall + run);
  const yTopMin = Math.min(yTop0M, yTop0P);
  const ground = groundAtLocal(u, wWall);
  const maxDrop = Number.isFinite(ground) ? Math.max(s * 2.2, yTopMin - ground - 0.1) : 5.0;
  const drop = Math.min(maxDrop, Math.max(s * 3.8, Math.min(run * 1.12, 4.2)));
  const yBot = yTopMin - drop;
  const b = createBuilder();
  // 1. Vertical timber wall post flush at w = wWall, sheared top to slab underside, continuing below diagonal.
  b.addHexahedron(
    [u - hs, yBot, wWall], [u + hs, yBot, wWall], [u + hs, yTop0P, wWall], [u - hs, yTop0M, wWall],
    [u - hs, yBot, wWall + s], [u + hs, yBot, wWall + s], [u + hs, yTopPostP, wWall + s], [u - hs, yTopPostM, wWall + s],
  );
  // 2. Top arm parallel to slab underside across both u and w, extending past diagonal.
  b.addHexahedron(
    [u - hs, yTopPostM - s, wWall + s], [u + hs, yTopPostP - s, wWall + s],
    [u + hs, yTopPostP, wWall + s], [u - hs, yTopPostM, wWall + s],
    [u - hs, yTopEndM - s, wWall + run], [u + hs, yTopEndP - s, wWall + run],
    [u + hs, yTopEndP, wWall + run], [u - hs, yTopEndM, wWall + run],
  );
  // 3. Mitered timber diagonal knee brace starting partway down post and meeting arm short of its tip.
  const w0 = wWall + s, tail = Math.min(drop * 0.34, Math.max(s * 1.65, 0.75));
  const y0 = yBot + tail;
  const tipClear = Math.max(s * 1.05, (run - s) * 0.22);
  const w1 = wWall + run - tipClear;
  const armSpan = Math.max(1e-4, run - s);
  const armBotSide = (f, w) => {
    const t = Math.max(0, Math.min(1, (w - (wWall + s)) / armSpan));
    const back = yTopPostM + (yTopPostP - yTopPostM) * f - s;
    const front = yTopEndM + (yTopEndP - yTopEndM) * f - s;
    return back + (front - back) * t;
  };
  const y1 = armBotSide(0.5, w1);
  if (w1 > w0 + 0.15 && y1 > y0 + 0.15) {
    const dw = w1 - w0, dy = y1 - y0, len = Math.hypot(dw, dy);
    const sD = s * 0.90, hd = sD / 2;
    const nw = -dy / len * hd, ny = dw / len * hd;
    const fM = 0.5 - hd / (2 * hs), fP = 0.5 + hd / (2 * hs);
    const slopeW = (armBotSide(0.5, wWall + run) - armBotSide(0.5, w0)) / armSpan;
    const denom = dy - slopeW * dw;
    if (denom > 1e-4) {
      const yLTopMax = Math.min(yTopPostM, yTopPostP) - s;
      const yLTop = Math.min(yLTopMax, y0 + ny - (nw / dw) * dy);
      const yLBot = Math.max(yBot + 0.05, y0 - ny + (nw / dw) * dy);
      const tUTop = (armBotSide(0.5, w0 + nw) - (y0 + ny)) / denom;
      const tUBot = (armBotSide(0.5, w0 - nw) - (y0 - ny)) / denom;
      const wUTop = Math.max(w0 + 0.05, Math.min(wWall + run - 0.04, w0 + nw + tUTop * dw));
      const wUBot = Math.max(wUTop + 0.04, Math.min(wWall + run - 0.04, w0 - nw + tUBot * dw));
      if (yLTop > yLBot + 0.04 && wUBot > w0 + 0.08) {
        b.addHexahedron(
          [u - hd, yLBot, w0], [u + hd, yLBot, w0], [u + hd, yLTop, w0], [u - hd, yLTop, w0],
          [u - hd, armBotSide(fM, wUBot), wUBot], [u + hd, armBotSide(fP, wUBot), wUBot],
          [u + hd, armBotSide(fP, wUTop), wUTop], [u - hd, armBotSide(fM, wUTop), wUTop],
        );
      }
    }
  }
  return b.build(THREE, frame);
}

function buildCable(THREE, frame, { u, wWall, wAt, size, slabTop, wallTopAtLocal }) {
  const localDepth = Math.max(0.45, wAt - wWall);
  const r = Math.max(0.018, Math.min(0.18, size * 0.35));
  const plateW = Math.max(0.22, Math.min(0.65, size * 3.0)), ph = plateW / 2;
  const wallPlateD = Math.max(0.11, Math.min(0.22, r * 3.8));
  const eavePlateD = Math.max(0.07, Math.min(0.16, r * 2.5));
  const wEave = wWall + Math.max(ph + 0.04, localDepth - Math.min(ph, localDepth * 0.25));
  const yTopWall = slabTop(u, wWall), yTopEave = slabTop(u, wEave);
  const wallTop = wallTopAtLocal(u, wWall);
  const hasWallRoom = Number.isFinite(wallTop) && (wallTop - yTopWall) >= 0.75;
  const b = createBuilder();
  let pA, pB, rodR = r;
  if (hasWallRoom) {
    const idealAnchor = Math.max(yTopEave + Math.max(1.2, localDepth * 0.75), yTopWall + 0.75);
    const yAnchor = Math.max(yTopWall + ph + 0.04, Math.min(idealAnchor, wallTop - ph - 0.04));
    // 1. Wall anchor plate (6 tris, flush at exterior wall face, clamped below wall top).
    b.addSquarePyramid(
      [u - ph, yAnchor - ph, wWall], [u + ph, yAnchor - ph, wWall],
      [u + ph, yAnchor + ph, wWall], [u - ph, yAnchor + ph, wWall],
      [u, yAnchor, wWall + wallPlateD],
    );
    // 2. Eave anchor plate (6 tris, flush on slab top).
    b.addSquarePyramid(
      [u - ph, slabTop(u - ph, wEave + ph), wEave + ph],
      [u + ph, slabTop(u + ph, wEave + ph), wEave + ph],
      [u + ph, slabTop(u + ph, wEave - ph), wEave - ph],
      [u - ph, slabTop(u - ph, wEave - ph), wEave - ph],
      [u, yTopEave + eavePlateD, wEave],
    );
    pA = [u, yTopEave + eavePlateD * 0.72, wEave];
    pB = [u, yAnchor, wWall + wallPlateD * 0.72];
  } else {
    // Low/missing wall fallback: short flat tie on the slab top from wall edge to eave, never floating.
    const wInner = wWall + ph;
    const yTopInner = slabTop(u, wInner);
    const maxRise = Number.isFinite(wallTop) ? Math.max(0.035, Math.min(eavePlateD, wallTop - yTopInner + 0.015)) : eavePlateD;
    rodR = Math.min(r, maxRise * 0.42);
    const rodLift = Math.max(rodR + 0.004, maxRise * 0.65);
    // 1. Inner high-edge plate (6 tris, back edge flush at wWall, resting on slab top).
    b.addSquarePyramid(
      [u - ph, slabTop(u - ph, wInner + ph), wInner + ph],
      [u + ph, slabTop(u + ph, wInner + ph), wInner + ph],
      [u + ph, slabTop(u + ph, wInner - ph), wInner - ph],
      [u - ph, slabTop(u - ph, wInner - ph), wInner - ph],
      [u, yTopInner + maxRise, wInner],
    );
    // 2. Outer eave plate (6 tris, flush on slab top).
    const wOuter = Math.max(wInner + plateW + 0.1, wEave);
    const yTopOuter = slabTop(u, wOuter);
    b.addSquarePyramid(
      [u - ph, slabTop(u - ph, wOuter + ph), wOuter + ph],
      [u + ph, slabTop(u + ph, wOuter + ph), wOuter + ph],
      [u + ph, slabTop(u + ph, wOuter - ph), wOuter - ph],
      [u - ph, slabTop(u - ph, wOuter - ph), wOuter - ph],
      [u, yTopOuter + maxRise, wOuter],
    );
    pA = [u, yTopOuter + rodLift, wOuter];
    pB = [u, yTopInner + rodLift, wInner];
  }
  // 3. Tension rod (12 tris, 4-sided profile seated into both anchor bosses).
  const dy = pB[1] - pA[1], dw = pB[2] - pA[2], len = Math.hypot(dy, dw);
  if (len > 0.05) {
    const vy = -dw / len, vz = dy / len;
    const ring = p => [
      [p[0] - rodR, p[1] - rodR * vy, p[2] - rodR * vz],
      [p[0] + rodR, p[1] - rodR * vy, p[2] - rodR * vz],
      [p[0] + rodR, p[1] + rodR * vy, p[2] + rodR * vz],
      [p[0] - rodR, p[1] + rodR * vy, p[2] + rodR * vz],
    ];
    const rWall = ring(pB), rEave = ring(pA);
    b.addHexahedron(rWall[0], rWall[1], rWall[2], rWall[3], rEave[0], rEave[1], rEave[2], rEave[3]);
  }
  return b.build(THREE, frame);
}

function buildPost(THREE, frame, { u, wWall, wEdge, wAt, size, outerOverhang, hasOverride, slabBot, groundAtLocal }) {
  const s = Math.max(0.15, Math.min(2.0, size)), hs = s / 2;
  const hb = (s * 1.38) / 2;
  const maxW = wEdge + outerOverhang - hs - 0.1;
  const wPost = !hasOverride && wAt > maxW ? Math.max(wWall + hs, maxW) : wAt;
  const groundRaw = groundAtLocal(u, wPost);
  const ground = Number.isFinite(groundRaw) ? groundRaw : 0;
  const y00 = slabBot(u - hs, wPost - hs), y10 = slabBot(u + hs, wPost - hs);
  const y11 = slabBot(u + hs, wPost + hs), y01 = slabBot(u - hs, wPost + hs);
  const minTop = Math.min(y00, y10, y11, y01);
  // Keep a visible minimum stub instead of silently dropping the post when ground is above the slab.
  const effectiveGround = minTop > ground + 0.04 ? ground : minTop - 0.25;
  const postH = minTop - effectiveGround;
  const baseH = Math.min(Math.max(0.25, s * 0.75), postH * 0.25);
  const yMid = effectiveGround + baseH;
  const b = createBuilder();
  // 1. Plinth base (12 tris) seated at ground.
  b.addHexahedron(
    [u - hb, effectiveGround, wPost - hb], [u + hb, effectiveGround, wPost - hb],
    [u + hb, yMid, wPost - hb], [u - hb, yMid, wPost - hb],
    [u - hb, effectiveGround, wPost + hb], [u + hb, effectiveGround, wPost + hb],
    [u + hb, yMid, wPost + hb], [u - hb, yMid, wPost + hb],
  );
  // 2. Square post shaft (12 tris) mitered cleanly to the slab underside.
  b.addHexahedron(
    [u - hs, yMid, wPost - hs], [u + hs, yMid, wPost - hs], [u + hs, y10, wPost - hs], [u - hs, y00, wPost - hs],
    [u - hs, yMid, wPost + hs], [u + hs, yMid, wPost + hs], [u + hs, y11, wPost + hs], [u - hs, y01, wPost + hs],
  );
  return b.build(THREE, frame);
}

/** Support geometry per point in building feet.
 * Brackets keep the exact sheared box of the original awning renderer.
 * THREE is supplied by the renderer so point placement stays renderer-free. */
export function supportGeometry(roof, points, ctx) {
  if (!isSupported(roof) || roof.support.count === 0 || !points?.length) return [];
  const kind = roof.support.kind;
  const { THREE } = ctx, { origin, outward, tangent, depth } = supportFrame(roof);
  if (kind === 'bracket') {
    const run = Math.min(3, depth * .8), rise = run * 2.6 / 3;
    if (!(run > 0)) return [];
    const slope = (roof.pitch || 0) / 12;
    const bracketMid = roof.plate + depth * slope - run * slope
      - (roof.thickness_ft ?? .25) - .15 - .04 - rise / 2;
    const frame = new THREE.Matrix4().makeBasis(new THREE.Vector3(tangent[0], 0, -tangent[1]),
      new THREE.Vector3(0, 1, 0), new THREE.Vector3(outward[0], 0, -outward[1]))
      .setPosition(origin[0], 0, -origin[1]);
    return points.map((point, i) => {
      const u = (point.at[0] - origin[0]) * tangent[0] + (point.at[1] - origin[1]) * tangent[1];
      const geometry = new THREE.BoxGeometry(.3, .3, run), p = geometry.attributes.position;
      for (let j = 0; j < p.count; j++) p.setY(j, p.getY(j) + rise / run * p.getZ(j));
      geometry.computeVertexNormals();
      geometry.translate(u, bracketMid, run / 2).applyMatrix4(frame);
      return { geometry, slot: 'support', part: point.id || `support:${i}` };
    });
  }
  if (!['corbel', 'brace', 'cable', 'post'].includes(kind)) return [];
  const thickness = roof.thickness_ft ?? 0.25;
  const size = validSize(roof.support?.size_ft, DEFAULT_SIZES[kind]);
  const style = roof.support?.style || (kind === 'corbel' ? 'scroll' : 'plain');
  const frame = new THREE.Matrix4().makeBasis(new THREE.Vector3(tangent[0], 0, -tangent[1]),
    new THREE.Vector3(0, 1, 0), new THREE.Vector3(outward[0], 0, -outward[1]))
    .setPosition(origin[0], 0, -origin[1]);
  const toPlan = (u, w) => [origin[0] + u * tangent[0] + w * outward[0], origin[1] + u * tangent[1] + w * outward[1]];
  const slabTop = (u, w) => {
    const [px, py] = toPlan(u, w);
    if (typeof ctx?.slabBottomAt === 'function') {
      const b = ctx.slabBottomAt(px, py);
      if (Number.isFinite(b)) return b + thickness;
    }
    return roofTopFallback(roof, px, py);
  };
  const slabBot = (u, w) => slabTop(u, w) - thickness;
  const groundAtLocal = (u, w) => {
    if (typeof ctx?.groundAt !== 'function') return NaN;
    const [px, py] = toPlan(u, w);
    return ctx.groundAt(px, py);
  };
  const wallTopAtLocal = (u, w) => {
    if (typeof ctx?.wallTopAt !== 'function') return NaN;
    const [px, py] = toPlan(u, w);
    const v = ctx.wallTopAt(px, py, outward);
    return Number.isFinite(v) ? v : NaN;
  };
  const wallFaceAtLocal = (u, w) => {
    if (typeof ctx?.wallFaceAt !== 'function') return 0;
    const [px, py] = toPlan(u, w);
    const offset = ctx.wallFaceAt(px, py, outward);
    return Number.isFinite(offset) && offset > 0 ? offset : 0;
  };
  const rawArea = roof.area || (roof.rect ? [[roof.rect[0], roof.rect[1]], [roof.rect[2], roof.rect[1]],
    [roof.rect[2], roof.rect[3]], [roof.rect[0], roof.rect[3]]] : []);
  const areaUW = rawArea.map(p => {
    const bp = roofPoint(roof, p);
    return [(bp[0] - origin[0]) * tangent[0] + (bp[1] - origin[1]) * tangent[1],
      (bp[0] - origin[0]) * outward[0] + (bp[1] - origin[1]) * outward[1]];
  });
  const slot = kind === 'post' ? 'column' : 'support';
  const result = [];
  for (let i = 0; i < points.length; i++) {
    const point = points[i];
    const u = (point.at[0] - origin[0]) * tangent[0] + (point.at[1] - origin[1]) * tangent[1];
    const wAt = (point.at[0] - origin[0]) * outward[0] + (point.at[1] - origin[1]) * outward[1];
    const { wWall: wRawWall, wEdge } = sliceBoundsAt(areaUW, u, wAt, depth);
    const wFace = wallFaceAtLocal(u, wRawWall);
    const wWall = wFace > 0 && wRawWall + wFace < Math.min(wEdge, wAt > wRawWall + 0.3 ? wAt : wEdge) - 0.35
      ? wRawWall + wFace : wRawWall;
    const outerOverhang = roof.edges?.[point.edge]?.overhang_ft ?? roof.overhang ?? 0;
    const hasOverride = !!roof.support?.at?.[String(i)];
    const params = {
      u, wWall, wEdge, wAt, size, style, outerOverhang, hasOverride,
      slabTop, slabBot, groundAtLocal, wallTopAtLocal,
    };
    const geometry = kind === 'corbel' ? buildCorbel(THREE, frame, params)
      : kind === 'brace' ? buildBrace(THREE, frame, params)
      : kind === 'cable' ? buildCable(THREE, frame, params)
      : buildPost(THREE, frame, params);
    if (geometry) result.push({ geometry, slot, part: point.id || `support:${i}` });
  }
  return result;
}
