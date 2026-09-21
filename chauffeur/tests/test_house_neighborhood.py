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
assert.equal(n.stats().lots,5);assert.equal(n.stats().batches,5);
const mesh=n.group.children[0],material=mesh.material;
let disposed=0;material.addEventListener('dispose',()=>disposed++);
n.update(new T.Vector3(0,25,80),new T.Vector3(0,0,0),true);
assert(n.stats().visibleLots<5);
n.update(new T.Vector3(0,25,80),new T.Vector3(0,0,0),false);
assert.equal(n.group.visible,false);
n.dispose();assert.equal(n.group.children.length,0);assert.equal(disposed,1);
'''
        subprocess.run(['node','-e',script,str((base/'vendor/three.min.js').resolve()),str((base/'house_neighborhood.js').resolve()),json.dumps(hf.CANONICAL)],check=True)

    def test_plan_is_stable_valid_and_does_not_modify_canonical(self):
        path=Path(__file__).parents[1]/'static/house_neighborhood.js'
        script="require(process.argv[1]); const a=JSON.parse(process.argv[2]); const before=JSON.stringify(a); const p=ChauffeurNeighborhood.plan(a); if(JSON.stringify(a)!==before)throw Error('mutated'); if(JSON.stringify(p)!==JSON.stringify(ChauffeurNeighborhood.plan(a)))throw Error('unstable'); console.log(JSON.stringify(p));"
        rows=json.loads(subprocess.check_output(['node','-e',script,str(path.resolve()),json.dumps(hf.CANONICAL)],text=True))
        self.assertEqual(len(rows),5)
        self.assertEqual(len({(r['x'],r['z']) for r in rows}),5)
        for r in rows:
            self.assertEqual(hf.validate_block_model(r['spec']),[])
            self.assertGreater(abs(r['x'])+abs(r['z']),45)
            self.assertEqual(hf.validate_block_model(hf.normalize(r['spec'])[0]),[])
        self.assertGreater(len({r['spec']['blocks']['main']['body'] for r in rows}),3)


if __name__=='__main__':unittest.main()
