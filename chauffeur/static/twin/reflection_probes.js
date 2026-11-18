import * as THREE from 'three';
import { waterBodies } from './effects/water_ripples.js';
import { buildingFootprint, buildingBase } from './twin_ground.js';

const FT = .3048;
const replace = (shader, stage, anchor, value) => {
  if (!shader[stage].includes(anchor)) throw new Error('Reflection shader missing anchor: ' + anchor);
  shader[stage] = shader[stage].replace(anchor, value);
};
const declarations = `varying vec3 vProbeWorld;
uniform vec3 probeCentre, probeMin, probeMax;
uniform float probeActive;
vec3 probeBox(vec3 direction, vec3 centre) {
  // Slab intersection with the forward box face. Avoid NaNs on axis-aligned rays.
  vec3 safeDirection = mix(vec3(-.00001), vec3(.00001), step(vec3(0.0), direction));
  safeDirection = mix(safeDirection, direction, step(vec3(.00001), abs(direction)));
  vec3 farFace = max((probeMin - vProbeWorld) / safeDirection, (probeMax - vProbeWorld) / safeDirection);
  float distanceToBox = min(min(farFace.x, farFace.y), farFace.z);
  return vProbeWorld + direction * max(0.0, distanceToBox) - centre;
}
vec3 probeDirection(vec3 direction) { return mix(direction, probeBox(direction, probeCentre), probeActive); }
`;
// Metres from the water to what it mirrors, along the mirrored ray.
const PLANAR_REACH = 5;
// Metres above the water where the mirror image starts (see drawMirror).
export const MIRROR_LIFT = .37;
const waterDeclarations = `attribute vec3 reflectionBodyCentre; varying vec3 vReflectionBodyCentre;\n`;
const waterFragment = `varying vec3 vReflectionBodyCentre;
uniform vec3 waterProbeCentre[4];
uniform float waterProbeFresh[4];
uniform int waterProbeCount;
uniform samplerCube waterProbe0, waterProbe1, waterProbe2, waterProbe3;
uniform sampler2D waterPlanar;
uniform mat4 waterPlanarMatrix;
uniform float waterPlanarActive, waterPlanarHeight;
vec3 waterProbeSample(int index, vec3 direction, float roughness) {
  // Calm bodies share a merged draw. Sample the selected linear cube's mip
  // chain directly; glass uses three's PMREM. Water roughness remains .08..12.
  float lod = roughness * 8.0;
  if (index == 0) return textureLod(waterProbe0, direction, lod).rgb;
  if (index == 1) return textureLod(waterProbe1, direction, lod).rgb;
  if (index == 2) return textureLod(waterProbe2, direction, lod).rgb;
  return textureLod(waterProbe3, direction, lod).rgb;
}
`;

// Install before batching. A binding's uniforms are shared by viewing/bake/ghost
// clones. Calm water keeps its shared draw and selects by body centre instead.
// Different buildings never share a binding. No per-probe program.
export function reflectionMaterial(material, kind, owner) {
  if (material.userData.reflection) { material.userData.reflection.owners.add(owner); return material; }
  const binding = {kind, owner, owners:new Set([owner]), materials: new Set(), probe: null, uniforms: {
    probeCentre: {value: new THREE.Vector3()}, probeMin: {value: new THREE.Vector3()},
    probeMax: {value: new THREE.Vector3()}, probeActive: {value: 0},
  }};
  if (kind === 'water') Object.assign(binding.uniforms, {
    waterProbeCentre:{value:Array.from({length:4},()=>new THREE.Vector3())},
    waterProbeFresh:{value:[0,0,0,0]}, waterProbeCount:{value:0},
    ...Object.fromEntries([0,1,2,3].map(i=>['waterProbe'+i,{value:null}])),
    waterPlanar:{value:null}, waterPlanarMatrix:{value:new THREE.Matrix4()},
    waterPlanarActive:{value:0}, waterPlanarHeight:{value:0},
  });
  if (kind === 'exterior') binding.uniforms.paneBaseOpacity = {get value() { return material.opacity; }};
  const before = material.onBeforeCompile, key = material.customProgramCacheKey();
  material.onBeforeCompile = function(shader, renderer) {
    before.call(this, shader, renderer);
    Object.assign(shader.uniforms, binding.uniforms);
    shader.vertexShader = 'varying vec3 vProbeWorld;\n' + shader.vertexShader;
    replace(shader, 'vertexShader', '#include <project_vertex>',
      'vProbeWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;\n#include <project_vertex>');
    shader.fragmentShader = declarations + shader.fragmentShader;
    // Vendored r187 uses PMREM for standard materials, including explicit cubes.
    const chunk = {fragmentShader: THREE.ShaderChunk.envmap_physical_pars_fragment};
    const anchor = 'reflectVec = transformDirectionByInverseViewMatrix( reflectVec, viewMatrix );';
    if (kind === 'water') {
      shader.vertexShader = waterDeclarations + shader.vertexShader;
      replace(shader, 'vertexShader', '#include <project_vertex>', 'vReflectionBodyCentre = reflectionBodyCentre;\n#include <project_vertex>');
      shader.fragmentShader = waterFragment + shader.fragmentShader;
      replace(chunk, 'fragmentShader', anchor, anchor + `
// A wave steep enough to send the mirrored ray below the horizon would show
// the pool's own shell, which the water hides. Such a ray meets the water
// again and leaves upward, so fold it back up, clear of the pool's own rim;
// without this a dark pool reads as a field of dark blobs instead of a
// picture of what stands beside it.
reflectVec = normalize(vec3(reflectVec.x, max(abs(reflectVec.y), .12), reflectVec.z));
if (waterPlanarActive > .5 && abs(vProbeWorld.y - waterPlanarHeight) < .05) {
  // The mirror image of the scene, drawn from the camera's reflection. A wave
  // bends the mirrored ray; follow the bent ray to where it would meet what
  // stands beside the pool and look that point up in the image. Seen low
  // across the water this smears the image up and down far more than
  // sideways, which is the streaking a real pool shows.
  vec4 waterClip = waterPlanarMatrix * vec4(vProbeWorld + reflectVec * ${PLANAR_REACH.toFixed(1)}, 1.0);
  return texture2D(waterPlanar, clamp(waterClip.xy / waterClip.w * .5 + .5, .002, .998)).rgb;
}
int waterProbeIndex = 0; float waterProbeDistance = 1e30;
for (int i = 0; i < 4; i++) {
  if (i >= waterProbeCount) break;
  float d = distance(vReflectionBodyCentre, waterProbeCentre[i]);
  if (d < waterProbeDistance) { waterProbeDistance = d; waterProbeIndex = i; }
}
if (waterProbeCount > 0 && waterProbeFresh[waterProbeIndex] > .5)
  return waterProbeSample(waterProbeIndex, probeBox(reflectVec, waterProbeCentre[waterProbeIndex]), roughness);`);
      // A water surface has no colour of its own: the share of light it mirrors
      // is light the body below cannot also send. Left at full strength, the lit
      // body drowns the mirror and the surroundings only tint it faintly.
      replace(shader, 'fragmentShader', '#include <lights_fragment_end>', `#include <lights_fragment_end>
if (waterProbeCount > 0) {
  float waterMirror = .02 + .98 * pow(1.0 - abs(dot(normal, geometryViewDir)), 5.0);
  reflectedLight.directDiffuse *= 1.0 - waterMirror;
  reflectedLight.indirectDiffuse *= 1.0 - waterMirror;
}`);
    } else replace(chunk, 'fragmentShader', anchor, anchor + '\nreflectVec = probeDirection(reflectVec);');
    replace(shader, 'fragmentShader', '#include <envmap_physical_pars_fragment>', chunk.fragmentShader);
    if (kind === 'exterior') {
      shader.fragmentShader = 'uniform float paneBaseOpacity;\n' + shader.fragmentShader;
      replace(shader, 'fragmentShader', '#include <lights_fragment_end>', `#include <lights_fragment_end>
float paneMirror = 0.0;
#ifdef USE_ENVMAP
// A glazed unit has four air-to-glass faces, so it mirrors about a tenth
// of the light head on, rising to all of it at a glancing angle.
float paneFresnel = .1 + .9 * pow(1.0 - abs(dot(normal, geometryViewDir)), 5.0);
reflectedLight.indirectSpecular = getIBLRadiance(geometryViewDir, normal, roughnessFactor) * paneFresnel;
paneMirror = paneFresnel;
#endif
paneMirror = clamp(paneMirror + luminance(reflectedLight.directSpecular), 0.0, 1.0);`);
      // The canvas blends in display space, so the pane cannot simply add light
      // over the room behind it: a tint premultiplied before tone mapping comes
      // out about twice as bright as it should. Instead the mirror share of the
      // pane covers the room (what a mirror does), and the tint and the mirrored
      // light are one surface colour at that cover, tone mapped as usual.
      replace(shader, 'fragmentShader', '#include <opaque_fragment>',
        `// Viewing/ghost fades still fade the whole pane, mirror included.
float paneFade = paneBaseOpacity > .00001 ? clamp(opacity / paneBaseOpacity, 0.0, 1.0) : 1.0;
float paneCover = clamp(diffuseColor.a + (paneFade - diffuseColor.a) * paneMirror, .0001, 1.0);
vec3 paneLight = (outgoingLight - totalSpecular) * diffuseColor.a + totalSpecular * paneFade;
gl_FragColor = vec4(paneLight / paneCover, paneCover);`);
    }
  };
  material.customProgramCacheKey = () => key + '|box-reflection-3|' + kind;
  if (kind === 'exterior') { material.premultipliedAlpha = true; material.depthWrite = false; }
  const attach = target => {
    Object.defineProperty(target.userData, 'reflection', {value: binding, configurable: true});
    binding.materials.add(target);
    target.addEventListener('dispose', () => binding.materials.delete(target));
  };
  attach(material);
  const clone = material.clone;
  material.clone = function() {
    const target = clone.call(this);
    target.onBeforeCompile = this.onBeforeCompile;
    target.customProgramCacheKey = this.customProgramCacheKey;
    target.clone = this.clone;
    attach(target);
    return target;
  };
  return material;
}

const area = poly => Math.abs(poly.reduce((sum, p, i) => {
  const q = poly[(i + 1) % poly.length]; return sum + p[0] * q[1] - q[0] * p[1];
}, 0)) / 2;
const centreOf = poly => [0, 1].map(k => (Math.min(...poly.map(p => p[k])) + Math.max(...poly.map(p => p[k]))) / 2);
const visible = object => { for (let p = object; p; p = p.parent) if (!p.visible) return false; return true; };

export function createReflectionProbes({scene, renderer, tier, extras = () => [], sky = () => null, uncut = () => null, now = () => performance.now(), warn = error => console.warn('House reflection capture failed:', error)}) {
  let probes = [], bindings = new Set(), queue = [], requested = false, quietAt = 0, unlit = false, disposed = false, lightsKey = null, lightsAt = -Infinity;
  const enabled = tier !== 'low';
  // A flat pool mirrors what stands beside it. One cube taken at the pool's
  // centre cannot place a wall ten metres away, so on high quality the largest
  // body's water level gets a true mirror image: the scene drawn once more from
  // the camera's reflection, at half size, only while that water is in view.
  // Bodies at another height, and medium quality, keep the cube.
  const planar = tier === 'high' ? {target:null, camera:new THREE.PerspectiveCamera(), boxes:[], hidden:[], hiddenAt:-Infinity, passes:0, active:false} : null;
  const frustum = new THREE.Frustum(), scratch = new THREE.Matrix4(), size = new THREE.Vector2();
  const eye = new THREE.Vector3(), aim = new THREE.Vector3(), up = new THREE.Vector3(), plane = new THREE.Plane(), clip = new THREE.Vector4(), corner = new THREE.Vector4();
  // What a reflection must not contain: markers, handles, effects, the water
  // itself and every other mirror.
  const excluded = (o, owner = null) => {
    const d = o.userData;
    return o.isSprite || o.isPoints || o.isLine || o.isHelper || o.layers.isEnabled(31) ||
      d.effectFixtures || d.effectFixture || d.fireFlame || d.reflectionExclude || d.preview || d.aimHandle || d.fixtureId || d.kind==='sheet' || o.name.startsWith('editor-') ||
      (owner && d.buildingId===owner) ||
      [].concat(o.material || []).some(m=>m.userData.waterSurface || m.userData.reflection || m.depthTest===false || m.name==='sheet');
  };
  function mirror(camera) {
    if (!planar) return;
    const water = probes.find(p=>p.kind==='water');
    let on = false;
    if (!unlit && !disposed && !planar.broken && water && camera.isPerspectiveCamera) {
      camera.updateMatrixWorld();
      camera.getWorldPosition(eye);
      if (eye.y > water.centre.y + .02) {
        frustum.setFromProjectionMatrix(scratch.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
        on = planar.boxes.some(box => Math.abs(box.min.y - water.centre.y) < .05 && frustum.intersectsBox(box));
      }
    }
    // A mirror that cannot be drawn is not retried every frame; the cube
    // stands in until the scene is next rebuilt.
    if (on) try { drawMirror(camera, water.centre.y); } catch (error) { on = false; planar.broken = true; warn(error); }
    planar.active = on;
    for (const b of bindings) if (b.kind==='water') {
      b.uniforms.waterPlanarActive.value = on ? 1 : 0;
      b.uniforms.waterPlanar.value = on ? planar.target.texture : null;
      if (on) { b.uniforms.waterPlanarHeight.value = water.centre.y; b.uniforms.waterPlanarMatrix.value.copy(scratch); }
    }
  }
  function drawMirror(camera, height) {
    renderer.getDrawingBufferSize(size);
    const w = Math.max(1, Math.floor(size.x / 2)), h = Math.max(1, Math.floor(size.y / 2));
    if (!planar.target) planar.target = new THREE.WebGLRenderTarget(w, h, {type:THREE.HalfFloatType, colorSpace:THREE.LinearSRGBColorSpace,
      generateMipmaps:false, minFilter:THREE.LinearFilter, magFilter:THREE.LinearFilter});
    else if (planar.target.width !== w || planar.target.height !== h) planar.target.setSize(w, h);
    // The camera's reflection in the water plane: same lens, mirrored pose.
    const virtual = planar.camera;
    camera.getWorldDirection(aim).add(eye); aim.y = 2 * height - aim.y;
    up.set(0, 1, 0).applyQuaternion(camera.getWorldQuaternion(new THREE.Quaternion())); up.y = -up.y;
    virtual.position.set(eye.x, 2 * height - eye.y, eye.z); virtual.up.copy(up); virtual.lookAt(aim);
    virtual.updateMatrixWorld();
    virtual.projectionMatrix.copy(camera.projectionMatrix);
    scratch.multiplyMatrices(virtual.projectionMatrix, virtual.matrixWorldInverse);
    // Nothing below the water belongs in the image, and the pool shell would
    // hide everything: put the near plane over the water (an oblique frustum).
    // It sits MIRROR_LIFT above the water, not on it. Seen from below, the deck,
    // coping and lawn around a pool are a slab underside that covers the whole
    // image outside the pool's opening; a wave sends the lookup out there and
    // the water shows grey blotches. A ray rising from the water never meets
    // that underside, so the slab is cut away and the lookup finds the house,
    // trees and sky behind it.
    plane.set(up.set(0, 1, 0), -(height + MIRROR_LIFT)).applyMatrix4(virtual.matrixWorldInverse);
    clip.set(plane.normal.x, plane.normal.y, plane.normal.z, plane.constant);
    const pm = virtual.projectionMatrix.elements;
    corner.set((Math.sign(clip.x) + pm[8]) / pm[0], (Math.sign(clip.y) + pm[9]) / pm[5], -1, (1 + pm[10]) / pm[14]);
    clip.multiplyScalar(2 / clip.dot(corner));
    pm[2] = clip.x; pm[6] = clip.y; pm[10] = clip.z + 1; pm[14] = clip.w;
    virtual.projectionMatrixInverse.copy(virtual.projectionMatrix).invert();
    // The scene walk that finds what to leave out runs twice a second, not
    // every frame; the hiding itself is a short list.
    if (now() - planar.hiddenAt >= 500) {
      planar.hiddenAt = now(); planar.hidden = [];
      scene.traverse(o => { if (excluded(o)) planar.hidden.push(o); });
    }
    const hidden = [...planar.hidden, ...extras()].filter(Boolean).map(o => [o, o.visible]);
    const save = {target:renderer.getRenderTarget(), face:renderer.getActiveCubeFace(), mip:renderer.getActiveMipmapLevel(),
      auto:renderer.autoClear, xr:renderer.xr.enabled, tone:renderer.toneMapping,
      viewport:renderer.getViewport(new THREE.Vector4()), scissor:renderer.getScissor(new THREE.Vector4()), scissorTest:renderer.getScissorTest(),
      clipping:renderer.clippingPlanes, local:renderer.localClippingEnabled,
      shadowAuto:renderer.shadowMap.autoUpdate, shadowNeeds:renderer.shadowMap.needsUpdate,
      info:{...renderer.info.render}, infoAuto:renderer.info.autoReset};
    try {
      for (const [o] of hidden) o.visible = false;
      // Shadows are sampled as the picture has them; none is drawn again.
      renderer.shadowMap.autoUpdate = renderer.shadowMap.needsUpdate = false;
      renderer.autoClear = true; renderer.xr.enabled = false; renderer.toneMapping = THREE.NoToneMapping;
      // The cut planes on a material stay on: the mirror shows the house as
      // the picture has it, and a material whose plane count differs between
      // two passes of one frame is set up again on every pass.
      renderer.info.autoReset = false;
      renderer.setRenderTarget(planar.target);
      renderer.render(scene, virtual);
      planar.passes++;
    } finally {
      for (const [o, value] of hidden) o.visible = value;
      renderer.setRenderTarget(save.target, save.face, save.mip); renderer.autoClear = save.auto;
      renderer.setViewport(save.viewport); renderer.setScissor(save.scissor); renderer.setScissorTest(save.scissorTest);
      renderer.xr.enabled = save.xr; renderer.toneMapping = save.tone;
      renderer.clippingPlanes = save.clipping; renderer.localClippingEnabled = save.local;
      renderer.shadowMap.autoUpdate = save.shadowAuto; renderer.shadowMap.needsUpdate = save.shadowNeeds;
      Object.assign(renderer.info.render, save.info); renderer.info.autoReset = save.infoAuto;
    }
  }
  function apply(binding) {
    const p = binding.probe, active = !unlit && !!p?.fresh;
    binding.uniforms.probeActive.value = active ? 1 : 0;
    if (p) {
      binding.uniforms.probeCentre.value.copy(p.centre);
      binding.uniforms.probeMin.value.copy(p.box.min); binding.uniforms.probeMax.value.copy(p.box.max);
    }
    const waters = probes.filter(p=>p.kind==='water');
    if (binding.kind==='water') {
      binding.uniforms.waterProbeCount.value = unlit ? 0 : waters.length;
      waters.forEach((p,i)=>{
        binding.uniforms.waterProbeCentre.value[i].copy(p.centre);
        binding.uniforms.waterProbeFresh.value[i] = p.fresh ? 1 : 0;
        binding.uniforms['waterProbe'+i].value = p.target.texture;
      });
    }
    for (const material of binding.materials) {
      const map = binding.kind==='water'
        ? (!unlit && waters.length && waters.every(p=>p.fresh) ? waters[0].target.texture : null)
        : (active ? p.target.texture : null);
      if (material.envMap !== map) { material.envMap = map; material.needsUpdate = true; }
      // Captures already contain current scene lighting. Explicit envMap intensity
      // is independent of scene.environmentIntensity (three's standard contract).
      material.envMapIntensity = 1;
    }
  }
  function request() {
    if (!enabled || disposed) return;
    requested = true; quietAt = now(); queue = [];
    for (const p of probes) p.fresh = false;
    // Keep the last successful cube displayed while a round is queued. A failed
    // capture explicitly falls back to sky, never to a partially rendered cube.
  }
  function rebuild(plan, root) {
    if (!enabled || disposed) return;
    root.updateMatrixWorld(true);
    bindings = new Set();
    const waterVisible = new Set();
    root.traverse(o => {
      for (const m of o.material ? [].concat(o.material) : []) {
        const b = m.userData.reflection;
        if (b) { bindings.add(b); if (b.kind === 'water' && visible(o)) b.owners.forEach(id=>waterVisible.add(id)); }
      }
    });
    const candidates = [];
    if (planar) { planar.boxes = []; planar.broken = false; }
    for (const body of waterBodies(plan)) if (waterVisible.has(body.id)) {
      const c = centreOf(body.polygon);
      if (planar) planar.boxes.push(new THREE.Box3().setFromPoints(body.polygon.map(p => new THREE.Vector3(p[0]*FT, body.height*FT, -p[1]*FT))));
      candidates.push({id:'water:' + body.id, owner:body.id, kind:'water', area:area(body.polygon), centre:new THREE.Vector3(c[0]*FT, body.height*FT, -c[1]*FT)});
    }
    for (const b of plan.buildings || []) {
      const poly = buildingFootprint(b); if (!poly.length) continue;
      const c = centreOf(poly), a = (b.rotation || 0)*Math.PI/180, pos = b.position || [0,0];
      candidates.push({id:'exterior:' + b.id, owner:b.id, kind:'exterior', area:area(poly), centre:new THREE.Vector3(
        (pos[0]+c[0]*Math.cos(a)-c[1]*Math.sin(a))*FT,
        (buildingBase(plan,b)+Math.min(...b.levels.map(l=>l.elevation)))*FT+1.5,
        -(pos[1]+c[0]*Math.sin(a)+c[1]*Math.cos(a))*FT)});
    }
    // Reserve one of each kind when both exist, then spend the remaining budget
    // on the largest candidates. Within each kind only its largest bodies survive.
    candidates.sort((a,b)=>b.area-a.area || a.id.localeCompare(b.id));
    const chosen = ['water','exterior'].map(kind=>candidates.find(p=>p.kind===kind)).filter(Boolean);
    for (const p of candidates) if (chosen.length < 4 && !chosen.includes(p)) chosen.push(p);
    const box = new THREE.Box3().setFromObject(root);
    const lot = plan.site?.lot;
    if (lot?.length) {
      box.min.x = Math.min(...lot.map(p=>p[0]))*FT; box.max.x = Math.max(...lot.map(p=>p[0]))*FT;
      box.min.z = -Math.max(...lot.map(p=>p[1]))*FT; box.max.z = -Math.min(...lot.map(p=>p[1]))*FT;
    }
    if (box.isEmpty()) box.set(new THREE.Vector3(-20,0,-20), new THREE.Vector3(20,30,20));
    box.min.y = Math.min(0,box.min.y); box.max.y = Math.max(30,box.max.y+10);
    const old = probes;
    probes = chosen.map(row => {
      const previous = old.find(p=>p.id===row.id && p.centre.equals(row.centre) && p.box.equals(box));
      if (previous) return previous;
      const target = new THREE.WebGLCubeRenderTarget(256, {type:THREE.HalfFloatType, colorSpace:THREE.LinearSRGBColorSpace,
        generateMipmaps:true, minFilter:THREE.LinearMipmapLinearFilter, magFilter:THREE.LinearFilter});
      const camera = new THREE.CubeCamera(.05, Math.max(100,box.getSize(new THREE.Vector3()).length()*2), target);
      camera.position.copy(row.centre);
      return {...row, box:box.clone(), target, camera, captures:0, fresh:false};
    });
    for (const p of old) if (!probes.includes(p)) p.target.dispose();
    for (const b of bindings) {
      const peers = probes.filter(p=>p.kind===b.kind), own = candidates.find(p=>p.kind===b.kind && p.owner===b.owner);
      b.probe = peers.find(p=>p.owner===b.owner) || (own && peers.sort((a,c)=>a.centre.distanceToSquared(own.centre)-c.centre.distanceToSquared(own.centre))[0]) || null;
      apply(b);
    }
    request();
  }
  function capture(p) {
    const hidden = new Map(), shadows = [];
    let restoreCut = null;
    const save = {target:renderer.getRenderTarget(), face:renderer.getActiveCubeFace(), mip:renderer.getActiveMipmapLevel(),
      auto:renderer.autoClear, xr:renderer.xr.enabled, tone:renderer.toneMapping,
      color:renderer.getClearColor(new THREE.Color()), alpha:renderer.getClearAlpha(),
      viewport:renderer.getViewport(new THREE.Vector4()), scissor:renderer.getScissor(new THREE.Vector4()), scissorTest:renderer.getScissorTest(),
      mipmaps:p.target.texture.mipmapsAutoUpdate,
      clipping:renderer.clippingPlanes, local:renderer.localClippingEnabled, background:scene.background,
      backgroundIntensity:scene.backgroundIntensity,
      shadow:renderer.shadowMap.enabled, shadowAuto:renderer.shadowMap.autoUpdate, shadowNeeds:renderer.shadowMap.needsUpdate,
      info:{...renderer.info.render}, infoAuto:renderer.info.autoReset};
    const hide = o => { if (o && !hidden.has(o)) { hidden.set(o,o.visible); o.visible = false; } };
    try {
      scene.traverse(o => {
        if (o.shadow) { shadows.push([o.shadow,o.shadow.autoUpdate,o.shadow.needsUpdate]); o.shadow.autoUpdate = o.shadow.needsUpdate = false; }
        if (excluded(o, p.kind==='exterior' ? p.owner : null)) hide(o);
      });
      extras().forEach(hide);
      // Keep shadow sampling, but prohibit every shadow render, including a
      // pending sun invalidation. Restore each light's flags exactly afterwards.
      renderer.shadowMap.autoUpdate = renderer.shadowMap.needsUpdate = false;
      renderer.autoClear = true; renderer.xr.enabled = false; renderer.toneMapping = THREE.NoToneMapping;
      // Clipping stays on, as in the mirror pass: switching it off made every
      // clipped material compile a second program on the main thread. The cut
      // planes are lifted instead, so the cube still holds the whole house.
      renderer.info.autoReset = false; restoreCut = uncut();
      scene.background = sky() || save.background;
      scene.backgroundIntensity = scene.environmentIntensity;
      p.camera.update(renderer,scene);
      // three prefilters a render-target cube once and reuses that result until
      // told the cube changed; without this, glass keeps its first capture forever.
      p.target.texture.needsPMREMUpdate = true;
      p.captures++; p.fresh = true;
    } catch (error) { p.fresh = false; warn(error); }
    finally {
      restoreCut?.();
      for (const [o,value] of hidden) o.visible = value;
      for (const [shadow,auto,needs] of shadows) { shadow.autoUpdate = auto; shadow.needsUpdate = needs; }
      scene.background = save.background;
      scene.backgroundIntensity = save.backgroundIntensity;
      renderer.setRenderTarget(save.target,save.face,save.mip); renderer.autoClear = save.auto;
      renderer.setClearColor(save.color,save.alpha); renderer.setViewport(save.viewport); renderer.setScissor(save.scissor); renderer.setScissorTest(save.scissorTest);
      p.target.texture.mipmapsAutoUpdate = save.mipmaps;
      renderer.xr.enabled = save.xr; renderer.toneMapping = save.tone;
      renderer.clippingPlanes = save.clipping; renderer.localClippingEnabled = save.local;
      renderer.shadowMap.enabled = save.shadow; renderer.shadowMap.autoUpdate = save.shadowAuto; renderer.shadowMap.needsUpdate = save.shadowNeeds;
      Object.assign(renderer.info.render,save.info); renderer.info.autoReset = save.infoAuto;
      for (const b of bindings) if (b.probe===p || b.kind==='water') apply(b);
    }
  }
  return {
    rebuild, request, mirror,
    setUnlit(on) { if (unlit===on) return; unlit=on; for (const b of bindings) apply(b); if (!on) request(); },
    frame() {
      if (!enabled || unlit || disposed) return;
      // Live light uniforms may change without a model rebuild. Observe their
      // result, excluding sun/moon (the time-look minute gate owns those).
      // Twice a second is plenty: a capture waits 1.5 seconds of quiet anyway,
      // and a whole-scene walk has no place in every frame.
      if (now()-lightsAt>=500) {
        lightsAt=now();
        const lights=[];
        scene.traverse(o=>{if(o.isPointLight || o.isSpotLight || o.isRectAreaLight) lights.push([o.uuid,visible(o),o.intensity,o.color?.getHex(),...o.getWorldPosition(new THREE.Vector3()).toArray(),o.distance,o.width,o.height,o.angle,...(o.target?.getWorldPosition(new THREE.Vector3()).toArray() || [])]);});
        const key=JSON.stringify(lights); if (lightsKey!==key) { lightsKey=key; request(); }
      }
      if (requested && now()-quietAt>=1500) { queue=[...probes]; requested=false; }
      const p=queue.shift(); if (p) capture(p);
    },
    info() { return {tier, ...(planar ? {planar:{active:planar.active, passes:planar.passes, size:planar.target ? [planar.target.width, planar.target.height] : null}} : {}), probes:probes.map(p=>({id:p.id,kind:p.kind,captures:p.captures,fresh:p.fresh,centre:p.centre.toArray(),box:{min:p.box.min.toArray(),max:p.box.max.toArray()}})), pending:requested || queue.length>0}; },
    dispose() { disposed=true; queue=[]; requested=false; const old=probes; probes=[]; for (const b of bindings) { b.probe=null; apply(b); } for (const p of old) p.target.dispose(); planar?.target?.dispose(); bindings.clear(); },
  };
}
