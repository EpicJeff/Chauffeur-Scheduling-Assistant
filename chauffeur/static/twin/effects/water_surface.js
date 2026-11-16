import * as THREE from 'three';

// World positions are metres in the mounted scene; plan geometry and sources are feet.
export const WATER_VERTEX = `varying vec3 vWaterWorld;
`;
export const WATER_POSITION = `vWaterWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;`;
export const WAVE_GLSL = `
uniform float waterTime;
// Four wave trains in plan feet, from a slow swell down to wind chop. Each one is
// warped by the others so no straight crest line shows, and each fades out before
// it would alias.
vec2 waterTrain(vec2 p, vec2 k, float speed, float slope) {
  float phase = dot(p, k) + waterTime * speed;
  return normalize(k) * cos(phase) * slope * (1.0 - smoothstep(.6, 2.6, fwidth(phase)));
}
vec2 waterSlope(vec2 p) {
  vec2 warp = vec2(sin(p.y * .31 + waterTime * .21), cos(p.x * .27 - waterTime * .17)) * 1.4;
  vec2 q = p + warp;
  return waterTrain(q, vec2(.62, .33), -.74, .05)
    + waterTrain(q + warp, vec2(-1.1, 1.5), 1.2, .055)
    + waterTrain(p - warp, vec2(2.9, 1.7), -1.9, .045)
    + waterTrain(p + warp * .5, vec2(-3.6, -5.2), 2.7, .035);
}
`;
export const FIELD_GLSL = `
uniform sampler2D waterField;
uniform vec4 waterFieldBounds;
uniform vec2 waterFieldTexel;
uniform float waterFieldActive;
vec2 waterFieldUv(vec2 p) { return (p - waterFieldBounds.xy) / waterFieldBounds.zw; }
vec3 waterFieldShape(vec2 p) {
  if (waterFieldActive < .5) return vec3(0.0);
  vec2 uv = waterFieldUv(p), t = waterFieldTexel;
  if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return vec3(0.0);
  float h = texture2D(waterField, uv).r;
  float l = texture2D(waterField, uv - vec2(t.x, 0.0)).r;
  float r = texture2D(waterField, uv + vec2(t.x, 0.0)).r;
  float b = texture2D(waterField, uv - vec2(0.0, t.y)).r;
  float f = texture2D(waterField, uv + vec2(0.0, t.y)).r;
  vec2 cell = t * waterFieldBounds.zw;
  return vec3(vec2(r-l, f-b) / (2.0 * cell),
    (l+r-2.0*h)/(cell.x*cell.x) + (b+f-2.0*h)/(cell.y*cell.y));
}
`;

// Fail loudly when three or an earlier hook removes an anchor. A silent replace
// would leave a material that appears to work while omitting half the water model.
export function waterReplace(shader, stage, anchor, replacement) {
  if (!shader[stage].includes(anchor)) throw new Error('Water shader missing anchor: ' + anchor);
  shader[stage] = shader[stage].replace(anchor, replacement);
}

export function keepWaterHook(material, name, uniforms) {
  Object.defineProperty(material.userData, name, {value: uniforms, configurable: true});
  const clone = material.clone;
  material.clone = function() {
    const target = clone.call(this);
    target.onBeforeCompile = this.onBeforeCompile;
    target.customProgramCacheKey = this.customProgramCacheKey;
    target.clone = this.clone;
    Object.defineProperty(target.userData, name, {value: uniforms, configurable: true});
    if (this.userData.waterUnlit) Object.defineProperty(target.userData, 'waterUnlit', {value:this.userData.waterUnlit});
    if (this.userData.ripples) Object.defineProperty(target.userData, 'ripples', {value: this.userData.ripples, configurable: true});
    return target;
  };
}

const RIPPLE_GLSL = `
uniform float rippleTime; uniform vec4 rippleLines[8]; uniform float rippleStrength[8];
`;
const RIPPLE_SLOPE = `
float sourceFoam = 0.0;
for (int i = 0; i < 8; i++) {
  vec2 a = rippleLines[i].xy, run = rippleLines[i].zw - a;
  vec2 delta = waterPoint - a - run * clamp(dot(waterPoint-a, run) / max(dot(run,run), .0001), 0.0, 1.0);
  float d = length(delta), phase = d * 9.0 - rippleTime * 4.5;
  if (waterAnalytic > .5) {
    float fade = exp(-d * .65) * smoothstep(0.0, .16, d);
    float wave = (sin(phase) + .28 * sin(phase * 1.73 + .8)) * (1.0 - smoothstep(.5, 3.14, fwidth(phase)));
    rippleSlope += delta / max(d, .01) * wave * fade * rippleStrength[i] * .24;
  }
  sourceFoam += exp(-d*d*10.0) * (.65 + .35*sin(phase*1.7)) * rippleStrength[i];
}
diffuseColor.rgb = mix(diffuseColor.rgb, vec3(.92,.97,.98), min(.65, sourceFoam * .5));
`;

export function surfaceMaterial(source, body = null, {tier = 'medium', simulation = null} = {}) {
  const material = source.clone(), before = source.onBeforeCompile, key = source.customProgramCacheKey();
  const sourced = !!body?.sources?.length;
  const uniforms = {waterTime: {value: 0}, waterBaseOpacity:{value:Math.max(.0001, source.opacity)}};
  if (sourced) Object.assign(uniforms, {
    rippleTime: {value: 0}, rippleLines: {value: Array.from({length:8}, () => new THREE.Vector4())},
    rippleStrength: {value: Array(8).fill(0)},
  });
  if (simulation) Object.assign(uniforms, simulation.uniforms);
  // Keep the slot's roughness parameter intact (and editable); the optical
  // water interface uses its own narrow standard specular lobe in the shader.
  material.transparent = true; material.depthWrite = false;
  const compile = (shader, renderer, unlit = false) => {
    if (!unlit) before.call(material, shader, renderer);
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = WATER_VERTEX + shader.vertexShader;
    waterReplace(shader, 'vertexShader', '#include <project_vertex>', WATER_POSITION + '\n#include <project_vertex>');
    shader.fragmentShader = WATER_VERTEX + WAVE_GLSL + 'uniform float waterBaseOpacity;\n' + (sourced ? RIPPLE_GLSL : '') + (simulation ? FIELD_GLSL : '') + shader.fragmentShader;
    waterReplace(shader, 'fragmentShader', '#include <color_fragment>', `#include <color_fragment>
vec2 waterPoint = vec2(vWaterWorld.x, -vWaterWorld.z) / .3048;
vec2 rippleSlope = waterSlope(waterPoint);
float waterAnalytic = ${simulation ? '1.0 - waterFieldActive' : '1.0'};
${sourced ? RIPPLE_SLOPE : ''}
${simulation ? 'rippleSlope += waterFieldShape(waterPoint).xy;' : ''}`);
    waterReplace(shader, 'fragmentShader', '#include <normal_fragment_maps>', `#include <normal_fragment_maps>
normal = normalize(normal + mat3(viewMatrix) * vec3(rippleSlope.x, 0.0, -rippleSlope.y));
vec3 waterView = normalize(cameraPosition - vWaterWorld);
vec3 waterNormal = inverseTransformDirection(normal, viewMatrix);
float waterFresnel = .02 + .98 * pow(1.0 - abs(dot(waterNormal, waterView)), 5.0);
// Retain map alpha and the native opacity uniform used by viewing/ghost clones.
diffuseColor.a *= mix(.30, .92, waterFresnel) / waterBaseOpacity;`);
    if (!unlit) waterReplace(shader, 'fragmentShader', '#include <roughnessmap_fragment>', '#include <roughnessmap_fragment>\nroughnessFactor = clamp(roughnessFactor, .08, .12);');
  };
  material.onBeforeCompile = (shader, renderer) => compile(shader, renderer);
  material.customProgramCacheKey = () => key + '|water-surface-2' + (sourced ? '|water-ripples-2' : '') + (simulation ? '|water-field-1' : '');
  Object.defineProperty(material.userData, 'waterUnlit', {value:{
    hook:(shader, renderer) => compile(shader, renderer, true), key:() => material.customProgramCacheKey() + '|matcap',
  }});
  keepWaterHook(material, 'waterSurface', uniforms);
  if (sourced) Object.defineProperty(material.userData, 'ripples', {value:uniforms, configurable:true});
  return {material, body, uniforms, simulation, tier};
}
