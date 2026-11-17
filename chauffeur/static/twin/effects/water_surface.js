import * as THREE from 'three';

export const CHOP_WAVE_STRENGTH_GAIN = 2.2;
export const CHOP_WAVE_SPEED_GAIN = .65;
export const CHOP_SHIMMER_GAIN = .35;

// World positions are metres in the mounted scene; plan geometry and sources are feet.
export const WATER_VERTEX = `varying vec3 vWaterWorld;
`;
export const WATER_POSITION = `vWaterWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;`;
export const WAVE_GLSL = `
uniform float waterTime;
// Nine wave trains in plan feet: a swell, a chop and a fine ripple, each sent
// three ways about 120 degrees apart, so crests cross and collide instead of
// marching one way. A negative speed carries a train along its own k. Each one
// is warped so no straight crest line shows, and fades out before it would alias.
// Running features stir the short waves hardest.
vec2 waterTrain(vec2 p, vec2 k, float speed, float slope, float time) {
  float phase = dot(p, k) + time * speed;
  return normalize(k) * cos(phase) * slope * (1.0 - smoothstep(.6, 2.6, fwidth(phase)));
}
vec2 waterSlope(vec2 p, vec3 motion) {
  float time = waterTime + motion.y;
  vec2 warp = vec2(sin(p.y * .31 + time * .21), cos(p.x * .27 - time * .17)) * 1.4;
  vec2 a = p + warp, b = p - warp * .7, c = p + warp.yx * .5;
  vec2 swell = waterTrain(a, vec2(.658, .239), -1.05, .05, time)
    + waterTrain(b, vec2(-.628, .527), -1.13, .05, time)
    + waterTrain(c, vec2(-.106, -.601), -.98, .05, time);
  vec2 chop = waterTrain(b, vec2(.492, 1.835), -1.72, .06, time)
    + waterTrain(c, vec2(-2.125, -.569), -1.85, .06, time)
    + waterTrain(a, vec2(1.202, -1.202), -1.63, .06, time);
  vec2 fine = waterTrain(p + warp * .5, vec2(3.253, 3.253), -2.68, .05, time)
    + waterTrain(p - warp * .4, vec2(-5.119, 1.372), -2.88, .05, time)
    + waterTrain(p + warp.yx * .3, vec2(1.061, -3.96), -2.53, .05, time);
  float stir = motion.x * ${CHOP_WAVE_STRENGTH_GAIN.toFixed(2)};
  return swell * (1.0 + stir * .6) + chop * (1.0 + stir) + fine * (1.0 + stir * 1.5);
}
`;
export const FIELD_GLSL = `
uniform sampler2D waterField;
uniform vec4 waterFieldBounds;
uniform vec2 waterFieldTexel;
uniform float waterFieldActive;
vec2 waterFieldUv(vec2 p) { return (p - waterFieldBounds.xy) / waterFieldBounds.zw; }
float waterFieldHeight(vec2 uv, float centre) {
  vec4 state = texture2D(waterField, uv);
  return state.a < .5 || any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0))) ? centre : state.r;
}
vec3 waterFieldShape(vec2 p) {
  if (waterFieldActive < .5) return vec3(0.0);
  vec2 uv = waterFieldUv(p), t = waterFieldTexel;
  if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return vec3(0.0);
  // The simulation writes alpha 0 into dry cells. A dry neighbour is a wall and
  // carries this cell's height, as it does inside the simulation; reading its
  // zero instead tilts the last wet cell and draws a bright line along the wall.
  vec4 centre = texture2D(waterField, uv);
  if (centre.a < .5) return vec3(0.0);
  float h = centre.r;
  float l = waterFieldHeight(uv - vec2(t.x, 0.0), h);
  float r = waterFieldHeight(uv + vec2(t.x, 0.0), h);
  float b = waterFieldHeight(uv - vec2(0.0, t.y), h);
  float f = waterFieldHeight(uv + vec2(0.0, t.y), h);
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
  const uniforms = {waterTime: {value: 0}, waterMotion:{value:new THREE.Vector3()}, waterBaseOpacity:{value:Math.max(.0001, source.opacity)}};
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
    shader.fragmentShader = WATER_VERTEX + WAVE_GLSL + 'uniform float waterBaseOpacity; uniform vec3 waterMotion;\n' + (sourced ? RIPPLE_GLSL : '') + (simulation ? FIELD_GLSL : '') + shader.fragmentShader;
    waterReplace(shader, 'fragmentShader', '#include <color_fragment>', `#include <color_fragment>
vec2 waterPoint = vec2(vWaterWorld.x, -vWaterWorld.z) / .3048;
vec2 rippleSlope = waterSlope(waterPoint, waterMotion);
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
    if (!unlit) waterReplace(shader, 'fragmentShader', '#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>\nroughnessFactor = clamp(roughnessFactor, .08, .12) / (1.0 + waterMotion.x * ${CHOP_SHIMMER_GAIN.toFixed(2)});`);
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
