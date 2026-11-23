"""Execute lazy/eager landing parity, source culling and sampler-local caching."""
import json
import os
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
globalThis.capBuilds=new Map();globalThis.landingQueries=0;globalThis.compareLandings=false;
registerHooks({load(url,ctx,next){const r=next(url,ctx);let source=String(r.source);
 if(url.endsWith('/pad_edge_geometry.js'))source=source.replace('export function buildPadEdge(', 'function originalBuildPadEdge(')+`
 export function buildPadEdge(...args){const key=args[1].id+':'+args[2];
 globalThis.capBuilds.set(key,(globalThis.capBuilds.get(key)||0)+1);return originalBuildPadEdge(...args);}`;
 if(url.endsWith('/eave_streams.js'))source=source.replace('export function createEaveLandingSampler(', 'export function rawSampler(')+`
 import assert from 'node:assert/strict';
 export function createEaveLandingSampler(plan,roofs,options={}){
  if(!globalThis.compareLandings)return rawSampler(plan,roofs,options);
  const lazy=rawSampler(plan,roofs,{...options,lazyCaps:true}),eager=rawSampler(plan,roofs,{...options,lazyCaps:false});
  return top=>{const a=lazy(top),b=eager(top);globalThis.landingQueries++;
   assert.ok(Math.abs(a.height-b.height)<=1e-9,JSON.stringify({top,a,b}));
   assert.deepEqual(a,b,JSON.stringify({top,a,b}));return a;};}`;
 return {...r,source};}});
const E=await import(file('static/twin/sky/eave_streams.js'));
const C=await import(file('static/twin/sky/wet_caps.js'));
const G=await import(file('static/twin/gutters.js'));
const FT=.3048,rect=(x0,y0,x1,y1)=>[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
function allEaves(plan){
 const p=structuredClone(plan);
 for(const b of p.buildings){for(const r of b.roofs||[])for(const e of r.edges)e.gutter=e.setting==='sloped';
  for(const s of b.roof.sections){s.gutters={};for(const side of (s.kind==='shed'?[s.low_side]:s.kind==='flat'?[]:s.kind==='gable'?(s.ridge==='x'?['y0','y1']:['x0','x1']):['y0','x1','y1','x0']))
   if(!['gable','clip'].includes(s.ends?.[side]))s.gutters[side]=true;}
  for(const a of b.roof.extensions||[])if(a.kind==='awning')a.gutter=true;
  for(const porch of b.porches||[])porch.gutter=true;
 }
 return p;
}
await test('every household placement query matches the eager sampler including roofDetails',()=>{
 globalThis.compareLandings=true;globalThis.landingQueries=0;
 const p=allEaves(input.plan),runs=G.gutterRuns(p),spouts=G.downspouts(p,runs);
 assert.equal(runs.length,22);assert.equal(spouts.length,23);assert.ok(globalThis.landingQueries>100);
 console.log('PLACEMENT_LANDING_QUERIES',globalThis.landingQueries);
});
await test('every household eave stream query matches the eager sampler without roofDetails',()=>{
 globalThis.landingQueries=0;
 const {instances}=E.eaveInstances(input.plan);assert.ok(instances.length>100);assert.ok(globalThis.landingQueries>100);
 console.log('STREAM_LANDING_QUERIES',globalThis.landingQueries);
 globalThis.compareLandings=false;
});

// Owner-like mix: household roofs/decks/beds plus pool/spas, caps, stairs and
// ordered terrain layers. Both wall directions and treads/no-treads occur.
const ownerLike={...structuredClone(input.plan),site:{...structuredClone(input.plan.site),...structuredClone(input.cases.site)}};
ownerLike.site.terraces.push(
 {id:'low-narrow',polygon:rect(58,-.02,72,.02),height:-3,blend:0},
 {id:'blend',polygon:rect(72,-8,85,20),height:7,blend:8},
 {id:'reverse',polygon:rect(78,0,88,12).reverse(),height:3.25,blend:0,edges:[
  {edge:'sharp',wall:{cap:{overhang_in:5,thickness_in:3},thickness_in:12,above_in:5}},
  {edge:'sharp',stair:{treads:false,tread_in:13,riser_in:6}},
  {edge:'sharp',wall:{cap:{},above_in:9}},
  {edge:'sharp',stair:{treads:true,rail:{height:3}}}]});
const caps=C.collectCapSurfaces(ownerLike);
await test('source boxes and height ranges construct no meshes until hit and cache per source',()=>{
 capBuilds.clear();const sample=E.rawSampler(ownerLike);assert.equal(capBuilds.size,0,'default sampler must be lazy');
 sample([-10000,1000,-10000]);assert.equal(capBuilds.size,0);
 capBuilds.clear();const at=C.createCapSurfaceIndex(ownerLike);assert.equal(capBuilds.size,0);
 assert.deepEqual(at(-10000,-10000,1000),[]);assert.equal(capBuilds.size,0);
 assert.deepEqual(at(65,.3,-1000),[]);assert.equal(capBuilds.size,0,'ray below cap bounds');
 const first=at(65,.3,1000);assert.ok(first.length);assert.ok(capBuilds.size>0);
 const built=[...capBuilds];assert.deepEqual(at(65,.3,1000),first);assert.deepEqual([...capBuilds],built);
 // Visit every source, including boxes with empty/nonflat tops, twice.
 for(let pass=0;pass<2;pass++)for(let x=-5;x<105;x+=1)for(let y=-10;y<55;y+=1)at(x,y,1000);
 assert.ok([...capBuilds.values()].every(n=>n===1),JSON.stringify([...capBuilds]));
 const old=[...capBuilds];C.createCapSurfaceIndex(ownerLike)(65,.3,1000);
 assert.notDeepEqual([...capBuilds],old,'a new sampler owns a new cache');
 const diagonal={site:{terraces:[{id:'diagonal',polygon:[[0,0],[100,100],[0,100]],height:2,blend:0,
  edges:[{edge:'sharp',wall:{cap:{}}}]}]}};
 capBuilds.clear();const diagonalAt=C.createCapSurfaceIndex(diagonal);
 diagonalAt(10,90,1000);assert.equal(capBuilds.size,0,'inside the box but outside the diagonal wall footprint');
 diagonalAt(50,50,1000);assert.equal(capBuilds.size,1,'ray on the diagonal wall footprint builds its cap');
});
await test('dense seeded random grid and cap boundaries are exactly equal for both roofDetails modes',()=>{
 let state=0x7183abcf;const random=()=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state/4294967296;};
 let count=0,capHits=0,roofHits=0;
 for(const roofDetails of [false,true]){
  const lazy=E.rawSampler(ownerLike,null,{roofDetails}),eager=E.rawSampler(ownerLike,null,{roofDetails,lazyCaps:false});
  const check=top=>{const a=lazy(top),b=eager(top);count++;if(a.kind==='cap')capHits++;if(a.kind==='roof')roofHits++;
   assert.ok(Math.abs(a.height-b.height)<=1e-9,JSON.stringify({top,a,b}));assert.deepEqual(a,b,JSON.stringify({top,a,b}));};
  for(let i=0;i<120;i++)for(let j=0;j<160;j++){
   const x=-10+(i+random())*130/120,y=-15+(j+random())*180/160;
   for(const h of [-4+random()*12,35])check([x*FT,h*FT,-y*FT]);
  }
  for(const c of caps){
   const centre=c.polygon.reduce((s,p)=>[s[0]+p[0]/c.polygon.length,s[1]+p[1]/c.polygon.length],[0,0]);
   for(const p of [centre,...c.polygon,...c.polygon.map((p,i)=>p.map((v,k)=>(v+c.polygon[(i+1)%c.polygon.length][k])/2))])
    for(const epsilon of [-1e-8,0,1e-8])for(const h of [c.top*FT+.005-1e-10,c.top*FT+.005+1e-10,40*FT])
     check([(p[0]+epsilon)*FT,h,-(p[1]-epsilon)*FT]);
  }
  // Warm cache, order-independent repeated queries and high to low origins.
  for(const top of [[65*FT,30*FT,-.3*FT],[65*FT,2*FT,-.3*FT],[23.5*FT,30*FT,-12*FT]]){check(top);check(top);}
 }
 assert.ok(capHits>100);assert.ok(roofHits>100);console.log('GRID_BOUNDARY_LANDING_QUERIES',count,'CAP_HITS',capHits,'ROOF_HITS',roofHits);
});
finish();
"""

if __name__ == '__main__':
    os.environ.pop('HA_BASE_URL', None)
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    cases = json.loads((ROOT / 'tests/fixtures/twin_model/wet-receivers.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': flatten(assemble(fixture)[0]), 'cases': cases}, timeout=180)
    print(output)
    sys.exit(code or 0)
