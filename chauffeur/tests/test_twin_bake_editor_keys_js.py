"""Viewer compatibility, authored classification and committed-edit timings."""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from twin_editor_dom import run_node
import test_twin_bake_editor_source_js as S
import test_twin_baker_js as B

BASELINE = 'a57eb1b3'

PREFIX = S.DRIVER[:S.DRIVER.index('const plan=input.plan')]
# Observe real synchronous generator work without replacing its implementation.
PREFIX = PREFIX.replace("if (url.endsWith('/twin_yard.js')) {", """if (url.endsWith('/twin_generator.js')) {
    const loaded=next(url,{...ctx,format:'module'}),source=String(loaded.source);
    return {...loaded,format:'module',source:source.replace('export function buildTwin(', 'function buildTwinImpl(')+
      '\\nexport function buildTwin(...args){const t=performance.now();const result=buildTwinImpl(...args);if(args[3]?.bakeSource)(globalThis.__bakeCosts ||= []).push({ms:performance.now()-t,neutral:!Object.keys(args[1].manifest||{}).length});return result;}'};
  }
  if (url.endsWith('/twin_yard.js')) {""")
# Load the complete pinned twin runtime in memory; no mutable-main checkout.
PREFIX = PREFIX.replace("}, load(url, ctx, next) {", """}, load(url, ctx, next) {
  if(input.baseline && url.startsWith(file('static/twin/')) && url.endsWith('.js')) {
    const relative='static/twin/'+decodeURIComponent(url.slice(file('static/twin/').length));
    assert.ok(Object.hasOwn(input.sources,relative),'pinned JS source is present: '+relative);
    globalThis.__gitShowModules=(globalThis.__gitShowModules||0)+1;
    return {format:'module',shortCircuit:true,source:input.sources[relative]};
  }
""")
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
if(input.baseline){assert.ok(globalThis.__gitShowModules>0,'pinned JS loader must actually run');console.log('GITSHOW_MODULES '+globalThis.__gitShowModules);}
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
   if(state==='focus')editor.setSelection({selected:{kind:'level',id:building.levels[0].id,building:building.id},room:{kind:'level',id:building.levels[0].id,building:building.id,level:building.levels[0].id,allowed:[],walls:[]}});
   if(state==='faint')editor.showLevels(Object.keys(editor.groups.levels),{faint:[level]});
   if(state==='room')editor.setSelection({selected:null,members:[],room:{building:building.id,level:room.level,id:room.id,allowed:[room.id],walls:[]}});
   while(!editor.ready)await new Promise(setImmediate);
   // A further presentation-only material swap must not classify opaque faces
   // as authored cutouts, even outside the two old selected/faded maps.
   const root=editor.scene.children.find(isBakeRoot);
   root.traverse(m=>{if(m.isMesh&&m.userData.merged){m.material=[].concat(m.material).map(source=>{const material=source.clone();material.transparent=true;material.alphaTest=.5;return material;});}});
   assert.equal(buildAtlas(root,editor.plan,layout).key,baseline,state);
  }
 });
}finally{editor.dispose();viewer.dispose();}
finish();
"""

OLD_NORMALIZE = r"""
import importlib.abc,importlib.util,json,os,subprocess,sys,tempfile
from pathlib import Path
os.environ['CHAUFFEUR_DATA_DIR']=tempfile.mkdtemp(prefix='keys_old_a57_')
class OldSource(importlib.abc.MetaPathFinder,importlib.abc.Loader):
 def find_spec(self,name,path=None,target=None):
  if not name.startswith('services.'):return None
  source_path='chauffeur/'+name.replace('.','/')+'.py'
  loaded=subprocess.run(['git','show',sys.argv[1]+':'+source_path],capture_output=True,text=True,encoding='utf8')
  if loaded.returncode:return None
  spec=importlib.util.spec_from_loader(name,self,origin=source_path)
  spec.loader_state=loaded.stdout;return spec
 def create_module(self,spec):return None
 def exec_module(self,module):
  module.__file__=str(Path.cwd().parent/module.__spec__.origin)
  exec(compile(module.__spec__.loader_state,module.__file__,'exec'),module.__dict__)
sys.meta_path.insert(0,OldSource())
raw=json.load(sys.stdin)
if sys.argv[2]=='assembled':
 from services import twin_store
 twin_store.push_round(raw,'build')
 print(json.dumps(twin_store.current()))
else:
 from services.twin_plan import normalize
 print(json.dumps(normalize(raw)[0]))
"""


def old_plan(raw, assembled=False):
    old = subprocess.run([sys.executable, '-c', OLD_NORMALIZE, BASELINE,
                          'assembled' if assembled else 'normalized'], cwd=S.ROOT,
                         input=json.dumps(raw), capture_output=True, text=True, encoding='utf8', check=True)
    return json.loads(old.stdout)


def old_js_sources():
    """Read pinned blobs in Python; sandboxed Node cannot spawn git."""
    tree=subprocess.check_output(['git','ls-tree','-r','-l','-z',BASELINE,'--','chauffeur/static/twin'],cwd=S.ROOT.parent)
    items=[]
    for entry in tree.split(b'\0'):
        if not entry:continue
        metadata,path=entry.split(b'\t',1)
        if path.endswith(b'.js'):items.append((path.decode('utf8'),int(metadata.split()[-1])))
    assert items,'pinned JS tree must not be empty'
    sources={}
    for offset in range(0,len(items),48):
        batch=items[offset:offset+48]
        payload=subprocess.check_output(['git','show',*[BASELINE+':'+path for path,_ in batch]],cwd=S.ROOT)
        assert len(payload)==sum(size for _,size in batch),'git-show blob framing'
        start=0
        for path,size in batch:
            sources[path.removeprefix('chauffeur/')]=payload[start:start+size].decode('utf8')
            start+=size
    required={'static/twin/twin_view.js','static/twin/twin_generator.js',
              'static/twin/bake/atlas.js','static/twin/bake/source.js',
              'static/twin/bake/atlas_transport.js'}
    assert required <= sources.keys(),('missing pinned JS roots',required-sources.keys())
    print('GITSHOW_SOURCES '+str(len(sources)))
    return sources


def no_attachment_plans(raw):
    raw = copy.deepcopy(raw)
    removed = []
    for building in raw['buildings']:
        roof = building.get('roof') or {}
        removed.extend((building['id'], e['id'], e['kind']) for e in roof.get('extensions', [])
                       if e.get('kind') in ('awning', 'shed_continuation'))
        roof['extensions'] = [e for e in roof.get('extensions', [])
                              if e.get('kind') not in ('awning', 'shed_continuation')]
    # This household has two awnings and no continuation. Keep the exact input
    # identity evidence separate from its deliberately changed atlas ownership.
    assert len(removed) == 2 and all(e[2] == 'awning' for e in removed), removed
    print('ATTACHMENTS '+json.dumps({'counts': {'awning': 2, 'shed_continuation': 0},
          'ids': removed, 'sha256': hashlib.sha256(json.dumps(sorted(removed), separators=(',', ':')).encode()).hexdigest()}))
    from services.twin_plan import normalize
    current = normalize(raw)[0]
    return current, old_plan(raw), removed

if __name__ == '__main__':
    B.household_pool_house()
    plan=B.twin_store.current()
    kit=json.loads((S.ROOT/'twin_kits/modern_farmhouse.json').read_text(encoding='utf8'));kit['manifest']={}
    data={'root':S.ROOT.as_posix(),'plan':plan,'kit':kit}
    # Keep the full migrated-house viewer and authored presentation checks.
    raw=json.loads(Path(B.HOUSEHOLD).read_text(encoding='utf8'))
    current,old,removed=no_attachment_plans(raw)
    sources=old_js_sources()
    for bid,rid,_ in removed:
        building=next(b for b in plan['buildings'] if b['id']==bid)
        assert not any(e.get('kind') in ('awning','shed_continuation') for e in building['roof'].get('extensions',[]))
        sections=[s for s in building['roof']['sections'] if (s.get('roof') or s.get('id'))==rid]
        assert sections and all(s.get('support',{}).get('kind')=='bracket' for s in sections), (rid,sections)
    code,out=run_node(VIEWER,data,timeout=480);print('FULL MIGRATED HOUSE\n'+out)
    if code:sys.exit(code)
    full_current=json.loads(next(line[5:] for line in out.splitlines() if line.startswith('KEYS ')))
    code,out=run_node(VIEWER,{**data,'plan':old_plan(raw,assembled=True),'baseline':BASELINE,'sources':sources},timeout=480)
    print('FULL GIT-SHOW '+BASELINE+' HOUSE\n'+out)
    if code:sys.exit(code)
    full_old=json.loads(next(line[5:] for line in out.splitlines() if line.startswith('KEYS ')))
    assert [r['charts'] for r in full_current]==[r['charts'] for r in full_old],f'Full household chart counts changed against {BASELINE}: {full_current}, {full_old}'
    print('  ok full household chart counts unchanged against git-show '+BASELINE)
    results=[]
    for label,fixture,baseline in [('current',current,None),('git-show '+BASELINE,old,BASELINE)]:
        code,out=run_node(VIEWER,{**data,'plan':fixture,'baseline':baseline,**({'sources':sources} if baseline else {})},timeout=480)
        print(label+' NO ATTACHMENTS\n'+out)
        if code:sys.exit(code)
        results.append(json.loads(next(line[5:] for line in out.splitlines() if line.startswith('KEYS '))))
    # Without attachments, chart counts and keys retain the pinned runtime's
    # exact compatibility promise. Keys must match unless this tree
    # deliberately migrated the atlas (a different ATLAS_VERSION), in which
    # case they must differ: an unchanged key would mean the bump never landed.
    version=lambda root:re.search(r"ATLAS_VERSION\s*=\s*'([^']+)'",(Path(root)/'static/twin/bake/key_inputs.js').read_text(encoding='utf8')).group(1)
    old_version=re.search(r"ATLAS_VERSION\s*=\s*'([^']+)'",subprocess.check_output(['git','show',BASELINE+':chauffeur/static/twin/bake/key_inputs.js'],cwd=S.ROOT,encoding='utf8')).group(1)
    migrated=version(S.ROOT)!=old_version
    assert [r['charts'] for r in results[0]]==[r['charts'] for r in results[1]],f'No-attachment viewer chart count regression against {BASELINE}: {results}'
    for ours,theirs in zip(results[0],results[1]):
        same=(ours['key'],ours['input'])==(theirs['key'],theirs['input'])
        assert same!=migrated,f'Viewer keys {"unchanged despite" if migrated else "changed without"} an ATLAS_VERSION migration: {results}'
    print('  ok 4 no-attachment viewer chart counts unchanged against git-show '+BASELINE+'; keys '+('migrated' if migrated else 'unchanged'))
    code,out=run_node(EDITOR,data,timeout=480);print(out);sys.exit(code or 0)
