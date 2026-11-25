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

/** Brackets use the same sheared box as the original awning renderer.
 * THREE is supplied by the renderer so point placement stays renderer-free. */
export function supportGeometry(roof, points, ctx) {
  if (roof.support?.kind !== 'bracket' || roof.support.count === 0 || !points.length) return [];
  const {THREE} = ctx, {origin, outward, tangent, depth} = supportFrame(roof);
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
    return {geometry, slot: 'support', part: point.id || `support:${i}`};
  });
}
