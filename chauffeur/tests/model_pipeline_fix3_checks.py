"""Round-3 copy disposal regression, included in the pipeline gate."""
from model_pipeline_fix1_checks import DRIVER as FIX1_DRIVER
import twin_live_node_rig as rig
from twin_live_node_rig import run


# A static invalid host currently falls back to the first level. Simulate that
# fallback no longer resolving for one fixture host, exercising the actual
# !level rejection body without changing normal production host semantics.
DRIVER = FIX1_DRIVER.split("await check('A_program_keys")[0].replace(
    "bundle.indexOf('function WebGLPrograms(')",
    "bundle.indexOf('function isPackedRGFormat(')"
).replace(
    "source:r.source.toString()+'",
    """source:r.source.toString().replace(
     'export function disposeObject(root, { keepMaterials = new Set() } = {}) {',
     'export function disposeObject(root, { keepMaterials = new Set() } = {}) { globalThis.__disposedCopies?.push(root);')+'"""
).replace(
    " if(url.endsWith('/twin_yard.js?baseline'))",
    """ if(url.endsWith('/static/twin/twin_generator.js')){
  const r=next(url,{...ctx,format:'module'}),source=r.source.toString();
  const fallback='return levels[surface?.level] || first;';
  assert.equal(source.split(fallback).length,2,'one host-level fallback hook');
  return {...r,format:'module',source:source.replace(fallback,
   "return surface?.level === 'missing-level' ? undefined : levels[surface?.level] || first;")};
 }
 if(url.endsWith('/twin_yard.js?baseline'))"""
) + r'''
await check('R3_1_lone_copy_keeps_scene_slot_and_warm_program',async()=>{
 const r=fresh({parts_version:1,parts:[{key:'Wood',has_uv:false}],materials:{Wood:{material:'oak'}}});
 lib.rememberImport(r);
 const kit={manifest:{oak:{household:true,kind:'material',params:{tint:'#884422'}}},materials:{}};
 // Build the still-rendering house first, with oak on a real floor surface.
 const p=planFor(r.id);p.materials.floor={id:'oak'};p.buildings[0].items=[];
 serveFiles();const house=buildTwin(p,kit,'high');await house.ready;
 const slot=meshes(house.root).find(m=>m.material.userData.materialId==='oak')?.material;
 assert.ok(slot,'the house draws the scene slot material');
 const map=new THREE.Texture(),normalMap=new THREE.Texture();slot.map=map;slot.normalMap=normalMap;
 const events={material:0,map:0,normalMap:0};
 slot.addEventListener('dispose',()=>events.material++);
 map.addEventListener('dispose',()=>events.map++);normalMap.addEventListener('dispose',()=>events.normalMap++);

 // Use r187's actual key, acquire and release implementation. Substitute only
 // the GL program constructor; material disposal releases its cached references
 // as WebGLRenderer does, so equal keys alone cannot hide a destroyed program.
 let compiled=0,destroyed=0;
 class Program {constructor(renderer,key){this.cacheKey=key;this.usedTimes=1;compiled++;}destroy(){destroyed++;}}
 const Factory=Function('THREE','WebGLProgram',`const {${Object.keys(THREE).filter(k=>/^[A-Za-z_$][\w$]*$/.test(k)).join(',')}}=THREE;class WebGLShaderCache{};${programSource};return WebGLPrograms;`)(THREE,Program);
 const cache=Factory(renderer,{get:()=>null},{has:()=>false},{precision:'highp',logarithmicDepthBuffer:false,getMaxPrecision:x=>x},{},{numPlanes:0,numIntersection:0});
 const owned=new Map(),scene=new THREE.Scene();
 function render(root){for(const mesh of meshes(root)){
  const material=mesh.material,params=cache.getParameters(material,lights,[],scene,mesh,[]),key=cache.getProgramCacheKey(params);
  if(!owned.has(material)){
   const refs=new Map();owned.set(material,refs);
   material.addEventListener('dispose',()=>{for(const program of refs.values())cache.releaseProgram(program);owned.delete(material);});
  }
  const refs=owned.get(material);if(!refs.has(key))refs.set(key,cache.acquireProgram(params,key));
 }}
 render(house.root);const warm=compiled,warmKeys=keys(house.root);
 const warmProgram=owned.get(slot).values().next().value;
 assert.ok(warmProgram);

 // The rejected item gets the very same slot via record-level defaults in
 // loadModel. Delay decode so the first render precedes the lone-copy disposal.
 let release;const gate=new Promise(resolve=>{release=resolve;});let fetched=false;
 serveFiles();const fetchModel=globalThis.fetch;
 globalThis.fetch=async(...args)=>{fetched=true;await gate;return fetchModel(...args);};
 const q=planFor(r.id);
 // hostPoint still resolves the room polygon. Its hostLevel surface names a
 // missing level, so only the loader hook suppresses the first-level fallback.
 q.buildings[0].rooms=[{id:'missing-room',level:'missing-level',polygon:[[0,0],[1,0],[1,1],[0,1]]}];
 q.buildings[0].items[0].host={floor:'missing-room',u:.5,v:.5};
 const rejected=buildTwin(q,kit,'high',{reuseMaterials:house.materials});
 assert.equal(rejected.materials.get('floor'),slot,'the same scene cache is retained');
 globalThis.__disposedCopies=[];release();await rejected.ready;
 assert.ok(fetched,'the rejected source was actually loaded');
 assert.equal(__disposedCopies.length,1,'the lone rejected copy reached disposeObject');
 assert.ok(__disposedCopies[0].userData.disposed,'the copy was actually disposed');
 assert.equal(meshes(__disposedCopies[0])[0].material,slot,'record override borrowed the scene slot');
 assert.ok(!(rejected.pieces.get('b:chair') || []).some(m=>m.geometry?.userData.partKey==='Wood'),
  'the rejected model was not attached (its old pick proxy can remain)');
 assert.ok(!house.root.userData.disposed,'the house remains alive');
 const beforeSecond=compiled;render(house.root);
 // Check both lifetime and cache evidence even if one of them regresses.
 assert.deepEqual({events,compiled,destroyed},{events:{material:0,map:0,normalMap:0},compiled:warm,destroyed:0},
  'lone-copy disposal must retain scene materials/textures and compile no replacement program');
 assert.equal(compiled,beforeSecond,'second render compiles no new program');
 assert.equal(owned.get(slot).values().next().value,warmProgram,'the warmed program reference survives');
 assert.deepEqual(keys(house.root),warmKeys,'house keeps exactly the same r187 program keys');
 assert.ok(meshes(house.root).some(m=>m.material===slot),'house still draws with the exact slot instance');
 console.log('R3 lifetime: zero material/texture disposals, zero replacement compiles, warmed program retained');
});
assert.deepEqual(escaped,[]);assert.deepEqual(domErrors,[]);
if(failures.length)throw new Error('Fix-round-3 failures: '+failures.join(', '));
'''


def run_checks():
    # live.js imports the builders during PRELUDE; hooks must precede it.
    hooks, driver = DRIVER.split('globalThis.ProgressEvent', 1)
    hooks = hooks.replace("+'\\nexport const __cacheForTest=modelCache;'", '')
    previous = rig.PRELUDE
    rig.PRELUDE = previous.replace('const liveModule = await import', hooks + '\nconst liveModule = await import')
    try:
        return run('globalThis.ProgressEvent' + driver, {}, prefix='.pipeline_fix3_', timeout=180)
    finally:
        rig.PRELUDE = previous


if __name__ == '__main__':
    import sys
    sys.exit(run_checks())
