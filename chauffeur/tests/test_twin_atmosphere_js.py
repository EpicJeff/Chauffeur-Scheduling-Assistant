"""Atmosphere quadrature and the real r187 cube/PMREM lifecycle, without a browser."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const THREE = await import('three');
registerHooks({load(url,ctx,next){
  if(url.endsWith('three.module.js?sky-keys'))return {format:'module',shortCircuit:true,source:readFileSync(new URL(url),'utf8')+'\nexport {WebGLPrograms};'};
  return next(url,ctx);
}});
const {WebGLPrograms}=await import(file('static/vendor/three-r187/three.module.js')+'?sky-keys');
const {sampleRadiance, createSky} = await import(file('static/twin/sky/atmosphere.js'));
const direction = (alt, az=0) => [Math.cos(alt*Math.PI/180)*Math.sin(az),Math.sin(alt*Math.PI/180),Math.cos(alt*Math.PI/180)*Math.cos(az)];
const sample = (alt, sunAlt, overcast=0) => sampleRadiance(direction(alt),{sunDir:direction(sunAlt),overcast});
const inputMatrix=new THREE.Matrix3().set(.59719,.35458,.04823,.076,.90834,.01566,.0284,.13383,.83777);
const outputMatrix=new THREE.Matrix3().set(1.60475,-.53108,-.07367,-.10208,1.10813,-.00605,-.00327,-.07276,1.07602);
const fit=x=>(x*(x+.0245786)-.000090537)/(x*(.983729*x+.432951)+.238081);
const aces=(rgb,exposure=1)=>{const v=new THREE.Vector3(...rgb).multiplyScalar(exposure/.6).applyMatrix3(inputMatrix);
  return v.set(fit(v.x),fit(v.y),fit(v.z)).applyMatrix3(outputMatrix).toArray().map(n=>Math.max(0,Math.min(1,n)));};
const luminance=rgb=>rgb.reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
await test('radiance is finite nonnegative at the sun, horizon, ground and night',()=>{
  for(const sunAlt of [-30,-20,-12,-6,-2,0,2,6,40,90]) for(const alt of [-90,-20,-15,-10,-5,-2,-1,-.001,0,.001,2,20,60,90,sunAlt]) for(const az of [0,Math.PI/2,Math.PI]) for(const overcast of [0,.4,1]) {
    const rgb=sampleRadiance(direction(alt,az),{sunDir:direction(sunAlt),overcast});
    assert.ok(rgb.every(n=>Number.isFinite(n)&&n>=0&&n<4096),JSON.stringify({alt,sunAlt,az,overcast,rgb}));
  }
});
await test('Rayleigh blue zenith, red sunset and dim nonzero airglow',()=>{
  const zenith=sample(90,60),horizon=sample(0,60);
  assert.ok(zenith[2]/zenith[0]>horizon[2]/horizon[0]);
  const sunset=sample(0,2),day=sample(0,40);
  assert.ok(sunset[0]/sunset[2]>day[0]/day[2]);
  const night=sample(90,-20);
  assert.ok(night.every(n=>n>0));
  assert.ok(luminance(aces(night,1.2))<luminance(aces(zenith))*.05,'night stays dim after the existing exposure/ACES');
  for(const c of [0,.4,1]) for(const alt of [-90,0,45,90]) assert.ok(luminance(aces(sample(alt,-20,c),1.2))>0,'night floor survives ACES, including overcast');
  const oldNight=new THREE.Color().setRGB(.035,.055,.1,THREE.SRGBColorSpace).toArray();
  aces(night,1.2).forEach((v,i)=>assert.ok(Math.abs(v-oldNight[i])<1e-5,'clear night matches the old night background'));
  const oldDay=new THREE.Color().setRGB(.725,.796,.843,THREE.SRGBColorSpace).toArray();
  assert.ok(Math.abs(luminance(aces(sample(0,60)))/luminance(oldDay)-1)<.05,'day horizon holds the old day luminance within 5%');
  assert.deepEqual(sample(0,40,1),day,'clouds replace the interim atmospheric greying; clear-air hue is unchanged');
});
await test('real cube and fixed PMREM target update contents without changing keys or leaking state',()=>{
  for(const tier of ['low','medium','high','max']) {
    const renderer=new Renderer();renderer.xr={enabled:true};renderer.coordinateSystem=THREE.WebGLCoordinateSystem;
    const target=new THREE.WebGLRenderTarget(4,4);renderer.setRenderTarget(target,3,2);renderer.autoClear=false;
    const calls=[],render=renderer.render;renderer.render=function(s,c){calls.push([s,this.target,this.face,this.mip]);return render.call(this,s,c);};
    const sky=createSky(renderer,{tier}),cube=sky.cube,env=sky.environment;
    renderer.state={buffers:{depth:{getReversed:()=>false}}};
    const cache=WebGLPrograms(renderer,{get:t=>t},{has:()=>false},{precision:'highp',getMaxPrecision:()=> 'highp'},{},{numPlanes:0,numIntersection:0});
    const lights=Object.fromEntries(['sun','directional','point','spot','spotLightMap','rectArea','hemi','sunShadowMap','directionalShadowMap','pointShadowMap','spotShadowMap'].map(k=>[k,[]]));
    lights.numSpotLightShadowsWithMaps=0;lights.numLightProbes=0;
    const litScene=new THREE.Scene();litScene.environment=env;
    const litMesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial());
    const parameters=()=>cache.getParameters(litMesh.material,lights,[],litScene,litMesh,[]);
    assert.equal(parameters().envMapPMREM,true);assert.equal(parameters().envMapSize,env.image[0].width);
    const litKey=cache.getProgramCacheKey(parameters());
    assert.ok(cube.isCubeTexture&&env.isPMREMTexture);
    assert.equal(cube.image[0].width,['high','max'].includes(tier)?512:256);
    assert.equal(cube.type,THREE.HalfFloatType);assert.equal(cube.colorSpace,THREE.LinearSRGBColorSpace);
    const key=JSON.stringify([env.uuid,env.image[0].width,env.mipmaps.length,env.mapping,env.type]);
    const material=calls.find(([s])=>s.name==='twin-atmosphere')[0].children[0].material, program=material.customProgramCacheKey(),version=material.version;
    assert.ok(material.fragmentShader.includes('pow(max(1e-4,')&&material.fragmentShader.includes('/max(ext,vec3(1e-6))'));
    for(const alt of [60,2,-20]) for(const overcast of [0,1]) {
      const before=calls.length;assert.equal(sky.update({sunDir:direction(alt),moonDir:direction(30),moonFraction:1,overcast,force:true}),true);
      assert.ok(calls.length>before+6,'six sky faces and real PMREM filtering');
      assert.equal(sky.cube,cube);assert.equal(sky.environment,env);
      assert.equal(JSON.stringify([env.uuid,env.image[0].width,env.mipmaps.length,env.mapping,env.type]),key);
      assert.equal(material.customProgramCacheKey(),program);
      assert.equal(material.version,version,'uniform changes never invalidate the sky material');
      assert.equal(cache.getProgramCacheKey(parameters()),litKey,'real r187 envMapPMREM/size/LOD key is fixed');
      assert.ok(sky.horizon([0,0,1]).isColor);
      assert.equal(renderer.getRenderTarget(),target);assert.equal(renderer.face,3);assert.equal(renderer.mip,2);assert.equal(renderer.xr.enabled,true);assert.equal(renderer.autoClear,false);
    }
    const input={sunDir:direction(60),moonDir:direction(30),overcast:0};sky.update({...input,force:true});
    assert.equal(sky.update({...input,sunDir:direction(60.1),overcast:.04}),false);
    assert.equal(sky.update({...input,sunDir:direction(60.3)}),true);
    assert.equal(sky.update({...input,overcast:.06}),true);
    assert.equal(sky.update({...input,moonDir:direction(31),overcast:.06}),true);
    const draw=renderer.render;renderer.render=()=>{throw Error('sky draw failed');};
    try {assert.throws(()=>sky.update({...input,force:true}),/sky draw failed/);}
    finally {renderer.render=draw;}
    assert.equal(renderer.getRenderTarget(),target);assert.equal(renderer.face,3);assert.equal(renderer.mip,2);assert.equal(renderer.xr.enabled,true);assert.equal(renderer.autoClear,false);
    assert.equal(sky.update({...input,force:true}),true,'a failed draw can retry');
    const disposed=[],release=THREE.WebGLCubeRenderTarget.prototype.dispose;
    THREE.WebGLCubeRenderTarget.prototype.dispose=function(){disposed.push(this.texture);return release.call(this);};
    try {sky.dispose();sky.dispose();assert.equal(disposed.filter(t=>t===cube).length,1);assert.equal(disposed.filter(t=>t===env).length,1);}
    finally {THREE.WebGLCubeRenderTarget.prototype.dispose=release;target.dispose();litMesh.geometry.dispose();litMesh.material.dispose();}
  }
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(out)
    sys.exit(code or 0)
