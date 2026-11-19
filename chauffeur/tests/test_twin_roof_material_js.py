"""Roof-only material regression proof; real generator, atlas and editor under Node."""
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path

from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'cce4decd'


def baseline_sources():
    sources = {}

    def read(path):
        if path in sources:
            return
        source = subprocess.check_output(
            ['git', 'show', BASELINE + ':chauffeur/' + path], cwd=ROOT, encoding='utf-8')
        sources[path] = source
        for ref in re.findall(r"(?:from|import)\s*['\"](\.[^'\"]+)['\"]", source):
            child = posixpath.normpath(posixpath.join(posixpath.dirname(path), ref))
            if child.startswith('static/twin/'):
                read(child)

    read('static/twin/twin_generator.js')
    return sources


DRIVER = PRELUDE + r"""
const THREE=await import('three');
const {createHash}=await import('node:crypto');
// Expose the private key function only in this test's in-memory module graph.
registerHooks({load(url,ctx,next){const result=next(url,ctx);
 if(url===file('static/twin/twin_generator.js'))return {...result,source:result.source+'\nexport {buildingKeyParts};'};
 return result;
}});
const G=await import(file('static/twin/twin_generator.js'));
const {buildAtlas,atlasMesh}=await import(file('static/twin/bake/atlas.js'));
const {createCards,findPiece}=await import(file('static/twin/editor/cards.js'));
const {materialLines,createLibrary,surfaceOperation}=await import(file('static/twin/editor/library.js'));
const mainURLs=new Map();
function mainURL(path){
 if(mainURLs.has(path))return mainURLs.get(path);
 let source=input.sources[path];
 source=source.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
  const url=new URL(s,file(path)).href,ref=Object.keys(input.sources).find(p=>file(p)===url);
  return a+(ref?mainURL(ref):url)+b;
 });
 if(path==='static/twin/twin_generator.js')source+='\nexport {buildingKeyParts};';
 const url='data:text/javascript;base64,'+Buffer.from(source).toString('base64');mainURLs.set(path,url);return url;
}
const square=(x,y,w,h=w)=>[[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
const section=(id,rect)=>({id,roof:id,kind:'gable',rect,plate:8,pitch:6,ridge:'x',overhang:1,level:'L1'});
const building=id=>({id,position:[id==='a'?5:50,3],rotation:12,base:0,materials:{},
 levels:[{id:'L1',elevation:0,ceiling:8,outline:square(0,0,20)}],
 rooms:[{id:'room',level:'L1',polygon:square(0,0,20),state:'settled'}],
 walls:square(0,0,20).map((from,i,p)=>({id:'w'+i,level:'L1',from,to:p[(i+1)%4],height:8,thickness:.5,exterior:true})),
 roof:{sections:[section('main',[0,0,20,20]),section('porch',[0,-10,20,-2])],flags:[]},
 roofs:[],dormers:[],openings:[],stairs:[],fixtures:[],items:[],anchors:[],lights:[]});
const fixture=()=>({buildings:[building('a'),building('b')],materials:{},site:{}});
const kit=()=>({materials:Object.fromEntries(['roof','trim','porch_ceiling','siding','interior_wall','floor','patio_concrete','base'].map(r=>[r,{asset:r,color:'#b8b0a4'}])),
 manifest:Object.fromEntries(['shingles','metal','default'].map(id=>[id,{household:true,kind:'material',revision:1,params:{tint:'#889999',roughness:.8},maps:{}}]))});
const keys=(p,k)=>p.buildings.map(b=>JSON.stringify(G.buildingKeyParts(p,b,k,'low')));
async function build(p,k=kit(),module=G){const out=module.buildTwin(p,k,'low');await out.ready;out.root.updateMatrixWorld(true);return out;}
const roofMeshes=(out,id='a')=>{const result=[];for(const group of out.groups.roof.children.filter(g=>g.userData.buildingId===id))group.traverse(o=>{
 if(o.isMesh&&!o.layers.isEnabled(31))result.push(o);
});return result;};
const flags=m=>[m.name,m.userData.materialKey??null,m.transparent,m.alphaTest,m.opacity,m.side];
const hash=a=>a?createHash('sha1').update(Buffer.from(a.array.buffer,a.array.byteOffset,a.array.byteLength)).digest('hex'):null;
const meshList=out=>{const list=[];out.root.traverse(o=>{if(o.isMesh)list.push([...flags(o.material),o.geometry.attributes.position.count,hash(o.geometry.attributes.position),hash(o.geometry.attributes.uv)]);});return list;};
const triangles=out=>roofMeshes(out).flatMap(o=>{
 const g=o.geometry,p=g.attributes.position,uv=g.attributes.uv,indices=g.index?.array||Array.from({length:p.count},(_,i)=>i),result=[];
 for(let t=0;t<indices.length;t+=3){const tri=[];
  for(const i of indices.slice(t,t+3)){const v=new THREE.Vector3().fromBufferAttribute(p,i).applyMatrix4(o.matrixWorld);
   tri.push([...v.toArray(),uv.getX(i),uv.getY(i)]);}
  result.push(JSON.stringify(tri.sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)))));
 }return result;
}).sort();
const setBoth=p=>{p.buildings[0].roof.sections[0].material={id:'shingles'};p.buildings[0].roof.sections[1].material={id:'metal'};};
await test('two_roofs_two_materials',async()=>{
 const p=fixture(),before=await build(p);setBoth(p);const after=await build(p);
 assert.deepEqual(roofMeshes(after).filter(o=>o.material.name==='roof').map(o=>o.material.userData.materialId).sort(),['metal','shingles']);
 for(const [id,mid] of [['main','shingles'],['porch','metal']]){
  const own=after.pieces.get('a:'+id).filter(o=>o.material?.name==='roof'&&!o.layers.isEnabled(31));
  assert.ok(own.length);assert.ok(own.every(o=>o.material.userData.materialId===mid));
 }
 for(const role of ['trim','porch_ceiling'])assert.deepEqual(roofMeshes(after).filter(o=>o.material.name===role).map(o=>[...flags(o.material),hash(o.geometry.attributes.position),hash(o.geometry.attributes.uv)]),roofMeshes(before).filter(o=>o.material.name===role).map(o=>[...flags(o.material),hash(o.geometry.attributes.position),hash(o.geometry.attributes.uv)]));
 assert.equal(roofMeshes(after).length,roofMeshes(before).length+1,'one additional batch for a second distinct covering');
});
await test('unset_roof_follows_the_building_default',async()=>{
 const p=fixture();p.buildings[0].materials.roof={id:'default'};p.buildings[0].roof.sections[0].material={id:'shingles'};
 const out=await build(p);assert.deepEqual(roofMeshes(out).filter(o=>o.material.name==='roof').map(o=>o.material.userData.materialId).sort(),['default','shingles']);
});
await test('split_roof_shares_one_instance',async()=>{
 const p=fixture(),s=p.buildings[0].roof.sections;
 s[0].id='main~1';s[1].id='main~2';for(const q of s){q.roof='main';q.material={id:'shingles'};}
 const out=await build(p),materials=s.flatMap(q=>out.pieces.get('a:'+q.id).filter(o=>o.material?.name==='roof').map(o=>o.material.uuid));
 assert.ok(materials.length>=2);assert.equal(new Set(materials).size,1);
 assert.equal(roofMeshes(out).find(o=>o.material.name==='roof').material.userData.materialId,'shingles');
});
await test('no_geometry_change',async()=>{
 const p=fixture(),before=await build(p);setBoth(p);const after=await build(p);
 const a=triangles(before),b=triangles(after);assert.ok(a.length>0);assert.equal(a.length,b.length);assert.deepEqual(b,a);
});
await test('untouched_house_equals_main',async()=>{
 const main=await import(mainURL('static/twin/twin_generator.js')),p=fixture(),k=kit();
 const now=await build(p,k),old=await build(p,k,main);
 assert.deepEqual(meshList(now),meshList(old));
 for(const b of p.buildings)assert.equal(JSON.stringify(G.buildingKeyParts(p,b,k,'low')),JSON.stringify(main.buildingKeyParts(p,b,k,'low')));
});
await test('roof_material_changes_the_key_and_clears_back',async()=>{
 const p=fixture(),k=kit(),original=keys(p,k);p.buildings[0].roof.sections[0].material={id:'shingles'};
 const a=keys(p,k);assert.notEqual(a[0],original[0]);assert.equal(a[1],original[1]);
 p.buildings[0].roof.sections[0].material={id:'metal'};const b=keys(p,k);assert.notEqual(b[0],a[0]);assert.equal(b[1],original[1]);
 delete p.buildings[0].roof.sections[0].material;assert.deepEqual(keys(p,k),original);
});
await test('dormer_material_changes_the_key_and_clears_back',async()=>{
 const p=fixture(),k=kit(),b=p.buildings[0];b.dormers=[{id:'d1',roof:'main'}];
 b.roof.sections.push({...section('d1',[6,-1,10,7]),roof:'main',dormer_of:[0,0,20,20]});
 const original=keys(p,k),set=id=>{b.dormers[0].material={id};b.roof.sections.at(-1).material={id};};
 set('metal');const a=keys(p,k);assert.notEqual(a[0],original[0]);assert.equal(a[1],original[1]);
 set('shingles');const c=keys(p,k);assert.notEqual(c[0],a[0]);assert.equal(c[1],original[1]);
 delete b.dormers[0].material;delete b.roof.sections.at(-1).material;assert.deepEqual(keys(p,k),original);
});
await test('roof_and_dormer_material_revision_changes_only_its_building_key',async()=>{
 for(const dormer of [false,true]){
  const p=fixture(),k=kit(),b=p.buildings[0];
  if(dormer){b.dormers=[{id:'d1',roof:'main',material:{id:'metal'}}];b.roof.sections.push({...section('d1',[6,-1,10,7]),dormer_of:[0,0,20,20],material:{id:'metal'}});}
  else b.roof.sections[0].material={id:'metal'};
  const before=keys(p,k);k.manifest.metal.revision++;const after=keys(p,k);
  assert.notEqual(after[0],before[0]);assert.equal(after[1],before[1]);
 }
});
await test('roof_material_keeps_the_atlas_key',async()=>{
 const p=fixture(),k=kit(),layout={room:{density:1,page:256,gutter:2}};
 const plain=await build(p,k),oldKey=buildAtlas(plain.root,p,layout).key;
 setBoth(p);const out=await build(p,k),key=buildAtlas(out.root,p,layout).key;assert.equal(key,oldKey);
 const covering=roofMeshes(out).filter(o=>o.material.userData.materialId);assert.equal(covering.length,2);assert.ok(covering.every(atlasMesh),'opaque overrides receive the ordinary roof bake');
 p.buildings[0].roof.sections[1].material={id:'shingles'};const changed=await build(p,k);assert.equal(buildAtlas(changed.root,p,layout).key,key);
});
await test('dormer_material_keeps_the_atlas_key',async()=>{
 const p=fixture(),b=p.buildings[0],k=kit(),layout={room:{density:1,page:256,gutter:2}};
 b.dormers=[{id:'d1',roof:'main'}];b.roof.sections.push({...section('d1',[6,-1,10,7]),roof:'main',dormer_of:[0,0,20,20]});
 const first=await build(p,k),before=buildAtlas(first.root,p,layout).key;
 b.dormers[0].material={id:'metal'};b.roof.sections.at(-1).material={id:'metal'};
 const next=await build(p,k);assert.equal(buildAtlas(next.root,p,layout).key,before);
 assert.ok(next.pieces.get('a:d1').some(o=>o.material?.userData.materialId==='metal'&&atlasMesh(o)));
});
await test('dormer_takes_its_own_material',async()=>{
 const p=fixture(),b=p.buildings[0];b.dormers=[{id:'d1',roof:'main',material:{id:'metal'}}];
 b.roof.sections[0].material={id:'shingles'};b.roof.sections.push({...section('d1',[6,-1,10,7]),dormer_of:[0,0,20,20],roof:'main',material:{id:'metal'}});
 const out=await build(p),own=out.pieces.get('a:d1').filter(o=>o.material?.name==='roof');
 assert.ok(own.length);assert.ok(own.every(o=>o.material.userData.materialId==='metal'));
 const line=materialLines(findPiece(p,'d1','a'),p,kit())[0];assert.ok(line);assert.deepEqual(line.target,{dormer:'d1'});
 assert.deepEqual(surfaceOperation(line.surface,'face',{id:'metal'}).target,{dormer:'d1'});
});
await test('roof_and_dormer_lines_inherit_the_building_roof',async()=>{
 const p=fixture(),b=p.buildings[0];b.materials.roof={id:'house_roof'};b.dormers=[{id:'d1',roof:'main'}];
 b.roof.sections.push({...section('d1',[6,-1,10,7]),roof:'main',dormer_of:[0,0,20,20]});
 for(const id of ['main','d1']){
  const line=materialLines(findPiece(p,id,'a'),p,kit())[0];
  assert.equal(line.label,'Roof');assert.equal(line.text,'From the building: House roof');assert.equal(line.clear,false);
 }
});
// Actual selection card and Library events, with only camera/pick and HTTP doubled.
await test('roof_and_dormer_card_choose_clear_drop_and_read_only',async()=>{
 const p=fixture(),b=p.buildings[0],k=kit();b.dormers=[{id:'d1',roof:'main'}];
 b.roof.sections.push({...section('d1',[6,-1,10,7]),dormer_of:[0,0,20,20],roof:'main'});
 const ops=[],op=async value=>{ops.push(value);},abort=new AbortController();let editable=true;
 const canvas=document.createElement('canvas');document.body.append(canvas);document.getElementById('library-panel').hidden=true;
 const camera=new THREE.PerspectiveCamera(45,1,.1,500);camera.position.set(3,20,3);camera.lookAt(3,0,3);
 let picked={kind:'roof',id:'main',building:'a',point:[3,3,3]};
 const view={renderer3:{domElement:canvas},scene:new THREE.Scene(),camera,controls:new THREE.EventDispatcher(),pick:()=>picked};
 const nativeFetch=globalThis.fetch;globalThis.fetch=async url=>{
  if(String(url).endsWith('/materials'))return new Response(JSON.stringify({materials:[{id:'metal',name:'Porch metal',color:'#889999',builtin:true}]}));
  if(String(url).endsWith('/library'))return new Response(JSON.stringify({items:[],imports:[]}));
  return nativeFetch(url);
 };
 const tools={selection:()=>({}),select(){}};
 const library=createLibrary({view,kit:k,getPlan:()=>p,tools,op,canEdit:()=>editable,signal:abort.signal});
 const cards=createCards({getPlan:()=>p,getKit:()=>k,op,edit:op,canEdit:()=>editable,select(){},library});
 const host=document.getElementById('piece-card'),settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setTimeout(r,0));};
 const row=()=>host.querySelector('[data-library-slot="Roof"]');
 for(const [id,target] of [['main',{roof:'main'}],['d1',{dormer:'d1'}]]){
  cards.draw(null);cards.draw({pieceId:id,buildingId:'a'});
  assert.ok(row(),id+' material row');assert.match(textOf(row()),/Roof/);
  await library.reveal('material','metal');library.select(null);
  click(document.querySelector('[data-material="metal"]'));await settle();
  click(row().querySelector('[data-slot-use]'));await settle();
  assert.deepEqual(ops.pop(),{op:'set_material',building:'a',target,material:{id:'metal'}});
  b.roof.sections.find(s=>s.id===id).material={id:'metal'};
  cards.draw({pieceId:id,buildingId:'a'});click([...row().querySelectorAll('button')].find(n=>n.textContent==='Clear'));await settle();
  assert.deepEqual(ops.pop(),{op:'set_material',building:'a',target,material:null});
  // A dormer is picked as kind roof by today's generator, so resolution must use its own id.
  picked={kind:'roof',id,building:'a',point:[3,3,3]};
  const surface=library.surfaceAt({clientX:100,clientY:100});assert.ok(surface);
  assert.deepEqual(surfaceOperation(surface,'face',{id:'metal'}).target,target);
  const thumb=document.querySelector('[data-material="metal"]');
  document.elementFromPoint=()=>canvas;
  fire(thumb,'pointerdown',{pointerId:1,clientX:1,clientY:1,button:0});
  fire(document,'pointerup',{pointerId:1,clientX:100,clientY:100,button:0});await settle();
  click(document.getElementById('material-chooser').querySelector('button'));await settle();
  assert.deepEqual(ops.pop(),{op:'set_material',building:'a',target,material:{id:'metal'}});
 }
 editable=false;
 cards.draw({pieceId:'d1',buildingId:'a'});assert.equal(row().querySelectorAll('button').length,0);
 for(const id of ['main','d1']){cards.draw(null);cards.draw({pieceId:id,buildingId:'a'});assert.equal(row().querySelectorAll('button').length,0);}
 abort.abort();globalThis.fetch=nativeFetch;
});
finish();
"""


if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'sources': baseline_sources()}, timeout=120)
    print(output)
    sys.exit(code or 0)
