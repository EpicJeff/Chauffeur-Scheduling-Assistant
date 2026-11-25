// Roof geometry in plan feet, with z up. No renderer or browser dependencies.
import { isSupported, roofPoint } from './roof_supports.js';

const EPS = 1e-9;
const AREA_EPS = 1e-10;
const valueAt = (plane, x, y) => plane[0] * x + plane[1] * y + plane[2];

// Indexed choices and their outline must always come from the same record.
// Plane form/heights remain derived from the partition section.
export function authoredRoofShape(record, section) {
  return record?.area ? { ...record, ...section, area: record.area,
    host: record.host, ends: record.ends, edges: record.edges, underside: record.underside } : section;
}

// Port of twin_model_roofs._rectangle_edge_indices: longest positive overlap,
// with the lower authored edge index breaking ties. Do not infer from winding.
export function rectangleEdgeIndices(area, rect) {
  const [x0, y0, x1, y1] = rect, points = [[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
  const edge = (a, b) => {
    const axis = Math.abs(a[0] - b[0]) <= 1e-8 ? 0 : 1;
    return [axis, a[axis], Math.min(a[1-axis], b[1-axis]), Math.max(a[1-axis], b[1-axis])];
  };
  return Object.fromEntries(['y0','x1','y1','x0'].map((side, j) => {
    const [axis, line, start, end] = edge(points[j], points[(j+1)%4]);
    let best = null, length = 1e-8;
    area.forEach((p, i) => {
      const [other, value, lo, hi] = edge(p, area[(i+1)%area.length]);
      const overlap = Math.min(end, hi) - Math.max(start, lo);
      if (axis === other && Math.abs(value-line) <= 1e-8 && overlap > length) { best = i; length = overlap; }
    });
    return [side, best];
  }));
}

export function roofBounds(section) {
  if (section.roof_frame) {
    const r=roofBounds({...section,roof_frame:null});
    const p=[[r[0],r[1]],[r[2],r[1]],[r[2],r[3]],[r[0],r[3]]].map(p=>roofPoint(section,p));
    return [Math.min(...p.map(p=>p[0])),Math.min(...p.map(p=>p[1])),Math.max(...p.map(p=>p[0])),Math.max(...p.map(p=>p[1]))];
  }
  const [x0, y0, x1, y1] = section.rect;
  const overhang = section.overhang ?? 0;
  if (!section.edges) return [x0 - overhang, y0 - overhang, x1 + overhang, y1 + overhang];
  const edge = index => section.edges?.[index]?.overhang_ft ?? overhang;
  return [x0 - edge(3), y0 - edge(0), x1 + edge(1), y1 + edge(2)];
}
const bounds = roofBounds;

function covers(rect, x, y) {
  return x >= rect[0] && y >= rect[1] && x <= rect[2] && y <= rect[3];
}

/** Effective ridge-end style; omitted ends inherit the section's form. */
export function endKind(section, end) {
  if (!['gable', 'hip'].includes(section.kind)) return null;
  return section.ends?.[end] ?? section.kind;
}

// A section is the minimum of its side planes, restricted to its footprint.
// Distances are signed: extending a plane past the plate lowers the eave.
export function planes(section) {
  if (section.roof_frame) return planes({...section,roof_frame:null}).map(p=>rotatePlane(section,p));
  const [x0, y0, x1, y1] = section.rect;
  const plate = section.plate;
  const side = name => (section.pitches?.[name] ?? section.pitch) / 12;
  const edges = {
    x0: () => { const s = side('x0'); return [s, 0, plate - s * x0]; },
    x1: () => { const s = side('x1'); return [-s, 0, plate + s * x1]; },
    y0: () => { const s = side('y0'); return [0, s, plate - s * y0]; },
    y1: () => { const s = side('y1'); return [0, -s, plate + s * y1]; },
  };
  const label = (plane, side) => Object.defineProperties(plane, {
    side:{value:side}, edge:{value:(section.plane_edges || {y0:0,x1:1,y1:2,x0:3})[side] ?? null},
  });
  if (section.kind === 'flat') return [label([0, 0, plate], null)];
  if (section.kind === 'shed') return [label(edges[section.low_side](), section.low_side)];
  let sides = section.kind === 'gable'
    ? (section.ridge === 'y' ? ['x0', 'x1'] : ['y0', 'y1'])
    : ['x0', 'x1', 'y0', 'y1'];
  const ends = section.ridge === 'y' ? ['y0', 'y1'] : ['x0', 'x1'];
  sides = sides.filter(name => !ends.includes(name) || endKind(section, name) !== 'gable');
  for (const end of ends) if (endKind(section, end) !== 'gable' && !sides.includes(end)) sides.push(end);
  const across = section.ridge === 'y' ? ['x0', 'x1'] : ['y0', 'y1'];
  const width = section.ridge === 'y' ? x1 - x0 : y1 - y0;
  const a = side(across[0]), b = side(across[1]);
  const rise = a + b > EPS ? width * a * b / (a + b) : 0;
  return sides.map(name => {
    const plane = edges[name]();
    if (ends.includes(name) && endKind(section, name) === 'clip') plane[2] += rise * 2 / 3;
    return label(plane, name);
  });
}

/** Height of one section, including its signed-slope overhang. */
export function sectionHeight(section, x, y) {
  const local=section.roof_frame?roofPoint(section,[x,y],true):[x,y];
  if (!covers(section.roof_frame?bounds({...section,roof_frame:null}):bounds(section), ...local)) return null;
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

/** Nearest roof above a floor, rather than the uppermost roof in the building. */
export function lowestRoofAbove(sections, x, y, floor) {
  let height = null;
  for (const section of sections) {
    const z = sectionHeight(section, x, y);
    if (z !== null && z > floor + EPS && (height === null || z < height)) height = z;
  }
  return height;
}

/** Storeys whose occupied volume or floor structure reaches this roof slab.
 * The caller supplies its actual outlines (triangulated for roofMesh). */
export function supportedRoofCutters(section, levels, polygons, thickness = 0.25) {
  const heights = sectionFaces(section, 0).flatMap(face =>
    face.polygon.map(p => valueAt(face.plane, ...p)));
  if (!heights.length) return [];
  const low = Math.min(...heights) - thickness, high = Math.max(...heights);
  return levels.filter(level => level.elevation - 0.8 <= high + EPS
    && level.elevation + level.ceiling >= low - EPS).flatMap(level => polygons.get(level.id) || []);
}

function insidePolygon(polygon, x, y) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[j], b = polygon[i], dx = b[0] - a[0], dy = b[1] - a[1];
    if (Math.abs(dx * (y - a[1]) - dy * (x - a[0])) <= EPS
        && x >= Math.min(a[0], b[0]) - EPS && x <= Math.max(a[0], b[0]) + EPS
        && y >= Math.min(a[1], b[1]) - EPS && y <= Math.max(a[1], b[1]) + EPS) return true;
    if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

/** Optional support cap, restricted to the same cut footprint as drawing. */
export function supportedRoofAbove(sections, x, y, floor, ceiling = Infinity,
  { cuts = () => [], thickness = 0.25, underside = false, ceilingAt = () => null } = {}) {
  let height = null;
  sections.forEach((section, index) => {
    if (!isSupported(section) || ['ghost', 'proposal'].includes(section.state)) return;
    const z = sectionHeight(section, x, y);
    const depth = section.thickness_ft ?? thickness;
    const flat = underside ? ceilingAt(section, index) : null;
    const result = underside ? Math.min(z - depth, flat ?? Infinity) : z;
    if (z === null || result <= floor + EPS || (flat === null ? z : result) >= ceiling - EPS
        || cuts(section, index).some(poly => insidePolygon(poly, x, y))) return;
    if (height === null || result < height) height = result;
  });
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

function rotatePlane(section, plane) {
  const {origin,angle}=section.roof_frame,c=Math.cos(angle),s=Math.sin(angle);
  const a=c*plane[0]-s*plane[1],b=s*plane[0]+c*plane[1];
  return Object.defineProperties([a,b,plane[2]+(plane[0]-a)*origin[0]+(plane[1]-b)*origin[1]],
    {side:{value:plane.side},edge:{value:plane.edge}});
}

function sectionFaces(section, index) {
  if (section.roof_frame) return sectionFaces({...section,roof_frame:null},index).map(face=>
    ({...face,polygon:face.polygon.map(p=>roofPoint(section,p)),plane:rotatePlane(section,face.plane)}));
  const all = planes(section);
  const faces = [];
  for (let i = 0; i < all.length; i++) {
    if (all.slice(0, i).some(p => samePlane(p, all[i]))) continue;
    let polygon = rectangle(bounds(section));
    for (const plane of all) polygon = clip(polygon, difference(plane, all[i]));
    if (polygon.length) faces.push({ polygon, plane: all[i], section: index, side: all[i].side, edge: all[i].edge });
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
  const slope0 = (section.pitches?.[alongX ? 'y0' : 'x0'] ?? section.pitch) / 12;
  const slope1 = (section.pitches?.[alongX ? 'y1' : 'x1'] ?? section.pitch) / 12;
  if (slope0 <= 0 || slope1 <= 0) return [];
  const apex = width * slope1 / (slope0 + slope1);
  const plate = section.plate;
  const positions = [];
  for (const [i, end] of (alongX ? [x0, x1] : [y0, y1]).entries()) {
    if (endKind(section, `${alongX ? 'x' : 'y'}${i}`) === 'hip') continue;
    const xy = u => alongX ? [end, start + u] : [start + u, end];
    let pieces = [[[0, plate], [width, plate], [apex, plate + apex * slope0]]];
    for (const plane of planes(section)) {
      pieces = pieces.map(piece => clip(piece,
        [alongX ? plane[1] : plane[0], -1, valueAt(plane, ...xy(0))])).filter(piece => piece.length);
    }
    for (let j = 0; j < sections.length; j++) {
      if (j === index || isSupported(sections[j])) continue;
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
  if (sections.some(isSupported)) {
    const indices = sections.flatMap((s, i) => isSupported(s) ? [] : [i]);
    if (only !== null && !indices.includes(only)) return new Float32Array();
    return stepFaces(indices.map(i => sections[i]), {
      section: only === null ? null : indices.indexOf(only), exclude: indices.map(i => exclude[i] || []),
      wallCover: (i, ...args) => wallCover(indices[i], ...args) });
  }
  const rects = sections.map(bounds), allPlanes = sections.map(planes), positions = [];
  sections.forEach((section, index) => {
    if (only !== null && only !== index) return;
    const rect = rects[index];
    for (let axis = 0; axis < 2; axis++) for (const sign of [-1, 1]) {
      // Rake ends are closed at the wall line by gableEnds, beneath their
      // overhang. Do not put another gable out at the roof's outer edge.
      if (axis === (section.ridge === 'y' ? 1 : 0)
          && ['gable', 'clip'].includes(endKind(section, `${axis === 0 ? 'x' : 'y'}${sign > 0 ? 1 : 0}`))) continue;
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
 * convex exclusions cut retained lower pieces, or every piece with cutAll. */
export function roofMesh(sections, { retainLower = false, exclude = [], materialKey = null, cutAll = false } = {}) {
  const faces = sections.flatMap(sectionFaces);
  const positions = [], labels = [], sides = [], edges = [], gables = [];
  for (const face of faces) {
    const partitioned = materialKey && faces.some(other => other.section !== face.section
      && samePlane(other.plane, face.plane) && materialKey(other) !== materialKey(face));
    let pieces = [face.polygon];
    for (const other of faces) {
      if (other.section === face.section) continue;
      let cutter;
      if (samePlane(other.plane, face.plane)) {
        // Deterministic ownership of coincident surfaces prevents z-fighting.
        if (!partitioned) {
          if (other.section > face.section) continue;
          cutter = other.polygon;
        } else {
          // Different finishes retain their own section's territory. Partition
          // a shared plane by section centres, rather than painting all of the
          // overlap with the lower index. Both owners use the same boundary.
          const rawCentre = i => { const r = sections[i].rect; return roofPoint(sections[i],[(r[0]+r[2])/2,(r[1]+r[3])/2]); };
          const centre = i => {
            const c = rawCentre(i);
            const tied = faces.filter(f => samePlane(f.plane,face.plane)
              && rawCentre(f.section).every((v,k)=>Math.abs(v-c[k])<EPS))
              .sort((a,b)=>String(sections[a.section].id || a.section).localeCompare(String(sections[b.section].id || b.section)));
            if (tied.length > 1) {
              // Coincident footprints still need territory for both finishes.
              // Stable IDs spread their ownership sites across the common
              // width, instead of silently giving all of it to index zero.
              const width = Math.max(EPS,Math.min(...tied.map(f=>sections[f.section].rect[2]-sections[f.section].rect[0])));
              c[0] += width*.5*((tied.findIndex(f=>f.section===i)+1)/(tied.length+1)-.5);
            }
            return c;
          };
          const a = centre(face.section), b = centre(other.section);
          const line = [2*(b[0]-a[0]), 2*(b[1]-a[1]), a[0]*a[0]+a[1]*a[1]-b[0]*b[0]-b[1]*b[1]];
          if (Math.hypot(line[0], line[1]) < EPS) {
            if (other.section > face.section) continue;
            cutter = other.polygon;
          } else cutter = clip(other.polygon, line);
        }
      } else {
        if (retainLower) continue;
        cutter = clip(other.polygon, difference(other.plane, face.plane));
      }
      if (cutter.length) pieces = pieces.flatMap(piece => subtract(piece, cutter));
      if (!pieces.length) break;
    }
    const cutters = exclude[face.section] || [];
    if (cutAll) {
      for (const cutter of cutters) pieces = pieces.flatMap(piece => subtract(piece, cutter));
    } else if (retainLower && cutters.length) {
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
      const start = labels.length;
      triangulate(piece, ([x, y]) => [x, y, valueAt(face.plane, x, y)], positions, labels, face.section);
      for (let t = start; t < labels.length; t++) { sides.push(face.side); edges.push(face.edge ?? -1); }
    }
  }
  sections.forEach((section, index) => {
    if (isSupported(section)) return;
    if (!['gable', 'hip'].includes(section.kind)) return;
    const ends = gableEnds(sections, index);
    if (ends.length) gables.push({ section: index, positions: new Float32Array(ends) });
  });
  return { positions: new Float32Array(positions), section: new Int32Array(labels),
    side: sides, edge: new Int32Array(edges), gables };
}

/** Independent envelopes; section labels are local to each group's input. */
export function roofEnvelope(sections, options) {
  return {
    walled: roofMesh(sections.filter(section => !isSupported(section)), options),
    supported: roofMesh(sections.filter(isSupported), options),
  };
}

/** Consumer mesh with independent support groups and original section labels.
 * Concave sections of one authored supported roof still share an envelope. */
export function roofMeshGroups(sections, options = {}) {
  if (!sections.some(isSupported)) return roofMesh(sections, options);
  const groups = new Map([['walled', []]]);
  sections.forEach((section, index) => {
    const key = isSupported(section) ? `supported:${section.roof || section.id || index}` : 'walled';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(index);
  });
  const meshes = [...groups.values()].map(indices => {
    const mesh = roofMesh(indices.map(i => sections[i]), { ...options,
      exclude: indices.map(i => options.exclude?.[i] || []),
      materialKey: options.materialKey ? face => options.materialKey({ ...face, section: indices[face.section] }) : null });
    return { ...mesh, section: Int32Array.from(mesh.section, i => indices[i]),
      gables: mesh.gables.map(g => ({ ...g, section: indices[g.section] })) };
  });
  return { positions: new Float32Array(meshes.flatMap(m => Array.from(m.positions))),
    section: new Int32Array(meshes.flatMap(m => Array.from(m.section))),
    side: meshes.flatMap(m => m.side), edge: new Int32Array(meshes.flatMap(m => Array.from(m.edge))),
    gables: meshes.flatMap(m => m.gables) };
}
