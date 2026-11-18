import * as THREE from 'three';
import { waterReplace } from './water_surface.js';

// Moving water on the pool water's own footing: a lit standard surface that
// mirrors the sky and catches the sun and the lamps, laid over what stands
// behind it like the pool's surface over its body. Ripples travel with the
// water and the lighting draws the streaks; white only where it churns.
// Uniform names match the unlit effect water, which the effect driver updates.
// The standard material declares its own opacity, so the driver's fade goes by sheetFade.
const HEAD = `uniform float time; uniform float strength; uniform float sheetFade; uniform float span; uniform float fall; uniform vec3 glow;
varying vec2 vSheet;
float sheetHash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float sheetNoise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
  return mix(mix(sheetHash(i),sheetHash(i+vec2(1.,0.)),f.x),mix(sheetHash(i+vec2(0.,1.)),sheetHash(i+1.),f.x),f.y);}
// Repeats every period cells across, so a column's ripples close without a seam.
float sheetNoiseP(vec2 p,float period){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
  float a=mod(i.x,period),b=mod(i.x+1.,period);
  return mix(mix(sheetHash(vec2(a,i.y)),sheetHash(vec2(b,i.y)),f.x),mix(sheetHash(vec2(a,i.y+1.)),sheetHash(vec2(b,i.y+1.)),f.x),f.y);}
`;
// A falling sheet, in feet along the lip and down the fall. Falling from rest,
// water covers distance as the square of time, so the pattern scrolls in the
// root of the fall and stretches as it goes down.
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
// One continuous sheet, however weak the flow: gaps showed a dark wall behind
// as black splotches (user, 2026-11-17). The edges pull in and fray as it falls.
float sheetFray = .05 + .22 * sheetAir * sheetNoise(vec2(sheetX * 3., sheetV * 6. - time * 2.));
float sheetMask = smoothstep(0., sheetFray + .03, min(sheetX, span - sheetX)) * sheetFade;
// Metres of ripple, all travelling down: long ridges with the flow (narrow
// across, long along it), finer chop over them, and broad disturbances that
// roll down the face. The lighting turns the ridges into the streaks.
float sheetHeight = (sheetNoise(vec2(sheetX * 9., sheetDown * .9 - time * 2.6)) * .55
  + sheetNoise(vec2(sheetX * 22., sheetDown * 3. - time * 4.2)) * .25
  + sheetNoise(vec2(sheetX * 2.6, sheetDown * 1.8 - time * 3.)) * .2) * .02 * (1. - .6 * sheetLanding);
float sheetFilm = .22, sheetLampShare = .2 + .8 * sheetV;
`;
// A bubbler's column, a lathe with uv.x around it and uv.y from the tip (0) to
// the foot (1); fall is its height in feet. Turbulence climbs it; it breaks
// white only in a small crown where the water stalls and falls back, and
// boils a little where it leaves the water.
const COLUMN = `
float sheetU = vSheet.x, sheetV = vSheet.y, sheetUp = (1. - sheetV) * fall;
float sheetFine = sheetNoiseP(vec2(sheetU * 24., sheetUp * 9. - time * 5.), 24.);
float sheetCrown = (1. - smoothstep(0., .2, sheetV)) * smoothstep(.4, .8, sheetFine);
float sheetFoot = smoothstep(.9, 1., sheetV) * (.4 + .6 * sheetFine);
float sheetWhite = clamp(sheetCrown * .75 + sheetFoot * .45, 0., 1.);
// The tip is ragged where the column breaks up.
float sheetMask = sheetFade * (.8 + .2 * strength) * mix(1., smoothstep(.25, .6, sheetFine), 1. - smoothstep(0., .1, sheetV));
float sheetHeight = (sheetNoiseP(vec2(sheetU * 10., sheetUp * 1.4 - time * 3.2), 10.) * .6
  + sheetNoiseP(vec2(sheetU * 24., sheetUp * 4. - time * 5.), 24.) * .4) * .012;
float sheetFilm = .32, sheetLampShare = .3 + .7 * sheetV;
`;
// Lumps of water climb the column; the tip sways and pulses. Whole turns of uv.x keep the seam closed.
const COLUMN_VERTEX = `
float columnH = 1. - uv.y, columnA = uv.x * 6.28318;
float columnLump = .5*sin(columnA*3.+columnH*11.-time*6.)+.3*sin(columnA*5.-columnH*19.+time*8.3)+.2*sin(columnA*2.+columnH*29.-time*11.);
transformed.xz *= 1. + columnLump * (.05 + .1 * columnH);
transformed.xz += vec2(sin(time*2.3+columnH*3.), cos(time*1.7+columnH*2.)) * .12 * columnH * columnH;
transformed.y *= 1. - .05 * columnH * columnH * (.5 + .5 * sin(time * 9.));`;

function litWater({name, key, vertex, shape, span, fall, flag}) {
  const uniforms = {time: {value: 0}, strength: {value: 1}, opacity: {value: 1}, kind: {value: 2}, flow: {value: 1},
    span: {value: span}, fall: {value: fall}, light: {value: 1}, glow: {value: new THREE.Color(0, 0, 0)}};
  const material = new THREE.MeshStandardMaterial({name, color: 0xd4eef4, roughness: .06, metalness: 0,
    side: THREE.DoubleSide, transparent: true, depthWrite: false, premultipliedAlpha: true});
  // The effect driver writes time, strength, opacity and flow here, as for the unlit effects.
  material.uniforms = uniforms;
  material.userData.litWater = true;
  if (flag) material.userData[flag] = true;
  const compile = (shader, unlit = false) => {
    // Not opacity: three refreshes the material's own every frame.
    const {time, strength, flow, span, fall, opacity, glow} = uniforms;
    Object.assign(shader.uniforms, {time, strength, flow, span, fall, glow, sheetFade: opacity});
    shader.vertexShader = 'attribute vec3 outward; uniform float flow; uniform float time; varying vec2 vSheet;\n' + shader.vertexShader;
    waterReplace(shader, 'vertexShader', '#include <begin_vertex>', `#include <begin_vertex>
vSheet = uv;${vertex}`);
    shader.fragmentShader = HEAD + shader.fragmentShader;
    waterReplace(shader, 'fragmentShader', '#include <color_fragment>', `#include <color_fragment>
${shape}
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
float sheetBody = max(sheetFilm, sheetWhite);
float sheetCover = clamp(sheetBody * sheetMask, .0001, 1.);
vec3 sheetLamp = glow * diffuseColor.rgb * sheetLampShare;
// Clear water scatters little of its own: the thin film tints and dims what
// shows through it, and only aerated water is lit like a white surface.
vec3 sheetLight = (reflectedLight.indirectSpecular + reflectedLight.directSpecular
  + (totalDiffuse + sheetLamp) * sheetBody * mix(vec3(.3, .45, .5), vec3(1.), sheetWhite)) * sheetMask;
gl_FragColor = vec4(sheetLight / sheetCover, sheetCover);`);
  };
  material.onBeforeCompile = shader => compile(shader);
  material.customProgramCacheKey = () => key;
  // The studio view keeps the motion and the cover on its matcap.
  Object.defineProperty(material.userData, 'unlitHook', {value: {hook: shader => compile(shader, true), key: () => key + '|matcap'}});
  return material;
}

export function sheetMaterial(span = 1, fall = 1) {
  return litWater({name: 'falling water', key: 'falling-water-1', span, fall, flag: 'fallingWater', shape: SHEET,
    vertex: '\ntransformed += outward * flow * (1. - exp(-uv.y * 6.));'});
}

// fall is the column's height in feet, set as the flow changes.
export function columnMaterial(fall = 1) {
  return litWater({name: 'rising water', key: 'rising-water-1', span: 1, fall, flag: 'risingWater', shape: COLUMN, vertex: COLUMN_VERTEX});
}
