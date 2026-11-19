import * as THREE from 'three';

// Shared by every twin scene; each scene binds its own uniform objects. Keep
// USE_FOG set from mount onwards, including Unlit, probes and mirror passes.
let installed = false;
const hooks = new WeakMap();
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
uniform samplerCube stageSky;
varying vec3 vStageWorld;
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
  // The cube is a render-target cube: r187's flipEnvMap is +1.
  // Preserve depression as well as azimuth, matching the background's ground
  // aerial perspective for raised cameras and the low-tier canvas too.
  vec3 stageColour = textureCube( stageSky, stageRay ).rgb;
  stageColour = vec3( stageColour.r >= 0.0 ? min( stageColour.r, 4096.0 ) : 0.0,
    stageColour.g >= 0.0 ? min( stageColour.g, 4096.0 ) : 0.0,
    stageColour.b >= 0.0 ? min( stageColour.b, 4096.0 ) : 0.0 );
  // Stock fog runs AFTER output conversion. Match the cube background on both
  // the low-tier canvas and the composer's linear half-float target.
  if ( stageCanvas > 0.5 ) stageColour = stageToneMapping( stageColour );
  stageColour = linearToOutputTexel( vec4( stageColour, 1.0 ) ).rgb;
  gl_FragColor.rgb = mix( gl_FragColor.rgb, stageColour, stageFade );
#endif`;
}

export function stageFade(point, centre, radius) {
  const r = Math.max(radius, .0001), t = Math.max(0, Math.min(1, (Math.hypot(point[0]-centre[0], point[1]-centre[1])-r)/(r*.35)));
  return t*t*(3-2*t);
}

export function installStageHaze(scene, sky) {
  installChunks();
  scene.fog = new THREE.Fog(0, 0, 1);
  const uniforms = {stageCentre:{value:new THREE.Vector2()}, stageRadius:{value:1},
    stageSky:{value:sky.cube}, stageEnabled:{value:1}, stageCanvas:{value:0}, stageExposure:{value:1}};
  const patched = new WeakMap();
  function prepare(root = scene) {
    root.traverse(object => {
      for (const material of [].concat(object.material || [])) {
        // Effect ShaderMaterials stay inside the lot and deliberately omit fog.
        if (!material.fog || material.isShaderMaterial) continue;
        if (patched.get(material) === material.onBeforeCompile) continue;
        // Grass, water and viewing clones may carry the wrapped hook. Unwrap
        // it so a clone gets the same key and this scene's uniforms exactly once.
        const source = hooks.get(material.onBeforeCompile);
        const compile = source?.compile || material.onBeforeCompile, key = source?.key || material.customProgramCacheKey;
        material.onBeforeCompile = function(shader, renderer) {
          compile.call(this, shader, renderer);
          Object.assign(shader.uniforms, uniforms);
        };
        material.customProgramCacheKey = function() {
          return (key === THREE.Material.prototype.customProgramCacheKey ? compile.toString() : key.call(this)) + '|stage-haze-1';
        };
        hooks.set(material.onBeforeCompile, {compile, key});
        patched.set(material, material.onBeforeCompile);
      }
    });
  }
  const previous = scene.onBeforeRender;
  scene.onBeforeRender = function(renderer, ...args) {
    previous.call(this, renderer, ...args);
    const target = renderer.getRenderTarget();
    uniforms.stageCanvas.value = !target || target.isXRRenderTarget ? 1 : 0;
    uniforms.stageExposure.value = Number.isFinite(renderer.toneMappingExposure) ? renderer.toneMappingExposure : 1;
    prepare();
  };
  return {prepare,
    set({centre, radius, enabled} = {}) {
      if (centre?.every(Number.isFinite)) uniforms.stageCentre.value.fromArray(centre);
      if (Number.isFinite(radius) && radius > 0) uniforms.stageRadius.value = radius;
      if (enabled !== undefined) uniforms.stageEnabled.value = enabled ? 1 : 0;
    },
    dispose() { scene.onBeforeRender = previous; },
  };
}
