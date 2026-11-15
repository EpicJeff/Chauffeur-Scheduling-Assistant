"""Byte-level scene, material, reuse and atlas comparison against pre-arc main."""
import posixpath
import re
import subprocess
import sys
from pathlib import Path

from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'e8b20515'


def baseline_sources():
    sources = {}

    def read(path):
        if path in sources:
            return
        source = subprocess.check_output(['git', 'show', BASELINE + ':chauffeur/' + path],
                                         cwd=ROOT, encoding='utf-8')
        sources[path] = source
        for ref in re.findall(r"(?:from|import)\s*['\"](\.[^'\"]+)['\"]", source):
            child = posixpath.normpath(posixpath.join(posixpath.dirname(path), ref))
            if child.startswith('static/twin/'):
                read(child)
    for path in ('static/twin/twin_generator.js', 'static/twin/twin_yard.js', 'static/twin/bake/atlas.js'):
        read(path)
    return sources


COMMON = PREFIX + r"""
const THREE=await import('three');
const {createHash}=await import('node:crypto');
registerHooks({load(url,ctx,next){const result=next(url,ctx);
 if(url===file('static/twin/twin_generator.js'))return {...result,source:result.source+'\nexport {buildingKeyParts};'};
 if(url===file('static/twin/bake/atlas.js'))return {...result,source:result.source+'\nexport {VERSION};'};
 return result;
}});
const G=await import(file('static/twin/twin_generator.js'));
const A=await import(file('static/twin/bake/atlas.js'));
const square=(x,y,w,h=w)=>[[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
const building=(id,x=0)=>({id,position:[x,0],rotation:0,base:1,materials:{},
 levels:[{id:'L1',elevation:1,ceiling:8,outline:square(0,0,40,24)},
         {id:'L2',elevation:9,ceiling:8,outline:square(0,0,20,24)}],
 rooms:[{id:'r1',level:'L1',polygon:square(0,0,40,24),state:'settled'},
        {id:'r2',level:'L2',polygon:square(0,0,20,24),state:'settled'}],
 walls:['L1','L2'].flatMap((level,n)=>square(0,0,n?20:40,24).map((from,i,p)=>({
  id:level+'w'+i,level,from,to:p[(i+1)%4],height:n?8:9,thickness:.5,exterior:true,state:'settled'}))),
 openings:[['window',4,3],['slider',11,6],['bifold',20,6],['garage',31,8]].map(([kind,at,width],i)=>({
  id:kind,level:'L1',wall:'L1w0',kind,at,width,sill:kind==='window'?3:0,head:7,panels:2,state:'settled'}))
  .concat([{id:'door',level:'L1',wall:'L1w2',kind:'door',glass:'half',at:5,width:3,sill:0,head:7,state:'settled'}]),
 roof:{sections:[{id:'gable',kind:'gable',rect:[0,0,20,24],plate:17,pitch:6,ridge:'y',overhang:1,level:'L2'},
                 {id:'hip',kind:'hip',rect:[20,0,40,24],plate:9,pitch:4,ridge:'y',overhang:1,level:'L1'}],flags:[],extensions:[]},
 roofs:[],dormers:[],porches:[{id:'porch',polygon:square(0,-8,16,8),floor:0,screened:true,
  columns:[{at:[0,-8],size:.5},{at:[16,-8],size:.5}]}],
 stairs:[{id:'stairs',level:'L1',from:[3,4],to:[13,4],width:3,risers:14,rise_to:9,style:'open',rail:'both',state:'settled'}],
 fixtures:[{id:'kitchen',kind:'counter',level:'L1',rect:[1,10,7,12],height:3,body:'#112233',top:'#8899aa',state:'settled'},
           {id:'vanity',kind:'vanity',level:'L1',rect:[9,10,13,12],height:3,state:'settled'},
           {id:'shower',kind:'shower',level:'L1',rect:[15,10,19,14],height:7,state:'settled'}],
 items:[],anchors:[],lights:[]});
const fixture=()=>({materials:{},buildings:[building('a'),building('b',60)],site:{lot:square(-10,-12,120,70),
 pool:{id:'pool',polygon:square(4,36,18,10),depth:4,coping:1,features:[{id:'spa',kind:'spa',polygon:square(6,38,6),depth_in:36,mode:'raised',raise_in:12}]},
 fence:[{id:'fence',polyline:[[-8,-10],[40,-10]],height:5,elevation:0}],
 hardscape:[{id:'patio',polygon:square(24,32,12),material:'paving'}],planting:[],furniture:[],terraces:[]}});
const kit=()=>({materials:Object.fromEntries(['floor','patio_concrete','siding','interior_wall','roof','trim',
 'window_frame','door','porch_ceiling','base','lattice','counter','stainless','lawn','paving'].map(role=>[role,{asset:role,color:'#bbccee'}])),
 manifest:{choice:{kind:'material',household:true,revision:1,maps:{},params:{tint:'#456789',roughness:.7}},
           blend:{kind:'material',household:true,revision:1,maps:{},params:{tint:'#abcdef',alpha_mode:'blend',opacity:.4}}}});
const hash=a=>a?createHash('sha1').update(Buffer.from(a.array.buffer,a.array.byteOffset,a.array.byteLength)).digest('hex'):null;
const meshes=out=>{const rows=[];out.root.traverse(o=>{if(o.isMesh)rows.push(o);});return rows;};
const signature=out=>meshes(out).map(o=>[o.material.name,o.material.userData.materialKey??null,
 o.material.transparent,o.material.alphaTest,o.material.opacity,o.material.side,o.material.depthWrite,
 o.geometry.attributes.position.count,hash(o.geometry.attributes.uv),hash(o.geometry.attributes.position)]);
const layout={room:{density:1,page:256,gutter:2}};
async function build(p,k=kit(),module=G){const out=module.buildTwin(p,k,'low',input.editable?{editableLevel:'a:L1'}:{});await out.ready;out.root.updateMatrixWorld(true);return out;}
const piece=(out,id,b='a')=>(out.pieces.get(b+':'+id)||[]).filter(o=>o.isMesh);
const rendered=out=>meshes(out).filter(o=>!o.layers.isEnabled(31));
"""

DRIVER = COMMON + r"""
const Y=await import(file('static/twin/twin_yard.js'));
const mainURLs=new Map();
for(const [path,original] of Object.entries(input.sources)){
 let source=original;
 source=source.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
  const url=new URL(s,file(path)).href,ref=Object.keys(input.sources).find(p=>file(p)===url);
  return a+(ref?'baseline:'+ref:url)+b;
 });
 if(path==='static/twin/twin_generator.js')source+='\nexport {buildingKeyParts};';
 if(path==='static/twin/bake/atlas.js')source+='\nexport {VERSION};';
 const url='data:text/javascript;base64,'+Buffer.from(source).toString('base64');mainURLs.set(path,url);
}
registerHooks({resolve(spec,ctx,next){return spec.startsWith('baseline:')
 ? {url:mainURLs.get(spec.slice(9)),shortCircuit:true}:next(spec,ctx);}});
const mainURL=path=>mainURLs.get(path);
const main=await import(mainURL('static/twin/twin_generator.js'));
const oldA=await import(mainURL('static/twin/bake/atlas.js'));
const oldY=await import(mainURL('static/twin/twin_yard.js'));
async function compare(p,k){
 const now=await build(p,k),old=await build(p,k,main);
 const newYard=await Y.buildYard(p,k,'low'),oldYard=await oldY.buildYard(p,k,'low');
 now.root.add(newYard.group);old.root.add(oldYard.group);
 assert.deepEqual(signature(now),signature(old));
 assert.equal(meshes(now).length,meshes(old).length);
 assert.equal(new Set(meshes(now).map(o=>o.material.uuid)).size,new Set(meshes(old).map(o=>o.material.uuid)).size);
 for(const b of p.buildings)assert.equal(JSON.stringify(G.buildingKeyParts(p,b,k,'low')),JSON.stringify(main.buildingKeyParts(p,b,k,'low')));
 assert.equal(Y.yardMaterialKey(p,k,'low'),oldY.yardMaterialKey(p,k,'low'));
 assert.deepEqual(Y.yardPartKeys(p,k,'low'),oldY.yardPartKeys(p,k,'low'));
 const a=A.buildAtlas(now.root,p,layout),b=oldA.buildAtlas(old.root,p,layout);
 assert.equal(a.key,b.key);assert.ok(a.room.charts.length>0);
 assert.equal(A.VERSION,oldA.VERSION);
}
await test('untouched_house_equals_main',()=>compare(fixture(),kit()));
await test('untouched_solid_door_and_closed_stair_equal_main',()=>{
 const p=fixture();p.buildings[0].openings.find(o=>o.id==='door').glass='none';
 p.buildings[0].stairs[0].style='solid';p.buildings[0].stairs[0].rail='none';
 return compare(p,kit());
});
await test('house_with_alpha_free_library_materials_equals_main',()=>{
 const p=fixture();p.buildings[0].materials.siding={id:'choice'};p.buildings[0].rooms[0].floor_material={id:'choice'};
 return compare(p,kit());
});
await test('house_with_existing_kit_role_defaults_equals_main',()=>{
 const p=fixture(),k=kit();k.materials.roof.asset='standing_seam';
 for(const b of p.buildings)for(const role of ['trim','window_frame','door','roof','base','counter'])
  b.materials[role]={id:role,color:'#334455'};
 return compare(p,k);
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'sources': baseline_sources()}, timeout=180)
    print(output)
    sys.exit(code or 0)
