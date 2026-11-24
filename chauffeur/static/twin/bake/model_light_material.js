// Placed-model shader patch: reads per-copy visibility bricks (mvBricks, sampler3D)
// and emitter/brick metadata (mvLamps, sampler2D) using the shared MODEL_LIGHT_LAYOUT
// contract from model_bricks.js. Adds exactly two samplers on patched model materials
// and zero on non-model materials; one program regardless of emitter count (1..8).
import { MODEL_LIGHT_LAYOUT } from './model_bricks.js';

export const MODEL_LIGHT_CACHE_SUFFIX = '|mv-1';

const L = MODEL_LIGHT_LAYOUT;
const INV_PACK_STRIDE = (1 / L.EMITTER_PACK_STRIDE).toFixed(12); // exact power-of-two 2^-12
const INJECT_GUARD = 'uniform highp sampler3D mvBricks;';

const VERTEX_DECL = `attribute float mvBrick;
flat varying float vMvBrick;
varying vec3 vMvWorldPos;`;

const VERTEX_BODY = `#include <project_vertex>
vec4 mvWp = vec4( transformed, 1.0 );
#ifdef USE_BATCHING
  mvWp = batchingMatrix * mvWp;
#endif
#ifdef USE_INSTANCING
  mvWp = instanceMatrix * mvWp;
#endif
mvWp = modelMatrix * mvWp;
vMvWorldPos = mvWp.xyz;
vMvBrick = mvBrick;`;

const FRAGMENT_DECL = `${INJECT_GUARD}
uniform sampler2D mvLamps;
uniform vec4 mvSize;
flat varying float vMvBrick;
varying vec3 vMvWorldPos;
ivec2 mvEmitterCoord(int row, int offset, int w) {
  return ivec2(row % w, (row / w) * ${L.EMITTER_ROWS} + offset);
}
ivec2 mvBrickCoord(int brick, int offset, int w, int firstRow) {
  return ivec2(brick % w, firstRow + (brick / w) * ${L.BRICK_ROWS} + offset);
}`;

const FRAGMENT_BODY = `#include <lights_fragment_end>
if (vMvBrick > 0.5) {
#if defined( STANDARD ) && !( NUM_SUN_LIGHTS > 0 || NUM_DIR_LIGHTS > 0 || NUM_POINT_LIGHTS > 0 || NUM_SPOT_LIGHTS > 0 )
  material.multiScatteringCompensation = 1.0 + material.specularColorBlended * ( 1.0 / ( material.dfg.x + material.dfg.y ) - 1.0 );
#endif
  int mvIdx = int(vMvBrick + 0.5) - 1;
  int mvW = max(1, int(mvSize.z + 0.5));
  int mvFirst = int(mvSize.w + 0.5);
  vec4 mvMeta = texelFetch(mvLamps, mvBrickCoord(mvIdx, ${L.BRICK_ROW_META}, mvW, mvFirst), 0);
  int mvCount = int(mvMeta.x + 0.5);
#if defined( RE_Direct )
  if (mvCount > 0) {
    float mvZOff = mvMeta.y;
    vec4 mvBoxMin = texelFetch(mvLamps, mvBrickCoord(mvIdx, ${L.BRICK_ROW_BOX_MIN}, mvW, mvFirst), 0);
    vec4 mvBoxInv = texelFetch(mvLamps, mvBrickCoord(mvIdx, ${L.BRICK_ROW_BOX_INV}, mvW, mvFirst), 0);
    vec3 mvLocal = vec3(
      mvBoxInv.x > 0.0 ? clamp((vMvWorldPos.x - mvBoxMin.x) * mvBoxInv.x, 0.0, 1.0) : 0.5,
      mvBoxInv.y > 0.0 ? clamp((vMvWorldPos.y - mvBoxMin.y) * mvBoxInv.y, 0.0, 1.0) : 0.5,
      mvBoxInv.z > 0.0 ? clamp((vMvWorldPos.z - mvBoxMin.z) * mvBoxInv.z, 0.0, 1.0) : 0.5
    );
    float mvU0 = clamp(0.5 + mvLocal.x * 4.0, 0.5, 4.5) / ${L.BRICK_TEX_WIDTH}.0;
    float mvU1 = clamp(5.5 + mvLocal.x * 4.0, 5.5, 9.5) / ${L.BRICK_TEX_WIDTH}.0;
    float mvV = clamp(0.5 + mvLocal.y * 4.0, 0.5, 4.5) / ${L.BRICK_TEX_HEIGHT}.0;
    float mvDepth = max(1.0, mvSize.y * ${L.BRICK_SIZE}.0);
    float mvWCoord = (mvZOff + clamp(0.5 + mvLocal.z * 4.0, 0.5, 4.5)) / mvDepth;
    vec4 mvVis0 = min(vec4(1.0), textureLod(mvBricks, vec3(mvU0, mvV, mvWCoord), 0.0) * (255.0 / 254.0));
    vec4 mvVis1 = vec4(0.0);
    if (mvCount > 4) {
      mvVis1 = min(vec4(1.0), textureLod(mvBricks, vec3(mvU1, mvV, mvWCoord), 0.0) * (255.0 / 254.0));
    }
    vec4 mvEmitPack = texelFetch(mvLamps, mvBrickCoord(mvIdx, ${L.BRICK_ROW_EMITTERS}, mvW, mvFirst), 0);
    vec4 mvSc0 = texelFetch(mvLamps, mvBrickCoord(mvIdx, ${L.BRICK_ROW_SCALES_0}, mvW, mvFirst), 0);
    vec4 mvSc1 = texelFetch(mvLamps, mvBrickCoord(mvIdx, ${L.BRICK_ROW_SCALES_1}, mvW, mvFirst), 0);
    for (int mvK = 0; mvK < ${L.MAX_EMITTERS_PER_BRICK}; mvK++) {
      if (mvK >= mvCount) break;
      float mvPair = mvK < 2 ? mvEmitPack.x : (mvK < 4 ? mvEmitPack.y : (mvK < 6 ? mvEmitPack.z : mvEmitPack.w));
      float mvHi = floor(mvPair * ${INV_PACK_STRIDE});
      float mvLo = mvPair - mvHi * ${L.EMITTER_PACK_STRIDE}.0;
      int mvRow = int(((mvK & 1) != 0 ? mvHi : mvLo) + 0.5) - 1;
      if (mvRow < 0) continue;
      float mvVis = mvK < 4
        ? (mvK < 2 ? (mvK == 0 ? mvVis0.x : mvVis0.y) : (mvK == 2 ? mvVis0.z : mvVis0.w))
        : (mvK < 6 ? (mvK == 4 ? mvVis1.x : mvVis1.y) : (mvK == 6 ? mvVis1.z : mvVis1.w));
      if (mvVis <= 0.0) continue;
      float mvScale = mvK < 4
        ? (mvK < 2 ? (mvK == 0 ? mvSc0.x : mvSc0.y) : (mvK == 2 ? mvSc0.z : mvSc0.w))
        : (mvK < 6 ? (mvK == 4 ? mvSc1.x : mvSc1.y) : (mvK == 6 ? mvSc1.z : mvSc1.w));
      vec3 mvColor = texelFetch(mvLamps, mvEmitterCoord(mvRow, ${L.EMITTER_ROW_COLOR_SCALE}, mvW), 0).rgb * mvScale;
      if (mvColor.r + mvColor.g + mvColor.b <= 0.0) continue;
      vec4 mvPosR = texelFetch(mvLamps, mvEmitterCoord(mvRow, ${L.EMITTER_ROW_POS_RANGE}, mvW), 0);
      vec4 mvAxQ = texelFetch(mvLamps, mvEmitterCoord(mvRow, ${L.EMITTER_ROW_AXIS_OR_QUAT}, mvW), 0);
      vec4 mvShSz = texelFetch(mvLamps, mvEmitterCoord(mvRow, ${L.EMITTER_ROW_SHAPE_SIZE}, mvW), 0);
      vec3 mvRepPos = mvPosR.xyz;
      float mvFactor = 1.0;
      float mvShape = mvShSz.y;
      if (mvShape > 1.5) {
        float qx = mvAxQ.x, qy = mvAxQ.y, qz = mvAxQ.z, qw = mvAxQ.w;
        vec3 mvUAxis = vec3(1.0 - 2.0 * (qy * qy + qz * qz), 2.0 * (qx * qy + qw * qz), 2.0 * (qx * qz - qw * qy));
        vec3 mvVAxis = vec3(2.0 * (qx * qy - qw * qz), 1.0 - 2.0 * (qx * qx + qz * qz), 2.0 * (qy * qz + qw * qx));
        vec3 mvEmitN = -vec3(2.0 * (qx * qz + qw * qy), 2.0 * (qy * qz - qw * qx), 1.0 - 2.0 * (qx * qx + qy * qy));
        vec3 mvOff = vMvWorldPos - mvPosR.xyz;
        float mvTu = clamp(dot(mvOff, mvUAxis), -mvShSz.z, mvShSz.z);
        float mvTv = mvShape < 2.5 ? clamp(dot(mvOff, mvVAxis), -mvShSz.w, mvShSz.w) : 0.0;
        mvRepPos = mvPosR.xyz + mvUAxis * mvTu + mvVAxis * mvTv;
        vec3 mvFromRep = vMvWorldPos - mvRepPos;
        mvFactor = max(0.0, dot(mvEmitN, mvFromRep / max(length(mvFromRep), 1e-4)));
      }
      vec3 mvToLight = mvRepPos - vMvWorldPos;
      float mvD = length(mvToLight);
      vec3 mvDirW = mvToLight / max(mvD, 1e-4);
      float mvRange = mvPosR.w;
      float mvR = mvRange > 0.0 ? mvD / mvRange : 1.0;
      float mvR2 = mvR * mvR;
      float mvCut = clamp(1.0 - mvR2 * mvR2, 0.0, 1.0);
      mvCut *= mvCut;
      float mvFall = mvCut / max(mvD * mvD, 0.01);
      if (mvShape > 0.5 && mvShape < 1.5) {
        float mvCos = dot(mvAxQ.xyz, -mvDirW);
        float mvOuter = mvAxQ.w;
        float mvInner = mvShSz.x;
        mvFactor = mvInner == mvOuter ? step(mvOuter, mvCos) : smoothstep(mvOuter, mvInner, mvCos);
      }
      float mvWeight = mvFall * mvFactor * mvVis;
      if (mvWeight > 0.0) {
        IncidentLight mvIncident;
        mvIncident.color = mvColor * mvWeight;
        mvIncident.direction = mat3(viewMatrix) * mvDirW;
        mvIncident.visible = true;
        RE_Direct(mvIncident, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight);
      }
    }
  }
#endif
#if defined( RE_IndirectDiffuse )
  vec3 mvFill = texelFetch(mvLamps, mvBrickCoord(mvIdx, ${L.BRICK_ROW_FILL}, mvW, mvFirst), 0).rgb;
  if (mvFill.r + mvFill.g + mvFill.b > 0.0) {
    RE_IndirectDiffuse(mvFill, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight);
  }
#endif
}`;

function wrapUniform(entry) {
  return entry && typeof entry === 'object' && 'value' in entry ? entry : { value: entry ?? null };
}

// Keep all patch hook state strictly in a WeakMap (never in material.userData, which
// Material.copy clones through JSON and would leak stale keys onto cloned materials).
const mvState = new WeakMap();
export const isModelLightMaterial = material => mvState.has(material);

export function patchModelLighting(material, shared) {
  if (!material || !shared) return material;
  const uniforms = {
    mvBricks: wrapUniform(shared.mvBricks),
    mvLamps: wrapUniform(shared.mvLamps),
    mvSize: wrapUniform(shared.mvSize),
  };

  // Always ensure mvBrick defaults to 0 on every patched material.
  material.defaultAttributeValues = { ...material.defaultAttributeValues, mvBrick: [0] };

  // Idempotent on the same material instance: rebind uniforms without recompiling.
  const existing = mvState.get(material);
  if (existing) {
    existing.uniforms = uniforms;
    if (existing.shader) Object.assign(existing.shader.uniforms, uniforms);
    return material;
  }

  // Capture this material's own current hook & key (safe for clones that copied onBeforeCompile).
  const before = material.onBeforeCompile;
  const baseKey = material.customProgramCacheKey();
  const cacheKey = baseKey.includes(MODEL_LIGHT_CACHE_SUFFIX) ? baseKey : `${baseKey}${MODEL_LIGHT_CACHE_SUFFIX}`;
  const state = { before, cacheKey, uniforms, shader: null };
  mvState.set(material, state);

  material.onBeforeCompile = function (shader, renderer) {
    before.call(this, shader, renderer);
    if (!shader.fragmentShader.includes('#include <lights_fragment_end>')) return;
    const active = mvState.get(this) || state;
    active.shader = shader;
    Object.assign(shader.uniforms, active.uniforms);
    if (shader.fragmentShader.includes(INJECT_GUARD)) return;
    shader.vertexShader = VERTEX_DECL + '\n' + shader.vertexShader.replace('#include <project_vertex>', VERTEX_BODY);
    shader.fragmentShader = FRAGMENT_DECL + '\n' + shader.fragmentShader.replace('#include <lights_fragment_end>', FRAGMENT_BODY);
  };
  material.customProgramCacheKey = () => cacheKey;
  material.needsUpdate = true;
  return material;
}
