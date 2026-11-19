"""Run real editor overlay builders under node; stage haze must leave them clear."""
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE = await import('three');
const {ghostGroup} = await import(file('static/twin/editor/ghost_geometry.js'));
const {aimTool} = await import(file('static/twin/editor/aim_tool.js'));
const {fixtureStroke} = await import(file('static/twin/editor/line_fixture_tool.js'));
const {markerSprite} = await import(file('static/twin/live/markers.js'));
const {createLotTools} = await import(file('static/twin/editor/lot_tools.js'));
const {createTerrainTools} = await import(file('static/twin/editor/terrain_tools.js'));
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const {createUnlit} = await import(file('static/twin/unlit.js'));
function clear(root, minimum) {
 let count=0;
 root.traverse(o=>{for(const m of [o.material].flat().filter(Boolean)) {
   count++;assert.equal(m.fog,false,`${o.type}/${m.type} overlay must remain clear`);
 }});
 assert.ok(count>=minimum,`${count} overlay materials exercised`);
}
await test('ghost_fill_and_dashed_edge_are_unhazed',()=>{
 const {group}=ghostGroup(new THREE.BoxGeometry());clear(group,2);
});
await test('aim_cone_and_handle_are_unhazed',()=>{
 const tool=aimTool({at:[0,0,0],aim:[10,10,5],onCommit:async()=>{}});
 clear(tool.preview,2);tool.begin();tool.move([20,10,5]);clear(tool.preview,2);tool.stop();
});
await test('fixture_stroke_and_shared_device_marker_are_unhazed',()=>{
 clear(fixtureStroke([[0,0,0],[10,10,0],[20,10,0]]),1);
 clear(markerSprite(new THREE.Texture()),1);
});
await test('lot_solid_and_suggestion_dashes_and_terrain_preview_are_unhazed',()=>{
 const shell=document.createElement('div');shell.className='editor-shell';document.body.append(shell);
 const canvas=document.createElement('canvas');shell.append(canvas);
 const view={scene:new THREE.Scene(),renderer3:{domElement:canvas},camera:new THREE.PerspectiveCamera(),
   controls:new THREE.EventDispatcher(),plan:{buildings:[],site:{}},state:{view:'ext'}};
 const abort=new AbortController(),lot=[[0,0],[30,0],[30,30],[0,30]];
 const options={view,getPlan:()=>view.plan,op:async()=>{},canEdit:()=>true,signal:abort.signal};
 createLotTools({...options,getSheets:()=>({place:{buildings:[],lot:{read:{lot,suggestions:[{id:'s',state:'open',outline:lot}]}}}}),
   getSelection:()=>({}),select(){},pauses:{lotPlacement:()=>null},reload(){}});
 createTerrainTools({...options,tools:{selection:()=>({}),setTool(){}}});
 clear(view.scene,3);abort.abort();shell.remove();
});
await test('generated_ghosts_stay_clear_and_real_house_materials_keep_fog',async()=>{
 const outline=[[0,0],[20,0],[20,20],[0,20]],level={id:'L',elevation:0,ceiling:9,outline};
 const building={id:'b',levels:[level],position:[0,0],walls:[
   {id:'w',from:[0,0],to:[20,0],level:'L',height:9,thickness:.5,exterior:true},
   {id:'g',from:[0,10],to:[20,10],level:'L',height:9,thickness:.5,state:'ghost'}],
   rooms:[{id:'r',level:'L',polygon:outline}],openings:[],roof:{sections:[]},anchors:[],fixtures:[],items:[]};
 const model=buildTwin({buildings:[building],site:{},materials:{}},{materials:{}},'low');await model.ready;
 const ghostMaterials=[...model.materials.values()].filter(m=>m.name==='ghost');
 assert.ok(ghostMaterials.length);ghostMaterials.forEach(m=>assert.equal(m.fog,false));
 const standard=[];model.root.traverse(o=>{for(const m of [o.material].flat().filter(Boolean)) {
   if(m.name==='ghost'||o.isLine||o.layers.isEnabled(31)) assert.equal(m.fog,false);
   else if(m.isMeshStandardMaterial){standard.push(m);assert.equal(m.fog,true,`${m.name} participates in stage haze`);}
 }});assert.ok(standard.length,'real house surfaces exercised');
 const unlit=createUnlit();unlit.apply(model.root);
 model.root.traverse(o=>{for(const m of [o.material].flat().filter(Boolean)) {
   if(m.name==='ghost'||o.isLine||o.layers.isEnabled(31)) assert.equal(m.fog,false,'Unlit preserves overlay exemption');
   else if(m.isMeshMatcapMaterial) assert.equal(m.fog,true,'Unlit retains world haze');
 }});unlit.dispose();model.dispose?.();
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code)
