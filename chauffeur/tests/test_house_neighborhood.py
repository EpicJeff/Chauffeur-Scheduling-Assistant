"""Deterministic valid facade neighbors; no provider or household dependencies."""
import json
import subprocess
import unittest
from pathlib import Path
import harness
from services import house_facade as hf


class NeighborhoodTests(unittest.TestCase):
    def test_builder_visibility_and_disposal(self):
        base=Path(__file__).parents[1]/'static'
        script=r'''
const T=require(process.argv[1]);require(process.argv[2]);
const spec=JSON.parse(process.argv[3]),assert=require('node:assert/strict');
const envelopes={main:{west:-7.15,east:14.65,north:-6.1,south:14.55,eave:5.6},garage:{west:-18.2,east:-7.15,north:-6.1,south:10.1,eave:5.6}};
const palette={body:{white:0xffffff},roof:{charcoal:0x333333},frame:{white:0xffffff},trim:{white:0xffffff},door:{wood:0x885522}};
const n=ChauffeurNeighborhood.build(T,spec,envelopes,palette);
assert.equal(n.stats().lots,48);assert.equal(n.stats().nearLots,8);assert.equal(n.stats().farLots,40);
assert(n.stats().batches<=12);assert(n.stats().triangles<90000);
assert(n.stats().placements.some(p=>p.z<0&&p.detail==='near'));
const materials=new Set(n.group.children.map(m=>m.material));
let disposed=0;materials.forEach(m=>m.addEventListener('dispose',()=>disposed++));
let near=0,far=0;
ChauffeurNeighborhood.exterior(ChauffeurNeighborhood.plan(spec)[16].spec,envelopes,palette,()=>near++,true);
ChauffeurNeighborhood.exterior(ChauffeurNeighborhood.plan(spec)[16].spec,envelopes,palette,()=>far++,false);
assert(near>far);
assert(n.group.children.every(m=>{const hits=[];m.raycast(null,hits);return hits.length===0;}));
n.update(new T.Vector3(0,25,80),new T.Vector3(0,0,0),true);
assert(n.stats().visibleLots<48);
n.update(new T.Vector3(0,25,80),new T.Vector3(0,0,0),false);
assert.equal(n.group.visible,false);
n.dispose();assert.equal(n.group.children.length,0);assert.equal(disposed,materials.size);
'''
        subprocess.run(['node','-e',script,str((base/'vendor/three.min.js').resolve()),str((base/'house_neighborhood.js').resolve()),json.dumps(hf.CANONICAL)],check=True)

    def test_capture_preserves_finished_geometry_and_owns_only_copies(self):
        base=Path(__file__).parents[1]/'static'
        script=r'''
const T=require(process.argv[1]);require(process.argv[2]);const assert=require('node:assert/strict');
const root=new T.Group();root.position.set(12,0,4);
const geo=new T.BoxGeometry(2,3,4),map=new T.Texture(),material=new T.MeshStandardMaterial({color:0x88aa66,map});
const first=new T.Mesh(geo,material);first.position.x=2;first.scale.x=-1;root.add(first);
const copies=new T.InstancedMesh(geo,material,2);copies.setMatrixAt(0,new T.Matrix4().makeTranslation(5,0,0));copies.setMatrixAt(1,new T.Matrix4().makeTranslation(8,0,0));root.add(copies);
const excluded=new T.Group();excluded.add(new T.Mesh(geo,material));root.add(excluded);
const cutaway=new T.Mesh(geo,material);cutaway.userData.maskOnly='|kitchen|';root.add(cutaway);
const label=new T.Mesh(geo,material);label.userData.noMirror=true;root.add(label);
let sourceDisposals=0;[geo,map,material].forEach(r=>r.addEventListener('dispose',()=>sourceDisposals++));
const kit=ChauffeurNeighborhood.captureExterior(T,root,[excluded]);
assert.equal(kit.sourceMeshes,2);assert.equal(kit.sourceInstances,3);assert.equal(kit.triangles,36);assert.equal(kit.parts.length,1);
const part=kit.parts[0];assert.notEqual(part.material,material);assert.equal(part.material.map,map);
part.geometry.computeBoundingBox();assert.equal(part.geometry.boundingBox.min.x,1);assert.equal(part.geometry.boundingBox.max.x,9);
const positions=part.geometry.attributes.position,normals=part.geometry.attributes.normal;
for(let i=0;i<positions.count;i+=3){const a=new T.Vector3().fromBufferAttribute(positions,i),b=new T.Vector3().fromBufferAttribute(positions,i+1),c=new T.Vector3().fromBufferAttribute(positions,i+2);assert(b.sub(a).cross(c.sub(a)).dot(new T.Vector3().fromBufferAttribute(normals,i))>0);}
const street=new T.Group(),streetMesh=new T.Mesh(new T.BoxGeometry(4,.1,4),material);streetMesh.position.z=30;street.add(streetMesh);
const roadKit=ChauffeurNeighborhood.captureExterior(T,street,[],{front:26});assert.equal(roadKit.triangles,0);roadKit.dispose();
assert.equal(part.geometry.attributes.uv.count,108);assert(Math.abs(part.geometry.attributes.color.getX(0)-material.color.r)<1e-6);
first.position.x=90;material.color.setHex(0xff0000);assert.equal(part.geometry.boundingBox.min.x,1);
let copiesDisposed=0;[part.geometry,part.material].forEach(r=>r.addEventListener('dispose',()=>copiesDisposed++));
const spec=JSON.parse(process.argv[3]);
const envelopes={main:{west:-7.15,east:14.65,north:-6.1,south:14.55,eave:5.6},garage:{west:-18.2,east:-7.15,north:-6.1,south:10.1,eave:5.6}};
const palette={body:{white:0xffffff},roof:{charcoal:0x333333},frame:{white:0xffffff},trim:{white:0xffffff},door:{wood:0x885522}};
const n=ChauffeurNeighborhood.build(T,spec,envelopes,palette,null,kit);
assert.equal(n.stats().nearSource,'active-exterior');
const detailed=n.group.children.filter(m=>m.userData.nearExterior);assert.equal(detailed.reduce((sum,m)=>sum+m.count,0),8);
const transform=new T.Matrix4();detailed.forEach(m=>{for(let i=0;i<m.count;i++){m.getMatrixAt(i,transform);assert(transform.determinant()>0);}});
assert(n.stats().placements.filter(l=>l.detail==='near').every(l=>l.style==='matching-home'));
n.dispose();assert.equal(copiesDisposed,2);assert.equal(sourceDisposals,0);
'''
        subprocess.run(['node','-e',script,str((base/'vendor/three.min.js').resolve()),str((base/'house_neighborhood.js').resolve()),json.dumps(hf.CANONICAL)],check=True)

    def test_plan_is_stable_valid_and_does_not_modify_canonical(self):
        path=Path(__file__).parents[1]/'static/house_neighborhood.js'
        script="require(process.argv[1]); const a=JSON.parse(process.argv[2]); const before=JSON.stringify(a); const p=ChauffeurNeighborhood.plan(a); if(JSON.stringify(a)!==before)throw Error('mutated'); if(JSON.stringify(p)!==JSON.stringify(ChauffeurNeighborhood.plan(a)))throw Error('unstable'); console.log(JSON.stringify(p));"
        rows=json.loads(subprocess.check_output(['node','-e',script,str(path.resolve()),json.dumps(hf.CANONICAL)],text=True))
        self.assertEqual(len(rows),48)
        self.assertEqual(len({(r['x'],r['z']) for r in rows}),48)
        self.assertEqual(sum(r['detail']=='near' for r in rows),8)
        self.assertEqual({r['style'] for r in rows if r['detail']=='near'}, {'farmhouse','craftsman','modern','ranch'})
        self.assertTrue(any(r['z']<0 and r['detail']=='near' for r in rows))
        for r in rows:
            self.assertEqual(hf.validate_block_model(r['spec']),[])
            self.assertGreater(abs(r['x'])+abs(r['z']),45)
            self.assertEqual(hf.validate_block_model(hf.normalize(r['spec'])[0]),[])
        self.assertGreater(len({r['spec']['blocks']['main']['body'] for r in rows}),3)


if __name__=='__main__':unittest.main()
