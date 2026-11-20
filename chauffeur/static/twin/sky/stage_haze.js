import * as THREE from 'three';

// Shared by every twin scene; each scene binds its own uniform objects. Keep
// USE_FOG set from mount onwards, including Unlit, probes and mirror passes.
let installed = false;
const hooks = new WeakMap();
// One environment wrapper, including on clones. Haze and cloud shadows bind
// independently, but must not mistake each other's hook for a new base hook.
const appliedPatches=new WeakMap();
export function bindEnvironmentMaterial(material, name, uniforms, patch = null) {
  const source=hooks.get(material.onBeforeCompile);
  if(source?.bindings.get(name)?.uniforms===uniforms)return;
  const compile=source?.compile || material.onBeforeCompile;
  const key=source?.key ?? (material.customProgramCacheKey===THREE.Material.prototype.customProgramCacheKey
    ? compile.toString() : material.customProgramCacheKey());
  const bindings=new Map(source?.bindings);bindings.set(name,{uniforms,patch});
  material.onBeforeCompile=function(shader,renderer) {
    compile.call(this,shader,renderer);
    // Another system (lightmaps, water, unlit...) may wrap this hook after binding;
    // the next bind then wraps that wrapper. Apply each named patch once per compile.
    let applied=appliedPatches.get(shader);
    if(!applied)appliedPatches.set(shader,applied=new Set());
    for(const [name,{uniforms,patch}] of bindings) {
      Object.assign(shader.uniforms,uniforms);
      if(applied.has(name))continue;
      applied.add(name);patch?.(shader);
    }
  };
  material.customProgramCacheKey=()=>key+[...bindings.keys()].sort().map(name=>'|'+name).join('');
  hooks.set(material.onBeforeCompile,{compile,key,bindings});
}
// A scene hook runs before every pass (mirror, AO, beauty, transparent, probe
// faces); binding walks the whole scene. Nothing joins the scene between the
// passes of one frame, so walk once per frame. The frame is the twin's own
// count (startEnvironmentFrame, called once by twin_view's render): three r187
// bumps info.render.frame on EVERY render call, so it cannot key this (the
// v2.499.954 gate did and saved nothing on the owner's house). A scene whose
// frames nobody counts walks every pass, as before.
const environmentFrames = new WeakMap();
export function startEnvironmentFrame(scene) {
  environmentFrames.set(scene, (environmentFrames.get(scene) || 0) + 1);
}
export function oncePerFrame(scene, prepare) {
  let walked = 0;
  return () => {
    const frame = environmentFrames.get(scene);
    if (frame !== undefined && frame === walked) return;
    walked = frame ?? 0; prepare();
  };
}
function installChunks() {
  if (installed) return;
  installed = true;
  THREE.ShaderChunk.fog_pars_vertex = `
#ifdef USE_FOG
varying vec3 vStageWorld;
#endif`;
  THREE.ShaderChunk.fog_vertex = `
#ifdef USE_FOG
  vec4 stageWorld = vec4( transformed, 1.0 );
  #ifdef USE_BATCHING
    stageWorld = batchingMatrix * stageWorld;
  #endif
  #ifdef USE_INSTANCING
    stageWorld = instanceMatrix * stageWorld;
  #endif
  vStageWorld = ( modelMatrix * stageWorld ).xyz;
#endif`;
  THREE.ShaderChunk.fog_pars_fragment = `
#ifdef USE_FOG
uniform vec2 stageCentre;
uniform float stageRadius, stageEnabled, stageCanvas, stageExposure;
// The sky's colour on a ring of directions (8 azimuths x 5 depressions), not a
// cube sampler: a sampler here cost every lit material one texture unit, and
// water, glass and lamp-shadowed materials ran past the 16 units ANGLE gives
// (owner's console, 2026-11-18). Haze is a smooth gradient; 40 colours hold it.
// vec3 array entries already cost one vector each. Their padded w lanes now
// carry extinction and fog RGB; vector and sampler totals are unchanged.
uniform vec4 stageRing[40];
varying vec3 vStageWorld;
// Callers supply azimuths 0..9 (the interpolated neighbour can cross 8).
vec3 stageRingAt( int az, int el ) { return stageRing[ el * 8 + ( az >= 8 ? az - 8 : az ) ].xyz; }
vec3 stageSkyColour( vec3 ray ) {
  float az = atan( ray.z, ray.x ) / 6.28318531 * 8.0;
  az = az < 0.0 ? az + 8.0 : az;
  float depression = degrees( asin( clamp( -ray.y, -1.0, 1.0 ) ) );
  // Depression bands at 0, 2, 6, 15 and 40 degrees below the horizon.
  // Sum the four saturated band ramps. This is the same piecewise-linear
  // coordinate without the nested conditional tree FXC has to optimise.
  vec4 bands = clamp( ( vec4( depression ) - vec4( 0.0, 2.0, 6.0, 15.0 ) ) / vec4( 2.0, 4.0, 9.0, 25.0 ), 0.0, 1.0 );
  float el = dot( bands, vec4( 1.0 ) );
  int a0 = int( floor( az ) ), e0 = int( floor( el ) ), e1 = min( e0 + 1, 4 );
  float fa = az - floor( az ), fe = el - floor( el );
  vec3 lower = mix( stageRingAt( a0, e0 ), stageRingAt( a0 + 1, e0 ), fa );
  vec3 upper = mix( stageRingAt( a0, e1 ), stageRingAt( a0 + 1, e1 ), fa );
  return mix( lower, upper, fe );
}
// r187 ACESFilmicToneMapping. Haze follows the destination even when its
// surface is an intentionally untonemapped bulb or luminous line.
vec3 stageToneMapping( vec3 colour ) {
  const mat3 inputMatrix = mat3( 0.59719, 0.07600, 0.02840, 0.35458, 0.90834, 0.13383, 0.04823, 0.01566, 0.83777 );
  const mat3 outputMatrix = mat3( 1.60475, -0.10208, -0.00327, -0.53108, 1.10813, -0.07276, -0.07367, -0.00605, 1.07602 );
  vec3 v = inputMatrix * ( colour * stageExposure / 0.6 );
  vec3 a = v * ( v + 0.0245786 ) - 0.000090537;
  vec3 b = v * ( 0.983729 * v + 0.4329510 ) + 0.238081;
  return clamp( outputMatrix * ( a / max( b, vec3( 0.0001 ) ) ), 0.0, 1.0 );
}
#endif`;
  THREE.ShaderChunk.fog_fragment = `
#ifdef USE_FOG
  float stageR = max( stageRadius, 0.0001 );
  float stageFade = stageEnabled * smoothstep( stageR, stageR * 1.35, distance( vStageWorld.xz, stageCentre ) );
  vec3 stageView = isOrthographic ? -vec3( viewMatrix[0].z, viewMatrix[1].z, viewMatrix[2].z ) : vStageWorld - cameraPosition;
  float stageLength = length( stageView );
  vec3 stageRay = stageLength > 0.0001 ? stageView / max( stageLength, 0.0001 ) : vec3( 0.0, -1.0, 0.0 );
  // Preserve depression as well as azimuth, matching the background's ground
  // aerial perspective for raised cameras and the low-tier canvas too.
  vec3 stageColour = stageSkyColour( stageRay );
  float stageFog = stageEnabled * ( 1.0 - exp( -max( stageRing[0].w, 0.0 ) * distance( vStageWorld, cameraPosition ) ) );
  vec3 stageFogColour = vec3( stageRing[1].w, stageRing[2].w, stageRing[3].w );
  stageColour = mix( stageColour, stageFogColour, stageFog / max( max( stageFade, stageFog ), 0.0001 ) );
  stageColour = vec3( stageColour.r >= 0.0 ? min( stageColour.r, 4096.0 ) : 0.0,
    stageColour.g >= 0.0 ? min( stageColour.g, 4096.0 ) : 0.0,
    stageColour.b >= 0.0 ? min( stageColour.b, 4096.0 ) : 0.0 );
  // Stock fog runs AFTER output conversion. Match the cube background on both
  // the low-tier canvas and the composer's linear half-float target.
  if ( stageCanvas > 0.5 ) stageColour = stageToneMapping( stageColour );
  stageColour = linearToOutputTexel( vec4( stageColour, 1.0 ) ).rgb;
  gl_FragColor.rgb = mix( gl_FragColor.rgb, stageColour, max( stageFade, stageFog ) );
#endif`;
}

export function stageFade(point, centre, radius) {
  const r = Math.max(radius, .0001), t = Math.max(0, Math.min(1, (Math.hypot(point[0]-centre[0], point[1]-centre[1])-r)/(r*.35)));
  return t*t*(3-2*t);
}
export function cameraFogFactor(distanceM,extinction) {
  return 1-Math.exp(-Math.max(0,Number.isFinite(extinction)?extinction:0)*Math.max(0,Number.isFinite(distanceM)?distanceM:0));
}

export const STAGE_RING_DEPRESSIONS = [0, 2, 6, 15, 40];
// Ring direction for azimuth index a (0..7, from +x toward +z) and depression band e.
export function stageRingDirection(a, e) {
  const az = a / 8 * Math.PI * 2, down = STAGE_RING_DEPRESSIONS[e] * Math.PI / 180;
  return [Math.cos(az) * Math.cos(down), -Math.sin(down), Math.sin(az) * Math.cos(down)];
}

export function installStageHaze(scene, sky) {
  installChunks();
  scene.fog = new THREE.Fog(0, 0, 1);
  // 40 vec4s packed flat (rgb = sky radiance, w = the extinction and fog colour
  // slots below): uniform4fv takes a Float32Array as it stands, where 40 Vector4s
  // were flattened again on every lit draw of every pass (2026-11-20 profile).
  const ring = new Float32Array(40 * 4);
  const uniforms = {stageCentre:{value:new THREE.Vector2()}, stageRadius:{value:1},
    stageRing:{value:ring}, stageEnabled:{value:1}, stageCanvas:{value:0}, stageExposure:{value:1}};
  // The same CPU radiance the cube is drawn from; refreshed whenever the sky changes.
  const guard = v => Number.isFinite(v) && v > 0 ? Math.min(v, 4096) : 0;
  function refresh() {
    if (!sky?.horizon) return;
    for (let e = 0; e < 5; e++) for (let a = 0; a < 8; a++) {
      const c = sky.horizon(stageRingDirection(a, e));
      const at=(e*8+a)*4;ring[at]=guard(c.r);ring[at+1]=guard(c.g);ring[at+2]=guard(c.b);
    }
  }
  refresh();
  function prepare(root = scene) {
    root.traverse(object => {
      for (const material of [].concat(object.material || [])) {
        // Effect ShaderMaterials stay inside the lot and deliberately omit fog.
        if (!material.fog || material.isShaderMaterial) continue;
        bindEnvironmentMaterial(material,'stage-haze-1',uniforms);
      }
    });
  }
  const previous = scene.onBeforeRender, walk = oncePerFrame(scene, () => prepare());
  scene.onBeforeRender = function(renderer, ...args) {
    previous.call(this, renderer, ...args);
    const target = renderer.getRenderTarget();
    uniforms.stageCanvas.value = !target || target.isXRRenderTarget ? 1 : 0;
    uniforms.stageExposure.value = Number.isFinite(renderer.toneMappingExposure) ? renderer.toneMappingExposure : 1;
    walk();
  };
  return {prepare, refresh,
    set({centre, radius, enabled, extinction, fogColour} = {}) {
      if (centre?.every(Number.isFinite)) uniforms.stageCentre.value.fromArray(centre);
      if (Number.isFinite(radius) && radius > 0) uniforms.stageRadius.value = radius;
      if (Number.isFinite(extinction)) ring[3]=Math.max(0,extinction);
      if (fogColour?.every(Number.isFinite)) for(let i=0;i<3;i++)ring[(i+1)*4+3]=guard(fogColour[i]);
      if (enabled !== undefined) uniforms.stageEnabled.value = enabled ? 1 : 0;
    },
    dispose() { scene.onBeforeRender = previous; },
  };
}
