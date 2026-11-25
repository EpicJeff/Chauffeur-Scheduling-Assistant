import { isSupported, roofPoint } from './roof_supports.js';
import { planes } from './twin_roof.js';
import { ROOF_THICKNESS, FASCIA } from './trim_dims.js';

const EPS = 1e-9;
const SHED_RECESS_FT = 0.15;
const BACK_OFFSET_FT = 0.01;

function signedArea(poly) {
  let sum = 0;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    sum += a[0] * b[1] - b[0] * a[1];
  }
  return sum * 0.5;
}

function canonicalArea(roof) {
  if (Array.isArray(roof.area) && roof.area.length >= 3) return roof.area.map(p => [p[0], p[1]]);
  if (Array.isArray(roof.rect) && roof.rect.length === 4) {
    const [x0, y0, x1, y1] = roof.rect;
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  }
  return [];
}

function unrotatedSection(roof, area, edges) {
  const base = roof.roof_frame ? { ...roof, roof_frame: null } : roof;
  const rect = base.rect || [
    Math.min(...area.map(p => p[0])), Math.min(...area.map(p => p[1])),
    Math.max(...area.map(p => p[0])), Math.max(...area.map(p => p[1])),
  ];
  const kind = base.kind || (base.low_side || base.host ? 'shed' : 'flat');
  const useEdges = edges || base.edges;
  const low_side = base.low_side || (kind === 'shed'
    ? (['y0', 'x1', 'y1', 'x0'][useEdges?.findIndex(e => e.setting === 'sloped')] || 'y0')
    : undefined);
  return {
    ...base,
    ...(useEdges ? { edges: useEdges } : {}),
    rect,
    kind,
    ...(low_side ? { low_side } : {}),
    plate: base.plate ?? 8,
    pitch: base.pitch ?? 0,
  };
}

function rotateDir(roof, dir) {
  const frame = roof.roof_frame;
  if (!frame) return [dir[0], dir[1]];
  const c = Math.cos(frame.angle), s = Math.sin(frame.angle);
  return [c * dir[0] - s * dir[1], s * dir[0] + c * dir[1]];
}

function offsetPolygon(area, outs, offsets) {
  const n = area.length;
  const shifted = [];
  for (let i = 0; i < n; i++) {
    const a = area[i], b = area[(i + 1) % n], o = outs[i], d = offsets[i];
    shifted.push([[a[0] + o[0] * d, a[1] + o[1] * d], [b[0] + o[0] * d, b[1] + o[1] * d]]);
  }
  const poly = [];
  for (let i = 0; i < n; i++) {
    const [p1, p2] = shifted[(i - 1 + n) % n];
    const [q1, q2] = shifted[i];
    const d1x = p2[0] - p1[0], d1y = p2[1] - p1[1];
    const d2x = q2[0] - q1[0], d2y = q2[1] - q1[1];
    const den = d1x * d2y - d1y * d2x;
    if (Math.abs(den) > 1e-8) {
      const t = ((q1[0] - p1[0]) * d2y - (q1[1] - p1[1]) * d2x) / den;
      poly.push([p1[0] + t * d1x, p1[1] + t * d1y]);
    } else {
      poly.push([(p2[0] + q1[0]) * 0.5, (p2[1] + q1[1]) * 0.5]);
    }
  }
  return poly;
}

function clipConvex(poly, line) {
  if (!poly.length) return [];
  const scale = Math.hypot(line[0], line[1]);
  if (scale < EPS) return line[2] >= 0 ? poly : [];
  const dist = p => {
    const d = (line[0] * p[0] + line[1] * p[1] + line[2]) / scale;
    return Math.abs(d) < EPS ? 0 : d;
  };
  const out = [];
  let prev = poly[poly.length - 1], dp = dist(prev);
  for (const cur of poly) {
    const dc = dist(cur);
    if ((dp < 0) !== (dc < 0)) {
      const t = dp / (dp - dc);
      out.push([prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])]);
    }
    if (dc >= 0) out.push(cur);
    prev = cur; dp = dc;
  }
  const clean = out.filter((p, i) => {
    const q = out[(i + out.length - 1) % out.length];
    return Math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-7;
  });
  return Math.abs(signedArea(clean)) > 1e-8 ? clean : [];
}

function subtractConvex(poly, cutter) {
  if (!cutter || cutter.length < 3) return [poly];
  const orient = signedArea(cutter) >= 0 ? 1 : -1;
  const edges = cutter.map((p, i) => {
    const q = cutter[(i + 1) % cutter.length];
    return orient > 0
      ? [p[1] - q[1], q[0] - p[0], q[1] * p[0] - q[0] * p[1]]
      : [q[1] - p[1], p[0] - q[0], p[1] * q[0] - p[0] * q[1]];
  });
  let overlap = poly;
  for (const e of edges) overlap = clipConvex(overlap, e);
  if (!overlap.length) return [poly];
  const pieces = [];
  let rem = poly;
  for (const e of edges) {
    const outside = clipConvex(rem, [-e[0], -e[1], -e[2]]);
    if (outside.length) pieces.push(outside);
    rem = clipConvex(rem, e);
    if (!rem.length) break;
  }
  return pieces;
}

function createSurfaceBuilder() {
  const positions = [], normals = [], uvs = [];
  const push = (p, n, uv) => {
    positions.push(p[0], p[1], p[2]);
    normals.push(n[0], n[1], n[2]);
    uvs.push(uv[0], uv[1]);
  };
  const addTri = (a, b, c, uvA, uvB, uvC) => {
    const e1x = b[0] - a[0], e1y = b[1] - a[1], e1z = b[2] - a[2];
    const e2x = c[0] - a[0], e2y = c[1] - a[1], e2z = c[2] - a[2];
    const nx = e1y * e2z - e1z * e2y, ny = e1z * e2x - e1x * e2z, nz = e1x * e2y - e1y * e2x;
    const area2 = Math.hypot(nx, ny, nz);
    if (!(area2 > 1e-8)) return;
    const n = [nx / area2, ny / area2, nz / area2];
    push(a, n, uvA); push(b, n, uvB); push(c, n, uvC);
  };
  const addOrientedTri = (a, b, c, uvA, uvB, uvC, targetN) => {
    const e1x = b[0] - a[0], e1y = b[1] - a[1], e1z = b[2] - a[2];
    const e2x = c[0] - a[0], e2y = c[1] - a[1], e2z = c[2] - a[2];
    const nx = e1y * e2z - e1z * e2y, ny = e1z * e2x - e1x * e2z, nz = e1x * e2y - e1y * e2x;
    if (nx * targetN[0] + ny * targetN[1] + nz * targetN[2] < 0) addTri(a, c, b, uvA, uvC, uvB);
    else addTri(a, b, c, uvA, uvB, uvC);
  };
  const addOrientedPoly = (pts, uvList, targetN) => {
    for (let i = 1; i + 1 < pts.length; i++) {
      addOrientedTri(pts[0], pts[i], pts[i + 1], uvList[0], uvList[i], uvList[i + 1], targetN);
    }
  };
  const build = THREE => {
    if (!positions.length) return null;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
    return geometry;
  };
  return { addTri, addOrientedTri, addOrientedPoly, build };
}

/** Precompute shared underside layout once per awning. Returns null when absent/exposed with no closed ends. */
export function prepareUnderside(roof, ctx = {}) {
  if (!isSupported(roof)) return null;
  const hasFlat = roof.underside?.kind === 'flat';
  const endsObj = roof.ends;
  const hasAnyClosedKey = !!endsObj && Object.values(endsObj).includes('closed');
  if (!hasFlat && !hasAnyClosedKey) return null;

  const area = canonicalArea(roof);
  if (area.length < 3) return null;
  const n = area.length;
  const edges = ctx?.recordEdges || roof.edges;
  const orient = signedArea(area) >= 0 ? 1 : -1;
  const outs = area.map((a, i) => {
    const b = area[(i + 1) % n];
    const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
    return [dy * orient / len, -dx * orient / len];
  });
  const localSection = unrotatedSection(roof, area, edges);
  const localPlanes = planes(localSection);
  const thickness = roof.thickness_ft ?? ROOF_THICKNESS;
  const planeTopLocal = (x, y) => Math.min(...localPlanes.map(p => p[0] * x + p[1] * y + p[2]));
  const slabBotLocal = (x, y) => {
    if (typeof ctx?.slabBottomAt === 'function') {
      const [bx, by] = roofPoint(roof, [x, y]);
      const v = ctx.slabBottomAt(bx, by);
      if (Number.isFinite(v)) return v;
    }
    return planeTopLocal(x, y) - thickness;
  };
  const slabTopLocal = (x, y) => slabBotLocal(x, y) + thickness;

  const hostEdge = Number.isInteger(roof.host?.edge) && roof.host.edge >= 0 && roof.host.edge < n ? roof.host.edge : -1;
  const isHost = Array.from({ length: n }, (_, i) => i === hostEdge);
  const isSlopedEave = Array.from({ length: n }, (_, i) => {
    if (localSection.kind === 'flat') return false;
    const a = area[i], b = area[(i + 1) % n];
    const mid = [(a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5];
    const zMid = planeTopLocal(mid[0], mid[1]);
    return localPlanes.some(pl =>
      Math.abs(pl[0] * mid[0] + pl[1] * mid[1] + pl[2] - zMid) < 1e-4
      && pl[0] * outs[i][0] + pl[1] * outs[i][1] < -1e-6);
  });
  const isClosedEnd = Array.from({ length: n }, (_, i) =>
    !isHost[i] && !isSlopedEave[i] && roof.ends?.[String(i)] === 'closed');
  if (!hasFlat && !isClosedEnd.some(Boolean)) return null;

  const hasAnySloped = isSlopedEave.some(Boolean);
  const hasExplicitSloped = Array.isArray(edges) && edges.some(e => e?.setting === 'sloped');
  const isFrontEave = Array.from({ length: n }, (_, i) => {
    if (isHost[i]) return false;
    if (hasAnySloped) return isSlopedEave[i];
    if (isClosedEnd[i]) return false;
    if (hostEdge >= 0) return outs[i][0] * outs[hostEdge][0] + outs[i][1] * outs[hostEdge][1] < -0.99;
    return hasExplicitSloped ? edges?.[i]?.setting === 'sloped' : true;
  });
  const hasAnyOpenEnd = Array.from({ length: n }, (_, i) =>
    !isHost[i] && !isSlopedEave[i] && !isFrontEave[i] && !isClosedEnd[i]).some(Boolean);

  const rawDrop = roof.underside?.drop_ft;
  const dropFt = hasFlat && Number.isFinite(rawDrop) ? Math.max(0, Math.min(3, rawDrop)) : 0;

  let wFace = 0;
  if (hostEdge >= 0 && typeof ctx?.wallFaceAt === 'function') {
    const a = area[hostEdge], b = area[(hostEdge + 1) % n];
    const mid = [(a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5];
    const inwardLocal = [-outs[hostEdge][0], -outs[hostEdge][1]];
    const midB = roofPoint(roof, mid);
    const inwardB = rotateDir(roof, inwardLocal);
    const raw = ctx.wallFaceAt(midB[0], midB[1], inwardB);
    const maxDepth = Math.max(...area.map(p => (p[0] - mid[0]) * inwardLocal[0] + (p[1] - mid[1]) * inwardLocal[1]));
    if (Number.isFinite(raw) && raw > 0 && raw < maxDepth - 0.15) wFace = raw;
  }

  const baseOffsets = Array.from({ length: n }, (_, i) =>
    isHost[i] ? -wFace : (edges?.[i]?.overhang_ft ?? roof.overhang ?? 0));
  const drawnPoly = offsetPolygon(area, outs, baseOffsets);

  let lowestSlabBot = Infinity, maxSlabBot = -Infinity;
  for (let i = 0; i < n; i++) {
    const p = drawnPoly[i], q = drawnPoly[(i + 1) % n];
    const a = slabBotLocal(p[0], p[1]), m = slabBotLocal((p[0] + q[0]) * 0.5, (p[1] + q[1]) * 0.5);
    lowestSlabBot = Math.min(lowestSlabBot, a, m);
    maxSlabBot = Math.max(maxSlabBot, a, m);
  }
  const ceilingZ = lowestSlabBot - dropFt;
  const endBottomZ = hasFlat ? ceilingZ : lowestSlabBot;

  const isFramedShedEnd = Array.from({ length: n }, (_, i) => {
    if (!isClosedEnd[i] || localSection.kind !== 'shed') return false;
    const p = drawnPoly[i], q = drawnPoly[(i + 1) % n];
    return Math.abs(slabTopLocal(p[0], p[1]) - slabTopLocal(q[0], q[1])) > 1e-3;
  });

  return {
    area, n, orient, outs, localSection, localPlanes, thickness,
    planeTopLocal, slabBotLocal, slabTopLocal,
    hostEdge, isHost, isSlopedEave, isClosedEnd, isFrontEave, isFramedShedEnd, hasAnyOpenEnd,
    hasFlat, dropFt, baseOffsets, drawnPoly, lowestSlabBot, maxSlabBot, ceilingZ, endBottomZ,
  };
}

/** Horizontal flat-ceiling height in building feet, or null when underside is exposed. */
export function undersideCeilingHeight(roof, ctx = {}) {
  const prep = ctx?._prepared !== undefined ? ctx._prepared : prepareUnderside(roof, ctx);
  return prep && prep.hasFlat && Number.isFinite(prep.ceilingZ) ? prep.ceilingZ : null;
}

function edgeProfileBreaks(P, Q, localPlanes) {
  const dx = Q[0] - P[0], dy = Q[1] - P[1];
  const lines = localPlanes.map(pl => [pl[0] * dx + pl[1] * dy, pl[0] * P[0] + pl[1] * P[1] + pl[2]]);
  const ts = [0, 1];
  for (let i = 0; i < lines.length; i++) {
    for (let j = i + 1; j < lines.length; j++) {
      const dm = lines[i][0] - lines[j][0];
      if (Math.abs(dm) > 1e-8) {
        const t = (lines[j][1] - lines[i][1]) / dm;
        if (t > 1e-5 && t < 1 - 1e-5) ts.push(t);
      }
    }
  }
  ts.sort((a, b) => a - b);
  const uniq = [];
  for (const t of ts) if (!uniq.length || t - uniq[uniq.length - 1] > 1e-5) uniq.push(t);
  return uniq;
}

/** Build flat ceiling, front drop face, and closed end geometries for a supported roof. */
export function undersideGeometry(roof, ctx) {
  const prep = ctx?._prepared !== undefined ? ctx._prepared : prepareUnderside(roof, ctx);
  if (!prep) return [];
  const {
    n, orient, outs, localSection, localPlanes, thickness,
    slabBotLocal, slabTopLocal, isClosedEnd, isFrontEave, isFramedShedEnd, hasAnyOpenEnd,
    hasFlat, dropFt, baseOffsets, drawnPoly, maxSlabBot, ceilingZ, endBottomZ,
  } = prep;
  if (!hasFlat && !isClosedEnd.some(Boolean)) return [];

  const { THREE } = ctx;
  const bare = roof.fascia === false;
  const frontProud = bare ? 0 : FASCIA.proudFt;
  const frontTopAt = (x, y) => bare ? slabBotLocal(x, y) : (slabTopLocal(x, y) - FASCIA.depthFt);

  const hasFrontDrop = Array.from({ length: n }, (_, i) => {
    if (!hasFlat || !(dropFt > 0) || !isFrontEave[i]) return false;
    const a = drawnPoly[i], b = drawnPoly[(i + 1) % n];
    return Math.max(frontTopAt(a[0], a[1]), frontTopAt(b[0], b[1])) > ceilingZ + 1e-5;
  });

  // Outer fascia-aligned polygon: aligns framed shed ends with the rake fascia plane (+0.01)
  // and front eaves with the front fascia plane (+0.01) so corners miter seamlessly with 0 step.
  const eaveTouchesFramedEnd = i => isFrontEave[i] && (isFramedShedEnd[(i - 1 + n) % n] || isFramedShedEnd[(i + 1) % n]);
  const outerOffsets = baseOffsets.map((off, i) =>
    off + (hasFrontDrop[i] || isFramedShedEnd[i] || (!bare && eaveTouchesFramedEnd(i)) ? frontProud : 0));
  const outerPoly = offsetPolygon(prep.area, outs, outerOffsets);

  const ceilOffsets = baseOffsets.map((off, i) =>
    off + (hasFrontDrop[i] || isFramedShedEnd[i] ? frontProud : 0));
  const ceilPoly = offsetPolygon(prep.area, outs, ceilOffsets);

  const toWorld3 = (x, y, z) => {
    const [bx, by] = roofPoint(roof, [x, y]);
    return [bx, z, -by];
  };
  const worldNormal2 = dir2 => {
    const r = rotateDir(roof, dir2);
    const l = Math.hypot(r[0], r[1]) || 1;
    return [r[0] / l, 0, -r[1] / l];
  };

  const parts = [];

  // 1. Flat horizontal ceiling facing down (slot: underside, part: underside).
  // When any non-host, non-eave end is open, include an upward copy at +0.01 ft so the cavity interior is solid.
  if (hasFlat) {
    const contour = ceilPoly.map(p => new THREE.Vector2(p[0], p[1]));
    const tris = THREE.ShapeUtils.triangulateShape(contour, []).map(idx => idx.map(k => ceilPoly[k]));
    let pieces = tris;
    if (Array.isArray(ctx?.cuts) && ctx.cuts.length) {
      const localCuts = ctx.cuts.map(poly => poly.map(p => roofPoint(roof, p, true)));
      for (const cut of localCuts) pieces = pieces.flatMap(tri => subtractConvex(tri, cut));
    }
    const minX = Math.min(...ceilPoly.map(p => p[0])), minY = Math.min(...ceilPoly.map(p => p[1]));
    const emitUpBack = hasAnyOpenEnd && maxSlabBot > ceilingZ + BACK_OFFSET_FT * 2;
    const builder = createSurfaceBuilder();
    for (const poly of pieces) {
      for (let i = 1; i + 1 < poly.length; i++) {
        let a = poly[0], b = poly[i], c = poly[i + 1];
        const area2 = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
        if (Math.abs(area2) <= 1e-8) continue;
        if (area2 > 0) [b, c] = [c, b]; // CW in plan -> downward normal (0, -1, 0)
        const uvA = [a[0] - minX, a[1] - minY], uvB = [b[0] - minX, b[1] - minY], uvC = [c[0] - minX, c[1] - minY];
        builder.addTri(
          toWorld3(a[0], a[1], ceilingZ), toWorld3(b[0], b[1], ceilingZ), toWorld3(c[0], c[1], ceilingZ),
          uvA, uvB, uvC,
        );
        if (emitUpBack) {
          const zBack = ceilingZ + BACK_OFFSET_FT;
          builder.addTri(
            toWorld3(a[0], a[1], zBack), toWorld3(c[0], c[1], zBack), toWorld3(b[0], b[1], zBack),
            uvA, uvC, uvB,
          );
        }
      }
    }
    const geometry = builder.build(THREE);
    if (geometry) parts.push({ geometry, slot: 'underside', part: 'underside' });
  }

  // Emit a vertical strip along outward-right segment A -> B from zBot up to [zTopA, zTopB]
  const emitVerticalStrip = (builder, A, B, zBot, zTopA, zTopB, uStart, uEnd) => {
    const hA = zTopA - zBot, hB = zTopB - zBot;
    if (hA <= 1e-5 && hB <= 1e-5) return;
    const pA0 = toWorld3(A[0], A[1], zBot), pB0 = toWorld3(B[0], B[1], zBot);
    const pA1 = toWorld3(A[0], A[1], Math.max(zBot, zTopA)), pB1 = toWorld3(B[0], B[1], Math.max(zBot, zTopB));
    if (hA > 1e-5 && hB > 1e-5) {
      builder.addTri(pA0, pB0, pB1, [uStart, 0], [uEnd, 0], [uEnd, hB]);
      builder.addTri(pA0, pB1, pA1, [uStart, 0], [uEnd, hB], [uStart, hA]);
    } else if (hB > 1e-5) {
      builder.addTri(pA0, pB0, pB1, [uStart, 0], [uEnd, 0], [uEnd, hB]);
    } else {
      builder.addTri(pA0, pB0, pA1, [uStart, 0], [uEnd, 0], [uStart, hA]);
    }
  };

  // 2. Front fascia continuation along each eave when drop_ft > 0 (slot: fascia, part: underside:front).
  // Also seals the 0.01 ft front-plane miter corner next to any framed closed shed end so no corner sliver shows.
  if (hasFrontDrop.some(Boolean)) {
    const builder = createSurfaceBuilder();
    for (let i = 0; i < n; i++) {
      if (!hasFrontDrop[i]) continue;
      const i0 = orient > 0 ? i : (i + 1) % n;
      const i1 = orient > 0 ? (i + 1) % n : i;
      const P = outerPoly[i0], Q = outerPoly[i1];
      const dP = drawnPoly[i0], dQ = drawnPoly[i1];
      const baseP = [dP[0] + outs[i][0] * frontProud, dP[1] + outs[i][1] * frontProud];
      const baseQ = [dQ[0] + outs[i][0] * frontProud, dQ[1] + outs[i][1] * frontProud];
      const len = Math.hypot(Q[0] - P[0], Q[1] - P[1]);
      if (!(len > 1e-5)) continue;
      // Main span below existing fascia (continuous across outerPoly[i0]..outerPoly[i1])
      const breaks = edgeProfileBreaks(dP, dQ, localPlanes);
      for (let k = 0; k + 1 < breaks.length; k++) {
        const t0 = breaks[k], t1 = breaks[k + 1];
        const A = [P[0] + t0 * (Q[0] - P[0]), P[1] + t0 * (Q[1] - P[1])];
        const B = [P[0] + t1 * (Q[0] - P[0]), P[1] + t1 * (Q[1] - P[1])];
        const dA = [dP[0] + t0 * (dQ[0] - dP[0]), dP[1] + t0 * (dQ[1] - dP[1])];
        const dB = [dP[0] + t1 * (dQ[0] - dP[0]), dP[1] + t1 * (dQ[1] - dP[1])];
        emitVerticalStrip(builder, A, B, ceilingZ, frontTopAt(dA[0], dA[1]), frontTopAt(dB[0], dB[1]), t0 * len, t1 * len);
      }
      // Upper 0.01 ft front-face miter strips alongside existing front fascia where framed ends meet this eave
      if (!bare && frontProud > 0) {
        const mStart = Math.hypot(baseP[0] - P[0], baseP[1] - P[1]);
        if (mStart > 1e-5) {
          const zLo = Math.max(ceilingZ, frontTopAt(dP[0], dP[1])), zHi = slabTopLocal(dP[0], dP[1]);
          emitVerticalStrip(builder, P, baseP, zLo, zHi, zHi, 0, mStart);
        }
        const mEnd = Math.hypot(Q[0] - baseQ[0], Q[1] - baseQ[1]);
        if (mEnd > 1e-5) {
          const zLo = Math.max(ceilingZ, frontTopAt(dQ[0], dQ[1])), zHi = slabTopLocal(dQ[0], dQ[1]);
          emitVerticalStrip(builder, baseQ, Q, zLo, zHi, zHi, len - mEnd, len);
        }
      }
    }
    const geometry = builder.build(THREE);
    if (geometry) parts.push({ geometry, slot: 'fascia', part: 'underside:front' });
  }

  // 3. Closed ends (part: end:<edge>).
  // Shed sloped ends get a 0.08 ft recessed panel framed by sloped top, horizontal bottom, and front vertical boards.
  const shedPanelSlot = ctx?.sidingIsBatten ? 'fascia' : 'siding';
  for (let i = 0; i < n; i++) {
    if (!isClosedEnd[i]) continue;
    const i0 = orient > 0 ? i : (i + 1) % n;
    const i1 = orient > 0 ? (i + 1) % n : i;
    const dP = drawnPoly[i0], dQ = drawnPoly[i1];
    const outN2 = outs[i], outN3 = worldNormal2(outN2), inN3 = [-outN3[0], 0, -outN3[2]];

    if (isFramedShedEnd[i]) {
      const oP = outerPoly[i0], oQ = outerPoly[i1];
      const lowAtStart = slabTopLocal(dP[0], dP[1]) < slabTopLocal(dQ[0], dQ[1]);
      const E_low = lowAtStart ? oP : oQ, E_high = lowAtStart ? oQ : oP;
      const D_low = lowAtStart ? dP : dQ, D_high = lowAtStart ? dQ : dP;
      const L = Math.hypot(E_high[0] - E_low[0], E_high[1] - E_low[1]);
      if (!(L > 1e-5)) continue;
      const dirS = [(E_high[0] - E_low[0]) / L, (E_high[1] - E_low[1]) / L];
      const dLen = Math.hypot(D_high[0] - D_low[0], D_high[1] - D_low[1]) || 1;
      const sMiter = Math.max(0, (D_low[0] - E_low[0]) * dirS[0] + (D_low[1] - E_low[1]) * dirS[1]);

      const zTop0 = slabTopLocal(D_low[0], D_low[1]);
      const zTopL = slabTopLocal(D_high[0], D_high[1]);
      const zTopAt = s => s <= sMiter ? zTop0 : zTop0 + (zTopL - zTop0) * Math.min(1, (s - sMiter) / dLen);
      const zSlabBotAt = s => zTopAt(s) - thickness;
      const zFrameRoofAt = s => bare ? zSlabBotAt(s) : zTopAt(s);
      const zBot = endBottomZ;
      const sSlope = (zTopL - zTop0) / dLen;

      const H_front = Math.max(0, zTop0 - zBot);
      const H_wall = Math.max(0, zTopL - zBot);
      const totalArea = dLen * (H_front + H_wall) * 0.5;
      const boardW = Math.min(0.35, 0.22 * H_wall);
      // Keep the recessed panel strictly at or below zSlabBotAt so it never crosses the roof slab.
      const topHMin = (!hasFlat || hasAnyOpenEnd) ? thickness : Math.min(thickness, 0.14);
      const evalOpening = (tH, bH, wF) => {
        const zBT = zBot + bH;
        const zRT = s => Math.min(zTopAt(s) - tH, zSlabBotAt(s));
        let sS = Math.max(sMiter, wF);
        if (zRT(sS) < zBT) {
          sS = sSlope > 1e-6 ? sMiter + (zBT - zRT(sMiter)) / sSlope : L;
        }
        sS = Math.max(Math.max(sMiter, wF), Math.min(L, sS));
        const zOF = zRT(sS), zOW = zRT(L);
        if (!(L - sS > 0.05 && zOW > zBT + 0.05)) return { R: [], area: 0, sS, zBT, zOF, zOW, zRT };
        const pts = [[sS, zBT], [L, zBT], [L, zOW]];
        if (zOF > zBT + 1e-4) pts.push([sS, zOF]);
        const area = (L - sS) * (Math.max(0, zOF - zBT) + (zOW - zBT)) * 0.5;
        return { R: pts, area, sS, zBT, zOF, zOW, zRT };
      };

      const baseTopH = Math.max(topHMin, boardW);
      const baseBotH = Math.min(boardW, Math.max(0.08, H_front * 0.65));
      const baseWFront = Math.max(sMiter, Math.min(boardW, H_front / 3, L * 0.25));
      let opening = evalOpening(baseTopH, baseBotH, baseWFront);
      let topBoardH = baseTopH, botBoardH = baseBotH, wFront = baseWFront;
      // Guarantee the recessed panel keeps at least 45% of the end's area when geometrically feasible.
      if (totalArea > 1e-4 && opening.area < 0.45 * totalArea) {
        let lo = 0.2, hi = 1.0;
        for (let iter = 0; iter < 14; iter++) {
          const mid = (lo + hi) * 0.5;
          const tryT = Math.max(topHMin, baseTopH * mid);
          const tryB = Math.max(0.06, baseBotH * mid);
          const tryW = Math.max(sMiter, baseWFront * mid);
          if (evalOpening(tryT, tryB, tryW).area >= 0.455 * totalArea) lo = mid;
          else hi = mid;
        }
        topBoardH = Math.max(topHMin, baseTopH * lo);
        botBoardH = Math.max(0.06, baseBotH * lo);
        wFront = Math.max(sMiter, baseWFront * lo);
        opening = evalOpening(topBoardH, botBoardH, wFront);
      }

      const { R, sS: sOpenStart, zBT: zBotTop, zOF: zOpenFront, zOW: zOpenWall, zRT: zRecTopAt } = opening;
      const pt3 = (s, z, depth = 0) => toWorld3(
        E_low[0] + dirS[0] * s - outN2[0] * depth,
        E_low[1] + dirS[1] * s - outN2[1] * depth,
        z,
      );
      const frameBuilder = createSurfaceBuilder();
      const panelBuilder = shedPanelSlot === 'fascia' ? frameBuilder : createSurfaceBuilder();
      const addSZPoly = (builder, szPts, depth, normal3) => {
        if (szPts.length < 3) return;
        builder.addOrientedPoly(
          szPts.map(([s, z]) => pt3(s, z, depth)),
          szPts.map(([s, z]) => [s, z - zBot]),
          normal3,
        );
      };

      // Close front-face 0.01 ft corner miter if no underside:front was emitted (drop_ft = 0 or exposed).
      if (sMiter > 1e-5 && zTop0 > zBot + 1e-5) {
        const adjEave = lowAtStart ? (i0 - 1 + n) % n : i1;
        if (!bare && isFrontEave[adjEave] && !hasFrontDrop[adjEave]) {
          const eaveN3 = worldNormal2(outs[adjEave]);
          const eP = pt3(0, zBot, 0), eQ = pt3(0, zBot, frontProud);
          const eQ1 = pt3(0, zTop0, frontProud), eP1 = pt3(0, zTop0, 0);
          frameBuilder.addOrientedPoly([eP, eQ, eQ1, eP1], [[0, 0], [frontProud, 0], [frontProud, zTop0 - zBot], [0, zTop0 - zBot]], eaveN3);
        }
      }

      // Emit a clean non-overlapping vertical strip on depth=0 over [sA, sB] between [zLo, min(zHiCap, zFrameRoofAt(s))]
      const emitFrameBand = (sA, sB, zLo, zHiCap) => {
        if (!(sB - sA > 1e-5)) return;
        const splits = [sA, sB];
        if (sMiter > sA + 1e-5 && sMiter < sB - 1e-5) splits.push(sMiter);
        if (sSlope > 1e-6) {
          for (const target of [zLo, zHiCap]) {
            if (!Number.isFinite(target)) continue;
            const sc = sMiter + (target - zFrameRoofAt(sMiter)) / sSlope;
            if (sc > sA + 1e-5 && sc < sB - 1e-5) splits.push(sc);
          }
        }
        splits.sort((a, b) => a - b);
        for (let k = 0; k + 1 < splits.length; k++) {
          const u0 = splits[k], u1 = splits[k + 1];
          if (!(u1 - u0 > 1e-6)) continue;
          const t0 = Math.min(zHiCap, zFrameRoofAt(u0)), t1 = Math.min(zHiCap, zFrameRoofAt(u1));
          if (t0 <= zLo + 1e-5 && t1 <= zLo + 1e-5) continue;
          const pts = [[u0, zLo], [u1, zLo]];
          if (t1 > zLo + 1e-5) pts.push([u1, t1]);
          if (t0 > zLo + 1e-5) pts.push([u0, t0]);
          addSZPoly(frameBuilder, pts, 0, outN3);
        }
      };

      if (R.length >= 3) {
        // 1) Bottom horizontal board (continuous from s=0 front miter to wall, zero step with front face)
        emitFrameBand(0, L, zBot, zBotTop);
        // 2) Front vertical board above bottom board up to roof top (includes front miter strip)
        if (sOpenStart > 1e-5) emitFrameBand(0, sOpenStart, zBotTop, Infinity);
        // 3) Sloped top board above recessed opening up to roof top (complete board; generator skips default rake on framed ends)
        const zTopLoA = zRecTopAt(sOpenStart), zTopLoB = zRecTopAt(L);
        const zTopHiA = zFrameRoofAt(sOpenStart), zTopHiB = zFrameRoofAt(L);
        if (zTopHiA > zTopLoA + 1e-5 || zTopHiB > zTopLoB + 1e-5) {
          const topPts = [[sOpenStart, zTopLoA], [L, zTopLoB]];
          if (zTopHiB > zTopLoB + 1e-5) topPts.push([L, zTopHiB]);
          if (zTopHiA > zTopLoA + 1e-5) topPts.push([sOpenStart, zTopHiA]);
          addSZPoly(frameBuilder, topPts, 0, outN3);
        }
        // 4) Recessed panel at depth = SHED_RECESS_FT (0.15 ft)
        addSZPoly(panelBuilder, R, SHED_RECESS_FT, outN3);

        // 5) 0.15 ft deep watertight reveal return walls framing the recessed opening (skip wall edge s = L)
        const addRevealQuad = (aSZ, bSZ, normal3) => {
          const edgeLen = Math.hypot(bSZ[0] - aSZ[0], bSZ[1] - aSZ[1]);
          if (!(edgeLen > 1e-5)) return;
          frameBuilder.addOrientedPoly(
            [pt3(aSZ[0], aSZ[1], 0), pt3(bSZ[0], bSZ[1], 0), pt3(bSZ[0], bSZ[1], SHED_RECESS_FT), pt3(aSZ[0], aSZ[1], SHED_RECESS_FT)],
            [[0, 0], [edgeLen, 0], [edgeLen, SHED_RECESS_FT], [0, SHED_RECESS_FT]],
            normal3,
          );
        };
        // Bottom sill reveal (facing up +Y)
        addRevealQuad([sOpenStart, zBotTop], [L, zBotTop], [0, 1, 0]);
        // Front vertical jamb reveal (facing toward wall +dirS)
        if (R.length === 4) {
          addRevealQuad([sOpenStart, zBotTop], [sOpenStart, zOpenFront], worldNormal2(dirS));
        }
        // Sloped top soffit reveal (facing downward-inward perpendicular to roof slope)
        const topA = R.length === 4 ? [sOpenStart, zOpenFront] : [sOpenStart, zBotTop];
        const topB = [L, zOpenWall];
        const ds = topB[0] - topA[0], dz = topB[1] - topA[1], sl = Math.hypot(ds, dz) || 1;
        const dirSWorld = worldNormal2(dirS);
        const topRevealN = [dirSWorld[0] * (dz / sl), -ds / sl, dirSWorld[2] * (dz / sl)];
        addRevealQuad(topA, topB, topRevealN);
      } else {
        // Fallback for very small/shallow ends where no recess opening fits
        emitFrameBand(0, L, zBot, Infinity);
      }

      // Exposed underside: inward-facing copy strictly behind panel and strictly below slab underside (no crossing at any pitch)
      if (!hasFlat) {
        const zBack0 = zSlabBotAt(sMiter), zBackL = zSlabBotAt(L);
        const backPts = [[sMiter, zBot], [L, zBot]];
        if (zBackL > zBot + 1e-5) backPts.push([L, zBackL]);
        if (zBack0 > zBot + 1e-5) backPts.push([sMiter, zBack0]);
        addSZPoly(frameBuilder, backPts, SHED_RECESS_FT + BACK_OFFSET_FT, inN3);
      }

      const frameGeo = frameBuilder.build(THREE);
      if (frameGeo) parts.push({ geometry: frameGeo, slot: 'fascia', part: `end:${i}` });
      if (panelBuilder !== frameBuilder) {
        const panelGeo = panelBuilder.build(THREE);
        if (panelGeo) parts.push({ geometry: panelGeo, slot: shedPanelSlot, part: `end:${i}` });
      }
      continue;
    }

    // Standard closed end (gable, hip, flat, or horizontal high back of unhosted shed)
    const endSlot = ['gable', 'hip'].includes(localSection.kind) ? 'siding' : 'fascia';
    const len = Math.hypot(dQ[0] - dP[0], dQ[1] - dP[1]);
    if (!(len > 1e-5)) continue;
    const builder = createSurfaceBuilder();
    const breaks = edgeProfileBreaks(dP, dQ, localPlanes);
    for (let k = 0; k + 1 < breaks.length; k++) {
      const t0 = breaks[k], t1 = breaks[k + 1];
      const A = [dP[0] + t0 * (dQ[0] - dP[0]), dP[1] + t0 * (dQ[1] - dP[1])];
      const B = [dP[0] + t1 * (dQ[0] - dP[0]), dP[1] + t1 * (dQ[1] - dP[1])];
      const zA = slabBotLocal(A[0], A[1]), zB = slabBotLocal(B[0], B[1]);
      emitVerticalStrip(builder, A, B, endBottomZ, zA, zB, t0 * len, t1 * len);
      // Exposed underside: inward-facing copy offset 0.01 ft inward
      if (!hasFlat) {
        const iA = [A[0] - outN2[0] * BACK_OFFSET_FT, A[1] - outN2[1] * BACK_OFFSET_FT];
        const iB = [B[0] - outN2[0] * BACK_OFFSET_FT, B[1] - outN2[1] * BACK_OFFSET_FT];
        emitVerticalStrip(builder, iB, iA, endBottomZ, zB, zA, t1 * len, t0 * len);
      }
    }
    // Corner seal where a non-shed closed end meets a proud fascia front drop
    if (frontProud > 0) {
      const cP = ceilPoly[i0], cQ = ceilPoly[i1];
      const dStart = Math.hypot(cP[0] - dP[0], cP[1] - dP[1]);
      if (dStart > 1e-5) {
        const zSeal = slabTopLocal(dP[0], dP[1]);
        emitVerticalStrip(builder, cP, dP, endBottomZ, zSeal, zSeal, -dStart, 0);
      }
      const dEnd = Math.hypot(cQ[0] - dQ[0], cQ[1] - dQ[1]);
      if (dEnd > 1e-5) {
        const zSeal = slabTopLocal(dQ[0], dQ[1]);
        emitVerticalStrip(builder, dQ, cQ, endBottomZ, zSeal, zSeal, len, len + dEnd);
      }
    }
    const geometry = builder.build(THREE);
    if (geometry) parts.push({ geometry, slot: endSlot, part: `end:${i}` });
  }

  return parts;
}
