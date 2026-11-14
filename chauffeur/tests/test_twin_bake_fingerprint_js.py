"""Actual yard, foundation and imported-model bake identity across render tiers.

CPU Node proof only; the live bake suite owns GPU pixel checks.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const THREE = await import(three);
const {buildTwin, mergeStatic} = await import(file('static/twin/twin_generator.js'));
const {buildYard} = await import(file('static/twin/twin_yard.js'));
const {rememberImport} = await import(file('static/twin/twin_library.js'));
const {buildAtlas} = await import(file('static/twin/bake/atlas.js'));
const {atlasJob, covered, packAtlas, applyAtlas, geometryFrom} = await import(file('static/twin/bake/atlas_transport.js'));
const {bakeLayout} = await import(file('static/twin/bake/baker.js'));
window.location={href:'http://house.test/house/twin'}; window.chfBase='../';
globalThis.ProgressEvent=class {constructor(type,values){this.type=type;Object.assign(this,values);}};
const asset='import-'+'b'.repeat(32), vertices=new Float32Array([-1,0,-1,1,0,-1,0,2,1]);
const doc={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],
 meshes:[{primitives:[{attributes:{POSITION:0}}]}],buffers:[{uri:'mesh.bin',byteLength:36}],
 bufferViews:[{buffer:0,byteLength:36}],accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[-1,0,-1],max:[1,2,1]}]};
rememberImport({id:asset,model:'model.gltf',files:{'model.gltf':true,'mesh.bin':true},triangles:400000,size:[2,2,2]});
const requests=[];
globalThis.fetch=async input=>{
 const url=typeof input==='string'?input:input.url; requests.push(url);
 return new Response(url.includes('mesh.bin')?Buffer.from(vertices.buffer):JSON.stringify(doc),{status:200});
};
const rect=[[0,0],[12,0],[12,12],[0,12]];
const building={id:'house',position:[0,0],base:0,foundation:{mode:'auto',offset_ft:.5,thickness_ft:1},
 levels:[{id:'L1',elevation:0,ceiling:8,outline:rect}],
 walls:[{id:'wall',level:'L1',from:[0,0],to:[12,0],thickness:.5,height:8}],
 rooms:[{id:'room',level:'L1',polygon:rect}],openings:[],roof:{sections:[]},anchors:[],items:[]};
const plan={generatorVersion:'test',materials:{},buildings:[building],site:{
 lot:[[-5,-5],[17,-5],[17,17],[-5,17]],
 terraces:[{id:'pad',polygon:rect,height:-2,blend:3,edges:rect.map(()=>({edge:'slope'}))}],
 hardscape:[{id:'patio',polygon:[[0,-4],[8,-4],[8,-1],[0,-1]]}],
 furniture:[{id:'car',asset,at:[6,6],scale:1,rotation:0}]}};
const options={room:{density:1,page:256,gutter:2}};
const lamp={device:'lamp',building:'house',level:'L1',room:'room',at:[6,6,6]};
async function scene(tier, source=plan) {
 // Only the viewer bakes (ruling B15): build the scene the way the viewer does. The editor
 // path always loads the full model (car-models LOD rule) and never bakes.
 const house=buildTwin(source,kit,tier,{viewing:true});await house.ready;
 const yard=await buildYard(source,kit,tier,{viewing:true});house.root.add(yard.group);
 house.root.updateMatrixWorld(true);return house.root;
}
const low=await scene('low'), before=requests.length;
assert.equal(before,0,'Low uses its heavy stand-in without fetching the model');
const high=await scene('high');assert.ok(requests.length>before,'High loads the full import');
const lowTriangles=low.getObjectByName('yard').children.reduce((n,o)=>n+(o.geometry?.attributes.position.count||0),0);
const highTriangles=high.getObjectByName('yard').children.reduce((n,o)=>n+(o.geometry?.attributes.position.count||0),0);
assert.notEqual(lowTriangles,highTriangles,'the fixture really has different render buffers');
assert.equal(atlasJob(low,plan,options).cacheKey,atlasJob(high,plan,options).cacheKey,'tier-independent input fingerprint');
const a=buildAtlas(low,plan,options), b=buildAtlas(high,plan,options);
assert.equal(a.key,b.key,'the panel polls exactly the desk bake key');
// Graded terrain bakes too (user, 2026-11-13). Its grid is finer on High than on Low, so its
// per-vertex arrays differ by tier; its charts (IDs, tiles, rects) and the UV at any shared
// ground point do not. Every other receiver is compared vertex for vertex, as before.
const field=root=>covered(root).find(m=>m.geometry.userData.bakeHeightfield);
assert.ok(field(low)&&field(high),'graded terrain is a bake receiver on both tiers');
const mapping=atlas=>({rooms:atlas.room.rooms,charts:atlas.room.charts.map(({mesh,faces,...c})=>c.heightfield?c:{...c,faces}),
 attributes:covered(atlas===a?low:high).filter(m=>!m.geometry.userData.bakeHeightfield).map(m=>Object.fromEntries(['uv3','lmRoom','lmLightPage'].map(k=>[k,[...m.geometry.attributes[k].array]])))});
assert.deepEqual(mapping(a),mapping(b),'identical chart IDs, packing and every lightmap UV');
const groundUV=mesh=>{const p=mesh.geometry.attributes.position,u=mesh.geometry.attributes.uv3,r=mesh.geometry.attributes.lmRoom,m=new Map();
 for(let i=0;i<p.count;i++)if(r.getX(i)>=0)m.set([p.getX(i),p.getY(i),p.getZ(i)].map(v=>v.toFixed(3)).join(),[u.getX(i),u.getY(i)]);return m;};
const lowUV=groundUV(field(low)),highUV=groundUV(field(high));let shared=0;
for(const [key,uv] of lowUV) {const other=highUV.get(key);if(!other)continue;shared++;
 assert.ok(Math.abs(uv[0]-other[0])<1e-6&&Math.abs(uv[1]-other[1])<1e-6,`ground point ${key} maps to the same lightmap texel on both tiers`);}
assert.ok(shared>10,`shared ground points compared: ${shared}`);
// A heightfield chart's face list indexes its own tier's grid; keys, addresses and ownership do not.
const layoutData=atlas=>JSON.parse(JSON.stringify(bakeLayout(atlas,options,[lamp]),(key,value)=>key==='mesh'?undefined:
 value&&value.heightfield&&value.faces?{...value,faces:undefined}:value));
assert.deepEqual(layoutData(a),layoutData(b),'same light keys, addresses and sticky ownership');
const packed=packAtlas(b,covered(high)), freshLow=await scene('low');
const applied=applyAtlas(packed,freshLow,options);
assert.equal(applied.key,b.key,'a High worker/cache result applies on Low');
assert.deepEqual(bakeLayout(applied,options,[lamp]).entries,bakeLayout(b,options,[lamp]).entries);
// Yard reuse (v2.499.848) keeps meshes whose geometry an earlier bake replaced. Re-deriving the
// atlas from them, the worker's way, keeps the key: no rebake after an unrelated edit.
{const job=atlasJob(freshLow,plan,options),again=new THREE.Group();
 for(const m of job.meshes){const mesh=new THREE.Mesh(geometryFrom(m.geometry),new THREE.MeshStandardMaterial({name:m.name}));
  mesh.matrixAutoUpdate=false;mesh.matrix.fromArray(m.matrix);mesh.userData={merged:true,buildingId:m.buildingId};again.add(mesh);}
 assert.equal(buildAtlas(again,plan,options).key,b.key,'an already-applied scene derives the same atlas key');}
const changed=structuredClone(plan);changed.buildings[0].walls[0].to[0]=10;
const {transformShape}=await import(file('static/twin/editor/site_shapes.js'));
const rotated=structuredClone(plan);Object.assign(rotated.site.hardscape[0],transformShape(rotated.site.hardscape[0],{rotation:90}));
assert.notEqual(atlasJob(await scene('low',rotated),rotated,options).cacheKey,atlasJob(low,plan,options).cacheKey,'polygon rotation changes authored worker bake key');
assert.notEqual(buildAtlas(await scene('high',rotated),rotated,options).key,b.key,'polygon rotation changes stored atlas key');
const drawn=structuredClone(plan);drawn.site.hardscape.push({id:'drawn-walk',kind:'path',points:[[-3,2],[-3,8],[3,10]],width:3,corner:'rounded',material:'paving',edging:'curb'});
const drawnLow=await scene('low',drawn),drawnHigh=await scene('high',drawn);
assert.notEqual(atlasJob(drawnLow,drawn,options).cacheKey,atlasJob(low,plan,options).cacheKey,'adding a path changes the worker bake key');
const pathLow=buildAtlas(drawnLow,drawn,options),pathHigh=buildAtlas(drawnHigh,drawn,options);
assert.notEqual(pathLow.key,b.key,'adding a path changes the stored atlas key');assert.equal(pathLow.key,pathHigh.key,'path receivers use one tier-independent atlas');
assert.ok(covered(drawnLow).reduce((n,m)=>n+m.geometry.attributes.position.count,0)>covered(low).reduce((n,m)=>n+m.geometry.attributes.position.count,0),'path and curb are baked receivers');
assert.notEqual(buildAtlas(await scene('high',changed),changed,options).key,b.key,'authored wall geometry invalidates');
assert.notEqual(bakeLayout(b,options,[{...lamp,at:[7,6,6]}]).entries.lamp.key,
 bakeLayout(b,options,[lamp]).entries.lamp.key,'moving the light invalidates its bake');
for(const mutate of [p=>p.site.terraces[0].height--,p=>p.site.furniture[0].rotation=90,
 p=>p.site.furniture[0].tint='#224466',p=>p.materials.wall={color:'#224466'}]) {
 const p=structuredClone(plan);mutate(p);
 assert.notEqual(buildAtlas(await scene('high',p),p,options).key,b.key,'authored terrain, object and material edits invalidate');
}
const lodPlan=structuredClone(plan);lodPlan.tier='low';lodPlan.site.furniture[0].lod=2;
assert.equal(atlasJob(await scene('low',lodPlan),lodPlan,options).cacheKey,atlasJob(await scene('high'),plan,options).cacheKey,'LOD choice is render detail');
assert.equal(buildAtlas(await scene('low',lodPlan),lodPlan,options).key,b.key,'LOD choice never changes the stored key');
// Per-part yard reuse: a fence edit rebuilds only the fence, so every terrain chart keeps
// its key (the ground's bake stays fresh) and only the fence charts change.
{
 const fenced=structuredClone(plan);fenced.site.fence=[{id:'fence',polyline:[[-4,-4],[-4,10]],height:5}];
 const house=buildTwin(fenced,kit,'high',{viewing:true});await house.ready;
 const first=await buildYard(fenced,kit,'high',{viewing:true});house.root.add(first.group);house.root.updateMatrixWorld(true);
 const partOf=mesh=>{for(let o=mesh;o;o=o.parent)if(o.userData.yardPart)return o.userData.yardPart;return null;};
 const keysOf=(root,p,part)=>buildAtlas(root,p,options).room.charts.filter(c=>partOf(c.mesh)===part).map(c=>c.key).sort();
 const terrainBefore=keysOf(house.root,fenced,'terrain'),fenceBefore=keysOf(house.root,fenced,'fences');
 assert.ok(terrainBefore.length>0&&fenceBefore.length>0,'the fixture bakes ground and fence charts');
 const moved=structuredClone(fenced);moved.site.fence[0].polyline[1][1]=12;
 const second=await buildYard(moved,kit,'high',{viewing:true,previous:first.group});second.group.userData.adoptParts();
 assert.deepEqual(second.group.userData.yardRebuiltParts,['fences'],'only the fence part rebuilds');
 house.root.remove(first.group);house.root.add(second.group);house.root.updateMatrixWorld(true);
 assert.deepEqual(keysOf(house.root,moved,'terrain'),terrainBefore,'a fence edit leaves every terrain chart key as it was');
 assert.notDeepEqual(keysOf(house.root,moved,'fences'),fenceBefore,'the fence charts change');
}
// Excluded geometry stays excluded after repeated static merges, even with a shared material.
const mixed=new THREE.Group(), material=new THREE.MeshStandardMaterial();
const excluded=new THREE.Mesh(new THREE.BoxGeometry(),material);excluded.geometry.userData.bakeExcluded=true;
mixed.add(excluded,new THREE.Mesh(new THREE.BoxGeometry(),material));mergeStatic(mixed);mergeStatic(mixed);
assert.equal(covered(mixed).length,1,'merging cannot mix render-only and baked receivers');
console.log('Passed: tier fingerprint, key, UVs, slots, cache application, authored invalidation and LOD invariance');
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_bake_fingerprint_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True,
                                text=True, timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
