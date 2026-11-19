"""Editor-only visibility through real geometry, mounted view and shared picker."""
from pathlib import Path
import sys
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const {createVisibility}=await import(file('static/twin/editor/visibility.js'));
const {createPieceVisibility}=await import(file('static/twin/twin_visibility.js'));
const {createPicker}=await import(file('static/twin/editor/picking.js'));
const T=await import('three');
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const storage=()=>{const rows=new Map();return {getItem:k=>rows.get(k)??null,setItem:(k,v)=>rows.set(k,v)};};
await test('store_roundtrip_house_pruning_and_notifications',()=>{
 const s=storage(),v=createVisibility({houseId:'one',storage:s});let calls=0;
 const off=v.subscribe(()=>calls++);v.hide('wall');v.lock('tree');v.hideKind('roof');v.lockKind('planting');
 assert.deepEqual(JSON.parse(s.getItem('chauffeur.editor.visibility.one')),v.snapshot());
 const copy=createVisibility({houseId:'one',storage:s});assert.deepEqual(copy.snapshot(),v.snapshot());
 v.forHouse('two',['wall']);assert.equal(v.isHidden('wall'),true);assert.equal(v.isLocked('tree'),false);
 v.showAll();v.forHouse('one',['wall','tree']);assert.equal(v.isHidden('wall'),true);assert.equal(v.isLocked('tree'),true);
 v.forHouse('one',['tree']);assert.equal(v.isHidden('wall'),false);assert.equal(v.isHidden('anything','roof'),true);
 v.showAll();assert.equal(v.isHidden('anything','roof'),false);assert.equal(v.isLocked('tree'),true);
 const snap=v.snapshot();snap.locked.length=0;assert.equal(v.isLocked('tree'),true);
 off();const before=calls;v.unlock('tree');assert.equal(calls,before);
 v.unlockKind('planting');assert.equal(v.isLocked('x','planting'),false);
 v.hideKind('wall');v.showKind('wall');v.hide('x');v.show('x');v.lockKind('wall');v.unlockKind('wall');
 assert.equal(v.isPickable({pieceId:'x',kind:'wall'}),true);
});
await test('broken_or_unavailable_storage_is_nonfatal',()=>{
 for(const s of [{getItem:()=>'{',setItem(){throw Error('quota');}},{getItem(){throw Error('denied');},setItem(){throw Error('denied');}}]){
  const v=createVisibility({houseId:'x',storage:s});v.hide('a');assert.equal(v.isHidden('a'),true);
 }
});
await test('shared_picker_skips_hidden_locked_and_kind_aliases_while_cycling',()=>{
 const v=createVisibility({storage:storage()}),hits=[{kind:'wall',id:'w',distance:1},{kind:'planting',id:'p',distance:2},{kind:'room',id:'r',distance:3}];
 const p=createPicker({sources:[()=>hits],isPickable:v.isPickable});v.hide('w');v.lockKind('planting');
 for(let i=0;i<4;i++)assert.equal(p.click(1,2).id,'r');
 v.showAll();assert.equal(p.click(1,2).id,'w');assert.equal(p.click(1,2).id,'r');
 v.hideKind('planting');assert.equal(v.isPickable({kind:'tree',pieceId:'p'}),false);
 v.lockKind('fixture');assert.equal(v.isPickable({kind:'light',id:'l'}),false);
});
await test('instances_and_separate_objects_restore_without_material_changes',()=>{
 const root=new T.Group(),mat=new T.MeshStandardMaterial(),mesh=new T.InstancedMesh(new T.BoxGeometry(),mat,2),m=new T.Matrix4();
 mesh.userData.instances=[{pieceId:'a',kind:'planting'},{pieceId:'b',kind:'planting'}];
 mesh.setMatrixAt(0,m.makeTranslation(1,2,3));mesh.setMatrixAt(1,m.makeTranslation(4,5,6));root.add(mesh);
 const object=new T.Mesh(new T.BoxGeometry(),mat);object.userData={pieceId:'chair',kind:'furniture'};root.add(object);
 const before=Array.from(mesh.instanceMatrix.array),version=mat.version,key=mat.customProgramCacheKey(),v=createPieceVisibility();
 v.set(['a','chair'],[]);v.apply(root);mesh.getMatrixAt(0,m);assert.equal(new T.Vector3().setFromMatrixScale(m).length(),0);
 assert.deepEqual(Array.from(mesh.instanceMatrix.array.slice(16)),before.slice(16));assert.equal(object.visible,false);
 v.set([],[]);v.apply(root);assert.deepEqual(Array.from(mesh.instanceMatrix.array),before);assert.equal(object.visible,true);
 v.set([],['planting']);v.apply(root);for(let i=0;i<2;i++){mesh.getMatrixAt(i,m);assert.equal(new T.Vector3().setFromMatrixScale(m).length(),0);}
 v.restore();assert.deepEqual(Array.from(mesh.instanceMatrix.array),before);assert.equal(mat.version,version);assert.equal(mat.customProgramCacheKey(),key);
});
await test('lights_keep_their_program_count_and_show_with_the_current_time_look',()=>{
 const root=new T.Group(),lamp=new T.PointLight('white',2),group=new T.Group(),mesh=new T.Mesh(new T.BoxGeometry(),new T.MeshStandardMaterial());
 group.userData={kind:'fixture',pieceId:'lamp'};group.add(lamp,mesh);root.add(group);
 const v=createPieceVisibility();v.set(['lamp'],[]);v.apply(root);
 assert.equal(group.visible,true);assert.equal(lamp.visible,true);assert.equal(lamp.intensity,0);assert.equal(mesh.visible,false);
 v.setLightIntensity(lamp,5);assert.equal(lamp.intensity,0);
 v.set([],[]);v.apply(root);assert.equal(lamp.intensity,5);assert.equal(mesh.visible,true);
});
await test('late_effect_poses_and_imports_stay_hidden_until_shown',()=>{
 const root=new T.Group(),v=createPieceVisibility();v.set([],['effect']);v.apply(root);
 const effect=new T.Group();effect.userData={kind:'effect',pieceId:'late'};root.add(effect);
 v.enforce(root);assert.equal(effect.visible,false);effect.visible=true;v.enforce(root);assert.equal(effect.visible,false);
 v.set([],[]);v.apply(root);assert.equal(effect.visible,true);
});
await test('reused_selection_helpers_follow_their_new_owner',()=>{
 const root=new T.Group(),helper=new T.Line(new T.BufferGeometry(),new T.LineBasicMaterial()),v=createPieceVisibility();
 helper.userData={kind:'planting',pieceId:'hidden'};root.add(helper);v.set(['hidden'],[]);v.apply(root);assert.equal(helper.visible,false);
 helper.userData.pieceId='shown';helper.visible=true;v.enforce(root);assert.equal(helper.visible,true);
 helper.userData.pieceId='hidden';v.enforce(root);assert.equal(helper.visible,false);
 v.set([],[]);v.apply(root);assert.equal(helper.visible,true);
});
const square=[[0,0],[10,0],[10,10],[0,10]],fixture=()=>({buildings:[{id:'b',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:8,outline:square}],walls:[
 {id:'w',level:'L1',from:[0,0],to:[10,0],height:8,thickness:.5,state:'settled'},
 {id:'other',level:'L1',from:[0,10],to:[10,10],height:8,thickness:.5,state:'settled'}],rooms:[{id:'room',level:'L1',polygon:square,state:'settled'}],openings:[],anchors:[],items:[],roof:{sections:[]}}],site:{},materials:{}});
async function mount(editor=true){const host=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(host);}return mountTwin(host,{plan:fixture(),kit:{materials:{}},tier:'low',bake:false,preserveCamera:true});}
const batches=v=>{const out=[];v.scene.traverse(o=>{if(o.userData.snapRanges?.some(r=>r.pieceId==='w'))out.push(o);});return out;};
await test('merged_wall_exact_ranges_restore_and_viewer_ignores_visibility',async()=>{
 for(const editor of [true,false]){const v=await mount(editor);try{
  const rows=batches(v).map(o=>({o,positions:Array.from(o.geometry.attributes.position.array),version:o.material.version,key:o.material.customProgramCacheKey()}));assert.ok(rows.length);
  v.setHiddenPieces(['w'],[]);
  for(const {o,positions,version,key} of rows){const a=Array.from(o.geometry.attributes.position.array);for(const r of o.userData.snapRanges){
   const old=positions.slice(r.start*3,(r.start+r.count)*3),now=a.slice(r.start*3,(r.start+r.count)*3);
   if(editor&&r.pieceId==='w'){for(let i=0;i<now.length;i++)assert.equal(now[i],old[i%3]);}else assert.deepEqual(now,old);
  }assert.equal(o.material.version,version);assert.equal(o.material.customProgramCacheKey(),key);}
  v.setHiddenPieces([],[]);for(const {o,positions} of rows)assert.deepEqual(Array.from(o.geometry.attributes.position.array),positions);
 }finally{v.dispose();}}
});
await test('hidden_state_survives_deform_settle_and_full_rebuild',async()=>{
 const v=await mount();try{
  v.setHiddenPieces(['w'],[]);const next=fixture();next.buildings[0].walls[0].to=[12,0];
  await v.settle(next);const shown=await mount();try{
   await shown.settle(next);v.setHiddenPieces([],[]);
   assert.deepEqual(batches(v).map(o=>Array.from(o.geometry.attributes.position.array)),batches(shown).map(o=>Array.from(o.geometry.attributes.position.array)));
  }finally{shown.dispose();}
  v.setHiddenPieces([],['wall']);await v.rebuild(next);
  for(const o of batches(v))for(const r of o.userData.snapRanges.filter(r=>r.kind==='wall')){const a=o.geometry.attributes.position.array;for(let i=0;i<r.count*3;i++)assert.equal(a[r.start*3+i],a[r.start*3+i%3]);}
 }finally{v.dispose();}
});
await test('real_yard_ownership_hides_plants_beds_edges_and_pad_triangles',async()=>{
 globalThis.__THREE_MESH=T.Mesh;globalThis.__THREE_BOX=T.BoxGeometry;globalThis.__THREE_STD=T.MeshStandardMaterial;
 const {buildYard}=await import(file('static/twin/twin_yard.js'));
 const plan={buildings:[],materials:{},site:{lot:square,terraces:[{id:'pad',polygon:[[2,2],[8,2],[8,8],[2,8]],height:1,blend:2}],
  planting:[{id:'tree',preset:'oak',height:5,at:[20,20],seed:1}],beds:[{id:'bed',polygon:[[0,0],[1,0],[1,1],[0,1]]}],edges:[{id:'edge',polygon:[[8,8],[9,8],[9,9],[8,9]]}]}},
  yard=(await buildYard(plan,{materials:{}},'high',{viewing:false})).group;
 const v=createPieceVisibility(),saved=[];yard.traverse(o=>{if(o.geometry)saved.push([o,Array.from(o.geometry.attributes.position.array)]);});
 const plant=yard.children.find(o=>o.userData.pieceId==='tree');assert.ok(plant);
 const terrain=saved.find(([o])=>o.userData.terrain&&o.userData.visibilityGeometry)[0],original=terrain.geometry;
 assert.ok(original.index,'ordinary terrain keeps its original indexed buffer');
 v.set([],['planting','bed','edge','pad']);v.apply(yard);assert.equal(plant.visible,false);
 let blend=false;yard.traverse(o=>{const a=o.geometry?.attributes.position;for(const r of o.geometry?.userData.snapRanges || [])if(r.pieceId==='pad')for(let i=r.start;i<r.start+r.count;i++)if(a.getX(i)<2)blend=true;});assert.ok(blend,'pad ranges include the ground blend');
 for(const id of ['bed','edge','pad']){let ranges=0;yard.traverse(o=>{for(const r of o.userData.snapRanges || o.geometry?.userData.snapRanges || [])if(r.pieceId===id){
  ranges++;const a=o.geometry.attributes.position.array;for(let i=0;i<r.count*3;i++)assert.equal(a[r.start*3+i],a[r.start*3+i%3]);
 }});assert.ok(ranges,id+' has an owned range');}
 v.set([],[]);v.apply(yard);assert.equal(terrain.geometry,original);assert.equal(plant.visible,true);for(const [o,a] of saved)assert.deepEqual(Array.from(o.geometry.attributes.position.array),a);
 const {disposeObject}=await import(file('static/twin/twin_library.js'));yard.userData.releasePlants?.();disposeObject(yard);
});
finish();
"""


def run_ui():
    import test_twin_gesture_rules_js as gestures
    setup = gestures.DRIVER.split("await test('pad_corner_wins_over_tree'")[0]
    setup = setup.replace('const view=await mountTwin(new Element(),', "const host=new Element();shell.className='editor-shell';shell.append(host);const view=await mountTwin(host,")
    setup = setup.replace('const tools=createSceneTools({view,', '''
  const {createVisibility}=await import(file('static/twin/editor/visibility.js'));
  const visibility=createVisibility({storage:null});view.isPiecePickable=visibility.isPickable;
  const tools=createSceneTools({view,visibility,isPickable:visibility.isPickable,''')
    setup = setup.replace('globalThis.ResizeObserver=originalResizeObserver;', '''
  const off=visibility.subscribe(()=>{const s=visibility.snapshot();view.setHiddenPieces(s.hidden,s.hiddenKinds);tools.visibilityChanged();library?.refresh();terrain?.refresh();});abort.signal.addEventListener('abort',off);
  globalThis.ResizeObserver=originalResizeObserver;''')
    setup = setup.replace('ready,\n    resizeCanvas:', 'ready,visibility,\n    resizeCanvas:')
    gestures.DRIVER = setup + r"""
const key=(key,extra={})=>{const e=new Event('keydown',{cancelable:true});Object.assign(e,{key,...extra});doc.dispatchEvent(e);return e;};
await test('H_and_ShiftH_and_modifier_input_guards',async({tools,visibility,ops,ready})=>{
 tools.select({kind:'wall',id:W,building:B});await ready();
 assert.ok(tools.handles().length);assert.equal(key('h').defaultPrevented,true);assert.equal(visibility.isHidden(W),true);
 assert.equal(tools.handles().length,0);visibility.lock('other');key('H',{shiftKey:true});
 assert.equal(visibility.isHidden(W),false);assert.equal(visibility.isLocked('other'),true);assert.ok(tools.handles().length);
 for(const extra of [{ctrlKey:true},{altKey:true},{metaKey:true}]){key('h',extra);assert.equal(visibility.isHidden(W),false);}
 doc.closest=()=>({});key('h');assert.equal(visibility.isHidden(W),false);doc.closest=()=>null;
 assert.equal(ops.length,0,'visibility never writes an edit');
});
await test('locked_tree_selection_keeps_properties_without_handles',async({tools,visibility,ready})=>{
 tools.select({kind:'wall',id:W,building:B});await ready();visibility.lock(W);
 assert.equal(tools.selection().id,W);assert.equal(tools.handles().length,0);
 tools.select({kind:'wall',id:W,building:B});assert.equal(tools.selection().id,W);assert.equal(tools.handles().length,0);
 visibility.unlock(W);assert.ok(tools.handles().length);
});
await test('hidden_pad_graphics_and_locked_pad_handles_update_at_once',async({terrain,visibility,look})=>{
 flat.site.terraces=[{id:'pad:visibility',polygon:[[200,200],[220,200],[220,220],[200,220]],height:0,blend:0}];
 look([200,200,0]);terrain.choose('terraces','pad:visibility');assert.equal(terrain.handles().length,8);
 visibility.lockKind('pad');assert.equal(terrain.handles().length,0);visibility.unlockKind('pad');assert.equal(terrain.handles().length,8);
 visibility.hide('pad:visibility');assert.equal(terrain.handles().length,0);visibility.showAll();assert.equal(terrain.handles().length,8);
});
console.log(`${passed} UI visibility checks passed`);if(failed)process.exitCode=1;
"""
    gestures.run()


if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(out)
    if code:
        sys.exit(code)
    run_ui()
