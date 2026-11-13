"""Real retaining solids/yard, baked receivers and materials under Node."""
import json
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node
from twin_solid_normals import NORMAL_CHECKS

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '\n'.join(line for line in PRELUDE.splitlines() if "if (spec === './twin_yard.js')" not in line)
PREFIX = PREFIX.replace("if (spec === 'three')", """if (spec === '@dgreenheck/ez-tree') return {url:data(`import {Group} from '${three}'; export class Tree extends Group {}`),shortCircuit:true};
  if (spec === 'three')""")
DRIVER = PREFIX + NORMAL_CHECKS + r"""
const THREE=await import(three);
const {createHash}=await import('node:crypto');
const {retainingWallGeometry,retainingWallRole}=await import(file('static/twin/twin_retaining_wall.js'));
const {terrainGeometry,terrainSlabGeometry}=await import(file('static/twin/twin_terrain_mesh.js'));
const {porchPlinthGeometry}=await import(file('static/twin/twin_porch_foundation.js'));
const {groundAt}=await import(file('static/twin/twin_ground.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
const {atlasJob,covered}=await import(file('static/twin/bake/atlas_transport.js'));
const square=(x0,y0,x1,y1)=>[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
const near=(a,b)=>assert.ok(Math.abs(a-b)<2e-5,`${a} != ${b}`);
const pad=(height=3,polygon=square(0,0,4,4))=>({id:'pad',polygon,height,blend:0,edges:polygon.map(()=>({edge:'sharp'}))});
const digest=g=>{const h=createHash('sha256');for(const k of Object.keys(g.attributes).sort())h.update(Buffer.from(g.attributes[k].array.buffer));if(g.index)h.update(Buffer.from(g.index.array.buffer));return h.digest('hex');};
// Each sampled interval is a closed prism, including buried footing/end caps.
const rotated=square(0,0,4,4).map(([x,y])=>[x*Math.cos(.4)-y*Math.sin(.4),x*Math.sin(.4)+y*Math.cos(.4)]);
for(const height of [3,-3,0])for(const polygon of [square(0,0,4,4),square(0,0,4,4).reverse(),rotated,[...rotated].reverse()]){
 const p=pad(height,polygon),plan={site:{terraces:[p]}};
 p.edges[0].wall={material:'stone',thickness_in:12,above_in:6};
 const g=retainingWallGeometry(plan,p,0),a=polygon[0],b=polygon[1],dx=(b[0]-a[0])/4,dy=(b[1]-a[1])/4;
 const uv=g.attributes.uv;
 for(let j=0;j<uv.count;j+=3){
  const area=(uv.getX(j+1)-uv.getX(j))*(uv.getY(j+2)-uv.getY(j))-(uv.getY(j+1)-uv.getY(j))*(uv.getX(j+2)-uv.getX(j));
  assert.ok(Math.abs(area)>1e-7,'all wall faces have physical texture UVs');
 }
 const winding=Math.sign(polygon.reduce((sum,a,i)=>{const b=polygon[(i+1)%polygon.length];return sum+a[0]*b[1]-a[1]*b[0];},0));
 const sign=(height>=0?1:-1)*winding;
 const normal=[-dy*sign,dx*sign];
 for(let i=0;i<4;i++){
  const start=[a[0]+dx*i,a[1]+dy*i],end=[start[0]+dx,start[1]+dy];
  const outline=[start,end,[end[0]+normal[0],end[1]+normal[1]],[start[0]+normal[0],start[1]+normal[1]]];
  const segment=new THREE.BufferGeometry();segment.setAttribute('position',new THREE.Float32BufferAttribute(g.attributes.position.array.slice(i*108,(i+1)*108),3));
  checkBoundaryNormals(segment,outline,{top:Math.max(0,height)+.5,bottom:Math.min(0,height)-.5,label:'retaining prism'});
 }
 const pos=g.attributes.position;
 for(let i=0;i<pos.count;i++){
  const along=(pos.getX(i)-a[0])*normal[0]+(-pos.getZ(i)-a[1])*normal[1];
  assert.ok(along>=-1e-5&&along<=1+1e-5,'body only toward higher ground');
 }
 const mesh=new THREE.Mesh(g,new THREE.MeshBasicMaterial({side:THREE.FrontSide}));
 const middle=[(a[0]+b[0])/2,(a[1]+b[1])/2];
 assert.ok(new THREE.Raycaster(new THREE.Vector3(middle[0]-normal[0]*2,height/2,-middle[1]+normal[1]*2),new THREE.Vector3(normal[0],0,-normal[1])).intersectObject(mesh).length,'front visible from low side');
}
console.log('Passed: raised/sunken body side, both windings, front/back/top/bottom/end normals and FrontSide raycast');
// An underlying blended pad makes the low ground vary along the edge.
const p=pad(3),plan={units:'ft',buildings:[],materials:{},site:{terraces:[{...pad(-4,square(-10,-10,0,10)),blend:8,edges:[]},p]}};
p.edges[0].wall={material:'stone',thickness_in:8,above_in:18};
for(const height of [3,-5,-3]){
 p.height=height;const g=retainingWallGeometry(plan,p,0),pos=g.attributes.position;
 for(let i=0;i<pos.count;i++){
  const x=pos.getX(i),at=Math.max(1e-7,Math.min(4-1e-7,x));
  const sides=[groundAt(plan,at,-1e-5),groundAt(plan,at,1e-5)],h=pos.getY(i);
  assert.ok(Math.abs(h-(Math.min(...sides)-.5))<2e-5||Math.abs(h-(Math.max(...sides)+1.5))<2e-5,`slope sample ${x},${h}`);
 }
 for(const {centre} of trianglesOf(g))if(Math.abs(centre.z)>1e-5){
  const sides=[groundAt(plan,centre.x,-1e-5),groundAt(plan,centre.x,1e-5)];
  assert.ok((sides[1]-sides[0])*(-centre.z)>=-2e-5,'body follows the higher side, including a change along one edge');
 }
}
p.height=3;
// A later layer crosses between grid samples: no diagonal ramp at the step.
plan.site.terraces.push({...pad(-1,square(1.4,-2,2.6,2)),id:'crossing'});
const layered=retainingWallGeometry(plan,p,0),heights=new Map();
for(const {vertices} of trianglesOf(layered))for(const v of vertices){const key=v.x.toFixed(5);if(!heights.has(key))heights.set(key,new Set());heights.get(key).add(v.y.toFixed(4));}
assert.ok(heights.get('1.40000').size>=3&&heights.get('2.60000').size>=3,'one-sided layer cuts');
// Capture-free golden against the pre-feature earth skirt, including buffers/index.
const bare={site:{terraces:[pad(3)]}},outline=square(-1,-1,5,5);
const skirt=terrainGeometry(bare,outline,'high',{skirts:true});
const slabBefore=digest(terrainSlabGeometry(bare,outline,'high',-.1,.3));
const porch={polygon:outline,foundation:{lip_in:0}};
const plinthBefore=digest(porchPlinthGeometry(bare,{},porch,5,0));
// Captured and compared buffer-for-buffer against HEAD's pre-wall implementation.
assert.equal(digest(skirt),'a5d94b470ae253f460f825dd55b067ca8c05614eb99c14dbf8eb83c3963c424b');
bare.site.terraces[0].edges[0].wall={material:'stone'};
const without=terrainGeometry(bare,outline,'high',{skirts:true});
assert.equal(digest(terrainSlabGeometry(bare,outline,'high',-.1,.3)),slabBefore,'wall does not open a gap in draped slabs');
assert.equal(digest(porchPlinthGeometry(bare,{},porch,5,0)),plinthBefore,'wall does not open a plinth underside');
assert.equal(trianglesOf(skirt).filter(t=>Math.abs(t.normal.y)<1e-5).length-trianglesOf(without).filter(t=>Math.abs(t.normal.y)<1e-5).length,8,'only wall edge loses its earth skirt');
console.log('Passed: sloped/layered ground, footing, above-ground height, legacy skirt golden and per-edge skirt suppression');
// Actual yard entry point: walls exist even without a lot and receive baked UVs.
const yardPlan={units:'ft',buildings:[],materials:{},site:{terraces:[pad(3)]}},wp=yardPlan.site.terraces[0];
const options={room:{density:1,page:256,gutter:2}};
const plain=await buildYard(yardPlan,input.kit,'low'),emptyKey=atlasJob(plain.group,yardPlan,options).cacheKey;
wp.edges[0].wall={material:'stone',thickness_in:8,above_in:0};
let prior=await buildYard(yardPlan,input.kit,'low');
let key=atlasJob(prior.group,yardPlan,options).cacheKey;assert.notEqual(key,emptyKey);
for(const [property,value] of [['thickness_in',12],['above_in',6],['material','brick']]){
 wp.edges[0].wall[property]=value;const next=await buildYard(yardPlan,input.kit,'low',{materials:prior.group.userData.materials});
 const nextKey=atlasJob(next.group,yardPlan,options).cacheKey;assert.notEqual(key,nextKey);key=nextKey;prior=next;
}
for(const material of ['stone','block','concrete','brick','timber','stone']){
 wp.edges[0].wall.material=material;
 const next=await buildYard(yardPlan,input.kit,'low',{materials:prior.group.userData.materials});
 assert.ok(next.group.children.some(o=>o.material?.name===retainingWallRole(material)));
 assert.ok(next.group.children.every(o=>o.receiveShadow&&covered(next.group).includes(o)));
 const atlas=buildAtlas(next.group,yardPlan,options);assert.ok(next.group.children.every(o=>o.geometry.attributes.uv3));
 const high=await buildYard(yardPlan,input.kit,'high');assert.equal(buildAtlas(high.group,yardPlan,options).key,atlas.key);
 const cache=next.group.userData.materials,again=await buildYard(yardPlan,input.kit,'low',{materials:cache});
 assert.equal(again.group.userData.materials.size,cache.size);for(const [k,v] of cache)assert.equal(again.group.userData.materials.get(k),v);
 prior=next;
}
for(const role of ['retaining_block','retaining_timber'])assert.ok(input.manifest[input.kit.materials[role].asset],'new roles use only existing vetted assets');
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const host=new Element();host.closest=selector=>selector==='.editor-shell'?host:null;
const view=await mountTwin(host,{plan:yardPlan,kit:input.kit,tier:'low',preserveCamera:true,bake:false});
// The yard batches static geometry by role, so inspect its live merged receiver.
const wallMesh=()=>{let found;view.groups.site.traverse(o=>{if(o.isMesh&&o.material.name==='base')found=o;});return found;};
assert.ok(view.ready&&wallMesh(),'wall reaches the actual scene entry point');
const wallMaterial=wallMesh().material,edit=structuredClone(yardPlan);edit.site.terraces[0].edges[0].wall.thickness_in=16;
await view.rebuild(edit);assert.ok(wallMesh());assert.equal(wallMesh().material,wallMaterial,'scene rebuild reuses the role material');
wallMesh().geometry.computeBoundingBox();near(wallMesh().geometry.boundingBox.min.z,-16/12);
view.dispose();
console.log('Passed: actual yard, all material roles, material reuse, baked receivers/UVs, add/edit bake invalidation and tier equality');
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    args = {'root': ROOT.as_posix(), 'kit': kit,
            'manifest': json.loads((ROOT / 'twin_library/manifest.json').read_text(encoding='utf-8'))}
    code, output = run_node(DRIVER, args)
    print(output)
    sys.exit(code or 0)
