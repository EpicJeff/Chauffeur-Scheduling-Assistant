"""Covered-sky lighting maths, roof-fade & sunlit-bounce wiring, single-point GLSL and softer sky fill: real r187 assembly in node."""
import json
from pathlib import Path
import sys

from test_twin_weather_surface_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]

DRIVER = PREFIX + r"""
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
const {sampleSkyIrradiance:skyIrr,sampleRadiance:skyRad}=await import(file('static/twin/sky/atmosphere.js'));
const {lookAt:skyLookAt}=await import(file('static/twin/sky/look.js'));
const {mountTwin:mountView}=await import(file('static/twin/twin_view.js'));

const close=(a,b,eps=1e-6)=>assert.ok(Math.abs(a-b)<=eps,`${a} != ${b}`);
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

await test('single-point lights_fragment_maps GLSL obeys open, normal, roof-fade, bounce delta and 0.3 IBL rules',()=>{
  const renderer=new Renderer(),scene=new THREE.Scene();
  renderer.toneMapping=THREE.ACESFilmicToneMapping;scene.environment=new THREE.Texture();
  const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),layer=installWeatherSurface(scene);
  const lights=makeLights();lights.directional=[{}];lights.hemi=[{}];
  const cache=programs(renderer);
  const mat=new THREE.MeshStandardMaterial({name:'patio_concrete'});
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(),mat);
  scene.add(mesh);haze.prepare();shadow.prepare();layer.prepare();
  const src=programSource(renderer,cache,scene,mesh,lights);
  const fs=preprocess(src[2]);

  // Stock hemisphere function is untouched (no per-light patching or weatherCover global).
  const hm=fs.match(/vec3 getHemisphereLightIrradiance\([^)]*\) \{([\s\S]*?)\n\}/);
  assert.ok(hm,'getHemisphereLightIrradiance present');
  assert.ok(hm[1].includes('vec3 irradiance = mix( hemiLight.groundColor, hemiLight.skyColor, hemiDiffuseWeight );'),'stock hemisphere chunk untouched');
  assert.ok(!fs.includes('weatherCover'),'no weatherCover global or helper overhead');

  // Extract and execute the REAL single-point expressions from lights_fragment_maps.
  const covExpr=fs.match(/float cov=([^;]+);/);
  const covWExpr=fs.match(/float covW=([^;]+);/);
  const iblExpr=fs.match(/float covIbl=([^;]+);/);
  assert.ok(covExpr&&covWExpr&&iblExpr,'single-point cov, covW and covIbl expressions present in lights_fragment_maps');
  assert.ok(fs.includes('float covUp=dot(geometryNormal,hemisphereLights[0].direction);'),'reuses hemisphereLights[0].direction for CSE');
  assert.ok(fs.includes('iblIrradiance*=covIbl;')&&fs.includes('radiance*=covIbl;'),'scales both diffuse and specular IBL once');
  assert.ok(fs.includes('irradiance.x+=stageRing[6].w*covW;')&&fs.includes('irradiance.y+=stageRing[7].w*covW;')&&fs.includes('irradiance.z+=stageRing[8].w*covW;'),'adds signed CPU coverDelta in one step');

  const evalCov=new Function('vWeatherOpen','covUp','stageRing','clamp','return '+covExpr[1]);
  const evalCovW=new Function('cov','covUp','return '+covWExpr[1]);
  const evalIbl=new Function('cov','return '+iblExpr[1]);
  const ringWith=roofFade=>{const r=Array.from({length:10},()=>({w:0}));r[5].w=1-roofFade;return r;};

  // Open surfaces (weatherOpen == 1) always yield 0 regardless of normal or roof fade.
  for(const up of [-1,0,.2,.45,.7,1])for(const roof of [0,.5,1])close(evalCov(1,up,ringWith(roof),clamp),0);

  // Vertical and downward faces under a roof yield 0 (keep today's look).
  for(const up of [-1,-.5,0,.1,.2])close(evalCov(0,up,ringWith(1),clamp),0);

  // Covered upward faces with roof on yield 1.
  for(const up of [.7,.85,1])close(evalCov(0,up,ringWith(1),clamp),1);

  // Linear ramp between up = 0.2 and up = 0.7.
  close(evalCov(0,.45,ringWith(1),clamp),.5);
  assert.ok(evalCov(0,.3,ringWith(1),clamp)>0&&evalCov(0,.3,ringWith(1),clamp)<.5);
  assert.ok(evalCov(0,.6,ringWith(1),clamp)>.5&&evalCov(0,.6,ringWith(1),clamp)<1);

  // Lifting or hiding the roof (roofFade == 0) returns cover to 0.
  for(const up of [0,.5,1])close(evalCov(0,up,ringWith(0),clamp),0);
  close(evalCov(0,1,ringWith(.5),clamp),.5);

  // IBL scale is 1 at cover=0, 0.3 at full cover=1, linear in between.
  close(evalIbl(0),1);
  close(evalIbl(1),.3);
  close(evalIbl(.5),.65);

  // Algebraic equivalence: stock mix(G, S, w) + (B - S) * cov * w == mix(G, mix(S, B, cov), w).
  const G=[.48,.50,.32],S=[.15,.27,.50],B=[.63,.60,.47];
  for(const up of [-1,0,.45,1])for(const open of [0,.5,1])for(const roof of [0,.5,1]){
    const w=.5*up+.5,cov=evalCov(open,up,ringWith(roof),clamp),covW=evalCovW(cov,up);
    for(let c=0;c<3;c++){
      const patched=G[c]+(S[c]-G[c])*w+(B[c]-S[c])*covW;
      const exact=G[c]+((S[c]+(B[c]-S[c])*cov)-G[c])*w;
      close(patched,exact,1e-6);
    }
  }

  layer.dispose();shadow.dispose();haze.dispose();
});

await test('softer sky fill uses cosine-weighted cloudIrradiance.top and sunlit ground bounce drives stageRing[5..8].w',async()=>{
  // Verify cosine-weighted sky irradiance is softer (less deeply blue) than pure zenith at mid-latitude winter noon (~30 deg sun).
  const novState={sunDir:[0,.5,.866],moonDir:[0,-1,0],moonFraction:0,overcast:0,fog:0};
  const irr=skyIrr(novState).top;
  const zen=skyRad([0,1,0],novState);
  const irrNorm=skyLookAt(30,undefined,{zenith:irr}).skyColor;
  const zenNorm=skyLookAt(30,undefined,{zenith:zen}).skyColor;
  assert.ok(irrNorm[0]>zenNorm[0],'cosine-weighted sky fill is softer (less deeply blue) than pure zenith');
  console.log('SKY_FILL',JSON.stringify({zenith:zenNorm.map(v=>+v.toFixed(3)),irradiance:irrNorm.map(v=>+v.toFixed(3))}));

  // Verify mounted viewer uses cloudIrradiance.top, drives stageRing[5].w (roof lift) and stageRing[6..8].w (coverDelta).
  const prevSearch=location.search; location.search='?test=1&tier=high';
  let v;
  try {
    v=await mountView(new Element(),{plan:structuredClone(input.plan),kit:{materials:{}},tier:'high',bake:false,
      site:{lat:40,lon:0,front_bearing_deg:180,source:'home_location',timezone:'Etc/UTC'}});
    v.setClock('2026-11-21T12:00:00Z');
    v.render();
    const hemi=v.scene.children.find(o=>o.isHemisphereLight);
    const sun=v.scene.getObjectByName('real-sun');
    assert.ok(hemi.color.r>zenNorm[0]+.04,`mounted hemisphere sky color is softer than zenith (r=${hemi.color.r.toFixed(3)} vs zenith ${zenNorm[0].toFixed(3)})`);

    const ringOf=()=>{
      v.scene.onBeforeRender(v.renderer3,v.scene,v.camera);
      let found=null;
      v.scene.traverse(o=>{for(const m of [].concat(o.material||[])){if(m.fog&&m.isMeshStandardMaterial&&!found){
        const s={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};
        m.onBeforeCompile(s,{});found=s.uniforms.stageRing?.value;
      }}});
      return found;
    };
    const ring=ringOf();
    assert.ok(ring,'stageRing bound on lit material');
    close(ring[23],0,1e-5); // roofFade == 1 => stageRing[5].w == 0

    // June noon: sunlit ground bounce adds warm irradiance; turning sun off drops back to dim neutral base bounce.
    v.setClock('2026-06-21T12:00:00Z');
    v.render();
    const sky=[hemi.color.r*hemi.intensity,hemi.color.g*hemi.intensity,hemi.color.b*hemi.intensity];
    const bounceSunOn=[ring[27]+sky[0],ring[31]+sky[1],ring[35]+sky[2]];
    assert.ok(bounceSunOn.every(x=>Number.isFinite(x)&&x>0),'sun-on cover bounce is finite and positive');
    assert.ok(bounceSunOn[2]/bounceSunOn[0]<1.0,'sun-on cover bounce is warm/neutral, not blue');

    const savedSun=sun.color.clone();
    sun.color.setRGB(0,0,0);
    v.render();
    const bounceSunOff=[ring[27]+sky[0],ring[31]+sky[1],ring[35]+sky[2]];
    assert.ok(bounceSunOff.every(x=>Number.isFinite(x)&&x>0),'sun-off cover bounce stays positive');
    assert.ok(bounceSunOff[0]<bounceSunOn[0]*0.65,'sun-off bounce is substantially dimmer than June noon sunlit bounce');
    assert.ok(ring[35]<0,'sun-off blue coverDelta is negative (subtracts blue sky)');
    sun.color.copy(savedSun);
    v.render();

    // Lifting the roof via floor view sets roofFade -> 0 => stageRing[5].w -> 1.
    v.setView(v.levelKeys()[0]);
    const oldNow=performance.now.bind(performance);
    let fakeNow=oldNow()+1000;
    performance.now=()=>fakeNow;
    try { v.render(); } finally { performance.now=oldNow; }
    close(ring[23],1,1e-5);

    // Returning to exterior restores roofFade -> 1 => stageRing[5].w -> 0.
    v.setView('ext');
    performance.now=()=>fakeNow+1000;
    try { v.render(); } finally { performance.now=oldNow; }
    close(ring[23],0,1e-5);
  } finally { v?.dispose(); location.search=prevSearch; }
});

finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan}, timeout=120)
    print(output)
    sys.exit(code)
