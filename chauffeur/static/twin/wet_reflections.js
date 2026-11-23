import * as THREE from 'three';
import { Pass, FullScreenQuad } from 'three/addons/postprocessing/Pass.js';
import { WEATHER_GLSL } from './sky/weather_surface.js';

const vertex='varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}';
// Only the post program gets these samplers. The shared weather functions are
// imported verbatim; unused ripple/drop functions disappear at shader link.
const common=`
varying vec2 vUv;
uniform sampler2D image,ssrDepth,ssrNormal,ssrBeautyDepth,wetEdge,wetCaps;
uniform vec4 wetGroundBounds;
uniform mat4 ssrProjection,ssrInverseProjection,ssrWorld;
uniform vec3 ssrCamera;
vec3 vWeatherWorld;
#define cameraPosition (ssrWorld[3].xyz)
${WEATHER_GLSL}
float ssrLinearDepth(float depth) {
  return mix(ssrCamera.x*ssrCamera.y/((ssrCamera.x-ssrCamera.y)*depth+ssrCamera.y),
    ssrCamera.x+(ssrCamera.y-ssrCamera.x)*depth,1.0-ssrCamera.z);
}
vec3 ssrPosition(vec2 uv,float depth) {
  vec4 p=ssrInverseProjection*vec4(uv*2.0-1.0,depth*2.0-1.0,1.0);
  return p.xyz/p.w;
}
float ssrDepthMatches(float groundDepth,float beautyDepth) {
  return abs(groundDepth-beautyDepth)<max(.03,groundDepth*.001)?1.0:0.0;
}
bool ssrVisible(vec2 uv,float depth) {
  // AO omits alpha-tested leaves/grass and custom water. Its ground behind
  // them must not receive a reflection over the foreground beauty pixel.
  return ssrDepthMatches(ssrLinearDepth(depth),ssrLinearDepth(texture2D(ssrBeautyDepth,uv).r))>0.0;
}
float ssrMask(float up,float y,float covered,float ground,float wet,float puddles,float snow,float edge) {
  if(up<=.9||y<covered||ground<=-9999.0||abs(y-ground)>=.15)return 0.0;
  float film=weatherFilm(wet);
  return max(film*.45,weatherPuddle(up,puddles,edge)*film)*(1.0-weatherSnow(up,snow,edge));
}
float ssrPuddle=0.0;
float ssrHardWeight(float y,float sdf,float top,float capSDF,float capTop) {
  float hard=smoothstep(-.015,.015,sdf);
  if(top<=-9999.0||abs(y-top)>=.15)hard=0.0;
  return capSDF>0.0&&abs(y-capTop)<.05?1.0:hard;
}
float ssrOpen(float y,float sdf,float ceiling) {
  return sdf>0.0||y>=ceiling?1.0:clamp(sdf/.6,0.0,1.0);
}
float ssrReceiver(vec3 position,vec3 normal) {
  ssrPuddle=0.0;
  vec3 world=(ssrWorld*vec4(position,1.0)).xyz;
  float up=(mat3(ssrWorld)*normal).y;
  if(up<=.9)return 0.0;
  vec2 uv=(world.xz-wetGroundBounds.xy)/max(wetGroundBounds.zw-wetGroundBounds.xy,vec2(.0001));
  if(any(lessThan(uv,vec2(0.0)))||any(greaterThanEqual(uv,vec2(1.0))))return 0.0;
  // Bilinear signed-distance + dilated-height field: r=cover SDF, g=hardscape SDF,
  // b=dilated cover height, a=dilated hardscape height. Smooth along curves and drip lines.
  vec4 field=texture2D(wetEdge,uv);
  vec2 cap=texture2D(wetCaps,uv).rg;
  float hard=ssrHardWeight(world.y,field.g,field.a,cap.r,cap.g);
  if(hard<=0.0)return 0.0;
  float open=ssrOpen(world.y,field.r,field.b);
  if(open<=0.0)return 0.0;
  // Reject lawn/roof/cover before paying for the procedural puddle edge.
  float edge=weatherSurface.y>0.0||weatherSurface.z>0.0?weatherEdge(world.xz):.5;
  ssrPuddle=weatherPuddle(up,weatherSurface.z,edge)*open;
  // ssrHardWeight already validated this height against either independent
  // receiver. Do not test a cap against the neighbouring deck's field.a again.
  return ssrMask(up,world.y,-1e4,world.y,weatherSurface.x*open,weatherSurface.z*open,weatherSurface.y*open,edge)*hard;
}
// Rain rings bend the reflection exactly as they bend the lit surface's normal.
vec3 ssrRippled(vec3 position,vec3 normal) {
  // weatherWorldDx/Dy were taken at the top of main, before any branch.
  vec3 world=(ssrWorld*vec4(position,1.0)).xyz;
  vWeatherWorld=world;
  vec2 slope=weatherRipple(world.xz);
  return normalize(normal+transpose(mat3(ssrWorld))*vec3(slope.x,0.0,slope.y));
}
vec3 ssrSafe(vec3 c){return vec3(c.r>=0.0?min(c.r,4096.0):0.0,c.g>=0.0?min(c.g,4096.0):0.0,c.b>=0.0?min(c.b,4096.0):0.0);}
`;

export const SSR_MARCH_GLSL=`
vec2 ssrProject(vec3 position) {
  vec4 p=ssrProjection*vec4(position,1.0);
  return p.xy/p.w*.5+.5;
}
float ssrGap(vec3 position,vec2 uv) {
  return -position.z-ssrLinearDepth(texture2D(ssrDepth,uv).r);
}
// Debug-only miss payloads; the shipping preprocessor removes all reason state.
// -1: a crossing was rejected and no later hit survived (even on screen exit),
// -2: toward camera, -3: screen exit without rejection, -4: march exhausted.
vec3 ssrMiss(float reason) {
#ifdef SSR_DEBUG_REASONS
  return vec3(0.0,0.0,reason);
#else
  return vec3(0.0);
#endif
}
// Metres in view space, 24 growing steps out to 64 m. Keep the original four
// bisections for accepted hits; only a rejected candidate pays for four more.
vec3 ssrMarch(vec3 origin,vec3 direction) {
  if(direction.z>=0.0)return ssrMiss(-2.0);
  // Unit reflection direction: fade over the last ~11.5 degrees before it
  // turns toward the camera. At the cutoff confidence already tends to zero.
  float facing=smoothstep(0.0,.2,-direction.z);
  float previous=0.0,travel=.2,stride=.2,previousGap=-1.0;
#ifdef SSR_DEBUG_REASONS
  bool rejected=false;
#endif
  for(int i=0;i<24;i++){
    vec3 position=origin+direction*travel;
    vec2 uv=ssrProject(position);
    if(any(lessThanEqual(uv,vec2(0.0)))||any(greaterThanEqual(uv,vec2(1.0)))){
#ifdef SSR_DEBUG_REASONS
      return ssrMiss(rejected?-1.0:-3.0);
#else
      return vec3(0.0);
#endif
    }
    float gap=ssrGap(position,uv);
    if(travel>.3&&gap>=0.0&&previousGap<0.0){
      float lo=previous,hi=travel;
      for(int j=0;j<4;j++){
        float middle=(lo+hi)*.5;
        vec3 point=origin+direction*middle;
        vec2 sampleUV=ssrProject(point);
        if(ssrGap(point,sampleUV)>=0.0)hi=middle;else lo=middle;
      }
      position=origin+direction*hi;uv=ssrProject(position);
      float depth=ssrLinearDepth(texture2D(ssrDepth,uv).r);
      float thickness=min(.4,.18+depth*.002);
      float delta=-position.z-depth;
      if(!(delta>=0.0&&delta<thickness&&depth<ssrCamera.y-.01)){
        // At the longest stride four bisections can still overshoot by ~.8 m.
        // Eight bound that error below .06 m, inside the thinnest hit shell.
        for(int j=0;j<4;j++){
          float middle=(lo+hi)*.5;
          vec3 point=origin+direction*middle;
          vec2 sampleUV=ssrProject(point);
          if(ssrGap(point,sampleUV)>=0.0)hi=middle;else lo=middle;
        }
        position=origin+direction*hi;uv=ssrProject(position);
        depth=ssrLinearDepth(texture2D(ssrDepth,uv).r);
        thickness=min(.4,.18+depth*.002);
        delta=-position.z-depth;
      }
      if(delta>=0.0&&delta<thickness&&depth<ssrCamera.y-.01){
        float edge=min(min(uv.x,1.0-uv.x),min(uv.y,1.0-uv.y));
        float confidence=smoothstep(0.0,.06,edge)*(1.0-smoothstep(32.0,64.0,hi))*facing;
        return vec3(uv,confidence);
      }
#ifdef SSR_DEBUG_REASONS
      rejected=true;
#endif
      // A depth discontinuity (thin rail/post/leaf) is not the end of the ray.
      // Keep the original coarse schedule so rejection cannot shorten reach.
    }
    previous=travel;previousGap=gap;stride*=1.2;travel=min(64.0,travel+stride);
    if(previous>=64.0)break;
  }
#ifdef SSR_DEBUG_REASONS
  return ssrMiss(rejected?-1.0:-4.0);
#else
  return vec3(0.0);
#endif
}
`;

export class WetReflectionPass extends Pass {
  constructor(camera,occlusion) {
    super();this.camera=camera;this.enabled=false;this.ready=true;this.error=null;
    this.target=new THREE.WebGLRenderTarget(1,1,{type:THREE.HalfFloatType,depthBuffer:false,
      minFilter:THREE.NearestFilter,magFilter:THREE.NearestFilter});
    this.uniforms={image:{value:null},ssrDepth:{value:occlusion.depthTexture},ssrNormal:{value:occlusion.normalTexture},ssrBeautyDepth:{value:null},
      weatherSurface:{value:new THREE.Vector4()},wetGround:{value:null},wetEdge:{value:null},wetCaps:{value:null},wetGroundBounds:{value:new THREE.Vector4(0,0,1,1)},
      ssrProjection:{value:new THREE.Matrix4()},ssrInverseProjection:{value:new THREE.Matrix4()},ssrWorld:{value:new THREE.Matrix4()},
      ssrCamera:{value:new THREE.Vector3()},ssrHits:{value:this.target.texture}};
    const material=(name,fragmentShader)=>new THREE.ShaderMaterial({name,uniforms:this.uniforms,vertexShader:vertex,
      fragmentShader,toneMapped:false,depthTest:false,depthWrite:false,blending:THREE.NoBlending});
    const gather=material('wet-reflections-march',common+SSR_MARCH_GLSL+`
void main(){
  gl_FragColor=vec4(0.0);
  float depth=texture2D(ssrDepth,vUv).r;
  vec3 position=ssrPosition(vUv,min(depth,.999999));
  vec3 worldHere=(ssrWorld*vec4(position,1.0)).xyz;
  weatherWorldDx=dFdx(worldHere);weatherWorldDy=dFdy(worldHere);
  if(depth>=1.0||!ssrVisible(vUv,depth))return;
  vec3 normal=normalize(texture2D(ssrNormal,vUv).rgb*2.0-1.0);
  if(ssrReceiver(position,normal)<=0.0)return;
  vec3 incident=mix(vec3(0.0,0.0,-1.0),normalize(position),ssrCamera.z);
  vec3 direction=reflect(incident,ssrRippled(position,normal));
  vec3 hit=ssrMarch(position+normal*.05,direction);
  gl_FragColor=vec4(hit,-position.z);
}`);
    const composite=material('wet-reflections-composite',common+`
uniform sampler2D ssrHits;
void main(){
  vec4 base=texture2D(image,vUv);gl_FragColor=base;
  vec4 hit=texture2D(ssrHits,vUv);if(hit.b<=0.0)return;
  float depth=texture2D(ssrDepth,vUv).r;if(depth>=1.0||!ssrVisible(vUv,depth))return;
  vec3 position=ssrPosition(vUv,depth),normal=normalize(texture2D(ssrNormal,vUv).rgb*2.0-1.0);
  // Nearest half-resolution hit, validated against the full-resolution face.
  // This prevents a puddle lookup bleeding onto the wall/lawn at its edge.
  if(abs(-position.z-hit.a)>max(.15,-position.z*.01))return;
  float strength=ssrReceiver(position,normal);if(strength<=0.0)return;
  vec3 eye=mix(vec3(0.0,0.0,1.0),normalize(-position),ssrCamera.z);
  float fresnel=.02+.98*pow(1.0-clamp(dot(normal,eye),0.0,1.0),5.0);
  vec2 texel=1.0/vec2(textureSize(image,0));
  float sharp=clamp(ssrPuddle,0.0,1.0);
  vec2 radius=max(texel*2.0,vec2(length(hit.rg-vUv)*mix(.08,.012,sharp)));
  vec3 reflected=ssrSafe(texture2D(image,hit.rg).rgb)*.28;
  reflected+=ssrSafe(texture2D(image,hit.rg+vec2(radius.x,0.0)).rgb)*.18;
  reflected+=ssrSafe(texture2D(image,hit.rg-vec2(radius.x,0.0)).rgb)*.18;
  reflected+=ssrSafe(texture2D(image,hit.rg+vec2(0.0,radius.y*1.6)).rgb)*.18;
  reflected+=ssrSafe(texture2D(image,hit.rg-vec2(0.0,radius.y*1.6)).rgb)*.18;
  gl_FragColor=vec4(mix(ssrSafe(base.rgb),reflected,strength*fresnel*hit.b),base.a);
}`);
    this.materials=[gather,composite];this.gather=new FullScreenQuad(gather);this.composite=new FullScreenQuad(composite);
  }
  get debugReasons(){return this.materials[0].defines.SSR_DEBUG_REASONS!==undefined;}
  set debugReasons(value){
    const gather=this.materials[0],enabled=!!value;
    if(enabled===this.debugReasons)return;
    if(enabled)gather.defines.SSR_DEBUG_REASONS=1;else delete gather.defines.SSR_DEBUG_REASONS;
    gather.needsUpdate=true;
  }
  bind({weatherSurface,precipCover,precipCoverBounds,precipEdge,precipCaps}) {
    const edge=precipEdge||{value:null};
    for(const material of this.materials){
      material.uniforms.weatherSurface=weatherSurface;
      material.uniforms.wetGround=precipCover;
      material.uniforms.wetEdge=edge;
      material.uniforms.wetCaps=precipCaps||{value:null};
      material.uniforms.wetGroundBounds=precipCoverBounds;
    }
    this.update();
  }
  update(){
    const u=this.uniforms.weatherSurface.value;
    this.enabled=!!this.uniforms.wetEdge.value&&(u.x>0||u.z>0);
  }
  setSize(w,h){this.target.setSize(Math.max(1,Math.ceil(w*.5)),Math.max(1,Math.ceil(h*.5)));}
  warm(renderer,destination){
    if(!renderer.compileAsync)return;
    this.ready=false;const saved=[renderer.getRenderTarget(),renderer.getActiveCubeFace(),renderer.getActiveMipmapLevel()];
    try{
      const eye=new THREE.OrthographicCamera(-1,1,1,-1,0,1);
      renderer.setRenderTarget(this.target);const gather=renderer.compileAsync(this.gather._mesh,eye);
      renderer.setRenderTarget(destination);const composite=renderer.compileAsync(this.composite._mesh,eye);
      Promise.all([gather,composite]).then(()=>{this.ready=true;},error=>{this.error=error;});
    }finally{renderer.setRenderTarget(...saved);}
  }
  render(renderer,writeBuffer,readBuffer){
    this.needsSwap=this.ready&&this.enabled;if(!this.needsSwap)return;
    const camera=this.camera,u=this.uniforms;camera.updateMatrixWorld();
    u.ssrProjection.value.copy(camera.projectionMatrix);u.ssrInverseProjection.value.copy(camera.projectionMatrixInverse);
    u.ssrWorld.value.copy(camera.matrixWorld);u.ssrCamera.value.set(camera.near,camera.far,camera.isPerspectiveCamera?1:0);
    u.image.value=readBuffer.texture;u.ssrBeautyDepth.value=readBuffer.depthTexture;
    renderer.setRenderTarget(this.target);this.gather.render(renderer);
    renderer.setRenderTarget(this.renderToScreen?null:writeBuffer);this.composite.render(renderer);
  }
  dispose(){this.target.dispose();this.materials.forEach(m=>m.dispose());this.gather.dispose();this.composite.dispose();}
}
