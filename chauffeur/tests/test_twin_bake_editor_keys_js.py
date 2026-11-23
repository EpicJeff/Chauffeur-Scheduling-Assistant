"""Viewer compatibility, authored classification and committed-edit timings."""
import json
from pathlib import Path
import sys
from twin_editor_dom import run_node
import test_twin_bake_editor_source_js as S
import test_twin_baker_js as B

PREFIX = S.DRIVER[:S.DRIVER.index('const plan=input.plan')]
# Observe real synchronous generator work without replacing its implementation.
PREFIX = PREFIX.replace("if (url.endsWith('/twin_yard.js')) {", """if (url.endsWith('/twin_generator.js')) {
    const loaded=next(url,{...ctx,format:'module'}),source=String(loaded.source);
    return {...loaded,format:'module',source:source.replace('export function buildTwin(', 'function buildTwinImpl(')+
      '\\nexport function buildTwin(...args){const t=performance.now();const result=buildTwinImpl(...args);if(args[3]?.bakeSource)(globalThis.__bakeCosts ||= []).push({ms:performance.now()-t,neutral:!Object.keys(args[1].manifest||{}).length});return result;}'};
  }
  if (url.endsWith('/twin_yard.js')) {""")
VIEWER = PREFIX + r"""
const layout={room:{density:1,page:256,gutter:2}},keys=[];
for(const alpha of [false,true]){
 const kit=structuredClone(input.kit),plan=structuredClone(input.plan);
 if(alpha){kit.manifest['editor-alpha']={household:true,kind:'material',revision:1,params:{alpha_mode:'cutout'},maps:{}};
  plan.buildings.find(b=>b.walls?.length).walls[0].faces={left:{id:'editor-alpha'},right:{id:'editor-alpha'}};}
 const v=await mountTwin(host(false),{plan,kit,tier:'high',bake:true});
 try{await test('4_viewer_key_'+(alpha?'cutout':'household'),()=>{
  const root=v.scene.children.find(isBakeRoot),job=atlasJob(root,v.plan,layout),atlas=buildAtlas(root,v.plan,layout);
  keys.push({input:job.cacheKey,key:atlas.key,charts:atlas.room.charts.length});
 });}finally{v.dispose();}
}
console.log('KEYS '+JSON.stringify(keys));finish();
"""
EDITOR = PREFIX + r"""
const layout={room:{density:1,page:256,gutter:2}},kit=structuredClone(input.kit),plan=structuredClone(input.plan);
kit.manifest['editor-alpha']={household:true,kind:'material',revision:1,params:{alpha_mode:'cutout'},maps:{}};
const building=plan.buildings.find(b=>b.walls?.length),wall=building.walls[0];
wall.faces={left:{id:'editor-alpha'},right:{id:'editor-alpha'}};
let parentChecks=0;
// Authorize the High parent desk; hold live transport so only the measured
// source call performs geometry work. No bake is requested by this benchmark.
const parentBake={host:new Element(),api:async(path,init)=>{
 if(path.endsWith('/lease')){assert.equal(JSON.parse(init.body).action,'check');parentChecks++;return new Response('{"free":true}');}
 return new Promise(()=>{});
}};
const editor=await mountTwin(host(true),{plan,kit,tier:'high',bake:parentBake});
const viewer=await mountTwin(host(false),{plan:structuredClone(plan),kit,tier:'high',bake:true});
try{
 await test('5_focused_faint_and_room_selected_use_authored_alpha',async()=>{
  const baseline=buildAtlas(viewer.scene.children.find(isBakeRoot),viewer.plan,layout).key;
  const level=building.id+':'+building.levels[0].id,room=building.rooms[0];
  for(const state of ['focus','faint','room']){
   await editor.rebuild(structuredClone(plan));
   if(state==='focus')await editor.setEditableLevel(level);
   if(state==='faint')editor.showLevels(Object.keys(editor.groups.levels),{faint:[level]});
   if(state==='room')editor.setSelection({selected:null,members:[],room:{building:building.id,level:room.level,id:room.id,allowed:[room.id],walls:[]}});
   while(!editor.ready)await new Promise(setImmediate);
   // A further presentation-only material swap must not classify opaque faces
   // as authored cutouts, even outside the two old selected/faded maps.
   const root=editor.scene.children.find(isBakeRoot);
   root.traverse(m=>{if(m.isMesh&&m.userData.merged){m.material=m.material.clone();m.material.transparent=true;m.material.alphaTest=.5;}});
   assert.equal(buildAtlas(root,editor.plan,layout).key,baseline,state);
  }
 });
}finally{editor.dispose();viewer.dispose();}
finish();
"""

if __name__ == '__main__':
    B.household_pool_house()
    plan=B.twin_store.current()
    kit=json.loads((S.ROOT/'twin_kits/modern_farmhouse.json').read_text(encoding='utf8'));kit['manifest']={}
    data={'root':S.ROOT.as_posix(),'plan':plan,'kit':kit}
    results=[]
    for root in [S.ROOT,Path('E:/repositories/Chauffeur/chauffeur')]:
        code,out=run_node(VIEWER,{**data,'root':root.as_posix()},timeout=480)
        print(str(root)+'\n'+out)
        if code:sys.exit(code)
        results.append(json.loads(next(line[5:] for line in out.splitlines() if line.startswith('KEYS '))))
    # Chart counts must match main. Keys must match too unless this tree
    # deliberately migrated the atlas (a different ATLAS_VERSION), in which
    # case they must differ: an unchanged key would mean the bump never landed.
    import re
    version=lambda root:re.search(r"ATLAS_VERSION\s*=\s*'([^']+)'",(Path(root)/'static/twin/bake/key_inputs.js').read_text(encoding='utf8')).group(1)
    migrated=version(S.ROOT)!=version('E:/repositories/Chauffeur/chauffeur')
    assert [r['charts'] for r in results[0]]==[r['charts'] for r in results[1]],f'Viewer chart count regression against read-only main: {results}'
    for ours,theirs in zip(results[0],results[1]):
        same=(ours['key'],ours['input'])==(theirs['key'],theirs['input'])
        assert same!=migrated,f'Viewer keys {"unchanged despite" if migrated else "changed without"} an ATLAS_VERSION migration: {results}'
    print('  ok 4 viewer chart counts unchanged against read-only main; keys '+('migrated' if migrated else 'unchanged'))
    code,out=run_node(EDITOR,data,timeout=480);print(out);sys.exit(code or 0)
