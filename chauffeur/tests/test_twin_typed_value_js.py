"""Typed precision entry exercised under node, without a browser."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_drag_js import DRIVER as DRAG_DRIVER

ROOT = Path(__file__).resolve().parents[1]
DRIVER = DRAG_DRIVER.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
let focused = null;
Element.prototype.focus = function(){focused=this;document.activeElement=this;};
Element.prototype.blur = function(){if(focused===this){focused=null;document.activeElement=null;}};
const {createTypedValue}=await import(file('static/twin/editor/typed_value.js'));
const host=new Element(), box=createTypedValue(host);
const input=host.children[0];
const key=k=>box.key({key:k,preventDefault(){},ctrlKey:false,metaKey:false,altKey:false});
box.show('length',3.5,[20,30]);
assert.equal(input.value,`3' 6"`);assert.equal(focused,null);assert.equal(box.editing(),false);
assert.equal(key('a'),null);
assert.equal(key('1'),'typing');assert.equal(focused,input);
assert.equal(key('2'),'typing');assert.equal(key('Enter'),'commit');assert.equal(box.value(),12);
box.hide();assert.equal(input.hidden,true);assert.equal(box.value(),null);assert.equal(focused,null);
box.show('length',0);
for(const k of `4'6"`)assert.equal(key(k),'typing');
assert.equal(key('Enter'),'commit');assert.equal(box.value(),4.5);
box.show('length',99,[30,40]);assert.equal(box.value(),4.5,'pointer moves preserve entry');
assert.equal(key('Backspace'),'typing');assert.equal(input.value,`4'6`);
assert.equal(key('Escape'),'cancel');box.hide();
box.show('angle',22.4);assert.equal(input.value,'22°');
assert.equal(key('-'),'typing');assert.equal(key('Enter'),'typing','invalid input cannot release');
assert.equal(key('3'),'typing');assert.equal(key('0'),'typing');assert.equal(box.value(),-30);
box.hide();box.show('factor',1.25);assert.equal(input.value,'1.25');
assert.equal(key('Escape'),'cancel');box.hide();assert.equal(key('1'),null);
console.log('typed value: formatting, focus, entry, parsing, Backspace, invalid input and Esc passed');
"""


def run():
    with tempfile.TemporaryDirectory(prefix='typed_value_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': {}}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
