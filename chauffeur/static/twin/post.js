import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

// Metres, not feet. Screen-space AO darkens the whole lit picture, not just
// the sky's share; this is the accepted limit of this contact-darkening pass.
// The values were set by eye on the fixture house: darkening under eaves,
// porches and at wall feet reads, and wall corners do not streak.
const OCCLUSION_RADIUS = 1;
const OCCLUSION_STRENGTH = .7;
const OCCLUSION_DISTANCE_FALLOFF = .6;
const OCCLUSION_CONTRAST = 1.5;
const OCCLUSION_THICKNESS = 2;
const DENOISE_RADIUS = 8;

function excluded(object) {
  const d = object.userData;
  return d.noOcclusion || d.ghost || d.preview || d.aimHandle || d.fixtureId ||
    object.isSprite || object.isLine || object.isLine2 || object.isPoints || object.isHelper ||
    object.layers.isEnabled(31) ||
    [].concat(object.material || []).some(m => m.userData.noOcclusion || seeThrough(m) ||
      m.alphaTest > 0 || m.alphaHash || m.depthTest === false || m.isShaderMaterial);
}
// The level fades draw every solid surface through a transparent copy, so
// that flag alone would drop the whole house. A copy of a solid surface
// counts as solid until its fade stops it writing depth. Glass counts as
// solid too: hidden, the room behind a pane would shade the pane itself and
// every window would go dark.
const seeThrough = m => m.transparent && m.name !== 'glass' && !(m.userData.viewingOpaque && m.depthWrite);

// A Color background is a clear, so the plain canvas path never tone maps it.
// Undo ACES for that clear only; OutputPass then returns the original colour.
// Fog stays in scene-linear space and receives ACES once, as on the plain path.
const inverseInput = new THREE.Matrix3().set(.59719,.35458,.04823, .076,.90834,.01566, .0284,.13383,.83777).invert();
const inverseOutput = new THREE.Matrix3().set(1.60475,-.53108,-.07367, -.10208,1.10813,-.00605, -.00327,-.07276,1.07602).invert();
function linearBackground(color, renderer, result) {
  result.copy(color);
  if (renderer.toneMapping !== THREE.ACESFilmicToneMapping) return result;
  const v = new THREE.Vector3(color.r, color.g, color.b).applyMatrix3(inverseOutput);
  const inverseFit = y => {
    const a = 1 - .983729 * y, b = .0245786 - .432951 * y, c = -.000090537 - .238081 * y;
    return (-b + Math.sqrt(b * b - 4 * a * c)) / (2 * a);
  };
  v.set(inverseFit(v.x), inverseFit(v.y), inverseFit(v.z)).applyMatrix3(inverseInput)
    .multiplyScalar(.6 / renderer.toneMappingExposure);
  return result.setRGB(v.x, v.y, v.z);
}

export function createPost(renderer, scene, camera, { samples = 0 } = {}) {
  const target = new THREE.WebGLRenderTarget(1, 1, {type: THREE.HalfFloatType, samples});
  const composer = new EffectComposer(renderer, target);
  const beauty = new RenderPass(scene, camera);
  const occlusion = new GTAOPass(scene, camera, 1, 1, undefined, {
    radius: OCCLUSION_RADIUS, distanceFallOff: OCCLUSION_DISTANCE_FALLOFF, screenSpaceRadius: false,
    scale: OCCLUSION_CONTRAST, thickness: OCCLUSION_THICKNESS,
  }, {radius: DENOISE_RADIUS});
  occlusion.blendIntensity = OCCLUSION_STRENGTH;
  const output = new OutputPass();
  composer.addPass(beauty);
  composer.addPass(occlusion);
  // Future bloom belongs here, before the single output transform.
  composer.addPass(output);
  let disposed = false, size = {}, mainStats = {calls: 0, triangles: 0};
  const backgroundColor = new THREE.Color();
  const drawBeauty = beauty.render.bind(beauty);
  beauty.render = (...args) => {
    const background = scene.background, before = {...renderer.info.render};
    try {
      if (background?.isColor) scene.background = linearBackground(background, renderer, backgroundColor);
      // r187 leaves render targets scene-linear even with ACES set on renderer.
      drawBeauty(...args);
      mainStats = {calls: renderer.info.render.calls - before.calls, triangles: renderer.info.render.triangles - before.triangles};
    } finally { scene.background = background; }
  };

  // Only the normal/depth pre-pass hides these objects. Do not hide them for
  // the beauty pass or AO composite. Vendor hooks lack exception restoration.
  occlusion._overrideVisibility = () => {}; // Our try/finally also owns lines and points.
  const drawOverride = occlusion._renderOverride.bind(occlusion);
  // A cut floor is clipped by planes on its own materials, which the override
  // material does not carry: the cut-away half would still occlude. Those
  // meshes draw with a normal material that holds their planes and refuses
  // the override.
  const clipped = new Map();
  const clippedNormal = (m, used) => {
    const key = m.clippingPlanes[0];
    used.add(key);
    if (!clipped.has(key)) {
      const normal = occlusion.normalMaterial.clone();
      normal.allowOverride = false; normal.clippingPlanes = m.clippingPlanes;
      clipped.set(key, normal);
    }
    return clipped.get(key);
  };
  occlusion._renderOverride = (...args) => {
    const hidden = [], swapped = [], used = new Set(), background = scene.background, override = scene.overrideMaterial;
    const shadows = renderer.shadowMap.enabled;
    try {
      scene.traverse(o => {
        if (!o.visible) return;
        if (excluded(o)) { hidden.push(o); o.visible = false; return; }
        const m = o.material;
        if (!o.isMesh || ![].concat(m).some(x => x?.clippingPlanes?.length)) return;
        swapped.push([o, m]);
        const normal = x => x.clippingPlanes?.length ? clippedNormal(x, used) : occlusion.normalMaterial;
        o.material = Array.isArray(m) ? m.map(normal) : normal(m);
      });
      scene.background = null;
      renderer.shadowMap.enabled = false;
      drawOverride(...args);
    } finally {
      hidden.forEach(o => { o.visible = true; });
      swapped.forEach(([o, m]) => { o.material = m; });
      for (const [key, m] of clipped) if (!used.has(key)) { m.dispose(); clipped.delete(key); }
      scene.background = background; scene.overrideMaterial = override;
      renderer.shadowMap.enabled = shadows;
    }
  };

  function setSize(width, height, pixelRatio = renderer.getPixelRatio()) {
    if (disposed || (size.width === width && size.height === height && size.pixelRatio === pixelRatio)) return;
    size = {width, height, pixelRatio};
    composer.setPixelRatio(pixelRatio);
    composer.setSize(width, height);
  }
  function setCamera(next) {
    beauty.camera = occlusion.camera = next;
    const perspective = next.isPerspectiveCamera ? 1 : 0;
    for (const m of [occlusion.gtaoMaterial, occlusion.depthRenderMaterial]) {
      if (m.defines.PERSPECTIVE_CAMERA !== perspective) {
        m.defines.PERSPECTIVE_CAMERA = perspective; m.needsUpdate = true;
      }
    }
  }
  return {
    setCamera, setSize,
    render() {
      if (disposed) return mainStats;
      const dimensions = renderer.getSize(new THREE.Vector2());
      setSize(dimensions.x, dimensions.y, renderer.getPixelRatio());
      const saved = {target: renderer.getRenderTarget(), face: renderer.getActiveCubeFace(), mip: renderer.getActiveMipmapLevel(),
        autoClear: renderer.autoClear, autoReset: renderer.info.autoReset, tone: renderer.toneMapping,
        color: renderer.getClearColor(new THREE.Color()), alpha: renderer.getClearAlpha()};
      try {
        renderer.info.autoReset = false;
        composer.render();
        return {...mainStats};
      } finally {
        renderer.setRenderTarget(saved.target, saved.face, saved.mip);
        renderer.autoClear = saved.autoClear; renderer.info.autoReset = saved.autoReset;
        renderer.toneMapping = saved.tone; renderer.setClearColor(saved.color, saved.alpha);
      }
    },
    // For tuning by eye: strength 0 is the picture without the pass, and
    // output takes GTAOPass.OUTPUT (2 depth, 3 normals, 5 the occlusion alone).
    tune({ strength, output, ...shape } = {}) {
      occlusion.updateGtaoMaterial(shape);
      if (strength !== undefined) occlusion.blendIntensity = strength;
      if (output !== undefined) occlusion.output = output;
    },
    info() { return {passes: composer.passes.map(p => p.constructor.name), enabled: !disposed, size: {...size}, samples}; },
    dispose() {
      if (disposed) return;
      disposed = true;
      composer.passes.forEach(p => p.dispose());
      // r187 GTAOPass.dispose omits these two owned shader materials.
      occlusion.gtaoMaterial.dispose(); occlusion.blendMaterial.dispose();
      clipped.forEach(m => m.dispose()); clipped.clear();
      composer.dispose();
    },
  };
}
