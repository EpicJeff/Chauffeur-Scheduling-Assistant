"""One neutral atlas across tiers, including actual Low receiver addressing.

Optional owner export stays outside the repository: --owner-export PATH.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from twin_editor_dom import run_node
from test_twin_tree_once_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    rect = [[0, 0], [12, 0], [12, 10], [0, 10]]
    return {'buildings': [{'id': 'b', 'position': [0, 0],
        'levels': [{'id': 'L1', 'elevation': 0, 'ceiling': 8, 'outline': rect}],
        'rooms': [{'id': 'r', 'level': 'L1', 'polygon': rect}],
        'walls': [{'id': f'w{i}', 'level': 'L1', 'from': rect[i], 'to': rect[(i+1) % 4],
                   'height': 8, 'thickness': .5, 'exterior': True} for i in range(4)],
        'openings': [{'id': 'window', 'wall': 'w0', 'at': 5, 'width': 3, 'sill': 2, 'head': 7, 'kind': 'window'}],
        'roofs': [{'id': 'roof', 'area': rect, 'overhang': 1,
                   'edges': [{'setting': 'sloped', 'pitch': 5, 'gutter': True} for _ in rect]}],
        'roof': {'sections': [{'id': 'roof', 'roof': 'roof', 'kind': 'hip', 'plate': 8,
                              'pitch': 5, 'overhang': 1, 'level': 'L1', 'rect': [0, 0, 12, 10],
                              'gutters': {'y0': True, 'x1': True, 'y1': True, 'x0': True}}]}}],
        'site': {'lot': [[-5, -5], [25, -5], [25, 25], [-5, 25]],
            'terraces': [{'id': 'pad', 'polygon': [[14, 0], [23, 0], [23, 8], [14, 8]], 'height': 2, 'blend': 3}],
            'planting': [{'id': 'tree', 'at': [20, 18], 'preset': 'Oak Medium', 'height': 10, 'seed': 3}],
            'fence': [{'id': 'fence', 'type': 'picket', 'polyline': [[-3, 14], [10, 14]], 'height': 4}],
            'hardscape': [{'id': 'patio', 'polygon': [[12, 0], [24, 0], [24, 10], [12, 10]], 'material': 'concrete'}],
            'beds': [{'id': 'bed', 'polygon': [[14, 12], [19, 12], [19, 16], [14, 16]]}],
            'edges': [{'id': 'border', 'polygon': [[0, 18], [8, 18], [8, 21], [0, 21]]}],
            'pool': {'id': 'pool', 'polygon': [[14, 18], [19, 18], [19, 23], [14, 23]], 'depth': 4,
                     'features': [{'id': 'spa', 'kind': 'spa', 'mode': 'flush',
                                   'polygon': [[17, 21], [19, 21], [19, 23], [17, 23]]}]}},
        'effect_fixtures': [{'id': 'bubbles', 'type': 'bubbler', 'at': [15, 19, 0], 'ref': 'absolute'}],
        'materials': {}}


DRIVER = PREFIX + r"""
if(input.mainSources)registerHooks({load(url,ctx,next){
 const source=input.mainSources[url];return source===undefined?next(url,ctx):{format:'module',source,shortCircuit:true};
}});
const THREE=await import('three');
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {buildAtlas,atlasMesh,prepareReceivers,heightfieldExtent}=await import(file('static/twin/bake/atlas.js'));
const {atlasJob,packAtlas,applyAtlas,covered}=await import(file('static/twin/bake/atlas_transport.js'));
const {bakeSource,registerBakeSource,cloneBakeGeometry,bakeReceiverRoots,isBakeRoot}=await import(file('static/twin/bake/source.js'));
const {materialParts}=await import(file('static/twin/bake/bindings.js'));
const {createHash}=await import('node:crypto');
const {disposeObject}=await import(file('static/twin/twin_library.js'));
const {releaseBakeSource}=await import(file('static/twin/bake/source.js'));
const {withoutSurfaceMaterials}=await import(file('static/twin/bake/geometry_key.js'));
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const arrayHash=a=>a?createHash('sha256').update(new Uint8Array(a.buffer,a.byteOffset,a.byteLength)).digest('hex'):null;
const meshes=root=>{const a=[];root.traverse(m=>{if(atlasMesh(m))a.push(m);});return a;};
const layout={room:{density:8,page:2048,gutter:2}};
// Pass the private export only by path. Flatten through a stdin pipe so no
// owner plan is serialized into the worktree-local Node job/temp files.
const plan=input.ownerExport?JSON.parse(readFileSync(0,'utf-8')):input.plan;
const kit={materials:{},manifest:{}};
// Geometry and real atlas/bindings run unchanged. Optional vegetation draws are
// excluded from the bake; cached cards avoid a GPU just for the drawn Low yard.
const cards=new Map();
for(const p of plan.site?.planting||[])if(p.preset&&!cards.has('plant_card:'+p.preset)){const m=new THREE.MeshStandardMaterial({alphaTest:.5});
 m.userData.cardAspect=1;m.userData.cardSeed=p.seed??1;cards.set('plant_card:'+p.preset,m);}
async function scene(tier,drawn=false,finished=false){
 const start=performance.now();
 const geometryPlan=drawn?structuredClone(plan):withoutSurfaceMaterials(plan);
 if(finished)geometryPlan.buildings[0].materials={siding:{id:'opaque-paint'}};
 const out=buildTwin(geometryPlan,kit,tier,{viewing:true,...(!drawn?{bakeSource:true}:{})});await out.ready;
 const yard=await buildYard(geometryPlan,kit,tier,{viewing:true,materials:drawn?new Map(cards):null,
  ...(!drawn?{bakeSource:true}:{}),skyCover:out.skyCover});
 out.groups.site.add(yard.group);out.root.updateMatrixWorld(true);
 if(!drawn){registerBakeSource(yard.group,()=>cloneBakeGeometry(yard.group),{extras:false});
  registerBakeSource(out.root,()=>cloneBakeGeometry(out.root),{extras:false});}
 return {out,yard,ms:performance.now()-start};
}
function signature(root){return hash(meshes(root).map(m=>[m.material.name,m.matrixWorld.elements,
 m.geometry.userData.bakeHeightfield?['heightfield',heightfieldExtent(m.geometry)]:[
 Object.fromEntries(Object.entries(m.geometry.attributes).map(([k,a])=>[k,arrayHash(a.array)])),
 arrayHash(m.geometry.index?.array)]]));}
function charts(atlas){return hash([atlas.room.charts.map(c=>[c.key,c.page,c.rect,c.field,
 c.mesh.material.name,c.heightfield?'heightfield':c.faces]),[...new Set(atlas.room.charts.filter(c=>!c.heightfield).map(c=>c.mesh))].map(m=>
 [arrayHash(m.geometry.attributes.uv3.array),arrayHash(m.geometry.attributes.lmLightPage.array)])]);}
const tiers=[];
let packed,highMatrices,highCharts;
const referenceFaces=new Map();
const pointKey=p=>p.toArray().map(x=>Math.round(x*1e5)).join(',');
const faceKey=points=>points.map(pointKey).sort().join('|');
function referenceFor(chart){
 if(referenceFaces.has(chart.id))return referenceFaces.get(chart.id);
 const source=highCharts.get(chart.id);
 assert.ok(source&&source.key===chart.key,'bound chart has its own canonical source chart');
 const faces=new Map(),triangles=[];
 for(const part of [{mesh:source.mesh,faces:source.faces},...(source.proxies||[])]){
  const g=packed.geometries[part.mesh],p=g.attributes.position.array,uv=g.attributes.uv3.array;
  for(const f of part.faces){const points=[0,1,2].map(k=>new THREE.Vector3().fromArray(p,(f*3+k)*3).applyMatrix4(highMatrices[part.mesh]));
   const key=faceKey(points),values=new Map(points.map((v,k)=>[pointKey(v),[uv[(f*3+k)*2],uv[(f*3+k)*2+1]]]));
   if(!faces.has(key))faces.set(key,[]);faces.get(key).push(values);
   triangles.push({triangle:new THREE.Triangle(...points),uv:[0,1,2].map(k=>[uv[(f*3+k)*2],uv[(f*3+k)*2+1]])});
  }
 }
 const result={faces,triangles};referenceFaces.set(chart.id,result);return result;
}
if(input.drawCost){
 const s=await scene('low',true);
 const stats=()=>{let draws=0,triangles=0;
  s.out.root.traverseVisible(m=>{if(!m.isMesh||m.layers.isEnabled(31))return;
   draws+=Array.isArray(m.material)?m.geometry.groups.filter(g=>m.material[g.materialIndex]?.visible).length:Number(m.material.visible);
   triangles+=(m.geometry.index?.count??m.geometry.attributes.position.count)/3*(m.isInstancedMesh?m.count:1);});
  return {draws,triangles};};
 const before=stats(),atlas=buildAtlas(s.out.root,plan,layout);
 console.log('DRAW_COST '+JSON.stringify({before,after:stats(),key:atlas.key}));process.exit(0);
}
if(input.measure){
 const times=[],cpuMs=[];
 for(let i=0;i<6;i++){
  const start=process.cpuUsage(),s=await scene('low'),cpu=process.cpuUsage(start);
  times.push(s.ms);cpuMs.push((cpu.user+cpu.system)/1000);disposeObject(s.out.root);
 }
 console.log('SOURCE_BUILD_MS '+JSON.stringify({elapsedMs:times,cpuMs}));process.exit(0);
}
for(const tier of ['high','low','medium','max']){
 const s=await scene(tier),job=atlasJob(s.out.root,plan,layout),source=signature(bakeSource(s.out.root));
 const atlas=buildAtlas(s.out.root,plan,layout);
 const field=meshes(bakeSource(s.out.root)).find(m=>m.geometry.userData.bakeHeightfield);
 const row={tier,ms:s.ms,key:atlas.key,cacheKey:job.cacheKey,terrainStep:job.terrainStep,source,charts:charts(atlas),
  terrainTriangles:(field.geometry.index?.count??field.geometry.attributes.position.count)/3};tiers.push(row);
 // The worker packs its canonical source in input order, before binding any
 // drawn receiver. Exercise the same transport contract on the cached path.
 if(tier==='high'){const root=bakeSource(s.out.root);packed=packAtlas(buildAtlas(root,plan,layout),covered(root));
  highMatrices=covered(root).map(m=>m.matrixWorld.clone());highCharts=new Map(packed.room.charts.map(c=>[c.id,c]));}
 console.log(JSON.stringify(row));
 releaseBakeSource(s.out.root);disposeObject(s.out.root);
}
await test('all_tiers_have_identical_source_buffers_and_worker_inputs',()=>{
 for(const r of tiers) {assert.equal(r.source,tiers[0].source,r.tier+' bake buffers');
  assert.equal(r.cacheKey,tiers[0].cacheKey,r.tier+' worker inputs');}
});
await test('low_source_retains_its_own_coarse_terrain',()=>{
 assert.ok(tiers.find(r=>r.tier==='low').terrainTriangles<tiers[0].terrainTriangles,'Low must not build the 1 ft source grid');
 for(const row of tiers)assert.equal(row.terrainStep,row.tier==='low'?2:1,'actual source geometry classifies its cache partition');
});
await test('all_tiers_have_identical_atlas_keys_and_receiver_UV_layout',()=>{
 for(const r of tiers){assert.equal(r.key,tiers[0].key,r.tier+' atlas key');assert.equal(r.charts,tiers[0].charts,r.tier+' charts/UVs');}
});
for(const tier of input.owner?['low']:['low','medium','high','max'])for(const cached of [false,true])
await test(`drawn_${tier}_uses_high_pages_${cached?'cached':'built'}_without_extra_triangles`,async()=>{
 const s=await scene(tier,true),source=bakeSource(s.out.root),job=atlasJob(s.out.root,plan,layout);
 assert.equal(job.cacheKey,tiers[0].cacheKey,'drawn provider worker input');
 prepareReceivers(s.out.root,plan);
 const beforeMeshes=meshes(s.out.root),triangles=list=>list.reduce((n,m)=>n+(m.geometry.index?.count??m.geometry.attributes.position.count)/3,0);
 const beforeTotal=triangles(beforeMeshes);
 const field=meshes(s.out.root).find(m=>m.geometry.userData.bakeHeightfield);
 const before=(field.geometry.index?.count??field.geometry.attributes.position.count)/3;
 let transported=packed;
 if(cached){
  transported=structuredClone(packed);
  for(const g of transported.geometries)if(g.userData.bakeHeightfield){delete g.attributes.uv3;delete g.attributes.lmLightPage;}
 }
 const atlas=cached?applyAtlas(transported,s.out.root,layout):buildAtlas(s.out.root,plan,layout);
 assert.equal(atlas.key,tiers[0].key,'mounted provider key');
 assert.equal((field.geometry.index?.count??field.geometry.attributes.position.count)/3,before,'keep cheap Low terrain');
 assert.ok(triangles(meshes(s.out.root))<=beforeTotal,'no added Low receiving triangles');
 assert.equal(meshes(s.out.root).length,beforeMeshes.length,'no added Low receiving draws');
 // Verify actual chart bindings, including the graded Low heightfield. Every
 // addressed vertex uses the same page and UV as its canonical chart mapping.
 let fields=0,faces=0,fragmentFaces=0;
 for(const c of atlas.room.charts)for(const part of materialParts(c)){
  const g=part.mesh.geometry,p=g.attributes.position,uv=g.attributes.uv3,page=g.attributes.lmLightPage;
  for(const f of part.faces){
   const points=tier==='low'&&!c.heightfield?[0,1,2].map(k=>new THREE.Vector3().fromBufferAttribute(p,f*3+k).applyMatrix4(part.mesh.matrixWorld)):null;
   const reference=points?referenceFor(c):null,refs=points?reference.faces.get(faceKey(points)):null;
   if(points&&!refs)fragmentFaces++;
   for(let k=0;k<3;k++){
   const i=f*3+k;assert.equal(page.getX(i),c.page);assert.ok(Number.isFinite(uv.getX(i))&&Number.isFinite(uv.getY(i)));faces++;
   if(c.heightfield){fields++;const [x0,y0,x1,y1]=c.field;
    const u=(c.rect.x+(p.getX(i)-x0)*c.density)/layout.room.page;
    const v=(c.rect.y+(-p.getZ(i)-y0)*c.density)/layout.room.page;
    assert.ok(Math.abs(uv.getX(i)-u)<1e-6);assert.ok(Math.abs(uv.getY(i)-v)<1e-6);}
   else if(points){const key=pointKey(points[k]),equal=expected=>expected&&Math.abs(uv.getX(i)-expected[0])<1e-6&&Math.abs(uv.getY(i)-expected[1])<1e-6;
    // Material territories can clip one canonical face into several drawn
    // faces. Compare their newly created vertices against that SAME source
    // chart's triangle at the same world position, never a neighbouring rect.
    const matches=refs?refs.some(ref=>equal(ref.get(key))):reference.triangles.some(({triangle,uv:sourceUv})=>{
     const bary=triangle.getBarycoord(points[k],new THREE.Vector3());
     if(!bary||Math.min(bary.x,bary.y,bary.z)<-1e-4||Math.abs(triangle.getPlane(new THREE.Plane()).distanceToPoint(points[k]))>2e-5)return false;
     return equal([0,1].map(axis=>bary.x*sourceUv[0][axis]+bary.y*sourceUv[1][axis]+bary.z*sourceUv[2][axis]));
    });
    assert.ok(matches,'Low UV must equal this source chart uv3 at the same faceKey position (chart '+c.id+')');}
   }
  }
 }
 assert.ok(fields>0&&faces>0,'actual Low receivers bound');
 const fieldPage=field.geometry.attributes.lmLightPage;
 let eligible=0,lit=0;const a=new THREE.Vector3(),b=a.clone(),c=a.clone(),n=a.clone();
 for(let f=0;f<field.geometry.attributes.position.count/3;f++){
  const p=field.geometry.attributes.position;a.fromBufferAttribute(p,f*3);b.fromBufferAttribute(p,f*3+1);c.fromBufferAttribute(p,f*3+2);
  n.copy(b).sub(a).cross(c.clone().sub(a));if(n.length()/2<1e-6||Math.abs(n.normalize().y)<.25)continue;
  eligible++;if(fieldPage.getX(f*3)>=0)lit++;
 }
 assert.equal(lit,eligible,'every receiving Low terrain face has a page');
 console.log('LOW_COST '+JSON.stringify({buildMs:s.ms,terrainTriangles:before,boundFaces:eligible,
  tier,cached,fragmentFaces,receiverTriangles:beforeTotal,receiverDraws:beforeMeshes.length,extraTriangles:triangles(meshes(s.out.root))-beforeTotal,extraDraws:meshes(s.out.root).length-beforeMeshes.length}));
 releaseBakeSource(s.out.root);disposeObject(s.out.root);
});
if(!input.owner)await test('nondefault_building_finish_provider_uses_the_same_topology',async()=>{
 for(const tier of ['low','high']){
  const s=await scene(tier,true,true);
  assert.equal(atlasJob(s.out.root,plan,layout).cacheKey,tiers[0].cacheKey);
  assert.equal(buildAtlas(s.out.root,plan,layout).key,tiers[0].key);
  releaseBakeSource(s.out.root);disposeObject(s.out.root);
 }
});
if(!input.owner)await test('editor_provider_keeps_physical_material_tier_and_the_high_key',async()=>{
 const {mountTwin}=await import(file('static/twin/twin_view.js'));
 const p=structuredClone(plan);p.site={};delete p.effect_fixtures;
 const k={materials:{siding:{asset:'tier-probe'}},manifest:{'tier-probe':{
  household:true,kind:'material',revision:1,params:{alpha_mode:'opaque'},maps:{}}}};
 const high=buildTwin(withoutSurfaceMaterials(p),{...k,manifest:{}},'high',{viewing:true,bakeSource:true});
 await high.ready;const expected=buildAtlas(high.root,p,layout).key;
 const shell=new Element();shell.className='editor-shell';const el=new Element();shell.appendChild(el);
 const fetch=globalThis.fetch;globalThis.Renderer.prototype.extensions={has:()=>false};let view;
 globalThis.fetch=async url=>String(url).includes('materials/manifest')?
  new Response(JSON.stringify({revision:1,entries:k.manifest})):new Response('{}',{status:404});
 try{
  view=await mountTwin(el,{plan:p,kit:k,tier:'low',bake:{poll:0,api:async()=>new Response('{}',{status:404})}});
  const root=view.scene.children.find(isBakeRoot);assert.ok(root,'mounted editor registered its bake provider');
  const physical=bakeReceiverRoots(root)[0];assert.notEqual(physical,root,'editor uses its detached physical house');
  const siding=[];physical.traverse(m=>{if(m.isMesh&&m.material?.userData.materialRole==='siding')siding.push(m.material);});
  assert.ok(siding.length,'physical materials are observable');
  for(const material of siding)assert.equal(JSON.parse(material.userData.materialKey)[3],'low','physical kit keeps the editor texture tier');
  assert.equal(buildAtlas(root,p,layout).key,expected,'twin_view neutral make() has the canonical High key');
 }finally{view?.dispose();globalThis.fetch=fetch;delete globalThis.Renderer.prototype.extensions;disposeObject(high.root);}
});
finish();
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner-export', type=Path)
    parser.add_argument('--baseline-main', action='store_true')
    parser.add_argument('--measure', action='store_true')
    parser.add_argument('--draw-cost', action='store_true')
    args = parser.parse_args()
    payload = {'root': ROOT.as_posix(), 'plan': None if args.owner_export else fixture(),
               'ownerExport': str(args.owner_export) if args.owner_export else None,
               'measure': args.measure,
               'drawCost': args.draw_cost, 'owner': bool(args.owner_export)}
    if args.baseline_main:
        files = ['bake/source.js', 'bake/bindings.js', 'twin_generator.js', 'twin_yard.js']
        payload['mainSources'] = {(ROOT / 'static/twin' / name).as_uri(): subprocess.check_output(
            ['git', 'show', f'9703861c:chauffeur/static/twin/{name}'], cwd=ROOT,
            encoding='utf-8') for name in files}
    if args.owner_export:
        # Keep the private flattened model in memory, even when TEMP is inside
        # the worktree. Only code and the export's path enter the Node job files.
        sys.path.insert(0, str(ROOT))
        from services.twin_model_bridge import flatten
        node = shutil.which('node')
        if not node:
            print('SKIP node is unavailable')
            return 0
        plan = flatten(json.loads(args.owner_export.read_text(encoding='utf-8'))['model'])
        with tempfile.TemporaryDirectory(prefix='twin_tier_key_') as directory:
            driver, job = Path(directory) / 'driver.mjs', Path(directory) / 'job.json'
            driver.write_text(DRIVER, encoding='utf-8')
            job.write_text(json.dumps(payload), encoding='utf-8')
            try:
                result = subprocess.run([node, str(driver), str(job)], input=json.dumps(plan),
                    capture_output=True, text=True, encoding='utf-8', timeout=300)
            except subprocess.TimeoutExpired as error:
                output = error.stdout or b''
                print(output.decode('utf-8', errors='replace') if isinstance(output, bytes) else output)
                raise
            code, output = result.returncode, result.stdout + result.stderr
    else:
        code, output = run_node(DRIVER, payload, timeout=300)
    print(output, end='')
    return code or 0


if __name__ == '__main__':
    sys.exit(main())
