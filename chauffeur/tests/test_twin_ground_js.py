"""Node CPU proof for ground, real yard geometry, foundations and editor input.

No GPU timing/program-count claims: those belong to the unrun browser scenarios.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_twin_drag_js import DRIVER as BASE
from twin_solid_normals import NORMAL_CHECKS

PREFIX = '\n'.join(line for line in BASE.split('const {createDrag, piecesOnMovedJoints}')[0].splitlines()
                   if "if (spec === './twin_yard.js')" not in line)
PREFIX = PREFIX.replace("if (spec === 'three')", """if (spec === '@dgreenheck/ez-tree') return {url: data(`import {Group,Mesh,BoxGeometry,MeshStandardMaterial} from '${three}';
  export class Tree extends Group {constructor(){super();this.options={};} loadPreset(){} generate(){this.add(new Mesh(new BoxGeometry(1,2,1).translate(0,1,0),new MeshStandardMaterial()));}}`),shortCircuit:true};
  if (spec === 'three')""")
DRIVER = PREFIX + NORMAL_CHECKS + r"""
const THREE = await import(three);
const {groundAt, buildingBase, foundationShape} = await import(file('static/twin/twin_ground.js'));
const {terrainGeometry,terrainSlabGeometry,tintGrade} = await import(file('static/twin/twin_terrain_mesh.js'));
const {buildYard} = await import(file('static/twin/twin_yard.js'));
const near=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-5,`${actual} != ${expected}`);
const {buildTwin,polygon} = await import(file('static/twin/twin_generator.js'));
const {disposeObject,cacheModelMaterials} = await import(file('static/twin/twin_library.js'));
const {parkingPoint} = await import(file('static/twin/twin_hosts.js'));
const {lotPoint} = await import(file('static/twin/live/energy_geometry.js'));
// Validation and rendering must agree, including concave pads and both windings.
for(const {pads,samples} of JSON.parse(readFileSync(process.argv[2])).terrainCases){
  for(const [x,y,h] of samples)near(groundAt({site:{terraces:pads}},x,y),h);
  const pad=pads.at(-1);
  pad.polygon.forEach((a,i)=>{if(pad.edges[i].edge==='sharp')return;const b=pad.polygon[(i+1)%pad.polygon.length];
    for(const t of [.01,.25,.5,.75,.99]){const p=a.map((v,j)=>v+t*(b[j]-v)),dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
      for(const sign of [-1,1])near(groundAt({site:{terraces:pads}},p[0]+sign*dy/length*1e-5,p[1]-sign*dx/length*1e-5),pad.height);}
  });
}
const rect = [[0,0],[10,0],[10,10],[0,10]];
for(const outline of [rect,[...rect].reverse(),[[0,0],[10,0],[10,4],[4,4],[4,10],[0,10]],[[0,10],[4,10],[4,4],[10,4],[10,0],[0,0]]]){
 const hole=[[1,1],[2,1],[2,2],[1,2]];
 for(const holes of [[],[hole],[hole.slice().reverse()]]){
  const slab=terrainSlabGeometry({},outline,'high',0,.3,holes);
  checkBoundaryNormals(slab,outline,{holes,top:.3,label:'hardscape/bed slab'});slab.dispose();
 }
 const foundation=polygon(outline,-2,0);
 checkBoundaryNormals(foundation,outline,{top:0,bottom:-2,label:'building foundation extrusion'});foundation.dispose();
}
// Sharp retaining skirts face the lower surface, for raised and sunken pads
// and either polygon winding. Check geometric face normals (not smoothed normals).
for(const outline of [rect,[...rect].reverse()])for(const height of [-2,2]){
 const shape={site:{terraces:[{polygon:outline,height,blend:0}]}};
 const skirt=terrainGeometry(shape,[[-2,-2],[12,-2],[12,12],[-2,12]],'high',{skirts:true});
 let count=0;
 for(const {normal,centre} of trianglesOf(skirt))if(Math.abs(normal.y)<1e-5){
  const low=groundAt(shape,centre.x+normal.x*.001,-centre.z-normal.z*.001);
  const high=groundAt(shape,centre.x-normal.x*.001,-centre.z+normal.z*.001);
  assert.ok(high>low,'retaining skirt faces lower ground');count++;
 }
 assert.ok(count,'retaining skirts checked');skirt.dispose();
}
console.log('Passed: hardscape/bed boundaries and holes, building foundation caps/sides, raised/sunken retaining skirts');
const modelCache=new Map(), model1=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial()),model2=model1.clone();
model2.material=model1.material.clone();const replaced=model2.material;let released=false;replaced.addEventListener('dispose',()=>released=true);
cacheModelMaterials(model1,'same-asset',modelCache);cacheModelMaterials(model2,'same-asset',modelCache);
assert.equal(model1.material,model2.material);assert.ok(released,'discarded model material is disposed when reusing its compiled predecessor');
disposeObject(model1);model2.geometry.dispose();
const pad = {id:'pad',polygon:rect,height:-1,blend:6,edges:rect.map(()=>({edge:'slope'}))};
const plan = {site:{terraces:[pad],lot:[[-15,-15],[25,-15],[25,25],[-15,25]]},buildings:[],materials:{}};
assert.equal(groundAt(plan,5,5),-1); assert.equal(groundAt(plan,40,5),0);
assert.equal(groundAt(plan,-3,5),-.5);
let last=groundAt(plan,-6,5);
for(let x=-5.75;x<=.25;x+=.25){const h=groundAt(plan,x,5);assert.ok(Math.abs(h-last)<=.1);last=h;}
pad.edges[3].edge='sharp';assert.equal(groundAt(plan,-.001,5),0);assert.equal(groundAt(plan,.001,5),-1);
pad.edges[3].edge='slope';
plan.site.terraces.push({...structuredClone(pad),id:'later',height:2,polygon:[[5,5],[15,5],[15,15],[5,15]]});
assert.equal(groundAt(plan,7,7),2);
const cornerWeight=(1-Math.hypot(3,3)/6)**2*(3-2*(1-Math.hypot(3,3)/6));
near(groundAt(plan,2,2),-1+cornerWeight*3,'later band blends into the earlier interior');
// Two disjoint pad bands overlap; both remain continuous and bounded.
plan.site.terraces[1].polygon=[[15,0],[25,0],[25,10],[15,10]];
last=groundAt(plan,10,5);
for(let x=10.01;x<=15;x+=.01){const h=groundAt(plan,x,5);assert.ok(Math.abs(h-last)<.1);assert.ok(h>=-1&&h<=2);last=h;}
// Grading layers: the zero-height patio grades into the -4 yard beneath it.
const square=(x0,y0,x1,y1)=>[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
const yardPad={id:'yard',polygon:square(0,0,30,30),height:-4,blend:6};
const patio={id:'patio',polygon:square(20,5,40,25),height:0,blend:6};
const layered={site:{terraces:[yardPad,patio]}};
near(groundAt(layered,25,15),0);near(groundAt(layered,5,15),-4);
near(groundAt(layered,14,15),-4);near(groundAt(layered,17,15),-2);
last=-4;
for(let x=14;x<=20;x+=.01){const h=groundAt(layered,x,15);assert.ok(h>=last-1e-9&&h<=0);last=h;}
near(groundAt(layered,-3,15),-2);near(groundAt(layered,-6,15),0);
layered.site.terraces.reverse();near(groundAt(layered,25,15),-4);
layered.site.terraces.reverse();
// A nested pad's band ends on the outer pad, including a sharp step.
const inner={...patio,polygon:square(10,10,20,20)};
layered.site.terraces=[{...yardPad,polygon:square(-20,-20,40,40)},inner];
near(groundAt(layered,7,15),-2);near(groundAt(layered,3,15),-4);near(groundAt(layered,15,15),0);
inner.edges=inner.polygon.map(()=>({edge:'sharp'}));
near(groundAt(layered,9.999,15),-4);near(groundAt(layered,10.001,15),0);
// Mixed sharp/slope corner: continuity on a dense 2-D grid and on rings
// around the endpoint. Only crossings of the sharp segment may jump.
inner.edges=inner.polygon.map((_,i)=>({edge:i===3?'sharp':'slope'}));
near(groundAt(layered,10.0001,9),-4,'taper reaches the sharp outward side continuously');
near(groundAt(layered,10.1,9.99999),0,'taper still meets the sloped boundary at full weight');
const crossesStep=(a,b)=>((a[0]<10-1e-9)!==(b[0]<10-1e-9))&&Math.min(a[1],b[1])>=10-1e-9&&Math.max(a[1],b[1])<=20+1e-9;
for(let x=8;x<=12;x+=.005)for(let y=8;y<=12;y+=.005){
  const a=[x,y];if(Math.hypot(x-10,y-10)<.3)continue;
  for(const b of [[x+.005,y],[x,y+.005]])if(!crossesStep(a,b))
    assert.ok(Math.abs(groundAt(layered,...a)-groundAt(layered,...b))<.2,`corner jump at ${a} -> ${b}`);
}
for(const radius of [.001,.01,.1,.5,1,3,6]){
  let a=[10+radius,10];
  for(let t=.001;t<=Math.PI*2;t+=.001){const b=[10+radius*Math.cos(t),10+radius*Math.sin(t)];
    if(!crossesStep(a,b))assert.ok(Math.abs(groundAt(layered,...a)-groundAt(layered,...b))<.05,'corner ring continuity');a=b;}
}
// The all-slope surface is continuous across interiors, overlapping bands,
// pad boundaries and the transition back to datum, in both orders.
delete inner.edges;
for(const pads of [[yardPad,patio],[patio,yardPad]]){
  layered.site.terraces=pads;
  for(const y of [-3,0,3,5,15,25,30,33]){last=groundAt(layered,-7,y);
    for(let x=-6.99;x<=47;x+=.01){const h=groundAt(layered,x,y);assert.ok(Math.abs(h-last)<.03);last=h;}}
}
layered.site.terraces=[{...yardPad,polygon:square(-20,-20,40,40)},inner];
const bandBuilding={position:[0,0],rotation:0,base:9,foundation:{mode:'auto',offset_ft:.5},
  levels:[{id:'L1',elevation:0,outline:square(6,14,8,16)}]};
near(buildingBase(layered,bandBuilding),groundAt(layered,8,15)+.5);
layered.site.terraces.reverse();near(buildingBase(layered,bandBuilding),-3.5);
// The existing skirt builder must connect the new layered heights.
inner.edges=inner.polygon.map(()=>({edge:'sharp'}));
layered.site.terraces.reverse();
const layeredGeometry=terrainGeometry(layered,square(5,5,25,25),'low',{skirts:true});
const lp=layeredGeometry.attributes.position,li=layeredGeometry.index;
assert.ok(Array.from({length:li.count/3},(_,i)=>[0,1,2].map(j=>lp.getY(li.getX(i*3+j))))
  .some(ys=>Math.min(...ys)<-3.99&&Math.max(...ys)>-.01),'skirt connects patio to earlier yard, not datum');
tintGrade(layeredGeometry,true);
for(let i=0;i<lp.count;i++)near(layeredGeometry.attributes.color.getX(i),.35+.5*(.5+lp.getY(i)/20));
layeredGeometry.dispose();
plan.site.terraces=[{...pad,height:4,blend:0,edges:rect.map(()=>({edge:'sharp'}))}];
const b={id:'b',position:[0,0],rotation:0,base:0,foundation:{mode:'auto',offset_ft:.5,thickness_ft:1},
  levels:[{id:'L1',elevation:0,ceiling:8,outline:[[-2,-2],[12,-2],[12,12],[-2,12]]}],walls:[],rooms:[],roof:{sections:[]},anchors:[],items:[]};
plan.buildings=[b];assert.equal(buildingBase(plan,b),4.5);
const savedPads=plan.site.terraces;
plan.site.terraces=[{...pad,height:7,blend:0,polygon:[[.4,-20],[.6,-20],[.6,20],[.4,20]]}];
assert.equal(buildingBase(plan,b),7.5,'narrow crossing pads are sampled at footprint intersections');
plan.site.terraces=savedPads;
assert.deepEqual({...foundationShape(plan,b),polygon:null},{polygon:null,top:4.5,bottom:0,base:4.5});
assert.equal(lotPoint(b,[0,0,2],plan)[2],6.5);
const parking={host:{ground:true,at:[-5,-5]}};
assert.ok(Math.abs(lotPoint(b,parkingPoint(b,parking,plan,.1,groundAt),plan)[2]-.1)<1e-9);
b.foundation.mode='fixed'; b.base=3;assert.equal(buildingBase(plan,b),3);
delete b.foundation;assert.equal(buildingBase(plan,b),3);b.base=0;b.foundation={mode:'auto',offset_ft:.5,thickness_ft:1};
const geometry=terrainGeometry(plan,plan.site.lot,'low',{skirts:true});
const p=geometry.attributes.position,ix=geometry.index;
assert.ok(p.count>100);assert.ok([...p.array].every(Number.isFinite));
let skirt=false;
for(let i=0;i<ix.count;i+=3){const ys=[0,1,2].map(j=>p.getY(ix.getX(i+j)));if(Math.min(...ys)<.01&&Math.max(...ys)>3.99)skirt=true;}
assert.ok(skirt,'sharp edge gets a vertical face');
const normal=geometry.attributes.normal;assert.ok([...normal.array].every(Number.isFinite));
tintGrade(geometry,false);assert.ok([...geometry.attributes.color.array].every(c=>c===1));tintGrade(geometry,true);
assert.ok([...geometry.attributes.color.array].some(c=>c!==1));geometry.dispose();
const twin=buildTwin(plan,kit,'low',{viewing:true,editableLevel:'b:L1'});await twin.ready;
const low=twin.groups.levels['b:L1'].children.find(g=>g.userData.buildingId==='b');
assert.equal(low.position.y,4.5);
const foundationBounds=new THREE.Box3();
let checkedFoundation=0;
low.traverse(o=>{if(o.isMesh&&o.material.name==='patio_concrete'){
 // Per-piece merging keeps the foundation separate from the level's floor slab.
 o.geometry.computeBoundingBox();
 if(o.geometry.boundingBox.min.y<-1){
  checkBoundaryNormals(o.geometry,foundationShape(plan,b).polygon,{top:0,bottom:-4.5,label:'generated building foundation'});checkedFoundation++;
 }
 foundationBounds.union(o.geometry.boundingBox);
}});
assert.ok(checkedFoundation,'actual foundation mesh checked');
assert.ok(Math.abs(foundationBounds.min.y+4.5)<1e-6&&Math.abs(foundationBounds.max.y)<1e-6,'actual concrete extends from the base down to the lowest ground');
const rebuilt=buildTwin(plan,kit,'low',{viewing:true,reuseMaterials:twin.materials});await rebuilt.ready;
assert.equal(rebuilt.materials.get('patio_concrete'),twin.materials.get('patio_concrete'),'terrain/foundation changes retain the concrete material');
disposeObject(twin.root,{keepMaterials:new Set(rebuilt.materials.values())});disposeObject(rebuilt.root);
// Real yard builder, with deterministic CPU tree geometry instead of EZ-Tree.
plan.site.terraces=[{...pad,height:-4}];plan.buildings=[];
plan.site.planting=[{id:'tree',at:[5,5],preset:'Pine',height:10}];
plan.site.beds=[{polygon:rect}];plan.site.hardscape=[{polygon:[[0,0],[2,0],[2,2],[0,2]]}];
plan.site.fire_pit={at:[5,5],radius:1};
const yard=await buildYard(plan,kit,'high');
// Since v2.499.821 a fire pit is a ring wall: an outer face, an inner face toward the bowl and
// a top. Each faces its own way; none may face into the wall (the inside-out bug).
const fireFaces=[];
yard.group.traverse(o=>{if(!o.isMesh||o.material.name!=='base')return;
 for(const {normal,centre} of trianglesOf(o.geometry))fireFaces.push({normal,centre,r:Math.hypot(centre.x-5,centre.z+5)});});
assert.ok(fireFaces.length,'actual fire pit walls checked');
const sides=fireFaces.filter(f=>Math.abs(f.normal.y)<.5),rMax=Math.max(...sides.map(f=>f.r)),rMin=Math.min(...sides.map(f=>f.r));
assert.ok(rMax-rMin>.05,'the ring has an outer and an inner face');
for(const f of sides){
 const radial=f.normal.dot(new THREE.Vector3(f.centre.x-5,0,f.centre.z+5).normalize());
 if(f.r>(rMax+rMin)/2)assert.ok(radial>0,'fire pit outer wall faces radially outward');
 else assert.ok(radial<0,'fire pit inner wall faces the bowl');
}
const caps=fireFaces.filter(f=>Math.abs(f.normal.y)>=.5),yTop=Math.max(...caps.map(f=>f.centre.y)),yBottom=Math.min(...caps.map(f=>f.centre.y));
for(const f of caps)assert.ok(f.centre.y>(yTop+yBottom)/2?f.normal.y>0:f.normal.y<0,'fire pit top faces up and bottom faces down');
console.log('Passed: fire pit wall outward normals');
const tree=yard.group.children.find(o=>o.constructor.name==='Tree');
assert.equal(new THREE.Box3().setFromObject(tree).min.y,-4);
let terrain;yard.group.traverse(o=>{if(o.userData.terrain)terrain=o;});assert.ok(terrain);
const material=terrain.material;let disposed=false;terrain.geometry.addEventListener('dispose',()=>disposed=true);
const yard2=await buildYard(plan,kit,'high',{materials:yard.group.userData.materials});
const tree2=yard2.group.children.find(o=>o.constructor.name==='Tree');assert.equal(tree2.children[0].material,tree.children[0].material,'tree materials survive terrain edits');
let nextTerrain;yard2.group.traverse(o=>{if(o.userData.terrain)nextTerrain=o;});assert.equal(nextTerrain.material,material);
disposeObject(yard.group,{keepMaterials:new Set(yard2.group.userData.materials.values())});assert.ok(disposed);
disposeObject(yard2.group);
// The merged yard builder applies object transforms on top of terrain height,
// and retains tinted materials across a terrain rebuild without tinting peers.
plan.site.planting=[{id:'scaled-tree',at:[5,5],preset:'Pine',height:10,scale:1.5,scale_axes:[2,1,1],rotation:90,tint:'#224466',elevation:1},
 {id:'plain-tree',at:[8,5],preset:'Pine',height:10}];
const transformed=await buildYard(plan,kit,'high');
const trees=transformed.group.children.filter(o=>o.constructor.name==='Tree');
near(new THREE.Box3().setFromObject(trees[0]).min.y,-3);near(new THREE.Box3().setFromObject(trees[0]).max.y,12);
near(trees[0].rotation.y,Math.PI/2);assert.equal(trees[0].children[0].material.color.getHexString(),'224466');
assert.equal(trees[1].children[0].material.color.getHexString(),'ffffff');
const transformedAgain=await buildYard(plan,kit,'high',{materials:transformed.group.userData.materials});
assert.equal(transformedAgain.group.children.find(o=>o.constructor.name==='Tree').children[0].material,trees[0].children[0].material);
disposeObject(transformed.group,{keepMaterials:new Set(transformedAgain.group.userData.materials.values())});disposeObject(transformedAgain.group);
const treeTexture=new THREE.Texture();let releasedTreeTexture=false;treeTexture.addEventListener('dispose',()=>releasedTreeTexture=true);
trees[0].children[0].material.map=treeTexture;transformed.group.userData.releasePlants();assert.equal(releasedTreeTexture,false,'EZ-Tree module textures remain owned by EZ-Tree');
treeTexture.dispose();
// Cached Low cards keep separate transform wrappers in editor and viewer,
// without rebaking their texture or replacing a tinted material on a rebuild.
const cardTexture=new THREE.Texture(),cardMaterial=new THREE.MeshStandardMaterial({name:'cached card',map:cardTexture});cardMaterial.userData.cardAspect=.5;
const cardCache=new Map([['plant_card:Pine',cardMaterial]]);
const cardYard=await buildYard(plan,kit,'low',{viewing:true,materials:cardCache});
const cardPlants=cardYard.group.children.filter(o=>o.userData.placedPlant);assert.equal(cardPlants.length,2);
near(new THREE.Box3().setFromObject(cardPlants[0]).min.y,-3);near(new THREE.Box3().setFromObject(cardPlants[0]).max.y,13.2);
const tintedCard=cardPlants[0].children[0].material;assert.equal(tintedCard.color.getHexString(),'224466');assert.equal(cardMaterial.color.getHexString(),'ffffff');
const cardYardAgain=await buildYard(plan,kit,'low',{materials:cardCache});
assert.equal(cardYardAgain.group.children.find(o=>o.userData.placedPlant).children[0].material,tintedCard);
cardYard.group.userData.releasePlants(new Set(cardCache.values()));disposeObject(cardYard.group,{keepMaterials:new Set(cardCache.values())});
cardYardAgain.group.userData.releasePlants();disposeObject(cardYardAgain.group);
// Real imported furniture uses its scale/turn/tint and surface offset once,
// both on bare terrain and on an Auto foundation's porch.
const {rememberImport}=await import(file('static/twin/twin_library.js'));
window.location={href:'http://house.test/house/editor'};window.chfBase='../';
globalThis.ProgressEvent=class {constructor(type,values){this.type=type;Object.assign(this,values);}};
const asset='import-'+'3'.repeat(32),vertices=new Float32Array([-1,0,-.1,1,0,-.1,0,2,.1]);
const modelDocument={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],meshes:[{primitives:[{attributes:{POSITION:0}}]}],
 buffers:[{uri:'mesh.bin',byteLength:36}],bufferViews:[{buffer:0,byteLength:36}],accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[-1,0,-.1],max:[1,2,.1]}]};
rememberImport({id:asset,model:'model.gltf',files:{'model.gltf':true,'mesh.bin':true}});
globalThis.fetch=async input=>new Response((typeof input==='string'?input:input.url).includes('mesh.bin')?Buffer.from(vertices.buffer):JSON.stringify(modelDocument),{status:200});
plan.site.planting=[];plan.site.furniture=[{id:'imported-chair',asset,at:[5,5],scale:1.5,rotation:90,tint:'#ffffff',elevation:1}];
const importedYard=await buildYard(plan,kit,'high');
const importedMaterial=[...importedYard.group.userData.materials.entries()].find(([key])=>key.startsWith('model:yard:'))[1];
const boundsFor=yard=>{const bounds=new THREE.Box3();yard.group.traverse(o=>{if(o.isMesh&&o.material===importedMaterial)bounds.expandByObject(o);});return bounds;};
const bounds=boundsFor(importedYard);near(bounds.min.y,-3);near(bounds.max.y,-3+3/.3048);near(bounds.max.z-bounds.min.z,3/.3048);
b.porch={polygon:rect,floor:2};plan.buildings=[b];
const porchYard=await buildYard(plan,kit,'high',{materials:importedYard.group.userData.materials});
near(boundsFor(porchYard).min.y,buildingBase(plan,b)+3);
disposeObject(importedYard.group,{keepMaterials:new Set(porchYard.group.userData.materials.values())});disposeObject(porchYard.group);
console.log('Ground, overlap bands, sharp skirts, foundation, parking, real yard and material reuse passed');
"""


def run():
    from services.twin_terrain import ground_at

    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    lower = {'polygon': [[-20, -20], [30, -20], [30, 30], [-20, 30]], 'height': -4}
    shapes = [([[0, 0], [10, 0], [10, 10], [0, 10]], 3),
              ([[0, 0], [10, 0], [10, 3], [3, 3], [3, 10], [0, 10]], 3)]
    terrain_cases = []
    for polygon, sharp in shapes:
        edges = [{'edge': 'sharp' if i == sharp else 'slope'} for i in range(len(polygon))]
        pads = [lower, {'polygon': polygon, 'height': 0, 'blend': 6, 'edges': edges}]
        samples = [[x/2, y/2, ground_at(pads, [x/2, y/2])] for x in range(-12, 33) for y in range(-12, 33)]
        terrain_cases.append({'pads': pads, 'samples': samples})
        reversed_pad = {**pads[1], 'polygon': polygon[::-1], 'edges': [edges[(len(edges)-2-i) % len(edges)] for i in range(len(edges))]}
        terrain_cases.append({'pads': [lower, reversed_pad], 'samples': samples})
    with tempfile.TemporaryDirectory(prefix='chauffeur_ground_node_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit, 'terrainCases': terrain_cases}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=300)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
