// GPU visibility accumulator for the light-visibility grid.
// Uses one float render target with one texel per (point, emitter) arranged as
// emitterCount horizontal bands of (pointCols x pointRows). Each sample() call
// tests all indexed points against the lamp's shadow cube depth map using the
// exact same depth test as bake_pass.js (step(reached - 0.02, stored)) and
// additively accumulates weight * visible into that emitter's band.
import * as THREE from '../../vendor/three-r187/three.module.js';

const vertexShader = `varying vec2 vUv;
void main() {
  vUv = position.xy * 0.5 + 0.5;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}`;

const fragmentShader = `uniform sampler2D pointsTex;
uniform samplerCube depthCube;
uniform vec3 source;
uniform float farPlane;
uniform float weight;
varying vec2 vUv;
void main() {
  vec4 pt = texture2D(pointsTex, vUv);
  if (pt.w < 0.5) discard;
  vec3 fromSource = pt.xyz - source;
  float reached = length(fromSource);
  float stored = reached > 1e-5 ? textureCube(depthCube, fromSource).r * farPlane : farPlane;
  float visible = step(reached - 0.02, stored);
  gl_FragColor = vec4(weight * visible, 0.0, 0.0, 1.0);
}`;

export function createGridAccumulator(renderer, points, indices, emitterCount) {
  const n = indices?.length || 0;
  const emitters = Math.max(0, emitterCount | 0);
  if (!n || !emitters) {
    return {
      sample() {},
      read() { return new Uint8Array(0); },
      dispose() {},
    };
  }

  // Enable float render targets and float additive blending in WebGL2.
  const hasFloat = !!renderer.extensions.get('EXT_color_buffer_float');
  const hasFloatBlend = hasFloat && !!renderer.extensions.get('EXT_float_blend');
  const rtType = hasFloatBlend ? THREE.FloatType : THREE.HalfFloatType;

  const maxTex = Math.min(2048, renderer.capabilities.maxTextureSize || 2048);
  const pointCols = Math.min(n, maxTex);
  const pointRows = Math.ceil(n / pointCols);
  const targetWidth = pointCols;
  const targetHeight = pointRows * emitters;
  if (targetHeight > (renderer.capabilities.maxTextureSize || 4096)) {
    throw new Error(`Grid accumulator height (${targetHeight}) exceeds max texture size.`);
  }

  // Upload indexed world-space points once into an RGBA32F DataTexture.
  const posData = new Float32Array(pointCols * pointRows * 4);
  for (let i = 0; i < n; i++) {
    const pIdx = indices[i] * 3;
    const o = i * 4;
    posData[o] = points[pIdx];
    posData[o + 1] = points[pIdx + 1];
    posData[o + 2] = points[pIdx + 2];
    posData[o + 3] = 1.0;
  }
  const pointsTex = new THREE.DataTexture(posData, pointCols, pointRows, THREE.RGBAFormat, THREE.FloatType);
  pointsTex.flipY = false;
  pointsTex.minFilter = THREE.NearestFilter;
  pointsTex.magFilter = THREE.NearestFilter;
  pointsTex.generateMipmaps = false;
  pointsTex.needsUpdate = true;

  const target = new THREE.WebGLRenderTarget(targetWidth, targetHeight, {
    format: THREE.RGBAFormat,
    type: rtType,
    minFilter: THREE.NearestFilter,
    magFilter: THREE.NearestFilter,
    depthBuffer: false,
    stencilBuffer: false,
  });

  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    depthTest: false,
    depthWrite: false,
    transparent: true,
    blending: THREE.CustomBlending,
    blendEquation: THREE.AddEquation,
    blendSrc: THREE.OneFactor,
    blendDst: THREE.OneFactor,
    blendSrcAlpha: THREE.OneFactor,
    blendDstAlpha: THREE.OneFactor,
    uniforms: {
      pointsTex: { value: pointsTex },
      depthCube: { value: null },
      source: { value: new THREE.Vector3() },
      farPlane: { value: 30 },
      weight: { value: 1 },
    },
  });

  const quadGeo = new THREE.BufferGeometry();
  quadGeo.setAttribute('position', new THREE.Float32BufferAttribute([-1, -1, 0, 3, -1, 0, -1, 3, 0], 3));
  const quad = new THREE.Mesh(quadGeo, material);
  quad.frustumCulled = false;
  const scene = new THREE.Scene();
  scene.add(quad);
  const camera = new THREE.Camera();

  const weightSums = new Float64Array(emitters);
  const savedColor = new THREE.Color();
  const savedViewport = new THREE.Vector4();
  const savedScissor = new THREE.Vector4();
  let disposed = false;

  const saveState = () => {
    const state = {
      target: renderer.getRenderTarget(),
      alpha: renderer.getClearAlpha(),
      tone: renderer.toneMapping,
      autoClear: renderer.autoClear,
      xr: renderer.xr.enabled,
      scissorTest: renderer.getScissorTest(),
    };
    renderer.getClearColor(savedColor);
    renderer.getViewport(savedViewport);
    renderer.getScissor(savedScissor);
    return state;
  };

  const restoreState = state => {
    renderer.setRenderTarget(state.target);
    renderer.setClearColor(savedColor, state.alpha);
    renderer.toneMapping = state.tone;
    renderer.autoClear = state.autoClear;
    renderer.xr.enabled = state.xr;
    renderer.setViewport(savedViewport);
    renderer.setScissor(savedScissor);
    renderer.setScissorTest(state.scissorTest);
  };

  // Clear the accumulator render target once.
  {
    const st = saveState();
    try {
      renderer.toneMapping = THREE.NoToneMapping;
      renderer.xr.enabled = false;
      target.scissorTest = false;
      target.viewport.set(0, 0, targetWidth, targetHeight);
      renderer.setRenderTarget(target);
      renderer.setScissorTest(false);
      renderer.setClearColor(0x000000, 0);
      renderer.clear(true, false, false);
    } finally {
      restoreState(st);
    }
  }

  return {
    sample(shadowTexture, source, far, emitter, weight) {
      if (disposed) throw new Error('Grid accumulator has been disposed.');
      const e = emitter | 0;
      if (e < 0 || e >= emitters) throw new RangeError(`Emitter index ${emitter} out of range [0, ${emitters}).`);
      if (!(weight > 0)) return;
      weightSums[e] += weight;

      const u = material.uniforms;
      u.depthCube.value = shadowTexture;
      u.source.value.set(source.x, source.y, source.z);
      u.farPlane.value = far;
      u.weight.value = weight;

      const bandY = e * pointRows;
      const st = saveState();
      try {
        renderer.toneMapping = THREE.NoToneMapping;
        renderer.xr.enabled = false;
        renderer.autoClear = false;
        target.viewport.set(0, bandY, pointCols, pointRows);
        target.scissor.set(0, bandY, pointCols, pointRows);
        target.scissorTest = true;
        renderer.setRenderTarget(target);
        renderer.setViewport(0, bandY, pointCols, pointRows);
        renderer.setScissor(0, bandY, pointCols, pointRows);
        renderer.setScissorTest(true);
        renderer.render(scene, camera);
      } finally {
        restoreState(st);
      }
    },

    read() {
      if (disposed) throw new Error('Grid accumulator has been disposed.');
      const pixelCount = targetWidth * targetHeight;
      const raw = rtType === THREE.FloatType
        ? new Float32Array(pixelCount * 4)
        : new Uint16Array(pixelCount * 4);
      const st = saveState();
      try {
        target.scissorTest = false;
        target.viewport.set(0, 0, targetWidth, targetHeight);
        renderer.readRenderTargetPixels(target, 0, 0, targetWidth, targetHeight, raw);
      } finally {
        restoreState(st);
      }

      const out = new Uint8Array(n * emitters);
      const bandPixels = pointCols * pointRows;
      for (let e = 0; e < emitters; e++) {
        const wSum = weightSums[e];
        if (!(wSum > 0)) continue;
        const invW = 1 / wSum;
        const bandOff = e * bandPixels;
        for (let i = 0; i < n; i++) {
          const r = raw[(bandOff + i) * 4];
          const val = rtType === THREE.FloatType ? r : THREE.DataUtils.fromHalfFloat(r);
          const norm = Math.min(1, Math.max(0, val * invW));
          out[i * emitters + e] = Math.round(norm * 254);
        }
      }
      return out;
    },

    dispose() {
      if (disposed) return;
      disposed = true;
      target.dispose();
      pointsTex.dispose();
      quadGeo.dispose();
      material.dispose();
    },
  };
}
