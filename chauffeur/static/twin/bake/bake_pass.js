import * as THREE from 'three';
import { FT } from '../twin_generator.js';
import { groundAt } from '../twin_ground.js';
import { lightRange, LAMP_HEIGHT } from '../live/modes.js';
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
float stored = textureCube(depthCube, -delta).r * farPlane;
float visibility = step(d - 0.025, stored);
float attenuation = pow(clamp(1.0 - pow(d / reach, 4.0), 0.0, 1.0), 2.0) / max(d*d, 0.01);
float irradiance = ${CANDELA.toFixed(1)} * attenuation * max(0.0, dot(normalize(wn), normalize(delta)));
// The byte stores irradiance / 16; runtime restores it before Lambert's 1/pi.
gl_FragColor = vec4(irradiance * visibility * weight / 16.0, 0.0, 0.0, 1.0); }`;
const skyFragment = `uniform sampler2D depthMap; uniform mat4 shadowMatrix; uniform vec3 direction;
uniform float weight; varying vec3 wp; varying vec3 wn;
void main() { vec4 p = shadowMatrix * vec4(wp + wn * 0.015, 1.0); vec3 q = p.xyz / p.w * 0.5 + 0.5;
float visible = step(q.z - 0.00003, texture2D(depthMap, q.xy).r);
gl_FragColor = vec4(visible * max(0.0, dot(normalize(wn), direction)) * weight, 0.0, 0.0, 1.0); }`;

function proxies(charts, size, sky, layout) {
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
    const uv = src.attributes[sky ? 'uv2' : 'uv3'].array.slice();
    const index = [];
    for (const c of list) {
      // Sparse banks move whole charts from the base room layout.
      for (const f of c.faces) for (let k = 0; k < 3; k++) {
        const i = f * 3 + k; index.push(i);
        if (!sky) {
          const base = layout.room.charts.find(b => b.mesh === mesh && b.faces === c.faces);
          if (base) { uv[i * 2] += (c.rect.x - base.rect.x) / size; uv[i * 2 + 1] += (c.rect.y - base.rect.y) / size; }
        }
      }
    }
    g.setAttribute('bakeUV', new THREE.BufferAttribute(uv, 2)); g.setIndex(index);
    const proxy = new THREE.Mesh(g); proxy.matrixAutoUpdate = false; proxy.matrix.copy(mesh.matrixWorld);
    proxy.frustumCulled = false; scene.add(proxy);
  }
  return scene;
}

function occluders(view) {
  const scene = new THREE.Scene();
  view.scene.updateMatrixWorld(true);
  view.scene.traverse(o => {
    if (!atlasMesh(o)) return;
    const mesh = new THREE.Mesh(o.geometry, o.material);
    mesh.matrixAutoUpdate = false; mesh.matrix.copy(o.matrixWorld); mesh.frustumCulled = false; scene.add(mesh);
  });
  return scene;
}

export async function renderPage(view, renderer, charts, size, sky, light, layout, atlas) {
  const target = new THREE.WebGLRenderTarget(size, size, { depthBuffer: false, type: THREE.HalfFloatType });
  const scene = proxies(charts, size, sky, atlas), blockers = occluders(view);
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
    if (!sky) {
      const b = view.plan.buildings.find(b => b.id === light.building), l = b?.levels.find(l => l.id === light.level);
      const r = b?.rooms?.find(r => r.id === light.room), floor = (b?.base || 0) + (l?.elevation || 0);
      const at = [...light.at];
      if (l && at[2] <= floor + .1) at[2] = floor + LAMP_HEIGHT;
      else if (l && at[2] >= floor + l.ceiling - .1) at[2] -= .2;
      const span = r ? Math.max(...[0, 1].map(k => Math.max(...r.polygon.map(p => p[k])) - Math.min(...r.polygon.map(p => p[k]))), 1) : 10;
      const reach = lightRange({ at }, b, l, r, span) * FT, far = Math.max(reach * 2, 30);
      const source = new THREE.Vector3(at[0] * FT, (at[2] + groundAt(view.plan, ...(b?.position || [0, 0]))) * FT, -at[1] * FT);
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
    } else {
      const bounds = new THREE.Box3().setFromObject(blockers), centre = bounds.getCenter(new THREE.Vector3());
      const reach = Math.max(bounds.getSize(new THREE.Vector3()).length(), 10);
      const sun = new THREE.OrthographicCamera(-reach, reach, reach, -reach, .1, reach * 4);
      shadow = new THREE.WebGLRenderTarget(1024, 1024, { type: THREE.FloatType,
        minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
      depth = new THREE.ShaderMaterial({ side: THREE.DoubleSide, vertexShader: worldVertex,
        fragmentShader: 'void main(){gl_FragColor = vec4(vec3(gl_FragCoord.z),1.0);}' });
      blockers.overrideMaterial = depth;
      material = new THREE.ShaderMaterial({ vertexShader: atlasVertex, fragmentShader: skyFragment,
        depthTest: false, depthWrite: false, transparent: true, blending: THREE.AdditiveBlending,
        uniforms: { depthMap: { value: shadow.texture }, shadowMatrix: { value: new THREE.Matrix4() },
          direction: { value: new THREE.Vector3() }, weight: { value: 2 / 32 } } });
      scene.overrideMaterial = material;
      for (let i = 0; i < 32; i++) {
        await nextFrame();
        const y = (i + .5) / 32, a = i * 2.3999632297;
        const direction = new THREE.Vector3(Math.cos(a) * Math.sqrt(1 - y*y), y, Math.sin(a) * Math.sqrt(1 - y*y));
        sun.position.copy(centre).addScaledVector(direction, reach * 2); sun.lookAt(centre); sun.updateMatrixWorld(true);
        material.uniforms.direction.value.copy(direction);
        material.uniforms.shadowMatrix.value.multiplyMatrices(sun.projectionMatrix, sun.matrixWorldInverse);
        renderer.autoClear = true; renderer.setClearColor(0xffffff, 1); renderer.setRenderTarget(shadow); renderer.render(blockers, sun);
        renderer.autoClear = false; renderer.setRenderTarget(target); renderer.render(scene, camera);
      }
    }
    const raw = new Uint16Array(size * size * 4);
    restore();
    if (renderer.readRenderTargetPixelsAsync) await renderer.readRenderTargetPixelsAsync(target, 0, 0, size, size, raw);
    else renderer.readRenderTargetPixels(target, 0, 0, size, size, raw);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = Math.round(Math.min(1, Math.max(0, THREE.DataUtils.fromHalfFloat(raw[i]))) * 255);
    // A small chart-local bilateral filter keeps shadow edges and never crosses a room.
    const copy = bytes.slice();
    for (const c of charts) {
      const r = c.rect;
      for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) {
        const p = (y * size + x) * 4, centre = copy[p]; let sum = 0, n = 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const sx = Math.max(r.x, Math.min(r.x + r.w - 1, x + dx)), sy = Math.max(r.y, Math.min(r.y + r.h - 1, y + dy));
          const v = copy[(sy * size + sx) * 4]; if (Math.abs(v - centre) < 20) { sum += v; n++; }
        }
        bytes[p] = Math.round(sum / n);
      }
    }
    if (!sky) {
      // One cheap diffuse bounce within this room. Its average lit albedo
      // scales the room fill, so even the bounce cannot cross a room boundary.
      let energy = 0, albedo = 0, count = 0;
      for (const c of charts) {
        const color = c.mesh.material.color, reflectance = color ? (color.r + color.g + color.b) / 3 : .5;
        for (let y = c.rect.y; y < c.rect.y + c.rect.h; y++) for (let x = c.rect.x; x < c.rect.x + c.rect.w; x++) {
          const v = bytes[(y * size + x) * 4]; energy += v; albedo += v * reflectance; count++;
        }
      }
      const bounce = count ? Math.min(4, albedo / count * .08) : 0;
      if (energy > 0) for (const c of charts)
        for (let y = c.rect.y; y < c.rect.y + c.rect.h; y++) for (let x = c.rect.x; x < c.rect.x + c.rect.w; x++) {
          const p = (y * size + x) * 4; bytes[p] = Math.min(255, Math.round(bytes[p] + bounce));
        }
    }
    return bytes;
  } finally {
    restore();
    for (const o of scene.children) o.geometry.dispose();
    material?.dispose(); depth?.dispose(); target.dispose(); shadow?.dispose();
  }
}
