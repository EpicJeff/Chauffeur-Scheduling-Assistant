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
const P=await import(file('static/twin/paver_layout.js'));
const {pathSurfacePolygons}=await import(file('static/twin/path_shapes.js'));
const paverPlan=()=>({buildings:[],site:{lot:square(0,0,40,30),hardscape:[{id:'pavers',kind:'path',points:[[5,15],[35,15]],width:5,pavers:{...P.PAVER_DEFAULTS}}]}});
await test('paver_covers_follow_joint_fill_and_cap_fallback_warns_once',async()=>{
 const p=paverPlan(),h=p.site.hardscape[0],layout=P.paverLayout(h);
 assert.deepEqual(B.grassCovers(p),layout.pavers.map(p=>({polygon:p.polygon,margin:0,paver:true})));
 for(const joint of ['gravel','sand','none']){
  h.pavers.joint=joint;assert.deepEqual(B.grassCovers(p),pathSurfacePolygons(h).map(polygon=>({polygon,margin:.4})));
 }
 delete h.pavers;assert.deepEqual(B.grassCovers(p),pathSurfacePolygons(h).map(polygon=>({polygon,margin:.4})));
 const refused={...h,points:[[0,15],[1000,15]],width:30,pavers:{...P.PAVER_DEFAULTS,length_in:2,width_in:2,gap_in:0}};
 p.site.hardscape=[refused];let warnings=0;const warn=console.warn;console.warn=()=>warnings++;
 try{
  await Y.buildYard(p,kit(),'low');const covers=B.grassCovers(p);assert.deepEqual(covers,pathSurfacePolygons(refused).map(polygon=>({polygon,margin:.4})));
  assert.equal(B.jointClumps(p,1).length,0);assert.equal(warnings,1,'yard and lawn share a single refusal');
 }finally{console.warn=warn;}
});
await test('paver_field_and_joint_roots_fit_joints_share_one_draw_and_obey_budget',()=>{
 const p=paverPlan(),layout=P.paverLayout(p.site.hardscape[0]);
 for(const tier of ['low','medium','high','max']){
  const f=buildField(p,tier);assert.ok(f.instances<=T.TIERS[tier].lawnBlades);assert.equal(f.draws,tier==='low'?0:1);
  if(tier==='low'){assert.equal(f.jointInstances,0);continue;}
  assert.ok(f.jointInstances>0);assert.equal(f.mesh.count,f.instances);
  const a=f.mesh.instanceMatrix.array,spread=Math.hypot(a[0],a[2]);
  for(let i=0;i<f.instances;i++){
   const x=a[i*16+12],y=-a[i*16+14];
    if(i<f.instances-f.jointInstances){
    for(const {polygon} of layout.pavers){assert.ok(!inPolygon(polygon,x,y));assert.ok(polygon.every((v,j)=>edgeDistance([x,y],v,polygon[(j+1)%polygon.length])>=B.PAVER_ROOT_MARGIN-2e-6));}
   }else{
    assert.ok(inPolygon(p.site.lot,x,y));assert.ok(layout.joints.some(([v,w])=>edgeDistance([x,y],v,w)<1e-6));
    assert.ok(.13*Math.hypot(a[i*16],a[i*16+2])<=layout.jointWidth/2+1e-6);assert.ok(Math.abs(a[i*16+5]-.6)<1e-6);
    for(const {polygon} of layout.pavers)assert.ok(!inPolygon(polygon,x,y));
   }
  }
  assert.deepEqual(a.slice(-f.jointInstances*16),B.jointClumps(p,spread).slice(0,f.jointInstances*16));
  if(tier==='high'){
   const m=new THREE.Matrix4(),v=new THREE.Vector3(),g=f.mesh.geometry;
   for(let i=0;i<f.instances;i++){
    const x=a[i*16+12],y=-a[i*16+14];if(x<4||x>36||y<12||y>18)continue;
    f.mesh.getMatrixAt(i,m);
    for(let j=0;j<g.attributes.position.count;j++){
     v.fromBufferAttribute(g.attributes.position,j).applyMatrix4(m);if(v.y<=1/12)continue;
     // Lawn blades lean over a stone's edge (owner: grass right up to the paver);
     // the squeezed joint clumps still stay inside their joint.
     if(i<f.instances-f.jointInstances)continue;
     for(const q of layout.pavers)assert.ok(!inPolygon(q.polygon,v.x,-v.z),`joint blade at ${x},${y} enters paver`);
    }
   }
  }
  release(f);
 }
 const n=paverPlan();n.site.hardscape[0].pavers.gap_in=.49;assert.equal(B.jointClumps(n,1).length,0);
 const dry=kit();dry.materials.lawn={asset:'paving'};assert.equal(buildField(p,'high',dry).jointInstances,0);
 const capped=T.TIERS.medium.lawnBlades;
 try{T.TIERS.medium.lawnBlades=20;const f=buildField(p,'medium');assert.ok(f.instances<=20);assert.ok(f.jointInstances>0);release(f);}finally{T.TIERS.medium.lawnBlades=capped;}
});
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
  const huge={buildings:[],site:{lot:square(-1000,-1000,10000),terraces:[{polygon:square(-900,-900,9000),height:10,blend:8}]}};const g=buildField(huge,tier);
  assert.ok(g.instances> T.TIERS[tier].lawnBlades*.98);assert.ok(g.instances<=T.TIERS[tier].lawnBlades);assert.equal(g.draws,1);release(g);
  const narrow=buildField({site:{lot:square(0,0,1000000,2)}},tier);assert.ok(narrow.instances<=T.TIERS[tier].lawnBlades);release(narrow);
 }
});
await test('blades_are_broad_enough_to_close_the_canopy_on_high',()=>{
 // Needle blades left the ground showing between them; a lawn's blades overlap
 // (user's comparison with their TwinMotion lawn, 2026-11-17).
 const lot={buildings:[],site:{lot:square(0,0,100)}},f=buildField(lot,'high'),g=f.mesh.geometry;
 const p=g.attributes.position,ix=g.index.array,v=i=>new THREE.Vector3().fromBufferAttribute(p,i);let face=0;
 for(let i=0;i<ix.length;i+=3)face+=new THREE.Triangle(v(ix[i]),v(ix[i+1]),v(ix[i+2])).getArea();
 const a=f.mesh.instanceMatrix.array;let scale=0;for(let i=0;i<f.instances;i++)scale+=a[i*16+5];
 // Face area grows with height (y scale); blade width does not change with it.
 // The needles came to about .85 ft2 per ft2 of lawn; the ribbons about 1.9.
 const perFoot=face*scale/(100*100);
 assert.ok(face/5>.016,`one blade face ${face/5} ft2`);assert.ok(perFoot>1.6,`${perFoot} ft2 of blade face per ft2 of lawn`);
 release(f);
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
await test('every_root_is_in_the_lot_or_its_skirt_and_clear_of_every_cover_with_margin',()=>{
 const p=make(),f=buildField(p),covers=B.grassCovers(p);
 assert.equal(covers.length,10,'building, porch, paving, driveway, deck, swept path, bed, pool, spa, pit; pads grow lawn');
 const off=(lot,x,y)=>inPolygon(lot,x,y)?0:Math.min(...lot.map((a,i)=>edgeDistance([x,y],a,lot[(i+1)%lot.length])));
 const a=f.mesh.instanceMatrix.array;let inside=0,skirt=0,rim=0,far=0;
 for(let i=0;i<f.instances;i++){
  const x=a[i*16+12],y=-a[i*16+14],d=off(p.site.lot,x,y);
  // User, 2026-11-17: the lawn reaches the lot line; past it a 4 ft skirt shortens.
  assert.ok(d<4);if(d)skirt++;else inside++;
  if(!d&&Math.min(x,110-x,y,100-y)<.3){rim++;assert.ok(a[i*16+5]>=.68-1e-6,'full height at the lot line');}
  if(d>3.5){far++;assert.ok(a[i*16+5]<1.1*.4,'short at the end of the skirt');}
  for(const {polygon,margin} of covers){assert.ok(!inPolygon(polygon,x,y));
   for(let i=0;i<polygon.length;i++)assert.ok(edgeDistance([x,y],polygon[i],polygon[(i+1)%polygon.length])>=margin-1e-5);
  }
 }
 assert.ok(inside>100000&&skirt>10000&&rim>1000&&far>500,`${inside} ${skirt} ${rim} ${far}`);
 const concave={buildings:[],site:{lot:[[0,0],[20,0],[20,8],[8,8],[8,20],[0,20]]}};
 const g=buildField(concave),notch=positions(g).filter(([x,y])=>x>8.5&&x<11.5&&y>8.5&&y<11.5);
 assert.ok(positions(g).every(([x,y])=>off(concave.site.lot,x,y)<4));
 assert.ok(notch.length>50,'the skirt follows a concave lot');
 assert.equal(positions(g).filter(([x,y])=>x>12.1&&y>12.1).length,0,'nothing past the skirt in the notch');release(f);release(g);
});
await test('a_fence_on_the_lot_line_stands_in_grass_and_the_budget_is_what_grows',()=>{
 const p={buildings:[],site:{lot:square(0,0,100),fence:[{id:'f',height:5,polyline:[[-1,0],[-1,100]]},{id:'g',height:5,polyline:[[50,10],[50,90]]}]}};
 assert.deepEqual(B.grassCovers(p),[],'a fence clears no lawn');
 const f=buildField(p);let west=0,east=0,mid=0;
 for(const [x,y] of positions(f)){if(y<10||y>90)continue;if(x>-1.6&&x<-1)west++;if(x>-1&&x<-.4)east++;if(Math.abs(x-50)<.3)mid++;}
 assert.ok(west>400&&east>400&&mid>400,`${west} ${east} ${mid}`);release(f);
 // Half the lot is paved: the lawn that is left still gets the tier's whole budget.
 for(const tier of ['medium','high','max']){
  const half={buildings:[],site:{lot:square(0,0,600),hardscape:[{id:'h',polygon:square(0,0,600,300)}]}},g=buildField(half,tier);
  assert.ok(g.instances>T.TIERS[tier].lawnBlades*.85,`${tier} ${g.instances}`);assert.ok(g.instances<=T.TIERS[tier].lawnBlades);release(g);
 }
});
await test('roots_follow_sampled_slopes_in_feet_and_geometry_is_bent_strips',()=>{
 const p=make(),f=buildField(p);let slopes=0;
 for(const [x,y,z] of positions(f)){const h=groundAt(p,x,y);assert.ok(Math.abs(z-(h-.04))<2e-5);if(h>.05)slopes++;}
 assert.ok(slopes>100);const g=f.mesh.geometry;assert.equal(g.attributes.position.count,25);assert.equal(g.index.count,45);
 // Vertex 4 is the shortest blade's tip, vertex 24 the tallest's; a tip leans off its root.
 const a=g.attributes.position;assert.ok(Math.hypot(a.getX(4)-(a.getX(0)+a.getX(1))/2,a.getZ(4)-(a.getZ(0)+a.getZ(1))/2)>.05);assert.ok(g.attributes.normal.getY(0)>.9);
 assert.ok(a.getY(4)*.68*.3048>=.06);assert.ok(a.getY(24)*1.1*.3048<=.121);release(f);
});
await test('pad_tops_blends_and_ground_outside_blends_grow_at_their_own_height_and_fit_bounds',()=>{
 const p={buildings:[],site:{lot:square(0,0,80),terraces:[2,4,6,10].map((height,i)=>
  ({id:'pad'+i,polygon:square(8+i*17,28,10),height,blend:5}))}};
 assert.deepEqual(B.grassCovers(p),[]);
 const f=buildField(p),hits=Array(4).fill(0);let slopes=0,outside=0;
 for(const [x,y,z] of positions(f)){
  const h=groundAt(p,x,y);assert.ok(Math.abs(z-(h-.04))<2e-5);
  p.site.terraces.forEach((pad,i)=>{if(inPolygon(pad.polygon,x,y)){hits[i]++;assert.ok(Math.abs(z-(pad.height-.04))<2e-5);}});
  if(h>0&&!p.site.terraces.some(pad=>inPolygon(pad.polygon,x,y)))slopes++;
  if(y>43&&y<44){assert.equal(h,0);outside++;}
  const v=new THREE.Vector3(x,z,-y);assert.ok(f.mesh.boundingBox.containsPoint(v));
  assert.ok(f.mesh.boundingSphere.containsPoint(v.clone().add(new THREE.Vector3(0,.5,0))));
 }
 assert.ok(hits.every(n=>n>100));assert.ok(slopes>100);assert.ok(outside>100);
 assert.ok(f.mesh.boundingBox.max.y>=10.5);release(f);
});
await test('blades_clear_both_sides_of_pad_wall_caps_and_stairs_even_at_maximum_spread_and_wind',()=>{
 const p={buildings:[],site:{lot:square(0,0,240),terraces:[{id:'pad',polygon:square(80,80,80),height:10,blend:0,
  edges:[{edge:'sharp',stair:{riser_in:7,tread_in:11,treads:true}},
   ...Array.from({length:3},()=>({edge:'sharp',wall:{material:'block',thickness_in:16,cap:{thickness_in:2,overhang_in:4}}}))]}]}};
 const f=buildField(p,'medium'),a=f.mesh.geometry.attributes.position,m=new THREE.Matrix4(),v=new THREE.Vector3();
 const covers=B.grassCovers(p),bounds=covers.map(c=>({x0:Math.min(...c.polygon.map(p=>p[0]))-2,x1:Math.max(...c.polygon.map(p=>p[0]))+2,
  y0:Math.min(...c.polygon.map(p=>p[1]))-2,y1:Math.max(...c.polygon.map(p=>p[1]))+2}));let high=0,low=0;
 assert.ok(Math.abs(Math.hypot(f.mesh.instanceMatrix.array[0],f.mesh.instanceMatrix.array[2])-2)<1e-5,'coarsest spread');
 for(let i=0;i<f.instances;i++){
  f.mesh.getMatrixAt(i,m);const x=m.elements[12],y=-m.elements[14];
  if(!bounds.some(b=>x>=b.x0&&x<=b.x1&&y>=b.y0&&y<=b.y1))continue;
  if(m.elements[13]>1)high++;else low++;
  for(let j=0;j<a.count;j++){
   // Full gust envelope at the coarsest spread; roots remain fixed. The shader's
   // far-distance widening is left out: it starts 25 m away, where what it adds
   // is under a pixel, and clearing it left a bare foot around every wall.
   const t=f.mesh.geometry.attributes.grassShape.getX(j);
   v.fromBufferAttribute(a,j);v.applyMatrix4(m);
   for(const sx of [-1,1])for(const sy of [-1,1])for(const c of covers)
    assert.ok(!inPolygon(c.polygon,v.x+sx*.043*1.4*t*t,-v.z+sy*.027*1.4*t*t),`blade at ${x},${y} enters pad solid`);
  }
 }
 assert.ok(high>100&&low>100);release(f);
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
 for(const [id,entry,wants] of [
  ['material-owned',{params:{grass:true}},true],['material-owned',{params:{grass:false}},false],
  ['material-owned',{params:{}},false],['material-owned',{source_id:'leafy_grass'},true],
  ['leafy_grass',{params:{grass:false}},false],['grass',{params:{grass:false}},false],
  ['lawn',{},true],['grass',{},true],['leafy_grass',{},true],
  ['material-owned',{source_id:'leafy_grass',params:{grass:false}},false]]){
  const k={materials:{lawn:{id}},manifest:{[id]:entry}},f=buildField(make(),'medium',k);
  assert.equal(B.grassLawn(k),wants,JSON.stringify([id,entry]));assert.equal(f.instances>0,wants);release(f);
 }
 // The server reads the JSON, the page reads the constants: one list, kept equal here.
 const R=await import(file('static/twin/material_rules.js')),D=JSON.parse(readFileSync(new URL(file('static/twin/material_defaults.json')),'utf8'));
 assert.deepEqual(D,{grass_ids:R.GRASS_IDS,grass_sources:R.GRASS_SOURCES});
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
 // Nothing thins inside 30 m, where the whole house is normally framed.
 for(const seed of [.05,.5,.95])assert.equal(fade(seed,keep(30,mix,smoothstep),smoothstep),1);
 let transitions=0;for(let d=0;d<130;d+=.05){const v=fade(.5,keep(d,mix,smoothstep),smoothstep);if(v>0&&v<1)transitions++;}assert.ok(transitions>10);
 assert.ok(s.includes('transformed.xz *= 1.0 + 1.2*'));release(f);
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
await test('neutral_tint_uses_imported_green_texture_colour',async()=>{
 const src=new THREE.MeshStandardMaterial({color:'#ffffff'}),m=B.grassMaterial(src),s=compile(m);
 src.map=new THREE.DataTexture(new Uint8Array([40,130,30,255]),1,1);src.map.colorSpace=THREE.SRGBColorSpace;
 src.dispatchEvent({type:'materialparamschange'});
 assert.equal(s.uniforms.grassMap.value,src.map);assert.equal(s.uniforms.grassHasMap.value,1);
 const tint=s.uniforms.grassTint.value;
 // Execute the shader's lawn multiplier on the actual texture's sample.
 const statement=s.fragmentShader.match(/if \(grassHasMap > .5\) lawn \*= ([^;]+);/)[1];
 assert.equal(statement,'texture2D(grassMap, vGrassUv.xy).rgb');
 const pixel=src.map.image.data,c=new THREE.Color().setRGB(pixel[0]/255,pixel[1]/255,pixel[2]/255,THREE.SRGBColorSpace).multiply(tint);
 assert.ok(c.g>c.r*3&&c.g>c.b*3);assert.equal(tint.getHexString(),'ffffff');
 m.dispose();src.map.dispose();src.dispose();
});
await test('existing_material_watcher_grows_and_drops_lawn_blades_without_reload',async()=>{
 const {watchMaterialCatalogue}=await import(file('static/twin/material_watch.js'));
 const p={buildings:[],materials:{lawn:{id:'material-photo'}},site:{lot:square(0,0,30)}},k=kit();
 k.manifest={'material-photo':{kind:'material',household:true,revision:1,maps:{},params:{grass:false,tint:'#ffffff'}}};
 const v=await mountTwin(new Element(),{plan:p,kit:k,tier:'medium',bake:false});let revision=1;
 const watcher=watchMaterialCatalogue(v,{api:async()=>({ok:true,status:200,json:async()=>({revision,entries:structuredClone(k.manifest)})})});
 try{
  await watcher.check();assert.equal(v.grassInfo().instances,0);
  for(const grass of [true,false,true]){
   k.manifest['material-photo']={...k.manifest['material-photo'],revision:++revision,params:{grass,tint:'#ffffff'}};
   await watcher.check();assert.equal(v.grassInfo().instances>0,grass);v.render();
  }
 }finally{watcher.stop();v.dispose();}
});
await test('grass_switch_never_enters_material_or_atlas_keys',async()=>{
 const {materialKey}=await import(file('static/twin/twin_library.js'));
 const p={buildings:[],materials:{lawn:{id:'material-photo'}},site:{lot:square(0,0,20),
  terraces:[{polygon:square(5,5,10),height:4,blend:3}]}},k=kit();
 k.manifest={'material-photo':{kind:'material',household:true,revision:1,maps:{},params:{grass:false,tint:'#56783a'}}};
 const off=await Y.buildYard(p,k,'medium'),key=materialKey({id:'material-photo'},'lawn','medium',k.manifest);
 const atlas=A.buildAtlas(off.group,p,layout);
 k.manifest['material-photo'].params.grass=true;
 const on=await Y.buildYard(p,k,'medium');
 assert.equal(materialKey({id:'material-photo'},'lawn','medium',k.manifest),key);
 assert.ok(on.group.userData.grass.instances>0);assert.equal(off.group.userData.grass.instances,0);
 assert.equal(A.buildAtlas(on.group,p,layout).key,atlas.key);
 disposeObject(off.group);disposeObject(on.group);
});
await test('paver_path_build_cost_is_printed',()=>{
 const p={buildings:[],site:{lot:square(0,0,110,100),hardscape:[{id:'timed',kind:'path',points:[[20,50],[80,50]],width:5,
  pavers:{layout:'grid',length_in:24,width_in:24,gap_in:3,rotation:0,edge:'whole',joint:'grass'}}]}};
 release(buildField(p));const samples=[];
 for(let i=0;i<7;i++){const q=structuredClone(p),start=performance.now(),f=buildField(q);samples.push(performance.now()-start);release(f);}
 console.log(`PAVER_GRASS_BUILD high 60ft_ms=${samples.map(n=>n.toFixed(2)).join(',')} median_ms=${[...samples].sort((a,b)=>a-b)[3].toFixed(2)}`);
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
