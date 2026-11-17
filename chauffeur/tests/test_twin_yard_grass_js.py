"""Execute the real grass field, standard/matcap shaders and mounted editor under Node."""
import sys
from pathlib import Path

from test_twin_untouched_house_js import COMMON
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = COMMON + r"""
const Y=await import(file('static/twin/twin_yard.js'));
const B=await import(file('static/twin/yard_grass.js'));
const T=await import(file('static/twin/twin_tiers.js'));
const {groundAt,inPolygon,edgeDistance}=await import(file('static/twin/twin_ground.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createUnlit}=await import(file('static/twin/unlit.js'));
const {createPointSnap}=await import(file('static/twin/editor/point_snap.js'));
const {occluders}=await import(file('static/twin/bake/bake_pass.js'));
const {disposeObject}=await import(file('static/twin/twin_library.js'));
const lawn=new THREE.MeshStandardMaterial({color:'#58783b'});
const make=()=>({units:'ft',buildings:[{id:'b',position:[14,14],rotation:25,base:0,
 levels:[{id:'L',elevation:0,ceiling:8,outline:square(0,0,24)}],rooms:[],walls:[],
 porches:[{polygon:square(0,-8,24,8),floor:0}]}],materials:{},site:{lot:square(0,0,110,100),
 terraces:[{id:'pad',polygon:square(65,15,14),height:3,blend:8}],
 hardscape:[{id:'patio',polygon:square(10,62,22,12)},
 {id:'drive',kind:'driveway',polygon:square(0,40,18,12)},
 {id:'deck',kind:'deck',polygon:square(75,38,12)},
 {id:'walk',kind:'path',points:[[38,66],[48,78],[65,74]],width:4,corner:'rounded',radius:3,edging:'curb'}],
 beds:[{id:'bed',polygon:square(85,8,14,9)}],
 pool:{id:'pool',polygon:square(66,60,24,16),coping:1,depth:4,
 features:[{id:'spa',kind:'spa',polygon:square(90,66,8),depth_in:36}]},
 fire_pit:{id:'pit',shape:'round',at:[45,48],radius:3},edges:[],planting:[],furniture:[]}});
const buildField=(p,t='high',k=kit())=>B.buildGrass(p,k,t,lawn);
const positions=f=>{const a=f.mesh?.instanceMatrix.array||[],out=[];for(let i=0;i<f.instances;i++)out.push([a[i*16+12],-a[i*16+14],a[i*16+13]]);return out;};
const rows=f=>{const a=f.mesh?.instanceMatrix.array||[],m=new Map();for(let i=0;i<f.instances;i++)m.set(`${a[i*16+12]}:${a[i*16+14]}`,Array.from(a.subarray(i*16,i*16+16)));return m;};
const release=f=>{f.mesh?.geometry.dispose();f.mesh?.material.dispose();};
const compile=(m,kind='standard')=>{const s={uniforms:{},vertexShader:THREE.ShaderLib[kind].vertexShader,
 fragmentShader:THREE.ShaderLib[kind].fragmentShader};m.onBeforeCompile(s,{});return s;};
await test('low_has_no_field_no_draw_and_never_touches_a_clock',async()=>{
 const p=make(),f=buildField(p,'low');assert.equal(f.instances,0);assert.equal(f.draws,0);assert.equal(f.mesh,null);assert.equal(f.animated,false);
 f.update(50);f.update(500);assert.equal(f.mesh,null);
 const y=await Y.buildYard(p,kit(),'low');assert.equal(y.group.children.filter(o=>o.userData.yardPart==='grass').length,0);
 assert.equal(y.group.userData.grass.instances,0);
});
await test('tier_caps_cover_density_and_large_lots_are_bounded',()=>{
 for(const tier of ['medium','high','max']){
  const f=buildField(make(),tier);assert.ok(f.instances>20000);assert.ok(f.instances<=T.TIERS[tier].lawnBlades);assert.equal(f.draws,1);assert.equal(f.regions,1);
  console.log(`GRASS tier=${tier} instances=${f.instances} draws=${f.draws} regions=${f.regions} blades=${f.instances*3}`);release(f);
  const huge={buildings:[],site:{lot:square(-1000,-1000,10000)}};const g=buildField(huge,tier);
  assert.ok(g.instances> T.TIERS[tier].lawnBlades*.98);assert.ok(g.instances<=T.TIERS[tier].lawnBlades);assert.equal(g.draws,1);release(g);
  const narrow=buildField({site:{lot:square(0,0,1000000,2)}},tier);assert.ok(narrow.instances<=T.TIERS[tier].lawnBlades);release(narrow);
 }
});
await test('pad_stair_treads_walls_and_outdoor_building_stairs_cover_the_lawn',()=>{
 const p={buildings:[{position:[2,2],levels:[{elevation:0,outline:square(0,0,8)}],
 stairs:[{from:[8,10],to:[18,10],width:4}]}],site:{lot:square(0,0,60),terraces:[
 {polygon:square(20,20,10),height:2,blend:0,edges:[{edge:'sharp',stair:{riser_in:7,tread_in:11}},
 {edge:'sharp',wall:{thickness_in:16,cap:{thickness_in:2,overhang_in:2}}}]}]}};
 const covers=B.grassCovers(p),f=buildField(p,'medium');
 for(const point of [[25,18],[15,12],[30.1,25]])assert.ok(covers.some(c=>inPolygon(c.polygon,...point)),String(point));
 for(const [x,y] of positions(f))assert.ok(!covers.some(c=>inPolygon(c.polygon,x,y)));release(f);
});
await test('existing_fringe_remains_and_total_hook_counts_both_draws',async()=>{
 const p=make();p.site.edges=[{points:[[1,1],[10,1]]}];
 for(const tier of ['low','medium','high','max']){
  const y=(await Y.buildYard(p,kit(),tier)).group,f=y.userData.grass,draws=y.children.filter(o=>o.userData.yardPart==='grass');
  assert.equal(f.draws,draws.length);assert.equal(f.instances,draws.reduce((n,o)=>n+o.count,0));
  assert.ok(f.instances<=T.TIERS[tier].lawnBlades);
  assert.equal(draws.filter(o=>o.material.name==='edge grass').length,T.TIERS[tier].edgeGrass?1:0);
  assert.ok(draws.every(o=>o.userData.yardGrass));
 }
});
await test('every_root_is_in_the_lot_and_clear_of_every_cover_with_margin',()=>{
 const p=make(),f=buildField(p),covers=B.grassCovers(p);
 assert.ok(covers.length>=11,'building, porch, pad, paving, driveway, deck, swept path, bed, pool, spa, pit');
 for(const [x,y] of positions(f)){
  assert.ok(inPolygon(p.site.lot,x,y));
  for(const {polygon,margin} of covers){assert.ok(!inPolygon(polygon,x,y));
   for(let i=0;i<polygon.length;i++)assert.ok(edgeDistance([x,y],polygon[i],polygon[(i+1)%polygon.length])>=margin-1e-5);
  }
 }
 const concave={buildings:[],site:{lot:[[0,0],[20,0],[20,8],[8,8],[8,20],[0,20]]}};
 const g=buildField(concave);assert.ok(positions(g).every(([x,y])=>inPolygon(concave.site.lot,x,y)));release(f);release(g);
});
await test('roots_follow_sampled_slopes_in_feet_and_geometry_is_bent_strips',()=>{
 const p=make(),f=buildField(p);let slopes=0;
 for(const [x,y,z] of positions(f)){const h=groundAt(p,x,y);assert.ok(Math.abs(z-(h-.04))<2e-5);if(h>.05)slopes++;}
 assert.ok(slopes>100);const g=f.mesh.geometry;assert.equal(g.attributes.position.count,21);assert.equal(g.index.count,45);
 const a=g.attributes.position;assert.ok(a.getZ(6)!==a.getZ(0));assert.ok(g.attributes.normal.getY(0)>.9);
 assert.ok(a.getY(6)*.68*.3048>=.06);assert.ok(a.getY(20)*1.1*.3048<=.121);release(f);
});
await test('placements_repeat_byte_for_byte_and_moving_one_cover_only_changes_local_cells',()=>{
 const p=make(),a=buildField(p),b=buildField(structuredClone(p));assert.deepEqual(a.mesh.instanceMatrix.array,b.mesh.instanceMatrix.array);
 const changed=structuredClone(p);changed.site.beds[0].polygon=square(82,8,14,9);const c=buildField(changed);
 const old=rows(a),next=rows(c);let local=0;
 for(const [key,row] of old){if(next.has(key))assert.deepEqual(next.get(key),row);else{assert.ok(row[12]>81&&row[12]<100&&-row[14]>7&&-row[14]<18);local++;}}
 for(const [key,row] of next)if(!old.has(key)){assert.ok(row[12]>81&&row[12]<100&&-row[14]>7&&-row[14]<18);local++;}
 assert.ok(local>0);release(a);release(b);release(c);
});
await test('material_identity_allows_lawn_tints_and_known_grass_but_rejects_other_surfaces',async()=>{
 for(const id of ['gravel','mulch','paving','material-user','snow','fake-grass-stone']){
  const k=kit();k.materials.lawn={asset:id,color:'#00ff00'};const f=buildField(make(),'high',k);assert.equal(f.instances,0,id);
 }
 for(const ref of [{color:'#aa0000'},{asset:'leafy_grass'},{asset:'grass'}])assert.ok(B.grassLawn({materials:{lawn:ref}}));
 const p=make();p.materials.lawn={id:'paving',color:'#00ff00'};const y=await Y.buildYard(p,kit(),'medium');assert.equal(y.group.userData.grass.instances,0);
});
await test('opaque_standard_material_patches_real_shaders_throws_and_clones',()=>{
 const f=buildField(make()),m=f.mesh.material;assert.ok(m.isMeshStandardMaterial);assert.equal(m.transparent,false);assert.equal(m.alphaTest,0);assert.equal(m.opacity,1);assert.equal('transmission' in m,false);
 const s=compile(m),c=m.clone();assert.equal(c.onBeforeCompile,m.onBeforeCompile);assert.equal(c.customProgramCacheKey(),m.customProgramCacheKey());
 assert.equal(compile(c).uniforms.grassTime,s.uniforms.grassTime);
 for(const [stage,anchor] of [['vertexShader','#include <begin_vertex>'],['fragmentShader','#include <color_fragment>'],['fragmentShader','#include <roughnessmap_fragment>'],['fragmentShader','#include <normal_fragment_begin>']]){
  const bad={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};bad[stage]=bad[stage].replace(anchor,'');assert.throws(()=>m.onBeforeCompile(bad,{}),/Grass shader missing anchor/);
 }
 f.update(72);assert.equal(s.uniforms.grassTime.value,72);assert.equal(compile(c).uniforms.grassTime.value,72);c.dispose();release(f);
});
await test('distance_thinning_is_continuous_per_clump_and_widens_distant_blades',()=>{
 // Execute the shader's exact scalar fade formula at a fixed seed, including its
 // transition interval, rather than merely checking that a distance token exists.
 const f=buildField(make()),s=compile(f.mesh.material).vertexShader;
 const expression=name=>{const match=s.match(new RegExp('float '+name+' = ([^;]+);'));assert.ok(match);return match[1];};
 const smoothstep=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);},mix=(a,b,t)=>a+(b-a)*t;
 const keep=new Function('grassDistance','mix','smoothstep','return '+expression('grassKeep'));
 const fade=new Function('grassSeed','grassKeep','smoothstep','return '+expression('grassScale'));
 assert.equal(fade(.5,keep(0,mix,smoothstep),smoothstep),1);assert.equal(fade(.5,keep(100,mix,smoothstep),smoothstep),0);
 let transitions=0;for(let d=0;d<60;d+=.05){const v=fade(.5,keep(d,mix,smoothstep),smoothstep);if(v>0&&v<1)transitions++;}assert.ok(transitions>10);
 assert.ok(s.includes('transformed.x *= 1.0 + .65*'));release(f);
});
await test('unlit_and_viewing_clones_keep_shape_wind_colour_and_opaque_contract',()=>{
 const f=buildField(make()),m=f.mesh.material,unlit=createUnlit(),root=new THREE.Group();root.add(f.mesh);unlit.apply(root);
 assert.ok(f.mesh.material.isMeshMatcapMaterial);const s=compile(f.mesh.material,'matcap');assert.equal(s.uniforms.grassTime,m.userData.grassUniforms.grassTime);
 f.update(123);assert.equal(s.uniforms.grassTime.value,123);unlit.restore();assert.equal(f.mesh.material,m);unlit.dispose();release(f);
});
await test('field_never_merges_bakes_casts_or_blocks_a_raycast',()=>{
 const f=buildField(make()),root=new THREE.Group();root.add(f.mesh);G.mergeStatic(root);assert.equal(root.children[0],f.mesh);assert.equal(f.mesh.userData.merged,undefined);
 assert.equal(A.atlasMesh(f.mesh),false);assert.equal(occluders({scene:root}).children.length,0);assert.equal(f.mesh.receiveShadow,true);assert.equal(f.mesh.castShadow,false);
 root.updateMatrixWorld(true);const r=new THREE.Raycaster(new THREE.Vector3(50,10,-50),new THREE.Vector3(0,-1,0));assert.deepEqual(r.intersectObject(root,true),[]);assert.equal(f.mesh.layers.isEnabled(31),false);release(f);
});
await test('point_snap_never_enumerates_blade_instances_or_exposes_a_draggable_host',()=>{
 const f=buildField(make()),root=new THREE.Group();root.add(f.mesh);root.scale.setScalar(.3048);
 const camera=new THREE.PerspectiveCamera(50,4/3,.01,1000);camera.position.set(15,25,-15);camera.lookAt(15,0,-15);
 f.mesh.getMatrixAt=()=>{throw new Error('Grass must never enter per-instance snapping');};
 let features=0;const snap=createPointSnap({scene:root,camera,renderer3:{domElement:new Element()},pick:()=>null},()=>make(),{onFeatures:()=>features++});
 assert.equal(snap.pick({clientX:400,clientY:300}),null);assert.equal(features,0);assert.equal(f.mesh.userData.pieceId,undefined);release(f);
});
await test('mounted_clock_hook_editor_picking_reuse_and_disposal',async()=>{
 location.search='?test=1';const p=make(),v=await mountTwin(new Element(),{plan:p,kit:kit(),tier:'medium',bake:false});
 try{
  const yard=()=>v.scene.getObjectByName('yard'),f=yard().userData.grass,m=f.mesh;
  assert.deepEqual(v.grassInfo(),{tier:'medium',instances:f.instances,draws:1,regions:1,animated:true});
  const u=m.material.userData.grassUniforms.grassTime;v.render();assert.ok(u.value>0);
  // A real projected editor pick above open lawn must still reach open ground.
  v.setCameraState({position:[15,25,-15],target:[15,0,-15]});assert.equal(v.pick(400,300),null);
  const next=structuredClone(p);next.buildings[0].materials={siding:{id:'door'}};await v.rebuild(next);assert.equal(yard().userData.grass,f);
  let gd=0,md=0;m.geometry.addEventListener('dispose',()=>gd++);m.material.addEventListener('dispose',()=>md++);
  const dry=structuredClone(next);dry.materials.lawn={id:'paving'};await v.rebuild(dry);assert.equal(v.grassInfo().instances,0);assert.ok(gd>=1);assert.ok(md>=1);
  await v.rebuild(p);const last=yard().userData.grass.mesh;let disposed=0;last.geometry.addEventListener('dispose',()=>disposed++);last.material.addEventListener('dispose',()=>disposed++);v.dispose();assert.ok(disposed>=2);
 }finally{v.dispose();}
 const low=await mountTwin(new Element(),{plan:p,kit:kit(),tier:'low',bake:false});try{low.render();assert.deepEqual(low.grassInfo(),{tier:'low',instances:0,draws:0,regions:0,animated:false});}finally{low.dispose();}
});
await test('grass_tracks_lawn_map_tint_and_uv_changes_without_per_frame_work',async()=>{
 const src=new THREE.MeshStandardMaterial({color:'#356b26'}),m=B.grassMaterial(src),shader=compile(m);
 const map=new THREE.Texture();map.repeat.set(.125,.125);src.map=map;src.color.set('#864433');src.dispatchEvent({type:'materialparamschange'});
 assert.equal(shader.uniforms.grassMap.value,map);assert.equal(shader.uniforms.grassHasMap.value,1);assert.equal(shader.uniforms.grassTint.value,src.color);
 assert.deepEqual(shader.uniforms.grassUvMatrix.value.elements,map.matrix.elements);
 let freed=0;m.addEventListener('dispose',()=>freed++);m.dispose();assert.equal(freed,1);map.dispose();src.dispose();
});
await test('high_budget_build_cost_is_printed',()=>{
 const p=make(),empty={buildings:[],site:{lot:square(0,0,110,100)}};
 // Warm JIT, then report both useful covered/sloped yard and full-budget cost.
 release(buildField(p));const samples=[];for(let i=0;i<5;i++){const start=performance.now(),f=buildField(p);samples.push(performance.now()-start);release(f);}
 const start=performance.now(),f=buildField(empty);const ms=performance.now()-start;
 console.log(`GRASS_BUILD high covered_ms=${samples.map(n=>n.toFixed(2)).join(',')} full_ms=${ms.toFixed(2)} full_instances=${f.instances}`);
 assert.ok([...samples].sort((a,b)=>a-b)[2]<100,'high-budget median stays below 100ms');
 assert.ok(ms<100,'full-budget build stays below 100ms');release(f);
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    sys.exit(code or 0)
