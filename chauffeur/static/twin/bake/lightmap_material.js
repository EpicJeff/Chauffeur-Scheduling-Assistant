import * as THREE from '../../vendor/three-r187/three.module.js';
import { atlasJob, buffers, applyAtlas, encodeAtlas, decodeAtlas } from './atlas_transport.js';
import { base } from '../twin_library.js';
import { CANDELA, FT } from '../twin_light_math.js';
import { fixturePoint } from '../live/fixture_geometry.js';
import { rectPieces } from './fixture_terms.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';
import { materialParts } from './bindings.js';

const floatTexture = (width, height) => {
  const t = new THREE.DataTexture(new Float32Array(Math.max(1, width) * Math.max(1, height) * 4),
    Math.max(1, width), Math.max(1, height), THREE.RGBAFormat, THREE.FloatType);
  t.needsUpdate = true; return t;
};
// The baked pages are a shadowmask: per light, how much of its emitter a texel sees. The
// material lights each pixel as the live PointLight does (three's RE_Direct: falloff, N.L
// with the shading normal, diffuse and specular by the material's own metalness), times the
// visibility from the page, coloured by the tint. Two data textures carry everything, so the
// lightmap holds three samplers regardless of bank count (lmTints, lmRegions, lmBanks).
// Fixture materials reuse the live pool's two LTC samplers.
//   lmTints   rows [0, R)    live colour x brightness by (slot, row): the switch, never a rebake
//             rows [R, 2R)   the light's world position (m) and reach (m)
//             rows [2R, 3R)  kind (0 point, 1 spot, 2 rect, 3 sum), pieces, sum scale, exact rect
// Fixture variant only (17R rows; legacy-only keeps its original 3R texture and shader):
//             rows [3R, 4R)  spot axis (world), outer cone cosine
//             rows [4R, 5R)  inner cone cosine, full-output candela, unused, unused
//             blocks 5..16   four rect pieces, three rows each: centre.xyz/luminance,
//                            half-width.xyz/reach, half-height.xyz/unused
// Sum channels store sqrt(irradiance/scale); point/spot/rect channels store visibility.
//   lmRegions rows [0, Q)    a chart's (or room's) region per bank: offset, layer, owners
//             rows [Q, 2Q)   the same address: the room fill of channel a (r) and b (g)
// Chart mode: R = 1 and a slot per light index; Q rows of 1024 chart x bank addresses. Room
// mode: R = a row per room, a slot per bank channel; Q = a row per room, a column per bank.
// Every lookup is by data, never by a uniform array index, so merged batches need nothing more.
const rowsOf = t => Math.max(1, Math.floor(t.image.height / (t.userData.fixtureRows ? 17 : 3)));
export const needsFixtureShader = lights => lights.some(l => l.kind > 0 || l.emitters?.some(e => !e.fire_pit));
export function lightmapUniforms(roomCount, slotCount, {fixtures = false} = {}) {
  const t = floatTexture(slotCount, (fixtures ? 17 : 3) * Math.max(1, roomCount));t.userData.fixtureRows = fixtures;
  if (fixtures && !THREE.UniformsLib.LTC_FLOAT_1) RectAreaLightUniformsLib.init();
  return {lmTints: {value: t}};
}
export function setLightSource(uniforms, room, slot, position, reach, kind = 0, light = null, exact = false) {
  const t = uniforms.lmTints.value, rows = rowsOf(t);
  if (room < 0 || room >= rows || slot < 0 || slot >= t.image.width) return;
  const put = (block, values) => t.image.data.set(values, ((block * rows + room) * t.image.width + slot) * 4);
  put(1, [position.x, position.y, position.z, reach]);
  put(2, [kind, 0, t.userData.fixtureRows ? light?.scale || 1 : 0, +exact]);
  if (t.userData.fixtureRows) put(4, [-1, CANDELA, 0, 0]);
  if (t.userData.fixtureRows && light?.emitters) {
    const e = light.emitters[0];
    if (kind < 2) {
      const cd = e.output_lm * e.output_fraction / (kind === 1 ? 2 * Math.PI * (1 - Math.cos(e.cone_deg * Math.PI / 360)) : 4 * Math.PI);
      put(4, [kind === 1 ? Math.cos(e.cone_deg * Math.PI / 360 * (1 - e.softness)) : -1, cd, 0, 0]);
      if (kind === 1) {
        const axis = fixturePoint(e.aim).sub(new THREE.Vector3(...e.position)).normalize();
        put(3, [...axis.toArray(), Math.cos(e.cone_deg * Math.PI / 360)]);
      }
    } else if (kind === 2) {
      const pieces = rectPieces(e);put(2, [kind, pieces.length, light.scale || 1, +exact]);
      pieces.forEach((p, i) => {
        put(5 + 3 * i, [...p.position.toArray(), p.luminance]);
        put(6 + 3 * i, [...p.u.toArray(), e.range * FT]);put(7 + 3 * i, [...p.v.toArray(), 0]);
      });
    }
  }
  t.needsUpdate = true;
}
const fillAt = (t, x, y, channel, value) => {
  const rows = Math.floor(t.image.height / 2);
  if (y < 0 || y >= rows || x < 0 || x >= t.image.width) return;
  t.image.data[((rows + y) * t.image.width + x) * 4 + channel] = value; t.needsUpdate = true;
};
// Room mode: a slot's fill in irradiance units (bank = slot / 2, channel = slot % 2).
export function setRoomFill(uniforms, room, slot, value) {
  if (uniforms.lmRegions) fillAt(uniforms.lmRegions.value, slot >> 1, room, slot & 1, value);
}
// Chart mode: the fill one channel of a chart's bank carries.
export function setChartFill(uniforms, chart, bank, banks, channel, value) {
  const [x, y] = chartAddress(chart, bank, banks);
  fillAt(uniforms.lmRegions.value, x, y, channel, value);
}
export function clearFills(uniforms) {
  const t = uniforms.lmRegions?.value; if (!t) return;
  const rows = Math.floor(t.image.height / 2);
  t.image.data.fill(0, rows * t.image.width * 4); t.needsUpdate = true;
}
export function setLightTint(uniforms, room, slot, rgb, intensity) {
  const t = uniforms.lmTints.value;
  if (room < 0 || room >= rowsOf(t) || slot < 0 || slot >= t.image.width) return;
  const c = new THREE.Color().setRGB(...rgb.map(x => x / 255), THREE.SRGBColorSpace).multiplyScalar(intensity);
  const i = (room * t.image.width + slot) * 4;
  t.image.data.set([c.r, c.g, c.b, 0], i); t.needsUpdate = true;
}
// A room-mode region texture: a column per bank, a row per room, then the fills.
export const roomRegions = (banks, rooms) => floatTexture(Math.max(1, banks), 2 * Math.max(1, rooms));
// Flat chart addressing stays below WebGL2's minimum texture-size limit even
// when a detailed house has more charts than texture rows.
export const chartAddress = (chart, bank, banks) => [((chart * banks + bank) % 1024), Math.floor((chart * banks + bank) / 1024)];
export function bankLayerBases(layers) {
  let next = 0;
  return layers.map(list => { const base = next; next += list.length; return base; });
}
export function applyChartIndices(atlas) {
  const arrays = new Map(), ArrayType = atlas.room.charts.length < 32768 ? Int16Array : Float32Array;
  for (const c of atlas.room.charts) {
    // A proxy (a batten face, a trim edge) reads its host chart's texels and lights.
    for (const part of materialParts(c)) {
      const g=part.mesh.geometry;
      if (!arrays.has(g)) arrays.set(g,new ArrayType(g.attributes.position.count).fill(-1));
      for (const f of part.faces) arrays.get(g).fill(c.id,f*3,f*3+3);
    }
  }
  for (const [g,data] of arrays) {
    g.setAttribute('lmRoom',new THREE.BufferAttribute(data,1));
    g.deleteAttribute('lmLightPage'); // Bank pages now come from chart metadata.
  }
}
export function chartLightmapUniforms(chartCount, packed, lights, pageSize, layers) {
  if (lights.length > 4095) throw new Error('Too many light indices for a chart owner texture.');
  const uniforms = lightmapUniforms(1, Math.max(1, lights.length), {fixtures: needsFixtureShader(lights)}), banks = Math.max(1, packed.banks.length);
  // Regions in the first half of the rows, each address's fills in the second (lmFillsAt).
  const texture = floatTexture(1024, 2 * Math.max(1, Math.ceil(chartCount*banks/1024)));
  const owners = new Map(), bankBase = bankLayerBases(layers);
  lights.forEach((l,index) => {
    const slot = packed.slots[l.device]; if (!slot) return;
    for (const a of slot.assignments || (slot.receivingCharts || []).map(chart=>({chart,bank:slot.bank,channel:slot.channel}))) {
      const key = a.chart*banks+a.bank;
      if (!owners.has(key)) owners.set(key,[0,0]);
      owners.get(key)[a.channel] = index+1;
    }
  });
  packed.banks.forEach((bank,b) => bank.charts.forEach(c => {
    const [x,y] = chartAddress(c.id,b,banks), owner = owners.get(c.id*banks+b) || [0,0];
    texture.image.data.set([(c.rect.x-c.sourceRegion.x)/pageSize, (c.rect.y-c.sourceRegion.y)/pageSize,
      bankBase[b] + Math.max(0,layers[b].indexOf(c.page)), owner[0]+owner[1]*4096], (y*1024+x)*4);
  }));
  texture.needsUpdate=true; uniforms.lmRegions={value:texture}; uniforms.lmChartMode={value:1};
  return uniforms;
}
export function chartLookupGLSL(banks) {
  return `ivec2 lmAddress(int bank, int chart) { int id = chart * ${Math.max(1,banks)} + bank; return ivec2(id % 1024, id / 1024); }
vec3 lmOwnerTint(float owner) { return owner < 0.5 ? vec3(0.0) : texelFetch(lmTints, ivec2(int(owner)-1, 0), 0).rgb; }`;
}
// The live PointLight at a view-space point: three's decay-2 falloff with its distance cutoff
// (real_lights.js). lmPoint answers the falloff (1/d^2 x cutoff), the unit direction and the
// cutoff alone (the room fill fades with it, so nothing glows past a light's reach). Kind 0
// is a point; other kinds (Slice C) answer 0 until built.
export const SHADE_GLSL = `int lmRows() { return max(1, textureSize(lmTints, 0).y / 3); }
vec3 lmTintAt(int slot, int row) { return texelFetch(lmTints, ivec2(slot, row), 0).rgb; }
vec4 lmFillsAt(ivec2 address) { return texelFetch(lmRegions, address + ivec2(0, textureSize(lmRegions, 0).y / 2), 0); }
float lmPoint(int slot, int row, vec3 posV, out vec3 direction, out float cutoff) {
  vec4 src = texelFetch(lmTints, ivec2(slot, lmRows() + row), 0), kind = texelFetch(lmTints, ivec2(slot, 2 * lmRows() + row), 0);
  direction = vec3(0.0, 0.0, 1.0); cutoff = 0.0;
  if (kind.x > 0.5 || src.w <= 0.0) return 0.0;
  vec3 toward = (viewMatrix * vec4(src.xyz, 1.0)).xyz - posV; float d = length(toward);
  direction = toward / max(d, 1e-4);
  cutoff = pow(clamp(1.0 - pow(d / src.w, 4.0), 0.0, 1.0), 2.0);
  return cutoff / max(d * d, 0.01);
}
int lmOwnerSlot(float owner) { return max(0, int(owner) - 1); }`;
const RECT_GLSL = `
vec4 lmData(int slot, int row, int block) { return texelFetch(lmTints, ivec2(slot, block * lmRows() + row), 0); }
float lmWindow(float d, float reach) { return reach > 0.0 ? pow(clamp(1.0-pow(d/reach,4.0),0.0,1.0),2.0) : 0.0; }
vec3 lmEdge(vec3 a, vec3 b) {
  float x=dot(a,b),y=abs(x),v=(0.8543985+(0.4965155+0.0145206*y)*y)/(3.4175940+(4.1616724+y)*y);
  return cross(a,b)*(x>0.0?v:0.5*inversesqrt(max(1.0-x*x,1e-7))-v);
}
float lmPolygon(vec3 n, vec3 delta, vec3 u, vec3 v) {
  vec3 a=normalize(delta+u-v),b=normalize(delta-u-v),c=normalize(delta-u+v),d=normalize(delta+u+v);
  vec3 f=lmEdge(a,b)+lmEdge(b,c)+lmEdge(c,d)+lmEdge(d,a);float l=length(f);
  return max(0.0,(l*l-dot(f,n))/(l+1.0));
}
float lmRect(int slot, int row, vec3 pos, vec3 n, out float cutoff) {
  vec4 kind=lmData(slot,row,2);float energy=0.0;cutoff=0.0;
  for (int i=0;i<4;i++) {
    if (float(i)>=kind.y) break;
    vec4 p=lmData(slot,row,5+i*3),w=lmData(slot,row,6+i*3),h=lmData(slot,row,7+i*3);
    vec3 delta=(viewMatrix*vec4(p.xyz,1.0)).xyz-pos,u=mat3(viewMatrix)*w.xyz,v=mat3(viewMatrix)*h.xyz;
    vec3 facing=-normalize(cross(u,v));
    vec3 nearest=delta-u*clamp(dot(delta,u)/dot(u,u),-1.0,1.0)-v*clamp(dot(delta,v)/dot(v,v),-1.0,1.0);
    float cut=lmWindow(length(nearest),w.w);cutoff=max(cutoff,cut);
    if (dot(facing,delta)>=0.0) continue;
    if (kind.w>0.5) energy+=p.w*3.141592653589793*lmPolygon(n,delta,u,v)*cut;
    else {
      float d=length(delta);vec3 dir=delta/max(d,1e-4);
      energy+=p.w*4.0*length(u)*length(v)*max(0.0,dot(n,dir))*max(0.0,-dot(facing,dir))*cut/max(d*d,0.01);
    }
  }
  return energy;
}`;
function shadeGLSL(fixtures) {
  if (!fixtures) return SHADE_GLSL;
  return SHADE_GLSL.replace(' / 3)', ' / 17)').replace('kind.x > 0.5 || ', '')
    .replace('return cutoff / max(d * d, 0.01);', `float factor = 1.0;
  if (kind.x < 1.5) {
    vec4 photometry=texelFetch(lmTints,ivec2(slot,4*lmRows()+row),0);factor=photometry.y/${CANDELA.toFixed(1)};
    if (kind.x > 0.5) {
      vec4 cone=texelFetch(lmTints,ivec2(slot,3*lmRows()+row),0);
      float cosine=dot(mat3(viewMatrix)*cone.xyz,-direction);
      factor*=cone.w==photometry.x?step(cone.w,cosine):smoothstep(cone.w,photometry.x,cosine);
    }
  }
  return factor * cutoff / max(d * d, 0.01);`) + RECT_GLSL;
}
const rectSpecular = (slot, row, visibility) => `
for (int i=0;i<4;i++) {
  if (float(i)>=lmKind.y) break;
  vec4 p=lmData(${slot},${row},5+i*3),w=lmData(${slot},${row},6+i*3),h=lmData(${slot},${row},7+i*3);
  vec3 centre=(viewMatrix*vec4(p.xyz,1.0)).xyz,u=mat3(viewMatrix)*w.xyz,v=mat3(viewMatrix)*h.xyz;
  vec3 delta=centre-geometryPosition;
  vec3 nearest=delta-u*clamp(dot(delta,u)/dot(u,u),-1.0,1.0)-v*clamp(dot(delta,v)/dot(v,v),-1.0,1.0);
  float cut=lmWindow(length(nearest),w.w);
  vec3 coords[4];coords[0]=centre+u-v;coords[1]=centre-u-v;coords[2]=centre-u+v;coords[3]=centre+u+v;
  vec2 uv=LTC_Uv(geometryNormal,geometryViewDir,material.roughness);
  vec4 t1=texture2D(ltc_1,uv),t2=texture2D(ltc_2,uv);
  mat3 inv=mat3(vec3(t1.x,0.0,t1.y),vec3(0.0,1.0,0.0),vec3(t1.z,0.0,t1.w));
  vec3 fresnel=material.specularColorBlended*t2.x+(material.specularF90-material.specularColorBlended)*t2.y;
  reflectedLight.directSpecular+=lmTint*p.w*fresnel*LTC_Evaluate(geometryNormal,geometryViewDir,geometryPosition,inv,coords)*cut*${visibility};
  #ifdef USE_CLEARCOAT
    vec2 coatUv=LTC_Uv(geometryClearcoatNormal,geometryViewDir,material.clearcoatRoughness);
    vec4 coat1=texture2D(ltc_1,coatUv),coat2=texture2D(ltc_2,coatUv);
    mat3 coatInv=mat3(vec3(coat1.x,0.0,coat1.y),vec3(0.0,1.0,0.0),vec3(coat1.z,0.0,coat1.w));
    vec3 coatFresnel=material.clearcoatF0*coat2.x+(material.clearcoatF90-material.clearcoatF0)*coat2.y;
    clearcoatSpecularDirect+=lmTint*p.w*coatFresnel*LTC_Evaluate(geometryClearcoatNormal,geometryViewDir,geometryPosition,coatInv,coords)*cut*${visibility};
  #endif
}`;
export const lightSwizzle = format => format === THREE.RGBAFormat ? 'ra' : 'rg';
export function pickTranscode(extensions, channels) {
  if (extensions.has('EXT_texture_compression_rgtc')) return channels === 1 ? THREE.RED_RGTC1_Format : THREE.RED_GREEN_RGTC2_Format;
  if (extensions.has('WEBGL_compressed_texture_etc')) return channels === 1 ? THREE.R11_EAC_Format : THREE.RG11_EAC_Format;
  return THREE.RGBAFormat;
}
export { transcodePage } from './transcode.js';

// One baked light's term in a lit material's main(), after lights_fragment_end: three's own
// RE_Direct with an IncidentLight of the live light's colour, so diffuse (by metalness),
// specular and the material's normal match the live PointLight and nothing pops when a light
// goes fresh. The fill is indirect, faded by the light's reach cutoff at the pixel.
const directTerm = (tint, slot, row, visibility, fill, fixtures = false) => `{ vec3 lmTint = ${tint};
  if (lmTint.r + lmTint.g + lmTint.b > 0.0) {
    ${fixtures ? `vec4 lmKind = lmData(${slot}, ${row}, 2);
    if (lmKind.x > 1.5) {
      float lmCut = 0.0;float lmEnergy = lmKind.x > 2.5 ? ${visibility} * ${visibility} * lmKind.z
        : lmRect(${slot}, ${row}, geometryPosition, geometryNormal, lmCut) * ${visibility};
      if (lmKind.x > 2.5) {vec3 unused;lmPoint(${slot}, ${row}, geometryPosition, unused, lmCut);}
      reflectedLight.directDiffuse += lmTint * lmEnergy * BRDF_Lambert(material.diffuseContribution);
      lmFill += lmTint * (${fill}) * lmCut;
      if (lmKind.x < 2.5 && lmKind.w > 0.5) {
        ${rectSpecular(slot, row, visibility)}
      }
    } else {` : ''}
    vec3 lmDir; float lmCut, lmFall = lmPoint(${slot}, ${row}, geometryPosition, lmDir, lmCut);
    IncidentLight lmIncident; lmIncident.color = lmTint * (${CANDELA.toFixed(1)} * lmFall * ${visibility});
    lmIncident.direction = lmDir; lmIncident.visible = true;
    RE_Direct(lmIncident, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight);
    lmFill += lmTint * (${fill}) * lmCut;
    ${fixtures ? '}' : ''}
  } }`;
export function patchLightmaps(materials, pages, uniforms) {
  const chartMode = !!uniforms.lmChartMode, fixtures = !!uniforms.lmTints.value.userData.fixtureRows;
  // M8: a room's region sits two texels from its neighbours on a shared page. Sample no
  // coarser than mip 1 (gradients clamped to two texels a pixel), so a far-off room never
  // blends a neighbour's light into its border under its own tint. The gradients are
  // taken outside the room branch, where derivatives are defined. A bank no light owns here
  // skips its page fetch and its lights (the per-bank early-out).
  // The texture list holds one physical array; metadata counts the logical banks.
  const banks = pages.bankBase || pages.banks;
  const bankCode = banks.map((_, b) => {
    if (pages.bankLayers?.[b] === 0) return '';
    const s = lightSwizzle(pages.banks[0].format);
    const address = chartMode ? `lmAddress(${b}, int(vLmRoom + 0.5))` : `ivec2(${b}, lmRow)`;
    const owner = k => chartMode ? [`mod(region${b}.w, 4096.0)`, `floor(region${b}.w / 4096.0)`][k] : null;
    const term = k => chartMode
      ? directTerm(`lmOwnerTint(${owner(k)})`, `lmOwnerSlot(${owner(k)})`, '0', `bank${b}.${s[k]}`, `fill${b}.${'rg'[k]}`, fixtures)
      : directTerm(`lmTintAt(${2 * b + k}, lmRow)`, `${2 * b + k}`, 'lmRow', `bank${b}.${s[k]}`, `fill${b}.${'rg'[k]}`, fixtures);
    const live = chartMode ? `region${b}.w > 0.5`
      : `dot(lmTintAt(${2 * b}, lmRow) + lmTintAt(${2 * b + 1}, lmRow), vec3(1.0)) > 0.0`;
    return `vec4 region${b} = texelFetch(lmRegions, ${address}, 0);
if (${live}) {
  vec4 fill${b} = lmFillsAt(${address});
  float lmSpan${b} = max(length(lmDx), length(lmDy)) * float(textureSize(lmBanks, 0).x);
  float lmClamp${b} = lmSpan${b} > 2.0 ? 2.0 / lmSpan${b} : 1.0;
  vec4 bank${b} = textureGrad(lmBanks, vec3(vLmUV + region${b}.xy, region${b}.z), lmDx * lmClamp${b}, lmDy * lmClamp${b});
  ${term(0)}
  ${term(1)}
}`;
  }).join('\n');
  const declarations = `uniform sampler2D lmTints;
uniform sampler2D lmRegions;
varying vec2 vLmUV; varying float vLmRoom;
uniform highp sampler2DArray lmBanks;
${fixtures ? `#if NUM_RECT_AREA_LIGHTS == 0
uniform sampler2D lmLtc1; uniform sampler2D lmLtc2;
#define ltc_1 lmLtc1
#define ltc_2 lmLtc2
#endif` : ''}
${shadeGLSL(fixtures)}
${chartMode ? chartLookupGLSL(banks.length) : ''}`;
  const slots = uniforms.lmTints.value.image.width, rooms = rowsOf(uniforms.lmTints.value);
  if (!uniforms.lmRegions) uniforms.lmRegions = { value: roomRegions(banks.length, rooms) };
  for (const material of new Set(materials)) {
    const before = material.userData.lmBefore || material.onBeforeCompile;
    const originalKey = material.userData.lmKey || material.customProgramCacheKey.bind(material);
    // Save the pre-patch key now; three's default key stringifies onBeforeCompile.
    const key = material.userData.lmOriginalKey ?? originalKey();
    material.userData.lmBefore = before; material.userData.lmOriginalKey = key;
    material.onBeforeCompile = (shader, renderer) => {
      before.call(material, shader, renderer);
      Object.assign(shader.uniforms, uniforms);
      if (fixtures) {
        const type = renderer?.extensions?.has('OES_texture_float_linear') ? 'FLOAT' : 'HALF';
        shader.uniforms.lmLtc1 = {value: THREE.UniformsLib['LTC_' + type + '_1']};
        shader.uniforms.lmLtc2 = {value: THREE.UniformsLib['LTC_' + type + '_2']};
      }
      shader.uniforms.lmBanks = { value: pages.banks[0] };
      shader.vertexShader = `#ifndef USE_UV3
attribute vec2 uv3;
#endif
attribute float lmRoom;
varying vec2 vLmUV; varying float vLmRoom;\n` + shader.vertexShader;
      shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>
vLmUV = uv3; vLmRoom = lmRoom;`);
      shader.fragmentShader = declarations + '\n' + shader.fragmentShader;
      // The baked lights shade with the fragment's own normal (normal maps, a batten's front
      // and sides) at its own position; the page says only how much of each light reaches it.
      shader.fragmentShader = shader.fragmentShader.replace('#include <lights_fragment_end>', `vec2 lmDx = dFdx(vLmUV), lmDy = dFdy(vLmUV);
#include <lights_fragment_end>
#if defined( STANDARD ) && !( NUM_SUN_LIGHTS > 0 || NUM_DIR_LIGHTS > 0 || NUM_POINT_LIGHTS > 0 || NUM_SPOT_LIGHTS > 0 )
  // three sets this only when a live punctual light exists; a baked light needs it too, or
  // its specular vanishes whenever the live pool is hidden.
  material.multiScatteringCompensation = 1.0 + material.specularColorBlended * ( 1.0 / ( material.dfg.x + material.dfg.y ) - 1.0 );
#endif
vec3 lmFill = vec3(0.0);
int lmRow = int(vLmRoom + 0.5);
if (vLmRoom > -0.5) {
${bankCode}
  RE_IndirectDiffuse(lmFill, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight);
}`);
    };
    material.customProgramCacheKey = () => `${key}|lm-9-merged-shadowmask-direct|${fixtures ? 'fixtures|' : ''}${chartMode ? 'charts-2|' : ''}${slots}|${banks.length}|${lightSwizzle(pages.banks[0]?.format)}|${pages.bankLayers?.map(n => +!!n).join('') || ''}`;
    material.needsUpdate = true;
  }
}

// A window pane glows with its room's baked light: the pane reads the shadowmask of the inside
// wall around it (glowRoom, glowUV) and lights it from its own point, with its normal on
// whichever side faces the lamp, standing in for that wall. Emissive, so no lighting chunks.
export function patchWindowGlow(material, pages, uniforms) {
  // Probed panes carry the slot's hooks as well as the reflection hook. Keep
  // the existing low-tier and interior-glass program completely unchanged.
  const before = material.userData.reflection ? material.onBeforeCompile : null;
  const key = before ? material.customProgramCacheKey() + '|' : '';
  const chartMode = !!uniforms.lmChartMode, banks = pages.bankBase || pages.banks, fixtures = !!uniforms.lmTints.value.userData.fixtureRows;
  const sum = banks.map((_, b) => {
    if (pages.bankLayers?.[b] === 0) return '';
    const s = lightSwizzle(pages.banks[0].format);
    const address = chartMode ? `lmAddress(${b}, int(vGlowRoom + 0.5))` : `ivec2(${b}, glowRow)`;
    const owner = k => [`mod(region${b}.w, 4096.0)`, `floor(region${b}.w / 4096.0)`][k];
    const term = k => {
      const tint = chartMode ? `lmOwnerTint(${owner(k)})` : `lmTintAt(${2 * b + k}, glowRow)`;
      const slot = chartMode ? `lmOwnerSlot(${owner(k)})` : `${2 * b + k}`, row = chartMode ? '0' : 'glowRow';
      return `{ vec3 lmTint = ${tint}; if (lmTint.r + lmTint.g + lmTint.b > 0.0) {
    vec3 lmDir; float lmCut, lmFall = lmPoint(${slot}, ${row}, glowPos, lmDir, lmCut);
    float energy = ${CANDELA.toFixed(1)} * lmFall * abs(dot(glowNormal, lmDir)) * value${b}.${s[k]};
    ${fixtures ? `vec4 kind = lmData(${slot}, ${row}, 2);
    if (kind.x > 2.5) energy = value${b}.${s[k]} * value${b}.${s[k]} * kind.z;
    else if (kind.x > 1.5) energy = lmRect(${slot}, ${row}, glowPos, faceforward(glowNormal, -lmDir, glowNormal), lmCut) * value${b}.${s[k]};` : ''}
    glow += lmTint * (energy + fill${b}.${'rg'[k]} * lmCut); } }`;
    };
    return `vec4 region${b} = texelFetch(lmRegions, ${address}, 0);
vec4 fill${b} = lmFillsAt(${address});
vec4 value${b} = textureLod(lmBanks, vec3(vGlowUV + region${b}.xy, region${b}.z), 0.0);
${term(0)}
${term(1)}`;
  }).join('\n');
  material.onBeforeCompile = (shader, renderer) => {
    before?.call(material, shader, renderer);
    Object.assign(shader.uniforms, uniforms);
    shader.uniforms.lmBanks = { value: pages.banks[0] };
    shader.vertexShader = 'attribute float glowRoom; attribute vec2 glowUV; varying float vGlowRoom; varying vec2 vGlowUV;\n' + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>
vGlowRoom = glowRoom; vGlowUV = glowUV;`);
    shader.fragmentShader = `uniform sampler2D lmTints; uniform sampler2D lmRegions;
varying float vGlowRoom; varying vec2 vGlowUV;
uniform highp sampler2DArray lmBanks;
${shadeGLSL(fixtures)}
${chartMode ? chartLookupGLSL(banks.length) : ''}
` + shader.fragmentShader;
    // Irradiance / 16 x 8, as the pane glowed when the page held irradiance / 16.
    shader.fragmentShader = shader.fragmentShader.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
if (vGlowRoom > -0.5) {
  vec3 glow = vec3(0.0), glowPos = -vViewPosition, glowNormal = normalize(normal);
  int glowRow = int(vGlowRoom + 0.5);
  ${sum}
  totalEmissiveRadiance += glow * 0.5;
}`);
  };
  material.customProgramCacheKey = () => `${key}twin-window-glow-8-merged-shadowmask-${fixtures ? 'fixtures-' : ''}${chartMode ? 'charts-' : ''}${banks.length}|${lightSwizzle(pages.banks[0]?.format)}|${pages.bankLayers?.map(n => +!!n).join('') || ''}`;
  material.needsUpdate = true;
}

async function openCache(indexedDB) {
  if (!indexedDB) return null;
  return new Promise(resolve => {
    const r = indexedDB.open('twin-lightmap-atlases', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('atlases');
    r.onsuccess = () => resolve(r.result); r.onerror = r.onblocked = () => resolve(null);
  });
}
async function cached(db, key, data) {
  if (!db) return null;
  return new Promise(resolve => {
    const tx = db.transaction('atlases', data ? 'readwrite' : 'readonly'), store = tx.objectStore('atlases');
    const r = data ? store.put(data, key) : store.get(key);
    r.onsuccess = () => { if (!data) resolve(r.result); };
    tx.oncomplete = () => resolve(data); tx.onerror = tx.onabort = () => resolve(null); r.onerror = () => resolve(null);
  });
}
// A browser keeps its two most recently used atlases (I3): each holds the clipped house,
// about 14 MB, under Home Assistant's own origin. 'recent' lists them newest first with
// the input fingerprints that point at them; every other entry is deleted.
export const KEEP_ATLASES = 2;
async function remember(db, key, input) {
  if (!db) return;
  await new Promise(resolve => {
    const tx = db.transaction('atlases', 'readwrite'), store = tx.objectStore('atlases');
    const r = store.get('recent');
    r.onsuccess = () => {
      const list = (Array.isArray(r.result) ? r.result : []).filter(row => row && row.key);
      const mine = list.find(row => row.key === key) || { key, inputs: [] };
      if (!mine.inputs.includes(input)) mine.inputs.push(input);
      const keep = [mine, ...list.filter(row => row.key !== key)].slice(0, KEEP_ATLASES);
      store.put(keep, 'recent');
      const live = new Set(['recent', ...keep.flatMap(row => [row.key, ...row.inputs.map(i => 'input:' + i)])]);
      if (store.getAllKeys) {
        const all = store.getAllKeys();
        all.onsuccess = () => { for (const k of all.result) if (!live.has(k)) store.delete(k); };
      }
    };
    tx.oncomplete = resolve; tx.onerror = tx.onabort = resolve;
  });
}
// A module's URL as this page's import map versions it (I9): a worker script is never
// served from last week's cache.
export function versioned(spec, from = import.meta.url) {
  const plain = new URL(spec, from).href;
  try { return import.meta.resolve ? import.meta.resolve(plain) : plain; } catch { return plain; }
}
// Large houses take more than 30 seconds on a desk, longer on a wall panel.
// Still bound a worker that never answers or errors, so the live-light fallback can retry.
export const ATLAS_TIMEOUT_MS = 10 * 60 * 1000;
let atlasServerWarning = false;
function reportAtlasServer(error, signal) {
  if (signal?.aborted || atlasServerWarning) return;
  atlasServerWarning = true; console.warn('Atlas server cache unavailable:', error);
}
function atlasWait(promise, signal) {
  if (!signal) return promise;
  return new Promise((resolve, reject) => {
    const abort = () => reject(new Error('Atlas cancelled.'));
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
    Promise.resolve(promise).then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}
// apply: false answers {key, apply()} and leaves the meshes alone until apply() (M1).
export async function loadAtlas(root, plan, layout, { Worker = globalThis.Worker, indexedDB = globalThis.indexedDB,
  fetch = globalThis.fetch, signal, apply = true } = {}) {
  const check = () => { if (signal?.aborted) throw new Error('Atlas cancelled.'); };
  check();
  const job = atlasJob(root, plan, layout);
  const opening = openCache(indexedDB).catch(() => null);
  opening.then(db => { if (signal?.aborted) db?.close(); });
  const db = await atlasWait(opening, signal);
  const wait = promise => atlasWait(promise, signal);
  const url = () => base() + 'api/house/atlases/' + job.cacheKey;
  // Publish local hits too: the baking desk may already have a pre-server-cache atlas.
  const publish = data => {
    (async () => {
      check();
      const body = await encodeAtlas(data, { signal }); check();
      const response = await fetch(url(), { method: 'PUT', body, signal, chfQuietAuth: true,
        headers: { 'Content-Type': 'application/octet-stream' } });
      if (!response.ok && response.status !== 403) throw new Error(`Atlas upload: HTTP ${response.status}`);
    })().catch(error => reportAtlasServer(error, signal));
  };
  const answer = data => { check(); return apply ? applyAtlas(data, root, layout) :
    { key: data.key, apply: () => { check(); return applyAtlas(data, root, layout); } }; };
  const save = async data => {
    check(); await wait(cached(db, data.key, data).catch(() => null));
    check(); await wait(cached(db, 'input:' + job.cacheKey, data.key).catch(() => null));
    check(); await wait(remember(db, data.key, job.cacheKey).catch(() => null));
  };
  try {
    const key = await wait(cached(db, 'input:' + job.cacheKey).catch(() => null));
    const stored = key && await wait(cached(db, key).catch(() => null));
    // One layout key can hold geometry from another base uv (random_offset on/off):
    // that copy is not this scene's, so lay out afresh and replace it.
    const hit = stored?.uvKey === job.uvKey ? stored : null;
    check();
    if (hit) { await wait(remember(db, hit.key, job.cacheKey).catch(() => null)); check(); publish(hit); return answer(hit); }
    try {
      const response = await wait(fetch(url(), { signal })); check();
      if (response.ok) {
        const data = await wait(decodeAtlas(await wait(response.arrayBuffer()), { signal })); check();
        if (data.uvKey === job.uvKey && data.geometries?.length === job.meshes.length && data.room && typeof data.key === 'string') {
          await save(data); return answer(data);
        }
      } else if (response.status !== 404 && response.status !== 403) throw new Error(`Atlas download: HTTP ${response.status}`);
    } catch (error) { check(); reportAtlasServer(error, signal); }
    check();
    const data = await new Promise((resolve, reject) => {
      const w = new Worker(versioned('./atlas_worker.js'), { type: 'module' });
      const cancel = () => { finish(); reject(new Error('Atlas cancelled.')); };
      const finish = () => { clearTimeout(timeout); w.terminate(); signal?.removeEventListener('abort', cancel); };
      // A worker which neither answers nor errors must not leave key:null forever.
      const timeout=setTimeout(() => { finish(); reject(new Error('Atlas worker timed out after 10 minutes.')); }, ATLAS_TIMEOUT_MS);
      w.onmessage = e => { finish(); e.data.error ? reject(new Error(e.data.error)) : resolve(e.data); };
      w.onerror = e => { finish(); reject(e.error || new Error(e.message || 'Atlas worker failed.')); };
      w.onmessageerror = () => { finish(); reject(new Error('Atlas worker returned an unreadable message.')); };
      signal?.addEventListener('abort', cancel, { once: true });
      if (signal?.aborted) { cancel(); return; }
      try { w.postMessage(job, buffers(job.meshes)); }
      catch (error) { finish(); reject(error); }
    });
    check();
    data.uvKey = job.uvKey;
    await save(data); check(); publish(data);
    return answer(data);
  } finally { db?.close(); }
}
