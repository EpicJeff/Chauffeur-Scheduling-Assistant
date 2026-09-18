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
console.log('facade editor slot/layer isolation OK');
'''
    subprocess.run(['node', '-e', script], check=True)


if __name__ == '__main__':
    main()
