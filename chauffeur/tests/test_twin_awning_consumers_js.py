"""Supported roofs retain independent rain, gutter and solar consumers (Node)."""
import argparse
import os
import sys
from twin_live_node_rig import PRELUDE, ROOT
from twin_editor_dom import run_node
from test_twin_awning_golden_js import baseline_sources

os.environ.pop('HA_BASE_URL', None)

DRIVER = r"""
globalThis.consumerSnapshots={gutter:[],extract:[],clip:[],catchment:[],sky:[]};
const replacements={
 gutter_group:['static/twin/gutters.js','base=cached?.positions?cached:roofMeshGroups(sections)','base=cached?.positions?cached:roofMesh(sections)'],
 eave_extract:['static/twin/sky/eave_streams.js','{...roofMeshGroups(sections),sections},groups','{...roofMesh(sections),sections},groups'],
 eave_clip:['static/twin/sky/eave_streams.js','roofMeshGroups(frame.b.roof?.sections||[])','roofMesh(frame.b.roof?.sections||[])'],
 eave_catchment:['static/twin/sky/eave_streams.js','{ ...roofMeshGroups(sections), sections }','{ ...roofMesh(sections), sections }'],
 sky_group:['static/twin/sky/sky_cover.js','roofMeshGroups(b.roof?.sections||[]).positions','roofMesh(b.roof?.sections||[]).positions'],
 gutter_walled:['static/twin/gutters.js','ctx.hasSupported?sections.filter(s=>!isSupported(s)):sections','sections'],
};
registerHooks({load(url,ctx,next){const result=next(url,ctx);let source=String(result.source);
 const mutation=replacements[config.mutation];
 if(mutation&&url===file(mutation[0])){
  assert.ok(source.includes(mutation[1]),'mutation anchor '+config.mutation);
  source=source.replace(mutation[1],mutation[2]);
  if(config.mutation!=='gutter_walled')source=source.replace('import { roofMeshGroups','import { roofMesh, roofMeshGroups');
 }
 const capture=(anchor,statement)=>{assert.ok(source.includes(anchor),'runtime capture '+anchor);source=source.replace(anchor,statement+anchor);};
 if(url===file('static/twin/gutters.js')){
  capture('const eaveAttachments=cached?',`globalThis.consumerSnapshots.gutter.push({positions:Array.from(base.positions),section:Array.from(base.section)});\n    `);
  source+='\nexport const consumerProbes={segmentOrigin,sampleAt,source};';
 }
 if(url===file('static/twin/sky/eave_streams.js')){
  capture('for(let t=0;t<envelope.section.length;t++){',`globalThis.consumerSnapshots.extract.push({positions:Array.from(envelope.positions),section:Array.from(envelope.section)});\n    `);
  capture('for(let t=0;t<positions.length;t+=9){',`globalThis.consumerSnapshots.clip.push(Array.from(positions));\n    `);
  capture('const tris = [];',`globalThis.consumerSnapshots.catchment.push(envelope?{positions:Array.from(envelope.positions),section:Array.from(envelope.section)}:null);\n    `);
 }
 if(url===file('static/twin/sky/sky_cover.js'))capture('staticParts.push([b.id',`globalThis.consumerSnapshots.sky.push(Array.from(roofPositions));\n    `);
 return {...result,source};
}});
const baselineUrls=new Map(),baselinePaths=Object.keys(config.sources||{});
for(const [path,original] of Object.entries(config.sources||{})){
 const source=original.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
  const url=new URL(s,file(path)).href,ref=baselinePaths.find(p=>file(p)===url);
  return a+(ref?'baseline:'+ref:url)+b;
 });baselineUrls.set(path,'data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
}
registerHooks({resolve(spec,ctx,next){return spec.startsWith('baseline:')?{url:baselineUrls.get(spec.slice(9)),shortCircuit:true}:next(spec,ctx);}});
const {solarPlanes,solarCovered}=await import(file('static/twin/twin_solar.js'));
const {buildingFootprint}=await import(file('static/twin/twin_ground.js'));
const {extractEaves,createEaveLandingSampler,eaveInstances}=await import(file('static/twin/sky/eave_streams.js'));
const {createSkyCover}=await import(file('static/twin/sky/sky_cover.js'));
const {createSplashSampler}=await import(file('static/twin/sky/precipitation.js'));
const {gutterRuns,downspouts,consumerProbes}=await import(file('static/twin/gutters.js'));
const {energyPlace}=await import(file('static/twin/live/energy.js'));
const {roofMeshGroups}=await import(file('static/twin/twin_roof.js'));
const baselineGutters=await import('baseline:static/twin/gutters.js');
const results=[];
const check=async(name,f)=>{try{await f();results.push({name,ok:true});console.log('PASS '+name);}catch(e){results.push({name,ok:false,error:String(e.stack)});console.log('FAIL '+name+' '+e.message);}};
const section=(id,rect,extra={})=>({id,roof:id,level:'L1',kind:'shed',low_side:'y0',rect,plate:10,pitch:3,overhang:1,...extra});
const supported=extra=>section('awning',[0,-6,20,0],{support:{kind:'bracket'},host:{wall:'host',edge:2},plate:8,...extra});
const building=sections=>({id:'b',position:[0,0],rotation:0,base:0,levels:[],walls:[],rooms:[],roof:{sections}});
const plan=b=>({buildings:[b]});
await check('row16 free-standing roof supplies its footprint',()=>{
 const b=building([supported({rect:[30,40,50,46],host:undefined,support:{kind:'post'}})]);
 assert.deepEqual(buildingFootprint(b),[[30,40],[50,40],[50,46],[30,46]]);
 const unchanged=building([section('ordinary',[2,3,4,5])]);assert.deepEqual(buildingFootprint(unchanged),[]);
});
await check('row14 mixed walled supported walled solar planes keep both independent envelopes',()=>{
 const a=section('first',[0,0,20,12]),c=section('last',[30,0,50,12]);
 for(const plate of [5,25]){
  const aw=supported({rect:[0,0,20,12],plate}),base=solarPlanes(building([a,c])),mixed=solarPlanes(building([a,aw,c]));
  assert.deepEqual(mixed.filter(p=>p.roof!=='awning'),base,'walled solar clipping must not see awning '+plate);
  assert.deepEqual(mixed.filter(p=>p.roof==='awning'),solarPlanes(building([aw])),'awning retains own full solar plane '+plate);
  assert.ok(solarCovered([2,2,4,4],mixed.find(p=>p.roof==='awning')));
 }
});
await check('supported eaves and gutter identities use original mixed indices',()=>{
 const first=section('first',[0,0,20,12],{gutters:{y0:true}}),last=section('last',[30,0,50,12],{gutters:{y0:true}}),aw=supported({rect:[60,0,80,6],gutters:{y0:true}});
 const p=plan(building([first,aw,last])),base=plan(building([first,last]));
 const identity=(p,e)=>({...e,section:p.buildings[0].roof.sections[e.section].id});
 assert.deepEqual(extractEaves(p).filter(e=>e.section!==1).map(e=>identity(p,e)),extractEaves(base).map(e=>identity(base,e)));
 assert.ok(extractEaves(p).some(e=>e.section===1),'supported roof emits exposed eaves');
 const own=gutterRuns(plan(building([aw]))).map(r=>({...r,id:r.id}));
 const runs=gutterRuns(p);assert.ok(runs.some(r=>r.segments.some(s=>s.roof==='awning')),'supported gutter run');
 assert.equal(runs.filter(r=>r.segments.some(s=>s.roof==='awning')).length,own.length);
});
await check('rain landing sampler sees a supported roof below an overlapping walled roof',()=>{
 const aw=supported({rect:[0,0,20,12],plate:8}),upper=section('upper',[0,0,20,12],{plate:20}),b=building([upper,aw]);
 const hit=createEaveLandingSampler(plan(b))([10*FT,15*FT,-6*FT]);
 assert.equal(hit.kind,'roof');assert.ok(Math.abs(hit.height-9.5*FT)<1e-5,JSON.stringify(hit));
 const cover=createSkyCover(plan(b));assert.equal(cover.open(10*FT,7*FT,-6*FT),0);
});
await check('supported energy places use the stored floor independently of height',()=>{
 const aw=supported({rect:[30,0,50,8],level:'L1',plate:30}),b=building([section('main',[0,0,20,12]),aw]);
 b.levels=[{id:'L1',elevation:0,ceiling:8,outline:[[0,0],[20,0],[20,12],[0,12]]},{id:'L2',elevation:10,ceiling:8}];
 assert.deepEqual(energyPlace(plan(b),[40,4,31]),{level:'b:L1'});
});
await check('supported energy places do not steal a point closer to a walled roof',()=>{
 const main=section('main',[0,0,20,12],{plate:10}),aw=supported({rect:[0,0,20,12],plate:8}),b=building([main]);
 b.levels=[{id:'L1',elevation:0,ceiling:8,outline:[[0,0],[20,0],[20,12],[0,12]]}];
 const before=energyPlace(plan(b),[10,4,11]);assert.deepEqual(before,{roof:'b'});
 b.roof.sections=[main,aw];assert.deepEqual(energyPlace(plan(b),[10,4,11]),before);
 assert.deepEqual(energyPlace(plan(b),[10,4,9]),{level:'b:L1'},'the nearer awning still uses its floor');
 assert.deepEqual(energyPlace(plan(b),[10,4,10]),before,'a tied walled plane retains its identity');
 b.roof.sections=[aw,main];assert.deepEqual(energyPlace(plan(b),[10,4,11]),before,'input order does not choose a roof');
 assert.deepEqual(energyPlace(plan(b),[10,4,10]),before,'ties are independent of input order');
});
await check('supported gutters mount only to their host wall, otherwise retain hanging endpoint',()=>{
 const aw=supported({rect:[0,0,20,6],plate:8,overhang:0,gutters:{y0:true}}),b=building([aw]);
 b.levels=[{id:'L1',elevation:0,ceiling:12,outline:[[0,0],[20,0],[20,6],[0,6]]}];
 b.walls=[{id:'wrong',level:'L1',from:[0,0],to:[20,0],height:12,exterior:true},{id:'host',level:'L1',from:[0,6],to:[20,6],height:12,exterior:true}];
 let drops=downspouts(plan(b),gutterRuns(plan(b)));assert.ok(drops.length);
 // The host is too far away: an unrelated nearby wall cannot acquire this awning.
 assert.ok(drops.every(d=>d.mount!=='wall'),JSON.stringify(drops.map(d=>({mount:d.mount,flags:d.flags}))));
 aw.host={wall:'wrong',edge:0};drops=downspouts(plan(b),gutterRuns(plan(b)));assert.ok(drops.some(d=>d.mount==='wall'));
 aw.overhang=6;aw.edges=Array.from({length:4},()=>({overhang_ft:0}));
 drops=downspouts(plan(b),gutterRuns(plan(b)));assert.ok(drops.some(d=>d.mount==='wall'),'mount uses the edge override rather than uniform overhang');
});
await check('row5 gutter posts preserve the walled maximum and only a lower supported underside overrides it',()=>{
 const high=section('high',[0,0,20,12],{plate:20,gutters:{y0:true}}),low=section('low',[0,0,20,6],{plate:8,overhang:0}),b=building([high,low]);
 b.porches=[{id:'porch',polygon:[[-2,-2],[22,-2],[22,2],[-2,2]],floor:0,columns:[{at:[0,0],size:.5},{at:[20,0],size:.5}]}];
 const highDrops=()=>downspouts(plan(b),gutterRuns(plan(b))).filter(d=>d.edge.roof==='high');
 const before=highDrops();assert.ok(before.some(d=>d.mount==='post'),JSON.stringify(before));
 const aw=supported({rect:[0,0,20,6],plate:30,overhang:0,host:undefined});
 b.roof.sections=[high,low,aw];assert.deepEqual(highDrops(),before,'an awning above today\'s post top cannot raise it');
 aw.plate=-2;assert.deepEqual(highDrops(),before,'a roof below the floor cannot cap this post');
 aw.plate=12;const lowered=highDrops();assert.ok(lowered.length);assert.ok(lowered.every(d=>d.mount!=='post'),'a lower supported underside prevents mounting above the post top');
});
await check('I1 flat and shed awnings cut from a room preserve baseline recessed gutter post paths',()=>{
 const high=section('high',[0,0,20,12],{plate:20,gutters:{y0:true}}),b=building([high]);
 b.levels=[{id:'L1',elevation:0,ceiling:8,outline:[[0,0],[20,0],[20,12],[0,12]]}];
 b.porches=[{id:'porch',polygon:[[-2,-2],[22,-2],[22,2],[-2,2]],floor:0,columns:[{at:[.6,.6],size:.5},{at:[19.4,.6],size:.5}]}];
 const drops=()=>downspouts(plan(b),gutterRuns(plan(b))).filter(d=>d.edge.roof==='high');
 const baselineDrops=()=>baselineGutters.downspouts(plan(b),baselineGutters.gutterRuns(plan(b))).filter(d=>d.edge.roof==='high');
 assert.ok(drops().some(d=>d.mount==='post'));
 assert.deepEqual(drops(),baselineDrops(),'the original post routes match 0ec59a62');
 for(const kind of ['flat','shed']){
  b.roof.sections=[high,supported({kind,rect:[0,-4,20,3],plate:6,pitch:kind==='flat'?0:3})];
  const actual=drops(),expected=baselineDrops();
  assert.ok(actual.some(d=>d.mount==='post'),'no drawn '+kind+' slab covers the recessed posts inside the cut room');
  assert.deepEqual(actual,expected,kind+' keeps exact 0ec59a62 post mounts, paths, outlets and flags with the same physical rain cover');
 }
});
await check('I6 a raised supported roof cannot make a short walled post reach a high gutter',()=>{
 const high=section('high',[1,0,21,12],{plate:20,overhang:0,gutters:{y0:true}}),low=section('low',[-2,-2,.9,2],{kind:'flat',plate:8,overhang:0}),b=building([high,low]);
 b.porches=[{id:'porch',polygon:[[-2,-2],[23,-2],[23,2],[-2,2]],floor:0,columns:[{at:[0,0],size:.5}]}];
 const drops=()=>downspouts(plan(b),gutterRuns(plan(b))).filter(d=>d.edge.roof==='high');
 const before=drops();assert.ok(before.length);assert.ok(before.every(d=>d.mount!=='post'));
 b.roof.sections.push(supported({kind:'flat',rect:[-1,-1,.9,.9],plate:30,pitch:0,overhang:0}));
 assert.deepEqual(drops(),before,'the supported roof is above the original walled cap');
});
await check('I6 every uncached consumer retains the complete grouped mesh and original section labels',()=>{
 const sections=[section('first',[0,0,20,12]),supported({rect:[0,0,20,12],plate:5,gutters:{y0:true}}),section('last',[30,0,50,12])],p=plan(building(sections));
 const expected=roofMeshGroups(sections),shape={positions:Array.from(expected.positions),section:Array.from(expected.section)};
 for(const key of Object.keys(consumerSnapshots))consumerSnapshots[key].length=0;
 gutterRuns(p);extractEaves(p);eaveInstances(p);createSkyCover(p);
 for(const key of ['gutter','extract','catchment']){assert.ok(consumerSnapshots[key].length,key+' executes');for(const snapshot of consumerSnapshots[key])assert.deepEqual(snapshot,shape,key+' preserves lower supported triangles and original labels');}
 for(const key of ['clip','sky']){assert.ok(consumerSnapshots[key].length,key+' executes');for(const positions of consumerSnapshots[key])assert.deepEqual(positions,shape.positions,key+' preserves lower supported triangles');}
});
await check('R1 walled rain paths match 0ec59a62 including splits, spouts and unaffected roofs',()=>{
 const main=section('main',[0,0,32,12],{gutters:{y0:true}}),other=section('other',[50,0,70,12],{gutters:{y0:true}}),b=building([main,other]);
 b.levels=[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[32,0],[32,12],[0,12]]}];
 b.walls=b.levels[0].outline.map((from,i,poly)=>({id:'w'+i,from,to:poly[(i+1)%4],level:'L1',height:10,exterior:true,thickness:.5}));
 const p=plan(b),read=(module,p)=>{const runs=module.gutterRuns(p);return {runs,spouts:module.downspouts(p,runs)};};
 const before=read(baselineGutters,p);assert.deepEqual(read({gutterRuns,downspouts},p),before);
 assert.equal(before.runs.find(r=>r.segments.some(s=>s.roof==='main')).length,34);
 const aw=supported({rect:[10,-3,20,1],plate:20});b.roof.sections.push(aw);
 const above=read({gutterRuns,downspouts},p);assert.deepEqual(above,read(baselineGutters,p),'overlapping rain path keeps existing physical clipping');
 const lengths=above.runs.filter(r=>r.segments.some(s=>s.roof==='main')).map(r=>r.length).sort((a,b)=>a-b);
 assert.equal(lengths.length,2);assert.ok(Math.abs(lengths[0]-10)<1e-5&&Math.abs(lengths[1]-12)<1e-5,JSON.stringify(lengths));
 assert.deepEqual(above.runs.filter(r=>r.segments.some(s=>s.roof==='other')),before.runs.filter(r=>r.segments.some(s=>s.roof==='other')));
 assert.deepEqual(above.spouts.filter(d=>d.edge.roof==='other'),before.spouts.filter(d=>d.edge.roof==='other'));
 aw.rect=[-3,-5,4,-.5];aw.plate=5;aw.overhang=0;
 const below=read({gutterRuns,downspouts},p);assert.deepEqual(below,read(baselineGutters,p),'awning below a corner keeps existing landing and outlet decisions');
 assert.notDeepEqual(below.spouts.filter(d=>d.edge.roof==='main'),before.spouts.filter(d=>d.edge.roof==='main'));
 assert.deepEqual(before.spouts.filter(d=>d.edge.roof==='main').map(d=>[d.edge.fraction,d.outlet.lands]),[[0,'grass']]);
 assert.deepEqual(below.spouts.filter(d=>d.edge.roof==='main').map(d=>[d.edge.fraction,d.outlet.lands]),[[1,'grass']]);
 assert.deepEqual(below.runs.filter(r=>r.segments.some(s=>s.roof==='other')),before.runs.filter(r=>r.segments.some(s=>s.roof==='other')));
 assert.deepEqual(below.spouts.filter(d=>d.edge.roof==='other'),before.spouts.filter(d=>d.edge.roof==='other'));
 console.log('R1_PATHS',JSON.stringify({before:before.spouts.filter(d=>d.edge.roof==='main'),below:below.spouts.filter(d=>d.edge.roof==='main'),splitFt:lengths}));
});
await check('per-edge overhangs retain real supported eaves and gutter edges',()=>{
 const aw=supported({rect:[0,0,20,6],overhang:1,edges:[{overhang_ft:0},{},{},{}],gutters:{y0:true}}),p=plan(building([aw]));
 const edges=extractEaves(p);assert.equal(edges.length,1);assert.ok(edges.every(e=>Math.abs(e.a[2])<1e-6&&Math.abs(e.b[2])<1e-6));
 assert.ok(gutterRuns(p).length,'zero-overhang eave retains its gutter');
});
await check('per-edge gutter origins and landing eaves use the actual roof bounds',()=>{
 const a=section('a',[0,0,10,10],{kind:'flat',plate:10,overhang:10,edges:Array.from({length:4},()=>({overhang_ft:0}))}),c=section('c',[12,0,14,10],{kind:'flat',plate:15,overhang:0});
 const ctx={f:{local:()=>[13,5,10]},info:new Map([['null:0:p',{sections:[a,c]}]]),sections:[a,c]};
 assert.equal(consumerProbes.segmentOrigin(ctx,{roof:null,edge:0,porch:'p',a:[0,0,0],b:[0,0,0]}),'section:0');
 const s=section('eave',[0,0,10,10],{plate:10,pitch:12,overhang:2,edges:[{overhang_ft:0},{},{},{}]});
 const context={f:{base:0,local:()=>[5,5,20]},sections:[s]};
 const sample=consumerProbes.sampleAt({sample:()=>({height:0,kind:'ground'}),contexts:new Map([['b',context]])},[0,20*FT,0]);
 assert.equal(sample.roofEave,10*FT);
 const src=consumerProbes.source({roofs:[{edges:[{gutter:true}]}]},section(undefined,[0,0,10,10]),'y0');
 assert.equal(src.record,undefined,'an undefined section id never matches an undefined carrier id');
});
await check('two storeys retain independently exposed supported gutter and rain identities',()=>{
 const a=supported({rect:[30,0,50,6],level:'L1',gutters:{y0:true}}),upper=supported({id:'upper-awning',roof:'upper-awning',rect:[60,0,80,6],level:'L2',plate:18,gutters:{y0:true}}),b=building([a,upper]);
 b.levels=[{id:'L1',elevation:0,ceiling:8},{id:'L2',elevation:10,ceiling:8}];
 const p=plan(b),eaves=extractEaves(p),runs=gutterRuns(p);
 assert.deepEqual(new Set(eaves.map(e=>b.roof.sections[e.section].level)),new Set(['L1','L2']));
 assert.deepEqual(new Set(runs.flatMap(r=>r.segments.map(s=>s.roof))),new Set(['awning','upper-awning']));
 assert.deepEqual(energyPlace(p,[40,3,8.75]),{level:'b:L1'});
 assert.deepEqual(energyPlace(p,[70,3,18.75]),{level:'b:L2'});
});
await check('precipitation fallback and cached snapshots catch rain on a free-standing supported roof',()=>{
 const aw=supported({rect:[0,0,20,12],host:undefined}),b=building([aw]),p=plan(b);
 for(const roofs of [new Map(),new Map([['b',{sections:[aw]}]])]){
  const sample=createSplashSampler(p,roofs),hit=sample(10*FT,-6*FT);
  assert.equal(hit?.kind,'roof');assert.ok(Math.abs(hit.position[1]-(9.5*FT+.006))<1e-6);
 }
});
await check('a walled-only precipitation fallback retains its original no-snapshot path',()=>{
 const p=plan(building([section('main',[0,0,20,12])]));
 assert.equal(createSplashSampler(p)(10*FT,-6*FT),null);
});
await check('legacy awning extensions retain gutter and downspout consumers without roof records',()=>{
 const b=building([section('r',[0,0,20,12])]),outline=[[0,0],[20,0],[20,12],[0,12]];
 b.levels=[{id:'L1',elevation:0,ceiling:10,outline}];
 b.walls=outline.map((from,i)=>({id:'w'+i,from,to:outline[(i+1)%4],level:'L1',height:10,exterior:true,thickness:.5}));
 b.roof.extensions=[{id:'old-awning',kind:'awning',section:'r',wall:'w0',x0:5,x1:15,depth:3,eave:8,pitch:3,gutter:true}];
 const p=plan(b),before=JSON.stringify(p),runs=gutterRuns(p),drops=downspouts(p,runs);
 assert.ok(runs.some(r=>r.segments.some(s=>s.porch==='old-awning')));
 assert.ok(drops.some(d=>d.edge.porch==='old-awning'));assert.equal(JSON.stringify(p),before);
});
console.log(JSON.stringify({results}));if(results.some(r=>!r.ok))process.exitCode=1;
"""

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--mutation',choices=['gutter_group','eave_extract','eave_clip','eave_catchment','sky_group','gutter_walled'])
    args=parser.parse_args()
    # Install observation/mutation hooks before the rig eagerly loads live.js.
    # This file exercises pure consumers and never mounts that live layer.
    anchor="const liveModule = await import(file('static/twin/live/live.js'));"
    assert PRELUDE.count(anchor)==1
    code, output=run_node(PRELUDE.replace(anchor,'const liveModule=null;')+DRIVER,
        {'root': ROOT.as_posix(), 'sources': baseline_sources(), 'mutation': args.mutation})
    print(output,end='')
    sys.exit(code or 0)
