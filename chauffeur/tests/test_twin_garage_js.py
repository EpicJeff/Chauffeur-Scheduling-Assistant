"""Garage geometry, slots, poses and the schema-driven card through real modules."""
import sys
from test_twin_untouched_house_js import COMMON, ROOT, run_node

DRIVER = COMMON + r"""
const D=await import(file('static/twin/garage_door.js'));
const {drawObjectShelf}=await import(file('static/twin/editor/object_shelf.js'));
const {materialLines}=await import(file('static/twin/editor/library.js'));
window.twinObjectSchema=JSON.parse(readFileSync(new URL(file('static/twin/object_schema.json'))));
const material=part=>new THREE.MeshStandardMaterial({name:part});
const spec=width=>({id:'garage',kind:'garage',width,sill:0,head:7});
const finite=door=>door.traverse(o=>{if(o.isMesh)assert.ok([...o.geometry.attributes.position.array].every(Number.isFinite));});
const moving=out=>{const rows=[];out.root.traverse(o=>{if(o.userData.garageOpening)rows.push(o);});return rows;};
for(const width of [8,16])for(const style of ['raised','flat','carriage','full_view'])for(const lites of ['none','top']){
 await test(`build:${width}:${style}:${lites}`,async()=>{
  const door=D.buildGarageDoor({...spec(width),style,lites},{material});finite(door);
  assert.equal(door.userData.garageOpening.sections,4);assert.equal(door.userData.garageOpening.columns,width/4);
  const glass=style==='full_view'||lites==='top';assert.equal(door.children.length,glass?2:1);
  assert.ok(door.children.length<=3);assert.equal(new Set(door.children.map(o=>o.material.name)).size,door.children.length);
  for(const o of door.children){assert.equal(o.material.name,o.userData.part);assert.ok(o.geometry.userData.bakeExcluded);assert.ok(o.userData.garageDoor);}
  assert.equal(door.children.some(o=>o.material.name==='pane'),glass);
  assert.ok(door.children.some(o=>o.material.name===(style==='full_view'?'window_frame':'garage_door')));
  const bounds=new THREE.Box3().setFromObject(door);assert.ok(bounds.min.y>=0&&bounds.max.y<=7);
 });
}
await test('defaults_and_authored_columns_and_sections',async()=>{
 const a=D.buildGarageDoor(spec(16),{material}),b=D.buildGarageDoor({...spec(16),style:'raised',lites:'none'},{material});
 assert.deepEqual(a.children.map(o=>hash(o.geometry.attributes.position)),b.children.map(o=>hash(o.geometry.attributes.position)));
 for(const panels of [undefined,1,3,6])assert.equal(D.buildGarageDoor({...spec(16),panels},{material}).userData.garageOpening.columns,panels>1?panels:4);
 for(const height of [3,8,10])assert.equal(D.buildGarageDoor({...spec(8),head:height},{material}).userData.garageOpening.sections,Math.max(3,Math.round(height/(21/12))));
 const glass=lites=>D.buildGarageDoor({...spec(8),style:'full_view',lites},{material}).children.map(o=>hash(o.geometry.attributes.position));
 assert.deepEqual(glass('top'),glass('none'),'full view ignores lites');
});
await test('generator_slots_follow_item_level_house_then_door_role',async()=>{
 const p=fixture(),b=p.buildings[0],o=b.openings.find(o=>o.id==='garage');o.lites='top';
 const get=out=>moving(out).find(g=>g.userData.garageOpening.building==='a').children;
 b.materials.door={id:'blend'};
 assert.equal(get(await build(p)).find(o=>o.userData.part==='garage_door').material.userData.materialId,'blend');
 b.materials.garage_door={id:'choice'};
 assert.equal(get(await build(p))[0].material.userData.materialId,'choice');
 b.levels[0].materials={garage_door:{id:'blend'}};
 assert.equal(get(await build(p))[0].material.userData.materialId,'blend');
 o.materials={garage_door:{id:'choice'},pane:{id:'blend'}};
 const out=await build(p);const door=get(out);assert.equal(door[0].material.userData.materialId,'choice');
 assert.equal(door.find(o=>o.userData.part==='pane').material.userData.materialId,'blend');
 for(const mesh of door){assert.ok(mesh.parent);assert.ok(!mesh.userData.merged);assert.equal(A.atlasMesh(mesh),false);}
 const S=await import(file('static/twin/surface_kinds.js'));assert.ok(S.ITEM_PARTS.opening.includes('garage_door'));
 const rows=materialLines({kind:'opening',piece:o,building:b},p,kit());
 assert.deepEqual(rows.map(l=>l.target.part),['garage_door','pane','window_frame','casing']);assert.equal(rows[0].label,'Garage door');
 o.lites='none';assert.deepEqual(materialLines({kind:'opening',piece:o,building:b},p,kit()).map(l=>l.target.part),['garage_door','window_frame','casing']);
 assert.deepEqual(o.materials.pane,{id:'blend'});o.style='full_view';assert.ok(materialLines({kind:'opening',piece:o,building:b},p,kit()).some(l=>l.target.part==='pane'));
});
await test('library_model_replaces_generated_door',async()=>{
 const {rememberImport}=await import(file('static/twin/twin_library.js'));
 const p=fixture(),b=p.buildings[0],o=b.openings.find(o=>o.id==='garage');
 rememberImport({id:'import-garage',kind:'door',revision:1,model:'door.gltf',files:{'door.gltf':true}});o.model='import-garage';
 const vertices=new Float32Array([-1,0,-.1,1,0,-.1,0,2,.1]);
 const gltf={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],meshes:[{primitives:[{attributes:{POSITION:0}}]}],
  buffers:[{uri:'data:application/octet-stream;base64,'+Buffer.from(vertices.buffer).toString('base64'),byteLength:36}],
  bufferViews:[{buffer:0,byteLength:36}],accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[-1,0,-.1],max:[1,2,.1]}]};
 const oldFetch=globalThis.fetch;window.location=location;
 globalThis.ProgressEvent=class {constructor(type,values){this.type=type;Object.assign(this,values);}};
 globalThis.fetch=async url=>String(typeof url==='string'?url:url.url).startsWith('data:')?oldFetch(url):new Response(JSON.stringify(gltf));
 try{const out=await build(p);assert.ok(!moving(out).some(g=>g.userData.garageOpening.building==='a'));
 assert.ok(piece(out,'garage').some(o=>!o.userData.pendingImport),'real glTF replaces placeholder');
 assert.ok(piece(out,'garage').every(o=>!o.userData.pendingImport));}finally{globalThis.fetch=oldFetch;}
});
await test('viewer_keeps_one_moving_group_per_opening_across_wall_variants',async()=>{
 const p=fixture();for(const b of p.buildings)b.openings.find(o=>o.kind==='garage').lites='top';
 const out=G.buildTwin(p,kit(),'low',{viewing:true});await out.ready;
 const doors=moving(out);assert.equal(doors.length,2);
 for(const door of doors){assert.equal(door.children.length,2);
  for(let parent=door.parent;parent;parent=parent.parent)assert.ok(!parent.userData.viewingWalls);
 }
});
await test('open_pose_is_inside_and_clears_wall_on_both_sides',async()=>{
 for(const inward of [-1,1]){
  const door=D.buildGarageDoor({...spec(16),lites:'top'},{material,inward,setback:.41});
  const ids=door.children.map(o=>[o.uuid,o.geometry.uuid]),closed=new THREE.Box3().setFromObject(door);
  assert.ok(closed.min.z<0&&closed.max.z>0);
  D.garagePose(door,true);const open=new THREE.Box3().setFromObject(door);
  assert.ok(inward===-1?open.max.z<-.25:open.min.z>.25,'whole group clears the wall thickness');
  assert.ok(Math.abs(open.max.y-open.min.y)<.25,'overhead, flat under the head');
  assert.deepEqual(door.children.map(o=>[o.uuid,o.geometry.uuid]),ids);D.garagePose(door,false);
  assert.deepEqual(new THREE.Box3().setFromObject(door),closed);
 }
});
await test('card_selects_and_single_ops_and_device_hint',async()=>{
 const operations=[],b=fixture().buildings[0],garage=b.openings.find(o=>o.id==='garage');
 const options={canEdit:()=>true,queue:f=>Promise.resolve().then(f),op:async op=>operations.push(op),report:e=>{throw e;}};
 globalThis.fetch=async()=>new Response('[]');
 const draw=(piece,devices=[])=>{const host=document.createElement('div');document.body.append(host);drawObjectShelf(host,{kind:'opening',piece,building:b},{...options,devices});return host;};
 const host=draw(garage);assert.ok(host.textContent.includes('Opens and closes with the garage door device placed on it.'));
 for(const [label,value,field] of [['Door style','carriage','style'],['Windows','top','lites']]){
  const select=host.querySelector(`[aria-label="${label}"]`);assert.ok(select);select.value=value;fire(select,'change');await new Promise(r=>setImmediate(r));
  assert.equal(operations.length,field==='style'?1:2);assert.deepEqual(operations.at(-1),{op:'set_object',building:b.id,id:garage.id,properties:{[field]:value}});
 }
 const labels=host.querySelector('[aria-label="Door style"]').children.map(o=>o.textContent);assert.deepEqual(labels,['Raised panel','Flat panel','Carriage','Full view glass']);
 for(const kind of ['window','door','slider','passage']){const card=draw({...garage,kind});assert.equal(card.querySelector('[aria-label="Door style"]'),null);assert.equal(card.querySelector('[aria-label="Windows"]'),null);}
 b.devices=[{device:'g',host:{opening:garage.id}}];
 assert.ok(!draw(garage,[{device_id:'g',kind:'garage',entity_id:'cover.g'}]).textContent.includes('Opens and closes with'));
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'editable': True}, timeout=180)
    print(output)
    sys.exit(code or 0)
