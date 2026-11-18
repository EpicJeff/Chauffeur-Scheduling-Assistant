import * as THREE from 'three';
import { waterReplace } from './water_surface.js';

// Falling water on the pool water's own footing: a lit standard surface that
// mirrors the sky and catches the sun and the lamps, laid over what stands
// behind it like the pool's surface over its body. Ripples run down the sheet
// and stretch as the water speeds up; air whitens it toward the landing.
// Uniform names match the unlit effect water, which the effect driver updates.
// The standard material declares its own opacity, so the driver's fade goes by sheetFade.
const HEAD = `uniform float time; uniform float strength; uniform float sheetFade; uniform float span; uniform float fall; uniform vec3 glow;
varying vec2 vSheet;
float sheetHash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float sheetNoise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
  return mix(mix(sheetHash(i),sheetHash(i+vec2(1.,0.)),f.x),mix(sheetHash(i+vec2(0.,1.)),sheetHash(i+1.),f.x),f.y);}
`;
// Feet along the lip and down the fall. Falling from rest, water covers
// distance as the square of time, so the pattern scrolls in the root of the
// fall and stretches as it goes down.
const SHEET = `
float sheetX = vSheet.x * span, sheetV = vSheet.y;
float sheetDown = sqrt(max(sheetV, 0.)) * fall;
float sheetFine = sheetNoise(vec2(sheetX * 23., sheetV * 7. - time * 3.4));
float sheetAir = smoothstep(.22, 1., sheetV);
// No painted streaks and little white (user, 2026-11-17): the sheet stays clear
// water and its ripples catch the light; it churns white only in a thin band
// where it meets the water.
float sheetLanding = smoothstep(.93, 1., sheetV) * (.5 + .5 * sheetFine);
float sheetWhite = clamp(sheetLanding * .7, 0., 1.);
// A weak flow thins and opens in wide gaps; the edges pull in and fray as it falls.
float sheetGaps = smoothstep(.2, .42, sheetNoise(vec2(sheetX * 2.5, sheetV * 1.2 - time * 1.1)) + .1 - .12 * sheetV);
float sheetFray = .05 + .22 * sheetAir * sheetNoise(vec2(sheetX * 3., sheetV * 6. - time * 2.));
float sheetMask = mix(sheetGaps, 1., smoothstep(.1, .6, strength)) * smoothstep(0., sheetFray + .03, min(sheetX, span - sheetX)) * sheetFade;
// Metres of ripple, all travelling down: long ridges with the flow (narrow
// across, long along it), finer chop over them, and broad disturbances that
// roll down the face. The lighting turns the ridges into the streaks.
float sheetHeight = (sheetNoise(vec2(sheetX * 9., sheetDown * .9 - time * 2.6)) * .55
  + sheetNoise(vec2(sheetX * 22., sheetDown * 3. - time * 4.2)) * .25
  + sheetNoise(vec2(sheetX * 2.6, sheetDown * 1.8 - time * 3.)) * .2) * .02 * (1. - .6 * sheetLanding);
`;

export function sheetMaterial(span = 1, fall = 1) {
  const uniforms = {time: {value: 0}, strength: {value: 1}, opacity: {value: 1}, kind: {value: 2}, flow: {value: 1},
    span: {value: span}, fall: {value: fall}, light: {value: 1}, glow: {value: new THREE.Color(0, 0, 0)}};
  const material = new THREE.MeshStandardMaterial({name: 'falling water', color: 0xd4eef4, roughness: .06, metalness: 0,
    side: THREE.DoubleSide, transparent: true, depthWrite: false, premultipliedAlpha: true});
  // The effect driver writes time, strength, opacity and flow here, as for the unlit effects.
  material.uniforms = uniforms;
  material.userData.fallingWater = true;
  const compile = (shader, unlit = false) => {
    // Not opacity: three refreshes the material's own every frame.
    const {time, strength, flow, span, fall, opacity, glow} = uniforms;
    Object.assign(shader.uniforms, {time, strength, flow, span, fall, glow, sheetFade: opacity});
    shader.vertexShader = 'attribute vec3 outward; uniform float flow; varying vec2 vSheet;\n' + shader.vertexShader;
    waterReplace(shader, 'vertexShader', '#include <begin_vertex>', `#include <begin_vertex>
vSheet = uv;
transformed += outward * flow * (1. - exp(-uv.y * 6.));`);
    shader.fragmentShader = HEAD + shader.fragmentShader;
    waterReplace(shader, 'fragmentShader', '#include <color_fragment>', `#include <color_fragment>
${SHEET}
diffuseColor.rgb = mix(diffuseColor.rgb, vec3(.95, .98, 1.), sheetWhite);
${unlit ? 'diffuseColor.a *= max(.3, sheetWhite) * sheetMask;' : ''}`);
    if (unlit) return;
    // Bump from the ripple height by screen derivatives, as three's bump map does.
    waterReplace(shader, 'fragmentShader', '#include <normal_fragment_maps>', `#include <normal_fragment_maps>
{
  vec3 sheetDx = dFdx(-vViewPosition), sheetDy = dFdy(-vViewPosition);
  float sheetHx = dFdx(sheetHeight), sheetHy = dFdy(sheetHeight);
  vec3 sheetR1 = cross(sheetDy, normal), sheetR2 = cross(normal, sheetDx);
  float sheetDet = dot(sheetDx, sheetR1);
  normal = normalize(abs(sheetDet) * normal - sign(sheetDet) * (sheetHx * sheetR1 + sheetHy * sheetR2));
}`);
    waterReplace(shader, 'fragmentShader', '#include <roughnessmap_fragment>',
      '#include <roughnessmap_fragment>\nroughnessFactor = mix(.03, .6, sheetWhite);');
    // Mirrored and direct highlights arrive whole; the body covers what lies
    // behind only where the water is white with air, plus a thin film. A baked
    // lamp leaves the real-time lights, so the lamps in the water it falls into
    // light it as they light its foam, most where it meets that water.
    waterReplace(shader, 'fragmentShader', '#include <opaque_fragment>', `
float sheetBody = max(.22, sheetWhite);
float sheetCover = clamp(sheetBody * sheetMask, .0001, 1.);
vec3 sheetLamp = glow * diffuseColor.rgb * (.2 + .8 * sheetV);
// Clear water scatters little of its own: the thin film tints and dims what
// shows through it, and only aerated water is lit like a white surface.
vec3 sheetLight = (reflectedLight.indirectSpecular + reflectedLight.directSpecular
  + (totalDiffuse + sheetLamp) * sheetBody * mix(vec3(.3, .45, .5), vec3(1.), sheetWhite)) * sheetMask;
gl_FragColor = vec4(sheetLight / sheetCover, sheetCover);`);
  };
  material.onBeforeCompile = shader => compile(shader);
  material.customProgramCacheKey = () => 'falling-water-1';
  // The studio view keeps the arc and the cover on its matcap.
  Object.defineProperty(material.userData, 'unlitHook', {value: {hook: shader => compile(shader, true), key: () => 'falling-water-1|matcap'}});
  return material;
}
