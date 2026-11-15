"""Fixture shadowmask transport; production modules in node, no browser or HA."""
import sys
import test_twin_real_lights_js as harness

DRIVER = harness.DRIVER[:harness.DRIVER.index("class Node")] + r"""
globalThis.window={}; const THREE=await import('three'); const FT=.3048;
const {createHash}=await import('node:crypto');
const checks=[]; const check=(name,fn)=>checks.push([name,fn]);
const {resolveEmitters} = await import(file('static/twin/live/emitters.js'));
const A = await import(file('static/twin/bake/atlas.js'));
const B = await import(file('static/twin/bake/baker.js'));
const P = await import(file('static/twin/bake/bake_pass.js'));
const M = await import(file('static/twin/bake/lightmap_material.js'));
const RT = await import(file('static/twin/bake/runtime.js'));
let F; try { F = await import(file('static/twin/bake/fixture_terms.js')); } catch {}
const needFixtures = () => assert.ok(F,'fixture bake transport module loads');
const plan={buildings:[],site:{}};
const fixture=(id,shape,extra={})=>({id:'fixture:'+id,shape,ref:'absolute',at:[0,0,4],...extra});
const fixtureLayout=rows=>({markers:[],light_fixtures:{'light.test':rows}});
const group=rows=>RT.bakeLights(fixtureLayout(rows),null,plan)[0];
const panel=()=>fixture('panel','area',{size_ft:[4,4],facing:'down'});
const V=(x,y,z)=>new THREE.Vector3(x,y,z);
const close=(a,b,e=1e-7)=>assert.ok(Math.abs(a-b)<=e,`${a} != ${b}`);
// Preprocess the generated shader and bundled chunks to count declarations,
// including both branches of the live-area/fallback LTC binding contract.
function samplerBudget(source, areas) {
  const macros=new Map(Object.entries({STANDARD:1,USE_MAP:1,USE_NORMALMAP:1,USE_ROUGHNESSMAP:1,
    USE_METALNESSMAP:1,USE_AOMAP:1,USE_ENVMAP:1,ENVMAP_TYPE_CUBE_UV:1,USE_SHADOWMAP:1,SHADOWMAP_TYPE_PCF:1,
    NUM_DIR_LIGHTS:1,NUM_DIR_LIGHT_SHADOWS:1,NUM_SUN_LIGHTS:0,NUM_SUN_LIGHT_SHADOWS:0,
    NUM_POINT_LIGHTS:12,NUM_POINT_LIGHT_SHADOWS:1,NUM_SPOT_LIGHTS:4,NUM_SPOT_LIGHT_SHADOWS:0,
    NUM_SPOT_LIGHT_MAPS:0,NUM_SPOT_LIGHT_COORDS:0,NUM_RECT_AREA_LIGHTS:areas,NUM_HEMI_LIGHTS:0,
    NUM_LIGHT_PROBES:0,NUM_CLIPPING_PLANES:0,UNION_CLIPPING_PLANES:0}));
  const expand=s=>s.replace(/#include <(\w+)>/g,(_,name)=>expand(THREE.ShaderChunk[name]));
  const expression=s=>s.replace(/defined\s*\(\s*(\w+)\s*\)/g,(_,k)=>macros.has(k)?'1':'0')
    .replace(/\b[A-Za-z_]\w*\b/g,k=>String(Number(macros.get(k))||0));
  const evaluate=s=>!!Function('return ('+expression(s)+')')();
  const stack=[],lines=[];let active=true;
  for(const line of expand(source).split('\n')) {
    const directive=line.trim().match(/^#(\w+)\s*(.*)$/);
    if(!directive){if(active)lines.push(line);continue;}
    const [,op,arg]=directive;
    if(['if','ifdef','ifndef'].includes(op)) {
      const on=op==='if'?evaluate(arg):op==='ifdef'?macros.has(arg):!macros.has(arg);
      stack.push({parent:active,taken:on});active=active&&on;
    } else if(op==='else'||op==='elif') {
      const top=stack.at(-1),on=!top.taken&&(op==='else'||evaluate(arg));top.taken||=on;active=top.parent&&on;
    } else if(op==='endif') active=stack.pop().parent;
    else if(active&&op==='define') {const [name,...value]=arg.split(/\s+/);if(!name.includes('('))macros.set(name,value.join(' ')||1);}
    else if(active&&op==='undef')macros.delete(arg);
  }
  const declarations=[...lines.join('\n').matchAll(/uniform\s+(?:highp\s+)?sampler\w+\s+(\w+)\s*(?:\[\s*(\w+)\s*\])?/g)];
  return {count:declarations.reduce((n,m)=>n+(m[2]?Number(macros.get(m[2])||m[2]):1),0),names:declarations.map(m=>m[1])};
}
const energy=(light,at,normal,visible=()=>1)=>F.sampleValue(F.bakeSamples(plan,light),at,normal,visible,light.kind,light.scale||1);
// A one-texel GPU double evaluates the uniforms submitted by the real cube/atlas
// pass. Occlusion uses real three raycasts; filtering and quantization are production.
async function renderProbe(light, blockers=[], point=V(0,0,0), normal=V(0,1,0), tier='high') {
  const mesh=new THREE.Mesh(new THREE.PlaneGeometry(1,1).toNonIndexed(),new THREE.MeshStandardMaterial());
  mesh.geometry.setAttribute('uv3',new THREE.Float32BufferAttribute(new Float32Array(12),2));
  mesh.userData.merged=true;const scene=new THREE.Scene();scene.add(mesh,...blockers);scene.updateMatrixWorld(true);
  const chart={id:0,mesh,faces:[0,1],room:0,rect:{x:0,y:0,w:1,h:1}},values=[0,0,0,1],sources=[];
  let target=null,color=new THREE.Color(),alpha=0;
  const renderer={toneMapping:THREE.NoToneMapping,autoClear:true,xr:{enabled:false},
    getRenderTarget:()=>target,setRenderTarget:t=>target=t,getClearColor:c=>c.copy(color),getClearAlpha:()=>alpha,
    setClearColor:(c,a)=>{color.set(c);alpha=a;},clear:()=>{},
    render(s,camera){
      if(camera.isPerspectiveCamera)return;
      const u=s.overrideMaterial.uniforms,source=u.source.value.clone();sources.push(source);
      const piece=u.pieceU.value.lengthSq()?{position:u.pieceCentre.value.clone(),u:u.pieceU.value.clone(),v:u.pieceV.value.clone()}:null;
      const sample={source,origin:u.origin.value,range:u.reach.value,weight:u.weight.value,cd:u.cd.value,
        normal:u.emitterNormal.value,axis:u.axis.value,outer:u.outer.value,inner:u.inner.value,
        visibilityWeight:u.visibilityWeight.value,piece};
      const visible=()=>{
        const lifted=point.clone().addScaledVector(normal,Math.min(.03,.005+.004*source.distanceTo(point)));
        const ray=new THREE.Raycaster(lifted,source.clone().sub(lifted).normalize(),.001,lifted.distanceTo(source)-.02);
        return ray.intersectObjects(blockers,false).length?0:1;
      };
      const e=F.sampleValue([sample],point,normal,visible,0,1);
      values[0]+=light.kind===3?e.irradiance/(light.scale||1):e.value;values[1]+=e.irradiance/16;
    },
    readRenderTargetPixels(t,x,y,w,h,raw){values.forEach((v,i)=>raw[i]=THREE.DataUtils.toHalfFloat(v));}};
  const bytes=await P.renderPage({plan,scene,tier},renderer,[chart],1,light,{}, {room:{charts:[chart]}});
  return {bytes,sources};
}
check('twelve_fixtures_one_entity_one_channel_per_chart',()=>{
  const list=RT.bakeLights(fixtureLayout(Array.from({length:12},(_,i)=>fixture('p'+i,'point',{at:[i,0,4]}))),null,plan);
  assert.equal(list.length,1); assert.equal(list[0].emitters.length,12); assert.equal(list[0].kind,3);
  const lights=list.map(l=>({...l,receivingCharts:[0,1],receivers:[0],scores:{0:12,1:6},chartKeys:{0:'a',1:'b'}}));
  const slots=A.assignChannels([{id:'room',building:null}],lights);
  assert.equal(Object.keys(slots).length,1);assert.equal(slots['light.test'].assignments.length,2);
  const separate=Array.from({length:12},(_,i)=>({device:'fixture:'+i,entity_id:'light.test',building:null,
    room:'room',receivingCharts:[0],receivers:[0],scores:{0:1},chartKeys:{0:'a'}}));
  const aggregate=A.assignChannels([{id:'room',building:null}],separate);
  assert.deepEqual(Object.keys(aggregate),['light.test']);assert.equal(aggregate['light.test'].assignments[0].score,12);
  assert.deepEqual(RT.bakeLights({markers:[{kind:'light',placed:false,entity_id:'light.unplaced',at:null}]},null,plan),[]);
});
check('legacy_house_bake_identical',async()=>{
  needFixtures(); const old={device:'lamp',building:null,level:null,room:'yard',at:[2,2,4],yard:true};
  const layout={markers:[{kind:'light',placed:true,device_id:'lamp',entity_id:'light.lamp',room:'yard',yard:true,at:[2,2,4]}]};
  assert.deepEqual(RT.bakeLights(layout,null,plan),[old]);
  const samples=F.bakeSamples(plan,old);assert.equal(samples.length,16);
  const {lightSource}=awaitImportReach;const src=lightSource(plan,old).source;
  for(let i=0;i<16;i++){
    const z=1-2*(i+.5)/16,a=i*2.3999632297,r=Math.sqrt(1-z*z)*.15*FT;
    assert.deepEqual(samples[i].source.toArray(),src.clone().add(V(Math.cos(a)*r,z*.15*FT,Math.sin(a)*r)).toArray());
    close(samples[i].weight,1/16);
  }
  const oldSlots=A.assignChannels([{building:null,id:'yard'}],[old]);
  assert.deepEqual(A.assignChannels([{building:null,id:'yard'}],RT.bakeLights(layout,null,plan)),oldSlots);
  const at=V(2*FT,0,-2*FT),n=V(0,1,0);
  const oldByte=Math.round(255*samples.reduce((s,p)=>s+p.weight,0));
  assert.equal(Math.round(255*energy(old,at,n).value),oldByte);
  const rendered=await renderProbe(old,[],at,n);
  assert.deepEqual(rendered.sources.map(p=>p.toArray()),samples.map(p=>p.source.toArray()));
  const reference=F.sampleValue(samples,at,n,()=>1,0,1);
  assert.deepEqual([...rendered.bytes],[255,Math.round(Math.min(1,THREE.DataUtils.fromHalfFloat(THREE.DataUtils.toHalfFloat(reference.irradiance/16)))*255),0,255]);
});
const awaitImportReach=await import(file('static/twin/bake/reach.js'));
check('spot_slot_is_kind_1_and_cone_matches_live',()=>{
  needFixtures();const l=group([fixture('spot','spot',{aim:[0,0,0],cone_deg:60,softness:.3})]);assert.equal(l.kind,1);
  const u=M.lightmapUniforms(1,1,{fixtures:true});M.setLightSource(u,0,0,V(...l.emitters[0].position),6,1,l);
  const data=u.lmTints.value.image.data;
  const spot=new THREE.SpotLight();spot.angle=Math.PI/6;spot.penumbra=.3;
  for(const angle of [0,10,21,25,30,40]){
    const c=Math.cos(angle*Math.PI/180),outer=Math.cos(spot.angle),inner=Math.cos(spot.angle*(1-spot.penumbra));
    const t=Math.max(0,Math.min(1,(c-outer)/(inner-outer)));
    close(F.coneWindow(c,outer,inner),t*t*(3-2*t));
    close(F.coneWindow(c,data[15],data[16]),t*t*(3-2*t),1e-5);
  }
});
check('rect_visibility_is_fraction_of_samples_seen',async()=>{
  needFixtures();const l=group([panel()]),at=V(0,0,0),n=V(0,1,0);
  close(energy(l,at,n,p=>p.source.x<0?0:1).value,.5,.04);
  close(energy(l,at,n).value,1);close(energy(l,at,n,()=>0).value,0);
  const samples=F.bakeSamples(plan,l);assert.ok(samples.length>=16&&samples.length<=48);
  const blocker=new THREE.Mesh(new THREE.PlaneGeometry(10,10).rotateX(-Math.PI/2),new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));
  blocker.position.set(-5,.6,0);
  close((await renderProbe(l,[blocker])).bytes[0]/255,.5,.04);
  assert.equal((await renderProbe(l)).bytes[0],255);
  blocker.position.x=0;assert.equal((await renderProbe(l,[blocker])).bytes[0],0);
});
check('rect_is_one_sided',async()=>{
  needFixtures();const l=group([panel()]);close(energy(l,V(0,2,0),V(0,-1,0)).value,0);
  const p=F.rectPieces(l.emitters[0])[0];close(F.rectIrradiance(p,V(0,2,0),V(0,-1,0)),0);
  assert.ok(F.rectIrradiance(p,V(0,0,0),V(0,1,0))>0);
  assert.equal((await renderProbe(l,[],V(0,2,0),V(0,-1,0))).bytes[0],0);
});
check('line_facing_down_grazes_wall_below',()=>{
  needFixtures();const l=group([fixture('run','line',{path:[[-4,0,4],[4,0,4]],width_in:.5,facing:'down'})]);
  const pieces=F.rectPieces(l.emitters[0]);
  const value=y=>pieces.reduce((s,p)=>s+F.rectIrradiance(p,V(0,y,-.05),V(0,0,1)),0);
  assert.ok(value(.8)>value(1.6));assert.ok(value(.8)>0);
});
check('multi_fixture_entity_stores_scaled_irradiance_and_restores_it',async()=>{
  needFixtures();const l=group([fixture('one','point',{at:[-2,0,4],share:1}),fixture('two','point',{at:[2,0,4],share:3})]);
  assert.equal(l.kind,3);const at=V(0,0,0),n=V(0,1,0),samples=F.bakeSamples(plan,l);
  const one=F.sampleValue(samples.filter(s=>s.emitter===0),at,n,()=>1,3,100).irradiance;
  const two=F.sampleValue(samples.filter(s=>s.emitter===1),at,n,()=>1,3,100).irradiance;
  close(two/one,3,.02);const scale=one+two+1;
  const stored=F.sampleValue(samples,at,n,()=>1,3,scale);
  const byte=Math.round(stored.value*255);close(F.decodeIrradiance(byte/255,scale),one+two,scale/128);
  const rendered=await renderProbe({...l,scale});close(F.decodeIrradiance(rendered.bytes[0]/255,scale),one+two,scale/128);
});
check('reaim_changes_fingerprint_and_marks_only_that_entity_stale',async()=>{
  const a=group([fixture('s','spot',{aim:[0,0,0]})]),b=group([fixture('s','spot',{aim:[2,0,0]})]);
  assert.notEqual(a?.signature,b?.signature);const slot={bank:0,channel:0},atlas={key:'geometry'};
  assert.notEqual(B.lightKey(atlas,a,slot,{}),B.lightKey(atlas,b,slot,{}));
  const other=group([panel()]);assert.equal(B.lightKey(atlas,other,slot,{}),B.lightKey(atlas,group([panel()]),slot,{}));
  const p={buildings:[{id:'house',position:[0,0],levels:[{id:'L',elevation:0,ceiling:8}],
    rooms:[{id:'room',level:'L',polygon:[[-8,-8],[8,-8],[8,8],[-8,8]]}]}]};
  const root=new THREE.Group();root.scale.setScalar(FT);root.userData.buildingId='house';
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(16,16).rotateX(-Math.PI/2),new THREE.MeshStandardMaterial({name:'floor'}));
  floor.userData.merged=true;root.add(floor);root.updateMatrixWorld(true);
  const options={room:{density:1,page:64,gutter:2}},physical=A.buildAtlas(root,p,options);
  const input={markers:[],light_fixtures:{'light.test':[fixture('s','spot',{aim:[0,0,0]})],'light.other':[panel()]}};
  const before=B.bakeLayout(physical,options,RT.bakeLights(input,null,p));
  input.light_fixtures['light.test'][0].aim=[3,0,0];
  const lights=RT.bakeLights(input,null,p),after=B.bakeLayout(physical,options,lights,before.ownership);
  assert.notEqual(before.entries['light.test'].key,after.entries['light.test'].key);
  assert.equal(before.entries['light.other'].key,after.entries['light.other'].key);
  const manifest={pages:before.pages,ownership:before.ownership,lights:before.entries};
  const baker=B.createBaker({plan:p,tier:'high'},{atlas:physical,layout:options,lights,api:async(path,init)=>
    init?.headers?new Response(null,{status:304}):new Response(JSON.stringify(manifest))});
  assert.deepEqual(await baker.staleLights(),['light.test']);baker.cancel();
});
check('brightness_and_colour_do_not',()=>{
  needFixtures();const l=fixtureLayout([panel()]);const before=RT.bakeLights(l,null,plan);
  l.states={'light.test':{state:'on',attributes:{brightness:20,rgb_color:[10,30,90]}}};
  assert.deepEqual(RT.bakeLights(l,null,plan),before);
});
check('rect_cap_changes_shading_only',async()=>{
  needFixtures();const lights=Array.from({length:10},(_,i)=>({...group([panel()]),device:'light.'+i,entity:'light.'+i}));
  const low=F.exactRects(lights,'low'),high=F.exactRects(lights,'high');assert.equal(low.size,2);assert.equal(high.size,8);
  const l=lights[5],slot={bank:0,channel:0};assert.equal(B.lightKey({key:'a'},l,slot,{}),B.lightKey({key:'a'},{...l,exact:false},slot,{}));
  assert.ok(!low.has(l.device));const p=F.rectPieces(l.emitters[0])[0];assert.ok(F.rectIrradiance(p,V(0,0,0),V(0,1,0),false)>0);
  const u=M.lightmapUniforms(1,1,{fixtures:true});
  M.setLightSource(u,0,0,V(0,1,0),6,2,l,low.has(l.device));assert.equal(u.lmTints.value.image.data[11],0);
  M.setLightSource(u,0,0,V(0,1,0),6,2,l,high.has(l.device));assert.equal(u.lmTints.value.image.data[11],1);
  assert.deepEqual((await renderProbe(l,[],V(0,0,0),V(0,1,0),'low')).bytes,(await renderProbe(l,[],V(0,0,0),V(0,1,0),'high')).bytes);
});
check('fire_pit_bakes_from_emitters_with_flame_tint',()=>{
  const p={buildings:[],site:{fire_pit:[{id:'gas',at:[5,5],fuel:'gas',entity:'switch.fire',radius:2}]}};
  const lights=RT.bakeLights({markers:[]},null,p);assert.equal(lights.length,1);assert.equal(lights[0].device,'switch.fire');
  assert.equal(lights[0].emitters[0].fire_pit,true);assert.deepEqual(lights[0].emitters[0].rgb,[255,154,60]);
  assert.equal(lights[0].emitters[0].intensityScale,.5);
});
check('room_fill_present_for_rect_and_sum_slots',()=>{
  needFixtures();for(const l of [group([panel()]),group([panel(),fixture('p','point')])]){
    const e=energy(l,V(0,0,0),V(0,1,0)),bytes=new Uint8Array([0,Math.round(Math.min(1,e.irradiance/16)*255),0,255]);
    const fill=P.roomFills([{bytes,charts:[{room:0,rect:{x:0,y:0,w:1,h:1},mesh:{material:{color:new THREE.Color('white')}}}]}],1);
    assert.ok(fill[0]>0);
  }
});
check('worst_case_sampler_count_and_legacy_shader_work',()=>{
  needFixtures();const u=M.lightmapUniforms(1,1,{fixtures:true});M.setLightSource(u,0,0,V(0,1,0),6,2,group([panel()]),true);
  const m=new THREE.MeshStandardMaterial(),pages={banks:Array.from({length:3},()=>new THREE.DataArrayTexture())};
  M.patchLightmaps([m],pages,u);const shader={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};
  m.onBeforeCompile(shader,{extensions:{has:()=>true}});
  assert.equal(shader.uniforms.lmLtc1.value,THREE.UniformsLib.LTC_FLOAT_1);
  assert.equal(shader.uniforms.lmLtc2.value,THREE.UniformsLib.LTC_FLOAT_2);
  const textures=new Set(Object.values(shader.uniforms).map(v=>v.value).filter(v=>v?.isTexture));assert.equal(textures.size,7);
  const maps=5,environment=1,dfg=1,sun=1,lamp=1;
  assert.equal(textures.size+maps+environment+dfg+sun+lamp,16);
  for(const areas of [0,8]) {
    const budget=samplerBudget(shader.fragmentShader,areas);
    assert.ok(budget.count<=16,JSON.stringify(budget));
    assert.equal(budget.names.filter(n=>['ltc_1','ltc_2','lmLtc1','lmLtc2'].includes(n)).length,2,JSON.stringify(budget));
    console.log(`       ${areas} live area slots: ${budget.count} declared samplers`);
  }
  const legacy=M.lightmapUniforms(1,1);assert.equal(legacy.lmTints.value.image.height,3);
  const old=new THREE.MeshStandardMaterial();M.patchLightmaps([old],pages,legacy);
  const s={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};old.onBeforeCompile(s,{});
  assert.equal(s.uniforms.lmLtc1,undefined);assert.notEqual(old.customProgramCacheKey(),m.customProgramCacheKey());
  // Captured by executing the v2.499.871 material: identical GLSL tokens prove
  // legacy-only Low does not acquire a branch, fetch or rectangle operation.
  assert.equal(createHash('sha256').update((s.vertexShader+s.fragmentShader).replace(/\s/g,'')).digest('hex'),
    '462fecdf60ddd67aa7874af6ddce6ff6ed863638effb2fe9d1e3182ccbc55bf7');
  const half={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};
  m.onBeforeCompile(half,{extensions:{has:()=>false}});assert.equal(half.uniforms.lmLtc1.value,THREE.UniformsLib.LTC_HALF_1);
});
let passed=0;for(const [name,fn] of checks){try{await fn();passed++;console.log('  ok   '+name);}catch(e){console.log('  FAIL '+name+' '+e.stack);}}
console.log(`${passed}/${checks.length} passed`);process.exit(passed===checks.length?0:1);
"""

if __name__ == '__main__':
    harness.DRIVER = DRIVER
    sys.exit(1 if harness.run() else 0)
