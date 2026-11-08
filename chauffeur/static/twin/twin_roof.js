// Roof geometry in plan feet, with z up. No renderer or browser dependencies.
const EPS = 1e-9;
const AREA_EPS = 1e-10;
const valueAt = (plane, x, y) => plane[0] * x + plane[1] * y + plane[2];

function bounds(section) {
  const [x0, y0, x1, y1] = section.rect;
  const overhang = section.overhang ?? 0;
  return [x0 - overhang, y0 - overhang, x1 + overhang, y1 + overhang];
}

function covers(rect, x, y) {
  return x >= rect[0] && y >= rect[1] && x <= rect[2] && y <= rect[3];
}

// A section is the minimum of its side planes, restricted to its footprint.
// Distances are signed: extending a plane past the plate lowers the eave.
function planes(section) {
  const [x0, y0, x1, y1] = section.rect;
  const plate = section.plate;
  const side = name => (section.pitches?.[name] ?? section.pitch) / 12;
  const edges = {
    x0: () => { const s = side('x0'); return [s, 0, plate - s * x0]; },
    x1: () => { const s = side('x1'); return [-s, 0, plate + s * x1]; },
    y0: () => { const s = side('y0'); return [0, s, plate - s * y0]; },
    y1: () => { const s = side('y1'); return [0, -s, plate + s * y1]; },
  };
  if (section.kind === 'flat') return [[0, 0, plate]];
  if (section.kind === 'shed') return [edges[section.low_side]()];
  const sides = section.kind === 'gable'
    ? (section.ridge === 'y' ? ['x0', 'x1'] : ['y0', 'y1'])
    : ['x0', 'x1', 'y0', 'y1'];
  return sides.map(name => edges[name]());
}

/** Height of one section, including its signed-slope overhang. */
export function sectionHeight(section, x, y) {
  if (!covers(bounds(section), x, y)) return null;
  return Math.min(...planes(section).map(plane => valueAt(plane, x, y)));
}

/** Upper envelope, including overhangs. */
export function heightAt(sections, x, y) {
  let height = null;
  for (const section of sections) {
    const z = sectionHeight(section, x, y);
    if (z !== null && (height === null || z > height)) height = z;
  }
  return height;
}

function rectangle([x0, y0, x1, y1]) {
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
}

function area(polygon) {
  let twice = 0;
  // Use a local origin to avoid cancellation for small, translated pieces.
  for (let i = 1; i + 1 < polygon.length; i++) {
    const a = polygon[0], b = polygon[i], c = polygon[i + 1];
    twice += (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  }
  return twice / 2;
}

// Keep a*x + b*y + c >= 0. Works in plan coordinates or local (u,z).
function clip(polygon, line) {
  if (!polygon.length) return [];
  const scale = Math.hypot(line[0], line[1]);
  if (scale === 0) return line[2] >= 0 ? polygon : [];
  const distance = point => {
    const d = valueAt(line, ...point) / scale;
    return Math.abs(d) < EPS ? 0 : d;
  };
  const result = [];
  let previous = polygon[polygon.length - 1], dp = distance(previous);
  for (const current of polygon) {
    const dc = distance(current);
    if ((dp < 0) !== (dc < 0)) {
      const t = dp / (dp - dc);
      result.push([previous[0] + t * (current[0] - previous[0]),
                   previous[1] + t * (current[1] - previous[1])]);
    }
    if (dc >= 0) result.push(current);
    previous = current;
    dp = dc;
  }
  // Boundary intersections can coincide with a retained endpoint.
  const clean = result.filter((p, i) => {
    const q = result[(i + result.length - 1) % result.length];
    return Math.hypot(p[0] - q[0], p[1] - q[1]) > EPS;
  });
  return area(clean) > AREA_EPS ? clean : [];
}

const opposite = line => line.map(v => -v);
const difference = (a, b) => a.map((v, i) => v - b[i]);
const samePlane = (a, b) => a.every((v, i) => Math.abs(v - b[i]) < EPS);

function insideEdges(polygon) {
  return polygon.map((p, i) => {
    const q = polygon[(i + 1) % polygon.length];
    return [p[1] - q[1], q[0] - p[0], q[1] * p[0] - q[0] * p[1]];
  });
}

// Convex minus convex: each outside slice is final, while the inside remainder
// proceeds to the next edge. The resulting convex pieces have disjoint interiors.
function subtract(polygon, cutter) {
  if (!cutter.length) return [polygon];
  const edges = insideEdges(cutter);
  let overlap = polygon;
  for (const edge of edges) overlap = clip(overlap, edge);
  if (!overlap.length) return [polygon];
  const pieces = [];
  let remainder = polygon;
  for (const edge of edges) {
    const outside = clip(remainder, opposite(edge));
    if (outside.length) pieces.push(outside);
    remainder = clip(remainder, edge);
    if (!remainder.length) break;
  }
  return pieces;
}

function sectionFaces(section, index) {
  const all = planes(section);
  const faces = [];
  for (let i = 0; i < all.length; i++) {
    if (all.slice(0, i).some(p => samePlane(p, all[i]))) continue;
    let polygon = rectangle(bounds(section));
    for (const plane of all) polygon = clip(polygon, difference(plane, all[i]));
    if (polygon.length) faces.push({ polygon, plane: all[i], section: index });
  }
  return faces;
}

function triangulate(polygon, pointAt, output, labels, section) {
  for (let i = 1; i + 1 < polygon.length; i++) {
    const triangle = [polygon[0], polygon[i], polygon[i + 1]];
    if (area(triangle) <= AREA_EPS) continue;
    for (const p of triangle) output.push(...pointAt(p));
    if (labels) labels.push(section);
  }
}

function gableEnds(sections, index) {
  const section = sections[index];
  const [x0, y0, x1, y1] = section.rect;
  const alongX = section.ridge !== 'y';
  const start = alongX ? y0 : x0;
  const width = alongX ? y1 - y0 : x1 - x0;
  const [first, second] = planes(section);
  const slope0 = alongX ? first[1] : first[0];
  const slope1 = -(alongX ? second[1] : second[0]);
  if (slope0 <= 0 || slope1 <= 0) return [];
  const apex = width * slope1 / (slope0 + slope1);
  const plate = section.plate;
  const positions = [];
  for (const end of (alongX ? [x0, x1] : [y0, y1])) {
    const xy = u => alongX ? [end, start + u] : [start + u, end];
    let pieces = [[[0, plate], [width, plate], [apex, plate + apex * slope0]]];
    for (let j = 0; j < sections.length; j++) {
      if (j === index) continue;
      const other = sections[j], rect = bounds(other);
      const fixedMin = alongX ? rect[0] : rect[1];
      const fixedMax = alongX ? rect[2] : rect[3];
      if (end < fixedMin || end > fixedMax) continue;
      const low = (alongX ? rect[1] : rect[0]) - start;
      const high = (alongX ? rect[3] : rect[2]) - start;
      const cutters = [[1, 0, -low], [-1, 0, high]];
      // Solid below the other roof: z <= every side plane at this wall.
      for (const plane of planes(other)) {
        cutters.push([alongX ? plane[1] : plane[0], -1, valueAt(plane, ...xy(0))]);
      }
      pieces = pieces.flatMap(piece => {
        let cutter = piece;
        for (const line of cutters) cutter = clip(cutter, line);
        return subtract(piece, cutter);
      });
    }
    for (const piece of pieces) {
      const local = [];
      triangulate(piece, ([u, z]) => [...xy(u), z], local);
      // Local (u,z) orientation points out of opposite ends differently.
      const reverse = alongX ? end === x0 : end === y1;
      for (let i = 0; i < local.length; i += 9) {
        positions.push(...local.slice(i, i + 3));
        positions.push(...local.slice(i + (reverse ? 6 : 3), i + (reverse ? 9 : 6)));
        positions.push(...local.slice(i + (reverse ? 3 : 6), i + (reverse ? 6 : 9)));
      }
    }
  }
  return positions;
}

/** Vertical drops of the upper envelope, facing the lower roof. Free edges
 * have no lower roof and are left to the roof shell. Convex exclusions use
 * the same per-section convention as roofMesh (occupied upper floors). */
export function stepFaces(sections, { section: only = null, exclude = [], wallCover = () => [] } = {}) {
  const rects = sections.map(bounds), allPlanes = sections.map(planes), positions = [];
  sections.forEach((section, index) => {
    if (only !== null && only !== index) return;
    const rect = rects[index];
    for (let axis = 0; axis < 2; axis++) for (const sign of [-1, 1]) {
      // Rake ends are closed at the wall line by gableEnds, beneath their
      // overhang. Do not put another gable out at the roof's outer edge.
      if (section.kind === 'gable' && axis === (section.ridge === 'y' ? 1 : 0)) continue;
      const along = 1 - axis, end = rect[axis + (sign > 0 ? 2 : 0)];
      const lo = rect[along], hi = rect[along + 2];
      const xy = u => axis === 0 ? [end, u] : [u, end];
      // On each interval every covering side-plane and envelope winner is
      // fixed. Include all plane exchanges, not just the section corners.
      const lines = allPlanes.flat().map(p => [p[along], p[axis] * end + p[2]]);
      const cuts = [lo, hi, ...rects.flatMap(r => [r[along], r[along + 2]])];
      for (let i = 0; i < lines.length; i++) for (let j = 0; j < i; j++) {
        const slope = lines[i][0] - lines[j][0];
        if (Math.abs(slope) > EPS) cuts.push((lines[j][1] - lines[i][1]) / slope);
      }
      const sorted = [...new Set(cuts.filter(u => u >= lo && u <= hi))].sort((a, b) => a - b);
      const winner = (u, outward) => {
        let best = null;
        rects.forEach((r, j) => {
          if (u <= r[along] || u >= r[along + 2] || end < r[axis] || end > r[axis + 2]) return;
          const direction = outward ? sign : -sign;
          if ((direction < 0 && end <= r[axis]) || (direction > 0 && end >= r[axis + 2])) return;
          const z = Math.min(...allPlanes[j].map(p => valueAt(p, ...xy(u))));
          if (!best || z > best.z + EPS) best = { index: j, z };
        });
        return best;
      };
      for (let i = 0; i + 1 < sorted.length; i++) {
        let a = sorted[i], b = sorted[i + 1];
        if (b - a < EPS) continue;
        const mid = (a + b) / 2, upper = winner(mid, false), lower = winner(mid, true);
        if (upper?.index !== index || !lower) continue;
        const height = (j, u) => Math.min(...allPlanes[j].map(p => valueAt(p, ...xy(u))));
        const gap = u => height(index, u) - height(lower.index, u);
        // Retain only the portion whose drop exceeds the step tolerance.
        const ga = gap(a), gb = gap(b);
        if (Math.max(ga, gb) <= 0.05) continue;
        if (ga < 0.05) a += (b - a) * (0.05 - ga) / (gb - ga);
        else if (gb < 0.05) b = a + (b - a) * (ga - 0.05) / (ga - gb);
        let pieces = [[[a, height(lower.index, a)], [b, height(lower.index, b)],
          [b, height(index, b)], [a, height(index, a)]]];
        for (const cutter of exclude[index] || []) {
          // Restrict the plan cutter to this vertical boundary plane.
          const lines = insideEdges(cutter).map(p => [p[along], 0, p[axis] * end + p[2]]);
          pieces = pieces.flatMap(piece => {
            let overlap = piece;
            for (const line of lines) overlap = clip(overlap, line);
            return subtract(piece, overlap);
          });
        }
        // Existing supporting walls (including their windows) own these
        // spans. Their overhang stays open below the soffit, not curtained
        // off by siding projected forward from the wall.
        for (const cutter of wallCover(index, axis, sign, end)) {
          pieces = pieces.flatMap(piece => subtract(piece, cutter));
        }
        for (const piece of pieces) {
          const local = [];
          triangulate(piece, ([u, z]) => [...xy(u), z], local);
          const reverse = axis === 0 ? sign < 0 : sign > 0;
          for (let t = 0; t < local.length; t += 9) {
            positions.push(...local.slice(t, t + 3),
              ...local.slice(t + (reverse ? 6 : 3), t + (reverse ? 9 : 6)),
              ...local.slice(t + (reverse ? 3 : 6), t + (reverse ? 6 : 9)));
          }
        }
      }
    }
  });
  return new Float32Array(positions);
}

/** Upper envelope and gable ends; optionally retain lower roofs. Per-section
 * convex exclusions cut only retained pieces below the visible envelope. */
export function roofMesh(sections, { retainLower = false, exclude = [] } = {}) {
  const faces = sections.flatMap(sectionFaces);
  const positions = [], labels = [], gables = [];
  for (const face of faces) {
    let pieces = [face.polygon];
    for (const other of faces) {
      if (other.section === face.section) continue;
      let cutter;
      if (samePlane(other.plane, face.plane)) {
        // Deterministic ownership of coincident surfaces prevents z-fighting.
        if (other.section > face.section) continue;
        cutter = other.polygon;
      } else {
        if (retainLower) continue;
        cutter = clip(other.polygon, difference(other.plane, face.plane));
      }
      if (cutter.length) pieces = pieces.flatMap(piece => subtract(piece, cutter));
      if (!pieces.length) break;
    }
    const cutters = exclude[face.section] || [];
    if (retainLower && cutters.length) {
      // Coplanar ownership is already resolved. Apply the normal envelope
      // cut to find the visible pieces, which occupied floors must not erase.
      let envelopePieces = pieces;
      for (const other of faces) {
        if (other.section === face.section || samePlane(other.plane, face.plane)) continue;
        const cutter = clip(other.polygon, difference(other.plane, face.plane));
        if (cutter.length) envelopePieces = envelopePieces.flatMap(piece => subtract(piece, cutter));
        if (!envelopePieces.length) break;
      }
      let remainder = pieces;
      for (const piece of envelopePieces) {
        remainder = remainder.flatMap(lower => subtract(lower, piece));
      }
      for (const cutter of cutters) {
        remainder = remainder.flatMap(piece => subtract(piece, cutter));
      }
      pieces = [...envelopePieces, ...remainder];
    }
    for (const piece of pieces) {
      triangulate(piece, ([x, y]) => [x, y, valueAt(face.plane, x, y)], positions, labels, face.section);
    }
  }
  sections.forEach((section, index) => {
    if (section.kind !== 'gable') return;
    const ends = gableEnds(sections, index);
    if (ends.length) gables.push({ section: index, positions: new Float32Array(ends) });
  });
  return { positions: new Float32Array(positions), section: new Int32Array(labels), gables };
}
