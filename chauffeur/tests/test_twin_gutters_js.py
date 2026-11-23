"""Pure gutter runs and corner-only downspouts, executed under Node."""
import json
import os
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const G=await import(file('static/twin/gutters.js'));
const E=await import(file('static/twin/sky/eave_streams.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {allPorches}=await import(file('static/twin/twin_generator.js'));
const {inPolygon,segmentIntersection}=await import(file('static/twin/twin_ground.js'));
const {roofMesh}=await import(file('static/twin/twin_roof.js'));
const FT=.3048,clone=structuredClone,near=(a,b,e=1e-4)=>assert.ok(Math.abs(a-b)<e,`${a} != ${b}`);
const rect=(x0,y0,x1,y1)=>[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
function house(length=30,kind='gable',poly=rect(0,0,length,20)){
 const b={id:'b',position:[0,0],base:0,rotation:0,levels:[{id:'L1',elevation:0,ceiling:10,outline:poly}],rooms:[],
  walls:poly.map((a,i)=>({id:'w'+i,from:a,to:poly[(i+1)%poly.length],exterior:true,height:10,thickness:.5,level:'L1'})),openings:[],
  roof:{sections:[],extensions:[]},roofs:[]};
 const p={units:'ft',buildings:[b],site:{}};roof(p,'r',[0,0,length,20],kind);return p;
}
function roof(p,id,bounds,kind='hip',extra={}){
 const s={id,roof:id,kind,ridge:'x',pitch:6,plate:10,overhang:0,level:'L1',rect:bounds,
  plane_edges:{y0:0,x1:1,y1:2,x0:3},...extra};
 const low=s.low_side,settings=['y0','x1','y1','x0'].map(side=>
  kind==='shed'?(side===low?'sloped':'gable'):kind==='gable'&&side[0]===s.ridge?'gable':'sloped');
 const r={id,area:rect(...bounds),overhang:s.overhang,edges:settings.map(setting=>({setting,gutter:setting==='sloped'}))};
 s.gutters=Object.fromEntries(['y0','x1','y1','x0'].filter((side,i)=>settings[i]==='sloped').map(side=>[side,true]));
 p.buildings[0].roofs.push(r);p.buildings[0].roof.sections.push(s);return s;
}
const calc=p=>{const runs=G.gutterRuns(p);return {runs,spouts:G.downspouts(p,runs)};};
const local=(p,v)=>{const b=p.buildings[0],a=(b.rotation||0)*Math.PI/180,x=v[0]/FT-b.position[0],y=-v[2]/FT-b.position[1];
 return [Math.cos(a)*x+Math.sin(a)*y,-Math.sin(a)*x+Math.cos(a)*y,v[1]/FT-(b.base||0)];};
const atCorner=(p,s,poly=p.buildings[0].levels[0].outline)=>poly.some(c=>Math.hypot(...local(p,s.top).slice(0,2).map((v,i)=>v-c[i]))<.1);
function override(p,index,values){const b=p.buildings[0],s=b.roof.sections[0];b.roofs[0].edges[index].downspouts=values;
 s.downspouts={...(s.downspouts||{}),[['y0','x1','y1','x0'][index]]:values};}
// Independent acceptance oracle: local quadrant occupancy of the whole house.
function unionCorners(b,height){
 const polys=[...(b.levels||[]).filter(l=>(l.elevation||0)<=height).map(l=>l.outline),
  ...allPorches(b).map(p=>p.polygon)].filter(p=>p?.length>=3);
 const points=polys.flat(),edges=polys.flatMap(p=>p.map((a,i)=>[a,p[(i+1)%p.length]]));
 for(let i=0;i<edges.length;i++)for(let j=i+1;j<edges.length;j++){const at=segmentIntersection(...edges[i],...edges[j]);if(at)points.push(at);}
 const count=at=>[-.3,.3].reduce((n,x)=>n+[-.3,.3].filter(y=>polys.some(p=>inPolygon(p,at[0]+x,at[1]+y))).length,0);
 return points.map(at=>({at,count:count(at)})).filter(c=>c.count===1||c.count===3);
}
function dropPoint(s){
 const vertical=s.path.slice(1).map((at,i)=>({at,above:s.path[i]}))
  .filter(v=>Math.hypot(v.at[0]-v.above[0],v.at[2]-v.above[2])<1e-5)
  .sort((a,b)=>(b.above[1]-b.at[1])-(a.above[1]-a.at[1]));
 return vertical[0]?.above||s.top;
}
function attachedPorch(kind){
 const p=house(),b=p.buildings[0];b.roofs[0].edges.forEach(e=>e.gutter=false);b.roof.sections[0].gutters={};
 const s=roof(p,'porchroof',[5,-8,25,0],kind,{ridge:'y',plate:8,pitch:3,overhang:1});
 s.gutters={};b.roofs.at(-1).edges.forEach(e=>e.gutter=false);
 b.porches=[{id:'p',gutter:true,polygon:rect(5,-8,25,0),floor:0,columns:[{at:[5,-8]},{at:[25,-8]}]}];return p;
}
for(const kind of ['hip','gable'])await test('test_'+kind+'_porch_uses_union_front_corners',()=>{
 for(const rotation of [0,37]){const p=attachedPorch(kind);p.buildings[0].rotation=rotation;p.buildings[0].position=[12.3,-7.7];
  const {runs,spouts}=calc(p),junctions=runs.flatMap(r=>r.corners).filter(c=>Math.abs(local(p,c.at)[1])<.1);
  assert.ok(junctions.length>=2);assert.ok(junctions.every(c=>!c.convex),'porch-to-house junctions are inner');
  assert.ok(spouts.length);assert.ok(spouts.every(s=>local(p,s.top)[1]<-7&&s.mount==='post'&&!s.flags.length));}
});
await test('test_upper_outline_ignores_exterior_flags_and_checks_windows',()=>{
 const poly=[[0,0],[40,0],[40,20],[20,20],[20,40],[0,40]],p=house(40,'hip',poly),b=p.buildings[0];
 b.levels.push({id:'L2',elevation:11,ceiling:10,outline:poly});
 b.walls.push(...b.walls.map(w=>({...clone(w),id:w.id+'up',level:'L2',exterior:false})));
 b.walls.forEach(w=>w.exterior=false);b.roof.sections=[];b.roofs=[];
 roof(p,'a',[0,0,40,20],'hip',{plate:21,level:'L2'});roof(p,'b',[0,0,20,40],'hip',{plate:21,level:'L2'});
 b.openings=[{id:'window',wall:'w0up',at:1,width:2,sill:3,head:7,kind:'window'}];
 const {runs,spouts}=calc(p);assert.ok(runs.flatMap(r=>r.corners).some(c=>!c.convex));
 assert.ok(spouts.length>=4&&spouts.every(s=>s.mount==='wall'));
 assert.ok(spouts.every(s=>Math.hypot(local(p,s.top)[0]-20,local(p,s.top)[1]-20)>.5));
 const front=spouts.filter(s=>s.edge.roof==='a'&&s.edge.edge===0);assert.ok(front.length);assert.ok(front.every(s=>local(p,s.top)[0]>1));
 const flagged=calc(p);b.walls.forEach(w=>w.exterior=true);assert.deepEqual(calc(p),flagged);
});
await test('test_corner_search_matches_mounting_box_beyond_overhang',()=>{
 const p=house(),b=p.buildings[0],s=b.roof.sections[0];s.rect=[-.8,-.8,30.8,20.8];b.roofs[0].area=rect(...s.rect);
 const {runs,spouts}=calc(p);assert.equal(runs.flatMap(r=>r.corners).length,4);
 assert.ok(spouts.every(s=>s.mount==='wall'&&!s.flags.length));
});
await test('test_outline_segments_match_one_long_wall_and_its_window',()=>{
 const p=house(30,'gable',[[0,0],[15,0],[30,0],[30,20],[0,20]]),b=p.buildings[0];
 b.walls=b.walls.filter(w=>w.id!=='w0'&&w.id!=='w1');
 b.walls.push({id:'front',from:[0,0],to:[30,0],exterior:false,height:10,level:'L1',thickness:.5});
 b.openings=[{id:'window',wall:'front',at:1,width:2,sill:3,head:7,kind:'window'}];
 near(local(p,calc(p).spouts.find(s=>s.edge.edge===0).top)[0],30);
});
await test('test_rejected_outside_corner_retries_non_inner_run_end',()=>{
 const p=house(),b=p.buildings[0];b.roof.sections=[];b.roofs=[];roof(p,'short',[0,0,15,8],'shed',{low_side:'y0'});
 b.openings=[{id:'window',wall:'w0',at:1,width:2,sill:3,head:7,kind:'window'}];
 const {spouts}=calc(p);assert.equal(spouts.length,1);near(local(p,spouts[0].top)[0],15);
 assert.ok(spouts[0].flags.includes('no-outside-corner'));
});
await test('test_mounted_non_inner_end_precedes_unmounted_outside_corner',()=>{
 const p=house(),b=p.buildings[0];b.levels[0].ceiling=8;b.walls.forEach(w=>w.height=8);
 b.walls.push({id:'tall-front',level:'L1',from:[5,0],to:[30,0],height:10,exterior:false});
 b.roof.sections=[];b.roofs=[];roof(p,'short',[0,0,15,8],'shed',{low_side:'y0'});
 const s=calc(p).spouts[0];assert.equal(s.mount,'wall');near(local(p,s.top)[0],15);
 assert.ok(s.flags.includes('no-outside-corner'));
});
await test('test_negative_eave_edge_is_null',()=>{
 const p=house();p.buildings[0].roof.sections[0].plane_edges.y0=-1;
 assert.equal(E.extractEaves(p).find(e=>e.side==='y0').edge,null);
});
await test('test_offset_eave_endpoints_dedupe_by_matched_house_corner',()=>{
 const p=house(20,'hip'),runs=G.gutterRuns(p),r=runs[0],side=r.segments.find(s=>s.edge===1);
 for(const field of ['a','b'])if(Math.abs(local(p,side[field])[1])<.01)side[field][2]-=.1*FT;
 const ss=G.downspouts(p,runs);assert.equal(ss.length,3);
 const keys=ss.map(s=>{const q=local(p,dropPoint(s));return rect(0,0,20,20).map((at,i)=>({i,d:Math.hypot(q[0]-at[0],q[1]-at[1])})).sort((a,b)=>a.d-b.d)[0].i;});
 assert.equal(new Set(keys).size,ss.length);
});
await test('test_all_inner_ends_hang_at_end_farthest_from_inner_vertex',()=>{
 const poly=[[0,0],[30,0],[30,30],[20,30],[20,10],[10,10],[10,30],[0,30]],p=house(30,'hip',poly),b=p.buildings[0];
 b.roofs=[];b.roof.sections=[];roof(p,'notch',[10,10,19.1,18],'shed',{low_side:'y0',plate:12,overhang:.2});
 const {runs,spouts}=calc(p);assert.equal(runs.length,1);assert.equal(spouts.length,1);
 const s=spouts[0];assert.equal(s.mount,'hang');assert.ok(s.flags.includes('inner-end')&&s.flags.includes('hang'));
 near(local(p,s.top)[0],19.3);
});
await test('test_clipped_run_end_is_not_a_wall_fallback',()=>{
 const p=house(40),b=p.buildings[0];b.roof.sections=[];b.roofs=[];roof(p,'short',[5,0,25,8],'shed',{low_side:'y0'});
 b.levels.push({id:'block',elevation:0,ceiling:20,outline:rect(4,-1,10,1)});
 const {spouts}=calc(p);assert.equal(spouts.length,1);near(local(p,spouts[0].top)[0],25);
 assert.equal(spouts[0].mount,'wall');assert.deepEqual(spouts[0].flags,['no-outside-corner']);
});
await test('test_smaller_upper_storey_uses_its_corners_above_lower_roof',()=>{
 for(const kind of ['flat','gable'])for(const ground of [rect(0,0,30,20),[[0,0],[30,0],[30,20],[5,20],[5,5],[0,5]]]){
  const p=house(30,kind,ground),b=p.buildings[0],upper=rect(5,5,25,15);
  b.roofs[0].edges.forEach(e=>e.gutter=false);b.roof.sections[0].gutters={};
  b.levels.push({id:'L2',elevation:11,ceiling:10,outline:upper});
  b.walls.push(...upper.map((from,i)=>({id:'up'+i,from,to:upper[(i+1)%4],level:'L2',height:10,exterior:false,thickness:.5})));
  roof(p,'upper',[5,5,25,15],'gable',{level:'L2',plate:21});
  const {runs,spouts}=calc(p);assert.equal(runs.length,2);assert.equal(spouts.length,2);
  assert.ok(spouts.every(s=>s.mount==='wall'&&s.outlet.lands==='roof'&&!s.flags.length&&atCorner(p,s,upper)));
  assert.ok(runs.every(r=>r.corners.length===2&&r.corners.every(c=>c.convex)));
 }
});
await test('test_all_hangs_are_flagged_stubs_with_no_kickout',()=>{
 const p=house();p.buildings[0].roof.sections[0].plate=22;
 for(const s of calc(p).spouts){assert.equal(s.mount,'hang');assert.ok(s.flags.includes('hang')&&s.flags.includes('stub'));
  assert.equal(s.path.length,2);near(s.top[1]-s.outlet.at[1],.5*FT);
  near(s.top[0],s.outlet.at[0]);near(s.top[2],s.outlet.at[2]);}
});
await test('test_flush_cross_gable_clipped_end_is_not_a_wall_fallback',()=>{
 const p=house(40),b=p.buildings[0];b.roofs=[];b.roof.sections=[];
 roof(p,'main',[0,0,40,20],'gable',{overhang:1});roof(p,'cross',[15,0,25,10],'gable',{ridge:'y',overhang:1});
 b.roofs[1].edges.forEach(e=>e.gutter=false);b.roof.sections[1].gutters={};
 b.openings=[{id:'window',wall:'w0',at:1,width:2,sill:3,head:7,kind:'window'}];
 const {runs,spouts}=calc(p),left=runs.find(r=>r.segments[0].edge===0&&r.segments.every(s=>Math.max(s.a[0],s.b[0])<20*FT));
 assert.ok(left);const s=spouts.find(s=>s.run===left.id);assert.ok(s);
 assert.equal(s.mount,'hang');assert.ok(s.flags.includes('stub'));
 assert.ok(Math.abs(local(p,s.top)[0]-14)>.5,'flush roof cut is not a wall fallback');
});
await test('test_corner_dedupe_across_runs_prefers_larger_share_then_run_id',()=>{
 for(const longer of [false,true]){
  const p=house(longer?40:20,'hip'),run=G.gutterRuns(p)[0],front=run.segments.find(s=>s.edge===0),left=run.segments.find(s=>s.edge===3);
  p.site.hardscape=[{id:'drive',kind:'driveway',polygon:rect(-5,16,1,25)}];
  const runs=[{...clone(run),id:'a-front',segments:[front],length:longer?40:20},
   {...clone(run),id:'z-left',segments:[left],length:20}];
  const ss=G.downspouts(p,runs),shared=ss.filter(s=>atCorner(p,s,[[0,0]]));assert.equal(shared.length,1);
  assert.equal(shared[0].run,longer?'z-left':'a-front');assert.ok(runs.every(r=>ss.some(s=>s.run===r.id)));
  assert.deepEqual(G.downspouts(p,[...runs].reverse()),ss);
 }
});
await test('test_nearly_parallel_outline_wall_keeps_opening_checks',()=>{
 const p=house(),b=p.buildings[0];b.walls[0].to=[30,.1];b.walls[0].exterior=false;
 b.openings=[{id:'window',wall:'w0',at:1,width:2,sill:3,head:7,kind:'window'}];
 near(local(p,calc(p).spouts.find(s=>s.edge.edge===0).top)[0],30);
});
await test('test_same_roof_hip_wrap_joins_at_2_04_inches',()=>{
 for(const authored of [true,false]){
  const p=house(20),b=p.buildings[0],s=b.roof.sections[0];s.overhang=1;s.ends={x0:'gable',x1:'hip'};s.pitches={x1:8.04};
  b.roofs[0].overhang=1;b.roofs[0].edges[1]={setting:'sloped',gutter:true};s.gutters.x1=true;
  if(!authored)delete b.roofs;
  const {runs,spouts}=calc(p);assert.equal(runs.length,1);assert.equal(runs[0].segments.length,3);
  const heights=runs[0].segments.map(s=>s.a[1]);near((Math.max(...heights)-Math.min(...heights))/FT*12,2.04,1e-3);
  assert.equal(spouts.length,2);assert.ok(spouts.every(s=>s.share===.5));
 }
 const p=house(20),b=p.buildings[0];b.roofs=[];b.roof.sections=[];
 roof(p,'first',[0,0,10,8],'shed',{low_side:'y0'});roof(p,'second',[10.2,0,20,8],'shed',{low_side:'y0',plate:10.17});
 assert.equal(G.gutterRuns(p).length,2,'different roofs still use 2 inches');
});
await test('test_orphan_run_links_to_adjacent_outlet_and_contributes_catchment',()=>{
 const p=house(40,'hip'),whole=G.gutterRuns(p)[0];override(p,0,[0,1]);override(p,3,[]);
 const runs=[{...clone(whole),id:'front',segments:whole.segments.filter(s=>s.edge===0),length:40},
  {...clone(whole),id:'left',segments:whole.segments.filter(s=>s.edge===3),length:20}];
 const ss=G.downspouts(p,runs);assert.equal(ss.length,2);
 const receiving=ss.find(s=>atCorner(p,s,[[0,0]])),other=ss.find(s=>s!==receiving);
 assert.equal(runs[1].drainsTo,receiving.id);assert.ok(!('drainsTo' in runs[0]));
 near(receiving.share,2/3);near(other.share,1/3);near(ss.reduce((n,s)=>n+s.share,0),1);
 assert.deepEqual(G.downspouts(p,runs),ss,'repeat placement does not accumulate catchment');
 override(p,3,[1]);const next=G.downspouts(p,runs);assert.ok(next.some(s=>s.source==='override'&&s.edge.edge===3));
 assert.ok(!('drainsTo' in runs[1]),'owned outlets clear stale links');
});
await test('test_orphan_prefers_adjacent_lower_outlet_before_nearest_higher_one',()=>{
 const p=house(40,'hip'),whole=G.gutterRuns(p)[0];override(p,0,[0]);override(p,2,[1]);override(p,3,[]);
 const piece=(edge,id,delta)=>{const segments=clone(whole.segments.filter(s=>s.edge===edge));for(const s of segments)for(const at of [s.a,s.b])at[1]+=delta*FT;
  return {...clone(whole),id,segments,length:edge===3?20:40};};
 const runs=[piece(0,'a-higher',1),piece(2,'z-lower',-1),piece(3,'orphan',0)],ss=G.downspouts(p,runs);
 assert.equal(runs[2].drainsTo,ss.find(s=>s.run==='z-lower').id);
});
await test('test_orphan_uses_nearest_outlet_when_none_is_adjacent',()=>{
 const p=house();override(p,0,[]);const {runs,spouts}=calc(p),front=runs.find(r=>r.segments[0].edge===0);
 assert.equal(spouts.length,1);assert.equal(front.drainsTo,spouts[0].id);
});
await test('test_no_outlet_building_gets_one_explicit_emergency_stub',()=>{
 const p=house();override(p,0,[]);override(p,2,[]);
 const {runs,spouts}=calc(p);assert.equal(spouts.length,1);assert.equal(spouts[0].mount,'hang');
 assert.ok(spouts[0].flags.includes('stub')&&spouts[0].flags.includes('no-outlet'));
 assert.ok(runs.every(r=>spouts.some(s=>s.run===r.id)||spouts.some(s=>s.id===r.drainsTo)));
 assert.deepEqual(p.buildings[0].roofs[0].edges[0].downspouts,[]);assert.deepEqual(p.buildings[0].roofs[0].edges[2].downspouts,[]);
});
await test('test_live_reordered_cover_positions_keep_storey_corners',()=>{
 const p=house(30),b=p.buildings[0],upper=rect(5,5,25,15);b.roofs[0].edges.forEach(e=>e.gutter=false);b.roof.sections[0].gutters={};
 b.levels.push({id:'L2',elevation:11,ceiling:10,outline:upper});
 b.walls.push(...upper.map((from,i)=>({id:'up'+i,from,to:upper[(i+1)%4],level:'L2',height:10,exterior:false})));
 roof(p,'upper',[5,5,25,15],'gable',{level:'L2',plate:21});
 const mesh=roofMesh(b.roof.sections),triangles=[];for(let i=0;i<mesh.positions.length;i+=9)triangles.push(Array.from(mesh.positions.slice(i,i+9)));
 triangles.sort((a,b)=>Math.max(b[2],b[5],b[8])-Math.max(a[2],a[5],a[8]));
 const coverPositions=triangles.slice(1).flat(),surfaces=new Map([['b',{...mesh,sections:b.roof.sections,coverPositions,eaveAttachments:[]}]]);
 const expected=G.gutterRuns(p);assert.ok(expected.every(r=>r.corners.length===2&&r.corners.every(c=>c.convex)));
 assert.deepEqual(G.gutterRuns(p,surfaces),expected);
});
await test('test_authored_override_wins_corner_claim_over_automatic',()=>{
 const p=house(20,'hip'),whole=G.gutterRuns(p)[0];override(p,3,[1]);
 const runs=[{...clone(whole),id:'a-auto',segments:whole.segments.filter(s=>s.edge===0),length:20},
  {...clone(whole),id:'z-override',segments:whole.segments.filter(s=>s.edge===3),length:20}];
 const ss=G.downspouts(p,runs),shared=ss.filter(s=>atCorner(p,s,[[0,0]]));assert.equal(shared.length,1);
 assert.equal(shared[0].source,'override');assert.equal(shared[0].run,'z-override');
 assert.equal(ss.filter(s=>s.source==='override').length,1);
});
await test('test_stacked_corner_claims_have_separate_receiving_floor_bands',()=>{
 const p=house(20,'hip'),b=p.buildings[0];b.roof.sections[0].overhang=2;b.roofs[0].overhang=2;
 b.levels.push({id:'L2',elevation:11,ceiling:10,outline:rect(0,0,20,20)});
 b.walls.push(...b.walls.map(w=>({...clone(w),id:w.id+'up',level:'L2',exterior:false})));
 roof(p,'upper',[0,0,20,20],'hip',{level:'L2',plate:21});
 const {runs,spouts}=calc(p);assert.equal(runs.length,2);assert.equal(spouts.length,6);
 for(const r of runs){const ss=spouts.filter(s=>s.run===r.id);assert.equal(ss.length,3);assert.ok(ss.every(s=>s.outlet.lands===(r.segments[0].roof==='upper'?'roof':'grass')));}
});
await test('test_corner_claim_is_shared_by_faces_with_different_receiving_surfaces',()=>{
 const p=house(40,'hip'),b=p.buildings[0];
 b.levels.push({id:'L2',elevation:11,ceiling:10,outline:rect(0,0,40,20)});
 b.walls.push(...b.walls.map(w=>({...clone(w),id:w.id+'up',level:'L2',exterior:false})));
 Object.assign(b.roof.sections[0],{level:'L2',plate:21});
 const canopy=roof(p,'canopy',[40,-.2,50,10],'shed',{low_side:'x1',plate:10});
 canopy.gutters={};b.roofs[1].edges.forEach(e=>e.gutter=false);
 const {runs,spouts}=calc(p),corner=ss=>ss.filter(s=>atCorner(p,s,[[40,0]]));
 assert.equal(runs.length,1);assert.equal(corner(spouts).length,1,'the two faces share one physical corner claim');
 near(local(p,corner(spouts)[0].top)[2],20.96);
 const whole=runs[0];override(p,0,[1]);override(p,1,[0]);
 const split=[{...clone(whole),id:'front',segments:whole.segments.filter(s=>s.edge===0),length:40},
  {...clone(whole),id:'right',segments:whole.segments.filter(s=>s.edge===1),length:20}];
 assert.equal(corner(G.downspouts(p,split)).length,1,'corner identity also spans separate runs');
});
await test('test_joined_offset_same_roof_ends_never_get_mid_run_fallbacks',()=>{
 const p=house(40),b=p.buildings[0];b.roofs=[];b.roof.sections=[];
 roof(p,'r',[10,0,20,8],'shed',{low_side:'y0'});
 const second=roof(p,'part',[20.25,0,30,8],'shed',{low_side:'y0',plate:10+2.5/12});
 second.roof='r';b.roofs.pop();
 b.openings=[10,30].map((at,i)=>({id:'window'+i,kind:'window',wall:'w0',at,width:2,sill:3,head:7}));
 const {runs,spouts}=calc(p);assert.equal(runs.length,1);assert.equal(runs[0].segments.length,2);
 assert.equal(spouts.length,1);
 const x=local(p,spouts[0].top)[0];assert.ok(Math.abs(x-10)<.1||Math.abs(x-30)<.1,`fallback must be at a free end, got ${x}`);
 assert.ok(spouts[0].flags.includes('hang'));
});
await test('test_colliding_authored_overrides_record_the_merged_request',()=>{
 const p=house(20,'hip'),whole=G.gutterRuns(p)[0];override(p,0,[0]);override(p,3,[.85]);
 const runs=[{...clone(whole),id:'a-front',segments:whole.segments.filter(s=>s.edge===0),length:20},
  {...clone(whole),id:'z-left',segments:whole.segments.filter(s=>s.edge===3),length:20}];
 const ss=G.downspouts(p,runs);assert.equal(ss.length,1);assert.equal(ss[0].source,'override');assert.equal(ss[0].run,'a-front');
 assert.ok(ss[0].flags.includes('merged-override'));
 assert.deepEqual(ss[0].merged,[{run:'z-left',fraction:.85}],'preserve the authored fraction before corner snapping');
 assert.equal(runs[1].drainsTo,ss[0].id);assert.equal(ss[0].share,1);
 assert.deepEqual(G.downspouts(p,clone(runs).reverse()),ss);assert.deepEqual(G.downspouts(p,runs),ss);
 assert.deepEqual(p.buildings[0].roofs[0].edges[3].downspouts,[.85]);
});
await test('test_shared_contract_and_units',()=>{
 assert.deepEqual(G.GUTTER,{runJoinFt:.3,runJoinHeightIn:2,spanFt:35,maxOverhangFt:4,openingClearFt:1,doorAvoidFt:6,kickOutFt:3,kickTurnFt:4,profileIn:5,spoutIn:[2,3]});
 const p=house(),{runs,spouts}=calc(p);
 for(const r of runs){assert.deepEqual(Object.keys(r).sort(),['id','building','segments','length','corners'].sort());near(r.length,30);
  for(const s of r.segments)assert.deepEqual(Object.keys(s).sort(),['roof','edge','porch','a','b','outward'].sort());
  for(const c of r.corners)assert.deepEqual(Object.keys(c).sort(),['at','convex','segIndex'].sort());}
 for(const s of spouts){assert.deepEqual(Object.keys(s).sort(),['id','run','edge','top','mount','path','outlet','share','source','flags'].sort());
  assert.deepEqual(Object.keys(s.edge).sort(),['roof','edge','porch','fraction'].sort());assert.deepEqual(Object.keys(s.outlet).sort(),['at','dir','lands'].sort());
  assert.ok(s.edge.fraction>=0&&s.edge.fraction<=1);assert.deepEqual(s.path[0],s.top);assert.deepEqual(s.path.at(-1),s.outlet.at);
  near(Math.hypot(...s.outlet.dir),1);assert.equal(s.outlet.dir[1],0);assert.ok(s.top[1]>2&&s.top[1]<4);}
});
await test('test_rectangle_gable_two_runs_four_outside_corners',()=>{
 const p=house(),{runs,spouts}=calc(p);assert.equal(runs.length,2);assert.equal(spouts.length,2);
 assert.equal(runs.flatMap(r=>r.corners.filter(c=>c.convex)).length,4);
 assert.ok(spouts.every(s=>atCorner(p,s)&&s.mount==='wall'&&s.flags.length===0&&s.outlet.lands==='grass'));
});
await test('test_long_run_uses_both_outside_corners',()=>{
 const p=house(40),{runs,spouts}=calc(p);assert.equal(runs.length,2);assert.equal(spouts.length,4);
 for(const r of runs){const ss=spouts.filter(s=>s.run===r.id);assert.equal(ss.length,2);near(ss.reduce((v,s)=>v+s.share,0),1);}
 assert.ok(spouts.every(s=>atCorner(p,s)));
});
await test('test_L_house_inner_corner_never_used',()=>{
 const poly=[[0,0],[40,0],[40,20],[20,20],[20,40],[0,40]],p=house(40,'hip',poly),b=p.buildings[0];
 b.roof.sections=[];b.roofs=[];roof(p,'a',[0,0,40,20]);roof(p,'b',[0,0,20,40]);
 const {runs,spouts}=calc(p);assert.ok(runs.flatMap(r=>r.corners).some(c=>!c.convex));assert.equal(spouts.length,5);
 assert.ok(spouts.every(s=>atCorner(p,s)&&Math.hypot(local(p,s.top)[0]-20,local(p,s.top)[1]-20)>.5));
});
await test('test_run_with_no_outside_corner_uses_non_inner_end_and_flags',()=>{
 const p=house(40),b=p.buildings[0];b.roof.sections=[];b.roofs=[];roof(p,'short',[10,0,20,8],'shed',{low_side:'y0'});
 const {spouts}=calc(p);assert.equal(spouts.length,1);assert.equal(spouts[0].mount,'wall');assert.ok(spouts[0].flags.includes('no-outside-corner'));
 assert.ok([10,20].some(x=>Math.abs(local(p,spouts[0].top)[0]-x)<.01));
});
await test('test_opening_within_1ft_slides_to_next_outside_corner',()=>{
 const p=house();p.buildings[0].openings=[{id:'door',wall:'w0',at:1.5,width:2,sill:0,head:7,kind:'door'}];
 const front=calc(p).spouts.find(s=>s.edge.edge===0);near(local(p,front.top)[0],30);
 p.buildings[0].openings[0].at=2.1;override(p,0,[0]);
 const clear=calc(p).spouts.find(s=>s.edge.edge===0);near(local(p,clear.top)[0],0);
});
await test('test_second_storey_checks_all_levels_below',()=>{
 const p=house(),b=p.buildings[0];b.levels.push({id:'L2',elevation:11,ceiling:10,outline:rect(0,0,30,20)});
 b.walls.push(...b.walls.map(w=>({...clone(w),id:w.id+'up',level:'L2',height:10})));
 b.roof.sections[0].plate=21;b.roof.sections[0].level='L2';b.openings=[{id:'window',wall:'w0',at:1.5,width:2,sill:3,head:7,kind:'window'}];
 const front=calc(p).spouts.find(s=>s.edge.edge===0);near(local(p,front.top)[0],30);
 b.openings[0].at=28.5;near(local(p,calc(p).spouts.find(s=>s.edge.edge===0).top)[0],0);
});
await test('test_walkway_landing_turns_kickout_toward_grass',()=>{
 const p=house();override(p,0,[0]);p.site.hardscape=[{id:'walk',kind:'walkway',polygon:rect(-.8,-7,.8,0)}];
 const s=calc(p).spouts.find(s=>s.edge.edge===0);assert.ok(s);near(local(p,s.top)[0],0);assert.equal(s.outlet.lands,'grass');
 const out=local(p,s.outlet.at);assert.ok(Math.abs(out[0])>.8&&Math.abs(out[0])<=4.1);
});
await test('test_driveway_allowed_after_grass_and_beds',()=>{
 const p=house();p.site.hardscape=[{id:'drive',kind:'driveway',polygon:rect(-5,-6,4,0)}];
 let s=calc(p).spouts.find(s=>s.edge.edge===0);assert.equal(s.outlet.lands,'grass');near(local(p,s.top)[0],30);
 p.site.hardscape[0].polygon=rect(-5,-6,35,0);s=calc(p).spouts.find(s=>s.edge.edge===0);assert.equal(s.outlet.lands,'driveway');
 p.site.beds=[{id:'bed',polygon:rect(26,-7,35,0),elevation:1}];s=calc(p).spouts.find(s=>s.edge.edge===0);assert.equal(s.outlet.lands,'bed');
});
await test('test_porch_run_comes_down_a_post',()=>{
 const p=house(),b=p.buildings[0];b.roof.sections=[];b.roofs=[];const s=roof(p,'porchroof',[0,-8,30,0],'shed',{low_side:'y0',plate:8,pitch:3});s.gutters={};b.roofs[0].edges.forEach(e=>e.gutter=false);
 b.porches=[{id:'p',gutter:true,polygon:rect(0,-8,30,0),floor:0,columns:[{at:[0,-8],size:.5},{at:[30,-8],size:.5}]}];
 const {runs,spouts}=calc(p);assert.equal(runs[0].id,'b:porch:p');assert.equal(spouts.length,1);assert.equal(spouts[0].mount,'post');assert.equal(spouts[0].edge.porch,'p');
});
await test('test_authored_porch_roof_mounts_posts_and_keeps_edge_identity',()=>{
 const p=house(),b=p.buildings[0];b.roof.sections=[];b.roofs=[];roof(p,'porchroof',[0,-8,30,0],'shed',{low_side:'y0',plate:8,pitch:3});
 b.porches=[{id:'p',gutter:false,polygon:rect(0,-8,30,0),floor:0,columns:[{at:[0,-8],size:.5},{at:[30,-8],size:.5}]}];
 const {spouts}=calc(p);assert.equal(spouts.length,1);assert.equal(spouts[0].mount,'post');assert.equal(spouts[0].edge.roof,'porchroof');
 assert.equal(spouts[0].edge.porch,null);assert.deepEqual(spouts[0].flags,[]);
});
await test('test_upper_roof_downspout_ends_on_lower_roof',()=>{
 const p=house(),b=p.buildings[0];b.roof.sections[0].plate=20;
 b.levels.push({id:'L2',elevation:10,ceiling:10,outline:rect(0,0,30,20)});
 b.walls.push(...b.walls.map(w=>({...clone(w),id:w.id+'up',level:'L2'})));b.roof.sections[0].level='L2';
 roof(p,'lower',[-5,-8,35,-.1],'flat',{plate:7});const spouts=calc(p).spouts.filter(s=>s.edge.edge===0&&s.edge.roof==='r');
 assert.equal(spouts.length,1);assert.equal(spouts[0].outlet.lands,'roof');assert.ok(spouts[0].outlet.at[1]>7*FT);
});
await test('test_deep_overhang_gets_leader',()=>{
 const p=house();p.buildings[0].roof.sections[0].overhang=3.5;p.buildings[0].roofs[0].overhang=3.5;
 let ss=calc(p).spouts;assert.ok(ss.length);assert.ok(ss.every(s=>s.mount==='wall'&&s.path.length>=4));
 assert.ok(ss.every(s=>s.path.some((v,i)=>i&&v[1]>s.top[1]-.6*FT&&Math.abs(v[1]-s.path[i-1][1])<1e-6&&Math.hypot(v[0]-s.path[i-1][0],v[2]-s.path[i-1][2])>2*FT)));
 p.buildings[0].roof.sections[0].overhang=4.5;p.buildings[0].roofs[0].overhang=4.5;
 ss=calc(p).spouts;assert.ok(ss.length);assert.ok(ss.every(s=>s.mount==='hang'&&s.flags.includes('hang')));
});
await test('test_overrides_replace_auto_for_that_edge',()=>{
 const p=house();override(p,0,[.8]);let {spouts}=calc(p);let front=spouts.filter(s=>s.edge.edge===0);
 assert.equal(front.length,1);assert.equal(front[0].source,'override');near(front[0].edge.fraction,1);
 override(p,0,[]);spouts=calc(p).spouts;assert.ok(!spouts.some(s=>s.edge.edge===0));assert.ok(spouts.some(s=>s.edge.edge===2));
});
await test('test_hip_corner_overrides_keep_their_authored_edge',()=>{
 const p=house(20,'hip');override(p,0,[.15,.85]);const {spouts}=calc(p),ss=spouts.filter(s=>s.source==='override');
 assert.equal(ss.length,2);assert.ok(ss.every(s=>s.edge.edge===0));assert.deepEqual(ss.map(s=>s.edge.fraction).sort(),[0,1]);
});
await test('test_deterministic',()=>{
 const p=house(40),before=clone(p);assert.deepEqual(calc(p),calc(clone(p)));assert.deepEqual(p,before);
 const runs=G.gutterRuns(p);assert.deepEqual(G.downspouts(p,JSON.parse(JSON.stringify(runs))),G.downspouts(p,runs));
});
await test('test_door_avoidance_tiebreak',()=>{
 const p=house();p.buildings[0].openings=[{id:'door',wall:'w0',at:4,width:2,sill:0,head:7,kind:'door'}];
 near(local(p,calc(p).spouts.find(s=>s.edge.edge===0).top)[0],30);
});
await test('test_door_avoidance_still_considers_doors_below_a_lower_roof',()=>{
 const p=house(),b=p.buildings[0];b.roof.sections[0].plate=20;
 roof(p,'lower',[-5,-8,35,-.1],'flat',{plate:8});
 b.openings=[{id:'door',wall:'w0',at:4,width:2,sill:0,head:7,kind:'door'}];
 near(local(p,calc(p).spouts.find(s=>s.edge.roof==='r'&&s.edge.edge===0).top)[0],30);
});
await test('test_rakes_and_unguttered_stale_overrides_ignored',()=>{
 const p=house(),b=p.buildings[0];override(p,1,[0,1]);b.roofs[0].edges[1].gutter=true;b.roof.sections[0].gutters.x1=true;
 b.roofs[0].edges[0].gutter=false;delete b.roof.sections[0].gutters.y0;override(p,0,[0,1]);
 const {runs,spouts}=calc(p);assert.equal(runs.length,1);assert.ok(spouts.every(s=>s.edge.edge===2));
 b.roofs[0].edges[2].gutter=false;b.roof.sections[0].gutters={};assert.deepEqual(calc(p),{runs:[],spouts:[]});
});
await test('test_rotated_raised_building_uses_world_metres_and_local_outward',()=>{
 const p=house(),b=p.buildings[0];b.rotation=90;b.position=[60,40];b.base=4;
 const {runs,spouts}=calc(p);assert.equal(runs.length,2);assert.ok(spouts.every(s=>atCorner(p,s)));near(spouts[0].top[1],13.96*FT);
 for(const r of runs)for(const s of r.segments){near(Math.hypot(...s.outward),1);assert.equal(s.outward.length,2);}
});
await test('test_partial_exposure_joins_and_does_not_invent_midrun_corner',()=>{
 const p=house(),b=p.buildings[0];b.levels.push({id:'tall',elevation:0,ceiling:20,outline:rect(10,-2,20,.1)});
 const {runs,spouts}=calc(p);assert.equal(runs.filter(r=>r.segments.some(s=>s.edge===0)).length,2);
 assert.ok(spouts.every(s=>!s.flags.length&&atCorner(p,s)));
});
await test('test_split_run_suffixes_follow_authored_start_fraction',()=>{
 const p=house(),b=p.buildings[0];b.levels.push({id:'tall',elevation:0,ceiling:20,outline:rect(10,19.9,20,22)});
 const runs=G.gutterRuns(p).filter(r=>r.segments[0].edge===2);assert.equal(runs.length,2);
 const base=runs.find(r=>r.id==='b:r:2'),second=runs.find(r=>r.id==='b:r:2~2');assert.ok(base&&second);
 assert.ok(base.segments.every(s=>Math.min(s.a[0],s.b[0])>=20*FT-.01),'edge 2 runs right to left');
 assert.ok(second.segments.every(s=>Math.max(s.a[0],s.b[0])<=10*FT+.01));
 const ss=G.downspouts(p,runs);assert.ok(ss.every(s=>s.id.startsWith(s.run+':')));assert.equal(new Set(ss.map(s=>s.id)).size,ss.length);
});
await test('test_porch_split_suffixes_follow_porch_edge_direction',()=>{
 const p=house(),b=p.buildings[0];b.roof.sections=[];b.roofs=[];const s=roof(p,'porchroof',[0,-8,30,0],'shed',{low_side:'y0',plate:8});
 s.gutters={};b.roofs[0].edges.forEach(e=>e.gutter=false);
 b.porches=[{id:'p',gutter:true,polygon:[[30,-8],[0,-8],[0,0],[30,0]],floor:0,columns:[{at:[0,-8]},{at:[30,-8]}]}];
 b.levels.push({id:'block',elevation:0,ceiling:20,outline:rect(10,-9,20,-7)});
 const runs=G.gutterRuns(p);assert.equal(runs.length,2);
 const first=runs.find(r=>r.id==='b:porch:p'),next=runs.find(r=>r.id==='b:porch:p~2');assert.ok(first&&next);
 assert.ok(first.segments.every(s=>Math.min(s.a[0],s.b[0])>=20*FT-.01));
 assert.ok(next.segments.every(s=>Math.max(s.a[0],s.b[0])<=10*FT+.01));
});
await test('test_one_override_on_split_edge_is_not_duplicated_per_run',()=>{
 const p=house(),b=p.buildings[0];b.levels.push({id:'tall',elevation:0,ceiling:20,outline:rect(10,-2,20,.1)});
 override(p,0,[.1]);const ss=calc(p).spouts.filter(s=>s.edge.edge===0);assert.equal(ss.length,1);assert.equal(ss[0].source,'override');near(ss[0].edge.fraction,0);
});
await test('test_downspouts_reject_stale_runs_after_gutters_disabled',()=>{
 const p=house(),runs=G.gutterRuns(p);p.buildings[0].roofs[0].edges.forEach(e=>e.gutter=false);
 assert.deepEqual(G.downspouts(p,runs),[]);
});
await test('test_flat_roof_only_explicit_gutter_perimeters',()=>{
 const p=house(20,'flat');assert.equal(calc(p).runs.length,1);assert.ok(calc(p).spouts.length>0);
 assert.equal(E.extractEaves(p).length,0,'stream extraction still ignores flat roofs');
});
await test('test_joins_obey_distance_and_height_tolerances',()=>{
 const p=house(20,'shed'),b=p.buildings[0];b.roof.sections=[];b.roofs=[];
 roof(p,'a',[0,0,10,8],'shed',{low_side:'y0'});const next=roof(p,'b',[10.2,0,20,8],'shed',{low_side:'y0',plate:10.1});
 assert.equal(G.gutterRuns(p).length,1);next.plate=10.2;assert.equal(G.gutterRuns(p).length,2);
 next.plate=10;next.rect[0]=10.4;b.roofs[1].area[0][0]=10.4;b.roofs[1].area[3][0]=10.4;assert.equal(G.gutterRuns(p).length,2);
});
await test('test_no_outside_corner_fallback_never_uses_inner_end',()=>{
 const poly=[[0,0],[40,0],[40,20],[20,20],[20,40],[0,40]],p=house(40,'hip',poly),b=p.buildings[0];
 b.roof.sections=[];b.roofs=[];roof(p,'notch',[20,20,28,30],'shed',{low_side:'x0'});
 const {spouts}=calc(p);assert.equal(spouts.length,1);assert.ok(spouts[0].flags.includes('no-outside-corner'));
 near(local(p,spouts[0].top)[1],30);
});
await test('test_wall_must_reach_the_soffit_not_just_share_its_plan_line',()=>{
 const p=house();p.buildings[0].roof.sections[0].plate=22;
 const ss=calc(p).spouts;assert.ok(ss.length);assert.ok(ss.every(s=>s.mount==='hang'&&s.flags.includes('hang')));
});
await test('test_outline_corner_does_not_require_duplicate_wall_records',()=>{
 const p=house();p.buildings[0].walls=p.buildings[0].walls.filter(w=>w.id==='w0');
 const {runs,spouts}=calc(p);assert.equal(runs.flatMap(r=>r.corners).length,4);
 assert.ok(spouts.every(s=>s.mount==='wall'&&!s.flags.length));
});
await test('test_section_only_flags_and_fraction_overrides',()=>{
 const p=house(),b=p.buildings[0];override(p,0,[.85]);delete b.roofs;
 const ss=calc(p).spouts.filter(s=>s.edge.edge===0);assert.equal(ss.length,1);assert.equal(ss[0].source,'override');near(ss[0].edge.fraction,1);
});
await test('test_eave_metadata_keeps_authored_side_and_edge',()=>{
 const p=house();const edges=E.extractEaves(p);assert.deepEqual(edges.map(e=>e.side).sort(),['y0','y1']);
 for(const e of edges)assert.equal(e.edge,p.buildings[0].roof.sections[0].plane_edges[e.side]);
 assert.equal(typeof E.clipExposedEdges,'function');assert.equal(typeof E.createEaveLandingSampler,'function');
});
await test('test_prohibited_landings_keep_mountable_corner_drop_with_warning',()=>{
 for(const kind of ['walkway','path','step','stair','patio_step','porch_step','deck_stair']){
  const p=house();p.site.hardscape=[{id:'blocked',kind,polygon:rect(-10,-10,40,0),points:[[-10,-3],[40,-3]],width:14}];
  const {runs,spouts}=calc(p);assert.ok(runs.every(r=>spouts.some(s=>s.run===r.id)),kind);
  const s=spouts.find(s=>s.edge.edge===0);assert.equal(s.mount,'wall');assert.deepEqual(s.flags,['no-safe-landing']);
  assert.equal(s.outlet.lands,'hard');assert.ok(s.outlet.at[1]<FT,'landing-only failure preserves the full wall drop');
 }
 const p=house();p.site.pool={polygon:rect(-10,-10,40,0),coping:0};
 const s=calc(p).spouts.find(s=>s.edge.edge===0);assert.equal(s.mount,'wall');assert.ok(s.flags.includes('no-safe-landing'));
});
await test('test_plain_patio_and_terrace_are_allowed_after_grass',()=>{
 for(const kind of ['patio','terrace']){const p=house();p.site.hardscape=[{id:'paving',kind,polygon:rect(-10,-10,40,0)}];
  const s=calc(p).spouts.find(s=>s.edge.edge===0);assert.equal(s.mount,'wall');assert.equal(s.outlet.lands,'hard');assert.deepEqual(s.flags,[]);}
 const p=house();p.site.hardscape=[{id:'paving',kind:'patio',polygon:rect(-10,-10,5,0)}];
 near(local(p,calc(p).spouts.find(s=>s.edge.edge===0).top)[0],30);
});
await test('test_blocked_kickout_keeps_best_allowed_turned_landing',()=>{
 const p=house();override(p,0,[0]);p.site.hardscape=[{id:'walk',kind:'walkway',polygon:rect(-.5,-10,.5,0)},
  {id:'left',kind:'patio',polygon:rect(-10,-10,-.5,0)},{id:'right',kind:'terrace',polygon:rect(.5,-10,10,0)}];
 const s=calc(p).spouts.find(s=>s.edge.edge===0);assert.equal(s.mount,'wall');assert.deepEqual(s.flags,[]);
 assert.equal(s.outlet.lands,'hard');const out=local(p,s.outlet.at);assert.ok(Math.abs(out[0])>.5&&Math.abs(out[0])<=4);
});
await test('test_awning_plan_only_and_snapshot_agree',async()=>{
 const p=house(),b=p.buildings[0];b.roofs[0].edges.forEach(e=>e.gutter=false);b.roof.sections[0].gutters={};
 b.roof.extensions=[{id:'aw',kind:'awning',section:'r',wall:'w0',x0:5,x1:15,depth:3,eave:8,pitch:3,gutter:true}];
 const runs=G.gutterRuns(p);assert.equal(runs.length,1);assert.equal(runs[0].segments[0].porch,'aw');
 const twin=buildTwin(p,{materials:{}},'high');await twin.ready;
 try{const other=G.gutterRuns(p,twin.roofSurfaces);assert.equal(other.length,1);near(other[0].length,runs[0].length,.01);
  for(const k of [0,1,2])near(other[0].segments[0].a[k],runs[0].segments[0].a[k],.01);
 }finally{for(const group of Object.values(twin.groups))group?.traverse?.(o=>o.geometry?.dispose());}
});
await test('test_snapshot_contract_accepts_sections_without_prebuilt_mesh',()=>{
 const p=house(),roofs=new Map([['b',{sections:p.buildings[0].roof.sections,eaveAttachments:[]}]]);
 assert.deepEqual(G.gutterRuns(p,roofs),G.gutterRuns(p));
});
await test('test_household_fixture_all_eaves_report',()=>{
 const p=clone(input.plan);
 for(const b of p.buildings){for(const r of b.roofs||[])for(const e of r.edges)e.gutter=e.setting==='sloped';
  for(const s of b.roof.sections){s.gutters={};for(const plane of (s.kind==='shed'?[s.low_side]:s.kind==='flat'?[]:s.kind==='gable'?(s.ridge==='x'?['y0','y1']:['x0','x1']):['y0','x1','y1','x0'])){
   if(!['gable','clip'].includes(s.ends?.[plane]))s.gutters[plane]=true;}}
  for(const a of b.roof.extensions||[])if(a.kind==='awning')a.gutter=true;
  for(const porch of b.porches||[])porch.gutter=true;
 }
 const before=clone(p),{runs,spouts}=calc(p);assert.ok(runs.length>10&&spouts.length>10);assert.deepEqual(p,before);
 const hip=runs.filter(r=>r.id.includes('roof:1f72'));assert.equal(hip.length,1);near(hip[0].length,46,.5);
 const hipSpouts=spouts.filter(s=>s.run===hip[0].id);assert.equal(hipSpouts.length,2);assert.ok(hipSpouts.every(s=>s.share===.5));
 for(const [prefix,edge] of [['2f47',2],['2f47',0],['144a',0],['144a',2],['c8d9',0],['c8d9',2]]){
  const run=runs.find(r=>r.id.includes('roof:'+prefix)&&r.segments[0].edge===edge&&(edge!==0||!['2f47','c8d9'].includes(prefix)||r.id.endsWith('~2')));
  const s=spouts.find(s=>s.run===run.id);assert.ok(s);assert.equal(s.mount,'wall',run.id);
  assert.equal(s.outlet.lands,'roof',run.id);assert.deepEqual(s.flags,[],run.id);
  const q=local({buildings:[p.buildings.find(b=>b.id===run.building)]},dropPoint(s));
  if(prefix==='2f47'&&edge===2)assert.ok(Math.hypot(q[0]-59,q[1]-43)<.5);
  if(prefix==='c8d9'&&edge===0)assert.ok(Math.hypot(q[0]-37,q[1]-13.333333)<.5);
 }
 const sampler=E.createEaveLandingSampler(p,null,{roofDetails:true});
 const placements=spouts.map(s=>{const run=runs.find(r=>r.id===s.run),b=p.buildings.find(b=>b.id===run.building),q=local({buildings:[b]},s.top);
  const hit=sampler([s.outlet.at[0],s.outlet.at[1]+.1*FT,s.outlet.at[2]]),floor=s.outlet.lands==='roof'?(hit.roofEave??hit.height)/FT-(b.base||0):-Infinity;
  const eligible={...b,levels:b.levels.filter(l=>(l.elevation||0)>=floor-1e-4),porches:allPorches(b).filter(v=>(v.floor||0)>=floor-1e-4)};delete eligible.porch;
  const corners=unionCorners(eligible,q[2]),oh=b.roofs?.find(r=>r.id===s.edge.roof)?.overhang??b.roof.extensions?.find(a=>a.id===s.edge.porch)?.depth??1;
  const corner=corners.filter(c=>Math.max(Math.abs(c.at[0]-q[0]),Math.abs(c.at[1]-q[1]))<=oh+1+1e-4)
   .sort((a,b)=>Math.hypot(a.at[0]-q[0],a.at[1]-q[1])-Math.hypot(b.at[0]-q[0],b.at[1]-q[1]))[0];
  return {s,run,b,corners,corner,oh};});
 const cornerKey=v=>v.b.id+':'+v.corner.at.map(n=>n.toFixed(4)).join(',');
 const mounted=placements.filter(v=>v.corner),keys=mounted.map(cornerKey);assert.equal(new Set(keys).size,keys.length,'one spout per building corner across all runs');
 const sharedRuns=[];
 for(const run of runs.filter(r=>!spouts.some(s=>s.run===r.id))){
  const winner=placements.find(v=>v.s.id===run.drainsTo&&v.b.id===run.building);
  assert.ok(winner,`${run.id}: every run has an owned outlet or explicit drainsTo`);
  sharedRuns.push({run:run.id,via:run.drainsTo,corner:winner.corner?.at??null});
 }
 for(const {s,b,corners} of placements){
  if(s.flags.includes('clipped-end'))assert.ok(s.path.every(v=>s.top[1]-v[1]<=.51*FT),'a clipped-only emergency must not pipe down through its blocker');
  for(const point of [s.top,dropPoint(s)]){const q=local({buildings:[b]},point);
   for(const c of corners.filter(c=>c.count===3))assert.ok(Math.hypot(q[0]-c.at[0],q[1]-c.at[1])>=.5,`${s.id} at inner union vertex ${c.at}`);}}
 assert.deepEqual(calc(p),{runs,spouts});
 for(const s of spouts){assert.ok(['wall','post','hang'].includes(s.mount));assert.ok(['grass','bed','driveway','roof','deck','hard'].includes(s.outlet.lands));
  assert.ok(s.path.flat().every(Number.isFinite));assert.ok(s.share>0&&s.share<=1);}
 console.log('HOUSEHOLD_GUTTERS',JSON.stringify({runCount:runs.length,downspoutCount:spouts.length,
  unservedRuns:[],sharedRuns,runsWithoutOwnDownspout:sharedRuns.map(v=>v.run),
  runs:runs.map(r=>({id:r.id,length:r.length,...(r.drainsTo?{drainsTo:r.drainsTo}:{})})),
  downspouts:placements.map(({s,corner})=>({id:s.id,run:s.run,corner:corner?(corner.count===1?'outside':'inner'):'non-corner',mount:s.mount,lands:s.outlet.lands,share:s.share,flags:s.flags}))}));
});
finish();
"""

if __name__ == '__main__':
    os.environ.pop('HA_BASE_URL', None)
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': flatten(assemble(fixture)[0])}, timeout=180)
    print(output)
    for line in output.splitlines():
        if line.startswith('HOUSEHOLD_GUTTERS '):
            target = ROOT.parent / '.superpowers/tmp/gutters-task-2-household.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(json.loads(line.split(' ', 1)[1]), indent=2) + '\n', encoding='utf-8')
    sys.exit(1 if code is None else code)
