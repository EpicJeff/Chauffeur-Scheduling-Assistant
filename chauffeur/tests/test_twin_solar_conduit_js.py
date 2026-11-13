"""Solar conduit ridge routing (the user's rule), the worker router, and the
household fixture, executed in node.

The user's rule (2026-11-13): from a solar zone go up to the ridge of its roof,
follow the ridge toward the main solar zone, at the end of the ridge go up
whatever it runs into to the next ridge, repeat until the main solar zone; the
conduit always lies on the building. All zones on one roof count as one zone.
"""
import json
import os
from pathlib import Path
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {solarConduits,conduitInput,createConduitRouter,CONDUIT_OFFSET:offset}=await import(file('static/twin/live/solar_conduit.js'));
const {energyAnchors,lotPoint}=await import(file('static/twin/live/energy_geometry.js'));
const {solarPlanes,solarCovered,solarPoint}=await import(file('static/twin/twin_solar.js'));
const {handleConduitMessage}=await import(file('static/twin/live/solar_conduit_worker.js'));
const checks=[],check=(n,f)=>checks.push([n,f]);
const section=(id,rect,extra={})=>({id,kind:'flat',rect,pitch:0,plate:10,overhang:0,level:'L1',...extra});
const gable=(id,rect,ridge,plate,pitch=12)=>section(id,rect,{kind:'gable',ridge,pitch,plate});
const anchors=plan=>energyAnchors({plan},{markers:[]},{cars:[]});
function building(id,sections,position=[0,0]) {
 return {id,position,rotation:0,base:0,levels:[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[40,0],[40,40],[0,40]]}],
  walls:[],rooms:[],stairs:[],roof:{sections},solar_zones:[]};
}
// A 2 x 2 ft zone on the chosen plane of a roof, as near the plane's middle as fits.
function zone(b,id,roof,pick=()=>true) {
 const plane=solarPlanes(b).find(p=>p.roof===roof&&pick(p.plane));if(!plane)throw Error('no plane '+roof);
 const uv=plane.triangles.flat(),xs=uv.map(p=>p[0]),ys=uv.map(p=>p[1]),cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
 const tries=[];for(let dy=-8;dy<=8;dy+=.5)for(let dx=-8;dx<=8;dx+=.5)tries.push([cx+dx-1,cy+dy-1]);
 tries.sort((a,b)=>Math.hypot(a[0]-cx+1,a[1]-cy+1)-Math.hypot(b[0]-cx+1,b[1]-cy+1));
 for(const [x,y] of tries){const rect=[x,y,x+2,y+2];if(solarCovered(rect,plane)){const z={id,roof,plane:plane.plane,rect};b.solar_zones.push(z);return z;}}
 throw Error('no room for zone '+id);
}
// Every vertex of a route lies on a roof plane (lifted by the conduit offset) or on the
// vertical rise below a roof it ran into: nothing floats and nothing is inside the house.
function onBuilding(plan,route) {
 const planes=plan.buildings.flatMap(b=>solarPlanes(b).map(p=>({b,p})));
 const z=(b,p,[x,y])=>{const t=p.triangles.map(t=>t.map(uv=>lotPoint(b,solarPoint(p.plane,uv),plan)));
  for(const tri of t){const [a,c,d]=tri,den=(c[1]-d[1])*(a[0]-d[0])+(d[0]-c[0])*(a[1]-d[1]);if(Math.abs(den)<1e-12)continue;
   const l1=((c[1]-d[1])*(x-d[0])+(d[0]-c[0])*(y-d[1]))/den,l2=((d[1]-a[1])*(x-d[0])+(a[0]-d[0])*(y-d[1]))/den,l3=1-l1-l2;
   if(l1>=-1e-6&&l2>=-1e-6&&l3>=-1e-6)return l1*a[2]+l2*c[2]+l3*d[2];}return null;};
 route.points.forEach((p,i)=>{
  const surface=planes.some(({b,p:pl})=>{const h=z(b,pl,p);return h!==null&&Math.abs(h+offset-p[2])<.02;});
  const rise=[route.points[i-1],route.points[i+1]].some(q=>q&&Math.hypot(q[0]-p[0],q[1]-p[1])<1e-6);
  assert.ok(surface||rise,'vertex off the building '+JSON.stringify(p)+' in '+route.id+' route '+JSON.stringify(route.points.map(q=>q.map(v=>+v.toFixed(2)))));
 });
}
function rises(route){return route.points.slice(1).filter((p,i)=>Math.hypot(p[0]-route.points[i][0],p[1]-route.points[i][1])<1e-6&&p[2]>route.points[i][2]+1);}

check('two gables in line: up to the ridge, along it, and down onto the main zone; never to an eave',()=>{
 const b=building('b',[gable('main',[0,0,20,20],'y',10),gable('far',[0,20,20,40],'y',10)]);
 zone(b,'main','main',p=>p[0]>0);zone(b,'sat','far',p=>p[0]<0);
 const plan={buildings:[b],solar_source_roof:'main',solar_source_building:'b'},[route]=solarConduits(plan,anchors(plan));
 assert.ok(route,'routed');onBuilding(plan,route);
 const top=Math.max(...route.points.map(p=>p[2]));assert.ok(Math.abs(top-(20+offset))<.02,'reaches the ridge '+top);
 const first=route.points[0],last=route.points.at(-1),low=Math.min(first[2],last[2]);
 assert.ok(route.points.every(p=>p[2]>=low-1e-6),'never descends below its ends: '+JSON.stringify(route.points));
 assert.ok(route.points.length<=6,'a short, direct route: '+JSON.stringify(route.points));
});
check('a lower ridge runs into a taller gable end: rise up that wall to the upper ridge',()=>{
 const b=building('b',[gable('main',[0,0,20,20],'x',20),gable('porch',[20,6,30,14],'x',10)]);
 zone(b,'main','main',p=>p[1]<0);zone(b,'sat','porch',p=>p[1]>0);
 const plan={buildings:[b],solar_source_roof:'main',solar_source_building:'b'},[route]=solarConduits(plan,anchors(plan));
 assert.ok(route,'routed');onBuilding(plan,route);
 const up=rises(route);assert.equal(up.length,1,'one climb up the taller wall: '+JSON.stringify(route.points));
 assert.ok(Math.abs(up[0][0]-20)<.02,'at the gable end '+JSON.stringify(up[0]));
 assert.ok(Math.abs(Math.max(...route.points.map(p=>p[2]))-(30+offset))<.02,'reaches the upper ridge');
});
check('all zones on one roof make one conduit, from whichever zone has the shorter run',()=>{
 const b=building('b',[gable('main',[0,0,20,20],'y',10),gable('far',[0,20,20,40],'y',10)]);
 zone(b,'main','main',p=>p[0]>0);zone(b,'a','far',p=>p[0]<0);zone(b,'c','far',p=>p[0]>0);
 const plan={buildings:[b],solar_source_roof:'main',solar_source_building:'b'},routes=solarConduits(plan,anchors(plan));
 assert.equal(routes.length,1);assert.equal(routes[0].id,'b:far');onBuilding(plan,routes[0]);
});
check('several main-roof zones are one destination; the ribbon origin is lifted onto that roof',()=>{
 const b=building('b',[gable('main',[0,0,20,20],'y',10),gable('far',[0,20,20,40],'y',10)]);
 zone(b,'east','main',p=>p[0]>0);zone(b,'west','main',p=>p[0]<0);zone(b,'sat','far',p=>p[0]<0);
 const plan={buildings:[b],solar_source_roof:'main',solar_source_building:'b'},a=anchors(plan),[route]=solarConduits(plan,a);
 assert.ok(route);assert.ok(route.source[2]>a.solar[2]+1,'weighted centre between opposite slopes is lifted: '+JSON.stringify([a.solar,route.source]));
 assert.ok(Math.abs(route.source[2]-20)<.05,'onto the ridge where the slopes meet');
});
check('flat roofs join at their level; a separate building with no shared roof gets no conduit',()=>{
 const b=building('b',[section('main',[0,0,10,20]),section('remote',[10,0,20,20])]);
 b.solar_zones=[{id:'main',roof:'main',plane:[0,0,10],rect:[2,2,6,6]},{id:'sat',roof:'remote',plane:[0,0,10],rect:[12,12,16,16]}];
 let plan={buildings:[b],solar_source_roof:'main',solar_source_building:'b'};
 const [route]=solarConduits(plan,anchors(plan));assert.ok(route);onBuilding(plan,route);
 const other=building('other',[section('away',[0,0,10,10])],[60,0]);other.solar_zones=[{id:'away',roof:'away',plane:[0,0,10],rect:[2,2,6,6]}];
 b.solar_zones.pop();plan={buildings:[b,other],solar_source_roof:'main',solar_source_building:'b'};const messages=[];
 assert.deepEqual(solarConduits(plan,anchors(plan),{debug:m=>messages.push(m)}),[]);assert.equal(messages.length,1);
});
check('ghost, absent and ambiguous sources draw nothing',()=>{
 const b=building('b',[section('main',[0,0,10,20]),section('remote',[10,0,20,20])]);
 b.solar_zones=[{id:'main',roof:'main',plane:[0,0,10],rect:[2,2,6,6]},{id:'sat',roof:'remote',plane:[0,0,10],rect:[12,12,16,16]}];
 const plan={buildings:[b],solar_source_roof:'main',solar_source_building:'b'};
 b.solar_zones[1].state='ghost';assert.deepEqual(solarConduits(plan,anchors(plan)),[]);
 assert.deepEqual(solarConduits(plan,{solar:null,source:null}),[]);
 b.solar_zones[1].state='settled';plan.solar_source_roof='missing';assert.deepEqual(solarConduits(plan,anchors(plan)),[]);
});
function fixture() {
 const b=building('b',[section('source',[0,0,10,20]),section('remote',[10,0,20,20])]);
 b.solar_zones=[{id:'main',roof:'source',plane:[0,0,10],rect:[2,2,6,6]},{id:'sat',roof:'remote',plane:[0,0,10],rect:[12,12,16,16]}];
 return {buildings:[b],solar_source_roof:'source',solar_source_building:'b'};
}
const workerUrls={worker:file('static/twin/live/solar_conduit_worker.js'),core:file('static/twin/live/solar_conduit_core.js'),ground:file('static/twin/twin_ground.js')};
check('worker message handler executes the real pure routing core and reports import failures',async()=>{
 const plan=fixture();let result;
 await handleConduitMessage({id:7,coreUrl:workerUrls.core,groundUrl:workerUrls.ground,input:conduitInput(plan,anchors(plan))},m=>result=m);
 assert.equal(result.id,7);assert.equal(result.routes.length,1);assert.deepEqual(result.routes,solarConduits(plan,anchors(plan)));
 await handleConduitMessage({id:8,coreUrl:'file:///no-conduit-core.js',groundUrl:workerUrls.ground,input:{}},m=>result=m);
 assert.equal(result.id,8);assert.ok(result.error);
});
check('worker router drops stale replies and resolves cancelled jobs without drawing',async()=>{
 const saved=globalThis.Worker,workers=[];
 class StubWorker {
  constructor(url,options){assert.equal(url,workerUrls.worker);assert.equal(options.type,'module');this.jobs=[];workers.push(this);}
  postMessage(m){this.jobs.push(structuredClone(m));}terminate(){this.closed=true;}
 }
 globalThis.Worker=StubWorker;const router=createConduitRouter({urls:workerUrls});
 try {
  const plan=fixture(),first=router.run(plan,anchors(plan));
  assert.equal(workers.length,0,'even preparation is deferred past mount');
  for(let i=0;i<100&&!workers[0]?.jobs.length;i++)await wait(2);
  const worker=workers[0],old=worker.jobs[0];assert.ok(old.input.planes.length);
  plan.buildings[0].solar_zones[1].rect=[14,12,18,16];let settled=false;
  const second=router.run(plan,anchors(plan));second.then(()=>settled=true);assert.equal(await first,null);
  for(let i=0;i<100&&worker.jobs.length<2;i++)await wait(2);
  worker.onmessage({data:{id:old.id,routes:[{id:'stale'}]}});await Promise.resolve();assert.equal(settled,false);
  const current=worker.jobs[1];await handleConduitMessage(current,data=>worker.onmessage({data}));
  assert.deepEqual(await second,solarConduits(plan,anchors(plan)));
  const last=router.run(plan,anchors(plan));router.stop();assert.equal(await last,null);assert.equal(worker.closed,true);
 }finally{router.stop();globalThis.Worker=saved;}
});
check('unavailable and failed workers defer the fallback until after paint',async()=>{
 const saved=globalThis.Worker,raf=globalThis.requestAnimationFrame,frames=[];
 globalThis.Worker=undefined;globalThis.requestAnimationFrame=f=>frames.push(f);
 const router=createConduitRouter({urls:workerUrls}),plan=fixture();let settled=false;
 try {
  const job=router.run(plan,anchors(plan));job.then(()=>settled=true);await Promise.resolve();assert.equal(settled,false);
  assert.equal(frames.length,1);frames.shift()();frames.shift()();await wait(5);
  assert.equal(settled,false,'fallback itself waits for another paint opportunity');
  frames.shift()();frames.shift()();assert.equal((await Promise.race([job,wait(500).then(()=>{throw Error('fallback did not settle; frames '+frames.length);})])).length,1);
 }finally{router.stop();globalThis.Worker=saved;globalThis.requestAnimationFrame=raf;}
 class BrokenWorker {postMessage(){throw Error('Worker blocked');}terminate(){}}
 globalThis.Worker=BrokenWorker;const broken=createConduitRouter({urls:workerUrls});
 try {assert.equal((await Promise.race([broken.run(plan,anchors(plan)),wait(500).then(()=>{throw Error('failed worker fallback did not settle');})])).length,1);}finally{broken.stop();globalThis.Worker=saved;}
});
check('household fixture: a zone on every roof plane routes on the building, one conduit per roof, quickly',()=>{
 const plan=structuredClone(config.harness_plan),b=plan.buildings[0];
 for(const building of plan.buildings)building.solar_zones=[];
 for(const [i,p] of solarPlanes(b).entries()){
  const uv=p.triangles.flat(),xs=uv.map(p=>p[0]),ys=uv.map(p=>p[1]);let rect=null;
  for(let y=Math.min(...ys)+.5;y+2<Math.max(...ys)&&!rect;y+=1)for(let x=Math.min(...xs)+.5;x+2<Math.max(...xs)&&!rect;x+=1){
   const r=[x,y,x+2,y+2];if(solarCovered(r,p))rect=r;
  }
  if(rect)b.solar_zones.push({id:'bench'+i,roof:p.roof,plane:p.plane,rect});
 }
 plan.solar_source_roof=b.solar_zones[0].roof;plan.solar_source_building=b.id;
 const roofs=new Set(b.solar_zones.filter(z=>z.roof!==plan.solar_source_roof).map(z=>z.roof));
 const started=performance.now(),routes=solarConduits(plan,anchors(plan)),elapsed=performance.now()-started;
 console.log(`    ${routes.length}/${roofs.size} satellite roofs in ${elapsed.toFixed(1)} ms`);
 for(const route of routes){onBuilding(plan,route);
  // No doubling back: consecutive level runs never reverse direction along a ridge.
  for(let i=2;i<route.points.length;i++){const a=route.points[i-2],c=route.points[i-1],d=route.points[i];
   if(Math.abs(a[2]-c[2])<1e-6&&Math.abs(c[2]-d[2])<1e-6){const u=[c[0]-a[0],c[1]-a[1]],v=[d[0]-c[0],d[1]-c[1]];assert.ok(u[0]*v[0]+u[1]*v[1]>-1e-6,'doubles back along a ridge in '+route.id+' '+JSON.stringify(route.points));}}}
 assert.equal(new Set(routes.map(r=>r.id)).size,routes.length,'one conduit per roof');
 assert.ok(routes.length>=roofs.size-2,`nearly every roof routes: ${routes.length}/${roofs.size}`);
 assert.ok(elapsed<150,`route computation ${elapsed.toFixed(1)} ms`);
});
let failed=0;for(const[n,f]of checks)try{await f();console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
console.log(`${checks.length-failed}/${checks.length} solar conduit ridge checks passed`);process.exit(failed?1:0);
"""

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ.setdefault('CHAUFFEUR_DATA_DIR', str(Path(__file__).parent / '.conduit_test_data'))
    from services import twin_plan, twin_model_bridge
    fixture = Path(__file__).parent / 'fixtures/twin_model/household-2026-11-09.json'
    plan = twin_model_bridge.flatten(twin_model_bridge.assemble(twin_plan.normalize(json.loads(fixture.read_text(encoding='utf-8')))[0])[0])
    sys.exit(run(DRIVER, {'harness_plan': plan}))
