"""Stage horizon continuation and lunar filtering under real three, without a browser."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const THREE=await import('three');
const {sampleRadiance,createSky}=await import(file('static/twin/sky/atmosphere.js'));
const {createBodies}=await import(file('static/twin/sky/bodies.js'));
const direction=(alt,az)=>{const a=alt*Math.PI/180;return [Math.cos(a)*Math.sin(az),Math.sin(a),Math.cos(a)*Math.cos(az)];};
const luma=rgb=>rgb.reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
const {transmittance}=await import(file('static/twin/sky/atmosphere.js'));
const expectedGround=state=>{
  const sun=state.sunDir,c=state.overcast||0,vertical=transmittance([0,1,0]),direct=transmittance(sun);
  const air=[.008845,.012168,.021506],albedo=[.18,.20,.14];
  return albedo.map((a,i)=>a*((10*direct[i]*Math.max(0,sun[1])*(1-.75*c)+
    10*(1-vertical[i])*.25*Math.max(0,Math.min(1,sun[1]+.1))*(1+.35*c))/Math.PI+
    air[i]*(1+(state.moonFraction||0)*Math.max(0,state.moonDir?.[1]||0)*(1-c))));
};
await test('below-horizon ground joins each azimuth horizon through day, dusk and night',()=>{
  for(const sunAlt of [90,60,4,2,-6,-20]) for(const overcast of [0,.4,1]) for(const az of [0,.7,2,4]) {
    const state={sunDir:direction(sunAlt,.3),moonDir:direction(30,2),moonFraction:.8,overcast};
    const horizon=sampleRadiance(direction(0,az),state);
    for(const alt of [-.0001,-1]) {
      const rgb=sampleRadiance(direction(alt,az),state);
      rgb.forEach((v,i)=>assert.ok(Math.abs(v-horizon[i])<1e-8,JSON.stringify({sunAlt,overcast,az,alt,rgb,horizon})));
    }
    const ground=expectedGround(state);
    for(const alt of [-15,-20,-70,-89.9,-90]) {
      const rgb=sampleRadiance(direction(alt,az),state);
      rgb.forEach((v,i)=>assert.ok(Math.abs(v-ground[i])<1e-8,JSON.stringify({sunAlt,overcast,az,alt,rgb,ground})));
    }
    assert.deepEqual(sampleRadiance([0,-1,0],state),sampleRadiance([0,-2,0],state),'nadir remains finite and scale independent');
  }
  const sun={sunDir:direction(60,.3)};
  assert.notDeepEqual(sampleRadiance([0,1,0],sun),sampleRadiance([0,0,1],sun),'zenith keeps its physical ray');
  assert.notDeepEqual(sampleRadiance(direction(0,.3),sun),sampleRadiance(direction(0,Math.PI+.3),sun),'horizon retains azimuth variation');
});
await test('golden-hour lower sky is ground rather than orange horizon; night ground stays below sky',()=>{
  for(const overcast of [0,.4,1]) {
    const state={sunDir:direction(4,.3),overcast};
    const horizon=sampleRadiance(direction(0,.3),state),near=sampleRadiance(direction(-1,.3),state);
    near.forEach((v,i)=>assert.ok(Math.abs(v-horizon[i])<1e-8,'within one degree the seam is horizon radiance'));
    assert.ok(luma(sampleRadiance(direction(-15,.3),state))<luma(horizon)*.5);
    for(const sunAlt of [-20,-30]) for(const moonFraction of [0,1]) {
      const night={sunDir:direction(sunAlt,.3),moonDir:direction(60,2),moonFraction,overcast};
      const sky=sampleRadiance(direction(0,.3),night),zenith=sampleRadiance([0,1,0],night);
      for(const alt of [-.001,-1,-2,-5,-15,-90]) {
        const rgb=sampleRadiance(direction(alt,.3),night);
        assert.ok(luma(rgb)<=luma(sky)+1e-10);
        assert.ok(luma(rgb)<=luma(zenith)+1e-10);
      }
    }
  }
});
await test('mounted sky keeps the cube and PMREM while its shader uses horizon continuation',()=>{
  const renderer=new Renderer(),scenes=[],render=renderer.render;
  renderer.render=function(scene,camera){scenes.push(scene);return render.call(this,scene,camera);};
  const sky=createSky(renderer),cube=sky.cube,environment=sky.environment;
  const material=scenes.find(s=>s.name==='twin-atmosphere').children[0].material,key=material.customProgramCacheKey(),version=material.version;
  // Offline shader inspection complements CPU quadrature; no GPU claim is made.
  assert.ok(material.fragmentShader.includes('if(d.y<0.0)'),'cube folds all below-horizon rays');
  assert.ok(material.fragmentShader.includes('vec3(0.0,0.0,1.0)'),'zero horizontal length is finite');
  for(const sunAlt of [60,2,-20]) {
    sky.update({sunDir:direction(sunAlt,.3),overcast:.4,force:true});
    assert.equal(sky.cube,cube);assert.equal(sky.environment,environment);
    assert.equal(material.customProgramCacheKey(),key);assert.equal(material.version,version);
    const lower=sky.horizon(direction(-30,.7)).toArray(),horizon=sky.horizon(direction(0,.7)).toArray();
    const ground=expectedGround({sunDir:direction(sunAlt,.3),overcast:.4});
    lower.forEach((v,i)=>assert.ok(Math.abs(v-ground[i])<1e-8));
    material.uniforms.groundColour.value.toArray().forEach((v,i)=>assert.ok(Math.abs(v-ground[i])<1e-8,'cube receives the same lit ground radiance'));
    // Execute the actual cube shader's angular ramp and mix with the CPU
    // horizon/ground. This checks parity without claiming GPU compilation.
    const ramp=material.fragmentShader.match(/float groundWeight=([^;]+);/)[1];
    const smoothstep=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);};
    const weight=new Function('below','smoothstep',`return ${ramp};`);
    for(const alt of [-.01,-1,-2,-5,-10,-15,-20,-90]) {
      const t=weight(-direction(alt,.7)[1],smoothstep),rgb=sky.horizon(direction(alt,.7)).toArray();
      rgb.forEach((v,i)=>assert.ok(Math.abs(v-(horizon[i]*(1-t)+ground[i]*t))<1e-8,'cube ramp and CPU radiance agree'));
    }
    assert.notDeepEqual(lower,horizon,'mounted lower hemisphere is ground');
  }
  sky.dispose();
});
await test('loaded lunar JPEG explicitly receives mip filtering, capped anisotropy and sRGB',async()=>{
  const oldLoad=THREE.TextureLoader.prototype.loadAsync,oldFetch=globalThis.fetch;
  try {
    for(const tier of ['low','high']) for(const capability of [2,16]) {
      let map;THREE.TextureLoader.prototype.loadAsync=async()=>{map=new THREE.Texture();map.generateMipmaps=false;map.minFilter=THREE.NearestFilter;return map;};
      globalThis.fetch=async()=>({ok:true,json:async()=>({stars:[]})});
      const renderer=new Renderer();renderer.capabilities={getMaxAnisotropy:()=>capability};
      const sky=createSky(renderer,{tier});await sky.loadAssets();
      assert.equal(map.generateMipmaps,true);assert.equal(map.minFilter,THREE.LinearMipmapLinearFilter);
      assert.equal(map.magFilter,THREE.LinearFilter);assert.equal(map.colorSpace,THREE.SRGBColorSpace);
      assert.equal(map.anisotropy,Math.min(capability,tier==='low'?1:4));
      assert.equal(sky.object.getObjectByName('sky-moon').material.uniforms.moonMap.value,map);
      sky.dispose();
    }
  } finally {THREE.TextureLoader.prototype.loadAsync=oldLoad;globalThis.fetch=oldFetch;}
});
await test('lunar limb has a full antialiasing gutter and derivatives before all discards',()=>{
  const bodies=createBodies(),moon=bodies.object.getObjectByName('sky-moon'),shader=moon.material.fragmentShader;
  const points=moon.geometry.attributes.position.array;
  assert.ok(Math.max(...points)>1.2&&Math.min(...points)<-1.2,'quad covers both sides of the analytic limb');
  const discard=shader.search(/\bdiscard\s*;/);
  assert.ok(discard>=0&&shader.indexOf('fwidth(r2)')<discard,'edge derivatives are evaluated before divergent kills');
  assert.ok(shader.indexOf('texture2D(moonMap')<discard,'implicit texture derivatives have neighbouring fragments');
  assert.ok(shader.includes('1.0+width'),'coverage extends beyond the ideal circle');
  // Execute the scalar coverage expressions from the actual mounted shader.
  const expressions=['width','edge'].map(name=>shader.match(new RegExp('float '+name+'=([^;]+);'))[1]);
  const smoothstep=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);};
  const coverage=new Function('r2','fwidth','max','smoothstep',`const width=${expressions[0]};return ${expressions[1]};`);
  const edge=r2=>coverage(r2,()=>.1,Math.max,smoothstep);
  assert.equal(edge(1),.5);assert.ok(edge(.99)>.5);assert.ok(edge(1.01)>0&&edge(1.01)<.5);
  assert.equal(edge(.9),1);assert.equal(edge(1.1),0);
  assert.ok(shader.includes('albedo*48.0'),'preserve the calibrated moon gain');
  bodies.dispose();
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(out)
    sys.exit(code or 0)
