"""Compare to main; private exports enter Node only through stdin."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_twin_awning_golden_js import baseline_sources, FIXTURE
from test_twin_tree_once_js import PREFIX

@lru_cache(maxsize=1)
def main_sources():
    return baseline_sources('1020f231e86d3ff44fff35d1326d56b3080dc93a')  # main at fix-round verification

DRIVER = PREFIX + FIXTURE + r"""
const {createHash}=await import('node:crypto');
const urls=new Map(),paths=Object.keys(input.sources);
for(const [path,original] of Object.entries(input.sources)){
 const source=original.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
  const url=new URL(s,file(path)).href,ref=paths.find(p=>file(p)===url);
  return a+(ref?'baseline:'+ref:url)+b;
 });urls.set(path,'data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
}
registerHooks({resolve(spec,ctx,next){return spec.startsWith('baseline:')?{url:urls.get(spec.slice(9)),shortCircuit:true}:next(spec,ctx);}});
const G=await import(file('static/twin/twin_generator.js')),A=await import(file('static/twin/bake/atlas.js'));
const oldG=await import(urls.get('static/twin/twin_generator.js')),oldA=await import(urls.get('static/twin/bake/atlas.js'));
const {authoredGeometry}=await import(file('static/twin/bake/geometry_key.js'));
const {disposeObject}=await import(file('static/twin/twin_library.js'));
const {releaseBakeSource}=await import(file('static/twin/bake/source.js'));
const plan=JSON.parse(readFileSync(0,'utf-8'));
const hash=v=>createHash('sha256').update(typeof v==='string'?v:JSON.stringify(v)).digest('hex');
const attr=a=>a?[a.itemSize,a.normalized,hash(Buffer.from(a.array.buffer,a.array.byteOffset,a.array.byteLength).toString('base64'))]:null;
const mat=m=>[m.name,m.userData.materialKey??null,m.transparent,m.alphaTest,m.opacity,m.side,m.depthWrite,m.depthTest];
const rendered=out=>{const rows=[];out.root.traverseVisible(m=>{if(m.isMesh&&!m.layers.isEnabled(31)&&(Array.isArray(m.material)?m.material.some(m=>m.visible):m.material.visible))rows.push(m);});return rows;};
const dispose=out=>{releaseBakeSource(out.root);disposeObject(out.root);};
async function build(module,tier,p=plan){const start=performance.now(),out=module.buildTwin(structuredClone(p),kit(),tier,{viewing:true,...input.opts});await out.ready;out.root.updateMatrixWorld(true);return {out,ms:performance.now()-start};}
function signature(out){const meshes=rendered(out),materials=new Set(meshes.flatMap(m=>(Array.isArray(m.material)?m.material:[m.material]).map(m=>JSON.stringify(mat(m)))));
return {meshes:meshes.length,materials:materials.size,draws:meshes.reduce((s,m)=>s+(Array.isArray(m.material)?m.geometry.groups.filter(g=>m.material[g.materialIndex]?.visible).length:1),0),triangles:meshes.reduce((s,m)=>s+(m.geometry.index?.count??m.geometry.attributes.position.count)/3*(m.isInstancedMesh?m.count:1),0),
 geometry:hash(meshes.map(m=>[m.name,m.matrixWorld.elements,['position','normal','uv'].map(k=>attr(m.geometry.attributes[k])),attr(m.geometry.index),m.geometry.groups,m.geometry.drawRange,Array.isArray(m.material)?m.material.map(mat):mat(m.material)])),
 uv:hash(meshes.map(m=>attr(m.geometry.attributes.uv)))};}
function atlas(module,out,p){const a=module.buildAtlas(out.root,p,{room:{density:1,page:2048,gutter:2}});return {key:a.key,charts:a.room.charts.length,chartKeys:hash(a.room.charts.map(c=>c.key))};}
const evidence={};
for(const tier of input.tiers||['high','low']){
 const old=await build(oldG,tier),current=await build(G,tier),before=signature(old.out),after=signature(current.out);
 if(after.geometry!==before.geometry){const rows=o=>rendered(o).map(m=>({name:m.material.name,count:m.geometry.attributes.position.count,
   position:attr(m.geometry.attributes.position),uv:attr(m.geometry.attributes.uv)}));const a=rows(old.out),b=rows(current.out);
   console.log('DIFFERENT_MESHES '+JSON.stringify(b.flatMap((r,i)=>JSON.stringify(r)===JSON.stringify(a[i])?[]:[{index:i,main:a[i],current:r}])));}
 assert.deepEqual(after,before,tier+' drawn bytes and counts');
 const keys={main:atlas(oldA,old.out,plan),current:atlas(A,current.out,plan)};assert.deepEqual(keys.current,keys.main,tier+' atlas keys');
 const minted=structuredClone(plan);for(const b of minted.buildings)for(const p of b.porches||[])p.columns.forEach((c,i)=>c.id ||= `post:${p.id}:${i}`);
 assert.equal(authoredGeometry(minted),authoredGeometry(plan));
 const mint=await build(G,tier,minted);const mintKeys=atlas(A,mint.out,minted);assert.deepEqual(mintKeys,keys.current,tier+' mint-only atlas');
 dispose(old.out);dispose(current.out);dispose(mint.out);
 const times={main:[],current:[]};if(input.measure!==false){for(const module of [oldG,G]){const r=await build(module,tier);dispose(r.out);}
 for(let i=0;i<5;i++)for(const [name,module] of i%2?[['current',G],['main',oldG]]:[['main',oldG],['current',G]]){const r=await build(module,tier);times[name].push(r.ms);dispose(r.out);}}
 const median=a=>[...a].sort((a,b)=>a-b)[2]||0,medians={main:median(times.main),current:median(times.current)};
 evidence[tier]={main:before,current:after,keys,times,medians,ratio:medians.current/medians.main};
}
evidence.posts=plan.buildings.flatMap(b=>(b.porches||[]).map((p,i)=>({buildingIndex:plan.buildings.indexOf(b),porchIndex:i,posts:p.columns.length})));
console.log(JSON.stringify(evidence));
"""


def compare(plan, *, measure=True, tiers=None, opts=None):
    with tempfile.TemporaryDirectory(prefix='post_measure_') as directory:
        driver, job = Path(directory)/'driver.mjs', Path(directory)/'job.json'
        driver.write_text(DRIVER, encoding='utf-8')
        job.write_text(json.dumps(dict(root=ROOT.as_posix(), sources=main_sources(), measure=measure, tiers=tiers or ['high','low'], opts=opts or {})), encoding='utf-8')
        result = subprocess.run([shutil.which('node'),str(driver),str(job)], input=json.dumps(plan),
                                capture_output=True,text=True,encoding='utf-8',timeout=900)
    if result.returncode: raise AssertionError(result.stdout+result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


if __name__ == '__main__':
    from services.twin_awning_migration import migrate_awnings
    from services.twin_model_bridge import flatten
    model=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['model']
    result=compare(flatten(migrate_awnings(model)[0]))
    (ROOT.parent/'.superpowers/sdd/posts/measurements.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
