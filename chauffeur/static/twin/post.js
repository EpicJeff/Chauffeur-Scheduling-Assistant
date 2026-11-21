import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { Pass, FullScreenQuad } from 'three/addons/postprocessing/Pass.js';
import { shadowTransmittance } from './sky/cloud_shadow.js';
import { createNoiseVolumeSampler } from './sky/cloud_noise.js';
import { WetReflectionPass } from './wet_reflections.js';
import { environmentFrame, frameObjects as environmentObjects } from './sky/stage_haze.js';

const finiteClamp=(v,a=0,b=1)=>Number.isFinite(v)?Math.max(a,Math.min(b,v)):a;
const smooth=(a,b,v)=>{const x=finiteClamp((v-a)/Math.max(b-a,1e-6));return x*x*(3-2*x);};
// Reject the back half-space before projecting. In particular, w=0 at the
// camera horizon must never become an infinite blur step or reach bloom.
export function lightShaftState(camera,{sunDir=[0,1,0],sunAltDeg=90,transmittance=1,enabled=true}={}) {
  const off={uv:[.5,.5],strength:0};
  if(!enabled||!Number.isFinite(sunAltDeg)||sunAltDeg<=-2||sunAltDeg>=12||!sunDir?.every(Number.isFinite))return off;
  const direction=new THREE.Vector3().fromArray(sunDir);
  if(direction.lengthSq()<1e-12)return off;
  camera.updateMatrixWorld();direction.normalize().transformDirection(camera.matrixWorldInverse);
  if(direction.z>=-1e-5)return off;
  const clip=new THREE.Vector4(...direction.multiplyScalar(100).toArray(),1).applyMatrix4(camera.projectionMatrix);
  if(!clip.toArray().every(Number.isFinite)||clip.w<=1e-5)return off;
  const uv=[clip.x/Math.max(clip.w,1e-5)*.5+.5,clip.y/Math.max(clip.w,1e-5)*.5+.5];
  const edge=Math.max(0,-uv[0],uv[0]-1,-uv[1],uv[1]-1);
  const strength=.18*smooth(-2,1,sunAltDeg)*(1-smooth(7,12,sunAltDeg))*(1-smooth(0,.18,edge))*finiteClamp(transmittance);
  return {uv:uv.map(v=>finiteClamp(v,-2,3)),strength:finiteClamp(strength)};
}

const shaftVertex='varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}';
const shaftSafe='float held(float v){return v>=0.0?min(v,4096.0):0.0;} vec3 safeRGB(vec3 v){return vec3(held(v.r),held(v.g),held(v.b));}';
class LightShaftPass extends Pass {
  constructor(tier,depth) {
    super();this.samples={medium:16,high:24,max:32}[tier]||24;this.scale=tier==='medium'?.25:.5;this.depth=depth;
    this.strength=0;this.ready=true;this.error=null;
    this.target=new THREE.WebGLRenderTarget(1,1,{type:THREE.HalfFloatType,depthBuffer:false});
    this.uniforms={image:{value:null},depth:{value:depth.texture},sunUV:{value:new THREE.Vector2(.5,.5)},strength:{value:0},rays:{value:this.target.texture}};
    const gather=new THREE.ShaderMaterial({name:'season-shaft-radial',uniforms:this.uniforms,vertexShader:shaftVertex,toneMapped:false,depthTest:false,depthWrite:false,
      fragmentShader:`uniform sampler2D image,depth;uniform vec2 sunUV;varying vec2 vUv;${shaftSafe}
      void main(){
        vec3 sum=vec3(0.0);float weight=1.0,total=0.0;
        for(int i=0;i<${this.samples};i++){
          float t=(float(i)+.5)/${this.samples}.0;vec2 p=mix(vUv,sunUV,t);
          if(p.x>=0.0&&p.y>=0.0&&p.x<=1.0&&p.y<=1.0){
            float sky=texture2D(depth,p).r>=1.0-1e-7?1.0:0.0;
            float source=1.0-smoothstep(.0,.32,distance(p,sunUV));
            sum+=min(safeRGB(texture2D(image,p).rgb),vec3(2.0))*sky*source*weight;
          }
          total+=weight;weight*=.96;
        }
        gl_FragColor=vec4(safeRGB(sum/max(total,.0001)),1.0);
      }`});
    const composite=new THREE.ShaderMaterial({name:'season-shaft-composite',uniforms:this.uniforms,vertexShader:shaftVertex,toneMapped:false,depthTest:false,depthWrite:false,
      fragmentShader:`uniform sampler2D image,rays,depth;uniform float strength;varying vec2 vUv;${shaftSafe}
      void main(){
        vec3 base=safeRGB(texture2D(image,vUv).rgb);
        // The source AND receiver are sky. Never paint a beam onto a room,
        // device or lamp, including cut-away views of the house.
        float sky=texture2D(depth,vUv).r>=1.0-1e-7?1.0:0.0;
        gl_FragColor=vec4(safeRGB(base+safeRGB(texture2D(rays,vUv).rgb)*strength*sky),1.0);
      }`});
    this.materials=[gather,composite];this.gather=new FullScreenQuad(gather);this.composite=new FullScreenQuad(composite);
  }
  setSize(w,h){this.depth.setSize(w,h);this.target.setSize(Math.max(1,Math.ceil(w*this.scale)),Math.max(1,Math.ceil(h*this.scale)));}
  warm(renderer,destination){
    if(!renderer.compileAsync)return;
    this.ready=false;const saved=[renderer.getRenderTarget(),renderer.getActiveCubeFace(),renderer.getActiveMipmapLevel()];
    try{
      renderer.setRenderTarget(destination);
      Promise.all([this.gather,this.composite].map(q=>renderer.compileAsync(q._mesh,new THREE.OrthographicCamera(-1,1,1,-1,0,1))))
        .then(()=>{this.ready=true;},error=>{this.error=error;});
    }finally{renderer.setRenderTarget(...saved);}
  }
  render(renderer,writeBuffer,readBuffer){
    this.needsSwap=this.ready&&this.strength>0;if(!this.needsSwap)return;
    this.uniforms.image.value=readBuffer.texture;this.uniforms.strength.value=this.strength;
    renderer.setRenderTarget(this.target);this.gather.render(renderer);
    renderer.setRenderTarget(this.renderToScreen?null:writeBuffer);this.composite.render(renderer);
  }
  dispose(){this.target.dispose();this.materials.forEach(m=>m.dispose());this.gather.dispose();this.composite.dispose();}
}

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
// Glow around what is brighter than the picture can show. The threshold is in
// displayed brightness (after exposure), where 1 is roughly paper white, so
// the same lamp glows the same at night as at dusk.
const BLOOM_STRENGTH = .25;
const BLOOM_RADIUS = .45;
const BLOOM_THRESHOLD = 1.6;
// Only what a pixel has over the threshold glows. The stock filter passes the
// whole pixel once it is over, so a wall or a floor a lamp lights brightly fed
// the glow at full strength over its whole area: lamps looked like they were
// melting the house.
const HIGH_PASS = 'gl_FragColor = mix( outputColor, texel, alpha );';
const EXCESS = 'gl_FragColor = mix( outputColor, texel * max( 0.0, 1.0 - luminosityThreshold / max( v, 1e-4 ) ), alpha );';
// Lit bulbs, strips and lamp shades are drawn at no more than paper white, so
// none would pass the threshold. Where this chain runs they are drawn this
// many times brighter; the output pass rolls that off, so hue survives. The
// plain path has no roll-off for them, so it keeps them as they were.
export const EMITTER_GAIN = 3;
// A pixel that is not a number poisons every pixel a blur mixes it into: one
// such pixel anywhere blacked out the whole picture through the glow. A pixel
// past what the half-float target holds whites it out the same way. The glow
// reads nothing brighter than GLOW_CEILING times its own threshold and the
// output nothing brighter than OUTPUT_CEILING; either turns a value that is
// not a number into black. The glow ceiling sits at a lit lamp at night
// (EMITTER_GAIN at the night exposure, over the threshold), so a sun glint on
// water glows like one lamp and a field of glints cannot wash the picture
// white.
const GLOW_CEILING = 2.2;
const OUTPUT_CEILING = 4096;
const SAMPLE = 'texture2D( tDiffuse, vUv );';
function guardSample(material, name, ceiling) {
  const source = material.fragmentShader;
  if (!source.includes(SAMPLE) || !source.includes('void main() {')) throw new Error('Post shader missing anchor');
  // The comparison is false for a value that is not a number, so it lands on 0.
  material.fragmentShader = source
    .replace('void main() {', `float held( float v ) { return v >= 0.0 ? min( v, ${ceiling} ) : 0.0; }\nvoid main() {`)
    .replace(SAMPLE, `${SAMPLE}\n${name}.rgb = vec3( held( ${name}.r ), held( ${name}.g ), held( ${name}.b ) );`);
  material.needsUpdate = true;
}

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
// Texture skies already hold linear radiance: leave them for OutputPass, just
// as the canvas path tone maps them once. Fog stays scene-linear too.
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

export function createPost(renderer, scene, camera, { samples = 0, clouds = null, tier = 'high' } = {}) {
  const hasDepth=!!clouds||tier!=='low';
  const target = new THREE.WebGLRenderTarget(1, 1, {type: THREE.HalfFloatType, samples});
  if (hasDepth) target.depthTexture = new THREE.DepthTexture(1,1,THREE.UnsignedIntType);
  const composer = new EffectComposer(renderer, target);
  const beauty = new RenderPass(scene, camera);
  const occlusion = new GTAOPass(scene, camera, 1, 1, undefined, {
    radius: OCCLUSION_RADIUS, distanceFallOff: OCCLUSION_DISTANCE_FALLOFF, screenSpaceRadius: false,
    scale: OCCLUSION_CONTRAST, thickness: OCCLUSION_THICKNESS,
  }, {radius: DENOISE_RADIUS});
  occlusion.blendIntensity = OCCLUSION_STRENGTH;
  const output = new OutputPass();
  guardSample(output.material, 'gl_FragColor', OUTPUT_CEILING.toFixed(1));
  composer.addPass(beauty);
  composer.addPass(occlusion);
  const wetReflections=['high','max'].includes(tier)?new WetReflectionPass(camera,occlusion):null;
  if(wetReflections){composer.addPass(wetReflections);wetReflections.warm(renderer,target);}
  // Capture BEAUTY depth, including alpha-tested vegetation and custom effects.
  // AO's intentionally restricted normal prepass cannot mask a cloud composite.
  // A separate colour texture also avoids sampling an attached framebuffer's
  // depth texture when the composer swaps back to the beauty target.
  const depthCopy = hasDepth ? new THREE.WebGLRenderTarget(1,1,{format:THREE.RedFormat,type:THREE.FloatType,
    depthBuffer:false,minFilter:THREE.NearestFilter,magFilter:THREE.NearestFilter}) : null;
  const depthMaterial = hasDepth ? new THREE.ShaderMaterial({uniforms:{sourceDepth:{value:null}},depthTest:false,depthWrite:false,toneMapped:false,
    vertexShader:'varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}',
    fragmentShader:'uniform sampler2D sourceDepth;varying vec2 vUv;void main(){gl_FragColor=vec4(texture2D(sourceDepth,vUv).r);}'}) : null;
  const depthQuad = hasDepth ? new FullScreenQuad(depthMaterial) : null;
  const shafts=tier==='low'?null:new LightShaftPass(tier,depthCopy);
  shafts?.warm(renderer,target);
  let sunInput={},cloudSample=null,cloudSampleTime=-Infinity,cloudSampleKey='',sunTransmission=1;
  function setSun(input={}){
    sunInput=input;const state=lightShaftState(beauty.camera,input);
    if(shafts){shafts.uniforms.sunUV.value.fromArray(state.uv);shafts.strength=state.strength;}
  }
  function updateShafts(){
    if(!shafts)return;
    const state=lightShaftState(beauty.camera,sunInput),u=clouds?.uniforms,now=performance.now()/1000;
    if(state.strength>0&&u){
      const key=[u.cloudCoverage.value,u.cloudType.value,...(sunInput.sunDir||[]),u.cloudFade.value].join(',');
      if(now-cloudSampleTime>=.5||cloudSampleKey!==key){
        cloudSampleTime=now;cloudSampleKey=key;sunTransmission=1;
        if(u.cloudCoverage.value>0&&u.cloudType.value>0&&u.cloudFade.value>0){
          cloudSample ??= clouds.noise?.base.image.data?clouds.noise:{base:createNoiseVolumeSampler(clouds.noise?.base.image.width||128),detail:createNoiseVolumeSampler(clouds.noise?.detail.image.width||32,{detail:true})};
          const direction=[sunInput.sunDir[0],Math.max(0,sunInput.sunDir[1]),sunInput.sunDir[2]];
          const p=beauty.camera.getWorldPosition(new THREE.Vector3());
          const t=shadowTransmittance(p.toArray(),direction,{...cloudSample,coverage:u.cloudCoverage.value,type:u.cloudType.value,offset:u.cloudOffset.value.toArray()});
          sunTransmission=1+(t-1)*finiteClamp(u.cloudFade.value);
        }
      }
    }else if(!u)sunTransmission=1;
    shafts.uniforms.sunUV.value.fromArray(state.uv);
    shafts.strength=depthReady?state.strength*finiteClamp(sunTransmission):0;
  }
  let depthReady=!renderer.compileAsync,depthError=null;
  if (depthQuad && renderer.compileAsync) {
    const saved=[renderer.getRenderTarget(),renderer.getActiveCubeFace(),renderer.getActiveMipmapLevel()];
    try {
      renderer.setRenderTarget(target);
      Promise.resolve(renderer.compileAsync(depthQuad._mesh,new THREE.OrthographicCamera(-1,1,1,-1,0,1)))
        .then(()=>{depthReady=true;},error=>{depthError=error;});
    } finally {renderer.setRenderTarget(...saved);}
  }
  const cloudsReady=()=>clouds?.active&&depthReady;
  let deferred = false;
  const isCelestial = o => o.name?.startsWith('sky-');
  const transparent = o => !isCelestial(o) && [].concat(o.material || []).some(m=>m.transparent && !(m.userData.viewingOpaque && m.depthWrite));
  let objectFrame, objects;
  function frameObjects() {
    const frame = environmentFrame(scene);
    if (objects && frame !== undefined && objectFrame === frame) return objects;
    objectFrame = frame;
    objects = {opaque:[], transparent:[], excluded:[], clipped:[]};
    // Classify once before any pass changes masks, visibility or materials.
    // traverse (not traverseVisible) preserves children of hidden parents.
    for (const o of environmentObjects(scene)) {
      if (o.material) objects[transparent(o) ? 'transparent' : 'opaque'].push(o);
      if (!o.visible) continue;
      if (excluded(o)) { objects.excluded.push(o); continue; }
      if (o.isMesh && [].concat(o.material).some(m=>m?.clippingPlanes?.length)) objects.clipped.push(o);
    }
    return objects;
  }
  function withGeometry(list, draw) {
    const hidden=[];
    try {
      // Layers skip only this draw, preserving the children of a skipped mesh.
      for (const o of list) { hidden.push([o,o.layers.mask]); o.layers.mask=0; }
      return draw();
    } finally {for(const [o,mask] of hidden)o.layers.mask=mask;}
  }
  class CloudCompositePass extends Pass {
    render(renderer, writeBuffer, readBuffer) {
      this.needsSwap = !!cloudsReady();
      if (!this.needsSwap) return;
      clouds.render(scene, beauty.camera, depthCopy.texture);
      // This writes the saved depth as well as colour. Transparent geometry
      // then depth-tests against precisely the opaque beauty that was shown.
      clouds.composite(readBuffer.texture, this.renderToScreen ? null : writeBuffer, depthCopy.texture);
      if (deferred) {
        const background=scene.background,auto=renderer.autoClear,before={...renderer.info.render};
        try {
          scene.background=null;renderer.autoClear=false;
          renderer.setRenderTarget(this.renderToScreen ? null : writeBuffer);
          withGeometry(objects.opaque,()=>renderer.render(scene,beauty.camera));
          mainStats.calls+=renderer.info.render.calls-before.calls;mainStats.triangles+=renderer.info.render.triangles-before.triangles;
        } finally {scene.background=background;renderer.autoClear=auto;}
      }
    }
    setSize(w,h) {depthCopy.setSize(w,h);}
    dispose() {}
  }
  if (clouds) composer.addPass(new CloudCompositePass());
  if (shafts) composer.addPass(shafts);
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), BLOOM_STRENGTH, BLOOM_RADIUS, BLOOM_THRESHOLD);
  guardSample(bloom.materialHighPassFilter, 'texel', `luminosityThreshold * ${GLOW_CEILING.toFixed(1)}`);
  if (!bloom.materialHighPassFilter.fragmentShader.includes(HIGH_PASS)) throw new Error('Post shader missing anchor');
  bloom.materialHighPassFilter.fragmentShader = bloom.materialHighPassFilter.fragmentShader.replace(HIGH_PASS, EXCESS);
  let bloomThreshold = BLOOM_THRESHOLD;
  const drawBloom = bloom.render.bind(bloom);
  bloom.render = (...args) => {
    bloom.threshold = bloomThreshold / Math.max(renderer.toneMappingExposure, 1e-3);
    drawBloom(...args);
  };
  composer.addPass(bloom);
  composer.addPass(output);
  let disposed = false, size = {}, mainStats = {calls: 0, triangles: 0};
  const backgroundColor = new THREE.Color();
  const drawBeauty = beauty.render.bind(beauty);
  beauty.render = (...args) => {
    const background = scene.background, before = {...renderer.info.render};
    try {
      if (background?.isColor) scene.background = linearBackground(background, renderer, backgroundColor);
      // r187 leaves render targets scene-linear even with ACES set on renderer.
      deferred=!!cloudsReady();
      if (deferred) withGeometry(objects.transparent,()=>drawBeauty(...args));
      else drawBeauty(...args);
      mainStats = {calls: renderer.info.render.calls - before.calls, triangles: renderer.info.render.triangles - before.triangles};
      if (depthReady&&(deferred||shafts?.strength>0)) {
        // RenderPass draws to readBuffer (args[2]), not the composer's target.
        const source=args[2],saved=[renderer.getRenderTarget(),renderer.getActiveCubeFace(),renderer.getActiveMipmapLevel()],auto=renderer.autoClear;
        try {
          depthMaterial.uniforms.sourceDepth.value=source.depthTexture;
          renderer.setRenderTarget(depthCopy);renderer.autoClear=false;depthQuad.render(renderer);
        } finally {renderer.setRenderTarget(...saved);renderer.autoClear=auto;}
      }
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
      for (const o of objects.excluded) if (o.visible) { hidden.push(o); o.visible = false; }
      for (const o of objects.clipped) {
        if (!o.visible) continue;
        const m = o.material;
        swapped.push([o, m]);
        const normal = x => x.clippingPlanes?.length ? clippedNormal(x, used) : occlusion.normalMaterial;
        o.material = Array.isArray(m) ? m.map(normal) : normal(m);
      }
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
    if(wetReflections)wetReflections.camera=next;
    const perspective = next.isPerspectiveCamera ? 1 : 0;
    for (const m of [occlusion.gtaoMaterial, occlusion.depthRenderMaterial]) {
      if (m.defines.PERSPECTIVE_CAMERA !== perspective) {
        m.defines.PERSPECTIVE_CAMERA = perspective; m.needsUpdate = true;
      }
    }
  }
  return {
    setCamera, setSize, setSun, shafts, wetReflections,
    setWetGround(bindings){wetReflections?.bind(bindings);},
    // Where the scene's materials draw: their programs are keyed on this target.
    get target() { return disposed ? null : target; },
    render() {
      if (disposed) return mainStats;
      frameObjects();
      const dimensions = renderer.getSize(new THREE.Vector2());
      setSize(dimensions.x, dimensions.y, renderer.getPixelRatio());
      const saved = {target: renderer.getRenderTarget(), face: renderer.getActiveCubeFace(), mip: renderer.getActiveMipmapLevel(),
        autoClear: renderer.autoClear, autoReset: renderer.info.autoReset, tone: renderer.toneMapping,
        color: renderer.getClearColor(new THREE.Color()), alpha: renderer.getClearAlpha()};
      try {
        renderer.info.autoReset = false;
        updateShafts();
        wetReflections?.update();
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
    // bloom takes {strength, radius, threshold}.
    tune({ strength, output, bloom: glow, ...shape } = {}) {
      if (glow?.strength !== undefined) bloom.strength = glow.strength;
      if (glow?.radius !== undefined) bloom.radius = glow.radius;
      if (glow?.threshold !== undefined) bloomThreshold = glow.threshold;
      occlusion.updateGtaoMaterial(shape);
      if (strength !== undefined) occlusion.blendIntensity = strength;
      if (output !== undefined) occlusion.output = output;
    },
    info() { return {passes: composer.passes.map(p => p.constructor.name), enabled: !disposed, size: {...size}, samples, cloudError:depthError,
      shafts:shafts?{samples:shafts.samples,scale:shafts.scale,strength:shafts.strength,error:shafts.error}:null,
      wetReflections:wetReflections?{enabled:wetReflections.enabled,ready:wetReflections.ready,error:wetReflections.error}:null}; },
    dispose() {
      if (disposed) return;
      disposed = true;
      composer.passes.forEach(p => p.dispose());
      depthCopy?.dispose();depthMaterial?.dispose();depthQuad?.dispose();cloudSample=null;
      // r187 GTAOPass.dispose omits these two owned shader materials.
      occlusion.gtaoMaterial.dispose(); occlusion.blendMaterial.dispose();
      // r187 UnrealBloomPass.dispose omits its high-pass material.
      bloom.materialHighPassFilter.dispose();
      clipped.forEach(m => m.dispose()); clipped.clear();
      composer.dispose();
    },
  };
}
