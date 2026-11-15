"""Fixture shadowmask transport; production modules in node, no browser or HA."""
import json
import subprocess
import sys
import test_twin_real_lights_js as harness

DRIVER = harness.DRIVER[:harness.DRIVER.index("class Node")] + r"""
globalThis.window={}; const THREE=await import('three'); const FT=.3048;
const {createHash}=await import('node:crypto');
// Execute main's modules without writing into either worktree.
const mainPaths=['baker.js','bake_pass.js','reach.js','atlas.js','lightmap_material.js'].map(p=>'static/twin/bake/'+p);
const mainURLs=new Map();
function mainURL(path) {
  if(mainURLs.has(path))return mainURLs.get(path);
  let source=mainSources[path];
  source=source.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
    const url=new URL(s,file(path)).href, ref=mainPaths.find(p=>file(p)===url);
    return a+(ref?mainURL(ref):url)+b;
  });
  const url='data:text/javascript;base64,'+Buffer.from(source).toString('base64');mainURLs.set(path,url);return url;
}
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
function samplerBudget(source, areas, clearcoat=false) {
  const macros=new Map(Object.entries({STANDARD:1,USE_MAP:1,USE_NORMALMAP:1,USE_ROUGHNESSMAP:1,
    USE_METALNESSMAP:1,USE_AOMAP:1,USE_ENVMAP:1,ENVMAP_TYPE_CUBE_UV:1,USE_SHADOWMAP:1,SHADOWMAP_TYPE_PCF:1,
    NUM_DIR_LIGHTS:1,NUM_DIR_LIGHT_SHADOWS:1,NUM_SUN_LIGHTS:0,NUM_SUN_LIGHT_SHADOWS:0,
    NUM_POINT_LIGHTS:12,NUM_POINT_LIGHT_SHADOWS:1,NUM_SPOT_LIGHTS:4,NUM_SPOT_LIGHT_SHADOWS:0,
    NUM_SPOT_LIGHT_MAPS:0,NUM_SPOT_LIGHT_COORDS:0,NUM_RECT_AREA_LIGHTS:areas,NUM_HEMI_LIGHTS:0,
    NUM_LIGHT_PROBES:0,NUM_CLIPPING_PLANES:0,UNION_CLIPPING_PLANES:0}));
  if(clearcoat)macros.set('USE_CLEARCOAT',1);
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
  return {count:declarations.reduce((n,m)=>n+(m[2]?Number(macros.get(m[2])||m[2]):1),0),names:declarations.map(m=>m[1]),source:lines.join('\n')};
}
const energy=(light,at,normal,visible=()=>1)=>F.sampleValue(F.bakeSamples(plan,light),at,normal,visible,light.kind,light.scale||1);
// A one-texel GPU double evaluates the uniforms submitted by the real cube/atlas
// pass. Occlusion uses real three raycasts; filtering and quantization are production.
async function renderProbe(light, blockers=[], point=V(0,0,0), normal=V(0,1,0), tier='high', pass=P) {
  const mesh=new THREE.Mesh(new THREE.PlaneGeometry(1,1).toNonIndexed(),new THREE.MeshStandardMaterial());
  mesh.geometry.setAttribute('uv3',new THREE.Float32BufferAttribute(new Float32Array(12),2));
  mesh.userData.merged=true;const scene=new THREE.Scene();scene.add(mesh,...blockers);scene.updateMatrixWorld(true);
  const chart={id:0,mesh,faces:[0,1],room:0,rect:{x:0,y:0,w:1,h:1}},values=[0,0,0,1],sources=[];
  let target=null,color=new THREE.Color(),alpha=0;
  const targets=new Set(),geometries=new Set();let disposedTargets=0,disposedGeometries=0;
  const renderer={toneMapping:THREE.NoToneMapping,autoClear:true,xr:{enabled:false},
    getRenderTarget:()=>target,setRenderTarget:t=>{
      target=t;if(t&&!targets.has(t)){targets.add(t);t.addEventListener('dispose',()=>disposedTargets++);}
    },getClearColor:c=>c.copy(color),getClearAlpha:()=>alpha,
    setClearColor:(c,a)=>{color.set(c);alpha=a;},clear:()=>{},
    render(s,camera){
      if(camera.isPerspectiveCamera)return;
      for(const o of s.children)if(!geometries.has(o.geometry)){
        geometries.add(o.geometry);o.geometry.addEventListener('dispose',()=>disposedGeometries++);
      }
      const u=s.overrideMaterial.uniforms,source=u.source.value.clone();sources.push(source);
      const piece=u.pieceU?.value.lengthSq()?{position:u.pieceCentre.value.clone(),u:u.pieceU.value.clone(),v:u.pieceV.value.clone()}:null;
      const sample={source,origin:u.origin?.value||source,range:u.reach.value,weight:u.weight.value,cd:u.cd?.value??40,
        normal:u.emitterNormal?.value||V(0,0,0),axis:u.axis?.value||V(0,0,0),outer:u.outer?.value??-1,inner:u.inner?.value??-1,
        visibilityWeight:u.visibilityWeight?.value,piece};
      const visible=()=>{
        const lifted=point.clone().addScaledVector(normal,Math.min(.03,.005+.004*source.distanceTo(point)));
        const ray=new THREE.Raycaster(lifted,source.clone().sub(lifted).normalize(),.001,lifted.distanceTo(source)-.02);
        return ray.intersectObjects(blockers,false).length?0:1;
      };
      const e=F.sampleValue([sample],point,normal,visible,0,1);
      values[0]+=light.kind===3?e.irradiance/u.scale.value:e.value;values[1]+=e.irradiance/(16*(u.fillStrength?.value??1));
    },
    readRenderTargetPixels(t,x,y,w,h,raw){values.forEach((v,i)=>raw[i]=THREE.DataUtils.toHalfFloat(v));}};
  const bytes=await pass.renderPage({plan,scene,tier},renderer,[chart],1,light,{}, {room:{charts:[chart]}});
  return {bytes,sources,resources:{targets:targets.size,disposedTargets,geometries:geometries.size,disposedGeometries}};
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
check('legacy_inputs_slots_jitter_and_uniform_submission_identical',async()=>{
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
check('legacy_key_pages_and_shader_equal_main',async()=>{
  const mainB=await import(mainURL('static/twin/bake/baker.js'));
  const mainA=await import(mainURL('static/twin/bake/atlas.js'));
  const mainP=await import(mainURL('static/twin/bake/bake_pass.js'));
  const mainR=await import(mainURL('static/twin/bake/reach.js'));
  const mainM=await import(mainURL('static/twin/bake/lightmap_material.js'));
  const {p,root,options,atlas}=physicalRoom();
  const legacy={device:'legacy',building:'house',level:'L',room:'room',at:[2,2,4]};
  const oldAtlas=mainA.buildAtlas(root,p,options),before=mainB.bakeLayout(oldAtlas,options,[legacy]);
  const after=B.bakeLayout(atlas,options,[legacy]);
  const {lights:reached,...comparable}=after;
  assert.deepEqual(reached,mainR.reachLights(oldAtlas.room,[legacy]),'reach and every per-light key input equal main');
  assert.deepEqual(comparable,before,'chart keys, ranking, ownership, locations and light keys equal main');
  for(const slot of [{bank:1,channel:0},{bank:0,channel:1,assignments:[{chartKey:'z',bank:1,channel:0},{chartKey:'a',bank:0,channel:1}]}])
    assert.equal(B.lightKey(atlas,legacy,slot),mainB.lightKey(atlas,legacy,slot),'legacy lightKey is main value');
  for(const blockers of [[],[new THREE.Mesh(new THREE.BoxGeometry(10,.2,10).translate(0,.5,0),new THREE.MeshBasicMaterial())]]) {
    for(const m of blockers)m.updateMatrixWorld(true);
    const now=await renderProbe(legacy,blockers),old=await renderProbe(legacy,blockers,V(0,0,0),V(0,1,0),'high',mainP);
    assert.deepEqual(now.bytes,old.bytes);assert.deepEqual(now.sources,old.sources);
    const charts=[{room:0,rect:{x:0,y:0,w:1,h:1},mesh:{material:{color:new THREE.Color('white')}}}];
    assert.deepEqual(P.roomFills([{bytes:now.bytes,charts}],1,legacy),mainP.roomFills([{bytes:old.bytes,charts}],1));
  }
  const compile=module=>{
    const u=module.lightmapUniforms(1,1);module.setLightSource(u,0,0,V(0,1,0),6);
    const m=new THREE.MeshStandardMaterial();module.patchLightmaps([m],{banks:[new THREE.DataArrayTexture()]},u);
    const s={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};m.onBeforeCompile(s,{});
    return {data:u.lmTints.value.image.data,glsl:(s.vertexShader+s.fragmentShader).replace(/\s/g,'')};
  };
  assert.deepEqual(compile(M),compile(mainM),'legacy shader reads the same bytes as main');
});
function physicalRoom(segments=1) {
  const p={buildings:[{id:'house',position:[0,0],levels:[{id:'L',elevation:0,ceiling:8}],
    rooms:[{id:'room',level:'L',polygon:[[-10,-10],[10,-10],[10,10],[-10,10]]}]}]};
  const root=new THREE.Group();root.scale.setScalar(FT);root.userData.buildingId='house';
  for(const ceiling of [false,true]) {
    const g=new THREE.PlaneGeometry(20,20,segments,segments).rotateX(ceiling?Math.PI/2:-Math.PI/2);
    if(ceiling)g.translate(0,8,0);
    const m=new THREE.Mesh(g,new THREE.MeshStandardMaterial({name:ceiling?'ceiling':'floor'}));
    m.userData.merged=true;root.add(m);
  }
  root.updateMatrixWorld(true);
  const options={room:{density:2,page:128,gutter:2}};
  return {p,root,options,atlas:A.buildAtlas(root,p,options)};
}
check('group_reach_cached_and_within_legacy_timing',()=>{
  const run=(name,rows,legacyCount)=>{
    const {p,options,atlas}=physicalRoom(150);
    const input=RT.bakeLights({markers:[],light_fixtures:rows},null,p);
    const legacy=Array.from({length:legacyCount},(_,i)=>({device:'old'+i,absolute:true,at:[i%8-4,Math.floor(i/8)-1,7.9],range:18}));
    const legacyScene=physicalRoom(150);
    const start=performance.now();B.bakeLayout(legacyScene.atlas,legacyScene.options,legacy);const old=performance.now()-start;
    const firstAt=performance.now(),first=B.bakeLayout(atlas,options,input),firstMs=performance.now()-firstAt;
    const reader=B.bakeLayout(atlas,options,input,first.ownership,
      Object.fromEntries(input.map(l=>[l.device,{scale:17}])));
    const secondAt=performance.now(),second=B.bakeLayout(atlas,options,input),secondMs=performance.now()-secondAt;
    assert.deepEqual(reader.entries, Object.fromEntries(Object.entries(first.entries).map(([id,e])=>
      [id,input.find(l=>l.device===id).kind===3?{...e,scale:17}:e])));
    assert.deepEqual(second.entries,first.entries);
    assert.ok(secondMs<50,`${name} cached ${secondMs} ms`);
    assert.ok(firstMs<old*3,`${name} first ${firstMs} ms vs legacy ${old} ms`);
    console.log(`       C2 ${name}: legacy ${old.toFixed(2)} ms, first ${firstMs.toFixed(2)} ms, second ${secondMs.toFixed(2)} ms`);
  };
  run('8 x 3 points',Object.fromEntries(Array.from({length:8},(_,i)=>['light.'+i,
    Array.from({length:3},(_,j)=>fixture(i+'p'+j,'point',{at:[i-4,j-1,7.9]}))])),24);
  run('line + panel + 3 points',{'light.line':[fixture('l','line',{path:[[-4,0,7.9],[5,0,7.9]],width_in:.5,facing:'down'})],
    'light.panel':[panel()], 'light.cluster':Array.from({length:3},(_,i)=>fixture('p'+i,'point',{at:[i-1,0,7.9]}))},5);
});
// Raster the atlas's real receiver triangles in a renderer double. The production
// pass submits every emitter uniform and reads half floats; this double supplies
// unoccluded pixels at those UVs. No tessellation-dependent CPU scale estimate.
async function renderedSumScene(rows) {
  const {p,root,options,atlas}=physicalRoom(1),size=options.room.page;
  const input=RT.bakeLights(fixtureLayout(rows),null,p),packed=B.bakeLayout(atlas,options,input),light=packed.lights[0];
  assert.equal(light.scale,undefined,'there is no scale before a first bake');
  const pages=[];
  const charts=packed.banks.flatMap((bank,i)=>bank.charts.map(c=>({...c,page:c.page+packed.offsets[i]})));
  for(const page of [...new Set(charts.map(c=>c.page))]) {
    const mine=charts.filter(c=>c.page===page),texels=new Map(),values=new Float64Array(size*size*4);
    for(const c of mine) {
      const g=c.mesh.geometry,uv=g.attributes.uv3,pos=g.attributes.position,norm=g.attributes.normal;
      const base=atlas.room.charts.find(b=>b.mesh===c.mesh&&b.faces===c.faces);
      for(const f of c.faces) {
        const ids=[0,1,2].map(k=>f*3+k),vs=ids.map(i=>new THREE.Vector2().fromBufferAttribute(uv,i).multiplyScalar(size)
          .add(new THREE.Vector2(c.rect.x-base.rect.x,c.rect.y-base.rect.y)));
        const ws=ids.map(i=>new THREE.Vector3().fromBufferAttribute(pos,i).applyMatrix4(c.mesh.matrixWorld));
        const normal=new THREE.Vector3().fromBufferAttribute(norm,ids[0]).transformDirection(c.mesh.matrixWorld);
        const denom=(vs[1].y-vs[2].y)*(vs[0].x-vs[2].x)+(vs[2].x-vs[1].x)*(vs[0].y-vs[2].y);
        for(let y=c.rect.y;y<c.rect.y+c.rect.h;y++)for(let x=c.rect.x;x<c.rect.x+c.rect.w;x++) {
          const a=((vs[1].y-vs[2].y)*(x+.5-vs[2].x)+(vs[2].x-vs[1].x)*(y+.5-vs[2].y))/denom;
          const b=((vs[2].y-vs[0].y)*(x+.5-vs[2].x)+(vs[0].x-vs[2].x)*(y+.5-vs[2].y))/denom;
          if(a< -1e-7||b< -1e-7||a+b>1+1e-7)continue;
          const at=ws[0].clone().multiplyScalar(a).addScaledVector(ws[1],b).addScaledVector(ws[2],1-a-b);
          texels.set((y*size+x)*4,{at,normal,floor:c.mesh.material.name==='floor'});
        }
      }
    }
    let target=null,color=new THREE.Color(),alpha=0;
    const renderer={toneMapping:THREE.NoToneMapping,autoClear:true,xr:{enabled:false},
      getRenderTarget:()=>target,setRenderTarget:t=>{target=t;},getClearColor:c=>c.copy(color),getClearAlpha:()=>alpha,
      setClearColor:(c,a)=>{color.set(c);alpha=a;},clear:()=>{},
      render(scene,camera){
        if(camera.isPerspectiveCamera)return;
        const u=scene.overrideMaterial.uniforms;
        assert.equal(u.scale.value,1,'half-float targets contain raw irradiance');
        const sample={source:u.source.value,origin:u.origin.value,range:u.reach.value,weight:u.weight.value,cd:u.cd.value,
          normal:u.emitterNormal.value,axis:u.axis.value,outer:u.outer.value,inner:u.inner.value,
          visibilityWeight:u.visibilityWeight.value};
        for(const [i,t]of texels){
          const e=F.sampleValue([sample],t.at,t.normal,()=>1,0,1);
          values[i]+=e.irradiance;values[i+1]+=e.irradiance/(16*u.fillStrength.value);values[i+3]=1;
        }
      },readRenderTargetPixels(t,x,y,w,h,raw){for(let i=0;i<raw.length;i++)raw[i]=THREE.DataUtils.toHalfFloat(values[i]);}};
    const result=await P.renderPage({plan:p,scene:root},renderer,mine,size,light,options,atlas,{deferBounce:true,deferSumEncoding:true});
    pages.push({...result,charts:mine,texels});
  }
  const scale=await P.encodeSumPages(pages,size);
  for(const p of pages)P.filterCharts(p.bytes,p.charts,size);
  const codes=pages.flatMap(p=>[...p.texels].filter(([i,t])=>t.floor&&p.bytes[i]>0).map(([i])=>p.bytes[i]));
  const range=[Math.min(...codes),Math.max(...codes)];
  assert.ok(range[1]>=96,`floor only reaches ${range[1]} codes at scale ${scale}`);
  assert.ok(range[1]<255,'headroom avoids clipping the floor');
  close(Math.log2(scale)*16,Math.round(Math.log2(scale)*16),1e-10);
  const reader=B.bakeLayout(atlas,options,input,packed.ownership,{[light.device]:{scale}});
  assert.equal(reader.entries[light.device].scale,scale);
  assert.equal(B.lightKey(atlas,{...light,scale},packed.slots[light.device],{}),
    B.lightKey(atlas,{...light,scale:scale*2},packed.slots[light.device],{}),'output scale is not an input key');
  return {range,scale};
}
check('rendered_sum_scale_coarse_cones_and_four_ceiling_downlights',async()=>{
  const spots=[[-3,-3],[3,-3],[-3,3],[3,3]].map(([x,y],i)=>
    fixture('s'+i,'spot',{at:[x,y,7.9],aim:[x,y,0],cone_deg:60,softness:.3}));
  const points=[[-3,-3],[3,-3],[-3,3],[3,3]].map(([x,y],i)=>fixture('p'+i,'point',{at:[x,y,7.9]}));
  for(const [name,rows,expected]of [['coarse cones',spots,[1,224]],['four ceiling downlights',points,[27,96]]]) {
    const {range,scale}=await renderedSumScene(rows);
    assert.deepEqual(range,expected,'rendered half-float percentile uses the expected floor codes');
    console.log(`       C3 ${name}: floor codes ${range.join('..')}, scale ${scale}`);
  }
});
check('sum_percentile_is_entity_wide_quantised_and_ignores_padding',async()=>{
  const make=(values)=>({charts:[{rect:{x:0,y:0,w:values.length,h:1}}],bytes:new Uint8Array(values.length*4),irradiance:new Uint16Array(values.length)});
  const a=make(Array(200).fill(4)),b=make(Array(200).fill(16));
  for(const [page,value]of [[a,4],[b,16]])for(let i=0;i<page.bytes.length;i+=4){page.bytes[i+3]=255;page.irradiance[i/4]=THREE.DataUtils.toHalfFloat(value);}
  b.irradiance[0]=THREE.DataUtils.toHalfFloat(1000); // one hot texel is outside the 99.5th percentile
  a.bytes[3]=0;a.irradiance[0]=THREE.DataUtils.toHalfFloat(60000); // padding is never a receiver
  const scale=await P.encodeSumPages([a,b],200);
  assert.equal(scale,2**(Math.ceil(Math.log2(16*1.25)*16)/16));
  assert.equal(b.bytes[0],255,'intentional outlier clipping');
  assert.ok(a.bytes[4]<b.bytes[4],'all pages use one entity scale');
  const small=make([4,4,Infinity]);small.bytes.fill(255);
  small.irradiance.set([THREE.DataUtils.toHalfFloat(4),THREE.DataUtils.toHalfFloat(4),0x7c00]);
  assert.equal(await P.encodeSumPages([small],3),2**(Math.ceil(Math.log2(4*1.25)*16)/16),'overflow does not set the scale of a small entity');
  assert.equal(small.bytes[8],255,'overflow still clamps to full output');
  // A whole 2048 page must not hide a main-thread scale search stall.
  const page=make(Array(2048).fill(1));page.charts[0].rect.h=2048;
  page.bytes=new Uint8Array(2048*2048*4);page.irradiance=new Uint16Array(page.bytes.length/4);
  for(let i=0;i<page.bytes.length;i+=4){page.bytes[i+3]=255;page.irradiance[i/4]=THREE.DataUtils.toHalfFloat(4);}
  const start=performance.now();let last=start,longest=0,yields=0;
  await P.encodeSumPages([page],2048,async()=>{
    longest=Math.max(longest,performance.now()-last);yields++;
    await new Promise(resolve=>setImmediate(resolve));last=performance.now();
  });
  longest=Math.max(longest,performance.now()-last);
  const ms=performance.now()-start;
  assert.ok(yields>1,'large pages yield while selecting and encoding the scale');
  assert.ok(longest<500,`scale blocked the main thread for ${longest} ms`);
  console.log(`       sum 2048 page scale/encode ${ms.toFixed(2)} ms total, ${longest.toFixed(2)} ms longest block (${yields} yields)`);
});
check('mixed_point_and_legacy_ranking_share_photometric_units',()=>{
  const {p,options,atlas}=physicalRoom();
  const fixtureLight=group([fixture('p','point',{at:[0,0,4]})]);
  const legacy={device:'legacy',absolute:true,at:[0,0,4],range:18};
  const reached=awaitImportReach.reachLights(atlas.room,[legacy,fixtureLight]);
  for(const id of reached[0].receivingCharts)close(reached[1].scores[id]/reached[0].scores[id],1,.01);
  const alone=B.bakeLayout(atlas,options,[legacy]);
  const mixed=B.bakeLayout(atlas,options,[legacy,fixtureLight]);
  close(mixed.slots.legacy.assignments[0].score,alone.slots.legacy.assignments[0].score);
  const again=awaitImportReach.reachLights(atlas.room,[legacy,fixtureLight]);
  assert.equal(again[0].receivers,reached[0].receivers,'nested fixture sweep retains legacy cache');
  assert.equal(again[1].receivers,mixed.lights[1].receivers,'group signature retains its result');
});
check('spot_slot_is_kind_1_and_cone_matches_live',async()=>{
  needFixtures();const l=group([fixture('spot','spot',{aim:[0,0,0],cone_deg:60,softness:.3})]);assert.equal(l.kind,1);
  const u=M.lightmapUniforms(1,1,{fixtures:true});M.setLightSource(u,0,0,V(...l.emitters[0].position),6,1,l);
  const data=u.lmTints.value.image.data;
  const {createRealLights}=await import(file('static/twin/live/real_lights.js'));
  const scene=new THREE.Scene(),rig=createRealLights({scene,tier:'high'});
  const emitter=resolveEmitters(fixtureLayout([fixture('spot','spot',{aim:[0,0,0],cone_deg:60,softness:.3})]),
    {'light.test':{state:'on'}},plan)[0];
  rig.update([{device:emitter.fixture_id,emitter,at:emitter.at,position:V(...emitter.position),
    distance:emitter.range*FT,intensity:1,rgb:[255,255,255]}],[0,0,0]);
  const spot=scene.children.find(o=>o.isSpotLight&&o.intensity>0);assert.ok(spot,'production live spot selected');
  for(const angle of [0,10,21,25,30,40]){
    const c=Math.cos(angle*Math.PI/180),outer=Math.cos(spot.angle),inner=Math.cos(spot.angle*(1-spot.penumbra));
    const t=Math.max(0,Math.min(1,(c-outer)/(inner-outer)));
    close(F.coneWindow(c,outer,inner),t*t*(3-2*t));
    close(F.coneWindow(c,data[15],data[16]),t*t*(3-2*t),1e-5);
  }
  rig.stop();
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
  close(two/one,3,.02);
  const rendered=await renderProbe(l),scale=l.scale;
  const stored=F.sampleValue(samples,at,n,()=>1,3,scale);
  const byte=Math.round(stored.value*255);close(F.decodeIrradiance(byte/255,scale),one+two,scale/128);
  close(F.decodeIrradiance(rendered.bytes[0]/255,scale),one+two,scale/128);
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
check('fire_pit_bakes_from_emitters_with_flame_tint',()=>{
  const p={buildings:[],site:{fire_pit:[{id:'gas',at:[5,5],fuel:'gas',entity:'switch.fire',radius:2}]}};
  const lights=RT.bakeLights({markers:[]},null,p);assert.equal(lights.length,1);assert.equal(lights[0].device,'switch.fire');
  assert.equal(lights[0].emitters[0].fire_pit,true);assert.deepEqual(lights[0].emitters[0].rgb,[255,154,60]);
  const packed={banks:[{charts:[]}],slots:{}};
  const bare=M.chartLightmapUniforms(0,packed,[],4,[[]]),pit=M.chartLightmapUniforms(0,packed,lights,4,[[]]);
  assert.equal(pit.lmTints.value.image.height,bare.lmTints.value.image.height);
  assert.equal(pit.lmTints.value.userData.fixtureRows,false);
  const variant=u=>{const m=new THREE.MeshStandardMaterial();M.patchLightmaps([m],{banks:[new THREE.DataArrayTexture()]},u);return m.customProgramCacheKey();};
  assert.equal(variant(pit),variant(bare),'pit-only house uses legacy shader variant');
  assert.equal(lights[0].emitters[0].intensityScale,.5);
  assert.equal(lights[0].kind,0);assert.equal(lights[0].emitters[0].shape,'point');
  assert.ok(energy(lights[0],V(5*FT,0,-5*FT),V(0,1,0)).irradiance>0,'patio gets fire light');
});
check('mixed_pit_samples_carry_half_strength_and_share',()=>{
  const p={buildings:[],site:{fire_pit:[{id:'gas',at:[5,5],fuel:'gas',entity:'switch.fire',radius:2}]}};
  const layout={markers:[],light_fixtures:{'switch.fire':[fixture('p','point',{at:[0,0,4]})]}};
  const light=RT.bakeLights(layout,null,p)[0],samples=F.bakeSamples(p,light);
  const pit=samples.filter(s=>light.emitters[s.emitter].fire_pit),point=samples.filter(s=>!light.emitters[s.emitter].fire_pit);
  close(pit.reduce((n,s)=>n+s.cd*s.weight,0)/point.reduce((n,s)=>n+s.cd*s.weight,0),.5);
});
check('repeated_fixture_pages_reuse_one_cube_and_dispose_all_owned_resources',async()=>{
  for(let i=0;i<3;i++) {
    const result=await renderProbe(group([panel(),fixture('p','point')]));
    assert.ok(result.sources.length>=32);
    assert.deepEqual(result.resources,{targets:2,disposedTargets:2,geometries:1,disposedGeometries:1});
  }
});
check('room_fill_uniform_submission_and_cpu_decode_for_rect_and_sum',async()=>{
  needFixtures();for(const l of [group([panel()]),group([panel(),fixture('p','point')])]){
    const {bytes}=await renderProbe(l);
    const fill=P.roomFills([{bytes,charts:[{room:0,rect:{x:0,y:0,w:1,h:1},mesh:{material:{color:new THREE.Color('white')}}}]}],1,l);
    assert.ok(fill[0]>0);
  }
});
check('default_panel_room_fill_does_not_clip_and_restores_strength',async()=>{
  const l=group([{...panel(),at:[0,0,8]}]),at=V(0,0,0),normal=V(0,1,0),{bytes}=await renderProbe(l,[],at,normal);
  assert.ok(bytes[1]>0&&bytes[1]<255,`G ${bytes[1]} should not clip`);
  const e=energy(l,at,normal),strength=F.fillStrength(l);
  close(bytes[1]/255*16*strength,e.irradiance,16*strength/255);
  const charts=[{room:0,rect:{x:0,y:0,w:1,h:1},mesh:{material:{color:new THREE.Color('white')}}}];
  close(P.roomFills([{bytes,charts}],1,l)[0],Math.min(4,bytes[1]*.08)*16/255*strength);
  const old={absolute:true,at:[0,0,4],range:18};assert.equal(F.fillStrength(old),1);
});
check('fixture_material_initialises_ltc_once_without_house_view',async()=>{
  const {RectAreaLightUniformsLib:lib}=await import('three/addons/lights/RectAreaLightUniformsLib.js');
  const init=lib.init,names=['LTC_FLOAT_1','LTC_FLOAT_2','LTC_HALF_1','LTC_HALF_2'];
  const saved=names.map(name=>THREE.UniformsLib[name]);let calls=0;
  try {
    for(const name of names)delete THREE.UniformsLib[name];
    lib.init=()=>{calls++;init.call(lib);};
    const a=M.lightmapUniforms(1,1,{fixtures:true}),b=M.lightmapUniforms(1,1,{fixtures:true});
    for(const name of names)assert.ok(THREE.UniformsLib[name]?.isDataTexture,name+' is ready');
    assert.equal(calls,1,'materials on any page initialise the tables once');
    a.lmTints.value.dispose();b.lmTints.value.dispose();
  } finally {lib.init=init;names.forEach((name,i)=>THREE.UniformsLib[name]=saved[i]);}
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
  for(const areas of [0,8])for(const clearcoat of [false,true]) {
    const budget=samplerBudget(shader.fragmentShader,areas,clearcoat);
    assert.ok(budget.count<=16,JSON.stringify(budget));
    assert.equal(budget.names.filter(n=>['ltc_1','ltc_2','lmLtc1','lmLtc2'].includes(n)).length,2,JSON.stringify(budget));
    if(clearcoat)assert.ok(budget.source.includes('clearcoatSpecularDirect+=lmTint*p.w*coatFresnel'));
    console.log(`       ${areas} live area slots, clearcoat ${clearcoat}: ${budget.count} declared samplers`);
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
    # main when this compatibility ruling was verified; keep the proof stable after landing.
    main_baseline = 'b5b98280bf508f117672f07681db034ff3e932dd'
    paths = ['static/twin/bake/' + name for name in
             ['baker.js', 'bake_pass.js', 'reach.js', 'atlas.js', 'lightmap_material.js']]
    sources = {path: subprocess.check_output(['git', 'show', main_baseline + ':chauffeur/' + path],
               cwd=harness.ROOT, encoding='utf-8') for path in paths}
    harness.DRIVER = 'const mainSources = ' + json.dumps(sources) + ';\n' + DRIVER
    sys.exit(1 if harness.run() else 0)
