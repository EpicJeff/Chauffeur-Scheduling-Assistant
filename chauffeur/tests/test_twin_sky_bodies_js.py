"""Sun, textured lunar terminator and catalogue stars under real three r187; no browser."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const THREE=await import('three');
const {createBodies,discDiameterDeg}=await import(file('static/twin/sky/bodies.js'));
const {createStars,starDirection}=await import(file('static/twin/sky/stars.js'));
const catalogue=JSON.parse(readFileSync(new URL(file('static/twin/sky/assets/stars.json')),'utf8'));
const {transmittance,createSky}=await import(file('static/twin/sky/atmosphere.js'));
registerHooks({load(url,ctx,next){
  if(url.endsWith('three.module.js?body-keys'))return {format:'module',shortCircuit:true,source:readFileSync(new URL(url),'utf8')+'\nexport {WebGLPrograms};'};
  return next(url,ctx);
}});
const {WebGLPrograms}=await import(file('static/vendor/three-r187/three.module.js')+'?body-keys');
await test('eye-sized discs, distance and horizon refraction',()=>{
  assert.equal(discDiameterDeg('moon',60),2.2);
  assert.ok(Math.abs(discDiameterDeg('moon',0)-2.2*1.6)<1e-12);
  assert.equal(discDiameterDeg('sun',60),2);
  assert.ok(discDiameterDeg('moon',60,356500)>discDiameterDeg('moon',60,406700));
  const bodies=createBodies({moonMap:new THREE.Texture()});
  bodies.update({sunDir:[1,0,0],moonDir:[0,0,1],sunAltDeg:0,moonAltDeg:0,transmittance});
  const sun=bodies.object.getObjectByName('sky-sun'),moon=bodies.object.getObjectByName('sky-moon');
  assert.equal(sun.material.uniforms.flatten.value,.85);
  assert.ok(sun.material.uniforms.extinction.value.x>sun.material.uniforms.extinction.value.z,'red horizon');
  assert.ok(sun.material.uniforms.extinction.value.x<1,'dim horizon');
  assert.equal(moon.material.uniforms.flatten.value,.85);
  bodies.dispose();
});
await test('lunar surface normal and real sunlight give both quarters and full/new',()=>{
  const bodies=createBodies({moonMap:new THREE.Texture()}),moon=bodies.object.getObjectByName('sky-moon');
  for(const sunDir of [[1,0,0],[-1,0,0],[0,0,-1],[0,0,1],[.3,.7,-.2]]) {
    bodies.update({sunDir,moonDir:[0,0,1],moonPhase:.25,moonDistanceKm:384400,sunAltDeg:40,moonAltDeg:40,transmittance:()=>[1,1,1]});
    const u=moon.material.uniforms,light=u.lightDirection.value;
    const world=u.right.value.clone().multiplyScalar(light.x).addScaledVector(u.up.value,light.y).addScaledVector(u.direction.value,-light.z);
    assert.ok(world.dot(new THREE.Vector3(...sunDir).normalize())>.999,'lit hemisphere faces the real sun');
    if(sunDir[2]===-1) assert.ok(light.z>.999,'full faces observer');
    if(sunDir[2]===1) assert.ok(light.z<-.999,'new faces away');
  }
  assert.ok(moon.material.fragmentShader.includes('texture2D(moonMap'));
  assert.ok(moon.material.fragmentShader.includes('dot(normal,lightDirection)'));
  assert.ok(moon.material.fragmentShader.includes('0.025'),'earthshine');
  bodies.dispose();
});
await test('5080 magnitude-coloured quads, pole altitude and clock rotation',()=>{
  assert.equal(catalogue.stars.length,5080);
  // Polaris HR 424: J2000 RA 2h31m49s, Dec +89d15m51s; locate by coordinates.
  const polaris=catalogue.stars.find(([ra,dec])=>Math.abs(ra-.6624)<.002 && dec>1.557);
  assert.ok(polaris);
  for(const latitude of [0,40,75]) for(const lst of [0,1,4]) {
    const d=starDirection(polaris[0],polaris[1],lst,latitude*Math.PI/180);
    assert.ok(Math.abs(Math.asin(d[1])*180/Math.PI-latitude)<1);
  }
  const stars=createStars(catalogue);
  assert.ok(stars.object.isMesh);assert.equal(stars.object.geometry.attributes.position.count,5080*4);
  const u=stars.object.material.uniforms;
  stars.update({siderealTime:0,latitudeRad:.7,sunAltDeg:0,moonFraction:0,overcast:0});assert.equal(u.opacity.value,0);
  stars.update({siderealTime:1,latitudeRad:.7,sunAltDeg:-15,moonFraction:0,overcast:0});assert.equal(u.opacity.value,1);
  stars.update({siderealTime:2,latitudeRad:.7,sunAltDeg:-15,moonFraction:1,overcast:0});assert.ok(u.opacity.value<1);
  stars.update({sunAltDeg:-15,overcast:1});assert.equal(u.opacity.value,0);
  const colours=stars.object.geometry.attributes.starColor.array;
  assert.ok(Math.max(...colours)>Math.min(...colours));stars.dispose();
});
await test('time and weather retain objects, visibility, programs and finite uniforms',()=>{
  const bodies=createBodies({moonMap:new THREE.Texture()}),stars=createStars(catalogue);
  const meshes=[...bodies.object.children,stars.object];
  const keys=meshes.map(o=>[o.material.customProgramCacheKey(),o.material.version,o.visible]);
  for(const alt of [-90,-20,-12,-4,0,2,60,90]) for(const c of [0,.4,1]) {
    const dir=[Math.cos(alt*Math.PI/180),Math.sin(alt*Math.PI/180),0];
    bodies.update({sunDir:dir,moonDir:dir,sunAltDeg:alt,moonAltDeg:alt,overcast:c,transmittance});
    stars.update({siderealTime:alt,latitudeRad:Math.PI/2,sunAltDeg:alt,moonFraction:1,overcast:c});
    meshes.forEach((o,i)=>{
      assert.ok(o.isMesh&&!o.isPoints&&!o.isSprite);assert.equal(o.material.depthTest,true);assert.equal(o.material.depthWrite,false);
      assert.deepEqual([o.material.customProgramCacheKey(),o.material.version,o.visible],keys[i]);
      for(const {value} of Object.values(o.material.uniforms)) for(const n of value?.isVector3?value.toArray():typeof value==='number'?[value]:[]) assert.ok(Number.isFinite(n));
      assert.ok(o.material.vertexShader.includes('cameraPosition'),'capture camera centres itself');
    });
  }
  bodies.dispose();stars.dispose();
});
await test('vendored r187 program keys stay fixed across all clock/weather uniforms',()=>{
  const renderer=new Renderer();renderer.state={buffers:{depth:{getReversed:()=>false}}};
  const cache=WebGLPrograms(renderer,{get:t=>t},{has:()=>false},{precision:'highp',getMaxPrecision:()=> 'highp'},{},{numPlanes:0,numIntersection:0});
  const lights=Object.fromEntries(['sun','directional','point','spot','spotLightMap','rectArea','hemi','sunShadowMap','directionalShadowMap','pointShadowMap','spotShadowMap'].map(k=>[k,[]]));
  lights.numSpotLightShadowsWithMaps=0;lights.numLightProbes=0;
  const scene=new THREE.Scene(),bodies=createBodies(),stars=createStars(catalogue);
  const meshes=[...bodies.object.children,stars.object];scene.add(bodies.object,stars.object);
  const key=o=>cache.getProgramCacheKey(cache.getParameters(o.material,lights,[],scene,o,[]));
  const keys=meshes.map(key);
  for(const alt of [60,0,-6,-20])for(const overcast of [0,1]) {
    bodies.update({sunDir:[1,alt/90,0],moonDir:[0,1,1],overcast,transmittance});
    stars.update({siderealTime:alt,latitudeRad:.7,sunAltDeg:alt,overcast});
    meshes.forEach((o,i)=>assert.equal(key(o),keys[i]));
  }
  const texture=new THREE.Texture();bodies.setMap(texture);stars.setCatalogue({stars:catalogue.stars.slice(0,3)});
  meshes.forEach((o,i)=>assert.equal(key(o),keys[i],'asset arrivals keep keys'));
  bodies.dispose();stars.dispose();texture.dispose();
});
await test('cube draws the same bodies/stars and refreshes on catalogue arrival',()=>{
  const renderer=new Renderer(),draws=[],render=renderer.render;
  renderer.render=function(s,c){draws.push(s);return render.call(this,s,c);};
  const sky=createSky(renderer,{tier:'low'}),env=sky.environment,cube=sky.cube;
  sky.setAssets({moonMap:new THREE.Texture(),catalogue});
  const scene=draws.find(s=>s.name==='twin-atmosphere');
  for(const name of ['sky-sun','sky-moon','sky-stars'])assert.ok(scene.getObjectByName(name),name+' in reflections');
  assert.ok(sky.object.getObjectByName('sky-sun'));assert.ok(sky.object.getObjectByName('sky-stars'));
  sky.update({sunDir:[0,-1,0],moonDir:[0,1,0],siderealTime:1,latitude:.7,force:true});
  assert.equal(sky.environment,env);assert.equal(sky.cube,cube);
  assert.equal(sky.update({sunDir:[0,-1,0],moonDir:[0,1,0],siderealTime:1,overcast:.04}),false);
  assert.equal(sky.object.getObjectByName('sky-sun').material.uniforms.strength.value,1,'cloud transmittance replaces the interim scalar disc dimmer');
  sky.setEnabled(false);
  sky.object.traverse(o=>{if(o.isMesh)assert.equal(o.material.uniforms.enabled.value,0);});
  sky.dispose();
});
await test('real mounted clock, north, lunar distance and Unlit reach the mesh uniforms',async()=>{
  const {mountTwin}=await import(file('static/twin/twin_view.js'));
  const {moonPosition,localSiderealTime}=await import(file('static/twin/sky/ephemeris.js'));
  const {modelDirection}=await import(file('static/twin/sky/look.js'));
  const host=new Element();host.className='editor-shell';
  const view=await mountTwin(host,{plan:input.plan,kit:{materials:{}},tier:'low',bake:false,
    site:{lat:40,lon:-75,front_bearing_deg:90,source:'home_location'}});
  try {
    view.setTime('now');view.setClock('2026-11-18T03:00:00Z');
    const moon=view.scene.getObjectByName('sky-moon'),sun=view.scene.getObjectByName('sky-sun'),stars=view.scene.getObjectByName('sky-stars');
    const lunar=moonPosition('2026-11-18T03:00:00Z',40,-75),u=moon.material.uniforms;
    modelDirection(lunar.azimuth,lunar.altitude,90).forEach((v,i)=>assert.ok(Math.abs(v-u.direction.value.toArray()[i])<1e-12));
    assert.ok(Math.abs(u.radius.value-Math.tan(discDiameterDeg('moon',lunar.altitude*180/Math.PI,lunar.distance)*Math.PI/360))<1e-12);
    assert.equal(stars.material.uniforms.siderealTime.value,localSiderealTime('2026-11-18T03:00:00Z',-75));
    assert.equal(stars.material.uniforms.latitudeRad.value,40*Math.PI/180);
    assert.equal(stars.material.uniforms.bearing.value,Math.PI/2);
    const version=sun.material.version;view.setUnlit(true);
    for(const o of [sun,moon,stars]){assert.equal(o.visible,true);assert.equal(o.material.uniforms.enabled.value,0);}
    view.setUnlit(false);assert.equal(sun.material.uniforms.enabled.value,1);assert.equal(sun.material.version,version);
  } finally {view.dispose();}
});
await test('asset loading succeeds once, degrades separately and releases late textures',async()=>{
  const oldLoad=THREE.TextureLoader.prototype.loadAsync,oldFetch=globalThis.fetch;
  const urls=[];let delivered,loads=0,changed=0;
  try {
    THREE.TextureLoader.prototype.loadAsync=async url=>{urls.push(url);loads++;return delivered=new THREE.Texture();};
    globalThis.fetch=async url=>{urls.push(url);return {ok:true,json:async()=>catalogue};};
    const sky=createSky(new Renderer()),promise=sky.loadAssets(()=>changed++);
    assert.equal(sky.loadAssets(),promise);await promise;
    assert.equal(loads,1);assert.equal(changed,2);
    assert.equal(delivered.colorSpace,THREE.SRGBColorSpace);
    assert.equal(sky.object.getObjectByName('sky-moon').material.uniforms.moonMap.value,delivered);
    assert.equal(sky.object.getObjectByName('sky-stars').geometry.attributes.position.count,5080*4);
    for(const url of urls) assert.ok(url.startsWith(file('static/twin/sky/assets/')),'relative module URL retains ingress directory');
    let releases=0;delivered.addEventListener('dispose',()=>releases++);sky.dispose();sky.dispose();assert.equal(releases,1);
    THREE.TextureLoader.prototype.loadAsync=async()=>{throw Error('offline');};
    const partial=createSky(new Renderer());const result=await partial.loadAssets();
    assert.equal(result[0].status,'rejected');assert.equal(result[1].status,'fulfilled');
    assert.equal(partial.object.getObjectByName('sky-stars').geometry.attributes.position.count,5080*4);partial.dispose();
    THREE.TextureLoader.prototype.loadAsync=async()=>new THREE.Texture();
    globalThis.fetch=async()=>({ok:false,status:404});
    const missingStars=createSky(new Renderer()),missingResult=await missingStars.loadAssets();
    assert.equal(missingResult[0].status,'fulfilled');assert.equal(missingResult[1].status,'rejected');
    assert.equal(missingStars.object.getObjectByName('sky-stars').geometry.attributes.position.count,0);missingStars.dispose();
    let finishMoon;
    THREE.TextureLoader.prototype.loadAsync=()=>new Promise(resolve=>finishMoon=resolve);
    const late=createSky(new Renderer()),pending=late.loadAssets();late.dispose();
    const texture=new THREE.Texture();let lateReleased=0;texture.addEventListener('dispose',()=>lateReleased++);finishMoon(texture);
    await pending;assert.equal(lateReleased,1);
  } finally {THREE.TextureLoader.prototype.loadAsync=oldLoad;globalThis.fetch=oldFetch;}
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
