"""Task 5 executes the real card, handles, gizmo, tree and 3D picks in Node."""
import json
from pathlib import Path
import subprocess
import tempfile

from test_twin_roof_tools_js import DRIVER as ROOF_DRIVER, ROOT

DRIVER = ROOF_DRIVER.split('look([15.5,11,roof.plate]);')[0] + r"""
const {createGizmo}=await import(file('static/twin/editor/gizmo.js'));
const {supportPoints,roofPoint}=await import(file('static/twin/roof_supports.js'));
const {roofHostChoices}=await import(file('static/twin/editor/roof_support_shelf.js'));
const hostRoof={area:[[0,0],[12,0],[12,4],[0,4]],level:'L1'};
const hostBuilding={walls:Array.from({length:20},(_,i)=>({id:`w${i}`,from:[0,-i-1],to:[12,-i-1],level:'L1',exterior:true}))};
hostBuilding.walls.push({id:'other-floor',level:'L2',from:[0,0],to:[12,0]}, {id:'separator',kind:'separator',level:'L1',from:[0,0],to:[12,0]}, {id:'angled',level:'L1',from:[0,-.1],to:[12,-.6]});
assert.deepEqual(roofHostChoices(hostRoof,hostBuilding).map(w=>[w.wall,w.edge]),Array.from({length:8},(_,i)=>[`w${i}`,0]));
hostRoof.host={wall:'w19',edge:0};assert.ok(roofHostChoices(hostRoof,hostBuilding).some(w=>w.wall==='w19'&&w.edge===0));
const {normalizeRoofBox}=await import(file('static/twin/roof_box_contract.js'));
assert.deepEqual(normalizeRoofBox({area:hostRoof.area,support:{kind:'brace'},host:{edge:0},edges:[{setting:'gable'},{setting:'gable'},{setting:'sloped',pitch:3},{setting:'gable'}],ends:{'0':'closed','1':'closed','2':'closed'},underside:{kind:'flat',drop_ft:9}}).underside,{kind:'flat',drop_ft:0});
const cards=createCards({getPlan:()=>flat,getLabel:()=> 'roof',canEdit:()=>enabled,edit:()=>{},op:commit,select(){},ask(){}});
const card=nodes.get('piece-card'), controls=()=>descendants(card);
const scroll=new Element();scroll.style.overflowY='auto';scroll.scrollTop=240;scroll.scrollHeight=2000;scroll.clientHeight=600;scroll.append(card);
globalThis.getComputedStyle=node=>({overflowY:node.style.overflowY||'',overflow:'',getPropertyValue:()=>''});
Element.prototype.contains=function(node){return node===this||descendants(this).includes(node);};
Element.prototype.hasAttribute=function(key){return this[key]!==undefined;};
Element.prototype.focus=function(){document.activeElement=this;};
Object.defineProperty(Element.prototype,'tagName',{get(){return this.tag?.toUpperCase();}});
Element.prototype.querySelectorAll=function(tag){return descendants(this).filter(n=>n.tag===tag?.toLowerCase());};
const replace=Element.prototype.replaceChildren;Element.prototype.replaceChildren=function(){replace.call(this);if(this===card){scroll.scrollTop=0;document.activeElement=null;}};
cards.draw({pieceId:roof.id,buildingId:B});
let choice=controls().find(n=>n['aria-label']==='Support kind');assert.ok(choice,'ordinary roof has support choice');
choice.value='post';choice.dispatchEvent(new Event('change'));await new Promise(r=>setTimeout(r,0));
assert.equal(ops.at(-1).op,'set_roof_support');assert.deepEqual(ops.at(-1).support,{kind:'post'});
roof.support={kind:'bracket',count:2,inset_ft:.6,size_ft:.5};
const section=b.roof.sections.find(s=>s.id===roof.id);section.support=roof.support;
cards.draw({pieceId:roof.id,buildingId:B});
for(const label of ['Support count','Support inset','Support size','Support style','Thickness','Fascia','Host wall','Move along building X (ft)','Move along building Y (ft)'])assert.ok(controls().find(n=>n['aria-label']===label),label);
const flush=()=>new Promise(r=>setTimeout(r,0));
roof.edges=[{setting:'gable',pitch:3},{setting:'gable',pitch:3},{setting:'sloped',pitch:3},{setting:'gable',pitch:3}];roof.host={wall:'current-host',edge:0};roof.ends={'1':'closed'};roof.underside={kind:'flat',drop_ft:1};
cards.draw({pieceId:roof.id,buildingId:B});
assert.ok(controls().find(n=>n['aria-label']==='Left end'));assert.ok(controls().find(n=>n['aria-label']==='Right end'));
assert.ok(!controls().find(n=>n['aria-label']==='Front end'));assert.ok(!controls().find(n=>n['aria-label']==='Back end'));
let allEnds=controls().find(n=>n['aria-label']==='All ends');allEnds.focus();scroll.scrollTop=240;allEnds.value='closed';allEnds.dispatchEvent(new Event('change'));await flush();assert.deepEqual(ops.at(-1).ends,{'1':'closed','3':'closed'});assert.equal(scroll.scrollTop,240);assert.equal(document.activeElement?.['aria-label'],'All ends');
const ceiling=controls().find(n=>n['aria-label']==='Ceiling underneath');assert.equal(ceiling.value,'flat');
const drop=controls().find(n=>n['aria-label']==='Drop below the roof edge (ft)');drop.value='2';drop.dispatchEvent(new Event('change'));await flush();assert.deepEqual(ops.at(-1).underside,{kind:'flat',drop_ft:2});
let style=controls().find(n=>n['aria-label']==='Support style');assert.equal(style.tag,'select');assert.deepEqual(style.children.map(n=>n.textContent),['Straight']);
roof.support.kind='corbel';roof.support.style='custom-stored';cards.draw({pieceId:roof.id,buildingId:B});style=controls().find(n=>n['aria-label']==='Support style');assert.deepEqual(style.children.map(n=>n.textContent),['Choose a style','Scroll','Stepped']);assert.equal(roof.support.style,'custom-stored');
roof.support.kind='cable';cards.draw({pieceId:roof.id,buildingId:B});assert.ok(!controls().find(n=>n['aria-label']==='Support style'));
roof.support.kind='bracket';delete roof.support.style;delete roof.ends;delete roof.underside;delete roof.host;cards.draw({pieceId:roof.id,buildingId:B});
for (const text of ['', '41', '2.5', '2']) {
 const n=ops.length, input=controls().find(n=>n['aria-label']==='Support count');
 input.value=text;input.dispatchEvent(new Event('change'));await flush();assert.equal(ops.length,n);
 if(!text)assert.equal(input.value,'2');
 if(['41','2.5'].includes(text)){assert.equal(input['aria-invalid'],'true');assert.match(input.parentElement?.children?.at(-1)?.textContent || descendants(card).find(n=>n.textContent?.includes('whole number'))?.textContent || '',/whole number/);}
}
const pos1=controls().find(n=>n['aria-label']==='Support 1 position (x, y)'),pos2=controls().find(n=>n['aria-label']==='Support 2 position (x, y)');
pos1.value='1.123, 2.456';pos1.dispatchEvent(new Event('change'));pos2.value='5.789, 6.123';pos2.dispatchEvent(new Event('change'));await flush();
assert.deepEqual(ops.at(-2).at,{'0':[1.123,2.456]});assert.deepEqual(ops.at(-1).at,{'1':[5.789,6.123]});
const noop=ops.length;const blankMove=controls().find(n=>n['aria-label']==='Move along building X (ft)');blankMove.value='';blankMove.dispatchEvent(new Event('change'));await flush();assert.equal(ops.length,noop);assert.equal(blankMove.value,'0');
let count=controls().find(n=>n['aria-label']==='Support count');scroll.scrollTop=240;count.focus();count.value='40';count.dispatchEvent(new Event('change'));await new Promise(r=>setTimeout(r,0));assert.deepEqual(ops.at(-1).support,{count:40});
assert.equal(scroll.scrollTop,240);assert.equal(document.activeElement?.['aria-label'],'Support count');
const move=controls().find(n=>n['aria-label']==='Move along building X (ft)');move.value='2';move.dispatchEvent(new Event('change'));await new Promise(r=>setTimeout(r,0));assert.equal(ops.at(-1).op,'move_roof');
const beforePosition=controls().find(n=>n['aria-label']==='Support 1 position (x, y)').value;
roof.area=roof.area.map(p=>[p[0]+10,p[1]]);roof.roof_frame={origin:[0,0],angle:.005};cards.draw({pieceId:roof.id,buildingId:B});
assert.notEqual(controls().find(n=>n['aria-label']==='Support 1 position (x, y)').value,beforePosition);
assert.equal(controls().filter(n=>n['aria-label']==='Roof height').length,1);
roof.area=roof.area.map(p=>[p[0]-10,p[1]]);delete roof.roof_frame;
ok('ordinary and supported roof cards share support, gutter, material and whole-roof controls');
let shown=handles.handles();assert.equal(shown.filter(h=>h.kind==='roof_edge').length,4);
assert.equal(shown.filter(h=>h.kind==='roof_support').length,2);assert.ok(shown.some(h=>h.kind==='roof_height'));
let h=shown.find(h=>h.kind==='roof_support');look(h.at);assert.ok(handles.begin(event(h.at)));handles.update(event([h.at[0]+1,h.at[1],h.at[2]]));await handles.finish();
assert.equal(ops.at(-1).op,'set_roof_support');assert.ok(ops.at(-1).at);
const noPin=ops.length;h=handles.handles().find(h=>h.kind==='roof_support');look(h.at);assert.ok(handles.begin(event(h.at)));handles.update(event([h.at[0]+1,h.at[1],h.at[2]]));handles.update(event(h.at));await handles.finish();assert.equal(ops.length,noPin);
ok('support handles commit a point override through the shared operation');
h=handles.handles().find(h=>h.kind==='roof_height');view.camera.position.copy(world([h.at[0],h.at[1]-30,h.at[2]+15]));view.camera.lookAt(world(h.at));view.camera.updateMatrixWorld(true);
const heightEvent=p=>{const e=event(p);return {...e,clientX:e.clientX+h.offset[0],clientY:e.clientY+h.offset[1]};};
assert.equal(handles.hit(heightEvent(h.at)).kind,'roof_height');assert.ok(handles.begin(heightEvent(h.at)));handles.update(heightEvent([h.at[0],h.at[1],h.at[2]+1]));await handles.finish();assert.equal(ops.at(-1).field,'plate');near(ops.at(-1).value,roof.plate+1);
assert.ok(h);enabled=false;assert.deepEqual(handles.handles(),[]);cards.draw({pieceId:roof.id,buildingId:B});assert.ok(controls().find(n=>n['aria-label']==='Support count').disabled);enabled=true;
assert.ok(handles.begin(heightEvent(h.at)));await handles.commit(9);assert.equal(ops.at(-1).value,9,'typed height is absolute');
const noHeight=ops.length;assert.ok(handles.begin(heightEvent(h.at)));handles.update(heightEvent([h.at[0],h.at[1],h.at[2]+1]));handles.update(heightEvent(h.at));await handles.finish();assert.equal(ops.length,noHeight,'returning to current height saves nothing');
const gizmo=createGizmo({getPlan:()=>flat,getSelection:()=>selected,getStructuralHandles:()=>handles.handles(),getTool:()=> 'move',view,layer:new Element(),op:commit});
assert.equal(gizmo.hit(heightEvent(h.at)),null,'height control is clear of the move gizmo');
look([15.5,11,roof.plate]);h=gizmo.handles().find(h=>h.kind==='gizmo_move_x');assert.ok(h);assert.ok(gizmo.begin(event(h.at),h));gizmo.update(event([h.at[0]+2,h.at[1],h.at[2]]));await gizmo.finish();assert.equal(ops.at(-1).op,'move_roof');
const savedArea=roof.area;roof.area=[[0,0],[12,0],[12,4],[0,4]];
for (const distance of [25,40,80]) {
 view.camera.position.copy(world([6,2,roof.plate+distance]));view.camera.lookAt(world([6,2,roof.plate]));view.camera.updateMatrixWorld(true);
 const gs=gizmo.handles();assert.equal(gs.length,3);
 for(const structural of handles.handles()) {
  const pixel=event(structural.at);pixel.clientX+=structural.offset?.[0]||0;pixel.clientY+=structural.offset?.[1]||0;
  assert.equal(gizmo.hit(pixel),null,`gizmo stays clear at ${distance} ft`);
  assert.ok(handles.hit(pixel),'structural handle keeps its hit');
 }
}
roof.area=savedArea;const savedSupport=roof.support;delete roof.support;assert.deepEqual(gizmo.handles(),[],'walled roofs keep only their old handles');roof.support=savedSupport;
ok('roof gizmo moves through move_roof and read-only cards and handles disable editing');
await view.rebuildLevel(B,'L1',flat);view.setView('ext');view.showLevels(null);await view.setEditableLevel(null);
look([15.5,11,roof.plate+4]);let picked=view.pick(...Object.values(event([15.5,11,roof.plate+4])));assert.ok(picked?.kind==='roof');
const {buildTwin,roofOutlinePositions}=await import(file('static/twin/twin_generator.js'));const built=buildTwin(flat,kit,{tier:'low'});
const proxy=[...built.pickObjects.values()].find(p=>p.userData.kind==='roof'&&p.userData.pieceId===roof.id&&p.userData.buildingId===B);assert.ok(proxy);
assert.ok(proxy.userData.partObjects.some(p=>(p.object.userData.part||'').startsWith('support:')));
assert.ok(proxy.userData.supportPick,'support geometry joins roof pick proxy');
assert.ok(proxy.userData.outlinePositions.length<=proxy.geometry.attributes.position.array.length,'outline has bounded support geometry');
const detailed=new THREE.SphereGeometry(1,20,11);assert.ok(detailed.index.count/3>=400);
const parts=Array.from({length:40},(_,i)=>({geometry:detailed,userData:{part:`support:${i}`}}));
const outlined=roofOutlinePositions(new Float32Array(18),parts);assert.equal(outlined.length/9,2+40*12,'400-triangle corbels have a fixed 480 support triangle outline cap');detailed.dispose();
built.root.updateMatrixWorld(true);
const part=proxy.userData.partObjects.find(p=>(p.object.userData.part||'').startsWith('support:'));
part.object.geometry.computeBoundingBox();const target=part.object.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(part.group.matrixWorld);
const ray=new THREE.Raycaster(target.clone().add(new THREE.Vector3(0,0,10)),new THREE.Vector3(0,0,-1)),hits=[];proxy.raycast(ray,hits);assert.ok(hits.length,'side ray strikes the support through the roof proxy');
const {sceneRows}=await import(file('static/twin/editor/scene_tree.js'));
const {createVisibility}=await import(file('static/twin/editor/visibility.js'));
delete roof.name;delete section.name;assert.match(sceneRows(flat).find(r=>r.id===roof.id&&r.building===B).name,/^Awning \d+$/);
const visibility=createVisibility({storage:null});visibility.lock(roof.id);assert.equal(visibility.isPickable(selected),false);visibility.unlock(roof.id);visibility.hide(roof.id);assert.equal(visibility.isPickable(selected),false);visibility.showAll();assert.equal(visibility.isPickable(selected),true);
const {createPieceVisibility}=await import(file('static/twin/twin_visibility.js'));const filter=createPieceVisibility();filter.set([roof.id],[]);filter.apply(built.root);assert.equal(proxy.visible,false);filter.restore();assert.equal(proxy.visible,true);
ok('roof triangles and support geometry use one ordinary roof pick proxy');
abort.abort();view.dispose();console.log(`${passed}/${passed} passed`);
"""


def run():
    from services.twin_model_bridge import assemble, flatten
    fixture=json.loads((ROOT/'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model=assemble(fixture)[0]
    kit=json.loads((ROOT/'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'));kit['manifest']={}
    with tempfile.TemporaryDirectory(prefix='awning_editor_') as directory:
        driver=Path(directory)/'test.mjs';payload=Path(directory)/'plan.json'
        driver.write_text(DRIVER,encoding='utf-8');payload.write_text(json.dumps(dict(root=ROOT.as_posix(),flat=flatten(model),kit=kit)),encoding='utf-8')
        result=subprocess.run(['node',str(driver),str(payload)],capture_output=True,text=True,timeout=90)
        print(result.stdout,end='')
        if result.returncode:raise AssertionError(result.stderr)


if __name__=='__main__':run()
