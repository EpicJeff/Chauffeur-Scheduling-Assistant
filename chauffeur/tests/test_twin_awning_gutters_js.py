"""Dropped awning faces clear pipe paths; untouched rain output stays exact."""
from pathlib import Path
import subprocess

from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '500a1a377de71ff0d07bb38ab70e7a8c76fe90d8'
DRIVER = PRELUDE + r"""
const G=await import(file('static/twin/gutters.js'));
const E=await import(file('static/twin/sky/eave_streams.js'));
const {roofBounds,sectionHeight}=await import(file('static/twin/twin_roof.js'));
const {roofPoint}=await import(file('static/twin/roof_supports.js'));
const FT=.3048, rect=(a,b,c,d)=>[[a,b],[c,b],[c,d],[a,d]];
function fixture(mount,drop,rotate=false) {
 const area=rect(0,0,16,3), outline=rect(0,-10,16,0);
 const s={id:'shade',roof:'shade',level:'L1',rect:[0,0,16,3],kind:'shed',low_side:'y1',plate:10,pitch:3,overhang:.4,
  support:{kind:mount.includes('post')?'post':'brace',count:2,at:{'0':[0,3],'1':[16,3]}},thickness_ft:.3,host:{wall:'host',edge:0},
  gutters:{y1:true},plane_edges:{y0:0,x1:1,y1:2,x0:3}};
 if(drop!==null)s.underside={kind:'flat',drop_ft:drop};
 const edges=['gable','gable','sloped','gable'].map(setting=>({setting,pitch:3,...(setting==='sloped'?{gutter:true,downspouts:[.5]}:{})}));
 const r={...structuredClone(s),area,edges}; delete r.rect; delete r.roof;
 const b={id:'b',position:rotate?[20,30]:[0,0],base:rotate?3:0,rotation:rotate?37:0,
  levels:[{id:'L1',elevation:0,ceiling:12,...(mount==='wall'?{outline}:{})}],rooms:[],openings:[],
  walls:mount==='wall'?[{id:'host',level:'L1',from:[0,0],to:[16,0],height:12,thickness:.5,exterior:true}]:[],
  porches:mount==='post'?[{id:'patio',polygon:area,level:'L1',floor:0,columns:[{at:[0,3],size:.5},{at:[16,3],size:.5}]}]:[],
  roof:{sections:[s],extensions:[]},roofs:[r]};
 return {units:'ft',buildings:[b],site:{}};
}
const calc=(g,p)=>{const runs=g.gutterRuns(p),spouts=g.downspouts(p,runs);return {runs,spouts};};
for(const mount of ['wall','post','roof-post','hang'])for(const rotate of [false,true])for(const drop of [.5,1.5]) {
 await test(`${mount} drop ${drop} rotated ${rotate} clears the ceiling face`,()=>{
  const p=fixture(mount,drop,rotate),{runs,spouts}=calc(G,p),b=p.buildings[0],s=b.roof.sections[0];
  assert.ok(runs.length); assert.equal(spouts.length,1);const spout=spouts[0];assert.equal(spout.mount,mount==='roof-post'?'post':mount);
  const [x0,y0,x1,y1]=roofBounds(s),low=Math.min(...rect(x0,y0,x1,y1).map(at=>sectionHeight(s,...roofPoint(s,at))));
  const ceiling=(b.base+low-s.thickness_ft-drop)*FT,limit=ceiling-G.GUTTER.soffitClearIn/12*FT;
  if(mount==='hang') {
   // A free-standing emergency stub stays wholly outside the face, with no inward elbow.
   assert.ok(spout.flags.includes('stub'));assert.equal(spout.path.length,2);
   assert.equal(spout.path[0][0],spout.path[1][0]);assert.equal(spout.path[0][2],spout.path[1][2]);
   const segment=runs.flatMap(r=>r.segments).find(s=>s.edge===spout.edge.edge),angle=b.rotation*Math.PI/180;
   const outward=[-Math.sin(angle),-Math.cos(angle)];
   const outside=(spout.top[0]-segment.a[0])*outward[0]+(spout.top[2]-segment.a[2])*outward[1];
   assert.ok(outside>=(Math.max(...G.GUTTER.spoutIn)/24+G.GUTTER.soffitClearIn/12)*FT-1e-8,'whole pipe clears the face by an inch');
  } else {
   assert.ok(spout.path[1][1]<=limit+1e-8,`inward turn ${spout.path[1][1]/FT} must clear ceiling ${ceiling/FT}`);
   for(let i=1;i<spout.path.length;i++)assert.ok(spout.path[i][1]<=spout.path[i-1][1]+1e-8,'never route upward');
  }
  assert.deepEqual(G.downspouts(p,JSON.parse(JSON.stringify(runs))),spouts,'serialized-run fallback agrees');
 });
}
// Load the pre-fix module in memory, sharing its actual dependencies. No checkout/archive.
const oldSource=input.before.replace(/from '(\.[^']+)'/g,(_,path)=>`from '${new URL(path,file('static/twin/gutters.js')).href}'`);
const before=await import('data:text/javascript;base64,'+Buffer.from(oldSource).toString('base64'));
for(const mount of ['wall','post','roof-post','hang'])for(const drop of [null,0])await test(`${mount} drop ${drop} keeps exact rain bytes`,()=>{
 const p=fixture(mount,drop),old=calc(before,p),now=calc(G,p);
 assert.equal(JSON.stringify(now),JSON.stringify(old),'gutters and spouts');
 const rain=g=>E.eaveInstances(p,new Map(),{},g);
 assert.equal(JSON.stringify(rain(now)),JSON.stringify(rain(old)),'streams, pours and catchment');
 if(drop===0)assert.equal(JSON.stringify(now),JSON.stringify(calc(G,fixture(mount,null))),'zero drop equals absent ceiling');
});
finish();
"""

if __name__ == '__main__':
    before = subprocess.check_output(['git', 'show', BASELINE + ':chauffeur/static/twin/gutters.js'], cwd=ROOT, encoding='utf-8')
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'before': before}, timeout=180)
    print(output)
    raise SystemExit(code)
