import * as THREE from 'three';
import { lightSource } from './reach.js';
import { CANDELA } from '../live/real_lights.js';
import { atlasMesh } from './atlas.js';
import { bakeSamples, fillStrength } from './fixture_terms.js';
import { chartReflectance } from './bindings.js';

const worldVertex = `varying vec3 wp;
void main() { wp = (modelMatrix * vec4(position, 1.0)).xyz;
gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0); }`;
const atlasVertex = `attribute vec2 bakeUV; varying vec3 wp; varying vec3 wn;
void main() { wp = (modelMatrix * vec4(position, 1.0)).xyz;
wn = normalize(mat3(modelMatrix) * normal); gl_Position = vec4(bakeUV * 2.0 - 1.0, 0.0, 1.0); }`;
// A shadowmask: each texel stores how much of the light's emitter it sees (0..1, soft over the
// emitter's jittered samples). The falloff, N.L and colour are the live light's, computed per
// pixel in the material (lightmap_material.js), so the bake carries no falloff or shading, and
// a normal map and a batten's own normal still shade (2026-11-14). G carries the texel's
// shadowed irradiance / 16 for the room fill only; it is never stored.
const pointFragment = `uniform samplerCube depthCube; uniform vec3 source; uniform float reach;
uniform float farPlane; uniform float weight; varying vec3 wp; varying vec3 wn;
void main() { vec3 delta = source - wp; float d = length(delta);
if (d >= reach) discard;
vec3 n = normalize(wn);
// Normal offset: a cube texel spans more depth at distance and at grazing angles, so the
// receiver steps off its own surface by about a texel before the depth test (no acne). At
// most 3 cm: a batten stands 2.7 cm proud, and a lift past it would erase the contact shadow
// it casts on the wall beside it (and under shelves and trim).
vec3 lifted = wp + n * min(0.03, 0.005 + 0.004 * d);
vec3 toward = source - lifted; float reached = length(toward);
float stored = textureCube(depthCube, -toward).r * farPlane;
float visibility = step(reached - 0.02, stored);
float attenuation = pow(clamp(1.0 - pow(d / reach, 4.0), 0.0, 1.0), 2.0) / max(d*d, 0.01);
float irradiance = ${CANDELA.toFixed(1)} * attenuation * max(0.0, dot(n, normalize(delta)));
gl_FragColor = vec4(visibility * weight, irradiance * visibility * weight / 16.0, 0.0, 1.0); }`;
const fixtureFragment = pointFragment.replace('uniform float farPlane;', `uniform vec3 emitterNormal; uniform vec3 axis; uniform vec3 origin;
uniform vec3 pieceCentre; uniform vec3 pieceU; uniform vec3 pieceV;
uniform float outer; uniform float inner; uniform float cd; uniform float kind;
uniform float visibilityWeight; uniform float scale; uniform float fillStrength; uniform float farPlane;`)
  .replace('if (d >= reach) discard;', `float nearest = d;
if (dot(pieceU,pieceU) > 0.0) {
  vec3 offset = wp-pieceCentre;
  vec3 closest = pieceCentre + pieceU * clamp(dot(offset,pieceU)/dot(pieceU,pieceU),-1.0,1.0)
    + pieceV * clamp(dot(offset,pieceV)/dot(pieceV,pieceV),-1.0,1.0);
  nearest = length(wp-closest);
}
if (nearest >= reach) discard;
float facing = dot(emitterNormal,emitterNormal) > 0.0 ? max(0.0,dot(emitterNormal,-delta/max(d,1e-4))) : 1.0;
float coneCos = dot(axis,normalize(wp-origin));
float cone = outer < -0.5 ? 1.0 : inner == outer ? step(outer,coneCos) : smoothstep(outer,inner,coneCos);`)
  .replace('pow(d / reach, 4.0)', 'pow(nearest / reach, 4.0)')
  .replace(`${CANDELA.toFixed(1)} * attenuation`, 'cd * facing * cone * attenuation')
  .replace('weight / 16.0', 'weight / (16.0 * fillStrength)')
  .replace('gl_FragColor = vec4(visibility * weight,', `visibility *= step(1e-8,facing);
gl_FragColor = vec4(kind > 2.5 ? irradiance * visibility * weight / scale : visibility * visibilityWeight,`);
function proxies(charts, size, layout) {
  const scene = new THREE.Scene(), groups = new Map();
  for (const c of charts) {
    if (!groups.has(c.mesh)) groups.set(c.mesh, []);
    groups.get(c.mesh).push(c);
  }
  for (const [mesh, list] of groups) {
    const g = new THREE.BufferGeometry(), src = mesh.geometry;
    // Own attribute objects over the same arrays: dispose() frees a geometry's GL buffers,
    // and the house's own position and normal buffers must outlive the bake (I6).
    g.setAttribute('position', new THREE.BufferAttribute(src.attributes.position.array, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(src.attributes.normal.array, 3));
    const uv = src.attributes.uv3.array.slice();
    const index = [];
    for (const c of list) {
      // Sparse banks move whole charts from the base room layout. One lookup per chart: a
      // per-vertex search was charts x vertices (seconds once graded ground baked).
      const base = layout.room.charts.find(b => b.mesh === mesh && b.faces === c.faces);
      const du = base ? (c.rect.x - base.rect.x) / size : 0, dv = base ? (c.rect.y - base.rect.y) / size : 0;
      for (const f of c.faces) for (let k = 0; k < 3; k++) {
        const i = f * 3 + k; index.push(i);
        if (base) { uv[i * 2] += du; uv[i * 2 + 1] += dv; }
      }
    }
    g.setAttribute('bakeUV', new THREE.BufferAttribute(uv, 2)); g.setIndex(index);
    const proxy = new THREE.Mesh(g); proxy.matrixAutoUpdate = false; proxy.matrix.copy(mesh.matrixWorld);
    proxy.frustumCulled = false; scene.add(proxy);
  }
  return scene;
}

// The host texels a thin proxy face covers (a batten's footprint, a trim board's), drawn in the
// host chart's own lightmap coordinates with the face's own position and normal. Those texels
// lie under the face, 2.7 cm behind it: baked as wall, their lifted sample point ended inside
// the batten and saw no light, and at 4 texels/ft that black was smeared into a dark strip
// beside every batten, which the batten then borrowed (owner 2026-11-21, the v2.499.861
// dark-lines bug again). renderPage bakes them as the face itself instead: the recess under a
// batten holds what the batten's front sees, and the wall beside it keeps its real shadow.
export function proxyCovers(charts, size, layout) {
  const scene = new THREE.Scene(), groups = new Map();
  for (const c of charts) for (const part of c.proxies || []) {
    if (!groups.has(part.mesh)) groups.set(part.mesh, []);
    groups.get(part.mesh).push({ host: c, faces: part.faces });
  }
  for (const [mesh, list] of groups) {
    const src = mesh.geometry;
    if (!src.attributes.uv3) continue;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(src.attributes.position.array, 3));
    if (src.attributes.normal) g.setAttribute('normal', new THREE.BufferAttribute(src.attributes.normal.array, 3));
    const uv = src.attributes.uv3.array.slice(), index = [];
    for (const { host, faces } of list) {
      // A proxy carries its host's mapping, so it moves with the host chart's rect.
      const base = layout.room.charts.find(b => b.mesh === host.mesh && b.faces === host.faces);
      const du = base ? (host.rect.x - base.rect.x) / size : 0, dv = base ? (host.rect.y - base.rect.y) / size : 0;
      for (const f of faces) for (let k = 0; k < 3; k++) {
        const i = f * 3 + k; index.push(i);
        if (base) { uv[i * 2] += du; uv[i * 2 + 1] += dv; }
      }
    }
    if (!index.length) continue;
    g.setAttribute('bakeUV', new THREE.BufferAttribute(uv, 2)); g.setIndex(index);
    const cover = new THREE.Mesh(g); cover.matrixAutoUpdate = false; cover.matrix.copy(mesh.matrixWorld);
    cover.frustumCulled = false; scene.add(cover);
  }
  return scene;
}
// Multiplies what is under it by zero, colour and alpha, so the face's own bake can replace it.
const clearCovered = () => new THREE.ShaderMaterial({
  vertexShader: 'attribute vec2 bakeUV; void main() { gl_Position = vec4(bakeUV * 2.0 - 1.0, 0.0, 1.0); }',
  fragmentShader: 'void main() { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); }',
  depthTest: false, depthWrite: false, transparent: true, side: THREE.DoubleSide,
  blending: THREE.CustomBlending, blendEquation: THREE.AddEquation,
  blendSrc: THREE.ZeroFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
  blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor });
// Adds one same-size target onto another texel for texel (the faces' bake onto the cleared page).
function addTarget(renderer, from, to, camera) {
  const quad = new THREE.Mesh(new THREE.BufferGeometry().setAttribute('position',
    new THREE.Float32BufferAttribute([-1, -1, 0, 3, -1, 0, -1, 3, 0], 3)), new THREE.ShaderMaterial({
    uniforms: { map: { value: from.texture } },
    vertexShader: 'varying vec2 vUv; void main() { vUv = position.xy * 0.5 + 0.5; gl_Position = vec4(position.xy, 0.0, 1.0); }',
    fragmentShader: 'uniform sampler2D map; varying vec2 vUv; void main() { gl_FragColor = texture2D(map, vUv); }',
    depthTest: false, depthWrite: false, transparent: true, blending: THREE.CustomBlending, blendEquation: THREE.AddEquation,
    blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor, blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneFactor }));
  quad.frustumCulled = false;
  const scene = new THREE.Scene(); scene.add(quad);
  renderer.setRenderTarget(to); renderer.render(scene, camera);
  quad.geometry.dispose(); quad.material.dispose();
}

export function occluders(view) {
  const scene = new THREE.Scene();
  view.scene.updateMatrixWorld(true);
  (view.bake?.occlusionRoot?.() || view.scene).traverse(o => {
    if (!atlasMesh(o) || o.material.name === 'glass') return;
    // Graded ground receives yard light but never blocks it: seen at grazing angles from a
    // lamp above, one cube texel spans more depth than the bias and the lawn shadows itself.
    if (o.geometry?.userData.bakeHeightfield) return;
    for (let p = o.parent; p; p = p.parent) if (p.userData.viewingWalls === 'cut') return;
    const mesh = new THREE.Mesh(o.geometry, o.material);
    mesh.matrixAutoUpdate = false; mesh.matrix.copy(o.matrixWorld); mesh.frustumCulled = false; scene.add(mesh);
  });
  return scene;
}

export async function renderPage(view, renderer, charts, size, light, layout, atlas,
  { deferBounce = false, deferSumEncoding = false, checkpoint = async () => {} } = {}) {
  const target = new THREE.WebGLRenderTarget(size, size, { depthBuffer: false, type: THREE.HalfFloatType });
  const scene = proxies(charts, size, atlas), blockers = occluders(view);
  const saved = { target: renderer.getRenderTarget(), color: renderer.getClearColor(new THREE.Color()),
    alpha: renderer.getClearAlpha(), tone: renderer.toneMapping, auto: renderer.autoClear, xr: renderer.xr.enabled };
  const controller = view.bake;
  const restore = () => {
    renderer.setRenderTarget(saved.target); renderer.setClearColor(saved.color, saved.alpha);
    renderer.toneMapping = saved.tone; renderer.autoClear = saved.auto; renderer.xr.enabled = saved.xr;
  };
  const nextFrame = async () => {
    await checkpoint();
    if (!controller?.idle) return;
    restore();
    await controller.idle();
    await checkpoint();
    renderer.toneMapping = THREE.NoToneMapping; renderer.xr.enabled = false;
  };
  const camera = new THREE.Camera();
  let shadow, material, depth, covers = null, clear = null, front = null;
  try {
    renderer.toneMapping = THREE.NoToneMapping; renderer.xr.enabled = false;
    renderer.setClearColor(0, 0); renderer.setRenderTarget(target); renderer.clear();
    const { source, range: reach } = lightSource(view.plan, light), far = Math.max(reach * 2, 30);
    const samples = bakeSamples(view.plan, light);
    shadow = new THREE.WebGLCubeRenderTarget(512, { type: THREE.HalfFloatType,
      minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
    const cube = new THREE.CubeCamera(.02, far, shadow);
    cube.coordinateSystem = THREE.WebGLCoordinateSystem; cube.updateCoordinateSystem();
    depth = new THREE.ShaderMaterial({ side: THREE.DoubleSide, vertexShader: worldVertex,
      uniforms: { source: { value: source.clone() }, farPlane: { value: far } },
      fragmentShader: `uniform vec3 source; uniform float farPlane; varying vec3 wp;
void main(){gl_FragColor = vec4(vec3(length(wp-source)/farPlane),1.0);}` });
    blockers.overrideMaterial = depth;
    material = new THREE.ShaderMaterial({ vertexShader: atlasVertex, fragmentShader: light.emitters ? fixtureFragment : pointFragment,
      depthTest: false, depthWrite: false, transparent: true, blending: THREE.AdditiveBlending,
      uniforms: { depthCube: { value: shadow.texture }, source: { value: source.clone() }, reach: { value: reach },
        farPlane: { value: far }, weight: { value: 1 / 16 },
        emitterNormal: {value: new THREE.Vector3()}, axis: {value: new THREE.Vector3()}, origin: {value: source.clone()},
        pieceCentre: {value: new THREE.Vector3()}, pieceU: {value: new THREE.Vector3()}, pieceV: {value: new THREE.Vector3()},
        outer: {value: -1}, inner: {value: -1}, cd: {value: CANDELA}, kind: {value: light.kind || 0},
        visibilityWeight: {value: 1 / 16}, scale: {value: 1}, fillStrength: {value: fillStrength(light)} } });
    scene.overrideMaterial = material;
    covers = proxyCovers(charts, size, atlas);
    if (covers.children.length) {
      covers.overrideMaterial = material;
      front = new THREE.WebGLRenderTarget(size, size, { depthBuffer: false, type: THREE.HalfFloatType,
        minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
      renderer.setClearColor(0, 0); renderer.setRenderTarget(front); renderer.clear();
    }
    for (const sample of samples) {
      await nextFrame();
      const p = sample.source, u = material.uniforms;
      u.reach.value = sample.range;u.weight.value = sample.weight;u.cd.value = sample.cd;
      u.visibilityWeight.value = sample.visibilityWeight ?? sample.weight;
      u.emitterNormal.value.copy(sample.normal);u.axis.value.copy(sample.axis);u.origin.value.copy(sample.origin);
      u.outer.value = sample.outer;u.inner.value = sample.inner;
      u.pieceCentre.value.copy(sample.piece?.position || p);
      u.pieceU.value.copy(sample.piece?.u || new THREE.Vector3());u.pieceV.value.copy(sample.piece?.v || new THREE.Vector3());
      cube.position.copy(p); depth.uniforms.source.value.copy(p); material.uniforms.source.value.copy(p);
      renderer.autoClear = true; renderer.setClearColor(0xffffff, 1); cube.updateMatrixWorld(true);
      for (let face = 0; face < 6; face++) { renderer.setRenderTarget(shadow, face); renderer.render(blockers, cube.children[face]); }
      renderer.autoClear = false; renderer.setRenderTarget(target); renderer.render(scene, camera);
      if (front) { renderer.setRenderTarget(front); renderer.render(covers, camera); }
    }
    if (front) {
      // The texels under each thin face hold what the face sees, not the buried wall.
      covers.overrideMaterial = clear = clearCovered();
      renderer.autoClear = false; renderer.setRenderTarget(target); renderer.render(covers, camera);
      addTarget(renderer, front, target, camera);
    }
    const raw = new Uint16Array(size * size * 4);
    restore();
    if (renderer.readRenderTargetPixelsAsync) await renderer.readRenderTargetPixelsAsync(target, 0, 0, size, size, raw);
    else renderer.readRenderTargetPixels(target, 0, 0, size, size, raw);
    const bytes = new Uint8Array(raw.length), irradiance = light.kind === 3 ? new Uint16Array(size * size) : null;
    for (let i = 0; i < raw.length; i++) {
      if (irradiance && i % 4 === 0) { irradiance[i / 4] = raw[i]; continue; }
      const value = Math.min(1, Math.max(0, THREE.DataUtils.fromHalfFloat(raw[i])));
      bytes[i] = Math.round(value * 255);
    }
    if (light.kind === 3) {
      const page = {bytes, irradiance, charts};
      if (deferSumEncoding) return page;
      light.scale = await encodeSumPages([page], size);
    }
    filterCharts(bytes, charts, size);
    if (!deferBounce) dilateCharts(bytes, charts, size);
    return bytes;
  } finally {
    restore();
    for (const o of scene.children) o.geometry.dispose();
    for (const o of covers?.children || []) o.geometry.dispose();
    material?.dispose(); depth?.dispose(); clear?.dispose(); front?.dispose(); target.dispose(); shadow?.dispose();
  }
}

// Sum targets carry raw half-float irradiance at scale 1 until every page of
// the entity has been read back. A half-float histogram gives the exact nearest-
// rank 99.5th percentile without sorting millions of receiver texels. Only
// raster-written, non-zero receiver texels count, never padding or other lights.
// Retain only R (two bytes per texel), not all four float channels, across pages.
// Yield every 64 rows so scale selection/encoding cannot monopolise the desk.
export async function encodeSumPages(pages, size, yieldWork = () => new Promise(resolve => setTimeout(resolve, 0))) {
  const histogram = new Uint32Array(0x7c00);
  let count = 0, rows = 0;
  for (const {bytes, irradiance, charts} of pages) for (const c of charts) {
    const r = c.rect;
    for (let y = r.y; y < r.y + r.h; y++) {
      for (let x = r.x; x < r.x + r.w; x++) {
        const i = (y * size + x) * 4, value = irradiance[i / 4];
        if (bytes[i + 3] && value > 0 && value < 0x7c00) {
          histogram[Math.min(value, 0x7bff)]++; count++;
        }
      }
      if (++rows % 64 === 0) await yieldWork();
    }
  }
  await yieldWork();
  const rank = Math.ceil(count * .995);
  let n = 0, code = 0;
  while (code < 0x7bff && (n += histogram[code]) < rank) code++;
  const measured = Math.max(1e-6, THREE.DataUtils.fromHalfFloat(code) * 1.25);
  const scale = 2 ** (Math.ceil(Math.log2(measured) * 16) / 16);
  for (const {bytes, irradiance} of pages) {
    const stride = size * 64 * 4;
    for (let start = 0; start < bytes.length; start += stride) {
      const end = Math.min(bytes.length, start + stride);
      for (let i = start; i < end; i += 4)
        bytes[i] = Math.round(Math.sqrt(Math.min(1, Math.max(0, THREE.DataUtils.fromHalfFloat(irradiance[i / 4])) / scale)) * 255);
      await yieldWork();
    }
  }
  return scale;
}

// A small chart-local bilateral filter keeps shadow edges. Texels the raster never wrote (in
// the chart's rectangle but outside its faces) neither count nor change: averaging them in
// darkened every chart border (the pool floor's dark diagonal, 2026-11-13).
export function filterCharts(bytes, charts, size) {
  const copy = bytes.slice();
  for (const c of charts) {
    const r = c.rect;
    for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) {
      const p = (y * size + x) * 4, centre = copy[p]; let sum = 0, n = 0;
      if (!copy[p + 3]) continue;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const sx = Math.max(r.x, Math.min(r.x + r.w - 1, x + dx)), sy = Math.max(r.y, Math.min(r.y + r.h - 1, y + dy));
        const q = (sy * size + sx) * 4, v = copy[q];
        if (copy[q + 3] && Math.abs(v - centre) < 20) { sum += v; n++; }
      }
      bytes[p] = Math.round(sum / n);
    }
  }
  return bytes;
}

// Fill each chart's unwritten texels from their written neighbours, ring by ring, so bilinear
// sampling at a chart's border never blends in black. A flat floor split into two charts (the
// pool floor crosses a 64 ft outdoor tile line) showed its seam as a dark diagonal. Filled
// texels stay alpha 0: they are padding, not surface, for bounce and coverage.
export function dilateCharts(bytes, charts, size) {
  for (const c of charts) {
    const r = c.rect, w = r.w, h = r.h, done = new Uint8Array(w * h);
    let any = false;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++)
      if (bytes[((r.y + y) * size + r.x + x) * 4 + 3]) { done[y * w + x] = 1; any = true; }
    if (!any) continue;
    for (let pass = 0; pass < w + h; pass++) {
      const fill = [];
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        if (done[y * w + x]) continue;
        let sum = 0, n = 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx, ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= w || ny >= h || !done[ny * w + nx]) continue;
          sum += bytes[((r.y + ny) * size + r.x + nx) * 4]; n++;
        }
        if (n) fill.push([x, y, Math.round(sum / n)]);
      }
      if (!fill.length) break;
      for (const [x, y, v] of fill) { bytes[((r.y + y) * size + r.x + x) * 4] = v; done[y * w + x] = 1; }
    }
  }
  return bytes;
}

// The room fill: each reached room gets a uniform term proportional to its own direct
// energy (albedo-weighted shadowed irradiance, read from G), in irradiance units, which the
// material adds to that light's term under its live tint. A room the light never reaches (all
// texels shadowed) gets none; outdoors keeps its shadows without fill.
export function roomFills(pages, size, light = null) {
  const rooms = new Set(pages.flatMap(p => p.charts.filter(c => !c.outdoor).map(c => c.room))), fills = {};
  for (const room of rooms) {
    const mine = pages.flatMap(p => p.charts.filter(c => c.room === room).map(c => ({ c, bytes: p.bytes })));
    let energy = 0, albedo = 0, count = 0;
    for (const { c, bytes } of mine) {
      const reflectance = chartReflectance(c);
      for (let y = c.rect.y; y < c.rect.y + c.rect.h; y++) for (let x = c.rect.x; x < c.rect.x + c.rect.w; x++) {
        const p = (y * size + x) * 4;
        if (!bytes[p + 3]) continue;
        const v = bytes[p + 1]; energy += v; albedo += v * reflectance; count++;
      }
    }
    // G bytes are irradiance / 16 * 255; the fill is what four such bytes carried at most.
    if (energy > 0 && count) fills[room] = Math.min(4, albedo / count * .08) * 16 / 255 * fillStrength(light);
  }
  return fills;
}
