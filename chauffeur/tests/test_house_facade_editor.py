"""Execute the actual editor methods: selecting one slot must not move spans."""
import subprocess
from pathlib import Path


def main():
    template = (Path(__file__).parents[1] / 'templates/config.html').read_text(encoding='utf-8')
    methods = template[template.index('facadeEntry(layer,'):template.index('async facadePreview(spec)')]
    script = "const assert = require('node:assert/strict');\nconst editor = {" + methods + "};\n" + r'''
const clone = x => JSON.parse(JSON.stringify(x));
const roof = {form:'gable', ridge:'x', pitch_deg:22.5};
editor.facadeDraft = {
  blocks:{main:{roof},garage:{roof}},
  upper:[{slot:9,span:4,roof}],
  ground:[{slot:9,span:4,kind:'window',size:'standard',story:1},
          {slot:9,span:4,kind:'porch',type:'covered',roof:'gable'}],
  roof:[{slot:9,span:4,kind:'shed',window:false}]
};
editor.facadeSlots = Array.from({length:18},(_,i)=>({i,face:i<6?'garage_block':'main'}));
editor.facadePreview = () => {};
const before = clone(editor.facadeDraft);
editor.facadeCellSelect(11);
assert.equal(editor.facadeSlot,11,'select the clicked slot inside an upper');
editor.facadeCellApply();
assert.deepEqual(editor.facadeDraft,before,'selection alone changes no layer');
editor.facadeCell.ground.size = 'small';
editor.facadeCellApply();
assert.deepEqual(editor.facadeDraft.upper,before.upper,'ground edits preserve upper anchor');
assert.deepEqual(editor.facadeDraft.roof,before.roof,'ground edits preserve roof span');
assert.deepEqual(editor.facadeDraft.ground.filter(e=>e.kind==='porch'),before.ground.filter(e=>e.kind==='porch'));
assert.deepEqual(editor.facadeDraft.ground.filter(e=>e.kind==='window').map(e=>[e.slot,e.span,e.size]),
                 [[9,2,'standard'],[12,1,'standard'],[11,1,'small']]);
editor.facadeCell.upper.roof.pitch_deg = 30;
editor.facadeCellApply();
assert.equal(editor.facadeDraft.upper[0].slot,9,'upper edit retains its own anchor');
assert.equal(editor.facadeDraft.upper[0].span,4);
editor.facadeCell.porch.roof = 'mixed';
editor.facadeCell.porch.gable_offset = 1;
editor.facadeCell.porch.gable_span = 2;
editor.facadeCellApply();
const porch = editor.facadeDraft.ground.find(e=>e.kind==='porch');
assert.equal(porch.slot,9,'porch edit retains its own anchor');
assert.equal(porch.gable_offset,1);
assert.equal(porch.gable_span,2);
editor.facadeCell.roof.kind = 'shed_dormer';
editor.facadeCellApply();
assert.equal(editor.facadeDraft.roof[0].kind,'shed');
assert.equal(editor.facadeDraft.roof[0].window,true,'explicit shed dormer includes a window');
editor.facadeLoadCell();
assert.equal(editor.facadeCell.roof.kind,'shed_dormer','saved shed dormer reopens as the same choice');
editor.facadeCell.roof.kind = 'shed';
editor.facadeCellApply();
assert.equal(editor.facadeDraft.roof[0].window,false,'plain shed roof removes the window');
editor.facadeDraft.finishes = [{slot:9,span:4,story:1,cladding:'brick'}, {slot:9,span:4,story:2,body:'stone_grey'}];
editor.facadeCellStory = 1;
editor.facadeLoadCell();
editor.facadeCell.finish.body = 'brick_red';
editor.facadeCellApply();
assert.deepEqual(editor.facadeDraft.finishes.filter(f=>f.story===1), [
 {slot:9,span:2,story:1,cladding:'brick'}, {slot:12,span:1,story:1,cladding:'brick'},
 {slot:11,span:1,story:1,cladding:'brick',body:'brick_red'}]);
assert.equal(editor.facadeDraft.finishes.find(f=>f.story===2).span,4,'other story untouched');
editor.facadeCell.finish.cladding = ''; editor.facadeCell.finish.body = '';
editor.facadeCellApply();
assert.ok(!editor.facadeDraft.finishes.some(f=>f.story===1 && f.slot===11),'inherit removes local override only');
editor.facadeSetStoryFinish('main',2,'cladding','shingle');
editor.facadeSetStoryFinish('main',2,'body','brick_red');
editor.facadeSetStoryFinish('main',2,'cladding','');
assert.equal(editor.facadeStoryFinish('main',2,'body'),'brick_red','clearing material preserves colour');
assert.equal(editor.facadeStoryFinish('main',2,'cladding'),'');
// Choose every porch slot even when editing a continuation cell.
editor.facadeCellSelect(11);
assert.deepEqual(editor.facadePorchGableSlots(), [9,10,11,12]);
for (const start of [12,10,9]) {
  editor.facadePorchGableStart(String(start));
  editor.facadeCell.porch.gable_span = 2;
  editor.facadeCellApply();
  const p = editor.facadeDraft.ground.find(e=>e.kind==='porch');
  assert.equal(p.slot,9,'moving gable never moves porch');
  assert.equal(p.gable_offset,start-9,'absolute starting slot maps to saved offset');
  assert.equal(p.gable_span,Math.min(2,13-start),'span stays inside porch');
  editor.facadeLoadCell();
  assert.equal(editor._origPorchSlot+editor.facadeCell.porch.gable_offset,start,'start survives reload');
}
editor.facadePorchGableStart('12');
editor.facadeCell.porch.span = 2;
editor.facadeCellApply();
assert.equal(editor.facadeCell.porch.gable_offset,1,'shortening porch keeps gable inside');
assert.equal(editor.facadeCell.porch.gable_span,1);
editor.facadeDraft.ground = [{slot:7,span:2,kind:'window',count:3,size:'standard',story:1,shutters:false},
 {slot:10,span:3,kind:'door',count:2}];
editor.facadeCellSelect(8);
editor.facadeCell.ground.shutters = true;
editor.facadeCellApply();
assert.deepEqual(editor.facadeDraft.ground.find(g=>g.kind==='window'),
 {slot:7,span:2,kind:'window',count:3,size:'standard',story:1,shutters:true});
editor.facadeCellSelect(11);
editor.facadeCell.ground.count = 1;
editor.facadeCellApply();
assert.deepEqual(editor.facadeDraft.ground.find(g=>g.kind==='door'),{slot:10,span:3,kind:'door'});
editor.facadeCell.ground.span=2;
editor.facadeCellApply();
assert.equal(editor.facadeDraft.ground.filter(g=>g.kind==='door').length,1,'shortening does not duplicate an assembly');
console.log('facade editor slot/layer isolation OK');
'''
    subprocess.run(['node', '-e', script], check=True)


if __name__ == '__main__':
    main()
