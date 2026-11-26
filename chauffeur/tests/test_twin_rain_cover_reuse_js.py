"""Pinned, same-process byte equality and CPU evidence for rain-cover edits.

Default: bounded household smoke set (<240 s). --full: every edit/undo through
both rebuild and settle, including the private export read by path, on stdin.
No private plan is written to a temporary file or printed.
"""
import argparse
import json
import io
import shutil
import subprocess
import sys
import tempfile
import tarfile
from pathlib import Path

from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'e392e57d5335e88de0518596987ced1d7a61b013'
OWNER = Path(r'C:\Users\ffejn\Downloads\Current house.chauffeur-house-11-20-2016.json')


def sources(revision=BASELINE):
    # One git process: hundreds of git-show launches dominate Windows startup.
    archive = subprocess.check_output(['git', 'archive', revision, 'chauffeur/static/twin'], cwd=ROOT.parent)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        return {m.name.removeprefix('chauffeur/'): tar.extractfile(m).read().decode('utf-8')
                for m in tar.getmembers() if m.isfile() and m.name.endswith('.js')}


DRIVER = PREFIX + r"""
const THREE=await import('three');
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
window.location={href:'http://house.test/house/editor'};
const {createHash}=await import('node:crypto');
const privateInput=JSON.parse(readFileSync(0,'utf8'));
process.on('uncaughtException',error=>{console.error(String(error.stack||error).split('\n').filter(line=>!line.includes('data:')).slice(0,8).join('\n'));process.exit(1);});
const {writeFileSync}=await import('node:fs');
const {Session}=await import('node:inspector');
const profiler=input.profile?new Session():null;if(profiler)profiler.connect();
const profileCall=(method)=>new Promise((resolve,reject)=>profiler.post(method,(err,result)=>err?reject(err):resolve(result)));
const urls=new Map(),paths=Object.keys(input.sources);
globalThis.coverCPU={baseline:0,current:0};globalThis.coverThreadCPU={baseline:0,current:0};globalThis.coverCalls={baseline:0,current:0};globalThis.coverDepth=0;
function instrument(source,label){
 const anchor='export function writeWeatherOpen(root,cover,worldScale=1) {';
 // Preserve the public wrapper's fourth reuse argument when implementation grows.
 const re=/export function writeWeatherOpen\(([^)]*)\) \{/;
 if(!re.test(source))return source;
 if(label==='baseline'&&!input.noAtlas){
  // A fresh sample oracle, using pinned arithmetic and the SAME view path.
  // Keep clipping decisions/ranges intact; disable only stored-sample reuse.
  const skip='if(previous?.geometry===g&&previous.attribute',reuse='const reuse=previous?.geometry===g&&';
  assert.ok(source.includes(skip)&&source.includes(reuse),'pinned sampling anchors');
  source=source.replace(skip,'if(false&&previous?.geometry===g&&previous.attribute')
   .replace(reuse,'const reuse=false&&previous?.geometry===g&&');
 }
 source=source.replace(re,'function measuredWriteWeatherOpen($1) {');
 if(label==='current'&&!input.candidateSources)source=source.replace('coverGeometry.set(record,record);return cover;',`coverGeometry.set(record,record);cover.__rainStats=()=>({triangles:triangles.length/16,gridCells:grid.size,gridEntries:[...grid.values()].reduce((n,a)=>n+a.length,0),raw:edgeRaw.get(record)?.length,pieces:edgePieces.get(record)?.length,outer:edgeCaches.get(record)?.outer.length});return cover;`);
 return source+`\nexport function rainCover(root){let cover;root.traverse(o=>{cover||=written.get(o)?.cover;});return cover;}
 export function rainParts(cover){return typeof partsOf==='function'?partsOf(cover):null;}
 export function rainPartState(cover){return typeof coverParts!=='undefined'&&coverParts.has(typeof stateOf==='function'?stateOf(cover):cover);}
 export function rainDiagnostics(before,after){const a=partsOf(before),b=partsOf(after),removed={},added={};
 for(const k of a.keys())if(!b.has(k))removed[k.slice(0,4)]=(removed[k.slice(0,4)]||0)+1;
 for(const k of b.keys())if(!a.has(k))added[k.slice(0,4)]=(added[k.slice(0,4)]||0)+1;
 return {removed,added,projection:sameProjection(before,after),dirty:changedCover(before,after).map(b=>({heightBand:Number.isFinite(b[4]),finiteTop:Number.isFinite(b[5])}))};}
 export function rainMemory(root){let samples=0,baseGeometry=0,numeric=0,partBytes=0;const arrays=new Set(),covers=new Set();
 root.traverse(o=>{const s=written.get(o);if(!s)return;for(const a of [s.base,s.faces])if(!arrays.has(a)){arrays.add(a);samples+=a.byteLength;}
 if(s.world)numeric+=16*8+6*8;
 const saved=unclipped.get(o);if(saved&&saved.base!==o.geometry)for(const a of Object.values(saved.base.attributes))if(!arrays.has(a.array)){arrays.add(a.array);baseGeometry+=a.array.byteLength;}
 if(typeof coverParts!=='undefined'&&s.cover&&!covers.has(s.cover)){covers.add(s.cover);for(const [k,b] of coverParts.get(s.cover)?.deref?.()||[])partBytes+=k.length*2+b.length*8;}
 });return {samples,baseGeometry,numeric,partBytes};}
 export function writeWeatherOpen(...args){globalThis.coverCalls.${label}++;const outer=!globalThis.coverDepth++;
 const start=outer?process.cpuUsage():null,threadStart=outer?process.threadCpuUsage():null;try{return measuredWriteWeatherOpen(...args);}
 finally{globalThis.coverDepth--;if(outer){const t=process.cpuUsage(start),thread=process.threadCpuUsage(threadStart);
 globalThis.coverCPU.${label}+=(t.user+t.system)/1000;globalThis.coverThreadCPU.${label}+=(thread.user+thread.system)/1000;}}}\n`;
}
for(const [path,original] of Object.entries(input.sources)){
 let source=(path.endsWith('/sky_cover.js')?instrument(original,'baseline'):original).replaceAll('import.meta.url',JSON.stringify(file(path)));
 source=source.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
  const url=new URL(s,file(path)).href,ref=paths.find(p=>file(p)===url);
  return a+(ref?'rain-baseline:'+ref:url)+b;
 });
 urls.set(path,data(source));
}
registerHooks({resolve(spec,ctx,next){return spec.startsWith('rain-baseline:')
 ?{url:urls.get(spec.slice(14)),shortCircuit:true}:next(spec,ctx);},
 load(url,ctx,next){const r=next(url,ctx),path=paths.find(p=>file(p)===url),source=input.candidateSources?.[path]??String(r.source);
 return url===file('static/twin/sky/sky_cover.js')?{...r,source:instrument(source,'current')}
 :input.candidateSources?.[path]?{...r,source}:r;}});
const current=await import(file('static/twin/twin_view.js'));
const baseline=await import(urls.get('static/twin/twin_view.js'));
const C=await import(file('static/twin/sky/sky_cover.js')),B=await import(urls.get('static/twin/sky/sky_cover.js'));
const A=await import(file('static/twin/bake/atlas.js')),oldA=await import(urls.get('static/twin/bake/atlas.js'));
const S=await import(file('static/twin/bake/source.js')),oldS=await import(urls.get('static/twin/bake/source.js'));
await test('exact cover arithmetic, fallback global gate, face class and instance capacity',async()=>{
 const square=(x,z,n)=>[[x,z],[x+n,z],[x+n,z+n],[x,z+n]];
 const plan={buildings:[{id:'unit',position:[10,20],rotation:30,
  levels:[{id:'L1',elevation:0,ceiling:8,outline:square(0,0,12)},{id:'L2',elevation:8,ceiling:8,outline:square(0,0,8)}],
  rooms:[{id:'room',level:'L2',polygon:square(0,0,8),floor_offset_ft:30}],
  roof:{sections:[{id:'roof',kind:'gable',rect:[0,0,12,12],plate:16,pitch:4,ridge:'x',overhang:2}]}}]};
 for(const mutate of [p=>{},p=>p.buildings[0].roof.sections[0].plate++,p=>p.buildings[0].rotation+=20,p=>p.buildings[0].roof.sections=[]]){
  const p=structuredClone(plan);mutate(p);const a=B.createSkyCover(p),b=C.createSkyCover(p);
  for(let i=0;i<1200;i++){const x=(i%31)/2-2,y=(i%23)/2,z=-((i%37)/2);
   for(const fn of ['open','staticOpen','slabOpen','roofHeight'])assert.equal(b[fn](x,y,z),a[fn](x,y,z),fn+' arithmetic');
   assert.equal(b.coverTop(x,z),a.coverTop(x,z));
  }
 }
 const a=B.createSkyCover(plan),b=C.createSkyCover(plan);
 const mesh=()=>{const o=new THREE.Mesh(new THREE.BoxGeometry(.1,.1,.1),new THREE.MeshStandardMaterial());o.position.set(4,.5,-7);return o;};
 const root=new THREE.Group(),o=mesh();root.add(o);C.writeWeatherOpen(root,b);
 o.userData.kind='roof';C.writeWeatherOpen(root,b);
 const fresh=new THREE.Group(),f=mesh();f.userData.kind='roof';fresh.add(f);B.writeWeatherOpen(fresh,a);
 assert.deepEqual(o.geometry.attributes.weatherOpen.array,f.geometry.attributes.weatherOpen.array,'face kind invalidates');
 o.geometry.setAttribute('weatherOpen',new THREE.Float32BufferAttribute(new Float32Array(o.geometry.attributes.position.count),1));
 C.writeWeatherOpen(root,b);
 assert.deepEqual(o.geometry.attributes.weatherOpen.array,f.geometry.attributes.weatherOpen.array,'replacement attribute invalidates');
 const moved=new Float32Array(o.geometry.attributes.position.array);for(let i=0;i<moved.length;i+=3)moved[i]+=40;
 o.geometry.setAttribute('position',new THREE.Float32BufferAttribute(moved,3));C.writeWeatherOpen(root,b);
 const movedRoot=root.clone(true);movedRoot.children[0].geometry=o.geometry.clone();B.writeWeatherOpen(movedRoot,a);
 assert.deepEqual(o.geometry.attributes.weatherOpen.array,movedRoot.children[0].geometry.attributes.weatherOpen.array,'replacement position buffer invalidates');
 const makeInstances=()=>{const r=new THREE.Group(),m=new THREE.InstancedMesh(new THREE.BoxGeometry(.1,.1,.1),new THREE.MeshStandardMaterial(),4);
  m.userData.weatherInstanceColor=true;m.instanceColor=new THREE.InstancedBufferAttribute(new Float32Array(12),3);
  for(let i=0;i<4;i++)m.setMatrixAt(i,new THREE.Matrix4().makeTranslation(i*6,.5,-7));m.count=1;r.add(m);return [r,m];};
 const [ir,im]=makeInstances(),[jr,jm]=makeInstances();C.writeWeatherOpen(ir,b);B.writeWeatherOpen(jr,a);
 assert.deepEqual(im.instanceColor.array,jm.instanceColor.array,'all capacity sampled');
 im.setMatrixAt(3,new THREE.Matrix4().makeTranslation(4,.5,-7));im.instanceMatrix.needsUpdate=true;C.writeWeatherOpen(ir,b);
 const [kr,km]=makeInstances();km.setMatrixAt(3,new THREE.Matrix4().makeTranslation(4,.5,-7));B.writeWeatherOpen(kr,a);
 assert.deepEqual(im.instanceColor.array,km.instanceColor.array,'instance move invalidates');
 const [small,sm]=makeInstances();sm.userData.weatherInstanceColor=false;sm.instanceColor=null;
 C.writeWeatherOpen(small,b);sm.count=4;C.writeWeatherOpen(small,b);
 const [large,lm]=makeInstances();lm.userData.weatherInstanceColor=false;lm.instanceColor=null;lm.count=4;B.writeWeatherOpen(large,a);
 assert.equal(sm.geometry.attributes.weatherOpen.count,4,'newly active ordinary instances are sampled');
 assert.deepEqual(sm.geometry.attributes.weatherOpen.array,lm.geometry.attributes.weatherOpen.array);
 const {mergeGeometries}=await import('three/addons/utils/BufferGeometryUtils.js');
 const cube=new THREE.BoxGeometry(.2,.2,.2).toNonIndexed().translate(4,.5,-7),mat=new THREE.MeshStandardMaterial();
 const src=new THREE.Group(),source=new THREE.Mesh(cube,mat);src.add(source);
 source.userData.snapRanges=[{start:0,count:36,kind:'fixture',pieceId:'kept',buildingId:'unit'}];C.writeWeatherOpen(src,b);
 const dst=new THREE.Group(),batch=new THREE.Mesh(mergeGeometries([cube.clone().translate(40,0,0),cube.clone()]),mat);dst.add(batch);
 batch.userData.snapRanges=[{start:0,count:36,kind:'fixture',pieceId:'new',buildingId:'unit'},
  {start:36,count:36,kind:'fixture',pieceId:'kept',buildingId:'unit'}];
 const changed=structuredClone(plan);changed.buildings[0].roof.sections[0].rect[0]--;
 const cc=C.createSkyCover(changed),sample=cc.staticOpen;let calls=0;cc.staticOpen=(...args)=>{calls++;return sample(...args);};
 C.writeWeatherOpen(dst,cc,1,src);
 const expected=dst.clone(true);expected.traverse(o=>{if(o.geometry)o.geometry=o.geometry.clone();});B.writeWeatherOpen(expected,B.createSkyCover(changed));
 assert.deepEqual(batch.geometry.attributes.weatherOpen.array,expected.children[0].geometry.attributes.weatherOpen.array,'rebuilt range shifted by a new piece');
 assert.ok(calls<72,'unchanged world samples are reused in a rebuilt batch');
 const base=new THREE.PlaneGeometry(12,12,16,16).rotateX(-Math.PI/2),ground=()=>{
  const root=new THREE.Group(),m=new THREE.Mesh(base.clone(),new THREE.MeshStandardMaterial());m.position.set(4,0,-7);root.add(m);return [root,m];};
 const [gr,gm]=ground();C.writeWeatherOpen(gr,b);
 const raised=structuredClone(plan);raised.buildings[0].roof.sections[0].plate++;
 C.writeWeatherOpen(gr,C.createSkyCover(raised));
 const [hr,hm]=ground();B.writeWeatherOpen(hr,B.createSkyCover(raised));
 for(const name of ['position','uv','weatherOpen'])assert.deepEqual(gm.geometry.attributes[name].array,hm.geometry.attributes[name].array,'height-only clip '+name);
 assert.deepEqual(gm.geometry.index?.array,hm.geometry.index?.array,'height-only indices');
 for(const merged of [false,true])for(const bound of [false,true]){
  const [r,m]=ground(),[s,n]=ground();m.userData.merged=n.userData.merged=merged;
  C.writeWeatherOpen(r,C.createSkyCover(plan));B.writeWeatherOpen(s,B.createSkyCover(plan));
  A.prepareReceivers(r,plan);oldA.prepareReceivers(s,plan);
  if(bound)for(const mesh of [m,n])mesh.geometry.setAttribute('lmRoom',new THREE.Float32BufferAttribute(new Float32Array(mesh.geometry.attributes.position.count),1));
  C.writeWeatherOpen(r,C.createSkyCover(raised));B.writeWeatherOpen(s,B.createSkyCover(raised));
  for(const name of ['position','uv','weatherOpen'])assert.deepEqual(m.geometry.attributes[name].array,n.geometry.attributes[name].array,'atlas-bound '+merged+' '+name);
  assert.deepEqual(m.geometry.index?.array,n.geometry.index?.array,'atlas-bound indices');
 }
});
const FT=.3048;
const rainQuad=(x0,z0,x1,z1,h)=>[x0,z0,h,x1,z0,h,x1,z1,h,x0,z0,h,x1,z1,h,x0,z1,h];
const wingPlan={buildings:[{id:'wing',position:[0,0],rotation:0,levels:[
 {id:'L1',elevation:0,ceiling:10,outline:[[0,0],[20,0],[20,10],[0,10]]},
 {id:'L2',elevation:10,ceiling:10,outline:[[0,0],[10,0],[10,10],[0,10]]}],rooms:[],walls:[]}]};
const wingCover=(module,positions)=>module.createSkyCover(wingPlan,new Map([['wing',{coverPositions:positions,slabPositions:[]}]]));
for(const operation of ['remove','add','shift'])await test('lower wing roof '+operation+' below building fallback top',async()=>{
 const high=rainQuad(-1,-1,11,11,22),low=rainQuad(10,-1,21,11,12),shifted=rainQuad(16,-1,21,11,12);
 const states=operation==='remove'?[[...high,...low],high]:operation==='add'?[high,[...high,...low]]:[[...high,...low],[...high,...shifted]];
 const receiver=()=>{const root=new THREE.Group(),g=new THREE.BufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute([15*FT,15*FT,-5*FT,15.1*FT,15*FT,-5*FT,15*FT,15*FT,-5.1*FT],3));
  root.add(new THREE.Mesh(g,new THREE.MeshStandardMaterial()));return root;};
 for(const [before,after] of [states,[...states].reverse()]){
  const reused=receiver(),fresh=receiver();C.writeWeatherOpen(reused,wingCover(C,before));C.writeWeatherOpen(reused,wingCover(C,after));
  B.writeWeatherOpen(fresh,wingCover(B,after));assert.deepEqual(reused.children[0].geometry.attributes.weatherOpen.array,fresh.children[0].geometry.attributes.weatherOpen.array);
 }
});
for(const atlas of [false,true])await test('matched rebuilt batch '+(atlas?'rejects prepared atlas clone':'clips new geometry'),async()=>{
 const plan=ceiling=>({buildings:[{id:'batch',position:[0,0],levels:[{id:'L1',elevation:0,ceiling,outline:[[2,2],[8,2],[8,8],[2,8]]}],rooms:[],walls:[]}]}),
  roofs=new Map([['batch',{coverPositions:rainQuad(0,0,10,10,12),slabPositions:[]}]]);
 const receiver=()=>{const raw=new THREE.PlaneGeometry(20*FT,10*FT,4,2).rotateX(-Math.PI/2).toNonIndexed().translate(10*FT,FT,-5*FT),g=new THREE.BufferGeometry();
  for(const n of ['position','normal','uv'])g.setAttribute(n,new THREE.BufferAttribute(raw.attributes[n].array.slice(),raw.attributes[n].itemSize));
  const root=new THREE.Group(),parent=new THREE.Group(),mesh=new THREE.Mesh(g,new THREE.MeshStandardMaterial());mesh.userData.merged=true;parent.userData.buildingId='batch';parent.add(mesh);root.add(parent);return [root,mesh];};
 const [before,old]=receiver(),[after,mesh]=receiver(),[fresh,expected]=receiver();C.writeWeatherOpen(before,C.createSkyCover(plan(10),roofs));
 if(atlas)mesh.userData.syncBakeCover=()=>{old.geometry=old.geometry.clone();old.geometry.setAttribute('lmRoom',new THREE.Float32BufferAttribute(new Float32Array(old.geometry.attributes.position.count),1));};
 const next=plan(atlas?10:11);C.writeWeatherOpen(after,C.createSkyCover(next,roofs),1,before);B.writeWeatherOpen(fresh,B.createSkyCover(next,roofs));
 for(const n of ['position','uv','weatherOpen'])assert.deepEqual(mesh.geometry.attributes[n].array,expected.geometry.attributes[n].array,n);
 assert.equal(mesh.geometry.hasAttribute('lmRoom'),false,'prepared atlas geometry is not a clone source');
});
await test('part keys stay lazy and mesh histories retain comparison inputs',async()=>{
 const cover=wingCover(C,rainQuad(0,0,20,10,12));assert.equal(C.rainPartState(cover),false,'creation does not build part keys');
 const root=new THREE.Group().add(new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial()));C.writeWeatherOpen(root,cover);
 assert.equal(C.rainPartState(cover),false,'first write needs no part comparison');
 assert.equal(typeof C.rainCover(root).open,'undefined','written does not retain the sampler');
 for(const key of C.rainParts(cover).keys())if(key.startsWith('roof')||key.startsWith('slab'))assert.equal(key.length,40,'kind and nine exact doubles');
});
await test('untracked cover inputs use fresh sampling on a rebuilt receiver',async()=>{
 const make=()=>{const root=new THREE.Group(),g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute([15*FT,15*FT,-5*FT,15.1*FT,15*FT,-5*FT,15*FT,15*FT,-5.1*FT],3));
  const mesh=new THREE.Mesh(g,new THREE.MeshStandardMaterial());root.userData.buildingId='wing';mesh.userData.kind='fixture';root.add(mesh);return root;};
 const wrapped=positions=>({...wingCover(C,positions),key:undefined}),high=rainQuad(-1,-1,11,11,22),low=rainQuad(10,-1,21,11,12);
 const before=make(),after=make(),fresh=make();C.writeWeatherOpen(before,wrapped([...high,...low]));C.writeWeatherOpen(after,wrapped(high),1,before);C.writeWeatherOpen(fresh,wrapped(high));
 assert.deepEqual(after.children[0].geometry.attributes.weatherOpen.array,fresh.children[0].geometry.attributes.weatherOpen.array);
});
if(results.some(([,error])=>error))finish();
const bytes=a=>a?[a.array.constructor.name,a.itemSize,a.normalized,
 createHash('sha256').update(new Uint8Array(a.array.buffer,a.array.byteOffset,a.array.byteLength)).digest('hex')]:null;
const material=m=>[m.name,m.userData.materialKey??null,m.customProgramCacheKey?.()];
function snapshot(v){
 const rows=[];let geometryBytes=0;const unique=new Set();v.scene.updateMatrixWorld(true);
 v.scene.traverse(o=>{if(!o.isMesh||o.layers.isEnabled(31))return;
  const g=o.geometry;if(!g?.attributes.position)return;
  if(!unique.has(g)){unique.add(g);for(const a of Object.values(g.attributes))geometryBytes+=a.array.byteLength;geometryBytes+=g.index?.array.byteLength||0;}
  rows.push([o.name,[].concat(o.material).map(material),o.matrixWorld.elements,
   ['position','uv','weatherOpen'].map(n=>bytes(g.attributes[n])),bytes(g.index),
   [o.userData.snapRanges??null,g.userData.snapRanges??null],
   [g.drawRange.start,Number.isFinite(g.drawRange.count)?g.drawRange.count:String(g.drawRange.count)],g.groups,
   bytes(o.instanceColor),bytes(o.instanceMatrix),o.count??null]);
 });
 return {rows,geometryBytes};
}
function editList(plan){
 const b=plan.buildings.find(b=>b.porches?.some(p=>p.columns?.length))||plan.buildings[0];
 const other=plan.buildings.find(x=>x!==b&&x.roof?.sections?.length)||b;
 const post=p=>p.buildings.find(x=>x.id===b.id).porches.find(p=>p.columns?.length).columns;
 const build=(p,id=b.id)=>p.buildings.find(x=>x.id===id);
 const roof=(p,id=b.id)=>build(p,id).roof.sections[0];
 const editPosts=(p,mutate)=>{const porch=build(p).porches.find(p=>p.columns?.length);
  porch.columns.forEach((c,i)=>{c.id||=`post:${porch.id}:${i}`;});mutate(porch);};
 const wing=p=>{const b=structuredClone(wingPlan.buildings[0]);b.id='rain-lower-wing';b.name='Rain lower wing';
  b.position=[Math.max(...p.buildings.map(b=>(b.position?.[0]||0)+Math.max(0,...b.levels.flatMap(l=>(l.outline||[]).map(p=>p[0])))))+5,p.buildings[0].position?.[1]||0];
  b.foundation={mode:'auto',offset_ft:0,thickness_ft:1};b.materials={};b.openings=[];b.items=[];b.fixtures=[];b.anchors=[];b.stairs=[];
  b.walls=[{id:'receiver',level:'L2',from:[15,4],to:[16,4],height:5,thickness:.5,exterior:false,state:'settled'}];
  b.roof={sections:[{id:'high',kind:'flat',rect:[-1,-1,11,11],plate:22,overhang:0},
   {id:'low',kind:'flat',rect:[10,-1,21,11],plate:12,overhang:0}],flags:[]};p.buildings.push(b);return p;};
 const low=p=>p.buildings.find(b=>b.id==='rain-lower-wing').roof.sections;
 return [
 ['delete-post',p=>post(p).pop()],['move-post',p=>post(p)[0].at[0]+=.5],
 ['move-post-field',p=>editPosts(p,po=>po.columns[0].at[0]+=.125)],
 ['size-post',p=>editPosts(p,po=>po.columns[0].size=(po.columns[0].size||.5)+.125)],
 ['add-post',p=>editPosts(p,po=>{let i=0;while(po.columns.some(c=>c.id===`post:${po.id}:${i}`))i++;
   po.columns.push({id:`post:${po.id}:${i}`,at:[po.columns[0].at[0]+.25,po.columns[0].at[1]],size:po.columns[0].size||.5});})],
 ['raise-main-roof',p=>roof(p).plate+=.5],['raise-pool-roof',p=>roof(p,other.id).plate+=.5],
 ['move-roof-edge',p=>roof(p).rect[0]-=.5],
 ['add-awning',p=>build(p).roof.sections.push({id:'rain-test-awning',kind:'shed',rect:[-6,-6,6,0],plate:8,pitch:2,low_side:'y0',support:{kind:'post',count:2}})],
 ['delete-awning',p=>{const s=build(p).roof.sections;const i=s.findIndex(s=>s.support?.kind&&s.support.kind!=='walls');s.splice(i<0?s.length-1:i,1);}],
 ['move-wall',p=>{const w=build(p).walls[0];w.from[0]+=.25;w.to[0]+=.25;}],
 ['move-room',p=>{for(const pt of build(p).rooms.find(r=>r.kind!=='porch').polygon)pt[0]+=.25;}],
 ['add-porch',p=>(build(p).porches||=[]).push({id:'rain-test-porch',polygon:[[-8,-8],[-2,-8],[-2,-2],[-8,-2]],floor:0,columns:[]})],
 ['hardscape',p=>{const h=p.site.hardscape[0];for(const pt of h.polygon||h.points||h.polyline)pt[0]+=.5;}],
 ['add-lower-wing-roof',p=>low(p).push({id:'low',kind:'flat',rect:[10,-1,21,11],plate:12,overhang:0}),p=>{wing(p);low(p).pop();return p;}],
 ['remove-lower-wing-roof',p=>low(p).pop(),wing],
 ['shift-lower-wing-roof',p=>low(p)[1].rect[0]=16,wing]
 ];
}
const mountCPU={baseline:0,current:0},mountThreadCPU={baseline:0,current:0};
async function mount(module,plan,kit){const start=process.cpuUsage(),threadStart=process.threadCpuUsage(),shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
 const view=await module.mountTwin(host,{plan:structuredClone(plan),kit:structuredClone(kit),tier:'high',bake:false});
 const elapsed=process.cpuUsage(start),thread=process.threadCpuUsage(threadStart),label=module===baseline?'baseline':'current';
 mountCPU[label]+=(elapsed.user+elapsed.system)/1000;mountThreadCPU[label]+=(thread.user+thread.system)/1000;return view;}
async function yardReady(v){while(v.yardSettling)await new Promise(resolve=>setTimeout(resolve,1));assert.equal(v.yardError,null);}
for(const fixture of privateInput.fixtures){
 const {label,plan,kit}=fixture;
  for(const route of input.route?[input.route]:input.full?['rebuild','settle']:['rebuild']){
  for(let mountRun=0;mountRun<(input.firstLoad?input.repeat:1);mountRun++){
  globalThis.coverCPU={baseline:0,current:0};
  globalThis.coverThreadCPU={baseline:0,current:0};mountCPU.baseline=mountCPU.current=mountThreadCPU.baseline=mountThreadCPU.current=0;
  let old,now;
  if(mountRun%2){now=await mount(current,plan,kit);old=await mount(baseline,plan,kit);}
  else{old=await mount(baseline,plan,kit);now=await mount(current,plan,kit);}
  if(input.metrics){
   const {setFlagsFromString}=await import('node:v8'),{runInNewContext}=await import('node:vm');setFlagsFromString('--expose_gc');const gc=runInNewContext('gc');
   const collect=async()=>{await new Promise(r=>setImmediate(r));gc();gc();};
   const G=await import(file('static/twin/twin_generator.js')),twin=G.buildTwin(plan,kit,'high',{viewing:true});await twin.ready;twin.adoptBuildings?.();
   const geometry=snapshot(now).geometryBytes,median=a=>a.sort((a,b)=>a-b)[a.length>>1],rows={};
   for(const [label,module] of [['baseline',B],['current',C]]){
    const times=[],processTimes=[],wallTimes=[];for(let i=0;i<9;i++){const start=process.threadCpuUsage(),cpu=process.cpuUsage(),clock=performance.now();for(let j=0;j<100;j++)module.createSkyCover(plan,twin.roofSurfaces);const dt=process.threadCpuUsage(start),total=process.cpuUsage(cpu);if(i>=2){times.push((dt.user+dt.system)/100000);processTimes.push((total.user+total.system)/100000);wallTimes.push((performance.now()-clock)/100);}await new Promise(r=>setImmediate(r));}
    await collect();const start=process.memoryUsage(),keep=[];for(let i=0;i<10;i++)keep.push(module.createSkyCover(plan,twin.roofSurfaces));await collect();const cold=process.memoryUsage();
    for(const cover of keep)cover.clipEdges();await collect();const end=process.memoryUsage();
    rows[label]={create_cpu_ms:median(times),create_process_cpu_ms:median(processTimes),create_wall_ms:median(wallTimes),cold_heap_bytes:(cold.heapUsed-start.heapUsed)/10,cold_array_bytes:(cold.arrayBuffers-start.arrayBuffers)/10,cover_heap_bytes:(end.heapUsed-start.heapUsed)/10,cover_array_bytes:(end.arrayBuffers-start.arrayBuffers)/10,stats:keep[0].__rainStats?.()};for(const cover of keep)module.rainParts(cover);await collect();const hot=process.memoryUsage();rows[label].compared_heap_bytes=(hot.heapUsed-start.heapUsed)/10;rows[label].compared_array_bytes=(hot.arrayBuffers-start.arrayBuffers)/10;keep.length=0;await collect();
   }
   const historyRoot=new THREE.Group(),historyMesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial());historyMesh.userData.kind='fixture';historyRoot.add(historyMesh);
   let sampler=C.createSkyCover(plan,twin.roofSurfaces);const sampled=new WeakRef(sampler);C.writeWeatherOpen(historyRoot,sampler);sampler=null;
   await collect();await collect();assert.equal(sampled.deref(),undefined,'written cannot retain an entire sampler');rows.current.written_sampler_collected=true;
   if(!input.metricsQuick){
   const operations=await import(file('static/twin/editor/local_ops.js')),building=plan.buildings.find(b=>b.walls?.length),wall=building.walls[0];
   const gesture=operations.moveGesture(plan,{kind:'wall',building:building.id,id:wall.id}),preview=operations.movePreview(plan,gesture,gesture.normal.map(v=>v*.125));
   for(const [label,v] of [['baseline',old],['current',now]]){const times=[],processTimes=[];for(let i=0;i<7;i++){const start=process.threadCpuUsage(),cpu=process.cpuUsage();v.rebuildLevel(building.id,gesture.piece.level,i%2?plan:preview,gesture.touched);const dt=process.threadCpuUsage(start),total=process.cpuUsage(cpu);if(i>=2){times.push((dt.user+dt.system)/1000);processTimes.push((total.user+total.system)/1000);}await new Promise(r=>setImmediate(r));}rows[label].wall_frame_cpu_ms=median(times);rows[label].wall_frame_process_cpu_ms=median(processTimes);}
   const {GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js'),originalLoad=GLTFLoader.prototype.loadAsync,originalTimer=globalThis.setTimeout;
   const libraries={baseline:await import(urls.get('static/twin/twin_library.js')),current:await import(file('static/twin/twin_library.js'))};
   try{
    globalThis.setTimeout=(fn,delay,...rest)=>originalTimer(fn,delay===15000?0:delay,...rest);
    for(const [name,module] of [['baseline',baseline],['current',current]]){const times=[],processTimes=[];let lateCalls=0;
     for(let run=0;run<6;run++){
      const p=structuredClone(plan),b=p.buildings.find(b=>b.rooms.some(r=>r.kind!=='porch')),room=b.rooms.find(r=>r.kind!=='porch'),pending=[];
      for(let i=0;i<8;i++){const id='import-'+(label==='owner'?'1':'0')+(name==='baseline'?'a':'b')+String(run*8+i).padStart(30,'0');libraries[name].rememberImport({id,model:'mesh.gltf',files:{'mesh.gltf':true},triangles:12});
       (b.items||=[]).push({id:'rain-late-'+i,asset:id,host:{floor:room.id,u:.5,v:.5},state:'settled'});}
      GLTFLoader.prototype.loadAsync=()=>new Promise(resolve=>pending.push(resolve));
      const start=process.threadCpuUsage(),cpu=process.cpuUsage(),out=await mount(module,p,kit);await yardReady(out);const before=coverCalls[name];
      assert.ok(out.scene.getObjectByName('yard'),'late-import load includes the mounted yard');
      assert.equal(pending.length,8,'eight actual delayed model requests');
      for(const resolve of pending)resolve({scene:new THREE.Group().add(new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial()))});
      await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));lateCalls=coverCalls[name]-before;assert.equal(lateCalls,8,'late callbacks sample all eight imported holders');
      const dt=process.threadCpuUsage(start),total=process.cpuUsage(cpu);if(run){times.push((dt.user+dt.system)/1000);processTimes.push((total.user+total.system)/1000);}out.dispose();
     }rows[name].late_import_load_cpu_ms=median(times);rows[name].late_import_load_process_cpu_ms=median(processTimes);rows[name].late_cover_calls=lateCalls;
    }
   }finally{GLTFLoader.prototype.loadAsync=originalLoad;globalThis.setTimeout=originalTimer;}
   }
   console.log('RAIN_METRICS '+JSON.stringify({fixture:label,geometry_bytes:geometry,source_triangles:[...twin.roofSurfaces.values()].reduce((n,s)=>n+(s.coverPositions.length+s.slabPositions.length)/9,0),...rows}));
   assert.ok(rows.current.create_process_cpu_ms<=rows.baseline.create_process_cpu_ms*1.1,'cover construction process CPU <= pinned +10%');
   assert.ok(rows.current.create_cpu_ms<=rows.baseline.create_cpu_ms*1.1,'cover construction main-thread CPU <= pinned +10%');
   if(label==='owner')assert.ok(Math.max(...['cold','cover','compared'].map(stage=>rows.current[stage+'_heap_bytes']+rows.current[stage+'_array_bytes']))<=geometry*.1,'live retained cover including typed arrays <=10% of drawn geometry');
   if(!input.metricsQuick)for(const metric of ['wall_frame_cpu_ms','wall_frame_process_cpu_ms','late_import_load_cpu_ms','late_import_load_process_cpu_ms'])assert.ok(rows.current[metric]<=rows.baseline[metric],metric+' no slower than pinned');
   old.dispose();now.dispose();continue;
  }
  let settlePath=null;
  async function compare(name){const a=snapshot(old),b=snapshot(now);
   assert.equal(b.rows.length,a.rows.length,`${label}/${route}/${name}: mesh count`);
   const digest=row=>createHash('sha256').update(JSON.stringify(row)).digest('hex');
   for(let i=0;i<a.rows.length;i++)for(let field=0;field<a.rows[i].length;field++){
    if(field===3){for(let k=0;k<a.rows[i][3].length;k++)assert.equal(digest(b.rows[i][3][k]),digest(a.rows[i][3][k]),`${label}/${route}/${name}: mesh ${i} ${['position','uv','weatherOpen'][k]}`);}
    else assert.equal(digest(b.rows[i][field]),digest(a.rows[i][field]),`${label}/${route}/${name}: mesh ${i} field ${field} buffers/ranges/keys`);
   }
   assert.equal(old.yardError,null);assert.equal(now.yardError,null);
   const memory={baseline:B.rainMemory(old.scene),current:C.rainMemory(now.scene)};
   assert.ok(memory.current.samples-memory.baseline.samples<=b.geometryBytes*.1,'additional stored samples <=10% of geometry');
   const cpu_ms={...coverCPU},thread_cpu_ms={...coverThreadCPU};let atlas;
   if(input.full&&!input.noAtlas){const start=process.cpuUsage(),roots=(v,s)=>{const root=v.scene.children.find(s.isBakeRoot);return input.bindAtlas?root:s.bakeSource(root);},layout={room:{density:1,page:512,gutter:2}};
    const a=oldA.buildAtlas(roots(old,oldS),old.plan,layout),b=A.buildAtlas(roots(now,S),now.plan,layout);
    assert.equal(b.key,a.key,`${label}/${route}/${name}: atlas/bake key`);assert.equal(b.room.charts.length,a.room.charts.length,'chart count');const elapsed=process.cpuUsage(start);atlas={key_equal:true,charts:b.room.charts.length,cpu_ms:(elapsed.user+elapsed.system)/1000};}
   // Drain provider callbacks and end the edit's turn before resetting timers.
   // Real editor actions occur in separate turns; weak comparison lookups may
   // be collected between them rather than accumulating across a repeat loop.
   await new Promise(resolve=>setImmediate(resolve));
   console.log('RAIN_COVER '+JSON.stringify({fixture:label,route,edit:name,settle_path:settlePath,cpu_ms,thread_cpu_ms,fresh_baseline:!input.noAtlas,
    mount_cpu_ms:name.startsWith('first-build')?{...mountCPU}:undefined,mount_thread_cpu_ms:name.startsWith('first-build')?{...mountThreadCPU}:undefined,
    geometry_bytes:b.geometryBytes,meshes:b.rows.length,memory,atlas}));}
  await compare(input.firstLoad?'first-build#'+mountRun:'first-build');
  if(input.firstLoad){old.dispose();now.dispose();continue;}
  let edits=editList(plan);if(!input.full)edits=edits.filter(([n])=>['delete-post','move-post-field','size-post','add-post','raise-pool-roof','move-roof-edge'].includes(n));
  if(input.edits)edits=edits.filter(([n])=>input.edits.includes(n));
  async function apply(p,name){globalThis.coverCPU={baseline:0,current:0};globalThis.coverThreadCPU={baseline:0,current:0};
   const edit=name.replace(/^undo-/,'').replace(/#\d+$/,'');
   const field=edit==='move-post-field';
   const update=async v=>{const next=structuredClone(p);
    if(!field)return v[route](next);
    const b=next.buildings.find(b=>b.porches?.some(po=>po.columns?.length)),po=b.porches.find(po=>po.columns?.length);
    const level=b.rooms.find(r=>r.id===po.id)?.level||po.level||b.levels[0].id;
    v.rebuildLevel(b.id,level,next,{walls:[],rooms:[],openings:[],anchors:[],items:[]});
    return v.settle(next,{buildingId:b.id,levelId:level});};
   const oldOutcome=await update(old);
   await yardReady(old);
   const beforeCover=input.diagnostics?C.rainCover(now.scene):null;
   if(profiler){await profileCall('Profiler.enable');await profileCall('Profiler.start');}
   const outcome=await update(now);
   await yardReady(now);
   settlePath=outcome?.path??null;
   assert.equal(outcome?.path,oldOutcome?.path,'pinned and current use the same view path');
   if(field||route==='settle'&&['size-post','move-wall','move-room','hardscape'].includes(edit))assert.equal(settlePath,'deform','exercise the actual post/level deformation/deferred-yard path');
   if(route==='settle'&&['add-post','delete-post'].includes(edit))assert.equal(settlePath,'rebuild','post topology rebuilds');
   if(profiler){const {profile}=await profileCall('Profiler.stop');writeFileSync(input.profile+'/'+label+'-'+route+'-'+name+'.cpuprofile',JSON.stringify(profile));}
   if(input.diagnostics)console.log('RAIN_DIAGNOSTICS '+JSON.stringify({fixture:label,edit:name,...C.rainDiagnostics(beforeCover,C.rainCover(now.scene))}));
   await compare(name);}
  try{for(const [name,mutate,setup] of edits)for(let repeat=0;repeat<input.repeat;repeat++){
    const suffix=input.repeat>1?'#'+repeat:'',base=setup?setup(structuredClone(plan)):plan;
    if(setup)await apply(base,'setup-'+name+suffix);
    const p=structuredClone(base);mutate(p);await apply(p,name+suffix);await apply(base,'undo-'+name+suffix);}
   if(input.full&&!input.edits){await apply(plan,'reset-lower-wing');const p=structuredClone(plan);edits.find(([n])=>n==='delete-post')[1](p);await apply(p,'two-edits-first');edits.find(([n])=>n==='raise-main-roof')[1](p);await apply(p,'two-edits-second');await apply(plan,'undo-two-edits');}
  }finally{old.dispose();now.dispose();}
  }
 }
}
if(input.metrics){console.log('PASS rain-cover performance gates');process.exit(0);}
console.log('PASS pinned rain-cover equality');
finish();
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--owner-export', type=Path, default=OWNER)
    parser.add_argument('--fixture', choices=['household', 'owner'])
    parser.add_argument('--route', choices=['rebuild', 'settle'])
    parser.add_argument('--edits', nargs='+', help='Focused rerun within the same pinned harness')
    parser.add_argument('--no-atlas', action='store_true', help='Profile edit CPU without preparing live atlas receivers')
    parser.add_argument('--unit-only', action='store_true', help='Run just the fast arithmetic and invalidation cases')
    parser.add_argument('--profile', type=Path, help='Existing directory for current-edit Node CPU profiles')
    parser.add_argument('--diagnostics', action='store_true', help='Print cache counts and projection checks, never plan contents')
    parser.add_argument('--repeat', type=int, default=1, help='Repeat each edit/undo for CPU medians')
    parser.add_argument('--bind-atlas', action='store_true', help='Additional live atlas-bound receiver stress run')
    parser.add_argument('--post-move', action='store_true', help='Only the post-field matrix edit against the pinned baseline')
    parser.add_argument('--first-load', action='store_true', help='Only paired mounts; --repeat sets mount count, alternating order')
    parser.add_argument('--metrics', action='store_true', help='Measure cover construction, live retained heap and complete wall drag frames')
    parser.add_argument('--metrics-quick', action='store_true', help='Construction/heap measurements without full frames and imports')
    parser.add_argument('--candidate-ref', help='Reproduce a reviewed candidate by commit, leaving the baseline pinned')
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    if args.post_move:
        args.edits = ['move-post-field']
    if args.metrics_quick:
        args.metrics = True
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    household = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    fixtures = [{'label': 'household', 'plan': flatten(assemble(household)[0]), 'kit': kit}]
    if args.full:
        model = json.loads(args.owner_export.read_text(encoding='utf-8'))['model']
        fixtures.append({'label': 'owner', 'plan': flatten(model), 'kit': kit})
    if args.fixture:
        fixtures = [f for f in fixtures if f['label'] == args.fixture]
        if not fixtures:
            parser.error('--fixture owner requires --full')
    if args.unit_only:
        fixtures = []
    paths = []
    try:
        for suffix, content in (('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix(), 'sources': sources(),
                'candidateSources':sources(args.candidate_ref) if args.candidate_ref else None,
                'metricsQuick':args.metrics_quick,'metrics':args.metrics,'firstLoad': args.first_load,'full': args.full, 'route': args.route, 'edits': args.edits, 'noAtlas': args.no_atlas, 'profile': args.profile.resolve().as_posix() if args.profile else None, 'diagnostics': args.diagnostics, 'repeat': args.repeat, 'bindAtlas': args.bind_atlas}))):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='rain_cover_', delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        driver, job = paths
        result = subprocess.run([shutil.which('node') or 'node', str(driver), str(job)],
                                input=json.dumps({'fixtures': fixtures}), text=True, encoding='utf-8',
                                timeout=7200 if args.full else 230)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
