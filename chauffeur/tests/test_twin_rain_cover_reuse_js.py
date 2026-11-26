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
BASELINE = '49a643ab'
POST_CALLER = '46e1361f'
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
globalThis.coverCPU={baseline:0,current:0};globalThis.coverThreadCPU={baseline:0,current:0};globalThis.coverDepth=0;
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
 return source+`\nexport function rainCover(root){let cover;root.traverse(o=>{cover||=written.get(o)?.cover;});return cover;}
 export function rainDiagnostics(before,after){const a=coverParts.get(before),b=coverParts.get(after),removed={},added={};
 for(const k of a.keys())if(!b.has(k))removed[k.slice(0,4)]=(removed[k.slice(0,4)]||0)+1;
 for(const k of b.keys())if(!a.has(k))added[k.slice(0,4)]=(added[k.slice(0,4)]||0)+1;
 const x=coverGeometry.get(before),y=coverGeometry.get(after);let changedXZ=0;for(let i=0;i<Math.min(x.triangles.length,y.triangles.length);i++)for(let j=0;j<3;j++)if(x.triangles[i].p[j][0]!==y.triangles[i].p[j][0]||x.triangles[i].p[j][2]!==y.triangles[i].p[j][2])changedXZ++;
 return {removed,added,triangles:[x.triangles.length,y.triangles.length],changedXZ,polygonsEqual:x.polygons===y.polygons,projection:sameProjection(before,after),edgeSafe:[edgeSafety.get(before),edgeSafety.get(after)],dirty:changedCover(before,after).map(b=>({heightBand:Number.isFinite(b[4]),finiteTop:Number.isFinite(b[5])}))};}
 export function rainMemory(root){let samples=0,baseGeometry=0,numeric=0,partBytes=0;const arrays=new Set(),covers=new Set();
 root.traverse(o=>{const s=written.get(o);if(!s)return;for(const a of [s.base,s.faces])if(!arrays.has(a)){arrays.add(a);samples+=a.byteLength;}
 if(s.world)numeric+=16*8+6*8;
 const saved=unclipped.get(o);if(saved&&saved.base!==o.geometry)for(const a of Object.values(saved.base.attributes))if(!arrays.has(a.array)){arrays.add(a.array);baseGeometry+=a.array.byteLength;}
 if(typeof coverParts!=='undefined'&&s.cover&&!covers.has(s.cover)){covers.add(s.cover);for(const [k,b] of coverParts.get(s.cover)||[])partBytes+=k.length*2+b.length*8;}
 });return {samples,baseGeometry,numeric,partBytes};}
 export function writeWeatherOpen(...args){const outer=!globalThis.coverDepth++;
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
 load(url,ctx,next){const r=next(url,ctx);return url===file('static/twin/sky/sky_cover.js')
 ?{...r,source:instrument(String(r.source),'current')}:r;}});
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
 return [
 ['delete-post',p=>post(p).pop()],['move-post',p=>post(p)[0].at[0]+=.5],
 ['raise-main-roof',p=>roof(p).plate+=.5],['raise-pool-roof',p=>roof(p,other.id).plate+=.5],
 ['move-roof-edge',p=>roof(p).rect[0]-=.5],
 ['add-awning',p=>build(p).roof.sections.push({id:'rain-test-awning',kind:'shed',rect:[-6,-6,6,0],plate:8,pitch:2,low_side:'y0',support:{kind:'post',count:2}})],
 ['delete-awning',p=>{const s=build(p).roof.sections;const i=s.findIndex(s=>s.support?.kind&&s.support.kind!=='walls');s.splice(i<0?s.length-1:i,1);}],
 ['move-wall',p=>{const w=build(p).walls[0];w.from[0]+=.25;w.to[0]+=.25;}],
 ['move-room',p=>{for(const pt of build(p).rooms.find(r=>r.kind!=='porch').polygon)pt[0]+=.25;}],
 ['add-porch',p=>(build(p).porches||=[]).push({id:'rain-test-porch',polygon:[[-8,-8],[-2,-8],[-2,-2],[-8,-2]],floor:0,columns:[]})],
 ['hardscape',p=>{const h=p.site.hardscape[0];for(const pt of h.polygon||h.points||h.polyline)pt[0]+=.5;}]
 ];
}
const mountCPU={baseline:0,current:0},mountThreadCPU={baseline:0,current:0};
async function mount(module,plan,kit){const start=process.cpuUsage(),threadStart=process.threadCpuUsage(),shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
 const view=await module.mountTwin(host,{plan:structuredClone(plan),kit:structuredClone(kit),tier:'high',bake:false});
 const elapsed=process.cpuUsage(start),thread=process.threadCpuUsage(threadStart),label=module===baseline?'baseline':'current';
 mountCPU[label]+=(elapsed.user+elapsed.system)/1000;mountThreadCPU[label]+=(thread.user+thread.system)/1000;return view;}
async function yardReady(v){while(v.yardSettling)await new Promise(resolve=>setTimeout(resolve,1));assert.equal(v.yardError,null);}
if(!input.postMove)for(const fixture of privateInput.fixtures){
 const {label,plan,kit}=fixture;
  for(const route of input.route?[input.route]:input.full?['rebuild','settle']:['rebuild']){
  globalThis.coverCPU={baseline:0,current:0};
  globalThis.coverThreadCPU={baseline:0,current:0};mountCPU.baseline=mountCPU.current=mountThreadCPU.baseline=mountThreadCPU.current=0;
  const old=await mount(baseline,plan,kit),now=await mount(current,plan,kit);
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
   // Detached source providers can finish their ready callbacks in microtasks.
   // Drain them before the next edit's counters are reset.
   if(atlas)await new Promise(resolve=>setImmediate(resolve));
   console.log('RAIN_COVER '+JSON.stringify({fixture:label,route,edit:name,settle_path:settlePath,cpu_ms,thread_cpu_ms,fresh_baseline:!input.noAtlas,
    mount_cpu_ms:name==='first-build'?{...mountCPU}:undefined,mount_thread_cpu_ms:name==='first-build'?{...mountThreadCPU}:undefined,
    geometry_bytes:b.geometryBytes,meshes:b.rows.length,memory,atlas}));}
  await compare('first-build');
  let edits=editList(plan);if(!input.full)edits=edits.filter(([n])=>['delete-post','raise-pool-roof','move-roof-edge'].includes(n));
  if(input.edits)edits=edits.filter(([n])=>input.edits.includes(n));
  async function apply(p,name){globalThis.coverCPU={baseline:0,current:0};globalThis.coverThreadCPU={baseline:0,current:0};
   await old[route](structuredClone(p));
   await yardReady(old);
   const beforeCover=input.diagnostics?C.rainCover(now.scene):null;
   if(profiler){await profileCall('Profiler.enable');await profileCall('Profiler.start');}
   const outcome=await now[route](structuredClone(p));
   await yardReady(now);
   settlePath=outcome?.path??null;
   if(route==='settle'&&['move-wall','move-room','hardscape'].includes(name.replace(/^undo-/,'')))assert.equal(settlePath,'deform','exercise the actual settle deformation/deferred-yard path');
   if(profiler){const {profile}=await profileCall('Profiler.stop');writeFileSync(input.profile+'/'+label+'-'+route+'-'+name+'.cpuprofile',JSON.stringify(profile));}
   if(input.diagnostics)console.log('RAIN_DIAGNOSTICS '+JSON.stringify({fixture:label,edit:name,...C.rainDiagnostics(beforeCover,C.rainCover(now.scene))}));
   await compare(name);}
  try{for(const [name,mutate] of edits)for(let repeat=0;repeat<input.repeat;repeat++){
    const suffix=input.repeat>1?'#'+repeat:'';const p=structuredClone(plan);mutate(p);await apply(p,name+suffix);await apply(plan,'undo-'+name+suffix);}
   if(input.full&&!input.edits){const p=structuredClone(plan);edits[0][1](p);await apply(p,'two-edits-first');edits[2][1](p);await apply(p,'two-edits-second');await apply(plan,'undo-two-edits');}
  }finally{old.dispose();now.dispose();}
 }
}
if(input.full||input.postMove){
 const postPaths=Object.keys(input.postSources),graphs={};
 for(const label of ['baseline','current']){
  const graph=new Map();
  for(const [path,original] of Object.entries(input.postSources)){
   if(label==='current'&&path.endsWith('/sky_cover.js')){graph.set(path,file(path));continue;}
   let source=original;
   if(path.endsWith('/sky_cover.js')){
    const anchor='export function refreshSlabCover';
    source=input.sources[path].split(anchor)[0]+anchor+original.split(anchor)[1];
    source=instrument(source,'baseline');
   }
   if(path.endsWith('/twin_generator.js'))source=source.replace('writeWeatherOpen(root, next.skyCover);','writeWeatherOpen(root, next.skyCover, 1, previous?.root);');
   source=source.replaceAll('import.meta.url',JSON.stringify(file(path)))
    .replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
      const url=new URL(s,file(path)).href,ref=postPaths.find(p=>file(p)===url);return a+(ref?'rain-post-'+label+':'+ref:url)+b;
    });
   graph.set(path,data(source));
  }
  graphs[label]=graph;
 }
 registerHooks({resolve(spec,ctx,next){for(const label of ['baseline','current']){
  const prefix='rain-post-'+label+':';if(spec.startsWith(prefix))return {url:graphs[label].get(spec.slice(prefix.length)),shortCircuit:true};}
  return next(spec,ctx);}});
 const oldPost=await import(graphs.baseline.get('static/twin/twin_view.js')),newPost=await import(graphs.current.get('static/twin/twin_view.js'));
 for(const fixture of privateInput.fixtures){
  const {label,plan,kit}=fixture,b=plan.buildings.find(b=>b.porches?.some(p=>p.columns?.length)),porch=b.porches.find(p=>p.columns?.length);
  const level=b.rooms.find(r=>r.id===porch.id)?.level||porch.level||b.levels[0].id;
  const old=await mount(oldPost,plan,kit),now=await mount(newPost,plan,kit);
  const moved=structuredClone(plan);moved.buildings.find(x=>x.id===b.id).porches.find(x=>x.id===porch.id).columns[0].at[0]+=.125;
  const hint={walls:[],rooms:[],openings:[],anchors:[],items:[]};
  try{for(let i=0;i<input.repeat;i++)for(const [name,p] of [['post-field-move',moved],['undo-post-field-move',plan]]){
    globalThis.coverCPU={baseline:0,current:0};globalThis.coverThreadCPU={baseline:0,current:0};
    for(const v of [old,now]){const next=structuredClone(p);v.rebuildLevel(b.id,level,next,hint);
      assert.equal((await v.settle(next,{buildingId:b.id,levelId:level})).path,'deform','actual post caller deforms');await yardReady(v);}
    const a=snapshot(old),z=snapshot(now),hash=x=>createHash('sha256').update(JSON.stringify(x)).digest('hex');
    assert.equal(hash(z.rows),hash(a.rows),label+' post caller exact buffers/ranges/program keys');
    console.log('RAIN_POST '+JSON.stringify({fixture:label,caller:input.postCaller,edit:name+'#'+i,cpu_ms:coverCPU,thread_cpu_ms:coverThreadCPU,geometry_bytes:z.geometryBytes}));
  }}finally{old.dispose();now.dispose();}
 }
}
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
    parser.add_argument('--post-move', action='store_true', help='Only the binding post-field gate through pinned caller 46e1361f')
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be positive')
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
        for suffix, content in (('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix(), 'sources': sources(), 'postSources': sources(POST_CALLER) if args.full or args.post_move else None,
                'postCaller': POST_CALLER,'postMove': args.post_move,'full': args.full, 'route': args.route, 'edits': args.edits, 'noAtlas': args.no_atlas, 'profile': args.profile.resolve().as_posix() if args.profile else None, 'diagnostics': args.diagnostics, 'repeat': args.repeat, 'bindAtlas': args.bind_atlas}))):
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
