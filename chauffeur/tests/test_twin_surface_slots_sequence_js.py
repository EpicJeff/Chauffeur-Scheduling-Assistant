"""Real household save/replace/UV/bulk paths in the mounted runtime; no browser."""
import ast
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_twin_surface_slots_live as S
from test_twin_tree_once_js import PREFIX
from services import twin_edit, twin_materials, twin_store
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
SETUP = PREFIX + r"""
const THREE=await import('three');
// Images cannot change receiving topology; deliver them without network I/O.
THREE.TextureLoader.prototype.load=function(url,done){const t=new THREE.Texture();queueMicrotask(()=>done?.(t));return t;};
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
const {bakeLayout}=await import(file('static/twin/bake/baker.js'));
window.chfBase=file('');location.search='?test=1';
const host=new Element(),shell=new Element();shell.className='editor-shell';shell.append(host);
const view=await mountTwin(host,{plan:structuredClone(input.plan),kit:input.kit,tier:'low',bake:false});
window.__twin=view;
assert.ok(view.ready);assert.ok(!view.bake);
"""

# Execute the browser test's actual observations and target selection against
# real Three meshes in the mounted view. Only renderer/image delivery are fake.
tree = ast.parse(Path(S.__file__).read_text(encoding='utf-8'))
bulk = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_bulk_targets')
bulk_expression = next(n.value.args[0].value for n in bulk.body if isinstance(n, ast.Return))
CHOOSE = SETUP + '\nconst records=await (' + S.SURFACE_RECORDS + ')({});\nconst drawnRoofs={};\n' + (
    'for(const b of view.plan.buildings)drawnRoofs[b.id]=await (' + S.ROOF_GROUPS + ')(b.id);\n') + (
    'const targets=await (' + bulk_expression + ')({records,drawnRoofs});\n') + r"""
console.log('TARGETS '+JSON.stringify(targets));view.dispose();process.exit(0);
"""

DRIVER = SETUP + r"""
const {releaseBakeSource}=await import(file('static/twin/bake/source.js'));
const {materialParts}=await import(file('static/twin/bake/bindings.js'));
const {authoredGeometry}=await import(file('static/twin/bake/geometry_key.js'));
const differences=(a,b,path='')=>{
 if(JSON.stringify(a)===JSON.stringify(b))return [];
 if(a&&b&&typeof a==='object'&&typeof b==='object')return [...new Set([...Object.keys(a),...Object.keys(b)])].flatMap(k=>differences(a[k],b[k],path+'/'+k));
 return [[path,a,b]];
};
for(const stage of input.stages){
 const diff=differences(JSON.parse(authoredGeometry(input.plan)),JSON.parse(authoredGeometry(stage.plan)));
 assert.deepEqual(diff,[],stage.name+' authored geometry unchanged: '+JSON.stringify(diff.slice(0,20)));
}
const options={room:{density:1,page:1024,gutter:2}};
const build=async plan=>{const h=buildTwin(plan,input.kit,'low',{viewing:true});await h.ready;
 const y=await buildYard(plan,input.kit,'low',{viewing:true});h.root.add(y.group);h.root.updateMatrixWorld(true);
 return {h,atlas:buildAtlas(h.root,plan,options)};};
const layout=a=>({key:a.key,pages:a.room.pages,rooms:a.room.rooms,
 charts:a.room.charts.map(c=>[c.id,c.key,c.page,c.rect,c.room,c.density])});
const finishes=c=>JSON.stringify([...new Set(materialParts(c).map(({mesh})=>JSON.stringify([
 mesh.material.userData.materialId||mesh.material.userData.bakeMaterialId||null,
 mesh.material.userData.materialRevision??null,mesh.material.color?.toArray()])))].sort());
const lights=input.plan.buildings.flatMap(b=>b.rooms.filter(r=>r.polygon?.length).map(r=>({device:b.id+':'+r.id,
 building:b.id,level:r.level,room:r.id,at:[...([0,1].map(i=>r.polygon.reduce((s,p)=>s+p[i],0)/r.polygon.length)),
 (b.levels.find(l=>l.id===r.level)?.elevation||0)+5]})));
const built=await build(input.plan),packed=bakeLayout(built.atlas,options,lights);
const initial=layout(built.atlas);
await view.setEditableLevel(input.floor);
for(const stage of input.stages){
 // Replay each actual editor replacement, including the inherited U-field
 // save before Rotation and the original-house reset between scenarios.
 for(const plan of stage.replacements)await view.rebuild(structuredClone(plan));
 if(stage.name==='many')await view.setEditableLevel(null);
 const next=await build(stage.plan);
 assert.deepEqual(layout(next.atlas),initial,stage.name+' stable atlas and complete chart addresses');
 const repacked=bakeLayout(next.atlas,options,lights,packed.ownership,packed.entries);
 assert.equal(!!repacked.ownershipReset,false,stage.name+' accepts sticky history');
 const changed=new Set(next.atlas.room.charts.filter((c,i)=>finishes(c)!==finishes(built.atlas.room.charts[i])).map(c=>c.id));
 const dirty=lights.filter(l=>packed.entries[l.device]?.key!==repacked.entries[l.device]?.key).map(l=>l.device).sort();
 const expected=packed.lights.filter(l=>l.receivingCharts.some(id=>changed.has(id))).map(l=>l.device).sort();
 assert.deepEqual(dirty,expected,stage.name+' exact reaching-light invalidation');
 if(stage.name==='uv')assert.deepEqual(dirty,[],'UV invalidates no light');
 if(stage.name==='wall')assert.ok(dirty.length>0&&dirty.length<lights.length,'wall rebakes locally');
 if(stage.name==='many'){
   const drawn=new Set();view.scene.traverseVisible(o=>{
     if(!o.isMesh||o.layers.isEnabled(31)||!o.geometry.attributes.position.count)return;
     const mats=Array.isArray(o.material)?o.geometry.groups.filter(g=>g.count>0).map(g=>o.material[g.materialIndex]):[o.material];
     for(const m of mats)if(m?.visible)drawn.add(m.userData.materialId);});
   for(let i=0;i<40;i++)assert.ok(drawn.has(input.costIds[i]),'all 40 slots render: '+JSON.stringify(input.targets[i]));
 }
 if(stage.name==='ledge'){
   const records=await (RECORD_SURFACES)({id:input.feature,part:'interior'});
   assert.ok(records.length,'the household ledge has actual interior triangles');
   assert.ok(records.every(r=>r.material===input.selected),'the row operation reaches every ledge interior triangle');
 }
 console.log('PASS sequence '+stage.name+' charts='+next.atlas.room.charts.length+' changed='+changed.size+' dirty='+dirty.length);
 releaseBakeSource(next.h.root);next.h.effects?.dispose?.();next.h.root.traverse(o=>o.geometry?.dispose());next.h.root.clear();
}
for(const bad of [{...packed.ownership,charts:-1},{version:99},
 {version:1,charts:built.atlas.room.charts.length,lights:{broken:'!'}}]){
 const recovered=bakeLayout(built.atlas,options,lights,bad,packed.entries);
 assert.equal(recovered.ownershipReset,true);
 assert.deepEqual(recovered.ownership,bakeLayout(built.atlas,options,lights).ownership);
}
view.dispose();console.log('PASS household mounted runtime and ownership recovery');process.exit(0);
"""


def main():
    assets = S._seed(many=True, feature=True)
    plan = twin_store.current()
    seed_round = twin_store.current_id()
    assert any(f['kind'] == 'ledge' for f in plan['site']['pool']['features']), 'Live ledge seed must survive normalization'
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = twin_materials.page_manifest()
    payload = {'root': ROOT.as_posix(), 'plan': plan, 'kit': kit}
    code, output = run_node(CHOOSE, payload, timeout=300)
    print(output, flush=True)
    assert code == 0, output
    targets = json.loads(next(line[8:] for line in output.splitlines() if line.startswith('TARGETS ')))
    assert len(targets) == 40
    b, w, room = S.L._target(plan)
    dx, dy = [v-u for u, v in zip(w['from'], w['to'])]
    centre = [sum(p[i] for p in room['polygon'])/len(room['polygon']) for i in (0, 1)]
    middle = [(u+v)/2 for u, v in zip(w['from'], w['to'])]
    side = 'right' if sum(n*(c-m) for n,c,m in zip([-dy, dx], centre, middle)) > 0 else 'left'
    stages = []

    def save(bid, target, material):
        twin_edit.save({'op': 'set_material', 'building': bid, 'target': target, 'material': material}, S.H.PARENT['id'])

    def remember(name, replacements=()):
        current = twin_store.current()
        for old, new in zip(plan['buildings'], current['buildings']):
            assert [(r['id'], r['polygon']) for r in old['rooms']] == [(r['id'], r['polygon']) for r in new['rooms']], name
        stages.append({'name': name, 'plan': current, 'replacements': [*replacements, current]})

    save(b['id'], {'wall': w['id'], 'side': side}, {'id': assets['selected']['id']})
    remember('wall')
    twin_store.revert(seed_round)
    save(b['id'], {'wall': w['id'], 'side': side}, {'uv': {'u': .25, 'v': 0, 'rot': 0}})
    u_plan = twin_store.current()
    save(b['id'], {'wall': w['id'], 'side': side}, {'uv': {'u': .25, 'v': 0, 'rot': 90}})
    remember('uv', [plan, u_plan])
    twin_store.revert(seed_round)
    for i, target in enumerate(targets):
        surface = ({'wall': target['wall'], 'side': target['side']} if 'wall' in target else
                   {'room': target['room'], 'surface': 'floor'} if 'room' in target else
                   {'roof': target['roof'], 'plane': target['plane']})
        save(target['bid'], surface, {'id': assets[f'cost{i}']['id']})
    remember('many', [plan])
    twin_store.revert(seed_round)
    feature = next(f for f in twin_store.current()['site']['pool']['features'] if f['kind'] == 'ledge')
    twin_edit.save({'op': 'update_pool_feature', 'id': feature['id'],
                    'materials': {'interior': {'id': assets['selected']['id']}}}, S.H.PARENT['id'])
    remember('ledge', [plan])
    payload.update(stages=stages, targets=targets, feature=feature['id'], selected=assets['selected']['id'], floor=f'{b["id"]}:{w["level"]}',
                   costIds=[assets[f'cost{i}']['id'] for i in range(40)])
    # Each live scenario opens a fresh page. Give its mounted runtime and bake
    # caches the same independent module lifetime rather than sharing detached
    # atlas/material caches across four unrelated page fixtures.
    for stage in stages:
        case = {**payload, 'stages': [stage]}
        code, output = run_node(DRIVER.replace('RECORD_SURFACES', S.SURFACE_RECORDS), case, timeout=600)
        print(output, flush=True)
        assert code == 0, output


if __name__ == '__main__':
    main()
