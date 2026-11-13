"""Rendered-surface conduit graph and scene adapter, executed in node."""
import json
import os
from pathlib import Path
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {solarConduits,planConduitSurfaces,conduitInput,createConduitRouter,buildSurfaceGraph,surfacePath,trianglePoint,CONDUIT_OFFSET:offset}=await import(file('static/twin/live/solar_conduit.js'));
const {energyAnchors,lotPoint,worldPoint}=await import(file('static/twin/live/energy_geometry.js'));
const {groundAt}=await import(file('static/twin/twin_ground.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {solarPlanes,solarCovered}=await import(file('static/twin/twin_solar.js'));
const {handleConduitMessage}=await import(file('static/twin/live/solar_conduit_worker.js'));
const {routeConduits}=await import(file('static/twin/live/solar_conduit_core.js'));
const checks=[],check=(n,f)=>checks.push([n,f]),dist=(a,b)=>Math.hypot(...a.map((v,i)=>v-b[i]));
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);
function quad(a,b,c,d,kind='roof',building='b') {return [{points:[a,b,c],kind,building},{points:[a,c,d],kind,building}];}
function surfaceCheck(points,triangles) {
 assert.ok(points?.length>1,'connected path');
 for(let i=0;i<points.length;i++)for(let t=0;t<=1;t+=.05){
  const a=points[Math.max(0,i-1)],b=points[i],p=a.map((v,j)=>v+(b[j]-v)*t);
  const d=Math.min(...triangles.map(f=>dist(p,trianglePoint(p,f.points))));
  assert.ok(d<=2.5/12+1e-6,JSON.stringify(p)+' distance from shell '+d);
 }
}
function gable() {return [...quad([-10,0,10],[0,0,15],[0,20,15],[-10,20,10]),
 ...quad([0,0,15],[10,0,10],[10,20,10],[0,20,15])];}
check('ridge preference: opposite gable planes rise to the ridge instead of descending to eaves',()=>{
 const triangles=gable(),path=surfacePath(buildSurfaceGraph(triangles),[-6,8,12],[6,12,12]);surfaceCheck(path,triangles);
 assert.ok(path.some(p=>Math.abs(p[0])<.1&&p[2]>=15),'ridge reached');
 assert.ok(path.every(p=>p[2]>=12),'never takes the eave detour: '+JSON.stringify(path));
});
check('climbing: lower roof abuts the interior of a taller wall, then reaches the upper roof',()=>{
 const triangles=[...quad([-10,2,5],[0,2,5],[0,8,5],[-10,8,5]),
 ...quad([0,0,0],[0,10,0],[0,10,10],[0,0,10],'wall'),
 ...quad([0,0,10],[10,0,10],[10,10,10],[0,10,10])];
 const path=surfacePath(buildSurfaceGraph(triangles),[-5,5,5],[5,5,10]);surfaceCheck(path,triangles);
 assert.ok(path.some((p,i)=>i&&p[2]>9&&path[i-1][2]<6&&Math.abs(p[0])<.2&&Math.abs(path[i-1][0])<.2),'climbs wall at the roof junction');
 assert.ok(path.at(-1)[2]>10);
});
check('retained lower roofs cannot shortcut beneath a taller roof or dormer',()=>{
 const walls=[...quad([-1,0,5],[-1,10,5],[-1,10,10],[-1,0,10],'wall'),
 ...quad([1,10,5],[1,0,5],[1,0,10],[1,10,10],'wall')];
 const upper=quad([-1,0,10],[1,0,10],[1,10,10],[-1,10,10]);
 const triangles=[...quad([-10,0,5],[10,0,5],[10,10,5],[-10,10,5]),...upper,...walls];
 const path=surfacePath(buildSurfaceGraph(triangles),[-5,5,5],[5,5,5]);
 const exposed=[...quad([-10,0,5],[-1,0,5],[-1,10,5],[-10,10,5]),
 ...quad([1,0,5],[10,0,5],[10,10,5],[1,10,5]),...upper,...walls];
 surfaceCheck(path,exposed);assert.ok(path.some(p=>p[2]>=10),'goes over the taller roof');
});
check('on the surface: welded seams and split T junctions keep every bend and span within 2.5 inches',()=>{
 const triangles=[...quad([0,0,10],[10,0,10],[10,10,10],[0,10,10]),
 ...quad([10,2,10],[16,2,13],[16,8,13],[10,8,10])];
 // There is no vertex at (10,2,10) on the left quad: its edge must be split.
 const graph=buildSurfaceGraph(triangles),path=surfacePath(graph,[2,5,10],[14,5,12]);surfaceCheck(path,triangles);
 assert.ok(graph.edges.some(e=>e.splits.length>2),'receiving edge was split');
 const almost=triangles.map(t=>({...t,points:t.points.map(p=>p[0]>=10?[p[0]+.04,p[1],p[2]]:p)}));
 surfaceCheck(surfacePath(buildSurfaceGraph(almost),[2,5,10],[14.04,5,12]),almost);
});
check('flat faces can cross directly; hips and ridges beat a long interior diagonal detour',()=>{
 const flat=quad([0,0,10],[10,0,10],[10,10,10],[0,10,10]);
 const direct=surfacePath(buildSurfaceGraph(flat),[2,2,10],[8,8,10]);surfaceCheck(direct,flat);
 close(direct.slice(1).reduce((s,p,i)=>s+dist(p,direct[i]),0),Math.sqrt(72));
 const a=[-10,-10,10],b=[10,-10,10],c=[10,10,10],d=[-10,10,10],l=[-4,0,16],r=[4,0,16];
 const hip=[...quad(a,b,r,l),...quad(r,c,d,l),{points:[a,l,d],kind:'roof',building:'b'},{points:[b,c,r],kind:'roof',building:'b'}];
 const path=surfacePath(buildSurfaceGraph(hip),[-6,-4,13.6],[-6,4,13.6]);surfaceCheck(path,hip);
 assert.ok(path.some(p=>Math.abs(p[0]+4)<.2&&Math.abs(p[1])<.2&&p[2]>=16),'uses hip/ridge junction');
 assert.ok(path.every(p=>p[2]>13),'no long diagonal to an eave');
});
const section=(id,rect)=>({id,kind:'flat',rect,pitch:0,plate:10,overhang:0,level:'L1'});
function fixture(two=false) {
 const b={id:'b',position:[0,0],rotation:0,base:0,levels:[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[20,0],[20,20],[0,20]]}],walls:[],rooms:[],stairs:[],
  roof:{sections:[section('source',[0,0,10,20]),section('remote',[10,0,20,20])]},
  solar_zones:[{id:'main',roof:'source',plane:[0,0,10],rect:[2,2,6,6]},{id:'sat',roof:'remote',plane:[0,0,10],rect:[12,12,16,16]}]};
 const plan={buildings:[b],solar_source_roof:'source',solar_source_building:'b'};
 if(two){b.solar_zones.pop();const other=structuredClone(b);other.id='other';other.position=[40,0];
 other.solar_zones=[{id:'away',roof:'source',plane:[0,0,10],rect:[2,2,6,6]}];plan.buildings.push(other);}
 return plan;
}
const anchors=plan=>energyAnchors({plan},{markers:[]},{cars:[]});
function shell(building,plan) {
 const id=building.id, walls=[...quad([0,0,0],[20,0,0],[20,0,10],[0,0,10],'wall',id),
 ...quad([20,0,0],[20,20,0],[20,20,10],[20,0,10],'wall',id),
 ...quad([20,20,0],[0,20,0],[0,20,10],[20,20,10],'wall',id),
 ...quad([0,20,0],[0,0,0],[0,0,10],[0,20,10],'wall',id)];
 return [...quad([0,0,10],[20,0,10],[20,20,10],[0,20,10],'roof',id),...walls]
  .map(t=>({...t,points:t.points.map(p=>lotPoint(building,p,plan))}));
}
function sceneFor(plan,triangles=plan.buildings.flatMap(b=>shell(b,plan))) {return {triangles};}
check('two buildings use ground only across the gap and preserve the shared source anchor and per-zone entity',()=>{
 const plan=fixture(true);plan.buildings[1].solar_zones[0].entity='sensor.zone';
 plan.site={terraces:[{polygon:[[26,-5],[34,-5],[34,25],[26,25]],height:3,blend:2}]};
 const triangles=plan.buildings.flatMap(b=>shell(b,plan)),scene=sceneFor(plan,triangles),a=anchors(plan);
 const [route]=solarConduits(plan,a,scene);assert.ok(route);assert.equal(route.entity,'sensor.zone');assert.equal(route.id,'other:away');
 assert.deepEqual(route.points.at(-1),a.solar);
 const ground=route.points.filter(p=>Math.abs(p[2]-groundAt(plan,...p)-offset)<1e-6);
 assert.ok(ground.some(p=>p[0]>22&&p[0]<38&&p[2]>1),'ground follows terrain in the gap');
 assert.ok(ground.every(p=>p[0]>=20-offset-1e-5&&p[0]<=40+offset+1e-5),'ground never runs round a footprint');
 const above=route.points.filter(p=>p[2]>4);for(const p of above)surfaceCheck([p,p],triangles);
});
check('connected buildings stay on the shared shell and never use ground',()=>{
 const plan=fixture(true);plan.buildings[1].position=[20,0];const scene=sceneFor(plan);
 const [route]=solarConduits(plan,anchors(plan),scene);assert.ok(route);assert.ok(route.points.every(p=>p[2]>=10));
 surfaceCheck(route.points,plan.buildings.flatMap(b=>shell(b,plan)));
});
check('no path or no structural shell skips conduits, with one debug message and no floating fallback',()=>{
 const plan=fixture(),triangles=[...quad([0,0,10],[8,0,10],[8,8,10],[0,8,10]),
 ...quad([12,12,10],[20,12,10],[20,20,10],[12,20,10])];
 let logs=0;const debug=()=>logs++;
 assert.deepEqual(solarConduits(plan,anchors(plan),{triangles,debug}),[]);assert.equal(logs,1);
 assert.deepEqual(solarConduits(plan,anchors(plan),{triangles:[],debug}),[]);assert.equal(logs,2);
 assert.equal(surfacePath(buildSurfaceGraph(triangles),[4,4,10],[14,14,10]),null);
 assert.equal(buildSurfaceGraph(Array(50001).fill(triangles[0])),null);
});
check('a typical several-thousand-triangle roof stays connected within the graph budget',()=>{
 const triangles=[];
 for(let x=0;x<40;x++)for(let y=0;y<40;y++)triangles.push(...quad([x,y,10],[x+1,y,10],[x+1,y+1,10],[x,y+1,10]));
 const started=performance.now(),graph=buildSurfaceGraph(triangles);assert.ok(graph);
 const path=surfacePath(graph,[.5,.5,10],[39.5,39.5,10]);assert.ok(path?.length>1);
 console.log('    3200 triangles graph + path: '+Math.round(performance.now()-started)+' ms');
});
check('plan extraction honours outer joint faces, transforms and ground while excluding interior walls',()=>{
 const plan=fixture(),b=plan.buildings[0];b.position=[30,-20];b.rotation=37;b.base=2;
 plan.site={terraces:[{polygon:[[-100,-100],[100,-100],[100,100],[-100,100]],height:4,blend:0}]};b.foundation={mode:'auto',offset_ft:2};
 b.walls=[{id:'outside',from:[0,0],to:[20,0],level:'L1',exterior:true,thickness:.5,
  footprint:[[0,-.25],[20,-.25],[20,.25],[0,.25]]},
 {id:'inside',from:[0,5],to:[20,5],level:'L1',exterior:false,thickness:.5}];
 const found=planConduitSurfaces(plan).get('b'),walls=found.filter(t=>t.kind==='wall');assert.equal(walls.length,2);
 const expected=lotPoint(b,[0,-.25,0],plan);assert.ok(walls.some(t=>t.points.some(p=>dist(p,expected)<1e-6)));
 const withoutInterior=structuredClone(plan);withoutInterior.buildings[0].walls.pop();assert.deepEqual(planConduitSurfaces(withoutInterior).get('b'),found);
});
check('real generator batching, rotated raised buildings and retained roof surfaces route without generator metadata changes',async()=>{
 const plan=fixture(),b=plan.buildings[0];b.position=[70,-30];b.rotation=37;b.base=2;
 const twin=buildTwin(plan,{materials:{}},'low',{viewing:true});const scene=new THREE.Scene();scene.add(twin.root);
 const surfaces=planConduitSurfaces(plan,new Set(['b'])).get('b');assert.ok(surfaces.length);
 const a=anchors(plan),[route]=solarConduits(plan,a);assert.ok(route);assert.deepEqual(route.points.at(-1),a.solar);surfaceCheck(route.points,surfaces);
 twin.root.traverse(o=>{o.geometry?.dispose();for(const m of [].concat(o.material||[]))m.dispose();});
});
check('multiple source zones preserve their weighted anchor; ghosts, absent and ambiguous sources remain excluded',()=>{
 const plan=fixture(),b=plan.buildings[0];b.solar_zones.push({...b.solar_zones[0],id:'second',rect:[6,8,8,10]});
 const a=anchors(plan),scene=sceneFor(plan),routes=solarConduits(plan,a,scene);assert.equal(routes.length,1);assert.deepEqual(routes[0].points.at(-1),a.solar);
 b.solar_zones[1].state='ghost';assert.deepEqual(solarConduits(plan,anchors(plan),scene),[]);
 assert.deepEqual(solarConduits(plan,{solar:null,source:null},scene),[]);
 b.solar_zones[1].state='settled';plan.solar_source_roof='missing';assert.deepEqual(solarConduits(plan,anchors(plan),scene),[]);
 const ambiguous=fixture(true);delete ambiguous.solar_source_building;assert.deepEqual(solarConduits(ambiguous,anchors(ambiguous),sceneFor(ambiguous)),[]);
});
check('a weighted anchor below opposite source slopes is projected onto the rendered source roof',()=>{
 const plan=fixture(),b=plan.buildings[0];
 b.roof.sections=[{...section('source',[-10,0,10,20]),kind:'gable',ridge:'y',pitch:6},section('remote',[10,0,20,20])];
 b.solar_zones=[{id:'left',roof:'source',plane:[.5,0,15],rect:[-8,2,-4,6]},
 {id:'right',roof:'source',plane:[-.5,0,15],rect:[4,2,8,6]},
 {id:'sat',roof:'remote',plane:[0,0,10],rect:[12,2,16,6]}];
 const triangles=[...gable(),...quad([10,0,10],[20,0,10],[20,20,10],[10,20,10])];
 const a=anchors(plan),[route]=solarConduits(plan,a,sceneFor(plan,triangles));assert.ok(route);
 assert.ok(dist(a.solar,route.points.at(-1))>1,'buried weighted centre is moved onto its source roof');surfaceCheck(route.points,triangles);
});
check('plan gable, lower porch and tall exterior wall form a connected coarse surface',()=>{
 const plan=fixture(),b=plan.buildings[0];
 b.roof.sections=[{...section('source',[0,0,20,20]),kind:'gable',ridge:'x',pitch:6},
 {...section('porch',[-8,2,0,18]),plate:5}];
 b.walls=[{id:'side',from:[0,20],to:[0,0],level:'L1',exterior:true,height:10,thickness:.5}];
 b.solar_zones=[{id:'main',roof:'source',plane:[0,.5,10],rect:[3,2,7,6]},
 {id:'porch',roof:'porch',plane:[0,0,5],rect:[-6,6,-2,10]}];
 const surfaces=planConduitSurfaces(plan).get('b'),[route]=solarConduits(plan,anchors(plan));
 surfaceCheck(route.points,surfaces);assert.ok(route.points.some(p=>p[2]>10),'climbs from the porch');
 assert.ok(surfaces.length<40,'structural triangles only');
});
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
  const worker=workers[0],old=worker.jobs[0];assert.ok(old.input.triangles.length);
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
check('household fixture with 26 satellites routes on coarse planes within the timing budget',()=>{
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
 globalThis.CONDUIT_PROFILE=true;
 const started=performance.now(),a=anchors(plan),anchorTime=performance.now(),input=conduitInput(plan,a),inputTime=performance.now(),routes=routeConduits(input,{groundAt}),elapsed=performance.now()-started;
 globalThis.CONDUIT_PROFILE=false;
 console.log(`    stages anchors ${(anchorTime-started).toFixed(1)}; surfaces ${(inputTime-anchorTime).toFixed(1)}; graph/routes ${(performance.now()-inputTime).toFixed(1)} ms`);
 const expected=b.solar_zones.filter(z=>z.roof!==plan.solar_source_roof).length;
 const counts=[...planConduitSurfaces(plan)].map(([id,t])=>`${id}: ${t.length} (${t.filter(f=>f.kind==='roof').length} roof, ${t.filter(f=>f.kind==='wall').length} wall)`);
 console.log('    coarse surfaces '+counts.join('; ')+`; ${routes.length}/${expected} satellites in ${elapsed.toFixed(1)} ms`);
 console.log('    missing',input.zones.filter(z=>!routes.some(r=>r.id===z.id)).map(z=>({id:z.id,roof:b.solar_zones.find(s=>z.id.endsWith(':'+s.id))?.roof})));console.log('    sections',b.roof.sections.map(s=>({id:s.id,dormer:s.dormer_of,level:s.level,plate:s.plate})));assert.equal(expected,26);assert.equal(routes.length,expected);
 assert.ok(elapsed<300,`route computation ${elapsed.toFixed(1)} ms exceeds 300 ms guard (target 150 ms)`);
});
let failed=0;for(const[n,f]of checks)try{await f();console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
console.log(`${checks.length-failed}/${checks.length} solar conduit surface checks passed`);process.exit(failed?1:0);
"""

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ.setdefault('CHAUFFEUR_DATA_DIR', str(Path(__file__).parent / '.conduit_test_data'))
    from services import twin_plan, twin_model_bridge
    fixture = Path(__file__).parent / 'fixtures/twin_model/household-2026-11-09.json'
    plan = twin_model_bridge.flatten(twin_model_bridge.assemble(twin_plan.normalize(json.loads(fixture.read_text(encoding='utf-8')))[0])[0])
    sys.exit(run(DRIVER, {'harness_plan': plan}))
