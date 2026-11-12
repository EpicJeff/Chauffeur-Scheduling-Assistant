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

PREFIX = '\n'.join(line for line in BASE.split('const {createDrag, piecesOnMovedJoints}')[0].splitlines()
                   if "if (spec === './twin_yard.js')" not in line)
PREFIX = PREFIX.replace("if (spec === 'three')", """if (spec === '@dgreenheck/ez-tree') return {url: data(`import {Group,Mesh,BoxGeometry,MeshStandardMaterial} from '${three}';
  export class Tree extends Group {constructor(){super();this.options={};} loadPreset(){} generate(){this.add(new Mesh(new BoxGeometry(1,2,1).translate(0,1,0),new MeshStandardMaterial()));}}`),shortCircuit:true};
  if (spec === 'three')""")
DRIVER = PREFIX + r"""
const THREE = await import(three);
const {groundAt, buildingBase, foundationShape} = await import(file('static/twin/twin_ground.js'));
const {terrainGeometry,tintGrade} = await import(file('static/twin/twin_terrain_mesh.js'));
const {buildYard} = await import(file('static/twin/twin_yard.js'));
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const {disposeObject,cacheModelMaterials} = await import(file('static/twin/twin_library.js'));
const {parkingPoint} = await import(file('static/twin/twin_hosts.js'));
const {lotPoint} = await import(file('static/twin/live/energy_geometry.js'));
const rect = [[0,0],[10,0],[10,10],[0,10]];
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
assert.equal(groundAt(plan,7,7),2);assert.equal(groundAt(plan,2,2),-1);
// Two disjoint pad bands overlap; both remain continuous and bounded.
plan.site.terraces[1].polygon=[[15,0],[25,0],[25,10],[15,10]];
last=groundAt(plan,10,5);
for(let x=10.01;x<=15;x+=.01){const h=groundAt(plan,x,5);assert.ok(Math.abs(h-last)<.1);assert.ok(h>=-1&&h<=2);last=h;}
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
const twin=buildTwin(plan,kit,'low',{viewing:true});await twin.ready;
const low=twin.groups.levels['b:L1'].children.find(g=>g.userData.buildingId==='b');
assert.equal(low.position.y,4.5);
const foundationBounds=new THREE.Box3();
low.traverse(o=>{if(o.isMesh&&o.material.name==='patio_concrete'){o.geometry.computeBoundingBox();foundationBounds.union(o.geometry.boundingBox);}});
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
const tree=yard.group.children.find(o=>o.constructor.name==='Tree');
assert.equal(new THREE.Box3().setFromObject(tree).min.y,-4);
let terrain;yard.group.traverse(o=>{if(o.userData.terrain)terrain=o;});assert.ok(terrain);
const material=terrain.material;let disposed=false;terrain.geometry.addEventListener('dispose',()=>disposed=true);
const yard2=await buildYard(plan,kit,'high',{materials:yard.group.userData.materials});
const tree2=yard2.group.children.find(o=>o.constructor.name==='Tree');assert.equal(tree2.children[0].material,tree.children[0].material,'tree materials survive terrain edits');
let nextTerrain;yard2.group.traverse(o=>{if(o.userData.terrain)nextTerrain=o;});assert.equal(nextTerrain.material,material);
disposeObject(yard.group,{keepMaterials:new Set(yard2.group.userData.materials.values())});assert.ok(disposed);
disposeObject(yard2.group);
console.log('Ground, overlap bands, sharp skirts, foundation, parking, real yard and material reuse passed');
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_ground_node_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=300)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
