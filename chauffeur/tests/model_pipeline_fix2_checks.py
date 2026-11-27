"""Round-2 runtime regressions, included in the pipeline gate."""
import subprocess
from pathlib import Path

from model_pipeline_fix1_checks import DRIVER as FIX1_DRIVER
from twin_live_node_rig import run

DRIVER = FIX1_DRIVER.split('// Use r187')[0].replace(
    " if(url.endsWith('/twin_yard.js?baseline'))",
    " if(url.endsWith('/twin_generator.js?baseline'))return {format:'module',source:config.mainGenerator,shortCircuit:true};\n if(url.endsWith('/twin_yard.js?baseline'))") + r'''
const mainDispose=Function(config.mainDispose.replace('export function','return function'))();
await check('R2_1_full_edit_keeps_far_independent_and_aligned',async()=>{
 const original=makeSource(),files={};let current=fresh({lod_percent:[80,25,5],fix:{height_m:4}});
 const upload=async(fs,p,s,d)=>{
  // Simulate trimmed extremes, retaining an authored vertex in every level.
  const parsed=await new GLTFLoader().parseAsync(await fs[0].arrayBuffer(),'');
  if(d.lod!=='lod1.glb')meshes(parsed.scene)[0].geometry.attributes.position.setX(1,d.lod==='lod0.glb'?3:2);
  files[d.lod]=await new GLTFExporter().parseAsync(parsed.scene,{binary:true});
  const revision=(current.lods.find(l=>l.name===d.lod)?.revision||0)+1;
  current={...current,revision:current.revision+1,files:{...current.files,[d.lod]:true},lods:[...current.lods.filter(l=>l.name!==d.lod),{name:d.lod,percent:d.percent,revision}]};return current;
 };
 await levels.buildLevels(current,original,{patch:async c=>(current={...current,...c,revision:1}),upload});
 assert.deepEqual(levels.pendingLevels(current),[],'start with all levels generated');
 current={...current,revision:current.revision+1,lod_percent:[60,25,5],lods:current.lods.filter(l=>l.name!=='lod0.glb')};
 const uploaded=[];await levels.buildLevels(current,original,{upload:async(...args)=>{uploaded.push(args[3].lod);return upload(...args);}});
 assert.deepEqual(uploaded,['lod0.glb'],'authored anchors do not invalidate mid/far');
 const urls=[];serveFiles(files,u=>urls.push(u));
 const low=await lib.loadModel(current.id,{},undefined,{tier:'low'});
 assert.ok(low);assert.ok(urls.length>0);
 assert.ok(urls.every(u=>u.includes('lod2.glb')),'Low fetches neither original nor Full after a Full edit: '+urls);
 const full=await lib.loadModel(current.id,{},undefined,{editor:true});
 const box=o=>new THREE.Box3().setFromObject(o);
 assert.ok(Math.abs(box(low).min.x-box(full).min.x)<1e-6,'B11b: the common authored extreme keeps its world position');
 assert.ok(Math.abs(box(low).min.y-box(full).min.y)<1e-6);
 assert.equal(low.userData.modelSize[0],6,'fix sizing also uses the stable authored bounds');
});
await check('R2_2_scene_slot_disposal_matches_main',async()=>{
 const r=fresh({parts_version:1,parts:[{key:'Wood',has_uv:false}],materials:{Wood:{material:'oak'}}});lib.rememberImport(r);serveFiles();
 const kit=revision=>({manifest:{oak:{household:true,kind:'material',revision,params:{tint:revision===1?'#884422':'#226644'}}},materials:{}});
 const plan={units:'ft',materials:{},buildings:[],site:{furniture:[{id:'chair',asset:r.id,at:[0,0]}]}};
 const before=await buildYard(plan,kit(1),'low',{viewing:true});
 const reference=await buildYard(plan,kit(1),'low',{viewing:true});
 const after=await buildYard(plan,kit(2),'low',{viewing:true});
 const retire=(root,dispose,keep)=>{
  const material=meshes(root).find(m=>m.material.userData.materialId==='oak').material;
  const texture=new THREE.Texture();material.map=texture;let materials=0,textures=0;
  material.addEventListener('dispose',()=>materials++);texture.addEventListener('dispose',()=>textures++);
  dispose(root,{keepMaterials:keep});return {materials,textures};
 };
 const keep=new Set(after.group.userData.materials.values());
 const expected=retire(reference.group,mainDispose,keep);assert.deepEqual(expected,{materials:1,textures:1});
 assert.deepEqual(retire(before.group,lib.disposeObject,keep),expected,'retired yard slots retain main lifetime');
 // The building release path uses the same disposal helper and retained set.
 const building=buildTwin(planFor(r.id),kit(1),'high');await building.ready;
 const next=buildTwin(planFor(r.id),kit(2),'high',{reuseMaterials:building.materials});await next.ready;
 assert.deepEqual(retire(building.root,lib.disposeObject,new Set(next.materials.values())),expected,'retired building slots retain main lifetime');
 const preview=await lib.loadModel(r.id,kit(1),undefined,{editor:true});let disposed=0;
 meshes(preview)[0].material.addEventListener('dispose',()=>disposed++);lib.disposeObject(preview);
 assert.equal(disposed,0,'standalone per-kit cache still owns its shared materials');
});
await check('R2_3_untouched_uv_offsets_are_byte_identical_to_main',async()=>{
 const baseline=await import(file('static/twin/twin_generator.js')+'?baseline');
 const authored=new THREE.Mesh(new THREE.BoxGeometry(2,1,1),new THREE.MeshStandardMaterial({name:'floor'}));
 authored.material.userData.randomOffset=true;
 const bytes=await new GLTFExporter().parseAsync(authored,{binary:true});
 serveFiles({'original.glb':bytes});
 const uvBytes=built=>Buffer.concat(built.pieces.get('b:chair').map(m=>{
  const uv=m.geometry.attributes.uv;assert.ok(uv);return Buffer.from(uv.array.buffer,uv.array.byteOffset,uv.array.byteLength);
 }));
 for(const uv of [null,{u:.25,v:.75,rot:90}]){
  // Independent decodes: BufferGeometry.clone shares userData. Running both
  // builders on one cached source would share uvOffsetSeed between the runs.
  const oldRecord=fresh(),nowRecord=fresh();lib.rememberImport(oldRecord);lib.rememberImport(nowRecord);
  const p=planFor(oldRecord.id),q=planFor(nowRecord.id);if(uv)p.materials.floor=q.materials.floor={uv};
  const old=baseline.buildTwin(p,{},'high');const now=buildTwin(q,{},'high');await Promise.all([old.ready,now.ready]);
  assert.deepEqual(uvBytes(now),uvBytes(old),uv?'explicit surface UVs match pinned main':'random UV offsets match pinned main');
 }
 const r=fresh();lib.rememberImport(r);
 const p=planFor(r.id),q=planFor(r.id);p.materials.floor={uv:{u:.25,v:.75,rot:90}};
 p.buildings[0].items[0].model_materials=q.buildings[0].items[0].model_materials={floor:{material:'oak',texture:'model',tiles:2}};
 const kit={manifest:{oak:{household:true,kind:'material',params:{tile_ft:[2,3]}}},materials:{}};
 const a=buildTwin(p,kit,'high'),b=buildTwin(q,kit,'high');await Promise.all([a.ready,b.ready]);
 assert.deepEqual(uvBytes(a),uvBytes(b),'resolved overrides skip structural offsets');
});
await check('R2_4_car_compensates_only_the_validated_turn',async()=>{
 const {fixTurnRadians}=await import(file('static/twin/model_parts.js'));
 const r=fresh({fix:{turn:45}});lib.rememberImport(r);serveFiles();
 const model=await lib.loadModel(r.id,{},undefined,{editor:true});
 const applied=fixTurnRadians(r.fix),before=model.rotation.y;
 const car=placeCarModel(model,{at:[0,0,0],rotation:37,width:9,depth:18});car.updateMatrixWorld(true);
 assert.equal(car.userData.modelTurn,applied,'wrapper uses the exact turn applied by loadModel');
 assert.equal(model.rotation.y,before-applied,'no raw-turn counter rotation');
 assert.ok(Math.abs(car.rotation.y-(37*Math.PI/180+applied))<1e-8);
 const direction=new THREE.Vector3(0,0,1).transformDirection(model.matrixWorld);
 assert.ok(Math.abs(direction.x-Math.sin(37*Math.PI/180+applied))<1e-6,'world direction includes the fix exactly once');
});
assert.deepEqual(escaped,[]);assert.deepEqual(domErrors,[]);
if(failures.length)throw new Error('Fix-round-2 failures: '+failures.join(', '));
'''


def run_checks(only=None):
    app = Path(__file__).resolve().parents[1]

    def main_source(name):
        return subprocess.run(['git', 'show', '02a6f0aeb16ada1b1c0866f2664a57d60c92b78c:chauffeur/static/twin/' + name],
                              cwd=app, capture_output=True, text=True, encoding='utf-8', check=True).stdout

    main_library = main_source('twin_library.js')
    return run(DRIVER, {'mainGenerator': main_source('twin_generator.js'),
                       'mainDispose': main_library[main_library.index('export function disposeObject('):],
                       'only': only}, prefix='.pipeline_fix2_', timeout=180)


if __name__ == '__main__':
    import sys
    sys.exit(run_checks(sys.argv[1] if len(sys.argv) > 1 else None))
