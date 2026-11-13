"""Surface conduit route maths, executed under node without a renderer."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {solarConduits,CONDUIT_OFFSET:offset}=await import(file('static/twin/live/solar_conduit.js'));
const {energyAnchors,lotPoint,worldPoint}=await import(file('static/twin/live/energy_geometry.js'));
const {solarPoint}=await import(file('static/twin/twin_solar.js'));
const {groundAt,buildingGround,inPolygon}=await import(file('static/twin/twin_ground.js'));
const checks=[],check=(n,f)=>checks.push([n,f]),close=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
const section=(id,rect)=>({id,kind:'gable',ridge:'x',rect,pitch:6,plate:10,overhang:0,level:'L1'});
const zone=(id,roof,x)=>({id,roof,plane:[0,.5,10],rect:[x,2,x+4,6]});
function fixture(){
 const b={id:'b',position:[0,0],rotation:0,base:0,levels:[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[40,0],[40,20],[0,20]]}],
  roof:{sections:[section('source',[0,0,20,20]),section('satellite',[20,0,40,20])]},solar_zones:[zone('a','source',2),zone('b','satellite',30)]};
 return {buildings:[b],solar_source_roof:'source',solar_source_building:'b'};
}
const anchors=plan=>energyAnchors({plan},{markers:[]},{cars:[]});
check('same building descends its sloped plane, follows the eave and ends exactly at the shared source',()=>{
 const plan=fixture(),a=anchors(plan),[route]=solarConduits(plan,a),b=plan.buildings[0];assert.ok(route);
 const expected=lotPoint(b,solarPoint([0,.5,10],[32,4],offset),plan);
 route.points[0].forEach((v,i)=>close(v,expected[i]));assert.deepEqual(route.points.at(-1),a.solar);
 const eave=route.points[1];close((eave[2]-.5*eave[1]-10)/Math.hypot(.5,1),offset);
 const run=route.points.filter(p=>Math.abs(p[1]+offset)<1e-8);assert.ok(run.length>=2);
 run.forEach(p=>close(p[2],10));assert.ok(Math.abs(run[0][0]-run.at(-1)[0])>20);
 // Every point is about two inches from its roof or outside wall, including
 // the existing ribbon anchor's 1.8-inch lift. Sample segments as well.
 const surfaceDistance=p=>{
  const r=p[2]-.5*p[1]-10,projectedY=p[1]+.5*r/1.25;
  const roof=projectedY>=0?Math.abs(r)/Math.hypot(.5,1):Math.hypot(p[1],p[2]-10);
  const wall=p[2]<=10?Math.abs(p[1]):Math.hypot(p[1],p[2]-10);return Math.min(roof,wall);
 };
 for(let i=1;i<route.points.length;i++)for(let t=0;t<=1;t+=.1){
  const p=route.points[i-1].map((v,j)=>v+(route.points[i][j]-v)*t),d=surfaceDistance(p);
  assert.ok(d>=.12&&d<=offset+1e-7,JSON.stringify(p)+' clearance '+d);
 }
});
check('other building goes down the wall, across sampled ground, up the nearest wall and roof',()=>{
 const plan=fixture(),b=plan.buildings[0];b.solar_zones.pop();b.roof.sections.pop();b.levels[0].outline=[[0,0],[20,0],[20,20],[0,20]];
 const shed={...structuredClone(b),id:'shed',position:[60,0],base:2,solar_zones:[zone('remote','remote',2)],roof:{sections:[section('remote',[0,0,20,20])]}};
 plan.buildings.push(shed);
 plan.site={terraces:[{polygon:[[35,-10],[50,-10],[50,30],[35,30]],height:3,blend:3}]};
 const a=anchors(plan),[route]=solarConduits(plan,a);assert.equal(route.id,'shed:remote');
 const ground=route.points.filter(p=>Math.abs(p[2]-groundAt(plan,p[0],p[1])-offset)<1e-7);
 assert.ok(ground.some(p=>p[0]>25&&p[0]<55),'ground between the buildings');assert.ok(ground.some(p=>p[2]>3));
 assert.deepEqual(route.points.at(-1),a.solar);assert.ok(route.points[0][2]>12);
 for(let i=1;i<ground.length;i++)assert.ok(Math.hypot(ground[i][0]-ground[i-1][0],ground[i][1]-ground[i-1][1])<=1.01);
});
check('rotated offset raised building honours its base and terrain, with scene metres and z=-y',()=>{
 const plan=fixture(),b=plan.buildings[0];b.rotation=37;b.position=[100,-40];b.base=2;b.foundation={mode:'auto',offset_ft:2};
 plan.site={terraces:[{polygon:[[50,-80],[160,-80],[160,40],[50,40]],height:4,blend:0}]};
 const plain=fixture(),expected=solarConduits(plain,anchors(plain))[0],route=solarConduits(plan,anchors(plan))[0];
 assert.equal(route.points.length,expected.points.length);close(buildingGround(plan,b),4);
 for(let i=0;i<expected.points.length;i++){
  const p=lotPoint(b,expected.points[i],plan);p.forEach((v,j)=>close(route.points[i][j],v));
  const w=worldPoint(p);close(w.x,p[0]*FT);close(w.y,p[2]*FT);close(w.z,-p[1]*FT);
 }
});
check('a far-side eave goes around its own building before crossing the ground',()=>{
 const plan=fixture(),b=plan.buildings[0];b.solar_zones.pop();b.roof.sections.pop();b.levels[0].outline=[[0,0],[20,0],[20,20],[0,20]];
 const other={...structuredClone(b),id:'other',position:[0,60],solar_zones:[{id:'away',roof:'away',plane:[0,-.5,20],rect:[2,6,6,10]}],
  roof:{sections:[{...section('away',[0,0,20,20]),kind:'shed',low_side:'y1'}]}};
 plan.buildings.push(other);const [route]=solarConduits(plan,anchors(plan));assert.ok(route);
 const ground=route.points.filter(p=>Math.abs(p[2]-offset)<1e-8);assert.ok(ground.length>40);
 for(let i=1;i<ground.length;i++)for(let t=0;t<=1;t+=.1){
  const p=ground[i-1].map((v,j)=>v+t*(ground[i][j]-v));
  assert.equal(inPolygon(other.levels[0].outline,p[0],p[1]-60),false,'ground must stay outside the satellite');
 }
 assert.ok(ground.some(p=>p[1]<60&&p[1]>20),'crosses the gap');
});
check('multiple source zones preserve their area-weighted anchor and same roof names on another building are satellites',()=>{
 const plan=fixture(),b=plan.buildings[0];b.solar_zones[0].rect=[2,2,6,4];b.solar_zones.push({...zone('second','source',10),rect:[10,2,18,8]});
 const other={...structuredClone(b),id:'other',position:[70,10],solar_zones:[zone('other-source','source',2)]};
 plan.buildings.push(other);const a=anchors(plan),routes=solarConduits(plan,a);assert.equal(routes.length,2);
 assert.ok(routes.some(r=>r.id==='other:other-source'));
 const first=lotPoint(b,solarPoint([0,.5,10],[4,3],.15),plan),second=lotPoint(b,solarPoint([0,.5,10],[14,5],.15),plan);
 a.solar.forEach((v,i)=>close(v,(first[i]*8+second[i]*48)/56));
 routes.forEach(r=>assert.deepEqual(r.points.at(-1),a.solar));
});
check('perimeter run goes around corners rather than through a building and accepts reverse winding',()=>{
 for(const reverse of [false,true]){
  const plan=fixture(),b=plan.buildings[0];b.roof.sections[1]={...section('satellite',[20,0,40,20]),low_side:'x1',kind:'shed'};
  b.solar_zones[1]={id:'b',roof:'satellite',plane:[-.5,0,30],rect:[25,6,29,10]};
  if(reverse)b.levels[0].outline.reverse();
  const [route]=solarConduits(plan,anchors(plan));assert.ok(route);
  assert.ok(route.points.some(p=>Math.abs(p[0]-40-offset)<1e-7&&Math.abs(p[1]+offset)<1e-7),'outside corner');
  for(const p of route.points.slice(2,-2))assert.ok(p[0]>=40||p[1]<=0,'wall path stays outside');
 }
});
check('flat roofs, no source, no satellite, ghost zones and ambiguous source identities',()=>{
 const plan=fixture();for(const s of plan.buildings[0].roof.sections){s.kind='flat';s.pitch=0;}
 for(const z of plan.buildings[0].solar_zones)z.plane=[0,0,10];
 assert.equal(solarConduits(plan,anchors(plan)).length,1);
 assert.deepEqual(solarConduits(plan,{solar:null,source:null}),[]);
 const ghost=structuredClone(plan);ghost.buildings[0].solar_zones[1].state='ghost';assert.deepEqual(solarConduits(ghost,anchors(ghost)),[]);
 plan.buildings[0].solar_zones.pop();assert.deepEqual(solarConduits(plan,anchors(plan)),[]);
 plan.solar_source_roof='missing';assert.deepEqual(solarConduits(plan,anchors(plan)),[]);
 const ambiguous=fixture();delete ambiguous.solar_source_building;const other=structuredClone(ambiguous.buildings[0]);other.id='other';ambiguous.buildings.push(other);
 assert.deepEqual(solarConduits(ambiguous,anchors(ambiguous)),[]);
});
let failed=0;for(const[n,f]of checks)try{await f();console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
console.log(`${checks.length-failed}/${checks.length} solar conduit route checks passed`);process.exit(failed?1:0);
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER))
