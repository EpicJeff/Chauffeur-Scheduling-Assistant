import * as THREE from 'three';

const FIXED_STEP = 1 / 60;
const MAX_STEPS = 2;

// Coordinates throughout this module are plan feet, [world X, -world Z].
export function simulationSize(body, longSide = 256) {
  const polygon = body.polygon || [];
  const xs = polygon.map(p => p[0]), ys = polygon.map(p => p[1]);
  const minX = xs.length ? Math.min(...xs) : 0, minY = ys.length ? Math.min(...ys) : 0;
  const widthFeet = Math.max(.01, xs.length ? Math.max(...xs) - minX : 1);
  const heightFeet = Math.max(.01, ys.length ? Math.max(...ys) - minY : 1);
  const longest = Math.max(16, Math.round(longSide));
  return {width: Math.max(16, Math.round(longest * widthFeet / Math.max(widthFeet, heightFeet))),
    height: Math.max(16, Math.round(longest * heightFeet / Math.max(widthFeet, heightFeet))),
    bounds: [minX, minY, widthFeet, heightFeet]};
}

function inside(polygon, x, y) {
  let result = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) result = !result;
  }
  return result;
}

// RGBA keeps the mask portable; nearest sampling makes dry neighbours walls.
export function rasterizeMask(body, width, height) {
  const {bounds: [minX, minY, sizeX, sizeY]} = simulationSize(body);
  const data = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const px = minX + (x + .5) / width * sizeX, py = minY + (y + .5) / height * sizeY;
    const wet = inside(body.polygon || [], px, py) && !(body.holes || []).some(hole => inside(hole, px, py));
    const index = (y * width + x) * 4;
    data[index] = data[index + 1] = data[index + 2] = wet ? 255 : 0;
    data[index + 3] = 255;
  }
  return data;
}

// Drop excess wall time instead of allowing a tab resume to start a catch-up spiral.
export function stepCount(delta, accumulator = 0) {
  const elapsed = Math.max(0, Number.isFinite(delta) ? delta : 0);
  const carry = Math.max(0, Number.isFinite(accumulator) ? accumulator : 0) % FIXED_STEP;
  const total = carry + Math.min(MAX_STEPS * FIXED_STEP, elapsed);
  const steps = Math.min(MAX_STEPS, Math.floor((total + 1e-10) / FIXED_STEP));
  return {steps, accumulator: Math.max(0, total - steps * FIXED_STEP)};
}

export function sourceDistance(point, line) {
  const a = Array.isArray(line) ? line : [line.x, line.y, line.z, line.w];
  const dx = a[2] - a[0], dy = a[3] - a[1];
  const t = Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / Math.max(dx * dx + dy * dy, .0001)));
  return Math.hypot(point[0] - a[0] - dx * t, point[1] - a[1] - dy * t);
}

const vertexShader = `varying vec2 vWaterUV;
void main() { vWaterUV = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;
const fragmentShader = `
precision highp float;
varying vec2 vWaterUV;
uniform sampler2D waterState;
uniform sampler2D waterMask;
uniform vec2 waterTexel;
uniform vec2 waterCell;
uniform vec4 waterBounds;
uniform vec4 rippleLines[8];
uniform float rippleStrength[8];
uniform float waterTime;
uniform float waveSpeed;

float heightAt(vec2 uv, float centre) {
  if (min(uv.x, uv.y) < 0.0 || max(uv.x, uv.y) > 1.0 || texture2D(waterMask, uv).r < .5) return centre;
  return texture2D(waterState, uv).r;
}
float hash(float n) { return fract(sin(n * 127.1 + 311.7) * 43758.5453); }
float noise(float t) { float f = fract(t); return mix(hash(floor(t)), hash(floor(t) + 1.0), f * f * (3.0 - 2.0 * f)) * 2.0 - 1.0; }
void main() {
  if (texture2D(waterMask, vWaterUV).r < .5) { gl_FragColor = vec4(0.0); return; }
  vec2 state = texture2D(waterState, vWaterUV).rg;
  float h = state.r;
  float lap = (heightAt(vWaterUV + vec2(waterTexel.x, 0.0), h) + heightAt(vWaterUV - vec2(waterTexel.x, 0.0), h) - 2.0 * h) / (waterCell.x * waterCell.x)
    + (heightAt(vWaterUV + vec2(0.0, waterTexel.y), h) + heightAt(vWaterUV - vec2(0.0, waterTexel.y), h) - 2.0 * h) / (waterCell.y * waterCell.y);
  vec2 point = waterBounds.xy + vWaterUV * waterBounds.zw;
  float push = 0.0;
  for (int i = 0; i < 8; i++) {
    vec2 a = rippleLines[i].xy, run = rippleLines[i].zw - a;
    vec2 delta = point - a - run * clamp(dot(point - a, run) / max(dot(run, run), .0001), 0.0, 1.0);
    float seed = float(i) * 19.731;
    float drive = .55 * noise(waterTime * 13.7 + seed) + .3 * sin(waterTime * 17.31 + seed) + .15 * sin(waterTime * 23.173 + seed * 2.3);
    float radius = max(.24, max(waterCell.x, waterCell.y) * 1.1);
    push += exp(-dot(delta, delta) / (radius * radius)) * rippleStrength[i] * drive * 12.0;
  }
  float velocity = (state.g + (waveSpeed * waveSpeed * lap + push) / 60.0) * exp(-1.8 / 60.0);
  float height = (h + velocity / 60.0) * exp(-.8 / 60.0);
  gl_FragColor = vec4(clamp(height, -.3, .3), clamp(velocity, -3.0, 3.0), 0.0, 1.0);
}`;

function saveState(renderer) {
  return {target: renderer.getRenderTarget(), face: renderer.getActiveCubeFace?.() || 0,
    mip: renderer.getActiveMipmapLevel?.() || 0, viewport: renderer.getViewport(new THREE.Vector4()).clone(),
    scissor: renderer.getScissor(new THREE.Vector4()).clone(), scissorTest: renderer.getScissorTest(),
    autoClear: renderer.autoClear, clearColor: renderer.getClearColor(new THREE.Color()).clone(),
    clearAlpha: renderer.getClearAlpha(), xr: renderer.xr?.enabled,
    infoAutoReset: renderer.info?.autoReset, infoRender: renderer.info?.render ? {...renderer.info.render} : null};
}

function restoreState(renderer, saved) {
  renderer.setRenderTarget(saved.target, saved.face, saved.mip);
  renderer.setViewport(saved.viewport);
  renderer.setScissor(saved.scissor);
  renderer.setScissorTest(saved.scissorTest);
  renderer.autoClear = saved.autoClear;
  renderer.setClearColor(saved.clearColor, saved.clearAlpha);
  if (renderer.xr) renderer.xr.enabled = saved.xr;
  if (renderer.info) {
    renderer.info.autoReset = saved.infoAutoReset;
    if (saved.infoRender) Object.assign(renderer.info.render, saved.infoRender);
  }
}

export function createWaterSimulation(body) {
  const {width, height, bounds} = simulationSize(body);
  const uniforms = {waterField: {value: null}, waterFieldBounds: {value: new THREE.Vector4(...bounds)},
    waterFieldTexel: {value: new THREE.Vector2(1 / width, 1 / height)}, waterFieldActive: {value: 0}};
  let targets = null, mask = null, material = null, quad = null, scene = null, camera = null;
  let disabled = false, disposed = false, lastSeconds = null, accumulator = 0, simSeconds = 0, quietSeconds = 0, settled = true;
  const frustum = new THREE.Frustum(), viewProjection = new THREE.Matrix4();
  const sphere = new THREE.Sphere(new THREE.Vector3(bounds[0] + bounds[2] / 2, body.level ?? body.height ?? 0, -bounds[1] - bounds[3] / 2), Math.hypot(bounds[2], bounds[3]) / 2 + 1);
  const worldSphere = new THREE.Sphere();

  function release() {
    targets?.forEach(target => target.dispose()); targets = null;
    mask?.dispose(); mask = null;
    material?.dispose(); material = null;
    quad?.geometry.dispose(); quad = null; scene = null; camera = null;
    uniforms.waterField.value = null; uniforms.waterFieldActive.value = 0;
  }

  function clear(renderer) {
    renderer.setClearColor(0, 0);
    for (const target of targets) { renderer.setRenderTarget(target); renderer.clear(true, false, false); }
  }

  function initialise(renderer) {
    const gl = renderer.getContext?.();
    if (!gl?.checkFramebufferStatus || !renderer.getViewport || !renderer.getScissor || !renderer.getClearColor) return false;
    // FBO completeness, rather than a browser/extension guess, is the final test.
    if (gl.getExtension && !gl.getExtension('EXT_color_buffer_float') && !gl.getExtension('EXT_color_buffer_half_float')) return false;
    targets = Array.from({length: 2}, () => new THREE.WebGLRenderTarget(width, height, {
      type: THREE.HalfFloatType, format: THREE.RGBAFormat, minFilter: THREE.NearestFilter,
      magFilter: THREE.NearestFilter, depthBuffer: false, stencilBuffer: false, generateMipmaps: false}));
    for (const target of targets) {
      renderer.setRenderTarget(target);
      if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) { release(); return false; }
    }
    mask = new THREE.DataTexture(rasterizeMask(body, width, height), width, height, THREE.RGBAFormat, THREE.UnsignedByteType);
    mask.minFilter = mask.magFilter = THREE.NearestFilter; mask.generateMipmaps = false; mask.needsUpdate = true;
    const cell = new THREE.Vector2(bounds[2] / width, bounds[3] / height);
    material = new THREE.ShaderMaterial({vertexShader, fragmentShader, depthTest: false, depthWrite: false,
      blending: THREE.NoBlending, uniforms: {waterState: {value: null}, waterMask: {value: mask},
        waterTexel: uniforms.waterFieldTexel, waterCell: {value: cell}, waterBounds: uniforms.waterFieldBounds,
        waterTime: {value: 0}, waveSpeed: {value: Math.min(4, .62 * Math.min(cell.x, cell.y) / FIXED_STEP)},
        rippleLines: {value: Array.from({length: 8}, () => new THREE.Vector4())}, rippleStrength: {value: Array(8).fill(0)}}});
    scene = new THREE.Scene(); camera = new THREE.Camera();
    quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material); quad.frustumCulled = false; scene.add(quad);
    clear(renderer);
    uniforms.waterField.value = targets[0].texture; uniforms.waterFieldActive.value = 1;
    return true;
  }

  return {body, uniforms,
    update(renderer, seconds, rippleUniforms, options = {}) {
      if (disposed || disabled || !renderer || !Number.isFinite(seconds)) return;
      const delta = lastSeconds == null ? FIXED_STEP : Math.max(0, seconds - lastSeconds); lastSeconds = seconds;
      const strengths = rippleUniforms?.rippleStrength?.value || [];
      const driven = strengths.some(strength => strength > .0001);
      const visible = options.mesh ? (() => { for (let mesh = options.mesh; mesh; mesh = mesh.parent) if (mesh.visible === false) return false; return true; })() : true;
      if (!visible) { accumulator = 0; return; }
      if (options.camera?.isCamera) {
        options.camera.updateMatrixWorld();
        viewProjection.multiplyMatrices(options.camera.projectionMatrix, options.camera.matrixWorldInverse);
        frustum.setFromProjectionMatrix(viewProjection, options.camera.coordinateSystem, options.camera.reversedDepth);
        // The merged water geometry and bounds are plan feet; the mounted twin
        // scales its ancestor root to metres. Refresh ancestors before the draw.
        worldSphere.copy(sphere);
        if (options.mesh?.matrixWorld) {
          options.mesh.updateWorldMatrix(true, false);
          worldSphere.applyMatrix4(options.mesh.matrixWorld);
        }
        if (!frustum.intersectsSphere(worldSphere)) { accumulator = 0; return; }
      }
      if (settled && !driven) return;
      // A light renderer stand-in or unsupported GPU keeps the analytic path.
      const required = ['getContext', 'getRenderTarget', 'getViewport', 'getScissor', 'getScissorTest', 'getClearColor',
        'getClearAlpha', 'setRenderTarget', 'setViewport', 'setScissor', 'setScissorTest', 'setClearColor', 'clear', 'render'];
      if (!required.every(name => typeof renderer[name] === 'function')) { disabled = true; return; }
      const saved = saveState(renderer);
      try {
        renderer.autoClear = false; renderer.setScissorTest(false);
        if (renderer.xr) renderer.xr.enabled = false;
        if (renderer.info) renderer.info.autoReset = false;
        if (!targets && !initialise(renderer)) { disabled = true; return; }
        if (driven) { quietSeconds = 0; settled = false; }
        const count = stepCount(delta, accumulator); accumulator = count.accumulator;
        quietSeconds = driven ? 0 : quietSeconds + count.steps * FIXED_STEP;
        if (quietSeconds > 10) { clear(renderer); settled = true; accumulator = 0; return; }
        if (rippleUniforms?.rippleLines) material.uniforms.rippleLines.value = rippleUniforms.rippleLines.value;
        if (rippleUniforms?.rippleStrength) material.uniforms.rippleStrength.value = strengths;
        for (let step = 0; step < count.steps; step++) {
          simSeconds += FIXED_STEP;
          material.uniforms.waterTime.value = simSeconds;
          material.uniforms.waterState.value = targets[0].texture;
          renderer.setRenderTarget(targets[1]); renderer.setViewport(0, 0, width, height);
          renderer.render(scene, camera);
          targets.reverse();
        }
        uniforms.waterField.value = targets[0].texture;
      } catch (_) {
        // A context/target failure must never take away the water or its ripples.
        release(); disabled = true;
      } finally { restoreState(renderer, saved); }
    },
    dispose() { if (disposed) return; disposed = true; release(); },
  };
}
