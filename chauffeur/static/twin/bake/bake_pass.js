import * as THREE from 'three';
import { FT } from '../twin_generator.js';
import { lightSource } from './reach.js';
import { CANDELA } from '../live/real_lights.js';
import { atlasMesh } from './atlas.js';

const worldVertex = `varying vec3 wp;
void main() { wp = (modelMatrix * vec4(position, 1.0)).xyz;
gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0); }`;
const atlasVertex = `attribute vec2 bakeUV; varying vec3 wp; varying vec3 wn;
void main() { wp = (modelMatrix * vec4(position, 1.0)).xyz;
wn = normalize(mat3(modelMatrix) * normal); gl_Position = vec4(bakeUV * 2.0 - 1.0, 0.0, 1.0); }`;
const pointFragment = `uniform samplerCube depthCube; uniform vec3 source; uniform float reach;
uniform float farPlane; uniform float weight; varying vec3 wp; varying vec3 wn;
void main() { vec3 delta = source - wp; float d = length(delta);
if (d >= reach) discard;
float stored = textureCube(depthCube, -delta).r * farPlane;
float visibility = step(d - 0.025, stored);
float attenuation = pow(clamp(1.0 - pow(d / reach, 4.0), 0.0, 1.0), 2.0) / max(d*d, 0.01);
float irradiance = ${CANDELA.toFixed(1)} * attenuation * max(0.0, dot(normalize(wn), normalize(delta)));
// The byte stores irradiance / 16; runtime restores it before Lambert's 1/pi.
gl_FragColor = vec4(irradiance * visibility * weight / 16.0, 0.0, 0.0, 1.0); }`;
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

export function occluders(view) {
  const scene = new THREE.Scene();
  view.scene.updateMatrixWorld(true);
  view.scene.traverse(o => {
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

export async function renderPage(view, renderer, charts, size, light, layout, atlas, { deferBounce = false } = {}) {
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
    if (!controller?.idle) return;
    restore();
    await controller.idle();
    renderer.toneMapping = THREE.NoToneMapping; renderer.xr.enabled = false;
  };
  const camera = new THREE.Camera();
  let shadow, material, depth;
  try {
    renderer.toneMapping = THREE.NoToneMapping; renderer.xr.enabled = false;
    renderer.setClearColor(0, 0); renderer.setRenderTarget(target); renderer.clear();
    const { source, range: reach } = lightSource(view.plan, light), far = Math.max(reach * 2, 30);
    shadow = new THREE.WebGLCubeRenderTarget(512, { type: THREE.HalfFloatType,
      minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
    const cube = new THREE.CubeCamera(.02, far, shadow);
    cube.coordinateSystem = THREE.WebGLCoordinateSystem; cube.updateCoordinateSystem();
    depth = new THREE.ShaderMaterial({ side: THREE.DoubleSide, vertexShader: worldVertex,
      uniforms: { source: { value: source.clone() }, farPlane: { value: far } },
      fragmentShader: `uniform vec3 source; uniform float farPlane; varying vec3 wp;
void main(){gl_FragColor = vec4(vec3(length(wp-source)/farPlane),1.0);}` });
    blockers.overrideMaterial = depth;
    material = new THREE.ShaderMaterial({ vertexShader: atlasVertex, fragmentShader: pointFragment,
      depthTest: false, depthWrite: false, transparent: true, blending: THREE.AdditiveBlending,
      uniforms: { depthCube: { value: shadow.texture }, source: { value: source.clone() }, reach: { value: reach },
        farPlane: { value: far }, weight: { value: 1 / 16 } } });
    scene.overrideMaterial = material;
    for (let i = 0; i < 16; i++) {
      await nextFrame();
      const z = 1 - 2 * (i + .5) / 16, a = i * 2.3999632297, radius = Math.sqrt(1 - z * z) * .15 * FT;
      const p = source.clone().add(new THREE.Vector3(Math.cos(a) * radius, z * .15 * FT, Math.sin(a) * radius));
      cube.position.copy(p); depth.uniforms.source.value.copy(p); material.uniforms.source.value.copy(p);
      renderer.autoClear = true; renderer.setClearColor(0xffffff, 1); cube.updateMatrixWorld(true);
      for (let face = 0; face < 6; face++) { renderer.setRenderTarget(shadow, face); renderer.render(blockers, cube.children[face]); }
      renderer.autoClear = false; renderer.setRenderTarget(target); renderer.render(scene, camera);
    }
    const raw = new Uint16Array(size * size * 4);
    restore();
    if (renderer.readRenderTargetPixelsAsync) await renderer.readRenderTargetPixelsAsync(target, 0, 0, size, size, raw);
    else renderer.readRenderTargetPixels(target, 0, 0, size, size, raw);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = Math.round(Math.min(1, Math.max(0, THREE.DataUtils.fromHalfFloat(raw[i]))) * 255);
    filterCharts(bytes, charts, size);
    if (!deferBounce) { addRoomBounce(bytes, charts, size); dilateCharts(bytes, charts, size); }
    return bytes;
  } finally {
    restore();
    for (const o of scene.children) o.geometry.dispose();
    material?.dispose(); depth?.dispose(); target.dispose(); shadow?.dispose();
  }
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

export function addRoomBounce(bytes, charts, size) {
  addRoomBounceAcrossPages([{bytes, charts}], size);
}

export function addRoomBounceAcrossPages(pages, size) {
  // Each reached room gets fill proportional to its own direct energy. A
  // shadowed room gets none. Outdoors retains direct shadows, without fill.
  const rooms = new Set(pages.flatMap(p => p.charts.filter(c => !c.outdoor).map(c => c.room)));
  for (const room of rooms) {
    const mine = pages.flatMap(p => p.charts.filter(c => c.room === room).map(c => ({c, bytes:p.bytes})));
    let energy = 0, albedo = 0, count = 0;
    for (const {c, bytes} of mine) {
      const color = c.mesh.material.color, reflectance = color ? (color.r + color.g + color.b) / 3 : .5;
      for (let y = c.rect.y; y < c.rect.y + c.rect.h; y++) for (let x = c.rect.x; x < c.rect.x + c.rect.w; x++) {
        const p = (y * size + x) * 4;
        if (!bytes[p + 3]) continue;
        const v = bytes[p]; energy += v; albedo += v * reflectance; count++;
      }
    }
    const bounce = count ? Math.min(4, albedo / count * .08) : 0;
    if (energy > 0) for (const {c, bytes} of mine)
      for (let y = c.rect.y; y < c.rect.y + c.rect.h; y++) for (let x = c.rect.x; x < c.rect.x + c.rect.w; x++) {
        const p = (y * size + x) * 4;
        if (bytes[p + 3]) bytes[p] = Math.min(255, Math.round(bytes[p] + bounce));
      }
  }
}
