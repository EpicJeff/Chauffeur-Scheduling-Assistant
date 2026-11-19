"""Slice 4 shell: rendered control homes and real JS entry points, no browser."""
from html.parser import HTMLParser
from pathlib import Path
import re
import sys

from jinja2 import DictLoader, Environment
from twin_live_node_rig import run
from test_twin_editor_history_js import STUBS

ROOT = Path(__file__).resolve().parents[1]
LABELS = dict(zip(
    'select move rotate scale draw-room draw-wall split-room add-door add-window add-anchor add-stair add-solar-zone add-meter add-electric-panel add-charger add-parking roof add-level delete undo redo sheet library add-effect ground'.split(),
    ['Select', 'Move', 'Turn', 'Scale', 'Draw room', 'Draw wall', 'Split room', 'Add door', 'Add window', 'Add anchor', 'Add stair', 'Add solar zone', 'Add meter', 'Add electric panel', 'Add charger', 'Add parking spot', 'Roof', 'Add floor', 'Delete', 'Undo', 'Redo', 'Sheet', 'Library', 'Add effect', 'Ground and yard']))


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes, self.stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        node = {'tag': tag, 'attrs': attrs, 'text': '', 'parent': self.stack[-1] if self.stack else None}
        self.nodes.append(node)
        if tag not in ['meta', 'link', 'input', 'img', 'br', 'hr', 'source']:
            self.stack.append(len(self.nodes) - 1)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[i]]['tag'] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack:
            self.nodes[self.stack[-1]]['text'] += data

    def by_id(self, id):
        rows = [n for n in self.nodes if n['attrs'].get('id') == id]
        assert len(rows) == 1, f'{id}: exactly one node, found {len(rows)}'
        return rows[0]

    def inside(self, node, id):
        while node['parent'] is not None:
            node = self.nodes[node['parent']]
            if node['attrs'].get('id') == id:
                return True
        return False


def page():
    source = (ROOT / 'templates/house_editor.html').read_text(encoding='utf-8')
    source = re.sub(r"\{% include .*?%\}", '', source)
    env = Environment(loader=DictLoader({'page': source}))
    env.filters['ver'] = lambda s: s
    return Page(env.get_template('page').render(request={'url': {'path': '/house/editor'}},
                twin_manifest={}, twin_object_schema={}, twin_modules=lambda: []))


def test_homes(p):
    p.by_id('editor-toolbar')
    for tool, name in LABELS.items():
        node = p.by_id('rail-' + tool)
        assert p.inside(node, 'editor-toolbar'), tool
        assert node['attrs'].get('aria-label', node['text'].strip()) == name, tool
        assert node['attrs'].get('title') == name, tool
    groups = [n['attrs']['data-toolbar-group'] for n in p.nodes if 'data-toolbar-group' in n['attrs']]
    assert groups == ['menu', 'house', 'save', 'select', 'structure', 'yard', 'fixtures', 'measure', 'delete', 'history', 'sheet', 'floor', 'view'], groups
    for tool in ['add-meter', 'add-electric-panel', 'add-charger', 'add-parking']:
        assert p.inside(p.by_id('rail-' + tool), 'editor-equipment-menu')
    for id in ['editor-status', 'editor-save-state']:
        assert p.inside(p.by_id(id), 'editor-statusbar'), id
    for id in ['editor-chip', 'editor-check-step', 'editor-resume', 'editor-stop', 'editor-steps']:
        assert p.inside(p.by_id(id), 'editor-genbar'), id
    assert 'hidden' in p.by_id('editor-genbar')['attrs']
    assert p.inside(p.by_id('editor-cameras'), 'editor-view-menu')
    assert p.inside(p.by_id('place-steps'), 'place-view')
    for id in ['draw-tools', 'device-tools', 'roof-tools']:
        assert p.inside(p.by_id(id), 'editor-statusbar'), id
    print('  ok rendered controls retain ids, names, groups, and status/generation homes')


DRIVER = r"""
let passed=0;
const test=async(name,fn)=>{try{await fn();passed++;console.log('  ok '+name);}catch(e){console.error('  FAIL '+name+'\n'+e.stack);process.exitCode=1;}};
const el=id=>document.getElementById(id);
// Use the rendered Jinja tree, so a runtime lookup sees the moved real node.
const nodes=config.nodes.map(n=>document.createElement(n.tag));
config.nodes.forEach((n,i)=>{for(const [k,v] of Object.entries(n.attrs))nodes[i].setAttribute(k,v??'');
 if(!['script','style'].includes(n.tag))nodes[i].textContent=n.text;
 (n.parent===null?document.body:nodes[n.parent]).append(nodes[i]);});
await test('Cmd and Ctrl history preserve field/modal guards',async()=>{
 const {createHistory}=await import(file('static/twin/editor/history.js'));
 let round=1,reverts=[];
 window.showGlobalAlert=()=>{};
 globalThis.fetch=window.fetch=async(_,init)=>{reverts.push(JSON.parse(init.body).round);return {ok:true,status:200,text:async()=>JSON.stringify({round:++round})};};
 const abort=new AbortController(),h=createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>true,refresh:async()=>{},signal:abort.signal});
 await h.perform(async()=>{round=2;});
 const send=(target,key,options={})=>target.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,...options}));
 send(document.body,'z',{metaKey:true});await wait(20);assert.deepEqual(reverts,[1]);
 send(document.body,'Z',{metaKey:true,shiftKey:true});await wait(20);assert.deepEqual(reverts,[1,2]);
 const input=document.createElement('input');document.body.append(input);
 send(input,'z',{metaKey:true});send(document.body,'z',{metaKey:true,altKey:true});await wait(20);assert.equal(reverts.length,2);
 const modal=document.createElement('dialog');modal.setAttribute('open','');document.body.append(modal);
 send(document.body,'z',{metaKey:true});await wait(20);assert.equal(reverts.length,2);modal.remove();
 send(document.body,'z',{ctrlKey:true});await wait(20);assert.deepEqual(reverts,[1,2,1]);
 send(document.body,'y',{ctrlKey:true});await wait(20);assert.deepEqual(reverts,[1,2,1,2]);abort.abort();
});
await test('Measure clicks snap, Shift is free, camera redraws, Esc and disarm clear',async()=>{
 const {createMeasure}=await import(file('static/twin/editor/measure.js'));
 const canvas=document.createElement('canvas'),layer=document.createElement('div');document.body.append(canvas,layer);
 const controls=new EventTarget();controls.enabled=true;
 const view={renderer3:{domElement:canvas},controls,state:{view:'b:L1'},
  floorAt:(x,y)=>[x,y],screenOfFloor:(x,y)=>[x*10,y*10]};
 const plan={buildings:[{id:'b',levels:[{id:'L1',elevation:0}],joints:[{level:'L1',at:[0,0]},{level:'L1',at:[3,4]}],walls:[],anchors:[]}]};
 const before=JSON.stringify(plan),m=createMeasure({view,getPlan:()=>plan,layer});
 const click=(x,y,shiftKey=false)=>{canvas.dispatchEvent(new PointerEvent('pointerdown',{clientX:x,clientY:y,pointerId:8,button:0,shiftKey,bubbles:true}));
  canvas.dispatchEvent(new PointerEvent('pointerup',{clientX:x,clientY:y,pointerId:8,button:0,shiftKey,bubbles:true}));};
 m.arm();assert.equal(m.active(),true);click(.03,.04);click(3.01,4.01);
 assert.match(layer.textContent,/5.*0/);assert.equal(layer.querySelector('line').getAttribute('x1'),'0');
 view.screenOfFloor=(x,y)=>[x*20,y*20];controls.dispatchEvent(new Event('change'));
 assert.equal(layer.querySelector('line').getAttribute('x2'),'60');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 assert.equal(m.active(),false);assert.equal(layer.textContent,'');assert.equal(layer.querySelector('line'),null);
 m.arm();click(.03,.04,true);click(3.01,4.01,true);
 assert.equal(layer.querySelector('line').getAttribute('x1'),'0.6');m.disarm();assert.equal(layer.children.length,0);
 // A camera drag is not a measured point and never disables navigation.
 m.arm();canvas.dispatchEvent(new PointerEvent('pointerdown',{clientX:0,clientY:0,pointerId:9,button:0}));
 canvas.dispatchEvent(new PointerEvent('pointerup',{clientX:10,clientY:10,pointerId:9,button:0}));click(3,4);
 assert.equal(layer.querySelector('line'),null);assert.equal(controls.enabled,true);
 // Crossing the click threshold stays navigation even after returning.
 m.disarm();m.arm();canvas.dispatchEvent(new PointerEvent('pointerdown',{clientX:0,clientY:0,pointerId:9,button:0}));
 canvas.dispatchEvent(new PointerEvent('pointermove',{clientX:10,clientY:10,pointerId:9,button:0}));
 canvas.dispatchEvent(new PointerEvent('pointerup',{clientX:0,clientY:0,pointerId:9,button:0}));click(3,4);
 assert.equal(layer.querySelector('line'),null);
 m.disarm();m.arm();
 for(const pointerId of [9,10])canvas.dispatchEvent(new PointerEvent('pointerdown',{clientX:0,clientY:0,pointerId,button:0}));
 for(const pointerId of [9,10])canvas.dispatchEvent(new PointerEvent('pointerup',{clientX:0,clientY:0,pointerId,button:0}));
 click(3,4);assert.equal(layer.querySelector('line'),null);
 assert.equal(JSON.stringify(plan),before);m.disarm();
});
await test('one shared cancel handler preserves fixture Done and device cancellation',async()=>{
 const {createDevicePlacement}=await import(file('static/twin/editor/device_placement.js'));
 const THREE=await import('three'),canvas=document.createElement('canvas');document.body.append(canvas);
 const abort=new AbortController(),ops=[],controls=new EventTarget();controls.enabled=true;
 const plan={buildings:[],site:{},light_fixtures:{}},view={renderer3:{domElement:canvas},scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(),controls};
 const placement=createDevicePlacement({view,tools:{haLink:{setPlacement(){}},setTool(){},select(){},selection:()=>({})},
  library:{surfaceAt:()=>null,ground:e=>[e.clientX,e.clientY]},getPlan:()=>plan,op:async o=>ops.push(o),canEdit:()=>true,signal:abort.signal,prepare(){}});
 const cancel=el('device-cancel');assert.equal(cancel.__listeners.filter(l=>l.type==='click').length,1);
 placement.arm({device_id:'d',name:'Lamp'},'wall');await press(cancel);assert.equal(el('device-tools').hidden,true);
 assert.equal(placement.pointerArmedDown({button:0,clientX:2,clientY:2,pointerId:1}),false);
 const host=document.createElement('div');document.body.append(host);
 placement.drawFixtures(host,{device_id:'d',entity_id:'light.a',entities:['light.a'],name:'Lamp',kind:'light'});
 await press(host.querySelector('button'));
 const add=el('piece-card').querySelectorAll('button').find(n=>n.textContent==='Add line fixture');await press(add);
 assert.equal(cancel.textContent,'Done');
 for(const x of [2,8]){const e={button:0,clientX:x,clientY:4,pointerId:3};assert.ok(placement.pointerArmedDown(e));await placement.pointerUp(e);}
 await press(cancel);assert.equal(ops.length,1);assert.equal(ops[0].op,'add_light_fixture');
 assert.equal(ops[0].fixture.path.length,2);assert.equal(cancel.__listeners.filter(l=>l.type==='click').length,1);
 abort.abort();
});
await test('real editor boot shows generation bar only for running, paused or resumable work',async()=>{
 location.search='?test=1';
 let build=null;const buildWrites=[];
 const plan={buildings:[{id:'b',name:'Our house',levels:[],walls:[],rooms:[],roofs:[]}],site:{}};
 globalThis.editorView={scene:{},state:{},dispose(){},setTime(){},setUnlit(){},rebuild:async()=>{}};
 const response=body=>({ok:true,status:200,text:async()=>JSON.stringify(body)});
 globalThis.fetch=window.fetch=async (url,init={})=>{
  const path=String(url).split('api/house/')[1];
  if(path==='editor/sheets')return response({sources:[],page_roles:[],place:{buildings:[{id:'b'}]}});
  if(path==='twin/kit/modern_farmhouse')return response({});
  if(path==='editor/state')return response({plan,model:plan,rounds:[],cost:{},build:build?.id??null});
  if(path==='editor/session')return response({});
  if(path?.startsWith('editor/build/')) {
   if(init.method==='POST'){buildWrites.push(path);build.state=path.endsWith('/resume')?'running':'stopped';}
   return response(build);
  }
  throw Error('unexpected request '+path);
 };
 const stubs='data:text/javascript,'+encodeURIComponent(config.stubs.replace('CARDS_URL',file('static/twin/editor/cards.js'))
  .replace('dismissed:()=>false','dismissed:()=>true')
  .replace('export const createChecks=()=>({sync(){},dismiss(){}});','export const createChecks=()=>({sync(){},dismiss(){},show(){globalThis.checkShown=true;}});')
  .replace("export const createPlace=()=>({sync(){},isOpen:()=>false});","export const createPlace=()=>({sync(){},close(){},isOpen:()=>false,open(name){globalThis.openedPlaceStep=name;}});"));
 registerHooks({resolve(spec,ctx,next){if(ctx.parentURL===file('static/twin/editor/editor.js')&&!['./api.js','./history.js','./lighting.js','./edit_queue.js','./local_ops.js','./icons.js','./steps.js'].includes(spec))return {url:stubs,shortCircuit:true};return next(spec,ctx);}});
 const {boot}=await import(file('static/twin/editor/editor.js'));await boot();assert.ok(window.__editor.ready);
 assert.equal(el('editor-genbar').hidden,true);
 for(const step of ['Your files','Your lot','Build','Link to Home Assistant']) {
  await press(el('place-steps').querySelectorAll('button').find(b=>b.dataset.step===step));assert.equal(globalThis.openedPlaceStep,step);
 }
 for(const state of ['running','paused','stopped','checkpoint','done','failed']){
  build={id:'build',state,steps:[],events:[]};await window.__editor.pollNow(true);
  assert.equal(el('editor-genbar').hidden,!['running','paused','stopped','checkpoint'].includes(state),state);
 }
 build={id:'build',state:'stopped',steps:[],events:[]};await window.__editor.pollNow(true);
 await press(el('editor-resume'));assert.equal(window.__editor.build().state,'running');assert.equal(el('editor-genbar').hidden,false);
 await press(el('editor-stop'));assert.equal(window.__editor.build().state,'stopped');assert.equal(el('editor-resume').hidden,false);
 assert.deepEqual(buildWrites,['editor/build/build/resume','editor/build/build/stop']);
 build={id:'build',state:'paused',pause:{kind:'outline',step:'s'},steps:[],events:[]};await window.__editor.pollNow(true);
 assert.equal(el('editor-check-step').hidden,false);await press(el('editor-check-step'));assert.equal(globalThis.checkShown,true);
 build=null;await window.__editor.pollNow(true);assert.equal(el('editor-genbar').hidden,true);
 assert.ok(el('rail-select').querySelector('svg'));assert.equal(el('rail-select').getAttribute('aria-label'),'Select');
 assert.equal(el('editor-house-name').textContent,'Our house');
 window.dispatchEvent(new Event('pagehide'));
});
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
console.log(`${passed}/4 shell runtime checks passed`);process.exit(process.exitCode||0);
"""


if __name__ == '__main__':
    p = page()
    failed = False
    try:
        test_homes(p)
    except AssertionError as e:
        print(f'  FAIL control homes: {e}')
        failed = True
    result = run(DRIVER, {'nodes': p.nodes, 'stubs': STUBS}, timeout=50)
    sys.exit(1 if failed or result else 0)
