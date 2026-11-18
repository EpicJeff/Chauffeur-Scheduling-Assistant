import * as THREE from 'three';
import {WATER_VERTEX, WATER_POSITION, WAVE_GLSL, FIELD_GLSL, waterReplace, keepWaterHook} from './water_surface.js';

export const CHOP_CAUSTIC_CONTRAST_GAIN = .9;
export const CHOP_CAUSTIC_SPEED_GAIN = .8;
export const CHOP_FLOOR_WOBBLE_GAIN = .4;

// One clone per source/level (source/body with a field), cached by the pool owner.
export function underwaterMaterial(source, body, {tier = 'medium', simulation = null, tint = '#7fd0e6', motion = null, regions = []} = {}) {
  const material = source.clone(), before = source.onBeforeCompile, key = source.customProgramCacheKey();
  const uniforms = {waterTime:{value:0}, waterMotion:motion || {value:new THREE.Vector3()}, waterLevel:{value:body.height * .3048},
    waterTint:{value:tint?.isColor ? tint.clone() : new THREE.Color(tint)},
    waterSun:{value:3}, waterSunDirection:{value:new THREE.Vector3(.4, .8, .3).normalize()}};
  if (simulation) Object.assign(uniforms, simulation.uniforms);
  // Equal-height basins share a material and draw. Select their motion in the
  // shader so a flush spa can stay calm while the surrounding pool is running.
  let regionUniforms = '', regionTests = '';
  regions.forEach((region, i) => {
    uniforms['waterRegionMotion' + i] = region.motion;
    uniforms['waterRegionPolygon' + i] = {value:region.polygon.map(p => new THREE.Vector2(...p))};
    const count = region.polygon.length;
    regionUniforms += `uniform vec3 waterRegionMotion${i}; uniform vec2 waterRegionPolygon${i}[${count}];\n`;
    regionTests += `{
  bool inside = false;
  for (int i = 0; i < ${count}; i++) {
    vec2 a = waterRegionPolygon${i}[i], b = waterRegionPolygon${i}[i == 0 ? ${count - 1} : i - 1];
    if ((a.y > p.y) != (b.y > p.y)) {
      if (p.x < (b.x-a.x) * (p.y-a.y) / (b.y-a.y) + a.x) inside = !inside;
    }
  }
  if (inside) return waterRegionMotion${i};
}\n`;
  });
  const motionGlsl = `uniform vec3 waterMotion;\n${regionUniforms}
vec3 waterMotionAt(vec2 p) {
${regionTests}return waterMotion;
}\n`;
  const iterations = tier === 'max' ? 5 : tier === 'high' ? 4 : 3;
  const prepare = (shader, renderer, unlit) => {
    if (!unlit) before.call(material, shader, renderer);
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = WATER_VERTEX + shader.vertexShader;
    waterReplace(shader, 'vertexShader', '#include <project_vertex>', WATER_POSITION + '\n#include <project_vertex>');
    shader.fragmentShader = WATER_VERTEX + WAVE_GLSL + motionGlsl + (simulation ? FIELD_GLSL : '') + `
uniform float waterLevel; uniform vec3 waterTint;
uniform float waterSun; uniform vec3 waterSunDirection;
// The bright net a rippled surface focuses on the floor: a point is warped through
// itself a few times and the folds become the light lines. Returns the change in
// sunlight: bright lines over a floor that is barely dimmed between them, because
// dark cells read as stains from above. depth is metres.
float waterCaustic(vec2 p, float depth, vec3 motion) {
  vec2 q = p * 1.35, i = q;
  float c = 1.0, time = (waterTime + motion.z) * .55;
  for (int n = 0; n < ${iterations}; n++) {
    float t = time * (1.0 - 3.5 / float(n + 1));
    i = q + vec2(cos(t - i.x) + sin(t + i.y), sin(t - i.y) + cos(t + i.x));
    vec2 fold = vec2(sin(i.x + t), cos(i.y + t));
    c += 1.0 / length(1.25 / (fold + sign(fold) * .0001 + .00001));
  }
  c = 1.17 - pow(c / ${iterations.toFixed(1)}, 1.4);
  float net = pow(abs(c), 8.0);
  // Faint in the shallows where the light has not yet focused, soft again when deep.
  float reach = smoothstep(0.0, .25, depth) * exp(-depth * .18);
  return max(net * 6.5 - .55, -.12) * reach / (1.0 + fwidth(net) * 3.0) * (1.0 + motion.x * ${CHOP_CAUSTIC_CONTRAST_GAIN.toFixed(2)});
}
` + shader.fragmentShader;
    // These are the material's own lookups. Offsetting each transformed UV by
    // its map transform keeps normal/roughness and tile lines in agreement.
    if (tier !== 'low') for (const [chunk, uv, transform] of [
      ['map_fragment','vMapUv','mapTransform'], ['normal_fragment_maps','vNormalMapUv','normalMapTransform'],
      ['roughnessmap_fragment','vRoughnessMapUv','roughnessMapTransform'],
    ]) {
      if (unlit && chunk === 'roughnessmap_fragment') continue;
      if (!THREE.ShaderChunk[chunk].includes(uv)) throw new Error('Water shader missing map UV: ' + uv);
      const text = THREE.ShaderChunk[chunk].replaceAll(uv, `(${uv} + (mat2(${transform}) * waterWobble))`);
      // UV transform uniforms live in the vertex shader in three; declare them
      // for fragment use only when their corresponding map is compiled in.
      const define = chunk === 'map_fragment' ? 'USE_MAP' : chunk === 'normal_fragment_maps' ? 'USE_NORMALMAP' : 'USE_ROUGHNESSMAP';
      shader.fragmentShader = `#ifdef ${define}\nuniform mat3 ${transform};\n#endif\n` + shader.fragmentShader;
      waterReplace(shader, 'fragmentShader', '#include <' + chunk + '>', text);
    }
  };
  // Compose the remaining patches after UV replacement; no nested shader hook
  // is installed on the final material.
  const compile = (shader, renderer, unlit = false) => {
    prepare(shader, renderer, unlit);
    waterReplace(shader, 'fragmentShader', 'void main() {', `void main() {
float waterDepth = max(0.0, waterLevel - vWaterWorld.y);
vec2 waterPoint = vec2(vWaterWorld.x, -vWaterWorld.z) / .3048;
vec3 waterBodyMotion = waterMotionAt(waterPoint);
${tier !== 'low' ? `vec2 waterWobble = waterSlope(waterPoint, waterBodyMotion) * waterDepth * .9 * (1.0 + waterBodyMotion.x * ${CHOP_FLOOR_WOBBLE_GAIN.toFixed(2)});
${simulation ? 'waterWobble += waterFieldShape(waterPoint).xy * waterDepth * .48;' : ''}` : ''}`);
    // Only directional sunlight is modulated; hemisphere/environment and local
    // lamps are never multiplied by the projected caustic pattern.
    if (!unlit) {
      const direct = THREE.ShaderChunk.lights_fragment_begin;
      const anchor = 'getDirectionalLightInfo( directionalLight, directLight );';
      if (!direct.includes(anchor)) throw new Error('Water shader missing directional light anchor');
      waterReplace(shader, 'fragmentShader', '#include <lights_fragment_begin>', direct.replace(anchor, `${anchor}
if (waterDepth > 0.0 && waterSun > 0.0) {
  vec3 waterSunV = normalize(mat3(viewMatrix) * waterSunDirection);
  float sunMatch = step(.999, dot(waterSunV, directLight.direction));
  float facing = max(0.0, dot(normal, waterSunV));
  vec2 projected = waterPoint + vec2(waterSunDirection.x, -waterSunDirection.z) * waterDepth / (.3048 * max(.2, waterSunDirection.y));
  float focus = waterCaustic(projected, waterDepth, waterBodyMotion);
  ${simulation ? 'focus += clamp(-waterFieldShape(projected).z * .12, -.35, .65) * exp(-waterDepth * .55);' : ''}
  directLight.color *= 1.0 + focus * facing * sunMatch * min(1.0, waterSun / 3.0);
}`));
    }
    waterReplace(shader, 'fragmentShader', '#include <opaque_fragment>', `
if (waterDepth > 0.0) {
  vec3 ray = normalize(cameraPosition - vWaterWorld);
  float cosRefracted = sqrt(max(.0, 1.0 - (1.0-ray.y*ray.y)/(1.33*1.33)));
  // Light goes down to the surface and back up along the refracted view ray.
  float path = waterDepth * (1.0 + 1.0 / max(.35, cosRefracted));
  // Stronger than clear water measures: a sunlit pale floor sits far above white
  // before tone mapping, and a physical rate would leave it white after.
  vec3 attenuation = exp(-vec3(1.1,.28,.14) * path);
  float lit = min(1.0, dot(outgoingLight, vec3(.3,.6,.1)) * 1.5);
  float haze = 1.0 - exp(-.11 * path);
  outgoingLight = outgoingLight * attenuation + waterTint * vec3(.3,.72,.9) * haze * lit;
}
#include <opaque_fragment>`);
  };
  material.onBeforeCompile = (shader, renderer) => compile(shader, renderer);
  material.customProgramCacheKey = () => key + '|underwater-5:' + tier + (simulation ? '|water-field-1' : '') + (regions.length ? '|water-regions:' + regions.map(r => r.polygon.length).join(',') : '');
  Object.defineProperty(material.userData, 'waterUnlit', {value:{
    hook:(shader, renderer) => compile(shader, renderer, true), key:() => material.customProgramCacheKey() + '|matcap',
  }});
  keepWaterHook(material, 'underwater', uniforms);
  return {material, body, uniforms, simulation};
}
