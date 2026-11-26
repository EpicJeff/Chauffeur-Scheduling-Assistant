"""Run the actual director JS: a no-op stops paid calls after logging its notes."""
import json
from pathlib import Path
import subprocess

source=(Path(__file__).resolve().parents[1]/'static/twin/twin_director.js').read_text(encoding='utf-8')
script='''
import assert from 'node:assert/strict';
const {runDirector} = await import('data:text/javascript;base64,'+Buffer.from(SOURCE).toString('base64'));
const view={capture:async()=>['data:image/png;base64,stub'],rebuild:async()=>{}};
let calls=0,rounds=0,notes=[];
await runDirector(view,{base:7,cameras:['front'],critique:async()=>{calls++;return {round:7,done:false,notes:['Nothing was saved.']};},
  onRound:async()=>{rounds++;},log:text=>notes.push(text)});
assert.equal(calls,1);assert.equal(rounds,1);assert(notes.some(x=>x.includes('Nothing was saved')));
calls=0;
await runDirector(view,{base:7,cameras:['front'],critique:async()=>({round:7+(++calls),done:false})});
assert.equal(calls,5);
console.log('PASS no-op costs one call; changing rounds retain the five-round cap');
'''.replace('SOURCE',json.dumps(source))
subprocess.run(['node','--input-type=module','-e',script],check=True)
